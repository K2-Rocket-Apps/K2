#!/usr/bin/env bash
# validate-server-json.sh: prove that server.json (this repository's listing on
# the official MCP Registry) is safe to publish before `mcp-publisher publish`
# ever runs.
#
# Usage:
#   scripts/validate-server-json.sh [--allow-pending-bump] [repo-root]
#
# <repo-root> defaults to the repository root and must be a git checkout with
# its tags fetched. The tests point it at a throwaway git repository holding
# one fixture from tests/fixtures/server-json/, to prove each rule fires.
#
# Rules (every failure is reported; any failure exits non-zero):
#   1. `$schema` is exactly the pinned 2025-12-11 schema URL, and the file
#      validates against that schema with ajv-cli 5.0.0 (draft-07, with
#      ajv-formats for `uri`). The schema is downloaded at run time and its
#      SHA-256 must equal SCHEMA_SHA256 below, so an upstream edit to the
#      published schema fails closed instead of silently changing the rules.
#   2. `description` is at most 100 characters.
#   3. No remote declares `headers`: the gateway is OAuth-only, so a client
#      never needs a header (and never a secret) to connect.
#   4. No remote variable carries a `default` or a `value`, and none is a
#      secret: a default `org_slug` would publish one organization's tenant
#      host to every registry user. `org_slug` itself must be declared and
#      required.
#   5. `version` equals the latest `v[0-9]*` release tag without its `v`. The
#      latest tag is `git describe --tags --match 'v[0-9]*' --abbrev=0`; when
#      no such tag is reachable from HEAD (release tags sit on main's release
#      merges, which a develop-based branch does not contain), it is the
#      highest strict `vX.Y.Z` tag in the repository. `--match 'v[0-9]*'`
#      never matches an `agent-v*` tag, so those never affect this rule. No
#      release tag at all fails closed.
#      With --allow-pending-bump (pull requests only), a version above the
#      latest tag is also accepted when it equals the k2 plugin manifest
#      version: that is a release-bump pull request, and the tag gate in
#      tests/version_consistency.py holds the eventual tag to the same value.
#   6. When the k2 plugin manifest exists, `version` equals its version.
#
# Needs: python3, git, curl and npx (Node.js). Writes nothing outside a
# temporary directory that is removed on exit.
set -euo pipefail

SCHEMA_URL="https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
SCHEMA_SHA256="3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0"
AJV_CLI="ajv-cli@5.0.0"
AJV_FORMATS="ajv-formats@3.0.1"

fail() {
  printf 'validate-server-json: FAIL: %s\n' "$*" >&2
  exit 1
}

ALLOW_PENDING_BUMP=0
if [ "${1:-}" = "--allow-pending-bump" ]; then
  ALLOW_PENDING_BUMP=1
  shift
fi
if [ "$#" -gt 1 ]; then
  printf 'usage: %s [--allow-pending-bump] [repo-root]\n' "$0" >&2
  exit 2
fi

ROOT="$(cd "${1:-$(dirname "${BASH_SOURCE[0]}")/..}" && pwd)"
[ -f "$ROOT/server.json" ] || fail "no server.json in $ROOT"
for tool in python3 git curl npx; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is not on PATH"
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The latest release tag (rule 5). Never a bare `v*` and never `agent-v*`.
LATEST_TAG="$(git -C "$ROOT" describe --tags --match 'v[0-9]*' --abbrev=0 HEAD 2>/dev/null || true)"
if [ -z "$LATEST_TAG" ]; then
  LATEST_TAG="$(git -C "$ROOT" tag --list 'v[0-9]*' \
    | grep -E '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' \
    | sort -V | tail -n 1 || true)"
fi

ERRORS=0

python3 - "$ROOT" "$SCHEMA_URL" "$LATEST_TAG" "$ALLOW_PENDING_BUMP" <<'PY' || ERRORS=1
import json
import re
import sys
from pathlib import Path

root, schema_url, latest_tag, allow_pending = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == "1"
errors = []

try:
    doc = json.loads((root / "server.json").read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    sys.exit(f"validate-server-json: FAIL: server.json is not valid JSON: {exc}")
if not isinstance(doc, dict):
    sys.exit("validate-server-json: FAIL: server.json must be a JSON object")

# Rule 1 (the pinned schema URL; ajv runs after this script).
if doc.get("$schema") != schema_url:
    errors.append(f"$schema must be exactly {schema_url}, got {doc.get('$schema')!r}")

# Rule 2.
description = doc.get("description")
if not isinstance(description, str) or not description:
    errors.append("description is required")
elif len(description) > 100:
    errors.append(f"description is {len(description)} characters; the registry allows at most 100")

# Rules 3-4.
remotes = doc.get("remotes")
if not isinstance(remotes, list) or not remotes:
    errors.append("remotes must be a non-empty list")
    remotes = []
for i, remote in enumerate(remotes):
    if not isinstance(remote, dict):
        errors.append(f"remotes[{i}] must be an object")
        continue
    if "headers" in remote:
        errors.append(f"remotes[{i}] declares headers; the gateway is OAuth-only and needs none")
    variables = remote.get("variables") or {}
    if not isinstance(variables, dict):
        errors.append(f"remotes[{i}].variables must be an object")
        continue
    for name, var in variables.items():
        if not isinstance(var, dict):
            errors.append(f"remotes[{i}].variables.{name} must be an object")
            continue
        for key in ("default", "value"):
            if key in var:
                errors.append(f"remotes[{i}].variables.{name} has a {key!r}; no tenant may be published")
        if var.get("isSecret"):
            errors.append(f"remotes[{i}].variables.{name} is a secret input; none is allowed")
    url = remote.get("url", "")
    if "{org_slug}" in str(url):
        org = variables.get("org_slug")
        if not isinstance(org, dict) or org.get("isRequired") is not True:
            errors.append(f"remotes[{i}].variables.org_slug must be declared with isRequired: true")
    for placeholder in re.findall(r"\{([^{}]+)\}", str(url)):
        if placeholder not in variables:
            errors.append(f"remotes[{i}].url uses {{{placeholder}}} but declares no such variable")

# Rules 5-6.
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse(v):
    m = SEMVER.match(v) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


version = doc.get("version")
manifest_path = root / "plugins" / "k2" / ".claude-plugin" / "plugin.json"
manifest_version = None
if manifest_path.exists():
    try:
        manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version")
    except json.JSONDecodeError as exc:
        errors.append(f"{manifest_path.relative_to(root)}: invalid JSON: {exc}")

if parse(version) is None:
    errors.append(f"version {version!r} is not strict semver X.Y.Z")
elif not latest_tag:
    errors.append("no v[0-9]* release tag found (fetch tags: fetch-depth 0); cannot check the version")
else:
    expected = latest_tag[1:]
    if version != expected:
        pending = (
            allow_pending
            and manifest_version == version
            and parse(expected) is not None
            and parse(version) > parse(expected)
        )
        if not pending:
            errors.append(f"version {version!r} does not match the latest release tag {latest_tag!r}")

if manifest_version is not None and version != manifest_version:
    errors.append(f"version {version!r} differs from the k2 plugin manifest version {manifest_version!r}")

for error in errors:
    print(f"validate-server-json: FAIL: {error}", file=sys.stderr)
sys.exit(1 if errors else 0)
PY

# Rule 1: the pinned schema, verified by hash, then ajv.
if curl -fsSL --retry 3 -o "$WORK/server.schema.json" "$SCHEMA_URL"; then
  got="$(sha256sum "$WORK/server.schema.json" | cut -d' ' -f1)"
  if [ "$got" != "$SCHEMA_SHA256" ]; then
    printf 'validate-server-json: FAIL: %s has sha256 %s, expected the pinned %s\n' "$SCHEMA_URL" "$got" "$SCHEMA_SHA256" >&2
    ERRORS=1
  else
    cp "$ROOT/server.json" "$WORK/server.json"
    # Run from the temporary directory so npx never reads this repo's package.json.
    if ! (cd "$WORK" && npx --yes -p "$AJV_CLI" -p "$AJV_FORMATS" ajv validate \
          --spec=draft7 --strict=false -c ajv-formats \
          -s server.schema.json -d server.json >ajv.log 2>&1); then
      grep -v '^npm warn' "$WORK/ajv.log" >&2 || true
      printf 'validate-server-json: FAIL: server.json does not validate against %s\n' "$SCHEMA_URL" >&2
      ERRORS=1
    fi
  fi
else
  printf 'validate-server-json: FAIL: could not download %s\n' "$SCHEMA_URL" >&2
  ERRORS=1
fi

[ "$ERRORS" -eq 0 ] || exit 1
printf 'validate-server-json: OK: schema-valid, description <= 100, no headers, no tenant default, version %s (latest release tag %s).\n' \
  "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/server.json")" "${LATEST_TAG:-?}"
