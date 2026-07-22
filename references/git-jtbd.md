# JTBD Job Story Guidelines

Rules for writing Job Stories used in PR titles, PR descriptions,
commit messages, and issue tickets.

> **Scope**: This format governs Job Stories in commits and PR descriptions.
> It also applies to issue titles and tickets.
> **Critical dependency**: Release notes parsing requires the precise JTBD
> structured format — `**When** … **[actor] wants to** … **so [beneficiary]
> can** …`. Dropping the `**[actor] wants to**` / `**so [beneficiary] can**`
> markers breaks automated release notes collection
> (`extract_jtbd_structured`). The extractor accepts any concrete actor and
> beneficiary phrase; it still tolerates the legacy first-person
> (`**I want to**` / `**so I can**`) form for already-merged PRs.
> Skills may define their own output formats in `references/`
> documents. If a skill's reference doc diverges from this format,
> verify the skill output is not used for PR/commit descriptions.

## Format

```
**When** [situation], **[actor] wants to** [motivation], **so [beneficiary] can** [expected outcome].
```

One sentence. No bullet points. No implementation details.

Name a concrete domain **actor** (who has the need) and a concrete
**beneficiary** (who gains from the outcome). They are often the same
role — then name that role in both slots ("**the dealer wants to** …
**so the dealer can** …"). When they differ, name both explicitly (a
service writer does the work so a dealer benefits). See § Choosing the
Actor for how to pick the role.

## Voice Requirement

Job Stories must use **third-person, domain-actor voice**: name the
actor and beneficiary as concrete roles. First-person ("I want to") and
faceless ("the user wants to") phrasing are both wrong.

| Form | Example | Status |
|------|---------|--------|
| ✅ Third-person actor | **the service writer wants to** batch quotes | REQUIRED |
| ✅ Explicit beneficiary | **so the dealer can** reconcile payouts | REQUIRED |
| ❌ First-person | **I want to** batch quotes | WRONG (legacy) |
| ❌ Faceless actor | **the user wants to** batch quotes | WRONG (no role) |

The difference: name the role ("the service writer wants to"), never
"I" and never a generic "user"/"customer". When the outcome benefits a
different role, say so explicitly: `**so [role/system] can** ...`.

## Choosing the Actor

- **Actors want outcomes, not work.** Nobody wants to *work*, and no
  company wants to *execute a feature* — people and companies want
  **outcomes**. The actor rarely wants to *do* anything; in the ideal
  case they want the outcome to happen with zero effort on their part.
  If the actor would be happiest doing nothing, name the outcome they
  want to *happen* — then check whether the true beneficiary (whoever
  captures the money or saves the time) is a *different* role than the
  one performing the action. When it is, the performer is a
  **mechanism**, and the beneficiary owns the job.
- Name a concrete domain role, never a faceless "user" or "customer".
  In TireTutor apps the common actors are **service writer**, **dealer**,
  **admin**, and **wholesaler**.
- This set is open — discover new actors as the domain grows, and
  combine roles when a stakeholder wears both hats (e.g. **Dealer
  Owner**, **Wholesaler Admin**).
- Internal teams are rarely the actor. When one genuinely is, make the
  business benefit explicit (reduces cost, increases speed to market).
  Developer tooling is the honest exception — a Job Story whose actor is
  a developer or maintainer is legitimate when the change is tooling.

> **[Verify]** The actor list (service writer / dealer / admin /
> wholesaler) reflects the working domain vocabulary, not an
> authoritative product taxonomy — confirm against the canonical domain
> model when a story hinges on the exact role.

## Localized Story Guidance

Write Job Stories, user-story prose, and BDD scenarios in the language
of the project or ticket — match the language the team and stakeholders
use rather than defaulting to English.

For Gherkin-derived keywords (Feature / Scenario / Given / When / Then),
use Cucumber's official language reference for the correct localized
keywords: <https://cucumber.io/docs/gherkin/languages/>. Add a
`# language: <code>` header to feature-file-style blocks so the keywords
parse (e.g. `# language: pl` for Polish, `# language: es` for Spanish).

```gherkin
# language: pl
Funkcja: Rezerwacja opon
  Scenariusz: Klient rezerwuje montaż
    Zakładając że koszyk zawiera cztery opony
    Kiedy klient wybiera termin montażu
    Wtedy rezerwacja zostaje potwierdzona
```

The structured JTBD markers (`**When**`, `**[actor] wants to**`,
`**so [beneficiary] can**`) stay in their canonical English form so the
release-notes extractor keeps recognizing the Job Story; the free-text
situation, motivation, and outcome — and any BDD scenario body — are
written in the project language.

## Key Principles

### 1. No Personas — Focus on Situation

Job stories replace "As a [persona]..." with the **situation** — the
context that creates the need.

### 2. Situation Over Implementation

The "When" clause describes the real-world context, not UI interactions.

- Good: "When reviewing PRs without automated code quality checks"
- Bad:  "When clicking the review button"

### 3. Motivation Reveals Anxiety

The "[actor] wants to" clause captures what the actor is trying to
accomplish.

- Good: "the admin wants to have Claude review code automatically"
- Bad:  "the admin wants a new workflow file"

### 4. Expected Outcome Shows Value

The "so [beneficiary] can" clause describes the measurable benefit or
the problem that goes away. It should contrast with the current broken
state.

- Good: "so the maintainer can catch regressions before production"
- Bad:  "so the system has reviews"

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Technical language | Not understandable by stakeholders | Use business/domain language |
| Solution-focused "When" | Prescribes implementation | Describe the real-world trigger |
| CLI/command-invocation "When" | "When running `make release-features`" prescribes the tool | Describe the real-world trigger: "When a feature release produces skipped version numbers" |
| Vague outcome | Not testable | Be specific about what improves |
| No contrast with current state | Unclear why it matters | Show what's wrong today |
| Faceless actor ("the user wants to") | No concrete role — untraceable to the domain | Name the role: "the service writer wants to" (see § Choosing the Actor) |
| Solution-focused "wants to" | "the dealer wants to see X on separate lines" names the UI change, not the need | Describe the motivation: "the dealer wants to quickly triage incoming notifications" |
| Solution-focused "wants to" (infra) | "the maintainer wants to use stable, version-independent paths" names the technical fix, not the need | Describe the motivation: "the maintainer wants to run skills without being re-prompted for the same permission" |
| UI-verb motivation ("wants to see/view/manage X") | Describes operating the feature, not the outcome — the actor wants less work, ideally none | Name the end state: "wants X to be obvious at a glance", "wants to be told when…" |
| Transactional-effort "wants to" ("wants to pay / submit / enter X") | Names work the actor performs, not the outcome — nobody wants to *pay*; paying is a mechanism, and it usually misidentifies the actor and beneficiary | Name the outcome and re-check the roles: the customer paying is the mechanism; "**the dealer wants** payment collected without manual card entry, **so the vendor can** capture the revenue" |
| Naming the replaced artifact ("instead of the old list/panel") | Contrasts with the previous implementation, not the pain — diff-framing | Contrast with the pain itself; naming prior broken *behavior* is fine, prior *component* is not |

## Title Writing Principle

Shift the perspective from what changed in the code to what it
enables for the actor. The "so [beneficiary] can" clause captures the
outcome.

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
*"What can the actor do now that they couldn't before?"* — that
answer is your title.

## Examples

### Skill Feature
**When** starting work on a new feature branch, **the maintainer wants
to** create an isolated worktree automatically, **so the maintainer can**
avoid cross-indexing conflicts between branches in the IDE.

### Code Review
**When** reviewing PRs without automated checks, **the admin wants to**
have Claude review code for quality and patterns, **so the team can**
catch regressions before they reach production.

### Bug Fix
**When** committing changes with heredoc syntax, **the maintainer wants
to** have the security hook recognize safe patterns, **so the maintainer
can** commit without false-positive blocks disrupting the workflow.

### Documentation
**When** onboarding a new contributor, **the maintainer wants to** have
clear rules for naming skills, **so contributors can** follow conventions
without reading every existing skill directory.

### Release
**When** a batch of features is ready, **the maintainer wants to** publish
a semver release, **so users can** pin to a stable version and get
predictable updates.

### Money Movement (actor ≠ beneficiary — outcome, not the payment)
A first draft framed the actor as "the customer wants to pay the balance
online right there." But the customer does not *want* to pay — paying is
the **mechanism**. The real jobs belong to the roles who capture the
money or save the time:

- Bad: **When** an order has an unpaid balance, **the customer wants to**
  pay online, **so the customer can** settle up.
- Good: **When** a completed order still has an unpaid balance, **the
  dealer wants** the balance collected without manually keying a card,
  **so TireTutor can** capture the revenue the moment the customer taps
  "pay".

The customer tapping "pay" is *how* the outcome happens, not the outcome
itself — so it belongs in neither the "wants to" nor the "so … can"
clause. Trace the money and the time: whoever captures the revenue
(TireTutor) or is spared the manual work (the dealer) is the actor and
beneficiary; the person performing the transaction is the mechanism.

## See Also

`.claude/rules/essentials.md` § PR Body contains a quick-reference excerpt of
this guide for the JTBD format used in PR bodies. If you notice the two
documents diverge, this file is authoritative — update essentials.md to match.
