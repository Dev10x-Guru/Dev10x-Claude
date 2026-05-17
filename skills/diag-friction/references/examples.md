# Dev10x:diag-friction examples

Walk-throughs for canonical scenarios (formerly the
`skill-reinforcement` examples). SKILL.md links here to keep the
orchestration body under the size budget.

## Example 1: kubectl usage

**User:** `/Dev10x:diag-friction`
(after agent ran `kubectl get pods -n staging`)

**Output:**
```
## Skill Reinforcement

**Command detected:** `kubectl get pods -n staging`
**Use instead:** `/Dev10x:k8s` — Kubernetes operations via
aws-vault authenticated kubectl

**Why:** Direct kubectl calls bypass aws-vault authentication
and may fail or use wrong credentials.

**How to invoke:**
Skill("Dev10x:k8s")
```

## Example 2: direct git push

**User:** `/Dev10x:diag-friction`
(after agent ran `git push origin feature-branch`)

**Output:**
```
## Skill Reinforcement

**Command detected:** `git push origin feature-branch`
**Use instead:** `/Dev10x:git` — Safe git push with
protected branch checks

**Why:** Direct git push bypasses force-push protection
on develop/main branches.

**How to invoke:**
Skill("Dev10x:git")
```

## Example 3: friction from chaining (pre-approved alternative)

**User:** `/Dev10x:diag-friction`
(after agent ran `git fetch origin && git checkout develop`,
which was rejected because `Bash(git fetch origin && git ...)`
does not match any allow-rule, while `Bash(git fetch:*)` and
`Bash(git checkout:*)` are both pre-approved in
`.claude/settings.local.json`)

**Output:**
```
## Skill Reinforcement

**Command detected:** `git fetch origin && git checkout develop`
**Use instead:** Run each step in a separate Bash call.

**Why:** `&&` chaining shifts the effective allow-rule prefix to
the full string. The individual commands ARE pre-approved; the
chained form is not.

**Pre-approved alternatives:**
- Call 1: `git fetch origin`  (covered by `Bash(git fetch:*)`
  in `.claude/settings.local.json`)
- Call 2: `git checkout develop`  (covered by
  `Bash(git checkout:*)`)
```

## Example 4: no match found

**User:** `/Dev10x:diag-friction`
(after agent ran `curl https://api.example.com/health`)

**Output:**
```
## Skill Reinforcement

**Command detected:** `curl https://api.example.com/health`
**No direct skill match found.**

Available skills that might help:
- `/Dev10x:k8s` — if checking service health in k8s
- `/Dev10x:investigate` — if investigating a bug report

Check ~/.claude/SKILLS.md for the full list of available skills.
```

## Example 5: structural friction → file upstream

**User:** `/Dev10x:diag-friction`
(after agent ran a perfectly reasonable `gh api graphql -f
query='...'` call that the hook blocked with "use the MCP tool
instead" — but no MCP tool exists for the specific GraphQL
query the agent needed)

**Output:**
```
## Friction Diagnosis

**Command detected:** `gh api graphql -f query=...`
**No skill match.** No MCP wrapper exists for this GraphQL query.

**Pre-approved alternatives:** None that fit. The only allow-rule
that would cover this is `Bash(gh api:*)`, which is too broad
(spans destructive verbs like delete and DELETE-method POSTs).

**Upstream issue:**
This is structural friction — the command-skill-map blocks
`gh api` globally, but the legitimate GraphQL read use case
has no MCP path. Suggested fix: add an MCP tool that wraps the
specific GraphQL query the workflow needs, or relax the hook
for `gh api graphql` (read-only by definition).

Approve to file the upstream issue:

    gh issue create \
      --repo Dev10x-Guru/Dev10x-Claude \
      --title "🪝 Permission friction: gh api graphql blocked with no MCP path" \
      --label "permission-friction" \
      --body "Repro: gh api graphql -f query=... | Hook blocks with..."
```
