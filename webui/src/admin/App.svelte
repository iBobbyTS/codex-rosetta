<script lang="ts">
  import { onMount } from 'svelte';
  import { AUTH_EXPIRED_EVENT, RESTART_REQUIRED_EVENT, ApiError, api, getAdminToken, request, setAdminToken } from './lib/api';
  import { routeFromPath, routes, type RouteId } from './lib/routes';
  import { language, setLanguage, t } from '../shared/i18n.svelte';
  import { Dropdown, type DropdownValue } from '@ibobbyts/svelte-ui-utils/dropdown';
  import DashboardPage from './pages/DashboardPage.svelte';
  import GatewayLogsPage from './pages/GatewayLogsPage.svelte';
  import KeysPage from './pages/KeysPage.svelte';
  import ModelsPage from './pages/ModelsPage.svelte';
  import NetworkSearchPage from './pages/NetworkSearchPage.svelte';
  import ProvidersPage from './pages/ProvidersPage.svelte';
  import RequestLogsPage from './pages/RequestLogsPage.svelte';
  import ToolsPage from './pages/ToolsPage.svelte';

  let route = $state<RouteId>(routeFromPath(location.pathname));
  let checking = $state(true);
  let authenticated = $state(false);
  let password = $state('');
  let busy = $state(false);
  let error = $state('');
  let restartRequired = $state(false);
  let theme = $state(localStorage.getItem('codex-rosetta-theme') ?? 'light');
  let settingsOpen = $state(false);
  let configPath = $state('');
  let version = $state('');
  let systemClock = $state('');

  const message = (value: unknown) => value instanceof Error ? value.message : String(value);
  function navigate(id: RouteId): void { const target = routes.find((item) => item.id === id)!; history.pushState({}, '', target.path); route = id; }
  function logout(): void { setAdminToken(''); authenticated = false; }
  function setTheme(value: string): void {
    theme = value === 'dark' ? 'dark' : 'light';
    localStorage.setItem('codex-rosetta-theme', theme);
    const colors = theme === 'dark'
      ? { '--bg':'#0f1117','--bg-card':'#1a1d27','--bg-hover':'#242838','--border':'#2d3148','--text':'#e4e7ef','--text-dim':'#8b90a5','--accent':'#6366f1','--accent-hover':'#818cf8','--green':'#22c55e','--red':'#ef4444','--orange':'#f59e0b','--blue':'#3b82f6','--provider-logo-filter':'invert(1)' }
      : { '--bg':'#ffffff','--bg-card':'#f6f8fa','--bg-hover':'#eef1f5','--border':'#d1d9e0','--text':'#1f2328','--text-dim':'#656d76','--accent':'#0969da','--accent-hover':'#0550ae','--green':'#1a7f37','--red':'#cf222e','--orange':'#bf8700','--blue':'#0969da','--provider-logo-filter':'none' };
    for (const [key, color] of Object.entries(colors)) document.documentElement.style.setProperty(key, color);
  }
  const themeOptions = [{ value: 'light', label: t('theme.light') }, { value: 'dark', label: t('theme.dark') }];
  const languageOptions = [{ value: 'en', label: t('language.english') }, { value: 'zh', label: t('language.chinese') }];

  async function loadShellConfig(): Promise<void> {
    try {
      const config = await api.get<{ config_path?: string; version?: string }>('/admin/api/config');
      configPath = config.config_path ?? '';
      version = config.version ?? '';
    } catch { /* Page loaders surface actionable request errors. */ }
  }

  async function authenticate(): Promise<void> {
    busy = true; error = '';
    try {
      const result = await request<{ token: string }>('/admin/api/login', { method: 'POST', body: { password }, auth: false });
      setAdminToken(result.token); password = ''; authenticated = true;
    } catch (cause) { error = message(cause); }
    finally { busy = false; }
  }

  async function checkAuth(): Promise<void> {
    checking = true; error = '';
    try {
      const state = await request<{ requires_auth: boolean }>('/admin/api/auth-check', { auth: false });
      if (!state.requires_auth) authenticated = true;
      else if (getAdminToken()) {
        try { await api.get('/admin/api/config'); authenticated = true; }
        catch (cause) { if (!(cause instanceof ApiError && [401, 403].includes(cause.status))) throw cause; }
      }
    } catch (cause) { error = message(cause); }
    finally {
      checking = false;
      if (authenticated) void loadShellConfig();
    }
  }

  onMount(() => {
    const pop = () => route = routeFromPath(location.pathname);
    const expired = () => { authenticated = false; password = ''; busy = false; };
    const restart = () => { restartRequired = true; };
    const closeSettings = (event: KeyboardEvent) => { if (event.key === 'Escape') settingsOpen = false; };
    const updateClock = () => { systemClock = new Date().toLocaleTimeString(); };
    addEventListener('popstate', pop);
    addEventListener(AUTH_EXPIRED_EVENT, expired);
    addEventListener(RESTART_REQUIRED_EVENT, restart);
    addEventListener('keydown', closeSettings);
    setTheme(theme);
    updateClock();
    const clockTimer = window.setInterval(updateClock, 1000);
    void checkAuth();
    return () => {
      removeEventListener('popstate', pop);
      removeEventListener(AUTH_EXPIRED_EVENT, expired);
      removeEventListener(RESTART_REQUIRED_EVENT, restart);
      removeEventListener('keydown', closeSettings);
      clearInterval(clockTimer);
    };
  });
</script>

{#if checking}
  <div aria-live="polite"></div>
{:else if !authenticated}
  <div class="login-overlay">
    <div class="login-box">
      <h2>{t('product.name')} <span style="font-weight:400;color:var(--text-dim)">{t('product.gateway')}</span></h2>
      <div class="login-subtitle">{t('login.subtitle')}</div>
      <form autocomplete="on" onsubmit={(event) => { event.preventDefault(); void authenticate(); }}>
        <input type="text" name="username" autocomplete="username" value="admin" style="display:none" aria-hidden="true" />
        <input id="password" type="password" name="password" bind:value={password} autocomplete="current-password" placeholder={t('label.password')} />
        <div class="login-error" role="alert">{error}</div>
        <button type="submit" disabled={busy || !password}>{t('login.btn')}</button>
      </form>
    </div>
  </div>
{:else}
  <div class="header">
    <div><h1>{t('product.name')} <span>{t('product.gatewayAdmin')}</span></h1></div>
    <div class="header-right">
      <span style="font-size:12px;color:var(--text-dim);margin-right:8px"><span style="margin-right:4px">{t('label.systemTime')}</span><span style="font-family:var(--mono)">{systemClock}</span></span>
      <button class="btn btn-sm" onclick={() => settingsOpen = !settingsOpen} title={t('modal.settings')} aria-label={t('modal.settings')}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      </button>
      <button class="btn btn-sm" onclick={logout}>{t('btn.logout')}</button>
    </div>
  </div>
  <nav class="admin-nav" aria-label={t('aria.adminPages')}>
    {#each routes as item}<a href={item.path} class="nav-link" class:active={route === item.id} onclick={(event) => { event.preventDefault(); navigate(item.id); }}>{t(item.labelKey)}</a>{/each}
    <div style="flex:1"></div><div class="config-path">{configPath}</div>
  </nav>
  <main class="content">
    {#if route === 'providers'}<ProvidersPage />
    {:else if route === 'models'}<ModelsPage />
    {:else if route === 'keys'}<KeysPage />
    {:else if route === 'tools'}<ToolsPage />
    {:else if route === 'network-search'}<NetworkSearchPage />
    {:else if route === 'dashboard'}<DashboardPage />
    {:else if route === 'logs'}<RequestLogsPage />
    {:else}<GatewayLogsPage />{/if}
  </main>
  <div class="settings-popup" class:open={settingsOpen} role="presentation" onclick={(event) => { if (event.target === event.currentTarget) settingsOpen = false; }}>
    <div class="settings-popup-panel" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <h3 id="settings-title">{t('modal.settings')}</h3>
      <div class="settings-popup-item"><label for="settingsThemeSelect">{t('label.theme')}</label><Dropdown id="settingsThemeSelect" value={theme} options={themeOptions} onChange={(value: DropdownValue) => setTheme(String(value))} /></div>
      <div class="settings-popup-item"><label for="settingsLangSelect">{t('label.language')}</label><Dropdown id="settingsLangSelect" value={language.value} options={languageOptions} onChange={(value: DropdownValue) => setLanguage(String(value) === 'zh' ? 'zh' : 'en')} /></div>
      <div class="settings-divider"></div>
      <div style="text-align:center;padding:4px 0 2px">
        <div style="font-size:15px;font-weight:600;margin-bottom:2px">{t('product.name')}</div>
        <div style="font-size:11px;color:var(--text-dim);margin-bottom:8px">{version ? `v${version}` : ''}</div>
        <div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap"><a href="https://github.com/iBobbyTS/codex-rosetta" target="_blank" rel="noopener" class="about-link">{t('about.github')}</a><a href="https://github.com/iBobbyTS/codex-rosetta/tree/master/docs" target="_blank" rel="noopener" class="about-link">{t('about.docs')}</a></div>
      </div>
    </div>
  </div>
  {#if restartRequired}<div class="restart-notice" role="alertdialog" aria-live="assertive"><div>{t('notice.codexRestart')}</div><button class="btn btn-primary btn-sm" onclick={() => restartRequired = false}>{t('btn.confirm')}</button></div>{/if}
{/if}
