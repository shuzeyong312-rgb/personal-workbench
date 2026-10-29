import { useState } from 'react';
import { fieldLabels } from './ProductLibraryDetails';
import { api, json, LibraryDialog } from './ProductLibrary';

type RowKey = { sheet: string; row_number: number; record_type: string; temp_id: string | null };
type Row = { row_key: RowKey; kind: string; product_ref: string; incoming: Record<string, unknown>; old: Record<string, unknown> | null; effective: Record<string, unknown>; errors: { message: string }[]; dependencies: RowKey[]; allowed_actions: string[]; default_action: string; target_id: number | null; target_version: number | null };
export type V2Preview = { template_version: 2; import_id: string; status: 'ready'; expires_at: string; attachment_warning: string; rows: Row[]; counts: Record<string, number> };
type Decision = { row_key: RowKey; action: string; target_id?: number; target_version?: number; set_default?: boolean };
type Result = { status: 'committed'; rows: { row_key: RowKey; target_id: number | null; outcome: string; reason_code: string }[]; counts: Record<string, Record<string, number>> };
const labels: Record<string, string> = { insert: '新增', update_main: '更新主资料', use_existing: '保留主资料，处理关联', append_source: '仅追加来源与价格', skip_product: '整组跳过', update: '确认更新', reuse: '复用已有记录', skip: '跳过', inserted: '已新增', updated: '已更新', reused: '已复用', skipped: '已跳过' };
const rowToken = (row: RowKey) => JSON.stringify(row);
const valueLabels: Record<string,string> = {unknown:'未知',included:'已含',excluded:'不含',extra:'另计',negotiable:'协商',quote:'报价',catalog:'目录',specification:'规格书',other:'其他',true:'是',false:'否'};
const show = (value: unknown) => value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : valueLabels[String(value)] ?? String(value);

export function V2ImportReview({ preview, onClose, onSaved }: { preview: V2Preview; onClose: () => void; onSaved: () => void }) {
  const [actions, setActions] = useState<Record<string, string>>({});
  const [defaults, setDefaults] = useState<Record<string, boolean>>({});
  const [attachments, setAttachments] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [retry, setRetry] = useState<{ decisions: Decision[]; confirmed_attachments_not_imported: boolean } | null>(null);
  const [sheet, setSheet] = useState('产品数据');
  const [page, setPage] = useState(1);
  const rows = preview.rows.filter(row => row.row_key.sheet === sheet);
  const locked = busy || uncertain || retry !== null || Date.parse(preview.expires_at) <= Date.now();
  async function lookup() {
    setBusy(true); setError(null);
    try {
      const next = await api<Result | V2Preview>(`/imports/${preview.import_id}`);
      setUncertain(false);
      if (next.status === 'committed') { setResult(next); onSaved(); }
      else setError('尚未提交，可按原决策重试。');
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  async function submit() {
    const payload = retry ?? { confirmed_attachments_not_imported: attachments, decisions: preview.rows.map(row => {
      const token = rowToken(row.row_key); const action = actions[token] ?? row.default_action;
      return { row_key: row.row_key, action, ...(['update_main', 'use_existing', 'append_source', 'update', 'reuse'].includes(action) && row.target_id !== null && row.target_version !== null ? { target_id: row.target_id, target_version: row.target_version } : {}), ...(defaults[token] !== undefined && action !== 'skip' ? { set_default: defaults[token] } : {}) };
    }) };
    setBusy(true); setError(null);
    try { const next = await api<Result>(`/imports/${preview.import_id}/confirm`, json('POST', payload)); setResult(next); setRetry(null); setUncertain(false); onSaved(); }
    catch (caught) { const failure = caught as Error & { uncertain?: boolean }; setError(failure.message); if (failure.uncertain) { setUncertain(true); setRetry(payload); } }
    finally { setBusy(false); }
  }
  function close() {
    if (uncertain) { setError('结果待确认，请先查询原导入结果。'); return; }
    if (!result && !window.confirm('关闭将放弃当前预览选择，确认关闭？')) return;
    onClose();
  }
  return <LibraryDialog wide review title={result ? 'V2 导入结果' : 'V2 导入 · 核对与决策'} busy={busy} onClose={close}>
    <p className="library-intro">主产品 {preview.counts.product} 款，逐表核对来源、规格、参数与价格。保留主资料仍可新增关联数据；整组跳过会同时跳过其关联行。</p>
    {error && <p role="alert">{error}</p>}
    <p className="library-row-error">{preview.attachment_warning}</p>
    {!result && <label className="library-check"><input type="checkbox" disabled={locked} checked={attachments} onChange={event => setAttachments(event.target.checked)} />已知晓图片和原始文件未保存，将自行保留原件</label>}
    <div className="library-review-toolbar"><label>工作表<select value={sheet} onChange={event => { setSheet(event.target.value); setPage(1); }}>{['产品数据', '资料索引', '规格款式', '参数明细', '价格明细'].map(name => <option key={name}>{name}</option>)}</select></label><span>{rows.length} 行</span></div>
    <div className="table-scroll"><table className="library-audit-table library-v2-audit"><thead><tr><th>行 / 产品</th><th>资料与差异</th><th>操作</th></tr></thead><tbody>{rows.slice((page - 1) * 20, page * 20).map(row => {
      const token = rowToken(row.row_key); const outcome = result?.rows.find(item => rowToken(item.row_key) === token);
      const action = actions[token] ?? row.default_action;
      return <tr key={token}><td>{row.row_key.sheet} · {row.row_key.row_number}<p>{row.row_key.temp_id ?? '参数'} / {row.product_ref}</p>{row.target_id != null && <small>已有记录 #{row.target_id} · v{row.target_version}</small>}</td><td>
        {row.errors.map((item, index) => <p className="library-row-error" key={index}>{item.message}</p>)}
        <dl className="library-details">{Object.entries(row.incoming).filter(([, value]) => value != null).map(([field, value]) => <div key={field}><dt>{fieldLabels[field] ?? field}</dt><dd>{show(value)}{row.old && row.old[field] !== value && <small className="library-match">原值：{show(row.old[field])}；生效值：{show(row.kind === 'product' && action === 'update_main' && field !== 'wholesale_price' && value != null ? value : row.effective[field])}</small>}</dd></div>)}</dl>
        {row.dependencies.length > 1 && <p className="library-hint">依赖：{row.dependencies.slice(1).map(dep => `${dep.sheet} ${dep.temp_id}`).join('、')}；如不写入，请一并跳过依赖行。</p>}
      </td><td>{outcome ? labels[outcome.outcome] ?? outcome.outcome : <><label>行操作<select disabled={locked} value={action} onChange={event => setActions(current => ({ ...current, [token]: event.target.value }))}>{row.allowed_actions.map(value => <option key={value} value={value}>{labels[value] ?? value}</option>)}</select></label>
        {row.kind === 'prices' && action !== 'skip' && <label className="library-check"><input type="checkbox" disabled={locked} checked={defaults[token] ?? Boolean(row.old?.is_default_wholesale ?? (preview.rows.find(parent => parent.kind === 'product' && parent.product_ref === row.product_ref)?.default_action === 'insert' && row.incoming.is_default_wholesale))} onChange={event => setDefaults(current => ({ ...current, [token]: event.target.checked }))} />明确设为默认批发价</label>}</>}</td></tr>;
    })}</tbody></table></div>
    <div className="pagination-bar"><button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>{page} / {Math.max(1, Math.ceil(rows.length / 20))}</span><button disabled={page * 20 >= rows.length} onClick={() => setPage(page + 1)}>下一页</button></div>
    <div className="dialog-actions library-sticky-actions">{result ? <button className="primary-button" onClick={onClose}>完成</button> : <><button className="secondary-button" disabled={busy} onClick={() => void lookup()}>查询原导入结果</button><button className="primary-button" disabled={busy || uncertain || !attachments || Date.parse(preview.expires_at) <= Date.now()} onClick={() => void submit()}>{busy ? '处理中…' : retry ? '按原决策重试' : '确认导入'}</button></>}</div>
  </LibraryDialog>;
}
