# MCP Tool Availability by Plugin Version

Moved out of `.claude/rules/mcp-tools.md` (GH-1606): version history is
not needed to make a call, and the rule loads in every session.

MCP tools are added incrementally. Document the minimum plugin version
supporting each tool:

| Tool | Server | Introduced | Availability |
|------|--------|------------|--------------|
| `detect_tracker` | `cli` | PR #126 | v0.25.0+ |
| `pr_detect` | `cli` | PR #126 | v0.25.0+ |
| `issue_get` | `cli` | PR #126 | v0.25.0+ |
| `issue_comments` | `cli` | PR #126 | v0.25.0+ |
| `issue_create` | `cli` | PR #552 | v0.44.0+ |
| `issue_close` | `cli` | GH-268 | v0.74.0+ |
| `issue_reopen` | `cli` | GH-268 | v0.74.0+ |
| `pr_get` | `cli` | GH-267 | v0.74.0+ |
| `pr_comments` | `cli` | PR #126 | v0.25.0+ |
| `pr_comment_reply` | `cli` | PR #399 | v0.37.0+ |
| `pr_review_comment_edit` | `cli` | GH-304 | v0.76.0+ |
| `pr_review_edit` | `cli` | GH-778 | v0.86.0+ |
| `pr_ready` | `cli` | GH-779 | v0.86.0+ |
| `pr_close` | `cli` | GH-924 | v0.92.0+ |
| `pr_list` | `cli` | GH-1359 | v0.103.0+ |
| `pr_issue_comment` | `cli` | GH-205 | v0.72.0+ |
| `request_review` | `cli` | PR #126 | v0.25.0+ |
| `detect_base_branch` | `cli` | PR #191 | v0.30.0+ |
| `verify_pr_state` | `cli` | PR #191 | v0.30.0+ |
| `pre_pr_checks` | `cli` | PR #191 | v0.30.0+ |
| `create_pr` | `cli` | PR #191 | v0.30.0+ |
| `update_pr` | `cli` | GH-60 | v0.70.0+ |
| `merge_pr` | `cli` | GH-232 | v0.73.0+ |
| `run_tests` | `cli` | GH-238 | v0.74.0+ |
| `run_node_tests` | `cli` | GH-703 | v0.80.0+ |
| `milestone_close` | `cli` | GH-187 | v0.71.0+ |
| `milestone_create` | `cli` | GH-220 | v0.73.0+ |
| `milestone_reopen` | `cli` | GH-850 | v0.90.0+ |
| `milestone_edit` | `cli` | GH-850 | v0.90.0+ |
| `milestone_list` | `cli` | GH-1319 | v0.103.0+ |
| `issue_edit` | `cli` | GH-220 | v0.73.0+ |
| `issue_comment` | `cli` | GH-220 | v0.73.0+ |
| `issue_comment_edit` | `cli` | GH-283 | v0.75.0+ |
| `issue_comment_delete` | `cli` | GH-283 | v0.75.0+ |
| `issue_list` | `cli` | GH-220 | v0.73.0+ |
| `triage_roster` | `cli` | GH-1102 | v0.96.0+ |
| `slack_thread_is_forward` | `cli` | GH-218 | v0.73.0+ |
| `milestones_bulk_create` | `cli` | GH-222 | v0.73.0+ |
| `issues_bulk_create` | `cli` | GH-222 | v0.73.0+ |
| `issues_bulk_edit` | `cli` | GH-222 | v0.73.0+ |
| `generate_commit_list` | `cli` | PR #191 | v0.30.0+ |
| `post_summary_comment` | `cli` | PR #191 | v0.30.0+ |
| `pr_notify` | `cli` | PR #191 | v0.30.0+ |
| `push_safe` | `cli` | PR #126 | v0.25.0+ |
| `rebase_groom` | `cli` | PR #126 | v0.25.0+ |
| `create_worktree` | `cli` | PR #126 | v0.25.0+ |
| `mass_rewrite` | `cli` | PR #288 | v0.30.0+ |
| `start_split_rebase` | `cli` | PR #288 | v0.30.0+ |
| `next_worktree_name` | `cli` | PR #126 | v0.25.0+ |
| `setup_aliases` | `cli` | PR #288 | v0.30.0+ |
| `mktmp` | `cli` | PR #160 | v0.26.0+ |
| `resolve_plugin_origin` | `cli` | GH-816 | v0.92.0+ |
| `audit_hook_log_path` | `cli` | GH-29 | v0.69.0+ |
| `audit_hook_recent` | `cli` | GH-29 | v0.69.0+ |
| `record_upgrade` | `cli` | GH-109 | v0.72.0+ |
| `cluster_review_comments` | `cli` | GH-346 | v0.80.0+ |
| `candidate_rules_report` | `cli` | GH-347 | v0.80.0+ |
| `validate_candidate_patterns` | `cli` | GH-348 | v0.80.0+ |
| `author_reference_rules` | `cli` | GH-349 | v0.80.0+ |
| `rule_confidence_report` | `cli` | GH-350 | v0.80.0+ |
| `record_rule_feedback` | `cli` | GH-350 | v0.80.0+ |
| `request_sampling` | `cli` | GH-343 | v0.80.0+ |
| `background_preamble` | `cli` | GH-610 | v0.80.0+ |
| `resolve_gate` | `cli` | GH-742 (ADR-0016 spike) | v0.83.0+ |
| `preset_pin_status` | `cli` | GH-855 | v0.92.0+ |
| `pin_gate_preset` | `cli` | GH-855 | v0.92.0+ |
| `supervisor_review_status` | `cli` | GH-1161 | v0.97.0+ |
| `pin_supervisor_review` | `cli` | GH-1165 | v0.97.0+ |
| `tracker_status` | `cli` | GH-768 | v0.95.0+ |
| `pin_tracker` | `cli` | GH-768 | v0.95.0+ |
| `ide_status` | `cli` | GH-1261 | v0.99.0+ |
| `pin_ide` | `cli` | GH-1261 | v0.99.0+ |
| `pr_labels` | `cli` | GH-1008 | v0.94.0+ |
| `issue_labels` | `cli` | GH-1322 | v0.102.0+ |
| `ci_rerun` | `cli` | GH-1674 | v0.109.0+ |
| `task_index_get` | `cli` | GH-1009 | v0.94.0+ |
| `task_index_append` | `cli` | GH-1009 | v0.94.0+ |
| `task_index_set` | `cli` | GH-1009 | v0.94.0+ |
| `usage_blocks` | `cli` | GH-878 | v0.90.0+ |
| `permission_catalog_gap` | `cli` | GH-1175 | v0.97.0+ |
| `permission_triage` | `cli` | GH-1676 | v0.109.0+ |
| `permission_grant` | `cli` | GH-1676 | v0.109.0+ (write; not seeded) |
| `gchat_watch_arm` | `cli` | GH-1682 | v0.109.0+ |
| `gchat_watch_disarm` | `cli` | GH-1682 | v0.109.0+ |
| `gchat_watch_list` | `cli` | GH-1682 | v0.109.0+ |
| `query` | `db` | PR #126 | v0.25.0+ |

When adding a new tool, update this table and note any dependencies on
specific CLI commands or external programs. Skills should declare required
tools explicitly in `allowed-tools:` to catch availability mismatches early.
