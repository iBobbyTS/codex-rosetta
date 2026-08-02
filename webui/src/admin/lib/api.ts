const TOKEN_KEY = 'admin_token';
export const DEFAULT_API_TIMEOUT_MS = 60_000;
export const AUTH_EXPIRED_EVENT = 'admin-auth-expired';
export const RESTART_REQUIRED_EVENT = 'admin-restart-required';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
  auth?: boolean;
  responseEffects?: 'global' | 'local';
};

function errorMessage(payload: unknown, status: number): string {
  if (!payload || typeof payload !== 'object' || !('error' in payload)) {
    return `Request failed (${status})`;
  }
  const error = (payload as { error: unknown }).error;
  if (error && typeof error === 'object' && 'message' in error) {
    const message = (error as { message: unknown }).message;
    if (typeof message === 'string' && message) return message;
  }
  if (typeof error === 'string' && error) return error;
  if (error !== undefined && error !== null && typeof error !== 'object') return String(error);
  try {
    const serialized = JSON.stringify(error);
    if (serialized) return serialized;
  } catch {
    // Fall through to the status-based message for non-serializable envelopes.
  }
  return `Request failed (${status})`;
}

export function getAdminToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? '';
}

export function setAdminToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (!path.startsWith('/admin/api/')) throw new Error('Admin API path required');
  const { auth = true, body: requestBody, responseEffects = 'global', timeoutMs, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs ?? DEFAULT_API_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  fetchOptions.signal?.addEventListener('abort', onAbort, { once: true });
  const headers = new Headers(fetchOptions.headers);
  if (auth) {
    const token = getAdminToken();
    if (token) headers.set('X-Admin-Token', token);
  }
  let body: BodyInit | undefined;
  if (requestBody !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(requestBody);
  }
  try {
    const response = await fetch(path, {
      ...fetchOptions,
      body,
      headers,
      signal: controller.signal,
      cache: 'no-store',
    });
    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      if (responseEffects === 'global' && (response.status === 401 || response.status === 403)) {
        setAdminToken('');
        window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
      }
      const detail = errorMessage(payload, response.status);
      const code = payload && typeof payload === 'object' && 'code' in payload
        ? String((payload as { code: unknown }).code)
        : undefined;
      throw new ApiError(detail, response.status, code);
    }
    if (responseEffects === 'global' && response.headers.get('X-Codex-Restart-Required')?.toLowerCase() === 'true') {
      window.dispatchEvent(new Event(RESTART_REQUIRED_EVENT));
    }
    return payload as T;
  } finally {
    window.clearTimeout(timeout);
    fetchOptions.signal?.removeEventListener('abort', onAbort);
  }
}

export async function download(path: string, signal?: AbortSignal): Promise<Blob> {
  if (!path.startsWith('/admin/api/')) throw new Error('Admin API path required');
  const headers = new Headers(); const token = getAdminToken(); if (token) headers.set('X-Admin-Token', token);
  const response = await fetch(path, { headers, signal, cache: 'no-store' });
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) { setAdminToken(''); window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT)); }
    throw new ApiError(`Request failed (${response.status})`, response.status);
  }
  return response.blob();
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: 'POST', body, signal }),
  put: <T>(path: string, body: unknown, signal?: AbortSignal) =>
    request<T>(path, { method: 'PUT', body, signal }),
  del: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: 'DELETE', signal }),
};
