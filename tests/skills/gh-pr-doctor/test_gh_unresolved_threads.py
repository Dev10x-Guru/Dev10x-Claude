"""Tests for the chunked-GraphQL unresolved-threads sweep (GH-836).

Loads the uv-script via importlib and exercises the pure helpers — the
chunking, query assembly, and per-PR node parsing — without any ``gh``
subprocess calls.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "gh_unresolved_threads",
    _repo_root / "skills" / "gh-pr-doctor" / "scripts" / "gh-unresolved-threads.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class TestChunked:
    def test_splits_into_size_bounded_chunks(self):
        chunks = list(_mod._chunked([1, 2, 3, 4, 5], 2))
        assert chunks == [[1, 2], [3, 4], [5]]

    def test_empty_input_yields_no_chunks(self):
        assert list(_mod._chunked([], 25)) == []


class TestBuildChunkQuery:
    def test_aliases_each_pr_with_embedded_number(self):
        query = _mod._build_chunk_query([101, 202])
        assert "pr0: pullRequest(number: 101)" in query
        assert "pr1: pullRequest(number: 202)" in query
        # The query declares only owner/repo variables — PR numbers are
        # embedded, not per-alias variables.
        assert "query($owner: String!, $repo: String!)" in query
        assert "reviewThreads(first: 100)" in query

    def test_coerces_numbers_to_int(self):
        # A str-typed number is coerced, so the query stays injection-safe.
        query = _mod._build_chunk_query(["303"])
        assert "pr0: pullRequest(number: 303)" in query


class TestExtractUnresolved:
    def test_skips_resolved_and_empty_threads(self):
        node = {
            "reviewThreads": {
                "nodes": [
                    {"isResolved": True, "comments": {"nodes": [{"body": "done"}]}},
                    {"isResolved": False, "comments": {"nodes": []}},
                    {
                        "isResolved": False,
                        "comments": {
                            "nodes": [
                                {
                                    "path": "a.py",
                                    "body": "x" * 300,
                                    "author": {"login": "carol"},
                                }
                            ]
                        },
                    },
                ]
            }
        }
        unresolved = _mod._extract_unresolved(node)
        assert len(unresolved) == 1
        assert unresolved[0]["path"] == "a.py"
        assert unresolved[0]["author"] == "carol"
        # Body is truncated to 200 chars.
        assert len(unresolved[0]["body"]) == 200

    def test_missing_author_defaults_to_unknown(self):
        node = {
            "reviewThreads": {
                "nodes": [
                    {"isResolved": False, "comments": {"nodes": [{"path": "b.py", "body": "hi"}]}}
                ]
            }
        }
        assert _mod._extract_unresolved(node)[0]["author"] == "unknown"


class TestHasAuditMarker:
    def test_detects_marker_in_conversation_comments(self):
        node = {"comments": {"nodes": [{"body": "chore"}, {"body": "PR Audit trail"}]}}
        assert _mod._has_audit_marker(node) is True

    def test_absent_marker_returns_false(self):
        node = {"comments": {"nodes": [{"body": "looks good"}]}}
        assert _mod._has_audit_marker(node) is False

    def test_none_body_is_safe(self):
        node = {"comments": {"nodes": [{"body": None}]}}
        assert _mod._has_audit_marker(node) is False
