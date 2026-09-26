"""GitHub MCP tool implementations, one module per capability (ADR-0027).

Each function takes explicit parameters and returns Result types. All
public functions are async to avoid blocking the MCP event loop.

**Pattern: Gateway** (Fowler, *PoEAA*). This package is the Gateway to
the GitHub external system: every call to the ``gh`` CLI and the GitHub
REST/GraphQL APIs is funnelled through ``_gateway`` (``_gh_api_raw`` /
``async_run`` / ``async_run_script``), giving callers a uniform Python
surface and a single place to inject auth (``as_bot`` bot-token
routing) and the effective working directory. ADR-0006 records the
decision to keep this internal Gateway instead of the official GitHub
MCP server; ADR-0013 names the pattern across this package and
``subprocess_utils``.

**One seam per dependency (ADR-0027 D2).** Capability modules call a
dependency through its defining module — ``_gateway.async_run(...)``,
``pulls.pr_get(...)`` — never through a name bound by ``from ... import``.
A test therefore patches the defining module, and that one patch
intercepts every caller. ``tests/github/test_github_split.py`` fails a
test that patches a re-export on this facade while package code looks the
name up elsewhere.

This module only re-exports: production callers (``mcp/github_tools.py``,
``mcp/gate_query.py``, ``skills/notifications/_gh.py``) keep importing
from ``dev10x.github``.
"""

from __future__ import annotations

from dev10x.github._gateway import (
    _GH_RETRY_POLICY,
    _bot_env,
    _detect_repo,
    _gh_api,
    _gh_api_raw,
    _parse_gh_api_result,
    _resolve_repo,
    _run_and_parse,
)
from dev10x.github.bulk import (
    _bulk_execute,
    issues_bulk_create,
    issues_bulk_edit,
    milestones_bulk_create,
)
from dev10x.github.detection import (
    detect_base_branch,
    detect_tracker,
    pr_detect,
    pre_pr_checks,
    verify_pr_state,
)
from dev10x.github.issues import (
    _CLOSE_REASON_GH_VALUE,
    _issue_result,
    _resolve_comment_body,
    issue_close,
    issue_comment,
    issue_comment_delete,
    issue_comment_edit,
    issue_comments,
    issue_create,
    issue_edit,
    issue_get,
    issue_list,
    issue_reopen,
    triage_roster,
)
from dev10x.github.labels import (
    PR_LABEL_ACTIONS,
    _current_label_names,
    _label_names,
    _loads_or_empty,
    issue_labels,
    pr_labels,
)
from dev10x.github.merge import _merge_as_bot, _resolve_merge_bot, merge_pr
from dev10x.github.milestones import (
    _resolve_milestone_number,
    milestone_close,
    milestone_create,
    milestone_edit,
    milestone_list,
    milestone_reopen,
)
from dev10x.github.notify import generate_commit_list, post_summary_comment, pr_notify
from dev10x.github.pulls import (
    _BASE_BRANCH_NAMES,
    _normalized_for_comparison,
    _set_pr_milestone,
    _unapplied_pr_fields,
    create_pr,
    pr_close,
    pr_get,
    pr_list,
    pr_ready,
    update_pr,
)
from dev10x.github.reviews import (
    _BOT_LOGIN_RE,
    _MINIMIZE_CLASSIFIERS,
    _PR_COMMENT_ACTIONS,
    _REACTION_GROUP_CONTENT_TO_KEY,
    _list_unresolved_threads,
    _normalize_reaction_groups,
    _pr_comment_edit,
    _pr_comment_get,
    _pr_comment_list,
    _pr_comment_reply,
    _pr_comment_resolve,
    check_top_level_comments,
    is_bot_login,
    minimize_comments,
    pr_comment_edit,
    pr_comment_reply,
    pr_comments,
    pr_issue_comment,
    pr_review_edit,
    request_review,
    resolve_review_thread,
    unresolved_threads,
)

__all__ = [
    # _gateway
    "_GH_RETRY_POLICY",
    "_bot_env",
    "_detect_repo",
    "_gh_api",
    "_gh_api_raw",
    "_parse_gh_api_result",
    "_resolve_repo",
    "_run_and_parse",
    # detection
    "detect_base_branch",
    "detect_tracker",
    "pr_detect",
    "pre_pr_checks",
    "verify_pr_state",
    # reviews
    "_BOT_LOGIN_RE",
    "_MINIMIZE_CLASSIFIERS",
    "_PR_COMMENT_ACTIONS",
    "_REACTION_GROUP_CONTENT_TO_KEY",
    "_list_unresolved_threads",
    "_normalize_reaction_groups",
    "_pr_comment_edit",
    "_pr_comment_get",
    "_pr_comment_list",
    "_pr_comment_reply",
    "_pr_comment_resolve",
    "check_top_level_comments",
    "is_bot_login",
    "minimize_comments",
    "pr_comment_edit",
    "pr_comment_reply",
    "pr_comments",
    "pr_issue_comment",
    "pr_review_edit",
    "request_review",
    "resolve_review_thread",
    "unresolved_threads",
    # labels
    "PR_LABEL_ACTIONS",
    "_current_label_names",
    "_label_names",
    "_loads_or_empty",
    "issue_labels",
    "pr_labels",
    # pulls
    "_BASE_BRANCH_NAMES",
    "_normalized_for_comparison",
    "_set_pr_milestone",
    "_unapplied_pr_fields",
    "create_pr",
    "pr_close",
    "pr_get",
    "pr_list",
    "pr_ready",
    "update_pr",
    # merge
    "_merge_as_bot",
    "_resolve_merge_bot",
    "merge_pr",
    # milestones
    "_resolve_milestone_number",
    "milestone_close",
    "milestone_create",
    "milestone_edit",
    "milestone_list",
    "milestone_reopen",
    # issues
    "_CLOSE_REASON_GH_VALUE",
    "_issue_result",
    "_resolve_comment_body",
    "issue_close",
    "issue_comment",
    "issue_comment_delete",
    "issue_comment_edit",
    "issue_comments",
    "issue_create",
    "issue_edit",
    "issue_get",
    "issue_list",
    "issue_reopen",
    "triage_roster",
    # bulk
    "_bulk_execute",
    "issues_bulk_create",
    "issues_bulk_edit",
    "milestones_bulk_create",
    # notify
    "generate_commit_list",
    "post_summary_comment",
    "pr_notify",
]
