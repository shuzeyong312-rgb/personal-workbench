import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

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

test("manual batch keeps the accepted seven-card 51/51 summary", async ({ page }, testInfo) => {
  const manualSummary = { ...batch, outcome_code: "success", planned_products: 51, completed: 51, remaining: 0, page_visits: 51, retry_visits: 0, counts: { first_pass_success: 51 } };
  const manualItems = Array.from({ length: 10 }, (_, position) => item(position, `验收商品 ${position + 1}`, "first_pass_success", [attempt(200 + position, 1, "first_pass", observed)], { offer_id: String(200 + position) }));
  const manualDetail = { ...detail, ...manualSummary, summary: manualSummary, items: manualItems, total: 51, page: 1, page_size: 10 };
  const mock = await installApiMock(page, { competitors: [], collectionBatches: { items: [manualSummary], total: 1, page: 1, page_size: 20 }, batchDetails: { "task-a": manualDetail } });
  await openRecords(page);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.getByRole("region", { name: "批次汇总" }).locator(".record-metric")).toHaveCount(7);
  await expect(page.getByRole("region", { name: "批次汇总" }).locator(".record-metric strong")).toHaveText(["51", "51", "0", "51", "0", "5分10秒", "成功"]);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "manual-batch-51-of-51.png"), fullPage: true });
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
  await expect(headers).toHaveText(["开始时间", "触发方式", "计划商品 / 提交链接", "成功", "异常", "页面访问", "补采访问", "耗时", "任务状态", "操作"]);
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

test("add-links batch uses the compact product table, seven summary cards, and full-width expandable history", async ({ page }, testInfo) => {
  const addSummary = {
    ...batch, task_id: "add-task", task_kind: "add_links", trigger_kind: "add_links", outcome_code: "partial_failure", planned_products: 6,
    counts: { first_pass_success: 6 }, page_visits: 6, retry_visits: 0, anomaly_products: 0, technical_exception_products: 0,
    input_summary: { total: 9, candidate_total: 6, processed: 9, remaining: 0, pending: 0, added: 6, business_rejected: 3, technical_failed: 0, verification_required: 0, interrupted: 0, not_executed: 0, anomaly_inputs: 0 },
  };
  const metricValues = ["2024-01", "100+", "<10", "500+", "200+", "95", "95%", "98%"];
  const successful = item(0, "这是一款用于测试两行省略与完整标题 tooltip 的长标题商品", "first_pass_success", [attempt(101, 1, "first_pass", observed)], {
    source_line: 1, input_text: "https://detail.1688.com/offer/101.html?spm=very-long-query-parameter-value",
    offer_id: "101", title: "这是一款用于测试两行省略与完整标题 tooltip 的长标题商品", shop_name: "测试店铺名称以及较长来源信息", main_image_url: "http://127.0.0.1:5201/product-thumb.svg",
    result_code: "added", operating_metrics_status: "success",
    attempts: [{ ...attempt(101, 1, "first_pass", observed), observations: metricKeys.map((metric_key, index) => ({ metric_key, status: "observed", raw_value: metricValues[index], reason: null, source: "官方采购助手来源说明较长", observed_at: "2026-10-15T03:45:47Z" })) }],
  });
  const addItems = [
    ...Array.from({ length: 6 }, (_, index) => ({ ...successful, position: index, source_line: index + 1, offer_id: String(101 + index), input_text: `https://detail.1688.com/offer/${101 + index}.html?query=${"x".repeat(140)}`, title: index ? `成功商品 ${index + 1}` : successful.title, main_image_url: index ? null : successful.main_image_url })),
    { ...item(6, "已存在商品", "first_pass_success", []), source_line: 7, input_text: "https://detail.1688.com/offer/107.html", offer_id: "107", result_code: "already_exists", sanitized_reason: "商品已存在" },
    { ...item(7, null, "not_executed", []), source_line: 8, input_text: "invalid", offer_id: null, title: null, shop_name: null, main_image_url: null, result_code: "invalid_url", sanitized_reason: "链接格式无效" },
    { ...item(8, "归组冲突商品", "not_executed", []), source_line: 9, input_text: "https://detail.1688.com/offer/109.html", offer_id: "109", result_code: "identity_rejected", sanitized_reason: "归组冲突" },
  ];
  const addDetail = { ...detail, ...addSummary, summary: addSummary, items: addItems, total: addItems.length, page: 1, page_size: 10 };
  const addBatchPage = { items: [addSummary], total: 1, page: 1, page_size: 20 };
  const mock = await installApiMock(page, { competitors: [], collectionBatches: addBatchPage, batchDetails: { "add-task": addDetail } });
  await page.route("http://127.0.0.1:5201/product-thumb.svg", route => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60"><rect width="60" height="60" fill="#d8e6fa"/></svg>' }));
  await openRecords(page);
  const addBatchRow = page.locator(".record-table tbody tr").first();
  await expect(addBatchRow.locator("td").nth(2)).toHaveText("提交 9 条");
  await expect(addBatchRow.locator("td").nth(4)).toHaveText("0");
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  const summaryCards = page.getByRole("region", { name: "批次汇总" }).locator(".record-metric");
  await expect(summaryCards).toHaveCount(7);
  await expect(summaryCards.locator("strong")).toHaveText(["9", "6", "3", "0", "6", "5分10秒", "部分新增成功"]);
  await expect(page.locator(".record-add-table thead th")).toHaveText(["商品信息", "新增结果", "页面访问", "耗时", "经营指标", "操作"]);
  await expect(page.locator(".record-add-table > tbody > tr")).toHaveCount(9);
  const productRow = page.locator(".record-add-table > tbody > tr").nth(0);
  await expect(productRow.locator("img.product-image")).toHaveAttribute("src", /product-thumb\.svg/);
  await expect(productRow).toContainText("Offer ID：101");
  await expect(productRow).toContainText("测试店铺名称以及较长来源信息");
  await page.setViewportSize({ width: 1600, height: 1100 });
  const beforeExpand = await page.locator(".record-add-table").boundingBox();
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "add-links-batch-1600.png"), fullPage: true });
  await productRow.getByRole("button", { name: /展开/ }).click();
  const expandedRow = page.locator(".record-add-detail-row").first();
  await expect(expandedRow.locator('td[colspan="6"]')).toHaveCount(1);
  await expect(expandedRow).toContainText("第 1 行 · 原始输入");
  await expect(expandedRow).toContainText("100+");
  await expect(expandedRow).toContainText("<10");
  const fieldSummary = expandedRow.getByText(/查看 8 项字段明细/);
  await fieldSummary.click();
  const fields = expandedRow.locator(".record-fields");
  await expect(fields.locator("thead th")).toHaveText(["字段名称", "原始页面值", "字段状态", "缺失 / 失败原因"]);
  await expect(fields.locator("tbody tr").first().locator("td").nth(2)).toHaveAttribute("title", /官方采购助手来源说明较长.*观察时间/);
  const afterExpand = await page.locator(".record-add-table").boundingBox();
  expect(afterExpand!.width).toBeCloseTo(beforeExpand!.width, 0);
  const secondRow = page.locator(".record-add-table > tbody > tr").nth(2);
  await expect(secondRow).toContainText("成功商品 2");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "add-links-batch-expanded-1440.png"), fullPage: true });
  await page.setViewportSize({ width: 1100, height: 1200 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.locator(".record-add-table").evaluate(table => table.closest(".table-scroll")!.scrollWidth > table.closest(".table-scroll")!.clientWidth)).toBe(true);
  await page.screenshot({ path: acceptanceScreenshot(testInfo, "add-links-batch-expanded-1100.png"), fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("add-links rejected inputs never render invented product photos or store details", async ({ page }) => {
  const addSummary = {
    ...batch, task_id: "add-errors", task_kind: "add_links", trigger_kind: "add_links", outcome_code: "partial_failure", planned_products: 1,
    counts: { final_failed: 1 }, page_visits: 1, anomaly_products: 1, technical_exception_products: 0,
    input_summary: { total: 4, candidate_total: 1, processed: 4, remaining: 0, pending: 0, added: 0, business_rejected: 3, technical_failed: 1, verification_required: 0, interrupted: 0, not_executed: 0, anomaly_inputs: 0 },
  };
  const rejectedItems = [
    { ...item(0, "真实的已存在商品", "not_executed", []), source_line: 1, input_text: "https://detail.1688.com/offer/201.html", offer_id: "201", result_code: "already_exists", sanitized_reason: "商品已存在" },
    { ...item(1, null, "not_executed", []), source_line: 2, input_text: "invalid", offer_id: null, title: null, shop_name: null, main_image_url: null, result_code: "invalid_url", sanitized_reason: "链接格式无效" },
    { ...item(2, null, "final_failed", []), source_line: 3, input_text: "https://detail.1688.com/offer/203.html", offer_id: "203", title: null, shop_name: null, main_image_url: null, result_code: "technical_failed", sanitized_reason: "页面读取失败：" + "原因".repeat(50), has_anomaly: true, attempts: [attempt(203, 1, "first_pass", [], "failed")] },
    { ...item(3, null, "not_executed", []), source_line: 4, input_text: "https://detail.1688.com/offer/204.html", offer_id: null, title: null, shop_name: null, main_image_url: null, identity_removed: true, result_code: "already_exists", sanitized_reason: "商品身份已移除" },
  ];
  const addDetail = { ...detail, ...addSummary, summary: addSummary, items: rejectedItems, total: 3, page: 1, page_size: 10 };
  const mock = await installApiMock(page, { competitors: [], collectionBatches: { items: [addSummary], total: 1, page: 1, page_size: 20 }, batchDetails: { "add-errors": addDetail } });
  await openRecords(page);
  await page.getByRole("button", { name: "查看详情", exact: true }).click();
  const rows = page.locator(".record-add-table > tbody > tr");
  await expect(rows).toHaveCount(4);
  await expect(rows.nth(0)).toContainText("真实的已存在商品");
  await expect(rows.nth(0)).toContainText("商品已存在");
  await expect(rows.nth(0).locator(".record-add-reason")).toHaveCount(0);
  await expect(rows.nth(1)).toContainText("invalid");
  await expect(rows.nth(1).locator(".record-add-reason")).toHaveText("链接格式无效");
  await expect(rows.nth(2)).toContainText("Offer ID 203");
  await expect(rows.nth(3)).toContainText("身份已移除");
  await expect(rows.nth(3)).not.toContainText("204");
  await expect(rows.locator("img.product-image")).toHaveCount(0);
  await expect(rows.locator(".product-image-placeholder")).toHaveCount(0);
  await expect(rows.nth(2).locator(".record-add-reason")).toHaveCSS("overflow-wrap", "anywhere");
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
  expect(Object.fromEntries(requests.at(-1)!.searchParams)).toMatchObject({ page: "1", trigger_kind: "manual", anomaly: "current" });
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
  expect(initial).toMatchObject({ page: "1", page_size: "20", trigger_kind: "all", anomaly: "all" });
  expect(requests.at(-1)!.searchParams.has("started_after")).toBe(false);
  expect(requests.at(-1)!.searchParams.has("started_before")).toBe(false);
  await expect(page.getByLabel("开始日期", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("结束日期", { exact: true })).toHaveValue("");
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


test("empty task page retains server pagination and returns to previous page", async ({ page }) => {
  const requestedPages: number[] = [];
  const mock = await installApiMock(page, { competitors: [] });
  await page.route("**/api/collection-batches?*", route => { const requestedPage = Number(new URL(route.request().url()).searchParams.get("page")); requestedPages.push(requestedPage); return route.fulfill({ json: { items: [], total: requestedPage === 1 ? 41 : 21, page: requestedPage, page_size: 20 } }); });
  await openRecords(page);
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
