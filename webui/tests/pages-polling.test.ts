import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSerialPoll } from '../src/admin/lib/polling';

afterEach(() => vi.useRealTimers());

describe('createSerialPoll', () => {
  it('waits for the active request before scheduling another', async () => {
    vi.useFakeTimers();
    let resolve!: () => void;
    const task = vi.fn(() => new Promise<void>((done) => { resolve = done; }));
    const poll = createSerialPoll(task, 5_000);
    poll.start();
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(task).toHaveBeenCalledTimes(1);
    resolve();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(4_999);
    expect(task).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(task).toHaveBeenCalledTimes(2);
    poll.stop();
  });

  it('aborts the active request when stopped', () => {
    const task = vi.fn((signal: AbortSignal) => new Promise<void>(() => {
      signal.addEventListener('abort', () => undefined);
    }));
    const poll = createSerialPoll(task, 5_000);
    poll.start();
    const signal = task.mock.calls[0][0];
    poll.stop();
    expect(signal.aborted).toBe(true);
  });
});
