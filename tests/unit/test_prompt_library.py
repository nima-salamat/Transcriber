from __future__ import annotations

from transcriber.assistant.prompt_library import (\n    LEGACY_DEFAULT_PROMPTS,\n    LEGACY_DEFAULT_PROMPT_VERSIONS,\n    PromptLibrary,\n)


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


def test_prompt_library_migrates_unchanged_legacy_agent_prompts(tmp_path):
    directory = tmp_path / "prompts"
    library = PromptLibrary(directory)

    for filename in ("00-AGENT.md", "50-workspace-actions.md"):
        legacy = LEGACY_DEFAULT_PROMPTS[filename].replace(
            "{PROMPT_DIRECTORY}", str(directory.resolve())
        )
        (directory / filename).write_text(legacy.rstrip() + "\n", encoding="utf-8")

    library.ensure_defaults()

    coordinator = library.read("00-AGENT.md")
    workspace = library.read("50-workspace-actions.md")
    assert "general-purpose desktop, development, file and web agent" in coordinator
    assert "not a browser-only assistant" in coordinator
    assert "system.run_command" in coordinator
    assert "Transcriber host actions and permissions" in workspace
    assert "general-purpose system.run_command" in workspace
    assert "OpenCode calls" in workspace
    assert "native terminal/shell" in workspace


def test_prompt_library_does_not_overwrite_customized_agent_prompt_during_migration(tmp_path):
    directory = tmp_path / "prompts"
    library = PromptLibrary(directory)
    custom = "# My general agent\nRun approved commands and keep my workflow."
    library.save("00-AGENT.md", custom)

    library.ensure_defaults()

    assert library.read("00-AGENT.md") == custom + "\n"


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
    assert "Do not promise reliable detection for an out-of-vocabulary" in context
    assert "PROMPT FILE: 30-subtitles.md" not in context


def test_general_windows_tasks_do_not_load_transcription_or_workspace_specialists(tmp_path):
    library = PromptLibrary(tmp_path / "prompts")

    request = "Run Get-ChildItem in PowerShell and inspect the project folder."
    selected = library.prompt_files_for_request(request)
    context = library.context_for_request(request)

    assert selected == []
    assert "general-purpose desktop, development, file and web agent" in context
    assert "not a browser-only assistant" in context
    assert "system.run_command" in context
    assert "PROMPT FILE: 10-transcription.md" not in context
    assert "PROMPT FILE: 50-workspace-actions.md" not in context


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



def test_prompt_library_migrates_previous_workspace_prompt_without_overwriting_custom_edits(
    tmp_path,
):
    directory = tmp_path / "prompts"
    library = PromptLibrary(directory)
    previous = LEGACY_DEFAULT_PROMPT_VERSIONS["50-workspace-actions.md"][0].replace(
        "{PROMPT_DIRECTORY}", str(directory.resolve())
    )
    (directory / "50-workspace-actions.md").write_text(
        previous.rstrip() + "\n", encoding="utf-8"
    )

    library.ensure_defaults()

    workspace = library.read("50-workspace-actions.md")
    assert "Transcriber host actions and permissions" in workspace
    assert "general-purpose system.run_command" in workspace
    assert "app_execute_action" in workspace
    assert "OpenCode native terminal/shell" in workspace
