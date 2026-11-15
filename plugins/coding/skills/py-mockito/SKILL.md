---
name: dev10x:py-mockito
description: >
  Write pytest tests with python-mockito and pytest-mockito — stub
  collaborator classes with when(), assert calls with verify(), capture
  arguments with captor(), and clean up with unstub() — so tests in a
  dependency-injection codebase isolate the unit under test without
  leaking stubs between tests.
  TRIGGER when: writing or reviewing Python tests that import from
  `mockito`, use the pytest-mockito `when` fixture, or need to stub a
  collaborator class resolved from a DI container.
  DO NOT TRIGGER when: the project uses `unittest.mock` / `pytest-mock`
  only, or the task is running tests (use dev10x:py-test).
user-invocable: true
invocation-name: dev10x:py-mockito
allowed-tools:
  - TaskCreate
  - TaskUpdate
  - Read(${CLAUDE_PLUGIN_ROOT}/skills/py-mockito/references/**)
---

# Python Mockito Testing Patterns

**Announce:** "Using dev10x:py-mockito to write mockito-based tests."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Apply mockito test patterns", activeForm="Writing mockito tests")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

**python-mockito** provides a Java-Mockito-inspired stubbing and
verification API for Python tests. Combined with **pytest-mockito**,
it integrates with pytest fixtures. Its key advantage over
`unittest.mock`: a stub can target a **class**, so every instance a
dependency-injection container resolves picks it up — no need to
reach the exact object the code under test will receive. Instances,
modules and managers can be stubbed too when that is the seam you
have.

**Core philosophy:** stub collaborator *classes* so the container
returns controlled behavior. Verify interactions by asserting *what
was called*, not *how the return value was used*.

## Quick Reference

```python
from mockito import (
    ANY,                     # match any single positional arg
    KWARGS,                  # match any keyword arguments
    any_,                    # typed matcher: any_(list), any_(int)
    captor,                  # capture args for later inspection
    mock,                    # create standalone mock object
    unstub,                  # remove stubs (cleanup)
    verify,                  # assert method was called
    verifyZeroInteractions,  # assert mock was never touched
    when,                    # stub a method to return/raise
)
```

| Function | Purpose | Example |
|----------|---------|---------|
| `when(Cls).method(...).thenReturn(val)` | Stub any call | Ellipsis matches all args |
| `when(Cls).method(x=1).thenReturn(val)` | Stub specific call | Named args for precision |
| `verify(Cls).method(x=1)` | Assert called once | Default `times=1` |
| `verify(Cls, times=0).method(...)` | Assert never called | Negative assertion |
| `captor()` | Capture argument | Inspect via `.value` |
| `mock()` | Create mock object | Standalone, no class |
| `unstub(Cls)` | Remove stubs on Cls | Or `unstub()` for all |

## Which Reference to Read

Read only the file the current test needs:

| Need | Reference |
|------|-----------|
| `when()` stubs, matchers, `thenReturn`/`thenRaise`, `verify()`, `captor()`, `mock()` | [`references/stubbing-and-verification.md`](references/stubbing-and-verification.md) |
| `unstub()` cleanup, the `when` fixture, autouse stubs, marker opt-in, result fixtures | [`references/pytest-patterns.md`](references/pytest-patterns.md) |
| `__call__` stubs, fluent-API chains, module functions, private methods, DI container, logger calls | [`references/advanced-patterns.md`](references/advanced-patterns.md) |

## The Cleanup Rule

python-mockito patches its targets globally, so a stub that outlives
its test leaks into every later test and turns an unrelated one red.

- **Use the pytest-mockito `when` fixture** (a test or fixture
  parameter, not an import). It unstubs at the end of each test, so
  function-scoped stubs need no cleanup code.
- **Clean up yourself** only when the stub escapes that teardown:
  `from mockito import when` at module level, or a stub set in a
  fixture scoped wider than the test (`class`, `module`, `session`).
  Then pair it with a targeted unstub:

```python
from mockito import unstub, when


@pytest.fixture(scope="class")
def stub_token_repository(token):
    when(TokenRepository).get_access_token(...).thenReturn(token)
    yield
    unstub(TokenRepository)
```

Prefer `unstub(SpecificClass)` over a bare `unstub()` in such a
fixture — the bare form clears every stub, including ones another
fixture still relies on.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Importing `mockito.when` and never unstubbing | Take the `when` fixture instead, or yield + `unstub(Cls)` |
| Stubbing an instance you built while the container resolves a fresh one | Stub the class: `when(MyClass).method(...)` reaches every resolved instance |
| Using `...` when you need to verify specific args | Use Ellipsis for stubs, named args for verify |
| Missing `thenReturn()` on void stubs | Either `when(X).m(...)` (implicit None) or `.thenReturn(None)` |
| Calling `unstub()` without args in a fixture | Clears ALL stubs globally — prefer `unstub(SpecificClass)` |
| Not using `captor.all_values` for multiple calls | `.value` returns only the last capture; use `.all_values` for all |
| Forgetting to register mock for `verifyZeroInteractions` | Call `when(module)` first to register it for tracking |

## Dependencies

```toml
[dependency-groups]
dev = [
    "mockito",
    "pytest-mockito",
]
```

`pytest-mockito` auto-provides the `when` fixture to all tests.
No manual registration or plugin configuration needed.
