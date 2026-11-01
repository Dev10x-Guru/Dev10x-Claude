<script lang="ts">
  import RecentAnswers from "./RecentAnswers.svelte";
  import Toggle from "./Toggle.svelte";
  import ToolPreview from "./ToolPreview.svelte";
  import { approvedByHand, displayName } from "../lib/format";
  import type { RecentTool, Session, SessionDetail } from "../lib/types";

  interface Props {
    session: Session;
    detail: SessionDetail | null;
    pending: boolean;
    live: (sessionId: string) => boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
  }

  let { session, detail, pending, live, run }: Props = $props();

  const OUTCOMES: Record<RecentTool["outcome"], string> = {
    ran: "ran",
    failed: "failed",
    rejected: "rejected",
    pending: "waiting",
  };

  let approvedOnly = $state(false);

  const openTasks = $derived(detail?.tasks.filter((task) => task.status !== "completed") ?? []);
  const doneCount = $derived(detail?.tasks.filter((task) => task.status === "completed").length ?? 0);

  const preview = $derived(detail?.preview ?? session.preview);
  const commandCount = $derived(detail?.recent.filter((tool) => tool.command).length ?? 0);
  const approvedCount = $derived(detail?.recent.filter(approvedByHand).length ?? 0);
  const shownCalls = $derived(
    approvedOnly ? (detail?.recent.filter(approvedByHand) ?? []) : (detail?.recent ?? []),
  );

  function preapprove(command?: string): void {
    run(
      "/preapprove",
      command ? { session_id: session.session_id, command } : { session_id: session.session_id },
      command
        ? `Asked the relay to draft an allow rule for that command from ${displayName(session)}; it checks with you before writing`
        : `Asked the relay to draft allow rules from ${displayName(session)}'s commands; it checks with you before writing`,
    );
  }
</script>

<aside class="detail" aria-label="Details for {displayName(session)}">
  <section class="tasks">
    <header class="recent-head">
      <h2>Tasks</h2>
      {#if detail?.tasks.length}
        <span class="n">{doneCount}/{detail.tasks.length} done</span>
      {/if}
    </header>
    {#if detail === null}
      <p class="quiet">Reading the task list…</p>
    {:else if openTasks.length || doneCount}
      <ol>
        {#each openTasks as task (task.id)}
          <li class={["task", task.status]}>
            <span class="tick" aria-hidden="true">{task.status === "in_progress" ? "◐" : "○"}</span>
            <span class="subject">{task.status === "in_progress" && task.active_form ? task.active_form : task.subject}</span>
          </li>
        {/each}
      </ol>
      {#if doneCount}
        <details>
          <summary>{doneCount} completed</summary>
          <ol>
            {#each detail.tasks.filter((task) => task.status === "completed") as task (task.id)}
              <li class="task completed">
                <span class="tick" aria-hidden="true">✓</span>
                <span class="subject">{task.subject}</span>
              </li>
            {/each}
          </ol>
        </details>
      {/if}
    {:else}
      <p class="quiet">This session keeps no task list.</p>
    {/if}
  </section>

  <section>
    <h2>Waiting to run</h2>
    {#if preview}
      <ToolPreview {preview} />
    {:else}
      <p class="quiet">No tool call is waiting. A pending edit shows here as a diff, a command as its full text.</p>
    {/if}
  </section>

  <section class="recent">
    <header class="recent-head">
      <h2>Recent calls</h2>
      {#if commandCount}
        <button class="ghost" disabled={pending} onclick={() => preapprove()}>Pre-approve all used</button>
      {/if}
    </header>
    <div class="only">
      <Toggle on={approvedOnly} onchange={(next) => (approvedOnly = next)}>
        Only ones I approved by hand <span class="n">{approvedCount}</span>
      </Toggle>
    </div>
    {#if detail === null}
      <p class="quiet">Reading the transcript…</p>
    {:else if shownCalls.length}
      <ol>
        {#each shownCalls as tool, index (index)}
          <li class={["call", tool.outcome]}>
            <span class="tool">
              {tool.tool}
              {#if approvedByHand(tool)}<span class="by-hand" title={tool.decided_by}>you approved</span>{/if}
            </span>
            <span class="outcome">{OUTCOMES[tool.outcome]}</span>
            {#if tool.target}<code title={tool.target}>{tool.target}</code>{/if}
            {#if tool.command}
              <button class="approve" disabled={pending} onclick={() => preapprove(tool.command)}>
                Pre-approve
              </button>
            {/if}
          </li>
        {/each}
      </ol>
    {:else if approvedOnly}
      <p class="quiet">Nothing in the recent calls needed your approval; rules or the mode let them all through.</p>
    {:else}
      <p class="quiet">This session has not called a tool yet, or its transcript is out of reach.</p>
    {/if}
  </section>

  <RecentAnswers {pending} {live} {run} />
</aside>

<style>
  .detail {
    display: flex;
    flex-direction: column;
    gap: var(--space-6);
    min-height: 0;
    padding: var(--space-4) var(--space-4) var(--space-8);
    overflow-y: auto;
    scrollbar-width: thin;
  }

  h2 {
    margin: 0 0 var(--space-2);
    font-family: var(--font-display);
    font-size: 0.78rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-soft);
  }

  .quiet {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .recent-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .ghost {
    padding: 0;
    background: none;
    border: none;
    color: var(--ink);
    font-size: var(--step--1);
    font-weight: 600;
    text-decoration: underline;
    text-decoration-color: var(--amber);
    text-underline-offset: 3px;
    cursor: pointer;
  }

  .only {
    margin: 0 0 var(--space-2);
  }

  .task {
    display: grid;
    grid-template-columns: 1rem minmax(0, 1fr);
    gap: var(--space-2);
    padding: 0.2rem 0;
    font-size: var(--step--1);
  }

  .tick {
    color: var(--ink-faint);
    text-align: center;
  }

  .task.in_progress .tick,
  .task.in_progress .subject {
    color: var(--amber-ink);
    font-weight: 650;
  }

  .task.completed .subject {
    color: var(--ink-faint);
    text-decoration: line-through;
    text-decoration-color: var(--rule-strong);
  }

  .subject {
    overflow-wrap: anywhere;
  }

  .tasks details summary {
    margin-top: var(--space-1);
    color: var(--ink-soft);
    font-size: 0.74rem;
    cursor: pointer;
  }

  .n {
    color: var(--ink-faint);
    font-variant-numeric: tabular-nums;
  }

  .by-hand {
    margin-left: var(--space-1);
    padding: 0 0.3rem;
    border-radius: 2px;
    background: var(--amber-wash);
    color: var(--amber-ink);
    font-size: 0.66rem;
    font-weight: 650;
  }

  ol {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .call {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: baseline;
    gap: 0.15rem var(--space-2);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--rule);
    font-size: var(--step--1);
  }

  .tool {
    font-weight: 650;
  }

  .outcome {
    color: var(--ink-faint);
    font-size: 0.72rem;
    text-align: right;
  }

  .rejected .outcome,
  .failed .outcome {
    color: var(--danger);
  }

  .pending .outcome {
    color: var(--amber-ink);
    font-weight: 650;
  }

  code {
    grid-column: 1 / -1;
    font-family: var(--font-term);
    font-size: 0.74rem;
    color: var(--ink-soft);
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow-wrap: anywhere;
  }

  .approve {
    grid-column: 1 / -1;
    justify-self: start;
    padding: 0.1rem var(--space-2);
    background: none;
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;
    opacity: 0;
    transition: opacity 140ms var(--ease-out), border-color 140ms var(--ease-out);
  }

  .call:hover .approve,
  .call:focus-within .approve,
  .pending .approve {
    opacity: 1;
  }

  .approve:hover:not(:disabled) {
    border-color: var(--ink);
  }

  @media (hover: none) {
    .approve {
      opacity: 1;
    }
  }

  button:disabled {
    cursor: progress;
  }
</style>
