import { expect, test, type Page, type TestInfo } from "@playwright/test";
import path from "node:path";
import { mkdir } from "node:fs/promises";

import type { Competitor } from "../src/App";
import { installApiMock } from "./support/api-mock";

const source = "1688_official_procurement_assistant_top";
const product: Competitor = {
  id: 1, platform: "1688", offer_id: "123456789", url: "https://detail.1688.com/offer/123456789.html",
  group_id: null, group_role: "competitor", ownership: "competitor", title: "暖手宝商品", shop_name: "家居店",
  main_image_url: null, status: "active", is_active: true, created_at: "2026-10-01T00:00:00Z", last_collected_at: "2026-10-10T00:08:00Z",
  latest_snapshot: { price_min: "40.00", price_max: "45.00", sku_count: 2 }, latest_change: null,
};

const fields = [
  ["listing_time", "上架时间", "经营表现"], ["monthly_deal", "月成交", "经营表现"],
  ["monthly_dropship", "月代销", "经营表现"], ["annual_units", "年成交件数", "经营表现"],
  ["annual_orders", "年成交笔数", "经营表现"], ["review_count", "评论数", "口碑履约"],
  ["positive_rate", "好评率", "口碑履约"], ["pickup_rate", "揽收率", "口碑履约"],
] as const;

function metric(index: number, mode: "normal" | "mixed") {
  const [metric_key, label, section] = fields[index];
  const historical = mode === "mixed" && [1, 2, 3].includes(index);
  const status = mode === "normal" ? "observed" : index === 1 || index === 7 ? "placeholder" : index === 3 ? "loading" : index === 4 ? "source_unavailable" : index === 5 ? "read_failed" : "observed";
  const raw_value = mode === "normal" ? ["2025-01-02", "100+", "12", "1,234", "56", "1,234", "95.6%", "98%"][index] : index === 1 || index === 7 ? "-" : index === 3 ? null : index === 4 || index === 5 ? null : ["2025-01-02", null, null, null, null, null, "95.6%", null][index];
  const valid_value = historical ? index === 1 ? "100+" : index === 2 ? "12" : "1,234" : mode === "normal" || status === "observed" ? raw_value : null;
  const validRun = historical ? 18 : 20;
  return {
    metric_key, label, section, eligible: true, status,
    latest_attempt: { collection_run_id: 20, status, raw_value, source, observed_at: "2026-10-10T00:08:00Z", reason: status === "read_failed" || status === "source_unavailable" ? "脱敏 Fixture 读取状态" : null },
    latest_valid: valid_value ? { collection_run_id: validRun, raw_value: valid_value, source, observed_at: historical ? "2026-10-08T00:08:00Z" : "2026-10-10T00:08:00Z" } : null,
  };
}

function detail(mode: "normal" | "mixed") {
  return {
    range_days: 7, competitor: product,
    latest_snapshot: { id: 20, captured_at: "2026-10-10T00:08:00Z", price_min: "40.00", price_max: "45.00", image_urls: null, product_status: "active", sku_count: 2, total_stock: 998, min_order_quantity: 1 },
    latest_skus: [{ sku_id: "sku-red", sku_name: "红色", stock: 600, price: "40.00" }, { sku_id: "sku-blue", sku_name: "蓝色", stock: 398, price: "45.00" }],
    latest_price_change: null,
    daily_trend: Array.from({ length: 7 }, (_, index) => ({ date: `2026-10-${String(index + 4).padStart(2, "0")}`, snapshot_id: index + 1, captured_at: `2026-10-${String(index + 4).padStart(2, "0")}T00:00:00Z`, price_min: `${39 + index}.00`, price_max: `${44 + index}.00`, total_stock: 1000 - index * 15 })),
    recent_changes: [{ id: 1, competitor_id: 1, change_type: "price_changed", entity_key: null, old_value: "39.00", new_value: "40.00", detected_at: "2026-10-10T00:08:00Z", collection_run_id: 20 }],
    recent_collection_runs: [{ id: 20, started_at: "2026-10-10T00:00:00Z", finished_at: "2026-10-10T00:08:00Z", status: "success", operating_metrics_status: "partial", error_type: null, error_message: null }],
    latest_collection_run: { id: 20, started_at: "2026-10-10T00:00:00Z", finished_at: "2026-10-10T00:08:00Z", status: "success", operating_metrics_status: "partial", error_type: null, error_message: null },
    operating_metrics: [...fields.map((_, index) => metric(index, mode)), { metric_key: "favorite_count", label: "收藏数", section: "口碑履约", eligible: false, status: "not_attempted", latest_attempt: null, latest_valid: null }, { metric_key: "platform_tag_new", label: "新品", section: "平台标签", eligible: false, status: "not_attempted", latest_attempt: null, latest_valid: null }],
  };
}

async function openDetail(page: Page, mode: "normal" | "mixed", adjust?: (data: ReturnType<typeof detail>) => void) {
  await installApiMock(page, { competitors: [product] });
  const fixture = detail(mode);
  adjust?.(fixture);
  await page.route("**/api/competitors/1/detail**", route => route.fulfill({ json: fixture }));
  await page.goto("/");
  await page.locator(".workspace-sidebar").getByRole("button", { name: "竞品列表", exact: true }).click();
  await page.getByRole("button", { name: product.title!, exact: true }).click();
  await expect(page.getByRole("heading", { name: "经营数据" })).toBeVisible();
}

async function screenshot(page: Page, testInfo: TestInfo, name: string, fullPage = true) {
  const directory = process.env.PW_DETAIL_UI_SCREENSHOT_DIR;
  const pathName = directory ? path.join(directory, name) : testInfo.outputPath(name);
  await mkdir(path.dirname(pathName), { recursive: true });
  await page.evaluate(() => {
    if (document.getElementById("fixture-mark")) return;
    const mark = document.createElement("div");
    mark.id = "fixture-mark";
    mark.textContent = "受控 Fixture · 非真实采集结果";
    Object.assign(mark.style, { position: "fixed", zIndex: "99999", right: "12px", bottom: "12px", padding: "7px 10px", borderRadius: "6px", color: "#fff", background: "#475569", font: "12px sans-serif", boxShadow: "0 2px 8px #0003" });
    document.body.append(mark);
  });
  await page.screenshot({ path: pathName, fullPage });
}

test("normal operating metrics and complete detail layout at 1440px", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openDetail(page, "normal");
  for (const [, label] of fields) await expect(page.getByRole("button", { name: new RegExp(label) })).toBeVisible();
  await expect(page.getByText("100+", { exact: true })).toBeVisible();
  await expect(page.getByText("95.6%", { exact: true })).toBeVisible();
  await expect(page.getByText("收藏数")).toHaveCount(0);
  await expect(page.getByText("新品", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "价格趋势" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "库存趋势" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "SKU 信息" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "最近变化" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "最近采集记录" })).toBeVisible();
  await page.getByRole("button", { name: "近 30 天" }).click();
  await expect(page.getByRole("button", { name: "近 30 天" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "近 7 天" }).click();
  await expect(page.getByRole("button", { name: "近 7 天" })).toHaveAttribute("aria-pressed", "true");
  await screenshot(page, testInfo, "A-normal-operating-data-1440-fixture.png", false);
  await screenshot(page, testInfo, "D-complete-product-detail-1440-fixture.png");
  const cards = await page.locator(".operating-metric-card").count();
  expect(cards).toBe(8);
  await page.getByRole("button", { name: /月成交/ }).click();
  const currentEvidence = page.getByRole("region", { name: "月成交数据依据" });
  await expect(currentEvidence).toContainText("本次有效值");
  await expect(currentEvidence.locator(".operating-evidence-record")).toHaveCount(1);
  await screenshot(page, testInfo, "E-current-valid-evidence-1440-fixture.png");
});

test("historical values, read failures, evidence switching, and responsive detail layout", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await openDetail(page, "mixed");
  await page.getByRole("button", { name: "查看数据依据" }).click();
  await expect(page.getByRole("region", { name: "上架时间数据依据" })).toBeVisible();
  await page.getByRole("button", { name: "收起", exact: true }).click();
  const monthly = page.getByRole("button", { name: /月成交/ });
  await expect(monthly).toContainText("100+");
  await expect(monthly).toContainText("历史有效值");
  await expect(monthly).toContainText("本次：页面显示占位符");
  await expect(page.getByRole("button", { name: /年成交件数/ })).toContainText("历史有效值");
  await expect(page.getByRole("button", { name: /年成交笔数/ })).toContainText("来源不可用");
  await expect(page.getByRole("button", { name: /评论数/ })).toContainText("读取失败");
  await expect(monthly).not.toContainText("最近采集已读取");
  await screenshot(page, testInfo, "B-mixed-history-and-read-errors-1600-fixture.png");

  await monthly.click();
  const evidence = page.getByRole("region", { name: "月成交数据依据" });
  await expect(evidence.locator("dd").nth(1)).toHaveText("-");
  await expect(evidence).toContainText("CollectionRun ID");
  await expect(evidence).toContainText("#20");
  await expect(evidence).toContainText("100+");
  await expect(evidence).toContainText("#18");
  await expect(evidence.locator(".operating-evidence-record")).toHaveCount(2);
  await expect(monthly).toHaveAttribute("aria-expanded", "true");
  await screenshot(page, testInfo, "C-operating-data-evidence-1600-fixture.png");

  await page.getByRole("button", { name: "收起", exact: true }).click();
  await monthly.focus();
  await monthly.press("Enter");
  await expect(page.getByRole("region", { name: "月成交数据依据" })).toBeVisible();

  await page.getByRole("button", { name: /年成交件数/ }).click();
  const annual = page.getByRole("region", { name: "年成交件数数据依据" });
  await expect(annual).toContainText("仍在加载");
  await expect(annual).toContainText("CollectionRun ID");
  await expect(annual).toContainText("#20");
  await expect(evidence).toHaveCount(0);
  await page.getByRole("button", { name: "收起", exact: true }).click();
  await expect(page.locator(".operating-metric-evidence")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "查看数据依据" })).toHaveAttribute("aria-expanded", "false");

  for (const width of [1600, 1440, 1024]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator(".operating-metrics-panel")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow at ${width}px`).toBe(false);
    const trendColumns = await page.locator(".detail-trend-grid").evaluate(element => getComputedStyle(element).gridTemplateColumns.split(" ").length);
    expect(trendColumns, `trend columns at ${width}px`).toBe(2);
  }
});

test("historical field-only records, absent latest run, and conflicting same-run evidence stay explicit", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openDetail(page, "normal", fixture => {
    fixture.operating_metrics[1].latest_attempt = { ...fixture.operating_metrics[1].latest_attempt!, collection_run_id: 19 };
    fixture.operating_metrics[1].latest_valid = { ...fixture.operating_metrics[1].latest_valid!, collection_run_id: 19 };
    fixture.operating_metrics[2].latest_valid = { ...fixture.operating_metrics[2].latest_valid!, raw_value: "different" };
    fixture.operating_metrics[3].latest_attempt = { ...fixture.operating_metrics[3].latest_attempt!, status: "read_failed", raw_value: null, reason: "脱敏 Fixture 失败" };
    fixture.operating_metrics[3].latest_valid = null;
  });

  const historical = page.getByRole("button", { name: /月成交/ });
  await historical.click();
  const historicalEvidence = page.getByRole("region", { name: "月成交数据依据" });
  await expect(historicalEvidence).toContainText("最近字段记录（历史）");
  await expect(historicalEvidence.locator(".operating-evidence-record")).toHaveCount(1);
  await expect(historicalEvidence).not.toContainText("本次有效值");

  await page.getByRole("button", { name: /月代销/ }).click();
  const conflictingEvidence = page.getByRole("region", { name: "月代销数据依据" });
  await expect(conflictingEvidence.locator(".operating-evidence-record")).toHaveCount(2);
  await expect(conflictingEvidence).toContainText("12");
  await expect(conflictingEvidence).toContainText("different");

  await page.getByRole("button", { name: /年成交件数/ }).click();
  const failedEvidence = page.getByRole("region", { name: "年成交件数数据依据" });
  await expect(failedEvidence).toContainText("读取失败");
  await expect(failedEvidence).toContainText("脱敏 Fixture 失败");
  await expect(failedEvidence).toContainText("暂无有效值");
  await expect(failedEvidence.locator(".operating-evidence-record")).toHaveCount(1);

});

test("an absent latest run never labels an observed value as current", async ({ page }) => {
  await openDetail(page, "normal", fixture => { fixture.latest_collection_run = null; });
  await page.getByRole("button", { name: /月成交/ }).click();
  const evidence = page.getByRole("region", { name: "月成交数据依据" });
  await expect(evidence).toContainText("有效值记录");
  await expect(evidence).not.toContainText("本次有效值");
  await expect(evidence.locator(".operating-evidence-record")).toHaveCount(1);
});
