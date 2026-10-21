import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { plannedCounts, emptyProduct, ProductEditor, customerCopy, sensitiveText, searchSummary, prioritizedRows, type LibraryProduct, type PreviewRow } from "./ProductLibrary";

describe("产品库导入选择", () => {
  it("新增默认入计划，重复默认跳过，异常固定跳过", () => {
    const rows = [
      { row_number: 2, category: "new", default_action: "insert" },
      { row_number: 3, category: "duplicate", default_action: "skip" },
      { row_number: 5, category: "invalid", default_action: "skip" },
    ] as PreviewRow[];
    expect(plannedCounts(rows, {})).toEqual({ insert: 1, update: 0, skip: 2 });
  });
  it("表单未知价和空型号不填造值", () => {
    expect(emptyProduct.wholesale_price).toBeNull();
    expect(emptyProduct.model).toBeNull();
  });
  it("客户完整资料复制严格只含四个白名单字段", () => {
    const text = customerCopy({ ...emptyProduct, name: "客户灯", manufacturer_name: "PRIVATE_SUPPLIER", wholesale_price: "123.45", price_note: "PRIVATE_NOTE", parameters: "3.7V\n1000mAh", selling_points: "轻便" });
    expect(text).toBe("产品型号：未提供\n产品名称：客户灯\n产品参数：3.7V\n1000mAh\n产品卖点：轻便");
    expect(text).not.toContain("PRIVATE");
    expect(text).not.toContain("123.45");
    for (const word of ["成本", "采购价", "进货价", "拿货价", "供货价", "底价", "批发价", "内部价", "利润", "加价率", "开票调整", "运费成本"]) expect(sensitiveText(word)).toBe(true);
    expect(sensitiveText("普通客户参数")).toBe(false);
  });
  it("参数搜索摘要定位命中片段，不搜索价格备注", () => {
    const fields = { ...emptyProduct, name: "灯", parameters: "前".repeat(90) + "3.7V\n1000mAh" + "后".repeat(90), price_note: "3.7V" };
    const summary = searchSummary(fields, " 3.7v ");
    expect(summary).toContain("命中产品参数：…"); expect(summary).toContain("3.7V");
    expect(summary).not.toContain("价格备注"); expect(summary.length).toBeLessThan(100);
  });
  it("193款正常行和8个错误行优先展示问题，仍按整批统计", () => {
    const rows = [...Array.from({ length: 193 }, (_, index) => ({ row_number: index + 2, category: "new", default_action: "insert" })), ...Array.from({ length: 8 }, (_, index) => ({ row_number: index + 195, category: "invalid", default_action: "skip" }))] as PreviewRow[];
    const sorted = prioritizedRows(rows);
    expect(sorted.slice(0, 8).map(row => row.row_number)).toEqual([195, 196, 197, 198, 199, 200, 201, 202]);
    expect(plannedCounts(sorted, {})).toEqual({ insert: 193, update: 0, skip: 8 });
    expect(rows[0].category).toBe("new");
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

it("价格草稿保留原有金额范围、精度与含端点区间", async () => {
  const { validPriceFilter } = await import("./ProductLibrary");
  expect(validPriceFilter("", "", "")).toBe(true);
  expect(validPriceFilter("between", "0", "999999999.99")).toBe(true);
  expect(validPriceFilter("between", "10", "10")).toBe(true);
  for (const [mode, min, max] of [["below", "", ""], ["above", "1.", ""], ["above", "1.001", ""], ["above", "-1", ""], ["above", "1000000000", ""], ["between", "2", "1"], ["above", "1e2", ""]]) expect(validPriceFilter(mode, min, max)).toBe(false);
});
