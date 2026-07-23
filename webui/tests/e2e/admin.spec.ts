import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route('**/admin/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: object = {};
    if (path.endsWith('/auth-check')) body = { requires_auth: false };
    else if (path.endsWith('/metrics')) body = { total_requests: 0, error_rate: 0, active_streams: 0, uptime_seconds: 1, by_target_provider: {} };
    else if (path.endsWith('/profiling/status')) body = { enabled: false, remaining: 0 };
    else if (path.endsWith('/profiling/results')) body = { results: [] };
    else if (path.endsWith('/config')) body = { providers: { upstream: {} }, models: { 'demo-model': { provider: 'upstream' } }, model_groups: { Main: { provider: 'upstream', type: 'llm', models: { 'demo-model': {} } } }, known_api_types: ['responses', 'chat', 'anthropic', 'google'], registered_shims: [], tool_profile_presets: [], model_presets: [], server: { request_body_limit_mb: 128 } };
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
  await expect(protocol.locator('option')).toHaveText([
    'OpenAI Responses',
    'OpenAI Chat Completions',
    'Anthropic Messages',
    'Google GenAI',
  ]);
  expect(await protocol.locator('option').evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value))).toEqual([
    'responses', 'chat', 'anthropic', 'google',
  ]);
  await expect(page.getByRole('dialog', { name: 'Add Provider' })).not.toContainText('open_responses');
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
