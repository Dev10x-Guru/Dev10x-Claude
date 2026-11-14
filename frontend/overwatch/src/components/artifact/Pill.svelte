<script lang="ts">
  import type { Tone } from "../../lib/artifact";

  interface Props {
    text: string;
    tone?: Tone;
  }

  let { text, tone = "info" }: Props = $props();
</script>

<span class="pill pill-{tone}">{text}</span>

<style>
  .pill {
    --tone: var(--focus);
    display: inline-flex;
    align-items: center;
    gap: 0.35em;
    padding: 0.1rem 0.55rem;
    border: 1px solid color-mix(in oklch, var(--tone) 55%, transparent);
    border-radius: 999px;
    background: color-mix(in oklch, var(--tone) 14%, var(--paper));
    color: var(--ink);
    font-size: 0.74rem;
    font-weight: 600;
    line-height: 1.5;
    white-space: nowrap;
  }

  .pill::before {
    content: "";
    width: 0.42rem;
    height: 0.42rem;
    border-radius: 50%;
    background: var(--tone);
  }

  .pill-ok {
    --tone: var(--working);
  }

  .pill-warn {
    --tone: var(--amber);
  }

  .pill-bad {
    --tone: var(--danger);
  }
</style>
