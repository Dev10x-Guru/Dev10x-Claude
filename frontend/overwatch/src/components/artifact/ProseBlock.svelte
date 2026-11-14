<script lang="ts">
  import type { ProseBlock } from "../../lib/artifact";

  let { block }: { block: ProseBlock } = $props();
</script>

<div class="prose">
  {#each block.paragraphs as paragraph, index (index)}
    <p>{paragraph}</p>
  {/each}
</div>

<style>
  .prose {
    max-width: 68ch;
  }

  .prose p {
    margin: 0;
    white-space: pre-line;
    overflow-wrap: anywhere;
    text-wrap: pretty;
  }

  .prose p + p {
    margin-top: var(--space-3);
  }
</style>
