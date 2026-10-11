"""hooks.json for the opt-in k2-memory-hooks plugin, and proof that the
default `k2` plugin never pulls it in."""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "k2-memory-hooks"
HOOKS_JSON = PLUGIN_DIR / "hooks" / "hooks.json"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

HEARTBEAT = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/heartbeat.py"'
FRICTION = 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/friction.py"'
TEST_RUNNERS = (
    "vendor/bin/pest *",
    "php artisan test *",
    "npm test *",
    "npm run test *",
    "pytest *",
    "python -m pytest *",
)
EXCLUDED_FLOWS = ("personal-context", "collision-check", "pre_commit_scan", "subagent_prompt_lint")


def _hooks():
    return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]


def _entries(event):
    """(matcher, hook) pairs for one event."""
    return [(group.get("matcher"), hook) for group in _hooks()[event] for hook in group["hooks"]]


def test_hook_event_set_is_exact():
    assert set(_hooks()) == {"Stop", "SubagentStop", "PreToolUse", "PostToolUse", "PostToolUseFailure"}


def test_every_command_runs_only_heartbeat_or_friction():
    for event in _hooks():
        for _, hook in _entries(event):
            assert hook["type"] == "command"
            assert hook["command"] in {HEARTBEAT, FRICTION}, hook["command"]
            assert re.search(r"/hooks/(heartbeat|friction)\.py\"$", hook["command"])


def test_every_hook_is_async():
    for event in _hooks():
        for _, hook in _entries(event):
            assert hook.get("async") is True, f"{event}: {hook}"


@pytest.mark.parametrize("flow", EXCLUDED_FLOWS)
def test_no_excluded_data_flow_is_referenced(flow):
    text = HOOKS_JSON.read_text(encoding="utf-8")
    assert flow not in text
    for path in PLUGIN_DIR.rglob("*"):
        assert flow not in path.name


@pytest.mark.parametrize("event", ["Stop", "SubagentStop"])
def test_heartbeat_on_stop_events_without_matcher(event):
    assert _entries(event) == [(None, {"type": "command", "command": HEARTBEAT, "async": True})]


def test_heartbeat_on_git_push_only_for_pre_tool_use():
    assert _entries("PreToolUse") == [
        ("Bash", {"type": "command", "command": HEARTBEAT, "if": "Bash(git push *)", "async": True})
    ]


@pytest.mark.parametrize("event", ["PostToolUse", "PostToolUseFailure"])
def test_friction_on_the_six_test_runners(event):
    entries = _entries(event)
    assert all(matcher == "Bash" for matcher, _ in entries)
    assert all(hook["command"] == FRICTION for _, hook in entries)
    assert [hook["if"] for _, hook in entries] == [f"Bash({runner})" for runner in TEST_RUNNERS]


def test_only_the_expected_files_ship():
    shipped = sorted(p.relative_to(PLUGIN_DIR).as_posix() for p in PLUGIN_DIR.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    assert shipped == [
        ".claude-plugin/plugin.json",
        "README.md",
        "hooks/friction.py",
        "hooks/heartbeat.py",
        "hooks/hooks.json",
        "hooks/lib/hook_common.py",
    ]


# --------------------------------------------------------------------------
# The default plugin never enables these hooks
# --------------------------------------------------------------------------


def _market():
    return json.loads(MARKETPLACE.read_text(encoding="utf-8"))


def test_marketplace_lists_the_hooks_plugin_as_its_own_entry():
    entries = {e["name"]: e for e in _market()["plugins"]}
    assert set(entries) == {"k2", "k2-memory-hooks"}
    assert entries["k2-memory-hooks"]["source"] == "./plugins/k2-memory-hooks"
    assert entries["k2"]["source"] == "./plugins/k2"
    assert _market()["plugins"][0]["name"] == "k2"


@pytest.mark.parametrize(
    "manifest",
    [REPO_ROOT / "plugins" / "k2" / ".claude-plugin" / "plugin.json",
     REPO_ROOT / "plugins" / "k2" / ".codex-plugin" / "plugin.json"],
    ids=["claude", "codex"],
)
def test_k2_manifest_does_not_list_or_depend_on_the_hooks_plugin(manifest):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert "dependencies" not in data
    assert "hooks" not in data
    assert "k2-memory-hooks" not in manifest.read_text(encoding="utf-8")


def test_k2_marketplace_entry_does_not_depend_on_or_inline_hooks():
    entry = next(e for e in _market()["plugins"] if e["name"] == "k2")
    assert "dependencies" not in entry
    assert "hooks" not in entry
    assert "k2-memory-hooks" not in json.dumps(entry)


def test_installing_the_default_plugin_copies_no_hooks():
    """An install copies the k2 plugin's source directory, and only that. It
    contains no hooks file and nothing that points at the hooks plugin."""
    k2_dir = REPO_ROOT / "plugins" / "k2"
    files = [p for p in k2_dir.rglob("*") if p.is_file()]
    assert files
    assert not any(p.name == "hooks.json" or "hooks" in p.relative_to(k2_dir).parts for p in files)
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "k2-memory-hooks" not in text, f"{path} references the opt-in hooks plugin"


def test_ci_validates_the_hooks_plugin_and_the_default_install():
    import yaml

    wf = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8"))
    runs = "\n".join(s.get("run", "") for s in wf["jobs"]["claude-plugin-validate"]["steps"])
    assert "claude plugin validate plugins/k2-memory-hooks --strict" in runs
    assert "claude plugin install k2@k2 --scope user" in runs
    assert 'enabled == {"k2@k2": True}' in runs
    codex = "\n".join(s.get("run", "") for s in wf["jobs"]["codex-install"]["steps"])
    assert "k2-memory-hooks" in codex
    for job in wf["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"
