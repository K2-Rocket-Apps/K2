---
name: k2-connect
description: Use when connecting Claude Code or Codex on this machine to a K2 gateway (K2 SaaS organisation or a self-hosted gateway), or when K2 tools are missing because no gateway is configured.
---

# Connect to a K2 gateway

This skill connects Claude Code and Codex on **this machine** to a K2 gateway: either your
organisation on K2 SaaS or a gateway you host yourself. The `k2` plugin ships no MCP server of
its own, so until this is done no K2 tools appear.

All sign-in and credential storage is done by `k2-agent`, the K2 desktop agent, outside this
conversation. Your part is to collect a URL, check it, run the right command, and relay what the
agent prints. You never see, handle or store a credential.

## Hard rules

These apply at every step. If a step below seems to conflict with one of them, the rule wins.

- **Never ask for, accept, repeat or write** a password, a TOTP or one-time code, a recovery
  code, or a gateway access key (the value beginning `mgw_`). Sign-in happens in the user's
  browser through the device flow; the only things you relay are the verification URL and the
  short user code that `k2-agent` prints.
- **If the user puts an `mgw_` value into the chat**, do not use it, do not repeat it, and do not
  store it anywhere. Tell them it is now exposed and they should revoke it from their gateway's
  web UI, then continue with the steps below, which never need it.
- **Never write a credential into a client or shell file yourself.** That covers
  `~/.claude/settings.json`, `~/.claude.json`, `~/.codex/config.toml`, any shell profile or rc
  file, and any exported variable. `k2-agent` keeps its credentials in its own store and wires
  the clients itself, so nothing here needs a file edit from you.
- **Never change machine-wide git settings** (no global git config edits) as part of connecting.
- **Never pipe a downloaded script into a shell or into PowerShell.** Download it to a file, let
  the user read it, then run the file.
- **Never guess a URL.** If a check fails, report exactly what failed and stop.

## Step 1: collect the base URL

Ask the user for their gateway's base URL, then normalise it:

1. Require an explicit scheme. Do not add one yourself.
2. Strip trailing slashes, then strip a trailing `/mcp` if present (people often copy the full
   endpoint from the gateway's setup page), then strip trailing slashes again.
3. **Require `https://`.** The only exception is a gateway on this machine:
   `http://localhost` or `http://127.0.0.1` (any port) is accepted for a local self-hosted
   gateway. Refuse every other `http://` URL, for example `http://example.com`, and ask for the
   `https://` address instead. Also refuse a URL that carries a username, password, query string
   or fragment.

Call the result `<base>`. Echo `<base>/mcp` back to the user and ask them to confirm it is the
endpoint they expect before going on.

<!-- k2-central-host-guard:start -->
## Step 2: central-host guard

Until per-organisation routing on the central hosts (T1) is live in production, the bare central
host does not serve your organisation. Compare the lower-cased host of `<base>` with this table:

| Central host (refuse exactly this host) |
|---|
| `gateway.k2-tek.com` |
| `dev.mcp-gateway.k2-tek.com` |

If the host is **exactly** one of these, refuse and ask for your organisation's own address,
`https://<your-org>.<that host>` (for example `https://<your-org>.gateway.k2-tek.com`). One
sentence of reason is enough: "That address is the shared central host, which does not route to
your organisation yet; use your organisation's own subdomain." Accept any other host, including
subdomains of these hosts.
<!-- k2-central-host-guard:end -->

## Step 3: probe the gateway

Fetch the gateway's public bootstrap document, with no authentication:

```bash
curl -fsS -H 'Accept: application/json' '<base>/.well-known/k2-agent'
```

On Windows PowerShell: `Invoke-RestMethod '<base>/.well-known/k2-agent'`.

If the request fails, returns anything other than HTTP 200, or the body is not JSON, **stop** and
report what you saw (status code or error). Do not try another URL, path or scheme.

From the JSON, read:

- `enrollment_enabled`: whether this gateway lets the desktop agent sign in;
- `binaries_available`: whether this gateway can serve the `k2-agent` binary;
- `oauth_client_id`: the public sign-in client identifier (not a secret).

If both `enrollment_enabled` and `binaries_available` are `true`, go to Step 4. Otherwise go to
Step 5.

## Step 4: connect with k2-agent (preferred)

### 4a. The agent is installed and has `connect`

Check whether `k2-agent` is on the PATH and whether `k2-agent help` lists a `k2-agent connect`
command. If it does, run:

```bash
k2-agent connect --gateway '<base>'
```

`k2-agent connect` fetches the same bootstrap document, signs in with the device flow, enrols
this device, configures every detected client (Claude Code, Codex, Cursor), and checks that the
gateway accepts the result. It applies the same https rule as Step 1.

While it runs, it prints a verification URL and a short user code. Relay **only** those two
values to the user, ask them to open the URL in their browser and confirm the code, and wait.
Then go to Step 6.

### 4b. The agent is missing, or has no `connect`

Have the user download the installer from their gateway, read it, and only then run it.

macOS and Linux:

```bash
curl -fsSLo k2-agent-install.sh '<base>/agent/install.sh'
less k2-agent-install.sh          # read it before running it
sh k2-agent-install.sh
```

Windows (PowerShell):

```powershell
Invoke-WebRequest -Uri '<base>/agent/install.ps1' -OutFile k2-agent-install.ps1
Get-Content k2-agent-install.ps1  # read it before running it
powershell -NoProfile -File .\k2-agent-install.ps1
```

The installer serves a script with this gateway's URL already in it. It installs `k2-agent`,
puts it on the PATH for new terminals, and then signs in: it runs `k2-agent connect` itself when
the installed agent has it, relaying the same URL and user code as in 4a.

If the installed agent has no `connect` (a self-hosted gateway can pin an older release), the
installer runs `k2-agent auth login` instead. When that finishes, run:

```bash
k2-agent configure
```

to wire the installed clients. If sign-in was interrupted, run the downloaded installer file
again rather than retrying by hand. If you do need to run `k2-agent auth login` by hand, give it
the gateway URL and the public `oauth_client_id` from Step 3 for that one command only (neither
value is a secret, and neither is written to a profile):

```bash
K2_GATEWAY_URL='<base>' K2_OAUTH_CLIENT_ID='<oauth_client_id>' k2-agent auth login
k2-agent configure
```

As in 4a, relay only the verification URL and user code. Then go to Step 6.

## Step 5: fallback when the agent path is off

If `enrollment_enabled` is `false`, say plainly that desktop-agent sign-in is not enabled on this
gateway; if `binaries_available` is `false`, say plainly that this gateway cannot serve the agent.
Then send the user to their gateway's setup page:

```
<base>/install
```

That page signs them in through the browser and shows the client setup for their organisation.
In this branch you write **no** configuration of any kind, and you stop here; an administrator can
enable the agent path later, after which this skill can be run again.

## Step 6: verify

Check each client the user has:

- **Claude Code:** run `claude mcp list` and confirm the `mcp-gateway` server is listed as
  connected. Restart Claude Code if it was open before connecting.
- **Codex:** run `codex mcp list --json` and confirm the `mcp-gateway` entry's `auth_status` is
  anything other than `unsupported`. `unsupported` means Codex could not reach or discover the
  gateway: recheck `<base>` rather than editing any file.

Finally, have the user call one read-only K2 tool from the client, for example
`memory.repo_overview`, and confirm it returns a result. If `k2-agent` is installed, `k2-agent
status` (and `k2-agent doctor`, on agents that have it) gives a read-only summary to report when
something does not work.
