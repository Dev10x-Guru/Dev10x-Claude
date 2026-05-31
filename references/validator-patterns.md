# Validator Design Patterns

Patterns for detecting command properties with flags when implementing bash
command validators (e.g., `ExecutionSafetyValidator`).

## Multi-Flag Detection

When a validator detects command patterns with flags (e.g., `sed -i`,
`perl -pi`), handle these cases:

### Short-Flag Clusters

Flags like `-i`, `-ni.bak`, `-in` (contiguous letters after `-`).

```python
# For arg="-ni.bak", extract flag_body = arg[1:] = "ni.bak"
# Collect alpha chars until non-alpha: "ni"
flag_letters = "".join(itertools.takewhile(str.isalpha, arg[1:]))
if "i" in flag_letters:
    # Block: -i (or -ni, -mi, etc.) detected
    return ValidationResult(...)
```

Example: ExecutionSafetyValidator blocks `sed -i` but allows `sed -n`.

### Separate-Token Flags

Flags spanning two tokens, like `gawk -i inplace` (flag + next token).

```python
if idx < len(argv) - 1 and argv[idx] == "-i" and argv[idx + 1] == "inplace":
    # Block: gawk -i inplace detected
    return ValidationResult(...)
```

Boundary check ensures no index overflow.

### Safe-Form Exclusion

Modifiers that make a command safe (e.g., `sed -n` for read-only).

```python
# Structure validation to allow read-only forms, block write forms
if "-n" in argv and "-i" in argv:
    return None  # -n disables the write, safe
elif "-i" in argv:
    return ValidationResult(...)  # -i without -n, block
```

### Special-Path Escapes

Commands with path arguments that are safe for specific targets.

```python
# Example: dd of=/dev/null is safe, dd of=/tmp/file is not
for arg in argv:
    if arg.startswith("of="):
        path = arg[3:]
        if not re.match(r"^/dev/(null|stdout|stderr)$", path):
            return ValidationResult(...)
```

### Pipeline Awareness

Validate each pipeline segment separately.

```python
segments = command.split("|")
for segment in segments:
    segment_argv = shlex.split(segment)
    if should_block(segment_argv):
        return ValidationResult(...)
```

## Reference Implementation

See `src/dev10x/validators/execution_safety.py` (DX003) for a complete
example covering short-flag clusters, separate tokens, safe-form exclusion,
and pipe awareness.
