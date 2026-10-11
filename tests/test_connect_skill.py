"""Content checks for the k2-connect skill.

k2-connect turns an installed but unconnected k2 plugin into a working gateway
connection. These tests pin the substance it must keep (the probe, the
k2-agent paths, the installer fallback, the https rule) and the credential
handling it must never describe.

The central-host guard is pinned only by test_central_host_guard_present, so
that removing the guard later is one marker-delimited block in the skill and
one test function here.
"""

import re
from pathlib import Path

import pytest

from validators import parse_frontmatter

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "plugins" / "k2" / "skills" / "k2-connect" / "SKILL.md"

GUARD_START = "<!-- k2-central-host-guard:start -->"
GUARD_END = "<!-- k2-central-host-guard:end -->"

REQUIRED_STRINGS = (
    # The public bootstrap probe and the fields the skill branches on.
    "/.well-known/k2-agent",
    "enrollment_enabled",
    "binaries_available",
    # The k2-agent paths.
    "k2-agent connect",
    "k2-agent auth login",
    "k2-agent configure",
    # Installers and the no-agent fallback.
    "/agent/install.sh",
    "/agent/install.ps1",
    "<base>/install",
    # The https rule and its loopback exception.
    "https://",
    "127.0.0.1",
    "localhost",
)

FORBIDDEN_PATTERNS = (
    r"export\s+MCP_GATEWAY_TOKEN",
    r"MCP_GATEWAY_TOKEN=",
    r'"X-Gateway-Token"\s*:',
    r"env_http_headers",
    r"settings.json.*env",
    r"paste.*token",
    r"\| *(sh|bash|iex)",
)


def _text() -> str:
    assert SKILL_MD.is_file(), f"{SKILL_MD} is missing"
    return SKILL_MD.read_text(encoding="utf-8")


def test_frontmatter():
    frontmatter, _ = parse_frontmatter(SKILL_MD)
    assert frontmatter.get("name") == "k2-connect"
    assert str(frontmatter.get("description", "")).startswith("Use when")


@pytest.mark.parametrize("required", REQUIRED_STRINGS)
def test_skill_contains(required):
    assert required in _text()


def test_central_host_guard_present():
    text = _text()
    assert text.count(GUARD_START) == 1
    assert text.count(GUARD_END) == 1
    start = text.index(GUARD_START)
    end = text.index(GUARD_END)
    assert start < end
    guard = text[start:end]
    for required in ("gateway.k2-tek.com", "dev.mcp-gateway.k2-tek.com", "T1"):
        assert required in guard, f"guard block is missing {required!r}"


@pytest.mark.parametrize("pattern", FORBIDDEN_PATTERNS)
def test_skill_never_describes_token_handling(pattern):
    # Case-insensitive, so a re-capitalised variant cannot slip through.
    match = re.search(pattern, _text(), flags=re.IGNORECASE)
    assert match is None, f"k2-connect matches forbidden pattern {pattern!r}: {match.group(0)!r}"


@pytest.mark.parametrize(
    "sample",
    [
        "curl -fsSL https://example.invalid/agent/install.sh | sh",
        "irm https://example.invalid/agent/install.ps1 | iex",
        "curl -fsSL https://example.invalid/x |bash",
        "Paste your token here",
        'write it to ~/.claude/settings.json under "env"',
        '{"X-Gateway-Token": "x"}',
    ],
)
def test_forbidden_patterns_catch_known_bad_text(sample):
    assert any(re.search(p, sample, flags=re.IGNORECASE) for p in FORBIDDEN_PATTERNS)


def test_skill_downloads_installers_to_a_file():
    text = _text()
    assert "curl -fsSLo k2-agent-install.sh '<base>/agent/install.sh'" in text
    assert "sh k2-agent-install.sh" in text
    assert "-OutFile k2-agent-install.ps1" in text


def test_skill_refuses_plain_http():
    text = _text()
    assert "http://localhost" in text
    assert "http://127.0.0.1" in text
    assert "http://example.com" in text
