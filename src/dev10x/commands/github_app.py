"""`dev10x github-app setup` — interactive onboarding for the bot identity.

Walks the user through GitHub App registration, prompts for the App
ID, installation ID, and private key, then writes a tightly-permissioned
config tree under ``~/.claude/Dev10x/github-bot/``. Validates the key
locally by minting a self-signed JWT before persisting.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

CONFIG_DIR = Path.home() / ".claude" / "Dev10x" / "github-bot"
CONFIG_PATH = CONFIG_DIR / "github-app.yaml"
KEY_PATH = CONFIG_DIR / "dev10x-bot.pem"

NEW_APP_URL = "https://github.com/settings/apps/new"

INTRO = """\
Dev10x GitHub App setup
━━━━━━━━━━━━━━━━━━━━━━━

This walks you through wiring up a GitHub App so agent-generated PR
review replies post under a `<your-app>[bot]` identity instead of your
personal account.

You will need to:
  1. Register the App on github.com (one browser visit)
  2. Install it on the repos you want the bot to comment on
  3. Paste the App ID, Installation ID, and private key here

Press Ctrl+C at any time to abort. Nothing is written until the
final step.
"""

CREATE_APP_INSTRUCTIONS = """\
Step 1: Register the GitHub App
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

Click "Create GitHub App". On the App settings page:
  • Note the App ID (numeric)
  • Click "Generate a private key" — a .pem file downloads
"""

INSTALL_INSTRUCTIONS = """\
Step 2: Install the App
───────────────────────

On the App settings page, click "Install App" in the left nav.
Pick the repos you want the bot to comment on.

After installing, the URL contains "installations/<id>" — that's the
Installation ID. It's optional here; Dev10x can auto-resolve it from
each target repo if you leave the prompt blank.
"""


def _prompt_app_id() -> str:
    while True:
        value = click.prompt("App ID", type=str).strip()
        if value.isdigit():
            return value
        click.echo("  App ID must be numeric (look for it on the App settings page).")


def _prompt_installation_id() -> str | None:
    value = click.prompt(
        "Installation ID (blank to auto-resolve per repo)",
        type=str,
        default="",
        show_default=False,
    ).strip()
    if not value:
        return None
    while not value.isdigit():
        click.echo("  Installation ID must be numeric or blank.")
        value = click.prompt(
            "Installation ID (blank to auto-resolve per repo)",
            type=str,
            default="",
            show_default=False,
        ).strip()
        if not value:
            return None
    return value


def _prompt_private_key() -> str:
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
    """Return None on success, or a human-readable error message."""
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


def _write_files(
    *,
    app_id: str,
    installation_id: str | None,
    private_key: str,
) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_text(private_key)
    os.chmod(KEY_PATH, 0o600)

    yaml_lines = [
        "github_app:",
        f'  app_id: "{app_id}"',
        f'  private_key_path: "{KEY_PATH}"',
        "  enabled: true",
    ]
    if installation_id:
        yaml_lines.insert(2, f'  installation_id: "{installation_id}"')
    CONFIG_PATH.write_text("\n".join(yaml_lines) + "\n")
    os.chmod(CONFIG_PATH, 0o600)


@click.group()
def github_app() -> None:
    """Manage the Dev10x GitHub App bot identity."""


@github_app.command()
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing config without prompting.",
)
def setup(*, force: bool) -> None:
    """Interactive setup wizard for the GitHub App bot identity."""
    click.echo(INTRO)

    if (CONFIG_PATH.exists() or KEY_PATH.exists()) and not force:
        click.echo(f"Existing config at {CONFIG_DIR} — pass --force to overwrite.")
        if not click.confirm("Overwrite?", default=False):
            click.echo("Aborted.")
            sys.exit(1)

    click.echo(CREATE_APP_INSTRUCTIONS.format(url=NEW_APP_URL))
    click.pause(info="Press any key when the App is created and the .pem file is downloaded… ")
    click.echo("")
    click.echo(INSTALL_INSTRUCTIONS)
    click.pause(info="Press any key when the App is installed on at least one repo… ")
    click.echo("")
    click.echo("Step 3: Paste credentials")
    click.echo("─────────────────────────")
    click.echo("")

    app_id = _prompt_app_id()
    installation_id = _prompt_installation_id()
    private_key = _prompt_private_key()

    error = _validate_key_locally(app_id=app_id, private_key=private_key)
    if error is not None:
        click.echo(f"\n  ✗ {error}")
        click.echo("  Re-download the .pem from the App settings page and try again.")
        sys.exit(1)

    _write_files(
        app_id=app_id,
        installation_id=installation_id,
        private_key=private_key,
    )

    click.echo("")
    click.echo("  ✓ Wrote config: " + str(CONFIG_PATH))
    click.echo("  ✓ Wrote key:    " + str(KEY_PATH))
    click.echo("")
    click.echo("Next: open a draft PR on a repo where the App is installed,")
    click.echo("then ask Dev10x to reply to a review comment. The reply should")
    click.echo("now appear under the bot identity instead of your account.")


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
