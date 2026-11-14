<script lang="ts">
  import ButtonControl from "./ButtonControl.svelte";
  import ChoiceControl from "./ChoiceControl.svelte";
  import FormControl from "./FormControl.svelte";
  import type { ControlBlock } from "../../lib/artifact";

  let { block }: { block: ControlBlock } = $props();
</script>

{#if block.type === "button"}
  <ButtonControl {block} />
{:else if block.type === "choice"}
  <ChoiceControl {block} />
{:else}
  <FormControl {block} />
{/if}
