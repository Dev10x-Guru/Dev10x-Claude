from __future__ import annotations

import shlex
import sys
from pathlib import Path
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
@click.option(
    "--post",
    is_flag=True,
    help="Post the replica to the PR as you, marked as a local replica (GH-1721).",
)
@click.option(
    "--compare-ci",
    "compare_ci",
    type=int,
    default=None,
    metavar="RUN_ID",
    help="Compare the findings with what this CI code-review run posted.",
)
@click.option(
    "--post-run-dir",
    "post_run_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Post the replica of a finished run directory; no new model run (GH-1762).",
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
    post: bool,
    compare_ci: int | None,
    post_run_dir: Path | None,
) -> None:
    """Replay the Claude CI review of a PR locally.

    The review's own writes are recorded to outbox.jsonl in the run
    directory, never posted (GH-1621). Only --post publishes, as one
    comment marked as a local replica (GH-1721); --post-run-dir
    publishes a run that already finished, after its report was read
    (GH-1762).
    """
    from dev10x.ci_review import ReplayOptions, run_replay
    from dev10x.ci_review.replay import detect_repo, detect_repo_root

    if post_run_dir is not None and (post or render_only or compare_ci is not None):
        raise click.UsageError(
            "--post-run-dir posts a finished run; drop --post, --render-only and --compare-ci"
        )
    if render_only and (post or compare_ci is not None):
        raise click.UsageError("--post and --compare-ci need a model run; drop --render-only")
    if compare_ci is not None and workflow != "code-review":
        raise click.UsageError("--compare-ci compares inline findings: use --workflow code-review")
    repo_root = detect_repo_root()
    if isinstance(repo_root, ErrorResult):
        _fail(error=repo_root)
    if repo is None:
        detected = detect_repo()
        if isinstance(detected, ErrorResult):
            _fail(error=detected)
        repo = detected.value
    if post_run_dir is not None:
        _post_finished_run(run_dir=post_run_dir, repo=repo, pr=pr)
        return
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
                post=post,
                compare_ci=compare_ci,
            )
        )
        if isinstance(result, ErrorResult):
            _fail(error=result)
        outcome = result.value
        guards = ", ".join(outcome.failed_guards) or "all pass"
        click.echo(f"== {outcome.workflow} ==")
        if outcome.trigger_warning is not None:
            click.echo(f"⚠️ {outcome.trigger_warning}")
        click.echo(f"guards: {guards}")
        click.echo(f"claude cli: {outcome.cli_version}")
        click.echo(f"argv: {shlex.join(outcome.argv)}")
        click.echo(f"prompt: {outcome.prompt_path}")
        if outcome.report is not None:
            click.echo(outcome.report)
        if outcome.posted_url is not None:
            click.echo(f"posted: {outcome.posted_url}")
        click.echo(f"run dir: {outcome.run_dir}")


def _post_finished_run(*, run_dir: Path, repo: str, pr: int) -> None:
    from dev10x.ci_review.share import post_finished_run

    posted = post_finished_run(run_dir=run_dir, repo=repo, pr=pr)
    if isinstance(posted, ErrorResult):
        _fail(error=posted)
    click.echo(f"posted: {posted.value}")
    click.echo(f"run dir: {run_dir}")


def _fail(*, error: ErrorResult) -> NoReturn:
    click.echo(f"❌ {error.error}", err=True)
    for key in ("stderr", "run_dir"):
        if error.details.get(key):
            click.echo(f"   {key}: {error.details[key]}", err=True)
    sys.exit(1)
