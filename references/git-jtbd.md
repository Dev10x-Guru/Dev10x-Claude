# JTBD Job Story Guidelines

Rules for writing Job Stories used in PR titles, PR descriptions,
commit messages, and issue tickets.

> **Scope**: This format governs Job Stories in commits and PR descriptions.
> It also applies to issue titles and tickets.
> **Critical dependency**: Release notes parsing requires precise JTBD
> voice format (first-person "I want to" or explicit third-party "so X can").
> Objective voice ("wants to") breaks automated release notes collection.
> Skills may define their own output formats in `references/`
> documents. If a skill's reference doc diverges from this format,
> verify the skill output is not used for PR/commit descriptions.

## Format

```
**When** [situation], **I want to** [motivation], **so I can** [expected outcome].
```

One sentence. No bullet points. No implementation details.

**Third-party outcome variant**: When the beneficiary of the outcome
is a third party (e.g., a teammate, a CI system, an end user),
`**so**` without "I can" is acceptable:

```
**When** ..., **I want to** ..., **so** [third party] can [outcome].
```

Example: "**so** reviewers can catch issues before merging."
The canonical `**so I can**` form is preferred for first-person
outcomes. Either form is accepted by the hygiene reviewer.

## Voice Requirement

Job Stories must use first-person or explicit third-party voice.
Objective voice ("wants to") is incorrect:

| Form | Example | Status |
|------|---------|--------|
| ✅ First-person | **I want to** have Claude config copied | REQUIRED |
| ✅ Third-party | **so** reviewers can catch issues | REQUIRED |
| ❌ Objective voice | **wants to** have Claude config copied | WRONG |
| ❌ Mixed voice | **I want to** X **so** reviewer wants Y | WRONG |

The difference: "I want to" (first-person) vs "wants to" (objective).
When describing outcomes benefiting others, use explicit names:
`**so** [person/system] can ...` — not just `**so**` alone.

## Key Principles

### 1. No Personas — Focus on Situation

Job stories replace "As a [persona]..." with the **situation** — the
context that creates the need.

### 2. Situation Over Implementation

The "When" clause describes the real-world context, not UI interactions.

- Good: "When reviewing PRs without automated code quality checks"
- Bad:  "When clicking the review button"

### 3. Motivation Reveals Anxiety

The "I want to" clause captures what the user is trying to accomplish.

- Good: "I want to have Claude review code automatically"
- Bad:  "I want a new workflow file"

### 4. Expected Outcome Shows Value

The "so I can" clause describes the measurable benefit or the problem
that goes away. It should contrast with the current broken state.

- Good: "so I can catch regressions before they reach production"
- Bad:  "so the system has reviews"

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Technical language | Not understandable by stakeholders | Use business/domain language |
| Solution-focused "When" | Prescribes implementation | Describe the real-world trigger |
| CLI/command-invocation "When" | "When running `make release-features`" prescribes the tool | Describe the real-world trigger: "When a feature release produces skipped version numbers" |
| Vague outcome | Not testable | Be specific about what improves |
| No contrast with current state | Unclear why it matters | Show what's wrong today |
| Solution-focused "I want to" | "I want to see X on separate lines" names the UI change, not the need | Describe the motivation: "I want to quickly triage incoming notifications" |
| Solution-focused "I want to" (infra) | "I want to use stable, version-independent paths" names the technical fix, not the need | Describe the user motivation: "I want to run skills without being re-prompted for the same permission on every invocation" |

## Title Writing Principle

Shift the perspective from what changed in the code to what it
enables for the user. The "so I can" clause captures the outcome.

### Common patterns

| Change type | Bad (implementation) | Good (outcome) |
|---|---|---|
| New skill | `Add git-worktree skill` | `Enable isolated workspace creation` |
| Hook | `Add bash validation hook` | `Prevent unsafe shell commands` |
| Config | `Add shellcheck workflow` | `Catch shell script errors in CI` |
| Bug fix | `Fix heredoc detection regex` | `Prevent false positives on commit messages` |
| Refactor | `Extract naming logic to module` | `Enable reusable skill naming across tools` |
| Docs | `Add review guidelines rule file` | `Standardize code review workflow` |
| Release | `Bump version to 1.2.0` | `Release skill naming + review features` |

### The "rename test"

If your title reads like a git diff summary, rewrite it. Ask:
*"What can the user do now that they couldn't before?"* — that
answer is your title.

## Examples

### Skill Feature
**When** starting work on a new feature branch, **I want to**
create an isolated worktree automatically, **so I can** avoid
cross-indexing conflicts between branches in my IDE.

### Code Review
**When** reviewing PRs without automated checks, **I want to** have
Claude review code for quality and patterns, **so I can** catch
regressions before they reach production.

### Bug Fix
**When** committing changes with heredoc syntax, **I want to** the
security hook to recognize safe patterns, **so I can** commit without
false positive blocks disrupting my workflow.

### Documentation
**When** onboarding a new contributor, **I want to** have clear rules
for naming skills, **so** contributors can follow conventions without
reading every existing skill directory.

### Release
**When** a batch of features is ready, **I want to** publish a semver
release, **so** users can pin to a stable version and get predictable
updates.

## See Also

`.claude/rules/essentials.md` § PR Body contains a quick-reference excerpt of
this guide for the JTBD format used in PR bodies. If you notice the two
documents diverge, this file is authoritative — update essentials.md to match.
