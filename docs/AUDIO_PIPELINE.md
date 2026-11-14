# Audio pipeline

## Import and file decoding

The import boundary validates that a file exists, is non-empty, and has a supported extension: WAV, MP3, M4A, AAC, FLAC, OGG, OPUS, or WMA. Faster-Whisper decodes the selected file through its PyAV/FFmpeg runtime. The exact codec/container combination still depends on the installed PyAV build; an extension alone cannot guarantee that every variant is decodable. Decode errors are reported by the engine instead of falling back to a network service.

The optional Google adapter reads formats supported by SpeechRecognition directly and can use pydub/FFmpeg for conversion. It uses SpeechRecognition's `recognize_google` method; this is an online Google recognition endpoint, not the authenticated Google Cloud Speech-to-Text API. It is only constructed after local-only mode has been disabled and cloud consent has been explicitly checked.

## Microphone capture

The Recording page enumerates `QMediaDevices.audioInputs()` and listens for device-list changes. Capture is implemented with `QAudioSource`. It selects a device-supported 16-bit PCM format from common 48/44.1/16 kHz mono/stereo candidates; if the device exposes no supported PCM16 format, the app reports an actionable error rather than writing an incorrectly described WAV file.

Raw PCM is written incrementally to a temporary target with a reserved 44-byte header. On stop, the recorder finalizes RIFF/WAV sizes, flushes and syncs the file, then offers it to the transcription workspace. Pause/resume, elapsed duration, RMS input level, device disconnect/error handling, save, and discard are implemented. The user chooses the output path; imported external audio is referenced by path and is not copied into the app's storage by default.

## Playback

`AudioPlayer` wraps `QMediaPlayer` and `QAudioOutput`. The transcription workspace exposes play/pause, seek, playback-rate selection, and volume. Segment start/end times are used to seek-highlight the corresponding transcript text while playing.

## Explicitly not the same as live dictation

The Recording page is real microphone capture, but the current build does not transcribe audio incrementally while the microphone is open. Faster-Whisper is used for file/chunk-window inference after the recording is saved. The app does not claim native continuous Whisper streaming. A future live mode needs VAD chunk scheduling, overlap reconciliation, partial/final state, and a distinct UI for unfinalized text.

The current capture meter is an RMS level meter, not a waveform renderer. No A-B loop, silence trimming UI, noise reduction, normalization, resampling controls, or speaker separation pipeline is shipped yet.
