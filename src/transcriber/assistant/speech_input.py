"""Optional local Vosk wake-word and voice-command capture.

The audio callback processes PCM in memory only. It does not write recordings,
transmit audio, or retain raw audio buffers beyond the current callback.
"""

from __future__ import annotations

import json
import threading
import time
from array import array
from collections.abc import Callable


class VoskVoiceAgent:
    def __init__(self, model_path, wake_phrase: str, *, device=None,
                 on_state: Callable[[str], None] | None = None,
                 on_transcript: Callable[[str], None] | None = None,
                 on_error: Callable[[str], None] | None = None,
                 silence_seconds: float = 1.25, max_command_seconds: float = 25.0):
        self.model_path = str(model_path)
        self.wake_phrase = " ".join(wake_phrase.casefold().split())
        self.device = device
        self.on_state = on_state
        self.on_transcript = on_transcript
        self.on_error = on_error
        self.silence_seconds = max(0.5, float(silence_seconds))
        self.max_command_seconds = max(3.0, float(max_command_seconds))
        self._stream = None
        self._model = None
        self._wake_recognizer = None
        self._command_recognizer = None
        self._mode = "stopped"
        self._lock = threading.RLock()
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._command_started = 0.0
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
            self._model = Model(self.model_path)
            self._wake_recognizer = KaldiRecognizer(self._model, 16000, json.dumps([self.wake_phrase]))
            self._wake_recognizer.SetWords(False)
            self._command_recognizer = None
            self._mode = "wake"
            self._stream = sd.RawInputStream(
                samplerate=16000, blocksize=4000, device=self.device, dtype="int16", channels=1,
                callback=self._callback,
            )
            self._stream.start()
        self._notify("Wake listening (local microphone)")

    def push_to_talk(self):
        with self._lock:
            if self._stream is None or self._model is None:
                raise RuntimeError("Start local wake detection before push-to-talk")
            self._begin_command_locked()
        self._notify("Listening for a voice command")

    def _begin_command_locked(self):
        from vosk import KaldiRecognizer
        self._command_recognizer = KaldiRecognizer(self._model, 16000)
        self._command_recognizer.SetWords(True)
        self._parts = []
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._command_started = time.monotonic()
        self._mode = "command"

    @staticmethod
    def _rms(data: bytes) -> float:
        samples = array("h")
        samples.frombytes(data[: len(data) - len(data) % 2])
        if not samples:
            return 0.0
        return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5

    def _callback(self, indata, frames, time_info, status):
        if status:
            return
        payload = bytes(indata)
        with self._lock:
            mode = self._mode
            if mode == "wake" and self._wake_recognizer is not None:
                if self._wake_recognizer.AcceptWaveform(payload):
                    try:
                        recognized = json.loads(self._wake_recognizer.Result()).get("text", "")
                    except (ValueError, TypeError):
                        recognized = ""
                    if " ".join(str(recognized).casefold().split()) == self.wake_phrase:
                        self._begin_command_locked()
                        self._notify("Wake phrase detected · listening")
                return
            if mode != "command" or self._command_recognizer is None:
                return
            now = time.monotonic()
            level = self._rms(payload)
            if level >= 240:
                if not self._speech_started:
                    self._speech_started = now
                self._last_voice = now
            if self._command_recognizer.AcceptWaveform(payload):
                try:
                    text = json.loads(self._command_recognizer.Result()).get("text", "").strip()
                except (ValueError, TypeError):
                    text = ""
                if text:
                    self._parts.append(text)
            command_timed_out_without_speech = (
                not self._speech_started and now - self._command_started >= 8.0
            )
            if command_timed_out_without_speech or (self._speech_started and (
                now - self._last_voice >= self.silence_seconds
                or now - self._speech_started >= self.max_command_seconds
            )):
                try:
                    final = json.loads(self._command_recognizer.FinalResult()).get("text", "").strip()
                except (ValueError, TypeError):
                    final = ""
                if final:
                    self._parts.append(final)
                command = " ".join(dict.fromkeys(part for part in self._parts if part)).strip()
                self._command_recognizer = None
                self._mode = "wake"
                self._parts = []
                self._notify("Wake listening")
                if command and self.on_transcript:
                    self.on_transcript(command)

    def _notify(self, state):
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                pass

    def stop(self):
        with self._lock:
            stream, self._stream = self._stream, None
            self._mode = "stopped"
            self._wake_recognizer = None
            self._command_recognizer = None
            self._model = None
            self._parts = []
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                if self.on_error:
                    self.on_error(str(exc))
        self._notify("Voice agent stopped")

    def close(self):
        self.stop()
