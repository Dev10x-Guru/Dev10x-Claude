# Module Extraction from Dual-Use Scripts

Pattern for moving code from a standalone uv-script to a proper module
while maintaining backward compatibility and CWD discipline.

## When to Use This Pattern

- Code needs to be imported by other modules (not just CLI)
- Standalone uv-scripts (PEP 723 shebang) with substantial logic
- Need to preserve the CLI entry point (e.g., for Bash skill invocation)

## Steps

1. **Create the module** in the appropriate package context:
   - e.g., `audit/permissions_model.py` (domain owns the logic)
   - NOT in skills (skills is a thin orchestration layer)

2. **Move all functions, classes, and constants** to the module

3. **Apply CWD discipline**:
   - Use `effective_cwd()` instead of `os.getcwd()`
   - Accept `project_root: str | None = None` parameter
   - Fallback chain: passed value → effective_cwd() → os.getcwd()

4. **Create module tests** (`tests/<package>/test_<module>.py`):
   - Test the module in isolation
   - Test CWD fallback behavior

5. **Refactor the original script** into a thin CLI adapter:
   - Import and re-export all public symbols
   - Keep the `main()` entry point
   - Update docstring to explain the architecture move

6. **Update script tests** (`tests/<category>/test_<script>.py`):
   - Verify re-exports (test `from original import symbol`)
   - Test that `main()` still drives the pipeline
   - Remove tests of internal logic (moved to module tests)

## Verification Checklist for Reviewers

- ✓ Module owns the logic; script is a thin re-export adapter
- ✓ CWD discipline applied: `effective_cwd()` + fallback chain
- ✓ Module tests added; script tests refactored to test adapter behavior
- ✓ Re-exports tested: `from script import symbol` pulls from module
- ✓ Backward compatibility maintained: callers don't know code moved
- ✓ Module docstring explains why the move happened (architecture, GH ticket)
