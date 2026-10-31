<script lang="ts">
  import DetailPane from "./components/DetailPane.svelte";
  import SessionPane from "./components/SessionPane.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import { fetchDetail, post, readToken, subscribe, type Connection } from "./lib/api";
  import { bucket, clockTime, headline } from "./lib/format";
  import {
    ASIDE_DEFAULT_PX,
    clampAside,
    loadAsideWidth,
    loadPins,
    loadView,
    saveAsideWidth,
    savePins,
    saveView,
    togglePin,
  } from "./lib/prefs";
  import { pickSession } from "./lib/selection";
  import type { ActionResult, SessionDetail, Snapshot, View } from "./lib/types";

  const TOAST_MS = 5000;
  const DETAIL_POLL_MS = 2500;
  const RESIZE_STEP_PX = 16;

  const token = readToken();

  let snapshot = $state<Snapshot | null>(null);
  let connection = $state<Connection>("connecting");
  let chosen = $state(decodeURIComponent(location.hash.slice(1)));
  let detail = $state<SessionDetail | null>(null);
  let pins = $state(loadPins());
  let view = $state<View>(loadView());
  let asideWidth = $state(loadAsideWidth());
  let dragging = $state(false);
  let needsOnly = $state(false);
  let pending = $state(false);
  let toast = $state<{ text: string; ok: boolean } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  const sessions = $derived(snapshot?.sessions ?? []);
  const groups = $derived(bucket(sessions));
  const waitingCount = $derived(groups["needs-you"].length);
  const listed = $derived(needsOnly && waitingCount ? groups["needs-you"] : sessions);
  const current = $derived(pickSession(sessions, chosen));
  const errors = $derived(Object.entries(snapshot?.errors ?? {}));

  $effect(() => {
    if (!token) return;
    return subscribe(
      token,
      (next) => (snapshot = next),
      (state) => (connection = state),
    );
  });

  $effect(() => {
    const sessionId = current?.session_id;
    const screen = view === "screen";
    void snapshot?.version;
    if (!sessionId) return;
    let live = true;
    const load = async (): Promise<void> => {
      const next = await fetchDetail(sessionId, token, screen);
      if (live && next?.session_id === sessionId) detail = next;
    };
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, DETAIL_POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  });

  function select(sessionId: string): void {
    if (sessionId === current?.session_id) return;
    chosen = sessionId;
    detail = null;
    history.replaceState(null, "", `${location.search}#${encodeURIComponent(sessionId)}`);
  }

  function pin(sessionId: string): void {
    pins = togglePin(pins, sessionId);
    savePins(pins);
  }

  function changeView(next: View): void {
    view = next;
    saveView(next);
  }

  function setAside(px: number): void {
    asideWidth = clampAside(px);
    saveAsideWidth(asideWidth);
  }

  function startResize(event: PointerEvent): void {
    const handle = event.currentTarget as HTMLElement;
    const startX = event.clientX;
    const startWidth = asideWidth;
    handle.setPointerCapture(event.pointerId);
    dragging = true;
    const move = (moved: PointerEvent): void => {
      asideWidth = clampAside(startWidth + moved.clientX - startX);
    };
    const stop = (): void => {
      dragging = false;
      saveAsideWidth(asideWidth);
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  }

  function resizeByKey(event: KeyboardEvent): void {
    const delta = { ArrowLeft: -RESIZE_STEP_PX, ArrowRight: RESIZE_STEP_PX }[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    setAside(asideWidth + delta);
  }

  async function run(path: string, body: Record<string, unknown>, what: string): Promise<void> {
    pending = true;
    const result = await post(path, body, token);
    pending = false;
    report(result, what);
  }

  function report(result: ActionResult, what: string): void {
    toast = result.ok ? { text: `${what}.`, ok: true } : { text: result.error ?? "Something went wrong.", ok: false };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), TOAST_MS);
  }
</script>

{#if !token}
  <main class="empty">
    <h1>Session Supervisor</h1>
    <p>Open the link printed by <code>dev10x supervisor serve</code>; it carries the access token.</p>
  </main>
{:else}
  <div class={["desk", { dragging }]} style="--aside: {asideWidth}px">
    <header class="brand">
      <p class="eyebrow">Session Supervisor</p>
      {#if waitingCount}
        <button
          class={["headline", "toggle", { on: needsOnly }]}
          aria-pressed={needsOnly}
          title={needsOnly ? "Show every session" : "Show only the sessions waiting for you"}
          onclick={() => (needsOnly = !needsOnly)}
        >
          <span aria-hidden="true" class="diamond">◆</span>
          {headline(groups)}
          <span class="hint">{needsOnly ? "Show all" : "Show only these"}</span>
        </button>
      {:else}
        <p class="headline">{snapshot ? headline(groups) : "Reading sessions…"}</p>
      {/if}
      <p class="meta">
        <span class="conn conn-{connection}" aria-hidden="true"></span>
        {#if connection === "live" && snapshot}
          {clockTime(snapshot.taken_at)} · {groups.working.length} working · {sessions.length} in all
        {:else if connection === "lost"}
          Lost the daemon. Reload once it is back.
        {:else}
          Connecting…
        {/if}
      </p>
      {#if errors.length}
        <ul class="errors" role="status">
          {#each errors as [source, message] (source)}
            <li><strong>{source}</strong> {message}</li>
          {/each}
        </ul>
      {/if}
    </header>

    <div class="index">
      <Sidebar sessions={listed} selected={current?.session_id ?? ""} {pins} onselect={select} onpin={pin} />
    </div>

    <button
      type="button"
      class="resize"
      aria-label="Resize the session list ({asideWidth} pixels); arrow keys adjust"
      title="Drag to resize, double-click to reset"
      onpointerdown={startResize}
      onkeydown={resizeByKey}
      ondblclick={() => setAside(ASIDE_DEFAULT_PX)}
    ></button>

    <main class="center">
      {#if current}
        {@const own = detail?.session_id === current.session_id ? detail : null}
        {#key current.session_id}
          <SessionPane
            session={current}
            conversation={own?.conversation ?? null}
            tail={own?.tail ?? ""}
            {view}
            onview={changeView}
            {pending}
            {run}
          />
        {/key}
      {:else if snapshot}
        <p class="calm">No sessions are running. They appear here, grouped by project, the moment one starts.</p>
      {/if}
    </main>

    <div class="side">
      {#if current}
        <DetailPane session={current} detail={detail?.session_id === current.session_id ? detail : null} {pending} {run} />
      {/if}
    </div>
  </div>
{/if}

<div class="toast-region" aria-live="polite">
  {#if toast}
    <p class={["toast", { bad: !toast.ok }]}>{toast.text}</p>
  {/if}
</div>

<style>
  .desk {
    position: relative;
    display: grid;
    grid-template-columns: var(--aside) minmax(0, 1fr) minmax(18rem, 25rem);
    grid-template-rows: auto minmax(0, 1fr);
    grid-template-areas:
      "brand center side"
      "index center side";
    height: 100dvh;
    overflow: hidden;
  }

  .desk.dragging {
    cursor: col-resize;
    user-select: none;
  }

  .resize {
    position: absolute;
    top: 0;
    bottom: 0;
    left: calc(var(--aside) - 3px);
    width: 7px;
    z-index: 2;
    padding: 0;
    background: none;
    border: none;
    cursor: col-resize;
    touch-action: none;
  }

  .resize::after {
    content: "";
    position: absolute;
    top: 0;
    bottom: 0;
    left: 3px;
    width: 1px;
    background: transparent;
    transition: background 140ms var(--ease-out);
  }

  .resize:hover::after,
  .resize:focus-visible::after,
  .dragging .resize::after {
    width: 2px;
    background: var(--focus);
  }

  .resize:focus-visible {
    outline: none;
  }

  .brand {
    grid-area: brand;
    padding: var(--space-4) var(--space-4) var(--space-3);
    background: var(--paper-sunk);
  }

  .index {
    grid-area: index;
    display: flex;
    min-height: 0;
    background: var(--paper-sunk);
    border-right: 1px solid var(--rule);
  }

  .index > :global(*) {
    flex: 1;
  }

  .brand {
    border-right: 1px solid var(--rule);
  }

  .center {
    grid-area: center;
    min-width: 0;
    min-height: 0;
  }

  .side {
    grid-area: side;
    display: flex;
    min-height: 0;
    border-left: 1px solid var(--rule);
  }

  .side > :global(*) {
    flex: 1;
  }

  .eyebrow {
    margin: 0;
    color: var(--ink-faint);
    font-size: 0.7rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  .headline {
    margin: var(--space-1) 0 0;
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.015em;
  }

  .toggle {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.15rem var(--space-2);
    width: 100%;
    padding: var(--space-1) var(--space-2);
    margin-left: calc(-1 * var(--space-2));
    background: none;
    border: 1px solid transparent;
    border-radius: 3px;
    color: var(--amber-ink);
    text-align: left;
    cursor: pointer;
    transition:
      background 160ms var(--ease-out),
      border-color 160ms var(--ease-out);
  }

  .toggle:hover {
    border-color: var(--amber);
  }

  .toggle.on {
    background: var(--amber-wash);
    border-color: var(--amber);
  }

  .diamond {
    font-size: 0.7em;
  }

  .hint {
    color: var(--ink-soft);
    font-family: var(--font-body);
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0;
    text-decoration: underline;
    text-decoration-color: var(--amber);
    text-underline-offset: 3px;
  }

  .meta {
    margin: var(--space-2) 0 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--ink-soft);
    font-size: 0.74rem;
    font-variant-numeric: tabular-nums;
  }

  .conn {
    width: 0.45rem;
    height: 0.45rem;
    border-radius: 50%;
    background: var(--ink-faint);
  }

  .conn-live {
    background: var(--working);
  }

  .conn-lost {
    background: var(--danger);
  }

  .errors {
    margin: var(--space-2) 0 0;
    padding: var(--space-2) 0 0;
    list-style: none;
    border-top: 1px solid var(--danger);
    color: var(--danger);
    font-size: 0.74rem;
  }

  .calm {
    max-width: 30rem;
    margin: 0;
    padding: var(--space-8) var(--space-6);
    color: var(--ink-soft);
    font-size: var(--step-1);
  }

  @media (max-width: 80rem) {
    .desk {
      grid-template-columns: var(--aside) minmax(0, 1fr);
      grid-template-rows: auto minmax(0, 1fr) minmax(0, 38dvh);
      grid-template-areas:
        "brand center"
        "index center"
        "index side";
    }

    .side {
      border-left: none;
      border-top: 1px solid var(--rule-strong);
    }
  }

  @media (max-width: 48rem) {
    .desk {
      height: auto;
      overflow: visible;
      grid-template-columns: 1fr;
      grid-template-rows: auto auto auto auto;
      grid-template-areas:
        "brand"
        "index"
        "center"
        "side";
    }

    .resize {
      display: none;
    }

    .index {
      max-height: 40dvh;
      border-right: none;
      border-bottom: 1px solid var(--rule-strong);
    }

    .brand {
      border-right: none;
    }

    .center {
      height: 85dvh;
    }
  }

  .empty {
    max-width: 34rem;
    padding: var(--space-8) var(--space-6);
  }

  .empty p {
    color: var(--ink-soft);
  }

  .toast-region {
    position: fixed;
    left: 50%;
    bottom: 6.5rem;
    transform: translateX(-50%);
    max-width: min(34rem, calc(100vw - 2rem));
    pointer-events: none;
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
