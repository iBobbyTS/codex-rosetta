<script lang="ts">
  import { onMount } from 'svelte';
  import Modal from '../components/Modal.svelte';
  import ServerSettingsSection from '../components/ServerSettingsSection.svelte';
  import { api } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  import { providerLogo, providerLogoNeedsDarkInversion } from '../lib/provider-logos';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';
  import OrderedListEditor, { type OrderedListItem } from '../components/OrderedListEditor.svelte';

  type BaseUrlStatus = { base_url:string; current:boolean; status:'available'|'cooling' };
  type Credential = { id:string; key:string };
  type CredentialStatus = { id:string; current:boolean; status:'available'|'cooling' };
  type Provider = { provider?: string; base_urls?: string[]; current_base_url?: string; base_url_statuses?: BaseUrlStatus[]; api_keys?: Credential[]; current_api_key?: string; credential_statuses?: CredentialStatus[]; api_type?: string; proxy?: string; enabled?: boolean; allow_redirects?: boolean; soft_interrupt?: boolean; force_rosetta_compaction?: boolean; validation_error?: string };
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
  let name = $state(''); let urls = $state<string[]>(['']); let currentUrl = $state(''); let proxy = $state(''); let apiType = $state(''); let allowRedirects = $state(false); let softInterrupt = $state(false); let forceRosettaCompaction = $state(false);
  let vendorId = $state('custom'); let variantId = $state('custom'); let credentials = $state<Credential[]>([{id:'primary',key:''}]); let currentCredential = $state('primary'); let keyVisible = $state(false);
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
    const value=variantId === 'custom' ? '' : protocols[apiType] ?? '';urls=[value];currentUrl=value;
  }
  function chooseVendor(value: string): void { const vendor=vendorById(value); vendorId=vendor.id; variantId=Object.keys(vendor.variants)[0]??'custom';apiType=vendor.recommended_api_type;softInterrupt=vendor.soft_interrupt_default===true;forceRosettaCompaction=false;applySelection(); }
  function chooseVariant(value: string): void { variantId = value; applySelection(); }
  function chooseProtocol(value: string): void { apiType = value; const next=variantId==='custom'?'':variant().endpoints[value] ?? '';urls=[next];currentUrl=next; }
  function deriveSelection(): void { const found=Object.entries(selectedVendor.variants).find(([,item])=>item===variantForUrl(selectedVendor,urls[0]??''));variantId=found?.[0]??'custom'; }
  function setUrl(index:number,value:string):void{urls=urls.map((item,position)=>position===index?value:item);if(!currentUrl||!urls.includes(currentUrl))currentUrl=value;deriveSelection();}
  function addUrl():void{urls=[...urls,''];}
  function moveUrl(index:number,offset:-1|1):void{const target=index+offset;if(target<0||target>=urls.length)return;const next=[...urls];[next[index],next[target]]=[next[target],next[index]];urls=next;}
  function removeUrl(index:number):void{if(urls.length===1)return;const removed=urls[index];const next=urls.filter((_,position)=>position!==index);if(currentUrl===removed)currentUrl=next[index]??next[0]??'';urls=next;deriveSelection();}
  const urlItems = $derived(urls.map((value,index):OrderedListItem=>({id:String(index),value,current:currentUrl===value})));
  const credentialItems = $derived(credentials.map((item,index):OrderedListItem=>({id:String(index),value:item.key,current:currentCredential===item.id})));
  function moveById<T>(items:T[],id:string,offset:-1|1,idFor:(item:T,index:number)=>string):T[]{const index=items.findIndex((item,position)=>idFor(item,position)===id);const target=index+offset;if(index<0||target<0||target>=items.length)return items;const next=[...items];[next[index],next[target]]=[next[target],next[index]];return next;}
  function moveUrlId(id:string,offset:-1|1):void{urls=moveById(urls,id,offset,(_,index)=>String(index));}
  function removeUrlId(id:string):void{removeUrl(Number(id));}
  function addCredential():void{let index=credentials.length+1;let id=`credential-${index}`;while(credentials.some((item)=>item.id===id)){index+=1;id=`credential-${index}`;}credentials=[...credentials,{id,key:''}];}
  function updateCredential(index:number,field:'id'|'key',value:string):void{const previous=credentials[index];credentials=credentials.map((item,position)=>position===index?{...item,[field]:value}:item);if(field==='id'&&currentCredential===previous.id)currentCredential=value;}
  function moveCredential(id:string,offset:-1|1):void{credentials=moveById(credentials,id,offset,(_,index)=>String(index));}
  function removeCredential(id:string):void{if(credentials.length===1)return;const index=Number(id);const removed=credentials[index];const next=credentials.filter((_,position)=>position!==index);if(currentCredential===removed.id)currentCredential=next[index]?.id??next[0]?.id??'';credentials=next;}
  function protocolGroups():{label:string;items:string[]}[]{const adapted=Object.keys(selectedVendor.adapted_api_types);const known=selectedVendor.known_supported_api_types.filter((item)=>!adapted.includes(item));const other=allowedTypes().filter((item)=>!adapted.includes(item)&&!known.includes(item));return[{label:'',items:adapted},{label:t('provider.rosettaUnadapted'),items:known},{label:t('provider.maybeUnsupported',{provider:t(selectedVendor.label_key)}),items:other}].filter((group)=>group.items.length);}
  function clearForm(): void {
    editingName=''; name=''; urls=['']; currentUrl=''; proxy=''; apiType=allowedTypes()[0] ?? ''; allowRedirects=false; softInterrupt=false; forceRosettaCompaction=false; vendorId='custom'; variantId='custom'; credentials=[{id:'primary',key:''}];currentCredential='primary';keyVisible=false; error='';
  }
  function openNew(): void { clearForm(); modalOpen=true; }
  async function openEdit(providerName: string, provider: Provider, clone = false): Promise<void> {
    editingName = clone ? '' : providerName; name = clone ? `${providerName}-copy` : providerName; urls=[...(provider.base_urls??[])];if(!urls.length)urls=[''];currentUrl=firstUrl(provider); proxy=provider.proxy ?? '';
    apiType = allowedTypes().includes(provider.api_type ?? '') ? provider.api_type ?? '' : allowedTypes()[0] ?? '';
    vendorId=vendorById(provider.provider).id; allowRedirects=provider.allow_redirects === true; softInterrupt=provider.soft_interrupt === true; forceRosettaCompaction=provider.force_rosetta_compaction === true;credentials=(provider.api_keys??[]).map((item)=>({...item}));if(!credentials.length)credentials=[{id:'primary',key:''}];currentCredential=provider.current_api_key??credentials[0].id;keyVisible=false;deriveSelection();modalOpen=true;error='';
  }
  async function load(signal?: AbortSignal): Promise<void> { try { config=await api.get<Config>('/admin/api/config',signal); error=''; } catch(cause){ if (!(cause instanceof DOMException && cause.name==='AbortError')) error=message(cause); } finally { loading=false; } }
  async function save(): Promise<void> {
    const normalizedUrls=urls.map(normalizeUrl);if (!name.trim() || !apiType || !allowedTypes().includes(apiType) || normalizedUrls.some((value)=>!/^https?:\/\//i.test(value)) || new Set(normalizedUrls).size!==normalizedUrls.length || !normalizedUrls.includes(normalizeUrl(currentUrl))) { error=t('error.providerFieldsRequired'); return; }
    const normalizedCredentials=credentials.map((item)=>({id:item.id.trim(),key:item.key.trim()}));if(normalizedCredentials.some((item)=>!item.id||!item.key)||new Set(normalizedCredentials.map((item)=>item.id)).size!==normalizedCredentials.length||!normalizedCredentials.some((item)=>item.id===currentCredential)){error=t('error.providerCredentialRequired');return;}
    busy=true; error=''; try { const body: Record<string,unknown>={provider:vendorId,api_type:apiType,base_urls:normalizedUrls,current_base_url:normalizeUrl(currentUrl),api_keys:normalizedCredentials,current_api_key:currentCredential,proxy:proxy.trim(),allow_redirects:allowRedirects}; if(apiType==='chat')body.soft_interrupt=softInterrupt; if(apiType==='responses')body.force_rosetta_compaction=forceRosettaCompaction; if(editingName&&editingName!==name.trim())body.rename_from=editingName; await api.put(`/admin/api/config/providers/${encodeURIComponent(name.trim())}`,body); modalOpen=false; notice=t('toast.providerSaved',{name:name.trim()}); await load(); } catch(cause){error=message(cause);} finally{busy=false;}
  }
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

<Modal open={modalOpen} labelledby="provider-modal-title" onclose={()=>modalOpen=false}>
  {#snippet header()}<h3 id="provider-modal-title">{editingName?t('modal.editProvider'):t('modal.addProvider')}</h3>{/snippet}
  <div class="form-group"><label for="provName">{t('label.providerName')}</label><input id="provName" bind:value={name} placeholder={t('placeholder.providerName')} /></div>
  <div class="form-group"><label for="provProvider">{t('label.providerVendor')}</label><div class="provider-preset-row"><div class="type-logo-wrapper">{#if logoFor(selectedVendor)}<img class="type-logo-preview" class:invert-in-dark={providerLogoNeedsDarkInversion(selectedVendor.logo_shim)} src={logoFor(selectedVendor)} alt="" />{/if}<Dropdown id="provProvider" value={vendorId} options={vendors().map((vendor)=>({value:vendor.id,label:t(vendor.label_key)}))} fitViewport={true} onChange={(value:DropdownValue)=>chooseVendor(String(value))} /></div><Dropdown ariaLabel={t('aria.providerVariant')} value={variantId} options={Object.keys(selectedVendor.variants).map((item)=>({value:item,label:t(`providerVariant.${item}`)}))} fitViewport={true} onChange={(value:DropdownValue)=>chooseVariant(String(value))} /></div></div>
  <div class="form-group"><label for="provApiType">{t('label.providerProtocol')}</label><Dropdown id="provApiType" value={apiType} options={protocolGroups().flatMap((group)=>group.items.map((item)=>({value:item,label:protocolLabel(item)})))} fitViewport={true} onChange={(value:DropdownValue)=>chooseProtocol(String(value))} /></div>
  <div class="form-group"><div class="form-label">{t('label.baseUrls')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker')}</span></span></div><OrderedListEditor items={urlItems} onmove={moveUrlId} onremove={removeUrlId} oncurrent={(id)=>currentUrl=urls[Number(id)]} moveUpLabel={(item)=>t('aria.moveBaseUrlUp',{url:item.value??''})} moveDownLabel={(item)=>t('aria.moveBaseUrlDown',{url:item.value??''})} currentLabel={(item)=>t('aria.makeBaseUrlCurrent',{url:item.value??''})} removeLabel={(item)=>t('aria.removeBaseUrl',{url:item.value??''})}>{#snippet children(item,index)}<input aria-label={t('aria.baseUrl',{index:index+1})} value={item.value??''} oninput={(event)=>setUrl(index,event.currentTarget.value)} placeholder={t('placeholder.baseUrl')} />{/snippet}</OrderedListEditor><button type="button" class="btn btn-sm" onclick={addUrl}>{t('btn.addBaseUrl')}</button></div>
  <div class="form-group"><div class="form-label">{t('label.providerCredentials')}</div><OrderedListEditor items={credentialItems} onmove={moveCredential} onremove={removeCredential} oncurrent={(id)=>currentCredential=credentials[Number(id)].id} moveUpLabel={(item)=>t('aria.moveOrderedItemUp',{id:credentials[Number(item.id)].id})} moveDownLabel={(item)=>t('aria.moveOrderedItemDown',{id:credentials[Number(item.id)].id})} currentLabel={(item)=>t('aria.makeCredentialCurrent',{id:credentials[Number(item.id)].id})} removeLabel={(item)=>t('aria.removeOrderedItem',{id:credentials[Number(item.id)].id})}>{#snippet children(item,index)}{@const credential=credentials[index]}<input aria-label={t('aria.credentialId',{id:credential.id})} value={credential.id} oninput={(event)=>updateCredential(index,'id',event.currentTarget.value)} placeholder={t('placeholder.credentialId')} /><input aria-label={t('aria.credentialKey',{id:credential.id})} type={keyVisible?'text':'password'} value={credential.key} oninput={(event)=>updateCredential(index,'key',event.currentTarget.value)} autocomplete="new-password" placeholder={'${OPENAI_API_KEY}'} />{/snippet}</OrderedListEditor><div class="provider-key-actions"><button type="button" class="btn btn-sm" onclick={addCredential}>{t('btn.addCredential')}</button><button type="button" class="key-btn" onclick={()=>keyVisible=!keyVisible} aria-label={t('aria.toggleVisibility')}>◉</button></div></div>
  <div class="form-group"><label for="provProxy">{t('label.proxyUrl')}<span class="hint-icon">?<span class="hint-popup">{t('hint.docker')}</span></span></label><input id="provProxy" bind:value={proxy} placeholder={t('placeholder.proxyExample')} /></div>
  <div class="form-group checkbox-group"><label><input type="checkbox" bind:checked={allowRedirects} /><span>{t('label.allowRedirects')}</span></label></div>
  {#if apiType==='chat'}<div class="form-group"><div class="checkbox-group"><label><input type="checkbox" bind:checked={softInterrupt} /><span>{t('label.softInterrupt')}</span></label></div><p class="provider-option-description">{t('provider.softInterruptDescription')}</p></div>{/if}
  {#if apiType==='responses'}<div class="form-group"><div class="checkbox-group"><label><input type="checkbox" bind:checked={forceRosettaCompaction} /><span>{t('label.forceRosettaCompaction')}</span></label></div><p class="provider-option-description">{t('provider.forceRosettaCompactionDescription')}</p></div>{/if}
  {#snippet actions()}<button class="btn" onclick={()=>modalOpen=false}>{t('btn.cancel')}</button><button class="btn btn-primary" disabled={busy} onclick={()=>void save()}>{t('btn.save')}</button>{/snippet}
</Modal>

<style>.provider-url-status{display:flex;align-items:center;gap:6px;margin:5px 0;padding:5px 7px;border-radius:var(--radius);font-size:11px}.provider-url-status.available{background:color-mix(in srgb,var(--green) 10%,transparent)}.provider-url-status.cooling{background:color-mix(in srgb,var(--orange) 12%,transparent)}.provider-url-status code{min-width:0;flex:1}.provider-key-actions{display:flex;gap:6px;margin-top:6px}</style>

<Modal open={deleteOpen} labelledby="delete-provider-title" onclose={()=>deleteOpen=false}>
  {#snippet header()}<h3 id="delete-provider-title">{t('confirm.deleteProviderTitle')}</h3>{/snippet}
  <p style="margin:8px 0 12px;color:var(--text-dim);font-size:13px">{t('confirm.typeProviderName',{name:pendingDelete})}</p>
  {#if affectedModels.length}<div style="margin-bottom:12px;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);font-size:12px;max-height:120px;overflow-y:auto"><div style="color:#cf222e;font-weight:600;margin-bottom:4px">{t('confirm.affectedModels',{count:affectedModels.length})}</div>{#each affectedModels as model}<div style="color:var(--text-dim)">• {model}</div>{/each}</div>{/if}
  <div class="form-group"><input aria-label={t('aria.confirmProviderName')} bind:value={deleteInput} autocomplete="off" spellcheck="false" style="font-family:monospace" /></div>
  {#snippet actions()}<button class="btn" onclick={()=>deleteOpen=false}>{t('btn.cancel')}</button><button class="btn btn-danger" disabled={deleteInput!==pendingDelete||busy} onclick={()=>void confirmDelete()}>{t('btn.delete')}</button>{/snippet}
</Modal>
