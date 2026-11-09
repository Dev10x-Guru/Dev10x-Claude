from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
_PROBE_TIMEOUT_SECONDS = 30
_IMPORT_PROBE = """
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
before = set(sys.modules)
importlib.import_module(sys.argv[2])
loaded = {name.split(".")[0] for name in set(sys.modules) - before}
print(json.dumps(sorted(loaded - set(sys.stdlib_module_names) - {"dev10x"})))
"""


@pytest.fixture(scope="module")
def third_party_imports() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-I", "-c", _IMPORT_PROBE, str(_SRC_ROOT), "dev10x.core.fixes_trailer"],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_SECONDS,
        check=True,
    )
    return json.loads(completed.stdout)


class TestStdlibOnly:
    def test_close_issues_shim_can_import_the_grammar_without_dependencies(
        self,
        third_party_imports: list[str],
    ) -> None:
        assert third_party_imports == []
