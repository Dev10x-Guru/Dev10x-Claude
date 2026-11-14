<script lang="ts">
  import type { CalloutBlock } from "../../lib/artifact";

  let { block }: { block: CalloutBlock } = $props();

  const LABELS = { ok: "Good", warn: "Watch", bad: "Problem", info: "Note" } as const;
</script>

<aside class="callout callout-{block.tone}">
  <p class="label">{LABELS[block.tone] ?? "Note"}</p>
  <p class="text">{block.text}</p>
</aside>

<style>
  .callout {
    --tone: var(--focus);
    max-width: 72ch;
    padding: var(--space-3) var(--space-4);
    border-left: 3px solid var(--tone);
    background: color-mix(in oklch, var(--tone) 9%, var(--paper));
  }

  .callout-ok {
    --tone: var(--working);
  }

  .callout-warn {
    --tone: var(--amber);
  }

  .callout-bad {
    --tone: var(--danger);
  }

  .label {
    margin: 0;
    color: var(--ink-soft);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  .text {
    margin: var(--space-1) 0 0;
    white-space: pre-line;
    overflow-wrap: anywhere;
  }
</style>
