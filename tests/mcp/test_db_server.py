"""Tests for db_server SQL validation and query function."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dev10x.domain.result import ErrorResult, SuccessResult
from dev10x.domain.sql import is_read_only_sql


class TestIsReadOnlySql:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1",
            "SELECT count(*) FROM users",
            "select * from orders where id = 5",
            "  SELECT id FROM t",
        ],
    )
    def test_allows_plain_select(self, sql: str) -> None:
        assert is_read_only_sql(sql=sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "WITH orders AS (SELECT id FROM orders) SELECT count(*) FROM orders",
            (
                "WITH active AS (SELECT * FROM users WHERE active = true), "
                "counts AS (SELECT department, count(*) FROM active GROUP BY department) "
                "SELECT * FROM counts"
            ),
            "with recursive tree as (select id from nodes) select * from tree",
        ],
    )
    def test_allows_read_only_cte(self, sql: str) -> None:
        assert is_read_only_sql(sql=sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "EXPLAIN SELECT * FROM users",
            "EXPLAIN ANALYZE SELECT 1",
        ],
    )
    def test_allows_explain(self, sql: str) -> None:
        assert is_read_only_sql(sql=sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "SHOW search_path",
            "SHOW server_version",
        ],
    )
    def test_allows_show(self, sql: str) -> None:
        assert is_read_only_sql(sql=sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "-- comment\nSELECT 1",
            "-- header\n-- another comment\nWITH cte AS (SELECT 1) SELECT * FROM cte",
        ],
    )
    def test_allows_sql_with_leading_comments(self, sql: str) -> None:
        assert is_read_only_sql(sql=sql) is True

    @pytest.mark.parametrize(
        "keyword",
        ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE"],
    )
    def test_blocks_write_keywords(self, keyword: str) -> None:
        assert is_read_only_sql(sql=f"{keyword} INTO users VALUES (1)") is False

    @pytest.mark.parametrize(
        "keyword",
        ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE"],
    )
    def test_blocks_write_keywords_inside_cte(self, keyword: str) -> None:
        sql = f"WITH cte AS ({keyword} INTO users VALUES (1) RETURNING id) SELECT * FROM cte"
        assert is_read_only_sql(sql=sql) is False

    @pytest.mark.parametrize(
        "keyword",
        [
            "GRANT",
            "REVOKE",
            "VACUUM",
            "REINDEX",
            "CLUSTER",
            "COPY",
            "LOCK",
            "DISCARD",
            "RESET",
            "REASSIGN",
        ],
    )
    def test_blocks_admin_keywords(self, keyword: str) -> None:
        assert is_read_only_sql(sql=f"{keyword} something") is False

    def test_blocks_refresh_materialized(self) -> None:
        assert is_read_only_sql(sql="REFRESH MATERIALIZED VIEW my_view") is False

    def test_blocks_unknown_prefix(self) -> None:
        assert is_read_only_sql(sql="CALL my_procedure()") is False

    def test_blocks_empty_string(self) -> None:
        assert is_read_only_sql(sql="") is False

    def test_blocks_comment_only(self) -> None:
        assert is_read_only_sql(sql="-- just a comment") is False


class TestQueryFunctionValidation:
    """Test query function SQL validation blocking."""

    @patch("dev10x.db.run_script")
    def test_blocks_insert_statement(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        result = query(database="pp", sql="INSERT INTO users VALUES (1)")
        assert isinstance(result, ErrorResult)
        assert "blocked" in result.details
        mock_run_script.assert_not_called()

    @patch("dev10x.db.run_script")
    def test_blocks_delete_statement(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        result = query(database="pp", sql="DELETE FROM users")
        assert isinstance(result, ErrorResult)
        assert "blocked" in result.details
        mock_run_script.assert_not_called()

    @patch("dev10x.db.run_script")
    def test_blocks_update_statement(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        result = query(database="pp", sql="UPDATE users SET id=1")
        assert isinstance(result, ErrorResult)
        assert "blocked" in result.details
        mock_run_script.assert_not_called()

    @patch("dev10x.db.run_script")
    def test_blocks_drop_statement(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        result = query(database="pp", sql="DROP TABLE users")
        assert isinstance(result, ErrorResult)
        assert "blocked" in result.details
        mock_run_script.assert_not_called()


class TestQueryFunctionSuccess:
    """Test successful query execution with script mocking."""

    @patch("dev10x.db.run_script")
    def test_executes_valid_select_with_json_output(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {
                "columns": ["id", "name"],
                "rows": [(1, "Alice"), (2, "Bob")],
                "row_count": 2,
            }
        )
        mock_run_script.return_value = mock_result

        result = query(database="pp", sql="SELECT * FROM users")

        assert isinstance(result, SuccessResult)
        assert result.value.get("columns") == ["id", "name"]
        assert result.value.get("row_count") == 2
        mock_run_script.assert_called_once()

    @patch("dev10x.db.run_script")
    def test_handles_script_execution_error(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Database connection error"
        mock_run_script.return_value = mock_result

        result = query(database="pp", sql="SELECT * FROM users")

        assert isinstance(result, ErrorResult)
        assert "Database connection error" in result.error

    @patch("dev10x.db.run_script")
    def test_handles_non_json_output(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Plain text output"
        mock_run_script.return_value = mock_result

        result = query(database="pp", sql="SELECT * FROM users")

        assert isinstance(result, SuccessResult)
        assert result.value["raw_output"] == "Plain text output"

    @patch("dev10x.db.run_script")
    def test_passes_correct_arguments_to_script(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"columns": [], "rows": [], "row_count": 0})
        mock_run_script.return_value = mock_result

        query(database="backend", sql="SELECT 1")

        mock_run_script.assert_called_once_with(
            "skills/db-psql/scripts/db.sh", "backend", "SELECT 1"
        )

    @patch("dev10x.db.run_script")
    def test_handles_empty_json_response(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({})
        mock_run_script.return_value = mock_result

        result = query(database="pp", sql="SELECT * FROM users")

        assert isinstance(result, SuccessResult)
        assert result.value == {}

    @patch("dev10x.db.run_script")
    def test_handles_cte_query(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"columns": ["id"], "rows": [[1]], "row_count": 1})
        mock_run_script.return_value = mock_result

        result = query(database="pp", sql="WITH cte AS (SELECT 1) SELECT * FROM cte")

        assert isinstance(result, SuccessResult)
        assert result.value.get("row_count") == 1

    @patch("dev10x.db.run_script")
    def test_handles_explain_query(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Seq Scan on users"
        mock_run_script.return_value = mock_result

        result = query(database="pp", sql="EXPLAIN SELECT * FROM users")

        assert isinstance(result, SuccessResult)
        assert "raw_output" in result.value

    @patch("dev10x.db.run_script")
    def test_different_database_aliases(self, mock_run_script: MagicMock) -> None:
        from dev10x.db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"rows": []})
        mock_run_script.return_value = mock_result

        for db_alias in ["pp", "ps", "bp", "bs"]:
            query(database=db_alias, sql="SELECT 1")

        assert mock_run_script.call_count == 4


class TestServerDbWrapper:
    """Test async query wrapper in server_db delegates to dev10x.mcp.db."""

    @pytest.mark.asyncio
    @patch("dev10x.db.run_script")
    async def test_async_query_delegates_to_db_module(self, mock_run_script: MagicMock) -> None:
        from dev10x.mcp.server_db import query

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"columns": ["id"], "rows": [[1]], "row_count": 1})
        mock_run_script.return_value = mock_result

        result = await query(database="pp", sql="SELECT 1")

        assert result.get("row_count") == 1
        mock_run_script.assert_called_once()

    @pytest.mark.asyncio
    @patch("dev10x.db.run_script")
    async def test_async_query_blocks_write_statements(self, mock_run_script: MagicMock) -> None:
        from dev10x.mcp.server_db import query

        result = await query(database="pp", sql="DROP TABLE users")

        assert result.get("blocked") is True
        mock_run_script.assert_not_called()
