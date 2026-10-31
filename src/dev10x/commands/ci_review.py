from __future__ import annotations

import shlex
import sys
from typing import NoReturn

import click

from dev10x.core.domain.common.result import ErrorResult

_WORKFLOW_CHOICES: tuple[str, ...] = ("code-review", "hygiene", "all")
_ALL_ORDER: tuple[str, ...] = ("hygiene", "code-review")


@click.command(name="ci-review")
@click.option("--pr", "pr", type=int, required=True, help="Pull request number.")
@click.option(
    "--workflow",
    type=click.Choice(_WORKFLOW_CHOICES),
    default="code-review",
    show_default=True,
    help="Which Claude CI review to replay; `all` runs hygiene, then code-review.",
)
@click.option("--repo", default=None, help="owner/name (default: the current gh repo).")
@click.option(
    "--rules",
    type=click.Choice(("base", "head")),
    default="base",
    show_default=True,
    help="base: instructions from the base branch, as CI. head: the PR's own.",
)
@click.option("--cli-version", default=None, help="Claude CLI version (default: as CI).")
@click.option(
    "--render-only",
    is_flag=True,
    help="Resolve guards, CLI version and argv, write the prompt; no model call.",
)
@click.option("--keep-workspace", is_flag=True, help="Keep the checkout worktree.")
@click.option(
    "--timeout",
    type=int,
    default=1800,
    show_default=True,
    help="Seconds the model run may take.",
)
def ci_review(
    *,
    pr: int,
    workflow: str,
    repo: str | None,
    rules: str,
    cli_version: str | None,
    render_only: bool,
    keep_workspace: bool,
    timeout: int,
) -> None:
    """Replay the Claude CI review of a PR locally, as a dry run.

    Nothing is posted to GitHub: every write the review would make is
    recorded to outbox.jsonl in the run directory (GH-1621).
    """
    from dev10x.ci_review import ReplayOptions, run_replay
    from dev10x.ci_review.replay import detect_repo, detect_repo_root

    repo_root = detect_repo_root()
    if isinstance(repo_root, ErrorResult):
        _fail(error=repo_root)
    if repo is None:
        detected = detect_repo()
        if isinstance(detected, ErrorResult):
            _fail(error=detected)
        repo = detected.value
    workflows = _ALL_ORDER if workflow == "all" else (workflow,)
    for name in workflows:
        result = run_replay(
            options=ReplayOptions(
                pr=pr,
                workflow=name,
                repo=repo,
                repo_root=repo_root.value,
                rules=rules,
                cli_version=cli_version,
                render_only=render_only,
                keep_workspace=keep_workspace,
                timeout=timeout,
            )
        )
        if isinstance(result, ErrorResult):
            _fail(error=result)
        outcome = result.value
        guards = ", ".join(outcome.failed_guards) or "all pass"
        click.echo(f"== {outcome.workflow} ==")
        click.echo(f"guards: {guards}")
        click.echo(f"claude cli: {outcome.cli_version}")
        click.echo(f"argv: {shlex.join(outcome.argv)}")
        click.echo(f"prompt: {outcome.prompt_path}")
        if outcome.report is not None:
            click.echo(outcome.report)
        click.echo(f"run dir: {outcome.run_dir}")


def _fail(*, error: ErrorResult) -> NoReturn:
    click.echo(f"❌ {error.error}", err=True)
    for key in ("stderr", "run_dir"):
        if error.details.get(key):
            click.echo(f"   {key}: {error.details[key]}", err=True)
    sys.exit(1)
