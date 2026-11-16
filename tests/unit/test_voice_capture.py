from __future__ import annotations

from transcriber.assistant.speech_input import AudioSilenceGate


def test_silence_gate_requires_the_full_continuous_silence_window():
    gate = AudioSilenceGate(silence_seconds=1.5)

    assert gate.observe(900.0, 10.0)
    assert not gate.should_finish(10.9)
    assert not gate.should_finish(11.49)
    assert gate.should_finish(11.5)


def test_silence_gate_resets_the_silence_window_when_speech_resumes():
    gate = AudioSilenceGate(silence_seconds=1.5)

    gate.observe(900.0, 1.0)
    assert not gate.should_finish(2.0)
    gate.observe(950.0, 2.2)

    assert not gate.should_finish(3.6)
    assert gate.should_finish(3.71)


def test_silence_before_the_first_speech_does_not_finish_a_command():
    gate = AudioSilenceGate(silence_seconds=1.5)

    gate.observe(20.0, 0.0)
    gate.observe(25.0, 5.0)

    assert not gate.has_speech
    assert not gate.should_finish(30.0)
