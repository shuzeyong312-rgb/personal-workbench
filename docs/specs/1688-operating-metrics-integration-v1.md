# 1688 经营指标正式集成 V1 Spec

状态：待 ChatGPT 独立 Final Spec Review；未 Freeze，禁止进入 Implement。<br>
范围：只把已准入的 1688 Offer 经营指标原值接入现有采集、存储和详情展示。<br>
证据基线：本地 Gate 1 五链接报告 `experiments/1688-gate1-visible-poc/five-extension-enabled-20261010-135701.jsonl`；正式批次 `formal-batch-10-20261010-103506.jsonl`；Research §11–12。所有样本均为 2026-10-10 本地观察，不表示持续覆盖率或平台许可。

## Problem Statement

手动「立即采集」和系统定时批量采集目前共用 Playwright 与唯一 Batch Runner，只保存基础商品、价格和 SKU 快照。`ProductData`、`ProductSnapshot`、单商品详情和 Group Detail 尚无经营指标原值合同。用户需要通过现有入口同时采集基础数据及可读取的经营指标，不逐个打开自制扩展，也不让经营字段暂缺破坏可信的基础结果或历史值。

## 已证实事实与待解决门槛

### 已证实事实

- 当前商品级事实由 `ProductData → ProductSnapshot / SkuSnapshot` 保存；`CollectionRun.status` 只有 `running / success / failed`。`ProductData` 不含经营字段。Group Detail 已批量载入组成员、最新 Snapshot 和变化，并提供「竞争总览 / 经营表现 / 口碑履约」三视图；经营字段当前未接入。
- 正式手动、批量和定时入口已共用采集服务、项目 `.browser-profile`、Playwright 与 Batch Runner。批次已有单条间隔、休息、验证冷却/有限自动恢复、暂停/继续和结束语义。不得添加第二个 Runner、调度器或逐商品扩展点击流程。
- Gate 1 五链接报告记录 5 个页面的 Offer ID 与目标 Offer 一致，顶部助手区可见，区域为 `goods-operation-panel-media` 且明确不含分销代发。3 个 Offer 八字段均为非占位原值；另 2 个 Offer 各有「评论数」和「好评率」显示 `-`，其余六项有原值。五条记录的 `data_load_state` 均为 `unknown`、等待时间为 0 秒、截图路径为空；这是观察报告，不是完整的正式 Collector 可靠性验收。
- 同日正式批次日志把 10 个基础商品采集都记为成功，但现有验证检测曾漏检覆盖商品内容的验证弹窗风险。不得把此批次记载解释为已证明没有验证，也不得与五链接指标结果合并成“全部成功”。
- Research 记录：收藏数仅有单一 A19 商品原值候选；八种平台标签没有带标签正样本。现有验证检测无法证明所有页面内嵌验证均被发现，这是独立已知问题，不作为本 Spec Freeze 或 Implement 前置门槛。

### 实现前硬门槛

1. 八项采购助手指标以本 Spec 的来源和原值合同为准；字段可独立采集，某字段或某商品失败不阻塞其他字段。收藏数和八种平台标签维持 Hold，直到现有 Playwright 路线取得字段级来源、归属、原值/缺失和失败隔离验收；不得依赖自制 Chrome 扩展来解除 Hold。
2. Offer ID、页面来源和数据库事务仍须通过现有校验与回滚合同；局部解析失败必须隔离，失败不能清除历史有效值。沿用现有验证检测与处理，不扩大检测范围、不开发绕过措施；已知漏检单独跟踪，不构成本轮门槛。
3. 本轮不开展数据使用许可专项研究，不要求许可核验报告作为 Spec 或开发前置条件，也不将其加入本轮验收。不得绕过登录/验证/风控，不读取 Cookie/账号存储，不使用未经授权私有接口或重放请求。

## Solution

在现有 Collector 单次商品访问中，于可信 Offer 页面读取可见的官方采购助手顶部区域，并将逐字段观察作为同一 `CollectionRun` 的独立结果持久化。基础商品采集和经营指标采集分别有状态；只有页面身份及可信性验证通过，才保存基础 Snapshot 或经营观察。对准入字段保存页面原始字符串及来源、Offer、状态、原因和观察时间；占位或失败只增加本次观察，不覆盖之前有效值。

扩展现有单商品详情与 Group Detail 三视图读取合同；列表/组查询按一条批量查询拿到所有成员的最新观察，不按商品逐个查询。只显示原值、来源、观察时间、状态/缺失原因和真实覆盖情况，不排序、不计算趋势或销量增长、不评分。

## User Stories

1. 作为运营者，我希望手动立即采集时同时尝试基础商品事实及已准入经营字段，以便不逐个操作扩展。
2. 作为运营者，我希望定时批次复用相同采集路径和节奏，以便自动任务的结果与手动采集一致。
3. 作为运营者，我希望看到每字段的原始值、来源和采集时间，以便判断其事实边界。
4. 作为运营者，我希望明确区分页面显示 `-`、字段未加载和本次采集失败，以免把缺失当作 0 或无标签。
5. 作为运营者，我希望经营采集失败时仍保留可信的基础价格、SKU 和库存快照。
6. 作为运营者，我希望验证弹窗、商品身份不符和页面可信性失败时，整次商品采集被阻止并保留历史，以免写入错误商品数据。
7. 作为运营者，我希望后续失败时仍可查看上一次有效经营原值及其原时间，同时看到最近一次尝试的失败原因。
8. 作为运营者，我希望在单商品详情和 Group Detail 既有三视图查看结果，不增加另一套经营指标页面。
9. 作为运营者，我希望我方商品与直接竞品遵循同一 Offer 来源、采集和可见性合同。

## Implementation Decisions

### 1. 字段目录与来源合同

| key | 展示名 | 唯一允许来源 | 原值规则 | 当前准入 |
| --- | --- | --- | --- | --- |
| `listing_time` | 上架时间 | 当前 Offer 的「1688官方采购助手」顶部区域 | 原样字符串；不替换为商品发布时间，不推断首次上架/重上架语义 | Gate 1 样本已观察；按本合同准入原值采集 |
| `monthly_deal` | 月成交 | 同上 | 保留 `100+`、`<10` 等档位文本 | Gate 1 样本已观察；原值准入 |
| `monthly_dropship` | 月代销 | 同上 | 保留原文；不得映射成「近 30 天代发数量」或分销代发区域值 | Gate 1 样本已观察；原值准入 |
| `annual_units` | 年成交件数 | 同上 | 保留原文；不等同年成交笔数 | Gate 1 样本已观察；原值准入 |
| `annual_orders` | 年成交笔数 | 同上 | 保留原文；不等同年成交件数 | Gate 1 样本已观察；原值准入 |
| `review_count` | 评论数 | 同上 | 保留原文；显示 `-` 是占位，不是 0 | Gate 1 样本已观察；原值准入 |
| `positive_rate` | 好评率 | 同上 | 保留 `96%` 等原文；不替换为代发品质达标率 | Gate 1 样本已观察；原值准入 |
| `pickup_rate` | 揽收率 | 同上 | 保留 `96%` 等原文；不读取分销代发区域的 24h/48h 揽收率 | Gate 1 样本已观察；原值准入 |
| `favorite_count` | 收藏数 | Offer 商品收藏控件的可见原值 | 原样保留；不可只凭计数器或店铺统计推断 | **Hold**：需 Playwright 字段级验收 |
| `platform_tag_new`、`platform_tag_popular_new`、`platform_tag_first_release`、`platform_tag_super_new`、`platform_tag_select`、`platform_tag_cross_border`、`platform_tag_store_treasure`、`platform_tag_wow_custom` | 新品、人气新品、首发新品、超级新品、严选、跨境、镇店之宝、哇偶定制 | Offer 页面可见标签的完整精确匹配 | 标签名完整匹配才算显示；未采集与未出现分开 | **Hold**：需带标签 Playwright 正样本及缺失/失败验收 |

字段目录可以列出 Hold 字段，但 Hold 期间不得由正式 Collector 写入它们的值或“未显示”观察。解除 Hold 按字段独立决定，不能要求全部目录字段一并通过。任何来源歧义、顶部区域不存在、多个候选区域无法唯一判定、区域含分销代发内容或标签和值不能绑定时，本字段读取失败，不选一个候选值凑结果。

Gate 1 五链接原值（所有值均为页面原文；两处 `-` 是官方助手区占位）：

| Offer ID | 上架时间 | 月成交 | 月代销 | 年成交件数 | 年成交笔数 | 评论数 | 好评率 | 揽收率 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `1079906223307` | `2026-09-07` | `100+` | `<10` | `100+` | `60+` | `2` | `100%` | `96%` |
| `1080864798243` | `2026-09-07` | `<10` | `<10` | `<10` | `<10` | `4` | `100%` | `75%` |
| `1083985416394` | `2026-09-11` | `10+` | `<10` | `10+` | `<10` | `-` | `-` | `75%` |
| `1082904060172` | `2026-09-07` | `20+` | `<10` | `20+` | `10+` | `-` | `-` | `100%` |
| `1081895898799` | `2026-09-11` | `20+` | `<10` | `20+` | `10+` | `1` | `100%` | `100%` |

### 2. 数据模型与迁移

新增 `operating_metric_observations`（表名可按仓库命名规范调整，但合同不变），每行代表一个商品、一次 `CollectionRun`、一个字段的一次真实读取尝试：

| 字段 | 语义与约束 |
| --- | --- |
| `id` | 主键 |
| `competitor_id` | FK 到当前监控商品；包含 ownership=self 与 competitor |
| `collection_run_id` | FK 到本次 CollectionRun；唯一键 `(collection_run_id, metric_key)`，避免同次重复字段 |
| `platform`、`offer_id` | 观察时的来源平台及页面 Offer ID；必须等于当前商品的 `platform + offer_id` 才能写有效观察 |
| `metric_key` | 本 Spec 的固定字段目录键；保持字符串，不创建每字段列 |
| `status` | 仅字段级 `observed`、`placeholder`、`loading`、`source_unavailable`、`read_failed`；全局失败不创建字段 Observation |
| `raw_value` | 原始字符串；`observed` 必须非空，`placeholder` 存页面实际占位符（如 `-`），技术缺失状态为 NULL；不保存派生数值 |
| `source` | 精确来源标识；八项为官方助手顶部区域，后续解除 Hold 的字段采用对应可见区域标识 |
| `observed_at` | 页面字段读取时的带时区时间；同次采集的字段可共享一次 DOM 读取时刻 |
| `reason` | 可读的缺失/读取失败原因；成功及占位可为空 |

新建 Alembic revision：建表、FK/check/唯一约束及 `(competitor_id, metric_key, observed_at, id)` 查询索引，并为 `CollectionRun` 增加非空 `operating_metrics_status` 列及对应 check constraint。Run 级状态只允许 `not_attempted / success / partial / no_values / failed / blocked`；迁移旧 Run 时统一默认 `not_attempted`，不回填推测状态。Observation 的 `competitor_id`、`collection_run_id` 使用默认 NO ACTION 外键，不依赖数据库级联；永久删除沿用 `_delete_competitor_history` 的单事务显式删除顺序：ChangeEvent → OperatingMetricObservation → CollectionRun → SkuSnapshot → ProductSnapshot → Competitor。单条和批量删除共用此 helper，任一步失败必须 rollback 整个事务。不得修改或回填既有 ProductSnapshot，不给旧商品造全 NULL 经营快照，不做猜测性迁移。历史从首次真实 Observation 起算；不承诺存在更早记录。成功 Observation 与失败状态历史都保留，不设自动过期或按天覆盖；失败、下架和后续缺值不得清除已有有效值。

`ProductSnapshot` 继续只存基础商品级事实；`SkuSnapshot` 继续只存 SKU 事实。经营 Observation 与同次 Run 关联，但不嵌入 Snapshot，也不复制标题、价格、库存、SKU。

### 3. 有效值和状态判定

- **最新全局采集 Run**：对商品按 `started_at DESC, id DESC` 取最近 CollectionRun，返回 Run 基础状态、经营状态、开始/结束时间及错误。失败 Run 即使没有 Observation 也必须被 API/UI 显示。
- **字段最近一次尝试**：只从真实 Observation 按 `observed_at DESC, id DESC` 取最新记录，返回其 `collection_run_id`。失败 Run 没有 Observation 时，不能伪造本次字段尝试；旧字段尝试仍显示自己的原时间和 Run ID。
- **字段最新有效值**：独立地在同一商品、同字段范围内，过滤 `status='observed' AND raw_value IS NOT NULL AND raw_value<>''` 后按同一顺序取最新值。占位、加载、缺来源、读取失败不得覆盖它。最新 Run 失败且无新 Observation 时，UI 同时展示 Run 失败时间及旧值的原观察时间，不将旧值标为本次结果。
- `placeholder` 是成功识别来源和字段后的页面观察，不是有效经营值。显示「页面显示 `-`」和占位观察时间；有效值若存在仍展示其原值及原时间。
- `loading`、`source_unavailable`、`read_failed` 描述本次不可读，不等同无数据、0、标签未出现或下架。 Hold 字段及从未采集字段没有 Observation 行，API/UI 显示待接入/未采集。
- Run 级经营状态只按本次已准入字段集合判定（V1 为八项）。每次可信页面读取都须为八个准入字段各生成且最多保存一个真实字段结果；不得因字段未读到而省略状态或补造值。按下表从上到下优先判定：

| 条件（优先级从高到低） | `operating_metrics_status` | Observation 合同 |
| --- | --- | --- |
| Offer ID、页面身份或页面来源的全局可信性校验失败 | `blocked` | 不产生任何字段 Observation |
| 本次未尝试、没有已准入字段、Hold 字段、迁移前旧 Run，或正常确认下架 | `not_attempted` | 不产生字段 Observation |
| 数据库业务事务失败并回滚 | `failed` | 不产生字段 Observation；不得把保存错误伪装成字段读取结果 |
| 八项均为 `observed` | `success` | 八项真实 Observation |
| 1–7 项为 `observed`，其余是 `placeholder / loading / source_unavailable / read_failed` 的任意组合 | `partial` | 八项真实 Observation；缺失字段按实际字段状态记录 |
| 0 项为 `observed` 且八项均为 `placeholder` | `no_values` | 八项 `placeholder` Observation |
| 0 项为 `observed`，且不是八项全 `placeholder`（含全技术失败，或占位与任一技术失败混合） | `failed` | 八项按实际结果记录 `placeholder / loading / source_unavailable / read_failed` |

字段解析仍处于 `loading` 且页面读取窗口结束时，该字段记 `loading`；有原始占位符才记 `placeholder`；无可用正确来源记 `source_unavailable`；其余解析异常记 `read_failed`。混合占位/失败且零个 `observed` 固定为 `failed`；只要至少一项 `observed` 且少于八项，就固定为 `partial`。数据库枚举约束、CollectionRun、Batch item 及六值经营状态计数、API、UI 与自动化测试均使用 `not_attempted / success / partial / no_values / failed / blocked`，不得另造同义状态。字段级状态枚举固定为 `observed / placeholder / loading / source_unavailable / read_failed`；全局失败和未尝试不创建虚假字段级 Observation。
- `placeholder` 只用于来源与字段已确认且原文属于 POC 明确识别的占位符集合（如 `-`）；保存实际原文。`observed` 保留 `0`、`100+`、`<10`、百分比等非空原文，不转数值。
- 全局 Offer 身份/页面来源失败只写 CollectionRun 的 `failed` 与经营状态 `blocked`，不得创建字段 Observation。可信页面内的字段级读取异常须为每个已准入字段保存真实状态行；不得把数据库提交失败伪造成字段级读取结果。

### 4. 页面读取、服务返回与事务边界

现有 Collector 在一个 Playwright page 上导航、校验和读取 HTML，随后可能关闭 page 并只返回 `ProductData`。新合同要求在**同一次导航、同一页面仍可用时**完成基础解析与助手顶部八字段解析；不得先关闭页面后另开页面补读指标，也不得因某字段缺失重载/重试商品页。

Collector 向现有 Service 返回一个同次页面结果，包含独立的基础解析结果（`ProductData` 或基础解析错误）和八项字段 Observation 候选（每项为字段状态/原值/来源/Offer/观察时间/原因）。候选只在页面全局 Offer ID 与来源通过校验后生成。解析应隔离：基础解析失败不抹掉同页已可信的经营 Observation；经营字段解析失败不抛出基础采集失败。全局身份/来源校验失败时两类都不可写。`collect_competitor` 仍是唯一持久化入口，单条、Batch 与定时调用不分叉。

事务合同：

1. Service 先用短事务创建并提交 `CollectionRun(status='running', operating_metrics_status='not_attempted')`；Playwright 期间不持有数据库事务。
2. 商品页返回后，若全局 Offer ID 与数据库 `platform + offer_id` 不匹配，或全局商品页面身份无法校验，丢弃两类解析结果；新事务只把 Run 记 `failed / blocked` 和安全错误摘要，不写 Snapshot、SKU、ChangeEvent 或 Observation。既有历史不变。
3. 页面可信且基础解析成功时，经营失败/部分/占位不影响基础 Snapshot、SKU、商品当前事实或 ChangeEvent；在一个事务中原子保存基础事实、字段 Observation、商品更新及 Run 终态。
4. 页面可信但基础解析失败时，不写基础 Snapshot/SKU/基础变化；若同页经营解析有真实字段结果，则保存这些 Observation，Run 基础状态 `failed`，经营状态依真值表保存。UI/API 必须同时显示基础 Run 失败和该字段观察，不将二者折叠成全成功。若字段解析也失败，保存真实字段错误状态，不能伪造有效值。
5. 正常确认下架沿用现有 `offline` 结果：Run 基础状态 success、无空 Snapshot/SKU/经营 Observation，经营状态 `not_attempted`，保留历史有效值。
6. 任一数据库保存/flush/commit 失败：回滚该次业务事务，确保 Snapshot/SKU/ChangeEvent/Observation/Competitor 更新全部为零提交；用新事务按现有 `_mark_failed` seam 将已提交的 Run 标为 `failed`，经营状态记 `failed`（若本次未准入/未尝试字段则仍 `not_attempted`），记录稳定保存错误。不得留下部分业务事实，也不把 DB 错误写成字段级解析失败 Observation。

验证弹窗漏检保留为**独立已知问题**：沿用 Collector 当前检测及 Batch 现有 `verification_required`、cooldown、有限恢复和人工处理机制。不增加验证检测器、检测覆盖要求、回归范围或绕过措施；本 Spec 不以修复该问题为 Freeze/Implement 前置条件。Offer ID 核验、正确助手顶部来源校验、失败隔离、事务回滚和历史保护仍为本 Feature 的必须条件。

### 5. CollectionRun、Batch 状态与 outcome_code

`CollectionRun.status` 保持现有 `running / success / failed`，表示基础商品/全局身份结果；新增受约束列 `operating_metrics_status`，使用上一节的六值真值表。每条 Run 都同时有两个独立状态；Detail API 展示最新 Run 的两者，不把基础 `success` 简写成两路全部成功。

Batch 每个终态 item 保留现有 `status=success / failed / verification_required` 与 `completed / succeeded / failed / verification_required / remaining` 计数，再附 `operating_metrics_status`。各计数仍只按基础 item 终态累计，指标状态不得改变 `completed + remaining = total`；cooldown 自动恢复的中间 attempt 不新增终态 item 或计数。另增六值经营状态计数，方便看到经营成功/部分/无值/失败/阻塞/未尝试分别涉及多少 item。

终态 `outcome_code` 按以下顺序取首个匹配项，暂停、继续、冷却、休息期间仍为 null/原运行态，不抢先定终态：

1. 显式用户结束 → `user_ended`（用户结束优先；既有 item 与剩余数保持原规则）。
2. Runner 停在未解决的现有人工验证状态 → `verification_required`。
3. 未捕获的 Batch/Runner 基础设施错误 → 现有 `collect_failed`；Runner 在最终获取采集锁时遇到竞态 → 保留现有 `collection_in_progress`。
4. 任一已终结基础 item 为 failed（含普通商品采集失败）→ `partial_failure`。
5. 基础 items 全成功，但任一经营状态非 `success`（包括 `partial`、`no_values`、`failed`、`blocked` 或 `not_attempted`）→ `partial_success`。
6. 所有已终结 items 的基础与经营状态均 success → `success`。空批次沿用现有空批次结果，不伪造商品计数。

终态 Batch item 的基础 `status` 继续只有 `success / failed / verification_required`；每个 item 另带上述六值之一的 `operating_metrics_status`。无 CollectionRun 的预校验拒绝 item 记 `not_attempted`；被现有验证机制拦截且页面整体未获准读取时经营状态为 `blocked`。Batch 六值计数对所有已终结 items 逐项累计，必须满足计数总和等于 `completed`；暂停、冷却和剩余 items 不计入终态计数。Runner 错误及锁竞态保持既有 outcome wire code，不改名。

保持现有 pause/resume/end、cooldown、remaining、单 Runner、Run attempt 和采集节奏合同。定时自动采集仍只触发现有 Batch Runner。已知验证状态的检测范围不在本 Feature 扩大。

### 6. API 与查询

不新增单独经营指标查询路由。扩展现有：

- `GET /api/competitors/{id}/detail?days=7|30`：增加该 Offer 的字段目录、最新一次状态、最新有效原值、source、`observed_at`、缺失原因和基础/经营状态。当前自有商品和竞品均适用；身份来自 `ownership`，不从 `group_role` 推断。
- `GET /api/competitor-groups/{group_id}/detail?days=7|30`：在每个既有 Offer 行增加同一经营字段结构与基础/经营状态。结果来自该组当前 membership；self 与直接竞品均显示，Offer 是记录粒度，不按店铺/company 聚合。
- 两个详情响应都提供独立 `latest_collection_run`（最新 Run，含失败）及每字段 `latest_attempt`、`latest_valid`。最新 Run 按 `started_at DESC, id DESC` 全量查询，不依赖 Observation；字段两种查询仅从真实 Observation 获取。Run History 与 CollectionRun List 增加经营状态字段，原 `status` filter 和旧属性不变。Batch status 的每 item 返回基础 `status` 与 `operating_metrics_status`，另有六值经营状态计数和终态 `outcome_code`；`succeeded/failed/verification_required/completed/remaining` 仍按基础终态计数。

Group Detail 一次请求内，对当前成员 ID 集合执行有界批量查询：窗口函数或等价的集合查询按成员 ID 一次取 latest Run，再按成员/字段一次取 latest attempt 与 latest valid，不允许在逐成员序列化循环里发 SQL。空组/无数据返回空字段或 null，不作逐商品详情 API fan-out。单商品详情可在同一查询中批量取该商品 Run 与字段观察。稳定按目录顺序返回。

Group Detail 的覆盖率按**字段分别统计**：分母是该次响应时组当前 membership 中 `is_active=true` 的商品 Offer，包含 ownership=self 和 competitor，也包含仍在监控但商品状态为 offline 的 Offer；不含停止监控商品及 Hold 字段。分子是该 Offer 存在至少一条 `observed` Observation（即当前 `latest_valid` 非空）。不设观察时间截断，故 API/UI 必须称“有历史有效值 N/M”，并提供每 Offer 的有效值观察时间；不能称“本次采集覆盖率”“本批次覆盖率”或暗示这些 Offer 同批采集。由于没有持久化 Batch ID，各商品最新尝试来自不同 Run 时也只展示逐 Offer 时间/状态，不聚合成当前批次覆盖。若需要描述最近尝试，展示其状态及对应时间，不与历史有效值分子混算。

建议字段响应形状：

```json
{
  "metric_key": "monthly_deal",
  "latest_attempt": {
    "collection_run_id": 45,
    "status": "placeholder",
    "raw_value": "-",
    "source": "1688_official_procurement_assistant_top",
    "observed_at": "2026-10-10T13:57:49+08:00",
    "reason": null
  },
  "latest_valid": {
    "collection_run_id": 38,
    "raw_value": "20+",
    "source": "1688_official_procurement_assistant_top",
    "observed_at": "2026-10-09T13:57:49+08:00"
  }
}
```

同一详情对象另含 `latest_collection_run: {id, started_at, finished_at, status, operating_metrics_status, error_type, error_message}`，其 Run ID 与字段观察的 `collection_run_id` 可不同。无有效值时 `latest_valid=null`；没有字段 Observation 时 `latest_attempt=null`。Hold 字段回 `eligible=false, status='not_attempted'` 且不查询/填值。身份不符时本次 Run 不返回有效的新观察，但历史仍可按 Offer 所属商品读取。API 不提供派生数值、排序名次、增长率或评分。

### 7. UI 范围

- 单商品详情在现有详情信息区分别展示最新 CollectionRun 的基础状态/经营状态/失败时间，以及经营字段 `latest_attempt` 和 `latest_valid`。最新 Run 失败且无新 Observation 时必须显示该次全局失败和结束时间，同时保留旧有效值、旧有效值原采集时间及旧字段尝试时间；不得把旧 Observation 标为本次结果。
- Group Detail 继续仅有已冻结的「竞争总览 / 经营表现 / 口碑履约」三视图。五项成交/上架字段进入经营表现；评论数、好评率、揽收率与已准入后的收藏数进入口碑履约。Hold 字段显示“待接入”，不能显示“无标签/无收藏”。
- 每个字段可同时展示“最新有效值及其时间”与“最近一次字段尝试状态/缺失原因”；来源可见且不把其时间伪装成本次采集时间。Group Detail 的汇总仅显示“有历史有效值 N/M”，分母为当前仍监控 Offer，不能标成批次/本次覆盖。对 `-`、loading、来源不可用、读取失败、最新 Run 全局失败、未采集、Hold 使用不同文字。
- 不新增独立页面、导航、UI 重构、自定义过滤/排名、趋势图、销量排名、增长计算或综合评分；不让前端推导值的业务语义。

### 8. 迁移兼容

旧数据库没有 Observation 时 API 返回 `latest_collection_run`（如有）、`latest_attempt=null`、`latest_valid=null`；旧 Run 的新 `operating_metrics_status` 统一迁移为 `not_attempted`。不得回填 Observation、虚构字段尝试或把旧全成功 Run 补成指标成功；保留既有 `CollectionRun.status/error` 和所有旧基础 API 字段语义。Alembic upgrade/downgrade 在临时数据库验证；禁止直接操作用户真实 SQLite 数据。

## Testing Decisions

测试最高复用现有 seams：同一 page 生命周期内的 `collector_1688` 结果、`collect_competitor` 的事务/Snapshot 保存、`_delete_competitor_history` 的删除事务、`BatchRuntime` 的唯一 Runner、`GET` 单商品详情与 Group Detail/CollectionRun API Contract、既有 Detail/Group Detail 浏览器视图。不得只测试独立解析 helper 而遗漏 Service、事务、API 或批次行为。

### 必须自动化覆盖

1. 八字段都从唯一正确助手顶部区域读到：保留 `100+`、`<10`、`96%` 原文、同 Offer、来源和时区观察时间；经营状态为 `success`。
2. 部分字段 observed，其余含占位、loading、source_unavailable、read_failed 的任意混合：状态明确为 `partial`；占位原文/错误原因保存，不能存 0。
3. 0 observed 且八项全部 placeholder：状态为 `no_values`；0 observed 且全是技术失败、或 placeholder 与任何技术失败混合：状态为 `failed`。跨全部状态组合验证真值表，并确认 blocked/not_attempted 优先规则。
4. 面板未加载且身份/页面整体可信：经营字段保存真实 source_unavailable/loading，状态 failed；可信基础 Snapshot 正常保存。若 Offer ID/页面身份全局校验失败则无 Observation，Run=`failed / blocked`。
5. 基础解析失败但同页经营字段可读：Run 基础状态 failed，合法 Observation 保留，经营状态按八字段结果判定；基础 Snapshot 不写。反向场景基础成功但经营字段解析失败：基础 Snapshot/SKU/ChangeEvent 正常保存，Run 经营状态 failed，不标全成功。
6. 数据库 flush/commit 失败：整组业务事实回滚，无 Snapshot/SKU/ChangeEvent/Observation/Competitor 更新残留；仅新事务保留失败 Run。不得产生字段级“数据库失败 Observation”。
7. 最新 Run 失败且没有新 Observation：详情仍返回/显示该 Run 的失败状态与时间；latest_attempt/latest_valid 保留其旧 observation 时间和 Run ID，不把旧值标成本次结果。
8. Offer 身份不一致：不写成功 Snapshot/有效 Observation；旧值保留，API 返回最新 Run 失败，不制造字段状态行。
9. `self` 与 `competitor`：同一来源/状态合同；组查询包含组内 own 和竞品，未分组 self 可单商品查询，不因角色混淆归属。
10. 手动、定时和批量入口使用同一 Service/Runner；Outcome 优先级覆盖用户结束、现有验证终止、基础设施失败、基础 item 失败、经营 partial/no_values/failed/blocked/not_attempted 和全部成功；验证覆盖页面内容时只验证现有检测若识别则沿用人工处理状态，不把漏检场景改成通过条件或扩大检测范围。pause/resume/end、cooldown、remaining 及计数不回归，不产生新调度器。
11. 商品确认下架：沿用既有 offline 逻辑，不造空 Snapshot/Observation，保留历史有效值；恢复后新观察追加，不覆盖旧记录。
12. 旧数据迁移：旧 Run 的经营状态一律为 not_attempted；API `latest_attempt/latest_valid=null`（除非已有 Observation）；无 NULL 历史回填，旧 Snapshot/Run 字段和 API 输出兼容，upgrade/downgrade 可用。
13. 单条删除、批量删除：Observation 按显式顺序先于 CollectionRun 删除，所有 FK 满足；单事务成功后不留该商品历史孤儿，任意删除阶段错误时回滚并保留完整 Competitor/Snapshot/Run/Observation/ChangeEvent 历史。
14. Group Detail 一次 API 请求批量返回成员 Run 和经营字段，不随成员数产生 N+1；分母只含当前组 active 监控商品（self+competitor，offline 但仍 active 也计入），分子为各字段存在历史 latest_valid 的 Offer 数；无时间截断但显示逐 Offer 时间，绝不标为本次/当前批次覆盖。
15. 收藏和八标签 Hold：正式 Collector 不写任何值或 not_displayed 行，UI 显示待接入。

### 本地真实样本人工验收

- 用 Gate 1 五链接逐 Offer 对照：`1079906223307`、`1080864798243`、`1081895898799` 显示八字段原值；`1083985416394`、`1082904060172` 的评论数及好评率显示本次 `-`，同时不得抹掉先前有效值。
- 对照 `formal-batch-10-20261010-103506.jsonl`：原 10 条 success 只代表当时记录的基础采集结果；现有验证检测漏检是独立已知问题，不要求本 Feature 修复，也不能从旧日志推断验证已被可靠排除。
- 验证弹窗覆盖商品内容：该漏检按独立已知问题记录；本 Spec 不要求扩大检测或将该场景的检测成功作为 Freeze/Implement 验收条件。若沿用机制识别出验证，则继续现有暂停、冷却及人工处理；不能绕过验证，也不能把原 10 条基础 success 当成验证已排除或指标全成功的证据。
- 用五链接样本确认 3 条八字段全有原值；另 2 条评论数和好评率为占位。人工验收按最新 Run、字段 latest_attempt 和 latest_valid 三层显示，核对 Offer、来源、时间及覆盖口径；Spec 阶段不访问平台。

## Out of Scope

- Collector、模型、Alembic migration、API、Frontend、测试、POC、浏览器 Profile 或 Chrome 扩展实现。
- 独立经营指标页面或 Dashboard / 导航/UI 全面重构。
- 收藏数、八种标签在字段级 Playwright 验收前的正式采集。
- 精确成交量、口径推导、销量排名、跨 Offer 比较、增长、趋势、综合评分或公司级汇总。
- 新采集调度器、独立浏览器/用户 Profile、逐商品点击扩展、自动处理验证码、风控规避、未经授权接口。
- 修复现有验证弹窗检测漏检；该项保留为独立已知问题，沿用当前验证处理，不扩大本 Feature。
- 本轮访问 1688、修改 Research/POC/实验文件或处理其他工作区改动。

## Further Notes

### Spec Freeze 与实施先决条件

本文件写完且本地一致性自检通过后可按授权单独 Commit/Push，随后等待 ChatGPT 从 GitHub 做独立 Final Spec Review。Push 不代表 Freeze。只有 Review 通过且本文件标注 Freeze 后才允许 Implement。验证漏检和许可专项研究均不是本轮 Freeze/Implement 前置条件；Spec 不发布到 Issue Tracker。

### 接受标准

- 八字段只有同 Offer 正确助手顶部区域产生的原值才可标为 observed；raw 原文不转换、不与分销代发指标混用。
- CollectionRun 基础状态、经营 Run 状态、字段 latest_attempt、字段 latest_valid 四者不混淆；全局身份/来源失败无字段 Observation，失败不清空历史值。
- 手动、批量、定时均复用同一 Playwright Profile、采集服务与 Batch Runner 和当前采集节奏。
- 两个既有详情表面显示真实 Run、字段状态/值/来源/时间；Group Detail 历史有效值分母/分子及不同步时间表述准确，不出现 N+1 查询。
- 迁移与删除明确兼容；不制造虚假历史，旧 Snapshot/Run/API/页面保持兼容，删除事务可回滚。
- 所有上列 Spec 验收场景明确且一致；现有验证检测缺口按独立已知问题记录。
