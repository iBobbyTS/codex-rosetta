<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, api, request } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import { createSerialPoll } from '../lib/polling';

  type SearchProviderType =
    | 'tavily'
    | 'configured_responses_provider'
    | 'self_hosted_google'
    | 'self_hosted_bing'
    | 'self_hosted_bing_browser';
  type SearchRow = {
    id: string;
    provider: SearchProviderType;
    tavily_api_key?: string;
    responses_provider?: string;
    responses_model?: string;
  };
  type Provider = { api_type?: string; enabled?: boolean };
  type SearchContract = {
    provider_types?: SearchProviderType[];
    responses_models?: string[];
    max_providers?: number;
  };
  type Config = {
    providers?: Record<string, Provider>;
    server?: { web_search?: { providers?: SearchRow[] } };
    web_search_contract?: SearchContract;
  };
  type Status = {
    configured?: boolean;
    service_online?: boolean;
    browser_ready?: boolean;
    error?: string;
  };
  type UsageEntry = {
    id?: string;
    status?: string;
    used?: number | null;
    limit?: number | null;
    reset_date?: string | null;
  };
  type UsageResponse = { entries?: UsageEntry[] };
  type DisplayUsage = { used: number; limit: number; percent: number; resetDate: string };

  const searchTestErrorKeys: Record<string, string> = {
    network_search_test_configuration_unavailable: 'network.searchTestError.configurationUnavailable',
    network_search_test_no_eligible_model: 'network.searchTestError.noEligibleModel',
    network_search_test_authorization_failed: 'network.searchTestError.authorizationFailed',
    network_search_test_timed_out: 'network.searchTestError.timedOut',
    network_search_test_rate_limited: 'network.searchTestError.rateLimited',
    network_search_test_unavailable: 'network.searchTestError.unavailable',
    network_search_test_rejected: 'network.searchTestError.rejected',
  };

  let rows = $state<SearchRow[]>([]);
  let providers = $state<Record<string, Provider>>({});
  let providerTypes = $state<SearchProviderType[]>([]);
  let responsesModels = $state<string[]>([]);
  let maxProviders = $state(0);
  let draggedId = $state<string | null>(null);
  let status = $state<Status | null>(null);
  let usageById = $state<Map<string, UsageEntry>>(new Map());
  let usageLoading = $state(true);
  let loading = $state(true);
  let saving = $state(false);
  let testing = $state(false);
  let testResult = $state('');
  let testError = $state('');
  let error = $state('');
  let notice = $state('');
  let testController: AbortController | null = null;

  const responsesProviders = $derived(
    Object.entries(providers)
      .filter(([, item]) => item.api_type === 'responses' && item.enabled !== false)
      .map(([name]) => name)
      .sort(),
  );
  const hasInvalidResponses = $derived(
    rows.some((row) => row.provider === 'configured_responses_provider' && !row.responses_provider),
  );

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const aborted = (value: unknown) =>
    (value instanceof DOMException || value instanceof Error) && value.name === 'AbortError';
  const searchTestError = (value: unknown): string => {
    if (value instanceof ApiError && value.code) {
      const key = searchTestErrorKeys[value.code];
      if (key) return t(key);
    }
    return t('network.searchTestFailed');
  };
  const providerLabel = (value: SearchProviderType): string => ({
    tavily: t('network.provider.tavily'),
    configured_responses_provider: t('network.provider.configuredResponses'),
    self_hosted_google: t('network.provider.google'),
    self_hosted_bing: t('network.provider.bingRss'),
    self_hosted_bing_browser: t('network.provider.bingBrowser'),
  })[value];

  function displayUsage(id: string): DisplayUsage | null {
    const entry = usageById.get(id);
    if (!entry || entry.status !== 'ok') return null;
    const { used, limit, reset_date: resetDate } = entry;
    if (
      typeof used !== 'number' || !Number.isFinite(used) || used < 0
      || typeof limit !== 'number' || !Number.isFinite(limit) || limit <= 0
      || typeof resetDate !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(resetDate)
    ) return null;
    const parsedDate = new Date(`${resetDate}T00:00:00Z`);
    if (!Number.isFinite(parsedDate.valueOf()) || parsedDate.toISOString().slice(0, 10) !== resetDate) return null;
    return {
      used,
      limit,
      percent: Math.max(0, Math.min(100, (used / limit) * 100)),
      resetDate: resetDate.replaceAll('-', '/'),
    };
  }

  function createId(): string {
    if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
  }

  function rowForType(id: string, provider: SearchProviderType): SearchRow {
    if (provider === 'tavily') return { id, provider, tavily_api_key: '' };
    if (provider === 'configured_responses_provider') {
      return {
        id,
        provider,
        responses_provider: responsesProviders[0] ?? '',
        responses_model: responsesModels[0] ?? '',
      };
    }
    return { id, provider };
  }

  function replaceRow(id: string, update: (row: SearchRow) => SearchRow): void {
    rows = rows.map((row) => row.id === id ? update(row) : row);
  }

  function changeType(id: string, provider: SearchProviderType): void {
    replaceRow(id, (row) => rowForType(row.id, provider));
  }

  function addRow(): void {
    if (rows.length >= maxProviders) return;
    const provider = providerTypes[0];
    if (!provider) return;
    rows = [...rows, rowForType(createId(), provider)];
  }

  function removeRow(id: string): void {
    rows = rows.filter((row) => row.id !== id);
  }

  function moveRow(id: string, offset: -1 | 1): void {
    const index = rows.findIndex((row) => row.id === id);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= rows.length) return;
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    rows = next;
  }

  function moveToTargetIndex(sourceId: string, targetId: string): void {
    if (sourceId === targetId) return;
    const sourceIndex = rows.findIndex((row) => row.id === sourceId);
    const targetIndex = rows.findIndex((row) => row.id === targetId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    // A dropped row occupies the target row's pre-drop index in either direction.
    const next = [...rows];
    const [source] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, source);
    rows = next;
  }

  function startDrag(event: DragEvent, id: string): void {
    draggedId = id;
    event.dataTransfer?.setData('text/plain', id);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
  }

  function dropRow(event: DragEvent, targetId: string): void {
    event.preventDefault();
    const sourceId = event.dataTransfer?.getData('text/plain') || draggedId;
    if (sourceId) moveToTargetIndex(sourceId, targetId);
    draggedId = null;
  }

  function canonicalRows(): SearchRow[] {
    return rows.map((row) => {
      if (row.provider === 'tavily') {
        return { id: row.id, provider: row.provider, tavily_api_key: row.tavily_api_key ?? '' };
      }
      if (row.provider === 'configured_responses_provider') {
        return {
          id: row.id,
          provider: row.provider,
          responses_provider: row.responses_provider ?? '',
          responses_model: row.responses_model ?? responsesModels[0] ?? '',
        };
      }
      return { id: row.id, provider: row.provider };
    });
  }

  async function loadConfig(signal: AbortSignal): Promise<void> {
    try {
      const config = await api.get<Config>('/admin/api/config', signal);
      providers = config.providers ?? {};
      providerTypes = config.web_search_contract?.provider_types ?? [];
      responsesModels = config.web_search_contract?.responses_models ?? [];
      maxProviders = config.web_search_contract?.max_providers ?? 0;
      rows = (config.server?.web_search?.providers ?? []).map((row) => ({ ...row }));
      error = '';
    } catch (cause) {
      if (!aborted(cause)) error = message(cause);
    } finally {
      loading = false;
    }
  }

  async function loadStatus(signal: AbortSignal): Promise<void> {
    try {
      status = await api.get<Status>('/admin/api/network-search/status', signal);
    } catch (cause) {
      if (!aborted(cause)) status = { configured: true, service_online: false, error: message(cause) };
    }
  }

  async function loadUsage(signal: AbortSignal): Promise<void> {
    try {
      const result = await api.get<UsageResponse>('/admin/api/network-search/usage', signal);
      const next = new Map<string, UsageEntry>();
      for (const entry of result.entries ?? []) {
        if (typeof entry.id === 'string' && entry.id) next.set(entry.id, entry);
      }
      usageById = next;
    } catch (cause) {
      if (!aborted(cause)) usageById = new Map();
    } finally {
      usageLoading = false;
    }
  }

  const poll = createSerialPoll(loadStatus, 5000);

  async function save(): Promise<void> {
    saving = true;
    error = '';
    notice = '';
    try {
      const result = await api.put<{ server?: { web_search?: { providers?: SearchRow[] } } }>(
        '/admin/api/config/server',
        { web_search: { providers: canonicalRows() } },
      );
      rows = (result.server?.web_search?.providers ?? rows).map((row) => ({ ...row }));
      notice = t('toast.networkSearchSaved');
      await poll.runNow();
    } catch (cause) {
      error = message(cause);
    } finally {
      saving = false;
    }
  }

  async function testSearch(): Promise<void> {
    if (testing) return;
    testing = true;
    testError = '';
    testResult = '';
    const controller = new AbortController();
    testController = controller;
    try {
      const result = await request<unknown>('/admin/api/network-search/test', {
        method: 'POST',
        responseEffects: 'local',
        signal: controller.signal,
      });
      testResult = JSON.stringify(result, null, 2) ?? String(result);
    } catch (cause) {
      if (!controller.signal.aborted) {
        testError = aborted(cause)
          ? t('network.searchTestFailed')
          : searchTestError(cause);
      }
    } finally {
      if (testController === controller) testController = null;
      testing = false;
    }
  }

  onMount(() => {
    const controller = new AbortController();
    void loadConfig(controller.signal);
    void loadUsage(controller.signal);
    poll.start();
    return () => { controller.abort(); testController?.abort(); poll.stop(); };
  });
</script>

<div class="section network-search-section">
  <div class="section-header">
    <h2>{t('section.basicSearch')}</h2>
    <div class="search-actions">
      <span class="provider-limit">{t('network.providerCount', { count: rows.length, max: maxProviders })}</span>
      <button class="btn btn-sm" disabled={loading || rows.length >= maxProviders || !providerTypes.length} onclick={addRow}>{t('btn.addSearchProvider')}</button>
      <button class="btn btn-primary btn-sm" disabled={loading || saving || hasInvalidResponses} onclick={() => void save()}>{t('btn.save')}</button>
    </div>
  </div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}
  {#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  {#if loading}
    <p class="loading-text">{t('loading.networkSearch')}</p>
  {:else}
    <div class="table-scroll search-provider-table">
      <table>
        <thead><tr><th>{t('col.searchName')}</th><th>{t('col.searchConfiguration')}</th><th>{t('col.searchQuota')}</th></tr></thead>
        <tbody>
          {#each rows as row, index (row.id)}
            <tr data-row-id={row.id} class:dragging={draggedId === row.id} ondragover={(event) => event.preventDefault()} ondrop={(event) => dropRow(event, row.id)}>
              <td class="search-name-cell">
                <div class="row-order-controls">
                  <button class="drag-handle" draggable="true" aria-label={t('aria.dragSearchProvider')} title={t('aria.dragSearchProvider')} ondragstart={(event) => startDrag(event, row.id)} ondragend={() => draggedId = null}>⋮⋮</button>
                  <button class="order-button" disabled={index === 0} aria-label={t('aria.moveSearchProviderUp')} onclick={() => moveRow(row.id, -1)}>↑</button>
                  <button class="order-button" disabled={index === rows.length - 1} aria-label={t('aria.moveSearchProviderDown')} onclick={() => moveRow(row.id, 1)}>↓</button>
                </div>
                <label class="sr-only" for={`search-provider-type-${row.id}`}>{t('label.searchProviderType')}</label>
                <select id={`search-provider-type-${row.id}`} class="provider-type" value={row.provider} onchange={(event) => changeType(row.id, event.currentTarget.value as SearchProviderType)}>
                  {#each providerTypes as type}<option value={type}>{providerLabel(type)}</option>{/each}
                </select>
                {#if row.provider === 'configured_responses_provider'}
                  <label class="sr-only" for={`responses-provider-${row.id}`}>{t('label.responsesSearchProvider')}</label>
                  <select id={`responses-provider-${row.id}`} aria-label={t('label.responsesSearchProvider')} value={row.responses_provider ?? ''} disabled={!responsesProviders.length} onchange={(event) => replaceRow(row.id, (item) => ({ ...item, responses_provider: event.currentTarget.value }))}>
                    {#if !responsesProviders.length}<option value="">{t('network.provider.noResponses')}</option>{:else}{#each responsesProviders as name}<option value={name}>{name}</option>{/each}{/if}
                  </select>
                {/if}
                <button class="btn btn-sm btn-danger remove-row" onclick={() => removeRow(row.id)}>{t('btn.remove')}</button>
              </td>
              <td class="search-config-cell">
                {#if row.provider === 'tavily'}
                  <label class="sr-only" for={`tavily-key-${row.id}`}>{t('label.searchApiKey')}</label>
                  <input id={`tavily-key-${row.id}`} aria-label={t('label.searchApiKey')} type="password" autocomplete="new-password" value={row.tavily_api_key ?? ''} placeholder={t('label.searchApiKeyPlaceholder')} oninput={(event) => replaceRow(row.id, (item) => ({ ...item, tavily_api_key: event.currentTarget.value }))} />
                {:else if row.provider === 'configured_responses_provider'}
                  <label class="sr-only" for={`responses-model-${row.id}`}>{t('label.responsesSearchModel')}</label>
                  <select id={`responses-model-${row.id}`} aria-label={t('label.responsesSearchModel')} value={row.responses_model ?? ''} onchange={(event) => replaceRow(row.id, (item) => ({ ...item, responses_model: event.currentTarget.value }))}>
                    {#each responsesModels as name}<option value={name}>{name}</option>{/each}
                  </select>
                {:else}<span aria-label={t('network.noConfiguration')}>—</span>{/if}
              </td>
              <td class="search-quota-cell">
                {#if row.provider === 'tavily'}
                  {@const usage = displayUsage(row.id)}
                  {#if usageLoading}
                    <span>{t('network.quotaLoading')}</span>
                  {:else if usage}
                    <div class="quota-usage">
                      <progress max="100" value={usage.percent} aria-label={t('network.quotaProgress', { percent: Math.round(usage.percent) })}></progress>
                      <span>{t('network.quotaUsed', { used: usage.used, limit: usage.limit })}</span>
                      <span>{t('network.quotaReset', { date: usage.resetDate })}</span>
                    </div>
                  {:else}
                    <span>{t('network.quotaUnavailable')}</span>
                  {/if}
                {/if}
              </td>
            </tr>
          {:else}
            <tr><td colspan="3" class="empty">{t('empty.searchProviders')}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<div class="section"><div class="section-header"><h2>{t('section.searchTest')}</h2></div><div class="provider-card search-test-card" style="max-width:560px"><div class="search-test-query">{t('label.searchTestQuery')}</div><button class="btn btn-primary btn-sm" disabled={testing} onclick={() => void testSearch()}>{testing ? t('status.testing') : t('btn.test')}</button><div class="search-test-response" aria-live="polite"><div class="form-label">{t('label.searchTestResponse')}</div>{#if testError}<pre class="test-output search-test-error" role="alert">{testError}</pre>{:else if testResult}<pre class="test-output">{testResult}</pre>{:else}<div class="search-test-placeholder">{t('label.searchTestEmpty')}</div>{/if}</div></div></div>
<div class="section"><div class="section-header"><h2>{t('section.advancedSearch')}</h2></div><div class="provider-card" style="max-width:560px"><div class="form-group"><div class="form-label">{t('label.sidecarService')}</div><span class="badge" class:badge-success={status?.service_online} class:badge-error={status && !status.service_online}>{status === null ? t('status.checking') : status.service_online ? t('status.online') : status.configured === false ? t('status.notConfigured') : t('status.offline')}</span></div><div class="form-group"><div class="form-label">{t('label.sidecarBrowser')}</div><span class="badge" class:badge-success={status?.browser_ready} class:badge-error={status?.service_online && !status.browser_ready}>{status === null ? t('status.unknown') : status.browser_ready ? t('status.ready') : status?.service_online ? t('status.notReady') : t('status.unknown')}</span></div>{#if status?.error}<div style="font-size:11px;color:var(--text-dim)">{status.error}</div>{/if}</div></div>

<style>
  .network-search-section{width:100%}.search-actions{display:flex;align-items:center;gap:8px}.provider-limit{color:var(--text-dim);font-size:12px}.loading-text{color:var(--text-dim)}.search-provider-table table{table-layout:fixed}.search-provider-table th:nth-child(1){width:38%}.search-provider-table th:nth-child(2){width:42%}.search-provider-table th:nth-child(3){width:20%}.search-provider-table td{vertical-align:middle}.search-provider-table tr.dragging{opacity:.45}.row-order-controls{display:inline-flex;align-items:center;vertical-align:middle}.search-name-cell>.provider-type{width:calc(100% - 150px)}.search-name-cell>select:not(.provider-type){width:calc(100% - 150px);margin:8px 68px 0 82px}.remove-row{float:right}.search-config-cell>input,.search-config-cell>select{width:100%}.drag-handle,.order-button{border:0;background:transparent;color:var(--text-dim);cursor:pointer;padding:4px;font:inherit}.drag-handle{cursor:grab}.drag-handle:active{cursor:grabbing}.order-button:disabled{cursor:default;opacity:.3}.search-quota-cell{color:var(--text-dim)}.quota-usage{display:grid;gap:3px;font-size:11px}.quota-usage progress{width:100%;height:8px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.search-test-card{display:grid;gap:12px;justify-items:start}.search-test-query{font-family:var(--mono);font-size:13px}.search-test-response{width:100%}.search-test-placeholder{padding:12px;border:1px dashed var(--border);border-radius:var(--radius);color:var(--text-dim);font-size:12px}.search-test-error{border-color:var(--red);color:var(--red)}
  @media(max-width:760px){.section-header{align-items:flex-start}.search-actions{flex-wrap:wrap;justify-content:flex-end}.search-provider-table{overflow-x:auto}.search-provider-table table{min-width:760px}}
</style>
