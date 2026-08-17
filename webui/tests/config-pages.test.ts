// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import KeysPage from '../src/admin/pages/KeysPage.svelte';
import ModelsPage from '../src/admin/pages/ModelsPage.svelte';
import ProvidersPage from '../src/admin/pages/ProvidersPage.svelte';
import SettingsPage from '../src/admin/pages/SettingsPage.svelte';
import { setLanguage } from '../src/shared/i18n.svelte';

async function selectDropdown(control: HTMLElement, label: string): Promise<void> {
  await fireEvent.click(control);
  const lists = screen.getAllByRole('listbox');
  const option = lists.flatMap((node) => within(node).getAllByRole('option')).find((item) => item.textContent?.trim() === label || item.getAttribute('data-value') === label)!;
  await fireEvent.click(option);
}

function transfer(): { value: string; effectAllowed: string; setData: (_type: string, value: string) => void; getData: () => string } {
  return {
    value: '',
    effectAllowed: 'none',
    setData(_type: string, value: string) { this.value = value; },
    getData() { return this.value; },
  };
}

function dragAt(element: Element, type: string, dataTransfer: ReturnType<typeof transfer>, clientY = 0): Promise<boolean> {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'clientY', { configurable: true, value: clientY });
  Object.defineProperty(event, 'dataTransfer', { configurable: true, value: dataTransfer });
  return fireEvent(element, event);
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));

const providerCatalog = {
  api_types: ['responses', 'chat', 'anthropic', 'google'],
  providers: {
    openai: { label_key: 'provider.openai', recommended_api_type: 'responses', adapted_api_types: { chat: 'openai', responses: 'openai_responses' }, known_supported_api_types: ['chat', 'responses'], variants: { official: { endpoints: { chat: 'https://api.openai.com/v1', responses: 'https://api.openai.com/v1' } }, custom: { endpoints: {} } } },
    moonshot: { label_key: 'provider.kimi', recommended_api_type: 'chat', adapted_api_types: { chat: 'moonshot' }, known_supported_api_types: ['chat', 'anthropic'], variants: { china: { endpoints: { chat: 'https://api.moonshot.cn/v1' } }, international: { endpoints: { chat: 'https://api.moonshot.ai/v1' } }, custom: { endpoints: {} } } },
    deepseek: { label_key: 'provider.deepseek', soft_interrupt_default: true, recommended_api_type: 'chat', adapted_api_types: { chat: 'deepseek' }, known_supported_api_types: ['chat', 'anthropic'], variants: { official: { endpoints: { chat: 'https://api.deepseek.com' } }, custom: { endpoints: {} } } },
    custom: { label_key: 'provider.custom', recommended_api_type: 'chat', adapted_api_types: {}, known_supported_api_types: [], variants: { custom: { endpoints: {} } } },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem('codex-rosetta-lang', 'en');
  setLanguage('en');
  apiMock.post.mockResolvedValue({ ok: true });
  apiMock.put.mockResolvedValue({ ok: true });
  apiMock.del.mockResolvedValue({ ok: true });
});

describe('ProvidersPage', () => {
  it('round-trips an untouched canonical credential mask', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai',
          base_urls: ['https://relay.example/v1'],
          current_base_url: 'https://relay.example/v1',
          api_keys: [{ id: 'primary', key: 'prov***cret' }],
          current_api_key: 'primary',
          api_type: 'responses',
          request_encoding: 'passthrough',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    expect(dialog.getByRole('textbox', { name: 'Credential key primary' })).toHaveValue('prov***cret');
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay', expect.objectContaining({
      api_keys: [{ id: 'primary', key: 'prov***cret' }],
      current_api_key: 'primary',
    })));
  });

  it('round-trips an untouched environment variable credential placeholder', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai',
          base_urls: ['https://relay.example/v1'],
          current_base_url: 'https://relay.example/v1',
          api_keys: [{ id: 'primary', key: '${OPENAI_API_KEY}' }],
          current_api_key: 'primary',
          api_type: 'responses',
          request_encoding: 'passthrough',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    expect(dialog.getByRole('textbox', { name: 'Credential key primary' })).toHaveValue('${OPENAI_API_KEY}');
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay', expect.objectContaining({
      api_keys: [{ id: 'primary', key: '${OPENAI_API_KEY}' }],
      current_api_key: 'primary',
    })));
  });

  it('keeps the credential name editable while the saved key is read-only', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai',
          base_urls: ['https://relay.example/v1'],
          current_base_url: 'https://relay.example/v1',
          api_keys: [{ id: 'primary', key: 'prov***cret' }],
          current_api_key: 'primary',
          api_type: 'responses',
          request_encoding: 'passthrough',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    const nameInput = dialog.getByRole('textbox', { name: 'Credential ID primary' });
    const keyDisplay = dialog.getByRole('textbox', { name: 'Credential key primary' });
    expect(nameInput).not.toBeDisabled();
    expect(nameInput).not.toHaveAttribute('readonly');
    expect(keyDisplay).toHaveAttribute('readonly');

    await fireEvent.input(nameInput, { target: { value: 'production' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay', expect.objectContaining({
      api_keys: [{ id: 'production', key: 'prov***cret' }],
      current_api_key: 'production',
    })));
  });

  it('clears a credential only in local state until Save', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai',
          base_urls: ['https://relay.example/v1'],
          current_base_url: 'https://relay.example/v1',
          api_keys: [{ id: 'primary', key: 'prov***cret' }],
          current_api_key: 'primary',
          api_type: 'responses',
          request_encoding: 'passthrough',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    expect(dialog.getByRole('textbox', { name: 'Credential key primary' })).toHaveValue('prov***cret');
    expect(dialog.queryByRole('button', { name: 'Toggle visibility' })).not.toBeInTheDocument();
    await fireEvent.click(dialog.getByRole('button', { name: 'Clear credential key primary' }));
    expect(apiMock.put).not.toHaveBeenCalled();
    expect(apiMock.post).not.toHaveBeenCalled();
    const input = dialog.getByLabelText('Credential key primary');
    expect(input).toHaveAttribute('type', 'password');
    await fireEvent.input(input, { target: { value: 'replacement-secret' } });
    expect(apiMock.put).not.toHaveBeenCalled();
    expect(apiMock.post).not.toHaveBeenCalled();
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay', expect.objectContaining({
      api_keys: [{ id: 'primary', key: 'replacement-secret' }],
      current_api_key: 'primary',
    })));
  });

  it('persists the provider while deriving its variant from that provider and URL', async () => {
    const config = {
      providers: { official: { provider: 'openai', base_urls: ['https://api.openai.com/v1', 'https://backup.example/v1'], current_base_url: 'https://api.openai.com/v1', base_url_statuses: [{ base_url: 'https://api.openai.com/v1', current: true, status: 'available' }, { base_url: 'https://backup.example/v1', current: false, status: 'cooling' }], api_keys: [{ id: 'primary', key: 'prov***cret' }], current_api_key: 'primary', credential_statuses: [{ id: 'primary', current: true, status: 'available' }], api_type: 'responses', request_encoding: 'identity', proxy: 'http://proxy.example:8080' } },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [{ name: 'openai', logo: '/admin/assets/openai.svg' }],
      credential_visible: true,
    };
    apiMock.get.mockResolvedValue(config);
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByLabelText('Provider')).toHaveAttribute('data-value', 'openai');
    expect(screen.getByLabelText('Provider variant')).toHaveAttribute('data-value', 'official');
    expect(screen.getByDisplayValue('http://proxy.example:8080')).toBeInTheDocument();
    expect(screen.getByLabelText('Upstream request encoding')).toHaveAttribute('data-value', 'identity');
    expect(await screen.findByRole('textbox', { name: 'Credential key primary' })).toHaveValue('prov***cret');
    expect(apiMock.get).not.toHaveBeenCalledWith('/admin/api/config/providers/official/key');
    const dialog = within(screen.getByRole('dialog', { name: /Edit Provider/ }));
    expect(dialog.getAllByLabelText(/^Credential key/)).toHaveLength(1);
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    expect(screen.getByRole('status')).toHaveTextContent("Provider 'official' saved");
    expect(screen.getByRole('status')).not.toHaveTextContent('{name}');
    const body = apiMock.put.mock.calls[0][1];
    expect(body).toEqual({
      provider: 'openai',
      base_urls: ['https://api.openai.com/v1', 'https://backup.example/v1'],
      current_base_url: 'https://api.openai.com/v1',
      proxy: 'http://proxy.example:8080',
      allow_redirects: false,
      api_type: 'responses',
      request_encoding: 'identity',
      force_rosetta_compaction: false,
      api_keys: [{ id: 'primary', key: 'prov***cret' }],
      current_api_key: 'primary',
    });
    expect(body).not.toHaveProperty('preset');
    expect(body).not.toHaveProperty('base');
    expect(body).not.toHaveProperty('variant');
    await fireEvent.click(screen.getByRole('button', { name: 'Grid view' }));
    expect(screen.getByText('Cooling')).toBeInTheDocument();
    await fireEvent.click(screen.getByLabelText('Maximum Request Body'));
    expect(within(screen.getByRole('listbox')).getAllByRole('option').map((option) => option.getAttribute('data-value'))).toEqual(['64', '128', '256', '512', '1024', 'unlimited']);
  });

  it('reorders URLs at the midpoint, keeps current by row identity, and falls forward when current is removed', async () => {
    const config = {
      providers: {
        relay: {
          provider: 'openai',
          base_urls: ['https://one.example/v1', 'https://two.example/v1', 'https://three.example/v1'],
          current_base_url: 'https://two.example/v1',
          base_url_statuses: [
            { base_url: 'https://one.example/v1', current: false, status: 'available' },
            { base_url: 'https://two.example/v1', current: true, status: 'available' },
            { base_url: 'https://three.example/v1', current: false, status: 'cooling' },
          ],
          api_keys: [{ id: 'primary', key: 'prov***cret' }],
          current_api_key: 'primary',
          credential_statuses: [{ id: 'primary', current: true, status: 'available' }],
          api_type: 'responses',
          request_encoding: 'passthrough',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    };
    apiMock.get.mockResolvedValue(config);
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    const source = dialog.getByRole('button', { name: 'Drag https://three.example/v1' });
    const target = dialog.getByRole('button', { name: 'Drag https://two.example/v1' }).closest('tr')!;
    const dataTransfer = transfer();
    await dragAt(source, 'dragstart', dataTransfer);
    Object.defineProperty(target, 'getBoundingClientRect', { value: () => ({ top: 0, height: 100 }) });
    await dragAt(target, 'dragover', dataTransfer, 25);
    expect(target).toHaveClass('suu-sortable-table__row--drop-before');
    await dragAt(target, 'drop', dataTransfer, 25);

    await fireEvent.click(dialog.getByRole('radio', { name: 'Make https://three.example/v1 current' }));
    const editedUrl = dialog.getByLabelText('Base URL 2');
    await fireEvent.input(editedUrl, { target: { value: 'https://edited-three.example/v1' } });
    expect(dialog.getByRole('radio', { name: 'Make https://edited-three.example/v1 current' })).toBeChecked();
    await fireEvent.click(dialog.getByRole('button', { name: 'Remove https://edited-three.example/v1' }));
    expect(dialog.getByRole('radio', { name: 'Make https://two.example/v1 current' })).toBeChecked();
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay', expect.objectContaining({
      base_urls: ['https://one.example/v1', 'https://two.example/v1'],
      current_base_url: 'https://two.example/v1',
    })));

    await fireEvent.click(screen.getByRole('button', { name: 'Grid view' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Make https://three.example/v1 current' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/admin/api/config/providers/relay/current-base-url', {
      current_base_url: 'https://three.example/v1',
    }));
  });

  it('reorders masked credentials, preserves current while its ID changes, and saves the existing DTO', async () => {
    const config = {
      providers: { relay: {
        provider: 'openai', api_type: 'responses',
          request_encoding: 'passthrough',
        base_urls: ['https://one.example/v1'], current_base_url: 'https://one.example/v1',
        base_url_statuses: [{ base_url: 'https://one.example/v1', current: true, status: 'available' }],
        api_keys: [{ id: 'first', key: 'firs***cret' }, { id: 'second', key: 'seco***cret' }],
        current_api_key: 'first',
        credential_statuses: [{ id: 'first', current: true, status: 'available' }, { id: 'second', current: false, status: 'cooling' }],
      } },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'], provider_catalog: providerCatalog, registered_shims: [], credential_visible: false,
    };
    apiMock.get.mockResolvedValue(config);
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    const source = dialog.getByRole('button', { name: 'Drag credential second' });
    const target = dialog.getByRole('button', { name: 'Drag credential first' }).closest('tr')!;
    const dataTransfer = transfer();
    await dragAt(source, 'dragstart', dataTransfer);
    Object.defineProperty(target, 'getBoundingClientRect', { value: () => ({ top: 0, height: 100 }) });
    await dragAt(target, 'dragover', dataTransfer, 25);
    expect(target).toHaveClass('suu-sortable-table__row--drop-before');
    await dragAt(target, 'drop', dataTransfer, 25);

    await fireEvent.input(dialog.getByRole('textbox', { name: 'Credential ID first' }), { target: { value: 'renamed-first' } });
    expect(dialog.getByRole('radio', { name: 'Make credential renamed-first current' })).toBeChecked();
    expect(dialog.getByRole('textbox', { name: 'Credential key renamed-first' })).toHaveValue('firs***cret');
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay', expect.objectContaining({
      api_keys: [{ id: 'second', key: 'seco***cret' }, { id: 'renamed-first', key: 'firs***cret' }],
      current_api_key: 'renamed-first',
    })));

    await fireEvent.click(screen.getByRole('button', { name: 'Grid view' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Make credential second current' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/admin/api/config/providers/relay/current-base-url', { credential_id: 'second' }));
  });

  it('protects the last URL and credential rows while allowing newly added rows to be removed', async () => {
    apiMock.get.mockResolvedValue({
      providers: { relay: {
        provider: 'openai', api_type: 'responses',
          request_encoding: 'passthrough',
        base_urls: ['https://one.example/v1'], current_base_url: 'https://one.example/v1',
        api_keys: [{ id: 'primary', key: 'prim***cret' }], current_api_key: 'primary',
      } },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'], provider_catalog: providerCatalog,
      registered_shims: [], credential_visible: false,
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    expect(dialog.getByRole('button', { name: 'Remove https://one.example/v1' })).toBeDisabled();
    expect(dialog.getByRole('button', { name: 'Remove credential primary' })).toBeDisabled();

    await fireEvent.click(dialog.getByRole('button', { name: '+ Add Base URL' }));
    expect(dialog.getByRole('button', { name: 'Remove Base URL' })).not.toBeDisabled();
    await fireEvent.click(dialog.getByRole('button', { name: 'Remove Base URL' }));
    expect(dialog.getByRole('button', { name: 'Remove https://one.example/v1' })).toBeDisabled();

    await fireEvent.click(dialog.getByRole('button', { name: '+ Add credential' }));
    expect(dialog.getByRole('button', { name: 'Remove credential credential-2' })).not.toBeDisabled();
    await fireEvent.click(dialog.getByRole('button', { name: 'Remove credential credential-2' }));
    expect(dialog.getByRole('button', { name: 'Remove credential primary' })).toBeDisabled();
  });

  it('derives a child option from persisted provider and URL without using api_type', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        kimi: { provider: 'moonshot', base_urls: ['https://api.moonshot.ai/v1'], current_base_url: 'https://api.moonshot.ai/v1', api_type: 'responses' },
        mismatch: { provider: 'deepseek', base_urls: ['https://api.openai.com/v1'], current_base_url: 'https://api.openai.com/v1', api_type: 'chat' },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);
    const edits = await screen.findAllByRole('button', { name: 'Edit' });
    await fireEvent.click(edits[0]);
    expect(screen.getByLabelText('Provider')).toHaveAttribute('data-value', 'moonshot');
    expect(screen.getByLabelText('Provider variant')).toHaveAttribute('data-value', 'international');
    await fireEvent.click(within(screen.getByRole('dialog', { name: 'Edit Provider' })).getByRole('button', { name: 'Cancel' }));
    await fireEvent.click(edits[1]);
    expect(screen.getByLabelText('Provider')).toHaveAttribute('data-value', 'deepseek');
    expect(screen.getByLabelText('Provider variant')).toHaveAttribute('data-value', 'custom');
  });

  it('renders only backend-supported API types with user-facing protocol names', async () => {
    apiMock.get.mockResolvedValue({
      providers: {},
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Provider' }));
    const protocol = within(screen.getByRole('dialog', { name: 'Add Provider' })).getByLabelText('Protocol');
    await fireEvent.click(protocol);
    expect(screen.getByRole('listbox').parentElement).toHaveClass(
      'suu-dropdown__menu--fit-content',
      'suu-dropdown__menu--left',
    );
    expect(within(screen.getByRole('listbox')).getAllByRole('option').map((option) => [option.getAttribute('data-value'), option.textContent?.trim()])).toEqual([
      ['responses', 'OpenAI Responses'],
      ['chat', 'OpenAI Chat Completions'],
      ['anthropic', 'Anthropic Messages'],
      ['google', 'Google GenAI'],
    ]);
    expect(screen.getByRole('listbox')).not.toHaveTextContent('open_responses');
    expect(protocol).not.toHaveTextContent('openai_chat');
    expect(protocol).not.toHaveTextContent('openai_responses');
  });

  it('defaults DeepSeek Chat to late-developer cache compatibility and hides it for non-Chat protocols', async () => {
    apiMock.get.mockResolvedValue({
      providers: {},
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Provider' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Add Provider' }));
    await selectDropdown(dialog.getByLabelText('Provider'), 'DeepSeek');
    expect(dialog.getByLabelText('Late instruction cache compatibility')).toBeChecked();
    expect(dialog.getByText(/append system or developer messages/)).toHaveTextContent('does not inspect or special-case turn_aborted');
    await selectDropdown(dialog.getByLabelText('Protocol'), 'Anthropic Messages');
    expect(dialog.queryByLabelText('Late instruction cache compatibility')).not.toBeInTheDocument();
    await fireEvent.input(dialog.getByLabelText('Provider Name'), { target: { value: 'deepseek-anthropic' } });
    await fireEvent.input(dialog.getByPlaceholderText('https://api.openai.com/v1'), { target: { value: 'https://api.deepseek.com/anthropic' } });
    await fireEvent.input(dialog.getByLabelText(/^Credential key/), { target: { value: 'sk-test' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    expect(apiMock.put.mock.calls[0][1]).not.toHaveProperty('soft_interrupt');
  });

  it('preserves explicitly disabled late-developer cache compatibility when editing and cloning', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        deepseek: {
          provider: 'deepseek',
          base_urls: ['https://api.deepseek.com'],
          current_base_url: 'https://api.deepseek.com',
          api_type: 'chat',
          soft_interrupt: false,
          api_keys: [{ id: 'primary', key: 'prov***cret' }],
          current_api_key: 'primary',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByLabelText('Late instruction cache compatibility')).not.toBeChecked();
    await fireEvent.click(within(screen.getByRole('dialog', { name: 'Edit Provider' })).getByRole('button', { name: 'Cancel' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Clone' }));
    expect(screen.getByLabelText('Late instruction cache compatibility')).not.toBeChecked();
  });

  it('requires fresh credential secrets when cloning a provider', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai',
          base_urls: ['https://relay.example/v1', 'https://backup.example/v1'],
          current_base_url: 'https://backup.example/v1',
          api_type: 'responses',
          request_encoding: 'passthrough',
          proxy: 'http://proxy.example:8080',
          api_keys: [
            { id: 'primary', key: 'prim***cret' },
            { id: 'fallback', key: 'fall***cret' },
          ],
          current_api_key: 'fallback',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Clone' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Add Provider' }));
    expect(dialog.getByLabelText('Provider Name')).toHaveValue('relay-copy');
    expect(dialog.getByLabelText('Base URL 1')).toHaveValue('https://relay.example/v1');
    expect(dialog.getByLabelText('Base URL 2')).toHaveValue('https://backup.example/v1');
    expect(dialog.getByLabelText(/^Proxy URL/)).toHaveValue('http://proxy.example:8080');
    expect(dialog.getByLabelText('Credential ID primary')).toHaveValue('primary');
    expect(dialog.getByLabelText('Credential ID fallback')).toHaveValue('fallback');
    expect(dialog.getByLabelText('Credential key primary')).toHaveValue('');
    expect(dialog.getByLabelText('Credential key fallback')).toHaveValue('');

    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    expect(apiMock.put).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('A provider credential is required when creating a provider.');

    await fireEvent.input(dialog.getByLabelText('Credential key primary'), { target: { value: 'fresh-primary-secret' } });
    await fireEvent.input(dialog.getByLabelText('Credential key fallback'), { target: { value: 'fresh-fallback-secret' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));

    const expectedBody = {
      provider: 'openai',
      api_type: 'responses',
      request_encoding: 'passthrough',
      base_urls: ['https://relay.example/v1', 'https://backup.example/v1'],
      current_base_url: 'https://backup.example/v1',
      api_keys: [
        { id: 'primary', key: 'fresh-primary-secret' },
        { id: 'fallback', key: 'fresh-fallback-secret' },
      ],
      current_api_key: 'fallback',
      proxy: 'http://proxy.example:8080',
      allow_redirects: false,
      force_rosetta_compaction: false,
    };
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/providers/relay-copy', expectedBody));
    expect(JSON.stringify(apiMock.put.mock.calls[0][1])).not.toContain('***');
  });

  it('shows forced prompt compaction only for Responses and preserves it when editing and cloning', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        cockpit: {
          provider: 'openai',
          base_urls: ['https://cockpit.example/v1'],
          current_base_url: 'https://cockpit.example/v1',
          api_type: 'responses',
          request_encoding: 'passthrough',
          force_rosetta_compaction: true,
          api_keys: [{ id: 'primary', key: 'prov***cret' }],
          current_api_key: 'primary',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const toggle = screen.getByLabelText('Force Rosetta prompt compaction');
    expect(toggle).toBeChecked();
    expect(screen.getByText(/summary plaintext in SQLite for seven days/)).toBeInTheDocument();
    await fireEvent.click(within(screen.getByRole('dialog', { name: 'Edit Provider' })).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    expect(apiMock.put.mock.calls[0][1]).toMatchObject({ force_rosetta_compaction: true });

    await fireEvent.click(await screen.findByRole('button', { name: 'Clone' }));
    expect(screen.getByLabelText('Force Rosetta prompt compaction')).toBeChecked();
    await selectDropdown(screen.getByLabelText('Protocol'), 'OpenAI Chat Completions');
    expect(screen.queryByLabelText('Force Rosetta prompt compaction')).not.toBeInTheDocument();
  });

  it('renders the forced prompt compaction control in Chinese', async () => {
    localStorage.setItem('codex-rosetta-lang', 'zh');
    setLanguage('zh');
    apiMock.get.mockResolvedValue({
      providers: {},
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [],
      credential_visible: false,
    });
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ 添加服务方' }));
    await selectDropdown(screen.getByLabelText('协议'), 'OpenAI Responses');
    expect(screen.getByLabelText('强制 Rosetta 提示词压缩')).toBeInTheDocument();
    expect(screen.getByText(/SQLite 中以明文保存摘要七天/)).toBeInTheDocument();
  });

  it('detects only the selected draft endpoint and updates the encoding draft without saving', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai', api_type: 'responses', request_encoding: 'identity',
          base_urls: ['https://one.example/v1', 'https://current.example/v1'],
          current_base_url: 'https://current.example/v1',
          api_keys: [{ id: 'first', key: 'firs***cret' }, { id: 'current', key: 'curr***cret' }],
          current_api_key: 'current', proxy: 'http://proxy.example:8080', allow_redirects: true,
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'], provider_catalog: providerCatalog,
    });
    apiMock.post.mockResolvedValue({
      selected: 'zstd',
      identity: { ok: false, status_code: 400, error: 'invalid JSON' },
      zstd: { ok: true, status_code: 200, error: null },
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    await fireEvent.input(dialog.getByLabelText('Detection model'), { target: { value: 'manual-model' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Auto-detect' }));

    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith(
      '/admin/api/config/providers/relay/detect-request-encoding',
      {
        provider: 'openai', api_type: 'responses', model: 'manual-model',
        current_base_url: 'https://current.example/v1',
        api_keys: [{ id: 'current', key: 'curr***cret' }], current_api_key: 'current',
        proxy: 'http://proxy.example:8080', allow_redirects: true,
      },
    ));
    expect(apiMock.put).not.toHaveBeenCalled();
    expect(dialog.getByLabelText('Upstream request encoding')).toHaveAttribute('data-value', 'zstd');
    expect(screen.getByRole('status')).toHaveTextContent('Save to apply it');

    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    expect(apiMock.put.mock.calls[0][1]).toMatchObject({ request_encoding: 'zstd' });
  });

  it('shows both complete detection failures without changing the draft encoding', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        relay: {
          provider: 'openai', api_type: 'responses', request_encoding: 'identity',
          base_urls: ['https://current.example/v1'], current_base_url: 'https://current.example/v1',
          api_keys: [{ id: 'current', key: 'curr***cret' }], current_api_key: 'current',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'], provider_catalog: providerCatalog,
    });
    apiMock.post.mockResolvedValue({
      selected: null,
      identity: { ok: false, status_code: 400, error: 'HTTP 400: identity full error' },
      zstd: { ok: false, status_code: 502, error: 'HTTP 502: zstd full error' },
    });
    render(ProvidersPage);

    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    await fireEvent.input(dialog.getByLabelText('Detection model'), { target: { value: 'manual-model' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Auto-detect' }));

    const failure = await dialog.findByRole('alert');
    expect(failure).toHaveTextContent('HTTP 400: identity full error');
    expect(failure).toHaveTextContent('HTTP 502: zstd full error');
    expect(dialog.getByLabelText('Upstream request encoding')).toHaveAttribute('data-value', 'identity');
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it('ignores a late detection result after closing one provider and detecting another', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        alpha: {
          provider: 'openai', api_type: 'responses', request_encoding: 'passthrough',
          base_urls: ['https://same.example/v1'], current_base_url: 'https://same.example/v1',
          api_keys: [{ id: 'current', key: 'curr***cret' }], current_api_key: 'current',
        },
        beta: {
          provider: 'openai', api_type: 'responses', request_encoding: 'identity',
          base_urls: ['https://same.example/v1'], current_base_url: 'https://same.example/v1',
          api_keys: [{ id: 'current', key: 'curr***cret' }], current_api_key: 'current',
        },
      },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'], provider_catalog: providerCatalog,
    });
    const alphaDetection = deferred<{ selected: 'zstd'; identity: { ok: true }; zstd: { ok: true } }>();
    const betaDetection = deferred<{ selected: 'identity'; identity: { ok: true }; zstd: { ok: false } }>();
    apiMock.post.mockImplementationOnce(() => alphaDetection.promise).mockImplementationOnce(() => betaDetection.promise);
    render(ProvidersPage);

    const editButtons = await screen.findAllByRole('button', { name: 'Edit' });
    await fireEvent.click(editButtons[0]);
    let dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    await fireEvent.input(dialog.getByLabelText('Detection model'), { target: { value: 'manual-model' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Auto-detect' }));
    expect(dialog.getByRole('button', { name: 'Detecting...' })).toBeDisabled();
    await fireEvent.click(dialog.getByRole('button', { name: 'Cancel' }));

    await fireEvent.click(editButtons[1]);
    dialog = within(screen.getByRole('dialog', { name: 'Edit Provider' }));
    expect(dialog.getByLabelText('Upstream request encoding')).toHaveAttribute('data-value', 'identity');
    await fireEvent.input(dialog.getByLabelText('Detection model'), { target: { value: 'manual-model' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Auto-detect' }));
    expect(dialog.getByRole('button', { name: 'Detecting...' })).toBeDisabled();

    alphaDetection.resolve({ selected: 'zstd', identity: { ok: true }, zstd: { ok: true } });
    await alphaDetection.promise;
    await tick();
    expect(dialog.getByLabelText('Upstream request encoding')).toHaveAttribute('data-value', 'identity');
    expect(dialog.queryByRole('alert')).not.toBeInTheDocument();
    expect(dialog.getByRole('button', { name: 'Detecting...' })).toBeDisabled();

    betaDetection.resolve({ selected: 'identity', identity: { ok: true }, zstd: { ok: false } });
    await waitFor(() => expect(dialog.getByRole('button', { name: 'Auto-detect' })).toBeEnabled());
    expect(dialog.getByLabelText('Upstream request encoding')).toHaveAttribute('data-value', 'identity');
  });

  it('hides request encoding detection for non-Responses protocols', async () => {
    apiMock.get.mockResolvedValue({ providers: {}, known_api_types: ['responses', 'chat', 'anthropic', 'google'], provider_catalog: providerCatalog });
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Provider' }));
    const dialog = within(screen.getByRole('dialog', { name: 'Add Provider' }));
    await selectDropdown(dialog.getByLabelText('Protocol'), 'OpenAI Chat Completions');
    expect(dialog.queryByRole('button', { name: 'Auto-detect' })).not.toBeInTheDocument();
    expect(dialog.queryByLabelText('Detection model')).not.toBeInTheDocument();
  });
});

describe('SettingsPage', () => {
  it('requires explicit confirmation for an existing catalog and restores the toggle on cancel', async () => {
    const config = {
      server: { local_mode: false, local_mode_confirmed: false, request_body_limit_mb: 128 },
      codex_home: '/Users/test/.codex',
      model_catalog_configured: true,
      models: {},
    };
    apiMock.get.mockResolvedValue(config);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(SettingsPage);
    await screen.findByText(/Existing model catalog detected/);
    const toggle = await screen.findByLabelText('Local mode');
    await fireEvent.click(toggle);
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('existing model catalog'));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('/Users/test/.codex'));
    expect(toggle).not.toBeChecked();
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it('confirms a pre-existing unconfirmed local-mode config before saving', async () => {
    const config = {
      server: { local_mode: true, local_mode_confirmed: false, request_body_limit_mb: 128 },
      codex_home: '/Users/test/.codex',
      model_catalog_configured: false,
      models: {},
    };
    apiMock.get.mockResolvedValue(config);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(SettingsPage);
    await screen.findByText('/Users/test/.codex');
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/server', {
      proxy: '', request_body_limit_mb: 128, local_mode: true, local_mode_confirmed: true,
    }));
  });

  it('renders effective task defaults and preserves a missing configured model', async () => {
    const config = {
      server: { local_mode: true, local_mode_confirmed: true, request_body_limit_mb: 128 },
      models: { configured: {}, 'gpt-5.4': {}, 'gpt-5.4-mini': {} },
      codex: { auto_review_model_override: 'deleted-model', memories: {} },
    };
    apiMock.get.mockResolvedValue(config);
    render(SettingsPage);
    expect(await screen.findByText('Missing model: deleted-model')).toBeInTheDocument();
    expect(screen.getByText('Effective default: gpt-5.4')).toBeInTheDocument();
    expect(screen.getByText('Effective default: gpt-5.4-mini')).toBeInTheDocument();
    await fireEvent.click(screen.getByLabelText('Auto review model'));
    expect(within(screen.getAllByRole('listbox').at(-1)!).getByRole('option', { name: 'deleted-model (missing)' })).toBeInTheDocument();
    const consolidation = screen.getByLabelText('Memory consolidation model');
    await fireEvent.click(consolidation);
    await fireEvent.click(within(consolidation.parentElement!).getByRole('option', { name: 'configured' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save Codex settings' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/codex', {
      auto_review_model_override: 'deleted-model',
      memories: { consolidation_model: 'configured', extract_model: null },
    }));
  });

  it('fetches host IP and internal token only after their explicit reveal actions', async () => {
    const config = { server: { local_mode: false, local_mode_confirmed: false }, models: {} };
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/admin/api/diagnostics/host-ip') return Promise.resolve({ ok: true, ip: '172.17.0.1' });
      if (path === '/admin/api/internal-token') return Promise.resolve({ token: 'internal-secret' });
      return Promise.resolve(config);
    });
    render(SettingsPage);
    await screen.findByRole('button', { name: 'Show host IP' });
    expect(apiMock.get).toHaveBeenCalledTimes(1);
    await fireEvent.click(screen.getByRole('button', { name: 'Show host IP' }));
    expect(await screen.findByText('172.17.0.1')).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalledWith('/admin/api/internal-token');
    await fireEvent.click(screen.getByRole('button', { name: 'Reveal internal token' }));
    expect(await screen.findByText('internal-secret')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/admin/api/internal-token');
  });
});

describe('KeysPage', () => {
  it('shows a newly generated nested credential exactly after create', async () => {
    apiMock.get.mockResolvedValue({ keys: [] });
    apiMock.post.mockResolvedValue({ ok: true, key: { id: 'one', key: 'rsk-secret' } });
    render(KeysPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Generate Key' }));
    await fireEvent.input(screen.getByLabelText('Label (optional)'), { target: { value: 'Codex' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Generate' }));
    expect(await screen.findByDisplayValue('rsk-secret')).toBeInTheDocument();
  });
});

describe('ModelsPage', () => {
  it('shares the modal-width dropdown boundary between provider and profile', async () => {
    apiMock.get.mockResolvedValue({
      providers: { upstream: { api_type: 'chat' } },
      model_groups: {},
      tool_profile_presets: [{ id: 'profile', name: 'Profile', api_types: ['chat'] }],
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    const providerSelect = screen.getByLabelText('Provider');
    const profileSelect = document.getElementById('modelGroupToolProfile');
    expect(providerSelect.closest('.model-group-modal')).toBeInTheDocument();
    expect(providerSelect.closest('.model-group-dropdown-field')).toBeInTheDocument();
    expect(profileSelect?.closest('.model-group-dropdown-field')).toBeInTheDocument();
    expect(document.querySelectorAll('.model-group-dropdown-field')).toHaveLength(2);
    await fireEvent.click(profileSelect as HTMLButtonElement);
    expect(profileSelect?.closest('.model-group-dropdown-field')?.querySelector('.suu-dropdown__menu--left')).toBeInTheDocument();
  });

  it('writes only the model-group contract fields', async () => {
    apiMock.get.mockResolvedValue({ providers: { upstream: { api_type: 'chat' } }, model_groups: {}, tool_profile_presets: [] });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'demo-model' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', { provider: 'upstream', type: 'llm', models: { 'demo-model': {} } }));
  });

  it('offers only tool profiles matching the selected provider protocol', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        chat: { api_type: 'chat' },
        responses: { api_type: 'responses' },
        anthropic: { api_type: 'anthropic' },
        gemini: { api_type: 'google' },
      },
      model_groups: {},
      tool_profile_presets: [
        { id: 'builtin', name: 'Chat Default', api_types: ['chat'] },
        { id: 'responses-default', name: 'Responses Default', api_types: ['responses'] },
        { id: 'shared', name: 'Shared Profile', api_types: ['chat', 'responses', 'anthropic', 'google'] },
      ],
      tool_profile_passthrough_option: { id: 'passthrough', api_types: ['responses'] },
      tool_profiles: {
        'custom-chat': { api_types: ['chat'] },
        'custom-responses': { api_types: ['responses'] },
        'custom-anthropic': { api_types: ['anthropic'] },
        'custom-gemini': { api_types: ['google'] },
      },
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    const providerSelect = screen.getByLabelText('Provider');
    const profileSelect = screen.getByLabelText('Profile');

    await fireEvent.click(profileSelect);
    expect(screen.getByRole('option', { name: 'Chat Default' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'custom-chat' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Responses Default' })).toBeNull();

    await selectDropdown(providerSelect, 'responses');

    expect(screen.getByRole('option', { name: 'Responses Default' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Pass through' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'custom-responses' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Chat Default' })).toBeNull();

    await selectDropdown(providerSelect, 'anthropic');

    expect(screen.getByRole('option', { name: 'custom-anthropic' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Responses Default' })).toBeNull();
    expect(screen.queryByRole('option', { name: 'Pass through' })).toBeNull();

    await selectDropdown(providerSelect, 'gemini');

    expect(screen.getByRole('option', { name: 'custom-gemini' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Chat Default' })).toBeNull();
  });

  it('persists the Responses pass-through option outside actual profiles', async () => {
    apiMock.get.mockResolvedValue({
      providers: { upstream: { api_type: 'responses' } },
      model_groups: {},
      tool_profile_presets: [],
      tool_profiles: {},
      tool_profile_passthrough_option: { id: 'passthrough', api_types: ['responses'] },
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'demo-model' } });
    await selectDropdown(screen.getByLabelText('Profile'), 'Pass through');
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith(
      '/admin/api/config/model-groups/Main',
      {
        provider: 'upstream',
        type: 'llm',
        tool_profile: 'passthrough',
        models: { 'demo-model': {} },
      },
    ));
  });

  it('visually edits model metadata while preserving hidden preset fields', async () => {
    const preset = { slug: 'gpt-demo', display_name: 'GPT Demo', description: 'Preset description', identity: 'demo', priority: 2, context_window: 64000, input_modalities: ['text', 'image'], supported_reasoning_levels: ['low', 'high'], base_instructions: 'hidden system prompt' };
    apiMock.get.mockResolvedValue({ providers: { upstream: { api_type: 'chat' } }, model_groups: {}, tool_profile_presets: [], model_presets: [preset] });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'gpt-demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    const restorePreset = screen.getByRole('button', { name: 'Restore GPT Demo preset' });
    const displayName = screen.getByLabelText('Display Name');
    const identity = screen.getByLabelText('Identity');
    expect(identity).toHaveValue('demo');
    expect(restorePreset).toBeDisabled();
    expect(displayName).not.toHaveClass('model-info-field-modified');
    expect(identity).not.toHaveClass('model-info-field-modified');
    expect(screen.queryByText('hidden system prompt')).toBeNull();
    await fireEvent.input(displayName, { target: { value: 'Changed' } });
    expect(restorePreset).toBeEnabled();
    expect(displayName).toHaveClass('model-info-field-modified');
    expect(identity).not.toHaveClass('model-info-field-modified');
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', {
      provider: 'upstream', type: 'llm', models: { 'gpt-demo': { model_info: { ...preset, display_name: 'Changed', effective_context_window_percent: 95, auto_compact_token_limit: 51200 } } },
    }));
  });

  it('synchronizes GPT context presets with the editable numeric value', async () => {
    const preset = { slug: 'gpt-5.6-sol', display_name: 'GPT-5.6-Sol', description: 'GPT', identity: 'GPT', priority: 1, context_window: 272000, input_modalities: ['text'], supported_reasoning_levels: ['low'] };
    apiMock.get.mockResolvedValue({ providers: { upstream: { api_type: 'responses' } }, model_groups: {}, tool_profile_presets: [], model_presets: [preset], context_window_presets: { 'gpt-5.6-sol': [{ label: '272k（官方）', context_window: 272000, effective_context_window_percent: 95, auto_compact_token_limit: 217600 }, { label: '500k', context_window: 500000, effective_context_window_percent: 95, auto_compact_token_limit: 400000 }, { label: '800k', context_window: 800000, effective_context_window_percent: 95, auto_compact_token_limit: 640000 }, { label: '1M', context_window: 1000000, effective_context_window_percent: 95, auto_compact_token_limit: 800000 }] } });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'gpt-5.6-sol' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));

    const contextInput = screen.getByRole('spinbutton', { name: 'Context Window' });
    expect(contextInput).toHaveValue(272000);
    expect(screen.getByRole('spinbutton', { name: 'Effective Context Window (%)' })).toHaveValue(95);
    const compactLimit = screen.getByRole('spinbutton', { name: 'Auto Compact Token Limit' });
    expect(compactLimit).toHaveValue(217600);
    expect(screen.getByRole('button', { name: 'Context Window' })).toHaveTextContent('272k（官方）');
    await selectDropdown(screen.getByRole('button', { name: 'Context Window' }), '800k');
    expect(contextInput).toHaveValue(800000);
    expect(compactLimit).toHaveValue(640000);
    await fireEvent.input(contextInput, { target: { value: '500000' } });
    expect(screen.getByRole('button', { name: 'Context Window' })).toHaveTextContent('500k');
    expect(compactLimit).toHaveValue(640000);
    await fireEvent.input(contextInput, { target: { value: '123456' } });
    expect(screen.getByRole('button', { name: 'Context Window' })).toHaveTextContent('Custom');
    expect(compactLimit).toHaveValue(640000);
    await fireEvent.input(compactLimit, { target: { value: '123457' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Auto compact token limit must not exceed the context window.');
    await fireEvent.input(compactLimit, { target: { value: '100000' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', expect.objectContaining({ models: { 'gpt-5.6-sol': { model_info: expect.objectContaining({ context_window: 123456, effective_context_window_percent: 95, auto_compact_token_limit: 100000, context_window_presets: expect.arrayContaining([{ label: 'Custom', context_window: 123456, effective_context_window_percent: 95, auto_compact_token_limit: 100000 }]) }) } } })));
  });

  it('keeps all GPT presets visible when a saved override contains one current preset', async () => {
    const preset = { slug: 'gpt-5.6-sol', display_name: 'GPT-5.6-Sol', description: 'GPT', identity: 'GPT', priority: 1, context_window: 272000, input_modalities: ['text'], supported_reasoning_levels: ['low'] };
    const contextPresets = [{ label: '272k（官方）', context_window: 272000, effective_context_window_percent: 95, auto_compact_token_limit: 217600 }, { label: '500k', context_window: 500000, effective_context_window_percent: 95, auto_compact_token_limit: 400000 }, { label: '800k', context_window: 800000, effective_context_window_percent: 95, auto_compact_token_limit: 640000 }, { label: '1M', context_window: 1000000, effective_context_window_percent: 95, auto_compact_token_limit: 800000 }];
    apiMock.get.mockResolvedValue({ providers: { upstream: { api_type: 'responses' } }, model_groups: { Main: { provider: 'upstream', models: { 'gpt-5.6-sol': { model_info: { ...preset, context_window: 500000, effective_context_window_percent: 95, auto_compact_token_limit: 400000, context_window_presets: [contextPresets[1]] }, has_overrides: true } } } }, tool_profile_presets: [], model_presets: [preset], context_window_presets: { 'gpt-5.6-sol': contextPresets } });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Context Window' }));

    expect(screen.getByRole('option', { name: '272k（官方）' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '500k' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '800k' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '1M' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Custom' })).toBeInTheDocument();
  });

  it('returns the main model row to auto-detected after matching the preset again', async () => {
    const preset = { slug: 'gpt-demo', display_name: 'GPT Demo', description: 'Preset description', identity: 'demo', priority: 2, context_window: 64000, input_modalities: ['text'], supported_reasoning_levels: ['low', 'high'], base_instructions: 'hidden system prompt' };
    apiMock.get.mockResolvedValue({ providers: { upstream: { api_type: 'chat' } }, model_groups: {}, tool_profile_presets: [], model_presets: [preset] });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'gpt-demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    const displayName = screen.getByLabelText('Display Name');
    await fireEvent.input(displayName, { target: { value: 'Changed' } });
    await fireEvent.input(displayName, { target: { value: 'GPT Demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));

    expect(screen.getByText('Auto-detected: GPT Demo')).toBeInTheDocument();
    expect(screen.queryByText('Auto-detected: GPT Demo (modified)')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', {
      provider: 'upstream', type: 'llm', models: { 'gpt-demo': {} },
    }));
  });

  it('restores an initially unmodified provider-model row after a model info round trip', async () => {
    const preset = { slug: 'qwen3.7-plus', display_name: 'Qwen', description: 'Preset description', identity: 'qwen', priority: 2, context_window: 64000, input_modalities: ['text'], supported_reasoning_levels: ['low', 'high'] };
    apiMock.get.mockResolvedValue({
      providers: { opencode: { provider: 'opencode_go', api_type: 'chat' } },
      provider_catalog: { providers: { opencode_go: { label_key: 'provider.opencodeGo', runtime_capability_fields: ['temperature', 'top_p'], runtime_capabilities_by_model: { 'qwen3.7-plus': { temperature: 0.55, top_p: 1 } } } } },
      model_groups: { Main: { provider: 'opencode', models: { 'qwen3.7-plus': { model_info: preset, has_overrides: false } } } },
      tool_profile_presets: [], model_presets: [preset],
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByText('Auto-detected: Qwen')).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    await fireEvent.input(screen.getByLabelText('Display Name'), { target: { value: 'Changed' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    expect(screen.getByText('Auto-detected: Qwen (modified)')).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Restore Qwen preset' }));
    expect(screen.getByText('Auto-detected: Qwen')).toBeInTheDocument();
    expect(screen.queryByText('Auto-detected: Qwen (modified)')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', {
      provider: 'opencode', type: 'llm', models: { 'qwen3.7-plus': {} },
    }));
  });

  it('restores GLM after reasoning levels are toggled across separate edits', async () => {
    const preset = { slug: 'glm-5.2', display_name: 'GLM 5.2', description: 'Flagship model by Z.ai', identity: 'GLM 5.2 by z.ai', priority: 20, context_window: 1000000, input_modalities: ['text'], supported_reasoning_levels: ['high', 'max'] };
    apiMock.get.mockResolvedValue({
      providers: { opencode: { provider: 'opencode_go', api_type: 'chat' } },
      provider_catalog: { providers: { opencode_go: { label_key: 'provider.opencodeGo', runtime_capability_fields: [], runtime_capabilities_by_model: {} } } },
      model_groups: { Main: { provider: 'opencode', models: { 'glm-5.2': { model_info: preset, has_overrides: false } } } },
      tool_profile_presets: [], model_presets: [preset],
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    await fireEvent.click(screen.getByRole('checkbox', { name: 'high' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    expect(screen.getByText('Auto-detected: GLM 5.2 (modified)')).toBeInTheDocument();

    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    await fireEvent.click(screen.getByRole('checkbox', { name: 'high' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    expect(screen.getByText('Auto-detected: GLM 5.2')).toBeInTheDocument();
    expect(screen.queryByText('Auto-detected: GLM 5.2 (modified)')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', {
      provider: 'opencode', type: 'llm', models: { 'glm-5.2': {} },
    }));
  });

  it('shows OpenCode extra configuration only for a bound provider-model pair', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        opencode: { provider: 'opencode_go', api_type: 'chat' },
        openai: { provider: 'openai', api_type: 'chat' },
      },
      provider_catalog: {
        providers: {
          opencode_go: {
            label_key: 'provider.opencodeGo',
            runtime_capability_fields: ['temperature', 'top_p'],
            runtime_capabilities_by_model: { 'glm-5.2': {} },
          },
          openai: { label_key: 'provider.openai', runtime_capability_fields: [] },
        },
      },
      model_groups: {}, tool_profile_presets: [],
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'glm-5.2' } });
    await fireEvent.click(screen.getByRole('button', { name: 'opencode Extra Configuration' }));
    expect(screen.getByRole('dialog', { name: 'opencode Extra Configuration' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Model Information' })).toBeNull();
    await fireEvent.click(screen.getByRole('checkbox', { name: 'temperature' }));
    await fireEvent.input(screen.getByRole('spinbutton', { name: 'temperature' }), { target: { value: '0.4' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', {
      provider: 'opencode', type: 'llm', models: { 'glm-5.2': { runtime_capabilities: { temperature: 0.4 } } },
    }));
  });

  it('hides extra configuration when the provider-model pair has no preset', async () => {
    apiMock.get.mockResolvedValue({
      providers: { opencode: { provider: 'opencode_go', api_type: 'chat' } },
      provider_catalog: {
        providers: {
          opencode_go: {
            label_key: 'provider.opencodeGo',
            runtime_capability_fields: ['temperature', 'top_p'],
            runtime_capabilities_by_model: {
              'qwen3.7-plus': { temperature: 0.55, top_p: 1 },
            },
          },
        },
      },
      model_groups: {}, tool_profile_presets: [],
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'glm-5.2' } });

    expect(screen.queryByRole('button', { name: 'opencode Extra Configuration' })).toBeNull();
  });

  it('auto-fills OpenCode limits from the exact upstream model preset', async () => {
    apiMock.get.mockResolvedValue({
      providers: { opencode: { provider: 'opencode_go', api_type: 'chat' } },
      provider_catalog: {
        providers: {
          opencode_go: {
            label_key: 'provider.opencodeGo',
            runtime_capability_fields: ['temperature', 'top_p'],
            runtime_capabilities_by_model: {
              'qwen3.7-plus': { temperature: 0.55, top_p: 1 },
            },
          },
        },
      },
      model_groups: {}, tool_profile_presets: [],
    });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'public-qwen' } });
    await fireEvent.input(screen.getByLabelText('Upstream model'), { target: { value: 'qwen3.7-plus' } });
    await fireEvent.click(screen.getByRole('button', { name: 'opencode Extra Configuration' }));

    expect(screen.getByRole('spinbutton', { name: 'temperature' })).toHaveValue(0.55);
    expect(screen.getByRole('spinbutton', { name: 'top_p' })).toHaveValue(1);
    expect(screen.getByRole('checkbox', { name: 'temperature' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'top_p' })).toBeChecked();
  });
});
