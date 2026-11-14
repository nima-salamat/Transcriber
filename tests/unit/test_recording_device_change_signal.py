from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECORDING_SOURCE = PROJECT_ROOT / "src" / "transcriber" / "ui" / "pages" / "recording.py"


def test_audio_input_change_signal_is_connected_from_qmediadevices_instance() -> None:
    source = RECORDING_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(RECORDING_SOURCE))

    assignment_found = False
    assignment_line = 0
    connection_found = False
    invalid_class_connection_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == "media_devices"
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "QMediaDevices"
                ):
                    assignment_found = True
                    assignment_line = node.lineno

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "audioInputsChanged"
        ):
            signal_owner = node.func.value.value
            if (
                isinstance(signal_owner, ast.Name)
                and signal_owner.id == "QMediaDevices"
            ):
                invalid_class_connection_found = True
            if (
                isinstance(signal_owner, ast.Attribute)
                and isinstance(signal_owner.value, ast.Name)
                and signal_owner.value.id == "self"
                and signal_owner.attr == "media_devices"
            ):
                connection_found = True
                assert node.lineno > assignment_line, "Create the monitor before connecting its signal"

    assert not invalid_class_connection_found, "Do not connect audioInputsChanged through the class"
    assert assignment_found, "RecordingPage must own a QMediaDevices instance"
    assert connection_found, "audioInputsChanged must be connected from the instance signal"
