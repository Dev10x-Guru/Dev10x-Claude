<script lang="ts">
  import ControlNote from "./ControlNote.svelte";
  import type { ButtonBlock } from "../../lib/artifact";
  import { getControlHost } from "../../lib/artifact-host";

  let { block }: { block: ButtonBlock } = $props();

  const host = getControlHost();
  const status = $derived(host.status(block.id));
  const usable = $derived(status.state === "ready" || status.state === "error");
</script>

<div class="control">
  <button
    type="button"
    class={["act", `tone-${block.tone ?? "default"}`, { sent: status.state === "pending" }]}
    disabled={!usable}
    aria-busy={status.state === "sending"}
    onclick={() => host.send(block, block.value ?? block.label)}
  >
    {#if status.state === "pending"}<span aria-hidden="true">✓</span>{/if}
    {block.label}
  </button>
  <ControlNote {status} />
</div>

<style>
  .control {
    display: grid;
    justify-items: start;
    gap: var(--space-1);
  }

  .act {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    font-weight: 650;
    cursor: pointer;
    transition:
      border-color 160ms var(--ease-out),
      transform 160ms var(--ease-out);
  }

  .act:hover:not(:disabled) {
    border-color: var(--ink);
    transform: translateY(-1px);
  }

  .tone-primary {
    background: var(--ink);
    border-color: var(--ink);
    color: var(--paper);
  }

  .tone-primary:hover:not(:disabled) {
    border-color: var(--amber);
    box-shadow: inset 0 -2px 0 var(--amber);
  }

  .tone-danger {
    border-color: var(--danger);
    color: var(--danger);
  }

  .act:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .act.sent {
    opacity: 1;
    border-color: var(--amber);
    background: var(--amber-wash);
    color: var(--amber-ink);
  }

  @media (prefers-reduced-motion: reduce) {
    .act:hover:not(:disabled) {
      transform: none;
    }
  }
</style>
