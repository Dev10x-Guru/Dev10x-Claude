#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.32,<3", "pyyaml>=6.0,<7"]
# ///
"""Publish a recording to YouTube as unlisted and return per-destination embeds.

Auth model: ``gog`` already holds a live OAuth access token. We warm it,
export it, use it, and shred the export. The OAuth client secret is never
needed and never read, and the long-lived refresh token is never used for an
exchange — so this script holds no credential of its own and nothing
secret ever reaches the repo or the config file.

Secrets live in memory only. They are never printed and never logged.

Every subcommand prints JSON to stdout. On failure it prints
``{"error": "..."}`` to **stdout** and exits non-zero, so a caller parses one
channel and never sees empty stdout on failure.

Subcommands:
    check           Is gog reachable, is youtube.upload granted, who will publish
    pin             Persist account/channel defaults to ~/.config/Dev10x/yt-upload.yaml
    resolve-video   Pick the one artifact to publish from a qa-self run directory
    upload          Upload the video and return the embed forms
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"

# 28 = Science & Technology. Least-wrong bucket for internal product demos;
# overridable per project because "least wrong" is a judgement, not a fact.
DEFAULT_CATEGORY_ID = "28"

# A standalone uv-script runs outside the package, with no access to
# subprocess_utils and its bounded default, so the
# timeout bound lives here (GH-827 / ADR-0011 convention for uv-scripts).
_SUBPROCESS_TIMEOUT_SECONDS = 300
_SESSION_OPEN_TIMEOUT_SECONDS = 120
_MEDIA_PUT_TIMEOUT_SECONDS = 1800

# Below this many seconds of remaining token life, an upload is likely to
# die partway through and leave a half-published video behind.
_MIN_TOKEN_LIFETIME_SECONDS = 120


class UploadError(Exception):
    """A failure the caller can act on, carrying guidance in its message."""


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _fail(message: str, hint: str = "") -> None:
    """Emit a parseable error on stdout and exit non-zero."""
    _emit({"error": message, **({"hint": hint} if hint else {})})
    raise SystemExit(1)


# --------------------------------------------------------------------------
# Durable preference — ~/.config/Dev10x/yt-upload.yaml
# --------------------------------------------------------------------------


def config_path() -> Path:
    """Where the operator's account and channel choice lives.

    Under ``~/.config/Dev10x/`` alongside the other durable Dev10x prefs
    (ADR-0018) rather than in a repo's ``.claude/``, so one answer covers a
    repo and every worktree of it and no self-settings consent gate fires.
    """
    home = os.environ.get("DEV10X_CONFIG_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".config" / "Dev10x"
    return base / "yt-upload.yaml"


def load_config() -> dict:
    """Parsed yt-upload.yaml, or an empty config when the file is absent.

    An ABSENT config is normal — ``account`` is then required as a flag. A
    MALFORMED one raises rather than being ignored: silently falling back
    would publish to a different channel than the one the operator pinned,
    and an unlisted video cannot be quietly withdrawn.
    """
    path = config_path()
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise UploadError(f"{path} is not valid YAML: {error}") from error
    return loaded if isinstance(loaded, dict) else {}


def project_entry(config: dict, cwd: Path) -> dict | None:
    """First ``projects[]`` entry whose match globs cover ``cwd``.

    First match wins, mirroring the friction.yaml and tts.yaml resolvers so
    all three files behave the same way for the same reader.
    """
    for entry in config.get("projects") or []:
        if not isinstance(entry, dict):
            continue
        for pattern in entry.get("match") or []:
            if fnmatch.fnmatch(str(cwd), pattern) or fnmatch.fnmatch(cwd.name, pattern):
                return entry
    return None


def resolve_preference(
    *,
    account: str | None = None,
    channel: str | None = None,
    category_id: str | None = None,
    cwd: Path | None = None,
) -> dict:
    """Resolve account, channel and category.

    Order, highest first: explicit flag, environment, a matching
    ``projects[]`` entry, ``defaults``, the built-in. There is deliberately
    NO built-in account: a wrong-account default publishes to a stranger's
    channel, which is exactly the failure a default should not invent.
    """
    config = load_config()
    here = cwd or Path.cwd()
    entry = project_entry(config, here) or {}
    defaults = config.get("defaults") or {}

    def pick(flag: str | None, env: str, key: str, fallback: str | None) -> str | None:
        return flag or os.environ.get(env) or entry.get(key) or defaults.get(key) or fallback

    return {
        "account": pick(account, "DEV10X_YT_ACCOUNT", "account", None),
        "channel": pick(channel, "DEV10X_YT_CHANNEL", "channel", None),
        "category_id": pick(
            flag=category_id,
            env="DEV10X_YT_CATEGORY_ID",
            key="category_id",
            fallback=DEFAULT_CATEGORY_ID,
        ),
    }


def write_config(config: dict) -> Path:
    """Persist yt-upload.yaml atomically.

    A standalone uv-script cannot import ``dev10x.domain.file_locks``, so
    the honest equivalent is a temp-file rename: a crash mid-write leaves
    the previous config intact instead of a truncated one.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            yaml.safe_dump(config, stream, sort_keys=False, default_flow_style=False)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return path


def require_account(preference: dict) -> str:
    account = preference.get("account")
    if not account:
        raise UploadError(
            "no gog account resolved. Pass --account, set DEV10X_YT_ACCOUNT, or "
            f"pin one: upload-video.py pin --account <email> (writes {config_path()})"
        )
    return account


# --------------------------------------------------------------------------
# Credential handling — gog owns the token; we borrow and shred it
# --------------------------------------------------------------------------


def token_export_path() -> Path:
    """Create a private directory and return the token path inside it.

    The userspace original used one fixed path under a shared ``/tmp``. A
    plugin ships to every user on the machine, so this must not be a
    hand-built path: ``mkdir(exist_ok=True)`` in a world-writable ``/tmp``
    silently REUSES a directory another local user pre-created and owns,
    and an attacker who owns the directory can read or replace whatever
    gog writes into it. Predictability was never the real control —
    directory ownership is.

    ``mkdtemp`` creates the directory atomically, mode 0o700, owned by the
    calling user, and refuses to reuse an existing path. Its random suffix
    also separates concurrent uploads, so no pid component is needed.
    """
    directory = Path(tempfile.mkdtemp(prefix="Dev10x-yt-upload-"))
    return directory / "gog-token.json"


def shred(path: Path) -> None:
    """Overwrite then remove a file holding secrets, and its directory.

    Best-effort, not a secure erase: on copy-on-write filesystems (Btrfs,
    ZFS), SSDs with wear levelling, or an encrypted volume, the original
    blocks may survive outside the file's logical extent. Acceptable for a
    token that exists for seconds and that gog can revoke and reissue —
    the point is to not leave a readable credential lying in the
    filesystem, not to defeat forensic recovery.
    """
    try:
        if path.exists():
            size = path.stat().st_size
            with open(path, "wb") as handle:
                handle.write(b"\0" * size)
                handle.flush()
                os.fsync(handle.fileno())
            path.unlink()
        # The mkdtemp directory exists only to hold this one file.
        if path.parent.name.startswith("Dev10x-yt-upload-"):
            path.parent.rmdir()
    except OSError as error:
        # Never raise from cleanup — that would mask the real outcome. But
        # say so loudly: a surviving token file is a live credential.
        print(
            f"WARNING: could not shred {path} ({type(error).__name__}); "
            "delete it by hand — it holds a live access token",
            file=sys.stderr,
        )


def _shred_on_signal(signum: int, _frame: object) -> None:
    """Shred the borrowed token when the process is asked to terminate.

    A `finally` covers exceptions but NOT an external signal: Python's
    default SIGTERM disposition kills the process without unwinding, so a
    plain `kill <pid>` mid-upload would leave the export on disk. This
    handler converts the signal into an ordinary exit so the `finally`
    runs.
    """
    raise SystemExit(128 + signum)


def _run_gog(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["gog", *arguments],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def warm_token(account: str) -> None:
    """Force gog to refresh its access token, and surface a dead API early.

    Without this the exported access_token may already be expired.
    """
    proc = _run_gog(["youtube", "channels", "list", "--mine", "-j", "-a", account])
    if proc.returncode == 0:
        return

    error = (proc.stderr or proc.stdout)[:500]
    if "accessNotConfigured" in error or "has not been used in project" in error:
        raise UploadError(
            "YouTube Data API v3 is not enabled on the Cloud project behind this "
            "OAuth client. Enable it, wait a few minutes for it to propagate, then "
            "retry: https://console.developers.google.com/apis/api/"
            "youtube.googleapis.com/overview"
        )
    lowered = error.lower()
    if "insufficient" in lowered or "forbidden" in lowered:
        raise UploadError(
            "the stored grant cannot call the YouTube API. Authorize YouTube as its "
            "OWN grant — appending youtube.upload to a service list that includes "
            "drive is refused as 'scopes that cannot be requested together', and a "
            "separate grant leaves your Drive and Gmail grants untouched: run `gog "
            "auth add <email> --services youtube --extra-scopes "
            "https://www.googleapis.com/auth/youtube.upload --force-consent --remote "
            "--step 1`, then `gog auth add <email> --remote --step 2 --auth-url "
            "<redirect URL>`"
        )
    raise UploadError(f"gog could not reach YouTube: {error}")


def get_access_token(account: str, export_path: Path) -> str:
    """Export gog's live access token. Verifies scope and remaining lifetime."""
    # gog creates the file, so its mode comes from gog and the ambient
    # umask — the chmod below cannot run until the subprocess returns,
    # leaving a window where a live token sits at gog's default mode.
    # Tightening the umask first closes that window at creation instead of
    # after it. mkdtemp already made the directory 0o700, so this is
    # belt-and-braces for the file itself.
    previous_umask = os.umask(0o077)
    try:
        proc = _run_gog(
            [
                "auth",
                "tokens",
                "export",
                account,
                "--out",
                str(export_path),
                "--overwrite",
                "--no-input",
            ]
        )
    finally:
        os.umask(previous_umask)
    if proc.returncode != 0:
        # gog's stderr is a third-party trust boundary: it is forwarded into
        # this script's own JSON contract, so keep the excerpt short and do
        # not assume it is free of anything sensitive.
        raise UploadError(f"gog token export failed (rc={proc.returncode}): {proc.stderr[:200]}")
    if not export_path.exists():
        raise UploadError("gog reported success but wrote no token file")

    export_path.chmod(0o600)
    data = json.loads(export_path.read_text(encoding="utf-8"))

    token = data.get("access_token")
    if not token:
        raise UploadError("the gog export contained no access_token")

    scopes = data.get("scopes") or []
    if not any("youtube.upload" in scope for scope in scopes):
        raise UploadError(
            "this grant lacks the youtube.upload scope, so it can read YouTube but "
            "not publish to it. Authorize YouTube as its OWN grant — `gog auth add "
            "<email> --services youtube --extra-scopes "
            "https://www.googleapis.com/auth/youtube.upload --force-consent --remote "
            "--step 1` — rather than adding the scope to a service list that already "
            "includes drive, which Google refuses"
        )

    expires_raw = data.get("access_token_expires_at")
    if expires_raw:
        expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        remaining = int((expires - datetime.now(UTC)).total_seconds())
        if remaining < _MIN_TOKEN_LIFETIME_SECONDS:
            raise UploadError(
                f"the access token expires in {remaining}s, too soon for an upload. "
                "Run any gog command to refresh it, then retry."
            )
        # Diagnostic on stderr, so it survives without touching the parsed
        # stdout contract. A large upload racing token expiry is the failure
        # this number lets an operator predict instead of discover.
        print(f"access token valid for {remaining}s", file=sys.stderr)
    return token


# --------------------------------------------------------------------------
# Artifact selection — one video per run, narrated when it exists
# --------------------------------------------------------------------------


def read_narration(run_dir: Path) -> dict | None:
    """The narration manifest for a run, when the capture was narrated.

    Returns ``None`` for a silent capture — that is the normal case, not an
    error.
    """
    manifest = run_dir / "narration" / "narration.json"
    if not manifest.exists():
        return None
    try:
        loaded = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UploadError(f"{manifest} is not valid JSON: {error}") from error
    return loaded if isinstance(loaded, dict) else None


def narration_defects(narration: dict | None) -> list[str]:
    """MECHANICAL defects in the narration — never a quality verdict.

    An empty list means "nothing detectable went wrong with rendering or
    timing". It does NOT mean the recording is correct. The failure mode
    this cannot see is a caption that rendered perfectly and says
    something false — the overlay installed, the audio played, and the
    claim is still wrong. Only a human watching catches that, which is why
    the review gate is not optional and why this list must not be read as
    clearing the footage.

    Reported, never enforced — same contract as the Dev10x:tts licence
    warning. The caller's review gate decides; the script only refuses to
    let the caller claim it did not know.
    """
    if not narration:
        return []
    defects = []
    unrendered = narration.get("unrendered") or []
    if unrendered:
        defects.append(f"{len(unrendered)} caption(s) played with no audio: {unrendered}")
    if narration.get("anchor") == "install":
        defects.append(
            "narration is anchored at 'install', so every cue is offset by however "
            "long setup took — the audio may lag the captions throughout"
        )
    return defects


def resolve_video(run_dir: Path) -> dict:
    """Pick the single artifact to publish from a qa-self run directory.

    ``convert-evidence.sh narrate`` writes ``-narrated.mp4`` as a SIBLING of
    the silent take and deletes nothing, so a run directory can hold both.
    Detection is presence-only — there is no manifest field saying a run was
    narrated — and the narrated variant wins. Publishing both would put two
    near-identical videos on an append-only evidence trail, and on YouTube
    the wrong one cannot be quietly withdrawn.
    """
    video_dir = run_dir / "video"
    if not video_dir.is_dir():
        raise UploadError(f"no video directory at {video_dir}")

    narrated = sorted(video_dir.glob("*-narrated.mp4"))
    if len(narrated) > 1:
        raise UploadError(
            f"{len(narrated)} narrated takes in {video_dir} "
            f"({[p.name for p in narrated]}) — publish one artifact per run; "
            "delete the takes you do not want before uploading"
        )

    # Newest first. Playwright's hex filenames carry no recency signal, so
    # alphabetical order is effectively random — and two silent takes exist
    # precisely when a run was RETRIED, which makes the older one the failed
    # attempt. Picking it silently publishes evidence of the failure, which
    # is the bug class the narrated branch above already refuses to risk.
    plain = sorted(
        (p for p in video_dir.glob("*.mp4") if not p.name.endswith("-narrated.mp4")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not narrated and len(plain) > 1:
        newest, *older = plain
        raise UploadError(
            f"{len(plain)} silent takes in {video_dir} — refusing to guess. "
            f"Newest by mtime is {newest.name}; older: {[p.name for p in older]}. "
            "Publish one artifact per run: delete the takes you do not want, "
            "or pass the file explicitly to `upload --video`."
        )

    chosen = narrated[0] if narrated else (plain[0] if plain else None)
    if chosen is None:
        raise UploadError(
            f"no .mp4 in {video_dir} — run convert-evidence.sh video first "
            "(Playwright records .webm, which YouTube handles poorly)"
        )

    narration = read_narration(run_dir)
    return {
        "video": str(chosen),
        "narrated": bool(narrated),
        "superseded": [str(p) for p in plain] if narrated else [],
        "narration": {
            "unrendered": (narration or {}).get("unrendered") or [],
            "warning": (narration or {}).get("warning"),
            "anchor": (narration or {}).get("anchor"),
        }
        if narration
        else None,
        "narration_defects": narration_defects(narration),
    }


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------


def open_session(*, token: str, size: int, metadata: dict) -> str:
    start = requests.post(
        UPLOAD_ENDPOINT,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=metadata,
        timeout=_SESSION_OPEN_TIMEOUT_SECONDS,
    )
    if start.status_code not in (200, 201):
        raise UploadError(
            f"could not open an upload session ({start.status_code}): {start.text[:400]}"
        )
    session_url = start.headers.get("Location")
    if not session_url:
        raise UploadError("the upload session returned no Location header")
    return session_url


def upload(
    *, token: str, video: Path, title: str, description: str, privacy: str, category_id: str
) -> dict:
    size = video.stat().st_size
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }
    session_url = open_session(token=token, size=size, metadata=metadata)
    with open(video, "rb") as handle:
        put = requests.put(
            session_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
            data=handle,
            timeout=_MEDIA_PUT_TIMEOUT_SECONDS,
        )
    if put.status_code not in (200, 201):
        raise UploadError(f"upload failed ({put.status_code}): {put.text[:400]}")
    return put.json()


def verify_via_gog(*, video_id: str, account: str) -> dict:
    """Read the stored record back through gog.

    The videos.insert response describes what we asked for; this describes
    what YouTube kept. A channel or privacy mismatch only shows up here.
    Advisory — a verification failure must not orphan a successful upload.
    """
    proc = _run_gog(
        [
            "youtube",
            "videos",
            "list",
            "--id",
            video_id,
            "--parts",
            "snippet,status",
            "-j",
            "-a",
            account,
        ]
    )
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else payload
    return items[0] if items else {}


def embed_forms(*, video_id: str, title: str) -> dict:
    """The per-destination forms. The split is load-bearing, not cosmetic.

    Linear's player is built at PASTE TIME in its editor; nothing posted
    through the API embeds, so a human has to cut and re-paste the URL. A
    bare URL is what makes that possible — a titled link hides it behind
    the edit view.

    GitHub strips <iframe>, so no player can render in a comment. A linked
    poster frame is the closest equivalent, and unlike a plain link it
    cannot be scrolled past.

    The Linear paste-time behaviour above is inherited from the userspace
    skill this ports, whose author observed it directly.

    [Verify] The hosts are said not to cross over — img.youtube.com renders
    on GitHub (camo-proxied) but not in Linear; uploads.linear.app renders
    in Linear but 401s for anyone on GitHub. That claim comes from the
    ported skill's OWN documentation and has been verified by nobody: the
    session that ran the tool end to end declined to corroborate it, having
    only ever used img.youtube.com on GitHub and a bare URL in Linear. It
    is the reason these two fields exist, so it deserves a deliberate
    two-post test rather than continued inheritance. See
    references/destinations.md § Provenance.
    """
    watch = f"https://www.youtube.com/watch?v={video_id}"
    thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
    return {
        "watch_url": watch,
        "embed_url": f"https://www.youtube.com/embed/{video_id}",
        "thumbnail_url": thumbnail,
        "linear_markdown": watch,
        "github_markdown": f'[<img src="{thumbnail}" width="640" alt="{title}">]({watch})',
    }


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> dict:
    preference = resolve_preference(account=args.account, channel=args.channel)
    account = require_account(preference)
    warm_token(account)
    export_path = token_export_path()
    try:
        get_access_token(account, export_path)
    finally:
        shred(export_path)
    return {
        "ok": True,
        "account": account,
        "channel": preference["channel"],
        "category_id": preference["category_id"],
        "config": str(config_path()),
        "upload_scope_granted": True,
    }


def cmd_pin(args: argparse.Namespace) -> dict:
    config = load_config()
    defaults = dict(config.get("defaults") or {})
    for key, value in (
        ("account", args.account),
        ("channel", args.channel),
        ("category_id", args.category_id),
    ):
        if value:
            defaults[key] = value
    if not defaults:
        raise UploadError("nothing to pin — pass --account, --channel or --category-id")
    config["defaults"] = defaults
    path = write_config(config)
    return {"pinned": defaults, "config": str(path)}


def cmd_resolve_video(args: argparse.Namespace) -> dict:
    return resolve_video(Path(args.run_dir))


def cmd_upload(args: argparse.Namespace) -> dict:
    preference = resolve_preference(
        account=args.account, channel=args.channel, category_id=args.category_id
    )
    account = require_account(preference)

    video = Path(args.video)
    if not video.exists():
        raise UploadError(f"video not found: {video}")
    if video.suffix.lower() != ".mp4":
        raise UploadError(
            f"{video.suffix} is not a safe upload format; convert to H.264 MP4 first: "
            "convert-evidence.sh video <file>"
        )

    description = args.description
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")

    if args.privacy == "private":
        # BEFORE the network call, not after. The payload carries the same
        # note for machine callers, but by the time anything reads that the
        # video already exists — and a mistyped --privacy private is exactly
        # the case a human still has time to abort.
        print(
            "WARNING: --privacy private plays only for the uploader. Teammates "
            "will see 'unavailable' and every embed will render blank. Use "
            "unlisted for anything meant to be watched by someone else.",
            file=sys.stderr,
        )

    warm_token(account)
    export_path = token_export_path()
    try:
        token = get_access_token(account, export_path)
        result = upload(
            token=token,
            video=video,
            title=args.title,
            description=description,
            privacy=args.privacy,
            category_id=preference["category_id"],
        )
    finally:
        shred(export_path)

    video_id = result["id"]
    # Prefer what YouTube stored over what the insert response echoed back.
    stored = verify_via_gog(video_id=video_id, account=account)
    # An empty `stored` means read-back was unavailable, and the fallback is
    # the insert echo — which reports what we ASKED for. So the privacy
    # comparison below cannot fail when verification failed: it goes vacuous
    # exactly when it was needed. Say so in the payload rather than letting
    # a caller read "no mismatch" as "confirmed correct".
    verified = bool(stored)
    snippet = (stored.get("snippet") or {}) or (result.get("snippet") or {})
    status = (stored.get("status") or {}) or (result.get("status") or {})
    channel = snippet.get("channelId")
    privacy = status.get("privacyStatus")

    expected_channel = preference["channel"]
    if expected_channel and channel != expected_channel:
        raise UploadError(
            f"the video uploaded to channel {channel}, not the expected "
            f"{expected_channel}. It exists at "
            f"https://www.youtube.com/watch?v={video_id} — move or delete it."
        )

    payload = {
        "video_id": video_id,
        **embed_forms(video_id=video_id, title=args.title),
        "privacy": privacy,
        "channel_id": channel,
        "account": account,
        # False = `privacy` and `channel_id` are what we ASKED for, echoed by
        # the insert response, not what YouTube confirmed it stored.
        "verified": verified,
    }
    if not verified:
        payload["verification_note"] = (
            "gog read-back was unavailable, so privacy and channel are the "
            "requested values echoed by the upload response — not confirmed "
            "stored state. Absence of a mismatch here proves nothing; check "
            f"https://www.youtube.com/watch?v={video_id} directly."
        )
    if privacy and privacy != args.privacy:
        payload["privacy_mismatch"] = f"requested {args.privacy!r} but YouTube stored {privacy!r}"
    if args.privacy == "private":
        # `private` plays for the uploader ALONE — a teammate sees
        # "unavailable" and every embed renders blank. It is not a cautious
        # unlisted; it is a way to publish something nobody else can watch,
        # which is almost never what a caller sharing evidence wanted.
        payload["privacy_note"] = (
            "private plays only for the uploader — teammates see 'unavailable' "
            "and embeds render blank; use unlisted to share"
        )
    # Measured (TD-5642, 5:14 / ~10MB upload): the poster frame 404s for at
    # least ~2 minutes, and maxresdefault.jpg and hqdefault.jpg 404 and
    # recover TOGETHER — so dropping to the smaller size is not a fallback.
    # Flagged unconditionally because the cost of saying so is one probe,
    # and the cost of silence is a caller embedding a broken image and
    # concluding the URL is wrong.
    payload["thumbnail_may_404"] = True
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_target_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("--account", help="gog account email")
        target.add_argument("--channel", help="assert the upload landed on this channel")

    check = subparsers.add_parser("check", help="preflight without uploading")
    add_target_options(check)
    check.set_defaults(handler=cmd_check)

    pin = subparsers.add_parser("pin", help="persist account/channel defaults")
    add_target_options(pin)
    pin.add_argument("--category-id")
    pin.set_defaults(handler=cmd_pin)

    resolve = subparsers.add_parser(
        "resolve-video", help="pick the one artifact to publish from a run dir"
    )
    resolve.add_argument("--run-dir", required=True)
    resolve.set_defaults(handler=cmd_resolve_video)

    up = subparsers.add_parser("upload", help="upload a video")
    add_target_options(up)
    up.add_argument("--video", required=True)
    up.add_argument("--title", required=True)
    up.add_argument("--description", default="")
    up.add_argument("--description-file")
    up.add_argument("--category-id")
    up.add_argument("--privacy", default="unlisted", choices=["unlisted", "private", "public"])
    up.set_defaults(handler=cmd_upload)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    signal.signal(signal.SIGTERM, _shred_on_signal)
    try:
        _emit(args.handler(args))
    except UploadError as error:
        _fail(str(error))
    except subprocess.TimeoutExpired:
        _fail(f"gog exceeded {_SUBPROCESS_TIMEOUT_SECONDS}s — treating as wedged")
    except requests.RequestException as error:
        _fail(f"the upload request failed: {type(error).__name__}: {error}")
    except Exception as error:  # noqa: BLE001 — the stdout contract outranks a traceback
        # Callers parse stdout. An unexpected exception that escaped to a
        # stderr traceback would leave them with empty stdout and nothing to
        # branch on, so every failure has to arrive through the same channel.
        _fail(f"unexpected {type(error).__name__}: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
