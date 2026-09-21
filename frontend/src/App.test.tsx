import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { addCompetitorsSequentially, AddDialog, applyInitialGroupFilter, BatchState, Competitor, CompetitorDetail, CompetitorFilters, CompetitorGroup, CompetitorGroupMetrics, CompetitorGroupSummary, ConfirmDialog, countActiveCompetitors, DashboardData, DashboardPage, DashboardTrendChart, defaultCompetitorFilters, DetailPage, filterCompetitors, formatChange, formatChangeMagnitude, formatChangeValue, formatDashboardMagnitude, formatDashboardSummary, formatDetailPriceDisplay, formatPriceChangeMagnitude, formatPriceChangeTransition, formatTrendTooltip, formatStockDisplay, formatDuration, formatGroupLatestChange, formatGroupPriceRange, formatLatestChange, getAddFailureReason, getChangeTypeLabel, getCollectionErrorMessage, getCollectionFailureMessage, getCollectionRequestErrorMessage, getCompetitorGroupLabel, getGroupAssignmentErrorMessage, getGroupFeedbackClass, getGroupNameErrorMessage, getLifecycleErrorMessage, getResponseStatus, GroupAssignmentDialog, GroupDeleteDialog, GroupNameDialog, GroupPage, idleBatchState, isCurrentDetailRequest, ListPage, mergeCompetitorUrlText, parseCompetitorUrls, reconcileSelectedIds, Sidebar, StatusBadge, updateCompetitorGroup, buildDashboardTrendChartPoints, buildPriceChartPoints, buildStockChartPoints } from "./App";

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
const listProps = { groups: [] as CompetitorGroup[] };
const group: CompetitorGroup = { id: 1, name: "暖手宝", created_at: "2026-09-20T10:00:00Z" };
const groupMetrics: CompetitorGroupMetrics = { competitor_count: 3, active_count: 2, price_min: "34.00", price_max: "40.00", changed_competitors_today: 2, last_change_at: "2026-09-21T10:35:00Z" };
const groupSummary: CompetitorGroupSummary = { ...group, ...groupMetrics };
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

test("select-all candidates come only from filtered active rows", () => {
  const filtered = filterCompetitors(filterCompetitorFixtures, filter({ search: "店" }));
  expect(filtered.filter((item) => item.is_active).map((item) => item.id)).toEqual([10]);
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
  expect(html).toContain("采集选中（0）");
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

test("converts request errors and unknown responses to server-error without stopping", async () => {
  const result = await addCompetitorsSequentially(["A", "B"], null, async (_input, init) => {
    const url = (JSON.parse(String(init?.body)) as { url: string }).url;
    if (url === "A") throw new Error("offline");
    return { ok: false, json: async () => ({}) } as Response;
  });
  expect(result.succeeded).toEqual([]);
  expect(result.failures.map(({ url, code }) => ({ url, code }))).toEqual([{ url: "A", code: "server-error" }, { url: "B", code: "server-error" }]);
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
  expect(normal).toContain("采集选中（0）");
  expect(normal).not.toContain("立即采集");
  expect(normal).toContain("全选当前页可采集竞品");
  expect(normal).toContain("监控中");
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

test("list keeps lifecycle actions out of the row", () => {
  const inactive = { ...competitor, is_active: false, title: "已停止商品" };
  const list = renderToStaticMarkup(<ListPage {...listProps} competitors={[inactive]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(list).toContain("已停止");
  expect(list).toContain(">详情</button>");
  expect(list).not.toContain("更多");
  expect(list).not.toContain("删除竞品");
  expect(list).toMatch(/aria-label="选择 已停止商品"[^>]*disabled=""/);
});

test("renders current-page selection counts and inactive checkbox semantics", () => {
  const second = { ...competitor, id: 2, offer_id: "987654321" };
  const inactive = { ...competitor, id: 3, is_active: false, title: "已停止商品" };
  const html = renderToStaticMarkup(<ListPage {...listProps} competitors={[competitor, second, inactive]} selectedIds={new Set([competitor.id])} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("采集选中（1）");
  expect(html).toMatch(/aria-label="选择 已停止商品"[^>]*disabled=""/);
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
  expect(html).toContain("添加竞品");
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
  expect(failed).toContain("未添加 1 个竞品");
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
  const html = renderToStaticMarkup(<ListPage {...listProps} groups={[group]} competitors={[{ ...competitor, group_id: null }, { ...competitor, id: 2, offer_id: "987654321", group_id: 1 }, { ...competitor, id: 3, offer_id: "111111111", group_id: 2 }]} status="ready" error={null} onRetry={noop} onAdd={noop} />);
  expect(html).toContain("竞品组");
  expect(html).toContain("未分组");
  expect(html).toContain("暖手宝");
  expect(html).toContain("—");
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
    primary_change: { id: 2, change_type: "price_increase", entity_key: null, sku_name: null, old_value: "40.00", new_value: "45.00", detected_at: "2026-09-20T10:00:00Z" },
    stock_changed_sku_count: 0,
    sku_added_count: 0,
    sku_removed_count: 0,
  }],
  collection_summary: { last_collection_at: "2026-09-20T10:00:00Z", success_runs: 3, failed_runs: 0, average_duration_seconds: 28 },
  trend_7d: ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19", "2026-09-20"].map((date, index) => ({ date, price_changes: index === 6 ? 2 : 0, stock_changes: index === 5 ? 1 : 0, sku_changes: 0, failed_collections: 0 })),
};

test("renders dashboard loading, error and empty states", () => {
  expect(renderToStaticMarkup(<DashboardPage data={null} groups={[]} status="loading" error={null} onRetry={noop} onNavigate={noop} />)).toContain("正在加载今日变化");
  expect(renderToStaticMarkup(<DashboardPage data={null} groups={[]} status="error" error="请求失败" onRetry={noop} onNavigate={noop} />)).toContain("重试");
  expect(renderToStaticMarkup(<DashboardPage data={{ ...dashboardData, items: [], stats: { ...dashboardData.stats, changed_competitors: 0, change_events: 0 } }} groups={[]} status="ready" error={null} onRetry={noop} onNavigate={noop} />)).toContain("今日暂无竞品变化");
});

test("renders dashboard stats, mapped group and aggregated change item", () => {
  const html = renderToStaticMarkup(<DashboardPage data={dashboardData} groups={[group]} status="ready" error={null} onRetry={noop} onNavigate={noop} />);
  expect(html).toContain("监控中 5 个竞品");
  expect(html).toContain("今日变价竞品");
  expect(html).toContain("今日库存变化竞品");
  expect(html).toContain("今日 SKU 变化竞品");
  expect(html).toContain("异常采集");
  expect(html).toContain("家居店");
  expect(html).toContain("暖手宝");
  expect(html).toContain("¥40.00");
  expect(html).toContain("¥45.00");
  expect(html).toContain("变价");
  expect(html).toContain("标题变化");
  expect(html).toContain("今日 1 个竞品 · 2 条变化");
  expect((html.match(/class="change-type-badge/g) || []).length).toBe(2);
  expect(html).not.toContain("最近变化列表");
  const unknownGroup = renderToStaticMarkup(<DashboardPage data={{ ...dashboardData, items: [{ ...dashboardData.items[0], group_id: 99 }] }} groups={[group]} status="ready" error={null} onRetry={noop} onNavigate={noop} />);
  expect(unknownGroup).toContain(">—</td>");
});

test("renders all competitor items without expanding event rows", () => {
  const items = Array.from({ length: 6 }, (_, index) => ({ ...dashboardData.items[0], competitor_id: index + 1 }));
  const html = renderToStaticMarkup(<DashboardPage data={{ ...dashboardData, items, stats: { ...dashboardData.stats, changed_competitors: 6, change_events: 12 } }} groups={[]} status="ready" error={null} onRetry={noop} onNavigate={noop} />);
  expect((html.match(/class="product-cell/g) || []).length).toBe(6);
  expect(html).toContain("今日 6 个竞品 · 12 条变化");
});

test("formats dashboard change rows, badges, magnitudes, and collection durations", () => {
  const price = { id: 1, change_type: "price_decrease", entity_key: null, old_value: "40", new_value: "38", detected_at: "2026-09-20T10:00:00Z" };
  const sku = { id: 2, change_type: "sku_added", entity_key: "sku-red", old_value: null, new_value: "红色", detected_at: "2026-09-20T10:00:00Z" };
  expect(formatChangeValue(price, "old")).toBe("¥40");
  expect(formatChangeValue(price, "new")).toBe("¥38");
  expect(formatChangeMagnitude(price)).toBe("↓ 5.0%");
  expect(formatChangeValue(sku, "old")).toBe("—");
  expect(formatChangeValue(sku, "new")).toBe("红色");
  expect(formatChangeMagnitude(sku)).toBe("—");
  expect(getChangeTypeLabel("stock_changed")).toBe("库存变化");
  const stock = { ...price, change_type: "stock_changed", entity_key: "sku-red", sku_name: "白色款", old_value: "481", new_value: "478" };
  const stockItem = { ...dashboardData.items[0], change_count: 2, change_types: ["stock_changed"], primary_change: stock, stock_changed_sku_count: 1 };
  expect(formatDashboardSummary(stockItem)).toBe("白色款 481 → 478");
  expect(formatDashboardMagnitude(stockItem)).toBe("↓ 0.6%");
  const multiStock = { ...stockItem, stock_changed_sku_count: 2 };
  expect(formatDashboardSummary(multiStock)).toBe("2 个 SKU 发生变化");
  expect(formatDashboardMagnitude(multiStock)).toBe("—");
  expect(formatDuration(72)).toBe("1 分 12 秒");
  expect(formatDuration(null)).toBe("—");
});

test("renders the seven trend labels and keeps zero-valued chart points valid", () => {
  const points = buildDashboardTrendChartPoints(dashboardData.trend_7d);
  expect(points).toHaveLength(7);
  expect(points.every((point) => Number.isFinite(point.y.price_changes))).toBe(true);
  const html = renderToStaticMarkup(<DashboardTrendChart trend={dashboardData.trend_7d} />);
  expect((html.match(/class="chart-label"/g) || []).length).toBeGreaterThanOrEqual(9);
  expect(html).toContain("09/14");
  expect(html).toContain("09/20");
});

test("renders batch state and quick action semantics", () => {
  const onAdd = () => undefined;
  const onCollect = () => undefined;
  const running = renderToStaticMarkup(<DashboardPage data={dashboardData} groups={[]} status="ready" error={null} batchState={{ ...idleBatchState, status: "running", total: 9, completed: 3, succeeded: 3, runner_active: true }} onRetry={noop} onNavigate={noop} onAdd={onAdd} onCollect={onCollect} />);
  expect(running).toContain("采集中 3 / 9");
  expect(running).toContain('style="width:33.33333333333333%"');
  const verification = renderToStaticMarkup(<DashboardPage data={dashboardData} groups={[]} status="ready" error={null} batchState={{ ...idleBatchState, status: "verification_required", total: 9, completed: 3 }} onRetry={noop} onNavigate={noop} />);
  expect(verification).toContain("需要人工验证");
  const empty = renderToStaticMarkup(<DashboardPage data={{ ...dashboardData, stats: { ...dashboardData.stats, monitored_competitors: 0 } }} groups={[]} status="ready" error={null} onRetry={noop} onNavigate={noop} />);
  expect(empty).toContain('disabled=""');
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
  const groups = renderToStaticMarkup(<Sidebar page="groups" onNavigate={noop} />);
  expect(dashboard).toContain('class="nav-item nav-child nav-active" aria-current="page"');
  expect(dashboard).toContain("竞品监控大屏");
  expect(competitors).toContain('class="nav-item nav-child nav-active" aria-current="page"');
  expect(competitors).toContain("竞品列表");
  expect(groups).toContain('竞品分组');
  expect(groups).toContain('class="nav-item nav-child nav-active" aria-current="page"');
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
  const loading = renderToStaticMarkup(<GroupPage summary={null} status="loading" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onNavigate={noop} />);
  const error = renderToStaticMarkup(<GroupPage summary={null} status="error" error="请求失败" onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onNavigate={noop} />);
  const empty = renderToStaticMarkup(<GroupPage summary={{ groups: [], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onNavigate={noop} />);
  const onlyUnassigned = renderToStaticMarkup(<GroupPage summary={{ groups: [], unassigned: { ...groupMetrics, competitor_count: 1, active_count: 1 } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onNavigate={noop} />);
  const normal = renderToStaticMarkup(<GroupPage summary={{ groups: [groupSummary], unassigned: { ...groupMetrics, competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } }} status="ready" error={null} onRetry={noop} onCreate={noop} onViewCompetitors={noop} onRename={noop} onDelete={noop} onNavigate={noop} />);
  expect(loading).toContain("正在加载竞品组");
  expect(error).toContain("重试");
  expect(empty).toContain("还没有竞品组");
  expect(onlyUnassigned).toContain("未分组");
  expect(onlyUnassigned).toContain("查看竞品");
  expect(normal).toContain("暖手宝");
  expect(normal).toContain("3 个竞品");
  expect(normal).toContain("¥34.00 ~ ¥40.00");
  expect(normal).toContain("更多");
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
    total_stock: null,
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
  expect(html).toContain("已停止监控");
  expect(html).toContain("红色");
  expect(html).toContain(">0<");
  expect(html).toContain("蓝色");
  expect(html).toContain("¥41.00");
  expect(html).toContain("—");
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
  expect(html).toContain("价格上涨 38.00 → 40.00");
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

test("price chart centers constant prices and uses the compact viewBox", () => {
  const points = buildPriceChartPoints([
    { date: "2026-09-18", snapshot_id: 1, captured_at: "2026-09-18T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null },
    { date: "2026-09-19", snapshot_id: 2, captured_at: "2026-09-19T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null },
    { date: "2026-09-20", snapshot_id: 3, captured_at: "2026-09-20T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null },
  ]);
  expect(points).toHaveLength(3);
  expect(points.every((point) => Number.isFinite(point.min_y) && Number.isFinite(point.max_y))).toBe(true);
  expect(points.every((point) => point.min_y === 78 && point.max_y === 78)).toBe(true);

  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={detailData} status="ready" error={null} />);
  expect(html).toContain('viewBox="0 0 640 170"');
  expect(html).not.toContain('viewBox="0 0 640 220"');
});

test("detail formatters keep stock, price-change, range and tooltip semantics", () => {
  expect(formatDetailPriceDisplay(detailData.latest_snapshot)).toBe("¥40.00 ~ ¥45.00");
  expect(formatStockDisplay(9998)).toBe("9,998");
  expect(formatPriceChangeTransition(latestChange({ old_value: "40.00", new_value: "38.00", change_type: "price_decrease" }))).toBe("¥40.00 → ¥38.00");
  expect(formatPriceChangeMagnitude(latestChange({ old_value: "40.00", new_value: "38.00", change_type: "price_decrease" }))).toBe("↓ 5.0%");
  expect(formatPriceChangeMagnitude(latestChange({ old_value: "40.00~50.00", new_value: "38.00~48.00", change_type: "price_decrease" }))).toBe("—");
  expect(formatPriceChangeMagnitude(null)).toBe("—");
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: "38.80", price_max: "38.80", total_stock: null }, "price")).toEqual(["09/20", "价格 ¥38.80"]);
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: null, price_max: null, total_stock: null }, "price")).toEqual([]);
  expect(formatTrendTooltip({ date: "2026-09-20", snapshot_id: 1, captured_at: "2026-09-20T10:00:00Z", price_min: null, price_max: null, total_stock: 9998 }, "stock")).toEqual(["09/20", "库存 9,998"]);
});

test("detail renders the overview, three trend cards, shared selector, placeholder and bottom facts", () => {
  const withImage = { ...detailData, competitor: { ...detailData.competitor, main_image_url: "https://img.example.com/item.jpg", group_id: 1 }, latest_snapshot: { ...detailData.latest_snapshot!, total_stock: 9998 } };
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={withImage} status="ready" error={null} />);
  expect(html).toContain("https://img.example.com/item.jpg");
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
  expect(html).toContain("最近变化");
  expect(html).toContain("最近采集记录");
  expect(html).not.toContain("saleQuantityList");
});

test("detail uses placeholders for missing image and stock", () => {
  const html = renderToStaticMarkup(<DetailPage {...detailProps} data={{ ...detailData, latest_snapshot: { ...detailData.latest_snapshot!, total_stock: null } }} status="ready" error={null} />);
  expect(html).toContain("暂无主图");
  expect(html).toContain("当前库存");
  expect(html).toContain(">—<");
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
