"""Bounded-memory waveform peak generation with a per-file cache."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Callable


class WaveformError(RuntimeError):
    pass


def waveform_cache_key(path: Path) -> str:
    source = Path(path).resolve()
    stat = source.stat()
    payload = f"{source}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_waveform(path: Path, cache_dir: Path, *, bins: int = 4096,
                   cancel_event=None, progress: Callable[[float], None] | None = None) -> list[float]:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"waveform-{waveform_cache_key(source)}.json"
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            peaks = payload.get("peaks")
            if isinstance(peaks, list) and 0 < len(peaks) <= bins and all(isinstance(v, (int, float)) for v in peaks):
                return [max(0.0, min(1.0, float(v))) for v in peaks]
        except (OSError, ValueError, TypeError):
            pass
    if shutil.which("ffmpeg"):
        peaks = _decode_ffmpeg(source, bins, cancel_event, progress)
    elif source.suffix.casefold() == ".wav":
        peaks = _decode_wave(source, bins, cancel_event, progress)
    else:
        raise WaveformError("Waveform generation for this format requires FFmpeg on PATH")
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"peaks": peaks}, separators=(",", ":")), encoding="utf-8")
    temporary.replace(cache_path)
    return peaks


def _decode_ffmpeg(source: Path, bins: int, cancel_event, progress) -> list[float]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
        capture_output=True, text=True, timeout=12,
    ) if shutil.which("ffprobe") else None
    duration = 0.0
    if probe and probe.returncode == 0:
        try:
            duration = max(0.0, float(probe.stdout.strip()))
        except ValueError:
            duration = 0.0
    process = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    peaks: list[float] = []
    sample_rate = 8000
    samples_per_bin = max(256, int((duration * sample_rate / bins))) if duration else 1024
    samples_seen = 0
    current_max = 0
    try:
        assert process.stdout is not None
        while True:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                raise InterruptedError("Waveform generation cancelled")
            raw = process.stdout.read(32768)
            if not raw:
                break
            values = array("h")
            values.frombytes(raw[: len(raw) - (len(raw) % 2)])
            for value in values:
                current_max = max(current_max, abs(value))
                samples_seen += 1
                if samples_seen >= samples_per_bin:
                    peaks.append(current_max / 32768.0)
                    current_max = 0
                    samples_seen = 0
            # A fixed-rate intermediate representation is bounded for long media;
            # it is downsampled to the requested display width after decoding.
            if progress and duration:
                progress(min(99.0, len(peaks) / bins * 100.0))
        if samples_seen:
            peaks.append(current_max / 32768.0)
        process.stdout.close()
        return_code = process.wait(timeout=10)
        if return_code not in (0, -15):
            stderr = process.stderr.read(2000).decode("utf-8", "replace") if process.stderr else ""
            raise WaveformError(f"FFmpeg could not decode waveform: {stderr.strip()}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
    if not peaks:
        raise WaveformError("The selected file contains no decodable audio samples")
    peaks = _downsample_peaks(peaks, bins)
    if progress:
        progress(100.0)
    return _downsample_peaks(peaks, bins)


def _decode_wave(source: Path, bins: int, cancel_event, progress) -> list[float]:
    peaks: list[float] = []
    with wave.open(str(source), "rb") as audio:
        if audio.getnchannels() < 1:
            raise WaveformError("WAV has no audio channels")
        sample_width = audio.getsampwidth()
        if sample_width != 2:
            raise WaveformError("Without FFmpeg, waveform preview supports 16-bit PCM WAV files only")
        total = audio.getnframes()
        samples_per_bin = max(256, total // max(1, bins))
        processed = 0
        current_max = 0
        while True:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Waveform generation cancelled")
            raw = audio.readframes(8192)
            if not raw:
                break
            values = array("h")
            values.frombytes(raw[: len(raw) - (len(raw) % 2)])
            # Interleaved samples are reduced to peak amplitude across channels.
            for frame in range(0, len(values), audio.getnchannels()):
                current_max = max(current_max, *(abs(v) for v in values[frame:frame + audio.getnchannels()]))
                processed += 1
                if processed >= samples_per_bin:
                    peaks.append(current_max / 32768.0)
                    current_max = 0
                    processed = 0
            if progress:
                progress(min(99.0, audio.tell() / max(1, total) * 100.0))
        if processed:
            peaks.append(current_max / 32768.0)
    if progress:
        progress(100.0)
    return peaks


def _downsample_peaks(peaks: list[float], bins: int) -> list[float]:
    bins = max(1, int(bins))
    if len(peaks) <= bins:
        return peaks
    output = []
    width = len(peaks) / bins
    for index in range(bins):
        start = int(index * width)
        end = max(start + 1, int((index + 1) * width))
        output.append(max(peaks[start:end]))
    return output
