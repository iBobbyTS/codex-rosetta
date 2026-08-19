<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import Hint from './Hint.svelte';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';

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
  const bodyLimitOptions = $derived([... [64,128,256,512,1024].map((value) => ({ value, label: t('format.megabytes',{value}) })), { value: 'unlimited', label: t('label.unlimited') }]);

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
        const home = config.codex_home ?? t('label.configuredCodexHome');
        const catalogWarning = config.model_catalog_configured === true
          ? t('confirm.catalogReplace', { home })
          : '';
        if (!confirm(t('confirm.localModeSync', { catalog_warning: catalogWarning }))) return;
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
  <div class="section-header"><h2>{t('section.server')}</h2></div>
  <div class="provider-card" style="max-width:480px">
    {#if error}<div class="alert error" role="alert">{error}</div>{/if}
    <div class="form-group" style="margin-bottom:0">
      <label for="globalProxy">{t('label.globalProxy')}<Hint content={t('hint.docker')} /></label>
      <div style="display:flex;gap:8px"><input id="globalProxy" bind:value={proxy} placeholder={t('placeholder.proxyExample')} style="flex:1" /><button class="btn btn-primary btn-sm" disabled={busy} onclick={() => void save()}>{t('btn.save')}</button></div>
      <div style="font-size:11px;color:var(--text-dim);margin-top:6px">{t('label.globalProxy.hint')}</div>
      <div style="margin-top:14px"><label for="requestBodyLimitMb">{t('label.requestBodyLimit')}</label><Dropdown id="requestBodyLimitMb" value={bodyLimit} options={bodyLimitOptions} fitViewport={true} onChange={(value: DropdownValue) => { bodyLimit = value; }} /><div style="font-size:11px;color:var(--text-dim);margin-top:6px">{t('label.requestBodyLimitHint')}</div></div>
      <div style="margin-top:14px"><label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" bind:checked={localMode} style="width:auto" /> <span>{t('label.localMode')}</span></label><div style="font-size:11px;color:var(--text-dim);margin-top:6px">{t('label.localModeHint')}</div></div>
      <div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap"><button class="btn btn-sm" disabled={busy} onclick={() => void runDiagnostics()}>{t('diag.runDiag')}</button>{#if diagnostics}<div class="net-diag" aria-live="polite"><span class="diag-item">{JSON.stringify(diagnostics)}</span></div>{/if}</div>
    </div>
  </div>
</div>
