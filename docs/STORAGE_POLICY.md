# Storage policy

## Per-user directories

Transcriber uses `platformdirs` with the lowercase application ID `transcriber` and keeps runtime data outside the source checkout. The `TRANSCRIBER_HOME` environment variable overrides all standard locations for portable installs and tests.

Typical locations:

| Purpose | Windows | Linux |
|---|---|---|
| Configuration | `%APPDATA%\transcriber` | `~/.config/transcriber` |
| User data | `%LOCALAPPDATA%\transcriber` | `~/.local/share/transcriber` |
| Cache | `%LOCALAPPDATA%\transcriber\Cache` (platformdirs) | `~/.cache/transcriber` |
| Logs | platformdirs user log directory (commonly `%LOCALAPPDATA%\transcriber\Logs`) | `~/.local/state/transcriber/log` |
| Models | user data `models/` by default | user data `models/` by default |
| Recordings | `Music\\Transcriber Recordings` by default | `~/Music/Transcriber Recordings` by default |

Exact Windows cache/log subdirectory names follow the active `platformdirs` version and platform conventions. Model and recording directories can be changed in Settings; restart is required for those overrides to take effect. The transcript database and settings remain in their standard data/config locations.

## Database and files

- `transcripts.sqlite3` stores transcript text, original recognized text, source path, engine/model metadata, tags/favorites, timed segments, optional word timings, and an independent `recordings` table with recording ID, path, filename, duration, size, format, capture date and input-device metadata.
- SQLite foreign keys link ordered segments to their transcript. The database layer handles the current schema version and adds the word-timing column when opening a prior schema.
- Settings and the installed-model registry are JSON files written through temporary files and atomic replacement.
- Downloaded model repositories live under the configured models directory. Incomplete downloads use a `.staging` subdirectory. Hugging Face's cache is placed under the application cache directory.
- Microphone recordings use native 16-bit PCM WAV capture. The default target is `Music/Transcriber Recordings`; a saved recording receives its own SQLite metadata row independent from transcript history. Capture first writes a temporary file beside the destination and publishes it with an atomic replace only after the WAV header is finalized. Imported external audio remains referenced by path and is not copied by default. Older files in the former application data `recordings/` folder remain discoverable and are not moved automatically.
- Rotating application logs are stored in the per-user log directory. Tokens and authorization headers must not be logged.

## Backup and restore

Metadata backups include `transcripts.sqlite3` (using SQLite's backup API) and `settings.json`. Models, recordings, Hub cache, and logs are excluded. Restore validates the zip structure, settings JSON, and SQLite integrity before swapping files; replacement is rolled back if a later replacement step fails. Restore should only be started when other background work is idle, and the application must be restarted to reload restored settings/history.

## Retention and deletion

Deleting a transcript deletes its database row and timed segments, not the source audio file or independent recording metadata. Recording deletion is a separate, confirmed Library action; if transcripts reference that path, the user is warned and those transcripts remain with an unavailable source-audio reference. Rename updates transcript source paths transactionally. Deleting a model removes only that managed model directory and its registry entry; the active model must be unloaded first. Clearing the Hub cache does not remove installed models. There is no automatic recording retention or orphaned-media cleanup.
