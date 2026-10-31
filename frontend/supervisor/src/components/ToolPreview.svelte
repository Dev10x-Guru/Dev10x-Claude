<script lang="ts">
  import { diffLineKind } from "../lib/format";
  import { tail } from "../lib/tail";
  import type { ToolCallPreview } from "../lib/types";

  interface Props {
    preview: ToolCallPreview;
  }

  let { preview }: Props = $props();

  const lines = $derived(preview.body.split("\n"));
</script>

<figure class="preview">
  <figcaption>
    <span class="tool">{preview.tool}</span>
    {#if preview.title}<span class="title" title={preview.title}>{preview.title}</span>{/if}
  </figcaption>

  {#if preview.kind === "diff"}
    <pre class="diff">{#each lines as line, index (index)}<span class={diffLineKind(line)}>{line}
</span>{/each}</pre>
  {:else}
    <pre class={preview.kind} {@attach tail(preview.body)}>{preview.body}</pre>
  {/if}

  {#if preview.truncated}<p class="cut">Cut short; the full change is in the session.</p>{/if}
</figure>

<style>
  .preview {
    margin: 0;
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    background: var(--paper);
    overflow: hidden;
  }

  figcaption {
    display: flex;
    gap: var(--space-3);
    align-items: baseline;
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--rule);
    font-size: var(--step--1);
  }

  .tool {
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--amber-ink);
  }

  .title {
    color: var(--ink-soft);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  pre {
    margin: 0;
    padding: var(--space-3);
    max-height: 26rem;
    overflow: auto;
    font-family: var(--font-term);
    font-size: 0.8rem;
    line-height: 1.45;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .command {
    background: var(--paper-sunk);
  }

  .diff span {
    display: block;
    padding: 0 var(--space-2);
    margin: 0 calc(-1 * var(--space-2));
  }

  .diff .add {
    background: color-mix(in oklch, var(--working) 16%, transparent);
  }

  .diff .del {
    background: color-mix(in oklch, var(--danger) 14%, transparent);
  }

  .diff .hunk {
    color: var(--ink-faint);
  }

  .diff .file {
    color: var(--ink-soft);
    font-weight: 600;
  }

  .cut {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border-top: 1px solid var(--rule);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }
</style>
