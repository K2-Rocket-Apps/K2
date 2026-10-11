"""The MCP Registry listing: server.json, scripts/validate-server-json.sh, its
fixtures (tests/fixtures/server-json/), publish-mcp-registry.yml and the
README section.

The validator cases build a throwaway git repository whose latest `v[0-9]*`
tag is v1.2.3 and whose HEAD also carries an `agent-v9.9.9` tag, put one
fixture in it as server.json, and prove the script's exit status. The script
downloads the pinned schema and runs ajv-cli through npx, so these cases need
npx and network access; without npx they report themselves skipped, which is
missing coverage, not a pass. CI (publish-mcp-registry.yml's `validate` job)
always has both.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate-server-json.sh"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "server-json"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SERVER = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

needs_npx = pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH")


def _workflow(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "tag.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True, text=True,
    ).stdout


def _run(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT), *flags, str(root)], capture_output=True, text=True, timeout=300)


def _repo(tmp_path: Path, fixture: str, *, release_tag_reachable: bool = True) -> Path:
    """A git repo: v1.2.3 (the latest release tag), then a commit tagged agent-v9.9.9."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "server.json").write_text((FIXTURES / fixture).read_text(encoding="utf-8"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "release")
    if release_tag_reachable:
        _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
    else:
        # The release tag sits on a side branch HEAD does not contain (as on
        # develop, where release tags sit on main's release merges).
        _git(root, "checkout", "-q", "-b", "side")
        _git(root, "commit", "-q", "--allow-empty", "-m", "release merge")
        _git(root, "tag", "-a", "v1.2.3", "-m", "v1.2.3")
        _git(root, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
        _git(root, "checkout", "-q", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "agent release")
    _git(root, "tag", "-a", "agent-v9.9.9", "-m", "agent-v9.9.9")
    return root


# --------------------------------------------------------------------------
# server.json
# --------------------------------------------------------------------------


def test_server_json_is_the_spec():
    assert SERVER["$schema"] == SCHEMA_URL
    assert SERVER["name"] == "com.k2-tek/gateway"
    assert SERVER["title"] == "MCP Gateway by K2"
    assert 0 < len(SERVER["description"]) <= 100
    assert SERVER["websiteUrl"] == "https://gateway.k2-tek.com/docs"
    assert SERVER["repository"] == {"url": "https://github.com/K2-Rocket-Apps/k2", "source": "github"}
    assert SERVER["remotes"] == [
        {
            "type": "streamable-http",
            "url": "https://{org_slug}.gateway.k2-tek.com/mcp",
            "variables": {
                "org_slug": {"description": "Your organization's gateway subdomain", "isRequired": True},
            },
        }
    ]
    # OAuth-only: no headers, no secret inputs, no packages.
    assert "packages" not in SERVER
    assert "headers" not in json.dumps(SERVER)
    assert "isSecret" not in json.dumps(SERVER)


def test_server_json_version_is_the_plugin_version():
    manifest = json.loads((REPO_ROOT / "plugins/k2/.claude-plugin/plugin.json").read_text())
    assert SERVER["version"] == manifest["version"]


def test_valid_fixture_is_the_real_server_json_at_the_fixture_version():
    valid = json.loads((FIXTURES / "valid.json").read_text())
    assert valid["version"] == "1.2.3"
    assert {**valid, "version": SERVER["version"]} == SERVER


# --------------------------------------------------------------------------
# The validator
# --------------------------------------------------------------------------


def test_script_is_executable_and_strict():
    assert os.access(SCRIPT, os.X_OK)
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "npx --yes -p \"$AJV_CLI\"" in text and 'AJV_CLI="ajv-cli@5.0.0"' in text
    assert f'SCHEMA_URL="{SCHEMA_URL}"' in text
    assert re.search(r'SCHEMA_SHA256="[0-9a-f]{64}"', text)
    assert "git -C \"$ROOT\" describe --tags --match 'v[0-9]*' --abbrev=0 HEAD" in text


@needs_npx
def test_the_real_server_json_passes():
    """AC1: exit 0 on the committed file (needs a fetched release tag)."""
    tags = subprocess.run(["git", "tag", "--list", "v[0-9]*"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    if not tags.strip():
        pytest.skip("no v[0-9]* tag in this checkout (shallow clone); publish-mcp-registry.yml checks with fetch-depth 0")
    result = _run(REPO_ROOT, "--allow-pending-bump")
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


@needs_npx
def test_valid_fixture_passes_despite_a_newer_agent_tag(tmp_path):
    """AC1: an agent-v9.9.9 tag at HEAD does not affect the version check."""
    root = _repo(tmp_path, "valid.json")
    assert "agent-v9.9.9" in _git(root, "tag", "--points-at", "HEAD")
    result = _run(root)
    assert result.returncode == 0, result.stderr
    assert "v1.2.3" in result.stdout


@needs_npx
def test_valid_fixture_passes_when_the_release_tag_is_not_reachable(tmp_path):
    root = _repo(tmp_path, "valid.json", release_tag_reachable=False)
    result = _run(root)
    assert result.returncode == 0, result.stderr


@needs_npx
@pytest.mark.parametrize(
    "fixture,needle",
    [
        ("description-101.json", "description is 101 characters"),
        ("headers.json", "remotes[0] declares headers"),
        ("version-mismatch.json", "version '1.2.4' does not match the latest release tag 'v1.2.3'"),
        ("version-of-agent-tag.json", "version '9.9.9' does not match the latest release tag 'v1.2.3'"),
        ("org-slug-default.json", "remotes[0].variables.org_slug has a 'default'"),
        ("schema-invalid.json", "does not validate against"),
        ("schema-url-unpinned.json", "$schema must be exactly"),
    ],
)
def test_rejects_each_forbidden_fixture(tmp_path, fixture, needle):
    """AC1: non-zero for each negative fixture, for the reason it names."""
    root = _repo(tmp_path, fixture)
    result = _run(root)
    assert result.returncode != 0
    assert needle in result.stderr, result.stderr


def test_every_negative_fixture_is_exercised():
    fixtures = {p.name for p in FIXTURES.glob("*.json")} - {"valid.json"}
    exercised = {
        "description-101.json", "headers.json", "version-mismatch.json", "version-of-agent-tag.json",
        "org-slug-default.json", "schema-invalid.json", "schema-url-unpinned.json",
    }
    assert fixtures == exercised


@needs_npx
def test_fails_closed_without_any_release_tag(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    shutil.copy(FIXTURES / "valid.json", root / "server.json")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "x")
    _git(root, "tag", "-a", "agent-v1.2.3", "-m", "agent")
    result = _run(root)
    assert result.returncode != 0
    assert "no v[0-9]* release tag found" in result.stderr


def _with_manifest(root: Path, version: str) -> None:
    manifest = root / "plugins" / "k2" / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "k2", "version": version}) + "\n")


def _set_version(root: Path, version: str) -> None:
    doc = json.loads((root / "server.json").read_text())
    doc["version"] = version
    (root / "server.json").write_text(json.dumps(doc, indent=2) + "\n")


@needs_npx
def test_pending_bump_is_accepted_only_with_the_flag_and_the_matching_manifest(tmp_path):
    root = _repo(tmp_path, "valid.json")
    _with_manifest(root, "1.3.0")
    _set_version(root, "1.3.0")
    # Strict (the publish path): the version must equal the latest tag.
    assert _run(root).returncode != 0
    # A release-bump pull request: above the latest tag and equal to the manifest.
    result = _run(root, "--allow-pending-bump")
    assert result.returncode == 0, result.stderr


@needs_npx
@pytest.mark.parametrize("manifest,version", [("1.3.0", "1.4.0"), ("1.2.2", "1.2.2"), ("1.2.3", "1.2.4")])
def test_pending_bump_never_accepts_a_mismatch_or_a_downgrade(tmp_path, manifest, version):
    root = _repo(tmp_path, "valid.json")
    _with_manifest(root, manifest)
    _set_version(root, version)
    assert _run(root, "--allow-pending-bump").returncode != 0


# --------------------------------------------------------------------------
# publish-mcp-registry.yml
# --------------------------------------------------------------------------

WF_NAME = "publish-mcp-registry.yml"
WF_TEXT = (WORKFLOWS / WF_NAME).read_text(encoding="utf-8")


def _jobs() -> dict:
    jobs = _workflow(WF_NAME)["jobs"]
    assert set(jobs) == {"validate", "publish"}
    return jobs


def test_triggers_are_pull_request_and_the_release_call_only():
    on = _workflow(WF_NAME)["on"]
    assert set(on) == {"pull_request", "workflow_call"}
    call = on["workflow_call"]
    assert call["inputs"]["tag"]["required"] is True and call["inputs"]["tag"]["type"] == "string"
    assert set(call["secrets"]) == {"MCP_REGISTRY_PRIVATE_KEY"}
    assert _workflow(WF_NAME)["permissions"] == {"contents": "read"}


def _github_tag_filter_matches(pattern: str, tag: str) -> bool:
    # Enough of GitHub's filter syntax for tag patterns without `/` or `**`.
    return "/" not in tag and fnmatch.fnmatchcase(tag, pattern)


@pytest.mark.parametrize("tag,fires", [("v0.4.1", True), ("v10.0.0", True), ("agent-v9.9.9", False),
                                       ("agent-v0.1.0", False), ("vnext", False)])
def test_only_a_v_digit_tag_reaches_the_publisher(tag, fires):
    """AC3: a pushed agent-v* tag never triggers a publish. The only path is
    release.yml's tag filter; this workflow has no tag trigger of its own."""
    assert "push" not in _workflow(WF_NAME)["on"]
    (pattern,) = _workflow("release.yml")["on"]["push"]["tags"]
    assert pattern == "v[0-9]*"
    assert _github_tag_filter_matches(pattern, tag) is fires


def test_the_publish_path_never_matches_a_bare_v_star_or_latest_release():
    for name in ("release.yml", WF_NAME):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert not re.search(r"""["'\[ ]v\*["'\] ,]""", text), name
        assert "releases/latest" not in text, name


def test_validate_job_is_read_only_and_self_tests_the_fixtures():
    job = _jobs()["validate"]
    assert job["if"] == "github.event_name == 'pull_request'"
    assert "environment" not in job and "permissions" not in job
    assert "secrets." not in yaml.safe_dump(job)
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    runs = [s.get("run", "") for s in job["steps"]]
    assert "scripts/validate-server-json.sh --allow-pending-bump" in runs
    assert any("pytest tests/test_validate_server_json.py" in r for r in runs)
    assert not any("mcp-publisher" in r for r in runs)


def _index(steps, predicate, what):
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    raise AssertionError(f"{WF_NAME}: no step {what}")


def test_publish_job_environment_and_permissions():
    job = _jobs()["publish"]
    assert job["if"] == "github.event_name != 'pull_request'"
    assert job["environment"] == "mcp-registry"
    assert job["permissions"] == {"contents": "read"}
    assert job["runs-on"] == "ubuntu-latest"
    assert job["env"]["TAG"] == "${{ inputs.tag }}"


def test_publish_steps_run_in_order():
    steps = _jobs()["publish"]["steps"]
    run = lambda needle: (lambda s: needle in s.get("run", ""))  # noqa: E731
    uses = lambda needle: (lambda s: s.get("uses", "").startswith(needle))  # noqa: E731
    order = [
        _index(steps, uses("actions/checkout@"), "checkout"),
        _index(steps, run('tests/version_consistency.py --tag "$TAG"'), "version gate"),
        _index(steps, run("git merge-base --is-ancestor"), "main ancestry check"),
        _index(steps, run("scripts/validate-server-json.sh"), "validator"),
        _index(steps, run('curl -fsS -o /dev/null "$WEBSITE_URL"'), "pre-publish websiteUrl gate"),
        _index(steps, run("sha256sum -c"), "checksum-verified mcp-publisher install"),
        _index(steps, run("mcp-publisher login dns --domain k2-tek.com"), "login"),
        _index(steps, run("mcp-publisher publish"), "publish"),
        _index(steps, run("is not listed on"), "post-publish registry check"),
    ]
    assert order == sorted(order), order
    checkout = steps[order[0]]["with"]
    assert checkout["ref"] == "refs/tags/${{ inputs.tag }}"
    assert checkout["fetch-depth"] == 0
    assert checkout["persist-credentials"] is False
    assert _workflow(WF_NAME)["env"]["WEBSITE_URL"] == SERVER["websiteUrl"]
    assert _workflow(WF_NAME)["env"]["SERVER_NAME"] == SERVER["name"]
    # Exactly one step publishes; nothing but checkout and setup runs before the version gate.
    assert sum("mcp-publisher publish" in s.get("run", "") for s in steps) == 1
    assert all("run" not in s for s in steps[: order[1]])


def test_mcp_publisher_is_pinned_and_checksum_verified():
    env = _workflow(WF_NAME)["env"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", env["MCP_PUBLISHER_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["MCP_PUBLISHER_SHA256"])
    (install,) = [s for s in _jobs()["publish"]["steps"] if "mcp-publisher_linux_amd64.tar.gz" in s.get("run", "")]
    text = install["run"]
    assert 'echo "${MCP_PUBLISHER_SHA256}  ${asset}" | sha256sum -c -' in text
    assert "registry_${MCP_PUBLISHER_VERSION}_checksums.txt" in text
    assert "releases/download/v${MCP_PUBLISHER_VERSION}" in text


def test_the_private_key_reaches_only_the_login_step_and_is_never_printed():
    steps = _jobs()["publish"]["steps"]
    with_key = [s for s in steps if "MCP_REGISTRY_PRIVATE_KEY" in yaml.safe_dump(s)]
    assert len(with_key) == 1
    login = with_key[0]
    assert login["env"] == {"MCP_REGISTRY_PRIVATE_KEY": "${{ secrets.MCP_REGISTRY_PRIVATE_KEY }}"}
    lines = login["run"].splitlines()
    assert lines[0] == "set +x"
    for line in lines:
        if re.search(r"\b(echo|printf)\b", line):
            assert "$MCP_REGISTRY_PRIVATE_KEY" not in line and "${MCP_REGISTRY_PRIVATE_KEY" not in line, line
    # The secret is referenced in exactly one place in the whole workflow.
    assert WF_TEXT.count("${{ secrets.MCP_REGISTRY_PRIVATE_KEY }}") == 1
    assert "set -x" not in WF_TEXT


def test_no_workflow_runs_on_a_self_hosted_runner():
    for path in WORKFLOWS.glob("*.yml"):
        assert "self-hosted" not in path.read_text(encoding="utf-8"), path.name


# --------------------------------------------------------------------------
# README section
# --------------------------------------------------------------------------


def _section() -> str:
    match = re.search(r"^## MCP Registry$(.*?)(?=^## )", README, re.M | re.S)
    assert match, "README.md has no '## MCP Registry' section"
    return match.group(1)


@pytest.mark.parametrize(
    "needle",
    [
        "com.k2-tek/gateway",
        "https://{org_slug}.gateway.k2-tek.com/mcp",
        "server.json",
        "publish-mcp-registry.yml",
        "mcp-registry",
        "v=MCPv1; k=ed25519; p=",
        "MCP_REGISTRY_PRIVATE_KEY",
        "Key rotation",
    ],
)
def test_readme_registry_section_has(needle):
    assert needle in _section()


def test_readme_registry_section_holds_no_key_material():
    section = _section()
    # A base64 Ed25519 public key is 44 characters; a hex private key is 64.
    assert not re.search(r"p=[A-Za-z0-9+/]{40,}={0,2}", section)
    assert not re.search(r"\b[0-9a-fA-F]{64}\b", section)
    assert "BEGIN PRIVATE KEY" not in section
