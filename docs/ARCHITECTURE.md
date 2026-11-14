# Architecture

## Runtime composition

`python -m transcriber` (or the `transcriber` console command) enters through `transcriber.__main__` and `transcriber.bootstrap.build_services()`. Bootstrap resolves per-user paths, loads validated settings, configures rotating logs, initializes SQLite and wires the Hugging Face client, model registry, downloader and Faster-Whisper model manager. The UI receives these services through constructors; it does not create its own database or model registry.

`python -m transcriber.mcp_server` (or packaged `Transcriber.exe --mcp-server`) is a separate stdio process. The MCP entry point does not construct the GUI. It exposes a compact discovery/action surface and talks to the running desktop app through authenticated local IPC. If the GUI is closed, MCP returns an explicit unavailable response instead of fabricated application state.

`APP.py` is only a source-checkout compatibility launcher. There is no second copy of the legacy interface.

## Package boundaries

- `core`: validated settings, application paths, logging and domain configuration. It does not import Qt widgets.
- `audio`: device enumeration, microphone capture, playback, waveform generation/cache and FFmpeg processing helpers.
- `engines`: the `TranscriptionEngine` interface plus concrete Faster-Whisper and opt-in Google compatibility adapters. Engines accept paths/options/cancellation/progress and return typed results; they do not know about widgets or SQLite.
- `models`: Hugging Face API access, CTranslate2 compatibility checks, pinned-revision downloads, registry persistence, the current single-active Faster-Whisper lifecycle, plus a generic resource-aware runtime and priority scheduler for future adapters.
- `transcription`: shared transcript/word/segment types, service orchestration, jobs, quality report, and export adapters.
- `editor`: Qt-independent segment-aware document, word timing validation, snapshot undo/redo, search/replace and preview/apply cleanup.
- `subtitles`: SRT/WebVTT/ASS/SSA codecs plus timing transforms and validation.
- `assistant`: semantic action registry, permission enforcement, voice state machine and optional local Vosk command capture.
- `opencode`: ACP stdio client and persistent session handling. The external OpenCode executable is not bundled.
- `mcp` / `ipc`: stdio MCP server, compact tool definitions, versioned JSON protocol, per-user local endpoint and authentication token.
- `storage`: SQLite schema migration, transcript/history repository and metadata backup/restore.
- `ui`: native `QMainWindow`, dockable inspector/timeline, sidebar, page widgets, theme tokens, SVG icon registry and worker adapters.

The dependency direction is UI → application services/repositories/engine interfaces. The ASR adapter does not import UI code, editor and subtitle domain models are testable without Qt, and persistence does not depend on widgets.

## Threading and process model

The GUI uses a bounded `QThreadPool`. Hub queries, model inspection/installation/loading, transcription inference, batch jobs, waveform generation, audio cleanup, storage accounting and OpenCode ACP requests run outside the Qt main thread. Worker signals return results/errors to the GUI thread. Agent/MCP actions use a Qt queued dispatcher; they never mutate a `QWidget` from a foreign thread.

The OpenCode ACP client starts `[opencode, acp]` in the selected absolute working directory and speaks newline-delimited JSON-RPC over stdin/stdout. Session IDs are persisted per user and reused when the working directory matches. MCP server definitions are passed when the ACP session is created or loaded. A prompt, notification stream and session cancellation are supported. Automatic process restart/reconnection is not yet implemented.

MCP uses stdio for its host-facing transport. Its tools call the desktop process through IPC, not direct Python object access. The IPC request contains a version, request ID and high-entropy per-run token. Unix uses a private domain socket; Windows uses a loopback-only TCP fallback. Endpoint files are restricted to the current user where OS permissions support it. The GUI must be running for state/actions to be available.

Optional local Vosk capture opens a microphone only after the user explicitly enables it. Audio frames are used in memory by the recognizer and are not intentionally written or uploaded. The current wake phrase detector and Persian accuracy need device/language benchmarking; it is not advertised as an always-on low-power multilingual product.

## Model runtime and resource policy

The generic `ModelRuntimeManager` separates a loaded handle from an active inference call. It serializes load/unload transitions; supports a configurable 1–10 loaded-model ceiling, adapter-declared RAM/VRAM estimates, pinning, LRU eviction and active-call protection. `PriorityModelScheduler` provides stable priority order with cooperative cancellation.

The production Faster-Whisper application service still uses its existing single-active-model manager. The generic runtime is an adapter foundation, not yet the global runtime for every integrated ASR/model task. Unknown resource estimates are not fabricated, and the user-configured ceiling is not a promise that a particular machine can load ten models.

## Persistence

SQLite is the source of truth for transcript history and ordered timed segments. Schema versions are explicit; migrations add editor metadata, including stable IDs, speaker, comments, review flags and word timings. Transcript autosaves capture immutable snapshots and are coalesced per project. The metadata backup archive excludes large audio and model directories.

The Batch UI currently keeps its queue in memory and processes one file at a time. Restart recovery and a unified persistent application job database remain future work.

See [Storage policy](STORAGE_POLICY.md) and [Known limitations](KNOWN_LIMITATIONS.md).
