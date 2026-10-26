#!/usr/bin/env -S -u LD_LIBRARY_PATH uv run --script
# (system CUDA on LD_LIBRARY_PATH would shadow the pinned pip CUDA libs)
# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "fireredasr2s @ git+https://github.com/FireRedTeam/FireRedASR2S@4e7d9aaf4482a47cec1724807026b9b151926eb5",
#   "torch==2.10.0",
#   "torchaudio==2.10.0",
#   "onnx-asr==0.12.0",
#   "onnxruntime-gpu[cuda,cudnn]==1.30.0",
#   "huggingface-hub==1.33.0",
#   "kaldi-native-fbank==1.22.3",  # missing from upstream deps
#   "soundfile==0.13.1",
#   "yt-dlp==2026.10.21",
# ]
#
# [[tool.uv.index]]
# name = "pytorch-cu130"
# url = "https://download.pytorch.org/whl/cu130"
# explicit = true
#
# [tool.uv.sources]
# torch = { index = "pytorch-cu130" }
# torchaudio = { index = "pytorch-cu130" }
# ///
"""Speech to text, local GPU. Stateless: models live in the Hugging Face cache.

  stt.py INPUT [-m firered|parakeet] [-o PREFIX]

INPUT    audio/video file, or any URL yt-dlp understands (podcast page,
         direct mp3, YouTube, Bilibili...).
-m       firered  (default) Chinese/Chinese-English, FireRedASR2-AED + punc
         parakeet NVIDIA Parakeet TDT 0.6B v3, English + 24 European langs
-o       output prefix (default: input name in cwd)

Writes PREFIX.txt ("[hh:mm:ss] line" per segment) and PREFIX.srt.
"""
import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from huggingface_hub import snapshot_download

# Pinned model revisions (Hugging Face commit SHAs).
MODELS = {
    "aed": ("FireRedTeam/FireRedASR2-AED", "2304afed56eacfee6256dee5937ed22ffa0b64ec", None),
    "vad": ("FireRedTeam/FireRedVAD", "7990aaccc6b7aec1e527743bd30201f2c4a03b8c", None),
    "punc": ("FireRedTeam/FireRedPunc", "e448fd967f44182a1c323cc30f5d89f2400c28da",
             ["*.txt", "*.yaml", "*.tar", "out_dict", "chinese-lert-base/*.json",
              "chinese-lert-base/*.txt", "chinese-lert-base/*.bin"]),
    "parakeet": ("istupakov/parakeet-tdt-0.6b-v3-onnx", "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce",
                 ["config.json", "vocab.txt", "nemo128.onnx", "decoder_joint-model.onnx",
                  "encoder-model.onnx", "encoder-model.onnx.data"]),
    "silero": ("istupakov/silero-vad-onnx", "b3e3ee3cce4c11ceb63b1a0b229d916069c1ddf6",
               ["config.json", "silero_vad.onnx"]),
}


def model(key):
    repo, rev, pats = MODELS[key]
    return snapshot_download(repo, revision=rev, allow_patterns=pats)


def fetch(src, tmp):
    """Return a path to the source audio, downloading if it's a URL."""
    if "://" not in src:
        return Path(src), Path(src).stem
    subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-playlist",
                    "-f", "bestaudio/best", "-o", f"{tmp}/dl.%(ext)s", src], check=True)
    title = subprocess.run([sys.executable, "-m", "yt_dlp", "--no-playlist", "--print",
                            "%(title)s", src], capture_output=True, text=True).stdout.strip()
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in title)[:80] or "audio"
    return next(Path(tmp).glob("dl.*")), stem


def to_wav(path, tmp):
    wav = f"{tmp}/in.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(path),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav], check=True)
    return wav


def firered(wav):
    """-> [(start_s, end_s, text)]. bf16 ASR + length-bucketed batches (~100x RT)."""
    import logging
    logging.disable(logging.INFO)
    import transformers
    transformers.logging.set_verbosity_error()
    from fireredasr2s import FireRedAsr2System, FireRedAsr2SystemConfig

    cfg = FireRedAsr2SystemConfig()
    cfg.vad_model_dir = f"{model('vad')}/VAD"
    cfg.asr_model_dir = model("aed")
    cfg.punc_model_dir = model("punc")
    cfg.enable_lid = False
    cfg.asr_config.use_half = True
    cfg.asr_config.beam_size = 3        # beam 1 is faster but mangles terms
    cfg.asr_batch_size = 10**9          # hand everything to the bucketing wrapper
    cfg.punc_batch_size = 32
    s = FireRedAsr2System(cfg)

    orig = s.asr.transcribe

    def bucketed(uttids, wavs, bs=8):   # sort by length: 133% -> 10% padding
        order = sorted(range(len(wavs)), key=lambda i: len(wavs[i][1]))
        out = {}
        for i in range(0, len(order), bs):
            idx = order[i:i + bs]
            for r in orig([uttids[j] for j in idx], [wavs[j] for j in idx]):
                out[r["uttid"]] = r
        return [out[u] for u in uttids if u in out]  # too-short segs are dropped

    s.asr.transcribe = bucketed
    r = s.process(wav)
    return [(x["start_ms"] / 1000, x["end_ms"] / 1000, x["text"]) for x in r["sentences"]]


def parakeet(wav):
    """-> [(start_s, end_s, text)], cues split at sentence ends / pauses."""
    import onnx_asr
    import onnxruntime as ort

    ort.preload_dlls()
    asr = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", model("parakeet"),
                              providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    vad = onnx_asr.load_vad("silero", model("silero"), providers=["CPUExecutionProvider"])
    asr = asr.with_vad(vad, max_speech_duration_s=30, min_silence_duration_ms=300,
                       speech_pad_ms=150).with_timestamps()
    words = []
    for seg in asr.recognize(wav):
        for tok, t in zip(seg.tokens, seg.timestamps):
            t += seg.start
            if tok[:1] in (" ", "\u2581") or not words:
                words.append([tok.lstrip(" \u2581"), t, t])
            else:
                words[-1][0] += tok
            words[-1][2] = t + 0.08
    words = [w for w in words if w[0]]
    cues, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x[0] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (not nxt or nxt[1] - w[2] > 0.8 or len(text) + len(nxt[0]) > 84
                or (w[0][-1] in ".?!" and len(text) > 20)
                or (w[0][-1] == "," and len(text) > 55) or nxt[2] - cur[0][1] > 7):
            cues.append((cur[0][1], min(w[2], nxt[1] if nxt else w[2]), text))
            cur = []
    return cues


def ts(sec, srt=False):
    ms = round(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}" if srt else f"{h:02}:{m:02}:{s:02}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-m", "--model", choices=["firered", "parakeet"], default="firered")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        src, stem = fetch(a.input, tmp)
        wav = to_wav(src, tmp)
        t0 = time.time()
        segs = (firered if a.model == "firered" else parakeet)(wav)
        el = time.time() - t0
    if not segs:
        sys.exit("stt: no speech recognized (see errors above)")

    prefix = Path(a.out or stem)
    prefix.with_suffix(".txt").write_text(
        "".join(f"[{ts(s)}] {t}\n" for s, _, t in segs))
    prefix.with_suffix(".srt").write_text(
        "".join(f"{i}\n{ts(s, 1)} --> {ts(e, 1)}\n{t}\n\n"
                for i, (s, e, t) in enumerate(segs, 1)))
    dur = segs[-1][1] if segs else 0
    print(f"{prefix}.txt  {prefix}.srt  ({len(segs)} segs, {dur / 60:.0f} min audio "
          f"in {el:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
