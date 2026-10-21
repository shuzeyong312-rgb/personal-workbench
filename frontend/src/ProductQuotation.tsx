import { useState } from "react";
import { api, json, LibraryDialog, type LibraryProduct } from "./ProductLibrary";

type Rules = { markup_mode: string; markup_value: string; tax_mode: string; tax_value: string; freight_mode: string; freight_value: string; rounding: string };
type Item = { id: number; version: number };
type QuoteRow = Item & { model: string | null; name: string; parameters: string | null; selling_points: string | null; original_price: string | null; final_price: string | null; automatic_price?: string | null; risks: string[]; text_risks: { field: string; word: string; snippet: string }[]; error: string | null; manual: boolean };
type Preview = { items: Item[]; rules: Rules; digest: string; rows: QuoteRow[]; moq: number; note: string; terms: string; note_risks: { word: string; snippet: string }[] };
const defaults: Rules = { markup_mode: "none", markup_value: "0.00", tax_mode: "excluded", tax_value: "0.00", freight_mode: "separate", freight_value: "0.00", rounding: "cents" };
const customerFieldLabels: Record<string, string> = { model: "产品型号", name: "产品名称", parameters: "产品参数", selling_points: "产品卖点" };

export function ProductQuotation({ selected, filters, onClose }: { selected: Item[]; filters: Record<string, string>; onClose: () => void }) {
  const [moq, setMoq] = useState("1");
  const [note, setNote] = useState("");
  const [confirmedNote, setConfirmedNote] = useState(false);
  const [configOpen, setConfigOpen] = useState(true);
  const [scope, setScope] = useState(selected.length ? "selected" : "filtered");
  const [selection, setSelection] = useState(selected);
  const [rules, setRules] = useState(defaults);
  const [includeUnquoted, setIncludeUnquoted] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState<number[]>([]);
  const [allText, setAllText] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [affected, setAffected] = useState<Item[]>([]);
  const [valid, setValid] = useState(false);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  function invalidate() { setValid(false); setConfirmed([]); setAllText(false); setConfirmedNote(false); setError(null); setDownloaded(false); }
  function changeRules(patch: Partial<Rules>) { setRules(current => ({ ...current, ...patch })); invalidate(); }
  async function calculate() {
    if (!/^[0-9]+$/.test(moq) || Number(moq) < 1 || Number(moq) > 999999999) { setError("MOQ 必须为1～999999999的整数"); return; }
    setBusy(true); setError(null); setValid(false); setDownloaded(false); setConfirmed([]); setAllText(false); setConfirmedNote(false);
    try {
      let items = preview?.items ?? selection;
      if (affected.length) {
        const refreshed = await Promise.all(affected.map(async item => {
          try { const product = await api<LibraryProduct>(`/products/${item.id}`); return { id: product.id, version: product.version }; }
          catch (caught) { if ((caught as { code?: string }).code === "product_not_found") return null; throw caught; }
        }));
        const replacements = new Map(refreshed.filter((item): item is Item => item !== null).map(item => [item.id, item]));
        items = items.flatMap(item => affected.some(row => row.id === item.id) ? replacements.has(item.id) ? [replacements.get(item.id)!] : [] : [item]);
        if (scope === "selected") setSelection(items);
      }
      const next = await api<Preview>("/customer-quotations/preview", json("POST", { scope: preview ? "selected" : scope, items, filters, rules, include_unquoted: includeUnquoted, overrides, moq: Number(moq), note }));
      setPreview(next); setMoq(String(next.moq)); setNote(next.note); setConfirmedNote(false); setConfigOpen(false); setRules(next.rules); setConfirmed([]); setAllText(false); setValid(true); setAffected([]); setPage(1);
    } catch (caught) { setError((caught as Error).message); const changed = (caught as { items?: Item[] }).items; if (changed) setAffected(changed); }
    finally { setBusy(false); }
  }
  async function download() {
    if (!preview || !valid) return;
    setBusy(true); setError(null); setDownloaded(false);
    try {
      const response = await fetch("/api/product-library/customer-quotations/export", json("POST", { items: preview.items, rules: preview.rules, digest: preview.digest, overrides: Object.fromEntries(Object.entries(overrides).filter(([id]) => preview.items.some(item => String(item.id) === id))), confirmed_risk_ids: confirmed, confirmed_all_text: allText, moq: preview.moq, note: preview.note, confirmed_note: confirmedNote }));
      if (!response.ok) {
        const failure = await response.json();
        if (failure.items) setAffected(failure.items);
        setValid(false); setConfirmed([]); setAllText(false); setConfirmedNote(false);
        throw new Error(failure.message ?? "导出失败，请重新预览");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "客户报价.xlsx"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloaded(true);
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  const filteredRows = preview?.rows.filter(row => `${row.model ?? ""} ${row.name}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (!riskFilter || (riskFilter === "error" ? !!row.error : riskFilter === "manual" ? overrides[row.id] !== undefined : riskFilter === "pending" ? !valid || row.text_risks.length > 0 && !confirmed.includes(row.id) : row.risks.length > 0 || row.text_risks.length > 0))) ?? [];
  const visiblePage = Math.min(page, Math.max(1, Math.ceil(filteredRows.length / 20)));
  const ready = valid && preview && preview.rows.length > 0 && !preview.rows.some(row => row.error) && allText && (!preview.note_risks?.length || confirmedNote) && preview.rows.every(row => !row.text_risks.length || confirmed.includes(row.id));
  return <LibraryDialog wide title="客户报价 Excel" busy={busy} onClose={onClose}>
    <ol className="library-steps" aria-label="报价进度"><li aria-current={!preview ? "step" : undefined}><span>1</span>配置报价</li><li aria-current={preview && !ready ? "step" : undefined}><span>2</span>预览与核查</li><li aria-current={ready ? "step" : undefined}><span>3</span>下载 Excel</li></ol>
    <p className="library-intro">本次报价独立计算，不修改产品库中的原始价格。</p>
    <details className="quotation-config" open={configOpen} onToggle={event => setConfigOpen(event.currentTarget.open)}><summary>报价配置{preview && ` · ${preview.rows.length} 款 · MOQ ${moq}`}</summary><div className="library-form quotation-rules"><fieldset className="library-fieldset"><legend>产品范围</legend><div className="library-field-grid"><label>导出范围<select value={scope} disabled={busy} onChange={event => { setScope(event.target.value); setPreview(null); setAffected([]); invalidate(); }}><option value="selected" disabled={!selected.length}>已选产品（{selected.length}）</option><option value="filtered">当前筛选全部结果</option><option value="all">全部产品</option></select></label>
      <label className="library-check"><input type="checkbox" disabled={busy} checked={includeUnquoted} onChange={event => { setIncludeUnquoted(event.target.checked); setPreview(null); setAffected([]); invalidate(); }} />保留未报价产品（默认排除）</label></div></fieldset>
      <fieldset className="library-fieldset"><legend>定价与取整</legend><div className="library-field-grid"><label>加价方式<select value={rules.markup_mode} disabled={busy} onChange={event => changeRules({ markup_mode: event.target.value })}><option value="none">不加价</option><option value="percent">比例加价</option><option value="fixed">固定金额加价</option></select></label>
      {rules.markup_mode !== "none" && <label>{rules.markup_mode === "percent" ? "加价百分点（10表示10%）" : "每件加价（元）"}<input inputMode="decimal" disabled={busy} value={rules.markup_value} onChange={event => changeRules({ markup_value: event.target.value })} /></label>}
      <label>最终取整<select value={rules.rounding} disabled={busy} onChange={event => changeRules({ rounding: event.target.value })}><option value="cents">两位小数（四舍五入）</option><option value="integer">整数元（向上取整）</option></select></label></div></fieldset>
      <fieldset className="library-fieldset"><legend>税费与运费口径</legend><div className="library-field-grid"><label>税费/开票口径<select value={rules.tax_mode} disabled={busy} onChange={event => changeRules({ tax_mode: event.target.value })}><option value="excluded">不含税</option><option value="included">报价已含税</option><option value="adjust">按指定开票报价调整比例加价</option></select></label>
      {rules.tax_mode === "adjust" && <label>开票报价调整百分点<input inputMode="decimal" disabled={busy} value={rules.tax_value} onChange={event => changeRules({ tax_value: event.target.value })} /></label>}
      <label>运费口径<select value={rules.freight_mode} disabled={busy} onChange={event => changeRules({ freight_mode: event.target.value })}><option value="separate">运费另计</option><option value="included">报价已含运费</option><option value="fixed">每件固定增加运费</option></select></label>
      {rules.freight_mode === "fixed" && <label>单件运费（元）<input inputMode="decimal" disabled={busy} value={rules.freight_value} onChange={event => changeRules({ freight_value: event.target.value })} /></label>}
      </div><p className="library-hint">开票调整是本次商业报价条件；单件运费不代表整单实际物流费用。</p></fieldset>
      <fieldset className="library-fieldset"><legend>客户报价条件</legend><div className="library-field-grid"><label>统一 MOQ（起订量）<input inputMode="numeric" disabled={busy} value={moq} onChange={event => { setMoq(event.target.value); invalidate(); }} aria-describedby="quotation-moq-help" /></label><p id="quotation-moq-help" className="library-hint">本次每款产品的起订量，不影响单价计算，不保存到产品库。</p></div>
      <label htmlFor="quotation-note">报价说明</label><textarea id="quotation-note" rows={4} maxLength={2000} disabled={busy} value={note} onChange={event => { setNote(event.target.value); invalidate(); }} aria-describedby="quotation-note-help" /><p id="quotation-note-help" className="library-hint">{note.length} / 2000 字符，可留空。请自行写明税费、运费等条件；按此原文导出，不会自动补充。</p></fieldset>
    </div></details>
    {downloaded && <p role="status" className="library-copy-status">客户 Excel 已生成，下载已开始。</p>}
    {error && <p role="alert">{error}</p>}{affected.length > 0 && <p role="alert">需刷新并复核的产品：{affected.map(item => `#${item.id}`).join("、")}。重新生成预览会刷新版本并移除已不存在项。</p>}
    {!valid && <p role="status">请生成或重新核算报价预览，核对后再下载。人工输入仍保留。重新核算保持原产品集合；如需重新解析范围，请切换导出范围。</p>}
    {preview && <><h3 className="library-section-title">客户报价预览</h3><div className="quotation-summary"><strong>{preview.rows.length} 款产品 · 统一 MOQ {preview.moq}</strong><span>仅最终报价、MOQ 和客户资料导出给客户</span></div>
      <p className="library-hint">计算口径：{preview.terms}请核对下方报价说明与此口径是否一致。</p>
      <section className="quotation-note-preview" aria-label="客户报价说明预览"><strong>报价说明（按此原文导出）</strong><p className="library-text">{preview.note || "未填写，Excel 中留空"}</p>{preview.note_risks?.map((risk, index) => <p role="alert" key={index}>说明含敏感词「{risk.word}」：{risk.snippet}</p>)}{!!preview.note_risks?.length && <label className="library-check"><input type="checkbox" disabled={busy || !valid} checked={confirmedNote} onChange={event => setConfirmedNote(event.target.checked)} />已核查报价说明中的敏感文本</label>}</section>
      <p className="library-hint">原始报价仅供内部核价，不导出。未命中风险词也不能保证文本安全，请展开核对客户资料。</p>
      <div className="library-review-toolbar"><label>搜索报价产品<input value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} /></label><label>报价核查状态<select aria-label="报价核查状态" value={riskFilter} onChange={event => { setRiskFilter(event.target.value); setPage(1); }}><option value="">全部产品</option><option value="risk">存在风险</option><option value="error">报价错误</option><option value="manual">人工改价</option><option value="pending">待核算或待核查</option></select></label><span role="status">匹配 {filteredRows.length} 款</span></div>
      <div className="table-scroll quotation-preview" role="region" aria-label="报价明细" tabIndex={0}><table className="library-audit-table quotation-audit-table"><thead><tr><th>型号 / 名称</th><th>原始报价<small>仅内部，不导出</small></th><th>最终报价<small>元 / 件，可直接修改</small></th></tr></thead>{filteredRows.slice((visiblePage - 1) * 20, visiblePage * 20).map(row => <tbody key={row.id}>
        <tr><td><strong>{row.model ?? "未提供型号"}</strong><p>{row.name}</p><button className="text-button" aria-expanded={expanded === row.id} onClick={() => setExpanded(expanded === row.id ? null : row.id)}>{expanded === row.id ? "收起客户资料" : "查看客户可见参数和卖点"}</button>
          {row.risks.map(risk => <small className="library-row-error" key={risk}>{risk}</small>)}{row.text_risks.length > 0 && <small className="library-row-error">客户文本{confirmed.includes(row.id) ? "已核查" : "待核查"}</small>}{row.error && <p role="alert">{row.error}</p>}</td>
        <td className="library-money">{row.original_price ?? "未提供"}</td>
        <td><label className="library-visually-hidden" htmlFor={`quote-price-${row.id}`}>最终报价 {row.id}</label><input id={`quote-price-${row.id}`} inputMode="decimal" disabled={busy} value={(valid ? row.final_price : overrides[row.id] ?? row.final_price) ?? ""} placeholder="待报价" onChange={event => { const value = event.target.value; setOverrides(current => ({ ...current, [row.id]: value })); invalidate(); }} />
          <small className="library-match" aria-live="polite">{!valid ? "待重新核算" : row.manual ? "已人工改价" : "按规则计算"}</small><button className="text-button" disabled={busy || overrides[row.id] === undefined} onClick={() => { setOverrides(current => { const next = { ...current }; delete next[row.id]; return next; }); invalidate(); }}>恢复自动计算</button></td></tr>
        {expanded === row.id && <tr><td colSpan={3}><div className="library-row-detail"><p>产品型号：{row.model ?? "未提供型号"} · 产品名称：{row.name}</p><p className="library-text">{row.parameters ?? "未提供参数"}</p><p className="library-text">{row.selling_points ?? "未提供卖点"}</p><p>最终报价：{valid ? row.final_price ?? "待报价" : "待重新核算"} · MOQ {preview.moq}</p>{row.text_risks.map((risk, index) => <p role="alert" key={index}>{customerFieldLabels[risk.field] ?? risk.field} · {risk.word}：{risk.snippet}</p>)}{row.text_risks.length > 0 && <label className="library-check"><input type="checkbox" disabled={busy || !valid} checked={confirmed.includes(row.id)} onChange={event => setConfirmed(current => event.target.checked ? [...current, row.id] : current.filter(id => id !== row.id))} />已逐项核查此产品客户文本 · {row.name}</label>}</div></td></tr>}
      </tbody>)}</table>{!filteredRows.length && <p className="state-panel">没有匹配的报价产品</p>}</div>
      <div className="pagination-bar"><button disabled={visiblePage === 1 || busy} onClick={() => setPage(visiblePage - 1)}>上一页</button><span>第 {visiblePage} / {Math.max(1, Math.ceil(filteredRows.length / 20))} 页</span><button disabled={visiblePage * 20 >= filteredRows.length || busy} onClick={() => setPage(visiblePage + 1)}>下一页</button></div>
      <label className="library-review-check"><input type="checkbox" disabled={busy || !valid} checked={allText} onChange={event => setAllText(event.target.checked)} />已核对全部客户可见产品文本与报价说明</label>
    </>}
    <div className="dialog-actions library-sticky-actions"><span>{ready ? "已完成文本核查，可下载客户报价" : preview ? "核对报价与全部客户文本后下载" : "配置完成后生成预览"}</span><button className="secondary-button" disabled={busy || scope === "selected" && !selected.length} onClick={() => void calculate()}>{busy ? "处理中…" : preview ? "重新核算报价" : "生成报价预览"}</button><button className="primary-button" disabled={busy || !ready} onClick={() => void download()}>下载客户 Excel</button></div>
  </LibraryDialog>;
}
