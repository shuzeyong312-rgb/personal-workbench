import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { customerCopy, emptyProduct, plannedCounts, type PreviewRow } from './ProductLibrary';
import { ProductLibraryDetails, type ProductDetail } from './ProductLibraryDetails';
import { V2ImportReview, type V2Preview } from './ProductLibraryV2Import';

describe('产品库 V2 安全入口', () => {
  it('同一产品追加来源计入修改计划，保留主产品身份', () => {
    const rows = [{ row_number: 2, category: 'duplicate', default_action: 'append_source' }] as PreviewRow[];
    expect(plannedCounts(rows, {})).toEqual({ insert: 0, update: 1, skip: 0 });
    expect(plannedCounts(rows, { 2: 'skip' })).toEqual({ insert: 0, update: 0, skip: 1 });
  });

  it('V2 预览默认复用已有主资料，附件确认前禁止提交', () => {
    const preview: V2Preview = { template_version: 2, import_id: 'preview', status: 'ready', expires_at: '2099-01-01', attachment_warning: '未保存图片及原始文件，请自行保留原件。', counts: { product: 1 }, rows: [{ row_key: { sheet: '产品数据', row_number: 2, record_type: 'product', temp_id: 'P' }, kind: 'product', product_ref: 'P', incoming: { name: '新品名称' }, old: { name: '原资料' }, effective: { name: '原资料' }, errors: [], dependencies: [], allowed_actions: ['update_main', 'use_existing', 'append_source', 'skip_product'], default_action: 'use_existing', target_id: 4, target_version: 2 }] };
    const html = renderToStaticMarkup(createElement(V2ImportReview, { preview, onClose() {}, onSaved() {} }));
    expect(html).toContain('value="use_existing" selected=""');
    expect(html).toContain('未保存图片及原始文件');
    expect(html).toMatch(/disabled="">确认导入/);
    expect(html).toContain('原资料');
    const update = { ...preview, rows: preview.rows.map(row => ({ ...row, default_action: 'update_main' })) };
    const updating = renderToStaticMarkup(createElement(V2ImportReview, { preview: update, onClose() {}, onSaved() {} }));
    expect(updating).toContain('生效值：新品名称');
  });

  it('详情保留未知资料并提供关联编辑，客户复制仍限制为四个字段', () => {
    const product: ProductDetail = { ...emptyProduct, name: '灯', id: 1, version: 1, created_at: '2026-10-29', updated_at: '2026-10-29', variants: [], prices: [], sources: [{ id: 2, version: 1, source_company: 'INTERNAL_COMPANY', source_excerpt: 'INTERNAL_EXCERPT' }], structured_attributes: null };
    const html = renderToStaticMarkup(createElement(ProductLibraryDetails, { product, onChanged() {} }));
    expect(html).toContain('新增规格款式');
    expect(html).toContain('新增价格明细');
    expect(html).toContain('编辑分类与参数');
    expect(html).toContain('INTERNAL_EXCERPT');
    const copy = customerCopy(product);
    expect(copy).not.toContain('INTERNAL');
    expect(copy).not.toContain('source');
    expect(copy).toContain('产品名称：灯');
  });
});
