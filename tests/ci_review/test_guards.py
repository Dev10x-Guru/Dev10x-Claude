from __future__ import annotations

from typing import Any

import pytest

from dev10x.ci_review import guards
from dev10x.ci_review.guards import evaluate_guards, fetch_pr
from dev10x.core.domain.common.result import ErrorResult, Result, SuccessResult, err, ok

_OPEN: dict[str, Any] = {"state": "OPEN", "isDraft": False, "isCrossRepository": False}


@pytest.mark.parametrize(
    ("pr", "active", "expected"),
    [
        (_OPEN, ("draft", "fork"), []),
        ({**_OPEN, "isDraft": True}, ("draft", "fork"), ["draft"]),
        ({**_OPEN, "isCrossRepository": True}, ("draft", "fork"), ["fork"]),
        ({**_OPEN, "isDraft": True}, (), []),
        ({**_OPEN, "state": "MERGED"}, ("draft",), ["not-open:MERGED"]),
        (
            {"state": "CLOSED", "isDraft": True, "isCrossRepository": True},
            ("draft", "fork"),
            ["draft", "fork", "not-open:CLOSED"],
        ),
    ],
    ids=["open", "draft", "fork", "draft-unguarded", "merged", "everything"],
)
def test_evaluate_guards(pr: dict[str, Any], active: tuple[str, ...], expected: list[str]) -> None:
    assert evaluate_guards(pr=pr, guards=active) == expected


class TestFetchPr:
    @pytest.fixture
    def calls(self) -> list[list[str]]:
        return []

    def _stub(
        self,
        *,
        monkeypatch: pytest.MonkeyPatch,
        calls: list[list[str]],
        result: Result[str],
    ) -> None:
        def fake_run(*, args: list[str], timeout: float) -> Result[str]:
            calls.append(args)
            return result

        monkeypatch.setattr(guards, "run_checked", fake_run)

    def test_parses_json(self, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
        self._stub(monkeypatch=monkeypatch, calls=calls, result=ok('{"number": 7}'))

        result = fetch_pr(repo="o/r", number=7)

        assert result == SuccessResult(value={"number": 7})
        assert calls == [["gh", "pr", "view", "7", "--repo", "o/r", "--json", guards.PR_FIELDS]]

    def test_bad_json(self, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
        self._stub(monkeypatch=monkeypatch, calls=calls, result=ok("nope"))

        result = fetch_pr(repo="o/r", number=7)

        assert isinstance(result, ErrorResult)
        assert "invalid JSON" in result.error

    def test_gh_failure(self, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
        self._stub(monkeypatch=monkeypatch, calls=calls, result=err("boom"))

        assert fetch_pr(repo="o/r", number=7) == err("boom")
