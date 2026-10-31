<script lang="ts">
  import AnswerDock from "./AnswerDock.svelte";
  import Conversation from "./Conversation.svelte";
  import StatusBar from "./StatusBar.svelte";
  import StatusMark from "./StatusMark.svelte";
  import { displayName, shortPath } from "../lib/format";
  import { pinned } from "../lib/tail";
  import { markOf } from "../lib/tree";
  import type { ConversationEntry, Session, View } from "../lib/types";

  interface Props {
    session: Session;
    conversation: ConversationEntry[] | null;
    tail: string;
    view: View;
    onview: (view: View) => void;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<void>;
  }

  let { session, conversation, tail, view, onview, pending, run }: Props = $props();

  const FOLLOW_SLACK_PX = 32;

  let following = $state(true);
  let reply = $state("");

  const text = $derived(tail || session.excerpt);
  const waiting = $derived(session.group === "needs-you");
  const content = $derived(
    view === "screen" ? text : `${conversation?.length ?? 0}:${conversation?.at(-1)?.outcome ?? ""}`,
  );

  function onscroll(event: Event): void {
    const node = event.currentTarget as HTMLElement;
    following = node.scrollHeight - node.scrollTop - node.clientHeight < FOLLOW_SLACK_PX;
  }

  async function send(): Promise<void> {
    const message = reply.trim();
    if (!message || pending) return;
    await run("/reply", { session_id: session.session_id, text: message }, `Relayed your reply to ${displayName(session)}`);
    reply = "";
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  }
</script>

<section class="pane" aria-label={displayName(session)}>
  <header class="head">
    <div class="title">
      <StatusMark mark={markOf(session)} />
      <h1>{displayName(session)}</h1>
      {#if session.callsign}<span class="alias">{session.name}</span>{/if}
    </div>
    <p class="where">
      <span title={session.cwd}>{shortPath(session.cwd)}</span>
      {#if session.workspace.branch}<span class="branch">{session.workspace.branch}</span>{/if}
    </p>
    {#if session.status_line_ansi}
      <StatusBar ansi={session.status_line_ansi} />
    {/if}
  </header>

  <div class="well">
    <div class="views" role="tablist" aria-label="What to show">
      {#each [["transcript", "Transcript"], ["screen", "Screen"]] as [key, label] (key)}
        <button
          role="tab"
          aria-selected={view === key}
          class={{ on: view === key }}
          onclick={() => {
            following = true;
            onview(key as View);
          }}>{label}</button
        >
      {/each}
    </div>
    <div class="scroll" {onscroll} {@attach pinned(content, following)}>
      {#if view === "transcript"}
        {#if conversation}
          <Conversation entries={conversation} />
        {:else}
          <p class="blank">Reading the transcript…</p>
        {/if}
      {:else if text}
        <pre class="screen">{text}</pre>
      {:else}
        <p class="blank">
          {session.pane_id
            ? "Reading the screen…"
            : "This session runs outside Herdr, so there is no screen to read."}
        </p>
      {/if}
    </div>
    {#if !following}
      <button class="jump" onclick={() => (following = true)}>Jump to latest ↓</button>
    {/if}
  </div>

  {#if waiting}
    <AnswerDock {session} {pending} {run} />
  {/if}

  <form
    class="chat"
    onsubmit={(event) => {
      event.preventDefault();
      send();
    }}
  >
    <label class="visually-hidden" for="chat-input">Message {displayName(session)}</label>
    <textarea
      id="chat-input"
      bind:value={reply}
      {onkeydown}
      rows="2"
      placeholder="Message {displayName(session)}. Enter sends through the relay, Shift+Enter adds a line."
      disabled={pending}
    ></textarea>
    <button type="submit" disabled={pending || !reply.trim()}>Send</button>
  </form>
</section>

<style>
  .pane {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto auto;
    min-height: 0;
    height: 100%;
    min-width: 0;
  }

  .head {
    padding: var(--space-4) var(--space-6) var(--space-3);
    border-bottom: 1px solid var(--rule);
  }

  .title {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
  }

  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 700;
    letter-spacing: -0.015em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .alias {
    color: var(--ink-faint);
    font-size: var(--step--1);
  }

  .where {
    margin: var(--space-1) 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .branch {
    font-family: var(--font-term);
    font-size: 0.76rem;
  }

  .head :global(.bar) {
    margin-top: var(--space-2);
  }

  .well {
    position: relative;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    min-height: 0;
    background: var(--term);
  }

  .views {
    display: flex;
    gap: var(--space-4);
    padding: var(--space-2) var(--space-6) 0;
    border-bottom: 1px solid var(--term-rule);
  }

  .views button {
    padding: var(--space-1) 0 var(--space-2);
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--term-faint);
    font-size: var(--step--1);
    font-weight: 600;
    cursor: pointer;
  }

  .views button.on {
    color: var(--term-ink);
    border-bottom-color: var(--amber);
  }

  .scroll {
    min-height: 0;
    overflow: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--term-rule) transparent;
  }

  .screen {
    margin: 0;
    padding: var(--space-4) var(--space-6);
    color: var(--term-ink);
    font-family: var(--font-term);
    font-size: 0.8rem;
    line-height: 1.42;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .blank {
    margin: 0;
    padding: var(--space-8) var(--space-6);
    color: var(--term-faint);
  }

  .jump {
    position: absolute;
    right: var(--space-6);
    bottom: var(--space-4);
    padding: var(--space-1) var(--space-3);
    background: var(--term-ink);
    color: var(--term);
    border: none;
    border-radius: 999px;
    font-size: var(--step--1);
    font-weight: 600;
    cursor: pointer;
    animation: rise 200ms var(--ease-out);
  }

  .chat {
    display: flex;
    align-items: flex-end;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-6) var(--space-4);
    border-top: 1px solid var(--rule-strong);
    background: var(--paper);
  }

  textarea {
    flex: 1;
    min-width: 0;
    max-height: 12rem;
    padding: var(--space-2) 0;
    resize: none;
    field-sizing: content;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--rule-strong);
    line-height: 1.4;
  }

  textarea:focus-visible {
    outline: none;
    border-bottom-color: var(--focus);
  }

  .chat button {
    padding: var(--space-2) var(--space-4);
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    font-weight: 650;
    cursor: pointer;
    transition: opacity 160ms var(--ease-out);
  }

  .chat button:disabled {
    opacity: 0.35;
    cursor: default;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }

  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
  }
</style>
