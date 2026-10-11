# k2

The public K2 plugin marketplace for Claude Code and Codex. It gives you one install that connects your coding agent to your organization's K2 MCP Gateway and Memory.

This repository is public and can be cloned anonymously. It contains no secrets, no credentials and no MCP server entries; your gateway URL and sign-in are configured locally by `k2-agent connect`.

## Install

Every command below uses only the public repository URL; none of them needs a token or a secret.
The `k2` plugin installs **no MCP server, no hooks and no background jobs**, and **changes no git
settings**. It ships skills only.

### Claude Code

```sh
claude plugin marketplace add K2-Rocket-Apps/k2
claude plugin install k2@k2 --scope user
```

To pin a specific release instead of following the default branch, add the marketplace at a tag:

```sh
claude plugin marketplace add K2-Rocket-Apps/k2#v0.3.0
claude plugin install k2@k2 --scope user
```

Optional: turn on `autoUpdate` for the `k2` marketplace so Claude Code picks up new releases when it
starts, by setting it in your user settings file (`~/.claude/settings.json`):

```json
{
  "extraKnownMarketplaces": {
    "k2": {
      "source": { "source": "github", "repo": "K2-Rocket-Apps/k2" },
      "autoUpdate": true
    }
  }
}
```

`autoUpdate` only manages user-scope installs, which is why the install above uses `--scope user`.
Leave it off if you pinned a tag.

### Codex

```sh
codex plugin marketplace add K2-Rocket-Apps/k2
codex plugin add k2@k2
```

To pin a release, add the marketplace with `--ref`:

```sh
codex plugin marketplace add K2-Rocket-Apps/k2 --ref v0.3.0
codex plugin add k2@k2
```

To upgrade later:

```sh
codex plugin marketplace upgrade k2
```

### Claude Code on the web

Add this line as the **last** line of your environment's setup script (its trailing `exit 0` ends the
script). A failed install is reported but never blocks the session from starting:

```sh
claude plugin marketplace add K2-Rocket-Apps/k2 && claude plugin install k2@k2 --scope user || echo "k2 plugin install failed (see above)" >&2; exit 0
```

### Verify a release

Each GitHub Release carries `k2-vX.Y.Z.tar.gz` (the tagged source) and `SHA256SUMS`, both with a
GitHub artifact attestation. After downloading them from the release page:

```sh
gh attestation verify k2-vX.Y.Z.tar.gz --repo K2-Rocket-Apps/k2
sha256sum -c SHA256SUMS
```

### Next step: connect

Installing the plugin connects nothing on its own. Ask your agent to run the **k2-connect** skill
(for example, "Connect me to my K2 gateway."). It sets up your gateway URL through `k2-agent`, and
sign-in happens in your browser.

### Optional: k2-memory-hooks

This marketplace also lists `k2-memory-hooks`, a separate Claude Code plugin that sends session
heartbeats and redacted test-failure friction to your organization's K2 Memory through `k2-agent`.
It is **opt-in**: installing `k2` never installs or enables it, and nothing it sends is accepted until
your organization's admin and you have both consented. See
[plugins/k2-memory-hooks/README.md](plugins/k2-memory-hooks/README.md) before installing it.

Release history is in [CHANGELOG.md](CHANGELOG.md).

## Install from npm (Codex)

Each release tag is also published to npm as `@k2-tek/k2`, with an npm provenance attestation that
links the package to the GitHub Actions run that built it from this repository. The package is the
marketplace exactly as tagged (`.claude-plugin/`, `plugins/k2/`, `plugins/k2-memory-hooks/`,
`LICENSE`, `README.md`): it has no install scripts and no dependencies, so installing it runs
nothing. Use it when you want Codex to install from the npm registry instead of from GitHub.
Publishing to npm starts with the first release after v0.4.0; until that version is on npm, use the
GitHub install above.

Codex adds a marketplace from a local path, so install the package into a directory you keep, then
point Codex at it. Always pin the version:

```sh
npm install --prefix ~/.k2-npm --ignore-scripts @k2-tek/k2@0.4.0
codex plugin marketplace add ~/.k2-npm/node_modules/@k2-tek/k2
codex plugin add k2@k2
```

To upgrade, install the newer version into the same directory and add the plugin again:

```sh
npm install --prefix ~/.k2-npm --ignore-scripts @k2-tek/k2@X.Y.Z
codex plugin add k2@k2
```

In a setup script, the same install can be made to report a failure without stopping the script:

```sh
{ npm install --prefix ~/.k2-npm --ignore-scripts @k2-tek/k2@0.4.0 && codex plugin marketplace add ~/.k2-npm/node_modules/@k2-tek/k2 && codex plugin add k2@k2; } || echo "k2 npm install failed (see above)" >&2
```

This marketplace is also named `k2`, so use either the npm copy or the GitHub one, not both.

**Claude Code:** use the GitHub marketplace (`claude plugin marketplace add K2-Rocket-Apps/k2`, see
above). Installing Claude Code plugins from npm is not supported here.

**Verify the provenance** of the package you installed:

```sh
cd ~/.k2-npm && npm audit signatures
```

It should report the `@k2-tek/k2` package as having a verified registry signature and a verified
attestation. The package page on npmjs.com shows the same provenance, linked to the workflow run.

**How it is published.** `.github/workflows/publish-npm.yml` publishes with npm
**trusted publishing** (OIDC): no npm token is stored in this repository. It has one entry point:
`release.yml` calls it for a release tag, only after the GitHub Release is created. It checks out
that tag, confirms it is on `main`, runs the version gate (the tag must equal `package.json` and
every plugin manifest) and the test suite, then runs `scripts/validate-npm-package.sh` (which also
rejects any packed file that git does not track), and only then runs `npm publish --provenance`.
Pull requests run `.github/workflows/validate-npm.yml`, which never publishes. For maintainers:
npm checks the file name of the workflow that *started* the run, so the package's trusted
publisher on npmjs.com is `release.yml` for `K2-Rocket-Apps/k2`, with the environment
`npm-publish`.

## MCP Registry

The MCP Gateway is listed on the official [MCP Registry](https://registry.modelcontextprotocol.io) as
`com.k2-tek/gateway`. The listing is [`server.json`](server.json) in this repository, published at
the version of each plugin release tag.

**The templated URL.** Every organization has its own gateway host, so the listing does not name one.
Its one remote is a template:

```text
https://{org_slug}.gateway.k2-tek.com/mcp
```

`org_slug` is a required variable with no default: your MCP client asks you for your organization's
gateway subdomain (for example, `acme` gives `https://acme.gateway.k2-tek.com/mcp`). The remote
declares no headers and no secret inputs. Sign-in is OAuth in your browser, so nothing in the listing
carries a token, and no organization's host is published in it.

**How it is published.** `.github/workflows/publish-mcp-registry.yml` has two entry points. On a pull
request it runs `scripts/validate-server-json.sh` (the pinned 2025-12-11 schema with ajv, a
description of at most 100 characters, no `headers`, no default `org_slug`, and a `version` equal to
the latest `v[0-9]*` release tag; `agent-v*` tags never count) and proves the validator rejects every
fixture in `tests/fixtures/server-json/`. For a release, `release.yml` calls it with the tag after the
GitHub Release is created; it never runs from a tag push of its own. The publish job runs in the
`mcp-registry` environment, which needs a maintainer's approval, then checks the version gate (the tag
must equal `server.json` and every plugin manifest), checks that `https://gateway.k2-tek.com/docs`
answers (it fails closed if not), installs a pinned, checksum-verified `mcp-publisher`, signs in with
DNS authentication for `k2-tek.com`, and publishes.

**DNS authentication.** The registry accepts `com.k2-tek/*` names from whoever holds the Ed25519 key
whose public half is published in a TXT record at the `k2-tek.com` apex:

```text
v=MCPv1; k=ed25519; p=<base64 public key>
```

The private key is stored only as the `MCP_REGISTRY_PRIVATE_KEY` secret of the `mcp-registry`
environment (hex, as `mcp-publisher login dns --private-key` expects). It is never committed, never
printed in a log, and never stored as a repository-wide secret.

**Key rotation.** For maintainers. No key material belongs in this repository, an issue or a log.

1. On an offline machine, generate a new Ed25519 keypair, for example
   `openssl genpkey -algorithm Ed25519 -out new.pem`. Derive the base64 public key
   (`openssl pkey -in new.pem -pubout -outform DER | tail -c 32 | base64`) and the hex private key
   (`openssl pkey -in new.pem -noout -text`, the `priv:` bytes without colons or spaces).
2. **Add** a second apex TXT record, `v=MCPv1; k=ed25519; p=<new base64 public key>`, next to the
   current one. Do not remove the old record yet. Wait until `dig +short TXT k2-tek.com` shows both.
3. Replace the `MCP_REGISTRY_PRIVATE_KEY` secret of the `mcp-registry` environment with the new hex
   private key.
4. Publish once with the new key (the next release, or a re-run of the `mcp-registry` job of the
   latest release, which skips publishing a version that is already listed but still proves nothing
   else changed). A failed login means the new TXT record is not visible yet: wait and retry.
5. **Remove** the old TXT record, then securely delete every copy of the old and new private keys
   outside the environment secret.

If the key is ever exposed, do the same steps at once and remove the old record immediately after
step 3.

## Security

CI for this repository runs on GitHub-hosted runners only. Release tags (`v*`) are immutable. To report a vulnerability, see [SECURITY.md](SECURITY.md).
