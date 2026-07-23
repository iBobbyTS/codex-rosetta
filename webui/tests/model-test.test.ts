import { beforeEach, describe, expect, it, vi } from 'vitest';
import { buildModelTestPayload, pollModelTest, safeUsageRows } from '../src/admin/lib/model-test';

const apiMock = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));

beforeEach(() => vi.clearAllMocks());

describe('model testing', () => {
  it('polls serially until a completed task without contacting a provider directly', async () => {
    apiMock.post.mockResolvedValueOnce({ status: 'pending' }).mockResolvedValueOnce({ status: 'done', status_code: 200, body: { output_text: 'ok' } });
    const wait = vi.fn().mockResolvedValue(undefined);
    const result = await pollModelTest('task-one', new AbortController().signal, wait);
    expect(result.status).toBe('done');
    expect(apiMock.post).toHaveBeenNthCalledWith(1, '/admin/api/test/task-one/poll', undefined, expect.any(AbortSignal));
    expect(apiMock.post).toHaveBeenCalledTimes(2);
  });

  it('builds only the basic text test through the Responses endpoint contract', () => {
    expect(buildModelTestPayload('demo', 'Reply with a short gateway test response.')).toEqual({
      model: 'demo',
      max_output_tokens: 256,
      input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Reply with a short gateway test response.' }] }],
    });
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
