import { FormEvent, useEffect, useState } from "react";

import "./App.css";

type AddStatus = "initial" | "submitting" | "success" | "invalid" | "duplicate" | "server-error";
type ListStatus = "loading" | "error" | "ready";
type Notice = { message: string; type: "success" | "error" };

type CollectionErrorBody = { code?: string; message?: string };

const collectionErrorMessages: Record<string, string> = {
  competitor_not_found: "竞品不存在",
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
};

export type Competitor = {
  id: number;
  platform: string;
  offer_id: string;
  url: string;
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

export function getResponseStatus(responseOk: boolean, code?: string): AddStatus {
  if (responseOk) return "success";
  if (code === "invalid_competitor_url") return "invalid";
  if (code === "competitor_already_exists") return "duplicate";
  return "server-error";
}

export function formatPriceDisplay(snapshot: Competitor["latest_snapshot"]): string {
  const min = snapshot?.price_min?.trim() || "";
  const max = snapshot?.price_max?.trim() || "";
  if (!min && !max) return "未采集";
  if (min && max && min === max) return `¥${min}`;
  if (min && max) return `¥${min} ~ ¥${max}`;
  return `¥${min || max}`;
}

export function formatLatestChange(change: Competitor["latest_change"]): string {
  if (change === null) return "暂无变化记录";
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

export function getCollectionErrorMessage(code?: string, message?: unknown): string {
  const backendMessage = typeof message === "string" ? message.trim() : "";
  if (backendMessage && !/[<>]/.test(backendMessage) && !/traceback|stack trace|File "/i.test(backendMessage)) return backendMessage;
  return (code && collectionErrorMessages[code]) || "采集失败，请稍后重试";
}

export function getCollectionRequestErrorMessage(_error: unknown): string {
  return "无法连接服务，请检查后端是否正常运行后重试";
}

function formatDate(value: string | null): string {
  if (!value) return "未采集";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function ProductImage({ competitor }: { competitor: Competitor }) {
  const [failed, setFailed] = useState(false);
  if (!competitor.main_image_url || failed) return <span className="product-image product-image-placeholder">暂无主图</span>;
  return <img className="product-image" src={competitor.main_image_url} alt="" onError={() => setFailed(true)} />;
}

function StatusBadge({ status }: { status: Competitor["status"] }) {
  const labels = { unknown: "未采集", active: "正常", offline: "已下架" };
  return <span className={"status-badge status-" + status}>{labels[status]}</span>;
}

type ListPageProps = { competitors: Competitor[]; status: ListStatus; error: string | null; onRetry: () => void; onAdd: () => void; collectingCompetitorId: number | null; onCollect: (competitorId: number) => void };

export function ListPage({ competitors, status, error, onRetry, onAdd, collectingCompetitorId, onCollect }: ListPageProps) {
  const collectedCount = competitors.filter((item) => item.last_collected_at !== null).length;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">PW</span><div><strong>个人工作台</strong><span>工作提效工具集</span></div></div>
        <nav aria-label="主导航">
          <button className="nav-item nav-disabled" disabled><span className="nav-icon" aria-hidden="true">⌂</span>首页</button>
          <div className="nav-group"><div className="nav-group-title"><span className="nav-icon" aria-hidden="true">⌁</span>竞品监控<span className="nav-chevron" aria-hidden="true">⌃</span></div>
            <button className="nav-item nav-child nav-disabled" disabled><span className="nav-dot" aria-hidden="true" />竞品监控大屏</button>
            <button className="nav-item nav-child nav-active" aria-current="page"><span className="nav-dot" aria-hidden="true" />竞品列表</button>
            <button className="nav-item nav-child nav-disabled" disabled><span className="nav-dot" aria-hidden="true" />竞品分组</button>
            <button className="nav-item nav-child nav-disabled" disabled><span className="nav-dot" aria-hidden="true" />采集记录</button>
          </div>
          <button className="nav-item nav-disabled" disabled><span className="nav-icon" aria-hidden="true">▣</span>自动上架</button><button className="nav-item nav-disabled" disabled><span className="nav-icon" aria-hidden="true">⚙</span>系统设置</button>
        </nav>
        <div className="sidebar-note"><strong>让工作更高效</strong><span>v1.0.0</span></div>
      </aside>
      <main className="main-content">
        <div className="workspace-header">
          <div className="breadcrumb">个人工作台 <span>/</span> 竞品监控 <span>/</span> <strong>竞品列表</strong></div>
          <div className="workspace-tools" aria-label="工作台工具区">
            <div className="workspace-search" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="5.5" /><path d="m16 16 4 4" /></svg><span>搜索商品名称、链接或关键词</span></div>
            <span className="workspace-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></svg></span>
            <span className="workspace-user" aria-hidden="true"><span className="workspace-avatar">W</span><span>工作台</span><svg viewBox="0 0 24 24"><path d="m8 10 4 4 4-4" /></svg></span>
          </div>
        </div>
        <header className="page-header"><div><h1>竞品列表</h1><p className="page-description">查看当前已添加的 1688 竞品，并管理监控对象。</p></div><button className="primary-button" onClick={onAdd}>添加竞品</button></header>
        <section className="filter-card" aria-label="搜索和筛选">
          <div className="filter-field filter-search"><label htmlFor="search">搜索商品名称 / offerId / 店铺</label><input id="search" disabled placeholder="搜索商品名称 / offerId / 店铺" /></div>
          <div className="filter-field"><label htmlFor="product-status">商品状态</label><select id="product-status" disabled><option>全部状态</option></select></div>
          <div className="filter-field"><label htmlFor="collection-status">采集状态</label><select id="collection-status" disabled><option>全部状态</option></select></div>
          <button className="secondary-button" disabled>筛选</button><button className="text-button" disabled>重置</button><span className="filter-hint">搜索与筛选暂未开放</span>
        </section>
        <section className="stats-strip" aria-label="列表统计">
          <div className="stat-total"><strong>共 {status === "ready" ? competitors.length : "—"} 个竞品</strong></div>
          <div className="stat-item"><span>已采集数量</span><strong>{status === "ready" ? collectedCount : "—"}</strong></div>
          <div className="stat-item"><span>未采集数量</span><strong>{status === "ready" ? competitors.length - collectedCount : "—"}</strong></div>
        </section>
        <section className="table-card">
          <div className="table-heading"><div><h2>全部竞品</h2><span>按添加时间倒序展示</span></div><span className="table-count">{status === "ready" ? competitors.length + " 个商品" : status === "loading" ? "加载中" : "—"}</span></div>
          {status === "loading" && <div className="state-panel"><div className="spinner" /><strong>正在加载竞品列表…</strong></div>}
          {status === "error" && <div className="state-panel state-error"><strong>加载失败</strong><span>{error || "暂时无法获取竞品列表。"}</span><button className="secondary-button" onClick={onRetry}>重试</button></div>}
          {status === "ready" && competitors.length === 0 && <div className="state-panel"><div className="empty-icon">+</div><strong>还没有添加竞品</strong><span>添加一个 1688 商品链接，开始建立你的监控列表。</span><button className="primary-button" onClick={onAdd}>添加竞品</button></div>}
          {status === "ready" && competitors.length > 0 && <div className="table-scroll"><table><thead><tr><th>商品信息</th><th>店铺名称</th><th>当前价格</th><th>SKU 数量</th><th>最近变化</th><th>最近采集时间</th><th>商品状态</th><th>操作</th></tr></thead><tbody>
            {competitors.map((competitor) => { const isCollecting = collectingCompetitorId === competitor.id; return <tr key={competitor.id}><td><div className="product-cell"><ProductImage competitor={competitor} /><div><strong>{competitor.title || "未采集"}</strong><span>offerId：{competitor.offer_id}</span><a href={competitor.url} target="_blank" rel="noreferrer">查看 1688 商品 ↗</a></div></div></td><td>{competitor.shop_name || "未采集"}</td><td className={competitor.latest_snapshot?.price_min || competitor.latest_snapshot?.price_max ? "price-cell" : "muted-cell"}>{formatPriceDisplay(competitor.latest_snapshot)}</td><td className={competitor.latest_snapshot === null ? "muted-cell" : "sku-cell"}>{competitor.latest_snapshot === null ? "未采集" : competitor.latest_snapshot.sku_count}</td><td className={competitor.latest_change === null ? "muted-cell" : "change-cell"}>{formatLatestChange(competitor.latest_change)}</td><td className="collection-date-cell">{formatDate(competitor.last_collected_at)}</td><td><StatusBadge status={competitor.status} /></td><td><button type="button" className={"collect-button" + (isCollecting ? " collect-button-loading" : "")} onClick={() => onCollect(competitor.id)} disabled={collectingCompetitorId !== null}>{isCollecting ? "采集中..." : "立即采集"}</button></td></tr>; })}
          </tbody></table></div>}
        </section>
        <div className="pagination-bar"><span>显示全部竞品</span><button disabled>上一页</button><span className="page-number">1</span><button disabled>下一页</button><span>分页暂未开放</span></div>
      </main>
    </div>
  );
}

type AddDialogProps = { url: string; status: AddStatus; onUrlChange: (url: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onClose: () => void };

export function AddDialog({ url, status, onUrlChange, onSubmit, onClose }: AddDialogProps) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
    <div className="dialog-header"><div><p className="eyebrow">竞品监控</p><h2 id="dialog-title">添加竞品</h2></div><button className="close-button" onClick={onClose} aria-label="关闭">×</button></div>
    <p className="dialog-description">添加一个 1688 商品链接，系统会保存监控对象。</p>
    <form onSubmit={onSubmit}><label htmlFor="competitor-url">1688 商品链接</label><input id="competitor-url" type="url" value={url} onChange={(event) => onUrlChange(event.target.value)} placeholder="https://detail.1688.com/offer/123456789.html" required /><p className="hint">仅支持 detail.1688.com/offer/{"{offerId}"}.html</p><div className="dialog-actions"><button type="button" className="secondary-button" onClick={onClose}>取消</button><button type="submit" className="primary-button" disabled={status === "submitting"}>{status === "submitting" ? "正在添加…" : "添加竞品"}</button></div></form>
    <div className={"feedback feedback-" + status} role="status" aria-live="polite">{status === "submitting" && "正在校验并保存…"}{status === "invalid" && "链接无效：请输入指定格式的 1688 商品链接。"}{status === "duplicate" && "该 1688 商品已经添加。"}{status === "server-error" && "服务暂时不可用，请稍后重试。"}</div>
  </section></div>;
}

function App() {
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [listStatus, setListStatus] = useState<ListStatus>("loading");
  const [listError, setListError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [addStatus, setAddStatus] = useState<AddStatus>("initial");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [collectingCompetitorId, setCollectingCompetitorId] = useState<number | null>(null);

  async function loadCompetitors() {
    setListStatus("loading"); setListError(null);
    try { const response = await fetch("/api/competitors"); if (!response.ok) throw new Error("request failed"); setCompetitors(await response.json() as Competitor[]); setListStatus("ready"); }
    catch { setListError("暂时无法获取竞品列表，请检查服务是否正常运行。"); setListStatus("error"); }
  }
  useEffect(() => { void loadCompetitors(); }, []);
  function openDialog() { setNotice(null); setAddStatus("initial"); setDialogOpen(true); }
  function closeDialog() { if (addStatus !== "submitting") { setDialogOpen(false); setUrl(""); setAddStatus("initial"); } }
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setAddStatus("submitting");
    try {
      const response = await fetch("/api/competitors", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, group_id: null }) });
      if (response.ok) { setDialogOpen(false); setUrl(""); setAddStatus("initial"); setNotice({ message: "竞品已添加，列表已更新。", type: "success" }); await loadCompetitors(); return; }
      const body = await response.json() as { code?: string }; setAddStatus(getResponseStatus(false, body.code));
    } catch { setAddStatus("server-error"); }
  }
  async function handleCollect(competitorId: number) {
    if (collectingCompetitorId !== null) return;
    setCollectingCompetitorId(competitorId);
    setNotice(null);
    try {
      const response = await fetch(`/api/competitors/${competitorId}/collect`, { method: "POST" });
      if (!response.ok) {
        let body: CollectionErrorBody = {};
        try { body = await response.json() as CollectionErrorBody; } catch { /* use the stable fallback below */ }
        throw new Error(getCollectionErrorMessage(body.code, body.message));
      }
      await loadCompetitors();
      setNotice({ message: "采集成功，商品数据已更新。", type: "success" });
    } catch (error) {
      setNotice({ message: getCollectionRequestErrorMessage(error), type: "error" });
    } finally {
      setCollectingCompetitorId(null);
    }
  }
  return <><ListPage competitors={competitors} status={listStatus} error={listError} onRetry={() => void loadCompetitors()} onAdd={openDialog} collectingCompetitorId={collectingCompetitorId} onCollect={(competitorId) => void handleCollect(competitorId)} />{notice && <div className={"toast toast-" + notice.type} role="status">{notice.message}</div>}{dialogOpen && <AddDialog url={url} status={addStatus} onUrlChange={setUrl} onSubmit={handleSubmit} onClose={closeDialog} />}</>;
}

export default App;
