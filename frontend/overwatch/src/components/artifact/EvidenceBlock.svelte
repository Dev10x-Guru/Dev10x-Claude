<script lang="ts">
  import type { EvidenceBlock } from "../../lib/artifact";

  let { block }: { block: EvidenceBlock } = $props();
</script>

<ol class="evidence">
  {#each block.items as item, index (index)}
    <li>
      <p class="claim">{item.claim}</p>
      <p class="ref"><span class="tag">Source</span> <code>{item.ref}</code></p>
      {#if item.check}
        <p class="check"><span class="tag">Check</span> <code>{item.check}</code></p>
      {/if}
    </li>
  {/each}
</ol>

<style>
  .evidence {
    margin: 0;
    padding: 0;
    list-style: none;
    counter-reset: evidence;
    display: grid;
    gap: var(--space-3);
    max-width: 80ch;
  }

  li {
    counter-increment: evidence;
    position: relative;
    padding: 0 0 var(--space-3) 2.2rem;
    border-bottom: 1px solid var(--rule);
  }

  li::before {
    content: counter(evidence);
    position: absolute;
    left: 0;
    top: 0.1rem;
    width: 1.5rem;
    color: var(--ink-faint);
    font-family: var(--font-term);
    font-size: var(--step--1);
    text-align: right;
  }

  p {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .claim {
    font-weight: 600;
  }

  .ref,
  .check {
    margin-top: var(--space-1);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .tag {
    display: inline-block;
    min-width: 3.6rem;
    color: var(--ink-faint);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  code {
    font-family: var(--font-term);
    font-size: 0.8rem;
    white-space: pre-wrap;
  }
</style>
