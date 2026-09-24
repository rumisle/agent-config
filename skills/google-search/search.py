#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["requests"]
# ///

import argparse
import json
import os
import sys
import requests

def search(query: str, country: str | None = None, language: str | None = None, 
           date_range: str | None = None, autocorrect: bool = True) -> dict:
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        sys.exit("SERPER_API_KEY env var required")
    
    payload = {"q": query}
    if country:
        payload["gl"] = country
    if language:
        payload["hl"] = language
    if date_range:
        payload["tbs"] = date_range
    if not autocorrect:
        payload["autocorrect"] = False
    
    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Google search via Serper API")
    p.add_argument("query", help="Search query")
    p.add_argument("-c", "--country", help="Country code (e.g., cn, us, jp)")
    p.add_argument("-l", "--language", help="Language code (e.g., zh-cn, en, ja)")
    p.add_argument("-t", "--time", dest="date_range", 
                   help="Date range: qdr:h (hour), qdr:d (day), qdr:w (week), qdr:m (month), qdr:y (year)")
    p.add_argument("--no-autocorrect", action="store_true", help="Disable autocorrect")
    args = p.parse_args()
    
    result = search(args.query, args.country, args.language, args.date_range, not args.no_autocorrect)
    print(json.dumps(result, ensure_ascii=False))
