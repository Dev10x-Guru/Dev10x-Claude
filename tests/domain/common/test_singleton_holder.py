"""Unit tests for the typed process-level singleton holder (GH-522)."""

from __future__ import annotations

from dev10x.domain.common.singleton_holder import SingletonHolder


class TestSingletonHolder:
    def test_empty_holder_returns_none(self) -> None:
        holder: SingletonHolder[str] = SingletonHolder()
        assert holder.get() is None

    def test_seeded_holder_returns_default(self) -> None:
        holder: SingletonHolder[str] = SingletonHolder(default="seed")
        assert holder.get() == "seed"

    def test_set_replaces_value(self) -> None:
        holder: SingletonHolder[str] = SingletonHolder(default="seed")
        holder.set("replaced")
        assert holder.get() == "replaced"

    def test_set_none_clears_slot(self) -> None:
        holder: SingletonHolder[str] = SingletonHolder(default="seed")
        holder.set(None)
        assert holder.get() is None

    def test_reset_clears_slot(self) -> None:
        holder: SingletonHolder[str] = SingletonHolder(default="seed")
        holder.reset()
        assert holder.get() is None
