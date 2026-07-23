<script lang="ts">
  import { onMount } from 'svelte';
  import {
    initializeConfiguration,
    launchGateway,
    probeConfiguration,
    setLocalMode,
  } from './commands';

  type BootstrapStep = 'probing' | 'password' | 'local-mode' | 'starting' | 'error';

  let step = $state<BootstrapStep>('probing');
  let password = $state('');
  let localModeChoice = $state<boolean | null>(null);
  let errorCode = $state('desktop_start_failed');
  let errorMessage = $state('The local gateway could not be started.');
  let retryAction = $state<() => Promise<void>>(probeGateway);

  const errorDescriptions: Record<string, string> = {
    bootstrap_capability_required: 'This window is not allowed to manage the local gateway.',
    config_exists: 'Gateway configuration already exists. Check its state and try again.',
    empty_admin_password: 'Enter a non-empty administrator password.',
    invalid_port: 'The configured desktop port is invalid.',
    local_mode_unconfirmed: 'Codex local mode requires an explicit decision before startup.',
    sidecar_path: 'The bundled gateway could not be found.',
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
      message: errorDescriptions[code] ?? 'The local gateway could not be started.',
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
  <title>Codex-Rosetta Setup</title>
</svelte:head>

<main>
  <section class="setup-panel" aria-labelledby="setup-title">
    <header>
      <div class="mark" aria-hidden="true">R</div>
      <div>
        <p class="product">Codex-Rosetta</p>
        <h1 id="setup-title">
          {step === 'password'
            ? 'Create administrator access'
            : step === 'local-mode'
              ? 'Connect Codex'
              : step === 'error'
                ? 'Startup failed'
                : 'Starting local gateway'}
        </h1>
      </div>
    </header>

    {#if step === 'probing'}
      <div class="status" role="status">
        <span class="spinner" aria-hidden="true"></span>
        <div>
          <strong>Checking local configuration</strong>
          <p>Verifying the bundled gateway before it starts.</p>
        </div>
      </div>
    {:else if step === 'password'}
      <form onsubmit={initializeGateway}>
        <p class="description">
          Set the password used to access the gateway administration interface. It cannot be
          recovered from this desktop app.
        </p>
        <label for="admin-password">Administrator password</label>
        <input
          id="admin-password"
          type="password"
          bind:value={password}
          autocomplete="new-password"
          required
        />
        <p class="field-note">Any non-empty password is accepted.</p>
        <button class="primary" type="submit">Continue</button>
      </form>
    {:else if step === 'local-mode'}
      <div class="decision">
        <p class="description">
          Local mode updates the Codex model catalog and endpoint configuration on this computer
          so Codex uses this gateway. This can replace existing Codex catalog entries.
        </p>
        <div class="actions">
          <button class="primary" type="button" onclick={() => void confirmLocalMode(true)}>
            Enable local mode
          </button>
          <button class="secondary" type="button" onclick={() => void confirmLocalMode(false)}>
            Not now
          </button>
        </div>
      </div>
    {:else if step === 'starting'}
      <div class="status" role="status">
        <span class="spinner" aria-hidden="true"></span>
        <div>
          <strong>Starting gateway</strong>
          <p>The administration window will open when the local service is ready.</p>
        </div>
      </div>
    {:else}
      <div class="error" role="alert">
        <div class="error-symbol" aria-hidden="true">!</div>
        <div>
          <strong>{errorMessage}</strong>
          <p class="error-code">Error code: {errorCode}</p>
        </div>
      </div>
      <button class="primary" type="button" onclick={() => void retryAction()}>Try again</button>
    {/if}
  </section>
</main>
