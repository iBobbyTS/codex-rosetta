<script lang="ts">
  let {
    value,
    ariaLabel,
    clearLabel,
    placeholder = '',
    onchange,
  }: {
    value: string;
    ariaLabel: string;
    clearLabel: string;
    placeholder?: string;
    onchange: (value: string) => void;
  } = $props();

  let editing = $state(false);

  function maskedValue(secret: string): string {
    if (secret === '***' || /^.{4}\*{3}.{4}$/u.test(secret) || /^\$\{.+\}$/u.test(secret)) return secret;
    if (secret.length > 8) return `${secret.slice(0, 4)}•••${secret.slice(-4)}`;

    const visibleCount = Math.floor(secret.length / 2);
    const prefixCount = Math.ceil(visibleCount / 2);
    const suffixCount = Math.floor(visibleCount / 2);
    const hiddenCount = secret.length - visibleCount;
    return `${secret.slice(0, prefixCount)}${'•'.repeat(hiddenCount)}${suffixCount ? secret.slice(-suffixCount) : ''}`;
  }

  function updateValue(next: string): void {
    editing = true;
    onchange(next);
  }

  function finishEditing(): void {
    editing = false;
  }

  function clear(): void {
    editing = false;
    onchange('');
  }
</script>

{#if editing || value.length === 0}
  <input
    type="password"
    {value}
    aria-label={ariaLabel}
    {placeholder}
    autocomplete="new-password"
    onfocus={() => editing = true}
    oninput={(event) => updateValue(event.currentTarget.value)}
    onblur={finishEditing}
  />
{:else}
  <div class="credential-display-row">
    <input class="credential-display" type="text" value={maskedValue(value)} aria-label={ariaLabel} readonly />
    <button type="button" class="credential-clear" aria-label={clearLabel} title={clearLabel} onclick={clear}>
      <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>
    </button>
  </div>
{/if}

<style>
  input {
    width: 100%;
    min-width: 0;
  }

  .credential-display-row {
    display: flex;
    flex: 1 1 0;
    align-items: center;
    gap: 4px;
    min-width: 0;
  }

  .credential-display {
    flex: 1;
  }

  .credential-clear {
    display: inline-flex;
    width: 30px;
    height: 30px;
    flex: 0 0 30px;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 0;
    border-radius: var(--radius);
    background: transparent;
    color: var(--text-dim);
    cursor: pointer;
  }

  .credential-clear:hover {
    background: var(--bg-hover);
    color: var(--red);
  }

  .credential-clear:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .credential-clear svg {
    width: 16px;
    height: 16px;
    fill: none;
    stroke: currentColor;
    stroke-linecap: round;
    stroke-width: 2;
  }
</style>
