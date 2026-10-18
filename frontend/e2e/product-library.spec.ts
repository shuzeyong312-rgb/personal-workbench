import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";
import type { LibraryProduct, PreviewRow } from "../src/ProductLibrary";

const product: LibraryProduct = { id: 1, version: 1, manufacturer_name: "厂家 A", model: "M01", name: "测试灯", parameters: "3.7V\n保留单位", selling_points: null, wholesale_price: "12.30", price_note: null, created_at: "2026-10-18T01:00:00Z", updated_at: "2026-10-18T01:00:00Z" };
const importId = "d0053c5b-5cb1-40b1-ad50-d29dcb4df123";
const previewRows: PreviewRow[] = [
  { row_number: 2, name: "新增灯", model: "N01", category: "new", errors: [], candidate: [], file_candidates: [], diff: {}, allowed_actions: ["insert", "skip"], default_action: "insert" },
  { row_number: 3, name: "更新灯", model: "M01", category: "conflict", errors: [], candidate: [{ id: 1, name: "测试灯", model: "M01" }], file_candidates: [], diff: { name: { old: "测试灯", incoming: "更新灯", effective: "更新灯", changed: true }, parameters: { old: "3.7V", incoming: null, effective: "3.7V", changed: false } }, allowed_actions: ["update", "skip"], default_action: "skip" },
  { row_number: 5, category: "invalid", errors: [{ field: "name", code: "required", message: "产品名称不能为空" }], candidate: [], file_candidates: [], diff: {}, allowed_actions: ["skip"], default_action: "skip" },
];
const preview = { import_id: importId, status: "ready", expires_at: "2030-10-18T01:30:00Z", manufacturer_name: "厂家 A", counts: { total_rows: 3, new: 1, existing: 0, conflict: 1, suspected: 0, invalid: 1, ignored_blank_rows: 1 }, rows: previewRows };
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
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 Excel 模板" }).click();
  expect((await download).suggestedFilename()).toBe("产品库导入模板.xlsx");
  await page.route("**/api/product-library/imports/preview?*", async route => { expect(decodeURIComponent(route.request().headers()["x-filename"])).toBe("厂家.xlsx"); await route.fulfill({ status: 201, json: preview }); });
  await page.route(`**/api/product-library/imports/${importId}/confirm`, async route => {
    expect(route.request().postDataJSON()).toEqual({ decisions: [{ row_number: 2, action: "insert" }, { row_number: 3, action: "update" }, { row_number: 5, action: "skip" }] });
    await route.fulfill({ json: result });
  });
  await upload(page);
  await expect(page.getByLabel("第 3 行操作")).toHaveValue("skip");
  await expect(page.getByLabel("第 5 行操作")).toBeDisabled();
  await expect(page.getByText("3.7V（保留原值）", { exact: true })).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  await page.getByLabel("第 3 行操作").selectOption("update");
  await expect(page.getByText("计划新增 1 · 更新 1 · 错误 1 · 合法跳过 0")).toBeVisible();
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

test("manual suspected duplicate requires explicit consent; failed deletion preserves confirmation", async ({ page }) => {
  const mock = await setup(page); let creates = 0;
  await page.route("**/api/product-library/products", async route => {
    creates++;
    const payload = route.request().postDataJSON();
    if (!payload.allow_suspected_duplicate) await route.fulfill({ status: 409, json: { code: "suspected_duplicate", message: "存在同名产品，请确认", candidates: [product] } });
    else { expect(payload.model).toBeNull(); expect(payload.wholesale_price).toBeNull(); await route.fulfill({ status: 201, json: { ...product, id: 2, model: null } }); }
  });
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  await page.getByLabel("厂家名称", { exact: false }).fill("厂家 A");
  await page.getByLabel("产品名称", { exact: false }).fill("测试灯");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("候选 #1");
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await page.getByLabel("产品名称", { exact: false }).fill("修正后的名称");
  await expect(page.getByText("候选 #1", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
  await page.getByLabel("产品名称", { exact: false }).fill("测试灯");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
  await page.getByLabel("已核对同名候选，仍保存为独立产品").check();
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
