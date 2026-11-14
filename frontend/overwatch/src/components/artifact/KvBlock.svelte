<script lang="ts">
  import type { KvBlock } from "../../lib/artifact";

  let { block }: { block: KvBlock } = $props();
</script>

<dl class="kv">
  {#each block.items as item, index (index)}
    <div class="row">
      <dt>{item.key}</dt>
      <dd>{item.value}</dd>
    </div>
  {/each}
</dl>

<style>
  .kv {
    margin: 0;
    max-width: 72ch;
    display: grid;
    border-top: 1px solid var(--rule);
  }

  .row {
    display: grid;
    grid-template-columns: minmax(8rem, 14rem) minmax(0, 1fr);
    gap: var(--space-3);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--rule);
  }

  dt {
    color: var(--ink-soft);
    font-size: var(--step--1);
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  dd {
    margin: 0;
    white-space: pre-line;
    overflow-wrap: anywhere;
  }

  @container artifact (max-width: 32rem) {
    .row {
      grid-template-columns: 1fr;
      gap: 0;
    }
  }
</style>
