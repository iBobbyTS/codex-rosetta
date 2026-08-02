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
vi.mock('../src/admin/lib/api', () => ({ api: apiMock, download: downloadMock }));

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.post.mockResolvedValue({ ok: true });
  apiMock.put.mockResolvedValue({ ok: true });
  apiMock.del.mockResolvedValue({ ok: true });
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
  it('preserves a masked Tavily key when saving', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/config')
      ? Promise.resolve({ server: { web_search: { provider: 'tavily', tavily_api_key: 'tav***key' } } })
      : Promise.resolve({ configured: false }));
    apiMock.put.mockResolvedValue({ server: { web_search: { provider: 'tavily', tavily_api_key: 'tav***key' } } });
    render(NetworkSearchPage);
    expect(await screen.findByDisplayValue('tav***key')).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', { web_search: { provider: 'tavily', tavily_api_key: 'tav***key' } });
  });

  it('selects an enabled Responses provider instead of showing an API key input', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/config')
      ? Promise.resolve({
          providers: {
            chat: { api_type: 'chat' },
            disabled: { api_type: 'responses', enabled: false },
            search: { api_type: 'responses' },
          },
          server: { web_search: { provider: 'configured_responses_provider', responses_provider: 'search' } },
        })
      : Promise.resolve({ configured: false }));
    apiMock.put.mockResolvedValue({ server: { web_search: { provider: 'configured_responses_provider', responses_provider: 'search' } } });
    render(NetworkSearchPage);

    const providerSelect = await screen.findByLabelText('Search Provider');
    await waitFor(() => expect(providerSelect).toHaveValue('configured_responses_provider'));
    expect(screen.queryByLabelText('API Key')).not.toBeInTheDocument();
    const responsesSelect = await screen.findByLabelText('Responses Provider');
    expect(responsesSelect).toHaveTextContent('search');
    expect(responsesSelect).not.toHaveTextContent('chat');
    expect(responsesSelect).not.toHaveTextContent('disabled');
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', {
      web_search: {
        provider: 'configured_responses_provider',
        responses_provider: 'search',
      },
    });
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
