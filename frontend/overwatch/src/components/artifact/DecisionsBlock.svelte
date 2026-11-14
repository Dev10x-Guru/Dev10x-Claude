<script lang="ts">
  import Control from "./Control.svelte";
  import type { DecisionsBlock } from "../../lib/artifact";
  import { getControlHost } from "../../lib/artifact-host";

  let { block }: { block: DecisionsBlock } = $props();

  const host = getControlHost();
</script>

<ol class="decisions">
  {#each block.items as item, index (index)}
    {@const control = item.control ? host.find(item.control) : null}
    <li>
      <p class="question">{item.question}</p>
      {#if item.owner}<p class="owner">Owner: {item.owner}</p>{/if}
      {#if control}
        <div class="answer"><Control block={control} /></div>
      {/if}
    </li>
  {/each}
</ol>

<style>
  .decisions {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: var(--space-3);
    max-width: 80ch;
  }

  li {
    padding: var(--space-3) var(--space-4);
    border-left: 3px solid var(--amber);
    background: var(--paper-sunk);
  }

  p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .question {
    font-weight: 650;
    text-wrap: pretty;
  }

  .owner {
    margin-top: var(--space-1);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .answer {
    margin-top: var(--space-3);
  }
</style>
