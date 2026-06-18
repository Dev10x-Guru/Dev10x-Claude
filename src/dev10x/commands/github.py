"""``dev10x github`` — GitHub review helpers usable from CI (GH-352).

The installable PR-review Action (``action.yml``) shells out to
``dev10x github review-rules`` to mine the consumer repository's own
merged-PR review history into a learned-rules Markdown digest. That
digest is fed into the review prompt alongside the bundled,
repo-agnostic reviewer checklist so an external repo gets review quality
close to the internal multi-agent pipeline.

This command is the CLI seam over
:func:`dev10x.github.rule_authoring.author_reference_rules`, which was
previously reachable only through the MCP boundary. Per ADR-0010 the
domain function returns ``Result[T]`` and stays side-effect free; this
entry point owns stdout and the process exit code.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import click

_RULE_SEPARATOR = "\n\n---\n\n"

_NO_RULES_DIGEST = "\n".join(
    [
        "# Learned review rules",
        "",
        "_No validated review-comment patterns were found in this "
        "repository's recent merged PRs. Review proceeds with the bundled "
        "reviewer checklist only._",
        "",
    ]
)


@click.group()
def github() -> None:
    """GitHub review helpers (learned-rule mining for the review Action)."""


def _render_digest(*, rules: list[dict[str, Any]], routing_fragment: str) -> str:
    """Compose the learned-rules Markdown digest from authored rule docs.

    Pure string assembly so the rendering is unit-testable without
    touching ``gh``. Each rule doc already carries its own heuristic
    confidence caveat, so the digest only adds a short preamble.
    """
    if not rules:
        return _NO_RULES_DIGEST

    bodies = [str(rule.get("content", "")).rstrip() for rule in rules]
    return "\n".join(
        [
            "# Learned review rules",
            "",
            f"> Mined from this repository's merged-PR review history "
            f"({len(rules)} validated pattern(s)). Frequencies and "
            "false-positive rates are heuristic estimates — treat them as "
            "signals, not measured precision.",
            "",
            _RULE_SEPARATOR.join(bodies),
            "",
            "## Routing",
            "",
            routing_fragment,
            "",
        ]
    )


@github.command(name="review-rules")
@click.option(
    "--repo",
    default=None,
    help="owner/name to mine. Defaults to the current repository.",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Max merged PRs scanned for review comments.",
)
@click.option(
    "--min-frequency",
    type=int,
    default=2,
    show_default=True,
    help="Minimum reviewer frequency for a validated pattern.",
)
@click.option(
    "--max-fp-rate",
    type=float,
    default=0.5,
    show_default=True,
    help="Maximum estimated false-positive rate for a validated pattern.",
)
def review_rules(
    *,
    repo: str | None,
    limit: int,
    min_frequency: int,
    max_fp_rate: float,
) -> None:
    """Print a learned-rules Markdown digest from validated review patterns.

    Wraps :func:`dev10x.github.rule_authoring.author_reference_rules` and
    emits a self-contained Markdown document on stdout. When no pattern
    validates, a clear placeholder digest is emitted (exit 0) so the
    Action always has a readable file to feed the review prompt. A genuine
    mining failure (e.g. ``gh`` auth error) prints the message to stderr
    and exits non-zero so the Action can degrade gracefully.
    """
    from dev10x.domain.common.result import SuccessResult
    from dev10x.github import rule_authoring

    result = asyncio.run(
        rule_authoring.author_reference_rules(
            repos=[repo] if repo else None,
            limit=limit,
            min_frequency=min_frequency,
            max_fp_rate=max_fp_rate,
        )
    )

    if not isinstance(result, SuccessResult):
        click.echo(f"[ERROR] {result.error}", err=True)
        sys.exit(1)

    click.echo(
        _render_digest(
            rules=result.value["rules"],
            routing_fragment=result.value["routing_fragment"],
        )
    )


@github.command(name="learn")
@click.option(
    "--repo",
    default=None,
    help="owner/name to mine and target. Defaults to the current repository.",
)
@click.option(
    "--base-dir",
    default=None,
    help="Checked-out repo root where rule docs are written and git runs. "
    "Defaults to the current directory ($GITHUB_WORKSPACE in the Action).",
)
@click.option(
    "--branch",
    default=None,
    help="Branch the rules-update PR is force-pushed to.",
)
@click.option(
    "--base",
    "base_branch",
    default=None,
    help="PR base branch. Defaults to the repository's default branch.",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Max merged PRs scanned for review comments.",
)
@click.option(
    "--min-frequency",
    type=int,
    default=2,
    show_default=True,
    help="Minimum reviewer frequency for a validated pattern.",
)
@click.option(
    "--max-fp-rate",
    type=float,
    default=0.5,
    show_default=True,
    help="Maximum estimated false-positive rate for a validated pattern.",
)
def learn(
    *,
    repo: str | None,
    base_dir: str | None,
    branch: str | None,
    base_branch: str | None,
    limit: int,
    min_frequency: int,
    max_fp_rate: float,
) -> None:
    """Run the continuous learning loop: mine rules, open a rules-update PR.

    Wraps :func:`dev10x.github.learn_loop.run_learning_loop`. On a closed
    PR the Action invokes this to harvest the repository's recurring
    reviewer patterns into validated reference rules and open a PR
    proposing them for human approval. When no pattern validates (or the
    proposal is already up to date) it prints a notice and exits 0 so the
    Action's learn step is a no-op rather than a failure. A genuine mining,
    git, or ``gh`` failure prints to stderr and exits non-zero.
    """
    import os

    from dev10x.domain.common.result import SuccessResult
    from dev10x.github import learn_loop

    result = asyncio.run(
        learn_loop.run_learning_loop(
            base_dir=base_dir or os.getcwd(),
            repo=repo,
            branch=branch or learn_loop.DEFAULT_LEARN_BRANCH,
            base_branch=base_branch,
            limit=limit,
            min_frequency=min_frequency,
            max_fp_rate=max_fp_rate,
        )
    )

    if not isinstance(result, SuccessResult):
        click.echo(f"[ERROR] {result.error}", err=True)
        sys.exit(1)

    if result.value["opened_pr"]:
        click.echo(
            f"Opened rules-update PR with {result.value['rules_authored']} "
            f"rule(s): {result.value['pr_url']}"
        )
    else:
        click.echo(f"No rules-update PR opened: {result.value['reason']}.")
