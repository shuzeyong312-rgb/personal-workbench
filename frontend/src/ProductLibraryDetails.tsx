import { useState } from 'react';
import { api, json, type LibraryProduct } from './ProductLibrary';

export type Attribute = { group: string | null; name: string; value: string | null; unit: string | null; condition: string | null; source_id: number | null; source_excerpt: string | null; review_status: string };
export type DetailRecord = { id: number; version: number; [key: string]: unknown };
export type ProductDetail = LibraryProduct & { category?: string | null; structured_attributes?: Attribute[] | null; variants: DetailRecord[]; sources: DetailRecord[]; prices: DetailRecord[]; attachment_warning?: string };
export const fieldLabels: Record<string, string> = {
  category: '分类', model: '产品型号', name: '名称', parameters: '参数原文', selling_points: '卖点', price_note: '价格备注', wholesale_price: '默认批发价',
  variant_code: '规格编码', variant_name: '规格名称', color: '颜色/款式', structured_attributes: '参数明细', notes: '补充备注',
  source_company: '报价来源公司', claimed_manufacturer_name: '原件标注生产厂家', source_file_name: '原始文件名', source_page: '页码/工作表/区域', source_date: '原件日期', source_type: '资料类型', source_excerpt: '原文摘录',
  variant_id: '适用规格', source_id: '资料来源', price_type: '价格类型', price_channel: '渠道', amount_text: '金额', currency_code: '币种', price_unit: '计价单位', min_order_quantity: '起订量', min_order_unit: '起订单位', tax_mode: '税费口径', freight_mode: '运费口径', freight_amount_cents: '人民币运费（分）', customization_terms: '定制条件', terms_text: '价格条件原文', quote_date: '报价日期', is_default_wholesale: '默认批发价',
  group: '参数分组', value: '参数值', unit: '单位', condition: '适用条件', review_status: '核对状态',
};
const fields = {
  variants: ['variant_name', 'variant_code', 'color', 'notes'],
  sources: ['source_company', 'claimed_manufacturer_name', 'source_file_name', 'source_page', 'source_date', 'source_type', 'source_excerpt', 'notes'],
  prices: ['variant_id', 'source_id', 'price_type', 'price_channel', 'amount_text', 'currency_code', 'price_unit', 'min_order_quantity', 'min_order_unit', 'tax_mode', 'freight_mode', 'freight_amount_cents', 'customization_terms', 'terms_text', 'source_excerpt', 'quote_date', 'notes'],
};
const enums: Record<string, string[]> = { price_type: ['出厂价', '批发价', '一件代发价', '定制价', '平台控价', '建议零售价', '零售价', '其他'], tax_mode: ['unknown', 'included', 'excluded'], freight_mode: ['unknown', 'included', 'excluded', 'extra', 'negotiable'], source_type: ['quote', 'catalog', 'specification', 'other'] };
const values: Record<string, string> = { unknown: '未知', included: '已含', excluded: '不含', extra: '另计', negotiable: '协商', quote: '报价', catalog: '目录', specification: '规格书', other: '其他' };
const kinds = { variants: '规格款式', sources: '资料来源', prices: '价格明细' };
type Kind = keyof typeof kinds;
const visible = (value: unknown) => value == null || value === '' ? '—' : String(value);

function AttributeEditor({ items, sources, disabled, onChange }: { items: Attribute[]; sources: DetailRecord[]; disabled: boolean; onChange: (items: Attribute[]) => void }) {
  function patch(index: number, field: string, value: unknown) { onChange(items.map((item, n) => n === index ? { ...item, [field]: value } : item)); }
  return <><div className="library-attribute-list">{items.map((item, index) => <fieldset className="library-fieldset" key={index}><legend>参数 {index + 1} · {item.review_status === 'needs_review' ? '待核对' : '已确认'}</legend><div className="library-field-grid">{['group', 'name', 'value', 'unit', 'condition', 'source_excerpt'].map(field => <label key={field}>{fieldLabels[field]}{['value', 'source_excerpt'].includes(field) ? <textarea rows={2} disabled={disabled} value={String(item[field as keyof Attribute] ?? '')} onChange={event => patch(index, field, event.target.value || null)} /> : <input disabled={disabled} value={String(item[field as keyof Attribute] ?? '')} onChange={event => patch(index, field, event.target.value || null)} />}</label>)}<label>来源<select disabled={disabled} value={item.source_id ?? ''} onChange={event => patch(index, 'source_id', Number(event.target.value) || null)}><option value="">未知来源</option>{sources.map(source => <option key={source.id} value={source.id}>{visible(source.source_company)} · {visible(source.source_file_name)} #{source.id}</option>)}</select></label><label>核对状态<select disabled={disabled} value={item.review_status} onChange={event => patch(index, 'review_status', event.target.value)}><option value="confirmed">已确认</option><option value="needs_review">待核对</option></select></label></div><button type="button" className="text-button" disabled={disabled} onClick={() => onChange(items.filter((_, n) => n !== index))}>移除参数 {index + 1}</button></fieldset>)}</div><button type="button" className="secondary-button" disabled={disabled} onClick={() => onChange([...items, { group: null, name: '', value: null, unit: null, condition: null, source_id: null, source_excerpt: null, review_status: 'needs_review' }])}>添加参数</button></>;
}

export function ProductLibraryDetails({ product, onChanged }: { product: ProductDetail; onChanged: (product: ProductDetail) => void }) {
  const [editing, setEditing] = useState<{ kind: Kind; record: DetailRecord | null } | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [parameterDraft, setParameterDraft] = useState<Attribute[] | null>(null);
  const [category, setCategory] = useState(product.category ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [defaultCommand, setDefaultCommand] = useState<boolean | null>(null);
  async function reload() { const next = await api<ProductDetail>(`/products/${product.id}`); onChanged(next); }
  async function write(path: string, method: string, body: unknown) {
    setBusy(true); setError(null);
    try { await api(path, json(method, body)); await reload(); setEditing(null); setParameterDraft(null); }
    catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }
  function open(kind: Kind, record: DetailRecord | null) {
    setEditing({ kind, record }); setDefaultCommand(null); setError(null);
    setDraft(Object.fromEntries(fields[kind].map(field => [field, record?.[field] ?? ''])));
    if (kind === 'variants') setDraft(current => ({ ...current, structured_attributes: record?.structured_attributes ?? [] }));
  }
  function save() {
    if (!editing) return;
    const body = Object.fromEntries(Object.entries(draft).map(([field, value]) => [field, ['source_id', 'variant_id', 'freight_amount_cents'].includes(field) ? value === '' || value == null ? null : Number(value) : value === '' ? null : value]));
    void write(`/products/${product.id}/${editing.kind}${editing.record ? `/${editing.record.id}` : ''}`, editing.record ? 'PUT' : 'POST', { ...body, product_version: product.version, ...(editing.record ? { version: editing.record.version } : {}), ...(defaultCommand !== null ? { set_default: defaultCommand } : {}) });
  }
  return <>
    {error && <p role="alert">{error} <button className="text-button" disabled={busy} onClick={() => void reload()}>重新读取产品</button></p>}
    <section className="library-detail-section"><h3>分类与参数明细</h3>{parameterDraft === null ? <><p>分类：{visible(product.category)}</p><dl className="library-details">{(product.structured_attributes ?? []).map((item, index) => <div key={index}><dt>{item.group} / {item.name}</dt><dd>{visible(item.value)} {item.unit} {item.condition}<small className="library-match">{item.review_status === 'needs_review' ? '待核对 · ' : ''}{item.source_excerpt}</small></dd></div>)}</dl><button className="secondary-button" disabled={busy} onClick={() => { setParameterDraft(product.structured_attributes ?? []); setCategory(product.category ?? ''); }}>编辑分类与参数</button></> : <><label>产品分类<input disabled={busy} value={category} onChange={event => setCategory(event.target.value)} /></label><AttributeEditor items={parameterDraft} sources={product.sources ?? []} disabled={busy} onChange={setParameterDraft} /><div className="library-actions"><button className="primary-button" disabled={busy} onClick={() => { const { manufacturer_name, model, name, parameters, selling_points, wholesale_price, price_note, version } = product; void write(`/products/${product.id}`, 'PUT', { manufacturer_name, model, name, parameters, selling_points, wholesale_price, price_note, version, category: category || null, structured_attributes: parameterDraft }); }}>保存分类与参数</button><button className="secondary-button" disabled={busy} onClick={() => setParameterDraft(null)}>取消</button></div></>}</section>
    {(Object.keys(kinds) as Kind[]).map(kind => <section className="library-detail-section" key={kind}><div className="library-detail-heading"><h3>{kinds[kind]}</h3><button className="secondary-button" disabled={busy} onClick={() => open(kind, null)}>新增{kinds[kind]}</button></div>{!(product[kind] ?? []).length && <p className="library-hint">尚无{kinds[kind]}，未知资料保持留空。</p>}{(product[kind] ?? []).map(record => <details className="library-related-record" key={record.id}><summary>{kind === 'variants' ? `${visible(record.variant_name)} ${record.color ?? ''}` : kind === 'sources' ? `${visible(record.source_company)} · ${visible(record.source_file_name)}` : `${visible(record.price_type)} ${visible(record.amount_text)} ${visible(record.currency_code)} / ${visible(record.price_unit)}${record.is_default_wholesale ? ' · 默认批发价' : ''}`}</summary><dl className="library-details">{fields[kind].map(field => <div key={field}><dt>{fieldLabels[field]}</dt><dd>{values[String(record[field])] ?? visible(record[field])}</dd></div>)}</dl>{kind === 'variants' && Array.isArray(record.structured_attributes) && (record.structured_attributes as Attribute[]).map((item, i) => <p key={i}>{item.name}：{visible(item.value)} {item.unit} · {item.condition} · {item.review_status === 'needs_review' ? '待核对' : '已确认'}</p>)}<div className="library-actions"><button className="secondary-button" disabled={busy} onClick={() => open(kind, record)}>编辑</button><button className="text-button" disabled={busy} onClick={() => { if (window.confirm(`确认删除这条${kinds[kind]}？被价格或参数引用时需先处理依赖。`)) void write(`/products/${product.id}/${kind}/${record.id}`, 'DELETE', { product_version: product.version, version: record.version }); }}>删除</button></div></details>)}</section>)}
    {editing && <section className="library-detail-section" aria-label={`编辑${kinds[editing.kind]}`}><h3>{editing.record ? '编辑' : '新增'}{kinds[editing.kind]}</h3><div className="library-field-grid">{fields[editing.kind].map(field => <label key={field}>{fieldLabels[field]}{field === 'source_id' || field === 'variant_id' ? <select disabled={busy} value={String(draft[field] ?? '')} onChange={event => setDraft(current => ({ ...current, [field]: event.target.value }))}><option value="">{field === 'source_id' ? '请选择资料来源' : '产品级（全部规格）'}</option>{(field === 'source_id' ? product.sources : product.variants).map(record => <option key={record.id} value={record.id}>{String(record.source_company ?? record.variant_name ?? record.id)} · {String(record.source_file_name ?? record.color ?? '')}</option>)}</select> : enums[field] ? <select disabled={busy} value={String(draft[field] ?? '')} onChange={event => setDraft(current => ({ ...current, [field]: event.target.value }))}><option value="">未知 / 未填写</option>{enums[field].map(value => <option key={value} value={value}>{values[value] ?? value}</option>)}</select> : ['notes', 'source_excerpt', 'customization_terms', 'terms_text'].includes(field) ? <textarea rows={4} disabled={busy} value={String(draft[field] ?? '')} onChange={event => setDraft(current => ({ ...current, [field]: event.target.value }))} /> : <input disabled={busy} value={String(draft[field] ?? '')} onChange={event => setDraft(current => ({ ...current, [field]: event.target.value }))} />}</label>)}</div>
      {editing.kind === 'prices' && <label>默认批发价操作<select disabled={busy} value={defaultCommand === null ? '' : String(defaultCommand)} onChange={event => setDefaultCommand(event.target.value === '' ? null : event.target.value === 'true')}><option value="">保持当前默认状态</option><option value="true">明确设为默认</option><option value="false">取消默认（保留价格事实）</option></select></label>}
      {editing.kind === 'variants' && <AttributeEditor items={(draft.structured_attributes ?? []) as Attribute[]} sources={product.sources} disabled={busy} onChange={items => setDraft(current => ({ ...current, structured_attributes: items }))} />}
      <div className="library-actions"><button className="primary-button" disabled={busy} onClick={save}>保存{kinds[editing.kind]}</button><button className="secondary-button" disabled={busy} onClick={() => setEditing(null)}>取消</button></div></section>}
    <p className="library-row-error">{product.attachment_warning ?? '未保存图片及原始文件，请自行保留原件。'}</p>
  </>;
}
