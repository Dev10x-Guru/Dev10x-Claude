<script lang="ts">
  import NeedsStrip from "./components/NeedsStrip.svelte";
  import SessionRow from "./components/SessionRow.svelte";
  import { readToken, subscribe, type Connection } from "./lib/api";
  import { bucket, clockTime, headline } from "./lib/format";
  import type { ActionResult, Snapshot } from "./lib/types";

  const DONE_PREVIEW = 12;
  const TOAST_MS = 5000;

  const token = readToken();

  let snapshot = $state<Snapshot | null>(null);
  let connection = $state<Connection>("connecting");
  let showAllDone = $state(false);
  let toast = $state<{ text: string; ok: boolean } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  const groups = $derived(bucket(snapshot?.sessions ?? []));
  const done = $derived(showAllDone ? groups.done : groups.done.slice(0, DONE_PREVIEW));
  const errors = $derived(Object.entries(snapshot?.errors ?? {}));

  $effect(() => {
    if (!token) return;
    return subscribe(
      token,
      (next) => (snapshot = next),
      (state) => (connection = state),
    );
  });

  function onresult(result: ActionResult, what: string): void {
    toast = result.ok ? { text: `${what}.`, ok: true } : { text: result.error ?? "Something went wrong.", ok: false };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), TOAST_MS);
  }
</script>

<main>
  {#if !token}
    <section class="empty">
      <h1>Session Supervisor</h1>
      <p>Open the link printed by <code>dev10x supervisor serve</code>; it carries the access token.</p>
    </section>
  {:else}
    <header class="masthead">
      <p class="eyebrow">Session Supervisor</p>
      <h1>{snapshot ? headline(groups) : "Reading sessions…"}</h1>
      <p class="meta">
        <span class="conn conn-{connection}" aria-hidden="true"></span>
        {#if connection === "live" && snapshot}
          Live · updated {clockTime(snapshot.taken_at)}
        {:else if connection === "lost"}
          Lost the daemon. Reload once it is back.
        {:else}
          Connecting…
        {/if}
        {#if snapshot}
          <span class="counts">{groups.working.length} working · {groups.done.length} idle or done</span>
        {/if}
      </p>
    </header>

    {#if errors.length}
      <section class="errors" role="status">
        {#each errors as [source, message] (source)}
          <p><strong>{source}</strong> {message}</p>
        {/each}
      </section>
    {/if}

    {#if groups["needs-you"].length}
      <section class="needs" aria-label="Needs you">
        {#each groups["needs-you"] as session (session.session_id)}
          <NeedsStrip {session} {token} {onresult} />
        {/each}
      </section>
    {:else if snapshot}
      <p class="calm">Every session is working or finished. Questions appear here the moment one asks.</p>
    {/if}

    {#if snapshot}
      <div class="lists">
        <section aria-labelledby="working-title">
          <h2 id="working-title">Working <span>{groups.working.length}</span></h2>
          {#if groups.working.length}
            <ul>
              {#each groups.working as session (session.session_id)}
                <SessionRow {session} />
              {/each}
            </ul>
          {:else}
            <p class="quiet">No session is busy right now.</p>
          {/if}
        </section>

        <section aria-labelledby="done-title">
          <h2 id="done-title">Idle or done <span>{groups.done.length}</span></h2>
          <ul>
            {#each done as session (session.session_id)}
              <SessionRow {session} />
            {/each}
          </ul>
          {#if groups.done.length > DONE_PREVIEW}
            <button class="more" onclick={() => (showAllDone = !showAllDone)}>
              {showAllDone ? "Show fewer" : `Show all ${groups.done.length}`}
            </button>
          {/if}
        </section>
      </div>
    {/if}
  {/if}

  <div class="toast-region" aria-live="polite">
    {#if toast}
      <p class={["toast", { bad: !toast.ok }]}>{toast.text}</p>
    {/if}
  </div>
</main>

<style>
  main {
    max-width: 76rem;
    margin: 0 auto;
    padding: var(--space-8) clamp(1rem, 3vw, 2.5rem) 6rem;
  }

  .masthead {
    padding-bottom: var(--space-6);
    border-bottom: 2px solid var(--ink);
  }

  .eyebrow {
    margin: 0 0 var(--space-2);
    color: var(--ink-soft);
    font-size: var(--step--1);
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: var(--step-3);
    font-weight: 700;
    line-height: 1.02;
    letter-spacing: -0.02em;
    text-wrap: balance;
  }

  .meta {
    margin: var(--space-3) 0 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-4);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .conn {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--ink-faint);
  }

  .conn-live {
    background: var(--working);
  }

  .conn-lost {
    background: var(--danger);
  }

  .counts {
    margin-left: auto;
  }

  .errors {
    margin-top: var(--space-4);
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--danger);
    color: var(--danger);
    font-size: var(--step--1);
  }

  .errors p {
    margin: 0;
  }

  .needs {
    margin-top: var(--space-6);
    border-bottom: 1px solid var(--rule-strong);
  }

  .calm {
    margin: var(--space-6) 0 0;
    max-width: 38rem;
    color: var(--ink-soft);
    font-size: var(--step-1);
  }

  .lists {
    container-type: inline-size;
    margin-top: var(--space-8);
    display: grid;
    grid-template-columns: 1fr 1.4fr;
    gap: var(--space-8);
  }

  @container (max-width: 44rem) {
    .lists {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 52rem) {
    .lists {
      grid-template-columns: 1fr;
    }
  }

  h2 {
    margin: 0 0 var(--space-2);
    padding-bottom: var(--space-2);
    border-bottom: 1px solid var(--ink);
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 650;
  }

  h2 span {
    color: var(--ink-faint);
    font-weight: 500;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .quiet {
    margin: var(--space-2) 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .more {
    margin-top: var(--space-3);
    padding: 0;
    background: none;
    border: none;
    color: var(--ink);
    font-size: var(--step--1);
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 3px;
    cursor: pointer;
  }

  .empty {
    max-width: 34rem;
  }

  .empty p {
    color: var(--ink-soft);
  }

  .toast-region {
    position: fixed;
    left: clamp(1rem, 3vw, 2.5rem);
    bottom: var(--space-6);
    max-width: min(32rem, calc(100vw - 2rem));
  }

  .toast {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    background: var(--ink);
    color: var(--paper);
    font-size: var(--step--1);
    border-radius: 3px;
    animation: rise 240ms var(--ease-out);
  }

  .toast.bad {
    background: var(--danger);
  }

  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(6px);
    }
  }
</style>
