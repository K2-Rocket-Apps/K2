#!/usr/bin/env python3
"""Friction hook: PostToolUse and PostToolUseFailure on test-runner Bash
commands (async; the runners are listed in hooks.json).

Both the tool output and the file hint are redacted on this machine before
anything leaves it. The file hint falls back to the raw Bash command, so it is
as much a secret-leak surface as the output. Redaction always runs on the full
raw text first and truncation second; truncating first could cut a secret
mid-pattern before any rule saw it. Always exits 0.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import hook_common  # noqa: E402


def main() -> int:
    try:
        if hook_common.is_cloud_session():
            return 0

        event = hook_common.read_stdin_event()
        cwd = str(event.get("cwd") or "")
        tool_input = event.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        # Claude Code names the field tool_response; tool_output and error are accepted too.
        tool_output = event.get("tool_output") or event.get("tool_response") or event.get("error") or ""
        tool_name = event.get("tool_name", "Bash")

        repo = hook_common.derive_repo(cwd)
        if not repo:
            return 0

        raw_file_hint = tool_input.get("file_path") or str(tool_input.get("command", "")) or "unknown"
        file_hint = hook_common.truncate(
            hook_common.redact(str(raw_file_hint)), max_lines=1, max_chars=hook_common.MAX_FILE_HINT_CHARS
        )
        description = hook_common.redact_and_truncate(str(tool_output))

        hook_common.send("friction", {
            "repo": repo, "file": file_hint, "description": description, "originating_tool": tool_name,
        })
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
