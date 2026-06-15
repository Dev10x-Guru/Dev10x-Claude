"""Tests for ConfigLoader Protocol."""

from __future__ import annotations

from pathlib import Path

from dev10x.domain.config_loader import ConfigLoader
from dev10x.domain.documents.config_document import Config


class TestConfigLoaderProtocol:
    def test_protocol_is_importable(self) -> None:
        assert ConfigLoader is not None

    def test_callable_satisfies_protocol(self) -> None:
        def loader(yaml_path: Path, *, ttl_seconds: int = 60) -> Config: ...  # type: ignore[return]

        assert isinstance(loader, ConfigLoader)

    def test_non_callable_does_not_satisfy(self) -> None:
        assert not isinstance(42, ConfigLoader)
        assert not isinstance("string", ConfigLoader)
        assert not isinstance(None, ConfigLoader)

    def test_object_without_call_does_not_satisfy(self) -> None:
        class NotALoader:
            pass

        assert not isinstance(NotALoader(), ConfigLoader)

    def test_class_with_call_satisfies_protocol(self) -> None:
        class MyLoader:
            def __call__(self, yaml_path: Path, *, ttl_seconds: int = 60) -> Config: ...  # type: ignore[return]

        assert isinstance(MyLoader(), ConfigLoader)
