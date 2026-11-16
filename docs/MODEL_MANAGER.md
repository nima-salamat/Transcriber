# Model Library, compatibility, import and downloads

## Discovery

`HuggingFaceHubClient` uses the official Hugging Face Hub API; it does not scrape HTML or fetch arbitrary URLs. An empty search uses the Hub's Automatic Speech Recognition task filter. A text search deliberately removes that API-level task filter and locally retains likely speech candidates based on pipeline metadata, repository names, tags and descriptions. This allows converted CTranslate2 repositories with incomplete/non-standard pipeline tags to be found.

Search results are candidates, not compatibility claims. The Inspect action reads the live repository file list, exact revision, sizes and model metadata. Install remains disabled until the CTranslate2 validator confirms the required root-level files. Missing descriptions, licenses, language tags and sizes remain unknown rather than being inferred from model names. Curated repository IDs are shortcuts, not compatibility guarantees.

## Faster-Whisper compatibility gate

The production local ASR adapter currently supports Faster-Whisper / CTranslate2 repositories. The validator requires root-level `model.bin`, `config.json`, `tokenizer.json`, and one supported vocabulary file (`vocabulary.txt`, `vocabulary.json`, or `vocab.json`). A regular Transformers/PyTorch checkpoint such as `pytorch_model.bin` is not accepted as a Faster-Whisper model. Nested model artefacts are not interpreted heuristically.

This is an engine-specific gate, not a statement that a repository cannot work with another runtime. Vosk, whisper.cpp and other model formats need their own adapters and validators. Hub metadata or a model name never bypasses local file inspection.

## Inspect and install

Inspect runs in a background worker. The card shows the returned file list, measured sizes, license, revision and the compatibility validator's reason. Network, access, metadata and compatibility errors are shown on the card. Installation is explicit and requires an inspected compatible result and a pinned revision.

The download service inspects again, pins the returned Hub commit, chooses only the compatible file set and writes into a per-task staging directory. After revalidation, it writes a local manifest, atomically publishes the directory and updates the registry. A model is not marked installed merely because a folder exists. If registry persistence fails, the previous directory is restored.

## Persistent Downloads

Every download has a SQLite task ID, repository ID, exact pinned revision once inspection succeeds, managed target, state, byte counts, model metadata, timestamps and sanitized error text. The Downloads tab is backed by this ledger, not only an in-memory worker map.

States include Queued, Inspecting, Downloading, Validating, Installing, Installed, Paused, Stopped, Cancelled and Failed.

- **Pause** requests a stop at the next safe transfer boundary. It does not pretend that an active HTTP request can be suspended at an arbitrary byte.
- **Resume** reruns the same logical task ID at the same pinned revision. The temporary staging directory is rebuilt, and `hf_hub_download` reuses reusable blobs/partial data in the shared Hugging Face cache.
- **Stop** ends the current task while preserving the same logical task and the shared cache; the user can resume it later.
- **Cancel** marks the task cancelled. It keeps the shared cache too; cancelling a ledger task does not purge a cache shared with other downloads.
- **Restart** creates a new task ID after cancellation.
- **Application restart** changes queued/in-flight tasks to Stopped. They appear in Downloads and are never resumed silently.

The application does not run a background daemon. Active transfers stop when the process exits. The cache is not deleted by Pause, Stop or Cancel. There is no per-task cache purger because the Hub cache may contain blobs shared by multiple repositories/tasks.

Progress is persisted on state changes, each roughly 1 MiB of transfer progress, or once per second. Some cache hits do not generate network byte progress; the UI may therefore show a lower byte count before the validation/install stages complete. Unknown repository file sizes remain unknown, not zero.

## Local import

The Import tab accepts a local directory or ZIP archive and a local registry ID in `owner/model-name` form (for example `local/my-whisper-small`). Import copies only the validated root-level Faster-Whisper artefacts into managed storage and writes a `local-<content digest>` revision manifest. It rejects symbolic links, invalid layouts, unsafe ZIP paths, ZIP symbolic-link entries, excessive ZIP entry counts and archives whose declared uncompressed size exceeds the import limit. It does not overwrite an existing managed model ID.

Private or public Hub repository IDs are imported through Discover → Inspect → Install. Transcriber never bypasses gated repository access; users must satisfy Hub terms and provide credentials securely outside the UI.

## Authentication and trust

Public models do not require a token. For gated/private repositories, users must accept the publisher's terms on Hugging Face and configure `HF_TOKEN` in the process environment. Transcriber does not display the token, put it in command-line arguments, or intentionally persist it. Downloader error messages are redacted before being displayed or stored; logs record the repository and exception type rather than arbitrary Hub exception text. Model files are treated as data and never executed.

Users remain responsible for reviewing licenses and model-card provenance. Pinning a commit makes the downloaded revision reproducible; it does not certify the model as safe or accurate.

## Current boundaries

- Discovery is currently optimized for ASR / Whisper / CTranslate2. Non-ASR categories such as VAD, diarization, TTS, LLM and multimodal models are not installable through this registry.
- The import validator only supports Faster-Whisper / CTranslate2 root-level files; other model formats require a separate runtime/validator.
- No RAM/VRAM requirement is inferred from a model name. The size shown is the repository file size supplied by the Hub, not a guarantee of the memory needed at inference.
- The production application still uses a single-active Faster-Whisper model; the generic multi-model runtime is not yet the global inference service.


## Windows GPU runtime

Faster-Whisper uses CTranslate2 for local inference. GPU execution requires NVIDIA cuBLAS for CUDA 12 and cuDNN 9 for CUDA 12; installing only the display driver is not enough. See the upstream [Faster-Whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu) and NVIDIA's [Windows CUDA Python-wheel instructions](https://docs.nvidia.com/cuda/cuda-installation-guide-microsoft-windows/).

For a source checkout using the same virtual environment as Transcriber, install the optional Windows GPU extra:

```powershell
python -m pip install -e ".[asr,gpu]"
```

This adds NVIDIA's CUDA 12 cuBLAS, CUDA runtime and cuDNN 9 wheels. The cuDNN wheel is large (hundreds of megabytes), so it is intentionally not part of the default install. Before importing CTranslate2, Transcriber discovers the active environment's `site-packages/nvidia/*/bin` directories and registers them with Windows DLL search plus `PATH`. A system CUDA installation already on `PATH` continues to work.

Restart Transcriber after installing or changing CUDA libraries. The Python environment used for the install must be the same environment used to launch the application.

If Compute device is **Automatic**, Transcriber retries with CPU INT8 when the CUDA library is missing either while constructing the model or when Faster-Whisper first iterates its lazy result generator. If Compute device is explicitly **CUDA GPU**, it does not silently switch devices; the error explains how to install the runtime. Choose **CPU** for a deliberate CPU-only run.
