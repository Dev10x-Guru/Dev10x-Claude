"""Matrix definition for rule-shape investigation.

Each :class:`MatrixCell` pairs a candidate rule shape with the
fixture path it should authorize and the rule-location dimension
(global / project / both / neither). The skill loops through the
generated matrix, applies each cell, dispatches a subagent to
exercise the corresponding tool call, and records the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Literal

ToolKind = Literal["Read", "Bash", "Edit", "Write", "MCP"]
RuleLocation = Literal["global", "project", "both", "neither"]
PathPrefix = Literal["tilde", "home_user", "env_home", "relative"]
WildcardShape = Literal[
    "literal",
    "single_star",
    "trailing_slash_star",
    "double_star",
    "star_double_star",
    "mid_path_star",
]


@dataclass(frozen=True)
class RuleShape:
    """One candidate rule shape (the LHS of a permission allow rule)."""

    tool: ToolKind
    prefix: PathPrefix
    wildcard: WildcardShape

    def render(self, *, fixture_relpath: str, user_home: str) -> str:
        """Render the rule string for this shape against a fixture path.

        ``fixture_relpath`` is the path *relative to user home* — e.g.
        ``.claude/plugins/cache/Test/Plugin/9.9.9/skills/x/SKILL.md``.
        """
        prefix = _PREFIX_RENDERERS[self.prefix](user_home=user_home)
        body = _WILDCARD_RENDERERS[self.wildcard](relpath=fixture_relpath)
        path = f"{prefix}/{body}" if prefix else body
        if self.tool == "MCP":
            return "mcp__plugin_Dev10x_cli__detect_tracker"
        return f"{self.tool}({path})"


@dataclass(frozen=True)
class MatrixCell:
    """A single matrix coordinate: shape + where it lives + outcome slot."""

    shape: RuleShape
    location: RuleLocation
    cell_id: str

    @property
    def label(self) -> str:
        return f"{self.shape.tool}/{self.shape.prefix}/{self.shape.wildcard}@{self.location}"


@dataclass
class MatrixResult:
    """Outcome recorded by the dispatcher for one cell."""

    cell_id: str
    auto_approved: bool
    prompted: bool
    error: str | None = None
    notes: str = ""

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if self.auto_approved and not self.prompted:
            return "works"
        if self.prompted:
            return "prompts"
        return "unknown"


@dataclass
class Matrix:
    """A complete matrix — input cells plus collected results."""

    cells: list[MatrixCell] = field(default_factory=list)
    results: dict[str, MatrixResult] = field(default_factory=dict)

    def add_result(self, result: MatrixResult) -> None:
        self.results[result.cell_id] = result

    def coverage(self) -> tuple[int, int]:
        return len(self.results), len(self.cells)


def _tilde_prefix(*, user_home: str) -> str:
    del user_home
    return "~"


def _home_user_prefix(*, user_home: str) -> str:
    return user_home


def _env_home_prefix(*, user_home: str) -> str:
    del user_home
    return "${HOME}"


def _relative_prefix(*, user_home: str) -> str:
    del user_home
    return ""


_PREFIX_RENDERERS = {
    "tilde": _tilde_prefix,
    "home_user": _home_user_prefix,
    "env_home": _env_home_prefix,
    "relative": _relative_prefix,
}


def _literal_wildcard(*, relpath: str) -> str:
    return relpath


def _single_star_wildcard(*, relpath: str) -> str:
    parts = relpath.rsplit("/", 1)
    if len(parts) == 1:
        return "*"
    return f"{parts[0]}/*"


def _trailing_slash_star_wildcard(*, relpath: str) -> str:
    parts = relpath.rsplit("/", 1)
    if len(parts) == 1:
        return "*/"
    return f"{parts[0]}/*/"


def _double_star_wildcard(*, relpath: str) -> str:
    parts = relpath.rsplit("/", 1)
    if len(parts) == 1:
        return "**"
    return f"{parts[0]}/**"


def _star_double_star_wildcard(*, relpath: str) -> str:
    parts = relpath.split("/")
    if len(parts) <= 1:
        return "*/**"
    return f"{'/'.join(parts[:-1])}/*/**"


def _mid_path_star_wildcard(*, relpath: str) -> str:
    parts = relpath.split("/")
    if len(parts) < 2:
        return relpath
    mid = max(0, len(parts) // 2)
    parts[mid] = "*"
    return "/".join(parts)


_WILDCARD_RENDERERS = {
    "literal": _literal_wildcard,
    "single_star": _single_star_wildcard,
    "trailing_slash_star": _trailing_slash_star_wildcard,
    "double_star": _double_star_wildcard,
    "star_double_star": _star_double_star_wildcard,
    "mid_path_star": _mid_path_star_wildcard,
}


DEFAULT_TOOLS: tuple[ToolKind, ...] = ("Read", "Bash")
DEFAULT_PREFIXES: tuple[PathPrefix, ...] = ("tilde", "home_user", "env_home")
DEFAULT_WILDCARDS: tuple[WildcardShape, ...] = (
    "literal",
    "single_star",
    "double_star",
    "star_double_star",
)
DEFAULT_LOCATIONS: tuple[RuleLocation, ...] = ("global", "project", "both")


def generate_matrix(
    *,
    tools: tuple[ToolKind, ...] = DEFAULT_TOOLS,
    prefixes: tuple[PathPrefix, ...] = DEFAULT_PREFIXES,
    wildcards: tuple[WildcardShape, ...] = DEFAULT_WILDCARDS,
    locations: tuple[RuleLocation, ...] = DEFAULT_LOCATIONS,
) -> Matrix:
    """Generate the cartesian product of dimensions as a Matrix."""
    matrix = Matrix()
    for tool, prefix, wildcard, location in product(
        tools, prefixes, wildcards, locations
    ):
        shape = RuleShape(tool=tool, prefix=prefix, wildcard=wildcard)
        cell = MatrixCell(
            shape=shape,
            location=location,
            cell_id=f"{tool}.{prefix}.{wildcard}.{location}",
        )
        matrix.cells.append(cell)
    return matrix
