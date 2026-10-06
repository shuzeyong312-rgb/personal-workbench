# Daily 自动采集策略 V1

状态：待实现；本轮只定义 Spec，不修改业务代码。

本 Spec 局部 supersede [`daily-collection.md`](daily-collection.md) 的自动采集规则：不再使用“启动约 30 秒后、每小时 direct 单商品 cycle”的实现和仅竞品范围。除本文明确变更外，既有 `Batch Runner`、`BatchRuntime`、`COLLECTION_LOCK`、headed Chrome/profile、串行访问、采集节奏与风控设置、全局 status polling、FastAPI lifespan 本地后台 task，以及单商品和添加商品的采集语义继续有效。

## Problem Statement

当前 daily scheduler 只有滚动 24 小时语义，并且自行逐条调用单商品采集。用户不能关闭自动采集、选择每日固定时间，或定义错过计划后的处理方式；自动采集也绕过了 Batch Runner 已有的节奏、主动休息、风控冷却、自动恢复和统一运行状态。

需要在本地单进程、无需新表或任务系统的前提下，将自动采集设置纳入既有“系统设置 → 竞品监控”，支持滚动 24 小时和每日固定时间两种可解释的策略，并让自动任务与手动 Batch 共享唯一 Runner。

## Solution

扩展既有 competitor-monitoring Settings API 和设置页面，保存完整的九项配置：既有五项 Batch 节奏/风控配置加四项自动采集配置。缺失的新 key 在读取时使用默认值，所以升级后保持现有滚动 24 小时自动采集行为。

scheduler 每次检查读取当前已保存的自动采集设置，判断是否应启动一次自动 Batch，计算所有符合条件的 active 商品 ID，然后仅尝试启动现有唯一 Batch Runner。它不再直接逐条采集，不新增第二 Runner、队列或持久化自动任务历史。自动 Batch 和手动 Batch 使用同一 Busy contract、同一冻结的 `BatchConfig`、同一 Runtime/status polling 和同一 stop/shutdown 行为。

## User Stories

1. 作为工作台用户，我希望能关闭每日自动采集，以便阻止未来自动任务而不打断已经开始的采集。
2. 作为工作台用户，我希望新安装或升级后默认继续滚动 24 小时自动采集，以便无需迁移或手工初始化。
3. 作为工作台用户，我希望在同一竞品监控设置区域选择滚动 24 小时或每日固定时间，以便按实际工作节奏监控商品。
4. 作为工作台用户，我希望为每日固定时间使用本机可读的 `HH:mm` 时间，以便每天在预期时间采集。
5. 作为工作台用户，我希望选择错过固定时间后补采或跳过，以便控制 Backend 晚启动后的行为。
6. 作为工作台用户，我希望固定时间当天只尝试每个商品一次，以免手动或自动采集后又重复外部访问。
7. 作为工作台用户，我希望计划时间之后手动单商品、添加商品首次采集或手动 Batch 已采过的商品自动被当天固定任务跳过，以便所有正式尝试都一致计入当天完成度。
8. 作为工作台用户，我希望失败尝试也计入滚动窗口和当天固定计划，以免失败时每次 scheduler check 反复重试。
9. 作为工作台用户，我希望 catch-up 在晚启动后只补尚未尝试的商品，以便不重复已完成或已失败的尝试。
10. 作为工作台用户，我希望 skip 在计划后新启动或才启用固定策略时当天不补采，以便明确地等到下一天。
11. 作为工作台用户，我希望当 Backend 已在计划前运行、到点时 Runner 忙，自动任务稍后仍会重试，以免瞬时冲突永久丢失当天任务。
12. 作为工作台用户，我希望自动采集与“立即采集”覆盖同一批 active self 和 competitor 商品，以便我方商品不会被悄然排除。
13. 作为工作台用户，我希望自动采集沿用商品间隔、主动休息、风控冷却和自动恢复设置，以便自动运行和手动 Batch 的访问节奏一致。
14. 作为工作台用户，我希望运行中的自动 Batch 不因修改自动设置或采集节奏设置而改变，以便当前任务可预测。
15. 作为工作台用户，我希望继续在现有采集任务状态中看到自动 Batch 的统一进度，以便不必学习第二套任务页面。
16. 作为系统维护者，我希望 scheduler 在 shutdown 时立即停止等待且不再启动 Batch，以便平稳退出本地 Backend。

## Implementation Decisions

### 1. 设置存储、默认值与 API

继续使用现有 `system_settings` 和 `GET` / `PUT /api/settings/competitor-monitoring`；不新增设置 API、数据库表或 migration。该 API 改为一次返回并保存既有五项 Batch 配置和以下四项自动采集配置的完整对象：

| API 字段 / `system_settings.key` | 默认值 | 有效值 |
| --- | --- | --- |
| `auto_collection_enabled` / `competitor_monitoring_auto_collection_enabled` | `true` | JSON boolean |
| `auto_collection_strategy` / `competitor_monitoring_auto_collection_strategy` | `rolling_24h` | `rolling_24h` 或 `fixed_daily` |
| `auto_collection_time` / `competitor_monitoring_auto_collection_time` | `09:30` | 严格 24 小时 `HH:mm` |
| `auto_collection_missed_policy` / `competitor_monitoring_auto_collection_missed_policy` | `catch_up` | `catch_up` 或 `skip` |

缺失、类型错误、格式错误或枚举外的历史值按字段 fallback 到默认值；读取不得写回默认值。既有五项的 strict validation、历史非法值 fallback、完整 body、未知字段拒绝、原子 PUT 和“不写回默认值”规则继续适用于扩展后的完整九项配置。PUT 必须在写入前验证所有九项，并在同一事务内提交；失败 rollback，不允许部分可见。关闭 `auto_collection_enabled` 只阻止未来自动 Batch reservation，不请求停止已启动的 Batch。

### 2. 两种 due 策略与本地时间

`rolling_24h` 保留现有语义：只评估 active 商品；不存在 `CollectionRun`，或最近一条 `CollectionRun.started_at` 距当前时刻至少 24 小时，商品才 due。成功和失败都计为最近一次尝试，不能因失败在每次 scheduler check 重试。

`fixed_daily` 使用运行 Backend 的电脑本地时区；V1 不新增时区设置。当天的本地计划时间点是 eligibility 边界。对每个 active 商品，只要存在 `CollectionRun.started_at >= 当天计划时间点`，无论由手动单商品、添加商品、手动 Batch 或自动 Batch 产生，且无论成功或失败，均视为当天已尝试，不能再次进入该日 fixed_daily 自动范围。计划时间之前的 Run 不算当天计划完成。实现以分钟级检查为目标，不要求秒级 Cron。

### 3. 错过计划、进程内 pending 与热更新

对 `fixed_daily`：

- `catch_up`：Backend 在当天计划后启动，或在计划后才切换/启用 fixed_daily 时，当天仍可启动自动 Batch；候选仅为计划时间后尚无 CollectionRun 的 active 商品。Backend 重启后根据 CollectionRun 继续补剩余商品，不重复已有尝试。
- `skip`：若当前 Backend 进程在当天计划后启动，或在计划后才切换/启用 fixed_daily，当天不补采，等待下一天。
- `skip` 的例外是本进程在计划时间之前已运行，并在本进程内跨过该时间：当天任务进入仅内存 `pending`。若 Runner 忙，后续 scheduler check 必须继续尝试；其他正式采集已生成 CollectionRun 的商品在每次重算候选时自然排除。

V1 不持久化 `skip` 的 pending。当天计划已到达后若 Backend 重启，新进程依上述 skip 规则重新判断，不承诺恢复上一进程未完成的 pending。

启用状态、策略、时间与错过策略不是 `BatchConfig`。scheduler 在每次未来任务判断时读取当前已保存值；修改设置影响后续判断，不取消或修改已经启动的 Batch。切换策略或启用状态后的“本次进程何时开始、是否已跨过今天计划时间”必须以当前进程的 lifecycle 和本次设置变更时刻确定，不能伪造重启前状态。

### 4. 统一 Batch Runner、范围与互斥

scheduler 只负责：确认自动采集启用、按当前策略判断 due、计算本次 due 商品 ID，并尝试通过现有 Batch 启动路径 reservation/start。它不得自行循环调用单商品采集。

自动范围与 Dashboard “立即采集”的 `all_active` 相同：全部 `is_active=true` 的 self 和 competitor 商品，按既有稳定顺序；inactive 商品不进入候选。启动自动 Batch 时冻结当前完整 BatchConfig，复用 headed Chrome/profile、串行访问、item interval、continuous collection count、resting、verification cooldown、auto resume、stop/shutdown、`BatchRuntime` 和 `COLLECTION_LOCK`。单商品手动采集和添加商品首次采集继续不使用 Batch 节奏。

全进程仍仅允许一个 Runner，不排队。自动任务 due 而手动 Batch、单商品或其他正式采集占用时不能并发启动：rolling_24h 在下一次 check 重新计算 due；fixed_daily 的本进程 pending 在下一次 check 重试。反向地，自动 Batch 运行时，手动 Batch 必须继续得到现有 `collection_in_progress` / busy contract。不得增加第二 Runner、任务队列或并发采集。

### 5. Scheduler lifecycle

保留 FastAPI lifespan 内的 asyncio 后台 task，不增加 scheduler 第三方依赖。替换“启动 30 秒 + 每小时 due-check”为能在固定计划时间后合理短时间内（分钟级）检查、同时支持设置热更新的简单本地循环；等待必须可被 shutdown 协作式唤醒，不能使用无法中断的长 sleep。shutdown 被请求后 scheduler 不得创建新的 Batch，并按既有 Runner shutdown 规则让已在运行的采集协作式结束。

### 6. Settings UI 与 Runtime/历史边界

现有“系统设置 → 竞品监控”保留 Batch 节奏与风控内容，并增加第三个轻量区域“自动采集”：每日自动采集开关、策略选择（每日固定时间 / 滚动 24 小时），fixed_daily 下的自动采集时间和错过计划选项（下次启动时补采 / 本次跳过）。rolling_24h 时隐藏 fixed-only 编辑 UI，但 Backend 保留已保存值，切回 fixed_daily 时恢复。区域显示“自动采集使用上方的采集节奏与风控设置。”

Settings UI 继续懒加载竞品监控配置、用一次完整 PUT 保存完整 contract，并与基础设置保持独立加载/错误状态；不新增自动采集独立页面。

自动采集继续复用 `BatchRuntime` 与全局 status polling。V1 不新增持久化 Batch 模型、`CollectionRun.source`、自动/手动历史区分、自动任务历史表或扩大的 Runtime contract；现有 Collection Tasks 若能自然显示统一 Batch 状态则直接复用。

## Testing Decisions

测试外部行为，优先复用既有 Settings API、`system_settings`、可注入 `now`/clock、session factory、`CollectionRun` fixture、`BatchRuntime`、Batch Runner fake collector、`COLLECTION_LOCK`、全局 Batch status polling 和现有 Settings Playwright API mock。禁止真实等待到某个时间，也不新增仅供测试的业务接口。

- Settings API 覆盖四项新值的默认值、完整 round-trip、严格类型/枚举/`HH:mm` 校验、历史非法值 fallback 且不写回、扩展九项完整 PUT 的原子性和失败 rollback。
- disabled 时不启动自动 Batch；验证关闭不停止已启动 Batch。
- rolling_24h 覆盖无历史、少于 24 小时、至少 24 小时和 failed Run。
- fixed_daily 覆盖计划前/后，以及 CollectionRun 在计划点前后对 eligibility 的区别；计划后由手动单商品、添加商品、手动 Batch、自动 Batch 或 failed Run 创建的 Run 都阻止当天重复自动采。
- catch_up 覆盖晚启动补采及部分商品已有当日 Run 时只补剩余；skip 覆盖计划后启动当天不补、计划前已运行跨过计划点后进入 pending，以及 pending 遇 Runner busy 后可重试。
- 覆盖 rolling 遇 busy 后后续重新判断；fixed pending 每次重算时排除其他正式采集已产生 Run 的商品。
- 覆盖 active self 与 competitor 都成为候选、inactive 不成为候选。
- 在 Batch 启动 seam 证明自动任务实际经过统一 Batch Runner 并冻结 BatchConfig；设置修改不改变已运行 Batch；自动 Batch 和手动 Batch 不并发。
- 覆盖 scheduler shutdown 唤醒等待、不再启动新 Batch，并保持既有协作式 Runner shutdown。
- Settings UI 覆盖自动采集条件显示、切换 rolling 后保留 fixed-only 值、完整九项保存 contract；至少扩展现有 Settings Playwright 路径，使用默认拒绝未声明 API 的 mock，不重复建设整套 E2E。

## Out of Scope

- 自定义 X 小时间隔、每周/工作日规则、Cron 表达式或多个每日时间；
- 云端调度、Backend 未运行时真正执行、系统休眠唤醒或时区设置；
- `CollectionRun.source`、自动采集历史表、持久化 Batch 或持久化 skip pending；
- 队列、Celery、Redis、第二 Runner 或并发采集；
- 单商品/添加商品采集节奏改造；
- 自动采集独立页面或按 manual/daily 区分现有历史/Runtime。

## Further Notes

本 Feature 的最小架构是“scheduler 编排、Batch Runner 执行”。固定时间的当天完成度仅由已存在的 `CollectionRun.started_at` 推断，而非新 source 或日任务记录；这刻意保留了 V1 的本地、单进程边界。实现前需以本 Spec 取代旧 daily scheduler 的 direct-cycle 规则，并在 ChatGPT Spec Review 后 Freeze；本 Spec 不授权实现业务代码。
