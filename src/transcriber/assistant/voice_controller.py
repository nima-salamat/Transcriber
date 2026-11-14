"""Small, explicit voice-agent state machine (audio capture is separately opt-in)."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread, current_thread
from time import monotonic


class VoiceState(StrEnum):
    DISABLED = "disabled"
    SLEEPING = "sleeping"
    WAKE_LISTENING = "wake_listening"
    WAKE_DETECTED = "wake_detected"
    LOADING_AGENT = "loading_agent"
    LISTENING = "listening"
    RECOGNIZING = "recognizing"
    THINKING = "thinking"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    SPEAKING = "speaking"
    COMPLETED = "completed"
    ERROR = "error"


_ALLOWED = {
    VoiceState.DISABLED: {VoiceState.SLEEPING},
    VoiceState.SLEEPING: {VoiceState.WAKE_LISTENING, VoiceState.LISTENING, VoiceState.DISABLED},
    VoiceState.WAKE_LISTENING: {VoiceState.WAKE_DETECTED, VoiceState.SLEEPING, VoiceState.DISABLED, VoiceState.ERROR},
    VoiceState.WAKE_DETECTED: {VoiceState.LOADING_AGENT, VoiceState.LISTENING, VoiceState.ERROR, VoiceState.SLEEPING},
    VoiceState.LOADING_AGENT: {VoiceState.LISTENING, VoiceState.ERROR, VoiceState.SLEEPING},
    VoiceState.LISTENING: {VoiceState.RECOGNIZING, VoiceState.SLEEPING, VoiceState.DISABLED, VoiceState.ERROR},
    VoiceState.RECOGNIZING: {VoiceState.THINKING, VoiceState.ERROR, VoiceState.SLEEPING},
    VoiceState.THINKING: {VoiceState.EXECUTING, VoiceState.WAITING_APPROVAL, VoiceState.COMPLETED, VoiceState.ERROR},
    VoiceState.EXECUTING: {VoiceState.WAITING_APPROVAL, VoiceState.SPEAKING, VoiceState.COMPLETED, VoiceState.ERROR},
    VoiceState.WAITING_APPROVAL: {VoiceState.EXECUTING, VoiceState.SLEEPING, VoiceState.ERROR},
    VoiceState.SPEAKING: {VoiceState.COMPLETED, VoiceState.ERROR, VoiceState.SLEEPING},
    VoiceState.COMPLETED: {VoiceState.SLEEPING, VoiceState.WAKE_LISTENING, VoiceState.LISTENING, VoiceState.DISABLED},
    VoiceState.ERROR: {VoiceState.SLEEPING, VoiceState.DISABLED, VoiceState.WAKE_LISTENING},
}


class VoiceAgentController:
    def __init__(self, *, wake_enabled: bool = False, auto_sleep_seconds: int = 30,
                 on_state: Callable[[VoiceState], None] | None = None):
        self.wake_enabled = bool(wake_enabled)
        self.auto_sleep_seconds = max(5, min(600, int(auto_sleep_seconds)))
        self.state = VoiceState.SLEEPING if wake_enabled else VoiceState.DISABLED
        self.on_state = on_state
        self._last_activity = monotonic()
        self._lock = RLock()

    def transition(self, new_state: VoiceState | str) -> None:
        target = VoiceState(new_state)
        with self._lock:
            if target == self.state:
                return
            if target not in _ALLOWED[self.state]:
                raise ValueError(f"Invalid voice transition: {self.state.value} -> {target.value}")
            self.state = target
            self._last_activity = monotonic()
        if self.on_state:
            self.on_state(target)

    def enable_wake_word(self, enabled: bool) -> None:
        self.wake_enabled = bool(enabled)
        if enabled:
            if self.state in {VoiceState.DISABLED, VoiceState.COMPLETED, VoiceState.ERROR}:
                self.transition(VoiceState.SLEEPING)
            if self.state == VoiceState.SLEEPING:
                self.transition(VoiceState.WAKE_LISTENING)
        else:
            if self.state == VoiceState.WAKE_LISTENING:
                self.transition(VoiceState.SLEEPING)
            if self.state == VoiceState.SLEEPING:
                self.transition(VoiceState.DISABLED)

    def push_to_talk(self) -> None:
        if self.state in {VoiceState.DISABLED, VoiceState.ERROR}:
            raise RuntimeError("Enable the voice agent before using push-to-talk")
        if self.state in {VoiceState.SLEEPING, VoiceState.WAKE_LISTENING, VoiceState.COMPLETED}:
            self.transition(VoiceState.LISTENING)

    def wake_detected(self) -> None:
        if self.state != VoiceState.WAKE_LISTENING:
            return
        self.transition(VoiceState.WAKE_DETECTED)
        self.transition(VoiceState.LOADING_AGENT)
        self.transition(VoiceState.LISTENING)

    def activity(self) -> None:
        with self._lock:
            self._last_activity = monotonic()

    def poll_auto_sleep(self) -> bool:
        with self._lock:
            expired = monotonic() - self._last_activity >= self.auto_sleep_seconds
            state = self.state
        if expired and state in {VoiceState.LISTENING, VoiceState.THINKING, VoiceState.COMPLETED}:
            if state == VoiceState.THINKING:
                return False
            self.transition(VoiceState.SLEEPING)
            if self.wake_enabled:
                self.transition(VoiceState.WAKE_LISTENING)
            return True
        return False

    def stop(self) -> None:
        if self.state in {VoiceState.DISABLED, VoiceState.SLEEPING}:
            return
        # Explicit stop is allowed from any active stage, including an in-flight
        # command. The capture owner must stop its audio stream at the same time.
        with self._lock:
            self.state = VoiceState.SLEEPING if self.wake_enabled else VoiceState.DISABLED
            target = self.state
            self._last_activity = monotonic()
        if self.on_state:
            self.on_state(target)


class VoskWakeWordDetector:
    """Optional phrase detector with lightweight callback and bounded worker queue."""

    def __init__(self, model_path, phrase: str, *, device=None, on_wake=None, on_error=None):
        self.model_path = str(model_path)
        self.phrase = " ".join(phrase.casefold().split())
        self.device = device
        self.on_wake = on_wake
        self.on_error = on_error
        self._stream = None
        self._recognizer = None
        self._model = None
        self._audio_queue: Queue[bytes] | None = None
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._queue_overflows = 0
        self._device_status_events = 0
        self._metrics_lock = RLock()

    def start(self) -> None:
        if not self.phrase:
            raise ValueError("Wake phrase cannot be empty")
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise RuntimeError("Local Vosk wake detection requires the optional voice dependencies") from exc
        if self._stream is not None:
            return
        if self._worker is not None and self._worker.is_alive():
            raise RuntimeError("The previous Vosk detector worker is still shutting down.")
        self._model = Model(self.model_path)
        self._recognizer = KaldiRecognizer(self._model, 16000, json.dumps([self.phrase]))
        self._recognizer.SetWords(False)
        self._audio_queue = Queue(maxsize=40)
        self._stop_event.clear()
        self._queue_overflows = 0
        self._device_status_events = 0
        self._worker = Thread(
            target=self._recognition_loop,
            name="Transcriber-Vosk-wake",
            daemon=True,
        )
        self._stream = sd.RawInputStream(
            samplerate=16000, blocksize=4000, device=self.device,
            dtype="int16", channels=1, callback=self._audio_callback,
        )
        self._worker.start()
        try:
            self._stream.start()
        except Exception:
            self.stop()
            raise

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """Only enqueue PCM; recognition and JSON parsing run on the worker."""
        if status:
            with self._metrics_lock:
                self._device_status_events += 1
        audio_queue = self._audio_queue
        if self._stop_event.is_set() or audio_queue is None:
            return
        try:
            audio_queue.put_nowait(bytes(indata))
        except Full:
            with self._metrics_lock:
                self._queue_overflows += 1

    def _recognition_loop(self):
        try:
            while not self._stop_event.is_set():
                audio_queue = self._audio_queue
                recognizer = self._recognizer
                if audio_queue is None or recognizer is None:
                    return
                try:
                    payload = audio_queue.get(timeout=0.15)
                except Empty:
                    self._report_audio_metrics()
                    continue
                if self._stop_event.is_set():
                    break
                if recognizer.AcceptWaveform(payload):
                    try:
                        recognized = json.loads(recognizer.Result()).get("text", "")
                    except (ValueError, TypeError):
                        recognized = ""
                    normalized = " ".join(str(recognized).casefold().split())
                    if normalized == self.phrase and self.on_wake:
                        try:
                            self.on_wake()
                        except Exception as exc:
                            self._report_error(str(exc))
                self._report_audio_metrics()
        except Exception as exc:
            self._report_error(str(exc))
            self._stop_event.set()

    def _report_audio_metrics(self):
        with self._metrics_lock:
            overflows, self._queue_overflows = self._queue_overflows, 0
            status_events, self._device_status_events = self._device_status_events, 0
        if overflows:
            self._report_error(f"Vosk wake queue overflow; dropped {overflows} audio chunks")
        if status_events:
            self._report_error(f"Microphone reported {status_events} audio status event(s)")

    def _report_error(self, message: str):
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        self._stop_event.set()
        if stream:
            try:
                stream.stop()
            finally:
                stream.close()
        worker = self._worker
        if worker and worker.ident is not None and worker is not current_thread():
            worker.join(timeout=5.0)
            if worker.is_alive():
                self._report_error("Vosk wake detector is still shutting down.")
                return
        self._worker = None
        self._recognizer = None
        self._model = None
        self._audio_queue = None
