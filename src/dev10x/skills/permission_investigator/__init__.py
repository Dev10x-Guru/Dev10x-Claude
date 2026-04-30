"""Permission Pattern Investigator (GH-47).

Materializes a controlled fixture, applies candidate rule shapes
to target settings files, and aggregates per-shape results into a
matrix that records whether the engine auto-approved or prompted.

This package owns the deterministic, non-Claude pieces. The
subagent dispatch loop that actually exercises each rule shape
lives in ``skills/permission-investigator/SKILL.md`` because the
Agent tool is only callable from Claude tool-use protocol.
"""
