import { expect, test } from '@playwright/test';
import path from 'node:path';
import { mkdir } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
const evidence = JSON.parse(readFileSync(new URL('./fixtures/add-links.json', import.meta.url), 'utf-8'));
const progress = JSON.parse(readFileSync(new URL('./fixtures/add-links-progress.json', import.meta.url), 'utf-8'));
import { installApiMock } from './support/api-mock';

// These controlled fixtures were exported by the isolated real API acceptance tests.
const task = evidence.response.task;
const screenshotDir = path.resolve('../.artifacts/v1.3');

test('four home filters and add input detail preserve real API rejection facts', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const mock = await installApiMock(page, { competitors: [], collectionBatches: evidence.batch_page, batchDetails: { [task.task_id]: { ...task, page_size: 10 } } });
  await mkdir(screenshotDir, { recursive: true });
  await page.setViewportSize({ width: 1680, height: 1100 });
  await page.goto('/');
  const homeResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/collection-batches');
  await page.getByRole('button', { name: '采集记录', exact: true }).click();
  const home = await (await homeResponse).json();
  expect(home.items[0].input_summary.business_rejected).toBe(2);
  expect(home.items[0].anomaly_products).toBe(0);
  await expect(page.getByLabel('记录类型', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('option', { name: '历史触发方式未知', exact: true })).toHaveCount(0);
  await expect(page.locator('.record-table tbody tr')).toContainText('部分新增成功');
  await expect(page.locator('.record-table tbody tr')).not.toContainText('业务拒绝');
  await expect(page.locator('.record-table tbody tr td').nth(4)).toHaveText('0');
  await page.getByRole('combobox', { name: '异常情况', exact: true }).selectOption('placeholder');
  await page.getByRole('combobox', { name: '触发方式', exact: true }).selectOption('add_links');
  await expect(page.getByRole('combobox', { name: '异常情况', exact: true })).toHaveValue('placeholder');
  await expect(page.getByRole('combobox', { name: '异常情况', exact: true }).locator('option[value="placeholder"]')).toHaveCount(1);
  await expect(page.getByRole('combobox', { name: '异常情况', exact: true }).locator('option[value="base_failed"]')).toHaveCount(1);
  await page.screenshot({ path: path.join(screenshotDir, 'collection-records-home.png'), fullPage: true });
  await page.getByRole('button', { name: '查看详情', exact: true }).click();
  await expect(page.getByRole('heading', { name: '批次详情', exact: true })).toBeVisible();
  await expect(page.locator('.record-table > tbody > tr')).toHaveCount(5);
  await expect(page.getByText('商品已存在', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('链接无效', { exact: true })).toBeVisible();
  await expect(page.locator('.record-metric-value').filter({ hasText: '业务拒绝' }).locator('strong')).toHaveText('2');
  await expect(page.locator('.record-table > tbody > tr > td:nth-child(2)').filter({ hasText: /商品已存在|链接无效/ })).toHaveCount(2);
  await expect(page.getByLabel('尝试类型', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: path.join(screenshotDir, 'add-links-detail.png'), fullPage: true });
  await page.getByRole('button', { name: /^展开 / }).first().click();
  await expect(page.getByText('本轮没有经营字段观测记录', { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshotDir, 'multi-link-partial-results.png'), fullPage: true });
  expect(errors).toEqual([]);
  await mock.expectNoUnexpectedApi();
});

test('clipboard and manual submission dedupe by Offer while preserving source lines', async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.addInitScript(() => {
    const state = window as Window & { testClipboardText: string };
    state.testClipboardText = '';
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { readText: async () => state.testClipboardText } });
  });
  let posted: { submission_id: string; group_id: number | null; inputs: { text: string; source_line: number }[] } | null = null;
  await page.route('**/api/competitors/add-batch', async route => {
    posted = route.request().postDataJSON();
    const taskId = posted!.submission_id;
    await route.fulfill({ status: 202, json: { accepted: true, task_id: taskId, task: { task_id: taskId, task_kind: 'add_links', trigger_kind: 'add_links', lifecycle_status: 'running', outcome_code: null, planned_products: posted!.inputs.length, items: [], input_summary: { total: posted!.inputs.length, processed: 0 } } } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '添加监控商品', exact: true }).click();
  const textarea = page.getByLabel('1688 商品链接');
  const original = 'https://detail.1688.com/offer/101.html';
  await textarea.fill(original);
  await page.evaluate(() => { (window as Window & { testClipboardText: string }).testClipboardText = 'https://detail.1688.com/offer/101.html?from=clip\nhttps://detail.1688.com/offer/102.html?from=clip\ninvalid'; });
  await page.getByRole('button', { name: '从剪贴板添加' }).click();
  await expect(textarea).toHaveValue(`${original}\nhttps://detail.1688.com/offer/102.html?from=clip\ninvalid`);
  await expect(page.getByRole('status').filter({ hasText: '已添加 2 条，过滤重复 1 条' })).toBeVisible();

  await page.evaluate(() => { (window as Window & { testClipboardText: string }).testClipboardText = 'https://detail.1688.com/offer/101.html?again=1\nhttps://detail.1688.com/offer/102.html?again=2'; });
  const beforeRepeatPaste = await textarea.inputValue();
  await page.getByRole('button', { name: '从剪贴板添加' }).click();
  await expect(textarea).toHaveValue(beforeRepeatPaste);
  await expect(page.getByRole('status').filter({ hasText: '链接已存在，无需重复添加' })).toBeVisible();

  await textarea.fill('https://detail.1688.com/offer/303.html?first=1\n\nhttps://detail.1688.com/offer/303.html?second=2\ninvalid\nhttps://detail.1688.com/offer/404.html');
  await page.getByRole('dialog').getByRole('button', { name: /添加.*监控商品/ }).click();
  await expect.poll(() => posted).not.toBeNull();
  expect(posted!.inputs).toEqual([
    { text: 'https://detail.1688.com/offer/303.html?first=1', source_line: 1 },
    { text: 'invalid', source_line: 4 },
    { text: 'https://detail.1688.com/offer/404.html', source_line: 5 },
  ]);
  expect(posted!.inputs).toHaveLength(3);
  await mock.expectNoUnexpectedApi();
});

test('100-item limit uses the final deduplicated submission list', async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  let posted: { inputs: { text: string; source_line: number }[] } | null = null;
  await page.route('**/api/competitors/add-batch', async route => {
    posted = route.request().postDataJSON();
    const taskId = crypto.randomUUID();
    await route.fulfill({ status: 202, json: { accepted: true, task_id: taskId, task: { task_id: taskId, task_kind: 'add_links', trigger_kind: 'add_links', lifecycle_status: 'running', outcome_code: null, planned_products: posted!.inputs.length, items: [], input_summary: { total: posted!.inputs.length, processed: 0 } } } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '添加监控商品', exact: true }).click();
  const textarea = page.getByLabel('1688 商品链接');
  const link = (id: number) => `https://detail.1688.com/offer/${id}.html`;
  await textarea.fill(Array.from({ length: 101 }, (_, index) => link(index + 1000)).join('\n'));
  await page.getByRole('dialog').getByRole('button', { name: /添加.*监控商品/ }).click();
  await expect(page.locator('.toast')).toContainText('最多提交100条');
  expect(posted).toBeNull();

  await textarea.fill([...Array.from({ length: 100 }, (_, index) => link(index + 1000)), link(1000) + '?duplicate=1'].join('\n'));
  await page.getByRole('dialog').getByRole('button', { name: /添加.*监控商品/ }).click();
  await expect.poll(() => posted).not.toBeNull();
  expect(posted!.inputs).toHaveLength(100);
  expect(posted!.inputs.at(-1)).toEqual({ text: link(1099), source_line: 100 });
  await mock.expectNoUnexpectedApi();
});

test('add live progress uses input units and the existing Dashboard controls', async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], batchStatus: progress });
  await page.setViewportSize({ width: 1680, height: 1100 });
  await page.goto('/');
  const overview = page.locator('.collection-overview');
  await expect(overview).toContainText('添加链接：已处理 5/20');
  await expect(overview).toContainText('当前输入：第 6 条');
  await expect(overview).toContainText('新增 3');
  await expect(overview).not.toContainText('完成 0 / 0');
  await expect(overview.getByRole('progressbar')).toHaveAttribute('aria-valuemax', '20');
  await page.screenshot({ path: path.join(screenshotDir, 'add-links-live-progress.png'), fullPage: true });
  await overview.getByRole('button', { name: '暂停采集' }).click();
  await expect(overview).toContainText('已暂停');
  await overview.getByRole('button', { name: '继续采集' }).click();
  await expect(overview).toContainText('添加链接：已处理 5/20');
  await mock.expectNoUnexpectedApi();
});

test('network uncertainty survives refresh and queries the same submission without another POST', async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  let posts = 0;
  let original: { submission_id: string; inputs: { text: string; source_line: number }[] } | undefined;
  await page.route('**/api/competitors/add-batch', async route => {
    posts++;
    original = route.request().postDataJSON();
    await route.fulfill({ status: 503, json: { code: 'admission_unknown', accepted: null } });
  });
  await page.route('**/api/competitors/add-batch/*', async route => {
    expect(route.request().method()).toBe('GET');
    expect(route.request().url()).toContain(original!.submission_id);
    await route.fulfill({ json: { accepted: true, task_id: original!.submission_id, task: { ...task, task_id: original!.submission_id } } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '添加监控商品', exact: true }).click();
  const originalText = [...evidence.submission.inputs.map((input: { text: string }) => input.text), 'https://detail.1688.com/offer/101.html?duplicate=1'].join('\n');
  await page.getByLabel('1688 商品链接').fill(originalText);
  await page.getByRole('dialog').getByRole('button', { name: /添加.*监控商品/ }).click();
  await expect(page.locator('.toast')).toContainText('受理结果尚未确认');
  expect(original!.inputs).toHaveLength(5);
  expect(original!.inputs.map(input => input.source_line)).toEqual([1, 2, 3, 4, 5]);
  const id = original!.submission_id;
  await page.reload();
  await page.getByRole('button', { name: '添加监控商品', exact: true }).click();
  await expect(page.getByLabel('1688 商品链接')).toHaveValue(originalText);
  await page.getByRole('dialog').getByRole('button', { name: /添加.*监控商品/ }).click();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('workbench.add-task.v1'))).toBe(id);
  expect(posts).toBe(1);
  await mock.expectNoUnexpectedApi();
});

for (const previousState of ['absent', 'accepted', 'unknown']) {
  test(`edited pending submission resolves old identity first: ${previousState}`, async ({ page }) => {
    const mock = await installApiMock(page, { competitors: [] });
    const oldId = '11111111-1111-4111-8111-111111111111';
    await page.addInitScript(id => localStorage.setItem('workbench.add-submission.v1', JSON.stringify({ submission_id: id, inputs: [{ text: 'old-link', source_line: 1 }], group_id: null })), oldId);
    const requests: string[] = [];
    await page.route('**/api/competitors/add-batch/*', async route => {
      requests.push('GET');
      await route.fulfill({ status: previousState === 'absent' ? 404 : previousState === 'unknown' ? 503 : 200, json: previousState === 'accepted' ? { accepted: true, task_id: oldId, task } : { code: 'admission_unknown', accepted: null } });
    });
    await page.route('**/api/competitors/add-batch', async route => {
      requests.push('POST');
      const body = route.request().postDataJSON();
      expect(body.submission_id).not.toBe(oldId);
      expect(body.inputs).toEqual([{ text: 'edited-link', source_line: 1 }]);
      await route.fulfill({ status: 202, json: { accepted: true, task_id: body.submission_id, task: { ...task, task_id: body.submission_id, lifecycle_status: 'running', items: [] } } });
    });
    await page.goto('/');
    await page.getByRole('button', { name: '添加监控商品', exact: true }).click();
    await page.getByLabel('1688 商品链接').fill('edited-link');
    await page.getByRole('dialog').getByRole('button', { name: /添加.*监控商品/ }).click();
    if (previousState === 'unknown') {
      await expect(page.locator('.toast')).toContainText('编辑内容尚未发送');
      expect(requests).toEqual(['GET']);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('workbench.add-submission.v1')!).submission_id)).toBe(oldId);
    } else {
      await expect(page.locator('.toast')).toContainText('添加任务已受理');
      expect(requests).toEqual(['GET', 'POST']);
    }
    await mock.expectNoUnexpectedApi();
  });
}

test('verification terminal refreshes product facts once and rest displays remaining time', async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], batchStatus: { ...progress, status: 'resting', resting_remaining_seconds: 17 } });
  let finished = false;
  let productReads = 0;
  page.on('request', request => { if (request.url().includes('/api/competitors?')) productReads++; });
  await page.route('**/api/competitors/collect-batch/status', route => route.fulfill({ json: finished ? { ...progress, lifecycle_status: 'terminal', status: 'verification_required', runner_active: false } : { ...progress, status: 'resting', resting_remaining_seconds: 17 } }));
  await page.goto('/');
  await expect(page.locator('.collection-overview')).toContainText('计划休息剩余');
  const before = productReads;
  finished = true;
  await expect(page.locator('.collection-overview')).toContainText('需要验证');
  await expect.poll(() => productReads).toBeGreaterThan(before);
  await mock.expectNoUnexpectedApi();
});
