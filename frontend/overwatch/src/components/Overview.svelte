<script lang="ts">
  import StatusMark from "./StatusMark.svelte";
  import { ago, displayName, waitingLabel } from "../lib/format";
  import { byUrgency, countMarks, lastWord, progress, waitingItems, type WaitKind } from "../lib/overview";
  import { markOf } from "../lib/tree";
  import type { Session } from "../lib/types";

  interface Props {
    sessions: Session[];
    now: number;
    onselect: (sessionId: string) => void;
  }

  let { sessions, now, onselect }: Props = $props();

  const KINDS: Record<WaitKind, string> = {
    decision: "decision",
    question: "question",
    permission: "approve",
    input: "input",
  };

  const counts = $derived(countMarks(sessions));
  const waiting = $derived(waitingItems(sessions));
  const ordered = $derived(byUrgency(sessions));
  const active = $derived(ordered.filter((session) => ["blocked", "working"].includes(markOf(session))));
  const resting = $derived(ordered.filter((session) => !["blocked", "working"].includes(markOf(session))));
</script>

{#snippet panel(session: Session)}
  {@const mark = markOf(session)}
  {@const ws = session.workspace}
  {@const tasks = progress(session)}
  {@const said = lastWord(session)}
  <li>
    <button type="button" class={["panel", mark]} onclick={() => onselect(session.session_id)}>
      <span class="panel-head">
        <StatusMark {mark} />
        <span class="panel-name">{displayName(session)}</span>
        {#if session.recap?.last_said_at}
          <span class="when">{ago(session.recap.last_said_at, now)}</span>
        {/if}
      </span>
      <span class="where">
        {ws.project}{#if ws.branch}<span class="branch"> · {ws.branch}</span>{/if}
      </span>
      {#if mark === "blocked"}
        <span class="waits">Waiting for {waitingLabel(session)}</span>
      {/if}
      {#if tasks}
        <span class="progress">
          <span class="bar" aria-hidden="true">
            <span class="fill" style="width: {Math.min(100, (100 * tasks.done) / tasks.total)}%"></span>
          </span>
          <span class="tally">{tasks.done}/{tasks.total} tasks</span>
          {#if tasks.current}<span class="current">{tasks.current}</span>{/if}
        </span>
      {/if}
      {#if said}
        <span class="said">{said}</span>
      {/if}
      <span class="badges">
        {#if session.decisions.length}
          <span class="badge ask">{session.decisions.length} {session.decisions.length === 1 ? "decision" : "decisions"}</span>
        {/if}
        {#if session.preview && session.status === "waiting"}
          <span class="badge ask">{session.preview.tool} waiting</span>
        {/if}
        {#if ws.issue}<span class="badge">{ws.issue}</span>{/if}
        {#if ws.pr}<span class="badge">PR #{ws.pr}</span>{/if}
      </span>
    </button>
  </li>
{/snippet}

<section class="overview" aria-label="Overview of every session">
  <header class="top">
    <h1>Overview</h1>
    <ul class="tiles">
      <li class={["tile", "blocked", { lit: counts.blocked }]}>
        <span class="n">{counts.blocked}</span><span class="label">need you</span>
      </li>
      <li class="tile">
        <span class="n">{waiting.length}</span><span class="label">decisions waiting</span>
      </li>
      <li class="tile working">
        <span class="n">{counts.working}</span><span class="label">working</span>
      </li>
      <li class="tile">
        <span class="n">{counts.done + counts.idle}</span><span class="label">idle or done</span>
      </li>
    </ul>
  </header>

  <section class="block" aria-label="Decisions waiting">
    <h2>Waiting on you <span class="count">{waiting.length}</span></h2>
    {#if waiting.length}
      <ol class="queue">
        {#each waiting as item (item.key)}
          <li>
            <button type="button" class="ask-row" onclick={() => onselect(item.session.session_id)}>
              <span class={["kind", item.kind]}>{KINDS[item.kind]}</span>
              <span class="ask-text">
                <span class="ask-title">{item.title}</span>
                {#if item.detail}<span class="ask-detail">{item.detail}</span>{/if}
              </span>
              <span class="ask-who">
                {displayName(item.session)}
                {#if item.since}<span class="when">{ago(item.since, now)}</span>{/if}
              </span>
            </button>
          </li>
        {/each}
      </ol>
    {:else}
      <p class="quiet">Nothing waits for you. Sessions that ask a question or need a tool approved show up here.</p>
    {/if}
  </section>

  <section class="block" aria-label="Active sessions">
    <h2>Active <span class="count">{active.length}</span></h2>
    {#if active.length}
      <ul class="panels">
        {#each active as session (session.session_id)}
          {@render panel(session)}
        {/each}
      </ul>
    {:else}
      <p class="quiet">No session is working or waiting right now.</p>
    {/if}
  </section>

  {#if resting.length}
    <details class="block resting">
      <summary><span class="heading">Idle or done <span class="count">{resting.length}</span></span></summary>
      <ul class="panels">
        {#each resting as session (session.session_id)}
          {@render panel(session)}
        {/each}
      </ul>
    </details>
  {/if}

  {#if !sessions.length}
    <p class="quiet">No sessions are running. Each one appears here the moment it starts.</p>
  {/if}
</section>

<style>
  .overview {
    height: 100%;
    overflow-y: auto;
    padding: var(--space-6) var(--space-6) var(--space-8);
    scrollbar-width: thin;
  }

  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: var(--step-3);
    font-weight: 700;
    letter-spacing: -0.02em;
  }

  h2,
  .heading {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-2);
    margin: 0 0 var(--space-3);
    font-family: var(--font-display);
    font-size: 0.78rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-soft);
  }

  .count,
  .n,
  .tally,
  .when {
    font-variant-numeric: tabular-nums;
  }

  .count {
    color: var(--ink-faint);
  }

  ul,
  ol {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  button {
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }

  .quiet {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .top {
    margin-bottom: var(--space-6);
  }

  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
    gap: var(--space-3);
    margin-top: var(--space-4);
  }

  .tile {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--rule);
    border-radius: 4px;
    background: var(--paper-sunk);
  }

  .tile .n {
    font-family: var(--font-display);
    font-size: var(--step-3);
    font-weight: 700;
    line-height: 1;
  }

  .tile .label {
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .tile.blocked.lit {
    border-color: var(--amber);
    background: var(--amber-wash);
  }

  .tile.blocked.lit .n {
    color: var(--amber-ink);
  }

  .tile.working .n {
    color: var(--working);
  }

  .block {
    margin-bottom: var(--space-8);
  }

  .resting summary {
    cursor: pointer;
    list-style: none;
  }

  .resting summary::-webkit-details-marker {
    display: none;
  }

  .resting summary .heading::before {
    content: "▸";
    color: var(--ink-faint);
  }

  .resting[open] summary .heading::before {
    content: "▾";
  }

  .queue {
    border-top: 1px solid var(--rule);
  }

  .ask-row {
    display: grid;
    grid-template-columns: 5.5rem minmax(0, 1fr) auto;
    align-items: baseline;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-3) var(--space-2);
    background: none;
    border: none;
    border-bottom: 1px solid var(--rule);
    transition: background 140ms var(--ease-out);
  }

  .ask-row:hover,
  .ask-row:focus-visible {
    background: var(--paper-sunk);
  }

  .ask-row:focus-visible,
  .panel:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  .kind {
    justify-self: start;
    padding: 0.05rem 0.4rem;
    border-radius: 2px;
    background: var(--amber-wash);
    color: var(--amber-ink);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .kind.permission {
    background: color-mix(in oklch, var(--danger) 12%, transparent);
    color: var(--danger);
  }

  .kind.input {
    background: var(--paper-sunk);
    color: var(--ink-soft);
  }

  .ask-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .ask-title {
    font-weight: 650;
    overflow-wrap: anywhere;
  }

  .ask-detail {
    color: var(--ink-soft);
    font-size: var(--step--1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ask-who {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    color: var(--ink-soft);
    font-size: var(--step--1);
    white-space: nowrap;
  }

  .when {
    color: var(--ink-faint);
    font-size: 0.72rem;
  }

  .panels {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr));
    gap: var(--space-3);
  }

  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    width: 100%;
    height: 100%;
    padding: var(--space-3) var(--space-4);
    background: var(--paper);
    border: 1px solid var(--rule);
    border-left: 3px solid var(--rule-strong);
    border-radius: 4px;
    transition: border-color 140ms var(--ease-out), background 140ms var(--ease-out);
  }

  .panel:hover,
  .panel:focus-visible {
    background: var(--paper-sunk);
  }

  .panel.blocked {
    border-left-color: var(--amber);
  }

  .panel.working {
    border-left-color: var(--working);
  }

  .panel-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .panel-name {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .where {
    color: var(--ink-soft);
    font-size: 0.74rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .branch {
    color: var(--ink-faint);
  }

  .waits {
    color: var(--amber-ink);
    font-size: var(--step--1);
    font-weight: 650;
  }

  .progress {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.2rem var(--space-2);
    font-size: 0.74rem;
  }

  .bar {
    height: 0.3rem;
    border-radius: 2px;
    background: var(--rule);
    overflow: hidden;
  }

  .fill {
    display: block;
    height: 100%;
    background: var(--working);
  }

  .blocked .fill {
    background: var(--amber);
  }

  .tally {
    color: var(--ink-soft);
  }

  .current {
    grid-column: 1 / -1;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .said {
    color: var(--ink-soft);
    font-size: var(--step--1);
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow-wrap: anywhere;
  }

  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin-top: auto;
  }

  .badge {
    padding: 0 0.35rem;
    border: 1px solid var(--rule);
    border-radius: 2px;
    color: var(--ink-soft);
    font-size: 0.68rem;
    font-weight: 600;
  }

  .badge.ask {
    border-color: var(--amber);
    background: var(--amber-wash);
    color: var(--amber-ink);
  }

  .badges:empty {
    display: none;
  }

  @media (max-width: 48rem) {
    .overview {
      padding: var(--space-4);
    }

    .ask-row {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-1);
    }

    .ask-who {
      flex-direction: row;
      gap: var(--space-2);
      align-items: baseline;
    }
  }
</style>
