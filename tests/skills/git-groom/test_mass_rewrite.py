"""Tests for mass-rewrite.py SHA normalization (GH-646)."""

import importlib.util
from pathlib import Path

_repo_root = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "mass_rewrite",
    _repo_root / "skills" / "git-groom" / "scripts" / "mass-rewrite.py",
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

normalize_config_shas = _mod.normalize_config_shas


class _Result:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class TestNormalizeConfigShas:
    def test_full_sha_rekeyed_to_short(self, monkeypatch):
        full = "1ca6654ec45a0d043586c4d43891b4e9c6f5b50e"
        monkeypatch.setattr(_mod, "run", lambda *a, **k: _Result(0, full + "\n"))
        result = normalize_config_shas({full: "New message"})
        assert result == {"1ca6654": "New message"}

    def test_short_sha_passthrough(self, monkeypatch):
        monkeypatch.setattr(_mod, "run", lambda *a, **k: _Result(0, "1ca6654ec45a0d04\n"))
        result = normalize_config_shas({"1ca6654": "msg"})
        assert result == {"1ca6654": "msg"}

    def test_unresolvable_key_preserved(self, monkeypatch):
        monkeypatch.setattr(_mod, "run", lambda *a, **k: _Result(1, ""))
        result = normalize_config_shas({"deadbeef": "msg"})
        assert result == {"deadbeef": "msg"}

    def test_dict_spec_value_preserved(self, monkeypatch):
        full = "d8eac5186ec9e1074ea58ede72a87ac4a1c3ca9f"
        spec = {"message": "msg", "renames": [["a", "b"]]}
        monkeypatch.setattr(_mod, "run", lambda *a, **k: _Result(0, full))
        result = normalize_config_shas({full: spec})
        assert result == {"d8eac51": spec}
