<script lang="ts">
  import AnswerDock from "./AnswerDock.svelte";
  import Conversation from "./Conversation.svelte";
  import StatusBar from "./StatusBar.svelte";
  import StatusMark from "./StatusMark.svelte";
  import { displayName, shortPath } from "../lib/format";
  import { statusLinks } from "../lib/links";
  import { SESSION_MIME, carriesSession, droppedPeer } from "../lib/drag";
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
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
    nameOf: (sessionId: string) => string;
  }

  let { session, conversation, tail, view, onview, pending, run, nameOf }: Props = $props();

  const NAME_PATTERN = "[A-Za-z0-9][A-Za-z0-9._\\-]{0,63}";
  const COMMANDS = [
    ["reflect", "Reflect", "/my:reflect"],
    ["wrap-up", "Wrap up", "/dev10x:session-wrap-up"],
  ] as const;

  let dropping = $state(false);
  let peer = $state("");
  let renaming = $state(false);
  let newName = $state("");

  async function saveName(): Promise<void> {
    const name = newName.trim();
    renaming = false;
    await run("/rename", { session_id: session.session_id, name }, `Sent /rename ${name} to ${session.name}`);
  }

  function ondragover(event: DragEvent): void {
    if (!carriesSession(event.dataTransfer?.types)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "link";
    dropping = true;
  }

  function ondragleave(event: DragEvent): void {
    const into = event.relatedTarget as Node | null;
    if (!into || !(event.currentTarget as HTMLElement).contains(into)) dropping = false;
  }

  function ondrop(event: DragEvent): void {
    dropping = false;
    if (!carriesSession(event.dataTransfer?.types)) return;
    event.preventDefault();
    peer = droppedPeer(event.dataTransfer?.getData(SESSION_MIME) ?? "", session.session_id);
  }

  async function introducePeer(): Promise<void> {
    const peerId = peer;
    peer = "";
    await run(
      "/introduce",
      { session_id: session.session_id, peer_id: peerId },
      `Introduced ${displayName(session)} and ${nameOf(peerId)} to each other through the relay`,
    );
  }

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

<section
  class={["pane", { dropping }]}
  aria-label={displayName(session)}
  {ondragover}
  {ondragleave}
  {ondrop}
>
  <header class="head">
    <div class="title">
      <StatusMark mark={markOf(session)} />
      {#if renaming}
        <form
          class="rename"
          onsubmit={(event) => {
            event.preventDefault();
            saveName();
          }}
        >
          <label class="visually-hidden" for="rename-input">New name for {session.name}</label>
          <input
            id="rename-input"
            bind:value={newName}
            pattern={NAME_PATTERN}
            maxlength="64"
            autocomplete="off"
            onkeydown={(event) => event.key === "Escape" && (renaming = false)}
            {@attach (node) => node.focus()}
          />
          <button type="submit" disabled={pending || !newName.trim() || newName.trim() === session.name}
            >Rename</button
          >
          <button type="button" class="ghost" onclick={() => (renaming = false)}>Cancel</button>
        </form>
      {:else}
        <h1 title={session.name}>{displayName(session)}</h1>
        {#if session.callsign}<span class="alias">{session.name}</span>{/if}
        <button
          class="ghost rename-open"
          title={session.status === "idle" ? "Rename this session" : "Rename once the session is idle"}
          disabled={session.status !== "idle" || !session.pane_id}
          onclick={() => {
            newName = session.name;
            renaming = true;
          }}>Rename</button
        >
        {#each COMMANDS as [command, label, sent] (command)}
          <button
            class="ghost"
            title={session.status === "idle" ? `Send ${sent} to this session` : `${label} once the session is idle`}
            disabled={pending || session.status !== "idle" || !session.pane_id}
            onclick={() =>
              run("/command", { session_id: session.session_id, command }, `Sent ${sent} to ${session.name}`)}
            >{label}</button
          >
        {/each}
      {/if}
    </div>
    <p class="where">
      <span title={session.cwd}>{shortPath(session.cwd)}</span>
      {#if session.workspace.branch}<span class="branch">{session.workspace.branch}</span>{/if}
    </p>
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

  {#if peer}
    <section class="introduce" aria-label="Introduce two sessions">
      <p>
        Introduce <strong>{displayName(session)}</strong> and <strong>{nameOf(peer)}</strong>? Each gets
        a message about the other to swap what they are changing, tips and gotchas. Neither leads.
      </p>
      <div class="actions">
        <button class="go" disabled={pending} onclick={introducePeer}>Introduce</button>
        <button class="cancel" onclick={() => (peer = "")}>Cancel</button>
      </div>
    </section>
  {:else if waiting}
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

  {#if session.status_line_ansi}
    <footer class="status">
      <StatusBar ansi={session.status_line_ansi} links={statusLinks(session.workspace)} />
    </footer>
  {/if}
</section>

<style>
  .pane {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto auto auto;
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

  .ghost {
    padding: 0;
    background: none;
    border: none;
    color: var(--ink-soft);
    font-size: var(--step--1);
    font-weight: 600;
    text-decoration: underline;
    text-decoration-color: var(--rule-strong);
    text-underline-offset: 3px;
    cursor: pointer;
  }

  .ghost:disabled {
    color: var(--ink-faint);
    text-decoration: none;
    cursor: default;
  }

  .rename-open {
    margin-left: auto;
  }

  .rename {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
  }

  .rename input {
    flex: 1;
    min-width: 0;
    max-width: 28rem;
    padding: var(--space-1) 0;
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--focus);
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 700;
  }

  .rename input:focus-visible {
    outline: none;
  }

  .rename input:invalid {
    border-bottom-color: var(--danger);
  }

  .rename button[type="submit"] {
    padding: var(--space-1) var(--space-3);
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    font-weight: 650;
    cursor: pointer;
  }

  .rename button[type="submit"]:disabled {
    opacity: 0.35;
    cursor: default;
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

  .status {
    padding: 0 var(--space-6) var(--space-3);
    background: var(--paper);
  }

  .pane.dropping {
    outline: 2px dashed var(--focus);
    outline-offset: -6px;
  }

  .introduce {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
    padding: var(--space-3) var(--space-6);
    background: color-mix(in oklch, var(--focus) 10%, var(--paper));
    border-top: 1px solid var(--focus);
  }

  .introduce p {
    margin: 0;
    max-width: 60ch;
  }

  .actions {
    display: flex;
    gap: var(--space-3);
  }

  .introduce .go {
    padding: var(--space-2) var(--space-4);
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    font-weight: 650;
    cursor: pointer;
  }

  .introduce .cancel {
    padding: var(--space-2) 0;
    background: none;
    border: none;
    color: var(--ink-soft);
    font-weight: 600;
    cursor: pointer;
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
