#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["requests"]
# ///
"""Classify text with Pangram's AI-text detector (sliding window endpoint).

Auth via two env vars, both grabbed from your logged-in https://www.pangram.com
browser session:
  - PANGRAM_SESSION_ID  -> the `sessionid` cookie value
  - PANGRAM_CSRF_TOKEN  -> the `X-CSRFToken` header value (the API uses
                           Django's session-bound CSRF, so the header alone
                           suffices; no csrftoken cookie needed)

Reads text from positional args (joined like `echo`) or from stdin when no
args are given. Pangram requires ~50+ words for an accurate prediction.
"""

import argparse
import json
import os
import sys

import requests


API_URL = "https://web.pangram.com/api/classify-text-sliding-window/"
DEFAULT_SOURCE = "product"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


def classify(
    text: str,
    *,
    session_id: str,
    csrf_token: str,
    distinct_id: str,
    source: str,
    logging: bool,
    timeout: int,
) -> dict:
    payload = {
        "text": text,
        "source": source,
        "logging": logging,
        "distinctId": distinct_id,
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.pangram.com",
        "Referer": "https://www.pangram.com/",
        "User-Agent": DEFAULT_USER_AGENT,
        "X-CSRFToken": csrf_token,
    }
    cookies = {"sessionid": session_id}

    resp = requests.post(
        API_URL,
        json=payload,
        headers=headers,
        cookies=cookies,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise SystemExit(
            f"pangram: HTTP {resp.status_code}: {resp.text[:1000]}"
        )
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"pangram: non-JSON response: {exc}: {resp.text[:1000]}"
        ) from exc


def read_text(args_text: list[str]) -> str:
    if args_text:
        return " ".join(args_text)
    if sys.stdin.isatty():
        raise SystemExit(
            "pangram: no text provided. Pass as args or pipe via stdin."
        )
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Classify text with Pangram (AI-vs-human, sliding-window endpoint)."
        ),
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="Text to classify. If omitted, read from stdin (echo-style).",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("PANGRAM_SESSION_ID"),
        help="sessionid cookie (default: env PANGRAM_SESSION_ID).",
    )
    parser.add_argument(
        "--csrf-token",
        default=os.environ.get("PANGRAM_CSRF_TOKEN"),
        help="X-CSRFToken header value (default: env PANGRAM_CSRF_TOKEN).",
    )
    parser.add_argument(
        "--distinct-id",
        default=os.environ.get("PANGRAM_DISTINCT_ID"),
        help="Analytics distinctId (default: env PANGRAM_DISTINCT_ID).",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"`source` field in request body (default: {DEFAULT_SOURCE!r}).",
    )
    parser.add_argument(
        "--no-logging",
        dest="logging",
        action="store_false",
        help="Set request `logging=false` (default: true, matches the web UI).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds (default: 120).",
    )
    args = parser.parse_args()

    if not args.session_id:
        raise SystemExit("pangram: set PANGRAM_SESSION_ID or pass --session-id.")
    if not args.csrf_token:
        raise SystemExit("pangram: set PANGRAM_CSRF_TOKEN or pass --csrf-token.")
    if not args.distinct_id:
        raise SystemExit("pangram: set PANGRAM_DISTINCT_ID or pass --distinct-id.")

    text = read_text(args.text).strip()
    if not text:
        raise SystemExit("pangram: empty text input.")

    result = classify(
        text,
        session_id=args.session_id,
        csrf_token=args.csrf_token,
        distinct_id=args.distinct_id,
        source=args.source,
        logging=args.logging,
        timeout=args.timeout,
    )

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
