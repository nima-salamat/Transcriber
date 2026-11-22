"""Permanent voice-agent shutdown tests that do not require local ASR dependencies."""
from __future__ import annotations

import pytest

from transcriber.assistant.speech_input import VoskVoiceAgent


def test_closed_voice_agent_cannot_start_again():
    agent = VoskVoiceAgent("unused-model-path", "transcriber")

    agent.close()

    assert agent.shutdown_requested is True
    assert agent.shutdown_complete is True
    with pytest.raises(RuntimeError, match="already been shut down"):
        agent.start()
