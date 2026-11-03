#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0,<7"]
# ///
"""Parse databases.yaml files into tab-separated output for db.sh.

Usage:
    parse-databases.py <file1.yaml> [<file2.yaml> ...]

Output format (one line per database, tab-separated):
    name\tbackend\tenv_var\tkeyring_service\tkeyring_account\tlabel\taliases

Databases from earlier files take precedence (first-seen wins).
"""

from __future__ import annotations

import sys

import yaml


def parse_files(paths: list[str]) -> list[dict[str, str]]:
    seen: set[str] = set()
    rows: list[dict[str, str]] = []

    for path in paths:
        try:
            with open(file=path) as fh:
                data = yaml.safe_load(stream=fh)
        except (OSError, yaml.YAMLError) as exc:
            print(f"WARNING: skipping {path}: {exc}", file=sys.stderr)
            continue

        if not isinstance(data, dict):
            continue

        databases = data.get("databases", {})
        if not isinstance(databases, dict):
            continue

        for name, entry in databases.items():
            if name in seen:
                continue
            seen.add(name)

            if not isinstance(entry, dict):
                continue

            backend = entry.get("backend", "env")
            rows.append(
                {
                    "name": str(name),
                    "backend": str(backend),
                    "env_var": str(entry.get("env_var", "")),
                    "keyring_service": str(entry.get("keyring_service", "")),
                    "keyring_account": str(entry.get("keyring_account", "")),
                    "label": str(entry.get("label", name)),
                    "aliases": ",".join(str(a) for a in entry.get("aliases", [])),
                }
            )

    return rows


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: parse-databases.py <file1.yaml> [<file2.yaml> ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    rows = parse_files(paths=sys.argv[1:])
    for row in rows:
        fields = [
            row["name"],
            row["backend"],
            row["env_var"],
            row["keyring_service"],
            row["keyring_account"],
            row["label"],
            row["aliases"],
        ]
        print("\t".join(fields))


if __name__ == "__main__":
    main()
