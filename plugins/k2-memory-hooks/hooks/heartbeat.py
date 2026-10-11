#!/usr/bin/env python3
"""Heartbeat hook: Stop, SubagentStop and `git push` (async).

Reads the hook event from stdin, derives repo, branch and agent_id from the
event's cwd, and hands {repo, branch, agent_id} to k2-agent. A missing cwd or
a detached HEAD is a silent no-op. Always exits 0.
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

        repo = hook_common.derive_repo(cwd)
        branch = hook_common.derive_branch(cwd) if repo else None
        if not repo or not branch:
            return 0

        agent_id = hook_common.derive_agent_id(cwd)
        hook_common.send("heartbeat", {"repo": repo, "branch": branch, "agent_id": agent_id})
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
