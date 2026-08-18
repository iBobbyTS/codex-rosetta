// @vitest-environment-options { "customExportConditions": ["browser"] }
import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AccountsPage from '../src/admin/pages/AccountsPage.svelte';
import { isSupportedOAuthHost } from '../src/admin/lib/oauth-host';

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));
vi.mock('../src/admin/lib/api', () => ({ api: apiMock }));
vi.mock('../src/shared/i18n.svelte', () => ({
  t: (key: string) => ({
    'accounts.loginChatGPT': 'Log in with ChatGPT',
    'accounts.oauthCancelled': 'ChatGPT login was cancelled; no account was changed.',
    'accounts.oauthSaved': 'ChatGPT account saved successfully.',
    'accounts.localhostRequired': 'ChatGPT login is only supported at localhost. Please open the Admin page using localhost.',
    'accounts.oauthMissingUrl': 'ChatGPT login did not return an authorization URL.',
    'accounts.oauthStarted': 'Complete ChatGPT login in the opened window, then return here.',
    'accounts.loginSub2API': 'Log in with Sub2API',
    'accounts.sub2apiTitle': 'Add Sub2API account',
    'accounts.sub2apiGuideTitle': 'How to add the account',
    'accounts.sub2apiGuideOpen': 'Open the logged-in Sub2API site.',
    'accounts.sub2apiGuideConsole': 'Open the browser Console and run the script.',
    'accounts.sub2apiGuidePaste': 'Paste the generated JSON below, then save.',
    'accounts.sub2apiCopyScript': 'Copy browser script',
    'accounts.sub2apiUrl': 'Base URL',
    'accounts.sub2apiAuth': 'Authentication JSON',
    'btn.cancel': 'Cancel',
    'btn.save': 'Save',
    'section.accounts': 'Accounts',
    'loading.accounts': 'Loading accounts...',
    'accounts.name': 'Name',
    'accounts.email': 'Email',
    'accounts.workspace': 'Workspace',
    'accounts.subscription': 'Subscription',
    'empty.accounts': 'No accounts.',
    'accounts.sub2apiDeferred': 'Sub2API account flow is coming soon',
  }[key] ?? key),
}));

type LoginPopup = {
  closed: boolean;
  location: { href: string };
  close: ReturnType<typeof vi.fn>;
};

let popup: LoginPopup;

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  popup = { closed: false, location: { href: '' }, close: vi.fn() };
  vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
  apiMock.get.mockResolvedValue({ accounts: [] });
  apiMock.post.mockResolvedValue({ authorization_url: 'https://auth.example.test/start', attempt_id: 'attempt-1' });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function startLogin(): Promise<HTMLElement> {
  render(AccountsPage);
  await vi.runAllTicks();
  const button = screen.getByRole('button', { name: 'Log in with ChatGPT' });
  await fireEvent.click(button);
  await vi.runAllTicks();
  return button;
}

describe('AccountsPage ChatGPT OAuth polling', () => {
  it('supports only localhost for ChatGPT OAuth', () => {
    expect(isSupportedOAuthHost('localhost')).toBe(true);
    expect(isSupportedOAuthHost('LOCALHOST')).toBe(true);
    expect(isSupportedOAuthHost('127.0.0.1')).toBe(false);
    expect(isSupportedOAuthHost('192.168.1.10')).toBe(false);
  });

  function sendCallback(data: Record<string, unknown>, source = popup): void {
    window.dispatchEvent(new MessageEvent('message', {
      data,
      origin: 'http://localhost:1455',
      source: source as unknown as Window,
    }));
  }

  it('reports a matching callback signal as saved, including a duplicate upsert', async () => {
    const button = await startLogin();

    // The account already existed before this attempt; success is established
    // by the one-time callback signal, not by observing a new row.
    apiMock.get.mockResolvedValue({
      accounts: [{ id: 'chatgpt-1', provider: 'chatgpt', name: 'Ada Updated', email: 'ada@example.test' }],
    });
    popup.closed = true;
    sendCallback({ source: 'codex-rosetta-chatgpt-oauth', signal: 'attempt-1', outcome: 'saved', message: '账号已保存。' });
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.runAllTicks();

    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('ChatGPT account saved successfully.'));
    expect(await screen.findByText('ada@example.test')).toBeInTheDocument();
    expect(button).toBeEnabled();
  });

  it('ignores an unfamiliar callback signal and only then reports direct close cancellation', async () => {
    const button = await startLogin();

    sendCallback({ source: 'codex-rosetta-chatgpt-oauth', signal: 'other-attempt', outcome: 'saved' });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(screen.getByRole('status')).not.toHaveTextContent('ChatGPT account saved successfully.');

    popup.closed = true;
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('ChatGPT login was cancelled; no account was changed.'));
    expect(button).toBeEnabled();
  });

  it('shows a matching callback failure and recovers the login button', async () => {
    const button = await startLogin();

    sendCallback({ source: 'codex-rosetta-chatgpt-oauth', signal: 'attempt-1', outcome: 'failed', message: 'OAuth 登录已超时，请返回管理页面重试。' });
    await vi.runAllTicks();

    await vi.waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('OAuth 登录已超时，请返回管理页面重试。'));
    expect(button).toBeEnabled();
  });

  it('reports popup cancellation and keeps login available', async () => {
    const button = await startLogin();

    await vi.advanceTimersByTimeAsync(2_000);
    expect(apiMock.get.mock.calls.length).toBeGreaterThanOrEqual(2);

    popup.closed = true;
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.runAllTicks();

    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('ChatGPT login was cancelled; no account was changed.'));
    expect(button).toBeEnabled();
    expect(popup.close).not.toHaveBeenCalled();
  });

  it('does not report success when an existing account remains after popup cancellation', async () => {
    apiMock.get.mockResolvedValue({
      accounts: [{ id: 'existing-chatgpt', provider: 'chatgpt', name: 'Existing', email: 'existing@example.test' }],
    });
    render(AccountsPage);
    await vi.waitFor(() => expect(screen.getByText('existing@example.test')).toBeInTheDocument());
    const button = screen.getByRole('button', { name: 'Log in with ChatGPT' });
    await fireEvent.click(button);
    await vi.runAllTicks();

    popup.closed = true;
    await vi.advanceTimersByTimeAsync(2_000);
    await vi.runAllTicks();

    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('ChatGPT login was cancelled; no account was changed.'));
    expect(screen.getByRole('status')).not.toHaveTextContent('ChatGPT account saved successfully.');
    expect(button).toBeEnabled();
  });

  it('reports the five-minute timeout, closes the popup, and stops polling', async () => {
    const button = await startLogin();

    await vi.advanceTimersByTimeAsync(5 * 60 * 1_000);

    await Promise.resolve();
    expect(screen.getByRole('alert')).toHaveTextContent('ChatGPT login timed out. Please try again.');
    expect(popup.close).toHaveBeenCalledTimes(1);
    expect(button).toBeEnabled();
    const callsAtTimeout = apiMock.get.mock.calls.length;

    await vi.advanceTimersByTimeAsync(4_000);
    expect(apiMock.get).toHaveBeenCalledTimes(callsAtTimeout);
  });
});

describe('AccountsPage Sub2API dialog', () => {
  it('presents the instructions and account fields as a guided form', async () => {
    render(AccountsPage);
    await vi.runAllTicks();

    await fireEvent.click(screen.getByRole('button', { name: 'Log in with Sub2API' }));

    const dialog = screen.getByRole('dialog', { name: 'Add Sub2API account' });
    expect(dialog).toHaveTextContent('How to add the account');
    expect(screen.getByRole('button', { name: 'Copy browser script' })).toBeInTheDocument();
    expect(screen.getByLabelText('Base URL')).toHaveAttribute('placeholder', 'ai-pixel.online');
    expect(screen.getByLabelText('Authentication JSON').tagName).toBe('TEXTAREA');
  });
});
