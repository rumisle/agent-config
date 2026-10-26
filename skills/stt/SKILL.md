---
name: stt
description: Transcribe audio or video to timestamped text and SRT on the local GPU. Takes a file or any URL (podcast episode page, direct mp3, YouTube, Bilibili). FireRedASR2 for Chinese (default), NVIDIA Parakeet for English and European languages. Use when the user wants a transcript of a podcast, talk, interview, or video.
---

# Speech to text

```bash
{baseDir}/stt.py INPUT [-m firered|parakeet] [-o PREFIX]
```

- `INPUT`: a local file (any format ffmpeg reads) or a URL that yt-dlp understands.
  For a podcast, the episode page usually works. If it doesn't, take the `<audio src>`
  or the feed's enclosure URL.
- `-m firered` (the default): Chinese, including Chinese with English mixed in. Adds punctuation.
- `-m parakeet`: English plus 24 European languages. Cannot do Chinese.
- Writes `PREFIX.txt` (one `[hh:mm:ss] text` line per segment) and `PREFIX.srt`.
  PREFIX defaults to the input's name, or the URL's title, in the cwd.

Self-contained: dependencies are pinned in the script header plus `stt.py.lock`, and
models are pinned by revision and downloaded on first use into the Hugging Face cache.
The first run downloads several GB (about 5.5 GB for FireRed, 2.5 GB for Parakeet), so run it as a bgjob.
After that, an hour of audio takes about a minute on the GPU.

Output is raw ASR: expect homophone errors in names and technical terms
(for example, cannon → 开弄). Say so when quoting it.
