# 批量采集与后台浏览器 Feature Spec

状态：待确认，当前仅为正式 Feature Spec，不包含实现授权。

## Problem Statement

当前竞品列表每一行都提供“立即采集”，导致列表操作重复且拥挤。每次单条采集还会由正式 collector 单独启动并关闭一个 headed Chrome，采集期间 Chrome 会出现在桌面上，影响用户进行其他工作。

本 Feature 需要在不扩大 V1 架构的前提下，提供一次选择多个竞品的采集入口，并让正常采集期间的 headed Chrome 停放到屏幕外。1688 的验证页不能被自动绕过；一旦触发验证，当前批次必须安全停止并明确交给用户处理。

## Solution

竞品列表增加当前页选择能力，并提供两个批次入口：

- 采集选中竞品；
- 采集全部监控中的竞品。

后端增加一个批次采集业务入口。POST 只负责校验、登记并启动一个进程内 Runner，立即返回当前批次状态；Runner 在独立线程中串行执行，持有现有 `COLLECTION_LOCK`，只启动一次 headed Chrome persistent context，连续处理竞品，正常结束后关闭 Browser/Context。GET status 通过 HTTP polling 返回内存中的真实进度。

V1 同一进程同一时间只允许一个批次 Runner。只保留当前批次的临时状态，不引入数据库任务表、队列、实时推送或批次历史。普通单条失败记录到现有 `CollectionRun` 后继续下一个竞品。

## Goals

1. 列表支持当前页 active 竞品的 checkbox 选择。
2. inactive 竞品不可选、不可被批量采集。
3. 批量采集不由前端循环调用 N 次单条 API。
4. 批次只启动一次 headed Chrome，并尽可能复用 Browser/Context。
5. 正常批次串行处理竞品，不引入并发 2。
6. 复用现有 `COLLECTION_LOCK`，保持手动采集、批量采集、删除和 daily scheduler 的互斥语义。
7. 普通单条失败不会终止后续竞品。
8. `verification_required` 会终止批次、召回 Chrome 并提示人工处理。
9. 不新增数据库表、字段、migration 或依赖。

## Non-goals

- headless 采集；
- 并发 2 或更高并发；
- 自动滑块、验证码、风控绕过或 stealth；
- 自动刷新、无限重试或验证后自动续跑；
- Celery、Redis、消息队列、微服务或分布式任务系统；
- BatchJob 表、任务历史、独立任务中心；
- WebSocket 或 SSE；HTTP polling 是本 Feature 的正式交互方式；
- 大规模 collector 重构或 `App.tsx` 重构；
- 搜索、筛选、分页系统重做；
- 修改 `dev.ps1`；
- 与本 Feature 无关的重构。

## Current verified constraints

- Headless POC 失败：综合批次核心成功率为 0/18，不得用于正式 collector。
- 屏幕外停放 POC 通过：可使用 Chromium CDP `Browser.getWindowForTarget` 和 `Browser.setWindowBounds`，目标坐标为 `(-32000, -32000)`，保持 `windowState=normal`。
- 召回 POC 通过：可恢复到合理可见位置并调用 `page.bring_to_front()`。
- 人工验证恢复闭环为 Conditional：没有稳定证明“验证 → 人工完成 → 自动续跑”，因此 V1 不承诺自动恢复。
- 页面层并发 2 仅为 Conditional POC，正式 `COLLECTION_LOCK` 仍覆盖现有单条采集路径，因此 V1 保持串行。

## User Stories

1. 作为竞品监控用户，我希望在列表中勾选多个监控中竞品，以便一次发起采集。
2. 作为竞品监控用户，我希望表头 checkbox 选择当前页全部可采集竞品，以便减少逐行点击。
3. 作为竞品监控用户，我希望表头 checkbox 在部分选中时显示 indeterminate，以便知道当前页并非全选。
4. 作为竞品监控用户，我希望已停止监控的竞品不能被选中，以便界面与后端的 inactive 语义一致。
5. 作为竞品监控用户，我希望列表只保留“详情”和“更多”，以便减少每行重复操作。
6. 作为竞品监控用户，我希望通过“采集选中（N）”采集当前选择，以便明确看到操作范围。
7. 作为竞品监控用户，我希望通过“采集全部监控中（M）”采集所有 active 竞品，以便不受当前页选择影响。
8. 作为竞品监控用户，我希望批次中的多个商品复用同一个 Chrome，以便减少启动窗口和 Profile 操作。
9. 作为竞品监控用户，我希望正常采集时 Chrome 不占用桌面可见区域，以便继续做其他工作。
10. 作为竞品监控用户，我希望一个商品超时或解析失败后批次继续，以便不因单个商品影响其他竞品。
11. 作为竞品监控用户，我希望看到成功数、失败数和每个失败商品的可读原因，以便判断是否需要重试。
12. 作为竞品监控用户，我希望 1688 要求验证时批次立即停止，以便不继续触发更多风控页面。
13. 作为竞品监控用户，我希望验证发生时 Chrome 自动回到前台，以便我能直接完成人工处理。
14. 作为竞品监控用户，我希望系统明确告诉我批次因人工验证停止，而不是笼统显示采集失败。
15. 作为竞品监控用户，我希望手动批量采集与 daily scheduler 不同时写入采集数据，以便保持快照和 CollectionRun 的一致性。
16. 作为竞品监控用户，我希望批次执行期间按钮和选择控件被禁用，以便避免重复提交。
17. 作为竞品监控用户，我希望刷新页面后可以重新读取当前批次真实状态，以便不中断对采集进度的观察。
18. 作为竞品监控用户，我希望 Backend 重启后不出现伪造的旧批次状态，以便清楚知道 V1 只保证进程内状态。
19. 作为竞品监控用户，我希望详情页已有的单条采集入口不因列表批量化而被误删；当前仓库若没有该入口，则本 Feature 不新增。

## User flows

### Select and collect

1. 用户打开竞品列表。
2. 用户勾选当前页一个或多个 active 竞品。
3. 页面显示“采集选中（N）”，N 为当前选中且 active 的数量。
4. 用户打开菜单并点击“采集选中（N）”。
5. 前端向批次 API 发送 selected 模式和 ID 列表。
6. 后端启动 Runner 并立即返回 running 状态，前端开始每 1～2 秒轮询 status。
7. Runner 在获得锁后再次校验竞品，并按请求顺序串行采集。
8. 每完成一个竞品，status 返回真实的 completed/total 进度。
9. Runner 结束后返回 completed，前端停止 polling、刷新竞品列表并显示汇总。

### Collect all active

1. 页面显示所有 active 竞品数量 M。
2. 用户点击“采集全部监控中（M）”。
3. 前端只发送 `mode=all_active`，不发送全部 ID。
4. 后端在 POST 校验阶段查询 `is_active=true`，冻结本批次 ID 集合。
5. 后端按稳定顺序串行采集集合中的竞品。

### Ordinary failure

当前竞品发生 timeout、parse failed、page unavailable、offer ID mismatch 或普通保存失败时：

1. 当前竞品的现有 `CollectionRun` 标记为 failed，并保存稳定的 error type/message。
2. 批次记录该竞品的失败结果。
3. 不启动新的 Browser/Context。
4. 继续使用当前 Browser/Context 处理下一个竞品。
5. 批次结束后返回部分失败汇总。

### Verification required

任意竞品触发 `verification_required` 时：

1. 当前竞品标记为需要人工处理，现有 `CollectionRun` 保存 `1688_verification_required`。
2. 不启动下一个竞品。
3. Runner 将状态更新为 `verification_required`，HTTP 请求已经结束时仍可通过 status 读取。
4. 将 Chrome 恢复到可见区域并 `bring_to_front()`。
5. 返回明确的人工验证结果，不自动刷新、点击、重试或续跑。

## Selection semantics

- checkbox 是列表表格的第一列，表头也有 checkbox。
- 选择范围严格是当前 API 返回的当前页；当前仓库尚未实现服务端分页，因此当前页等于现有完整列表。
- `is_active=true` 才是可选择对象。
- `is_active=false` 的 checkbox 始终 disabled 且不可 checked。
- 表头 checkbox 只统计当前页 active 竞品：
  - 全部当前页 active 已选：checked；
  - 部分当前页 active 已选：indeterminate；
  - 没有当前页 active 或没有选择：unchecked；没有 active 时 disabled。
- 表头 checkbox 不跨页，不持有 Gmail 式跨页选择状态。
- 选择集合在批次提交时冻结；批次运行期间后端不根据前端后续状态重新计算集合。
- 选中模式下，后端重新查询并校验全部 ID。任意 ID 不存在，整个请求在启动 Browser 前返回 `competitor_not_found`；任意 ID inactive，整个请求在启动 Browser 前返回 `competitor_inactive`。不静默跳过用户明确选择的对象。
- 重复 ID 由后端去重，保留第一次出现的顺序。
- `all_active` 模式由后端查询 active 竞品，前端不得先拉取 ID 再转发。
- 批次开始后新恢复的竞品不加入当前批次；新停止的竞品在实际轮到它时按 inactive 失败处理并继续后续对象。

## Batch collection semantics

### Recommended execution model

V1 推荐使用单进程、单批次、内存状态 Runner + HTTP polling：

1. `POST` 在 HTTP 请求中完成请求体校验、selected/all_active 目标校验和当前批次/锁检查。
2. POST 创建或替换一个进程内 `BatchRuntime`，通过 `asyncio.create_task(asyncio.to_thread(run_batch, ...))` 启动同步 Runner，然后立即返回 `202 Accepted` 和当前状态。
3. Runner 在 worker thread 中运行同步 Playwright、数据库 Session 和现有 collection service，不阻塞 asyncio event loop。
4. Runner 每完成一个竞品，就在状态锁内更新 `completed`、`succeeded`、`failed`、`remaining` 和该竞品结果。
5. `GET /api/competitors/collect-batch/status` 返回同一个进程内 Runtime 的状态；前端每 1～2 秒轮询一次。

这不是通用 Job Manager：只允许一个当前 Runtime，不排队、不保留历史、不新增队列或持久化任务实体。推荐使用可被 FastAPI lifespan 跟踪和等待的 `asyncio.create_task(asyncio.to_thread(...))`，不使用未被 Runner 状态统一管理的 `BackgroundTasks` 作为生命周期边界。`asyncio.to_thread` 与现有 daily scheduler 已使用的同步采集模式一致；Runner 必须持有可停止的 `threading.Event`，不能只依赖取消 asyncio Task，因为取消不会终止底层同步线程。

页面刷新行为：

- Backend 进程未重启时，刷新后前端调用 GET status，可以重新显示当前批次真实状态；
- Backend 重启后内存状态丢失，GET status 返回 idle；V1 接受这一点；
- 刷新不会创建第二个批次；如果当前 Runner 或 verification Chrome 仍占用采集资源，新的 POST 返回 `collection_in_progress`；
- completed 或 verification_required 状态可以保留为当前批次的最后状态，但不形成历史列表；
- 用户不得在 Runner 或 verification Chrome 活跃期间主动关闭 Backend。

### Ordering and isolation

- selected 模式按请求中去重后的 ID 顺序执行。
- all_active 模式按 `Competitor.id ASC` 执行，保证稳定且与 daily collection 的顺序一致。
- 同一批次内只允许一个竞品处于采集流程中。
- 每个竞品继续使用独立数据库 Session 和现有单竞品事务边界；Playwright 阶段不持有业务保存事务。
- 每个成功竞品仍写入 ProductSnapshot、SkuSnapshot、ChangeEvent、Competitor 当前字段和成功 CollectionRun。
- 每个失败竞品仍保留失败 CollectionRun；不得伪造 Snapshot 或成功状态。

### Batch result

POST 立即返回或 GET polling 返回的状态至少包含：

```json
{
  "status": "running",
  "total": 10,
  "completed": 3,
  "succeeded": 1,
  "failed": 2,
  "remaining": 7,
  "verification_required": 0,
  "current_competitor_id": 18,
  "browser_open": true,
  "items": []
}
```

`completed` 是已经得到终态结果的竞品数量，不是已启动数量；`completed + remaining = total`。正在处理的竞品只有在成功、普通失败或 verification_required 结果确定后才计入 completed。`current_competitor_id` 可为空；它只表示当前正在处理的对象，不计入 completed。`items` 返回已经得到终态结果的竞品的 `competitor_id`、`status`、`error_code` 和可读 `message`。

上面的 `items` 为了聚焦计数字段而省略具体数组内容；正式响应必须返回所有已经得到终态结果的 item。

- `status=idle`：没有当前批次，计数为 0。
- `status=running`：Runner 仍在处理目标集合，计数必须来自真实已完成结果。
- `status=completed`：Runner 已结束，可能是全成功、部分失败或批次级致命失败。
- `status=verification_required`：Runner 已停止启动新竞品，当前 Chrome 仍可能等待用户关闭。
- `outcome_code=success`：全部成功。
- `outcome_code=partial_failure`：至少一个普通失败，但没有验证中止。
- `outcome_code=verification_required`：因人工验证提前停止；`remaining` 表示未启动数量。
- `outcome_code=collect_failed`：Browser/Context 或批次级基础设施失败；未开始的竞品不伪造成失败。
- `outcome_code=collection_in_progress`：仅用于 POST lock probe 与 Runner 最终 acquire 之间发生极窄竞态时的安全终态；正常可观察的 busy 请求仍由 POST 直接返回 409。
- verification 不伪装成普通失败；其 `items` 状态为 `verification_required`，普通 `failed` 计数不包含该项。
- 没有 active 竞品时返回 `completed + total=0` 的 completed 状态，不启动 Browser。

### Runner lifecycle

状态转换固定为：

```text
idle
  → running
  → completed

running
  → verification_required (Chrome visible, Runner waiting for manual close)
  → verification_required (Chrome closed, lock released)
```

- `idle` 或上一次 terminal 状态可以被一次新的 POST 替换为 running；running 或 verification Chrome open 不能被替换。
- Runner 在每个竞品的 CollectionRun 进入 success/failed/verification_required 终态后更新计数；GET 不读取猜测值。
- Runtime 内部状态由一个 `threading.Lock` 保护，GET 读取不可变快照，Runner 只在锁内提交新快照；不允许返回中间半更新结构。
- `asyncio.Task` 只负责持有线程任务和 shutdown 等待；真实采集停止由 `threading.Event` 传递给同步 Runner。
- Runner 异常、Browser 启动失败或 shutdown 都必须经过同一个 finally 清理路径，更新 terminal 状态并释放 `COLLECTION_LOCK`。

## Browser lifecycle

当前 `collect_1688_product()` 自己创建和关闭 persistent Context，因此不能直接在循环中调用它来实现复用。正式实现需要做最小生命周期提取：让 collector 能在“外部已提供的批次 Context”中采集一页，同时保留现有单条入口的默认行为。

批次生命周期：

1. Runner 在自己的 worker thread 中获得 `COLLECTION_LOCK`；如果 POST 后发生竞态，Runner 不启动 Browser，并将状态安全地结束为 `status=completed, outcome_code=collection_in_progress`，前端提示用户稍后重试。
2. 在启动 Browser 前完成最终目标校验：selected 重新确认全部 ID 仍存在且 active；all_active 使用 POST 阶段由后端查询并冻结的 ID 集合，不接受前端传入的完整 ID。
3. 如果集合为空，直接返回，不启动 Browser。
4. 只调用一次 `sync_playwright()` 和 headed Chrome persistent context。
5. 使用现有专用 Profile：仓库根目录 `.browser-profile`。
6. `channel="chrome"`、`headless=False` 和现有启动参数保持不变。
7. 每个竞品使用一个新的 Page，串行完成导航、检查、解析、保存后关闭 Page；Browser/Context 继续复用。
8. 正常完成、普通失败或非验证型致命错误后，在 finally 关闭 Page、Context 和 Playwright。
9. 单条立即采集和 daily scheduler 继续使用现有单竞品生命周期，不因本 Feature 改成批次 Browser。

单条、daily、批次都继续使用同一 `.browser-profile`，因此 Profile lock 仍是实际运行约束；不得通过复制 Profile、输出 Cookie/Token 或新增 stealth 规避。

### Verification cleanup exception

若验证后必须允许用户直接操作 headed Chrome，则验证终态不能立即关闭该 Context，否则用户没有可操作的验证窗口。Runner 的推荐规则是：

- 触发验证后先更新内存状态为 `verification_required`，再召回窗口并 `bring_to_front()`；
- Runner 不再启动下一个竞品，不恢复采集，也不结束对 Browser 所有权的持有；
- `COLLECTION_LOCK` 在用户关闭验证 Chrome 前继续由 Runner thread 持有；
- 新的 POST 在 `runner_active=true` 或 `browser_open=true` 时返回 `collection_in_progress`，因此不会出现第二个批次争抢 Profile；
- 用户完成处理后手动关闭该 Chrome；Playwright Context close 事件唤醒 Runner 的清理等待；
- Runner 在同一 worker thread 中关闭剩余 Page/Context/Playwright，清除 `browser_open`，设置 `runner_active=false`，最后释放 `COLLECTION_LOCK`；
- 状态保留为 `verification_required`，但 Chrome 已关闭后允许用户重新发起新的批次；新批次开始时才重置当前状态。

这是正常“批次结束关闭 Browser”规则的明确验证例外。用户关闭 Chrome 是释放 Profile 和采集锁的人工边界，不是自动恢复信号；关闭后重新发起的批次由用户重新选择目标，V1 不自动计算或续跑剩余项。

如果 Backend shutdown 发生在验证等待期间，lifespan 必须设置 Runner stop event，关闭 Context 并在 finally 释放锁；进程重启后不恢复该批次。

## Window management

- 不使用 headless。
- 不新增 `pywin32` 或 Windows API 依赖。
- Browser/Context 启动后通过 CDP `Browser.getWindowForTarget` 获取窗口标识。
- 正常采集前通过 `Browser.setWindowBounds` 设置：`windowState=normal`、`left=-32000`、`top=-32000`；宽高保留合理值。
- 不最小化、不关闭窗口来实现后台效果。
- 触发验证时先设置 `windowState=normal`，再恢复到合理可见位置和尺寸（建议约 `40,60,1200,800`），最后调用 `page.bring_to_front()`。
- 正常批次不需要在关闭前恢复可见位置。
- CDP 调用失败属于批次级 Browser 错误；不得继续假装已完成后台停放。

## Verification handling

当前正式 detector 已识别登录页、验证 URL/title 和可见 `#nc_1_wrapper`。批次只消费已有 `VerificationRequiredError` 语义，不新增挑战识别或绕过逻辑。

一旦当前竞品抛出验证错误：

- 当前竞品的失败原因保留为 `1688_verification_required`；
- 批次状态为 `verification_required`；
- 后续竞品不再启动；
- 不把未启动竞品写成失败 CollectionRun；
- `completed` 增加当前需要人工处理的竞品，`remaining` 保留未启动数量；
- `browser_open=true` 且 `runner_active=true` 期间，GET status 必须持续返回 verification_required；
- 用户关闭 Chrome 后，状态仍为 verification_required，但 `browser_open=false`、`runner_active=false`，并释放 `COLLECTION_LOCK`；
- 前端提示：

> 1688 需要人工验证，本次采集已停止。请在浏览器中完成处理后重新发起采集。

V1 不判断用户是否已经完成验证，也不因页面刷新、滑块状态或 URL 变化自动继续。Chrome close 只用于资源清理和释放锁，不代表验证成功。

## Error handling

### Request-level errors

请求级错误发生在 Runner/Browser 启动前，不创建部分批次：

| 语义 | 现有/推荐 wire code | HTTP | 处理 |
|---|---|---:|---|
| 竞品不存在 | `competitor_not_found` | 404 | 整个请求拒绝，并返回相关 `competitor_ids` |
| 竞品 inactive | `competitor_inactive` | 409 | 整个请求拒绝，并返回相关 `competitor_ids` |
| 采集资源忙 | `collection_in_progress` | 409 | 不启动新 Runner/Browser |
| 请求体非法 | `invalid_batch_request` | 422 | 不启动新 Browser |

`competitor_not_found` 和 `competitor_inactive` 的错误 body 至少包含 `code`、`message` 和导致拒绝的 `competitor_ids` 数组。继续只使用 `collection_in_progress`，不新增 `collection_busy` wire code。

例如：

```json
{
  "code": "competitor_inactive",
  "message": "部分竞品已停止监控，无法采集",
  "competitor_ids": [15, 18]
}
```

### Per-item errors

以下属于单竞品结果，记录后继续：

- `1688_login_required`；
- `1688_page_unavailable`；
- `collection_timeout`；
- `collection_parse_failed`；
- `collection_partial_data`；
- `offer_id_mismatch`；
- `collection_save_failed`；
- `collection_failed`；
- 批次执行前后状态变化导致的 `competitor_inactive`。

每项只返回稳定、可读的 error code/message，不返回 traceback、HTML、Cookie、Token、请求头或原始外部响应。

### Batch-level outcomes

- `partial_failure` 只表示批次完成但包含普通失败。
- `verification_required` 表示批次因人工验证提前停止，优先级高于普通部分失败。
- Browser 启动、CDP 停放或无法建立采集上下文等错误属于 `collect_failed` 批次级错误；不得把未开始的竞品伪造成已失败 CollectionRun。

## API contract

### Start batch

```http
POST /api/competitors/collect-batch
Content-Type: application/json
```

Selected mode：

```json
{
  "mode": "selected",
  "competitor_ids": [12, 15, 18]
}
```

All-active mode：

```json
{
  "mode": "all_active"
}
```

约束：

- `mode` 只能是 `selected` 或 `all_active`；
- selected 必须提供至少一个正整数 ID；
- all_active 不依赖也不接受前端传入完整 ID 集合；
- selected 在启动 Runner/Browser 前一次性校验全部 ID；不存在或 inactive 都整体拒绝，不部分启动；
- all_active 由后端查询 `is_active=true`，冻结本次目标集合；
- POST 校验当前 Runtime，并以非阻塞方式探测现有 `COLLECTION_LOCK`；已有批次或已有采集返回 `collection_in_progress`；
- 通过校验后启动唯一进程内 Runner，POST 立即返回 `202 Accepted`；
- GET status 返回当前真实状态，前端每 1～2 秒轮询；
- Backend 进程重启后 Runtime 丢失，GET status 返回 idle；
- 无 active 竞品时 POST 返回 `202 Accepted` 的 completed 空状态，不启动 Browser；
- 忙、找不到竞品或 selected 包含 inactive 时返回对应请求级错误。

POST 和 GET 的状态响应至少包含：

```json
{
  "status": "idle | running | completed | verification_required",
  "outcome_code": "success | partial_failure | verification_required | collect_failed | collection_in_progress | null",
  "total": 10,
  "completed": 3,
  "succeeded": 1,
  "failed": 0,
  "remaining": 7,
  "verification_required": 0,
  "current_competitor_id": 18,
  "browser_open": true,
  "runner_active": true,
  "items": [
    {
      "competitor_id": 12,
      "status": "success | failed | verification_required",
      "error_code": null,
      "message": null
    }
  ]
}
```

`completed + remaining = total`。`succeeded + failed + verification_required` 等于 completed；`current_competitor_id` 只表示当前正在处理的对象，不计入 completed。`browser_open` 和 `runner_active` 用于区分 verification Chrome 仍被 Runner 持有，避免前端在锁尚未释放时重复发起。

响应不得添加前端推断字段、完整 Snapshot、HTML 或外部 1688 字段。单条详情页若未来已有独立采集入口，继续使用现有 `POST /api/competitors/{competitor_id}/collect`，不强制改为批次接口。

### Current status

```http
GET /api/competitors/collect-batch/status
```

- 无当前 Runtime 或 Backend 重启后：返回 `idle` 和全 0 计数；
- Runner 运行中：返回真实当前计数和已完成 item 结果；
- 普通完成：返回 `completed`，保留最后一次批次汇总，直到下一次批次启动；
- verification：返回 `verification_required`；Chrome 打开期间 `browser_open=true`、`runner_active=true`，Chrome 关闭清理后两个字段均为 false；
- status endpoint 不创建新任务、不触发采集、不改变数据库。

## Frontend states

列表页面使用最小状态：

- `idle`：可选择、可打开采集菜单；
- `running`：POST 已接受且 Runner 活跃；前端每 1～2 秒 GET status，checkbox、批次按钮、生命周期操作和单条操作均禁用；显示后端真实的“已完成 / 总数”，例如 `3 / 10`；
- `completed`：停止 polling，显示“批量采集完成：成功 S · 失败 F”，刷新列表；
- `verification_required`：停止把它当作普通失败，继续 polling 直到 `browser_open=false`，显示人工验证提示和已完成/剩余汇总；Chrome 关闭前批次入口保持 disabled。

轮询只展示后端返回的 `completed`、`succeeded`、`failed`、`remaining`，不使用前端循环次数推断进度。前端加载列表页时先读取 GET status，因此刷新后可以重新接管当前进程内批次。

页面右上角操作：

```text
[采集选中（N） ▼] [添加竞品]
```

菜单：

- `采集选中（N）`：N 为当前选中 active 竞品数；N=0 时 disabled；
- `采集全部监控中（M）`：M 为当前列表真实 active 数量；当前无分页，因此可从完整列表计算展示，但请求仍由后端查询 active 集合。

行级操作：

- active：`详情 | 更多`，更多包含停止监控、删除竞品；
- inactive：`详情 | 更多`，更多包含恢复监控、删除竞品；
- 行级“立即采集”移除；
- 当前仓库 `DetailPage` 没有单条采集按钮，本 Feature 不新增详情页采集入口，也没有入口需要删除。

批次完成后刷新竞品列表；成功、部分失败和验证终态都保留安全、可读的 Toast/提示。不得因为批次中单个竞品失败而把整个列表替换为错误页。轮询请求失败时保留当前已知状态并提示重试，不自动启动新批次。

## Locking / concurrency

- 批次实际采集使用现有进程内 `COLLECTION_LOCK`，不新建第二套采集互斥锁。
- POST 使用一个很短的非阻塞 lock probe 拒绝已知的单条采集或 daily scheduler；Runner 启动后必须再次 acquire，probe 与 Runner 之间即使发生竞态也不能并行采集。
- Runner 在启动 Browser、所有竞品采集、verification 窗口等待、窗口恢复和资源清理期间持有 `COLLECTION_LOCK`。
- `COLLECTION_LOCK` 必须由同一个 Runner worker thread acquire/release；不得在 POST 线程 acquire 后交给 Runner thread release。
- 现有 `RLock` 允许 Runner 在同一 worker thread 内复用单竞品保存流程；实现必须严格保持 acquire/release 配对。
- 另设一个只保护 `BatchRuntime` 字段的 `threading.Lock`，不承担采集互斥、不替代 `COLLECTION_LOCK`，只防止 POST、GET、Runner 和 shutdown 同时读写内存状态。
- 批次内部串行，不拆掉锁，也不改为并发 Page。
- 当前已有 Batch Runner 或 verification Chrome 时，批次 POST 返回 `collection_in_progress`。
- 批次 Runner 已持锁时，单条采集和删除返回 `collection_in_progress`。
- 单条采集或删除已持锁时，批次 POST 的 probe 返回 `collection_in_progress`；Runner 的再次 acquire 是最终安全边界。
- daily scheduler 获取同一把锁；批次运行时 daily cycle 记录 busy/interrupted 并退出当前 cycle，下一次 hourly due-check 再尝试。
- daily scheduler 运行时，手动批次不会等待或排队，而是返回 busy；用户稍后重试。
- PATCH monitoring 当前不是采集入口，不为它引入新的锁系统；批次实际处理每个 ID 时仍须重新读取 `is_active`，状态变化按 per-item 失败处理。

## Daily scheduler interaction

daily scheduler 保持现有规则：启动后约 30 秒首次 due-check，之后每小时检查，按 `CollectionRun.started_at` 的 24 小时窗口决定 active 竞品是否到期。

- 不修改 daily scheduler 的采集顺序、独立 Session、失败后继续和 shutdown 语义。
- 不让 daily scheduler 与手动批量共享一个 Browser；本 Feature 只要求手动批次内部复用 Browser。
- 手动批次持锁时，daily scheduler 不启动新的竞品，记录当前 cycle 被 busy 中断，下一周期再试。
- daily scheduler 持锁时，手动批次返回 `collection_in_progress`，不等待、不排队、不启动 Browser。
- 两者都继续复用现有 `CollectionRun`；失败尝试计入 daily 的 due 语义，不新增批次记录。

## Data model impact

- 不新增表、字段、关系或 index。
- 不新增 Alembic migration。
- 不创建 BatchJob、BatchItem 或任务历史。
- 每个已启动竞品继续产生现有 `CollectionRun`；成功继续产生 Snapshot/SKU/ChangeEvent，失败只更新该 Run 的失败字段。
- 进程内只保留一个当前 `BatchRuntime`，包含目标 ID、状态计数、逐项结果、Runner active 标志、verification Browser ownership 和 stop event；这些数据不写数据库。
- 批次汇总通过 GET status 暴露，不作为历史事实保存；completed/verification_required 只保留最后一次当前状态，不形成历史列表。
- 未启动的剩余竞品不写入假的 CollectionRun。

## Dependencies

不新增依赖。继续使用现有 FastAPI、SQLAlchemy、Playwright、React、TypeScript 和 Vitest；CDP 能力通过 Playwright 已有连接使用。

## Files likely to change

实现获批后，预计只修改以下正式代码和测试：

- `backend/app/collection/collector_1688.py`：提取可复用 Context 的最小 collector 边界，保留 headed、Profile、错误检测和单条默认行为；
- `backend/app/collection/service.py`：批次编排、结果汇总、锁边界和 shared Context 调用；
- `backend/app/competitors.py`：批次 request/response schema 与 endpoint；
- `backend/app/main.py`：在 FastAPI lifespan 中等待 Runner、发送 stop event 并确保 Browser/Context 与锁清理；
- `frontend/src/App.tsx`：checkbox、批次菜单、批次调用和四种页面状态；
- `frontend/src/App.css`：checkbox、菜单、批次状态和布局的最小样式；
- `frontend/src/App.test.tsx`：选择语义、菜单计数、状态和错误展示测试；
- backend 现有 collection/API 测试文件：补充批次行为测试；
- 如现有测试边界证明确有必要，才最小修改 `backend/app/collection/daily.py`；不改变其业务语义。

明确不修改：数据库模型、Alembic、requirements、`dev.ps1`、POC 文件和无关页面。

## POC reference boundary

可参考但不可直接搬入正式代码：

- `poc_background_batch_collection.py`：只参考 CDP 窗口移动/召回、headed Context 复用和验证暂停观察；它绕过正式 Service、数据库事务和 API，不是生产编排。
- `poc_headless_collection.py`：只作为 headless FAIL 的证据；不得导入、复用或把 `headless=True` 带入正式 collector。

POC 中的样本数量、页面层并发、network 监听结果和临时超时控制不能被当作正式业务契约。正式实现继续使用现有 Parser、CollectorError 边界、Profile 路径和安全错误语义。

## Acceptance criteria

1. 列表每行最左侧有 checkbox，inactive checkbox disabled。
2. 表头 checkbox 只作用于当前页 active 竞品，并正确呈现 checked/indeterminate/unchecked。
3. 行级“立即采集”已移除，详情和更多操作仍可用。
4. `采集选中（0）` disabled；选中数量与真实 active 选择一致。
5. `采集全部监控中（M）` 发送 `all_active`，不发送完整 ID 列表。
6. POST 校验通过后立即返回 `202`，GET status 能返回当前真实状态和 `completed/total` 进度。
7. 同一进程同一时间最多一个 Batch Runner；重复 POST 返回 `collection_in_progress`。
8. 页面刷新后，在 Backend 未重启时可以通过 GET status 重新显示当前批次；Backend 重启后返回 idle。
9. 批次一次启动一个 headed Chrome/Context，串行处理多个竞品，正常完成后关闭资源。
10. 正式 collector 不使用 headless，不引入并发 2，不拆掉 `COLLECTION_LOCK`。
11. 普通竞品失败会记录失败并继续后续竞品。
12. 批次状态返回总数、completed、succeeded、failed、remaining、verification 状态和逐项安全原因。
13. 任意 `verification_required` 会阻止后续竞品启动、召回 Chrome、置前并展示明确提示。
14. verification Chrome 未被用户关闭前，不允许第二个批次、单条采集或 daily scheduler 争抢 Profile；关闭后 Runner 清理并释放锁。
15. 手动批量与单条采集、删除、daily scheduler 互斥，冲突返回稳定 `collection_in_progress`。
16. 不新增数据库表、字段、migration 或依赖。
17. 详情页现有单条入口（若未来存在）不被批量 Feature 强制移除；当前仓库没有该入口，因此不新增。

## Testing decisions

测试外部行为和 API/UI 契约，不测试某个具体私有 helper 的实现细节。

### Backend

- POST 在 selected/all_active 请求体校验、去重、顺序和后端 active 查询完成后立即返回 202；
- not found、inactive、busy 的 HTTP 状态和稳定错误 body；
- selected 缺失 ID 或 inactive ID 会整体拒绝，并返回相关 ID；
- GET status 在 idle、running、completed、verification_required 四种状态下返回正确计数；
- Runner 只允许单进程单批次，重复 POST 返回 `collection_in_progress`；
- `BatchRuntime` 的 POST/GET/Runner/shutdown 并发读写由状态锁保护，状态不会出现负数、跳数或 `completed + remaining != total`；
- `asyncio.create_task(asyncio.to_thread(...))` 启动同步 Runner，真实进度在每个竞品终态保存后更新；
- 只启动一次 Playwright/Context，并按串行顺序处理多个竞品；
- 普通失败继续后续竞品，最终 `partial_failure` 汇总正确；
- verification 在当前竞品后停止，后续 collector 不被调用，状态可在 POST 返回后通过 GET 读取；
- CDP 隐藏、召回、`bring_to_front` 的调用契约和异常清理；
- verification Chrome 打开时新 POST、单条采集和 daily scheduler 都被同一锁拒绝；用户关闭 Chrome 后 Context close 事件触发清理并释放锁；
- Runner stop event 和 FastAPI lifespan shutdown 能关闭 Browser/Context，不遗留锁；
- 单条采集事务、失败 CollectionRun、成功 Snapshot/ChangeEvent 回归；
- batch 持锁时 single/daily/delete 的 busy 行为，以及 daily 持锁时 batch 的 busy 行为；
- empty all_active 不启动 Browser、不写数据库；
- no migration/schema diff。

### Frontend

- 当前页 active/inactive checkbox 选择和表头 indeterminate；
- 选中数 N、active 总数 M、两个菜单项的 disabled 语义；
- 批次请求 body 不循环调用单条 endpoint；
- POST 接受后按 1～2 秒轮询 GET status，使用真实 `completed/total` 显示 `3 / 10` 等进度；
- running 时控件禁用，completed/partial_failure/verification_required 文案正确；
- 页面刷新后先读取 GET status 并重新显示当前批次；Backend 重启后正确显示 idle；
- verification Chrome 未关闭前批次入口保持 disabled，关闭后允许重新发起；
- 列表刷新、错误提示和安全 fallback；
- 现有生命周期菜单、详情入口和列表加载状态不回归。

### Manual acceptance

至少用真实本地 Chrome Profile 验证：

- 多个真实竞品一次批次只出现一个 headed Chrome；
- Chrome 移出桌面后页面仍能采集；
- 普通失败后后续竞品仍执行；
- 验证页出现时 Chrome 可召回、置前，且没有启动下一个竞品；
- 不输出 Cookie、Token、HTML、headers 或 Profile 状态。

## Risks

1. 1688 风控状态会随访问频率和 Profile 状态变化；headed POC 的一次成功不能保证长期稳定。
2. persistent Profile 可能被普通 Chrome 或遗留验证窗口占用，导致 Browser 启动失败。
3. Runner 仍受单进程 worker、线程异常和 Backend shutdown 影响；V1 不承诺跨进程或重启恢复。
4. verification Chrome 在用户关闭前持续占用一个 Runner thread 和 `COLLECTION_LOCK`，这是为了避免 Profile 争抢。
5. 当前 `COLLECTION_LOCK` 是进程内锁，多进程/多实例部署不在 V1 支持范围。
6. 批次循环会放大单个商品页面结构变化的影响，但每个商品仍通过现有 Parser 和 error boundary 隔离。

## Open questions

当前没有阻塞性的产品决策：本次已确定使用内存 Runner + polling、selected 整体校验、复用 `collection_in_progress`，并接受用户关闭 verification Chrome 后重新发起批次。

## Further Notes

- 本 Spec 不授权实现、提交或推送。
- 本 Spec 不发布到 issue tracker；本轮交付边界仅为仓库内正式 Feature Spec。
- 所有未采集价格、库存和其他外部字段继续遵守现有 `NULL`/“未采集”语义，不因批次而补造数据。
- 批量化只改变采集触发方式和 Browser 生命周期，不改变现有快照、ChangeEvent、CollectionRun 的事实语义。
