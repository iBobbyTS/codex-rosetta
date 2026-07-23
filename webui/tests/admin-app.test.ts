// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminApp from '../src/admin/App.svelte';

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
    await fireEvent.change(screen.getByLabelText('Theme'), { target: { value: 'dark' } });
    expect(localStorage.getItem('codex-rosetta-theme')).toBe('dark');
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe('#0f1117');
    expect(document.documentElement.style.getPropertyValue('--provider-logo-filter')).toBe('invert(1)');
    window.dispatchEvent(new Event('admin-restart-required'));
    const restartText = 'Codex configuration changed. Restart Codex for the changes to take effect.';
    expect(await screen.findByText(restartText)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(screen.queryByText(restartText)).not.toBeInTheDocument();
  });
});
