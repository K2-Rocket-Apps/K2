#!/usr/bin/env bash
# validate-npm-package.sh: prove that the npm mirror of this marketplace is
# safe to publish before `npm publish` ever runs.
#
# Usage:
#   scripts/validate-npm-package.sh [package-root]
#
# <package-root> defaults to the repository root. The tests point it at a
# throwaway copy with one forbidden change applied, to prove each rule fires.
#
# The package is a byte-for-byte mirror of the git marketplace root, so that
# an npm install and a git install of the same tag are identical. Rules (any
# failure exits non-zero):
#   1. package.json declares no lifecycle script that npm runs on install,
#      pack or publish (preinstall, install, postinstall, prepare, prepack,
#      ...), no dependency of any kind, no `bin`, no native build (`gypfile`),
#      and is not `private`. Nothing may run on a customer machine at install
#      time. This is checked BEFORE packing, and the pack below passes
#      --ignore-scripts as well, so a bad fixture never gets to run anything.
#   2. `repository.url` points at the public repository (npm provenance
#      requires it) and `license` matches the plugin manifests.
#   3. `npm pack --dry-run --json` lists only allow-listed paths:
#      package.json, LICENSE, README.md, .claude-plugin/** and the trees of
#      the plugins the marketplace lists. The marketplace may list only the
#      plugins pinned in ALLOWED_PLUGINS below (adding one to the npm mirror
#      is a deliberate edit here), the k2 plugin must be present, and every
#      plugin the packed marketplace.json lists must be packed too.
#   3a. No packed path is build or cache output (`__pycache__/`, `*.pyc`,
#      `*.pyo`, `.pytest_cache/`, `.DS_Store`), and, when <package-root> is a
#      git checkout, every packed path is tracked by git. Running the test
#      suite writes bytecode under plugins/, and npm does not apply
#      .gitignore to `files` entries, so this keeps the tarball equal to the
#      git tree of the tag.
#   4. No packed file contains a gateway token prefix (`mgw_` followed by an
#      alphanumeric).
#   5. No URL in a packed `.mcp.json`, `plugin.json` or `marketplace.json`
#      contains `${` (an unexpanded placeholder would reach users verbatim).
#
# Needs: npm and python3 (and git, for a git checkout). Makes no network call
# and writes nothing outside a temporary file that is removed on exit.
set -euo pipefail

fail() {
  printf 'validate-npm-package: FAIL: %s\n' "$*" >&2
  exit 1
}

if [ "$#" -gt 1 ]; then
  printf 'usage: %s [package-root]\n' "$0" >&2
  exit 2
fi

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
[ -f "$ROOT/package.json" ] || fail "no package.json in $ROOT"
command -v npm >/dev/null 2>&1 || fail "npm is not on PATH"
command -v python3 >/dev/null 2>&1 || fail "python3 is not on PATH"

LISTING="$(mktemp)"
trap 'rm -f "$LISTING"' EXIT

# Rules 1-2 run first, on package.json alone, so a lifecycle script is
# rejected before npm is asked to pack anything.
python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
errors = []
try:
    pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    sys.exit(f"validate-npm-package: FAIL: package.json is not valid JSON: {exc}")
if not isinstance(pkg, dict):
    sys.exit("validate-npm-package: FAIL: package.json must be a JSON object")

# Every script npm runs on its own during install, pack or publish. `prepare`
# also runs when a package is installed from git, and `prepublish` ran on
# install in older npm.
LIFECYCLE = {
    "preinstall", "install", "postinstall",
    "preprepare", "prepare", "postprepare",
    "prepack", "postpack",
    "prepublish", "prepublishOnly", "publish", "postpublish",
    "preuninstall", "uninstall", "postuninstall",
}
scripts = pkg.get("scripts") or {}
if not isinstance(scripts, dict):
    errors.append("package.json: 'scripts' must be an object")
    scripts = {}
for name in sorted(set(scripts) & LIFECYCLE):
    errors.append(f"package.json: lifecycle script {name!r} is not allowed (nothing may run at install time)")

for key in ("dependencies", "optionalDependencies", "peerDependencies", "bundleDependencies", "bundledDependencies"):
    if pkg.get(key):
        errors.append(f"package.json: {key!r} is not allowed (a dependency can run its own install scripts)")
for key in ("bin", "gypfile"):
    if key in pkg:
        errors.append(f"package.json: {key!r} is not allowed")
if pkg.get("private") is not None:
    errors.append("package.json: 'private' must not be set")

PUBLIC_REPO = "github.com/K2-Rocket-Apps/k2"
repo = pkg.get("repository")
url = repo.get("url") if isinstance(repo, dict) else repo
if not (isinstance(url, str) and url.rstrip("/").removesuffix(".git").endswith(PUBLIC_REPO)):
    errors.append(f"package.json: repository.url must point at https://{PUBLIC_REPO} (npm provenance requires it), got {url!r}")

manifest = root / "plugins" / "k2" / ".claude-plugin" / "plugin.json"
try:
    expected_license = json.loads(manifest.read_text(encoding="utf-8")).get("license")
except (OSError, json.JSONDecodeError):
    expected_license = None
if not expected_license or pkg.get("license") != expected_license:
    errors.append(f"package.json: license {pkg.get('license')!r} must match the k2 plugin manifest ({expected_license!r})")

for error in errors:
    print(f"validate-npm-package: FAIL: {error}", file=sys.stderr)
sys.exit(1 if errors else 0)
PY

(cd "$ROOT" && npm pack --dry-run --json --ignore-scripts >"$LISTING" 2>/dev/null) \
  || fail "npm pack --dry-run failed in $ROOT"

# Rules 3-5 run on exactly the file list npm would publish.
python3 - "$ROOT" "$LISTING" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
try:
    listing = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    packed = sorted(f["path"] for f in listing[0]["files"])
except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
    sys.exit(f"validate-npm-package: FAIL: could not read the npm pack listing: {exc}")

errors = []

ROOT_FILES = {"package.json", "LICENSE", "README.md"}
MARKETPLACE = ".claude-plugin/marketplace.json"

plugin_dirs = []
try:
    market = json.loads((root / MARKETPLACE).read_text(encoding="utf-8"))
    for entry in market.get("plugins", []):
        source = entry.get("source") if isinstance(entry, dict) else None
        if isinstance(source, str) and re.fullmatch(r"\./plugins/[a-z0-9][a-z0-9-]*", source):
            plugin_dirs.append(source[2:])
        else:
            errors.append(f"{MARKETPLACE}: plugin source {source!r} is not a ./plugins/<name> directory")
except (OSError, json.JSONDecodeError, AttributeError) as exc:
    errors.append(f"{MARKETPLACE}: unreadable: {exc}")

if "plugins/k2" not in plugin_dirs:
    errors.append(f"{MARKETPLACE}: must list the k2 plugin at ./plugins/k2")

# Publishing another plugin to npm must be a deliberate edit here, never a
# side effect of listing it in the marketplace.
ALLOWED_PLUGINS = {"plugins/k2", "plugins/k2-memory-hooks"}
for d in plugin_dirs:
    if d not in ALLOWED_PLUGINS:
        errors.append(f"{MARKETPLACE}: plugin ./{d} is not in the npm mirror's pinned plugin set ({', '.join(sorted(ALLOWED_PLUGINS))})")
plugin_dirs = [d for d in plugin_dirs if d in ALLOWED_PLUGINS]

allowed_prefixes = (".claude-plugin/",) + tuple(f"{d}/" for d in plugin_dirs)


def allowed(path: str) -> bool:
    return path in ROOT_FILES or path.startswith(allowed_prefixes)


for path in packed:
    if not allowed(path):
        errors.append(f"{path}: packed file is outside the allow-list (package.json, LICENSE, README.md, .claude-plugin/, {', '.join(d + '/' for d in plugin_dirs)})")
    if Path(path).name == "binding.gyp":
        errors.append(f"{path}: a native build file would run node-gyp at install time")
    parts = path.split("/")
    if (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or path.endswith((".pyc", ".pyo"))
        or parts[-1] == ".DS_Store"
    ):
        errors.append(f"{path}: build or cache output must never be packed (it is not in git)")

# In a git checkout, the tarball must be a subset of the tracked tree.
try:
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
except (OSError, subprocess.CalledProcessError):
    top = ""
in_git = bool(top) and Path(top).resolve() == root.resolve()
if in_git:
    tracked = set(
        subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, text=True, check=True,
        ).stdout.split("\0")
    )
    for path in packed:
        if path not in tracked:
            errors.append(f"{path}: packed but not tracked by git (an npm install must match a git install of the same tag)")

required = {"package.json", MARKETPLACE} | {f"{d}/.claude-plugin/plugin.json" for d in plugin_dirs}
required.add("plugins/k2/.codex-plugin/plugin.json")
for path in sorted(required - set(packed)):
    errors.append(f"{path}: missing from the package (an npm install must match a git install of the same tag)")

TOKEN_RE = re.compile(r"mgw_[A-Za-z0-9]")
JSON_URL_FILES = {".mcp.json", "plugin.json", "marketplace.json"}


def placeholder_urls(node, key=""):
    """Every string under a URL-ish key, or that looks like a URL, containing `${`."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from placeholder_urls(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from placeholder_urls(v, key)
    elif isinstance(node, str) and "${" in node and ("url" in key.lower() or "://" in node or key.lower() in {"homepage", "repository"}):
        yield f"{key or '<value>'} = {node!r}"


for path in packed:
    try:
        data = (root / path).read_bytes()
    except OSError as exc:
        errors.append(f"{path}: unreadable: {exc}")
        continue
    text = data.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        if TOKEN_RE.search(line):
            errors.append(f"{path}:{lineno}: contains a gateway token prefix")
    if Path(path).name in JSON_URL_FILES:
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue
        for hit in placeholder_urls(doc):
            errors.append(f"{path}: URL contains an unexpanded '${{' placeholder: {hit}")

for error in errors:
    print(f"validate-npm-package: FAIL: {error}", file=sys.stderr)
if errors:
    sys.exit(1)
git_note = " and git-tracked" if in_git else ""
print(f"validate-npm-package: OK: {len(packed)} files, all allow-listed{git_note}, no build output, no lifecycle scripts, no token prefix, no placeholder URL.")
PY
