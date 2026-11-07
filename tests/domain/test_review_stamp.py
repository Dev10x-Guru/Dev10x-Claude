from __future__ import annotations

import json
from pathlib import Path

import pytest
from dev10x.domain.review_stamp import (
    CorruptStampStoreError,
    ReviewStamp,
    ReviewStampStore,
    StampVerdict,
    evaluate_stamp,
    repo_slug_from_pr_url,
    repo_slug_from_remote,
)

STAMP = ReviewStamp(head_sha="a" * 40, tree_sha="t" * 40, reviewed_at="2026-11-06T10:00:00+00:00")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:Dev10x-Guru/Dev10x-Claude.git", "dev10x-guru/dev10x-claude"),
        ("https://github.com/Dev10x-Guru/Dev10x-Claude.git", "dev10x-guru/dev10x-claude"),
        ("https://github.com/dev10x-guru/dev10x-claude", "dev10x-guru/dev10x-claude"),
        ("ssh://git@github.com/owner/repo/", "owner/repo"),
        ("not a url", None),
        ("", None),
    ],
)
def test_repo_slug_from_remote(url: str, expected: str | None) -> None:
    assert repo_slug_from_remote(url=url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/Dev10x-Guru/Dev10x-Claude/pull/1850", "dev10x-guru/dev10x-claude"),
        ("https://github.com/owner/repo/issues/3", None),
        ("", None),
    ],
)
def test_repo_slug_from_pr_url(url: str, expected: str | None) -> None:
    assert repo_slug_from_pr_url(url=url) == expected


@pytest.mark.parametrize(
    ("stamp", "head_sha", "head_tree_sha", "expected"),
    [
        (None, "a" * 40, "t" * 40, StampVerdict.MISSING),
        (STAMP, "a" * 40, None, StampVerdict.CURRENT),
        (STAMP, "b" * 40, "t" * 40, StampVerdict.SAME_TREE),
        (STAMP, "b" * 40, "u" * 40, StampVerdict.STALE),
        (STAMP, "b" * 40, None, StampVerdict.STALE),
    ],
)
def test_evaluate_stamp(
    stamp: ReviewStamp | None,
    head_sha: str,
    head_tree_sha: str | None,
    expected: StampVerdict,
) -> None:
    assert evaluate_stamp(stamp=stamp, head_sha=head_sha, head_tree_sha=head_tree_sha) is expected


@pytest.mark.parametrize(
    ("verdict", "passes"),
    [
        (StampVerdict.CURRENT, True),
        (StampVerdict.SAME_TREE, True),
        (StampVerdict.MISSING, False),
        (StampVerdict.STALE, False),
    ],
)
def test_verdict_passes(verdict: StampVerdict, passes: bool) -> None:
    assert verdict.passes is passes


class TestReviewStampStore:
    @pytest.fixture
    def store(self, tmp_path: Path) -> ReviewStampStore:
        return ReviewStampStore(path=tmp_path / "nested" / "review-stamps.json")

    def test_read_from_missing_file_is_none(self, store: ReviewStampStore) -> None:
        assert store.read(slug="o/r", branch="b") is None

    def test_write_then_read_round_trips(self, store: ReviewStampStore) -> None:
        store.write(slug="o/r", branch="feature", stamp=STAMP)

        assert store.read(slug="o/r", branch="feature") == STAMP

    def test_write_keeps_other_branches_and_repos(self, store: ReviewStampStore) -> None:
        other = ReviewStamp(head_sha="c" * 40, tree_sha="d" * 40, reviewed_at="x")
        store.write(slug="o/r", branch="one", stamp=STAMP)
        store.write(slug="o/r", branch="two", stamp=other)
        store.write(slug="o/other", branch="one", stamp=other)

        assert store.read(slug="o/r", branch="one") == STAMP
        assert store.read(slug="o/r", branch="two") == other
        assert store.read(slug="o/other", branch="one") == other

    def test_write_overwrites_the_same_branch(self, store: ReviewStampStore) -> None:
        newer = ReviewStamp(head_sha="e" * 40, tree_sha="f" * 40, reviewed_at="later")
        store.write(slug="o/r", branch="b", stamp=STAMP)
        store.write(slug="o/r", branch="b", stamp=newer)

        assert store.read(slug="o/r", branch="b") == newer

    def test_write_replaces_a_non_mapping_repo_entry(self, store: ReviewStampStore) -> None:
        store.path.parent.mkdir(parents=True)
        store.path.write_text(json.dumps({"o/r": "junk"}))

        store.write(slug="o/r", branch="b", stamp=STAMP)

        assert store.read(slug="o/r", branch="b") == STAMP

    @pytest.mark.parametrize(
        "content",
        [
            "{not json",
            json.dumps(["a", "list"]),
            json.dumps({"o/r": ["not", "a", "mapping"]}),
            json.dumps({"o/r": {"b": "not a mapping"}}),
            json.dumps({"o/r": {"b": {"head_sha": "a"}}}),
        ],
    )
    def test_unusable_content_reads_as_no_stamp(
        self, store: ReviewStampStore, content: str
    ) -> None:
        store.path.parent.mkdir(parents=True)
        store.path.write_text(content)

        assert store.read(slug="o/r", branch="b") is None

    def test_non_utf8_store_reads_as_no_stamp(self, store: ReviewStampStore) -> None:
        store.path.parent.mkdir(parents=True)
        store.path.write_bytes(b"\xff\xfe\x00junk")

        assert store.read(slug="o/r", branch="b") is None

    def test_unreadable_store_reads_as_no_stamp(self, tmp_path: Path) -> None:
        store = ReviewStampStore(path=tmp_path)

        assert store.read(slug="o/r", branch="b") is None

    @pytest.mark.parametrize("content", ["{not json", json.dumps(["a", "list"])])
    def test_write_refuses_to_replace_a_corrupt_store(
        self, store: ReviewStampStore, content: str
    ) -> None:
        store.path.parent.mkdir(parents=True)
        store.path.write_text(content)

        with pytest.raises(CorruptStampStoreError):
            store.write(slug="o/r", branch="b", stamp=STAMP)

        assert store.path.read_text() == content
