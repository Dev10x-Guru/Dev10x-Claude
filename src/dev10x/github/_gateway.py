"""Re-export of ``dev10x.core.github._gateway`` at its pre-ADR-0034 path (GH-1536).

The old name is the same module object as the new one, so every
``dev10x.github._gateway.<name>`` patch target keeps intercepting each
caller; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_module

if TYPE_CHECKING:
    from dev10x.core.github._gateway import *  # noqa: F403
    from dev10x.core.github._gateway import (
        _GH_RETRY_POLICY,
        _bot_env,
        _detect_repo,
        _gh_api,
        _gh_api_raw,
        _parse_gh_api_result,
        _resolve_repo,
        _run_and_parse,
    )

alias_module(old=__name__, new="dev10x.core.github._gateway")
