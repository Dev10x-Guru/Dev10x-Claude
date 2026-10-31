<script lang="ts">
  import StatusMark from "./StatusMark.svelte";
  import { displayName } from "../lib/format";
  import { buildTree, folderLabel, markOf, matches } from "../lib/tree";
  import type { Session } from "../lib/types";

  interface Props {
    sessions: Session[];
    selected: string;
    onselect: (sessionId: string) => void;
  }

  let { sessions, selected, onselect }: Props = $props();

  let query = $state("");
  let collapsed = $state<Record<string, boolean>>({});

  const tree = $derived(buildTree(sessions.filter((session) => matches(session, query))));

  function toggle(name: string): void {
    collapsed = { ...collapsed, [name]: !collapsed[name] };
  }
</script>

<nav class="index" aria-label="Sessions">
  <label class="search">
    <span class="visually-hidden">Filter sessions</span>
    <input bind:value={query} type="search" placeholder="Filter by name, branch, issue" autocomplete="off" />
  </label>

  <ul class="projects">
    {#each tree as project (project.name)}
      {@const open = !collapsed[project.name] || !!query}
      <li class="project">
        <button class="project-head" aria-expanded={open} onclick={() => toggle(project.name)}>
          <span class={["caret", { open }]} aria-hidden="true"></span>
          <StatusMark mark={project.mark} />
          <span class="project-name">{project.name}</span>
          <span class="count">{project.count}</span>
        </button>

        {#if open}
          {#each project.folders as folder (folder.root)}
            <ul class="sessions">
              {#if project.folders.length > 1 || folder.sessions.length > 1}
                <li class="folder" title={folder.root}>{folderLabel(folder.root, project.name)}</li>
              {/if}
              {#each folder.sessions as session (session.session_id)}
                {@const ws = session.workspace}
                <li>
                  <div class={["leaf", { current: session.session_id === selected }]}>
                    <button
                      class="pick"
                      aria-current={session.session_id === selected ? "true" : undefined}
                      onclick={() => onselect(session.session_id)}
                    >
                      <StatusMark mark={markOf(session)} />
                      <span class="leaf-name">{displayName(session)}</span>
                    </button>
                    {#if ws.issue || ws.pr}
                      <span class="refs">
                        {#if ws.issue}
                          {#if ws.issue_url}
                            <a href={ws.issue_url} target="_blank" rel="noreferrer">{ws.issue}</a>
                          {:else}
                            <span>{ws.issue}</span>
                          {/if}
                        {/if}
                        {#if ws.pr}
                          {#if ws.pr_url}
                            <a href={ws.pr_url} target="_blank" rel="noreferrer">PR {ws.pr}</a>
                          {:else}
                            <span>PR {ws.pr}</span>
                          {/if}
                        {/if}
                      </span>
                    {/if}
                  </div>
                </li>
              {/each}
            </ul>
          {/each}
        {/if}
      </li>
    {:else}
      <li class="none">{query ? "No session matches that filter." : "No sessions yet."}</li>
    {/each}
  </ul>
</nav>

<style>
  .index {
    display: flex;
    flex-direction: column;
    min-height: 0;
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

  .search input:focus-visible {
    outline: none;
    border-bottom-color: var(--focus);
  }

  .projects {
    flex: 1;
    min-height: 0;
    margin: 0;
    padding: 0 0 var(--space-8);
    overflow-y: auto;
    list-style: none;
    scrollbar-width: thin;
  }

  .project + .project {
    margin-top: var(--space-1);
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

  .folder {
    padding: var(--space-1) var(--space-4) 0 var(--space-2);
    color: var(--ink-faint);
    font-size: 0.7rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .leaf {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    padding-right: var(--space-3);
    border-left: 2px solid transparent;
  }

  .leaf.current {
    background: var(--paper);
    border-left-color: var(--ink);
  }

  .pick {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0.3rem 0 0.3rem var(--space-2);
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
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .current .leaf-name {
    font-weight: 650;
  }

  .refs {
    flex: none;
    display: flex;
    gap: var(--space-2);
    font-size: 0.7rem;
    font-variant-numeric: tabular-nums;
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
