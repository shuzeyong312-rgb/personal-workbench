import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

// Controlled UI fixtures; no business database or real supplier data is used.
const product = { id: 1, version: 1, manufacturer_name: "受控验收样本（非真实商品）", model: "LX-120", name: "便携式充电工作灯", parameters: "额定电压：3.7V\n电池容量：2000mAh\n充电接口：USB Type-C\n三档亮度，支持桌面与悬挂使用。", selling_points: "轻巧便携，适用于室内与户外照明。\n可调照明角度，独立开关。", wholesale_price: "28.50", price_note: "整箱采购价格，运费另计。", created_at: "2026-10-18T01:00:00Z", updated_at: "2026-10-20T02:30:00Z" };
const rows = [{ row_number: 2, name: "便携式充电工作灯", model: "LX-121", category: "new", errors: [], candidate: [], file_candidates: [], diff: {}, allowed_actions: ["insert", "skip"], default_action: "insert" }, { row_number: 3, name: null, model: "LX-122", category: "invalid", errors: [{ field: "name", message: "产品名称不能为空" }], candidate: [], file_candidates: [], diff: {}, allowed_actions: ["skip"], default_action: "skip" }];
const before = process.env.LIBRARY_BEFORE === "1";
const directory = `../docs/qa/product-library-ui-v1/${before ? "before" : "after"}`;
async function shot(page: Page, name: string) { await page.screenshot({ path: `${directory}/${name}.png`, fullPage: await page.getByRole("dialog").count() === 0 }); }
async function setup(page: Page) {
  const mock = await installApiMock(page, { competitors: [] });
  await page.route("**/api/product-library/manufacturers", route => route.fulfill({ json: { items: [product.manufacturer_name] } }));
  await page.route("**/api/product-library/products?*", route => route.fulfill({ json: { items: [product, { ...product, id: 2, model: "LX-200", name: "折叠桌面照明灯", wholesale_price: null }], total: 2 } }));
  await page.route("**/api/product-library/products/1", route => route.fulfill({ json: product }));
  await page.route("**/api/product-library/imports/preview?*", route => route.fulfill({ json: { import_id: "ui-fixture", status: "ready", manufacturer_name: product.manufacturer_name, expires_at: "2030-01-01T12:00:00Z", counts: { total_rows: 2, new: 1, invalid: 1, ignored_blank_rows: 0 }, rows } }));
  await page.route("**/api/product-library/imports/ui-fixture/confirm", route => route.fulfill({ json: { import_id: "ui-fixture", status: "committed", inserted: 1, updated: 0, skipped: 0, invalid: 1, rows: [{ row_number: 2, outcome: "inserted", product_id: 3 }, { row_number: 3, outcome: "invalid", product_id: null }] } }));
  await page.route("**/api/product-library/customer-quotations/preview", route => route.fulfill({ json: { items: [{ id: 1, version: 1 }], rules: route.request().postDataJSON().rules, digest: "fixture", rows: [{ ...product, final_price: "31.35", manual: false, risks: [], text_risks: [], error: null }], note: "以上报价为未税单价，税费另计。运费另计，金额以订单确认为准。" } }));
  await page.goto("/");
  await page.getByRole("button", { name: "产品库", exact: true }).click();
  await expect(page.getByRole("cell", { name: product.name, exact: true })).toBeVisible();
  return mock;
}

test("whole module visual evidence and modal keyboard geometry", async ({ page, context }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const mock = await setup(page);
  await shot(page, "01-list");
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  await shot(page, "02-create");
  await page.keyboard.press("Escape");
  if (!before) await expect(page.getByRole("button", { name: "手动新增", exact: true })).toBeFocused();
  await page.getByRole("button", { name: "编辑", exact: true }).first().click();
  await expect(page.getByRole("dialog").getByLabel("产品名称", { exact: false })).toHaveValue(product.name);
  await shot(page, "03-edit");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "查看", exact: true }).first().click();
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  for (const name of ["复制参数", "复制卖点", "复制完整资料"]) {
    await page.getByRole("button", { name, exact: true }).click();
    await expect(page.getByText("复制成功", { exact: true })).toBeVisible();
  }
  await shot(page, "04-detail-copy");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "批量导入", exact: true }).click();
  await shot(page, "05-import-upload");
  await page.getByRole("dialog").getByLabel("厂家名称").fill(product.manufacturer_name);
  await page.getByLabel("Excel 文件").setInputFiles({ name: "验收.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("controlled-fixture") });
  await page.getByRole("button", { name: "上传并预览" }).click();
  await expect(page.getByText("产品名称不能为空", { exact: false })).toBeVisible();
  await shot(page, "06-import-preview");
  await page.getByRole("button", { name: "确认导入", exact: true }).click();
  await expect(page.getByText("导入完成：新增 1 · 更新 0 · 跳过 0 · 错误 1")).toBeVisible();
  await shot(page, "07-import-result");
  await page.getByRole("button", { name: "返回列表", exact: true }).click();
  await page.getByRole("button", { name: "客户报价 Excel", exact: true }).click();
  await page.getByLabel("加价方式").selectOption("percent");
  await page.getByLabel("加价百分点（10表示10%）").fill("10");
  await shot(page, "08-quotation-config");
  await page.getByRole("button", { name: "生成报价预览", exact: true }).click();
  await page.getByLabel("已核对全部客户可见产品文本").check();
  await expect(page.getByRole("button", { name: "下载客户 Excel" })).toBeEnabled();
  await shot(page, "09-quotation-preview");
  await page.keyboard.press("Escape");
  await page.getByLabel("选择本页", { exact: true }).check();
  await page.getByRole("button", { name: "批量删除", exact: true }).click();
  await shot(page, "10-batch-delete");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "删除", exact: true }).first().click();
  await shot(page, "11-single-delete");
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, "12-narrow-list");
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  await shot(page, "13-narrow-editor");
  if (!before) {
    const dialog = page.getByRole("dialog");
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await expect(dialog.getByRole("button", { name: "保存", exact: true })).toBeInViewport();
    await dialog.getByRole("button", { name: "关闭", exact: true }).focus();
    await page.keyboard.press("Shift+Tab");
    expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await dialog.getByLabel("产品名称", { exact: false }).fill("未保存修改");
    page.once("dialog", event => event.dismiss());
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    page.once("dialog", event => event.accept());
  }
  await page.keyboard.press("Escape");
  if (!before) {
    await page.getByRole("button", { name: "查看", exact: true }).first().click();
    await shot(page, "14-narrow-detail");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "批量导入", exact: true }).click();
    await shot(page, "15-narrow-import");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "客户报价 Excel", exact: true }).click();
    await shot(page, "16-narrow-quotation");
    await page.keyboard.press("Escape");
  }
  await mock.expectNoUnexpectedApi();
});

test("loading, empty, retry, field errors and safe close remain actionable", async ({ page }) => {
  test.skip(before, "Baseline captures only");
  const mock = await setup(page);
  await page.setViewportSize({ width: 1280, height: 720 });
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/product-library/products?*", async route => { await gate; await route.fulfill({ status: 503, json: { message: "受控加载失败" } }); });
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByText("正在加载产品…")).toBeVisible();
  await shot(page, "17-loading");
  release();
  await expect(page.getByText("产品列表加载失败")).toBeVisible();
  await shot(page, "18-list-error");
  await page.route("**/api/product-library/products?*", route => route.fulfill({ json: { items: [], total: 0 } }));
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("没有符合条件的产品", { exact: true })).toBeVisible();
  await shot(page, "19-empty");
  await page.getByRole("button", { name: "手动新增", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("厂家名称").fill("受控样本");
  await dialog.getByLabel("产品名称").fill("验收灯");
  await page.route("**/api/product-library/products", route => route.fulfill({ status: 422, json: { code: "invalid_product", message: "请检查产品字段", errors: [{ field: "wholesale_price", message: "批发价最多两位小数" }] } }));
  await dialog.getByLabel("批发价").fill("12.345");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog.getByRole("alert")).toBeFocused();
  await dialog.getByRole("link", { name: "批发价：批发价最多两位小数" }).click();
  await expect(dialog.getByLabel("批发价", { exact: false })).toBeFocused();
  await shot(page, "20-editor-validation");
  for (const name of ["取消", "关闭"]) {
    page.once("dialog", event => event.dismiss());
    await dialog.getByRole("button", { name, exact: true }).click();
    await expect(dialog).toBeVisible();
  }
  page.once("dialog", event => event.accept());
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "手动新增", exact: true })).toBeFocused();
  await mock.expectNoUnexpectedApi();
});

test("narrow long content, import abandonment and quotation risk gates", async ({ page }) => {
  test.skip(before, "Baseline captures only");
  const mock = await setup(page);
  await page.setViewportSize({ width: 390, height: 700 });
  await page.route("**/api/product-library/products/1", route => route.fulfill({ json: { ...product, parameters: "长参数".repeat(3000), selling_points: "长卖点\n".repeat(500) } }));
  await page.getByRole("button", { name: "查看", exact: true }).first().click();
  let dialog = page.getByRole("dialog");
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  expect(await dialog.locator(".library-dialog-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await dialog.locator(".library-dialog-body").evaluate(el => { el.scrollTop = el.scrollHeight; });
  await expect(dialog.getByRole("button", { name: "关闭", exact: true })).toBeInViewport();
  await shot(page, "21-narrow-long-detail");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "批量导入", exact: true }).click();
  await page.getByRole("dialog").getByLabel("厂家名称").fill(product.manufacturer_name);
  await page.getByLabel("Excel 文件").setInputFiles({ name: "错误.txt", mimeType: "text/plain", buffer: Buffer.from("fixture") });
  await page.getByRole("button", { name: "上传并预览" }).click();
  await expect(page.getByRole("alert")).toHaveText("仅支持 .xlsx 文件");
  await shot(page, "22-import-file-error");
  await page.getByLabel("Excel 文件").setInputFiles({ name: "验收.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("fixture") });
  await page.getByRole("button", { name: "上传并预览" }).click();
  await expect(page.getByRole("heading", { name: "批量导入 · 步骤 2/3" })).toBeVisible();
  await expect(page.getByRole("button", { name: "确认导入", exact: true })).toBeInViewport();
  await shot(page, "23-narrow-import-preview");
  page.once("dialog", event => event.dismiss());
  await page.getByRole("button", { name: "返回修改文件或厂家（放弃选择）" }).click();
  await expect(page.getByRole("heading", { name: "批量导入 · 步骤 2/3" })).toBeVisible();
  page.once("dialog", event => event.accept());
  await page.getByRole("button", { name: "返回修改文件或厂家（放弃选择）" }).click();
  await expect(page.getByRole("heading", { name: "批量导入 · 步骤 1/3" })).toBeVisible();
  await expect(page.getByLabel("Excel 文件")).toBeEmpty();
  await expect(page.getByText("尚未选择文件 · .xlsx · 最多 5 MiB")).toBeVisible();
  await page.getByLabel("Excel 文件").setInputFiles({ name: "重新选择.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("fixture") });
  await page.getByRole("button", { name: "上传并预览" }).click();
  await expect(page.getByRole("heading", { name: "批量导入 · 步骤 2/3" })).toBeVisible();
  page.once("dialog", event => event.accept());
  await page.keyboard.press("Escape");
  await page.route("**/api/product-library/customer-quotations/preview", route => route.fulfill({ json: { items: [{ id: 1, version: 1 }], rules: route.request().postDataJSON().rules, digest: "fixture", rows: [{ ...product, parameters: "采购价需核查", final_price: "20.00", manual: false, risks: ["低于采购成本"], text_risks: [{ field: "parameters", word: "采购价", snippet: "采购价需核查" }], error: null }], note: "以上报价为未税单价，税费另计。运费另计。" } }));
  await page.route("**/api/product-library/customer-quotations/export", async route => {
    expect(route.request().postDataJSON().confirmed_risk_ids).toEqual([1]);
    expect(route.request().postDataJSON().confirmed_all_text).toBe(true);
    await route.fulfill({ contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", body: Buffer.from("controlled-download") });
  });
  await page.getByRole("button", { name: "客户报价 Excel", exact: true }).click();
  await page.getByRole("button", { name: "生成报价预览", exact: true }).click();
  await page.getByText("查看客户可见参数和卖点").click();
  await page.getByLabel("已核对全部客户可见产品文本").check();
  await expect(page.getByRole("button", { name: "下载客户 Excel" })).toBeDisabled();
  await shot(page, "24-narrow-quotation-risk");
  await page.getByLabel("已逐项核查此产品客户文本", { exact: false }).check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载客户 Excel" }).click();
  expect((await download).suggestedFilename()).toBe("客户报价.xlsx");
  await expect(page.getByText("客户 Excel 已生成，下载已开始。")).toBeVisible();
  await page.getByText("客户 Excel 已生成，下载已开始。").scrollIntoViewIfNeeded();
  await expect(page.getByText("客户 Excel 已生成，下载已开始。")).toBeInViewport();
  await shot(page, "25-quotation-download");
  dialog = page.getByRole("dialog");
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await mock.expectNoUnexpectedApi();
});
