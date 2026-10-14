import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { mkdir, writeFile } from "node:fs/promises";

import { competitors23 } from "./fixtures/competitors";
import { installApiMock } from "./support/api-mock";

const acceptanceScreenshot = (testInfo: import("@playwright/test").TestInfo, name: string) => process.env.PW_V1_2_QA_SCREENSHOT_DIR
  ? path.join(process.env.PW_V1_2_QA_SCREENSHOT_DIR, name)
  : testInfo.outputPath(name);
const metricKeys = ["listing_time", "monthly_deal", "monthly_dropship", "annual_units", "annual_orders", "review_count", "positive_rate", "pickup_rate"];
const observed = metricKeys.map(() => "observed");
const unavailable = metricKeys.map(() => "source_unavailable");
const recovered = metricKeys.map((_, index) => index < 6 ? "observed" : "placeholder");
const attempt = (id: number, number: number, kind: string, statuses: string[], status = "success") => ({
  id, attempt_number: number, attempt_kind: kind,
  started_at: `2026-10-14T00:0${number}:00Z`, finished_at: `2026-10-14T00:0${number}:06Z`, duration_seconds: 6,
  navigation_claimed_at: `2026-10-14T00:0${number}:00Z`, navigation_confirmed_at: `2026-10-14T00:0${number}:01Z`,
  status, operating_metrics_status: statuses.includes("source_unavailable") ? "failed" : statuses.includes("placeholder") ? "partial" : "success",
  error_type: status === "failed" ? "verification_required" : null, error_message: status === "failed" ? "页面要求验证" : null,
  observations: metricKeys.slice(0, statuses.length).map((metric_key, index) => ({ metric_key, status: statuses[index], raw_value: statuses[index] === "observed" ? "1" : statuses[index] === "placeholder" ? "-" : null, reason: statuses[index] === "source_unavailable" ? "助手标题不存在或不唯一" : null, source: "assistant", observed_at: "2026-10-14T00:01:06Z" })),
});
const item = (position: number, title: string | null, final_result: string, attempts: ReturnType<typeof attempt>[], overrides = {}) => ({
  position, competitor_id: position + 1, title, offer_id: `12345000${position}`, shop_name: "隔离测试店铺", main_image_url: null,
  execution_status: "completed", final_result, base_result: "success", operating_metrics_status: "success",
  attempts_started: attempts.length, page_visits: attempts.length, page_visits_unknown: 0, verification_resume_visits: 0,
  retry_visits: final_result === "retry_success" ? 1 : 0, technical_exception_count: 0, cancelled_retry_count: 0,
  protection_reason: null, stop_reason: null, identity_removed: false, has_anomaly: false, had_anomaly: false,
  started_at: attempts[0]?.started_at ?? null, finished_at: attempts.at(-1)?.finished_at ?? null,
  duration_seconds: attempts.length ? (attempts.length - 1) * 60 + 6 : null, attempts, ...overrides,
});
const batchItems = [
  item(0, "完整成功商品", "first_pass_success", [attempt(1, 1, "first_pass", observed)]),
  item(1, "正常页面占位商品", "first_pass_success", [attempt(2, 1, "first_pass", ["observed", "placeholder", ...observed.slice(2)])], { operating_metrics_status: "partial" }),
  item(2, "来源读取技术异常商品", "final_failed", [attempt(3, 1, "first_pass", unavailable)], { operating_metrics_status: "failed", technical_exception_count: 1, has_anomaly: true, had_anomaly: true, duration_seconds: null, finished_at: null }),
  item(3, "补采后恢复商品", "retry_success", [attempt(4, 1, "first_pass", unavailable), attempt(5, 2, "operating_metrics_retry", recovered)], { operating_metrics_status: "partial", technical_exception_count: 1, had_anomaly: true }),
  item(4, "验证恢复商品", "verification_resume_success", [attempt(6, 1, "first_pass", [], "failed"), attempt(7, 2, "verification_resume", observed)], { verification_resume_visits: 1, had_anomaly: true }),
  item(5, null, "not_executed", [], { competitor_id: null, identity_removed: true, execution_status: "not_executed", base_result: null, operating_metrics_status: null }),
];
const batch = {
  batch_id: 1, task_id: "task-a", trigger_kind: "manual_selected", created_at: "2026-10-14T00:00:00Z",
  started_at: "2026-10-14T00:00:00Z", finished_at: "2026-10-14T00:05:10Z", duration_seconds: 310,
  lifecycle_status: "terminal", outcome_code: "partial_success", planned_products: 6,
  counts: { first_pass_success: 2, verification_resume_success: 1, retry_success: 1, final_failed: 1, not_executed: 1 },
  page_visits: 7, page_visits_unknown: 0, retry_visits: 1, verification_resume_visits: 1, circuit_breaker_cancelled: 0,
  technical_exception_products: 1, base_failed_products: 0, completed: 5, remaining: 1, attempts_started: 7,
};
const detail = { ...batch, summary: { ...batch }, settings_snapshot: { operating_metrics_retry_max: 1 }, protection_reason: null, protection_details: null, circuit_breaker_streak: 0, items: batchItems, total: 6, page: 1, page_size: 10 };
const batchPage = { items: [batch], total: 1, page: 1, page_size: 20 };
const openRecords = async (page: Page) => {
  await page.goto("/");
  await page.getByRole("button", { name: "采集记录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "采集记录", exact: true })).toBeVisible();
};

test("record type round trip retains compatible payload without runtime errors", async ({ page }, testInfo) => {
  const evidence: { errors: string[]; console: string[]; network: { event: string; url: string; status?: number }[] } = { errors: [], console: [], network: [] };
  page.on("pageerror", error => evidence.errors.push(error.stack || error.message));
  page.on("console", message => { if (message.type() === "error") evidence.console.push(message.text()); });
  page.on("request", request => { if (/api\/collection-(batches|runs)/.test(request.url())) evidence.network.push({ event: "request", url: request.url() }); });
  page.on("response", response => { if (/api\/collection-(batches|runs)/.test(response.url())) evidence.network.push({ event: "response", url: response.url(), status: response.status() }); });
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage, collectionRuns: { items: [{ id: 51, competitor_id: 1, title: "历史独立记录", offer_id: "123450051", shop_name: "隔离店铺", started_at: "2026-10-14T00:00:00Z", finished_at: "2026-10-14T00:00:04Z", status: "success", operating_metrics_status: "success", has_anomaly: false }], total: 1, page: 1, page_size: 20 } });
  try {
    await openRecords(page);
    await expect(page.locator(".record-table tbody tr")).toContainText("手动");
    await page.getByRole("combobox", { name: "记录类型", exact: true }).selectOption("single");
    await expect(page.locator(".record-table tbody tr")).toContainText("单次记录 #51");
    await page.getByRole("combobox", { name: "记录类型", exact: true }).selectOption("batch");
    await expect(page.getByRole("heading", { name: "采集记录", exact: true })).toBeVisible();
    await expect(page.locator(".record-table tbody tr")).toContainText("手动");
    expect(evidence.errors).toEqual([]);
    expect(evidence.console).toEqual([]);
    await mock.expectNoUnexpectedApi();
  } finally {
    const dir = path.resolve("../.artifacts/collection-ui-final");
    await mkdir(dir, { recursive: true });
    await writeFile(path.join(dir, `repro-${testInfo.repeatEachIndex}.json`), JSON.stringify(evidence, null, 2));
    if (testInfo.repeatEachIndex === 0) await writeFile(path.join(dir, "repro.json"), JSON.stringify(evidence, null, 2));
  }
});

test("legacy search debounces committed IME text and clears incompatible filters", async ({ page }) => {
  const requests: URL[] = [];
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage, collectionRuns: url => { requests.push(url); return { items: [], total: 0, page: 1, page_size: 20 }; } });
  await openRecords(page);
  await expect(page.getByLabel("搜索", { exact: true })).toHaveCount(0);
  await page.getByRole("combobox", { name: "触发方式", exact: true }).selectOption("manual");
  await page.getByRole("combobox", { name: "异常情况", exact: true }).selectOption("recovered");
  await page.getByRole("combobox", { name: "记录类型", exact: true }).selectOption("single");
  await expect.poll(() => requests.length).toBeGreaterThan(0);
  expect(requests.at(-1)!.searchParams.get("trigger_kind")).toBe("all");
  const input = page.getByLabel("搜索", { exact: true });
  await input.dispatchEvent("compositionstart");
  await input.fill("shang");
  await page.waitForTimeout(450);
  expect(requests.some(url => url.searchParams.get("search") === "shang")).toBe(false);
  await input.fill("商品");
  await input.dispatchEvent("compositionend", { data: "商品" });
  await page.waitForTimeout(150);
  expect(requests.some(url => url.searchParams.get("search") === "商品")).toBe(false);
  await expect.poll(() => requests.at(-1)!.searchParams.get("search")).toBe("商品");
  await input.fill("商品1"); await input.fill("商品12"); await input.fill("商品123");
  await expect.poll(() => requests.at(-1)!.searchParams.get("search")).toBe("商品123");
  expect(requests.some(url => ["商品1", "商品12"].includes(url.searchParams.get("search") || ""))).toBe(false);
  await input.fill("");
  await expect.poll(() => requests.at(-1)!.searchParams.get("search")).toBe("");
  await page.getByRole("combobox", { name: "记录类型", exact: true }).selectOption("batch");
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

test("type switching handles page two empty failures and delayed obsolete records", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const mock = await installApiMock(page, { competitors: [] });
  let mode = "ready";
  let release: (() => void) | undefined;
  await page.route("**/api/collection-batches?*", async route => { const url = new URL(route.request().url()); await route.fulfill({ json: { ...batchPage, page: Number(url.searchParams.get("page")), total: 41 } }); });
  await page.route("**/api/collection-runs?*", async route => {
    const requestMode = mode;
    if (requestMode === "delayed") await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ status: requestMode === "error" ? 503 : 200, json: { items: [], total: 0, page: 1, page_size: 20 } });
  });
  await openRecords(page);
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
  const type = page.getByRole("combobox", { name: "记录类型", exact: true });
  await type.selectOption("single");
  await expect(page.getByText("暂无符合条件的采集记录，可清除筛选后重试。", { exact: true })).toBeVisible();
  await type.selectOption("batch");
  await expect(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
  mode = "error"; await type.selectOption("single");
  await expect(page.getByRole("alert")).toContainText("采集记录加载失败");
  mode = "ready"; await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await type.selectOption("batch");
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  mode = "delayed"; await type.selectOption("single");
  await expect.poll(() => !!release).toBe(true);
  await expect(page.locator(".record-table tbody tr")).toHaveCount(0);
  await type.selectOption("batch");
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  release!();
  for (let index = 0; index < 4; index++) { mode = "ready"; await type.selectOption("single"); await type.selectOption("batch"); }
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  await expect(page.locator(".record-table tbody tr")).toHaveCount(1);
  expect(errors).toEqual([]);
  await mock.expectNoUnexpectedApi();
});

test("detail stale responses cannot overwrite automatic filters and IME search", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage });
  const requests: URL[] = [];
  let release: (() => void) | undefined;
  await page.route("**/api/collection-batches/task-a?*", async route => {
    const url = new URL(route.request().url()); requests.push(url);
    const old = url.searchParams.get("anomaly") === "current";
    if (old) await new Promise<void>(resolve => { release = resolve; });
    const matching = url.searchParams.get("anomaly") === "recovered";
    await route.fulfill({ json: { ...detail, items: matching ? [batchItems[3]] : batchItems, total: matching ? 1 : 6 } });
  });
  await openRecords(page); await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByText("完整成功商品", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "是否异常", exact: true }).selectOption("current");
  await expect.poll(() => !!release).toBe(true);
  await expect(page.getByText("完整成功商品", { exact: true })).toHaveCount(0);
  await page.getByRole("combobox", { name: "是否异常", exact: true }).selectOption("recovered");
  await expect(page.getByText("补采后恢复商品", { exact: true })).toBeVisible();
  release!();
  await page.getByLabel("异常优先", { exact: true }).check();
  await expect.poll(() => requests.at(-1)!.searchParams.get("anomalies_first")).toBe("true");
  const input = page.getByLabel("关键词", { exact: true });
  await input.dispatchEvent("compositionstart"); await input.fill("bu"); await page.waitForTimeout(450);
  expect(requests.some(url => url.searchParams.get("search") === "bu")).toBe(false);
  await input.fill("补采"); await input.dispatchEvent("compositionend", { data: "补采" });
  await expect.poll(() => requests.at(-1)!.searchParams.get("search")).toBe("补采");
  await expect(page.getByText("完整成功商品", { exact: true })).toHaveCount(0);
  const row = page.getByRole("row").filter({ hasText: "补采后恢复商品" });
  await expect(row.locator("td").nth(1)).toHaveText("补采恢复成功");
  await row.getByRole("button", { name: /展开/ }).click();
  await expect(page.getByText("首次采集", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("经营指标补采", { exact: true }).last()).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

test("one task table opens final product results and authentic attempt history", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: competitors23, collectionBatches: batchPage, batchDetails: { "task-a": detail } });
  await openRecords(page);
  await expect(page.locator(".record-table")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "历史单次记录" })).toHaveCount(0);
  await expect(page.locator(".record-table tbody tr")).toHaveCount(1);
  const headers = page.locator(".record-table thead th");
  await expect(headers).toHaveText(["开始时间", "触发方式", "计划商品", "成功", "异常", "页面访问", "补采访问", "耗时", "任务状态", "操作"]);
  await expect(page.locator(".record-table tbody tr")).toContainText("5分10秒");
  await page.setViewportSize({ width: 1680, height: 1000 });
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "collection-records.png"), fullPage: true });
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByRole("heading", { name: "批次详情", exact: true })).toBeVisible();
  for (const title of batchItems.slice(0, 5).map(row => row.title)) await expect(page.getByText(title, { exact: true })).toBeVisible();
  await expect(page.getByText("商品已删除", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /展开/ })).toHaveCount(6);
  await expect(page.getByText("官方采购助手来源不可用", { exact: false }).first()).toBeVisible();
  await page.setViewportSize({ width: 1680, height: 1200 });
  await expect(page.locator(".collection-records .pagination-bar")).toBeInViewport();
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "batch-detail.png"), fullPage: true });
  const recoveredRow = page.getByRole("row").filter({ hasText: "补采后恢复商品" });
  await recoveredRow.getByRole("button", { name: /展开/ }).click();
  await expect(page.getByText("首次采集", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("经营指标补采", { exact: true }).last()).toBeVisible();
  const fields = page.locator("details summary").filter({ hasText: /字段/ });
  await expect(fields).toHaveCount(2);
  await fields.nth(0).click();
  await fields.nth(1).click();
  const fieldTable = page.locator(".record-fields").first();
  await expect(fieldTable).toBeVisible();
  expect(await fieldTable.evaluate(element => element.closest("td")?.colSpan)).toBe(7);
  const fieldBox = await fieldTable.boundingBox();
  const attemptBox = await page.locator(".record-attempts > table").first().boundingBox();
  expect(fieldBox!.width).toBeGreaterThan(attemptBox!.width * 0.9);
  await expect(page.getByText("页面显示 -，无需补采").first()).toBeVisible();
  await expect(page.getByText("来源不可用", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("已读取", { exact: true }).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/partial_success|first_pass|operating_metrics_retry|source_unavailable/);
  await page.setViewportSize({ width: 1680, height: 2600 });
  await page.evaluate(() => document.querySelectorAll(".main-content, .table-scroll").forEach(element => element.scrollTo(0, 0)));
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "batch-product-expanded.png"), fullPage: true });
  await page.getByRole("row").filter({ hasText: "验证恢复商品" }).getByRole("button", { name: /展开/ }).click();
  await expect(page.getByText("验证恢复", { exact: true }).last()).toBeVisible();
  await page.setViewportSize({ width: 1100, height: 1500 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const pagination = page.locator(".collection-records .pagination-bar");
  await expect(pagination).toBeVisible();
  const padding = await pagination.evaluate(element => { const style = getComputedStyle(element); return [parseFloat(style.paddingLeft), parseFloat(style.paddingRight), parseFloat(style.paddingTop), parseFloat(style.paddingBottom)]; });
  expect(padding.every(value => value >= 16)).toBe(true);
  await pagination.scrollIntoViewIfNeeded();
  await expect(pagination).toBeInViewport();
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "batch-responsive-pagination.png"), fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("product filter combinations and pagination retain selected batch and complete summary", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage });
  const requests: URL[] = [];
  await page.route("**/api/collection-batches/task-a?*", async route => {
    const url = new URL(route.request().url()); requests.push(url);
    const filtered = url.searchParams.get("anomaly") === "current";
    const second = url.searchParams.get("page") === "2";
    await route.fulfill({ json: { ...detail, items: filtered ? [batchItems[2]] : second ? [batchItems[3]] : batchItems, total: filtered ? 1 : 21, page: second ? 2 : 1 } });
  });
  await openRecords(page);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByText("完整成功商品", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("补采后恢复商品", { exact: true })).toBeVisible();
  await expect(page.getByText("完整成功商品", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "批次汇总" })).toContainText("完成 5 / 6");
  await expect(page.getByRole("region", { name: "批次汇总" }).locator("div strong")).toHaveText(["6", "4", "1", "7", "1", "5分10秒", "部分成功"]);
  await page.getByRole("combobox", { name: "是否异常", exact: true }).selectOption("current");
  await page.getByRole("combobox", { name: "尝试类型", exact: true }).selectOption("first_pass");
  await page.getByRole("combobox", { name: "异常原因", exact: true }).selectOption("source_unavailable");
  await page.getByRole("combobox", { name: "最终结果", exact: true }).selectOption("exception");
  await page.getByLabel("关键词", { exact: true }).fill("123450002");
  await expect(page.getByText("来源读取技术异常商品", { exact: true })).toBeVisible();
  await expect(page.getByText("补采后恢复商品", { exact: true })).toHaveCount(0);
  await expect.poll(() => requests.at(-1)?.searchParams.get("search")).toBe("123450002");
  const last = requests.at(-1)!.searchParams;
  expect(Object.fromEntries(last)).toMatchObject({ page: "1", search: "123450002", final_result: "exception", anomaly: "current", attempt_kind: "first_pass", reason: "source_unavailable" });
  await page.setViewportSize({ width: 1680, height: 1000 });
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "batch-anomaly-filter.png"), fullPage: true });
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await expect(page.getByText("完整成功商品", { exact: true })).toBeVisible();
  expect(requests.at(-1)!.searchParams.get("page")).toBe("1");
  await mock.expectNoUnexpectedApi();
});

test("placeholder reason filters a successful product without marking a technical anomaly", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage });
  const requests: URL[] = [];
  await page.route("**/api/collection-batches/task-a?*", async route => {
    const url = new URL(route.request().url()); requests.push(url);
    const matching = url.searchParams.get("reason") === "placeholder";
    await route.fulfill({ json: { ...detail, items: matching ? [batchItems[1]] : batchItems, total: matching ? 1 : batchItems.length } });
  });
  await openRecords(page);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await page.getByRole("combobox", { name: "异常原因", exact: true }).selectOption("placeholder");
  await page.getByRole("combobox", { name: "是否异常", exact: true }).selectOption("none");
  const row = page.locator(".record-product-table > tbody > tr");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("正常页面占位商品");
  await expect(row.locator("td").nth(1)).toHaveText("成功");
  await expect(row.locator("td").nth(5)).toHaveText("—");
  expect(Object.fromEntries(requests.at(-1)!.searchParams)).toMatchObject({ reason: "placeholder", anomaly: "none", page: "1" });
  await row.getByRole("button", { name: /展开/ }).click();
  await page.getByText("查看 8 项字段明细", { exact: true }).click();
  await expect(page.getByText("页面显示 -，无需补采", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "批次汇总" }).locator("div strong")).toHaveText(["6", "4", "1", "7", "1", "5分10秒", "部分成功"]);
  await mock.expectNoUnexpectedApi();
});

test("home combined filters use server query and reset page", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage });
  const requests: URL[] = [];
  await page.route("**/api/collection-batches?*", async route => { const url = new URL(route.request().url()); requests.push(url); await route.fulfill({ json: { ...batchPage, total: 41, page: Number(url.searchParams.get("page")) } }); });
  await openRecords(page);
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
  await page.getByLabel("开始日期", { exact: true }).fill("2026-10-01");
  await page.getByLabel("结束日期", { exact: true }).fill("2026-10-14");
  await page.getByRole("combobox", { name: "触发方式", exact: true }).selectOption("manual");
  await page.getByRole("combobox", { name: "异常情况", exact: true }).selectOption("current");
  await expect(page.getByLabel("搜索", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "查询", exact: true })).toHaveCount(0);
  await expect(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
  expect(Object.fromEntries(requests.at(-1)!.searchParams)).toMatchObject({ page: "1", trigger_kind: "manual", anomaly: "current", search: "" });
  expect(requests.at(-1)!.searchParams.get("started_after")).toBe(await page.evaluate(() => new Date("2026-10-01T00:00:00").toISOString()));
  expect(requests.at(-1)!.searchParams.get("started_before")).toBe(await page.evaluate(() => new Date("2026-10-14T23:59:59.999").toISOString()));
  await mock.expectNoUnexpectedApi();
});

test("home accepts one-sided dates rejects inverted ranges and restores defaults", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  const requests: URL[] = [];
  await page.route("**/api/collection-batches?*", route => { const url = new URL(route.request().url()); requests.push(url); return route.fulfill({ json: batchPage }); });
  await openRecords(page);
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  const initial = Object.fromEntries(requests.at(-1)!.searchParams);
  await page.getByLabel("开始日期", { exact: true }).fill("");
  await page.getByLabel("结束日期", { exact: true }).fill("2026-10-14");
  await expect.poll(() => requests.at(-1)!.searchParams.get("started_before")).not.toBeNull();
  expect(requests.at(-1)!.searchParams.has("started_after")).toBe(false);
  await page.getByLabel("结束日期", { exact: true }).fill("");
  await page.getByLabel("开始日期", { exact: true }).fill("2026-10-14");
  await expect.poll(() => requests.at(-1)!.searchParams.get("started_after")).toBe(await page.evaluate(() => new Date("2026-10-14T00:00:00").toISOString()));
  expect(requests.at(-1)!.searchParams.has("started_before")).toBe(false);
  await page.getByLabel("结束日期", { exact: true }).fill("2026-10-01");
  await page.waitForTimeout(450);
  expect(requests.some(url => url.searchParams.has("started_after") && url.searchParams.has("started_before") && url.searchParams.get("started_after")! > url.searchParams.get("started_before")!)).toBe(false);
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await expect.poll(() => Object.fromEntries(requests.at(-1)!.searchParams)).toEqual(initial);
  await expect(page.locator(".record-duration-note")).toContainText("页面显示 - 不属于技术异常");
  await page.setViewportSize({ width: 1000, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "home-pagination-help.png"), fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("server count shrink clamps home and detail pagination to a valid page", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  const homePages: number[] = [], detailPages: number[] = [];
  let shrinkHome = false, shrinkDetail = false;
  await page.route("**/api/collection-batches?*", route => { const requested = Number(new URL(route.request().url()).searchParams.get("page")); homePages.push(requested); if (requested === 3) shrinkHome = true; return route.fulfill({ json: { ...batchPage, items: requested === 3 ? [] : [batch], total: shrinkHome ? 21 : 41, page: requested } }); });
  await page.route("**/api/collection-batches/task-a?*", route => { const requested = Number(new URL(route.request().url()).searchParams.get("page")); detailPages.push(requested); if (requested === 3) shrinkDetail = true; return route.fulfill({ json: { ...detail, items: requested === 3 ? [] : [batchItems[0]], total: shrinkDetail ? 11 : 21, page: requested } }); });
  await openRecords(page);
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  expect(homePages.slice(-2)).toEqual([3, 2]);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  expect(detailPages.slice(-2)).toEqual([3, 2]);
  await mock.expectNoUnexpectedApi();
});

test("legacy records stay accessible only by explicit type and preserve dual statuses", async ({ page }) => {
  const statuses = ["success", "partial", "no_values", "failed", "blocked", "not_attempted", undefined] as const;
  const labels = ["经营成功", "经营部分成功", "经营页面暂无值", "经营失败", "经营已阻止", "经营未尝试", "经营未采集"];
  const requested: URL[] = [];
  const mock = await installApiMock(page, { competitors: [], collectionBatches: batchPage, collectionRuns: url => {
    requested.push(url);
    return { items: statuses.map((operating_metrics_status, index) => ({ id: index + 1, competitor_id: 1, ownership: "competitor", title: `状态记录 ${index + 1}`, offer_id: `offer-${index + 1}`, shop_name: "测试店铺", started_at: "2026-10-14T00:00:00Z", finished_at: "2026-10-14T00:00:04Z", status: "success", ...(operating_metrics_status ? { operating_metrics_status } : {}), error_type: null, error_message: null, duration_seconds: 4 })), total: statuses.length, page: 1, page_size: 20 };
  } });
  await openRecords(page);
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  expect(requested).toHaveLength(0);
  await page.getByRole("combobox", { name: "记录类型", exact: true }).selectOption("single");
  await expect(page.locator(".record-table tbody tr")).toHaveCount(statuses.length);
  expect(requested.at(-1)!.searchParams.get("unbatched")).toBe("true");
  for (const [index, label] of labels.entries()) await expect(page.locator(".record-table tbody tr").nth(index)).toContainText(label);
  await expect(page.locator(".record-table")).toHaveCount(1);
  await page.route("**/api/collection-runs/1", route => route.fulfill({ json: { ...attempt(1, 1, "first_pass", ["observed", "placeholder", ...observed.slice(2)]), title: "状态记录 1", offer_id: "offer-1", shop_name: "测试店铺", main_image_url: null, collection_batch_item_id: null } }));
  await page.getByRole("button", { name: "查看详情", exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "单次采集详情", exact: true })).toBeVisible();
  await expect(page.getByText("历史未归属单次采集 · 无可靠批次身份", { exact: true })).toBeVisible();
  await page.getByText("查看 8 项字段明细", { exact: true }).click();
  await expect(page.getByText("页面显示 -，无需补采", { exact: true })).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

test("empty history page retains server pagination and returns to previous page", async ({ page }) => {
  const requestedPages: number[] = [];
  const mock = await installApiMock(page, { competitors: [], collectionRuns: url => { const requestedPage = Number(url.searchParams.get("page")); requestedPages.push(requestedPage); return { items: [], total: requestedPage === 1 ? 41 : 21, page: requestedPage, page_size: 20 }; } });
  await openRecords(page);
  await page.getByRole("combobox", { name: "记录类型", exact: true }).selectOption("single");
  await expect(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("暂无符合条件的采集记录，可清除筛选后重试。", { exact: true })).toBeVisible();
  await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
  expect(requestedPages.slice(-2)).toEqual([2, 1]);
  await mock.expectNoUnexpectedApi();
});

test("batch query ignores delayed stale response", async ({ page }) => {
  let releaseOld: (() => void) | undefined;
  let oldFinished: Promise<void> | undefined;
  const mock = await installApiMock(page, { competitors: [] });
  await page.route("**/api/collection-batches?*", async route => {
    if (new URL(route.request().url()).searchParams.get("anomaly") === "all") {
      await new Promise<void>(resolve => { releaseOld = resolve; });
      oldFinished = route.fulfill({ json: { ...batchPage, items: [{ ...batch, planned_products: 999 }] } }); await oldFinished; return;
    }
    await route.fulfill({ json: batchPage });
  });
  await openRecords(page);
  await expect.poll(() => !!releaseOld).toBe(true);
  await page.getByRole("combobox", { name: "异常情况", exact: true }).selectOption("current");
  await expect(page.getByRole("button", { name: "查看详情", exact: true })).toBeVisible();
  releaseOld!(); await expect.poll(() => !!oldFinished).toBe(true); await oldFinished;
  await expect(page.locator(".record-table tbody")).not.toContainText("999");
  await mock.expectNoUnexpectedApi();
});

test("failed record and detail API can retry without a second history panel", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  let failBatches = true; let failDetail = true;
  await page.route("**/api/collection-batches?*", route => route.fulfill({ status: failBatches ? 503 : 200, json: batchPage }));
  await page.route("**/api/collection-batches/task-a?*", route => route.fulfill({ status: failDetail ? 503 : 200, json: detail }));
  await openRecords(page);
  await expect(page.getByText("采集记录加载失败", { exact: true })).toBeVisible();
  failBatches = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByText("采集记录加载失败", { exact: true })).toBeVisible();
  failDetail = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("完整成功商品", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /返回采集记录/ }).click();
  await expect(page.locator(".record-table")).toHaveCount(1);
  await mock.expectNoUnexpectedApi();
});

for (const source of ["own-products", "competitors"]) test(`${source} retains the shared local ten-row pagination`, async ({ page }) => {
  const self = source === "own-products";
  const products = competitors23.map(product => ({ ...product, ownership: self ? "self" as const : "competitor" as const }));
  const mock = await installApiMock(page, { competitors: products });
  await page.goto("/");
  await page.getByRole("button", { name: self ? "我方商品" : "竞品列表", exact: true }).click();
  const bar = page.locator(".pagination-bar");
  await expect(bar).toContainText(self ? "共 23 个我方商品" : "共 23 个竞品");
  await expect(bar.locator('[aria-current="page"]')).toHaveText("1");
  await expect(bar.getByRole("button", { name: "上一页" })).toBeDisabled();
  await bar.getByRole("button", { name: "下一页" }).click();
  await expect(bar).toContainText("第 2 / 3 页");
  await expect(page.getByRole("row").filter({ hasText: "固定竞品 11" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "固定竞品 10" })).toHaveCount(0);
  await mock.expectNoUnexpectedApi();
});

test("dashboard remains the single live collection progress and control surface", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  const state = { status: "running", outcome_code: null, batch_id: 4, task_id: "task-live", lifecycle_status: "running", batch_outcome_code: null, phase: "operating_metrics_retry", attempts_started: 4, page_visits: 3, page_visits_unknown: 0, verification_resume_visits: 1, retry_visits: 1, retry_max: 1, retry_total: 2, retry_completed: 1, total: 3, completed: 1, succeeded: 1, failed: 0, remaining: 2, verification_required: 0, current_competitor_id: 1, current_competitor_title: "搜索目标竞品 01", browser_open: true, runner_active: true, auto_resume_attempt: 1, auto_resume_max: 2, cooldown_remaining_seconds: 30, resting_remaining_seconds: 20, operating_metrics_counts: { not_attempted: 0, success: 0, partial: 0, no_values: 0, failed: 0, blocked: 0 }, items: [] };
  await page.route("**/api/competitors/collect-batch/status", route => route.fulfill({ json: state }));
  await page.goto("/");
  await page.getByRole("button", { name: "竞品监控大屏", exact: true }).click();
  await expect(page.getByRole("heading", { name: "采集状态概览" })).toBeVisible();
  await expect(page.getByText("采集中", { exact: true })).toBeVisible();
  await expect(page.getByRole("progressbar")).toBeVisible();
  await expect(page.getByText("搜索目标竞品 01")).toBeVisible();
  await expect(page.getByText(/阶段：经营补采 1\/2/)).toBeVisible();
  await expect(page.getByText(/完成 1 \/ 3 · 剩余 2/)).toBeVisible();
  await expect(page.getByText(/页面访问 3/)).toBeVisible();
  await expect(page.getByText(/补采访问 1 · 上限 1/)).toBeVisible();
  await expect(page.getByRole("button", { name: "暂停采集" })).toBeVisible();
  await expect(page.getByRole("button", { name: "结束采集" })).toBeVisible();
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "v1.2-live-dashboard.png"), fullPage: true });
  await mock.expectNoUnexpectedApi();
});
