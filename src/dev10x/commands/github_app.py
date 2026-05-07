"""``dev10x github-app setup`` — interactive onboarding for the bot identity.

Walks the engineer through GitHub App registration with install-target
guidance, picks up the downloaded ``.pem`` from disk, and runs an
end-to-end verification (App JWT → installations → installation token →
repo read) before writing config under ``~/.claude/Dev10x/github-bot/``.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import click

from dev10x.commands import github_app_api as api

CONFIG_DIR = Path.home() / ".claude" / "Dev10x" / "github-bot"
CONFIG_PATH = CONFIG_DIR / "github-app.yaml"
KEY_PATH = CONFIG_DIR / "dev10x-bot.pem"

PERSONAL_NEW_APP_URL = "https://github.com/settings/apps/new"

INTRO = """\
Dev10x GitHub App setup
━━━━━━━━━━━━━━━━━━━━━━━

This walks you through wiring up a GitHub App so agent-generated PR
review replies post under a `<your-app>[bot]` identity instead of your
personal account.

You will need to:
  1. Pick where the App is registered (personal vs. an org)
  2. Register the App on github.com (one browser visit)
  3. Install it on the repos you want the bot to comment on
  4. Point this wizard at the downloaded .pem file

Press Ctrl+C at any time to abort. Nothing is written until
verification succeeds.
"""

CREATE_APP_INSTRUCTIONS = """\
Step 2: Register the GitHub App
───────────────────────────────

Open this URL:

    {url}

Fill in:
  Name           dev10x-bot   (or any unique name; appears as
                              `<name>[bot]` next to comments)
  Homepage URL   anything (not user-facing)
  Webhook        UNCHECK "Active" — Dev10x doesn't receive webhooks

Repository permissions:
  Pull requests       Read and write   (required)
  Contents            Read-only        (required)
  All others          No access

{install_scope_hint}

Click "Create GitHub App". On the App settings page:
  • Note the App ID (numeric)
  • Click "Generate a private key" — a .pem file downloads to your
    browser's Downloads folder. Leave it there; the wizard will
    pick it up next.
"""

INSTALL_INSTRUCTIONS = """\
Step 3: Install the App on at least one repo
────────────────────────────────────────────

On the App settings page, click "Install App" in the left nav.
Pick the repos you want the bot to comment on. Without an
installation, the App can't post anywhere.
"""


def _prompt_install_target() -> dict[str, str]:
    """Return the install-target choice: personal, org-owned, or manual."""
    click.echo("Step 1: Where will the App be registered?")
    click.echo("─────────────────────────────────────────")
    click.echo("")
    click.echo("  1) Personal account — multi-target, can install on any account")
    click.echo("  2) Organization     — App owned by the org, scope is the org")
    click.echo("  3) Manual           — I'll open the settings page myself")
    click.echo("")
    while True:
        choice = click.prompt("Choose [1/2/3]", type=str, default="1").strip()
        if choice == "1":
            return {"kind": "personal"}
        if choice == "2":
            org = click.prompt("Org login (e.g. tiretutorinc)", type=str).strip()
            if not org:
                click.echo("  Org login is required for an org-owned App.")
                continue
            return {"kind": "org", "org": org}
        if choice == "3":
            return {"kind": "manual"}
        click.echo("  Pick 1, 2, or 3.")


def _registration_url(target: dict[str, str]) -> str:
    if target["kind"] == "org":
        return f"https://github.com/organizations/{target['org']}/settings/apps/new"
    if target["kind"] == "manual":
        return "(open the GitHub App settings page yourself)"
    return PERSONAL_NEW_APP_URL


def _install_scope_hint(target: dict[str, str]) -> str:
    if target["kind"] == "personal":
        return (
            "Where can this GitHub App be installed?\n"
            '  Pick "Any account" — lets you install the App on personal\n'
            '  repos AND any orgs you belong to. The default "Only on this\n'
            '  account" blocks org installs.'
        )
    if target["kind"] == "org":
        return (
            "Where can this GitHub App be installed?\n"
            "  Scope is implicit — the App is owned by the org and can only\n"
            "  be installed on it. Leave the default selection."
        )
    return (
        "Where can this GitHub App be installed?\n"
        '  Personal multi-target → "Any account".\n'
        "  Org-owned → leave the default."
    )


def _prompt_app_id() -> str:
    while True:
        value = click.prompt("App ID", type=str).strip()
        if value.isdigit():
            return value
        click.echo("  App ID must be numeric (look for it on the App settings page).")


def _newest_pem_in_downloads() -> Path | None:
    downloads = Path.home() / "Downloads"
    if not downloads.is_dir():
        return None
    candidates = sorted(
        downloads.glob("*.private-key.pem"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _prompt_private_key_path() -> Path:
    """Prompt for the path to the downloaded .pem; default to newest in ~/Downloads."""
    default = _newest_pem_in_downloads()
    if default is not None:
        click.echo(f"  Found: {default}")
    while True:
        kwargs: dict[str, object] = {"type": str}
        if default is not None:
            kwargs["default"] = str(default)
        raw = click.prompt("Path to .pem file", **kwargs).strip()
        if not raw:
            click.echo("  Path is required.")
            continue
        path = Path(raw).expanduser()
        if not path.is_file():
            click.echo(f"  No file at {path}.")
            continue
        return path


def _prompt_private_key_paste() -> str:
    """Legacy paste flow for headless setups (--paste flag)."""
    click.echo("")
    click.echo("Paste the private key contents below.")
    click.echo("Include the BEGIN/END lines. Finish with a blank line:")
    click.echo("")
    lines: list[str] = []
    saw_end = False
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        stripped = line.rstrip("\n")
        if saw_end and stripped == "":
            break
        if not stripped and not lines:
            continue
        lines.append(stripped)
        if "END" in stripped and "PRIVATE KEY" in stripped:
            saw_end = True
    return "\n".join(lines) + "\n"


def _validate_key_locally(*, app_id: str, private_key: str) -> str | None:
    """Quick offline check: can we sign a JWT with this key?"""
    try:
        import jwt
    except ImportError:
        return "PyJWT is not installed. Run `uv sync --extra dev`."
    try:
        token = jwt.encode(
            {"iat": 0, "exp": 60, "iss": app_id},
            private_key,
            algorithm="RS256",
        )
    except Exception as exc:  # noqa: BLE001 — surface the underlying message
        return f"Private key is not valid for RS256 signing: {exc}"
    if not token:
        return "JWT signing produced an empty token."
    return None


@dataclass
class InstallationInfo:
    """One entry in the verification report."""

    id: int
    account: str
    verified_repo: str | None = None
    error: str | None = None


@dataclass
class VerificationResult:
    """End-to-end verification outcome."""

    success: bool
    error: str | None = None
    app_slug: str | None = None
    app_id: int | None = None
    installations: list[InstallationInfo] = field(default_factory=list)


def _verify_setup(*, app_id: str, private_key: str) -> VerificationResult:
    """Mint JWT, fetch App + installations, exchange a token, read a repo."""
    try:
        jwt_token = api.mint_app_jwt(app_id=app_id, private_key=private_key)
    except Exception as exc:  # noqa: BLE001 — surface to user
        return VerificationResult(success=False, error=f"Could not mint JWT: {exc}")

    try:
        app = api.get_app(jwt_token=jwt_token)
    except api.GitHubAPIError as exc:
        return VerificationResult(success=False, error=f"GET /app failed: {exc}")

    actual_id = app.get("id")
    if str(actual_id) != str(app_id):
        return VerificationResult(
            success=False,
            error=(
                f"App ID mismatch: the key belongs to App {actual_id} "
                f"({app.get('slug')!r}), but you entered {app_id}. "
                "Re-download the .pem from the correct App settings page."
            ),
        )

    try:
        installations = api.list_installations(jwt_token=jwt_token)
    except api.GitHubAPIError as exc:
        return VerificationResult(
            success=False,
            error=f"GET /app/installations failed: {exc}",
        )

    if not installations:
        return VerificationResult(
            success=False,
            error=(
                "App has no installations. Click 'Install App' in the App "
                "settings page, pick at least one repo, then re-run setup."
            ),
            app_slug=app.get("slug"),
            app_id=actual_id,
        )

    verified = [
        _verify_one_installation(jwt_token=jwt_token, installation=inst) for inst in installations
    ]

    if not any(info.verified_repo for info in verified):
        failures = "\n      ".join(
            f"{info.account}: {info.error}" for info in verified if info.error
        )
        return VerificationResult(
            success=False,
            error=f"All installations failed verification:\n      {failures}",
            app_slug=app.get("slug"),
            app_id=actual_id,
            installations=verified,
        )

    return VerificationResult(
        success=True,
        app_slug=app.get("slug"),
        app_id=actual_id,
        installations=verified,
    )


def _verify_one_installation(
    *,
    jwt_token: str,
    installation: dict,
) -> InstallationInfo:
    info = InstallationInfo(
        id=installation["id"],
        account=installation.get("account", {}).get("login", "<unknown>"),
    )
    try:
        token = api.create_installation_token(
            jwt_token=jwt_token,
            installation_id=installation["id"],
        )
    except api.GitHubAPIError as exc:
        info.error = f"token exchange failed: {exc}"
        return info

    try:
        repos = api.list_installation_repositories(token=token)
    except api.GitHubAPIError as exc:
        info.error = f"could not list installation repos: {exc}"
        return info

    if not repos:
        info.error = "installation has no accessible repos"
        return info

    first = repos[0]
    owner = first["owner"]["login"]
    name = first["name"]
    try:
        api.get_repo(token=token, owner=owner, repo=name)
    except api.GitHubAPIError as exc:
        info.error = f"could not read {owner}/{name}: {exc}"
        return info

    info.verified_repo = f"{owner}/{name}"
    return info


def _install_key_from_path(*, source: Path) -> str:
    """Move the user-provided .pem into KEY_PATH and chmod 600."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if source.resolve() != KEY_PATH.resolve():
        shutil.move(str(source), str(KEY_PATH))
    os.chmod(KEY_PATH, 0o600)
    return KEY_PATH.read_text()


def _write_key_text(*, private_key: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_text(private_key)
    os.chmod(KEY_PATH, 0o600)


def _write_config(*, app_id: str) -> None:
    yaml_lines = [
        "github_app:",
        f'  app_id: "{app_id}"',
        f'  private_key_path: "{KEY_PATH}"',
        "  enabled: true",
    ]
    CONFIG_PATH.write_text("\n".join(yaml_lines) + "\n")
    os.chmod(CONFIG_PATH, 0o600)


def _print_verification(result: VerificationResult) -> None:
    click.echo("")
    click.echo(f"  ✓ App `{result.app_slug}` (ID {result.app_id})")
    click.echo(f"  ✓ {len(result.installations)} installation(s):")
    for info in result.installations:
        if info.verified_repo:
            click.echo(f"      • {info.account} — read {info.verified_repo}")
        else:
            click.echo(f"      • {info.account} — FAILED: {info.error}")


@click.group()
def github_app() -> None:
    """Manage the Dev10x GitHub App bot identity."""


@github_app.command()
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing config without prompting.",
)
@click.option(
    "--paste",
    is_flag=True,
    help="Paste the private key contents instead of pointing at a file.",
)
def setup(*, force: bool, paste: bool) -> None:
    """Interactive setup wizard for the GitHub App bot identity."""
    click.echo(INTRO)

    if (CONFIG_PATH.exists() or KEY_PATH.exists()) and not force:
        click.echo(f"Existing config at {CONFIG_DIR} — pass --force to overwrite.")
        if not click.confirm("Overwrite?", default=False):
            click.echo("Aborted.")
            sys.exit(1)

    target = _prompt_install_target()
    click.echo("")
    click.echo(
        CREATE_APP_INSTRUCTIONS.format(
            url=_registration_url(target),
            install_scope_hint=_install_scope_hint(target),
        )
    )
    click.pause(info="Press any key when the App is created and the .pem is downloaded… ")
    click.echo("")
    click.echo(INSTALL_INSTRUCTIONS)
    click.pause(info="Press any key when the App is installed on at least one repo… ")
    click.echo("")
    click.echo("Step 4: Provide credentials")
    click.echo("───────────────────────────")
    click.echo("")

    app_id = _prompt_app_id()

    if paste:
        private_key = _prompt_private_key_paste()
        key_source: Path | None = None
    else:
        key_source = _prompt_private_key_path()
        private_key = key_source.read_text()

    error = _validate_key_locally(app_id=app_id, private_key=private_key)
    if error is not None:
        click.echo(f"\n  ✗ {error}")
        click.echo("  Re-download the .pem from the App settings page and try again.")
        sys.exit(1)

    click.echo("")
    click.echo("Step 5: End-to-end verification")
    click.echo("───────────────────────────────")
    click.echo("  Calling GitHub API to confirm the App, installations, and repo access…")
    result = _verify_setup(app_id=app_id, private_key=private_key)
    if not result.success:
        click.echo(f"\n  ✗ {result.error}")
        click.echo("  Config not written. Fix the issue above and re-run setup.")
        sys.exit(1)

    _print_verification(result)

    if key_source is not None:
        _install_key_from_path(source=key_source)
    else:
        _write_key_text(private_key=private_key)
    _write_config(app_id=app_id)

    click.echo("")
    click.echo(f"  ✓ Wrote config: {CONFIG_PATH}")
    click.echo(f"  ✓ Wrote key:    {KEY_PATH}")
    click.echo("")
    click.echo("Done. Agent-generated PR replies will now post under the bot identity.")


@github_app.command()
def status() -> None:
    """Show current GitHub App config status."""
    if not CONFIG_PATH.exists():
        click.echo(f"No config at {CONFIG_PATH}")
        click.echo("Run `dev10x github-app setup` to create one.")
        sys.exit(1)

    click.echo(f"Config:        {CONFIG_PATH}")
    click.echo(f"Key:           {KEY_PATH}")
    click.echo(f"Key readable:  {KEY_PATH.is_file() and os.access(KEY_PATH, os.R_OK)}")
    if KEY_PATH.is_file():
        mode = oct(KEY_PATH.stat().st_mode & 0o777)
        click.echo(f"Key mode:      {mode}")
        if mode != "0o600":
            click.echo("  ⚠  Expected 0o600 — fix with: chmod 600 " + str(KEY_PATH))
