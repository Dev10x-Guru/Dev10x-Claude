# ADR-0033: Disposable test databases get a fixed-verb wrapper; DX004 stays absolute

- **Status:** Proposed (awaiting supervisor decision; recommendation
  below is Option A)
- **Date:** 2026-09-27
- **Supersedes:** none
- **Amends:** none
- **Related:** GH-1324, GH-1100 (E25), GH-1034, GH-604, GH-474,
  GH-1215, GH-1260

## Context

DX004 (`sql-safety`, `ProfileTier.MINIMAL`,
`validators/sql_safety.py:296-300`) enforces "no database writes, ever".
It has no notion of *what* it is pointed at. A `DROP DATABASE` against a
disposable local test database is refused exactly as it would be against
production. An attended session can hand the SQL to a human. An
unattended one stalls, because no action the agent can take satisfies
the gate (GH-1100 E25, extracted to GH-1324).

GH-1324 rules two responses out in advance. Loosening the keyword ban is
trivially evaded. A skip flag becomes the default path.

### How DX004 decides today

- `should_run` fires only when the command string contains `db.sh`,
  `psql`, `psycopg2`, `postgres://` or `postgresql://` (`:302-310`).
- `_validate_sql` (`:263-293`) accepts one statement starting with
  `SELECT`/`WITH`/`EXPLAIN`/`SHOW`, and rejects any hit on
  `BLOCKED_KEYWORDS` (`:25-40`). The list includes `DROP`, `CREATE` and,
  since GH-1034 (`ec12c2fd`), `pg_terminate_backend`. A teardown script
  reaches for that function when a `DROP` fails on an open connection.
- `docker exec … psql` and `op run -- psql` are exempt from the
  direct-psql ban (GH-474, `:75-93`), but their SQL is still checked
  (GH-1034, `:178-192`).
- The `psql-write` rule in `validators/command-skill-map.yaml:562-586`
  duplicates the block at the redirect layer.
- `db.sh` sets `default_transaction_read_only = on`
  (`skills/db-psql/scripts/db.sh:191, 197`), and `databases.yaml` has no
  field that says whether a target is disposable
  (`skills/db-psql/scripts/parse-databases.py:51-60`).

### How DX014 differs

DX014 (`validators/sensitivity_target.py`) classifies the **target**:
SECRET / CREDENTIAL / PII / INFRA (`domain/sensitivity.py:28-59`). It
emits `ask`, not `deny`, and a user catalog can downgrade that `ask` to
`allow` (`ExceptionEffect`, `:451-455`). It runs **after** DX004 in the
chain (`validators/__init__.py:64` vs `:125`), and a DX004 deny
short-circuits it. So the sensitivity catalog never sees a command DX004
has refused.

### A finding: the deny is absolute on spelling, not on effect

`rg dropdb|createdb` across `src/`, `skills/` and the catalog finds no
rule naming either binary, and DX004's `should_run` does not match them.
`dropdb app_test` is therefore not a DX004 decision at all. It reaches
Claude Code's default prompt. This is GH-1260's principle again: rules
match a command string, never an effect. It does not change the
recommendation below. It does mean "DX004 survives either way" has to
include closing this gap, or the survival is nominal.

## Options

### Option A: a narrow sanctioned wrapper with a fixed verb set

Add an MCP tool on the existing `db` server (`mcp/server_db.py`, which
today registers only `query`), for example `test_db(action, database)`.

- **Verbs:** `create`, `drop`, `recreate` (drop, then create). No SQL
  parameter, ever. `drop` uses `DROP DATABASE … WITH (FORCE)`
  (PostgreSQL 13+) inside the tool, so no caller needs
  `pg_terminate_backend`.
- **Name derivation:** the tool resolves a *declared* target, never a
  free string. `databases.yaml` gains `disposable: true` plus a
  `test_name:` on an entry. `database` names that entry's alias, and
  the tool reads the physical name from config.
- **Ineligible, and refused by name**, if any of these hold:
  1. The entry lacks `disposable: true`.
  2. The DSN host is not loopback, not a unix socket, and not a
     `docker compose` service of the current repo.
  3. The physical name does not match `test_*` / `*_test`.
  4. The name equals the database of any non-disposable entry in the
     same file.
  5. The DSN's user is the read-only user a `db.sh` entry uses.
- DX004 and `psql-write` are untouched. The wrapper is a different
  tool, not an exception to theirs.

**+** The deny stays absolute: nothing downgrades a safety-tier verdict.
**+** It is auditable: a fixed verb set, and eligibility decided from
config the supervisor owns. **+** It follows the `pr_ready` / `update_pr`
shape. When the sanctioned route exists, the raw route can stay blocked.
**−** It is a new write tool, and whether to seed it is a real question
(see Open Questions). **−** It is PostgreSQL-only at first.

### Option B: let the sensitivity-exceptions catalog downgrade a DX004 deny

Teach DX004 to consult `~/.config/Dev10x/sensitivity-exceptions.yaml`
and turn its `deny` into `ask` or `allow` for a matching target.

**−** It changes what the MINIMAL tier means. Today a safety-tier deny
has no config escape (`.claude/rules/hook-patterns.md` § DX014: "genuine
destructive writes are still hard-denied"). **−** It couples two
validators the chain deliberately orders. **−** The catalog is
user-owned, synced and unreviewed. A malformed entry that matched too
broadly would lift a production write guard. GH-1324 calls this "a
materially bigger trust decision", and it is.

### Option C: add a target axis inside DX004 that emits `ask` for local targets

**+** Symmetric with DX014. **−** An `ask` still stalls an unattended
run, which is the failure GH-1324 exists to fix. **−** It classifies from
the command string. `psql -h localhost` says nothing about which cluster
a port-forward points at.

### Option D: status quo, and park the task

The agent prints the SQL, tags the task awaiting, and the supervisor
runs it in the morning.

**+** No new surface. **−** Every unattended run that needs a fresh
test DB loses the night. That is the observed cost in E25.

## Recommendation

**Option A.** It is the only option that lets unattended work complete
without changing what a safety-tier deny means. Option B moves the
trust boundary into an unreviewed user file. Option C does not unblock
unattended runs. Option D accepts the cost the issue was filed about.
Keeping eligibility in declared config, rather than inferring it from a
command string, also sidesteps the string-matching limit the `dropdb`
finding shows.

The acceptance of GH-1324 asks for three things:

- **The exact verb set:** `create` / `drop` / `recreate`.
- **Name derivation:** a declared `disposable` entry's `test_name`.
- **Ineligibility:** criteria 1–5 above.

DX004's blanket deny is unchanged. Separately, DX004 or the redirect map
should learn to treat `dropdb` / `createdb` / `pg_restore --clean` as
writes, so that "absolute" holds on effect.

## Open Questions for the supervisor

1. **Seed the wrapper or keep it prompting?** Under GH-1215, a write
   whose raw form is blocked should be seeded, or the sanctioned route
   prompts while the unsanctioned one is denied. Under
   `WRITE_TOOLS_NOT_SEEDED`, destructive writes keep prompting. This ADR
   leans towards seeding, because eligibility criteria 1–5 are the gate.
   An unattended run gains nothing from a wrapper that prompts.
2. **Is the eligibility config per repo?** `databases.yaml` is global
   today (`~/.config/Dev10x/databases.yaml`). A per-repo `disposable`
   entry could instead live in a git-tracked project file, so teammates
   share it.
3. **Is loopback enough?** A `kubectl port-forward` makes a remote
   database look local. Should criterion 2 also require that the port
   belongs to a container of this repo's compose project?
4. **Close the `dropdb` / `createdb` gap first, as a separate
   issue?** This ADR recommends yes, independently of the wrapper.
5. **MySQL / SQLite:** out of scope for v1?

## Consequences (if Option A is accepted)

- The `db` server gains a second tool. `.claude/rules/mcp-tools.md`
  needs a table row and a parameter-shape row, and the tool needs either
  a `base_permissions` entry or a `WRITE_TOOLS_NOT_SEEDED` entry (the
  three-edit rule, GH-1153).
- `databases.yaml.example` documents `disposable:` and `test_name:`.
- DX004's messages can name the wrapper as the route for test-DB
  lifecycle, the way `DIRECT_PSQL_MSG` names `db.sh`
  (`sql_safety.py:63-68`).

## References

- `src/dev10x/validators/sql_safety.py:23-45, 75-93, 178-192, 263-310`
- `src/dev10x/validators/command-skill-map.yaml:562-586, 669-680`
- `src/dev10x/validators/sensitivity_target.py`;
  `src/dev10x/domain/sensitivity.py:28-59, 451-484`
- `src/dev10x/validators/__init__.py:64, 125`: chain order
- `src/dev10x/mcp/server_db.py:17-33`
- `skills/db-psql/scripts/db.sh:191, 197`;
  `skills/db-psql/scripts/parse-databases.py:51-60`;
  `skills/db-psql/databases.yaml.example`
- `.claude/rules/hook-patterns.md` § DX014
- [GH-1324](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1324),
  [GH-1034](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/1034)
