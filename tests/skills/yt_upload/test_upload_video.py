"""Tests for the Dev10x:yt-upload wrapper script (GH-1119).

The properties pinned here are the ones whose absence publishes the wrong
thing to a URL that cannot be quietly withdrawn: single-artifact selection
across a narrated/silent sibling pair, narration defects being reported
rather than swallowed, per-destination embed forms staying distinct, an
account that is never invented, and errors arriving as JSON on stdout so a
caller parsing one channel never sees empty output on failure.

The script is a standalone uv-script loaded by path — there is no package
context — so it is imported the same way as the other skills/ modules.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# `requests` is the uv-script's own PEP 723 dependency, resolved at run time
# by `uv run --script`. It is deliberately NOT a dependency of the dev
# environment — adding one to the package so a test can import a standalone
# script would invert the dependency direction. Stand it in instead, the way
# test_annotate.py stands in for an uninstalled Playwright. Nothing under
# test here performs a request; the two call sites are exercised through
# their own error paths.
#
# The stub is installed ONLY for the duration of the load and then removed.
# Leaving it in sys.modules makes `importlib.util.find_spec("requests")`
# succeed process-wide, which silently defeats the missing-dependency skip
# in tests/test_script_loadability.py — it then tries to really import every
# requests-dependent script in a subprocess and fails. The loaded module
# keeps its own reference, so removing the entry costs the tests nothing.


def _install_requests_stub() -> bool:
    if "requests" in sys.modules:
        return False
    stub = types.ModuleType("requests")

    class RequestException(Exception):
        """Mirrors requests.RequestException for the main() except clause."""

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no test may perform a real HTTP request")

    stub.RequestException = RequestException
    stub.post = unavailable
    stub.put = unavailable
    sys.modules["requests"] = stub
    return True


_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_stubbed = _install_requests_stub()
try:
    _spec = importlib.util.spec_from_file_location(
        "upload_video",
        _repo_root / "skills" / "yt-upload" / "scripts" / "upload-video.py",
    )
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
finally:
    if _stubbed:
        del sys.modules["requests"]


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "video").mkdir()
    return tmp_path


def write_video(run_dir: Path, name: str) -> Path:
    path = run_dir / "video" / name
    path.write_bytes(b"\0" * 1024)
    return path


def _mp4(tmp_path: Path, size: int = 16) -> Path:
    """A file that passes the .mp4 suffix check and has a real byte count."""
    path = tmp_path / "v.mp4"
    path.write_bytes(b"\0" * size)
    return path


def write_narration(run_dir: Path, payload: dict) -> Path:
    directory = run_dir / "narration"
    directory.mkdir(exist_ok=True)
    path = directory / "narration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# resolve_video — one artifact per run
# --------------------------------------------------------------------------


def test_narrated_take_wins_over_silent_sibling(run_dir: Path) -> None:
    write_video(run_dir, "qa-gh-42.mp4")
    narrated = write_video(run_dir, "qa-gh-42-narrated.mp4")

    result = _mod.resolve_video(run_dir)

    assert result["video"] == str(narrated)
    assert result["narrated"] is True


def test_silent_sibling_is_reported_as_superseded(run_dir: Path) -> None:
    silent = write_video(run_dir, "qa-gh-42.mp4")
    write_video(run_dir, "qa-gh-42-narrated.mp4")

    result = _mod.resolve_video(run_dir)

    assert result["superseded"] == [str(silent)]


def test_silent_take_is_published_when_not_narrated(run_dir: Path) -> None:
    silent = write_video(run_dir, "qa-gh-42.mp4")

    result = _mod.resolve_video(run_dir)

    assert result["video"] == str(silent)
    assert result["narrated"] is False
    assert result["superseded"] == []


def test_two_silent_takes_refuse_rather_than_guess(run_dir: Path) -> None:
    """Two silent takes exist precisely when a run was retried, so the older
    one is the failed attempt. Alphabetical order would publish it at random,
    because Playwright's hex filenames carry no recency signal."""
    write_video(run_dir, "aaa-first-attempt.mp4")
    write_video(run_dir, "zzz-second-attempt.mp4")

    with pytest.raises(_mod.UploadError, match="refusing to guess"):
        _mod.resolve_video(run_dir)


def test_silent_take_refusal_names_the_newest(run_dir: Path) -> None:
    """The operator has to pick, so the error must say which is newer —
    alphabetically-first is not the answer they need."""
    older = write_video(run_dir, "zzz-older.mp4")
    newer = write_video(run_dir, "aaa-newer.mp4")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    with pytest.raises(_mod.UploadError, match="Newest by mtime is aaa-newer.mp4"):
        _mod.resolve_video(run_dir)


def test_narrated_take_wins_even_with_several_silent_takes(run_dir: Path) -> None:
    """The multiple-silent guard must not fire when a narrated take settles
    the choice already."""
    write_video(run_dir, "aaa-first.mp4")
    write_video(run_dir, "zzz-second.mp4")
    narrated = write_video(run_dir, "qa-gh-42-narrated.mp4")

    assert _mod.resolve_video(run_dir)["video"] == str(narrated)


def test_two_narrated_takes_refuse_rather_than_guess(run_dir: Path) -> None:
    write_video(run_dir, "first-narrated.mp4")
    write_video(run_dir, "second-narrated.mp4")

    with pytest.raises(_mod.UploadError, match="publish one artifact per run"):
        _mod.resolve_video(run_dir)


def test_missing_mp4_names_the_conversion_step(run_dir: Path) -> None:
    (run_dir / "video" / "qa-gh-42.webm").write_bytes(b"\0" * 1024)

    with pytest.raises(_mod.UploadError, match="convert-evidence.sh video"):
        _mod.resolve_video(run_dir)


def test_missing_video_directory_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(_mod.UploadError, match="no video directory"):
        _mod.resolve_video(tmp_path)


def test_silent_capture_reports_no_narration(run_dir: Path) -> None:
    write_video(run_dir, "qa-gh-42.mp4")

    result = _mod.resolve_video(run_dir)

    assert result["narration"] is None
    assert result["narration_defects"] == []


# --------------------------------------------------------------------------
# narration_defects — reported, never enforced
# --------------------------------------------------------------------------


def test_unrendered_captions_are_a_defect() -> None:
    defects = _mod.narration_defects({"unrendered": ["step three"], "anchor": "video-start"})

    assert len(defects) == 1
    assert "step three" in defects[0]


def test_install_anchor_is_a_defect() -> None:
    defects = _mod.narration_defects({"unrendered": [], "anchor": "install"})

    assert len(defects) == 1
    assert "install" in defects[0]


def test_clean_narration_has_no_defects() -> None:
    assert _mod.narration_defects({"unrendered": [], "anchor": "video-start"}) == []


def test_licence_warning_alone_is_not_a_defect() -> None:
    """A licence caveat is the supervisor's call, not a publishing blocker."""
    assert (
        _mod.narration_defects(
            {"unrendered": [], "anchor": "video-start", "warning": "CC BY-NC-SA"}
        )
        == []
    )


def test_absent_narration_has_no_defects() -> None:
    assert _mod.narration_defects(None) == []


def test_defects_surface_through_resolve_video(run_dir: Path) -> None:
    write_video(run_dir, "qa-gh-42-narrated.mp4")
    write_narration(run_dir, {"unrendered": ["step two"], "anchor": "install"})

    result = _mod.resolve_video(run_dir)

    assert len(result["narration_defects"]) == 2
    assert result["narration"]["anchor"] == "install"


def test_non_dict_narration_manifest_is_treated_as_absent(run_dir: Path) -> None:
    """Valid JSON of the wrong shape must read as 'no narration' rather than
    crashing the publish path."""
    write_video(run_dir, "qa-gh-42-narrated.mp4")
    (run_dir / "narration").mkdir(exist_ok=True)
    (run_dir / "narration" / "narration.json").write_text("[1, 2, 3]", encoding="utf-8")

    result = _mod.resolve_video(run_dir)

    assert result["narration"] is None
    assert result["narration_defects"] == []


def test_malformed_narration_manifest_raises(run_dir: Path) -> None:
    write_video(run_dir, "qa-gh-42-narrated.mp4")
    (run_dir / "narration").mkdir(exist_ok=True)
    (run_dir / "narration" / "narration.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(_mod.UploadError, match="not valid JSON"):
        _mod.resolve_video(run_dir)


# --------------------------------------------------------------------------
# embed_forms — the split is load-bearing
# --------------------------------------------------------------------------


def test_linear_form_is_a_bare_url() -> None:
    forms = _mod.embed_forms(video_id="abc123", title="GH-42 — assigning a work order")

    assert forms["linear_markdown"] == "https://www.youtube.com/watch?v=abc123"


def test_github_form_is_a_linked_poster() -> None:
    forms = _mod.embed_forms(video_id="abc123", title="GH-42 — assigning a work order")

    assert forms["github_markdown"].startswith("[<img src=")
    assert "img.youtube.com/vi/abc123/maxresdefault.jpg" in forms["github_markdown"]
    assert forms["github_markdown"].endswith("](https://www.youtube.com/watch?v=abc123)")


def test_the_two_forms_are_never_equal() -> None:
    forms = _mod.embed_forms(video_id="abc123", title="whatever")

    assert forms["linear_markdown"] != forms["github_markdown"]


# --------------------------------------------------------------------------
# Preference resolution — no invented account
# --------------------------------------------------------------------------


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEV10X_CONFIG_HOME", str(tmp_path))
    for variable in ("DEV10X_YT_ACCOUNT", "DEV10X_YT_CHANNEL", "DEV10X_YT_CATEGORY_ID"):
        monkeypatch.delenv(variable, raising=False)
    return tmp_path


def test_absent_config_resolves_no_account(config_home: Path) -> None:
    assert _mod.resolve_preference()["account"] is None


def test_missing_account_names_the_pin_command(config_home: Path) -> None:
    with pytest.raises(_mod.UploadError, match="pin --account"):
        _mod.require_account(_mod.resolve_preference())


def test_flag_beats_config(config_home: Path) -> None:
    (config_home / "yt-upload.yaml").write_text(
        "defaults:\n  account: pinned@example.com\n", encoding="utf-8"
    )

    assert _mod.resolve_preference(account="flag@example.com")["account"] == "flag@example.com"


def test_project_entry_beats_defaults(config_home: Path, tmp_path: Path) -> None:
    (config_home / "yt-upload.yaml").write_text(
        "defaults:\n"
        "  channel: UCdefault\n"
        "projects:\n"
        '  - match: ["*/my-repo-*"]\n'
        "    channel: UCproject\n",
        encoding="utf-8",
    )
    here = tmp_path / "my-repo-7"
    here.mkdir()

    assert _mod.resolve_preference(cwd=here)["channel"] == "UCproject"


def test_project_matches_on_bare_directory_name(config_home: Path, tmp_path: Path) -> None:
    """The cwd.name fallback is what makes `*/repo-*`-free patterns work; a
    full-path-only matcher would silently ignore this entry."""
    (config_home / "yt-upload.yaml").write_text(
        'projects:\n  - match: ["my-repo-7"]\n    channel: UCbyname\n',
        encoding="utf-8",
    )
    here = tmp_path / "my-repo-7"
    here.mkdir()

    assert _mod.resolve_preference(cwd=here)["channel"] == "UCbyname"


def test_defaults_apply_outside_a_matching_project(config_home: Path, tmp_path: Path) -> None:
    (config_home / "yt-upload.yaml").write_text(
        "defaults:\n"
        "  channel: UCdefault\n"
        "projects:\n"
        '  - match: ["*/my-repo-*"]\n'
        "    channel: UCproject\n",
        encoding="utf-8",
    )
    here = tmp_path / "unrelated"
    here.mkdir()

    assert _mod.resolve_preference(cwd=here)["channel"] == "UCdefault"


def test_category_falls_back_to_the_builtin(config_home: Path) -> None:
    assert _mod.resolve_preference()["category_id"] == _mod.DEFAULT_CATEGORY_ID


def test_malformed_config_raises_rather_than_silently_defaulting(config_home: Path) -> None:
    """A pinned channel that fails to parse must not resolve to 'no channel'."""
    (config_home / "yt-upload.yaml").write_text("defaults:\n  : :\n", encoding="utf-8")

    with pytest.raises(_mod.UploadError, match="not valid YAML"):
        _mod.resolve_preference()


def test_malformed_project_entry_is_skipped_not_fatal(config_home: Path, tmp_path: Path) -> None:
    """A hand-edited list item that is not a mapping must not take out the
    whole resolver — the valid entry after it still has to apply."""
    (config_home / "yt-upload.yaml").write_text(
        'projects:\n  - just-a-string\n  - match: ["*/my-repo-*"]\n    channel: UCproject\n',
        encoding="utf-8",
    )
    here = tmp_path / "my-repo-7"
    here.mkdir()

    assert _mod.resolve_preference(cwd=here)["channel"] == "UCproject"


def test_failed_write_leaves_the_previous_config_intact(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-write must not truncate a pinned channel into nothing."""
    _mod.write_config({"defaults": {"channel": "UCoriginal"}})

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(_mod.yaml, "safe_dump", boom)

    with pytest.raises(RuntimeError, match="disk full"):
        _mod.write_config({"defaults": {"channel": "UCreplacement"}})

    assert _mod.resolve_preference()["channel"] == "UCoriginal"
    assert not list(_mod.config_path().parent.glob("*.tmp"))


def test_run_gog_shells_out_with_a_fixed_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """gog is invoked as a fixed argv list with a bounded timeout and no
    shell — the properties that keep a wedged call from hanging a session."""
    captured: dict = {}

    def fake_run(argv: list[str], **kwargs: object) -> FakeProc:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return FakeProc(returncode=0)

    monkeypatch.setattr(_mod.subprocess, "run", fake_run)

    _mod._run_gog(["auth", "list"])

    assert captured["argv"] == ["gog", "auth", "list"]
    assert captured["kwargs"]["timeout"] == _mod._SUBPROCESS_TIMEOUT_SECONDS
    assert captured["kwargs"]["check"] is False


def test_pin_round_trips(config_home: Path) -> None:
    _mod.write_config({"defaults": {"account": "you@example.com", "channel": "UCxyz"}})

    resolved = _mod.resolve_preference()

    assert resolved["account"] == "you@example.com"
    assert resolved["channel"] == "UCxyz"


# --------------------------------------------------------------------------
# Failure channel — JSON on stdout, non-zero exit
# --------------------------------------------------------------------------


def test_failure_is_json_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _mod._fail("something actionable", hint="do this instead")

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["error"] == "something actionable"
    assert payload["hint"] == "do this instead"


def test_upload_error_is_translated_to_the_json_channel(
    config_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        _mod.main(["resolve-video", "--run-dir", "/nonexistent-run-dir"])

    payload = json.loads(capsys.readouterr().out)
    assert "no video directory" in payload["error"]


def test_shred_removes_the_export(tmp_path: Path) -> None:
    export = tmp_path / "token.json"
    export.write_text('{"access_token": "x"}', encoding="utf-8")

    _mod.shred(export)

    assert not export.exists()


def test_shred_tolerates_an_absent_file(tmp_path: Path) -> None:
    _mod.shred(tmp_path / "never-existed.json")


def test_shred_removes_the_mkdtemp_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The directory exists only to hold the token — leaving it behind
    accumulates one empty 0700 dir per upload, forever."""
    export = _mod.token_export_path()
    export.write_text('{"access_token": "x"}', encoding="utf-8")

    _mod.shred(export)

    assert not export.parent.exists()


def test_export_directory_is_owner_only() -> None:
    """Directory ownership is the actual control against another local user
    reading the token — not the unpredictability of the filename."""
    export = _mod.token_export_path()
    try:
        assert export.parent.stat().st_mode & 0o777 == 0o700
        assert export.parent.stat().st_uid == os.getuid()
    finally:
        export.parent.rmdir()


def test_two_calls_get_separate_directories() -> None:
    """Concurrent uploads must not be able to read or shred each other's
    token."""
    first = _mod.token_export_path()
    second = _mod.token_export_path()
    try:
        assert first.parent != second.parent
    finally:
        first.parent.rmdir()
        second.parent.rmdir()


def test_shred_warns_rather_than_raising_when_it_cannot_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cleanup must never mask the real outcome — but a surviving export is
    a live credential, so it has to be said loudly."""
    export = tmp_path / "token.json"
    export.write_text("x", encoding="utf-8")
    monkeypatch.setattr(_mod, "open", _raise_oserror, raising=False)

    _mod.shred(export)

    assert "live access token" in capsys.readouterr().err


def _raise_oserror(*_args: object, **_kwargs: object) -> None:
    raise OSError("permission denied")


# --------------------------------------------------------------------------
# gog interaction — faked at the _run_gog seam
# --------------------------------------------------------------------------


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_gog(monkeypatch: pytest.MonkeyPatch, *responses: FakeProc) -> list[list[str]]:
    """Record gog argv and reply with the queued responses, last one sticky."""
    calls: list[list[str]] = []
    queue = list(responses)

    def runner(arguments: list[str]) -> FakeProc:
        calls.append(arguments)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(_mod, "_run_gog", runner)
    return calls


def test_warm_token_succeeds_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake_gog(monkeypatch, FakeProc(returncode=0))

    _mod.warm_token("you@example.com")

    assert calls == [["youtube", "channels", "list", "--mine", "-j", "-a", "you@example.com"]]


def test_warm_token_names_the_console_url_when_api_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gog(monkeypatch, FakeProc(returncode=1, stderr="accessNotConfigured"))

    with pytest.raises(_mod.UploadError, match="youtube.googleapis.com/overview"):
        _mod.warm_token("you@example.com")


def test_warm_token_tells_you_to_keep_existing_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-authorizing without repeating the service list silently drops the
    Drive grant other skills depend on — the fix has to say so."""
    fake_gog(monkeypatch, FakeProc(returncode=1, stderr="insufficient permissions"))

    with pytest.raises(_mod.UploadError, match="gog auth list"):
        _mod.warm_token("you@example.com")


def test_warm_token_surfaces_an_unrecognized_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_gog(monkeypatch, FakeProc(returncode=1, stderr="network unreachable"))

    with pytest.raises(_mod.UploadError, match="network unreachable"):
        _mod.warm_token("you@example.com")


def _token_payload(**overrides: object) -> str:
    payload = {
        "access_token": "live-token",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _export_writer(export: Path, contents: str, calls: list | None = None) -> object:
    def runner(arguments: list[str]) -> FakeProc:
        if calls is not None:
            calls.append(arguments)
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(contents, encoding="utf-8")
        return FakeProc(returncode=0)

    return runner


def test_export_argv_is_pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Line coverage alone would not catch a dropped --overwrite or an --out
    pointed at the wrong path, so the argv itself is the assertion."""
    export = tmp_path / "token.json"
    calls: list[list[str]] = []
    monkeypatch.setattr(_mod, "_run_gog", _export_writer(export, _token_payload(), calls=calls))

    _mod.get_access_token("you@example.com", export)

    assert calls == [
        [
            "auth",
            "tokens",
            "export",
            "you@example.com",
            "--out",
            str(export),
            "--overwrite",
            "--no-input",
        ]
    ]


def test_get_access_token_returns_the_borrowed_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = tmp_path / "token.json"
    monkeypatch.setattr(_mod, "_run_gog", _export_writer(export, _token_payload()))

    assert _mod.get_access_token("you@example.com", export) == "live-token"


def test_exported_token_is_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export = tmp_path / "token.json"
    monkeypatch.setattr(_mod, "_run_gog", _export_writer(export, _token_payload()))

    _mod.get_access_token("you@example.com", export)

    assert export.stat().st_mode & 0o777 == 0o600


def test_export_failure_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gog(monkeypatch, FakeProc(returncode=3, stderr="no such account"))

    with pytest.raises(_mod.UploadError, match="gog token export failed"):
        _mod.get_access_token("you@example.com", tmp_path / "token.json")


def test_silent_export_success_with_no_file_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gog(monkeypatch, FakeProc(returncode=0))

    with pytest.raises(_mod.UploadError, match="wrote no token file"):
        _mod.get_access_token("you@example.com", tmp_path / "token.json")


def test_export_without_a_token_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export = tmp_path / "token.json"
    monkeypatch.setattr(_mod, "_run_gog", _export_writer(export, json.dumps({"scopes": []})))

    with pytest.raises(_mod.UploadError, match="no access_token"):
        _mod.get_access_token("you@example.com", export)


def test_missing_upload_scope_names_the_extra_scopes_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = tmp_path / "token.json"
    monkeypatch.setattr(
        _mod,
        "_run_gog",
        _export_writer(
            export,
            _token_payload(scopes=["https://www.googleapis.com/auth/drive"]),
        ),
    )

    with pytest.raises(_mod.UploadError, match="--extra-scopes"):
        _mod.get_access_token("you@example.com", export)


def test_token_about_to_expire_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A token that dies partway through leaves a half-published video."""

    soon = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    export = tmp_path / "token.json"
    monkeypatch.setattr(
        _mod, "_run_gog", _export_writer(export, _token_payload(access_token_expires_at=soon))
    )

    with pytest.raises(_mod.UploadError, match="too soon for an upload"):
        _mod.get_access_token("you@example.com", export)


def test_token_with_ample_life_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    export = tmp_path / "token.json"
    monkeypatch.setattr(
        _mod,
        "_run_gog",
        _export_writer(export, _token_payload(access_token_expires_at=later)),
    )

    assert _mod.get_access_token("you@example.com", export) == "live-token"


# --------------------------------------------------------------------------
# verify_via_gog — advisory, never orphans a successful upload
# --------------------------------------------------------------------------


def test_read_back_returns_the_stored_record(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"items": [{"snippet": {"channelId": "UCstored"}}]}
    fake_gog(monkeypatch, FakeProc(returncode=0, stdout=json.dumps(stored)))

    assert _mod.verify_via_gog(video_id="abc", account="a@b.c")["snippet"]["channelId"] == (
        "UCstored"
    )


def test_read_back_accepts_a_bare_list(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gog(monkeypatch, FakeProc(returncode=0, stdout=json.dumps([{"status": {}}])))

    assert _mod.verify_via_gog(video_id="abc", account="a@b.c") == {"status": {}}


@pytest.mark.parametrize(
    "proc",
    [
        FakeProc(returncode=1, stderr="boom"),
        FakeProc(returncode=0, stdout="not json"),
        FakeProc(returncode=0, stdout=json.dumps({"items": []})),
    ],
    ids=["gog-failed", "unparseable", "no-items"],
)
def test_read_back_failure_is_advisory(proc: FakeProc, monkeypatch: pytest.MonkeyPatch) -> None:
    """A verification failure must not orphan a successful upload."""
    fake_gog(monkeypatch, proc)

    assert _mod.verify_via_gog(video_id="abc", account="a@b.c") == {}


# --------------------------------------------------------------------------
# Upload — faked at the requests seam
# --------------------------------------------------------------------------


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        headers: dict | None = None,
        payload: dict | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _capturing(response: FakeResponse, captured: dict) -> object:
    def call(*args: object, **kwargs: object) -> FakeResponse:
        captured.update(kwargs)
        return response

    return call


def test_open_session_returns_the_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _mod.requests,
        "post",
        lambda *a, **k: FakeResponse(headers={"Location": "https://upload/session"}),
    )

    assert _mod.open_session(token="t", size=1, metadata={}) == "https://upload/session"


def test_open_session_sends_the_bearer_token_and_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regression that dropped the Authorization header, sent the wrong
    token, or mismatched the declared length would still execute every line
    of open_session — so the request itself has to be asserted."""
    captured: dict = {}
    monkeypatch.setattr(
        _mod.requests,
        "post",
        _capturing(FakeResponse(headers={"Location": "https://upload/session"}), captured),
    )

    _mod.open_session(token="live-token", size=4096, metadata={"snippet": {"title": "T"}})

    assert captured["headers"]["Authorization"] == "Bearer live-token"
    assert captured["headers"]["X-Upload-Content-Length"] == "4096"
    assert captured["headers"]["X-Upload-Content-Type"] == "video/mp4"
    assert captured["params"] == {"uploadType": "resumable", "part": "snippet,status"}
    assert captured["json"] == {"snippet": {"title": "T"}}
    assert captured["timeout"] == _mod._SESSION_OPEN_TIMEOUT_SECONDS


def test_upload_declares_the_real_byte_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declared Content-Length must come from the file on disk, not from
    anything the caller asserted about it."""
    video = _mp4(tmp_path, size=2048)
    put_captured: dict = {}
    monkeypatch.setattr(
        _mod.requests,
        "post",
        lambda *a, **k: FakeResponse(headers={"Location": "https://upload/session"}),
    )
    monkeypatch.setattr(
        _mod.requests, "put", _capturing(FakeResponse(payload={"id": "vid"}), put_captured)
    )

    _mod.upload(
        token="t",
        video=video,
        title="T",
        description="",
        privacy="unlisted",
        category_id="28",
    )

    assert put_captured["headers"]["Content-Length"] == "2048"
    assert put_captured["timeout"] == _mod._MEDIA_PUT_TIMEOUT_SECONDS


def test_upload_metadata_carries_privacy_and_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    post_captured: dict = {}
    monkeypatch.setattr(
        _mod.requests,
        "post",
        _capturing(FakeResponse(headers={"Location": "https://upload/session"}), post_captured),
    )
    monkeypatch.setattr(_mod.requests, "put", lambda *a, **k: FakeResponse(payload={"id": "v"}))

    _mod.upload(
        token="t",
        video=video,
        title="GH-42 — the thing",
        description="body",
        privacy="unlisted",
        category_id="27",
    )

    metadata = post_captured["json"]
    assert metadata["status"]["privacyStatus"] == "unlisted"
    assert metadata["status"]["selfDeclaredMadeForKids"] is False
    assert metadata["snippet"]["categoryId"] == "27"
    assert metadata["snippet"]["title"] == "GH-42 — the thing"
    assert metadata["snippet"]["description"] == "body"


def test_open_session_rejects_a_bad_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _mod.requests, "post", lambda *a, **k: FakeResponse(status_code=403, text="denied")
    )

    with pytest.raises(_mod.UploadError, match="could not open an upload session"):
        _mod.open_session(token="t", size=1, metadata={})


def test_open_session_rejects_a_missing_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_mod.requests, "post", lambda *a, **k: FakeResponse())

    with pytest.raises(_mod.UploadError, match="no Location header"):
        _mod.open_session(token="t", size=1, metadata={})


def test_upload_returns_the_stored_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = _mp4(tmp_path)
    monkeypatch.setattr(
        _mod.requests,
        "post",
        lambda *a, **k: FakeResponse(headers={"Location": "https://upload/session"}),
    )
    monkeypatch.setattr(
        _mod.requests, "put", lambda *a, **k: FakeResponse(payload={"id": "vid123"})
    )

    result = _mod.upload(
        token="t",
        video=video,
        title="T",
        description="",
        privacy="unlisted",
        category_id="28",
    )

    assert result["id"] == "vid123"


def test_upload_rejects_a_failed_put(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = _mp4(tmp_path)
    monkeypatch.setattr(
        _mod.requests,
        "post",
        lambda *a, **k: FakeResponse(headers={"Location": "https://upload/session"}),
    )
    monkeypatch.setattr(
        _mod.requests, "put", lambda *a, **k: FakeResponse(status_code=500, text="oops")
    )

    with pytest.raises(_mod.UploadError, match="upload failed"):
        _mod.upload(
            token="t",
            video=video,
            title="T",
            description="",
            privacy="unlisted",
            category_id="28",
        )


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def test_check_reports_the_resolved_target(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export = tmp_path / "token.json"
    monkeypatch.setattr(_mod, "token_export_path", lambda: export)
    monkeypatch.setattr(_mod, "warm_token", lambda _account: None)
    monkeypatch.setattr(_mod, "get_access_token", lambda _a, _p: "live-token")

    result = _mod.cmd_check(
        _mod.build_parser().parse_args(
            ["check", "--account", "you@example.com", "--channel", "UCxyz"]
        )
    )

    assert result["ok"] is True
    assert result["account"] == "you@example.com"
    assert result["channel"] == "UCxyz"


def test_check_shreds_the_export(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole security story rests on cleanup actually running — a
    regression that dropped the `finally` would keep 100% line coverage."""
    export = tmp_path / "token.json"
    shredded: list[Path] = []
    monkeypatch.setattr(_mod, "token_export_path", lambda: export)
    monkeypatch.setattr(_mod, "warm_token", lambda _account: None)
    monkeypatch.setattr(_mod, "get_access_token", lambda _a, _p: "live-token")
    monkeypatch.setattr(_mod, "shred", shredded.append)

    _mod.cmd_check(_mod.build_parser().parse_args(["check", "--account", "you@example.com"]))

    assert shredded == [export]


def test_upload_shreds_the_export_even_when_the_upload_raises(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    export = tmp_path / "token.json"
    shredded: list[Path] = []
    monkeypatch.setattr(_mod, "token_export_path", lambda: export)
    monkeypatch.setattr(_mod, "warm_token", lambda _account: None)
    monkeypatch.setattr(_mod, "get_access_token", lambda _a, _p: "live-token")
    monkeypatch.setattr(_mod, "shred", shredded.append)

    def failing_upload(**_kwargs: object) -> dict:
        raise _mod.UploadError("upload failed (500)")

    monkeypatch.setattr(_mod, "upload", failing_upload)

    with pytest.raises(_mod.UploadError):
        _mod.cmd_upload(
            _mod.build_parser().parse_args(
                [
                    "upload",
                    "--video",
                    str(video),
                    "--title",
                    "T",
                    "--account",
                    "you@example.com",
                ]
            )
        )

    assert shredded == [export]


def test_pin_persists_only_what_was_passed(config_home: Path) -> None:
    result = _mod.cmd_pin(_mod.build_parser().parse_args(["pin", "--account", "you@example.com"]))

    assert result["pinned"] == {"account": "you@example.com"}
    assert "yt-upload.yaml" in result["config"]


def test_pin_merges_into_existing_defaults(config_home: Path) -> None:
    _mod.cmd_pin(_mod.build_parser().parse_args(["pin", "--account", "you@example.com"]))

    _mod.cmd_pin(_mod.build_parser().parse_args(["pin", "--channel", "UCxyz"]))

    resolved = _mod.resolve_preference()
    assert resolved["account"] == "you@example.com"
    assert resolved["channel"] == "UCxyz"


def test_pin_with_nothing_to_pin_is_refused(config_home: Path) -> None:
    with pytest.raises(_mod.UploadError, match="nothing to pin"):
        _mod.cmd_pin(_mod.build_parser().parse_args(["pin"]))


def test_resolve_video_subcommand_emits_the_selection(
    run_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_video(run_dir, "qa-gh-42.mp4")

    assert _mod.main(["resolve-video", "--run-dir", str(run_dir)]) == 0

    assert json.loads(capsys.readouterr().out)["narrated"] is False


def _stub_upload_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, stored_channel: str | None
) -> None:
    monkeypatch.setattr(_mod, "token_export_path", lambda: tmp_path / "token.json")
    monkeypatch.setattr(_mod, "warm_token", lambda _account: None)
    monkeypatch.setattr(_mod, "get_access_token", lambda _a, _p: "live-token")
    monkeypatch.setattr(
        _mod,
        "upload",
        lambda **_kwargs: {
            "id": "vid123",
            "snippet": {"channelId": stored_channel},
            "status": {"privacyStatus": "unlisted"},
        },
    )
    monkeypatch.setattr(_mod, "verify_via_gog", lambda **_kwargs: {})


def test_upload_subcommand_returns_both_embed_forms(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel="UCxyz")

    result = _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "GH-42 — the thing",
                "--account",
                "you@example.com",
            ]
        )
    )

    assert result["linear_markdown"] == "https://www.youtube.com/watch?v=vid123"
    assert result["github_markdown"].startswith("[<img src=")
    assert result["thumbnail_may_404"] is True


def test_upload_refuses_a_channel_mismatch(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong-channel upload has already happened — the error has to name
    the URL so it can be moved or deleted."""
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel="UCwrong")

    with pytest.raises(_mod.UploadError, match="watch\\?v=vid123"):
        _mod.cmd_upload(
            _mod.build_parser().parse_args(
                [
                    "upload",
                    "--video",
                    str(video),
                    "--title",
                    "T",
                    "--account",
                    "you@example.com",
                    "--channel",
                    "UCexpected",
                ]
            )
        )


def test_upload_reports_a_privacy_mismatch(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel=None)

    result = _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
                "--privacy",
                "public",
            ]
        )
    )

    assert result["privacy_mismatch"] == "requested 'public' but YouTube stored 'unlisted'"


def test_private_privacy_is_flagged_as_unshareable(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`private` plays for the uploader alone, so a caller sharing evidence
    almost never wants it. The original script warned; the JSON rewrite must
    not lose that signal."""
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel=None)
    monkeypatch.setattr(
        _mod,
        "upload",
        lambda **_kwargs: {
            "id": "vid123",
            "snippet": {},
            "status": {"privacyStatus": "private"},
        },
    )

    result = _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
                "--privacy",
                "private",
            ]
        )
    )

    assert "teammates see 'unavailable'" in result["privacy_note"]


def test_private_warns_before_the_network_call(
    config_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The payload note arrives after the video exists. A mistyped
    --privacy private has to be abortable, so the warning fires first."""
    video = _mp4(tmp_path)
    order: list[str] = []
    monkeypatch.setattr(_mod, "token_export_path", lambda: tmp_path / "token.json")
    monkeypatch.setattr(_mod, "warm_token", lambda _account: order.append("network"))
    monkeypatch.setattr(_mod, "get_access_token", lambda _a, _p: "live-token")
    monkeypatch.setattr(
        _mod,
        "upload",
        lambda **_kwargs: {
            "id": "vid123",
            "snippet": {},
            "status": {"privacyStatus": "private"},
        },
    )
    monkeypatch.setattr(_mod, "verify_via_gog", lambda **_kwargs: {})

    _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
                "--privacy",
                "private",
            ]
        )
    )

    assert "plays only for the uploader" in capsys.readouterr().err
    assert order == ["network"]


def test_unverified_upload_says_the_privacy_check_proved_nothing(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With read-back unavailable the comparison falls back to the insert
    echo, which reports what was requested — so it can never mismatch. The
    caller must not read that silence as confirmation."""
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel=None)

    result = _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
            ]
        )
    )

    assert result["verified"] is False
    assert "proves nothing" in result["verification_note"]


def test_verified_upload_reports_confirmed_state(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel=None)
    monkeypatch.setattr(
        _mod,
        "verify_via_gog",
        lambda **_kwargs: {
            "snippet": {"channelId": "UCstored"},
            "status": {"privacyStatus": "unlisted"},
        },
    )

    result = _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
            ]
        )
    )

    assert result["verified"] is True
    assert "verification_note" not in result
    assert result["channel_id"] == "UCstored"


def test_token_lifetime_is_reported_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Diagnostic must not reach the parsed stdout channel."""
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    export = tmp_path / "token.json"
    monkeypatch.setattr(
        _mod,
        "_run_gog",
        _export_writer(export, _token_payload(access_token_expires_at=later)),
    )

    _mod.get_access_token("you@example.com", export)

    captured = capsys.readouterr()
    assert "access token valid for" in captured.err
    assert captured.out == ""


def test_unlisted_upload_carries_no_privacy_note(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    _stub_upload_path(monkeypatch, tmp_path, stored_channel=None)

    result = _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
            ]
        )
    )

    assert "privacy_note" not in result


def test_upload_reads_a_description_file(
    config_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = _mp4(tmp_path)
    description = tmp_path / "d.txt"
    description.write_text("what the viewer will see", encoding="utf-8")
    captured: dict = {}
    _stub_upload_path(monkeypatch, tmp_path, stored_channel=None)

    def recording_upload(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {"id": "vid123", "snippet": {}, "status": {"privacyStatus": "unlisted"}}

    monkeypatch.setattr(_mod, "upload", recording_upload)

    _mod.cmd_upload(
        _mod.build_parser().parse_args(
            [
                "upload",
                "--video",
                str(video),
                "--title",
                "T",
                "--account",
                "you@example.com",
                "--description-file",
                str(description),
            ]
        )
    )

    assert captured["description"] == "what the viewer will see"


def test_upload_refuses_a_missing_video(config_home: Path, tmp_path: Path) -> None:
    with pytest.raises(_mod.UploadError, match="video not found"):
        _mod.cmd_upload(
            _mod.build_parser().parse_args(
                [
                    "upload",
                    "--video",
                    str(tmp_path / "absent.mp4"),
                    "--title",
                    "T",
                    "--account",
                    "you@example.com",
                ]
            )
        )


def test_upload_refuses_a_non_mp4(config_home: Path, tmp_path: Path) -> None:
    """Playwright records .webm; YouTube handles it poorly enough that the
    conversion step must not be skippable by accident."""
    webm = tmp_path / "v.webm"
    webm.write_bytes(b"\0" * 16)

    with pytest.raises(_mod.UploadError, match="convert-evidence.sh video"):
        _mod.cmd_upload(
            _mod.build_parser().parse_args(
                [
                    "upload",
                    "--video",
                    str(webm),
                    "--title",
                    "T",
                    "--account",
                    "you@example.com",
                ]
            )
        )


# --------------------------------------------------------------------------
# main dispatch
# --------------------------------------------------------------------------


def test_timeout_is_reported_as_wedged(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

    def timeout(_args: object) -> None:
        raise subprocess.TimeoutExpired(cmd="gog", timeout=1)

    monkeypatch.setattr(_mod, "cmd_resolve_video", timeout)

    with pytest.raises(SystemExit):
        _mod.main(["resolve-video", "--run-dir", str(run_dir)])

    assert "wedged" in json.loads(capsys.readouterr().out)["error"]


def test_sigterm_becomes_an_ordinary_exit_so_finally_runs() -> None:
    """Python's default SIGTERM kills without unwinding, which would leave
    the borrowed token on disk. The handler converts it to SystemExit."""
    with pytest.raises(SystemExit) as exit_info:
        _mod._shred_on_signal(signal.SIGTERM, None)

    assert exit_info.value.code == 128 + signal.SIGTERM


def test_unexpected_exception_still_lands_on_the_json_channel(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A traceback to stderr would leave a stdout-parsing caller with
    nothing to branch on — every failure arrives through one channel."""

    def boom(_args: object) -> None:
        raise KeyError("id")

    monkeypatch.setattr(_mod, "cmd_resolve_video", boom)

    with pytest.raises(SystemExit):
        _mod.main(["resolve-video", "--run-dir", str(run_dir)])

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "unexpected KeyError" in json.loads(captured.out)["error"]


def test_request_exception_is_reported_on_stdout(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(_args: object) -> None:
        raise _mod.requests.RequestException("connection reset")

    monkeypatch.setattr(_mod, "cmd_resolve_video", boom)

    with pytest.raises(SystemExit):
        _mod.main(["resolve-video", "--run-dir", str(run_dir)])

    assert "connection reset" in json.loads(capsys.readouterr().out)["error"]
