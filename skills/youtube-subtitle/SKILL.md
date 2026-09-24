---
name: youtube-subtitle
description: Download YouTube video subtitles. Supports uploaded and auto-generated captions in txt, srt, or vtt format. Use when the user needs to get subtitles or transcripts from YouTube videos.
---

# YouTube Subtitles

Download subtitles from YouTube videos. Requires `deno` in PATH.

## Usage

```bash
# Default: auto-detect language, txt to stdout
{baseDir}/yt-sub.py 'https://www.youtube.com/watch?v=VIDEO_ID'

# List available subtitles
{baseDir}/yt-sub.py -L 'https://www.youtube.com/watch?v=VIDEO_ID'

# Specific language
{baseDir}/yt-sub.py -l en 'https://www.youtube.com/watch?v=VIDEO_ID'

# Different format
{baseDir}/yt-sub.py -f srt 'https://www.youtube.com/watch?v=VIDEO_ID'

# Save to file
{baseDir}/yt-sub.py -o output.txt 'https://www.youtube.com/watch?v=VIDEO_ID'

# Auto-named file in a directory
{baseDir}/yt-sub.py -o . 'https://www.youtube.com/watch?v=VIDEO_ID'
```

## Args

| Arg | Description | Default |
|-----|-------------|---------|
| `url` | YouTube URL (required) | - |
| `-l LANG` | Language code (`en`, `zh`, `ja`, ...) | Auto-detect (prefers uploaded over auto-generated) |
| `-f FORMAT` | Output format: `txt`, `srt`, `vtt` | `txt` |
| `-o PATH` | Output: `-` for stdout, path for file, dir for auto-named | `-` (stdout) |
| `-L` | List available subtitles and exit | - |
