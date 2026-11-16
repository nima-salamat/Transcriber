from __future__ import annotations

from transcriber.audio.imports import collect_media_paths


def _write(path, payload=b"audio"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_collects_one_supported_file(tmp_path):
    media = _write(tmp_path / "one.wav")
    report = collect_media_paths([media])
    assert report.accepted == (media.resolve(),)
    assert report.rejected == ()
    assert report.duplicates == ()


def test_collects_multiple_supported_files_without_dropping_items(tmp_path):
    first = _write(tmp_path / "a.wav")
    second = _write(tmp_path / "b.mp3")
    third = _write(tmp_path / "c.flac")
    report = collect_media_paths([first, second, third])
    assert set(report.accepted) == {first.resolve(), second.resolve(), third.resolve()}
    assert report.rejected == ()


def test_mixed_supported_and_unsupported_paths_are_reported(tmp_path):
    supported = _write(tmp_path / "speech.wav")
    unsupported = _write(tmp_path / "notes.pdf")
    report = collect_media_paths([supported, unsupported])
    assert report.accepted == (supported.resolve(),)
    assert len(report.rejected) == 1
    assert report.rejected[0][0] == str(unsupported)
    assert "Unsupported audio extension" in report.rejected[0][1]


def test_missing_and_empty_paths_are_rejected(tmp_path):
    missing = tmp_path / "missing.wav"
    empty = _write(tmp_path / "empty.wav", b"")
    report = collect_media_paths([missing, empty])
    assert report.accepted == ()
    assert len(report.rejected) == 2
    assert "does not exist" in report.rejected[0][1]
    assert "empty" in report.rejected[1][1].casefold()


def test_duplicate_paths_are_ignored(tmp_path):
    media = _write(tmp_path / "same.wav")
    report = collect_media_paths([media, media], existing_paths=[])
    assert report.accepted == (media.resolve(),)
    assert report.duplicates == (str(media),)


def test_directory_import_expands_supported_media_only(tmp_path):
    folder = tmp_path / "folder"
    first = _write(folder / "a.wav")
    second = _write(folder / "nested" / "b.mp3")
    _write(folder / "ignore.txt")
    report = collect_media_paths([folder])
    assert set(report.accepted) == {first.resolve(), second.resolve()}
    assert report.rejected == ()


def test_empty_drop_returns_empty_report():
    report = collect_media_paths([])
    assert report.accepted == ()
    assert report.rejected == ()
    assert report.duplicates == ()


def test_invalid_path_syntax_is_reported_not_raised():
    report = collect_media_paths(["bad\\0path.wav"])
    assert report.accepted == ()
    assert len(report.rejected) == 1
    assert report.rejected[0][0] == "bad\\0path.wav"



def test_collects_supported_video_containers_for_transcription(tmp_path):
    from transcriber.audio.decoder import is_video_file

    video = _write(tmp_path / "lecture.mp4")
    report = collect_media_paths([video])

    assert report.accepted == (video.resolve(),)
    assert report.rejected == ()
    assert is_video_file(report.accepted[0])
