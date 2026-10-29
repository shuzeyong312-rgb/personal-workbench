import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { BatchState, Page } from "./App";
import type { LibraryProduct } from "./ProductLibrary";
import "./WorkspaceTools.css";

type Notification = { id: string; title: string; body: string; tone: "success" | "warning" | "error"; time: string; read: boolean };
type Stored = { items: Notification[]; seen: string[] };
const storageKey = "workspace-task-notifications-v1";
function readStored(): Stored {
  try { const data = JSON.parse(localStorage.getItem(storageKey) || "null"); if (Array.isArray(data?.items) && Array.isArray(data?.seen)) return { items: data.items.slice(0, 100), seen: data.seen.slice(0, 500) }; } catch { /* storage may be unavailable */ }
  return { items: [], seen: [] };
}
export function notificationForBatch(batch: BatchState): Notification | null {
  if (!batch.task_id || batch.lifecycle_status !== "terminal" || batch.runner_active || !batch.batch_outcome_code || !batch.work_kind) return null;
  const outcome = batch.batch_outcome_code;
  if (!["success", "partial_success", "partial_failure", "user_ended", "collect_failed", "infrastructure_error", "interrupted", "verification_required"].includes(outcome)) return null;
  const successes = batch.work_kind === "add_links" ? batch.input_progress?.added ?? 0 : batch.succeeded;
  const tone = outcome === "success" ? "success" : ["partial_success", "partial_failure", "user_ended"].includes(outcome) && successes > 0 ? "warning" : "error";
  if (batch.work_kind === "add_links") {
    const p = batch.input_progress;
    if (!p) return null;
    return { id: batch.task_id, title: tone === "success" ? "添加监控商品已完成" : tone === "warning" ? "添加监控商品部分完成" : "添加监控商品需处理", body: `新增 ${p.added} · 业务拒绝 ${p.business_rejected} · 技术失败 ${p.technical_failed} · 未执行 ${p.not_executed}`, tone, time: new Date().toISOString(), read: false };
  }
  return { id: batch.task_id, title: tone === "success" ? "竞品采集已完成" : tone === "warning" ? "竞品采集部分完成" : "竞品采集需处理", body: `已完成 ${batch.completed} / ${batch.total} · 成功 ${batch.succeeded} · 失败 ${batch.failed} · 剩余 ${batch.remaining}`, tone, time: new Date().toISOString(), read: false };
}
type ToolsContextValue = { stored: Stored; update: (fn: (s: Stored) => Stored) => void; productQuery: { text: string; version: number }; setProductQuery: (q: string) => void };
const ToolsContext = createContext<ToolsContextValue | null>(null);
export function WorkspaceToolsProvider({ batch, children }: { batch: BatchState; children: ReactNode }) {
  const [stored, setStored] = useState<Stored>(readStored);
  const [productQuery, setProductQueryState] = useState({ text: "", version: 0 });
  const setProductQuery = (text: string) => setProductQueryState(current => ({ text, version: current.version + 1 }));
  const update = (fn: (s: Stored) => Stored) => setStored(current => { const next = fn(current); if (next !== current) { try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* keep session state */ } } return next; });
  useEffect(() => { const item = notificationForBatch(batch); if (item) update(current => current.seen.includes(item.id) ? current : { items: [item, ...current.items].slice(0, 100), seen: [item.id, ...current.seen].slice(0, 500) }); }, [batch]);
  return <ToolsContext.Provider value={{ stored, update, productQuery, setProductQuery }}>{children}</ToolsContext.Provider>;
}
export function useProductSearchQuery() { return useContext(ToolsContext)?.productQuery ?? { text: "", version: 0 }; }
const entries: { label: string; page: Page; kind: "页面" | "功能"; tags: string; section?: string; planned?: boolean }[] = [
  { label: "工作台首页", page: "home", kind: "页面", tags: "首页 工作空间" },
  { label: "竞品监控大屏", page: "dashboard", kind: "页面", tags: "竞品 总览 采集" },
  { label: "我方商品", page: "own-products", kind: "页面", tags: "自家 商品" },
  { label: "竞品列表", page: "competitors", kind: "页面", tags: "竞争对手 商品" },
  { label: "竞品分组", page: "groups", kind: "页面", tags: "竞争分析 商品组" },
  { label: "采集记录", page: "collection-tasks", kind: "页面", tags: "任务 批次 日志" },
  { label: "产品库", page: "product-library", kind: "页面", tags: "商品资料 型号" },
  { label: "客户触达", page: "customer-reach", kind: "页面", tags: "客户 推广" },
  { label: "常用工具箱", page: "toolbox", kind: "页面", tags: "图片压缩 图片尺寸 网站工具" },
  { label: "系统设置", page: "settings", kind: "页面", tags: "配置" },
  { label: "店铺识别", page: "settings", kind: "功能", tags: "店铺名称", section: "settings-basic" },
  { label: "采集策略", page: "settings", kind: "功能", tags: "自动计划 定时", section: "settings-monitoring" },
  { label: "工作浏览器", page: "settings", kind: "功能", tags: "1688 Chrome 登录 插件", section: "settings-browser" },
  ...([ ["AI智能助手", "ai-assistant"], ["全网比价", "price-compare"], ["自动询价", "auto-inquiry"], ["自动上架", "auto-listing"] ] as const).map(([label, page]) => ({ label, page, kind: "页面" as const, tags: "规划中", planned: true }))
];

export function searchEntries(query: string) {
  return entries.filter(item => query.trim() ? `${item.label} ${item.tags}`.toLowerCase().includes(query.trim().toLowerCase()) : ["dashboard", "product-library", "groups", "collection-tasks", "settings"].includes(item.page) && !item.section);
}

function ToolIcon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v11h14V9M9 20v-6h6v6"/></>,
    dashboard: <><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="10" width="8" height="11" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/></>,
    product: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></>,
    groups: <><rect x="3" y="5" width="8" height="6" rx="1.5"/><rect x="13" y="5" width="8" height="6" rx="1.5"/><rect x="8" y="14" width="8" height="6" rx="1.5"/></>,
    tasks: <><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4m0-12.8L17 7M7 17l-1.4 1.4"/></>,
    browser: <><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-2 7-2 9h16c0-2-2-2-2-9M10 20h4"/></>,
    success: <><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></>,
    warning: <><path d="M12 3 2.7 19h18.6L12 3Z"/><path d="M12 9v4m0 3h.01"/></>,
    error: <><circle cx="12" cy="12" r="9"/><path d="M12 8v5m0 3h.01"/></>,
    arrow: <><path d="M5 12h14m-4-4 4 4-4 4"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name] ?? paths.product}</svg>;
}
function entryIcon(page: Page, section?: string) {
  if (section === "settings-browser") return "browser";
  if (page === "settings") return "settings";
  if (page === "home") return "home";
  if (page === "dashboard") return "dashboard";
  if (page === "groups") return "groups";
  if (page === "collection-tasks") return "tasks";
  return "product";
}
function notificationTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function WorkspaceTools({ onNavigate }: { onNavigate: (page: Page) => void | boolean }) {
  const context = useContext(ToolsContext);
  const [search, setSearch] = useState(false); const [panel, setPanel] = useState(false); const [unreadOnly, setUnreadOnly] = useState(false);
  const [q, setQ] = useState(""); const [products, setProducts] = useState<LibraryProduct[]>([]); const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const trigger = useRef<HTMLButtonElement>(null); const input = useRef<HTMLInputElement>(null); const notificationAnchor = useRef<HTMLDivElement>(null);
  function closeSearch() { setSearch(false); trigger.current?.focus(); }
  function openSearch() { if (document.querySelector('dialog[open], [role="dialog"]')) return; setPanel(false); setQ(""); setSearch(true); }
  useEffect(() => { const handler = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (search) closeSearch(); else openSearch(); } else if (e.key === "Escape") { if (search) closeSearch(); else setPanel(false); } }; document.addEventListener("keydown", handler); return () => document.removeEventListener("keydown", handler); }, [search]);
  useEffect(() => { if (search) input.current?.focus(); }, [search]);
  useEffect(() => { if (!panel) return; const dismiss = (event: MouseEvent) => { if (!notificationAnchor.current?.contains(event.target as Node)) setPanel(false); }; document.addEventListener("mousedown", dismiss); return () => document.removeEventListener("mousedown", dismiss); }, [panel]);
  useEffect(() => {
    const query = q.trim(); setProducts([]);
    if (!search || !query) { setStatus("idle"); return; }
    const controller = new AbortController(); setStatus("loading");
    const timer = window.setTimeout(() => { const params = new URLSearchParams({ q: query, page: "1", page_size: "8" });
      void fetch(`/api/product-library/products?${params}`, { signal: controller.signal }).then(response => { if (!response.ok) throw new Error(); return response.json(); }).then(data => { if (!controller.signal.aborted) { setProducts(data.items); setStatus("ready"); } }).catch(() => { if (!controller.signal.aborted) setStatus("error"); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [q, search]);
  if (!context) return null;
  const { stored, update } = context; const unread = stored.items.filter(item => !item.read).length;
  const filtered = searchEntries(q);
  function go(page: Page, section?: string, product?: string) { if (onNavigate(page) === false) return; if (product !== undefined) context!.setProductQuery(product); setSearch(false); setPanel(false); if (section) window.setTimeout(() => document.getElementById(section)?.scrollIntoView({ block: "start" }), 100); }
  const visibleNotifications = stored.items.filter(item => !unreadOnly || !item.read);
  return <div className="workspace-tools">
    <button ref={trigger} type="button" className="global-search-trigger" aria-label="搜索页面、功能或商品" onClick={openSearch}><ToolIcon name="search"/><span>搜索页面、功能或商品</span><kbd>Ctrl K</kbd></button>
    <div ref={notificationAnchor} className="notification-anchor">
      <button type="button" className="notification-trigger" aria-label={`任务通知，${unread} 条未读`} aria-expanded={panel} onClick={() => setPanel(!panel)}><ToolIcon name="bell"/>{unread > 0 && <b>{unread > 99 ? "99+" : unread}</b>}</button>
      {panel && <section className="notification-panel" aria-label="任务通知中心">
        <header className="notification-header"><div className="notification-heading-icon"><ToolIcon name="bell"/></div><div className="notification-heading"><strong>任务通知</strong><span>任务完成后会在这里提醒你</span></div><span className="notification-count">{unread} 条未读</span><button type="button" className="notification-close" onClick={() => setPanel(false)} aria-label="关闭通知"><ToolIcon name="close"/></button></header>
        <div className="notification-actions"><div className="notification-tabs"><button type="button" aria-pressed={!unreadOnly} onClick={() => setUnreadOnly(false)}>全部</button><button type="button" aria-pressed={unreadOnly} onClick={() => setUnreadOnly(true)}>未读{unread > 0 && <span>{unread}</span>}</button></div><button type="button" disabled={!unread} onClick={() => update(s => ({ ...s, items: s.items.map(item => ({ ...item, read: true })) }))}>全部已读</button><button type="button" onClick={() => update(s => ({ ...s, items: s.items.filter(item => !item.read) }))}>清理已读</button></div>
        <div className="notification-list">{visibleNotifications.map(item => <div key={item.id} className={`notification-item ${item.read ? "" : "unread"}`}>
          <button className="notification-content" type="button" onClick={() => { if (onNavigate("collection-tasks") === false) return; update(s => ({ ...s, items: s.items.map(n => n.id === item.id ? { ...n, read: true } : n) })); setPanel(false); }}><span className={`notification-status-icon ${item.tone}`}><ToolIcon name={item.tone}/></span><span className="notification-copy"><span className="notification-title"><strong>{item.title}</strong>{!item.read && <span className="notification-unread-dot" aria-label="未读"/>}</span><span className="notification-summary">{item.body}</span><span className="notification-meta"><time dateTime={item.time}>{notificationTime(item.time)}</time></span><span className="notification-view">查看任务 <ToolIcon name="arrow"/></span></span></button>{!item.read && <button type="button" className="notification-read" onClick={() => update(s => ({ ...s, items: s.items.map(n => n.id === item.id ? { ...n, read: true } : n) }))}>标记已读</button>}
        </div>)}{!visibleNotifications.length && <div className="notification-empty"><span><ToolIcon name="bell"/></span><strong>{unreadOnly ? "没有未读通知" : "暂无任务通知"}</strong><p>{unreadOnly ? "新的任务结果会出现在这里" : "采集或添加任务结束后，会在这里显示结果"}</p></div>}</div>
      </section>}
    </div>
    {search && <div className="global-search-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) closeSearch(); }}><section className="global-search-dialog" role="dialog" aria-modal="true" aria-label="全局搜索" onKeyDown={event => { if (event.key !== "Tab") return; const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('input, button:not(:disabled)')); const first = controls[0], last = controls.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } }}>
      <div className="global-search-input"><span className="search-input-icon"><ToolIcon name="search"/></span><input ref={input} aria-label="搜索页面、功能或商品" placeholder="搜索页面、功能或商品" value={q} onChange={e => setQ(e.target.value)} /><button type="button" onClick={closeSearch} aria-label="关闭搜索">Esc</button></div>
      <div className="global-search-results">{(["页面", "功能"] as const).map(kind => { const rows = filtered.filter(item => item.kind === kind); return rows.length > 0 && <div className="search-group" key={kind}><h2>{q.trim() ? kind : "常用入口"}</h2>{rows.map(item => <button className="search-result" type="button" key={item.label} aria-label={`${item.label} ${item.planned ? "规划中" : item.kind}`} onClick={() => go(item.page, item.section)}><span className={`search-result-icon ${item.kind === "功能" ? "feature" : item.page === "product-library" ? "library" : ""}`}><ToolIcon name={entryIcon(item.page, item.section)}/></span><span className="search-result-copy"><strong>{item.label}</strong><small>{item.planned ? "此功能正在规划" : item.kind === "功能" ? "系统设置 · 竞品监控" : item.tags.split(" ").slice(0, 2).join(" / ")}</small></span><span className="search-result-kind">{item.planned ? "规划中" : item.kind}</span><span className="search-result-arrow"><ToolIcon name="arrow"/></span></button>)}</div>; })}
      {q.trim() && <div className="search-group"><h2>商品资料</h2>{status === "loading" && <p className="search-state" role="status">正在搜索商品…</p>}{status === "error" && <p className="search-state error" role="alert">商品搜索失败，请检查服务后重试。</p>}{status === "ready" && products.map(product => <button className="search-result" type="button" key={product.id} onClick={() => go("product-library", undefined, product.model || product.name)}><span className="search-result-icon library"><ToolIcon name="product"/></span><span className="search-result-copy"><strong>{product.name}</strong><small>{product.model || "未提供型号"} · {product.manufacturer_name}</small></span><span className="search-result-kind">商品</span><span className="search-result-arrow"><ToolIcon name="arrow"/></span></button>)}{status === "ready" && !products.length && <p className="search-state">没有匹配的商品</p>}</div>}{!filtered.length && status !== "loading" && !products.length && <p className="search-state">没有找到匹配的页面或功能</p>}</div>
    </section></div>}
  </div>;
}
