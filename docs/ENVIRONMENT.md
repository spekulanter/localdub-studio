# Environment verification (Milestone 0)

Measured 2026-10-28 on the **laptop**. The desktop (RTX 5070 Ti 16 GB, Ryzen 7 5700X3D) has not
been tested yet.

| Item | Result |
|---|---|
| OS | Windows 11 (10.0.26300), Claude Code driving it from WSL2 Ubuntu 26.04 |
| CPU / RAM | i7-13700HX (hybrid P/E cores), 32 GB |
| GPU | RTX 5060 Laptop GPU, 8 GB, compute capability 12.0 (Blackwell sm_120), driver 621.01, CUDA UMD 13.5 |
| Python | 3.12.15 (uv-managed, Windows). 3.14 avoided: ML wheels lag behind |
| uv | 0.12.23 (Windows) |
| FFmpeg | 9.0.1 full build (gyan.dev, winget) with NVENC, rubberband, loudnorm |
| CTranslate2 | 4.8.4, sees 1 CUDA device; compute types bf16/fp16/fp32/int8/int8_fp16/int8_bf16/int8_fp32 |
| CUDA libs | `nvidia-cublas-cu12` 12.9.2.10 + `nvidia-cudnn-cu12` 9.27.0.42 wheels; no system CUDA toolkit required |
| ONNX Runtime | 1.31.1, CPU provider (no GPU EP, by design) |
| PyTorch | **not installed / not needed in M0** |
| Ollama | not installed at the time of writing; `winget install --id Ollama.Ollama -e` |

Run `uv run localdub-m0 env` for a fresh JSON report.

## faster-whisper on Blackwell
- `large-v3`, `cuda`/`float16` loads and runs on sm_120 with no fallback needed.
- VRAM: 3.9 GB after load, 4.0 GB during inference, about 0.1 GB after `close()`.
- Speed on a 16.6 s English clip (beam 5, VAD, word timestamps): first call 4.0 s (CUDA init),
  then **0.96 s warm (RTF 0.058)**.
- Transcript of a synthetic English clip was word-perfect, with plausible word timestamps.
- First model download: about 3 GB, 102 s. Hugging Face symlinks are unsupported without
  Windows Developer Mode, so files are copied (more disk use, harmless).

### Issue: PyAV incompatibility
faster-whisper 1.2.1 calls `av.open(..., metadata_errors=...)`, which PyAV 19 rejects. We decode
the already-extracted 16 kHz WAV with soundfile and pass a NumPy array, so PyAV is never used.

## Supertonic 3 (Slovak)
- `supertonic` 1.3.1; weights `Supertone/supertonic-3` at the package-pinned revision
  `724fb5ab…`, about 400 MB, downloaded into `models/supertonic3`.
- All Slovak characters are supported (validated: á ä č ď é í ĺ ľ ň ó ô ŕ š ť ú ý ž).
- 10 voices: F1–F5, M1–M5. Sample rate 44.1 kHz.
- `speed` scales duration almost linearly: speed 1.25 gives a 1.24× shorter clip.
- Upstream was archived after a July 2026 notice: no further development or support. Keep the
  package and revision pinned.

### Issue: Windows power throttling (EcoQoS)
Without a foreground window, Windows put the process at low QoS. Supertonic then took 7–28 s for
2–6 s of audio, getting slower call by call. With `SetProcessInformation(ProcessPowerThrottling)`
opt-out (`localdub/core/platform.py`, called at CLI start), 6.4 s of audio takes **1.4 s** on CPU
with 8 threads. The M1 server must call this at startup too.

### Thread count
ONNX Runtime's default ("auto" = all 24 logical cores incl. E-cores) is ~2.5× slower. Measured
for 4.74 s of Slovak audio (best of 3, throttling disabled): auto 2.09 s, 2 threads 0.86 s,
3 → 0.82 s, **4 → 0.82 s**, 6 → 0.87 s, 8 → 0.97 s. Default `LOCALDUB_TTS_THREADS=4` (RTF ≈ 0.17).
Re-measure on the desktop (M1).

### Determinism
Re-synthesizing the same text gives slightly different lengths (3.40 s vs 3.37 s), so TTS
output is not bit-reproducible; checkpoints, not re-synthesis, keep runs stable.

## Ollama translation
Ollama is installed natively on Windows and listens on `127.0.0.1:11434`. WSL2 is not used.
Pulled: `translategemma:4b` (3.3 GB) and `qwen3:8b` (5.2 GB). Default: translategemma:4b
(see docs/QUALITY.md). A model is unloaded (`keep_alive: 0`) after the translate stage, so it never
shares VRAM with Whisper. The first call after load takes 40–120 s (model load from disk).
