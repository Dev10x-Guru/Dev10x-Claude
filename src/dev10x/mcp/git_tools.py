"""Git MCP tool registrations (split from server_cli.py, GH-243/A6)."""

from __future__ import annotations

from dev10x.mcp._app import server


@server.tool()
async def push_safe(
    args: list[str],
    protected_branches: list[str] | None = None,
    cwd: str | None = None,
) -> dict:
    """Safely push git branches with protection for main/develop.

    Args:
        args: Arguments to pass to git push (e.g., ["origin", "branch-name"])
        protected_branches: List of branch names to protect (default: main, develop)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), branch, remote, blocked_reason (if blocked)

    Success semantics (GH-152):
        An empty dict `{}` IS a successful push — the underlying
        `git push` script may emit no key/value output on a clean
        fast-forward. Callers MUST NOT interpret `{}` as failure
        and MUST NOT fall back to raw `git push` (which is
        hook-blocked). To verify the remote actually received the
        push, run `git ls-remote --heads origin <branch>` and
        compare against the local HEAD SHA. A real failure
        returns `{"error": "<message>"}` — branch on the `error`
        key, not on emptiness.
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await git_tools.push_safe(args=args, protected_branches=protected_branches)
        ).to_dict()


@server.tool()
async def rebase_groom(seq_path: str, base_ref: str, cwd: str | None = None) -> dict:
    """Rebase and groom commits using an interactive sequence file.

    Args:
        seq_path: Path to git rebase sequence file
        base_ref: Base ref to rebase onto (e.g., develop, main)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), commits_rewritten (int)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.rebase_groom(seq_path=seq_path, base_ref=base_ref)).to_dict()


@server.tool()
async def create_worktree(
    branch: str,
    base: str | None = None,
    path: str | None = None,
    cwd: str | None = None,
) -> dict:
    """Create a new git worktree.

    Args:
        branch: Branch name for the worktree
        base: Base ref to create from (default: develop)
        path: Worktree path (default: ../.worktrees/{project}-NN)
        cwd: Effective working directory (GH-979). The new worktree
            is added relative to this repo.

    Returns:
        Dictionary with keys: worktree_path, branch, created (bool)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.create_worktree(branch=branch, base=base, path=path)).to_dict()


@server.tool()
async def mass_rewrite(config_path: str, cwd: str | None = None) -> dict:
    """Rewrite multiple commit messages in one unattended rebase pass.

    Args:
        config_path: Path to JSON config file with rewrite instructions.
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str), error (str if failed)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.mass_rewrite(config_path=config_path)).to_dict()


@server.tool()
async def start_split_rebase(
    commit_hash: str,
    base_branch: str = "develop",
    cwd: str | None = None,
) -> dict:
    """Start an interactive rebase to split a commit.

    Args:
        commit_hash: The commit hash to split
        base_branch: Base branch for the rebase (default: develop)
        cwd: Effective working directory (GH-979).

    Returns:
        Dictionary with keys: success (bool), output (str), error (str if failed)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (
            await git_tools.start_split_rebase(commit_hash=commit_hash, base_branch=base_branch)
        ).to_dict()


@server.tool()
async def next_worktree_name(base_dir: str | None = None, cwd: str | None = None) -> dict:
    """Calculate the next available worktree path.

    Args:
        base_dir: Override worktrees parent directory (default: ../.worktrees)
        cwd: Effective working directory (GH-979). The .worktrees parent
            is computed relative to this repo when base_dir is omitted.

    Returns:
        Dictionary with keys: path (str)
    """
    from dev10x import git as git_tools
    from dev10x.subprocess_utils import use_cwd

    with use_cwd(cwd):
        return (await git_tools.next_worktree_name(base_dir=base_dir)).to_dict()


@server.tool()
async def setup_aliases() -> dict:
    """Set up global git aliases for branch comparison operations.

    Returns:
        Dictionary with keys: success (bool), output (str)
    """
    from dev10x import git as git_tools

    return (await git_tools.setup_aliases()).to_dict()
