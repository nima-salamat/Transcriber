"""Official Hugging Face Hub API wrapper; no HTML scraping or arbitrary URLs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from transcriber.models.compatibility import validate_repo_id

CURATED_MODELS = (
    "Systran/faster-whisper-tiny",
    "Systran/faster-whisper-base",
    "Systran/faster-whisper-small",
    "Systran/faster-whisper-medium",
    "Systran/faster-whisper-large-v3",
    "Systran/faster-distil-whisper-large-v3",
    "distil-whisper/distil-large-v3-ct2",
    "aTrain-core/faster-whisper-large-v3-turbo",
)


@dataclass(frozen=True, slots=True)
class HubFile:
    name: str
    size: int | None = None


@dataclass(frozen=True, slots=True)
class HubModel:
    repo_id: str
    revision: str | None
    description: str | None
    task: str | None
    license: str | None
    downloads: int | None
    likes: int | None
    last_modified: str | None
    tags: tuple[str, ...]
    languages: tuple[str, ...]
    files: tuple[HubFile, ...]
    author: str | None
    url: str

    @property
    def total_size(self) -> int | None:
        if not self.files or any(item.size is None for item in self.files):
            return None
        return sum(item.size or 0 for item in self.files)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HuggingFaceHubClient:
    def __init__(self, token: str | None = None, timeout: float = 20):
        try:
            from huggingface_hub import HfApi
        except ImportError as exc:
            raise RuntimeError("Install the model-library dependency: Hugging Face Hub is already a core dependency; reinstall Transcriber if it is missing") from exc
        self.api = HfApi(token=token)
        self.timeout = timeout

    @staticmethod
    def _metadata(info: Any) -> HubModel:
        card = getattr(info, "card_data", None)
        card_data = card.to_dict() if card and hasattr(card, "to_dict") else {}
        siblings = getattr(info, "siblings", None) or []
        files = []
        for sibling in siblings:
            lfs = getattr(sibling, "lfs", None)
            size = getattr(lfs, "size", None) if lfs else None
            if size is None:
                size = getattr(sibling, "size", None)
            files.append(HubFile(str(getattr(sibling, "rfilename", "")), size))
        tags = tuple(str(item) for item in (getattr(info, "tags", None) or []))
        raw_languages = card_data.get("language") or card_data.get("languages") or []
        if isinstance(raw_languages, str):
            raw_languages = [raw_languages]
        languages = tuple(str(item) for item in raw_languages)
        if not languages:
            languages = tuple(tag.split(":", 1)[1] for tag in tags if tag.startswith("language:"))
        license_name = card_data.get("license")
        if not license_name:
            license_name = next((tag.split(":", 1)[1] for tag in tags if tag.startswith("license:")), None)
        repo_id = str(getattr(info, "id", ""))
        return HubModel(
            repo_id=repo_id, revision=getattr(info, "sha", None),
            description=str(card_data.get("description")) if card_data.get("description") else None,
            task=getattr(info, "pipeline_tag", None), license=license_name,
            downloads=getattr(info, "downloads", None), likes=getattr(info, "likes", None),
            last_modified=str(getattr(info, "last_modified", "") or "") or None,
            tags=tags, languages=languages, files=tuple(files),
            author=getattr(info, "author", None) or repo_id.split("/", 1)[0],
            url=f"https://huggingface.co/{repo_id}",
        )

    def search(self, query: str = "", *, sort: str = "downloads", limit: int = 30) -> list[HubModel]:
        sort_key = {"lastModified": "last_modified", "last_modified": "last_modified"}.get(sort, sort)
        if sort_key not in {"downloads", "likes", "last_modified"}:
            sort_key = "downloads"
        models = self.api.list_models(
            search=query.strip() or None,
            pipeline_tag="automatic-speech-recognition",
            sort=sort_key,
            limit=max(1, min(limit, 100)), full=True, cardData=True,
        )
        results: list[HubModel] = []
        for model in models:
            model_id = getattr(model, "id", None)
            if not model_id:
                continue
            try:
                validate_repo_id(model_id)
                results.append(self._metadata(model))
            except ValueError:
                continue
        return results

    def inspect(self, repo_id: str, revision: str | None = None) -> HubModel:
        repo_id = validate_repo_id(repo_id)
        try:
            info = self.api.model_info(repo_id, revision=revision, files_metadata=True, timeout=self.timeout)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {401, 403}:
                raise PermissionError(
                    "Hugging Face denied access. This repository may be gated or private. "
                    "Open the model page, accept its terms if required, then set HF_TOKEN in your environment."
                ) from exc
            raise
        return self._metadata(info)

    def curated(self) -> tuple[str, ...]:
        """Return IDs only; callers must inspect live metadata before rendering details."""
        return CURATED_MODELS
