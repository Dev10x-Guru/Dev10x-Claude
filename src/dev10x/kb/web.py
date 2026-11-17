"""Web page adapter: readable article text through Defuddle (GH-1985).

Defuddle is the extraction engine behind Obsidian Web Clipper, so a
page harvested here reads the way it would if clipped by hand: no
navigation, ads or comment threads.
"""

from __future__ import annotations

import json
import subprocess

from dev10x.core import subprocess_utils
from dev10x.core.domain.common.result import Result, SuccessResult, err, ok
from dev10x.kb.prerequisites import DEFUDDLE, require
from dev10x.kb.record import SourceKind, SourceRecord, SourceRef

DEFUDDLE_TIMEOUT_SECONDS = 120


def fetch_web(ref: SourceRef) -> Result[SourceRecord]:
    binary = require(DEFUDDLE)
    if not isinstance(binary, SuccessResult):
        return binary
    try:
        completed = subprocess_utils.run(
            [binary.value, "parse", ref.url, "--json"],
            capture_output=True,
            text=True,
            timeout=DEFUDDLE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return err(f"defuddle timed out reading {ref.url}. Please try again.")
    if completed.returncode != 0:
        return err(f"defuddle could not read {ref.url}: {completed.stderr.strip()[-400:]}")
    try:
        page = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return err(f"defuddle returned unreadable output for {ref.url}: {exc}")
    if not isinstance(page, dict):
        return err(f"defuddle returned unexpected output for {ref.url}")

    def text(key: str) -> str:
        value = page.get(key)
        return "" if value is None else str(value).strip()

    return ok(
        SourceRecord(
            id=ref.id,
            kind=SourceKind.WEB,
            url=ref.url,
            title=text("title") or ref.url,
            author=text("author") or text("site") or text("domain"),
            published=text("published"),
            description=text("description"),
            transcript=text("contentMarkdown"),
            metrics={"site": text("site") or text("domain"), "words": text("wordCount")},
        )
    )
