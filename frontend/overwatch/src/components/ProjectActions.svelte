<script lang="ts">
  import RangeCalendar from "./RangeCalendar.svelte";
  import { fetchProject } from "../lib/api";
  import { countByDay, inRange, keyOf, type Range } from "../lib/calendar";
  import { ago, shortPath } from "../lib/format";
  import { MODAL_HEIGHT, MODAL_WIDTH, loadWidth, saveWidth } from "../lib/prefs";
  import type { ProjectDetail } from "../lib/types";

  interface Props {
    root: string;
    name: string;
    token: string;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
    onclose: () => void;
  }

  let { root, name, token, pending, run, onclose }: Props = $props();

  type Tab = "new" | "worktrees" | "resume";

  let detail = $state<ProjectDetail | null>(null);
  let problem = $state("");
  let branch = $state("");
  let tab = $state<Tab>("resume");
  let range = $state<Range>({ start: "", end: "" });

  const main = $derived(detail?.checkouts.find((checkout) => checkout.is_main));
  const worktrees = $derived(detail?.checkouts.filter((checkout) => !checkout.is_main) ?? []);
  const counts = $derived(countByDay(detail?.past.map((past) => past.active_at) ?? []));
  const pastShown = $derived(
    (detail?.past ?? []).filter((past) => inRange(keyOf(past.active_at), range)),
  );

  $effect(() => {
    let live = true;
    fetchProject(root, token).then((result) => {
      if (!live) return;
      if (typeof result === "string") problem = result;
      else detail = result;
    });
    return () => {
      live = false;
    };
  });

  const SAVE_SIZE_MS = 250;

  function modal(node: HTMLDialogElement): () => void {
    node.style.width = `${loadWidth(MODAL_WIDTH)}px`;
    node.style.height = `${loadWidth(MODAL_HEIGHT)}px`;
    node.showModal();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const watcher = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        saveWidth(MODAL_WIDTH, node.offsetWidth);
        saveWidth(MODAL_HEIGHT, node.offsetHeight);
      }, SAVE_SIZE_MS);
    });
    watcher.observe(node);
    return () => {
      watcher.disconnect();
      clearTimeout(timer);
      node.close();
    };
  }

  async function launch(body: Record<string, unknown>, what: string): Promise<void> {
    await run("/launch", { root, ...body }, what);
    onclose();
  }

  function leaf(path: string): string {
    return path.split("/").filter(Boolean).pop() ?? path;
  }
</script>

<dialog
  class="project-modal"
  aria-label="Start work in {name}"
  {@attach modal}
  oncancel={(event) => {
    event.preventDefault();
    onclose();
  }}
  onclick={(event) => event.target === event.currentTarget && onclose()}
>
  <div class="frame">
    <header class="head">
      <h2>{name}</h2>
      <span class="root" title={root}>{shortPath(detail?.root ?? root)}</span>
      <button class="close" aria-label="Close" onclick={onclose}>×</button>
    </header>

    <div class="tabs" role="tablist">
      {#each [["new", "New", 0], ["worktrees", "Worktrees", worktrees.length], ["resume", "Resume", detail?.past.length ?? 0]] as [key, label, count] (key)}
        <button
          role="tab"
          aria-selected={tab === key}
          class={{ on: tab === key }}
          onclick={() => (tab = key as Tab)}
        >
          {label}
          {#if count}<span class="count">{count}</span>{/if}
        </button>
      {/each}
    </div>

    {#if problem}
      <p class="quiet">{problem}</p>
    {:else if !detail}
      <p class="quiet">Reading the project…</p>
    {:else if tab === "new"}
      <section class="body new">
        {#if main}
          <button
            class="act"
            disabled={pending}
            onclick={() => launch({ action: "session", path: main.path }, `Started a session in ${name}`)}
          >
            <span class="label">New session in the main folder</span>
            <span class="hint">{main.open ? "opens in a new tab" : "opens a new workspace"} · {main.branch}</span>
          </button>
        {/if}
        <form
          class="branch"
          onsubmit={(event) => {
            event.preventDefault();
            const value = branch.trim();
            if (value) launch({ action: "worktree", branch: value }, `Created worktree ${value} and started a session`);
          }}
        >
          <label for="branch-{root}">New worktree from a branch</label>
          <div class="row">
            <input id="branch-{root}" bind:value={branch} placeholder="janusz/GH-1234/short-name" autocomplete="off" />
            <button type="submit" disabled={pending || !branch.trim()}>Create and start</button>
          </div>
        </form>
      </section>
    {:else if tab === "worktrees"}
      <section class="body">
        {#if worktrees.length}
          <ul class="list">
            {#each worktrees as checkout (checkout.path)}
              <li>
                <button
                  class="pick"
                  disabled={pending}
                  title={checkout.path}
                  onclick={() =>
                    launch({ action: "session", path: checkout.path }, `Started a session in ${leaf(checkout.path)}`)}
                >
                  <span class="label">{leaf(checkout.path)}</span>
                  <span class="hint">{checkout.open ? "new tab" : "open"} · {checkout.branch}</span>
                </button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="quiet">No other worktrees. Create one on the New tab.</p>
        {/if}
      </section>
    {:else}
      <section class="body resume">
        <ul class="list">
          {#each pastShown as past (past.session_id)}
            <li>
              <button
                class="pick"
                disabled={pending}
                title={`${past.cwd}\n${past.topic}`}
                onclick={() =>
                  launch(
                    { action: "resume", session_id: past.session_id },
                    `Resumed ${past.title || past.session_id.slice(0, 8)} in ${leaf(past.cwd)}`,
                  )}
              >
                <span class={["label", { named: past.named }]}>{past.title || past.topic || past.session_id.slice(0, 8)}</span>
                {#if past.title && past.topic}<span class="topic">{past.topic}</span>{/if}
                <span class="hint">{ago(past.active_at)} · {leaf(past.cwd)}</span>
              </button>
            </li>
          {:else}
            <li class="quiet">{range.start ? "No sessions in that date range." : "No past sessions to resume."}</li>
          {/each}
        </ul>
        <RangeCalendar {range} {counts} onchange={(next) => (range = next)} />
      </section>
    {/if}
  </div>
</dialog>

<style>
  .project-modal {
    min-width: 30rem;
    min-height: 20rem;
    max-width: calc(100vw - 2rem);
    max-height: calc(100dvh - 2rem);
    margin: auto;
    padding: 0;
    overflow: hidden;
    resize: both;
    background: var(--paper);
    color: var(--ink);
    border: 1px solid var(--rule-strong);
    border-radius: 4px;
    box-shadow: 0 1.5rem 3rem color-mix(in oklch, var(--ink) 18%, transparent);
  }

  .project-modal::backdrop {
    background: color-mix(in oklch, var(--ink) 35%, transparent);
  }

  .frame {
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr);
    height: 100%;
  }

  .head {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    padding: var(--space-4) var(--space-6) var(--space-2);
  }

  h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: var(--step-1);
  }

  .root {
    flex: 1;
    min-width: 0;
    color: var(--ink-faint);
    font-size: var(--step--1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .close {
    padding: 0 var(--space-2);
    background: none;
    border: none;
    color: var(--ink-soft);
    font-size: 1.3rem;
    cursor: pointer;
  }

  .tabs {
    display: flex;
    gap: var(--space-4);
    padding: 0 var(--space-6);
    border-bottom: 1px solid var(--rule);
  }

  .tabs button {
    padding: var(--space-2) 0;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--ink-soft);
    font-weight: 600;
    cursor: pointer;
  }

  .tabs button.on {
    color: var(--ink);
    border-bottom-color: var(--amber);
  }

  .count {
    color: var(--ink-faint);
    font-weight: 400;
  }

  .body {
    min-height: 0;
    padding: var(--space-4) var(--space-6) var(--space-6);
    overflow-y: auto;
  }

  .new {
    display: grid;
    gap: var(--space-6);
    align-content: start;
  }

  .resume {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--space-6);
    overflow: hidden;
  }

  .resume .list {
    overflow-y: auto;
  }

  @media (max-width: 40rem) {
    .resume {
      grid-template-columns: 1fr;
      overflow-y: auto;
    }
  }

  .list {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .quiet {
    margin: 0;
    padding: var(--space-4) var(--space-6);
    color: var(--ink-soft);
  }

  .list .quiet {
    padding: 0;
  }

  .act,
  .pick {
    width: 100%;
    display: grid;
    gap: 0.1rem;
    padding: var(--space-2) var(--space-3);
    background: none;
    border: 1px solid transparent;
    border-radius: 3px;
    text-align: left;
    cursor: pointer;
  }

  .act {
    border-color: var(--rule-strong);
  }

  .act:hover:not(:disabled),
  .pick:hover:not(:disabled) {
    border-color: var(--rule-strong);
    background: var(--paper-sunk);
  }

  button:disabled {
    cursor: progress;
    opacity: 0.6;
  }

  .label {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .label.named {
    font-weight: 700;
  }

  .topic {
    color: var(--ink-soft);
    font-size: var(--step--1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .hint {
    color: var(--ink-faint);
    font-size: 0.72rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .branch label {
    display: block;
    margin-bottom: var(--space-1);
    color: var(--ink-soft);
    font-weight: 650;
  }

  .row {
    display: flex;
    gap: var(--space-3);
  }

  .row input {
    flex: 1;
    min-width: 0;
    padding: var(--space-2) 0;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--rule-strong);
    font-family: var(--font-term);
  }

  .row input:focus-visible {
    outline: none;
    border-bottom-color: var(--focus);
  }

  .row button {
    padding: var(--space-2) var(--space-4);
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    font-weight: 650;
    cursor: pointer;
  }

  .row button:disabled {
    opacity: 0.35;
  }
</style>
