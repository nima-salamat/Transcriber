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
| Recordings | user data `recordings/` by default | user data `recordings/` by default |

Exact Windows cache/log subdirectory names follow the active `platformdirs` version and platform conventions. Model and recording directories can be changed in Settings; restart is required for those overrides to take effect. The transcript database and settings remain in their standard data/config locations.

## Database and files

- `transcripts.sqlite3` stores transcript text, original recognized text, source path, engine/model metadata, tags/favorites, timed segments, and optional word timings.
- SQLite foreign keys link ordered segments to their transcript. The database layer handles the current schema version and adds the word-timing column when opening a prior schema.
- Settings and the installed-model registry are JSON files written through temporary files and atomic replacement.
- Downloaded model repositories live under the configured models directory. Incomplete downloads use a `.staging` subdirectory. Hugging Face's cache is placed under the application cache directory.
- Recordings are WAV files at the user-selected save path. The app does not duplicate imported files into its own directory; the history stores their source path.
- Rotating application logs are stored in the per-user log directory. Tokens and authorization headers must not be logged.

## Backup and restore

Metadata backups include `transcripts.sqlite3` (using SQLite's backup API) and `settings.json`. Models, recordings, Hub cache, and logs are excluded. Restore validates the zip structure, settings JSON, and SQLite integrity before swapping files; replacement is rolled back if a later replacement step fails. Restore should only be started when other background work is idle, and the application must be restarted to reload restored settings/history.

## Retention and deletion

Deleting a transcript deletes its database row and timed segments, not the source audio file. Deleting a model removes only that managed model directory and its registry entry; the active model must be unloaded first. Clearing the Hub cache does not remove installed models. The app does not yet provide automatic recording retention or orphaned-media cleanup, so user-created recordings and external source files remain under the user's control.
