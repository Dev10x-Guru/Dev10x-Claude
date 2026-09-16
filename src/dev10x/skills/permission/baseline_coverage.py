"""Does every baseline rule reach the seeding path? (GH-1313)

``skills/upgrade-cleanup/projects.yaml`` is the authoritative permission
catalog: ``ensure_base`` and ``seed_worktree`` render settings files from
its flat lists and from nothing else. ``baseline-permissions.yaml``'s
``groups:`` block is a second catalog of comparable size that no seeding
path reads — a rule written there reaches a settings file only if someone
runs ``permission doctor --enable-group`` for its group by name.

That is how GH-1100's E18 and E19 happened twice over: a ``cp`` rule
covering the one path a hard-deny excepts, and a ``git nopager`` rule the
plugin steers agents toward in three places, both existed only in the
grouped catalog. Each was written down, referenced by skills, relied on
by hooks — and still prompted, because being catalogued and being seeded
are different facts and nothing compared them.

This module compares them. :func:`unseeded_baseline_rules` is the
question "which grouped rules cannot reach a settings file", and the
answer must be empty or deliberate.

Three exclusion mechanisms, all explicit by name rather than by
predicate — a predicate absorbs the next omission silently, which is the
failure this module exists to stop:

- :data:`OPT_IN_GROUPS` — tier-3 groups are opt-in by design, so their
  rules are correctly absent from the shipped flat lists. Naming the
  groups instead of filtering on ``tier == 3`` means re-tagging a seeded
  group as tier 3 fails loudly rather than quietly leaving the guard's
  field of view.
- :data:`RULES_NOT_SEEDED` — individual tier-1/tier-2 rules that are
  deliberately not shipped, each carrying its reason. The precedent is
  ``enumerate_mcp.WRITE_TOOLS_NOT_SEEDED``: an explicit list makes an
  omission a conscious edit, where a heuristic absorbs the next one
  silently.
- :data:`UNTRIAGED_BACKLOG` — the 189 divergences that already existed
  when this guard was written. A ratchet, not an exemption: it lets the
  guard bite on *new* divergence today rather than waiting on a triage
  that is a security decision and belongs to a supervisor. It may shrink
  and must never grow.

The seeded side is deliberately not a hand-written list of section
names. It is built by folding every tracker and IDE block into the
config and handing the result to :func:`migrate_flat_config` — the same
projection ``ensure_base`` uses — so a section this module forgot to
read cannot masquerade as a rule the catalog never had.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from dev10x.domain.common.policy_migration import migrate_flat_config

#: Sections of ``projects.yaml`` that carry permission rules. Pinned so a
#: newly-added rule-bearing section fails :func:`rule_bearing_sections`'
#: check instead of being silently omitted from the seeded set — an
#: omission would make this guard *stricter*, but an unnoticed one also
#: makes its failures unreadable.
FLAT_SECTIONS: tuple[str, ...] = ("base_permissions", "base_denies", "base_asks")

#: Per-tracker and per-IDE blocks, folded into the flat sections by
#: ``ensure_base`` once the project's tracker/IDE is resolved. The guard
#: folds *all* of them: any user may pin any tracker, so a rule shipped
#: under one of these keys is reachable and must not read as unseeded.
KEYED_SECTIONS: dict[str, str] = {
    "tracker_permissions": "base_permissions",
    "tracker_denies": "base_denies",
    "ide_permissions": "base_permissions",
    "ide_denies": "base_denies",
}

OPT_IN_GROUPS: frozenset[str] = frozenset(
    {
        "node-dev-loop",
        "sudo-apt",
        "media-and-format",
        "gog-readonly",
        "gog-credentialed",
        "aws-readonly",
        "bigquery-readonly",
        "kubernetes-readonly",
        "network-diagnostics",
        "build-tools",
        "railway-cli",
        "obsidian-cli",
        "mcp-google-workspace-readonly",
        "secrets-listing-readonly",
    }
)

#: Tier-1/tier-2 rules deliberately absent from the seeding path, by rule
#: string. Add an entry only with a reason a reviewer can check.
RULES_NOT_SEEDED: dict[str, str] = {}

#: Divergence that predates this guard: tier-1/tier-2 rules the grouped
#: catalog declares and no seeding path delivers. This is a **ratchet**,
#: not an exemption list. It exists so the guard can fail on new
#: divergence today instead of waiting for a triage this module cannot
#: responsibly do on its own.
#:
#: Each entry needs a decision, one of: ship it in
#: ``skills/upgrade-cleanup/projects.yaml``; move it to
#: :data:`RULES_NOT_SEEDED` with a reason; or delete it from the grouped
#: catalog. The set may shrink freely and must never grow — adding to it
#: is what the guard is for, and ``test_backlog_only_shrinks`` refuses it.
#:
#: The triage is a security decision, not a mechanical one, which is why
#: it is not done here. The set contains rules that grant arbitrary code
#: execution (``npx:*``, ``pip install:*``, ``docker exec:*``,
#: ``python3:*``), raw database access the ``Dev10x:db`` skill exists to
#: route around (``psql:*``), tracker writes, and raw ``gh`` spellings
#: the skill-redirect hook deliberately steers to MCP wrappers
#: (``gh pr merge``, ``gh issue close``). Seeding those wholesale would
#: widen every Dev10x user's default permission surface, which is the
#: opposite of what GH-1313 is for.
BACKLOG_STARTING_SIZE = 189

UNTRIAGED_BACKLOG: frozenset[str] = frozenset(
    {
        # git-core
        "Bash(git switch:*)",
        "Bash(git commit -m:*)",
        "Bash(git pull:*)",
        "Bash(git rebase -i:*)",
        "Bash(git reset:*)",
        "Bash(git restore:*)",
        "Bash(git restore --staged:*)",
        "Bash(git merge:*)",
        "Bash(git merge-tree:*)",
        "Bash(git mv:*)",
        "Bash(git tag:*)",
        "Bash(git cherry-pick:*)",
        "Bash(git cherry:*)",
        "Bash(git ls-remote:*)",
        "Bash(git worktree:*)",
        "Bash(git check-ignore:*)",
        "Bash(git grep:*)",
        "Bash(git config --show-origin:*)",
        "Bash(git diff-tree:*)",
        # git-aliases-dev10x — GH-1100 E19: the plugin steers agents at
        # `git nopager` in three places and never seeds the rule.
        "Bash(git nopager:*)",
        "Bash(git nocolor:*)",
        # github-cli
        "Bash(gh auth login:*)",
        "Bash(gh auth status:*)",
        "Bash(gh browse:*)",
        "Bash(gh repo list:*)",
        "Bash(gh pr reopen:*)",
        "Bash(gh pr merge:*)",
        "Bash(gh issue status:*)",
        "Bash(gh issue close:*)",
        "Bash(gh issue edit:*)",
        "Bash(gh label create:*)",
        "Bash(gh label edit:*)",
        "Bash(gh milestone:*)",
        "Bash(gh run download:*)",
        "Bash(gh run rerun:*)",
        # dev10x-scaffolding
        "Read(/tmp/claude/git/**)",
        "Edit(/tmp/claude/git/**)",
        "Read(/tmp/Dev10x/**)",
        "Edit(/tmp/Dev10x/**)",
        "Read(~/.claude/plugins/marketplaces/Dev10x-Guru/**)",
        "Read(~/.claude/plugins/cache/Dev10x-Guru/**)",
        "Bash(${CLAUDE_PLUGIN_ROOT}/bin/**)",
        "Bash(${CLAUDE_PLUGIN_ROOT}/hooks/scripts/**)",
        "Bash(${CLAUDE_PLUGIN_ROOT}/skills/**)",
        "Bash(${CLAUDE_PLUGIN_ROOT}/lib/**)",
        # dev10x-cli
        "Bash(uvx dev10x session seed:*)",
        "Bash(uvx dev10x skill notify:*)",
        # shell-helpers
        "Bash(rg --files *)",
        "Bash(sed:*)",
        "Bash(sed *)",
        "Bash(awk *)",
        "Bash(awk:*)",
        "Bash(xargs cat:*)",
        "Bash(xargs ls:*)",
        "Bash(xargs rg:*)",
        "Bash(chmod:*)",
        "Bash(chmod +x:*)",
        "Bash(chmod a+x:*)",
        "Bash(chmod u+x:*)",
        "Bash(chmod -x:*)",
        "Bash(mkdir:*)",
        "Bash(ln:*)",
        "Bash(printenv:*)",
        "Bash(env:*)",
        "Bash(pwd:*)",
        "Bash(alias:*)",
        "Bash(source:*)",
        "Bash(tar *)",
        "Bash(gzip *)",
        "Bash(base64:*)",
        "Bash(curl -fsSL:*)",
        "Bash(curl -s*:*)",
        "Bash(curl -si:*)",
        "Bash(curl -sI:*)",
        "Bash(which *)",
        "Bash([ -f .git ])",
        # python-toolchain
        "Bash(uv:*)",
        "Bash(pip list:*)",
        "Bash(pip show:*)",
        "Bash(pip index:*)",
        "Bash(pip install:*)",
        "Bash(pipx list:*)",
        "Bash(python:*)",
        "Bash(python3:*)",
        "Bash(ipython:*)",
        "Bash(ruff check:*)",
        "Bash(ruff format:*)",
        "Bash(black:*)",
        "Bash(isort:*)",
        "Bash(mypy:*)",
        "Bash(python -m pytest *)",
        "Bash(pytest:*)",
        # imagemagick-evidence
        "Bash(magick:*)",
        "Bash(montage:*)",
        "Bash(convert:*)",
        # node-toolchain
        "Bash(node *)",
        "Bash(node:*)",
        "Bash(npm:*)",
        "Bash(npm run:*)",
        "Bash(npm test:*)",
        "Bash(npm view:*)",
        "Bash(npm run lint:*)",
        "Bash(npx:*)",
        "Bash(npx eslint:*)",
        "Bash(npx prettier:*)",
        "Bash(npx prettier --write:*)",
        "Bash(npx tsc:*)",
        "Bash(npx jest:*)",
        "Bash(npx vitest:*)",
        "Bash(npx vitest run:*)",
        "Bash(pnpm:*)",
        "Bash(pnpm test:*)",
        "Bash(pnpm lint:*)",
        "Bash(pnpm build:*)",
        "Bash(pnpm check:*)",
        "Bash(pnpm exec:*)",
        "Bash(pnpm remove:*)",
        "Bash(yarn:*)",
        "Bash(yarn test)",
        "Bash(yarn build *)",
        "Bash(yarn install *)",
        "Bash(yarn eslint *)",
        "Bash(yarn prettier *)",
        "Bash(yarn lint:eslint:*)",
        "Bash(yarn lint:tsc)",
        # docker
        "Bash(docker compose:*)",
        "Bash(docker ps:*)",
        "Bash(docker logs:*)",
        "Bash(docker inspect:*)",
        "Bash(docker exec:*)",
        "Bash(docker image:*)",
        "Bash(docker images:*)",
        "Bash(docker network:*)",
        "Bash(docker pull:*)",
        "Bash(docker run --rm:*)",
        "Bash(docker start:*)",
        "Bash(docker stop:*)",
        "Bash(docker rm:*)",
        "Bash(docker info:*)",
        "Bash(docker history:*)",
        # database-readonly
        "Bash(psql:*)",
        "Bash(pg_dump:*)",
        # apt-and-system
        "Bash(apt list:*)",
        "Bash(apt-cache policy:*)",
        "Bash(dpkg:*)",
        "Bash(flatpak list:*)",
        "Bash(pgrep:*)",
        "Bash(lsmod)",
        "Bash(lspci)",
        # mcp-sentry-readonly
        "mcp__claude_ai_Sentry__find_organizations",
        "mcp__claude_ai_Sentry__find_projects",
        "mcp__claude_ai_Sentry__get_sentry_resource",
        "mcp__claude_ai_Sentry__search_events",
        "mcp__claude_ai_Sentry__search_issues",
        "mcp__claude_ai_Sentry__search_sentry_tools",
        # mcp-atlassian-readonly
        "mcp__claude_ai_Atlassian__atlassianUserInfo",
        "mcp__claude_ai_Atlassian__getAccessibleAtlassianResources",
        "mcp__claude_ai_Atlassian__getIssueLinkTypes",
        "mcp__claude_ai_Atlassian__getJiraIssue",
        "mcp__claude_ai_Atlassian__getJiraIssueRemoteIssueLinks",
        "mcp__claude_ai_Atlassian__getJiraIssueTypeMetaWithFields",
        "mcp__claude_ai_Atlassian__getJiraProjectIssueTypesMetadata",
        "mcp__claude_ai_Atlassian__getTransitionsForJiraIssue",
        "mcp__claude_ai_Atlassian__getVisibleJiraProjects",
        "mcp__claude_ai_Atlassian__lookupJiraAccountId",
        "mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql",
        "mcp__claude_ai_Atlassian__fetch",
        "mcp__claude_ai_Atlassian__search",
        # mcp-atlassian-write
        "mcp__claude_ai_Atlassian__createJiraIssue",
        "mcp__claude_ai_Atlassian__editJiraIssue",
        "mcp__claude_ai_Atlassian__addCommentToJiraIssue",
        "mcp__claude_ai_Atlassian__createIssueLink",
        "mcp__claude_ai_Atlassian__transitionJiraIssue",
        "mcp__claude_ai_Atlassian__addWorklogToJiraIssue",
        # vercel-cli-readonly
        "Bash(vercel ls:*)",
        "Bash(vercel list:*)",
        "Bash(vercel inspect:*)",
        "Bash(vercel logs:*)",
        "Bash(vercel whoami:*)",
        "Bash(vercel teams ls:*)",
        "Bash(vercel projects ls:*)",
        "Bash(vercel domains ls:*)",
        "Bash(vercel certs ls:*)",
        "Bash(vercel dns ls:*)",
        "Bash(vercel git ls:*)",
        # readonly-skills
        "Skill(code-review)",
        "Skill(security-review)",
        "Skill(review)",
        "Skill(simplify)",
    }
)


@dataclass(frozen=True)
class BaselineRule:
    """One rule as the grouped catalog declares it."""

    group: str
    tier: int
    rule: str


def enumerate_baseline_rules(*, catalog: dict) -> list[BaselineRule]:
    """Every rule under ``groups:``, in declaration order.

    Duplicates across groups are preserved: the same rule listed twice is
    two declarations, and collapsing them would hide a group whose whole
    contents happen to be covered elsewhere.
    """
    groups = catalog.get("groups")
    if not isinstance(groups, dict):
        return []
    rules: list[BaselineRule] = []
    for name, group in groups.items():
        if not isinstance(group, dict):
            continue
        tier = group.get("tier")
        for rule in group.get("rules") or []:
            if isinstance(rule, str):
                rules.append(
                    BaselineRule(
                        group=str(name),
                        tier=tier if isinstance(tier, int) else 0,
                        rule=rule,
                    )
                )
    return rules


def rule_bearing_sections(*, config: dict) -> set[str]:
    """Sections of ``projects.yaml`` that look like they carry rules.

    Names the shape rather than the known keys, so a section added later
    is reported here and forces a decision about whether it is on the
    write path.
    """
    suffixes = ("_permissions", "_denies", "_asks")
    return {key for key in config if isinstance(key, str) and key.endswith(suffixes)}


def _folded_config(*, config: dict) -> dict:
    folded = copy.deepcopy(config)
    for section in FLAT_SECTIONS:
        entries = folded.get(section)
        folded[section] = list(entries) if isinstance(entries, list) else []
    for section, target in KEYED_SECTIONS.items():
        block = config.get(section)
        if not isinstance(block, dict):
            continue
        for entries in block.values():
            if isinstance(entries, list):
                folded[target].extend(entry for entry in entries if isinstance(entry, str))
    return folded


def seeded_rules(*, config: dict) -> set[str]:
    """Every rule ``ensure_base`` can write, across all trackers and IDEs."""
    policies = migrate_flat_config(config=_folded_config(config=config), baseline_policies=[])
    return {policy.signature for policy in policies}


def unseeded_baseline_rules(*, catalog: dict, config: dict) -> list[BaselineRule]:
    """Grouped rules that no seeding path can deliver, and that nothing excuses."""
    seeded = seeded_rules(config=config)
    return [
        entry
        for entry in enumerate_baseline_rules(catalog=catalog)
        if entry.group not in OPT_IN_GROUPS
        and entry.rule not in RULES_NOT_SEEDED
        and entry.rule not in UNTRIAGED_BACKLOG
        and entry.rule not in seeded
    ]


def triaged_backlog(*, catalog: dict, config: dict) -> set[str]:
    """Backlog entries that no longer need a decision.

    A rule leaves the backlog when it reaches the seeding path, gains a
    documented reason, or disappears from the grouped catalog. Reporting
    them keeps :data:`UNTRIAGED_BACKLOG` from accumulating entries that
    excuse nothing while making the remaining debt look larger.
    """
    declared = {entry.rule for entry in enumerate_baseline_rules(catalog=catalog)}
    seeded = seeded_rules(config=config)
    return {
        rule
        for rule in UNTRIAGED_BACKLOG
        if rule in seeded or rule in RULES_NOT_SEEDED or rule not in declared
    }


__all__ = [
    "BACKLOG_STARTING_SIZE",
    "FLAT_SECTIONS",
    "KEYED_SECTIONS",
    "OPT_IN_GROUPS",
    "RULES_NOT_SEEDED",
    "UNTRIAGED_BACKLOG",
    "BaselineRule",
    "enumerate_baseline_rules",
    "rule_bearing_sections",
    "seeded_rules",
    "triaged_backlog",
    "unseeded_baseline_rules",
]
