from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any, Literal

from dev10x.ci_review.outbox import OUTBOX_ENV, append_entry
from dev10x.core.subprocess_utils import effective_cwd

REAL_GH_ENV: str = "DEV10X_CI_REAL_GH"

# Fail closed: anything not listed as a read is recorded, never run, so a
# command nobody classified cannot post from a dry run.
_READ_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "pr": frozenset({"view", "list", "diff", "checks", "status"}),
    "issue": frozenset({"view", "list", "status"}),
    "repo": frozenset({"view"}),
    "run": frozenset({"view", "list"}),
    "auth": frozenset({"status"}),
}
_READ_GROUPS: frozenset[str] = frozenset({"search", "--version", "version", "help"})
_API_VALUE_FLAGS: frozenset[str] = frozenset(
    {
        "-X",
        "--method",
        "-f",
        "--raw-field",
        "-F",
        "--field",
        "--input",
        "-H",
        "--header",
        "-q",
        "--jq",
        "-t",
        "--template",
        "--hostname",
        "--cache",
        "-p",
        "--preview",
    }
)
_API_FIELD_FLAGS: frozenset[str] = frozenset({"-f", "--raw-field", "-F", "--field", "--input"})
_SHORT_ATTACHED: frozenset[str] = frozenset({"-X", "-f", "-F"})


def classify(*, argv: list[str]) -> Literal["read", "write"]:
    if not argv:
        return "read"
    group = argv[0]
    if group == "api":
        return _classify_api(args=argv[1:])
    if group in _READ_GROUPS:
        return "read"
    reads = _READ_SUBCOMMANDS.get(group, frozenset())
    return "read" if argv[1:2] and argv[1] in reads else "write"


def _classify_api(*, args: list[str]) -> Literal["read", "write"]:
    positionals, options = _split_api_args(args=args)
    method = next(
        (value.upper() for flag, value in options if flag in {"-X", "--method"}),
        None,
    )
    if method is not None and method != "GET":
        return "write"
    if positionals[:1] == ["graphql"]:
        return "write" if "mutation" in _graphql_query(options=options).lower() else "read"
    has_fields = any(flag in _API_FIELD_FLAGS for flag, _ in options)
    return "write" if has_fields and method is None else "read"


def _split_api_args(*, args: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    positionals: list[str] = []
    options: list[tuple[str, str]] = []
    tokens = iter(args)
    for token in tokens:
        if token.startswith("--") and "=" in token:
            flag, value = token.split("=", 1)
            options.append((flag, value))
        elif token in _API_VALUE_FLAGS:
            options.append((token, next(tokens, "")))
        elif token[:2] in _SHORT_ATTACHED and len(token) > 2:
            options.append((token[:2], token[2:]))
        elif token.startswith("-"):
            options.append((token, ""))
        else:
            positionals.append(token)
    return positionals, options


def _graphql_query(*, options: list[tuple[str, str]]) -> str:
    for flag, value in options:
        if flag not in _API_FIELD_FLAGS or not value.startswith("query="):
            continue
        query = value.removeprefix("query=")
        if flag in {"-F", "--field"} and query.startswith("@"):
            return _read_text(path=query[1:])
        return query
    return ""


def _read_text(*, path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _body_file(*, argv: list[str]) -> str | None:
    tokens = iter(argv)
    is_api = argv[:1] == ["api"]
    for token in tokens:
        if token.startswith("--body-file="):
            return token.split("=", 1)[1]
        if token == "--body-file" or (token == "-F" and not is_api):
            return next(tokens, None)
        if is_api and token in {"-F", "--field"}:
            value = next(tokens, "")
            if value.startswith("body=@"):
                return value.removeprefix("body=@")
    return None


def _reads_stdin(*, argv: list[str], body_file: str | None) -> bool:
    pairs = zip(argv, argv[1:], strict=False)
    return body_file == "-" or any(flag == "--input" and value == "-" for flag, value in pairs)


def record_write(*, argv: list[str], outbox: Path, cwd: str, stdin: str | None) -> None:
    entry: dict[str, Any] = {"kind": "gh", "argv": ["gh", *argv], "cwd": cwd}
    if stdin is not None:
        entry["stdin"] = stdin
    body_file = _body_file(argv=argv)
    if body_file and body_file != "-":
        entry["body_file_content"] = _read_text(path=str(Path(cwd) / body_file))
    append_entry(path=outbox, entry=entry)


def write_shim(*, bin_dir: Path, python: str, real_gh: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "gh"
    # -I keeps the untrusted checkout (the cwd) off sys.path.
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f": ${{{REAL_GH_ENV}:={shlex.quote(real_gh)}}}\n"
        f"export {REAL_GH_ENV}\n"
        f'exec {shlex.quote(python)} -I -m dev10x.ci_review.gh_shim "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def main(*, argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if classify(argv=args) == "write":
        body_file = _body_file(argv=args)
        stdin = sys.stdin.read() if _reads_stdin(argv=args, body_file=body_file) else None
        record_write(
            argv=args,
            outbox=Path(os.environ[OUTBOX_ENV]),
            cwd=effective_cwd() or os.getcwd(),
            stdin=stdin,
        )
        print("{}")
        return 0
    real_gh = os.environ[REAL_GH_ENV]
    os.execv(real_gh, [real_gh, *args])
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry, run via `python -m`
    sys.exit(main())
