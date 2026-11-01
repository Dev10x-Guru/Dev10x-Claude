<script lang="ts">
  import ProjectActions from "./ProjectActions.svelte";
  import StatusMark from "./StatusMark.svelte";
  import Toggle from "./Toggle.svelte";
  import { displayName } from "../lib/format";
  import { PROJECT_MIME, SESSION_MIME, carriesProject } from "../lib/drag";
  import {
    PROJECT_ORDER_KEY,
    PROJECT_PINS_KEY,
    loadHideStopped,
    loadList,
    moveBefore,
    moveBy,
    saveHideStopped,
    saveList,
    togglePin,
  } from "../lib/prefs";
  import { arrange, buildTree, isActive, markOf, matches } from "../lib/tree";
  import type { Session } from "../lib/types";

  interface Props {
    sessions: Session[];
    selected: string;
    pins: string[];
    token: string;
    pending: boolean;
    onselect: (sessionId: string) => void;
    onpin: (sessionId: string) => void;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
  }

  let { sessions, selected, pins, token, pending, onselect, onpin, run }: Props = $props();

  let query = $state("");
  let collapsed = $state<Record<string, boolean>>({});
  let acting = $state<{ name: string; root: string } | null>(null);
  let projectPins = $state(loadList(PROJECT_PINS_KEY));
  let projectOrder = $state(loadList(PROJECT_ORDER_KEY));
  let dropTarget = $state("");

  let hideStopped = $state(loadHideStopped());

  const stoppedCount = $derived(sessions.filter((session) => !isActive(session)).length);
  const visible = $derived(
    sessions.filter((session) => matches(session, query) && (!hideStopped || isActive(session))),
  );
  const pinned = $derived(
    pins
      .map((id) => visible.find((session) => session.session_id === id))
      .filter((session): session is Session => !!session),
  );
  const tree = $derived(
    arrange(
      buildTree(visible.filter((session) => !pins.includes(session.session_id))),
      projectOrder,
      projectPins,
    ),
  );

  function toggle(name: string): void {
    collapsed = { ...collapsed, [name]: !collapsed[name] };
  }

  function pinProject(name: string): void {
    projectPins = togglePin(projectPins, name);
    saveList(PROJECT_PINS_KEY, projectPins);
  }

  function reorder(next: string[]): void {
    projectOrder = next;
    saveList(PROJECT_ORDER_KEY, projectOrder);
  }

  function shown(): string[] {
    return tree.map((project) => project.name);
  }

  function dragProject(event: DragEvent, name: string): void {
    event.dataTransfer?.setData(PROJECT_MIME, name);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "linkMove";
  }

  function overProject(event: DragEvent, name: string): void {
    if (!carriesProject(event.dataTransfer?.types)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    dropTarget = name;
  }

  function dropProject(event: DragEvent, name: string): void {
    dropTarget = "";
    const dragged = event.dataTransfer?.getData(PROJECT_MIME) ?? "";
    if (!dragged) return;
    event.preventDefault();
    reorder(moveBefore(shown(), dragged, name));
  }

  function nudge(event: KeyboardEvent, name: string): void {
    const step = { ArrowUp: -1, ArrowDown: 1 }[event.key];
    if (!event.altKey || step === undefined) return;
    event.preventDefault();
    reorder(moveBy(shown(), name, step));
  }
</script>

{#snippet plus(name: string, root: string)}
  <button
    class={["project-pin", { on: projectPins.includes(name) }]}
    aria-pressed={projectPins.includes(name)}
    aria-label={projectPins.includes(name) ? `Unpin project ${name}` : `Pin project ${name} to the top`}
    title={projectPins.includes(name) ? "Unpin project" : "Pin project to the top (drag or Alt+↑/↓ to reorder)"}
    onclick={() => pinProject(name)}>{projectPins.includes(name) ? "★" : "☆"}</button
  >
  <button
    class={["plus", { on: acting?.name === name }]}
    aria-haspopup="dialog"
    aria-label="New session, worktree or resume in {name}"
    title="New session, worktree or resume"
    onclick={() => (acting = { name, root })}>+</button
  >
{/snippet}

{#snippet leaf(session: Session, showProject: boolean)}
  {@const ws = session.workspace}
  {@const isPinned = pins.includes(session.session_id)}
  <li
    class={["leaf", { current: session.session_id === selected, pinned: isPinned }]}
    draggable="true"
    ondragstart={(event) => {
      event.dataTransfer?.setData(SESSION_MIME, session.session_id);
      event.dataTransfer?.setData("text/plain", displayName(session));
      if (event.dataTransfer) event.dataTransfer.effectAllowed = "link";
    }}
  >
    <button
      class="pick"
      title={`${displayName(session)} · ${session.cwd}`}
      aria-current={session.session_id === selected ? "true" : undefined}
      onclick={() => onselect(session.session_id)}
    >
      <StatusMark mark={markOf(session)} />
      <span class="leaf-name">{displayName(session)}</span>
      {#if showProject}<span class="leaf-project">{ws.project}</span>{/if}
    </button>
    <span class="refs">
      {#if ws.issue}
        {#if ws.issue_url}
          <a href={ws.issue_url} target="_blank" rel="noreferrer" title="Issue {ws.issue}">{ws.issue}</a>
        {:else}
          <span title="Issue {ws.issue}">{ws.issue}</span>
        {/if}
      {/if}
      {#if ws.pr}
        {#if ws.pr_url}
          <a href={ws.pr_url} target="_blank" rel="noreferrer" title="Pull request {ws.pr}">#{ws.pr}</a>
        {:else}
          <span title="Pull request {ws.pr}">#{ws.pr}</span>
        {/if}
      {/if}
      <button
        class="pin"
        aria-pressed={isPinned}
        aria-label={isPinned ? `Unpin ${displayName(session)}` : `Pin ${displayName(session)} to the top`}
        title={isPinned ? "Unpin" : "Pin to the top"}
        onclick={() => onpin(session.session_id)}>{isPinned ? "★" : "☆"}</button
      >
    </span>
  </li>
{/snippet}

<nav class="index" aria-label="Sessions">
  <label class="search">
    <span class="visually-hidden">Filter sessions</span>
    <input bind:value={query} type="search" placeholder="Filter by name, branch, issue" autocomplete="off" />
  </label>
  <div class="stopped">
    <Toggle
      on={hideStopped}
      onchange={(next) => {
        hideStopped = next;
        saveHideStopped(next);
      }}
    >
      Hide idle and done <span class="count">{stoppedCount}</span>
    </Toggle>
  </div>

  <div class="scroll">
    {#if pinned.length}
      <section class="group" aria-label="Pinned">
        <p class="group-head">Pinned</p>
        <ul class="sessions flat">
          {#each pinned as session (session.session_id)}
            {@render leaf(session, true)}
          {/each}
        </ul>
      </section>
    {/if}

    <ul class="projects">
      {#each tree as project (project.name)}
        {@const open = !collapsed[project.name] || !!query}
        {@const root = project.folders[0].sessions[0].workspace.root || project.folders[0].root}
        {#if project.count === 1}
          <li
            class={["project", { target: dropTarget === project.name }]}
            ondragover={(event) => overProject(event, project.name)}
            ondragleave={() => (dropTarget = "")}
            ondrop={(event) => dropProject(event, project.name)}
          >
            <div
              class="project-row"
              role="group"
              aria-label="Project {project.name}"
              ondragstartcapture={(event) => dragProject(event, project.name)}
            >
              <ul class="sessions flat">
                {@render leaf(project.folders[0].sessions[0], true)}
              </ul>
              {@render plus(project.name, root)}
            </div>
          </li>
        {:else}
        <li
          class={["project", { target: dropTarget === project.name }]}
          ondragover={(event) => overProject(event, project.name)}
          ondragleave={() => (dropTarget = "")}
          ondrop={(event) => dropProject(event, project.name)}
        >
          <div
            class="project-row"
            role="group"
            aria-label="Project {project.name}; drag to reorder"
            draggable="true"
            ondragstart={(event) => dragProject(event, project.name)}
          >
            <button
              class="project-head"
              aria-expanded={open}
              onclick={() => toggle(project.name)}
              onkeydown={(event) => nudge(event, project.name)}
            >
              <span class={["caret", { open }]} aria-hidden="true"></span>
              <StatusMark mark={project.mark} />
              <span class="project-name">{project.name}</span>
              <span class="count">{project.count}</span>
            </button>
            {@render plus(project.name, root)}
          </div>

          {#if open}
            <ul class="sessions">
              {#each project.folders.flatMap((folder) => folder.sessions) as session (session.session_id)}
                {@render leaf(session, false)}
              {/each}
            </ul>
          {/if}
        </li>
        {/if}
      {:else}
        {#if !pinned.length}
          <li class="none">{query ? "No session matches that filter." : "No sessions yet."}</li>
        {/if}
      {/each}
    </ul>
  </div>

  {#if acting}
    {#key acting.root}
      <ProjectActions
        root={acting.root}
        name={acting.name}
        {token}
        {pending}
        {run}
        onclose={() => (acting = null)}
      />
    {/key}
  {/if}
</nav>

<style>
  .index {
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
  }

  .search {
    display: block;
    padding: 0 var(--space-4) var(--space-3);
  }

  .search input {
    width: 100%;
    padding: var(--space-1) 0;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--rule-strong);
    font-size: var(--step--1);
  }

  .stopped {
    padding: 0 var(--space-4) var(--space-2);
  }

  .search input:focus-visible {
    outline: none;
    border-bottom-color: var(--focus);
  }

  .scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding-bottom: var(--space-8);
    scrollbar-width: thin;
  }

  .group {
    padding-bottom: var(--space-2);
    margin-bottom: var(--space-2);
    border-bottom: 1px solid var(--rule);
  }

  .group-head {
    margin: 0;
    padding: var(--space-1) var(--space-4);
    color: var(--ink-faint);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  .projects {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .project + .project {
    margin-top: var(--space-1);
  }

  .project-row {
    display: flex;
    align-items: center;
    min-width: 0;
  }

  .project-row > :first-child {
    flex: 1;
    min-width: 0;
  }

  .project.target {
    box-shadow: inset 0 2px 0 var(--focus);
  }

  .project-row[draggable="true"] {
    cursor: grab;
  }

  .project-pin {
    flex: none;
    width: 1.2rem;
    padding: 0;
    background: none;
    border: none;
    color: var(--ink-faint);
    font-size: 0.8rem;
    line-height: 1;
    cursor: pointer;
    opacity: 0;
    transition: opacity 140ms var(--ease-out);
  }

  .project-row:hover .project-pin,
  .project-pin:focus-visible,
  .project-pin.on {
    opacity: 1;
  }

  .project-pin.on {
    color: var(--amber-ink);
  }

  @media (hover: none) {
    .project-pin {
      opacity: 1;
    }
  }

  .plus {
    flex: none;
    width: 1.4rem;
    height: 1.4rem;
    margin-right: var(--space-2);
    padding: 0;
    background: none;
    border: 1px solid transparent;
    border-radius: 3px;
    color: var(--ink-faint);
    font-size: 0.95rem;
    line-height: 1;
    cursor: pointer;
    opacity: 0;
    transition:
      opacity 140ms var(--ease-out),
      border-color 140ms var(--ease-out);
  }

  .project-row:hover .plus,
  .plus:focus-visible,
  .plus.on {
    opacity: 1;
  }

  .plus:hover,
  .plus.on {
    border-color: var(--rule-strong);
    color: var(--ink);
  }

  @media (hover: none) {
    .plus {
      opacity: 1;
    }
  }

  .project-head {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4) var(--space-1);
    background: none;
    border: none;
    text-align: left;
    cursor: pointer;
  }

  .caret {
    width: 0.4rem;
    height: 0.4rem;
    border: solid var(--ink-faint);
    border-width: 0 1.5px 1.5px 0;
    transform: rotate(-45deg);
    transition: transform 180ms var(--ease-out);
  }

  .caret.open {
    transform: rotate(45deg) translate(-1px, -1px);
  }

  .project-name {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-size: var(--step-0);
    font-weight: 650;
    letter-spacing: -0.01em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .count {
    color: var(--ink-faint);
    font-size: var(--step--1);
    font-variant-numeric: tabular-nums;
  }

  .sessions {
    margin: 0;
    padding: 0 0 0 1.55rem;
    list-style: none;
  }

  .sessions.flat {
    padding-left: var(--space-2);
  }

  .leaf {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
    height: 1.75rem;
    padding-right: var(--space-2);
    border-left: 2px solid transparent;
  }

  .leaf.current {
    background: var(--paper);
    border-left-color: var(--ink);
  }

  .pick {
    flex: 1;
    min-width: 0;
    height: 100%;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0 0 0 var(--space-2);
    background: none;
    border: none;
    text-align: left;
    font-size: var(--step--1);
    cursor: pointer;
  }

  .pick:hover .leaf-name {
    text-decoration: underline;
    text-decoration-color: var(--rule-strong);
    text-underline-offset: 3px;
  }

  .leaf-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .leaf-project {
    flex: none;
    color: var(--ink-faint);
    font-size: 0.68rem;
  }

  .current .leaf-name {
    font-weight: 650;
  }

  .refs {
    flex: none;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--ink-soft);
  }

  .refs a {
    color: inherit;
    text-decoration: none;
    border-bottom: 1px solid var(--rule-strong);
  }

  .refs a:hover {
    color: var(--ink);
    border-bottom-color: var(--ink);
  }

  .pin {
    width: 1rem;
    padding: 0;
    background: none;
    border: none;
    color: var(--ink-faint);
    font-size: 0.8rem;
    line-height: 1;
    cursor: pointer;
    opacity: 0;
    transition: opacity 140ms var(--ease-out);
  }

  .leaf:hover .pin,
  .pin:focus-visible,
  .pinned .pin {
    opacity: 1;
  }

  .pinned .pin {
    color: var(--amber-ink);
  }

  @media (hover: none) {
    .pin {
      opacity: 1;
    }
  }

  .none {
    padding: var(--space-4);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
