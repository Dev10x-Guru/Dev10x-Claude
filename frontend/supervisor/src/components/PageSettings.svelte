<script lang="ts">
  import type { PageSettings } from "../lib/types";

  interface Props {
    settings: PageSettings;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
  }

  let { settings, pending, run }: Props = $props();

  const MAX_WAIT = 540;

  let draft = $state<number | null>(null);
  const wait = $derived(draft ?? settings.answer_wait_seconds);
  const changed = $derived(draft !== null && draft !== settings.answer_wait_seconds);

  async function save(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    const seconds = Math.round(Math.min(MAX_WAIT, Math.max(0, wait)));
    const what = seconds ? `Questions now wait ${seconds} s for you here` : "Questions now go straight to the terminal";
    if (await run("/settings", { answer_wait_seconds: seconds }, what)) draft = null;
  }
</script>

<details class="settings">
  <summary>
    Questions outside Herdr wait {settings.answer_wait_seconds ? `${settings.answer_wait_seconds} s` : "nowhere"}
  </summary>
  <form onsubmit={save}>
    <label>
      Hold a session's question for your answer here for
      <input
        type="number"
        min="0"
        max={MAX_WAIT}
        step="15"
        value={wait}
        oninput={(event) => (draft = Number(event.currentTarget.value))}
      />
      seconds
    </label>
    <p class="hint">
      Only for sessions outside Herdr, which the page cannot type into. When the time runs out, the question opens in the
      session's terminal. 0 sends it there at once.
    </p>
    <button type="submit" disabled={pending || !changed}>Save</button>
  </form>
</details>

<style>
  .settings {
    margin-top: var(--space-2);
    font-size: 0.74rem;
    color: var(--ink-soft);
  }

  summary {
    cursor: pointer;
    width: fit-content;
  }

  summary:hover {
    color: var(--ink);
  }

  form {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: var(--paper);
    border: 1px solid var(--rule);
    border-radius: 3px;
  }

  label {
    color: var(--ink);
    line-height: 1.6;
  }

  input {
    width: 4.5rem;
    margin: 0 0.25em;
    padding: 0.1rem 0.3rem;
    font: inherit;
    font-variant-numeric: tabular-nums;
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    background: var(--paper);
    color: var(--ink);
  }

  .hint {
    margin: 0;
    line-height: 1.45;
  }

  button {
    justify-self: start;
    padding: 0.2rem 0.75rem;
    font: inherit;
    font-weight: 650;
    border: 1px solid var(--amber);
    border-radius: 3px;
    background: var(--amber-wash);
    color: var(--amber-ink);
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  input:focus-visible,
  button:focus-visible,
  summary:focus-visible {
    outline: 2px solid var(--amber);
    outline-offset: 2px;
  }
</style>
