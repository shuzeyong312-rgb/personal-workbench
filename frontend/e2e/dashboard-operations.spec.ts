import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { installApiMock } from "./support/api-mock";

const evidence = resolve("../docs/qa/dashboard-operations");
const date = "2026-10-21";
const groups = Array.from({ length: 7 }, (_, index) => ({
  group_id: index + 1,
  group_name: ["便携暖手宝 · 主推款", "桌面加湿器 · 静音款", "随行保温杯 · 轻量款", "折叠风扇 · 桌面款", "充电夜灯 · 柔光款", "电热水袋 · 家用款", "迷你取暖器 · 陶瓷款"][index],
  own_product: { id: index + 100, offer_id: `80000${index}`, title: "我方商品 · 标准配置 / 多规格", shop_name: "工作台示例店铺", main_image_url: null },
  attention_level: index === 0 ? "重点关注" : "建议查看",
  changed_competitor_count: index === 0 ? 3 : 1,
  reasons: [{ reason_type: "price_decrease", display_text: index === 0 ? "3 家直接竞品降价，请进入组分析核对价格差距" : "1 家直接竞品调整价格", competitor_count: index === 0 ? 3 : 1, sku_count: null, direction: "price_decrease", event_level: "B", current_state_safe: true }],
  latest_change_at: `${date}T02:18:00Z`,
}));

async function setup(page: Page, scenario = "changes", batchStatus?: Record<string, unknown>) {
  const mock = await installApiMock(page, { competitors: [], activeMonitoredProducts: 18, batchStatus });
  await page.route("**/api/dashboard/group-attention", async route => {
    if (scenario === "attention-error") return route.fulfill({ status: 503, json: { message: "关注信息服务暂不可用" } });
    const changed = scenario === "changes" || scenario === "dashboard-error" || scenario === "long";
    await route.fulfill({ json: { date, kpis: { monitored_product_groups: scenario === "no-groups" ? 0 : 12, changed_product_groups_today: changed ? 7 : 0, changed_competitors_today: changed ? 9 : 0 }, groups: changed ? groups.map(g => scenario === "long" ? { ...g, group_name: g.group_name.repeat(8), own_product: { ...g.own_product, title: g.own_product.title.repeat(8) } } : g) : [] } });
  });
  await page.route("**/api/dashboard/today", route => {
    if (scenario.startsWith("dashboard-") && scenario.endsWith("error")) return route.fulfill({ status: 503, json: { message: "采集统计暂不可用" } });
    const success = ["uncollected", "failed", "no-groups"].includes(scenario) ? 0 : 18;
    const failed = ["failed", "partial"].includes(scenario) ? 3 : 0;
    return route.fulfill({ json: { date, stats: { active_monitored_products: 18, monitored_competitors: 16, changed_competitors: scenario === "changes" ? 9 : 0, change_events: 12, price_changed_competitors: 4, stock_changed_competitors: 2, sku_changed_competitors: 1, failed_collections: failed }, items: [], collection_summary: { last_collection_at: scenario === "uncollected" ? "2026-10-20T02:18:00Z" : success || failed ? `${date}T02:18:00Z` : null, success_runs: success, failed_runs: failed, average_duration_seconds: success || failed ? 28 : null }, trend_7d: Array.from({ length: 7 }, (_, i) => ({ date: `2026-10-${15 + i}`, price_changes: [2, 0, 3, 1, 4, 2, 6][i], stock_changes: i % 3, sku_changes: i % 2, failed_collections: 0 })) } });
  });
  await page.goto("/");
  if (page.viewportSize()!.width < 760) await page.getByRole("button", { name: "展开导航" }).click();
  await page.getByRole("button", { name: "竞品监控大屏", exact: true }).click();
  await expect(page.getByRole("heading", { name: "今日需要关注的商品组" })).toBeVisible();
  return mock;
}

async function capture(page: Page, name: string) {
  mkdirSync(evidence, { recursive: true });
  await page.evaluate(() => {
    const label = document.createElement("div"); label.id = "qa-fixture-label";
    label.textContent = "受控场景 · 非正式业务数据";
    Object.assign(label.style, { position: "fixed", bottom: "8px", left: "12px", zIndex: "9999", background: "#fff", color: "#626b78", padding: "4px 8px", border: "1px solid #dde1e6", font: "12px sans-serif" });
    document.body.append(label);
  });
  await page.screenshot({ path: resolve(evidence, `${name}.png`), fullPage: true });
  await page.locator("#qa-fixture-label").evaluate(el => el.remove());
}

test("dashboard daily workflow and screenshots", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const mock = await setup(page);
  await expect(page.locator(".dashboard-attention-card").first()).toBeVisible();
  await capture(page, process.env.DASHBOARD_BEFORE ? "before-changes-1440" : "after-changes-1440");
  if (!process.env.DASHBOARD_BEFORE) {
    await expect(page.locator(".dashboard-attention-card h3")).toHaveText(groups.slice(0, 5).map(g => g.group_name));
    await expect(page.locator(".dashboard-trend-chart")).not.toBeVisible();
    await page.getByRole("button", { name: "展开全部", exact: true }).click();
    await expect(page.locator(".dashboard-attention-card h3")).toHaveText(groups.map(g => g.group_name));
    await page.getByRole("button", { name: "收起", exact: true }).click();
    await expect(page.locator(".dashboard-attention-card")).toHaveCount(5);
    await page.locator(".dashboard-history summary").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".dashboard-trend-chart")).toBeVisible();
    await page.mouse.move(0, 0);
    await page.locator(".chart-hit-area").last().focus();
    await expect(page.locator(".dashboard-trend-tooltip")).toContainText("10/21");
    await capture(page, "after-history-expanded");
    await page.locator(".dashboard-history summary").click();
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator(".dashboard-page-header").scrollIntoViewIfNeeded();
      await capture(page, `after-changes-${width}`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator(".dashboard-attention-footer").scrollIntoViewIfNeeded();
    await capture(page, "after-changes-bottom-1440");
    await page.getByRole("button", { name: "查看全部商品组" }).click();
    await expect(page.getByRole("heading", { name: "竞品分组", exact: true })).toBeVisible();
  }
  await mock.expectNoUnexpectedApi();
});

for (const [scenario, title] of [
  ["unchanged", "今日暂无需要关注的竞争变化"],
  ["uncollected", "尚不能判断今日竞争变化"],
  ["failed", "暂无关注事件"],
  ["partial", "暂无关注事件，仍有采集异常"],
  ["no-groups", "先建立可监控的商品组"],
  ["dashboard-empty-error", "暂无关注事件，采集情况待确认"],
] as const) {
  test(`daily empty state: ${scenario}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    const mock = await setup(page, scenario);
    const empty = page.locator(".dashboard-attention-state");
    await expect(empty).toContainText(scenario === "failed" ? "尚不能判断今日竞争变化" : title);
    if (scenario === "uncollected") {
      await expect(page.locator(".dashboard-data-notice")).toContainText("今日尚无已完成采集记录");
      await expect(page.locator(".collection-summary-grid")).toContainText("2026年10月20日");
    }
    if (scenario === "failed") await expect(page.locator(".dashboard-data-notice")).toContainText("今日采集尚未成功");
    if (scenario === "unchanged") await expect(page.locator(".dashboard-data-notice")).toContainText("不代表所有监控商品均已采集");
    if (scenario === "dashboard-empty-error") {
      await expect(page.locator(".collection-summary-grid")).toContainText("暂不可用");
      await expect(page.locator(".collection-summary-grid")).not.toContainText("暂无采集记录");
    }
    await capture(page, `after-${scenario}`);
    if (["failed", "partial"].includes(scenario)) {
      await page.getByRole("button", { name: "查看采集记录" }).click();
      await expect(page.getByRole("heading", { name: "采集记录", exact: true })).toBeVisible();
    }
    if (scenario === "uncollected") {
      await page.getByRole("button", { name: "采集监控商品" }).click();
      await expect(page.locator(".collection-batch")).toContainText("最近批次完成");
    }
    await mock.expectNoUnexpectedApi();
  });
}

test("isolates errors and retries Attention without losing collection status", async ({ page }) => {
  const mock = await setup(page, "attention-error");
  await expect(page.locator(".dashboard-attention-error")).toBeVisible();
  await expect(page.locator(".collection-summary-grid")).toContainText("18");
  await capture(page, "after-attention-error");
  await page.route("**/api/dashboard/group-attention", route => route.fulfill({ json: { date, kpis: { monitored_product_groups: 12, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] } }));
  await page.locator(".dashboard-attention-error").getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.locator(".dashboard-attention-state")).toContainText("今日暂无需要关注的竞争变化");
  await mock.expectNoUnexpectedApi();
});

test("keeps Attention available when dashboard statistics fail", async ({ page }) => {
  const mock = await setup(page, "dashboard-error");
  await expect(page.locator(".dashboard-attention-card")).toHaveCount(5);
  await expect(page.locator(".collection-overview [role=alert]")).toBeVisible();
  await expect(page.getByRole("button", { name: "立即采集", exact: true })).toBeDisabled();
  await capture(page, "after-dashboard-error");
  await mock.expectNoUnexpectedApi();
});

test("batch controls pause, resume and end through the existing callbacks", async ({ page }) => {
  const mock = await setup(page, "changes", { status: "running", runner_active: true, browser_open: true, total: 9, completed: 3, succeeded: 3, failed: 0, remaining: 6, current_competitor_id: null });
  const overview = page.locator(".collection-overview");
  await overview.getByRole("button", { name: "暂停采集", exact: true }).click();
  await expect(overview.getByRole("button", { name: "继续采集", exact: true })).toBeVisible();
  await overview.getByRole("button", { name: "继续采集", exact: true }).click();
  await expect(overview.getByRole("button", { name: "暂停采集", exact: true })).toBeVisible();
  await overview.getByRole("button", { name: "结束采集", exact: true }).click();
  await expect(overview).toContainText("已结束");
  await mock.expectNoUnexpectedApi();
});

test("loading cannot masquerade as no records or no changes", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/dashboard/**", async route => {
    await pending;
    await route.fallback();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "竞品监控大屏", exact: true }).click();
  await expect(page.locator(".dashboard-attention-state")).toContainText("正在加载");
  await expect(page.locator(".collection-summary-grid")).toContainText("加载中…");
  await expect(page.locator("main")).not.toContainText("今日暂无需要关注的竞争变化");
  await capture(page, "after-loading");
  release();
  await expect(page.locator(".dashboard-attention-state")).toContainText("先建立可监控的商品组");
  await mock.expectNoUnexpectedApi();
});

for (const status of ["running", "paused", "resting", "cooling_down", "verification_required", "completed"] as const) {
  test(`authoritative batch state: ${status}`, async ({ page }) => {
    const mock = await setup(page, "uncollected", { status, runner_active: status !== "completed", browser_open: status === "running", total: 9, completed: 3, succeeded: 0, failed: 3, remaining: 6, current_competitor_id: null, resting_remaining_seconds: status === "resting" ? 17 : 0, cooldown_remaining_seconds: status === "cooling_down" ? 120 : 0, auto_resume_attempt: 1, auto_resume_max: 2 });
    const overview = page.locator(".collection-overview");
    if (status !== "completed") await expect(page.getByRole("button", { name: "立即采集", exact: true })).toBeDisabled();
    if (status === "paused") await expect(overview.getByRole("button", { name: "继续采集" })).toBeVisible();
    if (["running", "resting", "cooling_down"].includes(status)) await expect(overview.getByRole("button", { name: "暂停采集" })).toBeVisible();
    if (status !== "completed") await expect(overview.getByRole("button", { name: "结束采集" })).toBeVisible();
    if (status === "resting") await expect(overview).toContainText("17 秒");
    if (status === "completed") {
      await expect(overview.locator(".overview-status-warning")).toContainText("最近批次完成");
      await expect(overview.locator(".collection-batch")).toContainText("成功 0 · 失败 3");
    }
    await capture(page, `after-batch-${status}`);
    await mock.expectNoUnexpectedApi();
  });
}

for (const width of [1280, 390]) {
  test(`long content and keyboard at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const mock = await setup(page, "long");
    await expect(page.locator(".dashboard-attention-card")).toHaveCount(5);
    expect(await page.locator("main").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: "进入组分析", exact: true }).first().focus();
    await expect(page.getByRole("button", { name: "进入组分析", exact: true }).first()).toBeFocused();
    await capture(page, `after-long-${width}`);
    await mock.expectNoUnexpectedApi();
  });
}
