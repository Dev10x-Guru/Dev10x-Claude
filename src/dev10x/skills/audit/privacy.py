"""Detect external-service usage and privacy-policy drift across the plugin.

GH-6 — security audits for the Dev10x plugin.

Two responsibilities:

1. **Inventory** — scan source files (``src/``, ``skills/``, ``bin/``,
   ``hooks/``, ``servers/``, ``commands/``) for any reference to
   third-party services. References are matched by:

   * Python imports of HTTP/network libraries (``requests``, ``httpx``,
     ``urllib``, ``aiohttp``).
   * Subprocess invocations of external CLI tools (``gh``, ``aws-vault``,
     ``kubectl``, ``psql``).
   * MCP tool namespaces (``mcp__claude_ai_Linear__*``,
     ``mcp__sentry__*``, etc.).
   * Hostnames (``linear.app``, ``slack.com``, ``sentry.io``, ...).

2. **Drift check** — parse the "Third-party integrations" table in
   ``PRIVACY_POLICY.md`` to know which services are documented. Any
   service detected in the scan that is *not* listed in the policy is
   reported as a violation.

The scanner is deliberately heuristic: it favours false positives over
false negatives so that maintainers notice when a new integration slips
into the codebase without a corresponding privacy entry.

Inline suppressions are supported: append ``# privacy-audit: allow
<service> — reason`` to the offending line.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────
# Detection rules
# ─────────────────────────────────────────────────────────────────────

# Python imports that imply direct outbound network access from plugin
# code. The privacy policy explicitly states that hooks, validators, and
# MCP servers make no outbound calls — so any of these in plugin source
# is a violation regardless of which service they target.
OUTBOUND_NET_IMPORTS: frozenset[str] = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "urllib.request",
        "urllib3",
    }
)

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?P<from>[\w.]+)\s+import\s+|import\s+(?P<mod>[\w.]+))",
)

# Service detection patterns. Each service maps to a list of (kind,
# regex) tuples. ``kind`` is one of ``cli``, ``mcp``, ``hostname``,
# ``token`` and is reported back for context.
SERVICE_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "GitHub": [
        ("cli", re.compile(r"(?<![\w-])gh\s+(api|pr|issue|repo|run|release|workflow|auth)")),
        (
            "cli",
            re.compile(
                r"""['"]gh['"]\s*,\s*['"](?:api|pr|issue|repo|run|release|workflow|auth)['"]"""
            ),
        ),
        ("hostname", re.compile(r"\bgithub\.com\b")),
        ("hostname", re.compile(r"\bapi\.github\.com\b")),
    ],
    "Linear": [
        ("hostname", re.compile(r"\blinear\.app\b")),
        ("mcp", re.compile(r"\bmcp__(?:[a-z_]+_)?[Ll]inear[a-z_]*__")),
    ],
    "JIRA": [
        ("hostname", re.compile(r"\batlassian\.net\b")),
        ("hostname", re.compile(r"\bjira\.atlassian\.com\b")),
    ],
    "Slack": [
        ("hostname", re.compile(r"\bslack\.com\b")),
        ("mcp", re.compile(r"\bmcp__(?:[a-z_]+_)?[Ss]lack[a-z_]*__")),
    ],
    "Sentry": [
        ("hostname", re.compile(r"\bsentry\.io\b")),
        ("mcp", re.compile(r"\bmcp__(?:[a-z_]+_)?[Ss]entry[a-z_]*__")),
    ],
    "AWS Secrets Manager": [
        ("cli", re.compile(r"(?<![\w-])aws-vault\b")),
        ("cli", re.compile(r"(?<![\w-])aws\s+secretsmanager\b")),
    ],
    "Anthropic API": [
        ("hostname", re.compile(r"\banthropic\.com\b")),
        ("token", re.compile(r"ANTHROPIC_API_KEY\b")),
        ("cli", re.compile(r"\banthropics/claude-code-action\b")),
    ],
    "PyPI": [
        ("hostname", re.compile(r"\bpypi\.org\b")),
        ("cli", re.compile(r"(?<![\w-])twine\s+upload\b")),
    ],
    "Kubernetes API": [
        ("cli", re.compile(r"(?<![\w-])kubectl\b")),
    ],
    "Postgres": [
        ("cli", re.compile(r"(?<![\w-])psql\b")),
    ],
}

# File extensions worth scanning. Markdown is included so SKILL docs
# that name external services still register in the inventory.
_SCANNED_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".sh", ".md", ".yaml", ".yml", ".json", ".toml"}
)

# Directory names skipped during recursive scans.
_SKIPPED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)

# Files exempt from the outbound-network-import rule. The privacy
# policy itself describes these patterns, and tests intentionally
# exercise them.
_NET_IMPORT_EXEMPT_PATHS: tuple[str, ...] = (
    "PRIVACY_POLICY.md",
    "src/dev10x/skills/audit/privacy.py",
    "tests/",
    # Skill scripts are documented in PRIVACY_POLICY.md as user-invoked
    # outbound integrations. They are exempt from the no-outbound rule
    # because the policy explicitly covers them.
    "skills/qa-self/scripts/upload-screenshots.py",
    # `dev10x github-app setup` wizard module: explicitly verifies App
    # credentials against api.github.com before writing config. Covered
    # by the GitHub row in PRIVACY_POLICY.md.
    "src/dev10x/commands/github_app_api.py",
)

# Files exempt from service detection. The scanner defines the
# patterns it looks for, the policy enumerates documented services,
# and tests construct fixture inputs — none of these are real
# integrations.
_DETECTION_EXEMPT_PATHS: tuple[str, ...] = (
    "PRIVACY_POLICY.md",
    "bin/check-privacy-policy.py",
    "tests/skills/audit/test_privacy.py",
    # Validator and audit modules describe tools they classify or
    # intercept; they do not invoke them. The hook-validator and
    # session-audit architectures guarantee no outbound calls
    # from these modules.
    "src/dev10x/validators/",
    "src/dev10x/skills/audit/",
    "skills/skill-audit/",
    # The skill-reinforcement skill exists to redirect agents away
    # from raw CLI commands; naming those commands is its job.
    "skills/skill-reinforcement/",
)

_INLINE_ALLOW_RE = re.compile(
    r"#\s*privacy-audit:\s*allow\s+(?P<service>[\w .()/-]+?)\s*(?:—|--|$)",
)


# ─────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ServiceUsage:
    """A single detected reference to an external service."""

    service: str
    kind: str
    path: Path
    line_number: int
    snippet: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line_number}: [{self.service}/{self.kind}] {self.snippet.strip()}"
        )


@dataclass(frozen=True)
class NetImportViolation:
    """A direct outbound-network import in plugin source."""

    module: str
    path: Path
    line_number: int
    snippet: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line_number}: [outbound-network] "
            f"imports `{self.module}` — violates 'no outbound calls' policy"
        )


@dataclass(frozen=True)
class AuditResult:
    """Outcome of an audit run."""

    usages: tuple[ServiceUsage, ...]
    net_imports: tuple[NetImportViolation, ...]
    documented: frozenset[str]
    undocumented: frozenset[str]

    @property
    def has_violations(self) -> bool:
        return bool(self.undocumented) or bool(self.net_imports)


# ─────────────────────────────────────────────────────────────────────
# Privacy policy parsing
# ─────────────────────────────────────────────────────────────────────


_TABLE_HEADER_RE = re.compile(r"^\|\s*Integration\s*\|\s*Credentials\s*\|", re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|.*\|.*\|\s*$")


def parse_documented_services(policy_text: str) -> frozenset[str]:
    """Extract service names from the policy's third-party table.

    The table header is::

        | Integration | Credentials | Data exchanged |

    Each subsequent row's first column is treated as a documented
    service name. The leading service label may contain a parenthetical
    (``GitHub (`gh` CLI, MCP)``) — the canonical name is everything up
    to the first parenthesis.
    """

    services: set[str] = set()
    in_table = False
    for raw_line in policy_text.splitlines():
        if _TABLE_HEADER_RE.match(raw_line):
            in_table = True
            continue
        if in_table:
            if not raw_line.startswith("|"):
                in_table = False
                continue
            stripped_chars = set(raw_line.replace("|", "")) - {" "}
            if stripped_chars <= {"-", ":"}:
                # separator row
                continue
            match = _TABLE_ROW_RE.match(raw_line)
            if not match:
                continue
            label = match.group(1)
            canonical = label.split("(")[0].strip().strip("`")
            if canonical:
                services.add(canonical)
    return frozenset(services)


# ─────────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────────


def _iter_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIPPED_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in _SCANNED_EXTENSIONS:
                continue
            yield path


def _is_net_import_exempt(path: Path) -> bool:
    text = str(path)
    return any(needle in text for needle in _NET_IMPORT_EXEMPT_PATHS)


def _is_detection_exempt(path: Path) -> bool:
    text = str(path)
    return any(needle in text for needle in _DETECTION_EXEMPT_PATHS)


def _suppressed_services(line: str) -> set[str]:
    return {match.group("service").strip() for match in _INLINE_ALLOW_RE.finditer(line)}


def _scan_text(path: Path, text: str) -> tuple[list[ServiceUsage], list[NetImportViolation]]:
    usages: list[ServiceUsage] = []
    net_violations: list[NetImportViolation] = []
    is_python = path.suffix == ".py"
    net_exempt = _is_net_import_exempt(path)
    detection_exempt = _is_detection_exempt(path)

    for line_no, line in enumerate(text.splitlines(), start=1):
        suppressions = _suppressed_services(line)

        if is_python and not net_exempt:
            match = _IMPORT_RE.match(line)
            if match:
                module = match.group("from") or match.group("mod") or ""
                top_level = module.split(".")[0]
                if module in OUTBOUND_NET_IMPORTS or top_level in OUTBOUND_NET_IMPORTS:
                    net_violations.append(
                        NetImportViolation(
                            module=module,
                            path=path,
                            line_number=line_no,
                            snippet=line.strip(),
                        )
                    )

        if detection_exempt:
            continue

        for service, patterns in SERVICE_PATTERNS.items():
            if service in suppressions:
                continue
            for kind, regex in patterns:
                if regex.search(line):
                    usages.append(
                        ServiceUsage(
                            service=service,
                            kind=kind,
                            path=path,
                            line_number=line_no,
                            snippet=line.strip(),
                        )
                    )
                    break  # one hit per service per line is enough
    return usages, net_violations


def scan_paths(
    paths: Iterable[Path],
) -> tuple[list[ServiceUsage], list[NetImportViolation]]:
    """Scan ``paths`` for external-service references and net imports."""

    all_usages: list[ServiceUsage] = []
    all_net: list[NetImportViolation] = []
    for path in _iter_files(paths):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        usages, net = _scan_text(path, text)
        all_usages.extend(usages)
        all_net.extend(net)
    return all_usages, all_net


def audit(
    *,
    scan_paths_: Iterable[Path],
    policy_path: Path,
) -> AuditResult:
    """Run a full audit and return documented vs undocumented services."""

    policy_text = policy_path.read_text(encoding="utf-8") if policy_path.exists() else ""
    documented = parse_documented_services(policy_text)

    usages, net_violations = scan_paths(scan_paths_)
    detected = {u.service for u in usages}
    undocumented = frozenset(detected - documented)

    return AuditResult(
        usages=tuple(usages),
        net_imports=tuple(net_violations),
        documented=documented,
        undocumented=undocumented,
    )


# ─────────────────────────────────────────────────────────────────────
# Reporting helpers
# ─────────────────────────────────────────────────────────────────────


def render_inventory_markdown(result: AuditResult) -> str:
    """Render a human-readable inventory of detected services."""

    if not result.usages:
        return "_No external services detected._\n"

    by_service: dict[str, list[ServiceUsage]] = {}
    for usage in result.usages:
        by_service.setdefault(usage.service, []).append(usage)

    lines: list[str] = ["# External Service Inventory", ""]
    for service in sorted(by_service):
        documented = "yes" if service in result.documented else "**NO**"
        usages = by_service[service]
        lines.append(f"## {service} (documented: {documented})")
        lines.append("")
        lines.append(f"References: {len(usages)}")
        lines.append("")
        for usage in usages[:20]:
            lines.append(f"- `{usage.path}:{usage.line_number}` ({usage.kind})")
        if len(usages) > 20:
            lines.append(f"- ... and {len(usages) - 20} more")
        lines.append("")
    return "\n".join(lines)
