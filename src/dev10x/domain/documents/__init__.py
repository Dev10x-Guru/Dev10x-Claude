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
"""
