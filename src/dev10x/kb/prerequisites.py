"""External tools the harvest needs, with the command that installs each (GH-1985).

A missing tool is reported with its install command and never worked
around: `pip install` into the system Python or a silent fallback to a
description-only summary would both hide the gap from the user.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from dev10x.core.domain.common.result import Result, err, ok


@dataclass(frozen=True)
class Tool:
    binary: str
    purpose: str
    install: str


YT_DLP = Tool(
    binary="yt-dlp",
    purpose="YouTube captions and reach metrics",
    install="uv tool install yt-dlp",
)
DEFUDDLE = Tool(
    binary="defuddle",
    purpose="readable text of web pages",
    install="npm install -g defuddle",
)
WHISPER = Tool(
    binary="whisper-ctranslate2",
    purpose="local transcription of podcast audio (faster-whisper)",
    install="uv tool install whisper-ctranslate2",
)
OBSIDIAN = Tool(
    binary="obsidian",
    purpose="daily-note path and vault root of the running Obsidian app",
    install="install Obsidian and enable its command line interface in Settings → General",
)

ALL_TOOLS = (YT_DLP, DEFUDDLE, WHISPER, OBSIDIAN)


def require(tool: Tool) -> Result[str]:
    """The tool's absolute path, or an error naming the install command."""
    path = shutil.which(tool.binary)
    if path is None:
        return err(
            f"{tool.binary} is not installed (needed for {tool.purpose}). "
            f"Install it with: {tool.install}",
            tool=tool.binary,
            install=tool.install,
        )
    return ok(path)


def report() -> dict[str, dict[str, str | None]]:
    return {
        tool.binary: {
            "path": shutil.which(tool.binary),
            "purpose": tool.purpose,
            "install": tool.install,
        }
        for tool in ALL_TOOLS
    }
