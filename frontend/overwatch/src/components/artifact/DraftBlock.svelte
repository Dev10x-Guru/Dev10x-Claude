<script lang="ts">
  import type { DraftBlock } from "../../lib/artifact";

  let { block }: { block: DraftBlock } = $props();

  const COPIED_MS = 1800;

  let copied = $state<"" | "yes" | "no">("");
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(block.text);
      copied = "yes";
    } catch {
      copied = "no";
    }
    clearTimeout(timer);
    timer = setTimeout(() => (copied = ""), COPIED_MS);
  }

  $effect(() => () => clearTimeout(timer));
</script>

<figure class="draft">
  <figcaption>
    <span class="label">{block.label}</span>
    <button type="button" class={["copy", { done: copied === "yes" }]} onclick={copy}>
      {copied === "yes" ? "Copied" : copied === "no" ? "Copy failed" : "Copy"}
    </button>
  </figcaption>
  <pre>{block.text}</pre>
</figure>

<style>
  .draft {
    margin: 0;
    max-width: 80ch;
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    background: var(--paper);
  }

  figcaption {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: var(--paper-sunk);
    border-bottom: 1px solid var(--rule);
  }

  .label {
    min-width: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
    font-weight: 650;
    overflow-wrap: anywhere;
  }

  .copy {
    flex: none;
    padding: 0.1rem 0.7rem;
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    cursor: pointer;
    transition: border-color 160ms var(--ease-out);
  }

  .copy:hover {
    border-color: var(--ink);
  }

  .copy.done {
    border-color: var(--working);
    color: var(--working);
  }

  pre {
    margin: 0;
    padding: var(--space-3);
    max-height: 28rem;
    overflow: auto;
    font-family: var(--font-term);
    font-size: 0.82rem;
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
