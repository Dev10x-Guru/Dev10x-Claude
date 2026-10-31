<script lang="ts">
  import { dayKey, inRange, monthGrid, pick, type Range } from "../lib/calendar";

  interface Props {
    range: Range;
    counts: Record<string, number>;
    onchange: (range: Range) => void;
  }

  let { range, counts, onchange }: Props = $props();

  const today = new Date();
  let year = $state(today.getFullYear());
  let month = $state(today.getMonth());

  const weeks = $derived(monthGrid(year, month));
  const title = $derived(new Date(year, month, 1).toLocaleDateString([], { month: "long", year: "numeric" }));
  const todayKey = dayKey(today);

  function step(by: number): void {
    const next = new Date(year, month + by, 1);
    year = next.getFullYear();
    month = next.getMonth();
  }
</script>

<div class="calendar">
  <header>
    <button type="button" aria-label="Previous month" onclick={() => step(-1)}>‹</button>
    <span class="title">{title}</span>
    <button type="button" aria-label="Next month" onclick={() => step(1)}>›</button>
  </header>
  <div class="grid" role="grid" aria-label="Pick a start day, then an end day">
    {#each ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"] as weekday (weekday)}
      <span class="weekday" aria-hidden="true">{weekday}</span>
    {/each}
    {#each weeks as week, row (row)}
      {#each week as day (day.key)}
        {@const picked = range.start !== "" && inRange(day.key, range)}
        <button
          type="button"
          class={[
            "day",
            {
              out: !day.inMonth,
              picked,
              edge: day.key === range.start || day.key === range.end,
              today: day.key === todayKey,
            },
          ]}
          aria-pressed={picked}
          aria-label="{day.key}{counts[day.key] ? `, ${counts[day.key]} sessions` : ''}"
          onclick={() => onchange(pick(range, day.key))}
        >
          {day.day}
          {#if counts[day.key]}<span class="dot" aria-hidden="true"></span>{/if}
        </button>
      {/each}
    {/each}
  </div>
  <p class="range">
    {#if range.start}
      {range.start}{range.end && range.end !== range.start ? ` → ${range.end}` : ""}
      <button type="button" class="clear" onclick={() => onchange({ start: "", end: "" })}>All dates</button>
    {:else}
      All dates · pick a start, then an end
    {/if}
  </p>
</div>

<style>
  .calendar {
    display: grid;
    gap: var(--space-2);
    font-size: var(--step--1);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  header button {
    width: 1.8rem;
    height: 1.8rem;
    background: none;
    border: 1px solid var(--rule);
    border-radius: 3px;
    cursor: pointer;
  }

  .title {
    font-family: var(--font-display);
    font-weight: 650;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(7, 2rem);
    gap: 0.15rem;
  }

  .weekday {
    color: var(--ink-faint);
    font-size: 0.66rem;
    font-weight: 650;
    text-align: center;
  }

  .day {
    position: relative;
    height: 2rem;
    padding: 0;
    background: none;
    border: none;
    border-radius: 3px;
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }

  .day:hover {
    background: var(--paper-sunk);
  }

  .day.out {
    color: var(--ink-faint);
  }

  .day.today {
    font-weight: 700;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .day.picked {
    background: var(--amber-wash);
  }

  .day.edge {
    background: var(--amber);
    color: var(--ink);
    font-weight: 700;
  }

  .dot {
    position: absolute;
    left: 50%;
    bottom: 0.2rem;
    width: 0.25rem;
    height: 0.25rem;
    border-radius: 50%;
    background: var(--amber-ink);
    transform: translateX(-50%);
  }

  .range {
    margin: 0;
    color: var(--ink-soft);
  }

  .clear {
    margin-left: var(--space-2);
    padding: 0;
    background: none;
    border: none;
    color: var(--ink);
    font-weight: 600;
    text-decoration: underline;
    text-underline-offset: 3px;
    cursor: pointer;
  }
</style>
