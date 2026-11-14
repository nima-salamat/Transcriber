# Architecture

## Runtime composition

`python -m transcriber` (or the `transcriber` console command) enters through `transcriber.__main__` and `bootstrap.build_services()`. The bootstrap module resolves per-user paths, loads validated settings, configures rotating logs, initializes SQLite, and wires the Hugging Face client, model registry, downloader, and model manager. The UI receives these services through constructors; it does not create its own database or model registry.

`APP.py` is only a source-checkout compatibility launcher. There is no second copy of the former 1.x interface.

## Package boundaries

- `core`: validated settings, application paths, logging, and domain errors. It does not import Qt widgets.
- `audio`: device enumeration, microphone capture, audio-file validation, and playback wrappers.
- `engines`: the `TranscriptionEngine` interface plus concrete Faster-Whisper and opt-in Google adapters. Engines accept paths/options/cancellation/progress and return typed results; they do not know about widgets or SQLite.
- `models`: Hugging Face API access, CTranslate2 compatibility checks, pinned-revision downloads, registry persistence, and active-model lifecycle.
- `transcription`: shared transcript/word/segment types, service orchestration, export adapters, and a generic job queue.
- `storage`: schema initialization, transcript repository operations, and metadata backup/restore.
- `ui`: Qt main window, navigation, page widgets, themes, and `QRunnable` worker adapters.

The dependency direction is UI → services/repositories/engine interfaces. The ASR adapter does not import the UI, and persistence does not depend on any Qt widgets.

## Threading model

The GUI creates one bounded `QThreadPool`. Hub queries, model inspection/installation/loading, transcription inference, transcript list/search queries, storage accounting, export, and backup operations run through `FunctionWorker`/`QRunnable`. Worker signals return results/errors to the GUI thread; workers never mutate widgets directly.

Model downloads have a separate configurable concurrency gate. The global Qt pool is sized to leave capacity for UI-adjacent tasks while respecting that download limit. Model swaps and load/unload operations are serialized behind a manager lock, and unload requests are dispatched to the worker pool. The generic `JobQueue` in `transcription/jobs.py` provides typed job state and cancellation for service integrations, but the current UI does not yet route every activity through a single persistent application-wide job database.

Transcript autosaves capture immutable project snapshots. Writes are serialized through a queue and coalesced per project, so a pending write remains attached to the transcript that was edited even when the user switches to another audio file or history item. The final shutdown flush drains queued snapshots after workers stop.

On shutdown, the UI requests cancellation, clears queued runnables, waits for active workers, flushes current and queued transcript snapshots, and only then unloads the active model. If an uncancellable task remains after the bounded close wait, the close is rejected rather than silently killing a worker while it writes data.

## Persistence

SQLite is the source of truth for transcript history and ordered timed segments. The schema has an explicit version marker; initialization creates missing tables/indexes and adds the word-timing column to older databases. Settings and the model registry use temporary files plus atomic replacement. The backup archive contains only metadata (database and settings), not large media/model directories.

See [Storage policy](STORAGE_POLICY.md) for locations, backup scope, and retention behavior.
