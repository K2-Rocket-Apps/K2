# k2-memory-hooks

Optional Claude Code hooks that send two small signals from your coding sessions to your
organization's K2 Memory: a **heartbeat** when a session stops or you push, and a **friction**
note when a test run fails.

## Opt-in only

This plugin is **not** part of the `k2` plugin. Installing `k2`, or running the `k2-connect`
skill, never installs or enables it. You get these hooks only if you install this plugin yourself:

```sh
claude plugin install k2-memory-hooks@k2 --scope user
```

It is a Claude Code plugin only. It ships no Codex manifest and no MCP server.

## What it sends

Each hook hands a small JSON payload to the `k2-agent` CLI already on your machine
(`k2-agent telemetry send heartbeat|friction`). k2-agent sends it through your organization's
K2 gateway using the sign-in you already completed with `k2-agent connect`. This plugin itself
reads no credential, holds no server address, opens no network connection, starts nothing in the
background and changes no git settings. In a Claude Code cloud session it does nothing at all.

The data falls into three classes, which is what you consent to:

| Data class | Hook | Fields |
|---|---|---|
| Git identity | heartbeat | `repo` (the directory name), `branch`, `agent_id` (the repository's git `user.email`, else `user@hostname`) |
| Redacted test output | friction | `description`: the failed test run's output, with secrets redacted on your machine and then cut to 100 lines / 4000 characters |
| Friction signals | friction | `repo`, `file` (the file path, or the redacted test command cut to 512 characters) and `originating_tool` |

Redaction runs on your machine before anything leaves it. It removes URL credentials, GitHub
tokens, private key blocks, `Authorization` header values, AWS access key IDs and secret keys,
and any other long opaque token, replacing each with `***`.

The heartbeat is skipped on a detached HEAD. Friction is captured only for these test runners:
`vendor/bin/pest`, `php artisan test`, `npm test`, `npm run test`, `pytest` and `python -m pytest`.

If `k2-agent` is not installed, is not signed in, or does not answer within a few seconds, the
hook gives up silently. A hook never interrupts your session and always exits successfully.

## Consent

Nothing is accepted until **both**:

1. an admin of your organization accepts the data processing agreement (DPA) for these data
   classes, and
2. you consent yourself, on the consent screen at `/settings/memory-hooks` on your organization's
   K2 gateway host.

Until then the gateway refuses every payload, so installing the plugin alone sends nothing that is
kept. Consenting is also what lets these two hook calls run without a browser approval prompt for
each call; every other action through your gateway keeps its normal approval rules.

## Uninstall

```sh
claude plugin uninstall k2-memory-hooks
```
