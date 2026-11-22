from __future__ import annotations

import pytest

from transcriber.audio.recorder import QtAudioRecorder, _waveform_display_peak
from transcriber.ui.pages.recording import _record_button_enabled_for_state


def test_quiet_microphone_peaks_are_visible_in_the_waveform() -> None:
    assert _waveform_display_peak(0.0) == pytest.approx(0.025)
    assert _waveform_display_peak(0.001) > 0.04
    assert _waveform_display_peak(0.01) > 0.12
    assert _waveform_display_peak(0.25) > _waveform_display_peak(0.01)
    assert _waveform_display_peak(1.0) == pytest.approx(1.0)


def test_discarded_take_returns_the_recorder_to_a_clean_idle_state() -> None:
    recorder = QtAudioRecorder()
    recorder._state = "idle"
    recorder._data_bytes = 16_000
    recorder._elapsed_before_pause = 2.0
    recorder._started = 123.0
    recorder._peaks = [0.2, 0.4, 0.8]
    recorder.device_id = "old-device"
    recorder.device_name = "Old microphone"

    recorder.cancel()

    assert recorder._state == "idle"
    assert recorder.duration() == 0.0
    assert recorder.waveform == []
    assert recorder._data_bytes == 0
    assert recorder.device_id is None
    assert recorder.device_name is None
    recorder.deleteLater()


@pytest.mark.parametrize("state", ["idle", "cancelled"])
def test_record_button_can_start_after_discard(state: str) -> None:
    assert _record_button_enabled_for_state(state, has_usable_input=True)
    assert not _record_button_enabled_for_state(state, has_usable_input=False)


def test_record_button_stays_available_during_active_capture() -> None:
    assert _record_button_enabled_for_state("recording", has_usable_input=False)
    assert _record_button_enabled_for_state("paused", has_usable_input=False)
