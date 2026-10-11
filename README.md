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
**trusted publishing** (OIDC): no npm token is stored in this repository. It runs only for a release tag,
called by `release.yml` after the GitHub Release is created (or on a pushed `v` tag), checks out
that tag, confirms it is on `main`, runs the version gate (the tag must equal `package.json` and
every plugin manifest) and `scripts/validate-npm-package.sh`, and then runs
`npm publish --provenance`. Pull requests run `.github/workflows/validate-npm.yml`, which never
publishes. For maintainers: npm checks the file name of the workflow that *started* the run, so the
package's trusted publishers on npmjs.com must list both `release.yml` and `publish-npm.yml` for
`K2-Rocket-Apps/k2`, each with the environment `npm-publish`.

## Security

CI for this repository runs on GitHub-hosted runners only. Release tags (`v*`) are immutable. To report a vulnerability, see [SECURITY.md](SECURITY.md).
