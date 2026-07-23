<script lang="ts">
  import { onMount } from 'svelte';
  import Modal from '../components/Modal.svelte';
  import ServerSettingsSection from '../components/ServerSettingsSection.svelte';
  import { api } from '../lib/api';
  import { t } from '../lib/i18n.svelte';

  type Provider = { provider?: string; base_url?: string; api_type?: string; proxy?: string; enabled?: boolean; allow_redirects?: boolean; api_key?: string; validation_error?: string };
  type Shim = { name?: string; logo?: string };
  type ModelRoute = string | { provider?: string };
  type ModelGroup = { provider?: string; models?: Record<string, unknown> };
  type Config = { providers?: Record<string, Provider>; models?: Record<string, ModelRoute>; model_groups?: Record<string, ModelGroup>; known_api_types?: string[]; registered_shims?: Shim[]; credential_visible?: boolean };
  type Protocols = Record<string, string>;
  type ProviderPreset = { id: string; label: string; labelKey: string; logoShim?: string; protocols: Protocols };
  type Variant = { id: string; label: string; providerId: string };
  type Vendor = { id: string; label: string; labelKey: string; logoShim?: string; variants: Variant[] };

  const providerPresets: ProviderPreset[] = [
    { id:'deepseek', label:'DeepSeek', labelKey:'provider.deepseek', logoShim:'deepseek', protocols:{ chat:'https://api.deepseek.com', anthropic:'https://api.deepseek.com/anthropic' } },
    { id:'zhipu', label:'Zhipu (GLM)', labelKey:'provider.zhipu', logoShim:'zhipu', protocols:{ chat:'https://open.bigmodel.cn/api/paas/v4' } },
    { id:'moonshot_china', label:'Moonshot (Kimi, China)', labelKey:'provider.moonshotChina', logoShim:'moonshot', protocols:{ chat:'https://api.moonshot.cn/v1', anthropic:'https://api.moonshot.cn/anthropic' } },
    { id:'moonshot_international', label:'Moonshot (Kimi, International)', labelKey:'provider.moonshotInternational', logoShim:'moonshot', protocols:{ chat:'https://api.moonshot.ai/v1', anthropic:'https://api.moonshot.ai/anthropic' } },
    { id:'minimax_china', label:'MiniMax (China)', labelKey:'provider.minimaxChina', logoShim:'minimax--openai_chat', protocols:{ anthropic:'https://api.minimaxi.com/anthropic', chat:'https://api.minimaxi.com/v1', responses:'https://api.minimaxi.com/v1' } },
    { id:'minimax_international', label:'MiniMax (International)', labelKey:'provider.minimaxInternational', logoShim:'minimax--openai_chat', protocols:{ anthropic:'https://api.minimax.io/anthropic', chat:'https://api.minimax.io/v1', responses:'https://api.minimax.io/v1' } },
    { id:'qwen', label:'Qwen', labelKey:'provider.qwen', logoShim:'qwen', protocols:{ responses:'https://{WorkspaceId}.{RegionId}.maas.aliyuncs.com/compatible-mode/v1', chat:'https://{WorkspaceId}.{RegionId}.maas.aliyuncs.com/compatible-mode/v1', anthropic:'https://{WorkspaceId}.{RegionId}.maas.aliyuncs.com/apps/anthropic' } },
    { id:'openai', label:'OpenAI', labelKey:'provider.openai', logoShim:'openai', protocols:{ responses:'https://api.openai.com/v1', chat:'https://api.openai.com/v1' } },
    { id:'google', label:'Google', labelKey:'provider.google', logoShim:'google', protocols:{ google:'https://generativelanguage.googleapis.com' } },
    { id:'anthropic', label:'Anthropic', labelKey:'provider.anthropic', logoShim:'anthropic', protocols:{ anthropic:'https://api.anthropic.com' } },
    { id:'openrouter', label:'Open Router', labelKey:'provider.openrouter', logoShim:'openrouter--openai_chat', protocols:{ anthropic:'https://openrouter.ai/api', chat:'https://openrouter.ai/api/v1' } },
    { id:'opencode_go', label:'Opencode Go', labelKey:'provider.opencodeGo', protocols:{ chat:'https://opencode.ai/zen/go/v1' } },
    { id:'custom', label:'Custom', labelKey:'provider.custom', protocols:{ responses:'', chat:'', anthropic:'', google:'' } },
  ];
  const vendors: Vendor[] = [
    { id:'deepseek', label:'DeepSeek', labelKey:'provider.deepseek', logoShim:'deepseek', variants:[{id:'official',label:'Official',providerId:'deepseek'},{id:'custom',label:'Custom',providerId:'deepseek'}] },
    { id:'zhipu', label:'Zhipu (GLM)', labelKey:'provider.zhipu', logoShim:'zhipu', variants:[{id:'official',label:'Official',providerId:'zhipu'},{id:'custom',label:'Custom',providerId:'zhipu'}] },
    { id:'moonshot', label:'Kimi', labelKey:'provider.kimi', logoShim:'moonshot', variants:[{id:'china',label:'China',providerId:'moonshot_china'},{id:'international',label:'International',providerId:'moonshot_international'},{id:'custom',label:'Custom',providerId:'moonshot_china'}] },
    { id:'minimax', label:'MiniMax', labelKey:'provider.minimax', logoShim:'minimax--openai_chat', variants:[{id:'china',label:'China',providerId:'minimax_china'},{id:'international',label:'International',providerId:'minimax_international'},{id:'custom',label:'Custom',providerId:'minimax_china'}] },
    { id:'qwen', label:'Qwen', labelKey:'provider.qwen', logoShim:'qwen', variants:[{id:'official',label:'Official',providerId:'qwen'},{id:'custom',label:'Custom',providerId:'qwen'}] },
    { id:'openai', label:'OpenAI', labelKey:'provider.openai', logoShim:'openai', variants:[{id:'official',label:'Official',providerId:'openai'},{id:'custom',label:'Custom',providerId:'openai'}] },
    { id:'google', label:'Google', labelKey:'provider.google', logoShim:'google', variants:[{id:'official',label:'Official',providerId:'google'},{id:'custom',label:'Custom',providerId:'google'}] },
    { id:'anthropic', label:'Anthropic', labelKey:'provider.anthropic', logoShim:'anthropic', variants:[{id:'official',label:'Official',providerId:'anthropic'},{id:'custom',label:'Custom',providerId:'anthropic'}] },
    { id:'openrouter', label:'Open Router', labelKey:'provider.openrouter', logoShim:'openrouter--openai_chat', variants:[{id:'official',label:'Official',providerId:'openrouter'},{id:'custom',label:'Custom',providerId:'openrouter'}] },
    { id:'opencode_go', label:'Opencode Go', labelKey:'provider.opencodeGo', variants:[{id:'official',label:'Official',providerId:'opencode_go'},{id:'custom',label:'Custom',providerId:'opencode_go'}] },
    { id:'custom', label:'Custom', labelKey:'provider.custom', variants:[{id:'custom',label:'Custom',providerId:'custom'}] },
  ];

  let config = $state<Config>({});
  let loading = $state(true); let busy = $state(false); let error = $state(''); let notice = $state('');
  let search = $state(''); let view = $state(localStorage.getItem('provider-view') === 'list' ? 'list' : 'grid');
  let modalOpen = $state(false); let deleteOpen = $state(false); let editingName = $state('');
  let name = $state(''); let url = $state(''); let proxy = $state(''); let apiType = $state(''); let allowRedirects = $state(false);
  let vendorId = $state('custom'); let variantId = $state('custom'); let keyValues = $state(['']); let keyVisible = $state(false); let multiKey = $state(false);
  let pendingDelete = $state(''); let deleteInput = $state('');

  const providerEntries = $derived(Object.entries(config.providers ?? {}));
  const filteredEntries = $derived(providerEntries.filter(([providerName, provider]) => {
    const query = search.trim().toLowerCase(); if (!query) return true;
    const display = displayInfo(provider);
    return [providerName, provider.base_url, provider.api_type, provider.validation_error, display.vendor, display.protocol].some((value) => String(value ?? '').toLowerCase().includes(query));
  }));
  const selectedVendor = $derived(vendors.find((item) => item.id === vendorId) ?? vendors[vendors.length - 1]);
  const affectedModels = $derived(Object.entries(config.models ?? {}).filter(([, route]) => (typeof route === 'string' ? route : route.provider) === pendingDelete).map(([model]) => model));

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const normalizeUrl = (value: string) => value.trim().replace(/\/+$/, '');
  function allowedTypes(): string[] { return config.known_api_types ?? []; }
  function presetById(id: string): ProviderPreset { return providerPresets.find((item) => item.id === id) ?? providerPresets[providerPresets.length - 1]; }
  function vendorById(id: string | undefined): Vendor { return vendors.find((item) => item.id === id) ?? vendors[vendors.length - 1]; }
  function variantForUrl(vendor: Vendor, value: string): Variant {
    const normalized = normalizeUrl(value);
    return vendor.variants.find((item) => {
      if (item.id === 'custom') return false;
      const preset = providerPresets.find((entry) => entry.id === item.providerId);
      return preset ? Object.values(preset.protocols).some((presetUrl) => normalizeUrl(presetUrl) === normalized) : false;
    }) ?? vendor.variants.find((item) => item.id === 'custom') ?? vendor.variants[0];
  }
  function variant(): Variant { return selectedVendor.variants.find((item) => item.id === variantId) ?? selectedVendor.variants[0]; }
  function resolvedPresetId(): string { return variant().providerId; }
  function logoFor(vendor: Vendor): string { return config.registered_shims?.find((shim) => shim.name === vendor.logoShim)?.logo ?? ''; }
  function protocolLabel(value: string): string { return ({responses:'OpenAI Responses',chat:'OpenAI Chat Completions',anthropic:'Anthropic Messages',google:'Google GenAI'} as Record<string,string>)[value] ?? value; }
  function displayInfo(provider: Provider): { vendor: string; protocol: string; logo: string } {
    const vendor = vendorById(provider.provider);
    return { vendor: t(vendor.labelKey, vendor.label), protocol: protocolLabel(provider.api_type ?? ''), logo: logoFor(vendor) };
  }
  function setView(value: string): void { view = value === 'list' ? 'list' : 'grid'; localStorage.setItem('provider-view', view); }
  function applySelection(): void {
    const selectedVariant = variant();
    const protocols = presetById(selectedVariant.providerId).protocols;
    const supported = allowedTypes().filter((item) => Object.prototype.hasOwnProperty.call(protocols, item));
    if (!allowedTypes().includes(apiType) || !Object.prototype.hasOwnProperty.call(protocols, apiType)) apiType = supported[0] ?? allowedTypes()[0] ?? '';
    url = selectedVariant.id === 'custom' ? '' : protocols[apiType] ?? '';
  }
  function chooseVendor(value: string): void { const vendor=vendorById(value); vendorId=vendor.id; variantId=vendor.variants[0]?.id ?? 'custom'; applySelection(); }
  function chooseVariant(value: string): void { variantId = value; applySelection(); }
  function chooseProtocol(value: string): void { apiType = value; if (variant().id !== 'custom') url = presetById(resolvedPresetId()).protocols[value] ?? ''; }
  function deriveSelection(): void { variantId=variantForUrl(selectedVendor,url).id; }
  function clearForm(): void {
    editingName=''; name=''; url=''; proxy=''; apiType=allowedTypes()[0] ?? ''; allowRedirects=false; vendorId='custom'; variantId='custom'; keyValues=['']; keyVisible=false; multiKey=false; error='';
  }
  function openNew(): void { clearForm(); modalOpen=true; }
  async function openEdit(providerName: string, provider: Provider, clone = false): Promise<void> {
    editingName = clone ? '' : providerName; name = clone ? `${providerName}-copy` : providerName; url=provider.base_url ?? ''; proxy=provider.proxy ?? '';
    apiType = allowedTypes().includes(provider.api_type ?? '') ? provider.api_type ?? '' : allowedTypes()[0] ?? '';
    vendorId=vendorById(provider.provider).id; allowRedirects=provider.allow_redirects === true; keyValues=['']; keyVisible=false; multiKey=false; deriveSelection(); modalOpen=true; error='';
    if (!clone && config.credential_visible !== false) {
      try { const result = await api.get<{api_key?: string}>(`/admin/api/config/providers/${encodeURIComponent(providerName)}/key`); const keys=(result.api_key ?? '').split(','); keyValues=keys.length ? keys : ['']; multiKey=keys.length > 1; }
      catch { /* The modal remains usable for replacing or preserving the credential. */ }
    }
  }
  function promoteKeys(): void { multiKey=true; if (keyValues.length < 2) keyValues=[...keyValues,'']; }
  function setKey(index: number, value: string): void { keyValues[index]=value; keyValues=[...keyValues]; }
  function addKey(): void { keyValues=[...keyValues,'']; }
  function removeKey(index: number): void { keyValues=keyValues.filter((_, current) => current !== index); if (!keyValues.length) keyValues=['']; if (keyValues.length === 1) multiKey=false; }
  async function load(signal?: AbortSignal): Promise<void> { try { config=await api.get<Config>('/admin/api/config',signal); error=''; } catch(cause){ if (!(cause instanceof DOMException && cause.name==='AbortError')) error=message(cause); } finally { loading=false; } }
  async function save(): Promise<void> {
    if (!name.trim() || !apiType || !allowedTypes().includes(apiType) || !/^https?:\/\//i.test(url.trim())) { error=t('error.fieldsRequired','Provider name, supported protocol, and HTTP(S) Base URL are required.'); return; }
    const credential=keyValues.map((item)=>item.trim()).filter(Boolean).join(','); if (!editingName && !credential) { error='A provider credential is required when creating a provider.'; return; }
    busy=true; error=''; try { const body: Record<string,unknown>={provider:vendorId,api_type:apiType,base_url:url.trim(),proxy:proxy.trim(),allow_redirects:allowRedirects}; if(credential)body.api_key=credential; if(editingName&&editingName!==name.trim())body.rename_from=editingName; await api.put(`/admin/api/config/providers/${encodeURIComponent(name.trim())}`,body); modalOpen=false; notice=t('toast.providerSaved',`Provider ${name.trim()} saved.`); await load(); } catch(cause){error=message(cause);} finally{busy=false;}
  }
  async function action(operation:()=>Promise<unknown>,success:string):Promise<void>{busy=true;error='';try{await operation();await load();notice=success;}catch(cause){error=message(cause);}finally{busy=false;}}
  async function toggle(providerName:string):Promise<void>{await action(()=>api.post(`/admin/api/config/providers/${encodeURIComponent(providerName)}/toggle`),t('toast.providerToggled','Provider status changed.'));}
  function requestDelete(providerName:string):void{pendingDelete=providerName;deleteInput='';deleteOpen=true;}
  async function confirmDelete():Promise<void>{if(deleteInput!==pendingDelete)return;const providerName=pendingDelete;await action(()=>api.del(`/admin/api/config/providers/${encodeURIComponent(providerName)}?cascade=true`),t('toast.providerDeleted','Provider deleted.'));deleteOpen=false;pendingDelete='';}
  onMount(()=>{const controller=new AbortController();void load(controller.signal);return()=>controller.abort();});
</script>

<ServerSettingsSection />
<div class="section">
  <div class="section-header"><h2>{t('section.providers','Providers')}</h2></div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}{#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  <div class="provider-toolbar">
    {#if providerEntries.length > 6}<input placeholder={t('label.searchProviders','Search providers...')} bind:value={search} />{/if}
    <span class="provider-count">{providerEntries.length > 6 ? (search ? `${filteredEntries.length} / ${providerEntries.length}` : `${providerEntries.length}`) : ''}</span>
    <div class="view-toggle">
      <button class="btn btn-sm" class:active={view==='grid'} onclick={()=>setView('grid')} title={t('label.gridView','Grid view')} aria-label={t('label.gridView','Grid view')}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg></button>
      <button class="btn btn-sm" class:active={view==='list'} onclick={()=>setView('list')} title={t('label.listView','List view')} aria-label={t('label.listView','List view')}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
    </div>
    <button class="btn btn-primary btn-sm" onclick={openNew}>{t('btn.addProvider','+ Add Provider')}</button>
  </div>
  {#if loading}<p style="color:var(--text-dim)">Loading providers...</p>{:else}
    <div class="provider-grid" class:list-view={view==='list'}>
      {#each filteredEntries as [providerName, provider]}
        {@const enabled=provider.enabled!==false}{@const info=displayInfo(provider)}
        <div class="provider-card" class:disabled={!enabled} class:config-error={!!provider.validation_error}>
          <div class="card-header"><div class="name">{#if info.logo}<img class="provider-logo" src={info.logo} alt="" />{/if}{providerName}{#if provider.validation_error}<span class="badge badge-error" title={provider.validation_error}>{t('provider.configError','Config Error')}</span>{/if}</div><label class="toggle" title={enabled?t('provider.enabled','Enabled'):t('provider.disabled','Disabled')}><input type="checkbox" checked={enabled} onchange={()=>void toggle(providerName)} /><span class="slider"></span></label></div>
          {#if view==='list'}
            <div class="field" title={`${info.vendor} · ${info.protocol}`}><code>{info.vendor} · {info.protocol}</code></div><div class="field" title={provider.base_url ?? ''}><code>{provider.base_url ?? ''}</code></div><div class="field"><code>{config.credential_visible===false?'':provider.api_key ?? ''}</code></div>
          {:else}
            <div class="field">{t('label.providerVendor','Provider')}: <code>{info.vendor}</code></div><div class="field">{t('label.providerProtocol','Protocol')}: <code>{info.protocol}</code></div><div class="field">Base URL: <code>{provider.base_url ?? ''}</code></div>{#if config.credential_visible!==false}<div class="field">API Key: <code>{provider.api_key ?? ''}</code></div>{/if}{#if provider.proxy}<div class="field">Proxy: <code>{provider.proxy}</code></div>{/if}
          {/if}
          <div class="actions"><button class="btn btn-sm" onclick={()=>void openEdit(providerName,provider,true)}>{t('btn.clone','Clone')}</button><button class="btn btn-sm" onclick={()=>void openEdit(providerName,provider)}>{t('btn.edit','Edit')}</button><button class="btn btn-sm btn-danger" onclick={()=>requestDelete(providerName)}>{t('btn.delete','Delete')}</button></div>
        </div>
      {:else}<p style="color:var(--text-dim)">{providerEntries.length?t('empty.searchResults','No matching providers.'):t('empty.providers','No providers configured.')}</p>{/each}
    </div>
  {/if}
</div>

<Modal open={modalOpen} labelledby="provider-modal-title" onclose={()=>modalOpen=false}>
  <h3 id="provider-modal-title">{editingName?t('modal.editProvider','Edit Provider'):t('modal.addProvider','Add Provider')}</h3>
  <div class="form-group"><label for="provName">{t('label.providerName','Provider Name')}</label><input id="provName" bind:value={name} placeholder="e.g. my-openai, openrouter-claude" /></div>
  <div class="form-group"><label for="provProvider">{t('label.providerVendor','Provider')}</label><div class="provider-preset-row"><div class="type-logo-wrapper">{#if logoFor(selectedVendor)}<img class="type-logo-preview" src={logoFor(selectedVendor)} alt="" />{/if}<select id="provProvider" value={vendorId} onchange={(event)=>chooseVendor(event.currentTarget.value)}>{#each vendors as vendor}<option value={vendor.id}>{t(vendor.labelKey,vendor.label)}</option>{/each}</select></div><select aria-label="Provider variant" value={variantId} onchange={(event)=>chooseVariant(event.currentTarget.value)}>{#each selectedVendor.variants as item}<option value={item.id}>{item.label}</option>{/each}</select></div></div>
  <div class="form-group"><label for="provApiType">{t('label.providerProtocol','Protocol')}</label><select id="provApiType" value={apiType} onchange={(event)=>chooseProtocol(event.currentTarget.value)}>{#each allowedTypes() as item}<option value={item}>{protocolLabel(item)}</option>{/each}</select></div>
  <div class="form-group"><label for="provBaseUrl">{t('label.baseUrl','Base URL')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker','In Docker, localhost refers to the container itself.')}</span></span></label><input id="provBaseUrl" bind:value={url} oninput={deriveSelection} placeholder="https://api.openai.com/v1" /></div>
  <div class="form-group"><label for="provApiKey">{t('label.apiKey','API Key (or ${ENV_VAR} placeholder)')}</label>{#if multiKey}<div>{#each keyValues as key,index}<div class="multi-key-row"><input aria-label={`API key ${index+1}`} type={keyVisible?'text':'password'} value={key} oninput={(event)=>setKey(index,event.currentTarget.value)} /><button type="button" class="key-btn" onclick={()=>removeKey(index)} aria-label="Remove key">×</button></div>{/each}</div><div class="multi-key-footer"><button type="button" class="btn btn-sm" onclick={addKey}>+ {t('label.addKey','Add key')}</button><button type="button" class="key-btn" onclick={()=>keyVisible=!keyVisible} aria-label="Toggle visibility">◉</button></div>{:else}<div style="display:flex;gap:4px;align-items:center"><input id="provApiKey" type={keyVisible?'text':'password'} value={keyValues[0]} oninput={(event)=>setKey(0,event.currentTarget.value)} autocomplete="new-password" placeholder={editingName?t('label.keyUnchangedHint','Leave blank to keep current key'):'${OPENAI_API_KEY}'} style="flex:1" /></div><div class="multi-key-footer"><button type="button" class="btn btn-sm" onclick={promoteKeys}>+ {t('label.addKey','Add key')}</button><button type="button" class="key-btn" onclick={()=>keyVisible=!keyVisible} aria-label="Toggle visibility">◉</button></div>{/if}</div>
  <div class="form-group"><label for="provProxy">{t('label.proxyUrl','Proxy URL (optional, overrides global)')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker','In Docker, localhost refers to the container itself.')}</span></span></label><input id="provProxy" bind:value={proxy} placeholder="e.g. http://127.0.0.1:7890" /></div>
  <div class="form-group checkbox-group"><label><input type="checkbox" bind:checked={allowRedirects} /><span>{t('label.allowRedirects','Allow redirects')}</span></label></div>
  <div class="modal-actions"><button class="btn" onclick={()=>modalOpen=false}>{t('btn.cancel','Cancel')}</button><button class="btn btn-primary" disabled={busy} onclick={()=>void save()}>{t('btn.save','Save')}</button></div>
</Modal>

<Modal open={deleteOpen} labelledby="delete-provider-title" onclose={()=>deleteOpen=false}>
  <h3 id="delete-provider-title">{t('confirm.deleteProviderTitle','Delete Provider')}</h3><p style="margin:8px 0 12px;color:var(--text-dim);font-size:13px">Type <strong>{pendingDelete}</strong> to confirm.</p>
  {#if affectedModels.length}<div style="margin-bottom:12px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);font-size:12px;max-height:120px;overflow-y:auto"><div style="color:#cf222e;font-weight:600;margin-bottom:4px">{affectedModels.length} affected models will also be removed.</div>{#each affectedModels as model}<div style="color:var(--text-dim)">• {model}</div>{/each}</div>{/if}
  <div class="form-group"><input aria-label="Confirm provider name" bind:value={deleteInput} autocomplete="off" spellcheck="false" style="font-family:monospace" /></div><div class="modal-actions"><button class="btn" onclick={()=>deleteOpen=false}>{t('btn.cancel','Cancel')}</button><button class="btn btn-danger" disabled={deleteInput!==pendingDelete||busy} onclick={()=>void confirmDelete()}>{t('btn.delete','Delete')}</button></div>
</Modal>
