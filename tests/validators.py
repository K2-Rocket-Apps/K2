"""Structural validators for this marketplace's skills and JSON manifests.

Every function is pure: it reads the paths it is given and returns a list of
human-readable error strings (an empty list means the input passes). Nothing
here writes to disk, so each validator is easy to exercise against a
throwaway fixture.
"""

import json
import re
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
CROSS_REF_RE = re.compile(r"\[\[([a-z0-9-]+)\]\]")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Parse a markdown file's leading `---`-delimited YAML frontmatter.

    Returns (frontmatter_dict, body_text). Raises ValueError when there is no
    frontmatter block, the YAML does not parse, or it is not a mapping.
    """
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: no frontmatter block found (expected a leading '---' fence)")

    yaml_block, body = match.group(1), match.group(2)
    try:
        frontmatter = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: frontmatter is not valid YAML: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise ValueError(f"{path}: frontmatter must be a YAML mapping")

    return frontmatter, body


def validate_skill(skill_dir: Path) -> list[str]:
    """Validate one `skills/<name>/SKILL.md`.

    `name` must equal the folder name, and `description` must exist and start
    with "Use when" (a description states triggering conditions only).
    """
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    folder_name = skill_dir.name

    if not skill_md.exists():
        return [f"{skill_dir}: missing SKILL.md"]

    try:
        frontmatter, _ = parse_frontmatter(skill_md)
    except ValueError as exc:
        return [str(exc)]

    name = frontmatter.get("name")
    if not name:
        errors.append(f"{skill_md}: frontmatter is missing 'name'")
    elif name != folder_name:
        errors.append(f"{skill_md}: frontmatter 'name' ({name!r}) must equal the folder name ({folder_name!r})")

    description = frontmatter.get("description")
    if not description:
        errors.append(f"{skill_md}: frontmatter is missing 'description'")
    elif not isinstance(description, str) or not description.startswith("Use when"):
        errors.append(f"{skill_md}: 'description' must start with \"Use when\" (states triggering conditions only)")

    return errors


def _load_json(path: Path) -> tuple[dict | None, list[str]]:
    if not path.exists():
        return None, [f"{path}: file is missing"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{path}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path}: top level must be a JSON object"]
    return data, []


def validate_plugin_json(path: Path) -> list[str]:
    """Validate a plugin.json manifest: valid JSON, required keys, strict semver."""
    data, errors = _load_json(path)
    if data is None:
        return errors

    for key in ("name", "description", "version"):
        if not data.get(key):
            errors.append(f"{path}: missing required key '{key}'")

    version = data.get("version")
    if version and not (isinstance(version, str) and SEMVER_RE.match(version)):
        errors.append(f"{path}: version {version!r} is not valid semver (expected X.Y.Z)")

    return errors


def validate_marketplace_json(path: Path, repo_root: Path) -> list[str]:
    """Validate marketplace.json.

    Checks: valid JSON, required keys, a name that does not contain "claude"
    (Claude Code rejects that as marketplace impersonation), and that every
    listed plugin's `source` resolves to a real directory. `source` is
    relative to the repo root, not to marketplace.json's own directory.
    """
    data, errors = _load_json(path)
    if data is None:
        return errors

    name = data.get("name")
    if not name:
        errors.append(f"{path}: missing required key 'name'")
    elif "claude" in name.lower():
        errors.append(f"{path}: name {name!r} must not contain \"claude\" (rejected as marketplace impersonation)")

    owner = data.get("owner") or {}
    if not isinstance(owner, dict) or not owner.get("name"):
        errors.append(f"{path}: missing required key 'owner.name'")

    metadata = data.get("metadata") or {}
    if not metadata.get("description"):
        errors.append(f"{path}: missing required key 'metadata.description'")
    if not metadata.get("version"):
        errors.append(f"{path}: missing required key 'metadata.version'")

    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        errors.append(f"{path}: 'plugins' must be a non-empty list")
        return errors

    root = repo_root.resolve()
    for i, plugin in enumerate(plugins):
        if not isinstance(plugin, dict):
            errors.append(f"{path}: plugins[{i}] must be an object")
            continue
        if not plugin.get("name"):
            errors.append(f"{path}: plugins[{i}] is missing 'name'")
        source = plugin.get("source")
        if not source:
            errors.append(f"{path}: plugins[{i}] is missing 'source'")
            continue
        if not isinstance(source, str):
            errors.append(f"{path}: plugins[{i}] 'source' must be a relative path string in this repo")
            continue
        source_dir = (root / source).resolve()
        if root not in source_dir.parents and source_dir != root:
            errors.append(f"{path}: plugins[{i}] source {source!r} escapes the repository root")
        elif not source_dir.is_dir():
            errors.append(f"{path}: plugins[{i}] source {source!r} does not resolve to a real directory")

    return errors


def extract_cross_refs(text: str) -> set[str]:
    """Every [[skill-name]] cross-reference in a block of skill prose.

    Matches inside single-backtick inline code are ignored, so prose that
    documents the `[[name]]` syntax itself is not treated as a link.
    """
    return set(CROSS_REF_RE.findall(INLINE_CODE_RE.sub("", text)))


def validate_cross_refs(skill_dir: Path, known_skill_names: set[str]) -> list[str]:
    """Every [[name]] inside a skill's SKILL.md must name a skill in the same plugin."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return []

    text = skill_md.read_text(encoding="utf-8")
    return [
        f"{skill_md}: [[{ref}]] does not match any skill in this plugin"
        for ref in sorted(extract_cross_refs(text))
        if ref not in known_skill_names
    ]
