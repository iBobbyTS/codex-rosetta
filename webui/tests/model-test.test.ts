import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildModelTestPayload, DEFAULT_MODEL_TEST_TIMEOUT_MS, pollModelTest, rawResponseText, responseText, safeUsageRows } from '../src/admin/lib/model-test';

const apiMock = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));

beforeEach(() => vi.clearAllMocks());

describe('model testing', () => {
  it('allows fifteen minutes for a complete model test', () => {
    expect(DEFAULT_MODEL_TEST_TIMEOUT_MS).toBe(900_000);
  });

  it('polls serially until a completed task without contacting a provider directly', async () => {
    apiMock.post.mockResolvedValueOnce({ status: 'pending' }).mockResolvedValueOnce({ status: 'done', status_code: 200, body: { output_text: 'ok' } });
    const wait = vi.fn().mockResolvedValue(undefined);
    const result = await pollModelTest('task-one', new AbortController().signal, wait);
    expect(result.status).toBe('done');
    expect(apiMock.post).toHaveBeenNthCalledWith(1, '/admin/api/test/task-one/poll', undefined, expect.any(AbortSignal));
    expect(apiMock.post).toHaveBeenCalledTimes(2);
  });

  it('builds only the basic text test through the Responses endpoint contract', () => {
    expect(buildModelTestPayload('demo')).toEqual({
      model: 'demo',
      store: false,
      stream: true,
      input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'hi' }] }],
    });
  });

  it('shows only the final model answer for a buffered Responses event stream', () => {
    const raw = [
      'event: response.created',
      'data: {"type":"response.created"}',
      '',
      'event: response.output_text.delta',
      'data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"hello "}',
      '',
      'event: response.output_text.delta',
      'data: {"type":"response.output_text.delta","output_index":0,"content_index":0,"delta":"world"}',
      '',
      'event: response.output_text.done',
      'data: {"type":"response.output_text.done","output_index":0,"content_index":0,"text":"Hello world"}',
      '',
      'event: response.completed',
      'data: {"type":"response.completed","response":{"status":"completed"}}',
      '',
    ].join('\n');

    expect(responseText(raw)).toBe('Hello world');
  });

  it('falls back to delta text and leaves non-SSE strings unchanged', () => {
    const deltaOnly = [
      'event: response.output_text.delta',
      'data: {"type":"response.output_text.delta","delta":"partial answer"}',
      '',
    ].join('\n');

    expect(responseText(deltaOnly)).toBe('partial answer');
    expect(responseText('plain response')).toBe('plain response');
  });

  it('preserves real line breaks for raw string responses', () => {
    expect(rawResponseText('event: one\ndata: first\n\nevent: two\ndata: second')).toBe(
      'event: one\ndata: first\n\nevent: two\ndata: second',
    );
    expect(rawResponseText({ status: 'completed' })).toBe('{\n  "status": "completed"\n}');
  });

  it('renders only non-negative safe integer usage without coercing hostile values', () => {
    const valueOf = vi.fn(() => 999);
    const hostile = { input_tokens: { valueOf }, output_tokens: 7, total_tokens: Number.MAX_SAFE_INTEGER + 1, negative: -1 };
    expect(safeUsageRows(hostile)).toEqual([['output_tokens', 7]]);
    expect(valueOf).not.toHaveBeenCalled();
  });

  it('stops pending polling at a bounded deadline', async () => {
    apiMock.post.mockResolvedValue({ status: 'pending' });
    let clock = 0;
    const wait = vi.fn(async (milliseconds: number) => { clock += milliseconds; });
    await expect(pollModelTest('task-timeout', new AbortController().signal, wait, 900, () => clock)).rejects.toEqual(expect.objectContaining({ name: 'TimeoutError', message: 'Test timed out' }));
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(wait).toHaveBeenCalledTimes(2);
  });
});
