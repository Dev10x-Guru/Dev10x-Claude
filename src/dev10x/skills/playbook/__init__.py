"""Re-export of ``dev10x.core.skills.playbook`` at its pre-ADR-0034 path (GH-1540).

Every ``dev10x.skills.playbook.<name>`` resolves to the same module object
as ``dev10x.core.skills.playbook.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.core.skills.playbook import (
        FieldDiff,
        PlaybookDiff,
        PlayDiff,
        StepDiff,
        UserPlaybook,
        compare_playbooks,
        find_user_playbooks,
        plugin_default_path,
        render_markdown_report,
    )

alias_package(old=__name__, new="dev10x.core.skills.playbook")

__all__ = [
    "FieldDiff",
    "PlayDiff",
    "PlaybookDiff",
    "StepDiff",
    "UserPlaybook",
    "compare_playbooks",
    "find_user_playbooks",
    "plugin_default_path",
    "render_markdown_report",
]
