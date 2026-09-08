"""The capture-pipeline skills name roles, not one deployment's fixtures.

GH-1230 took one deployment's test accounts out of ``qa-self``, but the
same class survived in two sibling skills of the same pipeline
(GH-1235). That defect is structurally unlikely to be reported by anyone
able to fix it: the runtime path reads the account map from config and
works fine for the deployment the names came from, so the docs are wrong
only for everybody else.

These tests are the documentation half, in the shape
``tests/skills/qa-self/test_deploy_check_paths.py`` established for
GH-1147 — they cannot check what a reader's deployment contains, so they
pin that the shipped text describes roles and defaults rather than
accounts and tenants.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILL = _REPO_ROOT / "skills" / "playwright" / "SKILL.md"
_WRAPPER = _REPO_ROOT / "skills" / "playwright" / "scripts" / "run-playwright.sh"
_PR_COMMENT = _REPO_ROOT / "skills" / "qa-publish" / "references" / "pr-comment.md"

# Account names that belonged to one deployment. None may appear in the
# shipped docs as though every reader had them.
_FOREIGN_ACCOUNTS = ("janusz_ai", "qa_bot")

# The wrapper's legacy default, deliberately retained. It is the one
# account name allowed to survive, and only as the tail of a `:-`
# expansion that config overrides.
_LEGACY_DEFAULT = "e2e_test_user"


@pytest.fixture(scope="module")
def skill() -> str:
    return _SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wrapper() -> str:
    return _WRAPPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pr_comment() -> str:
    return _PR_COMMENT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def template_blocks(pr_comment: str) -> list[str]:
    """The fenced blocks a reader copies, without the prose around them."""
    blocks = re.findall(r"^```.*?^```", pr_comment, flags=re.MULTILINE | re.DOTALL)
    assert blocks, "no fenced template block — the reference has no template to copy"
    return blocks


class TestNoForeignAccountsInTheDocs:
    @pytest.mark.parametrize("account", _FOREIGN_ACCOUNTS)
    def test_the_skill_names_no_deployment_account(self, skill: str, account: str):
        assert account not in skill

    @pytest.mark.parametrize("account", _FOREIGN_ACCOUNTS)
    def test_the_wrapper_names_no_deployment_account(self, wrapper: str, account: str):
        assert account not in wrapper

    def test_the_invocation_example_uses_a_role_not_a_person(self, skill: str):
        # `--user <a person's handle>` was the worked example, so the
        # documented happy path authenticated as an account that exists in
        # exactly one deployment.
        for line in skill.splitlines():
            if "--user" in line:
                assert not re.search(r"--user\s+[a-z][\w.]*\b", line), line

    def test_the_account_table_describes_permission_levels(self, skill: str):
        # The suffixes are the contract; the usernames are the reader's.
        assert "CRM_USERNAME2=<admin-level>" in skill


class TestTheLegacyDefaultIsDeliberate:
    def test_the_skill_marks_it_as_legacy(self, skill: str):
        # Naming it is fine — a reader debugging resolution needs it — as
        # long as the surrounding text says it matches only its own
        # deployment. Scoped to a window rather than the line, because
        # prose wraps and the qualifier lands on a neighbouring line.
        for match in re.finditer(re.escape(_LEGACY_DEFAULT), skill):
            window = skill[max(0, match.start() - 300) : match.end() + 300].lower()
            assert "legacy" in window or "pre-gh-1130" in window, window

    def test_the_wrapper_only_uses_it_as_an_overridable_default(self, wrapper: str):
        occurrences = [line for line in wrapper.splitlines() if _LEGACY_DEFAULT in line]
        assert occurrences, "the legacy default vanished — pre-GH-1130 deployments break"
        for line in occurrences:
            # Either the `${VAR:-default}` expansion itself, or the comment
            # explaining why it stays.
            assert ":-" in line or line.lstrip().startswith("#"), line

    def test_the_wrapper_records_why_it_stays(self, wrapper: str):
        # GH-1235 asked for an explicit keep-or-drop decision, documented
        # either way, so a later sweep does not read it as an oversight.
        assert "GH-1235" in wrapper

    def test_config_outranks_it(self, wrapper: str):
        # Reachable only when a deployment sets none of the layers above.
        assert "${CRM_USERNAME:-${PLAYWRIGHT_DEFAULT_USER:-" in wrapper


class TestNoTenantInTheTemplate:
    def test_the_template_names_no_concrete_dealer(self, pr_comment: str):
        assert not re.search(r"dealer\s+\d+", pr_comment, flags=re.IGNORECASE)

    def test_the_template_uses_a_placeholder(self, pr_comment: str):
        assert "DEALER" in pr_comment

    def test_the_placeholder_is_not_angle_bracketed(self, template_blocks: list[str]):
        # The template is pasted into a GitHub comment, which strips an
        # unknown tag — so an un-substituted angle placeholder would
        # disappear from the rendered caveat instead of standing out as
        # unfilled. Scoped to the fenced blocks: the prose around them
        # names the bad form in order to warn against it.
        for block in template_blocks:
            assert "<DEALER>" not in block, block
            assert "&lt;" not in block, block

    def test_the_reader_is_told_to_fill_it_in(self, pr_comment: str):
        # The posted comment must still name the real tenant — qa-self
        # requires evidence to say which record it shows. Only the
        # template stays generic.
        assert "Substitute" in pr_comment
