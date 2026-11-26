"""Shared read-only SQL rules for DX004 and the bq_query tool (GH-1633)."""

from __future__ import annotations

import time

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.core.domain.rules.read_only_sql import (
    BQ_READ_ONLY_VERBS,
    MAX_STATEMENT_CHARS,
    validate_bigquery_sql,
    validate_bigquery_statement,
    validate_read_only_sql,
)


class TestValidateReadOnlySql:
    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param("", id="empty"),
            pytest.param("SELECT 1", id="select"),
            pytest.param("WITH t AS (SELECT 1) SELECT * FROM t;", id="with-trailing-semicolon"),
            pytest.param("SELECT ';' AS sep", id="semicolon-in-string"),
        ],
    )
    def test_accepts(self, sql: str) -> None:
        assert isinstance(validate_read_only_sql(sql), SuccessResult)

    @pytest.mark.parametrize(
        ("sql", "reason"),
        [
            pytest.param("SELECT 1; SELECT 2", "Multi-statement", id="two-statements"),
            pytest.param("MERGE t USING s ON true", "does not start with", id="prefix"),
            pytest.param("SELECT * FROM t WHERE DELETE", "blocked keyword: DELETE", id="kw"),
        ],
    )
    def test_refuses(self, sql: str, reason: str) -> None:
        result = validate_read_only_sql(sql)

        assert isinstance(result, ErrorResult)
        assert reason in result.error


class TestValidateBigquerySql:
    def test_accepts_a_select(self) -> None:
        assert isinstance(validate_bigquery_sql("SELECT x FROM p.d.t"), SuccessResult)

    def test_reports_the_shared_rule_first(self) -> None:
        result = validate_bigquery_sql("DROP TABLE p.d.t")

        assert isinstance(result, ErrorResult)
        assert "does not start with" in result.error

    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param('SELECT "\'"; EXECUTE/**/IMMEDIATE "x"; SELECT "\'"', id="swallow"),
            pytest.param("SELECT 1 #x\r; UNDROP SCHEMA p.d", id="cr"),
            pytest.param("SELECT 1\f", id="formfeed"),
            pytest.param("SELECT 1 -- c\n; RAISE USING MESSAGE = 'x'", id="hidden-second"),
            pytest.param("SELECT 1;", id="trailing-semicolon"),
            pytest.param("SELECT 'open", id="unterminated"),
            pytest.param("EXPLAIN SELECT 1", id="not-select"),
            pytest.param("WITH a AS (SELECT 1) EXPORT/**/DATA OPTIONS()", id="comment-split"),
        ],
    )
    def test_refuses_hidden_statements(self, sql: str) -> None:
        assert isinstance(validate_bigquery_sql(sql), ErrorResult)

    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param('SELECT "it\'s; fine" AS s', id="quote-in-double"),
            pytest.param("SELECT * FROM `p.d.t;x`", id="backtick"),
            pytest.param("# standardSQL\nSELECT 1 -- note; here", id="comments"),
        ],
    )
    def test_statement_check_reads_quotes_and_comments(self, sql: str) -> None:
        result = validate_bigquery_statement(sql)

        assert isinstance(result, SuccessResult)
        assert ";" not in result.value

    @pytest.mark.parametrize(
        ("sql", "keyword"),
        [
            pytest.param("SELECT 1 FROM t WHERE x IN (CALL p())", "CALL", id="call"),
            pytest.param("WITH a AS (SELECT 1) EXPORT\n  DATA OPTIONS()", "EXPORT DATA", id="ws"),
            pytest.param("SELECT * FROM EXTERNAL_QUERY('c', 'x')", "EXTERNAL_QUERY", id="ext"),
        ],
    )
    def test_refuses_bigquery_writers(self, sql: str, keyword: str) -> None:
        result = validate_bigquery_sql(sql)

        assert isinstance(result, ErrorResult)
        assert result.error == f"Query contains blocked keyword: {keyword}"


class TestStatementCheckIsLinear:
    """GH-1633 PR #2022 round 3: no adversarial input may stall the hook."""

    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param("SELECT 1 " + "EXPORT/*" * 3000 + "*/" * 3000, id="lazy-gap"),
            pytest.param("SELECT 1 /*" + "/* " * 8000 + "*/", id="nested-looking"),
            pytest.param("SELECT 1 " + "EXPORT " * 9000, id="many-export"),
            pytest.param("SELECT 'x' " + "-- a\n" * 12000, id="many-comments"),
            pytest.param("SELECT " + "a" * (MAX_STATEMENT_CHARS - 7), id="max-length"),
        ],
    )
    def test_finishes_in_milliseconds(self, sql: str) -> None:
        started = time.perf_counter()
        validate_bigquery_sql(sql)
        elapsed = time.perf_counter() - started

        assert elapsed < 0.05

    def test_refuses_over_the_cap(self) -> None:
        result = validate_bigquery_statement("SELECT " + "a" * MAX_STATEMENT_CHARS)

        assert isinstance(result, ErrorResult)
        assert "longer than" in result.error


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param("SELECT * FROM t WHERE note = 'call me'", id="call"),
        pytest.param('SELECT "merge later" AS s', id="merge"),
        pytest.param("SELECT 'x merge y'", id="develop-literal"),
        pytest.param("SELECT 1 -- export data\n", id="develop-comment"),
        pytest.param("SELECT 'load   data' AS s", id="load-data"),
        pytest.param("SELECT 'execute immediate'", id="execute-immediate"),
    ],
)
def test_bigquery_keywords_inside_literals_stay_refused_as_on_develop(sql: str) -> None:
    # Fail closed beats the false positive: develop refused these.
    assert isinstance(validate_bigquery_statement(sql), ErrorResult)
    assert isinstance(validate_bigquery_sql(sql), ErrorResult)


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param("SELECT '''a'''' ; CALL p(); SELECT 1 -- '", id="single-run"),
        pytest.param('SELECT """a"""" ; CALL p(); SELECT 1 -- "', id="double-run"),
        pytest.param("SELECT '''' AS s", id="bare-single-run"),
        pytest.param('SELECT """""" AS s', id="six-double"),
    ],
)
def test_refuses_runs_of_four_quotes(sql: str) -> None:
    assert isinstance(validate_bigquery_statement(sql), ErrorResult)
    assert isinstance(validate_bigquery_sql(sql), ErrorResult)


def test_read_only_verbs_exclude_writers() -> None:
    assert BQ_READ_ONLY_VERBS.isdisjoint({"rm", "load", "cp", "mk", "update", "insert"})
