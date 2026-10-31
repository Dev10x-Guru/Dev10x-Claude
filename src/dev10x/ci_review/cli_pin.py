from __future__ import annotations

import re
from pathlib import Path

from dev10x.ci_review.process import run_checked
from dev10x.ci_review.workspace import cache_root
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok

VERSION_VARIABLE: str = "CLAUDE_CLI_VERSION"
PACKAGE: str = "@anthropic-ai/claude-code"

_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]*$")


def resolve_cli_version(
    *,
    explicit: str | None,
    environ: dict[str, str],
    owner: str,
    repo: str,
) -> Result[str]:
    candidates = (
        lambda: explicit,
        lambda: environ.get(VERSION_VARIABLE),
        lambda: _gh_variable(scope_flag="--org", scope=owner),
        lambda: _gh_variable(scope_flag="--repo", scope=repo),
    )
    for candidate in candidates:
        version = (candidate() or "").strip()
        if not version:
            continue
        if not _VERSION.match(version):
            return err(f"CLI version {version!r} is not a plain version string")
        return ok(version)
    return err(
        "No Claude CLI version: pass --cli-version, set the "
        f"{VERSION_VARIABLE} env var, or set the {VERSION_VARIABLE} Actions "
        f"variable on the {owner} organization or the {repo} repository"
    )


def _gh_variable(*, scope_flag: str, scope: str) -> str | None:
    result = run_checked(
        args=["gh", "variable", "get", VERSION_VARIABLE, scope_flag, scope],
        timeout=60,
    )
    if isinstance(result, ErrorResult):
        return None
    return result.value


def cli_prefix(*, version: str) -> Path:
    return cache_root() / "cli" / version


def cli_binary(*, version: str) -> Path:
    return cli_prefix(version=version) / "node_modules" / ".bin" / "claude"


def ensure_cli(*, version: str) -> Result[Path]:
    prefix = cli_prefix(version=version)
    binary = cli_binary(version=version)
    if not binary.exists():
        prefix.mkdir(parents=True, exist_ok=True)
        # cwd is the prefix, never the checkout, so a PR's .npmrc cannot
        # redirect the registry — the reason CI installs from RUNNER_TEMP.
        installed = run_checked(
            args=["npm", "install", "--prefix", str(prefix), "--no-save", f"{PACKAGE}@{version}"],
            cwd=prefix,
            timeout=600,
        )
        if isinstance(installed, ErrorResult):
            return installed
    checked = run_checked(args=[str(binary), "--version"], cwd=prefix, timeout=60)
    if isinstance(checked, ErrorResult):
        return checked
    return ok(binary)
