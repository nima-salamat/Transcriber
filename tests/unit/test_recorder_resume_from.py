from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from PySide6.QtMultimedia import QAudioFormat

from transcriber.audio.recorder import QtAudioRecorder


def test_resume_from_truncates_take_at_selected_pcm_frame() -> None:
    recorder = QtAudioRecorder()
    audio_format = QAudioFormat()
    audio_format.setSampleRate(8_000)
    audio_format.setChannelCount(1)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

    original_payload_bytes = 32_000
    stream = BytesIO(b"\0" * 44 + b"\x01\x00" * (original_payload_bytes // 2))
    resumed = []
    recorder._stream = stream
    recorder._format = audio_format
    recorder._source = SimpleNamespace(resume=lambda: resumed.append(True))
    recorder._state = "paused"
    recorder._data_bytes = original_payload_bytes
    recorder._elapsed_before_pause = 2.0
    recorder._peaks = [0.25] * 120

    recorder.resume_from(0.5)

    expected_bytes = int(0.5 * audio_format.sampleRate() * audio_format.bytesPerFrame())
    assert recorder._data_bytes == expected_bytes
    assert len(stream.getvalue()) == 44 + expected_bytes
    assert recorder._elapsed_before_pause == 0.5
    assert len(recorder.waveform) == 30
    assert recorder._state == "recording"
    assert resumed == [True]
    recorder.deleteLater()
