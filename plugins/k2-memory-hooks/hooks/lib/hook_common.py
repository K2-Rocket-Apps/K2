"""Shared helpers for the k2-memory-hooks command hooks.

Standard library only, so nothing needs to be installed on the machine.

This module never reads a credential, never knows a server address and never
opens a network connection. Its one side effect is `send()`, which hands a
small JSON payload to the locally installed `k2-agent` CLI
(`k2-agent telemetry send <kind>`). k2-agent uses the sign-in you already
completed with it, and your organization's gateway refuses the payload unless
an org admin has accepted the data processing terms and you have consented.

Every function here must leave the calling hook able to exit 0: a hook that
fails visibly would interrupt the coding session it is only observing.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import socket
import subprocess
import sys

MAX_DESCRIPTION_LINES = 100
MAX_DESCRIPTION_CHARS = 4000  # the server-side cap on a friction description
MAX_FILE_HINT_CHARS = 512  # the server-side cap on a friction `file` field

SEND_TIMEOUT = 6  # seconds; the hooks are async, so this never blocks the session
AGENT_COMMAND = ("k2-agent", "telemetry", "send")

_TRUTHY = {"1", "true", "yes", "on"}


def is_cloud_session() -> bool:
    """True inside a Claude Code cloud session (CLAUDE_CODE_REMOTE truthy).

    Cloud sessions have no local k2-agent sign-in and restricted egress, so
    every hook returns immediately there without doing anything.
    """
    return os.environ.get("CLAUDE_CODE_REMOTE", "").strip().lower() in _TRUTHY


def read_stdin_event() -> dict:
    """The Claude Code hook-event JSON from stdin, parsed defensively.

    A malformed or empty body yields {} rather than an exception, since a
    hook script must always exit 0.
    """
    try:
        raw = sys.stdin.read()
        parsed = json.loads(raw) if raw.strip() else {}
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def derive_repo(cwd: str) -> str | None:
    """repo := basename(cwd).

    Known limitation: a checkout whose directory name differs from the
    repository name (for example a git worktree) reports the directory name.
    """
    if not cwd:
        return None
    name = os.path.basename(cwd.rstrip("/"))
    return name or None


def derive_branch(cwd: str) -> str | None:
    """The checked-out git branch name, or None on a detached HEAD.

    Callers skip the heartbeat entirely on None rather than send an empty
    branch.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    branch = result.stdout.strip()
    return branch or None


def derive_agent_id(cwd: str) -> str:
    """Best-effort stable identity: the repository's configured git
    user.email, else user@hostname. Read-only: it never writes git config."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "config", "--get", "user.email"],
            capture_output=True, text=True, timeout=2,
        )
        email = result.stdout.strip()
        if email:
            return email
    except (OSError, subprocess.TimeoutExpired):
        pass

    return f"{getpass.getuser()}@{socket.gethostname()}"


# --------------------------------------------------------------------------
# Redaction
#
# Philosophy: a missed secret is worse than over-redaction. Detection is by
# shape and length, never by letter case: case-based rules have repeatedly
# let real single-case secrets (hex keys, all-caps tokens, base32, numeric
# PINs) through. Only three provably non-secret shapes are excluded.
# --------------------------------------------------------------------------

# A git SHA-1 / SHA-256 object id. Pinned to the two real lengths, so a 32-char
# lowercase-hex secret is still redacted. Accepted residual: a real secret that
# is exactly 40 or 64 lowercase-hex characters is left alone.
_GIT_SHA_SHAPE_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
# A canonical (lowercase) UUID. Deliberately case-sensitive: a mixed-case
# UUID-shaped value is treated as a possible secret.
_UUID_SHAPE_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# A kebab-case path or package segment.
_KEBAB_CASE_SHAPE_RE = re.compile(r"[a-z]+(?:-[a-z]+)+")


def _looks_like_secret(token: str) -> bool:
    """A long opaque run of identifier characters, other than the three
    excluded non-secret shapes above."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]{32,}", token):
        return False
    if _GIT_SHA_SHAPE_RE.fullmatch(token):
        return False
    if _UUID_SHAPE_RE.fullmatch(token):
        return False
    if _KEBAB_CASE_SHAPE_RE.fullmatch(token):
        return False
    return True


def _redact_generic_tokens(text: str) -> str:
    return re.sub(
        r"[A-Za-z0-9_\-]{32,}",
        lambda m: "***" if _looks_like_secret(m.group(0)) else m.group(0),
        text,
    )


def _looks_like_aws_secret(token: str) -> bool:
    """A {32,} run from the base64-ish alphabet (A-Za-z0-9/+), as used by AWS
    secret access keys, Basic-Auth tokens and generic base64 API keys.

    Only a git object id is excluded. UUIDs and kebab-case segments need no
    exclusion here: '-' is not in this character class, so they never form a
    single matching run. There is deliberately no letter-case requirement (see
    the module note above). Accepted cost: a long single-case identifier that
    uses '/' as a separator is also redacted; a short one (under 32 chars) is
    never affected.
    """
    if not re.fullmatch(r"[A-Za-z0-9/+]{32,}", token):
        return False
    return not _GIT_SHA_SHAPE_RE.fullmatch(token)


def _redact_aws_secret_keys(text: str) -> str:
    # Matches the maximal contiguous base64-alphabet run, not a fixed-width
    # window: a fixed width would match nothing at all when a secret sits inside
    # a longer run with no separator.
    return re.sub(
        r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{32,}(?![A-Za-z0-9/+])",
        lambda m: "***" if _looks_like_aws_secret(m.group(0)) else m.group(0),
        text,
    )


_SECRET_PATTERNS = [
    (re.compile(r"(https?://)[^/@\s:]+:[^/@\s]+@", re.I), r"\1***:***@"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "***"),
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----", re.S),
     "-----BEGIN PRIVATE KEY----- *** -----END PRIVATE KEY-----"),
    (re.compile(r"(Authorization[:=]\s*)(Bearer|Basic|token)\s+\S+", re.I), r"\1\2 ***"),
    # AWS access key IDs: long-lived (AKIA), temporary STS (ASIA) and the other
    # four prefixes that share the same 20-character shape.
    (re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AGPA|ANPA)[0-9A-Z]{16}\b"), "***"),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    text = _redact_aws_secret_keys(text)
    return _redact_generic_tokens(text)


def truncate(text: str, max_lines: int = MAX_DESCRIPTION_LINES, max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    lines = text.splitlines()
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... [truncated, {omitted} more lines]"]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "... [truncated]"
    return text


def redact_and_truncate(text: str) -> str:
    """Redact the full text first, then truncate. Truncating first could cut a
    secret mid-pattern before any rule saw the whole of it."""
    return truncate(redact(text))


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def send(kind: str, payload: dict) -> None:
    """Hand `payload` to `k2-agent telemetry send <kind>` on stdin.

    Returns immediately in a cloud session. Swallows every exception: k2-agent
    not installed (FileNotFoundError), a timeout, a non-serializable payload,
    or anything else. Its output is captured and discarded, so nothing reaches
    the session.
    """
    if is_cloud_session():
        return
    try:
        subprocess.run(
            [*AGENT_COMMAND, kind],
            input=json.dumps(payload),
            timeout=SEND_TIMEOUT,
            capture_output=True,
            text=True,
        )
    except Exception:
        pass
