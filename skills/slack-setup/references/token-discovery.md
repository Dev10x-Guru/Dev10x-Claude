# Where to Find an Existing Slack Bot Token

Use this reference when a user reports they "already have a token"
but cannot locate it.

## Slack App Console

The canonical source for any token.

1. Open https://api.slack.com/apps
2. Sign in to the workspace that owns the app
3. Pick the app (e.g., "Claude AI", "Dev10x Bot")
4. Sidebar → **OAuth & Permissions**
5. Copy the **Bot User OAuth Token** (`xoxb-...`)

If the workspace owner installed the app under a different account,
the user must ask that owner — Slack only exposes the token to app
collaborators.

## Password Manager / Vault

Search terms that commonly surface stored Slack tokens:

- `slack`
- `xoxb`
- `bot token`
- workspace name (e.g., `acme-eng`)

1Password, Bitwarden, KeePass, Vaultwarden all index secret bodies,
so even if the entry title is generic, the `xoxb-` prefix matches.

## OS Keychain (already-stored token)

If the user previously ran `Dev10x:slack-setup` on this machine,
the token is in the system keyring. The skill detects this in
Step 1 — no manual lookup needed.

Manual lookup commands (debug only):

| Platform | Command |
|----------|---------|
| Linux | `secret-tool lookup service slack key bot_token` |
| macOS | `security find-generic-password -s slack -a bot_token -w` |

## Environment Variable

Some users export the token in their shell profile:

```
export SLACK_TOKEN="xoxb-..."
```

Check `~/.zshrc`, `~/.bashrc`, `~/.config/fish/config.fish`, or any
file the user sources at login.

## Token Format Validation

| Prefix | Type | Notes |
|--------|------|-------|
| `xoxb-` | Bot User OAuth Token | Recommended for this skill |
| `xoxp-` | User OAuth Token | Works but acts as the user, not a bot |
| `xoxe.xoxb-` | Refresh-rotated bot token | Newer Slack apps; treat as `xoxb-` |
| anything else | Invalid | Reject and ask again |

A valid `auth.test` response confirms the token regardless of
prefix. The skill always calls `auth.test` before persisting.
