<script lang="ts">
  import { ago } from "../../lib/format";
  import type { ArtifactShare, Publisher } from "../../lib/artifact";

  interface Props {
    publishers: Publisher[];
    shares: ArtifactShare[];
    live: boolean;
    busy: string;
    owner: string;
    onshare: (publisher: string) => void;
  }

  let { publishers, shares, live, busy, owner, onshare }: Props = $props();

  function labelOf(id: string): string {
    return publishers.find((publisher) => publisher.id === id)?.label ?? id;
  }

  function safeUrl(url: string): string {
    return /^https?:\/\//i.test(url) ? url : "";
  }
</script>

<details class="share">
  <summary>Share{shares.length ? ` · ${shares.length}` : ""}</summary>
  <div class="menu">
    {#if publishers.length}
      <p class="head">Ask {owner} to publish with</p>
      <ul class="publishers">
        {#each publishers as publisher (publisher.id)}
          <li>
            <button
              type="button"
              disabled={!live || !!busy}
              aria-busy={busy === publisher.id}
              onclick={() => onshare(publisher.id)}
            >
              {busy === publisher.id ? "Asking…" : publisher.label}
            </button>
          </li>
        {/each}
      </ul>
      {#if !live}<p class="off">{owner} is not running, so nobody can publish this now.</p>{/if}
    {:else}
      <p class="off">No publishers are configured.</p>
    {/if}
    {#if shares.length}
      <p class="head">Published</p>
      <ul class="links">
        {#each shares as each, index (index)}
          {@const href = safeUrl(each.url)}
          <li>
            <span class="where">{labelOf(each.publisher)}</span>
            {#if href}
              <a {href} target="_blank" rel="noreferrer">{each.url}</a>
            {:else}
              <span class="url">{each.url}</span>
            {/if}
            {#if each.at}<span class="when">{ago(each.at)}</span>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</details>

<style>
  .share {
    position: relative;
  }

  summary {
    list-style: none;
    padding: var(--space-1) var(--space-3);
    border: 1px solid var(--rule-strong);
    border-radius: 999px;
    font-size: var(--step--1);
    font-weight: 650;
    cursor: pointer;
    user-select: none;
  }

  summary::-webkit-details-marker {
    display: none;
  }

  .share[open] summary {
    border-color: var(--ink);
  }

  .menu {
    position: absolute;
    right: 0;
    top: calc(100% + var(--space-1));
    z-index: 5;
    width: min(22rem, 80vw);
    padding: var(--space-3);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    box-shadow: 0 8px 24px color-mix(in oklch, var(--ink) 14%, transparent);
    display: grid;
    gap: var(--space-2);
  }

  .head {
    margin: 0;
    color: var(--ink-faint);
    font-size: 0.68rem;
    font-weight: 650;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  .publishers,
  .links {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    gap: var(--space-1);
  }

  .publishers button {
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: var(--paper);
    border: 1px solid var(--rule-strong);
    border-radius: 3px;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }

  .publishers button:hover:not(:disabled) {
    border-color: var(--ink);
  }

  .publishers button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .off {
    margin: 0;
    color: var(--ink-soft);
    font-size: var(--step--1);
  }

  .links li {
    display: grid;
    gap: 0.1rem;
    font-size: var(--step--1);
  }

  .where {
    font-weight: 650;
  }

  .links a,
  .url {
    color: var(--ink-soft);
    overflow-wrap: anywhere;
  }

  .when {
    color: var(--ink-faint);
    font-size: 0.7rem;
  }
</style>
