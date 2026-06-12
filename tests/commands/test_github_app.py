"""Tests for `dev10x github-app` setup wizard."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dev10x.commands import github_app as gha
from dev10x.commands.github_app import InstallationInfo, VerificationResult


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(gha, "CONFIG_DIR", tmp_path / "github-bot")
    monkeypatch.setattr(gha, "CONFIG_PATH", tmp_path / "github-bot" / "github-app.yaml")
    monkeypatch.setattr(gha, "KEY_PATH", tmp_path / "github-bot" / "dev10x-bot.pem")
    return tmp_path


@pytest.fixture
def fake_pem(tmp_path: Path) -> Path:
    pem = tmp_path / "downloads" / "dev10x-bot.2026-05-07.private-key.pem"
    pem.parent.mkdir(parents=True)
    pem.write_text("-----BEGIN RSA PRIVATE KEY-----\nFAKEKEY\n-----END RSA PRIVATE KEY-----\n")
    return pem


@pytest.fixture
def successful_verification() -> VerificationResult:
    return VerificationResult(
        success=True,
        app_slug="dev10x-bot",
        app_id=12345,
        installations=[
            InstallationInfo(
                id=99,
                account="Dev10x-Guru",
                verified_repo="Dev10x-Guru/Dev10x-Claude",
            ),
        ],
    )


class TestSetupInstallTargetPersonal:
    """Personal account → personal registration URL + 'Any account' hint."""

    @pytest.fixture
    def stdin_input(self, fake_pem: Path) -> str:
        # click.pause is a no-op when stdin is not a TTY, so only the
        # actual click.prompt calls consume input.
        return "\n".join(["1", "12345", str(fake_pem)]) + "\n"

    @pytest.fixture
    def result(
        self,
        fake_home: Path,
        stdin_input: str,
        successful_verification: VerificationResult,
    ) -> object:
        runner = CliRunner()
        with (
            patch.object(gha, "_validate_key_locally", return_value=None),
            patch.object(gha, "_verify_setup", return_value=successful_verification),
        ):
            return runner.invoke(gha.github_app, ["setup"], input=stdin_input)

    def test_exits_successfully(self, result: object) -> None:
        assert result.exit_code == 0, result.output

    def test_uses_personal_url(self, result: object) -> None:
        assert "https://github.com/settings/apps/new" in result.output

    def test_steers_to_any_account(self, result: object) -> None:
        assert '"Any account"' in result.output

    def test_writes_config_file(self, result: object, fake_home: Path) -> None:
        assert (fake_home / "github-bot" / "github-app.yaml").is_file()

    def test_omits_installation_id(self, result: object, fake_home: Path) -> None:
        config = (fake_home / "github-bot" / "github-app.yaml").read_text()
        assert "installation_id:" not in config

    def test_moves_pem_to_key_path(self, result: object, fake_home: Path, fake_pem: Path) -> None:
        assert (fake_home / "github-bot" / "dev10x-bot.pem").is_file()
        assert not fake_pem.exists()

    def test_key_file_has_600_perms(self, result: object, fake_home: Path) -> None:
        key_path = fake_home / "github-bot" / "dev10x-bot.pem"
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


class TestSetupInstallTargetOrg:
    """Org → org-specific registration URL."""

    @pytest.fixture
    def stdin_input(self, fake_pem: Path) -> str:
        return "\n".join(["2", "tiretutorinc", "12345", str(fake_pem)]) + "\n"

    def test_uses_org_url(
        self,
        fake_home: Path,
        stdin_input: str,
        successful_verification: VerificationResult,
    ) -> None:
        runner = CliRunner()
        with (
            patch.object(gha, "_validate_key_locally", return_value=None),
            patch.object(gha, "_verify_setup", return_value=successful_verification),
        ):
            result = runner.invoke(gha.github_app, ["setup"], input=stdin_input)

        assert result.exit_code == 0, result.output
        assert "https://github.com/organizations/tiretutorinc/settings/apps/new" in result.output


class TestSetupVerificationFailures:
    """Verification failures must abort BEFORE writing config."""

    def _run(
        self,
        fake_home: Path,
        fake_pem: Path,
        verification: VerificationResult,
    ) -> object:
        stdin_input = "\n".join(["1", "12345", str(fake_pem)]) + "\n"
        runner = CliRunner()
        with (
            patch.object(gha, "_validate_key_locally", return_value=None),
            patch.object(gha, "_verify_setup", return_value=verification),
        ):
            return runner.invoke(gha.github_app, ["setup"], input=stdin_input)

    def test_aborts_on_app_id_mismatch(self, fake_home: Path, fake_pem: Path) -> None:
        result = self._run(
            fake_home,
            fake_pem,
            VerificationResult(success=False, error="App ID mismatch: belongs to App 99"),
        )
        assert result.exit_code == 1
        assert "App ID mismatch" in result.output
        assert not (fake_home / "github-bot" / "github-app.yaml").exists()

    def test_aborts_on_no_installations(self, fake_home: Path, fake_pem: Path) -> None:
        result = self._run(
            fake_home,
            fake_pem,
            VerificationResult(success=False, error="App has no installations."),
        )
        assert result.exit_code == 1
        assert "no installations" in result.output
        assert not (fake_home / "github-bot" / "github-app.yaml").exists()

    def test_aborts_on_repo_read_failure(self, fake_home: Path, fake_pem: Path) -> None:
        result = self._run(
            fake_home,
            fake_pem,
            VerificationResult(success=False, error="All installations failed: 404 Not Found"),
        )
        assert result.exit_code == 1
        assert "failed" in result.output.lower()
        assert not (fake_home / "github-bot" / "github-app.yaml").exists()

    def test_pem_not_moved_on_failure(self, fake_home: Path, fake_pem: Path) -> None:
        self._run(
            fake_home,
            fake_pem,
            VerificationResult(success=False, error="boom"),
        )
        assert fake_pem.exists()


class TestSetupLocalKeyValidationFailure:
    def test_aborts_when_key_invalid(self, fake_home: Path, fake_pem: Path) -> None:
        stdin_input = "\n".join(["1", "12345", str(fake_pem)]) + "\n"
        runner = CliRunner()
        with patch.object(gha, "_validate_key_locally", return_value="bad signature"):
            result = runner.invoke(gha.github_app, ["setup"], input=stdin_input)

        assert result.exit_code == 1
        assert "bad signature" in result.output
        assert not (fake_home / "github-bot" / "github-app.yaml").exists()


class TestSetupPasteFlow:
    """--paste keeps the legacy paste flow for headless setups."""

    def test_paste_flag_writes_key_text(
        self,
        fake_home: Path,
        successful_verification: VerificationResult,
    ) -> None:
        fake_key_lines = [
            "-----BEGIN RSA PRIVATE KEY-----",
            "FAKEKEY",
            "-----END RSA PRIVATE KEY-----",
        ]
        # install_target=1, pause, pause, app_id, paste lines, blank
        stdin_input = "\n".join(["1", "12345", *fake_key_lines, ""]) + "\n"
        runner = CliRunner()
        with (
            patch.object(gha, "_validate_key_locally", return_value=None),
            patch.object(gha, "_verify_setup", return_value=successful_verification),
        ):
            result = runner.invoke(gha.github_app, ["setup", "--paste"], input=stdin_input)

        assert result.exit_code == 0, result.output
        key_path = fake_home / "github-bot" / "dev10x-bot.pem"
        assert key_path.is_file()
        assert "BEGIN RSA PRIVATE KEY" in key_path.read_text()


class TestAtomicCredentialWrites:
    """Credential files are written atomically, then locked down to 600."""

    def test_write_key_text_uses_atomic_write(self, fake_home: Path) -> None:
        gha.CONFIG_DIR.mkdir(parents=True)
        with (
            patch.object(gha, "atomic_write_text") as atomic,
            patch.object(gha.os, "chmod") as chmod,
        ):
            gha._write_key_text(private_key="SECRET")

        atomic.assert_called_once_with(gha.KEY_PATH, "SECRET")
        chmod.assert_called_once_with(gha.KEY_PATH, 0o600)

    def test_write_config_uses_atomic_write(self, fake_home: Path) -> None:
        gha.CONFIG_DIR.mkdir(parents=True)
        expected = (
            f'github_app:\n  app_id: "42"\n  private_key_path: "{gha.KEY_PATH}"\n  enabled: true\n'
        )
        with (
            patch.object(gha, "atomic_write_text") as atomic,
            patch.object(gha.os, "chmod") as chmod,
        ):
            gha._write_config(app_id="42")

        atomic.assert_called_once_with(gha.CONFIG_PATH, expected)
        chmod.assert_called_once_with(gha.CONFIG_PATH, 0o600)


class TestSetupRejectsExistingWithoutForce:
    def test_aborts_when_config_exists_and_no_confirm(
        self,
        fake_home: Path,
    ) -> None:
        gha.CONFIG_DIR.mkdir(parents=True)
        gha.CONFIG_PATH.write_text("github_app:\n  app_id: '0'\n")

        runner = CliRunner()
        result = runner.invoke(gha.github_app, ["setup"], input="\nN\n")

        assert result.exit_code == 1


class TestPromptInstallTarget:
    def test_personal_choice(self) -> None:
        runner = CliRunner()
        with runner.isolation(input="1\n"):
            target = gha._prompt_install_target()
        assert target == gha.InstallTarget(kind="personal")

    def test_org_choice(self) -> None:
        runner = CliRunner()
        with runner.isolation(input="2\nDev10x-Guru\n"):
            target = gha._prompt_install_target()
        assert target == gha.InstallTarget(kind="org", org="Dev10x-Guru")

    def test_manual_choice(self) -> None:
        runner = CliRunner()
        with runner.isolation(input="3\n"):
            target = gha._prompt_install_target()
        assert target == gha.InstallTarget(kind="manual")

    def test_retries_on_invalid_choice(self) -> None:
        runner = CliRunner()
        with runner.isolation(input="9\n1\n"):
            target = gha._prompt_install_target()
        assert target == gha.InstallTarget(kind="personal")

    def test_retries_on_empty_org(self) -> None:
        runner = CliRunner()
        with runner.isolation(input="2\n\nDev10x-Guru\n"):
            target = gha._prompt_install_target()
        assert target == gha.InstallTarget(kind="org", org="Dev10x-Guru")


class TestPromptPrivateKeyPath:
    def test_retries_when_path_does_not_exist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")
        valid = tmp_path / "key.pem"
        valid.write_text("KEY")

        runner = CliRunner()
        with runner.isolation(input=f"/no/such/file\n{valid}\n"):
            result = gha._prompt_private_key_path()

        assert result == valid

    def test_rejects_blank_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")
        valid = tmp_path / "key.pem"
        valid.write_text("KEY")

        runner = CliRunner()
        with runner.isolation(input=f"\n{valid}\n"):
            result = gha._prompt_private_key_path()

        assert result == valid


class TestVerifySetupApiErrors:
    def test_get_app_failure_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gha.api, "mint_app_jwt", lambda **_: "JWT")

        def boom(**_: object) -> dict:
            raise gha.api.GitHubAPIError("401 Unauthorized")

        monkeypatch.setattr(gha.api, "get_app", boom)

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is False
        assert "GET /app failed" in (result.error or "")

    def test_list_installations_failure_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gha.api, "mint_app_jwt", lambda **_: "JWT")
        monkeypatch.setattr(gha.api, "get_app", lambda **_: {"id": 12345, "slug": "ok"})

        def boom(**_: object) -> list:
            raise gha.api.GitHubAPIError("500")

        monkeypatch.setattr(gha.api, "list_installations", boom)

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is False
        assert "/app/installations" in (result.error or "")

    def test_jwt_minting_failure_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(**_: object) -> str:
            raise ValueError("malformed key")

        monkeypatch.setattr(gha.api, "mint_app_jwt", boom)

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is False
        assert "Could not mint JWT" in (result.error or "")


class TestRegistrationUrl:
    def test_personal(self) -> None:
        assert gha.InstallTarget(kind="personal").registration_url == gha.PERSONAL_NEW_APP_URL

    def test_org(self) -> None:
        url = gha.InstallTarget(kind="org", org="tiretutorinc").registration_url
        assert url == "https://github.com/organizations/tiretutorinc/settings/apps/new"

    def test_manual_returns_placeholder(self) -> None:
        url = gha.InstallTarget(kind="manual").registration_url
        assert "yourself" in url


class TestInstallScopeHint:
    def test_personal_steers_to_any_account(self) -> None:
        hint = gha.InstallTarget(kind="personal").install_scope_hint
        assert '"Any account"' in hint

    def test_org_explains_implicit_scope(self) -> None:
        hint = gha.InstallTarget(kind="org", org="x").install_scope_hint
        assert "owned by the org" in hint

    def test_manual_covers_both(self) -> None:
        hint = gha.InstallTarget(kind="manual").install_scope_hint
        assert "Any account" in hint


class TestNewestPemInDownloads:
    def test_returns_none_when_no_downloads_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert gha._newest_pem_in_downloads() is None

    def test_returns_newest_pem(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        old = downloads / "old.private-key.pem"
        new = downloads / "new.private-key.pem"
        old.write_text("old")
        new.write_text("new")
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))

        assert gha._newest_pem_in_downloads() == new

    def test_ignores_non_private_key_pems(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        (downloads / "cert.pem").write_text("not-a-key")
        assert gha._newest_pem_in_downloads() is None


class TestStatus:
    def test_reports_missing_config(self, fake_home: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(gha.github_app, ["status"])

        assert result.exit_code == 1
        assert "No config" in result.output

    def test_reports_present_config(self, fake_home: Path) -> None:
        gha.CONFIG_DIR.mkdir(parents=True)
        gha.CONFIG_PATH.write_text("github_app:\n  app_id: '0'\n")
        gha.KEY_PATH.write_text("KEY")
        os.chmod(gha.KEY_PATH, 0o600)

        runner = CliRunner()
        result = runner.invoke(gha.github_app, ["status"])

        assert result.exit_code == 0
        assert str(gha.CONFIG_PATH) in result.output


class TestVerifySetup:
    """Unit-level coverage of the verification orchestrator."""

    def test_app_id_mismatch_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gha.api, "mint_app_jwt", lambda **_: "JWT")
        monkeypatch.setattr(gha.api, "get_app", lambda **_: {"id": 999, "slug": "wrong-app"})

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is False
        assert "App ID mismatch" in (result.error or "")

    def test_no_installations_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gha.api, "mint_app_jwt", lambda **_: "JWT")
        monkeypatch.setattr(gha.api, "get_app", lambda **_: {"id": 12345, "slug": "ok"})
        monkeypatch.setattr(gha.api, "list_installations", lambda **_: [])

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is False
        assert "no installations" in (result.error or "").lower()

    def test_happy_path_reports_verified_repos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gha.api, "mint_app_jwt", lambda **_: "JWT")
        monkeypatch.setattr(gha.api, "get_app", lambda **_: {"id": 12345, "slug": "dev10x-bot"})
        monkeypatch.setattr(
            gha.api,
            "list_installations",
            lambda **_: [{"id": 99, "account": {"login": "Dev10x-Guru"}}],
        )
        monkeypatch.setattr(
            gha.api,
            "create_installation_token",
            lambda **_: "INSTALL_TOKEN",
        )
        monkeypatch.setattr(
            gha.api,
            "list_installation_repositories",
            lambda **_: [{"name": "Dev10x-Claude", "owner": {"login": "Dev10x-Guru"}}],
        )
        monkeypatch.setattr(gha.api, "get_repo", lambda **_: {"id": 1})

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is True
        assert result.app_slug == "dev10x-bot"
        assert len(result.installations) == 1
        assert result.installations[0].verified_repo == "Dev10x-Guru/Dev10x-Claude"

    def test_all_installations_failing_aborts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gha.api, "mint_app_jwt", lambda **_: "JWT")
        monkeypatch.setattr(gha.api, "get_app", lambda **_: {"id": 12345, "slug": "ok"})
        monkeypatch.setattr(
            gha.api,
            "list_installations",
            lambda **_: [{"id": 99, "account": {"login": "Dev10x-Guru"}}],
        )

        def boom(**_: object) -> str:
            raise gha.api.GitHubAPIError("403 Forbidden")

        monkeypatch.setattr(gha.api, "create_installation_token", boom)

        result = gha._verify_setup(app_id="12345", private_key="KEY")

        assert result.success is False
        assert "403" in (result.error or "")
