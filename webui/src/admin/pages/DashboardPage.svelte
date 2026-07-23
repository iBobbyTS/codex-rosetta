<script lang="ts">
  import { onMount } from 'svelte';
  import { api, download } from '../lib/api';
  import { createSerialPoll } from '../lib/polling';

  type Dict = Record<string, unknown>;
  type Metrics = {
    total_requests?: number;
    error_rate?: number;
    active_streams?: number;
    uptime_seconds?: number;
    by_target_provider?: Record<string, number>;
    persistence?: Dict;
    series?: Array<Record<string, number | string>>;
  };
  type ProfileStatus = { enabled?: boolean; remaining?: number };
  type ProfileResult = {
    timestamp?: string; model?: string; source?: string; target?: string;
    is_stream?: boolean; duration_ms?: number;
  };

  let metrics = $state<Metrics | null>(null);
  let profileStatus = $state<ProfileStatus>({});
  let results = $state<ProfileResult[]>([]);
  let count = $state(5);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let selectedProfile = $state<unknown>(null);
  let throughputCanvas = $state<HTMLCanvasElement>();
  let latencyCanvas = $state<HTMLCanvasElement>();

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const aborted = (value: unknown) => value instanceof DOMException && value.name === 'AbortError';
  const duration = (seconds = 0) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
  };

  function drawChart(canvas: HTMLCanvasElement, series: Array<Record<string, number | string>>, key: string): void {
    let context: CanvasRenderingContext2D | null;
    try { context = canvas.getContext('2d'); } catch { return; }
    if (!context) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    context.scale(dpr, dpr);
    const width = rect.width; const height = rect.height;
    context.clearRect(0, 0, width, height);
    const styles = getComputedStyle(document.documentElement);
    const gridColor = styles.getPropertyValue('--border').trim();
    const dimColor = styles.getPropertyValue('--text-dim').trim();
    const accentColor = styles.getPropertyValue('--accent').trim();
    const values = series.map((item) => Number(item[key]) || 0);
    const maxValue = Math.max(...values, 1);
    const padLeft = 40; const padRight = 8; const padTop = 8; const padBottom = 24;
    const chartWidth = width - padLeft - padRight; const chartHeight = height - padTop - padBottom;
    context.strokeStyle = gridColor; context.lineWidth = 0.5;
    for (let index = 0; index <= 4; index += 1) { const y = padTop + (chartHeight / 4) * index; context.beginPath(); context.moveTo(padLeft, y); context.lineTo(width - padRight, y); context.stroke(); }
    context.fillStyle = dimColor; context.font = '10px sans-serif'; context.textAlign = 'right';
    for (let index = 0; index <= 4; index += 1) { const y = padTop + (chartHeight / 4) * index; const value = maxValue * (1 - index / 4); context.fillText(value.toFixed(value >= 10 ? 0 : 1), padLeft - 6, y + 3); }
    context.textAlign = 'center'; context.fillText('-60s', padLeft, height - 4); context.fillText('-30s', padLeft + chartWidth / 2, height - 4); context.fillText('now', padLeft + chartWidth, height - 4);
    if (!values.length || Math.max(...values) === 0) { context.fillStyle = dimColor; context.font = '13px sans-serif'; context.fillText('No data', padLeft + chartWidth / 2, padTop + chartHeight / 2); return; }
    context.strokeStyle = accentColor; context.lineWidth = 1.5; context.beginPath();
    values.forEach((value, index) => { const x = padLeft + (index / Math.max(values.length - 1, 1)) * chartWidth; const y = padTop + chartHeight - (value / maxValue) * chartHeight; if (index === 0) context.moveTo(x, y); else context.lineTo(x, y); });
    context.stroke(); context.lineTo(padLeft + chartWidth, padTop + chartHeight); context.lineTo(padLeft, padTop + chartHeight); context.closePath(); context.fillStyle = accentColor.startsWith('#') ? `${accentColor}14` : 'rgba(99,102,241,0.08)'; context.fill();
  }

  $effect(() => {
    const series = metrics?.series ?? [];
    if (!throughputCanvas || !latencyCanvas) return;
    const frame = requestAnimationFrame(() => { drawChart(throughputCanvas!, series, 'count'); drawChart(latencyCanvas!, series, 'avg_ms'); });
    return () => cancelAnimationFrame(frame);
  });

  async function load(signal: AbortSignal): Promise<void> {
    try {
      const [nextMetrics, status, profileResults] = await Promise.all([
        api.get<Metrics>('/admin/api/metrics?seconds=60', signal),
        api.get<ProfileStatus>('/admin/api/profiling/status', signal),
        api.get<{ results?: ProfileResult[] }>('/admin/api/profiling/results', signal),
      ]);
      metrics = nextMetrics;
      profileStatus = status;
      results = profileResults.results ?? [];
      error = '';
    } catch (cause) {
      if (!aborted(cause)) error = message(cause);
    } finally {
      loading = false;
    }
  }

  const poll = createSerialPoll(load, 3_000);

  async function operation(action: () => Promise<unknown>, success: string): Promise<void> {
    busy = true; error = ''; notice = '';
    try {
      await action();
      notice = success;
      await poll.runNow();
    } catch (cause) { error = message(cause); }
    finally { busy = false; }
  }

  function toggleProfiling(): void {
    const requests = Math.max(1, Math.min(100, Math.trunc(count || 5)));
    void operation(
      () => profileStatus.enabled
        ? api.post('/admin/api/profiling/disable')
        : api.post('/admin/api/profiling/enable', { requests }),
      profileStatus.enabled ? 'Profiling disabled.' : 'Profiling enabled.',
    );
  }
  function clearProfiling(): void {
    if (!confirm('Clear all profiling results?')) return;
    void operation(() => api.del('/admin/api/profiling/results'), 'Profiling results cleared.');
  }
  async function inspectProfile(index: number): Promise<void> { busy = true; error = ''; try { selectedProfile = await api.get(`/admin/api/profiling/results/${index}`); } catch (cause) { error = message(cause); } finally { busy = false; } }
  async function downloadProfiles(): Promise<void> { busy = true; error = ''; try { const blob = await download('/admin/api/profiling/results/download'); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'profiling-results.zip'; link.click(); URL.revokeObjectURL(url); } catch (cause) { error = message(cause); } finally { busy = false; } }

  onMount(() => { poll.start(); return () => poll.stop(); });
</script>

<div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}{#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  {#if loading}<p aria-live="polite">Loading metrics...</p>
  {:else if metrics}
    <div class="stats-grid">
      <div class="stat-card"><div class="label">Total requests</div><div class="value blue">{metrics.total_requests??0}</div></div>
      <div class="stat-card"><div class="label">Error rate</div><div class="value" class:red={(metrics.error_rate??0)>0}>{((metrics.error_rate??0)*100).toFixed(1)}%</div></div>
      <div class="stat-card"><div class="label">Active streams</div><div class="value green">{metrics.active_streams??0}</div></div>
      <div class="stat-card"><div class="label">Uptime</div><div class="value">{duration(metrics.uptime_seconds)}</div></div>
    </div>
    <div class="chart-row"><div class="chart-box"><h3>Throughput (req/s)</h3><canvas bind:this={throughputCanvas} aria-label="Throughput chart"></canvas></div><div class="chart-box"><h3>Latency (ms)</h3><canvas bind:this={latencyCanvas} aria-label="Latency chart"></canvas></div></div>
    <div class="section"><div style="display:flex;align-items:center;gap:12px;margin-bottom:12px"><h2 style="margin:0">Per-Provider Breakdown</h2><button class="btn btn-sm" disabled={busy} onclick={()=>void operation(()=>api.post('/admin/api/metrics/rebuild'),'Metrics rebuilt.')}>Rebuild Counters</button></div>
      <div class="table-scroll"><table><thead><tr><th>Provider</th><th>Requests</th></tr></thead><tbody>
        {#each Object.entries(metrics.by_target_provider ?? {}).sort((a,b) => b[1]-a[1]) as [provider, requests]}
          <tr><td>{provider}</td><td>{requests}</td></tr>
        {:else}<tr><td colspan="2" class="empty">No request data.</td></tr>{/each}
      </tbody></table></div>
    </div>
  {/if}
  <div class="section"><h2 style="margin-bottom:12px">Profiling</h2><div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap"><span class="badge" class:badge-success={profileStatus.enabled} style="padding:4px 10px;border-radius:4px;font-size:12px;font-weight:600">{profileStatus.enabled?`${profileStatus.remaining??0} remaining`:'OFF'}</span><label for="profilingCount" style="font-size:13px">Requests:</label><input id="profilingCount" aria-label="Requests" type="number" min="1" max="100" bind:value={count} style="width:60px;padding:4px 6px" /><button class="btn btn-sm" disabled={busy} onclick={toggleProfiling}>{profileStatus.enabled?'Disable':'Enable'}</button><button class="btn btn-sm" disabled={busy||results.length===0} onclick={clearProfiling}>Clear</button><button class="btn btn-sm" disabled={busy||results.length===0} onclick={()=>void downloadProfiles()}>Download all</button></div>
    <p style="font-size:12px;color:var(--text-dim);margin:0 0 8px">Results are in-memory only and will be lost on restart. Download important results.</p>
    <div class="table-scroll"><table><thead><tr><th>Time</th><th>Model</th><th>Source → Target</th><th>Mode</th><th>Duration</th><th>Flamegraph</th></tr></thead><tbody>
      {#each results as result, index}
        <tr><td>{result.timestamp?new Date(result.timestamp).toLocaleString():'-'}</td><td>{result.model??'-'}</td><td>{result.source??'-'} → {result.target??'-'}</td><td>{result.is_stream?'stream':'sync'}</td><td>{typeof result.duration_ms==='number'?`${result.duration_ms.toFixed(0)} ms`:'-'}</td><td><button class="btn btn-sm" onclick={()=>void inspectProfile(index)}>View</button></td></tr>
      {:else}<tr><td colspan="6" class="empty">No profiling results. Enable profiling and send requests.</td></tr>{/each}
    </tbody></table></div>
    {#if selectedProfile}<pre aria-label="Profiling artifact">{JSON.stringify(selectedProfile, null, 2)}</pre>{/if}
  </div>
</div>
