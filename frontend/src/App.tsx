import { FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import "./App.css";

type AddStatus = "initial" | "submitting" | "success" | "partial" | "failed" | "invalid" | "duplicate" | "server-error";
type GroupCreateStatus = "initial" | "submitting" | "success" | "invalid" | "duplicate" | "server-error";
type ListStatus = "loading" | "error" | "ready";
type DashboardStatus = "loading" | "error" | "ready";
type GroupStatus = "loading" | "error" | "ready";
export type BatchStatus = "idle" | "running" | "completed" | "verification_required";
export type Page = "dashboard" | "competitors" | "detail" | "groups";
type Notice = { message: string; type: "success" | "error" };
export type LifecycleAction = "stop" | "resume" | "delete";

type CollectionErrorBody = { code?: string; message?: string };
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
};

const groupAssignmentErrorMessages: Record<string, string> = {
  competitor_not_found: "竞品不存在",
  competitor_group_not_found: "竞品组不存在",
};

export type Competitor = {
  id: number;
  platform: string;
  offer_id: string;
  url: string;
  group_id: number | null;
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
  latest_change: {
    id: number;
    snapshot_id: number;
    change_type: string;
    entity_key: string | null;
    old_value: string | null;
    new_value: string | null;
    detected_at: string;
  } | null;
};

type LifecycleCompetitor = Pick<Competitor, "id" | "title" | "offer_id" | "is_active">;

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

export function reconcileSelectedIds(selectedIds: ReadonlySet<number>, visibleActiveIds: readonly number[]): Set<number> {
  const visible = new Set(visibleActiveIds);
  return new Set([...selectedIds].filter((id) => visible.has(id)));
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
  items: { competitor_id: number; status: "success" | "failed" | "verification_required"; error_code: string | null; message: string | null }[];
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
  items: [],
};

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

export type CompetitorGroupSummary = CompetitorGroup & CompetitorGroupMetrics;

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
  snapshot_id?: number;
  change_type: string;
  entity_key: string | null;
  old_value: string | null;
  new_value: string | null;
  detected_at: string;
};

export type DashboardItem = {
  competitor_id: number;
  title: string | null;
  shop_name: string | null;
  main_image_url: string | null;
  group_id: number | null;
  last_collected_at: string | null;
  changes: Change[];
};

export type DashboardData = {
  date: string;
  stats: {
    monitored_competitors: number;
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
  competitor: Omit<Competitor, "latest_snapshot" | "latest_change">;
  latest_snapshot: {
    id: number;
    captured_at: string;
    price_min: string | null;
    price_max: string | null;
    product_status: "unknown" | "active" | "offline";
    sku_count: number;
    total_stock: number | null;
  } | null;
  latest_skus: { sku_id: string; sku_name: string; stock: number | null; price: string | null }[];
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

function chartY(value: number, minValue: number, maxValue: number, top: number, plotHeight: number): number {
  return maxValue === minValue ? top + plotHeight / 2 : top + ((maxValue - value) / (maxValue - minValue)) * plotHeight;
}

export function buildPriceChartPoints(trend: readonly DailyTrendPoint[], width = 640, height = 170): PriceChartPoint[] {
  const values = trend.flatMap((item) => [item.price_min, item.price_max]).flatMap((value) => {
    const number = value === null ? NaN : Number(value);
    return Number.isFinite(number) ? [number] : [];
  });
  if (trend.length === 0 || values.length === 0) return [];
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const left = 44;
  const right = 16;
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
  const values = trend.map((item) => item.total_stock).filter((value): value is number => value !== null && Number.isFinite(value));
  if (trend.length === 0 || values.length === 0) return [];
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const left = 44;
  const right = 16;
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

export type AddFailure = { url: string; code: "invalid_competitor_url" | "competitor_already_exists" | "competitor_group_not_found" | "server-error"; reason: string };
export type AddSubmissionResult = { succeeded: string[]; failures: AddFailure[] };

export function getAddFailureReason(code?: string): string {
  if (code === "invalid_competitor_url") return "链接格式无效";
  if (code === "competitor_already_exists") return "已存在";
  if (code === "competitor_group_not_found") return "竞品组不存在";
  return "服务暂时不可用，请稍后重试";
}

type CompetitorRequest = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export async function addCompetitorsSequentially(urls: readonly string[], groupId: number | null, request: CompetitorRequest = fetch, onProgress?: (completed: number, total: number) => void): Promise<AddSubmissionResult> {
  const succeeded: string[] = [];
  const failures: AddFailure[] = [];
  for (const url of urls) {
    try {
      const response = await request("/api/competitors", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, group_id: groupId }) });
      if (response.ok) succeeded.push(url);
      else {
        let code: string | undefined;
        try { code = (await response.json() as { code?: string }).code; } catch { /* use the stable fallback below */ }
        const failureCode = code === "invalid_competitor_url" || code === "competitor_already_exists" || code === "competitor_group_not_found" ? code : "server-error";
        failures.push({ url, code: failureCode, reason: getAddFailureReason(failureCode) });
      }
    } catch {
      failures.push({ url, code: "server-error", reason: getAddFailureReason() });
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
    case "price_increase": return `价格上涨 ${oldValue} → ${newValue}`;
    case "price_decrease": return `价格下降 ${oldValue} → ${newValue}`;
    case "sku_added": { const value = displayValue(change.new_value); return value ? `新增 SKU：${value}` : "新增 SKU"; }
    case "sku_removed": { const value = displayValue(change.old_value); return value ? `移除 SKU：${value}` : "移除 SKU"; }
    case "stock_changed": return `库存变化 ${oldValue} → ${newValue}`;
    case "title_changed": return "标题已变更";
    default: return "发生变化";
  }
}

export function getChangeTypeLabel(changeType: string): string {
  if (changeType === "price_increase" || changeType === "price_decrease") return "变价";
  if (changeType === "stock_changed") return "库存变化";
  if (changeType === "sku_added" || changeType === "sku_removed") return "SKU变化";
  if (changeType === "title_changed") return "标题变化";
  return "其他变化";
}

export function formatChangeValue(change: Change, side: "old" | "new"): string {
  const value = side === "old" ? change.old_value : change.new_value;
  const raw = value?.trim() || "";
  if (!raw) return "—";
  return change.change_type === "price_increase" || change.change_type === "price_decrease" ? `¥${raw}` : raw;
}

export function formatChangeMagnitude(change: Change): string {
  if (!["price_increase", "price_decrease", "stock_changed"].includes(change.change_type)) return "—";
  const oldValue = Number(change.old_value);
  const newValue = Number(change.new_value);
  if (!Number.isFinite(oldValue) || !Number.isFinite(newValue) || oldValue === 0) return "—";
  const percentage = ((newValue - oldValue) / oldValue) * 100;
  return `${percentage < 0 ? "↓" : "↑"} ${Math.abs(percentage).toFixed(1)}%`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const rounded = Math.round(seconds);
  if (rounded < 60) return `${rounded} 秒`;
  return `${Math.floor(rounded / 60)} 分 ${rounded % 60} 秒`;
}

export function buildDashboardChangeRows(data: DashboardData): { item: DashboardItem; change: Change }[] {
  return data.items.flatMap((item) => item.changes.map((change) => ({ item, change })))
    .sort((left, right) => new Date(right.change.detected_at).getTime() - new Date(left.change.detected_at).getTime() || right.change.id - left.change.id);
}

export type DashboardTrendChartPoint = DashboardTrendPoint & { x: number; y: Record<"price_changes" | "stock_changes" | "sku_changes" | "failed_collections", number> };

export function buildDashboardTrendChartPoints(trend: readonly DashboardTrendPoint[], width = 640, height = 180): DashboardTrendChartPoint[] {
  const points = trend.slice(-7);
  const maxValue = Math.max(1, ...points.flatMap((point) => [point.price_changes, point.stock_changes, point.sku_changes, point.failed_collections]));
  const left = 38;
  const right = 14;
  const top = 14;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const y = (value: number) => top + ((maxValue - value) / maxValue) * plotHeight;
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

function formatDate(value: string | null): string {
  if (!value) return "未采集";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function ProductImage({ competitor }: { competitor: Pick<Competitor, "main_image_url"> }) {
  const [failed, setFailed] = useState(false);
  if (!competitor.main_image_url || failed) return <span className="product-image product-image-placeholder">暂无主图</span>;
  return <img className="product-image" src={competitor.main_image_url} alt="" onError={() => setFailed(true)} />;
}

export function StatusBadge({ status }: { status: Competitor["status"] }) {
  const labels = { unknown: "状态未知", active: "在售", offline: "已下架" };
  return <span className={"status-badge status-" + status}>{labels[status]}</span>;
}

type ShellProps = { page: Page; onNavigate: (page: Page) => void; breadcrumb: string; children: ReactNode };

export function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  return <aside className="sidebar">
    <div className="brand"><span className="brand-mark">PW</span><div><strong>个人工作台</strong><span>工作提效工具集</span></div></div>
    <nav aria-label="主导航">
      <button className="nav-item nav-disabled" disabled><span className="nav-icon" aria-hidden="true">⌂</span>首页</button>
      <div className="nav-group"><div className="nav-group-title"><span className="nav-icon" aria-hidden="true">⌁</span>竞品监控<span className="nav-chevron" aria-hidden="true">⌃</span></div>
        <button className={"nav-item nav-child" + (page === "dashboard" ? " nav-active" : "")} onClick={() => onNavigate("dashboard")} aria-current={page === "dashboard" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品监控大屏</button>
        <button className={"nav-item nav-child" + (page === "competitors" || page === "detail" ? " nav-active" : "")} onClick={() => onNavigate("competitors")} aria-current={page === "competitors" || page === "detail" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品列表</button>
        <button className={"nav-item nav-child" + (page === "groups" ? " nav-active" : "")} onClick={() => onNavigate("groups")} aria-current={page === "groups" ? "page" : undefined}><span className="nav-dot" aria-hidden="true" />竞品分组</button>
        <button className="nav-item nav-child nav-disabled" disabled><span className="nav-dot" aria-hidden="true" />采集记录</button>
      </div>
      <button className="nav-item nav-disabled" disabled><span className="nav-icon" aria-hidden="true">▣</span>自动上架</button><button className="nav-item nav-disabled" disabled><span className="nav-icon" aria-hidden="true">⚙</span>系统设置</button>
    </nav>
    <div className="sidebar-note"><strong>让工作更高效</strong><span>v1.0.0</span></div>
  </aside>;
}

function AppShell({ page, onNavigate, breadcrumb, children }: ShellProps) {
  return <div className="app-shell"><Sidebar page={page} onNavigate={onNavigate} /><main className="main-content">
    <div className="workspace-header"><div className="breadcrumb">个人工作台 <span>/</span> 竞品监控 <span>/</span> <strong>{breadcrumb}</strong></div><div className="workspace-tools" aria-label="工作台工具区"><div className="workspace-search" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="5.5" /><path d="m16 16 4 4" /></svg><span>搜索商品名称、链接或关键词</span></div><span className="workspace-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></svg></span><span className="workspace-user" aria-hidden="true"><span className="workspace-avatar">W</span><span>工作台</span><svg viewBox="0 0 24 24"><path d="m8 10 4 4 4-4" /></svg></span></div></div>
    {children}
  </main></div>;
}

export function ConfirmDialog({ action, competitor, submitting, error, onClose, onConfirm }: { action: "stop" | "delete"; competitor: LifecycleCompetitor; submitting: boolean; error: string | null; onClose: () => void; onConfirm: () => void }) {
  const isDelete = action === "delete";
  const productLabel = competitor.title?.trim() || competitor.offer_id;
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="lifecycle-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="lifecycle-dialog-title">{isDelete ? "永久删除竞品" : "停止监控"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    {isDelete ? <p className="dialog-description">删除后，该竞品的历史快照、SKU、变化记录和采集记录都会永久删除，无法恢复。<br />当前商品：{productLabel}</p> : <p className="dialog-description">停止后将不再自动采集该竞品，但历史数据会保留，之后可以恢复监控。</p>}
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="button" className={isDelete ? "danger-button" : "primary-button"} onClick={onConfirm} disabled={submitting}>{isDelete ? "确认删除" : "停止监控"}</button></div>
  </section></div>;
}

function GroupMoreMenu({ onRename, onDelete }: { onRename: () => void; onDelete: () => void }) {
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

function CompetitorGroupCard({ group, onViewCompetitors, onRename, onDelete }: { group: CompetitorGroupSummary; onViewCompetitors: () => void; onRename: () => void; onDelete: () => void }) {
  return <article className="group-card">
    <div className="group-card-header"><div><h2>{group.name}</h2><span>{group.competitor_count} 个竞品</span></div><GroupMoreMenu onRename={onRename} onDelete={onDelete} /></div>
    <GroupMetrics metrics={group} />
    <div className="group-card-actions"><button type="button" className="primary-button" onClick={onViewCompetitors}>查看竞品</button></div>
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
  onRename: (group: CompetitorGroupSummary) => void;
  onDelete: (group: CompetitorGroupSummary) => void;
  onNavigate: (page: Page) => void;
};

export function GroupPage({ summary, status, error, onRetry, onCreate, onViewCompetitors, onRename, onDelete, onNavigate }: GroupPageProps) {
  const hasUnassigned = summary?.unassigned.competitor_count ? summary.unassigned.competitor_count > 0 : false;
  const isEmpty = status === "ready" && summary !== null && summary.groups.length === 0 && !hasUnassigned;
  return <AppShell page="groups" onNavigate={onNavigate} breadcrumb="竞品分组">
    <header className="page-header"><div><h1>竞品分组</h1><p className="page-description">以我方商品型号命名竞品组，管理对应竞品。</p></div><button type="button" className="primary-button" onClick={onCreate}>新增竞品组</button></header>
    {status === "loading" && <section className="table-card group-state-card state-panel"><div className="spinner" /><strong>正在加载竞品组…</strong></section>}
    {status === "error" && <section className="table-card group-state-card state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品组。"}</span><button type="button" className="secondary-button" onClick={onRetry}>重试</button></section>}
    {isEmpty && <section className="table-card group-state-card state-panel"><div className="empty-icon">＋</div><strong>还没有竞品组</strong><span>新增竞品组后，可按我方商品型号归集对应竞品进行对比监控。</span><button type="button" className="primary-button" onClick={onCreate}>新增竞品组</button></section>}
    {status === "ready" && summary && !isEmpty && <div className="group-card-grid">
      {summary.groups.map((group) => <CompetitorGroupCard key={group.id} group={group} onViewCompetitors={() => onViewCompetitors(group.id)} onRename={() => onRename(group)} onDelete={() => onDelete(group)} />)}
      {hasUnassigned && <UnassignedGroupCard metrics={summary.unassigned} onViewCompetitors={() => onViewCompetitors("unassigned")} />}
    </div>}
  </AppShell>;
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
  onAdd: () => void;
  batchState?: BatchState;
  selectedIds?: Set<number>;
  onToggleSelected?: (competitorId: number) => void;
  onToggleAll?: (checked: boolean, competitorIds: number[]) => void;
  onReconcileSelection?: (visibleActiveIds: number[]) => void;
  onBatchAction?: (mode: "selected" | "all_active") => void;
  onOpenDetail?: (competitorId: number) => void;
  onNavigate?: (page: Page) => void;
  initialGroupFilter?: InitialGroupFilter;
  navigationVersion?: number;
};

export function ListPage({ competitors, groups, status, error, onRetry, onAdd, batchState = idleBatchState, selectedIds = new Set<number>(), onToggleSelected = noop, onToggleAll = noop, onReconcileSelection = noop, onBatchAction = noop, onOpenDetail, onNavigate, initialGroupFilter = null, navigationVersion = 0 }: ListPageProps) {
  const [batchMenuOpen, setBatchMenuOpen] = useState(false);
  const [filters, setFilters] = useState<CompetitorFilters>(defaultCompetitorFilters);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const filteredCompetitors = useMemo(() => filterCompetitors(competitors, filters), [competitors, filters]);
  const collectedCount = filteredCompetitors.filter((item) => item.last_collected_at !== null).length;
  const activeCompetitorCount = countActiveCompetitors(competitors);
  const filteredActiveCompetitors = useMemo(() => filteredCompetitors.filter((item) => item.is_active), [filteredCompetitors]);
  const selectedActiveCount = filteredActiveCompetitors.filter((item) => selectedIds.has(item.id)).length;
  const batchBusy = batchState.runner_active || batchState.browser_open || batchState.status === "running";
  const allSelected = filteredActiveCompetitors.length > 0 && selectedActiveCount === filteredActiveCompetitors.length;
  const partiallySelected = selectedActiveCount > 0 && !allSelected;
  function resetFilters() {
    setFilters(defaultCompetitorFilters);
  }
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = partiallySelected;
  }, [partiallySelected]);
  useEffect(() => {
    onReconcileSelection(filteredActiveCompetitors.map((item) => item.id));
  }, [filteredActiveCompetitors, onReconcileSelection]);
  useEffect(() => {
    setFilters((current) => applyInitialGroupFilter(current, initialGroupFilter));
  }, [initialGroupFilter, navigationVersion]);
  return (
    <AppShell page="competitors" onNavigate={onNavigate || (() => undefined)} breadcrumb="竞品列表">
        <header className="page-header"><div><h1>竞品列表</h1><p className="page-description">查看当前已添加的 1688 竞品，并管理监控对象。</p></div><div className="page-actions"><div className="batch-menu"><button type="button" className="secondary-button batch-trigger" aria-haspopup="menu" aria-expanded={batchMenuOpen} onClick={() => setBatchMenuOpen((open) => !open)} disabled={batchBusy}>采集选中（{selectedActiveCount}） <span aria-hidden="true">▼</span></button>{batchMenuOpen && <div className="batch-menu-popover" role="menu"><button type="button" role="menuitem" disabled={selectedActiveCount === 0 || batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("selected"); }}>采集选中（{selectedActiveCount}）</button><button type="button" role="menuitem" disabled={batchBusy} onClick={() => { setBatchMenuOpen(false); onBatchAction("all_active"); }}>采集全部监控中（{activeCompetitorCount}）</button></div>}</div><button className="primary-button" onClick={onAdd} disabled={batchBusy}>添加竞品</button></div></header>
        {batchState.status === "running" && <div className="batch-status-panel batch-status-running" role="status">采集中 {batchState.completed} / {batchState.total} · 成功 {batchState.succeeded} · 失败 {batchState.failed}</div>}
        {batchState.status === "completed" && <div className="batch-status-panel" role="status">采集完成：成功 {batchState.succeeded}，失败 {batchState.failed}</div>}
        {batchState.status === "verification_required" && <div className="batch-status-panel batch-status-verification" role="alert">1688 需要人工验证，本次采集已停止。请在弹出的浏览器中完成处理，关闭浏览器后可重新发起采集。<span>已完成 {batchState.completed} / {batchState.total}，剩余 {batchState.remaining}</span></div>}
        <section className="filter-card" aria-label="搜索和筛选">
          <div className="filter-field filter-search"><input id="search" aria-label="搜索商品名称 / offerId / 店铺" value={filters.search} onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} placeholder="搜索商品名称 / offerId / 店铺" /></div>
          <div className="filter-field"><label htmlFor="product-status">商品状态</label><select id="product-status" value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as CompetitorFilters["status"] }))}><option value="all">全部状态</option><option value="active">在售</option><option value="offline">已下架</option><option value="unknown">状态未知</option></select></div>
          <div className="filter-field"><label htmlFor="collection-status">采集状态</label><select id="collection-status" value={filters.collectionStatus} onChange={(event) => setFilters((current) => ({ ...current, collectionStatus: event.target.value as CompetitorFilters["collectionStatus"] }))}><option value="all">全部状态</option><option value="collected">已采集</option><option value="not_collected">未采集</option></select></div>
          <div className="filter-field"><label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={filters.groupId === "all" ? "all" : String(filters.groupId)} onChange={(event) => setFilters((current) => ({ ...current, groupId: event.target.value === "all" || event.target.value === "unassigned" ? event.target.value : Number(event.target.value) }))}><option value="all">全部竞品组</option><option value="unassigned">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></div>
          <button type="button" className="text-button" onClick={resetFilters}>重置</button>
        </section>
        <section className="stats-strip" aria-label="列表统计">
          <div className="stat-total"><strong>共 {status === "ready" ? filteredCompetitors.length : "—"} 个竞品</strong></div>
          <div className="stat-item"><span>已采集数量</span><strong>{status === "ready" ? collectedCount : "—"}</strong></div>
          <div className="stat-item"><span>未采集数量</span><strong>{status === "ready" ? filteredCompetitors.length - collectedCount : "—"}</strong></div>
        </section>
        <section className="table-card">
          <div className="table-heading"><div><h2>全部竞品</h2><span>按添加时间倒序展示</span></div><span className="table-count">{status === "ready" ? filteredCompetitors.length + " 个商品" : status === "loading" ? "加载中" : "—"}</span></div>
          {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载竞品列表…</strong></div>}
          {status === "error" && <div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品列表。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div>}
          {status === "ready" && competitors.length === 0 && <div className="state-panel"><div className="empty-icon">+</div><strong>还没有添加竞品</strong><span>添加一个 1688 商品链接，开始建立你的监控列表。</span><button className="primary-button" onClick={onAdd}>添加竞品</button></div>}
          {status === "ready" && competitors.length > 0 && filteredCompetitors.length === 0 && <div className="state-panel"><strong>没有找到符合条件的竞品</strong><span>请调整搜索词或筛选条件</span><button type="button" className="secondary-button" onClick={resetFilters}>重置筛选</button></div>}
          {status === "ready" && filteredCompetitors.length > 0 && <div className="table-scroll"><table><thead><tr><th className="selection-column"><input ref={selectAllRef} type="checkbox" aria-label="全选当前页可采集竞品" checked={allSelected} disabled={filteredActiveCompetitors.length === 0 || batchBusy} onChange={(event) => onToggleAll(event.target.checked, filteredActiveCompetitors.map((item) => item.id))} /></th><th>商品信息</th><th>店铺名称</th><th>竞品组</th><th>当前价格</th><th>SKU 数量</th><th>最近变化</th><th>最近采集时间</th><th>商品状态</th><th>监控状态</th><th>操作</th></tr></thead><tbody>
            {filteredCompetitors.map((competitor) => <tr key={competitor.id}><td className="selection-column"><input type="checkbox" aria-label={`选择 ${competitor.title || competitor.offer_id}`} checked={competitor.is_active && selectedIds.has(competitor.id)} disabled={!competitor.is_active || batchBusy} onChange={() => onToggleSelected(competitor.id)} /></td><td><div className="product-cell"><ProductImage competitor={competitor} /><div><strong>{competitor.title || "未采集"}</strong><span>offerId：{competitor.offer_id}</span><a href={competitor.url} target="_blank" rel="noreferrer">查看 1688 商品 ↗</a></div></div></td><td>{competitor.shop_name || "未采集"}</td><td>{getCompetitorGroupLabel(competitor.group_id, groups)}</td><td className={competitor.latest_snapshot?.price_min || competitor.latest_snapshot?.price_max ? "price-cell" : "muted-cell"}>{formatPriceDisplay(competitor.latest_snapshot)}</td><td className={competitor.latest_snapshot === null ? "muted-cell" : "sku-cell"}>{competitor.latest_snapshot === null ? "未采集" : competitor.latest_snapshot.sku_count}</td><td className={competitor.latest_change === null ? "muted-cell" : "change-cell"}>{formatLatestChange(competitor.latest_change)}</td><td className="collection-date-cell">{formatDate(competitor.last_collected_at)}</td><td><StatusBadge status={competitor.status} /></td><td><span className={competitor.is_active ? "list-monitoring-badge" : "list-monitoring-badge list-monitoring-inactive"}>{competitor.is_active ? "监控中" : "已停止"}</span></td><td><button type="button" className="detail-button" onClick={() => onOpenDetail?.(competitor.id)}>详情</button></td></tr>) }
          </tbody></table></div>}
        </section>
        <div className="pagination-bar"><span>显示全部竞品</span><button disabled>上一页</button><span className="page-number">1</span><button disabled>下一页</button><span>分页暂未开放</span></div>
    </AppShell>
  );
}

type DashboardPageProps = {
  data: DashboardData | null;
  groups: CompetitorGroup[];
  status: DashboardStatus;
  error: string | null;
  batchState?: BatchState;
  onRetry: () => void;
  onNavigate: (page: Page) => void;
  onAdd?: () => void;
  onCollect?: () => void;
  onOpenDetail?: (competitorId: number) => void;
};

function DashboardIcon({ kind }: { kind: "price" | "stock" | "sku" | "error" }) {
  const paths = {
    price: <><path d="M5 17 10 12l3 3 6-7" /><path d="M15 8h4v4" /></>,
    stock: <><path d="m12 4 7 4v8l-7 4-7-4V8l7-4Z" /><path d="m5 8 7 4 7-4M12 12v8" /></>,
    sku: <><path d="m12 4 7 4-7 4-7-4 7-4Z" /><path d="m5 12 7 4 7-4M5 16l7 4 7-4" /></>,
    error: <><path d="M12 4 21 20H3L12 4Z" /><path d="M12 9v5M12 17h.01" /></>,
  };
  return <svg className="dashboard-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[kind]}</svg>;
}

function DashboardStatCard({ label, value, kind, tone }: { label: string; value: number | string; kind: "price" | "stock" | "sku" | "error"; tone: string }) {
  return <div className="dashboard-stat-card"><span className={`dashboard-stat-icon dashboard-stat-${tone}`}><DashboardIcon kind={kind} /></span><div><span>{label}</span><strong>{value}</strong></div></div>;
}

export function DashboardTrendChart({ trend }: { trend: DashboardTrendPoint[] }) {
  const width = 640;
  const height = 180;
  const points = buildDashboardTrendChartPoints(trend, width, height);
  const series = [
    ["price_changes", "变价", "dashboard-trend-price"],
    ["stock_changes", "库存变化", "dashboard-trend-stock"],
    ["sku_changes", "SKU变化", "dashboard-trend-sku"],
    ["failed_collections", "异常采集", "dashboard-trend-error"],
  ] as const;
  const line = (key: keyof DashboardTrendChartPoint["y"]) => points.map((point) => `${point.x},${point.y[key]}`).join(" ");
  return <div className="dashboard-trend-wrap"><svg className="dashboard-trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="近 7 天竞品变化趋势">
    {[0, 1, 2, 3].map((step) => <line key={step} className="chart-grid-line" x1="38" x2="626" y1={14 + step * 47.33} y2={14 + step * 47.33} />)}
    {points.length > 0 && <><text className="chart-label" x="7" y="18">{Math.max(1, ...points.flatMap((point) => [point.price_changes, point.stock_changes, point.sku_changes, point.failed_collections]))}</text><text className="chart-label" x="20" y="156">0</text></>}
    {series.map(([key, _label, className]) => <polyline key={key} className={`dashboard-trend-line ${className}`} points={line(key)} />)}
    {series.map(([key, _label, className]) => points.map((point) => <circle key={`${key}-${point.date}`} className={`dashboard-trend-point ${className}`} cx={point.x} cy={point.y[key]} r="3" />))}
    {points.map((point) => <text key={point.date} className="chart-label" x={point.x} y="170" textAnchor="middle">{point.date.slice(5).replace("-", "/")}</text>)}
  </svg><div className="chart-legend">{series.map(([key, label, className]) => <span key={key}><i className={`legend-dot ${className}`} />{label}</span>)}</div></div>;
}

function CollectionOverview({ data, batchState }: { data: DashboardData | null; batchState: BatchState }) {
  const summary = data?.collection_summary;
  const busy = batchState.status === "running" || batchState.runner_active || batchState.browser_open;
  const progress = batchState.total > 0 ? Math.min(100, (batchState.completed / batchState.total) * 100) : 0;
  return <section className="table-card collection-overview"><div className="table-heading"><div><h2>采集状态概览</h2><span>数据库记录与当前批次</span></div><span className={busy ? "overview-status overview-status-running" : batchState.status === "verification_required" ? "overview-status overview-status-warning" : "overview-status"}>{batchState.status === "running" ? "采集中" : batchState.status === "verification_required" ? "需要人工验证" : batchState.status === "completed" ? "最近批次完成" : "当前无采集任务"}</span></div>
    <div className="collection-summary-grid"><div><span>最近采集时间</span><strong>{summary?.last_collection_at ? formatDate(summary.last_collection_at) : "暂无采集记录"}</strong></div><div><span>今日成功</span><strong>{summary ? summary.success_runs : "—"}</strong></div><div><span>今日失败</span><strong className={summary?.failed_runs ? "collection-value-error" : ""}>{summary ? summary.failed_runs : "—"}</strong></div><div><span>平均耗时</span><strong>{formatDuration(summary?.average_duration_seconds ?? null)}</strong></div></div>
    <div className={`collection-batch collection-batch-${batchState.status}`}><div className="collection-batch-heading"><strong>{batchState.status === "running" ? `采集中 ${batchState.completed} / ${batchState.total}` : batchState.status === "verification_required" ? "需要人工验证" : batchState.status === "completed" ? "最近批次完成" : "当前无采集任务"}</strong><span>{batchState.status === "running" ? `成功 ${batchState.succeeded} · 失败 ${batchState.failed}` : batchState.status === "completed" ? `成功 ${batchState.succeeded} / 失败 ${batchState.failed}` : batchState.status === "verification_required" ? `已完成 ${batchState.completed} / ${batchState.total}` : "仍保留今日数据库统计"}</span></div>{batchState.status === "running" && <div className="collection-progress" role="progressbar" aria-label={`采集进度 ${batchState.completed} / ${batchState.total}`} aria-valuemin={0} aria-valuemax={batchState.total} aria-valuenow={batchState.completed}><span style={{ width: `${progress}%` }} /></div>}</div>
  </section>;
}

function QuickActions({ data, batchState, onAdd, onCollect, onNavigate }: { data: DashboardData | null; batchState: BatchState; onAdd?: () => void; onCollect?: () => void; onNavigate: (page: Page) => void }) {
  const busy = batchState.status === "running" || batchState.status === "verification_required" || batchState.runner_active || batchState.browser_open;
  const disabled = busy || !data || data.stats.monitored_competitors === 0;
  return <section className="table-card quick-actions"><div className="table-heading"><div><h2>快捷入口</h2><span>从这里继续今天的监控工作</span></div></div><div className="quick-action-list"><button type="button" className="quick-action" onClick={onAdd}><span className="quick-action-icon quick-action-blue">＋</span><span><strong>添加竞品</strong><small>录入新的监控商品</small></span></button><button type="button" className="quick-action" onClick={onCollect} disabled={disabled}><span className="quick-action-icon quick-action-purple">↗</span><span><strong>立即采集</strong><small>采集全部监控中竞品</small></span></button><button type="button" className="quick-action" onClick={() => onNavigate("competitors")}><span className="quick-action-icon quick-action-green">▤</span><span><strong>竞品列表</strong><small>查看和管理监控商品</small></span></button></div></section>;
}

export function DashboardPage({ data, groups, status, error, batchState = idleBatchState, onRetry, onNavigate, onAdd, onCollect, onOpenDetail }: DashboardPageProps) {
  const rows = status === "ready" && data ? buildDashboardChangeRows(data).slice(0, 5) : [];
  const value = (field: keyof DashboardData["stats"]) => status === "ready" && data ? data.stats[field] : "—";
  return <AppShell page="dashboard" onNavigate={onNavigate} breadcrumb="竞品监控大屏">
    <header className="page-header dashboard-page-header"><div><h1>竞品监控大屏</h1><p className="page-description">查看今日竞品变化、采集状态与近期趋势。</p></div><span className="dashboard-monitoring-count">监控中 {value("monitored_competitors")} 个竞品</span></header>
    <section className="dashboard-stats" aria-label="今日变化统计"><DashboardStatCard label="今日变价竞品" value={value("price_changed_competitors")} kind="price" tone="blue" /><DashboardStatCard label="今日库存变化竞品" value={value("stock_changed_competitors")} kind="stock" tone="green" /><DashboardStatCard label="今日 SKU 变化竞品" value={value("sku_changed_competitors")} kind="sku" tone="purple" /><DashboardStatCard label="异常采集" value={value("failed_collections")} kind="error" tone="orange" /></section>
    <div className="dashboard-main-grid"><section className="table-card dashboard-change-section"><div className="table-heading"><div><h2>今日发生变化的竞品</h2><span>{status === "ready" && data ? data.date : "本地业务日"}</span></div><span className="table-count">{status === "ready" && data ? `今日共 ${data.stats.change_events} 条变化` : "—"}</span></div>
      {status === "loading" && <div className="state-panel dashboard-inline-state"><div className="spinner" /><strong>正在加载今日变化…</strong></div>}
      {status === "error" && <div className="state-panel state-error dashboard-inline-state"><strong>加载失败</strong><span>{error || "暂时无法获取今日变化。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div>}
      {status === "ready" && data && rows.length === 0 && <div className="state-panel dashboard-empty"><div className="empty-icon">✓</div><strong>今日暂无竞品变化</strong><span>系统会继续按照每日采集规则监控竞品变化。</span></div>}
      {rows.length > 0 && <div className="table-scroll"><table className="dashboard-events-table"><thead><tr><th>商品信息</th><th>变化类型</th><th>旧值 → 新值</th><th>变化幅度</th><th>变化时间</th><th>竞品组</th><th>操作</th></tr></thead><tbody>{rows.map(({ item, change }) => <tr key={change.id}><td><div className="product-cell"><ProductImage competitor={item} /><div><strong>{item.title || "未采集"}</strong><span>{item.shop_name || "未采集"}</span></div></div></td><td><span className={`change-type-badge change-type-${change.change_type}`}>{getChangeTypeLabel(change.change_type)}</span></td><td className="change-transition">{formatChangeValue(change, "old")} <span>→</span> {formatChangeValue(change, "new")}</td><td className={`change-magnitude change-magnitude-${change.change_type}`}>{formatChangeMagnitude(change)}</td><td className="collection-date-cell">{formatDate(change.detected_at)}</td><td>{getCompetitorGroupLabel(item.group_id, groups)}</td><td><button type="button" className="detail-button" onClick={() => onOpenDetail?.(item.competitor_id)}>查看详情</button></td></tr>)}</tbody></table></div>}
    </section><CollectionOverview data={data} batchState={batchState} /></div>
    <div className="dashboard-lower-grid"><section className="table-card dashboard-trend-section"><div className="table-heading"><div><h2>近 7 天竞品变化趋势</h2><span>每天真实监控事件数量</span></div><span className="trend-period">连续 7 个业务日</span></div>{status === "ready" && data ? <DashboardTrendChart trend={data.trend_7d} /> : <div className="dashboard-trend-placeholder">—</div>}</section><QuickActions data={data} batchState={batchState} onAdd={onAdd} onCollect={onCollect} onNavigate={onNavigate} /></div>
  </AppShell>;
}

type DetailStatus = "loading" | "error" | "ready";
type DetailPageProps = {
  data: CompetitorDetail | null;
  groups: CompetitorGroup[];
  status: DetailStatus;
  error: string | null;
  days: 7 | 30;
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

export function formatTrendTooltip(point: DailyTrendPoint, kind: "price" | "stock"): string[] {
  const date = formatChartDate(point.date);
  if (kind === "stock") return point.total_stock === null ? [] : [date, `库存 ${formatStockDisplay(point.total_stock)}`];
  if (point.price_min === null && point.price_max === null) return [];
  if (point.price_min !== null && point.price_max !== null && point.price_min === point.price_max) return [date, `价格 ¥${point.price_min}`];
  return [date, ...(point.price_min === null ? [] : [`最低价 ¥${point.price_min}`]), ...(point.price_max === null ? [] : [`最高价 ¥${point.price_max}`])];
}

function DetailTrendChart({ kind, trend }: { kind: "price" | "stock"; trend: DailyTrendPoint[] }) {
  const width = 640;
  const height = 170;
  const top = 16;
  const bottom = 30;
  const plotHeight = height - top - bottom;
  const pricePoints = kind === "price" ? buildPriceChartPoints(trend, width, height) : [];
  const stockPoints = kind === "stock" ? buildStockChartPoints(trend, width, height) : [];
  const points = kind === "price" ? pricePoints : stockPoints;
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (points.length === 0) return <div className="detail-chart-empty">该时间范围暂无可用{kind === "price" ? "价格" : "库存"}数据</div>;
  const activePoint = activeIndex === null ? null : trend[activeIndex];
  const activeTooltip = activePoint ? formatTrendTooltip(activePoint, kind) : [];
  return <div className="detail-chart-shell" onMouseLeave={() => setActiveIndex(null)}>
    <svg className="detail-trend-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={kind === "price" ? "价格趋势" : "库存趋势"}>
      {[0, 1, 2, 3].map((step) => <line key={step} className="chart-grid-line" x1="44" x2="624" y1={top + step * (plotHeight / 3)} y2={top + step * (plotHeight / 3)} />)}
      {kind === "price" ? <>
        {lineSegments(pricePoints, "min_y").map((segment, index) => <polyline key={`min-${index}`} className="chart-line chart-line-min" points={segment.join(" ")} />)}
        {lineSegments(pricePoints, "max_y").map((segment, index) => <polyline key={`max-${index}`} className="chart-line chart-line-max" points={segment.join(" ")} />)}
        {pricePoints.map((point, index) => <g key={point.date} onMouseEnter={() => setActiveIndex(index)}>
          {point.min_y !== null && <circle className="chart-point chart-point-min" cx={point.x} cy={point.min_y} r="4" />}
          {point.max_y !== null && <circle className="chart-point chart-point-max" cx={point.x} cy={point.max_y} r="4" />}
          {shouldShowChartLabel(index, pricePoints.length) && <text className="chart-label" x={point.x} y={height - 8} textAnchor="middle">{formatChartDate(point.date)}</text>}
        </g>)}
      </> : <>
        {lineSegments(stockPoints, "y").map((segment, index) => <polyline key={`stock-${index}`} className="chart-line chart-line-stock" points={segment.join(" ")} />)}
        {stockPoints.map((point, index) => <g key={point.date} onMouseEnter={() => setActiveIndex(index)}>
          {point.y !== null && <circle className="chart-point chart-point-stock" cx={point.x} cy={point.y} r="4" />}
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
  return <section className="detail-overview table-card">
    <div className="detail-overview-image"><ProductImage competitor={competitor} /></div>
    <div className="detail-overview-main">
      <h2>{competitor.title || "未采集"}</h2>
      <dl className="detail-facts">
        <div><dt>店铺名称</dt><dd>{competitor.shop_name || "未采集"}</dd></div>
        <div><dt>商品链接</dt><dd><a href={competitor.url} target="_blank" rel="noreferrer">{competitor.url}</a></dd></div>
        <div><dt>offerId</dt><dd>{competitor.offer_id}</dd></div>
        <div><dt>所属竞品组</dt><dd className="detail-group-value"><span className="detail-group-badge">{getCompetitorGroupLabel(competitor.group_id, groups)}</span><button type="button" className="detail-group-edit" onClick={onChangeGroup}>修改</button></dd></div>
      </dl>
    </div>
    <div className="detail-overview-stats">
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

export function DetailPage({ data, groups, status, error, days, onRetry, onRangeChange, onBack, onChangeGroup, onLifecycleAction, lifecycleSubmitting = false, onNavigate }: DetailPageProps) {
  if (status === "loading") return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel"><div className="spinner" /><strong>正在加载竞品详情…</strong></div></AppShell>;
  if (status === "error" || data === null) return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品详情。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div></AppShell>;
  return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情">
    <header className="page-header detail-page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、变化趋势、SKU 信息和历史记录。</p></div><div className="detail-page-actions"><button type="button" className="secondary-button" onClick={onBack}>返回竞品列表</button>{data.competitor.is_active ? <button type="button" className="secondary-button" onClick={() => onLifecycleAction?.("stop", data.competitor)} disabled={lifecycleSubmitting}>停止监控</button> : <button type="button" className="primary-button" onClick={() => onLifecycleAction?.("resume", data.competitor)} disabled={lifecycleSubmitting}>恢复监控</button>}<button type="button" className="detail-danger-button" onClick={() => onLifecycleAction?.("delete", data.competitor)} disabled={lifecycleSubmitting}>删除竞品</button></div></header>
     <DetailOverview data={data} groups={groups} onChangeGroup={onChangeGroup} />
    <section className="detail-trends"><div className="detail-trends-header"><div><h2>趋势数据</h2><span>价格和库存来自每日最终 ProductSnapshot</span></div><div className="range-selector" role="group" aria-label="趋势时间范围"><button type="button" aria-pressed={days === 7} className={days === 7 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(7)}>近 7 天</button><button type="button" aria-pressed={days === 30} className={days === 30 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(30)}>近 30 天</button></div></div><div className="detail-trend-grid"><DetailTrendCard kind="price" title="价格趋势" description="最低价 / 最高价" trend={data.daily_trend} /><DetailTrendCard kind="stock" title="库存趋势" description="全部 SKU 库存总和" trend={data.daily_trend} /><SalesPlaceholderCard /></div></section>
    <div className="detail-lower-grid">
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>SKU 信息</h2><span>{data.latest_snapshot ? `共 ${data.latest_snapshot.sku_count} 个` : "当前快照"}</span></div></div>{data.latest_skus.length === 0 ? <div className="detail-empty">暂无 SKU 数据</div> : <div className="table-scroll"><table><thead><tr><th>SKU 规格</th><th>SKU ID</th><th>库存</th><th>SKU 价格</th></tr></thead><tbody>{data.latest_skus.map((sku) => <tr key={sku.sku_id}><td>{sku.sku_name}</td><td>{sku.sku_id}</td><td>{sku.stock === null ? "—" : sku.stock}</td><td>{sku.price === null ? "—" : `¥${sku.price}`}</td></tr>)}</tbody></table></div>}</section>
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>最近变化</h2><span>最近 20 条</span></div></div>{data.recent_changes.length === 0 ? <div className="detail-empty">暂无变化记录</div> : <div className="detail-record-list">{data.recent_changes.map((change) => <div className="detail-record-row" key={change.id}><strong>{formatChange(change)}</strong><time>{formatDate(change.detected_at)}</time></div>)}</div>}</section>
      <section className="table-card detail-section-card"><div className="table-heading"><div><h2>最近采集记录</h2><span>最近 20 条</span></div></div>{data.recent_collection_runs.length === 0 ? <div className="detail-empty">暂无采集记录</div> : <div className="table-scroll"><table className="collection-runs-table"><thead><tr><th>开始时间</th><th>结束时间</th><th>状态</th><th>结果</th></tr></thead><tbody>{data.recent_collection_runs.map((run) => <tr key={run.id}><td>{formatDate(run.started_at)}</td><td>{run.finished_at ? formatDate(run.finished_at) : "—"}</td><td>{run.status === "success" ? "成功" : run.status === "failed" ? "失败" : "采集中"}</td><td>{run.status === "failed" ? run.error_message || "采集失败" : run.status === "success" ? "成功" : "—"}</td></tr>)}</tbody></table></div>}</section>
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
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="dialog-title">添加竞品</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={busy}>×</button></div>
    <p className="dialog-description">添加 1688 商品链接，系统会保存监控对象。</p>
    <form onSubmit={onSubmit}><div className="dialog-field-header"><label htmlFor="competitor-url">1688 商品链接</label><button type="button" className="text-button clipboard-add-button" onClick={() => void handleClipboardAdd()} disabled={busy}>从剪贴板添加</button></div><textarea id="competitor-url" rows={5} value={url} onChange={(event) => { setClipboardFeedback(null); onUrlChange(event.target.value); }} placeholder={"https://detail.1688.com/offer/123456789.html\nhttps://detail.1688.com/offer/987654321.html"} autoComplete="off" spellCheck={false} autoCapitalize="none" autoCorrect="off" disabled={busy} /><p className="hint">每行一个链接，支持一次添加多个竞品；仅支持 detail.1688.com/offer/{"{offerId}"}.html</p>{clipboardFeedback && <p className={"clipboard-feedback clipboard-feedback-" + clipboardFeedback.kind} role="status" aria-live="polite">{clipboardFeedback.message}</p>}<label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={groupId === null ? "" : String(groupId)} onChange={(event) => onGroupChange(event.target.value ? Number(event.target.value) : null)} disabled={busy}><option value="">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select><label htmlFor="new-competitor-group">新增竞品组</label><div className="group-create-controls"><input id="new-competitor-group" type="text" value={newGroupName} onChange={(event) => onNewGroupNameChange(event.target.value)} placeholder="输入商品型号作为组名，例如 A19" maxLength={64} disabled={busy} /><button type="button" className="secondary-button" onClick={onCreateGroup} disabled={busy || groupCreateStatus === "submitting"}>{groupCreateStatus === "submitting" ? "创建中…" : "创建"}</button></div><div className={getGroupFeedbackClass(groupCreateStatus)} role="status" aria-live="polite">{groupCreateStatus === "success" && "竞品组已创建并已选中。"}{groupCreateStatus === "invalid" && "请输入有效的竞品组名称"}{groupCreateStatus === "duplicate" && "该竞品组已存在"}{groupCreateStatus === "server-error" && "竞品组创建失败，请稍后重试。"}</div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>取消</button><button type="submit" className="primary-button" disabled={busy || urlCount === 0}>{busy ? (progress.total ? `正在添加 ${progress.completed} / ${progress.total}…` : "正在添加…") : urlCount > 1 ? `添加 ${urlCount} 个竞品` : "添加竞品"}</button></div></form>
    <div className={"feedback feedback-" + status} role="status" aria-live="polite">{status === "partial" && `已添加 ${succeededCount} 个，${failures.length} 个未添加`}{status === "failed" && `未添加 ${failures.length} 个竞品`}{status === "invalid" && "链接无效：请输入指定格式的 1688 商品链接。"}{status === "duplicate" && "该 1688 商品已经添加。"}{status === "server-error" && "服务暂时不可用，请稍后重试。"}</div>
    {failures.length > 0 && <div className="add-failures" role="status" aria-live="polite"><strong>未添加：</strong><ul>{failures.map((failure) => <li key={failure.url}>{failure.url} — {failure.reason}</li>)}</ul></div>}
  </section></div>;
}

function App() {
  const [page, setPage] = useState<Page>("dashboard");
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [groups, setGroups] = useState<CompetitorGroup[]>([]);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashboardStatus, setDashboardStatus] = useState<DashboardStatus>("loading");
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [listStatus, setListStatus] = useState<ListStatus>("ready");
  const [listError, setListError] = useState<string | null>(null);
  const [listLoaded, setListLoaded] = useState(false);
  const [groupSummary, setGroupSummary] = useState<CompetitorGroupsSummary | null>(null);
  const [groupStatus, setGroupStatus] = useState<GroupStatus>("loading");
  const [groupError, setGroupError] = useState<string | null>(null);
  const [groupLoaded, setGroupLoaded] = useState(false);
  const [listNavigationIntent, setListNavigationIntent] = useState<ListNavigationIntent>({ filter: null, version: 0 });
  const [detailStatus, setDetailStatus] = useState<DetailStatus>("loading");
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CompetitorDetail | null>(null);
  const [detailDays, setDetailDays] = useState<7 | 30>(7);
  const [selectedCompetitorId, setSelectedCompetitorId] = useState<number | null>(null);
  const latestDetailRequestId = useRef(0);
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
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const batchStateRef = useRef(batchState);
  const reconcileSelection = useCallback((visibleActiveIds: number[]) => {
    setSelectedIds((current) => {
      const next = reconcileSelectedIds(current, visibleActiveIds);
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
  const [groupAssignmentDialog, setGroupAssignmentDialog] = useState<{ competitorId: number; groupId: number | null } | null>(null);
  const [groupAssignmentSubmitting, setGroupAssignmentSubmitting] = useState(false);
  const [groupAssignmentError, setGroupAssignmentError] = useState<string | null>(null);

  async function loadCompetitors() {
    setListStatus("loading"); setListError(null);
    try { const [competitorsResponse, groupsResponse] = await Promise.all([fetch("/api/competitors"), fetch("/api/competitor-groups")]); if (!competitorsResponse.ok || !groupsResponse.ok) throw new Error("request failed"); const [competitorData, groupData] = await Promise.all([competitorsResponse.json(), groupsResponse.json()]); const nextCompetitors = competitorData as Competitor[]; setCompetitors(nextCompetitors); setSelectedIds((current) => new Set([...current].filter((id) => nextCompetitors.some((item) => item.id === id && item.is_active)))); setGroups(groupData as CompetitorGroup[]); setListStatus("ready"); setListLoaded(true); }
    catch { setListError("暂时无法获取竞品列表，请检查服务是否正常运行。"); setListStatus("error"); }
  }
  async function loadDashboard() {
    setDashboardStatus("loading"); setDashboardError(null);
    try { const [dashboardResponse, groupsResponse] = await Promise.all([fetch("/api/dashboard/today"), fetch("/api/competitor-groups")]); if (!dashboardResponse.ok || !groupsResponse.ok) throw new Error("request failed"); const [dashboardData, groupData] = await Promise.all([dashboardResponse.json(), groupsResponse.json()]); setDashboard(dashboardData as DashboardData); setGroups(groupData as CompetitorGroup[]); setDashboardStatus("ready"); }
    catch { setDashboardError("暂时无法获取今日变化，请检查服务是否正常运行。"); setDashboardStatus("error"); }
  }
  async function loadGroups() {
    setGroupStatus("loading"); setGroupError(null);
    try {
      const [summaryResponse, groupsResponse] = await Promise.all([fetch("/api/competitor-groups/summary"), fetch("/api/competitor-groups")]);
      if (!summaryResponse.ok || !groupsResponse.ok) throw new Error("request failed");
      const [summaryData, groupData] = await Promise.all([summaryResponse.json(), groupsResponse.json()]);
      setGroupSummary(summaryData as CompetitorGroupsSummary);
      setGroups(groupData as CompetitorGroup[]);
      setGroupStatus("ready"); setGroupLoaded(true);
    } catch {
      setGroupError("暂时无法获取竞品组，请检查服务是否正常运行。"); setGroupStatus("error"); setGroupLoaded(false);
    }
  }
  async function loadDetail(competitorId: number, days: 7 | 30) {
    const requestId = ++latestDetailRequestId.current;
    setDetailStatus("loading"); setDetailError(null);
    try {
      const response = await fetch(`/api/competitors/${competitorId}/detail?days=${days}`);
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        throw new Error(getCollectionErrorMessage(body.code, body.message));
      }
      const data = await response.json() as CompetitorDetail;
      if (!isCurrentDetailRequest(requestId, latestDetailRequestId.current)) return;
      setDetail(data); setDetailStatus("ready");
    } catch (error) {
      if (!isCurrentDetailRequest(requestId, latestDetailRequestId.current)) return;
      setDetailError(error instanceof Error ? error.message : "暂时无法获取竞品详情，请稍后重试。"); setDetailStatus("error");
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
      if (next.status === "completed" && previous.status === "running") {
        await Promise.all([loadCompetitors(), loadDashboard()]);
        setNotice({ message: `采集完成：成功 ${next.succeeded}，失败 ${next.failed}`, type: next.failed ? "error" : "success" });
      }
    } catch {
      if (notifyOnError) setNotice({ message: "无法读取批量采集状态，请稍后重试。", type: "error" });
    }
  }
  useEffect(() => { void loadDashboard(); }, []);
  useEffect(() => { void loadBatchStatus(); }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (batchState.status !== "completed") return;
    const timer = window.setTimeout(() => {
      batchStateRef.current = idleBatchState;
      setBatchState(idleBatchState);
    }, 4000);
    return () => window.clearTimeout(timer);
  }, [batchState.status]);
  useEffect(() => {
    if (batchState.status !== "running" && !(batchState.status === "verification_required" && batchState.browser_open)) return;
    const timer = window.setInterval(() => { void loadBatchStatus(); }, 1500);
    return () => window.clearInterval(timer);
  }, [batchState.status, batchState.browser_open]);
  function navigate(nextPage: Page, initialGroupFilter: InitialGroupFilter = null) {
    if (nextPage !== "detail") latestDetailRequestId.current += 1;
    setListNavigationIntent((current) => ({ filter: nextPage === "competitors" ? initialGroupFilter : null, version: current.version + 1 }));
    setPage(nextPage);
    if (nextPage === "dashboard") void loadDashboard();
    if (nextPage === "competitors" && !listLoaded) void loadCompetitors();
    if (nextPage === "groups" && !groupLoaded) void loadGroups();
  }
  function openDetail(competitorId: number) { setSelectedCompetitorId(competitorId); setDetailDays(7); setPage("detail"); void loadDetail(competitorId, 7); }
  function changeDetailRange(days: 7 | 30) { if (selectedCompetitorId === null) return; setDetailDays(days); void loadDetail(selectedCompetitorId, days); }
  function openDialog() { setNotice(null); setUrl(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupId(null); setNewGroupName(""); setGroupCreateStatus("initial"); setDialogOpen(true); }
  function closeDialog() { if (addStatus !== "submitting") { setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupCreateStatus("initial"); } }
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
      setGroupNameDialog(null); setGroupName(""); setNotice({ message: isRename ? "竞品组已重命名。" : "竞品组已创建。", type: "success" });
      await loadGroups();
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
      setGroupDeleteDialog(null); setNotice({ message: "竞品组已删除，竞品已移至未分组。", type: "success" });
      await Promise.all([loadGroups(), loadCompetitors(), loadDashboard()]);
    } catch {
      setGroupDeleteError("竞品组删除失败，请稍后重试");
    } finally { setGroupDeleteSubmitting(false); }
  }
  function openGroupAssignmentDialog() {
    if (!detail) return;
    setGroupAssignmentError(null);
    setGroupAssignmentDialog({ competitorId: detail.competitor.id, groupId: detail.competitor.group_id });
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
      setNotice({ message: "竞品组已更新。", type: "success" });
      await Promise.all([loadDetail(groupAssignmentDialog.competitorId, detailDays), loadCompetitors(), loadDashboard(), loadGroups()]);
    } catch {
      setGroupAssignmentError("竞品组更新失败，请稍后重试");
    } finally { setGroupAssignmentSubmitting(false); }
  }
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const urls = parseCompetitorUrls(url);
    if (addStatus === "submitting" || urls.length === 0) return;
    setAddStatus("submitting"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: urls.length });
    const result = await addCompetitorsSequentially(urls, groupId, fetch, (completed, total) => setAddProgress({ completed, total }));
    if (result.failures.length === 0) {
      setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setGroupCreateStatus("initial"); setAddProgress({ completed: 0, total: 0 }); setNotice({ message: `已添加 ${result.succeeded.length} 个竞品`, type: "success" }); await Promise.all([loadCompetitors(), loadDashboard()]); return;
    }
    setAddFailures(result.failures); setAddSucceededCount(result.succeeded.length); setUrl(result.failures.map((failure) => failure.url).join("\n")); setAddStatus(result.succeeded.length ? "partial" : "failed");
    if (result.succeeded.length > 0) await Promise.all([loadCompetitors(), loadDashboard()]);
  }
  async function handleBatchAction(mode: "selected" | "all_active") {
    const ids = [...selectedIds];
    setNotice(null);
    try {
      const response = await fetch("/api/competitors/collect-batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mode === "selected" ? { mode, competitor_ids: ids } : { mode }) });
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
  async function refreshAfterLifecycle(message: string, competitor: LifecycleCompetitor, deleted = false) {
    setLifecycleDialog(null); setLifecycleError(null);
    setGroupLoaded(false);
    if (deleted) {
      latestDetailRequestId.current += 1;
      setDetail(null); setDetailError(null); setDetailStatus("loading"); setSelectedCompetitorId(null);
      navigate("competitors");
      await Promise.all([loadCompetitors(), loadDashboard()]);
    } else {
      await Promise.all([loadCompetitors(), loadDashboard(), loadDetail(competitor.id, detailDays)]);
    }
    setNotice({ message, type: "success" });
  }
  async function updateMonitoring(competitor: LifecycleCompetitor, isActive: boolean, dialogAction: "stop" | null) {
    setLifecycleSubmitting(true); setLifecycleError(null);
    try {
      const response = await fetch(`/api/competitors/${competitor.id}/monitoring`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: isActive }) });
      if (!response.ok) throw new Error(await readLifecycleError(response));
      await refreshAfterLifecycle(isActive ? "已恢复监控，列表和 Dashboard 已更新。" : "已停止监控，历史数据已保留。", competitor);
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
      await refreshAfterLifecycle("竞品已永久删除。", competitor, true);
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
  return <>{page === "dashboard" ? <DashboardPage data={dashboard} groups={groups} status={dashboardStatus} error={dashboardError} batchState={batchState} onRetry={() => void loadDashboard()} onNavigate={navigate} onAdd={openDialog} onCollect={() => void handleBatchAction("all_active")} onOpenDetail={openDetail} /> : page === "competitors" ? <ListPage competitors={competitors} groups={groups} status={listStatus} error={listError} onRetry={() => void loadCompetitors()} onAdd={openDialog} batchState={batchState} selectedIds={selectedIds} onToggleSelected={(competitorId) => setSelectedIds((current) => { const next = new Set(current); if (next.has(competitorId)) next.delete(competitorId); else next.add(competitorId); return next; })} onToggleAll={(checked, competitorIds) => setSelectedIds(checked ? new Set(competitorIds) : new Set())} onReconcileSelection={reconcileSelection} onBatchAction={(mode) => void handleBatchAction(mode)} onOpenDetail={openDetail} onNavigate={navigate} initialGroupFilter={listNavigationIntent.filter} navigationVersion={listNavigationIntent.version} /> : page === "groups" ? <GroupPage summary={groupSummary} status={groupStatus} error={groupError} onRetry={() => void loadGroups()} onCreate={openGroupCreateDialog} onViewCompetitors={(filter) => navigate("competitors", filter)} onRename={openGroupRenameDialog} onDelete={openGroupDeleteDialog} onNavigate={navigate} /> : <DetailPage data={detail} groups={groups} status={detailStatus} error={detailError} days={detailDays} onRetry={() => selectedCompetitorId !== null && void loadDetail(selectedCompetitorId, detailDays)} onRangeChange={changeDetailRange} onBack={() => navigate("competitors")} onChangeGroup={openGroupAssignmentDialog} onLifecycleAction={handleLifecycleAction} lifecycleSubmitting={lifecycleSubmitting} onNavigate={navigate} />}{notice && <div className={"toast toast-" + notice.type} role="status">{notice.message}</div>}{dialogOpen && <AddDialog url={url} status={addStatus} onUrlChange={setUrl} onSubmit={handleSubmit} onClose={closeDialog} groups={groups} groupId={groupId} onGroupChange={setGroupId} newGroupName={newGroupName} onNewGroupNameChange={setNewGroupName} onCreateGroup={() => void handleCreateGroup()} groupCreateStatus={groupCreateStatus} failures={addFailures} succeededCount={addSucceededCount} progress={addProgress} />}{groupNameDialog && <GroupNameDialog mode={groupNameDialog.mode} name={groupName} submitting={groupNameSubmitting} error={groupNameError} onChange={setGroupName} onClose={closeGroupNameDialog} onSubmit={submitGroupName} />}{groupDeleteDialog && <GroupDeleteDialog group={groupDeleteDialog} submitting={groupDeleteSubmitting} error={groupDeleteError} onClose={closeGroupDeleteDialog} onConfirm={() => void confirmGroupDelete()} />}{groupAssignmentDialog && <GroupAssignmentDialog groupId={groupAssignmentDialog.groupId} groups={groups} submitting={groupAssignmentSubmitting} error={groupAssignmentError} onChange={(groupId) => setGroupAssignmentDialog((current) => current ? { ...current, groupId } : current)} onClose={closeGroupAssignmentDialog} onSubmit={submitGroupAssignment} />}{lifecycleDialog && <ConfirmDialog action={lifecycleDialog.action} competitor={lifecycleDialog.competitor} submitting={lifecycleSubmitting} error={lifecycleError} onClose={closeLifecycleDialog} onConfirm={confirmLifecycleAction} />}</>;
}

export default App;
