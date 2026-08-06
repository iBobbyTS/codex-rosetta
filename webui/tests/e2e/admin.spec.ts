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
    else if (path.endsWith('/profiling/status')) body = { enabled: false, remaining: 0 };
    else if (path.endsWith('/profiling/results')) body = { results: [] };
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
  await expect(page.getByRole('heading', { name: 'Profiling' })).toBeVisible();
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
