// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardPage from '../src/admin/pages/DashboardPage.svelte';
import GatewayLogsPage from '../src/admin/pages/GatewayLogsPage.svelte';
import NetworkSearchPage from '../src/admin/pages/NetworkSearchPage.svelte';
import RequestLogsPage from '../src/admin/pages/RequestLogsPage.svelte';
import ToolsPage from '../src/admin/pages/ToolsPage.svelte';
import { ApiError } from '../src/admin/lib/api';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
}));
const downloadMock = vi.hoisted(() => vi.fn());
const requestMock = vi.hoisted(() => vi.fn());
vi.mock('../src/admin/lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../src/admin/lib/api')>(),
  api: apiMock,
  download: downloadMock,
  request: requestMock,
}));

async function chooseDropdown(control: HTMLElement, value: string): Promise<void> {
  await fireEvent.click(control);
  const option = within(control.parentElement!).getAllByRole('option').find((item) => item.getAttribute('data-value') === value);
  expect(option).toBeDefined();
  await fireEvent.click(option!);
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.post.mockResolvedValue({ ok: true });
  apiMock.put.mockResolvedValue({ ok: true });
  apiMock.del.mockResolvedValue({ ok: true });
  requestMock.mockResolvedValue({ ok: true });
});
afterEach(() => vi.useRealTimers());

describe('DashboardPage', () => {
  it('loads metrics and enables profiling with a bounded request count', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith('/admin/api/metrics')) return Promise.resolve({ total_requests: 12, error_rate: 0.25, active_streams: 1, uptime_seconds: 90, by_target_provider: { openai: 12 } });
      if (path.endsWith('/status')) return Promise.resolve({ enabled: false, remaining: 0 });
      return Promise.resolve({ results: [] });
    });
    render(DashboardPage);
    expect(await screen.findByText('Total requests')).toBeInTheDocument();
    expect(screen.getAllByText('12')).toHaveLength(2);
    const count = screen.getByLabelText('Requests');
    await fireEvent.input(count, { target: { value: '500' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Enable' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/admin/api/profiling/enable', { requests: 100 }));
  });

  it('downloads profiling results through the registered backend route', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith('/admin/api/metrics')) return Promise.resolve({ total_requests: 1 });
      if (path.endsWith('/status')) return Promise.resolve({ enabled: false, remaining: 0 });
      return Promise.resolve({ results: [{ timestamp: '2026-01-01T00:00:00Z', model: 'gpt-test' }] });
    });
    downloadMock.mockResolvedValue(new Blob(['zip']));
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    render(DashboardPage);
    await screen.findByText('gpt-test');
    await fireEvent.click(screen.getByRole('button', { name: 'Download all' }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledWith('/admin/api/profiling/results/download'));
    createObjectURL.mockRestore();
    revokeObjectURL.mockRestore();
  });
});

describe('RequestLogsPage', () => {
  it('renders a page and clears logs after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    apiMock.get.mockImplementation((path: string) => path.includes('key-labels')
      ? Promise.resolve({ labels: ['Primary'] })
      : Promise.resolve({ entries: [{ timestamp: '2026-01-01T00:00:00Z', model: 'gpt-test', status_code: 200, duration_ms: 8 }], total: 1 }));
    render(RequestLogsPage);
    expect(await screen.findByText('gpt-test')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Clear logs' }));
    await waitFor(() => expect(apiMock.del).toHaveBeenCalledWith('/admin/api/requests'));
  });
});

describe('GatewayLogsPage', () => {
  it('normalizes and saves stream trace settings', async () => {
    apiMock.get.mockResolvedValue({ server: { stream_trace: { enabled: false, max_string_chars: 20000 } } });
    apiMock.put.mockResolvedValue({ server: { stream_trace: { enabled: true, path: '', filter: '', max_string_chars: 20000 } } });
    render(GatewayLogsPage);
    const checkbox = await screen.findByLabelText('Enable stream trace JSONL');
    await waitFor(() => expect(checkbox).not.toBeDisabled());
    await fireEvent.click(checkbox);
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', { stream_trace: { enabled: true, path: '', filter: '', max_string_chars: 20000 } });
  });
});

describe('NetworkSearchPage', () => {
  const contract = {
    provider_types: ['tavily', 'configured_responses_provider', 'deepseek_native_responses', 'self_hosted_google', 'self_hosted_bing', 'self_hosted_bing_browser'],
    responses_models: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
    deepseek_providers: [],
    max_providers: 32,
  };

  const configResponse = (
    rows: Array<Record<string, string | undefined>> = [],
    providers: Record<string, unknown> = {},
    savedContract: Record<string, unknown> = {
      configured_providers: [],
      chain: { mode: 'unconfigured', capabilities: [], limitations: [] },
    },
  ) => {
    return {
      providers,
      web_search_contract: { ...contract, ...savedContract },
      server: { web_search: { providers: rows } },
    };
  };

  function mockConfig(value: ReturnType<typeof configResponse>, usage: Record<string, unknown> = { entries: [] }): void {
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/config')) return Promise.resolve(value);
      if (path.endsWith('/usage')) return Promise.resolve(usage);
      return Promise.resolve({ configured: false });
    });
  }

  function transfer(): { value: string; effectAllowed: string; setData: (_type: string, value: string) => void; getData: () => string } {
    return {
      value: '',
      effectAllowed: 'none',
      setData(_type: string, value: string) { this.value = value; },
      getData() { return this.value; },
    };
  }

  function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (reason?: unknown) => void } {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
    return { promise, resolve, reject };
  }

  it('loads and saves a canonical multi-row chain without changing order, IDs, or masked keys', async () => {
    const rows = [
      { id: 'tavily-a', provider: 'tavily', tavily_api_key: 'tav***key' },
      { id: 'responses-b', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      { id: 'local-c', provider: 'self_hosted_google' },
    ];
    mockConfig(configResponse(rows, { search: { api_type: 'responses' } }));
    apiMock.put.mockResolvedValue(configResponse(rows).server);
    render(NetworkSearchPage);
    expect(await screen.findByDisplayValue('tav***key')).toBeInTheDocument();
    expect(screen.getByText(/Requests start with the current provider/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', { web_search: { providers: rows } });
    const body = apiMock.put.mock.calls[0][1] as { web_search: Record<string, unknown> };
    expect(Object.keys(body.web_search)).toEqual(['providers']);
    expect(body.web_search).not.toHaveProperty('provider');
    expect(body.web_search).not.toHaveProperty('tavily_api_key');
  });

  it('renders current routing state and permits cooling but not exhausted selection', async () => {
    const rows = [
      { id: 'available', provider: 'self_hosted_google' },
      { id: 'cooling', provider: 'self_hosted_bing' },
      { id: 'exhausted', provider: 'tavily', tavily_api_key: 'masked***key' },
    ];
    const config = configResponse(rows);
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/config')) return Promise.resolve(config);
      if (path.endsWith('/usage')) return Promise.resolve({ entries: [] });
      return Promise.resolve({
        configured: false,
        current_provider_id: 'available',
        providers: [
          { id: 'available', status: 'available', current: true },
          { id: 'cooling', status: 'cooling', current: false },
          { id: 'exhausted', status: 'exhausted', current: false },
        ],
      });
    });
    apiMock.put.mockResolvedValue({ ok: true, current_provider_id: 'cooling' });
    render(NetworkSearchPage);

    await waitFor(() => expect(document.querySelector('tr[data-sortable-id="available"]')).not.toBeNull());
    const available = document.querySelector<HTMLElement>('tr[data-sortable-id="available"]')!;
    const cooling = document.querySelector<HTMLElement>('tr[data-sortable-id="cooling"]')!;
    const exhausted = document.querySelector<HTMLElement>('tr[data-sortable-id="exhausted"]')!;
    await waitFor(() => expect(available).toHaveClass('routing-available'));
    expect(cooling).toHaveClass('routing-cooling');
    expect(exhausted).toHaveClass('routing-exhausted');
    expect(within(available).getByText('Current')).toBeInTheDocument();
    expect(within(available).getByText('Available')).toBeInTheDocument();
    expect(within(cooling).getByText('Cooling')).toBeInTheDocument();
    expect(within(exhausted).getByText('Quota exhausted')).toBeInTheDocument();
    const exhaustedSelector = within(exhausted).getByRole('button', { name: 'Set Tavily as current provider' });
    expect(exhaustedSelector).toBeDisabled();
    const coolingSelector = within(cooling).getByRole('button', { name: 'Set Self-hosted (Bing RSS) as current provider' });
    expect(coolingSelector).toBeEnabled();

    await fireEvent.click(coolingSelector);

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith(
      '/admin/api/network-search/status',
      { current_provider_id: 'cooling' },
    ));
  });

  it('loads routing status after initial usage can mark a Tavily row exhausted', async () => {
    const rows = [
      { id: 'local', provider: 'self_hosted_google' },
      { id: 'tavily', provider: 'tavily', tavily_api_key: 'masked***key' },
    ];
    const usage = deferred<{ entries: Array<Record<string, unknown>> }>();
    let statusReads = 0;
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/config')) return Promise.resolve(configResponse(rows));
      if (path.endsWith('/usage')) return usage.promise;
      if (path.endsWith('/status')) {
        statusReads += 1;
        return Promise.resolve({
          configured: false,
          current_provider_id: 'local',
          providers: [
            { id: 'local', status: 'available', current: true },
            { id: 'tavily', status: 'exhausted', current: false },
          ],
        });
      }
      return Promise.resolve({});
    });
    render(NetworkSearchPage);

    await waitFor(() => expect(document.querySelector('tr[data-sortable-id="tavily"]')).not.toBeNull());
    expect(statusReads).toBe(0);

    usage.resolve({
      entries: [
        { id: 'tavily', status: 'ok', used: 100, limit: 100, reset_date: '2026-09-01' },
      ],
    });

    await waitFor(() => expect(statusReads).toBe(1));
    const row = document.querySelector<HTMLElement>('tr[data-sortable-id="tavily"]')!;
    await waitFor(() => expect(row).toHaveClass('routing-exhausted'));
    expect(within(row).getByText('Quota exhausted')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Set Tavily as current provider' })).toBeDisabled();
  });

  it.each([
    {
      name: 'Tavily',
      row: { id: 'row-0', provider: 'tavily', tavily_api_key: 'tvly***cret' },
      providers: {},
    },
    {
      name: 'Responses',
      row: { id: 'row-0', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      providers: { search: { api_type: 'responses' } },
    },
    {
      name: 'self-hosted',
      row: { id: 'row-0', provider: 'self_hosted_bing_browser' },
      providers: {},
    },
  ])('unchanged canonical save preserves the stable $name row', async ({ row, providers }) => {
    const rows = [{ ...row }];
    mockConfig(configResponse(rows, providers));
    apiMock.put.mockImplementation((_path: string, body: { web_search: { providers: Array<Record<string, string | undefined>> } }) => Promise.resolve({ server: { web_search: body.web_search } }));
    render(NetworkSearchPage);
    await waitFor(() => expect(document.querySelector('tr[data-sortable-id="row-0"]')).not.toBeNull());

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', {
      web_search: { providers: rows },
    });
    const webSearch = (apiMock.put.mock.calls[0][1] as { web_search: Record<string, unknown> }).web_search;
    expect(Object.keys(webSearch)).toEqual(['providers']);
  });

  it('renders only the controls allowed for Tavily, Responses, and self-hosted rows', async () => {
    mockConfig(configResponse([
      { id: 'tv', provider: 'tavily', tavily_api_key: 'masked***key' },
      { id: 'rp', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      { id: 'sh', provider: 'self_hosted_bing' },
    ], {
      chat: { api_type: 'chat' },
      disabled: { api_type: 'responses', enabled: false },
      search: { api_type: 'responses' },
    }));
    render(NetworkSearchPage);

    expect(await screen.findByDisplayValue('masked***key')).toHaveAttribute('type', 'password');
    expect(screen.getAllByLabelText('API Key')).toHaveLength(1);
    const responsesSelect = await screen.findByLabelText('Responses Provider');
    expect(responsesSelect).toHaveTextContent('search');
    expect(responsesSelect).not.toHaveTextContent('chat');
    expect(responsesSelect).not.toHaveTextContent('disabled');
    const modelSelect = await screen.findByLabelText('Search Model');
    expect(modelSelect).toHaveAttribute('data-value', 'gpt-5.6-terra');
    await fireEvent.click(modelSelect);
    expect(within(modelSelect.parentElement!).getAllByRole('option').map((option) => option.getAttribute('data-value'))).toEqual(contract.responses_models);
    expect(screen.getByLabelText('No configuration required')).toBeInTheDocument();
    expect(await screen.findByText('Quota unavailable')).toBeInTheDocument();
    expect(document.querySelector('tr[data-sortable-id="rp"] .search-quota-cell')).toBeEmptyDOMElement();
    expect(document.querySelector('tr[data-sortable-id="sh"] .search-quota-cell')).toBeEmptyDOMElement();
  });

  it('renders DeepSeek official rows from the contract and saves only the provider name', async () => {
    const rows = [{ id: 'deepseek-row', provider: 'deepseek_native_responses', deepseek_provider: 'official-deepseek' }];
    mockConfig(configResponse(rows, {}, {
      deepseek_providers: ['official-deepseek', 'backup-deepseek'],
      configured_providers: [{ id: 'deepseek-row', provider: 'deepseek_native_responses', family: 'deepseek_native_responses', execution_mode: 'native_responses_hosted_search', capabilities: ['search_query', 'normalized_results', 'reference_storage'] }],
      chain: { mode: 'local_query_adapter', capabilities: ['search_query', 'normalized_results', 'reference_storage'], limitations: [] },
    }));
    apiMock.put.mockResolvedValue({ server: { web_search: { providers: rows } } });
    render(NetworkSearchPage);

    const row = await screen.findByText('deepseek-v4-flash');
    expect(row).toBeInTheDocument();
    const provider = screen.getByLabelText('DeepSeek Provider');
    expect(provider).toHaveAttribute('data-value', 'official-deepseek');
    await fireEvent.click(provider);
    expect(within(provider.parentElement!).getAllByRole('option').map((option) => option.getAttribute('data-value')))
      .toEqual(['official-deepseek', 'backup-deepseek']);
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', {
      web_search: { providers: rows },
    });
    expect(screen.queryByLabelText('Search Model')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('deepseek-secret');
  });

  it('explains code-owned provider families and the mixed single-query projection', async () => {
    mockConfig(configResponse([
      { id: 'tv', provider: 'tavily', tavily_api_key: 'masked***key' },
      { id: 'rp', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      { id: 'sh', provider: 'self_hosted_bing' },
    ], { search: { api_type: 'responses' } }, {
      configured_providers: [
        { id: 'tv', provider: 'tavily', family: 'tavily_local', execution_mode: 'local_query_adapter', capabilities: ['search_query', 'domain_filter', 'multi_query', 'normalized_results', 'reference_storage'] },
        { id: 'rp', provider: 'configured_responses_provider', family: 'gpt_passthrough', execution_mode: 'alpha_search_passthrough', capabilities: ['full_web_run_passthrough'] },
        { id: 'sh', provider: 'self_hosted_bing', family: 'self_hosted_local', execution_mode: 'local_query_adapter', capabilities: ['search_query', 'domain_filter', 'multi_query', 'normalized_results', 'reference_storage'] },
      ],
      chain: { mode: 'mixed_single_query', capabilities: ['search_query', 'domain_filter', 'normalized_results', 'reference_storage'], limitations: ['single_search_query'] },
    }));
    render(NetworkSearchPage);

    expect(await screen.findByText(/mixed GPT\/local chain/)).toBeInTheDocument();
    expect(document.querySelector('[data-chain-mode="mixed_single_query"]')).toHaveTextContent('one search_query');
    expect(document.querySelector('[data-sortable-id="rp"] [data-provider-family="gpt_passthrough"]')).toHaveTextContent('configured Responses /alpha/search passthrough');
    expect(document.querySelector('[data-sortable-id="tv"] [data-provider-family="tavily_local"]')).toHaveTextContent('Tavily: local query adapter');
    expect(document.querySelector('[data-sortable-id="sh"] [data-provider-family="self_hosted_local"]')).toHaveTextContent('Self-hosted: sidecar adapter');
    expect(screen.getAllByText(/Capabilities:/)).toHaveLength(3);
  });

  it.each([
    {
      name: 'GPT to mixed after adding a local fallback',
      rows: [{ id: 'gpt', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' }],
      savedContract: {
        configured_providers: [{ id: 'gpt', provider: 'configured_responses_provider', family: 'gpt_passthrough', execution_mode: 'alpha_search_passthrough', capabilities: ['full_web_run_passthrough'] }],
        chain: { mode: 'full_gpt_passthrough', capabilities: ['full_web_run_passthrough'], limitations: [] },
      },
      mutate: async () => fireEvent.click(screen.getByRole('button', { name: '+ Add search provider' })),
    },
    {
      name: 'local to empty after deletion',
      rows: [{ id: 'local', provider: 'self_hosted_google' }],
      savedContract: {
        configured_providers: [{ id: 'local', provider: 'self_hosted_google', family: 'self_hosted_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] }],
        chain: { mode: 'local_query_adapter', capabilities: ['search_query'], limitations: [] },
      },
      mutate: async () => fireEvent.click(screen.getByRole('button', { name: 'Remove' })),
    },
    {
      name: 'provider reorder',
      rows: [
        { id: 'first', provider: 'tavily', tavily_api_key: 'first***mask' },
        { id: 'second', provider: 'self_hosted_google' },
      ],
      savedContract: {
        configured_providers: [
          { id: 'first', provider: 'tavily', family: 'tavily_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] },
          { id: 'second', provider: 'self_hosted_google', family: 'self_hosted_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] },
        ],
        chain: { mode: 'local_query_adapter', capabilities: ['search_query'], limitations: [] },
      },
      mutate: async () => {
        const source = document.querySelector('tr[data-sortable-id="first"] .drag-handle')!;
        const target = document.querySelector('tr[data-sortable-id="second"]')!;
        await fireEvent.dragStart(source);
        await fireEvent.drop(target);
      },
    },
  ])('hides stale saved contracts during dirty edits: $name', async ({ rows, savedContract, mutate }) => {
    mockConfig(configResponse(rows, { search: { api_type: 'responses' } }, savedContract));
    render(NetworkSearchPage);
    await waitFor(() => expect(document.querySelector('.chain-contract')).not.toBeNull());

    await mutate();

    expect(document.querySelector('.chain-contract')).toBeNull();
    expect(document.querySelectorAll('.provider-contract')).toHaveLength(0);
  });

  it('refreshes rows and contracts together after saving a local to GPT edit', async () => {
    const before = configResponse(
      [{ id: 'same-row', provider: 'self_hosted_google' }],
      { search: { api_type: 'responses' } },
      {
        configured_providers: [{ id: 'same-row', provider: 'self_hosted_google', family: 'self_hosted_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] }],
        chain: { mode: 'local_query_adapter', capabilities: ['search_query'], limitations: [] },
      },
    );
    const after = configResponse(
      [{ id: 'same-row', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-sol' }],
      { search: { api_type: 'responses' } },
      {
        configured_providers: [{ id: 'same-row', provider: 'configured_responses_provider', family: 'gpt_passthrough', execution_mode: 'alpha_search_passthrough', capabilities: ['full_web_run_passthrough'] }],
        chain: { mode: 'full_gpt_passthrough', capabilities: ['full_web_run_passthrough'], limitations: [] },
      },
    );
    let configReads = 0;
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/config')) return Promise.resolve(configReads++ === 0 ? before : after);
      if (path.endsWith('/usage')) return Promise.resolve({ entries: [] });
      return Promise.resolve({ configured: false });
    });
    apiMock.put.mockResolvedValue({ server: before.server });
    render(NetworkSearchPage);
    const type = await screen.findByLabelText('Search provider type');
    await chooseDropdown(type, 'configured_responses_provider');
    expect(document.querySelector('.chain-contract')).toBeNull();
    expect(document.querySelector('.provider-contract')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(screen.getByLabelText('Search provider type')).toHaveAttribute('data-value', 'configured_responses_provider');
      expect(document.querySelector('[data-chain-mode="full_gpt_passthrough"]')).not.toBeNull();
      expect(document.querySelector('[data-provider-family="gpt_passthrough"]')).toHaveTextContent('configured Responses /alpha/search passthrough');
    });
    expect(apiMock.get.mock.calls.filter(([path]) => path === '/admin/api/config')).toHaveLength(2);
  });

  it('locks every row editor mutation through deferred PUT and canonical GET', async () => {
    const rows = [
      { id: 'tv', provider: 'tavily', tavily_api_key: 'masked***key' },
      { id: 'rp', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      { id: 'sh', provider: 'self_hosted_bing' },
    ];
    const canonical = configResponse(rows, { search: { api_type: 'responses' } }, {
      configured_providers: [
        { id: 'tv', provider: 'tavily', family: 'tavily_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] },
        { id: 'rp', provider: 'configured_responses_provider', family: 'gpt_passthrough', execution_mode: 'alpha_search_passthrough', capabilities: ['full_web_run_passthrough'] },
        { id: 'sh', provider: 'self_hosted_bing', family: 'self_hosted_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] },
      ],
      chain: { mode: 'mixed_single_query', capabilities: ['search_query'], limitations: ['single_search_query'] },
    });
    const put = deferred<unknown>();
    const get = deferred<typeof canonical>();
    let configReads = 0;
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/config')) return configReads++ === 0 ? Promise.resolve(canonical) : get.promise;
      if (path.endsWith('/usage')) return Promise.resolve({ entries: [] });
      return Promise.resolve({ configured: false });
    });
    apiMock.put.mockReturnValue(put.promise);
    render(NetworkSearchPage);
    const key = await screen.findByLabelText('API Key');
    const originalOrder = ['tv', 'rp', 'sh'];
    const currentOrder = () => Array.from(document.querySelectorAll('tr[data-sortable-id]'))
      .map((row) => row.getAttribute('data-sortable-id'));
    const expectLocked = () => {
      expect(screen.getByRole('button', { name: '+ Add search provider' })).toBeDisabled();
      expect(screen.getAllByLabelText('Search provider type').every((control) => control.hasAttribute('disabled'))).toBe(true);
      expect(screen.getByLabelText('Responses Provider')).toBeDisabled();
      expect(screen.getByLabelText('Search Model')).toBeDisabled();
      expect(screen.getByLabelText('API Key')).toBeDisabled();
      expect(screen.getAllByRole('button', { name: 'Remove' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
      expect(screen.getAllByRole('button', { name: 'Drag to reorder search provider' }).every((button) => button.getAttribute('draggable') === 'false' && button.hasAttribute('disabled'))).toBe(true);
    };
    const attemptProgrammaticMutations = async () => {
      await fireEvent.input(key, { target: { value: 'request-in-flight-edit' } });
      const dataTransfer = transfer();
      dataTransfer.setData('text/plain', 'tv');
      await fireEvent.drop(document.querySelector('tr[data-sortable-id="sh"]')!, { dataTransfer });
      expect(currentOrder()).toEqual(originalOrder);
      expect(document.querySelector('[data-chain-mode="mixed_single_query"]')).not.toBeNull();
    };

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    expectLocked();
    await attemptProgrammaticMutations();

    put.resolve({ server: canonical.server });
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([path]) => path === '/admin/api/config')).toHaveLength(2));
    expectLocked();
    await attemptProgrammaticMutations();

    get.resolve(canonical);
    expect(await screen.findByText('Web search settings saved')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '+ Add search provider' })).toBeEnabled());
    expect(currentOrder()).toEqual(originalOrder);
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', {
      web_search: { providers: rows },
    });
  });

  it('unlocks the canonical editor while the post-save status refresh is still pending', async () => {
    const before = configResponse(
      [{ id: 'local', provider: 'self_hosted_google' }],
      { search: { api_type: 'responses' } },
    );
    const rows = [
      { id: 'tv', provider: 'tavily', tavily_api_key: 'masked***key' },
      { id: 'rp', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      { id: 'sh', provider: 'self_hosted_bing' },
    ];
    const after = configResponse(rows, { search: { api_type: 'responses' } }, {
      configured_providers: [
        { id: 'tv', provider: 'tavily', family: 'tavily_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] },
        { id: 'rp', provider: 'configured_responses_provider', family: 'gpt_passthrough', execution_mode: 'alpha_search_passthrough', capabilities: ['full_web_run_passthrough'] },
        { id: 'sh', provider: 'self_hosted_bing', family: 'self_hosted_local', execution_mode: 'local_query_adapter', capabilities: ['search_query'] },
      ],
      chain: { mode: 'mixed_single_query', capabilities: ['search_query'], limitations: ['single_search_query'] },
    });
    const status = deferred<unknown>();
    let configReads = 0;
    let statusReads = 0;
    apiMock.get.mockImplementation((path: string) => {
      if (path.endsWith('/config')) return Promise.resolve(configReads++ === 0 ? before : after);
      if (path.endsWith('/usage')) return Promise.resolve({ entries: [] });
      if (path.endsWith('/status')) {
        statusReads += 1;
        return statusReads === 1 ? Promise.resolve({ configured: false }) : status.promise;
      }
      return Promise.resolve({});
    });
    apiMock.put.mockResolvedValue({ server: before.server });
    render(NetworkSearchPage);
    await screen.findByLabelText('No configuration required');
    await waitFor(() => expect(statusReads).toBe(1));

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Web search settings saved')).toBeInTheDocument();
    await waitFor(() => expect(statusReads).toBe(2));
    expect(document.querySelector('[data-chain-mode="mixed_single_query"]')).not.toBeNull();
    expect(document.querySelector('[data-provider-family="gpt_passthrough"]')).toHaveTextContent('configured Responses /alpha/search passthrough');
    expect(screen.getByRole('button', { name: '+ Add search provider' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getAllByLabelText('Search provider type').every((control) => !control.hasAttribute('disabled'))).toBe(true);
    expect(screen.getByLabelText('Responses Provider')).toBeEnabled();
    expect(screen.getByLabelText('Search Model')).toBeEnabled();
    expect(screen.getByLabelText('API Key')).toBeEnabled();
    expect(screen.getAllByRole('button', { name: 'Remove' }).every((button) => !button.hasAttribute('disabled'))).toBe(true);
    expect(screen.getAllByRole('button', { name: 'Drag to reorder search provider' }).every((button) => button.getAttribute('draggable') === 'true' && !button.hasAttribute('disabled'))).toBe(true);

    status.reject(new Error('sidecar unavailable'));
    expect(await screen.findByText('Offline')).toBeInTheDocument();
    expect(screen.getByText('sidecar unavailable')).toBeInTheDocument();
  });

  it('loads usage once and binds clamped values and reset dates to stable Tavily row IDs', async () => {
    const rows = [
      { id: 'first', provider: 'tavily', tavily_api_key: 'first***mask' },
      { id: 'responses', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      { id: 'second', provider: 'tavily', tavily_api_key: 'second***mask' },
    ];
    mockConfig(configResponse(rows, { search: { api_type: 'responses' } }), { entries: [
      { id: 'second', status: 'ok', used: 25, limit: 100, reset_date: '2026-09-01' },
      { id: 'unknown', status: 'ok', used: 1, limit: 2, reset_date: '2026-09-02' },
      { id: 'first', status: 'ok', used: 120, limit: 100, reset_date: '2026-10-01' },
    ] });
    render(NetworkSearchPage);

    await waitFor(() => expect(document.querySelector('tr[data-sortable-id="first"]')).not.toBeNull());
    const first = document.querySelector<HTMLElement>('tr[data-sortable-id="first"]')!;
    const second = document.querySelector<HTMLElement>('tr[data-sortable-id="second"]')!;
    const responses = document.querySelector<HTMLElement>('tr[data-sortable-id="responses"]')!;
    await waitFor(() => expect(within(first).getByText('120/100')).toBeInTheDocument());
    expect(within(first).getByRole('progressbar')).toHaveValue(100);
    expect(within(first).getByText('Resets 2026/10/01')).toBeInTheDocument();
    expect(within(second).getByText('25/100')).toBeInTheDocument();
    expect(within(second).getByRole('progressbar')).toHaveValue(25);
    expect(responses.querySelector('.search-quota-cell')).toBeEmptyDOMElement();
    expect(apiMock.get.mock.calls.filter(([path]) => path === '/admin/api/network-search/usage')).toHaveLength(1);

    expect(within(document.querySelector<HTMLElement>('tr[data-sortable-id="first"]')!).getByText('120/100')).toBeInTheDocument();
    expect(within(document.querySelector<HTMLElement>('tr[data-sortable-id="second"]')!).getByText('25/100')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    expect(apiMock.get.mock.calls.filter(([path]) => path === '/admin/api/network-search/usage')).toHaveLength(1);
  });

  it('shows localized unavailable usage for missing, unavailable, zero-limit, and invalid-date Tavily entries', async () => {
    const rows = ['missing', 'unavailable', 'zero', 'date'].map((id) => ({ id, provider: 'tavily', tavily_api_key: `${id}***mask` }));
    mockConfig(configResponse(rows), { entries: [
      { id: 'unavailable', status: 'unavailable', used: null, limit: null, reset_date: null },
      { id: 'zero', status: 'ok', used: 0, limit: 0, reset_date: '2026-09-01' },
      { id: 'date', status: 'ok', used: 1, limit: 10, reset_date: '2026-02-30' },
    ] });
    render(NetworkSearchPage);

    expect(await screen.findAllByText('Quota unavailable')).toHaveLength(4);
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('still calls the usage endpoint exactly once when there are no Tavily rows', async () => {
    mockConfig(configResponse([{ id: 'local', provider: 'self_hosted_google' }]));
    render(NetworkSearchPage);

    await screen.findByLabelText('No configuration required');
    await waitFor(() => expect(apiMock.get.mock.calls.filter(([path]) => path === '/admin/api/network-search/usage')).toHaveLength(1));
    expect(document.querySelector('tr[data-sortable-id="local"] .search-quota-cell')).toBeEmptyDOMElement();
  });

  it('supports an empty list, adding and deleting rows, and cleans fields when changing type', async () => {
    mockConfig(configResponse([], { search: { api_type: 'responses' } }));
    apiMock.put.mockImplementation((_path: string, body: { web_search: { providers: Array<Record<string, string | undefined>> } }) => Promise.resolve({ server: { web_search: body.web_search } }));
    render(NetworkSearchPage);

    expect(await screen.findByText('No web search providers configured.')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: '+ Add search provider' }));
    const type = screen.getByLabelText('Search provider type');
    expect(type).toHaveAttribute('data-value', 'tavily');
    expect(screen.getByLabelText('API Key')).toBeInTheDocument();
    await chooseDropdown(type, 'configured_responses_provider');
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Responses Provider')).toHaveAttribute('data-value', 'search');
    await chooseDropdown(type, 'self_hosted_google');
    expect(screen.queryByLabelText('Responses Provider')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Search Model')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.getByText('No web search providers configured.')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: '+ Add search provider' }));
    await chooseDropdown(screen.getByLabelText('Search provider type'), 'self_hosted_google');
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    const savedRows = (apiMock.put.mock.calls[0][1] as { web_search: { providers: Array<Record<string, unknown>> } }).web_search.providers;
    expect(savedRows).toHaveLength(1);
    expect(savedRows[0]).toEqual({ id: expect.stringMatching(/^[A-Za-z0-9_-]{1,64}$/), provider: 'self_hosted_google' });
  });

  it('caps additions at the backend-provided 32-row limit', async () => {
    mockConfig(configResponse(Array.from({ length: 31 }, (_, index) => ({ id: `row-${index}`, provider: 'self_hosted_google' }))));
    render(NetworkSearchPage);
    const add = await screen.findByRole('button', { name: '+ Add search provider' });
    await waitFor(() => expect(add).toBeEnabled());
    await fireEvent.click(add);
    expect(screen.getByText('32 / 32')).toBeInTheDocument();
    expect(add).toBeDisabled();
  });

  it.each([
    {
      name: 'upward',
      sourceId: 'third',
      targetId: 'second',
      expectedIds: ['first', 'third', 'second'],
      clientY: 10,
    },
    {
      name: 'downward to the adjacent row',
      sourceId: 'second',
      targetId: 'third',
      expectedIds: ['first', 'third', 'second'],
      clientY: 90,
    },
    {
      name: 'to the end',
      sourceId: 'first',
      targetId: 'third',
      expectedIds: ['second', 'third', 'first'],
      clientY: 90,
    },
  ])('supports an $name drag while keeping IDs and masked keys on the same rows', async ({ sourceId, targetId, expectedIds, clientY }) => {
    const rows = [
      { id: 'first', provider: 'tavily', tavily_api_key: 'first***mask' },
      { id: 'second', provider: 'tavily', tavily_api_key: 'second***mask' },
      { id: 'third', provider: 'tavily', tavily_api_key: 'third***mask' },
    ];
    const expected = expectedIds.map((id) => rows.find((row) => row.id === id)!);
    mockConfig(configResponse(rows));
    apiMock.put.mockResolvedValue({ server: { web_search: { providers: expected } } });
    render(NetworkSearchPage);
    await screen.findByDisplayValue('first***mask');

    const source = document.querySelector(`tr[data-sortable-id="${sourceId}"] .drag-handle`);
    const target = document.querySelector(`tr[data-sortable-id="${targetId}"]`);
    expect(source).not.toBeNull();
    expect(target).not.toBeNull();
    const dataTransfer = transfer();
    await fireEvent.dragStart(source!, { dataTransfer });
    Object.defineProperty(target!, 'getBoundingClientRect', { value: () => ({ top: 0, height: 100 }) });
    await fireEvent.dragOver(target!, { dataTransfer, clientY });
    await fireEvent.drop(target!, { dataTransfer });
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', {
      web_search: { providers: expected },
    });
  });

  it('runs the fixed query through the network search test endpoint and displays its response', async () => {
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    requestMock.mockResolvedValue({ result: 'Python 3.test' });
    render(NetworkSearchPage);

    expect(await screen.findByText('latest python release version')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    await waitFor(() => expect(requestMock).toHaveBeenCalledWith('/admin/api/network-search/test', {
      method: 'POST',
      responseEffects: 'local',
      signal: expect.any(AbortSignal),
    }));
    expect(await screen.findByText(/Python 3\.test/)).toBeInTheDocument();
  });

  it('does not display an uncontrolled network search test failure', async () => {
    const providerDetail = 'debug endpoint http://10.0.0.5:9000, upstream request abc-123';
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    requestMock.mockRejectedValue(new Error(providerDetail));
    render(NetworkSearchPage);

    await screen.findByText('latest python release version');
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Search test failed');
    expect(screen.getByRole('alert')).not.toHaveTextContent(providerDetail);
  });

  it('displays a localized failure when the API client aborts its own timed-out request', async () => {
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    requestMock.mockRejectedValue(new DOMException('The operation was aborted.', 'AbortError'));
    render(NetworkSearchPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Test' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Search test failed');
    expect(screen.getByRole('button', { name: 'Test' })).toBeEnabled();
    expect(document.querySelector('.network-search-section > .toast.error')).toBeNull();
  });

  it.each([
    ['structured authorization failure', new ApiError('untrusted provider text', 401, 'network_search_test_authorization_failed'), 'Search test authorization failed'],
    ['no eligible model', new ApiError('safe backend fallback', 409, 'network_search_test_no_eligible_model'), 'No configured model has an enabled web.run search route'],
    ['upstream failure', new ApiError('provider debug endpoint http://10.0.0.5:9000', 502, 'network_search_test_unavailable'), 'Search provider is unavailable'],
  ])('localizes a controlled %s inside the result card without changing page-level state', async (_name, failure, expected) => {
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    requestMock.mockRejectedValue(failure);
    render(NetworkSearchPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Test' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(expected);
    expect(screen.getByRole('alert')).not.toHaveTextContent(failure.message);
    expect(screen.queryByText('Web search settings saved')).not.toBeInTheDocument();
    expect(document.querySelector('.network-search-section > .toast.error')).toBeNull();
  });

  it('prevents concurrent test requests and clears the previous result on the next click', async () => {
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    let resolveSecond!: (value: unknown) => void;
    requestMock
      .mockResolvedValueOnce({ result: 'old result' })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    render(NetworkSearchPage);
    const button = await screen.findByRole('button', { name: 'Test' });

    await fireEvent.click(button);
    expect(await screen.findByText(/old result/)).toBeInTheDocument();
    await fireEvent.click(button);
    expect(screen.queryByText(/old result/)).not.toBeInTheDocument();
    await fireEvent.click(button);
    expect(requestMock).toHaveBeenCalledTimes(2);
    resolveSecond({ result: 'new result' });
    expect(await screen.findByText(/new result/)).toBeInTheDocument();
  });

  it('silently aborts an in-flight test when the page unmounts', async () => {
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    let signal: AbortSignal | undefined;
    requestMock.mockImplementation((_path, options) => {
      signal = options.signal;
      return new Promise((_resolve, reject) => signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }));
    });
    const page = render(NetworkSearchPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Test' }));

    page.unmount();

    expect(signal?.aborted).toBe(true);
    await expect(requestMock.mock.results[0]?.value).rejects.toEqual(
      expect.objectContaining({ name: 'AbortError' }),
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('ToolsPage', () => {
  it('creates a writable copy from the selected profile', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/catalog')
      ? Promise.resolve({
          items: [{ id: 'function.exec_command', name: 'exec_command', type: 'function' }],
          placements: {
            groups: [{ id: 'exec_expansion', item_ids: ['function.exec_command'] }],
            namespaces: [],
          },
        })
      : Promise.resolve({ profiles: [{ id: 'builtin', name: 'Builtin', api_types: ['chat'], tools: { 'function.exec_command': 'modified' }, inputs: {}, readonly: true }], supported_states: { 'function.exec_command': ['disabled', 'modified'] }, references: {} }));
    render(ToolsPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Create Copy' }));
    const name = screen.getByLabelText('New profile name');
    await fireEvent.input(name, { target: { value: 'custom-profile' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Create copy' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/tools/profiles/custom-profile', { api_types: ['chat'], tools: { 'function.exec_command': 'modified' }, inputs: {} }));
  });

  it('saves multiple selected protocols for a writable profile', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/catalog')
      ? Promise.resolve({
          items: [{ id: 'function.exec_command', name: 'exec_command', type: 'function' }],
          placements: {
            groups: [{ id: 'exec_expansion', item_ids: ['function.exec_command'] }],
            namespaces: [],
          },
        })
      : Promise.resolve({ profiles: [{ id: 'custom', name: 'custom', api_types: ['chat'], tools: { 'function.exec_command': 'modified' }, inputs: {}, readonly: false }], supported_states: { 'function.exec_command': ['disabled', 'modified'] }, references: {} }));
    render(ToolsPage);
    const responses = await screen.findByRole('checkbox', { name: 'OpenAI Responses' });
    const anthropic = screen.getByRole('checkbox', { name: 'Anthropic Messages' });
    const google = screen.getByRole('checkbox', { name: 'Google GenAI (Gemini)' });
    expect(responses.closest('.tool-profile-protocol-row')).not.toBeNull();
    expect(document.querySelector('.tool-profile-toolbar input[type="checkbox"]')).toBeNull();

    await fireEvent.click(responses);
    await fireEvent.click(anthropic);
    await fireEvent.click(google);
    await fireEvent.click(screen.getByRole('button', { name: 'Save Profile' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/tools/profiles/custom', {
      api_types: ['chat', 'responses', 'anthropic', 'google'], tools: { 'function.exec_command': 'modified' }, inputs: {},
    }));
  });
});
