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
