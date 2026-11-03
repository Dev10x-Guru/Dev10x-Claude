# ADR-0033: How unattended work recreates a disposable test database while DX004 stays absolute

- **Status:** Proposed (awaiting supervisor decision)
- **Date:** 2026-09-27; refreshed 2026-11-03 against `a3ea3142`
- **Supersedes:** none
- **Amends:** none
- **Related:** GH-1324, GH-1100 (E25), GH-1732, GH-1633, GH-1034,
  GH-1215, GH-1261, GH-1493, ADR-0034

## Context

DX004 (`sql-safety`, minimal tier) enforces "no database writes, ever".
It has no notion of *what* it is pointed at, so dropping a disposable
local test database is refused exactly as dropping production would be.
An attended session hands the SQL to a human. An unattended one stalls
(GH-1100 E25, extracted to GH-1324). GH-1324 rules out loosening the
keyword ban and adding a skip flag, and requires DX004's blanket deny to
survive whatever is chosen.

### What changed since the 2026-09-27 draft

- **GH-1732 closed the draft's main finding.** DX004 now denies
  `dropdb`, `createdb` and their sibling binaries (`sql_safety.py:470-484`),
  plus `pg_restore -d`. It looks through `sudo`, `ssh`, `kubectl` and
  `docker` wrappers and catches quoting tricks (`:487-614`). The deny is
  now absolute on effect for every Bash route, not just on spelling.
- **GH-1633** extended DX004 to `bq query`.
- **ADR-0034 Stage B3** moves the database skills to `dev10x-db` but
  keeps the `db` MCP server in core, so tool names survive the split.
  The server still registers only `query` (`src/dev10x/db/mcp/server_db.py:17`).
- **GH-1493** set the precedent for per-repo durable config in
  `friction.yaml` `projects[]`, probing the worktree first and the main
  checkout second.

### A route the first draft missed

`run_tests` passes arbitrary pytest `args` through
(`src/dev10x/coding/runner/__init__.py:155-172`). `run_node_tests`
runs any `package.json` script. Both are seeded
(`projects.d/coding.yaml:56`, `projects.yaml:188`). Test frameworks that
own a test database, such as pytest-django with its `test_` prefix and
`--create-db`, already create and drop it themselves. So for the common
case a sanctioned route exists today, with no Dev10x write tool:
`run_tests(args=["--create-db"])`.

That route has two properties that matter here:

- It is **not checked**. DX004 never sees an MCP tool's subprocess
  (GH-1261), so a `conftest.py` teardown drops whatever the session's
  DSN points at.
- **Nobody is told about it.** All three DX004 deny messages end in
  "print the SQL for the user" (`sql_safety.py:195-198, 523-528, 761-766`),
  and `dev10x:py-test` says nothing about databases.

## Options

### Option A: a fixed-verb `test_db` wrapper on the `db` server

`test_db(action=create|drop|recreate, database=<alias>)`, with no SQL
parameter. `drop` uses `DROP DATABASE … WITH (FORCE)` internally. The
tool is a domain module beside `query` that returns `Result`. It never
goes through `db.sh`, which hard-sets read-only (`db.sh:191, 197`).

**Eligibility, refreshed against current code.** The tool refuses, and
names the reason, unless every check passes:

1. The `databases.yaml` entry is declared `disposable: true` with a
   `test_name:`.
2. That entry came from `~/.config/Dev10x/databases.yaml`. `db.sh`
   discovery also reads plugin marketplace directories (`db.sh:57-87`),
   and a third-party plugin must not be able to declare a database
   disposable.
3. The **resolved** DSN host is loopback, a unix socket, or a compose
   service of this repo. DSNs resolve lazily from env or keyring
   (`db.sh:141-152`), so the check runs at call time.
4. The physical name matches `test_*` / `*_test`, and the resolved
   `(host, port, dbname)` collides with no non-disposable entry.
5. A required `maintenance_dsn` connects as a user that no
   non-disposable entry uses. This replaces the draft's "not the
   read-only user" check, which had nothing to check: read-only is a
   session setting, not a user. `CREATE` and `DROP DATABASE` need a
   maintenance connection anyway.
6. Per-repo enablement: `test_db: {aliases: [...]}` in the repo's
   `friction.yaml` entry (GH-1493 precedent). An agent can then neither
   declare a target disposable nor enable it for the repo it is working
   in, because both files are supervisor-owned.

- **+** It is the only option that adds a target check. It covers cases
  a test runner cannot: migration rehearsal on an empty database,
  seeding a dev database, e2e suites not run by pytest, and recovery
  after a killed run left open connections.
- **+** It fits GH-1215: the raw forms are denied, so the sanctioned
  route belongs in `base_permissions` (`projects.d/db.yaml`).
- **−** It is a seeded destructive write. Its safety is only as good as
  the six checks. Loopback does not prove locality: a
  `kubectl port-forward` passes check 3 unless compose-service matching
  is required.
- **−** It is PostgreSQL 13+ only in v1. Keyring-backed DSNs may be
  editable by the agent if `secret-tool` is allowed [Verify].
- **−** Roughly 200–300 lines of domain code plus tests [Verify:
  estimate, not measured].

### Option E: no new write tool; steer to the test runner

Name `run_tests(args=["--create-db"])` and `run_node_tests(script=…)`
in DX004's three deny messages. Document test-database recreation in
`dev10x:py-test`. A database the runner does not own falls back to
Option D (park the task).

- **+** Zero new surface. "Dev10x has no database write tool" stays
  auditable by grep, and the safety of the test name comes from the
  project's own settings by construction.
- **+** It covers the case GH-1324 describes, a "project-config-derived
  local test database", if E25 was the stale `--reuse-db` shape
  [Verify: the E25 text was not readable during this refresh].
- **−** It covers no database outside a test session, and no Python
  project that resets through make or compose. A "declared command" tool
  for those would be Option A without the checks, or a shell-equivalent
  tool (GH-1261 deny).
- **−** It formalises an unchecked write path. If the session's
  `DATABASE_URL` points at staging, nothing objects.

### Option B: the sensitivity catalog downgrades a DX004 deny

Unchanged from the draft and **not recommended**. It changes what the
minimal tier means, and it puts the trust boundary in an unreviewed user
file.

### Option C: a target axis inside DX004 that emits `ask`

Unchanged and **not recommended**. An `ask` still stalls an unattended
run, and the command string cannot see a port-forward.

### Option D: status quo; park the task

Unchanged. Every unattended run that needs a fresh database loses the
night. That is the E25 cost.

## Ranking

The evaluation ranks **E first, then A on evidence**, with
**low-to-medium** confidence. The decision is the supervisor's.

- E solves the common case today for the cost of three message edits and
  a doc section.
- A's value is the long tail plus the target check. Building a seeded
  destructive tool for a long tail nobody has yet recorded runs ahead of
  the evidence, so E ships now and A follows when a non-runner case is
  recorded.
- **If E25 was not a runner-owned test database**, the ranking flips to
  A. Reading E25 is the one fact that would most change this decision.
- B and C are dominated. D is what E degrades to outside its coverage.

## Open questions

1. **Option A only: seed it or keep it prompting?** Unseeded, it stalls
   unattended runs, which fails GH-1324. Seeded, it rests on checks 1–6.
2. **Option A only: is loopback enough?** Or should check 3 require a
   compose-service match, at the cost of a `docker` dependency per call?
3. **Either option: file the unchecked runner path as its own issue?**
   `run_tests` and `run_node_tests` already write databases where DX004
   cannot see them. Separately, `baseline-permissions.yaml` describes
   `Bash(psql:*)` and `Bash(pg_dump:*)` as read-only. That holds only
   because DX004 holds [Verify: lines 490-497].
4. **MySQL / SQLite:** out of scope for v1 under either option?

## Consequences

- **E:** DX004's three messages name the runner routes, and
  `dev10x:py-test` gains a test-database section. The `db` server keeps
  one tool, and GH-1324 closes with A recorded as the evidence-gated
  follow-up.
- **A:** the `db` server gains a second tool, which needs the three
  GH-1153 edits. `databases.yaml.example` documents `disposable`,
  `test_name` and `maintenance_dsn`. `friction.yaml` gains a `test_db`
  durable key.
- **Both:** DX004's blanket deny and the GH-1732 binary denies are
  untouched.

## References

- `src/dev10x/core/validators/sql_safety.py:46-49, 195-198, 470-614, 761-766`
- `src/dev10x/db/mcp/server_db.py:17-33`; `src/dev10x/db/__init__.py:17`
- `src/dev10x/coding/runner/__init__.py:155-172`;
  `src/dev10x/coding/mcp/runner_tools.py`
- `skills/upgrade-cleanup/projects.d/coding.yaml:56`,
  `projects.d/db.yaml:8`, `projects.yaml:188`
- `src/dev10x/core/skills/permission/enumerate_mcp.py:505-534`
- `skills/db-psql/scripts/db.sh:57-87, 141-152, 191, 197`
- [ADR-0034](0034-staged-plugin-split-restructure-first.md) § Stage B
- [GH-1324](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1324),
  [GH-1732](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1732)
