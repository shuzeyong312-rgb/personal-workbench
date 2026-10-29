import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
import "./ProductLibrary.css";
import { ProductLibraryDetails, type ProductDetail } from "./ProductLibraryDetails";
import { V2ImportReview, type V2Preview } from "./ProductLibraryV2Import";
import { ProductQuotation } from "./ProductQuotation";
import { PaginationBar } from "./PaginationBar";
import { useProductSearchQuery } from "./WorkspaceTools";

export type ProductFields = {
  manufacturer_name: string; model: string | null; name: string; parameters: string | null;
  selling_points: string | null; wholesale_price: string | null; price_note: string | null;
};
export type LibraryProduct = ProductFields & { source_companies?: string[]; price_state?: "default" | "multiple" | "unquoted"; category?: string | null; id: number; version: number; created_at: string; updated_at: string };
type Action = "insert" | "update" | "append_source" | "skip";
type FieldDiff = Record<string, { old: string | null; incoming: string | null; effective: string | null; changed: boolean }>;
type Candidate = { id: number; name: string; model: string | null; version?: number; reason?: string; can_update?: boolean; diff?: FieldDiff };
export type PreviewRow = Partial<ProductFields> & {
  existing_id?: number | null; version?: number | null; identity_reason?: string;
  row_number: number; category: "new" | "duplicate" | "invalid";
  errors: { field: string; code: string; message: string }[];
  candidate: Candidate[]; file_candidates: { row_number: number; name: string; model: string | null }[];
  diff: FieldDiff;
  allowed_actions: Action[]; default_action: Action;
};
type Preview = { attachment_warning?: string | null; identity_rule_version?: number; import_id: string; status: "ready"; expires_at: string; manufacturer_name: string; counts: Record<string, number>; rows: PreviewRow[] };
type Result = { import_id: string; status: "committed"; inserted: number; updated: number; skipped: number; invalid: number; rows: { row_number: number; outcome: string; product_id: number | null; reason_code: string; model?: string | null; name?: string | null; errors?: { field: string; message: string }[] }[] };
type Receipt = Preview | Result;
type ApiError = Error & { code?: string; candidates?: Candidate[]; errors?: { field: string; message: string }[]; uncertain?: boolean };
const base = "/api/product-library";
export const emptyProduct: ProductFields = { manufacturer_name: "", model: null, name: "", parameters: null, selling_points: null, wholesale_price: null, price_note: null };
const labels: Record<keyof ProductFields, string> = { manufacturer_name: "厂家名称", model: "产品型号", name: "产品名称", parameters: "产品参数", selling_points: "产品卖点", wholesale_price: "批发价", price_note: "价格备注" };
const categories = { new: "新增", duplicate: "重复", invalid: "异常" };
const actions = { insert: "新增", update: "确认更新主资料", append_source: "追加来源/价格", skip: "跳过" };
const display = (value: string | null | undefined) => value ?? "未提供";

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(base + path, options); }
  catch { throw Object.assign(new Error("网络异常，结果待确认"), { uncertain: true }); }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw Object.assign(new Error(body.message ?? "请求失败，请重试"), { code: body.code, candidates: body.candidates, errors: body.errors, items: body.items, uncertain: response.status >= 500 && !["product_save_failed", "import_save_failed", "database_busy", "identity_schema_required"].includes(body.code) });
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
  for (const row of rows) { const action = decisions[row.row_number] ?? row.default_action; counts[action === 'append_source' ? 'update' : action]++; }
  return counts;
}

export function LibraryDialog({ title, busy = false, onClose, children, returnFocus, side, wide = false, review = false }: { title: string; busy?: boolean; onClose: () => void; children: ReactNode; returnFocus?: HTMLElement | null; side?: boolean; wide?: boolean; review?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [opener] = useState(() => returnFocus ?? (typeof document === "undefined" ? null : document.activeElement as HTMLElement | null));
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => { dialog?.close(); opener?.focus(); };
  }, []);
  return <dialog ref={ref} className={`dialog library-dialog${side ? " library-side-panel" : ""}${wide ? " library-dialog-wide" : ""}${review ? " library-import-review" : ""}`} aria-label={title} onCancel={event => { event.preventDefault(); if (event.target === event.currentTarget && !busy) onClose(); }} onKeyDown={event => {
    if (event.key !== "Tab") return;
    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary, [tabindex="0"]')).filter(node => node.getClientRects().length > 0);
    const target = event.shiftKey ? controls.at(-1) : controls[0];
    if (target && (event.shiftKey && document.activeElement === controls[0] || !event.shiftKey && document.activeElement === controls.at(-1))) { event.preventDefault(); target.focus(); }
  }}>
    <div className="dialog-header"><h2>{title}</h2><button type="button" className="close-button" aria-label="关闭" disabled={busy} onClick={onClose}>×</button></div><div className="library-dialog-body">{children}</div>
  </dialog>;
}

export function ProductEditor({ product, onClose, onSaved, returnFocus }: { product: LibraryProduct | null; onClose: () => void; onSaved: () => void; returnFocus?: HTMLElement | null }) {
  const [fields, setFields] = useState<ProductFields>(product ?? emptyProduct);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const errorSummary = useRef<HTMLDivElement>(null);
  useEffect(() => { if (error) errorSummary.current?.focus(); }, [error]);
  const dirty = (Object.keys(emptyProduct) as (keyof ProductFields)[]).some(key => fields[key] !== (product ?? emptyProduct)[key]);
  function close() { if (!dirty || window.confirm(uncertain ? "保存结果待确认，请关闭后刷新列表核对。确认关闭？" : "有未保存的修改，确认放弃并关闭？")) onClose(); }
  async function save(event: FormEvent) {
    event.preventDefault();
    const companyChanged = !!product && fields.manufacturer_name !== product.manufacturer_name;
    if (companyChanged && !window.confirm('确认修改首录资料公司？这不会替换已有来源资料；新增报价来源请在详情添加。')) return;
    setBusy(true); setError(null);
    try {
      const payload = Object.fromEntries(Object.keys(emptyProduct).map(key => [key, fields[key as keyof ProductFields]]));
      await api(product ? `/products/${product.id}` : "/products", json(product ? "PUT" : "POST", { ...payload, ...(product ? { version: product.version } : {}), ...(companyChanged ? { confirm_manufacturer_change: true } : {}) }));
      onSaved();
    } catch (caught) {
      const failure = caught as ApiError; setError(failure);
      if (failure.uncertain) setUncertain(true);
    } finally { setBusy(false); }
  }
  return <LibraryDialog wide title={product ? "编辑产品" : "手动新增产品"} busy={busy} onClose={close} returnFocus={returnFocus}>
    <form onSubmit={save} className="library-form">
      <p className="library-intro">{product ? "更新产品原始资料，客户报价调整不会写回这里。" : "录入厂家产品资料，稍后可用于检索、复制与客户报价。"} 标有 * 的字段必填。</p>
      {([{ title: "基本信息", fields: ["manufacturer_name", "model", "name"] }, { title: "客户产品资料", fields: ["parameters", "selling_points"] }, { title: "内部价格信息", fields: ["wholesale_price", "price_note"] }] as { title: string; fields: (keyof ProductFields)[] }[]).map(group => <fieldset className="library-fieldset" key={group.title}><legend>{group.title}</legend><div className="library-field-grid">
        {group.fields.map(key => <label className={`library-field library-field-${key}`} key={key}>{labels[key]}{(key === "manufacturer_name" || key === "name") && " *"}
          {key === "parameters" || key === "selling_points" || key === "price_note" ? <textarea id={`library-field-${key}`} disabled={busy || uncertain} aria-describedby={error?.errors?.some(item => item.field === key) ? `library-error-${key}` : undefined} aria-invalid={error?.errors?.some(item => item.field === key) || undefined} value={fields[key] ?? ""} maxLength={key === "price_note" ? 2000 : 10000} rows={key === "price_note" ? 2 : 5} onChange={event => { setFields({ ...fields, [key]: event.target.value || null }); setError(null); }} /> :
            <input id={`library-field-${key}`} disabled={busy || uncertain} aria-describedby={error?.errors?.some(item => item.field === key) ? `library-error-${key}` : undefined} aria-invalid={error?.errors?.some(item => item.field === key) || undefined} value={fields[key] ?? ""} required={key === "manufacturer_name" || key === "name"} maxLength={key === "wholesale_price" ? undefined : 200} inputMode={key === "wholesale_price" ? "decimal" : undefined} onChange={event => { setFields({ ...fields, [key]: event.target.value || (key === "manufacturer_name" || key === "name" ? "" : null) }); setError(null); }} />}
          {error?.errors?.some(item => item.field === key) && <span className="library-field-error" id={`library-error-${key}`}>{error.errors.filter(item => item.field === key).map(item => item.message).join("；")}</span>}
        </label>)}
      </div>{group.title === "内部价格信息" && <p className="library-hint">批发价单位为人民币元，最多两位小数。空字段保存为未提供。批发价与价格备注不进入客户 Excel。</p>}</fieldset>)}
      {error && <div ref={errorSummary} tabIndex={-1} role="alert" className="feedback feedback-server-error">{error.message}{error.errors?.map((item, index) => <p key={index}><a href={`#library-field-${item.field}`} onClick={event => { event.preventDefault(); document.getElementById(`library-field-${item.field}`)?.focus(); }}>{labels[item.field as keyof ProductFields] ?? item.field}：{item.message}</a></p>)}{error.candidates?.map(candidate => <p key={candidate.id}>候选 #{candidate.id} · {display(candidate.model)} · {candidate.name}{candidate.version != null ? ` · v${candidate.version}` : ""}</p>)}</div>}
      {error?.code === "product_exists" && <p>精确重复不能新增；请关闭表单，通过产品 ID 查看或编辑已有产品。</p>}
      {uncertain && <p role="alert">保存结果待确认。请关闭后刷新列表核对，避免重复创建或覆盖；本表单已停止重发。</p>}
      <div className="dialog-actions library-sticky-actions"><span>{dirty ? "有未保存的修改" : product ? "当前资料已载入" : "填写完成后保存"}</span><button type="button" className="secondary-button" disabled={busy} onClick={close}>取消</button><button className="primary-button" disabled={busy || uncertain}>{busy ? "保存中…" : "保存"}</button></div>
    </form>
  </LibraryDialog>;
}

function ImportDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [manufacturer, setManufacturer] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [attachmentsConfirmed, setAttachmentsConfirmed] = useState(false);
  const [v2Preview, setV2Preview] = useState<V2Preview | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [decisions, setDecisions] = useState<Record<number, Action>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [stale, setStale] = useState(false);
  const [retryDecisions, setRetryDecisions] = useState<{ row_number: number; action: Action; target_id?: number; target_version?: number }[] | null>(null);
  const [targets, setTargets] = useState<Record<number, number>>({});
  const [comparisons, setComparisons] = useState<Record<number, number>>({});
  const [page, setPage] = useState(1);
  const [reviewFilter, setReviewFilter] = useState("");
  const [reviewQuery, setReviewQuery] = useState("");
  const [reviewAction, setReviewAction] = useState("");
  const auditScroll = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [sourceRows, setSourceRows] = useState<PreviewRow[]>([]);
  const preview = receipt?.status === "ready" ? receipt : null;
  const plan = preview ? plannedCounts(preview.rows, decisions) : null;
  function close() {
    if (uncertain) { setError("结果待确认，请先查询原导入结果后关闭。"); return; }
    if (preview && !window.confirm("当前预览尚未保存，关闭将放弃选择。")) return;
    onClose();
  }
  function reset() { if (preview && !window.confirm("返回将放弃当前预览和逐行选择，确认返回？")) return; setReceipt(null); setFile(null); setDecisions({}); setTargets({}); setComparisons({}); setRetryDecisions(null); setStale(false); setError(null); setPage(1); }
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    if (!/\.xlsx$/i.test(file.name)) { setError("仅支持 .xlsx 文件"); return; }
    if (file.size > 5 * 1024 * 1024) { setError("文件不能超过 5 MiB"); return; }
    setBusy(true); setError(null); setAttachmentsConfirmed(false);
    try {
      const next = await api<Preview | V2Preview>(`/imports/preview?manufacturer_name=${encodeURIComponent(manufacturer)}`, { method: "POST", headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-Filename": encodeURIComponent(file.name) }, body: file });
      if ('template_version' in next && next.template_version === 2) { setV2Preview(next as V2Preview); return; }
      const legacy = next as Preview;
      setReceipt(legacy); setSourceRows(legacy.rows); setDecisions({}); setTargets({}); setComparisons({}); setReviewFilter(""); setReviewQuery(""); setReviewAction(""); setExpanded(null); setPage(1);
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function lookup() {
    if (!receipt) return; setBusy(true); setError(null);
    try {
      const next = await api<Receipt>(`/imports/${receipt.import_id}`); setReceipt(next); setUncertain(false);
      if (next.status === "committed") { setReviewFilter(""); setReviewQuery(""); setPage(1); onSaved(); }
      else setError("后端确认尚未提交，可按原决策重试。");
    } catch (caught) {
      const failure = caught as ApiError; setError(failure.message);
      if (failure.code === "preview_expired" || failure.code === "preview_stale" || failure.code === "preview_rule_changed") { setUncertain(false); setStale(true); }
    } finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview) return; setBusy(true); setError(null);
    const submitted = retryDecisions ?? preview.rows.map(row => {
      const action = decisions[row.row_number] ?? row.default_action;
      const target = updateTarget(row);
      return { row_number: row.row_number, action, ...((action === "update" || action === "append_source") && (preview.identity_rule_version ?? 0) >= 3 && target ? { target_id: target.id, target_version: target.version } : {}) };
    });
    try {
      const next = await api<Result>(`/imports/${preview.import_id}/confirm`, json("POST", { decisions: submitted, ...(preview.attachment_warning ? { confirmed_attachments_not_imported: attachmentsConfirmed } : {}) }));
      setReceipt(next); setReviewFilter(""); setReviewQuery(""); setPage(1); onSaved();
    } catch (caught) {
      const failure = caught as ApiError;
      setError(failure.uncertain ? "结果待确认，请查询原导入结果。" : failure.message);
      setUncertain(!!failure.uncertain);
      if (failure.uncertain) setRetryDecisions(submitted);
      if (failure.code === "preview_stale" || failure.code === "preview_expired" || failure.code === "preview_rule_changed") setStale(true);
    } finally { setBusy(false); }
  }
  function updateTarget(row: PreviewRow) {
    return row.candidate.find(candidate => candidate.id === (targets[row.row_number] ?? row.existing_id) && (candidate.can_update || row.allowed_actions.includes("append_source")));
  }
  function choose(row: PreviewRow, action: Action) {
    const target = updateTarget(row);
    if (action === "update" && (preview?.identity_rule_version ?? 0) >= 3) {
      if (!target) { setError(`请先为第 ${row.row_number} 行选择明确的更新目标。`); setExpanded(row.row_number); return; }
      if (expanded !== row.row_number || (comparisons[row.row_number] != null && comparisons[row.row_number] !== target.id)) { setComparisons(current => ({ ...current, [row.row_number]: target.id })); setExpanded(row.row_number); setError(`请核对第 ${row.row_number} 行目标 #${target.id} 的完整差异，再选择确认更新。`); return; }
    }
    if (action === "update" && !window.confirm(`确认用第 ${row.row_number} 行更新产品 #${target?.id ?? row.existing_id ?? "已有产品"} ${target?.name ?? ""}？将覆盖对应差异字段，空值保留原值。`)) return;
    setError(null); setDecisions(current => ({ ...current, [row.row_number]: action }));
  }
  const resultLabels: Record<string, string> = { inserted: "新增成功", updated: "更新成功", skipped: "已跳过", invalid: "校验未通过" };
  const allRows = receipt?.status === "ready" ? prioritizedRows(receipt.rows) : receipt?.rows.map(row => ({ ...sourceRows.find(source => source.row_number === row.row_number), ...row })) ?? [];
  const orderedRows = allRows.filter(row => {
    const status = "category" in row && receipt?.status === "ready" ? row.category : "outcome" in row ? row.outcome : "";
    const match = (!reviewFilter || status === reviewFilter) && (!preview || !reviewAction || (decisions[row.row_number] ?? (row as PreviewRow).default_action) === reviewAction);
    return match && `${row.model ?? ""} ${row.name ?? ""}`.toLocaleLowerCase().includes(reviewQuery.trim().toLocaleLowerCase());
  });
  const controls = receipt && <div className="library-review-toolbar"><label>搜索型号或名称<input placeholder="输入型号或产品名称" value={reviewQuery} onChange={event => { setReviewQuery(event.target.value); setPage(1); }} /></label><label>{preview ? "审核状态" : "执行结果"}<select aria-label={preview ? "审核状态" : "执行结果"} value={reviewFilter} onChange={event => { setReviewFilter(event.target.value); setPage(1); }}><option value="">全部</option>{Object.entries(preview ? categories : resultLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>{preview && <label>计划操作筛选<select value={reviewAction} onChange={event => { setReviewAction(event.target.value); setPage(1); }}><option value="">全部操作</option>{Object.entries(actions).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}{(reviewFilter || reviewQuery || (preview && reviewAction)) && <button className="text-button" onClick={() => { setReviewFilter(""); setReviewQuery(""); setReviewAction(""); setPage(1); }}>重置审核筛选</button>}<span role="status">匹配 {orderedRows.length} 行</span></div>;
  const locked = busy || uncertain || retryDecisions !== null || stale;
  const currentPage = Math.min(page, Math.max(1, Math.ceil(orderedRows.length / 20)));
  const rows = orderedRows.slice((currentPage - 1) * 20, currentPage * 20);
  useEffect(() => { if (page !== currentPage) setPage(currentPage); }, [page, currentPage]);
  useEffect(() => {
    const list = auditScroll.current;
    if (!list) return;
    list.scrollTop = 0; list.scrollLeft = 0;
    const body = list.closest<HTMLElement>(".library-dialog-body");
    if (body && body.scrollTop > 0) body.scrollTop += list.getBoundingClientRect().top - body.getBoundingClientRect().top;
  }, [currentPage, reviewFilter, reviewQuery, reviewAction]);
  const pagination = receipt && <div className="pagination-bar"><span>{orderedRows.length ? `${(currentPage - 1) * 20 + 1}–${Math.min(currentPage * 20, orderedRows.length)} / ${orderedRows.length} 行` : "0 行"} · 每页 20 行</span><button disabled={currentPage === 1 || busy} onClick={() => setPage(currentPage - 1)}>上一页</button><span>第 {currentPage} / {Math.max(1, Math.ceil(orderedRows.length / 20))} 页</span><button disabled={currentPage * 20 >= orderedRows.length || busy} onClick={() => setPage(currentPage + 1)}>下一页</button></div>;
  const expired = !!preview && Date.parse(preview.expires_at) <= Date.now();
  const [, tick] = useState(0);
  useEffect(() => { if (!preview) return; const timer = setInterval(() => tick(value => value + 1), 1000); return () => clearInterval(timer); }, [preview]);
  if (v2Preview) return <V2ImportReview preview={v2Preview} onClose={onClose} onSaved={onSaved} />;
  return <LibraryDialog wide review={!!preview} title={`批量导入 · 步骤 ${receipt?.status === "committed" ? 3 : preview ? 2 : 1}/3`} busy={busy} onClose={close}>
    <ol className="library-steps" aria-label="导入进度">{["上传文件", "核对与决策", "导入结果"].map((label, index) => <li key={label} aria-current={(receipt?.status === "committed" ? 2 : preview ? 1 : 0) === index ? "step" : undefined}><span>{index + 1}</span>{label}</li>)}</ol>
    {error && <div className="feedback feedback-server-error" role="alert">{error}</div>}
    {!receipt && <form className="library-form" onSubmit={upload}>
      <p>仅 .xlsx，最多 5 MiB、1000 行。支持原六列 V1 与五工作表 V2；文本列须为文本，禁止公式。确认前不写入产品。</p>
      <TemplateDownload /><a className="secondary-button" href="/api/product-library/template?template_version=2" download="产品库V2模板.xlsx">下载 V2 多规格/多价格模板</a>
      <label>批次资料公司（V1 必填，未知请留空）<input maxLength={200} value={manufacturer} onChange={event => setManufacturer(event.target.value)} /></label>
      <label>Excel 文件 *<span className="library-file-control"><span className="library-file-button" aria-hidden="true">选择 Excel 文件</span><span aria-hidden="true">{file?.name ?? "尚未选择文件 · .xlsx · 最多 5 MiB"}</span><input required={!file} type="file" accept=".xlsx" onChange={event => { const next = event.target.files?.[0]; if (next) setFile(next); }} /></span></label>
      <div className="dialog-actions"><button className="primary-button" disabled={busy}>{busy ? "校验中…" : "上传并预览"}</button></div>
    </form>}
    {preview && <>
      {preview.attachment_warning && <label className="library-check"><input type="checkbox" disabled={locked} checked={attachmentsConfirmed} onChange={event => setAttachmentsConfirmed(event.target.checked)} />{preview.attachment_warning} 已知晓并将自行保留原件。</label>}
      <section className="library-review-overview" aria-label="整批导入概况">
        <div className="library-review-heading"><div><h3>核对与决策</h3><p>厂家：<strong>{preview.manufacturer_name}</strong><span>共 {preview.rows.length} 行 · 忽略空行 {preview.counts.ignored_blank_rows ?? 0}</span></p></div><span className="library-hint">确认前不会写入产品</span></div>
        <div className="library-review-categories" aria-label="按审核状态快速定位">{[["", "全部", preview.rows.length], ...Object.entries(categories).map(([key, label]) => [key, label, preview.counts[key] ?? 0])].map(([key, label, count]) => <button key={key} aria-pressed={reviewFilter === key} onClick={() => { setReviewFilter(String(key)); setPage(1); }}><span>{label}</span><strong>{count}</strong></button>)}</div>
        <p className="library-review-guidance">{preview.counts.invalid > 0 ? `${preview.counts.invalid} 行异常不会导入，可筛选查看原因，修改文件后重新预览。` : preview.counts.duplicate > 0 ? "重复行默认跳过；如需更新，请展开核对完整差异并确认更新目标。" : "新增行已默认加入导入计划，可直接核对或调整计划操作。"} <span>重复仅指同型号、同名称，不按来源公司拆分。</span></p>
      </section>
      {uncertain && <p role="status">结果待确认：导入编号 {preview.import_id}。先查询回执，不能重新上传或更改决策。</p>}
      {controls}
      <div className="library-review-bulk"><span>整批新增行 · 不受当前筛选影响</span>{(["insert", "skip"] as Action[]).map(action => <button className="secondary-button" disabled={locked || !preview.counts.new} key={action} onClick={() => setDecisions(current => ({ ...current, ...Object.fromEntries(preview.rows.filter(row => row.category === "new").map(row => [row.row_number, action])) }))}>{action === "insert" ? "新增全部新增行" : "跳过全部新增行"}</button>)}</div>
      <div ref={auditScroll} className="table-scroll library-audit-scroll" role="region" aria-label="导入明细，可横向滚动" tabIndex={0}><table className="library-audit-table"><thead><tr><th>Excel 行</th><th>型号 / 名称</th><th>审核状态</th><th>计划操作</th><th>核对</th></tr></thead>{(rows as PreviewRow[]).map(row => <tbody className={`library-preview-row${expanded === row.row_number ? " is-expanded" : ""}`} key={row.row_number}>
        <tr><td>第 {row.row_number} 行</td><td><strong>{display(row.model)}</strong><span className="library-review-name">{display(row.name)}</span></td><td><span className={`library-review-badge is-${row.category}`}>{categories[row.category]}</span>{row.identity_reason && row.category !== "new" && <small className="library-match">{row.identity_reason}</small>}{row.errors.map((item, index) => <small className="library-row-error" key={index}>{labels[item.field as keyof ProductFields] ?? item.field}：{item.message}</small>)}</td>
        <td>{(preview.identity_rule_version ?? 0) >= 3 && row.allowed_actions.includes("update") && <label>第 {row.row_number} 行更新目标<select aria-label={`第 ${row.row_number} 行更新目标`} disabled={locked} value={targets[row.row_number] ?? row.existing_id ?? ""} onChange={event => { setTargets(current => ({ ...current, [row.row_number]: Number(event.target.value) })); setComparisons(current => ({ ...current, [row.row_number]: Number(event.target.value) })); setDecisions(current => ({ ...current, [row.row_number]: "skip" })); setExpanded(row.row_number); setError(null); }}><option value="">请选择目标，不自动覆盖</option>{row.candidate.filter(candidate => candidate.can_update).map(candidate => <option value={candidate.id} key={candidate.id}>#{candidate.id} · {candidate.name} · v{candidate.version}</option>)}</select></label>}<label className="library-visually-hidden" htmlFor={`import-action-${row.row_number}`}>第 {row.row_number} 行操作</label><select id={`import-action-${row.row_number}`} disabled={locked || row.category === "invalid"} value={decisions[row.row_number] ?? row.default_action} onChange={event => choose(row, event.target.value as Action)}>{row.allowed_actions.map(action => <option key={action} value={action}>{actions[action]}</option>)}</select></td>
        <td><button className="text-button" aria-expanded={expanded === row.row_number} onClick={() => setExpanded(expanded === row.row_number ? null : row.row_number)}>核对第 {row.row_number} 行</button></td></tr>
        {expanded === row.row_number && <tr><td colSpan={5}><div className="library-row-detail">
          {row.errors.map((item, index) => <p role="alert" key={index}>{labels[item.field as keyof ProductFields] ?? item.field}：{item.message}</p>)}
          {row.candidate.map(candidate => <p key={candidate.id}>已有候选 #{candidate.id} · {display(candidate.model)} · {candidate.name}{candidate.version != null ? ` · v${candidate.version}` : ""}</p>)}
          {row.file_candidates.map(candidate => <p key={candidate.row_number}>文件内候选：第 {candidate.row_number} 行 · {display(candidate.model)} · {candidate.name}</p>)}
          {row.candidate.length > 0 && <label>第 {row.row_number} 行对比候选<select aria-label={`第 ${row.row_number} 行对比候选`} disabled={locked} value={comparisons[row.row_number] ?? updateTarget(row)?.id ?? row.candidate[0].id} onChange={event => { setComparisons(current => ({ ...current, [row.row_number]: Number(event.target.value) })); if ((decisions[row.row_number] ?? row.default_action) === "update") setDecisions(current => ({ ...current, [row.row_number]: "skip" })); }}>{row.candidate.map(candidate => <option key={candidate.id} value={candidate.id}>#{candidate.id} · {candidate.name} · {candidate.reason ?? "候选"}</option>)}</select><small>仅用于比较；更新目标需在计划操作中明确选择并确认。</small></label>}
          <div className="table-scroll"><table className="library-diff"><caption>完整字段差异 · 当前计划：{actions[decisions[row.row_number] ?? row.default_action]}{(decisions[row.row_number] ?? row.default_action) === "skip" ? "（不保存）" : ""}</caption><thead><tr><th>字段</th><th>对比候选旧值</th><th>上传值</th><th>实际保存值{(decisions[row.row_number] ?? row.default_action) === "update" && updateTarget(row) ? ` · #${updateTarget(row)!.id}` : ""}</th></tr></thead><tbody>{(Object.keys(labels) as (keyof ProductFields)[]).filter(key => key !== "manufacturer_name").map(key => {
            const action = decisions[row.row_number] ?? row.default_action;
            const comparison = row.candidate.find(candidate => candidate.id === (comparisons[row.row_number] ?? updateTarget(row)?.id ?? row.candidate[0]?.id));
            const diff = (comparison?.diff ?? row.diff)[key] ?? { old: null, incoming: row[key] ?? null, effective: row[key] ?? null, changed: false };
            const update = (updateTarget(row)?.diff ?? row.diff)[key] ?? diff;
            return <tr key={key}><th>{labels[key]}</th><td>{display(diff.old)}</td><td>{display(row[key])}</td><td>{action === "skip" ? "不保存" : action === "insert" ? display(row[key]) : <>{display(update.effective)}{update.incoming == null && update.old != null ? "（保留原值）" : update.changed ? "（变更）" : ""}</>}</td></tr>;
          })}</tbody></table></div>
        </div></td></tr>}
      </tbody>)}</table>{!rows.length && <div className="state-panel"><p>没有匹配的导入行</p><button className="text-button" onClick={() => { setReviewFilter(""); setReviewQuery(""); setReviewAction(""); setPage(1); }}>查看全部导入行</button></div>}</div>
      <footer className="library-review-footer">{pagination}<div className="library-review-plan"><p aria-live="polite">计划新增 {plan!.insert} · 更新 {plan!.update} · 异常 {preview.counts.invalid} · 合法跳过 {plan!.skip - preview.counts.invalid}</p><span>{stale ? "预览已失效，请返回重新预览" : expired ? "预览已过期，请返回重新预览" : plan!.insert + plan!.update === 0 ? "当前没有待写入商品；可核对重复行后更新，或返回修改文件。" : "按整批计划提交，跨页选择已保留"} · {expired ? "已过期" : `有效至 ${new Date(preview.expires_at).toLocaleTimeString()}`}</span></div>
      <div className="dialog-actions"><button className="secondary-button" disabled={busy || uncertain || (retryDecisions !== null && !stale)} onClick={reset}>返回修改文件或厂家（放弃选择）</button>{uncertain ? <button className="primary-button" disabled={busy} onClick={() => void lookup()}>查询原导入结果</button> : <button className="primary-button" disabled={busy || stale || expired || !plan || plan.insert + plan.update === 0} onClick={() => void confirm()}>{busy ? "确认中…" : retryDecisions ? "按原决策重试" : "确认导入"}</button>}</div></footer>
    </>}
    {receipt?.status === "committed" && <><p role="status">导入完成：新增 {receipt.inserted} · 更新 {receipt.updated} · 跳过 {receipt.skipped} · 错误 {receipt.invalid}</p>{controls}<div className="table-scroll library-audit-scroll" role="region" aria-label="导入明细，可横向滚动" tabIndex={0}><table className="library-audit-table"><thead><tr><th>Excel 行</th><th>型号</th><th>名称</th><th>执行结果</th><th>原因 / 产品</th></tr></thead><tbody>{(rows as (Result["rows"][number] & Partial<ProductFields>)[]).map(row => <tr key={row.row_number}><td>第 {row.row_number} 行</td><td>{display(row.model)}</td><td>{display(row.name)}</td><td>{resultLabels[row.outcome] ?? "结果待确认"}</td><td>{row.outcome === "invalid" ? row.errors?.map(item => item.message).join("；") || "预览校验未通过，未写入" : row.outcome === "skipped" ? "按行级决策跳过，未写入" : row.product_id == null ? "未提供产品编号" : `产品 #${row.product_id}`}</td></tr>)}</tbody></table></div><div className="dialog-actions library-sticky-actions"><button className="primary-button" onClick={onClose}>返回列表</button></div></>}
    {receipt?.status === "committed" && pagination}

  </LibraryDialog>;
}

export function ProductLibrary() {
  const globalQuery = useProductSearchQuery();
  const [q, setQ] = useState(globalQuery.text);
  const [manufacturer, setManufacturer] = useState(""); const [sort, setSort] = useState("updated_desc"); const [page, setPage] = useState(1);
  const [data, setData] = useState<{ items: LibraryProduct[]; total: number } | null>(null);
  const [manufacturers, setManufacturers] = useState<string[]>([]);
  const [status, setStatus] = useState("loading"); const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0); const [editor, setEditor] = useState<LibraryProduct | "new" | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null); const [detailBusy, setDetailBusy] = useState(false);
  const [deleting, setDeleting] = useState<LibraryProduct | null>(null); const [deleteError, setDeleteError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [priceStatus, setPriceStatus] = useState("all"); const [priceMode, setPriceMode] = useState("");
  const [priceMin, setPriceMin] = useState(""); const [priceMax, setPriceMax] = useState("");
  const [selected, setSelected] = useState<Record<number, { id: number; version: number }>>({});
  const [batchConfirm, setBatchConfirm] = useState(false); const [quoting, setQuoting] = useState(false);
  const [batchResults, setBatchResults] = useState<{ id: number; outcome: string }[]>([]);
  const [appliedPrice, setAppliedPrice] = useState({ mode: "", min: "", max: "" });
  const appliedPriceLabel = appliedPrice.mode === "below" ? `小于${appliedPrice.max}`
    : appliedPrice.mode === "above" ? `大于${appliedPrice.min}`
    : appliedPrice.mode === "between" ? `${appliedPrice.min}～${appliedPrice.max}（含端点）` : "不限价格";
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  useEffect(() => {
    if (!globalQuery.text) return;
    setQ(globalQuery.text); setPage(1); setManufacturer(""); setPriceStatus("all");
    setPriceMode(""); setPriceMin(""); setPriceMax(""); setAppliedPrice({ mode: "", min: "", max: "" });
    setSelected({}); setBatchResults([]);
  }, [globalQuery.version]);
  const filters: Record<string, string> = { q: q.trim(), sort, price_status: priceStatus };
  if (manufacturer) filters.manufacturer = manufacturer;
  if (appliedPrice.mode) { filters.price_mode = appliedPrice.mode; if (appliedPrice.mode !== "below") filters.price_min = appliedPrice.min; if (appliedPrice.mode !== "above") filters.price_max = appliedPrice.max; }
  function changePrice(mode: string, min: string, max: string) {
    setPriceMode(mode); setPriceMin(min); setPriceMax(max); clearForFilter();
    if (validPriceFilter(mode, min, max)) setAppliedPrice({ mode, min, max });
  }
  function resetFilters() {
    setQ(""); setManufacturer(""); setSort("updated_desc"); setPriceStatus("all");
    setPriceMode(""); setPriceMin(""); setPriceMax(""); setAppliedPrice({ mode: "", min: "", max: "" }); clearForFilter();
  }
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
    const risk = sensitiveText(text) || detail.sources?.some(source => typeof source.source_company === 'string' && text.includes(source.source_company));
    if (!window.confirm(risk ? "资料可能包含采购成本或来源公司，请确认已全文核对客户可见内容，再按原文复制。" : "请确认已全文核对客户可见内容，可复制给客户。")) return;
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
  }, [q, manufacturer, sort, page, reload, priceStatus, appliedPrice]);
  function refresh() { saved.current = true; setNotice("操作已完成"); setReload(value => value + 1); }
  async function openProduct(id: number, edit: boolean) {
    detailOpener.current = document.activeElement as HTMLElement | null;
    setDetailBusy(true); setError(null);
    try { const product = await api<LibraryProduct>(`/products/${id}`); if (edit) setEditor(product); else { setDetail(product as ProductDetail); setCopyStatus(null); } }
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
    <header className="page-header"><div><h1>产品库</h1><p className="page-description">集中管理厂家资料，快速检索产品与制作客户报价。</p></div><div className="library-actions"><button className="primary-button" onClick={() => setEditor("new")}>手动新增</button><button className="secondary-button" onClick={() => setImporting(true)}>批量导入</button><button className="secondary-button library-quote-entry" onClick={() => setQuoting(true)}>客户报价 Excel</button></div></header>
    {notice && <p role="status" className="feedback feedback-success">{notice}</p>}{error && <p role="alert" className="feedback feedback-server-error">{error}</p>}
    <section className="table-card">
      <div className="library-toolbar"><label className="library-search">关键词<input aria-label="产品库关键词" maxLength={200} placeholder="型号、名称、参数、卖点、厂家" value={q} onChange={event => { setQ(event.target.value); clearForFilter(); }} /></label><label>厂家筛选<select value={manufacturer} onChange={event => { setManufacturer(event.target.value); clearForFilter(); }}><option value="">全部厂家</option>{manufacturers.map(name => <option key={name}>{name}</option>)}</select></label><label>排序<select aria-label="排序" value={sort} onChange={event => { setSort(event.target.value); clearForFilter(); }}><option value="updated_desc">最近更新</option><option value="price_asc">批发价从低到高</option><option value="price_desc">批发价从高到低</option></select></label><label>报价状态<select aria-label="报价状态" value={priceStatus} onChange={event => { setPriceStatus(event.target.value); clearForFilter(); }}><option value="all">全部报价状态</option><option value="quoted">有报价</option><option value="unquoted">未报价</option></select></label><div className="library-price-filter"><label>价格条件<select aria-label="价格条件" value={priceMode} onChange={event => { changePrice(event.target.value, "", ""); }}><option value="">不限价格</option><option value="below">小于</option><option value="above">大于</option><option value="between">指定区间（含端点）</option></select></label>
      {priceMode && priceMode !== "below" && <label>最低价<input aria-label="最低价" inputMode="decimal" value={priceMin} onChange={event => { changePrice(priceMode, event.target.value, priceMax); }} /></label>}
      {priceMode && priceMode !== "above" && <label>最高价<input aria-label="最高价" inputMode="decimal" value={priceMax} onChange={event => { changePrice(priceMode, priceMin, event.target.value); }} /></label>}
      </div><div className="library-filter-actions"><button className="secondary-button" onClick={resetFilters}>清空筛选</button><button className="secondary-button" onClick={() => { setSelected({}); setBatchResults([]); setReload(value => value + 1); }}>刷新</button></div></div>
      {!validPriceFilter(priceMode, priceMin, priceMax) && <p role="status" className="library-price-notice">价格条件尚未生效，请输入完整有效的金额和范围。仍使用上次有效条件：{appliedPriceLabel}；列表和“当前筛选全部结果”报价均按此条件。</p>}
      <div className={`library-selection${Object.keys(selected).length ? " has-selection" : ""}`}><span role="status">跨页已选 {Object.keys(selected).length} 款</span><button className="text-button" disabled={!Object.keys(selected).length} onClick={() => { setSelected({}); setBatchResults([]); }}>清空选择</button><button className="danger-button" disabled={!Object.keys(selected).length} onClick={() => { setBatchConfirm(true); setDeleteError(null); }}>批量删除</button></div>
      {batchResults.filter(row => row.outcome !== "deleted").map(row => <p role="status" key={row.id}>产品 #{row.id}：{row.outcome === "missing" ? "已不存在" : "版本已变化"}，请刷新后重新选择</p>)}
      {status === "loading" && <p role="status" className="state-panel">正在加载产品…</p>}
      {status === "error" && <div className="state-panel state-error"><p>产品列表加载失败</p><button className="secondary-button" onClick={() => setReload(value => value + 1)}>重试</button></div>}
      {status === "ready" && data && <>{data.items.length === 0 ? <div className="state-panel"><h2>没有符合条件的产品</h2><p>调整搜索和筛选条件，或通过手动新增、批量导入建立产品资料。</p></div> : <div className="table-scroll"><table className="library-table"><thead><tr><th><input aria-label="选择本页" type="checkbox" ref={node => { if (node) node.indeterminate = data.items.some(item => selected[item.id]) && !data.items.every(item => selected[item.id]); }} checked={!!data.items.length && data.items.every(item => selected[item.id])} onChange={event => { const checked = event.target.checked; setSelected(current => { const next = { ...current }; for (const item of data.items) { if (checked) { if (!next[item.id]) next[item.id] = { id: item.id, version: item.version }; } else delete next[item.id]; } return next; }); }} /></th><th>资料来源公司</th><th>型号</th><th>名称</th><th>批发价</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{data.items.map(product => <tr key={product.id}><td><input aria-label={`选择产品 ${product.id}`} type="checkbox" checked={!!selected[product.id]} onChange={event => toggle(product, event.target.checked)} /></td><td>{product.source_companies?.join("、") || product.manufacturer_name}</td><td>{display(product.model)}</td><td>{product.name}{q.trim() && <small className="library-match">{searchSummary(product, q)}</small>}</td><td className={`library-price${product.wholesale_price == null ? " library-price-unknown" : ""}`}>{product.wholesale_price == null ? (product.price_state === "multiple" ? "多价格 / 需选择" : "未提供") : `¥${product.wholesale_price}`}</td><td className="library-updated">{new Date(product.updated_at).toLocaleString()}</td><td><div className="library-actions"><button className="detail-button" disabled={detailBusy} onClick={() => void openProduct(product.id, false)}>查看</button><button className="detail-button" disabled={detailBusy} onClick={() => void openProduct(product.id, true)}>编辑</button><button className="text-button" onClick={() => { setDeleteError(null); setDeleting(product); }}>删除</button></div></td></tr>)}</tbody></table></div>}
        <PaginationBar total={data.total} itemLabel="款产品" pageSize={20} page={page} totalPages={Math.max(1, Math.ceil(data.total / 20))} onPrevious={() => setPage(page - 1)} onNext={() => setPage(page + 1)} previousDisabled={page === 1} nextDisabled={page * 20 >= data.total} /></>}
    </section>
    {detailBusy && <p role="status">正在加载产品详情…</p>}
    {editor && <ProductEditor product={editor === "new" ? null : editor} returnFocus={editor === "new" ? undefined : detailOpener.current} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); refresh(); }} />}
    {detail && <LibraryDialog side title="产品详情" returnFocus={detailOpener.current} onClose={() => setDetail(null)}>
      <div className="library-detail-identity"><p>首录资料公司（兼容字段）：{detail.manufacturer_name}</p><h3>{detail.name}</h3><span>{display(detail.model)}</span></div>
      <section className="library-detail-section"><h3>客户产品资料</h3><p className="library-hint">完整资料仅复制型号、名称、参数和卖点。</p><div className="library-actions library-copy-actions"><button className="secondary-button" onClick={() => void copyProduct("parameters")}>复制参数</button><button className="secondary-button" onClick={() => void copyProduct("selling_points")}>复制卖点</button><button className="primary-button" onClick={() => void copyProduct("full")}>复制完整资料</button></div>{copyStatus && <p role="status" className="library-copy-status">{copyStatus}</p>}
      <dl className="library-details">{(["parameters", "selling_points"] as const).map(key => <div key={key}><dt>{labels[key]}</dt><dd>{display(detail[key])}</dd></div>)}</dl></section>
      <section className="library-detail-section"><h3>内部价格信息</h3><p className="library-hint">以下字段不包含在完整资料复制和客户 Excel 中。</p><dl className="library-details library-details-price">{(["wholesale_price", "price_note"] as const).map(key => <div key={key}><dt>{labels[key]}</dt><dd>{key === "wholesale_price" && detail[key] != null ? `¥${detail[key]}` : display(detail[key])}</dd></div>)}</dl></section>
      <ProductLibraryDetails product={detail} onChanged={next => { setDetail(next); refresh(); }} />
      <p className="library-hint">创建：{new Date(detail.created_at).toLocaleString()}<br />更新：{new Date(detail.updated_at).toLocaleString()}</p>
    </LibraryDialog>}
    {deleting && <LibraryDialog title="永久删除产品" busy={busy} onClose={() => setDeleting(null)}><p>厂家：{deleting.manufacturer_name}</p><p>型号：{display(deleting.model)}</p><p>名称：{deleting.name}</p><p>此产品将永久删除，无法恢复。</p>{deleteError && <p role="alert">{deleteError}</p>}<div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => setDeleting(null)}>取消</button><button className="danger-button" disabled={busy} onClick={() => void remove()}>确认删除</button></div></LibraryDialog>}
    {batchConfirm && <LibraryDialog title="批量永久删除" busy={busy} onClose={() => setBatchConfirm(false)}><p>将永久删除已选择的 {Object.keys(selected).length} 款产品，产品资料不可恢复。版本变化或已不存在的项将跳过。</p>{deleteError && <p role="alert">{deleteError}</p>}<div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => setBatchConfirm(false)}>取消</button><button className="danger-button" disabled={busy} onClick={() => void batchRemove()}>确定删除</button></div></LibraryDialog>}
    {quoting && <ProductQuotation selected={Object.values(selected)} filters={filters} onClose={() => setQuoting(false)} />}
    {importing && <ImportDialog onClose={() => setImporting(false)} onSaved={refresh} />}
  </div>;
}

export function prioritizedRows(rows: PreviewRow[]) {
  const priority = { invalid: 0, duplicate: 1, new: 2 };
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

export function validPriceFilter(mode: string, min: string, max: string) {
  const amount = (value: string) => /^[0-9]+(?:\.[0-9]{1,2})?$/.test(value) && Number(value) <= 999999999.99;
  return !mode || (mode === "below" ? amount(max) : mode === "above" ? amount(min) : amount(min) && amount(max) && Number(min) <= Number(max));
}
