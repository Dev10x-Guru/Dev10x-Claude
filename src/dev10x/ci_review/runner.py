from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.ci_review.gh_shim import REAL_GH_ENV
from dev10x.ci_review.inline_stub import SERVER_NAME
from dev10x.ci_review.outbox import OUTBOX_ENV
from dev10x.core import subprocess_utils
from dev10x.core.domain.claude_paths import ClaudeDir
from dev10x.core.domain.common.result import Result, err, ok

DEFAULT_TIMEOUT_SECONDS: int = 1800
CREDENTIALS_FILE: str = ".credentials.json"


@dataclass(frozen=True)
class Auth:
    env: dict[str, str]
    notional: bool


@dataclass(frozen=True)
class Invocation:
    argv: list[str]
    env: dict[str, str]
    cwd: Path


def resolve_auth(*, environ: Mapping[str, str], config_dir: Path) -> Result[Auth]:
    api_key = environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return ok(Auth(env={"ANTHROPIC_API_KEY": api_key}, notional=False))
    source_root = (
        Path(environ["CLAUDE_CONFIG_DIR"])
        if environ.get("CLAUDE_CONFIG_DIR")
        else ClaudeDir.home()
    )
    source = source_root / CREDENTIALS_FILE
    if not source.is_file():
        return err(
            "No Claude credentials: set ANTHROPIC_API_KEY or log in with `claude` "
            f"so {source} exists"
        )
    config_dir.mkdir(parents=True, exist_ok=True)
    link = config_dir / CREDENTIALS_FILE
    if not link.is_symlink():
        link.symlink_to(source)
    return ok(Auth(env={}, notional=True))


def write_mcp_config(*, run_dir: Path, inline: bool, python: str) -> Path:
    servers: dict[str, Any] = {}
    if inline:
        servers[SERVER_NAME] = {
            "command": python,
            "args": ["-I", "-m", "dev10x.ci_review.inline_stub"],
        }
    path = run_dir / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")
    return path


def build_invocation(
    *,
    claude: Path,
    prompt: str,
    claude_args: list[str],
    run_dir: Path,
    checkout: Path,
    home: str,
    repo: str,
    pr: int,
    real_gh: str,
    auth: Auth,
    node_dir: Path | None,
) -> Invocation:
    owner, name = repo.split("/", 1)
    path_dirs = [str(run_dir / "bin"), *([str(node_dir)] if node_dir else []), "/usr/bin", "/bin"]
    env = {
        "PATH": ":".join(path_dirs),
        "HOME": home,
        "CLAUDE_CONFIG_DIR": str(run_dir / "config"),
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "CLAUDE_CODE_ACTION": "1",
        "DETAILED_PERMISSION_MESSAGES": "1",
        "SHELL": "/bin/bash",
        "GITHUB_REPOSITORY": repo,
        "PR_NUMBER": str(pr),
        "REPO_OWNER": owner,
        "REPO_NAME": name,
        OUTBOX_ENV: str(run_dir / "outbox.jsonl"),
        REAL_GH_ENV: real_gh,
        **auth.env,
    }
    argv = [
        str(claude),
        "-p",
        prompt,
        *claude_args,
        "--output-format",
        "stream-json",
        "--verbose",
        "--mcp-config",
        str(run_dir / "mcp.json"),
        "--strict-mcp-config",
    ]
    return Invocation(argv=argv, env=env, cwd=checkout)


def node_dir() -> Path | None:
    node = shutil.which("node")
    return Path(node).parent if node else None


def run_claude(*, invocation: Invocation, run_dir: Path, timeout: float) -> Result[list[dict]]:
    try:
        completed = subprocess_utils.run(
            invocation.argv,
            cwd=str(invocation.cwd),
            env=invocation.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return err(f"claude did not finish within {timeout:g}s. Please try again.")
    except OSError as exc:
        return err(f"claude could not start: {exc}")
    execution = parse_stream(stdout=completed.stdout)
    (run_dir / "execution.json").write_text(
        json.dumps(execution, indent=2) + "\n", encoding="utf-8"
    )
    if completed.returncode != 0:
        return err(f"claude exited {completed.returncode}", stderr=completed.stderr.strip())
    return ok(execution)


def parse_stream(*, stdout: str) -> list[dict]:
    messages: list[dict] = []
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.append(message)
    return messages
