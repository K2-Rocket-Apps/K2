# Changelog

Every release of the `k2` plugin is published from an immutable `v*` tag. Each
section below is used verbatim as that tag's GitHub Release notes.

## v0.4.0

Adds `k2-memory-hooks`, a separate, opt-in Claude Code plugin in this marketplace.

- `k2-memory-hooks` sends a heartbeat (repo, branch, agent id) when a session stops or pushes, and
  redacted test-failure friction for six common test runners. Both go through
  `k2-agent telemetry send`; the plugin holds no credential or server address and makes no network
  call of its own. Nothing is accepted until your organization's admin accepts the DPA and you
  consent. It does nothing in a Claude Code cloud session.
- The `k2` plugin is unchanged apart from its version: it still installs no hooks, does not depend on
  `k2-memory-hooks`, and its `k2-connect` skill never installs it.
- Public-package policy: the hooks ban stays on `k2`. `k2-memory-hooks` may ship only a single
  `hooks/hooks.json` whose every hook runs `heartbeat.py` or `friction.py`, and its version must
  match the marketplace version.

## v0.3.0

First tagged release of the `k2` plugin for Claude Code and Codex.

- Skills: `k2-connect` (connect this machine to your organization's K2 gateway
  or a self-hosted one), `mcp-step-up-approval`, `cross-repo-code-lookup` and
  `memory-orchestrate`.
- Ships skills only: no MCP server entry, no hooks, no commands and no
  background jobs. It changes no git settings and never handles a credential.
- Release assets: `k2-v0.3.0.tar.gz` (the tagged source) and `SHA256SUMS`, both
  with a GitHub artifact attestation. Verify with
  `gh attestation verify k2-v0.3.0.tar.gz --repo K2-Rocket-Apps/k2`.
