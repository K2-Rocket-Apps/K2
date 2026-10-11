"""Static and offline checks for the anonymous install smoke test.

`scripts/install-smoke.sh` and `.github/workflows/install-smoke.yml` prove the
k2 marketplace installs with no GitHub CLI and no credential. These tests pin
the properties that make that proof honest: the script never edits git config
itself, runs strict, refuses to run when `gh` is present, and the workflow can
never run on a pull request, holds no token permissions and pins its CLIs to
the same versions as validate.yml.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "install-smoke.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SMOKE_WORKFLOW = WORKFLOWS / "install-smoke.yml"

USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)")


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _code() -> str:
    """The script without its comment lines (the header describes commands it never runs)."""
    return "\n".join(line for line in _script().splitlines() if not line.lstrip().startswith("#"))


def _workflow(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


# --------------------------------------------------------------------------
# Script
# --------------------------------------------------------------------------


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_script_never_runs_global_git_config():
    assert "git config --global" not in _script()
    # No git config command anywhere in command position: the isolation is env-only.
    assert not re.search(r"(^|[;&|(]|\bthen|\bdo)\s*git\s+config\b", _code(), re.M), "the script must not run git config"


def test_script_runs_strict():
    lines = [line.strip() for line in _script().splitlines()]
    assert lines[0] == "#!/usr/bin/env bash"
    first_code = next(line for line in lines[1:] if line and not line.startswith("#"))
    assert first_code == "set -euo pipefail"


def test_script_isolates_home_and_git_config_through_the_environment():
    text = _script()
    assert 'export GIT_CONFIG_GLOBAL="$HOME/.gitconfig" GIT_CONFIG_NOSYSTEM=1' in text
    assert "GIT_TERMINAL_PROMPT=0" in text
    assert 'SMOKE_HOME="$(mktemp -d)"' in text and 'HOME="$SMOKE_HOME"' in text
    assert 'SMOKE_CODEX_HOME="$(mktemp -d)"' in text and 'CODEX_HOME="$SMOKE_CODEX_HOME"' in text
    assert re.search(r"^unset GH_TOKEN GITHUB_TOKEN\b", text, re.M)


def test_script_asserts_gh_is_absent_before_any_install():
    text = _code()
    gh_check = text.index("command -v gh")
    first_install = text.index("claude plugin marketplace add")
    assert gh_check < first_install


def test_script_checks_the_install_outcomes():
    text = _script()
    for needle in (
        "claude plugin install k2@k2 --scope user",
        "codex plugin add k2@k2",
        "codex mcp list --json",
        '"[]"',
        "k2-memory-hooks",
        "tests/test_curated_skills.py",
        "ALLOWED_SKILLS",
    ):
        assert needle in text, needle
    assert not re.search(r"plugin (install|add) k2-memory-hooks", text), "the script must never install k2-memory-hooks"


def test_script_checks_the_pinned_version_on_both_clis():
    text = _script()
    assert "EXPECTED_VERSION" in text
    assert re.search(r"\^v\(\[0-9\]\+", text), "a #vX.Y.Z source must derive the expected version"
    assert "k2.version !== process.env.EXPECTED_VERSION" in text
    assert '[ "$CACHED_VERSION" = "$EXPECTED_VERSION" ]' in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_script_fails_when_gh_is_on_path(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "gh-was-called"
    gh = fake_bin / "gh"
    gh.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
    gh.chmod(0o755)
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "TMPDIR": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(SCRIPT), "K2-Rocket-Apps/k2"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "GitHub CLI is on PATH" in result.stderr
    assert not marker.exists(), "the script must not run gh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_script_requires_a_source():
    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "usage:" in result.stderr


# --------------------------------------------------------------------------
# Workflow
# --------------------------------------------------------------------------


def test_workflow_triggers_never_include_pull_request():
    triggers = _workflow(SMOKE_WORKFLOW)["on"]
    assert set(triggers) == {"workflow_dispatch", "release", "schedule"}
    assert triggers["release"] == {"types": ["published"]}
    assert len(triggers["schedule"]) == 1
    assert not any(t.startswith("pull_request") for t in triggers)


def test_workflow_has_no_permissions_and_no_secrets():
    wf = _workflow(SMOKE_WORKFLOW)
    assert wf["permissions"] == {}
    for job in wf["jobs"].values():
        assert "permissions" not in job
    assert "secrets." not in SMOKE_WORKFLOW.read_text(encoding="utf-8")


def test_workflow_runs_in_a_bare_node_container_on_a_hosted_runner():
    for job in _workflow(SMOKE_WORKFLOW)["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"
        assert job["container"]["image"] == "node:22-bookworm-slim"


def test_workflow_actions_are_pinned_to_full_shas():
    for line in SMOKE_WORKFLOW.read_text(encoding="utf-8").splitlines():
        match = USES_RE.match(line)
        if match:
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", match.group(1)), match.group(1)


def test_workflow_pins_the_same_cli_versions_as_validate():
    smoke = _workflow(SMOKE_WORKFLOW)["env"]
    validate = _workflow(WORKFLOWS / "validate.yml")["env"]
    for key in ("CLAUDE_CODE_VERSION", "CODEX_VERSION"):
        assert re.fullmatch(r"\d+\.\d+\.\d+", smoke[key]), key
        assert smoke[key] == validate[key], key


def test_workflow_runs_unpinned_then_pinned_to_a_release_tag():
    (job,) = _workflow(SMOKE_WORKFLOW)["jobs"].values()
    runs = [step.get("run", "") for step in job["steps"]]
    smoke_runs = [r for r in runs if "scripts/install-smoke.sh" in r]
    assert smoke_runs == [
        'bash "$SMOKE_SRC/scripts/install-smoke.sh" "$SMOKE_REPO"',
        'bash "$SMOKE_SRC/scripts/install-smoke.sh" "$SMOKE_REPO#$SMOKE_TAG"',
    ]
    resolve_step = next(step for step in job["steps"] if "SMOKE_TAG=" in step.get("run", ""))
    resolve = resolve_step["run"]
    assert "git ls-remote --tags" in resolve
    assert runs.index(resolve) < runs.index(smoke_runs[1])
    # A release event pins the tag it published, passed through env (never
    # interpolated into the script body).
    assert resolve_step["env"]["RELEASE_TAG"] == "${{ github.event.release.tag_name }}"
    assert "${{" not in resolve
    assert '"$RELEASE_TAG"' in resolve


def test_workflow_never_interpolates_expressions_into_run_scripts():
    (job,) = _workflow(SMOKE_WORKFLOW)["jobs"].values()
    for step in job["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")


def test_workflow_never_installs_or_calls_gh():
    text = SMOKE_WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"apt-get install[^\n]*\bgh\b", text)
    assert not re.search(r"^\s*gh\s", text, re.M)
