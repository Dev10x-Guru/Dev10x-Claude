# Cedar `@sensitivity` Annotation Pattern

Specification for the sensitivity axis of the PAP (Permission Abstraction
Protocol) action model.
Complementary to the tier and reversibility axes already defined in the PAP.

## Three-Axis PAP Model

The full PAP action model classifies every Bash command on three orthogonal
axes:

| Axis | Question answered | Defined in |
|------|-------------------|------------|
| **Tier** | What verb class does this command fall into? | `references/friction-levels.md` |
| **Reversibility** | Can the effect be undone without specialist help? | `references/friction-levels.md` |
| **Sensitivity** | Does the target touch secrets, credentials, PII, or infra? | This document / `src/dev10x/domain/sensitivity.py` |

### Deny-Overrides Resolution

Effective effect = `max(tier_effect, reversibility_effect, sensitivity_effect)`
where the ordering is: `permit < ask < forbid`.

Any axis that demands `ask` or `forbid` wins, independent of the other two.
A trivially-reversible, safe-read command (`permit` on tier and reversibility)
still resolves to `ask` if the sensitivity axis fires.

This is the Cedar *deny-overrides* combination algorithm:

```cedar
// Conceptual Cedar pseudocode — Dev10x does not run Cedar directly;
// Claude Code is the PDP+PEP.  This shows the policy intent.

@sensitivity("secret")
forbid(
  principal is Agent,
  action == Action::"Bash",
  resource
)
when {
  resource.command matches SensitivityWordlist::SECRET
};

// Deny-overrides: any forbid/ask wins over permit.
// permit policies from the tier/reversibility axes are still evaluated,
// but the effect resolution picks the strictest matching policy.
```

## Cedar `@sensitivity` Annotation

The `@sensitivity` annotation labels a policy with the sensitivity category
that caused it.
It is surfaced in audit logs and human-readable hook messages so operators
can understand why a command was blocked.

### Label Vocabulary

| Annotation value | Scope |
|------------------|-------|
| `"secret"` | Secret stores, `.env` files, `gh secret`, `kubectl secret` |
| `"credential"` | Credential env-vars (`*_PASSWORD`, `*_TOKEN`, `*_RW`), `export DB_*` |
| `"pii"` | Customer-data tables, PII export/dump commands |
| `"infra"` | Production network probes (RDS, bastion, VPN, private IPs) |

### Annotation Usage Pattern

```cedar
@sensitivity("secret")
forbid(principal, action, resource)
when { resource.command matches secret_wordlist };

@sensitivity("credential")
forbid(principal, action, resource)
when { resource.command matches credential_wordlist };

@sensitivity("pii")
forbid(principal, action, resource)
when { resource.command matches pii_wordlist };

@sensitivity("infra")
forbid(principal, action, resource)
when { resource.command matches infra_wordlist };
```

## Implementation Mapping

Dev10x does not execute Cedar policies directly.
The mapping to the Claude Code hook system is:

| Cedar concept | Dev10x implementation |
|---------------|-----------------------|
| `@sensitivity` annotation | `SensitivityLabel` enum in `sensitivity.py` |
| `resource.command matches wordlist` | `SensitivityClassifier.classify()` |
| `forbid` with deny-overrides | `DX014 SensitivityTargetValidator` → `HookResult` (deny) |
| Cedar PolicySet | Validator registry (`validators/__init__.py`) |
| PDP + PEP | Claude Code PreToolUse hook infrastructure |

### Effect Mapping

| Cedar effect | Claude Code hook exit |
|-------------|----------------------|
| `permit` | `sys.exit(0)` (no output) / `HookAllow` |
| `ask` | `HookResult` with advisory message → `permissionDecision: deny` |
| `forbid` | `HookResult` with hard block → `permissionDecision: deny` |

DX014 maps sensitivity hits to `ask` semantics: it blocks the command and
presents a message that asks the user to approve explicitly.
This is more conservative than `permit` but less absolute than a silent
`forbid` — the user sees the reason and can approve if they intended it.

## Cross-References

- **GH-395**: `SensitivityClassifier` domain model (Increment 1).
  `src/dev10x/domain/sensitivity.py` — `SensitivityLabel`, `SensitivityMatch`,
  `SensitivityPattern`, `SensitivityClassifier`.
- **GH-406**: This document + DX014 validator wiring (Increment 2).
  `src/dev10x/validators/sensitivity_target.py`.
- **GH-271**: Evidence corpus.
  Fixtures #267–#273 drove the default wordlist entries for all four labels.
- **GH-310**: Sequence/unattended gate.
  Complements the per-command sensitivity axis: GH-310 gates entire
  sequences of commands in unattended runs, while DX014 gates individual
  commands at the point of execution.
- **GH-371**: Resource-classification / `capability_group` annotation.
  The `capability_group` annotation on MCP server entries (horizontal
  duplicate detection) is the resource-side analogue of the
  `@sensitivity` annotation on the command side.
  Together they form a two-sided classification: verb class on one side,
  resource sensitivity on the other.

## Wordlist Extension

The default wordlist is defined in `src/dev10x/domain/sensitivity.py`
as `_DEFAULT_PATTERNS`.
To extend it per project, inject a custom `SensitivityClassifier`:

```python
from dev10x.domain.sensitivity import SensitivityClassifier, SensitivityLabel, SensitivityPattern
import re

my_classifier = SensitivityClassifier(
    patterns=[
        *_DEFAULT_PATTERNS,
        SensitivityPattern(
            label=SensitivityLabel.PII,
            regex=re.compile(r"\bmy_pii_table\b", re.IGNORECASE),
            description="my_pii_table",
        ),
    ]
)
```

For the validator, pass it at construction time:

```python
from dev10x.validators.sensitivity_target import SensitivityTargetValidator

v = SensitivityTargetValidator(classifier=my_classifier)
# or use the factory:
v = SensitivityTargetValidator().with_patterns([...])
```

## Tier × Reversibility × Sensitivity Matrix

The table below shows the effective effect for representative combinations.
`S` = sensitivity hit; `–` = no sensitivity hit.

| Tier | Reversibility | Sensitivity | Effective effect |
|------|---------------|-------------|-----------------|
| safe-read | trivial | – | permit |
| safe-read | trivial | S | **ask** ← DX014 |
| safe-read | assisted | – | ask |
| safe-read | assisted | S | **ask** |
| destructive | none | – | forbid |
| destructive | none | S | **forbid** |
| fence-tool | trivial | – | ask |
| fence-tool | trivial | S | **ask** |

In every row where sensitivity fires, the effective effect is at least `ask`.
The sensitivity axis never lowers the effect — it can only raise it.
