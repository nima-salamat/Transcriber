# Known limitations of the 2.0 modernization

This release is a working local-first foundation, not yet the complete speech-production suite described in the product vision. The following are intentionally not advertised as implemented:

- **No incremental live Whisper dictation.** Microphone recording, pause/resume, level display, WAV finalization, and post-recording transcription work in the code, but live partial recognition, VAD chunking, overlap reconciliation, and final-segment merging are not implemented.
- **No Vosk adapter.** The engine interface is ready for additional engines; only Faster-Whisper and the opt-in Google SpeechRecognition adapter are present.
- **No speaker diarization.** The data/export formats can carry a speaker label, but no diarization model or speaker-assignment UI exists.
- **No rendered waveform.** Recording uses an RMS level meter; playback has a seek bar, not a waveform timeline.
- **No advanced audio processing suite.** No normalization/noise reduction, audio resampling controls, silence-removal editor, chunk-boundary editor, or A-B looping is exposed.
- **No batch project queue.** The generic cancellable job abstraction exists, but the UI does not yet offer batch multi-file prioritization, persistent job recovery, or a unified job-center page for every task type.
- **No full segment/word timeline editor.** The main editor is editable text. It propagates text changes to existing segment spans and preserves unchanged segment/word timing data, but does not yet provide visual segment splitting/merging, per-word timing adjustment, bookmark editing, or a dedicated segment table. Word times are cleared for a segment when its text changes because their old offsets are no longer reliable.
- **Limited Hub filters.** Live search supports the ASR task, query text, and download/like/updated sorting. Dedicated language, size, hardware, and quality filters are not implemented. RAM/VRAM estimates are not invented.
- **PDF RTL output depends on fonts.** ReportLab's default font lacks many RTL glyphs. For robust Persian/Arabic PDF output, install the optional shaping packages and configure `TRANSCRIBER_PDF_FONT` to a suitable font file. DOCX output sets RTL paragraph properties; fonts are supplied by the document viewer.
- **English UI only.** The language selector currently persists the built-in English setting; translated interface catalogs are not included yet. The selected microphone is managed on the Recording page rather than saved as a global default-device preference.
- **No native installer/release build in this repository change.** `pyproject.toml` supports editable installs and includes an optional PyInstaller extra, but signed Windows/macOS/Linux distributables have not been produced.
- **Runtime validation depends on the target desktop.** Automated tests in the development environment cover data, model validation/download behavior (mocked Hub transfer), job cancellation, and exporters. Actual Qt widget startup, device I/O, CUDA inference, and a real multi-gigabyte Hub download need validation on a machine with PySide6, Qt Multimedia/audio, Faster-Whisper, and the desired hardware installed.

The two legacy PNG screenshots are preserved only as historical assets; they do not show the redesigned UI. Fresh screenshots should be captured from an installed Qt runtime before a release.
