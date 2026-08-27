# Performance Baselines

Documented performance metrics for regression tracking.

## CLI Startup Time

**Target:** < 200ms for `dev10x --help`

**Baseline (2026-04-14):** ~40ms via `uv run dev10x --help`

**Architecture:** Click LazyGroup pattern (`src/dev10x/cli.py`)
defers all subcommand imports until invocation. Only `click`,
`importlib`, and `typing` are loaded at startup.

**Hot imports (from `-X importtime`):**

| Import | Self (us) | Cumulative (us) |
|--------|-----------|-----------------|
| `click.core` | 942 | 10,356 |
| `inspect` | 1,152 | 5,522 |
| `typing` | 1,162 | 2,608 |
| `ast` | 794 | 2,640 |
| `site` | 673 | 2,092 |

These are click framework and Python stdlib — not optimizable
without replacing the framework. Current lazy loading covers
all dev10x subcommands.

## CI Gate (GH-432)

The benchmark suite is wired into CI as a backpressure gate.
`.github/workflows/pytest-bench.yml` runs `tests/benchmarks/` with
`pytest-benchmark` on every PR, comparing each run against a cached
baseline. The job **fails on a mean regression greater than 20%**
via `--benchmark-compare-fail=mean:20%`, so a perf regression in
hook latency or CLI startup blocks merge rather than shipping
undetected.

Per-run artefacts under `.benchmarks/` are git-ignored. To inspect
a regression locally, run the benchmark tests and compare against
the stored baseline before pushing.

### CI enforces, local warns (GH-1080)

`tests/benchmarks/test_startup_time.py` gates hook startup against
`tests/fixtures/startup_baseline.json`. Those baselines were recorded
on the CI runner, and developer hardware varies enough that they are
unreachable on some machines — one machine measured ~135 ms against a
37 ms baseline, with a clean `origin/develop` checkout failing
identically. Three permanently-red tests teach everyone to read a red
`bench` as "the baselines again", which is exactly the state a real
regression slips through.

So a timing breach **fails in CI and warns locally**:

| Context | Behaviour | Trigger |
|---------|-----------|---------|
| CI | `pytest.fail` | `CI` env var set (GitHub Actions sets it) |
| Local | `UserWarning` | neither flag set |
| Local, opt-in | `pytest.fail` | `DEV10X_BENCH_STRICT=1` |

Use `DEV10X_BENCH_STRICT=1` when deliberately profiling an
import-chain change and you want the gate to bite on your own box.

**This does not weaken the gate** — the CI job with
`--benchmark-compare-fail=mean:20%` was already the authority; the
committed baselines were attempting the same job a second time against
uncontrolled hardware. If a *CI* baseline goes stale (the runner image
changes), re-record it rather than widening `REGRESSION_FACTOR`.

## Monitoring

Run `time uv run dev10x --help` after dependency changes.
If startup exceeds 200ms, profile with:
```bash
uv run python -X importtime -c "from dev10x.cli import cli" \
  2>&1 | sort -t: -k2 -n | tail -20
```

## Validator Lazy Import Behavior (GH-82)

The ValidatorRegistry defers importing validator modules until
`registry.active()` is called, avoiding the import cost of all
validators on every hook invocation.

**Trade-off**: Metadata assertion errors (rule_id drift, profile
mismatch) surface at hook-run time (when validators are instantiated),
not at startup.

**Monitor**: If hook latency increases during PreToolUse or PermissionDenied
invocations, profile with `HOOK_DEBUG=1 dev10x validate-bash echo hi` and
compare against prior measurements. Lazy imports reduce amortized cost per
hook invocation; eager loading of all validator modules would regress
initialization time across all PreToolUse events.

**If regression**: Evaluate eager-loading validator metadata only (specs
loaded at startup for assertion checks, module imports deferred until
`ValidatorChain.run()`).
