"""Tests for version_consistency.py, the release workflow, the version-bump CI
job and the README install section."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import version_consistency as vc
from version_consistency import changelog_section, check, requires_version_bump

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _market(version):
    return {"name": "k2", "metadata": {"version": version}, "plugins": [{"name": "k2"}]}


def _plugin(version):
    return {"name": "k2", "version": version}


# --------------------------------------------------------------------------
# check()
# --------------------------------------------------------------------------


def test_check_accepts_matching_tag_and_versions():
    assert check("v0.2.0", _market("0.2.0"), _plugin("0.2.0"), _plugin("0.2.0")) == []


def test_check_rejects_codex_manifest_at_a_different_version():
    assert check("v0.2.0", _market("0.2.0"), _plugin("0.2.0"), _plugin("0.2.1"))


@pytest.mark.parametrize("which", ["marketplace", "claude"])
def test_check_rejects_any_single_manifest_out_of_step(which):
    market = _market("0.2.1" if which == "marketplace" else "0.2.0")
    claude = _plugin("0.2.1" if which == "claude" else "0.2.0")
    assert check("v0.2.0", market, claude, _plugin("0.2.0"))


def test_check_rejects_tag_without_v_prefix():
    assert check("0.2.0", _market("0.2.0"), _plugin("0.2.0"), _plugin("0.2.0"))


@pytest.mark.parametrize("tag", ["v0.2.1", "v0.2", "v0.2.0-rc1", "release-0.2.0", "V0.2.0", ""])
def test_check_rejects_tag_that_is_not_exactly_v_plus_version(tag):
    assert check(tag, _market("0.2.0"), _plugin("0.2.0"), _plugin("0.2.0"))


def test_check_rejects_non_semver_versions_even_when_tag_matches():
    assert check("v0.2.0-beta", _market("0.2.0-beta"), _plugin("0.2.0-beta"), _plugin("0.2.0-beta"))


def test_check_rejects_missing_version_keys():
    assert check("v0.2.0", {"name": "k2"}, _plugin("0.2.0"), _plugin("0.2.0"))
    assert check("v0.2.0", _market("0.2.0"), {}, _plugin("0.2.0"))


def test_check_passes_for_the_real_repo_at_its_current_version():
    version = json.loads((REPO_ROOT / vc.CLAUDE_PLUGIN_JSON).read_text())["version"]
    assert vc.release_errors(REPO_ROOT, f"v{version}") == []
    assert vc.release_errors(REPO_ROOT, "v999.0.0")


# --------------------------------------------------------------------------
# PR mode: requires_version_bump()
# --------------------------------------------------------------------------


def test_pr_mode_rejects_skill_change_without_bump():
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], "0.3.0", "0.3.0")


def test_pr_mode_rejects_version_decrease():
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], "0.3.0", "0.2.9")


def test_pr_mode_compares_numerically_not_lexically():
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], "0.10.0", "0.9.0")
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], "0.9.0", "0.10.0") == []


@pytest.mark.parametrize("head", ["0.3.1", "0.4.0", "1.0.0"])
def test_pr_mode_accepts_change_with_increase(head):
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], "0.3.0", head) == []


@pytest.mark.parametrize(
    "path",
    ["plugins/k2/.codex-plugin/plugin.json", "plugins/k2/README.md", "plugins/k2/skills/a/b/c.md"],
)
def test_pr_mode_covers_everything_under_the_plugin(path):
    assert requires_version_bump([path], "0.3.0", "0.3.0")


@pytest.mark.parametrize(
    "path", ["README.md", "CHANGELOG.md", "tests/x.py", ".github/workflows/validate.yml", "plugins/k2x/a.md"]
)
def test_pr_mode_ignores_changes_outside_the_plugin(path):
    assert requires_version_bump([path], "0.3.0", "0.3.0") == []


def test_pr_mode_skips_when_plugin_absent_at_base():
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], None, "0.1.0") == []


def test_pr_mode_rejects_non_semver_head():
    assert requires_version_bump(["plugins/k2/skills/x/SKILL.md"], "0.3.0", "0.3.1-dev")


# PR mode end to end against a throwaway git repo (the fixture diff).


def _git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=root, check=True, capture_output=True,
    )


@pytest.fixture
def fixture_repo(tmp_path):
    root = tmp_path / "repo"
    for rel in (vc.MARKETPLACE_JSON, vc.CLAUDE_PLUGIN_JSON, vc.CODEX_PLUGIN_JSON, vc.CHANGELOG):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, root / rel)
    skill = root / "plugins" / "k2" / "skills" / "x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("v1\n")
    _git(root, "init", "-q", "-b", "base")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "head")
    return root


def _bump(root, version):
    for rel in (vc.CLAUDE_PLUGIN_JSON, vc.CODEX_PLUGIN_JSON):
        data = json.loads((root / rel).read_text())
        data["version"] = version
        (root / rel).write_text(json.dumps(data, indent=2) + "\n")
    data = json.loads((root / vc.MARKETPLACE_JSON).read_text())
    data["metadata"]["version"] = version
    (root / vc.MARKETPLACE_JSON).write_text(json.dumps(data, indent=2) + "\n")


def test_pr_mode_cli_fails_on_skill_diff_without_bump(fixture_repo, capsys):
    (fixture_repo / "plugins/k2/skills/x/SKILL.md").write_text("v2\n")
    _git(fixture_repo, "commit", "-qam", "change skill")
    assert vc.pr_errors(fixture_repo, "base", "HEAD")
    assert vc.main(["--base", "base"], root=fixture_repo) == 1
    assert "plugins/k2/skills/x/SKILL.md" in capsys.readouterr().err


def test_pr_mode_cli_passes_on_skill_diff_with_bump(fixture_repo):
    (fixture_repo / "plugins/k2/skills/x/SKILL.md").write_text("v2\n")
    _bump(fixture_repo, "99.0.0")
    _git(fixture_repo, "commit", "-qam", "change skill and bump")
    assert vc.pr_errors(fixture_repo, "base", "HEAD") == []
    assert vc.main(["--base", "base"], root=fixture_repo) == 0


def test_pr_mode_cli_passes_when_plugin_untouched(fixture_repo):
    (fixture_repo / "CHANGELOG.md").write_text("# Changelog\n")
    _git(fixture_repo, "commit", "-qam", "docs only")
    assert vc.main(["--base", "base"], root=fixture_repo) == 0


def test_release_cli_fails_on_mismatched_tag(fixture_repo):
    assert vc.main(["--tag", "v999.0.0"], root=fixture_repo) == 1


def test_release_cli_fails_without_changelog_section(fixture_repo):
    _bump(fixture_repo, "99.0.0")
    assert vc.main(["--tag", "v99.0.0"], root=fixture_repo) == 1


# --------------------------------------------------------------------------
# CHANGELOG
# --------------------------------------------------------------------------


def test_changelog_section_extracts_only_the_named_version():
    text = "# Changelog\n\n## v0.4.0\n\nnew\n\n### Fixed\n\n- a\n\n## v0.3.0\n\nold\n"
    assert changelog_section(text, "v0.4.0") == "new\n\n### Fixed\n\n- a\n"
    assert changelog_section(text, "v0.3.0") == "old\n"
    assert changelog_section(text, "v0.5.0") is None
    assert changelog_section("## v1.0.0\n\n## v0.9.0\nx\n", "v1.0.0") is None


def test_changelog_has_an_entry_for_the_current_version():
    version = json.loads((REPO_ROOT / vc.CLAUDE_PLUGIN_JSON).read_text())["version"]
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## v{re.escape(version)}$", text, re.M)
    assert changelog_section(text, f"v{version}")


def test_notes_cli_prints_the_section(capsys):
    version = json.loads((REPO_ROOT / vc.CLAUDE_PLUGIN_JSON).read_text())["version"]
    assert vc.main(["--notes", f"v{version}"]) == 0
    assert capsys.readouterr().out.strip()
    assert vc.main(["--notes", "v999.0.0"]) == 1


# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------


def _workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$")


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_every_action_is_pinned_to_a_full_sha_with_version_comment(name):
    for line in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines():
        match = USES_RE.match(line)
        if not match:
            continue
        ref, rest = match.groups()
        if ref.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{name}: {ref} not pinned to a full SHA"
        assert re.match(r"\s*#\s*v\d", rest), f"{name}: {ref} has no version comment"


@pytest.mark.parametrize("name", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_every_job_uses_a_github_hosted_runner(name):
    for job_name, job in _workflow(name)["jobs"].items():
        if "uses" in job:
            # A job that calls a reusable workflow has no runner of its own; the
            # called workflow is itself one of the files checked here.
            assert job["uses"].startswith("./.github/workflows/"), f"{name}:{job_name}"
            assert (REPO_ROOT / job["uses"]).is_file(), f"{name}:{job_name}"
            assert "runs-on" not in job, f"{name}:{job_name}"
            continue
        assert job["runs-on"] == "ubuntu-latest", f"{name}:{job_name}"


def test_release_triggers_on_v_tags_or_a_tag_dispatch_only():
    wf = _workflow("release.yml")
    assert set(wf["on"]) == {"push", "workflow_dispatch"}
    assert wf["on"]["push"] == {"tags": ["v[0-9]*"]}
    tag_input = wf["on"]["workflow_dispatch"]["inputs"]["tag"]
    assert tag_input["required"] is True and tag_input["type"] == "string"


def test_release_tag_comes_from_the_dispatch_input_or_the_pushed_ref():
    job = _workflow("release.yml")["jobs"]["release"]
    assert job["env"]["TAG"] == "${{ github.event_name == 'workflow_dispatch' && inputs.tag || github.ref_name }}"


def test_dispatch_creates_the_tag_only_after_the_version_gate():
    job = _workflow("release.yml")["jobs"]["release"]
    steps = job["steps"]
    gate = _step_index(steps, lambda s: 'tests/version_consistency.py --tag "$TAG"' in s.get("run", ""), "version gate")
    create = _step_index(steps, lambda s: 'tag -a "$TAG"' in s.get("run", ""), "tag creation")
    assert gate < create
    assert steps[create]["if"] == "github.event_name == 'workflow_dispatch'"
    assert "already exists" in steps[create]["run"]


def test_release_permissions_are_scoped_to_the_job():
    wf = _workflow("release.yml")
    assert wf["permissions"] == {"contents": "read"}
    job = wf["jobs"]["release"]
    assert job["permissions"] == {"contents": "write", "id-token": "write", "attestations": "write"}


def _step_index(steps, predicate, what):
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    raise AssertionError(f"release.yml: no step {what}")


def test_release_steps_run_in_order():
    job = _workflow("release.yml")["jobs"]["release"]
    steps = job["steps"]
    run = lambda needle: (lambda s: needle in s.get("run", ""))  # noqa: E731
    uses = lambda needle: (lambda s: s.get("uses", "").startswith(needle))  # noqa: E731

    order = [
        _step_index(steps, uses("actions/checkout@"), "checkout"),
        _step_index(steps, run('tests/version_consistency.py --tag "$TAG"'), "version gate"),
        _step_index(steps, run("git merge-base --is-ancestor"), "main ancestry check"),
        _step_index(steps, run("pytest tests/"), "pytest"),
        _step_index(steps, run("git archive --format=tar.gz"), "git archive"),
        _step_index(steps, run("> SHA256SUMS"), "SHA256SUMS"),
        _step_index(steps, uses("actions/attest-build-provenance@"), "attest"),
        _step_index(steps, run("gh release create"), "gh release create"),
    ]
    assert order == sorted(order), order

    archive = steps[order[4]]["run"]
    assert '--prefix="k2-${TAG}/"' in archive
    assert '-o "k2-${TAG}.tar.gz" "refs/tags/${TAG}"' in archive

    subjects = steps[order[6]]["with"]["subject-path"]
    assert "k2-${{ env.TAG }}.tar.gz" in subjects and "SHA256SUMS" in subjects

    publish = steps[order[7]]["run"]
    for flag in ("--verify-tag", "--latest", "--notes-file", "SHA256SUMS", 'k2-${TAG}.tar.gz'):
        assert flag in publish
    # The version gate is the first thing that can fail: nothing runs before it
    # except checkout and the interpreter setup (dispatch creates no tag before it).
    assert all("run" not in s for s in steps[: order[1]])


def test_validate_has_pull_request_only_version_bump_job():
    wf = _workflow("validate.yml")
    job = wf["jobs"]["version-bump"]
    assert job["if"] == "github.event_name == 'pull_request'"
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    assert any('version_consistency.py --base "origin/$BASE_REF"' in s.get("run", "") for s in job["steps"])
    assert wf["permissions"] == {"contents": "read"}


# --------------------------------------------------------------------------
# README install section
# --------------------------------------------------------------------------

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

REQUIRED_README_LINES = (
    "claude plugin marketplace add K2-Rocket-Apps/k2",
    "claude plugin install k2@k2 --scope user",
    "claude plugin marketplace add K2-Rocket-Apps/k2#v",
    "codex plugin marketplace add K2-Rocket-Apps/k2",
    "--ref v",
    "codex plugin add k2@k2",
    "codex plugin marketplace upgrade k2",
    'claude plugin marketplace add K2-Rocket-Apps/k2 && claude plugin install k2@k2 --scope user '
    '|| echo "k2 plugin install failed (see above)" >&2; exit 0',
    "gh attestation verify k2-vX.Y.Z.tar.gz --repo K2-Rocket-Apps/k2",
    "k2-connect",
    "autoUpdate",
)


@pytest.mark.parametrize("needle", REQUIRED_README_LINES)
def test_readme_install_section_has_command(needle):
    assert needle in README


@pytest.mark.parametrize("banned", ["| sh", "| bash", "iex", "mgw_", "git config"])
def test_readme_has_no_banned_string(banned):
    assert banned not in README.lower()


def test_readme_states_what_the_package_does_not_install():
    low = README.lower()
    for phrase in ("no mcp server", "no hooks", "no background jobs", "changes no git"):
        assert phrase in low


# --------------------------------------------------------------------------
# The opt-in hooks plugin rides the same version
# --------------------------------------------------------------------------


def test_check_holds_the_hook_plugin_to_the_same_version():
    assert check("v0.4.0", _market("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0")) == []
    assert check("v0.4.0", _market("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"), _plugin("0.3.0"))


def test_hook_plugin_content_change_requires_a_bump():
    path = "plugins/k2-memory-hooks/hooks/heartbeat.py"
    assert requires_version_bump([path], "0.4.0", "0.4.0")
    assert requires_version_bump([path], "0.4.0", "0.4.1") == []


def test_release_gate_reads_the_real_hook_plugin_manifest(tmp_path):
    root = tmp_path / "repo"
    for rel in (vc.MARKETPLACE_JSON, vc.CLAUDE_PLUGIN_JSON, vc.CODEX_PLUGIN_JSON, vc.HOOK_PLUGIN_JSON,
                vc.PACKAGE_JSON, vc.CHANGELOG):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, root / rel)
    version = json.loads((root / vc.MARKETPLACE_JSON).read_text())["metadata"]["version"]
    assert vc.release_errors(root, f"v{version}") == []
    data = json.loads((root / vc.HOOK_PLUGIN_JSON).read_text())
    data["version"] = "9.9.9"
    (root / vc.HOOK_PLUGIN_JSON).write_text(json.dumps(data))
    assert vc.release_errors(root, f"v{version}")


# --------------------------------------------------------------------------
# The npm mirror's package.json is a version source too
# --------------------------------------------------------------------------


def _package(version):
    return {"name": "@scope/k2", "version": version}


def test_check_accepts_package_json_at_the_tag_version():
    args = (_market("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"))
    assert check("v0.4.0", *args, _package("0.4.0")) == []


def test_check_rejects_package_json_that_differs_from_the_manifests():
    args = (_market("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"))
    errors = check("v0.4.0", *args, _package("0.4.1"))
    assert errors and any("package.json" in e for e in errors)


def test_check_rejects_package_json_that_differs_from_the_tag():
    # Every manifest and package.json agree with each other, but not with the tag.
    args = (_market("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"))
    assert check("v0.4.1", *args, _package("0.4.0"))


@pytest.mark.parametrize("bad", ["0.4", "0.4.0-rc1", None, 4])
def test_check_rejects_a_non_semver_package_json_version(bad):
    args = (_market("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"), _plugin("0.4.0"))
    assert check("v0.4.0", *args, _package(bad))


def test_real_package_json_matches_the_manifests():
    package = json.loads((REPO_ROOT / vc.PACKAGE_JSON).read_text())
    claude = json.loads((REPO_ROOT / vc.CLAUDE_PLUGIN_JSON).read_text())
    assert package["version"] == claude["version"]


def _release_fixture(tmp_path):
    root = tmp_path / "repo"
    for rel in (vc.MARKETPLACE_JSON, vc.CLAUDE_PLUGIN_JSON, vc.CODEX_PLUGIN_JSON, vc.HOOK_PLUGIN_JSON,
                vc.PACKAGE_JSON, vc.CHANGELOG):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, root / rel)
    version = json.loads((root / vc.MARKETPLACE_JSON).read_text())["metadata"]["version"]
    return root, version


def test_release_cli_fails_when_package_json_differs(tmp_path, capsys):
    root, version = _release_fixture(tmp_path)
    assert vc.main(["--tag", f"v{version}"], root=root) == 0
    data = json.loads((root / vc.PACKAGE_JSON).read_text())
    data["version"] = "9.9.9"
    (root / vc.PACKAGE_JSON).write_text(json.dumps(data))
    assert vc.main(["--tag", f"v{version}"], root=root) == 1
    assert "package.json version" in capsys.readouterr().err


def test_release_cli_fails_when_only_package_json_matches_the_tag(tmp_path):
    root, version = _release_fixture(tmp_path)
    data = json.loads((root / vc.PACKAGE_JSON).read_text())
    data["version"] = "9.9.9"
    (root / vc.PACKAGE_JSON).write_text(json.dumps(data))
    assert vc.main(["--tag", "v9.9.9"], root=root) == 1


def test_release_cli_fails_closed_without_package_json(tmp_path, capsys):
    root, version = _release_fixture(tmp_path)
    (root / vc.PACKAGE_JSON).unlink()
    assert vc.main(["--tag", f"v{version}"], root=root) == 1
    assert "package.json: missing" in capsys.readouterr().err


def _with_package(root, version):
    (root / vc.PACKAGE_JSON).write_text(json.dumps({"name": "@scope/k2", "version": version}) + "\n")


def test_pr_mode_fails_when_manifests_bump_without_package_json(fixture_repo, capsys):
    base_version = json.loads((fixture_repo / vc.CLAUDE_PLUGIN_JSON).read_text())["version"]
    _with_package(fixture_repo, base_version)
    _git(fixture_repo, "add", "-A")
    _git(fixture_repo, "commit", "-qm", "add package.json")
    (fixture_repo / "plugins/k2/skills/x/SKILL.md").write_text("v2\n")
    _bump(fixture_repo, "99.0.0")
    _git(fixture_repo, "commit", "-qam", "bump manifests only")
    assert vc.main(["--base", "base"], root=fixture_repo) == 1
    assert "package.json version" in capsys.readouterr().err
    _with_package(fixture_repo, "99.0.0")
    _git(fixture_repo, "commit", "-qam", "bump package.json too")
    assert vc.main(["--base", "base"], root=fixture_repo) == 0


# --------------------------------------------------------------------------
# release.yml hands the released tag to publish-npm.yml
# --------------------------------------------------------------------------


def test_release_has_exactly_the_release_and_npm_jobs():
    assert set(_workflow("release.yml")["jobs"]) == {"release", "npm"}


def test_release_npm_job_calls_publish_npm_after_the_release():
    job = _workflow("release.yml")["jobs"]["npm"]
    assert job["needs"] == "release"
    assert job["uses"] == "./.github/workflows/publish-npm.yml"
    assert job["with"] == {"tag": "${{ github.event_name == 'workflow_dispatch' && inputs.tag || github.ref_name }}"}
    # Same expression as the release job's TAG, so both publish the same tag.
    assert job["with"]["tag"] == _workflow("release.yml")["jobs"]["release"]["env"]["TAG"]
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert "secrets" not in job
