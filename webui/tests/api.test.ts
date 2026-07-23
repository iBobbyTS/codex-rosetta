import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTH_EXPIRED_EVENT, RESTART_REQUIRED_EVENT, request, setAdminToken } from '../src/admin/lib/api';

describe('admin API client', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
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

  it('rejects paths outside the admin API boundary', async () => {
    await expect(request('/v1/responses')).rejects.toThrow('Admin API path required');
  });

  it('broadcasts the Codex restart response header without discarding the body', async () => {
    const restart = vi.fn(); window.addEventListener(RESTART_REQUIRED_EVENT, restart, { once: true });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'X-Codex-Restart-Required': 'true' } }));
    await expect(request('/admin/api/config/codex')).resolves.toEqual({ ok: true });
    expect(restart).toHaveBeenCalledOnce();
  });
});
