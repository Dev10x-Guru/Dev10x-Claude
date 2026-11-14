from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult

from dev10x.comm.skills.notifications.gchat_users import (
    BusRole,
    ChatUser,
    chat_user_name,
    load_chat_users,
    parse_chat_users,
)


class TestChatUserName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("123", "users/123"),
            (123, "users/123"),
            (" 123 ", "users/123"),
            ("users/123", "users/123"),
            ("users/abc", None),
            ("²", None),
            ("users/١٢", None),
            ("abc", None),
            ("", None),
            (None, None),
            (True, None),
            (1.5, None),
        ],
    )
    def test_normalizes(self, raw: object, expected: str | None) -> None:
        assert chat_user_name(raw=raw) == expected


class TestParseChatUsers:
    def test_reads_roles(self) -> None:
        config = {
            "users": {
                "boss": {"chat_user_id": "1", "bus_role": "owner", "name": "Boss"},
                "helper": {"chat_user_id": 2, "bus_role": "trusted"},
                "reviewer": {"chat_user_id": "3"},
            }
        }
        assert parse_chat_users(config=config) == (
            ChatUser(login="boss", chat_user="users/1", bus_role=BusRole.OWNER),
            ChatUser(login="helper", chat_user="users/2", bus_role=BusRole.TRUSTED),
            ChatUser(login="reviewer", chat_user="users/3", bus_role=None),
        )

    @pytest.mark.parametrize("role", ["Owner", "OWNER", "admin", " owner", "", 1, True, ["owner"]])
    def test_invalid_role_fails_closed(self, role: Any) -> None:
        config = {"users": {"x": {"chat_user_id": "1", "bus_role": role}}}
        assert parse_chat_users(config=config)[0].bus_role is None

    def test_role_without_chat_id_fails_closed(self) -> None:
        config = {"users": {"x": {"chat_user_id": "not-an-id", "bus_role": "owner"}}}
        assert parse_chat_users(config=config) == (
            ChatUser(login="x", chat_user=None, bus_role=None),
        )

    def test_non_mapping_entry_fails_closed(self) -> None:
        assert parse_chat_users(config={"users": {"x": "owner"}}) == (
            ChatUser(login="x", chat_user=None, bus_role=None),
        )

    @pytest.mark.parametrize("users", [None, ["owner"], "owner"])
    def test_no_users_mapping(self, users: object) -> None:
        assert parse_chat_users(config={"users": users}) == ()

    def test_missing_users_key(self) -> None:
        assert parse_chat_users(config={}) == ()


class TestLoadChatUsers:
    @pytest.fixture
    def path(self, tmp_path: Path) -> Path:
        return tmp_path / "gchat-config.yaml"

    def test_reads_file(self, path: Path) -> None:
        path.write_text("users:\n  boss:\n    chat_user_id: '1'\n    bus_role: owner\n")
        result = load_chat_users(path=path)
        assert isinstance(result, SuccessResult)
        assert result.value == (
            ChatUser(login="boss", chat_user="users/1", bus_role=BusRole.OWNER),
        )

    def test_empty_file(self, path: Path) -> None:
        path.write_text("")
        result = load_chat_users(path=path)
        assert isinstance(result, SuccessResult)
        assert result.value == ()

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            ("users: [unclosed\n", "Cannot read the Google Chat config"),
            ("- a\n- b\n", "is not a mapping"),
        ],
    )
    def test_bad_file(self, path: Path, content: str, message: str) -> None:
        path.write_text(content)
        result = load_chat_users(path=path)
        assert isinstance(result, ErrorResult)
        assert message in result.error

    def test_missing_file(self, path: Path) -> None:
        result = load_chat_users(path=path)
        assert isinstance(result, ErrorResult)
        assert result.details == {"path": str(path)}
