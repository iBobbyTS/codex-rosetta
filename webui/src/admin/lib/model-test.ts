import { api } from './api';

export const DEFAULT_MODEL_TEST_TIMEOUT_MS = 900_000;

export type TestTaskResult = {
  status: 'pending' | 'done' | 'error' | 'cancelled';
  status_code?: number;
  body?: unknown;
  error?: string;
};

export function buildModelTestPayload(model: string): Record<string, unknown> {
  return {
    model,
    store: false,
    stream: true,
    input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'hi' }] }],
  };
}

export function safeUsageRows(value: unknown): Array<[string, number]> {
  if (!value || typeof value !== 'object') return [];
  const rows: Array<[string, number]> = [];
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === 'number' && Number.isSafeInteger(item) && item >= 0) rows.push([key, item]);
  }
  return rows;
}

function streamedResponseText(body: string): string | null {
  if (!body.includes('event: response.') || !body.includes('data:')) return null;

  const textParts = new Map<string, { delta: string; done?: string }>();
  let eventType = '';
  let dataLines: string[] = [];

  const flushEvent = (): void => {
    if (!dataLines.length) {
      eventType = '';
      return;
    }

    try {
      const parsed = JSON.parse(dataLines.join('\n')) as unknown;
      if (parsed && typeof parsed === 'object') {
        const event = parsed as Record<string, unknown>;
        const type = typeof event.type === 'string' ? event.type : eventType;
        const key = `${String(event.output_index ?? 0)}:${String(event.content_index ?? 0)}`;
        const current = textParts.get(key) ?? { delta: '' };

        if (type === 'response.output_text.delta' && typeof event.delta === 'string') {
          current.delta += event.delta;
          textParts.set(key, current);
        } else if (type === 'response.output_text.done' && typeof event.text === 'string') {
          current.done = event.text;
          textParts.set(key, current);
        }
      }
    } catch {
      // Keep the original response visible when an SSE data record is malformed.
    }

    eventType = '';
    dataLines = [];
  };

  for (const line of body.replaceAll('\r\n', '\n').split('\n')) {
    if (!line) {
      flushEvent();
    } else if (line.startsWith('event:')) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  flushEvent();

  const output = [...textParts.values()].map((part) => part.done ?? part.delta).join('');
  return output || null;
}

export function responseText(body: unknown): string {
  if (typeof body === 'string') return streamedResponseText(body) ?? body;
  if (!body || typeof body !== 'object') return JSON.stringify(body, null, 2);
  const value = body as Record<string, unknown>;
  if (typeof value.output_text === 'string') return value.output_text;
  return JSON.stringify(body, null, 2);
}

export function rawResponseText(body: unknown): string {
  return typeof body === 'string' ? body : JSON.stringify(body, null, 2);
}

export async function pollModelTest(
  taskId: string,
  signal: AbortSignal,
  wait: (milliseconds: number, signal: AbortSignal) => Promise<void> = delay,
  timeoutMs = DEFAULT_MODEL_TEST_TIMEOUT_MS,
  now: () => number = Date.now,
): Promise<TestTaskResult> {
  const deadline = now() + timeoutMs;
  for (;;) {
    const remaining = deadline - now();
    if (remaining <= 0) throw new DOMException('Test timed out', 'TimeoutError');
    await wait(Math.min(500, remaining), signal);
    if (now() >= deadline) throw new DOMException('Test timed out', 'TimeoutError');
    const result = await api.post<TestTaskResult>(`/admin/api/test/${encodeURIComponent(taskId)}/poll`, undefined, signal);
    if (result.status !== 'pending') return result;
  }
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(new DOMException('Cancelled', 'AbortError'));
    }, { once: true });
  });
}
