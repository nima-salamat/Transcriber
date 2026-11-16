# Unified Workspace Redesign

## Product objective

Transcriber is presented as one focused desktop workspace for importing audio/video, transcription, transcript correction, subtitle timing, recording and batch processing. The permanent feature sidebar and the eleven independent primary destinations are replaced by one shared work surface.

## Workspace composition

The current PySide6 workspace reuses the existing feature widgets as internal modes:

- **Transcribe** — media import, engine/model/language selection, recognition and first-pass text editing.
- **Segments** — segment timing, speaker metadata, split/merge, review state, bookmarks, notes and editing commands.
- **Captions** — subtitle formats and timing tools.
- **Record** — microphone capture and recording review.
- **Batch** — sequential multi-file queue.
- **Library** — nested Projects and Recordings views.
- **Audio cleanup** — non-destructive FFmpeg processing.

These modes live inside one `UnifiedWorkspace` widget. The existing `TranscriptDocument` and `CommandHistory` remain shared by the transcription and segment editing surfaces.

## Secondary surfaces

- Model Library opens in a dedicated large dialog so discovery, compatibility inspection, installation and download progress are not compressed into a small panel.
- Preferences opens in a dedicated dialog with the existing settings groups.
- Inspector / AI Assistant remains optional and hidden by default.
- The waveform timeline is fixed-height and hidden when no media is loaded. Its visibility preference is retained so it appears again when media is opened.
- The global command palette and search remain available from the application toolbar.

## State and compatibility

The workspace is a presentation-layer migration. It does not replace the ASR engine, audio decoder/player, recording backend, batch coordinator, SQLite repositories, model manager, CUDA runtime, OpenCode ACP, MCP bridge or permission system.

Existing data paths and SQLite schemas are unchanged. The old route IDs remain accepted by `MainWindow.navigate` as compatibility aliases and are mapped to the corresponding workspace tab or management dialog.

## Design constraints

- No permanent feature sidebar.
- One primary central workspace.
- Transcript, segment and caption views use the existing shared domain document.
- Optional panels do not consume the main editor width by default.
- Timeline height remains fixed at 172 logical pixels.
- Model management and preferences remain full-size secondary dialogs.
- Long-running operations continue to use the existing worker/thread-pool paths.

## Validation

The UI regression suite covers a single central workspace, route aliases, tool-button navigation, Library subviews, default panel visibility and the fixed waveform behavior. The full CI pipeline must still execute with the Qt offscreen runtime, followed by real Windows validation for audio devices and NVIDIA CUDA.
