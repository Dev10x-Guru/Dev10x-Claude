"""Strategy: forbidden-token-priming (GH-272).

Detects forbidden-token mentions in skill documentation that prime
the agent to reproduce the very anti-pattern the docs warn against.

The canonical case is ``DEV10X_SKIP_CMD_VALIDATION``: when the env
var appears as a negative example in a SKILL.md or instructions.md
("do NOT use this"), the literal token loads into the agent's
context every time the skill is referenced. Agents reaching for the
documented form are following the priming the plugin itself created.

Mirrors ``mcp_vs_script_drift`` but generalises across an extensible
token list. Hook-layer documentation paths (.claude/rules/, hooks/)
are exempt — that is where the token MUST be documented for skill
authors.
"""

from __future__ import annotations

from pathlib import Path

from dev10x.skills.doctor.strategy import (
    Context,
    Finding,
    Remediation,
    Strategy,
)

FORBIDDEN_TOKENS: dict[str, str] = {
    "DEV10X_SKIP_CMD_VALIDATION": (
        "structural guidance referencing the skill's mktmp mechanism "
        "or the documented escape path in .claude/rules/hook-patterns.md"
    ),
}

EXEMPT_PATH_FRAGMENTS: tuple[str, ...] = (
    "/.claude/rules/",
    "/hooks/",
    "/references/agents/",
    "/strategies/forbidden_token_priming",
)


def _is_exempt(path: Path) -> bool:
    path_str = str(path)
    return any(fragment in path_str for fragment in EXEMPT_PATH_FRAGMENTS)


def _scan_skill_docs(*, context: Context) -> list[Finding]:
    findings: list[Finding] = []
    plugin_root = context.plugin_cache_root
    if plugin_root is None or not plugin_root.exists():
        return findings

    patterns = ("SKILL.md", "instructions.md")
    for pattern in patterns:
        for doc_path in plugin_root.rglob(pattern):
            if _is_exempt(doc_path):
                continue
            try:
                text = doc_path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for token, suggested_replacement in FORBIDDEN_TOKENS.items():
                if token not in text:
                    continue
                findings.append(
                    Finding(
                        strategy_id="forbidden-token-priming",
                        severity="drift",
                        location=str(doc_path),
                        evidence=(
                            f"skill doc names forbidden token {token!r} — "
                            "negative-example mention primes the wrong behavior"
                        ),
                        proposed_fix=(
                            f"replace the literal mention with {suggested_replacement}; "
                            "keep the env var's true documentation in the hook layer only"
                        ),
                        metadata={
                            "token": token,
                            "suggested_replacement": suggested_replacement,
                        },
                    )
                )
    return findings


def detect(context: Context) -> list[Finding]:
    return _scan_skill_docs(context=context)


def remediate(finding: Finding) -> Remediation:
    return Remediation(
        kind="file_issue",
        target=finding.location,
        action={
            "token": finding.metadata.get("token"),
            "replacement": finding.metadata.get("suggested_replacement"),
        },
    )


STRATEGY = Strategy(
    id="forbidden-token-priming",
    description=(
        "Surface skill docs that name forbidden tokens as negative "
        "examples, priming the agent to reach for them."
    ),
    detect=detect,
    remediate=remediate,
)
