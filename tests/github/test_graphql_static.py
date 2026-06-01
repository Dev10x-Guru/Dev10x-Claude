"""Static GraphQL contract tests for dev10x.github (GH-386).

Contract class: static-lint
  No live API calls. Validates query strings that are known at import time
  or can be reconstructed from source-level string literals. Catches the
  GH-329 class of "invalid field silently green in CI because every test
  mocks the API boundary."

See ``docs/github-contract-test-boundary.md`` for the full mock-vs-contract
boundary documentation.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

_GITHUB_MODULE = Path(__file__).parents[2] / "src" / "dev10x" / "github" / "__init__.py"
_SKILLS_GH_CONTEXT = Path(__file__).parents[2] / "skills" / "gh-context" / "scripts"

# ---------------------------------------------------------------------------
# Known-invalid GitHub GraphQL fields (from GH-329 post-mortem).
# Add entries here whenever a field is found invalid via real-session failures.
# ---------------------------------------------------------------------------
_KNOWN_INVALID_GRAPHQL_FIELDS: list[dict[str, str]] = [
    {
        "field": "merged",
        "context": "PullRequest",
        "reason": (
            "``merged`` is not a valid ``gh pr view`` JSON field on PullRequest (GH-329). "
            "Use ``mergedAt`` (ISO8601 timestamp, null when not merged) instead."
        ),
    },
    {
        "field": "pullRequestReviewThread",
        "context": "PullRequestReviewComment",
        "reason": (
            "``PullRequestReviewComment.pullRequestReviewThread`` does not exist in GitHub's "
            "GraphQL schema (GH-329). Use databaseId + parent PR reviewThreads lookup."
        ),
    },
]

# ---------------------------------------------------------------------------
# Known-valid GraphQL field names used in the module.
# This list documents which selections are verified against the real schema
# (via GH-329 incident post-mortem + manual schema inspection). It is NOT
# exhaustive — it is a minimum baseline to prevent silent regression.
# ---------------------------------------------------------------------------
_KNOWN_VALID_PR_REVIEW_COMMENT_FIELDS = frozenset(
    {
        "databaseId",
        "body",
        "path",
        "line",
        "author",
        "pullRequestReview",
        "reactionGroups",
        "pullRequest",
        "id",
    }
)

_KNOWN_VALID_REVIEW_THREAD_FIELDS = frozenset(
    {
        "id",
        "isResolved",
        "isOutdated",
        "comments",
    }
)

# Known-valid ``gh pr view --json`` fields (verified against real API + GH-329 fix).
# Add fields here when they are validated against the real ``gh pr view --json`` surface.
_KNOWN_VALID_GH_PR_VIEW_JSON_FIELDS = frozenset(
    {
        "number",
        "title",
        "body",
        "state",
        "baseRefName",
        "headRefName",
        "mergedAt",
        "closedAt",
        "labels",
        "milestone",
        "assignees",
        "author",
        "url",
        "isDraft",
        "reviewDecision",
        "additions",
        "deletions",
        "changedFiles",
        "mergeable",
        "statusCheckRollup",
        "reviewRequests",
        "reviews",
        "comments",
        "commits",
        "files",
        "headRepository",
        "headRepositoryOwner",
        "isCrossRepository",
        "potentialMergeCommit",
        "autoMergeRequest",
        "id",
        "createdAt",
        "updatedAt",
    }
)


def _is_docstring_node(node: ast.AST, parent_body: list[ast.stmt]) -> bool:
    """Return True if ``node`` is the first statement (docstring) in a body."""
    if not parent_body:
        return False
    first = parent_body[0]
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and first.value is node
    )


def _extract_query_strings_from_source(source: str) -> list[str]:
    """Extract string literals that look like GraphQL queries from Python source.

    Skips docstrings (first expression in module/class/function bodies) and
    only collects strings that contain GraphQL-shaped content: balanced braces,
    field selections, operation keywords, or inline-fragment markers.

    For f-strings, returns the static skeleton with ``__DYNAMIC__`` placeholders
    for interpolated parts.
    """
    tree = ast.parse(source)

    # Collect all docstring node references so we can exclude them.
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        body: list[ast.stmt] | None = None
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
        if body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstring_nodes.add(id(first.value))

    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_nodes:
                continue
            literals.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            # f-strings — reconstruct the static skeleton.
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                else:
                    parts.append("__DYNAMIC__")
            literals.append("".join(parts))
    return literals


_GRAPHQL_INDICATORS = re.compile(
    r"query\s*\{|"
    r"mutation\s*\{|"
    r"\{\s*repository\s*\(|"
    r"\{\s*node\s*\(id\s*:|"
    r"\.\.\.\s*on\s+PullRequestReviewComment|"
    r"reviewThreads\s*\(|"
    r"resolveReviewThread\s*\(|"
    r"minimizeComment\s*\(",
    re.IGNORECASE,
)


def _extract_graphql_fragments(source: str) -> list[str]:
    """Return only those strings from source that contain GraphQL-shaped content."""
    return [s for s in _extract_query_strings_from_source(source) if _GRAPHQL_INDICATORS.search(s)]


class TestGraphqlStaticContractLint:
    """Contract class: static-lint.

    These tests validate GraphQL query strings at the static level — no live
    API calls. They catch the GH-329 class of failures: invalid field names
    and selections that pass CI because every unit test mocks the API boundary.
    """

    @pytest.fixture(scope="class")
    def github_source(self) -> str:
        return _GITHUB_MODULE.read_text()

    @pytest.fixture(scope="class")
    def graphql_fragments(self, github_source: str) -> list[str]:
        return _extract_graphql_fragments(github_source)

    def test_source_file_exists(self) -> None:
        """The github module must exist and be readable."""
        assert _GITHUB_MODULE.exists(), f"GitHub module not found: {_GITHUB_MODULE}"

    def test_extracts_graphql_fragments(self, graphql_fragments: list[str]) -> None:
        """At least one GraphQL fragment must be extractable from the source."""
        assert len(graphql_fragments) > 0, (
            "No GraphQL fragments found in github/__init__.py. "
            "If the module was refactored, update the extraction logic in this test."
        )

    @pytest.mark.parametrize(
        "field_spec",
        _KNOWN_INVALID_GRAPHQL_FIELDS,
        ids=[s["field"] for s in _KNOWN_INVALID_GRAPHQL_FIELDS],
    )
    def test_known_invalid_field_absent(
        self,
        graphql_fragments: list[str],
        field_spec: dict[str, Any],
    ) -> None:
        """Known-invalid GitHub GraphQL fields must not appear in query strings.

        These are documented cases where a field was found invalid via real-session
        failures (GH-329 post-mortem). The test prevents silent regression.
        """
        field = field_spec["field"]
        reason = field_spec["reason"]
        for fragment in graphql_fragments:
            assert field not in fragment, (
                f"Known-invalid GraphQL field {field!r} found in a query fragment.\n"
                f"Reason: {reason}\n"
                f"Fragment (truncated): {fragment[:200]!r}"
            )

    def test_list_unresolved_threads_query_structure(
        self,
        graphql_fragments: list[str],
    ) -> None:
        """The static query in _list_unresolved_threads must contain required fields.

        Reconstructs the query skeleton from string literals and checks that
        the known-valid selection set is present.
        """
        query_parts = [f for f in graphql_fragments if "reviewThreads" in f]
        assert query_parts, (
            "No fragment containing 'reviewThreads(' found in github/__init__.py. "
            "If the query was moved or renamed, update this test."
        )
        combined = " ".join(query_parts)
        required_fields = {"databaseId", "isResolved", "isOutdated"}
        for field in required_fields:
            assert field in combined, (
                f"Required field {field!r} missing from reviewThreads query. "
                f"Combined fragments (truncated): {combined[:300]!r}"
            )

    def test_resolve_review_thread_mutation_uses_correct_input(
        self,
        graphql_fragments: list[str],
    ) -> None:
        """resolveReviewThread mutation must use threadId input, not commentId.

        GitHub's mutation is resolveReviewThread(input: {threadId: "PRRT_..."}).
        Using commentId or any other input field name is invalid.
        """
        mutation_parts = [f for f in graphql_fragments if "resolveReviewThread" in f]
        assert mutation_parts, (
            "No resolveReviewThread fragment found. If the mutation was renamed, update this test."
        )
        for part in mutation_parts:
            assert "threadId" in part, (
                f"resolveReviewThread mutation must use 'threadId' input field. "
                f"Fragment: {part[:200]!r}"
            )
            assert "commentId" not in part, (
                f"resolveReviewThread does not accept 'commentId' — only 'threadId'. "
                f"Fragment: {part[:200]!r}"
            )

    def test_minimize_comment_mutation_uses_correct_inputs(
        self,
        graphql_fragments: list[str],
    ) -> None:
        """minimizeComment mutation must use subjectId and classifier inputs.

        GitHub's mutation is minimizeComment(input: {subjectId: ..., classifier: ...}).
        The f-string skeleton contains both static keys.
        """
        mutation_parts = [f for f in graphql_fragments if "minimizeComment" in f]
        assert mutation_parts, (
            "No minimizeComment fragment found. If the mutation was renamed, update this test."
        )
        combined = " ".join(mutation_parts)
        assert "subjectId" in combined, (
            f"minimizeComment mutation must use 'subjectId' input field. "
            f"Combined fragments (truncated): {combined[:300]!r}"
        )
        # 'classifier:' appears in the f-string static skeleton as 'classifier: __DYNAMIC__'
        assert "classifier" in combined, (
            f"minimizeComment mutation must use 'classifier' input field. "
            f"Combined fragments (truncated): {combined[:300]!r}"
        )

    def test_pr_review_comment_inline_fragment_fields_valid(
        self,
        graphql_fragments: list[str],
    ) -> None:
        """PullRequestReviewComment inline fragment must use only known-valid fields.

        Verifies that the selections within ``... on PullRequestReviewComment { }``
        blocks do not include known-invalid fields and do include expected ones.
        """
        inline_parts = [f for f in graphql_fragments if "PullRequestReviewComment" in f]
        assert inline_parts, (
            "No PullRequestReviewComment inline fragment found in github/__init__.py."
        )
        combined = " ".join(inline_parts)
        # databaseId must be present — it is the lookup key used in GH-329 fix
        assert "databaseId" in combined, (
            "databaseId must be selected in PullRequestReviewComment inline fragment. "
            "It is the lookup key for thread matching (GH-329)."
        )
        # pullRequestReviewThread is the invalid field from GH-329
        assert "pullRequestReviewThread" not in combined, (
            "pullRequestReviewThread does not exist on PullRequestReviewComment "
            "in GitHub's GraphQL schema (GH-329). Use reviewThreads on the parent PR."
        )

    @pytest.mark.parametrize(
        "graphql_op,required_return_field",
        [
            ("resolveReviewThread", "isResolved"),
            ("minimizeComment", "isMinimized"),
        ],
    )
    def test_mutation_return_fields_present(
        self,
        graphql_fragments: list[str],
        graphql_op: str,
        required_return_field: str,
    ) -> None:
        """Mutations must select their return payload fields.

        A mutation that doesn't select any return fields is technically valid
        GraphQL but provides no feedback and hides API errors.
        """
        op_fragments = [f for f in graphql_fragments if graphql_op in f]
        if not op_fragments:
            pytest.skip(f"No fragment for {graphql_op!r} found — skipping")
        combined = " ".join(op_fragments)
        assert required_return_field in combined, (
            f"{graphql_op} mutation must select {required_return_field!r} in return payload. "
            f"Missing return field prevents error detection. "
            f"Fragment (truncated): {combined[:300]!r}"
        )


class TestGhPrGetScriptContractLint:
    """Contract class: static-lint (shell script).

    These tests validate ``skills/gh-context/scripts/gh-pr-get.sh`` against
    the GH-329 class of failures: requesting invalid ``gh pr view`` JSON fields
    that only fail at runtime, not in CI.
    """

    @pytest.fixture(scope="class")
    def script_content(self) -> str:
        script = _SKILLS_GH_CONTEXT / "gh-pr-get.sh"
        assert script.exists(), f"gh-pr-get.sh not found at {script}"
        return script.read_text()

    @pytest.fixture(scope="class")
    def gh_pr_view_json_fields(self, script_content: str) -> set[str]:
        """Extract the field list from the ``gh pr view --json`` line specifically.

        The script also uses ``--json nameWithOwner`` for repo detection;
        we only want the ``gh pr view --json`` field list.

        Handles the common shell pattern where ``--json`` is on a continuation
        line after ``gh pr view "$NUMBER" --repo "$REPO" \\``.
        """
        # Join continuation lines (backslash-newline) so the whole command
        # is on one logical line, then search for the PR view --json argument.
        logical = script_content.replace("\\\n", " ")
        match = re.search(r"gh\s+pr\s+view\b[^#\n]*--json\s+([\w,]+)", logical)
        assert match is not None, (
            "Could not find 'gh pr view ... --json FIELDS' pattern in gh-pr-get.sh. "
            "Update the regex if the script format changed."
        )
        return set(match.group(1).split(","))

    def test_merged_field_absent(self, script_content: str) -> None:
        """``merged`` is not a valid ``gh pr view`` JSON field (GH-329).

        The script must use ``mergedAt`` (ISO8601 timestamp) instead.
        ``merged,`` (with trailing comma) and ``merged\\n`` (last field) are
        both checked to catch standalone field usage.
        """
        assert ",merged," not in script_content, (
            "Found ',merged,' in gh-pr-get.sh — 'merged' is not a valid gh pr view field (GH-329)."
        )
        assert ",merged\n" not in script_content, (
            "Found ',merged' at end of field list in gh-pr-get.sh (GH-329)."
        )

    def test_merged_at_field_present(self, script_content: str) -> None:
        """``mergedAt`` (the valid replacement for ``merged``) must be in the script."""
        assert "mergedAt" in script_content, (
            "gh-pr-get.sh must request the 'mergedAt' field to determine merge status (GH-329)."
        )

    def test_json_fields_flag_present(self, script_content: str) -> None:
        """The script must use ``--json`` to request structured output."""
        assert "--json" in script_content, (
            "gh-pr-get.sh must use 'gh pr view --json' for structured output."
        )

    def test_all_json_fields_are_known_valid(
        self,
        gh_pr_view_json_fields: set[str],
    ) -> None:
        """All requested JSON fields must be from the known-valid ``gh pr view`` set.

        This is the static-lint equivalent of a contract test: it compares the
        declared fields against the set known to exist in ``gh pr view --json``.
        Add fields here as they are validated against the real API.
        """
        invalid_fields = gh_pr_view_json_fields - _KNOWN_VALID_GH_PR_VIEW_JSON_FIELDS
        assert not invalid_fields, (
            f"gh-pr-get.sh requests unknown/invalid 'gh pr view --json' fields: "
            f"{sorted(invalid_fields)}. "
            "These may cause 'unknown JSON field' errors at runtime (GH-329 class). "
            "If a field was recently added to gh, add it to _KNOWN_VALID_GH_PR_VIEW_JSON_FIELDS "
            "in this test."
        )

    def test_merged_at_in_json_fields(
        self,
        gh_pr_view_json_fields: set[str],
    ) -> None:
        """``mergedAt`` must be in the explicitly declared JSON field list."""
        assert "mergedAt" in gh_pr_view_json_fields, (
            "gh-pr-get.sh must explicitly declare 'mergedAt' in --json fields (GH-329 fix)."
        )
