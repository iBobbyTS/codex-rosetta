<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../shared/i18n.svelte';

  export type OrderedListItem = { id: string; value?: string; current?: boolean; status?: string };

  let {
    items,
    disabled = false,
    compact = false,
    renderId,
    onmove,
    onremove,
    oncurrent,
    moveUpLabel,
    moveDownLabel,
    currentLabel,
    removeLabel,
    children,
  }: {
    items: OrderedListItem[];
    disabled?: boolean;
    compact?: boolean;
    renderId?: string;
    onmove?: (id: string, offset: -1 | 1) => void;
    onremove?: (id: string) => void;
    oncurrent?: (id: string) => void;
    moveUpLabel?: (item: OrderedListItem) => string;
    moveDownLabel?: (item: OrderedListItem) => string;
    currentLabel?: (item: OrderedListItem) => string;
    removeLabel?: (item: OrderedListItem) => string;
    children?: Snippet<[OrderedListItem, number]>;
  } = $props();
</script>

<div class:compact class="ordered-list-editor">
  {#each items as item, index}
    {#if renderId === undefined || renderId === item.id}
      <div class="ordered-list-row" data-ordered-id={item.id}>
        {#if children}{@render children(item, index)}{/if}
        <button type="button" class="btn btn-sm ordered-list-up" disabled={disabled || index === 0} aria-label={moveUpLabel?.(item) ?? t('aria.moveOrderedItemUp', { id: item.id })} onclick={() => onmove?.(item.id, -1)}>↑</button>
        <button type="button" class="btn btn-sm ordered-list-down" disabled={disabled || index === items.length - 1} aria-label={moveDownLabel?.(item) ?? t('aria.moveOrderedItemDown', { id: item.id })} onclick={() => onmove?.(item.id, 1)}>↓</button>
        {#if oncurrent}
          <button type="button" class="btn btn-sm ordered-list-current" disabled={disabled || item.current} aria-label={currentLabel?.(item) ?? t('aria.selectOrderedItem', { id: item.id })} onclick={() => oncurrent?.(item.id)}>{item.current ? t('provider.url.current') : t('provider.url.select')}</button>
        {/if}
        {#if onremove}
          <button type="button" class="btn btn-sm ordered-list-remove" disabled={disabled || items.length === 1} aria-label={removeLabel?.(item) ?? t('aria.removeOrderedItem', { id: item.id })} onclick={() => onremove?.(item.id)}>{t('btn.remove')}</button>
        {/if}
      </div>
    {/if}
  {/each}
</div>

<style>
  .ordered-list-editor { display: grid; gap: 5px; }
  .ordered-list-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .ordered-list-row :global(input) { min-width: 0; flex: 1; }
  .ordered-list-row :global(label) { display: flex; align-items: center; gap: 4px; white-space: nowrap; font-size: 11px; }
  .ordered-list-row :global(label input) { flex: 0; }
  .compact .ordered-list-row { gap: 3px; }
</style>
