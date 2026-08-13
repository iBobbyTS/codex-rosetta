// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminApp from '../src/admin/App.svelte';

async function selectDropdown(control: HTMLElement, value: string): Promise<void> {
  await fireEvent.click(control);
  await fireEvent.click(screen.getByRole('option', { name: new RegExp(`^${value}$`) }));
}

beforeEach(() => {
  localStorage.clear();
  history.replaceState({}, '', '/admin/providers');
  vi.restoreAllMocks();
});

describe('Admin application session', () => {
  it.each([401, 403])('returns the whole app to login after an API %s', async (status) => {
    localStorage.setItem('admin_token', 'expired-token');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input);
      if (path.endsWith('/auth-check')) {
        return new Response(JSON.stringify({ requires_auth: false }), { status: 200 });
      }
      return new Response(JSON.stringify({ error: 'Session expired' }), { status });
    });

    render(AdminApp);

    await screen.findByRole('navigation', { name: 'Admin pages' });
    await waitFor(() => expect(screen.getByRole('button', { name: /Sign in|Login/ })).toBeInTheDocument());
    expect(screen.queryByRole('navigation', { name: 'Admin pages' })).not.toBeInTheDocument();
    expect(localStorage.getItem('admin_token')).toBeNull();
  });

  it('persists theme selection and keeps restart notice until dismissed', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => String(input).endsWith('/auth-check')
      ? new Response(JSON.stringify({ requires_auth: false }), { status: 200 })
      : new Response(JSON.stringify({ providers: {}, model_groups: {} }), { status: 200 }));
    render(AdminApp);
    await screen.findByRole('navigation', { name: 'Admin pages' });
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe('#0f1117');
    expect(localStorage.getItem('codex-rosetta-theme')).toBe('dark');
    await selectDropdown(screen.getByLabelText('Theme'), 'Dark');
    expect(localStorage.getItem('codex-rosetta-theme')).toBe('dark');
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe('#0f1117');
    expect(document.documentElement.style.getPropertyValue('--provider-logo-filter')).toBe('invert(1)');
    window.dispatchEvent(new Event('admin-restart-required'));
    const restartText = 'Codex configuration changed. Restart Codex for the changes to take effect.';
    expect(await screen.findByText(restartText)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(screen.queryByText(restartText)).not.toBeInTheDocument();
  });

  it('keeps Search Test provider failures inside the result card', async () => {
    history.replaceState({}, '', '/admin/network-search');
    localStorage.setItem('admin_token', 'valid-token');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith('/auth-check')) {
        return new Response(JSON.stringify({ requires_auth: true }), { status: 200 });
      }
      if (path.endsWith('/network-search/test') && init?.method === 'POST') {
        return new Response(JSON.stringify({ error: { message: 'Insufficient account balance' } }), { status: 403 });
      }
      if (path.endsWith('/network-search/status')) {
        return new Response(JSON.stringify({ configured: true, service_online: true }), { status: 200 });
      }
      if (path.endsWith('/config')) {
        return new Response(JSON.stringify({
          config_path: '/tmp/config.jsonc',
          providers: { TURNING: { api_type: 'responses' } },
          web_search_contract: {
            provider_types: ['tavily', 'configured_responses_provider', 'self_hosted_google', 'self_hosted_bing', 'self_hosted_bing_browser'],
            responses_models: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'],
            max_providers: 32,
          },
          server: { web_search: { providers: [{ id: 'responses', provider: 'configured_responses_provider', responses_provider: 'TURNING', responses_model: 'gpt-5.6-sol' }] } },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ error: 'Unexpected request' }), { status: 500 });
    });

    render(AdminApp);

    await screen.findByRole('navigation', { name: 'Admin pages' });
    await fireEvent.click(await screen.findByRole('button', { name: 'Test' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Search test failed');
    expect(alert).not.toHaveTextContent('Insufficient account balance');
    expect(screen.getByRole('navigation', { name: 'Admin pages' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Sign in|Login/ })).not.toBeInTheDocument();
    expect(localStorage.getItem('admin_token')).toBe('valid-token');
  });
});
