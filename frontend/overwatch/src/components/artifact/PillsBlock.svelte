<script lang="ts">
  import Pill from "./Pill.svelte";
  import type { PillsBlock } from "../../lib/artifact";

  let { block }: { block: PillsBlock } = $props();
</script>

<ul class="pills">
  {#each block.items as item, index (index)}
    <li><Pill text={item.text} tone={item.tone} /></li>
  {/each}
</ul>

<style>
  .pills {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
