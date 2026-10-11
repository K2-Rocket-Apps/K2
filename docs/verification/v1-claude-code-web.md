# V1: k2 in Claude Code on the web

This is the record of whether the `k2` plugin installs and works in a Claude Code on the web (cloud)
environment through the one-line setup script in the [README](../../README.md#claude-code-on-the-web).

The local half of the same question (Claude Code and Codex installing anonymously on a clean machine
with no GitHub CLI) is automated by [`scripts/install-smoke.sh`](../../scripts/install-smoke.sh) and
the [`install-smoke`](../../.github/workflows/install-smoke.yml) workflow. This file covers the cloud
half, which needs a person to paste the setup script into a new environment and cannot be automated.

## Summary

| Check | What it proves | Result |
|---|---|---|
| (a) | The setup-script line in a **fresh** environment exits 0, `k2` is listed in a **new** session, and a cached rerun finishes in under 5 minutes | **PENDING**: needs an owner run in a fresh environment (steps below) |
| (b) | `curl` reaches a raw.githubusercontent.com file and a GitHub Release asset from the cloud | **PASS** (2026-10-11) |
| (c) | `git status` in the session's repository is clean after the setup line runs | **PASS** (2026-10-11) |
| (d) | Behaviour in a session with more than one repository | **PENDING**: needs an owner run in a fresh environment (steps below) |
| (e) | Whether `--yes` is needed for a user-scope install | **PASS**: not needed (2026-10-11) |

Nothing is marked PASS here unless it was actually observed. A PENDING row stays PENDING until
someone runs it and replaces the row with what they saw.

If (a) ends up FAIL, the plugin still ships for local Claude Code and Codex; the cloud path then falls
back to connecting through a connector only, and this file must say so.

## The setup-script line

The exact line, as published in the README. It goes **last** in the environment's setup script,
because its trailing `exit 0` ends the script:

```sh
claude plugin marketplace add K2-Rocket-Apps/k2 && claude plugin install k2@k2 --scope user || echo "k2 plugin install failed (see above)" >&2; exit 0
```

A failed install prints a message and still exits 0, so a broken network or marketplace can never stop
the environment from starting.

## Run of 2026-10-11 (from inside a running cloud session)

- Where: a Claude Code on the web session (a cloud container), not a fresh environment. That is why
  (a) and (d) are not answered by this run.
- Claude Code version in the environment: `2.1.296 (Claude Code)`.
- Every install below used a **throwaway** `HOME` and `CLAUDE_CONFIG_DIR`, so nothing was added to the
  session's own Claude Code configuration, and `GH_TOKEN`/`GITHUB_TOKEN` were unset.
- The cloud environment sends outbound HTTPS through its own proxy. From inside the session it is not
  observable whether that proxy adds GitHub credentials, so these results show the cloud can **reach**
  everything it needs; they do not prove the requests were anonymous. Anonymity is proven by the
  `install-smoke` workflow, which runs on a GitHub-hosted runner with no token.

### (b) raw file and Release asset: PASS

```console
$ curl -sS -o /dev/null -w '%{http_code} %{size_download}\n' \
    https://raw.githubusercontent.com/K2-Rocket-Apps/k2/v0.4.0/.claude-plugin/marketplace.json
200 675

$ curl -sSL -o k2-v0.4.0.tar.gz https://github.com/K2-Rocket-Apps/k2/releases/download/v0.4.0/k2-v0.4.0.tar.gz   # HTTP 200, 55863 bytes
$ curl -sSL -o SHA256SUMS      https://github.com/K2-Rocket-Apps/k2/releases/download/v0.4.0/SHA256SUMS        # HTTP 200, 83 bytes
$ sha256sum -c SHA256SUMS
k2-v0.4.0.tar.gz: OK
```

Both Release downloads redirect to `release-assets.githubusercontent.com`, which the cloud environment
also reached.

### (c) `git status` clean after setup: PASS

A scratch clone of this repository (checked out at `v0.4.0`) stood in for the session's repository. The
setup line was run from inside it, with stdin not a terminal (as in a setup script):

```console
$ claude plugin marketplace add K2-Rocket-Apps/k2 && claude plugin install k2@k2 --scope user || echo "k2 plugin install failed (see above)" >&2; exit 0
Adding marketplace…Cloning via HTTPS: https://github.com/K2-Rocket-Apps/k2.git
Refreshing marketplace cache (timeout: 120s)…
Cloning repository (timeout: 120s): https://github.com/K2-Rocket-Apps/k2.git
Clone complete, validating marketplace…
Cleaning up old marketplace cache…
√ Successfully added marketplace: k2 (declared in user settings)
Installing plugin "k2@k2"...√ Successfully installed plugin: k2@k2 (scope: user)
# exit 0, 1.6 s

$ git status --porcelain --ignored
$ git status
HEAD detached at v0.4.0
nothing to commit, working tree clean
```

`--porcelain --ignored` printing nothing means the install wrote no file into the repository, not even
an ignored one. The throwaway `HOME` also had no user-level git config file afterwards.

Running the same line a second time against the same `HOME` exited 0 in 0.9 s
(`Marketplace 'k2' already on disk`, `Plugin "k2@k2" is already installed`), and `claude plugin list`
showed `k2@k2`, version `0.4.0`, scope `user`, enabled. This is only an indication for (a): a rerun
inside one container is not the same as a fresh environment's cached rerun.

### (e) `--yes` at user scope: PASS (not needed)

The install above ran with stdin not a terminal and without `--yes`, and succeeded. Claude Code's own
help for `claude plugin install` says `--yes` only accepts a *marketplace-declared command* (a plugin
installed by running a command, or one fetched through a headers helper). `k2` is a plain path source
in this marketplace, so there is no command to accept. Running the same install with `--yes` in a fresh
throwaway `HOME` also succeeded (exit 0), so adding it is harmless but unnecessary. The setup line
stays without it.

## Steps still to run (owner)

### (a) Fresh environment, new session, cached rerun

1. In Claude Code on the web, create a **new** environment (one never used before) and put the
   setup-script line above as the last line of its setup script.
2. Start a session in that environment with any repository. Record the date and the version printed by
   `claude --version`.
3. In that session, confirm the setup script exited 0 (the setup log shows no
   `k2 plugin install failed` line) and that `claude plugin list` shows `k2@k2`, enabled, at user
   scope. Also confirm the `k2` skills are offered (for example, ask "Connect me to my K2 gateway." and
   check the agent picks the `k2-connect` skill).
4. Start a **second, new** session in the same environment. Time from start to a usable prompt and
   confirm `k2@k2` is still listed. Under 5 minutes is a PASS.
5. Replace the (a) row above with PASS or FAIL, the date, the version and the timing.

### (d) Multi-repository session

1. In the same environment, start a session with **two or more** repositories attached.
2. Confirm the setup script still exits 0, `claude plugin list` shows `k2@k2` once, enabled, and
   `git status` is clean in **every** attached repository.
3. Replace the (d) row above with PASS or FAIL and what was seen.
