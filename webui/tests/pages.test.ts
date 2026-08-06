// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardPage from '../src/admin/pages/DashboardPage.svelte';
import GatewayLogsPage from '../src/admin/pages/GatewayLogsPage.svelte';
import NetworkSearchPage from '../src/admin/pages/NetworkSearchPage.svelte';
import RequestLogsPage from '../src/admin/pages/RequestLogsPage.svelte';
import ToolsPage from '../src/admin/pages/ToolsPage.svelte';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(),
}));
const downloadMock = vi.hoisted(() => vi.fn());
const requestMock = vi.hoisted(() => vi.fn());
vi.mock('../src/admin/lib/api', () => ({ api: apiMock, download: downloadMock, request: requestMock }));

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
    provider_types: ['tavily', 'configured_responses_provider', 'self_hosted_google', 'self_hosted_bing', 'self_hosted_bing_browser'],
    responses_models: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
    max_providers: 32,
  };

  const configResponse = (rows: Array<Record<string, string | undefined>> = [], providers: Record<string, unknown> = {}) => ({
    providers,
    web_search_contract: contract,
    server: { web_search: { providers: rows } },
  });

  function mockConfig(value: ReturnType<typeof configResponse>): void {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/config')
      ? Promise.resolve(value)
      : Promise.resolve({ configured: false }));
  }

  function transfer(): { value: string; effectAllowed: string; setData: (_type: string, value: string) => void; getData: () => string } {
    return {
      value: '',
      effectAllowed: 'none',
      setData(_type: string, value: string) { this.value = value; },
      getData() { return this.value; },
    };
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
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', { web_search: { providers: rows } });
    const body = apiMock.put.mock.calls[0][1] as { web_search: Record<string, unknown> };
    expect(Object.keys(body.web_search)).toEqual(['providers']);
    expect(body.web_search).not.toHaveProperty('provider');
    expect(body.web_search).not.toHaveProperty('tavily_api_key');
  });

  it.each([
    {
      name: 'Tavily',
      row: { id: 'legacy-0', provider: 'tavily', tavily_api_key: 'tvly***cret' },
      providers: {},
    },
    {
      name: 'Responses',
      row: { id: 'legacy-0', provider: 'configured_responses_provider', responses_provider: 'search', responses_model: 'gpt-5.6-terra' },
      providers: { search: { api_type: 'responses' } },
    },
    {
      name: 'self-hosted',
      row: { id: 'legacy-0', provider: 'self_hosted_bing_browser' },
      providers: {},
    },
  ])('unchanged canonical save preserves the backend-adapted legacy $name row', async ({ row, providers }) => {
    const rows = [{ ...row }];
    mockConfig(configResponse(rows, providers));
    apiMock.put.mockImplementation((_path: string, body: { web_search: { providers: Array<Record<string, string | undefined>> } }) => Promise.resolve({ server: { web_search: body.web_search } }));
    render(NetworkSearchPage);
    await waitFor(() => expect(document.querySelector('tr[data-row-id="legacy-0"]')).not.toBeNull());

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
    expect(modelSelect).toHaveValue('gpt-5.6-terra');
    expect(Array.from((modelSelect as HTMLSelectElement).options).map((option) => option.value)).toEqual(contract.responses_models);
    expect(screen.getByLabelText('No configuration required')).toBeInTheDocument();
    expect(screen.getAllByLabelText('Quota display is not available yet')).toHaveLength(3);
  });

  it('supports an empty list, adding and deleting rows, and cleans fields when changing type', async () => {
    mockConfig(configResponse([], { search: { api_type: 'responses' } }));
    apiMock.put.mockImplementation((_path: string, body: { web_search: { providers: Array<Record<string, string | undefined>> } }) => Promise.resolve({ server: { web_search: body.web_search } }));
    render(NetworkSearchPage);

    expect(await screen.findByText('No web search providers configured.')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: '+ Add search provider' }));
    const type = screen.getByLabelText('Search provider type');
    expect(type).toHaveValue('tavily');
    expect(screen.getByLabelText('API Key')).toBeInTheDocument();
    await fireEvent.change(type, { target: { value: 'configured_responses_provider' } });
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Responses Provider')).toHaveValue('search');
    await fireEvent.change(type, { target: { value: 'self_hosted_google' } });
    expect(screen.queryByLabelText('Responses Provider')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Search Model')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    const savedRows = (apiMock.put.mock.calls[0][1] as { web_search: { providers: Array<Record<string, unknown>> } }).web_search.providers;
    expect(savedRows).toHaveLength(1);
    expect(savedRows[0]).toEqual({ id: expect.stringMatching(/^[A-Za-z0-9_-]{1,64}$/), provider: 'self_hosted_google' });
    await fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.getByText('No web search providers configured.')).toBeInTheDocument();
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

  it('reorders by keyboard without detaching a stable ID from its masked key', async () => {
    const rows = [
      { id: 'first', provider: 'tavily', tavily_api_key: 'first***mask' },
      { id: 'second', provider: 'tavily', tavily_api_key: 'second***mask' },
      { id: 'third', provider: 'self_hosted_google' },
    ];
    mockConfig(configResponse(rows));
    apiMock.put.mockResolvedValue({ server: { web_search: { providers: [] } } });
    render(NetworkSearchPage);
    await screen.findByDisplayValue('first***mask');

    await fireEvent.click(screen.getAllByRole('button', { name: 'Move search provider down' })[0]);
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', { web_search: { providers: [
      { id: 'second', provider: 'tavily', tavily_api_key: 'second***mask' },
      { id: 'first', provider: 'tavily', tavily_api_key: 'first***mask' },
      { id: 'third', provider: 'self_hosted_google' },
    ] } });
  });

  it.each([
    {
      name: 'upward',
      sourceId: 'third',
      targetId: 'second',
      expectedIds: ['first', 'third', 'second'],
    },
    {
      name: 'downward to the adjacent row',
      sourceId: 'second',
      targetId: 'third',
      expectedIds: ['first', 'third', 'second'],
    },
    {
      name: 'to the end',
      sourceId: 'first',
      targetId: 'third',
      expectedIds: ['second', 'third', 'first'],
    },
  ])('supports an $name drag while keeping IDs and masked keys on the same rows', async ({ sourceId, targetId, expectedIds }) => {
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

    const source = document.querySelector(`tr[data-row-id="${sourceId}"] .drag-handle`);
    const target = document.querySelector(`tr[data-row-id="${targetId}"]`);
    expect(source).not.toBeNull();
    expect(target).not.toBeNull();
    const dataTransfer = transfer();
    await fireEvent.dragStart(source!, { dataTransfer });
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
    }));
    expect(await screen.findByText(/Python 3\.test/)).toBeInTheDocument();
  });

  it('displays a readable network search test failure', async () => {
    mockConfig(configResponse([{ id: 'tv', provider: 'tavily', tavily_api_key: 'configured' }]));
    requestMock.mockRejectedValue(new Error('Upstream search failed'));
    render(NetworkSearchPage);

    await screen.findByText('latest python release version');
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Upstream search failed');
    expect(screen.getByRole('alert')).not.toHaveTextContent('[object Object]');
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
