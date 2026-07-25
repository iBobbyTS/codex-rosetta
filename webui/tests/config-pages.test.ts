// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import KeysPage from '../src/admin/pages/KeysPage.svelte';
import ModelsPage from '../src/admin/pages/ModelsPage.svelte';
import ProvidersPage from '../src/admin/pages/ProvidersPage.svelte';
import SettingsPage from '../src/admin/pages/SettingsPage.svelte';

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));

const providerCatalog = {
  api_types: ['responses', 'chat', 'anthropic', 'google'],
  providers: {
    openai: { label_key: 'provider.openai', recommended_api_type: 'responses', adapted_api_types: { chat: 'openai', responses: 'openai_responses' }, known_supported_api_types: ['chat', 'responses'], variants: { official: { endpoints: { chat: 'https://api.openai.com/v1', responses: 'https://api.openai.com/v1' } }, custom: { endpoints: {} } } },
    moonshot: { label_key: 'provider.kimi', recommended_api_type: 'chat', adapted_api_types: { chat: 'moonshot' }, known_supported_api_types: ['chat', 'anthropic'], variants: { china: { endpoints: { chat: 'https://api.moonshot.cn/v1' } }, international: { endpoints: { chat: 'https://api.moonshot.ai/v1' } }, custom: { endpoints: {} } } },
    deepseek: { label_key: 'provider.deepseek', recommended_api_type: 'chat', adapted_api_types: { chat: 'deepseek' }, known_supported_api_types: ['chat', 'anthropic'], variants: { official: { endpoints: { chat: 'https://api.deepseek.com' } }, custom: { endpoints: {} } } },
    custom: { label_key: 'provider.custom', recommended_api_type: 'chat', adapted_api_types: {}, known_supported_api_types: [], variants: { custom: { endpoints: {} } } },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem('codex-rosetta-lang', 'en');
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
    expect(screen.getByLabelText('Provider')).toHaveValue('openai');
    expect(screen.getByLabelText('Provider variant')).toHaveValue('official');
    expect(screen.getByDisplayValue('http://proxy.example:8080')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('provider-secret')).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith('/admin/api/config/providers/official/key');
    await fireEvent.click(within(screen.getByRole('dialog', { name: /Edit Provider/ })).getByRole('button', { name: 'Save' }));
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
      api_key: 'provider-secret',
    });
    expect(body).not.toHaveProperty('preset');
    expect(body).not.toHaveProperty('base');
    expect(body).not.toHaveProperty('variant');
    const bodyLimit = screen.getByLabelText('Maximum Request Body') as HTMLSelectElement;
    expect(Array.from(bodyLimit.options, (option) => option.value)).toEqual(['64', '128', '256', '512', '1024', 'unlimited']);
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
    expect(screen.getByLabelText('Provider')).toHaveValue('moonshot');
    expect(screen.getByLabelText('Provider variant')).toHaveValue('international');
    await fireEvent.click(within(screen.getByRole('dialog', { name: 'Edit Provider' })).getByRole('button', { name: 'Cancel' }));
    await fireEvent.click(edits[1]);
    expect(screen.getByLabelText('Provider')).toHaveValue('deepseek');
    expect(screen.getByLabelText('Provider variant')).toHaveValue('custom');
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
    const protocol = within(screen.getByRole('dialog', { name: 'Add Provider' })).getByLabelText('Protocol') as HTMLSelectElement;
    expect(Array.from(protocol.options, (option) => [option.value, option.textContent])).toEqual([
      ['responses', 'OpenAI Responses'],
      ['chat', 'OpenAI Chat Completions'],
      ['anthropic', 'Anthropic Messages'],
      ['google', 'Google GenAI'],
    ]);
    expect(protocol).not.toHaveTextContent('open_responses');
    expect(protocol).not.toHaveTextContent('openai_chat');
    expect(protocol).not.toHaveTextContent('openai_responses');
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
    expect(screen.getByRole('option', { name: 'deleted-model (missing)' })).toBeInTheDocument();
    await fireEvent.change(screen.getByLabelText('Memory consolidation model'), { target: { value: 'configured' } });
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

    expect(within(profileSelect).getByRole('option', { name: 'Chat Default' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'custom-chat' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(within(profileSelect).queryByRole('option', { name: 'Responses Default' })).toBeNull();

    await fireEvent.change(providerSelect, { target: { value: 'responses' } });

    expect(within(profileSelect).getByRole('option', { name: 'Responses Default' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'Pass through' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'custom-responses' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(within(profileSelect).queryByRole('option', { name: 'Chat Default' })).toBeNull();

    await fireEvent.change(providerSelect, { target: { value: 'anthropic' } });

    expect(within(profileSelect).getByRole('option', { name: 'custom-anthropic' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(within(profileSelect).queryByRole('option', { name: 'Responses Default' })).toBeNull();
    expect(within(profileSelect).queryByRole('option', { name: 'Pass through' })).toBeNull();

    await fireEvent.change(providerSelect, { target: { value: 'gemini' } });

    expect(within(profileSelect).getByRole('option', { name: 'custom-gemini' })).toBeInTheDocument();
    expect(within(profileSelect).getByRole('option', { name: 'Shared Profile' })).toBeInTheDocument();
    expect(within(profileSelect).queryByRole('option', { name: 'Chat Default' })).toBeNull();
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
    await fireEvent.change(screen.getByLabelText('Profile'), { target: { value: 'passthrough' } });
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

  it('detects, modifies, restores and saves all model preset metadata', async () => {
    const preset = { slug: 'gpt-demo', display_name: 'GPT Demo', description: 'Preset description', identity: 'demo', priority: 2, context_window: 64000, input_modalities: ['text', 'image'], supported_reasoning_levels: ['low', 'high'] };
    apiMock.get.mockResolvedValue({ providers: { upstream: { api_type: 'chat' } }, model_groups: {}, tool_profile_presets: [], model_presets: [preset] });
    render(ModelsPage);
    await fireEvent.click(await screen.findByRole('button', { name: '+ Add Model Group' }));
    await fireEvent.input(screen.getByLabelText('Model Group Name'), { target: { value: 'Main' } });
    await fireEvent.input(screen.getByLabelText('Exposed model'), { target: { value: 'gpt-demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Enter Model Information Manually' }));
    const modelInfo = screen.getByLabelText('model_info') as HTMLTextAreaElement;
    expect(JSON.parse(modelInfo.value)).toEqual(preset);
    await fireEvent.input(modelInfo, { target: { value: JSON.stringify({ ...preset, display_name: 'Changed' }) } });
    await fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledWith('/admin/api/config/model-groups/Main', {
      provider: 'upstream', type: 'llm', models: { 'gpt-demo': { model_info: { ...preset, display_name: 'Changed' } } },
    }));
  });
});
