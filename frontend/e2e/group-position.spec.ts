import { readFileSync } from "node:fs";
import type { GroupDetailData } from "../src/App";
import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";
import { detail, event, eventPage, group } from "./fixtures/group-position";

async function openWorkbench(page: Page, data = detail) {
  const mock = await installApiMock(page, { competitors: [], groups: [group] });
  await page.route("**/api/competitor-groups/summary", route => route.fulfill({ json: { groups: [{ ...group, competitor_count: 8, active_count: 7, price_min: "9", price_max: "150", changed_competitors_today: 2, last_change_at: null, own_product: detail.own_product }], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.route("**/api/competitor-groups/91/detail?*", route => route.fulfill({ json: { ...data, range_days: Number(new URL(route.request().url()).searchParams.get("days")), event_page: { ...eventPage, range: new URL(route.request().url()).searchParams.get("days") } } }));
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  await page.getByRole("button", { name: "组分析", exact: true }).click();
  await expect(page.getByRole("heading", { name: "隔离测试组 竞争分析" })).toBeVisible();
  return mock;
}

test("compact rows have no hover or focus popup and select same-shop Offers independently", async ({ page }) => {
  const mock = await openWorkbench(page);
  const preview = page.locator(".position-aside");
  for (const id of [1, 8, 2, 3]) {
    const row = page.locator(`[data-offer-id="${id}"]`);
    await row.locator("td:first-child").hover();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await expect(row.locator("[title]")).toHaveCount(0);
    await page.keyboard.press("Tab");
    await row.focus();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    expect(await row.locator("td:first-child").evaluate(cell => getComputedStyle(cell).outlineStyle)).toBe("solid");
    await row.press(id === 3 ? "Space" : "Enter");
    await expect(row).toHaveAttribute("aria-selected", "true");
    await expect(page.locator('.position-table tr[aria-selected="true"]')).toHaveCount(1);
    await expect(preview).toContainText(`隔离商品 ${id} · Offer 900${id}`);
    await expect(preview).toContainText(`来源快照 #${id}`);
    if (id === 8) { await expect(preview).toContainText("排名排除："); await expect(preview).toContainText("已停止"); }
    expect(await row.evaluate(element => element.getBoundingClientRect().height)).toBe(54);
  }
  await mock.expectNoUnexpectedApi();
});

test("operating metrics keep original values, attempts, and source visible in all three group views", async ({ page }) => {
  const source = "1688_official_procurement_assistant_top";
  const definitions = [
    ["listing_time", "上架时间", "经营表现", "observed", "2025-01-02"],
    ["monthly_deal", "月成交", "经营表现", "observed", "20+"],
    ["monthly_dropship", "月代销", "经营表现", "placeholder", "-"],
    ["annual_units", "年成交件数", "经营表现", "loading", null],
    ["annual_orders", "年成交笔数", "经营表现", "source_unavailable", null],
    ["review_count", "评论数", "口碑履约", "read_failed", null],
    ["positive_rate", "好评率", "口碑履约", "observed", "95.6%"],
    ["pickup_rate", "揽收率", "口碑履约", "placeholder", "-"],
  ] as const;
  const operatingMetrics = definitions.map(([metric_key, label, section, status, raw_value], index) => ({
    metric_key, label, section, eligible: true, status,
    latest_attempt: { collection_run_id: 77, status, raw_value, source, observed_at: `2026-10-10T0${index}:00:00Z`, reason: status === "observed" || status === "placeholder" ? null : "脱敏 Fixture 状态" },
    latest_valid: status === "observed" ? { collection_run_id: 77, raw_value: raw_value!, source, observed_at: `2026-10-10T0${index}:00:00Z` } : null,
  })).concat([
    { metric_key: "favorite_count", label: "收藏数", section: "口碑履约", eligible: false, status: "not_attempted", latest_attempt: null, latest_valid: null },
    { metric_key: "platform_tag_new", label: "新品", section: "平台标签", eligible: false, status: "not_attempted", latest_attempt: null, latest_valid: null },
  ] as const);
  const fixture: GroupDetailData = {
    ...detail,
    own_product: { ...detail.own_product!, latest_collection_run: { id: 77, started_at: "2026-10-10T00:00:00Z", finished_at: "2026-10-10T00:08:00Z", status: "success", operating_metrics_status: "partial", error_type: null, error_message: null }, operating_metrics: operatingMetrics },
    operating_metrics_coverage: Object.fromEntries(definitions.map(([key]) => [key, { has_history_valid_values: key === "monthly_deal" ? 1 : 0, active_offers: 7 }])),
  };
  const mock = await openWorkbench(page, fixture);
  const preview = page.locator(".position-aside");
  await expect(preview).toContainText("基础采集：成功 · 经营采集：部分成功");
  await expect(preview).toContainText("有效值来源：1688 官方采购助手顶部区域");
  await expect(preview).toContainText("收藏数");
  await expect(preview).toContainText("新品");
  await expect(preview).toContainText("收藏数待接入");
  await expect(preview).toContainText("20+");
  await expect(preview).toContainText("页面显示占位符（-）");
  await expect(preview).toContainText("仍在加载");
  await expect(preview).toContainText("来源不可用");
  await expect(preview).toContainText("读取失败");
  await expect(preview).toContainText("有历史有效值 1/7");
  await expect(page.locator(".position-table")).toContainText("20+");
  await page.getByRole("tab", { name: "经营表现" }).click();
  await expect(page.locator(".position-table")).toContainText("2025-01-02");
  await expect(page.locator(".position-table")).toContainText("页面显示 -");
  await expect(page.locator(".position-table")).toContainText("仍在加载");
  await page.getByRole("tab", { name: "口碑履约" }).click();
  await expect(page.locator(".position-table")).toContainText("95.6%");
  await expect(page.locator(".position-table")).toContainText("页面显示 -");
  await expect(preview).toContainText("尝试来源：1688 官方采购助手顶部区域");
  await mock.expectNoUnexpectedApi();
});

test("hidden-own notice follows actual filters and clears with keyboard location", async ({ page }, testInfo) => {
  const mock = await openWorkbench(page);
  const notice = page.locator(".position-filter-notice");
  const search = page.getByLabel("搜索店铺、商品或 Offer");
  await expect(notice).toHaveCount(0);
  await search.fill("9001");
  await expect(notice).toHaveText("当前筛选未显示我方商品清除筛选并定位");
  await search.clear();
  await expect(notice).toHaveCount(0);
  await page.getByLabel("监控状态", { exact: true }).selectOption("stopped");
  await expect(notice).toBeVisible();
  await page.getByLabel("监控状态", { exact: true }).selectOption("all");
  await expect(notice).toHaveCount(0);
  await search.fill("9001");
  await page.screenshot({ path: testInfo.outputPath("group-position-hidden-own.png") });
  const action = notice.getByRole("button", { name: "清除筛选并定位", exact: true });
  await action.focus();
  await action.press("Enter");
  await expect(search).toHaveValue("");
  await expect(notice).toHaveCount(0);
  await expect(page.locator('[data-offer-id="3"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-offer-id="3"]')).toHaveClass(/position-located/);
  await expect(page.locator(".position-aside")).toContainText("Offer 9003");
  await mock.expectNoUnexpectedApi();
});

test("locate own Offer at the end scrolls only the main pane into view in a short viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 540 });
  const data: GroupDetailData = { ...detail, own_product: { ...detail.competitors.find(product => product.id === 9)!, role: "own" }, competitors: [...detail.competitors.filter(product => product.id !== 9), { ...detail.own_product!, role: "competitor", comparison: { price: "overlap", min_order_quantity: "equal", sku_count: "equal", total_stock: "unknown" } }] };
  const mock = await openWorkbench(page, data);
  const own = page.locator('[data-offer-id="9"]');
  const table = page.locator(".position-comparison .table-scroll");
  const assertLocated = async () => {
    await expect(own).toHaveAttribute("aria-selected", "true");
    await expect(own).toHaveClass(/position-located/);
    await expect.poll(() => own.evaluate(row => {
      const rect = row.getBoundingClientRect();
      const main = row.closest(".main-content")!;
      const bounds = main.getBoundingClientRect();
      return rect.top >= Math.max(0, bounds.top) && rect.bottom <= Math.min(innerHeight, bounds.bottom);
    })).toBe(true);
  };
  await page.locator(".main-content").evaluate(main => { main.scrollTop = 0; });
  expect(await own.evaluate(row => row === row.parentElement!.lastElementChild)).toBe(true);
  expect(await own.evaluate(row => row.getBoundingClientRect().bottom > innerHeight)).toBe(true);
  const horizontal = await table.evaluate(element => { element.scrollLeft = 60; return element.scrollLeft; });
  expect(horizontal).toBeGreaterThan(0);
  await page.getByRole("button", { name: "定位我方", exact: true }).click();
  await assertLocated();
  expect(await own.locator("td:first-child").evaluate(cell => getComputedStyle(cell).boxShadow)).toBe("none");
  expect(await table.evaluate(element => element.scrollLeft)).toBe(horizontal);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await table.evaluate(element => element.scrollTop)).toBe(0);
  await expect(own).not.toHaveClass(/position-located/);
  expect(await own.locator("td:first-child").evaluate(cell => getComputedStyle(cell).boxShadow)).toBe("none");
  await expect(page.locator(".position-filter-notice")).toHaveCount(0);
  await page.getByLabel("搜索店铺、商品或 Offer").fill("9001");
  await expect(page.locator(".position-filter-notice")).toContainText("当前筛选未显示我方商品");
  await page.getByRole("button", { name: "定位我方", exact: true }).click();
  await expect(own).toHaveCount(0);
  await page.getByRole("button", { name: "清除筛选并定位" }).click();
  await expect(page.locator(".position-filter-notice")).toHaveCount(0);
  await assertLocated();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await table.evaluate(element => element.scrollLeft)).toBe(horizontal);
  await mock.expectNoUnexpectedApi();
});
async function mockOfferDetail(page: Page, offerId: number) {
  const offer = detail.competitors.find(product => product.id === offerId);
  if (!offer) throw new Error(`Offer ${offerId} is missing from the test fixture`);
  await page.route(`**/api/competitors/${offerId}/detail?*`, route => route.fulfill({ json: {
    range_days: 7,
    competitor: { ...offer, group_id: group.id, group_role: "competitor", ownership: "competitor", created_at: "2026-10-01T00:00:00Z" },
    latest_snapshot: offer.latest_snapshot ? { ...offer.latest_snapshot, image_urls: null, product_status: "active" } : null,
    latest_skus: [], latest_price_change: null, daily_trend: [], recent_changes: [], recent_collection_runs: [],
  } }));
}
const rowIds = (page: Page) => page.locator(".position-table tbody tr").evaluateAll(rows => rows.map(row => Number(row.getAttribute("data-offer-id"))));

async function measurePageWidth(page: Page, selectors: string[]) {
  return page.evaluate((targets) => {
    const main = document.querySelector(".main-content") as HTMLElement;
    const mainStyle = getComputedStyle(main);
    const box = (selector: string) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, width: rect.width };
    };
    return {
      main: box(".main-content"),
      constraints: { maxWidth: mainStyle.maxWidth, marginLeft: mainStyle.marginLeft, marginRight: mainStyle.marginRight, paddingLeft: mainStyle.paddingLeft, paddingRight: mainStyle.paddingRight },
      sections: Object.fromEntries(targets.map(selector => [selector, box(selector)])),
    };
  }, selectors);
}

for (const width of [1753, 1440, 1280, 800]) test(`left sidebar whitespace wheel scrolls group analysis main at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  await openWorkbench(page);
  const regions = await page.evaluate(() => {
    const sidebar = document.querySelector(".sidebar") as HTMLElement;
    const main = document.querySelector(".main-content") as HTMLElement;
    const sidebarBox = sidebar.getBoundingClientRect();
    return {
      viewport: { width: innerWidth, height: innerHeight },
      sidebar: { left: sidebarBox.left, right: sidebarBox.right, top: sidebarBox.top, bottom: sidebarBox.bottom, clientHeight: sidebar.clientHeight, scrollHeight: sidebar.scrollHeight },
      points: [0.08, 0.5, 0.92].map(ratio => ({ name: `sidebar-whitespace-${ratio}`, x: sidebarBox.left + sidebarBox.width * 0.92, y: innerHeight * ratio })),
    };
  });
  const observations: Array<{ name: string; x: number; y: number; hit: string | null; mainDelta: number; sidebarDelta: number; chain: string[] }> = [];
  for (const point of regions.points) {
    await page.evaluate(() => { (document.querySelector(".main-content") as HTMLElement).scrollTop = 0; (document.querySelector(".sidebar") as HTMLElement).scrollTop = 0; });
    const hit = await page.evaluate(({ x, y }) => {
      const target = document.elementFromPoint(x, y);
      const chain: string[] = [];
      let node = target as HTMLElement | null;
      while (node) {
        chain.push(`${node.tagName.toLowerCase()}.${node.className?.toString().trim().replaceAll(" ", ".")}`);
        if (node.classList.contains("app-shell")) break;
        node = node.parentElement;
      }
      return { target: target?.className ?? null, chain };
    }, point);
    await page.mouse.move(point.x, point.y);
    for (let repeat = 0; repeat < 5; repeat++) await page.mouse.wheel(0, 160);
    await page.waitForTimeout(80);
    const after = await page.evaluate(() => ({ main: (document.querySelector(".main-content") as HTMLElement).scrollTop, sidebar: (document.querySelector(".sidebar") as HTMLElement).scrollTop }));
    observations.push({ ...point, hit: hit.target, chain: hit.chain, mainDelta: after.main, sidebarDelta: after.sidebar });
  }
  const navHit = await page.locator(".sidebar nav button").first().evaluate(button => {
    const rect = button.getBoundingClientRect();
    return document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) === button;
  });
  const horizontalOverflow = await page.evaluate(() => ({ viewport: document.documentElement.scrollWidth, inner: innerWidth, shell: document.querySelector(".app-shell")!.scrollWidth, main: document.querySelector(".main-content")!.scrollWidth }));
  console.info(`left whitespace wheel ${width}px`, JSON.stringify({ bounds: { viewport: regions.viewport, sidebar: regions.sidebar }, observations, navHit, horizontalOverflow }));
  for (const result of observations) {
    expect(result.hit, `${width}px ${result.name} should hit main behind sidebar, chain: ${result.chain.join(" -> ")}`).toBe("main-content");
    expect(result.mainDelta, `${width}px ${result.name} at (${result.x}, ${result.y}) should scroll main`).toBeGreaterThan(0);
    expect(result.sidebarDelta, `${width}px ${result.name} should not scroll sidebar`).toBe(0);
  }
  expect(navHit, "sidebar navigation remains hit-testable").toBe(true);
  expect(horizontalOverflow.viewport, "no document horizontal overflow").toBeLessThanOrEqual(horizontalOverflow.inner);
  expect(horizontalOverflow.main, "no main horizontal overflow").toBeLessThanOrEqual(horizontalOverflow.shell);

  await page.setViewportSize({ width, height: 480 });
  const sidebarMetrics = await page.locator(".sidebar").evaluate(element => ({ scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }));
  expect(sidebarMetrics.scrollHeight, "sidebar navigation retains its own overflow at a short viewport").toBeGreaterThan(sidebarMetrics.clientHeight);
  const firstNavButton = await page.locator(".sidebar nav button:visible").first().boundingBox();
  expect(firstNavButton).not.toBeNull();
  await page.evaluate(() => { (document.querySelector(".main-content") as HTMLElement).scrollTop = 0; (document.querySelector(".sidebar") as HTMLElement).scrollTop = 0; });
  await page.mouse.move(firstNavButton!.x + firstNavButton!.width / 2, firstNavButton!.y + firstNavButton!.height / 2);
  await page.mouse.wheel(0, 320);
  await expect.poll(() => page.locator(".sidebar").evaluate(element => element.scrollTop)).toBeGreaterThan(0);
  expect(await page.locator(".main-content").evaluate(element => element.scrollTop), "navigation wheel stays in the sidebar").toBe(0);
});

test("wheel over comparison table, preview and events scrolls the main page", async ({ page }) => {
  const longData = { ...detail, competitors: [...detail.competitors, ...Array.from({ length: 28 }, (_, index) => ({ ...detail.competitors[index % detail.competitors.length], id: 200 + index, offer_id: `long-${index}`, title: `滚轮测试商品 ${index}` }))] };
  await page.setViewportSize({ width: 1440, height: 900 });
  await openWorkbench(page, longData);
  const zones = [
    { name: "left blank cell", locator: page.locator(".position-table tbody tr:first-child td:first-child") },
    { name: "table", locator: page.locator(".position-comparison .table-scroll") },
    { name: "preview", locator: page.locator(".position-aside .position-side-card:last-child") },
    { name: "events", locator: page.locator(".position-events") },
  ];
  const results: Array<{ name: string; mainDelta: number; tableDelta: number }> = [];
  for (const zone of zones) {
    await page.evaluate(() => { (document.querySelector("main") as HTMLElement).scrollTop = 0; document.querySelector(".table-scroll")!.scrollTop = 0; });
    await zone.locator.scrollIntoViewIfNeeded();
    const box = await zone.locator.boundingBox();
    if (!box) throw new Error(`${zone.name} has no layout box`);
    const point = await page.evaluate(({ x, y, width, height, name }) => ({ x: name === "left blank cell" ? x + width - 6 : x + width / 2, y: Math.max(20, Math.min(y + Math.min(height / 2, 250), innerHeight - 20)) }), { ...box, name: zone.name });
    const beforeWheel = await page.evaluate(() => ({ main: (document.querySelector("main") as HTMLElement).scrollTop, table: document.querySelector(".table-scroll")!.scrollTop }));
    await page.mouse.move(point.x, point.y);
    await page.mouse.wheel(0, zone.name === "events" ? -420 : 420);
    await page.waitForTimeout(80);
    const after = await page.evaluate(() => ({ main: (document.querySelector("main") as HTMLElement).scrollTop, table: document.querySelector(".table-scroll")!.scrollTop }));
    results.push({ name: zone.name, mainDelta: after.main - beforeWheel.main, tableDelta: after.table - beforeWheel.table });
  }
  const tableOverflow = await page.locator(".position-comparison .table-scroll").evaluate(element => ({ x: getComputedStyle(element).overflowX, y: getComputedStyle(element).overflowY, clientHeight: element.clientHeight, scrollHeight: element.scrollHeight }));
  expect(results.every(result => Math.abs(result.mainDelta) > 0), "each wheel region should move the main page").toBe(true);
  expect(results.every(result => result.tableDelta === 0), "the comparison table should not scroll vertically").toBe(true);
  expect(tableOverflow.x).toBe("auto");
  expect(["auto", "scroll"]).not.toContain(tableOverflow.y);
  expect(tableOverflow.scrollHeight).toBe(tableOverflow.clientHeight);
  await page.evaluate(() => {
    const main = document.querySelector("main") as HTMLElement;
    const table = document.querySelector(".position-comparison .table-scroll") as HTMLElement;
    main.scrollTop = 0;
    const mainRect = main.getBoundingClientRect();
    const tableRect = table.getBoundingClientRect();
    main.scrollTop += tableRect.bottom - (mainRect.top + main.clientHeight);
    table.scrollTop = table.scrollHeight;
  });
  const tableRect = await page.locator(".position-comparison .table-scroll").boundingBox();
  const boundaryStart = await page.locator("main").evaluate(element => element.scrollTop);
  await page.mouse.move(tableRect!.x + tableRect!.width / 2, tableRect!.y + tableRect!.height - 8);
  await page.mouse.wheel(0, 420);
  await expect.poll(() => page.locator("main").evaluate(element => element.scrollTop)).toBeGreaterThan(boundaryStart);
  expect(await page.locator(".position-comparison .table-scroll").evaluate(element => element.scrollTop)).toBe(0);
});

test("clicking different Offer rows updates the right-hand preview", async ({ page }) => {
  const mock = await openWorkbench(page);
  const preview = page.locator(".position-aside .position-side-card:last-child");
  await page.locator('[data-offer-id="1"] td:first-child').click();
  await expect(preview).toContainText("很长的真实来源店铺名称用于检查表格换行和操作按钮完整可见");
  await expect(preview).toContainText("隔离商品 1");
  await expect(preview).toContainText("Offer 9001");
  await expect(preview.locator(".position-facts")).toContainText("MOQ1");
  await page.locator('[data-offer-id="6"] td:first-child').click();
  await expect(preview).toContainText("测试店铺 6");
  await expect(preview).toContainText("隔离商品 6");
  await expect(preview).toContainText("Offer 9006");
  await expect(preview.locator(".position-facts")).toContainText("MOQ2");
  await mock.expectNoUnexpectedApi();
});

test("details action opens its Offer detail directly", async ({ page }) => {
  const mock = await openWorkbench(page);
  await mockOfferDetail(page, 6);
  await page.locator('[data-offer-id="2"] td:first-child').click();
  await page.locator('[data-offer-id="6"]').getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(page.locator(".detail-page-header")).toContainText("竞品详情");
  await expect(page.locator(".detail-overview-main h2")).toHaveText("隔离商品 6");
  await mock.expectNoUnexpectedApi();
});

test("details activation leaves the mounted Offer selection unchanged", async ({ page }) => {
  const mock = await openWorkbench(page);
  await page.evaluate(async data => {
    const reactUrl = "/node_modules/.vite/deps/react.js";
    const domUrl = "/node_modules/.vite/deps/react-dom_client.js";
    const appUrl = "/src/App.tsx";
    const [{ default: React }, { default: ReactDOM }, { GroupDetailPage }] = await Promise.all([import(reactUrl), import(domUrl), import(appUrl)]);
    document.getElementById("root")!.hidden = true;
    const container = document.createElement("div");
    container.dataset.selectionHarness = "true";
    document.body.append(container);
    const noop = () => {};
    ReactDOM.createRoot(container).render(React.createElement(GroupDetailPage, {
      data, status: "ready", error: null, days: 7, rangeLoading: false, rangeError: null,
      onRetry: noop, onRangeChange: noop, onBack: noop, onViewCompetitors: noop, onNavigate: noop,
      onOpenDetail: (id: number) => { container.dataset.openedOffer = String(id); },
    }));
  }, detail);
  const harness = page.locator("[data-selection-harness]");
  await harness.locator('[data-offer-id="2"] td:first-child').click();
  const button = harness.locator('[data-offer-id="6"]').getByRole("button", { name: "查看详情", exact: true });
  for (const key of ["click", "Enter", "Space"]) {
    await harness.evaluate(element => { delete (element as HTMLElement).dataset.openedOffer; });
    if (key === "click") await button.click();
    else { await button.focus(); await page.keyboard.press(key); }
    await expect(harness).toHaveAttribute("data-opened-offer", "6");
    await expect(harness.locator('[data-offer-id="2"]')).toHaveAttribute("aria-selected", "true");
    await expect(harness.locator('[data-offer-id="6"]')).toHaveAttribute("aria-selected", "false");
    await expect(harness.locator(".position-aside")).toContainText("Offer 9002");
  }
  await mock.expectNoUnexpectedApi();
});

for (const key of ["Enter", "Space"]) test(`keyboard details opens directly with ${key}`, async ({ page }) => {
  const mock = await openWorkbench(page);
  await mockOfferDetail(page, 6);
  await page.locator('[data-offer-id="2"] td:first-child').click();
  await page.locator('[data-offer-id="6"]').getByRole("button", { name: "查看详情", exact: true }).focus();
  await page.keyboard.press(key);
  await expect(page.locator(".detail-overview-main h2")).toHaveText("隔离商品 6");
  await mock.expectNoUnexpectedApi();
});

test("header sorting, tied positions, filtering, own location and pending views", async ({ page }) => {
  const mock = await openWorkbench(page);
  await expect(page.locator(".position-aside")).toContainText("Offer 9003");
  await expect(page.locator(".position-table thead")).toContainText("店铺");
  await expect(page.locator(".position-table thead")).not.toContainText("店铺 / Offer");
  await expect(page.locator(".position-table tbody tr").first()).not.toContainText("隔离商品");
  await expect(page.locator(".position-row-actions button")).toHaveCount(9);
  await expect(page.locator(".position-row-actions button")).toHaveText(Array(9).fill("查看详情"));
  await expect(page.getByRole("tab")).toHaveCount(3);
  await expect(page.getByRole("tab", { name: "平台标签", exact: true })).toHaveCount(0);
  const tagHeader = page.locator(".position-table thead th").filter({ hasText: "平台标签" });
  await expect(tagHeader).toContainText("待接入");
  await expect(tagHeader.locator("button")).toHaveCount(0);
  await expect(page.locator(".position-tag-cell")).toHaveCount(9);
  await expect(page.locator(".position-tag-cell")).toHaveText(Array(9).fill("—"));
  expect(await page.locator(".position-tag-cell").allTextContents()).not.toContain("无标签");
  expect(await rowIds(page)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  await page.getByRole("button", { name: "MOQ ↑", exact: true }).click();
  expect(await rowIds(page)).toEqual([3, 4, 5, 6, 1, 2, 7, 8, 9]);
  await expect(page.locator('[data-offer-id="3"]')).toHaveClass(/position-selected/);
  await expect(page.locator('th[aria-sort="descending"]')).toContainText("MOQ");
  await expect(page.locator(".position-aside")).toContainText("并列第 1 / 6");
  await expect(page.locator(".position-filter-notice")).toHaveCount(0);
  await page.getByLabel("搜索店铺、商品或 Offer").fill("9001");
  await expect(page.locator(".position-filter-notice")).toContainText("当前筛选未显示我方商品");
  expect(await rowIds(page)).toEqual([1]);
  await expect(page.locator(".position-summaries")).toContainText("并列第 1 / 6");
  await page.getByRole("button", { name: "定位我方", exact: true }).click();
  await expect(page.getByText("当前筛选未显示我方商品", { exact: false })).toBeVisible();
  await expect(page.locator(".position-aside")).toContainText("Offer 9003");
  await page.getByRole("button", { name: "清除筛选并定位" }).click();
  await expect(page.locator(".position-filter-notice")).toHaveCount(0);
  await expect(page.locator('[data-offer-id="3"]')).toHaveClass(/position-located/);
  expect(await rowIds(page)).toEqual([3, 4, 5, 6, 1, 2, 7, 8, 9]);
  await page.getByRole("tab", { name: "经营表现", exact: true }).click();
  expect(await rowIds(page)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  await expect(page.locator('th[aria-sort="descending"]')).toHaveCount(0);
  await expect(page.locator(".position-table")).toContainText("未采集");
  await page.getByRole("tab", { name: "竞争总览", exact: true }).click();
  expect(await rowIds(page)).toEqual([3, 4, 5, 6, 1, 2, 7, 8, 9]);
  await page.getByRole("button", { name: "展示报价 ↕", exact: true }).click();
  expect(await rowIds(page)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  await page.locator('[data-offer-id="1"]').click();
  await expect(page.locator(".position-aside")).toContainText("Offer 9001");
  await expect(page.locator('[data-offer-id="1"]')).toHaveClass(/position-selected/);
  await page.getByRole("button", { name: "MOQ ↕", exact: true }).click();
  await page.locator('[data-offer-id="2"]').click();
  await expect(page.locator(".position-aside")).toContainText("Offer 9002");
  await expect(page.locator('[data-offer-id="2"]')).toHaveClass(/position-selected/);
  await page.getByLabel("仅看重要变化").check();
  expect(await rowIds(page)).toEqual([1, 3, 6]);
  await expect(page.locator(".position-aside")).toContainText("当前选中商品不在筛选结果中");
  await page.locator('[data-offer-id="1"]').click();
  await expect(page.locator(".position-aside")).toContainText("Offer 9001");
  await expect(page.locator('[data-offer-id="1"]')).toHaveClass(/position-selected/);
  await expect(page.locator(".position-aside")).not.toContainText("当前选中商品不在筛选结果中");
  await page.getByLabel("仅看重要变化").uncheck();
  await page.locator('[data-offer-id="2"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".position-aside")).toContainText("Offer 9002");
  await expect(page.locator('[data-offer-id="2"]')).toHaveClass(/position-selected/);
  await page.locator('[data-offer-id="6"]').focus();
  await page.keyboard.press("Space");
  await expect(page.locator(".position-aside")).toContainText("Offer 9006");
  await expect(page.locator('[data-offer-id="6"]')).toHaveClass(/position-selected/);
  await expect(page.locator(".position-aside")).toContainText("来源快照 #6");
  await mock.expectNoUnexpectedApi();
});

test("unbound groups select the first Offer and refresh falls back when the selected Offer leaves", async ({ page }) => {
  await openWorkbench(page, { ...detail, own_product: null });
  await expect(page.locator(".position-filter-notice")).toHaveCount(0);
  await expect(page.locator(".position-aside")).toContainText("Offer 9001");
  await expect(page.locator('[data-offer-id="1"]')).toHaveClass(/position-selected/);
  await page.locator('[data-offer-id="6"]').click();
  await expect(page.locator(".position-aside")).toContainText("Offer 9006");
  await page.route("**/api/competitor-groups/91/detail?*", route => route.fulfill({ json: { ...detail, competitors: detail.competitors.filter(product => product.id !== 6) } }));
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.locator(".position-aside")).toContainText("Offer 9003");
});

test("bounded history append, failed retry, evidence and stale response isolation", async ({ page }) => {
  const mock = await openWorkbench(page);
  let appendAttempts = 0;
  await page.route("**/api/competitor-groups/91/events?*", async route => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("cursor")) {
      appendAttempts++;
      if (appendAttempts === 1) return route.fulfill({ status: 503, json: { message: "隔离追加失败" } });
      return route.fulfill({ json: { ...eventPage, items: [event(11), event(10), event(9)], has_more: false, next_cursor: null } });
    }
    if (url.searchParams.get("mode") === "all") {
      await new Promise(resolve => setTimeout(resolve, 350));
      return route.fulfill({ json: { ...eventPage, mode: "all", items: [event(99, "stock_decrease")], has_more: false, next_cursor: null } });
    }
    return route.fulfill({ json: { ...eventPage, items: [event(77)], has_more: false, next_cursor: null } });
  });
  await page.getByRole("button", { name: "继续加载" }).click();
  await expect(page.getByRole("alert")).toContainText("隔离追加失败");
  await expect(page.locator(".position-event-list li")).toHaveCount(20);
  await page.getByRole("button", { name: "重试 / 重新加载" }).click();
  await expect(page.locator(".position-event-list li")).toHaveCount(22);
  await expect(page.locator(".position-events")).toContainText("已加载当前窗口全部符合条件");
  await page.getByRole("button", { name: "变化证据" }).first().click();
  await expect(page.getByRole("region", { name: "所选变化证据" })).toContainText("Collection Run #42");
  await expect(page.getByRole("region", { name: "所选变化证据" })).toContainText("没有事件锚点");
  await page.getByRole("button", { name: "全部", exact: true }).click();
  await page.getByRole("button", { name: "重点", exact: true }).click();
  await expect(page.locator(".position-event-list li")).toHaveCount(1);
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: "变化证据" }).click();
  await expect(page.getByRole("region", { name: "所选变化证据" })).toContainText("Event #77");
  await mock.expectNoUnexpectedApi();
});

for (const width of [1753, 1440, 1280, 800]) test(`visual layout at ${width}px`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width, height: 1000 });
  const mock = await openWorkbench(page);
  const boxes = await page.locator(".position-primary, .position-aside").evaluateAll(elements => elements.map(element => { const box = element.getBoundingClientRect(); return { x: box.x, y: box.y, width: box.width }; }));
  if (width >= 1280) expect(boxes[1].x).toBeGreaterThan(boxes[0].x + boxes[0].width);
  else expect(boxes[1].y).toBeGreaterThan(boxes[0].y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const tableMetrics = await page.locator(".position-table").evaluate(table => {
    const rows = [...table.querySelectorAll("tbody tr")];
    return { width: table.getBoundingClientRect().width, scrollWidth: table.parentElement!.scrollWidth, actionWidth: table.querySelector("thead th:last-child")!.getBoundingClientRect().width, rowHeights: rows.map(row => row.getBoundingClientRect().height) };
  });
  console.info(`${width}px 行高: ${[...new Set(tableMetrics.rowHeights)].join(", ")}px`);
  expect(tableMetrics.scrollWidth).toBeGreaterThanOrEqual(tableMetrics.width);
  expect(tableMetrics.actionWidth).toBeGreaterThanOrEqual(82);
  expect(tableMetrics.actionWidth).toBeLessThan(116);
  expect([...new Set(tableMetrics.rowHeights)]).toEqual([54]);
  const row = page.locator('[data-offer-id="1"]');
  const colors = (id: number) => page.locator(`[data-offer-id="${id}"]`).evaluate(element => ({
    cells: [...element.querySelectorAll("td")].map(cell => getComputedStyle(cell).backgroundColor),
    outline: getComputedStyle(element).outlineStyle,
    sticky: getComputedStyle(element.lastElementChild!).position,
    layer: getComputedStyle(element.lastElementChild!).zIndex,
  }));
  await page.mouse.move(0, 0);
  const normal = await colors(1);
  await expect(page.locator(".page-header .page-description")).toHaveText("1 条我方商品 · 8 条竞品 · 仅监控样本，非实时报价");
  await expect(page.locator(".position-workbench > .position-context")).toHaveCount(0);
  await expect(page.locator(".position-aside")).toContainText("排名覆盖：");
  expect(new Set(normal.cells).size).toBe(1);
  await row.locator("td:first-child").hover();
  const hover = await colors(1);
  expect(new Set(hover.cells).size).toBe(1);
  expect(hover.cells[0]).not.toBe(normal.cells[0]);
  await page.screenshot({ path: testInfo.outputPath(`group-position-${width}-hover.png`) });
  await row.locator("td:first-child").click();
  await page.mouse.move(0, 0);
  const selected = await colors(1);
  const own = await colors(3);
  expect(own.cells).toEqual(normal.cells);
  const identity = await page.locator('[data-offer-id="3"]').evaluate(element => {
    const name = getComputedStyle(element.querySelector(".position-shop")!);
    const cells = [...element.querySelectorAll("td")].map(cell => ({ weight: getComputedStyle(cell).fontWeight, shadow: getComputedStyle(cell).boxShadow }));
    const other = document.querySelector('[data-offer-id="2"]')!;
    return { nameWeight: name.fontWeight, nameColor: name.color, cells, otherWeight: getComputedStyle(other.querySelector("td:nth-child(2)")!).fontWeight };
  });
  expect(Number(identity.nameWeight)).toBeGreaterThanOrEqual(650);
  expect(identity.nameColor).toBe("rgb(48, 72, 110)");
  expect(identity.cells.every(cell => cell.weight === identity.otherWeight && cell.shadow === "none")).toBe(true);
  expect(new Set(selected.cells).size).toBe(1);
  expect(new Set(own.cells).size).toBe(1);
  expect(selected.outline).toBe("none");
  expect(selected.sticky).toBe("sticky");
  expect(selected.layer).toBe("1");
  expect(selected.cells[0]).not.toBe(normal.cells[0]);
  expect(selected.cells[0]).not.toBe(hover.cells[0]);
  expect(selected.cells[0]).not.toBe(own.cells[0]);
  await row.locator("td:first-child").hover();
  expect((await colors(1)).cells).toEqual(selected.cells);
  await page.mouse.move(0, 0);
  await page.screenshot({ path: testInfo.outputPath(`group-position-${width}.png`), fullPage: true });
  const tableScroll = page.locator(".position-comparison .table-scroll");
  const tableBox = await tableScroll.boundingBox();
  expect(tableBox).not.toBeNull();
  const mainBefore = await page.locator("main").evaluate(element => element.scrollTop);
  const horizontalMetrics = await tableScroll.evaluate(element => ({ overflowX: getComputedStyle(element).overflowX, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }));
  expect(horizontalMetrics.overflowX).toBe("auto");
  await page.mouse.move(tableBox!.x + tableBox!.width / 2, tableBox!.y + tableBox!.height / 2);
  await page.mouse.wheel(420, 0);
  if (horizontalMetrics.scrollWidth > horizontalMetrics.clientWidth) await expect.poll(() => tableScroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  console.info(`${width}px 表格横向滚动`, JSON.stringify({ ...horizontalMetrics, scrollLeft: await tableScroll.evaluate(element => element.scrollLeft) }));
  await page.mouse.wheel(0, 420);
  await expect.poll(() => page.locator("main").evaluate(element => element.scrollTop)).toBeGreaterThan(mainBefore);
  expect(await tableScroll.evaluate(element => element.scrollTop)).toBe(0);
  await expect(page.locator('[data-offer-id="9"]')).toBeAttached();
  await page.locator("main").evaluate(element => { element.scrollTop = 0; });
  await tableScroll.evaluate(element => { element.scrollLeft = element.scrollWidth; });
  await page.locator('[data-offer-id="9"]').getByRole("button", { name: "查看详情", exact: true }).scrollIntoViewIfNeeded();
  await expect(page.locator('[data-offer-id="9"]').getByRole("button", { name: "查看详情", exact: true })).toBeInViewport();
  await page.locator('[data-offer-id="9"] td:last-child').click({ position: { x: 3, y: 3 } });
  expect(new Set((await colors(9)).cells).size).toBe(1);
  await page.screenshot({ path: testInfo.outputPath(`group-position-${width}-last-row.png`) });
  await page.locator(".main-content").evaluate(element => { element.scrollTop = element.scrollHeight; });
  await page.screenshot({ path: testInfo.outputPath(`group-position-${width}-lower.png`) });
  await mock.expectNoUnexpectedApi();
});

test("group-analysis content edges match competitor list at all target widths", async ({ page }) => {
  const widths = [1753, 1440, 1280, 800];
  const measurements = [];
  for (const width of widths) {
    await page.setViewportSize({ width, height: 1000 });
    await openWorkbench(page);
    const group = await measurePageWidth(page, [".page-header", ".position-summaries", ".position-layout", ".position-primary", ".position-aside"]);
    await page.getByRole("button", { name: "竞品列表", exact: true }).click();
    await expect(page.getByRole("heading", { name: "竞品列表", exact: true })).toBeVisible();
    const competitors = await measurePageWidth(page, [".page-header", ".filter-card", ".stats-strip", ".table-card"]);
    for (const section of [".page-header", ".position-summaries", ".position-layout"] as const) {
      const groupBox = group.sections[section]!;
      const competitorBox = competitors.sections[".page-header"]!;
      expect(Math.abs(groupBox.left - competitorBox.left), `${width}px ${section} left edge should match competitor list`).toBeLessThanOrEqual(1);
      expect(Math.abs(groupBox.right - competitorBox.right), `${width}px ${section} right edge should match competitor list`).toBeLessThanOrEqual(1);
    }
    if (width > 1100) expect(group.sections[".position-aside"]!.width, `${width}px analysis column stays compact`).toBeGreaterThanOrEqual(260);
    if (width > 1100) expect(group.sections[".position-aside"]!.width).toBeLessThanOrEqual(300);
    measurements.push({ width, group, competitors });
  }
  console.info("page content width measurements", JSON.stringify(measurements, null, 2));
});


test("range failure preserves facts and important filters; context conflict restarts history", async ({ page }) => {
  const mock = await openWorkbench(page);
  await page.getByLabel("仅看重要变化").check();
  await page.route("**/api/competitor-groups/91/detail?days=30", route => route.fulfill({ status: 503, json: { message: "隔离范围失败" } }));
  await page.getByRole("button", { name: "近 30 天", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("保留上一份事实");
  await expect(page.getByRole("button", { name: "近 7 天", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await rowIds(page)).toEqual([1, 3, 6]);
  await page.route("**/api/competitor-groups/91/events?*", route => new URL(route.request().url()).searchParams.has("cursor") ? route.fulfill({ status: 409, json: { code: "group_event_context_changed" } }) : route.fulfill({ json: { ...eventPage, items: [event(88)], has_more: false, next_cursor: null, important_offer_ids: [6] } }));
  await page.getByRole("button", { name: "继续加载" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "组成员" })).toBeVisible();
  await page.getByRole("button", { name: "重试 / 重新加载" }).click();
  await expect(page.locator(".position-event-list li")).toHaveCount(1);
  expect(await rowIds(page)).toEqual([6]);
  await mock.expectNoUnexpectedApi();
});

test("read-only real A19 response can be inspected in the browser", async ({ page }, testInfo) => {
  test.skip(!process.env.GROUP_REAL_RESPONSE, "Requires a manually captured read-only real database response");
  const real = JSON.parse(readFileSync(process.env.GROUP_REAL_RESPONSE!, "utf8")) as GroupDetailData;
  const mock = await installApiMock(page, { competitors: [], groups: [real.group] });
  await page.route("**/api/competitor-groups/summary", route => route.fulfill({ json: { groups: [{ ...real.group, competitor_count: real.competitors.length, active_count: real.summary.monitored_competitor_count, price_min: null, price_max: null, changed_competitors_today: real.summary.changed_competitors_today, last_change_at: null, own_product: real.own_product }], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.route(`**/api/competitor-groups/${real.group.id}/detail?*`, route => route.fulfill({ json: real }));
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  await page.getByRole("button", { name: "组分析", exact: true }).click();
  await expect(page.locator(".position-summaries")).toContainText("并列第 3 / 9");
  const own = page.locator(`[data-offer-id="${real.own_product!.id}"]`);
  expect(await rowIds(page)).toEqual([2, 3, 1, 4, 5, 6, 7, 8, 9]);
  await expect(page.locator('[data-offer-id="2"]')).toContainText("佛山淘趣");
  await expect(page.locator('[data-offer-id="3"]')).toContainText("深圳市飞也");
  await page.getByRole("button", { name: "MOQ ↑", exact: true }).click();
  await expect(own).toContainText("并列第 1 / 9");
  await page.getByRole("button", { name: "定位我方", exact: true }).click();
  await expect(own).toHaveClass(/position-located/);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: testInfo.outputPath("real-a19-position.png") });
  await page.getByRole("button", { name: "变化证据" }).first().click();
  await expect(page.getByRole("region", { name: "所选变化证据" })).toContainText(`Event #${real.event_page.items[0].id}`);
  await page.locator(".main-content").evaluate(element => { element.scrollTop = element.scrollHeight; });
  await page.screenshot({ path: testInfo.outputPath("real-a19-evidence.png") });
  await mock.expectNoUnexpectedApi();
});
