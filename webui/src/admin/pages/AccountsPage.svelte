<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { isSupportedOAuthHost } from '../lib/oauth-host';
  import { ConfirmDialog, Dialog } from '@ibobbyts/svelte-ui-utils/dialog';
  import { t } from '../../shared/i18n.svelte';

  type Account = {
    id: string;
    provider: string;
    name?: string;
    email?: string;
    workspace?: string;
    subscription_type?: string;
  };

  let accounts = $state<Account[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let sub2apiOpen = $state(false);
  let sub2apiUrl = $state('');
  let sub2apiAuth = $state('');
  let sub2apiBusy = $state(false);
  let deleteAccount = $state<Account | null>(null);

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);

  async function load(signal?: AbortSignal): Promise<void> {
    try {
      const result = await api.get<{ accounts?: Account[] }>('/admin/api/accounts', signal);
      accounts = result.accounts ?? [];
      error = '';
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) error = message(cause);
    } finally {
      loading = false;
    }
  }

  async function loginChatGPT(): Promise<void> {
    if (!isSupportedOAuthHost(window.location.hostname)) {
      error = t('accounts.localhostRequired');
      notice = '';
      return;
    }
    busy = true;
    error = '';
    notice = '';
    const popup = typeof window.open === 'function' ? window.open('about:blank', 'codex-chatgpt-login') : null;
    let poll = 0;
    let settled = false;
    let attemptId = '';

    const cleanup = () => {
      if (poll) window.clearInterval(poll);
      window.removeEventListener('message', onMessage);
    };
    const finish = async (outcome: 'saved' | 'failed' | 'cancelled' | 'timeout', detail = ''): Promise<void> => {
      if (settled) return;
      settled = true;
      cleanup();
      busy = false;
      if (outcome === 'saved') {
        // The callback signal is authoritative even when the stable account ID
        // already existed: the backend performed a successful upsert.
        await load();
        notice = t('accounts.oauthSaved');
      } else if (outcome === 'failed') {
        error = detail || 'ChatGPT login failed. Please try again.';
      } else if (outcome === 'timeout') {
        error = 'ChatGPT login timed out. Please try again.';
      } else {
        notice = t('accounts.oauthCancelled');
      }
    };
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.source !== popup) return;
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      const signal = 'signal' in data && typeof data.signal === 'string' ? data.signal : '';
      if (!attemptId || signal !== attemptId) return;
      if (!('source' in data) || data.source !== 'codex-rosetta-chatgpt-oauth') return;
      const outcome = 'outcome' in data && data.outcome === 'saved' ? 'saved' : 'failed';
      const detail = 'message' in data && typeof data.message === 'string' ? data.message : '';
      void finish(outcome, detail);
    };
    try {
      const result = await api.post<{ authorization_url: string; attempt_id: string }>('/admin/api/accounts/chatgpt/start');
      if (!result.authorization_url) throw new Error(t('accounts.oauthMissingUrl'));
      if (!result.attempt_id) throw new Error('ChatGPT login did not return a completion signal.');
      attemptId = result.attempt_id;
      window.addEventListener('message', onMessage);
      if (popup) popup.location.href = result.authorization_url;
      else window.location.href = result.authorization_url;
      notice = t('accounts.oauthStarted');
      const startedAt = Date.now();
      poll = window.setInterval(() => {
        if (Date.now() - startedAt >= 5 * 60 * 1000) {
          popup?.close();
          void finish('timeout');
        } else if (popup && popup.closed) {
          // A direct close has no matching callback signal.  Do not infer
          // success from a pre-existing row or a refresh race.
          void finish('cancelled');
        } else {
          void load();
        }
      }, 2000);
    } catch (cause) {
      cleanup();
      popup?.close();
      busy = false;
      error = message(cause);
    }
  }

  const sub2apiScript = "(function(){var d={access_token:localStorage.getItem('auth_token'),refresh_token:localStorage.getItem('refresh_token'),expires_at:localStorage.getItem('token_expires_at')};copy(JSON.stringify(d));alert('认证信息已复制，请粘贴到账号管理页面。')})()";

  async function copySub2APIScript(): Promise<void> {
    try {
      await navigator.clipboard.writeText(sub2apiScript);
      notice = t('accounts.sub2apiScriptCopied');
    } catch {
      error = t('accounts.sub2apiCopyFailed');
    }
  }

  async function addSub2API(): Promise<void> {
    sub2apiBusy = true;
    error = '';
    try {
      let auth: unknown;
      try { auth = JSON.parse(sub2apiAuth); } catch { throw new Error(t('accounts.sub2apiInvalidJson')); }
      await api.post('/admin/api/accounts/sub2api', { base_url: sub2apiUrl, auth });
      sub2apiOpen = false;
      sub2apiUrl = '';
      sub2apiAuth = '';
      notice = t('accounts.sub2apiSaved');
      await load();
    } catch (cause) { error = message(cause); }
    finally { sub2apiBusy = false; }
  }

  async function confirmDelete(): Promise<void> {
    if (!deleteAccount) return;
    const target = deleteAccount;
    try {
      await api.del(`/admin/api/accounts/${encodeURIComponent(target.id)}`);
      deleteAccount = null;
      notice = t('accounts.deleted');
      await load();
    } catch (cause) { error = message(cause); }
  }

  onMount(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  });
</script>

<div class="section">
  <div class="section-header"><h2>{t('section.accounts')}</h2></div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
    <button class="btn btn-primary" disabled={busy} onclick={() => void loginChatGPT()}>{t('accounts.loginChatGPT')}</button>
    <button class="btn" disabled={busy || sub2apiBusy} onclick={() => { sub2apiOpen = true; error = ''; }}>{t('accounts.loginSub2API')}</button>
  </div>
  {#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}
  {#if loading}
    <p style="color:var(--text-dim)">{t('loading.accounts')}</p>
  {:else}
    <h3>{t('accounts.chatgptSection')}</h3>
    <div class="table-scroll"><table>
      <thead><tr><th>{t('accounts.name')}</th><th>{t('accounts.email')}</th><th>{t('accounts.workspace')}</th><th>{t('accounts.subscription')}</th><th>{t('accounts.actions')}</th></tr></thead>
      <tbody>
        {#each accounts.filter((account) => account.provider === 'chatgpt') as account}
          <tr><td>{account.name ?? ''}</td><td>{account.email ?? ''}</td><td>{account.workspace ?? ''}</td><td>{account.subscription_type ?? ''}</td><td><button class="btn btn-sm" onclick={() => deleteAccount = account}>{t('btn.delete')}</button></td></tr>
        {:else}<tr><td colspan="5" class="empty">{t('empty.accounts')}</td></tr>{/each}
      </tbody>
    </table></div>
    <h3>{t('accounts.sub2apiSection')}</h3>
    <div class="table-scroll"><table>
      <thead><tr><th>{t('accounts.email')}</th><th>{t('accounts.actions')}</th></tr></thead>
      <tbody>
        {#each accounts.filter((account) => account.provider === 'sub2api') as account}
          <tr><td>{account.email ?? ''}</td><td><button class="btn btn-sm" onclick={() => deleteAccount = account}>{t('btn.delete')}</button></td></tr>
        {:else}<tr><td colspan="2" class="empty">{t('empty.accounts')}</td></tr>{/each}
      </tbody>
    </table></div>
  {/if}
</div>

<Dialog open={sub2apiOpen} title={t('accounts.sub2apiTitle')} size="lg" closeLabel={t('btn.cancel')} onClose={() => { if (!sub2apiBusy) sub2apiOpen = false; }}>
  <div class="account-dialog-content">
    <p>{t('accounts.sub2apiGuide')}</p>
    <button class="btn btn-sm" type="button" onclick={() => void copySub2APIScript()}>{t('accounts.sub2apiCopyScript')}</button>
    <label><span>{t('accounts.sub2apiUrl')}</span><input bind:value={sub2apiUrl} placeholder="ai-pixel.online" /></label>
    <label><span>{t('accounts.sub2apiAuth')}</span><textarea bind:value={sub2apiAuth} rows="6" placeholder="Paste authentication JSON here"></textarea></label>
  </div>
  <svelte:fragment slot="footer">
    <button class="suu-dialog__button" type="button" disabled={sub2apiBusy} onclick={() => sub2apiOpen = false}>{t('btn.cancel')}</button>
    <button class="suu-dialog__button suu-dialog__button--primary" type="button" disabled={sub2apiBusy || !sub2apiUrl.trim() || !sub2apiAuth.trim()} onclick={() => void addSub2API()}>{t('btn.save')}</button>
  </svelte:fragment>
</Dialog>

<ConfirmDialog open={deleteAccount !== null} title={t('accounts.deleteTitle')} message={t('accounts.deleteMessage')} confirmLabel={t('btn.delete')} cancelLabel={t('btn.cancel')} closeLabel={t('btn.cancel')} intent="danger" onClose={() => deleteAccount = null} onConfirm={() => void confirmDelete()} />
