<script lang="ts">
  import { onMount } from 'svelte';
import { api } from '../lib/api';
  import { createSerialPoll } from '../lib/polling';
  import { t } from '../../shared/i18n.svelte';

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

  let metrics = $state<Metrics | null>(null);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let throughputCanvas = $state<HTMLCanvasElement>();
  let latencyCanvas = $state<HTMLCanvasElement>();

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  const aborted = (value: unknown) => value instanceof DOMException && value.name === 'AbortError';
  const duration = (seconds = 0) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours
      ? t('format.durationHoursMinutes', { hours, minutes })
      : t('format.durationMinutes', { minutes });
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
    context.textAlign = 'center'; context.fillText(t('chart.secondsAgo', { seconds: 60 }), padLeft, height - 4); context.fillText(t('chart.secondsAgo', { seconds: 30 }), padLeft + chartWidth / 2, height - 4); context.fillText(t('chart.now'), padLeft + chartWidth, height - 4);
    if (!values.length || Math.max(...values) === 0) { context.fillStyle = dimColor; context.font = '13px sans-serif'; context.fillText(t('chart.noData'), padLeft + chartWidth / 2, padTop + chartHeight / 2); return; }
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
      const nextMetrics = await api.get<Metrics>('/admin/api/metrics?seconds=60', signal);
      metrics = nextMetrics;
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


  onMount(() => { poll.start(); return () => poll.stop(); });
</script>

<div>
  {#if error}<div class="toast error show" role="alert">{error}</div>{/if}{#if notice}<div class="toast show" role="status">{notice}</div>{/if}
  {#if loading}<p aria-live="polite">{t('loading.metrics')}</p>
  {:else if metrics}
    <div class="stats-grid">
      <div class="stat-card"><div class="label">{t('metric.totalRequests')}</div><div class="value blue">{metrics.total_requests??0}</div></div>
      <div class="stat-card"><div class="label">{t('metric.errorRate')}</div><div class="value" class:red={(metrics.error_rate??0)>0}>{((metrics.error_rate??0)*100).toFixed(1)}%</div></div>
      <div class="stat-card"><div class="label">{t('metric.activeStreams')}</div><div class="value green">{metrics.active_streams??0}</div></div>
      <div class="stat-card"><div class="label">{t('metric.uptime')}</div><div class="value">{duration(metrics.uptime_seconds)}</div></div>
    </div>
    <div class="chart-row"><div class="chart-box"><h3>{t('chart.throughput')}</h3><canvas bind:this={throughputCanvas} aria-label={t('aria.throughputChart')}></canvas></div><div class="chart-box"><h3>{t('chart.latency')}</h3><canvas bind:this={latencyCanvas} aria-label={t('aria.latencyChart')}></canvas></div></div>
    <div class="section"><div style="display:flex;align-items:center;gap:12px;margin-bottom:12px"><h2 style="margin:0">{t('section.breakdown')}</h2><button class="btn btn-sm" disabled={busy} onclick={()=>void operation(()=>api.post('/admin/api/metrics/rebuild'),t('toast.metricsRebuildComplete'))}>{t('metrics.rebuild')}</button></div>
      <div class="table-scroll"><table><thead><tr><th>{t('col.provider')}</th><th>{t('col.requests')}</th></tr></thead><tbody>
        {#each Object.entries(metrics.by_target_provider ?? {}).sort((a,b) => b[1]-a[1]) as [provider, requests]}
          <tr><td>{provider}</td><td>{requests}</td></tr>
        {:else}<tr><td colspan="2" class="empty">{t('empty.requestData')}</td></tr>{/each}
      </tbody></table></div>
    </div>
  {/if}
</div>
