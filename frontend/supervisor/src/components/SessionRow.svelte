<script lang="ts">
  import { displayName, shortPath } from "../lib/format";
  import type { Session } from "../lib/types";

  interface Props {
    session: Session;
  }

  let { session }: Props = $props();
</script>

<li class={["row", { working: session.group === "working" }]}>
  <span class="mark" aria-hidden="true"></span>
  <span class="name">{displayName(session)}</span>
  <span class="what" title={session.summary || session.cwd}>{session.summary || shortPath(session.cwd)}</span>
</li>

<style>
  .row {
    display: grid;
    grid-template-columns: 0.5rem minmax(8rem, 14rem) 1fr;
    align-items: baseline;
    gap: var(--space-3);
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--rule);
    font-size: var(--step--1);
  }

  .mark {
    width: 0.4rem;
    height: 0.4rem;
    border-radius: 50%;
    background: var(--rule-strong);
    align-self: center;
  }

  .working .mark {
    background: var(--working);
    animation: pulse 2.4s var(--ease-out) infinite;
  }

  .name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .what {
    color: var(--ink-soft);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @keyframes pulse {
    50% {
      opacity: 0.35;
    }
  }
</style>
