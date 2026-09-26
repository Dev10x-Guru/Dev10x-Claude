# Data-Retrieval Naming Conventions

Moved out of `CLAUDE.md` under its 100-line budget (GH-1438).

Prefer `get_*` for functions that fetch and return data. Use
`load_*` for reading and parsing config/catalog files (`load_yaml`,
`load_json`, `load_config`) and `read_*` for byte- or line-level
file I/O (`read_applied_version`, `read_plugin_version`) — both are
blessed, dominant conventions, not exceptions. Reserve `fetch_*` for
names carrying protocol/domain semantics (`git fetch`, HTTP fetch)
or documented exceptions such as `fetch_mergeable` and
`fetch_merged_prs` (`skills/release/collect_prs.py`). Do not
rename-sweep existing `load_*`/`read_*` functions to `get_*`.
