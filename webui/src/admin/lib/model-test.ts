import { api } from './api';

export type ModelTestKind = 'text' | 'stream' | 'tools' | 'vision' | 'reasoning';

export type TestTaskResult = {
  status: 'pending' | 'done' | 'error' | 'cancelled';
  status_code?: number;
  body?: unknown;
  error?: string;
};

export function buildModelTestPayload(model: string, kind: ModelTestKind): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    model,
    max_output_tokens: 256,
    input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Reply with a short gateway test response.' }] }],
  };
  if (kind === 'stream') payload.stream = true;
  if (kind === 'reasoning') payload.reasoning = { effort: 'low' };
  if (kind === 'tools') {
    payload.tools = [{
      type: 'function', name: 'get_weather', description: 'Get weather for a city',
      parameters: { type: 'object', properties: { location: { type: 'string' } }, required: ['location'] },
    }];
  }
  if (kind === 'vision') {
    payload.input = [{
      type: 'message', role: 'user', content: [
        { type: 'input_text', text: 'Describe this test image briefly.' },
        { type: 'input_image', image_url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==' },
      ],
    }];
  }
  return payload;
}

export function safeUsageRows(value: unknown): Array<[string, number]> {
  if (!value || typeof value !== 'object') return [];
  const rows: Array<[string, number]> = [];
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === 'number' && Number.isSafeInteger(item) && item >= 0) rows.push([key, item]);
  }
  return rows;
}

export function responseText(body: unknown): string {
  if (!body || typeof body !== 'object') return typeof body === 'string' ? body : JSON.stringify(body, null, 2);
  const value = body as Record<string, unknown>;
  if (typeof value.output_text === 'string') return value.output_text;
  return JSON.stringify(body, null, 2);
}

export async function pollModelTest(
  taskId: string,
  signal: AbortSignal,
  wait: (milliseconds: number, signal: AbortSignal) => Promise<void> = delay,
  timeoutMs = 120_000,
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
