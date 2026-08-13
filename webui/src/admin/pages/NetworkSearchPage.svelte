<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError, api, request } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import { createSerialPoll } from '../lib/polling';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';
  import OrderedListEditor, { type OrderedListItem } from '../components/OrderedListEditor.svelte';

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
  let providerContracts = $state<SearchProviderContract[]>([]);
  let chainContract = $state<SearchChainContract | null>(null);
  let contractsCurrent = $state(false);
  let draggedId = $state<string | null>(null);
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
  const orderedRows = $derived(rows.map((row):OrderedListItem=>({id:row.id})));

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
  const providerDescription = (contract: SearchProviderContract): string => {
    const contractKey = `${contract.family}:${contract.execution_mode}`;
    const descriptionKey: Record<string, string> = {
      'gpt_passthrough:alpha_search_passthrough': 'network.provider.gptDescription',
      'tavily_local:local_query_adapter': 'network.provider.tavilyDescription',
      'self_hosted_local:local_query_adapter': 'network.provider.selfHostedDescription',
      'deepseek_native_responses:native_responses_hosted_search': 'network.provider.deepseekDescription',
    };
    const key = descriptionKey[contractKey];
    return key ? t(key) : '';
  };
  const capabilityLabel = (value: string): string => t(`network.capability.${value}`);
  const rowContract = (id: string): SearchProviderContract | undefined =>
    contractsCurrent ? providerContracts.find((contract) => contract.id === id) : undefined;
  const chainDescription = (): string => {
    if (!contractsCurrent || !chainContract) return '';
    return t(`network.chain.${chainContract.mode}`);
  };
  const routingEntry = (id: string): RoutingEntry | undefined =>
    status?.providers?.find((entry) => entry.id === id);
  const routingLabel = (entry: RoutingEntry): string =>
    t(`network.routing.${entry.status}`);

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

  function moveRow(id: string, offset: -1 | 1): void {
    if (saving) return;
    const index = rows.findIndex((row) => row.id === id);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= rows.length) return;
    const next = [...rows];
    [next[index], next[target]] = [next[target], next[index]];
    rows = next;
    contractsCurrent = false;
  }

  function moveToTargetIndex(sourceId: string, targetId: string): void {
    if (saving) return;
    if (sourceId === targetId) return;
    const sourceIndex = rows.findIndex((row) => row.id === sourceId);
    const targetIndex = rows.findIndex((row) => row.id === targetId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    // A dropped row occupies the target row's pre-drop index in either direction.
    const next = [...rows];
    const [source] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, source);
    rows = next;
    contractsCurrent = false;
  }

  function startDrag(event: DragEvent, id: string): void {
    if (saving) {
      event.preventDefault();
      draggedId = null;
      return;
    }
    draggedId = id;
    event.dataTransfer?.setData('text/plain', id);
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
  }

  function dropRow(event: DragEvent, targetId: string): void {
    event.preventDefault();
    if (saving) {
      draggedId = null;
      return;
    }
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
    const nextProviderContracts = config.web_search_contract?.configured_providers ?? [];
    const nextChainContract = config.web_search_contract?.chain ?? null;
    providers = config.providers ?? {};
    providerTypes = config.web_search_contract?.provider_types ?? [];
    responsesModels = config.web_search_contract?.responses_models ?? [];
    deepseekProviders = config.web_search_contract?.deepseek_providers ?? [];
    maxProviders = config.web_search_contract?.max_providers ?? 0;
    rows = nextRows;
    providerContracts = nextProviderContracts;
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
    draggedId = null;
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
    <div class="table-scroll search-provider-table">
      <table>
        <thead><tr><th>{t('col.searchName')}</th><th>{t('col.searchConfiguration')}</th><th>{t('col.searchQuota')}</th></tr></thead>
        <tbody>
          {#each rows as row, index (row.id)}
            {@const contract = rowContract(row.id)}
            {@const routing = routingEntry(row.id)}
            <tr data-row-id={row.id} class:dragging={draggedId === row.id} class:routing-available={routing?.status === 'available'} class:routing-cooling={routing?.status === 'cooling'} class:routing-exhausted={routing?.status === 'exhausted'} ondragover={(event) => { if (!saving) event.preventDefault(); }} ondrop={(event) => dropRow(event, row.id)}>
              <td class="search-name-cell">
                <div class="row-order-controls">
                  <button class="drag-handle" draggable={!saving} disabled={saving} aria-label={t('aria.dragSearchProvider')} title={t('aria.dragSearchProvider')} ondragstart={(event) => startDrag(event, row.id)} ondragend={() => draggedId = null}>⋮⋮</button>
                  <OrderedListEditor items={orderedRows} renderId={row.id} disabled={saving} compact onmove={moveRow} moveUpLabel={()=>t('aria.moveSearchProviderUp')} moveDownLabel={()=>t('aria.moveSearchProviderDown')} />
                </div>
                <label class="sr-only" for={`search-provider-type-${row.id}`}>{t('label.searchProviderType')}</label>
                <Dropdown id={`search-provider-type-${row.id}`} value={row.provider} disabled={saving} options={providerTypes.map((type)=>({value:type,label:providerLabel(type)}))} fitViewport={true} onChange={(value:DropdownValue)=>changeType(row.id,String(value) as SearchProviderType)} />
                {#if row.provider === 'configured_responses_provider'}
                  <label class="sr-only" for={`responses-provider-${row.id}`}>{t('label.responsesSearchProvider')}</label>
                  <Dropdown id={`responses-provider-${row.id}`} ariaLabel={t('label.responsesSearchProvider')} value={row.responses_provider ?? ''} disabled={saving || !responsesProviders.length} options={responsesProviders.length ? responsesProviders.map((name)=>({value:name,label:name})) : [{value:'',label:t('network.provider.noResponses') }]} fitViewport={true} onChange={(value:DropdownValue)=>replaceRow(row.id,(item)=>({...item,responses_provider:String(value)}))} />
                {:else if row.provider === 'deepseek_native_responses'}
                  <label class="sr-only" for={`deepseek-provider-${row.id}`}>{t('label.deepseekSearchProvider')}</label>
                  <Dropdown id={`deepseek-provider-${row.id}`} ariaLabel={t('label.deepseekSearchProvider')} value={row.deepseek_provider ?? ''} disabled={saving || !deepseekProviders.length} options={deepseekProviders.length ? deepseekProviders.map((name)=>({value:name,label:name})) : [{value:'',label:t('network.provider.noDeepSeek') }]} fitViewport={true} onChange={(value:DropdownValue)=>replaceRow(row.id,(item)=>({...item,deepseek_provider:String(value)}))} />
                {/if}
                {#if routing}
                  <span class={`routing-status routing-status-${routing.status}`}>{routingLabel(routing)}</span>
                  {#if routing.current}
                    <span class="current-provider">{t('network.routing.current')}</span>
                  {:else}
                    <button class="btn btn-sm current-provider-selector" aria-label={t('aria.selectCurrentProvider', { provider: providerLabel(row.provider) })} disabled={saving || selectingCurrentId !== null || routing.status === 'exhausted'} onclick={() => void selectCurrent(row)}>{t('network.routing.select')}</button>
                  {/if}
                {/if}
                <button class="btn btn-sm btn-danger remove-row" disabled={saving} onclick={() => removeRow(row.id)}>{t('btn.remove')}</button>
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
                {#if contract}
                  <div class="provider-contract" data-provider-family={contract.family}>
                    {#if providerDescription(contract)}<span>{providerDescription(contract)}</span>{/if}
                    {#if contract.capabilities.length}
                      <span>{t('network.capabilities', { capabilities: contract.capabilities.map(capabilityLabel).join(', ') })}</span>
                    {/if}
                  </div>
                {/if}
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
  .network-search-section{width:100%}.search-actions{display:flex;align-items:center;gap:8px}.provider-limit,.chain-contract{color:var(--text-dim);font-size:12px}.chain-contract{margin:-4px 0 12px}.loading-text{color:var(--text-dim)}.search-provider-table table{table-layout:fixed}.search-provider-table th:nth-child(1){width:38%}.search-provider-table th:nth-child(2){width:42%}.search-provider-table th:nth-child(3){width:20%}.search-provider-table td{vertical-align:middle}.search-provider-table tr.dragging{opacity:.45}.row-order-controls{display:inline-flex;align-items:center;vertical-align:middle}.search-config-cell>input,.search-config-cell>:global(.suu-dropdown),.search-config-cell>:global(.suu-dropdown__button){width:100%}.fixed-search-model{display:block;padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius);color:var(--text-dim);font-family:var(--mono);font-size:12px}.drag-handle,.order-button{border:0;background:transparent;color:var(--text-dim);cursor:pointer;padding:4px;font:inherit}.drag-handle{cursor:grab}.drag-handle:active{cursor:grabbing}.order-button:disabled{cursor:default;opacity:.3}.search-quota-cell{color:var(--text-dim)}.quota-usage{display:grid;gap:3px;font-size:11px}.quota-usage progress{width:100%;height:8px}.provider-contract{display:grid;gap:2px;margin-top:6px;color:var(--text-dim);font-size:11px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.search-test-card{display:grid;gap:12px;justify-items:start}.search-test-query{font-family:var(--mono);font-size:13px}.search-test-response{width:100%}.search-test-placeholder{padding:12px;border:1px dashed var(--border);border-radius:var(--radius);color:var(--text-dim);font-size:12px}.search-test-error{border-color:var(--red);color:var(--red)}
  .search-name-cell{display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-width:0}.search-name-cell .row-order-controls{flex:0 0 auto}.search-name-cell>:global(.provider-type){flex:1 1 260px;width:auto;min-width:220px}.search-name-cell>:global(.suu-dropdown:not(.provider-type)){flex:1 1 240px;width:auto;min-width:220px;margin:0}.search-name-cell .remove-row{margin-left:auto}.search-name-cell :global(.suu-dropdown__button){width:100%;max-width:100%}.search-name-cell :global(.suu-dropdown__button > span:first-child){min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .search-provider-table tr.routing-available>td{background:color-mix(in srgb,var(--green) 10%,transparent)}.search-provider-table tr.routing-cooling>td{background:color-mix(in srgb,var(--orange) 12%,transparent)}.search-provider-table tr.routing-exhausted>td{background:color-mix(in srgb,var(--red) 12%,transparent)}.routing-status,.current-provider{font-size:11px;font-weight:600}.routing-status-available{color:var(--green)}.routing-status-cooling{color:var(--orange)}.routing-status-exhausted{color:var(--red)}.current-provider{color:var(--accent)}
  @media(max-width:760px){.section-header{align-items:flex-start}.search-actions{flex-wrap:wrap;justify-content:flex-end}.search-provider-table{overflow:visible}}
</style>
