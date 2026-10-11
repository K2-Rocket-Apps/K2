"""The opt-in hooks plugin touches no scheduler, no global git config, no
credential and no network: everything it sends goes through k2-agent."""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_DIR = REPO_ROOT / "plugins" / "k2-memory-hooks"

BANNED = (
    "launchctl",
    "systemctl",
    "schtasks",
    "crontab",
    "git config --global",
    "safe.directory",
    "insteadOf",
    "MEMORY_HOOK_" + "TOKEN",
    "mgw" + "_",
    "urllib",
    "import requests",
)
URL_SCHEMES = ("http://", "https://")


def _files():
    files = sorted(p for p in PLUGIN_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    assert files, "plugin directory is empty"
    return files


@pytest.mark.parametrize("needle", BANNED)
def test_no_banned_string_anywhere_in_the_plugin(needle):
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{n}"
        for p in _files()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if needle.lower() in line.lower()
    ]
    assert hits == []


@pytest.mark.parametrize("scheme", URL_SCHEMES)
def test_no_url_outside_the_readme(scheme):
    hits = [
        str(p.relative_to(REPO_ROOT))
        for p in _files()
        if p.name != "README.md" and scheme in p.read_text(encoding="utf-8")
    ]
    assert hits == []


def test_scripts_and_hooks_json_carry_no_url_at_all():
    for rel in ("hooks/hooks.json", "hooks/heartbeat.py", "hooks/friction.py", "hooks/lib/hook_common.py"):
        text = (PLUGIN_DIR / rel).read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, rel


def test_the_scan_itself_catches_a_planted_string(tmp_path):
    planted = tmp_path / "x.py"
    planted.write_text("import " + "urllib.request\n")
    assert any(n.lower() in planted.read_text().lower() for n in BANNED)
