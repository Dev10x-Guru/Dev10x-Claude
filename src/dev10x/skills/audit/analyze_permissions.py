#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic Phase 4 permission friction analysis for skill-audit.

Parses a normalized markdown transcript, loads allow rules from
settings.json, and reports:
- Unmatched tool calls with classification
- Toxicity detection for structural friction
- Script hygiene audit
- Proposed allow rules

Usage:
    analyze-permissions.py <transcript.md> [settings.json] [output.md]

If settings.json is omitted, uses ~/.claude/settings.local.json.
If output.md is omitted, writes to stdout.
"""

import fnmatch
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

TURN_RE = re.compile(
    r"^## Turn (\d+) \[([^\]]+)\] (USER|ASSISTANT)",
    re.MULTILINE,
)

TOOL_INPUT_BLOCK_RE = re.compile(
    r"^\*\*Tool: `([^`]+)`\*\*\n```\n(.*?)```",
    re.MULTILINE | re.DOTALL,
)

TOOL_RE = re.compile(r"^\*\*Tool: `([^`]+)`\*\*", re.MULTILINE)

PERMISSION_TOOLS = {"Bash", "Read", "Write", "Edit"}

ALLOW_RULE_RE = re.compile(r"^(\w+)\((.+)\)$")

CHAIN_RE = re.compile(r"&&|;\s")
SUBSHELL_RE = re.compile(r"\$\(")
ENV_PREFIX_RE = re.compile(r"^[A-Z_]+=\S+\s")
GIT_C_RE = re.compile(r"^git\s+-C\s+")
COMMENT_PREFIX_RE = re.compile(r"^#")
HEREDOC_RE = re.compile(r"cat\s+<<|cat\s+>|echo\s+>|printf\s+>")

DANGEROUS_COMMANDS = re.compile(
    r"git\s+push\s+--force|"
    r"git\s+reset\s+--hard|"
    r"git\s+clean\s+-f|"
    r"git\s+checkout\s+\.|"
    r"rm\s+-rf\s+(?!/tmp)|"
    r"--no-verify|"
    r"--force"
)

# Paths matching mktmp's high-entropy suffix — Write to these triggers
# the Write tool's overwrite gate even with explicit allow-rules (GH-39).
MKTMP_PATH_RE = re.compile(r"/tmp/Dev10x/[^/]+/[^/]+\.[A-Za-z0-9]{6,}\.\w+$")

# Known commands that exit non-zero on benign deprecation warnings while
# the operation actually succeeded (GH-41 — Projects classic on `gh pr edit`).
EXIT_FALSE_POSITIVE_RE = re.compile(r"^gh\s+pr\s+edit\b")

# PreToolUse hook denial signal in tool result text (best-effort —
# only available when the parser captures result blocks).
HOOK_BLOCK_RE = re.compile(r"^BLOCKED:|hook error", re.MULTILINE)


@dataclass
class ToolCall:
    turn: int
    time: str
    tool: str
    command: str
    file_path: str = ""


@dataclass
class AllowRule:
    tool: str
    pattern: str
    raw: str


@dataclass
class Finding:
    index: int
    turn: int
    time: str
    tool: str
    command_display: str
    classification: str
    fix: str


@dataclass
class HygieneFinding:
    index: int
    target: str
    issue: str
    classification: str
    fix: str


def parse_tool_calls(text: str) -> list[ToolCall]:
    turn_matches = list(TURN_RE.finditer(text))
    calls: list[ToolCall] = []

    for i, tm in enumerate(turn_matches):
        role = tm.group(3)
        if role != "ASSISTANT":
            continue

        turn_num = int(tm.group(1))
        turn_time = tm.group(2)
        start = tm.end()
        end = turn_matches[i + 1].start() if i + 1 < len(turn_matches) else len(text)
        body = text[start:end]

        for tool_match in TOOL_INPUT_BLOCK_RE.finditer(body):
            tool_name = tool_match.group(1)
            if tool_name not in PERMISSION_TOOLS:
                continue
            input_text = tool_match.group(2).strip()
            tc = ToolCall(
                turn=turn_num,
                time=turn_time,
                tool=tool_name,
                command="",
            )
            if tool_name == "Bash":
                cmd_match = re.search(r"command=(.+?)(?:,\s*\w+=|\Z)", input_text, re.DOTALL)
                tc.command = cmd_match.group(1).strip() if cmd_match else input_text[:200]
            else:
                path_match = re.search(r"file_path=([^\s,]+)", input_text)
                tc.file_path = path_match.group(1) if path_match else ""
                tc.command = tc.file_path
            calls.append(tc)

        bare_tools = set()
        for bm in TOOL_RE.finditer(body):
            bare_tools.add(bm.group(1))
        named = {tc.tool for tc in calls if tc.turn == turn_num}
        for name in bare_tools - named:
            if name in PERMISSION_TOOLS:
                calls.append(
                    ToolCall(
                        turn=turn_num,
                        time=turn_time,
                        tool=name,
                        command="(no input captured)",
                    )
                )

    return calls


def parse_allow_rules(settings_path: str) -> list[AllowRule]:
    path = Path(settings_path)
    if not path.exists():
        return []

    data = json.loads(path.read_text())
    rules: list[AllowRule] = []

    allow_list = data.get("permissions", {}).get("allow", [])
    for entry in allow_list:
        raw = entry if isinstance(entry, str) else str(entry)
        m = ALLOW_RULE_RE.match(raw)
        if m:
            rules.append(AllowRule(tool=m.group(1), pattern=m.group(2), raw=raw))

    return rules


def parse_additional_directories(settings_path: str) -> list[str]:
    """Return permissions.additionalDirectories entries (GH-40, GH-46)."""
    path = Path(settings_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return list(data.get("permissions", {}).get("additionalDirectories", []))


def detect_known_friction(
    calls: list[ToolCall],
    *,
    additional_dirs: list[str],
    project_root: str | None = None,
) -> list[Finding]:
    """Detect friction patterns no allow-rule can prevent (GH-46).

    The base allow-rule analysis only catches Bash command vs allow-rule
    mismatch. Real sessions hit other gates that allow-rules cannot
    bypass:

    - WRITE_OVERWRITE_GATE — Write to an existing file (typical with
      mktmp paths) prompts on every call.
    - WORKSPACE_GATE — Write/Edit/Read to a path outside the project
      root prompts unless the dir is in additionalDirectories.
    - EXIT_CODE_FALSE_POSITIVE — `gh pr edit` exits 1 on the
      Projects-classic deprecation while the operation succeeds.

    These findings are added on top of the standard unmatched-call list
    even when allow-rules formally cover the call.
    """
    findings: list[Finding] = []
    idx = 0
    project_prefix = (project_root or os.getcwd()).rstrip("/") + "/"
    home_prefix = os.path.expanduser("~/").rstrip("/") + "/"

    for tc in calls:
        if tc.tool == "Bash":
            if EXIT_FALSE_POSITIVE_RE.match(tc.command):
                idx += 1
                findings.append(
                    Finding(
                        index=idx,
                        turn=tc.turn,
                        time=tc.time,
                        tool=tc.tool,
                        command_display=tc.command[:60],
                        classification="EXIT_CODE_FALSE_POSITIVE",
                        fix="Use REST API (`gh api PATCH …/pulls/<n>`) instead",
                    )
                )
            continue

        target = tc.file_path or tc.command
        if not target:
            continue

        if tc.tool == "Write" and MKTMP_PATH_RE.search(target):
            idx += 1
            findings.append(
                Finding(
                    index=idx,
                    turn=tc.turn,
                    time=tc.time,
                    tool=tc.tool,
                    command_display=target[:60],
                    classification="WRITE_OVERWRITE_GATE",
                    fix="Make mktmp return path without pre-creating (GH-39)",
                )
            )

        if not (target.startswith(project_prefix) or target.startswith(home_prefix)):
            covered = any(target.startswith(d.rstrip("/") + "/") for d in additional_dirs)
            if not covered:
                idx += 1
                findings.append(
                    Finding(
                        index=idx,
                        turn=tc.turn,
                        time=tc.time,
                        tool=tc.tool,
                        command_display=target[:60],
                        classification="WORKSPACE_GATE",
                        fix=(
                            f"Register parent dir under additionalDirectories"
                            f" (e.g. `/permissions add {Path(target).parent}`)"
                        ),
                    )
                )

    return findings


def matches_allow_rule(tc: ToolCall, rules: list[AllowRule]) -> bool:
    for rule in rules:
        if rule.tool != tc.tool:
            continue

        pattern = rule.pattern
        if tc.tool == "Bash":
            if pattern.endswith(":*"):
                prefix = pattern[:-2]
                if tc.command.startswith(prefix):
                    return True
            elif pattern.endswith("*"):
                prefix = pattern[:-1]
                if tc.command.startswith(prefix):
                    return True
            elif tc.command == pattern:
                return True
        else:
            target = tc.file_path or tc.command
            if pattern.endswith("**"):
                dir_prefix = pattern[:-2]
                if target.startswith(dir_prefix):
                    return True
            elif fnmatch.fnmatch(target, pattern):
                return True

    return True if not rules else False


def classify_toxicity(command: str) -> str | None:
    if COMMENT_PREFIX_RE.match(command):
        return "PREFIX_POISONED_COMMENT"
    if ENV_PREFIX_RE.match(command):
        return "PREFIX_POISONED_ENVVAR"
    if GIT_C_RE.match(command):
        return "PREFIX_POISONED_GIT_C"
    if SUBSHELL_RE.search(command) and CHAIN_RE.search(command):
        return "PREFIX_POISONED_SUBSHELL"
    if CHAIN_RE.search(command) and not SUBSHELL_RE.search(command):
        return "PREFIX_POISONED_CHAIN"
    if HEREDOC_RE.search(command):
        return "HOOK_BLOCKED_HEREDOC"
    return None


MULTI_WORD_COMMANDS = {"gh", "git", "uv", "docker", "kubectl", "aws"}


def _extract_command_prefix(command: str) -> str:
    parts = command.split()
    if not parts:
        return command
    if parts[0] in MULTI_WORD_COMMANDS and len(parts) >= 2:
        subcommand = parts[1]
        if not subcommand.startswith("-"):
            return f"{parts[0]} {subcommand}"
    return parts[0]


def classify_unmatched(
    tc: ToolCall,
    rules: list[AllowRule],
) -> tuple[str, str]:
    if tc.tool == "Bash":
        toxicity = classify_toxicity(command=tc.command)
        if toxicity:
            if "PREFIX_POISONED" in toxicity:
                return toxicity, "Restructure to avoid prefix poisoning"
            return toxicity, "Use Write tool + file reference instead"

        if DANGEROUS_COMMANDS.search(tc.command):
            return "CORRECTLY_PROMPTED", "No action — risky command"

        has_similar = any(
            r.tool == "Bash" and tc.command[:10].startswith(r.pattern[:10]) for r in rules
        )
        if has_similar:
            return "PATTERN_TOO_NARROW", "Widen existing allow rule pattern"

        prefix = _extract_command_prefix(command=tc.command)
        return "MISSING_RULE", f"Add: Bash({prefix}:*)"

    target = tc.file_path or tc.command
    has_similar = any(r.tool == tc.tool and target[:10].startswith(r.pattern[:10]) for r in rules)
    if has_similar:
        return "PATH_NOT_COVERED", f"Widen {tc.tool} glob pattern"

    parent = str(Path(target).parent) if target else ""
    return "MISSING_RULE", f"Add: {tc.tool}({parent}/**)"


def analyze_permissions(
    calls: list[ToolCall],
    rules: list[AllowRule],
) -> list[Finding]:
    findings: list[Finding] = []
    idx = 0

    for tc in calls:
        if matches_allow_rule(tc=tc, rules=rules):
            continue

        idx += 1
        classification, fix = classify_unmatched(tc=tc, rules=rules)
        cmd_display = tc.command[:60] if tc.command else tc.file_path[:60]
        findings.append(
            Finding(
                index=idx,
                turn=tc.turn,
                time=tc.time,
                tool=tc.tool,
                command_display=cmd_display,
                classification=classification,
                fix=fix,
            )
        )

    return findings


def count_nuisance_patterns(findings: list[Finding]) -> list[Finding]:
    pattern_counts: dict[str, list[Finding]] = {}
    for f in findings:
        if f.classification == "MISSING_RULE":
            key = f.tool + ":" + f.command_display.split()[0] if f.command_display else f.tool
            pattern_counts.setdefault(key, []).append(f)

    for key, group in pattern_counts.items():
        if len(group) >= 3:
            for f in group:
                f.classification = f"NUISANCE_PATTERN ({len(group)}x)"

    return findings


def audit_script_hygiene(skills_dir: str, tools_dir: str) -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    idx = 0
    dirs_to_scan = []

    if os.path.isdir(skills_dir):
        dirs_to_scan.append(Path(skills_dir))
    if os.path.isdir(tools_dir):
        dirs_to_scan.append(Path(tools_dir))

    for scan_dir in dirs_to_scan:
        for py_file in scan_dir.rglob("*.py"):
            if not py_file.is_file():
                continue

            try:
                content = py_file.read_text()
            except (OSError, UnicodeDecodeError):
                continue

            first_line = content.split("\n", 1)[0] if content else ""

            if first_line.startswith("#!") and "uv run" not in first_line:
                if "python" in first_line:
                    idx += 1
                    findings.append(
                        HygieneFinding(
                            index=idx,
                            target=str(py_file),
                            issue=f"Shebang: {first_line}",
                            classification="WRONG_SHEBANG",
                            fix="Change to: #!/usr/bin/env -S uv run --script",
                        )
                    )

            if "uv run" in first_line and "# /// script" not in content:
                idx += 1
                findings.append(
                    HygieneFinding(
                        index=idx,
                        target=str(py_file),
                        issue="Has uv shebang but no PEP 723 metadata block",
                        classification="MISSING_PEP723",
                        fix="Add # /// script block after shebang",
                    )
                )

            file_stat = py_file.stat()
            if not (file_stat.st_mode & stat.S_IXUSR):
                if first_line.startswith("#!"):
                    idx += 1
                    findings.append(
                        HygieneFinding(
                            index=idx,
                            target=str(py_file),
                            issue=f"Mode {oct(file_stat.st_mode)[-3:]} — not executable",
                            classification="NOT_EXECUTABLE",
                            fix="chmod +x",
                        )
                    )

    for scan_dir in dirs_to_scan:
        for skill_md in scan_dir.rglob("SKILL.md"):
            try:
                content = skill_md.read_text()
            except (OSError, UnicodeDecodeError):
                continue

            for m in re.finditer(r"uv run --script\s+(\S+\.py)", content):
                script_path = m.group(1)
                expanded = os.path.expanduser(script_path)
                if os.path.isfile(expanded):
                    try:
                        script_content = Path(expanded).read_text()
                        if "uv run" in script_content.split("\n", 1)[0]:
                            idx += 1
                            findings.append(
                                HygieneFinding(
                                    index=idx,
                                    target=f"{skill_md}",
                                    issue=f"Redundant uv run --script for {script_path}",
                                    classification="REDUNDANT_UV_PREFIX",
                                    fix="Call script directly (has uv shebang)",
                                )
                            )
                    except (OSError, UnicodeDecodeError):
                        pass

    return findings


def propose_allow_rules(findings: list[Finding]) -> list[str]:
    seen: set[str] = set()
    proposals: list[str] = []

    for f in findings:
        if "MISSING_RULE" in f.classification or "NUISANCE" in f.classification:
            if "Add:" in f.fix:
                rule = f.fix.split("Add: ", 1)[1]
                if rule not in seen:
                    seen.add(rule)
                    proposals.append(rule)

    return proposals


def write_output(
    findings: list[Finding],
    hygiene: list[HygieneFinding],
    proposals: list[str],
    out: TextIO,
) -> None:
    out.write("# Phase 4: Permission Friction Analysis\n\n")

    out.write("## Unmatched Tool Calls\n\n")
    if findings:
        out.write("| # | Turn | Time | Tool | Command (truncated) | Classification | Fix |\n")
        out.write("|---|------|------|------|---------------------|----------------|-----|\n")
        for f in findings:
            cmd = f.command_display.replace("|", "\\|")
            fix = f.fix.replace("|", "\\|")
            out.write(
                f"| {f.index} | {f.turn} | {f.time} | {f.tool} "
                f"| {cmd} | {f.classification} | {fix} |\n"
            )
    else:
        out.write("No unmatched tool calls found.\n")

    out.write("\n---\n\n")

    out.write("## Script Hygiene Audit\n\n")
    if hygiene:
        out.write("| # | Target | Issue | Classification | Fix |\n")
        out.write("|---|--------|-------|----------------|-----|\n")
        for h in hygiene:
            target = h.target.replace("|", "\\|")
            issue = h.issue.replace("|", "\\|")
            out.write(f"| {h.index} | {target} | {issue} | {h.classification} | {h.fix} |\n")
    else:
        out.write("No script hygiene issues found.\n")

    out.write("\n---\n\n")

    out.write("## Proposed Allow Rules\n\n")
    if proposals:
        for p in proposals:
            out.write(f"- `{p}`\n")
    else:
        out.write("No new allow rules proposed.\n")

    out.write("\n---\n\n")

    summary: dict[str, int] = {}
    for f in findings:
        base = f.classification.split("(")[0].strip()
        summary[base] = summary.get(base, 0) + 1
    out.write("## Summary\n\n")
    out.write(f"**Total unmatched calls:** {len(findings)}\n")
    out.write(f"**Script hygiene issues:** {len(hygiene)}\n")
    out.write(f"**Proposed allow rules:** {len(proposals)}\n\n")
    if summary:
        out.write("**By classification:**\n")
        for cls, count in sorted(summary.items(), key=lambda x: -x[1]):
            out.write(f"- {cls}: {count}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    transcript_path = sys.argv[1]
    settings_path = (
        sys.argv[2]
        if len(sys.argv) >= 3 and sys.argv[2].endswith(".json")
        else os.path.expanduser("~/.claude/settings.local.json")
    )
    output_path = None
    if len(sys.argv) >= 3 and sys.argv[-1].endswith(".md"):
        output_path = sys.argv[-1]

    transcript = Path(transcript_path).read_text()
    calls = parse_tool_calls(text=transcript)
    rules = parse_allow_rules(settings_path=settings_path)
    additional_dirs = parse_additional_directories(settings_path=settings_path)
    findings = analyze_permissions(calls=calls, rules=rules)
    findings = count_nuisance_patterns(findings=findings)
    extra = detect_known_friction(calls=calls, additional_dirs=additional_dirs)
    # Renumber the extra findings to continue past the base ones
    base_count = len(findings)
    for offset, finding in enumerate(extra, start=1):
        finding.index = base_count + offset
    findings.extend(extra)

    skills_dir = os.path.expanduser("~/.claude/skills")
    tools_dir = os.path.expanduser("~/.claude/tools")
    hygiene = audit_script_hygiene(skills_dir=skills_dir, tools_dir=tools_dir)

    proposals = propose_allow_rules(findings=findings)

    if output_path:
        with open(output_path, "w") as f:
            write_output(findings=findings, hygiene=hygiene, proposals=proposals, out=f)
        print(f"Phase 4 output written to {output_path}", file=sys.stderr)
    else:
        write_output(findings=findings, hygiene=hygiene, proposals=proposals, out=sys.stdout)


if __name__ == "__main__":
    main()
