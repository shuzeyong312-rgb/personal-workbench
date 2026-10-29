import { expect, test } from "vitest";
import { idleBatchState } from "./App";
import { notificationForBatch, searchEntries } from "./WorkspaceTools";

test("global search finds the toolbox page by name and image tool tag", () => {
  for (const query of ["常用工具箱", "图片压缩"]) {
    expect(searchEntries(query)).toContainEqual(expect.objectContaining({ label: "常用工具箱", page: "toolbox", kind: "页面" }));
  }
  expect(searchEntries("系统设置")).toContainEqual(expect.objectContaining({ page: "settings" }));
});

test("notifications require an identified, finished task with a known result", () => {
  const batch = { ...idleBatchState, task_id: "task-1", work_kind: "collect_products" as const, lifecycle_status: "terminal" as const, batch_outcome_code: "partial_failure", total: 3, completed: 3, succeeded: 2, failed: 1 };
  expect(notificationForBatch({ ...batch, runner_active: true })).toBeNull();
  expect(notificationForBatch({ ...batch, lifecycle_status: "running" })).toBeNull();
  expect(notificationForBatch({ ...batch, task_id: null })).toBeNull();
  expect(notificationForBatch(batch)).toMatchObject({ id: "task-1", tone: "warning", body: expect.stringContaining("失败 1") });
  expect(notificationForBatch({ ...batch, work_kind: "add_links", input_progress: null })).toBeNull();
});
