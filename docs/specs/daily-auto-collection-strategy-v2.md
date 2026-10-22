# 每日自动采集调度策略 V2

状态：已完成 Spec Review，授权按本文实施。

本文在自动采集调度范围内取代 [`daily-auto-collection-strategy-v1.md`](daily-auto-collection-strategy-v1.md)。V1 中关于“仅 rolling_24h 与单时间 fixed_daily”“四项自动设置”“固定任务每天至多一次”“多个每日时间不在范围内”的限制均不再适用。V1 没有被本文明确替代的边界继续有效，特别是现有系统设置、唯一 Batch Runner、BatchRuntime、COLLECTION_LOCK、CollectionRun、单进程本地时区语义、采集风控、完整 PUT、原子保存、shutdown 和不新增持久化任务体系。

## Spec Review：现状和决策

指定基线 `047b9560e98b56a714484ffec96c78e3a787feb1` 已有：

- `system_settings` 中六项节奏/风控设置和四项自动采集设置，完整 PUT 在同一事务保存；读取单次查询设置并对旧值使用默认值。
- `rolling_24h` 与单个 `fixed_daily`；固定策略按运行后端电脑本地日期构造计划边界，CollectionRun 的正式尝试（含失败）决定资格。
- FastAPI lifespan 中可中断的分钟级 scheduler；每次检查读取当前配置，在 collection slot 内再次读取配置和候选，预留唯一 BatchRuntime，并使用唯一 COLLECTION_LOCK。
- 设置页已有懒加载、独立草稿/保存状态、完整 PUT 和两种策略的条件展示。

V2 只扩展策略数据和该区域 UI。每个每日计划点是独立 occurrence；一个 occurrence 最多 reservation/启动一个自动 Batch。Batch 忙时不积累历史队列，只保留最新到期且仍适用的 occurrence，并在 slot 内重新查询 active 状态及正式采集记录。每个商品在 occurrence 计划时间或之后存在 CollectionRun 即视为该 occurrence 已尝试，成功、失败、手动单品、添加商品首次采集、手动 Batch 和自动 Batch 一视同仁。计划点之前的尝试不阻止后续计划点再次采集。

## 用户可配置策略

1. `rolling_24h`：完全保留当前逻辑；无 CollectionRun，或距最近一次正式尝试至少 24 小时的 active 我方商品和竞品才符合资格。
2. `fixed_daily`：每天配置 1–8 个严格 `HH:mm` 的本地时间点；不重复，API 与数据库的规范列表按时刻升序。旧版只有 `auto_collection_time=HH:mm` 时等价于只配置该一个时间点。已保存的单时间值在 V2 读取时生成一个元素的列表，不写回迁移。
3. `fixed_interval`：配置每日开始时间 `HH:mm`、间隔小时数 `1–24` 和每日次数 `1–12`。第 n 个计划时间为开始时间加 `n × interval` 小时（n 从 0 开始）。配置必须保证最后一个计划点早于次日 00:00；不静默截断或滚入次日。默认开始时间 09:30、间隔 4 小时、次数 3（09:30、13:30、17:30）。

两种固定策略都使用 `catch_up` / `skip`：

- `catch_up`：若本进程首次启用/切换到固定策略或 Backend 启动时已有计划点到期，只考虑当天最新到期 occurrence；可立即尝试其仍符合资格的商品，不为更早 occurrence 建队列。
- `skip`：首次启用/切换到固定策略或 Backend 启动时若最新计划点已到期，则当天跳过，等待下一个未来计划点。若本进程在一个计划点前已启用策略，则该 occurrence 到点后进入进程内待执行状态；Runner 忙时后续分钟检查可重试。新计划点到期时旧 pending 被最新 occurrence 取代。跨日、关闭自动采集、离开固定策略或修改任何调度字段均清除旧 pending；配置变更后的 skip 按新的生命周期重新判断。
- occurrence 因 Runner 忙而延后时，catch_up 与 skip 均可在本进程内等待重试；差别只在进程/配置生命周期于计划点之后开始时是否补采。候选每次都以所保留 occurrence 的边界重新计算，因此该边界之后已有正式尝试的商品会排除。
- 日期边界以 Backend 本地时区计算。已过期日期的 pending 永不跨日执行。CollectionRun naive 时间继续按 UTC 解释。

## 设置/API 与存储

继续使用 `GET/PUT /api/settings/competitor-monitoring` 和现有 `system_settings`；不新增表、migration 或 API。保持既有六项 Batch 字段及设置字段名/含义。扩展完整设置对象，包括策略枚举和固定间隔字段；旧 `auto_collection_time` 在 `fixed_daily` 下兼容为单时间，并作为 `auto_collection_times` 最早时间的兼容镜像，在 `fixed_interval` 下表示开始时间。时间列表严格校验类型、长度、格式、唯一性并排序。区间配置严格拒绝 bool、字符串、浮点数和区间外整数；组合校验必须保证所有派生时间留在当天。坏的历史新增值按字段默认值处理、不写回。

保留旧 `auto_collection_time` 存储值并兼容为 V1 的单时间配置；固定多时间列表使用新增 key。新读取以有效列表 key 为准，否则回退单值 key。固定间隔字段使用新增 key。PUT 必须校验完整 payload 后，在一个事务中写入扩展的完整 contract；失败整体 rollback。自动调度配置不进入 BatchConfig；BatchConfig 仍只从六个既有节奏/风控字段显式投影，且在 reservation 时冻结。

## 调度和互斥

- 所有 active 我方商品和竞品按既有稳定 ID 顺序成为候选；不改手动采集和添加商品语义。
- 每分钟读取当前设置。计划点、配置变化和进程启动状态只用于确定最新到期 occurrence；资格按当前正式 CollectionRun 与 active 状态计算。
- 先做锁外快速预判；最终资格判断必须在成功取得现有 COLLECTION_LOCK 后完成，且必须重新读取配置、active 商品和 CollectionRun，再 reserve BatchRuntime/CollectionBatch。不得加入另一把锁或 runner。
- 每个 occurrence 具有稳定 `scheduler_occurrence_key`，分钟检查不得重复触发同一个 occurrence。Occurrence 因忙被保留时不产生队列；新 occurrence 替代旧 occurrence。自动 Batch 继续使用 `trigger_kind=scheduled`、CollectionBatch、CollectionRun 与现有运行状态。
- 已运行 Batch 使用启动时冻结的 BatchConfig；设置热更新只影响之后的 occurrence。关掉自动采集不取消运行中 Batch。shutdown 唤醒 scheduler 并阻止新 reservation；既有 Runner 继续协作式停止。

## 前端

仅修改“系统设置 → 竞品监控 → 自动采集”现有区域：互斥策略选项、策略简述和后端电脑本地时间说明；`fixed_daily` 为 1–8 项时间列表并可新增/删除；`fixed_interval` 展示开始时间、小时间隔和次数上限；错过计划只在固定策略下显示。校验错误、完整 PUT、独立保存状态、草稿保留、加载和重试语义继续使用现有实现。

## 验收

扩展现有后端设置/调度测试和 `competitor-monitoring-settings.spec.ts`。以注入时间、时区和现有 collection slot/CollectionRun/BatchRuntime seam 验证：列表校验/旧配置兼容；间隔派生计划和跨日校验；多 occurrence catch_up/skip、busy、跨日和重复触发；资格重算；原子保存、热更新与 BatchConfig 冻结；互斥与 shutdown。前端验证旧 payload 展示、策略条件切换、时间点增删/验证和完整保存。测试不等待真实时间、不运行真实 1688 采集。

完成后同步更新 `docs/architecture.md` 的调度原则。无需新增 QA 体系；如现有 QA 文档有专门的调度验收契约，则同步修订。
