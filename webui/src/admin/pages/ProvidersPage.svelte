<script lang="ts">
  import { onMount } from 'svelte';
  import Modal from '../components/Modal.svelte';
  import ServerSettingsSection from '../components/ServerSettingsSection.svelte';
  import { api } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import { providerLogo, providerLogoNeedsDarkInversion } from '../lib/provider-logos';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';

  type Provider = { provider?: string; base_url?: string; api_type?: string; proxy?: string; enabled?: boolean; allow_redirects?: boolean; soft_interrupt?: boolean; force_rosetta_compaction?: boolean; api_key?: string; validation_error?: string };
  type ModelRoute = string | { provider?: string };
  type ModelGroup = { provider?: string; models?: Record<string, unknown> };
  type Variant = { endpoints: Record<string,string> };
  type Vendor = { id:string; label_key:string; logo_shim?:string; soft_interrupt_default?:boolean; recommended_api_type:string; adapted_api_types:Record<string,string>; known_supported_api_types:string[]; variants:Record<string,Variant> };
  type ProviderCatalog = { api_types:string[]; providers:Record<string,Omit<Vendor,'id'>> };
  type Config = { providers?: Record<string, Provider>; models?: Record<string, ModelRoute>; model_groups?: Record<string, ModelGroup>; known_api_types?: string[]; provider_catalog?:ProviderCatalog; credential_visible?: boolean };

  let config = $state<Config>({});
  let loading = $state(true); let busy = $state(false); let error = $state(''); let notice = $state('');
  let search = $state(''); let view = $state(localStorage.getItem('provider-view') === 'list' ? 'list' : 'grid');
  let modalOpen = $state(false); let deleteOpen = $state(false); let editingName = $state('');
  let name = $state(''); let url = $state(''); let proxy = $state(''); let apiType = $state(''); let allowRedirects = $state(false); let softInterrupt = $state(false); let forceRosettaCompaction = $state(false);
  let vendorId = $state('custom'); let variantId = $state('custom'); let apiKey = $state(''); let keyVisible = $state(false);
  let pendingDelete = $state(''); let deleteInput = $state('');

  const providerEntries = $derived(Object.entries(config.providers ?? {}));
  const filteredEntries = $derived(providerEntries.filter(([providerName, provider]) => {
    const query = search.trim().toLowerCase(); if (!query) return true;
    const display = displayInfo(provider);
    return [providerName, provider.base_url, provider.api_type, provider.validation_error, display.vendor, display.protocol].some((value) => String(value ?? '').toLowerCase().includes(query));
  }));
  const selectedVendor = $derived(vendorById(vendorId));
  const affectedModels = $derived(Object.entries(config.models ?? {}).filter(([, route]) => (typeof route === 'string' ? route : route.provider) === pendingDelete).map(([model]) => model));

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const normalizeUrl = (value: string) => value.trim().replace(/\/+$/, '');
  function allowedTypes(): string[] { return config.provider_catalog?.api_types ?? config.known_api_types ?? []; }
  function vendors(): Vendor[] { return Object.entries(config.provider_catalog?.providers??{}).map(([id,value])=>({id,...value})); }
  function vendorById(id: string | undefined): Vendor { const values=vendors();return values.find((item) => item.id === id) ?? values.find((item)=>item.id==='custom') ?? {id:'custom',label_key:'provider.custom',recommended_api_type:'chat',adapted_api_types:{},known_supported_api_types:[],variants:{custom:{endpoints:{}}}}; }
  function variantForUrl(vendor: Vendor, value: string): Variant {
    const normalized = normalizeUrl(value);
    const match=Object.entries(vendor.variants).find(([id,item]) => id!=='custom'&&Object.values(item.endpoints).some((presetUrl) => normalizeUrl(presetUrl) === normalized));
    return match?.[1] ?? vendor.variants.custom ?? Object.values(vendor.variants)[0] ?? {endpoints:{}};
  }
  function variant(): Variant { return selectedVendor.variants[variantId] ?? Object.values(selectedVendor.variants)[0] ?? {endpoints:{}}; }
  function logoFor(vendor: Vendor): string { return providerLogo(vendor.logo_shim); }
  function protocolLabel(value: string): string { return ['responses','chat','anthropic','google'].includes(value) ? t(`protocol.${value}`) : value; }
  function displayInfo(provider: Provider): { vendor: string; protocol: string; logo: string; invertLogo: boolean } {
    const vendor = vendorById(provider.provider);
    return { vendor: t(vendor.label_key), protocol: protocolLabel(provider.api_type ?? ''), logo: logoFor(vendor), invertLogo: providerLogoNeedsDarkInversion(vendor.logo_shim) };
  }
  function setView(value: string): void { view = value === 'list' ? 'list' : 'grid'; localStorage.setItem('provider-view', view); }
  function applySelection(): void {
    const protocols = variant().endpoints;
    if (!allowedTypes().includes(apiType)) apiType = selectedVendor.recommended_api_type;
    url = variantId === 'custom' ? '' : protocols[apiType] ?? '';
  }
  function chooseVendor(value: string): void { const vendor=vendorById(value); vendorId=vendor.id; variantId=Object.keys(vendor.variants)[0]??'custom';apiType=vendor.recommended_api_type;softInterrupt=vendor.soft_interrupt_default===true;forceRosettaCompaction=false;applySelection(); }
  function chooseVariant(value: string): void { variantId = value; applySelection(); }
  function chooseProtocol(value: string): void { apiType = value; url = variantId==='custom'?'':variant().endpoints[value] ?? ''; }
  function deriveSelection(): void { const found=Object.entries(selectedVendor.variants).find(([,item])=>item===variantForUrl(selectedVendor,url));variantId=found?.[0]??'custom'; }
  function protocolGroups():{label:string;items:string[]}[]{const adapted=Object.keys(selectedVendor.adapted_api_types);const known=selectedVendor.known_supported_api_types.filter((item)=>!adapted.includes(item));const other=allowedTypes().filter((item)=>!adapted.includes(item)&&!known.includes(item));return[{label:'',items:adapted},{label:t('provider.rosettaUnadapted'),items:known},{label:t('provider.maybeUnsupported',{provider:t(selectedVendor.label_key)}),items:other}].filter((group)=>group.items.length);}
  function clearForm(): void {
    editingName=''; name=''; url=''; proxy=''; apiType=allowedTypes()[0] ?? ''; allowRedirects=false; softInterrupt=false; forceRosettaCompaction=false; vendorId='custom'; variantId='custom'; apiKey=''; keyVisible=false; error='';
  }
  function openNew(): void { clearForm(); modalOpen=true; }
  async function openEdit(providerName: string, provider: Provider, clone = false): Promise<void> {
    editingName = clone ? '' : providerName; name = clone ? `${providerName}-copy` : providerName; url=provider.base_url ?? ''; proxy=provider.proxy ?? '';
    apiType = allowedTypes().includes(provider.api_type ?? '') ? provider.api_type ?? '' : allowedTypes()[0] ?? '';
    vendorId=vendorById(provider.provider).id; allowRedirects=provider.allow_redirects === true; softInterrupt=provider.soft_interrupt === true; forceRosettaCompaction=provider.force_rosetta_compaction === true; apiKey=''; keyVisible=false; deriveSelection(); modalOpen=true; error='';
    if (!clone && config.credential_visible !== false) {
      try { const result = await api.get<{api_key?: string}>(`/admin/api/config/providers/${encodeURIComponent(providerName)}/key`); apiKey=result.api_key ?? ''; }
      catch { /* The modal remains usable for replacing or preserving the credential. */ }
    }
  }
  async function load(signal?: AbortSignal): Promise<void> { try { config=await api.get<Config>('/admin/api/config',signal); error=''; } catch(cause){ if (!(cause instanceof DOMException && cause.name==='AbortError')) error=message(cause); } finally { loading=false; } }
  async function save(): Promise<void> {
    if (!name.trim() || !apiType || !allowedTypes().includes(apiType) || !/^https?:\/\//i.test(url.trim())) { error=t('error.providerFieldsRequired'); return; }
    const credential=apiKey.trim(); if (!editingName && !credential) { error=t('error.providerCredentialRequired'); return; }
    busy=true; error=''; try { const body: Record<string,unknown>={provider:vendorId,api_type:apiType,base_url:url.trim(),proxy:proxy.trim(),allow_redirects:allowRedirects}; if(apiType==='chat')body.soft_interrupt=softInterrupt; if(apiType==='responses')body.force_rosetta_compaction=forceRosettaCompaction; if(credential)body.api_key=credential; if(editingName&&editingName!==name.trim())body.rename_from=editingName; await api.put(`/admin/api/config/providers/${encodeURIComponent(name.trim())}`,body); modalOpen=false; notice=t('toast.providerSaved',{name:name.trim()}); await load(); } catch(cause){error=message(cause);} finally{busy=false;}
  }
  async function action(operation:()=>Promise<unknown>,success:string):Promise<void>{busy=true;error='';try{await operation();await load();notice=success;}catch(cause){error=message(cause);}finally{busy=false;}}
  async function toggle(providerName:string):Promise<void>{await action(()=>api.post(`/admin/api/config/providers/${encodeURIComponent(providerName)}/toggle`),t('toast.providerToggled'));}
  function requestDelete(providerName:string):void{pendingDelete=providerName;deleteInput='';deleteOpen=true;}
  async function confirmDelete():Promise<void>{if(deleteInput!==pendingDelete)return;const providerName=pendingDelete;await action(()=>api.del(`/admin/api/config/providers/${encodeURIComponent(providerName)}?cascade=true`),t('toast.providerDeleted',{name:providerName}));deleteOpen=false;pendingDelete='';}
  onMount(()=>{const controller=new AbortController();void load(controller.signal);return()=>controller.abort();});
</script>

<ServerSettingsSection />
<div class="section">
  <div class="section-header"><h2>{t('section.providers')}</h2></div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}{#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  <div class="provider-toolbar">
    {#if providerEntries.length > 6}<input placeholder={t('label.searchProviders')} bind:value={search} />{/if}
    <span class="provider-count">{providerEntries.length > 6 ? (search ? `${filteredEntries.length} / ${providerEntries.length}` : `${providerEntries.length}`) : ''}</span>
    <div class="view-toggle">
      <button class="btn btn-sm" class:active={view==='grid'} onclick={()=>setView('grid')} title={t('label.gridView')} aria-label={t('label.gridView')}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg></button>
      <button class="btn btn-sm" class:active={view==='list'} onclick={()=>setView('list')} title={t('label.listView')} aria-label={t('label.listView')}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg></button>
    </div>
    <button class="btn btn-primary btn-sm" onclick={openNew}>{t('btn.addProvider')}</button>
  </div>
  {#if loading}<p style="color:var(--text-dim)">{t('loading.providers')}</p>{:else}
    <div class="provider-grid" class:list-view={view==='list'}>
      {#each filteredEntries as [providerName, provider]}
        {@const enabled=provider.enabled!==false}{@const info=displayInfo(provider)}
        <div class="provider-card" class:disabled={!enabled} class:config-error={!!provider.validation_error}>
          <div class="card-header"><div class="name">{#if info.logo}<img class="provider-logo" class:invert-in-dark={info.invertLogo} src={info.logo} alt="" />{/if}{providerName}{#if provider.validation_error}<span class="badge badge-error" title={provider.validation_error}>{t('provider.configError')}</span>{/if}</div><label class="toggle" title={enabled?t('provider.enabled'):t('provider.disabled')}><input type="checkbox" checked={enabled} onchange={()=>void toggle(providerName)} /><span class="slider"></span></label></div>
          {#if view==='list'}
            <div class="field" title={`${info.vendor} · ${info.protocol}`}><code>{info.vendor} · {info.protocol}</code></div><div class="field" title={provider.base_url ?? ''}><code>{provider.base_url ?? ''}</code></div><div class="field"><code>{config.credential_visible===false?'':provider.api_key ?? ''}</code></div>
          {:else}
            <div class="field">{t('label.providerVendor')}: <code>{info.vendor}</code></div><div class="field">{t('label.providerProtocol')}: <code>{info.protocol}</code></div><div class="field">{t('label.baseUrlShort')} <code>{provider.base_url ?? ''}</code></div>{#if config.credential_visible!==false}<div class="field">{t('label.apiKeyShort')} <code>{provider.api_key ?? ''}</code></div>{/if}{#if provider.proxy}<div class="field">{t('label.proxyShort')} <code>{provider.proxy}</code></div>{/if}
          {/if}
          <div class="actions"><button class="btn btn-sm" onclick={()=>void openEdit(providerName,provider,true)}>{t('btn.clone')}</button><button class="btn btn-sm" onclick={()=>void openEdit(providerName,provider)}>{t('btn.edit')}</button><button class="btn btn-sm btn-danger" onclick={()=>requestDelete(providerName)}>{t('btn.delete')}</button></div>
        </div>
      {:else}<p style="color:var(--text-dim)">{providerEntries.length?t('empty.searchResults'):t('empty.providers')}</p>{/each}
    </div>
  {/if}
</div>

<Modal open={modalOpen} labelledby="provider-modal-title" onclose={()=>modalOpen=false}>
  {#snippet header()}<h3 id="provider-modal-title">{editingName?t('modal.editProvider'):t('modal.addProvider')}</h3>{/snippet}
  <div class="form-group"><label for="provName">{t('label.providerName')}</label><input id="provName" bind:value={name} placeholder={t('placeholder.providerName')} /></div>
  <div class="form-group"><label for="provProvider">{t('label.providerVendor')}</label><div class="provider-preset-row"><div class="type-logo-wrapper">{#if logoFor(selectedVendor)}<img class="type-logo-preview" class:invert-in-dark={providerLogoNeedsDarkInversion(selectedVendor.logo_shim)} src={logoFor(selectedVendor)} alt="" />{/if}<Dropdown id="provProvider" value={vendorId} options={vendors().map((vendor)=>({value:vendor.id,label:t(vendor.label_key)}))} onChange={(value:DropdownValue)=>chooseVendor(String(value))} /></div><Dropdown ariaLabel={t('aria.providerVariant')} value={variantId} options={Object.keys(selectedVendor.variants).map((item)=>({value:item,label:t(`providerVariant.${item}`)}))} onChange={(value:DropdownValue)=>chooseVariant(String(value))} /></div></div>
  <div class="form-group"><label for="provApiType">{t('label.providerProtocol')}</label><Dropdown id="provApiType" value={apiType} optionGroups={protocolGroups().map((group)=>({label:group.label,options:group.items.map((item)=>({value:item,label:protocolLabel(item)}))}))} onChange={(value:DropdownValue)=>chooseProtocol(String(value))} /></div>
  <div class="form-group"><label for="provBaseUrl">{t('label.baseUrl')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker')}</span></span></label><input id="provBaseUrl" bind:value={url} oninput={deriveSelection} placeholder={t('placeholder.baseUrl')} /></div>
  <div class="form-group"><label for="provApiKey">{t('label.apiKey')}</label><div class="provider-key-input"><input id="provApiKey" type={keyVisible?'text':'password'} bind:value={apiKey} autocomplete="new-password" placeholder={editingName?t('label.keyUnchangedHint'):'${OPENAI_API_KEY}'} /><button type="button" class="key-btn" onclick={()=>keyVisible=!keyVisible} aria-label={t('aria.toggleVisibility')}>◉</button></div></div>
  <div class="form-group"><label for="provProxy">{t('label.proxyUrl')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker')}</span></span></label><input id="provProxy" bind:value={proxy} placeholder={t('placeholder.proxyExample')} /></div>
  <div class="form-group checkbox-group"><label><input type="checkbox" bind:checked={allowRedirects} /><span>{t('label.allowRedirects')}</span></label></div>
  {#if apiType==='chat'}<div class="form-group"><div class="checkbox-group"><label><input type="checkbox" bind:checked={softInterrupt} /><span>{t('label.softInterrupt')}</span></label></div><p class="provider-option-description">{t('provider.softInterruptDescription')}</p></div>{/if}
  {#if apiType==='responses'}<div class="form-group"><div class="checkbox-group"><label><input type="checkbox" bind:checked={forceRosettaCompaction} /><span>{t('label.forceRosettaCompaction')}</span></label></div><p class="provider-option-description">{t('provider.forceRosettaCompactionDescription')}</p></div>{/if}
  {#snippet actions()}<button class="btn" onclick={()=>modalOpen=false}>{t('btn.cancel')}</button><button class="btn btn-primary" disabled={busy} onclick={()=>void save()}>{t('btn.save')}</button>{/snippet}
</Modal>

<Modal open={deleteOpen} labelledby="delete-provider-title" onclose={()=>deleteOpen=false}>
  {#snippet header()}<h3 id="delete-provider-title">{t('confirm.deleteProviderTitle')}</h3>{/snippet}
  <p style="margin:8px 0 12px;color:var(--text-dim);font-size:13px">{t('confirm.typeProviderName',{name:pendingDelete})}</p>
  {#if affectedModels.length}<div style="margin-bottom:12px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);font-size:12px;max-height:120px;overflow-y:auto"><div style="color:#cf222e;font-weight:600;margin-bottom:4px">{t('confirm.affectedModels',{count:affectedModels.length})}</div>{#each affectedModels as model}<div style="color:var(--text-dim)">• {model}</div>{/each}</div>{/if}
  <div class="form-group"><input aria-label={t('aria.confirmProviderName')} bind:value={deleteInput} autocomplete="off" spellcheck="false" style="font-family:monospace" /></div>
  {#snippet actions()}<button class="btn" onclick={()=>deleteOpen=false}>{t('btn.cancel')}</button><button class="btn btn-danger" disabled={deleteInput!==pendingDelete||busy} onclick={()=>void confirmDelete()}>{t('btn.delete')}</button>{/snippet}
</Modal>
