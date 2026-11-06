# Diagram Mechanics (learned the hard way)

How mermaid and bpmn-js behave inside the claude.ai artifact sandbox,
and why [`../template.html`](../template.html) is written the way it
is. Read this before changing a diagram block or the template's
scripts.

Confirmed in the artifact sandbox on 2026-11-05: host mermaid
(sequence, state, C4 flowchart) and the bpmn-js viewer below both
render, in light and dark.

## Mermaid

**Mermaid is rendered by the artifact host.** The host injects its
own mermaid runtime and renders every `<pre class="mermaid">`,
marking it `data-claude-mermaid-claimed`. Do not load mermaid
yourself in the page — it would render twice. The template loads
mermaid from jsDelivr only when no block was claimed (a local
preview outside the host).

## bpmn-js

- **Viewer:** `bpmn-navigated-viewer.production.min.js` at an exact
  version (template: `bpmn-js@17.11.1` on unpkg), `zoomScroll` off,
  Zoom in / Zoom out / Fit buttons, drag to pan, a legend under the
  canvas.
- **Render BPMN when its view is shown**, not at load: a hidden view
  has no size, so `fit-viewport` lays out at zero. Re-render on a
  theme change.
- **Theme colors in BPMN XML:** write
  `color:background-color="{{--bpmn-auto-fill}}"`; the template
  replaces `{{--token}}` with the current CSS value before import.
  Color roles: manual work (the bottleneck), automated, person.
- **No external stylesheets** beyond Google Fonts, so the template
  inlines the few diagram-js rules the viewer needs (hit areas,
  outlines).

## Hidden views

**`[hidden]{display:none!important}`** is in the template because
`section{display:grid}` otherwise overrides `hidden` and every view
shows at once outside the host.
