# Audio pipeline

## Import and file decoding

The import boundary validates that a file exists, is non-empty, and has a supported extension: WAV, MP3, M4A, AAC, FLAC, OGG, OPUS, or WMA. Faster-Whisper decodes the selected file through its PyAV/FFmpeg runtime. The exact codec/container combination still depends on the installed PyAV build; an extension alone cannot guarantee that every variant is decodable. Decode errors are reported by the engine instead of falling back to a network service.

The optional Google adapter uses the official Google Cloud Speech-to-Text V2 Python client with Application Default Credentials. It requires a project ID, a selected V2 region/model, API enablement, billing and sufficient IAM permissions. Local audio is normalized with FFmpeg into PCM WAV chunks of at most 50 seconds and sent inline to the synchronous V2 Recognize method; no Cloud Storage bucket is used. Each request remains below the documented 60-second / 10 MB synchronous limits. Cloud use is gated by both Local-only mode being disabled and explicit cloud consent.

## Microphone capture

The Recording page enumerates `QMediaDevices.audioInputs()` and listens for device-list changes. Capture is implemented with `QAudioSource`. It selects a device-supported 16-bit PCM format from common 48/44.1/16 kHz mono/stereo candidates; if the device exposes no supported PCM16 format, the app reports an actionable error rather than writing an incorrectly described WAV file.

Raw PCM is written incrementally to a temporary target with a reserved 44-byte header. On stop, the recorder finalizes RIFF/WAV sizes, flushes and syncs the file, then offers it to the transcription workspace. Pause/resume, elapsed duration, RMS input level, device disconnect/error handling, save, and discard are implemented. The user chooses the output path; imported external audio is referenced by path and is not copied into the app's storage by default.

## Playback

`AudioPlayer` wraps `QMediaPlayer` and `QAudioOutput`. The transcription workspace exposes play/pause, seek, playback-rate selection, and volume. Segment start/end times are used to seek-highlight the corresponding transcript text while playing.

## Explicitly not the same as live dictation

The Recording page is real microphone capture, but the current build does not transcribe audio incrementally while the microphone is open. Faster-Whisper is used for file/chunk-window inference after the recording is saved. The app does not claim native continuous Whisper streaming. A future live mode needs VAD chunk scheduling, overlap reconciliation, partial/final state, and a distinct UI for unfinalized text.

The current capture meter is an RMS level meter, not a waveform renderer. No A-B loop, silence trimming UI, noise reduction, normalization, resampling controls, or speaker separation pipeline is shipped yet.
