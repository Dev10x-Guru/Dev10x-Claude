"""Validator: ship actions need a review stamp at the PR head (DX019, GH-1830).

The pre-merge checks in ``dev10x:gh-pr-merge`` are skill text, and a long
or compacted session can skip them: a field-tested workflow recorded a PR
merged with no review because the session forgot. This validator moves
the one check that matters most into a hook. ``merge_pr``, ``pr_ready``
and ``request_review`` are denied unless a clean ``dev10x:review`` round
stamped the PR's current head (see ``dev10x.domain.review_stamp``).

Scope:

* Only the three MCP tools are gated. Raw ``gh pr merge`` / ``gh pr
  ready`` are already routed to them by the skill-redirect hook.
* ``pr_ready(undo=true)`` returns a PR to draft and is never gated.
* The gate applies only where the repo's ``friction.yaml`` entry says
  ``review_stamp: required``; absent or ``none`` leaves the tools alone,
  so installing the plugin never walls a repo that does not use
  ``dev10x:review``. The setting is read the way DX017 reads its own:
  file reads only, worktree first, main checkout second.
* The gate applies when either the hook's own checkout or an absolute
  ``tool_input.cwd`` checkout requires it, so a caller-chosen ``cwd``
  cannot lift it. ``gh`` and ``git`` run in the ``tool_input.cwd``
  checkout when there is one, else the hook's. The PR — its head SHA,
  branch and ``owner/repo`` —
  comes from ``gh pr view`` on ``tool_input.pr_number`` (and
  ``tool_input.repo`` when given), so the stamp is matched against the
  PR the call names, not against whatever the session has checked out.

``gh`` costs one network call, which is affordable here: these tools run
a handful of times per PR, unlike the Bash chain under the latency gate.
When the head cannot be read the validator denies: a wall that opens on
an error is not a wall. ``DEV10X_HOOK_DISABLE=DX019`` is the escape.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from dev10x import subprocess_utils
from dev10x.domain import HookInput, HookResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.friction_yaml import load_checkout_prefs
from dev10x.domain.profile_tier import ProfileTier
from dev10x.domain.review_stamp import (
    ReviewStampStore,
    evaluate_stamp,
    repo_slug_from_pr_url,
)
from dev10x.validators.base import ValidatorBase

log = logging.getLogger(__name__)

_TOOL_PREFIX = "mcp__plugin_dev10x_cli__"
GATED_TOOLS = frozenset(
    f"{_TOOL_PREFIX}{name}" for name in ("merge_pr", "pr_ready", "request_review")
)
PREFS_KEY = "review_stamp"
REQUIRED = "required"

_GH_TIMEOUT_SECONDS = 15.0
_GIT_TIMEOUT_SECONDS = 5.0
_SUBPROCESS_FAILURES = (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)

_RERUN_HINT = (
    "Run `dev10x:review --loop` on that branch at this head; a clean round "
    "records the stamp through `review_stamp_write`. To lift the gate for "
    "this repo set `review_stamp: none` in its friction.yaml entry, or for "
    "this session `DEV10X_HOOK_DISABLE=DX019`."
)


@dataclass(frozen=True)
class PrHead:
    sha: str
    branch: str
    slug: str


def _tool_input(*, inp: HookInput) -> dict[str, Any]:
    value = inp.raw.get("tool_input")
    return value if isinstance(value, dict) else {}


def _find_checkout(*, start: str) -> Path | None:
    if not start:
        return None
    here = Path(start)
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _checkouts(*, inp: HookInput) -> tuple[Path | None, Path | None]:
    """``(tool checkout, hook checkout)`` — either may be ``None``.

    The tool checkout comes from an absolute ``tool_input.cwd``; the hook
    checkout from the session's own working directory. Both are kept so a
    caller-chosen ``cwd`` can redirect where the PR is read, but never
    lift a gate the session's repo requires.
    """
    requested = _tool_input(inp=inp).get("cwd")
    tool_checkout = (
        _find_checkout(start=requested)
        if isinstance(requested, str) and Path(requested).is_absolute()
        else None
    )
    return tool_checkout, _find_checkout(start=inp.cwd)


def _gate_required(*, checkout: Path) -> bool:
    return load_checkout_prefs(checkout=checkout).get(PREFS_KEY) == REQUIRED


def _pr_head(*, pr_number: int, repo: str | None, checkout: Path) -> PrHead | None:
    command = ["gh", "pr", "view", str(pr_number), "--json", "headRefOid,headRefName,url"]
    if repo:
        command += ["--repo", repo]
    try:
        result = subprocess_utils.run(
            command,
            cwd=str(checkout),
            capture_output=True,
            text=True,
            check=True,
            timeout=_GH_TIMEOUT_SECONDS,
        )
        payload = json.loads(result.stdout)
    except (*_SUBPROCESS_FAILURES, json.JSONDecodeError):
        log.warning("gh pr view failed for PR #%s", pr_number, exc_info=True)
        return None
    if not isinstance(payload, dict):
        log.warning("gh pr view returned a non-object payload for PR #%s", pr_number)
        return None
    slug = repo_slug_from_pr_url(url=str(payload.get("url", "")))
    sha = payload.get("headRefOid")
    branch = payload.get("headRefName")
    if not (slug and isinstance(sha, str) and sha and isinstance(branch, str) and branch):
        return None
    return PrHead(sha=sha, branch=branch, slug=slug)


def _tree_sha(*, commit: str, checkout: Path) -> str | None:
    try:
        result = subprocess_utils.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{tree}}"],
            cwd=str(checkout),
            capture_output=True,
            text=True,
            check=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except _SUBPROCESS_FAILURES:
        log.info("PR head %s is not in the local object store", commit, exc_info=True)
        return None
    return result.stdout.strip() or None


def _deny(*, tool: str, reason: str) -> HookResult:
    return HookResult(
        message=f"🛑 Review stamp gate (DX019): `{tool}` blocked — {reason}\n{_RERUN_HINT}"
    )


@dataclass
class ReviewStampValidator(ValidatorBase):
    """Deny ship actions whose PR head carries no clean-review stamp."""

    name: ClassVar[str] = "review-stamp"
    rule_id: ClassVar[str] = "DX019"
    profile: ClassVar[ProfileTier] = ProfileTier.STANDARD
    experimental: ClassVar[bool] = False

    def should_run(self, inp: HookInput) -> bool:
        if inp.tool_name not in GATED_TOOLS:
            return False
        is_undo = _tool_input(inp=inp).get("undo") is True
        return not (inp.tool_name.endswith("__pr_ready") and is_undo)

    def validate(self, inp: HookInput) -> HookResult | None:
        """Run the check; an unexpected error denies instead of allowing.

        DX019 is a STANDARD-tier validator, and ``ValidatorChain`` swallows
        an exception from any tier but MINIMAL — which would let the ship
        call through. The wall must not open on its own failure.
        """
        try:
            return self._validate(inp=inp)
        except Exception as exc:
            log.error("DX019 review stamp check failed", exc_info=True)
            return _deny(
                tool=inp.tool_name.removeprefix(_TOOL_PREFIX),
                reason=f"the review stamp check failed ({exc!r}). Please try again.",
            )

    def _validate(self, inp: HookInput) -> HookResult | None:
        tool_checkout, hook_checkout = _checkouts(inp=inp)
        candidates = [found for found in (tool_checkout, hook_checkout) if found is not None]
        if not any(_gate_required(checkout=found) for found in candidates):
            return None
        checkout = candidates[0]

        tool = inp.tool_name.removeprefix(_TOOL_PREFIX)
        tool_input = _tool_input(inp=inp)
        pr_number = tool_input.get("pr_number")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool):
            return _deny(tool=tool, reason="no integer `pr_number` to check the stamp against.")

        repo = tool_input.get("repo")
        head = _pr_head(
            pr_number=pr_number,
            repo=repo if isinstance(repo, str) and repo else None,
            checkout=checkout,
        )
        if head is None:
            return _deny(
                tool=tool,
                reason=f"could not read the head of PR #{pr_number} with `gh pr view`. "
                "Please try again once GitHub is reachable.",
            )

        stamp = ReviewStampStore(path=Dev10xConfigDir.review_stamps_json()).read(
            slug=head.slug, branch=head.branch
        )
        if stamp is None:
            return _deny(
                tool=tool,
                reason=(
                    f"PR #{pr_number} ({head.slug}, branch `{head.branch}`) has no "
                    f"review stamp; its head is {head.sha}."
                ),
            )
        head_tree_sha = _tree_sha(commit=head.sha, checkout=checkout)
        verdict = evaluate_stamp(stamp=stamp, head_sha=head.sha, head_tree_sha=head_tree_sha)
        if verdict.passes:
            return None
        content = (
            "different content"
            if head_tree_sha
            else "content this checkout cannot compare (run `git fetch` and retry)"
        )
        return _deny(
            tool=tool,
            reason=(
                f"the review stamp for PR #{pr_number} ({head.slug}, branch "
                f"`{head.branch}`) covers {stamp.head_sha}, but the PR head is "
                f"{head.sha} with {content}."
            ),
        )
