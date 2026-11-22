from __future__ import annotations

import io
import subprocess

from transcriber.audio import processing


def test_ffmpeg_is_started_with_hidden_console_flags(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "cleaned.wav"
    temporary = tmp_path / "cleaned.processing.wav"
    source.write_bytes(b"source")
    temporary.write_bytes(b"processed")

    monkeypatch.setattr(processing.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(processing, "hidden_subprocess_creation_flags", lambda: 0x08000000)

    captured = {}

    class CompletedProcess:
        returncode = 0
        stderr = io.StringIO("")

        @staticmethod
        def poll():
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return CompletedProcess()

    monkeypatch.setattr(processing.subprocess, "Popen", fake_popen)

    assert processing.process_audio(source, output, filters=["volume=1"]) == output
    assert captured["kwargs"]["creationflags"] == 0x08000000
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert output.read_bytes() == b"processed"
