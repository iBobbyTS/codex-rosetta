import { expect, test, type Page } from '@playwright/test';

async function chooseDropdown(page: Page, label: string, value: string): Promise<void> {
  await page.getByLabel(label, { exact: true }).click();
  await page.locator(`.suu-dropdown__option[data-value="${value}"]`).click();
}

test.beforeEach(async ({ page }) => {
  const upstream: Record<string, unknown> = { provider: 'moonshot', base_url: 'https://api.moonshot.ai/v1', api_type: 'responses' };
  const config = { providers: { upstream }, models: { 'demo-model': { provider: 'upstream' } }, model_groups: { Main: { provider: 'upstream', type: 'llm', models: { 'demo-model': {} } } }, known_api_types: ['responses', 'chat', 'anthropic', 'google'], registered_shims: [], tool_profile_presets: [], model_presets: [], server: { request_body_limit_mb: 128 } };
  await page.route('**/admin/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = {};
    if (path.endsWith('/auth-check')) body = { requires_auth: false };
    else if (path.endsWith('/metrics')) body = { total_requests: 0, error_rate: 0, active_streams: 0, uptime_seconds: 1, by_target_provider: {} };
    else if (path.endsWith('/config')) body = config;
    else if (path.endsWith('/config/providers/upstream') && route.request().method() === 'PUT') {
      Object.assign(upstream, route.request().postDataJSON());
      body = { ok: true };
    }
    else if (path === '/admin/api/test') body = { task_id: 'browser-task' };
    else if (path.endsWith('/admin/api/test/browser-task/poll')) body = { status: 'done', status_code: 200, body: { output_text: '<img src="https://audit.invalid/probe" onerror="fetch(\'/stolen\')">', usage: { input_tokens: '<script>bad()</script>', output_tokens: 7, total_tokens: 9007199254740992 } } };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
});

test('renders hostile model-test output and usage as inert text', async ({ page }) => {
  const unexpected: string[] = [];
  page.on('request', (request) => { if (request.url().includes('audit.invalid') || request.url().endsWith('/stolen')) unexpected.push(request.url()); });
  await page.goto('/admin/admin.html');
  await page.getByRole('link', { name: 'Models' }).click();
  await expect(page.getByRole('heading', { name: 'Model Routing' })).toBeVisible();
  await page.getByRole('button', { name: 'Test', exact: true }).click();
  await expect(page.getByText('<img src="https://audit.invalid/probe" onerror="fetch(\'/stolen\')">')).toBeVisible();
  await expect(page.locator('img[src*="audit.invalid"]')).toHaveCount(0);
  await expect(page.getByText('output_tokens:', { exact: true })).toBeVisible();
  await expect(page.getByText('input_tokens:', { exact: true })).toHaveCount(0);
  expect(unexpected).toEqual([]);
});

test('renders the shared Admin shell without viewport overflow', async ({ page }) => {
  await page.goto('/admin/admin.html');
  await expect(page.getByRole('heading', { name: 'Providers' })).toBeVisible();
  await expect(page.getByText('gateway admin')).toBeVisible();
  await page.getByRole('link', { name: 'Dashboard' }).click();
  await expect(page.getByText('Total requests')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test('renders configurable API types with user-facing protocol names', async ({ page }) => {
  await page.goto('/admin/admin.html');
  await page.getByRole('button', { name: '+ Add Provider' }).click();
  const protocol = page.getByLabel('Protocol');
  await protocol.click();
  await expect(page.getByRole('option')).toHaveText([
    'OpenAI Responses',
    'OpenAI Chat Completions',
    'Anthropic Messages',
    'Google GenAI',
  ]);
  expect(await page.getByRole('option').evaluateAll((options) => options.map((option) => option.getAttribute('data-value')))).toEqual([
    'responses', 'chat', 'anthropic', 'google',
  ]);
  await expect(page.getByRole('dialog', { name: 'Add Provider' })).not.toContainText('open_responses');
});

test('keeps the provider dialog body scrollable when its form exceeds the modal height', async ({ page }) => {
  await page.setViewportSize({ width: 658, height: 520 });
  await page.goto('/admin/admin.html');
  await page.getByRole('button', { name: '+ Add Provider' }).click();

  const body = page.getByRole('dialog', { name: 'Add Provider' }).locator('.modal-body');
  const metrics = await body.evaluate((element) => ({
    overflowY: getComputedStyle(element).overflowY,
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));

  expect(metrics.overflowY).toBe('auto');
  expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight);
  await body.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  expect(await body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
});

test('loads provider logos only from bundled assets', async ({ page }) => {
  const externalLogos: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('cdn.jsdelivr.net')) externalLogos.push(request.url());
  });
  await page.goto('/admin/admin.html');
  const providerLogo = page.locator('.provider-card .provider-logo');
  await expect(providerLogo).toHaveAttribute('src', /provider-logos\/moonshot\.svg$/);
  await page.getByRole('button', { name: 'Settings' }).click();
  await chooseDropdown(page, 'Theme', 'dark');
  await expect(providerLogo).toHaveCSS('filter', 'invert(1)');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '+ Add Provider' }).click();
  await chooseDropdown(page, 'Provider', 'opencode_go');
  const opencodeLogo = page.locator('.type-logo-preview');
  await expect(opencodeLogo).toHaveAttribute('src', /provider-logos\/opencode\.png$/);
  await expect(opencodeLogo).toHaveCSS('filter', 'none');
  expect(externalLogos).toEqual([]);
});

test('derives the provider child option only from persisted provider and URL', async ({ page }) => {
  await page.goto('/admin/admin.html');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Provider', { exact: true })).toHaveAttribute('data-value', 'moonshot');
  await expect(page.getByLabel('Provider variant')).toHaveAttribute('data-value', 'international');
  await expect(page.getByLabel('Protocol')).toHaveAttribute('data-value', 'responses');
});

test('keeps a changed provider after save and config reload', async ({ page }) => {
  await page.goto('/admin/admin.html');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await chooseDropdown(page, 'Provider', 'deepseek');
  await page.getByRole('dialog', { name: 'Edit Provider' }).getByRole('button', { name: 'Save' }).click();
  await expect(page.getByRole('status')).toHaveText("Provider 'upstream' saved");
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Provider', { exact: true })).toHaveAttribute('data-value', 'deepseek');
});

test('keeps model mapping actions inside the model-group dialog', async ({ page }) => {
  await page.setViewportSize({ width: 658, height: 850 });
  await page.goto('/admin/admin.html');
  await page.getByRole('link', { name: 'Models' }).click();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();

  const dialog = page.getByRole('dialog', { name: 'Edit Model Group' });
  const row = dialog.locator('.model-group-row');
  const remove = dialog.getByRole('button', { name: 'Remove' });
  await expect(remove).toBeVisible();
  const [rowBox, removeBox] = await Promise.all([row.boundingBox(), remove.boundingBox()]);
  expect(rowBox).not.toBeNull();
  expect(removeBox).not.toBeNull();
  expect(removeBox!.x + removeBox!.width).toBeLessThanOrEqual(rowBox!.x + rowBox!.width);
});

test('wraps collapsed and expanded model-group cooldown detail inside the status column', async ({ page }) => {
  const cooldownDetail = '错误已脱敏请等待恢复后重试。'.repeat(7);
  expect(cooldownDetail.length).toBeLessThanOrEqual(120);
  const config = {
    providers: { upstream: { provider: 'moonshot', base_url: 'https://api.moonshot.ai/v1', api_type: 'responses', auto_rotate_credentials: true } },
    models: { 'demo-model': { provider: 'upstream' } },
    model_groups: { Main: { providers: [{ name: 'upstream', auto_rotate_credentials: true, current: true, enabled: true, routing_enabled: true, status: 'cooling', error: null, cooldown_detail: cooldownDetail, cooldown_recovery_at_ms: Date.now() + 60_000, availability: null, rate_multiplier: 1 }], type: 'llm', models: { 'demo-model': {} } } },
    known_api_types: ['responses', 'chat', 'anthropic', 'google'], registered_shims: [], tool_profile_presets: [], model_presets: [], server: { request_body_limit_mb: 128 },
  };
  await page.route('**/admin/api/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }));

  for (const viewport of [{ width: 1280, height: 900 }, { width: 658, height: 850 }]) {
    await page.setViewportSize(viewport);
    await page.goto('/admin/admin.html');
    await page.getByRole('link', { name: 'Models' }).click();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();

    const dialog = page.getByRole('dialog', { name: 'Edit Model Group' });
    const providerTable = dialog.locator('.model-group-provider-table table');
    await expect(providerTable).toHaveCSS('table-layout', 'auto');
    await expect(dialog.locator('.model-group-provider-heading')).not.toHaveAttribute('style');
    const status = dialog.locator('.model-group-provider-status');
    const detail = status.locator('.model-group-provider-detail');
    const collapsed = await detail.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        whiteSpace: style.whiteSpace,
        lineHeight: Number.parseFloat(style.lineHeight),
        height: element.getBoundingClientRect().height,
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      };
    });
    expect(collapsed.whiteSpace).toBe('normal');
    expect(collapsed.height).toBeGreaterThan(collapsed.lineHeight);
    expect(collapsed.height).toBeLessThanOrEqual(collapsed.lineHeight * 2.2);
    expect(collapsed.scrollWidth).toBeLessThanOrEqual(collapsed.clientWidth + 1);

    await dialog.getByRole('button', { name: 'Expand cooldown detail for upstream' }).click();
    const expanded = await status.evaluate((cell) => {
      const detailElement = cell.querySelector('.model-group-provider-detail') as HTMLElement;
      const cellBox = cell.getBoundingClientRect();
      const detailBox = detailElement.getBoundingClientRect();
      return {
        whiteSpace: getComputedStyle(detailElement).whiteSpace,
        cellRight: cellBox.right,
        detailRight: detailBox.right,
        clientWidth: detailElement.clientWidth,
        scrollWidth: detailElement.scrollWidth,
      };
    });
    expect(expanded.whiteSpace).toBe('normal');
    expect(expanded.scrollWidth).toBeLessThanOrEqual(expanded.clientWidth + 1);
    expect(expanded.detailRight).toBeLessThanOrEqual(expanded.cellRight + 1);
  }
});

test('shows runtime columns for a model-group provider excluded from routing', async ({ page }) => {
  const config = {
    providers: { upstream: { provider: 'moonshot', base_url: 'https://api.moonshot.ai/v1', api_type: 'responses', auto_rotate_credentials: true } },
    models: { 'demo-model': { provider: 'upstream' } },
    model_groups: { Main: { providers: [{ name: 'upstream', auto_rotate_credentials: true, current: false, enabled: true, routing_enabled: false, status: 'available', error: null, availability: { kind: 'percentage', value: 99, band: 'green' }, rate_multiplier: 0.5 }], type: 'llm', models: { 'demo-model': {} } } },
    known_api_types: ['responses', 'chat', 'anthropic', 'google'], registered_shims: [], tool_profile_presets: [], model_presets: [], server: { request_body_limit_mb: 128 },
  };
  await page.route('**/admin/api/config', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(config) }));
  await page.goto('/admin/admin.html');
  await page.getByRole('link', { name: 'Models' }).click();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();

  const dialog = page.getByRole('dialog', { name: 'Edit Model Group' });
  const row = dialog.getByRole('button', { name: 'Drag provider upstream' }).locator('xpath=ancestor::tr');
  await expect(row.getByRole('checkbox', { name: 'Allow upstream in model group routing' })).not.toBeChecked();
  await expect(row.locator('.model-group-provider-status')).toHaveText('Available');
  await expect(row.locator('.model-group-provider-availability')).toHaveText('99%');
  await expect(row.locator('.model-group-provider-multiplier')).toHaveText('0.5x');
  expect(await dialog.locator('.model-group-provider-table').evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
});
