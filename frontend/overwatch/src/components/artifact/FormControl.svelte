<script lang="ts">
  import ControlNote from "./ControlNote.svelte";
  import type { FormBlock } from "../../lib/artifact";
  import { getControlHost } from "../../lib/artifact-host";

  let { block }: { block: FormBlock } = $props();

  const host = getControlHost();
  const status = $derived(host.status(block.id));
  const usable = $derived(status.state === "ready" || status.state === "error");

  let values = $state<Record<string, string>>({});

  function valueOf(name: string, fallback: string): string {
    return values[name] ?? fallback;
  }

  function submit(event: SubmitEvent): void {
    event.preventDefault();
    const filled = Object.fromEntries(
      block.fields.map((field) => [
        field.name,
        valueOf(field.name, field.kind === "select" ? (field.options?.[0] ?? "") : ""),
      ]),
    );
    host.send(block, filled);
  }
</script>

<form class="control" onsubmit={submit} aria-busy={status.state === "sending"}>
  <fieldset disabled={!usable}>
    <legend>{block.label}</legend>
    {#each block.fields as field (field.name)}
      <label class="field">
        <span class="field-label">{field.label}</span>
        {#if field.kind === "textarea"}
          <textarea
            rows="4"
            value={valueOf(field.name, "")}
            oninput={(event) => (values[field.name] = event.currentTarget.value)}
          ></textarea>
        {:else if field.kind === "select"}
          <select
            value={valueOf(field.name, field.options?.[0] ?? "")}
            onchange={(event) => (values[field.name] = event.currentTarget.value)}
          >
            {#each field.options ?? [] as option, index (index)}
              <option value={option}>{option}</option>
            {/each}
          </select>
        {:else}
          <input
            type="text"
            value={valueOf(field.name, "")}
            oninput={(event) => (values[field.name] = event.currentTarget.value)}
          />
        {/if}
      </label>
    {/each}
    <button type="submit" class="send">{block.submit || "Send"}</button>
  </fieldset>
  <ControlNote {status} />
</form>

<style>
  .control {
    display: grid;
    gap: var(--space-2);
    max-width: 60ch;
  }

  fieldset {
    margin: 0;
    padding: var(--space-3) var(--space-4) var(--space-4);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    display: grid;
    gap: var(--space-3);
    min-width: 0;
  }

  legend {
    padding: 0 var(--space-1);
    font-weight: 650;
  }

  .field {
    display: grid;
    gap: var(--space-1);
  }

  .field-label {
    color: var(--ink-soft);
    font-size: var(--step--1);
    font-weight: 600;
  }

  input,
  textarea,
  select {
    width: 100%;
    padding: var(--space-2);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    font: inherit;
    color: inherit;
  }

  textarea {
    resize: vertical;
  }

  input:focus-visible,
  textarea:focus-visible,
  select:focus-visible {
    outline: none;
    border-color: var(--focus);
  }

  .send {
    justify-self: start;
    padding: var(--space-2) var(--space-4);
    background: var(--ink);
    border: 1px solid var(--ink);
    border-radius: 3px;
    color: var(--paper);
    font-weight: 650;
    cursor: pointer;
  }

  fieldset:disabled {
    opacity: 0.6;
  }

  fieldset:disabled .send {
    cursor: not-allowed;
  }
</style>
