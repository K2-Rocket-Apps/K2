"""Version gates for the k2 plugin.

Two checks, both runnable from CI:

* Release mode (`--tag vX.Y.Z`): the pushed tag must be exactly `v` + the
  version that the marketplace metadata, the k2 Claude and Codex manifests
  and the k2-memory-hooks manifest all declare, and CHANGELOG.md must carry a `## vX.Y.Z` section.
  `.github/workflows/release.yml` runs this before anything is built, so a
  mismatched tag fails the run and no Release is created.

* PR mode (`--base <ref> [--head <ref>]`): a change to anything under
  `plugins/k2/` or `plugins/k2-memory-hooks/` must come with a version
  increase. Installed copies are
  cached by version, so shipping new content under an old version would
  leave existing installs silently stale. `.github/workflows/validate.yml`
  runs this as the `version-bump` job.

`--notes vX.Y.Z` prints that version's CHANGELOG section (the release notes).

The pure functions (`check`, `requires_version_bump`, `changelog_section`)
are unit-tested directly in test_version_consistency.py; `main()` only
gathers inputs from the working tree or from git.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PLUGIN = "k2"
PLUGIN_PREFIX = f"plugins/{PLUGIN}/"
MARKETPLACE_JSON = ".claude-plugin/marketplace.json"
CLAUDE_PLUGIN_JSON = f"plugins/{PLUGIN}/.claude-plugin/plugin.json"
CODEX_PLUGIN_JSON = f"plugins/{PLUGIN}/.codex-plugin/plugin.json"

# The opt-in hooks plugin ships in the same marketplace at the same version.
# Its installs are cached by version too, so its content changes need a bump.
HOOK_PLUGIN = "k2-memory-hooks"
HOOK_PLUGIN_PREFIX = f"plugins/{HOOK_PLUGIN}/"
HOOK_PLUGIN_JSON = f"plugins/{HOOK_PLUGIN}/.claude-plugin/plugin.json"
VERSIONED_PREFIXES = (PLUGIN_PREFIX, HOOK_PLUGIN_PREFIX)
CHANGELOG = "CHANGELOG.md"

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


# --------------------------------------------------------------------------
# Pure logic
# --------------------------------------------------------------------------


def _version_of(manifest: object, *path: str) -> object:
    node = manifest
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def check(
    tag: str,
    marketplace_json: Mapping,
    claude_plugin_json: Mapping,
    codex_plugin_json: Mapping,
    hook_plugin_json: Mapping | None = None,
) -> list[str]:
    """Errors when the manifest versions differ, are not strict semver, or
    when `tag` is not exactly `'v' + version`. An empty list means the tag
    may be released. `hook_plugin_json`, when given, is held to the same
    version."""
    versions = {
        f"{MARKETPLACE_JSON} metadata.version": _version_of(marketplace_json, "metadata", "version"),
        f"{CLAUDE_PLUGIN_JSON} version": _version_of(claude_plugin_json, "version"),
        f"{CODEX_PLUGIN_JSON} version": _version_of(codex_plugin_json, "version"),
    }
    if hook_plugin_json is not None:
        versions[f"{HOOK_PLUGIN_JSON} version"] = _version_of(hook_plugin_json, "version")

    errors: list[str] = []
    for where, version in versions.items():
        if not (isinstance(version, str) and SEMVER_RE.match(version)):
            errors.append(f"{where}: {version!r} is not strict semver X.Y.Z")

    distinct = {str(v) for v in versions.values()}
    if len(distinct) > 1:
        detail = ", ".join(f"{where} = {v!r}" for where, v in versions.items())
        errors.append(f"manifest versions differ: {detail}")
        return errors

    version = next(iter(distinct))
    if tag != f"v{version}":
        errors.append(f"tag {tag!r} does not match the manifest version: expected 'v{version}'")
    return errors


def parse_semver(version: object) -> tuple[int, int, int] | None:
    if not isinstance(version, str):
        return None
    match = SEMVER_RE.match(version)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def requires_version_bump(
    changed_files: list[str], base_version: str | None, head_version: str | None
) -> list[str]:
    """Errors when a file under plugins/k2/ or plugins/k2-memory-hooks/
    changed but the version did not increase. `base_version` None means the
    plugin did not exist at the base ref, so there is nothing to bump against."""
    content_changes = sorted(f for f in changed_files if f.startswith(VERSIONED_PREFIXES))
    if not content_changes or base_version is None:
        return []

    base, head = parse_semver(base_version), parse_semver(head_version)
    if head is None:
        return [f"{CLAUDE_PLUGIN_JSON}: head version {head_version!r} is not strict semver X.Y.Z"]
    if base is not None and head > base:
        return []
    if base is None:
        # A non-semver base cannot be ordered; a changed version string is the
        # best evidence of a bump available.
        if head_version != base_version:
            return []

    shown = ", ".join(content_changes[:3]) + (" …" if len(content_changes) > 3 else "")
    return [
        f"{shown} changed but the k2 version did not increase "
        f"(base {base_version}, head {head_version}). Bump the version in "
        f"{MARKETPLACE_JSON}, {CLAUDE_PLUGIN_JSON}, {CODEX_PLUGIN_JSON} and {HOOK_PLUGIN_JSON}, "
        f"and add a CHANGELOG.md entry."
    ]


_HEADING_RE = re.compile(r"^##\s+(\S+)")


def changelog_section(text: str, tag: str) -> str | None:
    """Body of the `## <tag>` section of a changelog, or None if absent/empty."""
    lines = text.splitlines()
    body: list[str] | None = None
    for line in lines:
        heading = _HEADING_RE.match(line)
        if heading and not line.startswith("###"):
            if body is not None:
                break
            if heading.group(1) == tag:
                body = []
            continue
        if body is not None:
            body.append(line)
    if body is None:
        return None
    section = "\n".join(body).strip()
    return section + "\n" if section else None


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def _version_at(root: Path, ref: str) -> str | None:
    try:
        return json.loads(_git(root, "show", f"{ref}:{CLAUDE_PLUGIN_JSON}")).get("version")
    except subprocess.CalledProcessError:
        return None


def release_errors(root: Path, tag: str) -> list[str]:
    hook_manifest = root / HOOK_PLUGIN_JSON
    errors = check(
        tag,
        _load(root / MARKETPLACE_JSON),
        _load(root / CLAUDE_PLUGIN_JSON),
        _load(root / CODEX_PLUGIN_JSON),
        _load(hook_manifest) if hook_manifest.exists() else None,
    )
    changelog = root / CHANGELOG
    text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    if changelog_section(text, tag) is None:
        errors.append(f"{CHANGELOG}: no non-empty '## {tag}' section for the release notes")
    return errors


def pr_errors(root: Path, base: str, head: str) -> list[str]:
    changed = [f for f in _git(root, "diff", "--name-only", f"{base}...{head}").splitlines() if f]
    return requires_version_bump(changed, _version_at(root, base), _version_at(root, head))


def main(argv: list[str] | None = None, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description="Version gates for the k2 plugin.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tag", help="Release mode: the pushed tag, e.g. v0.3.0")
    mode.add_argument("--base", help="PR mode: the base ref, e.g. origin/develop")
    mode.add_argument("--notes", metavar="TAG", help="Print the CHANGELOG section for TAG")
    parser.add_argument("--head", default="HEAD", help="PR mode: the head ref (default HEAD)")
    args = parser.parse_args(argv)

    if args.notes:
        changelog = root / CHANGELOG
        text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
        section = changelog_section(text, args.notes)
        if section is None:
            print(f"FAIL: {CHANGELOG} has no non-empty '## {args.notes}' section", file=sys.stderr)
            return 1
        sys.stdout.write(section)
        return 0

    if args.tag:
        errors = release_errors(root, args.tag)
        ok = f"OK: tag {args.tag} matches every manifest version and has a changelog entry."
    else:
        errors = pr_errors(root, args.base, args.head)
        ok = "OK: no plugin content change without a version increase."

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
