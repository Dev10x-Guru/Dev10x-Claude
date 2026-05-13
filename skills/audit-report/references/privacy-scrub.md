# Privacy Scrubbing for Upstream Issue Bodies

Treat the source session as private by default. The upstream issue
filed at `Dev10x-Guru/Dev10x-Claude` is a public artifact and MUST
NOT disclose any identifier from a non-public repository, project,
branch, ticket tracker, file path, person, or service that is not
part of the public Dev10x plugin.

## Principle: Fictionalize, Don't Redact

Replace every private identifier with a **similar-sounding fictional
counterpart drawn from pop culture** — movies, books, TV, cartoons,
video games. Do NOT use generic placeholders like `<private-repo>`
or `TICKET-NN`; they break narrative flow and make the issue body
read like a leak instead of a story.

Real examples of this pattern already in the wild — issue
[#68](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/68) uses
`initech/initech-pos` (Office Space), reviewer handle `skywalker`
(Star Wars), and keeps `PAY-` as a plausible-looking fictional
tracker prefix. Issue
[#98](https://github.com/Dev10x-Guru/Dev10x-Claude/issues/98) uses
Tyrell Corp (Blade Runner) and Aperture Labs (Portal) as the two
example workspaces.

**Source pool — pop culture only.** Movies, novels, TV series,
cartoons, comics, video games. NEVER use the names of real
companies, real competitors, real products, or real people — even
if those names *sound* fictional. "Initech" is fine (Office Space);
"Initrode" is fine (Office Space sequel-joke); a real but obscure
company name is not.

**Forbidden sources:** real corporations, real tradenames, real
product names, real public figures, real internal customers, real
vendors, real internal codenames. When in doubt, pick something
unambiguously from a movie or book.

## Replacement Strategy

Pick fictional names freely per finding — there is no fixed
catalog. Choose names that evoke a **similar vibe or domain** to
the original where it helps the reader follow the story:

| Source flavor | Pick from pop-culture set evoking… |
|---|---|
| Big-corporate / megacorp | Tyrell Corp, Weyland-Yutani, Cyberdyne, Omni Consumer Products, Soylent, Vault-Tec, Buy n Large |
| Defense / aerospace / industrial | Stark Industries, Wayne Enterprises, Massive Dynamic, Yoyodyne, Rekall |
| Consumer tech / startups | Hooli, Pied Piper, Aperture Science, Wonka Industries, Acme Corp, MomCorp |
| Quirky / cartoon-coded SMB | Krusty Krab, Los Pollos Hermanos, Bluth Company, Dunder Mifflin, Planet Express, Vandelay Industries |
| Retail / payments / e-commerce | Initech, Initrode, Pizza Planet, Hot Dog on a Stick, Big Kahuna Burger |
| Biotech / medical / lab | Umbrella Corp, InGen, Oscorp, Spacely Sprockets, Veridian Dynamics |

For **people**: use first names from the same fictional universe
or generic literary names — `skywalker`, `vader`, `gandalf`,
`hermione`, `arya`, `neo`, `morpheus`. Never use a real Slack
handle or real first+last name even if it "looks generic."

For **branches**: keep the structural pattern
(`<user>/<TICKET>/<worktree>/<slug>`) but fictionalize each
segment — `skywalker/CORE-401/death-star-3/align-targeting-computer`.

For **ticket trackers**: invent a fictional 3-4 letter prefix
that evokes a fictional team or product (`CORE`, `WONKA`, `DUFF`,
`MOMCORP`, `KRAB`, `INGEN`) and a small integer. Keep the
prefix consistent within one issue.

For **hostnames / domains**: fictional planets, cities, or
in-universe locations (`tatooine.internal`, `gotham-db-01`,
`mos-eisley-staging`).

For **file paths**: keep the directory structure shape but
fictionalize the project root and any product-revealing
segment — `wayne-enterprises/payments/src/refund_calculator.py`
not `/work/acme/billing/...`.

## Consistency Rule

Use a **deterministic per-session mapping** — the same private
value gets the same fictional name throughout one issue body so
cross-references stay readable. If the original mentions
`acme/billing` four times and a reviewer `j.smith` twice, pick
one fictional repo and one fictional handle on first sight and
reuse them every time.

When the source has TWO related private orgs (e.g., user's
company + a side project), pick two fictional companies that
read as clearly distinct universes — Tyrell Corp + Aperture
Labs, not Tyrell Corp + Tyrell Subsidiary.

## Allowed Verbatim (public Dev10x context)

The following CAN appear unchanged — they are already public:

- Skill names with the `Dev10x:` prefix (`Dev10x:git`,
  `Dev10x:git-commit`, …)
- Hook script names that ship in this plugin
- Public file paths inside this repo (`skills/<name>/SKILL.md`,
  `hooks/...`, `references/...`)
- The plugin version and the public repo URL
- GitHub issue / PR numbers from `Dev10x-Guru/Dev10x-Claude`
- Generic tool names (`git`, `gh`, `pytest`, `ruff`)

## What Must Be Fictionalized

Anything that could let a reader trace the report back to a
private codebase, customer, employer, or person — and anything
where management might reasonably claim "internal information
leaked." When unsure, fictionalize.

- Repository / package names from non-Dev10x repos
- Org or user owner names (GitHub, Linear, JIRA, internal git)
- Branch names beyond the public PR branch
- Ticket IDs / tracker URLs from non-Dev10x trackers
- File paths under `/work/<project>/` or any non-plugin path
- Internal hostnames, database names, service names, cluster names
- Customer names, vendor names, partner names
- Product names, internal codenames, project codenames
- Person names, email addresses, Slack handles, GitHub handles
- Free-text excerpts from private commits, comments, or Slack
  messages — summarize abstractly OR rewrite with fictional
  details, do not quote verbatim
- Sentry / observability project slugs
- Domain names, URLs pointing at internal systems

## Algorithm

1. Extract the verbatim findings text.
2. Walk the text once, building a session mapping: each unique
   private identifier → a fictional counterpart. Pick the
   fictional name with the vibe-matching guide above; keep a
   running list so the second mention of a value gets the same
   replacement as the first.
3. Apply the mapping. Rewrite quoted excerpts from private
   sources so the surrounding prose still makes sense with the
   fictional names substituted in.
4. Replace transcript turn references that point at private
   session files (`session 529d497f`,
   `~/.claude/projects/-work-...`) with `<source session>`.
   Keep in-session turn numbers ("turn 75", "turns 59–73") —
   they are anonymous within the upstream issue.
5. Strip any "Local fixes" / "Notes for triage" sections — by
   definition these are private context.
6. Re-read the assembled body. For every named entity, ask:
   "could this be googled back to a real company, product, or
   person?" If yes, fictionalize again. Do not file the issue
   until every named entity passes this check.

## Decision Gate: Unfictionalizable Findings

**STOP and ask the user** if a finding is fundamentally about
a private codebase pattern that cannot be retold through
fictional stand-ins without losing the technical point. Use
`AskUserQuestion`:

- **Fictionalize aggressively and file (Recommended)** — pick
  the closest pop-culture stand-in even at the cost of some
  specificity; the technical finding is what matters upstream
- **Skip this finding** — exclude it from the upstream issue
  and keep it in local notes only

Never auto-include unfictionalized text. A finding that still
contains a real org, real person, or real product name is not
ready to file.
