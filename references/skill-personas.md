# Skill Personas

A persona is the expert a skill thinks like while it runs.
It names a role plus the standard that role holds its output to.
It shapes the judgment calls the steps leave open: what to raise,
what to leave out, and who the output is written for.
It never changes the steps, gates or tools (GH-1638).

## Declaring one

1. Add an optional `persona:` scalar to the skill's front matter.
2. Repeat it, word for word, as the first paragraph after the H1:
   `**Persona:** <the same text>`.

A skill load shows the SKILL.md body starting at its H1, without the
front matter, so the body line is what the agent actually reads.
The front-matter field is the machine-readable copy that tooling and
tests can enumerate.
`tests/skills/test_skill_personas.py` fails when the two drift apart,
and when a body line has no front-matter field behind it.

## Writing one

- One or two sentences, 300 characters or fewer.
- Name a role (`Staff architect`, `Tech lead`), then the standard:
  who the output is for and what the role refuses to skip.
- State behavior the steps do not already enforce.
  A persona that restates a gate adds tokens, not judgment.
- No tone-of-voice instructions and no claims of authority over the
  supervisor.
  The persona advises how to judge, not who decides.

## Where personas belong

Judgment-heavy skills, where two competent runs could produce very
different output: reviews, ADRs, scoping.
Mechanical skills (`git-commit`, `ticket-branch`, `gh-pr-merge`) gain
nothing, because the steps fix their output shape.

## Pilot

| Skill | Persona |
|-------|---------|
| `dev10x:review` | Staff engineer doing a pre-push self-review |
| `dev10x:adr` | Staff architect writing for the engineer who implements it later |
| `dev10x:ticket-scope` | Tech lead scoping work someone else will build |

Extend to another skill only when its output shows the gap a persona
closes.
That is the same evidence bar the `dev10x:ddd` discussion personas
were held to (GH-789).
