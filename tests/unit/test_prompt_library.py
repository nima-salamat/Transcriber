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



def test_prompt_context_includes_current_coordinator_index_and_relevant_specialist(tmp_path):
    library = PromptLibrary(tmp_path / "prompts")

    context = library.context_for_request(
        "Choose a Vosk wake-word model and configure the activation keyword."
    )

    assert "PROMPT FILE: 00-AGENT.md" in context
    assert "PROMPT FILE: 01-INDEX.md" in context
    assert "PROMPT FILE: 50-workspace-actions.md" in context
    assert "PROMPT FILE: 60-voice-agent.md" in context
    assert "phrase made of words the selected model can recognize" in context
    assert "PROMPT FILE: 30-subtitles.md" not in context


def test_prompt_context_reloads_user_edits_instead_of_caching(tmp_path):
    library = PromptLibrary(tmp_path / "prompts")

    library.save("60-voice-agent.md", "# Updated voice workflow\nUse the chosen language model.")
    context = library.context_for_request("Set my wake word and Vosk activation phrase.")

    assert "Use the chosen language model." in context


def test_copied_prompt_pack_is_self_contained_and_includes_voice_specialist(tmp_path):
    library = PromptLibrary(tmp_path / "prompts")

    copied = library.export_prompt_pack()

    assert str(library.directory) in copied
    assert "PROMPT FILE: 00-AGENT.md" in copied
    assert "PROMPT FILE: 60-voice-agent.md" in copied
    assert "The selected Vosk model is the local wake-word detector only." in copied
