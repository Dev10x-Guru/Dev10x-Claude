<script lang="ts">
  import {
    STATUS_LABELS,
    WORK_STATUSES,
    busTime,
    byStatus,
    fetchBoard,
    member,
    threadUrl,
    type BusBoard,
  } from "../lib/chatbus";

  interface Props {
    token: string;
  }

  let { token }: Props = $props();

  const POLL_MS = 10_000;

  let board = $state<BusBoard | null>(null);
  let error = $state("");
  let loadedAt = $state("");

  const groups = $derived(byStatus(board?.work_items ?? []));

  $effect(() => {
    let live = true;
    const load = async (): Promise<void> => {
      const next = await fetchBoard(token);
      if (!live) return;
      if (typeof next === "string") {
        error = next;
        return;
      }
      error = "";
      board = next;
      loadedAt = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    };
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  });
</script>

{#snippet thread(name: string | null)}
  {#if name && threadUrl(name)}
    <a href={threadUrl(name)} target="_blank" rel="noreferrer noopener" title={name}>Open thread</a>
  {:else if name}
    <span class="mono" title={name}>{name}</span>
  {:else}
    <span class="faint">no thread</span>
  {/if}
{/snippet}

<section class="bus" aria-labelledby="bus-title">
  <header>
    <p class="eyebrow">Chat bus · read-only</p>
    <h2 id="bus-title">What the bots were asked to do</h2>
    <p class="meta">
      {#if board}
        Store <span class="mono">{board.store}</span>{board.exists ? "" : " (not created yet)"}
        {#if loadedAt}· read {loadedAt}{/if}
      {:else if !error}
        Reading the Chat bus…
      {/if}
    </p>
    <p class="note">
      Chat text below is untrusted: it is what someone typed, shown as plain text. Approve or reject work from
      the owner's Chat DM with the bot; this page only shows it.
    </p>
    {#if error}
      <p class="error" role="status">{error}</p>
    {/if}
  </header>

  {#if board}
    <section aria-labelledby="bus-queue">
      <h3 id="bus-queue">Queue</h3>
      <ul class="counts">
        {#each WORK_STATUSES as status (status)}
          <li class={["count", status, { some: (board.queue[status] ?? 0) > 0 }]}>
            <span class="n">{board.queue[status] ?? 0}</span>
            {STATUS_LABELS[status]}
          </li>
        {/each}
        <li class={["count", { some: board.expired_leases > 0 }]}>
          <span class="n">{board.expired_leases}</span> Expired leases
        </li>
      </ul>
    </section>

    <section aria-labelledby="bus-gaps">
      <h3 id="bus-gaps">Open gaps <span class="faint">{board.gaps.length}</span></h3>
      {#if board.gaps.length}
        <table>
          <thead><tr><th>Space</th><th>From</th><th>To</th><th>Reason</th></tr></thead>
          <tbody>
            {#each board.gaps as gap (gap.id)}
              <tr class="gap">
                <td class="mono">{gap.space}</td>
                <td>{busTime(gap.from)}</td>
                <td>{busTime(gap.to)}</td>
                <td>{gap.reason}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="faint">No unrecovered windows.</p>
      {/if}
    </section>

    <section aria-labelledby="bus-allowlist">
      <h3 id="bus-allowlist">Allowlist</h3>
      {#if board.allowlist.error}
        <p class="error">No authority is granted: {board.allowlist.error}</p>
      {:else}
        <dl class="allow">
          <dt>Owner</dt>
          <dd>{member(board.allowlist.owner)}</dd>
          <dt>Trusted</dt>
          <dd>
            {#if board.allowlist.trusted.length}
              {board.allowlist.trusted.map((each) => member(each)).join(", ")}
            {:else}
              none
            {/if}
          </dd>
        </dl>
      {/if}
      <p class="faint">
        As configured in <span class="mono">{board.allowlist.config}</span>; the daemon applies it when it starts
        or reloads.
      </p>
    </section>

    <section aria-labelledby="bus-work">
      <h3 id="bus-work">Work items <span class="faint">{board.work_items.length}</span></h3>
      {#each groups as group (group.status)}
        <h4 class={["status", group.status]}>{STATUS_LABELS[group.status]}</h4>
        <ul class="items">
          {#each group.items as work (work.id)}
            <li class="item">
              <p class="line">
                <span class="mono">#{work.id}</span>
                <span class="kind">{work.kind}</span>
                <span class="mono">{work.sender}</span>
                {#if work.claimed_by}<span>claimed by {work.claimed_by}</span>{/if}
                <span class="faint">{busTime(work.created_at)}</span>
                {@render thread(work.thread)}
              </p>
              <blockquote class="untrusted">{work.untrusted_text}</blockquote>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="faint">No work items yet.</p>
      {/each}
    </section>

    <section aria-labelledby="bus-commands">
      <h3 id="bus-commands">Verdicts <span class="faint">{board.commands.length}</span></h3>
      {#if board.commands.length}
        <table>
          <thead>
            <tr><th>Event</th><th>Actor</th><th>Verb</th><th>Outcome</th><th>Reason</th><th>When</th></tr>
          </thead>
          <tbody>
            {#each board.commands as command (command.id)}
              <tr class={{ refused: !command.authorized }}>
                <td class="mono">{command.event_id}</td>
                <td class="mono">{command.actor}</td>
                <td>{command.verb || "-"}</td>
                <td>{command.outcome ?? (command.authorized ? "allowed" : "rejected")}</td>
                <td>{command.reason}</td>
                <td>{busTime(command.created_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="faint">No verdicts yet.</p>
      {/if}
    </section>

    <section aria-labelledby="bus-events">
      <h3 id="bus-events">Events <span class="faint">{board.events.length}</span></h3>
      {#if board.events.length}
        <ul class="items">
          {#each board.events as event (event.id)}
            <li class="item">
              <p class="line">
                <span class="mono">#{event.id}</span>
                <span class="kind">{event.source}</span>
                <span class="mono">{event.sender}</span>
                <span class="faint">{busTime(event.event_time)}</span>
                {@render thread(event.thread)}
              </p>
              <p class="faint mono small">{event.type}</p>
              {#if event.untrusted_text}
                <blockquote class="untrusted">{event.untrusted_text}</blockquote>
              {/if}
            </li>
          {/each}
        </ul>
      {:else}
        <p class="faint">No events stored.</p>
      {/if}
    </section>
  {/if}
</section>

<style>
  .bus {
    height: 100%;
    overflow-y: auto;
    padding: var(--space-6);
  }

  .bus > section {
    margin-top: var(--space-6);
  }

  .eyebrow {
    margin: 0;
    color: var(--ink-faint);
    font-size: 0.7rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  h2 {
    margin: var(--space-1) 0 0;
    font-family: var(--font-display);
    font-size: var(--step-1);
  }

  h3 {
    margin: 0 0 var(--space-2);
    font-size: var(--step-0);
  }

  h4 {
    margin: var(--space-3) 0 var(--space-1);
    font-size: var(--step--1);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-soft);
  }

  h4.awaiting_approval {
    color: var(--amber-ink);
  }

  .meta,
  .note {
    margin: var(--space-2) 0 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .error {
    margin: var(--space-2) 0 0;
    color: var(--danger);
    font-size: var(--step--1);
  }

  .faint {
    color: var(--ink-faint);
  }

  .mono {
    font-family: var(--font-term);
    font-size: 0.85em;
    overflow-wrap: anywhere;
  }

  .small {
    margin: 0;
    font-size: 0.72rem;
  }

  .counts {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .count {
    padding: var(--space-1) var(--space-3);
    border: 1px solid var(--rule);
    border-radius: 3px;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .count.some {
    color: var(--ink);
    border-color: var(--rule-strong);
  }

  .count.awaiting_approval.some {
    background: var(--amber-wash);
    border-color: var(--amber);
  }

  .n {
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--step--1);
  }

  th,
  td {
    padding: var(--space-1) var(--space-2);
    border-bottom: 1px solid var(--rule);
    text-align: left;
    vertical-align: top;
  }

  th {
    color: var(--ink-soft);
    font-weight: 600;
  }

  tr.refused td,
  tr.gap td {
    color: var(--danger);
  }

  .allow {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: var(--space-1) var(--space-3);
    margin: 0 0 var(--space-2);
    font-size: var(--step--1);
  }

  .allow dt {
    color: var(--ink-soft);
  }

  .allow dd {
    margin: 0;
  }

  .items {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .item {
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--rule);
  }

  .line {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    align-items: baseline;
    margin: 0;
    font-size: var(--step--1);
  }

  .kind {
    font-weight: 600;
  }

  .untrusted {
    margin: var(--space-1) 0 0;
    padding: var(--space-1) var(--space-3);
    border-left: 2px solid var(--rule-strong);
    color: var(--ink);
    font-size: var(--step--1);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
