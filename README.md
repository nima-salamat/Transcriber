# Transcriber

**Transcriber** is a local-first desktop workspace for audio transcription, segment editing, subtitle production and optional AI-agent assistance. The 2.1.4 source uses PySide6, SQLite, Hugging Face Hub and Faster-Whisper/CTranslate2. A downloaded compatible ASR model can run offline; the default local engine does not send audio to a cloud service.

> **Project status:** 2.1.4 expands the Stage-1 modernization with a native workspace, resizable inspector/timeline docks, segment-aware editing, subtitle tools, Batch, Audio Cleanup, a generic model-runtime foundation and optional OpenCode ACP/MCP integration. This is still an alpha development snapshot. Important limits remain, including no live partial ASR, automatic diarization, verified Persian wake-word accuracy, TTS or full video-preview workflow. See [Known limitations](docs/KNOWN_LIMITATIONS.md).

## What is implemented

- Native `QMainWindow` frame and workspace with collapsible sidebar, global search, command palette, resizable Inspector and bottom Waveform/Timeline docks; window geometry and panel state are persisted.
- Central semantic dark/light theme tokens and a bundled Lucide SVG icon subset. No runtime network access or QtAwesome dependency is required for icons.
- Faster-Whisper local audio-file transcription with language detection/selection, task, VAD, beam size, compute device/type, CPU threads and optional word timestamps.
- Hugging Face model discovery, compatibility inspection, pinned-revision download, validation, install/retry/cancel, default selection and active-model lifecycle.
- Microphone recording through Qt Multimedia with device selection, level meter, pause/resume, save/discard and optional transcription after saving.
- Transcript Editor with segment table, timing/text/speaker edits, split/merge/delete, word-timing edits when supplied, locks, bookmarks, notes, reviewed markers, undo/redo, regex search/replace, cleanup preview and Original/Edited comparison.
- Transcript quality report based on available language, duration, gaps, duplicate text and engine-provided word confidence; missing confidence is not fabricated.
- Subtitle Studio for SRT, WebVTT, ASS and SSA import/export, timing shift, frame-rate conversion, minimum-gap correction and overlap/reading-speed validation.
- Batch page with sequential processing, per-file progress, pause/resume/cancel/retry and subtitle export.
- Waveform peak caching and a timeline for seek, playhead and segment boundaries.
- Audio Cleanup using optional FFmpeg filters on a new output file; the original source is protected.
- Generic model runtime service with resource budgets, lazy loading, pinning, LRU eviction and a configurable 1–10 loaded-model ceiling for compatible adapters. The integrated Faster-Whisper application manager remains single-active-model for now.
- Optional OpenCode ACP client with persistent sessions, streaming updates and cancellation; standalone MCP stdio server exposes application state, action discovery and registered actions through authenticated local IPC.
- Optional local Vosk wake/voice input. It is disabled until explicitly enabled, processes audio locally and places recognized text into the prompt field for review before submission.
- SQLite transcript persistence, editor metadata, history, favorites, autosave and metadata-only backup/restore.

The full scope and verified gaps are listed in [Feature extraction](docs/product/feature-extraction.md) and [Known limitations](docs/KNOWN_LIMITATIONS.md).

## Screenshots

The two images currently in the repository (`screenshot_1.png` and `screenshot_2.png`) show the legacy 1.x interface. They are retained for historical reference and are **not** screenshots of the redesigned 2.0 UI. Fresh screenshots require launching the new GUI on a machine with the PySide6 multimedia runtime installed.

## Requirements

- Python 3.11 or newer.
- Windows 10/11 or a current Linux desktop environment with an available Qt Multimedia audio backend.
- PySide6 6.7+.
- Internet access only for Hugging Face model discovery/download and the optional cloud engine. Transcription with an installed model is local.
- A compatible Faster-Whisper model. Model downloads are user-initiated; no model is silently downloaded on first launch.

## Installation

Create and activate a virtual environment, then install the runtime dependencies:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e . --no-deps
```

`requirements.txt` includes the runtime integrations for local ASR, optional cloud recognition,
local voice input, MCP, and document/PDF export. Cloud recognition and microphone-based voice
features remain disabled until explicitly configured in the application. For a smaller install,
install only the core package and selected extras with `pip install -e ".[asr,documents]"`.

For development and tests:

```bash
pip install -e ".[asr,documents,dev]"
pytest
ruff check src tests
```

For the optional Google cloud adapter:

```bash
pip install -e ".[cloud]"
```

On Linux, make sure the desktop session has working audio permissions and a Qt Multimedia backend. If playback or microphone access is unavailable, check the system's PipeWire/PulseAudio/ALSA configuration and the application's device list. The local Faster-Whisper decoder uses PyAV; separate system FFmpeg installation is generally not required for local inference. The optional cloud adapter may need FFmpeg for formats SpeechRecognition cannot read directly.

## Run the application

```bash
transcriber
# or, from a source checkout:
python -m transcriber
```

The legacy `APP.py` file remains only as a compatibility launcher. It imports the package entry point and no longer contains a second implementation.

## Install an offline model

1. Open **Model Library**.
2. Choose **Curated models** or search the live Hugging Face Hub API.
3. Open the repository page and inspect its license/model card.
4. Select **Inspect compatibility**. Transcriber checks for a CTranslate2 `model.bin`, config, tokenizer and vocabulary artefact set. A normal PyTorch Transformers checkpoint is not treated as a Faster-Whisper model.
5. Select **Install model** and confirm. Transcriber pins the returned repository commit, downloads supported artefacts to a staging directory, validates them, then publishes the installation.
6. Set a default model or load it from the Installed tab. Once installed, inference can run without network access.

The curated list includes the Systran tiny/base/small/medium/large-v3 models, plus CTranslate2-converted distilled and Turbo examples. Availability and current metadata are fetched from the Hub; the repository compatibility check remains authoritative. Repository sizes can be large, especially for medium/large models. Check available disk space before installation.

For gated repositories, open the model page and accept its terms with the model provider first. Then configure `HF_TOKEN` in the environment before launching Transcriber. Tokens are not shown in the interface or intentionally written to logs.

## Transcribe audio

1. Open **New Transcription** and choose an audio file, or drag a supported file into the application.
2. Select an installed model and a language, or leave language detection on Auto.
3. Adjust beam size and voice activity detection as needed.
4. Start offline transcription. Inference runs in a worker and updates the status/progress controls.
5. Open **Transcript Editor** to edit segments, speakers and available word timestamps. Split, merge, bookmark, lock, review, add notes, search/replace or preview text cleanup. Segment edits support undo/redo and are saved with the transcript metadata.
6. Open **Subtitle Studio** to inspect and fix timing, then export SRT, WebVTT, ASS or SSA. The timeline can seek the loaded audio and display segment boundaries.

## Record audio

Open **Live Recording**, choose an available microphone, select a WAV destination and press the circular record control. The recorder uses a supported 16-bit PCM input format, writes a WAV file, displays a live level meter and elapsed duration, and supports pause/resume, save and discard. The optional **Start transcription after saving** switch opens the saved recording in the transcription page and starts a job when a compatible model is installed.

This page records microphone audio; it does **not** claim to perform continuous Whisper streaming while the microphone is active. Incremental chunked Whisper/VAD reconciliation remains future work.

## Data locations

The app uses `platformdirs` and does not put model weights, recordings, databases or runtime state in the source checkout. The default locations are:

| Data | Windows | Linux |
|---|---|---|
| Configuration | `%APPDATA%/transcriber` | `~/.config/transcriber` |
| User data | `%LOCALAPPDATA%/transcriber` | `~/.local/share/transcriber` |
| Cache | `%LOCALAPPDATA%/transcriber/Cache` | `~/.cache/transcriber` |
| Logs | platformdirs user log directory | `~/.local/state/transcriber/log` |
| Models | user data `models/` | user data `models/` |
| Recordings | user data `recordings/` | user data `recordings/` |

The precise paths are determined by `platformdirs` for the active OS. Set `TRANSCRIBER_HOME` to a root directory for portable/test use. Storage Settings can override model and recording directories; restart the app after changing these locations. The SQLite database and settings are not removed during upgrades.

## Engines and privacy

- **Faster-Whisper:** local CTranslate2 inference. CPU INT8 is the default; `device=auto` prefers CUDA when CTranslate2 detects a CUDA device and retries CPU INT8 if automatic CUDA initialization fails. Explicit CUDA selection reports a clear failure instead of silently changing the user's choice.
- **Google Speech Recognition:** optional online compatibility adapter using SpeechRecognition's `recognize_google` method (not the authenticated Google Cloud Speech-to-Text API). It is never a fallback for a failed local model. The user must install the cloud extra, switch off local-only mode, and check the cloud-consent setting. Audio is then sent to Google's online recognition service.
- **Vosk:** optional local wake/voice input is provided by the `[voice]` extra. It is not the primary transcription backend, Persian wake accuracy is not benchmarked and no model weights are bundled.

Transcriber does not enable telemetry. Logs are rotated and include conservative redaction for common Hugging Face token patterns. Model repository files are treated as data artefacts, validated by name and never executed by the application.

## Development architecture

```text
src/transcriber/
  core/          paths, settings, errors, logging
  audio/         device capture, WAV recording, playback, file validation
  engines/       engine interface, Faster-Whisper, optional cloud adapter
  models/        Hub API, compatibility checks, downloader, registry, manager
  storage/       SQLite history and metadata backup/restore
  transcription/ segments, service, job queue, quality report, exporters
  editor/        segment-aware document, undo/redo, search and cleanup preview
  subtitles/     SRT/VTT/ASS/SSA codecs and timing validation
  models/        Hub integration plus generic runtime and priority scheduler
  assistant/     semantic actions, permissions and optional local voice input
  opencode/      ACP stdio client and persistent session handling
  mcp/ ipc/      MCP tools and authenticated local IPC bridge
  ui/            native workspace, inspector/timeline docks, pages and theme
```

See [Architecture](docs/ARCHITECTURE.md), [Model manager](docs/MODEL_MANAGER.md), [Audio pipeline](docs/AUDIO_PIPELINE.md), [Storage policy](docs/STORAGE_POLICY.md) and [Known limitations](docs/KNOWN_LIMITATIONS.md).

## Troubleshooting

- **No local model appears:** open Model Library and inspect a CTranslate2 model. PyTorch-only Whisper repositories are intentionally rejected.
- **CUDA load failure:** use Automatic or CPU/INT8 first. CUDA support depends on a compatible CTranslate2 wheel and CUDA/cuDNN runtime; install the combination supported by Faster-Whisper/CTranslate2 for your system.
- **Model download interrupted:** retry the same repository. Hub cache/download facilities are used to reuse completed artefacts where possible; the incomplete staging installation is not marked installed.
- **Gated model access:** accept the repository terms on Hugging Face and provide a `HF_TOKEN` environment variable. Transcriber does not bypass access restrictions.
- **Microphone unavailable:** verify OS privacy permissions, connect an input device, and refresh the device list. Some devices do not support the selected PCM16 format; choose a different input.
- **Unsupported audio codec:** not all files sharing an extension use the same codec. Try converting it to PCM WAV with a trusted local FFmpeg build.
- **RTL PDF output:** install the document extras and configure a font that supports the target script. DOCX is usually the better option when a Word processor should perform final shaping/layout.
- **Logs:** inspect the current platform log directory under Transcriber. Do not attach model tokens or private recordings to issue reports.

## License

MIT. See [LICENSE](LICENSE).
