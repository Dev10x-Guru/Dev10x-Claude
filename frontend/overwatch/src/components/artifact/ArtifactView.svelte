<script lang="ts">
  import Block from "./Block.svelte";
  import ShareMenu from "./ShareMenu.svelte";
  import {
    controlState,
    deliveryReport,
    describeValue,
    findControl,
    formatRoute,
    isPending,
    navGroups,
    pickView,
    sendControl,
    sentKey,
    share,
    standaloneBlocks,
    type ArtifactDocument,
    type ArtifactIndexEntry,
    type ControlBlock,
    type ControlState,
    type ControlValue,
    type Publisher,
    type SentControls,
  } from "../../lib/artifact";
  import { setControlHost, type ControlStatus } from "../../lib/artifact-host";
  import { ago, clockTime } from "../../lib/format";
  import type { ActionResult } from "../../lib/types";

  interface Props {
    artifact: ArtifactDocument;
    entry: ArtifactIndexEntry | null;
    publishers: Publisher[];
    view: string;
    token: string;
    onreport: (result: ActionResult, what: string) => void;
    onstale: () => void;
  }

  let { artifact, entry, publishers, view, token, onreport, onstale }: Props = $props();

  const STALE = "The page changed";
  const REPEAT = "Already sent";

  let sent = $state<SentControls>({});
  let sending = $state<Record<string, boolean>>({});
  let failures = $state<Record<string, string>>({});
  let sharing = $state("");

  const live = $derived(entry?.owner_live ?? false);
  const owner = $derived(entry?.owner.name || artifact.owner.name || "The owner session");
  const active = $derived(pickView(artifact, view));
  const groups = $derived(navGroups(artifact.views));
  const recent = $derived([...(artifact.events ?? [])].reverse().slice(0, 8));
  const meta = $derived(
    [
      artifact.meta?.as_of && `As of ${artifact.meta.as_of}`,
      artifact.meta?.asked_by && `Asked by ${artifact.meta.asked_by}`,
      artifact.meta?.sources && `Sources: ${artifact.meta.sources}`,
    ].filter((each): each is string => !!each),
  );

  const NOTES: Record<ControlState, (error: string) => string> = {
    ready: () => "",
    sending: () => "Sending…",
    pending: () => `Sent. Waiting for ${owner} to update the page.`,
    offline: () => `${owner} is not running, so this cannot be sent now.`,
    error: (error) => error,
  };

  function status(controlId: string): ControlStatus {
    const error = failures[controlId] ?? "";
    const state = controlState({
      live,
      pending: isPending(artifact, controlId, sent),
      sending: !!sending[controlId],
      error,
    });
    return { state, note: NOTES[state](error) };
  }

  async function send(control: ControlBlock, value: ControlValue): Promise<void> {
    const revision = artifact.revision;
    sending = { ...sending, [control.id]: true };
    const result = await sendControl(
      { artifact_id: artifact.id, revision, control_id: control.id, value },
      token,
    );
    sending = { ...sending, [control.id]: false };
    const repeat = !result.ok && (result.error ?? "").startsWith(REPEAT);
    if (result.ok || repeat) {
      sent = { ...sent, [sentKey(artifact.id, control.id)]: revision };
      failures = { ...failures, [control.id]: "" };
    } else {
      failures = { ...failures, [control.id]: result.error ?? "Something went wrong." };
    }
    onreport(result, deliveryReport(result, `Sent “${control.label}: ${describeValue(value)}” to ${owner}`));
    if (!result.ok && (result.error ?? "").startsWith(STALE)) onstale();
  }

  async function publish(publisher: string): Promise<void> {
    sharing = publisher;
    const result = await share(artifact.id, publisher, token);
    sharing = "";
    const label = publishers.find((each) => each.id === publisher)?.label ?? publisher;
    onreport(result, deliveryReport(result, `Asked ${owner} to publish with ${label}`));
  }

  setControlHost({
    status,
    send,
    find: (controlId) => findControl(artifact, controlId),
  });
</script>

<article class="artifact">
  <header class="head">
    <div class="titles">
      <p class="eyebrow">
        <span class={["live", { on: live }]} aria-hidden="true"></span>
        {owner}{live ? "" : " · not running"} · revision {artifact.revision}
        {#if artifact.updated_at}
          · <time datetime={artifact.updated_at} title={clockTime(artifact.updated_at)}>{ago(artifact.updated_at)}</time>
        {/if}
      </p>
      <h1>{artifact.title}</h1>
      {#if artifact.description}<p class="description">{artifact.description}</p>{/if}
      {#if meta.length}
        <ul class="meta">
          {#each meta as line (line)}<li>{line}</li>{/each}
        </ul>
      {/if}
    </div>
    <ShareMenu
      {publishers}
      shares={artifact.shares ?? []}
      {live}
      busy={sharing}
      {owner}
      onshare={publish}
    />
  </header>

  <div class="body">
    <nav class="nav" aria-label="Page sections">
      {#each groups as group (group.group)}
        <div class="nav-group">
          {#if group.group}<p class="nav-head">{group.group}</p>{/if}
          <ul>
            {#each group.views as each (each.id)}
              <li>
                <a
                  href={formatRoute(artifact.id, each.id)}
                  class={{ current: each.id === active.id }}
                  aria-current={each.id === active.id ? "page" : undefined}
                >
                  <span class="nav-label">{each.label}</span>
                  {#if each.badge}<span class="badge">{each.badge}</span>{/if}
                </a>
              </li>
            {/each}
          </ul>
        </div>
      {/each}
      {#if recent.length}
        <div class="nav-group activity">
          <p class="nav-head">Sent from this page</p>
          <ul>
            {#each recent as event, index (event.event_id ?? index)}
              <li>
                {#if event.kind === "share"}
                  Share · {event.publisher}
                {:else}
                  {event.label || findControl(artifact, event.control_id ?? "")?.label || event.control_id}: {describeValue(event.value)}
                {/if}
                {#if event.revision !== undefined}<span class="rev">r{event.revision}</span>{/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    </nav>

    <section class="view" aria-labelledby="artifact-view-title">
      <h2 id="artifact-view-title">{active.label}</h2>
      {#each standaloneBlocks(active) as block, index (`${active.id}:${index}`)}
        <div class="block"><Block {block} /></div>
      {:else}
        <p class="empty">This view is empty.</p>
      {/each}
    </section>
  </div>
</article>

<style>
  .artifact {
    container: artifact / inline-size;
    height: 100%;
    overflow-y: auto;
    scrollbar-width: thin;
  }

  .head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-6) var(--space-6) var(--space-4);
    border-bottom: 1px solid var(--rule);
  }

  .titles {
    min-width: 0;
  }

  .eyebrow {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0 var(--space-1);
    color: var(--ink-faint);
    font-size: 0.74rem;
    font-variant-numeric: tabular-nums;
  }

  .live {
    width: 0.45rem;
    height: 0.45rem;
    margin-right: var(--space-1);
    border-radius: 50%;
    background: var(--ink-faint);
  }

  .live.on {
    background: var(--working);
  }

  h1 {
    margin: var(--space-1) 0 0;
    font-family: var(--font-display);
    font-size: var(--step-3);
    font-weight: 700;
    line-height: 1.05;
    letter-spacing: -0.02em;
    overflow-wrap: anywhere;
    text-wrap: balance;
  }

  .description {
    margin: var(--space-2) 0 0;
    max-width: 68ch;
    color: var(--ink-soft);
  }

  .meta {
    margin: var(--space-2) 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 0 var(--space-4);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .body {
    display: grid;
    grid-template-columns: minmax(10rem, 14rem) minmax(0, 1fr);
    align-items: start;
  }

  .nav {
    position: sticky;
    top: 0;
    padding: var(--space-4) var(--space-3) var(--space-6) var(--space-4);
    display: grid;
    gap: var(--space-4);
  }

  .nav ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .nav-head {
    margin: 0 0 var(--space-1);
    color: var(--ink-faint);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  .nav a {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
    border-left: 2px solid transparent;
    color: var(--ink-soft);
    font-size: var(--step--1);
    text-decoration: none;
  }

  .nav a:hover {
    color: var(--ink);
  }

  .nav a.current {
    border-left-color: var(--ink);
    background: var(--paper-sunk);
    color: var(--ink);
    font-weight: 650;
  }

  .nav-label {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .badge {
    flex: none;
    padding: 0 0.4em;
    border-radius: 999px;
    background: var(--amber-wash);
    color: var(--amber-ink);
    font-size: 0.68rem;
    font-weight: 650;
  }

  .activity li {
    padding: var(--space-1) 0;
    color: var(--ink-soft);
    font-size: 0.72rem;
    overflow-wrap: anywhere;
  }

  .rev {
    margin-left: var(--space-1);
    color: var(--ink-faint);
    font-variant-numeric: tabular-nums;
  }

  .view {
    min-width: 0;
    padding: var(--space-4) var(--space-6) var(--space-8);
    display: grid;
    gap: var(--space-4);
    align-content: start;
  }

  h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 650;
  }

  .block {
    min-width: 0;
  }

  .empty {
    margin: 0;
    color: var(--ink-soft);
  }

  @container artifact (max-width: 820px) {
    .head {
      padding: var(--space-4);
      flex-direction: column;
    }

    .body {
      grid-template-columns: 1fr;
    }

    .nav {
      z-index: 3;
      display: flex;
      gap: var(--space-3);
      padding: var(--space-2) var(--space-4);
      overflow-x: auto;
      background: var(--paper);
      border-bottom: 1px solid var(--rule);
      scrollbar-width: thin;
    }

    .nav-group {
      display: flex;
      align-items: center;
      gap: var(--space-1);
      flex: none;
    }

    .nav-head {
      margin: 0;
    }

    .nav ul {
      display: flex;
      gap: var(--space-1);
    }

    .nav a {
      white-space: nowrap;
      border-left: none;
      border-bottom: 2px solid transparent;
    }

    .nav a.current {
      border-bottom-color: var(--ink);
    }

    .activity {
      display: none;
    }

    .view {
      padding: var(--space-4);
    }
  }
</style>
