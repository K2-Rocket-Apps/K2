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


AGENT_WIRING_COMMAND = re.compile(r"^\s*(?:\S+=\S+\s+)*k2-agent\s+(connect|configure)\b.*$")


def _command_lines(text: str) -> list[str]:
    """Lines inside fenced code blocks: the commands the skill tells you to run."""
    lines, in_block = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_block = not in_block
            continue
        if in_block:
            lines.append(line)
    return lines


def test_every_agent_wiring_command_is_scoped_to_claude_code_and_codex():
    # Wiring Cursor makes k2-agent persist a gateway access key into a shell
    # profile or a user environment variable, so every connect/configure the
    # skill prescribes must name only the two in-scope clients.
    commands = [l for l in _command_lines(_text()) if AGENT_WIRING_COMMAND.match(l)]
    assert commands, "no k2-agent connect/configure command found in a code block"
    for command in commands:
        assert "--client claude-code,codex" in command, f"unscoped agent command: {command.strip()!r}"


def test_skill_never_claims_to_wire_cursor():
    text = _text()
    assert re.search(r"configures? every detected client", text, flags=re.IGNORECASE) is None
    assert "(Claude Code, Codex, Cursor)" not in text


def test_skill_checks_for_cursor_before_running_the_installer():
    text = _text()
    installer = text.index("curl -fsSLo k2-agent-install.sh")
    cursor_check = text.index("ls -d ~/.cursor; command -v cursor")
    assert cursor_check < installer
    assert "do not run the installer" in text


def test_central_host_comparison_normalises_port_and_trailing_dot():
    text = _text()
    guard = text[text.index(GUARD_START):text.index(GUARD_END)]
    assert "drop any port" in guard
    assert "trailing dot" in guard
