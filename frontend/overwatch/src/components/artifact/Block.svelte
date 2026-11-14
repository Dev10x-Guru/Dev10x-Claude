<script lang="ts">
  import CalloutBlock from "./CalloutBlock.svelte";
  import ClaimBlock from "./ClaimBlock.svelte";
  import Control from "./Control.svelte";
  import DecisionsBlock from "./DecisionsBlock.svelte";
  import DraftBlock from "./DraftBlock.svelte";
  import EvidenceBlock from "./EvidenceBlock.svelte";
  import KvBlock from "./KvBlock.svelte";
  import MermaidBlock from "./MermaidBlock.svelte";
  import PillsBlock from "./PillsBlock.svelte";
  import ProseBlock from "./ProseBlock.svelte";
  import StatsBlock from "./StatsBlock.svelte";
  import TableBlock from "./TableBlock.svelte";
  import type { Block } from "../../lib/artifact";

  let { block }: { block: Block } = $props();
</script>

{#if block.type === "claim"}
  <ClaimBlock {block} />
{:else if block.type === "prose"}
  <ProseBlock {block} />
{:else if block.type === "callout"}
  <CalloutBlock {block} />
{:else if block.type === "kv"}
  <KvBlock {block} />
{:else if block.type === "table"}
  <TableBlock {block} />
{:else if block.type === "pills"}
  <PillsBlock {block} />
{:else if block.type === "stats"}
  <StatsBlock {block} />
{:else if block.type === "mermaid"}
  <MermaidBlock {block} />
{:else if block.type === "draft"}
  <DraftBlock {block} />
{:else if block.type === "evidence"}
  <EvidenceBlock {block} />
{:else if block.type === "decisions"}
  <DecisionsBlock {block} />
{:else if block.type === "button" || block.type === "choice" || block.type === "form"}
  <Control {block} />
{:else}
  <p class="unknown">This page uses a block this Overwatch does not know yet.</p>
{/if}

<style>
  .unknown {
    margin: 0;
    color: var(--ink-faint);
    font-size: var(--step--1);
  }
</style>
