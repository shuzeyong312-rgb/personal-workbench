import { createPortal } from "react-dom";
import { FormEvent, type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import "./App.css";

type AddStatus = "initial" | "submitting" | "success" | "partial" | "failed" | "invalid" | "duplicate" | "server-error";
type GroupCreateStatus = "initial" | "submitting" | "success" | "invalid" | "duplicate" | "server-error";
type ListStatus = "loading" | "error" | "ready";
type DashboardStatus = "loading" | "error" | "ready";
export type BatchStatus = "idle" | "running" | "completed" | "verification_required";
export type Page = "dashboard" | "competitors" | "detail";
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
  };
  items: DashboardItem[];
};

export type PriceTrend = {
  snapshot_id: number;
  captured_at: string;
  price_min: string | null;
  price_max: string | null;
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
  } | null;
  latest_skus: { sku_id: string; sku_name: string; stock: number | null; price: string | null }[];
  price_trend: PriceTrend[];
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
  snapshot_id: number;
  captured_at: string;
  x: number;
  min_y: number | null;
  max_y: number | null;
  price_min: string | null;
  price_max: string | null;
};

export function buildPriceChartPoints(trend: readonly PriceTrend[], width = 640, height = 220): PriceChartPoint[] {
  const usable = trend.filter((item) => item.price_min !== null || item.price_max !== null);
  const values = usable.flatMap((item) => [item.price_min, item.price_max]).flatMap((value) => {
    const number = value === null ? NaN : Number(value);
    return Number.isFinite(number) ? [number] : [];
  });
  if (usable.length === 0 || values.length === 0) return [];
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueRange = maxValue === minValue ? 1 : maxValue - minValue;
  const left = 44;
  const right = 16;
  const top = 16;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const y = (value: string | null) => value === null ? null : top + ((maxValue - Number(value)) / valueRange) * plotHeight;
  return usable.map((item, index) => ({
    snapshot_id: item.snapshot_id,
    captured_at: item.captured_at,
    x: usable.length === 1 ? left + plotWidth / 2 : left + (index / (usable.length - 1)) * plotWidth,
    min_y: y(item.price_min),
    max_y: y(item.price_max),
    price_min: item.price_min,
    price_max: item.price_max,
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

export function formatPriceDisplay(snapshot: Competitor["latest_snapshot"]): string {
  const min = snapshot?.price_min?.trim() || "";
  const max = snapshot?.price_max?.trim() || "";
  if (!min && !max) return "未采集";
  if (min && max && min === max) return `¥${min}`;
  if (min && max) return `¥${min} ~ ¥${max}`;
  return `¥${min || max}`;
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
        <button className="nav-item nav-child nav-disabled" disabled><span className="nav-dot" aria-hidden="true" />竞品分组</button>
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

type MoreMenuRect = Pick<DOMRect, "top" | "bottom" | "right">;
type MoreMenuSize = Pick<DOMRect, "width" | "height">;

export function getMoreMenuPosition(
  buttonRect: MoreMenuRect,
  menuSize: MoreMenuSize,
  viewportWidth: number,
  viewportHeight: number,
): { top: number; left: number } {
  const margin = 8;
  const gap = 6;
  const width = menuSize.width || 132;
  const height = menuSize.height || 96;
  const left = Math.min(Math.max(margin, buttonRect.right - width), Math.max(margin, viewportWidth - width - margin));
  const opensBelow = buttonRect.bottom + gap + height <= viewportHeight - margin;
  return {
    top: opensBelow ? buttonRect.bottom + gap : Math.max(margin, buttonRect.top - gap - height),
    left,
  };
}

export function MoreMenu({ competitor, open, onToggle, onAction, disabled = false }: { competitor: Competitor; open: boolean; onToggle: () => void; onAction: (action: LifecycleAction) => void; disabled?: boolean }) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || typeof window === "undefined") return;
    const button = buttonRef.current;
    if (!button) return;
    setPosition(getMoreMenuPosition(button.getBoundingClientRect(), menuRef.current?.getBoundingClientRect() || { width: 0, height: 0 }, window.innerWidth, window.innerHeight));
  }, [open]);

  useEffect(() => {
    if (!open || typeof document === "undefined") return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!buttonRef.current?.contains(target) && !menuRef.current?.contains(target)) onToggle();
    };
    const closeOnViewportChange = () => onToggle();
    document.addEventListener("mousedown", closeOnOutsideClick);
    window.addEventListener("scroll", closeOnViewportChange, true);
    window.addEventListener("resize", closeOnViewportChange);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      window.removeEventListener("scroll", closeOnViewportChange, true);
      window.removeEventListener("resize", closeOnViewportChange);
    };
  }, [open, onToggle]);

  const menu = open && <div ref={menuRef} className="more-menu-popover" role="menu" data-more-menu-portal="body" style={{ top: position?.top ?? 0, left: position?.left ?? 0, visibility: position ? "visible" : "hidden" }}>
    {competitor.is_active ? <button type="button" role="menuitem" onClick={() => onAction("stop")}>停止监控</button> : <button type="button" role="menuitem" onClick={() => onAction("resume")}>恢复监控</button>}
    <button type="button" role="menuitem" className="more-menu-danger" onClick={() => onAction("delete")}>删除竞品</button>
  </div>;

  return <><div className="more-menu"><button ref={buttonRef} type="button" className="detail-button" aria-haspopup="menu" aria-expanded={open} onClick={onToggle} disabled={disabled}>更多</button></div>{open && !disabled && (typeof document === "undefined" ? menu : createPortal(menu, document.body))}</>;
}

export function ConfirmDialog({ action, competitor, submitting, error, onClose, onConfirm }: { action: "stop" | "delete"; competitor: Competitor; submitting: boolean; error: string | null; onClose: () => void; onConfirm: () => void }) {
  const isDelete = action === "delete";
  const productLabel = competitor.title?.trim() || competitor.offer_id;
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="lifecycle-dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="lifecycle-dialog-title">{isDelete ? "永久删除竞品" : "停止监控"}</h2></div><button className="close-button" onClick={onClose} aria-label="关闭" disabled={submitting}>×</button></div>
    {isDelete ? <p className="dialog-description">删除后，该竞品的历史快照、SKU、变化记录和采集记录都会永久删除，无法恢复。<br />当前商品：{productLabel}</p> : <p className="dialog-description">停止后将不再自动采集该竞品，但历史数据会保留，之后可以恢复监控。</p>}
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    <div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={submitting}>取消</button><button type="button" className={isDelete ? "danger-button" : "primary-button"} onClick={onConfirm} disabled={submitting}>{isDelete ? "确认删除" : "停止监控"}</button></div>
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
  onLifecycleAction?: (action: LifecycleAction, competitor: Competitor) => void;
  onNavigate?: (page: Page) => void;
};

export function ListPage({ competitors, groups, status, error, onRetry, onAdd, batchState = idleBatchState, selectedIds = new Set<number>(), onToggleSelected = noop, onToggleAll = noop, onReconcileSelection = noop, onBatchAction = noop, onOpenDetail, onLifecycleAction, onNavigate }: ListPageProps) {
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);
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
            {filteredCompetitors.map((competitor) => <tr key={competitor.id}><td className="selection-column"><input type="checkbox" aria-label={`选择 ${competitor.title || competitor.offer_id}`} checked={competitor.is_active && selectedIds.has(competitor.id)} disabled={!competitor.is_active || batchBusy} onChange={() => onToggleSelected(competitor.id)} /></td><td><div className="product-cell"><ProductImage competitor={competitor} /><div><strong>{competitor.title || "未采集"}</strong><span>offerId：{competitor.offer_id}</span><a href={competitor.url} target="_blank" rel="noreferrer">查看 1688 商品 ↗</a></div></div></td><td>{competitor.shop_name || "未采集"}</td><td>{getCompetitorGroupLabel(competitor.group_id, groups)}</td><td className={competitor.latest_snapshot?.price_min || competitor.latest_snapshot?.price_max ? "price-cell" : "muted-cell"}>{formatPriceDisplay(competitor.latest_snapshot)}</td><td className={competitor.latest_snapshot === null ? "muted-cell" : "sku-cell"}>{competitor.latest_snapshot === null ? "未采集" : competitor.latest_snapshot.sku_count}</td><td className={competitor.latest_change === null ? "muted-cell" : "change-cell"}>{formatLatestChange(competitor.latest_change)}</td><td className="collection-date-cell">{formatDate(competitor.last_collected_at)}</td><td><StatusBadge status={competitor.status} /></td><td><span className={competitor.is_active ? "list-monitoring-badge" : "list-monitoring-badge list-monitoring-inactive"}>{competitor.is_active ? "监控中" : "已停止"}</span></td><td><div className="row-actions"><button type="button" className="detail-button" onClick={() => onOpenDetail?.(competitor.id)}>详情</button><MoreMenu competitor={competitor} disabled={batchBusy} open={openMenuId === competitor.id} onToggle={() => setOpenMenuId(openMenuId === competitor.id ? null : competitor.id)} onAction={(action) => { setOpenMenuId(null); onLifecycleAction?.(action, competitor); }} /></div></td></tr>) }
          </tbody></table></div>}
        </section>
        <div className="pagination-bar"><span>显示全部竞品</span><button disabled>上一页</button><span className="page-number">1</span><button disabled>下一页</button><span>分页暂未开放</span></div>
    </AppShell>
  );
}

type DashboardPageProps = { data: DashboardData | null; groups: CompetitorGroup[]; status: DashboardStatus; error: string | null; onRetry: () => void; onNavigate: (page: Page) => void; onOpenDetail?: (competitorId: number) => void };

export function DashboardPage({ data, groups, status, error, onRetry, onNavigate, onOpenDetail }: DashboardPageProps) {
  return <AppShell page="dashboard" onNavigate={onNavigate} breadcrumb="竞品监控大屏">
    <header className="page-header"><div><h1>竞品监控大屏</h1><p className="page-description">查看今日真正发生的竞品变化，及时掌握监控动态。</p></div></header>
    <section className="dashboard-stats" aria-label="今日变化统计">
      <div className="dashboard-stat-card"><span className="dashboard-stat-icon dashboard-stat-blue">◌</span><div><span>监控竞品</span><strong>{status === "ready" && data ? data.stats.monitored_competitors : "—"}</strong></div></div>
      <div className="dashboard-stat-card"><span className="dashboard-stat-icon dashboard-stat-purple">↗</span><div><span>今日变化竞品</span><strong>{status === "ready" && data ? data.stats.changed_competitors : "—"}</strong></div></div>
      <div className="dashboard-stat-card"><span className="dashboard-stat-icon dashboard-stat-orange">✦</span><div><span>今日变化事件</span><strong>{status === "ready" && data ? data.stats.change_events : "—"}</strong></div></div>
    </section>
    <section className="table-card dashboard-change-section">
      <div className="table-heading"><div><h2>今日变化</h2><span>{status === "ready" && data ? data.date : "本地业务日"}</span></div><span className="table-count">{status === "ready" && data ? `${data.stats.changed_competitors} 个竞品` : "—"}</span></div>
      {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载今日变化…</strong></div>}
      {status === "error" && <div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取今日变化。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div>}
      {status === "ready" && data && data.items.length === 0 && <div className="state-panel"><div className="empty-icon">✓</div><strong>今天暂无竞品变化</strong><span>系统会继续按照每日采集规则监控竞品变化。</span></div>}
      {status === "ready" && data && data.items.length > 0 && <div className="dashboard-change-grid">{data.items.map((item) => <article className="dashboard-change-card" key={item.competitor_id}>
        <div className="dashboard-item-header"><div className="dashboard-product"><span className="product-image product-image-placeholder">{item.main_image_url ? <img className="product-image" src={item.main_image_url} alt="" /> : "暂无主图"}</span><div><strong>{item.title || "未采集"}</strong><span>{item.shop_name || "未采集"}</span></div></div><span className="dashboard-change-count">{item.changes.length} 条变化</span></div>
        <div className="dashboard-meta"><span>竞品组：{getCompetitorGroupLabel(item.group_id, groups)}</span><span>最近采集：{formatDate(item.last_collected_at)}</span></div>
        <button type="button" className="text-button dashboard-detail-button" onClick={() => onOpenDetail?.(item.competitor_id)}>查看详情</button>
        <ul className="dashboard-change-list">{item.changes.map((change) => <li key={change.id}><span>{formatChange(change)}</span><time>{formatDate(change.detected_at)}</time></li>)}</ul>
      </article>)}</div>}
    </section>
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
  onNavigate: (page: Page) => void;
};

function formatChartDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(new Date(value));
}

function PriceChart({ trend }: { trend: PriceTrend[] }) {
  const width = 640;
  const height = 220;
  const points = buildPriceChartPoints(trend, width, height);
  if (points.length === 0) return <div className="detail-empty">该时间范围暂无可用价格数据</div>;
  const line = (key: "min_y" | "max_y") => points.filter((point) => point[key] !== null).map((point) => `${point.x},${point[key]}`).join(" ");
  return <div className="price-chart-wrap">
    <svg className="price-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="价格趋势">
      {[0, 1, 2, 3].map((step) => <line key={step} className="chart-grid-line" x1="44" x2="624" y1={16 + step * 56.67} y2={16 + step * 56.67} />)}
      <polyline className="chart-line chart-line-min" points={line("min_y")} />
      <polyline className="chart-line chart-line-max" points={line("max_y")} />
      {points.map((point) => <g key={point.snapshot_id}>
        {point.min_y !== null && <circle className="chart-point chart-point-min" cx={point.x} cy={point.min_y} r="4" />}
        {point.max_y !== null && <circle className="chart-point chart-point-max" cx={point.x} cy={point.max_y} r="4" />}
        <text className="chart-label" x={point.x} y="207" textAnchor="middle">{formatChartDate(point.captured_at)}</text>
      </g>)}
    </svg>
    <div className="chart-legend"><span><i className="legend-dot legend-dot-min" />最低价</span><span><i className="legend-dot legend-dot-max" />最高价</span></div>
  </div>;
}

function DetailOverview({ data, groups }: { data: CompetitorDetail; groups: CompetitorGroup[] }) {
  const competitor = data.competitor;
  return <section className="detail-overview table-card">
    <div className="detail-overview-image"><ProductImage competitor={competitor} /></div>
    <div className="detail-overview-main">
      <h2>{competitor.title || "未采集"}</h2>
      <div className="detail-overview-tags"><StatusBadge status={competitor.status} />{!competitor.is_active && <span className="detail-inactive-badge">已停止监控</span>}</div>
      <dl className="detail-facts">
        <div><dt>店铺名称</dt><dd>{competitor.shop_name || "未采集"}</dd></div>
        <div><dt>商品链接</dt><dd><a href={competitor.url} target="_blank" rel="noreferrer">{competitor.url}</a></dd></div>
        <div><dt>offerId</dt><dd>{competitor.offer_id}</dd></div>
        <div><dt>所属竞品组</dt><dd>{getCompetitorGroupLabel(competitor.group_id, groups)}</dd></div>
      </dl>
    </div>
    <div className="detail-overview-stats">
      <div className="detail-price-stat"><span>当前价格</span><strong>{formatPriceDisplay(data.latest_snapshot)}</strong><small>{data.latest_snapshot ? `采集于 ${formatDate(data.latest_snapshot.captured_at)}` : "暂无采集数据"}</small></div>
      <div className="detail-stat-grid"><div><span>商品状态</span><strong>{data.latest_snapshot ? <StatusBadge status={data.latest_snapshot.product_status} /> : "未采集"}</strong></div><div><span>SKU 数量</span><strong>{data.latest_snapshot ? data.latest_snapshot.sku_count : "未采集"}</strong></div><div><span>最近采集时间</span><strong>{formatDate(competitor.last_collected_at)}</strong></div><div><span>监控状态</span><strong>{competitor.is_active ? "监控中" : "已停止监控"}</strong></div></div>
    </div>
  </section>;
}

export function DetailPage({ data, groups, status, error, days, onRetry, onRangeChange, onBack, onNavigate }: DetailPageProps) {
  if (status === "loading") return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel"><div className="spinner" /><strong>正在加载竞品详情…</strong></div></AppShell>;
  if (status === "error" || data === null) return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情"><header className="page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、价格趋势、SKU 信息和历史记录。</p></div></header><div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品详情。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div></AppShell>;
  return <AppShell page="detail" onNavigate={onNavigate} breadcrumb="竞品列表 / 竞品详情">
    <header className="page-header detail-page-header"><div><h1>竞品详情</h1><p className="page-description">查看当前商品状态、SKU 信息、变化记录与趋势数据。</p></div><button type="button" className="secondary-button" onClick={onBack}>返回竞品列表</button></header>
    <DetailOverview data={data} groups={groups} />
    <section className="table-card detail-trend-card"><div className="table-heading"><div><h2>价格趋势</h2><span>基于 ProductSnapshot 价格事实</span></div><div className="range-selector" role="group" aria-label="价格趋势时间范围"><button type="button" aria-pressed={days === 7} className={days === 7 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(7)}>近 7 天</button><button type="button" aria-pressed={days === 30} className={days === 30 ? "range-button range-button-active" : "range-button"} onClick={() => onRangeChange(30)}>近 30 天</button></div></div><PriceChart trend={data.price_trend} /></section>
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
    <form onSubmit={onSubmit}><div className="dialog-field-header"><label htmlFor="competitor-url">1688 商品链接</label><button type="button" className="text-button clipboard-add-button" onClick={() => void handleClipboardAdd()} disabled={busy}>从剪贴板添加</button></div><textarea id="competitor-url" rows={5} value={url} onChange={(event) => { setClipboardFeedback(null); onUrlChange(event.target.value); }} placeholder={"https://detail.1688.com/offer/123456789.html\nhttps://detail.1688.com/offer/987654321.html"} autoComplete="off" spellCheck={false} autoCapitalize="none" autoCorrect="off" disabled={busy} /><p className="hint">每行一个链接，支持一次添加多个竞品；仅支持 detail.1688.com/offer/{"{offerId}"}.html</p>{clipboardFeedback && <p className={"clipboard-feedback clipboard-feedback-" + clipboardFeedback.kind} role="status" aria-live="polite">{clipboardFeedback.message}</p>}<label htmlFor="competitor-group">竞品组</label><select id="competitor-group" value={groupId === null ? "" : String(groupId)} onChange={(event) => onGroupChange(event.target.value ? Number(event.target.value) : null)} disabled={busy}><option value="">未分组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select><label htmlFor="new-competitor-group">新建分组</label><div className="group-create-controls"><input id="new-competitor-group" type="text" value={newGroupName} onChange={(event) => onNewGroupNameChange(event.target.value)} placeholder="输入分组名称" maxLength={64} disabled={busy} /><button type="button" className="secondary-button" onClick={onCreateGroup} disabled={busy || groupCreateStatus === "submitting"}>{groupCreateStatus === "submitting" ? "创建中…" : "创建"}</button></div><div className={getGroupFeedbackClass(groupCreateStatus)} role="status" aria-live="polite">{groupCreateStatus === "success" && "分组已创建并已选中。"}{groupCreateStatus === "invalid" && "请输入有效的分组名称"}{groupCreateStatus === "duplicate" && "该分组已存在"}{groupCreateStatus === "server-error" && "分组创建失败，请稍后重试。"}</div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={busy}>取消</button><button type="submit" className="primary-button" disabled={busy || urlCount === 0}>{busy ? (progress.total ? `正在添加 ${progress.completed} / ${progress.total}…` : "正在添加…") : urlCount > 1 ? `添加 ${urlCount} 个竞品` : "添加竞品"}</button></div></form>
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
  const [lifecycleDialog, setLifecycleDialog] = useState<{ action: "stop" | "delete"; competitor: Competitor } | null>(null);
  const [lifecycleSubmitting, setLifecycleSubmitting] = useState(false);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);

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
        await loadCompetitors();
        setNotice({ message: `采集完成：成功 ${next.succeeded}，失败 ${next.failed}`, type: next.failed ? "error" : "success" });
      }
    } catch {
      if (notifyOnError) setNotice({ message: "无法读取批量采集状态，请稍后重试。", type: "error" });
    }
  }
  useEffect(() => { void loadDashboard(); }, []);
  useEffect(() => { void loadBatchStatus(); }, []);
  useEffect(() => {
    if (batchState.status !== "running" && !(batchState.status === "verification_required" && batchState.browser_open)) return;
    const timer = window.setInterval(() => { void loadBatchStatus(); }, 1500);
    return () => window.clearInterval(timer);
  }, [batchState.status, batchState.browser_open]);
  function navigate(nextPage: Page) { if (nextPage !== "detail") latestDetailRequestId.current += 1; setPage(nextPage); if (nextPage === "competitors" && !listLoaded) void loadCompetitors(); }
  function openDetail(competitorId: number) { setSelectedCompetitorId(competitorId); setDetailDays(7); setPage("detail"); void loadDetail(competitorId, 7); }
  function changeDetailRange(days: 7 | 30) { if (selectedCompetitorId === null) return; setDetailDays(days); void loadDetail(selectedCompetitorId, days); }
  function openDialog() { setNotice(null); setUrl(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupId(null); setNewGroupName(""); setGroupCreateStatus("initial"); setDialogOpen(true); }
  function closeDialog() { if (addStatus !== "submitting") { setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: 0 }); setGroupCreateStatus("initial"); } }
  async function handleCreateGroup() {
    setGroupCreateStatus("submitting");
    try {
      const response = await fetch("/api/competitor-groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newGroupName }) });
      if (response.ok) { const group = await response.json() as CompetitorGroup; setGroups((current) => [...current, group]); setGroupId(group.id); setNewGroupName(""); setGroupCreateStatus("success"); return; }
      const body = await response.json() as { code?: string }; setGroupCreateStatus(getGroupCreateStatus(false, body.code));
    } catch { setGroupCreateStatus("server-error"); }
  }
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const urls = parseCompetitorUrls(url);
    if (addStatus === "submitting" || urls.length === 0) return;
    setAddStatus("submitting"); setAddFailures([]); setAddSucceededCount(0); setAddProgress({ completed: 0, total: urls.length });
    const result = await addCompetitorsSequentially(urls, groupId, fetch, (completed, total) => setAddProgress({ completed, total }));
    if (result.failures.length === 0) {
      setDialogOpen(false); setUrl(""); setGroupId(null); setNewGroupName(""); setAddStatus("initial"); setGroupCreateStatus("initial"); setAddProgress({ completed: 0, total: 0 }); setNotice({ message: `已添加 ${result.succeeded.length} 个竞品`, type: "success" }); await loadCompetitors(); return;
    }
    setAddFailures(result.failures); setAddSucceededCount(result.succeeded.length); setUrl(result.failures.map((failure) => failure.url).join("\n")); setAddStatus(result.succeeded.length ? "partial" : "failed");
    if (result.succeeded.length > 0) await loadCompetitors();
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
    } catch (error) {
      setNotice({ message: getCollectionFailureMessage({ kind: "request", error }), type: "error" });
    }
  }
  function openLifecycleDialog(action: "stop" | "delete", competitor: Competitor) {
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
  async function refreshAfterLifecycle(message: string) {
    setLifecycleDialog(null); setLifecycleError(null); setNotice({ message, type: "success" });
    await Promise.all([loadCompetitors(), loadDashboard()]);
  }
  async function updateMonitoring(competitor: Competitor, isActive: boolean, dialogAction: "stop" | null) {
    setLifecycleSubmitting(true); setLifecycleError(null);
    try {
      const response = await fetch(`/api/competitors/${competitor.id}/monitoring`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: isActive }) });
      if (!response.ok) throw new Error(await readLifecycleError(response));
      await refreshAfterLifecycle(isActive ? "已恢复监控，列表和 Dashboard 已更新。" : "已停止监控，历史数据已保留。" );
    } catch (error) {
      const message = error instanceof Error ? error.message : "操作失败，请稍后重试";
      if (dialogAction) setLifecycleError(message); else setNotice({ message, type: "error" });
    } finally { setLifecycleSubmitting(false); }
  }
  async function deleteCompetitor(competitor: Competitor) {
    setLifecycleSubmitting(true); setLifecycleError(null);
    try {
      const response = await fetch(`/api/competitors/${competitor.id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readLifecycleError(response));
      await refreshAfterLifecycle("竞品已永久删除，列表和 Dashboard 已更新。" );
    } catch (error) {
      setLifecycleError(error instanceof Error ? error.message : "操作失败，请稍后重试");
    } finally { setLifecycleSubmitting(false); }
  }
  function handleLifecycleAction(action: LifecycleAction, competitor: Competitor) {
    if (action === "stop" || action === "delete") { openLifecycleDialog(action, competitor); return; }
    void updateMonitoring(competitor, true, null);
  }
  function confirmLifecycleAction() {
    if (!lifecycleDialog) return;
    if (lifecycleDialog.action === "stop") void updateMonitoring(lifecycleDialog.competitor, false, "stop");
    else void deleteCompetitor(lifecycleDialog.competitor);
  }
  return <>{page === "dashboard" ? <DashboardPage data={dashboard} groups={groups} status={dashboardStatus} error={dashboardError} onRetry={() => void loadDashboard()} onNavigate={navigate} onOpenDetail={openDetail} /> : page === "competitors" ? <ListPage competitors={competitors} groups={groups} status={listStatus} error={listError} onRetry={() => void loadCompetitors()} onAdd={openDialog} batchState={batchState} selectedIds={selectedIds} onToggleSelected={(competitorId) => setSelectedIds((current) => { const next = new Set(current); if (next.has(competitorId)) next.delete(competitorId); else next.add(competitorId); return next; })} onToggleAll={(checked, competitorIds) => setSelectedIds(checked ? new Set(competitorIds) : new Set())} onReconcileSelection={reconcileSelection} onBatchAction={(mode) => void handleBatchAction(mode)} onOpenDetail={openDetail} onLifecycleAction={handleLifecycleAction} onNavigate={navigate} /> : <DetailPage data={detail} groups={groups} status={detailStatus} error={detailError} days={detailDays} onRetry={() => selectedCompetitorId !== null && void loadDetail(selectedCompetitorId, detailDays)} onRangeChange={changeDetailRange} onBack={() => navigate("competitors")} onNavigate={navigate} />}{notice && <div className={"toast toast-" + notice.type} role="status">{notice.message}</div>}{dialogOpen && <AddDialog url={url} status={addStatus} onUrlChange={setUrl} onSubmit={handleSubmit} onClose={closeDialog} groups={groups} groupId={groupId} onGroupChange={setGroupId} newGroupName={newGroupName} onNewGroupNameChange={setNewGroupName} onCreateGroup={() => void handleCreateGroup()} groupCreateStatus={groupCreateStatus} failures={addFailures} succeededCount={addSucceededCount} progress={addProgress} />}{lifecycleDialog && <ConfirmDialog action={lifecycleDialog.action} competitor={lifecycleDialog.competitor} submitting={lifecycleSubmitting} error={lifecycleError} onClose={closeLifecycleDialog} onConfirm={confirmLifecycleAction} />}</>;
}

export default App;
