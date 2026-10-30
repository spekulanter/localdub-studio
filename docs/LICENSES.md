# Third-Party Licenses

LocalDub Studio incorporates the following third-party components. This document records each component's role, version, license, key restrictions, and whether it runs locally.

---

## Summary for Distribution

| Obligation | Detail |
|---|---|
| **GPL FFmpeg** | FFmpeg 9.0.1 (full build from gyan.dev) is GPL v3. It **must** be invoked as a separate process (fork/exec), never linked into the app binary. Shipping the FFmpeg binary with the app **triggers GPL source-offer obligations**: you must provide or offer the complete corresponding source code (FFmpeg + all GPL libs incl. librubberband) under GPL v3 to anyone who receives the binary. |
| **Rubber Band (GPL)** | The Rubber Band Library is GPL v2+. It is pulled in transitively via the FFmpeg full build. Same GPL obligations as above apply — do not link; distribute only as a separate process. |
| **Gemma Terms of Use (TranslateGemma)** | TranslateGemma is governed by the **Gemma Terms of Use** (not open-source). Distribution requires: (1) include the Gemma use restrictions (Section 3.2) as enforceable downstream terms, (2) provide recipients a copy of the Gemma Terms of Use, (3) mark modified files, (4) include a Notice file pointing to `ai.google.dev/gemma/terms`. The Gemma Prohibited Use Policy is incorporated by reference. |
| **OpenRAIL-M (Supertonic 3)** | The Supertonic 3 model weights are licensed under OpenRAIL-M. The use-based restrictions in **Attachment A** (see [Supertonic section](#supertonic-3) below) must be passed to end users as enforceable terms. These restrict use for deepfakes, discrimination, medical advice, law enforcement, impersonation, harm to minors, and more. |
| **NVIDIA cuBLAS / cuDNN wheels** | Governed by the **NVIDIA Software License Agreement** (proprietary EULA). cuBLAS is redistributable as part of an application with "material additional functionality" (not stand-alone); cuDNN is **not listed** as redistributable under the standard CUDA Toolkit EULA and may require a separate agreement. Must include attribution notice. Cannot be used in critical applications (avionics, medical, autonomous vehicles) without separate agreement. |
| **libsndfile (LGPL-2.1)** | The `soundfile` Python package is BSD-3-Clause, but it wraps `libsndfile` which is **LGPL-2.1**. If you ship the libsndfile binary, you must allow relinking with a modified version of the library (LGPL §6). Distributing as a shared DLL satisfies this. |
| **Whisper weights (MIT / Apache-2.0)** | Both the Systran/faster-whisper-large-v3 (MIT) and openai/whisper-large-v3 (Apache-2.0) weights are permissive. Apache-2.0 requires preserving attribution notices. |
| **Silero VAD (MIT)** | MIT-licensed; no special obligations beyond attribution. |

---

## Active Components

### Speech Recognition

| Component | Role | Version / Revision | License | License Link | Runs Locally |
|---|---|---|---|---|---|
| faster-whisper | Whisper inference on CTranslate2 (ASR) | 1.2.1 | MIT | [PyPI](https://pypi.org/project/faster-whisper/1.2.1/) | Yes |
| CTranslate2 | Efficient inference engine | 4.8.4 | MIT | [PyPI](https://pypi.org/project/ctranslate2/4.8.4/) | Yes |
| OpenAI Whisper large-v3 weights | Original Whisper model weights | large-v3 | Apache-2.0 | [HuggingFace](https://huggingface.co/openai/whisper-large-v3) | Yes (downloaded) |
| Systran/faster-whisper-large-v3 | CTranslate2-converted Whisper weights | large-v3 | MIT | [HuggingFace](https://huggingface.co/Systran/faster-whisper-large-v3) | Yes (downloaded) |
| Silero VAD | Voice activity detection (bundled in faster-whisper) | bundled | MIT | [GitHub](https://github.com/snakers4/silero-vad) | Yes |

### Speech Synthesis (TTS)

| Component | Role | Version / Revision | License | License Link | Runs Locally |
|---|---|---|---|---|---|
| supertonic (Python pkg) | TTS inference code (ONNX Runtime) | 1.3.1 | MIT | [PyPI](https://pypi.org/project/supertonic/1.3.1/) | Yes |
| Supertone/supertonic-3 (weights) | TTS model weights (ONNX) | pinned @ `724fb5abbf5502583fb520898d45929e62f02c0b` | **OpenRAIL-M** | [HuggingFace LICENSE](https://huggingface.co/Supertone/supertonic-3/blob/main/LICENSE) | Yes (downloaded) |

> **Supertonic upstream status:** The upstream repository ([github.com/supertone-inc/supertonic](https://github.com/supertone-inc/supertonic)) was **archived on September 9, 2026** (redirects to `supertone-oss-archive/supertonic`). A service notice dated **July 23, 2026** announced no further development or official support. The Voice Builder service became inaccessible after August 31, 2026. The code and weights remain available for reference and use under their respective licenses.

#### OpenRAIL-M Attachment A — Use-Based Restrictions (Supertonic 3)

The following uses are **prohibited** under the OpenRAIL-M license for the Supertonic 3 model weights:

| Item | Restricted Use |
|---|---|
| (a) | Violating any applicable law or regulation |
| (b) | Exploiting or harming minors |
| (c) | Generating/disseminating verifiably false information to harm others |
| (d) | Generating/disseminating personal identifiable information to harm individuals |
| (e) | Generating content without expressly disclaiming it as machine-generated |
| (f) | Defaming, disparaging, or harassing others |
| (g) | Impersonating others (e.g., deepfakes) without consent |
| (h) | Fully automated decision-making that adversely affects individual legal rights |
| (i) | Discriminating or harming based on social behavior or personality characteristics |
| (j) | Exploiting vulnerabilities of specific groups to distort behavior causing harm |
| (k) | Discriminating based on legally protected characteristics |
| (l) | Providing medical advice or medical results interpretation |
| (m) | Generating information for administration of justice, law enforcement, or immigration/asylum processes |

**Distribution requirement:** These restrictions must be passed downstream to any recipient of the model or derivatives.

### Translation & LLM

| Component | Role | Version / Revision | License | License Link | Runs Locally |
|---|---|---|---|---|---|
| Ollama | Local LLM/model serving | (latest) | MIT | [GitHub](https://github.com/ollama/ollama) | Yes |
| TranslateGemma | Translation model (served via Ollama) | 4b / 12b / 27b | **Gemma Terms of Use** | [ai.google.dev/gemma/terms](https://ai.google.dev/gemma/terms) | Yes (downloaded) |
| Qwen3 8B | LLM for translation post-processing (served via Ollama) | `qwen3:8b` | Apache-2.0 | [Ollama](https://ollama.com/library/qwen3:8b) | Yes (downloaded) |

#### TranslateGemma — Available Tags (ollama.com/library/translategemma)

| Tag | Size |
|---|---|
| `latest` (= `4b`) | 3.3 GB |
| `4b` | 3.3 GB |
| `12b` | 8.1 GB |
| `27b` | 17 GB |
| `4b-it-q4_K_M` | 3.3 GB |
| `4b-it-q8_0` | 4.9 GB |
| `4b-it-bf16` | 8.6 GB |
| `12b-it-q4_K_M` | 8.1 GB |
| `12b-it-q8_0` | 13 GB |
| `12b-it-bf16` | 24 GB |
| `27b-it-q4_K_M` | 17 GB |
| `27b-it-q8_0` | 30 GB |
| `27b-it-bf16` | 55 GB |

#### Gemma Terms of Use — Key Distribution Requirements

1. Include the Gemma use restrictions (Section 3.2) as enforceable downstream terms.
2. Provide recipients a copy of the Gemma Terms of Use.
3. Mark modified files with prominent notices.
4. Include a Notice file: *"Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms"*.
5. Comply with the Gemma Prohibited Use Policy (incorporated by reference).

> **Note:** Gemma 4 uses Apache 2.0. TranslateGemma (built on Gemma 3) uses the **Gemma Terms of Use** — a custom, non-open-source license.

### Runtime / Infrastructure

| Component | Role | Version | License | License Link | Runs Locally |
|---|---|---|---|---|---|
| ONNX Runtime | Model inference runtime | 1.31.1 | MIT | [PyPI](https://pypi.org/project/onnxruntime/1.31.1/) | Yes |
| nvidia-cublas-cu12 | CUDA BLAS (GPU math) | 12.9.2.10 | **NVIDIA Proprietary EULA** | [NVIDIA EULA](https://docs.nvidia.com/cuda/eula/index.html) | Yes |
| nvidia-cudnn-cu12 | CUDA DNN (deep neural nets) | 9.27.0.42 | **NVIDIA Proprietary EULA** | [NVIDIA EULA](https://docs.nvidia.com/cuda/eula/index.html) | Yes |
| FFmpeg | Audio/video processing (full build, gyan.dev) | 9.0.1 | **GPL v3** | [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) | Yes |
| Rubber Band Library | Time-stretching (transitive via FFmpeg) | (FFmpeg build) | **GPL v2+** | [GitHub](https://github.com/breakfastquay/rubberband) | Yes |
| numpy | Numerical computing | ≥2.0, <2.6 | BSD-3-Clause (composite) | [PyPI](https://pypi.org/project/numpy/) | Yes |
| soundfile | Audio I/O (wraps libsndfile) | 0.14.0 | BSD-3-Clause | [PyPI](https://pypi.org/project/soundfile/) | Yes |
| libsndfile | Audio file I/O (native lib) | (system/bundled) | **LGPL-2.1** | [GitHub](https://github.com/libsndfile/libsndfile) | Yes |
| httpx | HTTP client | 0.28.1 | BSD-3-Clause | [GitHub](https://github.com/encode/httpx) | Yes |
| pydantic | Data validation | 2.14.1 | MIT | [PyPI](https://pypi.org/project/pydantic/2.14.1/) | Yes |
| pydantic-settings | Settings management | 2.16.2 | MIT | [PyPI](https://pypi.org/project/pydantic-settings/2.16.2/) | Yes |
| huggingface_hub | Model download / Hub access | ≥0.30, <3 | Apache-2.0 | [PyPI](https://pypi.org/project/huggingface-hub/) | Yes |

#### NVIDIA EULA — Redistribution Notes

- **cuBLAS:** Redistributable as part of an application with "material additional functionality" (not stand-alone). Must include attribution: *"This software contains source code provided by NVIDIA Corporation."* Some routines contain third-party code under Modified BSD, Apache 2.0, and MIT licenses (see EULA Attachment B).
- **cuDNN:** **Not listed** as redistributable under the standard CUDA Toolkit EULA Attachment A. May require a separate cuDNN license agreement for redistribution. Verify with NVIDIA's current terms before shipping.
- Both: Cannot be used in critical applications (avionics, medical, life support, autonomous vehicles) without separate written agreement. Cannot be reverse-engineered or targeted at non-NVIDIA platforms.

---

## Future / Optional Components (Not Yet Used)

| Component | Role (Planned) | License | License Link | Notes |
|---|---|---|---|---|
| WhisperX | Forced alignment & word-level timestamps | BSD-2-Clause | [GitHub](https://github.com/m-bain/whisperX) | Not yet integrated |
| pyannote.audio | Speaker diarization | MIT (code) | [GitHub](https://github.com/pyannote/pyannote-audio) | Code is MIT; **model weights are gated on HuggingFace** and require accepting terms (share HF info; may receive marketing emails) |
| pyannote models (segmentation-3.0 etc.) | Pretrained diarization models | MIT (gated) | [HuggingFace](https://huggingface.co/pyannote/segmentation-3.0) | Gated access — must accept conditions on HuggingFace before download |
| OpenVoice V2 | Voice cloning | MIT | [GitHub](https://github.com/myshell-ai/OpenVoice) | Not yet integrated; free for commercial use since April 2024 |
| Demucs | Source separation (music/vocals) | MIT | [GitHub](https://github.com/adefossez/demucs) | Not yet integrated |
| Piper TTS | Local TTS engine | MIT (original `rhasspy/piper`) | [GitHub](https://github.com/rhasspy/piper) | Development moved to `piper1-gpl` (GPL-3); see note below |
| piper1-gpl | Piper TTS successor | **GPL-3** | UNVERIFIED (repo returned 404 at time of writing) | GPL-3 obligations apply if used |
| sk_SK-lili voice (Piper) | Slovak voice for Piper TTS | UNVERIFIED | UNVERIFIED (model card inaccessible at time of writing) | Check HuggingFace model card before use |
| Tauri | Native desktop shell (replacing Electron) | MIT / Apache-2.0 (dual) | [GitHub](https://github.com/tauri-apps/tauri) | Not yet integrated |

> **Piper TTS license note:** The original `rhasspy/piper` repo is MIT, but development has moved to a successor repository (`piper1-gpl`) which is GPL-3. If LocalDub adopts Piper, verify which fork/version is used — the GPL-3 fork would impose source-sharing obligations.

---

## License Compatibility Notes

| Concern | Assessment |
|---|---|
| GPL components (FFmpeg, Rubber Band) | Must remain separate processes. Do not link into the proprietary app binary. Shipping binaries triggers source-offer obligations. |
| LGPL libsndfile | Distribute as a shared library (DLL) to allow relinking. BSD `soundfile` Python wrapper is fine. |
| Gemma Terms of Use | Not open-source. Flow-down requirements are concrete (see table above). Must be reviewed by legal before distribution. |
| OpenRAIL-M (Supertonic 3) | Use-based restrictions must be passed to end users. Compatible with commercial use but with significant content/usage restrictions. |
| NVIDIA EULA | Proprietary. cuBLAS redistribution is permitted under conditions; cuDNN redistribution status is unclear — verify before shipping. |
| MIT / BSD / Apache-2.0 components | Permissive. Retain copyright notices and license texts. Apache-2.0 components require preserving NOTICE files. |


## Speaker diarization (optional, M2)
| Component | Source | Licence | Status |
|---|---|---|---|
| sherpa-onnx 2.0.1 (inference library) | PyPI, k2-fsa | Apache-2.0 (PyPI metadata) | verified from package metadata |
| pyannote segmentation 3.0, ONNX conversion | GitHub release `speaker-segmentation-models` (tarball sha256 `24615ee8…6488`) | MIT, Copyright 2022 CNRS (LICENSE file inside the tarball) | verified |
| 3D-Speaker ERes2Net-base speaker embedding, ONNX | GitHub release `speaker-recongition-models` (sha256 `1a331345…5e4b`) | The 3D-Speaker toolkit is Apache-2.0; **no source states the licence of these weights explicitly** | **UNVERIFIED**: check the ModelScope card before redistributing |

The two model files (about 46 MB) are downloaded only when a project enables diarization, into
`models/diarization/`, and refused unless their sha256 matches the values pinned in
`localdub/core/diarize/sherpa_diarizer.py`. The pins were recorded at first download (trust on first
use). The embedding model was trained on Mandarin speech; its behaviour on other languages is only
measured on the samples in docs/QUALITY.md.

## Dialogue/background separation (optional, experimental, M3)
| Component | Source | Licence | Status |
|---|---|---|---|
| Demucs 4.1.0 (code) | PyPI, facebookresearch/demucs | MIT (PyPI metadata) | verified from package metadata |
| `htdemucs` weights (about 80 MB, safetensors) | Hugging Face `adefossez/HTDemucs`, `main` branch, fetched by `demucs.pretrained` (revision **not pinned**, no checksum check by us) | MIT per the Demucs repository; **the weights' licence on that model card was not checked** | UNVERIFIED |
| PyTorch 2.9.1 + CUDA 12.8 | download.pytorch.org/whl/cu128 | BSD-3-Clause-style (PyTorch) | NVIDIA CUDA runtime libraries inside the wheels are under NVIDIA's licence; check before redistributing an installer |

Installed only on request from inside the app (`localdub/extras.py`: wheels and SHA-256 come from `uv.lock`, about 2.9 GB; from a source checkout `uv sync --extra experimental` does the same). Weights go to the Hugging Face cache (`~/.cache/huggingface`).

## Voice cloning (optional, experimental, M3)
| Component | Source | Licence | Status |
|---|---|---|---|
| OpenVoice tone-colour converter code | github.com/myshell-ai/OpenVoice at commit `74a1d147…`, vendored in `localdub/vendor/openvoice/` (7 files, license file kept) | MIT, Copyright 2024 MyShell.ai | verified (GitHub licence metadata and the LICENSE file) |
| OpenVoice V2 converter weights (`checkpoint.pth`, `config.json`) | Hugging Face `myshell-ai/OpenVoiceV2` at revision `f36e7edf…` | MIT (Hugging Face model metadata) | verified from metadata; **the licensing of OpenVoice's training data was not examined** |

The checkpoint is loaded with `torch.load(weights_only=True)`. Same optional install as separation
(in-app install). Voice cloning requires an explicit confirmation in the UI and API
that the user may imitate the voices; generated MP4s keep the AI-disclosure metadata. Cloning
people's voices can be illegal or harmful without their consent; this feature is meant for your own
voice or voices you have permission to use.
