import { isValidElement, type ReactNode } from "react";
import { fileURLToPath } from "node:url";

import { chromium, expect as playwrightExpect, type Route } from "@playwright/test";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { expect, test, vi } from "vitest";

import { competitorPageSize, formatCollectionRunStatus, getBatchRefreshNotice, paginateCompetitors, updatePageSelection } from "./App";
import { CurrentBatchCard } from "./App";

import { addCompetitorsSequentially, AddDialog, applyInitialGroupFilter, BatchGroupAssignmentDialog, BatchLifecycleDialog, BatchState, Change, Competitor, CompetitorDetail, CompetitorFilters, CompetitorGroup, CompetitorGroupMetrics, CompetitorGroupSummary, CollectionTasksPage, ConfirmDialog, countActiveCompetitors, DashboardData, DashboardPage, DashboardTrendChart, defaultCompetitorFilters, DetailPage, DETAIL_GALLERY_SCROLL_STEP, filterCompetitors, formatChange, formatChangeMagnitude, formatDashboardTrendTooltip, formatDate, formatDetailPriceDisplay, formatPriceChangeMagnitude, formatPriceChangeTransition, formatPriceTick, formatTrendTooltip, formatStockDisplay, formatDuration, formatGroupLatestChange, formatGroupPriceRange, formatGroupDetailLatestChange, formatGroupProductFreshness, formatLatestChange, getAddFailureReason, getCollectionErrorMessage, getCollectionFailureMessage, getCollectionRequestErrorMessage, getCompetitorGroupLabel, getDetailGallery, getGalleryScrollState, getGroupAssignmentErrorMessage, getGroupFeedbackClass, getGroupNameErrorMessage, getLifecycleErrorMessage, getResponseStatus, GroupAssignmentDialog, GroupDeleteDialog, GroupNameDialog, GroupPage, GroupDetailPage, sortGroupOffers, HomePage, formatGroupUpdateTime, getGroupDifferenceLabels, getNonzeroGroupActionDomains, hideDetailGalleryThumbnail, idleBatchState, isCurrentDetailRequest, ListPage, mergeCompetitorUrlText, parseCompetitorUrls, reconcileSelectedIds, scrollDetailGallery, Sidebar, StatusBadge, WorkspacePlaceholderPage, updateCompetitorGroup, OwnProductDialog, buildDashboardTrendChartPoints, buildDashboardTrendScale, buildPriceChartPoints, buildPriceChartScale, buildStockChartPoints, buildStockChartScale, buildTrendHitAreas } from "./App";

const competitor: Competitor = {
  id: 1,
  platform: "1688",
  offer_id: "123456789",
  url: "https://detail.1688.com/offer/123456789.html",
  group_id: null,
  group_role: "competitor",
  ownership: "competitor",
  title: null,
  shop_name: null,
  main_image_url: null,
  status: "unknown",
  is_active: true,
  created_at: "2026-09-19T10:00:00Z",
  last_collected_at: null,
  latest_snapshot: null,
  latest_change: null,
};

const noop = () => undefined;
const mainClassTokens = (html: string) => html.match(/<main\b[^>]*\bclass="([^"]*)"/)?.[1].split(/\s+/).filter(Boolean) ?? [];
const listProps = { groups: [] as CompetitorGroup[] };
const group: CompetitorGroup = { id: 1, name: "暖手宝", created_at: "2026-09-20T10:00:00Z" };
const groupMetrics: CompetitorGroupMetrics = { competitor_count: 3, active_count: 2, price_min: "34.00", price_max: "40.00", changed_competitors_today: 2, last_change_at: "2026-09-21T10:35:00Z" };
const groupSummary: CompetitorGroupSummary = { ...group, ...groupMetrics, own_product: null };
const latestChange = (overrides: Partial<Change> = {}): Change => ({
  id: 1,
  snapshot_id: 2,
  collection_run_id: null,
  change_type: "title_changed",
  entity_key: null,
  sku_name: null,
  old_value: null,
  new_value: null,
  delta_value: null,
  delta_rate: null,
  detected_at: "2026-09-20T10:00:00Z",
  ...overrides,
});
const groupProduct = (overrides: Partial<import("./App").GroupProductFacts> = {}): import("./App").GroupProductFacts => ({
  id: 10, role: "competitor", platform: "1688", offer_id: "100", url: "https://detail.1688.com/offer/100.html", title: "竞品商品", shop_name: "测试店铺", main_image_url: null, status: "active", is_active: true, last_collected_at: "2026-09-22T10:00:00Z",
  latest_snapshot: { id: 1, captured_at: "2026-09-22T10:00:00Z", price_min: "20.00", price_max: "30.00", min_order_quantity: 2, sku_count: 3, total_stock: 0 }, latest_change: null, ...overrides,
});
const emptyEventPage: import("./App").GroupEventPage = { items: [], has_more: false, next_cursor: null, range: "7", mode: "important", limit: 20, window_start: "2026-09-16T16:00:00", window_end: "2026-09-23T16:00:00", through_event_id: 2, important_offer_ids: [10] };
const testPosition: import("./App").MetricPosition = { default_direction: "asc", group_count: 2, eligible_count: 2, offers: { 7: { eligible: true, reason: null, sort_value: 2, rank_asc: 2, rank_desc: 1 }, 10: { eligible: true, reason: null, sort_value: 1, rank_asc: 1, rank_desc: 2 } } };
const groupDetailData: import("./App").GroupDetailData = {
  position: { display_price_min: testPosition, min_order_quantity: testPosition, sku_count: { ...testPosition, default_direction: "desc" }, total_stock: { ...testPosition, default_direction: "desc" } }, event_page: emptyEventPage,
  range_days: 7, group, own_product: groupProduct({ id: 7, role: "own", title: "自有商品", offer_id: "700" }),
  summary: { direct_competitor_count: 1, monitored_competitor_count: 1, changed_competitors_today: 1, price_lower_than_own: { matched_count: 1, comparable_count: 1 }, moq_lower_than_own: { matched_count: 0, comparable_count: 0 }, sku_more_than_own: { matched_count: 0, comparable_count: 1 }, stock_higher_than_own: { matched_count: 0, comparable_count: 0 } },
  competitors: [{ ...groupProduct(), comparison: { price: "lower", min_order_quantity: "lower", sku_count: "more", total_stock: "unknown" } }],
  today: { event_pagination: { ...emptyEventPage, range: "today", mode: "all" }, important_offer_ids: [10], own_event_count: 1, competitor_event_count: 2, changed_competitor_count: 1, events: [{ ...latestChange(), snapshot_id: 2, collection_run_id: null, sku_name: null, competitor_id: 7, role: "own", title: "自有商品", offer_id: "700" }, { ...latestChange({ id: 2 }), snapshot_id: 2, collection_run_id: null, sku_name: null, competitor_id: 10, role: "competitor", title: "竞品商品", offer_id: "100" }] },
  action_window: { important_offer_ids: [10], days: 7, own_event_count: 1, competitor_event_count: 2, competitors: [{ competitor_id: 10, title: "竞品商品", offer_id: "100", event_count: 2, latest_change_at: "2026-09-22T10:00:00Z", domain_counts: { price: 1, stock: 1, sku: 0, min_order_quantity: 0, lifecycle: 0, title: 0, main_image: 0 } }] },
};

const filterCompetitorFixtures: Competitor[] = [
  { ...competitor, id: 10, offer_id: "1081895898799", title: "暖手宝 Pro", shop_name: "家居旗舰店", status: "active", last_collected_at: "2026-09-20T10:00:00Z" },
  { ...competitor, id: 11, offer_id: "2087654321", title: "桌面风扇", shop_name: "电器店", status: "offline", is_active: false },
  { ...competitor, id: 12, offer_id: "3087654321", title: null, shop_name: null, status: "unknown" },
];
const groupedFilterFixtures = [
  { ...filterCompetitorFixtures[0], group_id: 1 },
  { ...filterCompetitorFixtures[1], group_id: null },
  { ...filterCompetitorFixtures[2], group_id: 2 },
];
const filterGroups: CompetitorGroup[] = [
  { id: 1, name: "家居组", created_at: "2026-09-20T10:00:00Z" },
  { id: 2, name: "电器组", created_at: "2026-09-20T10:00:00Z" },
];

const filter = (overrides: Partial<CompetitorFilters>): CompetitorFilters => ({ ...defaultCompetitorFilters, ...overrides });
const filteredIds = (filters: CompetitorFilters) => filterCompetitors(filterCompetitorFixtures, filters).map((item) => item.id);
const makeBatchState = (status: BatchState["status"], overrides: Partial<BatchState> = {}): BatchState => ({
  status,
  outcome_code: null,
  total: 1,
  completed: 0,
  succeeded: 0,
  failed: 0,
  remaining: 1,
  verification_required: 0,
  operating_metrics_counts: { not_attempted: 0, success: 0, partial: 0, no_values: 0, failed: 0, blocked: 0 },
  current_competitor_id: 1,
  browser_open: status === "running",
  runner_active: status === "running" || status === "cooling_down",
  auto_resume_attempt: status === "cooling_down" ? 1 : 0,
  auto_resume_max: 2,
  cooldown_remaining_seconds: 0,
  resting_remaining_seconds: 0,
  items: [],
  ...overrides,
});

const monitoringSettings = { item_interval_seconds: 5, continuous_collection_count: 10, batch_rest_seconds: 120, verification_cooldown_seconds: 600, auto_resume_max: 2, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "09:30", auto_collection_missed_policy: "catch_up" };

async function openSettingsScenario(options: { ownGet: number; monitoringGet: number; ownPut?: number; monitoringPut?: number }) {
  const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { host: "127.0.0.1", port: 0 }, clearScreen: false });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", async route => {
    const key = `${route.request().method()} ${new URL(route.request().url()).pathname}`;
    if (key === "GET /api/dashboard/today") return json(route, { date: "2026-10-06", stats: { monitored_competitors: 0, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] });
    if (key === "GET /api/dashboard/group-attention") return json(route, { date: "2026-10-06", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] });
    if (key === "GET /api/competitors/collect-batch/status") return json(route, makeBatchState("idle"));
    if (key === "GET /api/settings/own-shop-name") return json(route, options.ownGet === 200 ? { configured: true, own_shop_name: "测试店铺" } : { message: "基础设置加载失败" }, options.ownGet);
    if (key === "PUT /api/settings/own-shop-name") return json(route, options.ownPut === 200 || options.ownPut === undefined ? { configured: true, own_shop_name: "更新店铺" } : { message: "基础设置保存失败" }, options.ownPut ?? 200);
    if (key === "GET /api/settings/competitor-monitoring") return json(route, options.monitoringGet === 200 ? monitoringSettings : { message: "竞品监控加载失败" }, options.monitoringGet);
    if (key === "PUT /api/settings/competitor-monitoring") return json(route, options.monitoringPut === 200 || options.monitoringPut === undefined ? monitoringSettings : { message: "竞品监控保存失败" }, options.monitoringPut ?? 200);
    return route.abort("blockedbyclient");
  });
  const baseUrl = server.resolvedUrls?.local[0];
  if (!baseUrl) throw new Error("Vite test server did not expose a local URL");
  await page.goto(baseUrl);
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  return { page, close: async () => { await context.close(); await browser.close(); await server.close(); } };
}

test("basic-settings load failure does not block competitor-monitoring settings", async () => {
  const scenario = await openSettingsScenario({ ownGet: 500, monitoringGet: 200 });
  try {
    await playwrightExpect(scenario.page.getByText("设置加载失败", { exact: true })).toBeVisible();
    await scenario.page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^竞品监控/ }).click();
    await playwrightExpect(scenario.page.getByLabel("单商品采集间隔")).toHaveValue("5");
  } finally { await scenario.close(); }
});

test("basic-settings save failure does not block competitor-monitoring settings", async () => {
  const scenario = await openSettingsScenario({ ownGet: 200, monitoringGet: 200, ownPut: 500 });
  try {
    await playwrightExpect(scenario.page.getByLabel("我方店铺名称")).toHaveValue("测试店铺");
    await scenario.page.getByRole("button", { name: "保存设置", exact: true }).click();
    await playwrightExpect(scenario.page.getByRole("alert")).toContainText("基础设置保存失败");
    await scenario.page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^竞品监控/ }).click();
    await playwrightExpect(scenario.page.getByLabel("单商品采集间隔")).toHaveValue("5");
  } finally { await scenario.close(); }
});

test("competitor-monitoring load failure does not replace the loaded basic settings", async () => {
  const scenario = await openSettingsScenario({ ownGet: 200, monitoringGet: 500 });
  try {
    await playwrightExpect(scenario.page.getByLabel("我方店铺名称")).toHaveValue("测试店铺");
    await scenario.page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^竞品监控/ }).click();
    await playwrightExpect(scenario.page.getByText("竞品监控设置加载失败", { exact: true })).toBeVisible();
    await scenario.page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^基础设置/ }).click();
    await playwrightExpect(scenario.page.getByLabel("我方店铺名称")).toHaveValue("测试店铺");
  } finally { await scenario.close(); }
});

test("competitor-monitoring save failure does not replace the loaded basic settings", async () => {
  const scenario = await openSettingsScenario({ ownGet: 200, monitoringGet: 200, monitoringPut: 500 });
  try {
    await scenario.page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^竞品监控/ }).click();
    await playwrightExpect(scenario.page.getByLabel("单商品采集间隔")).toHaveValue("5");
    await scenario.page.getByRole("button", { name: "保存设置", exact: true }).click();
    await playwrightExpect(scenario.page.getByRole("alert")).toContainText("竞品监控保存失败");
    await scenario.page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^基础设置/ }).click();
    await playwrightExpect(scenario.page.getByLabel("我方店铺名称")).toHaveValue("测试店铺");
  } finally { await scenario.close(); }
});

test("paginates eleven competitors with a fixed page size and clamps invalid pages", () => {
  const items = Array.from({ length: 11 }, (_, index) => ({ ...competitor, id: index + 1, offer_id: String(index + 1) }));
  expect(competitorPageSize).toBe(10);
  expect(paginateCompetitors(items, 1)).toMatchObject({ page: 1, totalPages: 2, items: items.slice(0, 10) });
  expect(paginateCompetitors(items, 2)).toMatchObject({ page: 2, totalPages: 2, items: [items[10]] });
  expect(paginateCompetitors(items, 3)).toMatchObject({ page: 2, totalPages: 2, items: [items[10]] });
  expect(paginateCompetitors([], 3)).toMatchObject({ page: 1, totalPages: 1, items: [] });
});

test("current-page select-all preserves selections on other pages", () => {
  expect(updatePageSelection(new Set([1, 11]), [2, 3], true)).toEqual(new Set([1, 2, 3, 11]));
  expect(updatePageSelection(new Set([1, 2, 3, 11]), [2, 3], false)).toEqual(new Set([1, 11]));
});

test("filters by title", () => {
  expect(filteredIds(filter({ search: "暖手宝" }))).toEqual([10]);
});

test("filters by partial offerId", () => {
  expect(filteredIds(filter({ search: "8189" }))).toEqual([10]);
});

test("filters by shop name", () => {
  expect(filteredIds(filter({ search: "旗舰店" }))).toEqual([10]);
});

test("trims search input and matches title case-insensitively", () => {
  expect(filteredIds(filter({ search: "  暖手宝 pro  " }))).toEqual([10]);
});

test.each([
  ["active", [10]],
  ["offline", [11]],
  ["unknown", [12]],
] as const)("filters product status %s", (status, expected) => {
  expect(filteredIds(filter({ status }))).toEqual(expected);
});

test.each([
  ["collected", [10]],
  ["not_collected", [11, 12]],
] as const)("filters collection status %s using last_collected_at only", (collectionStatus, expected) => {
  expect(filteredIds(filter({ collectionStatus }))).toEqual(expected);
});

test("combines search, product status and collection status with AND", () => {
  expect(filteredIds(filter({ search: "暖手宝", status: "active", collectionStatus: "collected" }))).toEqual([10]);
  expect(filteredIds(filter({ search: "暖手宝", status: "offline", collectionStatus: "collected" }))).toEqual([]);
});

test("filters by a specified competitor group", () => {
  expect(filterCompetitors(groupedFilterFixtures, filter({ groupId: 2 })).map((item) => item.id)).toEqual([12]);
});

test("filters ungrouped competitors", () => {
  expect(filterCompetitors(groupedFilterFixtures, filter({ groupId: "unassigned" })).map((item) => item.id)).toEqual([11]);
});

test("all competitor groups removes the group restriction", () => {
  expect(filterCompetitors(groupedFilterFixtures, filter({ groupId: "all" })).map((item) => item.id)).toEqual([10, 11, 12]);
});

test("combines all four filter conditions with AND", () => {
  expect(filterCompetitors(groupedFilterFixtures, filter({ search: "暖手宝", status: "active", collectionStatus: "collected", groupId: 1 })).map((item) => item.id)).toEqual([10]);
  expect(filterCompetitors(groupedFilterFixtures, filter({ search: "暖手宝", status: "active", collectionStatus: "collected", groupId: 2 })).map((item) => item.id)).toEqual([]);
});

test("handles null searchable fields safely", () => {
  expect(filteredIds(filter({ search: "308765" }))).toEqual([12]);
  expect(filteredIds(filter({ search: "不存在" }))).toEqual([]);
});

test("keeps the source list unchanged before filters are applied", () => {
  expect(filterCompetitors(filterCompetitorFixtures, defaultCompetitorFilters)).toHaveLength(3);
  expect(filterCompetitorFixtures).toHaveLength(3);
});

test("applies the complete filter set after submission", () => {
  const editing = filter({ search: "  家居  ", status: "active", collectionStatus: "collected" });
  expect(filteredIds(editing)).toEqual([10]);
});

test("reset restores all competitors", () => {
  expect(filteredIds(filter({ search: "暖手宝", status: "active" }))).toEqual([10]);
  expect(filteredIds(defaultCompetitorFilters)).toEqual([10, 11, 12]);
});

test("filtered result counts provide the list statistics", () => {
  const filtered = filterCompetitors(filterCompetitorFixtures, filter({ search: "暖手宝" }));
  const collected = filtered.filter((item) => item.last_collected_at !== null).length;
  expect({ total: filtered.length, collected, notCollected: filtered.length - collected }).toEqual({ total: 1, collected: 1, notCollected: 0 });
});

test("select-all candidates include every filtered row", () => {
  const filtered = filterCompetitors(filterCompetitorFixtures, filter({ search: "店" }));
  expect(filtered.map((item) => item.id)).toEqual([10, 11]);
});

test("reloaded data can reuse the same applied filters", () => {
  const applied = filter({ search: "暖手宝", status: "active" });
  const refreshed = [{ ...filterCompetitorFixtures[0], last_collected_at: null }, filterCompetitorFixtures[1]];
  expect(filterCompetitors(refreshed, applied).map((item) => item.id)).toEqual([10]);
});

test("real-time filtering keeps visible active selections and removes hidden selections", () => {
  expect(reconcileSelectedIds(new Set([10, 11, 12]), [10, 12])).toEqual(new Set([10, 12]));
  expect(reconcileSelectedIds(new Set([10, 11]), [10])).toEqual(new Set([10]));
});

test("renders an accessible search input without a duplicate external label", () => {
  const html = renderToStaticMarkup(<ListPage {...listProps} groups={filterGroups} competitors={filterCompetitorFixtures} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain('id="search"');
  expect(html).toContain('aria-label="搜索商品名称 / offerId / 店铺"');
  expect(html).toContain('placeholder="搜索商品名称 / offerId / 店铺"');
  expect(html).not.toContain('<label for="search">');
  expect(html).toContain('<button type="button" class="text-button">重置</button>');
  expect(html).toContain('value="active"');
  expect(html).toContain('value="offline"');
  expect(html).toContain('value="unknown"');
  expect(html).toContain('value="collected"');
  expect(html).toContain('value="not_collected"');
  expect(html).toContain("家居组");
  expect(html).toContain("电器组");
  expect(html).not.toContain('<button type="submit"');
  expect(html).not.toContain(">筛选<");
  expect(html).not.toContain("搜索与筛选暂未开放");
});

test("renders filtered-result empty state separately from system empty state", () => {
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={filterCompetitorFixtures} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("筛选");
  expect(renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="ready" error={null} onRetry={noop} onAdd={noop} />)).toContain("还没有添加竞品");
});

test("keeps all-active batch count independent from the filtered result", () => {
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={filterCompetitorFixtures} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(countActiveCompetitors(filterCompetitorFixtures)).toBe(2);
  expect(html).toContain("批量操作（0）");
});

test.each([
  [true, undefined, "success"],
  [false, "invalid_competitor_url", "invalid"],
  [false, "competitor_already_exists", "duplicate"],
] as const)("maps API result to %s UI state", (ok, code, expected) => {
  expect(getResponseStatus(ok, code)).toBe(expected);
});

test.each([
  ["https://detail.1688.com/offer/123.html", ["https://detail.1688.com/offer/123.html"]],
  [" A \r\n\r\n B \n A ", ["A", "B"]],
] as const)("parses one URL per line, trims blank lines, and de-duplicates in order", (value, expected) => {
  expect(parseCompetitorUrls(value)).toEqual(expected);
});

test("submits each URL sequentially with the same group", async () => {
  const calls: { url: string; groupId: number | null }[] = [];
  const progress: number[] = [];
  const result = await addCompetitorsSequentially(["A", "B", "C"], 19, async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as { url: string; group_id: number | null };
    calls.push({ url: body.url, groupId: body.group_id });
    return { ok: true, json: async () => ({}) } as Response;
  }, (completed) => progress.push(completed));
  expect(result).toEqual({ succeeded: ["A", "B", "C"], failures: [] });
  expect(calls).toEqual([{ url: "A", groupId: 19 }, { url: "B", groupId: 19 }, { url: "C", groupId: 19 }]);
  expect(progress).toEqual([1, 2, 3]);
});

test("continues after one URL fails and retains failure reasons", async () => {
  const result = await addCompetitorsSequentially(["A", "B", "C", "D"], null, async (_input, init) => {
    const url = (JSON.parse(String(init?.body)) as { url: string }).url;
    const code = url === "B" ? "competitor_already_exists" : url === "C" ? "invalid_competitor_url" : undefined;
    return { ok: !code, json: async () => ({ code }) } as Response;
  });
  expect(result.succeeded).toEqual(["A", "D"]);
  expect(result.failures).toEqual([
    { url: "B", code: "competitor_already_exists", reason: "已存在" },
    { url: "C", code: "invalid_competitor_url", reason: "链接格式无效" },
  ]);
  expect(getAddFailureReason("competitor_group_not_found")).toBe("竞品组不存在");
});

test("preserves network and HTTP error categories without stopping", async () => {
  const result = await addCompetitorsSequentially(["A", "B"], null, async (_input, init) => {
    const url = (JSON.parse(String(init?.body)) as { url: string }).url;
    if (url === "A") throw new Error("offline");
    return { ok: false, json: async () => ({}) } as Response;
  });
  expect(result.succeeded).toEqual([]);
  expect(result.failures.map(({ url, code }) => ({ url, code }))).toEqual([{ url: "A", code: "network-error" }, { url: "B", code: "server-error" }]);
});

test.each([
  ["own_shop_name_not_configured", "own_shop_name_not_configured"],
  ["collection_in_progress", "collection_in_progress"],
  ["competitor_already_exists", "competitor_already_exists"],
  ["competitor_group_not_found", "competitor_group_not_found"],
  ["own_product_already_bound", "own_product_already_bound"],
  ["1688_login_required", "1688_login_required"],
  ["1688_verification_required", "1688_verification_required"],
  ["collection_timeout", "collection_timeout"],
  ["collection_parse_failed", "collection_parse_failed"],
  ["collection_save_failed", "collection_save_failed"],
] as const)("keeps add error code %s instead of collapsing it", async (backendCode, expectedCode) => {
  const result = await addCompetitorsSequentially(["A"], null, async () => ({
    ok: false,
    status: 409,
    json: async () => ({ code: backendCode }),
  } as Response));
  expect(result.failures[0].code).toBe(expectedCode);
});

test("renders loading, empty, error and normal list states", () => {
  const competitorLoading = renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="loading" error={null} onRetry={noop} onAdd={noop} />);
  expect(competitorLoading).toContain("正在加载竞品列表");
  const ownLoading = renderToStaticMarkup(<ListPage {...listProps} ownership="self" competitors={[]} status="loading" error={null} onRetry={noop} onAdd={noop} />);
  expect(ownLoading).toContain("正在加载我方商品");
  expect(ownLoading).not.toContain("正在加载竞品列表");
  expect(renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="ready" error={null} onRetry={noop} onAdd={noop} />)).toContain("还没有添加竞品");
  expect(renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="error" error="请求失败" onRetry={noop} onAdd={noop} />)).toContain("重试");
  const normal = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(normal).toContain("未采集");
  expect(normal).toContain("123456789");
  expect(normal).toContain("查看 1688 商品");
  expect(normal).toContain("暂无变化记录");
  expect(normal).toContain("批量操作（0）");
  expect(normal).not.toContain("立即采集");
  expect(normal).not.toContain("采集选中");
  expect(normal).not.toContain("采集全部监控中");
  expect(normal).toContain("全选当前页全部商品");
  expect(normal).toContain("监控中");
  expect(normal).not.toContain("添加监控商品");
  expect(normal).toContain("共 1 个竞品");
  const ownNormal = renderToStaticMarkup(<ListPage {...listProps} ownership="self" competitors={[competitor]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(ownNormal).toContain("共 1 个我方商品");
  expect(ownNormal).not.toContain("共 1 个竞品");
});

test("removes collection actions from the own-product batch menu", () => {
  const html = renderToStaticMarkup(<ListPage {...listProps} ownership="self" competitors={[competitor]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).not.toContain("采集选中");
  expect(html).not.toContain("采集全部监控中");
});

test("uses own-product wording for the own-product list summary and empty state", () => {
  const originalFilters = { ...defaultCompetitorFilters };
  defaultCompetitorFilters.search = "不存在的我方商品";
  try {
    const filtered = renderToStaticMarkup(<ListPage {...listProps} ownership="self" competitors={[competitor]} status="ready" error={null} onRetry={noop} />);
    expect(filtered).toContain("没有找到符合条件的我方商品");
    expect(filtered).not.toContain("没有找到符合条件的竞品");
  } finally {
    Object.assign(defaultCompetitorFilters, originalFilters);
  }
  const empty = renderToStaticMarkup(<ListPage {...listProps} ownership="self" competitors={[]} status="ready" error={null} onRetry={noop} />);
  expect(empty).toContain("共 0 个我方商品");
  expect(empty).toContain("还没有我方商品");
  expect(empty).not.toContain("还没有添加竞品");
});

test.each([
  ["unknown", "状态未知"],
  ["active", "在售"],
  ["offline", "已下架"],
] as const)("maps product status %s to %s", (status, label) => {
  const html = renderToStaticMarkup(<StatusBadge status={status} />);
  expect(html).toContain(label);
  expect(html).not.toContain("未采集");
});

test("renders product status badges as one-line labels", () => {
  const html = renderToStaticMarkup(<StatusBadge status="offline" />);
  expect(html).toBe('<span class="status-badge status-offline">已下架</span>');
});

test("list keeps lifecycle actions out of the row", () => {
  const inactive = { ...competitor, is_active: false, title: "已停止商品" };
  const list = renderToStaticMarkup(<ListPage {...listProps} competitors={[inactive]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(list).toContain("已停止");
  expect(list).toContain(">详情</button>");
  expect(list).not.toContain("更多");
  expect(list).not.toContain("删除竞品");
  expect(list).not.toMatch(/aria-label="选择 已停止商品"[^>]*disabled=""/);
});

test("renders current-page selection counts and inactive checkbox semantics", () => {
  const second = { ...competitor, id: 2, offer_id: "987654321" };
  const inactive = { ...competitor, id: 3, is_active: false, title: "已停止商品" };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor, second, inactive]} selectedIds={new Set([competitor.id])} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("批量操作（1）");
  expect(html).not.toMatch(/aria-label="选择 已停止商品"[^>]*disabled=""/);
  expect(html).toContain("checked=\"\"");
  expect(html).not.toContain("立即采集");
});

test("keeps product and monitoring status in separate list columns", () => {
  const active = { ...competitor, id: 2, status: "active" as const, title: "在售商品" };
  const offline = { ...competitor, id: 3, status: "offline" as const, is_active: false, title: "下架商品" };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[active, offline]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("商品状态");
  expect(html).toContain("监控状态");
  expect(html).toContain("在售");
  expect(html).toContain("已下架");
  expect(html).toContain("监控中");
  expect(html).toContain("已停止");
  expect((html.match(/<th(?:\s|>)/g) ?? [])).toHaveLength(11);
  expect((html.match(/<td(?:\s|>)/g) ?? [])).toHaveLength(22);
});

test("renders completed and verification batch states", () => {
  const completed = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} batchState={{ ...idleBatchState, status: "completed", total: 1, completed: 1, succeeded: 1 }} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(completed).toContain("采集完成：成功 1，失败 0");
  const verification = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} batchState={{ ...idleBatchState, status: "verification_required", total: 2, completed: 1, remaining: 1, verification_required: 1, browser_open: true, runner_active: true }} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(verification).toContain("1688 需要人工验证，本次采集已停止");
  expect(verification).toContain("关闭浏览器后可重新发起采集");
});

test("renders cooling batch state from backend countdown and keeps controls busy", () => {
  const cooling: BatchState = {
    ...idleBatchState,
    status: "cooling_down",
    total: 3,
    completed: 1,
    remaining: 2,
    auto_resume_attempt: 1,
    auto_resume_max: 2,
    cooldown_remaining_seconds: 73,
    runner_active: true,
  };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} batchState={cooling} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("1688 验证已触发，浏览器已自动关闭");
  expect(html).toContain("73 秒");
  expect(html).toContain("自动恢复 1/2");
  expect(html).toContain("已完成 1 / 3，剩余 2");
  expect((html.match(/type="checkbox"[^>]*disabled=""/g) ?? [])).toHaveLength(2);
  expect(html).not.toContain("立即继续");
});

test("renders cooling state in dashboard collection overview", () => {
  const cooling: BatchState = {
    ...idleBatchState,
    status: "cooling_down",
    total: 3,
    completed: 1,
    remaining: 2,
    auto_resume_attempt: 2,
    auto_resume_max: 2,
    cooldown_remaining_seconds: 9,
    runner_active: true,
  };
  const html = renderDashboard({ batchState: cooling });
  expect(html).toContain("冷却中");
  expect(html).toContain("9 秒");
  expect(html).toContain("自动恢复 2/2");
});

test("renders resting state in dashboard collection overview and preserves idle", () => {
  const resting = renderDashboard({ batchState: { ...idleBatchState, status: "resting", total: 3, completed: 1, remaining: 2, resting_remaining_seconds: 17, runner_active: true } });
  expect(resting).not.toContain("当前无采集任务");
  expect(resting).toContain('class="overview-status overview-status-running">计划休息</span>');
  expect(resting).toContain("计划休息中");
  expect(resting).toContain("休息剩余 17 秒 · 已完成 1 / 3 · 剩余 2");
  expect(resting).toContain('role="progressbar"');

  const idle = renderDashboard({ batchState: idleBatchState });
  expect(idle).toContain("当前无采集任务");
  expect(idle).toContain("今日采集统计仍会保留");
});

test("uses confirmation dialogs for stop and permanent delete", () => {
  const stop = renderToStaticMarkup(<ConfirmDialog action="stop" competitor={competitor} submitting={false} error={null} onClose={noop} onConfirm={noop} />);
  expect(stop).toContain("停止监控");
  expect(stop).toContain("历史数据会保留");
  const deleted = renderToStaticMarkup(<ConfirmDialog action="delete" competitor={{ ...competitor, title: "测试商品" }} submitting={false} error={null} onClose={noop} onConfirm={noop} />);
  expect(deleted).toContain("永久删除竞品");
  expect(deleted).toContain("历史快照、SKU、变化记录和采集记录都会永久删除");
  expect(deleted).toContain("测试商品");
  expect(deleted).toContain("确认删除");
});

test("shows readable lifecycle request failures", () => {
  expect(getLifecycleErrorMessage("competitor_delete_failed")).toBe("竞品删除失败，请稍后重试");
  expect(getLifecycleErrorMessage("competitor_delete_failed", "删除失败，请稍后再试")).toBe("删除失败，请稍后再试");
  expect(getLifecycleErrorMessage("competitor_delete_failed", "<html>traceback</html>")).toBe("竞品删除失败，请稍后重试");
});

test("renders real snapshot price and SKU values", () => {
  const collected = { ...competitor, latest_snapshot: { price_min: "40.00", price_max: "40.00", sku_count: 3 } };
  const range = { ...competitor, id: 2, latest_snapshot: { price_min: "40.00", price_max: "45.00", sku_count: 0 } };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[collected, range]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("¥40.00");
  expect(html).toContain("¥40.00 ~ ¥45.00");
  expect(html).toContain(">3<");
  expect(html).toContain(">0<");
});

test.each([
  [latestChange({ change_type: "price_increase", old_value: "40.00", new_value: "45.00" }), "商品涨价 40.00 → 45.00"],
  [latestChange({ change_type: "price_decrease", old_value: "45.00", new_value: "40.00" }), "商品降价 45.00 → 40.00"],
  [latestChange({ change_type: "price_decrease", entity_key: "sku-1", sku_name: "红色", old_value: "38.00", new_value: "35.00" }), "红色 · SKU 降价 38.00 → 35.00"],
  [latestChange({ change_type: "sku_added", new_value: "红色" }), "新增 SKU：红色"],
  [latestChange({ change_type: "sku_removed", old_value: "蓝色" }), "移除 SKU：蓝色"],
  [latestChange({ change_type: "stock_changed", old_value: "10", new_value: "20" }), "库存变化 10 → 20"],
  [latestChange({ change_type: "stock_changed", old_value: "10", new_value: "0" }), "库存变化 10 → 0"],
  [latestChange({ change_type: "stock_increase", entity_key: "sku-1", sku_name: "红色", old_value: "10", new_value: "20" }), "红色 · SKU 库存增加 10 → 20"],
  [latestChange({ change_type: "stock_decrease", entity_key: "sku-1", sku_name: "红色", old_value: "20", new_value: "10" }), "红色 · SKU 库存下降 20 → 10"],
  [latestChange({ change_type: "sku_sold_out", entity_key: "sku-1", sku_name: "红色", old_value: "10", new_value: "0" }), "红色 · SKU 售罄"],
  [latestChange({ change_type: "sku_restocked", entity_key: "sku-1", sku_name: "红色", old_value: "0", new_value: "10" }), "红色 · SKU 恢复有货"],
  [latestChange({ change_type: "min_order_quantity_decrease", old_value: "5", new_value: "1" }), "起批量降低 5 → 1"],
  [latestChange({ change_type: "main_image_changed" }), "主图发生变化"],
  [latestChange({ change_type: "title_changed" }), "标题已变更"],
  [latestChange({ change_type: "new_change_type" }), "发生变化"],
  [null, "暂无变化记录"],
] as const)("formats latest change %s", (change, expected) => {
  expect(formatLatestChange(change)).toBe(expected);
});

test.each([
  [latestChange({ change_type: "sku_added", entity_key: "红色" }), "新增 SKU：红色"],
  [latestChange({ change_type: "sku_removed", entity_key: "蓝色" }), "移除 SKU：蓝色"],
] as const)("falls back to entity key when SKU value is missing", (change, expected) => {
  expect(formatLatestChange(change)).toBe(expected);
});

test("formats stock changes with SKU identity and keeps the legacy fallback", () => {
  expect(formatChange({ ...latestChange({ change_type: "stock_changed", entity_key: "6298697170559", old_value: "998", new_value: "994" }), sku_name: "粉色>A19" })).toBe("粉色>A19 · 库存 998 → 994");
  expect(formatChange({ ...latestChange({ change_type: "stock_changed", entity_key: "6298697170559", old_value: "998", new_value: "994" }) })).toBe("SKU 6298697170559 · 库存 998 → 994");
  expect(formatChange(latestChange({ change_type: "stock_changed", old_value: "998", new_value: "994" }))).toBe("库存变化 998 → 994");
});

test.each([
  ["39996", "39995", "↓ <0.1%"],
  ["13325", "13323", "↓ <0.1%"],
  ["2995", "2993", "↓ 0.1%"],
] as const)("formats small price changes without displaying a misleading zero: %s → %s", (oldValue, newValue, expected) => {
  expect(formatChangeMagnitude(latestChange({ change_type: "price_decrease", old_value: oldValue, new_value: newValue }))).toBe(expected);
});

test("keeps zero and normal percentage magnitudes unchanged", () => {
  expect(formatChangeMagnitude(latestChange({ change_type: "price_decrease", old_value: "100", new_value: "100" }))).toBe("↑ 0.0%");
  expect(formatChangeMagnitude(latestChange({ change_type: "price_increase", old_value: "100", new_value: "100.2" }))).toBe("↑ 0.2%");
});

test.each([
  ["0", "↑ 0.0%"],
  ["0.000000", "↑ 0.0%"],
  ["16.666667", "↑ 16.7%"],
  ["-16.666667", "↓ 16.7%"],
] as const)("formats numeric-string delta_rate %s", (delta_rate, expected) => {
  const change = latestChange({
    change_type: "price_decrease",
    old_value: "40.00",
    new_value: "35.00",
    delta_value: "-5.000000",
    delta_rate,
  });
  expect(formatPriceChangeMagnitude(change)).toBe(expected);
  expect(formatChangeMagnitude(change)).toBe(expected);
});

test("treats null, empty, and invalid delta_rate as unknown without rendering NaN", () => {
  const unknown = latestChange({ change_type: "price_decrease", delta_rate: null, old_value: null, new_value: null });
  expect(formatPriceChangeMagnitude(unknown)).toBe("—");
  expect(formatChangeMagnitude(unknown)).toBe("—");
  expect(formatChangeMagnitude(latestChange({ delta_rate: "", old_value: null, new_value: null }))).toBe("—");
  expect(formatChangeMagnitude(latestChange({ delta_rate: "not-a-number", old_value: null, new_value: null }))).toBe("—");
});

test("formats lifecycle changes for list, detail, and dashboard", () => {
  expect(formatChange(latestChange({ change_type: "product_offline", snapshot_id: null }))).toBe("商品已下架");
  expect(formatChange(latestChange({ change_type: "product_online", snapshot_id: 4 }))).toBe("商品恢复上架");
});

test("formats backend UTC timestamps in Asia/Shanghai without double conversion", () => {
  expect(formatDate("2026-09-22T09:04:00Z")).toContain("2026年9月22日 17:04");
  expect(formatDate("2026-09-22T09:04:00")).toContain("2026年9月22日 17:04");
  expect(formatDate("2026-09-22T17:04:00+08:00")).toContain("2026年9月22日 17:04");
});

test("renders the real latest change in the recent change column", () => {
  const changed = {
    ...competitor,
    latest_change: {
      id: 7,
      snapshot_id: 8,
      change_type: "price_increase",
      entity_key: null,
      sku_name: null,
      old_value: "40.00",
      new_value: "45.00",
      delta_value: null,
      delta_rate: null,
      detected_at: "2026-09-20T10:00:00Z",
    },
  };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[changed]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("商品涨价 40.00 → 45.00");
});

test("displays real batch progress and disables selection while running", () => {
  const second = { ...competitor, id: 2, offer_id: "987654321" };
  const running: BatchState = { ...idleBatchState, status: "running", total: 2, completed: 1, succeeded: 1, remaining: 1, runner_active: true };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor, second]} batchState={running} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("采集中 1 / 2");
  expect((html.match(/type="checkbox"[^>]*disabled=""/g) ?? [])).toHaveLength(3);
});

test("maps collection errors without exposing technical response bodies", () => {
  expect(getCollectionErrorMessage("1688_login_required")).toBe("1688 登录状态已失效，请重新登录后再试");
  expect(getCollectionErrorMessage("competitor_inactive")).toBe("该竞品已停止监控，无法立即采集");
  expect(getCollectionErrorMessage("collection_timeout")).toBe("商品页面加载超时，请稍后重试");
  expect(getCollectionErrorMessage("collection_failed", "后端返回的可读提示")).toBe("后端返回的可读提示");
  expect(getCollectionErrorMessage("collection_failed", "<html>traceback</html>")).toBe("采集失败，请稍后重试");
});

test("uses a fixed friendly message for request exceptions", () => {
  const message = getCollectionRequestErrorMessage(new TypeError("Failed to fetch"));
  expect(message).toBe("无法连接服务，请检查后端是否正常运行后重试");
  expect(message).not.toContain("Failed to fetch");
});

test.each([
  [{ kind: "http", code: "1688_login_required" }, "1688 登录状态已失效，请重新登录后再试"],
  [{ kind: "http", code: "collection_timeout" }, "商品页面加载超时，请稍后重试"],
  [{ kind: "http", code: "collection_failed", message: "后端返回的可读提示" }, "后端返回的可读提示"],
  [{ kind: "http", code: "collection_failed", message: "<html>traceback</html>" }, "采集失败，请稍后重试"],
  [{ kind: "request", error: new TypeError("Failed to fetch") }, "无法连接服务，请检查后端是否正常运行后重试"],
] as const)("keeps collection HTTP failures separate from request exceptions", (failure, expected) => {
  expect(getCollectionFailureMessage(failure)).toBe(expected);
});

test("appends clipboard links after current links and removes duplicates", () => {
  expect(mergeCompetitorUrlText(
    "https://detail.1688.com/offer/111.html",
    "https://detail.1688.com/offer/222.html",
  )).toBe("https://detail.1688.com/offer/111.html\nhttps://detail.1688.com/offer/222.html");

  expect(mergeCompetitorUrlText(
    "https://detail.1688.com/offer/111.html",
    "https://detail.1688.com/offer/111.html\n\nhttps://detail.1688.com/offer/333.html",
  )).toBe("https://detail.1688.com/offer/111.html\nhttps://detail.1688.com/offer/333.html");
});

test("renders a clipboard add action beside the competitor link field", () => {
  const html = renderToStaticMarkup(<AddDialog url="" status="initial" onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[]} groupId={null} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus="initial" />);
  expect(html).toContain("从剪贴板添加");
  expect(html).toContain('class="dialog-field-header"');
  expect(html).toContain('autoComplete="off"');
});

test("renders competitor group controls and new group entry", () => {
  const html = renderToStaticMarkup(<AddDialog url="" status="initial" onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[group]} groupId={1} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus="initial" />);
  expect(html).toContain('role="dialog"');
  expect(html).toContain('id="competitor-url"');
  expect(html).toContain("<textarea");
  expect(html).toContain('autoComplete="off"');
  expect(html).toContain('spellCheck="false"');
  expect(html).not.toContain('type="url"');
  expect(html).toContain("每行一个链接");
  expect(html).toContain("竞品组");
  expect(html).toContain("未分组");
  expect(html).toContain("暖手宝");
  expect(html).toContain("新增竞品组");
  expect(html).toContain("添加监控商品");
});

test("renders progress, failed URLs, and disables all add controls while submitting", () => {
  const html = renderToStaticMarkup(<AddDialog url="A\nB" status="submitting" onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[group]} groupId={1} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus="initial" progress={{ completed: 1, total: 2 }} />);
  expect(html).toContain("正在添加 1 / 2");
  expect(html).toContain('disabled=""');
  expect(html).toContain('id="competitor-group"');
});

test("renders partial and all-failed summaries with backend reasons", () => {
  const failures = [{ url: "A", code: "competitor_already_exists", reason: "已存在" }] as const;
  const partial = renderToStaticMarkup(<AddDialog url="A" status="partial" succeededCount={2} failures={[...failures]} onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[]} groupId={null} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus="initial" />);
  const failed = renderToStaticMarkup(<AddDialog url="A" status="failed" failures={[...failures]} onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[]} groupId={null} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus="initial" />);
  expect(partial).toContain("已添加 2 个，1 个未添加");
  expect(partial).toContain("A — 已存在");
  expect(failed).toContain("未添加 1 个监控商品");
  expect(failed).toContain("A — 已存在");
});

test.each([
  ["success", "feedback"],
  ["invalid", "feedback feedback-invalid"],
  ["duplicate", "feedback feedback-duplicate"],
  ["server-error", "feedback feedback-server-error"],
] as const)("renders the existing group feedback class for %s", (status, className) => {
  const html = renderToStaticMarkup(<AddDialog url="" status="initial" onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[]} groupId={null} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus={status} />);
  expect(html).toContain(`class="${className}"`);
  expect(getGroupFeedbackClass(status)).toBe(className);
});

test.each([
  [null, [], "未分组"],
  [1, [group], "暖手宝"],
  [2, [group], "—"],
] as const)("formats competitor group label", (groupId, groups, expected) => {
  expect(getCompetitorGroupLabel(groupId, groups)).toBe(expected);
});

test("renders competitor group labels in the list", () => {
  const html = renderToStaticMarkup(<ListPage {...listProps} groups={[group]} competitors={[{ ...competitor, group_id: null }, { ...competitor, id: 2, offer_id: "987654321", group_id: 1 }, { ...competitor, id: 3, offer_id: "111111111", group_id: 2 }]} status="ready" error={null} onRetry={noop} onAdd={noop} onOpenGroupAssignment={noop} />);
  expect(html).toContain("竞品组");
  expect(html).toContain("未分组");
  expect(html).toContain("暖手宝");
  expect(html).toContain("—");
  expect(html).toContain("+ 绑定竞品组");
  expect(html).toContain("更换/解除");
});

const dashboardData: DashboardData = {
  date: "2026-09-20",
  stats: { monitored_competitors: 5, changed_competitors: 1, change_events: 2, price_changed_competitors: 1, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 },
  items: [{
    competitor_id: 1,
    title: "暖手宝",
    shop_name: "家居店",
    main_image_url: null,
    group_id: 1,
    last_collected_at: "2026-09-20T10:00:00Z",
    change_count: 2,
    change_types: ["price_increase", "title_changed"],
    latest_change_at: "2026-09-20T10:00:00Z",
    primary_change: { id: 2, snapshot_id: 3, collection_run_id: 4, change_type: "price_increase", entity_key: null, sku_name: null, old_value: "40.00", new_value: "45.00", delta_value: null, delta_rate: null, detected_at: "2026-09-20T10:00:00Z" },
    stock_changed_sku_count: 0,
    stock_total_change: null,
    sku_added_count: 0,
    sku_removed_count: 0,
  }],
  collection_summary: { last_collection_at: "2026-09-20T10:00:00Z", success_runs: 3, failed_runs: 0, average_duration_seconds: 28 },
  trend_7d: ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19", "2026-09-20"].map((date, index) => ({ date, price_changes: index === 6 ? 2 : 0, stock_changes: index === 5 ? 1 : 0, sku_changes: 0, failed_collections: 0 })),
};

const attentionData = {
  date: "2026-09-20",
  kpis: { monitored_product_groups: 7, changed_product_groups_today: 3, changed_competitors_today: 9 },
  groups: [
    { group_id: 9, group_name: "一般组", own_product: { id: 109, offer_id: "own-9", title: "我方一般款", shop_name: "自营店", main_image_url: null }, attention_level: "一般变化" as const, changed_competitor_count: 2, reasons: [{ reason_type: "product_content_changed", display_text: "2 家竞品调整商品内容", competitor_count: 2, sku_count: null, direction: null, event_level: "D" as const, current_state_safe: true }], latest_change_at: "2026-09-20T10:00:00Z" },
    { group_id: 4, group_name: "建议组", own_product: { id: 104, offer_id: "own-4", title: "我方建议款", shop_name: null, main_image_url: null }, attention_level: "建议查看" as const, changed_competitor_count: 3, reasons: [{ reason_type: "price_increase", display_text: "3 家竞品涨价", competitor_count: 3, sku_count: null, direction: "price_increase", event_level: "B" as const, current_state_safe: true }, { reason_type: "sku_added", display_text: "1 家竞品新增 SKU", competitor_count: 1, sku_count: 2, direction: "sku_added", event_level: "B" as const, current_state_safe: true }], latest_change_at: "2026-09-20T11:00:00Z" },
    { group_id: 2, group_name: "重点组", own_product: { id: 102, offer_id: "own-2", title: "我方重点款", shop_name: "旗舰店", main_image_url: null }, attention_level: "重点关注" as const, changed_competitor_count: 4, reasons: [0, 1, 2, 3].map((index) => ({ reason_type: `price_${index}`, display_text: `${index + 1} 家竞品降价`, competitor_count: index + 1, sku_count: null, direction: "price_decrease", event_level: "S" as const, current_state_safe: true })).slice(0, 3), latest_change_at: "2026-09-20T12:00:00Z" },
  ],
};

const dashboardProps: React.ComponentProps<typeof DashboardPage> = {
  data: dashboardData,
  attention: attentionData,
  attentionStatus: "ready",
  attentionError: null,
  status: "ready",
  error: null,
  onRetry: noop,
  onRetryAttention: noop,
  onNavigate: noop,
  onOpenGroupDetail: noop,
  ownShopName: "测试店铺",
};
const renderDashboard = (props: Partial<React.ComponentProps<typeof DashboardPage>> = {}) => renderToStaticMarkup(<DashboardPage {...dashboardProps} {...props} />);

function findButton(node: ReactNode, text: string): { onClick?: () => void } | null {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = findButton(child, text);
      if (match) return match;
    }
    return null;
  }
  if (!isValidElement<{ children?: ReactNode; onClick?: () => void }>(node)) return null;
  const children = node.props.children;
  if (node.type === "button" && reactText(children) === text) return node.props;
  return findButton(children, text);
}

function reactText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(reactText).join("");
  return isValidElement<{ children?: ReactNode }>(node) ? reactText(node.props.children) : "";
}

test("renders group-first KPI and keeps backend group order and Attention levels", () => {
  const html = renderDashboard();
  expect(html).toContain("监控商品组");
  expect(html).toContain(">7</strong>");
  expect(html).toContain("今日有变化商品组");
  expect(html).toContain(">3</strong>");
  expect(html).toContain("今日涉及变化竞品");
  expect(html).toContain(">9</strong>");
  expect(html).toContain("异常采集");
  expect(html).not.toContain("添加竞品");
  expect(html).toContain("我方店铺：测试店铺");
  expect(html).toContain("立即采集");
  expect(html).toContain("添加监控商品");
  expect(html).not.toContain("dashboard-context-row");
  expect(html).toContain("今日需要关注的商品组");
  const order = ["一般组", "建议组"].map((name) => html.indexOf(name));
  expect(order.every((index) => index >= 0)).toBe(true);
  expect(order).toEqual([...order].sort((left, right) => left - right));
  expect(html).toContain("一般变化");
  expect(html).toContain("建议查看");
  expect(html).not.toContain("重点关注");
  expect(html).not.toContain("我方重点款");
  expect(html).not.toContain("旗舰店");
  expect(html).toContain("今日变化竞品");
  expect(html).toContain("进入组分析");
  expect(html).not.toContain("attention_score");
  expect(html).not.toContain("今日发生变化的竞品");
  expect(html).not.toContain("我方商品组</h2>");
  expect(html).not.toContain("dashboard-events-table");
  expect(html).toContain("采集状态概览");
  expect(html).toContain("近 7 天竞品变化趋势");
});

test("limits dashboard Attention groups to the first two by default", () => {
  const groups = ["第一组", "第二组", "第三组", "第四组", "第五组"].map((group_name, index) => ({ ...attentionData.groups[index % attentionData.groups.length], group_id: index + 1, group_name }));
  const html = renderDashboard({ attention: { ...attentionData, groups } });
  const order = groups.slice(0, 2).map((group) => html.indexOf(group.group_name));
  expect(order.every((index) => index >= 0)).toBe(true);
  expect(order).toEqual([...order].sort((left, right) => left - right));
  expect(html).not.toContain("第三组");
  expect(html).not.toContain("第四组");
  expect(html).not.toContain("第五组");
  expect(html).toContain("还有 3 个需要关注的商品组");
  expect(html).toContain("展开全部");
  expect(html).toContain('class="dashboard-attention-toggle"');

  const twoGroups = renderDashboard({ attention: { ...attentionData, groups: groups.slice(0, 2) } });
  expect(twoGroups).not.toContain("展开全部");
  expect(twoGroups).not.toContain("收起");
});

test("expands and collapses dashboard Attention groups without changing their order", async () => {
  const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { host: "127.0.0.1", port: 0 }, clearScreen: false });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  const groups = ["第一组", "第二组", "第三组", "第四组", "第五组"].map((group_name, index) => ({ ...attentionData.groups[index % attentionData.groups.length], group_id: index + 1, group_name }));
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", async (route) => {
    const key = `${route.request().method()} ${new URL(route.request().url()).pathname}`;
    if (key === "GET /api/dashboard/today") return json(route, dashboardData);
    if (key === "GET /api/dashboard/group-attention") return json(route, { ...attentionData, groups });
    if (key === "GET /api/settings/own-shop-name") return json(route, { configured: true, own_shop_name: "测试店铺" });
    if (key === "GET /api/competitors/collect-batch/status") return json(route, idleBatchState);
    if (key === "GET /api/competitor-groups/1/detail") return json(route, { message: "not found" }, 404);
    return route.abort("blockedbyclient");
  });

  try {
    const baseUrl = server.resolvedUrls?.local[0];
    if (!baseUrl) throw new Error("Vite test server did not expose a local URL");
    await page.goto(baseUrl);
    await playwrightExpect(page.getByRole("heading", { name: "竞品监控大屏" })).toBeVisible();
    await playwrightExpect(page.locator(".dashboard-attention-card h3")).toHaveText(["第一组", "第二组"]);
    await playwrightExpect(page.getByText("第四组", { exact: true })).toHaveCount(0);
    await playwrightExpect(page.locator(".dashboard-attention-toggle")).toHaveText("还有 3 个需要关注的商品组展开全部⌄");
    await page.getByRole("button", { name: "展开全部" }).click();
    await playwrightExpect(page.locator(".dashboard-attention-card h3")).toHaveText(groups.map((group) => group.group_name));
    await playwrightExpect(page.locator(".dashboard-attention-toggle")).toHaveText("已展示全部 5 个商品组收起⌃");
    await page.getByRole("button", { name: "收起" }).click();
    await playwrightExpect(page.locator(".dashboard-attention-card h3")).toHaveText(["第一组", "第二组"]);
    await page.getByRole("button", { name: "进入组分析" }).first().click();
    await playwrightExpect(page.getByRole("heading", { name: "组竞争分析" })).toBeVisible();
  } finally {
    await context.close();
    await browser.close();
    await server.close();
  }
}, 10_000);

test("keeps Dashboard collection status complete in idle, running, and resting browser views", async () => {
  const server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { host: "127.0.0.1", port: 0 }, clearScreen: false });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const groups = ["第一组", "第二组", "第三组", "第四组", "第五组"].map((group_name, index) => ({ ...attentionData.groups[index % attentionData.groups.length], group_id: index + 1, group_name }));
  let batchState: BatchState = idleBatchState;
  const json = (route: Route, body: unknown) => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/**", async (route) => {
    const key = `${route.request().method()} ${new URL(route.request().url()).pathname}`;
    if (key === "GET /api/dashboard/today") return json(route, dashboardData);
    if (key === "GET /api/dashboard/group-attention") return json(route, { ...attentionData, groups });
    if (key === "GET /api/settings/own-shop-name") return json(route, { configured: true, own_shop_name: "测试店铺" });
    if (key === "GET /api/competitors/collect-batch/status") return json(route, batchState);
    return route.abort("blockedbyclient");
  });

  try {
    const baseUrl = server.resolvedUrls?.local[0];
    if (!baseUrl) throw new Error("Vite test server did not expose a local URL");
    for (const state of [idleBatchState, makeBatchState("running", { total: 3, completed: 1, remaining: 2, runner_active: true }), makeBatchState("resting", { total: 3, completed: 1, remaining: 2, resting_remaining_seconds: 17, runner_active: true })]) {
      batchState = state;
      await page.goto(baseUrl);
      const overview = page.locator(".collection-overview");
      await playwrightExpect(overview).toBeVisible();
      await playwrightExpect(overview.locator(".collection-batch")).toBeVisible();
      expect(await overview.evaluate((element) => {
        const card = element.getBoundingClientRect();
        const batch = element.querySelector(".collection-batch")!.getBoundingClientRect();
        return batch.top >= card.top && batch.bottom <= card.bottom;
      })).toBe(true);
      if (state.status === "running" || state.status === "resting") await playwrightExpect(overview.getByRole("progressbar")).toBeVisible();
    }
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
      batchState = idleBatchState;
      await page.setViewportSize(viewport);
      await page.goto(baseUrl);
      const lowerLayout = await page.locator(".dashboard-lower-grid").evaluate((element) => {
        const main = element.closest(".main-content")!.getBoundingClientRect();
        const grid = element.getBoundingClientRect();
        const cards = Array.from(element.querySelectorAll<HTMLElement>(":scope > .table-card")).map((card) => card.getBoundingClientRect().height);
        const chart = element.querySelector<HTMLElement>(".dashboard-trend-chart")!.getBoundingClientRect().height;
        return { remainingBelow: main.bottom - grid.bottom, cards, chart };
      });
      expect(lowerLayout.remainingBelow).toBeLessThanOrEqual(14);
      expect(Math.abs(lowerLayout.cards[0] - lowerLayout.cards[1])).toBeLessThanOrEqual(1);
      expect(lowerLayout.chart).toBeLessThanOrEqual(260);
    }
    const dimensions = await page.locator(".main-content-dashboard").evaluate((element) => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }));
    expect(dimensions.scrollHeight).toBeLessThanOrEqual(dimensions.clientHeight);
    const mainContent = page.locator(".main-content-dashboard");
    expect(await mainContent.evaluate((element) => getComputedStyle(element).scrollbarGutter)).toBe("stable");
    expect(await mainContent.evaluate((element) => getComputedStyle(element, "::-webkit-scrollbar").width)).toBe("7px");
    const collapsedWidth = await mainContent.evaluate((element) => element.getBoundingClientRect().width);
    await page.getByRole("button", { name: "展开全部" }).click();
    const expandedDimensions = await page.locator(".main-content-dashboard").evaluate((element) => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }));
    expect(expandedDimensions.scrollHeight).toBeGreaterThan(expandedDimensions.clientHeight);
    expect(await mainContent.evaluate((element) => element.getBoundingClientRect().width)).toBe(collapsedWidth);
    await page.getByText("第五组", { exact: true }).scrollIntoViewIfNeeded();
    await playwrightExpect(page.getByText("第五组", { exact: true })).toBeVisible();
  } finally {
    await context.close();
    await browser.close();
    await server.close();
  }
}, 10_000);

test("disables dashboard collection when there are no active monitored products", () => {
  const html = renderDashboard({ data: { ...dashboardData, stats: { ...dashboardData.stats, active_monitored_products: 0 } } });
  expect(html).toMatch(/<button[^>]*disabled=""[^>]*>立即采集<\/button>/);
  const active = renderDashboard({ data: { ...dashboardData, stats: { ...dashboardData.stats, active_monitored_products: 1 } } });
  expect(active).toMatch(/<button[^>]*>立即采集<\/button>/);
});

test("wires Dashboard collection action and keeps it out of list pages", () => {
  const collect = vi.fn();
  const dashboard = DashboardPage({ ...dashboardProps, onCollect: collect });
  findButton(dashboard, "立即采集")?.onClick?.();
  expect(collect).toHaveBeenCalledOnce();
  const ownList = renderToStaticMarkup(<ListPage {...listProps} ownership="self" competitors={[competitor]} status="ready" error={null} onRetry={noop} onOpenGroupAssignment={noop} />);
  const competitorList = renderToStaticMarkup(<ListPage {...listProps} ownership="competitor" competitors={[competitor]} status="ready" error={null} onRetry={noop} onOpenGroupAssignment={noop} />);
  expect(ownList).not.toContain("采集选中");
  expect(ownList).not.toContain("采集全部监控中");
  expect(competitorList).not.toContain("采集选中");
  expect(competitorList).not.toContain("采集全部监控中");
});

test("limits rendered reasons to the backend-provided list and shows the no-change state", () => {
  const html = renderDashboard();
  expect((html.match(/dashboard-attention-reasons/g) || []).length).toBe(2);
  const empty = renderDashboard({ attention: { ...attentionData, groups: [], kpis: { ...attentionData.kpis, changed_product_groups_today: 0, changed_competitors_today: 0 } } });
  expect(empty).toContain("今日暂无需要关注的竞争变化");
  expect(empty).not.toContain("一般组");
  expect(empty).not.toContain("重点组");
});

test("isolates Attention error from collection and trend and offers an Attention-only retry", () => {
  const retry = vi.fn();
  const html = renderDashboard({ attention: null, attentionStatus: "error", attentionError: "Attention unavailable", onRetryAttention: retry });
  expect(html).toContain("Attention unavailable");
  expect(html).toContain("重试");
  expect(html).toContain("采集状态概览");
  expect(html).toContain("近 7 天竞品变化趋势");
  expect(html).not.toContain("今日暂无需要关注的竞争变化");
  expect(html).toContain("暂时无法获取商品组关注信息");
  expect(html).not.toContain("attention_score");
  expect(retry).not.toHaveBeenCalled();
});

test("wires Attention retry and renders Group Detail actions", () => {
  const retry = vi.fn();
  const retryTree = DashboardPage({ ...dashboardProps, attention: null, attentionStatus: "error", attentionError: "failed", onRetryAttention: retry });
  findButton(retryTree, "重试")?.onClick?.();
  expect(retry).toHaveBeenCalledOnce();
  const groups = renderDashboard();
  expect(groups).toContain("进入组分析");
});

test("shows an independent dashboard/today error while preserving Attention results", () => {
  const html = renderDashboard({ status: "error", error: "今日数据暂不可用" });
  expect(html).toContain("今日数据暂不可用");
  expect(html).not.toContain("重点组");
  expect(html).toContain("今日需要关注的商品组");
});

test("renders the collection batch status and Group Detail action", () => {
  const running = renderDashboard({ batchState: { ...idleBatchState, status: "running", total: 9, completed: 3, succeeded: 3, runner_active: true } });
  expect(running).toContain("采集中 3 / 9");
  expect(running).toContain('style="width:33.33333333333333%"');
  expect(running).toContain('class="secondary-button" disabled="">立即采集</button>');
  expect(running).toContain("进入组分析");
  const verification = renderDashboard({ batchState: { ...idleBatchState, status: "verification_required", total: 9, completed: 3 } });
  expect(verification).toContain("需要人工验证");
});

test("formats collection durations", () => {
  expect(formatDuration(72)).toBe("1 分 12 秒");
  expect(formatDuration(null)).toBe("—");
});

test("renders the seven trend labels and keeps zero-valued chart points valid", () => {
  const points = buildDashboardTrendChartPoints(dashboardData.trend_7d);
  expect(points).toHaveLength(7);
  expect(points.every((point) => Number.isFinite(point.y.price_changes))).toBe(true);
  const html = renderToStaticMarkup(<DashboardTrendChart trend={dashboardData.trend_7d} />);
  expect((html.match(/class="chart-label chart-y-label"/g) || []).length).toBeGreaterThanOrEqual(4);
  expect(html).toContain("09/14");
  expect(html).toContain("09/20");
});

test("dashboard trend uses a zero-based integer scale with useful intermediate ticks", () => {
  const trend = [{ date: "2026-09-20", price_changes: 15, stock_changes: 0, sku_changes: 0, failed_collections: 0 }];
  const scale = buildDashboardTrendScale(trend);
  expect(scale.domain[0]).toBe(0);
  expect(scale.ticks).toEqual([0, 5, 10, 15]);
  expect(scale.ticks.every(Number.isInteger)).toBe(true);
  expect(formatDashboardTrendTooltip(trend[0])).toEqual(["09/20", "变价 15", "库存变化 0", "SKU变化 0", "异常采集 0"]);
});

test("dashboard all-zero trend still has a usable integer domain", () => {
  const scale = buildDashboardTrendScale(dashboardData.trend_7d.map((point) => ({ ...point, price_changes: 0, stock_changes: 0, sku_changes: 0, failed_collections: 0 })));
  expect(scale.domain).toEqual([0, 4]);
  expect(scale.ticks).toEqual([0, 1, 2, 3, 4]);
});

test("renders batch state with the dashboard collection action", () => {
  const running = renderDashboard({ batchState: { ...idleBatchState, status: "running", total: 9, completed: 3, succeeded: 3, runner_active: true } });
  expect(running).toContain("采集中 3 / 9");
  expect(running).toContain('style="width:33.33333333333333%"');
  const verification = renderDashboard({ batchState: { ...idleBatchState, status: "verification_required", total: 9, completed: 3 } });
  expect(verification).toContain("需要人工验证");
  const empty = renderDashboard({ data: { ...dashboardData, stats: { ...dashboardData.stats, monitored_competitors: 0 } } });
  expect(empty).toContain("当前无采集任务");
  expect(empty).toContain("今日采集统计仍会保留");
  expect(empty).toContain('disabled=""');
  expect(empty).not.toContain("添加竞品");
  expect(empty).toContain("立即采集");
});

test("renders detail entry actions on dashboard and competitor list", () => {
  const dashboard = renderDashboard();
  const list = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} status="ready" error={null} onRetry={noop} onAdd={noop} onOpenDetail={noop} />);
  expect(dashboard).toContain("进入组分析");
  expect(list).toContain(">详情<");
});

test.each([
  [latestChange({ change_type: "price_increase", old_value: "1", new_value: "2" }), "商品涨价 1 → 2"],
  [latestChange({ change_type: "price_decrease", old_value: "2", new_value: "1" }), "商品降价 2 → 1"],
  [latestChange({ change_type: "sku_added", new_value: "红色" }), "新增 SKU：红色"],
  [latestChange({ change_type: "sku_removed", old_value: "蓝色" }), "移除 SKU：蓝色"],
  [latestChange({ change_type: "stock_changed", old_value: "1", new_value: "0" }), "库存变化 1 → 0"],
  [latestChange({ change_type: "main_image_changed" }), "主图发生变化"],
  [latestChange({ change_type: "title_changed" }), "标题已变更"],
  [latestChange({ change_type: "unknown" }), "发生变化"],
] as const)("formats dashboard changes through the shared formatter", (change, expected) => {
  expect(formatChange(change)).toBe(expected);
});

test("marks active root and monitoring navigation with one consistent icon style", () => {
  const home = renderToStaticMarkup(<Sidebar page="home" onNavigate={noop} />);
  const dashboard = renderToStaticMarkup(<Sidebar page="dashboard" onNavigate={noop} />);
  const competitors = renderToStaticMarkup(<Sidebar page="competitors" onNavigate={noop} />);
  const groups = renderToStaticMarkup(<Sidebar page="groups" onNavigate={noop} />);
  const collectionTasks = renderToStaticMarkup(<Sidebar page="collection-tasks" onNavigate={noop} />);
  const priceCompare = renderToStaticMarkup(<Sidebar page="price-compare" onNavigate={noop} />);
  const autoInquiry = renderToStaticMarkup(<Sidebar page="auto-inquiry" onNavigate={noop} />);
  const autoListing = renderToStaticMarkup(<Sidebar page="auto-listing" onNavigate={noop} />);
  expect(home).toContain('aria-current="page"');
  expect(home).toContain("首页");
  expect(home).toContain("<svg");
  expect(home).toContain('aria-expanded="false"');
  expect(dashboard).toContain('aria-expanded="true"');
  expect(dashboard).toContain('aria-controls="competitor-monitoring-nav"');
  expect(dashboard).toContain('nav-group-title nav-group-title-current');
  expect(dashboard).toContain('class="nav-item nav-child nav-active" aria-current="page"');
  expect(competitors).toContain("竞品列表");
  expect(groups).toContain("竞品分组");
  expect(collectionTasks).toContain("采集任务");
  expect(priceCompare).toContain("全网比价");
  expect(priceCompare).toContain('aria-current="page"');
  expect(priceCompare).toContain('aria-expanded="false"');
  expect(autoInquiry).toContain("自动询价");
  expect(autoInquiry).toContain('aria-current="page"');
  expect(autoInquiry).toContain('aria-expanded="false"');
  expect(autoListing).toContain("自动上架");
  expect(autoListing).toContain('aria-current="page"');
  expect(autoListing).toContain('aria-expanded="false"');
  const settings = renderToStaticMarkup(<Sidebar page="settings" onNavigate={noop} />);
  expect(settings).toContain('aria-expanded="false"');
});

test("renders workspace module placeholders", () => {
  const home = renderToStaticMarkup(<HomePage onNavigate={noop} />);
  const compare = renderToStaticMarkup(<WorkspacePlaceholderPage page="price-compare" title="全网比价" description="比价" note="待实现" icon="compare" onNavigate={noop} />);
  const collectionTasks = renderToStaticMarkup(<CollectionTasksPage onNavigate={noop} />);
  expect(home).toContain("<h1>首页</h1>");
  expect(home).toContain("首页模块已预留");
  expect(compare).toContain("<h1>全网比价</h1>");
  expect(compare).toContain("全网比价模块已预留");
  expect(collectionTasks).toContain("<h1>采集任务</h1>");
  expect(collectionTasks).toContain("当前批量采集");
  expect(collectionTasks).toContain("采集记录");
});

test("shows the frozen wait countdown while a batch is paused", () => {
  const pausedCooling = renderDashboard({ batchState: { ...idleBatchState, status: "paused", total: 3, completed: 1, remaining: 2, cooldown_remaining_seconds: 9, runner_active: true } });
  expect(pausedCooling).toContain("风控冷却已暂停");
  expect(pausedCooling).toContain("9 秒");

  const pausedResting = renderDashboard({ batchState: { ...idleBatchState, status: "paused", total: 3, completed: 1, remaining: 2, resting_remaining_seconds: 17, runner_active: true } });
  expect(pausedResting).toContain("计划休息已暂停");
  expect(pausedResting).toContain("17 秒");
});

test("renders Collection Tasks runtime states and preserves missing current product IDs", () => {
  const productById = new Map([[1, { ...competitor, title: "当前商品", offer_id: "offer-1", shop_name: "测试店铺" }]]);
  const render = (batchState: BatchState) => renderToStaticMarkup(<CurrentBatchCard batchState={batchState} status="ready" error={null} onRetry={noop} productById={productById} />);
  const idle = render(idleBatchState);
  expect(idle).toContain("当前无批量采集任务");
  expect(idle).toContain("可在竞品监控大屏点击「立即采集」发起批量采集。");
  expect(render({ ...idleBatchState, status: "running", total: 2, completed: 1, remaining: 1, current_competitor_id: 99 })).toContain("商品 ID：99");
  expect(render({ ...idleBatchState, status: "resting", total: 2, completed: 1, remaining: 1, current_competitor_id: 1, resting_remaining_seconds: 17, browser_open: true, runner_active: true })).toContain("计划内主动休息");
  expect(render({ ...idleBatchState, status: "resting", total: 2, completed: 1, remaining: 1, current_competitor_id: 1, resting_remaining_seconds: 17, browser_open: true, runner_active: true })).toContain("休息剩余：17 秒");
  expect(render({ ...idleBatchState, status: "paused", total: 2, completed: 1, remaining: 1, resting_remaining_seconds: 17, runner_active: true })).toContain("计划休息剩余：17 秒");
  expect(render({ ...idleBatchState, status: "paused", total: 2, completed: 1, remaining: 1, cooldown_remaining_seconds: 17, runner_active: true })).toContain("风控冷却剩余：17 秒");
  expect(render({ ...idleBatchState, status: "cooling_down", total: 2, completed: 1, remaining: 1, current_competitor_id: 1, cooldown_remaining_seconds: 17, auto_resume_attempt: 1 })).toContain("风控冷却中");
  expect(render({ ...idleBatchState, status: "verification_required", total: 2, completed: 1, remaining: 1, current_competitor_id: 1, browser_open: true, runner_active: true })).toContain("需要人工验证");
  expect(render({ ...idleBatchState, status: "completed", total: 2, completed: 2, succeeded: 1, failed: 1, outcome_code: "completed" })).toContain("结果码：completed");
});

test("keeps collection task labels in user-facing language", () => {
  const html = renderToStaticMarkup(<CollectionTasksPage onNavigate={noop} />);
  expect(html).toContain("查看每次商品采集结果与失败原因");
  expect(html).not.toMatch(/BatchRuntime|Runtime|持久化|单商品采集尝试/);
});

test("formats the independent base and operating statuses for collection records", () => {
  expect(formatCollectionRunStatus("success", "success")).toBe("成功 · 经营成功");
  expect(formatCollectionRunStatus("success", "partial")).toBe("成功 · 经营部分成功");
  expect(formatCollectionRunStatus("success", "no_values")).toBe("成功 · 经营页面暂无值");
  expect(formatCollectionRunStatus("success", "failed")).toBe("成功 · 经营失败");
  expect(formatCollectionRunStatus("success", "blocked")).toBe("成功 · 经营已阻止");
  expect(formatCollectionRunStatus("success", "not_attempted")).toBe("成功 · 经营未尝试");
  expect(formatCollectionRunStatus("failed", undefined)).toBe("失败 · 经营未采集");
});

test.each([
  [{ price_min: null, price_max: null }, "暂无价格"],
  [{ price_min: "39.00", price_max: "39.00" }, "¥39.00"],
  [{ price_min: "34.00", price_max: "40.00" }, "¥34.00 ~ ¥40.00"],
  [{ price_min: "39.00", price_max: null }, "¥39.00"],
] as const)("formats group price range", (metrics, expected) => {
  expect(formatGroupPriceRange(metrics)).toBe(expected);
});

test("formats missing group latest change as an explicit empty value", () => {
  expect(formatGroupLatestChange(null)).toBe("暂无变化");
  expect(formatGroupLatestChange("2026-09-21T10:35:00Z")).not.toBe("暂无变化");
});

test("applies group navigation intent and clears it for normal list navigation", () => {
  expect(applyInitialGroupFilter(defaultCompetitorFilters, 1).groupId).toBe(1);
  expect(applyInitialGroupFilter(defaultCompetitorFilters, "unassigned").groupId).toBe("unassigned");
  expect(applyInitialGroupFilter({ ...defaultCompetitorFilters, groupId: 1 }, null).groupId).toBe("all");
});

test("renders group page loading, error, full empty, unassigned and normal states", () => {
  const loading = renderToStaticMarkup(<GroupPage summary={null} status="loading" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onOwnProduct={noop} onNavigate={noop} />);
  const error = renderToStaticMarkup(<GroupPage summary={null} status="error" error="请求失败" onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onOwnProduct={noop} onNavigate={noop} />);
  const empty = renderToStaticMarkup(<GroupPage summary={{ groups: [], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onOwnProduct={noop} onNavigate={noop} />);
  const onlyUnassigned = renderToStaticMarkup(<GroupPage summary={{ groups: [], unassigned: { ...groupMetrics, competitor_count: 1, active_count: 1 } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onOwnProduct={noop} onNavigate={noop} />);
  const normal = renderToStaticMarkup(<GroupPage summary={{ groups: [groupSummary], unassigned: { ...groupMetrics, competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onOwnProduct={noop} onNavigate={noop} />);
  expect(loading).toContain("正在加载竞品组");
  expect(error).toContain("重试");
  expect(empty).toContain("还没有竞品组");
  expect(onlyUnassigned).toContain("未分组");
  expect(onlyUnassigned).toContain("查看竞品");
  expect(onlyUnassigned).not.toContain("组分析");
  expect(onlyUnassigned).not.toContain("绑定我方商品");
  expect(normal).toContain("暖手宝");
  expect(normal).toContain("3 个竞品");
  expect(normal).toContain("¥34.00 ~ ¥40.00");
  expect(normal).toContain("更多");
  expect(normal).toContain("组分析");
  const bound = renderToStaticMarkup(<GroupPage summary={{ groups: [{ ...groupSummary, own_product: { id: 7, offer_id: "700", title: "我的基准商品", shop_name: "我的店铺", main_image_url: null, status: "active", is_active: true } }], unassigned: { ...groupMetrics, competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onOwnProduct={noop} onNavigate={noop} />);
  expect(bound).toContain("我的基准商品");
});

test("formats compact group update times and only nonzero action domains", () => {
  expect(formatGroupUpdateTime(null)).toBe("未采集");
  expect(formatGroupUpdateTime("2026-09-22T01:57:00Z")).toBe("09:57");
  expect(getNonzeroGroupActionDomains({ price: 0, stock: 6, sku: 0, min_order_quantity: 0, lifecycle: 0, title: 0, main_image: 0 })).toEqual(["库存 6"]);
});

test("uses neutral group change placeholder and offline snapshot freshness for own and competitors", () => {
  expect(formatGroupDetailLatestChange(null)).toBe("—");
  const offlineOwn = { ...groupDetailData.own_product!, status: "offline" as const, last_collected_at: "2026-09-23T10:00:00Z", latest_snapshot: { ...groupDetailData.own_product!.latest_snapshot!, captured_at: "2026-09-22T10:00:00Z" } };
  const offlineCompetitor = { ...groupProduct({ status: "offline", last_collected_at: "2026-09-23T10:00:00Z", latest_snapshot: { ...groupProduct().latest_snapshot!, captured_at: "2026-09-21T10:00:00Z" } }), comparison: groupDetailData.competitors[0].comparison };
  expect(formatGroupProductFreshness(offlineOwn)).toBe(`最后快照 ${formatDate("2026-09-22T10:00:00Z")}`);
  expect(formatGroupProductFreshness(offlineCompetitor)).toBe(`最后快照 ${formatDate("2026-09-21T10:00:00Z")}`);
  expect(formatGroupProductFreshness({ ...offlineCompetitor, latest_snapshot: null })).toBe("未采集");
  expect(formatGroupProductFreshness(groupProduct())).toBe("18:00 更新");

  const html = renderToStaticMarkup(<GroupDetailPage data={{ ...groupDetailData, own_product: offlineOwn, competitors: [offlineCompetitor] }} status="ready" error={null} days={7} rangeLoading={false} rangeError={null} onRetry={noop} onRangeChange={noop} onBack={noop} onViewCompetitors={noop} onOpenDetail={noop} onNavigate={noop} />);
  expect(html).toContain(`来源快照 #${offlineOwn.latest_snapshot!.id} · ${formatDate("2026-09-22T10:00:00Z")}`);
  expect(html).toContain(`快照时间：${formatDate("2026-09-21T10:00:00Z")}`);
  expect(html).not.toContain("最后快照");
  expect(html).toContain("已下架");
  expect(html).not.toContain('<td>暂无变化</td>');
  expect(html).toContain("查看详情");
});

test("summarizes meaningful group differences without turning unknown fields into advantages", () => {
  expect(getGroupDifferenceLabels({ price: "lower", min_order_quantity: "lower", sku_count: "more", total_stock: "unknown" }, true)).toEqual({ primary: ["低价", "起批更低", "SKU 更多"], stock: [], hasUnknown: true });
  expect(getGroupDifferenceLabels({ price: "overlap", min_order_quantity: "equal", sku_count: "equal", total_stock: "equal" }, true)).toEqual({ primary: [], stock: [], hasUnknown: false });
  expect(getGroupDifferenceLabels({ price: "unknown", min_order_quantity: "unknown", sku_count: "unknown", total_stock: "unknown" }, false)).toEqual({ primary: ["未建立基准"], stock: [], hasUnknown: false });
});

test("renders competitive workbench states and truthful pending analysis", () => {
  const props = { data: groupDetailData, status: "ready" as const, error: null, days: 7 as const, rangeLoading: false, rangeError: null, onRetry: noop, onRangeChange: noop, onBack: noop, onViewCompetitors: noop, onOpenDetail: noop, onNavigate: noop };
  expect(renderToStaticMarkup(<GroupDetailPage {...props} data={null} status="loading" />)).toContain("正在加载组分析");
  expect(renderToStaticMarkup(<GroupDetailPage {...props} data={null} status="error" error="竞品组不存在" />)).toContain("竞品组不存在");
  const html = renderToStaticMarkup(<GroupDetailPage {...props} />);
  for (const text of ["组内经营景气信号", "评分规则未冻结", "经营字段历史有效值", "当前经营决策提示", "仅监控样本，非实时报价", "排名覆盖：", "经营表现", "口碑履约", "平台标签", "待接入", "证据不足", "MOQ ↑", "aria-sort=\"ascending\"", "筛选不改变全组排名", "可查看全部变化", "自有商品", "商品速览", "查看详情"]) expect(html).toContain(text);
  expect(html.match(/class=\"position-row-actions\"><button class=\"detail-button\">查看详情<\/button><\/div>/g)).toHaveLength(groupDetailData.competitors.length + 1);
  expect(html).toContain("平台标签 <small class=\"position-tag-pending\">待接入</small>");
  expect(html.match(/role=\"tab\"/g)).toHaveLength(3);
  expect(html).not.toContain("role=\"tab\" aria-selected=\"false\" class=\"\">平台标签");
  expect(html.match(/class=\"position-tag-cell\" aria-label=\"平台标签待接入/g)).toHaveLength(groupDetailData.competitors.length + 1);
  expect(html).not.toContain("无标签");
  expect(html).not.toContain("模拟");
  const rows = html.match(/<tr[^>]*data-offer-id[^>]*>/g)!;
  expect(rows).toHaveLength(groupDetailData.competitors.length + 1);
  for (const row of rows) {
    expect(row).toContain('tabindex="0"');
    expect(row).toContain("Offer ID：");
    expect(row).toContain("快照时间：");
    expect(row).toContain("状态：");
  }
  expect(html).not.toContain("position-row-hint");
  expect(html).not.toContain("最近真实采集");
  expect(html).toContain(`1 条我方商品 · ${groupDetailData.competitors.length} 条竞品 · 仅监控样本，非实时报价`);
  expect(renderToStaticMarkup(<GroupDetailPage {...props} data={{ ...groupDetailData, own_product: null, competitors: [] }} />)).toContain("0 条我方商品 · 0 条竞品 · 仅监控样本，非实时报价");
  expect(html).not.toContain("group-own-row");
  expect(html).toContain("position-own-row");
  expect(html).not.toContain("position-filter-notice");
  const body = html.match(/<tbody>(.*?)<\/tbody>/s)![1];
  expect(body).not.toContain("group-own-label");
  expect(body).not.toContain("<time");
  expect(body).not.toContain("title=");
  expect(body).toContain('class="position-shop"');
  expect(html.indexOf('data-offer-id="10"')).toBeLessThan(html.indexOf('data-offer-id="7"'));
  expect(renderToStaticMarkup(<GroupDetailPage {...props} data={{ ...groupDetailData, own_product: null }} />)).toContain("尚未绑定我方商品");
  expect(renderToStaticMarkup(<GroupDetailPage {...props} rangeError="请求失败" />)).toContain("保留上一份事实");
  expect(renderToStaticMarkup(<GroupDetailPage {...props} data={{ ...groupDetailData, competitors: [] }} />)).toContain("仅我方 1 条");
});

test("sorts using authoritative directional competition ranks, ties by id and unknowns last", () => {
  const offers = [groupProduct({ id: 4 }), groupProduct({ id: 2 }), groupProduct({ id: 3 }), groupProduct({ id: 1 })];
  const position = { ...testPosition, offers: {
    1: { eligible: true, reason: null, sort_value: "9", rank_asc: 1, rank_desc: 2 },
    2: { eligible: true, reason: null, sort_value: "9", rank_asc: 1, rank_desc: 2 },
    3: { eligible: true, reason: null, sort_value: "100", rank_asc: 3, rank_desc: 1 },
    4: { eligible: false, reason: "offline", sort_value: null, rank_asc: null, rank_desc: null },
  } };
  expect(sortGroupOffers(offers, position, "asc").map(item => item.id)).toEqual([1, 2, 3, 4]);
  expect(sortGroupOffers(offers, position, "desc").map(item => item.id)).toEqual([3, 1, 2, 4]);
  expect(sortGroupOffers(offers, undefined, "desc").map(item => item.id)).toEqual([1, 2, 3, 4]);
});

test("shows own role in list and detail and limits bind candidates to group members", () => {
  const own = { ...competitor, id: 7, group_id: 1, group_role: "own" as const, ownership: "self" as const, title: null };
  const list = renderToStaticMarkup(<ListPage {...listProps} competitors={[own]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(list).toContain("我方");
  const detail = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, competitor: { ...detailData.competitor, group_role: "own", ownership: "self" } }} status="ready" error={null} />);
  expect(detail).toContain("我方商品");
  const dialog = renderToStaticMarkup(<OwnProductDialog group={{ ...groupSummary, own_product: { id: own.id, offer_id: own.offer_id, title: null, shop_name: null, main_image_url: null, status: "unknown", is_active: true } }} mode="bind" competitors={[own, { ...competitor, id: 8, group_id: null }, { ...competitor, id: 9, group_id: 1, offer_id: "909" }]} loading={false} selectedId={null} confirming={false} submitting={false} error={null} onSelect={noop} onConfirmStep={noop} onClose={noop} onSubmit={noop} />);
  expect(dialog).toContain("Offer 909");
  expect(dialog).not.toContain("Offer 123456789");
  const replacement = renderToStaticMarkup(<OwnProductDialog group={{ ...groupSummary, own_product: { id: 7, offer_id: "700", title: "原商品", shop_name: null, main_image_url: null, status: "active", is_active: true } }} mode="replace" competitors={[{ ...competitor, id: 9, group_id: 1, offer_id: "909", title: "新商品" }]} loading={false} selectedId={9} confirming submitting error="绑定失败" onSelect={noop} onConfirmStep={noop} onClose={noop} onSubmit={noop} />);
  expect(replacement).toContain("原商品");
  expect(replacement).toContain("新商品");
  expect(replacement).toContain("历史监控数据不会删除");
  expect(replacement).toContain("绑定失败");
  expect(replacement).toContain('disabled=""');
  const unbind = renderToStaticMarkup(<OwnProductDialog group={{ ...groupSummary, own_product: { id: 7, offer_id: "700", title: "原商品", shop_name: null, main_image_url: null, status: "active", is_active: true } }} mode="unbind" competitors={[]} loading={false} selectedId={null} confirming={false} submitting={false} error={null} onSelect={noop} onConfirmStep={noop} onClose={noop} onSubmit={noop} />);
  expect(unbind).toContain("仍保留在当前组");
  expect(unbind).toContain("历史数据不会删除");
});

test("uses ownership for an ungrouped self detail", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, competitor: { ...detailData.competitor, ownership: "self", group_id: null, group_role: "competitor" } }} status="ready" error={null} />);
  expect(html).toContain("我方商品详情");
  expect(html).toContain("返回我方商品");
  expect(html).toContain("删除我方商品");
  expect(html).not.toContain("直接竞品");
});

test("renders create and rename group dialogs with failure feedback", () => {
  const create = renderToStaticMarkup(<GroupNameDialog mode="create" name="" submitting={false} error={null} onChange={noop} onClose={noop} onSubmit={noop} />);
  const rename = renderToStaticMarkup(<GroupNameDialog mode="rename" name="A19" submitting={true} error="该竞品组已存在" onChange={noop} onClose={noop} onSubmit={noop} />);
  expect(create).toContain("新增竞品组");
  expect(create).toContain("使用商品型号命名，例如 A19、X6");
  expect(rename).toContain("重命名竞品组");
  expect(rename).toContain("该竞品组已存在");
  expect(rename).toContain('disabled=""');
  expect(getGroupNameErrorMessage("invalid_competitor_group_name")).toBe("请输入有效的竞品组名称");
});

test("batch group dialog distinguishes no target, unassigned, and a formal group", () => {
  const initial = renderToStaticMarkup(<BatchGroupAssignmentDialog targetGroupId={undefined} groups={[group]} selectedCount={2} eligibleCount={1} ownCount={1} submitting={false} error={null} onChange={noop} onClose={noop} onSubmit={noop} />);
  expect(initial).toContain("请选择竞品组");
  expect(initial).toContain("1 个我方商品不会参与本次批量分组");
  expect(initial).toContain('disabled=""');
  expect(initial).toContain('value="__unassigned__">未分组');
  const formal = renderToStaticMarkup(<BatchGroupAssignmentDialog targetGroupId={1} groups={[group]} selectedCount={1} eligibleCount={1} ownCount={0} submitting={false} error="更新失败" onChange={noop} onClose={noop} onSubmit={noop} />);
  expect(formal).toContain('value="1" selected=""');
  expect(formal).toContain("更新失败");
});

test("batch lifecycle dialogs expose stop and irreversible delete semantics", () => {
  const stop = renderToStaticMarkup(<BatchLifecycleDialog action="stop" selectedCount={3} eligibleCount={2} ownCount={0} submitting={false} error={null} onClose={noop} onConfirm={noop} />);
  expect(stop).toContain("停止监控 2 个商品？");
  expect(stop).toContain("变化历史都会保留");
  expect(stop).toContain(">确认停止</button>");

  const deleteWithOwn = renderToStaticMarkup(<BatchLifecycleDialog action="delete" selectedCount={3} eligibleCount={2} ownCount={1} submitting={false} error={"删除失败"} onClose={noop} onConfirm={noop} />);
  expect(deleteWithOwn).toContain("本次将永久删除 2 个直接竞品");
  expect(deleteWithOwn).toContain("1 个我方商品不会参与批量删除");
  expect(deleteWithOwn).toContain("此操作不可恢复");
  expect(deleteWithOwn).toContain("删除失败");
  expect(deleteWithOwn).toContain(">永久删除 2 个竞品</button>");
  expect(deleteWithOwn).not.toContain("0 个我方商品");
});

test("reports completed batch mutation when authoritative refresh is incomplete", () => {
  expect(getBatchRefreshNotice("已永久删除 2 个竞品", false)).toEqual({
    message: "操作已完成，但部分数据刷新失败，请刷新页面后确认最新状态",
    type: "error",
  });
  expect(getBatchRefreshNotice("已永久删除 2 个竞品", true)).toEqual({
    message: "已永久删除 2 个竞品",
    type: "success",
  });
});

test("reports refresh failure through the real batch delete flow", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    server: { host: "127.0.0.1", port: 0 },
    clearScreen: false,
  });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  let competitorReads = 0;
  let groupSummaryReads = 0;
  let deleteRequests = 0;
  const listedCompetitor: Competitor = { ...competitor, title: "待删除商品" };
  const dashboard = { date: "2026-09-29", stats: { monitored_competitors: 1, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] };
  const attention = { date: "2026-09-29", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] };
  const batchStatus = { status: "idle", outcome_code: null, total: 0, completed: 0, succeeded: 0, failed: 0, remaining: 0, verification_required: 0, current_competitor_id: null, browser_open: false, runner_active: false, items: [] };
  const groupSummary = { groups: [], unassigned: { competitor_count: 1, active_count: 1, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } };

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (key === "GET /api/dashboard/today") return json(dashboard);
    if (key === "GET /api/dashboard/group-attention") return json(attention);
    if (key === "GET /api/competitors/collect-batch/status") return json(batchStatus);
    if (key === "GET /api/competitors") return json(++competitorReads === 1 ? [listedCompetitor] : []);
    if (key === "GET /api/competitor-groups") return json([]);
    if (key === "GET /api/competitor-groups/summary") return json(++groupSummaryReads === 1 ? { message: "refresh failed" } : groupSummary, 500);
    if (key === "POST /api/competitors/delete-batch") {
      deleteRequests += 1;
      return json({ deleted_count: 1, competitor_ids: [listedCompetitor.id] });
    }
    return route.abort("blockedbyclient");
  });

  try {
    const baseUrl = server.resolvedUrls?.local[0];
    if (!baseUrl) throw new Error("Vite test server did not expose a local URL");
    await page.goto(baseUrl);
    await page.getByRole("button", { name: "竞品列表" }).click();
    await playwrightExpect(page.getByRole("heading", { name: "竞品列表" })).toBeVisible();
    await page.getByRole("checkbox", { name: "选择 待删除商品" }).check();
    await page.getByRole("button", { name: "批量操作（1）" }).click();
    await page.getByRole("menuitem", { name: "删除竞品（1）" }).click();
    await page.getByRole("button", { name: "永久删除 1 个竞品" }).click();

    await playwrightExpect(page.getByRole("dialog")).not.toBeVisible();
    await playwrightExpect(page.getByRole("status")).toContainText("操作已完成，但部分数据刷新失败，请刷新页面后确认最新状态");
    await playwrightExpect(page.getByRole("status")).not.toContainText("已永久删除 1 个竞品");
    await playwrightExpect(page.getByText("待删除商品")).not.toBeVisible();
    await playwrightExpect(page.getByRole("button", { name: "批量操作（0）" })).toBeVisible();
    expect(deleteRequests).toBe(1);
  } finally {
    await context.close();
    await browser.close();
    await server.close();
  }
});

test("polls cooling batches through retry and refreshes authoritative data once on completion", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    server: { host: "127.0.0.1", port: 0 },
    clearScreen: false,
  });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  let statusReads = 0;
  let competitorReads = 0;
  let todayReads = 0;
  let attentionReads = 0;
  const listedCompetitor: Competitor = { ...competitor, title: "自动恢复商品" };
  const dashboard = { date: "2026-09-29", stats: { monitored_competitors: 1, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] };
  const attention = { date: "2026-09-29", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] };
  const statuses = [
    makeBatchState("cooling_down", { cooldown_remaining_seconds: 17, auto_resume_attempt: 1 }),
    makeBatchState("cooling_down", { cooldown_remaining_seconds: 17, auto_resume_attempt: 1 }),
    makeBatchState("cooling_down", { cooldown_remaining_seconds: 11, auto_resume_attempt: 1 }),
    makeBatchState("running", { auto_resume_attempt: 1 }),
    makeBatchState("completed", { completed: 1, succeeded: 1, remaining: 0, current_competitor_id: null }),
  ];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (key === "GET /api/competitors/collect-batch/status") return json(statuses[Math.min(statusReads++, statuses.length - 1)]);
    if (key === "GET /api/dashboard/today") { todayReads += 1; return json(dashboard); }
    if (key === "GET /api/dashboard/group-attention") { attentionReads += 1; return json(attention); }
    if (key === "GET /api/competitors") { competitorReads += 1; return json([listedCompetitor]); }
    if (key === "GET /api/competitor-groups") return json([]);
    return route.abort("blockedbyclient");
  });

  try {
    const baseUrl = server.resolvedUrls?.local[0];
    if (!baseUrl) throw new Error("Vite test server did not expose a local URL");
    await page.goto(baseUrl);
    await page.getByRole("button", { name: "竞品列表" }).click();
    await playwrightExpect(page.locator(".batch-status-cooling_down")).toContainText("17 秒");
    await playwrightExpect(page.getByRole("button", { name: /批量操作/ })).toBeDisabled();
    await page.waitForTimeout(500);
    await playwrightExpect(page.locator(".batch-status-cooling_down")).toContainText("17 秒");
    await playwrightExpect(page.locator(".batch-status-cooling_down")).toContainText("11 秒", { timeout: 4000 });
    const refreshBaseline = { competitorReads, todayReads, attentionReads };
    await playwrightExpect(page.locator(".batch-status-panel")).toContainText("采集完成：成功 1，失败 0", { timeout: 6000 });
    await playwrightExpect.poll(() => statusReads, { timeout: 6000 }).toBeGreaterThanOrEqual(5);
    await playwrightExpect.poll(() => competitorReads, { timeout: 3000 }).toBe(refreshBaseline.competitorReads + 1);
    await playwrightExpect.poll(() => todayReads, { timeout: 3000 }).toBe(refreshBaseline.todayReads + 1);
    await playwrightExpect.poll(() => attentionReads, { timeout: 3000 }).toBe(refreshBaseline.attentionReads + 1);
    await playwrightExpect(page.locator(".toast")).toHaveCount(1);
    await playwrightExpect(page.locator(".toast")).toHaveText("采集完成：成功 1，失败 0");
  } finally {
    await context.close();
    await browser.close();
    await server.close();
  }
}, 15000);

test("refreshes after cooling_down completes directly and ignores historical completed on first load", async () => {
  const server = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    server: { host: "127.0.0.1", port: 0 },
    clearScreen: false,
  });
  await server.listen();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  let statusReads = 0;
  let competitorReads = 0;
  let todayReads = 0;
  let attentionReads = 0;
  const listedCompetitor: Competitor = { ...competitor, title: "直接完成商品" };
  const dashboard = { date: "2026-09-29", stats: { monitored_competitors: 1, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] };
  const attention = { date: "2026-09-29", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] };
  const statuses = [
    makeBatchState("cooling_down", { cooldown_remaining_seconds: 17, auto_resume_attempt: 1 }),
    makeBatchState("cooling_down", { cooldown_remaining_seconds: 17, auto_resume_attempt: 1 }),
    makeBatchState("completed", { completed: 1, succeeded: 1, remaining: 0, current_competitor_id: null }),
  ];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (key === "GET /api/competitors/collect-batch/status") return json(statuses[Math.min(statusReads++, statuses.length - 1)]);
    if (key === "GET /api/dashboard/today") { todayReads += 1; return json(dashboard); }
    if (key === "GET /api/dashboard/group-attention") { attentionReads += 1; return json(attention); }
    if (key === "GET /api/competitors") { competitorReads += 1; return json([listedCompetitor]); }
    if (key === "GET /api/competitor-groups") return json([]);
    return route.abort("blockedbyclient");
  });

  try {
    const baseUrl = server.resolvedUrls?.local[0];
    if (!baseUrl) throw new Error("Vite test server did not expose a local URL");
    await page.goto(baseUrl);
    await page.getByRole("button", { name: "竞品列表" }).click();
    await playwrightExpect(page.locator(".batch-status-cooling_down")).toContainText("17 秒");
    const refreshBaseline = { competitorReads, todayReads, attentionReads };
    await playwrightExpect(page.locator(".batch-status-panel")).toContainText("采集完成：成功 1，失败 0", { timeout: 4000 });
    await playwrightExpect.poll(() => competitorReads, { timeout: 3000 }).toBe(refreshBaseline.competitorReads + 1);
    await playwrightExpect.poll(() => todayReads, { timeout: 3000 }).toBe(refreshBaseline.todayReads + 1);
    await playwrightExpect.poll(() => attentionReads, { timeout: 3000 }).toBe(refreshBaseline.attentionReads + 1);
    await playwrightExpect(page.locator(".toast")).toHaveCount(1);
    await page.reload();
    await playwrightExpect(page.locator(".collection-batch")).toContainText("最近批次完成");
    await playwrightExpect(page.locator(".toast")).toHaveCount(0);
  } finally {
    await context.close();
    await browser.close();
    await server.close();
  }
}, 15000);

test("generic selection count includes inactive and own rows while lifecycle menu eligibility stays distinct", () => {
  const inactive = { ...competitor, id: 2, offer_id: "inactive", title: "已停止商品", is_active: false };
  const own = { ...competitor, id: 3, offer_id: "own", title: "我方商品", group_id: 1, group_role: "own" as const };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor, inactive, own]} selectedIds={new Set([competitor.id, inactive.id, own.id])} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("批量操作（3）");
  expect(html).toContain('aria-label="选择 已停止商品" checked=""');
  expect(html).toContain('aria-label="选择 我方商品" checked=""');
});

test("renders delete confirmation with the real competitor count and protects submitting state", () => {
  const html = renderToStaticMarkup(<GroupDeleteDialog group={groupSummary} submitting={true} error="删除失败" onClose={noop} onConfirm={noop} />);
  expect(html).toContain("删除竞品组“暖手宝”？");
  expect(html).toContain("该组下有 3 个竞品");
  expect(html).toContain("3 个竞品将移至“未分组”");
  expect(html).toContain("删除失败");
  expect(html).toContain("删除中…");
});

const detailData: CompetitorDetail = {
  range_days: 7,
  competitor: {
    id: 1,
    platform: "1688",
    offer_id: "123456789",
    url: "https://detail.1688.com/offer/123456789.html",
    group_id: 1,
    group_role: "competitor",
    ownership: "competitor",
    title: "暖手宝商品",
    shop_name: "家居店",
    main_image_url: null,
    status: "offline",
    is_active: false,
    created_at: "2026-09-19T10:00:00Z",
    last_collected_at: "2026-09-20T10:00:00Z",
  },
  latest_snapshot: {
    id: 9,
    captured_at: "2026-09-20T10:00:00Z",
    price_min: "40.00",
    price_max: "45.00",
    image_urls: null,
    product_status: "unknown",
    sku_count: 2,
    total_stock: null,
    min_order_quantity: 1,
  },
  latest_skus: [
    { sku_id: "sku-0", sku_name: "红色", stock: 0, price: null },
    { sku_id: "sku-null", sku_name: "蓝色", stock: null, price: "41.00" },
  ],
  latest_price_change: latestChange({ id: 7, change_type: "price_increase", old_value: "38.00", new_value: "40.00" }),
  daily_trend: [
    { date: "2026-09-18", snapshot_id: 1, captured_at: "2026-09-18T10:00:00Z", price_min: "38.00", price_max: "42.00", total_stock: 12 },
    { date: "2026-09-19", snapshot_id: null, captured_at: null, price_min: null, price_max: null, total_stock: null },
    { date: "2026-09-20", snapshot_id: 2, captured_at: "2026-09-20T10:00:00Z", price_min: "40.00", price_max: "45.00", total_stock: null },
  ],
  recent_changes: [latestChange({ id: 8, change_type: "price_increase", old_value: "38.00", new_value: "40.00" })],
  recent_collection_runs: [
    { id: 2, started_at: "2026-09-20T10:00:00Z", finished_at: "2026-09-20T10:00:02Z", status: "success", error_type: null, error_message: null },
    { id: 1, started_at: "2026-09-19T10:00:00Z", finished_at: "2026-09-19T10:00:02Z", status: "failed", error_type: "collection_timeout", error_message: "请求超时" },
    { id: 3, started_at: "2026-09-18T10:00:00Z", finished_at: null, status: "running", error_type: null, error_message: null },
  ],
};

const detailProps = { groups: [group], days: 7 as const, onRetry: noop, onRangeChange: noop, onBack: noop, onNavigate: noop };

test("renders detail loading, error and local empty states", () => {
  expect(renderToStaticMarkup(<DetailPage {...detailProps} data={null} status="loading" error={null} />)).toContain("正在加载竞品详情");
  expect(renderToStaticMarkup(<DetailPage {...detailProps} data={null} status="error" error="请求失败" />)).toContain("重试");
  const empty = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, latest_snapshot: null, latest_skus: [], latest_price_change: null, daily_trend: [], recent_changes: [], recent_collection_runs: [] }} status="ready" error={null} />);
  expect(empty).toContain("暂无采集数据");
  expect(empty).toContain("该时间范围暂无可用价格数据");
  expect(empty).toContain("暂无 SKU 数据");
  expect(empty).toContain("暂无变化记录");
  expect(empty).toContain("暂无采集记录");
});

test("renders detail overview, mapped group, inactive status and latest sku null semantics", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={detailData} status="ready" error={null} />);
  expect(html).toContain("暖手宝商品");
  expect(html).toContain("家居店");
  expect(html).toContain("123456789");
  expect(html).toContain("暖手宝");
  expect(html).toContain("¥40.00 ~ ¥45.00");
  expect(html).toContain('class="detail-overview table-card"');
  expect(html).not.toContain('detail-overview detail-section-card');
  expect(html).not.toContain('detail-overview detail-table-scroll');
  expect(html).toContain("已停止监控");
  expect(html).toContain("红色");
  expect(html).toContain(">0<");
  expect(html).toContain("蓝色");
  expect(html).toContain("¥41.00");
  expect(html).toContain("—");
});

test("single-product detail renders original operating metric values and missing states", () => {
  const source = "1688_official_procurement_assistant_top";
  const definitions = [
    ["listing_time", "上架时间", "经营表现", "observed", "2025-01-02"],
    ["monthly_deal", "月成交", "经营表现", "observed", "20+"],
    ["monthly_dropship", "月代销", "经营表现", "placeholder", "-"],
    ["annual_units", "年成交件数", "经营表现", "loading", null],
    ["annual_orders", "年成交笔数", "经营表现", "source_unavailable", null],
    ["review_count", "评论数", "口碑履约", "read_failed", null],
    ["positive_rate", "好评率", "口碑履约", "observed", "95.6%"],
    ["pickup_rate", "揽收率", "口碑履约", "placeholder", "-"],
  ] as const;
  const operatingMetrics = definitions.map(([metric_key, label, section, status, raw_value], index) => ({
    metric_key, label, section, eligible: true, status,
    latest_attempt: { collection_run_id: 9, status, raw_value, source, observed_at: `2026-10-10T0${index}:00:00Z`, reason: status === "observed" || status === "placeholder" ? null : "脱敏 Fixture 状态" },
    latest_valid: status === "observed" ? { collection_run_id: 9, raw_value: raw_value!, source, observed_at: `2026-10-10T0${index}:00:00Z` } : null,
  }));
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{
    ...detailData,
    latest_collection_run: { id: 9, started_at: "2026-10-10T00:00:00Z", finished_at: "2026-10-10T00:08:00Z", status: "success", operating_metrics_status: "partial", error_type: null, error_message: null },
    operating_metrics: [...operatingMetrics, { metric_key: "favorite_count", label: "收藏数", section: "口碑履约", eligible: false, status: "not_attempted", latest_attempt: null, latest_valid: null }],
  }} status="ready" error={null} />);

  for (const [, label] of definitions) expect(html).toContain(label);
  for (const [, , , status, rawValue] of definitions) if (status === "observed" && rawValue) expect(html).toContain(rawValue);
  expect(html).toContain("经营采集：部分成功");
  expect(html).toContain("有效值来源：1688 官方采购助手顶部区域");
  expect(html).toContain("有效值时间：");
  expect(html).toContain("页面显示占位符（-）");
  expect(html).toContain("仍在加载");
  expect(html).toContain("来源不可用");
  expect(html).toContain("读取失败");
  expect(html).toContain("收藏数");
  expect(html).toContain("待接入");
});

test("renders monitored offline notice and lifecycle recent change", () => {
  const html = renderToStaticMarkup(
    <DetailPage
      {...detailProps}
      data={{
        ...detailData,
        competitor: { ...detailData.competitor, is_active: true },
        recent_changes: [latestChange({ change_type: "product_offline", snapshot_id: null })],
      }}
      status="ready"
      error={null}
    />,
  );

  expect(html).toContain("已下架");
  expect(html).toContain("该商品已下架，目前仍在监控。");
  expect(html).toContain("商品已下架");
  expect(html).toContain("检测时间");
});

test("keeps detail history cards and their scoped scroll containers", () => {
  const data = { ...detailData, recent_changes: [{ ...latestChange({ change_type: "stock_changed", entity_key: "6298697170559", old_value: "998", new_value: "994" }), sku_name: "粉色>A19" }] };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={data} status="ready" error={null} />);
  expect((html.match(/detail-section-card/g) || []).length).toBe(4);
  expect((html.match(/detail-table-scroll/g) || []).length).toBe(2);
  expect(html).toContain("detail-record-list");
  expect(html).toContain("粉色&gt;A19 · 库存 998 → 994");
  expect(html).not.toContain("onWheel");
});

test("detail collection history shows operating status and legacy runs as not collected", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, recent_collection_runs: [
    { id: 8, started_at: "2026-10-10T00:00:00Z", finished_at: "2026-10-10T00:00:02Z", status: "success", operating_metrics_status: "partial", error_type: null, error_message: null },
    { id: 7, started_at: "2026-10-09T00:00:00Z", finished_at: "2026-10-09T00:00:02Z", status: "failed", error_type: "collection_timeout", error_message: "请求超时" },
  ] }} status="ready" error={null} />);
  expect(html).toContain("成功 · 经营部分成功");
  expect(html).toContain("失败 · 经营未采集");
});

test("detail keeps status in the summary and exposes group assignment", () => {
  const active = { ...detailData, competitor: { ...detailData.competitor, status: "active" as const, is_active: true } };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={active} status="ready" error={null} onChangeGroup={noop} />);
  expect(html).toContain("所属竞品组");
  expect(html).toContain(">修改</button>");
  expect((html.match(/status-badge status-active/g) || []).length).toBe(1);
  expect(html).toContain("商品状态");
  expect(html).toContain("监控状态");
  expect(html).toContain("当前库存");
  expect(html).toContain("SKU 数量");
  expect(html).toContain("最近采集时间");
});

test("group assignment dialog keeps the current group selected and supports unassigned", () => {
  const html = renderToStaticMarkup(<GroupAssignmentDialog groupId={1} groups={[group, { ...group, id: 2, name: "X6" }]} submitting={false} error={null} onChange={noop} onClose={noop} onSubmit={noop} />);
  expect(html).toContain("修改竞品组");
  expect(html).toContain("调整当前竞品所属的竞品组。");
  expect(html).toContain('value=""');
  expect(html).toContain("未分组");
  expect(html).toContain("暖手宝");
  expect(html).toContain("X6");
  expect(html).toContain('value="1"');
});

test("group assignment dialog preserves errors and disables controls while saving", () => {
  const html = renderToStaticMarkup(<GroupAssignmentDialog groupId={null} groups={[]} submitting={true} error="竞品组不存在" onChange={noop} onClose={noop} onSubmit={noop} />);
  expect(html).toContain("竞品组不存在");
  expect(html).toContain('disabled=""');
  expect(getGroupAssignmentErrorMessage("competitor_group_not_found")).toBe("竞品组不存在");
});

test("group assignment flow sends the target group and supports unassigned", async () => {
  const calls: { url: string; body: { group_id: number | null } }[] = [];
  const request = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), body: JSON.parse(String(init?.body)) as { group_id: number | null } });
    return { ok: true } as Response;
  };

  await expect(updateCompetitorGroup(7, 2, request)).resolves.toEqual({ ok: true });
  await expect(updateCompetitorGroup(7, null, request)).resolves.toEqual({ ok: true });
  expect(calls).toEqual([
    { url: "/api/competitors/7/group", body: { group_id: 2 } },
    { url: "/api/competitors/7/group", body: { group_id: null } },
  ]);
});

test("group assignment flow keeps the error result for a failed PATCH", async () => {
  const result = await updateCompetitorGroup(7, 2, async () => ({ ok: false, json: async () => ({ code: "competitor_group_not_found" }) } as Response));
  expect(result).toEqual({ ok: false, message: "竞品组不存在" });
});

test("renders detail lifecycle actions for active and inactive competitors", () => {
  const active = { ...detailData, competitor: { ...detailData.competitor, is_active: true } };
  const activeHtml = renderToStaticMarkup(<DetailPage {...detailProps} data={active} status="ready" error={null} />);
  expect(activeHtml).toContain(">停止监控</button>");
  expect(activeHtml).toContain(">删除竞品</button>");
  expect(activeHtml).not.toContain(">恢复监控</button>");

  const inactiveHtml = renderToStaticMarkup(<DetailPage {...detailProps} data={detailData} status="ready" error={null} />);
  expect(inactiveHtml).toContain(">恢复监控</button>");
  expect(inactiveHtml).toContain(">删除竞品</button>");
  expect(inactiveHtml).not.toContain(">停止监控</button>");
});

test("detail lifecycle callbacks receive the detail competitor", () => {
  const calls: { action: string; competitor: unknown }[] = [];
  const active = { ...detailData, competitor: { ...detailData.competitor, is_active: true } };
  const page = DetailPage({ ...detailProps, data: active, status: "ready", error: null, onLifecycleAction: (action, received) => calls.push({ action, competitor: received }) }) as any;
  const header = page.props.children[0];
  const actions = header.props.children[1];
  actions.props.children[1].props.onClick();
  expect(calls).toEqual([{ action: "stop", competitor: active.competitor }]);
});

test("keeps detail content mounted while a trend range refresh is pending", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={detailData} status="ready" error={null} rangeLoading />);
  expect(html).toContain("暖手宝商品");
  expect(html).toContain("更新中…");
  expect(html).toContain('aria-busy="true"');
  expect((html.match(/disabled=""/g) || []).length).toBeGreaterThanOrEqual(2);
  expect(html).not.toContain("正在加载竞品详情");
});

test("renders price chart data, selector state, changes and collection statuses", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} days={30} data={{ ...detailData, range_days: 30 }} status="ready" error={null} />);
  expect(html).toContain('aria-pressed="true"');
  expect(html).toContain("近 30 天");
  expect(html).toContain("价格趋势");
  expect(html).toContain("商品涨价 38.00 → 40.00");
  expect(html).toContain("成功");
  expect(html).toContain("结束时间");
  expect(html).toContain("请求超时");
  expect(html).toContain("采集中");
  expect(html).toContain("<svg");
});

test("price chart points preserve empty dates and keep real values", () => {
  const points = buildPriceChartPoints([
    { date: "2026-09-18", snapshot_id: 1, captured_at: "2026-09-18T10:00:00Z", price_min: null, price_max: null, total_stock: null },
    { date: "2026-09-20", snapshot_id: 2, captured_at: "2026-09-20T10:00:00Z", price_min: "40.00", price_max: null, total_stock: null },
  ]);
  expect(points).toHaveLength(2);
  expect(points[0].date).toBe("2026-09-18");
  expect(points[0].min_y).toBeNull();
  expect(points[1].snapshot_id).toBe(2);
  expect(points[1].min_y).not.toBeNull();
  expect(points[1].max_y).toBeNull();
});

test("detail trend hit areas cover the plot once without gaps", () => {
  const areas = buildTrendHitAreas([{ x: 54 }, { x: 339 }, { x: 624 }], 54, 624);
  expect(areas).toEqual([
    { x: 54, width: 142.5, center: 54 },
    { x: 196.5, width: 285, center: 339 },
    { x: 481.5, width: 142.5, center: 624 },
  ]);
  expect(areas[0].x).toBe(54);
  expect(areas[areas.length - 1].x + areas[areas.length - 1].width).toBe(624);
  expect(areas.reduce((total, area) => total + area.width, 0)).toBe(570);
});

test.each([7, 30] as const)("detail trend renders one hit area per date for %s points", (length) => {
  const dailyTrend = Array.from({ length }, (_, index) => ({ date: `2026-09-${String(index + 1).padStart(2, "0")}`, snapshot_id: index === 1 ? null : index + 1, captured_at: null, price_min: index === 1 ? null : "38.80", price_max: index === 1 ? null : "40.00", total_stock: index === 1 ? null : 1454 }));
  const html = renderToStaticMarkup(<DetailPage {...detailProps} days={length} data={{ ...detailData, range_days: length, daily_trend: dailyTrend }} status="ready" error={null} />);
  expect((html.match(/class="chart-hit-area"/g) || []).length).toBe(length * 2);
  expect(html).not.toContain("库存 0");
  expect(html).not.toContain("价格 ¥0");
});

test("price chart centers constant prices and uses the compact viewBox", () => {
  const points = buildPriceChartPoints([
    { date: "2026-09-18", snapshot_id: 1, captured_at: "2026-09-18T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null },
    { date: "2026-09-19", snapshot_id: 2, captured_at: "2026-09-19T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null },
    { date: "2026-09-20", snapshot_id: 3, captured_at: "2026-09-20T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null },
  ]);
  expect(points).toHaveLength(3);
  expect(points.every((point) => Number.isFinite(point.min_y) && Number.isFinite(point.max_y))).toBe(true);
  expect(points.every((point) => point.min_y === point.max_y)).toBe(true);

  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={detailData} status="ready" error={null} />);
  expect(html).toContain('viewBox="0 0 640 170"');
  expect(html).not.toContain('viewBox="0 0 640 220"');
});

test("price and stock scales pad their data without forcing zero", () => {
  const price = buildPriceChartScale([
    { date: "2026-09-19", snapshot_id: 1, captured_at: null, price_min: "38.00", price_max: "40.00", total_stock: null },
  ])!;
  const stock = buildStockChartScale([
    { date: "2026-09-19", snapshot_id: 1, captured_at: null, price_min: null, price_max: null, total_stock: 1454 },
  ])!;
  expect(price.domain[0]).toBeGreaterThan(0);
  expect(price.ticks.every((tick) => Number.isFinite(tick))).toBe(true);
  expect(stock.domain[0]).toBeGreaterThan(0);
  expect(stock.domain[0]).toBeLessThan(1454);
  expect(stock.domain[1]).toBeGreaterThan(1454);
  expect(stock.ticks.every(Number.isInteger)).toBe(true);
  expect(formatPriceTick(price.ticks[1], price.step)).toMatch(/^¥\d+(\.\d+)?$/);
});

test("constant prices and inventory expand their domains", () => {
  const trend = Array.from({ length: 3 }, (_, index) => ({ date: `2026-09-${String(index + 18).padStart(2, "0")}`, snapshot_id: index + 1, captured_at: null, price_min: "38.80", price_max: "38.80", total_stock: 1454 }));
  const price = buildPriceChartScale(trend)!;
  const stock = buildStockChartScale(trend)!;
  expect(price.domain[0]).toBeLessThan(38.8);
  expect(price.domain[1]).toBeGreaterThan(38.8);
  expect(stock.domain[0]).toBeLessThan(1454);
  expect(stock.domain[1]).toBeGreaterThan(1454);
});

test("detail formatters keep stock, price-change, range and tooltip semantics", () => {
  expect(formatDetailPriceDisplay(detailData.latest_snapshot)).toBe("¥40.00 ~ ¥45.00");
  expect(formatStockDisplay(9998)).toBe("9,998");
  expect(formatPriceChangeTransition(latestChange({ old_value: "40.00", new_value: "38.00", change_type: "price_decrease" }))).toBe("¥40.00 → ¥38.00");
  expect(formatPriceChangeMagnitude(latestChange({ old_value: "40.00", new_value: "38.00", change_type: "price_decrease" }))).toBe("↓ 5.0%");
  expect(formatPriceChangeMagnitude(latestChange({ old_value: "40.00~50.00", new_value: "38.00~48.00", change_type: "price_decrease" }))).toBe("—");
  expect(formatPriceChangeMagnitude(null)).toBe("—");
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null }, "price")).toEqual(["09/20", "价格 ¥38.80"]);
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: "79", price_max: "89", total_stock: null }, "price")).toEqual(["09/20", "最低价 ¥79.00", "最高价 ¥89.00"]);
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: null, price_max: null, total_stock: null }, "price")).toEqual([]);
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: null, price_max: null, total_stock: 9998 }, "stock")).toEqual(["09/20", "库存 9,998"]);
});

test("7-day and 30-day trend scales are computed from their current data", () => {
  const sevenDays = [
    { date: "2026-09-14", snapshot_id: 1, captured_at: null, price_min: "38", price_max: "39", total_stock: 100 },
    { date: "2026-09-20", snapshot_id: 2, captured_at: null, price_min: "40", price_max: "41", total_stock: 110 },
  ];
  const thirtyDays = [...sevenDays, { date: "2026-09-01", snapshot_id: 3, captured_at: null, price_min: "80", price_max: "90", total_stock: 900 }];
  expect(buildPriceChartScale(sevenDays)!.domain).not.toEqual(buildPriceChartScale(thirtyDays)!.domain);
  expect(buildStockChartScale(sevenDays)!.domain).not.toEqual(buildStockChartScale(thirtyDays)!.domain);
});

test("detail renders the overview, three trend cards, shared selector, placeholder and bottom facts", () => {
  const withImage = { ...detailData, competitor: { ...detailData.competitor, main_image_url: "https://img.example.com/item.jpg", group_id: 1 }, latest_snapshot: { ...detailData.latest_snapshot!, image_urls: ["https://img.example.com/item.jpg", "https://img.example.com/item-2.jpg", "https://img.example.com/item-3.jpg"], total_stock: 9998 } };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={withImage} status="ready" error={null} />);
  expect(html).toContain("https://img.example.com/item.jpg");
  expect(html).toContain('referrerPolicy="no-referrer"');
  expect(html).toContain('class="detail-gallery-thumbnails"');
  expect(html).toContain('class="detail-gallery-viewport"');
  expect(html).toContain('class="detail-gallery-strip"');
  expect((html.match(/class="detail-gallery-thumbnail"/g) || []).length).toBe(3);
  expect(html).toContain('class="detail-gallery-thumbnail-button detail-gallery-thumbnail-selected"');
  expect(html).not.toContain("向右滚动商品图库");
  expect(html).toContain("detail-group-badge");
  expect(html).toContain("当前库存");
  expect(html).toContain(">9998<");
  expect(html).toContain("最近变价");
  expect(html).toContain("价格趋势");
  expect(html).toContain("库存趋势");
  expect(html).toContain("销量趋势");
  expect(html).toContain("销量数据待接入");
  expect(html).toContain("当前数据源尚未达到正式采集标准");
  expect(html).toContain("近 7 天");
  expect(html).toContain("SKU 信息");
  expect(html).toContain("SKU 价格");
  expect(html).toContain("起批量");
  expect(html).toContain("最近变化");
  expect(html).toContain("最近采集记录");
  expect(html).not.toContain("saleQuantityList");
});

test("detail gallery shows only the right scroll arrow when thumbnails overflow", () => {
  const imageUrls = Array.from({ length: 5 }, (_, index) => `https://img.example.com/item-${index + 1}.jpg`);
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, competitor: { ...detailData.competitor, main_image_url: imageUrls[0] }, latest_snapshot: { ...detailData.latest_snapshot!, image_urls: imageUrls } }} status="ready" error={null} />);
  expect(html).toContain('aria-label="向右滚动商品图库"');
  expect(html).not.toContain('aria-label="向左滚动商品图库"');
  expect(html).toContain('width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"');
  expect(html).not.toContain("‹");
  expect(html).not.toContain("›");
});

test("detail gallery keeps the 44px scroll step and handles overflow boundaries with tolerance", () => {
  expect(DETAIL_GALLERY_SCROLL_STEP).toBe(44);
  expect(getGalleryScrollState(0, 172, 172)).toEqual({ canScrollLeft: false, canScrollRight: false });
  expect(getGalleryScrollState(0, 272, 172)).toEqual({ canScrollLeft: false, canScrollRight: true });
  expect(getGalleryScrollState(1, 272, 172)).toEqual({ canScrollLeft: false, canScrollRight: true });
  expect(getGalleryScrollState(2, 272, 172)).toEqual({ canScrollLeft: true, canScrollRight: true });
  expect(getGalleryScrollState(99, 272, 172)).toEqual({ canScrollLeft: true, canScrollRight: false });
});

test("detail gallery arrows scroll 44px and thumbnail failure refreshes after hiding the image", () => {
  const scrollBy = vi.fn();
  scrollDetailGallery({ scrollBy }, 1);
  expect(scrollBy).toHaveBeenCalledWith({ left: 44, behavior: "smooth" });

  const setAttribute = vi.fn();
  const updateScrollState = vi.fn();
  const scheduleFrame = vi.fn((callback: () => void) => {
    callback();
    return 1;
  });
  const image = { parentElement: { setAttribute } } as unknown as HTMLImageElement;
  hideDetailGalleryThumbnail({ currentTarget: image }, updateScrollState, scheduleFrame);
  expect(setAttribute).toHaveBeenCalledWith("hidden", "true");
  expect(scheduleFrame).toHaveBeenCalledOnce();
  expect(updateScrollState).toHaveBeenCalledOnce();
});

test("detail gallery resets its rendered preview when the detail data changes", () => {
  const firstImage = "https://img.example.com/first.jpg";
  const secondImage = "https://img.example.com/second.jpg";
  const first = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, competitor: { ...detailData.competitor, id: 1, main_image_url: firstImage }, latest_snapshot: { ...detailData.latest_snapshot!, id: 9, image_urls: [firstImage] } }} status="ready" error={null} />);
  const second = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, competitor: { ...detailData.competitor, id: 2, main_image_url: secondImage }, latest_snapshot: { ...detailData.latest_snapshot!, id: 10, image_urls: [secondImage] } }} status="ready" error={null} />);
  expect(first).toContain(firstImage);
  expect(second).toContain(secondImage);
  expect(second).not.toContain(firstImage);
});

test.each([1, 2])("detail renders product minimum order quantity %s", (quantity) => {
  const data = { ...detailData, latest_snapshot: { ...detailData.latest_snapshot!, min_order_quantity: quantity } };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={data} status="ready" error={null} />);
  expect(html).toContain(`起批量`);
  expect(html).toContain(`${quantity}件起批`);
  expect(html.indexOf("offerId")).toBeLessThan(html.indexOf("起批量"));
  expect(html.indexOf("起批量")).toBeLessThan(html.indexOf("所属竞品组"));
  expect(html).not.toContain("按SKU");
});

test("detail keeps SKU prices at the SKU level", () => {
  const data = {
    ...detailData,
    latest_skus: [
      { ...detailData.latest_skus[0], price: "79.00" },
      { ...detailData.latest_skus[1], price: "89.00" },
    ],
  };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={data} status="ready" error={null} />);
  expect(html).toContain("¥79.00");
  expect(html).toContain("¥89.00");
});

test("detail renders null product minimum order quantity as a dash and removes it from SKU table", () => {
  const data = { ...detailData, latest_snapshot: { ...detailData.latest_snapshot!, min_order_quantity: null } };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={data} status="ready" error={null} />);
  expect(html).toContain("起批量");
  expect(html).toContain("SKU 价格");
  expect(html).not.toContain("<span>起批量</span>");
  expect(html).not.toContain("<th>起批量</th>");
  expect(html).not.toContain("按SKU");
});

test("detail uses placeholders for missing image and stock", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, latest_snapshot: { ...detailData.latest_snapshot!, total_stock: null } }} status="ready" error={null} />);
  expect(html).toContain("暂无主图");
  expect(html).toContain("当前库存");
  expect(html).toContain(">—<");
});

test("detail gallery uses legacy main image only for a null snapshot gallery", () => {
  expect(getDetailGallery(null, "https://img.example.com/item.jpg")).toEqual(["https://img.example.com/item.jpg"]);
  expect(getDetailGallery([], "https://img.example.com/item.jpg")).toEqual([]);
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, competitor: { ...detailData.competitor, main_image_url: "https://img.example.com/item.jpg" }, latest_snapshot: { ...detailData.latest_snapshot!, image_urls: null } }} status="ready" error={null} />);
  expect(html).toContain("https://img.example.com/item.jpg");
  expect(html).toContain('class="detail-gallery-thumbnails"');
});

test("detail keeps 30 daily points and does not render null stock as zero", () => {
  const dailyTrend = Array.from({ length: 30 }, (_, index) => ({ date: `2026-08-${String(index + 1).padStart(2, "0")}`, snapshot_id: null, captured_at: null, price_min: null, price_max: null, total_stock: null }));
  const html = renderToStaticMarkup(<DetailPage {...detailProps} days={30} data={{ ...detailData, range_days: 30, daily_trend: dailyTrend }} status="ready" error={null} />);
  expect(html).toContain("近 30 天");
  expect(buildStockChartPoints(dailyTrend)).toEqual([]);
  expect(html).not.toContain("库存 0");
});

test("detail keeps competitor list active in the sidebar", () => {
  const html = renderToStaticMarkup(<Sidebar page="detail" onNavigate={noop} />);
  expect(html).toContain('class="nav-item nav-child nav-active" aria-current="page"');
  expect(html).toContain("竞品列表");
});

test("only the newest competitor detail request remains current", () => {
  let latestRequestId = 0;
  const requestA = ++latestRequestId;
  const requestB = ++latestRequestId;

  expect(isCurrentDetailRequest(requestB, latestRequestId)).toBe(true);
  expect(isCurrentDetailRequest(requestA, latestRequestId)).toBe(false);
});

test("a newer 7-day request invalidates an older 30-day response", () => {
  let latestRequestId = 0;
  const thirtyDayRequest = ++latestRequestId;
  const sevenDayRequest = ++latestRequestId;

  expect(isCurrentDetailRequest(sevenDayRequest, latestRequestId)).toBe(true);
  expect(isCurrentDetailRequest(thirtyDayRequest, latestRequestId)).toBe(false);
});

test("an older detail error cannot replace the newer successful request", () => {
  let latestRequestId = 0;
  const oldRequest = ++latestRequestId;
  const currentRequest = ++latestRequestId;
  let state = "loading";

  if (isCurrentDetailRequest(currentRequest, latestRequestId)) state = "ready";
  if (isCurrentDetailRequest(oldRequest, latestRequestId)) state = "error";

  expect(state).toBe("ready");
});
