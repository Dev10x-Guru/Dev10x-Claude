<script lang="ts">
  import { correction, type Answer } from "../lib/answers";
  import { ago } from "../lib/format";
  import { recent, revise } from "../lib/recent.svelte";

  interface Props {
    pending: boolean;
    live: (sessionId: string) => boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
  }

  let { pending, live, run }: Props = $props();

  let open = $state("");

  async function change(answer: Answer, chosen: string): Promise<void> {
    const sent = await run(
      "/reply",
      { session_id: answer.session_id, text: correction(answer, chosen) },
      `Told ${answer.session_name} you now pick “${chosen}”`,
    );
    if (!sent) return;
    revise(answer.id, chosen);
    open = "";
  }
</script>

<section class="answers">
  <h2>Your last answers</h2>
  {#if recent.answers.length}
    <ol>
      {#each recent.answers as answer (answer.id)}
        {@const reachable = live(answer.session_id)}
        <li class={{ open: open === answer.id }}>
          <button
            class="row"
            aria-expanded={open === answer.id}
            onclick={() => (open = open === answer.id ? "" : answer.id)}
          >
            <span class="question">{answer.question}</span>
            <span class="chosen">{answer.chosen}</span>
            <span class="meta">{answer.session_name} · {ago(answer.at)}</span>
          </button>
          {#if open === answer.id}
            {#if reachable}
              <p class="hint">Pick another option to tell the session you changed your mind.</p>
              <ul class="options">
                {#each answer.options as option (option)}
                  <li>
                    <button
                      class={["option", { current: option === answer.chosen }]}
                      disabled={pending || option === answer.chosen}
                      onclick={() => change(answer, option)}
                    >
                      {option}
                      {#if option === answer.chosen}<span class="tag">your answer</span>{/if}
                    </button>
                  </li>
                {/each}
              </ul>
            {:else}
              <p class="hint">That session is no longer running, so there is no one to tell.</p>
            {/if}
          {/if}
        </li>
      {/each}
    </ol>
  {:else}
    <p class="quiet">Questions you answer from this page land here, the last five, so you can change your mind.</p>
  {/if}
</section>

<style>
  h2 {
    margin: 0 0 var(--space-2);
    font-family: var(--font-display);
    font-size: 0.78rem;
    font-weight: 650;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-soft);
  }

  ol,
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li.open {
    padding-bottom: var(--space-2);
  }

  .row {
    width: 100%;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.1rem var(--space-2);
    padding: var(--space-2) 0;
    background: none;
    border: none;
    border-bottom: 1px solid var(--rule);
    text-align: left;
    font-size: var(--step--1);
    cursor: pointer;
  }

  .row:hover .question {
    text-decoration: underline;
    text-decoration-color: var(--amber);
    text-underline-offset: 3px;
  }

  .question {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .open .question {
    white-space: normal;
    overflow-wrap: anywhere;
  }

  .chosen {
    color: var(--amber-ink);
    font-weight: 650;
  }

  .meta {
    grid-column: 1 / -1;
    color: var(--ink-faint);
    font-size: 0.72rem;
  }

  .hint,
  .quiet {
    margin: var(--space-2) 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .options {
    display: grid;
    gap: var(--space-1);
  }

  .option {
    width: 100%;
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-3);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    text-align: left;
    font-size: var(--step--1);
    font-weight: 600;
    cursor: pointer;
  }

  .option:hover:not(:disabled) {
    border-color: var(--ink);
  }

  .option.current {
    border-color: var(--amber);
    cursor: default;
  }

  .option:disabled:not(.current) {
    cursor: progress;
    opacity: 0.6;
  }

  .tag {
    color: var(--amber-ink);
    font-size: 0.7rem;
  }
</style>
