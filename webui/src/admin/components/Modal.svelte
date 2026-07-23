<script lang="ts">
  import { tick } from 'svelte';

  let {
    open,
    labelledby,
    wide = false,
    className = '',
    sidecar,
    onclose,
    children,
  }: {
    open: boolean;
    labelledby: string;
    wide?: boolean;
    className?: string;
    sidecar?: import('svelte').Snippet;
    onclose: () => void;
    children: import('svelte').Snippet;
  } = $props();

  let panel = $state<HTMLDivElement>();
  let previousFocus: HTMLElement | null = null;
  let wasOpen = false;

  $effect(() => {
    if (open && !wasOpen) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      void tick().then(() => {
        panel?.querySelector<HTMLElement>('[autofocus], input, select, textarea, button')?.focus();
      });
    } else if (!open && wasOpen) {
      previousFocus?.focus();
      previousFocus = null;
    }
    wasOpen = open;
  });

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      onclose();
      return;
    }
    if (event.key !== 'Tab' || !panel) return;
    const focusable = [...panel.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])')];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
</script>

{#if open}
  <div
    class="modal-overlay open"
    role="presentation"
    onclick={(event) => { if (event.target === event.currentTarget) onclose(); }}
    onkeydown={handleKeydown}
  >
    {#if sidecar}
      <div bind:this={panel} class="model-group-modal-shell">
        <div class:modal-wide={wide} class={`modal ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={labelledby} tabindex="-1">
          {@render children()}
        </div>
        {@render sidecar()}
      </div>
    {:else}
      <div bind:this={panel} class:modal-wide={wide} class={`modal ${className}`.trim()} role="dialog" aria-modal="true" aria-labelledby={labelledby} tabindex="-1">
        {@render children()}
      </div>
    {/if}
  </div>
{/if}
