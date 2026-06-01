"""Sensitivity axis for the PAP (Permission Abstraction Protocol) model.

Adds an orthogonal third axis to PAP action classification:

    (tier) × (reversibility) × (sensitivity)

Tier and reversibility classify *what the verb does*.
Sensitivity classifies *what the target is*.

A trivially-reversible, safe-read command against a sensitive target
scores "harmless" on the first two axes — but plainly deserves an
``ask``.  Effect resolution: any axis demanding ``ask``/``forbid``
wins (deny-overrides), so a sensitivity hit elevates the effective
effect independently of tier and reversibility.

Defined in GH-395; fixtures from GH-271 evidence #267–#273.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class SensitivityLabel(StrEnum):
    """Orthogonal sensitivity labels for PAP action classification.

    Each label covers a distinct threat class:

    SECRET
        Actions that inventory or access stored secrets — e.g.
        ``gh secret list``, ``kubectl get secret``, reads of ``.env``
        files and credential stores.  Discovering what secrets *exist*
        is already a reconnaissance step.

    CREDENTIAL
        Actions whose target or query matches known credential-name
        patterns (``*_RW``, ``PRODUCTION_*``, ``*_PASSWORD``,
        ``*_TOKEN``, ``*_SECRET``, ``export DB_``).  Distinct from
        SECRET because the sensitive information may not be stored in
        a dedicated secret store.

    PII
        Actions that touch customer-data tables, exports, or files
        recognised as containing personally-identifiable information.

    INFRA
        Actions that probe, resolve, or interact with production
        network topology — RDS endpoints, bastion / VPN hosts,
        production IP ranges, port probes (``nc -zv``, ``dig``).
    """

    SECRET = "secret"
    CREDENTIAL = "credential"
    PII = "pii"
    INFRA = "infra"

    def __repr__(self) -> str:
        return f"SensitivityLabel.{self.name}"


@dataclass(frozen=True)
class SensitivityMatch:
    """Result of a sensitivity classification pass.

    Attributes:
        label: The matched sensitivity category.
        pattern: Human-readable description of the rule that triggered.
        matched_text: The substring from the command that triggered the rule.
    """

    label: SensitivityLabel
    pattern: str
    matched_text: str


@dataclass(frozen=True)
class SensitivityPattern:
    """One entry in the sensitivity wordlist.

    Attributes:
        label: Which sensitivity category this pattern covers.
        regex: Compiled pattern matched against the full command string.
        description: Short human-readable label for error messages.
    """

    label: SensitivityLabel
    regex: re.Pattern[str]
    description: str


def _compile(label: SensitivityLabel, pattern: str, description: str) -> SensitivityPattern:
    return SensitivityPattern(
        label=label,
        regex=re.compile(pattern, re.IGNORECASE),
        description=description,
    )


# ---------------------------------------------------------------------------
# Default sensitivity wordlist
#
# Each entry covers one class of sensitive target recognised from
# GH-271 evidence #267–#273 and related sessions.
# ---------------------------------------------------------------------------

_DEFAULT_PATTERNS: list[SensitivityPattern] = [
    # ── SECRET ──────────────────────────────────────────────────────────────
    # GH-271 #267: gh secret list
    _compile(SensitivityLabel.SECRET, r"\bgh\s+secret\b", "gh secret"),
    # GH-271 #267: gh variable list/get
    _compile(SensitivityLabel.SECRET, r"\bgh\s+variable\b", "gh variable"),
    # kubectl secret access
    _compile(
        SensitivityLabel.SECRET,
        r"\bkubectl\b.*\bsecret\b",
        "kubectl secret",
    ),
    # .env file reads (direct read or cat/less)
    _compile(
        SensitivityLabel.SECRET,
        r"(?:^|\s)(?:cat|less|head|tail|bat)\s+.*\.env\b",
        ".env file read",
    ),
    _compile(
        SensitivityLabel.SECRET,
        r"(?:^|\s)\.env\b",
        ".env file reference",
    ),
    # ── CREDENTIAL ──────────────────────────────────────────────────────────
    # GH-271 #269: rg for *_PRODUCTION_RW
    _compile(
        SensitivityLabel.CREDENTIAL,
        r"[A-Z0-9_]*PRODUCTION[A-Z0-9_]*_RW\b",
        "PRODUCTION_RW credential pattern",
    ),
    # Generic _RW suffix (production read-write credentials)
    _compile(
        SensitivityLabel.CREDENTIAL,
        r"\b[A-Z0-9_]{3,}_RW\b",
        "*_RW credential suffix",
    ),
    # Common secret/token env-var suffixes: match env-var-style names that end
    # with a credential suffix.  The prefix is 1+ uppercase word chars so that
    # bare suffixes like "_PASSWORD" (no prefix) don't fire, while short names
    # like DB_PASSWORD, API_TOKEN, JWT_SECRET all match.
    _compile(
        SensitivityLabel.CREDENTIAL,
        r"\b[A-Z][A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY|PRIVATE_KEY)\b",
        "credential env-var pattern",
    ),
    # Explicit DB export patterns
    _compile(
        SensitivityLabel.CREDENTIAL,
        r"\bexport\s+DB_",
        "export DB_ credential",
    ),
    # GH-271 #270: ~/.config scans for credentials
    _compile(
        SensitivityLabel.CREDENTIAL,
        r"~/\.config\b.*(?:cred|pass|token|secret|key)",
        "~/.config credential scan",
    ),
    # ── PII ─────────────────────────────────────────────────────────────────
    # Customer-data table names combined with bulk-export or bulk-read verbs.
    # Matches forward (verb before table) or reverse (table before verb).
    # SELECT * FROM <pii-table> is treated as a bulk read of PII.
    _compile(
        SensitivityLabel.PII,
        r"(?:"
        # bulk export tools: mysqldump / pg_dump / mongodump targeting PII table
        r"\b(?:pg_dump|mysqldump|mongodump)\b.*\b(?:customers?|patients?|subscribers?|account_holders?)\b"
        r"|"
        # SQL SELECT *: may be followed by FROM and then the table name
        r"SELECT\s+\*\s+FROM\s+(?:customers?|patients?|subscribers?|account_holders?)\b"
        r"|"
        # reverse: table name then an export/dump verb on the same command line
        r"\b(?:customers?|patients?|subscribers?|account_holders?)\b.*\b(?:dump|export|backup)\b"
        r")",
        "customer-data export/dump",
    ),
    _compile(
        SensitivityLabel.PII,
        r"\bpersonally[_\s-]identifiable\b",
        "PII keyword",
    ),
    # ── INFRA ────────────────────────────────────────────────────────────────
    # GH-271 #271: dig on RDS writer endpoint
    _compile(
        SensitivityLabel.INFRA,
        r"\bdig\b.*\.rds\.amazonaws\.com\b",
        "RDS endpoint DNS resolution",
    ),
    # Any RDS hostname reference
    _compile(
        SensitivityLabel.INFRA,
        r"\.rds\.amazonaws\.com\b",
        "AWS RDS endpoint",
    ),
    # GH-271 #272–#273: nc probes to production DB ports
    _compile(
        SensitivityLabel.INFRA,
        r"\bnc\b.*-[zv]+",
        "nc port probe",
    ),
    # bastion / jump-host / VPN infrastructure.  wireguard may appear as
    # "wireguard0" (interface name) so we allow optional trailing digits.
    _compile(
        SensitivityLabel.INFRA,
        r"\b(?:bastion|jumphost|jump-host|wireguard\d*|cloudflared|tailscale)\b",
        "bastion/VPN host",
    ),
    # Production marker in hostnames/targets
    _compile(
        SensitivityLabel.INFRA,
        r"\bprod(?:uction)?[-.]",
        "production host/resource",
    ),
    # RFC 1918 private IPs frequently used as prod pivot targets (10.x, 172.16-31.x, 192.168.x)
    _compile(
        SensitivityLabel.INFRA,
        r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3})\b",
        "RFC 1918 private IP",
    ),
]


@dataclass
class SensitivityClassifier:
    """Classifies a command string against the sensitivity wordlist.

    Usage::

        classifier = SensitivityClassifier()
        matches = classifier.classify(command="gh secret list")
        # → [SensitivityMatch(label=SensitivityLabel.SECRET, ...)]

    The classifier checks all registered patterns and returns every
    match (there can be more than one — e.g. a command may touch both
    CREDENTIAL and INFRA targets).  Callers apply deny-overrides: if
    *any* match is returned, the effective effect is elevated to ``ask``
    regardless of tier and reversibility.

    Attributes:
        patterns: The wordlist used for classification.  Defaults to
            ``_DEFAULT_PATTERNS``.  Pass a custom list to narrow or
            extend coverage without subclassing.
    """

    patterns: list[SensitivityPattern] = field(default_factory=lambda: list(_DEFAULT_PATTERNS))

    def classify(self, *, command: str) -> list[SensitivityMatch]:
        """Return all sensitivity matches for *command*.

        Args:
            command: The full shell command string to inspect.

        Returns:
            List of :class:`SensitivityMatch` objects, one per matched
            pattern.  Empty list means no sensitivity concern was found.
        """
        results: list[SensitivityMatch] = []
        for pat in self.patterns:
            m = pat.regex.search(command)
            if m:
                results.append(
                    SensitivityMatch(
                        label=pat.label,
                        pattern=pat.description,
                        matched_text=m.group(0),
                    )
                )
        return results

    def is_sensitive(self, *, command: str) -> bool:
        """Return True if *command* triggers any sensitivity rule."""
        return bool(self.classify(command=command))

    def highest_label(self, *, command: str) -> SensitivityLabel | None:
        """Return the first matched label, or None if no match.

        When multiple labels match, returns the first match in wordlist
        order (which preserves the declaration order of
        ``_DEFAULT_PATTERNS``).
        """
        matches = self.classify(command=command)
        return matches[0].label if matches else None


__all__ = [
    "SensitivityClassifier",
    "SensitivityLabel",
    "SensitivityMatch",
    "SensitivityPattern",
]
