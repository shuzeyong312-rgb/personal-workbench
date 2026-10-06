import { FormEvent, type ReactNode, type SyntheticEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import "./App.css";

type AddStatus = "initial" | "submitting" | "success" | "partial" | "failed" | "invalid" | "duplicate" | "server-error";
type GroupCreateStatus = "initial" | "submitting" | "success" | "invalid" | "duplicate" | "server-error";
type ListStatus = "loading" | "error" | "ready";
type DashboardStatus = "loading" | "error" | "ready";
type GroupStatus = "loading" | "error" | "ready";
export type BatchStatus = "idle" | "running" | "resting" | "cooling_down" | "completed" | "verification_required";
export type Page = "home" | "dashboard" | "own-products" | "competitors" | "detail" | "groups" | "group-detail" | "collection-tasks" | "price-compare" | "auto-inquiry" | "auto-listing" | "settings";
type Notice = { message: string; type: "success" | "error" };
export type LifecycleAction = "stop" | "resume" | "delete";
type BatchAction = "selected" | "all_active" | "group" | "stop" | "resume" | "delete";
const batchRefreshFailureMessage = "操作已完成，但部分数据刷新失败，请刷新页面后确认最新状态";

type CollectionErrorBody = { code?: string; message?: string };
type GroupRole = "competitor" | "own";
const noop = () => undefined;

const collectionErrorMessages: Record<string, string> = {
  competitor_not_found: "竞品不存在",
  competitor_inactive: "该竞品已停止监控，无法立即采集",
  collection_in_progress: "已有竞品正在采集，请稍后重试",
  "1688_login_required": "1688 登录状态已失效，请重新登录后再试",
  "1688_verification_required": "1688 当前需要完成安全验证",
  "1688_page_unavailable": "商品页面暂时无法访问，请稍后重试",
  collection_timeout: "商品页面加载超时，请稍后重试",
  collection_parse_failed: "无法解析该商品页面，请稍后重试",
  collection_partial_data: "商品数据不完整，暂时无法采集",
  offer_id_mismatch: "采集到的商品与当前竞品不匹配",
  collection_failed: "采集失败，请稍后重试",
  collection_save_failed: "商品数据保存失败，请稍后重试",
  invalid_batch_request: "批量采集请求无效",
};

const lifecycleErrorMessages: Record<string, string> = {
  competitor_not_found: "竞品不存在",
  competitor_inactive: "该竞品已停止监控，无法立即采集",
  collection_in_progress: "已有竞品正在采集，请稍后重试",
  competitor_delete_failed: "竞品删除失败，请稍后重试",
  own_product_not_batch_deletable: "我方商品不能参与批量删除",
};

const groupAssignmentErrorMessages: Record<string, string> = {
  competitor_not_found: "竞品不存在",
  competitor_group_not_found: "竞品组不存在",
  own_product_already_bound: "该竞品组已绑定我方商品，请刷新后重试。",
};

export type Competitor = {
  id: number;
  platform: string;
  offer_id: string;
  url: string;
  group_id: number | null;
  group_role: GroupRole;
  ownership: "self" | "competitor";
  title: string | null;
  shop_name: string | null;
  main_image_url: string | null;
  status: "unknown" | "active" | "offline";
  is_active: boolean;
  created_at: string;
  last_collected_at: string | null;
  latest_snapshot: {
    price_min: string | null;
    price_max: string | null;
    sku_count: number;
  } | null;
  latest_change: Change | null;
};

type LifecycleCompetitor = Pick<Competitor, "id" | "title" | "offer_id" | "is_active" | "group_role" | "ownership">;

export type CompetitorFilters = {
  search: string;
  status: "all" | Competitor["status"];
  collectionStatus: "all" | "collected" | "not_collected";
  groupId: "all" | "unassigned" | number;
};

export const defaultCompetitorFilters: CompetitorFilters = {
  search: "",
  status: "all",
  collectionStatus: "all",
  groupId: "all",
};

export function filterCompetitors(competitors: readonly Competitor[], filters: CompetitorFilters): Competitor[] {
  const query = filters.search.trim();
  const lowerQuery = query.toLocaleLowerCase();
  return competitors.filter((competitor) => {
    const searchMatches = !query || [competitor.title, competitor.offer_id, competitor.shop_name]
      .filter((value): value is string => value !== null)
      .some((value) => value.toLocaleLowerCase().includes(lowerQuery));
    const statusMatches = filters.status === "all" || competitor.status === filters.status;
    const collectionMatches = filters.collectionStatus === "all"
      || (filters.collectionStatus === "collected" ? competitor.last_collected_at !== null : competitor.last_collected_at === null);
    const groupMatches = filters.groupId === "all"
      || (filters.groupId === "unassigned" ? competitor.group_id === null : competitor.group_id === filters.groupId);
    return searchMatches && statusMatches && collectionMatches && groupMatches;
  });
}

export function countActiveCompetitors(competitors: readonly Competitor[]): number {
  return competitors.filter((competitor) => competitor.is_active).length;
}

export function getBatchRefreshNotice(successMessage: string, refreshSucceeded: boolean): Notice {
  return refreshSucceeded ? { message: successMessage, type: "success" } : { message: batchRefreshFailureMessage, type: "error" };
}

export function reconcileSelectedIds(selectedIds: ReadonlySet<number>, visibleIds: readonly number[]): Set<number> {
  const visible = new Set(visibleIds);
  return new Set([...selectedIds].filter((id) => visible.has(id)));
}

export const competitorPageSize = 10;

export function paginateCompetitors(competitors: readonly Competitor[], currentPage: number) {
  const totalPages = Math.max(1, Math.ceil(competitors.length / competitorPageSize));
  const page = Math.min(Math.max(1, currentPage), totalPages);
  return { page, totalPages, items: competitors.slice((page - 1) * competitorPageSize, page * competitorPageSize) };
}

export function updatePageSelection(selectedIds: ReadonlySet<number>, pageIds: readonly number[], checked: boolean): Set<number> {
  const next = new Set(selectedIds);
  for (const id of pageIds) checked ? next.add(id) : next.delete(id);
  return next;
}

export type BatchState = {
  status: BatchStatus;
  outcome_code: string | null;
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  remaining: number;
  verification_required: number;
  current_competitor_id: number | null;
  browser_open: boolean;
  runner_active: boolean;
  auto_resume_attempt: number;
  auto_resume_max: number;
  cooldown_remaining_seconds: number;
  resting_remaining_seconds: number;
  items: { competitor_id: number; status: "success" | "failed" | "verification_required"; error_code: string | null; message: string | null; outcome: "active" | "offline" | null }[];
};

export const idleBatchState: BatchState = {
  status: "idle",
  outcome_code: null,
  total: 0,
  completed: 0,
  succeeded: 0,
  failed: 0,
  remaining: 0,
  verification_required: 0,
  current_competitor_id: null,
  browser_open: false,
  runner_active: false,
  auto_resume_attempt: 0,
  auto_resume_max: 2,
  cooldown_remaining_seconds: 0,
  resting_remaining_seconds: 0,
  items: [],
};

export function formatBatchCooldown(seconds: number): string {
  return `${Math.max(0, seconds)} 秒`;
}

export type CompetitorGroup = {
  id: number;
  name: string;
  created_at: string;
};

export type CompetitorGroupMetrics = {
  competitor_count: number;
  active_count: number;
  price_min: string | null;
  price_max: string | null;
  changed_competitors_today: number;
  last_change_at: string | null;
};

export type OwnProductSummary = Pick<Competitor, "id" | "offer_id" | "title" | "shop_name" | "main_image_url" | "status" | "is_active">;

export type CompetitorGroupSummary = CompetitorGroup & CompetitorGroupMetrics & { own_product: OwnProductSummary | null };

export type CompetitorGroupsSummary = {
  groups: CompetitorGroupSummary[];
  unassigned: CompetitorGroupMetrics;
};

export type InitialGroupFilter = "unassigned" | number | null;

export type ListNavigationIntent = {
  filter: InitialGroupFilter;
  version: number;
};

export type Change = {
  id: number;
  snapshot_id?: number | null;
  collection_run_id?: number | null;
  change_type: string;
  entity_key: string | null;
  sku_name?: string | null;
  old_value: string | null;
  new_value: string | null;
  delta_value: string | null;
  delta_rate: string | null;
  detected_at: string;
};

export type DashboardItem = {
  competitor_id: number;
  title: string | null;
  shop_name: string | null;
  main_image_url: string | null;
  group_id: number | null;
  last_collected_at: string | null;
  change_count: number;
  change_types: string[];
  latest_change_at: string;
  primary_change: (Change & { sku_name: string | null }) | null;
  stock_changed_sku_count: number | null;
  stock_total_change: { old_total: number | null; new_total: number | null } | null;
  sku_added_count: number;
  sku_removed_count: number;
};

export type DashboardData = {
  date: string;
  stats: {
    monitored_competitors: number;
    active_monitored_products?: number;
    changed_competitors: number;
    change_events: number;
    price_changed_competitors: number;
    stock_changed_competitors: number;
    sku_changed_competitors: number;
    failed_collections: number;
  };
  items: DashboardItem[];
  collection_summary: {
    last_collection_at: string | null;
    success_runs: number;
    failed_runs: number;
    average_duration_seconds: number | null;
  };
  trend_7d: DashboardTrendPoint[];
};

export type GroupAttentionReason = {
  reason_type: string;
  display_text: string;
  competitor_count: number;
  sku_count: number | null;
  direction: string | null;
  event_level: "S" | "A" | "B" | "C" | "D";
  current_state_safe: boolean;
};

export type GroupAttentionItem = {
  group_id: number;
  group_name: string;
  own_product: Pick<Competitor, "id" | "offer_id" | "title" | "shop_name" | "main_image_url">;
  attention_level: "重点关注" | "建议查看" | "一般变化";
  changed_competitor_count: number;
  reasons: GroupAttentionReason[];
  latest_change_at: string;
};

export type GroupAttentionData = {
  date: string;
  kpis: {
    monitored_product_groups: number;
    changed_product_groups_today: number;
    changed_competitors_today: number;
  };
  groups: GroupAttentionItem[];
};

export type DashboardTrendPoint = {
  date: string;
  price_changes: number;
  stock_changes: number;
  sku_changes: number;
  failed_collections: number;
};

export type DailyTrendPoint = {
  date: string;
  snapshot_id: number | null;
  captured_at: string | null;
  price_min: string | null;
  price_max: string | null;
  total_stock: number | null;
};

export type CompetitorDetail = {
  range_days: number;
  competitor: Omit<Competitor, "latest_snapshot" | "latest_change"> & { ownership: "self" | "competitor" };
  latest_snapshot: {
    id: number;
    captured_at: string;
    price_min: string | null;
    price_max: string | null;
    image_urls: string[] | null;
    product_status: "unknown" | "active" | "offline";
    sku_count: number;
    total_stock: number | null;
    min_order_quantity: number | null;
  } | null;
  latest_skus: { sku_id: string; sku_name: string | null; stock: number | null; price: string | null }[];
  latest_price_change: Change | null;
  daily_trend: DailyTrendPoint[];
  recent_changes: Change[];
  recent_collection_runs: {
    id: number;
    started_at: string;
    finished_at: string | null;
    status: "running" | "success" | "failed";
    error_type: string | null;
    error_message: string | null;
  }[];
};

export type PriceChartPoint = {
  date: string;
  snapshot_id: number | null;
  captured_at: string | null;
  x: number;
  min_y: number | null;
  max_y: number | null;
  price_min: string | null;
  price_max: string | null;
};

export type StockChartPoint = {
  date: string;
  snapshot_id: number | null;
  captured_at: string | null;
  x: number;
  y: number | null;
  total_stock: number | null;
};

export type GroupProductFacts = Pick<Competitor, "id" | "platform" | "offer_id" | "url" | "title" | "shop_name" | "main_image_url" | "status" | "is_active" | "last_collected_at"> & {
  role: GroupRole;
  latest_snapshot: { id: number; captured_at: string; price_min: string | null; price_max: string | null; min_order_quantity: number | null; sku_count: number; total_stock: number | null } | null;
  latest_change: (Change & { snapshot_id: number | null; collection_run_id: number | null; sku_name: string | null }) | null;
};
export type GroupComparison = { price: "lower" | "higher" | "overlap" | "unknown"; min_order_quantity: "lower" | "higher" | "equal" | "unknown"; sku_count: "more" | "fewer" | "equal" | "unknown"; total_stock: "higher" | "lower" | "equal" | "unknown" };
export type GroupFactGapMetric = { matched_count: number; comparable_count: number };
export type GroupActionDomainCounts = { price: number; stock: number; sku: number; min_order_quantity: number; lifecycle: number; title: number; main_image: number };
export type GroupTodayEvent = NonNullable<GroupProductFacts["latest_change"]> & { competitor_id: number; role: GroupRole; title: string | null; offer_id: string };
export type GroupActionItem = { competitor_id: number; title: string | null; offer_id: string; event_count: number; latest_change_at: string; domain_counts: GroupActionDomainCounts };
export type GroupDetailData = {
  range_days: 7 | 30;
  group: CompetitorGroup;
  own_product: GroupProductFacts | null;
  summary: { direct_competitor_count: number; monitored_competitor_count: number; changed_competitors_today: number; price_lower_than_own: GroupFactGapMetric; moq_lower_than_own: GroupFactGapMetric; sku_more_than_own: GroupFactGapMetric; stock_higher_than_own: GroupFactGapMetric };
  competitors: (GroupProductFacts & { comparison: GroupComparison })[];
  today: { own_event_count: number; competitor_event_count: number; changed_competitor_count: number; events: GroupTodayEvent[] };
  action_window: { days: 7 | 30; own_event_count: number; competitor_event_count: number; competitors: GroupActionItem[] };
};

export type ChartScale = {
  domain: [number, number];
  ticks: number[];
  step: number;
};

export type TrendHitArea = { x: number; width: number; center: number };

const detailChartLeft = 54;
const detailChartRight = 16;

function chartY(value: number, minValue: number, maxValue: number, top: number, plotHeight: number): number {
  return maxValue === minValue ? top + plotHeight / 2 : top + ((maxValue - value) / (maxValue - minValue)) * plotHeight;
}

export function buildTrendHitAreas(points: readonly { x: number }[], plotLeft: number, plotRight: number): TrendHitArea[] {
  return points.map((point, index) => {
    const left = index === 0 ? plotLeft : (points[index - 1].x + point.x) / 2;
    const right = index === points.length - 1 ? plotRight : (point.x + points[index + 1].x) / 2;
    return { x: left, width: Math.max(0, right - left), center: point.x };
  });
}

function niceStep(range: number, intervals: number, integer: boolean): number {
  const raw = Math.max(range / intervals, integer ? 1 : Number.EPSILON);
  const power = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / power;
  const factor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
  const step = factor * power;
  return integer ? Math.max(1, Math.ceil(step)) : step;
}

function chartTicks(minValue: number, maxValue: number, step: number): number[] {
  const count = Math.max(1, Math.round((maxValue - minValue) / step));
  const decimals = step >= 1 ? 4 : Math.min(8, Math.max(2, Math.ceil(-Math.log10(step)) + 2));
  return Array.from({ length: count + 1 }, (_, index) => Number((minValue + index * step).toFixed(decimals)));
}

function buildNumericScale(values: readonly number[], { zeroBased = false, integer = false, minimumPadding = 1 }: { zeroBased?: boolean; integer?: boolean; minimumPadding?: number } = {}): ChartScale | null {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0 && !zeroBased) return null;
  const dataMin = finiteValues.length > 0 ? Math.min(...finiteValues) : 0;
  const dataMax = finiteValues.length > 0 ? Math.max(...finiteValues) : 0;
  let minValue = zeroBased ? 0 : dataMin;
  let maxValue = zeroBased ? Math.max(0, dataMax) : dataMax;
  if (zeroBased && maxValue < 4) maxValue = 4;
  else if (!zeroBased) {
    const padding = dataMin === dataMax ? Math.max(minimumPadding, Math.abs(dataMin) * .04) : Math.max((dataMax - dataMin) * .12, minimumPadding);
    minValue -= padding;
    maxValue += padding;
  }
  const step = niceStep(maxValue - minValue, 4, integer);
  const domainMin = zeroBased ? 0 : Math.floor(minValue / step) * step;
  const domainMax = Math.max(domainMin + step, Math.ceil(maxValue / step) * step);
  return { domain: [domainMin, domainMax], ticks: chartTicks(domainMin, domainMax, step), step };
}

export function buildDashboardTrendScale(trend: readonly DashboardTrendPoint[]): ChartScale {
  const values = trend.flatMap((point) => [point.price_changes, point.stock_changes, point.sku_changes, point.failed_collections]);
  return buildNumericScale(values, { zeroBased: true, integer: true })!;
}

export function buildPriceChartScale(trend: readonly DailyTrendPoint[]): ChartScale | null {
  const values = trend.flatMap((item) => [item.price_min, item.price_max]).flatMap((value) => {
    const number = value === null ? NaN : Number(value);
    return Number.isFinite(number) ? [number] : [];
  });
  return buildNumericScale(values, { minimumPadding: .5 });
}

export function buildStockChartScale(trend: readonly DailyTrendPoint[]): ChartScale | null {
  return buildNumericScale(trend.map((item) => item.total_stock).filter((value): value is number => value !== null && Number.isFinite(value)), { integer: true, minimumPadding: 1 });
}

export function buildPriceChartPoints(trend: readonly DailyTrendPoint[], width = 640, height = 170): PriceChartPoint[] {
  const scale = buildPriceChartScale(trend);
  if (trend.length === 0 || scale === null) return [];
  const [minValue, maxValue] = scale.domain;
  const left = detailChartLeft;
  const right = detailChartRight;
  const top = 16;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const y = (value: string | null) => value === null ? null : chartY(Number(value), minValue, maxValue, top, plotHeight);
  return trend.map((item, index) => ({
    date: item.date,
    snapshot_id: item.snapshot_id,
    captured_at: item.captured_at,
    x: trend.length === 1 ? left + plotWidth / 2 : left + (index / (trend.length - 1)) * plotWidth,
    min_y: y(item.price_min),
    max_y: y(item.price_max),
    price_min: item.price_min,
    price_max: item.price_max,
  }));
}

export function buildStockChartPoints(trend: readonly DailyTrendPoint[], width = 640, height = 170): StockChartPoint[] {
  const scale = buildStockChartScale(trend);
  if (trend.length === 0 || scale === null) return [];
  const [minValue, maxValue] = scale.domain;
  const left = detailChartLeft;
  const right = detailChartRight;
  const top = 16;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  return trend.map((item, index) => ({
    date: item.date,
    snapshot_id: item.snapshot_id,
    captured_at: item.captured_at,
    x: trend.length === 1 ? left + plotWidth / 2 : left + (index / (trend.length - 1)) * plotWidth,
    y: item.total_stock === null ? null : chartY(item.total_stock, minValue, maxValue, top, plotHeight),
    total_stock: item.total_stock,
  }));
}

export function isCurrentDetailRequest(requestId: number, latestRequestId: number): boolean {
  return requestId === latestRequestId;
}

export function getResponseStatus(responseOk: boolean, code?: string): AddStatus {
  if (responseOk) return "success";
  if (code === "invalid_competitor_url") return "invalid";
  if (code === "competitor_already_exists") return "duplicate";
  return "server-error";
}

export function parseCompetitorUrls(value: string): string[] {
  return [...new Set(value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
}

export function mergeCompetitorUrlText(currentValue: string, clipboardValue: string): string {
  return [...new Set([...parseCompetitorUrls(currentValue), ...parseCompetitorUrls(clipboardValue)])].join("\n");
}

export type AddFailureCode = "invalid_competitor_url" | "competitor_already_exists" | "competitor_group_not_found" | "own_shop_name_not_configured" | "shop_name_unavailable" | "own_product_already_bound" | "collection_in_progress" | "1688_login_required" | "1688_verification_required" | "collection_timeout" | "collection_parse_failed" | "collection_partial_data" | "offer_id_mismatch" | "collection_save_failed" | "collection_failed" | "validation-error" | "http-error" | "network-error" | "timeout" | "server-error";
export type AddFailure = { url: string; code: AddFailureCode; reason: string };
export type AddSubmissionResult = { succeeded: string[]; failures: AddFailure[] };

export function getAddFailureReason(code?: string): string {
  if (code === "invalid_competitor_url") return "链接格式无效";
  if (code === "competitor_already_exists") return "已存在";
  if (code === "competitor_group_not_found") return "竞品组不存在";
  if (code === "own_shop_name_not_configured") return "请先在系统设置中配置我方店铺名称";
  if (code === "shop_name_unavailable") return "无法确认店铺名称，未添加监控商品，请重试";
  if (code === "own_product_already_bound") return "该竞品组已绑定我方商品";
  if (code === "collection_in_progress") return "已有商品正在采集，请稍后重试";
  if (code === "1688_login_required") return "1688 登录状态已失效，请重新登录后再试";
  if (code === "1688_verification_required") return "1688 当前需要完成安全验证";
  if (code === "collection_timeout" || code === "timeout") return "商品页面加载超时，请稍后重试";
  if (code === "collection_parse_failed") return "无法解析该商品页面，请稍后重试";
  if (code === "collection_partial_data") return "商品数据不完整，暂时无法采集";
  if (code === "offer_id_mismatch") return "采集到的商品与当前链接不匹配";
  if (code === "collection_save_failed") return "商品数据保存失败，请稍后重试";
  if (code === "validation-error") return "请求参数无效，请检查后重试";
  if (code === "http-error") return "服务器请求失败，请稍后重试";
  if (code === "network-error") return "无法连接服务，请检查后端是否正常运行后重试";
  return "服务暂时不可用，请稍后重试";
}

type CompetitorRequest = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export async function addCompetitorsSequentially(urls: readonly string[], groupId: number | null, request: CompetitorRequest = fetch, onProgress?: (completed: number, total: number) => void, onSuccess?: (url: string, body: { ownership?: "self" | "competitor"; title?: string | null }) => void): Promise<AddSubmissionResult> {
  const succeeded: string[] = [];
  const failures: AddFailure[] = [];
  for (const url of urls) {
    try {
      const response = await request("/api/competitors", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, group_id: groupId }) });
      if (response.ok) {
        succeeded.push(url);
        try { onSuccess?.(url, await response.json() as { ownership?: "self" | "competitor"; title?: string | null }); } catch { onSuccess?.(url, {}); }
      }
      else {
        let code: string | undefined;
        try { code = (await response.json() as { code?: string }).code; } catch { /* use the stable fallback below */ }
        const knownCode = code && ["invalid_competitor_url", "competitor_already_exists", "competitor_group_not_found", "own_shop_name_not_configured", "shop_name_unavailable", "own_product_already_bound", "collection_in_progress", "1688_login_required", "1688_verification_required", "collection_timeout", "collection_parse_failed", "collection_partial_data", "offer_id_mismatch", "collection_save_failed", "collection_failed"] .includes(code) ? code as AddFailureCode : undefined;
        const failureCode: AddFailureCode = knownCode || (response.status >= 400 && response.status < 500 ? response.status === 400 || response.status === 422 ? "validation-error" : "http-error" : "server-error");
        failures.push({ url, code: failureCode, reason: getAddFailureReason(failureCode) });
      }
    } catch (error) {
      const failureCode: AddFailureCode = error instanceof DOMException && error.name === "AbortError" ? "timeout" : "network-error";
      failures.push({ url, code: failureCode, reason: getAddFailureReason(failureCode) });
    }
    onProgress?.(succeeded.length + failures.length, urls.length);
  }
  return { succeeded, failures };
}

export function getGroupCreateStatus(responseOk: boolean, code?: string): GroupCreateStatus {
  if (responseOk) return "success";
  if (code === "invalid_competitor_group_name") return "invalid";
  if (code === "competitor_group_already_exists") return "duplicate";
  return "server-error";
}

export function getGroupFeedbackClass(status: GroupCreateStatus): string {
  if (status === "invalid" || status === "duplicate" || status === "server-error") {
    return "feedback feedback-" + status;
  }
  return "feedback";
}

export function getCompetitorGroupLabel(groupId: number | null, groups: readonly CompetitorGroup[]): string {
  if (groupId === null) return "未分组";
  return groups.find((group) => group.id === groupId)?.name || "—";
}

export function applyInitialGroupFilter(
  filters: CompetitorFilters,
  initialGroupFilter: InitialGroupFilter,
): CompetitorFilters {
  return { ...filters, groupId: initialGroupFilter ?? "all" };
}

export function formatGroupPriceRange(metrics: Pick<CompetitorGroupMetrics, "price_min" | "price_max">): string {
  const min = metrics.price_min?.trim() || "";
  const max = metrics.price_max?.trim() || "";
  if (!min && !max) return "暂无价格";
  if (min && max && min === max) return `¥${min}`;
  if (min && max) return `¥${min} ~ ¥${max}`;
  return `¥${min || max}`;
}

export function formatGroupLatestChange(value: string | null): string {
  return value ? formatDate(value) : "暂无变化";
}

export function getGroupNameErrorMessage(code?: string, message?: unknown): string {
  if (code === "invalid_competitor_group_name") return "请输入有效的竞品组名称";
  if (code === "competitor_group_already_exists") return "该竞品组已存在";
  if (code === "competitor_group_not_found") return "竞品组不存在";
  const backendMessage = typeof message === "string" ? message.trim() : "";
  if (backendMessage && !/[<>]/.test(backendMessage) && !/traceback|stack trace|File "/i.test(backendMessage)) return backendMessage;
  return "竞品组操作失败，请稍后重试";
}

export function formatPriceDisplay(snapshot: Competitor["latest_snapshot"]): string {
  const min = snapshot?.price_min?.trim() || "";
  const max = snapshot?.price_max?.trim() || "";
  if (!min && !max) return "未采集";
  if (min && max && min === max) return `¥${min}`;
  if (min && max) return `¥${min} ~ ¥${max}`;
  return `¥${min || max}`;
}

export function formatDetailPriceDisplay(snapshot: CompetitorDetail["latest_snapshot"]): string {
  const min = snapshot?.price_min?.trim() || "";
  const max = snapshot?.price_max?.trim() || "";
  if (!min && !max) return "—";
  if (min && max && min === max) return `¥${min}`;
  if (min && max) return `¥${min} ~ ¥${max}`;
  return `¥${min || max}`;
}

function parseSinglePrice(value: string | null): number | null {
  const raw = value?.trim() || "";
  if (!raw || /[-~至到]/.test(raw)) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function formatPriceEventValue(value: string | null): string {
  const raw = value?.trim() || "";
  if (!raw) return "—";
  const range = raw.split("~").map((part) => part.trim()).filter(Boolean);
  if (range.length === 2) return `¥${range[0]} ~ ¥${range[1]}`;
  return `¥${raw}`;
}

export function formatPriceChangeTransition(change: Change | null): string {
  if (change === null) return "暂无价格变化";
  return `${formatPriceEventValue(change.old_value)} → ${formatPriceEventValue(change.new_value)}`;
}

export function formatPriceChangeMagnitude(change: Change | null): string {
  if (change === null || !["price_increase", "price_decrease"].includes(change.change_type)) return "—";
  const deltaRate = parseNumericString(change.delta_rate);
  if (deltaRate !== null) return formatPercentageMagnitude(deltaRate);
  const oldValue = parseSinglePrice(change.old_value);
  const newValue = parseSinglePrice(change.new_value);
  if (oldValue === null || newValue === null || oldValue === 0) return "—";
  const percentage = ((newValue - oldValue) / oldValue) * 100;
  if (percentage === 0) return "—";
  return `${percentage < 0 ? "↓" : "↑"} ${Math.abs(percentage).toFixed(1)}%`;
}

export function formatChange(change: Change): string {
  const oldValue = change.old_value ?? "";
  const newValue = change.new_value ?? "";
  const displayValue = (value: string | null) => value?.trim() || change.entity_key?.trim() || "";
  switch (change.change_type) {
    case "product_offline": return "商品已下架";
    case "product_online": return "商品恢复上架";
    case "price_increase": {
      const prefix = change.entity_key ? "SKU 涨价" : "商品涨价";
      const sku = change.entity_key ? `${change.sku_name?.trim() || `SKU ${change.entity_key}`} · ` : "";
      return `${sku}${prefix} ${oldValue} → ${newValue}`;
    }
    case "price_decrease": {
      const prefix = change.entity_key ? "SKU 降价" : "商品降价";
      const sku = change.entity_key ? `${change.sku_name?.trim() || `SKU ${change.entity_key}`} · ` : "";
      return `${sku}${prefix} ${oldValue} → ${newValue}`;
    }
    case "sku_added": { const value = displayValue(change.new_value); return value ? `新增 SKU：${value}` : "新增 SKU"; }
    case "sku_removed": { const value = displayValue(change.old_value); return value ? `移除 SKU：${value}` : "移除 SKU"; }
    case "stock_changed": {
      const sku = change.sku_name?.trim() || (change.entity_key ? `SKU ${change.entity_key}` : "");
      return sku ? `${sku} · 库存 ${oldValue} → ${newValue}` : `库存变化 ${oldValue} → ${newValue}`;
    }
    case "stock_increase": {
      const sku = change.sku_name?.trim() || (change.entity_key ? `SKU ${change.entity_key}` : "SKU");
      return `${sku} · SKU 库存增加 ${oldValue} → ${newValue}`;
    }
    case "stock_decrease": {
      const sku = change.sku_name?.trim() || (change.entity_key ? `SKU ${change.entity_key}` : "SKU");
      return `${sku} · SKU 库存下降 ${oldValue} → ${newValue}`;
    }
    case "sku_sold_out": {
      const sku = change.sku_name?.trim() || (change.entity_key ? `SKU ${change.entity_key}` : "SKU");
      return `${sku} · SKU 售罄`;
    }
    case "sku_restocked": {
      const sku = change.sku_name?.trim() || (change.entity_key ? `SKU ${change.entity_key}` : "SKU");
      return `${sku} · SKU 恢复有货`;
    }
    case "min_order_quantity_increase": return `起批量增加 ${oldValue} → ${newValue}`;
    case "min_order_quantity_decrease": return `起批量降低 ${oldValue} → ${newValue}`;
    case "main_image_changed": return "主图发生变化";
    case "title_changed": return "标题已变更";
    default: return "发生变化";
  }
}

function formatPercentageMagnitude(percentage: number): string {
  const direction = percentage < 0 ? "↓" : "↑";
  const magnitude = Math.abs(percentage).toFixed(1);
  return percentage !== 0 && magnitude === "0.0" ? `${direction} <0.1%` : `${direction} ${magnitude}%`;
}

function parseNumericString(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatChangeMagnitude(change: Change): string {
  const numericTypes = [
    "price_increase", "price_decrease", "stock_increase", "stock_decrease", "sku_sold_out",
    "sku_restocked", "stock_changed", "min_order_quantity_increase", "min_order_quantity_decrease",
  ];
  if (!numericTypes.includes(change.change_type)) return "—";
  const deltaRate = parseNumericString(change.delta_rate);
  if (deltaRate !== null) return formatPercentageMagnitude(deltaRate);
  const oldValue = parseNumericString(change.old_value);
  const newValue = parseNumericString(change.new_value);
  if (oldValue === null || newValue === null || oldValue === 0) return "—";
  const percentage = ((newValue - oldValue) / oldValue) * 100;
  return formatPercentageMagnitude(percentage);
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const rounded = Math.round(seconds);
  if (rounded < 60) return `${rounded} 秒`;
  return `${Math.floor(rounded / 60)} 分 ${rounded % 60} 秒`;
}

export type DashboardTrendChartPoint = DashboardTrendPoint & { x: number; y: Record<"price_changes" | "stock_changes" | "sku_changes" | "failed_collections", number> };

export function buildDashboardTrendChartPoints(trend: readonly DashboardTrendPoint[], width = 640, height = 180): DashboardTrendChartPoint[] {
  const points = trend.slice(-7);
  const scale = buildDashboardTrendScale(points);
  const [minValue, maxValue] = scale.domain;
  const left = 52;
  const right = 14;
  const top = 14;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const y = (value: number) => chartY(value, minValue, maxValue, top, plotHeight);
  return points.map((point, index) => ({
    ...point,
    x: points.length === 1 ? left + plotWidth / 2 : left + (index / (points.length - 1)) * plotWidth,
    y: {
      price_changes: y(point.price_changes),
      stock_changes: y(point.stock_changes),
      sku_changes: y(point.sku_changes),
      failed_collections: y(point.failed_collections),
    },
  }));
}

export function formatDashboardTrendTooltip(point: DashboardTrendPoint): string[] {
  return [formatChartDate(point.date), `变价 ${Math.round(point.price_changes)}`, `库存变化 ${Math.round(point.stock_changes)}`, `SKU变化 ${Math.round(point.sku_changes)}`, `异常采集 ${Math.round(point.failed_collections)}`];
}

export function formatLatestChange(change: Competitor["latest_change"]): string {
  return change === null ? "暂无变化记录" : formatChange(change);
}

export function getCollectionErrorMessage(code?: string, message?: unknown): string {
  const backendMessage = typeof message === "string" ? message.trim() : "";
  if (backendMessage && !/[<>]/.test(backendMessage) && !/traceback|stack trace|File "/i.test(backendMessage)) return backendMessage;
  return (code && collectionErrorMessages[code]) || "采集失败，请稍后重试";
}

export function getCollectionRequestErrorMessage(_error: unknown): string {
  return "无法连接服务，请检查后端是否正常运行后重试";
}

type CollectionFailure =
  | { kind: "http"; code?: string; message?: unknown }
  | { kind: "request"; error: unknown };

export function getCollectionFailureMessage(failure: CollectionFailure): string {
  if (failure.kind === "http") return getCollectionErrorMessage(failure.code, failure.message);
  return getCollectionRequestErrorMessage(failure.error);
}

export function getLifecycleErrorMessage(code?: string, message?: unknown): string {
  const backendMessage = typeof message === "string" ? message.trim() : "";
  if (backendMessage && !/[<>]/.test(backendMessage) && !/traceback|stack trace|File "/i.test(backendMessage)) return backendMessage;
  return (code && lifecycleErrorMessages[code]) || "操作失败，请稍后重试";
}

export function getGroupAssignmentErrorMessage(code?: string, message?: unknown): string {
  const backendMessage = typeof message === "string" ? message.trim() : "";
  if (backendMessage && !/[<>]/.test(backendMessage) && !/traceback|stack trace|File "/i.test(backendMessage)) return backendMessage;
  return (code && groupAssignmentErrorMessages[code]) || "竞品组更新失败，请稍后重试";
}

export type GroupAssignmentResult = { ok: true } | { ok: false; message: string };

export async function updateCompetitorGroup(competitorId: number, groupId: number | null, request: CompetitorRequest = fetch): Promise<GroupAssignmentResult> {
  try {
    const response = await request(`/api/competitors/${competitorId}/group`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ group_id: groupId }) });
    if (response.ok) return { ok: true };
    let body: CollectionErrorBody = {};
    try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
    return { ok: false, message: getGroupAssignmentErrorMessage(body.code, body.message) };
  } catch {
    return { ok: false, message: "竞品组更新失败，请稍后重试" };
  }
}

function parseBackendDate(value: string): Date {
  const normalized = value.trim();
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  return new Date(hasOffset ? normalized : `${normalized}Z`);
}

export async function updateGroupOwnProduct(groupId: number, competitorId: number, replaceExisting: boolean, request: CompetitorRequest = fetch): Promise<GroupAssignmentResult> {
  try {
    const response = await request(`/api/competitor-groups/${groupId}/own-product`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competitor_id: competitorId, replace_existing: replaceExisting }) });
    if (response.ok) return { ok: true };
    let body: CollectionErrorBody = {};
    try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
    return { ok: false, message: getOwnProductErrorMessage(body.code, body.message) };
  } catch { return { ok: false, message: "我方商品绑定失败，请稍后重试" }; }
}

export async function removeGroupOwnProduct(groupId: number, request: CompetitorRequest = fetch): Promise<GroupAssignmentResult> {
  try {
    const response = await request(`/api/competitor-groups/${groupId}/own-product`, { method: "DELETE" });
    if (response.ok) return { ok: true };
    let body: CollectionErrorBody = {};
    try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
    return { ok: false, message: getOwnProductErrorMessage(body.code, body.message) };
  } catch { return { ok: false, message: "我方商品解除失败，请稍后重试" }; }
}

export function getOwnProductErrorMessage(code?: string, message?: unknown): string {
  const backendMessage = typeof message === "string" ? message.trim() : "";
  if (backendMessage && !/[<>]/.test(backendMessage) && !/traceback|stack trace|File "/i.test(backendMessage)) return backendMessage;
  if (code === "own_product_already_bound") return "该竞品组已绑定我方商品，请刷新后重试。";
  if (code === "competitor_not_in_group") return "所选商品已不属于该竞品组，请刷新后重试。";
  if (code === "competitor_not_found") return "所选商品不存在，请刷新后重试。";
  if (code === "competitor_group_not_found") return "竞品组不存在，请刷新后重试。";
  return "我方商品操作失败，请稍后重试。";
}

export function formatDate(value: string | null): string {
  if (!value) return "未采集";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai",
  }).format(parseBackendDate(value));
}

function ProductImage({ competitor }: { competitor: Pick<Competitor, "main_image_url"> }) {
  const [failed, setFailed] = useState(false);
  if (!competitor.main_image_url || failed) return <span className="product-image product-image-placeholder">暂无主图</span>;
  return <img className="product-image" src={competitor.main_image_url} alt="" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

export function getDetailGallery(imageUrls: string[] | null, mainImageUrl: string | null): string[] {
  if (imageUrls !== null) return imageUrls.filter((url): url is string => typeof url === "string" && url.trim().length > 0);
  return mainImageUrl ? [mainImageUrl] : [];
}

export const DETAIL_GALLERY_SCROLL_STEP = 44;

export function getGalleryScrollState(scrollLeft: number, scrollWidth: number, clientWidth: number): { canScrollLeft: boolean; canScrollRight: boolean } {
  const maxScrollLeft = Math.max(0, scrollWidth - clientWidth);
  return { canScrollLeft: scrollLeft > 1, canScrollRight: scrollLeft < maxScrollLeft - 1 };
}

export function scrollDetailGallery(element: Pick<HTMLElement, "scrollBy">, direction: -1 | 1): void {
  element.scrollBy({ left: direction * DETAIL_GALLERY_SCROLL_STEP, behavior: "smooth" });
}

export function hideDetailGalleryThumbnail(
  event: { currentTarget: HTMLImageElement },
  updateScrollState: () => void,
  scheduleFrame: (callback: () => void) => number = (callback) => requestAnimationFrame(callback),
): void {
  event.currentTarget.parentElement?.setAttribute("hidden", "true");
  scheduleFrame(updateScrollState);
}

function DetailGallery({ imageUrls }: { imageUrls: string[] }) {
  const [selectedImage, setSelectedImage] = useState<string | null>(imageUrls[0] ?? null);
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const thumbnailsRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(imageUrls.length > 4);

  const updateScrollState = useCallback(() => {
    const thumbnails = thumbnailsRef.current;
    if (!thumbnails) {
      setCanScrollLeft(false);
      setCanScrollRight(false);
      return;
    }
    const maxScrollLeft = Math.max(0, thumbnails.scrollWidth - thumbnails.clientWidth);
    if (thumbnails.scrollLeft > maxScrollLeft) thumbnails.scrollLeft = maxScrollLeft;
    const scrollState = getGalleryScrollState(thumbnails.scrollLeft, thumbnails.scrollWidth, thumbnails.clientWidth);
    setCanScrollLeft(scrollState.canScrollLeft);
    setCanScrollRight(scrollState.canScrollRight);
  }, []);

  useEffect(() => {
    setSelectedImage(imageUrls[0] ?? null);
    setFailedImage(null);
  }, [imageUrls]);

  useEffect(() => {
    const thumbnails = thumbnailsRef.current;
    if (!thumbnails) {
      setCanScrollLeft(false);
      setCanScrollRight(false);
      return;
    }
    thumbnails.scrollLeft = 0;
    updateScrollState();
    window.addEventListener("resize", updateScrollState);
    return () => window.removeEventListener("resize", updateScrollState);
  }, [imageUrls, updateScrollState]);

  const selectImage = (imageUrl: string) => {
    setSelectedImage(imageUrl);
    setFailedImage(null);
  };

  const scrollGallery = (direction: -1 | 1) => {
    if (thumbnailsRef.current) scrollDetailGallery(thumbnailsRef.current, direction);
  };

  return <div className="detail-overview-image">
    <div className="detail-gallery-main">
      {selectedImage && selectedImage !== failedImage
        ? <img className="product-image detail-gallery-main-image" src={selectedImage} alt="" referrerPolicy="no-referrer" onError={() => setFailedImage(selectedImage)} />
        : <span className="product-image product-image-placeholder detail-gallery-main-image">暂无主图</span>}
    </div>
    {imageUrls.length > 0 && <div className="detail-gallery-strip">
      <span className="detail-gallery-arrow-slot">{canScrollLeft && <button type="button" className="detail-gallery-arrow" aria-label="向左滚动商品图库" onClick={() => scrollGallery(-1)}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg></button>}</span>
      <div ref={thumbnailsRef} className="detail-gallery-viewport" onScroll={updateScrollState}>
        <div className="detail-gallery-thumbnails" role="list" aria-label="商品图库">
          {imageUrls.map((imageUrl, index) => <button
            key={imageUrl}
            type="button"
            className={selectedImage === imageUrl ? "detail-gallery-thumbnail-button detail-gallery-thumbnail-selected" : "detail-gallery-thumbnail-button"}
            aria-label={`查看第 ${index + 1} 张商品图`}
            aria-pressed={selectedImage === imageUrl}
            onClick={() => selectImage(imageUrl)}
          ><img className="detail-gallery-thumbnail" src={imageUrl} alt="" referrerPolicy="no-referrer" onError={(event: SyntheticEvent<HTMLImageElement>) => hideDetailGalleryThumbnail(event, updateScrollState)} /></button>)}
        </div>
      </div>
      <span className="detail-gallery-arrow-slot">{canScrollRight && <button type="button" className="detail-gallery-arrow" aria-label="向右滚动商品图库" onClick={() => scrollGallery(1)}><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg></button>}</span>
    </div>}
  </div>;
}

export function StatusBadge({ status }: { status: Competitor["status"] }) {
  const labels = { unknown: "状态未知", active: "在售", offline: "已下架" };
  return <span className={"status-badge status-" + status}>{labels[status]}</span>;
}

type ShellProps = { page: Page; onNavigate: (page: Page) => void; breadcrumb: string; children: ReactNode };
type NavIconName = "home" | "monitoring" | "compare" | "inquiry" | "listing" | "settings";

function NavIcon({ name }: { name: NavIconName }) {
  const paths: Record<NavIconName, ReactNode> = {
    home: <><path d="m4 10 8-6 8 6" /><path d="M6 9v11h12V9" /><path d="M10 20v-6h4v6" /></>,
    monitoring: <><path d="M4 17V9" /><path d="M10 17V5" /><path d="M16 17v-4" /><path d="m4 7 5-3 5 5 6-5" /></>,
    compare: <><path d="M5 7h12" /><path d="m14 4 3 3-3 3" /><path d="M19 17H7" /><path d="m10 14-3 3 3 3" /></>,
    inquiry: <><path d="M5 5h14v10H9l-4 4V5Z" /><path d="M8 9h8" /><path d="M8 12h5" /></>,
    listing: <><path d="M5 9v10h14V9" /><path d="M9 7l3-3 3 3" /><path d="M12 4v10" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 3v2" /><path d="M12 19v2" /><path d="m5.64 5.64 1.42 1.42" /><path d="m16.94 16.94 1.42 1.42" /><path d="M3 12h2" /><path d="M19 12h2" /><path d="m5.64 18.36 1.42-1.42" /><path d="m16.94 7.06 1.42-1.42" /></>,
  };
  return <span className="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{paths[name]}</svg></span>;
}

const monitoringPages = new Set<Page>(["dashboard", "own-products", "competitors", "detail", "groups", "group-detail", "collection-tasks"]);

export function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const [monitoringExpanded, setMonitoringExpanded] = useState(true);
  const monitoringActive = monitoringPages.has(page);
  return <aside className="sidebar">
    <div className="brand"><span className="brand-mark">PW</span><div><strong>个人工作台</strong><span>工作提效工具集</span></div></div>
    <nav aria-label="主导航">
      <button className={"nav-item" + (page === "home" ? " nav-active" : "")} onClick={() => onNavigate("home")} aria-current={page === "home" ? "page" : undefined}><NavIcon name="home" />首页</button>
      <div className={"nav-group" + (monitoringExpanded ? "" : " nav-group-collapsed")}>
        <button type="button" className={"nav-group-title" + (monitoringActive ? " nav-group-title-current" : "")} onClick={() => setMonitoringExpanded((expanded) => !expanded)} aria-expanded={monitoringExpanded} aria-controls="competitor-monitoring-nav"><NavIcon name="monitoring" />竞品监控<span className="nav-chevron" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m8 14 4-4 4 4" /></svg></span></button>
        <div className="nav-group-children" id="competitor-monitoring-nav" hidden={!monitoringExpanded}>
          <button className={"nav-item nav-child" + (page === "dashboard" ? " nav-active" : "")} onClick={() => onNavigate("dashboard")} aria-current={page === "dashboard" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品监控大屏</button>
          <button className={"nav-item nav-child" + (page === "own-products" ? " nav-active" : "")} onClick={() => onNavigate("own-products")} aria-current={page === "own-products" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />我方商品</button>
          <button className={"nav-item nav-child" + (page === "competitors" || page === "detail" ? " nav-active" : "")} onClick={() => onNavigate("competitors")} aria-current={page === "competitors" || page === "detail" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品列表</button>
          <button className={"nav-item nav-child" + (page === "groups" || page === "group-detail" ? " nav-active" : "")} onClick={() => onNavigate("groups")} aria-current={page === "groups" || page === "group-detail" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品分组</button>
          <button className={"nav-item nav-child" + (page === "collection-tasks" ? " nav-active" : "")} onClick={() => onNavigate("collection-tasks")} aria-current={page === "collection-tasks" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />采集任务</button>
        </div>
      </div>
      <button className={"nav-item" + (page === "price-compare" ? " nav-active" : "")} onClick={() => onNavigate("price-compare")} aria-current={page === "price-compare" ? "page" : undefined}><NavIcon name="compare" />全网比价</button>
      <button className={"nav-item" + (page === "auto-inquiry" ? " nav-active" : "")} onClick={() => onNavigate("auto-inquiry")} aria-current={page === "auto-inquiry" ? "page" : undefined}><NavIcon name="inquiry" />自动询价</button>
      <button className={"nav-item" + (page === "auto-listing" ? " nav-active" : "")} onClick={() => onNavigate("auto-listing")} aria-current={page === "auto-listing" ? "page" : undefined}><NavIcon name="listing" />自动上架</button>
      <button className={"nav-item" + (page === "settings" ? " nav-active" : "")} onClick={() => onNavigate("settings")} aria-current={page === "settings" ? "page" : undefined}><NavIcon name="settings" />系统设置</button>
    </nav>
    <div className="sidebar-note"><strong>让工作更高效</strong><span>v1.0.0</span></div>
  </aside>;
}

function AppShell({ page, onNavigate, breadcrumb, children }: ShellProps) {
  const monitoringPage = monitoringPages.has(page);
  return <div className="app-shell"><Sidebar page={page} onNavigate={onNavigate} /><main className={`main-content${page === "dashboard" ? " main-content-dashboard" : ""}`}>
    <div className="workspace-header"><div className="breadcrumb">个人工作台 <span>/</span>{monitoringPage && <>竞品监控 <span>/</span></>}<strong>{breadcrumb}</strong></div><div className="workspace-tools" aria-label="工作台工具区"><div className="workspace-search" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="5.5" /><path d="m16 16 4 4" /></svg><span>搜索商品名称、链接或关键词</span></div><span className="workspace-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></svg></span><span className="workspace-user" aria-hidden="true"><span className="workspace-avatar">W</span><span>工作台</span><svg viewBox="0 0 24 24"><path d="m8 10 4 4 4-4" /></svg></span></div></div>
    {children}
  </main></div>;
}

export function ConfirmDialog({ action, competitor, submitting, error, onClose, onConfirm }: { action: "stop" | "delete"; competitor: LifecycleCompetitor; submitting: boolean; error: string | null; onClose: () => void; onConfirm: () => void }) {
  const isDelete = action === "delete";
  const isSelf = competitor.ownership === "self";
  const productLabel = competitor.title?.trim() || competitor.offer_id;
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="lifecycle-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="lifecycle-dialog-title">{isDelete ? `永久删除${isSelf ? "我方商品" : "竞品"}` : "停止监控"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    {isDelete ? <p className="dialog-description">删除后，该商品的历史快照、SKU、变化记录和采集记录都会永久删除，无法恢复。<br />当前商品：{productLabel}</p> : <p className="dialog-description">停止后将不再自动采集该商品，但历史数据会保留，之后可以恢复监控。</p>}
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="button" className={isDelete ? "danger-button" : "primary-button"} onClick={onConfirm} disabled={submitting}>{isDelete ? "确认删除" : "停止监控"}</button></div>
  </section></div>;
}

export function BatchLifecycleDialog({ action, selectedCount, eligibleCount, ownCount, submitting, error, onClose, onConfirm }: { action: "stop" | "delete"; selectedCount: number; eligibleCount: number; ownCount: number; submitting: boolean; error: string | null; onClose: () => void; onConfirm: () => void }) {
  const isDelete = action === "delete";
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="batch-lifecycle-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="batch-lifecycle-dialog-title">{isDelete ? "永久删除竞品" : "停止监控"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    {isDelete ? <p className="dialog-description">已选择 {selectedCount} 个商品<br />本次将永久删除 {eligibleCount} 个直接竞品{ownCount > 0 && <><br />{ownCount} 个我方商品不会参与批量删除</>}<br /><br />删除后将同时删除商品快照、SKU 快照、采集记录和变化事件。<br />此操作不可恢复。</p> : <p className="dialog-description">停止监控 {eligibleCount} 个商品？<br />停止后这些商品将不再参与后续自动采集和手动采集，已有商品信息、快照、SKU、采集记录和变化历史都会保留。</p>}
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="button" className={isDelete ? "danger-button" : "primary-button"} onClick={onConfirm} disabled={submitting}>{isDelete ? `永久删除 ${eligibleCount} 个竞品` : "确认停止"}</button></div>
  </section></div>;
}

type OwnProductAction = "bind" | "replace" | "unbind";

function GroupMoreMenu({ ownProduct, onRename, onDelete, onOwnProduct }: { ownProduct: OwnProductSummary | null; onRename: () => void; onDelete: () => void; onOwnProduct: (action: OwnProductAction) => void }) {
  const [open, setOpen] = useState(false);
  return <div className="group-more-menu">
    <button type="button" className="detail-button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((current) => !current)}>更多</button>
    {open && <div className="group-more-popover" role="menu">
      <button type="button" role="menuitem" onClick={() => { setOpen(false); onRename(); }}>重命名竞品组</button>
      <button type="button" role="menuitem" className="more-menu-danger" onClick={() => { setOpen(false); onDelete(); }}>删除竞品组</button>
    </div>}
  </div>;
}

function GroupMetrics({ metrics }: { metrics: CompetitorGroupMetrics }) {
  return <div className="group-card-metrics">
    <div><span>竞品数量</span><strong>{metrics.competitor_count}</strong></div>
    <div><span>监控中</span><strong>{metrics.active_count}</strong></div>
    <div className="group-card-price"><span>竞品价格区间</span><strong>{formatGroupPriceRange(metrics)}</strong></div>
    <div><span>今日变化</span><strong>{metrics.changed_competitors_today} 个竞品</strong></div>
    <div><span>最近变化</span><strong>{formatGroupLatestChange(metrics.last_change_at)}</strong></div>
  </div>;
}

function CompetitorGroupCard({ group, onViewCompetitors, onViewAnalysis, onRename, onDelete, onOwnProduct }: { group: CompetitorGroupSummary; onViewCompetitors: () => void; onViewAnalysis: () => void; onRename: () => void; onDelete: () => void; onOwnProduct: (action: OwnProductAction) => void }) {
  return <article className="group-card">
    <div className="group-card-header"><div><h2>{group.name}</h2><span>{group.competitor_count} 个竞品</span></div><GroupMoreMenu ownProduct={group.own_product} onRename={onRename} onDelete={onDelete} onOwnProduct={onOwnProduct} /></div>
    <div className="group-own-product"><span>我方商品</span><strong>{group.own_product ? group.own_product.title || `Offer ${group.own_product.offer_id}` : "尚未绑定"}</strong></div>
    <GroupMetrics metrics={group} />
    <div className="group-card-actions"><button type="button" className="secondary-button" onClick={onViewCompetitors}>查看竞品</button><button type="button" className="primary-button" onClick={onViewAnalysis}>组分析</button></div>
  </article>;
}

function UnassignedGroupCard({ metrics, onViewCompetitors }: { metrics: CompetitorGroupMetrics; onViewCompetitors: () => void }) {
  return <article className="group-card group-card-unassigned">
    <div className="group-card-header"><div><h2>未分组</h2><span>尚未归入竞品组</span></div></div>
    <GroupMetrics metrics={metrics} />
    <div className="group-card-actions"><button type="button" className="secondary-button" onClick={onViewCompetitors}>查看竞品</button></div>
  </article>;
}

type GroupPageProps = {
  summary: CompetitorGroupsSummary | null;
  status: GroupStatus;
  error: string | null;
  onRetry: () => void;
  onCreate: () => void;
  onViewCompetitors: (filter: InitialGroupFilter) => void;
  onViewAnalysis?: (groupId: number) => void;
  onRename: (group: CompetitorGroupSummary) => void;
  onDelete: (group: CompetitorGroupSummary) => void;
  onOwnProduct: (group: CompetitorGroupSummary, action: OwnProductAction) => void;
  onNavigate: (page: Page) => void;
};

export function GroupPage({ summary, status, error, onRetry, onCreate, onViewCompetitors, onViewAnalysis = noop, onRename, onDelete, onOwnProduct, onNavigate }: GroupPageProps) {
  const hasUnassigned = summary?.unassigned.competitor_count ? summary.unassigned.competitor_count > 0 : false;
  const isEmpty = status === "ready" && summary !== null && summary.groups.length === 0 && !hasUnassigned;
  return <AppShell page="groups" onNavigate={onNavigate} breadcrumb="竞品分组">
    <header className="page-header"><div><h1>竞品分组</h1><p className="page-description">以我方商品型号命名竞品组，管理对应竞品。</p></div><button type="button" className="primary-button" onClick={onCreate}>新增竞品组</button></header>
    {status === "loading" && <section className="table-card group-state-card state-panel"><div className="spinner" /><strong>正在加载竞品组…</strong></section>}
    {status === "error" && <section className="table-card group-state-card state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品组。"}</span><button type="button" className="secondary-button" onClick={onRetry}>重试</button></section>}
    {isEmpty && <section className="table-card group-state-card state-panel"><div className="empty-icon">＋</div><strong>还没有竞品组</strong><span>新增竞品组后，可按我方商品型号归集对应竞品进行对比监控。</span><button type="button" className="primary-button" onClick={onCreate}>新增竞品组</button></section>}
    {status === "ready" && summary && !isEmpty && <div className="group-card-grid">
      {summary.groups.map((group) => <CompetitorGroupCard key={group.id} group={group} onViewCompetitors={() => onViewCompetitors(group.id)} onViewAnalysis={() => onViewAnalysis(group.id)} onRename={() => onRename(group)} onDelete={() => onDelete(group)} onOwnProduct={(action) => onOwnProduct(group, action)} />)}
      {hasUnassigned && <UnassignedGroupCard metrics={summary.unassigned} onViewCompetitors={() => onViewCompetitors("unassigned")} />}
    </div>}
  </AppShell>;
}

const comparisonLabels = {
  price: { lower: "低于我方", higher: "高于我方", overlap: "区间重叠", unknown: "未知" },
  min_order_quantity: { lower: "更低", higher: "更高", equal: "相同", unknown: "未知" },
  sku_count: { more: "更多", fewer: "更少", equal: "相同", unknown: "未知" },
  total_stock: { higher: "更高", lower: "更低", equal: "相同", unknown: "未知" },
} as const;

function groupSnapshotValue(product: GroupProductFacts, field: "price" | "moq" | "sku" | "stock"): string {
  const snapshot = product.latest_snapshot;
  if (!snapshot) return "未采集";
  if (field === "price") {
    if (!snapshot.price_min && !snapshot.price_max) return "未采集";
    if (snapshot.price_min && snapshot.price_max && snapshot.price_min === snapshot.price_max) return `¥${snapshot.price_min}`;
    return `¥${snapshot.price_min || snapshot.price_max}` + (snapshot.price_min && snapshot.price_max ? ` ~ ¥${snapshot.price_max}` : "");
  }
  if (field === "moq") return snapshot.min_order_quantity === null ? "未知" : String(snapshot.min_order_quantity);
  if (field === "sku") return String(snapshot.sku_count);
  return snapshot.total_stock === null ? "未知" : String(snapshot.total_stock);
}

export function formatGroupUpdateTime(value: string | null): string {
  if (!value) return "未采集";
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Shanghai" }).format(parseBackendDate(value));
}

export function formatGroupProductFreshness(product: Pick<GroupProductFacts, "status" | "last_collected_at" | "latest_snapshot">): string {
  if (product.status === "offline") return product.latest_snapshot ? `最后快照 ${formatDate(product.latest_snapshot.captured_at)}` : "未采集";
  return product.last_collected_at ? `${formatGroupUpdateTime(product.last_collected_at)} 更新` : "未采集";
}

export function formatGroupDetailLatestChange(change: GroupProductFacts["latest_change"]): string {
  return change ? formatChange(change) : "—";
}

export function getGroupDifferenceLabels(comparison: GroupComparison, hasBaseline: boolean): { primary: string[]; stock: string[]; hasUnknown: boolean } {
  if (!hasBaseline) return { primary: ["未建立基准"], stock: [], hasUnknown: false };
  const primary: string[] = [];
  const stock: string[] = [];
  if (comparison.price === "lower") primary.push("低价");
  if (comparison.price === "higher") primary.push("高价");
  if (comparison.min_order_quantity === "lower") primary.push("起批更低");
  if (comparison.min_order_quantity === "higher") primary.push("起批更高");
  if (comparison.sku_count === "more") primary.push("SKU 更多");
  if (comparison.sku_count === "fewer") primary.push("SKU 更少");
  if (comparison.total_stock === "higher") stock.push("库存更高");
  if (comparison.total_stock === "lower") stock.push("库存更低");
  const hasUnknown = Object.values(comparison).some((value) => value === "unknown");
  return { primary, stock, hasUnknown };
}

const actionDomainLabels: Record<keyof GroupActionDomainCounts, string> = {
  price: "价格", stock: "库存", sku: "SKU", min_order_quantity: "起批量", lifecycle: "生命周期", title: "标题", main_image: "主图",
};

export function getNonzeroGroupActionDomains(counts: GroupActionDomainCounts): string[] {
  return (Object.keys(actionDomainLabels) as (keyof GroupActionDomainCounts)[])
    .filter((domain) => counts[domain] > 0)
    .map((domain) => `${actionDomainLabels[domain]} ${counts[domain]}`);
}

export function GroupDetailPage({ data, status, error, days, rangeLoading, rangeError, onRetry, onRangeChange, onBack, onViewCompetitors, onOpenDetail, onNavigate }: {
  data: GroupDetailData | null; status: DetailStatus; error: string | null; days: 7 | 30; rangeLoading: boolean; rangeError: string | null;
  onRetry: () => void; onRangeChange: (days: 7 | 30) => void; onBack: () => void; onViewCompetitors: (groupId: number) => void; onOpenDetail: (competitorId: number) => void; onNavigate: (page: Page) => void;
}) {
  const [dynamicTab, setDynamicTab] = useState<"today" | 7 | 30>(7);
  useEffect(() => { setDynamicTab(days); }, [data?.group.id, days]);
  useEffect(() => { if (!rangeLoading && rangeError) setDynamicTab(days); }, [rangeLoading, rangeError, days]);
  if (status === "loading") return <AppShell page="group-detail" onNavigate={onNavigate} breadcrumb="竞品分组 / 组分析"><header className="page-header"><div><h1>组竞争分析</h1><p className="page-description">围绕我方商品查看当前竞争位置和近期客观变化</p></div></header><div className="state-panel"><div className="spinner" /><strong>正在加载组分析…</strong></div></AppShell>;
  if (!data) return <AppShell page="group-detail" onNavigate={onNavigate} breadcrumb="竞品分组 / 组分析"><header className="page-header"><div><h1>{error === "竞品组不存在" ? "竞品组不存在" : "组竞争分析"}</h1></div><div className="detail-page-actions"><button type="button" className="secondary-button" onClick={onBack}>返回竞品分组</button><button type="button" className="secondary-button" onClick={onRetry}>重试</button></div></header><div className="state-panel state-error"><strong>{error === "竞品组不存在" ? "竞品组不存在" : "加载失败"}</strong><span>{error || "暂时无法获取组分析。"}</span></div></AppShell>;

  const own = data.own_product;
  const metrics = [
    ["明确低价竞品", data.summary.price_lower_than_own],
    ["更低起批量", data.summary.moq_lower_than_own],
    ["SKU 更多", data.summary.sku_more_than_own],
  ] as const;
  const actionMode = dynamicTab === "today" ? "today" : "actions";
  const visibleActions = data.action_window.competitors.slice(0, 5);
  const latestEventTime = (value: string) => formatGroupUpdateTime(value);
  const selectDynamicTab = (tab: "today" | 7 | 30) => {
    setDynamicTab(tab);
    if (tab !== "today" && tab !== days) onRangeChange(tab);
  };
  const renderProductCell = (product: GroupProductFacts, isOwn: boolean) => <div className="group-product-cell">
    <strong title={product.title?.trim() || `Offer ${product.offer_id}`}>{product.title?.trim() || `Offer ${product.offer_id}`}</strong>
    <span>{[product.shop_name, !isOwn ? formatGroupProductFreshness(product) : null].filter(Boolean).join(" · ")}</span>
    {(product.status === "offline" || !product.is_active || isOwn) && <div className="group-product-status">{isOwn && <span className="group-own-label">我方</span>}{product.status === "offline" && <span>已下架</span>}{!product.is_active && <span>已停止</span>}</div>}
  </div>;
  return <AppShell page="group-detail" onNavigate={onNavigate} breadcrumb={`竞品分组 / ${data.group.name}`}>
    <header className="page-header group-detail-page-header"><div><h1>{data.group.name} 竞争分析</h1><p className="page-description">围绕我方商品查看当前竞争位置和近期客观变化</p></div><div className="detail-page-actions"><button type="button" className="secondary-button" onClick={() => onViewCompetitors(data.group.id)}>查看竞品</button><button type="button" className="secondary-button" onClick={onBack}>返回竞品分组</button></div></header>

    <section className="table-card group-baseline-panel" aria-label="我方基准与关键差距">
      {own ? <>
        <div className="group-own-compact">
          <ProductImage competitor={own} />
          <div className="group-own-compact-main">
            <h2 title={own.title?.trim() || `Offer ${own.offer_id}`}>{own.title?.trim() || `Offer ${own.offer_id}`}</h2>
            <div className="group-own-compact-meta"><span>{own.shop_name || "店铺未知"}</span><a href={own.url} target="_blank" rel="noreferrer">1688 商品</a></div>
            <div className="group-own-inline-facts"><strong>{groupSnapshotValue(own, "price")}</strong><span>起批 {groupSnapshotValue(own, "moq")}</span><span>{groupSnapshotValue(own, "sku")} SKU</span><span>库存 {groupSnapshotValue(own, "stock")}</span></div>
            <div className="group-own-compact-status"><StatusBadge status={own.status} /><span className={own.is_active ? "list-monitoring-badge" : "list-monitoring-badge list-monitoring-inactive"}>{own.is_active ? "监控中" : "已停止"}</span><time>{formatGroupProductFreshness(own)}</time></div>
          </div>
        </div>
        <div className="group-key-gaps" aria-label="关键差距">
          {metrics.map(([label, metric]) => <div className="group-key-gap" key={label}><span>{label}</span><strong>{metric.comparable_count ? `${metric.matched_count} / ${metric.comparable_count}` : "暂无可比数据"}</strong>{metric.comparable_count > 0 && <small>可比较竞品</small>}</div>)}
        </div>
      </> : <div className="group-unbound-notice"><strong>尚未绑定我方商品</strong><span>绑定后可查看价格、起批量、SKU 和库存的横向比较。</span><button type="button" className="secondary-button" onClick={onBack}>返回竞品分组</button></div>}
    </section>

    <section className="table-card group-detail-section group-compare-section">
      <div className="table-heading"><div><h2>我方 vs 竞品</h2><span>{data.summary.direct_competitor_count} 个直接竞品 · {data.summary.monitored_competitor_count} 个监控中</span></div></div>
      {data.competitors.length === 0 ? <div className="group-compact-empty"><strong>当前组还没有直接竞品</strong><button type="button" className="text-button" onClick={() => onViewCompetitors(data.group.id)}>查看竞品列表</button></div> : <div className="table-scroll"><table className="group-comparison-table"><thead><tr><th>商品</th><th>当前价格</th><th>起批量</th><th>SKU</th><th>库存</th><th>当前差异</th><th>最近变化</th><th>详情</th></tr></thead><tbody>
        {own && <tr className="group-own-row"><td>{renderProductCell(own, true)}</td><td>{groupSnapshotValue(own, "price")}</td><td>{groupSnapshotValue(own, "moq")}</td><td>{groupSnapshotValue(own, "sku")}</td><td>{groupSnapshotValue(own, "stock")}</td><td>—</td><td>{formatGroupDetailLatestChange(own.latest_change)}</td><td>—</td></tr>}
        {data.competitors.map((product) => {
          const difference = getGroupDifferenceLabels(product.comparison, own !== null);
          const noDifference = difference.primary.length === 0 && difference.stock.length === 0 && !difference.hasUnknown;
          return <tr key={product.id}><td>{renderProductCell(product, false)}</td><td>{groupSnapshotValue(product, "price")}</td><td>{groupSnapshotValue(product, "moq")}</td><td>{groupSnapshotValue(product, "sku")}</td><td>{groupSnapshotValue(product, "stock")}</td><td><div className="group-difference-list">{difference.primary.map((label) => <span className="group-difference-primary" key={label}>{label}</span>)}{difference.stock.map((label) => <span className="group-difference-stock" key={label}>{label}</span>)}{noDifference && <span className="group-difference-neutral">基本持平</span>}{difference.hasUnknown && <span className="group-difference-unknown">部分数据未知</span>}</div></td><td>{formatGroupDetailLatestChange(product.latest_change)}</td><td><button type="button" className="detail-button" onClick={() => onOpenDetail(product.id)}>查看详情</button></td></tr>;
        })}
      </tbody></table></div>}
    </section>

    <GroupDynamics data={data} days={days} tab={dynamicTab} rangeLoading={rangeLoading} rangeError={rangeError} onSelectTab={selectDynamicTab} onOpenDetail={onOpenDetail} />
  </AppShell>;
}

export function GroupDynamics({ data, days, tab, rangeLoading, rangeError, onSelectTab, onOpenDetail }: {
  data: GroupDetailData; days: 7 | 30; tab: "today" | 7 | 30; rangeLoading: boolean; rangeError: string | null;
  onSelectTab: (tab: "today" | 7 | 30) => void; onOpenDetail: (competitorId: number) => void;
}) {
  const todayMode = tab === "today";
  const visibleActions = data.action_window.competitors.slice(0, 5);
  return <section className="table-card group-detail-section group-dynamics-section">
    <div className="table-heading group-dynamics-heading"><div><h2>竞争动态</h2><span>{todayMode ? `变化竞品 ${data.today.changed_competitor_count} · 竞品事件 ${data.today.competitor_event_count} · 我方事件 ${data.today.own_event_count}` : `竞品 ${data.action_window.competitor_event_count} 次 · 我方 ${data.action_window.own_event_count} 次`}</span></div><div className="group-dynamics-tabs" role="group" aria-label="竞争动态范围" aria-busy={rangeLoading}>{(["today", 7, 30] as const).map((range) => <button type="button" key={range} className={tab === range ? "group-dynamics-tab group-dynamics-tab-active" : "group-dynamics-tab"} aria-pressed={tab === range} disabled={rangeLoading && range !== "today"} onClick={() => onSelectTab(range)}>{range === "today" ? "今日" : `近 ${range} 天`}</button>)}</div></div>
    {rangeLoading && !todayMode && <div className="group-range-loading" role="status">正在更新动作范围…</div>}
    {rangeError && !todayMode && <div className="group-range-error" role="alert">{rangeError} · 可重新选择时间范围重试</div>}
    {todayMode ? data.today.events.length === 0 ? <div className="group-compact-empty">今日暂无变化</div> : <ol className="group-dynamic-list">{data.today.events.map((event) => <li className="group-dynamic-event" key={event.id}><time title={formatDate(event.detected_at)}>{formatGroupUpdateTime(event.detected_at)}</time><span className={event.role === "own" ? "group-dynamic-role group-dynamic-role-own" : "group-dynamic-role"}>{event.role === "own" ? "我方" : "竞品"}</span><span className="group-dynamic-product" title={event.title?.trim() || `Offer ${event.offer_id}`}>{event.title?.trim() || `Offer ${event.offer_id}`}</span><strong>{formatChange(event)}</strong>{event.role === "competitor" && <button type="button" className="detail-button" onClick={() => onOpenDetail(event.competitor_id)}>详情</button>}</li>)}</ol> : visibleActions.length === 0 ? <div className="group-compact-empty">近 {days} 天暂无竞品动作</div> : <ol className="group-action-list">{visibleActions.map((item) => <li className="group-action-item" key={item.competitor_id}><div className="group-action-main"><span className="group-action-rank" aria-hidden="true" /><strong title={item.title?.trim() || `Offer ${item.offer_id}`}>{item.title?.trim() || `Offer ${item.offer_id}`}</strong><span className="group-action-count">{item.event_count} 次</span><button type="button" className="detail-button" onClick={() => onOpenDetail(item.competitor_id)}>详情</button></div><div className="group-action-meta"><span>{getNonzeroGroupActionDomains(item.domain_counts).join(" · ")}</span><time title={formatDate(item.latest_change_at)}>最近：{formatDate(item.latest_change_at)}</time></div></li>)}</ol>}
  </section>;
}

export function GroupNameDialog({ mode, name, submitting, error, onChange, onClose, onSubmit }: { mode: "create" | "rename"; name: string; submitting: boolean; error: string | null; onChange: (name: string) => void; onClose: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  const isRename = mode === "rename";
  return <div className="dialog-backdrop" role="presentation"><section className="dialog group-name-dialog" role="dialog" aria-modal="true" aria-labelledby="group-name-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="group-name-dialog-title">{isRename ? "重命名竞品组" : "新增竞品组"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    <p className="dialog-description">{isRename ? "修改竞品组名称，不影响竞品及历史监控数据。" : "竞品组使用我方商品型号命名，用于归集该商品对应的竞品。"}</p>
    <form onSubmit={onSubmit}><label htmlFor="group-name">竞品组名称</label><input id="group-name" value={name} onChange={(event) => onChange(event.target.value)} placeholder="使用商品型号命名，例如 A19、X6" maxLength={64} autoComplete="off" disabled={submitting} />{error && <div className="feedback feedback-server-error" role="alert">{error}</div>}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="submit" className="primary-button" disabled={submitting || !name.trim()}>{submitting ? "保存中…" : isRename ? "保存" : "新增竞品组"}</button></div></form>
  </section></div>;
}

export function GroupAssignmentDialog({ groupId, groups, submitting, error, onChange, onClose, onSubmit }: { groupId: number | null; groups: CompetitorGroup[]; submitting: boolean; error: string | null; onChange: (groupId: number | null) => void; onClose: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="group-assignment-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="group-assignment-dialog-title">修改竞品组</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    <p className="dialog-description">调整当前竞品所属的竞品组。</p>
    <form onSubmit={onSubmit}><label htmlFor="detail-competitor-group">竞品组</label><select id="detail-competitor-group" value={groupId === null ? "" : String(groupId)} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} disabled={submitting}><option value="">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select>{error && <div className="feedback feedback-server-error" role="alert">{error}</div>}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="submit" className="primary-button" disabled={submitting}>{submitting ? "保存中…" : "保存"}</button></div></form>
  </section></div>;
}

export function BatchGroupAssignmentDialog({ targetGroupId, groups, selectedCount, eligibleCount, ownCount, submitting, error, onChange, onClose, onSubmit }: { targetGroupId: number | null | undefined; groups: CompetitorGroup[]; selectedCount: number; eligibleCount: number; ownCount: number; submitting: boolean; error: string | null; onChange: (groupId: number | null | undefined) => void; onClose: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="batch-group-assignment-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="batch-group-assignment-dialog-title">批量设置竞品组</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    <p className="dialog-description">已选择 {selectedCount} 个商品<br />本次修改 {eligibleCount} 个直接竞品{ownCount > 0 && <><br />{ownCount} 个我方商品不会参与本次批量分组</>}</p>
    <form onSubmit={onSubmit}><label htmlFor="batch-competitor-group">目标竞品组</label><select id="batch-competitor-group" value={targetGroupId === undefined ? "" : targetGroupId === null ? "__unassigned__" : String(targetGroupId)} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "__unassigned__" ? null : Number(event.target.value))} disabled={submitting}><option value="">请选择竞品组</option><option value="__unassigned__">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select>{error && <div className="feedback feedback-server-error" role="alert">{error}</div>}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="submit" className="primary-button" disabled={submitting || targetGroupId === undefined}>{submitting ? "设置中…" : "确认设置"}</button></div></form>
  </section></div>;
}

export function GroupDeleteDialog({ group, submitting, error, onClose, onConfirm }: { group: CompetitorGroupSummary; submitting: boolean; error: string | null; onClose: () => void; onConfirm: () => void }) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="group-delete-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="group-delete-dialog-title">删除竞品组</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    <p className="dialog-description">删除竞品组“{group.name}”？<br />该组下有 {group.competitor_count} 个竞品。<br />删除后，{group.competitor_count} 个竞品将移至“未分组”，竞品及历史监控数据不会删除。</p>
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="button" className="danger-button" onClick={onConfirm} disabled={submitting}>{submitting ? "删除中…" : "删除竞品组"}</button></div>
  </section></div>;
}

type ListPageProps = {
  competitors: Competitor[];
  groups: CompetitorGroup[];
  status: ListStatus;
  error: string | null;
  onRetry: () => void;
  onAdd?: () => void;
  ownership?: "self" | "competitor";
  batchState?: BatchState;
  selectedIds?: Set<number>;
  onToggleSelected?: (competitorId: number) => void;
  onToggleAll?: (checked: boolean, competitorIds: number[]) => void;
  onReconcileSelection?: (visibleIds: number[]) => void;
  onBatchAction?: (mode: BatchAction, selectedCompetitorIds?: number[]) => void;
  onOpenDetail?: (competitorId: number) => void;
  onOpenGroupAssignment?: (competitor: Competitor) => void;
  onNavigate?: (page: Page) => void;
  initialGroupFilter?: InitialGroupFilter;
  navigationVersion?: number;
  paginationResetVersion?: number;
};

function isSelfProduct(competitor: Competitor): boolean {
  return competitor.ownership === "self";
}

export function ListPage({ competitors, groups, status, error, onRetry, onAdd = noop, ownership = "competitor", batchState = idleBatchState, selectedIds = new Set<number>(), onToggleSelected = noop, onToggleAll = noop, onReconcileSelection = noop, onBatchAction = noop, onOpenDetail, onOpenGroupAssignment = noop, onNavigate, initialGroupFilter = null, navigationVersion = 0, paginationResetVersion = 0 }: ListPageProps) {
  const [batchMenuOpen, setBatchMenuOpen] = useState(false);
  const [filters, setFilters] = useState<CompetitorFilters>(defaultCompetitorFilters);
  const [currentPage, setCurrentPage] = useState(1);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const filteredCompetitors = useMemo(() => filterCompetitors(competitors, filters), [competitors, filters]);
  const pagination = paginateCompetitors(filteredCompetitors, currentPage);
  const pagedCompetitors = pagination.items;
  const collectedCount = filteredCompetitors.filter((item) => item.last_collected_at !== null).length;
  const selectedFilteredCompetitors = filteredCompetitors.filter((item) => selectedIds.has(item.id));
  const selectedCount = selectedFilteredCompetitors.length;
  const selectedActiveCompetitors = selectedFilteredCompetitors.filter((item) => item.is_active);
  const selectedActiveCount = selectedActiveCompetitors.length;
  const selectedInactiveCompetitors = selectedFilteredCompetitors.filter((item) => !item.is_active);
  const selfPage = ownership === "self";
  const selectedGroupCompetitors = selectedFilteredCompetitors.filter((item) => !isSelfProduct(item));
  const selectedGroupCount = selectedGroupCompetitors.length;
  const selectedOwnCount = selectedFilteredCompetitors.filter(isSelfProduct).length;
  const batchBusy = batchState.runner_active || batchState.browser_open || batchState.status === "running" || batchState.status === "cooling_down";
  const pageIds = pagedCompetitors.map((item) => item.id);
  const selectedPageCount = pageIds.filter((id) => selectedIds.has(id)).length;
  const allSelected = pageIds.length > 0 && selectedPageCount === pageIds.length;
  const partiallySelected = selectedPageCount > 0 && !allSelected;
  function updateFilters(update: (current: CompetitorFilters) => CompetitorFilters) {
    setFilters(update);
    setCurrentPage(1);
  }
  function resetFilters() {
    setFilters(defaultCompetitorFilters);
    setCurrentPage(1);
  }
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = partiallySelected;
  }, [partiallySelected]);
  useEffect(() => {
    onReconcileSelection(filteredCompetitors.map((item) => item.id));
  }, [filteredCompetitors, onReconcileSelection]);
  useEffect(() => {
    setFilters((current) => applyInitialGroupFilter(current, initialGroupFilter));
    setCurrentPage(1);
  }, [initialGroupFilter, navigationVersion]);
  useEffect(() => {
    setCurrentPage((page) => Math.min(page, pagination.totalPages));
  }, [pagination.totalPages]);
  useEffect(() => {
    setCurrentPage(1);
  }, [paginationResetVersion]);
  return (
    <AppShell page={ownership === "self" ? "own-products" : "competitors"} onNavigate={onNavigate || (() => undefined)} breadcrumb={ownership === "self" ? "我方商品" : "竞品列表"}>
        <header className="page-header"><div><h1>{selfPage ? "我方商品" : "竞品列表"}</h1><p className="page-description">{selfPage ? "查看已识别为我方店铺的监控商品，并管理采集与竞品组关系。" : "查看当前已添加的 1688 竞品，并管理监控对象。"}</p></div><div className="page-actions"><div className="batch-menu"><button type="button" className="secondary-button batch-trigger" aria-haspopup="menu" aria-expanded={batchMenuOpen} onClick={() => setBatchMenuOpen((open) => !open)} disabled={batchBusy}>批量操作（{selectedCount}） <span aria-hidden="true">▼</span></button>{batchMenuOpen && <div className="batch-menu-popover" role="menu">{!selfPage && <><button type="button" role="menuitem" disabled={selectedGroupCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("group", selectedFilteredCompetitors.map((item) => item.id)); }}>设置分组（{selectedGroupCount}）</button><span className="batch-menu-divider" role="separator" /></>}<button type="button" role="menuitem" disabled={selectedActiveCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("stop", selectedFilteredCompetitors.map((item) => item.id)); }}>停止监控（{selectedActiveCount}）</button><button type="button" role="menuitem" disabled={selectedInactiveCompetitors.length === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("resume", selectedFilteredCompetitors.map((item) => item.id)); }}>恢复监控（{selectedInactiveCompetitors.length}）</button>{!selfPage && <><span className="batch-menu-divider" role="separator" /><button type="button" role="menuitem" className="batch-menu-danger" disabled={selectedGroupCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("delete", selectedFilteredCompetitors.map((item) => item.id)); }}>删除竞品（{selectedGroupCount}）</button></>}</div>}</div></div></header>
        {batchState.status === "running" && <div className="batch-status-panel batch-status-running" role="status">采集中 {batchState.completed} / {batchState.total} · 成功 {batchState.succeeded} · 失败 {batchState.failed}</div>}
        {batchState.status === "cooling_down" && <div className="batch-status-panel batch-status-cooling_down" role="status">1688 验证已触发，浏览器已自动关闭。将在 {formatBatchCooldown(batchState.cooldown_remaining_seconds)} 后自动继续采集（自动恢复 {batchState.auto_resume_attempt}/{batchState.auto_resume_max}）。<span>已完成 {batchState.completed} / {batchState.total}，剩余 {batchState.remaining}</span></div>}
        {batchState.status === "completed" && <div className="batch-status-panel" role="status">采集完成：成功 {batchState.succeeded}，失败 {batchState.failed}</div>}
        {batchState.status === "verification_required" && <div className="batch-status-panel batch-status-verification" role="alert">1688 需要人工验证，本次采集已停止。请在弹出的浏览器中完成处理，关闭浏览器后可重新发起采集。<span>已完成 {batchState.completed} / {batchState.total}，剩余 {batchState.remaining}</span></div>}
        <section className="filter-card" aria-label="搜索和筛选">
          <div className="filter-field filter-search"><input id="search" aria-label="搜索商品名称 / offerId / 店铺" value={filters.search} onChange={(event) => updateFilters((current) => ({ ...current, search: event.target.value }))} placeholder="搜索商品名称 / offerId / 店铺" /></div>
          <div className="filter-field"><label htmlFor="product-status">商品状态</label><select id="product-status" value={filters.status} onChange={(event) => updateFilters((current) => ({ ...current, status: event.target.value as CompetitorFilters["status"] }))}><option value="all">全部状态</option><option value="active">在售</option><option value="offline">已下架</option><option value="unknown">状态未知</option></select></div>
          <div className="filter-field"><label htmlFor="collection-status">采集状态</label><select id="collection-status" value={filters.collectionStatus} onChange={(event) => updateFilters((current) => ({ ...current, collectionStatus: event.target.value as CompetitorFilters["collectionStatus"] }))}><option value="all">全部状态</option><option value="collected">已采集</option><option value="not_collected">未采集</option></select></div>
          <div className="filter-field"><label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={filters.groupId === "all" ? "all" : String(filters.groupId)} onChange={(event) => updateFilters((current) => ({ ...current, groupId: event.target.value === "all" || event.target.value === "unassigned" ? event.target.value : Number(event.target.value) }))}><option value="all">全部竞品组</option><option value="unassigned">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></div>
          <button type="button" className="text-button" onClick={resetFilters}>重置</button>
        </section>
        <section className="stats-strip" aria-label="列表统计">
          <div className="stat-total"><strong>共 {status === "ready" ? filteredCompetitors.length : "—"} 个{selfPage ? "我方商品" : "竞品"}</strong></div>
          <div className="stat-item"><span>已采集数量</span><strong>{status === "ready" ? collectedCount : "—"}</strong></div>
          <div className="stat-item"><span>未采集数量</span><strong>{status === "ready" ? filteredCompetitors.length - collectedCount : "—"}</strong></div>
        </section>
        <section className="table-card">
          <div className="table-heading"><div><h2>{selfPage ? "全部我方商品" : "全部竞品"}</h2><span>按添加时间倒序展示</span></div><span className="table-count">{status === "ready" ? filteredCompetitors.length + " 个商品" : status === "loading" ? "加载中" : "—"}</span></div>
          {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>{selfPage ? "正在加载我方商品…" : "正在加载竞品列表…"}</strong></div>}
          {status === "error" && <div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品列表。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div>}
          {status === "ready" && competitors.length === 0 && <div className="state-panel"><div className="empty-icon">+</div><strong>{selfPage ? "还没有我方商品" : "还没有添加竞品"}</strong><span>{selfPage ? "从竞品监控大屏添加商品后，识别为我方店铺的商品会出现在这里。" : "从竞品监控大屏添加一个 1688 商品链接，开始建立你的监控列表。"}</span></div>}
          {status === "ready" && competitors.length > 0 && filteredCompetitors.length === 0 && <div className="state-panel"><strong>{selfPage ? "没有找到符合条件的我方商品" : "没有找到符合条件的竞品"}</strong><span>请调整搜索词或筛选条件</span><button type="button" className="secondary-button" onClick={resetFilters}>重置筛选</button></div>}
          {status === "ready" && filteredCompetitors.length > 0 && <div className="table-scroll"><table><thead><tr><th className="selection-column"><input ref={selectAllRef} type="checkbox" aria-label="全选当前页全部商品" checked={allSelected} disabled={pageIds.length === 0 || batchBusy} onChange={(event) => onToggleAll(event.target.checked, pageIds)} /></th><th>商品信息</th><th>店铺名称</th><th>竞品组</th><th>当前价格</th><th>SKU 数量</th><th>最近变化</th><th>最近采集时间</th><th>商品状态</th><th>监控状态</th><th>操作</th></tr></thead><tbody>
             {pagedCompetitors.map((competitor) => <tr key={competitor.id}><td className="selection-column"><input type="checkbox" aria-label={`选择 ${competitor.title || competitor.offer_id}`} checked={selectedIds.has(competitor.id)} disabled={batchBusy} onChange={() => onToggleSelected(competitor.id)} /></td><td><div className="product-cell"><ProductImage competitor={competitor} /><div><strong>{competitor.title || "未采集"} {isSelfProduct(competitor) && <span className="own-role-badge">我方</span>}</strong><span>offerId：{competitor.offer_id}</span><a href={competitor.url} target="_blank" rel="noreferrer">查看 1688 商品 ↗</a></div></div></td><td>{competitor.shop_name || "未采集"}</td><td><div className="list-group-cell"><span>{getCompetitorGroupLabel(competitor.group_id, groups)}</span><button type="button" className="text-button" onClick={() => onOpenGroupAssignment(competitor)}>{competitor.group_id === null ? "+ 绑定竞品组" : "更换/解除"}</button></div></td><td className={competitor.latest_snapshot?.price_min || competitor.latest_snapshot?.price_max ? "price-cell" : "muted-cell"}>{formatPriceDisplay(competitor.latest_snapshot)}</td><td className={competitor.latest_snapshot === null ? "muted-cell" : "sku-cell"}>{competitor.latest_snapshot === null ? "未采集" : competitor.latest_snapshot.sku_count}</td><td className={competitor.latest_change === null ? "muted-cell" : "change-cell"}>{formatLatestChange(competitor.latest_change)}</td><td className="collection-date-cell">{formatDate(competitor.last_collected_at)}</td><td><StatusBadge status={competitor.status} /></td><td><span className={competitor.is_active ? "list-monitoring-badge" : "list-monitoring-badge list-monitoring-inactive"}>{competitor.is_active ? "监控中" : "已停止"}</span></td><td><button type="button" className="detail-button" onClick={() => onOpenDetail?.(competitor.id)}>详情</button></td></tr>) }
          </tbody></table></div>}
        </section>
        <PaginationBar total={filteredCompetitors.length} itemLabel={selfPage ? "个我方商品" : "个竞品"} page={pagination.page} totalPages={pagination.totalPages} onPrevious={() => setCurrentPage((page) => page - 1)} onNext={() => setCurrentPage((page) => page + 1)} previousDisabled={pagination.page === 1} nextDisabled={pagination.page === pagination.totalPages} />
    </AppShell>
  );
}

type DashboardPageProps = {
  data: DashboardData | null;
  attention: GroupAttentionData | null;
  attentionStatus: DashboardStatus;
  attentionError: string | null;
  status: DashboardStatus;
  error: string | null;
  batchState?: BatchState;
  onRetry: () => void;
  onNavigate: (page: Page) => void;
  ownShopName?: string | null;
  onAdd?: () => void;
  onCollect?: () => void;
  onOpenGroupDetail?: (groupId: number) => void;
  onRetryAttention: () => void;
};

function DashboardIcon({ kind }: { kind: "groups" | "changed-groups" | "competitors" | "error" }) {
  const paths = {
    groups: <><rect x="3.5" y="4" width="7" height="6" rx="1.5" /><rect x="13.5" y="4" width="7" height="6" rx="1.5" /><rect x="3.5" y="14" width="7" height="6" rx="1.5" /><rect x="13.5" y="14" width="7" height="6" rx="1.5" /></>,
    "changed-groups": <><path d="M4 6h9M4 12h6M4 18h9" /><path d="m15 10 3 3 3-3M18 13V4" /></>,
    competitors: <><circle cx="8" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M2.5 20c.4-3.4 2.2-5 5.5-5s5.1 1.6 5.5 5M14 15c3.8-.8 6.4.7 7.3 4" /></>,
    error: <><path d="M12 4 21 20H3L12 4Z" /><path d="M12 9v5M12 17h.01" /></>,
  };
  return <svg className="dashboard-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[kind]}</svg>;
}

function DashboardStatCard({ label, value, kind, tone }: { label: string; value: number | string; kind: "groups" | "changed-groups" | "competitors" | "error"; tone: string }) {
  return <div className="dashboard-stat-card"><span className={`dashboard-stat-icon dashboard-stat-${tone}`}><DashboardIcon kind={kind} /></span><div><span>{label}</span><strong>{value}</strong></div></div>;
}

export function DashboardTrendChart({ trend }: { trend: DashboardTrendPoint[] }) {
  const width = 640;
  const height = 180;
  const top = 14;
  const bottom = 28;
  const left = 52;
  const right = 14;
  const plotHeight = height - top - bottom;
  const scale = buildDashboardTrendScale(trend.slice(-7));
  const points = buildDashboardTrendChartPoints(trend, width, height);
  const series = [
    ["price_changes", "变价", "dashboard-trend-price"],
    ["stock_changes", "库存变化", "dashboard-trend-stock"],
    ["sku_changes", "SKU变化", "dashboard-trend-sku"],
    ["failed_collections", "异常采集", "dashboard-trend-error"],
  ] as const;
  const line = (key: keyof DashboardTrendChartPoint["y"]) => points.map((point) => `${point.x},${point.y[key]}`).join(" ");
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const activePoint = activeIndex === null ? null : points[activeIndex];
  const activeTooltip = activePoint ? formatDashboardTrendTooltip(activePoint) : [];
  return <div className="dashboard-trend-wrap" onMouseLeave={() => setActiveIndex(null)}><svg className="dashboard-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="近 7 天竞品变化趋势">
    {scale.ticks.map((tick) => { const y = chartY(tick, scale.domain[0], scale.domain[1], top, plotHeight); return <g key={tick}><line className="chart-grid-line" x1={left} x2={width - right} y1={y} y2={y} /><text className="chart-label chart-y-label" x={left - 8} y={y + 3} textAnchor="end">{tick}</text></g>; })}
    {activePoint && <line className="chart-hover-line" x1={activePoint.x} x2={activePoint.x} y1={top} y2={top + plotHeight} />}
    {series.map(([key, _label, className]) => <polyline key={key} className={`dashboard-trend-line ${className}`} points={line(key)} />)}
    {series.map(([key, _label, className]) => points.map((point, index) => <circle key={`${key}-${point.date}`} className={`dashboard-trend-point ${className}${activeIndex === index ? " chart-point-active" : ""}`} cx={point.x} cy={point.y[key]} r={activeIndex === index ? 4.5 : 3} />))}
    {points.map((point, index) => <g key={`hit-${point.date}`} onMouseEnter={() => setActiveIndex(index)}><rect className="chart-hit-area" x={point.x - (points.length === 1 ? 18 : 14)} y={top} width={points.length === 1 ? 36 : 28} height={plotHeight} /></g>)}
    {points.map((point) => <text key={point.date} className="chart-label" x={point.x} y="170" textAnchor="middle">{point.date.slice(5).replace("-", "/")}</text>)}
  </svg>{activeTooltip.length > 0 && <div className="dashboard-trend-tooltip" role="status" style={{ left: `${Math.min(91, Math.max(9, ((activeIndex ?? 0) / Math.max(1, points.length - 1)) * 100))}%` }}>{activeTooltip.map((line) => <span key={line}>{line}</span>)}</div>}<div className="chart-legend">{series.map(([key, label, className]) => <span key={key}><i className={`legend-dot ${className}`} />{label}</span>)}</div></div>;
}

export function OwnProductDialog({ group, mode, competitors, loading, selectedId, confirming, submitting, error, onSelect, onConfirmStep, onClose, onSubmit }: { group: CompetitorGroupSummary; mode: OwnProductAction; competitors: Competitor[]; loading: boolean; selectedId: number | null; confirming: boolean; submitting: boolean; error: string | null; onSelect: (id: number) => void; onConfirmStep: () => void; onClose: () => void; onSubmit: () => void }) {
  const choices = competitors.filter((competitor) => competitor.group_id === group.id && competitor.id !== group.own_product?.id);
  const selected = choices.find((competitor) => competitor.id === selectedId);
  const title = (competitor: Competitor) => competitor.title || `Offer ${competitor.offer_id}`;
  return <div className="dialog-backdrop" role="presentation"><section className="dialog own-product-dialog" role="dialog" aria-modal="true" aria-labelledby="own-product-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">{group.name}</p><h2 id="own-product-dialog-title">{mode === "unbind" ? "解除我方商品" : mode === "replace" ? "更换我方商品" : "绑定我方商品"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    {mode === "unbind" ? <p className="dialog-description">解除后，{group.own_product?.title || `Offer ${group.own_product?.offer_id}`} 仍保留在当前组，并作为普通竞品继续按照现有监控状态运行。历史数据不会删除。</p> : <>
      <p className="dialog-description">{mode === "replace" && confirming && selected ? <>将我方商品从“{group.own_product?.title || `Offer ${group.own_product?.offer_id}`}”更换为“{title(selected)}”？原商品会保留在该组并变为普通竞品，历史监控数据不会删除。</> : "选择当前组中已有的商品。"}</p>
      {loading ? <p className="own-product-empty">正在加载组内商品…</p> : choices.length === 0 ? <p className="own-product-empty">当前竞品组还没有可绑定商品。请先通过“添加竞品”将我方商品链接加入该竞品组，再回来绑定。</p> : <div className="own-product-candidates" role="radiogroup" aria-label="选择我方商品">
        {choices.map((competitor) => <label key={competitor.id} className="own-product-candidate"><input type="radio" name="own-product-candidate" checked={selectedId === competitor.id} onChange={() => onSelect(competitor.id)} disabled={submitting || confirming} /><span><strong>{title(competitor)}</strong><small>{competitor.shop_name || "店铺未采集"} · Offer {competitor.offer_id}</small><small>商品：{competitor.status === "unknown" ? "未知" : competitor.status === "active" ? "在售" : "已下架"} · {competitor.is_active ? "监控中" : "已停止"}</small></span></label>)}
      </div>}
    </>}
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button>{mode === "replace" && !confirming ? <button type="button" className="primary-button" onClick={onConfirmStep} disabled={submitting || selectedId === null}>继续</button> : <button type="button" className="primary-button" onClick={onSubmit} disabled={submitting || (mode !== "unbind" && (!selected || loading))}>{submitting ? "保存中…" : mode === "unbind" ? "确认解除" : mode === "replace" ? "确认更换" : "绑定为我方商品"}</button>}</div>
  </section></div>;
}

function CollectionOverview({ data, status, error, batchState, onRetry }: { data: DashboardData | null; status: DashboardStatus; error: string | null; batchState: BatchState; onRetry: () => void }) {
  const summary = status === "ready" ? data?.collection_summary : null;
  const busy = batchState.status === "running" || batchState.status === "cooling_down" || batchState.runner_active || batchState.browser_open;
  const progress = batchState.total > 0 ? Math.min(100, (batchState.completed / batchState.total) * 100) : 0;
  return <section className="table-card collection-overview"><div className="table-heading"><div><h2>采集状态概览</h2><span>数据库记录与当前批次</span></div><span className={busy ? "overview-status overview-status-running" : batchState.status === "verification_required" ? "overview-status overview-status-warning" : "overview-status"}>{batchState.status === "running" ? "采集中" : batchState.status === "cooling_down" ? "冷却中" : batchState.status === "verification_required" ? "需要人工验证" : batchState.status === "completed" ? "最近批次完成" : "当前无采集任务"}</span></div>
    {status === "error" && <div className="dashboard-support-error" role="alert"><span>{error || "暂时无法获取采集统计和趋势。"}</span><button type="button" className="text-link-button" onClick={onRetry}>重试</button></div>}
    <div className="collection-summary-grid"><div><span>最近采集时间</span><strong>{summary?.last_collection_at ? formatDate(summary.last_collection_at) : "暂无采集记录"}</strong></div><div><span>今日成功</span><strong>{summary ? summary.success_runs : "—"}</strong></div><div><span>今日失败</span><strong className={summary?.failed_runs ? "collection-value-error" : ""}>{summary ? summary.failed_runs : "—"}</strong></div><div><span>平均耗时</span><strong>{formatDuration(summary?.average_duration_seconds ?? null)}</strong></div></div>
    <div className={`collection-batch collection-batch-${batchState.status}`}><div className="collection-batch-heading"><strong>{batchState.status === "running" ? `采集中 ${batchState.completed} / ${batchState.total}` : batchState.status === "cooling_down" ? "冷却中" : batchState.status === "verification_required" ? "需要人工验证" : batchState.status === "completed" ? "最近批次完成" : "当前无采集任务"}</strong><span>{batchState.status === "running" ? `成功 ${batchState.succeeded} · 失败 ${batchState.failed}` : batchState.status === "cooling_down" ? `冷却剩余 ${formatBatchCooldown(batchState.cooldown_remaining_seconds)} · 自动恢复 ${batchState.auto_resume_attempt}/${batchState.auto_resume_max} · 已完成 ${batchState.completed} · 剩余 ${batchState.remaining}` : batchState.status === "completed" ? `成功 ${batchState.succeeded} / 失败 ${batchState.failed}` : batchState.status === "verification_required" ? `已完成 ${batchState.completed} / ${batchState.total}` : "今日采集统计仍会保留"}</span></div>{batchState.status === "running" && <div className="collection-progress" role="progressbar" aria-label={`采集进度 ${batchState.completed} / ${batchState.total}`} aria-valuemin={0} aria-valuemax={batchState.total} aria-valuenow={batchState.completed}><span style={{ width: `${progress}%` }} /></div>}</div>
  </section>;
}

export function DashboardPage({ data, attention, attentionStatus, attentionError, status, error, batchState = idleBatchState, onRetry, onRetryAttention, onNavigate, ownShopName = null, onAdd = noop, onCollect = noop, onOpenGroupDetail }: DashboardPageProps) {
  const attentionValue = (field: keyof GroupAttentionData["kpis"]) => attentionStatus === "ready" && attention ? attention.kpis[field] : "—";
  const failedCollections = status === "ready" && data ? data.stats.failed_collections : "—";
  const collectionBusy = batchState.status === "running" || batchState.status === "cooling_down" || batchState.runner_active || batchState.browser_open;
  const collectionAvailable = status === "ready" && (data?.stats.active_monitored_products ?? 0) > 0;
  return <AppShell page="dashboard" onNavigate={onNavigate} breadcrumb="竞品监控大屏">
    <header className="page-header dashboard-page-header"><div><h1>竞品监控大屏</h1><p className="page-description">先看今天值得关注的商品组，再查看采集状态与近期趋势。</p></div><div className="dashboard-header-actions"><span className="dashboard-shop-context">我方店铺：{ownShopName || "未配置"}</span>{ownShopName ? <><button type="button" className="secondary-button" onClick={onCollect} disabled={collectionBusy || !collectionAvailable}>立即采集</button><button type="button" className="primary-button" onClick={onAdd}>添加监控商品</button></> : <button type="button" className="text-link-button" onClick={() => onNavigate("settings")}>去系统设置</button>}</div></header>
    <section className="dashboard-stats" aria-label="商品组关注统计"><DashboardStatCard label="监控商品组" value={attentionValue("monitored_product_groups")} kind="groups" tone="blue" /><DashboardStatCard label="今日有变化商品组" value={attentionValue("changed_product_groups_today")} kind="changed-groups" tone="purple" /><DashboardStatCard label="今日涉及变化竞品" value={attentionValue("changed_competitors_today")} kind="competitors" tone="green" /><DashboardStatCard label="异常采集" value={failedCollections} kind="error" tone="orange" /></section>
    <section className="table-card dashboard-attention-section"><div className="table-heading"><div><h2>今日需要关注的商品组</h2><span>{attentionStatus === "ready" && attention ? attention.date : "今日"}</span></div><span className="table-count">{attentionStatus === "ready" && attention ? `${attention.groups.length} 个商品组` : "—"}</span></div>
      {attentionStatus === "loading" && <div className="dashboard-attention-state"><div className="spinner" /><strong>正在加载商品组关注信息…</strong></div>}
      {attentionStatus === "error" && <div className="dashboard-attention-state dashboard-attention-error" role="alert"><strong>暂时无法获取商品组关注信息</strong><span>{attentionError || "请检查服务后重试。"}</span><button type="button" className="secondary-button" onClick={onRetryAttention}>重试</button></div>}
      {attentionStatus === "ready" && attention && attention.groups.length === 0 && <div className="dashboard-attention-state"><strong>今日暂无需要关注的竞争变化</strong><span>有新的竞品变化时，相关商品组会显示在这里。</span></div>}
      {attentionStatus === "ready" && attention && attention.groups.length > 0 && <div className="dashboard-attention-list">{attention.groups.map((item) => <article className="dashboard-attention-card" key={item.group_id}><div className="dashboard-attention-main"><div className="dashboard-attention-identity"><h3>{item.group_name}</h3><span>{item.own_product.title?.trim() || `Offer ${item.own_product.offer_id}`}{item.own_product.shop_name ? ` · ${item.own_product.shop_name}` : ""}</span></div><span className={`dashboard-attention-level dashboard-attention-level-${item.attention_level === "重点关注" ? "high" : item.attention_level === "建议查看" ? "medium" : "low"}`}>{item.attention_level}</span></div><div className="dashboard-attention-meta"><span>今日变化竞品 <strong>{item.changed_competitor_count}</strong></span><span>最近变化 {formatDate(item.latest_change_at)}</span></div><ul className="dashboard-attention-reasons">{item.reasons.map((reason, index) => <li key={`${reason.reason_type}-${index}`}>{reason.display_text}</li>)}</ul><button type="button" className="detail-button dashboard-attention-action" onClick={() => onOpenGroupDetail?.(item.group_id)}>进入组分析</button></article>)}</div>}
    </section>
    <div className="dashboard-lower-grid"><CollectionOverview data={data} status={status} error={error} batchState={batchState} onRetry={onRetry} /><section className="table-card dashboard-trend-section"><div className="table-heading"><div><h2>近 7 天竞品变化趋势</h2><span>每天真实监控事件数量</span></div><span className="trend-period">连续 7 个业务日</span></div>{status === "ready" && data ? <DashboardTrendChart trend={data.trend_7d} /> : <div className="dashboard-trend-placeholder">{status === "error" ? "趋势暂不可用" : "—"}</div>}</section></div>
  </AppShell>;
}

type DetailStatus = "loading" | "error" | "ready";
type DetailPageProps = {
  data: CompetitorDetail | null;
  groups: CompetitorGroup[];
  status: DetailStatus;
  error: string | null;
  days: 7 | 30;
  rangeLoading?: boolean;
  onRetry: () => void;
  onRangeChange: (days: 7 | 30) => void;
  onBack: () => void;
  onChangeGroup?: () => void;
  onLifecycleAction?: (action: LifecycleAction, competitor: LifecycleCompetitor) => void;
  lifecycleSubmitting?: boolean;
  onNavigate: (page: Page) => void;
};

function formatChartDate(value: string): string {
  const date = value.includes("T") ? new Date(value) : new Date(`${value}T00:00:00+08:00`);
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", timeZone: "Asia/Shanghai" }).format(date);
}

function shouldShowChartLabel(index: number, length: number): boolean {
  if (length <= 8) return true;
  const step = Math.ceil((length - 1) / 6);
  return index === 0 || index === length - 1 || index % step === 0;
}

function lineSegments<T extends { x: number }>(points: readonly T[], key: keyof T): string[][] {
  const segments: string[][] = [];
  let segment: string[] = [];
  for (const point of points) {
    const value = point[key];
    if (typeof value !== "number") {
      if (segment.length > 0) segments.push(segment);
      segment = [];
      continue;
    }
    segment.push(`${point.x},${value}`);
  }
  if (segment.length > 0) segments.push(segment);
  return segments;
}

export function formatStockDisplay(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatPriceTick(value: number, step: number): string {
  const decimals = Number.isInteger(step) ? 0 : step * 10 % 1 === 0 ? 1 : 2;
  return `¥${value.toFixed(decimals)}`;
}

function formatPriceTrendValue(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : value;
}

export function formatTrendTooltip(point: DailyTrendPoint, kind: "price" | "stock"): string[] {
  const date = formatChartDate(point.date);
  if (kind === "stock") return point.total_stock === null ? [] : [date, `库存 ${formatStockDisplay(point.total_stock)}`];
  if (point.price_min === null && point.price_max === null) return [];
  if (point.price_min !== null && point.price_max !== null && Number(point.price_min) === Number(point.price_max)) return [date, `价格 ¥${formatPriceTrendValue(point.price_min)}`];
  return [date, ...(point.price_min === null ? [] : [`最低价 ¥${formatPriceTrendValue(point.price_min)}`]), ...(point.price_max === null ? [] : [`最高价 ¥${formatPriceTrendValue(point.price_max)}`])];
}

function DetailTrendChart({ kind, trend }: { kind: "price" | "stock"; trend: DailyTrendPoint[] }) {
  const width = 640;
  const height = 170;
  const top = 16;
  const bottom = 30;
  const plotHeight = height - top - bottom;
  const pricePoints = kind === "price" ? buildPriceChartPoints(trend, width, height) : [];
  const stockPoints = kind === "stock" ? buildStockChartPoints(trend, width, height) : [];
  const scale = kind === "price" ? buildPriceChartScale(trend) : buildStockChartScale(trend);
  const points = kind === "price" ? pricePoints : stockPoints;
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (points.length === 0 || scale === null) return <div className="detail-chart-empty">该时间范围暂无可用{kind === "price" ? "价格" : "库存"}数据</div>;
  const hitAreas = buildTrendHitAreas(points, detailChartLeft, width - detailChartRight);
  const activeChartPoint = activeIndex === null ? null : points[activeIndex];
  const activeTrendPoint = activeIndex === null ? null : trend[activeIndex];
  const activeTooltip = activeTrendPoint ? formatTrendTooltip(activeTrendPoint, kind) : [];
  return <div className="detail-chart-shell" onMouseLeave={() => setActiveIndex(null)}>
    <svg className="detail-trend-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={kind === "price" ? "价格趋势" : "库存趋势"}>
      {scale.ticks.map((tick) => { const y = chartY(tick, scale.domain[0], scale.domain[1], top, plotHeight); return <g key={tick}><line className="chart-grid-line" x1={detailChartLeft} x2={width - detailChartRight} y1={y} y2={y} /><text className="chart-label chart-y-label" x={detailChartLeft - 8} y={y + 3} textAnchor="end">{kind === "price" ? formatPriceTick(tick, scale.step) : formatStockDisplay(tick)}</text></g>; })}
      {hitAreas.map((area, index) => <rect key={`hit-${index}`} className="chart-hit-area" x={area.x} y={top} width={area.width} height={plotHeight} onMouseEnter={() => setActiveIndex(index)} />)}
      {activeChartPoint && <line className="chart-hover-line" x1={activeChartPoint.x} x2={activeChartPoint.x} y1={top} y2={top + plotHeight} />}
      {kind === "price" ? <>
        {lineSegments(pricePoints, "min_y").map((segment, index) => <polyline key={`min-${index}`} className="chart-line chart-line-min" points={segment.join(" ")} />)}
        {lineSegments(pricePoints, "max_y").map((segment, index) => <polyline key={`max-${index}`} className="chart-line chart-line-max" points={segment.join(" ")} />)}
        {pricePoints.map((point, index) => <g key={point.date} className={activeIndex === index ? "chart-point-group-active" : undefined} onMouseEnter={() => setActiveIndex(index)}>
          {point.min_y !== null && <circle className="chart-point chart-point-min" cx={point.x} cy={point.min_y} r={activeIndex === index ? 5 : 4} />}
          {point.max_y !== null && <circle className="chart-point chart-point-max" cx={point.x} cy={point.max_y} r={activeIndex === index ? 5 : 4} />}
          {shouldShowChartLabel(index, pricePoints.length) && <text className="chart-label" x={point.x} y={height - 8} textAnchor="middle">{formatChartDate(point.date)}</text>}
        </g>)}
      </> : <>
        {lineSegments(stockPoints, "y").map((segment, index) => <polyline key={`stock-${index}`} className="chart-line chart-line-stock" points={segment.join(" ")} />)}
        {stockPoints.map((point, index) => <g key={point.date} className={activeIndex === index ? "chart-point-group-active" : undefined} onMouseEnter={() => setActiveIndex(index)}>
          {point.y !== null && <circle className="chart-point chart-point-stock" cx={point.x} cy={point.y} r={activeIndex === index ? 5 : 4} />}
          {shouldShowChartLabel(index, stockPoints.length) && <text className="chart-label" x={point.x} y={height - 8} textAnchor="middle">{formatChartDate(point.date)}</text>}
        </g>)}
      </>}
    </svg>
    {activeTooltip.length > 0 && <div className="detail-chart-tooltip" role="status" style={{ left: `${Math.min(88, Math.max(12, ((activeIndex ?? 0) / Math.max(1, points.length - 1)) * 100))}%` }}>{activeTooltip.map((line) => <span key={line}>{line}</span>)}</div>}
    {kind === "price" ? <div className="chart-legend"><span><i className="legend-dot legend-dot-min" />最低价</span><span><i className="legend-dot legend-dot-max" />最高价</span></div> : <div className="chart-legend"><span><i className="legend-dot legend-dot-stock" />库存</span></div>}
  </div>;
}

function DetailOverview({ data, groups, onChangeGroup }: { data: CompetitorDetail; groups: CompetitorGroup[]; onChangeGroup?: () => void }) {
  const competitor = data.competitor;
  const latestSnapshot = data.latest_snapshot;
  const gallery = useMemo(
    () => getDetailGallery(latestSnapshot?.image_urls ?? null, competitor.main_image_url),
    [competitor.main_image_url, latestSnapshot?.image_urls],
  );
  return <section className="detail-overview table-card">
    <DetailGallery key={`${competitor.id}:${latestSnapshot?.id ?? "none"}`} imageUrls={gallery} />
    <div className="detail-overview-main">
      <h2>{competitor.title || "未采集"}</h2>
      <dl className="detail-facts">
        <div><dt>店铺名称</dt><dd>{competitor.shop_name || "未采集"}</dd></div>
        <div><dt>商品链接</dt><dd><a href={competitor.url} target="_blank" rel="noreferrer">{competitor.url}</a></dd></div>
        <div><dt>offerId</dt><dd>{competitor.offer_id}</dd></div>
        <div><dt>起批量</dt><dd>{latestSnapshot?.min_order_quantity == null ? "—" : `${latestSnapshot.min_order_quantity}件起批`}</dd></div>
        <div><dt>所属竞品组</dt><dd className="detail-group-value"><span className="detail-group-badge">{getCompetitorGroupLabel(competitor.group_id, groups)}</span><button type="button" className="detail-group-edit" onClick={onChangeGroup}>修改</button></dd></div>
        <div><dt>身份</dt><dd>{competitor.ownership === "self" ? "我方商品" : "直接竞品"}</dd></div>
      </dl>
    </div>
    <div className="detail-overview-stats">
      {competitor.status === "offline" && competitor.is_active && <p className="detail-offline-monitoring-notice">该商品已下架，目前仍在监控。</p>}
      <div className="detail-price-stat"><span>当前价格</span><div className="detail-price-value-row"><strong>{formatDetailPriceDisplay(latestSnapshot)}</strong>{data.latest_price_change && <b className="detail-price-magnitude">{formatPriceChangeMagnitude(data.latest_price_change)}</b>}</div><small>{latestSnapshot ? `采集于 ${formatDate(latestSnapshot.captured_at)}` : "暂无采集数据"}</small></div>
      <div className="detail-latest-price-change"><span>最近变价</span><strong>{formatPriceChangeTransition(data.latest_price_change)}</strong></div>
      <div className="detail-stat-grid"><div><span>商品状态</span><strong><StatusBadge status={competitor.status} /></strong></div><div><span>当前库存</span><strong>{latestSnapshot?.total_stock ?? "—"}</strong></div><div><span>SKU 数量</span><strong>{latestSnapshot ? latestSnapshot.sku_count : "—"}</strong></div><div><span>最近采集时间</span><strong>{formatDate(competitor.last_collected_at)}</strong></div><div><span>监控状态</span><strong>{competitor.is_active ? "监控中" : "已停止监控"}</strong></div></div>
    </div>
  </section>;
}

function DetailTrendCard({ kind, title, description, trend }: { kind: "price" | "stock"; title: string; description: string; trend: DailyTrendPoint[] }) {
  return <section className="table-card detail-trend-card"><div className="table-heading"><div><h3>{title}</h3><span>{description}</span></div></div><DetailTrendChart kind={kind} trend={trend} /></section>;
}

function SalesPlaceholderCard() {
  return <section className="table-card detail-trend-card detail-sales-placeholder"><div className="table-heading"><div><h3>销量趋势</h3><span>正式销量能力尚未开放</span></div></div><div className="detail-sales-placeholder-body"><strong>销量数据待接入</strong><span>当前数据源尚未达到正式采集标准</span></div></section>;
}

export function DetailPage({ data, groups, status, error, days, rangeLoading = false, onRetry, onRangeChange, onBack, onChangeGroup, onLifecycleAction, lifecycleSubmitting = false, onNavigate }: DetailPageProps) {
  if (status === "loading") return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel"><div className="spinner" /><strong>正在加载竞品详情…</strong></div></AppShell>;
  if (status === "error" || data === null) return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品详情。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div></AppShell>;
  const isSelf = data.competitor.ownership === "self";
  return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情">
    <header className="page-header detail-page-header"><div><h1>{isSelf ? "我方商品详情" : "竞品详情"}</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div><div className="detail-page-actions"><button type="button" className="secondary-button" onClick={onBack}>返回{isSelf ? "我方商品" : "竞品列表"}</button>{data.competitor.is_active ? <button type="button" className="secondary-button" onClick={() => onLifecycleAction?.("stop", data.competitor)} disabled={lifecycleSubmitting}>停止监控</button> : <button type="button" className="primary-button" onClick={() => onLifecycleAction?.("resume", data.competitor)} disabled={lifecycleSubmitting}>恢复监控</button>}<button type="button" className="detail-danger-button" onClick={() => onLifecycleAction?.("delete", data.competitor)} disabled={lifecycleSubmitting}>删除{isSelf ? "我方商品" : "竞品"}</button></div></header>
     <DetailOverview data={data} groups={groups} onChangeGroup={onChangeGroup} />
    <section className="detail-trends"><div className="detail-trends-header"><div><h2>趋势数据</h2><span>价格和库存来自每日最终 ProductSnapshot</span></div><div className="range-selector" role="group" aria-label="趋势时间范围" aria-busy={rangeLoading}><button type="button" aria-pressed={days === 7} className={days === 7 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(7)} disabled={rangeLoading}>近 7 天</button><button type="button" aria-pressed={days === 30} className={days === 30 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(30)} disabled={rangeLoading}>近 30 天</button>{rangeLoading && <span className="range-loading-indicator" role="status">更新中…</span>}</div></div><div className="detail-trend-grid"><DetailTrendCard kind="price" title="价格趋势" description="最低价 / 最高价" trend={data.daily_trend} /><DetailTrendCard kind="stock" title="库存趋势" description="全部 SKU 库存总和" trend={data.daily_trend} /><SalesPlaceholderCard /></div></section>
    <div className="detail-lower-grid">
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>SKU 信息</h2><span>{data.latest_snapshot ? `共 ${data.latest_snapshot.sku_count} 个` : "当前快照"}</span></div></div>{data.latest_skus.length === 0 ? <div className="detail-empty">暂无 SKU 数据</div> : <div className="table-scroll detail-table-scroll"><table><thead><tr><th>SKU 规格</th><th>SKU ID</th><th>库存</th><th>SKU 价格</th></tr></thead><tbody>{data.latest_skus.map((sku) => <tr key={sku.sku_id}><td>{sku.sku_name ?? "未命名 SKU"}</td><td>{sku.sku_id}</td><td>{sku.stock === null ? "—" : sku.stock}</td><td>{sku.price === null ? "—" : `¥${sku.price}`}</td></tr>)}</tbody></table></div>}</section>
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>最近变化</h2><span>最近 20 条 · 检测时间</span></div></div>{data.recent_changes.length === 0 ? <div className="detail-empty">暂无变化记录</div> : <div className="detail-record-list">{data.recent_changes.map((change) => <div className="detail-record-row" key={change.id}><strong>{formatChange(change)}</strong><time>{formatDate(change.detected_at)}</time></div>)}</div>}</section>
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>最近采集记录</h2><span>最近 20 条</span></div></div>{data.recent_collection_runs.length === 0 ? <div className="detail-empty">暂无采集记录</div> : <div className="table-scroll detail-table-scroll"><table className="collection-runs-table"><thead><tr><th>开始时间</th><th>结束时间</th><th>状态</th><th>结果</th></tr></thead><tbody>{data.recent_collection_runs.map((run) => <tr key={run.id}><td>{formatDate(run.started_at)}</td><td>{run.finished_at ? formatDate(run.finished_at) : "—"}</td><td>{run.status === "success" ? "成功" : run.status === "failed" ? "失败" : "采集中"}</td><td>{run.status === "failed" ? run.error_message || "采集失败" : run.status === "success" ? "成功" : "—"}</td></tr>)}</tbody></table></div>}</section>
    </div>
  </AppShell>;
}

type AddDialogProps = { url: string; status: AddStatus; onUrlChange: (url: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onClose: () => void; groups: CompetitorGroup[]; groupId: number | null; onGroupChange: (groupId: number | null) => void; newGroupName: string; onNewGroupNameChange: (name: string) => void; onCreateGroup: () => void; groupCreateStatus: GroupCreateStatus; failures?: AddFailure[]; succeededCount?: number; progress?: { completed: number; total: number } };

export function AddDialog({ url, status, onUrlChange, onSubmit, onClose, groups, groupId, onGroupChange, newGroupName, onNewGroupNameChange, onCreateGroup, groupCreateStatus, failures = [], succeededCount = 0, progress = { completed: 0, total: 0 } }: AddDialogProps) {
  const busy = status === "submitting";
  const urlCount = parseCompetitorUrls(url).length;
  const [clipboardFeedback, setClipboardFeedback] = useState<{ kind: "success" | "info" | "error"; message: string } | null>(null);

  async function handleClipboardAdd() {
    if (busy) return;
    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.readText) {
        setClipboardFeedback({ kind: "error", message: "当前浏览器无法读取剪贴板，请检查剪贴板权限" });
        return;
      }
      const clipboardValue = await navigator.clipboard.readText();
      const clipboardUrls = parseCompetitorUrls(clipboardValue);
      if (clipboardUrls.length === 0) {
        setClipboardFeedback({ kind: "info", message: "剪贴板中没有可添加的内容" });
        return;
      }
      const currentCount = parseCompetitorUrls(url).length;
      const nextValue = mergeCompetitorUrlText(url, clipboardValue);
      const addedCount = parseCompetitorUrls(nextValue).length - currentCount;
      if (addedCount <= 0) {
        setClipboardFeedback({ kind: "info", message: "剪贴板中的链接已存在" });
        return;
      }
      onUrlChange(nextValue);
      setClipboardFeedback({ kind: "success", message: `已从剪贴板添加 ${addedCount} 条链接` });
    } catch {
      setClipboardFeedback({ kind: "error", message: "无法读取剪贴板，请检查浏览器剪贴板权限" });
    }
  }

  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="dialog-title">添加监控商品</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={busy}>×</button></div>
    <p className="dialog-description">添加 1688 商品链接，系统会先确认真实店铺，再自动分流到我方商品或竞品列表。</p>
    <form onSubmit={onSubmit}><div className="dialog-field-header"><label htmlFor="competitor-url">1688 商品链接</label><button type="button" className="text-button clipboard-add-button" onClick={() => void handleClipboardAdd()} disabled={busy}>从剪贴板添加</button></div><textarea id="competitor-url" rows={5} value={url} onChange={(event) => { setClipboardFeedback(null); onUrlChange(event.target.value); }} placeholder={"https://detail.1688.com/offer/123456789.html\nhttps://detail.1688.com/offer/987654321.html"} autoComplete="off" spellCheck={false} autoCapitalize="none" autoCorrect="off" disabled={busy} /><p className="hint">每行一个链接，支持一次添加多个监控商品；仅支持 detail.1688.com/offer/{"{offerId}"}.html</p>{clipboardFeedback && <p className={"clipboard-feedback clipboard-feedback-" + clipboardFeedback.kind} role="status" aria-live="polite">{clipboardFeedback.message}</p>}<label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={groupId === null ? "" : String(groupId)} onChange={(event) => onGroupChange(event.target.value ? Number(event.target.value) : null)} disabled={busy}><option value="">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select><label htmlFor="new-competitor-group">新增竞品组</label><div className="group-create-controls"><input id="new-competitor-group" type="text" value={newGroupName} onChange={(event) => onNewGroupNameChange(event.target.value)} placeholder="输入商品型号作为组名，例如 A19" maxLength={64} disabled={busy} /><button type="button" className="secondary-button" onClick={onCreateGroup} disabled={busy || groupCreateStatus === "submitting"}>{groupCreateStatus === "submitting" ? "创建中…" : "创建"}</button></div><div className={getGroupFeedbackClass(groupCreateStatus)} role="status" aria-live="polite">{groupCreateStatus === "success" && "竞品组已创建并已选中。"}{groupCreateStatus === "invalid" && "请输入有效的竞品组名称"}{groupCreateStatus === "duplicate" && "该竞品组已存在"}{groupCreateStatus === "server-error" && "竞品组创建失败，请稍后重试。"}</div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>取消</button><button type="submit" className="primary-button" disabled={busy || urlCount === 0}>{busy ? (progress.total ? `正在添加 ${progress.completed} / ${progress.total}…` : "正在添加…") : urlCount > 1 ? `添加 ${urlCount} 个监控商品` : "添加监控商品"}</button></div></form>
    <div className={"feedback feedback-" + status} role="status" aria-live="polite">{status === "partial" && `已添加 ${succeededCount} 个，${failures.length} 个未添加`}{status === "failed" && `未添加 ${failures.length} 个监控商品`}{status === "invalid" && "链接无效：请输入指定格式的 1688 商品链接。"}{status === "duplicate" && "该 1688 商品已经添加。"}{status === "server-error" && "服务暂时不可用，请稍后重试。"}</div>
    {failures.length > 0 && <div className="add-failures" role="status" aria-live="polite"><strong>未添加：</strong><ul>{failures.map((failure) => <li key={failure.url}>{failure.url} — {failure.reason}</li>)}</ul></div>}
  </section></div>;
}

type WorkspacePlaceholderPageProps = {
  page: Page;
  title: string;
  description: string;
  note: string;
  icon: NavIconName;
  onNavigate: (page: Page) => void;
};

export function WorkspacePlaceholderPage({ page, title, description, note, icon, onNavigate }: WorkspacePlaceholderPageProps) {
  return <AppShell page={page} onNavigate={onNavigate} breadcrumb={title}>
    <header className="page-header"><div><h1>{title}</h1><p className="page-description">{description}</p></div></header>
    <section className="table-card module-placeholder-card">
      <div className="module-placeholder-icon"><NavIcon name={icon} /></div>
      <span className="module-placeholder-badge">规划中</span>
      <strong>{title}模块已预留</strong>
      <p>{note}</p>
    </section>
  </AppShell>;
}

export function HomePage({ onNavigate }: { onNavigate: (page: Page) => void }) {
  return <WorkspacePlaceholderPage page="home" title="首页" description="个人工作台总览与快捷入口。" note="后续将在这里汇总竞品监控、全网比价、自动询价和自动上架等模块的关键状态与快捷入口。" icon="home" onNavigate={onNavigate} />;
}

type PaginationBarProps = {
  total: number;
  itemLabel: string;
  page: number;
  totalPages: number;
  onPrevious: () => void;
  onNext: () => void;
  previousDisabled: boolean;
  nextDisabled: boolean;
};

export function PaginationBar({ total, itemLabel, page, totalPages, onPrevious, onNext, previousDisabled, nextDisabled }: PaginationBarProps) {
  return <div className="pagination-bar"><span>共 {total} {itemLabel}</span><button type="button" disabled={previousDisabled} onClick={onPrevious}>上一页</button><span className="page-number" aria-current="page">{page}</span><button type="button" disabled={nextDisabled} onClick={onNext}>下一页</button><span>第 {page} / {totalPages} 页</span></div>;
}

type CollectionRun = { id: number; competitor_id: number; ownership: "self" | "competitor"; title: string | null; offer_id: string; shop_name: string | null; started_at: string; finished_at: string | null; status: "running" | "success" | "failed"; error_type: string | null; error_message: string | null; duration_seconds: number | null };
type CollectionRunPage = { items: CollectionRun[]; total: number; page: number; page_size: number };
type CollectionTaskProps = { onNavigate: (page: Page) => void; batchState?: BatchState; batchStatus?: ListStatus; batchError?: string | null; onRefreshBatch?: () => Promise<boolean> };

function ProductReference({ competitorId, productById }: { competitorId: number; productById: ReadonlyMap<number, Competitor> }) {
  const product = productById.get(competitorId);
  if (!product) return <div className="collection-task-product collection-task-product-missing"><strong>商品 ID：{competitorId}</strong><span>标题、Offer ID、店铺和身份未采集</span></div>;
  return <div className="collection-task-product"><strong>{product.title || "标题未采集"}</strong><span>Offer ID：{product.offer_id || "未采集"}</span><span>{product.shop_name || "店铺未采集"} · {product.ownership === "self" ? "我方商品" : "直接竞品"}</span></div>;
}

export function CurrentBatchCard({ batchState, status, error, onRetry, productById }: { batchState: BatchState; status: ListStatus; error: string | null; onRetry: () => void; productById: ReadonlyMap<number, Competitor> }) {
  if (status === "loading") return <section className="table-card collection-current-card"><div className="table-heading"><div><h2>当前批量采集</h2></div></div><div className="state-panel"><div className="spinner" /><strong>正在读取当前批量采集状态…</strong></div></section>;
  if (status === "error") return <section className="table-card collection-current-card"><div className="table-heading"><div><h2>当前批量采集</h2></div></div><div className="state-panel state-error"><strong>状态刷新失败</strong><span>{error || "暂时无法读取批量采集状态。"}</span><button type="button" className="secondary-button" onClick={onRetry}>重试</button></div></section>;
  if (batchState.status === "idle") return <section className="table-card collection-current-card"><div className="table-heading"><div><h2>当前批量采集</h2></div></div><div className="collection-batch-idle"><strong>当前无批量采集任务</strong><span>可在竞品监控大屏点击「立即采集」发起批量采集。</span></div></section>;
  const currentProduct = batchState.current_competitor_id === null ? null : <ProductReference competitorId={batchState.current_competitor_id} productById={productById} />;
  const progress = batchState.total ? Math.min(100, (batchState.completed / batchState.total) * 100) : 0;
  const title = batchState.status === "running" ? "采集中" : batchState.status === "resting" ? `计划内主动休息 · 剩余 ${formatBatchCooldown(batchState.resting_remaining_seconds)} · 已完成 ${batchState.completed} · 剩余 ${batchState.remaining}` : batchState.status === "cooling_down" ? "1688 验证已触发" : batchState.status === "verification_required" ? "需要人工完成 1688 验证" : "最近批次完成";
  return <section className={`table-card collection-current-card collection-batch-${batchState.status}`}><div className="table-heading"><div><h2>当前批量采集</h2></div><span className={`collection-batch-status collection-batch-status-${batchState.status}`}>{title}</span></div><div className="collection-batch-summary"><div><strong>{batchState.completed} / {batchState.total}</strong><span>已完成 / 总数</span></div><div><strong>{batchState.succeeded}</strong><span>成功</span></div><div><strong>{batchState.failed}</strong><span>失败</span></div><div><strong>{batchState.remaining}</strong><span>剩余</span></div></div>{(batchState.status === "running" || batchState.status === "cooling_down" || batchState.status === "verification_required") && <div className="collection-progress" aria-label={`批量采集进度 ${batchState.completed} / ${batchState.total}`}><i style={{ width: `${progress}%` }} /></div>}{batchState.status === "cooling_down" && <div className="collection-batch-notice"><strong>浏览器已关闭，等待冷却后自动恢复。</strong><span>冷却剩余：{formatBatchCooldown(batchState.cooldown_remaining_seconds)} · 自动恢复 {batchState.auto_resume_attempt} / {batchState.auto_resume_max}</span></div>}{batchState.status === "verification_required" && <div className="collection-batch-notice"><strong>请在已打开的浏览器中完成 1688 验证。</strong><span>浏览器：{batchState.browser_open ? "已打开" : "未打开"} · 采集器：{batchState.runner_active ? "运行中" : "未运行"}</span></div>}{batchState.status === "completed" && <div className="collection-batch-notice"><strong>结果码：{batchState.outcome_code || "未提供"}</strong><span>需要验证：{batchState.verification_required}</span></div>}{currentProduct && <div className="collection-current-product"><span>当前商品</span>{currentProduct}</div>}{batchState.items.length > 0 && <div className="collection-batch-items"><strong>已完成项目</strong><ul>{batchState.items.map((item) => <li key={`${item.competitor_id}-${item.status}`}><ProductReference competitorId={item.competitor_id} productById={productById} /><span className={`collection-task-run-status collection-task-run-status-${item.status}`}>{item.status === "success" ? `采集成功${item.outcome === "active" ? " · 在售" : item.outcome === "offline" ? " · 已下架" : ""}` : item.status === "failed" ? "失败" : "需要验证"}</span>{item.status !== "success" && <>{item.message && <small>{item.message}</small>}{item.error_code && <small>{item.error_code}</small>}</>}</li>)}</ul></div>}</section>;
}

export function CollectionTasksPage({ onNavigate, batchState = idleBatchState, batchStatus = "ready", batchError = null, onRefreshBatch = async () => true }: CollectionTaskProps) {
  const [products, setProducts] = useState<Competitor[]>([]); const [historyStatus, setHistoryStatus] = useState<ListStatus>("loading"); const [historyError, setHistoryError] = useState<string | null>(null); const [history, setHistory] = useState<CollectionRunPage | null>(null); const [searchDraft, setSearchDraft] = useState(""); const [search, setSearch] = useState(""); const [runStatus, setRunStatus] = useState<"all" | "success" | "failed">("all"); const [ownership, setOwnership] = useState<"all" | "self" | "competitor">("all"); const [page, setPage] = useState(1); const latestHistoryRequest = useRef(0);
  const refreshBatchRef = useRef(onRefreshBatch);
  refreshBatchRef.current = onRefreshBatch;
  const productById = useMemo(() => new Map(products.map((product) => [product.id, product])), [products]);
  const refreshBatch = useCallback(() => refreshBatchRef.current(), []);
  const loadHistory = useCallback(async () => { const requestId = ++latestHistoryRequest.current; setHistoryStatus("loading"); setHistoryError(null); const params = new URLSearchParams({ status: runStatus, ownership, page: String(page) }); if (search.trim()) params.set("search", search.trim()); try { const response = await fetch(`/api/collection-runs?${params.toString()}`); if (!response.ok) throw new Error("request failed"); const data = await response.json() as CollectionRunPage; if (requestId !== latestHistoryRequest.current) return; setHistory(data); setHistoryStatus("ready"); } catch { if (requestId !== latestHistoryRequest.current) return; setHistoryError("暂时无法获取采集记录，请检查服务是否正常运行。"); setHistoryStatus("error"); } }, [ownership, page, runStatus, search]);
  useEffect(() => { void refreshBatch(); }, [refreshBatch]); useEffect(() => { void loadHistory(); }, [loadHistory]); useEffect(() => { void fetch("/api/competitors").then((response) => response.ok ? response.json() as Promise<Competitor[]> : []).then(setProducts).catch(() => setProducts([])); }, []);
  const totalPages = history ? Math.max(1, Math.ceil(history.total / history.page_size)) : 1;
  const updateFilters = (nextStatus: "all" | "success" | "failed", nextOwnership: "all" | "self" | "competitor") => { setPage(1); setRunStatus(nextStatus); setOwnership(nextOwnership); };
  return <AppShell page="collection-tasks" onNavigate={onNavigate} breadcrumb="采集任务"><header className="page-header"><div><h1>采集任务</h1><p className="page-description">查看当前采集进度、历史记录与失败原因。</p></div></header><CurrentBatchCard batchState={batchState} status={batchStatus} error={batchError} onRetry={() => void refreshBatch()} productById={productById} /><section className="table-card collection-history-card"><div className="table-heading"><div><h2>采集记录</h2><span>查看每次商品采集结果与失败原因</span></div></div><form className="collection-history-filters" onSubmit={(event) => { event.preventDefault(); setPage(1); setSearch(searchDraft); }}><input aria-label="搜索采集记录" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="搜索标题、Offer ID 或店铺" /><button type="submit" className="secondary-button">搜索</button><select aria-label="采集记录状态" value={runStatus} onChange={(event) => updateFilters(event.target.value as typeof runStatus, ownership)}><option value="all">全部状态</option><option value="success">成功</option><option value="failed">失败</option></select><select aria-label="采集记录身份" value={ownership} onChange={(event) => updateFilters(runStatus, event.target.value as typeof ownership)}><option value="all">全部身份</option><option value="self">我方商品</option><option value="competitor">直接竞品</option></select></form>{historyStatus === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载采集记录…</strong></div>}{historyStatus === "error" && <div className="state-panel state-error"><strong>采集记录加载失败</strong><span>{historyError}</span><button type="button" className="secondary-button" onClick={() => void loadHistory()}>重试</button></div>}{historyStatus === "ready" && history && (<>{history.items.length === 0 ? <div className="detail-empty">{history.total === 0 ? "暂无采集记录" : "当前页无记录"}</div> : <div className="table-scroll"><table className="collection-runs-table"><thead><tr><th>状态</th><th>商品</th><th>当前身份</th><th>开始时间</th><th>耗时</th><th>结果</th></tr></thead><tbody>{history.items.map((run) => <tr key={run.id}><td><span className={`collection-task-run-status collection-task-run-status-${run.status}`}>{run.status === "success" ? "成功" : run.status === "failed" ? "失败" : "未完成"}</span></td><td><strong>{run.title || "标题未采集"}</strong><small>Offer ID：{run.offer_id} · {run.shop_name || "店铺未采集"}</small></td><td>{run.ownership === "self" ? "我方商品" : "直接竞品"}</td><td>{formatDate(run.started_at)}</td><td>{formatDuration(run.duration_seconds)}</td><td>{run.status === "failed" ? (run.error_message || run.error_type || "采集失败") : ""}</td></tr>)}</tbody></table></div>}<PaginationBar total={history.total} itemLabel="条" page={history.page} totalPages={totalPages} onPrevious={() => setPage(history.page - 1)} onNext={() => setPage(history.page + 1)} previousDisabled={history.page <= 1} nextDisabled={history.page >= totalPages} /></>)}</section></AppShell>;
}

type SettingsPageProps = {
  configured: boolean;
  value: string;
  status: ListStatus;
  error: string | null;
  saveError: string | null;
  submitting: boolean;
  onChange: (value: string) => void;
  onRetry: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onNavigate: (page: Page) => void;
  monitoring: CompetitorMonitoringSettings | null;
  monitoringStatus: ListStatus;
  monitoringError: string | null;
  monitoringSaveError: string | null;
  monitoringSubmitting: boolean;
  onMonitoringChange: (value: CompetitorMonitoringSettings) => void;
  onMonitoringOpen: () => void;
  onMonitoringRetry: () => void;
  onMonitoringSave: (event: FormEvent<HTMLFormElement>) => void;
};

type CompetitorMonitoringSettings = { item_interval_seconds: number; continuous_collection_count: number; batch_rest_seconds: number; verification_cooldown_seconds: number; auto_resume_max: number };

export function SettingsPage({ configured, value, status, error, saveError, submitting, onChange, onRetry, onSave, onNavigate, monitoring, monitoringStatus, monitoringError, monitoringSaveError, monitoringSubmitting, onMonitoringChange, onMonitoringOpen, onMonitoringRetry, onMonitoringSave }: SettingsPageProps) {
  const [module, setModule] = useState<"basic" | "monitoring">("basic");
  const setNumber = (key: keyof CompetitorMonitoringSettings, value: string) => { if (monitoring) onMonitoringChange({ ...monitoring, [key]: Number(value) }); };
  const monitoringRows: { key: keyof CompetitorMonitoringSettings; title: string; description: string; unit: string; recommended: string; range: string; value: number }[] = monitoring ? [
    { key: "item_interval_seconds", title: "单商品采集间隔", description: "每采集完一个商品后的等待时间", unit: "秒", recommended: "推荐 5 秒", range: "1～60 秒", value: monitoring.item_interval_seconds },
    { key: "continuous_collection_count", title: "连续采集数量", description: "连续访问指定数量后进入主动休息", unit: "个", recommended: "推荐 10 个", range: "1～50 个", value: monitoring.continuous_collection_count },
    { key: "batch_rest_seconds", title: "批次休息时间", description: "完成一组连续采集后暂停一段时间", unit: "分钟", recommended: "推荐 2 分钟", range: "0～30 分钟，0 表示关闭主动休息", value: monitoring.batch_rest_seconds / 60 },
    { key: "verification_cooldown_seconds", title: "风控冷却时间", description: "触发 1688 验证后等待多久再自动恢复", unit: "分钟", recommended: "推荐 10 分钟", range: "1～60 分钟", value: monitoring.verification_cooldown_seconds / 60 },
    { key: "auto_resume_max", title: "自动恢复次数", description: "触发验证后最多自动恢复的次数", unit: "次", recommended: "推荐 2 次", range: "0～5 次，0 表示直接进入人工处理", value: monitoring.auto_resume_max },
  ] : [];
  const field = (row: typeof monitoringRows[number]) => <label className="monitoring-setting-row" key={row.key}><span className="monitoring-setting-copy"><strong>{row.title}</strong><small>{row.description}</small></span><span className="monitoring-setting-input"><input aria-label={row.title} type="number" min={row.key === "batch_rest_seconds" || row.key === "auto_resume_max" ? 0 : 1} max={row.key === "item_interval_seconds" ? 60 : row.key === "continuous_collection_count" ? 50 : row.key === "batch_rest_seconds" ? 30 : row.key === "verification_cooldown_seconds" ? 60 : 5} step={1} value={row.value} disabled={monitoringSubmitting} onChange={(event) => setNumber(row.key, row.key === "batch_rest_seconds" || row.key === "verification_cooldown_seconds" ? String(Number(event.target.value) * 60) : event.target.value)} /><b>{row.unit}</b></span><span className="monitoring-setting-meta"><em>{row.recommended}</em><small>{row.range}</small></span></label>;
  return <AppShell page="settings" onNavigate={onNavigate} breadcrumb="系统设置">
    <header className="page-header"><div><h1>系统设置</h1><p className="page-description">按业务模块管理基础信息与竞品采集节奏。</p></div></header>
    <div className="settings-layout"><nav aria-label="设置模块" className="settings-nav"><button type="button" className={module === "basic" ? "settings-module-active" : "settings-module"} onClick={() => setModule("basic")}><strong>基础设置</strong><span>我方店铺、基础信息</span></button><button type="button" className={module === "monitoring" ? "settings-module-active" : "settings-module"} onClick={() => { setModule("monitoring"); onMonitoringOpen(); }}><strong>竞品监控</strong><span>采集节奏、风控处理</span></button></nav>
    {module === "basic" && <section className="table-card settings-card"><div className="table-heading"><div><h2>我方店铺</h2><span>仅支持精确店铺名称匹配（首尾空白和连续空白会标准化）。</span></div></div>
      {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载系统设置…</strong></div>}
      {status === "error" && <div className="state-panel state-error"><strong>设置加载失败</strong><span>{error || "暂时无法读取系统设置。"}</span><button type="button" className="secondary-button" onClick={onRetry}>重试</button></div>}
      {status === "ready" && <form className="settings-form" onSubmit={onSave}><label htmlFor="own-shop-name">我方店铺名称</label><input id="own-shop-name" value={value} onChange={(event) => onChange(event.target.value)} maxLength={255} disabled={submitting} placeholder="请输入 1688 店铺名称" />{!configured && <p className="hint">尚未配置。配置后才能从大屏添加监控商品。</p>}{saveError && <div className="feedback feedback-server-error" role="alert">{saveError}</div>}<div className="dialog-actions"><button type="submit" className="primary-button" disabled={submitting || !value.trim()}>{submitting ? "保存中…" : "保存设置"}</button><button type="button" className="secondary-button" onClick={() => onNavigate("dashboard")} disabled={submitting}>返回大屏</button></div></form>}
    </section>}
    {module === "monitoring" && <section className="table-card settings-card settings-monitoring-card"><div className="settings-monitoring-heading"><h2>竞品监控设置</h2><p>配置采集节奏与风控恢复策略，降低长时间连续访问造成的压力。</p><span>设置仅影响下一次新启动的批量采集，当前运行任务不变。</span></div>{monitoringStatus === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载竞品监控设置…</strong></div>}{monitoringStatus === "error" && <div className="state-panel state-error"><strong>竞品监控设置加载失败</strong><span>{monitoringError || "暂时无法读取竞品监控设置。"}</span><button type="button" className="secondary-button" onClick={onMonitoringRetry}>重试</button></div>}{monitoringStatus === "ready" && monitoring && <form className="monitoring-settings-form" onSubmit={onMonitoringSave}><section className="monitoring-setting-group"><header><h3>采集节奏</h3><span>控制每次访问之间的节奏与计划内休息。</span></header>{monitoringRows.slice(0, 3).map(field)}</section><section className="monitoring-setting-group"><header><h3>风控处理</h3><span>触发验证后，按当前设置等待并尝试恢复。</span></header>{monitoringRows.slice(3).map(field)}</section>{monitoringSaveError && <div className="feedback feedback-server-error" role="alert">{monitoringSaveError}</div>}<div className="settings-save-bar"><button type="submit" className="primary-button" disabled={monitoringSubmitting}>{monitoringSubmitting ? "保存中…" : "保存设置"}</button></div></form>}</section>}</div>
  </AppShell>;
}

function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [ownProducts, setOwnProducts] = useState<Competitor[]>([]);
  const [groups, setGroups] = useState<CompetitorGroup[]>([]);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashboardStatus, setDashboardStatus] = useState<DashboardStatus>("loading");
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [dashboardAttention, setDashboardAttention] = useState<GroupAttentionData | null>(null);
  const [dashboardAttentionStatus, setDashboardAttentionStatus] = useState<DashboardStatus>("loading");
  const [dashboardAttentionError, setDashboardAttentionError] = useState<string | null>(null);
  const [listStatus, setListStatus] = useState<ListStatus>("ready");
  const [listError, setListError] = useState<string | null>(null);
  const [listLoaded, setListLoaded] = useState(false);
  const [ownListStatus, setOwnListStatus] = useState<ListStatus>("ready");
  const [ownListError, setOwnListError] = useState<string | null>(null);
  const [ownListLoaded, setOwnListLoaded] = useState(false);
  const [ownShopName, setOwnShopName] = useState<string | null>(null);
  const [settingsValue, setSettingsValue] = useState("");
  const [settingsConfigured, setSettingsConfigured] = useState(false);
  const [settingsStatus, setSettingsStatus] = useState<ListStatus>("loading");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSaveError, setSettingsSaveError] = useState<string | null>(null);
  const [settingsSubmitting, setSettingsSubmitting] = useState(false);
  const [monitoringSettings, setMonitoringSettings] = useState<CompetitorMonitoringSettings | null>(null);
  const [monitoringStatus, setMonitoringStatus] = useState<ListStatus>("loading");
  const [monitoringError, setMonitoringError] = useState<string | null>(null);
  const [monitoringSaveError, setMonitoringSaveError] = useState<string | null>(null);
  const [monitoringSubmitting, setMonitoringSubmitting] = useState(false);
  const [groupSummary, setGroupSummary] = useState<CompetitorGroupsSummary | null>(null);
  const [groupStatus, setGroupStatus] = useState<GroupStatus>("loading");
  const [groupError, setGroupError] = useState<string | null>(null);
  const [groupLoaded, setGroupLoaded] = useState(false);
  const [listNavigationIntent, setListNavigationIntent] = useState<ListNavigationIntent>({ filter: null, version: 0 });
  const [detailStatus, setDetailStatus] = useState<DetailStatus>("loading");
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CompetitorDetail | null>(null);
  const [detailDays, setDetailDays] = useState<7 | 30>(7);
  const [detailRangeLoading, setDetailRangeLoading] = useState(false);
  const [selectedCompetitorId, setSelectedCompetitorId] = useState<number | null>(null);
  const latestDetailRequestId = useRef(0);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [groupDetail, setGroupDetail] = useState<GroupDetailData | null>(null);
  const [groupDetailStatus, setGroupDetailStatus] = useState<DetailStatus>("loading");
  const [groupDetailError, setGroupDetailError] = useState<string | null>(null);
  const [groupDetailRangeError, setGroupDetailRangeError] = useState<string | null>(null);
  const [groupDetailDays, setGroupDetailDays] = useState<7 | 30>(7);
  const [groupDetailRangeLoading, setGroupDetailRangeLoading] = useState(false);
  const latestGroupDetailRequestId = useRef(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [newGroupName, setNewGroupName] = useState("");
  const [groupCreateStatus, setGroupCreateStatus] = useState<GroupCreateStatus>("initial");
  const [addStatus, setAddStatus] = useState<AddStatus>("initial");
  const [addFailures, setAddFailures] = useState<AddFailure[]>([]);
  const [addSucceededCount, setAddSucceededCount] = useState(0);
  const [addProgress, setAddProgress] = useState({ completed: 0, total: 0 });
  const [notice, setNotice] = useState<Notice | null>(null);
  const [batchState, setBatchState] = useState<BatchState>(idleBatchState);
  const [batchStatus, setBatchStatus] = useState<ListStatus>("loading");
  const [batchError, setBatchError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [batchGroupDialog, setBatchGroupDialog] = useState<{ competitorIds: number[]; selectedCount: number; ownCount: number } | null>(null);
  const [batchGroupTarget, setBatchGroupTarget] = useState<number | null | undefined>(undefined);
  const [batchGroupSubmitting, setBatchGroupSubmitting] = useState(false);
  const [batchGroupError, setBatchGroupError] = useState<string | null>(null);
  const [batchLifecycleDialog, setBatchLifecycleDialog] = useState<{ action: "stop" | "delete"; competitorIds: number[]; selectedCount: number; ownCount: number } | null>(null);
  const [batchLifecycleSubmitting, setBatchLifecycleSubmitting] = useState(false);
  const [batchLifecycleError, setBatchLifecycleError] = useState<string | null>(null);
  const batchLifecycleSubmittingRef = useRef(false);
  const [paginationResetVersion, setPaginationResetVersion] = useState(0);
  const batchStateRef = useRef(batchState);
  const reconcileSelection = useCallback((visibleIds: number[]) => {
    setSelectedIds((current) => {
      const next = reconcileSelectedIds(current, visibleIds);
      return next.size === current.size ? current : next;
    });
  }, []);
  const [lifecycleDialog, setLifecycleDialog] = useState<{ action: "stop" | "delete"; competitor: LifecycleCompetitor } | null>(null);
  const [lifecycleSubmitting, setLifecycleSubmitting] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [groupNameDialog, setGroupNameDialog] = useState<{ mode: "create" | "rename"; group?: CompetitorGroupSummary } | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupNameSubmitting, setGroupNameSubmitting] = useState(false);
  const [groupNameError, setGroupNameError] = useState<string | null>(null);
  const [groupDeleteDialog, setGroupDeleteDialog] = useState<CompetitorGroupSummary | null>(null);
  const [groupDeleteSubmitting, setGroupDeleteSubmitting] = useState(false);
  const [groupDeleteError, setGroupDeleteError] = useState<string | null>(null);
  const [groupAssignmentDialog, setGroupAssignmentDialog] = useState<{ competitorId: number; groupId: number | null; ownership: "self" | "competitor"; fromDetail: boolean } | null>(null);
  const [groupAssignmentSubmitting, setGroupAssignmentSubmitting] = useState(false);
  const [groupAssignmentError, setGroupAssignmentError] = useState<string | null>(null);
  const [ownProductDialog, setOwnProductDialog] = useState<{ group: CompetitorGroupSummary; mode: OwnProductAction } | null>(null);
  const [ownProductSelectedId, setOwnProductSelectedId] = useState<number | null>(null);
  const [ownProductConfirming, setOwnProductConfirming] = useState(false);
  const [ownProductSubmitting, setOwnProductSubmitting] = useState(false);
  const [ownProductLoading, setOwnProductLoading] = useState(false);
  const [ownProductError, setOwnProductError] = useState<string | null>(null);
  const ownProductSubmittingRef = useRef(false);
  const currentProducts = page === "own-products" ? ownProducts : competitors;

  async function loadCompetitors(): Promise<boolean> {
    setListStatus("loading"); setListError(null);
    try { const [competitorsResponse, groupsResponse] = await Promise.all([fetch("/api/competitors?ownership=competitor"), fetch("/api/competitor-groups")]); if (!competitorsResponse.ok || !groupsResponse.ok) throw new Error("request failed"); const [competitorData, groupData] = await Promise.all([competitorsResponse.json(), groupsResponse.json()]); const nextCompetitors = competitorData as Competitor[]; setCompetitors(nextCompetitors); setSelectedIds((current) => new Set([...current].filter((id) => nextCompetitors.some((item) => item.id === id)))); setGroups(groupData as CompetitorGroup[]); setListStatus("ready"); setListLoaded(true); return true; }
    catch { setListError("暂时无法获取竞品列表，请检查服务是否正常运行。"); setListStatus("error"); return false; }
  }
  async function loadOwnProducts(): Promise<boolean> {
    setOwnListStatus("loading"); setOwnListError(null);
    try {
      const [response, groupsResponse] = await Promise.all([fetch("/api/competitors?ownership=self"), fetch("/api/competitor-groups")]);
      if (!response.ok || !groupsResponse.ok) throw new Error("request failed");
      const [next, groupData] = await Promise.all([response.json() as Promise<Competitor[]>, groupsResponse.json() as Promise<CompetitorGroup[]>]);
      setOwnProducts(next); setGroups(groupData); setOwnListStatus("ready"); setOwnListLoaded(true); return true;
    } catch { setOwnListError("暂时无法获取我方商品，请检查服务是否正常运行。"); setOwnListStatus("error"); return false; }
  }
  async function loadCurrentProducts(): Promise<boolean> {
    return page === "own-products" ? loadOwnProducts() : loadCompetitors();
  }
  async function loadOwnShopName(): Promise<boolean> {
    setSettingsStatus("loading"); setSettingsError(null);
    try {
      const response = await fetch("/api/settings/own-shop-name");
      if (!response.ok) throw new Error("request failed");
      const body = await response.json() as { configured: boolean; own_shop_name: string | null };
      setSettingsConfigured(body.configured); setOwnShopName(body.own_shop_name); setSettingsValue(body.own_shop_name || ""); setSettingsStatus("ready"); return true;
    } catch { setSettingsError("暂时无法获取系统设置，请检查服务是否正常运行。"); setSettingsStatus("error"); return false; }
  }
  async function loadMonitoringSettings(): Promise<boolean> {
    setMonitoringStatus("loading"); setMonitoringError(null);
    try {
      const response = await fetch("/api/settings/competitor-monitoring");
      if (!response.ok) throw new Error("request failed");
      setMonitoringSettings(await response.json() as CompetitorMonitoringSettings); setMonitoringStatus("ready"); return true;
    } catch { setMonitoringError("暂时无法获取竞品监控设置，请检查服务是否正常运行。"); setMonitoringStatus("error"); return false; }
  }
  async function loadDashboardAttention(): Promise<boolean> {
    setDashboardAttentionStatus("loading"); setDashboardAttentionError(null);
    try {
      const response = await fetch("/api/dashboard/group-attention");
      if (!response.ok) throw new Error("request failed");
      setDashboardAttention(await response.json() as GroupAttentionData);
      setDashboardAttentionStatus("ready");
      return true;
    } catch {
      setDashboardAttentionError("暂时无法获取商品组关注信息。"); setDashboardAttentionStatus("error");
      return false;
    }
  }
  async function loadDashboard(): Promise<boolean> {
    setDashboardStatus("loading"); setDashboardError(null);
    const attentionRequest = loadDashboardAttention();
    let dashboardLoaded = false;
    try {
      const response = await fetch("/api/dashboard/today");
      if (!response.ok) throw new Error("request failed");
      setDashboard(await response.json() as DashboardData); setDashboardStatus("ready");
      dashboardLoaded = true;
    } catch { setDashboardError("暂时无法获取今日变化，请检查服务是否正常运行。"); setDashboardStatus("error"); }
    const attentionLoaded = await attentionRequest;
    return dashboardLoaded && attentionLoaded;
  }
  async function loadGroups(): Promise<boolean> {
    setGroupStatus("loading"); setGroupError(null);
    try {
      const [summaryResponse, groupsResponse] = await Promise.all([fetch("/api/competitor-groups/summary"), fetch("/api/competitor-groups")]);
      if (!summaryResponse.ok || !groupsResponse.ok) throw new Error("request failed");
      const [summaryData, groupData] = await Promise.all([summaryResponse.json(), groupsResponse.json()]);
      setGroupSummary(summaryData as CompetitorGroupsSummary);
      setGroups(groupData as CompetitorGroup[]);
      setGroupStatus("ready"); setGroupLoaded(true);
      return true;
    } catch {
      setGroupError("暂时无法获取竞品组，请检查服务是否正常运行。"); setGroupStatus("error"); setGroupLoaded(false);
      return false;
    }
  }
  async function loadDetail(competitorId: number, days: 7 | 30, preserveContent = false): Promise<boolean> {
    const requestId = ++latestDetailRequestId.current;
    if (!preserveContent) { setDetailStatus("loading"); setDetailError(null); }
    try {
      const response = await fetch(`/api/competitors/${competitorId}/detail?days=${days}`);
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        throw new Error(getCollectionErrorMessage(body.code, body.message));
      }
      const data = await response.json() as CompetitorDetail;
      if (!isCurrentDetailRequest(requestId, latestDetailRequestId.current)) return false;
      setDetail(data); setDetailError(null); setDetailStatus("ready");
      return true;
    } catch (error) {
      if (!isCurrentDetailRequest(requestId, latestDetailRequestId.current)) return false;
      const message = error instanceof Error ? error.message : "暂时无法获取竞品详情，请稍后重试。";
      if (preserveContent) {
        setNotice({ message, type: "error" });
        return false;
      }
      setDetailError(message); setDetailStatus("error");
      return false;
    }
  }
  async function loadBatchStatus(notifyOnError = false) {
    try {
      const response = await fetch("/api/competitors/collect-batch/status");
      if (!response.ok) throw new Error("request failed");
      const next = await response.json() as BatchState;
      const previous = batchStateRef.current;
      batchStateRef.current = next;
      setBatchState(next);
      setBatchStatus("ready");
      setBatchError(null);
      const wasActiveBatch = previous.status === "running" || previous.status === "resting" || previous.status === "cooling_down";
      if (next.status === "completed" && wasActiveBatch) {
        const refreshSucceeded = (await Promise.all([loadCurrentProducts(), loadDashboard()])).every(Boolean);
        setNotice(refreshSucceeded
          ? { message: `采集完成：成功 ${next.succeeded}，失败 ${next.failed}`, type: next.failed ? "error" : "success" }
          : { message: batchRefreshFailureMessage, type: "error" });
      }
      return true;
    } catch {
      setBatchStatus("error");
      setBatchError("暂时无法读取批量采集状态，请检查服务是否正常运行。");
      if (notifyOnError) setNotice({ message: "无法读取批量采集状态，请稍后重试。", type: "error" });
      return false;
    }
  }
  useEffect(() => { void loadDashboard(); void loadOwnShopName(); }, []);
  useEffect(() => { void loadBatchStatus(); }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (batchState.status !== "running" && batchState.status !== "resting" && batchState.status !== "cooling_down" && !(batchState.status === "verification_required" && batchState.browser_open)) return;
    const timer = window.setInterval(() => { void loadBatchStatus(); }, 1500);
    return () => window.clearInterval(timer);
  }, [batchState.status, batchState.browser_open]);
  function navigate(nextPage: Page, initialGroupFilter: InitialGroupFilter = null) {
    if (nextPage !== "detail") { latestDetailRequestId.current += 1; setDetailRangeLoading(false); }
    if (nextPage !== "group-detail") { latestGroupDetailRequestId.current += 1; setGroupDetailRangeLoading(false); }
    setListNavigationIntent((current) => ({ filter: nextPage === "competitors" ? initialGroupFilter : null, version: current.version + 1 }));
    setPage(nextPage);
    if (nextPage === "dashboard") void loadDashboard();
    if (nextPage === "competitors" && !listLoaded) void loadCompetitors();
    if (nextPage === "own-products" && !ownListLoaded) void loadOwnProducts();
    if (nextPage === "groups" && !groupLoaded) void loadGroups();
    if (nextPage === "settings" && settingsStatus !== "ready") void loadOwnShopName();
  }
  function openDetail(competitorId: number) { setSelectedCompetitorId(competitorId); setDetailDays(7); setDetailRangeLoading(false); setPage("detail"); void loadDetail(competitorId, 7); }
  function openGroupDetail(groupId: number) { latestGroupDetailRequestId.current += 1; setSelectedGroupId(groupId); setGroupDetail(null); setGroupDetailDays(7); setGroupDetailRangeLoading(false); setGroupDetailRangeError(null); setGroupDetailStatus("loading"); setPage("group-detail"); void loadGroupDetail(groupId, 7); }
  async function changeDetailRange(days: 7 | 30) {
    if (selectedCompetitorId === null || days === detailDays || detailRangeLoading) return;
    setDetailRangeLoading(true);
    const updated = await loadDetail(selectedCompetitorId, days, true);
    if (updated) setDetailDays(days);
    setDetailRangeLoading(false);
  }
  function openDialog() { setNotice(null); setUrl(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupId(null); setNewGroupName(""); setGroupCreateStatus("initial"); setDialogOpen(true); }
  function openDashboardAddDialog() {
    if (!ownShopName) { navigate("settings"); return; }
    openDialog();
  }
  function closeDialog() { if (addStatus !== "submitting") { setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupCreateStatus("initial"); } }
  async function submitOwnShopName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (settingsSubmitting || !settingsValue.trim()) return;
    if (settingsConfigured && settingsValue.trim() !== ownShopName) {
      const confirmed = window.confirm("保存后将根据当前商品店铺名称重新识别我方商品与竞品，并可能调整竞品组中的我方基准商品。");
      if (!confirmed) return;
    }
    setSettingsSubmitting(true); setSettingsSaveError(null);
    try {
      const response = await fetch("/api/settings/own-shop-name", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ own_shop_name: settingsValue }) });
      let body: { configured?: boolean; own_shop_name?: string | null; message?: string; code?: string } = {};
      try { body = await response.json() as typeof body; } catch { /* use the stable fallback below */ }
      if (!response.ok) throw new Error(body.message || "我方店铺名称保存失败，请稍后重试");
      setSettingsConfigured(Boolean(body.configured)); setOwnShopName(body.own_shop_name || null); setSettingsValue(body.own_shop_name || "");
      const refreshSucceeded = (await Promise.all([loadOwnShopName(), loadDashboard(), loadGroups(), loadCompetitors(), loadOwnProducts()])).every(Boolean);
      setNotice(getBatchRefreshNotice("我方店铺设置已保存，商品身份已重新识别。", refreshSucceeded));
    } catch (error) { setSettingsSaveError(error instanceof Error ? error.message : "我方店铺名称保存失败，请稍后重试"); }
    finally { setSettingsSubmitting(false); }
  }
  async function submitMonitoringSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (monitoringSubmitting || !monitoringSettings) return;
    setMonitoringSubmitting(true); setMonitoringSaveError(null);
    try {
      const response = await fetch("/api/settings/competitor-monitoring", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(monitoringSettings) });
      const body = await response.json().catch(() => ({})) as CompetitorMonitoringSettings & CollectionErrorBody;
      if (!response.ok) throw new Error(body.message || "竞品监控设置保存失败，请稍后重试");
      setMonitoringSettings(body); setNotice({ message: "竞品监控设置已保存。", type: "success" });
    } catch (error) { setMonitoringSaveError(error instanceof Error ? error.message : "竞品监控设置保存失败，请稍后重试"); }
    finally { setMonitoringSubmitting(false); }
  }
  async function handleCreateGroup() {
    setGroupCreateStatus("submitting");
    try {
      const response = await fetch("/api/competitor-groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newGroupName }) });
      if (response.ok) { const group = await response.json() as CompetitorGroup; setGroups((current) => [...current, group]); setGroupId(group.id); setNewGroupName(""); setGroupCreateStatus("success"); setGroupLoaded(false); return; }
      const body = await response.json() as { code?: string }; setGroupCreateStatus(getGroupCreateStatus(false, body.code));
    } catch { setGroupCreateStatus("server-error"); }
  }
  function openGroupCreateDialog() { setGroupName(""); setGroupNameError(null); setGroupNameDialog({ mode: "create" }); }
  function openGroupRenameDialog(group: CompetitorGroupSummary) { setGroupName(group.name); setGroupNameError(null); setGroupNameDialog({ mode: "rename", group }); }
  function closeGroupNameDialog() { if (!groupNameSubmitting) { setGroupNameDialog(null); setGroupName(""); setGroupNameError(null); } }
  async function submitGroupName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!groupNameDialog || groupNameSubmitting || !groupName.trim()) return;
    setGroupNameSubmitting(true); setGroupNameError(null);
    const isRename = groupNameDialog.mode === "rename";
    const endpoint = isRename ? `/api/competitor-groups/${groupNameDialog.group?.id}` : "/api/competitor-groups";
    try {
      const response = await fetch(endpoint, { method: isRename ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: groupName }) });
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        setGroupNameError(getGroupNameErrorMessage(body.code, body.message));
        return;
      }
      setGroupNameDialog(null); setGroupName("");
      const refreshSucceeded = await loadGroups();
      setNotice(getBatchRefreshNotice(isRename ? "竞品组已重命名。" : "竞品组已创建。", refreshSucceeded));
    } catch {
      setGroupNameError("竞品组操作失败，请稍后重试");
    } finally { setGroupNameSubmitting(false); }
  }
  function openGroupDeleteDialog(group: CompetitorGroupSummary) { setGroupDeleteError(null); setGroupDeleteDialog(group); }
  function closeGroupDeleteDialog() { if (!groupDeleteSubmitting) { setGroupDeleteDialog(null); setGroupDeleteError(null); } }
  async function confirmGroupDelete() {
    if (!groupDeleteDialog || groupDeleteSubmitting) return;
    setGroupDeleteSubmitting(true); setGroupDeleteError(null);
    try {
      const response = await fetch(`/api/competitor-groups/${groupDeleteDialog.id}`, { method: "DELETE" });
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        setGroupDeleteError(getGroupNameErrorMessage(body.code, body.message));
        return;
      }
      setGroupDeleteDialog(null);
      const refreshSucceeded = (await Promise.all([loadGroups(), loadCompetitors(), loadDashboard()])).every(Boolean);
      setNotice(getBatchRefreshNotice("竞品组已删除，竞品已移至未分组。", refreshSucceeded));
    } catch {
      setGroupDeleteError("竞品组删除失败，请稍后重试");
    } finally { setGroupDeleteSubmitting(false); }
  }
  async function changeGroupDetailRange(days: 7 | 30) {
    if (selectedGroupId === null || days === groupDetailDays || groupDetailRangeLoading) return;
    setGroupDetailRangeLoading(true); setGroupDetailRangeError(null);
    const updated = await loadGroupDetail(selectedGroupId, days, true);
    if (updated) setGroupDetailDays(days);
    setGroupDetailRangeLoading(false);
  }
  async function loadGroupDetail(groupId: number, days: 7 | 30, preserveContent = false): Promise<boolean> {
    const requestId = ++latestGroupDetailRequestId.current;
    if (!preserveContent) { setGroupDetailStatus("loading"); setGroupDetailError(null); }
    try {
      const response = await fetch(`/api/competitor-groups/${groupId}/detail?days=${days}`);
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use stable local message */ }
        throw new Error(body.code === "competitor_group_not_found" ? "竞品组不存在" : body.message || "暂时无法获取组分析。");
      }
      const data = await response.json() as GroupDetailData;
      if (requestId !== latestGroupDetailRequestId.current) return false;
      setGroupDetail(data); setGroupDetailError(null); setGroupDetailRangeError(null); setGroupDetailStatus("ready");
      return true;
    } catch (error) {
      if (requestId !== latestGroupDetailRequestId.current) return false;
      const message = error instanceof Error ? error.message : "暂时无法获取组分析。";
      if (preserveContent) setGroupDetailRangeError(message);
      else { setGroupDetailError(message); setGroupDetailStatus("error"); }
      return false;
    }
  }
  async function openOwnProductDialog(group: CompetitorGroupSummary, mode: OwnProductAction) {
    setOwnProductDialog({ group, mode }); setOwnProductSelectedId(null); setOwnProductConfirming(false); setOwnProductError(null);
    if (!listLoaded) {
      setOwnProductLoading(true);
      const loaded = await loadCompetitors();
      setOwnProductLoading(false);
      if (!loaded) setOwnProductError("暂时无法获取组内商品，请关闭后重试。");
    }
  }
  function closeOwnProductDialog() {
    if (!ownProductSubmitting) { setOwnProductDialog(null); setOwnProductSelectedId(null); setOwnProductConfirming(false); setOwnProductError(null); }
  }
  async function submitOwnProduct() {
    if (!ownProductDialog || ownProductSubmittingRef.current) return;
    ownProductSubmittingRef.current = true; setOwnProductSubmitting(true); setOwnProductError(null);
    const result = ownProductDialog.mode === "unbind"
      ? await removeGroupOwnProduct(ownProductDialog.group.id)
      : ownProductSelectedId === null
        ? { ok: false as const, message: "请选择组内商品" }
        : await updateGroupOwnProduct(ownProductDialog.group.id, ownProductSelectedId, ownProductDialog.mode === "replace");
    if (!result.ok) {
      setOwnProductError(result.message); ownProductSubmittingRef.current = false; setOwnProductSubmitting(false); return;
    }
    const message = ownProductDialog.mode === "unbind" ? "我方商品已解除绑定。" : ownProductDialog.mode === "replace" ? "我方商品已更换。" : "我方商品已绑定。";
    setOwnProductDialog(null); setOwnProductSelectedId(null); setOwnProductConfirming(false); setNotice({ message, type: "success" });
    try {
      const refreshSucceeded = (await Promise.all([loadGroups(), loadCompetitors(), loadOwnProducts(), loadDashboard()])).every(Boolean);
      setNotice(getBatchRefreshNotice(message, refreshSucceeded));
    } finally { ownProductSubmittingRef.current = false; setOwnProductSubmitting(false); }
  }
  function openGroupAssignmentDialog(competitor?: Competitor) {
    const target = competitor ?? detail?.competitor;
    if (!target) return;
    setGroupAssignmentError(null);
    setGroupAssignmentDialog({ competitorId: target.id, groupId: target.group_id, ownership: target.ownership, fromDetail: competitor === undefined });
  }
  function closeGroupAssignmentDialog() {
    if (!groupAssignmentSubmitting) { setGroupAssignmentDialog(null); setGroupAssignmentError(null); }
  }
  async function submitGroupAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!groupAssignmentDialog || groupAssignmentSubmitting) return;
    setGroupAssignmentSubmitting(true); setGroupAssignmentError(null);
    const result = await updateCompetitorGroup(groupAssignmentDialog.competitorId, groupAssignmentDialog.groupId);
    if (!result.ok) {
      setGroupAssignmentError(result.message);
      setGroupAssignmentSubmitting(false);
      return;
    }
    try {
      setGroupAssignmentDialog(null);
      const refreshList = groupAssignmentDialog.ownership === "self" ? loadOwnProducts : loadCompetitors;
      const refreshes: Promise<unknown>[] = [refreshList(), loadDashboard(), loadGroups()];
      if (groupAssignmentDialog.fromDetail) refreshes.push(loadDetail(groupAssignmentDialog.competitorId, detailDays));
      const refreshSucceeded = (await Promise.all(refreshes)).every(Boolean);
      setNotice(getBatchRefreshNotice("竞品组已更新。", refreshSucceeded));
    } catch {
      setGroupAssignmentError("竞品组更新失败，请稍后重试");
    } finally { setGroupAssignmentSubmitting(false); }
  }
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const urls = parseCompetitorUrls(url);
    if (addStatus === "submitting" || urls.length === 0) return;
    setAddStatus("submitting"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: urls.length });
    const successLabels: string[] = [];
    const result = await addCompetitorsSequentially(urls, groupId, fetch, (completed, total) => setAddProgress({ completed, total }), (_url, body) => {
      successLabels.push(body.ownership === "self" ? `已识别为我方商品「${body.title || "新商品"}」，已添加至我方商品` : `已添加监控商品「${body.title || "新商品"}」`);
    });
    if (result.failures.length === 0) {
      setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setGroupCreateStatus("initial"); setAddProgress({ completed: 0, total: 0 }); const refreshSucceeded = (await Promise.all([loadCompetitors(), loadOwnProducts(), loadDashboard()])).every(Boolean); setNotice(getBatchRefreshNotice(successLabels.length === 1 ? successLabels[0] : `已添加 ${result.succeeded.length} 个监控商品`, refreshSucceeded)); if (refreshSucceeded) setPaginationResetVersion((version) => version + 1); return;
    }
    setAddFailures(result.failures); setAddSucceededCount(result.succeeded.length); setUrl(result.failures.map((failure) => failure.url).join("\n")); setAddStatus(result.succeeded.length ? "partial" : "failed");
    if (result.succeeded.length > 0) { const refreshSucceeded = (await Promise.all([loadCompetitors(), loadOwnProducts(), loadDashboard()])).every(Boolean); setNotice(getBatchRefreshNotice(`已添加 ${result.succeeded.length} 个监控商品`, refreshSucceeded)); if (refreshSucceeded) setPaginationResetVersion((version) => version + 1); }
  }
  function openBatchGroupDialog(selectedCompetitorIds: number[]) {
    const selected = currentProducts.filter((item) => selectedCompetitorIds.includes(item.id));
    const eligible = selected.filter((item) => !isSelfProduct(item));
    setBatchGroupTarget(undefined);
    setBatchGroupError(null);
    setBatchGroupDialog({ competitorIds: eligible.map((item) => item.id), selectedCount: selected.length, ownCount: selected.length - eligible.length });
  }
  function closeBatchGroupDialog() {
    if (!batchGroupSubmitting) { setBatchGroupDialog(null); setBatchGroupTarget(undefined); setBatchGroupError(null); }
  }
  async function submitBatchGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!batchGroupDialog || batchGroupTarget === undefined || batchGroupSubmitting) return;
    setBatchGroupSubmitting(true); setBatchGroupError(null);
    try {
      const response = await fetch("/api/competitors/group-batch", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competitor_ids: batchGroupDialog.competitorIds, group_id: batchGroupTarget }) });
      let body: { code?: string; message?: string; updated_count?: number } = {};
      try { body = await response.json() as typeof body; } catch { /* use the stable fallback below */ }
      if (!response.ok) throw new Error(body.message || "竞品组更新失败，请稍后重试");
      setBatchGroupDialog(null); setBatchGroupTarget(undefined); setSelectedIds(new Set());
      const updatedCount = body.updated_count ?? 0;
      const groupName = batchGroupTarget === null ? "未分组" : groups.find((group) => group.id === batchGroupTarget)?.name || "目标竞品组";
      const refreshSucceeded = (await Promise.all([loadCurrentProducts(), loadGroups(), loadDashboard()])).every(Boolean);
      setNotice(getBatchRefreshNotice(updatedCount > 0 ? `已将 ${updatedCount} 个竞品${batchGroupTarget === null ? "移至" : "设置到"}「${groupName}」` : "所选竞品已在目标分组，无需修改", refreshSucceeded));
    } catch (error) {
      setBatchGroupError(error instanceof Error ? error.message : "竞品组更新失败，请稍后重试");
    } finally { setBatchGroupSubmitting(false); }
  }
  function openBatchLifecycleDialog(action: "stop" | "delete", selectedCompetitorIds: number[]) {
    const selected = currentProducts.filter((item) => selectedCompetitorIds.includes(item.id));
    const eligible = selected.filter((item) => action === "stop" ? item.is_active : !isSelfProduct(item));
    if (eligible.length === 0) return;
    setNotice(null);
    setBatchLifecycleError(null);
    setBatchLifecycleDialog({ action, competitorIds: eligible.map((item) => item.id), selectedCount: selected.length, ownCount: selected.filter(isSelfProduct).length });
  }
  function closeBatchLifecycleDialog() {
    if (!batchLifecycleSubmittingRef.current) { setBatchLifecycleDialog(null); setBatchLifecycleError(null); }
  }
  async function refreshAfterBatchLifecycle() {
    return (await Promise.all([loadCurrentProducts(), loadGroups(), loadDashboard()])).every(Boolean);
  }
  async function updateMonitoringBatch(selectedCompetitorIds: number[], isActive: boolean) {
    if (batchLifecycleSubmittingRef.current) return;
    const eligibleIds = currentProducts.filter((item) => selectedCompetitorIds.includes(item.id) && item.is_active !== isActive).map((item) => item.id);
    if (eligibleIds.length === 0) return;
    batchLifecycleSubmittingRef.current = true;
    setBatchLifecycleSubmitting(true);
    setNotice(null);
    try {
      const response = await fetch("/api/competitors/monitoring-batch", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ competitor_ids: eligibleIds, is_active: isActive }) });
      let body: CollectionErrorBody & { updated_count?: number } = {};
      try { body = await response.json() as typeof body; } catch { /* use the stable fallback below */ }
      if (!response.ok) throw new Error(getLifecycleErrorMessage(body.code, body.message));
      setSelectedIds(new Set());
      const updatedCount = body.updated_count ?? 0;
      const refreshSucceeded = await refreshAfterBatchLifecycle();
      setNotice(getBatchRefreshNotice(updatedCount > 0 ? `${isActive ? "已恢复监控" : "已停止监控"} ${updatedCount} 个商品` : isActive ? "所选商品均在监控中，无需修改" : "所选商品均已停止监控，无需修改", refreshSucceeded));
    } catch (error) {
      setNotice({ message: error instanceof Error ? error.message : "操作失败，请稍后重试", type: "error" });
    } finally {
      batchLifecycleSubmittingRef.current = false;
      setBatchLifecycleSubmitting(false);
    }
  }
  async function submitBatchLifecycle() {
    if (!batchLifecycleDialog || batchLifecycleSubmittingRef.current) return;
    batchLifecycleSubmittingRef.current = true;
    setBatchLifecycleSubmitting(true);
    setBatchLifecycleError(null);
    try {
      const isDelete = batchLifecycleDialog.action === "delete";
      const response = await fetch(isDelete ? "/api/competitors/delete-batch" : "/api/competitors/monitoring-batch", { method: isDelete ? "POST" : "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(isDelete ? { competitor_ids: batchLifecycleDialog.competitorIds } : { competitor_ids: batchLifecycleDialog.competitorIds, is_active: false }) });
      let body: CollectionErrorBody & { updated_count?: number; deleted_count?: number } = {};
      try { body = await response.json() as typeof body; } catch { /* use the stable fallback below */ }
      if (!response.ok) throw new Error(getLifecycleErrorMessage(body.code, body.message));
      setBatchLifecycleDialog(null);
      setSelectedIds(new Set());
      const count = isDelete ? body.deleted_count ?? 0 : body.updated_count ?? 0;
      const refreshSucceeded = await refreshAfterBatchLifecycle();
      setNotice(getBatchRefreshNotice(isDelete ? `已永久删除 ${count} 个竞品` : count > 0 ? `已停止监控 ${count} 个商品` : "所选商品均已停止监控，无需修改", refreshSucceeded));
    } catch (error) {
      setBatchLifecycleError(error instanceof Error ? error.message : "操作失败，请稍后重试");
    } finally {
      batchLifecycleSubmittingRef.current = false;
      setBatchLifecycleSubmitting(false);
    }
  }
  async function handleBatchAction(mode: BatchAction, selectedCompetitorIds: number[] = []) {
    if (mode === "group") { openBatchGroupDialog(selectedCompetitorIds); return; }
    if (mode === "stop" || mode === "delete") { openBatchLifecycleDialog(mode, selectedCompetitorIds); return; }
    if (mode === "resume") { void updateMonitoringBatch(selectedCompetitorIds, true); return; }
    setNotice(null);
    try {
      const response = await fetch("/api/competitors/collect-batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mode === "selected" ? { mode, competitor_ids: selectedCompetitorIds } : { mode }) });
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        setNotice({ message: getCollectionErrorMessage(body.code, body.message), type: "error" });
        return;
      }
      const next = await response.json() as BatchState;
      batchStateRef.current = next;
      setBatchState(next);
      setSelectedIds(new Set());
      if (next.status === "completed") await loadDashboard();
    } catch (error) {
      setNotice({ message: getCollectionFailureMessage({ kind: "request", error }), type: "error" });
    }
  }
  function openLifecycleDialog(action: "stop" | "delete", competitor: LifecycleCompetitor) {
    setNotice(null); setLifecycleError(null); setLifecycleDialog({ action, competitor });
  }
  function closeLifecycleDialog() {
    if (!lifecycleSubmitting) { setLifecycleDialog(null); setLifecycleError(null); }
  }
  async function readLifecycleError(response: Response): Promise<string> {
    let body: CollectionErrorBody = {};
    try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
    return getLifecycleErrorMessage(body.code, body.message);
  }
  async function refreshAfterLifecycle(message: string, competitor: LifecycleCompetitor, deleted = false): Promise<boolean> {
    setLifecycleDialog(null); setLifecycleError(null);
    setGroupLoaded(false);
    const isSelf = competitor.ownership === "self";
    const refreshList = isSelf ? loadOwnProducts : loadCompetitors;
    if (deleted) {
      latestDetailRequestId.current += 1;
      setDetail(null); setDetailError(null); setDetailStatus("loading"); setSelectedCompetitorId(null);
      navigate(isSelf ? "own-products" : "competitors");
      return (await Promise.all([refreshList(), loadDashboard()])).every(Boolean);
    } else {
      return (await Promise.all([refreshList(), loadDashboard(), loadDetail(competitor.id, detailDays)])).every(Boolean);
    }
  }
  async function updateMonitoring(competitor: LifecycleCompetitor, isActive: boolean, dialogAction: "stop" | null) {
    setLifecycleSubmitting(true); setLifecycleError(null);
    try {
      const response = await fetch(`/api/competitors/${competitor.id}/monitoring`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: isActive }) });
      if (!response.ok) throw new Error(await readLifecycleError(response));
      const refreshSucceeded = await refreshAfterLifecycle(isActive ? "已恢复监控，列表和 Dashboard 已更新。" : "已停止监控，历史数据已保留。", competitor);
      setNotice(getBatchRefreshNotice(isActive ? "已恢复监控，列表和 Dashboard 已更新。" : "已停止监控，历史数据已保留。", refreshSucceeded));
    } catch (error) {
      const message = error instanceof Error ? error.message : "操作失败，请稍后重试";
      if (dialogAction) setLifecycleError(message); else setNotice({ message, type: "error" });
    } finally { setLifecycleSubmitting(false); }
  }
  async function deleteCompetitor(competitor: LifecycleCompetitor) {
    setLifecycleSubmitting(true); setLifecycleError(null);
    try {
      const response = await fetch(`/api/competitors/${competitor.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readLifecycleError(response));
      const message = `${competitor.ownership === "self" ? "我方商品" : "竞品"}已永久删除。`;
      const refreshSucceeded = await refreshAfterLifecycle(message, competitor, true);
      setNotice(getBatchRefreshNotice(message, refreshSucceeded));
    } catch (error) {
      setLifecycleError(error instanceof Error ? error.message : "操作失败，请稍后重试");
    } finally { setLifecycleSubmitting(false); }
  }
  function handleLifecycleAction(action: LifecycleAction, competitor: LifecycleCompetitor) {
    if (action === "stop" || action === "delete") { openLifecycleDialog(action, competitor); return; }
    void updateMonitoring(competitor, true, null);
  }
  function confirmLifecycleAction() {
    if (!lifecycleDialog) return;
    if (lifecycleDialog.action === "stop") void updateMonitoring(lifecycleDialog.competitor, false, "stop");
    else void deleteCompetitor(lifecycleDialog.competitor);
  }
  return <>
    {page === "home" && <HomePage onNavigate={navigate} />}
    {page === "price-compare" && <WorkspacePlaceholderPage page="price-compare" title="全网比价" description="统一检索并对比全网同款与相似商品价格。" note="后续将在这里承载商品检索、候选同款筛选、价格对比和结果沉淀。" icon="compare" onNavigate={navigate} />}
    {page === "auto-inquiry" && <WorkspacePlaceholderPage page="auto-inquiry" title="自动询价" description="统一管理供应商询价任务与报价结果。" note="后续将在这里承载询价对象、询价话术、回复状态和供应商报价记录。" icon="inquiry" onNavigate={navigate} />}
    {page === "auto-listing" && <WorkspacePlaceholderPage page="auto-listing" title="自动上架" description="统一管理商品资料校验、上架任务与执行结果。" note="后续将在这里承载商品资料准备、渠道映射、批量上架和失败结果处理。" icon="listing" onNavigate={navigate} />}
    {page === "dashboard" && <DashboardPage data={dashboard} attention={dashboardAttention} attentionStatus={dashboardAttentionStatus} attentionError={dashboardAttentionError} status={dashboardStatus} error={dashboardError} batchState={batchState} ownShopName={ownShopName} onAdd={openDashboardAddDialog} onCollect={() => void handleBatchAction("all_active")} onRetry={() => void loadDashboard()} onRetryAttention={() => void loadDashboardAttention()} onNavigate={navigate} onOpenGroupDetail={openGroupDetail} />}
    {page === "own-products" && <ListPage competitors={ownProducts} ownership="self" groups={groups} status={ownListStatus} error={ownListError} onRetry={() => void loadOwnProducts()} batchState={batchState} selectedIds={selectedIds} onToggleSelected={(competitorId) => setSelectedIds((current) => { const next = new Set(current); if (next.has(competitorId)) next.delete(competitorId); else next.add(competitorId); return next; })} onToggleAll={(checked, competitorIds) => setSelectedIds((current) => updatePageSelection(current, competitorIds, checked))} onReconcileSelection={reconcileSelection} onBatchAction={(mode, competitorIds) => void handleBatchAction(mode, competitorIds)} onOpenDetail={openDetail} onOpenGroupAssignment={openGroupAssignmentDialog} onNavigate={navigate} paginationResetVersion={paginationResetVersion} />}
    {page === "competitors" && <ListPage competitors={competitors} ownership="competitor" groups={groups} status={listStatus} error={listError} onRetry={() => void loadCompetitors()} batchState={batchState} selectedIds={selectedIds} onToggleSelected={(competitorId) => setSelectedIds((current) => { const next = new Set(current); if (next.has(competitorId)) next.delete(competitorId); else next.add(competitorId); return next; })} onToggleAll={(checked, competitorIds) => setSelectedIds((current) => updatePageSelection(current, competitorIds, checked))} onReconcileSelection={reconcileSelection} onBatchAction={(mode, competitorIds) => void handleBatchAction(mode, competitorIds)} onOpenDetail={openDetail} onOpenGroupAssignment={openGroupAssignmentDialog} onNavigate={navigate} initialGroupFilter={listNavigationIntent.filter} navigationVersion={listNavigationIntent.version} paginationResetVersion={paginationResetVersion} />}
    {page === "collection-tasks" && <CollectionTasksPage onNavigate={navigate} batchState={batchState} batchStatus={batchStatus} batchError={batchError} onRefreshBatch={loadBatchStatus} />}
    {page === "settings" && <SettingsPage configured={settingsConfigured} value={settingsValue} status={settingsStatus} error={settingsError} saveError={settingsSaveError} submitting={settingsSubmitting} onChange={setSettingsValue} onRetry={() => void loadOwnShopName()} onSave={submitOwnShopName} onNavigate={navigate} monitoring={monitoringSettings} monitoringStatus={monitoringStatus} monitoringError={monitoringError} monitoringSaveError={monitoringSaveError} monitoringSubmitting={monitoringSubmitting} onMonitoringChange={setMonitoringSettings} onMonitoringOpen={() => { if (monitoringStatus !== "ready") void loadMonitoringSettings(); }} onMonitoringRetry={() => void loadMonitoringSettings()} onMonitoringSave={submitMonitoringSettings} />}
    {page === "groups" && <GroupPage summary={groupSummary} status={groupStatus} error={groupError} onRetry={() => void loadGroups()} onCreate={openGroupCreateDialog} onViewCompetitors={(filter) => navigate("competitors", filter)} onViewAnalysis={openGroupDetail} onRename={openGroupRenameDialog} onDelete={openGroupDeleteDialog} onOwnProduct={(group, mode) => void openOwnProductDialog(group, mode)} onNavigate={navigate} />}
    {page === "group-detail" && <GroupDetailPage data={groupDetail} status={groupDetailStatus} error={groupDetailError} days={groupDetailDays} rangeLoading={groupDetailRangeLoading} rangeError={groupDetailRangeError} onRetry={() => selectedGroupId !== null && void loadGroupDetail(selectedGroupId, groupDetailDays)} onRangeChange={changeGroupDetailRange} onBack={() => navigate("groups")} onViewCompetitors={(id) => navigate("competitors", id)} onOpenDetail={openDetail} onNavigate={navigate} />}
    {page === "detail" && <DetailPage data={detail} groups={groups} status={detailStatus} error={detailError} days={detailDays} rangeLoading={detailRangeLoading} onRetry={() => selectedCompetitorId !== null && void loadDetail(selectedCompetitorId, detailDays)} onRangeChange={changeDetailRange} onBack={() => navigate(detail?.competitor.ownership === "self" ? "own-products" : "competitors")} onChangeGroup={openGroupAssignmentDialog} onLifecycleAction={handleLifecycleAction} lifecycleSubmitting={lifecycleSubmitting} onNavigate={navigate} />}
    {notice && <div className={"toast toast-" + notice.type} role="status">{notice.message}</div>}
    {dialogOpen && <AddDialog url={url} status={addStatus} onUrlChange={setUrl} onSubmit={handleSubmit} onClose={closeDialog} groups={groups} groupId={groupId} onGroupChange={setGroupId} newGroupName={newGroupName} onNewGroupNameChange={setNewGroupName} onCreateGroup={() => void handleCreateGroup()} groupCreateStatus={groupCreateStatus} failures={addFailures} succeededCount={addSucceededCount} progress={addProgress} />}
    {groupNameDialog && <GroupNameDialog mode={groupNameDialog.mode} name={groupName} submitting={groupNameSubmitting} error={groupNameError} onChange={setGroupName} onClose={closeGroupNameDialog} onSubmit={submitGroupName} />}
    {groupDeleteDialog && <GroupDeleteDialog group={groupDeleteDialog} submitting={groupDeleteSubmitting} error={groupDeleteError} onClose={closeGroupDeleteDialog} onConfirm={() => void confirmGroupDelete()} />}
    {ownProductDialog && <OwnProductDialog group={ownProductDialog.group} mode={ownProductDialog.mode} competitors={competitors} loading={ownProductLoading} selectedId={ownProductSelectedId} confirming={ownProductConfirming} submitting={ownProductSubmitting} error={ownProductError} onSelect={(id) => { setOwnProductSelectedId(id); setOwnProductConfirming(false); }} onConfirmStep={() => { setOwnProductConfirming(true); setOwnProductError(null); }} onClose={closeOwnProductDialog} onSubmit={() => void submitOwnProduct()} />}
    {batchGroupDialog && <BatchGroupAssignmentDialog targetGroupId={batchGroupTarget} groups={groups} selectedCount={batchGroupDialog.selectedCount} eligibleCount={batchGroupDialog.competitorIds.length} ownCount={batchGroupDialog.ownCount} submitting={batchGroupSubmitting} error={batchGroupError} onChange={setBatchGroupTarget} onClose={closeBatchGroupDialog} onSubmit={submitBatchGroup} />}
    {batchLifecycleDialog && <BatchLifecycleDialog action={batchLifecycleDialog.action} selectedCount={batchLifecycleDialog.selectedCount} eligibleCount={batchLifecycleDialog.competitorIds.length} ownCount={batchLifecycleDialog.ownCount} submitting={batchLifecycleSubmitting} error={batchLifecycleError} onClose={closeBatchLifecycleDialog} onConfirm={() => void submitBatchLifecycle()} />}
    {groupAssignmentDialog && <GroupAssignmentDialog groupId={groupAssignmentDialog.groupId} groups={groups} submitting={groupAssignmentSubmitting} error={groupAssignmentError} onChange={(groupId) => setGroupAssignmentDialog((current) => current ? { ...current, groupId } : current)} onClose={closeGroupAssignmentDialog} onSubmit={submitGroupAssignment} />}
    {lifecycleDialog && <ConfirmDialog action={lifecycleDialog.action} competitor={lifecycleDialog.competitor} submitting={lifecycleSubmitting} error={lifecycleError} onClose={closeLifecycleDialog} onConfirm={confirmLifecycleAction} />}
  </>;
}

export default App;
