// @vitest-environment-options { "customExportConditions": ["browser"] }
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ModelTestPanel from '../src/admin/components/ModelTestPanel.svelte';

const apiMock = vi.hoisted(() => ({ post: vi.fn(), del: vi.fn() }));
const pollMock = vi.hoisted(() => vi.fn());
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));
vi.mock('../src/admin/lib/model-test', async (importOriginal) => ({
  ...await importOriginal<typeof import('../src/admin/lib/model-test')>(),
  pollModelTest: pollMock,
}));

beforeEach(() => { vi.clearAllMocks(); apiMock.post.mockResolvedValue({ task_id: 'task-one' }); apiMock.del.mockResolvedValue({ ok: true }); });

describe('ModelTestPanel', () => {
  it('keeps the result dialog left-aligned inside the right-aligned model action cell', () => {
    const adminStyles = readFileSync(resolve('src/admin/styles.css'), 'utf8');
    expect(adminStyles).toMatch(/\.modal\s*\{[^}]*text-align:\s*left;/s);
    expect(adminStyles).toMatch(/\.modal-actions\s*\{[^}]*justify-content:\s*flex-end;/s);
  });

  it('does not call the test API until the user explicitly starts a test', async () => {
    pollMock.mockResolvedValue({ status: 'done', status_code: 200, body: { output_text: 'safe result' } });
    render(ModelTestPanel, { props: { model: 'demo' } });
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'More tests for demo' })).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await waitFor(() => expect(apiMock.post).toHaveBeenCalledWith('/admin/api/test', { endpoint: '/v1/responses', payload: {
      model: 'demo',
      store: false,
      stream: true,
      input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'hi' }] }],
    } }, expect.any(AbortSignal)));
    expect(await screen.findByText('safe result')).toBeInTheDocument();
  });

  it('shows the final SSE answer while retaining the complete stream under Raw Response', async () => {
    const raw = [
      'event: response.created',
      'data: {"type":"response.created"}',
      '',
      'event: response.output_text.done',
      'data: {"type":"response.output_text.done","text":"Final answer"}',
      '',
      'event: response.completed',
      'data: {"type":"response.completed"}',
      '',
    ].join('\n');
    pollMock.mockResolvedValue({ status: 'done', status_code: 200, body: raw });

    const { container } = render(ModelTestPanel, { props: { model: 'demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));

    expect(await screen.findByText('Final answer')).toBeInTheDocument();
    expect(container.querySelector('.test-output')?.textContent).toBe('Final answer');
    expect(container.querySelector('.detail-body pre')?.textContent).toBe(raw);
    expect(container.querySelector('.detail-body pre')?.textContent).toContain('\n\nevent: response.completed');
  });

  it('aborts polling and cancels the owned server task', async () => {
    pollMock.mockImplementation((_id: string, signal: AbortSignal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true })));
    render(ModelTestPanel, { props: { model: 'demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    await waitFor(() => expect(pollMock).toHaveBeenCalled());
    await fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(apiMock.del).toHaveBeenCalledWith('/admin/api/test/task-one'));
    expect(await screen.findByText('Test cancelled.')).toBeInTheDocument();
  });

  it('surfaces a bounded timeout and cancels the server task', async () => {
    pollMock.mockRejectedValue(new DOMException('Test timed out', 'TimeoutError'));
    render(ModelTestPanel, { props: { model: 'demo' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Test' }));
    expect(await screen.findByText('Test timed out.')).toBeInTheDocument();
    expect(apiMock.del).toHaveBeenCalledWith('/admin/api/test/task-one');
  });
});
