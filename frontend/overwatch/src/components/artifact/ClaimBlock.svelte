<script lang="ts">
  import type { ClaimBlock } from "../../lib/artifact";

  let { block }: { block: ClaimBlock } = $props();
</script>

<p class="claim">{block.text}</p>

<style>
  .claim {
    margin: 0;
    max-width: 62ch;
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 650;
    line-height: 1.3;
    letter-spacing: -0.01em;
    text-wrap: pretty;
    overflow-wrap: anywhere;
  }
</style>
