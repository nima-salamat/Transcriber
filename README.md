# Transcriber

**Transcriber** is a local-first desktop workspace for audio transcription, segment editing, subtitle production and optional AI-agent assistance. The 2.1.4 source uses PySide6, SQLite, Hugging Face Hub and Faster-Whisper/CTranslate2. A downloaded compatible ASR model can run offline; the default local engine does not send audio to a cloud service.

> **Project status:** 2.1.4 expands the Stage-1 modernization with a native workspace, resizable inspector/timeline docks, segment-aware editing, subtitle tools, Batch, Audio Cleanup, a generic model-runtime foundation and optional OpenCode ACP/MCP integration. This is still an alpha development snapshot. Important limits remain, including no live partial ASR, automatic diarization, verified Persian wake-word accuracy, TTS or full video-preview workflow. See [Known limitations](docs/KNOWN_LIMITATIONS.md).

## What is implemented

- Native `QMainWindow` with a unified workspace for Transcribe, Segments, Captions, Record, Batch, Library and Audio Cleanup. The permanent feature sidebar is removed; model management and Preferences open in dedicated dialogs, while Inspector and the fixed-height timeline are optional panels.
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
- Optional local Vosk wake/voice input. Choose the activation keyword and one installed Vosk wake-word model in Settings → OpenCode & Voice Agent (or Assistant → Wake word & voice settings). Vosk detects only the wake phrase; the installed local Faster-Whisper model transcribes the command.
- Optional local Ollama chat provider in the side Assistant panel. Select an installed Ollama model, load it locally and chat with streamed responses. **Start voice chat** connects the selected provider, warms the local Faster-Whisper model, loads the Vosk wake detector, and continuously cycles through wake phrase → microphone capture → local transcription → model response → wake listening. The response is displayed in the chat; speech playback is not included.
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

Create and activate a virtual environment, then install the local speech-recognition
runtime:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-asr.txt
```

`requirements.txt` is the core GUI/runtime dependency lock. It does not install the optional
speech-recognition engine or NVIDIA GPU libraries. `requirements-asr.txt` adds Faster-Whisper
and the supported PyAV range for CPU or automatic-device recognition. For a core-only GUI
environment, install `requirements.txt` and then `pip install -e . --no-deps`.

For Windows x64 NVIDIA GPU acceleration, use the dedicated requirements file instead of
manually installing individual CUDA wheels:

```powershell
python -m pip install -r requirements-windows-gpu.txt
```

This installs the core application, Faster-Whisper/PyAV, local Vosk/sounddevice voice support,
and the CUDA 12 cuBLAS/runtime, NVRTC, nvJitLink and cuDNN 9 wheels into the active Python
environment. Transcriber registers every
NVIDIA wheel `bin` directory before loading CTranslate2. Close all Transcriber processes and
restart the application after installation. A recent NVIDIA display driver alone does not
provide these runtime DLLs. The same command can be used to repair an existing environment.

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

1. Open **Models** from the workspace's **More** menu.
2. Choose **Curated models** or search the live Hugging Face Hub API.
3. Open the repository page and inspect its license/model card.
4. Select **Inspect compatibility**. Transcriber checks for a CTranslate2 `model.bin`, config, tokenizer and vocabulary artefact set. A normal PyTorch Transformers checkpoint is not treated as a Faster-Whisper model.
5. Select **Install model** and confirm. Transcriber pins the returned repository commit, downloads supported artefacts to a staging directory, validates them, then publishes the installation.
6. Set a default model or load it from the Installed tab. Once installed, inference can run without network access.

The curated list includes the Systran tiny/base/small/medium/large-v3 models, plus CTranslate2-converted distilled and Turbo examples. Availability and current metadata are fetched from the Hub; the repository compatibility check remains authoritative. Repository sizes can be large, especially for medium/large models. Check available disk space before installation.

For gated repositories, open the model page and accept its terms with the model provider first. Then configure `HF_TOKEN` in the environment before launching Transcriber. Tokens are not shown in the interface or intentionally written to logs.

## Transcribe audio and video

1. Open the **Transcribe** workspace view and choose a supported audio file or video, or drag one into the application. Video transcription reads its first audio track; a video without audio is rejected before recognition. The workspace plays the audio but does not show video frames.
2. Select an installed model and a language, or leave language detection on Auto.
3. Adjust beam size and voice activity detection as needed.
4. Start transcription. Local recognition stays on-device; a Cloud engine is used only after explicit consent. Inference runs in a worker and updates the status/progress controls.
5. Switch to **Segments** in the same workspace to edit speakers, timing, word-level metadata and review state.
6. Switch to **Captions** to adjust subtitle timing, validate cues and export SRT, WebVTT, ASS or SSA.

While a transcription or history load is active, Transcriber locks media replacement and changes to the Library, Segments and Captions views until the worker has actually finished. Requesting Cancel does not release the lock early.

## Record audio

Open the **Record** workspace view, choose an available microphone, select a WAV destination and press the record control. The recorder uses a supported 16-bit PCM input format, writes a WAV file, displays a live level meter and elapsed duration, and supports pause/resume, save and discard. The optional **Start transcription after saving** switch opens the saved recording in the Transcribe view and starts a job when a compatible model is installed.

This page records microphone audio; it does **not** claim to perform continuous Whisper streaming while the microphone is active. Incremental chunked Whisper/VAD reconciliation remains future work.

## Voice agent and wake word

1. Install voice support in the same Python environment used to launch Transcriber:
   - Windows with NVIDIA GPU: `python -m pip install -r requirements-windows-gpu.txt`
   - CPU or Linux: `python -m pip install -r requirements-voice.txt`
2. Open **AI models → Vosk** and install a compatible Vosk model for the language you intend to use.
3. Open **Settings → OpenCode & Voice Agent**. Enter the **Activation keyword / phrase**, then choose the **Wake-word Vosk model** from the installed-model list. The Assistant's **Wake word & voice settings** panel exposes the same controls.
4. Use **Refresh** after installing a Vosk model. A local folder can also be selected with **Browse local…**. Only compatible registered Vosk models are listed automatically.
5. Install and start [Ollama](https://ollama.com), then download a local chat model, for example `ollama pull qwen2.5:7b`.
6. In the Assistant side panel choose **Ollama · Local models**, keep the default URL `http://127.0.0.1:11434`, refresh the model list and connect. Select a Faster-Whisper model separately in **Wake word & voice settings**; the Vosk model is used only for the activation phrase. Press **Start voice chat** to launch the complete hands-free loop: wake phrase, command capture, local transcription, Ollama response, then wake listening again.
7. For ordinary one-shot voice commands, review-before-send remains the default unless automatic submission is enabled. The dedicated **Start voice chat** mode submits each turn automatically and resumes listening after the response. Use a short phrase supported by the chosen Vosk model; arbitrary names or unsupported languages are not guaranteed to be recognized.

Vosk is the wake detector, not the command transcription model. The wake model and activation phrase are saved in Transcriber settings. Voice input remains off until explicitly enabled, and review-before-send remains the default.

The **Prompt library** in the Assistant stores editable Markdown instructions. **Copy full prompt pack** copies the actual current contents, rather than only a folder path. For messages sent through Transcriber, the application reads the current coordinator, index and task-relevant specialist files and embeds their contents in requests to OpenCode or the local Ollama model; it does not rely on an external client independently opening Transcriber's AppData directory.

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
  ui/            unified workspace, contextual inspector/timeline, dialogs and theme
```

See [Architecture](docs/ARCHITECTURE.md), [Model manager](docs/MODEL_MANAGER.md), [Audio pipeline](docs/AUDIO_PIPELINE.md), [Storage policy](docs/STORAGE_POLICY.md) and [Known limitations](docs/KNOWN_LIMITATIONS.md).

## Troubleshooting

- **No local model appears:** open **Models** from the workspace's **More** menu and inspect a CTranslate2 model. PyTorch-only Whisper repositories are intentionally rejected.
- **CUDA load failure:** on Windows run `python -m pip install -r requirements-windows-gpu.txt` from the repository root and the same activated environment used to launch Transcriber, then fully restart the application. This installs cuBLAS, CUDA Runtime, NVRTC, nvJitLink and cuDNN 9 wheels. Transcriber adds all `nvidia/*/bin` folders and CUDA Toolkit `bin` folders to the native DLL search path. The error dialog reports the active Python executable, installed NVIDIA wheel versions and whether core runtime DLL files were found. If DLL files exist but still cannot load, repair the Microsoft Visual C++ 2015–2022 x64 Redistributable and check for conflicting CUDA versions.
- **OpenCode ACP fails with WinError 193 on Windows:** select the npm `opencode.cmd` launcher (normally `%APPDATA%\\npm\\opencode.cmd`) in Settings → OpenCode executable, or clear the field and let Transcriber resolve OpenCode from PATH. Do not point Settings at the extensionless npm JavaScript shim. Transcriber runs `.cmd`/`.bat` launchers through the Windows command processor and uses the same launcher logic for **Test OpenCode executable**.
- **`open() got an unexpected keyword argument 'metadata_errors'`:** the current Faster-Whisper release calls a PyAV API parameter removed in PyAV 19. The project pins PyAV to `av>=11,<19`; repair an existing environment with `python -m pip install --upgrade "av>=11,<19"` and restart Transcriber.
- **Model download interrupted:** retry the same repository. Hub cache/download facilities are used to reuse completed artefacts where possible; the incomplete staging installation is not marked installed.
- **Gated model access:** accept the repository terms on Hugging Face and provide a `HF_TOKEN` environment variable. Transcriber does not bypass access restrictions.
- **Microphone unavailable:** verify OS privacy permissions, connect an input device, and refresh the device list. Some devices do not support the selected PCM16 format; choose a different input.
- **Unsupported audio codec:** not all files sharing an extension use the same codec. Try converting it to PCM WAV with a trusted local FFmpeg build.
- **RTL PDF output:** install the document extras and configure a font that supports the target script. DOCX is usually the better option when a Word processor should perform final shaping/layout.
- **Logs:** inspect the current platform log directory under Transcriber. Do not attach model tokens or private recordings to issue reports.

## License

MIT. See [LICENSE](LICENSE).
