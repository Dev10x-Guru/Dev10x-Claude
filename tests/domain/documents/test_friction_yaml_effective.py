"""FrictionYamlDocument.effective — defaults layered under the first match."""

from __future__ import annotations

import pytest
from dev10x.domain.dev10x_paths import Dev10xConfigDir
from dev10x.domain.documents.friction_yaml import FrictionYamlDocument

FRICTION_YAML = (
    "defaults:\n"
    "  tracker: linear\n"
    "  ide: none\n"
    "projects:\n"
    "  - match: ['*/feature-x']\n"
    "    tracker: jira\n"
    "  - match: ['*/repo']\n"
    "    tracker: github\n"
)


@pytest.fixture(autouse=True)
def friction_yaml() -> None:
    path = Dev10xConfigDir.friction_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FRICTION_YAML)


@pytest.mark.parametrize(
    ("toplevel", "fallbacks", "expected"),
    [
        ("/work/feature-x", (), {"tracker": "jira", "ide": "none"}),
        ("/work/wt/unrelated", ("/work/repo",), {"tracker": "github", "ide": "none"}),
        ("/work/feature-x", ("/work/repo",), {"tracker": "jira", "ide": "none"}),
        ("/work/other", ("/work/also-other",), {"tracker": "linear", "ide": "none"}),
    ],
)
def test_effective_layers_defaults_under_the_first_matching_probe(
    toplevel: str, fallbacks: tuple[str, ...], expected: dict[str, str]
) -> None:
    document = FrictionYamlDocument(toplevel=toplevel)

    assert document.effective(fallback_toplevels=fallbacks) == expected
