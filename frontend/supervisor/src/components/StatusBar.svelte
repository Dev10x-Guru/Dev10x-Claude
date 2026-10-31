<script lang="ts">
  import { runLines, type Run } from "../lib/ansi";

  interface Props {
    ansi: string;
  }

  let { ansi }: Props = $props();

  const lines = $derived(runLines(ansi));

  function style(run: Run): string {
    return [run.fg && `color: ${run.fg}`, run.bg && `background: ${run.bg}`].filter(Boolean).join("; ");
  }
</script>

{#if lines.length}
  <div class="bar">
    {#each lines as line, row (row)}
      <p class="line">
        {#each line as run, index (index)}
          <span
            class={["run", { chip: !!run.bg, bold: run.bold, dim: run.dim, italic: run.italic, underline: run.underline }]}
            style={style(run)}>{run.text.trim() || run.text}</span
          >
        {/each}
      </p>
    {/each}
  </div>
{/if}

<style>
  .bar {
    display: grid;
    gap: 0.2rem;
    padding: 0.35rem var(--space-3);
    background: var(--term);
    border-radius: 3px;
    color: var(--term-ink);
    font-family: var(--font-status);
    font-size: 0.74rem;
    line-height: 1.35;
  }

  .line {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem 0.15rem;
  }

  .run {
    white-space: pre;
  }

  .chip {
    position: relative;
    padding: 0.08rem 0.75rem 0.08rem 0.5rem;
    clip-path: polygon(0 0, calc(100% - 0.4rem) 0, 100% 50%, calc(100% - 0.4rem) 100%, 0 100%, 0.4rem 50%);
    font-weight: 600;
  }

  .chip:first-child {
    clip-path: polygon(0 0, calc(100% - 0.4rem) 0, 100% 50%, calc(100% - 0.4rem) 100%, 0 100%);
    border-radius: 2px 0 0 2px;
  }

  .run:not(.chip) {
    padding: 0 0.3rem;
  }

  .bold {
    font-weight: 700;
  }

  .dim {
    opacity: 0.7;
  }

  .italic {
    font-style: italic;
  }

  .underline {
    text-decoration: underline;
  }
</style>
