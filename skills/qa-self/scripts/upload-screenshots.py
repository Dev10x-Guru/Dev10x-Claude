#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests>=2.0,<3"]
# ///
"""Upload evidence files (screenshots, videos) to Linear.

Usage:
    uv run --script upload-screenshots.py upload <file1.png> [<file2.mp4> ...]

Commands:
    upload   Upload files to Linear, print asset URLs as JSON

Supported formats:
    Images: png, jpg, jpeg, gif, webp
    Videos: mp4, webm

Environment:
    LINEAR_API_KEY  Linear personal API key (falls back to secret-tool lookup)
"""

import json
import os
import subprocess
import sys

import requests

LINEAR_API = "https://api.linear.app/graphql"


def _keyring_lookup(*, service: str, key: str) -> str | None:
    if sys.platform == "darwin":
        cmd = ["security", "find-generic-password", "-s", service, "-a", key, "-w"]
    else:
        cmd = ["secret-tool", "lookup", "service", service, "key", key]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_api_key() -> str:
    key = os.environ.get("LINEAR_API_KEY", "")
    if not key:
        key = _keyring_lookup(service="linear", key="api_key") or ""
    if not key:
        print("ERROR: No Linear API key found", file=sys.stderr)
        sys.exit(1)
    return key


def upload_file(api_key: str, filepath: str) -> str | None:
    headers = {"Authorization": api_key, "Content-Type": "application/json"}

    with open(filepath, "rb") as f:
        content = f.read()

    ext = filepath.rsplit(".", 1)[-1].lower()
    content_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "mp4": "video/mp4",
        "webm": "video/webm",
    }.get(ext, "application/octet-stream")

    mutation = """mutation($size: Int!, $contentType: String!, $filename: String!) {
      fileUpload(size: $size, contentType: $contentType, filename: $filename) {
        uploadFile { uploadUrl assetUrl headers { key value } }
        success
      }
    }"""

    filename = os.path.basename(filepath)
    file_size = len(content)
    variables = {"size": file_size, "contentType": content_type, "filename": filename}

    resp = requests.post(
        LINEAR_API,
        json={"query": mutation, "variables": variables},
        headers=headers,
    )
    data = resp.json()

    if "errors" in data:
        print(f"ERROR upload URL for {filename}: {data['errors']}", file=sys.stderr)
        return None

    upload_file_data = data["data"]["fileUpload"]["uploadFile"]
    upload_url = upload_file_data["uploadUrl"]
    asset_url = upload_file_data["assetUrl"]
    signed_headers = upload_file_data.get("headers") or []

    upload_headers: dict[str, str] = {}
    for h in signed_headers:
        upload_headers[h["key"]] = h["value"]
    upload_headers["Content-Type"] = content_type
    upload_headers["Content-Length"] = str(file_size)

    put_resp = requests.put(upload_url, data=content, headers=upload_headers)

    if put_resp.status_code in (200, 201):
        return asset_url

    print(
        f"ERROR PUT {filename}: {put_resp.status_code} {put_resp.text[:200]}",
        file=sys.stderr,
    )
    return None


def cmd_upload(args: list[str]) -> None:
    if not args:
        print("Usage: upload-screenshots.py upload <file1> [file2 ...]", file=sys.stderr)
        sys.exit(1)

    api_key = get_api_key()
    results: list[dict[str, str]] = []

    for filepath in args:
        if not os.path.exists(filepath):
            print(f"SKIP {filepath}: file not found", file=sys.stderr)
            continue
        print(f"Uploading {os.path.basename(filepath)}...", file=sys.stderr)
        url = upload_file(api_key, filepath)
        if url:
            results.append({"file": filepath, "url": url})
            print(f"  OK: {url}", file=sys.stderr)
        else:
            print("  FAILED", file=sys.stderr)

    # Output JSON to stdout for piping
    print(json.dumps(results, indent=2))


def cmd_comment(args: list[str]) -> None:
    print(
        "Use Linear MCP create_comment instead of this command.\n"
        "The personal API key cannot write to all team issues.",
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "upload":
        cmd_upload(args)
    elif cmd == "comment":
        cmd_comment(args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
