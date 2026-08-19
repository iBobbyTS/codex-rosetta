<script lang="ts">
  import { onMount } from 'svelte';

  let {
    content,
    ariaLabel = 'More information',
  }: {
    content: string;
    ariaLabel?: string;
  } = $props();

  let trigger = $state<HTMLSpanElement>();
  let visible = $state(false);
  let left = $state(0);
  let top = $state(0);
  let below = $state(false);

  function updatePosition(): void {
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = 280;
    left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8);
    below = rect.top < 150;
    top = below ? rect.bottom + 8 : rect.top - 8;
  }

  function show(): void {
    updatePosition();
    visible = true;
  }

  function refreshPosition(): void {
    if (visible) updatePosition();
  }

  onMount(() => {
    const refresh = () => refreshPosition();
    window.addEventListener('resize', refresh);
    window.addEventListener('scroll', refresh, true);
    return () => {
      window.removeEventListener('resize', refresh);
      window.removeEventListener('scroll', refresh, true);
    };
  });
</script>

<span
  bind:this={trigger}
  class="hint-icon"
  role="button"
  tabindex="0"
  aria-label={ariaLabel}
  onmouseenter={show}
  onfocus={show}
  onmouseleave={() => { visible = false; }}
  onblur={() => { visible = false; }}
>
  ?
  {#if visible}
    <span
      class:hint-popup-below={below}
      class="hint-popup"
      role="tooltip"
      style={`left:${left}px;top:${top}px`}
    >{content}</span>
  {/if}
</span>
