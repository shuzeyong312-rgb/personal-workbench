import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";
import { detail, group } from "./fixtures/group-position";

test("workspace visual evidence", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
  await page.screenshot({ path: "../docs/qa/workspace-experience/after-home.png", fullPage: true });
  await page.locator(".workspace-sidebar").screenshot({ path: "../docs/qa/workspace-experience/sidebar.png" });
  await page.locator(".workspace-home .primary-button").focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(page.locator(".workspace-home .primary-button")).toBeFocused();
  expect(await page.locator(".workspace-home .primary-button").evaluate(el => el.matches(":focus-visible"))).toBe(true);
  await page.screenshot({ path: "../docs/qa/workspace-experience/keyboard-focus.png" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("group analysis retains usable narrow global navigation at 720px", async ({ page }) => {
  await installApiMock(page, { competitors: [], groups: [group] });
  await page.route("**/api/competitor-groups/summary", route => route.fulfill({ json: { groups: [{ ...group, competitor_count: 8, active_count: 7, price_min: "9", price_max: "150", changed_competitors_today: 2, last_change_at: null, own_product: detail.own_product }], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.route("**/api/competitor-groups/91/detail?*", route => route.fulfill({ json: detail }));
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  await page.locator(".group-directory-name").click();
  await expect(page.getByRole("heading", { name: "隔离测试组 竞争分析" })).toBeVisible();
  await page.setViewportSize({ width: 720, height: 1000 });
  await page.locator(".workspace-menu-toggle").click();
  await expect(page.getByRole("navigation", { name: "主导航", exact: true })).toBeVisible();
  await page.screenshot({ path: "../docs/qa/workspace-experience/group-navigation-720.png" });
  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(page.locator(".workspace-home")).toBeVisible();
  await expect(page.locator(".workspace-menu-toggle")).toHaveAttribute("aria-expanded", "false");
});

test("home task entries navigate to real modules", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.route("**/api/product-library/products?*", route => route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }));
  await page.route("**/api/product-library/manufacturers", route => route.fulfill({ json: { items: [] } }));
  await page.goto("/");
  for (const [entry, target] of [["进入竞品监控大屏", "竞品监控大屏"], ["打开产品库", "产品库"], ["我方商品", "我方商品"], ["竞品列表", "竞品列表"], ["竞品分组", "竞品分组"], ["采集记录", "采集记录"], ["配置我方店铺与采集策略", "系统设置"]]) {
    await page.getByRole("navigation", { name: "当前位置" }).getByRole("button", { name: "个人工作台", exact: true }).click();
    await page.locator(".workspace-home").getByRole("button", { name: entry }).click();
    await expect(page.getByRole("heading", { name: target, exact: true })).toBeVisible();
    await page.screenshot({ path: `../docs/qa/workspace-experience/regression-${target}.png`, fullPage: true });
  }
  await mock.expectNoUnexpectedApi();
});

test("narrow navigation, escape, keyboard and reduced motion", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "主导航", exact: true })).toBeHidden();
  const toggle = page.locator(".workspace-menu-toggle");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await page.screenshot({ path: "../docs/qa/workspace-experience/narrow-navigation.png", fullPage: true });
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".workspace-home")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../docs/qa/workspace-experience/narrow-home.png", fullPage: true });
  await page.keyboard.press("Control+Home");
  await page.locator(".workspace-skip").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#workspace-main")).toBeFocused();
  expect(await page.locator(".workspace-home .primary-button").evaluate(el => getComputedStyle(el).transitionDuration)).toBe("0s");
  await page.setViewportSize({ width: 320, height: 740 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
