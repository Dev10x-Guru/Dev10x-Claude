# Bash Compatibility for macOS

macOS ships with bash 3.2 (released 2007, GPL v2 license). It has not been
updated to preserve GPL v2 license compliance. Tools and skills targeting
macOS must avoid bash 4.0+ features to ensure scripts run without errors.

## Incompatible Patterns

| Pattern | Bash 4.0+ Feature | Bash 3.2 Alternative |
|---------|----------|-------------|
| `declare -A assoc_array` | Associative arrays | Case statement or lookup function |
| `[[ $var =~ regex ]]` | Regex operator | `grep`, `sed`, or `expr` |
| `${var//old/new}` | Parameter expansion (global replace) | `sed` with `-e 's/old/new/g'` |
| `<(command)` | Process substitution | Temp file + subshell |
| `[[ -v VAR ]]` | Variable existence test | `[[ -n "${VAR+set}" ]]` |

## Detection in Code Review

When reviewing shell scripts targeting macOS, verify absence of incompatible
patterns using grep:

```bash
grep -E 'declare -A|=~|\$\{.*//|<\(|\\[\\[ -v' script.sh
```

If matches found, request refactoring to use bash 3.2 compatible alternatives.

## Detection in Tests

Add static assertions to test suite to prevent reintroduction of incompatible
patterns:

```python
def test_no_bash_4_features(self) -> None:
    """Prevent macOS bash 3.2 incompatibilities."""
    content = Path("bin/script.sh").read_text()

    forbidden_patterns = [
        ("declare -A", "Associative arrays; use case statement or function"),
        ("[[ $var =~ ", "Regex operator; use grep or sed"),
    ]

    for pattern, reason in forbidden_patterns:
        assert pattern not in content, (
            f"Pattern '{pattern}' requires bash 4.0+: {reason}"
        )
```

See `references/shell-testing-patterns.md` for full testing pattern with
examples.

## When to Apply

**Require bash 3.2 compatibility for**:
- Scripts invoked by PreToolUse/PostToolUse hooks
- CLI tools shipped with Dev10x plugin (used on contributor machines)
- Shared infrastructure scripts in `bin/`
- Scripts sourced by other shell scripts

**Do NOT require bash 3.2 compatibility for**:
- Scripts explicitly documented as Linux-only
- Docker/container build scripts (container has bash 4+)
- GitHub Actions workflow steps (GH Actions runs Ubuntu with bash 5+)
- Scripts requiring bash 4+ features for functionality

## Implementation Example

Reference bash version constraints in code comments:

```bash
# Requires bash 3.2 compatible lookup; avoid declare -A
_get_install_url() {
    local name=$1
    case "$name" in
        jq) echo "https://jqlang.github.io/download/" ;;
        yq) echo "https://github.com/mikefarah/yq/releases" ;;
        *) return 1 ;;
    esac
}
```

Established by PR #663 (macOS bash 3.2 compatibility fix).

## References

- [macOS bash version history](https://tidbits.com/2019/02/05/macos-bash-fork-version-history/)
- [Bash 4.0 release notes](https://www.gnu.org/software/bash/manual/html_node/What_0027s-New-in-Bash-4_002e0.html)
