<script lang="ts">
  import { onMount } from 'svelte';
  import ErrorDumpsPanel from '../components/ErrorDumpsPanel.svelte';
  import { api } from '../lib/api';
  import { createSerialPoll } from '../lib/polling';

  type Entry = {
    timestamp?: string; model?: string; source_provider?: string; target_provider?: string;
    target_provider_name?: string; is_stream?: boolean; api_key_label?: string;
    client_ip?: string; status_code?: number; duration_ms?: number; error_detail?: string;
  };
  const limit = 50;
  let entries = $state<Entry[]>([]);
  let total = $state(0);
  let offset = $state(0);
  let model = $state('');
  let provider = $state('');
  let status = $state('');
  let apiKeyLabel = $state('');
  let keyLabels = $state<string[]>([]);
  let expanded = $state(new Set<string>());
  let loading = $state(true);
  let clearing = $state(false);
  let error = $state('');

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const aborted = (value: unknown) => value instanceof DOMException && value.name === 'AbortError';
  function query(): string {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (model.trim()) params.set('model', model.trim());
    if (provider.trim()) params.set('provider', provider.trim());
    if (status) params.set('status', status);
    if (apiKeyLabel) params.set('api_key_label', apiKeyLabel);
    return `/admin/api/requests?${params}`;
  }
  async function load(signal: AbortSignal): Promise<void> {
    try {
      const data = await api.get<{ entries?: Entry[]; total?: number }>(query(), signal);
      entries = data.entries ?? [];
      total = data.total ?? 0;
      error = '';
    } catch (cause) { if (!aborted(cause)) error = message(cause); }
    finally { loading = false; }
  }
  const poll = createSerialPoll(load, 5_000);
  async function reload(reset = false): Promise<void> {
    if (reset) offset = 0;
    expanded = new Set();
    await poll.runNow();
  }
  function rowId(entry: Entry, index: number): string { return `${entry.timestamp ?? ''}:${entry.model ?? ''}:${index}`; }
  function toggle(id: string): void {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id); else next.add(id);
    expanded = next;
  }
  async function clearLogs(): Promise<void> {
    if (!confirm('Clear all request logs?')) return;
    clearing = true; error = '';
    try { await api.del('/admin/api/requests'); offset = 0; expanded = new Set(); await poll.runNow(); }
    catch (cause) { error = message(cause); }
    finally { clearing = false; }
  }
  function reset(): void { model = ''; provider = ''; status = ''; apiKeyLabel = ''; void reload(true); }
  onMount(() => {
    const controller = new AbortController();
    void api.get<{ labels?: string[] }>('/admin/api/requests/key-labels', controller.signal)
      .then((data) => { keyLabels = data.labels ?? []; })
      .catch((cause) => { if (!aborted(cause)) error = message(cause); });
    poll.start();
    return () => { controller.abort(); poll.stop(); };
  });
</script>

<div>
  <div class="filters">
    <input aria-label="Model" bind:value={model} placeholder="All Models" onkeydown={(event)=>{if(event.key==='Enter')void reload(true);}} />
    <input aria-label="Provider" bind:value={provider} placeholder="All Providers" onkeydown={(event)=>{if(event.key==='Enter')void reload(true);}} />
    <select aria-label="Status" bind:value={status} onchange={()=>void reload(true)}><option value="">All Status</option><option value="ok">OK (2xx/3xx)</option><option value="error">Error (4xx/5xx)</option></select>
    <select aria-label="API key" bind:value={apiKeyLabel} onchange={()=>void reload(true)}><option value="">All Keys</option>{#each keyLabels as label}<option value={label}>{label}</option>{/each}</select>
    <button class="btn btn-sm" onclick={reset}>Reset Filters</button><button class="btn btn-sm btn-danger" disabled={clearing} onclick={()=>void clearLogs()}>{clearing?'Clearing...':'Clear logs'}</button>
  </div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}
  {#if loading}<p aria-live="polite" style="color:var(--text-dim)">Loading request logs...</p>
  {:else}<div class="table-scroll"><table><thead><tr><th>Time</th><th>Model</th><th>Source → Target</th><th>Mode</th><th>API Key</th><th>Client IP</th><th>Status</th><th>Duration</th></tr></thead><tbody>
    {#each entries as entry, index}
      {@const id = rowId(entry, index)}
      <tr style="cursor:pointer" onclick={() => toggle(id)}>
        <td>{entry.timestamp ? new Date(entry.timestamp).toLocaleString() : '-'}</td><td><code>{entry.model ?? '-'}</code></td>
        <td>{entry.source_provider ?? '-'} → {entry.target_provider_name ?? entry.target_provider ?? '-'}</td><td>{entry.is_stream ? 'stream' : 'sync'}</td>
        <td>{entry.api_key_label ?? '-'}</td><td>{entry.client_ip ?? '-'}</td><td><span class="badge" class:badge-error={(entry.status_code??0)>=400} class:badge-success={(entry.status_code??0)>0&&(entry.status_code??0)<400}>{entry.status_code ?? '-'}</span></td>
        <td>{typeof entry.duration_ms === 'number' ? `${entry.duration_ms.toFixed(0)} ms` : '-'}</td>
      </tr>
      {#if expanded.has(id)}<tr><td colspan="8"><pre style="white-space:pre-wrap;word-break:break-word;max-height:220px;overflow:auto;margin:0;padding:10px;background:var(--bg)">{JSON.stringify(entry,null,2)}</pre></td></tr>{/if}
    {:else}<tr><td colspan="8" class="empty">No request logs match these filters.</td></tr>{/each}
  </tbody></table></div>{/if}
  <div class="pagination"><button class="btn btn-sm" disabled={offset===0} onclick={()=>{offset=Math.max(0,offset-limit);void reload();}}>Prev</button><span class="info">Page {Math.floor(offset/limit)+1} of {Math.max(1,Math.ceil(total/limit))} · {total} entries</span><button class="btn btn-sm" disabled={offset+limit>=total} onclick={()=>{offset+=limit;void reload();}}>Next</button></div>
  <ErrorDumpsPanel />
</div>
