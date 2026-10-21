import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

const screenshots = "../docs/qa/product-library-import-review";
const baseline = process.env.IMPORT_REVIEW_BASELINE === "1";
const sampleRows = (count = 1000, category?: string) => Array.from({ length: count }, (_, index) => {
  const kind = category ?? (index < 6 ? "invalid" : index < 32 ? "duplicate" : "new");
  return { row_number: index + 2, model: `MODEL-${index}`, name: `便携式多功能工作灯 ${index}`, parameters: "材质：铝合金\n电池容量：2600mAh\n" + "完整规格与厂家原文保留。".repeat(12), selling_points: "厂家提供的产品资料", wholesale_price: "29.80", category: kind,
    identity_reason: kind === "duplicate" ? "同厂家、同型号、同名称已存在" : "",
    existing_id: kind === "duplicate" ? index + 1 : null,
    errors: kind === "invalid" ? [{ field: "name", code: "required", message: "名称缺失，请修改文件后重新预览" }] : [],
    candidate: kind === "duplicate" ? [{ id: index + 1, name: `便携式多功能工作灯 ${index}`, model: `MODEL-${index}`, version: 1, can_update: true, diff: { parameters: { old: "旧参数", incoming: "新参数", effective: "新参数", changed: true } } }] : [],
    file_candidates: [], diff: {}, allowed_actions: kind === "invalid" ? ["skip"] : kind === "duplicate" ? ["update", "skip"] : ["insert", "skip"], default_action: kind === "new" ? "insert" : "skip" };
});

async function setup(page: Page, rows = sampleRows(), expires = "2030-01-01T00:00:00Z", manufacturer = "审核体验验收厂家") {
  await installApiMock(page, { competitors: [] });
  await page.route("**/api/product-library/products?*", route => route.fulfill({ json: { items: [], total: 0 } }));
  await page.route("**/api/product-library/manufacturers", route => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/product-library/imports/preview?*", route => route.fulfill({ json: {
    identity_rule_version: 3, import_id: "review-qa", status: "ready", manufacturer_name: manufacturer, expires_at: expires,
    counts: { new: rows.filter(row => row.category === "new").length, duplicate: rows.filter(row => row.category === "duplicate").length, invalid: rows.filter(row => row.category === "invalid").length, ignored_blank_rows: 3 }, rows,
  } }));
  await page.goto("/");
  await page.getByRole("button", { name: "产品库", exact: true }).click();
  await page.getByRole("button", { name: "批量导入", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("厂家名称").fill("审核体验验收厂家");
  await dialog.getByLabel("Excel 文件").setInputFiles({ name: "批量审核验收.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.from("UI fixture") });
  await dialog.getByRole("button", { name: "上传并预览" }).click();
  await expect(dialog.getByLabel("审核状态", { exact: true })).toBeVisible();
  return dialog;
}

test("visual comparison: 1000 rows, desktop and narrow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const dialog = await setup(page);
  await page.screenshot({ path: `${screenshots}/${baseline ? "before" : "after"}-desktop.png` });
  await dialog.locator(".library-audit-scroll").evaluate(node => { node.scrollTop = node.scrollHeight; });
  await page.screenshot({ path: `${screenshots}/${baseline ? "before" : "after"}-scrolled.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.locator(".library-dialog-body").evaluate(node => { node.scrollTop = 0; });
  await dialog.locator(".library-audit-scroll").evaluate(node => { node.scrollTop = 0; });
  await page.screenshot({ path: `${screenshots}/${baseline ? "before" : "after"}-narrow.png` });
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
});

test("1000 rows: fixed paging, scroll reset, filters and whole-batch payload", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const dialog = await setup(page);
  await dialog.getByLabel("审核状态", { exact: true }).selectOption("new");
  await dialog.getByLabel("第 34 行操作", { exact: true }).selectOption("skip");
  const scroll = dialog.locator(".library-audit-scroll");
  await scroll.evaluate(node => { node.scrollTop = node.scrollHeight; });
  await expect(dialog.getByRole("button", { name: "下一页", exact: true })).toBeInViewport();
  await expect(dialog.getByRole("button", { name: "确认导入", exact: true })).toBeInViewport();
  const header = await dialog.locator(".library-audit-table > thead th").first().boundingBox();
  const bounds = await scroll.boundingBox();
  expect(Math.abs(header!.y - bounds!.y)).toBeLessThan(2);
  await dialog.getByRole("button", { name: "下一页", exact: true }).click();
  expect(await scroll.evaluate(node => node.scrollTop)).toBe(0);
  await dialog.getByLabel("第 54 行操作", { exact: true }).selectOption("skip");
  await dialog.getByLabel("计划操作筛选").selectOption("skip");
  await expect(dialog.getByLabel("第 34 行操作", { exact: true })).toHaveValue("skip");
  await expect(dialog.getByLabel("第 54 行操作", { exact: true })).toHaveValue("skip");
  await dialog.getByLabel("搜索型号或名称", { exact: true }).fill("没有匹配的型号");
  await expect(dialog.getByText("没有匹配的导入行", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "查看全部导入行" }).click();
  let payload: { decisions: { row_number: number; action: string }[] } | undefined;
  await page.route("**/imports/review-qa/confirm", async route => { payload = route.request().postDataJSON(); await route.fulfill({ status: 409, json: { code: "preview_stale", message: "资料已变化，请重新预览" } }); });
  await dialog.getByRole("button", { name: "确认导入", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("资料已变化");
  expect(payload!.decisions).toHaveLength(1000);
  expect(payload!.decisions.filter(row => row.action === "insert")).toHaveLength(966);
  expect(payload!.decisions.find(row => row.row_number === 54)?.action).toBe("skip");
  await expect(dialog.getByLabel("第 8 行操作", { exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "确认导入", exact: true })).toBeDisabled();
});

test("plan filter clamps the page after the final matching row changes", async ({ page }) => {
  const dialog = await setup(page, sampleRows(21, "new"));
  await dialog.getByLabel("计划操作筛选").selectOption("insert");
  await dialog.getByRole("button", { name: "下一页", exact: true }).click();
  await dialog.getByLabel("第 22 行操作", { exact: true }).selectOption("skip");
  await expect(dialog.getByText("第 1 / 1 页", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel("第 2 行操作", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "跳过全部新增行", exact: true }).click();
  await expect(dialog.getByText("没有匹配的导入行", { exact: true })).toBeVisible();
  await expect(dialog.getByText("计划新增 0 · 更新 0 · 异常 0 · 合法跳过 21", { exact: true })).toBeVisible();
});

test("all duplicates: default skip, full comparison and explicit target update", async ({ page }) => {
  const dialog = await setup(page, sampleRows(45, "duplicate"));
  await expect(dialog.getByRole("button", { name: "确认导入", exact: true })).toBeDisabled();
  await expect(dialog.getByText(/当前没有待写入商品/)).toBeVisible();
  await dialog.getByLabel("第 2 行操作", { exact: true }).selectOption("update");
  await expect(dialog.getByRole("alert")).toContainText("请核对第 2 行目标");
  await expect(dialog.locator(".library-diff tbody tr")).toHaveCount(6);
  await expect(dialog.getByText("旧参数", { exact: true })).toBeVisible();
  page.once("dialog", event => event.accept());
  await dialog.getByLabel("第 2 行操作", { exact: true }).selectOption("update");
  await dialog.getByLabel("计划操作筛选").selectOption("update");
  await expect(dialog.getByLabel("第 2 行操作", { exact: true })).toHaveValue("update");
  await dialog.locator(".library-diff").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${screenshots}/after-duplicate-diff.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.getByRole("button", { name: "核对第 2 行", exact: true }).focus();
  const button = await dialog.getByRole("button", { name: "核对第 2 行", exact: true }).boundingBox();
  const footer = await dialog.locator(".library-review-footer").boundingBox();
  expect(button!.y + button!.height).toBeLessThanOrEqual(footer!.y);
  const detail = dialog.locator(".library-row-detail .table-scroll");
  await detail.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  await dialog.locator(".library-dialog-body").evaluate(node => { node.scrollTop = node.scrollHeight; });
  await page.screenshot({ path: `${screenshots}/after-narrow-diff.png` });
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
});

test("all invalid and expired previews explain recovery and prevent writes", async ({ page }) => {
  const dialog = await setup(page, sampleRows(45, "invalid"), "2020-01-01T00:00:00Z");
  await expect(dialog.getByText("预览已过期，请返回重新预览", { exact: false })).toBeVisible();
  await expect(dialog.getByLabel("第 2 行操作", { exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "确认导入", exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "跳过全部新增行", exact: true })).toBeDisabled();
  await page.screenshot({ path: `${screenshots}/after-invalid-expired.png` });
});

test("uncertain receipt locks decisions and keeps original retry payload", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const dialog = await setup(page, sampleRows(25, "new"));
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const payloads: unknown[] = [];
  await page.route("**/imports/review-qa/confirm", async route => { payloads.push(route.request().postDataJSON()); await pending; await route.fulfill({ status: 500, json: { message: "结果未知" } }); });
  await page.route("**/imports/review-qa", route => route.fulfill({ json: { import_id: "review-qa", status: "ready", identity_rule_version: 3, expires_at: "2030-01-01T00:00:00Z", manufacturer_name: "审核体验验收厂家", counts: { new: 25, duplicate: 0, invalid: 0 }, rows: sampleRows(25, "new") } }));
  await dialog.getByLabel("第 2 行操作", { exact: true }).selectOption("skip");
  await dialog.getByRole("button", { name: "确认导入", exact: true }).click();
  await expect(dialog.getByLabel("第 2 行操作", { exact: true })).toBeDisabled();
  release();
  await expect(dialog.getByRole("button", { name: "查询原导入结果", exact: true })).toBeEnabled();
  await expect(dialog.getByRole("button", { name: "查询原导入结果", exact: true })).toBeInViewport();
  await dialog.getByRole("button", { name: "查询原导入结果", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "按原决策重试", exact: true })).toBeEnabled();
  await expect(dialog.getByLabel("第 2 行操作", { exact: true })).toBeDisabled();
  await dialog.getByRole("button", { name: "按原决策重试", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "查询原导入结果", exact: true })).toBeVisible();
  expect(payloads).toHaveLength(2);
  expect(payloads[1]).toEqual(payloads[0]);
});

test("review navigation and actions remain reachable at laptop and short viewport sizes", async ({ page }) => {
  const dialog = await setup(page);
  for (const size of [{ width: 1280, height: 720 }, { width: 1024, height: 768 }, { width: 900, height: 651 }, { width: 1440, height: 600 }, { width: 390, height: 640 }]) {
    await page.setViewportSize(size);
    await expect(dialog.getByRole("button", { name: "确认导入", exact: true })).toBeInViewport();
    await dialog.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(dialog.getByText(/第 \d+ \/ 50 页/)).toBeInViewport();
    expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  }
});

test("narrow paging and filtering return the actual scroll container to the first row", async ({ page }) => {
  const dialog = await setup(page, sampleRows(60, "new"));
  await page.setViewportSize({ width: 390, height: 844 });
  const body = dialog.locator(".library-dialog-body");
  await body.evaluate(node => { node.scrollTop = node.scrollHeight; });
  await dialog.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(dialog.getByLabel("第 22 行操作", { exact: true })).toBeInViewport();
  const first = await dialog.locator(".library-preview-row").first().boundingBox();
  const bodyBox = await body.boundingBox();
  expect(Math.abs(first!.y - bodyBox!.y)).toBeLessThan(4);
  await body.evaluate(node => { node.scrollTop = node.scrollHeight; });
  await dialog.getByLabel("搜索型号或名称", { exact: true }).fill("MODEL-1");
  await expect(dialog.getByLabel("第 3 行操作", { exact: true })).toBeInViewport();
  await page.screenshot({ path: `${screenshots}/after-narrow-paged.png` });
});

test("long supplier and server error cannot push recovery actions out of a low viewport", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 651 });
  const dialog = await setup(page, sampleRows(60, "new"), "2030-01-01T00:00:00Z", "长厂家名称".repeat(40));
  await page.route("**/imports/review-qa/confirm", route => route.fulfill({ status: 409, json: { code: "preview_stale", message: "资料已经变化，请重新核对。".repeat(10) } }));
  await expect(dialog.getByRole("button", { name: "确认导入", exact: true })).toBeInViewport();
  await dialog.getByRole("button", { name: "确认导入", exact: true }).click();
  const back = dialog.getByRole("button", { name: "返回修改文件或厂家（放弃选择）", exact: true });
  await expect(back).toBeInViewport();
  await expect(dialog.getByRole("button", { name: "下一页", exact: true })).toBeInViewport();
  await dialog.getByRole("alert").scrollIntoViewIfNeeded();
  await expect(dialog.getByRole("alert")).toBeInViewport();
  await expect(back).toBeInViewport();
  await page.screenshot({ path: `${screenshots}/after-low-viewport-error.png` });
});
