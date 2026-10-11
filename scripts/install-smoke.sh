#!/usr/bin/env bash
# install-smoke.sh: prove that the k2 marketplace installs anonymously on a
# clean machine, with no GitHub CLI and no credential of any kind.
#
# Usage:
#   scripts/install-smoke.sh <marketplace-source>
#
# <marketplace-source> is what a user would type after
# `claude plugin marketplace add`: `K2-Rocket-Apps/k2`, `K2-Rocket-Apps/k2#v0.4.0`,
# or a local path. For Codex, a `#<ref>` suffix is passed as `--ref <ref>`.
#
# What it checks (any failure exits non-zero):
#   1. `gh` is not on PATH and no GitHub token is in the environment.
#   2. Claude Code: the marketplace adds, `k2@k2` installs at user scope and is
#      listed as enabled, and the opt-in `k2-memory-hooks` plugin is neither
#      installed nor enabled.
#   3. Codex: the marketplace adds, `k2@k2` installs, `codex mcp list --json`
#      prints exactly `[]`, the installed plugin carries exactly the skill
#      folders on the curated allow-list (ALLOWED_SKILLS in
#      tests/test_curated_skills.py, read from the source the CLI just cloned),
#      and `k2-memory-hooks` was not installed.
#   4. Neither installer wrote a user-level git config file.
#   5. When the source is pinned to a release tag (`#vX.Y.Z`), both the Claude
#      plugin list and the Codex cache report plugin version X.Y.Z, so a CLI
#      that silently ignored the ref would fail here.
#
# Isolation: HOME, CLAUDE_CONFIG_DIR and CODEX_HOME all point at fresh
# temporary directories, and git's user-level config is redirected into that
# throwaway HOME through GIT_CONFIG_GLOBAL (system config is ignored through
# GIT_CONFIG_NOSYSTEM). This script never edits any git config itself; it only
# checks that the installers did not either. Nothing outside the temporary
# directories is touched, and they are removed on exit unless
# K2_SMOKE_KEEP=1.
#
# Env:
#   K2_SMOKE_TIMEOUT  per-CLI-call timeout in seconds (default 300).
#   K2_SMOKE_KEEP     set to 1 to keep the temporary directories for debugging.
set -euo pipefail

say() { printf 'install-smoke: %s\n' "$*"; }
fail() {
  printf 'install-smoke: FAIL: %s\n' "$*" >&2
  exit 1
}

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  printf 'usage: %s <marketplace-source>\n' "$0" >&2
  exit 2
fi
SOURCE="$1"

# A source pinned to a release tag (`...#vX.Y.Z`) must install version X.Y.Z.
EXPECTED_VERSION=""
case "$SOURCE" in
  *'#'*)
    if [[ "${SOURCE#*#}" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
      EXPECTED_VERSION="${BASH_REMATCH[1]}"
    fi
    ;;
esac

# --- Clean-machine environment -------------------------------------------
SMOKE_HOME="$(mktemp -d)"
SMOKE_CODEX_HOME="$(mktemp -d)"
cleanup() {
  if [ "${K2_SMOKE_KEEP:-0}" = "1" ]; then
    printf 'install-smoke: kept HOME=%s CODEX_HOME=%s\n' "$SMOKE_HOME" "$SMOKE_CODEX_HOME" >&2
  else
    rm -rf "$SMOKE_HOME" "$SMOKE_CODEX_HOME"
  fi
}
trap cleanup EXIT

export GIT_TERMINAL_PROMPT=0 HOME="$SMOKE_HOME" CODEX_HOME="$SMOKE_CODEX_HOME"
export GIT_CONFIG_GLOBAL="$HOME/.gitconfig" GIT_CONFIG_NOSYSTEM=1
export CLAUDE_CONFIG_DIR="$HOME/.claude"
export XDG_CONFIG_HOME="$HOME/.config"
unset GH_TOKEN GITHUB_TOKEN GH_ENTERPRISE_TOKEN GITHUB_ENTERPRISE_TOKEN
# Drop git config injected through the environment, so the installers see
# what a fresh machine would.
unset GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS

say "source: $SOURCE"
say "HOME=$HOME CODEX_HOME=$CODEX_HOME"

# --- No GitHub CLI --------------------------------------------------------
if command -v gh >/dev/null 2>&1; then
  fail "the GitHub CLI is on PATH ($(command -v gh)); this check must run without gh"
fi
say "gh absent: OK (command -v gh found nothing)"

for tool in claude codex git node; do
  command -v "$tool" >/dev/null 2>&1 || fail "'$tool' is not on PATH"
done
say "claude $(claude --version 2>/dev/null | head -n 1)"
say "codex $(codex --version 2>/dev/null | head -n 1)"
say "git $(git --version | head -n 1)"

# --- User-level git config snapshot (expected: absent) --------------------
git_config_state() {
  local out=""
  for f in "$GIT_CONFIG_GLOBAL" "$XDG_CONFIG_HOME/git/config"; do
    if [ -e "$f" ]; then
      out="$out $(sha256sum "$f" 2>/dev/null || echo "unreadable $f")"
    fi
  done
  printf '%s' "${out:-absent}"
}
GIT_CONFIG_BEFORE="$(git_config_state)"
[ "$GIT_CONFIG_BEFORE" = "absent" ] || fail "user-level git config exists before install: $GIT_CONFIG_BEFORE"
say "user-level git config before install: absent"

run() {
  # The command echo goes to stderr so captured stdout stays parseable.
  printf 'install-smoke: $ %s\n' "$*" >&2
  if command -v timeout >/dev/null 2>&1; then
    timeout "${K2_SMOKE_TIMEOUT:-300}" "$@"
  else
    "$@"
  fi
}

# --- Claude Code ----------------------------------------------------------
run claude plugin marketplace add "$SOURCE" || fail "claude plugin marketplace add failed"
run claude plugin install k2@k2 --scope user || fail "claude plugin install k2@k2 failed"
run claude plugin list || fail "claude plugin list failed"
CLAUDE_LIST_JSON="$(run claude plugin list --json)" || fail "claude plugin list --json failed"

CLAUDE_LIST_JSON="$CLAUDE_LIST_JSON" node -e '
  const list = JSON.parse(process.env.CLAUDE_LIST_JSON);
  if (!Array.isArray(list)) { console.error("plugin list is not an array"); process.exit(1); }
  const k2 = list.find((p) => p.id === "k2@k2");
  if (!k2 || k2.enabled !== true) { console.error("k2@k2 is not listed as enabled"); process.exit(1); }
  const hooks = list.filter((p) => String(p.id).startsWith("k2-memory-hooks@"));
  if (hooks.length) { console.error("k2-memory-hooks is installed: " + JSON.stringify(hooks)); process.exit(1); }
' || fail "claude plugin list does not show exactly k2@k2 enabled without k2-memory-hooks"
say "claude: k2@k2 listed and enabled: OK"

if [ -n "$EXPECTED_VERSION" ]; then
  CLAUDE_LIST_JSON="$CLAUDE_LIST_JSON" EXPECTED_VERSION="$EXPECTED_VERSION" node -e '
    const k2 = JSON.parse(process.env.CLAUDE_LIST_JSON).find((p) => p.id === "k2@k2");
    if (k2.version !== process.env.EXPECTED_VERSION) {
      console.error("k2@k2 version is " + JSON.stringify(k2.version) + ", expected " + process.env.EXPECTED_VERSION);
      process.exit(1);
    }
  ' || fail "claude installed the wrong k2 version for $SOURCE"
  say "claude: k2@k2 version $EXPECTED_VERSION matches the pinned tag: OK"
fi

node -e '
  const fs = require("fs");
  const path = process.env.CLAUDE_CONFIG_DIR + "/settings.json";
  const enabled = JSON.parse(fs.readFileSync(path, "utf8")).enabledPlugins || {};
  const keys = Object.keys(enabled);
  if (keys.length !== 1 || keys[0] !== "k2@k2" || enabled["k2@k2"] !== true) {
    console.error("enabledPlugins is " + JSON.stringify(enabled) + ", expected exactly {\"k2@k2\": true}");
    process.exit(1);
  }
' || fail "claude settings enable something other than k2@k2"
[ ! -e "$CLAUDE_CONFIG_DIR/plugins/cache/k2/k2-memory-hooks" ] || fail "claude cached k2-memory-hooks"
say "claude: k2-memory-hooks not installed or enabled: OK"

# --- Codex ----------------------------------------------------------------
case "$SOURCE" in
  *'#'*) CODEX_ARGS=("${SOURCE%%#*}" --ref "${SOURCE#*#}") ;;
  *) CODEX_ARGS=("$SOURCE") ;;
esac
run codex plugin marketplace add "${CODEX_ARGS[@]}" || fail "codex plugin marketplace add failed"
run codex plugin add k2@k2 || fail "codex plugin add k2@k2 failed"

MCP_JSON="$(run codex mcp list --json)" || fail "codex mcp list --json failed"
say "codex mcp list --json: $MCP_JSON"
[ "$(printf '%s' "$MCP_JSON" | tr -d '[:space:]')" = "[]" ] || fail "codex mcp list --json is not exactly []"
say "codex: no MCP server: OK"

CODEX_CACHE="$CODEX_HOME/plugins/cache/k2"
[ ! -e "$CODEX_CACHE/k2-memory-hooks" ] || fail "codex cached k2-memory-hooks"
say "codex: k2-memory-hooks not installed: OK"

shopt -s nullglob
versions=("$CODEX_CACHE/k2/"*/)
shopt -u nullglob
[ "${#versions[@]}" -eq 1 ] || fail "expected one cached k2 version under $CODEX_CACHE/k2, found ${#versions[@]}"
if [ -n "$EXPECTED_VERSION" ]; then
  CACHED_VERSION="$(basename "${versions[0]%/}")"
  [ "$CACHED_VERSION" = "$EXPECTED_VERSION" ] \
    || fail "codex cached k2 version $CACHED_VERSION, expected $EXPECTED_VERSION for $SOURCE"
  say "codex: cached k2 version $EXPECTED_VERSION matches the pinned tag: OK"
fi
SKILLS_DIR="${versions[0]%/}/skills"
[ -d "$SKILLS_DIR" ] || fail "no skills directory at $SKILLS_DIR"

# The allow-list is read from the marketplace the Claude CLI cloned for this
# same source, so a pinned run is checked against that tag's own list.
ALLOW_FILE="$CLAUDE_CONFIG_DIR/plugins/marketplaces/k2/tests/test_curated_skills.py"
[ -f "$ALLOW_FILE" ] || fail "allow-list file not found at $ALLOW_FILE"
EXPECTED="$(awk '
  /^ALLOWED_SKILLS = frozenset\(/ { on = 1; next }
  on && /^\)/ { exit }
  on { while (match($0, /"[a-z0-9-]+"/)) { print substr($0, RSTART + 1, RLENGTH - 2); $0 = substr($0, RSTART + RLENGTH) } }
' "$ALLOW_FILE" | LC_ALL=C sort)"
[ -n "$EXPECTED" ] || fail "could not read ALLOWED_SKILLS from $ALLOW_FILE"
ACTUAL="$(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | LC_ALL=C sort)"
say "allow-listed skills: $(printf '%s' "$EXPECTED" | tr '\n' ' ')"
say "codex cached skills: $(printf '%s' "$ACTUAL" | tr '\n' ' ')"
[ "$EXPECTED" = "$ACTUAL" ] || fail "codex skill folders differ from the allow-list"
say "codex: skill folders match the allow-list: OK"

# --- Git config untouched -------------------------------------------------
GIT_CONFIG_AFTER="$(git_config_state)"
[ "$GIT_CONFIG_AFTER" = "absent" ] || fail "an installer wrote user-level git config: $GIT_CONFIG_AFTER"
say "user-level git config after install: absent: OK"

say "PASS: $SOURCE"
