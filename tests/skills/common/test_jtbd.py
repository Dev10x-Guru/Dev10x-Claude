"""Tests for the shared JTBD/Slack helpers (GH-246 F5)."""

from __future__ import annotations

import pytest

from dev10x.domain.pr_body import missing_job_story_markers
from dev10x.skills.common.jtbd import (
    extract_jtbd,
    extract_jtbd_structured,
    md_to_slack_bold,
)

STRUCTURED_BODY = (
    "Some intro.\n\n"
    "**When** reconciling payments, **I want to** retry transient errors,"
    " **so I can** avoid manual reposting\n\n"
    "## Notes\nmore text"
)


class TestExtractJtbd:
    def test_collects_when_block_until_blank_line(self):
        body = "intro\n**When** X happens, I want Y\nso I can Z\n\ntrailing"
        assert extract_jtbd(body=body) == "**When** X happens, I want Y so I can Z"

    def test_stops_at_heading_line(self):
        body = "**When** X, I want Y\n# Heading\nignored"
        assert extract_jtbd(body=body) == "**When** X, I want Y"

    def test_returns_none_without_when_marker(self):
        assert extract_jtbd(body="no story here\njust text") is None

    def test_returns_none_on_empty_body(self):
        assert extract_jtbd(body="") is None


POLISH_BODY = (
    "Wstęp.\n\n"
    "**Gdy** zaczynamy implementować klienta KSeF, **deweloper chce** mieć model "
    "domeny udokumentowany razem z dowodami, **żeby zespół mógł** budować na "
    "ustaleniach potwierdzonych wykonaniem\n\n"
    "## Notatki\nwięcej tekstu"
)


class TestExtractsALocalizedStory:
    """GH-1291: the validator accepts a project-language story, so the
    extractor must find one — otherwise release notes silently omit it."""

    def test_polish_story_is_located_by_its_opening_marker(self):
        assert extract_jtbd(body=POLISH_BODY).startswith("**Gdy** zaczynamy")

    def test_polish_story_matches_the_structured_pattern(self):
        result = extract_jtbd_structured(body=POLISH_BODY)

        assert result is not None
        assert result.startswith("**Gdy** zaczynamy implementować")
        assert result.endswith(".")

    @pytest.mark.parametrize(
        "body",
        [
            "**Gdy** X, **osoba utrzymująca chce** Y, **żeby integratorzy mogli** Z.",
            "**Gdy** X, **dealer chce** Y, **żeby serwisantka mogła** Z.",
        ],
    )
    def test_polish_verb_inflections_are_matched(self, body: str):
        assert extract_jtbd_structured(body=body) is not None

    def test_an_english_story_still_matches(self):
        # The added dialect must not shadow the original.
        assert extract_jtbd_structured(body=STRUCTURED_BODY) is not None


ACCEPTED_BY_THE_VALIDATOR = [
    # English, canonical.
    "**When** reconciling a payout, **the dealer wants to** see each line"
    " item, **so the service writer can** resolve disputes.",
    # English outcome frame — no `to` after `wants` (GH-1258).
    "**When** a call times out, **the dealer wants** the reason to be"
    " obvious, **so the dealer can** retry without guessing.",
    # English, legacy first person.
    "**When** A, **I want to** B, **so I can** C.",
    # Polish, canonical.
    "**Gdy** klient rezerwuje montaż, **serwisant chce** znać termin,"
    " **żeby dealer mógł** potwierdzić rezerwację.",
    # Polish with words trailing the verb inside the markers.
    "**Gdy** zaczynamy wdrożenie, **osoba utrzymująca chce bardzo** mieć"
    " model domeny, **żeby integratorzy mogli szybko** na nim budować.",
]


class TestTheTwoSurfacesAgree:
    """GH-1291: a story the validator accepts MUST be extractable.

    The failure this guards is silent — `create_pr` lets the PR through
    and the Job Story never reaches release notes — so it cannot be
    caught by using either surface alone. An extractor stricter than its
    validator is the same defect as a validator stricter than its
    extractor, only quieter.
    """

    @pytest.mark.parametrize("job_story", ACCEPTED_BY_THE_VALIDATOR)
    def test_the_validator_accepts_it(self, job_story: str):
        assert missing_job_story_markers(job_story=job_story) == []

    @pytest.mark.parametrize("job_story", ACCEPTED_BY_THE_VALIDATOR)
    def test_and_the_extractor_finds_it(self, job_story: str):
        assert extract_jtbd_structured(body=job_story) is not None


class TestExtractJtbdStructured:
    def test_matches_full_structured_story_and_adds_period(self):
        result = extract_jtbd_structured(body=STRUCTURED_BODY)
        assert result is not None
        assert result.startswith("**When** reconciling payments")
        assert result.endswith(".")
        assert "\n" not in result

    def test_keeps_existing_trailing_period(self):
        body = "**When** A, **I want to** B, **so I can** C."
        result = extract_jtbd_structured(body=body)
        assert result == "**When** A, **I want to** B, **so I can** C."

    @pytest.mark.parametrize(
        "body",
        [
            # Third-person domain-actor voice (GH-847) — distinct actor and
            # beneficiary roles.
            "**When** reconciling a payout, **the dealer wants to** see each"
            " line item, **so the service writer can** resolve disputes.",
            # Same role in both slots.
            "**When** onboarding, **the admin wants to** copy config,"
            " **so the admin can** skip manual setup.",
            # Negative-outcome verb.
            "**When** notifications pile up, **the wholesaler wants to** batch"
            " them, **so the wholesaler doesn't** miss orders.",
            # Legacy first-person back-compat.
            "**When** A, **I want to** B, **so I can** C.",
            # Legacy third-person plural back-compat.
            "**When** A, **they want to** B, **so they can** C.",
        ],
    )
    def test_matches_third_person_and_legacy_voice(self, body: str):
        result = extract_jtbd_structured(body=body)
        assert result is not None
        assert result.startswith("**When** ")

    @pytest.mark.parametrize(
        "body",
        [
            "",
            "no jtbd structure at all",
            "**When** X happens but no want clause",
        ],
    )
    def test_returns_none_when_structure_absent(self, body: str):
        assert extract_jtbd_structured(body=body) is None


class TestMdToSlackBold:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("**When** I do **this**", "*When* I do *this*"),
            ("plain text", "plain text"),
            ("", ""),
            ("**bold**", "*bold*"),
        ],
    )
    def test_converts_double_star_to_single(self, text: str, expected: str):
        assert md_to_slack_bold(text=text) == expected
