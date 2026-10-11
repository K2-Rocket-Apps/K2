# Changelog

Every release of the `k2` plugin is published from an immutable `v*` tag. Each
section below is used verbatim as that tag's GitHub Release notes.

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
