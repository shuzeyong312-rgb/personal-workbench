import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { AddDialog, Competitor, formatLatestChange, getCollectionErrorMessage, getCollectionFailureMessage, getCollectionRequestErrorMessage, getResponseStatus, ListPage } from "./App";

const competitor: Competitor = {
  id: 1,
  platform: "1688",
  offer_id: "123456789",
  url: "https://detail.1688.com/offer/123456789.html",
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
const listProps = { collectingCompetitorId: null, onCollect: noop };
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

test("renders add dialog without competitor group controls", () => {
  const html = renderToStaticMarkup(<AddDialog url="" status="initial" onUrlChange={noop} onSubmit={noop} onClose={noop} />);
  expect(html).toContain('role="dialog"');
  expect(html).toContain('id="competitor-url"');
  expect(html).not.toContain("竞品组");
  expect(html).toContain("添加竞品");
});
