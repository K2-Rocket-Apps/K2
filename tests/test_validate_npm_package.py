"""The npm mirror: package.json, scripts/validate-npm-package.sh, and the two
workflows around it (publish-npm.yml, validate-npm.yml).

The validator cases copy the package's files to `tmp_path`, apply one
forbidden change (the fixture), and prove the script exits non-zero. They need
npm and python3, which every GitHub-hosted runner has; without npm they report
themselves skipped, which is missing coverage, not a pass.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "validate-npm-package.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PACKAGE = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not on PATH")

# What the package may ship: the git marketplace root, nothing else.
PACKAGE_FILES = [
    ".claude-plugin/",
    "plugins/k2/",
    "plugins/k2-memory-hooks/",
    "LICENSE",
    "README.md",
    # Never pack bytecode the test suite (or a user) left under plugins/.
    "!**/__pycache__/**",
    "!**/*.py[co]",
]


def _workflow(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def _run(root: Path | None = None) -> subprocess.CompletedProcess:
    args = [str(SCRIPT)] + ([str(root)] if root else [])
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith("npm_config_")}
    return subprocess.run(args, capture_output=True, text=True, timeout=120, env=env)


# --------------------------------------------------------------------------
# package.json
# --------------------------------------------------------------------------


def test_package_name_is_scoped_and_lives_only_in_package_json():
    assert re.fullmatch(r"@[a-z0-9-]+/[a-z0-9-]+", PACKAGE["name"])
    for wf in ("publish-npm.yml", "validate-npm.yml", "release.yml"):
        assert PACKAGE["name"] not in (WORKFLOWS / wf).read_text(encoding="utf-8"), wf


def test_package_version_matches_the_plugin_manifest():
    manifest = json.loads((REPO_ROOT / "plugins/k2/.claude-plugin/plugin.json").read_text())
    assert PACKAGE["version"] == manifest["version"]


def test_package_license_matches_license_file_and_manifest():
    manifest = json.loads((REPO_ROOT / "plugins/k2/.claude-plugin/plugin.json").read_text())
    assert PACKAGE["license"] == manifest["license"] == "Apache-2.0"
    assert "Apache License" in (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")[:200]


def test_package_repository_is_the_public_repo():
    assert PACKAGE["repository"]["url"] == "git+https://github.com/K2-Rocket-Apps/k2.git"


def test_package_files_allow_list_is_exactly_the_marketplace_root():
    assert PACKAGE["files"] == PACKAGE_FILES


def test_package_runs_nothing_and_is_publishable():
    assert "private" not in PACKAGE
    assert "scripts" not in PACKAGE
    for key in ("dependencies", "optionalDependencies", "peerDependencies", "bundleDependencies", "bin"):
        assert key not in PACKAGE
    assert PACKAGE["publishConfig"] == {"access": "public", "provenance": True}


# --------------------------------------------------------------------------
# The validator
# --------------------------------------------------------------------------


def test_script_is_executable_and_strict():
    assert os.access(SCRIPT, os.X_OK)
    assert "set -euo pipefail" in SCRIPT.read_text(encoding="utf-8")


def test_script_never_lets_npm_run_a_script():
    text = SCRIPT.read_text(encoding="utf-8")
    pack_lines = [line for line in text.splitlines() if re.search(r"&&\s*npm pack\b", line)]
    assert pack_lines and all("--ignore-scripts" in line for line in pack_lines)
    # The lifecycle check runs before npm is asked to pack anything.
    assert text.index("LIFECYCLE = {") < text.index('(cd "$ROOT" && npm pack --dry-run --json')


@needs_npm
def test_the_real_package_passes():
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


@needs_npm
def test_npm_pack_lists_only_allow_listed_paths_and_no_token():
    """AC1, independent of the script: the raw `npm pack --dry-run --json` listing."""
    out = subprocess.run(
        ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=120,
    ).stdout
    (entry,) = json.loads(out)
    assert entry["name"] == PACKAGE["name"] and entry["version"] == PACKAGE["version"]
    paths = sorted(f["path"] for f in entry["files"])
    roots = {"package.json", "LICENSE", "README.md"}
    prefixes = (".claude-plugin/", "plugins/k2/", "plugins/k2-memory-hooks/")
    assert [p for p in paths if p not in roots and not p.startswith(prefixes)] == []
    assert [p for p in paths if "__pycache__" in p.split("/") or p.endswith((".pyc", ".pyo"))] == []
    # The tarball is a subset of the git tree: nothing untracked is packed.
    tracked = set(subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0"))
    assert [p for p in paths if p not in tracked] == []
    assert {"package.json", ".claude-plugin/marketplace.json", "plugins/k2/.codex-plugin/plugin.json"} <= set(paths)
    for path in paths:
        assert not re.search(r"mgw_[A-Za-z0-9]", (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")), path


@pytest.fixture
def package_copy(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    for name in ("package.json", "LICENSE", "README.md"):
        shutil.copy(REPO_ROOT / name, root / name)
    for name in (".claude-plugin", "plugins"):
        shutil.copytree(REPO_ROOT / name, root / name)
    return root


def _edit_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@needs_npm
def test_copy_passes_before_any_fixture(package_copy):
    result = _run(package_copy)
    assert result.returncode == 0, result.stderr


@needs_npm
@pytest.mark.parametrize("script", ["postinstall", "prepare", "preinstall", "install", "prepack"])
def test_rejects_a_lifecycle_script(package_copy, script):
    marker = package_copy / "ran"
    _edit_json(package_copy / "package.json", lambda d: d.setdefault("scripts", {}).update({script: f"touch {marker}"}))
    result = _run(package_copy)
    assert result.returncode != 0
    assert f"lifecycle script {script!r}" in result.stderr
    assert not marker.exists(), "the validator let npm run the fixture's script"


@needs_npm
def test_rejects_a_file_outside_the_allow_list(package_copy):
    (package_copy / "notes.txt").write_text("x\n")
    _edit_json(package_copy / "package.json", lambda d: d["files"].append("notes.txt"))
    result = _run(package_copy)
    assert result.returncode != 0
    assert "notes.txt: packed file is outside the allow-list" in result.stderr


@needs_npm
def test_rejects_a_file_widened_in_by_a_glob(package_copy):
    (package_copy / "scripts").mkdir()
    (package_copy / "scripts" / "x.sh").write_text("true\n")
    _edit_json(package_copy / "package.json", lambda d: d["files"].append("scripts/"))
    result = _run(package_copy)
    assert result.returncode != 0
    assert "scripts/x.sh" in result.stderr


@needs_npm
@pytest.mark.parametrize(
    "rel,mutate",
    [
        ("plugins/k2/.claude-plugin/plugin.json", lambda d: d.update(homepage="https://${K2_HOST}/k2")),
        ("plugins/k2/.codex-plugin/plugin.json", lambda d: d["interface"].update(websiteURL="${SITE}/k2")),
        (".claude-plugin/marketplace.json", lambda d: d["owner"].update(url="https://${ORG}.example")),
    ],
    ids=["claude-manifest", "codex-manifest", "marketplace"],
)
def test_rejects_a_placeholder_url(package_copy, rel, mutate):
    _edit_json(package_copy / rel, mutate)
    result = _run(package_copy)
    assert result.returncode != 0
    assert "unexpanded '${' placeholder" in result.stderr


@needs_npm
def test_rejects_a_placeholder_url_in_a_packed_mcp_json(package_copy):
    (package_copy / "plugins/k2/.mcp.json").write_text(
        json.dumps({"mcpServers": {"k2": {"type": "http", "url": "${K2_GATEWAY_URL}/mcp"}}}) + "\n"
    )
    result = _run(package_copy)
    assert result.returncode != 0
    assert "plugins/k2/.mcp.json: URL contains an unexpanded" in result.stderr


@needs_npm
def test_rejects_a_token_prefix_in_a_packed_file(package_copy):
    token = "mgw" + "_" + "Abc123"  # assembled so this test file never holds the literal
    skill = package_copy / "plugins/k2/skills/k2-connect/SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + f"\nexample: {token}\n", encoding="utf-8")
    result = _run(package_copy)
    assert result.returncode != 0
    assert "contains a gateway token prefix" in result.stderr


@needs_npm
@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda d: d.update(private=True), "'private' must not be set"),
        (lambda d: d.update(dependencies={"left-pad": "1.3.0"}), "'dependencies' is not allowed"),
        (lambda d: d.update(bin={"k2": "x.js"}), "'bin' is not allowed"),
        (lambda d: d.update(repository={"type": "git", "url": "https://example.com/other.git"}), "repository.url"),
        (lambda d: d.update(license="MIT"), "license"),
    ],
    ids=["private", "dependency", "bin", "repository", "license"],
)
def test_rejects_an_unsafe_package_json(package_copy, mutate, needle):
    _edit_json(package_copy / "package.json", mutate)
    result = _run(package_copy)
    assert result.returncode != 0
    assert needle in result.stderr


@needs_npm
def test_bytecode_is_never_packed_by_default(package_copy):
    """The `files` negations keep bytecode out of the tarball even if it exists."""
    cache = package_copy / "plugins" / "k2-memory-hooks" / "hooks" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "planted.cpython-313.pyc").write_bytes(b"\x00bytecode")
    result = _run(package_copy)
    assert result.returncode == 0, result.stderr
    out = subprocess.run(
        ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
        cwd=package_copy, capture_output=True, text=True, check=True, timeout=120,
    ).stdout
    assert not [f["path"] for f in json.loads(out)[0]["files"] if "__pycache__" in f["path"]]


@needs_npm
@pytest.mark.parametrize(
    "rel",
    [
        "plugins/k2-memory-hooks/hooks/__pycache__/planted.cpython-313.pyc",
        "plugins/k2-memory-hooks/hooks/stray.pyc",
        "plugins/k2/.pytest_cache/v/cache/lastfailed",
    ],
)
def test_rejects_packed_build_output(package_copy, rel):
    """Without the negations, the validator itself refuses build/cache output."""
    _edit_json(package_copy / "package.json", lambda d: d.update(files=[f for f in d["files"] if not f.startswith("!")]))
    target = package_copy / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x00bytecode")
    result = _run(package_copy)
    assert result.returncode != 0
    assert f"{rel}: build or cache output must never be packed" in result.stderr


@needs_npm
def test_rejects_a_packed_file_git_does_not_track(package_copy):
    """In a git checkout, every packed file must be tracked by git."""
    git = lambda *a: subprocess.run(["git", *a], cwd=package_copy, capture_output=True, text=True, check=True)  # noqa: E731
    git("init", "-q")
    git("add", "-A")
    assert _run(package_copy).returncode == 0
    (package_copy / "plugins" / "k2" / "untracked.md").write_text("not in git\n", encoding="utf-8")
    result = _run(package_copy)
    assert result.returncode != 0
    assert "plugins/k2/untracked.md: packed but not tracked by git" in result.stderr


@needs_npm
def test_rejects_a_plugin_outside_the_pinned_set(package_copy):
    """Adding a plugin to the npm mirror is a deliberate edit to the validator."""
    extra = package_copy / "plugins" / "extra" / ".claude-plugin"
    extra.mkdir(parents=True)
    (extra / "plugin.json").write_text('{"name": "extra", "version": "0.4.0"}\n', encoding="utf-8")
    _edit_json(
        package_copy / ".claude-plugin" / "marketplace.json",
        lambda d: d["plugins"].append({"name": "extra", "source": "./plugins/extra"}),
    )
    _edit_json(package_copy / "package.json", lambda d: d["files"].insert(0, "plugins/extra/"))
    result = _run(package_copy)
    assert result.returncode != 0
    assert "plugin ./plugins/extra is not in the npm mirror's pinned plugin set" in result.stderr


@needs_npm
def test_rejects_a_package_missing_a_listed_plugin(package_copy):
    # A marketplace entry whose directory is not packed would install from git
    # but not from npm.
    _edit_json(package_copy / "package.json", lambda d: d["files"].remove("plugins/k2-memory-hooks/"))
    result = _run(package_copy)
    assert result.returncode != 0
    assert "plugins/k2-memory-hooks/.claude-plugin/plugin.json: missing from the package" in result.stderr


# --------------------------------------------------------------------------
# publish-npm.yml
# --------------------------------------------------------------------------


def _publish_job() -> dict:
    jobs = _workflow("publish-npm.yml")["jobs"]
    assert set(jobs) == {"publish"}
    return jobs["publish"]


def test_publish_triggers_only_when_release_yml_calls_it():
    # No tag trigger of its own: a hand-pushed tag reaches npm only through
    # release.yml, after the GitHub Release succeeded.
    on = _workflow("publish-npm.yml")["on"]
    assert set(on) == {"workflow_call"}
    assert on["workflow_call"]["inputs"] == {
        "tag": {"description": on["workflow_call"]["inputs"]["tag"]["description"], "required": True, "type": "string"}
    }
    assert "secrets" not in on["workflow_call"]


def test_publish_permissions_and_environment():
    wf = _workflow("publish-npm.yml")
    assert wf["permissions"] == {"contents": "read"}
    job = _publish_job()
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["environment"] == "npm-publish"
    assert job["concurrency"] == {"group": "publish-npm-${{ inputs.tag }}", "cancel-in-progress": False}
    assert job["env"]["TAG"] == "${{ inputs.tag }}"
    assert job["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_no_npm_token_anywhere():
    """Trusted publishing only: no workflow names a long-lived npm token."""
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "NPM_TOKEN" not in text, path.name
        assert "NODE_AUTH_TOKEN" not in text, path.name
        assert "_authToken" not in text, path.name


def _index(steps, predicate, what):
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    raise AssertionError(f"publish-npm.yml: no step {what}")


def test_publish_steps_run_in_order():
    steps = _publish_job()["steps"]
    run = lambda needle: (lambda s: needle in s.get("run", ""))  # noqa: E731
    uses = lambda needle: (lambda s: s.get("uses", "").startswith(needle))  # noqa: E731
    order = [
        _index(steps, uses("actions/checkout@"), "checkout"),
        _index(steps, run('tests/version_consistency.py --tag "$TAG"'), "version gate"),
        _index(steps, run("git merge-base --is-ancestor"), "main ancestry check"),
        _index(steps, run("pytest tests/"), "pytest"),
        # After pytest: the last look at the tree before publish.
        _index(steps, run("scripts/validate-npm-package.sh"), "validator"),
        _index(steps, run("npm view"), "already-published check"),
        _index(steps, run("npm publish"), "npm publish"),
    ]
    assert order == sorted(order), order

    checkout = steps[order[0]]["with"]
    assert checkout["ref"] == "refs/tags/${{ inputs.tag }}"
    assert checkout["persist-credentials"] is False

    publish = steps[order[-1]]
    assert publish["run"] == "npm publish --provenance --access public --ignore-scripts"
    assert publish["if"] == "steps.existing.outputs.published == 'false'"
    assert "env" not in publish
    # Nothing is published by any other step.
    assert sum("npm publish" in s.get("run", "") for s in steps) == 1
    # Nothing but checkout and interpreter setup runs before the version gate.
    assert all("run" not in s for s in steps[: order[1]])


def test_publish_uses_an_npm_that_supports_trusted_publishing():
    version = _workflow("publish-npm.yml")["env"]["NPM_VERSION"]
    major, minor, patch = (int(x) for x in version.split("."))
    assert (major, minor, patch) >= (11, 5, 1)
    assert any('npm install -g "npm@${NPM_VERSION}"' in s.get("run", "") for s in _publish_job()["steps"])


# --------------------------------------------------------------------------
# validate-npm.yml
# --------------------------------------------------------------------------


def test_validate_npm_runs_on_pull_requests_only_and_read_only():
    wf = _workflow("validate-npm.yml")
    assert set(wf["on"]) == {"pull_request"}
    assert wf["permissions"] == {"contents": "read"}
    for job in wf["jobs"].values():
        assert "permissions" not in job
        assert "environment" not in job
    text = (WORKFLOWS / "validate-npm.yml").read_text(encoding="utf-8")
    assert "id-token" not in text
    assert "npm publish" not in text
    assert "secrets." not in text


def test_validate_npm_runs_the_validator_and_its_fixtures():
    (job,) = _workflow("validate-npm.yml")["jobs"].values()
    runs = [s.get("run", "") for s in job["steps"]]
    assert "scripts/validate-npm-package.sh" in runs
    assert any("pytest tests/test_validate_npm_package.py" in r for r in runs)
    for step in job["steps"]:
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step["with"]["persist-credentials"] is False


def test_validate_npm_pins_the_same_cli_versions_as_validate():
    ours = _workflow("validate-npm.yml")["env"]
    theirs = _workflow("validate.yml")["env"]
    for key in ("CLAUDE_CODE_VERSION", "CODEX_VERSION"):
        assert ours[key] == theirs[key]
        assert re.fullmatch(r"\d+\.\d+\.\d+", ours[key])


def test_only_publish_npm_can_publish():
    for path in WORKFLOWS.glob("*.yml"):
        if path.name != "publish-npm.yml":
            assert "npm publish" not in path.read_text(encoding="utf-8"), path.name


# --------------------------------------------------------------------------
# README section
# --------------------------------------------------------------------------


def _npm_section() -> str:
    match = re.search(r"^## Install from npm \(Codex\)$(.*?)(?=^## )", README, re.M | re.S)
    assert match, "README.md has no '## Install from npm (Codex)' section"
    return match.group(1)


def test_readme_names_the_package_from_package_json_with_a_pinned_version():
    section = _npm_section()
    assert f"{PACKAGE['name']}@{PACKAGE['version']}" in section
    assert f"{PACKAGE['name']}@latest" not in section


@pytest.mark.parametrize(
    "needle",
    [
        "--ignore-scripts",
        "codex plugin marketplace add ~/.k2-npm/node_modules/",
        "codex plugin add k2@k2",
        "npm audit signatures",
        "trusted publishing",
        "release.yml",
        "publish-npm.yml",
        "npm-publish",
    ],
)
def test_readme_npm_section_has(needle):
    assert needle in _npm_section()


def test_readme_npm_section_points_claude_code_at_git():
    section = _npm_section()
    assert "Claude Code" in section and "claude plugin marketplace add K2-Rocket-Apps/k2" in section
