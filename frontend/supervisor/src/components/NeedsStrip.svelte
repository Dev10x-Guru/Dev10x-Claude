<script lang="ts">
  import { fly } from "svelte/transition";
  import { cubicOut } from "svelte/easing";

  import { post } from "../lib/api";
  import { displayName, optionText, shortPath, waitingLabel } from "../lib/format";
  import type { ActionResult, Decision, PromptOption, Session } from "../lib/types";

  interface Props {
    session: Session;
    token: string;
    onresult: (result: ActionResult, what: string) => void;
  }

  let { session, token, onresult }: Props = $props();

  let pending = $state(false);
  let reply = $state("");

  async function run(path: string, body: Record<string, unknown>, what: string): Promise<void> {
    pending = true;
    const result = await post(path, body, token);
    pending = false;
    onresult(result, what);
  }

  function choose(option: PromptOption): void {
    const { label } = optionText(option);
    run(
      "/keys",
      { session_id: session.session_id, key: option.key, label: option.label },
      `Sent “${label}” to ${displayName(session)}`,
    );
  }

  function answer(decision: Decision, index: number): void {
    run(
      "/answer",
      { decision_id: decision.decision_id, option_index: index },
      `Answered “${decision.options[index]}” for ${displayName(session)}`,
    );
  }

  async function sendReply(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const text = reply.trim();
    if (!text) return;
    await run("/reply", { session_id: session.session_id, text }, `Relayed your reply to ${displayName(session)}`);
    reply = "";
  }
</script>

<article class={["strip", { pending }]} in:fly={{ y: 8, duration: 280, easing: cubicOut }}>
  <header class="ident">
    <p class="waiting"><span class="dot" aria-hidden="true"></span>{waitingLabel(session)}</p>
    <h3>{displayName(session)}</h3>
    {#if session.callsign}<p class="aside">{session.name}</p>{/if}
    <p class="aside" title={session.cwd}>{shortPath(session.cwd)}</p>
  </header>

  <div class="body">
    {#if session.prompt}
      {#if session.prompt.question}<p class="question">{session.prompt.question}</p>{/if}
      <ul class="options">
        {#each session.prompt.options as option (option.key)}
          {@const text = optionText(option)}
          <li>
            <button
              class={["option", { recommended: text.recommended }]}
              disabled={pending}
              onclick={() => choose(option)}
            >
              <kbd>{option.key}</kbd>
              <span class="label">{text.label}</span>
              {#if text.recommended}<span class="tag">suggested</span>{/if}
              {#if option.detail}<span class="detail">{option.detail}</span>{/if}
            </button>
          </li>
        {/each}
      </ul>
    {:else if session.decisions.length}
      {#each session.decisions as decision (decision.decision_id)}
        <section class="decision">
          <p class="question">
            {#if decision.header}<span class="header">{decision.header}</span>{/if}
            {decision.question}
          </p>
          {#if decision.multi_select}
            <p class="note">Pick several in the session itself; the page answers single choices only.</p>
          {:else}
            <ul class="options">
              {#each decision.options as option, index (index)}
                {@const text = optionText({ key: String(index + 1), label: option, detail: "", selected: false })}
                <li>
                  <button
                    class={["option", { recommended: text.recommended }]}
                    disabled={pending}
                    onclick={() => answer(decision, index)}
                  >
                    <kbd>{index + 1}</kbd>
                    <span class="label">{text.label}</span>
                    {#if text.recommended}<span class="tag">suggested</span>{/if}
                  </button>
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/each}
    {:else if session.summary}
      <p class="question">{session.summary}</p>
    {:else}
      <p class="note">Waiting with no readable question. Check the screen below or reply.</p>
    {/if}

    <form class="reply" onsubmit={sendReply}>
      <label class="visually-hidden" for={`reply-${session.session_id}`}>Reply to {displayName(session)}</label>
      <input
        id={`reply-${session.session_id}`}
        bind:value={reply}
        placeholder="Reply in words, sent through the relay"
        autocomplete="off"
        disabled={pending}
      />
      <button type="submit" class="send" disabled={pending || !reply.trim()}>Send</button>
    </form>

    {#if session.excerpt}
      <details>
        <summary>Screen</summary>
        <pre>{session.excerpt}</pre>
      </details>
    {/if}
  </div>
</article>

<style>
  .strip {
    container-type: inline-size;
    display: grid;
    grid-template-columns: minmax(11rem, 15rem) 1fr;
    gap: var(--space-6);
    padding: var(--space-6) var(--space-6) var(--space-6) var(--space-4);
    background: var(--amber-wash);
    border-top: 1px solid var(--rule-strong);
    transition: opacity 200ms var(--ease-out);
  }

  .strip.pending {
    opacity: 0.6;
  }

  @container (max-width: 40rem) {
    .strip {
      grid-template-columns: 1fr;
      gap: var(--space-3);
    }
  }

  .ident h3 {
    margin: var(--space-1) 0 var(--space-1);
    font-family: var(--font-display);
    font-size: var(--step-1);
    font-weight: 650;
    line-height: 1.15;
    overflow-wrap: anywhere;
  }

  .waiting {
    margin: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--amber-ink);
    font-size: var(--step--1);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .dot {
    width: 0.55rem;
    height: 0.55rem;
    border-radius: 50%;
    background: var(--amber);
  }

  .aside {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }

  .body {
    display: grid;
    gap: var(--space-3);
    align-content: start;
    min-width: 0;
  }

  .question {
    margin: 0;
    font-size: var(--step-1);
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  .header {
    margin-right: var(--space-2);
    color: var(--amber-ink);
    font-weight: 600;
  }

  .options {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: var(--space-1);
  }

  .option {
    width: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: baseline;
    column-gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    text-align: left;
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    cursor: pointer;
    transition:
      border-color 160ms var(--ease-out),
      transform 160ms var(--ease-out);
  }

  .option:hover:not(:disabled) {
    border-color: var(--ink);
    transform: translateX(2px);
  }

  .option:disabled {
    cursor: progress;
  }

  .option.recommended {
    border-color: var(--amber);
  }

  kbd {
    min-width: 1.6rem;
    padding: 0 var(--space-1);
    font-family: var(--font-term);
    font-size: var(--step--1);
    text-align: center;
    color: var(--ink-soft);
    border: 1px solid var(--rule-strong);
    border-bottom-width: 2px;
    border-radius: 3px;
  }

  .label {
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  .tag {
    color: var(--amber-ink);
    font-size: var(--step--1);
    font-weight: 600;
  }

  .detail {
    grid-column: 2 / -1;
    color: var(--ink-soft);
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }

  .decision {
    display: grid;
    gap: var(--space-2);
  }

  .note {
    margin: 0;
    color: var(--ink-soft);
  }

  .reply {
    display: flex;
    gap: var(--space-2);
  }

  .reply input {
    flex: 1;
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--rule-strong);
  }

  .reply input:focus-visible {
    outline: none;
    border-bottom-color: var(--focus);
  }

  .send {
    padding: var(--space-2) var(--space-3);
    background: none;
    border: none;
    color: var(--ink);
    font-weight: 600;
    cursor: pointer;
  }

  .send:disabled {
    color: var(--ink-faint);
    cursor: default;
  }

  details summary {
    color: var(--ink-soft);
    font-size: var(--step--1);
    cursor: pointer;
  }

  pre {
    margin: var(--space-2) 0 0;
    padding: var(--space-3);
    max-height: 22rem;
    overflow: auto;
    background: var(--paper-sunk);
    font-family: var(--font-term);
    font-size: 0.78rem;
    line-height: 1.4;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
</style>
