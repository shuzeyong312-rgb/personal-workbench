# 竞品监控设置与采集节奏 V1

状态：待实现；本轮只定义 Spec，不修改业务代码。

本 Spec 局部 supersede [`batch-collection-auto-resume-v1.md`](batch-collection-auto-resume-v1.md) 中“默认冷却 10 分钟、自动恢复上限 2”以及对应 Runtime 固定常量的规则；两个值改为每个 Batch 启动时冻结的竞品监控设置。除本文明确变更外，既有单 Runner、HTTP polling、headed Chrome、`.browser-profile`、串行采集、`COLLECTION_LOCK`、verification detector、人工 `verification_required` 兜底、内存 Runtime 和 Backend 重启不恢复的规则继续有效。

## Problem Statement

当前“系统设置”只有我方店铺名称；Batch Collection 的商品间隔、连续访问后的主动休息、风控冷却和自动恢复次数散落为固定行为或固定常量。用户无法按自己的运行环境调整批次节奏，也无法从采集任务区分计划内降频和已经触发 1688 verification 的风控冷却。

需要在不引入通用配置平台、数据库表或任务持久化的前提下，使竞品监控设置可验证、可原子保存，并保证运行中的 Batch 不会被后续设置改动改变节奏。

## Solution

系统设置页按业务模块展示两个独立区域：保留“基础设置”中的我方店铺名称；新增“竞品监控”，一次完整保存五项采集节奏与风控设置。设置仍存于现有 `system_settings` key/value；缺失 key 在读取时使用 V1 默认值。

每次 Batch 在启动时读取一次完整竞品监控设置，生成只属于该 Batch 的不可变配置快照。Runner 只使用该快照：商品之间按间隔等待；当主动批次休息已启用时，每达到连续真实外部访问上限后在仍有待处理商品时进入新的 `resting`；触发 verification 时沿用既有自动恢复流程，但使用该快照中的冷却和恢复上限。单商品采集和 daily scheduler 完全不读取这些设置。

## User Stories

1. 作为工作台用户，我希望在系统设置中分别看到基础设置和竞品监控设置，以便按业务目的配置系统。
2. 作为工作台用户，我希望保留已有我方店铺名称配置方式，以便不改变身份识别流程。
3. 作为工作台用户，我希望一次保存完整的五项竞品监控设置，以免出现半新半旧的运行参数。
4. 作为工作台用户，我希望未配置过竞品监控设置时仍取得明确默认值，以便升级后无需迁移或手工初始化。
5. 作为工作台用户，我希望运行中的 Batch 固定使用启动时的参数，以便设置修改不会让已开始的等待或恢复行为不可预测。
6. 作为工作台用户，我希望商品之间有可配置的节奏，但最后一个商品后不产生无意义等待。
7. 作为工作台用户，我希望连续真实访问达到上限后看到计划内主动休息，以便降低访问频率而不误解为风控。
8. 作为工作台用户，我希望 verification 后的冷却和自动恢复使用本批次固定的风控参数，以便恢复行为可解释。
9. 作为工作台用户，我希望在“采集任务”看到主动休息的剩余时间，并能与风控冷却明确区分。
10. 作为系统维护者，我希望三类等待均能被 stop/shutdown 立即中断，以便不遗留 Runner、Browser 或采集锁。

## Implementation Decisions

### 1. 设置存储、默认值与 API

不新增表、migration、通用设置注册表或配置服务。继续使用 `system_settings(key, value)`，以下 key 的 value 均保存为十进制整数字符串：

| API 字段 / `system_settings.key` | 默认值 | 有效范围 |
| --- | ---: | ---: |
| `item_interval_seconds` / `competitor_monitoring_item_interval_seconds` | 5 | 1–60 秒 |
| `continuous_collection_count` / `competitor_monitoring_continuous_collection_count` | 10 | 1–50 次 |
| `batch_rest_seconds` / `competitor_monitoring_batch_rest_seconds` | 120 | 0–1800 秒 |
| `verification_cooldown_seconds` / `competitor_monitoring_verification_cooldown_seconds` | 600 | 60–3600 秒 |
| `auto_resume_max` / `competitor_monitoring_auto_resume_max` | 2 | 0–5 次 |

新增业务级接口：

```http
GET /api/settings/competitor-monitoring
PUT /api/settings/competitor-monitoring
Content-Type: application/json
```

GET 始终返回完整五项数值。某个 key 缺失、值不是严格十进制整数或值超出该字段范围时，返回该字段默认值；读取不得写回默认值，也不得因旧数据使设置页不可用。

PUT body 必须完整且只包含五个 API 字段，例如：

```json
{
  "item_interval_seconds": 5,
  "continuous_collection_count": 10,
  "batch_rest_seconds": 120,
  "verification_cooldown_seconds": 600,
  "auto_resume_max": 2
}
```

- 每项必须为 JSON integer，布尔值、浮点数、字符串、缺项、未知字段和越界值均为非法；返回 HTTP 422。
- Backend 必须在修改任何 `SystemSetting` 前完成完整 body 校验；五个值在同一个数据库事务中 insert/update 并 commit。验证失败或保存异常时 rollback，不允许部分成功或部分可见。
- 成功响应返回保存后的完整五项数值；失败响应使用安全、字段可定位的稳定错误信息，不回显数据库异常。
- `GET` / `PUT /api/settings/own-shop-name`、我方店铺重识别和其既有事务语义不变。

### 2. 设置页面

系统设置内部使用左侧模块导航和右侧当前模块内容，不将两类设置拼成一个通用设置表。V1 导航仅有以下两个模块：

1. **基础设置**：保留现有“我方店铺”卡片、说明、确认提示、独立 GET/PUT 和保存语义。
2. **竞品监控**：右侧显示“采集节奏与风控”卡片，含五个带单位和范围提示的数字输入；使用独立 GET/PUT 与保存按钮。该按钮一次提交完整五项，保存中禁止重复提交。

竞品监控区域的加载、保存错误和成功反馈独立于基础设置。加载或保存竞品监控失败不得覆盖已成功加载的我方店铺区域，反之亦然。前端可以在输入层做范围提示和提交禁用，但 Backend 422 是权威校验；不得把运行中 Batch 配置写回或显示成“当前设置”。

`batch_rest_seconds` 与 `verification_cooldown_seconds` 在前端以业务友好的“分钟”展示和编辑；提交时转换为 API 所需的整数秒。分钟输入必须能精确表达 API 已保存的秒值，不得静默截断或四舍五入；保存前转换结果仍须落在各自秒级范围。界面明确提示：**“设置仅影响下一次新启动的批量采集，当前运行任务不变。”**

### 3. Batch 配置快照与状态

Batch POST 在冻结目标 competitor IDs、确认没有既有采集占用并成功取得本次 Runner reservation 时，用同一个启动请求的数据库读取取得五项完整有效设置，构造 `BatchConfig` 值对象/等价不可变快照，再启动 worker。该快照仅存于现有内存 BatchRuntime/Runner 生命周期内，不写入新表，也不要求跨 Backend 重启恢复。

- 每个成功启动的 Batch 只读取一次竞品监控设置；Runner、自动恢复和所有等待只读取该快照，不在循环、轮询或重试时重新读设置。
- PUT 与启动并发时，启动 Batch 只能看到 PUT 事务提交前的完整旧配置，或提交后的完整新配置，不能看到五项混合值；之后的 PUT 不影响已启动 Batch。
- 仍保留一个进程内 Runner 和既有 `COLLECTION_LOCK`。`resting`、`cooling_down`、人工 verification 窗口和 running 期间均保持现有互斥语义；不得重构、提前释放或用另一把锁替代 `COLLECTION_LOCK`。
- `GET /api/competitors/collect-batch/status` 在既有字段基础上新增 `resting_remaining_seconds`。其状态枚举扩展为 `idle | running | resting | cooling_down | verification_required | completed`。
- `resting_remaining_seconds` 只在 `resting` 返回非负整数倒计时，其他状态为 0；既有 `cooldown_remaining_seconds` 只在 `cooling_down` 返回非负整数，其他状态为 0。两个剩余时间不得同时为正，均以 Backend Runtime 为准，Frontend 不自行倒推。
- `resting` 接入现有唯一的全局 Batch status polling：不新增页面级或第二个 polling loop。全局 polling 将 `resting` 视为 active batch，与 `running`、`cooling_down` 一样持续刷新；状态从 `resting` 转为 `running` 或 `completed` 后，必须自动继续取得并渲染后续状态，不能因本地终止条件停留在旧状态。

### 4. 真实外部访问计数与三类等待

“真实外部访问”是 Runner 对一个 competitor 发起一次既有 1688 collector 调用的时点；不以采集成功、`CollectionRun` 最终状态或 UI 进度计数。启动前 ID 校验、is_active 预检查、被锁拒绝、stop 已请求而未发起 collector 的路径均不计数；已经发起 collector 后即使后续解析、保存或 verification 失败，仍计数一次。

Runner 维护只属于本次 Batch 的连续真实访问计数，初始为 0。一次外部访问返回后，按下列互斥顺序决定后续动作：

1. 若该访问触发 `1688_verification_required`，立即停止下一次外部访问，进入既有 verification 路径；不得先加 item interval 或主动休息。`cooling_down` 完成后将连续访问计数归零，重试当前 competitor 前不额外等待。
2. 若当前 competitor 已得到正常最终结果（成功或普通失败）且没有待处理 competitor，不等待 item interval 或主动休息，直接完成 Batch。
3. 若仍有待处理 competitor、`batch_rest_seconds > 0`，且连续真实访问计数已达到 `continuous_collection_count`，进入 `resting`，不叠加 item interval；主动休息结束后将连续访问计数归零，再处理下一项。
4. 否则进入可中断的 item interval，等待 `item_interval_seconds` 后处理下一项。

因此 `continuous_collection_count=1` 表示每一次正常完成的真实外部访问后、仅在还有下一项且主动批次休息已启用时进入主动休息。`batch_rest_seconds=0` 表示关闭主动批次休息：Runner 不进入 `resting`、不产生 0 秒 `resting` 状态，即使已达到连续数量也按正常 item interval 继续；在该模式下连续访问计数无需因主动休息归零。一次 Batch 最后的真实访问后不发生任何等待。

`resting` 是计划内降频，满足：`runner_active=true`、`browser_open=true`（既有 batch Context 仍可复用）、保持 `COLLECTION_LOCK`，且 `outcome_code` 仍为 `null`。它不是 verification，不关闭 Browser/Context、不增加 `auto_resume_attempt`，也不改变 `completed`、`remaining` 或最终 items。

`cooling_down` 仅表示既有 detector 已触发 verification：关闭 Browser/Context、`browser_open=false`、`runner_active=true`、保持锁，并按 Batch 快照的 `verification_cooldown_seconds` 等待。自动恢复上限使用快照的 `auto_resume_max`：值为 0 时首次 verification 直接进入既有人工 `verification_required`，不进入 `cooling_down`；其他计数、当前项重试和人工兜底语义继续遵循 auto-resume V1。

任何 item interval、`resting` 或 `cooling_down` 等待都必须复用/扩展现有基于 `stop_event` 的短间隔可中断等待，不能使用不可中断的长 `sleep`。stop/shutdown 时不得发起下一次外部访问；随后按现有 finally/lifespan 清理 Browser/Context、Runtime 和锁。主动休息或风控冷却结束后都将连续访问计数归零。

### 5. Collection Tasks 与其他采集路径

Collection Tasks 继续只消费现有 Batch status polling，不新增任务 API、第二个 polling loop 或持久化 Batch 模型。

- `running` 显示现有采集进度。
- `resting` 显示“计划内主动休息”，显示 `resting_remaining_seconds`、完成数和剩余数；文案不得提及 verification、风控或自动恢复。
- `cooling_down` 显示“1688 风控冷却/等待自动恢复”，显示 `cooldown_remaining_seconds` 和 `auto_resume_attempt / auto_resume_max`；文案必须与主动休息不同。
- `verification_required` 继续显示既有人工验证提示。状态标识、颜色/辅助文本应使 `resting` 与 `cooling_down` 可辨识，而不是复用同一个“冷却中”标签。

本 V1 只改变 Batch Collection。单商品采集、添加商品时的采集、daily scheduler 的到期判断、顺序、等待和锁获取规则均不读取这些参数，行为保持不变。

## Testing Decisions

测试外部行为和 API/UI contract，优先复用已有 Settings API、BatchRuntime/Runner fake collector、`COLLECTION_LOCK`、全局 status polling、Collection Tasks 组件和 Playwright API mock seam；不为测试增加业务接口、任务框架或持久化 fixture。

### Settings API 与页面

- GET 在五个 key 都缺失、部分缺失、旧值非法时返回各自默认值，且不写数据库；有效保存后完整 round-trip。
- PUT 覆盖五项的边界值；缺项、未知字段、bool、浮点、字符串和每项越界均为 422，并证明原五项数据库值完全未变。
- 模拟提交期间的保存异常，证明事务 rollback 后不存在部分更新。
- Settings 页使用左侧“基础设置”“竞品监控”模块导航和右侧当前模块内容；竞品监控加载/保存成功与失败状态独立；一次保存发出完整五项 body，范围与单位可见。两个长时长字段以分钟编辑、精确转换为秒，并显示“仅影响下一次新启动的批量采集，当前运行任务不变”。
- 保留我方店铺 GET/PUT、重识别确认和既有页面行为回归测试。

### Batch service/runtime

- Batch 启动读取一次设置快照；启动后 PUT 新值，当前 Batch 的 item interval、主动休息、cooldown 和 auto-resume 上限仍使用旧快照；下一 Batch 使用新值。
- 验证真实外部访问而非成功数：预检查拒绝不计数；collector 已被调用但随后普通失败或 verification 仍计数。
- 覆盖 item interval：仅在正常已完成项之间等待，最后一项后不等待。
- 覆盖主动休息：`batch_rest_seconds > 0` 时，第 `continuous_collection_count` 次真实访问后、仅在有后续项时进入 `resting`；`resting` 不额外叠加 item interval，结束后计数归零且复用 Context/锁。`batch_rest_seconds=0` 时不进入 `resting`、不产生 0 秒状态，并在达到连续数量后仍按 item interval 继续。
- 覆盖 verification 优先级：verification 不先进入 resting/item interval；cooldown 结束归零，重试当前项前不叠加等待；`auto_resume_max=0` 直接走人工兜底。
- 覆盖 `resting` 和 `cooling_down` 的 status、剩余秒字段互斥、计数不变量（包括 `completed + remaining = total`）及 `COLLECTION_LOCK` 持有。
- 对三类等待分别触发 stop/shutdown，证明不会启动下一次 collector、资源清理和锁释放仍符合现有 shutdown contract。
- 回归单商品、添加商品与 daily scheduler：它们不读取竞品监控设置，也不新增节奏等待。

### Collection Tasks 与浏览器路径

- Collection Tasks 以同一 status seam 渲染 `resting` 的主动休息、剩余时间、完成数和剩余数；`cooling_down` 显示不同的风控冷却/自动恢复信息；现有 running、completed、人工 verification 显示不回归。现有唯一全局 polling 将 `resting` 视为 active，验证 `resting → running` 和 `resting → completed` 都自动刷新；不新增第二个 polling loop。
- 至少一条关键 Playwright 路径：进入系统设置，修改五项竞品监控设置并保存，验证完整 PUT body 与成功反馈；API mock 默认拒绝未声明请求。

## Out of Scope

- daily 自动采集设置或它的运行节奏；
- 单商品采集、添加商品采集的间隔/风控设置；
- 全网比价、自动询价、自动上架设置；
- `COLLECTION_LOCK` 重构、并发采集、第二 Runner、队列、WebSocket/SSE；
- BatchRuntime 持久化、Backend 重启恢复、批次历史表；
- verification detector 修改、CAPTCHA/风控绕过、stealth、proxy 或动态热更新运行中 Batch；
- 新数据库表、migration、通用设置平台或新增依赖。

## Further Notes

实现时应将五项设置的 key、默认值、范围和严格解析集中在 settings 业务边界，避免 Router、Runner 与 Frontend 各自散落不同默认值。Batch 快照是运行事实，不是新的持久化配置历史；设置页面始终展示当前已保存的系统设置，不承诺展示任一正在运行 Batch 的冻结值。

本 Spec 不授权实现业务代码。本轮交付仅为仓库内 Spec，经 review 冻结后再进入实现。
