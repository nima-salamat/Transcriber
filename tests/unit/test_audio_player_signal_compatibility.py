from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAYER_SOURCE = PROJECT_ROOT / "src" / "transcriber" / "audio" / "player.py"


def test_qmediaplayer_64_bit_signals_are_bridged_through_python_callables() -> None:
    source = PLAYER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PLAYER_SOURCE))

    connections: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "connect" or not isinstance(node.func.value, ast.Attribute):
            continue
        signal_name = node.func.value.attr
        if signal_name in {"positionChanged", "durationChanged"}:
            connections[signal_name] = node

    assert set(connections) == {"positionChanged", "durationChanged"}
    for signal_name, connection in connections.items():
        assert connection.args, f"{signal_name} must have a connection target"
        target = connection.args[0]
        assert isinstance(target, ast.Lambda), (
            f"{signal_name} must bridge through a Python callable instead of connecting "
            "directly to a Qt Signal(int) with an incompatible qlonglong signature"
        )
        assert isinstance(target.body, ast.Call)
        assert isinstance(target.body.func, ast.Attribute)
        assert target.body.func.attr == "emit"
        assert target.body.args and isinstance(target.body.args[0], ast.Call)
        assert isinstance(target.body.args[0].func, ast.Name)
        assert target.body.args[0].func.id == "int"
