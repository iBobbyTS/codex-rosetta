<script lang="ts">
  import { onMount } from 'svelte';
  import Modal from '../components/Modal.svelte';
  import ServerSettingsSection from '../components/ServerSettingsSection.svelte';
  import CredentialEditor from '../components/CredentialEditor.svelte';
  import { api } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import { providerLogo, providerLogoNeedsDarkInversion } from '../lib/provider-logos';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';
  import { SortableTableEnhanced } from '@ibobbyts/svelte-ui-utils/sortable-table';

  type BaseUrlStatus = { base_url:string; current:boolean; status:'available'|'cooling' };
  type Credential = { id:string; key:string };
  type UrlRow = { id:string; value:string };
  type CredentialRow = Credential & { rowId:string };
  type CredentialStatus = { id:string; current:boolean; status:'available'|'cooling' };
  type RequestEncoding = 'passthrough'|'identity'|'zstd';
  type EncodingProbe = { ok:boolean; status_code:number|null; error:string|null };
  type EncodingDetection = { selected:RequestEncoding|null; identity:EncodingProbe; zstd:EncodingProbe };
  type Provider = { provider?: string; base_urls?: string[]; current_base_url?: string; base_url_statuses?: BaseUrlStatus[]; api_keys?: Credential[]; current_api_key?: string; credential_statuses?: CredentialStatus[]; api_type?: string; request_encoding?: RequestEncoding; proxy?: string; enabled?: boolean; allow_redirects?: boolean; soft_interrupt?: boolean; force_rosetta_compaction?: boolean; validation_error?: string };
  type ModelRoute = string | { provider?: string };
  type ModelGroup = { provider?: string; models?: Record<string, unknown> };
  type Variant = { endpoints: Record<string,string> };
  type Vendor = { id:string; label_key:string; logo_shim?:string; soft_interrupt_default?:boolean; recommended_api_type:string; adapted_api_types:Record<string,string>; known_supported_api_types:string[]; variants:Record<string,Variant> };
  type ProviderCatalog = { api_types:string[]; providers:Record<string,Omit<Vendor,'id'>> };
  type Config = { providers?: Record<string, Provider>; models?: Record<string, ModelRoute>; model_groups?: Record<string, ModelGroup>; known_api_types?: string[]; provider_catalog?:ProviderCatalog; credential_visible?: boolean };

  let config = $state<Config>({});
  let loading = $state(true); let busy = $state(false); let error = $state(''); let notice = $state('');
  let search = $state(''); let view = $state(localStorage.getItem('provider-view') === 'grid' ? 'grid' : 'list');
  let modalOpen = $state(false); let deleteOpen = $state(false); let editingName = $state('');
  let rowSequence = 0;
  function nextRowId(prefix:string):string{return `${prefix}-${++rowSequence}`;}
  function urlRow(value:string):UrlRow{return{id:nextRowId('url'),value};}
  function credentialRow(value:Credential):CredentialRow{return{rowId:nextRowId('credential'),...value};}
  const initialUrlRow = urlRow('');
  const initialCredentialRow = credentialRow({id:'primary',key:''});
  let name = $state(''); let urlRows = $state<UrlRow[]>([initialUrlRow]); let currentUrlRowId = $state(initialUrlRow.id); let proxy = $state(''); let apiType = $state(''); let requestEncoding = $state<RequestEncoding>('passthrough'); let detectionModel = $state(''); let detectingEncoding = $state(false); let detectionError = $state(''); let allowRedirects = $state(false); let softInterrupt = $state(false); let forceRosettaCompaction = $state(false);
  let vendorId = $state('custom'); let variantId = $state('custom'); let credentialRows = $state<CredentialRow[]>([initialCredentialRow]); let currentCredentialRowId = $state(initialCredentialRow.rowId);
  let pendingDelete = $state(''); let deleteInput = $state('');

  const providerEntries = $derived(Object.entries(config.providers ?? {}));
  const filteredEntries = $derived(providerEntries.filter(([providerName, provider]) => {
    const query = search.trim().toLowerCase(); if (!query) return true;
    const display = displayInfo(provider);
    return [providerName, ...(provider.base_urls ?? []), provider.api_type, provider.validation_error, display.vendor, display.protocol].some((value) => String(value ?? '').toLowerCase().includes(query));
  }));
  const selectedVendor = $derived(vendorById(vendorId));
  const affectedModels = $derived(Object.entries(config.models ?? {}).filter(([, route]) => (typeof route === 'string' ? route : route.provider) === pendingDelete).map(([model]) => model));

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const normalizeUrl = (value: string) => value.trim().replace(/\/+$/, '');
  function firstUrl(provider:Provider):string{return provider.current_base_url??provider.base_urls?.[0]??'';}
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
    const value=variantId === 'custom' ? '' : protocols[apiType] ?? '';const row=urlRow(value);urlRows=[row];currentUrlRowId=row.id;
  }
  function chooseVendor(value: string): void { const vendor=vendorById(value); vendorId=vendor.id; variantId=Object.keys(vendor.variants)[0]??'custom';apiType=vendor.recommended_api_type;requestEncoding='passthrough';softInterrupt=vendor.soft_interrupt_default===true;forceRosettaCompaction=false;applySelection(); }
  function chooseVariant(value: string): void { variantId = value; applySelection(); }
  function chooseProtocol(value: string): void { apiType = value; if(value==='responses')requestEncoding='passthrough';const next=variantId==='custom'?'':variant().endpoints[value] ?? '';const row=urlRow(next);urlRows=[row];currentUrlRowId=row.id; }
  function deriveSelection(): void { const found=Object.entries(selectedVendor.variants).find(([,item])=>item===variantForUrl(selectedVendor,urlRows[0]?.value??''));variantId=found?.[0]??'custom'; }
  function setUrl(rowId:string,value:string):void{urlRows=urlRows.map((item)=>item.id===rowId?{...item,value}:item);deriveSelection();}
  function addUrl():void{urlRows=[...urlRows,urlRow('')];}
  function reorderUrls(next:UrlRow[]):void{urlRows=next;deriveSelection();}
  function removeUrl(row:UrlRow):void{if(urlRows.length===1)return;const index=urlRows.findIndex((item)=>item.id===row.id);if(index<0)return;const next=urlRows.filter((item)=>item.id!==row.id);if(currentUrlRowId===row.id)currentUrlRowId=next[index]?.id??next[0]?.id??'';urlRows=next;deriveSelection();}
  function addCredential():void{let index=credentialRows.length+1;let id=`credential-${index}`;while(credentialRows.some((item)=>item.id===id)){index+=1;id=`credential-${index}`;}credentialRows=[...credentialRows,credentialRow({id,key:''})];}
  function updateCredential(rowId:string,field:'id'|'key',value:string):void{credentialRows=credentialRows.map((item)=>item.rowId===rowId?{...item,[field]:value}:item);}
  function reorderCredentials(next:CredentialRow[]):void{credentialRows=next;}
  function removeCredential(row:CredentialRow):void{if(credentialRows.length===1)return;const index=credentialRows.findIndex((item)=>item.rowId===row.rowId);if(index<0)return;const next=credentialRows.filter((item)=>item.rowId!==row.rowId);if(currentCredentialRowId===row.rowId)currentCredentialRowId=next[index]?.rowId??next[0]?.rowId??'';credentialRows=next;}
  function protocolGroups():{label:string;items:string[]}[]{const adapted=Object.keys(selectedVendor.adapted_api_types);const known=selectedVendor.known_supported_api_types.filter((item)=>!adapted.includes(item));const other=allowedTypes().filter((item)=>!adapted.includes(item)&&!known.includes(item));return[{label:'',items:adapted},{label:t('provider.rosettaUnadapted'),items:known},{label:t('provider.maybeUnsupported',{provider:t(selectedVendor.label_key)}),items:other}].filter((group)=>group.items.length);}
  function clearForm(): void {
    const url=urlRow('');const credential=credentialRow({id:'primary',key:''});editingName=''; name=''; urlRows=[url]; currentUrlRowId=url.id; proxy=''; apiType=allowedTypes()[0] ?? ''; requestEncoding='passthrough'; detectionModel=''; detectingEncoding=false; detectionError=''; allowRedirects=false; softInterrupt=false; forceRosettaCompaction=false; vendorId='custom'; variantId='custom'; credentialRows=[credential];currentCredentialRowId=credential.rowId; error='';
  }
  function openNew(): void { clearForm(); modalOpen=true; }
  async function openEdit(providerName: string, provider: Provider, clone = false): Promise<void> {
    editingName = clone ? '' : providerName; name = clone ? `${providerName}-copy` : providerName; urlRows=(provider.base_urls??[]).map(urlRow);if(!urlRows.length)urlRows=[urlRow('')];currentUrlRowId=urlRows.find((row)=>row.value===firstUrl(provider))?.id??urlRows[0].id; proxy=provider.proxy ?? '';
    apiType = allowedTypes().includes(provider.api_type ?? '') ? provider.api_type ?? '' : allowedTypes()[0] ?? '';
    vendorId=vendorById(provider.provider).id; requestEncoding=provider.request_encoding??'passthrough'; detectionModel=''; detectingEncoding=false; detectionError=''; allowRedirects=provider.allow_redirects === true; softInterrupt=provider.soft_interrupt === true; forceRosettaCompaction=provider.force_rosetta_compaction === true;credentialRows=(provider.api_keys??[]).map((item)=>credentialRow({...item,key:clone?'':item.key}));if(!credentialRows.length)credentialRows=[credentialRow({id:'primary',key:''})];currentCredentialRowId=credentialRows.find((row)=>row.id===(provider.current_api_key??credentialRows[0].id))?.rowId??credentialRows[0].rowId;deriveSelection();modalOpen=true;error='';
  }
  async function load(signal?: AbortSignal): Promise<void> { try { config=await api.get<Config>('/admin/api/config',signal); error=''; } catch(cause){ if (!(cause instanceof DOMException && cause.name==='AbortError')) error=message(cause); } finally { loading=false; } }
  async function save(): Promise<void> {
    const normalizedUrls=urlRows.map((row)=>normalizeUrl(row.value));const currentUrl=normalizeUrl(urlRows.find((row)=>row.id===currentUrlRowId)?.value??'');if (!name.trim() || !apiType || !allowedTypes().includes(apiType) || normalizedUrls.some((value)=>!/^https?:\/\//i.test(value)) || new Set(normalizedUrls).size!==normalizedUrls.length || !normalizedUrls.includes(currentUrl)) { error=t('error.providerFieldsRequired'); return; }
    const normalizedCredentials=credentialRows.map((item)=>({id:item.id.trim(),key:item.key.trim()}));const currentCredential=credentialRows.find((row)=>row.rowId===currentCredentialRowId)?.id.trim()??'';if(normalizedCredentials.some((item)=>!item.id||!item.key)||new Set(normalizedCredentials.map((item)=>item.id)).size!==normalizedCredentials.length||!normalizedCredentials.some((item)=>item.id===currentCredential)){error=t('error.providerCredentialRequired');return;}
    busy=true; error=''; try { const body: Record<string,unknown>={provider:vendorId,api_type:apiType,base_urls:normalizedUrls,current_base_url:currentUrl,api_keys:normalizedCredentials,current_api_key:currentCredential,proxy:proxy.trim(),allow_redirects:allowRedirects}; if(apiType==='chat')body.soft_interrupt=softInterrupt; if(apiType==='responses'){body.request_encoding=requestEncoding;body.force_rosetta_compaction=forceRosettaCompaction;} if(editingName&&editingName!==name.trim())body.rename_from=editingName; await api.put(`/admin/api/config/providers/${encodeURIComponent(name.trim())}`,body); modalOpen=false; notice=t('toast.providerSaved',{name:name.trim()}); await load(); } catch(cause){error=message(cause);} finally{busy=false;}
  }
  function detectionBody():Record<string,unknown>|null{const providerName=name.trim();const model=detectionModel.trim();const currentUrl=normalizeUrl(urlRows.find((row)=>row.id===currentUrlRowId)?.value??'');const currentCredential=credentialRows.find((row)=>row.rowId===currentCredentialRowId);const credentialId=currentCredential?.id.trim()??'';const credentialKey=currentCredential?.key.trim()??'';if(!providerName||!model||!/^https?:\/\//i.test(currentUrl)||!credentialId||!credentialKey)return null;const body:Record<string,unknown>={provider:vendorId,api_type:'responses',model,current_base_url:currentUrl,api_keys:[{id:credentialId,key:credentialKey}],current_api_key:credentialId,proxy:proxy.trim(),allow_redirects:allowRedirects};if(editingName&&editingName!==providerName)body.rename_from=editingName;return body;}
  async function detectRequestEncoding():Promise<void>{const body=detectionBody();if(!body){detectionError=t('error.requestEncodingDetectionFields');return;}const signature=JSON.stringify(body);detectingEncoding=true;detectionError='';error='';try{const result=await api.post<EncodingDetection>(`/admin/api/config/providers/${encodeURIComponent(name.trim())}/detect-request-encoding`,body);if(signature!==JSON.stringify(detectionBody())){detectionError=t('error.requestEncodingDetectionStale');return;}if(result.selected){requestEncoding=result.selected;notice=t('toast.requestEncodingDetected',{encoding:t(`provider.requestEncoding.${result.selected}`)});return;}detectionError=t('error.requestEncodingDetectionFailed',{identity:result.identity.error??'',zstd:result.zstd.error??''});}catch(cause){detectionError=message(cause);}finally{detectingEncoding=false;}}
  async function action(operation:()=>Promise<unknown>,success:string):Promise<void>{busy=true;error='';try{await operation();await load();notice=success;}catch(cause){error=message(cause);}finally{busy=false;}}
  async function toggle(providerName:string):Promise<void>{await action(()=>api.post(`/admin/api/config/providers/${encodeURIComponent(providerName)}/toggle`),t('toast.providerToggled'));}
  async function selectCurrent(providerName:string,baseUrl:string):Promise<void>{await action(()=>api.post(`/admin/api/config/providers/${encodeURIComponent(providerName)}/current-base-url`,{current_base_url:baseUrl}),t('toast.providerCurrentUrlChanged'));}
  async function selectCredential(providerName:string,credentialId:string):Promise<void>{await action(()=>api.post(`/admin/api/config/providers/${encodeURIComponent(providerName)}/current-base-url`,{credential_id:credentialId}),t('toast.providerCurrentCredentialChanged'));}
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
            <div class="field" title={`${info.vendor} · ${info.protocol}`}><code>{info.vendor} · {info.protocol}</code></div><div class="field" title={firstUrl(provider)}><code>{firstUrl(provider)}</code></div><div class="field"><code>{provider.api_keys?.find((item)=>item.id===provider.current_api_key)?.key ?? ''}</code></div>
          {:else}
            <div class="field">{t('label.providerVendor')}: <code>{info.vendor}</code></div><div class="field">{t('label.providerProtocol')}: <code>{info.protocol}</code></div>{#each provider.base_url_statuses??[] as item}<div class="provider-url-status" class:available={item.status==='available'} class:cooling={item.status==='cooling'}><code>{item.base_url}</code><span>{t(`provider.url.${item.status}`)}</span>{#if item.current}<span>{t('provider.url.current')}</span>{:else}<button class="btn btn-sm" aria-label={t('aria.makeBaseUrlCurrent',{url:item.base_url})} onclick={()=>void selectCurrent(providerName,item.base_url)}>{t('provider.url.select')}</button>{/if}</div>{/each}{#each provider.credential_statuses??[] as item}<div class="provider-url-status" class:available={item.status==='available'} class:cooling={item.status==='cooling'}><code>{provider.api_keys?.find((credential)=>credential.id===item.id)?.key ?? item.id}</code><span>{t(`provider.url.${item.status}`)}</span>{#if item.current}<span>{t('provider.url.current')}</span>{:else}<button class="btn btn-sm" aria-label={t('aria.makeCredentialCurrent',{id:item.id})} onclick={()=>void selectCredential(providerName,item.id)}>{t('provider.url.select')}</button>{/if}</div>{/each}{#if provider.proxy}<div class="field">{t('label.proxyShort')} <code>{provider.proxy}</code></div>{/if}
          {/if}
          <div class="actions"><button class="btn btn-sm" onclick={()=>void openEdit(providerName,provider,true)}>{t('btn.clone')}</button><button class="btn btn-sm" onclick={()=>void openEdit(providerName,provider)}>{t('btn.edit')}</button><button class="btn btn-sm btn-danger" onclick={()=>requestDelete(providerName)}>{t('btn.delete')}</button></div>
        </div>
      {:else}<p style="color:var(--text-dim)">{providerEntries.length?t('empty.searchResults'):t('empty.providers')}</p>{/each}
    </div>
  {/if}
</div>

<Modal open={modalOpen} className="provider-modal" labelledby="provider-modal-title" onclose={()=>modalOpen=false}>
  {#snippet header()}<h3 id="provider-modal-title">{editingName?t('modal.editProvider'):t('modal.addProvider')}</h3>{/snippet}
  <div class="form-group"><label for="provName">{t('label.providerName')}</label><input id="provName" bind:value={name} placeholder={t('placeholder.providerName')} /></div>
  <div class="form-group"><label for="provProvider">{t('label.providerVendor')}</label><div class="provider-preset-row"><div class="type-logo-wrapper">{#if logoFor(selectedVendor)}<img class="type-logo-preview" class:invert-in-dark={providerLogoNeedsDarkInversion(selectedVendor.logo_shim)} src={logoFor(selectedVendor)} alt="" />{/if}<Dropdown id="provProvider" value={vendorId} options={vendors().map((vendor)=>({value:vendor.id,label:t(vendor.label_key)}))} fitViewport={true} onChange={(value:DropdownValue)=>chooseVendor(String(value))} /></div><Dropdown ariaLabel={t('aria.providerVariant')} value={variantId} options={Object.keys(selectedVendor.variants).map((item)=>({value:item,label:t(`providerVariant.${item}`)}))} fitViewport={true} onChange={(value:DropdownValue)=>chooseVariant(String(value))} /></div></div>
  <div class="form-group"><label for="provApiType">{t('label.providerProtocol')}</label><Dropdown id="provApiType" value={apiType} options={protocolGroups().flatMap((group)=>group.items.map((item)=>({value:item,label:protocolLabel(item)})))} fitViewport={true} fitContent={true} menuAlign="left" onChange={(value:DropdownValue)=>chooseProtocol(String(value))} /></div>
  <div class="form-group">
    <div class="form-label">{t('label.baseUrls')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker')}</span></span></div>
    <SortableTableEnhanced items={urlRows} currentId={currentUrlRowId} disabled={busy} onReorder={reorderUrls} onRemove={removeUrl} onCurrentChange={(row)=>{currentUrlRowId=row.id;}} getCurrentLabel={(row)=>t('aria.makeBaseUrlCurrent',{url:row.value||t('label.baseUrl')})} getDragLabel={(row)=>t('aria.dragBaseUrl',{url:row.value||t('label.baseUrl')})} getRemoveLabel={(row)=>t('aria.removeBaseUrl',{url:row.value||t('label.baseUrl')})}>
      {#snippet header()}<th>{t('col.baseUrl')}</th>{/snippet}
      {#snippet children(row,index)}<td><input aria-label={t('aria.baseUrl',{index:index+1})} value={row.value} oninput={(event)=>setUrl(row.id,event.currentTarget.value)} placeholder={t('placeholder.baseUrl')} /></td>{/snippet}
    </SortableTableEnhanced>
    <button type="button" class="btn btn-sm" onclick={addUrl}>{t('btn.addBaseUrl')}</button>
  </div>
  <div class="form-group">
    <div class="form-label">{t('label.providerCredentials')}</div>
    <SortableTableEnhanced items={credentialRows} getId={(row)=>row.rowId} currentId={currentCredentialRowId} disabled={busy} onReorder={reorderCredentials} onRemove={removeCredential} onCurrentChange={(row)=>{currentCredentialRowId=row.rowId;}} getCurrentLabel={(row)=>t('aria.makeCredentialCurrent',{id:row.id||t('placeholder.credentialId')})} getDragLabel={(row)=>t('aria.dragCredential',{id:row.id||t('placeholder.credentialId')})} getRemoveLabel={(row)=>t('aria.removeCredential',{id:row.id||t('placeholder.credentialId')})}>
      {#snippet header()}<th>{t('col.credentialId')}</th><th>{t('col.credentialKey')}</th>{/snippet}
      {#snippet children(row)}<td><input type="text" aria-label={t('aria.credentialId',{id:row.id})} value={row.id} oninput={(event)=>updateCredential(row.rowId,'id',event.currentTarget.value)} placeholder={t('placeholder.credentialId')} /></td><td><CredentialEditor ariaLabel={t('aria.credentialKey',{id:row.id})} clearLabel={t('aria.clearCredentialKey',{id:row.id})} value={row.key} onchange={(value)=>updateCredential(row.rowId,'key',value)} placeholder={'${OPENAI_API_KEY}'} /></td>{/snippet}
    </SortableTableEnhanced>
    <div class="provider-key-actions"><button type="button" class="btn btn-sm" onclick={addCredential}>{t('btn.addCredential')}</button></div>
  </div>
  <div class="form-group"><label for="provProxy">{t('label.proxyUrl')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker')}</span></span></label><input id="provProxy" bind:value={proxy} placeholder={t('placeholder.proxyExample')} /></div>
  <div class="form-group checkbox-group"><label><input type="checkbox" bind:checked={allowRedirects} /><span>{t('label.allowRedirects')}</span></label></div>
  {#if apiType==='responses'}<div class="form-group"><label for="provRequestEncoding">{t('label.requestEncoding')}</label><div class="request-encoding-row"><Dropdown id="provRequestEncoding" value={requestEncoding} options={['passthrough','identity','zstd'].map((value)=>({value,label:t(`provider.requestEncoding.${value}`)}))} fitViewport={true} fitContent={true} menuAlign="left" onChange={(value:DropdownValue)=>{requestEncoding=String(value) as RequestEncoding;}} /><input aria-label={t('label.requestEncodingDetectionModel')} bind:value={detectionModel} placeholder={t('placeholder.requestEncodingDetectionModel')} /><button type="button" class="btn btn-sm" disabled={detectingEncoding} onclick={()=>void detectRequestEncoding()}>{detectingEncoding?t('btn.detectingRequestEncoding'):t('btn.detectRequestEncoding')}</button></div><p class="provider-option-description">{t('provider.requestEncodingDescription')}</p>{#if detectionError}<pre class="request-encoding-error" role="alert">{detectionError}</pre>{/if}</div>{/if}
  {#if apiType==='chat'}<div class="form-group"><div class="checkbox-group"><label><input type="checkbox" bind:checked={softInterrupt} /><span>{t('label.softInterrupt')}</span></label></div><p class="provider-option-description">{t('provider.softInterruptDescription')}</p></div>{/if}
  {#if apiType==='responses'}<div class="form-group"><div class="checkbox-group"><label><input type="checkbox" bind:checked={forceRosettaCompaction} /><span>{t('label.forceRosettaCompaction')}</span></label></div><p class="provider-option-description">{t('provider.forceRosettaCompactionDescription')}</p></div>{/if}
  {#snippet actions()}<button class="btn" onclick={()=>modalOpen=false}>{t('btn.cancel')}</button><button class="btn btn-primary" disabled={busy} onclick={()=>void save()}>{t('btn.save')}</button>{/snippet}
</Modal>

<style>
  :global(.modal.provider-modal) { width: 880px; max-width: 80vw; max-height: 80vh; }
  .provider-url-status{display:flex;align-items:center;gap:6px;margin:5px 0;padding:5px 7px;border-radius:var(--radius);font-size:11px}
  .provider-url-status.available{background:color-mix(in srgb,var(--green) 10%,transparent)}
  .provider-url-status.cooling{background:color-mix(in srgb,var(--orange) 12%,transparent)}
  .provider-url-status code{min-width:0;flex:1}
  .provider-key-actions{display:flex;gap:6px;margin-top:6px}
  .request-encoding-row{display:grid;grid-template-columns:minmax(180px,1fr) minmax(160px,1fr) auto;gap:8px;align-items:center}
  .request-encoding-error{margin:8px 0 0;padding:8px;border:1px solid var(--red);border-radius:var(--radius);white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.45 monospace;color:var(--red);background:color-mix(in srgb,var(--red) 7%,transparent)}
  @media (max-width: 700px){.request-encoding-row{grid-template-columns:1fr}.request-encoding-row .btn{justify-self:start}}
</style>

<Modal open={deleteOpen} labelledby="delete-provider-title" onclose={()=>deleteOpen=false}>
  {#snippet header()}<h3 id="delete-provider-title">{t('confirm.deleteProviderTitle')}</h3>{/snippet}
  <p style="margin:8px 0 12px;color:var(--text-dim);font-size:13px">{t('confirm.typeProviderName',{name:pendingDelete})}</p>
  {#if affectedModels.length}<div style="margin-bottom:12px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);font-size:12px;max-height:120px;overflow-y:auto"><div style="color:#cf222e;font-weight:600;margin-bottom:4px">{t('confirm.affectedModels',{count:affectedModels.length})}</div>{#each affectedModels as model}<div style="color:var(--text-dim)">• {model}</div>{/each}</div>{/if}
  <div class="form-group"><input aria-label={t('aria.confirmProviderName')} bind:value={deleteInput} autocomplete="off" spellcheck="false" style="font-family:monospace" /></div>
  {#snippet actions()}<button class="btn" onclick={()=>deleteOpen=false}>{t('btn.cancel')}</button><button class="btn btn-danger" disabled={deleteInput!==pendingDelete||busy} onclick={()=>void confirmDelete()}>{t('btn.delete')}</button>{/snippet}
</Modal>
