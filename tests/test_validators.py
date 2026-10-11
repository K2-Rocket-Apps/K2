"""Fixture tests for validators.py: each validator accepts a good input and
rejects each kind of bad one."""

import json
from pathlib import Path

from validators import (
    extract_cross_refs,
    validate_cross_refs,
    validate_marketplace_json,
    validate_plugin_json,
    validate_skill,
)


def _skill(tmp_path: Path, folder: str, frontmatter: str, body: str = "Body.\n") -> Path:
    skill_dir = tmp_path / "skills" / folder
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}")
    return skill_dir


def test_validate_skill_accepts_good_skill(tmp_path):
    d = _skill(tmp_path, "demo", "name: demo\ndescription: Use when testing.")
    assert validate_skill(d) == []


def test_validate_skill_rejects_name_mismatch(tmp_path):
    d = _skill(tmp_path, "demo", "name: other\ndescription: Use when testing.")
    assert validate_skill(d)


def test_validate_skill_rejects_description_without_use_when(tmp_path):
    d = _skill(tmp_path, "demo", "name: demo\ndescription: Does things.")
    assert validate_skill(d)


def test_validate_skill_rejects_missing_frontmatter(tmp_path):
    d = tmp_path / "skills" / "demo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("no frontmatter\n")
    assert validate_skill(d)


def test_validate_skill_rejects_missing_file(tmp_path):
    d = tmp_path / "skills" / "demo"
    d.mkdir(parents=True)
    assert validate_skill(d)


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def test_validate_plugin_json(tmp_path):
    good = {"name": "x", "description": "d", "version": "1.2.3"}
    assert validate_plugin_json(_write(tmp_path / "a.json", good)) == []
    assert validate_plugin_json(_write(tmp_path / "b.json", {**good, "version": "1.2"}))
    assert validate_plugin_json(_write(tmp_path / "c.json", {"name": "x"}))
    (tmp_path / "d.json").write_text("{not json")
    assert validate_plugin_json(tmp_path / "d.json")


def _marketplace(name="k2", source="./plugins/k2"):
    return {
        "name": name,
        "owner": {"name": "o"},
        "metadata": {"description": "d", "version": "0.1.0"},
        "plugins": [{"name": "k2", "source": source}],
    }


def test_validate_marketplace_json(tmp_path):
    (tmp_path / "plugins" / "k2").mkdir(parents=True)
    path = tmp_path / ".claude-plugin" / "marketplace.json"
    assert validate_marketplace_json(_write(path, _marketplace()), tmp_path) == []
    assert validate_marketplace_json(_write(path, _marketplace(name="my-claude-tools")), tmp_path)
    assert validate_marketplace_json(_write(path, _marketplace(source="./plugins/missing")), tmp_path)
    assert validate_marketplace_json(_write(path, _marketplace(source="../outside")), tmp_path)


def test_cross_refs(tmp_path):
    d = _skill(tmp_path, "a", "name: a\ndescription: Use when.", "See [[b]] and `[[literal]]`.\n")
    assert extract_cross_refs((d / "SKILL.md").read_text()) == {"b"}
    assert validate_cross_refs(d, {"a", "b"}) == []
    assert validate_cross_refs(d, {"a"})
