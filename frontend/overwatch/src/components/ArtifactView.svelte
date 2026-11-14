<script lang="ts">
  import ArtifactControl from "./ArtifactControl.svelte";
  import { fetchArtifact, isKnownBlock, isStale, toneClass } from "../lib/artifacts";
  import { clockTime } from "../lib/format";
  import type { ArtifactDocument, ArtifactSummary } from "../lib/types";

  interface Props {
    artifactId: string;
    token: string;
    summary: ArtifactSummary | undefined;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
  }

  let { artifactId, token, summary, pending, run }: Props = $props();

  let document = $state<ArtifactDocument | null>(null);
  let error = $state("");
  let copied = $state<number | null>(null);

  async function load(): Promise<void> {
    const next = await fetchArtifact(artifactId, token);
    if (typeof next === "string") {
      error = next;
      return;
    }
    error = "";
    document = next;
  }

  $effect(() => {
    void artifactId;
    document = null;
    load();
  });

  $effect(() => {
    if (isStale(document, summary)) load();
  });

  async function copy(index: number, text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      copied = index;
    } catch {
      copied = null;
    }
  }
</script>

<article class="artifact">
  {#if error}
    <p class="problem" role="alert">{error}</p>
  {:else if !document}
    <p class="calm">Loading the page…</p>
  {:else}
    <header>
      <p class="eyebrow">Artifact · {document.session}</p>
      <h1>{document.title}</h1>
      <p class="meta">Revision {document.revision} · updated {clockTime(document.updated_at)}</p>
    </header>

    {#each document.blocks as block, index (block.id ?? index)}
      <section class={["block", `block-${block.type}`]}>
        {#if !isKnownBlock(block)}
          <p class="problem">This page holds a block this version cannot show.</p>
        {:else if block.type === "summary"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <p class="prose">{block.text}</p>
        {:else if block.type === "claim"}
          <p class={["claim", toneClass(block.tone)]}>{block.text}</p>
        {:else if block.type === "decisions"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <ul class="decisions">
            {#each block.items as item, row (row)}
              <li>
                <span>{item.question}</span>
                {#if item.owner}<span class="owner">{item.owner}</span>{/if}
                {#if item.status}<span class={["pill", toneClass(item.tone)]}>{item.status}</span>{/if}
              </li>
            {/each}
          </ul>
        {:else if block.type === "kv"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <dl class="kv">
            {#each block.items as item, row (row)}
              <dt>{item.key}</dt>
              <dd>{item.value}</dd>
            {/each}
          </dl>
        {:else if block.type === "table"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <div class="scroll">
            <table>
              <thead>
                <tr>{#each block.columns as column, col (col)}<th>{column}</th>{/each}</tr>
              </thead>
              <tbody>
                {#each block.rows as cells, row (row)}
                  <tr>{#each cells as cell, col (col)}<td>{cell}</td>{/each}</tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else if block.type === "pills"}
          <p class="pills">
            {#each block.items as item, row (row)}<span class={["pill", toneClass(item.tone)]}>{item.label}</span>{/each}
          </p>
        {:else if block.type === "stats"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <div class="stats">
            {#each block.items as item, row (row)}
              <div class={["stat", toneClass(item.tone)]}>
                <span class="value">{item.value}</span>
                <span class="label">{item.label}</span>
              </div>
            {/each}
          </div>
        {:else if block.type === "draft"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <pre class="draft">{block.text}</pre>
          <button type="button" class="copy" onclick={() => copy(index, block.text)}>
            {copied === index ? "Copied" : "Copy"}
          </button>
        {:else if block.type === "evidence"}
          {#if block.title}<h2>{block.title}</h2>{/if}
          <ul class="evidence">
            {#each block.items as item, row (row)}
              <li>
                <p>{item.claim}</p>
                <p class="source">{item.source}{item.checked ? ` · ${item.checked}` : ""}</p>
              </li>
            {/each}
          </ul>
        {:else}
          <ArtifactControl control={block} {document} {pending} {run} />
        {/if}
      </section>
    {/each}
  {/if}
</article>

<style>
  .artifact {
    height: 100%;
    overflow-y: auto;
    padding: var(--space-6) var(--space-6) var(--space-8);
  }

  header {
    margin-bottom: var(--space-4);
  }

  .eyebrow {
    margin: 0;
    color: var(--ink-faint);
    font-size: 0.7rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  h1 {
    margin: var(--space-1) 0;
    font-family: var(--font-display);
    font-size: var(--step-3);
    line-height: 1.1;
  }

  h2 {
    margin: 0 0 var(--space-2);
    font-family: var(--font-display);
    font-size: var(--step-1);
  }

  .meta,
  .source,
  .owner {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .block {
    padding: var(--space-4) 0;
    border-top: 1px solid var(--rule);
  }

  .prose {
    max-width: 72ch;
    margin: 0;
    white-space: pre-line;
  }

  .claim {
    margin: 0;
    padding-left: var(--space-3);
    border-left: 3px solid var(--rule-strong);
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 650;
    white-space: pre-line;
  }

  .claim.tone-ok {
    border-left-color: var(--working);
  }

  .claim.tone-warn {
    border-left-color: var(--amber);
  }

  .claim.tone-bad {
    border-left-color: var(--danger);
  }

  .claim.tone-info {
    border-left-color: var(--focus);
  }

  .decisions,
  .evidence {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: var(--space-2);
  }

  .decisions li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
  }

  .evidence p {
    margin: 0;
  }

  .kv {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: var(--space-1) var(--space-4);
    margin: 0;
  }

  .kv dt {
    color: var(--ink-soft);
  }

  .kv dd {
    margin: 0;
    white-space: pre-line;
  }

  .scroll {
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    font-size: var(--step--1);
  }

  th,
  td {
    padding: var(--space-1) var(--space-3);
    border-bottom: 1px solid var(--rule);
    text-align: left;
    vertical-align: top;
  }

  .pills {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
  }

  .pill {
    padding: 0.1rem var(--space-2);
    border: 1px solid var(--rule-strong);
    border-radius: 999px;
    font-size: var(--step--1);
    font-weight: 600;
  }

  .pill.tone-ok,
  .stat.tone-ok {
    border-color: var(--working);
    color: var(--working);
  }

  .pill.tone-warn,
  .stat.tone-warn {
    border-color: var(--amber);
    color: var(--amber-ink);
  }

  .pill.tone-bad,
  .stat.tone-bad {
    border-color: var(--danger);
    color: var(--danger);
  }

  .pill.tone-info,
  .stat.tone-info {
    border-color: var(--focus);
  }

  .stats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
  }

  .stat {
    display: grid;
    min-width: 8rem;
    padding: var(--space-3);
    border: 1px solid var(--rule);
    border-radius: 3px;
  }

  .stat .value {
    font-family: var(--font-display);
    font-size: var(--step-3);
    font-weight: 700;
  }

  .stat .label {
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .draft {
    max-width: 72ch;
    margin: 0 0 var(--space-2);
    padding: var(--space-3);
    background: var(--paper-sunk);
    border: 1px solid var(--rule);
    border-radius: 3px;
    font-family: var(--font-term);
    white-space: pre-wrap;
  }

  .copy {
    padding: var(--space-1) var(--space-3);
    font: inherit;
    color: var(--ink);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    cursor: pointer;
  }

  .problem {
    color: var(--danger);
  }

  .calm {
    color: var(--ink-soft);
  }
</style>
