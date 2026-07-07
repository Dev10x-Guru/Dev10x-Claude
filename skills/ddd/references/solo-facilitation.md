# Solo Facilitation — One Human + AI Cast

> Event Storming canon assumes 6–30 people in a room. The default
> reality for this skill is ONE human. This reference defines how
> AI substitutes replace the room without replacing the human's
> two irreplaceable roles: domain expert and decision-maker.

## Role Substitution Map

| The room provides | Solo substitute |
|---|---|
| Facilitator | Claude main session (this skill) |
| Domain knowledge, source of truth | **The human — never substituted** |
| Diverse stakeholder perspectives | Persona panel (parallel subagents) |
| Duplicate-sticky hot-spot signal | Blind generation + overlap analysis |
| Challenge, disagreement | Devil's advocate agent |
| Note-taker | Session deliverables (unchanged) |
| Decision authority | **The human — never substituted** |

## The Assumption Guardrail (non-negotiable)

Personas and advocates generate **hypotheses, not facts**. Every
claim about the business the human has not confirmed is tagged
`[ASSUMPTION]`. Tagged items:

- May drive exploration ("if this holds, we'd also need...")
- Must NOT silently enter `model.md`, `decisions.md`, or
  `glossary.md`
- Land in the workshop record's Open Questions until the human
  confirms, rejects, or reformulates them

This is the solo-mode extension of process-rules Rule 3: the AI
cast must not invent the client's domain.

## Persona Panel

### Selecting personas

After the human states the session brief, pick 3–5 personas whose
viewpoints the domain implies. Menu (extend per domain):

| Persona | Brings to the board |
|---|---|
| Operator / back-office | Exceptions, corrections, manual overrides |
| Finance / controller | Money movement, reconciliation, audit, tax |
| Customer / end user | Happy path, expectations, failure experience |
| Integration partner | External events, contracts, data exchange |
| Compliance / legal | Retention, consent, jurisdiction rules |
| Support / success | Complaints, refunds, edge-case tickets |
| Competitor's architect | What they'd do differently; market table stakes |

Name the selected personas to the human before dispatch (one line
each); accept edits.

### Blind generation protocol

1. **Human first**: elicit the human's domain events for the brief
   (or reuse ones already on the board).
2. **Dispatch personas in parallel** (cheap models — haiku;
   `general-purpose`, background). Each persona receives: the
   session brief, its perspective description, the glossary (if
   any) — and NOT the human's events, NOT other personas' output.
   Each returns: domain events (past tense), suspected policies,
   pain points, one "what everyone forgets" item — all tagged
   `[ASSUMPTION]`.
3. **Overlap analysis** (facilitator, inline):
   - Events named by human + ≥1 persona → validated core
   - Events named by ≥2 personas but not the human → **hot spot:
     present for confirmation first**
   - Single-source events → exploration frontier, batch-present
4. **Human arbitration**: present as ONE batched menu (process
   rules, Rule 1). The human confirms/renames/rejects; confirmed
   events lose the `[ASSUMPTION]` tag and enter the timeline.
   Ubiquitous language naming is always the human's call.

### Where personas plug into the flow

| Workshop stage | Persona use |
|---|---|
| Event storming (Step 3, layers 1–4) | Blind event/command/policy generation |
| Aggregate & context design (layers 5–6) | Skip — facilitator + human work directly |
| Stress testing (Step 4) | Each persona contributes one "what if" scenario from its viewpoint |
| Decision capture (Step 5) | Never — decisions are human-only |

## Devil's Advocate

Before decision capture on any structural change, dispatch ONE
adversarial agent (stronger model than personas — sonnet tier)
with: the proposed model delta, the anti-patterns catalog
(`references/domain/anti-patterns.md` at the repo root), and the prior
decisions list. Its brief:

- Attack aggregate boundaries (invariants, size, coupling)
- Name any anti-pattern the proposal matches
- Run a pre-mortem: "it's 12 months later and this design failed —
  why?"
- Check contradiction against active `[D-NNN]` decisions

The advocate's findings are presented to the human WITH the
facilitator's response to each (accept / rebut / defer). Findings
the human accepts become stress-test scenarios or superseding
decisions; rebuttals are recorded in the decision's Alternatives.

## Cost & Cadence Defaults

- Personas: haiku, 3–5 agents, dispatched at most twice per
  session (initial storming + one refinement round). More rounds
  add anchoring risk, not signal.
- Devil's advocate: sonnet, once per structural change batch.
- Everything else runs inline — solo mode must stay cheap enough
  to be the default, not a special occasion.

## Solo-Mode Session Etiquette

- The human is the only participant: batch questions hard
  (Rule 1), keep momentum, no ceremony that assumes an audience.
- Timebox persona rounds: results are presented as diffs against
  the human's board, never as walls of raw agent output.
- The quality checklist gains one solo item: **no `[ASSUMPTION]`
  tags remain in model.md / decisions.md / glossary.md**.
