# Pytest Fixture Composition Patterns

Proven patterns for testing code that depends on multiple system resources
(home directory, temporary working directories, environment variables).

## Nested Context Managers for Isolated State

When testing code with multiple system dependencies, compose fixtures to
patch all dependencies at once without leaking state between tests.

**Pattern:**

```python
@pytest.fixture
def patched_workdir(workdir: Path, fake_home: Path):
    """Redirect default workdir + Path.home() so commands operate in tmp_path."""
    def _workdir() -> Path:
        return workdir
    with (
        patch("dev10x.commands.permission._investigator_workdir", _workdir),
        patch("dev10x.commands.permission.Path.home", return_value=fake_home),
    ):
        yield workdir
```

**Why this works:**
- All patches are scoped to the fixture's context manager lifetime
- Tests using `patched_workdir` automatically get both patches applied
- On fixture cleanup, all patches are reverted (no test-to-test leakage)
- Future tests don't inherit state or side effects from prior tests

**Anti-pattern** (patches exit before test runs):
```python
# ❌ BAD
@pytest.fixture
def workdir():
    with patch(...):
        pass  # Patch exits here, before test runs!
    return Path(...)
```

## Temporary Path Helpers for CLI Testing

When testing Click CLI commands that read/write to temporary directories,
use helper fixtures to create isolated temporary state:

```python
@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    return home
```

Then pass both `fake_home` and `tmp_path` to dependent fixtures so tests
can create multiple isolated directories without conflicts.

**Use case**: CLI commands that write to `~/.claude/` or other user-scoped
paths need a controlled home directory to avoid polluting the developer's
actual home directory.

## Multi-Layer Fixture Composition

For complex test scenarios with 3+ dependencies, build fixtures in layers:

```python
@pytest.fixture
def temp_state(tmp_path: Path):
    """Create temp directory structure."""
    return tmp_path / "state"

@pytest.fixture
def fake_home(temp_state: Path) -> Path:
    """Create isolated home directory within temp_state."""
    home = temp_state / "home"
    home.mkdir(parents=True)
    return home

@pytest.fixture
def patched_env(fake_home: Path):
    """Patch environment to use isolated home."""
    with patch.dict(os.environ, {"HOME": str(fake_home)}):
        yield fake_home
```

This composition allows tests to:
- Use `temp_state` for minimal temp setup
- Use `fake_home` when home directory patching is needed
- Use `patched_env` for full environment isolation

Each fixture has a single responsibility; tests request what they need.

## Parametrized Test Matrix Completeness

When a PR uses `@pytest.mark.parametrize` to test a set of related items,
ensure the test matrix is exhaustive:

1. **Count items in parametrize list** — e.g., `@pytest.mark.parametrize("handler_name", ["detect_tracker", "pr_detect", ...])`
2. **Count items in actual codebase** — grep for all handler names in `servers/cli_server.py`
3. **Flag divergence as WARNING** — suggests incomplete coverage

**Example**: If parametrized test validates "all 19 CWD-sensitive handlers
must invoke use_cwd(cwd)", verify the list includes all 19. Adding new
handlers without updating the parametrize list causes silent regressions.

## Mock Call Signature Verification

When mocking functions and verifying calls, go beyond `call_count`:

```python
# Good: verifies specific arguments
mock_api.assert_called_once()
assert mock_api.call_args.kwargs["as_bot"] is True
assert mock_api.call_args.args[0] == "issue_id"

# Weak: only checks it was called
assert mock_api.called
```

**Checklist**:
- Verify `call_args` contains all required parameters
- Check both positional args (`args`) and keyword args (`kwargs`)
- Test both success and failure scenarios
- Avoid assertions that only check `call_count == 1` without verifying arguments

## Async Handler Error Path Coverage

For async handlers wrapping synchronous operations (GitHub API, git commands):

**Test matrix**:
1. Success path: returncode 0, stdout contains expected output
2. Failure path: returncode != 0, stderr contains error message
3. Empty success: returncode 0, stdout is empty (verify handler doesn't crash)
4. Malformed response: handler can't parse output (graceful error)

**Assertions**:
```python
# Success case
result = await handler(...)
assert isinstance(result, SuccessResult)
assert "expected_field" in result.data

# Error case
result = await handler(...)
assert isinstance(result, ErrorResult)
assert "error_context" in str(result.error)
```

**Common gaps to watch**:
- Error test missing (success-only coverage)
- Error message not validated (just checking `"error" in result`)
- Stderr content lost during error wrapping (context lost)

## Regression Tests for Orchestration Algorithms

When SKILL.md documents a routing algorithm, write a test that replicates it
and validates all canonical examples.

**Pattern**: Extract examples from SKILL.md, replicate the algorithm in test
code, parametrize over examples, assert each produces documented behavior.

**Why this works**: Keeps implementation and docs in sync; renames/removals
surface immediately; reviewers verify completeness against documentation.

**Common gap**: Algorithm documented but no test ensures implementation
matches. Refactors diverge from docs silently.

## Schema Validation for Data-Driven Configuration

When a feature is driven by YAML/JSON configuration, write parametrized tests
that verify all entries satisfy the schema.

**Pattern**: Load configuration, extract all entry IDs, parametrize a test
over them, assert required fields present and values valid.

**Example**:
```python
@pytest.mark.parametrize("rule_name", _all_rule_ids())
def test_rule_has_required_fields(self, rule_name: str) -> None:
    rule = self.rules[rule_name]
    assert "name" in rule and "compensations" in rule
```

**Why this works**: Catches silent schema divergence early; configuration-
driven systems need completeness checks; new entries get verified in review.

**Common gap**: New entries added without schema validation. Reviewers lack
guidance to request schema tests for data-driven features.
