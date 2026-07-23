<script lang="ts">
  import { onMount } from 'svelte';
  import Modal from '../components/Modal.svelte';
  import { api } from '../lib/api';
  import { t } from '../lib/i18n.svelte';
  type KeyEntry={id:string;label?:string;key?:string;created?:string};
  let keys=$state<KeyEntry[]>([]);let label=$state('');let manualKey=$state('');let createdKey=$state('');let createOpen=$state(false);let createdOpen=$state(false);let loading=$state(true);let busy=$state(false);let error=$state('');
  const message=(value:unknown)=>value instanceof Error?value.message:String(value);
  async function load(signal?:AbortSignal):Promise<void>{try{keys=(await api.get<{keys?:KeyEntry[]}>('/admin/api/keys',signal)).keys??[];error='';}catch(cause){if(!(cause instanceof DOMException&&cause.name==='AbortError'))error=message(cause);}finally{loading=false;}}
  function openCreate():void{label='';manualKey='';error='';createOpen=true;}
  async function create():Promise<void>{busy=true;error='';try{const body:Record<string,string>={label:label.trim()};if(manualKey)body.key=manualKey;const result=await api.post<Record<string,unknown>>('/admin/api/keys',body);const raw=result.key;createdKey=typeof raw==='string'?raw:raw&&typeof raw==='object'?String((raw as Record<string,unknown>).key??''):'';createOpen=false;createdOpen=true;await load();}catch(cause){error=message(cause);}finally{busy=false;}}
  async function remove(entry:KeyEntry):Promise<void>{if(!confirm(`Delete API key “${entry.label??entry.id}”?`))return;busy=true;error='';try{await api.del(`/admin/api/keys/${encodeURIComponent(entry.id)}`);await load();}catch(cause){error=message(cause);}finally{busy=false;}}
  async function copy():Promise<void>{if(createdKey)await navigator.clipboard.writeText(createdKey);}
  onMount(()=>{const controller=new AbortController();void load(controller.signal);return()=>controller.abort();});
</script>

<div class="section">
  <div class="section-header"><h2>{t('section.apiKeys','API Keys')}</h2><button class="btn btn-primary btn-sm" onclick={openCreate}>{t('btn.generateKey','+ Generate Key')}</button></div>
  <p style="font-size:13px;color:var(--text-dim);margin-bottom:16px">{t('keys.description','Manage gateway API keys used to authenticate requests to /v1/* endpoints.')}</p>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}
  {#if loading}<p style="color:var(--text-dim)">Loading keys...</p>{:else}<div class="table-scroll"><table><thead><tr><th>{t('col.label','Label')}</th><th>{t('col.key','Key')}</th><th>{t('col.created','Created')}</th><th></th></tr></thead><tbody>{#each keys as entry}<tr><td>{entry.label??''}</td><td><code>{entry.key??''}</code></td><td>{entry.created?new Date(entry.created).toLocaleString():'-'}</td><td style="text-align:right"><button class="btn btn-sm btn-danger" disabled={busy} onclick={()=>void remove(entry)}>{t('btn.delete','Delete')}</button></td></tr>{:else}<tr><td colspan="4" class="empty">No API keys.</td></tr>{/each}</tbody></table></div>{/if}
</div>

<Modal open={createOpen} labelledby="key-modal-title" onclose={()=>createOpen=false}><h3 id="key-modal-title">{t('modal.generateKey','Generate API Key')}</h3><div class="form-group"><label for="keyLabel">{t('label.keyLabel','Label (optional)')}</label><input id="keyLabel" maxlength="128" bind:value={label} placeholder="e.g. Production, Dev testing" /></div><div class="form-group"><label for="keyManual">{t('label.keyManual','Manual key (leave empty to auto-generate)')}</label><input id="keyManual" bind:value={manualKey} autocomplete="new-password" placeholder="rsk-... (auto-generated if empty)" style="font-family:var(--mono)" /></div><div class="modal-actions"><button class="btn" onclick={()=>createOpen=false}>{t('btn.cancel','Cancel')}</button><button class="btn btn-primary" disabled={busy} onclick={()=>void create()}>{t('btn.generate','Generate')}</button></div></Modal>
<Modal open={createdOpen} labelledby="key-created-title" onclose={()=>createdOpen=false}><h3 id="key-created-title">{t('modal.keyCreated','Key Created')}</h3><p style="font-size:13px;color:var(--text-dim);margin-bottom:12px">{t('keys.copyWarning','Copy this key now. It will not be shown again in full.')}</p><div style="display:flex;gap:8px;align-items:center"><input readonly value={createdKey} style="flex:1;padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:14px;font-family:var(--mono)" /><button class="btn btn-sm" onclick={()=>void copy()}>{t('btn.copy','Copy')}</button></div><div class="modal-actions" style="margin-top:16px"><button class="btn btn-primary" onclick={()=>createdOpen=false}>{t('btn.close','Close')}</button></div></Modal>
