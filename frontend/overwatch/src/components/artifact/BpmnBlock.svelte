<script lang="ts">
  import { MediaQuery } from "svelte/reactivity";

  import { diagramLabel, type BpmnBlock } from "../../lib/artifact";
  import { renderBpmn } from "../../lib/bpmn";
  import { bpmnColors, pagePalette } from "../../lib/diagram-theme";

  let { block }: { block: BpmnBlock } = $props();

  const prefersDark = new MediaQuery("prefers-color-scheme: dark");

  const dark = $derived.by(() => {
    const forced = document.documentElement.dataset.theme;
    return forced ? forced === "dark" : prefersDark.current;
  });

  let canvas: HTMLDivElement | undefined = $state();
  let phase: "loading" | "ready" | "failed" = $state("loading");
  let failure = $state("");

  function reason(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  $effect(() => {
    const target = canvas;
    if (!target) return;
    const colors = bpmnColors(pagePalette(dark));
    let disposed = false;
    let destroy: (() => void) | null = null;
    phase = "loading";
    renderBpmn(target, block.xml, colors).then(
      (dispose) => {
        if (disposed) return dispose();
        destroy = dispose;
        phase = "ready";
      },
      (error: unknown) => {
        if (disposed) return;
        failure = reason(error);
        phase = "failed";
      },
    );
    return () => {
      disposed = true;
      destroy?.();
    };
  });
</script>

<figure class="diagram" aria-label={diagramLabel(block)}>
  {#if block.title}
    <figcaption class="title">{block.title}</figcaption>
  {/if}
  {#if phase === "loading"}
    <p class="loading">Drawing the diagram…</p>
  {:else if phase === "failed"}
    <p class="failure">The diagram did not render: {failure}</p>
  {/if}
  <div class="canvas" class:hidden={phase === "failed"} bind:this={canvas}></div>
</figure>

<style>
  .diagram {
    margin: 0;
    max-width: 100%;
    padding: var(--space-3);
    border: 1px solid var(--rule);
    border-radius: 3px;
    background: var(--paper);
  }

  .title {
    margin-bottom: var(--space-2);
    color: var(--ink-soft);
    font-size: var(--step--1);
    font-weight: 600;
  }

  .canvas {
    position: relative;
    height: clamp(16rem, 45vh, 32rem);
  }

  .canvas.hidden {
    display: none;
  }

  .canvas :global(.bjs-powered-by) {
    padding: 2px;
    border-radius: 3px;
    background: oklch(97.4% 0.009 85);
  }

  .failure {
    margin: 0 0 var(--space-2);
    color: var(--danger);
    font-size: var(--step--1);
  }

  .loading {
    margin: 0;
    color: var(--ink-faint);
    font-size: var(--step--1);
  }
</style>
