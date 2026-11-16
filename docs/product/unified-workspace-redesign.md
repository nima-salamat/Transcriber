# Unified Workspace Redesign

## Objective

Reduce the feeling that Transcriber is a collection of unrelated pages. The primary experience is now one workspace for preparing media, transcribing, reviewing segments and creating captions. Secondary administration and management tasks remain available without occupying permanent navigation space.

This change is a UI composition redesign. It intentionally reuses the current PySide6 pages, document model, audio player, model manager and services instead of replacing working domain logic.

## New information architecture

### Primary workspace

The main window has one compact toolbar and a central workspace stack.

- **Transcript** — import media, configure recognition, transcribe and edit the main text.
- **Segments** — inspect and edit timed segments, speaker assignments, review state and other existing segment metadata.
- **Captions** — import, edit, validate and export subtitle cues.
- **Record** — microphone recording is an in-workspace mode.
- **Batch** — the existing sequential processing queue is an in-workspace mode.

Transcript, Segments and Captions are presented as three modes of the same work context, not as permanent destinations in a left navigation rail. The existing `TranscriptDocument` and `CommandHistory` remain the shared source for transcript and segment editing; the existing synchronization signals continue to reconcile caption edits with the document.

### Secondary tools

- **Library dialog:** Projects and Recordings tabs. Selecting a project or audio recording continues to open it in the primary workspace.
- **Model Manager dialog:** installed models, discovery, validation, download and lifecycle management.
- **Preferences dialog:** existing audio, recognition, privacy, storage, runtime and Agent settings.
- **Audio Cleanup dialog:** existing non-destructive processing workflow.
- **Contextual Inspector:** Properties and AI Assistant tabs in a resizable right panel. It is hidden by default.
- **Command palette / global search:** remain available without leaving the active workspace mode.

The Library, Model Manager, Preferences and Cleanup still use their existing page widgets and services. They are hosted by non-modal dialogs rather than recreated as simplified feature stubs.

## Audio experience

A new `AudioTransportBar` displays compact playback controls once media is loaded. It references the same `AudioPlayer` instance owned by `TranscriptionPage`; it does not create a second player.

The previous transport card remains part of the legacy transcription-page implementation but is hidden by the main workspace, avoiding two visible sets of play/seek/volume controls.

The bottom waveform/timeline is fixed at 148 pixels and can be hidden or shown. The Inspector remains horizontally resizable through the explicit left-to-right workspace splitter.

The recognition panel keeps engine, model and language in the normal view. Beam size, VAD, task, word timestamps and the initial prompt are grouped under a collapsed **Advanced options** disclosure. The top toolbar becomes denser below normal desktop widths by hiding global search and the optional AI shortcut and shortening secondary labels; Ctrl+K remains available.

## Visual system

The redesigned shell uses the existing semantic dark/light tokens and Lucide icon registry. New styles cover:

- Workspace toolbar surface
- Transcript / Segments / Captions mode selector
- Shared audio transport
- Primary playback button

The native window frame remains in place. The new shell does not introduce a frameless window or a new UI dependency.

## Feature migration map

| Previous destination | New location |
|---|---|
| Home | Empty state within Transcript workspace |
| New Transcription | Transcript mode |
| Transcript Editor | Segments mode |
| Subtitles & Timing | Captions mode |
| Record Audio | Record mode / toolbar |
| Batch Processing | Batch mode / toolbar |
| Projects / History | Library → Projects |
| Audio Library / Recordings | Library → Recordings |
| AI Models | Model Manager dialog |
| Audio Cleanup | Audio Cleanup dialog / Tools menu |
| Settings | Preferences dialog / More menu |
| AI Assistant | Optional Inspector |

## Preservation constraints

This UI change does not claim to add capabilities that are not present in the existing services. In particular:

- Live Partial Whisper transcription is still not implemented.
- Automatic speaker diarization is still not implemented; speaker assignment remains manual.
- Video preview and subtitle burn-in are not provided.
- Batch processing remains sequential and session-scoped.
- The integrated Faster-Whisper model manager remains single-active-model.
- Caption timing operations remain limited to the current subtitle editor capabilities.
- No restart recovery for the batch queue is introduced.

Audio cleanup continues to write a separate output and must not overwrite the source automatically. Local-first behavior and explicit consent for online recognition remain unchanged.

## Validation added

The workspace UI tests now cover:

- No permanent sidebar / multi-destination navigation.
- Transcript, Segments and Captions as central workspace modes.
- Record and Batch as additional work modes.
- Library, Model Manager, Preferences and Cleanup dialog hosting.
- Optional Inspector and discoverable panel toggles.
- Fixed 148-pixel timeline height.
- Shared AudioPlayer controller and hidden duplicate player card.
- Global search and command palette behavior.
- Inspector resizing and waveform seeking.

The test suite and a real Windows audio/CUDA smoke test still need to run in a PySide6-capable environment. Passing an offscreen UI test does not substitute for hardware validation.
