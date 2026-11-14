<script lang="ts">
  import { MediaQuery } from "svelte/reactivity";

  import type { MermaidBlock } from "../../lib/artifact";
  import { renderMermaid } from "../../lib/mermaid";

  let { block }: { block: MermaidBlock } = $props();

  const prefersDark = new MediaQuery("prefers-color-scheme: dark");

  const dark = $derived.by(() => {
    const forced = document.documentElement.dataset.theme;
    return forced ? forced === "dark" : prefersDark.current;
  });

  const rendering = $derived(renderMermaid(block.source, dark));

  function reason(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }
</script>

<figure class="diagram">
  {#await rendering}
    <p class="loading">Drawing the diagram…</p>
  {:then svg}
    <!-- mermaid produced this SVG itself with securityLevel "strict" -->
    <div class="canvas">{@html svg}</div>
  {:catch error}
    <figcaption class="failure">The diagram did not render: {reason(error)}</figcaption>
    <pre>{block.source}</pre>
  {/await}
</figure>

<style>
  .diagram {
    margin: 0;
    max-width: 100%;
    overflow-x: auto;
    padding: var(--space-3);
    border: 1px solid var(--rule);
    border-radius: 3px;
    background: var(--paper);
  }

  .canvas {
    display: flex;
    justify-content: center;
  }

  .canvas :global(svg) {
    max-width: 100%;
    height: auto;
  }

  .failure {
    margin-bottom: var(--space-2);
    color: var(--danger);
    font-size: var(--step--1);
  }

  pre {
    margin: 0;
    font-family: var(--font-term);
    font-size: 0.8rem;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .loading {
    margin: 0;
    color: var(--ink-faint);
    font-size: var(--step--1);
  }
</style>
