from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAYER_SOURCE = PROJECT_ROOT / "src" / "transcriber" / "audio" / "player.py"


def test_audio_player_exposes_a_public_stop_method() -> None:
    source = PLAYER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PLAYER_SOURCE))
    audio_player = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AudioPlayer"
    )
    stop_method = next(
        (
            node for node in audio_player.body
            if isinstance(node, ast.FunctionDef) and node.name == "stop"
        ),
        None,
    )
    assert stop_method is not None, "Embedded preview controllers need AudioPlayer.stop()"
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stop"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "player"
        for node in ast.walk(stop_method)
    ), "AudioPlayer.stop() must stop QMediaPlayer without clearing the loaded source"
