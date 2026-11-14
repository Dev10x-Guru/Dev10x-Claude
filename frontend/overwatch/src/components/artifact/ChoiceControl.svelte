<script lang="ts">
  import ControlNote from "./ControlNote.svelte";
  import type { ChoiceBlock } from "../../lib/artifact";
  import { getControlHost } from "../../lib/artifact-host";

  let { block }: { block: ChoiceBlock } = $props();

  const host = getControlHost();
  const status = $derived(host.status(block.id));
  const usable = $derived(status.state === "ready" || status.state === "error");

  let picked = $state<string[]>([]);
</script>

<fieldset class="control" disabled={!usable} aria-busy={status.state === "sending"}>
  <legend>{block.label}</legend>
  {#if block.multi}
    <ul class="checks">
      {#each block.options as option, index (index)}
        <li>
          <label class="check">
            <input type="checkbox" value={option} bind:group={picked} />
            <span>{option}</span>
          </label>
        </li>
      {/each}
    </ul>
    <button type="button" class="send" disabled={!picked.length} onclick={() => host.send(block, [...picked])}>
      {picked.length ? `Send ${picked.length} selected` : "Pick at least one"}
    </button>
  {:else}
    <ul class="options">
      {#each block.options as option, index (index)}
        <li>
          <button type="button" class="option" onclick={() => host.send(block, option)}>{option}</button>
        </li>
      {/each}
    </ul>
  {/if}
  <ControlNote {status} />
</fieldset>

<style>
  .control {
    margin: 0;
    padding: 0;
    border: none;
    display: grid;
    justify-items: start;
    gap: var(--space-2);
    min-width: 0;
  }

  legend {
    padding: 0;
    margin-bottom: var(--space-2);
    font-weight: 650;
    overflow-wrap: anywhere;
  }

  .options,
  .checks {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .checks {
    display: grid;
    gap: var(--space-1);
  }

  .option,
  .send {
    padding: var(--space-2) var(--space-3);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    font-weight: 600;
    text-align: left;
    overflow-wrap: anywhere;
    cursor: pointer;
    transition: border-color 160ms var(--ease-out);
  }

  .option:hover:not(:disabled),
  .send:hover:not(:disabled) {
    border-color: var(--ink);
  }

  .send {
    background: var(--ink);
    border-color: var(--ink);
    color: var(--paper);
  }

  .check {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    cursor: pointer;
    overflow-wrap: anywhere;
  }

  .check input {
    accent-color: var(--amber);
    translate: 0 0.12em;
  }

  button:disabled,
  .control:disabled .check {
    cursor: not-allowed;
    opacity: 0.55;
  }
</style>
