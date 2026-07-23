<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { t } from '../lib/i18n.svelte';

  type Dict = Record<string, unknown>;
  type Config = {
    server?: Dict;
    codex?: Dict;
    models?: Record<string, unknown>;
    model_catalog_configured?: boolean;
    codex_home?: string;
  };

  const taskDefaults = {
    review: 'codex-auto-review',
    consolidation: 'gpt-5.4',
    extract: 'gpt-5.4-mini',
  } as const;

  let config = $state<Config>({});
  let proxy = $state('');
  let bodyLimit = $state<number | string>(128);
  let localMode = $state(false);
  let localModeConfirmed = $state(false);
  let reviewModel = $state('');
  let consolidationModel = $state('');
  let extractModel = $state('');
  let diagnostics = $state<unknown>(null);
  let hostIp = $state('');
  let internalToken = $state('');
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');

  const configuredModels = $derived(Object.keys(config.models ?? {}).sort());
  const taskModelsEnabled = $derived(localMode && localModeConfirmed);

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);

  function hydrate(next: Config): void {
    config = next;
    const server = next.server ?? {};
    const codex = next.codex ?? {};
    const memories = (codex.memories && typeof codex.memories === 'object' ? codex.memories : {}) as Dict;
    proxy = String(server.proxy ?? '');
    bodyLimit = server.request_body_limit_mb === 'unlimited'
      ? 'unlimited'
      : Number(server.request_body_limit_mb ?? 128);
    localMode = server.local_mode === true;
    localModeConfirmed = server.local_mode_confirmed === true;
    reviewModel = String(codex.auto_review_model_override ?? '');
    consolidationModel = String(memories.consolidation_model ?? '');
    extractModel = String(memories.extract_model ?? '');
  }

  async function load(signal?: AbortSignal): Promise<void> {
    try {
      hydrate(await api.get<Config>('/admin/api/config', signal));
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) error = message(cause);
    }
  }

  async function operation(action: () => Promise<unknown>, success: string): Promise<void> {
    busy = true;
    error = '';
    notice = '';
    try {
      await action();
      await load();
      notice = success;
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
    }
  }

  function saveServer(): void {
    const server = config.server ?? {};
    const wasEnabled = server.local_mode === true;
    const wasConfirmed = server.local_mode_confirmed === true;
    const needsConfirmation = localMode && !wasConfirmed;
    if (needsConfirmation) {
      const home = config.codex_home || 'the configured Codex home';
      const catalogWarning = config.model_catalog_configured
        ? ` The existing model catalog configured under ${home} will be replaced.`
        : ` A managed model catalog will be created under ${home}.`;
      if (!confirm(`Enable Codex local mode and synchronize Codex configuration?${catalogWarning}`)) {
        localMode = wasEnabled;
        localModeConfirmed = wasConfirmed;
        return;
      }
    }
    const body: Dict = {
      proxy: proxy.trim(),
      request_body_limit_mb: bodyLimit,
      local_mode: localMode,
    };
    if (needsConfirmation) body.local_mode_confirmed = true;
    void operation(() => api.put('/admin/api/config/server', body), 'Server settings saved.');
  }

  function saveCodex(): void {
    void operation(
      () => api.put('/admin/api/config/codex', {
        auto_review_model_override: reviewModel || null,
        memories: {
          consolidation_model: consolidationModel || null,
          extract_model: extractModel || null,
        },
      }),
      'Codex settings saved.',
    );
  }

  function taskStatus(selected: string, fallback: string): string {
    const effective = selected || fallback;
    if (!taskModelsEnabled) return `Effective default: ${fallback} (local mode is not confirmed)`;
    if (!configuredModels.includes(effective)) return `Missing model: ${effective}`;
    return selected ? `Configured model: ${effective}` : `Effective default: ${effective}`;
  }

  async function diagnose(): Promise<void> {
    busy = true;
    error = '';
    diagnostics = null;
    try {
      diagnostics = await api.get('/admin/api/diagnostics/network');
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
    }
  }

  async function revealHostIp(): Promise<void> {
    busy = true;
    error = '';
    try {
      const result = await api.get<{ ok?: boolean; ip?: string; error?: string }>('/admin/api/diagnostics/host-ip');
      if (!result.ok || !result.ip) throw new Error(result.error || 'Host IP is unavailable.');
      hostIp = result.ip;
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
    }
  }

  async function revealInternalToken(): Promise<void> {
    busy = true;
    error = '';
    try {
      const result = await api.get<{ token?: string }>('/admin/api/internal-token');
      if (!result.token) throw new Error('Internal token is unavailable.');
      internalToken = result.token;
    } catch (cause) {
      error = message(cause);
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  });
</script>

<section class="settings" aria-labelledby="settings-title">
  <header>
    <div>
      <h2 id="settings-title">{t('modal.settings', 'Server and Codex settings')}</h2>
      <p>Configuration writes and Codex synchronization remain transactional in Python.</p>
    </div>
    <button disabled={busy} onclick={() => void operation(() => api.post('/admin/api/config/reload'), 'Configuration reloaded.')}>Reload config</button>
  </header>

  {#if error}<div class="alert" role="alert">{error}</div>{/if}
  {#if notice}<div class="notice" role="status">{notice}</div>{/if}

  <div class="columns">
    <div class="panel">
      <h3>Server</h3>
      <label>{t('label.globalProxy', 'Global proxy')} <input bind:value={proxy} placeholder="http://proxy.example:8080" /></label>
      <label>{t('label.requestBodyLimit', 'Request body limit')}
        <select bind:value={bodyLimit}>
          {#each [64, 128, 256, 512, 1024] as value}<option value={value}>{value} MB</option>{/each}
          <option value="unlimited">Unlimited</option>
        </select>
      </label>
      <label class="check"><input type="checkbox" bind:checked={localMode} /> {t('label.localMode', 'Codex local mode')}</label>
      <p class:warning={localMode && !localModeConfirmed} class="hint">
        {localModeConfirmed ? 'Local mode is explicitly confirmed.' : 'Local mode is not confirmed.'}
        {#if config.model_catalog_configured} Existing model catalog detected.{/if}
      </p>
      {#if config.codex_home}<p class="hint"><code>{config.codex_home}</code></p>{/if}
      <button class="primary" disabled={busy} onclick={saveServer}>{t('btn.save', 'Save')}</button>
    </div>

    <div class="panel">
      <h3>Codex task models</h3>
      <label>Auto review model
        <select bind:value={reviewModel} disabled={!taskModelsEnabled}>
          <option value="">Use default ({taskDefaults.review})</option>
          {#each configuredModels as model}<option value={model}>{model}</option>{/each}
          {#if reviewModel && !configuredModels.includes(reviewModel)}<option value={reviewModel}>{reviewModel} (missing)</option>{/if}
        </select>
      </label>
      <p class="hint" class:missing={taskStatus(reviewModel, taskDefaults.review).startsWith('Missing')}>{taskStatus(reviewModel, taskDefaults.review)}</p>
      <label>Memory consolidation model
        <select bind:value={consolidationModel} disabled={!taskModelsEnabled}>
          <option value="">Use default ({taskDefaults.consolidation})</option>
          {#each configuredModels as model}<option value={model}>{model}</option>{/each}
          {#if consolidationModel && !configuredModels.includes(consolidationModel)}<option value={consolidationModel}>{consolidationModel} (missing)</option>{/if}
        </select>
      </label>
      <p class="hint" class:missing={taskStatus(consolidationModel, taskDefaults.consolidation).startsWith('Missing')}>{taskStatus(consolidationModel, taskDefaults.consolidation)}</p>
      <label>Memory extraction model
        <select bind:value={extractModel} disabled={!taskModelsEnabled}>
          <option value="">Use default ({taskDefaults.extract})</option>
          {#each configuredModels as model}<option value={model}>{model}</option>{/each}
          {#if extractModel && !configuredModels.includes(extractModel)}<option value={extractModel}>{extractModel} (missing)</option>{/if}
        </select>
      </label>
      <p class="hint" class:missing={taskStatus(extractModel, taskDefaults.extract).startsWith('Missing')}>{taskStatus(extractModel, taskDefaults.extract)}</p>
      <button class="primary" disabled={busy || !taskModelsEnabled} onclick={saveCodex}>Save Codex settings</button>
    </div>
  </div>

  <div class="panel sensitive">
    <h3>On-demand diagnostics</h3>
    <p class="hint">Sensitive values are fetched only after an explicit action.</p>
    <div class="actions">
      <button disabled={busy} onclick={() => void revealHostIp()}>Show host IP</button>
      <button disabled={busy} onclick={() => void revealInternalToken()}>Reveal internal token</button>
    </div>
    {#if hostIp}<p>Host IP: <code>{hostIp}</code></p>{/if}
    {#if internalToken}<p>Internal token: <code>{internalToken}</code></p>{/if}
  </div>

  <div class="diagnostics">
    <button disabled={busy} onclick={() => void diagnose()}>{t('diag.runDiag', 'Run network diagnostics')}</button>
    {#if diagnostics}<pre>{JSON.stringify(diagnostics, null, 2)}</pre>{/if}
  </div>
</section>

<style>
  .settings{display:grid;gap:12px;margin-top:14px;padding-top:20px;border-top:1px solid #d0d5dd}
  header,.actions{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
  h2,h3,p{margin:0}
  header p,.hint{color:#667085;font-size:12px}
  .columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .panel{display:grid;gap:10px;padding:16px;border:1px solid #d0d5dd;border-radius:6px;background:#fff}
  .panel label{display:grid;gap:5px}
  .panel input,.panel select{font:inherit;padding:8px;min-width:0}
  .check{display:flex!important;align-items:center}.check input{width:auto}
  .warning,.missing{color:#b42318}.sensitive .actions{justify-content:flex-start}
  .alert,.notice{padding:10px;border-radius:4px}.alert{background:#fee4e2;color:#912018}.notice{background:#dcfae6;color:#085d3a}
  .diagnostics{display:grid;gap:8px;justify-items:start}.diagnostics pre{max-width:100%;overflow:auto;padding:12px;background:#20262e;color:#f5f7fa;border-radius:6px}
  code{overflow-wrap:anywhere}@media(max-width:800px){.columns{grid-template-columns:1fr}}
</style>
