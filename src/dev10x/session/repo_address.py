"""Resolve the `org/repo` a repo-addressed `projects:` list matches (GH-1375).

ADR-0026 converges every repo-addressed config — playbooks,
``settings-pr-merge.yaml``, ``gitmoji.yaml`` — onto ``nameWithOwner``.
Matching the full origin URL instead is protocol-dependent: a glob
written against ``https://github.com/org/repo.git`` silently fails on
``git@github.com:org/repo.git``, so the same config resolves for one
contributor and not another purely by clone style.

The lookup is deliberately offline — ``git remote get-url origin``, not
``gh repo view`` — so ``dev10x config doctor`` never blocks on the
network. A repo with no ``origin`` remote is a documented outcome, not
an error to swallow: the caller renders it as "did not look".
"""

from __future__ import annotations

import subprocess

from dev10x.domain.common.result import Result, err, ok

_GIT_TIMEOUT_SECONDS = 5.0

NO_ORIGIN_REASON = "no `origin` remote — repo-addressed Tier 2 config cannot be resolved"


def parse_name_with_owner(url: str) -> str | None:
    """Extract ``org/repo`` from an SSH or HTTPS remote URL.

    Returns ``None`` when the URL carries no recognisable owner/name
    pair, so the caller reports an unresolved target rather than
    matching against a half-parsed string.
    """
    text = url.strip()
    if not text:
        return None
    if text.endswith(".git"):
        text = text[: -len(".git")]
    if "://" in text:
        # Drop the host: `https://github.com/solo` carries no owner/name
        # pair, and keeping the host would hand back `github.com/solo`.
        _, _, after_host = text.split("://", 1)[1].partition("/")
        text = after_host
    elif "@" in text and ":" in text:
        text = text.split(":", 1)[1]
    text = text.strip("/")
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return None
    return "/".join(parts[-2:])


def resolve_name_with_owner(*, cwd: str | None = None) -> Result[str]:
    """Return the checkout's ``org/repo``, or an error naming the cause."""
    from dev10x.domain.git_context import GitContext

    try:
        url = GitContext(cwd=cwd).run("remote", "get-url", "origin", timeout=_GIT_TIMEOUT_SECONDS)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return err(NO_ORIGIN_REASON)
    name_with_owner = parse_name_with_owner(url)
    if name_with_owner is None:
        return err(f"origin remote {url!r} carries no org/repo pair")
    return ok(name_with_owner)
