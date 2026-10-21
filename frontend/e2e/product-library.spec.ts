import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";
import type { LibraryProduct, PreviewRow } from "../src/ProductLibrary";

const product: LibraryProduct = { id: 1, version: 1, manufacturer_name: "厂家 A", model: "M01", name: "测试灯", parameters: "3.7V\n保留单位", selling_points: null, wholesale_price: "12.30", price_note: null, created_at: "2026-10-18T01:00:00Z", updated_at: "2026-10-18T01:00:00Z" };
const importId = "d0053c5b-5cb1-40b1-ad50-d29dcb4df123";
const previewRows: PreviewRow[] = [
  { row_number: 2, name: "新增灯", model: "N01", category: "new", errors: [], candidate: [], file_candidates: [], diff: {}, allowed_actions: ["insert", "skip"], default_action: "insert" },
  { row_number: 3, name: "测试灯", model: "M01", wholesale_price: "15.00", category: "duplicate", existing_id: 1, version: 1, errors: [], candidate: [{ id: 1, name: "测试灯", model: "M01", version: 1, can_update: true, diff: { name: { old: "测试灯", incoming: "测试灯", effective: "测试灯", changed: false }, parameters: { old: "3.7V", incoming: null, effective: "3.7V", changed: false }, wholesale_price: { old: "12.30", incoming: "15.00", effective: "15.00", changed: true } } }], file_candidates: [], diff: { name: { old: "测试灯", incoming: "测试灯", effective: "测试灯", changed: false }, parameters: { old: "3.7V", incoming: null, effective: "3.7V", changed: false }, wholesale_price: { old: "12.30", incoming: "15.00", effective: "15.00", changed: true } }, allowed_actions: ["update", "skip"], default_action: "skip" },
  { row_number: 5, category: "invalid", errors: [{ field: "name", code: "required", message: "产品名称不能为空" }], candidate: [], file_candidates: [], diff: {}, allowed_actions: ["skip"], default_action: "skip" },
];
const preview = { import_id: importId, status: "ready", identity_rule_version: 3, expires_at: "2030-10-18T01:30:00Z", manufacturer_name: "厂家 A", counts: { total_rows: 3, new: 1, duplicate: 1, invalid: 1, ignored_blank_rows: 1 }, rows: previewRows };
const result = { import_id: importId, status: "committed", inserted: 1, updated: 1, skipped: 0, invalid: 1, rows: [{ row_number: 2, outcome: "inserted", product_id: 2, reason_code: "inserted" }, { row_number: 3, outcome: "updated", product_id: 1, reason_code: "updated" }, { row_number: 5, outcome: "invalid", product_id: null, reason_code: "invalid" }] };

async function setup(page: Page) {
  const mock = await installApiMock(page, { competitors: [] });
  let products = [product];
  await page.route("**/api/product-library/manufacturers", route => route.fulfill({ json: { items: ["厂家 A"] } }));
  await page.route("**/api/product-library/products?*", route => route.fulfill({ json: { items: products, total: products.length, page: 1, page_size: 20 } }));
  await page.route("**/api/product-library/products/1", async route => {
    if (route.request().method() === "PUT") { products = [{ ...product, ...route.request().postDataJSON(), version: 2 }]; await route.fulfill({ json: products[0] }); }
    else if (route.request().method() === "DELETE") { expect(route.request().postDataJSON()).toEqual({ version: 2 }); products = []; await route.fulfill({ status: 204 }); }
    else await route.fulfill({ json: products[0] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "产品库", exact: true }).click();
  await expect(page.getByRole("cell", { name: "测试灯", exact: true })).toBeVisible();
  return mock;
}

test("V1.1 combines filters, preserves cross-page selection and reports partial deletion", async ({ page }) => {
  const mock = await setup(page);
  const products = Array.from({ length: 21 }, (_, i) => ({ ...product, id: i + 1, model: `M${i + 1}`, name: `产品${i + 1}` }));
  await page.route("**/api/product-library/products?*", route => {
    const url = new URL(route.request().url()); const p = Number(url.searchParams.get("page"));
    return route.fulfill({ json: { items: products.slice((p - 1) * 20, p * 20), total: 21, page: p, page_size: 20 } });
  });
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("cell", { name: "产品1", exact: true })).toBeVisible();
  await page.getByLabel("选择本页", { exact: true }).check();
  await expect(page.getByText("跨页已选 20 款", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await page.getByLabel("选择产品 21", { exact: true }).check();
  await expect(page.getByText("跨页已选 21 款", { exact: true })).toBeVisible();
  await page.route("**/api/product-library/products/batch-delete", async route => {
    const items = route.request().postDataJSON().items;
    expect(items).toHaveLength(21); expect(items[0]).toEqual({ id: 1, version: 1 });
    await route.fulfill({ json: { items: items.map((item: { id: number; version: number }) => ({ ...item, outcome: item.id === 21 ? "stale" : "deleted" })), deleted: 20, missing: 0, stale: 1 } });
  });
  await page.getByRole("button", { name: "批量删除", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("21 款产品");
  await page.getByRole("button", { name: "确定删除", exact: true }).click();
  await expect(page.getByText("跨页已选 1 款", { exact: true })).toBeVisible();
  await page.getByLabel("报价状态", { exact: true }).selectOption("quoted");
  await expect(page.getByText("筛选条件已改变，已清除旧查询的选择")).toBeVisible();
  await page.getByLabel("价格条件", { exact: true }).selectOption("between");
  await page.getByLabel("最低价", { exact: true }).fill("10");
  const request = page.waitForRequest(req => req.url().includes("price_max=20"));
  await page.getByLabel("最高价", { exact: true }).fill("20");
  const url = new URL((await request).url());
  expect(url.searchParams.get("price_status")).toBe("quoted"); expect(url.searchParams.get("price_min")).toBe("10"); expect(url.searchParams.get("page")).toBe("1");
  await mock.expectNoUnexpectedApi();
});

test("V1.1 side preview copies only customer fields and warns before sensitive text", async ({ page, context }) => {
  const mock = await setup(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.route("**/api/product-library/products/1", route => route.fulfill({ json: { ...product, parameters: "采购价请核查\n3.7V", price_note: "SECRET_NOTE", manufacturer_name: "SECRET_SUPPLIER" } }));
  await page.getByRole("button", { name: "查看", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveClass(/library-side-panel/);
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "复制完整资料", exact: true }).click();
  await expect(page.getByText("复制成功", { exact: true })).toHaveCount(0);
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "复制完整资料", exact: true }).click();
  await expect(page.getByText("复制成功", { exact: true })).toBeVisible();
  const copied = (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n");
  expect(copied).toContain("采购价请核查\n3.7V"); expect(copied).not.toContain("SECRET"); expect(copied).not.toContain("12.30");
  await page.evaluate(() => { Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: () => Promise.reject(new Error("denied")) } }); });
  await page.getByRole("button", { name: "复制卖点", exact: true }).click();
  await expect(page.getByText("复制失败，请手动选择并复制资料")).toBeVisible();
  await page.screenshot({ path: "test-results/product-library-v11-side.png", fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("V1.1 quotation retains manual prices, requires text review and recovers stale versions", async ({ page }) => {
  const mock = await setup(page); let stale = true; let previews = 0;
  await page.getByLabel("选择产品 1", { exact: true }).check();
  const rules = { markup_mode: "none", markup_value: "0.00", tax_mode: "excluded", tax_value: "0.00", freight_mode: "separate", freight_value: "0.00", rounding: "cents" };
  await page.route("**/api/product-library/customer-quotations/preview", async route => {
    const body = route.request().postDataJSON(); previews++;
    await route.fulfill({ json: { items: body.items, rules: { ...rules, ...body.rules }, digest: "controlled-digest", moq: 1, note_risks: [], terms: "未税单价，运费另计。", note: "以上报价为未税单价，税费另计。运费另计，金额以订单确认为准。", rows: [{ ...product, original_price: product.wholesale_price, final_price: body.overrides["1"] ?? "12.30", manual: !!body.overrides["1"], risks: [], error: null, text_risks: [{ field: "parameters", word: "成本", snippet: "成本需核查" }] }] } });
  });
  await page.route("**/api/product-library/customer-quotations/export", async route => {
    const body = route.request().postDataJSON(); expect(body.overrides).toEqual({ "1": "20.00" }); expect(body.confirmed_risk_ids).toEqual([1]); expect(body.confirmed_all_text).toBe(true);
    if (stale) { stale = false; await route.fulfill({ status: 409, json: { code: "quotation_stale", message: "产品已变化，请重新预览", items: [{ id: 1, version: 1, reason: "stale" }] } }); }
    else await route.fulfill({ contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", body: Buffer.from("controlled-xlsx-download") });
  });
  await page.getByRole("button", { name: "客户报价 Excel", exact: true }).click();
  await page.getByRole("button", { name: /生成报价预览|重新核算报价/ }).click();
  await page.getByLabel("最终报价 1", { exact: true }).fill("20.00");
  await expect(page.getByRole("button", { name: "下载客户 Excel" })).toBeDisabled();
  await page.getByText("报价配置", { exact: false }).click();
  await page.getByLabel("加价方式").selectOption("percent");
  await page.getByLabel("加价百分点（10表示10%）").fill("10");
  await page.getByRole("button", { name: /生成报价预览|重新核算报价/ }).click();
  await page.getByRole("button", { name: "查看客户可见参数和卖点" }).click();
  await expect(page.getByText("最终报价：20.00 · MOQ 1")).toBeVisible();
  await page.getByLabel("已核对全部客户可见产品文本").check();
  await expect(page.getByRole("button", { name: "下载客户 Excel" })).toBeDisabled();
  await page.getByLabel("已逐项核查此产品客户文本", { exact: false }).check();
  await page.getByRole("button", { name: "下载客户 Excel" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "需刷新并复核的产品" })).toBeVisible();
  await expect(page.getByLabel("最终报价 1", { exact: true })).toHaveValue("20.00");
  await page.route("**/api/product-library/products/1", route => route.fulfill({ json: { ...product, version: 2 } }));
  await page.getByRole("button", { name: /生成报价预览|重新核算报价/ }).click();
  await page.getByLabel("已核对全部客户可见产品文本").check();
  await page.getByLabel("已逐项核查此产品客户文本", { exact: false }).check();
  const download = page.waitForEvent("download"); await page.getByRole("button", { name: "下载客户 Excel" }).click();
  expect((await download).suggestedFilename()).toBe("客户报价.xlsx"); expect(previews).toBe(3);
  await page.getByRole("button", { name: "恢复自动计算", exact: true }).click();
  await expect(page.getByLabel("最终报价 1", { exact: true })).toHaveValue("20.00");
  await expect(page.getByRole("button", { name: "下载客户 Excel" })).toBeDisabled();
  await page.screenshot({ path: "test-results/product-library-v11-quotation.png", fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("V1.1 dense 193+8 import keeps whole-batch actions visible across pages", async ({ page }) => {
  const mock = await setup(page);
  const rows: PreviewRow[] = [
    ...Array.from({ length: 193 }, (_, i) => ({ ...previewRows[0], row_number: i + 2, model: `N${i}`, name: `普通产品${i}` })),
    ...Array.from({ length: 8 }, (_, i) => ({ ...previewRows[2], row_number: i + 195 })),
  ];
  const receipt = { ...preview, rows, counts: { total_rows: 201, new: 193, duplicate: 0, invalid: 8, ignored_blank_rows: 0 } };
  await page.route("**/api/product-library/imports/preview?*", route => route.fulfill({ status: 201, json: receipt }));
  await page.route(`**/api/product-library/imports/${importId}/confirm`, async route => {
    const choices = route.request().postDataJSON().decisions;
    expect(choices).toHaveLength(201); expect(choices.filter((row: { action: string }) => row.action === "insert")).toHaveLength(193);
    await route.fulfill({ json: { ...result, inserted: 193, updated: 0, skipped: 0, invalid: 8, rows: [] } });
  });
  await upload(page);
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".library-preview-row").first()).toContainText("第 195 行");
  await expect(dialog.locator(".library-preview-row").nth(7)).toContainText("第 202 行");
  await expect(dialog.getByLabel("第 195 行操作")).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "核对第 2 行", exact: true })).toHaveAttribute("aria-expanded", "false");
  const confirmButton = dialog.getByRole("button", { name: "确认导入", exact: true });
  await expect(confirmButton).toBeInViewport();
  await dialog.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await expect(confirmButton).toBeInViewport();
  await dialog.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(dialog.getByText("计划新增 193 · 更新 0 · 异常 8 · 合法跳过 0", { exact: true })).toBeVisible();
  await expect(confirmButton).toBeInViewport();
  await page.screenshot({ path: "test-results/product-library-v11-dense-import.png", fullPage: true });
  await confirmButton.click();
  await expect(dialog.getByText("导入完成：新增 193 · 更新 0 · 跳过 0 · 错误 8")).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

for (const scope of ["filtered", "all"]) test(`V1.1 stale ${scope} refresh preserves the original snapshot without adding new matches`, async ({ page }) => {
  const mock = await setup(page); let previews = 0;
  const rules = { markup_mode: "none", markup_value: "0.00", tax_mode: "excluded", tax_value: "0.00", freight_mode: "separate", freight_value: "0.00", rounding: "cents" };
  await page.route("**/api/product-library/customer-quotations/preview", async route => {
    const body = route.request().postDataJSON(); previews++;
    if (previews === 1) expect(body.scope).toBe(scope);
    else { expect(body.scope).toBe("selected"); expect(body.items).toEqual([{ id: 1, version: 2 }]); }
    const items = previews > 1 && body.scope !== "selected" ? [{ id: 1, version: 2 }, { id: 2, version: 1 }] : [{ id: 1, version: previews > 1 ? 2 : 1 }];
    await route.fulfill({ json: { items, rules, digest: "controlled-digest", moq: 1, note_risks: [], terms: "未税单价，运费另计。", note: "未税单价，运费另计。", rows: items.map(item => ({ ...product, ...item, name: item.id === 2 ? "不应混入的新产品" : product.name, final_price: "12.30", manual: false, risks: [], text_risks: [], error: null })) } });
  });
  await page.route("**/api/product-library/customer-quotations/export", route => route.fulfill({ status: 409, json: { code: "quotation_stale", message: "产品已变化，请重新预览", items: [{ id: 1, version: 1, reason: "stale" }] } }));
  await page.getByRole("button", { name: "客户报价 Excel", exact: true }).click();
  await page.getByLabel("导出范围", { exact: false }).selectOption(scope);
  await page.getByRole("button", { name: /生成报价预览|重新核算报价/ }).click();
  await page.getByLabel("已核对全部客户可见产品文本").check();
  await page.getByRole("button", { name: "下载客户 Excel" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "需刷新并复核的产品" })).toBeVisible();
  await page.route("**/api/product-library/products/1", route => route.fulfill({ json: { ...product, version: 2 } }));
  await page.getByRole("button", { name: /生成报价预览|重新核算报价/ }).click();
  await expect(page.getByText("不应混入的新产品")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "下载客户 Excel" })).toBeDisabled();
  expect(previews).toBe(2);
  await mock.expectNoUnexpectedApi();
});

async function upload(page: Page) {
  await page.getByRole("button", { name: "批量导入", exact: true }).click();
  await page.getByRole("dialog").getByLabel("厂家名称").fill("厂家 A");
  await page.getByLabel("Excel 文件").setInputFiles({ name: "厂家.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("mock-xlsx") });
  await page.getByRole("button", { name: "上传并预览" }).click();
  await expect(page.getByRole("heading", { name: "批量导入 · 步骤 2/3" })).toBeVisible();
}

test("template → preview → explicit diff update → partial import; edit and confirmed delete", async ({ page }) => {
  const mock = await setup(page);
  await page.screenshot({ path: "test-results/product-library-list.png", fullPage: true });
  await page.route("**/api/product-library/template", route => route.fulfill({ contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers: { "Content-Disposition": "attachment; filename=template.xlsx" }, body: Buffer.from("mock-template") }));
  await page.getByRole("button", { name: "批量导入", exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 Excel 模板" }).click();
  expect((await download).suggestedFilename()).toBe("产品库导入模板.xlsx");
  await page.keyboard.press("Escape");
  await page.route("**/api/product-library/imports/preview?*", async route => { expect(decodeURIComponent(route.request().headers()["x-filename"])).toBe("厂家.xlsx"); await route.fulfill({ status: 201, json: preview }); });
  await page.route(`**/api/product-library/imports/${importId}/confirm`, async route => {
    expect(route.request().postDataJSON()).toEqual({ decisions: [{ row_number: 2, action: "insert" }, { row_number: 3, action: "update", target_id: 1, target_version: 1 }, { row_number: 5, action: "skip" }] });
    await route.fulfill({ json: result });
  });
  await upload(page);
  await expect(page.getByLabel("第 3 行操作")).toHaveValue("skip");
  await expect(page.getByLabel("第 5 行操作")).toBeDisabled();
  await page.getByRole("button", { name: "核对第 3 行", exact: true }).click();
  page.once("dialog", dialog => dialog.accept());
  await page.getByLabel("第 3 行操作").selectOption("update");
  await expect(page.getByText("3.7V（保留原值）", { exact: true })).toBeVisible();
  await expect(page.getByText("计划新增 1 · 更新 1 · 异常 1 · 合法跳过 0")).toBeVisible();
  await page.screenshot({ path: "test-results/product-library-preview.png", fullPage: true });
  await page.getByRole("button", { name: "确认导入", exact: true }).click();
  await expect(page.getByText("导入完成：新增 1 · 更新 1 · 跳过 0 · 错误 1")).toBeVisible();
  await page.getByRole("button", { name: "返回列表", exact: true }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByRole("dialog").getByLabel("产品名称").fill("手动修订灯");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("cell", { name: "手动修订灯" })).toBeVisible();
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("厂家：厂家 A");
  await expect(page.getByRole("dialog")).toContainText("型号：M01");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("cell", { name: "手动修订灯" })).toBeVisible();
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(page.getByText("没有符合条件的产品")).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

test("lost confirm response queries the original receipt and never resubmits", async ({ page }) => {
  const mock = await setup(page); let confirms = 0;
  await page.route("**/api/product-library/imports/preview?*", route => route.fulfill({ status: 201, json: preview }));
  await page.route(`**/api/product-library/imports/${importId}/confirm`, async route => { confirms++; await route.abort("failed"); });
  await page.route(`**/api/product-library/imports/${importId}`, route => route.fulfill({ json: { ...result, updated: 0, skipped: 1, rows: result.rows.map(row => row.row_number === 3 ? { ...row, outcome: "skipped", product_id: null, reason_code: "user_skipped" } : row) } }));
  await upload(page);
  await page.getByRole("button", { name: "确认导入", exact: true }).click();
  await expect(page.getByRole("button", { name: "查询原导入结果" })).toBeVisible();
  await expect(page.getByLabel("第 3 行操作")).toBeDisabled();
  await page.getByRole("button", { name: "查询原导入结果" }).click();
  await expect(page.getByText("导入完成：新增 1 · 更新 0 · 跳过 1 · 错误 1")).toBeVisible();
  expect(confirms).toBe(1);
  await page.screenshot({ path: "test-results/product-library-import-result.png", fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("manual partial matches are allowed and exact duplicates are rejected; deletion preserves confirmation", async ({ page }) => {
  const mock = await setup(page); let creates = 0;
  await page.route("**/api/product-library/products", async route => {
    creates++;
    const payload = route.request().postDataJSON();
    expect(payload.model).toBeNull(); expect(payload.wholesale_price).toBeNull();
    if (creates === 2) await route.fulfill({ status: 409, json: { code: "product_exists", message: "同厂家同型号同名称产品已存在，请编辑已有产品", candidates: [{ ...product, id: 2, model: null }] } });
    else await route.fulfill({ status: 201, json: { ...product, id: 2 + creates, model: null, name: payload.name } });
  });
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  await page.getByLabel("厂家名称", { exact: false }).fill("厂家 A");
  await page.getByLabel("产品名称", { exact: false }).fill("测试灯");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  await page.getByLabel("厂家名称", { exact: false }).fill("厂家 A");
  await page.getByLabel("产品名称", { exact: false }).fill("测试灯");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("精确重复不能新增");
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
  await page.getByLabel("产品名称", { exact: false }).fill("修正后的名称");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(creates).toBe(3);
  await page.route("**/api/product-library/products/1", route => route.fulfill({ status: 409, json: { code: "product_stale", message: "产品已变化，请重新读取" } }));
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("产品已变化，请重新读取");
  await expect(page.getByRole("dialog")).toContainText("名称：测试灯");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  await page.getByLabel("厂家名称", { exact: false }).fill("厂家 A");
  await page.getByLabel("产品名称", { exact: false }).fill("另一个灯");
  await page.route("**/api/product-library/products", route => route.abort("failed"));
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("保存结果待确认");
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await expect(page.getByLabel("产品名称", { exact: false })).toHaveValue("另一个灯");
  await mock.expectNoUnexpectedApi();
});

test("a ready receipt after network uncertainty only retries the original decisions", async ({ page }) => {
  const mock = await setup(page); let confirms = 0; let first: unknown;
  await page.route("**/api/product-library/imports/preview?*", route => route.fulfill({ status: 201, json: preview }));
  await page.route(`**/api/product-library/imports/${importId}/confirm`, async route => {
    confirms++;
    if (confirms === 1) { first = route.request().postDataJSON(); await route.abort("failed"); }
    else { expect(route.request().postDataJSON()).toEqual(first); await route.fulfill({ json: { ...result, updated: 0, skipped: 1 } }); }
  });
  await page.route(`**/api/product-library/imports/${importId}`, route => route.fulfill({ json: preview }));
  await upload(page);
  await page.getByRole("button", { name: "确认导入", exact: true }).click();
  await page.getByRole("button", { name: "查询原导入结果" }).click();
  await expect(page.getByLabel("第 3 行操作")).toBeDisabled();
  await expect(page.getByRole("button", { name: "返回修改文件或厂家（放弃选择）" })).toBeDisabled();
  await page.getByRole("button", { name: "按原决策重试" }).click();
  await expect(page.getByText("导入完成：新增 1 · 更新 0 · 跳过 1 · 错误 1")).toBeVisible();
  expect(confirms).toBe(2);
  await mock.expectNoUnexpectedApi();
});

test("keyboard focus, literal query, sort and narrow layout retain usable library controls", async ({ page }) => {
  const mock = await setup(page);
  await page.getByLabel("产品库关键词").fill("%_");
  const request = page.waitForRequest(request => request.url().includes("/api/product-library/products?") && new URL(request.url()).searchParams.get("manufacturer") === "厂家 A");
  await page.getByLabel("厂家筛选").selectOption("厂家 A");
  expect(new URL((await request).url()).searchParams.get("q")).toBe("%_");
  await page.getByLabel("排序", { exact: true }).selectOption("price_asc");
  await page.getByRole("button", { name: "查看", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("3.7V\n保留单位");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "查看", exact: true })).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: "test-results/product-library-narrow-form.png", fullPage: true });
  await mock.expectNoUnexpectedApi();
});
