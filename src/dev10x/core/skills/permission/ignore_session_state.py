"""Keep Dev10x's own session state out of `git status` (GH-1275).

Dev10x writes per-session state to `.claude/Dev10x/` in whichever
checkout it runs in. In any project that tracks `.claude/` — the common
case, since `.claude/agents/`, `.claude/rules/` and `.claude/references/`
are checked in — nothing ignores that path, so every worktree
accumulates an untracked directory and a fresh worktree reads as dirty
the moment a session runs in it.

The rule goes in `.git/info/exclude`, not a tracked `.claude/.gitignore`.
The issue leaves that choice open, but `references/post-upgrade-verification.md`
settles it: a maintenance pass must not write git-tracked content, which
is what keeps it from dirtying reviewed repo state. `info/exclude` also
lives in the **common** git dir, so one write covers a repo and every
worktree of it, where a per-worktree file would need N writes and still
miss the next worktree created.

The tracked spelling is a better fit for something a human commits
deliberately — shared with teammates, surviving a fresh clone — so it is
offered as a suggestion rather than written.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dev10x import subprocess_utils
from dev10x.domain.file_locks import atomic_append_line
from dev10x.domain.git_context import GitContext

#: Relative to the repo root — the spelling `.git/info/exclude` expects.
IGNORE_PATTERN = ".claude/Dev10x/"

#: Relative to `.claude/` — the spelling a tracked `.claude/.gitignore`
#: expects, offered to the user rather than written by the pass.
SUGGESTED_TRACKED_PATTERN = "/Dev10x/"

_MARKER_COMMENT = "# Dev10x per-session state (GH-1275)"

Status = Literal["already-ignored", "appended", "would-append", "not-a-repo"]


@dataclass(frozen=True)
class IgnoreOutcome:
    """What the pass did for one repo."""

    repo_root: Path
    status: Status
    exclude_path: Path | None = None

    @property
    def changed(self) -> bool:
        """Whether this repo needed a rule — written, or would be.

        A dry run counts: the suggestion in :func:`suggestion_for` is about
        what the repo lacks, not about what this process did, so hiding it
        under ``--dry-run`` would make the preview disagree with the run.
        """
        return self.status in ("appended", "would-append")

    def summary(self) -> str:
        if self.status == "not-a-repo":
            return f"  {self.repo_root}: skipped — not a git repository"
        if self.status == "already-ignored":
            return f"  {self.repo_root}: already ignored"
        verb = "would add" if self.status == "would-append" else "+"
        return f"  {self.repo_root}: {verb} {IGNORE_PATTERN} → {self.exclude_path}"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    # `subprocess` is imported for the return type only — every call goes
    # through subprocess_utils.run so it inherits the effective CWD
    # binding (GH-979).
    return subprocess_utils.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def is_already_ignored(*, repo_root: Path) -> bool:
    """Whether git already ignores the state directory for this repo.

    Asks git rather than reading the file, so a rule reaching the path by
    any route counts — a global `core.excludesFile`, a tracked
    `.claude/.gitignore` a teammate committed, or a broader pattern. The
    issue asks for exactly that: skip when the path is already ignored by
    some other rule.
    """
    return _git("check-ignore", "-q", IGNORE_PATTERN, cwd=repo_root).returncode == 0


def common_git_dir(*, repo_root: Path) -> Path | None:
    """The shared git dir for this repo, or None when it is not a repo.

    `--git-common-dir` rather than `--git-dir`: from inside a worktree the
    latter points at `<main>/.git/worktrees/<name>`, whose `info/exclude`
    git does NOT consult. The common dir is the one place a single write
    covers every worktree.

    GH-1445: delegates to :attr:`GitContext.common_dir`, which asks for an
    absolute path — this was the third hand-rolled copy of the lookup, and
    the second to re-resolve a relative result by hand.
    """
    common = GitContext(cwd=str(repo_root)).common_dir
    return Path(common) if common else None


def ensure_ignored(*, repo_root: Path, dry_run: bool = False) -> IgnoreOutcome:
    """Ensure `.claude/Dev10x/` is ignored for ``repo_root``.

    Idempotent and additive: appends one line and never rewrites or
    reorders what is already there.
    """
    git_dir = common_git_dir(repo_root=repo_root)
    if git_dir is None:
        return IgnoreOutcome(repo_root=repo_root, status="not-a-repo")

    if is_already_ignored(repo_root=repo_root):
        return IgnoreOutcome(repo_root=repo_root, status="already-ignored")

    exclude_path = git_dir / "info" / "exclude"
    if dry_run:
        return IgnoreOutcome(
            repo_root=repo_root,
            status="would-append",
            exclude_path=exclude_path,
        )
    atomic_append_line(exclude_path, f"{_MARKER_COMMENT}\n{IGNORE_PATTERN}")
    return IgnoreOutcome(
        repo_root=repo_root,
        status="appended",
        exclude_path=exclude_path,
    )


def discover_repo_roots(roots: list[Path]) -> list[Path]:
    """Expand each configured root into every git repo beneath it (GH-1330).

    A configured root may itself be a repo (`/work/dx/Dev10x-Claude`), or a
    container directory holding many repos and worktrees beneath it
    (`/work/dx` covers a dozen checkouts, not one). Passing a container
    straight to :func:`ensure_ignored` made `common_git_dir` fail on it —
    the container itself has no `.git` — so every real repo underneath
    was never reached.

    Mirrors the walk `update_paths.find_settings_files` already uses for
    `.claude/settings.local.json`: `root.rglob(".git")` for a container,
    keeping the root itself when IT is the repo rather than also
    descending into its own tree (a worktree's `.git` is a file, not a
    directory, so entry type is never checked).
    """
    seen: dict[Path, None] = {}
    for root in roots:
        if not root.is_dir():
            continue
        if (root / ".git").exists():
            seen.setdefault(root.resolve(), None)
            continue
        for git_entry in root.rglob(".git"):
            seen.setdefault(git_entry.parent.resolve(), None)
    return list(seen.keys())


def ensure_ignored_for_roots(
    *,
    repo_roots: list[Path],
    dry_run: bool = False,
) -> list[IgnoreOutcome]:
    """Run :func:`ensure_ignored` once per repo, de-duplicated.

    Two worktrees of one repo are distinct roots that share a common git
    dir, so the second reads as ``already-ignored`` after the first write
    rather than appending a duplicate — the de-duplication here only saves
    the redundant subprocess pair.
    """
    seen: dict[Path, None] = {}
    for root in repo_roots:
        seen.setdefault(root, None)
    return [ensure_ignored(repo_root=root, dry_run=dry_run) for root in seen]


def suggestion_for(outcome: IgnoreOutcome) -> str | None:
    """The tracked rule a human may prefer to commit, or None.

    Only offered where the pass actually wrote an untracked rule: a repo
    already covered needs nothing, and suggesting a commit there would be
    noise.
    """
    if not outcome.changed:
        return None
    return (
        f"  {outcome.repo_root}: to share this with teammates and survive a "
        f"fresh clone, commit `{SUGGESTED_TRACKED_PATTERN}` in "
        f"{outcome.repo_root / '.claude' / '.gitignore'} — this pass does not "
        "write git-tracked files."
    )
