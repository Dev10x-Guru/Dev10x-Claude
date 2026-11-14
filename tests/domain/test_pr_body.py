"""GH-945: PR-body hygiene rules mirroring the hygiene-bot findings."""

import pytest
from dev10x.domain.pr_body import (
    HIDDEN_TRAILER_HINT,
    MISSING_REFERENCE_HINT,
    MULTILINE_REFERENCE_HINT,
    NONE_TRAILER_HINT,
    SEVERAL_REFERENCES_HINT,
    SO_CAN_MARKER,
    UNREADABLE_REFERENCE_HINT,
    WANTS_MARKER,
    WHEN_MARKER,
    built_trailer_error,
    built_trailer_lines,
    fixes_references,
    fixes_trailer_error,
    has_fixes_trailer,
    job_story_error,
    malformed_trailer_error,
    missing_job_story_markers,
    none_trailer_error,
    normalize_pr_body,
)

_NBSP = chr(0x00A0)
_ZWSP = chr(0x200B)
_WORD_JOINER = chr(0x2060)
_BOM = chr(0xFEFF)
_SPACING_MARK = chr(0x0903)

COMPLIANT_STORY = (
    "**When** an unattended run creates PRs, **the plugin maintainer "
    "wants to** get compliant bodies on the first try, **so the crew can** "
    "skip the fix-and-edit round."
)
FIXES_URL = "https://github.com/Dev10x-Guru/dev10x-claude/issues/945"


def test_compliant_job_story_has_no_missing_markers():
    assert missing_job_story_markers(job_story=COMPLIANT_STORY) == []


def test_compliant_job_story_yields_no_error():
    assert job_story_error(job_story=COMPLIANT_STORY) is None


def test_first_person_legacy_story_is_accepted():
    story = "**When** X, **I want to** Y, **so I can** Z."
    assert missing_job_story_markers(job_story=story) == []


@pytest.mark.parametrize(
    "job_story,expected",
    [
        (
            "**the maintainer wants to** Y, **so the crew can** Z.",
            [WHEN_MARKER],
        ),
        (
            "**When** X, the maintainer wants to Y, **so the crew can** Z.",
            [WANTS_MARKER],
        ),
        (
            "**When** X, **the maintainer wants to** Y, **so the crew doesn't burn a round.**",
            [SO_CAN_MARKER],
        ),
        (
            "When X, the maintainer wants to Y, so the crew can Z.",
            [WHEN_MARKER, WANTS_MARKER, SO_CAN_MARKER],
        ),
    ],
)
def test_missing_markers_are_reported(job_story, expected):
    assert missing_job_story_markers(job_story=job_story) == expected


@pytest.mark.parametrize(
    "job_story",
    [
        "**When** a refund times out, **the dealer wants** the reason to be "
        "obvious, **so the service writer can** answer the customer.",
        "**When** CI is red, **the maintainer wants** a named failing leg, "
        "**so the crew can** skip the bisect.",
    ],
)
def test_outcome_framed_story_is_accepted(job_story):
    """GH-1258: jtbd recommends outcome frames that omit the ``to`` verb.

    The marker check demanded a literal ``wants to**``, so writers had to
    abandon the better guidance to pass validation.
    """
    assert missing_job_story_markers(job_story=job_story) == []


def test_actor_clause_is_still_required():
    """Widening the marker must not accept a story with no actor."""
    assert WANTS_MARKER in missing_job_story_markers(
        job_story="**When** X, **wants** Y, **so the crew can** Z."
    )


def test_error_names_the_missing_marker_and_the_expected_format():
    error = job_story_error(job_story="**When** X, **I want to** Y, so I can Z.")
    assert SO_CAN_MARKER in error
    assert "references/git-jtbd.md" in error


# GH-1291: the skill tells writers to use the project's language and to
# look for translated markers when reading, but the validator matched
# English literals — so a Polish story written exactly as its own
# project prescribed was refused.
POLISH_STORY = (
    "**Gdy** zaczynamy implementować klienta KSeF, **deweloper chce** mieć model "
    "domeny udokumentowany razem z dowodami, **żeby zespół mógł** budować na "
    "ustaleniach potwierdzonych wykonaniem."
)


def test_polish_job_story_is_accepted():
    assert missing_job_story_markers(job_story=POLISH_STORY) == []


def test_polish_job_story_yields_no_error():
    assert job_story_error(job_story=POLISH_STORY) is None


@pytest.mark.parametrize(
    "job_story",
    [
        "**Gdy** X, **osoba utrzymująca chce** Y, **żeby integratorzy mogli** Z.",
        "**Gdy** X, **dealer chce** Y, **żeby serwisantka mogła** Z.",
    ],
)
def test_polish_verb_inflections_are_accepted(job_story):
    # mógł / mogła / mogli all appear in real stories; pinning one form
    # would reproduce the GH-1258 mistake in another language.
    assert missing_job_story_markers(job_story=job_story) == []


def test_polish_actor_clause_is_still_required():
    missing = missing_job_story_markers(job_story="**Gdy** X, **chce** Y, **żeby zespół mógł** Z.")

    assert missing != []


def test_a_story_mixing_two_languages_is_not_accepted():
    # The English-marker/Polish-prose hybrid is exactly the workaround the
    # old validator forced, and it reads worse than either language alone.
    mixed = "**When** X, **deweloper chce** Y, **so the team can** Z."

    assert missing_job_story_markers(job_story=mixed) != []


def test_the_error_names_every_accepted_marker_set():
    error = job_story_error(job_story="brak jakichkolwiek znaczników")

    assert "**When**" in error
    assert "**Gdy**" in error


def test_bare_separator_after_fixes_is_dropped():
    body = f"Story\n\n---\n\n- commit\n\nFixes: {FIXES_URL}\n\n---\n"
    assert normalize_pr_body(body=body) == f"Story\n\n---\n\n- commit\n\nFixes: {FIXES_URL}"


def test_substantive_trailer_is_relocated_above_fixes():
    body = f"Story\n\nFixes: {FIXES_URL}\n\n---\n\n## Checklist\n- [ ] tested\n"
    assert normalize_pr_body(body=body) == (
        f"Story\n\n---\n\n## Checklist\n- [ ] tested\n\nFixes: {FIXES_URL}"
    )


def test_already_compliant_body_is_unchanged_apart_from_trailing_whitespace():
    body = f"Story\n\n---\n\n- commit\n\nFixes: {FIXES_URL}"
    assert normalize_pr_body(body=f"{body}\n\n") == body


def test_body_without_fixes_trailer_is_left_alone():
    body = "Story\n\n---\n\n- commit"
    assert normalize_pr_body(body=f"{body}\n") == body


def test_only_the_last_fixes_line_anchors_normalization():
    body = f"Fixes: mentioned inline\n\nStory\n\nFixes: {FIXES_URL}\n\n---"
    assert normalize_pr_body(body=body) == (
        f"Fixes: mentioned inline\n\nStory\n\nFixes: {FIXES_URL}"
    )


def test_fixes_only_body_normalizes_to_the_single_line():
    assert normalize_pr_body(body=f"\n\nFixes: {FIXES_URL}\n---\n") == f"Fixes: {FIXES_URL}"


def test_contiguous_fixes_block_is_kept_together():
    # GH-1107 F2: a bundle PR needs one Fixes line per issue, and only
    # a Fixes trailer auto-closes on a develop merge — splitting the run
    # would strand the earlier entries mid-body and leave those issues
    # open with nothing explaining why.
    body = f"Story\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2\n\n---"

    assert normalize_pr_body(body=body) == (f"Story\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2")


def test_trailing_content_moves_above_a_multi_line_fixes_block():
    body = f"Story\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2\n\nstray note"

    assert normalize_pr_body(body=body) == (
        f"Story\n\nstray note\n\nFixes: {FIXES_URL}\nFixes: {FIXES_URL}2"
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Story\n\nFixes: #12\n\n```\nFixes: #99\n```",
            "Story\n\n```\nFixes: #99\n```\n\nFixes: #12",
        ),
        (
            "Story\n\nFixes: #12\n\n<!--\nFixes: #99\n-->",
            "Story\n\n<!--\nFixes: #99\n-->\n\nFixes: #12",
        ),
    ],
    ids=["fenced-reference-below", "commented-reference-below"],
)
def test_a_hidden_fixes_line_never_anchors_normalization(body: str, expected: str):
    # GH-1896
    assert normalize_pr_body(body=body) == expected


def test_self_motivated_fixes_trailer_is_detected():
    assert has_fixes_trailer(body="Story\n\nFixes: none — self-motivated")


def test_missing_fixes_trailer_is_detected():
    assert not has_fixes_trailer(body="Story\n\n---")


def test_missing_fixes_trailer_is_named():
    assert fixes_trailer_error(body="Story\n\n---") == "body carries no Fixes: trailer"


@pytest.mark.parametrize(
    "body",
    [
        "Story\n\n<!-- Fixes: #7 -->",
        "Story\n\n```\nFixes: #7\n```",
        "Story\n\n<!--\nFixes: none — part of #7\n-->",
    ],
    ids=["commented", "fenced", "multi-line-comment"],
)
def test_a_hidden_trailer_is_no_trailer(body: str):
    # GH-1896: close-issues never reads it, so neither does create_pr.
    assert fixes_trailer_error(body=body) == "body carries no Fixes: trailer"


def test_an_indented_trailer_is_a_trailer():
    # GH-1896: close-issues strips the line, so an indented trailer is
    # accepted before the PR opens, not only by the read-back after it.
    assert fixes_trailer_error(body="Story\n\n  Fixes: #7") is None


@pytest.mark.parametrize(
    "trailer",
    [
        "Fixes: none",
        "Fixes: none —",
        "Fixes: none — —",
        "Fixes: none — <reason>",
        "Fixes: none of the above",
        "Fixes: LIN-42\nFixes: none",
        "  Fixes: none",
        "Fixes: none\n\nA closing note.",
        "<!-- Fixes: none — part of #9 -->\nFixes: none",
    ],
    ids=[
        "bare",
        "dash-only",
        "punctuation-only",
        "placeholder",
        "no-dash",
        "bare-none-beside-a-non-github-reference",
        "indented-bare",
        "bare-none-above-trailing-prose",
        "commented-example-above-bare",
    ],
)
def test_a_none_trailer_close_issues_would_fail_is_refused(trailer: str):
    error = none_trailer_error(body=f"Story\n\n{trailer}")

    assert error is not None
    assert "Fixes: none — part of #123" in error


@pytest.mark.parametrize(
    "body",
    [
        "Story\n\nFixes: none — self-motivated",
        f"Story\n\nFixes: {FIXES_URL}",
        "Story\n\nFixes: LIN-42",
        "Story\n\n---",
        "Story\n\nFixes: GH-7\nFixes: none",
        "Story\n\nFixes: #7\n\nFixes: none",
        "Story\n\n  Fixes: none — part of #9",
        "Story\n\n<!-- Fixes: none -->\nFixes: #7",
    ],
    ids=[
        "usable-reason",
        "reference-trailer",
        "non-github-reference",
        "no-trailer",
        "reference-beside-bare-none",
        "reference-above-a-separate-bare-none",
        "indented-usable-reason",
        "commented-bare-none-above-a-reference",
    ],
)
def test_only_a_malformed_none_trailer_is_a_none_trailer_error(body: str):
    assert none_trailer_error(body=body) is None


@pytest.mark.parametrize(
    "trailer",
    [
        "Fixes: #١٢٣",
        "Fixes: GH-12_",
        "Fixes: #7\nFixes: #١٢٣",
        "Fixes: https://github.com/owner/repo/pull/5",
        "  fixes: #",
        "Closes #١٢٣",
        "Resolves GH-12_",
        "Fixes #١٢٣",
    ],
    ids=[
        "non-ascii-number",
        "number-glued-to-a-word-character",
        "readable-beside-unreadable",
        "pull-request-url",
        "indented-empty-reference",
        "closes-keyword",
        "resolves-keyword",
        "fixes-without-colon",
    ],
)
def test_a_github_reference_close_issues_cannot_read_is_refused(trailer: str):
    # GH-1896
    error = malformed_trailer_error(body=f"Story\n\n{trailer}")

    assert error is not None
    assert error.startswith("Fixes: trailer is malformed — ")
    assert "'Fixes: #123'" in error


@pytest.mark.parametrize(
    "body",
    [
        "Story\n\nFixes: #7",
        "Story\n\nFixes: GH-7, Fixes: #8",
        "Story\n\nFixes: https://github.com/owner/repo/issues/7",
        "Story\n\nFixes: LIN-42",
        "Story\n\nFixes: none — self-motivated",
        "Story\n\n<!-- Fixes: #١٢٣ -->\nFixes: #7",
    ],
    ids=["bare", "comma-list", "url", "non-github", "declared-none", "hidden-unreadable"],
)
def test_a_readable_or_non_github_trailer_is_not_malformed(body: str):
    assert malformed_trailer_error(body=body) is None


@pytest.mark.parametrize(
    "job_story",
    [
        "Story\n\nFixes: #9\n```\nopen",
        "Story\n\nFixes: #9\n<!-- open",
    ],
    ids=["own-trailer-then-open-fence", "own-trailer-then-open-comment"],
)
def test_a_built_trailer_hidden_after_a_visible_one_is_refused(job_story: str):
    # GH-1896
    error = built_trailer_error(job_story=job_story, references="#12")

    assert error == f"Fixes: trailer is malformed — {HIDDEN_TRAILER_HINT}"


@pytest.mark.parametrize(
    "job_story",
    ["Story\n\n```\nFixes: none\n```", "Story\n\n<!-- Fixes: none -->"],
    ids=["closed-fence", "closed-comment"],
)
def test_a_built_trailer_after_closed_blocks_is_accepted(job_story: str):
    assert built_trailer_error(job_story=job_story, references="#12") is None


@pytest.mark.parametrize(
    ("job_story", "references", "hint"),
    [
        ("Story\n\n```\nopen", "#12", HIDDEN_TRAILER_HINT),
        ("Story\n\n<!-- open", "#12", HIDDEN_TRAILER_HINT),
        ("Story", "none", NONE_TRAILER_HINT),
        ("Story", "#١٢٣", UNREADABLE_REFERENCE_HINT),
    ],
    ids=["open-fence", "open-comment", "bare-none", "unreadable-reference"],
)
def test_a_built_trailer_is_refused_with_the_matching_hint(
    job_story: str,
    references: str,
    hint: str,
):
    error = built_trailer_error(job_story=job_story, references=references)

    assert error == f"Fixes: trailer is malformed — {hint}"


@pytest.mark.parametrize(
    ("references", "expected"),
    [
        ("#12", ["Fixes: #12"]),
        ("#12 #13", ["Fixes: #12", "Fixes: #13"]),
        (
            "GH-12,https://github.com/o/r/issues/13",
            ["Fixes: GH-12", "Fixes: https://github.com/o/r/issues/13"],
        ),
        ("none — self-motivated", ["Fixes: none — self-motivated"]),
        ("#12 #١٢", ["Fixes: #12 #١٢"]),
        (
            "http://github.com/o/r/issues/13 #14",
            ["Fixes: http://github.com/o/r/issues/13", "Fixes: #14"],
        ),
        (f"#12{_NBSP}#13", [f"Fixes: #12{_NBSP}#13"]),
        ("#12\t#13", ["Fixes: #12", "Fixes: #13"]),
        ("none — self-motivated\n", ["Fixes: none — self-motivated"]),
        ("none\nmore", ["Fixes: none\nmore"]),
        ("", []),
        (",", []),
        (" , ", []),
    ],
    ids=[
        "one",
        "two-bare",
        "comma-mixed",
        "prose",
        "non-ascii-token",
        "http",
        "nbsp-does-not-split",
        "tab-splits",
        "trailing-newline-prose",
        "newline-prose",
        "empty",
        "comma-only",
        "blank",
    ],
)
def test_built_trailer_lines_mirror_create_pr_sh(references: str, expected: list[str]):
    # GH-1896
    assert built_trailer_lines(references=references) == expected


def test_a_built_trailer_is_judged_line_by_line_as_create_pr_sh_posts_it():
    # GH-1896: joined, "Fixes: #12 #13x" still reads #12; posted, the
    # second line "Fixes: #13x" names no issue close-issues can read.
    error = built_trailer_error(job_story="Story", references="#12 #13x")

    assert error == f"Fixes: trailer is malformed — {UNREADABLE_REFERENCE_HINT}"


def test_a_built_trailer_with_several_references_is_accepted():
    assert built_trailer_error(job_story="Story", references="#12 GH-13") is None


@pytest.mark.parametrize("references", ["", ",", " , "])
def test_a_built_trailer_without_references_is_refused_as_missing(references: str):
    error = built_trailer_error(job_story="Story", references=references)

    assert error == f"Fixes: trailer is missing — {MISSING_REFERENCE_HINT}"


@pytest.mark.parametrize(
    "job_story",
    ["Story\n\n```\nopen", "Story\n\n<!-- open"],
    ids=["open-fence", "open-comment"],
)
def test_several_built_trailer_lines_hidden_together_are_refused(job_story: str):
    error = built_trailer_error(job_story=job_story, references="#12 #13")

    assert error == f"Fixes: trailer is malformed — {HIDDEN_TRAILER_HINT}"


@pytest.mark.parametrize(
    "references",
    ["#1 -->\nFixes: #2", "none — x\nmore"],
    ids=["closes-a-comment", "prose"],
)
def test_a_multiline_built_reference_is_refused(references: str):
    # GH-1896: a second line can close a comment or carry text the
    # trailer check never reads as part of the trailer.
    error = built_trailer_error(job_story="Story\n\n<!-- open", references=references)

    assert error == f"Fixes: trailer is malformed — {MULTILINE_REFERENCE_HINT}"


@pytest.mark.parametrize(
    ("issue_id", "fixes_url", "expected"),
    [
        ("12\nnone", None, f"Fixes: trailer is malformed — {MULTILINE_REFERENCE_HINT}"),
        ("12", ",", f"Fixes: trailer is missing — {MISSING_REFERENCE_HINT}"),
    ],
    ids=["multiline-issue-id", "comma-fixes-url-wins-over-issue-id"],
)
def test_create_pr_arguments_reach_the_matching_hint(
    issue_id: str,
    fixes_url: str | None,
    expected: str,
):
    references = fixes_references(issue_id=issue_id, fixes_url=fixes_url, closes=None)

    assert built_trailer_error(job_story="Story", references=references) == expected


def test_a_prose_reference_with_a_trailing_newline_is_accepted():
    # GH-1896: the script's command substitution drops the newline.
    error = built_trailer_error(job_story="Story", references="none — self-motivated\n")

    assert error is None


def test_the_none_rule_answers_before_the_unreadable_reference_rule():
    error = malformed_trailer_error(body="Story\n\nFixes: #١٢٣\nFixes: none")

    assert error == f"Fixes: trailer is malformed — {NONE_TRAILER_HINT}"


@pytest.mark.parametrize(
    "references",
    [
        "#12, #13 (duplicate)",
        f"#12{_NBSP}#13",
        "#12 GH-13 see-above",
        "https://github.com/o/r/issues/12 and #13",
    ],
    ids=["trailing-prose", "nbsp", "word-token", "url-and-bare"],
)
def test_a_non_split_trailer_naming_several_issues_is_refused(references: str):
    # GH-1936
    error = built_trailer_error(job_story="Story", references=references)

    assert error == f"Fixes: trailer is malformed — {SEVERAL_REFERENCES_HINT}"


@pytest.mark.parametrize(
    "trailer",
    [
        "Fixes: #12, #13",
        "Closes #12 #13",
        "Fixes: #12 (duplicate of #11)",
    ],
    ids=["comma", "closes-space", "prose-mention"],
)
def test_a_body_line_naming_more_issues_than_it_closes_is_refused(trailer: str):
    # GH-1936
    error = malformed_trailer_error(body=f"Story\n\n{trailer}")

    assert error == f"Fixes: trailer is malformed — {SEVERAL_REFERENCES_HINT}"


@pytest.mark.parametrize(
    "trailer",
    [
        "Fixes: #12\nFixes: #13",
        "Fixes: GH-7, Fixes: #8",
        "Fixes: https://github.com/o/r/issues/12#issuecomment-1",
        "Fixes: none — part of #909 and #910",
        "Fixes: LIN-42 LIN-43",
    ],
    ids=["one-per-line", "keyword-per-reference", "url-fragment", "declared-none", "non-github"],
)
def test_a_line_closing_every_issue_it_names_is_accepted(trailer: str):
    assert malformed_trailer_error(body=f"Story\n\n{trailer}") is None


@pytest.mark.parametrize(
    "trailer",
    [f"Fixes:{_ZWSP}#12", f"Fixes: {_WORD_JOINER}#12", f"Closes{_BOM}#12"],
    ids=["zwsp", "word-joiner", "bom"],
)
def test_a_format_character_between_keyword_and_number_is_refused(trailer: str):
    # GH-1936
    error = malformed_trailer_error(body=f"Story\n\n{trailer}")

    assert error == f"Fixes: trailer is malformed — {UNREADABLE_REFERENCE_HINT}"


@pytest.mark.parametrize(
    "trailer",
    [f"Fixes: #12{_SPACING_MARK}", f"Fixes: https://github.com/o/r/issues/12{_ZWSP}"],
    ids=["spacing-mark-after-number", "hidden-character-after-url"],
)
def test_a_hidden_character_after_the_reference_is_refused(trailer: str):
    # GH-1936
    error = malformed_trailer_error(body=f"Story\n\n{trailer}")

    assert error == f"Fixes: trailer is malformed — {UNREADABLE_REFERENCE_HINT}"


def test_the_missing_hint_says_fixes_url_replaces_issue_id():
    assert "replaces issue_id" in MISSING_REFERENCE_HINT


def test_the_multiline_hint_does_not_call_a_none_value_an_issue_reference():
    assert "issue reference" not in MULTILINE_REFERENCE_HINT
