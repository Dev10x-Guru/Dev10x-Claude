# Shell Script Testing Patterns

Proven patterns for testing shell scripts, especially those with functions
or complex logic. Established by PR #663 (bash 3.2 compatibility fix).

## Subprocess Execution Testing

When testing shell scripts that define functions, validate runtime behavior
by executing the actual script in an isolated subprocess rather than
parsing syntax.

**Pattern:**

```python
import subprocess
from pathlib import Path

script_path = Path(__file__).parent / "../../bin/require-tool.sh"

def test_function_behavior(self) -> None:
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}" && function_name arg'],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "expected output" in result.stdout
```

**Why**:
- Validates runtime behavior, not just syntax
- Isolated subprocess prevents state leakage between tests
- Timeout prevents infinite loops from infinite recursion or bad logic
- Catches edge cases that linters miss (empty returns, unset variables)

## Regression Prevention (Static Assertions)

For constraints that cannot be checked at runtime (e.g., bash version
compatibility), add static assertions that scan the script for forbidden
patterns.

**Pattern:**

```python
def test_no_bash_4_features(self) -> None:
    """Ensure script avoids bash 4.0+ features for macOS bash 3.2 compat."""
    content = script_path.read_text()
    assert "declare -A" not in content, (
        "declare -A requires bash 4.0+ and breaks on macOS bash 3.2; "
        "use case statement or function-based lookup instead"
    )
```

**When to use**:
- Platform-specific constraints (e.g., macOS bash 3.2, POSIX compliance)
- Security constraints (e.g., no eval of untrusted input)
- Future-proof guards against reintroduction of known issues

**Error message pattern**: State what's forbidden, the constraint it violates,
and (if possible) the recommended alternative. This guides contributors toward
correct solutions rather than just failing the test.

## Parametrized Tests for Scalability

When a shell function processes multiple inputs (tools, configurations,
patterns), use parametrized tests to scale without test duplication.

**Pattern:**

```python
import pytest

@pytest.mark.parametrize(
    ("tool_name", "expected_url"),
    [
        ("jq", "jqlang.github.io"),
        ("yq", "github.com/mikefarah/yq"),
        ("ripgrep", "github.com/BurntSushi/ripgrep"),
    ],
)
def test_install_url_for_tool(self, tool_name: str, expected_url: str) -> None:
    """Verify installation URLs for known tools."""
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}" && _get_install_url "{tool_name}"'],
        capture_output=True,
        text=True,
    )
    assert expected_url in result.stdout
```

**Why**: Maintains one test definition but validates multiple cases. Adding
a new tool requires one new row in the parametrize list, not a new test.

## Test Directory Structure

Mirror the source code structure in `tests/`:

```
src/
  dev10x/
  bin/
    require-tool.sh

tests/
  dev10x/
  bin/
    __init__.py
    test_require_tool.py
    test_other_tool.py
```

This pattern makes it clear which tests cover which scripts and prevents
test files from becoming scattered and hard to maintain.

## Error Handling in Tests

Shell scripts often use exit codes to signal success/failure. Test both
the return code and the output:

```python
def test_tool_not_found_provides_install_url(self) -> None:
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}" && _get_install_url "unknown"'],
        capture_output=True,
        text=True,
    )
    # Function should exit 0 but produce empty output when tool unknown
    assert result.returncode == 0
    assert result.stdout.strip() == ""
```

This validates the caller can check `[[ -n "$url" ]]` before using the value.

## Best Practices

1. **Set timeout** — Prevents infinite loops from blocking test runs
2. **Capture output** — Use `capture_output=True` to inspect stdout/stderr
3. **Test edge cases** — Empty arguments, missing tools, malformed input
4. **Add comments** — Explain why the test matters (especially for static assertions)
5. **Verify exit codes** — Don't assume 0; check what the script actually returns
