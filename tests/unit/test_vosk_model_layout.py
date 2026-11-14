from __future__ import annotations

import hashlib
import io
import threading
import zipfile

from transcriber.models import vosk
from transcriber.models.manager import ModelManager
from transcriber.models.registry import ModelRegistry


def _write_vosk_v2_model(root, *, feature="mfcc"):
    (root / "am").mkdir(parents=True, exist_ok=True)
    (root / "conf").mkdir(parents=True, exist_ok=True)
    (root / "graph").mkdir(parents=True, exist_ok=True)
    (root / "am" / "final.mdl").write_bytes(b"model")
    (root / "conf" / "model.conf").write_text("--beam=13", encoding="utf-8")
    (root / "conf" / f"{feature}.conf").write_text("--sample-frequency=16000", encoding="utf-8")
    (root / "graph" / "HCLG.fst").write_bytes(b"graph")
    (root / "graph" / "words.txt").write_text("<eps> 0\n", encoding="utf-8")


def test_vosk_validator_finds_model_nested_under_multiple_wrapper_directories(tmp_path):
    extracted = tmp_path / "extracted"
    model_root = extracted / "mirror" / "download" / "vosk-model-small-fa-0.42"
    _write_vosk_v2_model(model_root)

    found_root, report = vosk._find_vosk_model_directory(extracted)

    assert report.compatible
    assert found_root == model_root
    assert vosk.validate_vosk_model_directory(extracted).compatible


def test_vosk_v2_accepts_fbank_without_mfcc_configuration(tmp_path):
    model_root = tmp_path / "model"
    _write_vosk_v2_model(model_root, feature="fbank")

    report = vosk.validate_vosk_model_directory(model_root)

    assert report.compatible
    assert "conf/fbank.conf" in report.included_files
    assert "conf/mfcc.conf or conf/fbank.conf" not in report.missing_files


def test_vosk_legacy_layout_is_supported(tmp_path):
    model_root = tmp_path / "legacy"
    model_root.mkdir()
    (model_root / "final.mdl").write_bytes(b"model")
    (model_root / "mfcc.conf").write_text("--sample-frequency=16000", encoding="utf-8")
    (model_root / "HCLG.fst").write_bytes(b"graph")
    (model_root / "words.txt").write_text("<eps> 0\n", encoding="utf-8")

    report = vosk.validate_vosk_model_directory(model_root)

    assert report.compatible
    assert "final.mdl" in report.included_files


class FakeResponse:
    def __init__(self, payload: bytes):
        self.status = 200
        self.headers = {"Content-Length": str(len(payload))}
        self.stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.stream.close()

    def read(self, size=-1):
        return self.stream.read(size)


def test_vosk_download_installs_model_from_deeply_nested_archive(tmp_path, monkeypatch):
    archive_stream = io.BytesIO()
    model_name = "vosk-model-small-zz-0.42"
    prefix = f"third-party/mirror/package/{model_name}/"
    with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(prefix + "am/final.mdl", b"model")
        archive.writestr(prefix + "conf/model.conf", "--beam=13")
        archive.writestr(prefix + "conf/fbank.conf", "--sample-frequency=16000")
        archive.writestr(prefix + "graph/HCLG.fst", b"graph")
        archive.writestr(prefix + "graph/words.txt", "<eps> 0\n")
    payload = archive_stream.getvalue()

    model = vosk.VoskModelInfo(
        repo_id=f"vosk/{model_name}",
        name=model_name,
        language="zz",
        language_name="Test",
        model_type="small",
        size_bytes=len(payload),
        size_text=f"{len(payload)} bytes",
        md5=hashlib.md5(payload).hexdigest(),
        url=vosk.MODEL_PAGE_URL,
        download_url=f"https://alphacephei.com/vosk/models/{model_name}.zip",
        version="0.42",
    )

    class Catalog:
        @staticmethod
        def by_name(_model_id, *, include_obsolete=False):
            return model

    monkeypatch.setattr(
        vosk.urllib.request,
        "urlopen",
        lambda _request, timeout: FakeResponse(payload),
    )
    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    downloader = vosk.VoskModelDownloader(registry, Catalog())

    installed = downloader.download(model.repo_id)

    assert registry.get_path(model.repo_id) == installed
    assert (installed / "am" / "final.mdl").read_bytes() == b"model"
    assert (installed / "conf" / "fbank.conf").is_file()
    assert vosk.validate_vosk_model_directory(installed).compatible



def test_manual_vosk_zip_import_uses_the_inner_model_root(tmp_path):
    archive_path = tmp_path / "nested-vosk-model.zip"
    model_name = "vosk-model-small-fa-0.42"
    prefix = f"mirror/package/{model_name}/"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(prefix + "am/final.mdl", b"model")
        archive.writestr(prefix + "conf/model.conf", "--beam=13")
        archive.writestr(prefix + "conf/mfcc.conf", "--sample-frequency=16000")
        archive.writestr(prefix + "graph/HCLG.fst", b"graph")
        archive.writestr(prefix + "graph/words.txt", "<eps> 0\n")

    registry = ModelRegistry(tmp_path / "models", tmp_path / "registry.json")
    manager = object.__new__(ModelManager)
    manager.registry = registry
    manager._lock = threading.RLock()
    manager._installing = set()
    manager._active_model_id = None

    imported = manager.import_vosk_zip(
        archive_path, "local/vosk-test", language_code="fa"
    )

    assert registry.get_path("local/vosk-test") == imported
    assert (imported / "am" / "final.mdl").read_bytes() == b"model"
    assert not (imported / "mirror").exists()
    assert vosk.validate_vosk_model_directory(imported).compatible



def test_vosk_hclg_graph_may_embed_words_without_words_txt(tmp_path):
    model_root = tmp_path / "model"
    _write_vosk_v2_model(model_root)
    (model_root / "graph" / "words.txt").unlink()

    report = vosk.validate_vosk_model_directory(model_root)

    assert report.compatible
    assert "graph/words.txt" not in report.included_files


def test_vosk_lookahead_graph_requires_disambiguation_symbols(tmp_path):
    model_root = tmp_path / "model"
    (model_root / "am").mkdir(parents=True)
    (model_root / "conf").mkdir()
    (model_root / "graph").mkdir()
    (model_root / "am" / "final.mdl").write_bytes(b"model")
    (model_root / "conf" / "model.conf").write_text("--beam=13", encoding="utf-8")
    (model_root / "conf" / "fbank.conf").write_text("--sample-frequency=16000", encoding="utf-8")
    (model_root / "graph" / "HCLr.fst").write_bytes(b"hcl")
    (model_root / "graph" / "Gr.fst").write_bytes(b"g")

    incomplete = vosk.validate_vosk_model_directory(model_root)
    assert not incomplete.compatible
    assert "graph/disambig_tid.int" in incomplete.missing_files

    (model_root / "graph" / "disambig_tid.int").write_text("0\\n", encoding="utf-8")
    complete = vosk.validate_vosk_model_directory(model_root)
    assert complete.compatible
