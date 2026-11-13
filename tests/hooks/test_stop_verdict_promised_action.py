"""GH-1829: a turn that ends on a promised action with nothing run.

"Now I'll run the tests" read at the end of a turn looks like work in
progress. When no tool followed it and no widget is open, it is a
stated intention the session never acted on — the supervisor comes back
later to an idle session. The block names the promise and tells the
agent to either make the call or end the turn honestly.

What it must never do is trap a session: the two loop guards still win,
and so does an open ``AskUserQuestion``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from dev10x.hooks.stop_verdict import (
    INTENT_PATTERNS_PATH,
    IntentPatterns,
    StopSignal,
    decide,
    load_intent_patterns,
    parse_intent_patterns,
    promised_action,
    record_block,
)

from .conftest import DEPLETED_PLAN, PENDING_PLAN
from .test_stop_verdict import _ask, _assistant, _text
from .test_stop_verdict import _transcript as _write_transcript
from .test_stop_verdict_open_work import _transcript as _closing_turn


def _tool_use() -> dict:
    return {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}


def _entries(*, closing: str) -> list[dict]:
    return [_assistant(blocks=[_text(text=closing)])]


class TestAPromiseWithNothingRunBlocks:
    @pytest.mark.parametrize(
        "closing",
        [
            "Now I'll run the full test suite.",
            "Next, I will open the PR.",
            "I'll now push the branch.",
            "I will go ahead and merge it.",
            "I'm going to rebase onto develop.",
            "I am about to rerun the failing check.",
            "Let me check the CI logs.",
            "Next, let's fix the lint errors.",
            "I'll run the tests.",
            "I will commit the fix.",
            "Now I’ll run the tests.",
        ],
    )
    def test_the_closing_promise_blocks(
        self, tmp_path: Path, isolated_markers: Path, closing: str
    ) -> None:
        verdict = decide(
            data={
                "session_id": "p1",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing=closing),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.block is True
        assert verdict.signal == StopSignal.PROMISED_ACTION

    def test_it_fires_without_a_task_list(self, tmp_path: Path, isolated_markers: Path) -> None:
        """A model without task tools is the likeliest to narrate instead of act."""
        verdict = decide(
            data={
                "session_id": "p2",
                "transcript_path": _closing_turn(
                    tmp_path=tmp_path, closing="Now I'll run the tests."
                ),
            },
            plan=None,
        )

        assert verdict.signal == StopSignal.PROMISED_ACTION

    def test_it_outranks_the_depleted_list_steer(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "p3",
                "transcript_path": _closing_turn(
                    tmp_path=tmp_path, closing="I'll open the PR next."
                ),
            },
            plan=DEPLETED_PLAN,
        )

        assert verdict.signal == StopSignal.PROMISED_ACTION

    def test_the_steer_quotes_the_promise_and_names_both_exits(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "p4",
                "transcript_path": _closing_turn(
                    tmp_path=tmp_path, closing="Now I'll run the tests."
                ),
            },
            plan=PENDING_PLAN,
        )

        assert "> Now I'll run the tests." in verdict.reason
        assert "Do the action now" in verdict.reason
        assert "AskUserQuestion" in verdict.reason
        assert "status line" in verdict.reason


#: Closings that do declare an action, and are let through only by an
#: exemption. Each one must match an intent pattern on its own, or the
#: test would pass with the exemption deleted.
_EXEMPT_PROMISES = [
    "Now I'll wait for CI to finish.",
    "Next, I will stand by for your review.",
    "Then I'll leave it for tomorrow.",
    "Once you approve, I'll merge it.",
    "If you want, I will rebase it.",
    "Say go and I'll push it.",
    "Give me the word and I will merge.",
    "With your approval I'll open the PR.",
    "I'll now pick up the docs in the next session.",
    "Now I'll merge it once you approve.",
    "Next, I'll push the branch after you've reviewed it.",
    "I'll push the branch when you're ready.",
    "I'll rebase it if you'd like.",
    "I'll rebase it if you want me to.",
    "Let me know if you want me to, and I'll rebase it.",
    "Ping me once you approve, I'll merge it.",
    "I'll merge it once you sign.",
    "I'll merge it once you've chosen.",
    "I'll push it once you've fixed the tests.",
    "I'll update the docs after you merge the PR.",
    "I'll push the branch when you've read the plan.",
    "I'll merge it if you agree.",
    "I'll rebase it if you'd rather.",
    "I'll push it if you need me to.",
    "I'll push it if you're ready.",
    "I'll merge it if you're happy.",
    "Otherwise, if you see failures, I'll fix them.",
    "So if you see failures, I'll fix them.",
    "+ If you see failures, I'll fix them.",
    "(If you see failures, I'll fix them.)",
    "Here is the plan:\n- If you see failures, I'll fix them.",
    "Plan: 1. If you see failures, I'll fix them.",
    "I'll rebase it when you'd like.",
    "I'll merge it when you want.",
    "• If you see failures, I'll fix them.",
    '"If you see failures, I\'ll fix them."',
    "[If you see failures, I'll fix them.]",
    "And if you see failures, I'll fix them.",
    "Then, if you see failures, I'll fix them.",
    "I'll merge it if you're done.",
    "I'll push it if you're ok with it.",
    "I'll push it when you're sure.",
    "I'll merge it if you accept.",
    "I'll rebase it if you decide to.",
    "I'll merge it if you wish.",
    "I'll rerun it if you ask.",
    "I'll merge it if you would like.",
    "I'll merge it when you accept.",
    "I'll push it when you tell me.",
    "I'll push it when you let me know.",
    "I'll merge it if you're happy with the diff.",
    "If you see failures, I'll fix them.",
    "- If you see failures, I'll fix them.",
    "2. When you have a minute, I'll review it with you.",
]


class TestATurnThatKeptItsWordEndsQuietly:
    @pytest.mark.parametrize(
        "closing",
        [
            "All tests pass and the PR is merged.",
            "Let me know what you think of it.",
            "Everything is merged and green.",
        ],
    )
    def test_a_close_with_no_promise_does_not_block(
        self, tmp_path: Path, isolated_markers: Path, closing: str
    ) -> None:
        verdict = decide(
            data={
                "session_id": "n1",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing=closing),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.OPEN_WORK

    @pytest.mark.parametrize("closing", _EXEMPT_PROMISES)
    def test_an_exempt_promise_does_not_block(
        self, tmp_path: Path, isolated_markers: Path, closing: str
    ) -> None:
        verdict = decide(
            data={
                "session_id": "n5",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing=closing),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.OPEN_WORK

    @pytest.mark.parametrize("closing", _EXEMPT_PROMISES)
    def test_only_the_exemption_lets_the_promise_through(self, closing: str) -> None:
        intent_only = IntentPatterns(intent=load_intent_patterns().intent)

        assert promised_action(entries=_entries(closing=closing), patterns=intent_only)

    def test_a_promise_made_after_earlier_tools_still_blocks(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """Tools earlier in the turn do not cover the promise it ends on."""
        transcript = _write_transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_tool_use()]),
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
                    },
                },
                _assistant(blocks=[_text(text="Now I'll run the tests.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "n6", "transcript_path": transcript},
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.PROMISED_ACTION

    @pytest.mark.parametrize(
        "after_prose",
        [
            [_assistant(blocks=[_text(text="Now I'll run the tests."), _tool_use()])],
            [
                _assistant(blocks=[_text(text="Now I'll run the tests.")]),
                _assistant(blocks=[_tool_use()]),
            ],
        ],
        ids=["same-entry", "later-entry"],
    )
    def test_a_tool_after_the_text_is_narration(
        self, tmp_path: Path, isolated_markers: Path, after_prose: list[dict]
    ) -> None:
        transcript = _write_transcript(
            tmp_path=tmp_path,
            entries=[{"type": "user", "message": {"role": "user", "content": "go"}}, *after_prose],
        )

        verdict = decide(
            data={"session_id": "n2", "transcript_path": transcript},
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.OPEN_WORK

    @pytest.mark.parametrize(
        "closing",
        [
            "Let me summarize what changed.",
            "Let me be clear about the trade-off.",
            "I'm going to be honest: the tests are slow.",
        ],
    )
    def test_status_narration_is_not_a_promise(self, closing: str) -> None:
        assert promised_action(entries=_entries(closing=closing)) == ""

    def test_a_long_run_of_spaces_is_judged_in_bounded_time(self) -> None:
        """Overlapping whitespace quantifiers once made this quadratic."""
        closing = "now" + " " * 50_000 + "done"

        assert promised_action(entries=_entries(closing=closing)) == ""

    def test_a_long_run_of_emphasis_in_a_clause_is_judged_in_bounded_time(self) -> None:
        """Overlapping condition classes once made each clause quadratic."""
        closing = "Done, " + "*" * 1900 + " I'll run the tests, I'll push it, I'll merge it."

        assert promised_action(entries=_entries(closing=closing)) == closing

    def test_only_the_tail_of_a_long_close_is_judged(self) -> None:
        closing = "Now I'll run the tests. " + "x" * 3000

        assert promised_action(entries=_entries(closing=closing)) == ""

    def test_an_earlier_paragraph_is_not_the_close(self) -> None:
        """Only the sentence the turn ends on is the state of play."""
        closing = promised_action(
            entries=_entries(closing="I'll keep the old name.\n\nEverything is merged.")
        )

        assert closing == ""

    def test_a_turn_parked_on_subagents_ends_quietly(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """GH-1464: the harness resumes the turn when the children report."""
        plan = {
            "tasks": [
                {"subject": "Collate wave 1", "status": "pending", "metadata": {"awaiting": True}}
            ]
        }

        verdict = decide(
            data={
                "session_id": "n4",
                "transcript_path": _closing_turn(
                    tmp_path=tmp_path, closing="Next, I'll collate the results as they land."
                ),
            },
            plan=plan,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.AWAITING_SUBAGENTS

    def test_an_open_widget_wins(self, tmp_path: Path, isolated_markers: Path) -> None:
        transcript = _write_transcript(
            tmp_path=tmp_path,
            entries=[
                {"type": "user", "message": {"role": "user", "content": "go"}},
                _assistant(blocks=[_text(text="Now I'll merge once you pick."), _ask()]),
            ],
        )

        verdict = decide(
            data={"session_id": "n3", "transcript_path": transcript},
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.ASKED

    def test_a_tool_only_turn_promises_nothing(self) -> None:
        assert promised_action(entries=[_assistant(blocks=[_tool_use()])]) == ""

    def test_a_turn_with_neither_prose_nor_tools_promises_nothing(self) -> None:
        thinking_only = _assistant(blocks=[{"type": "thinking", "thinking": "I'll run it."}])

        assert promised_action(entries=[thinking_only]) == ""


#: Closings whose promise shares a sentence with its condition, or sits
#: in a list under a colon lead-in that carries the condition. Like
#: ``_EXEMPT_PROMISES``, each must also match an intent pattern on its
#: own, which ``test_only_the_exemption_lets_the_promise_through`` pins.
_SAME_SENTENCE_EXEMPTIONS = [
    pytest.param(
        "Once you approve, I'll merge it. If you want, I will rebase it first.",
        id="two-exempt-sentences",
    ),
    pytest.param("Everything is green. Once you approve, I'll merge it.", id="status-then-exempt"),
    pytest.param("Once you approve,\nI'll merge it.", id="wrapped-sentence"),
    pytest.param("If you want, e.g. the slow ones, I'll rerun the tests.", id="abbreviation-eg"),
    pytest.param("If you prefer squash vs. rebase, I'll merge it that way.", id="abbreviation-vs"),
    pytest.param(
        "Once you approve:\n- I'll push the branch\n- I'll merge it",
        id="conditional-lead-in-list",
    ),
    pytest.param(
        "Once you approve:\n  1. I'll push the branch\n  10. I'll merge it",
        id="conditional-lead-in-indented-numbers",
    ),
    pytest.param(
        "Once you approve:\n1) I'll push the branch\n2) I'll merge it",
        id="conditional-lead-in-paren-numbers",
    ),
    pytest.param(
        "Ping me once you approve, I'll merge it; CI is green now.",
        id="gate-with-now-in-another-clause",
    ),
    pytest.param("Let me know if you'd like, and I'll rebase it.", id="gate-phrase-no-now"),
    pytest.param("If you'd like, I'll rebase it.", id="opening-gate-phrase"),
    pytest.param("Say the word — I'll merge it.", id="em-dash-gate"),
    pytest.param("Once you approve, I'll merge it now.", id="opening-wait-then-now"),
    pytest.param("Ping me once you approve, I'll merge it now.", id="wait-in-another-clause-now"),
    pytest.param("I'll run the tests now, if you approve.", id="now-then-decision-gate"),
    pytest.param("If you see failures, I'll fix them right away.", id="opening-condition-now"),
    pytest.param(
        "Here is the plan:\n- If you see failures, I'll fix them now.",
        id="list-item-condition-now",
    ),
    pytest.param("If you're interested, I'll run the tests.", id="opening-interest-no-now"),
    pytest.param("If you see failures I'll fix them right away.", id="no-comma-condition-now"),
]


#: Closings where an unconditional promise stands beside a conditional
#: one, so the paragraph as a whole would read as exempt.
_UNCONDITIONAL_BESIDE_CONDITIONAL = [
    pytest.param(
        "Now I'll run the tests. If you see failures, I'll fix them.",
        id="promise-then-condition",
    ),
    pytest.param(
        "If you want a summary, say so. Next, I'll push the branch.",
        id="condition-then-promise",
    ),
    pytest.param("I'll open the PR! Once you approve, I'll merge it.", id="exclamation"),
    pytest.param(
        "Want a summary? Next, I'll push the branch. If you want, I'll add one.",
        id="question-mark",
    ),
    pytest.param("I'll run the tests.\nIf you see failures, I'll fix them.", id="line-break"),
    pytest.param("**I'll push it now.** Once you approve, I'll merge it.", id="markdown-bold"),
    pytest.param("- I'll run the tests\n- Once you approve, I'll merge it", id="bullet-list"),
    pytest.param("1. I'll run the tests\n2. Once you approve, I'll merge it", id="numbered-list"),
    pytest.param(
        "1) I'll run the tests\n2) Once you approve, I'll merge it",
        id="numbered-paren-list",
    ),
    pytest.param(
        "Once you approve:\n- I'll merge it. Now I'll run the tests.",
        id="item-splits-at-sentence-end",
    ),
    pytest.param(
        "Once you approve:\n- I'll merge it. Next steps below.\n- I'll run the tests",
        id="lead-in-stops-at-next-sentence",
    ),
]


#: Closings where "if/when you" hedges rather than conditions: it
#: neither opens a clause before the promise nor names the supervisor's
#: decision, so nothing in it waits on them (GH-1869), or it names only
#: a preference in another clause while the promise says it happens now
#: (GH-1894).
_HEDGED_PROMISES = [
    pytest.param("Let me know if you'd like, I'll run the tests now.", id="gate-phrase-then-now"),
    pytest.param("Let me know, if you'd like, I'll run the tests now.", id="comma-gate-then-now"),
    pytest.param("Let us know if you'd like; now I'll push it.", id="gate-phrase-now-i-will"),
    pytest.param("If you want, I'm going to rebase it now.", id="going-to-now"),
    pytest.param("If you'd like, I'll rerun the tests right away.", id="right-away"),
    pytest.param("Shout if you want — I'll merge it immediately.", id="em-dash-immediately"),
    pytest.param("I'll run the tests now, if you'd like.", id="now-then-gate-phrase"),
    pytest.param("I'll run the tests, if you don't mind.", id="trailing-condition"),
    pytest.param("If you're interested, I'll run the tests now.", id="opening-interest-now"),
    pytest.param("If you do want me to, I'll push it now.", id="opening-do-want-now"),
    pytest.param("If you care to, I'll rebase it right away.", id="opening-care-to-now"),
    pytest.param("If you care to I'll rebase it right away.", id="no-comma-opening-preference"),
    pytest.param("If you're interested I'll run the tests now.", id="no-comma-interest-now"),
    pytest.param("I'll run the tests now if you'd like.", id="no-comma-now-then-preference"),
    pytest.param("Let me know if you disagree, I'll run the tests now.", id="if-you-disagree"),
    pytest.param("Shout if you have questions; I'll push the branch now.", id="if-you-have"),
    pytest.param("Ping me when you see this, I'll rerun the tests now.", id="when-you-see"),
    pytest.param("Tell me if you spot anything off; next, I'll push it.", id="if-you-spot"),
    pytest.param("Shout if you're stuck; I'll push it now.", id="if-you-are-stuck"),
    pytest.param("Ping me when you're back, I'll rerun the tests now.", id="when-you-are-back"),
    pytest.param("Let me know: if you disagree, I'll run the tests now.", id="colon-then-if-you"),
    pytest.param(
        "I'll run the tests now: if you see failures, I'll fix them.", id="promise-colon-if-you"
    ),
    pytest.param("Now I'll run it:\nIf you see failures, I'll fix them.", id="colon-newline-if"),
    pytest.param(
        "Let me know if you disagree with this plan:\n- I'll run the tests now\n- I'll push it",
        id="hedged-lead-in",
    ),
]


class TestAHedgeIsNotACondition:
    """GH-1869: "if you" in passing must not excuse the promise beside it."""

    @pytest.mark.parametrize("closing", _HEDGED_PROMISES)
    def test_a_hedged_promise_blocks(
        self, tmp_path: Path, isolated_markers: Path, closing: str
    ) -> None:
        verdict = decide(
            data={
                "session_id": "h1",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing=closing),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.PROMISED_ACTION

    @pytest.mark.parametrize("closing", _HEDGED_PROMISES)
    def test_a_hedged_promise_is_returned_whole(self, closing: str) -> None:
        assert promised_action(entries=_entries(closing=closing)) == closing


class TestAnExemptionCoversOnlyItsOwnSentence:
    """GH-1854: a conditional sentence must not excuse its neighbor."""

    @pytest.mark.parametrize("closing", _UNCONDITIONAL_BESIDE_CONDITIONAL)
    def test_an_unconditional_promise_beside_a_conditional_one_blocks(
        self, tmp_path: Path, isolated_markers: Path, closing: str
    ) -> None:
        verdict = decide(
            data={
                "session_id": "s1",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing=closing),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.PROMISED_ACTION

    def test_the_whole_paragraph_is_returned_not_just_the_promise(self) -> None:
        closing = "Now I'll run the tests. If you see failures, I'll fix them."

        assert promised_action(entries=_entries(closing=closing)) == closing

    @pytest.mark.parametrize("closing", _SAME_SENTENCE_EXEMPTIONS)
    def test_only_the_exemption_lets_the_promise_through(self, closing: str) -> None:
        intent_only = IntentPatterns(intent=load_intent_patterns().intent)

        assert promised_action(entries=_entries(closing=closing), patterns=intent_only)

    @pytest.mark.parametrize("closing", _SAME_SENTENCE_EXEMPTIONS)
    def test_a_condition_sharing_the_promises_sentence_still_exempts_it(
        self, tmp_path: Path, isolated_markers: Path, closing: str
    ) -> None:
        verdict = decide(
            data={
                "session_id": "s2",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing=closing),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.signal == StopSignal.OPEN_WORK


class TestTheLoopGuardsStillWin:
    def test_stop_hook_active_lets_the_turn_end(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        verdict = decide(
            data={
                "session_id": "g1",
                "stop_hook_active": True,
                "transcript_path": _closing_turn(
                    tmp_path=tmp_path, closing="Now I'll run the tests."
                ),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.STOP_HOOK_ACTIVE

    def test_standby_lets_the_turn_end(self, tmp_path: Path, isolated_markers: Path) -> None:
        """A parked gate stays parked, promise or not (GH-1314)."""
        transcript = _write_transcript(
            tmp_path=tmp_path,
            entries=[
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "content": '"Done?"="On standby"'},
                            {"type": "text", "text": "back later"},
                        ],
                    },
                },
                _assistant(blocks=[_text(text="Now I'll run the tests.")]),
            ],
        )

        verdict = decide(
            data={"session_id": "g3", "transcript_path": transcript},
            plan=PENDING_PLAN,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.STANDBY

    def test_a_recent_block_lets_the_turn_end(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        record_block(session_id="g2")

        verdict = decide(
            data={
                "session_id": "g2",
                "transcript_path": _closing_turn(
                    tmp_path=tmp_path, closing="Now I'll run the tests."
                ),
            },
            plan=PENDING_PLAN,
        )

        assert verdict.block is False
        assert verdict.signal == StopSignal.COOLDOWN


class TestThePatternsLiveInData:
    def test_the_shipped_file_matches_both_future_forms(self) -> None:
        patterns = load_intent_patterns()

        assert promised_action(entries=_entries(closing="I'll run it."), patterns=patterns)
        assert promised_action(entries=_entries(closing="I will run it."), patterns=patterns)

    def test_the_shipped_file_sits_beside_the_module(self) -> None:
        assert INTENT_PATTERNS_PATH.name == "stop_intent_patterns.yaml"
        assert INTENT_PATTERNS_PATH.is_file()

    def test_the_shipped_file_parses_without_a_warning(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A broken shipped entry is caught here, not by a disarmed gate."""
        patterns = parse_intent_patterns(
            data=yaml.safe_load(INTENT_PATTERNS_PATH.read_text(encoding="utf-8"))
        )

        assert patterns.intent
        assert patterns.exempt
        assert capsys.readouterr().err == ""

    def test_every_language_is_merged(self) -> None:
        patterns = parse_intent_patterns(
            data={
                "languages": {
                    "en": {"intent": ["\\bI'll run\\b"]},
                    "pl": {"intent": ["\\bteraz uruchomi\\w*\\b"], "exempt": ["\\bpoczekam\\b"]},
                }
            }
        )

        assert len(patterns.intent) == 2
        assert len(patterns.exempt) == 1
        assert promised_action(
            entries=_entries(closing="Teraz uruchomię testy."), patterns=patterns
        )

    def test_a_pattern_that_does_not_compile_is_dropped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        patterns = parse_intent_patterns(
            data={"languages": {"en": {"intent": ["(unclosed", "\\bI'll run\\b"]}}}
        )

        assert len(patterns.intent) == 1
        assert "compiling en intent pattern" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("data", "diagnostic"),
        [
            (None, "no 'languages' mapping"),
            ([], "no 'languages' mapping"),
            ({"languages": []}, "no 'languages' mapping"),
            ({"languages": {"en": "nope"}}, "reading intent language 'en'"),
            ({"languages": {"en": {"intent": "\\bI'll\\b"}}}, "reading en intent"),
            ({"languages": {"en": {"intent": [True]}}}, "reading en intent entry True"),
        ],
    )
    def test_an_unusable_shape_yields_no_patterns_and_says_so(
        self, data: object, diagnostic: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A one-character YAML slip must not disarm the gate in silence."""
        assert parse_intent_patterns(data=data) == IntentPatterns()
        assert diagnostic in capsys.readouterr().err

    def test_an_empty_language_is_quiet(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert parse_intent_patterns(data={"languages": {"en": {}}}) == IntentPatterns()
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("key", ["exempt", "preference", "condition"])
    def test_a_broken_excuse_disarms_the_gate(
        self, key: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A lost excuse would mean more blocks, the wrong direction to fail."""
        patterns = parse_intent_patterns(
            data={"languages": {"en": {"intent": ["\\bI'll run\\b"], key: ["(unclosed"]}}}
        )

        assert patterns == IntentPatterns()
        assert f"compiling en {key} pattern" in capsys.readouterr().err

    def test_a_broken_immediacy_marker_is_dropped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A lost marker means fewer blocks, so the rest still runs."""
        patterns = parse_intent_patterns(
            data={
                "languages": {
                    "en": {"intent": ["\\bI'll run\\b"], "immediate": ["(unclosed", "\\bnow\\b"]}
                }
            }
        )

        assert len(patterns.intent) == 1
        assert len(patterns.immediate) == 1
        assert "compiling en immediate pattern" in capsys.readouterr().err

    def test_the_shipped_file_carries_conditions_and_markers(self) -> None:
        patterns = load_intent_patterns()

        assert patterns.preference
        assert patterns.condition
        assert patterns.immediate

    @pytest.mark.parametrize(
        "content",
        [b"languages:\n  en:\n    intent: ['\xff\xfe']\n", b"languages: [unclosed"],
        ids=["not-utf8", "malformed-yaml"],
    )
    def test_an_unparseable_file_yields_no_patterns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
    ) -> None:
        broken = tmp_path / "broken.yaml"
        broken.write_bytes(content)

        patterns = load_intent_patterns(path=broken)

        assert patterns == IntentPatterns()
        assert "parsing the intent patterns" in capsys.readouterr().err

    def test_a_missing_file_yields_no_patterns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        patterns = load_intent_patterns(path=tmp_path / "absent.yaml")

        assert patterns == IntentPatterns()
        assert "reading the intent patterns" in capsys.readouterr().err

    def test_decide_takes_its_patterns_as_an_input(
        self, tmp_path: Path, isolated_markers: Path
    ) -> None:
        """The rule judges what it is given, like `dirty` and `plan`."""
        verdict = decide(
            data={
                "session_id": "i1",
                "transcript_path": _closing_turn(tmp_path=tmp_path, closing="Now I'll run it."),
            },
            plan=PENDING_PLAN,
            patterns=IntentPatterns(),
        )

        assert verdict.signal == StopSignal.OPEN_WORK

    def test_no_patterns_never_blocks(self) -> None:
        closing = promised_action(
            entries=_entries(closing="Now I'll run the tests."), patterns=IntentPatterns()
        )

        assert closing == ""


class TestTheSignalIsLegible:
    def test_promised_action_reprs_as_a_member(self) -> None:
        assert repr(StopSignal.PROMISED_ACTION) == "StopSignal.PROMISED_ACTION"
