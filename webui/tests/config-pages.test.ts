// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
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
  it('persists the provider while deriving its variant from that provider and URL', async () => {
    const config = {
      providers: { official: { provider: 'openai', base_url: 'https://api.openai.com/v1', api_type: 'responses', proxy: 'http://proxy.example:8080' } },
      known_api_types: ['responses', 'chat', 'anthropic', 'google'],
      provider_catalog: providerCatalog,
      registered_shims: [{ name: 'openai', logo: '/admin/assets/openai.svg' }],
      credential_visible: true,
    };
    apiMock.get.mockImplementation((path: string) => path.endsWith('/key')
      ? Promise.resolve({ api_key: 'provider-secret' })
      : Promise.resolve(config));
    render(ProvidersPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByLabelText('Provider')).toHaveAttribute('data-value', 'openai');
    expect(screen.getByLabelText('Provider variant')).toHaveAttribute('data-value', 'official');
    expect(screen.getByDisplayValue('http://proxy.example:8080')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('provider-secret')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/admin/api/config/providers/official/key');
    const dialog = within(screen.getByRole('dialog', { name: /Edit Provider/ }));
    expect(dialog.getAllByLabelText(/^API Key/)).toHaveLength(1);
    expect(dialog.queryByRole('button', { name: /Add key/i })).not.toBeInTheDocument();
    expect(dialog.queryByRole('button', { name: /Remove key/i })).not.toBeInTheDocument();
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    expect(screen.getByRole('status')).toHaveTextContent("Provider 'official' saved");
    expect(screen.getByRole('status')).not.toHaveTextContent('{name}');
    const body = apiMock.put.mock.calls[0][1];
    expect(body).toEqual({
      provider: 'openai',
      base_url: 'https://api.openai.com/v1',
      proxy: 'http://proxy.example:8080',
      allow_redirects: false,
      api_type: 'responses',
      force_rosetta_compaction: false,
      api_key: 'provider-secret',
    });
    expect(body).not.toHaveProperty('preset');
    expect(body).not.toHaveProperty('base');
    expect(body).not.toHaveProperty('variant');
    await fireEvent.click(screen.getByLabelText('Maximum Request Body'));
    expect(within(screen.getByRole('listbox')).getAllByRole('option').map((option) => option.getAttribute('data-value'))).toEqual(['64', '128', '256', '512', '1024', 'unlimited']);
  });

  it('derives a child option from persisted provider and URL without using api_type', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        kimi: { provider: 'moonshot', base_url: 'https://api.moonshot.ai/v1', api_type: 'responses' },
        mismatch: { provider: 'deepseek', base_url: 'https://api.openai.com/v1', api_type: 'chat' },
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
    await fireEvent.input(dialog.getByLabelText(/^API Key/), { target: { value: 'sk-test' } });
    await fireEvent.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    expect(apiMock.put.mock.calls[0][1]).not.toHaveProperty('soft_interrupt');
  });

  it('preserves explicitly disabled late-developer cache compatibility when editing and cloning', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        deepseek: {
          provider: 'deepseek',
          base_url: 'https://api.deepseek.com',
          api_type: 'chat',
          soft_interrupt: false,
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

  it('shows forced prompt compaction only for Responses and preserves it when editing and cloning', async () => {
    apiMock.get.mockResolvedValue({
      providers: {
        cockpit: {
          provider: 'openai',
          base_url: 'https://cockpit.example/v1',
          api_type: 'responses',
          force_rosetta_compaction: true,
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
      provider: 'upstream', type: 'llm', models: { 'gpt-demo': { model_info: { ...preset, display_name: 'Changed' } } },
    }));
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
