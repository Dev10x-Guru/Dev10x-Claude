<script lang="ts">
  import { fetchProject } from "../lib/api";
  import { ago, shortPath } from "../lib/format";
  import type { ProjectDetail } from "../lib/types";

  interface Props {
    root: string;
    token: string;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<void>;
    onclose: () => void;
  }

  let { root, token, pending, run, onclose }: Props = $props();

  let detail = $state<ProjectDetail | null>(null);
  let problem = $state("");
  let branch = $state("");

  const main = $derived(detail?.checkouts.find((checkout) => checkout.is_main));
  const worktrees = $derived(detail?.checkouts.filter((checkout) => !checkout.is_main) ?? []);

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

  async function launch(body: Record<string, unknown>, what: string): Promise<void> {
    await run("/launch", { root, ...body }, what);
    onclose();
  }

  function leaf(path: string): string {
    return path.split("/").filter(Boolean).pop() ?? path;
  }
</script>

<section class="actions" aria-label="Start work in {detail?.name ?? leaf(root)}">
  {#if problem}
    <p class="quiet">{problem}</p>
  {:else if !detail}
    <p class="quiet">Reading the project…</p>
  {:else}
    {#if main}
      <button
        class="act"
        disabled={pending}
        onclick={() => launch({ action: "session", path: main.path }, `Started a session in ${detail?.name}`)}
      >
        <span class="glyph" aria-hidden="true">+</span> New session in the main folder
        <span class="hint">{main.open ? "new tab" : "new workspace"} · {main.branch}</span>
      </button>
    {/if}

    <form
      class="branch"
      onsubmit={(event) => {
        event.preventDefault();
        const name = branch.trim();
        if (name) launch({ action: "worktree", branch: name }, `Created worktree ${name} and started a session`);
      }}
    >
      <label for="branch-{root}">New worktree</label>
      <div class="row">
        <input id="branch-{root}" bind:value={branch} placeholder="janusz/GH-1234/short-name" autocomplete="off" />
        <button type="submit" disabled={pending || !branch.trim()}>Create</button>
      </div>
    </form>

    {#if worktrees.length}
      <details>
        <summary>Open a worktree <span class="count">{worktrees.length}</span></summary>
        <ul>
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
      </details>
    {/if}

    {#if detail.past.length}
      <details open>
        <summary>Resume a session <span class="count">{detail.past.length}</span></summary>
        <ul>
          {#each detail.past as past (past.session_id)}
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
                <span class="hint">{ago(past.active_at)} · {shortPath(past.cwd)}</span>
              </button>
            </li>
          {/each}
        </ul>
      </details>
    {/if}
  {/if}
</section>

<style>
  .actions {
    display: grid;
    gap: var(--space-2);
    margin: 0 var(--space-3) var(--space-2) 1.55rem;
    padding: var(--space-2) var(--space-3);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    font-size: var(--step--1);
  }

  .quiet {
    margin: 0;
    color: var(--ink-soft);
  }

  button {
    font: inherit;
  }

  .act,
  .pick {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0 var(--space-2);
    padding: var(--space-1) 0;
    background: none;
    border: none;
    text-align: left;
    cursor: pointer;
  }

  .pick {
    grid-template-columns: 1fr;
  }

  .act {
    font-weight: 650;
  }

  .act .hint {
    grid-column: 2;
  }

  .glyph {
    color: var(--amber-ink);
    font-weight: 700;
  }

  .label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .label.named {
    font-weight: 650;
  }

  .hint {
    color: var(--ink-faint);
    font-size: 0.7rem;
    font-weight: 400;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .act:hover:not(:disabled),
  .pick:hover:not(:disabled) .label {
    text-decoration: underline;
    text-decoration-color: var(--rule-strong);
    text-underline-offset: 3px;
  }

  button:disabled {
    cursor: progress;
    opacity: 0.6;
  }

  .branch label {
    display: block;
    color: var(--ink-soft);
    font-weight: 650;
  }

  .row {
    display: flex;
    gap: var(--space-2);
  }

  .row input {
    flex: 1;
    min-width: 0;
    padding: var(--space-1) 0;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--rule-strong);
    font-family: var(--font-term);
    font-size: 0.74rem;
  }

  .row input:focus-visible {
    outline: none;
    border-bottom-color: var(--focus);
  }

  .row button {
    padding: 0.15rem var(--space-3);
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

  details summary {
    color: var(--ink-soft);
    font-weight: 650;
    cursor: pointer;
  }

  .count {
    color: var(--ink-faint);
    font-weight: 400;
  }

  ul {
    margin: var(--space-1) 0 0;
    padding: 0;
    list-style: none;
    max-height: 16rem;
    overflow-y: auto;
  }
</style>
