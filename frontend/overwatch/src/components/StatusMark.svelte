<script lang="ts">
  import type { Mark } from "../lib/tree";

  interface Props {
    mark: Mark;
  }

  let { mark }: Props = $props();

  const LABELS: Record<Mark, string> = {
    blocked: "needs you",
    working: "working",
    done: "done",
    idle: "idle",
  };
</script>

<span class="mark {mark}" role="img" aria-label={LABELS[mark]} title={LABELS[mark]}></span>

<style>
  .mark {
    position: relative;
    display: inline-block;
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
  }

  .blocked::before {
    content: "";
    position: absolute;
    inset: 0.08rem;
    background: var(--amber);
    transform: rotate(45deg);
    border-radius: 1px;
    animation: beckon 1.8s var(--ease-out) infinite;
  }

  .working::before {
    content: "";
    position: absolute;
    inset: 0.05rem;
    border-radius: 50%;
    border: 2px solid color-mix(in oklch, var(--working) 28%, transparent);
    border-top-color: var(--working);
    animation: turn 1.1s linear infinite;
  }

  .done::before {
    content: "";
    position: absolute;
    left: 0.17rem;
    top: 0.04rem;
    width: 0.3rem;
    height: 0.52rem;
    border: solid var(--ink-soft);
    border-width: 0 2px 2px 0;
    transform: rotate(40deg);
  }

  .idle::before {
    content: "";
    position: absolute;
    inset: 0.16rem;
    border-radius: 50%;
    border: 1.5px solid var(--ink-faint);
  }

  @keyframes turn {
    to {
      transform: rotate(1turn);
    }
  }

  @keyframes beckon {
    50% {
      transform: rotate(45deg) scale(0.78);
      opacity: 0.7;
    }
  }
</style>
