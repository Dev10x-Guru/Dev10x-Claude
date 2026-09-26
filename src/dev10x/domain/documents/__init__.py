"""Document-shaped domain aggregates (Plan, Task, session/config YAML).

Re-exports only — no logic, classes, or constants (CLAUDE.md § 3).

Where is the Repository pattern here? There is no class named
``Repository`` in this package. For ``Plan``/``Task`` the role is split
across the ``Plan`` aggregate in :mod:`dev10x.domain.documents.plan`
(in-memory state + invariants) and the IO/transaction orchestration in
its ``*.service`` layer (``dev10x.plan.service``) — the same
responsibility a Fowler Repository owns, expressed as an aggregate plus
a service rather than a single class. See
``dev10x.domain.common.repository_ref.RepositoryRef`` for a value
object that is deliberately *not* this pattern despite its name.

Why is there no shared ``Document`` base class? Decided in GH-1454, on
the evidence of the GH-1431 split. The documents here have little in
common beyond "backed by a file". ``config_yaml`` and ``session_yaml``
are read-only. ``SessionState`` and ``PlanSummary`` are aggregates with
no persistence of their own. ``SettingsDocument`` parses JSON strictly
and raises on purpose. The one thing that really was duplicated, the
tolerant YAML load, now lives in :mod:`.yaml_mapping`. The hazard a base
class was meant to remove is two writers of one file taking different
lock sidecars (GH-825). That depends on the *file*, not the class: a
document must use whichever lock helper that file's other writers use,
so one canonical lock in a base class would move some file onto the
wrong sidecar. ``tests/domain/test_file_locks_sidecar_consistency.py``
enforces the per-file rule across the whole tree. Add a new persisted
document as its own frozen dataclass, and reuse :mod:`.yaml_mapping`
when its load contract matches.
"""
