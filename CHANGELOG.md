# Changelog

## 0.1.0 — First public Windows release

- Published the modular PySide6 desktop workspace for local-first transcription, recording, transcript editing and subtitle production.
- Added a windowed Windows application package and a per-user Inno Setup installer with Start Menu and optional desktop shortcuts.
- Suppressed console windows for background command-line tools launched by the desktop application.
- Improved live recording waveform visibility, recorder restart after discard and stable recorder controls.

## Development history (pre-release)


## 2.1.4 — Microphone device-change signal fix

- Fixed the Recording page startup crash caused by trying to connect `QMediaDevices.audioInputsChanged` as a class-level signal.
- Created a page-owned `QMediaDevices` monitor and connected its instance signal, allowing microphone add/remove events to refresh the device list.
- Added a dependency-free regression test to prevent connecting Qt instance signals through the class descriptor.

## 2.1.3 — Qt Multimedia signal compatibility fix

- Fixed startup failure when connecting `QMediaPlayer.positionChanged` and `durationChanged` (`qlonglong`) directly to custom `Signal(int)` signals.
- Added Python-callable bridges that explicitly convert the 64-bit millisecond values to Python integers before emitting the application signals.
- Added a dependency-free regression test for both multimedia signal connections.

## 2.1.2 — Main window dependency initialization fix

- Fixed startup crash caused by `_build_ui()` referencing constructor dependencies as local names instead of instance attributes.
- Updated every page and assistant-panel construction call to use the dependencies stored on `MainWindow`.
- Added a regression test that checks the UI builder for these out-of-scope dependency references without requiring a Qt runtime.

## 2.1.1 — PySide6 import correction

- Fixed `QMediaDevices` being imported from `PySide6.QtCore`; it is provided by `PySide6.QtMultimedia`.
- Added a dependency-free AST regression test for the owning PySide6 modules of `QMediaDevices` and `QDesktopServices`.
- Revalidated source compilation and the complete available test suite.

## 2.0.0 — Modern modular foundation

- Replaced the monolithic custom-framed window with a native PySide6 application shell and separate Home, Transcription, Recording, History, Model Library, Audio Library, and Settings pages.
- Added light/dark theme persistence, native window geometry persistence, navigation shortcuts, drag-and-drop audio import, and bounded Qt worker execution.
- Added per-user cross-platform configuration, data, cache, model, recording, and log locations.
- Added SQLite transcript history, segment persistence, search, favorites, rename, duplicate, delete, and metadata backup/restore.
- Added a local-first engine interface and a lazy Faster-Whisper/CTranslate2 adapter with CPU INT8, explicit CUDA selection, automatic hardware detection, and CPU fallback when automatic CUDA initialization fails.
- Added an official Hugging Face Hub client, CTranslate2 artefact validation, pinned-revision staged model installation, byte-progress callbacks, cancellation, cache-backed retry, and active-model deletion protection.
- Added microphone enumeration and PCM16 WAV recording using Qt Multimedia, including pause/resume, elapsed time, input level meter, save/discard, and optional post-recording transcription.
- Added audio playback controls, editable transcript text with autosave, timestamp-aware segment persistence, and TXT/Markdown/SRT/VTT/JSON/DOCX/PDF export adapters.
- Retained Google Speech Recognition only as an explicit optional online adapter requiring user consent.
- Added a deterministic core test suite and development packaging metadata.

This release is an initial modernization foundation. Incremental live Whisper streaming, waveform rendering, diarization, batch transcription, advanced audio restoration, and full segment-level editing are not represented as implemented features; see `docs/KNOWN_LIMITATIONS.md`.

## 2.1.0 — Professional workspace and Agent foundations

- Added a native workspace shell with collapsible navigation, global search/command navigation, resizable inspector and waveform/timeline docks, persisted layout state and keyboard shortcuts.
- Added centralized semantic design tokens and a selected, offline Lucide SVG icon subset with the upstream license. SVG assets are included in the installable Python package.
- Added segment-aware document operations, stable segment IDs, word-timing edits, split/merge/delete, speaker labels, bookmarks, comments, locking/review flags, snapshot undo/redo, regex search/replace, cleanup preview and evidence-based quality reporting.
- Added SQLite persistence for editor metadata and original-versus-edited transcript comparison.
- Added SRT/WebVTT/ASS/SSA import/export and subtitle timing transforms and validation.
- Added cached waveform generation, segment/playhead timeline rendering and non-destructive FFmpeg Audio Cleanup output.
- Added sequential Batch UI with per-file status, pause-after-current, retry, cancel-current and stop-queue controls.
- Added a generic resource-aware model runtime with RAM/VRAM estimates, configurable 1–10 loaded-model ceiling, lazy load, pinning, LRU eviction, active-inference protection and a priority job scheduler. The Faster-Whisper app manager remains single-active until a future migration.
- Added optional local Vosk wake/voice capture, configurable Agent permission levels and a persistent OpenCode ACP stdio session client.
- Added standalone MCP stdio entry point and compact action-discovery/execution tools over authenticated local IPC. Destructive actions require permission and an explicit GUI approval.
- Added tests for editor integrity, subtitles, cleanup atomicity, runtime concurrency/eviction, priority scheduling, IPC authentication, ACP session/prompt/cancel, quality reports, settings permissions and packaged icon assets.
- Updated feature extraction, architecture, README and known-limitations documentation.

This remains an alpha development snapshot. Live partial ASR, automatic diarization, integrated multi-engine/multi-model runtime, automatic ACP recovery, automatic voice prompt submission, TTS, video preview and PySide6 desktop smoke validation remain incomplete.
