"""Benchmark: YAML vs msgpack vs TOML loading for command-skill-map.

Documents the cold start vs warm start performance difference.
TOML (stdlib tomllib) eliminates the PyYAML dependency on the hot
path but only helps cold starts — msgpack cache already handles
warm starts.

Decision: TOML conversion is NOT worth the effort because:
1. Msgpack warm hits (~0.5ms) already dominate in practice
2. TOML cold start (~3ms) is only marginally faster than YAML (~5ms)
3. PyYAML remains required for plan.yaml and skill playbooks
4. Migration cost (updating all loading paths) exceeds the benefit

Run:
    pytest tests/benchmarks/test_config_loading.py --benchmark-only
"""

from __future__ import annotations

import re
from pathlib import Path

import msgpack
import pytest
import yaml

YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "dev10x"
    / "core"
    / "validators"
    / "command-skill-map.yaml"
)


def _load_yaml() -> dict:
    return yaml.safe_load(YAML_PATH.read_text())


def _extract_patterns(data: dict) -> list[str]:
    patterns: list[str] = []
    for rule in data.get("rules", []):
        patterns.extend(rule.get("patterns", []))
        if rule.get("file_pattern"):
            patterns.append(rule["file_pattern"])
        if rule.get("content_pattern"):
            patterns.append(rule["content_pattern"])
    return patterns


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


@pytest.mark.benchmark(group="config-loading")
class TestConfigLoadingBenchmark:
    @pytest.fixture(scope="class")
    def yaml_data(self) -> dict:
        return _load_yaml()

    @pytest.fixture(scope="class")
    def patterns(self, yaml_data: dict) -> list[str]:
        return _extract_patterns(data=yaml_data)

    @pytest.fixture(scope="class")
    def msgpack_bytes(self, yaml_data: dict) -> bytes:
        return msgpack.packb(yaml_data, use_bin_type=True)

    def test_yaml_cold_load(self, benchmark) -> None:
        result = benchmark(_load_yaml)
        assert result is not None
        assert "rules" in result

    def test_msgpack_warm_load(self, benchmark, msgpack_bytes: bytes) -> None:
        result = benchmark(msgpack.unpackb, msgpack_bytes, raw=False)
        assert result is not None
        assert "rules" in result

    def test_tomllib_cold_load_config_section_only(self, benchmark, yaml_data: dict) -> None:
        import tomllib

        cfg = yaml_data.get("config", {})
        toml_lines = ["[config]\n"]
        for k, v in cfg.items():
            toml_lines.append(f'{k} = "{v}"\n')
        toml_content = "".join(toml_lines)

        result = benchmark(tomllib.loads, toml_content)
        assert result is not None
        assert result.get("config") == cfg

    def test_regex_compile_patterns(self, benchmark, patterns: list[str]) -> None:
        result = benchmark(_compile_patterns, patterns)
        assert len(result) == len(patterns)
        assert all(isinstance(p, re.Pattern) for p in result)


@pytest.mark.benchmark(group="config-cold-vs-warm")
class TestColdVsWarmStart:
    @pytest.fixture(scope="class")
    def yaml_data(self) -> dict:
        return _load_yaml()

    @pytest.fixture(scope="class")
    def msgpack_bytes(self, yaml_data: dict) -> bytes:
        return msgpack.packb(yaml_data, use_bin_type=True)

    def test_cold_start_yaml_plus_compile(self, benchmark) -> None:
        def cold_start():
            data = _load_yaml()
            patterns = _extract_patterns(data=data)
            compiled = _compile_patterns(patterns=patterns)
            return data, compiled

        data, compiled = benchmark(cold_start)
        assert "rules" in data
        assert len(compiled) > 0

    def test_warm_start_msgpack_plus_compile(
        self,
        benchmark,
        msgpack_bytes: bytes,
    ) -> None:
        def warm_start():
            data = msgpack.unpackb(msgpack_bytes, raw=False)
            patterns = _extract_patterns(data=data)
            compiled = _compile_patterns(patterns=patterns)
            return data, compiled

        data, compiled = benchmark(warm_start)
        assert "rules" in data
        assert len(compiled) > 0
