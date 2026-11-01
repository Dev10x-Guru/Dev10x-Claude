<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    on: boolean;
    onchange: (on: boolean) => void;
    children: Snippet;
  }

  let { on, onchange, children }: Props = $props();
</script>

<button type="button" class="toggle" role="switch" aria-checked={on} onclick={() => onchange(!on)}>
  <span class={["track", { on }]} aria-hidden="true"><span class="knob"></span></span>
  <span class="label">{@render children()}</span>
</button>

<style>
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0;
    background: none;
    border: none;
    color: var(--ink-soft);
    font-size: 0.74rem;
    text-align: left;
    cursor: pointer;
  }

  .track {
    position: relative;
    flex: none;
    width: 1.75rem;
    height: 1rem;
    border-radius: 999px;
    background: var(--rule-strong);
    transition: background 160ms var(--ease-out);
  }

  .knob {
    position: absolute;
    top: 0.125rem;
    left: 0.125rem;
    width: 0.75rem;
    height: 0.75rem;
    border-radius: 50%;
    background: var(--paper);
    box-shadow: 0 1px 2px color-mix(in oklch, var(--ink) 30%, transparent);
    transition: transform 160ms var(--ease-out);
  }

  .track.on {
    background: var(--amber-ink);
  }

  .track.on .knob {
    transform: translateX(0.75rem);
  }

  .toggle:hover .label {
    color: var(--ink);
  }
</style>
