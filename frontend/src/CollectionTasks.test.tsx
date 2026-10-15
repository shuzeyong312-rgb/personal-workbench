import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { CollectionTasksPage, DashboardPage, idleBatchState, collectionDuration, formatCollectionDuration, attemptSummary } from "./App";

const noop = () => undefined;

test("collection records has no live collection controls or second progress surface", () => {
  const html = renderToStaticMarkup(createElement(CollectionTasksPage, { onNavigate: noop }));
  expect(html).toContain("采集记录");

  expect(html).not.toContain("历史未归属单次采集");
  expect(html).not.toContain("<h2>历史单次记录</h2>");
  expect(html).toContain("开始日期");
  expect(html).toContain("结束日期");
  expect(html).toContain("触发方式");
  expect(html).toContain("异常情况");
  expect(html).not.toContain("记录类型");
  expect(html).toContain("添加链接");
  expect(html).not.toContain(">查询</button>");
  expect(html).not.toContain("搜索批次 / 商品 / 店铺 / Offer");
  expect(html).not.toContain("暂停采集");
  expect(html).not.toContain("结束采集");
  expect(html).not.toContain("role=\"progressbar\"");
});

test("dashboard shows persisted attempt and retry progress in the existing live panel", () => {
  const html = renderToStaticMarkup(createElement(DashboardPage, {
    data: null,
    attention: null,
    attentionStatus: "loading",
    attentionError: null,
    status: "loading",
    error: null,
    batchState: {
      ...idleBatchState,
      status: "running",
      total: 3,
      completed: 1,
      remaining: 2,
      phase: "operating_metrics_retry",
      attempts_started: 4,
      page_visits: 3,
      retry_visits: 1,
      retry_max: 1,
      retry_total: 2,
      retry_completed: 1,
      current_competitor_id: 1,
      current_competitor_title: "当前商品测试",
      runner_active: true,
    },
    onRetry: noop,
    onRetryAttention: noop,
    onNavigate: noop,
    onToggleBatchPause: noop,
    onEndBatch: noop,
  }));
  expect(html).toContain("采集状态概览");
  expect(html).toContain("当前商品测试");
  expect(html).toContain("阶段：经营补采 1/2");
  expect(html).toContain("完成 1 / 3 · 剩余 2");
  expect(html).toContain("页面访问 3");
  expect(html).toContain("补采访问 1 · 上限 1");
  expect(html).toContain("role=\"progressbar\"");
  expect(html).toContain("暂停采集");
  expect(html).toContain("结束采集");
});


test("elapsed time uses actual timestamps and explicit missing boundaries", () => {
  expect(collectionDuration("2026-10-14T00:00:00Z", "2026-10-14T00:05:10Z")).toBe("5分10秒");
  expect(collectionDuration(null, "2026-10-14T00:05:10Z")).toBe("开始时间缺失");
  expect(collectionDuration("2026-10-14T00:00:00Z", null, true)).toBe("进行中");
  expect(collectionDuration("2026-10-14T00:00:00Z", null)).toBe("结束时间缺失");
  expect(collectionDuration("2026-10-14T00:05:10Z", "2026-10-14T00:00:00Z")).toBe("时间信息不足");
  expect(collectionDuration("not-a-date", "2026-10-14T00:00:00Z")).toBe("时间信息不足");
  expect(collectionDuration("2026-10-15T03:45:47.168528Z", "2026-10-15T03:45:47.408197Z")).toBe("0秒");
  expect(formatCollectionDuration(null)).toBe("—");
  expect(formatCollectionDuration(0)).toBe("0秒");
  expect(formatCollectionDuration(3661)).toBe("1小时1分1秒");
});

test("attempt anomaly summary aggregates real technical errors and excludes placeholders", () => {
  const makeAttempt = (statuses: string[]) => ({ id: 1, attempt_number: 1, attempt_kind: "first_pass", started_at: "2026-10-14T00:00:00Z", finished_at: "2026-10-14T00:00:01Z", status: "success", operating_metrics_status: "partial", error_type: null, error_message: null, observations: statuses.map((status, index) => ({ metric_key: String(index), status, raw_value: status === "placeholder" ? "-" : null, reason: null, source: "assistant", observed_at: "2026-10-14T00:00:01Z" })) });
  expect(attemptSummary(makeAttempt(["observed", "placeholder"]))).toBe("—");
  expect(attemptSummary(makeAttempt(Array(8).fill("source_unavailable")))).toBe("官方采购助手来源不可用，影响 8 项指标");
  expect(attemptSummary(makeAttempt(["placeholder", "loading", "read_failed"]))).toContain("影响 1 项指标");
  expect(attemptSummary({ ...makeAttempt([]), status: "failed", error_message: "商品页面加载失败" })).toBe("商品页面加载失败");
});
