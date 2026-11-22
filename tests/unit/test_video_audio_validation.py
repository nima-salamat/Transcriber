from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from transcriber.audio.decoder import inspect_video_audio_stream


def _fake_av(monkeypatch, *, audio_streams=1, duration=90):
    class FakeContainer:
        def __init__(self):
            self.streams = [
                SimpleNamespace(type="video"),
                *[SimpleNamespace(type="audio", duration=None, time_base=None) for _ in range(audio_streams)],
            ]
            self.duration = duration * 1_000_000

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    av = ModuleType("av")
    av.time_base = 1_000_000
    av.open = lambda _path: FakeContainer()
    monkeypatch.setitem(sys.modules, "av", av)


def test_video_preflight_reports_audio_tracks_and_duration(tmp_path, monkeypatch):
    _fake_av(monkeypatch, audio_streams=2, duration=90)
    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"video container")
    result = inspect_video_audio_stream(video)
    assert result.audio_stream_count == 2
    assert result.duration_seconds == pytest.approx(90.0)


def test_video_without_audio_is_rejected_before_asr(tmp_path, monkeypatch):
    _fake_av(monkeypatch, audio_streams=0)
    video = tmp_path / "silent.mp4"
    video.write_bytes(b"silent video")
    with pytest.raises(ValueError, match="No audio track"):
        inspect_video_audio_stream(video)


def test_audio_path_is_not_accepted_by_video_preflight(tmp_path):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    with pytest.raises(ValueError, match="Expected a supported video"):
        inspect_video_audio_stream(audio)
