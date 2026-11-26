"""Read-only BigQuery access through the ``bq`` CLI (GH-1633).

Authentication is whatever ``gcloud`` / ``bq`` already hold; there is no
DSN or ``databases.yaml``. Tables are addressed ``project.dataset.table``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from dev10x.core.domain.common.result import ErrorResult, Result, err, ok
from dev10x.core.domain.rules.read_only_sql import validate_bigquery_statement
from dev10x.core.subprocess_utils import run

BQ_BINARY = "bq"
BQ_TIMEOUT_SECONDS = 120

DEFAULT_MAX_ROWS = 100
MAX_ROWS_CAP = 10_000
DEFAULT_MAX_RESULTS = 200
MAX_RESULTS_CAP = 10_000
DEFAULT_MAX_BYTES_BILLED = 10 * 1024**3
MAX_BYTES_BILLED_CAP = 1024**4
MAX_SQL_CHARS = 64 * 1024

_PROJECT = r"[a-z][a-z0-9-]{4,28}[a-z0-9]"
_DATASET = r"[A-Za-z0-9_]{1,1024}"
_TABLE = r"[A-Za-z0-9_-]{1,1024}"
_PROJECT_RE = re.compile(_PROJECT)
_DATASET_REF_RE = re.compile(rf"(?P<project>{_PROJECT})[.:](?P<dataset>{_DATASET})")
_TABLE_REF_RE = re.compile(
    rf"(?P<project>{_PROJECT})[.:](?P<dataset>{_DATASET})\.(?P<table>{_TABLE})"
)
_LOCATION_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,62}")
MAX_OUTPUT_CHARS = 16 * 1024 * 1024
_FLAG_ENV_RE = re.compile(r"^(BIGQUERYRC|FLAGS_\w*)$")

BQ_NOT_FOUND_MSG = (
    "The bq CLI was not found on PATH. Install the Google Cloud SDK, then "
    "run `gcloud auth login` and `gcloud auth application-default login`."
)


def _isolated_global_flags() -> list[str]:
    return [f"--bigqueryrc={os.devnull}", "--headless", "--format=json"]


def _bq_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not _FLAG_ENV_RE.match(key)}


def _in_range(*, name: str, value: int, cap: int) -> ErrorResult | None:
    if 1 <= value <= cap:
        return None
    return err(f"{name} must be between 1 and {cap}, got {value}.")


def dataset_ref(*, dataset: str) -> Result[str]:
    match = _DATASET_REF_RE.fullmatch(dataset)
    if not match:
        return err(
            f"Dataset must be addressed as project.dataset, got {dataset!r}. "
            "Project ids are 6-30 lowercase letters, digits or hyphens; "
            "dataset ids are letters, digits or underscores."
        )
    return ok(f"{match['project']}:{match['dataset']}")


def table_ref(*, table: str) -> Result[str]:
    match = _TABLE_REF_RE.fullmatch(table)
    if not match:
        return err(
            f"Table must be addressed as project.dataset.table, got {table!r}. "
            "Table ids are letters, digits, underscores or hyphens."
        )
    return ok(f"{match['project']}:{match['dataset']}.{match['table']}")


def run_bq(*, global_flags: list[str], args: list[str]) -> Result[Any]:
    command = [BQ_BINARY, *_isolated_global_flags(), *global_flags, *args]
    try:
        completed = run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            env=_bq_env(),
            timeout=BQ_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return err(BQ_NOT_FOUND_MSG)
    except subprocess.TimeoutExpired:
        return err(
            f"bq did not finish within {BQ_TIMEOUT_SECONDS}s. Please try again "
            "with a narrower query, a LIMIT, or a partition filter."
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:4096]
        return err(detail or f"bq exited with status {completed.returncode}.")
    if len(completed.stdout) > MAX_OUTPUT_CHARS:
        return err(
            f"bq returned more than {MAX_OUTPUT_CHARS} characters. Select fewer "
            "columns or lower max_rows."
        )
    try:
        return ok(json.loads(completed.stdout))
    except json.JSONDecodeError:
        return ok({"raw_output": completed.stdout})


def validate_query(*, sql: str) -> Result[str]:
    if len(sql) > MAX_SQL_CHARS:
        return err(f"SQL is longer than {MAX_SQL_CHARS} characters.")
    stripped = sql.strip()
    if stripped.startswith("-"):
        return err(
            "SQL must not start with '-': bq would read it as a flag. "
            "Move a leading -- comment below the SELECT, or drop it."
        )
    statement = validate_bigquery_statement(sql)
    if isinstance(statement, ErrorResult):
        return err(
            f"{statement.error}\nOnly one SELECT or WITH statement is allowed through "
            "dev10x-db:bq. Print any other statement for the user to run manually."
        )
    return ok(stripped)


def query(
    *,
    sql: str,
    project_id: str | None = None,
    location: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    maximum_bytes_billed: int = DEFAULT_MAX_BYTES_BILLED,
    dry_run: bool = False,
) -> Result[dict[str, Any]]:
    checked = validate_query(sql=sql)
    if isinstance(checked, ErrorResult):
        return err(checked.error, blocked=True)
    for name, value, cap in (
        ("max_rows", max_rows, MAX_ROWS_CAP),
        ("maximum_bytes_billed", maximum_bytes_billed, MAX_BYTES_BILLED_CAP),
    ):
        out_of_range = _in_range(name=name, value=value, cap=cap)
        if out_of_range:
            return out_of_range
    global_flags: list[str] = []
    if project_id is not None:
        if not _PROJECT_RE.fullmatch(project_id):
            return err(f"project_id {project_id!r} is not a valid GCP project id.")
        global_flags.append(f"--project_id={project_id}")
    if location is not None:
        if not _LOCATION_RE.fullmatch(location):
            return err(f"location {location!r} is not a valid BigQuery location.")
        global_flags.append(f"--location={location}")
    args = [
        "query",
        "--nouse_legacy_sql",
        f"--max_rows={max_rows}",
        f"--maximum_bytes_billed={maximum_bytes_billed}",
        f"--job_timeout_ms={BQ_TIMEOUT_SECONDS * 1000}",
    ]
    if dry_run:
        args.append("--dry_run")
    result = run_bq(global_flags=global_flags, args=[*args, "--", checked.value])
    if isinstance(result, ErrorResult):
        return result
    if dry_run:
        return ok({"dry_run": True, "job": result.value})
    if not isinstance(result.value, list):
        return ok(
            {
                "rows": [],
                "row_count": 0,
                "max_rows": max_rows,
                "truncated": False,
                "raw": result.value,
            }
        )
    return ok(
        {
            "rows": result.value,
            "row_count": len(result.value),
            "max_rows": max_rows,
            "truncated": len(result.value) >= max_rows,
        }
    )


def datasets(*, project_id: str, max_results: int = DEFAULT_MAX_RESULTS) -> Result[dict[str, Any]]:
    if not _PROJECT_RE.fullmatch(project_id):
        return err(f"project_id {project_id!r} is not a valid GCP project id.")
    out_of_range = _in_range(name="max_results", value=max_results, cap=MAX_RESULTS_CAP)
    if out_of_range:
        return out_of_range
    result = run_bq(
        global_flags=[f"--project_id={project_id}"],
        args=["ls", f"--max_results={max_results}"],
    )
    if isinstance(result, ErrorResult):
        return result
    return ok({"project_id": project_id, "datasets": result.value})


def tables(*, dataset: str, max_results: int = DEFAULT_MAX_RESULTS) -> Result[dict[str, Any]]:
    ref = dataset_ref(dataset=dataset)
    if isinstance(ref, ErrorResult):
        return ref
    out_of_range = _in_range(name="max_results", value=max_results, cap=MAX_RESULTS_CAP)
    if out_of_range:
        return out_of_range
    result = run_bq(global_flags=[], args=["ls", f"--max_results={max_results}", ref.value])
    if isinstance(result, ErrorResult):
        return result
    return ok({"dataset": dataset, "tables": result.value})


def schema(*, table: str) -> Result[dict[str, Any]]:
    ref = table_ref(table=table)
    if isinstance(ref, ErrorResult):
        return ref
    result = run_bq(global_flags=[], args=["show", "--schema", ref.value])
    if isinstance(result, ErrorResult):
        return result
    return ok({"table": table, "schema": result.value})
