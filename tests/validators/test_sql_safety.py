"""Tests for SqlSafetyValidator."""

from __future__ import annotations

import pytest

from dev10x.core.validators.sql_safety import SqlSafetyValidator
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

    @pytest.mark.parametrize(
        "command",
        [
            "dropdb app",
            "timeout 9 createdb x",
            "pg_restore -l d",
            'd""ropdb app',
            "dr\\opdb app",
            "'drop'db app",
        ],
    )
    def test_should_run_for_postgres_client_binaries(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        assert validator.should_run(inp=_make_input(command=command)) is True


class TestPostgresWriteBinaries:
    """GH-1732: the deny is on effect, so the client binaries that write
    a database are denied like the SQL that would do the same."""

    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "dropdb app",
            "createdb scratch",
            "dropuser reporter",
            "createuser -s intruder",
            "vacuumdb --all",
            "reindexdb app",
            "clusterdb app",
            "/usr/lib/postgresql/16/bin/dropdb app",
            "PGHOST=db dropdb app",
            "env PGPASSWORD=x dropdb app",
            "timeout 30 createdb scratch",
            "nice -n 5 dropuser reporter",
            "cd /tmp && dropdb app",
            "echo go | dropdb app",
            "docker exec pg dropdb app",
            "op run -- createdb scratch",
            "pg_restore -d app dump.bin",
            "pg_restore --dbname=app dump.bin",
            "pg_restore --clean -d app dump.bin",
            "pg_restore -dapp dump.bin",
            "pg_restore --db=app dump.bin",
            "pg_restore --dbn app dump.bin",
            'd""ropdb app',
            "dr\\opdb app",
            "'drop'db app",
            "echo x;dropdb app",
            "true & dropdb app",
            "true &dropdb app",
            "echo x\ndropdb app",
            "(dropdb app)",
            "{ dropdb app; }",
            "echo $(dropdb app)",
            "echo `createdb app`",
            "if true; then dropdb app; fi",
            "dropdb app # it's gone",
            "FOO=1 createdb 'unterminated",
            "sudo -u postgres dropdb app",
            "sudo -u postgres; dropdb app",
            "echo '>' & dropdb app",
            "echo 'a'& dropdb app",
            "kubectl exec mypod -n prod -- dropdb app",
            "ssh db01 -t dropdb app",
            "docker run --rm postgres:16 dropdb -h h app",
            "docker compose exec db dropdb app",
            "docker --context prod exec c dropdb app",
            "su postgres -c'dropdb app'",
            "su -lc 'dropdb app' postgres",
            "s''sh h 'dropdb app'",
            "sudo -u postgres dropdb app # don't",
            "find . -exec echo {} \\; -exec dropdb app {} \\;",
            "doas -u postgres createdb app",
            "su postgres -c 'dropdb app'",
            "echo app | xargs dropdb",
            "ssh db-host 'dropdb app'",
            "kubectl exec pg-0 -- dropdb app",
            "find . -name x -exec dropuser {} ;",
            "pgbench -i app",
            "pgbench -c 10 app",
        ],
    )
    def test_denies_database_writing_binaries(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "GH-1732" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "pg_dump --schema-only app",
            "pg_dumpall --globals-only",
            "pg_restore -l dump.bin",
            "pg_restore --clean -f out.sql dump.bin",
            "pg_restore --data-only -f out.sql dump.bin",
            "pg_restore --d -f out.sql dump.bin",
            "rg -n dropdb src/",
            "echo dropdb",
            "git log --grep=createdb",
            "pg_isready -h db",
            "rg 'dropdb' src/ ; echo done",
            "command -v dropdb",
            "command -V createdb",
            "sudo -u postgres pg_dump app",
            "sudo ls /var/lib && echo dropdb",
            "kubectl exec pg-0 -- pg_restore -l dump.bin",
            'echo "it\'s the dropdb docs"',
            "grep -n createdb 'unterminated",
        ],
    )
    def test_allows_reads_and_mentions(self, validator: SqlSafetyValidator, command: str) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None


class TestBigQueryReadOnly:
    """GH-1633: `bq query` gets the same read-only contract as db.sh."""

    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "bq query --nouse_legacy_sql 'DELETE FROM ds.t WHERE true'",
            "bq query --nouse_legacy_sql 'UPDATE ds.t SET a = 1 WHERE true'",
            "bq query 'INSERT INTO ds.t VALUES (1)'",
            "bq query 'MERGE ds.t USING ds.s ON false WHEN NOT MATCHED THEN INSERT ROW'",
            "bq query 'DROP TABLE ds.t'",
            "bq query 'TRUNCATE TABLE ds.t'",
            "bq query 'CALL ds.proc()'",
            "bq query 'SELECT 1; DELETE FROM ds.t WHERE true'",
            "bq query \"EXPORT DATA OPTIONS(uri='gs://b/*') AS SELECT 1\"",
            "bq query \"WITH s AS (SELECT 1) EXPORT DATA OPTIONS(uri='gs://b/*') AS SELECT 1\"",
            "bq query 'SELECT 1 FROM ds.t WHERE x IN (SELECT 1) MERGE'",
            "bq query 'WITH x AS (SELECT 1) SELECT * FROM x' --destination_table=ds.t",
            "bq query --replace 'SELECT 1'",
            "bq query --append_table 'SELECT 1'",
            "bq query --schedule='every 24 hours' 'SELECT 1'",
            "bq query --nouse_legacy_sql < cleanup.sql",
            "cat cleanup.sql | bq query --nouse_legacy_sql",
            "cd /tmp && bq query 'DELETE FROM ds.t WHERE true'",
            "/usr/bin/bq --project_id=p query 'DELETE FROM ds.t WHERE true'",
            "bq query --format json 'DELETE FROM ds.t WHERE true'",
            "bq query -destination_table=ds.t 'SELECT 1'",
            "bq query -replace -destination_table=ds.t 'SELECT 1'",
            "bq query -append_table 'SELECT 1'",
            "bq query -format json 'DELETE FROM ds.t WHERE true'",
            "CLOUDSDK_CORE_PROJECT=p bq query 'DELETE FROM ds.t WHERE true'",
            "timeout 60 bq query 'DELETE FROM ds.t WHERE true'",
            "env bq query 'MERGE ds.t USING ds.s ON false WHEN MATCHED THEN DELETE'",
        ],
    )
    def test_blocks_bigquery_writes(self, validator: SqlSafetyValidator, command: str) -> None:
        inp = _make_input(command=command)

        assert validator.should_run(inp=inp) is True
        assert validator.validate(inp=inp) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "bq query --nouse_legacy_sql 'SELECT count(*) FROM `p.ds.t`'",
            "bq query --format json --max_rows 10 'SELECT 1'",
            "bq query -n 5 'WITH x AS (SELECT 1) SELECT * FROM x'",
            "bq query --format=prettyjson --dry_run 'SELECT 1'",
            "bq query 'SELECT 1' > out.json",
            "bq query 'SELECT 1' 2>/dev/null",
            "bq query -format json -max_rows 5 'SELECT 1'",
            "bq query -format=json 'SELECT 1'",
            "timeout 60 bq query 'SELECT 1'",
            "env",
            "bq ls ds",
            "bq show --schema ds.t",
            "echo bq is great",
        ],
    )
    def test_allows_read_only_bigquery(self, validator: SqlSafetyValidator, command: str) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None

    @pytest.mark.parametrize("command", ["bq query < q.sql", "bq query <q.sql"])
    def test_stdin_query_is_named_in_the_message(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "stdin" in result.message

    @pytest.mark.parametrize(
        "command",
        ["bq query 'SELECT 1", "x;bq query --replace 'SELECT 1", "sudo bq query 'SELECT"],
    )
    def test_unparseable_bq_query_fails_closed(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        """GH-1773: skipping an untokenizable unit was the evasion."""
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "could not be tokenized" in result.message

    def test_unparseable_non_query_bq_is_left_alone(self, validator: SqlSafetyValidator) -> None:
        assert validator.validate(inp=_make_input(command="bq ls 'ds")) is None

    @pytest.mark.parametrize(
        "command",
        [
            "x;bq query --destination_table=t 'SELECT 1'",
            "true & bq query --replace 'SELECT 1'",
            "true\nbq query --replace 'SELECT 1'",
            "(bq query --replace 'SELECT 1')",
            "echo $(bq query --replace 'SELECT 1')",
            "sudo -u svc bq query --replace 'SELECT 1'",
            "ssh host bq query --replace \"'SELECT 1'\"",
            "b''q query --destination_table=t 'SELECT 1'",
            "b\\q query --replace 'SELECT 1'",
        ],
    )
    def test_blocks_chained_and_runner_wrapped_writes(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        """GH-1773/GH-1774: every operator and runner reaches the bq check."""
        assert validator.validate(inp=_make_input(command=command)) is not None

    def test_allows_a_chained_read(self, validator: SqlSafetyValidator) -> None:
        command = "cd /tmp;bq query 'SELECT 1' 2>&1 | head"

        assert validator.validate(inp=_make_input(command=command)) is None

    def test_should_not_run_for_a_word_starting_with_bq(
        self, validator: SqlSafetyValidator
    ) -> None:
        assert validator.should_run(inp=_make_input(command="ls bqfiles")) is False

    def test_word_ending_in_bq_wakes_the_probe_but_blocks_nothing(
        self, validator: SqlSafetyValidator
    ) -> None:
        """GH-1798: no leading boundary, so `-c'bq …'` is not missed."""
        inp = _make_input(command="ls abq-files")

        assert validator.should_run(inp=inp) is True
        assert validator.validate(inp=inp) is None

    @pytest.mark.parametrize(
        "command",
        [
            "su u -c'bq query --replace \"SELECT 1\"'",
            "bq query 'SELECT 1' >| out.txt --destination_table=t",
            "bq query 3> err.log --replace 'SELECT 1'",
        ],
    )
    def test_blocks_writes_past_quoting_and_redirects(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        assert validator.validate(inp=_make_input(command=command)) is not None

    @pytest.mark.parametrize(
        "command",
        [
            "bq query 'SELECT 1' >| out.txt",
            "bq query 'SELECT 1' &>> log",
            "bq query 'SELECT 1' 3>&1",
        ],
    )
    def test_redirect_target_is_not_read_as_sql(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None


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


class TestPsqlAsSearchOperand:
    """A `psql` search pattern is not a psql call (GH-1790)."""

    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "rg -n -i 'psql' projects.yaml baseline-permissions.yaml",
            "grep -rn psql src/",
            "echo psql",
            "timeout 5 rg psql docs/",
            "rg -n psql src | head -5",
        ],
    )
    def test_search_pattern_is_not_blocked(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None

    @pytest.mark.parametrize(
        "command",
        [
            "rg psql src && psql -d mydb",
            "rg psql src; psql -d mydb",
            "rg psql src | psql -d mydb",
            "rg --pre psql pattern src",
            "grep psql x & psql -d mydb",
            "sudo -u postgres psql",
            "cat <( psql -d mydb -c 'DELETE FROM t' )",
            "grep x <( psql -d mydb )",
            "echo x > >( psql -d mydb )",
            "ag --pager psql pattern src",
        ],
    )
    def test_psql_in_command_position_is_still_blocked(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "Direct psql calls" in result.message


class TestPsqlCommandPosition:
    """DX004 judges the program each unit runs, not every word (GH-1809)."""

    @pytest.fixture()
    def validator(self) -> SqlSafetyValidator:
        return SqlSafetyValidator()

    @pytest.mark.parametrize(
        "command",
        [
            "watch psql -c 'DROP TABLE t'",
            "watch -n 5 psql -d mydb",
            "setsid psql -d mydb",
            "eval psql -d mydb",
            "eval 'psql -d mydb'",
            "flock /tmp/lock psql -d mydb",
            "flock /tmp/lock -c 'psql -d mydb'",
            "env -S 'psql -d mydb'",
            "nsenter -t 1 psql -d mydb",
            "xargs psql -d mydb",
            "ssh db01 psql -d mydb",
            "ssh db01 'psql -d mydb -c \"DELETE FROM t\"'",
            "su postgres -c 'psql -d mydb'",
            "find . -name x -exec psql -f {} \\;",
            "kubectl exec pod -- psql -d mydb",
            "docker run --rm img psql -d mydb",
            "sudo docker exec c psql -d mydb",
            "/usr/bin/psql -d mydb",
            "p''sql -d mydb",
            "echo $(psql -d mydb -c 'SELECT 1')",
            "echo `psql -d mydb`",
            "rg --pre=psql pattern src",
            "rg --hostname-bin psql pattern src",
            "ack --pager=psql pattern src",
            "psql -d mydb -c 'SELECT 1",
            "timeout 5 'psql -d mydb",
            "man -Ppsql psql",
        ],
    )
    def test_blocks_psql_run_by_a_runner(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "Direct psql calls" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "strace psql -d mydb",
            "strace -f -o trace.log psql -d mydb",
            "ltrace -o out psql -d mydb",
            "valgrind --tool=memcheck psql -d mydb",
            "gdb --args psql -d mydb",
            "gdb -ex run --args /usr/bin/psql -d mydb",
            "ionice -c3 psql -d mydb",
            "ionice -c 2 -n 7 psql -d mydb",
            "taskset 0x1 psql -d mydb",
            "taskset -c 0,1 psql -d mydb",
            "chrt 10 psql -d mydb",
            "chrt -f 10 psql -d mydb",
            "unbuffer psql -d mydb",
            "rlwrap psql -d mydb",
            "rlwrap -f words psql -d mydb",
            "systemd-run --user psql -d mydb",
            "systemd-run -p MemoryMax=1G --unit job psql -d mydb",
            "firejail --noprofile psql -d mydb",
            "script -c 'psql -d mydb' /dev/null",
            "script -q --command='psql -d mydb' out.log",
            "tmux new-session 'psql -d mydb'",
            "tmux new -d -s db psql -d mydb",
            "tmux send-keys -t db 'psql -d mydb -c \"DROP TABLE t\"' Enter",
            "screen psql -d mydb",
            "screen -dmS db psql -d mydb",
            "parallel psql -d {} ::: a b",
            "parallel -j 2 ::: 'psql -d a' 'psql -d b'",
            "nohup some-unknown-runner psql -d mydb",
            "some-unknown-runner --flag /usr/lib/postgresql/bin/psql",
        ],
    )
    def test_blocks_psql_run_by_an_exec_style_runner(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        """GH-1998: each runner is unwrapped; an unknown one fails closed."""
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "Direct psql calls" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "bash <<'EOF'\npsql -c \"DROP TABLE x\"\nEOF",
            "bash <<< psql",
            "source <(echo psql -c 'DROP TABLE x')",
            "eval $(echo psql -c x)",
            "git submodule foreach psql -c x",
            "git rebase -x psql",
            "git bisect run psql",
            "git difftool -x psql",
            "git filter-branch --tree-filter psql",
            'rlwrap -m psql -c "DROP TABLE x"',
            "strace --output git psql",
            "systemd-run --working-directory git psql",
            "./git psql",
            "/tmp/x/cat psql",
        ],
    )
    def test_blocks_review_bypasses(self, validator: SqlSafetyValidator, command: str) -> None:
        """PR #1999 review: develop blocks each of these, so the branch must too."""
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "Direct psql calls" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "git log --grep psql",
            "which psql",
            "man psql",
            "command -v psql",
            "ls /usr/bin/psql",
            "rg --pre-glob '*.gz' psql src",
            "rg psql src; > out.txt",
        ],
    )
    def test_word_rule_still_blocks_what_develop_blocks(
        self, validator: SqlSafetyValidator, command: str
    ) -> None:
        """The walk only adds blocks; the word rule keeps develop's verdicts."""
        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "Direct psql calls" in result.message

    @pytest.mark.parametrize(
        "command",
        [
            "rg psql src",
            "echo psql",
            "/usr/bin/rg psql src",
            "/bin/echo psql",
            'rg psql "src',
            "echo $(echo psql) $(echo psql) $( )",
        ],
    )
    def test_allows_psql_as_an_operand(self, validator: SqlSafetyValidator, command: str) -> None:
        assert validator.validate(inp=_make_input(command=command)) is None

    def test_wrapped_psql_inside_a_substitution_is_checked_for_writes(
        self, validator: SqlSafetyValidator
    ) -> None:
        command = "echo $(docker exec c psql -c 'DROP TABLE t')"

        result = validator.validate(inp=_make_input(command=command))

        assert result is not None
        assert "DROP" in result.message


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
