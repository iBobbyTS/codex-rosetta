<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { t } from '../lib/i18n.svelte';

  type Dict = Record<string, unknown>;
  type Config = { server?: Dict; model_catalog_configured?: boolean; codex_home?: string };
  let config = $state<Config>({});
  let proxy = $state('');
  let bodyLimit = $state<number | string>(128);
  let localMode = $state(true);
  let busy = $state(false);
  let error = $state('');
  let diagnostics = $state<Dict | null>(null);

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);

  async function load(signal?: AbortSignal): Promise<void> {
    try {
      config = await api.get<Config>('/admin/api/config', signal);
      const server = config.server ?? {};
      proxy = String(server.proxy ?? '');
      bodyLimit = server.request_body_limit_mb === 'unlimited' ? 'unlimited' : Number(server.request_body_limit_mb ?? 128);
      localMode = server.local_mode !== false;
      error = '';
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) error = message(cause);
    }
  }

  async function save(): Promise<void> {
    busy = true; error = '';
    try {
      const server = config.server ?? {};
      const body: Dict = { proxy: proxy.trim(), request_body_limit_mb: bodyLimit, local_mode: localMode };
      if (localMode && server.local_mode_confirmed !== true) {
        const home = config.codex_home ?? 'the configured Codex home';
        const existing = config.model_catalog_configured === true ? ` The existing model catalog configured under ${home} will be replaced.` : '';
        if (!confirm(`Enable Codex local mode and synchronize Codex configuration?${existing}`)) return;
        body.local_mode_confirmed = true;
      }
      await api.put('/admin/api/config/server', body);
      await load();
    } catch (cause) { error = message(cause); }
    finally { busy = false; }
  }

  async function runDiagnostics(): Promise<void> {
    busy = true; diagnostics = null; error = '';
    try { diagnostics = await api.get<Dict>('/admin/api/diagnostics/network'); }
    catch (cause) { error = message(cause); }
    finally { busy = false; }
  }

  onMount(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); });
</script>

<div class="section">
  <div class="section-header"><h2>{t('section.server', 'Server Settings')}</h2></div>
  <div class="provider-card" style="max-width:480px">
    {#if error}<div class="alert error" role="alert">{error}</div>{/if}
    <div class="form-group" style="margin-bottom:0">
      <label for="globalProxy">{t('label.globalProxy', 'Global Proxy URL')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker', 'In Docker, localhost refers to the container itself.')}</span></span></label>
      <div style="display:flex;gap:8px"><input id="globalProxy" bind:value={proxy} placeholder="e.g. http://127.0.0.1:7890" style="flex:1" /><button class="btn btn-primary btn-sm" disabled={busy} onclick={() => void save()}>{t('btn.save', 'Save')}</button></div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:6px">{t('label.globalProxy.hint', 'Applies to all providers unless overridden per-provider.')}</div>
      <div style="margin-top:14px"><label for="requestBodyLimitMb">{t('label.requestBodyLimit', 'Maximum Request Body')}</label><select id="requestBodyLimitMb" bind:value={bodyLimit} style="max-width:180px"><option value={64}>64 MB</option><option value={128}>128 MB</option><option value={256}>256 MB</option><option value={512}>512 MB</option><option value={1024}>1024 MB</option><option value="unlimited">{t('label.unlimited', 'Unlimited')}</option></select><div style="font-size:11px;color:var(--text-dim);margin-top:6px">{t('label.requestBodyLimitHint', 'Limits each inbound request before it is buffered.')}</div></div>
      <div style="margin-top:14px"><label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" bind:checked={localMode} style="width:auto" /> <span>{t('label.localMode', 'Local mode')}</span></label><div style="font-size:11px;color:var(--text-dim);margin-top:6px">{t('label.localModeHint', 'Automatically maintains the Codex model catalog and local gateway provider.')}</div></div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap"><button class="btn btn-sm" disabled={busy} onclick={() => void runDiagnostics()}>{t('diag.runDiag', 'Network Diagnostics')}</button>{#if diagnostics}<div class="net-diag" aria-live="polite"><span class="diag-item">{JSON.stringify(diagnostics)}</span></div>{/if}</div>
    </div>
  </div>
</div>
