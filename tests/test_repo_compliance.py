"""Run the validators in validators.py against the REAL content of this repo.

A failure here means an actual file in this marketplace breaks an authoring
rule, not that a synthetic fixture does.
"""

from pathlib import Path

import pytest

from validators import (
    validate_cross_refs,
    validate_marketplace_json,
    validate_plugin_json,
    validate_skill,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _plugin_dirs(repo_root: Path) -> list[Path]:
    # iterdir() order is filesystem-dependent; sort so test IDs are stable.
    plugins_dir = repo_root / "plugins"
    if not plugins_dir.is_dir():
        return []
    return sorted(d for d in plugins_dir.iterdir() if d.is_dir())


def _skill_dirs(plugin_dir: Path) -> list[Path]:
    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(d for d in skills_dir.iterdir() if d.is_dir())


_PLUGIN_DIRS = _plugin_dirs(REPO_ROOT)
# Plugins that ship for Claude Code only, with no Codex manifest (the opt-in
# hooks plugin: Codex hook wiring is out of scope). Every other plugin must
# carry both manifests.
CLAUDE_ONLY_PLUGINS = frozenset({"k2-memory-hooks"})
_DUAL_PLUGIN_DIRS = [d for d in _PLUGIN_DIRS if d.name not in CLAUDE_ONLY_PLUGINS]
_SKILL_PARAMS = [(p, s.name) for p in _PLUGIN_DIRS for s in _skill_dirs(p)]
_SKILL_IDS = [f"{p.name}/{name}" for p, name in _SKILL_PARAMS]


def test_at_least_one_plugin_exists():
    assert _PLUGIN_DIRS, "expected at least one plugin under plugins/"


def test_marketplace_json_is_well_formed(repo_root):
    errors = validate_marketplace_json(repo_root / ".claude-plugin" / "marketplace.json", repo_root)
    assert errors == [], "\n".join(errors)


@pytest.mark.parametrize("plugin_dir", _PLUGIN_DIRS, ids=lambda d: d.name)
def test_claude_plugin_json_is_well_formed(plugin_dir):
    errors = validate_plugin_json(plugin_dir / ".claude-plugin" / "plugin.json")
    assert errors == [], "\n".join(errors)


@pytest.mark.parametrize("plugin_dir", _DUAL_PLUGIN_DIRS, ids=lambda d: d.name)
def test_codex_plugin_json_is_well_formed(plugin_dir):
    errors = validate_plugin_json(plugin_dir / ".codex-plugin" / "plugin.json")
    assert errors == [], "\n".join(errors)


@pytest.mark.parametrize("plugin_dir", _DUAL_PLUGIN_DIRS, ids=lambda d: d.name)
def test_both_manifests_agree_on_identity(plugin_dir):
    import json

    claude = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    codex = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    for key in ("name", "version", "description"):
        assert claude.get(key) == codex.get(key), f"{plugin_dir.name}: '{key}' differs between the two manifests"
    assert claude["name"] == plugin_dir.name


@pytest.mark.parametrize("name", sorted(CLAUDE_ONLY_PLUGINS))
def test_claude_only_plugin_has_no_codex_manifest_and_matching_name(name):
    import json

    plugin_dir = REPO_ROOT / "plugins" / name
    assert not (plugin_dir / ".codex-plugin").exists()
    claude = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert claude["name"] == name


def test_primary_plugin_ships_both_manifests():
    assert (REPO_ROOT / "plugins" / "k2") in _DUAL_PLUGIN_DIRS


def test_plugin_dirs_are_sorted_for_determinism():
    names = [d.name for d in _PLUGIN_DIRS]
    assert names == sorted(names)


@pytest.mark.parametrize("plugin_dir,skill_name", _SKILL_PARAMS, ids=_SKILL_IDS)
def test_skill_is_well_formed(plugin_dir, skill_name):
    errors = validate_skill(plugin_dir / "skills" / skill_name)
    assert errors == [], "\n".join(errors)


@pytest.mark.parametrize("plugin_dir,skill_name", _SKILL_PARAMS, ids=_SKILL_IDS)
def test_skill_cross_references_resolve(plugin_dir, skill_name):
    # Cross-references resolve within the owning plugin only.
    known = {d.name for d in _skill_dirs(plugin_dir)}
    errors = validate_cross_refs(plugin_dir / "skills" / skill_name, known)
    assert errors == [], "\n".join(errors)
