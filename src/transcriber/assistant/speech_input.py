"""Local Vosk wake-word and command capture using a bounded audio queue.

The sounddevice callback only copies PCM into a bounded queue. All Vosk work,
noise tracking, silence detection and command finalization run on a dedicated
recognition worker. Raw audio is not persisted or uploaded.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from array import array
from collections.abc import Callable


class VoskVoiceAgent:
    def __init__(
        self,
        model_path,
        wake_phrase: str,
        *,
        device=None,
        on_state: Callable[[str], None] | None = None,
        on_transcript: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        silence_seconds: float = 1.25,
        max_command_seconds: float = 25.0,
        queue_chunks: int = 40,
    ):
        self.model_path = str(model_path)
        self.wake_phrase = " ".join(wake_phrase.casefold().split())
        self.device = device
        self.on_state = on_state
        self.on_transcript = on_transcript
        self.on_error = on_error
        self.silence_seconds = max(0.5, float(silence_seconds))
        self.max_command_seconds = max(3.0, float(max_command_seconds))
        self.queue_chunks = max(4, min(int(queue_chunks), 256))
        self._stream = None
        self._model = None
        self._wake_recognizer = None
        self._command_recognizer = None
        self._mode = "stopped"
        self._lock = threading.RLock()
        self._metrics_lock = threading.Lock()
        self._audio_queue: queue.Queue[bytes] | None = None
        self._stop_event = threading.Event()
        self._ptt_requested = threading.Event()
        self._worker: threading.Thread | None = None
        self._queue_overflows = 0
        self._device_status_events = 0
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._command_started = 0.0
        self._noise_floor = 65.0
        self._parts: list[str] = []

    def start(self):
        if not self.wake_phrase:
            raise ValueError("Wake phrase cannot be empty")
        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise RuntimeError("Install voice support with: pip install 'transcriber[voice]'") from exc
        with self._lock:
            if self._stream is not None:
                return
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError("The previous voice recognition worker is still shutting down.")
            self._model = Model(self.model_path)
            self._wake_recognizer = KaldiRecognizer(
                self._model, 16000, json.dumps([self.wake_phrase])
            )
            self._wake_recognizer.SetWords(False)
            self._command_recognizer = None
            self._audio_queue = queue.Queue(maxsize=self.queue_chunks)
            self._queue_overflows = 0
            self._device_status_events = 0
            self._stop_event.clear()
            self._ptt_requested.clear()
            self._mode = "wake"
            self._worker = threading.Thread(
                target=self._recognition_loop,
                name="Transcriber-Vosk-recognition",
                daemon=True,
            )
            stream = sd.RawInputStream(
                samplerate=16000,
                blocksize=4000,
                device=self.device,
                dtype="int16",
                channels=1,
                callback=self._audio_callback,
            )
            self._stream = stream
            self._worker.start()
        try:
            stream.start()
        except Exception:
            self.stop()
            raise
        self._notify("Wake listening · local microphone")

    def push_to_talk(self):
        with self._lock:
            if self._stream is None or self._model is None or self._stop_event.is_set():
                raise RuntimeError("Start local wake detection before push-to-talk")
            if self._mode == "command":
                raise RuntimeError("A voice command is already being captured.")
            self._ptt_requested.set()

    def _audio_callback(self, indata, frames, time_info, status):
        """Audio callback: bounded enqueue only; never run recognition here."""
        if status:
            with self._metrics_lock:
                self._device_status_events += 1
        if self._stop_event.is_set():
            return
        audio_queue = self._audio_queue
        if audio_queue is None:
            return
        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            with self._metrics_lock:
                self._queue_overflows += 1

    def _recognition_loop(self):
        try:
            while not self._stop_event.is_set():
                if self._ptt_requested.is_set():
                    self._ptt_requested.clear()
                    if self._mode == "wake":
                        self._begin_command()
                        self._notify("Push-to-talk · listening locally")
                self._report_audio_metrics()
                audio_queue = self._audio_queue
                if audio_queue is None:
                    break
                try:
                    payload = audio_queue.get(timeout=0.1)
                except queue.Empty:
                    self._check_command_deadline()
                    continue
                if self._stop_event.is_set():
                    break
                if self._mode == "wake":
                    self._process_wake_audio(payload)
                elif self._mode == "command":
                    self._process_command_audio(payload)
        except Exception as exc:
            self._mode = "error"
            self._stop_event.set()
            self._notify("Voice recognition error")
            if self.on_error:
                try:
                    self.on_error(str(exc))
                except Exception:
                    pass
        finally:
            if not self._stop_event.is_set():
                self._stop_event.set()
            self._mode = "stopped"

    def _process_wake_audio(self, payload: bytes):
        recognizer = self._wake_recognizer
        if recognizer is None or not recognizer.AcceptWaveform(payload):
            return
        try:
            recognized = json.loads(recognizer.Result()).get("text", "")
        except (ValueError, TypeError):
            recognized = ""
        normalized = " ".join(str(recognized).casefold().split())
        if normalized == self.wake_phrase:
            self._begin_command()
            self._notify("Wake phrase detected · listening")

    def _begin_command(self):
        from vosk import KaldiRecognizer

        if self._model is None:
            raise RuntimeError("The local Vosk model is no longer available.")
        self._command_recognizer = KaldiRecognizer(self._model, 16000)
        self._command_recognizer.SetWords(True)
        self._parts = []
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._command_started = time.monotonic()
        self._noise_floor = 65.0
        self._mode = "command"

    @staticmethod
    def _rms(data: bytes) -> float:
        samples = array("h")
        samples.frombytes(data[: len(data) - len(data) % 2])
        if not samples:
            return 0.0
        return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5

    def _process_command_audio(self, payload: bytes):
        recognizer = self._command_recognizer
        if recognizer is None:
            self._mode = "wake"
            return
        now = time.monotonic()
        level = self._rms(payload)
        threshold = max(190.0, self._noise_floor * 2.8)
        if not self._speech_started and level < threshold:
            self._noise_floor = min(500.0, self._noise_floor * 0.96 + level * 0.04)
            threshold = max(190.0, self._noise_floor * 2.8)
        if level >= threshold:
            if not self._speech_started:
                self._speech_started = now
            self._last_voice = now
        if recognizer.AcceptWaveform(payload):
            self._append_recognizer_result(recognizer.Result())
        self._check_command_deadline(now)

    def _append_recognizer_result(self, result: str):
        try:
            text = str(json.loads(result).get("text", "")).strip()
        except (ValueError, TypeError):
            text = ""
        if text:
            self._parts.append(text)

    def _check_command_deadline(self, now: float | None = None):
        if self._mode != "command" or self._command_recognizer is None:
            return
        now = time.monotonic() if now is None else now
        no_speech_timeout = not self._speech_started and now - self._command_started >= 8.0
        silence_timeout = (
            self._speech_started
            and now - self._last_voice >= self.silence_seconds
        )
        maximum_duration = (
            self._speech_started
            and now - self._speech_started >= self.max_command_seconds
        )
        if no_speech_timeout or silence_timeout or maximum_duration:
            self._finish_command()

    def _finish_command(self):
        recognizer, self._command_recognizer = self._command_recognizer, None
        if recognizer is not None:
            try:
                self._append_recognizer_result(recognizer.FinalResult())
            except Exception as exc:
                self._notify(f"Could not finalize voice command: {exc}")
        command = " ".join(part for part in self._parts if part).strip()
        self._parts = []
        self._mode = "wake"
        if command:
            self._notify("Voice command recognized")
            if self.on_transcript:
                try:
                    self.on_transcript(command)
                except Exception as exc:
                    if self.on_error:
                        self.on_error(str(exc))
        else:
            self._notify("No speech detected · wake listening")
        if self._mode == "wake" and not self._stop_event.is_set():
            self._notify("Wake listening")

    def _report_audio_metrics(self):
        with self._metrics_lock:
            overflows, self._queue_overflows = self._queue_overflows, 0
            status_events, self._device_status_events = self._device_status_events, 0
        if overflows:
            self._notify(
                f"Voice buffer overflow · dropped {overflows} audio chunk(s)"
            )
        if status_events:
            self._notify(
                f"Microphone reported {status_events} audio stream status event(s)"
            )

    def _notify(self, state):
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                pass

    def stop(self):
        with self._lock:
            stream, self._stream = self._stream, None
            worker = self._worker
            self._stop_event.set()
        if stream:
            try:
                stream.stop()
            except Exception as exc:
                if self.on_error:
                    try:
                        self.on_error(str(exc))
                    except Exception:
                        pass
            try:
                stream.close()
            except Exception as exc:
                if self.on_error:
                    try:
                        self.on_error(str(exc))
                    except Exception:
                        pass
        if worker and worker is not threading.current_thread():
            worker.join(timeout=5.0)
            if worker.is_alive():
                message = "Voice recognition is still shutting down; microphone capture has been closed."
                self._notify(message)
                if self.on_error:
                    try:
                        self.on_error(message)
                    except Exception:
                        pass
                return
        with self._lock:
            self._worker = None
            self._wake_recognizer = None
            self._command_recognizer = None
            self._model = None
            self._audio_queue = None
            self._parts = []
            self._mode = "stopped"
        self._notify("Voice agent stopped")

    def close(self):
        self.stop()
