from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT: Path = Path(__file__).parents[2]
_SCRIPTS: Path = _REPO_ROOT / ".github" / "scripts" / "claude-pr-context"

PR_NUMBER: int = 7


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout


def _write(*, root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@dataclass(frozen=True)
class GitFixture:
    clone: Path
    base_sha: str
    merge_sha: str


@pytest.fixture
def git_repos(tmp_path: Path) -> GitFixture:
    origin = tmp_path / "origin"
    origin.mkdir()
    git("init", "-q", "-b", "develop", cwd=origin)
    shutil.copytree(_SCRIPTS, origin / ".github" / "scripts" / "claude-pr-context")
    _write(
        root=origin,
        files={
            ".github/claude/ci-system-prompt.md": "base system prompt\n",
            ".github/claude-ci-settings.json": "{}\n",
            ".github/workflows/review.yml": "name: base\n",
            "references/guide.md": "base guide\n",
            ".claude/rules/a.md": "base rule\n",
            "CLAUDE.md": "base claude\n",
        },
    )
    git("add", "-A", cwd=origin)
    git("commit", "-q", "-m", "base", cwd=origin)
    base_sha = git("rev-parse", "HEAD", cwd=origin).strip()
    _write(
        root=origin,
        files={
            ".github/claude/ci-system-prompt.md": "pr system prompt\n",
            ".github/workflows/review.yml": "name: pr\n",
            ".claude/rules/a.md": "pr rule\n",
            ".claude/rules/b.md": "pr-only rule\n",
            ".mcp.json": '{"mcpServers": {"evil": {}}}\n',
            "CLAUDE.md": "pr claude\n",
        },
    )
    (origin / ".claude" / "link").symlink_to("/etc/hostname")
    git("add", "-A", cwd=origin)
    git("commit", "-q", "-m", "pr", cwd=origin)
    merge_sha = git("rev-parse", "HEAD", cwd=origin).strip()
    git("update-ref", f"refs/pull/{PR_NUMBER}/merge", merge_sha, cwd=origin)
    git("reset", "-q", "--hard", base_sha, cwd=origin)
    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    return GitFixture(clone=clone, base_sha=base_sha, merge_sha=merge_sha)
