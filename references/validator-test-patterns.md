# Validator Test Patterns

Patterns for writing comprehensive tests for `src/dev10x/validators/*.py`.

## Structure

1. **Parametrized positive tests**: Commands that should block
2. **Parametrized false-positive tests**: Strings containing the marker
   but not as a command (should allow)
3. **Discrete edge-case tests**: Malformed input, empty input, env prefix
   only (should allow or return gracefully)

## Positive Cases (Should Block)

```python
@pytest.mark.parametrize("command", [
    "mcp__plugin_Dev10x_cli__mktmp",
    "mcp__plugin_Dev10x_cli__mktmp namespace=git",
    "FOO=bar mcp__plugin_Dev10x_cli__pr_get pr_number=1",
])
def test_blocks_mcp_tool_as_command(validator, command):
    result = validator.validate(inp=_make_input(command=command))
    assert result is not None
    assert "mcp-tools" in result.message
```

**Guidelines**:
- 3+ parametrized cases covering different argument styles
- Verify error message contains the rule ID or descriptive text
- Test with and without env-prefix forms

## False Positive Cases (Should Allow)

```python
@pytest.mark.parametrize("command", [
    "grep mcp__plugin tests/",        # substring in args
    'echo "mcp__foo__bar"',           # string literal
    "git commit -m 'mcp__name'",      # commit message
])
def test_allows_mcp_substring_in_args(validator, command):
    assert validator.validate(inp=_make_input(command=command)) is None
```

**Guidelines**:
- 3+ parametrized cases testing the marker in safe contexts
- Cover string literals, comments, arguments, commit messages
- Verify no false positives that would break normal workflows

## Edge Cases (Discrete Tests)

```python
def test_unbalanced_quotes_returns_none(validator):
    assert validator.validate(inp=_make_input(command='echo "unbalanced')) is None

def test_empty_command_returns_none(validator):
    assert validator.validate(inp=_make_input(command="")) is None

def test_should_run_gates_on_marker(validator):
    assert validator.should_run(inp=_make_input(command="mcp__...")) is True
    assert validator.should_run(inp=_make_input(command="git status")) is False
```

**Guidelines**:
- 2+ edge-case tests covering graceful handling
- Test malformed input (unbalanced quotes, empty commands)
- Verify `should_run()` gate prevents expensive validation on irrelevant commands
- Return `None` (allow) for malformed input, never crash

## Profile Filtering Test

If the validator has non-trivial scope (affects multiple profiles or depends
on a profile tier), add an integration test:

```python
def test_mcp_prefix_is_standard_tier():
    """Verify validator is registered at standard profile."""
    from dev10x.validators import ValidatorRegistry
    registry = ValidatorRegistry()
    active = registry.active(profile="standard")
    assert any("McpPrefixValidator" in type(v).__name__ for v in active)
```

## Coverage Targets

- ≥3 positive cases (different argument styles)
- ≥3 false positive cases (marker in different contexts)
- ≥2 edge cases (malformed/empty/env-only)
- Profile filtering test if rule has non-trivial scope or tier-dependent behavior

## Benefits

- **Parametrization**: DRY, easy to add new test cases
- **False positives**: Catches over-aggressive matching
- **Edge cases**: Handles malformed input gracefully
- **Coverage**: Exercises both `should_run()` and `validate()` phases
