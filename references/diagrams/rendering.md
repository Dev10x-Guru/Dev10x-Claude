# Diagram Rendering Toolchain

Shared by the `dev10x:diagram-*` skills. Each skill's
`scripts/render.sh` implements this; read this page when a render
fails for a reason the script's message does not explain.

## Contract every render script keeps

1. Syntax-check before rendering; exit non-zero with the line number.
2. Write the image next to the source as `<source-stem>.<png|svg>`.
3. Print `rendered: <path>` on success and nothing else on stdout.
4. Never report success without a non-empty image on disk.

The image still has to be **read** before the diagram is handed back:
a clean exit proves the syntax parsed, not that the picture says what
was meant.

## PlantUML

Requires `java` (any 11+). Graphviz is needed only for component,
class, and C4 layouts — sequence diagrams lay out without it.

Jar lookup order:

1. `$PLANTUML_JAR`
2. The jar bundled with the plugin at `skills/scope/bin/plantuml.jar`
3. `~/.local/bin/plantuml.jar`

| Symptom | Cause | Fix |
|---------|-------|-----|
| `syntax error at line N` | Unknown keyword or malformed arrow on that line | Fix the line; numbers are 1-based |
| Frame missing from the image | Unclosed `alt`/`loop`/`group` — PlantUML closes it at `@enduml` silently | Add the matching `end` |
| `Dot executable does not exist` | Graphviz missing for a layout diagram | Install `graphviz` |
| `!include <C4/...>` not found | Jar older than 2020 with no bundled stdlib | Use the bundled jar or set `PLANTUML_JAR` |

The scripts render with `-pipe`, so the output is named after the
source file even when `@startuml <name>` gives the diagram another
name.

## Mermaid

Rendered with `pnpm dlx @mermaid-js/mermaid-cli@11.17.1` — an exact
pin, so an upstream release cannot change what renders. The first run
downloads it into the pnpm store; later runs are offline. `npx`
works too but is not used, because sessions commonly deny it.

mermaid-cli drives a headless Chrome through puppeteer. When
`PUPPETEER_EXECUTABLE_PATH` is unset the script points it at the
first of `google-chrome-stable`, `google-chrome`, `chromium`,
`chromium-browser` on `PATH`, so puppeteer never needs its own
downloaded browser.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Parse error on line N` with a caret | Malformed statement | Fix that line |
| `Could not find Chrome (ver. …)` | No system Chrome on `PATH` and no puppeteer cache | Install Chrome/Chromium or set `PUPPETEER_EXECUTABLE_PATH` |
| GitHub shows an error box but the local render passed | GitHub runs a different Mermaid version | Avoid features newer than ~6 months; re-check in the PR preview |

Inline Mermaid in a PR body still goes through the script once: a
broken block on GitHub renders as an error box in front of reviewers.

## BPMN

`dev10x:diagram-bpmn` installs a pinned toolchain (`bpmn-moddle`,
`bpmn-auto-layout`, `bpmn-to-image`) once into
`${XDG_CACHE_HOME:-~/.cache}/dev10x/diagram-bpmn` with `pnpm`, and
reinstalls only when the skill's pinned `package.json` (or its
`pnpm-workspace.yaml`) changes. The three direct dependencies are exact
versions; their transitive dependencies still resolve at install time,
since no lockfile ships. Set `DEV10X_BPMN_DEPS` to put the cache
elsewhere.

pnpm 11 refuses dependency build scripts unless told otherwise; the
shipped `pnpm-workspace.yaml` answers `allowBuilds: {puppeteer:
false}`, because rendering uses the system Chrome (same lookup as
Mermaid) instead of the browser puppeteer would download.

`bpmn-auto-layout` places nodes and edges but draws no pool or lane
shapes; `layout.mjs` re-bands its output into the single pool and its
lanes and re-routes the edges. Multi-pool collaborations are refused
rather than drawn wrong.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `X is in no lane` | A flow node missing from every `flowNodeRef` | Add it to exactly one lane |
| `only a single pool is laid out` | Second `participant` or a `messageFlow` | One file per pool |
| `unparsable content …` / `unknown type` | Misspelled element; its `line:` is 0-based (add 1) | Fix the named element |
| `unresolved reference <Id>` | A flow or lane points at an id that does not exist — often a knock-on of the row above | Fix the id, or the typo that hid it |
| `kept existing layout` | The file already has DI (e.g. tuned in Camunda Modeler) | Pass `--relayout` to regenerate |
| `could not install the BPMN toolchain` | No network or no `pnpm` on first run | Retry online; later runs are offline |
| `no Chrome/Chromium on PATH` | Nothing to render with | Install one; the laid-out `.bpmn` is still valid |
