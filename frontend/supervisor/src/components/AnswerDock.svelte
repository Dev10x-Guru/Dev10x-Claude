<script lang="ts">
  import { fly } from "svelte/transition";
  import { cubicOut } from "svelte/easing";

  import { displayName, optionText, waitingLabel } from "../lib/format";
  import type { Decision, PromptOption, Session } from "../lib/types";

  interface Props {
    session: Session;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<void>;
  }

  let { session, pending, run }: Props = $props();

  function choose(option: PromptOption): void {
    run(
      "/keys",
      { session_id: session.session_id, key: option.key, label: option.label },
      `Sent “${optionText(option).label}” to ${displayName(session)}`,
    );
  }

  function answer(decision: Decision, index: number): void {
    run(
      "/answer",
      { decision_id: decision.decision_id, option_index: index },
      `Answered “${decision.options[index]}” for ${displayName(session)}`,
    );
  }
</script>

<section class="dock" aria-label="Answer {displayName(session)}" in:fly={{ y: 10, duration: 260, easing: cubicOut }}>
  <p class="waiting"><span aria-hidden="true">◆</span> {waitingLabel(session)}</p>

  {#if session.prompt}
    {#if session.prompt.question}<p class="question">{session.prompt.question}</p>{/if}
    <ol class="options">
      {#each session.prompt.options as option (option.key)}
        {@const text = optionText(option)}
        <li>
          <button class={["option", { recommended: text.recommended }]} disabled={pending} onclick={() => choose(option)}>
            <kbd>{option.key}</kbd>
            <span class="label">{text.label}</span>
            {#if text.recommended}<span class="tag">suggested</span>{/if}
            {#if option.detail}<span class="detail">{option.detail}</span>{/if}
          </button>
        </li>
      {/each}
    </ol>
  {:else if session.decisions.length}
    {#each session.decisions as decision (decision.decision_id)}
      <p class="question">
        {#if decision.header}<span class="header">{decision.header}</span>{/if}
        {decision.question}
      </p>
      {#if decision.multi_select}
        <p class="note">This one takes several picks; answer it in the session's own pane.</p>
      {:else}
        <ol class="options">
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
        </ol>
      {/if}
    {/each}
  {:else}
    <p class="note">{session.summary || "No readable question on screen. Read the tail above, or reply below."}</p>
  {/if}
</section>

<style>
  .dock {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-6) var(--space-4);
    background: var(--amber-wash);
    border-top: 1px solid var(--amber);
    max-height: 45vh;
    overflow-y: auto;
  }

  .waiting {
    margin: 0;
    color: var(--amber-ink);
    font-size: 0.72rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .question {
    margin: 0;
    font-size: var(--step-1);
    line-height: 1.3;
    overflow-wrap: anywhere;
  }

  .header {
    margin-right: var(--space-2);
    color: var(--amber-ink);
    font-weight: 650;
  }

  .options {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 15rem), 1fr));
    gap: var(--space-2);
  }

  .option {
    width: 100%;
    height: 100%;
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: baseline;
    column-gap: var(--space-2);
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
    transform: translateY(-1px);
  }

  .option:disabled {
    cursor: progress;
    opacity: 0.6;
  }

  .option.recommended {
    border-color: var(--amber);
    box-shadow: inset 0 -2px 0 var(--amber);
  }

  kbd {
    min-width: 1.4rem;
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
    font-size: 0.72rem;
    font-weight: 650;
  }

  .detail {
    grid-column: 2 / -1;
    color: var(--ink-soft);
    font-size: var(--step--1);
    overflow-wrap: anywhere;
  }

  .note {
    margin: 0;
    color: var(--ink-soft);
  }
</style>
