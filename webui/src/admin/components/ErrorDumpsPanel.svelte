<script lang="ts">
  import { onMount } from 'svelte';
  import { api, download } from '../lib/api';
  import { t } from '../../shared/i18n.svelte';
  type Dump = { id?: string; dump_id?: string; timestamp?: string; model?: string; provider?: string; error_phase?: string; error?: string; body_hash?: string; [key: string]: unknown };
  let entries = $state<Dump[]>([]); let detail = $state<Dump | null>(null); let loading = $state(true); let busy = $state(false); let error = $state('');
  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const idFor = (entry: Dump) => String(entry.id ?? entry.dump_id ?? '');
  async function load(signal?: AbortSignal): Promise<void> { try { entries = (await api.get<{ entries?: Dump[] }>('/admin/api/error-dumps?limit=50&offset=0', signal)).entries ?? []; error = ''; } catch (cause) { error = message(cause); } finally { loading = false; } }
  async function inspect(entry: Dump): Promise<void> { busy = true; error = ''; try { detail = await api.get<Dump>(`/admin/api/error-dumps/${encodeURIComponent(idFor(entry))}`); } catch (cause) { error = message(cause); } finally { busy = false; } }
  async function body(entry: Dump): Promise<void> { busy = true; error = ''; try { const blob = await download(`/admin/api/error-dumps/${encodeURIComponent(idFor(entry))}/body`); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `error-dump-${idFor(entry)}.json`; link.click(); URL.revokeObjectURL(url); } catch (cause) { error = message(cause); } finally { busy = false; } }
  async function clear(): Promise<void> { if (!confirm(t('confirm.clearErrorDumps'))) return; busy = true; try { await api.del('/admin/api/error-dumps'); detail = null; await load(); } catch (cause) { error = message(cause); } finally { busy = false; } }
  onMount(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); });
</script>
<section class="dumps" aria-labelledby="dumps-title"><header><div><h2 id="dumps-title">{t('section.errorDumps')}</h2><p>{t('errorDumps.description')}</p></div><button disabled={busy || !entries.length} onclick={() => void clear()}>{t('btn.clearDumps')}</button></header>
  {#if error}<div class="alert" role="alert">{error}</div>{/if}
  {#if loading}<p>{t('loading.errorDumps')}</p>{:else if !entries.length}<p class="empty">{t('empty.errorDumps')}</p>{:else}<div class="scroll"><table><thead><tr><th>{t('col.time')}</th><th>{t('col.model')}</th><th>{t('col.provider')}</th><th>{t('col.phase')}</th><th>{t('col.actions')}</th></tr></thead><tbody>{#each entries as entry}<tr><td>{entry.timestamp ?? '-'}</td><td>{entry.model ?? '-'}</td><td>{entry.provider ?? '-'}</td><td>{entry.error_phase ?? '-'}</td><td><button disabled={busy} onclick={() => void inspect(entry)}>{t('btn.details')}</button> <button disabled={busy || !entry.body_hash} onclick={() => void body(entry)}>{t('btn.downloadBody')}</button></td></tr>{/each}</tbody></table></div>{/if}
  {#if detail}<pre aria-label={t('aria.errorDumpDetail')}>{JSON.stringify(detail, null, 2)}</pre>{/if}
</section>
<style>.dumps{display:grid;gap:12px;padding-top:16px;border-top:1px solid var(--border,#d0d5dd)}header{display:flex;justify-content:space-between;gap:10px}h2,p{margin:0}header p,.empty{color:var(--text-dim,#667085)}button{font:inherit;padding:7px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--border,#d0d5dd)}pre{white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto;padding:10px;background:var(--bg,#f7f8fa)}.alert{padding:10px;background:#fee4e2;color:#912018}</style>
