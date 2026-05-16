# Skill-reinforcement examples

Walk-throughs for the four canonical scenarios. SKILL.md links
here to keep the orchestration body under the size budget.

## Example 1: kubectl usage

**User:** `/Dev10x:skill-reinforcement`
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

**User:** `/Dev10x:skill-reinforcement`
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

**User:** `/Dev10x:skill-reinforcement`
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

**User:** `/Dev10x:skill-reinforcement`
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
