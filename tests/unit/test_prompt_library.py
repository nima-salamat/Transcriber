from __future__ import annotations

from transcriber.assistant.prompt_library import PromptLibrary


def test_prompt_library_seeds_specialist_workflows_and_bootstrap(tmp_path):
    library = PromptLibrary(tmp_path / "agent-prompts")

    names = {name for name, _title in library.list_prompts()}
    assert "00-AGENT.md" in names
    assert "01-INDEX.md" in names
    assert "20-transcript-editing.md" in names
    assert "30-subtitles.md" in names

    bootstrap = library.bootstrap_prompt()
    assert str(library.directory) in bootstrap
    assert "00-AGENT.md" in bootstrap
    assert "01-INDEX.md" in bootstrap


def test_prompt_library_preserves_user_edits_when_seeding(tmp_path):
    directory = tmp_path / "prompts"
    library = PromptLibrary(directory)
    library.save("20-transcript-editing.md", "# My workflow\nKeep the user's phrasing.")

    library.ensure_defaults()

    assert "Keep the user's phrasing." in library.read("20-transcript-editing.md")


def test_prompt_library_imports_clipboard_content_as_a_safe_markdown_file(tmp_path):
    library = PromptLibrary(tmp_path / "prompts")

    filename = library.import_prompt("../My copied prompt", "# My instructions\nDo useful work.")

    assert filename == "my-copied-prompt.md"
    assert library.read(filename) == "# My instructions\nDo useful work.\n"
    second = library.import_prompt("My copied prompt", "# Second copy")
    assert second == "my-copied-prompt-2.md"
    assert library.read(second) == "# Second copy\n"
