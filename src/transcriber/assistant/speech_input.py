"""Local wake-word detection and post-wake audio capture.

Vosk is deliberately used only as a lightweight local wake-word detector. Once
the phrase is heard, raw PCM is buffered until a configurable continuous-silence
window expires; a separate ASR engine can then transcribe the captured audio.
Audio stays in memory unless the caller explicitly chooses to persist it.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from array import array
from collections.abc import Callable


class AudioSilenceGate:
    """Adaptive RMS gate that closes a recording only after sustained silence."""

    def __init__(
        self,
        *,
        silence_seconds: float = 1.5,
        minimum_voice_level: float = 190.0,
        initial_noise_floor: float = 65.0,
    ):
        self.silence_seconds = max(0.5, min(float(silence_seconds), 8.0))
        self.minimum_voice_level = max(1.0, float(minimum_voice_level))
        self.noise_floor = max(0.0, float(initial_noise_floor))
        self.speech_started_at: float | None = None
        self.last_voice_at: float | None = None

    @property
    def has_speech(self) -> bool:
        return self.speech_started_at is not None

    def observe(self, level: float, now: float) -> bool:
        """Record an RMS observation and return whether speech has started."""
        threshold = max(self.minimum_voice_level, self.noise_floor * 2.8)
        if not self.has_speech and level < threshold:
            self.noise_floor = min(500.0, self.noise_floor * 0.96 + level * 0.04)
            threshold = max(self.minimum_voice_level, self.noise_floor * 2.8)
        if level >= threshold:
            if self.speech_started_at is None:
                self.speech_started_at = now
            self.last_voice_at = now
        return self.has_speech

    def should_finish(self, now: float) -> bool:
        """True only after actual speech followed by the full silence interval."""
        return bool(
            self.last_voice_at is not None
            and now - self.last_voice_at >= self.silence_seconds
        )

    def silence_duration(self, now: float) -> float:
        if self.last_voice_at is None:
            return 0.0
        return max(0.0, now - self.last_voice_at)


class VoskVoiceAgent:
    """Capture post-wake PCM and hand it to a caller-supplied speech recognizer.

    The sounddevice callback only copies frames into a bounded queue. Vosk,
    metering, silence detection and command finalization all run on a worker.
    The caller should transcribe `on_audio` payloads off the GUI thread and
    call `resume_after_processing()` when the turn is ready for another wake
    phrase. `on_transcript` remains as a compatibility fallback for callers
    that do not provide a dedicated ASR callback.
    """

    SAMPLE_RATE = 16_000
    CHANNELS = 1
    SAMPLE_WIDTH = 2

    def __init__(
        self,
        model_path,
        wake_phrase: str,
        *,
        device=None,
        on_state: Callable[[str], None] | None = None,
        on_transcript: Callable[[str], None] | None = None,
        on_audio: Callable[[bytes], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        silence_seconds: float = 1.5,
        max_command_seconds: float = 60.0,
        no_speech_timeout: float = 8.0,
        queue_chunks: int = 80,
    ):
        self.model_path = str(model_path)
        self.wake_phrase = " ".join(wake_phrase.casefold().split())
        self.device = device
        self.on_state = on_state
        self.on_transcript = on_transcript
        self.on_audio = on_audio
        self.on_error = on_error
        self.silence_seconds = max(0.5, min(float(silence_seconds), 8.0))
        self.max_command_seconds = max(3.0, min(float(max_command_seconds), 300.0))
        self.no_speech_timeout = max(2.0, min(float(no_speech_timeout), 60.0))
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
        self._resume_requested = threading.Event()
        self._worker: threading.Thread | None = None
        self._queue_overflows = 0
        self._device_status_events = 0
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._command_started = 0.0
        self._noise_floor = 65.0
        self._parts: list[str] = []
        self._command_frames: list[bytes] = []
        self._silence_gate: AudioSilenceGate | None = None

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def _new_wake_recognizer(self):
        from vosk import KaldiRecognizer

        recognizer = KaldiRecognizer(
            self._model, self.SAMPLE_RATE, json.dumps([self.wake_phrase])
        )
        recognizer.SetWords(False)
        return recognizer

    def start(self):
        if not self.wake_phrase:
            raise ValueError("Wake phrase cannot be empty")
        try:
            import sounddevice as sd
            from vosk import Model
        except ImportError as exc:
            raise RuntimeError(
                "Install voice support with: pip install 'transcriber-desktop[voice]'"
            ) from exc
        with self._lock:
            if self._stream is not None:
                return
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError(
                    "The previous voice recognition worker is still shutting down."
                )
            self._model = Model(self.model_path)
            self._wake_recognizer = self._new_wake_recognizer()
            self._command_recognizer = None
            self._audio_queue = queue.Queue(maxsize=self.queue_chunks)
            self._queue_overflows = 0
            self._device_status_events = 0
            self._stop_event.clear()
            self._ptt_requested.clear()
            self._resume_requested.clear()
            self._mode = "wake"
            self._worker = threading.Thread(
                target=self._recognition_loop,
                name="Transcriber-Vosk-wake",
                daemon=True,
            )
            stream = sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=4000,
                device=self.device,
                dtype="int16",
                channels=self.CHANNELS,
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
            if (
                self._stream is None
                or self._model is None
                or self._stop_event.is_set()
            ):
                raise RuntimeError("Start local wake detection before push-to-talk")
            if self._mode == "command":
                raise RuntimeError("A voice command is already being captured.")
            if self._mode == "processing":
                raise RuntimeError("The previous voice command is still being processed.")
            self._ptt_requested.set()

    def set_silence_seconds(self, seconds: float):
        """Update the endpointing threshold, including an active command."""
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            value = 1.5
        if not (0.5 <= value <= 8.0):
            value = 1.5
        with self._lock:
            self.silence_seconds = value
            if self._silence_gate is not None:
                self._silence_gate.silence_seconds = value

    def resume_after_processing(self):
        """Resume wake detection after the current audio/AI turn is ready."""
        with self._lock:
            if self._stream is None or self._stop_event.is_set():
                return
            self._resume_requested.set()

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

    def _drain_audio_queue(self):
        audio_queue = self._audio_queue
        if audio_queue is None:
            return
        while True:
            try:
                audio_queue.get_nowait()
            except queue.Empty:
                return

    def _recognition_loop(self):
        try:
            while not self._stop_event.is_set():
                if self._resume_requested.is_set():
                    self._resume_requested.clear()
                    if self._mode == "processing":
                        self._drain_audio_queue()
                        self._wake_recognizer = self._new_wake_recognizer()
                        self._mode = "wake"
                        self._notify("Wake listening")
                if self._ptt_requested.is_set():
                    self._ptt_requested.clear()
                    if self._mode == "wake":
                        # Drop pre-press frames so they cannot leak into the command.
                        self._drain_audio_queue()
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
                # In processing mode frames are intentionally discarded while
                # the ASR/Agent handles the completed turn.
        except Exception as exc:
            with self._lock:
                self._mode = "error"
            self._stop_event.set()
            self._notify("Voice recognition error")
            self._report_error(str(exc))
        finally:
            with self._lock:
                if self._mode != "error":
                    self._mode = "stopped"

    def _process_wake_audio(self, payload: bytes):
        recognizer = self._wake_recognizer
        if recognizer is None:
            return
        if recognizer.AcceptWaveform(payload):
            try:
                recognized = json.loads(recognizer.Result()).get("text", "")
            except (ValueError, TypeError):
                recognized = ""
        else:
            try:
                recognized = json.loads(recognizer.PartialResult()).get("partial", "")
            except (ValueError, TypeError):
                recognized = ""
        normalized = " ".join(str(recognized).casefold().split())
        # The grammar is restricted to the wake phrase. Detecting its partial
        # result avoids requiring a full command utterance before recording starts.
        if normalized == self.wake_phrase or normalized.startswith(self.wake_phrase + " "):
            self._wake_recognizer = None
            self._begin_command()
            self._notify("Wake phrase detected · capturing your command")

    def _begin_command(self):
        self._command_frames = []
        self._parts = []
        self._speech_started = 0.0
        self._last_voice = 0.0
        self._command_started = time.monotonic()
        self._noise_floor = 65.0
        self._silence_gate = AudioSilenceGate(
            silence_seconds=self.silence_seconds,
            initial_noise_floor=self._noise_floor,
        )
        if self.on_audio is None:
            from vosk import KaldiRecognizer

            if self._model is None:
                raise RuntimeError("The local Vosk model is no longer available.")
            self._command_recognizer = KaldiRecognizer(self._model, self.SAMPLE_RATE)
            self._command_recognizer.SetWords(True)
        else:
            self._command_recognizer = None
        with self._lock:
            self._mode = "command"

    @staticmethod
    def _rms(data: bytes) -> float:
        samples = array("h")
        samples.frombytes(data[: len(data) - len(data) % 2])
        if not samples:
            return 0.0
        return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5

    def _process_command_audio(self, payload: bytes):
        now = time.monotonic()
        if self.on_audio is not None:
            self._command_frames.append(payload)
            gate = self._silence_gate
            if gate is not None:
                gate.observe(self._rms(payload), now)
                if gate.has_speech:
                    self._speech_started = gate.speech_started_at or now
                    self._last_voice = gate.last_voice_at or now
            self._check_command_deadline(now)
            return

        recognizer = self._command_recognizer
        if recognizer is None:
            self._mode = "wake"
            return
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
        if self._mode != "command":
            return
        now = time.monotonic() if now is None else now
        gate = self._silence_gate
        if self.on_audio is not None and gate is not None:
            no_speech_timeout = (
                not gate.has_speech
                and now - self._command_started >= self.no_speech_timeout
            )
            silence_timeout = gate.should_finish(now)
            maximum_duration = (
                gate.has_speech
                and now - (gate.speech_started_at or now) >= self.max_command_seconds
            )
        else:
            no_speech_timeout = (
                not self._speech_started
                and now - self._command_started >= self.no_speech_timeout
            )
            silence_timeout = (
                bool(self._speech_started)
                and now - self._last_voice >= self.silence_seconds
            )
            maximum_duration = (
                bool(self._speech_started)
                and now - self._speech_started >= self.max_command_seconds
            )
        if no_speech_timeout:
            self._cancel_empty_command()
        elif silence_timeout or maximum_duration:
            self._finish_command()

    def _cancel_empty_command(self):
        self._command_frames = []
        self._command_recognizer = None
        self._parts = []
        self._silence_gate = None
        self._mode = "wake"
        self._wake_recognizer = self._new_wake_recognizer()
        self._notify("No speech detected · wake listening")

    def _finish_command(self):
        if self.on_audio is not None:
            gate = self._silence_gate
            audio = b"".join(self._command_frames)
            self._command_frames = []
            self._silence_gate = None
            self._command_recognizer = None
            if gate is None or not gate.has_speech or not audio:
                self._mode = "wake"
                self._wake_recognizer = self._new_wake_recognizer()
                self._notify("No speech detected · wake listening")
                return
            with self._lock:
                self._mode = "processing"
            self._notify("Silence detected · transcribing with Faster-Whisper")
            try:
                self.on_audio(audio)
            except Exception as exc:
                self._report_error(str(exc))
                self.resume_after_processing()
            return

        recognizer, self._command_recognizer = self._command_recognizer, None
        if recognizer is not None:
            try:
                self._append_recognizer_result(recognizer.FinalResult())
            except Exception as exc:
                self._notify(f"Could not finalize voice command: {exc}")
        command = " ".join(part for part in self._parts if part).strip()
        self._parts = []
        self._silence_gate = None
        self._mode = "wake"
        self._wake_recognizer = self._new_wake_recognizer()
        if command:
            self._notify("Voice command recognized")
            if self.on_transcript:
                try:
                    self.on_transcript(command)
                except Exception as exc:
                    self._report_error(str(exc))
        else:
            self._notify("No speech detected · wake listening")
        if not self._stop_event.is_set():
            self._notify("Wake listening")

    def _report_audio_metrics(self):
        with self._metrics_lock:
            overflows, self._queue_overflows = self._queue_overflows, 0
            status_events, self._device_status_events = self._device_status_events, 0
        if overflows:
            self._notify(f"Voice buffer overflow · dropped {overflows} audio chunk(s)")
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

    def _report_error(self, message: str):
        if self.on_error:
            try:
                self.on_error(message)
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
                self._report_error(str(exc))
            try:
                stream.close()
            except Exception as exc:
                self._report_error(str(exc))
        if worker and worker.ident is not None and worker is not threading.current_thread():
            worker.join(timeout=5.0)
            if worker.is_alive():
                message = (
                    "Voice recognition is still shutting down; microphone capture has been closed."
                )
                self._notify(message)
                self._report_error(message)
                return
        with self._lock:
            self._worker = None
            self._wake_recognizer = None
            self._command_recognizer = None
            self._model = None
            self._audio_queue = None
            self._command_frames = []
            self._parts = []
            self._silence_gate = None
            self._mode = "stopped"
        self._notify("Voice agent stopped")

    def close(self):
        self.stop()
