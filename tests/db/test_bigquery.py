"""dev10x.db.bigquery — read-only bq wrapper (GH-1633). bq is always stubbed."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

import pytest

from dev10x.core.domain.common.result import ErrorResult, SuccessResult
from dev10x.db import bigquery


@dataclass
class FakeBq:
    stdout: str = "[]"
    stderr: str = ""
    returncode: int = 0
    raises: BaseException | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(
            args=args, returncode=self.returncode, stdout=self.stdout, stderr=self.stderr
        )

    @property
    def argv(self) -> list[str]:
        return self.calls[-1]["args"]


@pytest.fixture
def fake_bq(monkeypatch: pytest.MonkeyPatch) -> FakeBq:
    fake = FakeBq(stdout=json.dumps([{"id": 1}, {"id": 2}]))
    monkeypatch.setattr(bigquery, "run", fake)
    return fake


ISOLATION = [f"--bigqueryrc={os.devnull}", "--headless", "--format=json"]


class TestQuery:
    def test_runs_the_select_with_isolated_flags(self, fake_bq: FakeBq) -> None:
        result = bigquery.query(sql="  SELECT id FROM p.d.t  ")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "rows": [{"id": 1}, {"id": 2}],
            "row_count": 2,
            "max_rows": 100,
            "truncated": False,
        }
        assert fake_bq.argv == [
            "bq",
            *ISOLATION,
            "query",
            "--nouse_legacy_sql",
            "--max_rows=100",
            f"--maximum_bytes_billed={bigquery.DEFAULT_MAX_BYTES_BILLED}",
            "--job_timeout_ms=120000",
            "--",
            "SELECT id FROM p.d.t",
        ]
        assert fake_bq.calls[-1]["timeout"] == bigquery.BQ_TIMEOUT_SECONDS
        assert fake_bq.calls[-1]["stdin"] == subprocess.DEVNULL

    def test_passes_project_location_and_dry_run(self, fake_bq: FakeBq) -> None:
        fake_bq.stdout = json.dumps({"statistics": {"totalBytesProcessed": "42"}})

        result = bigquery.query(
            sql="WITH a AS (SELECT 1) SELECT * FROM a",
            project_id="my-project",
            location="EU",
            max_rows=5,
            maximum_bytes_billed=1000,
            dry_run=True,
        )

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "dry_run": True,
            "job": {"statistics": {"totalBytesProcessed": "42"}},
        }
        assert fake_bq.argv[4:7] == ["--project_id=my-project", "--location=EU", "query"]
        assert "--dry_run" in fake_bq.argv

    def test_relays_a_bq_failure(self, fake_bq: FakeBq) -> None:
        fake_bq.returncode, fake_bq.stderr = 1, "Quota exceeded"

        result = bigquery.query(sql="SELECT 1")

        assert isinstance(result, ErrorResult)
        assert result.error == "Quota exceeded"

    def test_flags_a_full_page_as_truncated(self, fake_bq: FakeBq) -> None:
        result = bigquery.query(sql="SELECT 1", max_rows=2)

        assert isinstance(result, SuccessResult)
        assert result.value["truncated"] is True

    def test_reports_non_list_output_as_raw(self, fake_bq: FakeBq) -> None:
        fake_bq.stdout = "not json"

        result = bigquery.query(sql="SELECT 1")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "rows": [],
            "row_count": 0,
            "max_rows": 100,
            "truncated": False,
            "raw": {"raw_output": "not json"},
        }

    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param("SELECT 'a;b' AS s", id="semicolon-in-single"),
            pytest.param('SELECT "it\'s; fine" AS s', id="quote-in-double"),
            pytest.param("SELECT '''x;'y''' AS s", id="triple"),
            pytest.param(r"SELECT 'it\'s' AS s", id="escaped-quote"),
            pytest.param("SELECT * FROM `p.d.t;x`", id="backtick"),
            pytest.param("# standardSQL\nSELECT 1 -- note; here\n/* ; */", id="comments"),
        ],
    )
    def test_accepts_quoted_and_commented_reads(self, fake_bq: FakeBq, sql: str) -> None:
        assert isinstance(bigquery.query(sql=sql), SuccessResult)

    @pytest.mark.parametrize(
        "sql",
        [
            pytest.param("DELETE FROM p.d.t WHERE true", id="dml"),
            pytest.param("EXPLAIN SELECT 1", id="explain-not-bigquery"),
            pytest.param("SELECT 1; DROP TABLE p.d.t", id="multi"),
            pytest.param("SELECT * FROM p.d.t WHERE x = (CALL p.d.proc())", id="call"),
            pytest.param("WITH a AS (SELECT 1) MERGE p.d.t USING a ON true", id="merge"),
            pytest.param(
                r"SELECT * FROM EXTERNAL_QUERY('c', '\x44ELETE FROM t')", id="external-query"
            ),
            pytest.param(
                """SELECT "'"; EXECUTE/**/IMMEDIATE CONCAT("DEL","ETE FROM p.d.t"); SELECT "'\"""",
                id="quote-swallows-script",
            ),
            pytest.param("SELECT 1 FROM t WHERE x IN (CALL/**/p())", id="comment-split-call"),
            pytest.param("WITH a AS (SELECT 1) EXPORT/**/DATA OPTIONS()", id="comment-split"),
            pytest.param("SELECT 1 -- x\n; DELETE FROM p.d.t", id="line-comment-hides-sep"),
            pytest.param("/* SELECT */ DELETE FROM p.d.t", id="comment-prefix"),
            pytest.param("SELECT 1;", id="trailing-semicolon"),
            pytest.param("SELECT * FROM t WHERE note = 'call me'", id="keyword-in-literal"),
            pytest.param("SELECT '''a'''' ; CALL p(); SELECT 1 -- '", id="quote-run-single"),
            pytest.param('SELECT """a"""" ; CALL p(); SELECT 1 -- "', id="quote-run-double"),
            pytest.param("SELECT 'open", id="unterminated-quote"),
            pytest.param(
                "SELECT 1 #x\r; EXPORT/**/DATA OPTIONS(uri='gs://b/*') AS SELECT 1",
                id="cr-ends-hash-comment",
            ),
            pytest.param("SELECT 1 #\r; UNDROP SCHEMA p.d", id="cr-undrop"),
            pytest.param("SELECT 1 --x\f; ASSERT false", id="formfeed"),
            pytest.param("SELECT 1\v", id="vtab"),
            pytest.param("SELECT 1 -- c\n; RAISE USING MESSAGE = 'x'", id="hidden-second"),
            pytest.param("--destination_table=p:d.t\nSELECT 1", id="leading-flag"),
            pytest.param("--flagfile=/tmp/f\nSELECT 1", id="leading-flagfile"),
            pytest.param("SELECT 1 /* open", id="unterminated-comment"),
            pytest.param(r"SELECT r'\' ; DROP TABLE t; '", id="raw-string"),
            pytest.param("SELECT " + "x" * bigquery.MAX_SQL_CHARS, id="too-long"),
            pytest.param("", id="empty"),
        ],
    )
    def test_refuses_without_running_bq(self, fake_bq: FakeBq, sql: str) -> None:
        result = bigquery.query(sql=sql)

        assert isinstance(result, ErrorResult)
        assert result.details["blocked"] is True
        assert fake_bq.calls == []

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            pytest.param({"max_rows": 0}, "max_rows must be between 1", id="rows-low"),
            pytest.param({"max_rows": 10_001}, "max_rows must be between 1", id="rows-high"),
            pytest.param(
                {"maximum_bytes_billed": bigquery.MAX_BYTES_BILLED_CAP + 1},
                "maximum_bytes_billed must be between 1",
                id="bytes-high",
            ),
            pytest.param({"project_id": "--flagfile=x"}, "not a valid GCP project", id="project"),
            pytest.param({"location": "--replace"}, "not a valid BigQuery location", id="loc"),
        ],
    )
    def test_refuses_bad_options(
        self, fake_bq: FakeBq, kwargs: dict[str, Any], message: str
    ) -> None:
        result = bigquery.query(sql="SELECT 1", **kwargs)

        assert isinstance(result, ErrorResult)
        assert message in result.error
        assert fake_bq.calls == []


class TestRunBq:
    def test_drops_flag_injecting_environment(
        self, fake_bq: FakeBq, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BIGQUERYRC", "/tmp/evil")
        monkeypatch.setenv("FLAGS_destination_table", "p:d.t")
        monkeypatch.setenv("KEEP_ME", "1")

        bigquery.run_bq(global_flags=[], args=["ls"])

        env = fake_bq.calls[-1]["env"]
        assert ("BIGQUERYRC" in env, "FLAGS_destination_table" in env) == (False, False)
        assert env["KEEP_ME"] == "1"

    @pytest.mark.parametrize(
        ("stdout", "stderr", "expected"),
        [
            pytest.param("", "Access Denied", "Access Denied", id="stderr"),
            pytest.param("BigQuery error", "", "BigQuery error", id="stdout"),
            pytest.param("", "", "bq exited with status 2.", id="silent"),
        ],
    )
    def test_reports_a_failed_run(
        self, fake_bq: FakeBq, stdout: str, stderr: str, expected: str
    ) -> None:
        fake_bq.returncode, fake_bq.stdout, fake_bq.stderr = 2, stdout, stderr

        result = bigquery.run_bq(global_flags=[], args=["ls"])

        assert isinstance(result, ErrorResult)
        assert result.error == expected

    def test_refuses_oversized_output(
        self, fake_bq: FakeBq, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bigquery, "MAX_OUTPUT_CHARS", 4)
        fake_bq.stdout = "[1, 2, 3]"

        result = bigquery.run_bq(global_flags=[], args=["ls"])

        assert isinstance(result, ErrorResult)
        assert "lower max_rows" in result.error

    def test_caps_error_text(self, fake_bq: FakeBq) -> None:
        fake_bq.returncode, fake_bq.stderr = 1, "e" * 10_000

        result = bigquery.run_bq(global_flags=[], args=["ls"])

        assert isinstance(result, ErrorResult)
        assert len(result.error) == 4096

    def test_reports_a_missing_bq(self, fake_bq: FakeBq) -> None:
        fake_bq.raises = FileNotFoundError("bq")

        result = bigquery.run_bq(global_flags=[], args=["ls"])

        assert isinstance(result, ErrorResult)
        assert result.error == bigquery.BQ_NOT_FOUND_MSG

    def test_reports_a_timeout_with_guidance(self, fake_bq: FakeBq) -> None:
        fake_bq.raises = subprocess.TimeoutExpired(cmd="bq", timeout=1)

        result = bigquery.run_bq(global_flags=[], args=["ls"])

        assert isinstance(result, ErrorResult)
        assert "Please try again" in result.error


class TestRefs:
    @pytest.mark.parametrize(
        ("dataset", "expected"),
        [("my-project.sales", "my-project:sales"), ("my-project:sales", "my-project:sales")],
    )
    def test_dataset_ref(self, dataset: str, expected: str) -> None:
        result = bigquery.dataset_ref(dataset=dataset)

        assert isinstance(result, SuccessResult)
        assert result.value == expected

    @pytest.mark.parametrize("dataset", ["sales", "-x.sales", "my-project.sa les"])
    def test_dataset_ref_refuses(self, dataset: str) -> None:
        assert isinstance(bigquery.dataset_ref(dataset=dataset), ErrorResult)

    def test_table_ref(self) -> None:
        result = bigquery.table_ref(table="my-project.sales.orders")

        assert isinstance(result, SuccessResult)
        assert result.value == "my-project:sales.orders"

    @pytest.mark.parametrize("table", ["sales.orders", "my-project.sales.--replace x"])
    def test_table_ref_refuses(self, table: str) -> None:
        assert isinstance(bigquery.table_ref(table=table), ErrorResult)


class TestDatasets:
    def test_lists_datasets(self, fake_bq: FakeBq) -> None:
        result = bigquery.datasets(project_id="my-project", max_results=5)

        assert isinstance(result, SuccessResult)
        assert result.value["project_id"] == "my-project"
        assert fake_bq.argv == [
            "bq",
            *ISOLATION,
            "--project_id=my-project",
            "ls",
            "--max_results=5",
        ]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            pytest.param({"project_id": "X"}, "not a valid GCP project", id="project"),
            pytest.param({"project_id": "my-project", "max_results": 0}, "max_results", id="n"),
        ],
    )
    def test_refuses(self, fake_bq: FakeBq, kwargs: dict[str, Any], message: str) -> None:
        result = bigquery.datasets(**kwargs)

        assert isinstance(result, ErrorResult)
        assert message in result.error
        assert fake_bq.calls == []

    def test_relays_a_bq_failure(self, fake_bq: FakeBq) -> None:
        fake_bq.returncode, fake_bq.stderr = 1, "Not found"

        result = bigquery.datasets(project_id="my-project")

        assert isinstance(result, ErrorResult)


class TestTables:
    def test_lists_tables(self, fake_bq: FakeBq) -> None:
        result = bigquery.tables(dataset="my-project.sales")

        assert isinstance(result, SuccessResult)
        assert result.value["dataset"] == "my-project.sales"
        assert fake_bq.argv[-3:] == ["ls", "--max_results=200", "my-project:sales"]

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            pytest.param({"dataset": "sales"}, "project.dataset", id="ref"),
            pytest.param({"dataset": "my-project.sales", "max_results": 0}, "max_results", id="n"),
        ],
    )
    def test_refuses(self, fake_bq: FakeBq, kwargs: dict[str, Any], message: str) -> None:
        result = bigquery.tables(**kwargs)

        assert isinstance(result, ErrorResult)
        assert message in result.error
        assert fake_bq.calls == []

    def test_relays_a_bq_failure(self, fake_bq: FakeBq) -> None:
        fake_bq.returncode, fake_bq.stderr = 1, "Not found"

        assert isinstance(bigquery.tables(dataset="my-project.sales"), ErrorResult)


class TestSchema:
    def test_shows_the_schema(self, fake_bq: FakeBq) -> None:
        fake_bq.stdout = json.dumps([{"name": "id", "type": "INTEGER"}])

        result = bigquery.schema(table="my-project.sales.orders")

        assert isinstance(result, SuccessResult)
        assert result.value == {
            "table": "my-project.sales.orders",
            "schema": [{"name": "id", "type": "INTEGER"}],
        }
        assert fake_bq.argv[-3:] == ["show", "--schema", "my-project:sales.orders"]

    def test_refuses_a_bad_ref(self, fake_bq: FakeBq) -> None:
        assert isinstance(bigquery.schema(table="orders"), ErrorResult)
        assert fake_bq.calls == []

    def test_relays_a_bq_failure(self, fake_bq: FakeBq) -> None:
        fake_bq.returncode, fake_bq.stderr = 1, "Not found"

        assert isinstance(bigquery.schema(table="my-project.sales.orders"), ErrorResult)
