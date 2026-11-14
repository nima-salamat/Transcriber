# Transcriber

**Transcriber** is a local-first desktop application for turning audio into editable, timestamped text. The modernized 2.0 application uses PySide6, SQLite, Hugging Face Hub and the Faster-Whisper/CTranslate2 inference runtime. A downloaded compatible model can be used offline; audio is not sent to a cloud service by the default engine.

> **Project status:** 2.0 is an alpha modernization release. The modular foundation, file transcription workflow, model installation, local recording, history and export paths are implemented. Incremental live Whisper dictation and several advanced studio features are still under development and are listed explicitly in [Known limitations](docs/KNOWN_LIMITATIONS.md).

## What is implemented

- Native operating-system window controls, resizing, multi-screen geometry restoration, and high-DPI support provided by Qt 6.
- Sidebar navigation for Home, New Transcription, Live Recording, History, Model Library, Audio Library and Settings.
- Persisted dark/light themes, recognition settings, hardware selection and storage locations.
- Offline Faster-Whisper file transcription with automatic language detection, explicit language selection, timestamps, VAD, beam-size configuration, CPU execution and CUDA selection.
- A model library backed by the Hugging Face Hub API. It displays Hub-supplied metadata, inspects CTranslate2 artefacts, downloads a pinned repository revision, validates files before installation, and supports cancellation/retry from the Hub cache.
- Installed-model inspection, size reporting, default selection, explicit load/unload, corruption visibility and active-model deletion protection.
- Real microphone recording through Qt Multimedia (`QAudioSource`) into PCM16 WAV, with input-device selection, duration, input level meter, pause/resume, save/discard and optional post-recording transcription.
- Audio import for WAV, MP3, M4A, AAC, FLAC, OGG, OPUS and WMA where the bundled PyAV/FFmpeg decoder supports the specific codec. Playback includes seeking, speed and volume controls.
- Editable transcript text, find/replace, word/character counts, timestamp-associated segment storage and automatic local saving.
- SQLite history with title/content search, favorites, rename, duplicate, delete and restart persistence.
- TXT, Markdown, SRT, WebVTT, JSON, DOCX and PDF export. DOCX and PDF export use optional dependencies; RTL PDF shaping requires the optional shaping packages and an appropriate installed font.
- Metadata-only backup/restore. Audio recordings and downloaded models are deliberately excluded from the archive.
- Optional Google Speech Recognition adapter, disabled by default and blocked in local-only mode until the user explicitly grants cloud consent.

## Screenshots

The two images currently in the repository (`screenshot_1.png` and `screenshot_2.png`) show the legacy 1.x interface. They are retained for historical reference and are **not** screenshots of the redesigned 2.0 UI. Fresh screenshots require launching the new GUI on a machine with the PySide6 multimedia runtime installed.

## Requirements

- Python 3.11 or newer.
- Windows 10/11 or a current Linux desktop environment with an available Qt Multimedia audio backend.
- PySide6 6.7+.
- Internet access only for Hugging Face model discovery/download and the optional cloud engine. Transcription with an installed model is local.
- A compatible Faster-Whisper model. Model downloads are user-initiated; no model is silently downloaded on first launch.

## Installation

Create and activate a virtual environment, then install the application and the features you need:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[asr,documents]"
```

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
5. Edit the text. Changes are auto-saved to the local history database while the original recognized text and timestamp segment records are retained.
6. Export the transcript or subtitle file from the editor.

The editor currently presents a unified editable text view. The timing and original segment association are stored separately; a full word-by-word/segment editing timeline is not yet available.

## Record audio

Open **Live Recording**, choose an available microphone, select a WAV destination and press the circular record control. The recorder uses a supported 16-bit PCM input format, writes a WAV file, displays a live level meter and elapsed duration, and supports pause/resume, save and discard. The optional **Start transcription after saving** switch opens the saved recording in the transcription page and starts a job when a compatible model is installed.

This page records microphone audio; it does **not** claim to perform continuous Whisper streaming while the microphone is active. Incremental chunked Whisper/VAD reconciliation is a documented follow-up feature.

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
- **Vosk:** not implemented in this release.

Transcriber does not enable telemetry. Logs are rotated and include conservative redaction for common Hugging Face token patterns. Model repository files are treated as data artefacts, validated by name and never executed by the application.

## Development architecture

```text
src/transcriber/
  core/          paths, settings, errors, logging
  audio/         device capture, WAV recording, playback, file validation
  engines/       engine interface, Faster-Whisper, optional cloud adapter
  models/        Hub API, compatibility checks, downloader, registry, manager
  storage/       SQLite history and metadata backup/restore
  transcription/ segments, service, job queue, exporters
  ui/            native main window, workers, theme and feature pages
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
