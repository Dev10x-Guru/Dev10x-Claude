"""Knowledge-vault resolution for dev10x:reflect (GH-1822)."""

from __future__ import annotations

from pathlib import Path

import pytest
from dev10x.domain.common.result import ErrorResult, SuccessResult
from dev10x.domain.dev10x_paths import Dev10xConfigDir

from dev10x.tasks.reflect import VaultConfig, confine, resolve_vault_config
from dev10x.tasks.reflect.vault_config import DEFAULT_FOLDERS


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    path.mkdir()
    return path


@pytest.fixture
def config_path() -> Path:
    path = Dev10xConfigDir.knowledge_vault_yaml()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _resolve(*, repo: str | None = "acme/shop", repo_reason: str | None = None) -> VaultConfig:
    result = resolve_vault_config(repo=repo, repo_reason=repo_reason)
    assert isinstance(result, SuccessResult), result
    return result.value


def _error(*, config_path: Path, text: str) -> str:
    config_path.write_text(text, encoding="utf-8")
    result = resolve_vault_config(repo="acme/shop")
    assert isinstance(result, ErrorResult)
    return result.error


class TestUnconfigured:
    def test_missing_file_is_a_skip_not_an_error(self) -> None:
        config = _resolve()

        assert config.configured is False
        assert "does not exist" in config.reason

    @pytest.mark.parametrize("text", ["\n", "# vault: not chosen yet\n"])
    def test_empty_or_comment_only_file_is_a_skip(self, config_path: Path, text: str) -> None:
        config_path.write_text(text, encoding="utf-8")

        assert _resolve().configured is False

    def test_file_without_vault_key_is_a_skip(self, config_path: Path) -> None:
        config_path.write_text("folders:\n  retro: Retros\n", encoding="utf-8")

        config = _resolve()

        assert config.configured is False
        assert "no `vault:`" in config.reason

    def test_project_can_opt_out(self, config_path: Path, vault: Path) -> None:
        config_path.write_text(
            f"vault: {vault}\nprojects:\n  - match_repo: acme/*\n    enabled: false\n",
            encoding="utf-8",
        )

        config = _resolve()

        assert config.configured is False
        assert config.project_status == "matched"


class TestConfigured:
    def test_defaults_apply_when_only_vault_is_set(self, config_path: Path, vault: Path) -> None:
        config_path.write_text(f"vault: {vault}\n", encoding="utf-8")

        config = _resolve()

        assert config.configured is True
        assert config.vault == vault
        assert config.folders == DEFAULT_FOLDERS
        assert (config.index_note, config.log_note) == ("index.md", "log.md")
        assert config.rules_note is None

    def test_matching_project_overrides_folders_key_by_key(
        self, config_path: Path, vault: Path
    ) -> None:
        config_path.write_text(
            f"vault: {vault}\n"
            "folders:\n  retro: Retros\n  process: Team\n"
            "projects:\n"
            "  - match_repo: other/*\n    folders:\n      retro: Other\n"
            "  - match_repo: acme/*\n    folders:\n      retro: Clients/Acme\n",
            encoding="utf-8",
        )

        config = _resolve()

        assert config.folders["retro"] == "Clients/Acme"
        assert config.folders["process"] == "Team"
        assert config.project_status == "matched"

    def test_unresolved_repo_keeps_top_level_defaults(
        self, config_path: Path, vault: Path
    ) -> None:
        config_path.write_text(
            f"vault: {vault}\nprojects:\n  - match_repo: acme/*\n    enabled: false\n",
            encoding="utf-8",
        )

        config = _resolve(repo=None, repo_reason="no origin")

        assert config.configured is True
        assert config.project_status == "unresolved"

    def test_home_relative_vault_is_expanded(
        self, config_path: Path, vault: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(vault.parent))
        config_path.write_text("vault: ~/vault\n", encoding="utf-8")

        assert _resolve().vault == vault

    def test_rules_note_resolves_inside_vault(self, config_path: Path, vault: Path) -> None:
        config_path.write_text(f"vault: {vault}\nrules_note: meta/rules.md\n", encoding="utf-8")

        assert _resolve().rules_note == vault / "meta" / "rules.md"

    def test_to_dict_is_json_ready(self, config_path: Path, vault: Path) -> None:
        config_path.write_text(f"vault: {vault}\n", encoding="utf-8")

        payload = _resolve().to_dict()

        assert payload["vault"] == str(vault)
        assert payload["configured"] is True
        assert payload["repo"] == "acme/shop"
        assert payload["log_folders"] == DEFAULT_FOLDERS


class TestLogFolders:
    def test_each_kind_logs_in_its_own_folder_by_default(
        self, config_path: Path, vault: Path
    ) -> None:
        config_path.write_text(f"vault: {vault}\n", encoding="utf-8")

        assert _resolve().log_folder(kind="retro") == "Retros"

    def test_kind_can_log_in_a_parent_folder(self, config_path: Path, vault: Path) -> None:
        config_path.write_text(
            f"vault: {vault}\n"
            "folders:\n  retro: Project/Retros\n"
            "log_folders:\n  retro: Project/\n",
            encoding="utf-8",
        )

        config = _resolve()

        assert config.log_folder(kind="retro") == "Project"
        assert config.to_dict()["log_folders"]["patterns"] == "Patterns"

    def test_project_entry_merges_log_folders_key_by_key(
        self, config_path: Path, vault: Path
    ) -> None:
        config_path.write_text(
            f"vault: {vault}\n"
            "log_folders:\n  retro: Eng\n  patterns: Shared\n"
            "projects:\n  - match_repo: acme/*\n    log_folders:\n      retro: Acme\n",
            encoding="utf-8",
        )

        config = _resolve()

        assert (config.log_folder(kind="retro"), config.log_folder(kind="patterns")) == (
            "Acme",
            "Shared",
        )

    @pytest.mark.parametrize(
        ("entry_log_folders", "kind", "expected"),
        [
            pytest.param("", "retro", "Clients/Acme/Retros", id="moved-kind-drops-inherited"),
            pytest.param("", "patterns", "Shared", id="untouched-kind-keeps-inherited"),
            pytest.param(
                "    log_folders:\n      retro: Clients/Acme\n",
                "retro",
                "Clients/Acme",
                id="moved-kind-keeps-its-own",
            ),
        ],
    )
    def test_project_that_moves_a_folder(
        self,
        config_path: Path,
        vault: Path,
        entry_log_folders: str,
        kind: str,
        expected: str,
    ) -> None:
        config_path.write_text(
            f"vault: {vault}\n"
            "log_folders:\n  retro: Eng\n  patterns: Shared\n"
            "projects:\n  - match_repo: acme/*\n"
            "    folders:\n      retro: Clients/Acme/Retros\n" + entry_log_folders,
            encoding="utf-8",
        )

        assert _resolve().log_folder(kind=kind) == expected

    def test_unknown_kind_has_no_log_folder(self, config_path: Path, vault: Path) -> None:
        config_path.write_text(f"vault: {vault}\n", encoding="utf-8")

        assert _resolve().log_folder(kind="nonexistent") == ""


class TestInvalid:
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("vault: relative/dir\n", "must be absolute"),
            ("vault: [a, b]\n", "must be a path string"),
            ("vault: /definitely/not/here\n", "does not exist"),
        ],
    )
    def test_bad_vault(self, config_path: Path, text: str, message: str) -> None:
        assert message in _error(config_path=config_path, text=text)

    @pytest.mark.parametrize(
        ("suffix", "message"),
        [
            ("folders: [a]\n", "must be a mapping"),
            ("folders:\n  retro: ''\n", "non-empty"),
            ("folders:\n  retro: ../outside\n", "must not contain '..'"),
            ("folders:\n  retro: /etc\n", "not absolute"),
            ("index_note: sub/index.md\n", "bare Markdown file name"),
            ("log_note: log.txt\n", "bare Markdown file name"),
            ("rules_note: ../rules.md\n", "rules_note"),
            ("log_folders: [a]\n", "`log_folders:` must be a mapping"),
            ("log_folders:\n  retro: ../up\n", "`log_folders.retro`"),
            ("folders:\n  retro: ' ../up'\n", "must not contain '..'"),
            ("log_folders:\n  retro: '.. '\n", "must not contain '..'"),
        ],
    )
    def test_bad_keys(self, config_path: Path, vault: Path, suffix: str, message: str) -> None:
        assert message in _error(config_path=config_path, text=f"vault: {vault}\n{suffix}")

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("vault: [unclosed\n", "cannot parse"),
            ("- just\n- a list\n", "must be a mapping"),
        ],
    )
    def test_unparseable_file_is_an_error_not_a_skip(
        self, config_path: Path, text: str, message: str
    ) -> None:
        assert message in _error(config_path=config_path, text=text)

    def test_undecodable_file_is_an_error(self, config_path: Path) -> None:
        config_path.write_bytes(b"vault: \xff\xfe\n")

        result = resolve_vault_config(repo="acme/shop")

        assert isinstance(result, ErrorResult)
        assert "cannot read" in result.error


class TestConfine:
    def test_nested_folder_is_allowed(self, vault: Path) -> None:
        result = confine(vault=vault, relative="a/b")

        assert isinstance(result, SuccessResult)
        assert result.value == vault / "a" / "b"

    def test_symlink_escape_is_refused(self, vault: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (vault / "link").symlink_to(outside)

        result = confine(vault=vault, relative="link")

        assert isinstance(result, ErrorResult)
        assert "outside the vault" in result.error
