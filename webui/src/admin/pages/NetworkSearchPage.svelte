<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, api, request } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import { createSerialPoll } from '../lib/polling';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';
  import { SortableTableEnhanced, type SortableTableRowColorPreset } from '@ibobbyts/svelte-ui-utils/sortable-table';

  type SearchProviderType =
    | 'tavily'
    | 'configured_responses_provider'
    | 'deepseek_native_responses'
    | 'self_hosted_google'
    | 'self_hosted_bing'
    | 'self_hosted_bing_browser';
  type SearchRow = {
    id: string;
    provider: SearchProviderType;
    tavily_api_key?: string;
    responses_provider?: string;
    responses_model?: string;
    deepseek_provider?: string;
  };
  type Provider = { api_type?: string; enabled?: boolean };
  type SearchContract = {
    provider_types?: SearchProviderType[];
    responses_models?: string[];
    deepseek_providers?: string[];
    max_providers?: number;
    configured_providers?: SearchProviderContract[];
    chain?: SearchChainContract;
  };
  type SearchProviderContract = {
    id: string;
    provider: SearchProviderType;
    family: 'gpt_passthrough' | 'tavily_local' | 'self_hosted_local' | 'deepseek_native_responses';
    execution_mode: 'alpha_search_passthrough' | 'local_query_adapter' | 'native_responses_hosted_search';
    capabilities: string[];
  };
  type SearchChainContract = {
    mode: 'unconfigured' | 'full_gpt_passthrough' | 'local_query_adapter' | 'mixed_single_query';
    capabilities: string[];
    limitations: string[];
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
    current_provider_id?: string | null;
    providers?: RoutingEntry[];
  };
  type RoutingEntry = {
    id: string;
    status: 'available' | 'cooling' | 'exhausted';
    current: boolean;
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
  let deepseekProviders = $state<string[]>([]);
  let maxProviders = $state(0);
  let chainContract = $state<SearchChainContract | null>(null);
  let contractsCurrent = $state(false);
  let status = $state<Status | null>(null);
  let usageById = $state<Map<string, UsageEntry>>(new Map());
  let usageLoading = $state(true);
  let loading = $state(true);
  let saving = $state(false);
  let selectingCurrentId = $state<string | null>(null);
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
    rows.some((row) => (
      (row.provider === 'configured_responses_provider' && !row.responses_provider)
      || (row.provider === 'deepseek_native_responses' && !row.deepseek_provider)
    )),
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
    deepseek_native_responses: t('network.provider.deepseekNativeResponses'),
    self_hosted_google: t('network.provider.google'),
    self_hosted_bing: t('network.provider.bingRss'),
    self_hosted_bing_browser: t('network.provider.bingBrowser'),
  })[value];
  const chainDescription = (): string => {
    if (!contractsCurrent || !chainContract) return '';
    return t(`network.chain.${chainContract.mode}`);
  };
  const routingEntry = (id: string): RoutingEntry | undefined =>
    status?.providers?.find((entry) => entry.id === id);
  const routingLabel = (entry: RoutingEntry): string =>
    t(`network.routing.${entry.status}`);
  const currentProviderId = $derived(status?.current_provider_id ?? null);
  const currentDisabled = (row: SearchRow): boolean => {
    const entry = routingEntry(row.id);
    return selectingCurrentId !== null || !entry || entry.status === 'exhausted';
  };
  const rowColorPreset = (row: SearchRow): SortableTableRowColorPreset | null => {
    const entry = routingEntry(row.id);
    if (!entry) return null;
    if (entry.status === 'exhausted') return 'red';
    if (entry.status === 'cooling') return 'yellow';
    return 'green';
  };

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
    if (provider === 'deepseek_native_responses') {
      return { id, provider, deepseek_provider: deepseekProviders[0] ?? '' };
    }
    return { id, provider };
  }

  function replaceRow(id: string, update: (row: SearchRow) => SearchRow): void {
    if (saving) return;
    rows = rows.map((row) => row.id === id ? update(row) : row);
    contractsCurrent = false;
  }

  function changeType(id: string, provider: SearchProviderType): void {
    replaceRow(id, (row) => rowForType(row.id, provider));
  }

  function addRow(): void {
    if (saving) return;
    if (rows.length >= maxProviders) return;
    const provider = providerTypes[0];
    if (!provider) return;
    rows = [...rows, rowForType(createId(), provider)];
    contractsCurrent = false;
  }

  function removeRow(id: string): void {
    if (saving) return;
    rows = rows.filter((row) => row.id !== id);
    contractsCurrent = false;
  }

  function reorderRows(next: SearchRow[]): void {
    if (saving) return;
    rows = next;
    contractsCurrent = false;
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
      if (row.provider === 'deepseek_native_responses') {
        return {
          id: row.id,
          provider: row.provider,
          deepseek_provider: row.deepseek_provider ?? '',
        };
      }
      return { id: row.id, provider: row.provider };
    });
  }

  async function loadConfig(signal: AbortSignal): Promise<void> {
    try {
      const config = await api.get<Config>('/admin/api/config', signal);
      applyConfig(config);
      error = '';
    } catch (cause) {
      if (!aborted(cause)) error = message(cause);
    } finally {
      loading = false;
    }
  }

  function applyConfig(config: Config): void {
    const nextRows = (config.server?.web_search?.providers ?? []).map((row) => ({ ...row }));
    const nextChainContract = config.web_search_contract?.chain ?? null;
    providers = config.providers ?? {};
    providerTypes = config.web_search_contract?.provider_types ?? [];
    responsesModels = config.web_search_contract?.responses_models ?? [];
    deepseekProviders = config.web_search_contract?.deepseek_providers ?? [];
    maxProviders = config.web_search_contract?.max_providers ?? 0;
    rows = nextRows;
    chainContract = nextChainContract;
    contractsCurrent = true;
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

  async function selectCurrent(row: SearchRow): Promise<void> {
    const entry = routingEntry(row.id);
    if (!entry || entry.current || entry.status === 'exhausted' || selectingCurrentId) return;
    selectingCurrentId = row.id;
    error = '';
    try {
      await api.put('/admin/api/network-search/status', { current_provider_id: row.id });
      status = {
        ...status,
        current_provider_id: row.id,
        providers: status?.providers?.map((item) => ({
          ...item,
          current: item.id === row.id,
          status: item.id === row.id ? 'available' : item.status,
        })),
      };
    } catch (cause) {
      error = message(cause);
    } finally {
      selectingCurrentId = null;
    }
  }

  const poll = createSerialPoll(loadStatus, 5000);

  async function save(): Promise<void> {
    if (saving) return;
    saving = true;
    error = '';
    notice = '';
    let saved = false;
    try {
      await api.put<{ server?: { web_search?: { providers?: SearchRow[] } } }>(
        '/admin/api/config/server',
        { web_search: { providers: canonicalRows() } },
      );
      const config = await api.get<Config>('/admin/api/config');
      applyConfig(config);
      notice = t('toast.networkSearchSaved');
      saved = true;
    } catch (cause) {
      error = message(cause);
    } finally {
      saving = false;
    }
    if (saved) void poll.runNow();
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
    void loadUsage(controller.signal).then(() => {
      if (!controller.signal.aborted) poll.start();
    });
    return () => { controller.abort(); testController?.abort(); poll.stop(); };
  });
</script>

<div class="section network-search-section">
  <div class="section-header">
    <h2>{t('section.basicSearch')}</h2>
    <div class="search-actions">
      <span class="provider-limit">{t('network.providerCount', { count: rows.length, max: maxProviders })}</span>
      <button class="btn btn-sm" disabled={loading || saving || rows.length >= maxProviders || !providerTypes.length} onclick={addRow}>{t('btn.addSearchProvider')}</button>
      <button class="btn btn-primary btn-sm" disabled={loading || saving || hasInvalidResponses} onclick={() => void save()}>{t('btn.save')}</button>
    </div>
  </div>
  <p class="chain-help">{t('network.chain.help')}</p>
  {#if chainDescription()}<p class="chain-contract" data-chain-mode={chainContract?.mode}>{chainDescription()}</p>{/if}
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}
  {#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  {#if loading}
    <p class="loading-text">{t('loading.networkSearch')}</p>
  {:else}
      {#if rows.length}
      <div class="table-scroll search-provider-table">
          <SortableTableEnhanced
            items={rows}
            disabled={saving}
            onReorder={reorderRows}
            onRemove={(item) => removeRow(item.id)}
            allowRemoveLast={true}
            tableClass="search-provider-table__table"
            currentId={currentProviderId}
            getCurrentDisabled={currentDisabled}
            getCurrentLabel={(row) => t('aria.selectCurrentProvider', { provider: providerLabel(row.provider) })}
            getRowColorPreset={rowColorPreset}
            onCurrentChange={(row) => void selectCurrent(row)}
          >
          {#snippet header()}
            <th>{t('col.searchName')}</th><th>{t('col.searchConfiguration')}</th><th>{t('col.status')}</th><th>{t('col.searchQuota')}</th>
          {/snippet}
          {#snippet children(row, _index)}
            {@const routing = routingEntry(row.id)}
            {@const usage = displayUsage(row.id)}
            <td class="search-name-cell">
              <div class="search-name-content">
                <label class="sr-only" for={`search-provider-type-${row.id}`}>{t('label.searchProviderType')}</label>
                <Dropdown id={`search-provider-type-${row.id}`} value={row.provider} disabled={saving} options={providerTypes.map((type)=>({value:type,label:providerLabel(type)}))} fitViewport={true} onChange={(value:DropdownValue)=>changeType(row.id,String(value) as SearchProviderType)} />
                {#if row.provider === 'configured_responses_provider'}
                  <label class="sr-only" for={`responses-provider-${row.id}`}>{t('label.responsesSearchProvider')}</label>
                  <Dropdown id={`responses-provider-${row.id}`} ariaLabel={t('label.responsesSearchProvider')} value={row.responses_provider ?? ''} disabled={saving || !responsesProviders.length} options={responsesProviders.length ? responsesProviders.map((name)=>({value:name,label:name})) : [{value:'',label:t('network.provider.noResponses') }]} fitViewport={true} onChange={(value:DropdownValue)=>replaceRow(row.id,(item)=>({...item,responses_provider:String(value)}))} />
                {:else if row.provider === 'deepseek_native_responses'}
                  <label class="sr-only" for={`deepseek-provider-${row.id}`}>{t('label.deepseekSearchProvider')}</label>
                  <Dropdown id={`deepseek-provider-${row.id}`} ariaLabel={t('label.deepseekSearchProvider')} value={row.deepseek_provider ?? ''} disabled={saving || !deepseekProviders.length} options={deepseekProviders.length ? deepseekProviders.map((name)=>({value:name,label:name})) : [{value:'',label:t('network.provider.noDeepSeek') }]} fitViewport={true} onChange={(value:DropdownValue)=>replaceRow(row.id,(item)=>({...item,deepseek_provider:String(value)}))} />
                {/if}
              </div>
            </td>
            <td class="search-config-cell">
              {#if row.provider === 'tavily'}
                <label class="sr-only" for={`tavily-key-${row.id}`}>{t('label.searchApiKey')}</label>
                <input id={`tavily-key-${row.id}`} aria-label={t('label.searchApiKey')} type="password" autocomplete="new-password" value={row.tavily_api_key ?? ''} placeholder={t('label.searchApiKeyPlaceholder')} disabled={saving} oninput={(event) => replaceRow(row.id, (item) => ({ ...item, tavily_api_key: event.currentTarget.value }))} />
              {:else if row.provider === 'configured_responses_provider'}
                <label class="sr-only" for={`responses-model-${row.id}`}>{t('label.responsesSearchModel')}</label>
                <Dropdown id={`responses-model-${row.id}`} ariaLabel={t('label.responsesSearchModel')} value={row.responses_model ?? ''} disabled={saving} options={responsesModels.map((name)=>({value:name,label:name}))} fitViewport={true} onChange={(value:DropdownValue)=>replaceRow(row.id,(item)=>({...item,responses_model:String(value)}))} />
              {:else if row.provider === 'deepseek_native_responses'}
                <span class="fixed-search-model" aria-label={t('label.deepseekSearchModel')}>{t('network.provider.deepseekModel')}</span>
              {:else}<span aria-label={t('network.noConfiguration')}>—</span>{/if}
            </td>
            <td class="search-status-cell">
              {#if routing}
                <span class={`routing-status routing-status-${routing.status}`}>{routingLabel(routing)}</span>
              {/if}
            </td>
            <td class="search-quota-cell search-remove-cell">
              {#if row.provider === 'tavily'}
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
          {/snippet}
          </SortableTableEnhanced>
      </div>
      {:else}
      <div class="table-scroll search-provider-table">
        <table>
          <thead><tr><th>{t('col.searchName')}</th><th>{t('col.searchConfiguration')}</th><th>{t('col.status')}</th><th>{t('col.searchQuota')}</th></tr></thead>
          <tbody><tr><td colspan="4" class="empty">{t('empty.searchProviders')}</td></tr></tbody>
        </table>
      </div>
      {/if}
  {/if}
</div>

<div class="section"><div class="section-header"><h2>{t('section.searchTest')}</h2></div><div class="provider-card search-test-card" style="max-width:560px"><div class="search-test-query">{t('label.searchTestQuery')}</div><button class="btn btn-primary btn-sm" disabled={testing} onclick={() => void testSearch()}>{testing ? t('status.testing') : t('btn.test')}</button><div class="search-test-response" aria-live="polite"><div class="form-label">{t('label.searchTestResponse')}</div>{#if testError}<pre class="test-output search-test-error" role="alert">{testError}</pre>{:else if testResult}<pre class="test-output">{testResult}</pre>{:else}<div class="search-test-placeholder">{t('label.searchTestEmpty')}</div>{/if}</div></div></div>
<div class="section"><div class="section-header"><h2>{t('section.advancedSearch')}</h2></div><div class="provider-card" style="max-width:560px"><div class="form-group"><div class="form-label">{t('label.sidecarService')}</div><span class="badge" class:badge-success={status?.service_online} class:badge-error={status && !status.service_online}>{status === null ? t('status.checking') : status.service_online ? t('status.online') : status.configured === false ? t('status.notConfigured') : t('status.offline')}</span></div><div class="form-group"><div class="form-label">{t('label.sidecarBrowser')}</div><span class="badge" class:badge-success={status?.browser_ready} class:badge-error={status?.service_online && !status.browser_ready}>{status === null ? t('status.unknown') : status.browser_ready ? t('status.ready') : status?.service_online ? t('status.notReady') : t('status.unknown')}</span></div>{#if status?.error}<div style="font-size:11px;color:var(--text-dim)">{status.error}</div>{/if}</div></div>

<style>
  .network-search-section{width:100%}.search-actions{display:flex;align-items:center;gap:8px}.provider-limit,.chain-contract{color:var(--text-dim);font-size:12px}.chain-contract{margin:-4px 0 12px}.loading-text{color:var(--text-dim)}.search-provider-table :global(.suu-sortable-table){table-layout:fixed}.search-provider-table :global(th:nth-child(2)){width:34%}.search-provider-table :global(th:nth-child(3)){width:36%}.search-provider-table :global(th:nth-child(4)){width:14%}.search-provider-table :global(th:nth-child(5)){width:16%}.search-provider-table td{vertical-align:middle}.search-config-cell>input,.search-config-cell>:global(.suu-dropdown),.search-config-cell>:global(.suu-dropdown__button){width:100%}.fixed-search-model{display:block;padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius);color:var(--text-dim);font-family:var(--mono);font-size:12px}.search-quota-cell{color:var(--text-dim)}.search-remove-cell{text-align:right}.quota-usage{display:grid;gap:3px;font-size:11px}.quota-usage progress{width:100%;height:8px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.search-test-card{display:grid;gap:12px;justify-items:start}.search-test-query{font-family:var(--mono);font-size:13px}.search-test-response{width:100%}.search-test-placeholder{padding:12px;border:1px dashed var(--border);border-radius:var(--radius);color:var(--text-dim);font-size:12px}.search-test-error{border-color:var(--red);color:var(--red)}
  .search-name-cell{min-width:0}.search-name-content{display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-width:0}.search-name-content>:global(.provider-type){flex:1 1 260px;width:auto;min-width:220px}.search-name-content>:global(.suu-dropdown:not(.provider-type)){flex:1 1 240px;width:auto;min-width:220px;margin:0}.search-name-content :global(.suu-dropdown__button){width:100%;max-width:100%}.search-name-content :global(.suu-dropdown__button > span:first-child){min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .search-status-cell{white-space:nowrap}.routing-status{font-size:11px;font-weight:600}.routing-status-available{color:var(--green)}.routing-status-cooling{color:var(--orange)}.routing-status-exhausted{color:var(--red)}
  @media(max-width:760px){.section-header{align-items:flex-start}.search-actions{flex-wrap:wrap;justify-content:flex-end}.search-provider-table{overflow:visible}}
</style>
