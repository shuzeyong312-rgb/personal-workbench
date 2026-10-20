import { useState } from "react";
import { api, json, LibraryDialog, type LibraryProduct } from "./ProductLibrary";

type Rules = { markup_mode: string; markup_value: string; tax_mode: string; tax_value: string; freight_mode: string; freight_value: string; rounding: string };
type Item = { id: number; version: number };
type QuoteRow = Item & { model: string | null; name: string; parameters: string | null; selling_points: string | null; final_price: string | null; risks: string[]; text_risks: { field: string; word: string; snippet: string }[]; error: string | null; manual: boolean };
type Preview = { items: Item[]; rules: Rules; digest: string; rows: QuoteRow[]; note: string };
const defaults: Rules = { markup_mode: "none", markup_value: "0.00", tax_mode: "excluded", tax_value: "0.00", freight_mode: "separate", freight_value: "0.00", rounding: "cents" };

export function ProductQuotation({ selected, filters, onClose }: { selected: Item[]; filters: Record<string, string>; onClose: () => void }) {
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
  function invalidate() { setValid(false); setConfirmed([]); setAllText(false); setError(null); }
  function changeRules(patch: Partial<Rules>) { setRules(current => ({ ...current, ...patch })); invalidate(); }
  async function calculate() {
    setBusy(true); setError(null); setValid(false);
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
      const next = await api<Preview>("/customer-quotations/preview", json("POST", { scope: preview ? "selected" : scope, items, filters, rules, include_unquoted: includeUnquoted, overrides }));
      setPreview(next); setRules(next.rules); setConfirmed([]); setAllText(false); setValid(true); setAffected([]); setPage(1);
    } catch (caught) { setError((caught as Error).message); const changed = (caught as { items?: Item[] }).items; if (changed) setAffected(changed); }
    finally { setBusy(false); }
  }
  async function download() {
    if (!preview || !valid) return;
    setBusy(true); setError(null);
    try {
      const response = await fetch("/api/product-library/customer-quotations/export", json("POST", { items: preview.items, rules: preview.rules, digest: preview.digest, overrides: Object.fromEntries(Object.entries(overrides).filter(([id]) => preview.items.some(item => String(item.id) === id))), confirmed_risk_ids: confirmed, confirmed_all_text: allText }));
      if (!response.ok) {
        const failure = await response.json();
        if (failure.items) setAffected(failure.items);
        setValid(false); setConfirmed([]); setAllText(false);
        throw new Error(failure.message ?? "导出失败，请重新预览");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "客户报价.xlsx"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  const ready = valid && preview && preview.rows.length > 0 && !preview.rows.some(row => row.error) && allText && preview.rows.every(row => !row.text_risks.length || confirmed.includes(row.id));
  return <LibraryDialog title="客户报价 Excel" busy={busy} onClose={onClose}>
    <div className="library-form quotation-rules"><label>导出范围<select value={scope} disabled={busy} onChange={event => { setScope(event.target.value); setPreview(null); setAffected([]); invalidate(); }}><option value="selected" disabled={!selected.length}>已选产品（{selected.length}）</option><option value="filtered">当前筛选全部结果</option><option value="all">全部产品</option></select></label>
      <label>加价方式<select value={rules.markup_mode} disabled={busy} onChange={event => changeRules({ markup_mode: event.target.value })}><option value="none">不加价</option><option value="percent">比例加价</option><option value="fixed">固定金额加价</option></select></label>
      {rules.markup_mode !== "none" && <label>{rules.markup_mode === "percent" ? "加价百分点（10表示10%）" : "每件加价（元）"}<input inputMode="decimal" disabled={busy} value={rules.markup_value} onChange={event => changeRules({ markup_value: event.target.value })} /></label>}
      <label>税费/开票口径<select value={rules.tax_mode} disabled={busy} onChange={event => changeRules({ tax_mode: event.target.value })}><option value="excluded">不含税</option><option value="included">报价已含税</option><option value="adjust">按指定开票报价调整比例加价</option></select></label>
      {rules.tax_mode === "adjust" && <label>开票报价调整百分点<input inputMode="decimal" disabled={busy} value={rules.tax_value} onChange={event => changeRules({ tax_value: event.target.value })} /></label>}
      <label>运费口径<select value={rules.freight_mode} disabled={busy} onChange={event => changeRules({ freight_mode: event.target.value })}><option value="separate">运费另计</option><option value="included">报价已含运费</option><option value="fixed">每件固定增加运费</option></select></label>
      {rules.freight_mode === "fixed" && <label>单件运费（元）<input inputMode="decimal" disabled={busy} value={rules.freight_value} onChange={event => changeRules({ freight_value: event.target.value })} /></label>}
      <label>最终取整<select value={rules.rounding} disabled={busy} onChange={event => changeRules({ rounding: event.target.value })}><option value="cents">两位小数（四舍五入）</option><option value="integer">整数元（向上取整）</option></select></label>
      <label className="library-check"><input type="checkbox" disabled={busy} checked={includeUnquoted} onChange={event => { setIncludeUnquoted(event.target.checked); setPreview(null); setAffected([]); invalidate(); }} />保留未报价产品（默认排除）</label>
    </div>
    {error && <p role="alert">{error}</p>}{affected.length > 0 && <p role="alert">需刷新并复核的产品：{affected.map(item => `#${item.id}`).join("、")}。重新生成预览会刷新版本并移除已不存在项。</p>}
    {!valid && <p role="status">请生成或重新核算报价预览，核对后再下载。人工输入仍保留。重新核算保持原产品集合；如需重新解析范围，请切换导出范围。</p>}
    {preview && <><p>共 {preview.rows.length} 款 · {preview.note}</p><p>未命中风险词也不能保证文本安全，请核对全部客户可见资料。</p>
      <div className="library-preview quotation-preview">{preview.rows.slice((page - 1) * 20, page * 20).map(row => <article className="library-preview-row" key={row.id}>
        <h3>{row.model ?? "未提供型号"} · {row.name}</h3><details><summary>查看客户可见参数和卖点</summary><p className="library-text">{row.parameters ?? "未提供参数"}</p><p className="library-text">{row.selling_points ?? "未提供卖点"}</p></details>
        <p>最终报价：{row.final_price ?? "待报价"} · {row.manual ? "人工报价" : "自动计算"}{row.risks.length > 0 && ` · ${row.risks.join(" · ")}`}</p>{row.error && <p role="alert">{row.error}</p>}
        <label>人工最终报价 · {row.name}<input aria-label={`人工报价 ${row.id}`} inputMode="decimal" disabled={busy} value={overrides[row.id] ?? ""} placeholder="留空使用自动计算" onChange={event => { const value = event.target.value; setOverrides(current => { const next = { ...current }; if (value) next[row.id] = value; else delete next[row.id]; return next; }); invalidate(); }} /></label>
        <button className="text-button" disabled={busy || overrides[row.id] === undefined} onClick={() => { setOverrides(current => { const next = { ...current }; delete next[row.id]; return next; }); invalidate(); }}>恢复自动计算</button>
        {row.text_risks.map((risk, index) => <p role="alert" key={index}>{risk.field} · {risk.word}：{risk.snippet}</p>)}
        {row.text_risks.length > 0 && <label><input type="checkbox" disabled={busy || !valid} checked={confirmed.includes(row.id)} onChange={event => setConfirmed(current => event.target.checked ? [...current, row.id] : current.filter(id => id !== row.id))} />已逐项核查此产品客户文本 · {row.name}</label>}
      </article>)}</div>
      <div className="pagination-bar"><button disabled={page === 1 || busy} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} / {Math.max(1, Math.ceil(preview.rows.length / 20))} 页</span><button disabled={page * 20 >= preview.rows.length || busy} onClick={() => setPage(page + 1)}>下一页</button></div>
      <label><input type="checkbox" disabled={busy || !valid} checked={allText} onChange={event => setAllText(event.target.checked)} />已核对全部客户可见产品文本</label>
    </>}
    <div className="dialog-actions library-sticky-actions"><button className="secondary-button" disabled={busy || scope === "selected" && !selected.length} onClick={() => void calculate()}>{busy ? "处理中…" : "生成报价预览"}</button><button className="primary-button" disabled={busy || !ready} onClick={() => void download()}>下载客户 Excel</button></div>
  </LibraryDialog>;
}
