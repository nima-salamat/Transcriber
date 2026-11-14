from __future__ import annotations

import threading
import time
import wave
from pathlib import Path

import pytest

from transcriber.assistant.action_registry import ActionRegistry, ActionSpec
from transcriber.assistant.permissions import AgentPermission, PermissionDenied
from transcriber.assistant.voice_controller import VoiceAgentController, VoiceState
from transcriber.audio.processing import build_filter_chain, process_audio
from transcriber.audio.waveform import build_waveform
from transcriber.editor.cleanup import apply_cleanup, preview_cleanup
from transcriber.editor.commands import CommandHistory
from transcriber.editor.document import TranscriptDocument
from transcriber.editor.search import replace, search
from transcriber.ipc.client import IPCUnavailable, LocalIPCClient
from transcriber.ipc.server import LocalIPCServer
from transcriber.models.runtime import (
    ModelRuntimeManager, ModelSpec, ModelState, ResourceLimitError, ResourceSnapshot,
)
from transcriber.models.scheduler import JobPriority, JobStatus, PriorityModelScheduler
from transcriber.storage.database import Database
from transcriber.storage.history import HistoryRepository
from transcriber.subtitles.formats import export_subtitles, parse_subtitles
from transcriber.subtitles.timing import apply_minimum_gap, shift_timestamps, validate_subtitles
from transcriber.transcription.segments import TranscriptSegment, TranscriptWord


class StaticMonitor:
    def __init__(self, ram=100_000, vram=100_000):
        self.ram, self.vram = ram, vram

    def snapshot(self):
        return ResourceSnapshot(self.ram, self.ram, self.vram, self.vram)


class FakeAdapter:
    def __init__(self, delay=0):
        self.delay = delay
        self.loads = 0
        self.unloads = []

    def load(self, spec):
        self.loads += 1
        if self.delay:
            time.sleep(self.delay)
        return {"model": spec.model_id, "instance": self.loads}

    def unload(self, handle):
        self.unloads.append(handle)


def make_spec(model_id, ram=10, vram=0):
    return ModelSpec(model_id, "test", "asr", "fake", required_ram_mb=ram,
                     required_vram_mb=vram, installed=True)


def test_editor_snapshot_undo_redo_preserves_word_timing():
    segment = TranscriptSegment(
        0, 2, "hello world", id="s1",
        words=[TranscriptWord(0.1, 0.8, "hello"), TranscriptWord(1.0, 1.8, "world")],
    )
    document = TranscriptDocument([segment])
    history = CommandHistory(document)
    history.execute(document.update_segment, "s1", text="hello there")
    assert document.get("s1").words == []
    assert history.undo()
    assert [word.text for word in document.get("s1").words] == ["hello", "world"]
    assert history.redo()
    assert document.get("s1").text == "hello there"
    assert document.get("s1").words == []


def test_editor_word_split_merge_and_locks():
    document = TranscriptDocument([TranscriptSegment(
        0, 2, "one two", id="s1", speaker="A", bookmarked=True,
        words=[TranscriptWord(0.1, 0.8, "one"), TranscriptWord(1.0, 1.8, "two")],
    )])
    left, right = document.split_segment("s1", 0.9)
    assert (left.text, right.text) == ("one", "two")
    assert left.id != right.id
    merged = document.merge_segments(left.id, right.id)
    assert merged.text == "one two"
    assert merged.speaker == "A"
    document.toggle_lock(merged.id, True)
    with pytest.raises(PermissionError):
        document.update_segment(merged.id, text="blocked")
    with pytest.raises(PermissionError):
        document.delete_segment(merged.id)


def test_editor_time_edit_is_atomic_when_word_ranges_would_be_invalid():
    segment = TranscriptSegment(0, 2, "hello", id="s1", words=[TranscriptWord(0.2, 1.4, "hello")])
    document = TranscriptDocument([segment])
    with pytest.raises(ValueError):
        document.update_segment("s1", end=0.5)
    assert document.get("s1").end == 2
    assert document.get("s1").words[0].end == 1.4


def test_search_regex_replace_skips_locked_segments():
    document = TranscriptDocument([
        TranscriptSegment(0, 1, "Hello hello", id="a"),
        TranscriptSegment(1, 2, "hello", id="b", locked=True),
    ])
    assert len(search(document, r"hello", regex=True)) == 3
    assert replace(document, r"hello", "hi", regex=True) == 2
    assert document.get("a").text == "hi hi"
    assert document.get("b").text == "hello"


def test_cleanup_preview_stale_guard_is_atomic():
    document = TranscriptDocument([
        TranscriptSegment(0, 1, "um hello  world", id="a", language="en"),
        TranscriptSegment(1, 2, "uh repeated", id="b", language="en"),
    ])
    preview = preview_cleanup(document, {"filler", "spaces"})
    assert len(preview) == 2
    document.update_segment("b", text="changed")
    before_first = document.get("a").text
    with pytest.raises(RuntimeError):
        apply_cleanup(document, preview)
    assert document.get("a").text == before_first


def test_subtitle_roundtrip_and_timing_tools(tmp_path):
    segments = [
        TranscriptSegment(0.0, 1.0, "Hello", id="a"),
        TranscriptSegment(0.95, 2.0, "World", id="b"),
    ]
    path = export_subtitles(tmp_path / "test.srt", segments)
    parsed = parse_subtitles(path)
    assert len(parsed) == 2
    assert parsed[1].text == "World"
    assert any(issue.code == "overlap" for issue in validate_subtitles(segments))
    shifted = shift_timestamps(parsed, 1.0)
    assert shifted[0].start == 1.0
    fixed = apply_minimum_gap(segments, 0.1)
    assert fixed[1].start >= fixed[0].end + 0.1 - 1e-9
    vtt_path = export_subtitles(tmp_path / "test.vtt", parsed)
    assert vtt_path.read_text(encoding="utf-8").startswith("WEBVTT")


def test_model_runtime_enforces_slots_evicts_lru_and_respects_pins():
    manager = ModelRuntimeManager(max_active_models=1, monitor=StaticMonitor(), ram_budget_mb=1000)
    first, second = FakeAdapter(), FakeAdapter()
    manager.register(make_spec("one"), first)
    manager.register(make_spec("two"), second)
    handle = manager.load("one")
    assert manager.state("one") == ModelState.LOADED
    manager.load("two")
    assert manager.state("one") == ModelState.INSTALLED
    assert manager.state("two") == ModelState.LOADED
    assert first.unloads == [handle]
    manager.pin("two")
    with pytest.raises(ResourceLimitError):
        manager.load("one")


def test_model_runtime_rejects_active_unload_and_unknown_adapter():
    manager = ModelRuntimeManager(max_active_models=2, monitor=StaticMonitor())
    adapter = FakeAdapter()
    manager.register(make_spec("one"), adapter)
    with manager.acquire("one"):
        with pytest.raises(RuntimeError):
            manager.unload("one")
    assert manager.unload("one")
    missing = ModelRuntimeManager(monitor=StaticMonitor())
    missing.register(make_spec("missing"))
    with pytest.raises(RuntimeError):
        missing.load("missing")


def test_model_runtime_serializes_concurrent_loads():
    manager = ModelRuntimeManager(max_active_models=2, monitor=StaticMonitor())
    adapter = FakeAdapter(delay=0.05)
    manager.register(make_spec("one"), adapter)
    results = []
    workers = [threading.Thread(target=lambda: results.append(manager.load("one"))) for _ in range(5)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)
    assert len(results) == 5
    assert adapter.loads == 1
    assert all(value is results[0] for value in results)


def test_priority_scheduler_runs_high_priority_before_pending_batch_jobs():
    scheduler = PriorityModelScheduler(workers=1)
    release = threading.Event()
    started = threading.Event()
    order = []
    try:
        blocker = scheduler.submit(lambda cancel: (started.set(), release.wait(2), "blocker")[-1],
                                   priority=JobPriority.WAKE_WORD)
        assert started.wait(1)
        low = scheduler.submit(lambda cancel: order.append("batch") or "low", priority=JobPriority.BATCH)
        high = scheduler.submit(lambda cancel: order.append("voice") or "high",
                                priority=JobPriority.ACTIVE_VOICE_COMMAND)
        release.set()
        assert blocker.future.result(2) == "blocker"
        assert high.future.result(2) == "high"
        assert low.future.result(2) == "low"
        assert order == ["voice", "batch"]
        assert high.status == JobStatus.COMPLETED
    finally:
        release.set()
        scheduler.shutdown()


def test_priority_scheduler_cancels_queued_jobs():
    scheduler = PriorityModelScheduler(workers=1)
    release = threading.Event()
    started = threading.Event()
    try:
        scheduler.submit(lambda cancel: (started.set(), release.wait(2)), priority=JobPriority.WAKE_WORD)
        assert started.wait(1)
        queued = scheduler.submit(lambda cancel: "should not run", priority=JobPriority.BATCH)
        assert scheduler.cancel(queued.job_id)
        release.set()
        deadline = time.time() + 2
        while queued.status != JobStatus.CANCELLED and time.time() < deadline:
            time.sleep(0.01)
        assert queued.status == JobStatus.CANCELLED
    finally:
        release.set()
        scheduler.shutdown()


def test_action_registry_enforces_permissions_and_explicit_destructive_approval():
    calls = []
    registry = ActionRegistry(permissions={AgentPermission.READ_ONLY}, approval=lambda spec, args: False)
    registry.register(ActionSpec("read", "read", AgentPermission.READ_ONLY, lambda args: "ok"))
    registry.register(ActionSpec("edit", "edit", AgentPermission.EDIT_CONTENT, lambda args: "edited"))
    registry.register(ActionSpec("delete", "delete", AgentPermission.READ_ONLY,
                                 lambda args: calls.append("deleted"), destructive=True))
    assert registry.execute("read") == "ok"
    with pytest.raises(PermissionDenied):
        registry.execute("edit")
    with pytest.raises(PermissionDenied):
        registry.execute("delete")
    assert calls == []


def test_voice_controller_sleep_wake_and_explicit_stop():
    controller = VoiceAgentController(wake_enabled=True, auto_sleep_seconds=5)
    assert controller.state == VoiceState.SLEEPING
    controller.enable_wake_word(True)
    assert controller.state == VoiceState.WAKE_LISTENING
    controller.wake_detected()
    assert controller.state == VoiceState.LISTENING
    controller.stop()
    assert controller.state == VoiceState.SLEEPING
    controller.enable_wake_word(False)
    assert controller.state == VoiceState.DISABLED


def test_authenticated_local_ipc_roundtrip_and_rejects_wrong_token(tmp_path):
    endpoint = tmp_path / "transcriber-ipc.json"
    server = LocalIPCServer(endpoint, lambda method, params: {"method": method, "value": params.get("value")})
    server.start()
    try:
        client = LocalIPCClient(endpoint)
        assert client.call("app.get_state", {"value": 5}) == {"method": "app.get_state", "value": 5}
        import json
        data = json.loads(endpoint.read_text())
        data["token"] = "invalid-token"
        endpoint.write_text(json.dumps(data))
        with pytest.raises(IPCUnavailable):
            client.call("app.get_state")
    finally:
        server.close()


def test_history_roundtrip_keeps_editor_metadata(tmp_path):
    database = Database(tmp_path / "history.sqlite3")
    history = HistoryRepository(database)
    segment = TranscriptSegment(
        0.1, 1.2, "edited text", id="stable-uid", language="fa", metadata={"confidence": 0.8},
        is_edited=True, comment="check this", bookmarked=True, locked=True, reviewed=True,
    )
    transcript_id = history.save(title="Meta", text="edited text", original_text="original",
                                 segments=[segment], language="fa", duration=1.5)
    loaded = history.get(transcript_id)["segments"][0]
    assert loaded["id"] == "stable-uid"
    assert loaded["metadata"] == {"confidence": 0.8}
    assert loaded["comment"] == "check this"
    assert loaded["bookmarked"] and loaded["locked"] and loaded["reviewed"] and loaded["is_edited"]


def test_waveform_wav_fallback_is_bounded_and_cached(tmp_path, monkeypatch):
    import transcriber.audio.waveform as waveform_module

    source = tmp_path / "tone.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\xff\x7f" * 16000)
    monkeypatch.setattr(waveform_module.shutil, "which", lambda _name: None)
    first = build_waveform(source, tmp_path / "cache", bins=32)
    second = build_waveform(source, tmp_path / "cache", bins=32)
    assert first == second
    assert 0 < len(first) <= 32
    assert all(0 <= value <= 1 for value in first)


def test_audio_processing_is_non_destructive_and_validates_filter_ranges(tmp_path):
    source = tmp_path / "original.wav"
    source.write_bytes(b"input")
    assert build_filter_chain(normalize=True, highpass_hz=80, volume_db=3)[0] == "highpass=f=80"
    with pytest.raises(ValueError):
        build_filter_chain(highpass_hz=10)
    with pytest.raises(ValueError):
        process_audio(source, source, filters=["loudnorm"])
    assert source.read_bytes() == b"input"


def test_quality_report_only_uses_available_engine_confidence():
    from transcriber.transcription.quality_report import build_quality_report

    segments = [
        TranscriptSegment(
            0, 1.0, "hello world", id="a", speaker="A",
            words=[TranscriptWord(0.1, 0.4, "hello", 0.9), TranscriptWord(0.5, 0.9, "world", 0.2)],
        ),
        TranscriptSegment(2.0, 3.0, "hello world", id="b", speaker="B"),
    ]
    report = build_quality_report(segments=segments, language="en", duration=3.0)
    assert report.language == "en"
    assert report.segment_count == 2
    assert report.speaker_count == 2
    assert report.silence_regions == ((1.0, 2.0),)
    assert report.duplicate_segment_ids == ("a", "b")
    assert report.mean_word_confidence == pytest.approx(0.55)
    assert report.low_confidence_word_count == 1
    # There is no confidence evidence on segment b, so it is not scored.
    assert any(issue.code == "low-word-confidence" for issue in report.issues)


def test_opencode_acp_client_persistent_session_and_prompt(tmp_path):
    import os
    import sys

    import pytest

    if os.name != "posix":
        pytest.skip("The lightweight ACP simulator uses a POSIX executable shebang")

    from transcriber.opencode.acp_client import OpenCodeACPClient

    command_log = tmp_path / "acp-requests.jsonl"
    executable = tmp_path / "opencode-test"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    with open(os.environ['ACP_TEST_LOG'], 'a', encoding='utf-8') as log:\n"
        "        log.write(json.dumps(request) + '\\n')\n"
        "    method = request.get('method')\n"
        "    result = {'agentCapabilities': {'loadSession': True}} if method == 'initialize' else {}\n"
        "    if method == 'session/new': result = {'sessionId': 'session-test-1'}\n"
        "    if method == 'session/prompt': result = {'stopReason': 'end_turn'}\n"
        "    if method == 'session/load': result = {'loaded': True}\n"
        "    response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}\n"
        "    sys.stdout.write(json.dumps(response) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    os.environ["ACP_TEST_LOG"] = str(command_log)
    client = OpenCodeACPClient(str(executable), cwd=tmp_path)
    try:
        capabilities = client.start(timeout=3)
        assert capabilities["loadSession"] is True
        session_id = client.new_session(mcp_servers=[{
            "type": "stdio", "name": "transcriber", "command": sys.executable,
            "args": ["-m", "transcriber.mcp_server"], "env": {},
        }])
        assert session_id == "session-test-1"
        result = client.prompt("Summarize the current transcript", timeout=3)
        assert result["stopReason"] == "end_turn"
        client.cancel()
        lines = [__import__("json").loads(line) for line in command_log.read_text().splitlines()]
        new_session = next(item for item in lines if item["method"] == "session/new")
        assert new_session["params"]["mcpServers"][0]["name"] == "transcriber"
        prompt = next(item for item in lines if item["method"] == "session/prompt")
        assert prompt["params"]["sessionId"] == session_id
        assert prompt["params"]["prompt"][0]["text"] == "Summarize the current transcript"
        assert any(item["method"] == "session/cancel" for item in lines)
    finally:
        client.close()
        os.environ.pop("ACP_TEST_LOG", None)
    assert not client.connected


def test_icon_assets_are_packaged_inside_transcriber_package():
    from pathlib import Path

    import transcriber

    icon_dir = Path(transcriber.__file__).resolve().parent / "assets" / "icons"
    assert (icon_dir / "house.svg").is_file()
    assert (icon_dir / "LICENSE.txt").is_file()


def test_agent_destructive_action_requires_permission_and_user_approval():
    calls = []
    registry = ActionRegistry(
        permissions={AgentPermission.READ_ONLY, AgentPermission.DESTRUCTIVE_ACTIONS},
        approval=lambda _spec, _args: True,
    )
    registry.register(ActionSpec(
        "project.delete", "Delete a project", AgentPermission.READ_ONLY,
        lambda _args: calls.append("deleted") or {"deleted": True}, destructive=True,
    ))
    assert registry.execute("project.delete") == {"deleted": True}
    assert calls == ["deleted"]
    registry.set_permission(AgentPermission.DESTRUCTIVE_ACTIONS, False)
    with pytest.raises(PermissionDenied):
        registry.execute("project.delete")
    assert calls == ["deleted"]


def test_settings_agent_permissions_are_validated_and_default_safe(tmp_path):
    from transcriber.core.config import SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    store.load()
    assert set(store.settings.agent_permissions) == {"read_only", "edit_content"}
    store.update(agent_permissions=["read_only", "not-a-permission", "destructive_actions"])
    assert store.settings.agent_permissions == ["read_only", "destructive_actions"]


def test_packaged_mcp_entrypoint_does_not_import_qt(monkeypatch):
    import sys
    import types

    from transcriber import __main__ as app_entry

    called = []
    fake_module = types.ModuleType("transcriber.mcp_server")
    fake_module.main = lambda: called.append("mcp") or 17
    monkeypatch.setitem(sys.modules, "transcriber.mcp_server", fake_module)
    monkeypatch.setattr(sys, "argv", ["Transcriber", "--mcp-server"])
    assert app_entry.main() == 17
    assert called == ["mcp"]
    assert "PySide6" not in sys.modules
