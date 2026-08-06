"""Tests for SqlSafetyValidator."""

from __future__ import annotations

import pytest

from dev10x.validators.sql_safety import SqlSafetyValidator
from tests.fakers import BashHookInputFaker


def _make_input(*, command: str) -> BashHookInputFaker:
    return BashHookInputFaker.build(
        command=command,
    )


class TestShouldRun:
    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            'db.sh pp "SELECT 1"',
            "psql -h localhost",
            "python3 /tmp/script.py",  # no db keyword
        ],
    )
    def test_should_run_for_db_commands(self, validator: SqlSafetyValidator, command: str) -> None:
        inp = _make_input(command=command)
        expected = "db.sh" in command or "psql" in command
        assert validator.should_run(inp=inp) is expected

    def test_false_for_unrelated(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command="git status")
        assert validator.should_run(inp=inp) is False


class TestDirectConnection:
    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    def test_blocks_psycopg2(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command="python3 -c 'import psycopg2'")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "psycopg2" in result.message

    def test_blocks_postgres_url(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(
            command="python3 -c \"conn = psycopg2.connect('postgresql://user:pass@host')\""
        )
        result = validator.validate(inp=inp)
        assert result is not None


class TestDirectPsql:
    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    def test_blocks_direct_psql(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command="psql -h localhost -d mydb")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Direct psql calls" in result.message


class TestWrappedPsqlExemption:
    """psql wrapped by docker exec / op run is exempt (GH-474 #4)."""

    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "docker exec dvi-enum-test psql -U postgres -d testdb -c 'SELECT 1'",
            "op run --env-file=.env -- psql -h localhost -d mydb -c 'SELECT 1'",
            "/usr/local/bin/op run -- psql -d mydb -c 'SELECT 1'",
        ],
    )
    def test_allows_wrapped_psql(self, validator: SqlSafetyValidator, command: str) -> None:
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is None

    @pytest.mark.parametrize(
        "command",
        [
            'docker exec tt-pos-postgis psql -U u -d postgres -c "DROP DATABASE IF EXISTS t;"',
            "docker exec c psql -d postgres -c 'TRUNCATE users'",
            "docker exec c psql -d postgres --command='DELETE FROM users'",
            "op run --env-file=.env -- psql -d mydb -c 'DROP TABLE users'",
            "/usr/local/bin/op run -- psql -d mydb -c 'ALTER TABLE t ADD COLUMN c int'",
        ],
    )
    def test_blocks_write_through_wrapper(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        """GH-1034: the wrapper exemption must not cover writes."""
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_terminate_backend_through_wrapper(self, validator: SqlSafetyValidator) -> None:
        """GH-1034: pg_terminate_backend is a SELECT-shaped destructive call."""
        sql = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'test_db' AND pid <> pg_backend_pid()"
        )
        inp = _make_input(command=f'docker exec c psql -U u -d postgres -c "{sql}"')
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_script_file_through_wrapper(self, validator: SqlSafetyValidator) -> None:
        """GH-1034: -f contents are unknowable at match time — treat as a write."""
        inp = _make_input(command="docker exec c psql -d mydb -f /tmp/teardown.sql")
        result = validator.validate(inp=inp)
        assert result is not None

    @pytest.mark.parametrize(
        "command",
        [
            "docker exec c psql -tAc 'DROP TABLE users'",
            "docker exec c psql -tAc'DROP TABLE users'",
            "docker exec c psql -cDROP TABLE users",
            "docker exec c psql -U u -tAf /tmp/teardown.sql",
        ],
    )
    def test_blocks_write_in_short_option_bundle(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        """getopt bundles and attached values are ordinary scripting shapes."""
        inp = _make_input(command=command)
        assert validator.validate(inp=inp) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "docker exec c psql --command 'DROP TABLE users'",
            "docker exec c psql --file=/tmp/teardown.sql",
            "docker exec c psql --file /tmp/teardown.sql",
        ],
    )
    def test_blocks_write_in_long_option_form(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        assert validator.validate(inp=inp) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "docker exec c psql -tAc 'SELECT 1'",
            "docker exec c psql -tAc'SELECT 1'",
            # A bundle of value-less flags must not swallow the next token.
            "docker exec c psql -tA -c 'SELECT 1'",
            # -U takes a value; `drop_user` must not be read as a flag.
            "docker exec c psql -U drop_user -c 'SELECT 1'",
        ],
    )
    def test_allows_read_in_short_option_bundle(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        inp = _make_input(command=command)
        assert validator.validate(inp=inp) is None

    def test_allows_wrapped_psql_without_arguments(self, validator: SqlSafetyValidator) -> None:
        """An interactive in-container session carries no SQL to check."""
        inp = _make_input(command="docker exec c psql")
        assert validator.validate(inp=inp) is None

    def test_exempt_segment_without_psql_falls_through(
        self, validator: SqlSafetyValidator
    ) -> None:
        """A wrapper segment that runs something else still lets later
        segments be judged on their own."""
        inp = _make_input(command="docker exec c ls -l | psql -h prod -d db")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Direct psql calls" in result.message

    def test_still_blocks_bare_psql_after_exempt_segment(
        self, validator: SqlSafetyValidator
    ) -> None:
        command = "docker exec c psql -c 'SELECT 1' | psql -h prod -d db"
        inp = _make_input(command=command)
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Direct psql calls" in result.message

    def test_handles_empty_pipe_segment(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command="| psql -h prod -d db")
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Direct psql calls" in result.message


class TestSqlValidation:
    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    def test_allows_select(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command='db.sh pp "SELECT count(*) FROM users"')
        result = validator.validate(inp=inp)
        assert result is None

    @pytest.mark.parametrize(
        "keyword",
        ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"],
    )
    def test_blocks_write_keywords(self, validator: SqlSafetyValidator, keyword: str) -> None:
        inp = _make_input(command=f'db.sh pp "{keyword} INTO users VALUES (1)"')
        result = validator.validate(inp=inp)
        assert result is not None

    def test_allows_cte(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command='db.sh pp "WITH cte AS (SELECT 1) SELECT * FROM cte"')
        result = validator.validate(inp=inp)
        assert result is None

    @pytest.mark.parametrize(
        "keyword",
        ["INSERT", "UPDATE", "DELETE", "DROP"],
    )
    def test_blocks_write_inside_cte(self, validator: SqlSafetyValidator, keyword: str) -> None:
        sql = f"WITH cte AS ({keyword} INTO t VALUES (1) RETURNING id) SELECT * FROM cte"
        inp = _make_input(command=f'db.sh pp "{sql}"')
        result = validator.validate(inp=inp)
        assert result is not None

    def test_blocks_multi_statement(self, validator: SqlSafetyValidator) -> None:
        inp = _make_input(command='db.sh pp "SELECT 1; SELECT 2"')
        result = validator.validate(inp=inp)
        assert result is not None
        assert "Multi-statement" in result.message

    def test_allows_semicolon_inside_string_literal(self, validator: SqlSafetyValidator) -> None:
        sql = "SELECT STRING_AGG(name, '; ' ORDER BY name) FROM users"
        inp = _make_input(command=f'db.sh pp "{sql}"')
        result = validator.validate(inp=inp)
        assert result is None

    def test_blocks_multi_statement_with_string_literal(
        self, validator: SqlSafetyValidator
    ) -> None:
        sql = "SELECT '; '; DROP TABLE users"
        inp = _make_input(command=f'db.sh pp "{sql}"')
        result = validator.validate(inp=inp)
        assert result is not None
