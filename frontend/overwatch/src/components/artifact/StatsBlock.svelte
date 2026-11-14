<script lang="ts">
  import type { StatsBlock } from "../../lib/artifact";

  let { block }: { block: StatsBlock } = $props();
</script>

<dl class="stats">
  {#each block.items as item, index (index)}
    <div class="stat">
      <dt>{item.label}</dt>
      <dd class="value">{item.value}</dd>
      {#if item.note}<dd class="note">{item.note}</dd>{/if}
    </div>
  {/each}
</dl>

<style>
  .stats {
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
    gap: var(--space-3);
  }

  .stat {
    padding: var(--space-3) var(--space-4);
    background: var(--paper-sunk);
    border-top: 2px solid var(--ink);
  }

  dt {
    color: var(--ink-soft);
    font-size: 0.7rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .value {
    margin-top: var(--space-1);
    font-family: var(--font-display);
    font-size: var(--step-3);
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }

  .note {
    margin-top: var(--space-2);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }
</style>
