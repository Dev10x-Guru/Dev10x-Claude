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
    # Credentialed-CLI secret-exfil reads (GH-605). These verbs READ but
    # the value they return is a live secret — a broad "allow read
    # subcommands" grant on a credentialed wrapper must never cover them,
    # so DX014's sensitivity axis elevates them to ask even when the
    # surrounding wrapper (aws-vault exec, vercel) is otherwise pre-approved.
    _compile(
        SensitivityLabel.SECRET,
        r"\bsecretsmanager\s+get-secret-value\b",
        "aws secretsmanager get-secret-value",
    ),
    _compile(
        SensitivityLabel.SECRET,
        r"\bssm\s+get-parameters?\b.*--with-decryption\b",
        "aws ssm get-parameter --with-decryption",
    ),
    # `vercel env pull` / `vercel pull` write decrypted secrets to disk
    # (GH-605 evidence #24).
    _compile(
        SensitivityLabel.SECRET,
        r"\bvercel\s+(?:env\s+)?pull\b",
        "vercel env pull (decrypted secrets to disk)",
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
    # Production marker in hostnames/targets (GH-482).
    #
    # A bare ``prod-`` / ``prod.`` substring over-matches: filenames
    # (``prod-synthetic.yml``), branch slugs
    # (``feature/prod-synthetic-cohesion``), and grep literals all carry
    # the token without touching production infrastructure.  Narrow the
    # match to a genuine host context:
    #   • a ``scheme://prod-`` or ``user@prod-`` reference, or
    #   • a dotted FQDN whose ``prod`` label is followed by a real
    #     network domain suffix (``.internal``, ``.com``, ``.amazonaws.com``…).
    # A code/config extension (``.yml``, ``.json``, …) is not a domain
    # suffix, so file paths and slugs no longer fire.
    _compile(
        SensitivityLabel.INFRA,
        r"(?:"
        r"(?:://|@)prod(?:uction)?[-.]"
        r"|"
        r"\bprod(?:uction)?[-.][a-z0-9.-]*"
        r"\.(?:internal|local|amazonaws\.com|com|net|org|io|cloud|aws)\b"
        r")",
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


# ---------------------------------------------------------------------------
# Sensitivity-exception catalog — the user-owned downgrade layer (GH-604)
#
# DX014 elevates a sensitive command to ``ask`` by default. A user who
# has blessed a specific read-only probe to a known target should not be
# re-prompted every time. The exception catalog (Tier 2, synced via
# ~/.config/Dev10x/sensitivity-exceptions.yaml) downgrades blessed hits
# from ``ask`` to ``allow`` (or keeps an explicit ``ask``).
#
# These value objects and the resolver are pure domain logic; loading the
# YAML file is an infra concern handled in
# ``dev10x.validators.sensitivity_exceptions``.
# ---------------------------------------------------------------------------


class ExceptionEffect(StrEnum):
    """Effect a matched catalog entry applies to a DX014 sensitivity hit."""

    ALLOW = "allow"
    ASK = "ask"

    def __repr__(self) -> str:
        return f"ExceptionEffect.{self.name}"


@dataclass(frozen=True)
class SensitivityException:
    """One blessed entry in the sensitivity-exception catalog (GH-604).

    Hybrid target+shape matching (decision D5): an entry downgrades a
    DX014 hit to ``effect`` when *every* supplied matcher applies —

        label   apply only when every match carries this exact label
        shape   regex searched against the full command string
        target  regex searched against the full command string

    At least one matcher must be set; a matcher-less entry would bless
    every sensitive command and is rejected at construction. The
    ``label`` guard uses ``all(...)`` so a command that trips a second,
    un-blessed label (e.g. CREDENTIAL alongside a blessed INFRA probe)
    is not silently downgraded — only a label-less (shape/target) entry
    can bless a multi-label command, which is the user's explicit call.
    """

    effect: ExceptionEffect = ExceptionEffect.ALLOW
    label: SensitivityLabel | None = None
    shape: re.Pattern[str] | None = None
    target: re.Pattern[str] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.label is None and self.shape is None and self.target is None:
            raise ValueError("SensitivityException requires at least one of label/shape/target")

    def applies(self, *, matches: list[SensitivityMatch], command: str) -> bool:
        """Return True when every supplied matcher applies to this hit."""
        if not matches:
            return False
        if self.label is not None and not all(m.label == self.label for m in matches):
            return False
        if self.shape is not None and not self.shape.search(command):
            return False
        if self.target is not None and not self.target.search(command):
            return False
        return True


def resolve_exception_effect(
    *,
    matches: list[SensitivityMatch],
    command: str,
    exceptions: list[SensitivityException],
) -> ExceptionEffect | None:
    """Return the effect of the first applicable catalog entry, or None.

    First-match-wins by catalog order — the user controls precedence by
    ordering entries. ``None`` means no entry blessed this command, so
    the caller keeps DX014's default ``ask`` elevation.
    """
    for exc in exceptions:
        if exc.applies(matches=matches, command=command):
            return exc.effect
    return None


# ---------------------------------------------------------------------------
# Identifier sensitivity — the NAME axis (GH-607)
#
# This module is the single source of the sensitivity vocabulary for every
# PAP surface. ``SensitivityClassifier`` above matches *command strings*
# (shell-shaped regexes, used by DX014); the helpers below match *identifier
# names* — MCP tool, CLI command, and skill names — by word token.
#
# Both wordlists live here so the four surfaces — DX014, MCP promotion
# (``promote.py``), the credentialed-CLI allowlist (GH-605), and skill
# curation (GH-608) — share one source and cannot drift apart. Previously
# the name-token set and its tokenizer lived in
# ``skills/permission/promote.py``, duplicating the sensitivity notion the
# regex wordlist already encodes (GH-607). The skills layer now imports
# these from the domain layer rather than re-declaring them.
# ---------------------------------------------------------------------------

# Splits an identifier into word tokens: an acronym run before a CamelWord
# (``HTTPSConnection`` → ``HTTPS`` + ``Connection``), a Capitalized or
# lowercase word, a bare acronym, or a digit run. Combined with splitting on
# ``_`` this tokenizes camelCase MCP tools (``getJiraIssue`` →
# ``{get, jira, issue}``) instead of collapsing them into one token (GH-593).
_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")

# Read identifiers whose target is private/DM/secret/credential data — a read
# verb against one of these is promotable only on an explicit opt-in.
SENSITIVE_NAME_TOKENS: frozenset[str] = frozenset(
    {"private", "secret", "secrets", "credential", "credentials", "password", "dm"}
)


def tokenize_identifier(name: str) -> set[str]:
    """Split a surface identifier into lowercase word tokens.

    Strips any ``server__tool`` MCP prefix (keeps the final segment), then
    splits on ``_`` and camelCase boundaries (GH-593). Shared by the
    read/write classifier (``promote.classify_tokens``) and the name-based
    sensitivity check so every surface tokenizes identically (GH-607).
    """
    short = name.rsplit("__", 1)[-1]
    return {
        match.group(0).lower()
        for chunk in short.split("_")
        for match in _IDENTIFIER_TOKEN_RE.finditer(chunk)
    }


def name_is_sensitive(name: str, *, tokens: frozenset[str] = SENSITIVE_NAME_TOKENS) -> bool:
    """Return True when an identifier names a private/DM/secret/credential read.

    Distinct from :class:`SensitivityClassifier`, which matches shell-command
    *shapes*: this matches identifier *tokens* (tool / skill / command names).
    Both share this module as their single source (GH-607).
    """
    return bool(tokenize_identifier(name) & tokens)


__all__ = [
    "SENSITIVE_NAME_TOKENS",
    "ExceptionEffect",
    "SensitivityClassifier",
    "SensitivityException",
    "SensitivityLabel",
    "SensitivityMatch",
    "SensitivityPattern",
    "name_is_sensitive",
    "resolve_exception_effect",
    "tokenize_identifier",
]
