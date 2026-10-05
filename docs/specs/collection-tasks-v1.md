# 采集任务 V1 Feature Spec

状态：待实现；本轮只定义正式 Feature Spec，不修改业务代码。

## Problem Statement

左侧“采集任务”目前仍是占位页面。用户已经可以从 Dashboard 或竞品列表发起批量采集，但缺少一个专门的运行中心来观察当前批次、识别 1688 验证和冷却异常，也不能从一个页面查看最近持久化的单商品采集尝试及其失败原因。

当前系统已经有两类不同事实：

- `BatchRuntime` 是当前 Backend 进程内、临时存在的批次运行状态；
- `CollectionRun` 是某个商品的一次采集尝试记录，不是 batch，也没有 `batch_id`。

V1 需要把这两类事实清楚地呈现给用户，但不为它们建立第三种事实来源，也不通过时间接近程度把多个 `CollectionRun` 猜测性地聚合成历史 batch。

## Solution

将左侧“采集任务”占位页升级为只读的采集运行中心：

1. 页面顶部消费现有 `GET /api/competitors/collect-batch/status`，展示当前进程内 `BatchRuntime` 的真实状态、进度、当前商品、item 结果和异常。
2. 当前商品只使用现有 `GET /api/competitors` 返回的竞品资料进行映射，复用 `title`、`offer_id`、`shop_name` 和 `ownership`，不新增 task product API。
3. 页面下方新增只读 `GET /api/collection-runs`，从真实 `CollectionRun` 查询历史单商品采集尝试，并通过当前 `Competitor` JOIN 提供商品展示字段、身份和店铺信息。
4. 搜索、身份/状态筛选、排序和分页全部由 Backend 完成；Frontend 只渲染当前页，不下载完整历史后再本地分页。
5. 当前批次区与历史记录区独立维护 loading、error 和 empty 状态。任一请求失败都不遮蔽另一块已经成功取得的内容。

V1 不新增持久化 `BatchJob`/`BatchTask`，不改变现有采集 Runner、冷却或自动恢复状态机，也不在本页增加新的采集触发入口。

## Goals and User Stories

1. 作为采集用户，我希望进入“采集任务”后能看到当前批次状态，以便知道系统是否正在工作。
2. 作为采集用户，我希望看到 `completed / total`、成功数、失败数和剩余数，以便判断批次进度。
3. 作为采集用户，我希望在运行中看到当前商品及已经完成的 item 结果，以便定位批次停留位置。
4. 作为采集用户，我希望当前商品显示标题、Offer ID、店铺和身份，以便确认采集对象没有错位。
5. 作为采集用户，我希望验证触发时看到明确的人工处理提示，以便知道为什么批次没有继续。
6. 作为采集用户，我希望冷却状态展示后端返回的剩余时间和自动恢复次数，以便理解当前是否会继续运行。
7. 作为采集用户，我希望批次完成后看到成功、失败、验证中止、结果码和逐商品结果，以便评估本批次结果。
8. 作为采集用户，我希望 Backend 重启后页面显示“当前无采集任务”，而不是把历史记录伪装成最近 batch。
9. 作为采集用户，我希望查看最近每一次单商品采集尝试，以便追溯实际发生过的成功或失败。
10. 作为采集用户，我希望按标题、Offer ID 或店铺搜索历史，以便快速找到目标商品。
11. 作为采集用户，我希望按成功/失败和我方/竞品筛选历史，以便集中处理异常或查看某类商品。
12. 作为采集用户，我希望历史表按最近开始时间排序，并能翻页，以便结果稳定、可持续浏览。
13. 作为采集用户，我希望失败记录直接显示简短原因，并能展开较长的安全错误信息，以便快速判断下一步。
14. 作为采集用户，我希望历史为空时看到“暂无采集记录”，而不是误以为当前 Runtime idle 代表没有历史。
15. 作为采集用户，我希望当前状态请求失败时仍能查看历史，或历史请求失败时仍能查看当前状态，以便局部故障不会隐藏所有信息。
16. 作为采集用户，我希望页面不会展示 Cookie、Token、HTML、headers、浏览器 Profile 或原始异常堆栈，以便采集敏感信息不泄露。

## Implementation Decisions

### 1. 现有运行时 seam 与职责

- 当前批次唯一来源继续是 `GET /api/competitors/collect-batch/status` 和现有 `BatchRuntime`。
- 不新增第二套 runtime、queue、WebSocket、SSE、任务状态机或批次持久化模型。
- 页面消费现有状态：`idle`、`running`、`cooling_down`、`verification_required`、`completed`。
- 页面直接消费 Backend 返回的 `total`、`completed`、`succeeded`、`failed`、`remaining`、`verification_required`、`current_competitor_id`、`browser_open`、`runner_active`、`auto_resume_attempt`、`auto_resume_max`、`cooldown_remaining_seconds`、`items` 和 `outcome_code`。
- `cooldown_remaining_seconds`、自动恢复次数和进度均以每次 status 响应为准。Frontend 不使用本地计时器推算后端剩余时间，不根据请求耗时修正数值。
- 现有 status polling 是最高层的运行状态 seam。实现应继续复用其轮询和终态刷新边界；不得为采集任务页创建第二个批次状态请求或第二个 Runtime。

### 2. 页面标题与入口

页面标题固定为“采集任务”，说明固定为“查看当前采集进度、历史记录与失败原因。”

V1 只把现有左侧入口从占位页替换为运行中心。页面不新增“立即采集”按钮、不新增批次 POST、不迁移 Dashboard 的“立即采集”。Dashboard 现有入口保持原位置和行为。

### 3. 当前任务区域

#### `idle`

显示“当前无采集任务”。该状态只表示当前 `BatchRuntime` 没有批次，不推断历史是否为空，也不通过 `CollectionRun` 伪造最近批次。

#### `running`

显示：

- “采集中”；
- `completed / total` 和进度条；
- `succeeded`、`failed`、`remaining`；
- 当前商品；
- 已完成 item 列表。

进度条的数值直接来自 `completed` 和 `total`。item 的状态、错误码、短消息和 outcome 直接来自 status contract；不得把尚未完成的商品提前计入完成数或失败数。

#### `cooling_down`

明确显示：

- 1688 验证已触发；
- 浏览器已关闭；
- `cooldown_remaining_seconds` 对应的冷却剩余时间；
- 自动恢复 `auto_resume_attempt / auto_resume_max`；
- `completed` 和 `remaining`；
- 当前 competitor（若 status 返回 `current_competitor_id`）。

倒计时每次随 Backend status 刷新，不在浏览器本地自减。页面不得提供手动加速、绕过或改变冷却的操作。

#### `verification_required`

明确告诉用户“需要人工完成 1688 验证”，并显示当前商品及已有进度。页面不增加自动验证、跳过验证、绕过验证或重跑当前项按钮。当前状态是否仍持有浏览器和 Runner 以 `browser_open`、`runner_active` 为准。

#### `completed`

直接展示最近一次仍保存在内存中的 batch status：

- `total`、`succeeded`、`failed`、`verification_required`；
- `outcome_code`；
- item 结果。

`completed` 不是历史 batch。Backend 重启后 Runtime 回到 `idle`，页面必须尊重该事实，不用 CollectionRun 补造“最近一次批次”。

### 4. 当前商品映射

status 只提供 `current_competitor_id`。页面优先复用现有 `GET /api/competitors` 的响应，将该 ID 映射为：

- `title`；
- `offer_id`；
- `shop_name`；
- `ownership`。

映射不到时不得伪造商品名称、店铺或身份；显示可识别的缺失值，并保留真实 ID。不得为了补充名称而创建第二套 task product API。若 Spec Review 发现现有竞品列表 seam 在当前实现中无法安全复用，再单独提出调整，不在本 Spec 隐式扩大接口范围。

### 5. 历史 API：`GET /api/collection-runs`

新增一个只读 API。它读取真实 `CollectionRun`，不创建或修改采集事实。

响应为分页对象：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

每个 item 至少包括：

- `id`；
- `competitor_id`；
- 当前 `Competitor.ownership`；
- 当前 `Competitor.title`；
- 当前 `Competitor.offer_id`；
- 当前 `Competitor.shop_name`；
- `started_at`；
- `finished_at`；
- `status`；
- `error_type`；
- `error_message`；
- `duration_seconds`。

查询通过 `CollectionRun` JOIN 当前 `Competitor` 获取展示信息。`CollectionRun` 自身字段必须按数据库事实返回，不能被当前 Competitor 的新标题、店铺或身份覆盖，也不能推断出不存在的错误、结束时间或 batch 关系。

当前删除语义必须先在真实模型和 FK 行为中确认：如果删除竞品时现有流程同时删除其 CollectionRun，则 V1 保持该语义；如果 FK 阻止删除，则保持该约束。不得凭空设计 orphan fallback、匿名商品或历史快照表来填补不存在的关联。

#### 查询参数

- `search`：可选；Backend 在 `title`、`offer_id`、`shop_name` 上执行匹配。空白输入按无搜索处理。
- `status`：`all`、`success`、`failed`。`all` 返回现有 CollectionRun 状态；若真实存在 `running` 且未结束，必须按事实返回。
- `ownership`：`all`、`self`、`competitor`。
- `page`：从 1 开始；非法值返回稳定的参数错误，不静默使用不存在的页码。
- `page_size`：V1 固定 20，或由 Backend 固定默认 20；不提供用户可调 page size。

排序固定为 `started_at DESC`，其次 `id DESC`。搜索、过滤、总数计算、排序和分页必须在 Backend 执行，禁止先返回完整历史再由 Frontend 分页。

#### 时间与错误字段

- 页面沿用项目现有时间展示规则。
- `duration_seconds` 只有 `finished_at` 非空时才计算。
- 真实存在的 running CollectionRun 若 `finished_at` 为空，耗时显示“进行中”或“—”，不得写入假结束时间。
- `error_type` 和 `error_message` 只展示现有稳定、已脱敏的内容。
- API/UI 均不得输出 Cookie、Token、HTML、headers、浏览器 Profile、原始异常堆栈或其他未脱敏运行上下文。
- 成功记录不要生成“无错误”等没有信息量的文案。

### 6. 历史记录区

建议表格列为：

| 列 | 内容 |
| --- | --- |
| 状态 | `CollectionRun.status` 的用户可读状态 |
| 商品 | 标题、Offer ID、店铺 |
| 身份 | `self` 或 `competitor` |
| 开始时间 | `started_at` |
| 耗时 | `duration_seconds`，或进行中/— |
| 结果 | 成功无额外噪音；失败显示简短原因 |

失败原因直接来自安全的 `error_type` / `error_message`。较长的 `error_message` 可以通过详情展开或 Dialog 查看，但不新增独立 Detail API；列表 contract 已包含所需字段。详情交互不得扩大可见字段集合。

历史为空时显示“暂无采集记录”。该空状态只由 `GET /api/collection-runs` 的真实结果决定，不由当前任务区的 `idle` 状态决定。

### 7. 独立数据状态

当前任务区和历史记录区分别处理：

- loading：保留各自的加载状态，不阻塞另一块的展示；
- error：显示可重试的局部错误，不清空另一块已经成功加载的数据；
- empty：当前任务区使用 idle 语义，历史区使用“暂无采集记录”；
- normal：当前任务和历史表分别按各自的 contract 渲染。

当前 status 请求失败时，历史记录仍可独立展示；历史 API 请求失败时，当前 status 仍可独立展示。刷新或重试只重新请求对应的数据源，不借用另一个数据源猜测结果。

### 8. 数据模型与兼容性

V1：

- 不新增数据库表；
- 不新增字段；
- 不新增 migration；
- 不新增 `batch_id`；
- 不修改 `CollectionRun` 的“单商品一次采集尝试”语义；
- 不通过 `started_at` 接近程度推断 historical batch；
- 不改变现有 `BatchRuntime`、`COLLECTION_LOCK`、cooling 或 auto-resume 状态机；
- 不改变单商品采集、daily scheduler 或 Dashboard 的既有数据写入行为。

历史 API 是查询 seam，不能因为展示需求反向修改 CollectionRun 的事实字段或生命周期。

## Testing Decisions

测试只验证外部可观察的 API/UI contract、数据一致性和独立状态行为，不测试组件内部实现细节，不复制现有 BatchRuntime 全部状态机测试，也不为本 Feature 引入新的测试框架、队列或持久化 fixture。

### Backend

优先使用 FastAPI TestClient + temp SQLite，构造真实 `Competitor`、`CollectionRun` 数据并通过 API 验证：

1. 默认按 `started_at DESC`、其次 `id DESC` 排序；
2. `status=success`、`status=failed` 和 `status=all` 过滤；
3. `ownership=self`、`ownership=competitor` 和 `ownership=all` 过滤；
4. `search` 分别匹配 title、offer_id、shop_name；
5. page 从 1 开始、固定 page size 20、total/page/page_size 正确；
6. 成功和失败记录的字段完整，失败原因来自真实 `error_type` / `error_message`；
7. `finished_at` 存在时 `duration_seconds` 正确；
8. `finished_at=NULL` 的 running CollectionRun 不假造结束时间，耗时为进行中或 — 的 contract 值；
9. self 与 competitor 混合记录能正确 JOIN 当前 Competitor 展示信息；
10. 查询不会改变任何 CollectionRun 字段或创建额外记录；
11. 当前删除/FK 语义不会被 API 擅自改写；不实现未经证实的 orphan fallback；
12. 不新增 migration，且 schema 与现有 migration 保持一致。

现有 `GET /api/competitors/collect-batch/status` 与 BatchRuntime 的测试继续保护运行时事实；本 Feature 只补充页面所需的历史查询 contract，不把 batch 历史语义写进数据库测试。

### Frontend Vitest

至少覆盖页面外部渲染和请求行为：

1. `idle`；
2. `running`：计数、进度条、当前商品和已完成 item；
3. `cooling_down`：验证提示、浏览器已关闭、Backend 倒计时、自动恢复 X/Y、completed/remaining 和当前商品；
4. `verification_required`：人工验证提示、当前商品和已有进度，不出现绕过/跳过按钮；
5. `completed`：汇总、`outcome_code` 和 item 结果；
6. current competitor 信息通过现有竞品数据映射，缺失时不伪造名称；
7. history loading、error、empty 和 normal；
8. title/offer_id/shop_name 搜索、status/ownership 筛选和 Backend 分页参数；
9. 下一页、上一页、第一页/最后一页边界及 total/page/page_size 展示；
10. 失败记录展示安全的简短错误原因，成功记录不出现“无错误”噪音；
11. `finished_at=NULL` 的记录显示进行中或 —；
12. Backend status 与 history 其中一边失败时，另一边仍正常显示；
13. idle 时显示“当前无采集任务”，历史为空时独立显示“暂无采集记录”；
14. 状态 polling 消费 Backend 返回的 `cooldown_remaining_seconds`，不由 Frontend 自行推算。

### Playwright

只补一个核心页面流程，不把 Backend 状态矩阵复制到 E2E：

```text
进入采集任务
→ 当前状态区域可见
→ 历史记录列表可见
→ 状态筛选可以工作
```

E2E 使用现有 fail-closed `/api/**` mock 约定和最小固定 fixture；不连接真实 Backend、SQLite、1688、浏览器 Profile 或验证码流程。状态矩阵留在 Vitest/Backend contract 测试中。

## Out of Scope

- `BatchJob` / `BatchTask` 数据库表；
- 历史 batch 聚合；
- 通过 `started_at` 接近程度推断历史 batch；
- 跨 Backend 重启恢复当前 batch；
- WebSocket / SSE；
- Redis / Celery / queue；
- 停止、暂停、取消 batch；
- 手动跳过 competitor；
- 重跑失败项；
- 自动验证码；
- 修改 cooling / auto-resume 状态机；
- 修改 daily scheduler；
- 将 Dashboard“立即采集”迁移到本页；
- 新的采集触发 API；
- 导出记录；
- 统计报表；
- 独立历史详情 API；
- 新的 task product API；
- 大规模 `App.tsx` 重构；
- 与本功能无关的 UI、数据库、Collector 或基础设施重构。

## Further Notes

### 事实边界

当前批次和历史记录必须在 UI 文案、接口和测试中保持不同命名：

```text
GET /api/competitors/collect-batch/status
    → 当前进程内 BatchRuntime，可能因 Backend 重启回到 idle

GET /api/collection-runs
    → 持久化 CollectionRun 单商品采集尝试
```

历史记录可以帮助用户定位单商品失败，但不能反推出某个 batch 的边界、顺序、总数或 outcome_code。只有 BatchRuntime 的 status 响应能提供当前/最近内存 batch 的这些信息。

### Spec 冻结流程

本 Spec 的交付流程为：

1. 基于当前仓库真实实现和现有 seam 完成本文件；
2. 自检文档范围、API、状态、测试边界和 Out of Scope；
3. 只提交 `docs/specs/collection-tasks-v1.md`；
4. Push 到 `main`；
5. 进入 ChatGPT Spec Review；
6. Review 通过后再冻结 Spec，后续实现另开明确授权的实现阶段。

本轮不发布 issue tracker，不添加 `ready-for-agent` label，不修改业务代码或其他文档。
