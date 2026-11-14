"""Non-destructive FFmpeg processing; the source is never overwritten."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


class AudioProcessingError(RuntimeError):
    pass


def build_filter_chain(*, normalize: bool = False, highpass_hz: int | None = None,
                       lowpass_hz: int | None = None, remove_silence: bool = False,
                       denoise: bool = False, volume_db: float = 0.0) -> list[str]:
    filters: list[str] = []
    if highpass_hz is not None:
        highpass_hz = int(highpass_hz)
        if not 20 <= highpass_hz <= 1000:
            raise ValueError("High-pass frequency must be between 20 and 1000 Hz")
        filters.append(f"highpass=f={highpass_hz}")
    if lowpass_hz is not None:
        lowpass_hz = int(lowpass_hz)
        if not 1000 <= lowpass_hz <= 20000:
            raise ValueError("Low-pass frequency must be between 1000 and 20000 Hz")
        filters.append(f"lowpass=f={lowpass_hz}")
    if denoise:
        filters.append("afftdn=nf=-25")
    if volume_db:
        volume_db = max(-24.0, min(24.0, float(volume_db)))
        filters.append(f"volume={volume_db:.2f}dB")
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if remove_silence:
        filters.append("silenceremove=start_periods=1:start_duration=0.35:start_threshold=-45dB:stop_periods=-1:stop_duration=0.45:stop_threshold=-45dB")
    return filters


def process_audio(source: Path, output: Path, *, filters: list[str], cancel_event=None,
                  progress=None) -> Path:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output:
        raise ValueError("Audio cleanup must write to a new file; the original is protected")
    if not filters:
        raise ValueError("Select at least one audio processing operation")
    if not shutil.which("ffmpeg"):
        raise AudioProcessingError("FFmpeg is required for audio cleanup")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.stem + ".processing" + output.suffix)
    command = ["ffmpeg", "-nostdin", "-y", "-i", str(source), "-vn", "-af", ",".join(filters), str(temporary)]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        while process.poll() is None:
            should_cancel = cancel_event.wait(0.15) if cancel_event else False
            if not cancel_event:
                time.sleep(0.15)
            if should_cancel:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise InterruptedError("Audio processing cancelled")
            if progress:
                progress("Processing audio…")
        stderr = process.stderr.read() if process.stderr else ""
        if process.returncode != 0:
            raise AudioProcessingError(stderr[-3000:] or "FFmpeg processing failed")
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise AudioProcessingError("FFmpeg produced an empty output")
        temporary.replace(output)
        return output
    finally:
        if process.poll() is None:
            process.kill()
        temporary.unlink(missing_ok=True)
