"""Continuous learning loop for the installable review Action (GH-353).

Closes the review-bot learning cycle: when a PR is closed, mine the
consumer repository's merged-PR review history into validated reference
rules (the GH-346→GH-349 pipeline), materialize them under
``references/review-checks/generated/``, and open a *rules-update* PR for
human approval. The PR is the approval gate — nothing is enforced until a
human merges it, mirroring the dry-run philosophy of every upstream step.

The Action's ``learn`` mode shells out to ``dev10x github learn`` (see
``dev10x.commands.github``), which owns stdout and the process exit code
per ADR-0010. This module is the side-effect-bearing orchestrator: it
returns ``Result[T]`` and never calls ``print`` or ``sys.exit``. Git and
``gh`` invocations route through :func:`dev10x.subprocess_utils.async_run`
with an explicit ``cwd`` so the loop operates on the checked-out consumer
workspace, not the process start directory.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from dev10x.domain.common.result import Result, SuccessResult, err, ok
from dev10x.github import rule_authoring
from dev10x.github.rule_authoring import RuleDoc
from dev10x.subprocess_utils import async_run

logger = logging.getLogger(__name__)

# Stable branch the bot reuses for its rules-update PR. Reusing one branch
# (force-pushed each run) keeps a single open proposal per repo rather than
# accumulating one branch per closed PR.
DEFAULT_LEARN_BRANCH = "dev10x/learned-rules"

# Identity stamped on the bot's commit when the runner has no git config.
_BOT_NAME = "dev10x-review[bot]"
_BOT_EMAIL = "dev10x-review@users.noreply.github.com"


def render_pr_body(
    *,
    rules: list[dict[str, Any]],
    routing_fragment: str,
    summary: dict[str, Any],
) -> str:
    """Compose the rules-update PR body from authored rule docs.

    Pure string assembly so the rendering is unit-testable without git or
    ``gh``. Each rule already carries its own heuristic-confidence caveat,
    so the body adds a short preamble plus the routing fragment a human
    pastes into ``.claude/rules/INDEX.md`` on approval.
    """
    scanned = summary.get("repos_scanned", [])
    scanned_text = ", ".join(scanned) if scanned else "this repository"
    lines = [
        "## Proposed learned review rules",
        "",
        f"Dev10x mined **{len(rules)}** recurring reviewer pattern(s) from "
        f"the merged-PR review history of {scanned_text} and authored a "
        "reference-rule doc for each. Frequencies and false-positive rates "
        "are heuristic estimates — **review each rule before merging**.",
        "",
        "Merging this PR adopts the rules; closing it discards them. The "
        "review bot only proposes — it never enforces a rule without human "
        "approval.",
        "",
        "### Generated rules",
        "",
    ]
    for rule in rules:
        lines.append(f"- `{rule.get('path', '')}` — {rule.get('title', '')}")
    lines.extend(
        [
            "",
            "### Routing",
            "",
            "Add these rows to `.claude/rules/INDEX.md` so the review agents "
            "pick up the generated docs:",
            "",
            routing_fragment,
            "",
        ]
    )
    return "\n".join(lines)


async def _git(
    args: list[str], *, cwd: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return await async_run(args=["git", *args], cwd=cwd, env=env, timeout=60)


async def _prepare_branch(*, branch: str, cwd: str) -> Result[None]:
    """Create or reset the rules-update branch at the current HEAD.

    Uses ``git checkout -B`` so a stale local branch from a previous run is
    reset rather than colliding. The branch is force-pushed later, so a
    fresh local pointer is the only requirement here.
    """
    result = await _git(["checkout", "-B", branch], cwd=cwd)
    if result.returncode != 0:
        return err(result.stderr.strip() or "failed to create rules-update branch")
    return ok(None)


async def _commit_rules(*, generated_dir: str, branch: str, cwd: str) -> Result[None]:
    """Stage the generated rules and commit them on the rules-update branch.

    Returns ``err`` when nothing was staged so the caller can surface a
    "no changes" outcome instead of opening an empty PR.
    """
    add = await _git(["add", "--", generated_dir], cwd=cwd)
    if add.returncode != 0:
        return err(add.stderr.strip() or "git add failed")

    staged = await _git(["diff", "--cached", "--quiet"], cwd=cwd)
    if staged.returncode == 0:
        # Exit 0 from --quiet means no staged changes.
        return err("no_changes")

    # Merge onto os.environ — async_run passes env straight to the
    # subprocess, which REPLACES (not extends) the environment. A bare
    # 4-key dict would drop PATH/HOME and the runner could not find git.
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": _BOT_NAME,
        "GIT_AUTHOR_EMAIL": _BOT_EMAIL,
        "GIT_COMMITTER_NAME": _BOT_NAME,
        "GIT_COMMITTER_EMAIL": _BOT_EMAIL,
    }
    commit = await _git(
        ["commit", "-m", "🤖 Update learned review rules"],
        cwd=cwd,
        env=commit_env,
    )
    if commit.returncode != 0:
        return err(commit.stderr.strip() or "git commit failed")
    return ok(None)


async def _push_branch(*, branch: str, cwd: str) -> Result[None]:
    result = await _git(
        ["push", "--force-with-lease", "origin", branch],
        cwd=cwd,
    )
    if result.returncode != 0:
        return err(result.stderr.strip() or "git push failed")
    return ok(None)


async def _existing_pr_url(*, branch: str, repo: str | None, cwd: str) -> str | None:
    args = ["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"]
    if repo:
        args.extend(["--repo", repo])
    result = await async_run(args=args, cwd=cwd, timeout=30)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


async def _open_pr(
    *,
    branch: str,
    base_branch: str | None,
    repo: str | None,
    title: str,
    body: str,
    cwd: str,
) -> Result[str]:
    """Open the rules-update PR, returning its URL.

    When a PR for ``branch`` already exists, ``gh pr create`` exits
    non-zero; we recover by looking up the open PR's URL so a re-run that
    only refreshes the branch reports the same PR instead of failing.
    """
    body_file = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    body_file.write(body)
    body_file.close()
    body_path = Path(body_file.name)

    args = [
        "gh",
        "pr",
        "create",
        "--head",
        branch,
        "--title",
        title,
        "--body-file",
        str(body_path),
    ]
    if repo:
        args.extend(["--repo", repo])
    if base_branch:
        args.extend(["--base", base_branch])

    try:
        result = await async_run(args=args, cwd=cwd, timeout=60)
    finally:
        body_path.unlink(missing_ok=True)

    if result.returncode == 0:
        url = next(
            (line.strip() for line in result.stdout.splitlines() if line.startswith("http")),
            result.stdout.strip(),
        )
        return ok(url)

    existing = await _existing_pr_url(branch=branch, repo=repo, cwd=cwd)
    if existing:
        return ok(existing)
    return err(result.stderr.strip() or "gh pr create failed")


async def run_learning_loop(
    *,
    base_dir: str,
    repo: str | None = None,
    branch: str = DEFAULT_LEARN_BRANCH,
    base_branch: str | None = None,
    limit: int = 50,
    top_n: int = 20,
    diff_limit: int = 20,
    min_frequency: int = 2,
    max_fp_rate: float = 0.5,
) -> Result[dict[str, Any]]:
    """Mine validated review rules and open a rules-update PR for approval.

    Orchestrates the full continuous-learning loop:

    1. Author reference rules from the repo's merged-PR review history
       (delegates to GH-346→GH-349; no rules ⇒ no PR).
    2. Materialize each rule doc under ``base_dir``.
    3. Branch, commit, and force-push the generated docs.
    4. Open (or reuse) a rules-update PR for human approval.

    Args:
        base_dir: Checked-out repository root where rule docs are written
            and git runs. In the Action this is ``$GITHUB_WORKSPACE``.
        repo: ``owner/name`` to mine and target. Defaults to the current
            repository when omitted.
        branch: Branch the bot force-pushes the proposal to.
        base_branch: PR base. ``None`` lets ``gh`` target the default branch.
        limit: Max merged PRs scanned for review comments.
        top_n: Number of top candidate patterns to consider.
        diff_limit: Max recent merged PRs sampled for diff matching.
        min_frequency: Minimum reviewer frequency for a validated pattern.
        max_fp_rate: Maximum estimated false-positive rate.

    Returns:
        ``ok({"opened_pr": bool, "rules_authored": int, "summary": {...}})``
        — plus ``"pr_url"`` and ``"branch"`` when a PR was opened, or
        ``"reason"`` when none was. ``err(...)`` on a mining, git, or ``gh``
        failure.
    """
    authored = await rule_authoring.author_reference_rules(
        repos=[repo] if repo else None,
        limit=limit,
        top_n=top_n,
        diff_limit=diff_limit,
        min_frequency=min_frequency,
        max_fp_rate=max_fp_rate,
    )
    if not isinstance(authored, SuccessResult):
        return authored

    rules = authored.value["rules"]
    summary = authored.value["summary"]
    routing_fragment = authored.value["routing_fragment"]

    if not rules:
        return ok(
            {
                "opened_pr": False,
                "reason": "no validated review patterns",
                "rules_authored": 0,
                "summary": summary,
            }
        )

    docs = [
        RuleDoc(
            slug=rule["slug"],
            title=rule["title"],
            path=rule["path"],
            content=rule["content"],
        )
        for rule in rules
    ]
    rule_authoring.write_rule_docs(docs=docs, base_dir=Path(base_dir))

    branch_result = await _prepare_branch(branch=branch, cwd=base_dir)
    if not isinstance(branch_result, SuccessResult):
        return branch_result

    commit_result = await _commit_rules(
        generated_dir=rule_authoring.GENERATED_RULES_DIR,
        branch=branch,
        cwd=base_dir,
    )
    if not isinstance(commit_result, SuccessResult):
        if commit_result.error == "no_changes":
            return ok(
                {
                    "opened_pr": False,
                    "reason": "rules already up to date",
                    "rules_authored": len(rules),
                    "summary": summary,
                }
            )
        return commit_result

    push_result = await _push_branch(branch=branch, cwd=base_dir)
    if not isinstance(push_result, SuccessResult):
        return push_result

    plural = "rule" if len(rules) == 1 else "rules"
    pr_result = await _open_pr(
        branch=branch,
        base_branch=base_branch,
        repo=repo,
        title=f"🤖 Propose {len(rules)} learned review {plural}",
        body=render_pr_body(
            rules=rules,
            routing_fragment=routing_fragment,
            summary=summary,
        ),
        cwd=base_dir,
    )
    if not isinstance(pr_result, SuccessResult):
        return pr_result

    return ok(
        {
            "opened_pr": True,
            "pr_url": pr_result.value,
            "branch": branch,
            "rules_authored": len(rules),
            "summary": summary,
        }
    )
