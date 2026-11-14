<script lang="ts">
  import Pill from "./Pill.svelte";
  import { cellText, type TableBlock } from "../../lib/artifact";

  let { block }: { block: TableBlock } = $props();
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex (a scrolling region must be reachable by keyboard) -->
<div class="wrap" role="region" aria-label="Table" tabindex="0">
  <table>
    <thead>
      <tr>
        {#each block.columns as column, index (index)}
          <th scope="col">{column}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each block.rows as row, rowIndex (rowIndex)}
        <tr>
          {#each row as raw, cellIndex (cellIndex)}
            {@const cell = cellText(raw)}
            <td>
              {#if cell.tone}
                <Pill text={cell.text} tone={cell.tone} />
              {:else}
                {cell.text}
              {/if}
            </td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .wrap {
    max-width: 100%;
    overflow-x: auto;
    border: 1px solid var(--rule);
    border-radius: 3px;
    scrollbar-width: thin;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--step--1);
    font-variant-numeric: tabular-nums;
  }

  th,
  td {
    padding: var(--space-2) var(--space-3);
    text-align: left;
    vertical-align: top;
    border-bottom: 1px solid var(--rule);
  }

  th {
    position: sticky;
    top: 0;
    background: var(--paper-sunk);
    color: var(--ink-soft);
    font-size: 0.7rem;
    font-weight: 650;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
  }

  td {
    min-width: 6rem;
    max-width: 40ch;
    white-space: pre-line;
    overflow-wrap: anywhere;
  }

  tbody tr:last-child td {
    border-bottom: none;
  }

  tbody tr:hover td {
    background: color-mix(in oklch, var(--paper-sunk) 60%, transparent);
  }
</style>
