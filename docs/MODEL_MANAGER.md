# Model Library and installation

## Discovery

`HuggingFaceHubClient` uses `huggingface_hub.HfApi` for model search and repository inspection. It does not scrape Hub HTML. Search is limited to the automatic-speech-recognition task and supports name/publisher text plus download, like, and last-modified sorting. Curated IDs are shortcuts only: every card's repository details are fetched live. Missing descriptions, licenses, language tags, file sizes, and statistics remain unknown instead of being fabricated.

## Compatibility gate

The Faster-Whisper adapter expects a CTranslate2 Whisper repository layout. The validator currently requires root-level `model.bin`, `config.json`, `tokenizer.json`, and one supported vocabulary file (`vocabulary.txt`, `vocabulary.json`, or `vocab.json`). A regular Transformers/PyTorch checkpoint such as `pytorch_model.bin` is not accepted as a Faster-Whisper model. Nested model artefacts are intentionally rejected by this first validator rather than interpreted heuristically.

This is an engine-specific gate, not a general statement that a repository cannot work with another engine. Future engines need their own validators.

## Download lifecycle

1. The user explicitly confirms the repository, pinned revision, and license information before installation.
2. Transcriber inspects repository metadata and chooses only the required compatible model artefacts.
3. A per-model reservation prevents duplicate downloads. The download gate limits simultaneous Hub transfers; queued work can be cancelled before it gets a transfer slot.
4. `hf_hub_download` downloads to a model-specific staging folder at the Hub commit SHA. The Hub cache is used to support retry/resume behavior.
5. `tqdm` updates are converted into byte counts, percentage when size metadata is available, transfer speed, and ETA when calculable.
6. Required files are checked again locally. A manifest records repository ID, pinned revision, engine ID, selected files, and license.
7. The staging directory is atomically published into the managed model directory and registered. Reinstall keeps a recoverable previous directory until registry persistence succeeds.

A model is not installed merely because a folder exists. A compatible manifest and required files are required. Failed or cancelled staging folders are removed. A currently loaded model cannot be deleted or replaced; unload it first.

## Authentication and trust

Public models do not require a token. For gated/private repositories, the user must accept the publisher's terms on Hugging Face and configure `HF_TOKEN` in the environment. Transcriber does not bypass gates or fetch arbitrary URLs. Tokens are not displayed in the UI or intentionally written to logs. Model files are treated as data and are never executed by Transcriber.

Users remain responsible for reviewing repository license terms and model-card provenance before installing a model. Pinning the inspected commit makes the downloaded revision reproducible; it does not certify the model as safe or accurate.

## Built-in curated repository IDs

The curated shortcuts include Faster-Whisper tiny/base/small/medium/large-v3, a Faster-Distil Whisper large variant, a Distil-Whisper CTranslate2 repository, and a Turbo community repository. A shortcut may become unavailable, gated, or incompatible over time; the application shows the live inspection result and does not assume a curated ID is still valid.

## Current boundaries

- Search currently supports task filtering and text search, but not a dedicated language or hardware-requirements filter.
- Resource/RAM/VRAM estimates are not inferred from model names. They are not displayed unless the Hub supplies measurable repository file sizes.
- The app supports the Faster-Whisper/CTranslate2 validator only. Vosk and other model formats require a separate engine and validator.
- A retry uses the Hub cache; there is no separate UI to inspect or selectively purge individual cached blobs.
