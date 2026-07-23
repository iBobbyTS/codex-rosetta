// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RequestLogsPage from '../src/admin/pages/RequestLogsPage.svelte';
import ToolsPage from '../src/admin/pages/ToolsPage.svelte';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
const downloadMock = vi.hoisted(() => vi.fn());
vi.mock('../src/admin/lib/api', () => ({ api: apiMock, download: downloadMock }));

beforeEach(() => {
  vi.clearAllMocks(); apiMock.put.mockResolvedValue({ ok: true }); apiMock.del.mockResolvedValue({ ok: true });
});

describe('advanced tool profiles', () => {
  it('labels exec and namespace groups from the selected profile protocols', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/catalog') ? Promise.resolve({
      items: [
        { id: 'function.exec_command', name: 'exec_command', type: 'function' },
        { id: 'namespace.multi', name: 'multi', type: 'namespace' },
      ],
      placements: {
        groups: [
          { id: 'exec_expansion', item_ids: ['function.exec_command'] },
          { id: 'namespace', item_ids: ['namespace.multi'] },
        ],
        namespaces: [{ namespace_id: 'namespace.multi', child_ids: [] }],
      },
    }) : Promise.resolve({
      profiles: [{
        id: 'custom', name: 'Custom', api_types: ['chat'], readonly: false,
        tools: {
          'function.exec_command': 'modified',
          'namespace.multi': 'modified',
        },
        inputs: {},
      }],
      supported_states: {},
      references: {},
    }));

    const view = render(ToolsPage);
    const execGroup = await waitFor(() => {
      const group = view.container.querySelector<HTMLElement>('[data-tool-group="exec_expansion"]');
      expect(group).not.toBeNull();
      return group as HTMLElement;
    });
    const namespaceGroup = view.container.querySelector<HTMLElement>('[data-tool-group="namespace"]');
    expect(namespaceGroup).not.toBeNull();
    expect(execGroup.querySelector('.tool-group-title > span:first-child')).toHaveTextContent('Exec Expansion');
    expect(namespaceGroup?.querySelector('.tool-group-title > span:first-child')).toHaveTextContent('Namespace Expansion');

    await fireEvent.click(screen.getByRole('checkbox', { name: 'OpenAI Responses' }));

    expect(execGroup.querySelector('.tool-group-title > span:first-child')).toHaveTextContent(/^exec$/);
    expect(namespaceGroup?.querySelector('.tool-group-title > span:first-child')).toHaveTextContent(/^Namespace$/);
  });

  it('renders namespace children only inside their expandable namespace group', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/catalog') ? Promise.resolve({
      items: [
        { id: 'function.exec_command', name: 'exec_command', type: 'function' },
        { id: 'namespace.multi', name: 'multi', type: 'namespace' },
        { id: 'namespace.multi.send', name: 'send', type: 'function', namespace_id: 'namespace.multi' },
      ],
      placements: {
        groups: [
          { id: 'exec_expansion', item_ids: ['function.exec_command'] },
          { id: 'namespace', item_ids: ['namespace.multi'] },
        ],
        namespaces: [
          { namespace_id: 'namespace.multi', child_ids: ['namespace.multi.send'] },
        ],
      },
    }) : Promise.resolve({
      profiles: [{
        id: 'builtin', name: 'Builtin', api_types: ['chat'], readonly: true,
        tools: {
          'function.exec_command': 'modified',
          'namespace.multi': 'modified',
          'namespace.multi.send': 'modified',
        },
        inputs: {},
      }],
      supported_states: {},
      references: {},
    }));

    const view = render(ToolsPage);
    const namespaceGroup = await waitFor(() => {
      const group = view.container.querySelector<HTMLElement>('[data-tool-group="namespace"]');
      expect(group).not.toBeNull();
      return group as HTMLElement;
    });

    expect(within(namespaceGroup).getByText('multi')).toBeInTheDocument();
    expect(within(namespaceGroup).getByText('send')).toBeInTheDocument();
    expect(screen.getAllByText('send')).toHaveLength(1);

    const toggle = within(namespaceGroup).getByRole('button', { name: 'Collapse multi' });
    const children = namespaceGroup.querySelector<HTMLElement>('.tool-namespace-children');
    expect(children).not.toBeNull();
    expect(children).not.toHaveAttribute('hidden');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await fireEvent.click(toggle);
    expect(children).toHaveAttribute('hidden');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await fireEvent.click(toggle);
    expect(children).not.toHaveAttribute('hidden');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('uses real catalog groups and saves typed inputs without changing readonly states', async () => {
    apiMock.get.mockImplementation((path: string) => path.endsWith('/catalog') ? Promise.resolve({
      items: [
        { id: 'namespace.multi', name: 'multi', type: 'namespace' },
        { id: 'namespace.multi.send', name: 'send', type: 'function', namespace_id: 'namespace.multi' },
        { id: 'hosted.web_search', name: 'web_search', type: 'hosted', policy_id: 'passthrough', profile_inputs: [{ id: 'provider', type: 'select', default: 'tavily', options: [{ value: 'tavily' }] }, { id: 'token', type: 'password', default: '', visible_when: ['modified'] }] },
        { id: 'custom.apply_patch', name: 'apply_patch', type: 'custom' },
        { id: 'custom_injection.image', name: 'imagegen', type: 'custom_injection' },
      ],
      placements: {
        groups: [
          { id: 'exec_expansion', item_ids: ['custom.apply_patch'] },
          { id: 'function', item_ids: ['hosted.web_search'] },
          { id: 'namespace', item_ids: ['namespace.multi'] },
          { id: 'rosetta_injection', item_ids: ['custom_injection.image'] },
        ],
        namespaces: [{ namespace_id: 'namespace.multi', child_ids: ['namespace.multi.send'] }],
      },
    }) : Promise.resolve({ profiles: [{ id: 'builtin', name: 'Builtin', api_types: ['chat'], readonly: true, tools: { 'namespace.multi': 'modified', 'namespace.multi.send': 'modified', 'hosted.web_search': 'modified', 'custom.apply_patch': 'passthrough', 'custom_injection.image': 'modified' }, inputs: {} }], supported_states: { 'hosted.web_search': ['disabled','modified'] }, references: {} }));
    const view = render(ToolsPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Function' }));
    const functionGroup = view.container.querySelector<HTMLElement>('[data-tool-group="function"]');
    expect(functionGroup).not.toBeNull();
    expect(within(functionGroup as HTMLElement).getByText('web_search')).toBeInTheDocument();
    expect(screen.queryByText('apply_patch')).not.toBeInTheDocument();
    await fireEvent.click(within(functionGroup as HTMLElement).getByText('web_search'));
    const state = screen.getByLabelText('web_search state');
    expect(state).toBeDisabled();
    const token = screen.getByLabelText('token');
    expect(token).not.toBeDisabled();
    await fireEvent.input(token, { target: { value: 'override-token' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Save Profile' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/tools/profiles/builtin', expect.objectContaining({ api_types: ['chat'], inputs: { 'hosted.web_search': { token: 'override-token' } } })));
  });
});

describe('request and error-dump details', () => {
  it('renders full request details and dump detail as text', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path.includes('key-labels')) return Promise.resolve({ labels: [] });
      if (path.startsWith('/admin/api/requests?')) return Promise.resolve({ entries: [{ timestamp: '2026-01-01', model: 'demo', status_code: 500, error_detail: '<script>bad()</script>', request_id: 'req-one' }], total: 1 });
      if (path.startsWith('/admin/api/error-dumps?')) return Promise.resolve({ entries: [{ id: 'dump-one', model: 'demo', body_hash: 'hash' }] });
      if (path === '/admin/api/error-dumps/dump-one') return Promise.resolve({ id: 'dump-one', request_body: { prompt: '<img onerror=bad()>' } });
      return Promise.resolve({});
    });
    render(RequestLogsPage);
    await screen.findByText('demo');
    await fireEvent.click(screen.getAllByText('demo')[0]);
    expect(await screen.findByText(/request_id/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Details' }));
    expect(await screen.findByLabelText('Error dump detail')).toHaveTextContent('<img onerror=bad()>');
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('img')).toBeNull();
  });
});
