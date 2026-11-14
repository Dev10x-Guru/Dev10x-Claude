<script lang="ts">
  import DetailPane from "./components/DetailPane.svelte";
  import PageSettings from "./components/PageSettings.svelte";
  import SessionPane from "./components/SessionPane.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import ArtifactView from "./components/artifact/ArtifactView.svelte";
  import {
    browserStorage,
    checkToken,
    fetchDetail,
    forgetToken,
    post,
    resolveToken,
    subscribe,
    type Connection,
  } from "./lib/api";
  import { fetchArtifact, parseRoute, type ArtifactDocument } from "./lib/artifact";
  import { bucket, clockTime, headline } from "./lib/format";
  import {
    ASIDE,
    SIDE,
    clampWidth,
    loadAfterAnswer,
    loadPins,
    loadView,
    loadWidth,
    saveAfterAnswer,
    savePins,
    saveView,
    saveWidth,
    togglePin,
    type AfterAnswer,
    type Panel,
  } from "./lib/prefs";
  import {
    ACK_GRACE_MS,
    asksQuestion,
    awaitingAck,
    nextQuestion,
    pickSession,
    pruneSent,
    questionKey,
    type SentAnswers,
  } from "./lib/selection";
  import type { ActionResult, SessionDetail, Snapshot, View } from "./lib/types";

  const TOAST_MS = 5000;
  const DETAIL_POLL_MS = 2500;
  const RESIZE_STEP_PX = 16;
  const ACK_TICK_MS = 5000;
  const PANELS = {
    aside: { panel: ASIDE, grows: 1 },
    side: { panel: SIDE, grows: -1 },
  } satisfies Record<string, { panel: Panel; grows: number }>;

  type Edge = keyof typeof PANELS;

  const storage = browserStorage();
  const found = resolveToken(location.search, storage);

  const mustCheck = found.remembered && found.token !== "";

  let token = $state(found.remembered ? "" : found.token);
  let checking = $state(mustCheck);
  let expired = $state(false);

  async function adoptRemembered(): Promise<void> {
    const verdict = await checkToken(found.token);
    checking = false;
    if (verdict === "rejected") {
      drop();
      return;
    }
    token = found.token;
  }

  function drop(): void {
    forgetToken(storage);
    token = "";
    expired = true;
  }

  async function recheck(state: Connection): Promise<void> {
    if (state === "live" || !token) return;
    if ((await checkToken(token)) === "rejected") drop();
  }

  if (mustCheck) adoptRemembered();

  let snapshot = $state<Snapshot | null>(null);
  let connection = $state<Connection>("connecting");
  const initialRoute = parseRoute(location.hash);

  let route = $state(initialRoute);
  let chosen = $state(initialRoute ? "" : sessionFromHash(location.hash));
  let artifact = $state<ArtifactDocument | null>(null);
  let artifactError = $state("");
  let artifactReloads = $state(0);
  let detail = $state<SessionDetail | null>(null);
  let pins = $state(loadPins());
  let view = $state<View>(loadView());
  let widths = $state<Record<Edge, number>>({ aside: loadWidth(ASIDE), side: loadWidth(SIDE) });
  let dragging = $state(false);
  let needsOnly = $state(false);
  let afterAnswer = $state<AfterAnswer>(loadAfterAnswer());
  let sent = $state<SentAnswers>({});
  let now = $state(Date.now());
  let pending = $state(false);
  let toast = $state<{ text: string; ok: boolean } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | undefined;

  const sessions = $derived(snapshot?.sessions ?? []);
  const groups = $derived(bucket(sessions));
  const waitingCount = $derived(groups["needs-you"].length);
  const listed = $derived(needsOnly && waitingCount ? groups["needs-you"] : sessions);
  const current = $derived(pickSession(sessions, chosen));
  const errors = $derived(Object.entries(snapshot?.errors ?? {}));
  const otherQuestions = $derived(
    sessions.filter((session) => {
      if (session.session_id === current?.session_id || !asksQuestion(session)) return false;
      const entry = awaitingAck(session, sent);
      return !entry || now - entry.at >= ACK_GRACE_MS;
    }).length,
  );
  const ackSince = $derived(current ? (awaitingAck(current, sent)?.at ?? null) : null);
  const artifacts = $derived(snapshot?.artifacts ?? []);
  const artifactEntry = $derived(route ? (artifacts.find((each) => each.id === route?.id) ?? null) : null);
  const artifactRevision = $derived(artifactEntry?.revision ?? 0);

  function sessionFromHash(hash: string): string {
    try {
      return decodeURIComponent(hash.slice(1));
    } catch {
      return "";
    }
  }

  $effect(() => {
    const follow = (): void => {
      route = parseRoute(location.hash);
      if (!route) chosen = sessionFromHash(location.hash);
    };
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  });

  $effect(() => {
    const id = route?.id;
    void artifactRevision;
    void artifactReloads;
    if (!id || !token) return;
    let live = true;
    fetchArtifact(id, token).then((next) => {
      if (!live) return;
      if (typeof next === "string") {
        artifactError = next;
        if (artifact?.id !== id) artifact = null;
      } else {
        artifactError = "";
        artifact = next;
      }
    });
    return () => {
      live = false;
    };
  });

  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), ACK_TICK_MS);
    return () => clearInterval(timer);
  });

  $effect(() => {
    const kept = pruneSent(sessions, sent);
    if (Object.keys(kept).length !== Object.keys(sent).length) sent = kept;
  });

  $effect(() => {
    if (!token) return;
    return subscribe(
      token,
      (next) => (snapshot = next),
      (state) => {
        connection = state;
        recheck(state);
      },
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
    if (sessionId === current?.session_id && !route) return;
    route = null;
    chosen = sessionId;
    detail = null;
    history.replaceState(null, "", `${location.search}#${encodeURIComponent(sessionId)}`);
  }

  function pin(sessionId: string): void {
    pins = togglePin(pins, sessionId);
    savePins(pins);
  }

  function changeAfterAnswer(next: AfterAnswer): void {
    afterAnswer = next;
    saveAfterAnswer(next);
  }

  function answered(sessionId: string): void {
    const session = sessions.find((each) => each.session_id === sessionId);
    if (session) sent = { ...sent, [sessionId]: { key: questionKey(session), at: Date.now() } };
    if (afterAnswer !== "next") return;
    const next = nextQuestion(sessions, sessionId, sent, Date.now());
    if (next) select(next);
  }

  function changeView(next: View): void {
    view = next;
    saveView(next);
  }

  function setWidth(edge: Edge, px: number): void {
    widths[edge] = clampWidth(PANELS[edge].panel, px);
    saveWidth(PANELS[edge].panel, widths[edge]);
  }

  function startResize(edge: Edge, event: PointerEvent): void {
    const { panel, grows } = PANELS[edge];
    const handle = event.currentTarget as HTMLElement;
    const startX = event.clientX;
    const startWidth = widths[edge];
    handle.setPointerCapture(event.pointerId);
    dragging = true;
    const move = (moved: PointerEvent): void => {
      widths[edge] = clampWidth(panel, startWidth + grows * (moved.clientX - startX));
    };
    const stop = (): void => {
      dragging = false;
      saveWidth(panel, widths[edge]);
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  }

  function resizeByKey(edge: Edge, event: KeyboardEvent): void {
    const delta = { ArrowLeft: -RESIZE_STEP_PX, ArrowRight: RESIZE_STEP_PX }[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    setWidth(edge, widths[edge] + PANELS[edge].grows * delta);
  }

  async function run(path: string, body: Record<string, unknown>, what: string): Promise<boolean> {
    pending = true;
    const result = await post(path, body, token);
    pending = false;
    report(result, what);
    return result.ok;
  }

  function report(result: ActionResult, what: string): void {
    toast = result.ok ? { text: `${what}.`, ok: true } : { text: result.error ?? "Something went wrong.", ok: false };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast = null), TOAST_MS);
  }
</script>

{#if !token}
  <main class="empty">
    <h1>Session Overwatch</h1>
    {#if checking}
      <p>Checking the remembered access token…</p>
    {:else if expired}
      <p>
        Overwatch restarted, so the remembered access token no longer works. Open the fresh link printed by
        <code>dev10x overwatch serve</code>.
      </p>
    {:else}
      <p>Open the link printed by <code>dev10x overwatch serve</code>; it carries the access token.</p>
    {/if}
  </main>
{:else}
  {#snippet handle(edge: Edge, what: string)}
    <button
      type="button"
      class="resize resize-{edge}"
      aria-label="Resize the {what} ({widths[edge]} pixels); arrow keys adjust"
      title="Drag to resize, double-click to reset"
      onpointerdown={(event) => startResize(edge, event)}
      onkeydown={(event) => resizeByKey(edge, event)}
      ondblclick={() => setWidth(edge, PANELS[edge].panel.fallback)}
    ></button>
  {/snippet}

  <div class={["desk", { dragging }]} style="--aside: {widths.aside}px; --side: {widths.side}px">
    <header class="brand">
      <p class="eyebrow">Session Overwatch</p>
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
      {#if snapshot?.settings}
        <PageSettings settings={snapshot.settings} {pending} {run} />
      {/if}
      {#if errors.length}
        <ul class="errors" role="status">
          {#each errors as [source, message] (source)}
            <li><strong>{source}</strong> {message}</li>
          {/each}
        </ul>
      {/if}
    </header>

    <div class="index">
      <Sidebar
        sessions={listed}
        selected={current?.session_id ?? ""}
        {pins}
        {token}
        {pending}
        {artifacts}
        artifact={route?.id ?? ""}
        onselect={select}
        onpin={pin}
        {run}
      />
    </div>

    {@render handle("aside", "session list")}
    {@render handle("side", "details panel")}

    <main class="center">
      {#if route}
        {#if artifact?.id === route.id}
          {#key artifact.id}
            <ArtifactView
              {artifact}
              entry={artifactEntry}
              publishers={snapshot?.publishers ?? []}
              view={route.view}
              {token}
              onreport={report}
              onstale={() => artifactReloads++}
            />
          {/key}
        {:else if artifactError}
          <p class="calm">This page did not load: {artifactError}</p>
        {:else}
          <p class="calm">Loading the page…</p>
        {/if}
      {:else if current}
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
            {afterAnswer}
            onafteranswer={changeAfterAnswer}
            onanswered={answered}
            {otherQuestions}
            {ackSince}
            nameOf={(sessionId) => {
              const found = sessions.find((session) => session.session_id === sessionId);
              return found ? found.callsign || found.name : "that session";
            }}
          />
        {/key}
      {:else if snapshot}
        <p class="calm">No sessions are running. They appear here, grouped by project, the moment one starts.</p>
      {/if}
    </main>

    <div class="side">
      {#if current}
        <DetailPane
          session={current}
          detail={detail?.session_id === current.session_id ? detail : null}
          {pending}
          live={(sessionId) => sessions.some((session) => session.session_id === sessionId)}
          {run}
        />
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
    grid-template-columns: var(--aside) minmax(0, 1fr) var(--side);
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

  .resize-side {
    left: auto;
    right: calc(var(--side) - 4px);
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
  .resize:active::after {
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

    .resize-side {
      display: none;
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
