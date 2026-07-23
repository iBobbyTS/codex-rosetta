<script lang="ts">
  import { onMount } from 'svelte';
  import {
    initializeConfiguration,
    launchGateway,
    probeConfiguration,
    setLocalMode,
  } from './commands';
  import { t } from '../shared/i18n.svelte';

  type BootstrapStep = 'probing' | 'password' | 'local-mode' | 'starting' | 'error';

  let step = $state<BootstrapStep>('probing');
  let password = $state('');
  let localModeChoice = $state<boolean | null>(null);
  let errorCode = $state('desktop_start_failed');
  let errorMessage = $state(t('bootstrap.error.default'));
  let retryAction = $state<() => Promise<void>>(probeGateway);

  const errorDescriptionKeys: Record<string, string> = {
    bootstrap_capability_required: 'bootstrap.error.bootstrap_capability_required',
    config_exists: 'bootstrap.error.config_exists',
    empty_admin_password: 'bootstrap.error.empty_admin_password',
    invalid_port: 'bootstrap.error.invalid_port',
    local_mode_unconfirmed: 'bootstrap.error.local_mode_unconfirmed',
    sidecar_path: 'bootstrap.error.sidecar_path',
  };

  function describeError(error: unknown): { code: string; message: string } {
    const code =
      typeof error === 'string'
        ? error
        : error instanceof Error
          ? error.message
          : 'desktop_start_failed';
    return {
      code,
      message: t(errorDescriptionKeys[code] ?? 'bootstrap.error.default'),
    };
  }

  function showError(error: unknown, retry: () => Promise<void>): void {
    const detail = describeError(error);
    errorCode = detail.code;
    errorMessage = detail.message;
    retryAction = retry;
    step = 'error';
  }

  async function probeGateway(): Promise<void> {
    step = 'probing';
    try {
      const result = await probeConfiguration();
      if (result.state === 'needs_initialization') {
        step = 'password';
        return;
      }
      if (result.state === 'needs_local_mode_confirmation') {
        localModeChoice = null;
        step = 'local-mode';
        return;
      }
      if (result.state !== 'ready') {
        throw new Error(result.code ?? 'invalid_sidecar_response');
      }
      await startGateway();
    } catch (error) {
      showError(error, probeGateway);
    }
  }

  async function initializeGateway(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!password.trim()) {
      showError('empty_admin_password', returnToPassword);
      password = '';
      return;
    }

    step = 'starting';
    let suppliedPassword = password;
    try {
      const result = await initializeConfiguration(suppliedPassword, () => {
        password = '';
      });
      if (result.state !== 'ready_for_local_mode_confirmation') {
        throw new Error(result.code ?? 'invalid_sidecar_response');
      }
      localModeChoice = null;
      step = 'local-mode';
    } catch (error) {
      showError(error, returnToPassword);
    } finally {
      suppliedPassword = '';
    }
  }

  async function returnToPassword(): Promise<void> {
    password = '';
    step = 'password';
  }

  async function confirmLocalMode(confirm: boolean): Promise<void> {
    localModeChoice = confirm;
    step = 'starting';
    try {
      await setLocalMode(confirm);
      await startGateway();
    } catch (error) {
      showError(error, retryLocalMode);
    }
  }

  async function retryLocalMode(): Promise<void> {
    if (localModeChoice === null) {
      step = 'local-mode';
      return;
    }
    await confirmLocalMode(localModeChoice);
  }

  async function startGateway(): Promise<void> {
    step = 'starting';
    try {
      await launchGateway();
    } catch (error) {
      showError(error, startGateway);
    }
  }

  onMount(() => {
    void probeGateway();
  });
</script>

<svelte:head>
  <title>{t('product.setupTitle')}</title>
</svelte:head>

<main>
  <section class="setup-panel" aria-labelledby="setup-title">
    <header>
      <div class="mark" aria-hidden="true">{t('product.mark')}</div>
      <div>
        <p class="product">{t('product.name')}</p>
        <h1 id="setup-title">
          {step === 'password'
            ? t('bootstrap.title.createAdmin')
            : step === 'local-mode'
              ? t('bootstrap.title.connectCodex')
              : step === 'error'
                ? t('bootstrap.title.failed')
                : t('bootstrap.title.starting')}
        </h1>
      </div>
    </header>

    {#if step === 'probing'}
      <div class="status" role="status">
        <span class="spinner" aria-hidden="true"></span>
        <div>
          <strong>{t('bootstrap.checking')}</strong>
          <p>{t('bootstrap.checkingDetail')}</p>
        </div>
      </div>
    {:else if step === 'password'}
      <form onsubmit={initializeGateway}>
        <p class="description">{t('bootstrap.passwordDescription')}</p>
        <label for="admin-password">{t('bootstrap.adminPassword')}</label>
        <input
          id="admin-password"
          type="password"
          bind:value={password}
          autocomplete="new-password"
          required
        />
        <p class="field-note">{t('bootstrap.passwordHint')}</p>
        <button class="primary" type="submit">{t('btn.continue')}</button>
      </form>
    {:else if step === 'local-mode'}
      <div class="decision">
        <p class="description">{t('bootstrap.localModeDescription')}</p>
        <div class="actions">
          <button class="primary" type="button" onclick={() => void confirmLocalMode(true)}>
            {t('bootstrap.enableLocalMode')}
          </button>
          <button class="secondary" type="button" onclick={() => void confirmLocalMode(false)}>
            {t('bootstrap.notNow')}
          </button>
        </div>
      </div>
    {:else if step === 'starting'}
      <div class="status" role="status">
        <span class="spinner" aria-hidden="true"></span>
        <div>
          <strong>{t('bootstrap.starting')}</strong>
          <p>{t('bootstrap.startingDetail')}</p>
        </div>
      </div>
    {:else}
      <div class="error" role="alert">
        <div class="error-symbol" aria-hidden="true">!</div>
        <div>
          <strong>{errorMessage}</strong>
          <p class="error-code">{t('bootstrap.errorCode', { code: errorCode })}</p>
        </div>
      </div>
      <button class="primary" type="button" onclick={() => void retryAction()}>{t('btn.tryAgain')}</button>
    {/if}
  </section>
</main>
