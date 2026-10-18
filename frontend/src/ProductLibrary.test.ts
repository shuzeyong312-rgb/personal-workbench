import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { plannedCounts, emptyProduct, ProductEditor, type LibraryProduct, type PreviewRow } from "./ProductLibrary";

describe("产品库导入选择", () => {
  it("默认只新增 new，逐行更新与疑似新增纳入计划，错误跳过", () => {
    const rows = [
      { row_number: 2, category: "new", default_action: "insert" },
      { row_number: 3, category: "conflict", default_action: "skip" },
      { row_number: 4, category: "suspected", default_action: "skip" },
      { row_number: 5, category: "invalid", default_action: "skip" },
    ] as PreviewRow[];
    expect(plannedCounts(rows, {})).toEqual({ insert: 1, update: 0, skip: 3 });
    expect(plannedCounts(rows, { 3: "update", 4: "insert" })).toEqual({ insert: 2, update: 1, skip: 1 });
  });
  it("表单未知价和空型号不填造值", () => {
    expect(emptyProduct.wholesale_price).toBeNull();
    expect(emptyProduct.model).toBeNull();
  });
  it("新增表单渲染必填项、文本金额与完整资料字段", () => {
    const html = renderToStaticMarkup(createElement(ProductEditor, { product: null, onClose: () => {}, onSaved: () => {} }));
    expect(html).toContain("厂家名称 *");
    expect(html).toContain("产品名称 *");
    expect(html.match(/required=""/g)).toHaveLength(2);
    expect(html).toContain('inputMode="decimal"');
    expect(html).toContain('maxLength="10000"');
    expect(html).toContain("价格备注");
    expect(html).not.toContain('value="0"');
  });
  it("编辑表单保留明确零价、型号前导零、参数换行", () => {
    const product: LibraryProduct = { ...emptyProduct, id: 1, version: 1, created_at: "2026-10-18T00:00:00Z", updated_at: "2026-10-18T00:00:00Z", manufacturer_name: "厂家", name: "灯", model: "001", wholesale_price: "0.00", parameters: "3.7V\n1000mAh" };
    const html = renderToStaticMarkup(createElement(ProductEditor, { product, onClose: () => {}, onSaved: () => {} }));
    expect(html).toContain('value="0.00"');
    expect(html).toContain('value="001"');
    expect(html).toContain("3.7V\n1000mAh");
  });
});
