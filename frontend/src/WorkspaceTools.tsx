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
  { label: "系统设置", page: "settings", kind: "页面", tags: "配置" },
  { label: "店铺识别", page: "settings", kind: "功能", tags: "店铺名称", section: "settings-basic" },
  { label: "采集策略", page: "settings", kind: "功能", tags: "自动计划 定时", section: "settings-monitoring" },
  { label: "工作浏览器", page: "settings", kind: "功能", tags: "1688 Chrome 登录 插件", section: "settings-browser" },
  ...([ ["AI智能助手", "ai-assistant"], ["全网比价", "price-compare"], ["自动询价", "auto-inquiry"], ["自动上架", "auto-listing"] ] as const).map(([label, page]) => ({ label, page, kind: "页面" as const, tags: "规划中", planned: true }))
];
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
  const filtered = entries.filter(item => !q.trim() || `${item.label} ${item.tags}`.toLowerCase().includes(q.trim().toLowerCase()));
  function go(page: Page, section?: string, product?: string) { if (onNavigate(page) === false) return; if (product !== undefined) context!.setProductQuery(product); setSearch(false); setPanel(false); if (section) window.setTimeout(() => document.getElementById(section)?.scrollIntoView({ block: "start" }), 100); }
  return <div className="workspace-tools">
    <button ref={trigger} type="button" className="global-search-trigger" aria-label="搜索页面、功能或商品" onClick={openSearch}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg><span>搜索页面、功能或商品</span><kbd>Ctrl K</kbd></button>
    <div ref={notificationAnchor} className="notification-anchor"><button type="button" className="notification-trigger" aria-label={`任务通知，${unread} 条未读`} aria-expanded={panel} onClick={() => setPanel(!panel)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-2 7-2 9h16c0-2-2-2-2-9M10 20h4"/></svg>{unread > 0 && <b>{unread > 99 ? "99+" : unread}</b>}</button>
    {panel && <section className="notification-panel" aria-label="任务通知中心"><header><div><strong>任务通知</strong><span>{unread} 条未读</span></div><button type="button" onClick={() => setPanel(false)} aria-label="关闭通知">×</button></header><div className="notification-actions"><div><button type="button" aria-pressed={!unreadOnly} onClick={() => setUnreadOnly(false)}>全部</button><button type="button" aria-pressed={unreadOnly} onClick={() => setUnreadOnly(true)}>未读</button></div><button type="button" disabled={!unread} onClick={() => update(s => ({ ...s, items: s.items.map(item => ({ ...item, read: true })) }))}>全部已读</button><button type="button" onClick={() => update(s => ({ ...s, items: s.items.filter(item => !item.read) }))}>清理已读</button></div><div className="notification-list">{stored.items.filter(item => !unreadOnly || !item.read).map(item => <div key={item.id} className={`notification-item ${item.read ? "" : "unread"}`}><button className="notification-content" type="button" onClick={() => { if (onNavigate("collection-tasks") === false) return; update(s => ({ ...s, items: s.items.map(n => n.id === item.id ? { ...n, read: true } : n) })); setPanel(false); }}><strong><i className={`notification-dot ${item.tone}`} />{item.title}</strong><span>{item.body}</span><small>{new Date(item.time).toLocaleString()} · 查看采集记录</small></button>{!item.read && <button type="button" className="notification-read" onClick={() => update(s => ({ ...s, items: s.items.map(n => n.id === item.id ? { ...n, read: true } : n) }))}>标记已读</button>}</div>)}{!stored.items.filter(item => !unreadOnly || !item.read).length && <p className="notification-empty">{unreadOnly ? "没有未读通知" : "暂无任务通知"}</p>}</div></section>}</div>
    {search && <div className="global-search-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) closeSearch(); }}><section className="global-search-dialog" role="dialog" aria-modal="true" aria-label="全局搜索" onKeyDown={event => { if (event.key !== "Tab") return; const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('input, button:not(:disabled)')); const first = controls[0], last = controls.at(-1); if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } }}><div className="global-search-input"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg><input ref={input} aria-label="搜索页面、功能或商品" placeholder="搜索页面、功能或商品" value={q} onChange={e => setQ(e.target.value)} /><button type="button" onClick={closeSearch} aria-label="关闭搜索">Esc</button></div><div className="global-search-results">{(["页面", "功能"] as const).map(kind => { const rows = filtered.filter(item => item.kind === kind); return rows.length > 0 && <div key={kind}><h2>{kind}</h2>{rows.map(item => <button type="button" key={item.label} onClick={() => go(item.page, item.section)}><span>{item.label}</span><small>{item.planned ? "规划中" : item.kind}</small></button>)}</div>; })}{q.trim() && <div><h2>商品资料</h2>{status === "loading" && <p role="status">正在搜索商品…</p>}{status === "error" && <p role="alert">商品搜索失败，请检查服务后重试。</p>}{status === "ready" && products.map(product => <button type="button" key={product.id} onClick={() => go("product-library", undefined, product.model || product.name)}><span>{product.name}{product.model && ` · ${product.model}`}</span><small>商品</small></button>)}{status === "ready" && !products.length && <p>没有匹配的商品</p>}</div>}{!filtered.length && status !== "loading" && !products.length && <p>没有找到匹配的页面或功能</p>}</div></section></div>}
  </div>;
}
