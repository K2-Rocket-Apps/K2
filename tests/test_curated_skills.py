"""Content checks for the curated skills shipped in the k2 plugin.

The k2 plugin ships a short, deliberate list of skills. Each one is a public
rewrite, so these tests pin the substance each skill must keep and the
content it must never carry. Adding a skill means adding its folder name to
ALLOWED_SKILLS here, in the same change that adds the skill.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "plugins" / "k2" / "skills"

ALLOWED_SKILLS = frozenset(
    {
        "mcp-step-up-approval",
        "cross-repo-code-lookup",
        "memory-orchestrate",
        "k2-connect",
    }
)

# A tracker reference such as "repo#123": public skills cite no issue or
# review numbers.
TRACKER_REF_RE = re.compile(r"[A-Za-z-]+#\d+")


def _skill_dirs() -> list[Path]:
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())


def _skill_text(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    assert path.is_file(), f"{path} is missing"
    return path.read_text(encoding="utf-8")


def _all_skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.rglob("*")) if SKILLS_DIR.is_dir() else []


def test_skill_folders_are_allow_listed():
    unlisted = sorted(p.name for p in _skill_dirs() if p.name not in ALLOWED_SKILLS)
    assert not unlisted, f"skills not on the allow-list: {unlisted}"


@pytest.mark.parametrize("name", ["mcp-step-up-approval", "cross-repo-code-lookup", "memory-orchestrate"])
def test_curated_skill_is_present(name):
    _skill_text(name)


def test_memory_orchestrate_is_gateway_only():
    text = _skill_text("memory-orchestrate")
    assert "memory.declare_scope" in text
    assert "250000" in text
    for banned in ("run-waves", "RemoteTrigger", "bypass"):
        assert banned not in text, f"memory-orchestrate must not mention {banned!r}"


@pytest.mark.parametrize("required", ["indexed_sha", "static", "resolved", "heuristic", "UNKNOWN"])
def test_cross_repo_code_lookup_keeps_its_reading_rules(required):
    assert required in _skill_text("cross-repo-code-lookup")


def test_mcp_step_up_approval_keeps_its_core_rules():
    text = _skill_text("mcp-step-up-approval")
    for required in ("user_code", "k2-agent approve", "Never fabricate a code", "approval_required"):
        assert required in text


@pytest.mark.parametrize("path", [p for p in _all_skill_files() if p.is_file()], ids=lambda p: str(p.relative_to(SKILLS_DIR)))
def test_skill_files_cite_no_tracker_numbers(path):
    text = path.read_text(encoding="utf-8")
    assert "finding #" not in text
    match = TRACKER_REF_RE.search(text)
    assert match is None, f"{path}: tracker reference {match.group(0)!r}"


def test_tracker_ref_pattern_catches_references():
    assert TRACKER_REF_RE.search("see some-repo#42")
    assert TRACKER_REF_RE.search("issue#7")
    assert not TRACKER_REF_RE.search("an issue number such as `#12`")


def test_allow_list_check_rejects_unlisted_skill(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "memory-orchestrate").mkdir(parents=True)
    (skills / "something-else").mkdir()
    monkeypatch.setattr(__import__(__name__), "SKILLS_DIR", skills)
    with pytest.raises(AssertionError):
        test_skill_folders_are_allow_listed()
