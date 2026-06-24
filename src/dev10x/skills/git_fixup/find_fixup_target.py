"""Resolve fixup target commits via git blame on staged hunks.

The legacy approach in ``Dev10x:git-fixup`` selected the fixup target as
the first commit on the branch (``git log --reverse | head -1``), which
attributes fixes to commits that did not own the edited lines. When the
fixup is reordered by ``git rebase -i --autosquash``, a later commit
that touches the same files no longer applies cleanly and conflicts on
modify/delete or content. ``git rerere`` then memoizes the bad
resolution and silently re-applies it on the next attempt.

This module reads the staged diff, locates the pre-image line range for
every modified hunk, and asks ``git blame`` which branch commit last
touched those lines. The owning commit becomes the fixup target. When
the staged change spans hunks owned by more than one branch commit, the
module returns all owners so the caller can split the change into
multiple fixups (one per owning commit) instead of producing a
cross-commit fixup that autosquash cannot fold cleanly.

Output is JSON on stdout; exit codes are 0 (success — single or multi),
1 (error), 2 (no staged changes), 3 (staged hunks land entirely on
commits outside the branch range, e.g. base-branch history).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Hunk header: @@ -<start>[,<count>] +<start>[,<count>] @@
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")

# git blame --porcelain header: <sha> <orig-line> <final-line>[ <num-lines>]
_BLAME_HEADER_RE = re.compile(r"^([0-9a-f]{40}) \d+ \d+(?: \d+)?$")


@dataclass(frozen=True)
class Hunk:
    """A staged hunk in a single file (pre-image line range)."""

    path: str
    start: int  # 1-based first pre-image line
    count: int  # number of pre-image lines (0 for pure additions)


@dataclass
class Owner:
    """A branch commit that owns one or more staged hunks."""

    sha: str
    subject: str = ""
    hunks: list[Hunk] = field(default_factory=list)


def _run(args: list[str], *, cwd: Path | None = None) -> str:
    """Run a git subprocess and return stdout. Raises CalledProcessError."""
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def detect_base_branch(*, cwd: Path | None = None) -> str:
    """Detect the base branch — prefer develop, fall back to main/master."""
    # Local copy of dev10x.domain.common.branch_name.BASE_BRANCH_PRIORITY:
    # this script runs standalone via `uv run --script` in an isolated
    # venv, so it must not import the dev10x package (GH-583).
    candidates = ("develop", "development", "main", "master", "trunk")
    for candidate in candidates:
        try:
            _run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"],
                cwd=cwd,
            )
            return candidate
        except subprocess.CalledProcessError:
            pass
    for candidate in candidates:
        try:
            _run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{candidate}"],
                cwd=cwd,
            )
            return f"origin/{candidate}"
        except subprocess.CalledProcessError:
            pass
    raise RuntimeError("Could not detect base branch (develop/main/master)")


def branch_commits(base: str, *, cwd: Path | None = None) -> set[str]:
    """Return full SHAs of commits in ``base..HEAD`` (the fixup target window)."""
    out = _run(["git", "rev-list", f"{base}..HEAD"], cwd=cwd)
    return {line.strip() for line in out.splitlines() if line.strip()}


def parse_staged_hunks(*, cwd: Path | None = None) -> list[Hunk]:
    """Parse ``git diff --cached -U0`` into pre-image hunks.

    Pure additions (count == 0) are kept — the caller treats them by
    blaming the surrounding context (the line at ``start`` is the line
    *before* the insertion in the pre-image), which still attributes
    the new code to the commit that last touched that file region.
    """
    out = _run(
        ["git", "diff", "--cached", "-U0", "--no-color", "--no-renames"],
        cwd=cwd,
    )
    hunks: list[Hunk] = []
    current_path: str | None = None
    for line in out.splitlines():
        if line.startswith("--- "):
            # --- a/path or --- /dev/null
            current_path = None
            continue
        if line.startswith("+++ "):
            # +++ b/path — strip "b/" prefix; /dev/null for deletes
            target = line[4:].strip()
            if target == "/dev/null":
                current_path = None
            elif target.startswith("b/"):
                current_path = target[2:]
            else:
                current_path = target
            continue
        if current_path is None:
            continue
        match = _HUNK_RE.match(line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        hunks.append(Hunk(path=current_path, start=start, count=count))
    return hunks


def blame_hunk(hunk: Hunk, *, cwd: Path | None = None) -> list[str]:
    """Return the unique full SHAs that own the pre-image lines of ``hunk``.

    For pure additions (count == 0), blame the line at ``hunk.start`` —
    that line is the pre-image line immediately preceding the insertion
    point and attributes the new code to the commit that last touched
    that region. When ``hunk.start == 0`` (insertion at top of file),
    no pre-image context exists; return an empty list (caller treats
    this as ambiguous).
    """
    if hunk.count == 0:
        if hunk.start == 0:
            return []
        line_start = hunk.start
        line_end = hunk.start
    else:
        line_start = hunk.start
        line_end = hunk.start + hunk.count - 1

    try:
        out = _run(
            [
                "git",
                "blame",
                "--porcelain",
                f"-L{line_start},{line_end}",
                "HEAD",
                "--",
                hunk.path,
            ],
            cwd=cwd,
        )
    except subprocess.CalledProcessError:
        return []

    shas: list[str] = []
    seen: set[str] = set()
    for line in out.splitlines():
        match = _BLAME_HEADER_RE.match(line)
        if match:
            sha = match.group(1)
            if sha not in seen:
                seen.add(sha)
                shas.append(sha)
    return shas


def commit_subject(sha: str, *, cwd: Path | None = None) -> str:
    """Return the subject line of ``sha``."""
    out = _run(["git", "log", "-1", "--format=%s", sha], cwd=cwd)
    return out.strip()


def resolve_owners(
    hunks: list[Hunk],
    branch_shas: set[str],
    *,
    cwd: Path | None = None,
) -> tuple[list[Owner], list[Hunk]]:
    """Group hunks by their branch-range owning commit.

    Returns a tuple ``(owners, orphan_hunks)``. Owners preserve the
    order they were first encountered. Orphan hunks are those whose
    blame produced no branch-range commit (lines owned only by base
    history); the caller decides whether to abort or fall through to a
    legacy target.
    """
    owners_by_sha: dict[str, Owner] = {}
    orphans: list[Hunk] = []
    for hunk in hunks:
        blame_shas = blame_hunk(hunk, cwd=cwd)
        branch_owners = [sha for sha in blame_shas if sha in branch_shas]
        if not branch_owners:
            orphans.append(hunk)
            continue
        # Attribute the hunk to every branch-owning commit it touches —
        # in practice this is usually one, but a hunk that spans several
        # lines may legitimately straddle commits. `branch_owners` holds
        # distinct SHAs (blame_hunk deduplicates), so each (hunk, owner)
        # pair is appended at most once per hunk — no membership guard
        # is needed here.
        for sha in branch_owners:
            owner = owners_by_sha.get(sha)
            if owner is None:
                owner = Owner(sha=sha, subject=commit_subject(sha, cwd=cwd))
                owners_by_sha[sha] = owner
            owner.hunks.append(hunk)
    return list(owners_by_sha.values()), orphans


def _owner_to_dict(owner: Owner) -> dict:
    return {
        "sha": owner.sha,
        "subject": owner.subject,
        "hunks": [{"path": h.path, "start": h.start, "count": h.count} for h in owner.hunks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve fixup target commits by blaming staged hunks against "
            "the current branch range."
        ),
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Base branch ref (default: auto-detect develop/main/master).",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory for git subprocesses.",
    )
    args = parser.parse_args(argv)

    cwd = Path(args.cwd) if args.cwd else None
    try:
        base = args.base or detect_base_branch(cwd=cwd)
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1

    try:
        branch_shas = branch_commits(base, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": f"git rev-list {base}..HEAD failed: {exc.stderr.strip()}",
                }
            )
        )
        return 1

    if not branch_shas:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": (
                        f"No commits in {base}..HEAD — fixup requires at least "
                        "one branch commit to target."
                    ),
                }
            )
        )
        return 1

    hunks = parse_staged_hunks(cwd=cwd)
    if not hunks:
        print(json.dumps({"status": "no_staged", "base": base}))
        return 2

    owners, orphans = resolve_owners(hunks, branch_shas, cwd=cwd)

    if not owners:
        # Every hunk landed on base-branch history. This is a legitimate
        # case for a brand-new file or a region untouched by branch
        # commits — the caller should fall back to the first branch
        # commit (legacy behavior) and mark the result as a fresh
        # change rather than a cross-commit fixup.
        out = _run(["git", "log", f"{base}..HEAD", "--reverse", "--format=%H"], cwd=cwd)
        first_branch_sha = out.strip().splitlines()[0]
        print(
            json.dumps(
                {
                    "status": "out_of_branch",
                    "base": base,
                    "fallback_target": first_branch_sha,
                    "fallback_subject": commit_subject(first_branch_sha, cwd=cwd),
                    "orphan_hunks": [
                        {"path": h.path, "start": h.start, "count": h.count} for h in orphans
                    ],
                }
            )
        )
        return 3

    if len(owners) == 1 and not orphans:
        owner = owners[0]
        print(
            json.dumps(
                {
                    "status": "single",
                    "base": base,
                    "target": owner.sha,
                    "subject": owner.subject,
                    "hunks": [
                        {"path": h.path, "start": h.start, "count": h.count} for h in owner.hunks
                    ],
                }
            )
        )
        return 0

    print(
        json.dumps(
            {
                "status": "multi",
                "base": base,
                "owners": [_owner_to_dict(o) for o in owners],
                "orphan_hunks": [
                    {"path": h.path, "start": h.start, "count": h.count} for h in orphans
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
