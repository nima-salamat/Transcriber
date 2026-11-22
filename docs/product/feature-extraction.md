# Transcriber — Product Feature Extraction & UX Blueprint

**Research snapshot:** 2026-11-14  
**Project baseline:** Stage-1 source ZIP, `transcriber-desktop` 2.1.1, PySide6 6.7+, primary Faster-Whisper adapter  
**Scope:** Product patterns and technical capabilities; no third-party UI or model weights copied into this repository.

> This report distinguishes product claims from functionality verified in the Stage-1 source. “Existing” means the implementation is present in code, not merely mentioned in a README. “Partial” means a narrower version exists. “No” means no implementation was found in the inspected source.

## 1. Reference review

| Reference | Useful patterns observed | Product implications for Transcriber |
|---|---|---|
| [MacWhisper](https://www.macwhisper.com/) | Local transcription; microphone capture; broad audio/video import; speaker recognition; batch transcription; subtitle/document exports; translation and post-processing; watched folders and automation integrations on some editions. | Keep the first-run path short; expose model choice without making every advanced option mandatory; treat export, speaker labeling and AI cleanup as adjacent workspace tasks. Product is commercial/proprietary; do not copy its UI, branding or bundled assets. |
| [Buzz](https://chidiwilliams.github.io/buzz/docs) | Offline-first workflow; audio/video and microphone paths; advanced transcript viewer with find/playback/speed controls; smart visibility and persisted UI state; multiple ASR backends and CLI. | Preserve local-first defaults; separate engine capability discovery from UI; reuse the same service layer for GUI and CLI/agents. |
| [Audacity](https://www.audacityteam.org/) | Detailed waveform/selection workflows and non-destructive effect application; Noise Reduction uses a noise-only profile followed by controlled attenuation, with warnings about over-processing. | Use a real waveform/timeline and source-preserving cleanup. Do not claim profile-based noise reduction when only a one-pass denoising filter is available. |
| [Subtitle Edit 5](https://subtitleedit.github.io/subtitleedit/overview.html) | Subtitle grid, waveform/spectrogram, split/merge, visual/point sync, FPS conversion, batch conversion, line-length/reading-speed fixes, spell-check and command palette. | Subtitle quality is measurable; provide validation issues tied to cue IDs and timing transforms that can be previewed before applying. |
| [Vibe](https://github.com/seigneurcui/vibe-transcribe) | Offline audio/video; batch import; live preview; SRT/VTT/TXT/HTML/PDF/JSON/DOCX outputs; local Ollama and optional cloud summaries; CLI and GPU configurations. | Treat batch, export profiles and AI post-processing as first-class workflows. Keep local models and remote providers separately permissioned. |
| [noScribe](https://noscribe.de/en/docs/usage/) | Multiple files queued sequentially; quality preset; language selection including experimental multilingual; optional speaker count; disfluency options; job queue with cancel/retry/open-result; editor playback-follow, speed and find/replace. | A predictable sequential queue is a safer first implementation than arbitrary parallel model loading. A user must be able to recover an incomplete transcript after a failed job. |
| [Whisper Desktop](https://github.com/phongus/whisper-desktop) | The name is ambiguous: this matrix uses the `phongus/whisper-desktop` Electron/React project as one concrete example. It supports local desktop transcription, file/URL/mic sources, model download/cache and speaker tools, with early-alpha limitations. Other products use the same name. | Never infer a capability from the product name alone. Prefer capability adapters, persistent speaker records and an explicit alpha/unsupported label. |
| [WhisperX](https://github.com/m-bain/whisperX) | Alignment stage for word-level timing; optional diarization; VAD; model/language-specific alignment; additional GPU and model dependencies; some language combinations require a separately chosen alignment model. | Keep diarization and word alignment as independent pipeline adapters. Missing alignments must remain missing; do not fabricate word times from sentence duration. Model access/licensing and GPU requirements must be surfaced. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CTranslate2 inference; VAD integration; word timestamps; batched inference; CPU/GPU and quantized compute modes; multilingual options. | This remains the default ASR integration, but its current adapter cannot honestly advertise streaming or diarization. Engine options must be capability-gated. |
| [Vosk](https://alphacephei.com/vosk/) | Offline streaming recognition; vocabulary reconfiguration; speaker features; lightweight model families. The official model catalog lists Persian small models, including `vosk-model-small-fa-0.42` (53 MB, Apache-2.0 model license); the compressed size is not runtime RAM. | Candidate for optional local Persian command/wake phrase experiments and streaming ASR. Do not ship weights by default; record the exact model URL/revision/license and test false activations before enabling background listening. |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | C/C++ inference; CPU and multiple GPU backends; integer quantization; VAD; a microphone streaming example; standalone inference rather than a full desktop editor. | Good optional CLI/runtime adapter. Streaming example is a rolling-window demonstration, not proof of a complete diarized real-time product. Ship neither binary nor model weights without a reproducible build and license audit. |

### Research limitations

- “Whisper Desktop” does not identify a unique product. The project above is named explicitly so its capabilities are not attributed to unrelated applications.
- Commercial MacWhisper product pages are useful for workflow discovery, not an implementation or license source.
- A model's repository license does not automatically establish the license of every weight file, alignment model, VAD model or dependency. Each artifact needs its own catalog record and license review.
- NoSpeech/diarization accuracy, Persian wake phrase false-positive rate, and resource use require local benchmark recordings; documentation alone cannot establish them.

## 2. Stage-1 implementation audit

| Area | Verified implementation | Gaps / cautions |
|---|---|---|
| App shell | Native `QMainWindow`, standard OS title frame, stacked pages, drag/drop, geometry restore, keyboard shortcuts. | No dockable/resizable inspector or timeline; no persisted QMainWindow dock-state; sidebar not collapsible; no command palette. |
| Audio import | Extension validation for WAV/MP3/M4A/AAC/FLAC/OGG/OPUS/WMA; Faster-Whisper/PyAV decoding. | Video import is not wired to extraction; no file metadata inspection UI; AIFF is missing from accepted suffixes. Codec support depends on the packaged PyAV/FFmpeg build. |
| Playback | Qt Multimedia play/pause/seek/speed/volume; current segment highlighting in the transcript editor. | No waveform/spectrogram, A-B loop, loop region, segment markers or timeline zoom/pan. |
| Recording | Microphone selection, recording state, pause/resume/stop, saved audio file and optional post-record transcription. | No concurrent live ASR stream or live segment editor. No persistent voice-agent sleep/wake lifecycle. |
| ASR | Faster-Whisper local model and explicitly consented Google cloud adapter; beam, VAD, language/task, initial prompt and word timestamps. | Registry is Faster-Whisper model-oriented; no Vosk/whisper.cpp/WhisperX adapters. No automatic engine capability model or independent diarization. |
| Model lifecycle | Hugging Face discovery/download, staged install, manifest validation, one active Faster-Whisper model, worker-based load/unload. | Existing manager deliberately supports one active ASR model. No multi-task loaded-model scheduler, LRU eviction, pinning or RAM/VRAM budgets. |
| Text editor | QText document, find, replace-selection, autosave, persistence, basic export and segment reconciliation after document text edits. | No segment grid or per-word editing; no split/merge/lock/bookmarks/comments/review; no command history/undo-redo for segment edits; no preview cleanup. |
| History/storage | SQLite history, favorites, model/source metadata, backup/restore. | No project-level timeline, project revision history or durable queue/job recovery. |
| Export | TXT, Markdown, SRT, VTT, JSON; optional DOCX/PDF. | No ASS/SSA parser/export; subtitle validation and transformation absent. |
| AI / Agent | No agent, ACP, MCP, semantic action registry or permission layer in Stage 1. | All agent, wake-word and tool-control capabilities are new work; never present an unconnected panel as operational. |
| UI assets | Existing stylesheet is centralized. | No bundled SVG registry or audited icon license. |

## 3. Feature matrix and prioritization

Difficulty: **S** small, **M** medium, **L** large, **XL** research/integration heavy. Decisions refer to this branch's intended product direction.

### P0 — essential professional baseline

| Feature | Reference Software | Existing Implementation | Gap | Difficulty | Priority | Decision |
|---|---|---|---|---|---|---|
| Feature-aware native workspace with saved splitter/dock layout | Buzz, Subtitle Edit | Partial: native shell and geometry | No collapsible sidebar, right inspector, bottom timeline or saved dock layout | L | P0 | Implement PySide6 dock/splitter panels; preserve native frame. |
| Central tokens, dark/light theme, offline SVG icons | Buzz; Lucide | Partial: central QSS only | No semantic token contract or icon registry/assets | M | P0 | Use bundled Lucide SVG only; include license and use selected icons only. |
| Reliable audio/video import and metadata | MacWhisper, Vibe, Whisper Desktop | Partial audio validation | No video demux/extract workflow or metadata panel | M | P0 | Add FFmpeg-backed extraction, codec errors and metadata; preserve source. |
| Capability-aware ASR engine interface | Buzz, faster-whisper, Vosk | Partial: abstract engine plus two concrete adapters | Registry assumes narrow engines; capability flags not exposed | M | P0 | Extend engine metadata and gate unsupported settings. |
| Segment-aware transcript document and edit commands | MacWhisper, Buzz, noScribe | Partial: timed segments and reconciliation | No segment command model, identity, lock/review/comment, word edit or undo history | L | P0 | Implement document/command layer; preserve timings and invalidate stale word timing. |
| SRT/VTT import, export and validation | Subtitle Edit, Vibe | Partial: export only | No parsing, timing issue model, FPS/gap/CPS transforms | M | P0 | Add format codecs and deterministic timing validator. |
| Search/replace, preview cleanup and original/edited separation | MacWhisper, Subtitle Edit | Partial: plain find and selection replacement | No regex search service, filler/repeat cleanup or preview diff | M | P0 | Add safe deterministic preview; never overwrite original without consent. |
| Batch queue with retry/cancel and durable states | noScribe, Vibe, Buzz | No first-class batch queue | No retry/status history or parallel resource constraints | L | P0 | Implement sequential queue first; one loaded ASR model; add resumable metadata. |
| Real progress, recoverable failures and bounded workers | noScribe, Buzz | Partial: QThreadPool, progress and cancellation | Queue is not persisted; model and ASR lifecycle remain separate | M | P0 | Standardize job states and cancellation; persist state before claiming restart recovery. |

### P1 — high-value workflow features

| Feature | Reference Software | Existing Implementation | Gap | Difficulty | Priority | Decision |
|---|---|---|---|---|---|---|
| Waveform with playback cursor and segment ranges | Subtitle Edit, Audacity | No | No visualization or cache | M | P1 | Generate bounded peak cache; render via QPainter; waveform only initially. |
| Speaker labeling/editing | MacWhisper, noScribe, WhisperX | Partial data field only | No diarization adapter, speaker table, assignment workflow or speaker colors | L | P1 | Implement manual speaker editing first; diarization optional adapter later. |
| Quality report: language, duration, silence, segments, validation | noScribe, Subtitle Edit | Partial engine language/duration | No unified post-run report; no trustworthy uncertainty score | M | P1 | Report only metrics returned/calculated reliably; omit fabricated confidence. |
| Audio cleanup with source preservation | Audacity | No | No FFmpeg processing UI/preview | M | P1 | Provide copy-output processing; label one-pass filters versus noise-profile processing. |
| Model library metadata and model details | Buzz, Whisper Desktop | Partial Hub results and install status | No runtime/task/license/resources catalog | M | P1 | Add typed catalog; show model license and dependencies separately. |
| Application Action Registry and permission enforcement | MacWhisper CLI/workflows | No | UI-only methods are not semantic app services | L | P1 | Route registered actions through a shared service; no raw widget access. |
| Local authenticated MCP bridge | OpenCode MCP docs | No | No independent stdio server or GUI IPC | L | P1 | Expose a small discovery/action surface over token-authenticated local IPC. |
| OpenCode ACP process/session client | OpenCode ACP docs | No | No subprocess/session/prompt/notification lifecycle | L | P1 | Use JSON-RPC stdio, persistent session ID and cancellation. |
| Project search and command palette | Subtitle Edit, Buzz | Partial shortcut map | No searchable commands or global search | M | P1 | Provide palette for registered navigation/actions only. |

### P2 — advanced capabilities

| Feature | Reference Software | Existing Implementation | Gap | Difficulty | Priority | Decision |
|---|---|---|---|---|---|---|
| Spectrogram and detailed timing editor | Audacity, Subtitle Edit | No | No FFT/time-frequency renderer | L | P2 | Optional layer; waveform baseline first. |
| WhisperX word alignment | WhisperX | Partial word times if Faster-Whisper returns them | No forced-alignment pipeline | XL | P2 | Optional adapter; language-specific alignment-model license/availability required. |
| Speaker diarization | WhisperX, noScribe | No inference; `speaker` field only | Requires pyannote or comparable model and consent/license handling | XL | P2 | Separate pipeline stage; never claim Faster-Whisper performs diarization. |
| Multimodel pipeline scheduling | Buzz and ASR toolchains | No | Existing ASR manager supports one model | XL | P2 | Generic scheduler supports max 10 as a configurable ceiling; actual adapters and memory estimates decide feasible concurrency. |
| AI summaries/translation/action items | MacWhisper, Vibe | No | No provider adapter, preview/diff or cloud permission model | L | P2 | Local OpenCode/LLM provider integration optional; preview only. |
| Video preview and burn-in/subtitle overlay | Subtitle Edit, Whisper Desktop | No | No video player/FFmpeg export UI | L | P2 | Optional FFmpeg-backed feature; do not bundle codec binaries without legal review. |
| Live transcription while recording | Buzz, whisper.cpp | Partial recording then transcribe | No streaming engine or partial segment stabilization | L | P2 | Add only for engines advertising streaming; keep recording stable otherwise. |
| Persian/English wake phrase | Vosk, openWakeWord | No | No tested wake model or false activation data | XL | P2 | Vosk Persian small model is optional; do not default-enable or claim lightweight until measured. |

### P3 — specialist / experimental

| Feature | Reference Software | Existing Implementation | Gap | Difficulty | Priority | Decision |
|---|---|---|---|---|---|---|
| Cloud ASR providers beyond Google | MacWhisper, Buzz | Partial Google adapter | Provider-specific error, consent, pricing and retention policies | L | P3 | Adapter plug-ins only; local-only stays default. |
| Music/speech source separation | Audacity ecosystem | No | Requires dedicated models and heavy compute | XL | P3 | Optional later; not core. |
| OCR/subtitle image extraction | Subtitle Edit | No | Requires OCR models, language packs and review UI | XL | P3 | Optional specialist module. |
| TTS / voice cloning | Subtitle Edit, MacWhisper | No | Model/voice licensing, privacy and misuse risk | XL | P3 | Optional local TTS only; no voice cloning in core scope. |
| Watch folders and workflow webhooks | MacWhisper, Vibe | No | Filesystem event monitoring, dedupe, security and audit | L | P3 | Defer until durable queue and permission system are stable. |
| Meeting/system-audio capture | MacWhisper, Buzz | Partial microphone capture only | OS-specific permissions and loopback capture | L | P3 | Platform-specific add-on; not silently enabled. |

## 4. Design principles / information architecture

Primary navigation should remain focused around these seven groups:

1. **Workspace:** Home, New Transcription, Live Recording, Batch.
2. **Library:** Projects, Transcripts, Audio Files, Recent, Favorites.
3. **Studio:** Transcript Editor, Subtitle Studio, Audio Cleanup, Translate & Summarize.
4. **AI & Models:** AI Assistant, Model Library, Runtime, Agent Activity.
5. **Global header:** breadcrumb/title, global search, command palette, new action and compact model status.
6. **Inspector:** Properties, Assistant, Speakers, Transcription Settings, Model Pipeline.
7. **Timeline:** waveform, ruler, cursor, segment ranges and speaker lanes; optional spectrogram is deferred.

Progressive disclosure rules:

- Default transcription shows file, language, model, device preset and Start. Beam, VAD tuning, compute type, CPU threads and prompt live in Advanced Options.
- Model capabilities are displayed from the adapter, not assumed from a generic control list.
- Agent panels must show disconnected/disabled states until the actual process/IPC is connected.
- “Loaded” and “Running” are separate states. A configured maximum of ten is a ceiling, not a promise that ten models fit in RAM/VRAM.
- A cloud provider is unavailable until the user opts in for that provider and operation.

## 5. Stage-2 implementation status in the delivered source snapshot

The current ZIP contains the following implementation, beyond the Stage-1 baseline:

### Implemented code paths

- Native `QMainWindow` workspace with sidebar navigation, collapsible sidebar, global search, command-palette dialog, resizable right-side inspector dock, bottom waveform/timeline dock, native OS title frame, persisted geometry/dock visibility and keyboard navigation.
- Central dark/light semantic tokens and an offline Lucide SVG registry. Only the selected static SVGs are included; assets and license text are packaged inside the Python distribution.
- New Transcription and existing recording flows remain connected to the Stage-1 Faster-Whisper service. The main workspace includes Batch, Transcript Editor, Subtitle Studio, Model Library, Audio Library, Audio Cleanup and Settings pages.
- Segment-aware transcript model with stable IDs, per-word timing edits when supplied by the engine, split/merge/delete, speaker assignment, bookmarks, comments, lock/review flags, snapshot undo/redo, regex search/replace, cleanup preview/apply, original-vs-edited comparison and a quality report.
- SQLite persistence for segment editor metadata, including stable IDs, notes, speaker, review flags and word timings.
- Subtitle parsing/export for SRT, WebVTT, ASS and SSA; timing offset/FPS transform, minimum-gap correction and overlap/reading-speed validation.
- Bounded waveform peak generation/cache; a timeline widget renders waveform peaks, playhead and segment boundaries and can seek playback.
- FFmpeg-backed Audio Cleanup writes a separate output file. It supports normalization, one-pass denoising, silence removal, high/low-pass filters and gain, while protecting the input file.
- Batch UI offers sequential jobs, per-file status/progress, pause/resume/cancel, retry and subtitle export. It deliberately does not load multiple Faster-Whisper models concurrently.
- Generic model runtime and priority scheduler support adapters, active-model ceiling 1–10, RAM/VRAM admission budgets, pinning, lazy load and LRU eviction. These are reusable services, not yet the global Faster-Whisper manager.
- OpenCode ACP client uses the current stdio JSON-RPC session model; it supports initialize, session create/load, prompt, notification handling and cancellation. The Assistant panel provides project selection, persistent session reuse, prompt review and connection state.
- Standalone MCP entrypoint supports stdio and exposes three compact tools: application state, action discovery and action execution. Calls cross a versioned, token-authenticated user-local IPC channel and are dispatched onto the Qt main thread.
- Agent permissions are configurable. Read and transcript edit are defaults; settings, audio capture, export, model management and destructive operations are separate permissions. A destructive action also requires user approval.
- Optional Vosk voice input is explicitly enabled by the user and processes microphone frames locally in memory. It can recognize a configured wake phrase or accept push-to-talk during an active voice session, then put recognized text into the prompt editor for review.

### Not implemented or not yet validated

- No automatic diarization, speaker embedding, speaker clustering or speaker merge/split model.
- No Persian wake phrase accuracy/false activation benchmark. No claim is made that the Vosk adapter is always-on low-power on every device.
- No live partial Whisper transcription while recording; recording is saved before ASR.
- No automatic voice-to-Agent submission; a recognized command is shown for review and the user must send it. No TTS output.
- No transparent ACP reconnection after the external process exits; users can reconnect.
- The MCP tool surface is dynamic but compact; only registered actions can be invoked. The entire product feature list is not yet exposed as agent actions.
- No persistent batch queue recovery across restarts, and no parallel batch ASR.
- No automatic video preview, subtitle burn-in, spectrogram UI, full point-sync, subtitle style preview, spell check or OCR.
- No dedicated AI translation/summarization provider or diff-based approval layer; OpenCode remains the optional external agent.
- The current Faster-Whisper application service remains single-active-model. The configurable generic 1–10 runtime ceiling is not a promise of ten concurrently loaded ASR models.
- The actual PySide6 GUI test is skipped in the development environment because PySide6 is not installed. The Python wheel build verifies packaging metadata and included icon assets, not Qt runtime behavior.

The status above is code-level, not a claim that every product acceptance criterion is complete. Remaining work and test limitations are tracked in [Known limitations](../KNOWN_LIMITATIONS.md).

## 6. Source and license notes

- **Lucide icons**: project license text is included at `assets/icons/LICENSE.txt`; only selected SVG files are vendored. Verify the upstream icon license on each future asset update.
- **Vosk**: code and model weights are separate artifacts. The official model catalog lists `vosk-model-small-fa-0.42` as 53 MB and Apache 2.0; its runtime memory and recognition error rate must still be measured. It is not enabled automatically.
- **WhisperX / pyannote**: optional diarization/alignment may require accepted model cards, credentials or separate licenses; no weights are redistributed here.
- **FFmpeg**: this branch invokes an installed executable when available. It does not bundle FFmpeg. Redistribution terms depend on the exact build and enabled libraries.
- **OpenCode ACP**: external executable must be user-installed and authenticated independently. ACP's `cwd` must be absolute; one prompt per session is allowed while another is running; cancel is a session operation. See [OpenCode ACP docs](https://opencode.ai/docs/cli/acp/).
- **MCP SDK**: current 2.x API is used (`MCPServer`, stdio). Do not copy v1 examples using `FastMCP` or assume v1 wire-level behavior. See [MCP Python SDK migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## 7. Primary references

- [MacWhisper product capabilities](https://www.macwhisper.com/)
- [Buzz documentation](https://chidiwilliams.github.io/buzz/docs)
- [Audacity noise reduction workflow](https://www.audacityteam.org/manual/effects/noise-removal-and-repair/noise-reduction/)
- [Subtitle Edit overview](https://subtitleedit.github.io/subtitleedit/overview.html), [main window](https://subtitleedit.github.io/subtitleedit/features/main-window.html)
- [Vibe repository](https://github.com/seigneurcui/vibe-transcribe)
- [noScribe usage](https://noscribe.de/en/docs/usage/), [source/license](https://github.com/kaixxx/noScribe)
- [Whisper Desktop example](https://github.com/phongus/whisper-desktop)
- [WhisperX repository](https://github.com/m-bain/whisperX)
- [faster-whisper repository](https://github.com/SYSTRAN/faster-whisper)
- [Vosk language models](https://alphacephei.com/vosk/models)
- [whisper.cpp repository and stream sample](https://github.com/ggml-org/whisper.cpp)
- [OpenCode ACP](https://opencode.ai/docs/cli/acp/), [MCP servers](https://opencode.ai/docs/mcp-servers/)
- [MCP Python SDK v2 migration](https://py.sdk.modelcontextprotocol.io/migration/)
- [Qt for Python](https://doc.qt.io/qtforpython/), [Qt Multimedia](https://doc.qt.io/qtforpython/PySide6/QtMultimedia/index.html), [QtSvg](https://doc.qt.io/qtforpython/PySide6/QtSvg/index.html)
