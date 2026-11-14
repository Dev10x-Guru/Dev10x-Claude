<script lang="ts">
  import { untrack } from "svelte";

  import {
    emptyForm,
    eventBody,
    missingRequired,
    toggleOption,
    toneClass,
    type ControlValue,
  } from "../lib/artifacts";
  import type { ArtifactControl, ArtifactDocument } from "../lib/types";

  interface Props {
    control: ArtifactControl;
    document: ArtifactDocument;
    pending: boolean;
    run: (path: string, body: Record<string, unknown>, what: string) => Promise<boolean>;
  }

  let { control, document, pending, run }: Props = $props();

  let picked = $state<string[]>([]);
  let values = $state<Record<string, string>>(untrack(() => (control.type === "form" ? emptyForm(control.fields) : {})));
  let sentAt = $state<string | null>(null);

  const missing = $derived(control.type === "form" ? missingRequired(control.fields, values) : []);

  async function send(value: ControlValue): Promise<void> {
    const ok = await run("/api/artifact/event", eventBody(document, control.id, value), "Sent to the session");
    if (ok) sentAt = new Date().toLocaleTimeString();
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    if (control.type === "form" && !missing.length) send({ ...values });
  }
</script>

<div class="control">
  {#if control.type === "button"}
    <button type="button" class={["act", toneClass(control.tone)]} disabled={pending} onclick={() => send(null)}>
      {control.label}
    </button>
  {:else if control.type === "choice"}
    <fieldset>
      <legend>{control.prompt}</legend>
      <div class="options">
        {#each control.options as option (option)}
          {#if control.multiple}
            <button
              type="button"
              class={["opt", { on: picked.includes(option) }]}
              aria-pressed={picked.includes(option)}
              disabled={pending}
              onclick={() => (picked = toggleOption(picked, option, control.options))}
            >
              {option}
            </button>
          {:else}
            <button type="button" class="opt" disabled={pending} onclick={() => send(option)}>{option}</button>
          {/if}
        {/each}
      </div>
      {#if control.multiple}
        <button type="button" class="act" disabled={pending || !picked.length} onclick={() => send([...picked])}>
          Send {picked.length || ""}
        </button>
      {/if}
    </fieldset>
  {:else if control.type === "form"}
    <form onsubmit={submit}>
      {#if control.title}<p class="legend">{control.title}</p>{/if}
      {#each control.fields as field (field.name)}
        <label>
          <span>{field.label}{field.required ? " *" : ""}</span>
          {#if field.kind === "textarea"}
            <textarea rows="4" bind:value={values[field.name]}></textarea>
          {:else}
            <input type="text" bind:value={values[field.name]} />
          {/if}
        </label>
      {/each}
      <button type="submit" class="act" disabled={pending || missing.length > 0}>
        {control.submit || "Send"}
      </button>
    </form>
  {/if}
  {#if sentAt}
    <p class="sent" role="status">Sent at {sentAt}. The session answers by updating this page.</p>
  {/if}
</div>

<style>
  .control {
    display: grid;
    gap: var(--space-2);
  }

  fieldset {
    margin: 0;
    padding: 0;
    border: none;
  }

  legend,
  .legend {
    margin: 0 0 var(--space-2);
    font-weight: 650;
  }

  .options {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }

  form {
    display: grid;
    gap: var(--space-3);
    max-width: 40rem;
  }

  label {
    display: grid;
    gap: var(--space-1);
    font-size: var(--step--1);
    color: var(--ink-soft);
  }

  input,
  textarea {
    font: inherit;
    color: var(--ink);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    padding: var(--space-2);
  }

  .act,
  .opt {
    justify-self: start;
    padding: var(--space-2) var(--space-4);
    font: inherit;
    font-weight: 600;
    color: var(--ink);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    cursor: pointer;
  }

  .act {
    background: var(--amber-wash);
    border-color: var(--amber);
  }

  .opt.on {
    background: var(--amber-wash);
    border-color: var(--amber);
  }

  .tone-ok {
    border-color: var(--working);
  }

  .tone-bad {
    border-color: var(--danger);
    color: var(--danger);
  }

  button:disabled {
    cursor: default;
    opacity: 0.55;
  }

  button:focus-visible,
  input:focus-visible,
  textarea:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
  }

  .sent {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }
</style>
