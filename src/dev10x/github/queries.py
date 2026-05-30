"""Reusable GraphQL query shapes for GitHub PR status fetches.

`PRStatusQuery` centralises the field set that `pr_notify`,
`ci_check_status`, and release-notes collection all need today.
Each caller previously built its own ad-hoc query (or fell back
to per-PR `gh pr view` subprocess fan-out); this module exposes
a single source of truth so they can share one query body and,
via `batch_find_prs()`, one GraphQL request.

Scope (GH-146 #I5/#I6):

- ``PRStatusQuery`` — generate single-PR or multi-PR query bodies
  using GraphQL field aliases for the batch form.
- ``batch_find_prs(numbers, repo=...)`` — execute one GraphQL
  request and return ``dict[int, PRStatus]``, replacing the
  N-subprocess fan-out used by ``collect_prs.py``.

The status field set is intentionally small: only what current
callers consume. Add fields here when a new caller actually needs
them — speculative additions inflate every batch request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from dev10x.domain.common.repository_ref import RepositoryRef
from dev10x.domain.common.result import Result, err, ok

_PR_FIELDS = " ".join(
    [
        "number",
        "title",
        "state",
        "isDraft",
        "mergedAt",
        "headRefName",
        "baseRefName",
        "mergeable",
        "reviewDecision",
        "url",
    ]
)


@dataclass(frozen=True)
class PRStatus:
    """Snapshot of the PR fields shared callers care about.

    Mirrors the GraphQL ``PullRequest`` node restricted to the
    columns ``pr_notify``, ``ci_check_status``, and
    ``collect_prs`` actually consume.
    """

    number: int
    title: str
    state: str
    is_draft: bool
    merged_at: str | None
    head_ref_name: str
    base_ref_name: str
    mergeable: str | None
    review_decision: str | None
    url: str

    @classmethod
    def from_node(cls, node: dict[str, Any]) -> PRStatus:
        return cls(
            number=int(node["number"]),
            title=node.get("title", ""),
            state=node.get("state", ""),
            is_draft=bool(node.get("isDraft", False)),
            merged_at=node.get("mergedAt"),
            head_ref_name=node.get("headRefName", ""),
            base_ref_name=node.get("baseRefName", ""),
            mergeable=node.get("mergeable"),
            review_decision=node.get("reviewDecision"),
            url=node.get("url", ""),
        )


@dataclass(frozen=True)
class PRStatusQuery:
    """Build GraphQL bodies that fetch ``PRStatus`` fields.

    Both ``for_pr`` and ``for_prs`` return self-contained query
    strings ready for ``gh api graphql -f query=...``. The batch
    form uses GraphQL aliases (``pr123: pullRequest(number: 123)``)
    so one request returns every requested PR.
    """

    repo: RepositoryRef

    def for_pr(self, *, number: int) -> str:
        return (
            "query { "
            f"repository(owner: {json.dumps(self.repo.owner)}, "
            f"name: {json.dumps(self.repo.name)}) "
            f"{{ pullRequest(number: {number}) {{ {_PR_FIELDS} }} }} "
            "}"
        )

    def for_prs(self, *, numbers: list[int]) -> str:
        unique_numbers = sorted({int(n) for n in numbers})
        if not unique_numbers:
            raise ValueError("PRStatusQuery.for_prs requires at least one PR number")
        aliased = " ".join(
            f"{self._alias_for(number=n)}: pullRequest(number: {n}) {{ {_PR_FIELDS} }}"
            for n in unique_numbers
        )
        return (
            "query { "
            f"repository(owner: {json.dumps(self.repo.owner)}, "
            f"name: {json.dumps(self.repo.name)}) "
            f"{{ {aliased} }} "
            "}"
        )

    @staticmethod
    def _alias_for(*, number: int) -> str:
        return f"pr{number}"

    @classmethod
    def parse_single(cls, *, data: dict[str, Any]) -> PRStatus | None:
        node = data.get("data", {}).get("repository", {}).get("pullRequest")
        if node is None:
            return None
        return PRStatus.from_node(node=node)

    @classmethod
    def parse_batch(
        cls,
        *,
        data: dict[str, Any],
        numbers: list[int],
    ) -> dict[int, PRStatus]:
        repo_node = data.get("data", {}).get("repository", {}) or {}
        out: dict[int, PRStatus] = {}
        for number in numbers:
            alias = cls._alias_for(number=number)
            node = repo_node.get(alias)
            if node is None:
                continue
            out[int(number)] = PRStatus.from_node(node=node)
        return out


async def batch_find_prs(
    *,
    numbers: list[int],
    repo: str,
) -> Result[dict[int, PRStatus]]:
    """Fetch status for many PRs in one GraphQL request.

    Replaces the per-PR ``gh pr view`` fan-out used today by
    ``collect_prs.py``. An empty ``numbers`` list short-circuits
    to ``ok({})`` so callers can pass through filtered batches
    without an extra ``if`` guard.
    """
    if not numbers:
        return ok({})

    from dev10x.github import _gh_api_raw

    repo_ref = RepositoryRef.parse(repo)
    query = PRStatusQuery(repo=repo_ref).for_prs(numbers=numbers)
    result = await _gh_api_raw("graphql", fields={"query": query})
    if result.returncode != 0:
        return err(result.stderr.strip())
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return err(f"Invalid JSON from gh api graphql: {exc}")
    return ok(PRStatusQuery.parse_batch(data=data, numbers=numbers))
