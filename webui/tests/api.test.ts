import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_EXPIRED_EVENT, DEFAULT_API_TIMEOUT_MS, RESTART_REQUIRED_EVENT, request, setAdminToken } from '../src/admin/lib/api';

describe('admin API client', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('allows one minute for ordinary Admin API operations', () => {
    expect(DEFAULT_API_TIMEOUT_MS).toBe(60_000);
  });

  it('adds the admin token and serializes JSON', async () => {
    setAdminToken('sentinel-token');
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await request('/admin/api/config', { method: 'PUT', body: { enabled: true } });
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get('X-Admin-Token')).toBe('sentinel-token');
    expect(init?.body).toBe(JSON.stringify({ enabled: true }));
  });

  it.each([401, 403])('clears the token and broadcasts rejected authorization (%s)', async (status) => {
    setAdminToken('expired');
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired, { once: true });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'Unauthorized' }), { status }),
    );
    await expect(request('/admin/api/config')).rejects.toEqual(
      expect.objectContaining({ status, message: 'Unauthorized' }),
    );
    expect(localStorage.getItem('admin_token')).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
  });

  it.each([401, 403])('keeps request-local authorization failures inside the caller (%s)', async (status) => {
    setAdminToken('valid-admin-session');
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired, { once: true });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        error: 'Search test authorization failed',
        code: 'network_search_test_authorization_failed',
      }), { status }),
    );

    await expect(request('/admin/api/network-search/test', { responseEffects: 'local' })).rejects.toEqual(
      expect.objectContaining({
        status,
        message: 'Search test authorization failed',
        code: 'network_search_test_authorization_failed',
      }),
    );
    expect(localStorage.getItem('admin_token')).toBe('valid-admin-session');
    expect(expired).not.toHaveBeenCalled();
  });

  it('keeps generic nested error handling outside the Search Test trust boundary', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: { message: 'Upstream search failed', type: 'upstream_error' } }), { status: 502 }),
    );

    await expect(request('/admin/api/request-log/example')).rejects.toEqual(
      expect.objectContaining({ status: 502, message: 'Upstream search failed' }),
    );
  });

  it('renders a controlled string error envelope', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'Search is unavailable' }), { status: 503 }),
    );

    await expect(request('/admin/api/network-search/test')).rejects.toEqual(
      expect.objectContaining({ status: 503, message: 'Search is unavailable' }),
    );
  });

  it.each([
    ['plain text', 'provider secret at http://internal.example', 'text/plain'],
    ['JSON primitive string', JSON.stringify('provider secret at http://internal.example'), 'application/json'],
    ['object without an error envelope', JSON.stringify({ message: 'provider secret at http://internal.example' }), 'application/json'],
    ['unrecognized error object', JSON.stringify({ error: { detail: 'provider secret at http://internal.example' } }), 'application/json'],
    ['non-string error primitive', JSON.stringify({ error: 3711 }), 'application/json'],
  ])('does not expose an uncontrolled %s response', async (_name, body, contentType) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(body, { status: 502, headers: { 'Content-Type': contentType } }),
    );

    await expect(request('/admin/api/network-search/test')).rejects.toEqual(
      expect.objectContaining({ status: 502, message: 'Request failed (502)' }),
    );
  });

  it('rejects paths outside the admin API boundary', async () => {
    await expect(request('/v1/responses')).rejects.toThrow('Admin API path required');
  });

  it('broadcasts the Codex restart response header without discarding the body', async () => {
    const restart = vi.fn(); window.addEventListener(RESTART_REQUIRED_EVENT, restart, { once: true });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'X-Codex-Restart-Required': 'true' } }));
    await expect(request('/admin/api/config/codex')).resolves.toEqual({ ok: true });
    expect(restart).toHaveBeenCalledOnce();
  });

  it('does not broadcast response headers for request-local effects', async () => {
    const restart = vi.fn(); window.addEventListener(RESTART_REQUIRED_EVENT, restart, { once: true });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'X-Codex-Restart-Required': 'true' } }));
    await expect(request('/admin/api/network-search/test', { responseEffects: 'local' })).resolves.toEqual({ ok: true });
    expect(restart).not.toHaveBeenCalled();
  });
});
