from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dev10x.ci_review import cli_pin, compare, gh_shim, post_steps, runner, workspace
from dev10x.ci_review.guards import evaluate_guards, fetch_pr
from dev10x.ci_review.outbox import read_entries
from dev10x.ci_review.process import run_checked
from dev10x.ci_review.render import RenderedInputs, render_inputs
from dev10x.ci_review.report import elide_prompt, render_comparison, replica_body, summarize
from dev10x.ci_review.usage import usage_report
from dev10x.ci_review.workflow import (
    REVIEW_WORKFLOWS,
    ReviewJob,
    load_review_job,
    would_trigger,
)
from dev10x.core.domain.common.result import ErrorResult, Result, err, ok
from dev10x.core.subprocess_utils import effective_cwd

log = logging.getLogger(__name__)

HYGIENE: str = "hygiene"


@dataclass(frozen=True)
class ReplayOptions:
    pr: int
    workflow: str
    repo: str
    repo_root: Path
    rules: str = "base"
    cli_version: str | None = None
    render_only: bool = False
    keep_workspace: bool = False
    timeout: float = runner.DEFAULT_TIMEOUT_SECONDS
    post: bool = False
    compare_ci: int | None = None


@dataclass(frozen=True)
class ReplayOutcome:
    workflow: str
    run_dir: Path
    failed_guards: list[str]
    cli_version: str
    argv: list[str]
    prompt_path: Path
    report: str | None = None
    notional: bool = False
    trigger_warning: str | None = None
    posted_url: str | None = None


def detect_repo() -> Result[str]:
    found = run_checked(
        args=["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        timeout=60,
    )
    if isinstance(found, ErrorResult):
        return found
    return ok(found.value.strip())


def detect_repo_root() -> Result[Path]:
    found = run_checked(
        args=["git", "rev-parse", "--show-toplevel"],
        cwd=Path(effective_cwd() or os.getcwd()),
        timeout=60,
    )
    if isinstance(found, ErrorResult):
        return found
    return ok(Path(found.value.strip()))


def run_replay(*, options: ReplayOptions, now: datetime | None = None) -> Result[ReplayOutcome]:
    pr_data = fetch_pr(repo=options.repo, number=options.pr)
    if isinstance(pr_data, ErrorResult):
        return pr_data
    base = str(pr_data.value.get("baseRefName", ""))
    refs = workspace.fetch_refs(repo_root=options.repo_root, base=base, pr=options.pr)
    if isinstance(refs, ErrorResult):
        return refs
    workflow_text = _workflow_text(options=options, refs=refs.value)
    if isinstance(workflow_text, ErrorResult):
        return workflow_text
    job = load_review_job(workflow_text=workflow_text.value)
    if isinstance(job, ErrorResult):
        return job
    trigger_warning = _trigger_warning(options=options, refs=refs.value, job=job.value)
    failed = evaluate_guards(pr=pr_data.value, guards=job.value.guards)
    if failed and not options.render_only:
        return err(
            f"CI would skip {options.workflow} on PR #{options.pr}: {', '.join(failed)}",
            failed_guards=failed,
        )
    scripts_ok = workspace.require_base_scripts(
        repo_root=options.repo_root, base=base, base_sha=refs.value.base_sha
    )
    if isinstance(scripts_ok, ErrorResult):
        return scripts_ok
    run_dir = workspace.run_dir_for(
        repo=options.repo,
        pr=options.pr,
        workflow=options.workflow,
        now=now or datetime.now(tz=UTC),
    )
    created = workspace.create_workspace(
        repo_root=options.repo_root, run_dir=run_dir, refs=refs.value
    )
    if isinstance(created, ErrorResult):
        return err(created.error, run_dir=str(run_dir), **created.details)
    try:
        return _replay_in(
            options=options,
            space=created.value,
            job=job.value,
            failed_guards=failed,
            trigger_warning=trigger_warning,
        )
    finally:
        if not options.keep_workspace:
            removed = workspace.remove_workspace(workspace=created.value)
            if isinstance(removed, ErrorResult):
                log.warning("could not remove %s: %s", created.value.checkout, removed.error)


def _workflow_text(*, options: ReplayOptions, refs: workspace.Refs) -> Result[str]:
    path = f".github/workflows/{REVIEW_WORKFLOWS[options.workflow]}"
    base_text = workspace.read_blob(repo_root=options.repo_root, sha=refs.base_sha, path=path)
    if isinstance(base_text, ErrorResult):
        return base_text
    merge_text = workspace.read_blob(repo_root=options.repo_root, sha=refs.merge_sha, path=path)
    if isinstance(merge_text, ErrorResult):
        return merge_text
    if base_text.value != merge_text.value:
        log.warning(
            "%s differs from the base branch; CI skips the review on a PR that edits "
            "its own workflow, and the replay uses the %s copy",
            path,
            "PR" if options.rules == "head" else "base",
        )
    return merge_text if options.rules == "head" else base_text


def _trigger_warning(
    *,
    options: ReplayOptions,
    refs: workspace.Refs,
    job: ReviewJob,
) -> str | None:
    if not job.paths and not job.paths_ignore:
        return None
    files = workspace.changed_files(repo_root=options.repo_root, merge_sha=refs.merge_sha)
    if isinstance(files, ErrorResult):
        log.warning("could not list PR #%s's changed files: %s", options.pr, files.error)
        return None
    if would_trigger(files=files.value, paths=job.paths, paths_ignore=job.paths_ignore):
        return None
    return (
        f"none of PR #{options.pr}'s {len(files.value)} changed files match the "
        f"{options.workflow} workflow's paths filter; CI would never have triggered it"
    )


def _replay_in(
    *,
    options: ReplayOptions,
    space: workspace.Workspace,
    job: ReviewJob,
    failed_guards: list[str],
    trigger_warning: str | None,
) -> Result[ReplayOutcome]:
    staged = workspace.apply_rules(
        workspace=space, rules=options.rules, keep_pr_head=job.keep_pr_head
    )
    if isinstance(staged, ErrorResult):
        return _with_run_dir(error=staged, run_dir=space.run_dir)
    gathered = workspace.gather_context(workspace=space, repo=options.repo, pr=options.pr)
    if isinstance(gathered, ErrorResult):
        return _with_run_dir(error=gathered, run_dir=space.run_dir)
    prior_comment_id: int | None = None
    if options.workflow == HYGIENE:
        prior = workspace.write_prior_hygiene_comment(checkout=space.checkout)
        if isinstance(prior, ErrorResult):
            return _with_run_dir(error=prior, run_dir=space.run_dir)
        prior_comment_id = prior.value
    rendered = render_inputs(
        scripts=space.scripts,
        checkout=space.checkout,
        build_inputs=job.build_inputs,
        repo=options.repo,
        pr=options.pr,
        output=space.run_dir / "inputs.out",
    )
    if isinstance(rendered, ErrorResult):
        return _with_run_dir(error=rendered, run_dir=space.run_dir)
    prompt_path = space.run_dir / "prompt.md"
    prompt_path.write_text(rendered.value.prompt, encoding="utf-8")
    version = cli_pin.resolve_cli_version(
        explicit=options.cli_version,
        environ=dict(os.environ),
        owner=options.repo.split("/", 1)[0],
        repo=options.repo,
    )
    if isinstance(version, ErrorResult):
        return _with_run_dir(error=version, run_dir=space.run_dir)
    context = _RunContext(
        options=options,
        space=space,
        rendered=rendered.value,
        version=version.value,
        prompt_path=prompt_path,
        failed_guards=failed_guards,
        prior_comment_id=prior_comment_id,
        trigger_warning=trigger_warning,
    )
    if options.render_only:
        return ok(context.outcome(claude=cli_pin.cli_binary(version=version.value)))
    return _run_model(context=context)


@dataclass(frozen=True)
class _RunContext:
    options: ReplayOptions
    space: workspace.Workspace
    rendered: RenderedInputs
    version: str
    prompt_path: Path
    failed_guards: list[str]
    prior_comment_id: int | None
    trigger_warning: str | None

    def invocation(self, *, claude: Path, real_gh: str, auth: runner.Auth) -> runner.Invocation:
        return runner.build_invocation(
            claude=claude,
            prompt=self.rendered.prompt,
            claude_args=self.rendered.claude_args,
            run_dir=self.space.run_dir,
            checkout=self.space.checkout,
            home=os.environ.get("HOME") or str(Path.home()),
            repo=self.options.repo,
            pr=self.options.pr,
            real_gh=real_gh,
            auth=auth,
            node_dir=runner.node_dir(),
        )

    def outcome(
        self,
        *,
        claude: Path,
        real_gh: str = "gh",
        auth: runner.Auth | None = None,
        report: str | None = None,
        posted_url: str | None = None,
    ) -> ReplayOutcome:
        used_auth = auth or runner.Auth(env={}, notional=False)
        invocation = self.invocation(claude=claude, real_gh=real_gh, auth=used_auth)
        return ReplayOutcome(
            workflow=self.options.workflow,
            run_dir=self.space.run_dir,
            failed_guards=self.failed_guards,
            cli_version=self.version,
            argv=elide_prompt(argv=invocation.argv, prompt=self.rendered.prompt),
            prompt_path=self.prompt_path,
            report=report,
            notional=used_auth.notional,
            trigger_warning=self.trigger_warning,
            posted_url=posted_url,
        )


def _run_model(*, context: _RunContext) -> Result[ReplayOutcome]:
    run_dir = context.space.run_dir
    binary = cli_pin.ensure_cli(version=context.version)
    if isinstance(binary, ErrorResult):
        return _with_run_dir(error=binary, run_dir=run_dir)
    real_gh = shutil.which("gh")
    if real_gh is None:
        return err("gh is not on PATH; the replay needs it for reads", run_dir=str(run_dir))
    gh_shim.write_shim(bin_dir=run_dir / "bin", python=sys.executable, real_gh=real_gh)
    runner.write_mcp_config(
        run_dir=run_dir, inline=context.rendered.uses_inline_comments, python=sys.executable
    )
    auth = runner.resolve_auth(environ=dict(os.environ), config_dir=run_dir / "config")
    if isinstance(auth, ErrorResult):
        return _with_run_dir(error=auth, run_dir=run_dir)
    invocation = context.invocation(claude=binary.value, real_gh=real_gh, auth=auth.value)
    execution = runner.run_claude(
        invocation=invocation, run_dir=run_dir, timeout=context.options.timeout
    )
    if isinstance(execution, ErrorResult):
        return _with_run_dir(error=execution, run_dir=run_dir)
    outbox = run_dir / "outbox.jsonl"
    if context.options.workflow == HYGIENE:
        posted = post_steps.hygiene_post_step(
            checkout=context.space.checkout,
            outbox=outbox,
            repo=context.options.repo,
            pr=context.options.pr,
            prior_comment_id=context.prior_comment_id,
        )
        if isinstance(posted, ErrorResult):
            return _with_run_dir(error=posted, run_dir=run_dir)
    else:
        post_steps.code_review_post_steps(
            outbox=outbox, repo=context.options.repo, pr=context.options.pr
        )
    entries = read_entries(path=outbox)
    report = summarize(
        workflow=context.options.workflow,
        failed_guards=context.failed_guards,
        cli_version=context.version,
        usage=usage_report(execution=execution.value, notional=auth.value.notional),
        entries=entries,
    )
    report_path = run_dir / "report.md"
    # The model run is paid for: its report is on disk before anything else can fail.
    report_path.write_text(report, encoding="utf-8")
    if context.options.compare_ci is not None:
        section = "\n" + _comparison(
            options=context.options, run_id=context.options.compare_ci, entries=entries
        )
        with report_path.open("a", encoding="utf-8") as report_file:
            report_file.write(section)
        report += section
    posted_url: str | None = None
    if context.options.post:
        body_path = run_dir / "replica-comment.md"
        body_path.write_text(
            replica_body(workflow=context.options.workflow, report=report, entries=entries),
            encoding="utf-8",
        )
        shared = post_steps.post_replica(
            repo=context.options.repo, pr=context.options.pr, body_path=body_path
        )
        if isinstance(shared, ErrorResult):
            return _with_run_dir(error=shared, run_dir=run_dir)
        posted_url = shared.value
    return ok(
        context.outcome(
            claude=binary.value,
            real_gh=real_gh,
            auth=auth.value,
            report=report,
            posted_url=posted_url,
        )
    )


def _comparison(
    *,
    options: ReplayOptions,
    run_id: int,
    entries: list[dict[str, Any]],
) -> str:
    ci = compare.fetch_ci_posted(repo=options.repo, pr=options.pr, run_id=run_id)
    if isinstance(ci, ErrorResult):
        return f"### Compared with CI run {run_id}\n\n- Comparison unavailable: {ci.error}\n"
    return render_comparison(comparison=compare.compare(entries=entries, ci=ci.value))


def _with_run_dir(*, error: ErrorResult, run_dir: Path) -> ErrorResult:
    return err(error.error, run_dir=str(run_dir), **error.details)
