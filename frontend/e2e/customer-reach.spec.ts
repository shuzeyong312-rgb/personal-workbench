import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("creates an ordered outreach campaign and confirms each customer against its content", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  let campaign: Record<string, unknown> | null = null;
  let confirmation: Record<string, unknown> | null = null;
  let skipConfirmation: Record<string, unknown> | null = null;
  let skipped = false;
  await page.route("**/api/customer-reach/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/mode")) return route.fulfill({ json: { mode: "simulated" } });
    if (path.endsWith("/screenshot")) return route.fulfill({ status: 404, json: { message: "no screenshot" } });
    if (path.endsWith("/campaigns") && request.method() === "GET") return route.fulfill({ json: campaign ? [campaign] : [] });
    if (path.endsWith("/campaigns") && request.method() === "POST") {
      const body = request.postDataJSON();
      const recipient = { recipient_id: "recipient-1", customer_key: "simulated-buyer-1", nickname: "模拟客户 1", category: "已成单客户", sequence: 1, eligible: true, authorization_evidence: "模拟：明确授权", status: "awaiting_confirmation", step: "模拟草稿已核验", matched_customer: "模拟客户 1", draft_verified: true, send_result: null, error_reason: null, processed_at: null };
      campaign = { id: "campaign-1", ...body, content_fingerprint: "fingerprint-1", execution_mode: "simulated", status: "awaiting_confirmation", step: "等待第 1 位客户单独确认", recipients: [recipient], current_recipient_id: "recipient-1", error_reason: null, created_at: "2026-10-23T00:00:00Z", started_at: "2026-10-23T00:00:01Z", finished_at: null };
      return route.fulfill({ status: 201, json: campaign });
    }
    if (path.endsWith("/confirm") && request.method() === "POST") {
      confirmation = request.postDataJSON();
      const recipients = campaign?.recipients as Array<Record<string, unknown>>;
      campaign = { ...campaign, status: "success", step: "队列处理完成", recipients: recipients.map((row) => ({ ...row, status: "success", send_result: "simulated" })) };
      return route.fulfill({ json: campaign });
    }
    if (path.endsWith("/skip-current") && request.method() === "POST") {
      skipConfirmation = request.postDataJSON();
      skipped = true;
      const recipients = campaign?.recipients as Array<Record<string, unknown>>;
      campaign = { ...campaign, status: "success", step: "队列处理完成", recipients: recipients.map((row) => ({ ...row, status: "skipped", send_result: "not_sent" })) };
      return route.fulfill({ json: campaign });
    }
    return route.fulfill({ status: 404, json: { message: "unhandled customer reach request" } });
  });

  await page.goto("/");
  await page.locator(".workspace-sidebar").getByRole("button", { name: "客户触达", exact: true }).click();
  await expect(page.getByRole("heading", { name: "客户触达" })).toBeVisible();
  await expect(page.getByText(/当前为模拟执行模式/)).toBeVisible();
  await page.getByLabel("客户分类").selectOption("ordered");
  await page.getByLabel("新品推广文案").fill("新品说明");
  await page.getByLabel("商品链接").fill("https://detail.1688.com/offer/123.html");
  await page.getByRole("button", { name: "创建并开始" }).click();
  await expect(page.getByText("模拟客户 1").first()).toBeVisible();
  await expect(page.getByText("新品说明")).toBeVisible();
  await page.screenshot({ path: "test-results/customer-reach-v1.png", fullPage: true });
  await page.getByRole("button", { name: "确认向此客户发送一次" }).click();
  await expect(page.getByText("模拟完成：未向客户发送消息")).toBeVisible();
  expect(confirmation).toEqual({ campaign_id: "campaign-1", recipient_id: "recipient-1", customer_key: "simulated-buyer-1", content_fingerprint: "fingerprint-1" });

  await page.getByLabel("新品推广文案").fill("另一条新品说明");
  await page.getByLabel("商品链接").fill("https://detail.1688.com/offer/124.html");
  await page.getByRole("button", { name: "创建并开始" }).click();
  await expect(page.getByRole("button", { name: "跳过此客户" })).toBeVisible();
  await page.getByRole("button", { name: "跳过此客户" }).click();
  await expect(page.getByText("模拟完成：未向客户发送消息").last()).toBeVisible();
  expect(skipped).toBe(true);
  expect(skipConfirmation).toEqual({ campaign_id: "campaign-1", recipient_id: "recipient-1", customer_key: "simulated-buyer-1", content_fingerprint: "fingerprint-1" });
});
