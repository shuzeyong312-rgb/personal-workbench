import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import "./ProductLibrary.css";
import { ProductQuotation } from "./ProductQuotation";
import { PaginationBar } from "./PaginationBar";

export type ProductFields = {
  manufacturer_name: string; model: string | null; name: string; parameters: string | null;
  selling_points: string | null; wholesale_price: string | null; price_note: string | null;
};
export type LibraryProduct = ProductFields & { id: number; version: number; created_at: string; updated_at: string };
type Action = "insert" | "update" | "skip";
type Candidate = { id: number; name: string; model: string | null };
export type PreviewRow = Partial<ProductFields> & {
  row_number: number; category: "new" | "existing" | "conflict" | "suspected" | "invalid";
  errors: { field: string; code: string; message: string }[];
  candidate: Candidate[]; file_candidates: { row_number: number; name: string; model: string | null }[];
  diff: Record<string, { old: string | null; incoming: string | null; effective: string | null; changed: boolean }>;
  allowed_actions: Action[]; default_action: Action;
};
type Preview = { import_id: string; status: "ready"; expires_at: string; manufacturer_name: string; counts: Record<string, number>; rows: PreviewRow[] };
type Result = { import_id: string; status: "committed"; inserted: number; updated: number; skipped: number; invalid: number; rows: { row_number: number; outcome: string; product_id: number | null; reason_code: string }[] };
type Receipt = Preview | Result;
type ApiError = Error & { code?: string; candidates?: Candidate[]; errors?: { field: string; message: string }[]; uncertain?: boolean };
const base = "/api/product-library";
export const emptyProduct: ProductFields = { manufacturer_name: "", model: null, name: "", parameters: null, selling_points: null, wholesale_price: null, price_note: null };
const labels: Record<keyof ProductFields, string> = { manufacturer_name: "厂家名称", model: "产品型号", name: "产品名称", parameters: "产品参数", selling_points: "产品卖点", wholesale_price: "批发价", price_note: "价格备注" };
const categories = { new: "待新增", existing: "已有产品", conflict: "名称冲突", suspected: "疑似重复", invalid: "错误行" };
const actions = { insert: "新增", update: "确认更新", skip: "跳过" };
const display = (value: string | null | undefined) => value ?? "未提供";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(base + path, options); }
  catch { throw Object.assign(new Error("网络异常，结果待确认"), { uncertain: true }); }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw Object.assign(new Error(body.message ?? "请求失败，请重试"), { code: body.code, candidates: body.candidates, errors: body.errors, items: body.items, uncertain: response.status >= 500 && !["product_save_failed", "import_save_failed", "database_busy"].includes(body.code) });
  }
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; }
  catch { throw Object.assign(new Error("响应无法读取，结果待确认"), { uncertain: true }); }
}
export const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function TemplateDownload() {
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  async function download() {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`${base}/template`);
      if (!response.ok) throw new Error("模板下载失败，请重试");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "产品库导入模板.xlsx"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { setError("模板下载失败，请重试"); }
    finally { setBusy(false); }
  }
  return <span><button type="button" className="secondary-button" disabled={busy} onClick={() => void download()}>{busy ? "下载中…" : "下载 Excel 模板"}</button>{error && <span role="alert">{error}</span>}</span>;
}

export function plannedCounts(rows: PreviewRow[], decisions: Record<number, Action>) {
  const counts = { insert: 0, update: 0, skip: 0 };
  for (const row of rows) counts[decisions[row.row_number] ?? row.default_action]++;
  return counts;
}

export function LibraryDialog({ title, busy = false, onClose, children, returnFocus, side }: { title: string; busy?: boolean; onClose: () => void; children: ReactNode; returnFocus?: HTMLElement | null; side?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = returnFocus ?? document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => { ref.current?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className={`dialog library-dialog${side ? " library-side-panel" : ""}`} aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-header"><h2>{title}</h2><button type="button" className="close-button" aria-label="关闭" disabled={busy} onClick={onClose}>×</button></div>{children}
  </dialog>;
}

export function ProductEditor({ product, onClose, onSaved, returnFocus }: { product: LibraryProduct | null; onClose: () => void; onSaved: () => void; returnFocus?: HTMLElement | null }) {
  const [fields, setFields] = useState<ProductFields>(product ?? emptyProduct);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [allow, setAllow] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const payload = Object.fromEntries(Object.keys(emptyProduct).map(key => [key, fields[key as keyof ProductFields]]));
      await api(product ? `/products/${product.id}` : "/products", json(product ? "PUT" : "POST", { ...payload, ...(product ? { version: product.version } : {}), allow_suspected_duplicate: allow }));
      onSaved();
    } catch (caught) {
      const failure = caught as ApiError; setError(failure);
      if (failure.uncertain) setUncertain(true);
    } finally { setBusy(false); }
  }
  return <LibraryDialog title={product ? "编辑产品" : "手动新增产品"} busy={busy} onClose={onClose} returnFocus={returnFocus}>
    <form onSubmit={save} className="library-form">
      {(Object.keys(labels) as (keyof ProductFields)[]).map(key => <label key={key}>{labels[key]}{(key === "manufacturer_name" || key === "name") && " *"}
        {key === "parameters" || key === "selling_points" || key === "price_note" ? <textarea value={fields[key] ?? ""} maxLength={key === "price_note" ? 2000 : 10000} onChange={event => { setFields({ ...fields, [key]: event.target.value || null }); setAllow(false); setError(null); }} /> :
          <input value={fields[key] ?? ""} required={key === "manufacturer_name" || key === "name"} maxLength={key === "wholesale_price" ? undefined : 200} inputMode={key === "wholesale_price" ? "decimal" : undefined} onChange={event => { setFields({ ...fields, [key]: event.target.value || (key === "manufacturer_name" || key === "name" ? "" : null) }); setAllow(false); setError(null); }} />}
      </label>)}
      <p>批发价单位为人民币元，最多两位小数。空字段保存为未提供。</p>
      {error && <div role="alert" className="feedback feedback-server-error">{error.message}{error.errors?.map((item, index) => <p key={index}>{labels[item.field as keyof ProductFields] ?? item.field}：{item.message}</p>)}{error.candidates?.map(candidate => <p key={candidate.id}>候选 #{candidate.id} · {display(candidate.model)} · {candidate.name}</p>)}</div>}
      {error?.code === "product_exists" && <p>请关闭表单，在列表中查看或编辑现有型号。</p>}
      {error?.code === "suspected_duplicate" && <label className="library-check"><input type="checkbox" checked={allow} onChange={event => setAllow(event.target.checked)} />已核对同名候选，仍保存为独立产品</label>}
      {uncertain && <p role="alert">保存结果待确认。请关闭后刷新列表核对，避免重复创建或覆盖；本表单已停止重发。</p>}
      <div className="dialog-actions"><button type="button" className="secondary-button" disabled={busy} onClick={onClose}>取消</button><button className="primary-button" disabled={busy || uncertain || (error?.code === "suspected_duplicate" && !allow)}>{busy ? "保存中…" : "保存"}</button></div>
    </form>
  </LibraryDialog>;
}

function ImportDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [manufacturer, setManufacturer] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [decisions, setDecisions] = useState<Record<number, Action>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [stale, setStale] = useState(false);
  const [retryDecisions, setRetryDecisions] = useState<{ row_number: number; action: Action }[] | null>(null);
  const [page, setPage] = useState(1);
  const preview = receipt?.status === "ready" ? receipt : null;
  const plan = preview ? plannedCounts(preview.rows, decisions) : null;
  function close() {
    if (uncertain) { setError("结果待确认，请先查询原导入结果后关闭。"); return; }
    if (preview && !window.confirm("当前预览尚未保存，关闭将放弃选择。")) return;
    onClose();
  }
  function reset() { setReceipt(null); setDecisions({}); setRetryDecisions(null); setStale(false); setError(null); setPage(1); }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    if (!/\.xlsx$/i.test(file.name)) { setError("仅支持 .xlsx 文件"); return; }
    if (file.size > 5 * 1024 * 1024) { setError("文件不能超过 5 MiB"); return; }
    setBusy(true); setError(null);
    try {
      const next = await api<Preview>(`/imports/preview?manufacturer_name=${encodeURIComponent(manufacturer)}`, { method: "POST", headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-Filename": encodeURIComponent(file.name) }, body: file });
      setReceipt(next); setDecisions({}); setPage(1);
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function lookup() {
    if (!receipt) return; setBusy(true); setError(null);
    try {
      const next = await api<Receipt>(`/imports/${receipt.import_id}`); setReceipt(next); setUncertain(false);
      if (next.status === "committed") onSaved();
      else setError("后端确认尚未提交，可按原决策重试。");
    } catch (caught) {
      const failure = caught as ApiError; setError(failure.message);
      if (failure.code === "preview_expired" || failure.code === "preview_stale") { setUncertain(false); setStale(true); }
    } finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview) return; setBusy(true); setError(null);
    const submitted = retryDecisions ?? preview.rows.map(row => ({ row_number: row.row_number, action: decisions[row.row_number] ?? row.default_action }));
    try {
      const next = await api<Result>(`/imports/${preview.import_id}/confirm`, json("POST", { decisions: submitted }));
      setReceipt(next); setPage(1); onSaved();
    } catch (caught) {
      const failure = caught as ApiError;
      setError(failure.uncertain ? "结果待确认，请查询原导入结果。" : failure.message);
      setUncertain(!!failure.uncertain);
      if (failure.uncertain) setRetryDecisions(submitted);
      if (failure.code === "preview_stale" || failure.code === "preview_expired") setStale(true);
    } finally { setBusy(false); }
  }
  function choose(row: PreviewRow, action: Action) {
    if ((action === "update" || (action === "insert" && row.category === "suspected")) && !window.confirm(action === "update" ? `确认按第 ${row.row_number} 行的实际保存值覆盖此型号？请核对下方字段差异。` : `确认将第 ${row.row_number} 行新增为独立产品？不会合并候选。`)) return;
    setDecisions(current => ({ ...current, [row.row_number]: action }));
  }
  const orderedRows = receipt?.status === "ready" ? prioritizedRows(receipt.rows) : receipt?.rows ?? [];
  const rows = orderedRows.slice((page - 1) * 20, page * 20);
  const expired = !!preview && Date.parse(preview.expires_at) <= Date.now();
  const [, tick] = useState(0);
  useEffect(() => { if (!preview) return; const timer = setInterval(() => tick(value => value + 1), 1000); return () => clearInterval(timer); }, [preview]);
  return <LibraryDialog title={`批量导入 · 步骤 ${receipt?.status === "committed" ? 3 : preview ? 2 : 1}/3`} busy={busy} onClose={close}>
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    {!receipt && <form className="library-form" onSubmit={upload}>
      <p>仅 .xlsx，最多 5 MiB、1000 行。使用固定六列表头；文本列须为文本，禁止公式。确认前不写入产品。</p>
      <TemplateDownload />
      <label>厂家名称 *<input required maxLength={200} value={manufacturer} onChange={event => setManufacturer(event.target.value)} /></label>
      <label>Excel 文件 *<input required type="file" accept=".xlsx" onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
      <div className="dialog-actions"><button className="primary-button" disabled={busy}>{busy ? "校验中…" : "上传并预览"}</button></div>
    </form>}
    {preview && <>
      <p>厂家：<strong>{preview.manufacturer_name}</strong> · 有效至 {new Date(preview.expires_at).toLocaleString()}</p>
      <p>{Object.entries(categories).map(([key, label]) => `${label} ${preview.counts[key] ?? 0}`).join(" · ")} · 忽略空行 {preview.counts.ignored_blank_rows ?? 0}</p>
      <p aria-live="polite">计划新增 {plan!.insert} · 更新 {plan!.update} · 错误 {preview.counts.invalid} · 合法跳过 {plan!.skip - preview.counts.invalid}</p>
      {uncertain && <p role="status">结果待确认：导入编号 {preview.import_id}。先查询回执，不能重新上传或更改决策。</p>}
      <div className="library-preview">{(rows as PreviewRow[]).map(row => <article className="library-preview-row" key={row.row_number}>
        <h3>第 {row.row_number} 行 · {categories[row.category]} · {display(row.model)} · {display(row.name)}</h3>
        {row.errors.map((item, index) => <p role="alert" key={index}>{labels[item.field as keyof ProductFields] ?? item.field}：{item.message}</p>)}
        {row.candidate.map(candidate => <p key={candidate.id}>已有候选 #{candidate.id} · {display(candidate.model)} · {candidate.name}</p>)}
        {row.file_candidates.map(candidate => <p key={candidate.row_number}>文件内候选：第 {candidate.row_number} 行 · {display(candidate.model)} · {candidate.name}</p>)}
        <details open={row.category === "invalid" || row.category === "conflict" || row.category === "suspected"}><summary>查看完整字段差异</summary><div className="table-scroll"><table className="library-diff"><thead><tr><th>字段</th><th>旧值</th><th>上传值</th><th>实际保存值</th></tr></thead><tbody>{(Object.keys(labels) as (keyof ProductFields)[]).filter(key => key !== "manufacturer_name").map(key => {
          const diff = row.diff[key] ?? { old: null, incoming: row[key] ?? null, effective: row[key] ?? null, changed: false };
          return <tr key={key}><th>{labels[key]}</th><td>{display(diff.old)}</td><td>{display(diff.incoming)}</td><td>{display(diff.effective)}{diff.incoming == null && diff.old != null ? "（保留原值）" : diff.changed ? "（变更）" : ""}</td></tr>;
        })}</tbody></table></div></details>
        <label>第 {row.row_number} 行操作 <select disabled={busy || uncertain || retryDecisions !== null || stale || row.category === "invalid"} value={decisions[row.row_number] ?? row.default_action} onChange={event => choose(row, event.target.value as Action)}>{row.allowed_actions.map(action => <option key={action} value={action}>{action === "insert" && row.category === "suspected" ? "仍新增为独立产品" : actions[action]}</option>)}</select></label>
      </article>)}</div>
      <div className="dialog-actions library-sticky-actions"><span>整批：新增 {plan!.insert} · 更新 {plan!.update} · 跳过 {plan!.skip - preview.counts.invalid} · 错误 {preview.counts.invalid} · {expired ? "已过期" : `有效至 ${new Date(preview.expires_at).toLocaleTimeString()}`}</span><button className="secondary-button" disabled={busy || uncertain || (retryDecisions !== null && !stale)} onClick={reset}>返回修改文件或厂家（放弃选择）</button>{uncertain ? <button className="primary-button" disabled={busy} onClick={() => void lookup()}>查询原导入结果</button> : <button className="primary-button" disabled={busy || stale || expired || !plan || plan.insert + plan.update === 0} onClick={() => void confirm()}>{busy ? "确认中…" : retryDecisions ? "按原决策重试" : "确认导入"}</button>}</div>
    </>}
    {receipt?.status === "committed" && <><p role="status">导入完成：新增 {receipt.inserted} · 更新 {receipt.updated} · 跳过 {receipt.skipped} · 错误 {receipt.invalid}</p><div className="library-preview">{(rows as Result["rows"]).map(row => <p key={row.row_number}>第 {row.row_number} 行 · {({ inserted: "已新增", updated: "已更新", skipped: "已按选择跳过", invalid: "校验错误，未写入" } as Record<string, string>)[row.outcome]} · {row.product_id == null ? "未写入" : `产品 #${row.product_id}`}</p>)}</div><div className="dialog-actions"><button className="primary-button" onClick={onClose}>返回列表</button></div></>}
    {receipt && <div className="pagination-bar"><button disabled={page === 1 || busy} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} / {Math.max(1, Math.ceil(receipt.rows.length / 20))} 页</span><button disabled={page * 20 >= receipt.rows.length || busy} onClick={() => setPage(page + 1)}>下一页</button></div>}
  </LibraryDialog>;
}

export function ProductLibrary() {
  const [q, setQ] = useState(""); const [manufacturer, setManufacturer] = useState(""); const [sort, setSort] = useState("updated_desc"); const [page, setPage] = useState(1);
  const [data, setData] = useState<{ items: LibraryProduct[]; total: number } | null>(null);
  const [manufacturers, setManufacturers] = useState<string[]>([]);
  const [status, setStatus] = useState("loading"); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0); const [editor, setEditor] = useState<LibraryProduct | "new" | null>(null);
  const [detail, setDetail] = useState<LibraryProduct | null>(null); const [detailBusy, setDetailBusy] = useState(false);
  const [deleting, setDeleting] = useState<LibraryProduct | null>(null); const [deleteError, setDeleteError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [priceStatus, setPriceStatus] = useState("all"); const [priceMode, setPriceMode] = useState("");
  const [priceMin, setPriceMin] = useState(""); const [priceMax, setPriceMax] = useState("");
  const [selected, setSelected] = useState<Record<number, { id: number; version: number }>>({});
  const [batchConfirm, setBatchConfirm] = useState(false); const [quoting, setQuoting] = useState(false);
  const [batchResults, setBatchResults] = useState<{ id: number; outcome: string }[]>([]);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const filters: Record<string, string> = { q: q.trim(), sort, price_status: priceStatus };
  if (manufacturer) filters.manufacturer = manufacturer;
  if (priceMode) { filters.price_mode = priceMode; if (priceMode !== "below") filters.price_min = priceMin; if (priceMode !== "above") filters.price_max = priceMax; }
  function clearForFilter() { setPage(1); setSelected({}); setBatchResults([]); if (Object.keys(selected).length) setNotice("筛选条件已改变，已清除旧查询的选择"); }
  function toggle(product: LibraryProduct, checked: boolean) { setSelected(current => { const next = { ...current }; if (checked) next[product.id] = { id: product.id, version: product.version }; else delete next[product.id]; return next; }); }
  async function batchRemove() {
    setBusy(true); setDeleteError(null);
    try {
      const result = await api<{ items: { id: number; outcome: string }[]; deleted: number; missing: number; stale: number }>("/products/batch-delete", json("POST", { items: Object.values(selected) }));
      setBatchResults(result.items); setSelected(current => Object.fromEntries(Object.entries(current).filter(([id]) => !result.items.some(row => row.id === Number(id) && row.outcome === "deleted"))));
      setBatchConfirm(false); refresh(); setNotice(`已删除 ${result.deleted} · 已不存在 ${result.missing} · 版本变化 ${result.stale}。失效项保留选择，请清除或刷新后重新选择。`);
    } catch (caught) { setDeleteError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function copyProduct(kind: "parameters" | "selling_points" | "full") {
    if (!detail) return;
    const text = kind === "full" ? customerCopy(detail) : detail[kind] ?? "";
    if (sensitiveText(kind === "full" ? `${detail.parameters ?? ""}\n${detail.selling_points ?? ""}` : text) && !window.confirm("参数或卖点包含采购成本敏感风险词，请核查客户资料。确认后按原文复制。")) return;
    try { await navigator.clipboard.writeText(text); setCopyStatus("复制成功"); } catch { setCopyStatus("复制失败，请手动选择并复制资料"); }
  }
  const saved = useRef(false);
  const detailOpener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setStatus("loading"); setError(null);
    const params = new URLSearchParams({ ...filters, page: String(page), page_size: "20" });
    if (manufacturer) params.set("manufacturer", manufacturer);
    void Promise.all([api<{ items: LibraryProduct[]; total: number }>(`/products?${params}`, { signal: controller.signal }), api<{ items: string[] }>("/manufacturers", { signal: controller.signal })]).then(([list, names]) => {
      if (controller.signal.aborted) return;
      if (page > 1 && (page - 1) * 20 >= list.total) { setPage(Math.max(1, Math.ceil(list.total / 20))); return; }
      setData(list); setManufacturers(names.items); setStatus("ready"); saved.current = false;
    }).catch(caught => { if (!controller.signal.aborted) { setStatus("error"); setError(saved.current ? "操作已完成，列表刷新失败，请重试刷新。" : (caught as Error).message); } });
    return () => controller.abort();
  }, [q, manufacturer, sort, page, reload, priceStatus, priceMode, priceMin, priceMax]);
  function refresh() { saved.current = true; setNotice("操作已完成"); setReload(value => value + 1); }
  async function openProduct(id: number, edit: boolean) {
    detailOpener.current = document.activeElement as HTMLElement | null;
    setDetailBusy(true); setError(null);
    try { const product = await api<LibraryProduct>(`/products/${id}`); if (edit) setEditor(product); else { setDetail(product); setCopyStatus(null); } }
    catch (caught) { setError((caught as Error).message); }
    finally { setDetailBusy(false); }
  }
  async function remove() {
    if (!deleting) return; setBusy(true); setDeleteError(null);
    try { await api(`/products/${deleting.id}`, json("DELETE", { version: deleting.version })); setDeleting(null); refresh(); }
    catch (caught) { setDeleteError((caught as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="library-page">
    <header className="page-header"><div><p className="eyebrow">PRODUCT LIBRARY</p><h1>产品库</h1><p className="page-description">厂家产品资料</p></div><div className="library-actions"><button className="primary-button" onClick={() => setEditor("new")}>手动新增</button><button className="secondary-button" onClick={() => setImporting(true)}>批量导入</button><TemplateDownload /><button className="secondary-button" onClick={() => setQuoting(true)}>客户报价 Excel</button></div></header>
    {notice && <p role="status" className="feedback feedback-success">{notice}</p>}{error && <p role="alert" className="feedback feedback-server-error">{error}</p>}
    <section className="table-card">
      <div className="library-toolbar"><label>关键词<input aria-label="产品库关键词" maxLength={200} placeholder="型号、名称、参数、卖点、厂家" value={q} onChange={event => { setQ(event.target.value); clearForFilter(); }} /></label><label>厂家筛选<select value={manufacturer} onChange={event => { setManufacturer(event.target.value); clearForFilter(); }}><option value="">全部厂家</option>{manufacturers.map(name => <option key={name}>{name}</option>)}</select></label><label>排序<select aria-label="排序" value={sort} onChange={event => { setSort(event.target.value); setPage(1); }}><option value="updated_desc">最近更新</option><option value="price_asc">批发价从低到高</option><option value="price_desc">批发价从高到低</option></select></label><label>报价状态<select aria-label="报价状态" value={priceStatus} onChange={event => { setPriceStatus(event.target.value); clearForFilter(); }}><option value="all">全部报价状态</option><option value="quoted">有报价</option><option value="unquoted">未报价</option></select></label><label>价格条件<select aria-label="价格条件" value={priceMode} onChange={event => { setPriceMode(event.target.value); clearForFilter(); }}><option value="">不限价格</option><option value="below">小于</option><option value="above">大于</option><option value="between">指定区间（含端点）</option></select></label>
      {priceMode && priceMode !== "below" && <label>最低价<input aria-label="最低价" inputMode="decimal" value={priceMin} onChange={event => { setPriceMin(event.target.value); clearForFilter(); }} /></label>}
      {priceMode && priceMode !== "above" && <label>最高价<input aria-label="最高价" inputMode="decimal" value={priceMax} onChange={event => { setPriceMax(event.target.value); clearForFilter(); }} /></label>}
      <button className="secondary-button" onClick={() => { setSelected({}); setBatchResults([]); setReload(value => value + 1); }}>刷新</button></div>
      <div className="library-selection"><span>跨页已选 {Object.keys(selected).length} 款</span><button className="text-button" onClick={() => { setSelected({}); setBatchResults([]); }}>清空选择</button><button className="danger-button" disabled={!Object.keys(selected).length} onClick={() => { setBatchConfirm(true); setDeleteError(null); }}>批量删除</button></div>
      {batchResults.filter(row => row.outcome !== "deleted").map(row => <p role="status" key={row.id}>产品 #{row.id}：{row.outcome === "missing" ? "已不存在" : "版本已变化"}，请刷新后重新选择</p>)}
      {status === "loading" && <p role="status" className="state-panel">正在加载产品…</p>}
      {status === "error" && <div className="state-panel state-error"><p>产品列表加载失败</p><button onClick={() => setReload(value => value + 1)}>重试</button></div>}
      {status === "ready" && data && <>{data.items.length === 0 ? <p className="state-panel">没有符合条件的产品</p> : <div className="table-scroll"><table className="library-table"><thead><tr><th><input aria-label="选择本页" type="checkbox" checked={!!data.items.length && data.items.every(item => selected[item.id])} onChange={event => { const checked = event.target.checked; setSelected(current => { const next = { ...current }; for (const item of data.items) { if (checked) { if (!next[item.id]) next[item.id] = { id: item.id, version: item.version }; } else delete next[item.id]; } return next; }); }} /></th><th>厂家</th><th>型号</th><th>名称</th><th>批发价</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{data.items.map(product => <tr key={product.id}><td><input aria-label={`选择产品 ${product.id}`} type="checkbox" checked={!!selected[product.id]} onChange={event => toggle(product, event.target.checked)} /></td><td>{product.manufacturer_name}</td><td>{display(product.model)}</td><td>{product.name}{q.trim() && <small className="library-match">{searchSummary(product, q)}</small>}</td><td>{product.wholesale_price == null ? "未提供" : `¥${product.wholesale_price}`}</td><td>{new Date(product.updated_at).toLocaleString()}</td><td><div className="library-actions"><button className="detail-button" disabled={detailBusy} onClick={() => void openProduct(product.id, false)}>查看</button><button className="detail-button" disabled={detailBusy} onClick={() => void openProduct(product.id, true)}>编辑</button><button className="text-button" onClick={() => { setDeleteError(null); setDeleting(product); }}>删除</button></div></td></tr>)}</tbody></table></div>}
        <PaginationBar total={data.total} itemLabel="款产品" pageSize={20} page={page} totalPages={Math.max(1, Math.ceil(data.total / 20))} onPrevious={() => setPage(page - 1)} onNext={() => setPage(page + 1)} previousDisabled={page === 1} nextDisabled={page * 20 >= data.total} /></>}
    </section>
    {detailBusy && <p role="status">正在加载产品详情…</p>}
    {editor && <ProductEditor product={editor === "new" ? null : editor} returnFocus={editor === "new" ? undefined : detailOpener.current} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); refresh(); }} />}
    {detail && <LibraryDialog side title="产品详情" returnFocus={detailOpener.current} onClose={() => setDetail(null)}><div className="library-actions"><button onClick={() => void copyProduct("parameters")}>复制参数</button><button onClick={() => void copyProduct("selling_points")}>复制卖点</button><button onClick={() => void copyProduct("full")}>复制完整资料</button></div>{copyStatus && <p role="status">{copyStatus}</p>}<dl className="library-details">{(Object.keys(labels) as (keyof ProductFields)[]).map(key => <div key={key}><dt>{labels[key]}</dt><dd>{display(detail[key])}</dd></div>)}</dl><p>创建：{new Date(detail.created_at).toLocaleString()} · 更新：{new Date(detail.updated_at).toLocaleString()}</p></LibraryDialog>}
    {deleting && <LibraryDialog title="永久删除产品" busy={busy} onClose={() => setDeleting(null)}><p>厂家：{deleting.manufacturer_name}</p><p>型号：{display(deleting.model)}</p><p>名称：{deleting.name}</p><p>此产品将永久删除，无法恢复。</p>{deleteError && <p role="alert">{deleteError}</p>}<div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => setDeleting(null)}>取消</button><button className="danger-button" disabled={busy} onClick={() => void remove()}>确认删除</button></div></LibraryDialog>}
    {batchConfirm && <LibraryDialog title="批量永久删除" busy={busy} onClose={() => setBatchConfirm(false)}><p>将永久删除已选择的 {Object.keys(selected).length} 款产品，产品资料不可恢复。版本变化或已不存在的项将跳过。</p>{deleteError && <p role="alert">{deleteError}</p>}<div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => setBatchConfirm(false)}>取消</button><button className="danger-button" disabled={busy} onClick={() => void batchRemove()}>确定删除</button></div></LibraryDialog>}
    {quoting && <ProductQuotation selected={Object.values(selected)} filters={filters} onClose={() => setQuoting(false)} />}
    {importing && <ImportDialog onClose={() => setImporting(false)} onSaved={refresh} />}
  </div>;
}

export function prioritizedRows(rows: PreviewRow[]) {
  const priority = { invalid: 0, conflict: 1, suspected: 2, new: 3, existing: 3 };
  return [...rows].sort((a, b) => priority[a.category] - priority[b.category] || a.row_number - b.row_number);
}
export function customerCopy(product: ProductFields) {
  return `产品型号：${product.model ?? "未提供"}\n产品名称：${product.name}\n产品参数：${product.parameters ?? "未提供"}\n产品卖点：${product.selling_points ?? "未提供"}`;
}
export function sensitiveText(text: string) { return /成本|采购价|进货价|拿货价|供货价|底价|批发价|内部价|利润|加价率|开票调整|运费成本/.test(text); }
export function searchSummary(product: ProductFields, query: string) {
  const keyword = query.trim().toLowerCase();
  return (["model", "name", "parameters", "selling_points", "manufacturer_name"] as const).flatMap(field => {
    const value = product[field] ?? ""; const index = value.toLowerCase().indexOf(keyword);
    return index < 0 ? [] : [`命中${labels[field]}${field === "parameters" ? `：${index > 20 ? "…" : ""}${value.slice(Math.max(0, index - 20), index + keyword.length + 40)}${index + keyword.length + 40 < value.length ? "…" : ""}` : ""}`];
  }).join(" · ");
}
