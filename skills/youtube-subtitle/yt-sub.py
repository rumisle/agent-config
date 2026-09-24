#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["yt-dlp[curl-cffi,default]"]
# ///
"""Download YouTube subtitles. Usage: yt-sub.py [-l LANG] [-f txt|srt|vtt] [-L] URL"""

import argparse, re, sys, urllib.request
from yt_dlp import YoutubeDL

p = argparse.ArgumentParser(description="Download YouTube subtitles")
p.add_argument("url")
p.add_argument("-l", help="language code (default: auto-detect)")
p.add_argument("-f", default="txt", choices=["txt", "srt", "vtt"], help="output format (default: txt)")
p.add_argument("-o", default="-", help="output path, '-' for stdout (default), dir for auto-named")
p.add_argument("-L", action="store_true", help="list available subtitles")
args = p.parse_args()

with YoutubeDL({"quiet": True}) as ydl:
    info = ydl.extract_info(args.url, download=False)

uploaded = {k: v for k, v in info.get("subtitles", {}).items() if k != "live_chat"}
auto = info.get("automatic_captions", {})

if args.L:
    if uploaded: print(f"Uploaded: {' '.join(uploaded)}")
    if auto: print(f"Auto-generated: {' '.join(sorted(auto))}")
    sys.exit(0)

# Pick source and language
if args.l:
    if args.l in uploaded:   subs, lang = uploaded, args.l
    elif args.l in auto:     subs, lang = auto, args.l
    else: sys.exit(f"Error: no subtitles for '{args.l}'")
elif uploaded: subs, lang = uploaded, next(iter(uploaded))
elif auto:    subs, lang = auto, sorted(auto, key=len)[0]
else: sys.exit("Error: no subtitles available")

# Find URL for desired format
dl_fmt = "srt" if args.f == "txt" else args.f
url = next((e["url"] for e in subs[lang] if e.get("ext") == dl_fmt), None)
if not url: sys.exit(f"Error: format '{dl_fmt}' not available")

data = urllib.request.urlopen(url).read().decode()

if args.f == "txt":
    lines = data.splitlines()
    data = "\n".join(l for l in lines if l and not re.match(r'^\d+$', l) and not re.match(r'^\d\d:', l))

from pathlib import Path
dest = Path(args.o)
if args.o == "-":
    sys.stdout.write(data)
else:
    if dest.is_dir():
        title = re.sub(r'[/\\]', '_', info.get("title", "subtitle"))
        dest = dest / f"{title}.{lang}.{args.f}"
    dest.write_text(data)
    print(f"Saved: {dest}", file=sys.stderr)
