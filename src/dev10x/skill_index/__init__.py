"""Re-export of ``dev10x.teach.skill_index`` at its pre-ADR-0034 path (GH-1544).

Every ``dev10x.skill_index.<name>`` resolves to the same module object as
``dev10x.teach.skill_index.<name>``; see ``dev10x.core.module_alias``.
"""

from typing import TYPE_CHECKING

from dev10x.core.module_alias import alias_package

if TYPE_CHECKING:
    from dev10x.teach.skill_index import (
        SkillCatalog,
        SkillEntry,
        generate_all,
        scan_skill_dirs,
    )

alias_package(old=__name__, new="dev10x.teach.skill_index")

__all__ = ["SkillCatalog", "SkillEntry", "generate_all", "scan_skill_dirs"]
