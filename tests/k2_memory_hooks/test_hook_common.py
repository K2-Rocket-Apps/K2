"""Unit tests for plugins/k2-memory-hooks/hooks/lib/hook_common.py and the two
hook scripts.

The redaction, truncation, derive_* and read_stdin_event cases are ported
from the original implementation's test-suite with their assertions
unchanged; only placeholder paths and repo names were swapped for neutral
ones. The send() and script tests below them are specific to the k2-agent
transport.
"""
import importlib.util
import io
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / "plugins" / "k2-memory-hooks" / "hooks"
sys.path.insert(0, str(HOOKS_DIR / "lib"))

from hook_common import (  # noqa: E402
    derive_agent_id,
    derive_branch,
    derive_repo,
    read_stdin_event,
    redact,
    redact_and_truncate,
    truncate,
)
import hook_common  # noqa: E402


# --------------------------------------------------------------------------
# Ported cases
# --------------------------------------------------------------------------


def test_redact_strips_github_tokens():
    assert "ghp_" not in redact("token=ghp_" + "a" * 36)


def test_redact_strips_url_credentials():
    result = redact("https://x-access-token:ghs_abc123def456@github.com/example-org/example.git")
    assert "ghs_abc123def456" not in result
    assert "***:***@github.com" in result


def test_redact_strips_pem_private_key_blocks():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
    result = redact(f"some log line\n{pem}\nmore log")
    assert "MIIEowIBAAKCAQEA" not in result
    assert "some log line" in result and "more log" in result


def test_redact_strips_bearer_authorization_headers():
    result = redact("Authorization: Bearer sk-abcdef0123456789abcdef0123456789")
    assert "sk-abcdef0123456789abcdef0123456789" not in result


def test_redact_strips_aws_access_key_ids():
    result = redact("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert "AKIAIOSFODNN7EXAMPLE" not in result


def test_redact_strips_aws_sts_temporary_access_key_ids():
    result = redact("AWS_ACCESS_KEY_ID=ASIAIOSFODNN7EXAMPLE")
    assert "ASIAIOSFODNN7EXAMPLE" not in result


def test_redact_strips_aws_secret_access_keys():
    result = redact("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in result


def test_redact_strips_aws_secret_access_key_glued_to_a_trailing_char():
    result = redact("key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEYx and more text")
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in result


def test_redact_strips_aws_secret_access_key_embedded_with_no_separator():
    result = redact("prefixwJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEYsuffix")
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in result


def test_redact_strips_generic_long_opaque_tokens():
    result = redact("api_key: Z9x7Q2w8E5r1T6y3U0i4O7p2A5s8D1f4G7h0J3k6L9")
    assert "Z9x7Q2w8E5r1T6y3U0i4O7p2A5s8D1f4G7h0J3k6L9" not in result


def test_redact_leaves_ordinary_test_output_untouched():
    text = "FAIL: test_it_does_the_thing\nExpected 200, got 500\nat FooTest.php:42"
    assert redact(text) == text


def test_redact_leaves_ordinary_long_identifiers_untouched():
    path_segment = "example-tools-marketplace-worktrees"
    git_sha = "daefb1e0912c45fd1162baa5d950d412f7f4e5bf"
    request_id = "550e8400-e29b-41d4-a716-446655440000"
    text = f"cwd=/home/dev/code/{path_segment} sha={git_sha} request_id={request_id}"
    result = redact(text)
    assert path_segment in result
    assert git_sha in result
    assert request_id in result


def test_redact_strips_mixed_case_uuid_shaped_secret():
    result = redact("token=DeadBeef-CaFe-BaBe-FaCe-0123456789ab")
    assert "DeadBeef-CaFe-BaBe-FaCe-0123456789ab" not in result


def test_redact_strips_all_lowercase_hex_secret():
    result = redact("api_key=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4")
    assert "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4" not in result


def test_redact_strips_all_uppercase_secret():
    result = redact("SECRET=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in result


def test_redact_strips_all_lowercase_base32_secret():
    result = redact("token=abcdefghijklmnopqrstuvwxyz234567")
    assert "abcdefghijklmnopqrstuvwxyz234567" not in result


def test_redact_strips_numeric_only_secret():
    result = redact("pin=12345678901234567890123456789012")
    assert "12345678901234567890123456789012" not in result


def test_redact_strips_short_secret_containing_slash():
    secret = "aB3xK9mQ2pL7vN4w/Z8tY1rC6uE0sD5fGhJ2"
    assert len(secret) == 36
    result = redact(f"api_key={secret}")
    assert secret not in result


def test_redact_strips_short_secret_containing_plus():
    secret = "aB3xK9+Q2pL7vN4w/Z8tY1rC6uE0sD5fGhJ2"
    assert len(secret) == 36
    result = redact(f"token={secret}")
    assert secret not in result


def _build_secret_shape(length: int, case: str, punctuation: str) -> str:
    """Builds a synthetic token of exactly `length` chars matching the
    given case ('mixed'/'lower'/'upper') and punctuation
    ('slash'/'plus'/'none'). Cycles through the FULL 26-letter alphabet
    (not just a-f) so a 'lower'/'none' token of length 40 or 64 is never
    accidentally indistinguishable from a real git SHA — it always
    contains letters outside the hex range, which is exactly the
    property _GIT_SHA_SHAPE_RE relies on to tell them apart."""
    if case == "lower":
        letters = "abcdefghijklmnopqrstuvwxyz"
    elif case == "upper":
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    else:
        letters = "AbCdEfGhIjKlMnOpQrStUvWxYz"
    pool = letters + "0123456789"
    chars = [pool[i % len(pool)] for i in range(length)]
    if punctuation == "slash":
        chars[length // 2] = "/"
    elif punctuation == "plus":
        chars[length // 2] = "+"
    return "".join(chars)


_SWEEP_CASES = list(itertools.product(["mixed", "lower", "upper"], ["slash", "plus", "none"], [32, 36, 40, 64]))


@pytest.mark.parametrize("case,punctuation,length", _SWEEP_CASES, ids=[f"{c}-{p}-{n}" for c, p, n in _SWEEP_CASES])
def test_redact_strips_every_case_and_punctuation_and_length_combination(case, punctuation, length):
    secret = _build_secret_shape(length, case, punctuation)
    assert len(secret) == length
    result = redact(f"secret={secret}")

    assert secret not in result

    if punctuation != "none":
        half = length // 2
        before, after = secret[:half], secret[half + 1 :]
        assert before not in result
        assert after not in result


_SAFE_SHAPES = {
    "sha1_40_lowercase_hex": "daefb1e0912c45fd1162baa5d950d412f7f4e5bf",
    "sha256_64_lowercase_hex": "71f1f8d5336a2f57e8a394a82722070bd40c80e1024544892c50268840c05be3",
    "canonical_uuid": "550e8400-e29b-41d4-a716-446655440000",
    "kebab_case_path_segment": "example-tools-marketplace-worktrees",
    "short_laravel_fqcn": "App/Services/Foo/Bar",
}


@pytest.mark.parametrize("shape_name", sorted(_SAFE_SHAPES))
def test_redact_leaves_non_secret_shapes_untouched_across_the_sweep(shape_name):
    token = _SAFE_SHAPES[shape_name]
    result = redact(f"x={token}")
    assert token in result
    assert result == f"x={token}"


def test_truncate_caps_line_count():
    text = "\n".join(f"line {i}" for i in range(500))
    result = truncate(text, max_lines=100, max_chars=100_000)
    lines = result.splitlines()
    assert len(lines) <= 101
    assert "line 0" in result
    assert "line 499" not in result


def test_truncate_caps_character_count():
    result = truncate("x" * 10_000, max_lines=100_000, max_chars=4000)
    assert len(result) <= 4000 + len("... [truncated]")


def test_derive_repo_uses_cwd_basename():
    assert derive_repo("/home/dev/code/example-repo") == "example-repo"
    assert derive_repo("/home/dev/code/example-repo/") == "example-repo"
    assert derive_repo("") is None


def test_derive_branch_returns_none_outside_a_git_repo(tmp_path):
    assert derive_branch(str(tmp_path)) is None


def test_derive_branch_reads_the_real_branch_name(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "feat/test-branch", str(tmp_path)], check=True)
    assert derive_branch(str(tmp_path)) == "feat/test-branch"


def test_derive_agent_id_falls_back_to_user_at_host_outside_git(tmp_path):
    result = derive_agent_id(str(tmp_path))
    assert "@" in result


def test_read_stdin_event_returns_empty_dict_on_malformed_json(monkeypatch):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert read_stdin_event() == {}


def test_read_stdin_event_parses_real_json(monkeypatch):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"cwd": "/tmp/x"}'))
    assert read_stdin_event() == {"cwd": "/tmp/x"}


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " true "])
def test_is_cloud_session_truthy_values(monkeypatch, value):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", value)
    assert hook_common.is_cloud_session() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_is_cloud_session_falsy_values(monkeypatch, value):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", value)
    assert hook_common.is_cloud_session() is False


def test_is_cloud_session_false_when_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    assert hook_common.is_cloud_session() is False


# --------------------------------------------------------------------------
# send(): the k2-agent transport
# --------------------------------------------------------------------------


class _Recorder:
    """Stands in for subprocess.run and records every call."""

    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def test_send_runs_k2_agent_telemetry_send_with_the_payload_on_stdin(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    run = _Recorder()
    monkeypatch.setattr(hook_common.subprocess, "run", run)
    hook_common.send("heartbeat", {"repo": "r", "branch": "b", "agent_id": "a"})
    assert len(run.calls) == 1
    args, kwargs = run.calls[0]
    assert args == ["k2-agent", "telemetry", "send", "heartbeat"]
    assert json.loads(kwargs["input"]) == {"repo": "r", "branch": "b", "agent_id": "a"}
    assert kwargs["timeout"] == 6
    assert kwargs["capture_output"] is True


@pytest.mark.parametrize("value", ["1", "true"])
def test_send_does_nothing_in_a_cloud_session(monkeypatch, value):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", value)
    run = _Recorder()
    monkeypatch.setattr(hook_common.subprocess, "run", run)
    hook_common.send("friction", {"repo": "r"})
    assert run.calls == []


@pytest.mark.parametrize(
    "exc",
    [FileNotFoundError("k2-agent"), subprocess.TimeoutExpired("k2-agent", 6), PermissionError("x"), RuntimeError("x")],
    ids=["missing", "timeout", "permission", "anything"],
)
def test_send_swallows_every_exception(monkeypatch, exc):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.setattr(hook_common.subprocess, "run", _Recorder(raises=exc))
    hook_common.send("heartbeat", {"repo": "r"})


def test_send_swallows_a_non_serializable_payload(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    run = _Recorder()
    monkeypatch.setattr(hook_common.subprocess, "run", run)
    hook_common.send("heartbeat", {"x": object()})
    assert run.calls == []


def test_hook_common_has_no_network_or_credential_surface():
    source = (HOOKS_DIR / "lib" / "hook_common.py").read_text(encoding="utf-8")
    for banned in ("urllib", "import requests", "http.client", "create_connection", "def forward", "read_token",
                   "hook_token", "base_url", "claude_plugin_data"):
        assert banned not in source.lower(), banned


# --------------------------------------------------------------------------
# The hook scripts
# --------------------------------------------------------------------------


def _load_script(name):
    spec = importlib.util.spec_from_file_location(f"k2mh_{name}", HOOKS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git_repo(path: Path, branch: str = "feat/x") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    return path


def _run_main(monkeypatch, capsys, script, event):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    code = _load_script(script).main()
    out = capsys.readouterr()
    return code, out.out, out.err


class _AgentOnly:
    """subprocess.run that lets git through and makes k2-agent behave as given."""

    def __init__(self, raises=None):
        self.agent_calls = []
        self.raises = raises
        self.real = subprocess.run

    def __call__(self, args, **kwargs):
        if args and args[0] == "k2-agent":
            self.agent_calls.append((list(args), kwargs))
            if self.raises is not None:
                raise self.raises
            return subprocess.CompletedProcess(args, 0, stdout="ignored output", stderr="ignored")
        return self.real(args, **kwargs)


def _friction_event(cwd, output="FAIL"):
    return {"cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": "pytest -q"}, "tool_output": output}


@pytest.mark.parametrize("script", ["heartbeat", "friction"])
def test_scripts_exit_0_and_never_call_subprocess_in_cloud(monkeypatch, capsys, tmp_path, script):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "1")
    run = _Recorder()
    monkeypatch.setattr(subprocess, "run", run)
    repo = tmp_path / "repo"
    repo.mkdir()
    event = _friction_event(repo) if script == "friction" else {"cwd": str(repo)}
    code, out, err = _run_main(monkeypatch, capsys, script, event)
    assert code == 0
    assert run.calls == []
    assert out == ""


@pytest.mark.parametrize("script", ["heartbeat", "friction"])
@pytest.mark.parametrize(
    "exc", [FileNotFoundError("k2-agent"), subprocess.TimeoutExpired("k2-agent", 6)], ids=["missing", "timeout"]
)
def test_scripts_exit_0_silently_when_k2_agent_is_missing_or_slow(monkeypatch, capsys, tmp_path, script, exc):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    repo = _git_repo(tmp_path / "repo")
    run = _AgentOnly(raises=exc)
    monkeypatch.setattr(subprocess, "run", run)
    event = _friction_event(repo) if script == "friction" else {"cwd": str(repo)}
    code, out, err = _run_main(monkeypatch, capsys, script, event)
    assert code == 0
    assert out == ""
    assert len(run.agent_calls) == 1, "k2-agent should have been attempted exactly once"


@pytest.mark.parametrize("script", ["heartbeat", "friction"])
def test_scripts_print_nothing_even_when_k2_agent_answers(monkeypatch, capsys, tmp_path, script):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setattr(subprocess, "run", _AgentOnly())
    event = _friction_event(repo) if script == "friction" else {"cwd": str(repo)}
    code, out, err = _run_main(monkeypatch, capsys, script, event)
    assert (code, out, err) == (0, "", "")


@pytest.mark.parametrize("script", ["heartbeat", "friction"])
@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", '{"cwd": 5}'])
def test_scripts_exit_0_on_malformed_events(monkeypatch, capsys, script, stdin):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.setattr(subprocess, "run", _AgentOnly(raises=FileNotFoundError("k2-agent")))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    assert _load_script(script).main() == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("script", ["heartbeat", "friction"])
def test_scripts_exit_0_as_real_subprocesses_without_k2_agent(tmp_path, script):
    repo = _git_repo(tmp_path / "repo")
    git_dir = os.path.dirname(subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
    env = {"PATH": git_dir, "HOME": str(tmp_path)}
    event = _friction_event(repo) if script == "friction" else {"cwd": str(repo)}
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / f"{script}.py")],
        input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize("script", ["heartbeat", "friction"])
def test_scripts_exit_0_as_real_subprocesses_in_cloud(tmp_path, script):
    env = {**os.environ, "CLAUDE_CODE_REMOTE": "1"}
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / f"{script}.py")],
        input=json.dumps({"cwd": str(tmp_path)}), capture_output=True, text=True, env=env, timeout=30,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


# heartbeat ------------------------------------------------------------------


def test_heartbeat_sends_repo_branch_and_agent_id(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    repo = _git_repo(tmp_path / "my-repo", branch="feat/42-thing")
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "dev@example.invalid"], check=True)
    sent = []
    monkeypatch.setattr(hook_common, "send", lambda kind, payload: sent.append((kind, payload)))
    code, out, _ = _run_main(monkeypatch, capsys, "heartbeat", {"cwd": str(repo)})
    assert code == 0 and out == ""
    assert sent == [("heartbeat", {"repo": "my-repo", "branch": "feat/42-thing", "agent_id": "dev@example.invalid"})]


def test_heartbeat_skips_a_detached_head(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    repo = _git_repo(tmp_path / "repo")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run([*git, "checkout", "-q", "--detach"], check=True)
    assert derive_branch(str(repo)) is None
    sent = []
    monkeypatch.setattr(hook_common, "send", lambda kind, payload: sent.append((kind, payload)))
    code, out, _ = _run_main(monkeypatch, capsys, "heartbeat", {"cwd": str(repo)})
    assert code == 0 and out == ""
    assert sent == []


def test_heartbeat_skips_outside_a_git_repo_and_without_cwd(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    sent = []
    monkeypatch.setattr(hook_common, "send", lambda kind, payload: sent.append((kind, payload)))
    for event in ({"cwd": str(tmp_path)}, {}):
        assert _run_main(monkeypatch, capsys, "heartbeat", event)[0] == 0
    assert sent == []


# friction -------------------------------------------------------------------


GITHUB_TOKEN = "ghp_" + "Ab3dEf6hIj" * 3 + "Kl3mN6"
AWS_KEY_ID = "AKIA" + "IOSFODNN7EXAMPLE"


def _capture_friction(monkeypatch, capsys, event):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    sent = []
    monkeypatch.setattr(hook_common, "send", lambda kind, payload: sent.append((kind, payload)))
    code, out, _ = _run_main(monkeypatch, capsys, "friction", event)
    assert code == 0 and out == ""
    assert len(sent) == 1 and sent[0][0] == "friction"
    return sent[0][1]


def test_friction_redacts_secrets_from_tool_output(monkeypatch, capsys, tmp_path):
    assert len(GITHUB_TOKEN) == 4 + 36 and GITHUB_TOKEN[4:].isalnum()
    output = f"FAILED test_login\nGITHUB_TOKEN={GITHUB_TOKEN}\nAWS_ACCESS_KEY_ID={AWS_KEY_ID}\n"
    payload = _capture_friction(monkeypatch, capsys, _friction_event(tmp_path / "my-repo", output))
    assert set(payload) == {"repo", "file", "description", "originating_tool"}
    assert payload["repo"] == "my-repo"
    assert payload["originating_tool"] == "Bash"
    assert "***" in payload["description"]
    blob = json.dumps(payload)
    assert GITHUB_TOKEN not in blob
    assert AWS_KEY_ID not in blob
    assert "FAILED test_login" in payload["description"]


def test_friction_redacts_a_secret_straddling_the_file_hint_cutoff(monkeypatch, capsys, tmp_path):
    prefix = "pytest -q"
    while len(prefix) < 500:
        prefix += " tests/test_a.py"
    prefix += " "
    command = prefix + GITHUB_TOKEN + " tests/"
    assert len(prefix) < 512 < len(prefix) + len(GITHUB_TOKEN)
    event = {"cwd": str(tmp_path / "repo"), "tool_name": "Bash", "tool_input": {"command": command}, "tool_output": "F"}
    payload = _capture_friction(monkeypatch, capsys, event)
    assert len(payload["file"]) <= 512 + len("... [truncated]")
    assert GITHUB_TOKEN[:8] not in payload["file"]
    assert "ghp_" not in payload["file"]
    assert payload["file"].startswith(prefix)


def test_friction_redacts_before_truncating_the_description(monkeypatch, capsys, tmp_path):
    output = "x" * 3990 + " " + GITHUB_TOKEN
    payload = _capture_friction(monkeypatch, capsys, _friction_event(tmp_path / "repo", output))
    assert "ghp_" not in payload["description"]
    assert redact_and_truncate(output) == payload["description"]


def test_friction_prefers_file_path_and_falls_back_to_unknown(monkeypatch, capsys, tmp_path):
    event = {"cwd": str(tmp_path / "repo"), "tool_input": {"file_path": "src/a.py"}, "tool_output": "F"}
    assert _capture_friction(monkeypatch, capsys, event)["file"] == "src/a.py"
    event = {"cwd": str(tmp_path / "repo"), "tool_input": {}, "tool_output": "F"}
    assert _capture_friction(monkeypatch, capsys, event)["file"] == "unknown"


def test_friction_reads_tool_response_when_tool_output_is_absent(monkeypatch, capsys, tmp_path):
    event = {"cwd": str(tmp_path / "repo"), "tool_input": {"command": "pytest"}, "tool_response": f"E {AWS_KEY_ID}"}
    payload = _capture_friction(monkeypatch, capsys, event)
    assert AWS_KEY_ID not in payload["description"] and "***" in payload["description"]


def test_friction_skips_without_cwd(monkeypatch, capsys):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    sent = []
    monkeypatch.setattr(hook_common, "send", lambda kind, payload: sent.append((kind, payload)))
    assert _run_main(monkeypatch, capsys, "friction", {"tool_output": "F"})[0] == 0
    assert sent == []
