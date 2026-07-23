// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import KeysPage from '../src/admin/pages/KeysPage.svelte';
import ModelsPage from '../src/admin/pages/ModelsPage.svelte';
import ProvidersPage from '../src/admin/pages/ProvidersPage.svelte';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.post.mockResolvedValue({ ok: true });
  apiMock.put.mockResolvedValue({ ok: true });
  apiMock.del.mockResolvedValue({ ok: true });
});

function expectFixedModalRegions(dialog: HTMLElement): void {
  expect(Array.from(dialog.children, (child) => child.className)).toEqual([
    'modal-header',
    'modal-body',
    'modal-actions',
  ]);
}

describe('legacy Admin visual structure', () => {
  it('keeps provider editing in the legacy modal and requires an exact delete name', async () => {
    apiMock.get.mockResolvedValue({
      server: {}, known_api_types: ['responses'], credential_visible: false,
      providers: { Primary: { provider: 'openai', base_url: 'https://api.openai.com/v1', api_type: 'responses' } },
      models: { demo: { provider: 'Primary' } }, registered_shims: [],
    });
    render(ProvidersPage);
    expect(await screen.findByText('Server Settings')).toBeInTheDocument();
    expect(screen.getByText('Providers')).toBeInTheDocument();
    expect(screen.queryByLabelText('Provider Name')).not.toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: '+ Add Provider' }));
    const addDialog = screen.getByRole('dialog', { name: 'Add Provider' });
    expectFixedModalRegions(addDialog);
    expect(within(addDialog).getByLabelText('Provider Name')).toHaveFocus();
    await fireEvent.keyDown(addDialog, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Add Provider' })).not.toBeInTheDocument());

    await fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const deleteDialog = screen.getByRole('dialog', { name: 'Delete Provider' });
    expectFixedModalRegions(deleteDialog);
    const confirmButton = within(deleteDialog).getByRole('button', { name: 'Delete' });
    expect(confirmButton).toBeDisabled();
    expect(within(deleteDialog).getByText(/1 affected models/)).toBeInTheDocument();
    await fireEvent.input(within(deleteDialog).getByLabelText('Confirm provider name'), { target: { value: 'primary' } });
    expect(confirmButton).toBeDisabled();
    await fireEvent.input(within(deleteDialog).getByLabelText('Confirm provider name'), { target: { value: 'Primary' } });
    expect(confirmButton).toBeEnabled();
  });

  it('opens key creation and model-group editing in dialogs instead of inline editors', async () => {
    apiMock.get.mockImplementation((path: string) => path === '/admin/api/keys'
      ? Promise.resolve({ keys: [] })
      : Promise.resolve({ providers: { upstream: {} }, models: {}, model_groups: {}, tool_profile_presets: [] }));

    const keys = render(KeysPage);
    expect(await screen.findByText('API Keys')).toBeInTheDocument();
    expect(screen.queryByLabelText('Label (optional)')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: '+ Generate Key' }));
    const keyDialog = screen.getByRole('dialog', { name: 'Generate API Key' });
    expectFixedModalRegions(keyDialog);
    keys.unmount();

    render(ModelsPage);
    expect(await screen.findByText('Codex Task Models')).toBeInTheDocument();
    expect(screen.queryByLabelText('Model Group Name')).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: '+ Add Model Group' }));
    const modelDialog = screen.getByRole('dialog', { name: 'Add Model Group' });
    expectFixedModalRegions(modelDialog);
    await fireEvent.click(within(modelDialog).getByRole('button', { name: 'Enter Model Information Manually' }));
    expectFixedModalRegions(screen.getByRole('dialog', { name: 'Model Information' }));
  });
});
