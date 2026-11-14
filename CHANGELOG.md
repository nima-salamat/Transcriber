# Changelog

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
