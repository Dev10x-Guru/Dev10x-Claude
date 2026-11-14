<script lang="ts">
  import type { ControlStatus } from "../../lib/artifact-host";

  let { status }: { status: ControlStatus } = $props();
</script>

{#if status.note}
  <p class={["note", `note-${status.state}`]} role={status.state === "error" ? "alert" : "status"}>
    {status.note}
  </p>
{/if}

<style>
  .note {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .note-pending {
    color: var(--amber-ink);
  }

  .note-error {
    color: var(--danger);
  }
</style>
