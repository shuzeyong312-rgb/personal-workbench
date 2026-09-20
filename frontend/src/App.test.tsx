import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { AddDialog, Competitor, CompetitorDetail, CompetitorGroup, DashboardData, DashboardPage, DeleteDialog, DetailPage, formatChange, formatLatestChange, getCollectionErrorMessage, getCollectionFailureMessage, getCollectionRequestErrorMessage, getCompetitorGroupLabel, getGroupFeedbackClass, getResponseStatus, isCurrentDetailRequest, ListPage, Sidebar, buildPriceChartPoints } from "./App";

const competitor: Competitor = {
  id: 1,
  platform: "1688",
  offer_id: "123456789",
  url: "https://detail.1688.com/offer/123456789.html",
  group_id: null,
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
const listProps = { collectingCompetitorId: null, deletingCompetitorId: null, onCollect: noop, onDelete: noop, groups: [] as CompetitorGroup[] };
const group: CompetitorGroup = { id: 1, name: "暖手宝", created_at: "2026-09-20T10:00:00Z" };
const latestChange = (overrides: Partial<NonNullable<Competitor["latest_change"]>> = {}): NonNullable<Competitor["latest_change"]> => ({
  id: 1,
  snapshot_id: 2,
  change_type: "title_changed",
  entity_key: null,
  old_value: null,
  new_value: null,
  detected_at: "2026-09-20T10:00:00Z",
  ...overrides,
});

test.each([
  [true, undefined, "success"],
  [false, "invalid_competitor_url", "invalid"],
  [false, "competitor_already_exists", "duplicate"],
] as const)("maps API result to %s UI state", (ok, code, expected) => {
  expect(getResponseStatus(ok, code)).toBe(expected);
});

test("renders loading, empty, error and normal list states", () => {
  expect(renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="loading" error={null} onRetry={noop} onAdd={noop} />)).toContain("正在加载竞品列表");
  expect(renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="ready" error={null} onRetry={noop} onAdd={noop} />)).toContain("还没有添加竞品");
  expect(renderToStaticMarkup(<ListPage {...listProps} competitors={[]} status="error" error="请求失败" onRetry={noop} onAdd={noop} />)).toContain("重试");
  const normal = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(normal).toContain("未采集");
  expect(normal).toContain("123456789");
  expect(normal).toContain("查看 1688 商品");
  expect(normal).toContain("暂无变化记录");
  expect(normal).toContain("立即采集");
  expect(normal).toContain(">删除<");
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
  [latestChange({ change_type: "price_increase", old_value: "40.00", new_value: "45.00" }), "价格上涨 40.00 → 45.00"],
  [latestChange({ change_type: "price_decrease", old_value: "45.00", new_value: "40.00" }), "价格下降 45.00 → 40.00"],
  [latestChange({ change_type: "sku_added", new_value: "红色" }), "新增 SKU：红色"],
  [latestChange({ change_type: "sku_removed", old_value: "蓝色" }), "移除 SKU：蓝色"],
  [latestChange({ change_type: "stock_changed", old_value: "10", new_value: "20" }), "库存变化 10 → 20"],
  [latestChange({ change_type: "stock_changed", old_value: "10", new_value: "0" }), "库存变化 10 → 0"],
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

test("renders the real latest change in the recent change column", () => {
  const changed = {
    ...competitor,
    latest_change: {
      id: 7,
      snapshot_id: 8,
      change_type: "price_increase",
      entity_key: null,
      old_value: "40.00",
      new_value: "45.00",
      detected_at: "2026-09-20T10:00:00Z",
    },
  };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[changed]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("价格上涨 40.00 → 45.00");
});

test("displays collecting state and disables every collect button", () => {
  const second = { ...competitor, id: 2, offer_id: "987654321" };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor, second]} collectingCompetitorId={1} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("采集中...");
  expect((html.match(/class="collect-button[^\"]*" disabled=""/g) ?? [])).toHaveLength(2);
});

test("maps collection errors without exposing technical response bodies", () => {
  expect(getCollectionErrorMessage("1688_login_required")).toBe("1688 登录状态已失效，请重新登录后再试");
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

test("renders destructive delete confirmation with history warning", () => {
  const html = renderToStaticMarkup(<DeleteDialog competitor={{ ...competitor, title: "暖手宝商品" }} status="initial" error={null} onConfirm={noop} onClose={noop} />);
  expect(html).toContain("删除竞品");
  expect(html).toContain("暖手宝商品");
  expect(html).toContain("历史快照、变化记录和采集记录");
  expect(html).toContain("确认删除");
});

test("renders competitor group controls and new group entry", () => {
  const html = renderToStaticMarkup(<AddDialog url="" status="initial" onUrlChange={noop} onSubmit={noop} onClose={noop} groups={[group]} groupId={1} onGroupChange={noop} newGroupName="" onNewGroupNameChange={noop} onCreateGroup={noop} groupCreateStatus="initial" />);
  expect(html).toContain('role="dialog"');
  expect(html).toContain('id="competitor-url"');
  expect(html).toContain("竞品组");
  expect(html).toContain("未分组");
  expect(html).toContain("暖手宝");
  expect(html).toContain("新建分组");
  expect(html).toContain("添加竞品");
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
  const html = renderToStaticMarkup(<ListPage {...listProps} groups={[group]} competitors={[{ ...competitor, group_id: null }, { ...competitor, id: 2, offer_id: "987654321", group_id: 1 }, { ...competitor, id: 3, offer_id: "111111111", group_id: 2 }]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("竞品组");
  expect(html).toContain("未分组");
  expect(html).toContain("暖手宝");
  expect(html).toContain("—");
});

const dashboardData: DashboardData = {
  date: "2026-09-20",
  stats: { monitored_competitors: 5, changed_competitors: 1, change_events: 2 },
  items: [{
    competitor_id: 1,
    title: "暖手宝",
    shop_name: "家居店",
    main_image_url: null,
    group_id: 1,
    last_collected_at: "2026-09-20T10:00:00Z",
    changes: [
      { id: 2, change_type: "price_increase", entity_key: null, old_value: "40.00", new_value: "45.00", detected_at: "2026-09-20T10:00:00Z" },
      { id: 1, change_type: "title_changed", entity_key: null, old_value: null, new_value: null, detected_at: "2026-09-20T09:00:00Z" },
    ],
  }],
};

test("renders dashboard loading, error and empty states", () => {
  expect(renderToStaticMarkup(<DashboardPage data={null} groups={[]} status="loading" error={null} onRetry={noop} onNavigate={noop} />)).toContain("正在加载今日变化");
  expect(renderToStaticMarkup(<DashboardPage data={null} groups={[]} status="error" error="请求失败" onRetry={noop} onNavigate={noop} />)).toContain("重试");
  expect(renderToStaticMarkup(<DashboardPage data={{ ...dashboardData, items: [], stats: { ...dashboardData.stats, changed_competitors: 0, change_events: 0 } }} groups={[]} status="ready" error={null} onRetry={noop} onNavigate={noop} />)).toContain("今天暂无竞品变化");
});

test("renders dashboard stats, mapped group and all changes", () => {
  const html = renderToStaticMarkup(<DashboardPage data={dashboardData} groups={[group]} status="ready" error={null} onRetry={noop} onNavigate={noop} />);
  expect(html).toContain("监控竞品");
  expect(html).toContain(">5<");
  expect(html).toContain("今日变化事件");
  expect(html).toContain("家居店");
  expect(html).toContain("暖手宝");
  expect(html).toContain("价格上涨 40.00 → 45.00");
  expect(html).toContain("标题已变更");
  expect(html).toContain("2 条变化");
  const unknownGroup = renderToStaticMarkup(<DashboardPage data={{ ...dashboardData, items: [{ ...dashboardData.items[0], group_id: 99 }] }} groups={[group]} status="ready" error={null} onRetry={noop} onNavigate={noop} />);
  expect(unknownGroup).toContain("竞品组：—");
});

test("renders detail entry actions on dashboard and competitor list", () => {
  const dashboard = renderToStaticMarkup(<DashboardPage data={dashboardData} groups={[]} status="ready" error={null} onRetry={noop} onNavigate={noop} onOpenDetail={noop} />);
  const list = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor]} status="ready" error={null} onRetry={noop} onAdd={noop} onOpenDetail={noop} />);
  expect(dashboard).toContain("查看详情");
  expect(list).toContain(">详情<");
});

test.each([
  [latestChange({ change_type: "price_increase", old_value: "1", new_value: "2" }), "价格上涨 1 → 2"],
  [latestChange({ change_type: "price_decrease", old_value: "2", new_value: "1" }), "价格下降 2 → 1"],
  [latestChange({ change_type: "sku_added", new_value: "红色" }), "新增 SKU：红色"],
  [latestChange({ change_type: "sku_removed", old_value: "蓝色" }), "移除 SKU：蓝色"],
  [latestChange({ change_type: "stock_changed", old_value: "1", new_value: "0" }), "库存变化 1 → 0"],
  [latestChange({ change_type: "title_changed" }), "标题已变更"],
  [latestChange({ change_type: "unknown" }), "发生变化"],
] as const)("formats dashboard changes through the shared formatter", (change, expected) => {
  expect(formatChange(change)).toBe(expected);
});

test("marks the active sidebar page", () => {
  const dashboard = renderToStaticMarkup(<Sidebar page="dashboard" onNavigate={noop} />);
  const competitors = renderToStaticMarkup(<Sidebar page="competitors" onNavigate={noop} />);
  expect(dashboard).toContain('class="nav-item nav-child nav-active" aria-current="page"');
  expect(dashboard).toContain("竞品监控大屏");
  expect(competitors).toContain('class="nav-item nav-child nav-active" aria-current="page"');
  expect(competitors).toContain("竞品列表");
});

const detailData: CompetitorDetail = {
  range_days: 7,
  competitor: {
    id: 1,
    platform: "1688",
    offer_id: "123456789",
    url: "https://detail.1688.com/offer/123456789.html",
    group_id: 1,
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
    product_status: "unknown",
    sku_count: 2,
  },
  latest_skus: [
    { sku_id: "sku-0", sku_name: "红色", stock: 0, price: null },
    { sku_id: "sku-null", sku_name: "蓝色", stock: null, price: "41.00" },
  ],
  price_trend: [
    { snapshot_id: 1, captured_at: "2026-09-18T10:00:00Z", price_min: "38.00", price_max: "42.00" },
    { snapshot_id: 2, captured_at: "2026-09-20T10:00:00Z", price_min: "40.00", price_max: "45.00" },
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
  const empty = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, latest_snapshot: null, latest_skus: [], price_trend: [], recent_changes: [], recent_collection_runs: [] }} status="ready" error={null} />);
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
  expect(html).toContain("已停止监控");
  expect(html).toContain("红色");
  expect(html).toContain(">0<");
  expect(html).toContain("蓝色");
  expect(html).toContain("¥41.00");
  expect(html).toContain("—");
});

test("renders price chart data, selector state, changes and collection statuses", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} days={30} data={{ ...detailData, range_days: 30 }} status="ready" error={null} />);
  expect(html).toContain('aria-pressed="true"');
  expect(html).toContain("近 30 天");
  expect(html).toContain("价格趋势");
  expect(html).toContain("价格上涨 38.00 → 40.00");
  expect(html).toContain("成功");
  expect(html).toContain("结束时间");
  expect(html).toContain("请求超时");
  expect(html).toContain("采集中");
  expect(html).toContain("<svg");
});

test("price chart points filter null snapshots and keep a single real point", () => {
  const points = buildPriceChartPoints([
    { snapshot_id: 1, captured_at: "2026-09-18T10:00:00Z", price_min: null, price_max: null },
    { snapshot_id: 2, captured_at: "2026-09-20T10:00:00Z", price_min: "40.00", price_max: null },
  ]);
  expect(points).toHaveLength(1);
  expect(points[0].snapshot_id).toBe(2);
  expect(points[0].min_y).not.toBeNull();
  expect(points[0].max_y).toBeNull();
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
