<script lang="ts">
  import { clockTime } from "../lib/format";
  import type { ConversationEntry } from "../lib/types";

  interface Props {
    entries: ConversationEntry[];
  }

  let { entries }: Props = $props();

  const OUTCOMES: Record<string, string> = {
    ran: "✓",
    failed: "✗",
    rejected: "⊘",
    pending: "…",
  };
</script>

<ol class="log">
  {#each entries as entry, index (index)}
    {#if entry.kind === "tool"}
      <li class={["tool", entry.outcome]}>
        <span class="mark" aria-label={entry.outcome}>{OUTCOMES[entry.outcome] ?? ""}</span>
        <span class="name">{entry.tool}</span>
        <code class="target">{entry.text}</code>
        {#if entry.result}
          <details>
            <summary>output</summary>
            <pre>{entry.result}</pre>
          </details>
        {/if}
      </li>
    {:else}
      <li class={["say", entry.role]}>
        <p class="who">
          {entry.role === "user" ? "Prompt" : "Claude"}
          {#if entry.at}<time datetime={entry.at}>{clockTime(entry.at)}</time>{/if}
        </p>
        <div class="text">{entry.text}</div>
      </li>
    {/if}
  {:else}
    <li class="empty">No transcript yet. The session's messages appear here as it writes them.</li>
  {/each}
</ol>

<style>
  .log {
    margin: 0;
    padding: var(--space-4) var(--space-6) var(--space-6);
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .say {
    max-width: 72ch;
    padding-top: var(--space-2);
  }

  .say.user {
    align-self: flex-end;
    padding: var(--space-2) var(--space-3);
    background: color-mix(in oklch, var(--term-ink) 9%, transparent);
    border-radius: 6px 6px 2px 6px;
  }

  .who {
    margin: 0 0 0.15rem;
    display: flex;
    gap: var(--space-2);
    color: var(--term-faint);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  time {
    font-weight: 400;
    letter-spacing: 0;
    font-variant-numeric: tabular-nums;
  }

  .text {
    color: var(--term-ink);
    font-size: 0.9rem;
    line-height: 1.5;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .tool {
    display: grid;
    grid-template-columns: 1rem auto minmax(0, 1fr);
    align-items: baseline;
    gap: 0 var(--space-2);
    padding: 0.1rem 0;
    color: var(--term-faint);
    font-size: 0.76rem;
  }

  .mark {
    text-align: center;
  }

  .ran .mark {
    color: color-mix(in oklch, var(--working) 80%, var(--term-ink));
  }

  .failed .mark,
  .rejected .mark {
    color: var(--danger);
  }

  .pending .mark {
    color: var(--amber);
  }

  .name {
    color: var(--term-ink);
    font-weight: 600;
  }

  .target {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-term);
    font-size: 0.74rem;
  }

  details {
    grid-column: 3;
  }

  summary {
    font-size: 0.68rem;
    cursor: pointer;
  }

  pre {
    margin: 0.2rem 0 0;
    padding: var(--space-2);
    background: color-mix(in oklch, var(--term-ink) 6%, transparent);
    font-family: var(--font-term);
    font-size: 0.72rem;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .empty {
    color: var(--term-faint);
  }
</style>
