import { createPortal } from "react-dom";
import { PaginationBar } from "./PaginationBar";
export { PaginationBar } from "./PaginationBar";
import { createContext, Fragment, FormEvent, type Dispatch, type ReactNode, type SetStateAction, type SyntheticEvent, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import "./App.css";
import "./CompetitorList.css";
import "./Workspace.css";
import "./Dashboard.css";
import { ProductLibrary } from "./ProductLibrary";
import { WorkspaceTools, WorkspaceToolsProvider } from "./WorkspaceTools";
import { CustomerReachPage } from "./CustomerReach";

type AddStatus = "initial" | "submitting" | "success" | "partial" | "failed" | "invalid" | "duplicate" | "server-error";
type GroupCreateStatus = "initial" | "submitting" | "success" | "invalid" | "duplicate" | "server-error";
type ListStatus = "loading" | "error" | "ready";
type DashboardStatus = "loading" | "error" | "ready";
type GroupStatus = "loading" | "error" | "ready";
export type BatchStatus = "idle" | "running" | "pausing" | "paused" | "stopping" | "stopped" | "resting" | "cooling_down" | "completed" | "verification_required";
export type Page = "home" | "dashboard" | "own-products" | "competitors" | "detail" | "groups" | "group-detail" | "collection-tasks" | "product-library" | "customer-reach" | "ai-assistant" | "price-compare" | "auto-inquiry" | "auto-listing" | "settings";
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
  auto_collection_enabled?: boolean;
  auto_collection_strategy?: "rolling_24h" | "fixed_daily" | "fixed_interval";
  next_auto_collection_at?: string | null;
  work_kind?: "collect_products" | "add_links";
  input_progress?: AddInputSummary | null;
  current_input_position?: number | null;
  status: BatchStatus;
  outcome_code: string | null;
  batch_id: number | null;
  task_id: string | null;
  lifecycle_status: "created" | "running" | "terminal" | null;
  batch_outcome_code: string | null;
  phase: "first_pass" | "verification_resume" | "operating_metrics_retry" | null;
  attempts_started: number;
  page_visits: number;
  page_visits_unknown: number;
  verification_resume_visits: number;
  retry_visits: number;
  retry_max: number;
  retry_total: number;
  retry_completed: number;
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  remaining: number;
  verification_required: number;
  operating_metrics_counts: Record<"not_attempted" | "success" | "partial" | "no_values" | "failed" | "blocked", number>;
  current_competitor_id: number | null;
  current_competitor_title?: string | null;
  browser_open: boolean;
  runner_active: boolean;
  auto_resume_attempt: number;
  auto_resume_max: number;
  cooldown_remaining_seconds: number;
  resting_remaining_seconds: number;
  items: { competitor_id: number; status: "success" | "failed" | "verification_required"; error_code: string | null; message: string | null; outcome: "active" | "offline" | null; operating_metrics_status: "not_attempted" | "success" | "partial" | "no_values" | "failed" | "blocked" }[];
};

export const idleBatchState: BatchState = {
  status: "idle",
  outcome_code: null,
  batch_id: null,
  task_id: null,
  lifecycle_status: null,
  batch_outcome_code: null,
  phase: null,
  attempts_started: 0,
  page_visits: 0,
  page_visits_unknown: 0,
  verification_resume_visits: 0,
  retry_visits: 0,
  retry_max: 0,
  retry_total: 0,
  retry_completed: 0,
  total: 0,
  completed: 0,
  succeeded: 0,
  failed: 0,
  remaining: 0,
  verification_required: 0,
  operating_metrics_counts: { not_attempted: 0, success: 0, partial: 0, no_values: 0, failed: 0, blocked: 0 },
  current_competitor_id: null,
  current_competitor_title: null,
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
    operating_metrics_status?: OperatingMetricsStatus;
    error_type: string | null;
    error_message: string | null;
  }[];
  latest_collection_run?: LatestCollectionRun | null;
  operating_metrics?: OperatingMetric[];
};

export type OperatingMetricsStatus = "not_attempted" | "success" | "partial" | "no_values" | "failed" | "blocked";
export type LatestCollectionRun = { id: number; started_at: string; finished_at: string | null; status: "running" | "success" | "failed"; operating_metrics_status: OperatingMetricsStatus; error_type: string | null; error_message: string | null };
export type OperatingMetric = {
  metric_key: string; label: string; section: "经营表现" | "口碑履约" | "平台标签"; eligible: boolean;
  status: "not_attempted" | "observed" | "placeholder" | "loading" | "source_unavailable" | "read_failed";
  latest_attempt: { collection_run_id: number; status: "observed" | "placeholder" | "loading" | "source_unavailable" | "read_failed"; raw_value: string | null; source: string; observed_at: string; reason: string | null } | null;
  latest_valid: { collection_run_id: number; raw_value: string; source: string; observed_at: string } | null;
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
  latest_collection_run?: LatestCollectionRun | null;
  operating_metrics?: OperatingMetric[];
};
export type GroupComparison = { price: "lower" | "higher" | "overlap" | "unknown"; min_order_quantity: "lower" | "higher" | "equal" | "unknown"; sku_count: "more" | "fewer" | "equal" | "unknown"; total_stock: "higher" | "lower" | "equal" | "unknown" };
export type GroupFactGapMetric = { matched_count: number; comparable_count: number };
export type GroupActionDomainCounts = { price: number; stock: number; sku: number; min_order_quantity: number; lifecycle: number; title: number; main_image: number };
export type GroupTodayEvent = NonNullable<GroupProductFacts["latest_change"]> & { competitor_id: number; role: GroupRole; title: string | null; offer_id: string };
export type GroupActionItem = { competitor_id: number; title: string | null; offer_id: string; event_count: number; latest_change_at: string; domain_counts: GroupActionDomainCounts };
export type PositionMetric = "display_price_min" | "min_order_quantity" | "sku_count" | "total_stock";
export type OfferPosition = { eligible: boolean; reason: string | null; sort_value: string | number | null; rank_asc: number | null; rank_desc: number | null };
export type MetricPosition = { default_direction: "asc" | "desc"; group_count: number; eligible_count: number; offers: Record<string, OfferPosition> };
export type GroupEventPage = { items: (GroupTodayEvent & { shop_name?: string | null })[]; has_more: boolean; next_cursor: string | null; range: "today" | "7" | "30"; mode: "important" | "all"; limit: number; window_start: string; window_end: string; through_event_id: number; important_offer_ids: number[] };
export type GroupDetailData = {
  position: Record<PositionMetric, MetricPosition>;
  event_page: GroupEventPage;
  range_days: 7 | 30;
  group: CompetitorGroup;
  own_product: GroupProductFacts | null;
  summary: { direct_competitor_count: number; monitored_competitor_count: number; changed_competitors_today: number; price_lower_than_own: GroupFactGapMetric; moq_lower_than_own: GroupFactGapMetric; sku_more_than_own: GroupFactGapMetric; stock_higher_than_own: GroupFactGapMetric };
  competitors: (GroupProductFacts & { comparison: GroupComparison })[];
  today: { own_event_count: number; competitor_event_count: number; changed_competitor_count: number; events: GroupTodayEvent[]; event_pagination: GroupEventPage; important_offer_ids: number[] };
  action_window: { days: 7 | 30; own_event_count: number; competitor_event_count: number; competitors: GroupActionItem[]; important_offer_ids: number[] };
  operating_metrics_coverage?: Record<string, { has_history_valid_values: number; active_offers: number }>;
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
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

export function competitorOfferId(value: string): string | null {
  try {
    const parsed = new URL(value.trim());
    if (parsed.protocol !== "https:" || parsed.hostname !== "detail.1688.com" || parsed.username || parsed.password || (parsed.port && parsed.port !== "443")) return null;
    return parsed.pathname.match(/^\/offer\/(\d+)\.html$/)?.[1] ?? null;
  } catch { return null; }
}

export function dedupeCompetitorInputs(value: string): { text: string; source_line: number }[] {
  const seen = new Set<string>();
  return value.split(/\r?\n/).flatMap((line, index) => {
    const text = line.trim();
    if (!text) return [];
    const offerId = competitorOfferId(text);
    if (offerId && seen.has(offerId)) return [];
    if (offerId) seen.add(offerId);
    return [{ text, source_line: index + 1 }];
  });
}

export function mergeCompetitorUrlText(currentValue: string, clipboardValue: string): { value: string; addedCount: number; duplicateCount: number } {
  const seen = new Set(parseCompetitorUrls(currentValue).map(competitorOfferId).filter((id): id is string => id !== null));
  const additions: string[] = [];
  let duplicateCount = 0;
  for (const line of clipboardValue.split(/\r?\n/)) {
    const text = line.trim();
    if (!text) continue;
    const offerId = competitorOfferId(text);
    if (offerId && seen.has(offerId)) { duplicateCount++; continue; }
    if (offerId) seen.add(offerId);
    additions.push(text);
  }
  const value = additions.length
    ? `${currentValue}${currentValue && !currentValue.endsWith("\n") ? "\n" : ""}${additions.join("\n")}`
    : currentValue;
  return { value, addedCount: additions.length, duplicateCount };
}

export type AddFailureCode = "invalid_competitor_url" | "competitor_already_exists" | "competitor_group_not_found" | "own_shop_name_not_configured" | "shop_name_unavailable" | "own_product_already_bound" | "collection_in_progress" | "1688_login_required" | "1688_verification_required" | "collection_timeout" | "collection_parse_failed" | "collection_partial_data" | "offer_id_mismatch" | "collection_save_failed" | "collection_failed" | "validation-error" | "http-error" | "network-error" | "timeout" | "server-error";
export type AddFailure = { url: string; code: AddFailureCode; reason: string };

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

export type AddEnvelope = { submission_id: string; inputs: { text: string; source_line: number }[]; group_id: number | null };
type PendingAddEnvelope = AddEnvelope & { draft_text?: string };
const pendingAddKey = "workbench.add-submission.v1";
export async function submitAddLinks(envelope: AddEnvelope, request: CompetitorRequest = fetch, recover = false) {
  let response = recover ? await request(`/api/competitors/add-batch/${envelope.submission_id}`) : null;
  if (!response || response.status === 404) response = await request("/api/competitors/add-batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(envelope) });
  const body = await response.json() as { accepted?: boolean; code?: string; message?: string; task_id?: string; task?: BatchRecordDetail };
  if (!response.ok || body.accepted !== true || !body.task_id || body.task_id !== envelope.submission_id || !body.task || body.task.task_id !== envelope.submission_id) throw new Error(body.message || (body.code === "idempotency_conflict" ? "同一提交标识内容冲突，请保留原提交并核对" : "受理结果尚未确认，请使用原提交重试查询"));
  return body as { accepted: true; task_id: string; task: BatchRecordDetail };
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

export function buildDashboardTrendChartPoints(trend: readonly DashboardTrendPoint[], width = 640, height = 320): DashboardTrendChartPoint[] {
  const points = trend.slice(-7);
  const scale = buildDashboardTrendScale(points);
  const [minValue, maxValue] = scale.domain;
  const left = 52;
  const right = 38;
  const top = 20;
  const bottom = 44;
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

type ShellProps = { page: Page; onNavigate: (page: Page) => void | boolean; breadcrumb: string; children: ReactNode };
type NavIconName = "home" | "monitoring" | "library" | "assistant" | "compare" | "inquiry" | "listing" | "settings";

function NavIcon({ name }: { name: NavIconName }) {
  const paths: Record<NavIconName, ReactNode> = {
    home: <><path d="m4 10 8-6 8 6" /><path d="M6 9v11h12V9" /><path d="M10 20v-6h4v6" /></>,
    monitoring: <><path d="M4 17V9" /><path d="M10 17V5" /><path d="M16 17v-4" /><path d="m4 7 5-3 5 5 6-5" /></>,
    library: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22V5.5Z" /><path d="M4 5.5V22" /><path d="M8 7h8" /><path d="M8 11h8" /></>,
    assistant: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" /><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></>,
    compare: <><path d="M5 7h12" /><path d="m14 4 3 3-3 3" /><path d="M19 17H7" /><path d="m10 14-3 3 3 3" /></>,
    inquiry: <><path d="M5 5h14v10H9l-4 4V5Z" /><path d="M8 9h8" /><path d="M8 12h5" /></>,
    listing: <><path d="M5 9v10h14V9" /><path d="M9 7l3-3 3 3" /><path d="M12 4v10" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 3v2" /><path d="M12 19v2" /><path d="m5.64 5.64 1.42 1.42" /><path d="m16.94 16.94 1.42 1.42" /><path d="M3 12h2" /><path d="M19 12h2" /><path d="m5.64 18.36 1.42-1.42" /><path d="m16.94 7.06 1.42-1.42" /></>,
  };
  return <span className="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{paths[name]}</svg></span>;
}

const monitoringPages = new Set<Page>(["dashboard", "own-products", "competitors", "detail", "groups", "group-detail", "collection-tasks"]);
const MonitoringNavigationContext = createContext<{ expanded: boolean; setExpanded: Dispatch<SetStateAction<boolean>> } | null>(null);

export function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  function closeMenu() { setMenuOpen(false); menuButton.current?.focus(); }
  function selectPage(nextPage: Page) { setMenuOpen(false); onNavigate(nextPage); }
  const monitoringActive = monitoringPages.has(page);
  const navigationState = useContext(MonitoringNavigationContext);
  const [localExpanded, setLocalExpanded] = useState(monitoringActive);
  const monitoringExpanded = navigationState?.expanded ?? localExpanded;
  const setMonitoringExpanded = navigationState?.setExpanded ?? setLocalExpanded;
  useEffect(() => { if (monitoringActive) setMonitoringExpanded(true); }, [monitoringActive, setMonitoringExpanded]);
  return <aside className={"sidebar workspace-sidebar" + (menuOpen ? " workspace-menu-open" : "")} onKeyDown={(event) => { if (event.key === "Escape" && menuOpen) { event.preventDefault(); closeMenu(); } }}>
    <div className="brand"><span className="brand-mark">PW</span><div><strong>个人工作台</strong><span>工作提效工具集</span></div></div>
    <button type="button" ref={menuButton} className="workspace-menu-toggle" aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? "收起导航" : "展开导航"}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d={menuOpen ? "m6 6 12 12M6 18 18 6" : "M4 6h16M4 12h16M4 18h16"} /></svg></button>
    <div id="workspace-navigation" className="workspace-navigation">
    <nav aria-label="主导航">
      <button className={"nav-item" + (page === "home" ? " nav-active" : "")} onClick={() => selectPage("home")} aria-current={page === "home" ? "page" : undefined}><NavIcon name="home" />首页</button>
      <p className="nav-section-label">工作工具</p>
      <button className={"nav-item" + (page === "product-library" ? " nav-active" : "")} onClick={() => selectPage("product-library")} aria-current={page === "product-library" ? "page" : undefined}><NavIcon name="library" />产品库</button>
      <button className={"nav-item" + (page === "customer-reach" ? " nav-active" : "")} onClick={() => selectPage("customer-reach")} aria-current={page === "customer-reach" ? "page" : undefined}><NavIcon name="monitoring" />客户触达</button>
      <div className={"nav-group" + (monitoringExpanded ? "" : " nav-group-collapsed")}>
        <button type="button" className={"nav-group-title" + (monitoringActive ? " nav-group-title-current" : "")} onClick={() => setMonitoringExpanded((expanded) => !expanded)} aria-expanded={monitoringExpanded} aria-controls="competitor-monitoring-nav"><NavIcon name="monitoring" />竞品监控<span className="nav-chevron" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m8 14 4-4 4 4" /></svg></span></button>
        <div className="nav-group-children" id="competitor-monitoring-nav" hidden={!monitoringExpanded}>
          <button className={"nav-item nav-child" + (page === "dashboard" ? " nav-active" : "")} onClick={() => selectPage("dashboard")} aria-current={page === "dashboard" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品监控大屏</button>
          <button className={"nav-item nav-child" + (page === "own-products" ? " nav-active" : "")} onClick={() => selectPage("own-products")} aria-current={page === "own-products" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />我方商品</button>
          <button className={"nav-item nav-child" + (page === "competitors" || page === "detail" ? " nav-active" : "")} onClick={() => selectPage("competitors")} aria-current={page === "competitors" || page === "detail" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品列表</button>
          <button className={"nav-item nav-child" + (page === "groups" || page === "group-detail" ? " nav-active" : "")} onClick={() => selectPage("groups")} aria-current={page === "groups" || page === "group-detail" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品分组</button>
          <button className={"nav-item nav-child" + (page === "collection-tasks" ? " nav-active" : "")} onClick={() => selectPage("collection-tasks")} aria-current={page === "collection-tasks" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />采集记录</button>
        </div>
      </div>
      <p className="nav-section-label nav-section-planned">规划工具<span>规划中</span></p>
      <button className={"nav-item" + (page === "ai-assistant" ? " nav-active" : "")} onClick={() => selectPage("ai-assistant")} aria-current={page === "ai-assistant" ? "page" : undefined}><NavIcon name="assistant" />AI智能助手</button>
      <button className={"nav-item" + (page === "price-compare" ? " nav-active" : "")} onClick={() => selectPage("price-compare")} aria-current={page === "price-compare" ? "page" : undefined}><NavIcon name="compare" />全网比价</button>
      <button className={"nav-item" + (page === "auto-inquiry" ? " nav-active" : "")} onClick={() => selectPage("auto-inquiry")} aria-current={page === "auto-inquiry" ? "page" : undefined}><NavIcon name="inquiry" />自动询价</button>
      <button className={"nav-item" + (page === "auto-listing" ? " nav-active" : "")} onClick={() => selectPage("auto-listing")} aria-current={page === "auto-listing" ? "page" : undefined}><NavIcon name="listing" />自动上架</button>
      <button className={"nav-item" + (page === "settings" ? " nav-active" : "")} onClick={() => selectPage("settings")} aria-current={page === "settings" ? "page" : undefined}><NavIcon name="settings" />系统设置</button>
    </nav>
    </div>
    <div className="sidebar-note"><strong>个人工作台</strong><span>商品资料与竞争情报</span></div>
  </aside>;
}

function AppShell({ page, onNavigate, breadcrumb, children }: ShellProps) {
  const monitoringPage = monitoringPages.has(page);
  return <div className={`app-shell workspace-shell${page === "settings" ? " settings-shell" : ""}${page === "group-detail" ? " group-detail-shell" : ""}`}><a className="workspace-skip" href="#workspace-main">跳至主内容</a><Sidebar page={page} onNavigate={onNavigate} /><main id="workspace-main" tabIndex={-1} className={`main-content${page === "dashboard" ? " main-content-dashboard" : ""}`} data-page={page}>
    <div className="workspace-header"><nav className="breadcrumb" aria-label="当前位置"><button type="button" onClick={() => onNavigate("home")}>个人工作台</button><span aria-hidden="true">/</span>{monitoringPage && <><button type="button" aria-label="返回模块总览" onClick={() => onNavigate("dashboard")}>竞品监控</button><span aria-hidden="true">/</span></>}<strong aria-current="page">{breadcrumb}</strong></nav><WorkspaceTools onNavigate={onNavigate} /></div>
    {children}
  </main></div>;
}

export function ConfirmDialog({ action, competitor, submitting, error, onClose, onConfirm }: { action: "stop" | "delete"; competitor: LifecycleCompetitor; submitting: boolean; error: string | null; onClose: () => void; onConfirm: () => void }) {
  const isDelete = action === "delete";
  const isSelf = competitor.ownership === "self";
  const productLabel = competitor.title?.trim() || competitor.offer_id;
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="lifecycle-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="lifecycle-dialog-title">{isDelete ? `永久删除${isSelf ? "我方商品" : "竞品"}` : "停止监控"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    {isDelete ? <p className="dialog-description">删除后，该商品的历史快照、SKU、变化记录和采集记录都会永久删除，无法恢复。<br />当前商品：{productLabel}<br />Offer ID：{competitor.offer_id}</p> : <p className="dialog-description">停止后将不再自动采集该商品，但历史数据会保留，之后可以恢复监控。</p>}
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

function GroupMoreMenu({ onRename, onDelete }: { onRename: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const dismiss = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);
  return <div className="group-more-menu" ref={root} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }} onKeyDown={(event) => {
    if (event.key === "Escape" && open) { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
    if (open && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const items = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') || []);
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[next]?.focus();
    }
  }}>
    <button ref={trigger} type="button" className="detail-button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((current) => !current)}>更多</button>
    {open && <div className="group-more-popover" role="menu">
      <button type="button" role="menuitem" onClick={() => { setOpen(false); onRename(); }}>重命名竞品组</button>
      <button type="button" role="menuitem" className="more-menu-danger" onClick={() => { setOpen(false); onDelete(); }}>删除竞品组</button>
    </div>}
  </div>;
}

function OfferMoreMenu({ product, isSelf, busy, onOpenDetail, onAction }: { product: GroupProductFacts; isSelf: boolean; busy: boolean; onOpenDetail: (id: number) => void; onAction: (action: "stop" | "delete", product: LifecycleCompetitor) => void }) {
  const [position, setPosition] = useState<{ top: number; right: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!position) return;
    menu.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const dismiss = (event: PointerEvent) => { if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setPosition(null); };
    const close = () => setPosition(null);
    document.addEventListener("pointerdown", dismiss); window.addEventListener("scroll", close, true); window.addEventListener("resize", close);
    return () => { document.removeEventListener("pointerdown", dismiss); window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, [position]);
  const target: LifecycleCompetitor = { ...product, ownership: isSelf ? "self" : "competitor", group_role: isSelf ? "own" : "competitor" };
  return <div className="position-row-actions" onClick={event => event.stopPropagation()}>
    <button ref={trigger} type="button" className="detail-button" aria-label={`Offer ${product.offer_id} 更多操作`} aria-haspopup="menu" aria-expanded={!!position} disabled={busy} onClick={() => { const rect = trigger.current!.getBoundingClientRect(); setPosition(position ? null : { top: Math.min(rect.bottom + 6, window.innerHeight - 130), right: Math.max(8, window.innerWidth - rect.right) }); }}>•••</button>
    {position && createPortal(<div ref={menu} className="group-more-popover offer-more-popover" role="menu" style={position} onClick={event => event.stopPropagation()} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== trigger.current) setPosition(null); }} onKeyDown={event => {
      if (event.key === "Escape") { setPosition(null); trigger.current?.focus(); }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) { event.preventDefault(); const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')); const index = items.indexOf(document.activeElement as HTMLButtonElement); items[event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus(); }
    }}>
      <button type="button" role="menuitem" onClick={() => { setPosition(null); onOpenDetail(product.id); }}>查看详情</button>
      <button type="button" role="menuitem" onClick={() => { setPosition(null); onAction("stop", target); }}>停止监控</button>
      <button type="button" role="menuitem" className="more-menu-danger" onClick={() => { setPosition(null); onAction("delete", target); }}>删除{isSelf ? "我方商品" : "竞品"}</button>
    </div>, document.body)}
  </div>;
}

type GroupDirectoryFilter = "all" | "changed" | "incomplete" | "empty";
type GroupDirectorySort = "recent" | "changes" | "count" | "price" | "name";
type GroupDirectoryView = "list" | "cards";

export function filterAndSortCompetitorGroups(groups: readonly CompetitorGroupSummary[], query: string, filter: GroupDirectoryFilter, sort: GroupDirectorySort): CompetitorGroupSummary[] {
  const needle = query.trim().toLocaleLowerCase();
  return groups.map((group, index) => ({ group, index })).filter(({ group }) => {
    const matchesQuery = !needle || `${group.name} ${group.own_product?.title || ""}`.toLocaleLowerCase().includes(needle);
    const matchesFilter = filter === "all" || filter === "changed" && group.changed_competitors_today > 0
      || filter === "incomplete" && group.competitor_count > 0 && group.active_count < group.competitor_count
      || filter === "empty" && group.competitor_count === 0;
    return matchesQuery && matchesFilter;
  }).sort((a, b) => {
    if (sort === "changes") return b.group.changed_competitors_today - a.group.changed_competitors_today || a.index - b.index;
    if (sort === "count") return b.group.competitor_count - a.group.competitor_count || a.index - b.index;
    if (sort === "price") {
      const minimum = (group: CompetitorGroupSummary) => {
        const values = [group.price_min, group.price_max].filter((value): value is string => value !== null).map(Number).filter(Number.isFinite);
        return values.length ? Math.min(...values) : Number.POSITIVE_INFINITY;
      };
      const delta = minimum(a.group) - minimum(b.group);
      return Number.isNaN(delta) ? a.index - b.index : delta || a.index - b.index;
    }
    if (sort === "name") return a.group.name.localeCompare(b.group.name, "zh-CN") || a.index - b.index;
    const parsedA = a.group.last_change_at ? Date.parse(a.group.last_change_at) : Number.NEGATIVE_INFINITY;
    const parsedB = b.group.last_change_at ? Date.parse(b.group.last_change_at) : Number.NEGATIVE_INFINITY;
    const aTime = Number.isNaN(parsedA) ? Number.NEGATIVE_INFINITY : parsedA;
    const bTime = Number.isNaN(parsedB) ? Number.NEGATIVE_INFINITY : parsedB;
    return bTime - aTime || a.index - b.index;
  }).map(({ group }) => group);
}

function CompetitorGroupCard({ group, view, onViewCompetitors, onViewAnalysis, onRename, onDelete }: { group: CompetitorGroupSummary; view: GroupDirectoryView; onViewCompetitors: () => void; onViewAnalysis: () => void; onRename: () => void; onDelete: () => void }) {
  const stoppedCount = group.competitor_count - group.active_count;
  const coverageStatus = group.competitor_count === 0 ? "空分组" : stoppedCount > 0 ? "部分停止" : "全部监控";
  return <article className="group-directory-card" role="listitem" aria-label={group.name} data-group-id={group.id}>
    <header className="group-directory-card-heading"><div className="group-directory-heading-main"><button type="button" className="group-directory-name" title={group.name} onClick={onViewAnalysis}>{group.name}</button></div>{view === "cards" && <GroupMoreMenu onRename={onRename} onDelete={onDelete} />}</header>
    <div className="group-directory-coverage"><span className="group-directory-coverage-count"><strong>{group.competitor_count}</strong><span>个竞品</span></span><span className="group-directory-coverage-state"><span>监控 {group.active_count}/{group.competitor_count}{stoppedCount > 0 && <> · 停止 {stoppedCount}</>}</span><span className={"group-directory-status " + (stoppedCount > 0 ? "is-partial" : group.competitor_count === 0 ? "is-empty" : "")}>{coverageStatus}</span></span></div>
    <dl className="group-directory-facts">
      <div><dt>竞品价格范围</dt><dd title="链接展示价范围，不代表同规格竞品比较价">{formatGroupPriceRange(group)}</dd></div>
      <div><dt>今日变化</dt><dd className={group.changed_competitors_today > 0 ? "group-directory-changed" : "group-directory-muted"}>{group.changed_competitors_today} 个竞品</dd></div>
      <div><dt>最近变化</dt><dd className="group-directory-latest" title={formatGroupLatestChange(group.last_change_at)}>{formatGroupLatestChange(group.last_change_at)}</dd></div>
    </dl>
    <footer className="group-directory-card-footer"><button type="button" className="detail-button" onClick={onViewCompetitors}>查看竞品</button>{view === "list" && <GroupMoreMenu onRename={onRename} onDelete={onDelete} />}</footer>
  </article>;
}

function UnassignedGroupCard({ metrics, onViewCompetitors }: { metrics: CompetitorGroupMetrics; onViewCompetitors: () => void }) {
  return <div className="group-unassigned-row"><div><strong>未分组</strong><span>{metrics.competitor_count} 个商品尚未归入竞品组</span></div><button type="button" className="detail-button" onClick={onViewCompetitors}>查看竞品</button></div>;
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
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<GroupDirectoryFilter>("all");
  const [sort, setSort] = useState<GroupDirectorySort>("recent");
  const [view, setView] = useState<GroupDirectoryView>("list");
  const [page, setPage] = useState(1);
  const hasUnassigned = summary?.unassigned.competitor_count ? summary.unassigned.competitor_count > 0 : false;
  const isEmpty = status === "ready" && summary !== null && summary.groups.length === 0 && !hasUnassigned;
  const groups = summary ? filterAndSortCompetitorGroups(summary.groups, query, filter, sort) : [];
  const totalPages = Math.max(1, Math.ceil(groups.length / 10));
  const currentPage = Math.min(page, totalPages);
  const pageGroups = groups.slice((currentPage - 1) * 10, currentPage * 10);
  const totalCompetitors = summary ? summary.groups.reduce((total, group) => total + group.competitor_count, summary.unassigned.competitor_count) : 0;
  const totalActive = summary ? summary.groups.reduce((total, group) => total + group.active_count, summary.unassigned.active_count) : 0;
  const changedGroups = summary ? summary.groups.filter(group => group.changed_competitors_today > 0).length : 0;
  const partialGroups = summary ? summary.groups.filter(group => group.competitor_count > 0 && group.active_count < group.competitor_count).length : 0;
  const emptyGroups = summary ? summary.groups.filter(group => group.competitor_count === 0).length : 0;
  useEffect(() => { setPage((current) => Math.min(current, totalPages)); }, [totalPages]);
  const changeFilter = (next: GroupDirectoryFilter) => { setFilter(next); setPage(1); };
  const clearFilters = () => { setQuery(""); setFilter("all"); setSort("recent"); setPage(1); };
  return <AppShell page="groups" onNavigate={onNavigate} breadcrumb="竞品分组">
    <header className="page-header"><div><h1>竞品分组</h1><p className="page-description">按我方商品组织直接竞品，快速进入组内分析。</p></div><button type="button" className="primary-button" onClick={onCreate}>新增竞品组</button></header>
    {status === "loading" && <section className="table-card group-state-card state-panel"><div className="spinner" /><strong>正在加载竞品组…</strong></section>}
    {status === "error" && <section className="table-card group-state-card state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品组。"}</span><button type="button" className="secondary-button" onClick={onRetry}>重试</button></section>}
    {isEmpty && <section className="table-card group-state-card state-panel"><div className="empty-icon">＋</div><strong>还没有竞品组</strong><span>新增竞品组后，可按我方商品型号归集对应竞品进行对比监控。</span><button type="button" className="primary-button" onClick={onCreate}>新增竞品组</button></section>}
    {status === "ready" && summary && !isEmpty && <>
      <div className="group-directory-stats" aria-label="分组概况">
        <button type="button" onClick={() => changeFilter("all")}><span>分组总数</span><strong>{summary.groups.length}</strong></button>
        <div><span>直接竞品（含未分组）</span><strong>{totalCompetitors}</strong></div>
        <div><span>监控中（含未分组）</span><strong>{totalActive}</strong></div>
        <button type="button" onClick={() => changeFilter("changed")}><span>今日有变化</span><strong className="is-blue">{changedGroups}</strong></button>
        <button type="button" onClick={() => changeFilter("incomplete")}><span>部分停止</span><strong className="is-orange">{partialGroups}</strong></button>
      </div>
      {summary.groups.length > 0 && <>
        <div className="group-directory-workspace">
        <div className="group-directory-tabs" role="group" aria-label="快捷筛选">
          {([["all", "全部分组", summary.groups.length], ["changed", "今日有变化", changedGroups], ["incomplete", "部分停止", partialGroups], ["empty", "空分组", emptyGroups]] as const).map(([value, label, count]) => <button type="button" key={value} className={filter === value ? "is-active" : ""} aria-pressed={filter === value} onClick={() => changeFilter(value)}>{label} <small>{count}</small></button>)}
        </div>
        <section className="filter-card group-directory-toolbar" aria-label="分组搜索和筛选">
          <div className="filter-field filter-search"><label htmlFor="group-directory-search">搜索</label><input id="group-directory-search" aria-label="搜索竞品组" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="组名或我方商品标题" /></div>
          <div className="filter-field group-directory-select"><label htmlFor="group-directory-filter">筛选</label><select id="group-directory-filter" aria-label="分组筛选" value={filter} onChange={(event) => { setFilter(event.target.value as GroupDirectoryFilter); setPage(1); }}><option value="all">全部分组</option><option value="changed">今日有变化</option><option value="incomplete">部分停止</option><option value="empty">空分组</option></select></div>
          <div className="filter-field group-directory-select"><label htmlFor="group-directory-sort">排序</label><select id="group-directory-sort" aria-label="分组排序" value={sort} onChange={(event) => { setSort(event.target.value as GroupDirectorySort); setPage(1); }}><option value="recent">最近变化优先</option><option value="changes">今日变化最多</option><option value="count">竞品数量最多</option><option value="price">最低价格优先</option><option value="name">组名排序</option></select></div>
          <div className="group-directory-views" role="group" aria-label="视图切换"><button type="button" aria-pressed={view === "list"} className={view === "list" ? "is-active" : ""} onClick={() => setView("list")}>列表</button><button type="button" aria-pressed={view === "cards"} className={view === "cards" ? "is-active" : ""} onClick={() => setView("cards")}>卡片</button></div>
          <button type="button" className="text-button group-directory-clear" onClick={clearFilters}>清除筛选</button>
        </section></div>
        <div className="group-directory-results">
          <div className="group-directory-result-count">显示 {groups.length} / {summary.groups.length} 个分组</div>
          {view === "list" && groups.length > 0 && <div className="group-directory-list-head" aria-hidden="true"><span>分组名称</span><span className="group-directory-list-coverage-head"><span>竞品数量</span><span>监控状态</span></span><span className="group-directory-list-facts-head"><span>竞品价格范围</span><span>今日变化</span><span>最近变化</span></span><span>操作</span></div>}
          {pageGroups.length > 0 ? <div role="list" aria-label="竞品组" className={"group-directory-grid " + (view === "list" ? "view-list" : "view-cards")}>{pageGroups.map(group => <CompetitorGroupCard key={group.id} group={group} view={view} onViewCompetitors={() => onViewCompetitors(group.id)} onViewAnalysis={() => onViewAnalysis(group.id)} onRename={() => onRename(group)} onDelete={() => onDelete(group)} />)}</div> : <section className="group-directory-no-results"><strong>没有符合条件的竞品组</strong><span>调整搜索或筛选条件后重试。</span></section>}
          <PaginationBar total={groups.length} itemLabel="个竞品组" pageSize={10} page={currentPage} totalPages={totalPages} onPrevious={() => setPage(currentPage - 1)} onNext={() => setPage(currentPage + 1)} previousDisabled={currentPage === 1} nextDisabled={currentPage === totalPages} />
        </div>
      </>}
      {hasUnassigned && <UnassignedGroupCard metrics={summary.unassigned} onViewCompetitors={() => onViewCompetitors("unassigned")} />}
    </>}
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

const positionLabels: Record<PositionMetric, string> = { display_price_min: "链接展示报价下限", min_order_quantity: "MOQ", sku_count: "SKU", total_stock: "完整库存" };
const positionReasons: Record<string, string> = { not_monitored: "已停止监控，历史事实", offline: "已下架，历史事实", status_unknown: "在线状态未知，历史事实", no_snapshot: "未采集", unknown_value: "字段未知或无效" };
const pendingViews = {
  "经营表现": [
    { title: "上架时间", metric_key: "listing_time" }, { title: "月成交", metric_key: "monthly_deal" },
    { title: "月代销", metric_key: "monthly_dropship" }, { title: "年成交件数", metric_key: "annual_units" },
    { title: "年成交笔数", metric_key: "annual_orders" },
  ],
  "口碑履约": [
    { title: "评论数", metric_key: "review_count" }, { title: "好评率", metric_key: "positive_rate" },
    { title: "揽收率", metric_key: "pickup_rate" },
  ],
};

type OperatingMetricSortKey = "listing_time" | "monthly_deal" | "monthly_dropship" | "annual_units" | "annual_orders" | "review_count" | "positive_rate" | "pickup_rate";
type OperatingMetricView = "经营表现" | "口碑履约";
const operatingSortDefaults: Record<OperatingMetricSortKey, "asc" | "desc"> = {
  listing_time: "desc", monthly_deal: "desc", monthly_dropship: "desc", annual_units: "desc", annual_orders: "desc",
  review_count: "desc", positive_rate: "desc", pickup_rate: "desc",
};

const operatingStatusLabels: Record<OperatingMetricsStatus, string> = {
  not_attempted: "未尝试", success: "成功", partial: "部分成功", no_values: "页面暂无值", failed: "失败", blocked: "已阻止",
};
const metricAttemptLabels = { observed: "已读取", placeholder: "页面显示占位符", loading: "仍在加载", source_unavailable: "来源不可用", read_failed: "读取失败" } as const;
const operatingMetricSource = (source: string) => source === "1688_official_procurement_assistant_top" ? "1688 官方采购助手顶部区域" : source;
export function formatCollectionRunStatus(status: "running" | "success" | "failed", operatingStatus?: OperatingMetricsStatus): string {
  const baseStatus = status === "success" ? "成功" : status === "failed" ? "失败" : "采集中";
  return `${baseStatus} · 经营${operatingStatus === undefined ? "未采集" : operatingStatusLabels[operatingStatus]}`;
}

function operatingMetricPresentation(metric: OperatingMetric, latestRun?: LatestCollectionRun | null) {
  const attempt = metric.latest_attempt;
  const currentAttempt = attempt && latestRun && attempt.collection_run_id === latestRun.id ? attempt : null;
  const valid = metric.latest_valid;
  const attemptHasValue = attempt?.status === "observed" && !!attempt.raw_value?.trim();
  const currentRead = currentAttempt?.status === "observed" && !!currentAttempt.raw_value?.trim();
  const sameObservedValue = !!attempt && !!valid && attempt.collection_run_id === valid.collection_run_id
    && attempt.status === "observed" && !!attempt.raw_value?.trim() && attempt.raw_value === valid.raw_value;
  const hasHistoricalValue = !!valid && !!latestRun && valid.collection_run_id !== latestRun.id;
  const value = attemptHasValue ? attempt.raw_value! : valid?.raw_value ?? null;
  const status = currentRead ? "本次有效值"
    : hasHistoricalValue ? "历史有效值"
      : !attempt ? valid ? "有效值记录" : "尚未采集"
        : latestRun && attempt.collection_run_id !== latestRun.id ? "最近字段记录（历史）"
          : attempt.status === "observed" ? "有效值记录" : metricAttemptLabels[attempt.status];
  const records = [];
  if (attempt) records.push({
    label: sameObservedValue ? (currentAttempt ? "本次有效值" : latestRun ? "最近字段记录（历史）" : "有效值记录")
      : currentAttempt ? "最近一次字段尝试" : latestRun ? "最近字段记录（历史）" : "最近字段记录",
    status: metricAttemptLabels[attempt.status], rawValue: attempt.raw_value,
    source: attempt.source, observedAt: attempt.observed_at, runId: attempt.collection_run_id, reason: attempt.reason,
  });
  if (valid && !sameObservedValue) records.push({
    label: hasHistoricalValue ? "历史有效值" : "有效值记录",
    status: null, rawValue: valid.raw_value, source: valid.source,
    observedAt: valid.observed_at, runId: valid.collection_run_id, reason: null,
  });
  return { attempt, currentAttempt, value, status, valueKind: currentRead ? "本次有效值" : hasHistoricalValue ? "历史有效值" : valid || attemptHasValue ? "有效值记录" : "暂无有效值", records };
}

function OperatingMetricsPanel({ metrics = [], latestRun }: { metrics?: OperatingMetric[]; latestRun?: LatestCollectionRun | null }) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const eligibleMetrics = metrics.filter(metric => metric.eligible && metric.section !== "平台标签");
  const groups = [
    { key: "经营表现", title: "成交表现" },
    { key: "口碑履约", title: "口碑与履约" },
  ] as const;
  const selected = eligibleMetrics.find(metric => metric.metric_key === selectedKey) ?? null;
  const toggleMetric = (metricKey: string) => setSelectedKey(current => current === metricKey ? null : metricKey);
  const evidenceId = "operating-metric-evidence";
  const evidence = selected ? operatingMetricPresentation(selected, latestRun) : null;

  return <section className="table-card detail-section-card operating-metrics-panel" aria-label="经营数据">
    <div className="table-heading"><div><h2>经营数据</h2><span>1688 官方采购助手 · 保留页面原始值</span></div><button type="button" className="text-button operating-evidence-toggle" aria-expanded={!!selected} aria-controls={evidenceId} onClick={() => setSelectedKey(current => current ? null : eligibleMetrics[0]?.metric_key ?? null)}>{selected ? "收起数据依据" : "查看数据依据"}</button></div>
    <div className="operating-metric-groups">{groups.map(group => <div className="operating-metric-group" key={group.key}><h3>{group.title}</h3><div className={`operating-metric-grid operating-metric-grid-${group.key === "经营表现" ? "deals" : "service"}`}>{eligibleMetrics.filter(metric => metric.section === group.key).map(metric => {
      const presentation = operatingMetricPresentation(metric, latestRun);
      const selectedCard = selectedKey === metric.metric_key;
      const showAttemptStatus = !!metric.latest_valid && !!presentation.currentAttempt && presentation.currentAttempt.status !== "observed";
      return <button key={metric.metric_key} type="button" className={`operating-metric-card${selectedCard ? " operating-metric-card-selected" : ""}`} aria-expanded={selectedCard} aria-controls={evidenceId} onClick={() => toggleMetric(metric.metric_key)}>
        <span className="operating-metric-label">{metric.label}</span><strong>{presentation.value ?? "暂无有效值"}</strong><span className={`operating-metric-status operating-status-${presentation.status === "本次有效值" ? "read" : presentation.status.includes("历史") ? "history" : presentation.status === "读取失败" || presentation.status === "来源不可用" ? "warning" : "neutral"}`}>{presentation.status}</span>
        {showAttemptStatus && <span className="operating-metric-latest-status">本次：{metricAttemptLabels[presentation.currentAttempt!.status]}</span>}
      </button>;
    })}</div></div>)}</div>
    {selected && evidence && <section className="operating-metric-evidence" id={evidenceId} role="region" aria-label={`${selected.label}数据依据`}>
      <header><div><h3>{selected.label} · 数据依据</h3><span>当前展示：{evidence.value ?? "暂无有效值"} · {evidence.valueKind}</span></div><button type="button" className="text-button" onClick={() => setSelectedKey(null)}>收起</button></header>
      {evidence.records.length ? <div className={`operating-evidence-records operating-evidence-records-${evidence.records.length > 1 ? "multiple" : "single"}`}>{evidence.records.map((record, index) => <div className="operating-evidence-record" key={`${record.label}-${record.runId}-${index}`}>
        <strong>{record.label}</strong><dl>
          {record.status && <><dt>状态</dt><dd>{record.status}</dd></>}
          <dt>{record.status ? "页面原值" : "原值"}</dt><dd>{record.rawValue ?? "—"}</dd>
          {record.reason && <><dt>原因</dt><dd>{record.reason}</dd></>}
          <dt>来源</dt><dd>{operatingMetricSource(record.source)}</dd>
          <dt>观察时间</dt><dd>{formatDate(record.observedAt)}</dd>
          <dt>CollectionRun ID</dt><dd>#{record.runId}</dd>
        </dl>
      </div>)}</div> : <p className="operating-evidence-empty">{evidence.attempt?.reason ? `原因：${evidence.attempt.reason}` : "尚未采集该字段"} · 暂无有效值</p>}
    </section>}
  </section>;
}
function operatingMetricValue(product: GroupProductFacts, metricKey: string): string {
  const metric = product.operating_metrics?.find(item => item.metric_key === metricKey);
  if (!metric) return "未采集";
  if (!metric.eligible) return "待接入";
  const attempt = metric.latest_attempt;
  if (!attempt) return "未采集";
  if (attempt.status === "observed") return attempt.raw_value?.trim() || "—";
  if (attempt.status === "placeholder") return attempt.raw_value?.trim() || "-";
  return attempt.status === "loading" ? "仍在加载" : attempt.status === "source_unavailable" ? "来源不可用" : "读取失败";
}

function parseOperatingMetricSortValue(raw: string | null | undefined, metricKey: OperatingMetricSortKey): { value: number; boundary: number } | null {
  const normalized = raw?.trim();
  if (!normalized || normalized === "-") return null;
  if (metricKey === "listing_time") {
    const time = Date.parse(normalized);
    return Number.isFinite(time) ? { value: time, boundary: 0 } : null;
  }
  const threshold = metricKey === "monthly_deal" || metricKey === "monthly_dropship" || metricKey === "annual_units" || metricKey === "annual_orders";
  const number = "(?:\\d{1,3}(?:,\\d{3})+|\\d+)(?:\\.\\d+)?";
  const value = normalized.match(threshold ? new RegExp(`^([<>]?)(${number})(\\+)?$`) : new RegExp(`^(${number})\\s*%?$`));
  if (!value || (threshold && value[1] && value[3])) return null;
  const parsed = Number(value[threshold ? 2 : 1].replaceAll(",", ""));
  const boundary = !threshold ? 0 : value[1] === "<" ? 0 : value[1] === ">" ? 2 : value[3] ? 3 : 1;
  return Number.isFinite(parsed) ? { value: parsed, boundary } : null;
}

function operatingMetricSortValue(product: GroupProductFacts, metricKey: OperatingMetricSortKey): { value: number; boundary: number } | null {
  const metric = product.operating_metrics?.find(item => item.metric_key === metricKey);
  const raw = metric?.eligible && metric.latest_attempt?.status === "observed" ? metric.latest_attempt.raw_value : null;
  return parseOperatingMetricSortValue(raw, metricKey);
}

export function sortGroupOffersByOperatingMetric(offers: GroupProductFacts[], metricKey: OperatingMetricSortKey, direction: "asc" | "desc"): GroupProductFacts[] {
  return [...offers].sort((a, b) => {
    const left = operatingMetricSortValue(a, metricKey), right = operatingMetricSortValue(b, metricKey);
    if ((left === null) !== (right === null)) return left === null ? 1 : -1;
    if (left === null || right === null) return a.id - b.id;
    return (direction === "asc" ? left.value - right.value || left.boundary - right.boundary : right.value - left.value || right.boundary - left.boundary) || a.id - b.id;
  });
}

function groupShopLink(product: GroupProductFacts) {
  const shopName = product.shop_name?.trim() || "店铺未采集";
  try {
    const { protocol } = new URL(product.url);
    if (protocol === "http:" || protocol === "https:") return <a className="position-shop position-shop-link" href={product.url} target="_blank" rel="noopener noreferrer" onClick={event => event.stopPropagation()}>{shopName}</a>;
  } catch {
    // Invalid or relative product URLs remain plain shop names.
  }
  return <span className="position-shop">{shopName}</span>;
}

export function sortGroupOffers(offers: GroupProductFacts[], position: MetricPosition | undefined, direction: "asc" | "desc"): GroupProductFacts[] {
  return [...offers].sort((a, b) => {
    const left = position?.offers[a.id], right = position?.offers[b.id];
    if (Boolean(left?.eligible) !== Boolean(right?.eligible)) return left?.eligible ? -1 : 1;
    // Backend ranks preserve Decimal precision and competition ties in both directions.
    const rankKey = direction === "asc" ? "rank_asc" : "rank_desc";
    return left?.eligible && right?.eligible ? (left[rankKey]! - right[rankKey]!) || a.id - b.id : a.id - b.id;
  });
}

export function groupEventSummaries(events: GroupEventPage["items"]) {
  const groups = new Map<string, GroupEventPage["items"]>();
  for (const event of events) {
    const relation = event.collection_run_id != null ? `run:${event.collection_run_id}`
      : event.snapshot_id != null ? `snapshot:${event.snapshot_id}` : `event:${event.id}`;
    const key = JSON.stringify([event.competitor_id, event.offer_id, relation, event.change_type]);
    const group = groups.get(key);
    if (group) group.push(event);
    else groups.set(key, [event]);
  }
  return [...groups].map(([key, items]) => ({ key, items }));
}

export function groupEventSummaryLabel(events: GroupEventPage["items"]): string {
  if (events.length === 1) return formatChange(events[0]);
  const skuCount = new Set(events.filter(event => event.entity_key).map(event => event.entity_key)).size;
  const hasProduct = events.some(event => !event.entity_key);
  const actions: Record<string, string> = {
    price_decrease: "降价", price_increase: "涨价", min_order_quantity_increase: "起批量增加", min_order_quantity_decrease: "起批量降低",
    sku_added: "新增", sku_removed: "移除", stock_changed: "库存变化", stock_increase: "库存增加",
    stock_decrease: "库存下降", sku_sold_out: "售罄", sku_restocked: "恢复有货",
    product_offline: "下架", product_online: "恢复上架", title_changed: "标题变化", main_image_changed: "主图变化",
  };
  const action = actions[events[0].change_type] ?? events[0].change_type;
  return `${hasProduct ? `商品${action}` : ""}${hasProduct && skuCount ? "，涉及 " : ""}${skuCount ? `${skuCount} 个 SKU${hasProduct ? "" : ` ${action}`}` : ""} · ${events.length} 条原始变化`;
}

type AdvancedFilterField = "shop_name" | "title" | "offer_id" | "price_min" | "price_max" | "min_order_quantity" | "sku_count" | "total_stock" | OperatingMetricSortKey | "has_reviews";
type AdvancedFilterOperator = "contains" | "not_contains" | "equals" | "not_equals" | "gt" | "gte" | "lt" | "lte" | "between" | "has_value" | "no_value" | "before" | "after" | "date_between" | "raw_equals" | "raw_not_equals" | "has_reviews" | "no_reviews";
export type AdvancedFilterRule = { id: number; field: AdvancedFilterField; operator: AdvancedFilterOperator; value: string; value2: string };
type FilterVerdict = "match" | "no_match" | "unknown";
type AdvancedFilterFieldDefinition = { label: string; kind: "text" | "number" | "integer" | "percent" | "date" | "bucket" | "reviews"; metricKey?: OperatingMetricSortKey };

const advancedFilterFields: Record<AdvancedFilterField, AdvancedFilterFieldDefinition> = {
  shop_name: { label: "店铺名称", kind: "text" }, title: { label: "商品名称", kind: "text" }, offer_id: { label: "Offer ID", kind: "text" },
  price_min: { label: "展示报价下限", kind: "number" }, price_max: { label: "展示报价上限", kind: "number" }, min_order_quantity: { label: "MOQ", kind: "integer" }, sku_count: { label: "SKU 数", kind: "integer" }, total_stock: { label: "完整库存", kind: "integer" },
  listing_time: { label: "上架时间", kind: "date", metricKey: "listing_time" }, monthly_deal: { label: "月成交", kind: "bucket", metricKey: "monthly_deal" }, monthly_dropship: { label: "月代销", kind: "bucket", metricKey: "monthly_dropship" }, annual_units: { label: "年成交件数", kind: "bucket", metricKey: "annual_units" }, annual_orders: { label: "年成交笔数", kind: "bucket", metricKey: "annual_orders" },
  review_count: { label: "评论数", kind: "integer", metricKey: "review_count" }, positive_rate: { label: "好评率", kind: "percent", metricKey: "positive_rate" }, pickup_rate: { label: "揽收率", kind: "percent", metricKey: "pickup_rate" }, has_reviews: { label: "是否有评价", kind: "reviews", metricKey: "review_count" },
};
const advancedFilterOperators: Record<AdvancedFilterFieldDefinition["kind"], { value: AdvancedFilterOperator; label: string }[]> = {
  text: [{ value: "contains", label: "包含" }, { value: "not_contains", label: "不包含" }, { value: "equals", label: "等于" }],
  number: [{ value: "equals", label: "等于" }, { value: "not_equals", label: "不等于" }, { value: "gt", label: "大于" }, { value: "gte", label: "大于等于" }, { value: "lt", label: "小于" }, { value: "lte", label: "小于等于" }, { value: "between", label: "介于" }, { value: "has_value", label: "有有效值" }, { value: "no_value", label: "无有效值" }],
  integer: [{ value: "equals", label: "等于" }, { value: "not_equals", label: "不等于" }, { value: "gt", label: "大于" }, { value: "gte", label: "大于等于" }, { value: "lt", label: "小于" }, { value: "lte", label: "小于等于" }, { value: "between", label: "介于" }, { value: "has_value", label: "有有效值" }, { value: "no_value", label: "无有效值" }],
  percent: [{ value: "equals", label: "等于" }, { value: "not_equals", label: "不等于" }, { value: "gt", label: "大于" }, { value: "gte", label: "大于等于" }, { value: "lt", label: "小于" }, { value: "lte", label: "小于等于" }, { value: "between", label: "介于" }, { value: "has_value", label: "有有效值" }, { value: "no_value", label: "无有效值" }],
  date: [{ value: "before", label: "早于" }, { value: "after", label: "晚于" }, { value: "date_between", label: "介于日期范围" }],
  bucket: [{ value: "raw_equals", label: "原始档位为" }, { value: "raw_not_equals", label: "原始档位不为" }, { value: "gt", label: "确定大于" }, { value: "gte", label: "确定大于等于" }, { value: "lt", label: "确定小于" }, { value: "lte", label: "确定小于等于" }, { value: "has_value", label: "有有效值" }, { value: "no_value", label: "无有效值" }],
  reviews: [{ value: "has_reviews", label: "有评价" }, { value: "no_reviews", label: "无评价" }],
};
const isValueOperator = (operator: AdvancedFilterOperator) => !["has_value", "no_value", "has_reviews", "no_reviews"].includes(operator);
const ruleLabel = (rule: AdvancedFilterRule) => `${advancedFilterFields[rule.field].label} ${advancedFilterOperators[advancedFilterFields[rule.field].kind].find(option => option.value === rule.operator)?.label ?? rule.operator}${isValueOperator(rule.operator) ? ` ${rule.value}${["between", "date_between"].includes(rule.operator) ? ` 至 ${rule.value2}` : ""}` : ""}`;
const numberInput = (value: string) => value.trim() !== "" && Number.isFinite(Number(value));
const bucketThresholdOperator = (operator: AdvancedFilterOperator) => ["gt", "gte", "lt", "lte"].includes(operator);
const dateInput = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number), date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? date.getTime() : null;
};

export function validateAdvancedFilters(rules: AdvancedFilterRule[]): string | null {
  for (const rule of rules) {
    const definition = advancedFilterFields[rule.field];
    if (!isValueOperator(rule.operator)) continue;
    if (definition.kind === "text") {
      if (!rule.value.trim()) return `${definition.label}需要输入筛选值。`;
      continue;
    }
    if (definition.kind === "bucket") {
      if (rule.operator === "raw_equals" || rule.operator === "raw_not_equals") {
        if (!rule.value.trim()) return `${definition.label}需要输入原始档位。`;
      } else if (!/^\d+$/.test(rule.value)) return `${definition.label}需要非负整数阈值。`;
      continue;
    }
    if (definition.kind === "date") {
      const first = dateInput(rule.value), second = rule.operator === "date_between" ? dateInput(rule.value2) : 0;
      if (first === null || (rule.operator === "date_between" && second === null)) return `${definition.label}需要有效日期。`;
      if (rule.operator === "date_between" && first > second!) return `${definition.label}的开始日期不能晚于结束日期。`;
      continue;
    }
    if (!numberInput(rule.value) || (rule.operator === "between" && !numberInput(rule.value2))) return `${definition.label}需要有效数值。`;
    if ([rule.value, rule.value2].filter(Boolean).some(value => Number(value) < 0)) return `${definition.label}不能小于 0。`;
    if (definition.kind === "integer" && (![rule.value, rule.value2].filter(Boolean).every(value => /^\d+$/.test(value)))) return `${definition.label}只能输入整数。`;
    if (definition.kind === "percent" && [rule.value, rule.value2].filter(Boolean).some(value => Number(value) < 0 || Number(value) > 100)) return `${definition.label}必须介于 0% 和 100% 之间。`;
    if (rule.operator === "between" && Number(rule.value) > Number(rule.value2)) return `${definition.label}的起始值不能大于结束值。`;
  }
  return null;
}

function metricRawValue(product: GroupProductFacts, key: OperatingMetricSortKey): string | null {
  const metric = product.operating_metrics?.find(item => item.metric_key === key);
  return metric?.eligible && metric.latest_attempt?.status === "observed" ? metric.latest_attempt.raw_value?.trim() || null : null;
}
function numericRuleVerdict(value: number | null, rule: AdvancedFilterRule): FilterVerdict {
  if (rule.operator === "has_value") return value === null ? "no_match" : "match";
  if (rule.operator === "no_value") return value === null ? "match" : "no_match";
  if (value === null) return "unknown";
  const first = Number(rule.value), second = Number(rule.value2);
  if (!Number.isFinite(first) || first < 0 || (rule.operator === "between" && (!Number.isFinite(second) || second < 0))) return "no_match";
  if (rule.operator === "between" && first > second) return "no_match";
  if (rule.operator === "equals") return value === first ? "match" : "no_match";
  if (rule.operator === "not_equals") return value !== first ? "match" : "no_match";
  if (rule.operator === "gt") return value > first ? "match" : "no_match";
  if (rule.operator === "gte") return value >= first ? "match" : "no_match";
  if (rule.operator === "lt") return value < first ? "match" : "no_match";
  if (rule.operator === "lte") return value <= first ? "match" : "no_match";
  return value >= first && value <= second ? "match" : "no_match";
}
function bucketRuleVerdict(raw: string | null, rule: AdvancedFilterRule): FilterVerdict {
  if (!raw) return rule.operator === "no_value" ? "match" : rule.operator === "has_value" ? "no_match" : "unknown";
  if (rule.operator === "raw_equals") return raw === rule.value ? "match" : "no_match";
  if (rule.operator === "raw_not_equals") return raw !== rule.value ? "match" : "no_match";
  const parsed = parseOperatingMetricSortValue(raw, "monthly_deal");
  const threshold = Number(rule.value);
  if (!parsed || !Number.isFinite(threshold)) return rule.operator === "has_value" || rule.operator === "no_value" ? rule.operator === "no_value" ? "match" : "no_match" : "unknown";
  if (rule.operator === "has_value") return "match";
  if (rule.operator === "no_value") return "no_match";
  if (threshold < 0) return "no_match";
  const lower = parsed.boundary === 0 ? -Infinity : parsed.value;
  const upper = parsed.boundary === 0 ? parsed.value : parsed.boundary === 1 ? parsed.value : Infinity;
  const lowerInclusive = parsed.boundary === 1 || parsed.boundary === 3;
  const upperInclusive = parsed.boundary === 1;
  if (rule.operator === "gt") return lower > threshold || (lower === threshold && !lowerInclusive) ? "match" : upper <= threshold ? "no_match" : "unknown";
  if (rule.operator === "gte") return lower >= threshold ? "match" : upper < threshold || (upper === threshold && !upperInclusive) ? "no_match" : "unknown";
  if (rule.operator === "lt") return upper < threshold || (upper === threshold && !upperInclusive) ? "match" : lower >= threshold ? "no_match" : "unknown";
  return upper <= threshold ? "match" : lower > threshold || (lower === threshold && !lowerInclusive) ? "no_match" : "unknown";
}
export function evaluateAdvancedFilterRule(product: GroupProductFacts, rule: AdvancedFilterRule): FilterVerdict {
  const definition = advancedFilterFields[rule.field];
  if (definition.kind === "text") {
    const value = String(product[rule.field as "shop_name" | "title" | "offer_id"] ?? "").toLocaleLowerCase(), target = rule.value.toLocaleLowerCase();
    if (!target) return "no_match";
    return rule.operator === "contains" ? value.includes(target) ? "match" : "no_match" : rule.operator === "not_contains" ? value.includes(target) ? "no_match" : "match" : value === target ? "match" : "no_match";
  }
  if (definition.kind === "reviews") {
    const value = operatingMetricSortValue(product, "review_count")?.value ?? null;
    if (value === null) return "unknown";
    return (rule.operator === "has_reviews" ? value > 0 : value === 0) ? "match" : "no_match";
  }
  if (definition.kind === "bucket") return bucketRuleVerdict(metricRawValue(product, definition.metricKey!), rule);
  if (definition.kind === "date") {
    const raw = metricRawValue(product, definition.metricKey!), value = raw ? dateInput(raw) : null;
    const first = dateInput(rule.value), second = dateInput(rule.value2);
    if (value === null) return "unknown";
    if (first === null || (rule.operator === "date_between" && second === null)) return "no_match";
    return rule.operator === "before" ? value < first ? "match" : "no_match" : rule.operator === "after" ? value > first + 86_399_999 ? "match" : "no_match" : value >= first && value <= second! + 86_399_999 ? "match" : "no_match";
  }
  const snapshot = product.latest_snapshot;
  const basic = rule.field === "price_min" ? snapshot?.price_min : rule.field === "price_max" ? snapshot?.price_max : rule.field === "min_order_quantity" ? snapshot?.min_order_quantity : rule.field === "sku_count" ? snapshot?.sku_count : rule.field === "total_stock" ? snapshot?.total_stock : null;
  const raw = definition.metricKey ? metricRawValue(product, definition.metricKey) : basic;
  if (definition.kind === "integer" && (rule.value && !/^\d+$/.test(rule.value) || rule.value2 && !/^\d+$/.test(rule.value2))) return "no_match";
  const parsed = definition.metricKey ? operatingMetricSortValue(product, definition.metricKey)?.value ?? null : raw === null || raw === undefined ? null : Number(String(raw).replaceAll(",", "").replace(/%$/, ""));
  return numericRuleVerdict(Number.isFinite(parsed) ? parsed : null, rule);
}
export function evaluateAdvancedFilters(product: GroupProductFacts, rules: AdvancedFilterRule[]): FilterVerdict {
  let uncertain = false;
  for (const rule of rules) { const verdict = evaluateAdvancedFilterRule(product, rule); if (verdict === "no_match") return "no_match"; if (verdict === "unknown") uncertain = true; }
  return uncertain ? "unknown" : "match";
}

function AdvancedFilterEditor({ rules, error, onChange, onApply, onReset }: { rules: AdvancedFilterRule[]; error: string | null; onChange: (rules: AdvancedFilterRule[]) => void; onApply: () => void; onReset: () => void }) {
  const update = (id: number, patch: Partial<AdvancedFilterRule>) => onChange(rules.map(rule => rule.id === id ? { ...rule, ...patch } : rule));
  const add = () => { const field: AdvancedFilterField = "shop_name"; onChange([...rules, { id: Date.now(), field, operator: "contains", value: "", value2: "" }]); };
  return <details className="advanced-filter-panel"><summary>高级筛选{rules.length ? `（草稿 ${rules.length}）` : ""}</summary><div className="advanced-filter-body"><p>所有条件同时满足。成交档位仅在结论确定时进入匹配；其余会单独列出。</p>{error && <p role="alert" className="feedback feedback-server-error advanced-filter-error">{error}</p>}{rules.map(rule => { const definition = advancedFilterFields[rule.field], needsValue = isValueOperator(rule.operator), range = rule.operator === "between" || rule.operator === "date_between", numeric = ["number", "integer", "percent"].includes(definition.kind) || definition.kind === "bucket" && bucketThresholdOperator(rule.operator), inputType = definition.kind === "date" ? "date" : numeric ? "number" : "text", step = definition.kind === "integer" || definition.kind === "bucket" && bucketThresholdOperator(rule.operator) ? "1" : numeric ? "any" : undefined; const valueInput = (label: string, value: string, onChange: (value: string) => void) => <span className="advanced-filter-value"><input aria-label={label} type={inputType} min={numeric ? "0" : undefined} step={step} inputMode={numeric ? "decimal" : undefined} placeholder={definition.kind === "percent" ? "百分比" : definition.kind === "bucket" ? bucketThresholdOperator(rule.operator) ? "非负整数" : "如 100+ 或 100" : "输入值"} value={value} onChange={event => onChange(event.target.value)} />{definition.kind === "percent" && <span aria-hidden="true">%</span>}</span>; return <div className="advanced-filter-rule" key={rule.id}><select aria-label="筛选字段" value={rule.field} onChange={event => { const field = event.target.value as AdvancedFilterField; update(rule.id, { field, operator: advancedFilterOperators[advancedFilterFields[field].kind][0].value, value: "", value2: "" }); }}>{Object.entries(advancedFilterFields).map(([key, item]) => <option value={key} key={key}>{item.label}</option>)}</select><select aria-label="筛选操作符" value={rule.operator} onChange={event => update(rule.id, { operator: event.target.value as AdvancedFilterOperator })}>{advancedFilterOperators[definition.kind].map(option => <option value={option.value} key={option.value}>{option.label}</option>)}</select>{needsValue && valueInput("筛选值", rule.value, value => update(rule.id, { value }))}{range && valueInput("筛选第二个值", rule.value2, value => update(rule.id, { value2: value }))}<button type="button" className="text-button" onClick={() => onChange(rules.filter(item => item.id !== rule.id))}>删除</button></div>; })}<div className="advanced-filter-actions"><button type="button" className="text-button" onClick={add}>添加条件</button><span /><button type="button" className="secondary-button" onClick={onReset}>重置</button><button type="button" className="primary-button" onClick={onApply}>应用筛选</button></div></div></details>;
}

export function updateGroupOfferAfterLifecycle(data: GroupDetailData, id: number, deleted: boolean): GroupDetailData {
  return { ...data, own_product: data.own_product?.id === id ? (deleted ? null : { ...data.own_product, is_active: false }) : data.own_product, competitors: deleted ? data.competitors.filter(item => item.id !== id) : data.competitors.map(item => item.id === id ? { ...item, is_active: false } : item) };
}

export function GroupDetailPage({ data, status, error, days, rangeLoading, rangeError, onRetry, onRangeChange, onBack, onViewCompetitors, onOpenDetail, onNavigate, onAdd = noop, onOfferAction = noop, offerActionBusy = false }: {
  data: GroupDetailData | null; status: DetailStatus; error: string | null; days: 7 | 30; rangeLoading: boolean; rangeError: string | null;
  onOfferAction?: (action: "stop" | "delete", product: LifecycleCompetitor) => void; offerActionBusy?: boolean; onAdd?: (groupId: number) => void; onRetry: () => void; onRangeChange: (days: 7 | 30) => void; onBack: () => void; onViewCompetitors: (groupId: number) => void; onOpenDetail: (competitorId: number) => void; onNavigate: (page: Page) => void;
}) {
  const own = data?.own_product ?? null;
  const allOffers = [...(own ? [own] : []), ...(data?.competitors ?? [])];
  const currentOffers = allOffers.filter(product => product.is_active === true && product.status !== "offline");
  const fallbackSelected = currentOffers.find(product => product.id === own?.id) ?? currentOffers[0] ?? null;
  const [workspaceView, setWorkspaceView] = useState("竞品动态");
  const [view, setView] = useState<string>("竞争总览");
  const [metric, setMetric] = useState<PositionMetric>("min_order_quantity");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [operatingSort, setOperatingSort] = useState<Partial<Record<OperatingMetricView, { key: OperatingMetricSortKey; direction: "asc" | "desc" }>>>({});
  const [overviewOperatingKey, setOverviewOperatingKey] = useState<OperatingMetricSortKey | null>(null);
  const [search, setSearch] = useState("");
  const [importantOnly, setImportantOnly] = useState(false);
  const [draftAdvancedFilters, setDraftAdvancedFilters] = useState<AdvancedFilterRule[]>([]);
  const [appliedAdvancedFilters, setAppliedAdvancedFilters] = useState<AdvancedFilterRule[]>([]);
  const [advancedFilterError, setAdvancedFilterError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [page, setEventPage] = useState<GroupEventPage | null>(data?.event_page ?? null);
  const [eventLoading, setEventLoading] = useState(false);
  const [eventError, setEventError] = useState<string | null>(null);
  const [failedEventRequest, setFailedEventRequest] = useState<{ range: GroupEventPage["range"]; mode: GroupEventPage["mode"]; append: boolean } | null>(null);
  const [evidence, setEvidence] = useState<GroupTodayEvent | null>(null);
  const eventGroupId = useRef<number | null>(null);
  const [locateNotice, setLocateNotice] = useState(false);
  const [highlightOwn, setHighlightOwn] = useState(false);
  const requestId = useRef(0);
  const eventBusy = useRef(false);
  const ownRow = useRef<HTMLTableRowElement>(null);
  const locateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { setWorkspaceView("竞品动态"); setSelectedId(fallbackSelected?.id ?? null); setView("竞争总览"); setMetric("min_order_quantity"); setDirection("asc"); setOverviewOperatingKey(null); setOperatingSort({}); setSearch(""); setImportantOnly(false); setDraftAdvancedFilters([]); setAppliedAdvancedFilters([]); setAdvancedFilterError(null); setEvidence(null); setLocateNotice(false); }, [data?.group.id]);
  useEffect(() => { setSelectedId(current => currentOffers.some(product => product.id === current) ? current : fallbackSelected?.id ?? null); }, [data]);
  useEffect(() => { if (data && eventGroupId.current === data.group.id && eventBusy.current) return; requestId.current++; eventBusy.current = false; setEventPage(null); setEventLoading(false); setEventError(null); setFailedEventRequest(null); setEvidence(null); if (data && eventGroupId.current !== data.group.id) { eventGroupId.current = data.group.id; void loadEvents("today", "important"); } else setEventPage(data?.event_page ?? null); }, [data]);
  useEffect(() => { if (rangeLoading) { requestId.current++; eventBusy.current = false; setEventLoading(false); } }, [rangeLoading]);
  useEffect(() => () => { requestId.current++; if (locateTimer.current) clearTimeout(locateTimer.current); }, []);
  async function loadEvents(range: GroupEventPage["range"], mode: GroupEventPage["mode"], append = false) {
    if (!data || (append && eventBusy.current) || rangeLoading) return;
    const id = ++requestId.current;
    eventBusy.current = true; setEventLoading(true); setEventError(null); setFailedEventRequest(null);
    const params = new URLSearchParams({ range, mode, limit: String(append ? page?.limit ?? 20 : 20) });
    if (append && page?.next_cursor) params.set("cursor", page.next_cursor);
    try {
      const response = await fetch(`/api/competitor-groups/${data.group.id}/events?${params}`);
      if (!response.ok) { const body = await response.json(); throw new Error(response.status === 409 ? "组成员或角色已变化，请重新加载当前历史" : body.message || "历史加载失败，请重试"); }
      const next = await response.json() as GroupEventPage;
      if (id !== requestId.current) return;
      setEventPage(append ? { ...next, items: [...(page?.items ?? []), ...next.items.filter(item => !page?.items.some(old => old.id === item.id))] } : next);
      setEvidence(null);
    } catch (failure) { if (id === requestId.current) { setEventError(failure instanceof Error ? failure.message : "历史加载失败"); setFailedEventRequest({ range, mode, append }); } }
    finally { if (id === requestId.current) { eventBusy.current = false; setEventLoading(false); } }
  }
  const clearFilters = () => { setSearch(""); setImportantOnly(false); setDraftAdvancedFilters([]); setAppliedAdvancedFilters([]); setAdvancedFilterError(null); };
  const locate = () => {
    if (!own) return;
    setSelectedId(own.id);
    if (!ownRow.current) { setLocateNotice(true); return; }
    const container = ownRow.current.closest<HTMLElement>(".main-content");
    if (container) container.scrollTop += ownRow.current.getBoundingClientRect().top - container.getBoundingClientRect().top - (container.clientHeight - ownRow.current.offsetHeight) / 2;
    setLocateNotice(false); setHighlightOwn(true);
    if (locateTimer.current) clearTimeout(locateTimer.current);
    locateTimer.current = setTimeout(() => setHighlightOwn(false), 1800);
  };
  useEffect(() => { if (locateNotice && !search && !importantOnly && !appliedAdvancedFilters.length) locate(); }, [search, importantOnly, appliedAdvancedFilters.length, locateNotice]);
  if (status === "loading" && !data) return <AppShell page="group-detail" onNavigate={onNavigate} breadcrumb="竞品分组 / 组分析"><header className="page-header"><h1>组竞争分析</h1></header><div className="state-panel"><div className="spinner" /><strong>正在加载组分析…</strong></div></AppShell>;
  if (!data) return <AppShell page="group-detail" onNavigate={onNavigate} breadcrumb="竞品分组 / 组分析"><header className="page-header"><h1>组竞争分析</h1></header><div className="state-panel state-error"><strong>{error || "加载失败"}</strong><button className="secondary-button" onClick={onRetry}>重试</button><button className="secondary-button" onClick={onBack}>返回竞品分组</button></div></AppShell>;
  const needle = search.trim().toLocaleLowerCase();
  const operatingView = view === "经营表现" || view === "口碑履约" ? view : null;
  const currentOperatingSort = operatingView ? operatingSort[operatingView] : overviewOperatingKey ? operatingSort["经营表现"] : undefined;
  const activePosition = view === "竞争总览" && !overviewOperatingKey ? data.position[metric] : undefined;
  const sortedOffers = operatingView
    ? currentOperatingSort ? sortGroupOffersByOperatingMetric(currentOffers, currentOperatingSort.key, currentOperatingSort.direction) : [...currentOffers].sort((a, b) => a.id - b.id)
    : overviewOperatingKey && currentOperatingSort ? sortGroupOffersByOperatingMetric(currentOffers, overviewOperatingKey, currentOperatingSort.direction) : sortGroupOffers(currentOffers, activePosition, direction);
  const filterResults = sortedOffers.map(product => ({ product, verdict: evaluateAdvancedFilters(product, appliedAdvancedFilters) }));
  const visible = filterResults.filter(({ product, verdict }) => verdict === "match" && (!needle || [product.shop_name, product.title, product.offer_id].some(value => value?.toLocaleLowerCase().includes(needle))) && (!importantOnly || page?.important_offer_ids.includes(product.id))).map(({ product }) => product);
  const uncertain = filterResults.filter(({ product, verdict }) => verdict === "unknown" && (!needle || [product.shop_name, product.title, product.offer_id].some(value => value?.toLocaleLowerCase().includes(needle))) && (!importantOnly || page?.important_offer_ids.includes(product.id))).map(({ product }) => product);
  const selected = currentOffers.find(product => product.id === selectedId) ?? fallbackSelected;
  const hiddenOfferCount = allOffers.length - currentOffers.length;
  const ownExcluded = Boolean(own && !currentOffers.some(product => product.id === own.id));
  const operatingCoverageText = (selected?.operating_metrics ?? []).map(metric => {
    const coverage = data.operating_metrics_coverage?.[metric.metric_key];
    return coverage ? `${metric.label} ${coverage.has_history_valid_values}/${coverage.active_offers}` : null;
  }).filter(Boolean).join(" · ");
  const rankKey = direction === "asc" ? "rank_asc" : "rank_desc";
  const rankCounts = new Map<number, number>();
  for (const value of Object.values(activePosition?.offers ?? {})) {
    if (value.eligible && value[rankKey] !== null) rankCounts.set(value[rankKey]!, (rankCounts.get(value[rankKey]!) ?? 0) + 1);
  }
  const positionText = (product: GroupProductFacts, compact = false) => {
    if (!activePosition) return "当前视图指标待接入";
    const value = activePosition.offers[product.id];
    if (!value?.eligible) return positionReasons[value?.reason ?? "unknown_value"];
    const rank = value[rankKey]!;
    const label = `${(rankCounts.get(rank) ?? 0) > 1 ? "并列" : ""}第 ${rank} / ${activePosition.eligible_count}`;
    return compact ? label : `${label} 个可排名 Offer（${positionLabels[metric]} ${direction === "asc" ? "升序" : "降序"}）`;
  };
  const exclusions = (product: GroupProductFacts) => (Object.keys(positionLabels) as PositionMetric[]).flatMap(key => {
    const value = data.position[key].offers[product.id];
    return value?.eligible ? [] : [`${positionLabels[key]}：${positionReasons[value?.reason ?? "unknown_value"]}`];
  }).join("；");
  const rowDescription = (product: GroupProductFacts) => `${product.shop_name?.trim() || "店铺未采集"}\n${product.title || "商品名未采集"}\nOffer ID：${product.offer_id}\n快照时间：${formatDate(product.latest_snapshot?.captured_at ?? null)}\n状态：${product.status === "active" ? "在售" : product.status === "offline" ? "已下架" : "未知"} · ${product.is_active ? "监控中" : "已停止"}${exclusions(product) ? `\n排名排除：${exclusions(product)}` : ""}`;
  const previewPosition = (product: GroupProductFacts) => {
    if (view !== "竞争总览" || !activePosition) return null;
    const position = activePosition.offers[product.id];
    return position?.eligible ? <p className="position-preview-rank">{positionLabels[metric]}：{positionText(product, true)}</p> : null;
  };
  const columns: { title: string; metric?: PositionMetric; field?: "price" | "moq" | "sku" | "stock"; metric_key?: OperatingMetricSortKey }[] = view === "竞争总览" ? [{ title: "竞争力" }, { title: "展示报价", metric: "display_price_min", field: "price" }, { title: "MOQ", metric: "min_order_quantity", field: "moq" }, { title: "SKU", metric: "sku_count", field: "sku" }, { title: "库存", metric: "total_stock", field: "stock" }, { title: "月成交", metric_key: "monthly_deal" }, { title: "增长" }] : (pendingViews[view as keyof typeof pendingViews] ?? []).map(column => ({ ...column, metric_key: column.metric_key as OperatingMetricSortKey }));
  return <AppShell page="group-detail" onNavigate={onNavigate} breadcrumb={`竞品分组 / ${data.group.name}`}>
    <div className="position-workbench">
    <header className="page-header group-detail-page-header"><div><h1>{data.group.name} 竞争分析</h1><p className="page-description">当前参与对比 {currentOffers.length} 个商品 · 仅监控样本，非实时报价</p>{hiddenOfferCount > 0 && <p className="page-description">已隐藏 {hiddenOfferCount} 条下架或停监商品</p>}</div><div className="detail-page-actions"><button className="primary-button" onClick={() => onAdd(data.group.id)}>添加竞品</button><button className="secondary-button" onClick={onRetry}>刷新</button><button className="secondary-button" onClick={() => onViewCompetitors(data.group.id)}>查看竞品</button><button className="secondary-button" onClick={onBack}>返回竞品分组</button></div></header>
    {(error || rangeError) && <div className="feedback feedback-server-error" role="alert">更新失败，保留上一份事实：{error || rangeError}<button className="text-button" onClick={onRetry}>重试</button></div>}
    <div className="position-tabs position-workspace-tabs" role="tablist" aria-label="组分析视图">{["竞品动态", "商品对比"].map(tab => <button type="button" role="tab" id={tab === "竞品动态" ? "group-events-tab" : "group-comparison-tab"} aria-controls={tab === "竞品动态" ? "group-events-panel" : "group-comparison-panel"} aria-selected={workspaceView === tab} tabIndex={workspaceView === tab ? 0 : -1} className={workspaceView === tab ? "active" : ""} key={tab} onClick={() => setWorkspaceView(tab)} onKeyDown={event => {
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? "竞品动态" : event.key === "End" ? "商品对比" : tab === "竞品动态" ? "商品对比" : "竞品动态";
        setWorkspaceView(next);
        document.getElementById(next === "竞品动态" ? "group-events-tab" : "group-comparison-tab")?.focus();
      }
    }}>{tab}</button>)}</div>
    <section hidden={workspaceView !== "商品对比"} className="position-summaries">{[["组内经营景气信号", "证据不足", "不计算销量排名、增长或综合评分"], ["我方综合竞争力及组内位置", "待接入", "评分规则未冻结"], ["经营字段历史有效值", "八项原值已接入", operatingCoverageText ? `${operatingCoverageText}（按监控中 Offer 统计）` : "各 Offer 有效值覆盖将在采集后逐项显示"], ["当前经营决策提示", "证据不足", "先核查原值、时间与来源"]].map(([title, value, hint], index) => <article className="table-card" key={title}><span>{title}</span><strong>{value}</strong><small>{index === 1 && own ? ownExcluded ? "我方基准商品当前不可参与比较" : positionText(own) : hint}</small>{index === 1 && <small>{hint}</small>}</article>)}</section>
    <div className={`position-layout${workspaceView === "竞品动态" ? " position-layout-events" : ""}`}><div className="position-primary">
    <section hidden={workspaceView !== "商品对比"} role="tabpanel" id="group-comparison-panel" aria-labelledby="group-comparison-tab" className="table-card group-detail-section position-comparison"><div className="table-heading"><div><h2>商品横向竞争对比</h2><span>Offer 为比较单位，同店多个 Offer 分别保留</span></div><button className="secondary-button" disabled={!own || ownExcluded} onClick={locate}>定位我方</button></div>
    {!own && <p className="group-compact-empty">尚未绑定我方商品 · 未建立我方基准</p>}
    {own && ownExcluded && <p className="group-compact-empty">我方基准商品当前{own.status === "offline" ? "已下架" : "已停止监控"}{own.status === "offline" && !own.is_active ? "且已停止监控" : ""}，不参与比较；绑定关系保留。</p>}
    <div className="position-tabs" role="tablist" aria-label="对比视图">{["竞争总览", ...Object.keys(pendingViews)].map(tab => <button role="tab" aria-selected={view === tab} className={view === tab ? "active" : ""} key={tab} onClick={() => setView(tab)}>{tab}</button>)}</div>
    <div className="position-filters"><input aria-label="搜索店铺、商品或 Offer" placeholder="搜索店铺 / 商品 / Offer" value={search} onChange={event => setSearch(event.target.value)} /><label><input type="checkbox" checked={importantOnly} onChange={event => setImportantOnly(event.target.checked)} />仅看重要变化</label><AdvancedFilterEditor rules={draftAdvancedFilters} error={advancedFilterError} onChange={rules => { setDraftAdvancedFilters(rules); setAdvancedFilterError(null); }} onApply={() => { const validation = validateAdvancedFilters(draftAdvancedFilters); if (validation) { setAdvancedFilterError(validation); return; } setAppliedAdvancedFilters(draftAdvancedFilters); setAdvancedFilterError(null); }} onReset={() => { setDraftAdvancedFilters([]); setAppliedAdvancedFilters([]); setAdvancedFilterError(null); }} />{(search || importantOnly || appliedAdvancedFilters.length) && <button className="text-button" onClick={clearFilters}>清除筛选</button>}</div>
    {appliedAdvancedFilters.length > 0 && <div className="advanced-filter-summary" aria-label="已应用高级筛选">{appliedAdvancedFilters.map(rule => <span key={rule.id}>{ruleLabel(rule)}<button type="button" aria-label={`删除条件：${ruleLabel(rule)}`} onClick={() => { const next = appliedAdvancedFilters.filter(item => item.id !== rule.id); setAppliedAdvancedFilters(next); setDraftAdvancedFilters(next); }}>×</button></span>)}</div>}
    <p className="position-context">成交类指标按页面显示档位排序，保留原文，不代表精确销量或竞争排名。</p>
    {own && !ownExcluded && !visible.some(product => product.id === own.id) && <div className="position-filter-notice" role="status"><span><svg aria-hidden="true" viewBox="0 0 20 20"><circle cx="10" cy="10" r="7" /><path d="M10 9v5M10 6v1" /></svg>当前筛选未显示我方商品</span><button onClick={() => { setLocateNotice(true); clearFilters(); }}>清除筛选并定位</button></div>}
    <div className="table-scroll"><table className={view === "竞争总览" ? "position-table position-overview-table" : "position-table"}><thead><tr><th>店铺</th>{view === "竞争总览" && <th aria-sort="none"><span title="数据待接入，不能排序">平台标签 <small className="position-tag-pending">待接入</small></span></th>}{columns.map(column => {
      const positionSorted = Boolean(column.metric && activePosition && metric === column.metric);
      const metricSorted = Boolean(column.metric_key && currentOperatingSort?.key === column.metric_key);
      const sortDirection = positionSorted ? direction : metricSorted ? currentOperatingSort!.direction : undefined;
      return <th key={column.title} className={positionSorted || metricSorted ? "position-sorted" : ""} aria-sort={sortDirection ? sortDirection === "asc" ? "ascending" : "descending" : column.metric || column.metric_key ? "none" : undefined}>
        {column.metric ? <button onClick={() => { setOverviewOperatingKey(null); if (metric === column.metric) setDirection(direction === "asc" ? "desc" : "asc"); else { setMetric(column.metric!); setDirection(data.position[column.metric!].default_direction); } }}>{column.title}{positionSorted ? direction === "asc" ? " ↑" : " ↓" : " ↕"}</button> : column.metric_key ? <button onClick={() => { if (view === "竞争总览") setOverviewOperatingKey(column.metric_key!); setOperatingSort(current => {
          const sortView = operatingView ?? "经营表现";
          const active = current[sortView];
          return { ...current, [sortView]: { key: column.metric_key!, direction: active?.key === column.metric_key && active ? active.direction === "asc" ? "desc" : "asc" : operatingSortDefaults[column.metric_key!] } };
        }); }}>{column.title}{metricSorted ? currentOperatingSort!.direction === "asc" ? " ↑" : " ↓" : " ↕"}</button> : <span title="数据待接入，不能排序">{column.title}</span>}
      </th>;
    })}<th>操作</th></tr></thead><tbody>{visible.map(product => <tr key={product.id} data-offer-id={product.id} ref={product.id === own?.id ? ownRow : undefined} tabIndex={0} aria-label={rowDescription(product)} aria-selected={product.id === selected?.id} onClick={() => setSelectedId(product.id)} onKeyDown={event => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); setSelectedId(product.id); } }} className={(product.id === own?.id ? "position-own-row " : "") + (product.id === selected?.id ? "position-selected " : "") + (product.id === own?.id && highlightOwn ? "position-located" : "")}><td>{groupShopLink(product)}{product.status === "unknown" && <small className="position-status-unknown">状态未知</small>}</td>{view === "竞争总览" && <td className="position-tag-cell" aria-label={`平台标签待接入，Offer ${product.offer_id}`}>—</td>}{columns.map(column => <td key={column.title}>{column.metric_key ? <span className="position-metric-raw">{operatingMetricValue(product, column.metric_key)}</span> : column.field ? <button className="position-value" onClick={() => setSelectedId(product.id)} aria-label={`${column.title}字段依据 ${product.offer_id}`}>{groupSnapshotValue(product, column.field)}</button> : <span className="position-pending">待接入</span>}</td>)}<td><OfferMoreMenu product={product} isSelf={product.id === own?.id} busy={offerActionBusy} onOpenDetail={onOpenDetail} onAction={onOfferAction} /></td></tr>)}</tbody></table></div>
    {!visible.length && <p className="group-compact-empty">{currentOffers.length ? "没有符合条件的 Offer。" : "当前没有商品可参与比较。"}</p>}{uncertain.length > 0 && <details className="advanced-filter-uncertain"><summary>无法判断 {uncertain.length} 个 Offer</summary><p>这些记录没有把未知、占位符或读取失败当成数值，因此未混入确定匹配结果。</p><ul>{uncertain.map(product => <li key={product.id}>{product.shop_name || "店铺未采集"} · Offer {product.offer_id}</li>)}</ul></details>}<p className="position-context">确定匹配 {visible.length} · 无法判断 {uncertain.length} / 当前参与对比 {currentOffers.length} · 筛选不改变全组排名与分母</p></section>
    <section hidden={workspaceView !== "竞品动态"} role="tabpanel" id="group-events-panel" aria-labelledby="group-events-tab" className="table-card group-detail-section position-events"><div className="table-heading"><div><h2>竞争动态与可追溯变化</h2><span>全组 · 价格、MOQ、SKU 为重点，普通库存变化弱化</span></div></div><div className="position-event-controls">{(["today", "7", "30"] as const).map(range => <button className={page?.range === range ? "active" : ""} disabled={rangeLoading} aria-pressed={page?.range === range} key={range} onClick={() => { if (range !== "today") { requestId.current++; onRangeChange(Number(range) as 7 | 30); } else void loadEvents(range, "important"); }}>{range === "today" ? "今日" : `近 ${range} 天`}</button>)}{(["important", "all"] as const).map(mode => <button className={page?.mode === mode ? "active" : ""} disabled={rangeLoading} aria-pressed={page?.mode === mode} key={mode} onClick={() => void loadEvents(page?.range ?? String(days) as "7" | "30", mode)}>{mode === "important" ? "重点" : "全部"}</button>)}</div>
    {(eventLoading || rangeLoading) && <p role="status">正在更新历史范围，保留上一份事实…</p>}
    {eventError && <p role="alert">{eventError}<button className="text-button" onClick={() => { if (eventError.includes("角色")) void loadEvents(page?.range ?? "7", page?.mode ?? "important"); else if (failedEventRequest) void loadEvents(failedEventRequest.range, failedEventRequest.mode, failedEventRequest.append); }}>重试 / 重新加载</button></p>}
    {page && !page.items.length && <p className="group-compact-empty">{page.mode === "important" ? "当前窗口暂无重点事件，可查看全部变化" : "当前窗口暂无变化"}</p>}
    <ol className="position-event-list">{groupEventSummaries(page?.items ?? []).map(({ key, items }) => {
      const event = items[0];
      const original = (item: GroupEventPage["items"][number]) => <div className="position-event-original" key={item.id}><div><strong>{item.entity_key ? item.sku_name || `SKU ${item.entity_key}` : "商品级变化"}</strong><p>{formatChange(item)}</p><p>前值 {item.old_value ?? "未知"} → 后值 {item.new_value ?? "未知"}</p><small>检测时间 {formatDate(item.detected_at)}</small></div><button className="detail-button" onClick={() => setEvidence(item)}>变化证据</button></div>;
      return <li key={key} className={/^(price_|min_order_quantity_|sku_added|sku_removed)/.test(event.change_type) ? "important" : "ordinary"}><div className="position-event-summary"><strong>{event.shop_name || event.title || `Offer ${event.offer_id}`}</strong> <span>{event.role === "own" ? "我方" : "竞品"}{allOffers.some(product => product.id === event.competitor_id && !currentOffers.some(current => current.id === product.id)) ? " · 当前已下架或停监" : ""} · {groupEventSummaryLabel(items)}</span><small>检测时间 {formatDate(event.detected_at)} · Offer {event.offer_id}</small>{items.length > 1 ? <details><summary>展开 {items.length} 条原始变化</summary>{items.map(original)}</details> : original(event)}</div></li>;
    })}</ol>
    {page && <p className="position-context">已加载 {page.items.length} 条原始事件{page.has_more ? "，摘要数量仅代表已加载事件，仍有更多" : "，已加载当前窗口全部符合条件的事件"}{page.has_more && <button className="secondary-button" disabled={eventLoading || rangeLoading} onClick={() => void loadEvents(page.range, page.mode, true)}>继续加载</button>}</p>}
    {evidence && <div className="position-evidence" role="region" aria-label="所选变化证据"><strong>{formatChange(evidence)}</strong><p>前值 {evidence.old_value ?? "未知"} → 后值 {evidence.new_value ?? "未知"}</p><p>检测时间 {formatDate(evidence.detected_at)}</p><p>Event #{evidence.id} · Snapshot #{evidence.snapshot_id ?? "未知"} · Collection Run #{evidence.collection_run_id ?? "未知"} · {evidence.entity_key ?? "Offer 级"} {evidence.sku_name}</p><p>单品详情没有事件锚点；以上保留所选事件证据。</p><button className="detail-button" onClick={() => onOpenDetail(evidence.competitor_id)}>查看详情</button></div>}
    </section></div>
    <aside hidden={workspaceView !== "商品对比"} className="position-aside"><section className="table-card position-side-card"><h2>组内经营判断</h2><strong>证据不足</strong><p>不计算销量排名、增长或综合评分。</p><h3>关键证据与缺口</h3><p>经营表现和口碑履约展示官方采购助手原值；平台标签与收藏数待接入。</p><h3>当前建议</h3><p>证据不足。可从单品速览核查事实，不生成调价、加码或放弃建议。</p></section><section className="table-card position-side-card product-preview"><h2>商品速览</h2>{selected ? <><div className="product-preview-shop">{selected.shop_name?.trim() || "店铺未采集"}{selected.id === own?.id && <span className="group-own-label">我方</span>}</div><p className="product-preview-title">{selected.title || "商品名未采集"}</p><p className="product-preview-offer">Offer ID：{selected.offer_id}</p><dl className="position-facts">{(["price", "moq", "sku", "stock"] as const).map((field, index) => <div key={field}><dt>{["展示报价", "MOQ", "SKU 数", "完整库存"][index]}</dt><dd>{groupSnapshotValue(selected, field)}</dd></div>)}</dl><div className="product-preview-status"><span>商品：{selected.status === "active" ? "在售" : selected.status === "offline" ? "下架" : "未知"}</span><span>{selected.is_active ? "监控中" : "已停止"}</span></div><p className="product-preview-freshness">最近有效基础快照 · {formatDate(selected.latest_snapshot?.captured_at ?? null)}</p>{previewPosition(selected)}<button className="detail-button" onClick={() => onOpenDetail(selected.id)}>查看详情</button></> : <p>当前组暂无有效商品可速览</p>}</section></aside>
    </div></div>
  </AppShell>;
}

export function GroupNameDialog({ mode, name, submitting, error, onChange, onClose, onSubmit }: { mode: "create" | "rename"; name: string; submitting: boolean; error: string | null; onChange: (name: string) => void; onClose: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  const isRename = mode === "rename";
  const ref = useRef<HTMLDialogElement>(null);
  const [opener] = useState(() => typeof document === "undefined" ? null : document.activeElement as HTMLElement | null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    dialog?.querySelector("input")?.focus();
    return () => { dialog?.close(); opener?.focus(); };
  }, []);
  return <dialog ref={ref} className="dialog group-name-dialog" aria-modal="true" aria-labelledby="group-name-dialog-title" onCancel={event => { event.preventDefault(); if (!submitting) onClose(); }} onKeyDown={event => {
    if (event.key !== "Tab") return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled)"));
    const target = event.shiftKey ? controls.at(-1) : controls[0];
    if (target && (event.shiftKey && document.activeElement === controls[0] || !event.shiftKey && document.activeElement === controls.at(-1))) { event.preventDefault(); target.focus(); }
  }}>
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="group-name-dialog-title">{isRename ? "重命名竞品组" : "新增竞品组"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    <p className="dialog-description">{isRename ? "修改竞品组名称，不影响竞品及历史监控数据。" : "竞品组使用我方商品型号命名，用于归集该商品对应的竞品。"}</p>
    <form onSubmit={onSubmit}><label htmlFor="group-name">竞品组名称</label><input id="group-name" value={name} onChange={(event) => onChange(event.target.value)} placeholder="使用商品型号命名，例如 A19、X6" maxLength={64} autoComplete="off" disabled={submitting} />{error && <div className="feedback feedback-server-error" role="alert">{error}</div>}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="submit" className="primary-button" disabled={submitting || !name.trim()}>{submitting ? "保存中…" : isRename ? "保存" : "新增竞品组"}</button></div></form>
  </dialog>;
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
      <div className={`competitor-list-page${selfPage ? " own-product-list-page" : ""}`}>
        <header className="page-header"><div><h1>{selfPage ? "我方商品" : "竞品列表"}</h1><p className="page-description">{selfPage ? "查看已识别为我方店铺的监控商品，并管理采集与竞品组关系。" : "查看当前已添加的 1688 竞品，并管理监控对象。"}</p></div><div className="page-actions"><div className="batch-menu"><button type="button" className="secondary-button batch-trigger" aria-haspopup="menu" aria-expanded={batchMenuOpen} onClick={() => setBatchMenuOpen((open) => !open)} disabled={batchBusy}>批量操作（{selectedCount}） <span aria-hidden="true">▼</span></button>{batchMenuOpen && <div className="batch-menu-popover" role="menu">{!selfPage && <><button type="button" role="menuitem" disabled={selectedGroupCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("group", selectedFilteredCompetitors.map((item) => item.id)); }}>设置分组（{selectedGroupCount}）</button><span className="batch-menu-divider" role="separator" /></>}<button type="button" role="menuitem" disabled={selectedActiveCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("stop", selectedFilteredCompetitors.map((item) => item.id)); }}>停止监控（{selectedActiveCount}）</button><button type="button" role="menuitem" disabled={selectedInactiveCompetitors.length === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("resume", selectedFilteredCompetitors.map((item) => item.id)); }}>恢复监控（{selectedInactiveCompetitors.length}）</button>{!selfPage && <><span className="batch-menu-divider" role="separator" /><button type="button" role="menuitem" className="batch-menu-danger" disabled={selectedGroupCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("delete", selectedFilteredCompetitors.map((item) => item.id)); }}>删除竞品（{selectedGroupCount}）</button></>}</div>}</div></div></header>
        {batchState.status === "running" && <div className="batch-status-panel batch-status-running" role="status">采集中 {batchState.completed} / {batchState.total} · 成功 {batchState.succeeded} · 失败 {batchState.failed}</div>}
        {batchState.status === "cooling_down" && <div className="batch-status-panel batch-status-cooling_down" role="status">1688 验证已触发，浏览器已自动关闭。将在 {formatBatchCooldown(batchState.cooldown_remaining_seconds)} 后自动继续采集（自动恢复 {batchState.auto_resume_attempt}/{batchState.auto_resume_max}）。<span>已完成 {batchState.completed} / {batchState.total}，剩余 {batchState.remaining}</span></div>}
        {batchState.status === "verification_required" && <div className="batch-status-panel batch-status-verification" role="alert">1688 需要人工验证，本次采集已停止。请在弹出的浏览器中完成处理，关闭浏览器后可重新发起采集。<span>已完成 {batchState.completed} / {batchState.total}，剩余 {batchState.remaining}</span></div>}
        <div className={`competitor-workspace${selfPage ? " own-product-workspace" : ""}`}>
        <section className="filter-card" aria-label="搜索和筛选">
          <div className="filter-field filter-search"><label htmlFor="search">{selfPage ? "搜索我方商品" : "搜索竞品"}</label><input id="search" aria-label="搜索商品名称 / offerId / 店铺" value={filters.search} onChange={(event) => updateFilters((current) => ({ ...current, search: event.target.value }))} placeholder="搜索商品名称 / offerId / 店铺" /></div>
          <div className="filter-field"><label htmlFor="product-status">商品状态</label><select id="product-status" value={filters.status} onChange={(event) => updateFilters((current) => ({ ...current, status: event.target.value as CompetitorFilters["status"] }))}><option value="all">全部状态</option><option value="active">在售</option><option value="offline">已下架</option><option value="unknown">状态未知</option></select></div>
          <div className="filter-field"><label htmlFor="collection-status">采集状态</label><select id="collection-status" value={filters.collectionStatus} onChange={(event) => updateFilters((current) => ({ ...current, collectionStatus: event.target.value as CompetitorFilters["collectionStatus"] }))}><option value="all">全部状态</option><option value="collected">已采集</option><option value="not_collected">未采集</option></select></div>
          <div className="filter-field"><label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={filters.groupId === "all" ? "all" : String(filters.groupId)} onChange={(event) => updateFilters((current) => ({ ...current, groupId: event.target.value === "all" || event.target.value === "unassigned" ? event.target.value : Number(event.target.value) }))}><option value="all">全部竞品组</option><option value="unassigned">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></div>
          <button type="button" className="text-button" onClick={resetFilters}>重置</button>
        </section>
        <section className="stats-strip" aria-label="列表统计">
          <div className="stat-total"><h2>{selfPage ? "全部我方商品" : "全部竞品"}</h2><strong>共 {status === "ready" ? filteredCompetitors.length : "—"} 个{selfPage ? "我方商品" : "竞品"}</strong></div>
          <div className="stat-item"><span>已采集数量</span><strong>{status === "ready" ? collectedCount : "—"}</strong></div>
          <div className="stat-item"><span>未采集数量</span><strong>{status === "ready" ? filteredCompetitors.length - collectedCount : "—"}</strong></div>
          {!selfPage && <span className="competitor-sort-note">按添加时间倒序展示</span>}
        </section>
        <section className="table-card">
          {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>{selfPage ? "正在加载我方商品…" : "正在加载竞品列表…"}</strong></div>}
          {status === "error" && <div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品列表。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div>}
          {status === "ready" && competitors.length === 0 && <div className="state-panel"><div className="empty-icon">+</div><strong>{selfPage ? "还没有我方商品" : "还没有添加竞品"}</strong><span>{selfPage ? "从竞品监控大屏添加商品后，识别为我方店铺的商品会出现在这里。" : "从竞品监控大屏添加一个 1688 商品链接，开始建立你的监控列表。"}</span></div>}
          {status === "ready" && competitors.length > 0 && filteredCompetitors.length === 0 && <div className="state-panel"><strong>{selfPage ? "没有找到符合条件的我方商品" : "没有找到符合条件的竞品"}</strong><span>请调整搜索词或筛选条件</span><button type="button" className="secondary-button" onClick={resetFilters}>重置筛选</button></div>}
          {status === "ready" && filteredCompetitors.length > 0 && <div className="table-scroll"><table aria-label={selfPage ? "我方商品列表" : "竞品列表"}><thead><tr><th className="selection-column"><input ref={selectAllRef} type="checkbox" aria-label="全选当前页全部商品" checked={allSelected} disabled={pageIds.length === 0 || batchBusy} onChange={(event) => onToggleAll(event.target.checked, pageIds)} /></th><th>商品信息</th><th>店铺名称</th><th>竞品组</th><th>当前价格</th><th>SKU 数量</th><th>最近采集时间</th><th>商品状态</th><th>监控状态</th></tr></thead><tbody>
             {pagedCompetitors.map((competitor) => <tr key={competitor.id} data-selected={selectedIds.has(competitor.id) ? "true" : undefined}><td data-label="选择" className="selection-column"><input type="checkbox" aria-label={`选择 ${competitor.title || competitor.offer_id}`} checked={selectedIds.has(competitor.id)} disabled={batchBusy} onChange={() => onToggleSelected(competitor.id)} /></td><td data-label="商品信息"><div className="product-cell"><ProductImage competitor={competitor} /><div><button type="button" className="competitor-title-link" title={competitor.title || "未采集"} onClick={() => onOpenDetail?.(competitor.id)}>{competitor.title || "未采集"}</button><div className="competitor-product-meta"><span>offerId：{competitor.offer_id}</span><a href={competitor.url} target="_blank" rel="noreferrer" aria-label="查看 1688 商品 ↗">1688 ↗</a></div></div></div></td><td data-label="店铺名称">{competitor.shop_name || "未采集"}</td><td data-label="竞品组"><div className="list-group-cell"><span>{getCompetitorGroupLabel(competitor.group_id, groups)}</span><button type="button" className="text-button" onClick={() => onOpenGroupAssignment(competitor)}>{competitor.group_id === null ? "+ 绑定竞品组" : "更换/解除"}</button></div></td><td data-label="当前价格" className={competitor.latest_snapshot?.price_min || competitor.latest_snapshot?.price_max ? "price-cell" : "muted-cell"}>{formatPriceDisplay(competitor.latest_snapshot)}</td><td data-label="SKU 数量" className={competitor.latest_snapshot === null ? "muted-cell" : "sku-cell"}>{competitor.latest_snapshot === null ? "未采集" : competitor.latest_snapshot.sku_count}</td><td data-label="最近采集时间" className="collection-date-cell">{formatDate(competitor.last_collected_at)}</td><td data-label="商品状态"><StatusBadge status={competitor.status} /></td><td data-label="监控状态"><span className={competitor.is_active ? "list-monitoring-badge" : "list-monitoring-badge list-monitoring-inactive"}>{competitor.is_active ? "监控中" : "已停止"}</span></td></tr>) }
          </tbody></table></div>}
        </section>
        <PaginationBar total={filteredCompetitors.length} itemLabel={selfPage ? "个我方商品" : "个竞品"} page={pagination.page} totalPages={pagination.totalPages} onPrevious={() => setCurrentPage((page) => page - 1)} onNext={() => setCurrentPage((page) => page + 1)} previousDisabled={pagination.page === 1} nextDisabled={pagination.page === pagination.totalPages} />
        </div>
      </div>
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
  onToggleBatchPause?: () => void;
  onEndBatch?: () => void;
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
  const height = 320;
  const top = 20;
  const bottom = 44;
  const left = 52;
  const right = 38;
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
    {points.map((point, index) => <g key={`hit-${point.date}`} onMouseEnter={() => setActiveIndex(index)}><rect className="chart-hit-area" tabIndex={0} role="img" aria-label={formatDashboardTrendTooltip(point).join("，")} onFocus={() => setActiveIndex(index)} onBlur={() => setActiveIndex(null)} x={point.x - (points.length === 1 ? 18 : 14)} y={top} width={points.length === 1 ? 36 : 28} height={plotHeight} /></g>)}
    {points.map((point) => <text key={point.date} className="chart-label" x={point.x} y={height - 10} textAnchor="middle">{point.date.slice(5).replace("-", "/")}</text>)}
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

function CollectionOverview({ data, status, error, batchState, onRetry, onTogglePause, onEndBatch, onNavigate }: { data: DashboardData | null; status: DashboardStatus; error: string | null; batchState: BatchState; onRetry: () => void; onTogglePause: () => void; onEndBatch: () => void; onNavigate: (page: Page) => void }) {
  const summary = status === "ready" ? data?.collection_summary : null;
  const progress = batchState.total > 0 ? Math.min(100, (batchState.completed / batchState.total) * 100) : 0;
  const pausedWait = batchState.cooldown_remaining_seconds > 0 ? `风控冷却已暂停 · 剩余 ${formatBatchCooldown(batchState.cooldown_remaining_seconds)}` : batchState.resting_remaining_seconds > 0 ? `计划休息已暂停 · 剩余 ${formatBatchCooldown(batchState.resting_remaining_seconds)}` : null;
  const statusLabel = batchState.status === "running" ? "采集中" : batchState.status === "pausing" ? "正在暂停" : batchState.status === "paused" ? "已暂停" : batchState.status === "stopping" ? "正在结束" : batchState.status === "stopped" ? "已结束" : batchState.status === "resting" ? "计划休息" : batchState.status === "cooling_down" ? "冷却中" : batchState.status === "verification_required" ? "需要人工验证" : batchState.status === "completed" ? "最近批次完成" : "当前无采集任务";
  const statusTone = batchState.status === "running" ? "running" : batchState.status === "verification_required" || batchState.failed > 0 || batchState.batch_outcome_code === "infrastructure_error" || batchState.batch_outcome_code === "interrupted" ? "warning" : batchState.status === "resting" || batchState.status === "cooling_down" ? "waiting" : "quiet";
  const nextAutoText = batchState.auto_collection_enabled === false ? "自动采集未开启" : batchState.auto_collection_enabled !== true ? "正在读取计划…" : batchState.auto_collection_strategy === "rolling_24h" ? "滚动计划（按商品上次采集时间判断）" : batchState.next_auto_collection_at || "正在计算…";
  return <section className="table-card collection-overview"><div className="table-heading"><div><h2>采集状态概览</h2><span>数据库记录与当前批次</span></div>{batchState.status !== "idle" && <div className="collection-overview-controls"><span className={`overview-status overview-status-${statusTone}`} role="status" aria-live="polite" aria-atomic="true"><span className="collection-status-dot" aria-hidden="true" />{statusLabel}</span><div className="collection-overview-actions">{batchState.runner_active && ["running", "pausing", "paused", "resting", "cooling_down"].includes(batchState.status) && <button type="button" className="secondary-button collection-pause-button" onClick={onTogglePause} disabled={batchState.status === "pausing"}><svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">{batchState.status === "paused" ? <path d="M7 4.5v11l8-5.5-8-5.5Z" /> : <path d="M7 5v10M13 5v10" />}</svg>{batchState.status === "paused" ? "继续采集" : batchState.status === "pausing" ? "暂停中…" : "暂停采集"}</button>}{batchState.runner_active && ["running", "pausing", "paused", "stopping", "resting", "cooling_down", "verification_required"].includes(batchState.status) && <button type="button" className="secondary-button collection-end-button" onClick={onEndBatch} disabled={batchState.status === "stopping"}><svg viewBox="0 0 20 20" aria-hidden="true" focusable="false"><rect x="5.5" y="5.5" width="9" height="9" rx="1" /></svg>{batchState.status === "stopping" ? "结束中…" : "结束采集"}</button>}</div></div>}</div>
    {status === "error" && <div className="dashboard-support-error" role="alert"><span>{error || "暂时无法获取采集统计和趋势。"}</span><button type="button" className="text-link-button" onClick={onRetry}>重试</button></div>}
    <div className="collection-summary-grid"><div><span>最近采集时间（含历史）</span><strong>{summary ? summary.last_collection_at ? formatDate(summary.last_collection_at) : "暂无采集记录" : status === "loading" ? "加载中…" : "暂不可用"}</strong></div><div><span>今日成功</span><strong>{summary ? summary.success_runs : "—"}</strong></div><div><span>今日失败</span><strong className={summary?.failed_runs ? "collection-value-error" : ""}>{summary ? summary.failed_runs : "—"}</strong></div><div><span>平均耗时</span><strong>{formatDuration(summary?.average_duration_seconds ?? null)}</strong></div></div>
    <p className="dashboard-collection-note">今日统计为采集次数，包含我方商品与竞品，非去重商品数。</p>
    <p className="dashboard-next-collection">下次自动采集：<strong>{nextAutoText}</strong>{batchState.auto_collection_enabled && batchState.auto_collection_strategy !== "rolling_24h" && <span>（后端本地时间，计划检查时间）</span>}</p>
    <div className={`collection-batch collection-batch-${batchState.status}`}>
      {batchState.work_kind === "add_links" && batchState.input_progress ? <>
        <div className="collection-batch-heading"><strong>添加链接：已处理 {batchState.input_progress.processed}/{batchState.input_progress.total}</strong><span>{batchState.batch_outcome_code === "infrastructure_error" ? "基础设施异常中止" : batchState.batch_outcome_code === "interrupted" ? "进程中断" : batchState.status === "completed" ? batchState.input_progress.added ? batchState.input_progress.added === batchState.input_progress.total ? "全部新增" : "部分新增成功" : batchState.input_progress.technical_failed ? "添加失败" : "未新增" : batchState.status === "stopped" ? "用户已结束" : batchState.status === "paused" ? pausedWait || "已暂停" : batchState.status === "resting" ? `计划休息剩余 ${formatBatchCooldown(batchState.resting_remaining_seconds)}` : batchState.status === "verification_required" ? "需要验证，已停止访问" : "处理中"}</span></div>
        {batchState.current_input_position != null && <div className="collection-batch-current">当前输入：第 {batchState.current_input_position + 1} 条</div>}
        <div className="collection-batch-meta"><span>新增 {batchState.input_progress.added}</span><span>业务拒绝 {batchState.input_progress.business_rejected}</span><span>技术失败 {batchState.input_progress.technical_failed}</span><span>验证 {batchState.input_progress.verification_required}</span><span>中断 {batchState.input_progress.interrupted}</span><span>{batchState.runner_active ? "剩余" : "未执行"} {batchState.input_progress.remaining}</span><span>页面访问 {batchState.page_visits} · 未知 {batchState.page_visits_unknown}</span></div>
        <div className="collection-progress" role="progressbar" aria-label={`添加进度 ${batchState.input_progress.processed} / ${batchState.input_progress.total}`} aria-valuemin={0} aria-valuemax={batchState.input_progress.total} aria-valuenow={batchState.input_progress.processed}><span style={{ width: `${100 * batchState.input_progress.processed / batchState.input_progress.total}%` }} /></div>
      </> : batchState.status === "idle" ? <div className="collection-batch-heading"><strong>当前无采集任务</strong><span>今日采集统计仍会保留</span></div> : batchState.status === "completed" ? <>
        <div className="collection-batch-heading"><strong>最近批次完成</strong><span>成功 {batchState.succeeded} · 失败 {batchState.failed}</span></div>
        <div className="collection-batch-meta"><span>已完成 {batchState.completed} / {batchState.total}</span><span>页面访问 {batchState.page_visits}{batchState.page_visits_unknown ? ` + ${batchState.page_visits_unknown} 次未知` : ""}</span></div>
      </> : <>
      <div className="collection-batch-heading"><strong>{batchState.status === "running" ? `采集中 ${batchState.completed} / ${batchState.total}` : batchState.status === "pausing" ? `当前商品完成后暂停 · ${batchState.completed} / ${batchState.total}` : batchState.status === "paused" ? `采集已暂停 · ${batchState.completed} / ${batchState.total}` : batchState.status === "stopping" ? `当前商品完成后结束 · ${batchState.completed} / ${batchState.total}` : batchState.status === "stopped" ? `采集已结束 · ${batchState.completed} / ${batchState.total}` : batchState.status === "resting" ? "计划休息中" : batchState.status === "cooling_down" ? "冷却中" : "需要人工验证"}</strong><span>{batchState.status === "running" ? `成功 ${batchState.succeeded} · 失败 ${batchState.failed}` : batchState.status === "pausing" || batchState.status === "stopping" || batchState.status === "stopped" ? `已完成 ${batchState.completed} / ${batchState.total} · 剩余 ${batchState.remaining}` : batchState.status === "paused" ? pausedWait || `已完成 ${batchState.completed} / ${batchState.total} · 剩余 ${batchState.remaining}` : batchState.status === "resting" ? `休息剩余 ${formatBatchCooldown(batchState.resting_remaining_seconds)} · 已完成 ${batchState.completed} / ${batchState.total} · 剩余 ${batchState.remaining}` : batchState.status === "cooling_down" ? `冷却剩余 ${formatBatchCooldown(batchState.cooldown_remaining_seconds)} · 自动恢复 ${batchState.auto_resume_attempt}/${batchState.auto_resume_max} · 已完成 ${batchState.completed} · 剩余 ${batchState.remaining}` : batchState.status === "verification_required" ? `已完成 ${batchState.completed} / ${batchState.total}` : "今日采集统计仍会保留"}</span></div>
      {batchState.current_competitor_id !== null && <div className="collection-batch-current"><span>当前商品</span><strong>{batchState.current_competitor_title || `商品 ${batchState.current_competitor_id}`}</strong></div>}
      <div className="collection-batch-meta"><span>阶段：{batchState.phase === "operating_metrics_retry" ? `经营补采 ${batchState.retry_completed}/${batchState.retry_total}` : batchState.phase === "verification_resume" ? "验证恢复" : "首次采集"}</span><span>完成 {batchState.completed} / {batchState.total} · 剩余 {batchState.remaining}</span><span>页面访问 {batchState.page_visits}{batchState.page_visits_unknown ? ` + ${batchState.page_visits_unknown} 次未知` : ""}</span><span>补采访问 {batchState.retry_visits} · 上限 {batchState.retry_max}</span></div>
      {(batchState.status === "running" || batchState.status === "pausing" || batchState.status === "paused" || batchState.status === "resting") && <div className="collection-progress" role="progressbar" aria-label={`采集进度 ${batchState.completed} / ${batchState.total}`} aria-valuemin={0} aria-valuemax={batchState.total} aria-valuenow={batchState.completed}><span style={{ width: `${progress}%` }} /></div>}      </>}

    </div>
    <div className="dashboard-collection-footer"><button type="button" className="text-link-button" onClick={() => onNavigate("collection-tasks")}>查看采集记录</button><span>排查失败与历史批次</span></div>
  </section>;
}

function dashboardCollectionNotice(data: DashboardData | null, status: DashboardStatus, batch: BatchState) {
  const stages: Partial<Record<BatchStatus, string>> = { running: "采集进行中", pausing: "正在暂停采集", paused: "采集已暂停", stopping: "正在结束采集", resting: "采集计划休息中", cooling_down: "采集风控冷却中", verification_required: "采集需要人工验证" };
  if (stages[batch.status]) return { title: stages[batch.status], detail: "当前结果尚不完整，请结合采集状态查看；已检测的变化仍会保留。", tone: batch.status === "verification_required" ? "warning" : "info" };
  if (status !== "ready" || !data) return { title: status === "error" ? "采集统计暂不可用" : "正在读取采集统计", detail: "当前无法确认今日采集情况，不能据此判断竞品是否无变化。", tone: "neutral" };
  const { success_runs, failed_runs } = data.collection_summary;
  if (failed_runs > 0) return { title: success_runs > 0 ? "今日部分采集失败" : "今日采集尚未成功", detail: "请查看采集记录排查异常；暂无关注事件不代表竞品没有变化。", tone: "warning" };
  if (success_runs === 0) return { title: "今日尚无已完成采集记录", detail: "先采集再判断今日变化。历史采集结果不能代表今天的竞品状态。", tone: "neutral" };
  return { title: "今日已有成功采集记录", detail: "变化仅来自已检测事件，成功次数不代表所有监控商品均已采集。", tone: "neutral" };
}

function DashboardAttentionList({ attention, onOpenGroupDetail }: { attention: GroupAttentionData; onOpenGroupDetail?: (groupId: number) => void }) {
  const [showAllAttention, setShowAllAttention] = useState(false);
  const priorityGroups = attention.groups.filter(item => item.attention_level !== "一般变化");
  const ordinaryGroups = attention.groups.filter(item => item.attention_level === "一般变化");
  const visibleAttentionGroups = showAllAttention ? priorityGroups : priorityGroups.slice(0, 5);
  const renderGroup = (item: GroupAttentionItem) => <article className="dashboard-attention-card" key={item.group_id}><div className="dashboard-attention-main"><div className="dashboard-attention-identity"><h3>{item.group_name}</h3></div><span className={`dashboard-attention-level dashboard-attention-level-${item.attention_level === "重点关注" ? "high" : item.attention_level === "建议查看" ? "medium" : "low"}`}>{item.attention_level}</span></div><div className="dashboard-attention-meta"><span>今日变化竞品 <strong>{item.changed_competitor_count}</strong></span><span>最近变化 {formatDate(item.latest_change_at)}</span></div><ul className="dashboard-attention-reasons">{item.reasons.map((reason, index) => <li key={`${reason.reason_type}-${index}`}>{reason.display_text}</li>)}</ul><button type="button" className="detail-button dashboard-attention-action" onClick={() => onOpenGroupDetail?.(item.group_id)}>进入组分析</button></article>;
  return <><p className="position-context">重点关注 / 建议查看 {priorityGroups.length} 组 · 一般变化 {ordinaryGroups.length} 组</p>
    {!priorityGroups.length && <p className="group-compact-empty">今日暂无重点关注或建议查看的商品组</p>}
    <div className="dashboard-attention-list">{visibleAttentionGroups.map(renderGroup)}</div>
    {priorityGroups.length > 5 && <div className="dashboard-attention-toggle"><span>{showAllAttention ? `已展示全部 ${priorityGroups.length} 个商品组` : `还有 ${priorityGroups.length - 5} 个需要关注的商品组`}</span><button type="button" aria-expanded={showAllAttention} onClick={() => setShowAllAttention(value => !value)} aria-label={showAllAttention ? "收起" : "展开全部"}>{showAllAttention ? "收起" : "展开全部"}<i aria-hidden="true">{showAllAttention ? "⌃" : "⌄"}</i></button></div>}
    {ordinaryGroups.length > 0 && <details className="dashboard-ordinary-groups"><summary>一般变化 {ordinaryGroups.length} 组</summary><div className="dashboard-attention-list">{ordinaryGroups.map(renderGroup)}</div></details>}
  </>;
}

export function DashboardPage({ data, attention, attentionStatus, attentionError, status, error, batchState = idleBatchState, onRetry, onRetryAttention, onNavigate, ownShopName = null, onAdd = noop, onCollect = noop, onToggleBatchPause = noop, onEndBatch = noop, onOpenGroupDetail }: DashboardPageProps) {
  const attentionValue = (field: keyof GroupAttentionData["kpis"]) => attentionStatus === "ready" && attention ? attention.kpis[field] : "—";
  const failedCollections = status === "ready" && data ? data.stats.failed_collections : "—";
  const collectionBusy = batchState.status === "running" || batchState.status === "cooling_down" || batchState.runner_active || batchState.browser_open;
  const collectionAvailable = status === "ready" && (data?.stats.active_monitored_products ?? 0) > 0;
  const notice = dashboardCollectionNotice(data, status, batchState);
  const noGroups = attentionStatus === "ready" && attention?.kpis.monitored_product_groups === 0;
  const emptyTitle = noGroups ? "先建立可监控的商品组" : notice.tone === "info" || batchState.status === "verification_required" ? "等待本轮采集结果" : status !== "ready" ? "暂无关注事件，采集情况待确认" : !data?.collection_summary.success_runs ? "尚不能判断今日竞争变化" : data.collection_summary.failed_runs > 0 ? "暂无关注事件，仍有采集异常" : "今日暂无需要关注的竞争变化";
  return <AppShell page="dashboard" onNavigate={onNavigate} breadcrumb="竞品监控大屏">
    <header className="page-header dashboard-page-header"><div><h1>竞品监控大屏</h1><p className="page-description">从今日变化找到关注重点，进入商品组核对竞争差距。</p></div><div className="dashboard-header-actions"><span className="dashboard-shop-context">我方店铺：{ownShopName || "未配置"}</span>{ownShopName ? <div className="dashboard-header-buttons"><button type="button" className="primary-button" onClick={onCollect} disabled={collectionBusy || !collectionAvailable}>立即采集</button><button type="button" className="secondary-button" onClick={onAdd}>添加监控商品</button></div> : <button type="button" className="text-link-button" onClick={() => onNavigate("settings")}>去系统设置</button>}</div></header>
    <section className="dashboard-stats" aria-label="商品组关注统计"><DashboardStatCard label="监控商品组" value={attentionValue("monitored_product_groups")} kind="groups" tone="blue" /><DashboardStatCard label="今日有变化商品组" value={attentionValue("changed_product_groups_today")} kind="changed-groups" tone="purple" /><DashboardStatCard label="今日涉及变化竞品" value={attentionValue("changed_competitors_today")} kind="competitors" tone="green" /><DashboardStatCard label="异常采集" value={failedCollections} kind="error" tone="orange" /></section>
    <p className="dashboard-scope-note">{attentionStatus === "ready" && attention ? attention.date : "今日"} · 上海时间 · 变化统计仅含已检测事件，零变化不等于全部已采集。</p>
    <div className="dashboard-work-grid">
    <section className="table-card dashboard-attention-section" aria-labelledby="dashboard-attention-heading"><div className="table-heading"><div><h2 id="dashboard-attention-heading">今日需要关注的商品组</h2><span>按关注优先级查看，再进入组分析核对事实</span></div><span className="table-count">{attentionStatus === "ready" && attention ? `${attention.groups.length} 个商品组` : "—"}</span></div>
      <div className={`dashboard-data-notice dashboard-data-notice-${notice.tone}`}><strong>{notice.title}</strong><span>{notice.detail}</span></div>
      {attentionStatus === "loading" && <div className="dashboard-attention-state"><div className="spinner" /><strong>正在加载商品组关注信息…</strong></div>}
      {attentionStatus === "error" && <div className="dashboard-attention-state dashboard-attention-error" role="alert"><strong>暂时无法获取商品组关注信息</strong><span>{attentionError || "请检查服务后重试。"}</span><button type="button" className="secondary-button" onClick={onRetryAttention}>重试</button></div>}
      {attentionStatus === "ready" && attention && attention.groups.length === 0 && <div className="dashboard-attention-state"><DashboardIcon kind="groups" /><strong>{emptyTitle}</strong><span>{noGroups ? "商品组需绑定我方商品，并至少添加一个直接竞品，才能进入关注统计。" : "这里只显示符合组条件、且已检测到今日竞争变化的商品组。"}</span>{noGroups ? <button type="button" className="secondary-button" onClick={() => onNavigate("groups")}>管理商品组</button> : ownShopName && collectionAvailable && !collectionBusy ? <button type="button" className="secondary-button" onClick={onCollect}>采集监控商品</button> : !ownShopName ? <button type="button" className="secondary-button" onClick={() => onNavigate("settings")}>配置我方店铺</button> : null}</div>}
      {attentionStatus === "ready" && attention && attention.groups.length > 0 && <DashboardAttentionList attention={attention} onOpenGroupDetail={onOpenGroupDetail} />}
      <div className="dashboard-attention-footer"><span>关注等级表示查看优先级</span><button type="button" className="text-link-button" onClick={() => onNavigate("groups")}>查看全部商品组</button></div>
    </section>
    <CollectionOverview data={data} status={status} error={error} batchState={batchState} onRetry={onRetry} onTogglePause={onToggleBatchPause} onEndBatch={onEndBatch} onNavigate={onNavigate} />
    </div>
    <details className="dashboard-history"><summary><span>近 7 天竞品变化趋势</span><span className="dashboard-history-hint">历史参考 · 按需展开</span></summary><section className="dashboard-trend-section"><p className="dashboard-scope-note">每日真实监控事件数，不代表商品覆盖率或销量。</p>{status === "ready" && data ? <DashboardTrendChart trend={data.trend_7d} /> : <div className="dashboard-trend-placeholder">{status === "error" ? "趋势暂不可用" : "正在加载趋势…"}</div>}</section></details>
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

export function DetailPage({ data, groups, status, error, days, rangeLoading = false, onRetry, onRangeChange, onBack, onChangeGroup, onLifecycleAction, lifecycleSubmitting = false, onNavigate }: DetailPageProps) {
  if (status === "loading") return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel"><div className="spinner" /><strong>正在加载竞品详情…</strong></div></AppShell>;
  if (status === "error" || data === null) return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品详情。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div></AppShell>;
  const isSelf = data.competitor.ownership === "self";
  return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情">
    <header className="page-header detail-page-header"><div><h1>{isSelf ? "我方商品详情" : "竞品详情"}</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div><div className="detail-page-actions"><button type="button" className="secondary-button" onClick={onBack}>返回{isSelf ? "我方商品" : "竞品列表"}</button>{data.competitor.is_active ? <button type="button" className="secondary-button" onClick={() => onLifecycleAction?.("stop", data.competitor)} disabled={lifecycleSubmitting}>停止监控</button> : <button type="button" className="primary-button" onClick={() => onLifecycleAction?.("resume", data.competitor)} disabled={lifecycleSubmitting}>恢复监控</button>}<button type="button" className="detail-danger-button" onClick={() => onLifecycleAction?.("delete", data.competitor)} disabled={lifecycleSubmitting}>删除{isSelf ? "我方商品" : "竞品"}</button></div></header>
     <DetailOverview data={data} groups={groups} onChangeGroup={onChangeGroup} />
    <OperatingMetricsPanel metrics={data.operating_metrics} latestRun={data.latest_collection_run} />
    <section className="detail-trends"><div className="detail-trends-header"><div><h2>趋势数据</h2><span>价格和库存来自每日最终 ProductSnapshot</span></div><div className="range-selector" role="group" aria-label="趋势时间范围" aria-busy={rangeLoading}><button type="button" aria-pressed={days === 7} className={days === 7 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(7)} disabled={rangeLoading}>近 7 天</button><button type="button" aria-pressed={days === 30} className={days === 30 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(30)} disabled={rangeLoading}>近 30 天</button>{rangeLoading && <span className="range-loading-indicator" role="status">更新中…</span>}</div></div><div className="detail-trend-grid"><DetailTrendCard kind="price" title="价格趋势" description="最低价 / 最高价" trend={data.daily_trend} /><DetailTrendCard kind="stock" title="库存趋势" description="全部 SKU 库存总和" trend={data.daily_trend} /></div></section>
    <div className="detail-lower-grid">
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>SKU 信息</h2><span>{data.latest_snapshot ? `共 ${data.latest_snapshot.sku_count} 个` : "当前快照"}</span></div></div>{data.latest_skus.length === 0 ? <div className="detail-empty">暂无 SKU 数据</div> : <div className="table-scroll detail-table-scroll"><table><thead><tr><th>SKU 规格</th><th>SKU ID</th><th>库存</th><th>SKU 价格</th></tr></thead><tbody>{data.latest_skus.map((sku) => <tr key={sku.sku_id}><td>{sku.sku_name ?? "未命名 SKU"}</td><td>{sku.sku_id}</td><td>{sku.stock === null ? "—" : sku.stock}</td><td>{sku.price === null ? "—" : `¥${sku.price}`}</td></tr>)}</tbody></table></div>}</section>
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>最近变化</h2><span>最近 20 条 · 检测时间</span></div></div>{data.recent_changes.length === 0 ? <div className="detail-empty">暂无变化记录</div> : <div className="detail-record-list">{data.recent_changes.map((change) => <div className="detail-record-row" key={change.id}><strong>{formatChange(change)}</strong><time>{formatDate(change.detected_at)}</time></div>)}</div>}</section>
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>最近采集记录</h2><span>最近 20 条</span></div></div>{data.recent_collection_runs.length === 0 ? <div className="detail-empty">暂无采集记录</div> : <div className="table-scroll detail-table-scroll"><table className="collection-runs-table"><thead><tr><th>开始时间</th><th>结束时间</th><th>状态</th><th>结果</th></tr></thead><tbody>{data.recent_collection_runs.map((run) => <tr key={run.id}><td>{formatDate(run.started_at)}</td><td>{run.finished_at ? formatDate(run.finished_at) : "—"}</td><td>{formatCollectionRunStatus(run.status, run.operating_metrics_status)}</td><td>{run.status === "failed" ? run.error_message || "采集失败" : run.status === "success" ? "成功" : "—"}</td></tr>)}</tbody></table></div>}</section>
    </div>
  </AppShell>;
}

type AddDialogProps = { url: string; status: AddStatus; onUrlChange: (url: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onClose: () => void; groups: CompetitorGroup[]; groupsStatus?: GroupStatus; groupsError?: string | null; onRetryGroups?: () => void; groupId: number | null; onGroupChange: (groupId: number | null) => void; newGroupName: string; onNewGroupNameChange: (name: string) => void; onCreateGroup: () => void; groupCreateStatus: GroupCreateStatus; failures?: AddFailure[]; succeededCount?: number; progress?: { completed: number; total: number } };

export function AddDialog({ url, status, onUrlChange, onSubmit, onClose, groups, groupsStatus = "ready", groupsError = null, onRetryGroups = () => {}, groupId, onGroupChange, newGroupName, onNewGroupNameChange, onCreateGroup, groupCreateStatus, failures = [], succeededCount = 0, progress = { completed: 0, total: 0 } }: AddDialogProps) {
  const busy = status === "submitting";
  const urlCount = dedupeCompetitorInputs(url).length;
  const [clipboardFeedback, setClipboardFeedback] = useState<{ kind: "success" | "info" | "error"; message: string } | null>(null);

  async function handleClipboardAdd() {
    if (busy) return;
    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.readText) {
        setClipboardFeedback({ kind: "error", message: "当前浏览器无法读取剪贴板，请检查剪贴板权限" });
        return;
      }
      const clipboardValue = await navigator.clipboard.readText();
      if (parseCompetitorUrls(clipboardValue).length === 0) {
        setClipboardFeedback({ kind: "info", message: "剪贴板中没有可添加的内容" });
        return;
      }
      const merged = mergeCompetitorUrlText(url, clipboardValue);
      if (merged.addedCount === 0 && merged.duplicateCount > 0) {
        setClipboardFeedback({ kind: "info", message: "链接已存在，无需重复添加" });
        return;
      }
      if (merged.addedCount === 0) {
        setClipboardFeedback({ kind: "info", message: "剪贴板中没有可添加的内容" });
        return;
      }
      onUrlChange(merged.value);
      setClipboardFeedback({ kind: "success", message: `已添加 ${merged.addedCount} 条，过滤重复 ${merged.duplicateCount} 条` });
    } catch {
      setClipboardFeedback({ kind: "error", message: "无法读取剪贴板，请检查浏览器剪贴板权限" });
    }
  }

  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="dialog-title">添加监控商品</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={busy}>×</button></div>
    <p className="dialog-description">添加 1688 商品链接，系统会先确认真实店铺，再自动分流到我方商品或竞品列表。</p>
    <form onSubmit={onSubmit}><div className="dialog-field-header"><label htmlFor="competitor-url">1688 商品链接</label><button type="button" className="text-button clipboard-add-button" onClick={() => void handleClipboardAdd()} disabled={busy}>从剪贴板添加</button></div><textarea id="competitor-url" rows={5} value={url} onChange={(event) => { setClipboardFeedback(null); onUrlChange(event.target.value); }} placeholder={"https://detail.1688.com/offer/123456789.html\nhttps://detail.1688.com/offer/987654321.html"} autoComplete="off" spellCheck={false} autoCapitalize="none" autoCorrect="off" disabled={busy} /><p className="hint">每行一个链接，支持一次添加多个监控商品；仅支持 detail.1688.com/offer/{"{offerId}"}.html</p>{clipboardFeedback && <p className={"clipboard-feedback clipboard-feedback-" + clipboardFeedback.kind} role="status" aria-live="polite">{clipboardFeedback.message}</p>}<label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={groupId === null ? "" : String(groupId)} onChange={(event) => onGroupChange(event.target.value ? Number(event.target.value) : null)} disabled={busy || groupsStatus !== "ready"}>{groupsStatus === "ready" ? <><option value="">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</> : <option value={groupId === null ? "" : String(groupId)} disabled>{groupsStatus === "loading" ? "正在加载竞品组…" : "竞品组加载失败"}</option>}</select>{groupsStatus === "error" && <div className="feedback feedback-server-error" role="alert">{groupsError || "暂时无法获取竞品组。"}<button type="button" className="secondary-button" onClick={onRetryGroups} disabled={busy}>重试加载</button></div>}<label htmlFor="new-competitor-group">新增竞品组</label><div className="group-create-controls"><input id="new-competitor-group" type="text" value={newGroupName} onChange={(event) => onNewGroupNameChange(event.target.value)} placeholder="输入商品型号作为组名，例如 A19" maxLength={64} disabled={busy || groupsStatus !== "ready"} /><button type="button" className="secondary-button" onClick={onCreateGroup} disabled={busy || groupsStatus !== "ready" || groupCreateStatus === "submitting"}>{groupCreateStatus === "submitting" ? "创建中…" : "创建"}</button></div><div className={getGroupFeedbackClass(groupCreateStatus)} role="status" aria-live="polite">{groupCreateStatus === "success" && "竞品组已创建并已选中。"}{groupCreateStatus === "invalid" && "请输入有效的竞品组名称"}{groupCreateStatus === "duplicate" && "该竞品组已存在"}{groupCreateStatus === "server-error" && "竞品组创建失败，请稍后重试。"}</div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>取消</button><button type="submit" className="primary-button" disabled={busy || groupsStatus !== "ready" || urlCount === 0}>{busy ? (progress.total ? `正在添加 ${progress.completed} / ${progress.total}…` : "正在添加…") : urlCount > 1 ? `添加 ${urlCount} 个监控商品` : "添加监控商品"}</button></div></form>
    <div className={"feedback feedback-" + status} role="status" aria-live="polite">{status === "partial" && `已添加 ${succeededCount} 个，${failures.length} 个未添加`}{status === "failed" && `未添加 ${failures.length} 个监控商品`}{status === "invalid" && "链接无效：请输入指定格式的 1688 商品链接。"}{status === "duplicate" && "该 1688 商品已经添加。"}{status === "server-error" && "服务暂时不可用，请稍后重试。"}</div>
    {failures.length > 0 && <div className="add-failures" role="status" aria-live="polite"><strong>未添加：</strong><ul>{failures.map((failure, index) => <li key={index}>{failure.url} — {failure.reason}</li>)}</ul></div>}
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
  return <AppShell page="home" breadcrumb="首页" onNavigate={onNavigate}>
    <div className="workspace-home">
      <header className="home-heading">
        <div className="home-intro"><h1>首页</h1><p>从商品资料，<br />到竞争判断。</p><span>整理产品信息，跟进竞品变化。<br />在一个工作台，连接日常工作的每一步。</span></div>
        <div className="home-architecture" aria-hidden="true">
          <svg viewBox="0 0 440 232" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round">
            <path className="home-diagram-guide" d="M12 24h22m-11-11v22M406 208h22m-11-11v22M12 208h22m-11-11v22M406 24h22m-11-11v22M72 116h296" />
            <path className="home-diagram-wire" d="M85 114v49l135 58 135-58v-49M85 163l65-28m205 28-65-28M220 172v49" />
            <path className="home-diagram-base" d="m85 114 135-58 135 58-135 58Z" />
            <path className="home-diagram-layer" d="m117 100 103-44 103 44v26l-103 44-103-44Z" />
            <path className="home-diagram-face" d="m117 100 103 44 103-44M220 144v26" />
            <path className="home-diagram-core" d="m155 74 65-28 65 28v28l-65 28-65-28Z" />
            <path className="home-diagram-face" d="m155 74 65 28 65-28M220 102v28" />
            <path className="home-diagram-signal" d="m178 74 42-18 42 18-42 18ZM39 82h42l36 18m206 0 36-18h42" />
            <circle cx="39" cy="82" r="3" className="home-diagram-node" /><circle cx="401" cy="82" r="3" className="home-diagram-node" />
            <path className="home-diagram-guide" d="M185 193v8m18-1v8m34-8v8m18-15v8" />
            <text x="38" y="65" stroke="none">商品资料</text><text x="347" y="65" stroke="none">竞争情报</text>
          </svg>
        </div>
      </header>
      <div className="home-workspaces">
        <section className="home-monitoring" aria-labelledby="home-monitoring-title">
          <div className="home-tool-heading"><NavIcon name="monitoring" /><h2 id="home-monitoring-title">竞争情报</h2><span>竞品监控</span></div>
          <h3>先看变化，再查证据</h3>
          <p>从今日关注的商品组开始，进入组内比较，回到单品查看价格、库存与变化记录。</p>
          <button type="button" className="primary-button" onClick={() => onNavigate("dashboard")}>进入竞品监控大屏<HomeArrow /></button>
          <div className="home-monitoring-links" aria-label="竞品监控快捷入口">
            <button type="button" onClick={() => onNavigate("own-products")}><strong>我方商品</strong><span>管理监控与分组</span><HomeArrow /></button>
            <button type="button" onClick={() => onNavigate("competitors")}><strong>竞品列表</strong><span>查找商品与证据</span><HomeArrow /></button>
            <button type="button" onClick={() => onNavigate("groups")}><strong>竞品分组</strong><span>组织同组商品比较</span><HomeArrow /></button>
            <button type="button" onClick={() => onNavigate("collection-tasks")}><strong>采集记录</strong><span>核查采集过程与结果</span><HomeArrow /></button>
          </div>
        </section>
        <section className="home-library" aria-labelledby="home-library-title">
          <div className="home-tool-heading"><NavIcon name="library" /><h2 id="home-library-title">商品资料</h2><span>产品库</span></div>
          <h3>让产品资料有处可查</h3>
          <p>集中整理产品与厂家信息，查找规格、图片和报价资料，为后续工作准备可靠依据。</p>
          <button type="button" className="secondary-button" onClick={() => onNavigate("product-library")}>打开产品库<HomeArrow /></button>
          <div className="home-library-guide"><span>资料导入</span><span>字段核对</span><span>客户报价</span></div>
        </section>
      </div>
      <section className="home-task-section" aria-labelledby="home-task-title"><div><h2 id="home-task-title">开始之前</h2><p>让监控商品正确识别我方身份。</p></div><button type="button" className="home-settings-link" onClick={() => onNavigate("settings")}><NavIcon name="settings" /><span><strong>配置我方店铺与采集策略</strong><small>前往系统设置</small></span><HomeArrow /></button></section>
      <section className="home-planned" aria-labelledby="home-planned-title"><div><h2 id="home-planned-title">工具拓展</h2><span>规划中，尚未开放</span></div><ul><li><NavIcon name="assistant" />AI智能助手</li><li><NavIcon name="compare" />全网比价</li><li><NavIcon name="inquiry" />自动询价</li><li><NavIcon name="listing" />自动上架</li></ul></section>
    </div>
  </AppShell>;
}

function HomeArrow() { return <svg className="home-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5" /></svg>; }


type AddInputSummary = { total: number; candidate_total: number | null; processed: number; remaining: number; pending: number; added: number; business_rejected: number; technical_failed: number; verification_required: number; interrupted: number; not_executed: number; anomaly_inputs: number };
type BatchObservation = { metric_key: string; status: string; raw_value: string | null; reason: string | null; source?: string; observed_at?: string };
type BatchAttempt = { id: number; attempt_number: number | null; attempt_kind: string | null; started_at: string | null; finished_at: string | null; status: string; operating_metrics_status: string; error_message: string | null; navigation_claimed_at?: string | null; navigation_confirmed_at?: string | null; duration_seconds?: number | null; observations: BatchObservation[] };
type BatchRecord = { task_kind?: "add_links" | "collect_products"; input_summary?: AddInputSummary; anomaly_products?: number; technical_exception_products?: number; task_id: string; trigger_kind: string; started_at: string | null; finished_at: string | null; lifecycle_status: string; outcome_code: string | null; planned_products: number; completed: number; remaining: number; counts: Record<string, number>; page_visits: number; page_visits_unknown: number; verification_resume_visits: number; retry_visits: number };
type BatchRecordItem = { input_text?: string | null; source_line?: number; result_code?: string | null; sanitized_reason?: string | null; navigation_claimed_at?: string | null; navigation_confirmed_at?: string | null; identity_state?: string; operating_metrics_status?: string; position: number; competitor_id: number | null; offer_id: string | null; main_image_url: string | null; title: string | null; shop_name: string | null; final_result: string | null; base_result: string | null; attempts_started: number; page_visits: number; page_visits_unknown: number; retry_visits: number; technical_exception_count: number; attempts: BatchAttempt[]; identity_removed: boolean; had_anomaly: boolean; has_anomaly: boolean; duration_seconds: number | null };
type BatchRecordPage = { items: BatchRecord[]; total: number; page: number; page_size: number };
type BatchRecordDetail = BatchRecord & { summary: BatchRecord; items: BatchRecordItem[]; total: number; page: number; page_size: number; protection_details: string | null; circuit_breaker_cancelled: number };
type CollectionTaskProps = { onNavigate: (page: Page) => void; batchState?: BatchState; batchStatus?: ListStatus; batchError?: string | null; onRefreshBatch?: () => Promise<boolean> };
const collectionFieldLabels: Record<string, string> = { listing_time: "上架时间", monthly_deal: "月成交", monthly_dropship: "月分销代发", annual_units: "年成交件数", annual_orders: "年成交订单数", review_count: "评价数", positive_rate: "好评率", pickup_rate: "揽收率" };
const batchResultLabels: Record<string, string> = { first_pass_success: "成功", verification_resume_success: "验证恢复成功", retry_success: "补采恢复成功", final_failed: "异常", verification_required: "需要人工验证", not_executed: "未执行" };
const batchTriggerLabels: Record<string, string> = { manual_selected: "手动选择采集", manual_all_active: "手动全部在监控", scheduled: "定时采集" };
Object.assign(batchTriggerLabels, { manual_single: "手动采集", manual_selected: "手动采集", manual_all_active: "手动采集", scheduled: "定时采集", add_links: "添加链接" });
const batchOutcomeLabels: Record<string, string> = { success: "成功", partial_success: "部分成功", partial_failure: "部分失败", user_ended: "用户结束", verification_required: "需要人工验证", collect_failed: "采集失败", infrastructure_error: "运行异常", interrupted: "进程中断" };
const batchAttemptKindLabels: Record<string, string> = { first_pass: "首次采集", verification_resume: "验证恢复", operating_metrics_retry: "经营指标补采" };
const observationStatusLabels: Record<string, string> = { observed: "已读取", placeholder: "页面占位 -，无需补采", loading: "加载未完成", source_unavailable: "来源不可用", read_failed: "字段读取失败" };
const recordOperatingLabels: Record<string, string> = { not_attempted: "尚未读取经营指标", success: "经营指标完整", partial: "经营部分指标可用", no_values: "页面没有有效经营值", failed: "经营指标读取异常", blocked: "经营指标读取已阻止" };
const technicalStatuses = new Set(["source_unavailable", "loading", "read_failed"]);
const batchTitle = (batch: Pick<BatchRecord, "outcome_code" | "lifecycle_status" | "input_summary">) => batch.input_summary && batch.lifecycle_status === "terminal" && !["infrastructure_error", "interrupted", "verification_required", "user_ended"].includes(batch.outcome_code || "") ? batch.input_summary.added === batch.input_summary.total ? "全部新增" : batch.input_summary.added ? "部分新增成功" : batch.input_summary.technical_failed ? "添加失败" : "未新增" : batch.outcome_code ? batchOutcomeLabels[batch.outcome_code] || "终态未知" : ["running", "created"].includes(batch.lifecycle_status) ? "进行中" : "状态未知";
const successfulProducts = (batch: BatchRecord) => batch.input_summary ? batch.input_summary.added : ["first_pass_success", "verification_resume_success", "retry_success"].reduce((n, key) => n + (batch.counts[key] || 0), 0);
const exceptionProducts = (batch: BatchRecord) => batch.input_summary ? batch.anomaly_products ?? batch.input_summary.anomaly_inputs : (batch.counts.final_failed || 0) + (batch.counts.verification_required || 0);
export function collectionDuration(start: string | null, finish: string | null, running = false): string {
  if (!start) return "开始时间缺失";
  if (!finish) return running ? "进行中" : "结束时间缺失";
  const seconds = (Date.parse(finish) - Date.parse(start)) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return "时间信息不足";
  return formatCollectionDuration(seconds);
}
export function formatCollectionDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  return total >= 3600 ? `${Math.floor(total / 3600)}小时${Math.floor(total % 3600 / 60)}分${total % 60}秒` : total >= 60 ? `${Math.floor(total / 60)}分${total % 60}秒` : `${total}秒`;
}
export function attemptSummary(attempt: BatchAttempt): string {
  const groups = new Map<string, number>();
  for (const field of attempt.observations || []) if (technicalStatuses.has(field.status)) groups.set(field.status, (groups.get(field.status) || 0) + 1);
  if (groups.size) return [...groups].map(([status, count]) => `${status === "source_unavailable" ? "官方采购助手来源不可用" : observationStatusLabels[status]}，影响 ${count} 项指标`).join("；");
  if (attempt.status === "failed") return attempt.error_message || "基础商品读取失败";
  return "—";
}
function AttemptHistory({ attempts }: { attempts: BatchAttempt[] }) {
  return <div className="record-attempts table-scroll"><table><thead><tr><th>尝试轮次</th><th>尝试类型</th><th>开始时间</th><th>页面访问事实</th><th title="从本轮真实开始到结束">本轮耗时</th><th>基础采集结果</th><th>经营指标结果 / 字段异常摘要</th></tr></thead><tbody>{attempts.map(attempt => {
    const observed = attempt.observations.filter(field => field.status === "observed").length;
    const placeholder = attempt.observations.filter(field => field.status === "placeholder").length;
    return <Fragment key={attempt.id}>
      <tr><td>第 {attempt.attempt_number ?? 1} 轮</td><td>{batchAttemptKindLabels[attempt.attempt_kind || ""] || "单次采集"}</td><td className="record-attempt-time">{formatDate(attempt.started_at)}</td><td>{attempt.navigation_confirmed_at ? "已确认 1 次" : attempt.navigation_claimed_at ? "已发起，次数未知" : "无已确认访问证据"}</td><td>{attempt.finished_at && attempt.started_at ? collectionDuration(attempt.started_at, attempt.finished_at) : "—"}</td><td>{attempt.status === "success" ? "基础采集成功" : attempt.status === "failed" ? "基础采集失败" : "进行中"}</td><td><span>{recordOperatingLabels[attempt.operating_metrics_status] || "经营状态未知"}</span>{attempt.observations.length > 0 && <small>{observed} 项已读取 · {placeholder} 项页面占位</small>}<small>{attemptSummary(attempt)}</small>{attempt.observations.length === 0 && <small>本轮没有经营字段观测记录</small>}</td></tr>
      {attempt.observations.length > 0 && <tr className="record-field-row"><td colSpan={7}><details><summary title="悬停经营指标状态可查看来源与观察时间">查看 {attempt.observations.length} 项字段明细</summary><table className="record-fields"><thead><tr><th>字段名称</th><th>原始页面值</th><th>字段状态</th><th>缺失 / 失败原因</th></tr></thead><tbody>{attempt.observations.map(field => <tr key={field.metric_key}><td>{collectionFieldLabels[field.metric_key] || "经营字段"}</td><td>{field.raw_value ?? "未采集"}</td><td title={`来源：${field.source || "—"}；观察时间：${field.observed_at ? formatDate(field.observed_at) : "—"}`}>{observationStatusLabels[field.status] || "未知"}</td><td>{field.status === "placeholder" ? "页面显示 -，无需补采" : field.reason || "—"}</td></tr>)}</tbody></table></details></td></tr>}
    </Fragment>;
  })}</tbody></table></div>;
}
const recordMetricIcons: Record<string, ReactNode> = {
  plan: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h4M9 12h6M9 16h6" /></>,
  rejected: <><circle cx="12" cy="12" r="9" /><path d="M8 12h8" /></>,
  success: <><circle cx="12" cy="12" r="9" /><path d="m7 12 3 3 7-7" /></>,
  anomaly: <><circle cx="12" cy="12" r="9" /><path d="M12 6v7M12 17h.01" /></>,
  visits: <><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12" /><circle cx="12" cy="12" r="3" /></>,
  retry: <><path d="M19 8a8 8 0 1 0 1 8M19 3v5h-5" /></>,
  time: <><circle cx="12" cy="12" r="9" /><path d="M12 6v6l4 2" /></>,
  state: <><path d="M8 6h12M8 12h12M8 18h12M3 6h1M3 12h1M3 18h1" /></>,
};
function RecordSummary({ detail }: { detail: BatchRecordDetail }) {
  const summary = detail.summary;
  if (detail.input_summary) {
    const input = detail.input_summary;
    const anomalies = detail.anomaly_products ?? input.anomaly_inputs;
    const active = ["created", "running"].includes(detail.lifecycle_status);
    const stateTone = active ? "blue" : detail.outcome_code === "success" ? "green" : ["partial_success", "partial_failure", "user_ended", "verification_required"].includes(detail.outcome_code || "") ? "orange" : anomalies > 0 || ["collect_failed", "infrastructure_error"].includes(detail.outcome_code || "") ? "red" : "neutral";
    const metrics = [
      { label: "提交链接", value: input.total, icon: "plan", tone: "neutral" },
      { label: "新增成功", value: input.added, icon: "success", tone: "green" },
      { label: "业务拒绝", value: input.business_rejected, icon: "rejected", tone: input.business_rejected ? "orange" : "neutral" },
      { label: "异常商品", value: anomalies, icon: "anomaly", tone: anomalies ? "red" : "neutral" },
      { label: "页面访问", value: summary.page_visits, icon: "visits", tone: "neutral" },
      { label: "耗时", value: collectionDuration(detail.started_at, detail.finished_at, active), icon: "time", tone: "neutral" },
      { label: "任务状态", value: batchTitle(detail), icon: "state", tone: stateTone },
    ];
    return <section className="table-card record-summary record-summary-add" aria-label="批次汇总">
      {metrics.map(metric => <div key={metric.label} className={`record-metric record-metric-${metric.tone}`}><span className="record-metric-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{recordMetricIcons[metric.icon]}</svg></span><div className="record-metric-value"><span>{metric.label}</span><strong>{metric.value}</strong></div></div>)}
      <p className="record-summary-note">候选商品 {detail.planned_products} · 技术失败 <span className={input.technical_failed ? "record-summary-alert" : ""}>{input.technical_failed}</span> · 经营异常 <span className={detail.technical_exception_products ? "record-summary-alert" : ""}>{detail.technical_exception_products ?? 0}</span> · 需要验证 {input.verification_required} · 中断 {input.interrupted} · 未执行 {input.not_executed} · 未知访问 {summary.page_visits_unknown}</p>
    </section>;
  }
  const anomalies = exceptionProducts(summary);
  const active = ["created", "running"].includes(detail.lifecycle_status);
  const stateTone = active ? "blue" : detail.outcome_code === "success" ? "green" : ["partial_success", "partial_failure", "user_ended", "verification_required"].includes(detail.outcome_code || "") ? "orange" : anomalies > 0 || ["collect_failed", "infrastructure_error"].includes(detail.outcome_code || "") ? "red" : "neutral";
  const metrics = [
    { label: "计划商品", value: summary.planned_products, icon: "plan", tone: "neutral" },
    { label: "成功", value: successfulProducts(summary), icon: "success", tone: "green" },
    { label: "异常", value: anomalies, icon: "anomaly", tone: anomalies ? "red" : "neutral" },
    { label: "页面访问", value: summary.page_visits, icon: "visits", tone: "neutral" },
    { label: "补采访问", value: summary.retry_visits, icon: "retry", tone: "purple" },
    { label: "耗时", value: collectionDuration(detail.started_at, detail.finished_at, active), icon: "time", tone: "neutral" },
    { label: "任务状态", value: batchTitle(detail), icon: "state", tone: stateTone },
  ];
  return <section className="table-card record-summary" aria-label="批次汇总">
    {metrics.map(metric => <div key={metric.label} className={`record-metric record-metric-${metric.tone}`}><span className="record-metric-icon" aria-hidden="true"><svg viewBox="0 0 24 24">{recordMetricIcons[metric.icon]}</svg></span><div className="record-metric-value"><span>{metric.label}</span><strong>{metric.value}</strong></div></div>)}
    <p className="record-summary-note">完成 {summary.completed} / {summary.planned_products} · 剩余 {summary.remaining} · 未执行 {summary.counts.not_executed || 0} · 未知访问 {summary.page_visits_unknown} · 验证恢复访问 {summary.verification_resume_visits}（不计经营补采）</p>
  </section>;
}
const initialRecordFilters = () => {
  return { start: "", end: "", trigger_kind: "all", anomaly: "all" };
};
const emptyItemFilters = { search: "", final_result: "all", anomaly: "all", attempt_kind: "all", reason: "all", anomalies_first: "false" };
function RecordSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: [string, string][] }) {
  return <label>{label}<select value={value} onChange={event => onChange(event.target.value)}>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>;
}
function RecordState({ status, error, retry }: { status: ListStatus; error: string | null; retry: () => void }) {
  return status === "loading" ? <div className="state-panel"><div className="spinner" /><strong role="status" aria-live="polite">正在加载采集记录…</strong></div> : status === "error" ? <div className="state-panel state-error" role="alert"><strong>采集记录加载失败</strong><span>{error}</span><button className="secondary-button" onClick={retry}>重试</button></div> : null;
}
function RecordBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) { return <span className={`record-badge record-badge-${tone}`}>{children}</span>; }
const inputResultLabels: Record<string, string> = { added: "新增成功", invalid_url: "链接无效", duplicate_input: "提交内重复（历史）", already_exists: "商品已存在", identity_rejected: "身份或归组拒绝", technical_failed: "技术失败", verification_required: "需要验证", not_executed: "未执行", interrupted: "中断，结果未知" };
const anomalyOptions: [string, string][] = [["all", "全部"], ["current", "当前有异常"], ["none", "无当前异常"], ["recovered", "曾异常但已恢复"], ["placeholder", "页面占位"], ["source_unavailable", "官方助手来源不可用"], ["loading", "加载未完成"], ["read_failed", "字段读取失败"], ["base_failed", "基础采集失败"], ["rejected", "业务拒绝"], ["verification_required", "需要验证"]];
export function allowedRecordAnomalies(trigger: string) {
  return anomalyOptions.filter(([key]) => trigger === "add_links" ? ["all", "current", "none", "base_failed", "rejected", "verification_required", "placeholder", "source_unavailable", "loading", "read_failed"].includes(key) : trigger === "all" || key !== "rejected");
}
function AddInputTable({ detail, expanded, onToggle }: { detail: BatchRecordDetail; expanded: Set<number>; onToggle: (position: number) => void }) {
  return <div className="table-scroll"><table className="record-table record-product-table record-add-table"><thead><tr><th>商品信息</th><th>新增结果</th><th>页面访问</th><th>耗时</th><th>经营指标</th><th>操作</th></tr></thead><tbody>{detail.items.map(item => {
    const isExpanded = expanded.has(item.position);
    const productTitle = item.identity_removed ? "商品已删除" : item.title || (item.offer_id ? `Offer ID ${item.offer_id}` : item.input_text || "商品资料未获取");
    const resultTone = item.result_code === "added" ? item.has_anomaly ? "warning" : "success" : ["technical_failed", "verification_required", "interrupted"].includes(item.result_code || "") ? "danger" : "neutral";
    const metricTone = item.technical_exception_count > 0 || ["failed", "blocked"].includes(item.operating_metrics_status || "") ? "danger" : item.operating_metrics_status === "partial" ? "warning" : item.operating_metrics_status === "success" ? "success" : "neutral";
    return <Fragment key={item.position}>
      <tr>
        <td><div className="product-cell record-add-product">{!item.identity_removed && item.main_image_url && <ProductImage competitor={{ main_image_url: item.main_image_url }} />}<div><strong title={productTitle}>{productTitle}</strong>{item.identity_removed ? <small>第 {item.source_line ?? item.position + 1} 行 · 身份已移除</small> : <small>Offer ID：{item.offer_id || "未识别"} · 店铺：{item.shop_name || "未采集"}</small>}</div></div></td>
        <td><RecordBadge tone={resultTone}>{inputResultLabels[item.result_code || ""] || "待处理"}</RecordBadge>{item.sanitized_reason && item.sanitized_reason !== (inputResultLabels[item.result_code || ""] || "待处理") && <small className="record-add-reason" title={item.sanitized_reason}>{item.sanitized_reason}</small>}</td>
        <td>确认 {item.page_visits} 次{item.page_visits_unknown > 0 && <small>未知 {item.page_visits_unknown} 次</small>}</td>
        <td>{formatCollectionDuration(item.duration_seconds)}</td>
        <td><RecordBadge tone={metricTone}>{recordOperatingLabels[item.operating_metrics_status || "not_attempted"] || "经营状态未知"}</RecordBadge>{item.technical_exception_count > 0 && <small>技术异常 {item.technical_exception_count} 项</small>}</td>
        <td><button className="text-button" aria-expanded={isExpanded} aria-label={`${isExpanded ? "收起" : "展开"} ${productTitle}`} onClick={() => onToggle(item.position)}>{isExpanded ? "收起 ∧" : "展开 ∨"}</button></td>
      </tr>
      {isExpanded && <tr className="record-add-detail-row"><td colSpan={6}><div className="record-add-detail"><div className="record-add-input"><strong>第 {item.source_line ?? item.position + 1} 行 · 原始输入</strong><span title={item.identity_removed ? undefined : item.input_text || undefined}>{item.identity_removed ? "商品身份已移除" : item.input_text || "—"}</span></div>{item.attempts.length > 0 ? <AttemptHistory attempts={item.attempts} /> : <div className="detail-empty">{item.identity_removed ? "商品身份已移除，匿名处理事实仍保留。" : "无商品采集 Run；保留输入处理事实。"}</div>}</div></td></tr>}
    </Fragment>;
  })}</tbody></table></div>;
}
export function CollectionTasksPage({ onNavigate }: CollectionTaskProps) {
  const [filters, setFilters] = useState(initialRecordFilters);
  const [filterNotice, setFilterNotice] = useState("");
  const [page, setPage] = useState(1);
  const [records, setRecords] = useState<BatchRecordPage | null>(null);
  const [selected, setSelected] = useState<{ id: string; kind: "batch" } | null>(null);
  const [itemFilters, setItemFilters] = useState(emptyItemFilters);
  const [itemSearchText, setItemSearchText] = useState("");
  const [itemSearchComposing, setItemSearchComposing] = useState(false);
  const [itemPage, setItemPage] = useState(1);
  const [detail, setDetail] = useState<BatchRecordDetail | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [status, setStatus] = useState<ListStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [loadedQuery, setLoadedQuery] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const changeFilters = (patch: Partial<typeof filters>) => {
    const next = { ...filters, ...patch };
    const compatible = allowedRecordAnomalies(next.trigger_kind).some(([key]) => key === next.anomaly);
    setFilterNotice(compatible ? "" : "该触发方式不适用此异常类别，已恢复为全部异常情况。");
    setFilters({ ...next, anomaly: compatible ? next.anomaly : "all" });
    setPage(1);
  };
  const changeItemFilters = (patch: Partial<typeof itemFilters>) => { setItemFilters(current => ({ ...current, ...patch })); setItemPage(1); setExpanded(new Set()); };
  useEffect(() => {
    if (!selected || itemSearchComposing || itemSearchText === itemFilters.search) return;
    const timer = window.setTimeout(() => { setItemFilters(current => ({ ...current, search: itemSearchText })); setItemPage(1); setExpanded(new Set()); }, 350);
    return () => window.clearTimeout(timer);
  }, [selected, itemFilters.search, itemSearchText, itemSearchComposing]);
  const datesValid = (!filters.start || !Number.isNaN(Date.parse(`${filters.start}T00:00:00`))) && (!filters.end || !Number.isNaN(Date.parse(`${filters.end}T00:00:00`))) && (!filters.start || !filters.end || filters.start <= filters.end);
  let requestUrl: string | null = null;
  if (selected) {
    requestUrl = `/api/collection-batches/${encodeURIComponent(selected.id)}?${new URLSearchParams({ ...itemFilters, page: String(itemPage), page_size: "10" })}`;
  } else if (datesValid) {
    const params = new URLSearchParams({ page: String(page), page_size: "20", trigger_kind: filters.trigger_kind, anomaly: filters.anomaly });
    if (filters.start) params.set("started_after", new Date(`${filters.start}T00:00:00`).toISOString());
    if (filters.end) params.set("started_before", new Date(`${filters.end}T23:59:59.999`).toISOString());
    requestUrl = `/api/collection-batches?${params}`;
  }
  useEffect(() => {
    if (!requestUrl) return;
    const controller = new AbortController();
    setStatus("loading"); setError(null);
    void fetch(requestUrl, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error("查询失败，请稍后重试");
      const value = await response.json();
      if (controller.signal.aborted) return;
      if (!Array.isArray(value?.items) || !Number.isInteger(value.total) || value.total < 0 || !Number.isInteger(value.page_size) || value.page_size <= 0 || (selected ? !value.summary?.counts : value.items.some((item: BatchRecord) => !item.counts))) throw new Error("采集记录响应格式不正确，请重试");
      const lastPage = Math.max(1, Math.ceil(value.total / value.page_size));
      if ((selected ? itemPage : page) > lastPage) { if (selected) setItemPage(lastPage); else setPage(lastPage); setExpanded(new Set()); return; }
      if (selected) setDetail(value); else setRecords(value);
      setLoadedQuery(requestUrl); setStatus("ready");
    }).catch(reason => { if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "查询失败"); setLoadedQuery(requestUrl); setStatus("error"); } });
    return () => controller.abort();
  }, [requestUrl, selected, page, itemPage, refresh]);
  const searchPending = !!selected && (itemSearchComposing || itemSearchText !== itemFilters.search);
  const viewStatus = !requestUrl ? "ready" : searchPending || loadedQuery !== requestUrl ? "loading" : status;
  const open = (id: string) => { setDetail(null); setExpanded(new Set()); setItemSearchText(""); setItemSearchComposing(false); setItemFilters(emptyItemFilters); setItemPage(1); setSelected({ id, kind: "batch" }); };
  const totalPages = records ? Math.max(1, Math.ceil(records.total / records.page_size)) : 1;
  const itemPages = detail ? Math.max(1, Math.ceil(detail.total / detail.page_size)) : 1;
  const adding = detail?.task_kind === "add_links";
  const title = selected ? "批次详情" : "采集记录";
  return <AppShell page="collection-tasks" onNavigate={onNavigate} breadcrumb={selected ? `采集记录 / ${title}` : "采集记录"}>
    <div className="collection-records"><header className="page-header"><div><h1>{title}</h1><p className="page-description">{selected && detail ? `${batchTriggerLabels[detail.trigger_kind]} · ${formatDate(detail.started_at)} · ${batchTitle(detail)}` : "按每次采集任务查看结果、耗时与异常情况。"}</p></div>{selected && <button className="secondary-button" onClick={() => { setSelected(null); setDetail(null); }}>← 返回采集记录</button>}</header>
    {!selected && <div className="table-card record-filters"><div className="record-date-range"><label>开始日期<input type="date" value={filters.start} onChange={event => changeFilters({ start: event.target.value })} /></label><label>结束日期<input type="date" value={filters.end} min={filters.start} onChange={event => changeFilters({ end: event.target.value })} /></label></div>
      <RecordSelect label="触发方式" value={filters.trigger_kind} onChange={trigger_kind => changeFilters({ trigger_kind })} options={[["all", "全部"], ["manual", "手动采集"], ["scheduled", "定时采集"], ["add_links", "添加链接"]]} />
      <RecordSelect label="异常情况" value={filters.anomaly} onChange={anomaly => changeFilters({ anomaly })} options={allowedRecordAnomalies(filters.trigger_kind)} />
      <button className="secondary-button" onClick={() => { setFilters(initialRecordFilters()); setFilterNotice(""); setPage(1); }}>清除筛选</button>{filterNotice && <p role="status">{filterNotice}</p>}{!datesValid && <p role="alert" className="record-date-error">请输入有效日期，开始日期不能晚于结束日期。</p>}
    </div>}
    {selected && detail && <RecordSummary detail={detail} />}
    {selected && <div className="table-card record-filters record-item-filters"><label className="record-search">关键词<input value={itemSearchText} onChange={event => setItemSearchText(event.target.value)} onCompositionStart={() => setItemSearchComposing(true)} onCompositionEnd={event => { setItemSearchText(event.currentTarget.value); setItemSearchComposing(false); }} placeholder="搜索商品 / Offer / 店铺" /></label>
      <RecordSelect label="最终结果" value={itemFilters.final_result} onChange={final_result => changeItemFilters({ final_result })} options={[["all", "全部"], ["success", "成功"], ["exception", "异常"], ["not_executed", "未执行"], ...(adding ? [["business_rejected", "业务拒绝"]] as [string, string][] : [["verification_required", "需要人工验证"]] as [string, string][]), ["pending", "进行中"]]} />
      <RecordSelect label={adding ? "异常 / 经营状态" : "是否异常"} value={itemFilters.anomaly} onChange={anomaly => changeItemFilters({ anomaly })} options={adding ? [["all", "全部"], ["current", "当前有异常"], ["none", "无当前异常"], ["base_failed", "基础商品失败"], ["placeholder", "页面占位"], ["source_unavailable", "来源不可用"], ["loading", "加载未完成"], ["read_failed", "字段读取失败"], ["rejected", "业务拒绝"], ["verification_required", "需要验证"]] : [["all", "全部"], ["current", "当前有异常"], ["recovered", "曾异常但已恢复"], ["none", "无技术异常"]]} />
      {!adding && <><RecordSelect label="尝试类型" value={itemFilters.attempt_kind} onChange={attempt_kind => changeItemFilters({ attempt_kind })} options={[["all", "全部"], ...Object.entries(batchAttemptKindLabels)]} /><RecordSelect label="异常原因" value={itemFilters.reason} onChange={reason => changeItemFilters({ reason })} options={[["all", "全部"], ["placeholder", "页面占位（非技术异常）"], ["source_unavailable", "官方助手来源不可用"], ["loading", "加载未完成"], ["read_failed", "字段读取失败"], ["base_failed", "基础商品读取失败"]]} /></>}
      <button className="secondary-button" onClick={() => { setItemFilters(emptyItemFilters); setItemSearchText(""); setItemSearchComposing(false); setItemPage(1); setExpanded(new Set()); }}>重置</button><label className="record-sort"><input type="checkbox" checked={itemFilters.anomalies_first === "true"} onChange={event => changeItemFilters({ anomalies_first: String(event.target.checked) })} />异常优先</label>
    </div>}
    <RecordState status={viewStatus} error={error} retry={() => setRefresh(refresh + 1)} />
    {viewStatus === "ready" && requestUrl && !selected && records && <section className="table-card"><div className="table-scroll"><table className="record-table"><thead><tr>{["开始时间", "触发方式", "计划商品 / 提交链接", "成功", "异常", "页面访问", "补采访问", "耗时", "任务状态", "操作"].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{records.items.map(batch => <tr key={batch.task_id}><td title={batch.task_id}>{formatDate(batch.started_at)}</td><td>{batchTriggerLabels[batch.trigger_kind] || "手动采集"}</td><td>{batch.input_summary ? <>提交 {batch.input_summary.total} 条</> : batch.planned_products}</td><td className="record-success">{successfulProducts(batch)}</td><td className={exceptionProducts(batch) ? "record-error" : ""}>{exceptionProducts(batch)}</td><td>{batch.page_visits}{batch.page_visits_unknown > 0 && <small>另 {batch.page_visits_unknown} 次未知</small>}</td><td>{batch.retry_visits}</td><td>{collectionDuration(batch.started_at, batch.finished_at, ["created", "running"].includes(batch.lifecycle_status))}</td><td><RecordBadge tone={exceptionProducts(batch) ? "warning" : batch.outcome_code === "success" ? "success" : "neutral"}>{batchTitle(batch)}</RecordBadge></td><td><button className="secondary-button" onClick={() => open(batch.task_id)}>查看详情</button></td></tr>)}</tbody></table></div>{records.items.length === 0 && <div className="detail-empty">暂无符合条件的采集记录，可清除筛选后重试。</div>}<PaginationBar total={records.total} itemLabel="条记录" pageSize={records.page_size} page={records.page} totalPages={totalPages} onPrevious={() => setPage(page - 1)} onNext={() => setPage(page + 1)} previousDisabled={page <= 1} nextDisabled={page >= totalPages} /></section>}
    {viewStatus === "ready" && selected && detail && adding && <section className="table-card"><AddInputTable detail={detail} expanded={expanded} onToggle={position => setExpanded(current => { const next = new Set(current); if (next.has(position)) next.delete(position); else next.add(position); return next; })} />{detail.total === 0 && <div className="detail-empty">没有符合条件的输入</div>}<PaginationBar total={detail.total} itemLabel="条输入" pageSize={detail.page_size} page={itemPage} totalPages={itemPages} onPrevious={() => { setItemPage(itemPage - 1); setExpanded(new Set()); }} onNext={() => { setItemPage(itemPage + 1); setExpanded(new Set()); }} previousDisabled={itemPage <= 1} nextDisabled={itemPage >= itemPages} /></section>}
    {viewStatus === "ready" && requestUrl !== null && selected && detail && detail.task_kind !== "add_links" && <>{detail.protection_details && <p className="collection-batch-notice">{detail.protection_details} · 已取消补采 {detail.circuit_breaker_cancelled}</p>}<section className="table-card"><div className="table-scroll"><table className="record-table record-product-table"><thead><tr>{["商品信息", "最终结果", "尝试次数", "页面访问数", "耗时", "异常摘要", "操作"].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{detail.items.map(item => <Fragment key={item.position}><tr><td><div className="product-cell"><ProductImage competitor={{ main_image_url: item.main_image_url }} /><div><strong>{item.identity_removed ? "商品已删除" : item.title || "标题未采集"}</strong>{item.identity_removed ? <small>字段明细已随商品删除</small> : <small>Offer ID：{item.offer_id || "未采集"} ｜ 店铺：{item.shop_name || "未采集"}</small>}</div></div></td><td><RecordBadge tone={item.final_result === "final_failed" ? "danger" : item.has_anomaly ? "warning" : item.final_result?.includes("success") ? "success" : "neutral"}>{batchResultLabels[item.final_result || ""] || "进行中"}</RecordBadge></td><td>{item.attempts_started}</td><td>{item.page_visits}{item.page_visits_unknown > 0 && <small>另 {item.page_visits_unknown} 次未知</small>}</td><td title="该商品本批次首次尝试到最终结果确定的历时，包含跨队列等待，不是连续页面加载时间">{formatCollectionDuration(item.duration_seconds)}</td><td className="record-anomaly">{item.has_anomaly ? item.final_result === "verification_required" ? "需要人工验证" : item.attempts.length ? attemptSummary([...item.attempts].reverse().find(attempt => attemptSummary(attempt) !== "—") || item.attempts[item.attempts.length - 1]) : "最终异常（字段已删除）" : item.had_anomaly ? "历史技术异常已恢复" : "—"}</td><td><button className="text-button" aria-expanded={expanded.has(item.position)} aria-label={`${expanded.has(item.position) ? "收起" : "展开"} ${item.title || "商品已删除"}`} onClick={() => setExpanded(previous => { const next = new Set(previous); if (next.has(item.position)) next.delete(item.position); else next.add(item.position); return next; })}>{expanded.has(item.position) ? "收起 ∧" : "展开 ∨"}</button></td></tr>{expanded.has(item.position) && <tr><td colSpan={7}>{item.attempts.length ? <AttemptHistory attempts={item.attempts} /> : <div className="detail-empty">{item.identity_removed ? "商品已删除，字段明细已随商品删除；匿名汇总仍保留。" : "尚无采集尝试"}</div>}</td></tr>}</Fragment>)}</tbody></table></div>{detail.items.length === 0 && <div className="detail-empty">没有符合条件的商品，可重置筛选后重试。</div>}<PaginationBar total={detail.total} itemLabel="个商品" pageSize={detail.page_size} page={detail.page} totalPages={itemPages} onPrevious={() => { setItemPage(itemPage - 1); setExpanded(new Set()); }} onNext={() => { setItemPage(itemPage + 1); setExpanded(new Set()); }} previousDisabled={itemPage <= 1} nextDisabled={itemPage >= itemPages} /></section></>}

    <p className="record-duration-note">采集耗时包含等待与补采；页面显示 - 不属于技术异常。<span className="record-help" tabIndex={0} title="任务：真实开始到结束；商品：本任务首次尝试到可信终态；单轮：真实开始到结束。缺少可信时间时显示 —。">耗时与记录说明 ⓘ</span></p></div>
  </AppShell>;
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
  onReset: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  onNavigate: (page: Page) => void;
  basicDirty: boolean;
  monitoringDirty: boolean;
  monitoring: CompetitorMonitoringSettings | null;
  monitoringStatus: ListStatus;
  monitoringError: string | null;
  monitoringSaveError: string | null;
  monitoringSubmitting: boolean;
  onMonitoringChange: (value: CompetitorMonitoringSettings) => void;
  onMonitoringOpen: () => void;
  onMonitoringRetry: () => void;
  onMonitoringReset: () => void;
  onMonitoringSave: (event: FormEvent<HTMLFormElement>) => void;
};

type CompetitorMonitoringSettings = { item_interval_seconds: number; continuous_collection_count: number; batch_rest_seconds: number; verification_cooldown_seconds: number; auto_resume_max: number; operating_metrics_retry_max: number; auto_collection_enabled: boolean; auto_collection_strategy: "rolling_24h" | "fixed_daily" | "fixed_interval"; auto_collection_time: string; auto_collection_times: string[]; auto_collection_interval_hours: number; auto_collection_daily_limit: number; auto_collection_missed_policy: "catch_up" | "skip" };

function WorkBrowserSettings({ onStatus }: { onStatus: (status: string) => void }) {
  const [state, setState] = useState<{ status: string; message: string }>({ status: "unknown", message: "" });
  const [pending, setPending] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/api/work-browser");
        if (!response.ok) throw new Error();
        const result = await response.json();
        if (active) setState(result);
      } catch { if (active) setState({ status: "unknown", message: "无法读取浏览器状态。" }); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const open = async (extensions = false) => {
    setPending(true);
    try {
      const response = await fetch(extensions ? "/api/work-browser/extensions" : "/api/work-browser", { method: "POST", headers: { "Content-Type": "application/json", "X-Workbench-Request": "work-browser" }, body: "{}" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || "打开失败，请检查后台服务。");
      setState(result);
    } catch (error) { setState({ status: "unknown", message: error instanceof Error ? error.message : "打开失败。" }); }
    finally { setPending(false); }
  };
  const labels: Record<string, string> = { idle: "空闲", opening: "正在打开", managing: "管理中", closing: "正在关闭", collecting: "采集中", unknown: "未知" };
  useEffect(() => { onStatus(labels[state.status] || "未知"); }, [state.status, onStatus]);
  const unavailable = pending || !["idle", "managing", "opening"].includes(state.status);
  return <section className="table-card settings-card"><div className="table-heading"><div><h2>工作浏览器</h2><span>管理 1688 采集使用的浏览器、账号和扩展。</span></div></div>
    <div className="work-browser-settings">
      <div className="work-browser-row"><div className="monitoring-setting-copy"><strong>浏览器状态</strong><small>管理期间暂停使用此浏览器进行采集。</small></div><span className="work-browser-value" role="status">{labels[state.status] || "未知"}</span></div>
      <div className="work-browser-row"><div className="monitoring-setting-copy"><strong>1688 官方采购助手</strong><small>在插件管理中检查扩展，然后在商品页确认助手区域。</small></div><span className="work-browser-value">未自动检测</span></div>
      <div className="work-browser-row"><div className="monitoring-setting-copy"><strong>工作浏览器配置目录</strong><small>沿用当前项目的采集配置，账号与扩展保存在本机。</small></div><span className="work-browser-value">项目根目录 / .browser-profile</span></div>
      {state.message && <div className="feedback feedback-server-error" role="alert">{state.message}</div>}
      <div className="settings-save-bar"><span className="settings-save-state">关闭整个浏览器后可继续采集。</span><button type="button" className="secondary-button" onClick={() => void open(true)} disabled={unavailable}>插件管理</button><button type="button" className="primary-button" onClick={() => void open()} disabled={unavailable}>{pending || state.status === "opening" ? "正在打开…" : "打开工作浏览器"}</button></div>
    </div></section>;
}

export function SettingsPage({ configured, value, status, error, saveError, submitting, onChange, onRetry, onReset, onSave, onNavigate, monitoring, monitoringStatus, monitoringError, monitoringSaveError, monitoringSubmitting, onMonitoringChange, onMonitoringOpen, onMonitoringRetry, onMonitoringReset, onMonitoringSave, basicDirty, monitoringDirty }: SettingsPageProps) {
  const [planned, setPlanned] = useState("产品库");
  const [browserStatus, setBrowserStatus] = useState("未知");
  const [activeSection, setActiveSection] = useState("settings-overview");
  useEffect(() => {
    const root = document.getElementById("workspace-main");
    const sections = ["settings-overview", "settings-basic", "settings-monitoring", "settings-browser", "settings-future"].map(id => document.getElementById(id)).filter((element): element is HTMLElement => element !== null);
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible.length) setActiveSection(visible[0].target.id);
    }, { root, rootMargin: "-10% 0px -65% 0px" });
    sections.forEach(section => observer.observe(section));
    return () => observer.disconnect();
  }, []);
  useEffect(() => { onMonitoringOpen(); }, []);
  const dirty = basicDirty || monitoringDirty;
  const [invalid, setInvalid] = useState(false);
  const [invalidMessage, setInvalidMessage] = useState("请检查输入：数值须在范围内，时间点不得重复，计划时间须在同一天内。");
  const navigate = (page: Page) => {
    if (page === "settings") return true;
    if (submitting || monitoringSubmitting) return false;
    if (dirty && !window.confirm("有尚未保存的设置。离开后草稿仍会保留在本次工作台会话中，刷新或关闭页面会丢失。仍要离开吗？")) return false;
    onNavigate(page); return true;
  };
  const setNumber = (key: keyof CompetitorMonitoringSettings, value: string) => { if (monitoring) onMonitoringChange({ ...monitoring, [key]: value === "" ? NaN : Number(value) }); };
  const saveState = (changed: boolean, busy: boolean, failed: string | null, unconfigured = false) => <span className="settings-save-state" role="status">{busy ? "正在保存，请稍候…" : failed ? "保存失败，修改已保留，请重试" : changed ? "有未保存的修改" : unconfigured ? "尚未配置" : "当前设置已保存"}</span>;
  const monitoringRows: { key: keyof CompetitorMonitoringSettings; title: string; description: string; unit: string; recommended: string; range: string; value: number }[] = monitoring ? [
    { key: "item_interval_seconds", title: "单商品采集间隔", description: "每采集完一个商品后的等待时间", unit: "秒", recommended: "推荐 5 秒", range: "1～60 秒", value: monitoring.item_interval_seconds },
    { key: "continuous_collection_count", title: "连续采集数量", description: "连续访问指定数量后进入主动休息", unit: "个", recommended: "推荐 10 个", range: "1～50 个", value: monitoring.continuous_collection_count },
    { key: "batch_rest_seconds", title: "批次休息时间", description: "完成一组连续采集后暂停一段时间", unit: "分钟", recommended: "推荐 2 分钟", range: "0～30 分钟，0 表示关闭主动休息", value: monitoring.batch_rest_seconds / 60 },
    { key: "verification_cooldown_seconds", title: "风控冷却时间", description: "触发 1688 验证后等待多久再自动恢复", unit: "分钟", recommended: "推荐 10 分钟", range: "1～60 分钟", value: monitoring.verification_cooldown_seconds / 60 },
    { key: "auto_resume_max", title: "自动恢复次数", description: "触发验证后最多自动恢复的次数", unit: "次", recommended: "推荐 2 次", range: "0～5 次，0 表示直接进入人工处理", value: monitoring.auto_resume_max },
    { key: "operating_metrics_retry_max", title: "经营指标补采次数", description: "首轮结束后，对符合条件的经营指标技术异常最多补采次数", unit: "次", recommended: "默认关闭", range: "0～2 次，页面占位不补采", value: monitoring.operating_metrics_retry_max },
  ] : [];
  const field = (row: typeof monitoringRows[number]) => <div className="monitoring-setting-row" key={row.key}><label className="monitoring-setting-copy" htmlFor={row.key}><strong>{row.title}</strong><small>{row.description}</small></label><div className="monitoring-setting-control"><span className="monitoring-setting-input"><input id={row.key} aria-describedby={`${row.key}-meta`} type="number" required min={row.key === "batch_rest_seconds" || row.key === "auto_resume_max" || row.key === "operating_metrics_retry_max" ? 0 : 1} max={row.key === "item_interval_seconds" ? 60 : row.key === "continuous_collection_count" ? 50 : row.key === "batch_rest_seconds" ? 30 : row.key === "verification_cooldown_seconds" ? 60 : row.key === "operating_metrics_retry_max" ? 2 : 5} step={1} value={Number.isNaN(row.value) ? "" : row.value} disabled={monitoringSubmitting} onChange={(event) => setNumber(row.key, row.key === "batch_rest_seconds" || row.key === "verification_cooldown_seconds" ? (event.target.value === "" ? "" : String(Number(event.target.value) * 60)) : event.target.value)} /><b>{row.unit}</b></span><span id={`${row.key}-meta`} className="monitoring-setting-meta"><small>{row.range}；{row.recommended}</small></span></div></div>;
  const autoRow = (title: string, description: string, control: ReactNode) => <div className="monitoring-setting-row monitoring-auto-row"><span className="monitoring-setting-copy" id={`${title}-description`}><strong>{title}</strong><small>{description}</small></span><div className="monitoring-auto-control">{control}</div></div>;
  const radios = (key: "auto_collection_strategy" | "auto_collection_missed_policy", title: string, options: { value: string; label: string; description: string }[]) => <fieldset className="settings-radio-group" aria-describedby={`${title}-description`}><legend>{title}</legend>{options.map(option => <label className="settings-radio-option" key={option.value}><input type="radio" name={key} aria-label={option.label} value={option.value} checked={monitoring?.[key] === option.value} disabled={monitoringSubmitting} aria-describedby={`${option.value}-description`} onChange={() => { if (monitoring) onMonitoringChange({ ...monitoring, [key]: option.value }); }} /><span><strong>{option.label}</strong><small id={`${option.value}-description`}>{option.description}</small></span></label>)}</fieldset>;
  const changeTimes = (times: string[]) => {
    if (!monitoring) return;
    onMonitoringChange({ ...monitoring, auto_collection_times: times, auto_collection_time: [...times].sort()[0] });
  };
  const addTime = () => {
    if (!monitoring || monitoring.auto_collection_times.length >= 8) return;
    const latest = Math.max(...monitoring.auto_collection_times.map(value => Number(value.slice(0, 2)) * 60 + Number(value.slice(3))));
    const next = Array.from({ length: 24 }, (_, index) => {
      const minutes = (latest + (index + 1) * 60) % 1440;
      return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    }).find(value => !monitoring.auto_collection_times.includes(value)) ?? "00:00";
    changeTimes([...monitoring.auto_collection_times, next]);
  };
  const submitMonitoring = (event: FormEvent<HTMLFormElement>) => {
    if (!monitoring) return;
    const times = monitoring.auto_collection_times;
    const timeValid = times.length >= 1 && times.length <= 8 && times.every(value => /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)) && new Set(times).size === times.length;
    const [hour, minute] = monitoring.auto_collection_time.split(":").map(Number);
    const intervalValid = Number.isInteger(monitoring.auto_collection_interval_hours) && monitoring.auto_collection_interval_hours >= 1 && monitoring.auto_collection_interval_hours <= 24 && Number.isInteger(monitoring.auto_collection_daily_limit) && monitoring.auto_collection_daily_limit >= 1 && monitoring.auto_collection_daily_limit <= 12 && hour * 60 + minute + (monitoring.auto_collection_daily_limit - 1) * monitoring.auto_collection_interval_hours * 60 < 1440;
    if (!timeValid || monitoring.auto_collection_strategy === "fixed_interval" && !intervalValid || monitoring.auto_collection_strategy === "fixed_daily" && monitoring.auto_collection_time !== [...times].sort()[0]) {
      event.preventDefault(); setInvalid(true); setInvalidMessage("固定时间须为 1–8 个不重复的有效时间点；固定间隔的全部计划须落在同一天内。"); return;
    }
    setInvalid(false);
    onMonitoringSave(event);
  };
  return <AppShell page="settings" onNavigate={navigate} breadcrumb="系统设置">
    <header className="page-header"><div><h1>系统设置</h1><p className="page-description">统一管理工作台的业务设置与使用偏好。</p></div></header>
    <div className="settings-layout"><nav aria-label="设置模块" className="settings-side-nav"><strong>设置中心</strong><a href="#settings-overview" aria-current={activeSection === "settings-overview" ? "location" : undefined}>设置概览</a><span>竞品监控分析</span><a href="#settings-basic" aria-current={activeSection === "settings-basic" ? "location" : undefined}>店铺识别{basicDirty && " · 未保存"}</a><a href="#settings-monitoring" aria-current={activeSection === "settings-monitoring" ? "location" : undefined}>采集策略{monitoringDirty && " · 未保存"}</a><a href="#settings-browser" aria-current={activeSection === "settings-browser" ? "location" : undefined}>工作浏览器</a><span>其他模块 · 规划中</span>{["产品库", "客户触达", "AI 工具", "通用偏好"].map(name => <a href="#settings-future" key={name} onClick={() => setPlanned(name)}>{name}</a>)}</nav>
    <div className="settings-content"><section id="settings-overview" className="settings-overview"><div><h2>设置概览</h2><p>在这里管理工作台各模块的设置。已接入功能可独立保存，其他模块持续规划中。</p></div><div className="settings-overview-grid"><div><span>店铺识别</span><strong>{status === "ready" ? basicDirty ? "有未保存修改" : configured ? "已配置" : "尚未配置" : "状态未知"}</strong></div><div><span>自动采集</span><strong>{monitoringStatus === "ready" && monitoring ? monitoringDirty ? "有未保存修改" : monitoring.auto_collection_enabled ? "已开启" : "已关闭" : "状态未知"}</strong></div><div><span>工作浏览器</span><strong>{browserStatus}</strong></div></div></section>
    <div className="settings-group-heading"><h2>竞品监控分析</h2><p>管理店铺身份、采集策略与工作浏览器。</p></div>
    <section id="settings-basic" className="table-card settings-card"><div className="table-heading"><div><h2>店铺识别</h2><span>配置店铺身份，让监控中的我方商品与竞品准确归属。</span></div></div>
      {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载系统设置…</strong></div>}
      {status === "error" && <div className="state-panel state-error"><strong>设置加载失败</strong><span>{error || "暂时无法读取系统设置。"}</span><button type="button" className="secondary-button" onClick={onRetry}>重试</button></div>}
      {status === "ready" && <form className="settings-form" onSubmit={onSave}>
        <div className="settings-basic-content"><div className="settings-identity-editor">
          <label className="monitoring-setting-copy" htmlFor="own-shop-name"><strong>我方店铺名称</strong><small>填写用于识别我方商品的 1688 店铺名称。</small></label>
          <input id="own-shop-name" aria-describedby="shop-name-help" value={value} onChange={(event) => onChange(event.target.value)} maxLength={255} disabled={submitting} placeholder="请输入 1688 店铺名称" required />
          <p id="shop-name-help" className="settings-help">使用完整店铺名称，最多 255 个字符。</p>
          {!configured && <p className="hint">尚未配置。配置后才能从大屏添加监控商品。</p>}
        </div><aside className="settings-explanation"><h3>修改后会发生什么</h3><p>保存后会重新识别我方商品与竞品，并可能调整竞品组中的我方基准商品。</p><p>只按店铺名称精确匹配，不支持简称或关键词。首尾空白和连续空白会自动标准化。</p></aside></div>
        {saveError && <div className="feedback feedback-server-error" role="alert">{saveError}</div>}
        <div className="settings-save-bar">{saveState(basicDirty, submitting, saveError, !configured)}{basicDirty && <button type="button" className="secondary-button" onClick={onReset} disabled={submitting}>撤销店铺修改</button>}<button type="button" className="secondary-button" onClick={() => navigate("dashboard")} disabled={submitting}>返回大屏</button><button type="submit" className="primary-button" disabled={submitting || !value.trim()}>{submitting ? "保存中…" : "保存设置"}</button></div>
      </form>}

    </section>
    <section id="settings-monitoring" className="table-card settings-card settings-monitoring-card"><div className="settings-monitoring-heading"><h2>采集策略</h2><p>管理访问节奏与自动计划。推荐值供参考，按实际需要调整。</p></div>{monitoringStatus === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载竞品监控设置…</strong></div>}{monitoringStatus === "error" && <div className="state-panel state-error"><strong>竞品监控设置加载失败</strong><span>{monitoringError || "暂时无法读取竞品监控设置。"}</span><button type="button" className="secondary-button" onClick={onMonitoringRetry}>重试</button></div>}{monitoringStatus === "ready" && monitoring && <form className="monitoring-settings-form" onSubmit={submitMonitoring} onInvalid={() => { setInvalid(true); setInvalidMessage("请检查输入：数值须在范围内，时间点不得重复，计划时间须在同一天内。"); }} onInput={() => setInvalid(false)}>
        <div className="settings-effect-note"><strong>生效范围</strong><span>采集节奏、风控与补采设置用于下一次新启动的批量采集，当前运行任务不变；自动调度设置对后续检查生效。</span></div>
        <div className="settings-monitoring-columns"><section className="monitoring-setting-group settings-automation"><header><h3>自动采集</h3><span>使用后端电脑本地时间，沿用上方采集节奏与风控设置。</span></header>{autoRow("每日自动采集", "开启后按所选策略自动发起批量采集", <><span className="settings-switch-state">{monitoring.auto_collection_enabled ? "已开启" : "已关闭"}</span><input className="monitoring-switch" aria-label="每日自动采集" type="checkbox" role="switch" aria-describedby="每日自动采集-description" checked={monitoring.auto_collection_enabled} disabled={monitoringSubmitting} onChange={(event) => onMonitoringChange({ ...monitoring, auto_collection_enabled: event.target.checked })} /></>)}{autoRow("自动采集策略", "所有计划均使用后端电脑本地时间", radios("auto_collection_strategy", "自动采集策略", [{ value: "rolling_24h", label: "滚动 24 小时", description: "距商品最近一次正式尝试满 24 小时后进入自动采集范围；失败也算尝试。" }, { value: "fixed_daily", label: "每日固定时间", description: "每天在 1–8 个时间点各检查一次；每个商品每个时间点最多尝试一次。" }, { value: "fixed_interval", label: "每日固定间隔", description: "从开始时间按固定小时数采集，次数受每日上限约束，计划不会跨到次日。" }]))}{monitoring.auto_collection_strategy === "fixed_daily" && <>{monitoring.auto_collection_times.map((value, index) => autoRow(`时间点 ${index + 1}`, "后端电脑本地时间；每个时间点分别判断商品资格", <div className="settings-time-list-item"><input aria-label={`自动采集时间点 ${index + 1}`} type="time" required value={value} disabled={monitoringSubmitting} onChange={(event) => { if (event.target.value) changeTimes(monitoring.auto_collection_times.map((item, itemIndex) => itemIndex === index ? event.target.value : item)); }} /><button type="button" className="secondary-button" aria-label={`删除时间点 ${index + 1}`} disabled={monitoringSubmitting || monitoring.auto_collection_times.length <= 1} onClick={() => changeTimes(monitoring.auto_collection_times.filter((_, itemIndex) => itemIndex !== index))}>删除</button></div>))}{autoRow("新增时间点", "可设置 1–8 个不重复时间", <button type="button" className="secondary-button" disabled={monitoringSubmitting || monitoring.auto_collection_times.length >= 8} onClick={addTime}>新增时间点</button>)}</>}{monitoring.auto_collection_strategy === "fixed_interval" && <>{autoRow("每日开始时间", "后端电脑本地时间；作为当天第一个计划点", <input aria-label="每日开始时间" type="time" required value={monitoring.auto_collection_time} disabled={monitoringSubmitting} onChange={(event) => onMonitoringChange({ ...monitoring, auto_collection_time: event.target.value })} />)}{autoRow("固定间隔小时数", "每次计划间隔 1–24 小时", <input aria-label="固定间隔小时数" type="number" min={1} max={24} step={1} required value={Number.isNaN(monitoring.auto_collection_interval_hours) ? "" : monitoring.auto_collection_interval_hours} disabled={monitoringSubmitting} onChange={(event) => onMonitoringChange({ ...monitoring, auto_collection_interval_hours: event.target.value === "" ? NaN : Number(event.target.value) })} />)}{autoRow("每日最多采集次数", "最多 12 次；全部计划须落在当天", <input aria-label="每日最多采集次数" type="number" min={1} max={12} step={1} required value={Number.isNaN(monitoring.auto_collection_daily_limit) ? "" : monitoring.auto_collection_daily_limit} disabled={monitoringSubmitting} onChange={(event) => onMonitoringChange({ ...monitoring, auto_collection_daily_limit: event.target.value === "" ? NaN : Number(event.target.value) })} />)}</>}{monitoring.auto_collection_strategy !== "rolling_24h" && autoRow("错过计划", "决定进程启动或策略变更时如何处理已到期计划", radios("auto_collection_missed_policy", "错过计划", [{ value: "catch_up", label: "补采最新到期计划", description: "计划已错过时只补最新到期点；忙碌期间不排队，稍后重算未尝试商品。" }, { value: "skip", label: "跳过已错过计划", description: "进程或策略在计划后启用时跳过当天；已运行进程遇忙时保留最新计划等待重试。" }]))}</section><div className="settings-runtime"><section className="monitoring-setting-group"><header><h3>采集节奏</h3><span>控制每次访问之间的节奏与计划内休息。</span></header>{monitoringRows.slice(0, 3).map(field)}</section><section className="monitoring-setting-group"><header><h3>风控处理</h3><span>触发验证后，按当前设置等待并尝试恢复。</span></header>{monitoringRows.slice(3, 5).map(field)}</section><section className="monitoring-setting-group"><header><h3>经营指标补采</h3><span>默认关闭；只补采符合条件的技术异常，真实页面占位不会重试。</span></header>{monitoringRows.slice(5).map(field)}</section></div></div>{monitoringSaveError && <div className="feedback feedback-server-error" role="alert">{monitoringSaveError}</div>}{invalid && <p className="settings-validation" role="alert">{invalidMessage}</p>}<div className="settings-save-bar">{saveState(monitoringDirty, monitoringSubmitting, monitoringSaveError)}{monitoringDirty && <button type="button" className="secondary-button" onClick={() => { onMonitoringReset(); setInvalid(false); }} disabled={monitoringSubmitting}>撤销采集策略修改</button>}<button type="submit" className="primary-button" disabled={monitoringSubmitting}>{monitoringSubmitting ? "保存中…" : "保存设置"}</button></div></form>}</section>
    <div id="settings-browser"><WorkBrowserSettings onStatus={setBrowserStatus} /></div>
    <section id="settings-future" className="settings-future"><h2>其他模块设置</h2><p>工作台后续业务设置在此统一接入。</p><div className="settings-future-grid">{["产品库", "客户触达", "AI 工具", "通用偏好"].map(name => <button type="button" key={name} aria-pressed={planned === name} onClick={() => setPlanned(name)}><strong>{name}</strong><small>{({ "产品库": "产品资料与导入相关设置", "客户触达": "客户运营相关设置", "AI 工具": "模型和工具使用偏好", "通用偏好": "界面与工作台通用设置" } as Record<string, string>)[name]}</small><span>规划中</span></button>)}</div><p role="status"><strong>{planned}设置 · 尚未开放</strong><br />具体设置将在需求确认后接入。</p></section></div></div>
  </AppShell>;
}

function App() {
  const [page, setPage] = useState<Page>("home");
  const [monitoringExpanded, setMonitoringExpanded] = useState(() => monitoringPages.has("dashboard"));
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [ownProducts, setOwnProducts] = useState<Competitor[]>([]);
  const [groups, setGroups] = useState<CompetitorGroup[]>([]);
  const [addDialogGroups, setAddDialogGroups] = useState<CompetitorGroup[]>([]);
  const [addDialogGroupsStatus, setAddDialogGroupsStatus] = useState<GroupStatus>("loading");
  const [addDialogGroupsError, setAddDialogGroupsError] = useState<string | null>(null);
  const addDialogGroupsRequestId = useRef(0);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashboardStatus, setDashboardStatus] = useState<DashboardStatus>("loading");
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [dashboardAttention, setDashboardAttention] = useState<GroupAttentionData | null>(null);
  const [dashboardAttentionStatus, setDashboardAttentionStatus] = useState<DashboardStatus>("loading");
  const [dashboardAttentionError, setDashboardAttentionError] = useState<string | null>(null);
  const dashboardRequestId = useRef(0);
  const dashboardAttentionRequestId = useRef(0);
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
  const settingsLoadInFlight = useRef(false);
  const monitoringLoadInFlight = useRef(false);
  const [savedMonitoringSettings, setSavedMonitoringSettings] = useState<CompetitorMonitoringSettings | null>(null);
  const [monitoringSettings, setMonitoringSettings] = useState<CompetitorMonitoringSettings | null>(null);
  const [monitoringStatus, setMonitoringStatus] = useState<ListStatus>("loading");
  const [monitoringError, setMonitoringError] = useState<string | null>(null);
  const [monitoringSaveError, setMonitoringSaveError] = useState<string | null>(null);
  const [monitoringSubmitting, setMonitoringSubmitting] = useState(false);
  const [groupSummary, setGroupSummary] = useState<CompetitorGroupsSummary | null>(null);
  const [groupStatus, setGroupStatus] = useState<GroupStatus>("loading");
  const [groupError, setGroupError] = useState<string | null>(null);
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
    if (settingsLoadInFlight.current) return false;
    settingsLoadInFlight.current = true;
    setSettingsStatus("loading"); setSettingsError(null);
    try {
      const response = await fetch("/api/settings/own-shop-name");
      if (!response.ok) throw new Error("request failed");
      const body = await response.json() as { configured: boolean; own_shop_name: string | null };
      setSettingsConfigured(body.configured); setOwnShopName(body.own_shop_name); setSettingsValue(body.own_shop_name || ""); setSettingsStatus("ready"); return true;
    } catch { setSettingsError("暂时无法获取系统设置，请检查服务是否正常运行。"); setSettingsStatus("error"); return false; }
    finally { settingsLoadInFlight.current = false; }
  }
  async function loadMonitoringSettings(): Promise<boolean> {
    if (monitoringLoadInFlight.current) return false;
    monitoringLoadInFlight.current = true;
    setMonitoringStatus("loading"); setMonitoringError(null);
    try {
      const response = await fetch("/api/settings/competitor-monitoring");
      if (!response.ok) throw new Error("request failed");
      const loaded = await response.json() as CompetitorMonitoringSettings; setMonitoringSettings(loaded); setSavedMonitoringSettings(loaded); setMonitoringStatus("ready"); return true;
    } catch { setMonitoringError("暂时无法获取竞品监控设置，请检查服务是否正常运行。"); setMonitoringStatus("error"); return false; }
    finally { monitoringLoadInFlight.current = false; }
  }
  async function loadDashboardAttention(): Promise<boolean> {
    const requestId = ++dashboardAttentionRequestId.current;
    setDashboardAttentionStatus("loading"); setDashboardAttentionError(null);
    try {
      const response = await fetch("/api/dashboard/group-attention");
      if (!response.ok) throw new Error("request failed");
      const attention = await response.json() as GroupAttentionData;
      if (requestId !== dashboardAttentionRequestId.current) return true;
      setDashboardAttention(attention);
      setDashboardAttentionStatus("ready");
      return true;
    } catch {
      if (requestId !== dashboardAttentionRequestId.current) return true;
      setDashboardAttentionError("暂时无法获取商品组关注信息。"); setDashboardAttentionStatus("error");
      return false;
    }
  }
  async function loadDashboard(): Promise<boolean> {
    const requestId = ++dashboardRequestId.current;
    setDashboardStatus("loading"); setDashboardError(null);
    const attentionRequest = loadDashboardAttention();
    let dashboardLoaded = false;
    try {
      const response = await fetch("/api/dashboard/today");
      if (!response.ok) throw new Error("request failed");
      const data = await response.json() as DashboardData;
      if (requestId !== dashboardRequestId.current) return true;
      setDashboard(data); setDashboardStatus("ready");
      dashboardLoaded = true;
    } catch {
      if (requestId !== dashboardRequestId.current) return true;
      setDashboardError("暂时无法获取今日变化，请检查服务是否正常运行。"); setDashboardStatus("error");
    }
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
      setGroupStatus("ready");
      return true;
    } catch {
      setGroupError("暂时无法获取竞品组，请检查服务是否正常运行。"); setGroupStatus("error");
      return false;
    }
  }
  async function loadAddDialogGroups(): Promise<boolean> {
    const requestId = ++addDialogGroupsRequestId.current;
    setAddDialogGroupsStatus("loading"); setAddDialogGroupsError(null);
    try {
      const response = await fetch("/api/competitor-groups");
      if (!response.ok) throw new Error("request failed");
      const groupData = await response.json() as CompetitorGroup[];
      if (requestId !== addDialogGroupsRequestId.current) return false;
      setAddDialogGroups(groupData); setAddDialogGroupsStatus("ready");
      return true;
    } catch {
      if (requestId !== addDialogGroupsRequestId.current) return false;
      setAddDialogGroupsError("暂时无法获取竞品组，请检查服务后重试。"); setAddDialogGroupsStatus("error");
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
      const wasActiveBatch = previous.status === "running" || previous.status === "pausing" || previous.status === "paused" || previous.status === "stopping" || previous.status === "resting" || previous.status === "cooling_down";
      const addFinished = next.work_kind === "add_links" && next.lifecycle_status === "terminal" && (wasActiveBatch || previous.task_id !== next.task_id);
      if (addFinished || (next.status === "completed" || next.status === "stopped") && wasActiveBatch) {
        const refreshSucceeded = (await Promise.all([loadCurrentProducts(), loadDashboard(), ...(page === "group-detail" && selectedGroupId !== null ? [loadGroupDetail(selectedGroupId, groupDetailDays, true)] : [])])).every(Boolean);
        setNotice(refreshSucceeded
          ? next.work_kind === "add_links" && next.input_progress
            ? { message: `添加任务：新增 ${next.input_progress.added}，业务拒绝 ${next.input_progress.business_rejected}，技术失败 ${next.input_progress.technical_failed}，未执行 ${next.input_progress.not_executed}`, type: next.input_progress.anomaly_inputs ? "error" : "success" }
            : next.status === "stopped"
            ? { message: `采集已结束：已完成 ${next.completed} 件，剩余 ${next.remaining} 件未采集`, type: "success" }
            : { message: `采集完成：成功 ${next.succeeded}，失败 ${next.failed}`, type: next.failed ? "error" : "success" }
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
  async function controlBatch(action: "pause" | "resume" | "end") {
    try {
      const response = await fetch(`/api/competitors/collect-batch/${action}`, { method: "POST" });
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        setNotice({ message: body.message || "采集任务状态已变化，请刷新后重试。", type: "error" });
        void loadBatchStatus();
        return;
      }
      const next = await response.json() as BatchState;
      batchStateRef.current = next;
      setBatchState(next);
    } catch {
      setNotice({ message: "采集任务操作失败，请检查服务后重试。", type: "error" });
    }
  }
  function toggleBatchPause() {
    void controlBatch(batchStateRef.current.status === "paused" ? "resume" : "pause");
  }
  const basicSettingsDirty = settingsStatus === "ready" && settingsValue !== (ownShopName || "");
  const monitoringSettingsDirty = monitoringStatus === "ready" && JSON.stringify(monitoringSettings) !== JSON.stringify(savedMonitoringSettings);
  const settingsDirty = basicSettingsDirty || monitoringSettingsDirty;
  useEffect(() => {
    if (!settingsDirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [settingsDirty]);
  useEffect(() => { void loadDashboard(); void loadOwnShopName(); }, []);
  useEffect(() => { void loadBatchStatus(); }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    const active = ["running", "pausing", "paused", "stopping", "resting", "cooling_down"].includes(batchState.status) || batchState.status === "verification_required" && batchState.browser_open || batchState.lifecycle_status === "terminal" && batchState.runner_active;
    if (page !== "dashboard" && !active) return;
    const timer = window.setInterval(() => { void loadBatchStatus(); }, active ? 1500 : 3000);
    return () => window.clearInterval(timer);
  }, [page, batchState.status, batchState.browser_open, batchState.lifecycle_status, batchState.runner_active]);
  function navigate(nextPage: Page, initialGroupFilter: InitialGroupFilter = null) {
    if (nextPage !== "detail") { latestDetailRequestId.current += 1; setDetailRangeLoading(false); }
    if (nextPage !== "group-detail") { latestGroupDetailRequestId.current += 1; setGroupDetailRangeLoading(false); }
    setListNavigationIntent((current) => ({ filter: nextPage === "competitors" ? initialGroupFilter : null, version: current.version + 1 }));
    setPage(nextPage);
    if (nextPage === "dashboard") { void loadDashboard(); void loadBatchStatus(); }
    if (nextPage === "competitors" && !listLoaded) void loadCompetitors();
    if (nextPage === "own-products" && !ownListLoaded) void loadOwnProducts();
    if (nextPage === "groups") void loadGroups();
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
  function openDialog(initialGroupId: number | null = null) { setNotice(null); setUrl(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupId(initialGroupId); setNewGroupName(""); setGroupCreateStatus("initial"); setDialogOpen(true); void loadAddDialogGroups();
    try { const stored = localStorage.getItem(pendingAddKey); if (stored) { const pending = JSON.parse(stored) as PendingAddEnvelope; if (initialGroupId !== null && pending.group_id !== initialGroupId) return; setUrl(pending.draft_text ?? Array.from({ length: Math.max(...pending.inputs.map(input => input.source_line)) }, (_, index) => pending.inputs.find(input => input.source_line === index + 1)?.text || "").join("\n")); setGroupId(pending.group_id); setNotice({ message: "有待确认的添加提交，点击添加将先查询原任务，不会重复采集。", type: "error" }); } } catch { setNotice({ message: "无法读取提交恢复信息，请检查浏览器存储。", type: "error" }); }
  }
  function openDashboardAddDialog() {
    if (!ownShopName) { navigate("settings"); return; }
    openDialog();
  }
  function closeDialog() { if (addStatus !== "submitting") { addDialogGroupsRequestId.current += 1; setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupCreateStatus("initial"); } }
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
      setMonitoringSettings(body); setSavedMonitoringSettings(body); setNotice({ message: "竞品监控设置已保存。", type: "success" });
    } catch (error) { setMonitoringSaveError(error instanceof Error ? error.message : "竞品监控设置保存失败，请稍后重试"); }
    finally { setMonitoringSubmitting(false); }
  }
  async function handleCreateGroup() {
    setGroupCreateStatus("submitting");
    try {
      const response = await fetch("/api/competitor-groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newGroupName }) });
      if (response.ok) { const group = await response.json() as CompetitorGroup; setGroups((current) => [...current, group]); setAddDialogGroups((current) => [...current, group]); setGroupId(group.id); setNewGroupName(""); setGroupCreateStatus("success"); return; }
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
    if (selectedGroupId === null || groupDetailRangeLoading) return;
    setGroupDetailRangeLoading(true); setGroupDetailRangeError(null);
    await loadGroupDetail(selectedGroupId, days, true);
  }
  async function loadGroupDetail(groupId: number, days: 7 | 30, preserveContent = false): Promise<boolean> {
    const requestId = ++latestGroupDetailRequestId.current;
    if (!preserveContent) { setGroupDetailStatus("loading"); setGroupDetailError(null); }
    else setGroupDetailRangeLoading(true);
    try {
      const response = await fetch(`/api/competitor-groups/${groupId}/detail?days=${days}`);
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use stable local message */ }
        throw new Error(body.code === "competitor_group_not_found" ? "竞品组不存在" : body.message || "暂时无法获取组分析。");
      }
      const data = await response.json() as GroupDetailData;
      if (requestId !== latestGroupDetailRequestId.current) return false;
      setGroupDetail(data); setGroupDetailDays(days); setGroupDetailRangeLoading(false); setGroupDetailError(null); setGroupDetailRangeError(null); setGroupDetailStatus("ready");
      return true;
    } catch (error) {
      if (requestId !== latestGroupDetailRequestId.current) return false;
      const message = error instanceof Error ? error.message : "暂时无法获取组分析。";
      setGroupDetailRangeLoading(false);
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
    if (addStatus === "submitting") return;
    setAddStatus("submitting"); setAddFailures([]); setAddSucceededCount(0);
    try {
      const stored = localStorage.getItem(pendingAddKey);
      let previous: PendingAddEnvelope | null = stored ? JSON.parse(stored) : null;
      const rawInputs = url.split(/\r?\n/).map((text, index) => ({ text: text.trim(), source_line: index + 1 })).filter(input => input.text);
      const draftUnchanged = !!previous && previous.group_id === groupId && (previous.draft_text !== undefined
        ? previous.draft_text === url
        : JSON.stringify(previous.inputs) === JSON.stringify(rawInputs));
      const inputs = draftUnchanged ? previous!.inputs : dedupeCompetitorInputs(url);
      if (!inputs.length) { setAddStatus("initial"); return; }
      if (inputs.length > 100 || inputs.some(input => input.text.length > 2048)) { setNotice({ message: "最多提交100条非空链接，每条最长2048字符。", type: "error" }); setAddStatus("initial"); return; }
      if (previous && !draftUnchanged) {
        const response = await fetch(`/api/competitors/add-batch/${previous.submission_id}`);
        if (response.status !== 404) {
          const body = await response.json();
          if (!response.ok || body.accepted !== true || body.task_id !== previous.submission_id) throw new Error("原提交受理结果未知，编辑内容尚未发送，请先查询原任务。");
          localStorage.setItem("workbench.add-task.v1", body.task_id);
        }
        previous = null;
      }
      const envelope: AddEnvelope = draftUnchanged && previous
        ? { submission_id: previous.submission_id, inputs: previous.inputs, group_id: previous.group_id }
        : { submission_id: crypto.randomUUID(), inputs, group_id: groupId };
      // Save before sending. Storage failures must not send an unresumable request.
      localStorage.setItem(pendingAddKey, JSON.stringify({ ...envelope, draft_text: url }));
      const result = await submitAddLinks(envelope, fetch, !!previous);
      localStorage.setItem("workbench.add-task.v1", result.task_id);
      localStorage.removeItem(pendingAddKey);
      const task = result.task;
      setAddProgress({ completed: task.input_summary?.processed || 0, total: envelope.inputs.length });
      if (task.lifecycle_status !== "terminal") {
        setDialogOpen(false); setUrl(""); setAddStatus("initial");
        setNotice({ message: "添加任务已受理，可在大屏查看进度，在采集记录查看所有输入结果。", type: "success" });
        await loadBatchStatus();
        return;
      }
      const failed = task.items.filter(input => input.result_code !== "added").map(input => ({ url: input.input_text || "身份已移除", code: (input.result_code === "already_exists" ? "competitor_already_exists" : input.result_code === "invalid_url" ? "invalid_competitor_url" : "server-error") as AddFailureCode, reason: input.sanitized_reason || inputResultLabels[input.result_code || ""] || "未处理" }));
      const succeeded = task.input_summary?.added || 0;
      setAddFailures(failed); setAddSucceededCount(succeeded);
      setUrl(failed.map(input => input.url).join("\n")); setAddStatus(failed.length ? succeeded ? "partial" : "failed" : "initial");
      if (!failed.length) setDialogOpen(false);
      await Promise.all([loadCompetitors(), loadOwnProducts(), loadDashboard(), loadBatchStatus(), ...(page === "group-detail" && selectedGroupId !== null ? [loadGroupDetail(selectedGroupId, groupDetailDays, true)] : [])]);
      setNotice({ message: `添加任务：新增 ${succeeded}，业务拒绝 ${task.input_summary?.business_rejected || 0}，技术失败 ${task.input_summary?.technical_failed || 0}；完整结果见采集记录。`, type: task.input_summary?.anomaly_inputs ? "error" : "success" });
    } catch (error) {
      setAddStatus("server-error");
      setNotice({ message: error instanceof Error ? error.message : "受理结果未知，请使用原提交重试查询。", type: "error" });
    }
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

    const isSelf = competitor.ownership === "self";
    if (page === "group-detail" && selectedGroupId !== null) {
      setGroupDetail(current => current ? updateGroupOfferAfterLifecycle(current, competitor.id, deleted) : current);
      return (await Promise.all([loadGroupDetail(selectedGroupId, groupDetailDays, true), isSelf ? loadOwnProducts() : loadCompetitors(), loadDashboard()])).every(Boolean);
    }
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
  return <WorkspaceToolsProvider batch={batchState}><MonitoringNavigationContext.Provider value={{ expanded: monitoringExpanded, setExpanded: setMonitoringExpanded }}><>
    {page === "home" && <HomePage onNavigate={navigate} />}
    {page === "product-library" && <AppShell page="product-library" breadcrumb="产品库" onNavigate={navigate}><ProductLibrary /></AppShell>}
    {page === "customer-reach" && <AppShell page="customer-reach" breadcrumb="客户触达" onNavigate={navigate}><CustomerReachPage /></AppShell>}
    {page === "ai-assistant" && <WorkspacePlaceholderPage page="ai-assistant" title="AI智能助手" description="智能辅助工作入口。" note="AI智能助手模块已预留，具体能力待规划。" icon="assistant" onNavigate={navigate} />}
    {page === "price-compare" && <WorkspacePlaceholderPage page="price-compare" title="全网比价" description="统一检索并对比全网同款与相似商品价格。" note="后续将在这里承载商品检索、候选同款筛选、价格对比和结果沉淀。" icon="compare" onNavigate={navigate} />}
    {page === "auto-inquiry" && <WorkspacePlaceholderPage page="auto-inquiry" title="自动询价" description="统一管理供应商询价任务与报价结果。" note="后续将在这里承载询价对象、询价话术、回复状态和供应商报价记录。" icon="inquiry" onNavigate={navigate} />}
    {page === "auto-listing" && <WorkspacePlaceholderPage page="auto-listing" title="自动上架" description="统一管理商品资料校验、上架任务与执行结果。" note="后续将在这里承载商品资料准备、渠道映射、批量上架和失败结果处理。" icon="listing" onNavigate={navigate} />}
    {page === "dashboard" && <DashboardPage data={dashboard} attention={dashboardAttention} attentionStatus={dashboardAttentionStatus} attentionError={dashboardAttentionError} status={dashboardStatus} error={dashboardError} batchState={batchState} ownShopName={ownShopName} onAdd={openDashboardAddDialog} onCollect={() => void handleBatchAction("all_active")} onToggleBatchPause={toggleBatchPause} onEndBatch={() => void controlBatch("end")} onRetry={() => void loadDashboard()} onRetryAttention={() => void loadDashboardAttention()} onNavigate={navigate} onOpenGroupDetail={openGroupDetail} />}
    {page === "own-products" && <ListPage competitors={ownProducts} ownership="self" groups={groups} status={ownListStatus} error={ownListError} onRetry={() => void loadOwnProducts()} batchState={batchState} selectedIds={selectedIds} onToggleSelected={(competitorId) => setSelectedIds((current) => { const next = new Set(current); if (next.has(competitorId)) next.delete(competitorId); else next.add(competitorId); return next; })} onToggleAll={(checked, competitorIds) => setSelectedIds((current) => updatePageSelection(current, competitorIds, checked))} onReconcileSelection={reconcileSelection} onBatchAction={(mode, competitorIds) => void handleBatchAction(mode, competitorIds)} onOpenDetail={openDetail} onOpenGroupAssignment={openGroupAssignmentDialog} onNavigate={navigate} paginationResetVersion={paginationResetVersion} />}
    {page === "competitors" && <ListPage competitors={competitors} ownership="competitor" groups={groups} status={listStatus} error={listError} onRetry={() => void loadCompetitors()} batchState={batchState} selectedIds={selectedIds} onToggleSelected={(competitorId) => setSelectedIds((current) => { const next = new Set(current); if (next.has(competitorId)) next.delete(competitorId); else next.add(competitorId); return next; })} onToggleAll={(checked, competitorIds) => setSelectedIds((current) => updatePageSelection(current, competitorIds, checked))} onReconcileSelection={reconcileSelection} onBatchAction={(mode, competitorIds) => void handleBatchAction(mode, competitorIds)} onOpenDetail={openDetail} onOpenGroupAssignment={openGroupAssignmentDialog} onNavigate={navigate} initialGroupFilter={listNavigationIntent.filter} navigationVersion={listNavigationIntent.version} paginationResetVersion={paginationResetVersion} />}
    {page === "collection-tasks" && <CollectionTasksPage onNavigate={navigate} batchState={batchState} batchStatus={batchStatus} batchError={batchError} onRefreshBatch={loadBatchStatus} />}
    {page === "settings" && <SettingsPage basicDirty={basicSettingsDirty} monitoringDirty={monitoringSettingsDirty} configured={settingsConfigured} value={settingsValue} status={settingsStatus} error={settingsError} saveError={settingsSaveError} submitting={settingsSubmitting} onChange={setSettingsValue} onRetry={() => void loadOwnShopName()} onReset={() => { setSettingsValue(ownShopName || ""); setSettingsSaveError(null); }} onSave={submitOwnShopName} onNavigate={navigate} monitoring={monitoringSettings} monitoringStatus={monitoringStatus} monitoringError={monitoringError} monitoringSaveError={monitoringSaveError} monitoringSubmitting={monitoringSubmitting} onMonitoringChange={setMonitoringSettings} onMonitoringOpen={() => { if (monitoringStatus !== "ready") void loadMonitoringSettings(); }} onMonitoringRetry={() => void loadMonitoringSettings()} onMonitoringReset={() => { setMonitoringSettings(savedMonitoringSettings); setMonitoringSaveError(null); }} onMonitoringSave={submitMonitoringSettings} />}
    {page === "groups" && <GroupPage summary={groupSummary} status={groupStatus} error={groupError} onRetry={() => void loadGroups()} onCreate={openGroupCreateDialog} onViewCompetitors={(filter) => navigate("competitors", filter)} onViewAnalysis={openGroupDetail} onRename={openGroupRenameDialog} onDelete={openGroupDeleteDialog} onOwnProduct={(group, mode) => void openOwnProductDialog(group, mode)} onNavigate={navigate} />}
    {page === "group-detail" && <GroupDetailPage data={groupDetail} status={groupDetailStatus} error={groupDetailError} days={groupDetailDays} rangeLoading={groupDetailRangeLoading} rangeError={groupDetailRangeError} onRetry={() => selectedGroupId !== null && void loadGroupDetail(selectedGroupId, groupDetailDays, groupDetail !== null)} onRangeChange={changeGroupDetailRange} onBack={() => navigate("groups")} onViewCompetitors={(id) => navigate("competitors", id)} onAdd={(id) => { if (!ownShopName) { navigate("settings"); return; } openDialog(id); }} onOpenDetail={openDetail} onNavigate={navigate} offerActionBusy={lifecycleSubmitting} onOfferAction={(action, competitor) => { if (action === "stop") void updateMonitoring(competitor, false, null); else openLifecycleDialog("delete", competitor); }} />}
    {page === "detail" && <DetailPage data={detail} groups={groups} status={detailStatus} error={detailError} days={detailDays} rangeLoading={detailRangeLoading} onRetry={() => selectedCompetitorId !== null && void loadDetail(selectedCompetitorId, detailDays)} onRangeChange={changeDetailRange} onBack={() => navigate(detail?.competitor.ownership === "self" ? "own-products" : "competitors")} onChangeGroup={openGroupAssignmentDialog} onLifecycleAction={handleLifecycleAction} lifecycleSubmitting={lifecycleSubmitting} onNavigate={navigate} />}
    {notice && <div className={"toast toast-" + notice.type} role="status">{notice.message}</div>}
    {dialogOpen && <AddDialog url={url} status={addStatus} onUrlChange={setUrl} onSubmit={handleSubmit} onClose={closeDialog} groups={addDialogGroups} groupsStatus={addDialogGroupsStatus} groupsError={addDialogGroupsError} onRetryGroups={() => void loadAddDialogGroups()} groupId={groupId} onGroupChange={setGroupId} newGroupName={newGroupName} onNewGroupNameChange={setNewGroupName} onCreateGroup={() => void handleCreateGroup()} groupCreateStatus={groupCreateStatus} failures={addFailures} succeededCount={addSucceededCount} progress={addProgress} />}
    {groupNameDialog && <GroupNameDialog mode={groupNameDialog.mode} name={groupName} submitting={groupNameSubmitting} error={groupNameError} onChange={setGroupName} onClose={closeGroupNameDialog} onSubmit={submitGroupName} />}
    {groupDeleteDialog && <GroupDeleteDialog group={groupDeleteDialog} submitting={groupDeleteSubmitting} error={groupDeleteError} onClose={closeGroupDeleteDialog} onConfirm={() => void confirmGroupDelete()} />}
    {ownProductDialog && <OwnProductDialog group={ownProductDialog.group} mode={ownProductDialog.mode} competitors={competitors} loading={ownProductLoading} selectedId={ownProductSelectedId} confirming={ownProductConfirming} submitting={ownProductSubmitting} error={ownProductError} onSelect={(id) => { setOwnProductSelectedId(id); setOwnProductConfirming(false); }} onConfirmStep={() => { setOwnProductConfirming(true); setOwnProductError(null); }} onClose={closeOwnProductDialog} onSubmit={() => void submitOwnProduct()} />}
    {batchGroupDialog && <BatchGroupAssignmentDialog targetGroupId={batchGroupTarget} groups={groups} selectedCount={batchGroupDialog.selectedCount} eligibleCount={batchGroupDialog.competitorIds.length} ownCount={batchGroupDialog.ownCount} submitting={batchGroupSubmitting} error={batchGroupError} onChange={setBatchGroupTarget} onClose={closeBatchGroupDialog} onSubmit={submitBatchGroup} />}
    {batchLifecycleDialog && <BatchLifecycleDialog action={batchLifecycleDialog.action} selectedCount={batchLifecycleDialog.selectedCount} eligibleCount={batchLifecycleDialog.competitorIds.length} ownCount={batchLifecycleDialog.ownCount} submitting={batchLifecycleSubmitting} error={batchLifecycleError} onClose={closeBatchLifecycleDialog} onConfirm={() => void submitBatchLifecycle()} />}
    {groupAssignmentDialog && <GroupAssignmentDialog groupId={groupAssignmentDialog.groupId} groups={groups} submitting={groupAssignmentSubmitting} error={groupAssignmentError} onChange={(groupId) => setGroupAssignmentDialog((current) => current ? { ...current, groupId } : current)} onClose={closeGroupAssignmentDialog} onSubmit={submitGroupAssignment} />}
    {lifecycleDialog && <ConfirmDialog action={lifecycleDialog.action} competitor={lifecycleDialog.competitor} submitting={lifecycleSubmitting} error={lifecycleError} onClose={closeLifecycleDialog} onConfirm={confirmLifecycleAction} />}
  </></MonitoringNavigationContext.Provider></WorkspaceToolsProvider>;
}

export default App;
