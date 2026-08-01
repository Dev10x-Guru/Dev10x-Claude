"""Report pinned dependencies whose next release is outside the bound (GH-937).

GH-916 gave every PEP 723 uv-script requirement and every
`pyproject.toml` dependency an upper bound, which stops the GH-914
failure mode (an unbounded requirement resolving a breaking major at run
time). It also trades "silent breakage" for "silent staleness": nothing
tells a maintainer when a pinned dependency's next major has shipped.

This module closes that gap. It reuses
:mod:`dev10x.dependency_pins`'s parsing to enumerate the declared pins,
then asks the package index for each distribution's current version and
reports the ones the declared bound would refuse. Callers:
``dev10x deps sweep`` (local + scheduled workflow).

No `packaging` dependency: comparing a release tuple is all the check
needs, and `uvx dev10x` installs base dependencies only — adding a
runtime dependency for one comparison would tax every invocation.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev10x.dependency_pins import PinnedRequirement, collect_pinned_requirements
from dev10x.domain.common.result import Result, SuccessResult, err, ok

_logger = logging.getLogger(__name__)

PYPI_JSON_URL = "https://pypi.org/pypi/{distribution}/json"
DEFAULT_TIMEOUT_SECONDS = 15.0

# Captures the tightest kind of ceiling a requirement can declare: `<`,
# `<=`, or an exact `==`. Ordering matters — `<=` must be tried before
# `<` so the two-character operator isn't split.
_UPPER_BOUND = re.compile(r"(?P<operator><=|<|==)\s*(?P<version>[0-9][0-9A-Za-z.*+!\-]*)")


@dataclass(frozen=True)
class UpperBound:
    operator: str
    version: str

    @property
    def inclusive(self) -> bool:
        return self.operator in {"<=", "=="}


def parse_release(version: str) -> tuple[int, ...]:
    """Return the numeric release segment of a version string.

    Parsing stops at the first non-numeric segment so a pre-release,
    post-release, or wildcard suffix (`7.0rc1`, `2.1.*`) compares as its
    release prefix rather than raising.
    """
    release: list[int] = []
    for segment in version.split("."):
        digits = re.match(r"\d+", segment)
        if digits is None:
            break
        release.append(int(digits.group()))
        if digits.end() != len(segment):
            break
    return tuple(release)


def upper_bound(specifier: str) -> UpperBound | None:
    """Return the ceiling a requirement specifier declares, if any.

    The environment marker (everything after `;`) is stripped first — a
    marker's `<` constrains the interpreter, not the distribution.
    """
    version_part = specifier.split(";", 1)[0]
    tightest: UpperBound | None = None
    for match in _UPPER_BOUND.finditer(version_part):
        candidate = UpperBound(operator=match.group("operator"), version=match.group("version"))
        if tightest is None or _is_tighter(candidate=candidate, current=tightest):
            tightest = candidate
    return tightest


def _is_tighter(*, candidate: UpperBound, current: UpperBound) -> bool:
    candidate_release = parse_release(candidate.version)
    current_release = parse_release(current.version)
    if candidate_release != current_release:
        return candidate_release < current_release
    # Same release: the exclusive form admits strictly less.
    return not candidate.inclusive and current.inclusive


def exceeds_bound(*, latest: str, bound: UpperBound) -> bool:
    """True when the index's current version is outside the declared ceiling."""
    latest_release = parse_release(latest)
    bound_release = parse_release(bound.version)
    if not latest_release or not bound_release:
        return False
    width = max(len(latest_release), len(bound_release))
    padded_latest = latest_release + (0,) * (width - len(latest_release))
    padded_bound = bound_release + (0,) * (width - len(bound_release))
    if bound.inclusive:
        return padded_latest > padded_bound
    return padded_latest >= padded_bound


def fetch_latest_version(
    distribution: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Result[str]:
    """Read a distribution's current stable version from the PyPI JSON API."""
    url = PYPI_JSON_URL.format(distribution=distribution)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed https PyPI host
            request,
            timeout=timeout,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        return err(f"PyPI returned HTTP {ex.code} for {distribution}")
    except (urllib.error.URLError, TimeoutError) as ex:
        return err(f"PyPI request failed for {distribution}: {ex}")
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        return err(f"PyPI returned an unreadable payload for {distribution}: {ex}")

    version = payload.get("info", {}).get("version")
    if not version:
        return err(f"PyPI payload for {distribution} carries no info.version")
    return ok(str(version))


def _group_pins(pins: list[PinnedRequirement]) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for pin in pins:
        grouped.setdefault((pin.distribution, pin.specifier), []).append(pin.source)
    return {key: sorted(set(sources)) for key, sources in grouped.items()}


def sweep(
    *,
    root: Path,
    fetch: Callable[[str], Result[str]] = fetch_latest_version,
) -> Result[dict[str, Any]]:
    """Report every pinned requirement whose current index version is out of bounds.

    `fetch` is the network seam — tests inject a stub so the sweep never
    reaches PyPI.
    """
    if not root.is_dir():
        return err(f"Sweep root is not a directory: {root}")

    grouped = _group_pins(collect_pinned_requirements(root))
    latest_by_distribution: dict[str, str] = {}
    stale: list[dict[str, Any]] = []
    errors: list[str] = []

    for (distribution, specifier), sources in sorted(grouped.items()):
        bound = upper_bound(specifier)
        if bound is None:
            # collect_pinned_requirements only yields bounded requirements,
            # so a specifier with no parseable ceiling means the two modules
            # disagree — surface it instead of dropping it silently.
            errors.append(f"No parseable upper bound in {distribution}{specifier}")
            continue
        if distribution not in latest_by_distribution:
            result = fetch(distribution)
            if not isinstance(result, SuccessResult):
                errors.append(result.error)
                continue
            latest_by_distribution[distribution] = result.value
        latest = latest_by_distribution[distribution]
        if exceeds_bound(latest=latest, bound=bound):
            stale.append(
                {
                    "distribution": distribution,
                    "specifier": specifier,
                    "bound": f"{bound.operator}{bound.version}",
                    "latest": latest,
                    "sources": sources,
                }
            )

    _logger.info(
        "Dependency sweep checked %d pins across %d distributions; %d stale",
        len(grouped),
        len(latest_by_distribution),
        len(stale),
    )
    return ok(
        {
            "pins": len(grouped),
            "distributions": len(latest_by_distribution),
            "stale": stale,
            "errors": errors,
        }
    )


def format_report(report: dict[str, Any]) -> str:
    """Render a sweep report as Markdown (reused verbatim as an issue body)."""
    lines = [
        f"Checked {report['pins']} pinned requirement(s) "
        f"across {report['distributions']} distribution(s).",
        "",
    ]
    stale: list[dict[str, Any]] = report["stale"]
    if not stale:
        lines.append("✅ No pinned dependency has a release outside its declared bound.")
    else:
        lines.append(f"### {len(stale)} pin(s) with a newer release outside the bound")
        lines.append("")
        for entry in stale:
            lines.append(
                f"- **{entry['distribution']}** `{entry['specifier']}` "
                f"— latest is `{entry['latest']}`, bound is `{entry['bound']}`"
            )
            for source in entry["sources"]:
                lines.append(f"  - `{source}`")
    if report["errors"]:
        lines.extend(["", "### Lookup errors", ""])
        lines.extend(f"- {error}" for error in report["errors"])
    return "\n".join(lines)
