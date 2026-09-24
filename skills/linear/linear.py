#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["requests"]
# ///

import argparse
import json
import os
import sys
import requests


def query(graphql: str, variables: dict | None = None) -> dict:
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        print("Error: LINEAR_API_KEY env var required", file=sys.stderr)
        print("Create one at: Settings → Security & access → Personal API keys", file=sys.stderr)
        sys.exit(1)

    payload = {"query": graphql}
    if variables:
        payload["variables"] = variables

    resp = requests.post(
        "https://api.linear.app/graphql",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if "errors" in result:
        print(json.dumps(result["errors"], indent=2), file=sys.stderr)
        sys.exit(1)

    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Query Linear GraphQL API")
    p.add_argument("query", help="GraphQL query or mutation")
    p.add_argument(
        "-v", "--variables",
        help="JSON string of variables (e.g., '{\"id\": \"abc\"}')",
        default=None,
    )
    args = p.parse_args()

    variables = json.loads(args.variables) if args.variables else None
    result = query(args.query, variables)
    print(json.dumps(result, ensure_ascii=False, indent=2))
