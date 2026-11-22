from __future__ import annotations

import io
import urllib.error

import pytest

from transcriber.models import vosk


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None):
        self.status = status
        self.headers = headers or {}
        self._stream = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._stream.close()

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _transfer(partial, monkeypatch, opener, *, downloaded: int, total: int | None = None):
    updates = []
    monkeypatch.setattr(vosk.urllib.request, "urlopen", opener)
    result = vosk._download_vosk_archive(
        "https://alphacephei.com/vosk/models/test.zip",
        partial,
        timeout=5,
        downloaded=downloaded,
        total=total,
        check_events=lambda: None,
        progress=lambda current, size, message: updates.append((current, size, message)),
    )
    return result, updates


def test_vosk_resume_accepts_416_when_partial_is_already_complete(tmp_path, monkeypatch):
    archive = b"completed-archive"
    partial = tmp_path / "model.zip.partial"
    partial.write_bytes(archive)
    requests = []

    def opener(request, timeout):
        requests.append(request)
        assert request.get_header("Range") == f"bytes={len(archive)}-"
        raise urllib.error.HTTPError(
            request.full_url,
            416,
            "Range Not Satisfiable",
            {"Content-Range": f"bytes */{len(archive)}"},
            None,
        )

    result, _ = _transfer(partial, monkeypatch, opener, downloaded=len(archive))

    assert result == (len(archive), len(archive))
    assert partial.read_bytes() == archive
    assert len(requests) == 1


def test_vosk_resume_discards_stale_partial_after_416_and_restarts(tmp_path, monkeypatch):
    archive = b"fresh"
    partial = tmp_path / "model.zip.partial"
    partial.write_bytes(b"stale-partial-data-that-is-too-long")
    requests = []

    def opener(request, timeout):
        requests.append(request)
        if len(requests) == 1:
            assert request.get_header("Range") is not None
            raise urllib.error.HTTPError(
                request.full_url,
                416,
                "Range Not Satisfiable",
                {"Content-Range": f"bytes */{len(archive)}"},
                None,
            )
        assert request.get_header("Range") is None
        return FakeResponse(200, archive, {"Content-Length": str(len(archive))})

    result, updates = _transfer(
        partial, monkeypatch, opener, downloaded=partial.stat().st_size
    )

    assert result == (len(archive), len(archive))
    assert partial.read_bytes() == archive
    assert len(requests) == 2
    assert any("restarting from the beginning" in item[2] for item in updates)


def test_vosk_resume_appends_only_the_requested_206_byte_range(tmp_path, monkeypatch):
    partial = tmp_path / "model.zip.partial"
    partial.write_bytes(b"abc")
    requests = []

    def opener(request, timeout):
        requests.append(request)
        assert request.get_header("Range") == "bytes=3-"
        return FakeResponse(
            206,
            b"def",
            {"Content-Range": "bytes 3-5/6", "Content-Length": "3"},
        )

    result, _ = _transfer(partial, monkeypatch, opener, downloaded=3)

    assert result == (6, 6)
    assert partial.read_bytes() == b"abcdef"
    assert len(requests) == 1


def test_vosk_resume_replaces_partial_when_server_ignores_range(tmp_path, monkeypatch):
    partial = tmp_path / "model.zip.partial"
    partial.write_bytes(b"old-prefix")
    archive = b"new-complete-archive"

    def opener(request, timeout):
        assert request.get_header("Range") == f"bytes={len(b'old-prefix')}-"
        return FakeResponse(200, archive, {"Content-Length": str(len(archive))})

    result, _ = _transfer(partial, monkeypatch, opener, downloaded=len(b"old-prefix"))

    assert result == (len(archive), len(archive))
    assert partial.read_bytes() == archive



def test_vosk_download_stops_before_writing_bytes_beyond_pinned_size(tmp_path, monkeypatch):
    partial = tmp_path / "model.zip.partial"
    response = FakeResponse(200, b"this-is-larger-than-the-pinned-size")

    def opener(request, timeout):
        return response

    with pytest.raises(OSError, match="exceeded its expected size"):
        _transfer(
            partial,
            monkeypatch,
            opener,
            downloaded=0,
            total=5,
        )

    assert not partial.exists()
