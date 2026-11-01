"""Tests for the dev supervisor checkout preference (GH-1765)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dev10x.comm.supervisor import dev_checkout
from dev10x.comm.supervisor.dev_checkout import DevCheckout, DevCheckoutError


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "Dev10x-Claude"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "Dev10x"\n', encoding="utf-8")
    return root


@pytest.fixture
def store(config_home: Path) -> Path:
    return config_home / "overwatch.yaml"


def _write(*, path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


class TestLoad:
    def test_absent_file_means_no_dev_page(self, store: Path) -> None:
        assert dev_checkout.load_dev_checkout() is None

    @pytest.mark.parametrize(
        "doc",
        [
            {"other": 1},
            {"dev": "not-a-mapping"},
            {"dev": {"port": 9000}},
            {"dev": {"checkout": ""}},
            {"dev": {"checkout": 7}},
        ],
        ids=["no-key", "scalar", "no-checkout", "empty-checkout", "non-string"],
    )
    def test_unusable_entry_means_no_dev_page(self, store: Path, doc: object) -> None:
        _write(path=store, doc=doc)

        assert dev_checkout.load_dev_checkout() is None

    @pytest.mark.parametrize(
        ("port", "expected"),
        [({"port": 9001}, 9001), ({}, 8766)],
        ids=["set", "default"],
    )
    def test_valid_entry(
        self, store: Path, checkout: Path, port: dict[str, object], expected: int
    ) -> None:
        _write(path=store, doc={"dev": {"checkout": str(checkout), **port}})

        assert dev_checkout.load_dev_checkout() == DevCheckout(checkout=checkout, port=expected)

    @pytest.mark.parametrize(
        "port",
        [True, 0, 70000, "x", 8765],
        ids=["bool", "zero", "too-big", "string", "release-port"],
    )
    def test_invalid_port_means_no_dev_page(
        self, store: Path, checkout: Path, port: object
    ) -> None:
        _write(path=store, doc={"dev": {"checkout": str(checkout), "port": port}})

        assert dev_checkout.load_dev_checkout() is None

    @pytest.mark.parametrize(
        "checkout_path",
        ["relative/dx", "/nonexistent/dx"],
        ids=["relative", "missing"],
    )
    def test_invalid_checkout_means_no_dev_page(self, store: Path, checkout_path: str) -> None:
        _write(path=store, doc={"dev": {"checkout": checkout_path}})

        assert dev_checkout.load_dev_checkout() is None


class TestRead:
    def test_absent_file_is_not_an_error(self, store: Path) -> None:
        assert dev_checkout.read_dev_checkout() is None

    def test_no_dev_key_is_not_an_error(self, store: Path) -> None:
        _write(path=store, doc={"other": 1})

        assert dev_checkout.read_dev_checkout() is None

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("dev: [unclosed\n", "not valid YAML"),
            ("- a list\n", "must hold a mapping"),
            ("dev: scalar\n", "`dev` must be a mapping"),
            ("dev:\n  port: 9000\n", "`dev.checkout` must be a path"),
            ("dev:\n  checkout: relative/dx\n", "absolute path"),
        ],
        ids=["bad-yaml", "not-a-mapping", "dev-scalar", "no-checkout", "relative"],
    )
    def test_names_the_problem_and_the_file(self, store: Path, text: str, message: str) -> None:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(text, encoding="utf-8")

        with pytest.raises(DevCheckoutError) as raised:
            dev_checkout.read_dev_checkout()

        assert (message in str(raised.value), str(store) in str(raised.value)) == (True, True)

    def test_unreadable_file(self, store: Path) -> None:
        store.mkdir(parents=True)

        with pytest.raises(DevCheckoutError, match="unreadable"):
            dev_checkout.read_dev_checkout()


class TestPin:
    def test_writes_the_dev_key_and_keeps_others(self, store: Path, checkout: Path) -> None:
        _write(path=store, doc={"other": 1})

        pinned = dev_checkout.pin_dev_checkout(checkout=checkout, port=9002)

        assert (pinned, yaml.safe_load(store.read_text())) == (
            DevCheckout(checkout=checkout, port=9002),
            {"other": 1, "dev": {"checkout": str(checkout), "port": 9002}},
        )

    def test_round_trips_through_load(self, store: Path, checkout: Path) -> None:
        dev_checkout.pin_dev_checkout(checkout=checkout, port=8766)

        assert dev_checkout.load_dev_checkout() == DevCheckout(checkout=checkout, port=8766)


class TestValidate:
    def test_relative_checkout(self) -> None:
        with pytest.raises(DevCheckoutError, match="absolute"):
            dev_checkout.validate_dev_checkout(checkout=Path("dx"), port=8766)

    def test_missing_dir(self, tmp_path: Path) -> None:
        with pytest.raises(DevCheckoutError, match="not a directory"):
            dev_checkout.validate_dev_checkout(checkout=tmp_path / "gone", port=8766)

    def test_no_pyproject(self, tmp_path: Path) -> None:
        with pytest.raises(DevCheckoutError, match="no readable pyproject"):
            dev_checkout.validate_dev_checkout(checkout=tmp_path, port=8766)

    def test_bad_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project", encoding="utf-8")

        with pytest.raises(DevCheckoutError, match="no readable pyproject"):
            dev_checkout.validate_dev_checkout(checkout=tmp_path, port=8766)

    @pytest.mark.parametrize(
        "body",
        [
            '[project]\nname = "other"\n',
            "[project]\nname = 3\n",
            "[tool]\n",
            "project = 1\n",
        ],
        ids=["other-name", "non-string", "no-project", "project-not-a-table"],
    )
    def test_foreign_project(self, tmp_path: Path, body: str) -> None:
        (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")

        with pytest.raises(DevCheckoutError, match="not a Dev10x checkout"):
            dev_checkout.validate_dev_checkout(checkout=tmp_path, port=8766)

    def test_bad_port(self, checkout: Path) -> None:
        with pytest.raises(DevCheckoutError, match="1-65535"):
            dev_checkout.validate_dev_checkout(checkout=checkout, port=0)

    def test_release_port(self, checkout: Path) -> None:
        with pytest.raises(DevCheckoutError, match="release"):
            dev_checkout.validate_dev_checkout(checkout=checkout, port=8765)


class TestUnpin:
    def test_absent_file(self, store: Path) -> None:
        assert (dev_checkout.unpin_dev_checkout(), store.exists()) == (False, False)

    def test_removes_only_the_dev_key(self, store: Path) -> None:
        _write(path=store, doc={"other": 1, "dev": {"checkout": "/w"}})

        assert (dev_checkout.unpin_dev_checkout(), yaml.safe_load(store.read_text())) == (
            True,
            {"other": 1},
        )

    def test_without_dev_key(self, store: Path) -> None:
        _write(path=store, doc={"other": 1})

        assert dev_checkout.unpin_dev_checkout() is False
