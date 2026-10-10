# 1688 经营指标正式集成 V1 Spec

状态：待 ChatGPT 独立 Spec Review；未 Freeze，禁止进入 Implement。<br>
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
- Research 记录：收藏数仅有单一 A19 商品原值候选；八种平台标签没有带标签正样本。适用平台/采购助手许可尚无明确证据。Research 中旧探针只检查 URL/标题不能证明没有页面内验证；页面内嵌验证盲区仍需正式修复。

### 实现前硬门槛

1. **P1 阻塞：验证页漏检。** 实现经营指标前，先补齐全局页面可信性检测（见「P1：验证页可信性阻塞」）。Collector 不得因页面主商品内容仍可解析而把带验证弹窗的页面判成功。此 Spec 不修改 Collector。
2. **平台许可门槛。** 实现和启用前，项目负责人须确认当前平台条款、采购助手/扩展许可覆盖项目 Chrome Profile 内自动读取、保存及本地展示用途。没有许可证据时不得启用采集；用户确认访问不等于平台授权。不得绕过验证码、登录、验证、风控，不读 Cookie/账号存储，不抓取未经授权私有接口或重放请求。
3. **字段级准入。** 八项采购助手指标以本 Spec 的来源和原值合同为准；字段可独立准入，某字段或某商品失败不阻塞其他已准入字段。收藏数和八种平台标签维持 Hold，直到现有 Playwright 路线取得字段级来源、归属、原值/缺失和失败隔离验收；不得依赖自制 Chrome 扩展来解除 Hold。

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
| `listing_time` | 上架时间 | 当前 Offer 的「1688官方采购助手」顶部区域 | 原样字符串；不替换为商品发布时间，不推断首次上架/重上架语义 | Gate 1 样本已观察；按本合同准入原值采集，仍受许可门槛约束 |
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
| `status` | `observed`、`placeholder`、`loading`、`source_unavailable`、`read_failed`、`verification_required`；Offer 不匹配是全局失败，不绑定到此商品写 Observation |
| `raw_value` | 原始字符串；`observed` 必须非空，`placeholder` 存页面实际占位符（如 `-`），技术缺失状态为 NULL；不保存派生数值 |
| `source` | 精确来源标识；八项为官方助手顶部区域，后续解除 Hold 的字段采用对应可见区域标识 |
| `observed_at` | 页面字段读取时的带时区时间；同次采集的字段可共享一次 DOM 读取时刻 |
| `reason` | 可读的缺失/读取失败原因；成功及占位可为空 |

新建 Alembic revision：建表、FK/check/唯一约束及 `(competitor_id, metric_key, observed_at, id)` 查询索引，并为 `CollectionRun` 增加非空 `operating_metrics_status` 列；迁移旧 Run 时默认 `not_attempted`。不得修改或回填既有 ProductSnapshot，不给旧商品造全 NULL 经营快照，不做猜测性迁移。历史从首次真实 Observation 起算；不承诺存在更早记录。Observation 的删除/保留跟随该商品及 CollectionRun 的既有历史删除边界；不设自动过期或按天覆盖，失败、下架和后续缺值不得清除已存记录。

`ProductSnapshot` 继续只存基础商品级事实；`SkuSnapshot` 继续只存 SKU 事实。经营 Observation 与同次 Run 关联，但不嵌入 Snapshot，也不复制标题、价格、库存、SKU。经营字段失败不能阻止基础 Snapshot 保存；基础字段失败或全局可信性失败不能写任何成功基础事实或经营 Observation。

### 3. 有效值和状态判定

- **字段最近一次尝试**：按 `observed_at DESC, id DESC` 取最新 Observation，展示该次状态、原因和时间。
- **字段最新有效值**：独立地在同一商品、同字段范围内，过滤 `status='observed' AND raw_value IS NOT NULL AND raw_value<>''` 后按同一顺序取最新值。占位、加载、缺来源、读取失败、验证状态不得覆盖它。
- `placeholder` 是成功识别来源和字段后的页面观察，不是有效经营值。显示「页面显示 `-`」和占位观察时间；有效值若存在仍展示其原值及原时间。
- `loading`、`source_unavailable`、`read_failed` 描述本次不可读，不等同无数据、0、标签未出现或下架。无本次 Observation（包括 Hold 字段）显示“未采集/待接入”，不制造状态行。
- 八字段采集结果：8 项本次都为 `observed` → `success`；至少一项为 `observed` 且另有占位/读取缺失 → `partial`；来源/面板未就绪且无可读取字段 → `failed`；全局验证/身份等可信性问题 → `blocked`。允许字段集合为 0 时为 `not_attempted`。
- 数据库不存“目前没有有效值”的独立假记录；本次尝试的错误只在真实运行且身份可信时作为字段状态观察保存。若 Offer 身份不符或页面全局可信性未过，则仅记录 CollectionRun 全局失败。

### 4. P1：验证页可信性阻塞

当前 `collector_1688.py` 识别部分 URL、标题、可见选择器和特定 Baxia 文案；Gate 1 Research §11 明确旧 URL/标题检查漏检可嵌入商品页的验证。P1 在任何正式经营字段上线前关闭：

1. 校验点至少包括导航后页面稳定时、页面内容解析前、以及写入 Snapshot/Observation 前；检测顶层、可见内嵌验证框/iframe 与遮挡商品主内容的验证层。只基于正向页面证据判定，不能将网络 200、商品 HTML 可解析、字段可见或扩展 Service Worker 状态当作无验证证明。
2. 若验证 UI 覆盖/替代商品内容，或页面可信性不能确认，抛出既有验证/不可用错误：先回滚当前数据库事务，不能写 Snapshot、SKU、ChangeEvent 或 `observed` Observation；Run 记 `failed`，记录稳定错误码/安全摘要；经营状态记 `blocked`。不清除之前的基础或经营历史。
3. 单条手动采集失败并向 UI 报验证；Batch 与定时入口沿用现有验证冷却和有限自动恢复。每轮仅按现有配置尝试，不自动操作验证码。超出既有限制后进入 `verification_required`，保留人工浏览器窗口并停止下一个商品访问；人工处理只能走现有明示操作，验证未解除不得继续。批次停止/结束保持既有语义，不把尚未访问商品记失败或成功。
4. 必须补充 Collector 对“商品详情可解析但验证层覆盖”“可见验证 iframe/文案”“普通商品页不得误报”的回归测试；验证拒绝时断言完整回滚、Run 状态、基础历史和经营历史保留。还须经手动、Batch、定时路径验证同一 detector 生效。此门槛未关闭前，经营指标集成不得上线。

### 5. 单次采集、CollectionRun 与 Batch 状态

所有现有入口调用同一商品采集服务，依次执行全局页面可信性与 Offer 身份校验，然后独立执行基础解析/持久化和经营字段读取/持久化。读取经营字段不得另开商品页面或启动第二个 Chrome/Runner；每商品仅当前既有访问和节奏，不为了缺值重试页面或增加访问频率。

`CollectionRun.status` 继续表达基础可信商品采集状态，兼容既有 `running / success / failed`；新增 `operating_metrics_status` 表达 `not_attempted / success / partial / failed / blocked`。Run 的产品整体摘要由这两个明确字段共同表达，不能只根据 `CollectionRun.status='success'` 宣称经营字段也成功。经营字段失败而基础事实可信时，Run 基础状态仍 success，并在 UI/Batch 标明部分成功；不因非必要字段失败回滚可信价格/SKU Snapshot。基础采集失败时不生成新的有效经营观察。全局验证、Offer 不匹配、无法确认当前页面等错误令基础状态 failed，经营状态 blocked，且无成功写入。

Batch item 保留现有基础 `success / failed / verification_required` 计数，扩展每项的经营状态与聚合的完整/部分/失败计数；`succeeded` 仍只表示基础采集成功。若基础成功但指标 partial/failed，Batch item 对用户呈“基础成功 / 经营部分成功或失败”，批次 `outcome_code=partial_success`；基础项目失败仍用现有 `partial_failure`；两部分均成功为 `success`。暂停、继续、cooling_down、verification_required、人工处理、停止、恢复仍走现有 BatchRuntime/API。定时调度仍只负责按当前设置触发 Batch Runner，不自行访问商品、不新增调度队列。

### 6. API 与查询

不新增单独经营指标查询路由。扩展现有：

- `GET /api/competitors/{id}/detail?days=7|30`：增加该 Offer 的字段目录、最新一次状态、最新有效原值、source、`observed_at`、缺失原因和基础/经营状态。当前自有商品和竞品均适用；身份来自 `ownership`，不从 `group_role` 推断。
- `GET /api/competitor-groups/{group_id}/detail?days=7|30`：在每个既有 Offer 行增加同一经营字段结构与基础/经营状态。结果来自该组当前 membership；self 与直接竞品均显示，Offer 是记录粒度，不按店铺/company 聚合。
- 采集 Run/Batch 结果响应扩展为分别返回基础状态、经营状态及字段失败数；既有 Run 查询仍可用。`CollectionRun.status` 过滤仍筛基础运行状态，响应应显式返回经营状态，避免将旧客户端的 success 误解为经营成功。

Group Detail 一次请求内，对当前成员 ID 集合执行有界批量查询：窗口函数或等价的集合查询一次取每个成员/字段的 latest attempt 与 latest effective，不允许在逐成员序列化循环里发 SQL。空组/无数据返回空字段或 null，不作逐商品详情 API fan-out。单商品详情可在同一查询批量取该商品字段。稳定按目录顺序返回。

建议字段响应形状：

```json
{
  "metric_key": "monthly_deal",
  "latest_attempt": {
    "status": "placeholder",
    "raw_value": "-",
    "source": "1688_official_procurement_assistant_top",
    "observed_at": "2026-10-10T13:57:49+08:00",
    "reason": null
  },
  "latest_valid": {
    "raw_value": "20+",
    "source": "1688_official_procurement_assistant_top",
    "observed_at": "2026-10-09T13:57:49+08:00"
  }
}
```

无有效旧值时 `latest_valid=null`；Hold 字段回 `eligible=false, status='hold'` 且不查询/填入值。Offer 身份核验和来源若未通过则不返回已观察值给本次结果。API 不提供派生数值、排序名次、增长率或评分。

### 7. UI 范围

- 单商品详情在现有详情信息区展示经营指标原值、字段最近尝试状态、来源和各自时间；保留现有详情页结构及最近采集记录，不另开经营指标页。
- Group Detail 继续仅有已冻结的「竞争总览 / 经营表现 / 口碑履约」三视图。五项成交/上架字段进入经营表现；评论数、好评率、揽收率与已准入后的收藏数进入口碑履约。Hold 字段显示“待接入”，不能显示“无标签/无收藏”。
- 每个字段可同时展示“上次有效值及其时间”与“本次状态/缺失原因”；来源可见且不把最新有效时间伪装成本次采集时间。只显示实际覆盖计数，例如“3/5 个商品本次有值”；对 `-`、未加载、采集失败、未采集、Hold 使用不同文字。
- 不新增独立页面、导航、UI 重构、自定义过滤/排名、趋势图、销量排名、增长计算或综合评分；不让前端推导值的业务语义。

### 8. 迁移兼容

旧数据库没有 Observation 时 API 返回 `not_attempted` / `latest_valid=null`，基础 Snapshot、旧 CollectionRun、旧 API 客户端和 Group Detail 三视图继续正常工作。迁移不回填历史经营值、不把旧全成功 Run 补成指标成功，也不改变旧 Run 的 status/error 含义。新字段需使用兼容默认值（既有 Run 迁移后为 `not_attempted`），并为旧响应 consumer 保持原有基础字段。Alembic upgrade/downgrade 在临时数据库验证；禁止直接操作用户真实 SQLite 数据。

## Testing Decisions

测试最高复用现有 seams：`collector_1688` 的 Playwright 页面检查、`collect_competitor` 的事务/Snapshot 保存、`BatchRuntime` 的唯一 Runner、`GET` 单商品详情与 Group Detail 的 API Contract、既有 Detail/Group Detail 浏览器视图。不得只测试独立解析 helper 而遗漏真实页面/API/批次行为。

### 必须自动化覆盖

1. 八字段均从唯一正确助手顶部区域读到：保留 `100+`、`<10`、`96%` 原文、同 Offer、来源和时区观察时间；八项状态 `success`。
2. 部分字段为 `-`：写入占位观察、不存 0，其他字段照常入库；经营状态 `partial`，有效原值仍可见。
3. 助手面板未加载/不可见：经营状态 failed，缺失原因明确；基础 Snapshot 成功且历史值保留。
4. 后续基础采集失败或经营采集失败：不清理任何既有经营有效值；latest attempt 与 latest valid 分开返回。
5. 验证弹窗/iframe 覆盖商品内容：页面即使仍可解析也必须识别；完整事务回滚，无新 Snapshot、SKU、ChangeEvent 或有效 Observation，Run=failed、metrics=blocked；批次进入现有验证恢复/人工状态。
6. Offer 身份不一致：不把任一字段归到数据库 Offer，不存有效 Snapshot/Observation，Run 失败且旧数据保留。
7. 基础成功、经营失败：价格/SKU Snapshot 正常写入；Run/Batch/UI 清楚显示基础成功与经营失败，不能标全成功。
8. `self` 与 `competitor`：同一来源/状态合同；组查询包含组内 own 和竞品，未分组 self 可单商品查询，不因角色混淆归属。
9. 手动和定时 Batch：使用同一服务/Runner；验证 pause/resume/end、cooldown、普通失败、partial success 和停止时 remaining 语义不回归，不产生新调度器。
10. 商品下架：按既有 offline 逻辑不造空 ProductSnapshot/经营有效观察，保留历史有效值；恢复后新鲜观察建立新事实，不覆盖旧记录。
11. 旧数据迁移：无 Observation 的商品/Run 安全读为 not_attempted；迁移可升级、降级；无 NULL 历史回填，旧 Snapshot 与 API 输出兼容。
12. Group Detail 一次 API 请求批量返回多商品经营字段；SQL 语句数不随成员数线性增长，页面三视图覆盖数与缺失状态一致。
13. 收藏和八标签 Hold：即使出现页面文本也不由正式 Collector 写入，UI 不误报“未出现”。

### 本地真实样本人工验收

- 用 Gate 1 五链接逐 Offer 对照：`1079906223307`、`1080864798243`、`1081895898799` 显示八字段原值；`1083985416394`、`1082904060172` 的评论数及好评率显示本次 `-`，同时不得抹掉先前有效值。
- 对照 `formal-batch-10-20261010-103506.jsonl`：原基础批次 10 条 success 只说明基础结果；因验证弹窗检测缺口，该日志不能作为“验证无风险”证据。修复后必须以可信页面重新验证，不改写旧 Run 结论。
- 取得字段来源、Offer 归属、时间与 UI 实际覆盖均符合合同的手动验收；不得实际访问平台作为 Spec 阶段工作，也不得使用凭据/私有响应作测试夹具。

## Out of Scope

- Collector、模型、Alembic migration、API、Frontend、测试、POC、浏览器 Profile 或 Chrome 扩展实现。
- 独立经营指标页面或 Dashboard / 导航/UI 全面重构。
- 收藏数、八种标签在字段级 Playwright 验收前的正式采集。
- 精确成交量、口径推导、销量排名、跨 Offer 比较、增长、趋势、综合评分或公司级汇总。
- 新采集调度器、独立浏览器/用户 Profile、逐商品点击扩展、自动处理验证码、风控规避、未经授权接口。
- 本轮访问 1688、修改 Research/POC/实验文件或处理其他工作区改动。

## Further Notes

### Spec Freeze 与实施先决条件

本文件写完且本地一致性自检通过后可按授权单独 Commit/Push，随后等待 ChatGPT 从 GitHub 做独立 Spec Review。Push 不代表 Freeze。只有 Review 通过且本文件标注 Freeze 后才允许 Implement；P1 验证检测门槛与平台许可门槛仍须在正式上线前关闭。Spec 不发布到 Issue Tracker。

### 接受标准

- 八字段只有同 Offer 正确助手顶部区域产生的原值才可标为 observed；raw 原文不转换、不与分销代发指标混用。
- 基础和经营状态分离；占位、失败和验证不能清空过去值；全局可信性失败不能误标成功。
- 手动、批量、定时均复用同一 Playwright Profile、采集服务与 Batch Runner 和当前采集节奏。
- 两个既有详情表面可显示原值、来源、时间、缺失原因及覆盖情况，Group Detail 不出现 N+1 查询。
- 迁移不制造虚假历史，旧 Snapshot/Run/API/页面保持兼容。
- 所有上列验收场景通过，P1 和适用许可门槛有可审计关闭证据。
