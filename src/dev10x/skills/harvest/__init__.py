"""Review-pattern harvesting — read-only MVP (M4 milestone).

Provides functions to fetch merged/closed PRs and their review threads
from GitHub repositories. The data structures here are consumed by
downstream modules that cluster and score patterns (#346) and emit
a candidate-rules report (#347).
"""
