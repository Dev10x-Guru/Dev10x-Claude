#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""branch:groom mass-rewrite — non-interactive multi-commit message rewrite.

Rewrites commit messages (and optionally renames files) for multiple
commits in one unattended git rebase pass. All operations are batched
so only a single permission approval is needed.

Usage:
    python3 mass-rewrite.py <config.json>
    python3 mass-rewrite.py -     # reads JSON from stdin

Config JSON:
    {
      "base": "develop",
      "commits": {
        "abc1234": "New commit message",
        "def5678": {
          "message": "New commit message",
          "renames": [["old/path/A", "new/path/A"], ["old/path/B", "new/path/B"]]
        }
      }
    }

Notes:
  - SHAs must be 7-char prefixes from the current branch HEAD.
  - Commits with renames: all mv + amend ops are chained in a single exec
    line to keep the index clean between rebase steps.
  - On failure: git rebase --abort; to recover: git reflog
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TMPDIR = Path("/tmp/Dev10x/git")


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def get_base_sha(base_ref: str) -> str:
    return run(["git", "merge-base", base_ref, "HEAD"]).stdout.strip()


def get_current_commits(base_sha: str) -> list[tuple[str, str]]:
    """Return (short_sha, subject) tuples, oldest first."""
    result = run(["git", "log", "--oneline", "--reverse", f"{base_sha}..HEAD"])
    commits = []
    for line in result.stdout.strip().splitlines():
        if line:
            short, *rest = line.split(" ", 1)
            commits.append((short[:7], rest[0] if rest else ""))
    return commits


def validate_shas(config_shas: set[str], current_shas: set[str]) -> None:
    stale = config_shas - current_shas
    if not stale:
        return
    print("ERROR: These SHAs from config don't exist in current branch:", file=sys.stderr)
    for sha in sorted(stale):
        print(f"  {sha}", file=sys.stderr)
    print("\nRe-check SHAs with: git log --oneline develop..HEAD", file=sys.stderr)
    sys.exit(1)


def write_message_files(commits_config: dict, msgs_dir: Path) -> None:
    msgs_dir.mkdir(parents=True, exist_ok=True)
    for sha, spec in commits_config.items():
        msg = spec["message"] if isinstance(spec, dict) else spec
        (msgs_dir / sha).write_text(msg, encoding="utf-8")


def write_seq_editor(commits_config: dict, msgs_dir: Path, seq_editor: Path) -> None:
    """Generate a GIT_SEQUENCE_EDITOR script that injects exec lines.

    Commits with renames get a single chained exec (mv + amend) to avoid
    leaving staged changes between exec steps, which halts the rebase.
    All other config commits get a simple amend exec.
    """
    rename_commits = {
        sha: spec
        for sha, spec in commits_config.items()
        if isinstance(spec, dict) and spec.get("renames")
    }

    lines = [
        "#!/bin/bash",
        "TMPFILE=$(mktemp)",
        "while IFS= read -r line; do",
        '    if [[ "$line" =~ ^[[:space:]]*# ]] || [[ -z "$line" ]]; then',
        '        printf \'%s\\n\' "$line" >> "$TMPFILE"; continue',
        "    fi",
        "    SHA=$(echo \"$line\" | awk '{print $2}')",
        '    SHORT="${SHA:0:7}"',
        f'    MSGFILE="{msgs_dir}/$SHORT"',
        '    printf \'%s\\n\' "$line" >> "$TMPFILE"',
    ]

    if rename_commits:
        first = True
        for sha, spec in rename_commits.items():
            renames = spec["renames"]
            kw = "if" if first else "    elif"
            first = False
            mv_chain = " && ".join(f"git mv {src} {dst}" for src, dst in renames)
            lines.append(f'    {kw} [[ "$SHORT" == "{sha}" ]]; then')
            lines.append(
                f"        printf 'exec {mv_chain}"
                f' && git commit --amend -F %s\\n\' "$MSGFILE" >> "$TMPFILE"'
            )
        lines.append('    elif [[ -f "$MSGFILE" ]]; then')
    else:
        lines.append('    if [[ -f "$MSGFILE" ]]; then')

    lines += [
        '        printf \'exec git commit --amend -F %s\\n\' "$MSGFILE" >> "$TMPFILE"',
        "    fi",
        'done < "$1"',
        'mv "$TMPFILE" "$1"',
        "",
    ]

    seq_editor.write_text("\n".join(lines), encoding="utf-8")
    seq_editor.chmod(seq_editor.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def is_rebase_in_progress() -> bool:
    git_dir = run(["git", "rev-parse", "--git-dir"]).stdout.strip()
    return (Path(git_dir) / "rebase-merge").is_dir()


def get_conflicted_files() -> list[str]:
    result = run(["git", "diff", "--name-only", "--diff-filter=U"], check=False)
    return [f for f in result.stdout.strip().splitlines() if f]


def run_rebase(base_sha: str, seq_editor: Path) -> None:
    env = os.environ.copy()
    env["GIT_SEQUENCE_EDITOR"] = str(seq_editor)
    env["GIT_EDITOR"] = "true"
    result = subprocess.run(
        ["git", "rebase", "-i", base_sha],
        env=env,
        text=True,
    )
    if result.returncode != 0:
        if is_rebase_in_progress():
            files = get_conflicted_files()
            print("CONFLICT_DETECTED")
            print(f"conflicted_files={','.join(files)}")
            rebase_head = run(
                ["git", "rev-parse", "--short", "REBASE_HEAD"], check=False
            ).stdout.strip()
            print(f"rebase_head={rebase_head or 'unknown'}")
            print("hint=Resolve conflicts, git add, then git rebase --continue")
            sys.exit(1)
        print("Rebase failed.", file=sys.stderr)
        print("  Abort:   git rebase --abort", file=sys.stderr)
        print("  Recover: git reflog  →  git reset --hard HEAD@{n}", file=sys.stderr)
        sys.exit(result.returncode)


def create_workdir() -> Path:
    DEFAULT_TMPDIR.mkdir(parents=True, exist_ok=True)

    return Path(tempfile.mkdtemp(prefix="groom.", dir=DEFAULT_TMPDIR))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    src = sys.argv[1]
    config = json.load(sys.stdin) if src == "-" else json.loads(Path(src).read_text())

    base_ref: str = config.get("base", "develop")
    commits_config: dict = config["commits"]

    workdir = create_workdir()
    msgs_dir = workdir / "msgs"
    seq_editor = workdir / "seq-editor.sh"

    print(f"Base: {base_ref}  |  Commits to rewrite: {len(commits_config)}")
    print(f"Workdir: {workdir}")

    base_sha = get_base_sha(base_ref)
    current_commits = get_current_commits(base_sha)
    current_shas = {sha for sha, _ in current_commits}

    print(f"\nCurrent branch ({len(current_commits)} commits):")
    for sha, subject in current_commits:
        marker = "✎" if sha in commits_config else " "
        print(f"  {marker} {sha} {subject}")

    validate_shas(set(commits_config.keys()), current_shas)

    print(f"\nWriting message files → {msgs_dir}")
    write_message_files(commits_config=commits_config, msgs_dir=msgs_dir)

    print(f"Writing sequence editor → {seq_editor}")
    write_seq_editor(
        commits_config=commits_config,
        msgs_dir=msgs_dir,
        seq_editor=seq_editor,
    )

    print("Running rebase…")
    run_rebase(base_sha=base_sha, seq_editor=seq_editor)

    print("\nDone. New log:")
    result = run(["git", "log", "--oneline", f"{base_sha}..HEAD"])
    print(result.stdout)


if __name__ == "__main__":
    main()
