import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { makeCompetitor } from "./fixtures/competitors";
import { installApiMock } from "./support/api-mock";

// Controlled test data only; captures render the real application and never reach the database.
const products = Array.from({ length: 23 }, (_, i) => makeCompetitor(i + 1, {
  title: ["便携式暖手宝 双面发热 充电款", "桌面循环风扇 USB 供电三档调节", "折叠台灯 可调角度 阅读照明", "无线充电底座 桌面收纳款"][i % 4] + ` 测试款 ${i + 1}`,
  shop_name: i === 2 ? "用于验证长店铺名称换行的家居电器测试供应商" : `家居电器测试店铺 ${i + 1}`,
  offer_id: `1081895898${String(i + 1).padStart(3, "0")}`,
  group_id: i % 3 === 0 ? null : 19,
  status: i === 2 ? "offline" : i === 4 ? "unknown" : "active",
  last_collected_at: i % 4 === 0 ? null : "2026-10-19T08:30:00Z",
  latest_snapshot: i % 4 === 0 ? null : { price_min: "24.80", price_max: "39.90", sku_count: 6, total_stock: 120, captured_at: "2026-10-19T08:30:00Z" },
}));

test("visual evidence: desktop, selection, menu, narrow and reduced motion", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: products, groups: [{ id: 19, name: "便携家电", created_at: "2026-09-01T00:00:00Z" }] });
  const directory = resolve("../docs/qa/competitor-visual-v1.3");
  await mkdir(directory, { recursive: true });
  const phase = process.env.VISUAL_PHASE ?? "after";
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/");
  await page.getByRole("button", { name: "竞品列表", exact: true }).click();
  await expect(page.getByRole("heading", { name: "全部竞品", exact: true })).toBeVisible();
  await page.screenshot({ path: `${directory}/${phase}-desktop.png`, fullPage: true });
  await page.getByRole("checkbox", { name: `选择 ${products[0].title}`, exact: true }).check();
  await page.getByRole("button", { name: /批量操作（1）/ }).click();
  await expect(page.getByRole("menuitem", { name: "设置分组（1）" })).toBeVisible();
  await page.locator(".batch-menu-popover").evaluate(el => Promise.all(el.getAnimations().map(animation => animation.finished)));
  await page.screenshot({ path: `${directory}/${phase}-selected-menu.png`, fullPage: true });
  await page.getByRole("button", { name: /批量操作（1）/ }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  if (phase === "after") {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("button", { name: products[0].title, exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: products[0].title, exact: true })).toBeInViewport();
    await page.evaluate(() => scrollTo(0, 0));
  }
  await page.screenshot({ path: `${directory}/${phase}-narrow.png`, fullPage: true });
  if (phase === "after") {
    await page.locator("tbody tr").first().screenshot({ path: `${directory}/after-narrow-record.png` });
  }
  await page.getByRole("textbox", { name: "搜索商品名称 / offerId / 店铺" }).fill("不匹配任何商品");
  await expect(page.getByText("没有找到符合条件的竞品", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${directory}/${phase}-empty.png`, fullPage: true });
  await page.getByRole("button", { name: "重置筛选", exact: true }).click();
  if (phase === "after") {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.getByRole("button", { name: /批量操作/ }).click();
    expect(await page.locator(".batch-menu-popover").evaluate(el => getComputedStyle(el).animationName)).toBe("none");
    const search = page.getByRole("textbox", { name: "搜索商品名称 / offerId / 店铺" });
    await search.focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("商品状态", { exact: true })).toBeFocused();
    expect(await page.getByLabel("商品状态", { exact: true }).evaluate(el => getComputedStyle(el).outlineStyle)).not.toBe("none");
    await page.getByRole("button", { name: /批量操作/ }).click();
    for (const width of [320, 768, 1024, 1280, 1600]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    await page.getByRole("button", { name: "我方商品", exact: true }).click();
    await expect(page.locator(".competitor-workspace")).toHaveCount(0);
  }
  await mock.expectNoUnexpectedApi();
});

test("touch devices do not inherit desktop hover feedback", async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, viewport: { width: 1600, height: 1000 } });
  try {
    const page = await context.newPage();
    const mock = await installApiMock(page, { competitors: products });
    await page.goto("/");
    await page.getByRole("button", { name: "竞品列表", exact: true }).click();
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => matchMedia("(pointer: coarse)").matches)).toBe(true);
    const next = page.getByRole("button", { name: "下一页", exact: true });
    await next.scrollIntoViewIfNeeded();
    await expect.poll(() => next.evaluate(el => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 255, 255)");
    const before = await next.evaluate(el => getComputedStyle(el).backgroundColor);
    await next.hover();
    expect(await next.evaluate(el => getComputedStyle(el).backgroundColor)).toBe(before);
    const trigger = page.getByRole("button", { name: /批量操作/ });
    await trigger.scrollIntoViewIfNeeded();
    await page.mouse.move(0, 0);
    await expect.poll(() => trigger.evaluate(el => getComputedStyle(el).borderColor)).toBe("rgb(203, 209, 217)");
    const border = await trigger.evaluate(el => getComputedStyle(el).borderColor);
    await trigger.hover();
    expect(await trigger.evaluate(el => getComputedStyle(el).borderColor)).toBe(border);
    await mock.expectNoUnexpectedApi();
  } finally { await context.close(); }
});

test("loading, error, retry and system empty remain distinct", async ({ page }) => {
  test.skip(process.env.VISUAL_PHASE === "before", "Additional after-state coverage");
  const mock = await installApiMock(page, { competitors: [] });
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const listUrl = /\/api\/competitors(?:\?.*)?$/;
  await page.route(listUrl, async route => {
    await pending;
    await route.fulfill({ status: 500, json: { message: "测试服务暂时不可用" } });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "竞品列表", exact: true }).click();
  await expect(page.getByText("正在加载竞品列表…", { exact: true })).toBeVisible();
  const directory = resolve("../docs/qa/competitor-visual-v1.3");
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: `${directory}/after-loading.png` });
  release();
  await expect(page.getByText("加载失败", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${directory}/after-error.png` });
  await page.unroute(listUrl);
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("还没有添加竞品", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${directory}/after-system-empty.png` });
  await mock.expectNoUnexpectedApi();
});
