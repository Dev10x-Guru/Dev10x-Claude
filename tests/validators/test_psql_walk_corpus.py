"""DX004's command-position walk, judged without the word rule (GH-2005)."""

from __future__ import annotations

import pytest

from dev10x.core.validators.sql_safety import SqlSafetyValidator
from tests.validators import test_sql_safety
from tests.validators.psql_corpus import compare, corpus, walk_blocks

_REVIEW_BYPASSES = test_sql_safety.TestPsqlCommandPosition.test_blocks_review_bypasses.pytestmark[
    0
].args[1]

# Commands only the word rule blocks: what retiring it would allow.
# The first group names psql without running it. The second runs an
# installed program by bare name that the runner tables do not know.
_NAMES_PSQL_WITHOUT_RUNNING_IT = frozenset(
    {
        "git log --grep psql",
        "ls /usr/bin/psql",
        "man -P less psql",
        "man -Pless psql",
        "man psql",
        "rg --pre-glob '*.gz' psql src",
        "rg psql src; > out.txt",
        "which psql",
    }
)
_UNKNOWN_BARE_RUNNERS = frozenset(
    {
        "nohup some-unknown-runner psql -d mydb",
        "some-unknown-runner --flag /usr/lib/postgresql/bin/psql",
    }
)
WORD_RULE_ONLY = _NAMES_PSQL_WITHOUT_RUNNING_IT | _UNKNOWN_BARE_RUNNERS

_CORPUS = corpus()
_PRODUCTION_BLOCKS = [
    command
    for command in _CORPUS
    if SqlSafetyValidator()._check_direct_psql(command=command) is not None
]


@pytest.mark.parametrize("command", _REVIEW_BYPASSES)
def test_walk_alone_blocks_review_bypasses(command: str) -> None:
    assert walk_blocks(command=command)


@pytest.mark.parametrize(
    "command", [command for command in _PRODUCTION_BLOCKS if command not in WORD_RULE_ONLY]
)
def test_walk_alone_blocks_what_production_blocks(command: str) -> None:
    assert walk_blocks(command=command)


def test_word_rule_only_residue_is_pinned() -> None:
    comparison = compare(commands=_CORPUS)
    print(comparison.report())

    assert comparison.word_rule_only == WORD_RULE_ONLY, comparison.report()
