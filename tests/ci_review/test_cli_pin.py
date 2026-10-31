from __future__ import annotations

from pathlib import Path

import pytest

from dev10x.ci_review import cli_pin
from dev10x.ci_review.cli_pin import cli_binary, ensure_cli, resolve_cli_version
from dev10x.core.domain.common.result import ErrorResult, Result, SuccessResult, err, ok


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    values: dict[str, str | None] = {"--org": None, "--repo": None}
    monkeypatch.setattr(cli_pin, "_gh_variable", lambda *, scope_flag, scope: values[scope_flag])
    return values


@pytest.mark.parametrize(
    ("explicit", "env", "org", "repo", "expected"),
    [
        ("1.0.1", "2.0.0", "3.0.0", "4.0.0", "1.0.1"),
        (None, "2.0.0", "3.0.0", "4.0.0", "2.0.0"),
        (None, "", "3.0.0\n", "4.0.0", "3.0.0"),
        (None, None, None, "4.0.0", "4.0.0"),
    ],
    ids=["flag", "env", "org", "repo"],
)
def test_precedence(
    lookups: dict[str, str | None],
    explicit: str | None,
    env: str | None,
    org: str | None,
    repo: str | None,
    expected: str,
) -> None:
    lookups.update({"--org": org, "--repo": repo})
    environ = {} if env is None else {"CLAUDE_CLI_VERSION": env}

    result = resolve_cli_version(explicit=explicit, environ=environ, owner="o", repo="o/r")

    assert result == SuccessResult(value=expected)


def test_no_source_names_all_four(lookups: dict[str, str | None]) -> None:
    result = resolve_cli_version(explicit=None, environ={}, owner="o", repo="o/r")

    assert isinstance(result, ErrorResult)
    for source in ("--cli-version", "env var", "o organization", "o/r repository"):
        assert source in result.error


def test_refuses_path_like_version(lookups: dict[str, str | None]) -> None:
    result = resolve_cli_version(explicit="../x", environ={}, owner="o", repo="o/r")

    assert isinstance(result, ErrorResult)


@pytest.mark.parametrize(
    ("result", "expected"),
    [(ok("2.1.0"), "2.1.0"), (err("not found"), None)],
)
def test_gh_variable(
    monkeypatch: pytest.MonkeyPatch, result: Result[str], expected: str | None
) -> None:
    calls: list[list[str]] = []

    def fake_run(*, args: list[str], timeout: float) -> Result[str]:
        calls.append(args)
        return result

    monkeypatch.setattr(cli_pin, "run_checked", fake_run)

    assert cli_pin._gh_variable(scope_flag="--org", scope="o") == expected
    assert calls == [["gh", "variable", "get", "CLAUDE_CLI_VERSION", "--org", "o"]]


class TestEnsureCli:
    @pytest.fixture(autouse=True)
    def cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        return tmp_path

    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        recorded: list[list[str]] = []

        def fake_run(*, args: list[str], cwd: Path, timeout: float) -> Result[str]:
            recorded.append(args)
            return err("npm down") if args[0] == "npm" and "fail" in args[-1] else ok("")

        monkeypatch.setattr(cli_pin, "run_checked", fake_run)
        return recorded

    def test_installs_into_the_cache_prefix(self, calls: list[list[str]], cache: Path) -> None:
        result = ensure_cli(version="2.1.0")

        prefix = cache / "dev10x" / "ci-review" / "cli" / "2.1.0"
        assert result == SuccessResult(value=prefix / "node_modules" / ".bin" / "claude")
        assert calls == [
            [
                "npm",
                "install",
                "--prefix",
                str(prefix),
                "--no-save",
                "@anthropic-ai/claude-code@2.1.0",
            ],
            [str(cli_binary(version="2.1.0")), "--version"],
        ]

    def test_skips_install_when_present(self, calls: list[list[str]]) -> None:
        binary = cli_binary(version="2.1.0")
        binary.parent.mkdir(parents=True)
        binary.write_text("", encoding="utf-8")

        ensure_cli(version="2.1.0")

        assert calls == [[str(binary), "--version"]]

    def test_install_failure(self, calls: list[list[str]]) -> None:
        assert ensure_cli(version="fail") == err("npm down")

    def test_version_check_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        binary = cli_binary(version="2.1.0")
        binary.parent.mkdir(parents=True)
        binary.write_text("", encoding="utf-8")
        monkeypatch.setattr(cli_pin, "run_checked", lambda **_: err("broken"))

        assert ensure_cli(version="2.1.0") == err("broken")
