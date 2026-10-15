# 添加链接首轮经营指标与输入去重 V1.4

状态：**Draft / 待 ChatGPT Review**（2026-10-15）。

基线：`0cff99870a2feb4e6d852e977bc0f2d6aab470ef`。本 Spec 只定义实现合同，不授权实施、Freeze、迁移或真实采集。

本轮定向修订基线：`aeb748c9fb00d2e4e717fdbb804c6a1e488e35a7`（P0=0、P1=2、P2=2，NOT FROZEN）。

## 1. 问题与目标

添加链接已通过现有 Collector 单次访问获得 `CollectionPageResult`，其中包含商品信息和经营指标，但当前添加保存路径只写商品、快照和一个 `not_attempted` Run，丢弃了实际指标。添加窗口粘贴和提交前也不按 Offer ID 去重，重复链接会进入新任务并产生 `duplicate_input` 结果。

V1.4 仅修正这两处：首次添加沿用同一次页面结果保存商品与真实经营 Observation；新 UI 在粘贴及提交时按 Offer ID 去重。继承 [1688 经营指标正式集成 V1](1688-operating-metrics-integration-v1.md) 的八项字段来源与原值合同、V1.2 的 Observation 语义与批次统计，以及 V1.3 的添加任务、输入行、导航证据、并发受理、`submission_id`、pending envelope 和幂等重放合同。V1.4 的新增规则只覆盖与之冲突的添加链接行为；普通手动/定时采集、Scheduler、采集互斥和历史记录保持原合同。

## 2. 当前实现核对

| 区域 | 基线事实 | V1.4 变化 |
| --- | --- | --- |
| 添加入口 | `App.tsx` 以 `parseCompetitorUrls` 拆分非空行；剪贴板直接拼接；提交体按输入数组生成 `source_line`。 | 粘贴合并和提交预处理均按有效 Offer ID 去重，保留首次输入及其行号。 |
| 采集与保存 | `collector_1688.py` 的 `CollectionPageResult` 含 `ProductData`、`product_error` 和 `operating_metrics`；`add_links.py` 目前保存商品/SKU/快照及成功 Run，但将 Run 与 Item 状态写为 `not_attempted`，不保存 Observation。 | 添加成功的一个候选使用本次同页结果保存基础事实、Run 和实际 Observation。 |
| 校验与模型 | `service.py` 已有商品归一化及八个指标键、状态和 Offer ID 校验；`models.py` 已有 `OperatingMetricObservation`、Run/指标唯一约束、来源/原值/观察时间字段及 `CollectionRun.operating_metrics_status`。 | 复用现有模型和校验；无须新增 Schema 或迁移。指标来源需按下节收紧校验。 |
| 批次记录 | `batch_records.py` 能序列化添加输入与关联 Run，但 `add_task_detail` 把经营状态和 Observation 固定为空/`not_attempted`；添加筛选排除了经营 Observation 状态。 | 返回真实 Run 状态和 Observation；添加批次首页及详情筛选以持久化事实为准。 |
| 重复处理 | `add_links.py` 与 `CollectionAddInput.result_code` 支持 `duplicate_input`，V1.3 将其纳入业务拒绝统计；现有数据库 Offer 唯一约束和 API 防重复处理仍有效。 | 新 UI 正常提交不含重复有效 Offer；后端旧客户端防重及 `duplicate_input` 的历史/API兼容保留。 |

已核对相关测试：`test_collection_unification.py`、`test_operating_metrics.py`、采集记录 API/UI 测试、`App.test.tsx`、`CollectionTasks.test.tsx`、`collection-unification.spec.ts` 和相关添加入口 Playwright seam。测试矩阵优先扩展这些边界，不增加采集框架。

## 3. A：添加时保存当次经营指标

### 3.1 页面访问和成功事务

1. 每个候选 Offer 最多执行一次真实商品页面导航。基础商品和经营指标复用同一次 `CollectionPageResult`；不再次导航、不启动经营补采、不创建额外 Run、不新增 Collector、Runner、浏览器会话或队列。
2. 仅在商品页面身份、商品归一化和我方店铺/组约束均通过后，才将该候选判为新增成功。Offer 身份不一致或数据不能安全关联时拒绝该候选，不能把错误商品或指标写入数据库。
3. 商品、SKU、`ProductSnapshot`、`CollectionRun`、实际 `OperatingMetricObservation`、Batch Item 关联、添加输入结果和成功状态在同一候选数据库事务中提交。任一写入失败则回滚该候选的全部成功数据；后续错误结果收口沿用 V1.3，不重新访问页面。其他候选已完成的事务不受影响。
4. Run 的开始/结束时间和导航证据继续遵循 V1.3：输入行是添加导航 claim/confirmed 的权威来源，Run 不伪造独立导航证据；Run 关联本次新增商品及 Batch Item，序号为首次尝试。

### 3.2 Observation 与状态

八项固定指标沿用 `1688-operating-metrics-integration-v1.md`：`listing_time`（上架时间）、`monthly_deal`（月成交）、`monthly_dropship`（月代销）、`annual_units`（年成交件数）、`annual_orders`（年成交笔数）、`review_count`（评论数）、`positive_rate`（好评率）、`pickup_rate`（揽收率）。只存页面原始字符串及实际状态、来源、Offer ID、观察时间和原因；保留 `100+`、`<10` 等值，不转换为估算数字。

- 对 Collector 实际返回的字段逐条保存 Observation；保留 `observed`、`placeholder`、`loading`、`source_unavailable`、`read_failed` 的现有语义及原值规则。
- 没有经营读取结果/证据时，不生成八条虚构 Observation，Run 和 Item 的经营状态为 `not_attempted`。
- 添加模式按下表从真实 Observation 派生状态；复用现有六种枚举，不修改 V1.2 普通手动/定时采集的 `operating_metrics_status()` 合同。Run 与 Item 记录同一经营状态。经营字段缺失、占位或读取异常只影响经营状态，不单独把基础商品成功改成失败。
- 指标身份校验必须覆盖八个已知键、同次无重复键、每条 Observation 的 Offer ID 等于目标 Offer，来源为 V1.2 准入的 1688 官方采购助手顶部区域（`1688_official_procurement_assistant_top`），状态及原值组合符合 Observation 约束。身份或来源不匹配、未知/重复键等无法安全关联的结果不得写入，并按添加候选失败处理；不得静默跳过疑似串商品的数据。
- 返回值没有指标列表表示没有读取证据，按 `not_attempted` 保存。Collector 提供了可安全关联的部分真实 Observation 时只保存这些实际项，不补齐不存在的字段；状态仍使用既有聚合函数。不得将缺字段推断为 `source_unavailable`。
- 指标异常不覆盖既有有效 Observation，不改写历史 Run。历史添加批次中的 `not_attempted` 及空 Observation 保持原事实，不回填、不追采。

添加模式经营状态映射（仅针对该次添加 Run）：

| 当次实际 Observation | Run / Item 经营状态 | 技术异常 |
| --- | --- | --- |
| 0 条 | `not_attempted` | 否 |
| 恰好 8 条且全部 `observed` | `success` | 否 |
| 至少 1 条 `observed`，但不是上述完整 8 条 | `partial` | 若任一字段为 `source_unavailable / loading / read_failed`，是 |
| 1–8 条且全部为 `placeholder`（包括不足 8 条） | `no_values` | 否 |
| 至少一条技术状态且没有 `observed` | `failed` | 是 |

键、来源、身份、状态或原值组合不合法仍按前述校验拒绝，不套用此映射。实际 Observation 必须逐条保留，不能因状态映射补齐缺失字段。此添加专用兼容映射不改变普通手动/定时采集：它们继续调用现有 `operating_metrics_status()` 并遵循 V1.2 合同。

基础新增结果与指标结果分开：只要基础商品及身份/店铺/组校验成功，输入仍为 `added`、Batch Item 的 `base_result` 为 `success`、Run 的基础 `status` 为 `success`；经营字段技术异常不把它们改成失败，也不改变添加任务按输入结果派生的 `outcome_code`。Batch Item 的经营状态、`placeholder_count`、`source_unavailable_count`、`loading_count`、`read_failed_count` 和 `technical_exception_count` 必须由该候选已提交的真实 Observation 派生；后者等于三种技术状态 Observation 数之和。无 Observation 时这些计数为 0。缓存可由 Observation 幂等重建。

添加任务摘要口径固定如下：

- `input_summary.anomaly_inputs` 仍只统计 V1.3 的输入结果异常（`technical_failed + verification_required + interrupted`），不包含任何经营字段状态。
- `technical_exception_products` 是本添加批次中至少有一条 `source_unavailable / loading / read_failed` Observation 的不同候选商品数；不统计异常字段条数。
- `anomaly_products` 是有输入处理异常或经营技术异常的不同添加输入/候选数，即两类异常按输入行取并集后计数；同一候选的输入失败与指标异常不重复计数。Placeholder 不进入该数。
- `current` 命中已有输入异常，或当前候选有实际经营技术 Observation 的输入；`none` 命中已收口且无上述异常的输入，包括只有 placeholder 或 `not_attempted` 的成功添加。`base_failed` 只命中基础新增失败，不因经营异常命中。`placeholder` 可筛选，但不算技术异常。

### 3.3 批次收口与恢复

1. 新增成功事务必须同一提交真实 Observation、Run 经营状态、Item 经营状态和上述 Observation 派生计数，以及商品、快照、SKU、输入 `added` 和 Item linked 状态。
2. 正常批次收口只补齐尚无结果的输入，不得重写已经提交成功输入的 Run/Item 经营状态、Observation 或异常计数；重复收口结果幂等。
3. 进程中断恢复和重复收口不得重置已提交成功商品的 Observation、经营状态或异常计数，也不得重访页面。允许从该成功商品已保存的 Run/Observation 幂等重建 Item 状态及计数缓存。
4. 旧添加任务的 `not_attempted` Run 和空 Observation 是历史事实；收口、恢复、列表/详情查询均不得将其推断或回填成其他状态。

### 3.4 展示、查询与筛选

新增商品详情和添加批次详情应显示本次 Run 的真实经营状态及实际字段 Observation，包括状态、原始值、来源、观察时间、原因。无 Observation 才显示“未读取经营指标”，不可对所有添加 Run 固定显示“经营指标未采集”。

复用现有记录 API 的 `anomaly` 参数，不另建 API：

- 添加批次首页和详情均支持 `current`、`none`、`base_failed`、`placeholder`、`source_unavailable`、`loading`、`read_failed`；详情的具体状态筛选按该输入关联 Item/Run 的 Observation 查询。
- `trigger_kind=all` 时同一筛选对普通采集和添加任务使用各自真实 Observation；无添加 Observation 的历史行不命中具体状态筛选，不能被补造。
- `trigger_kind=add_links` 不允许 `recovered`，保持现有不兼容参数的 422 行为；`trigger_kind=all` 的 `recovered` 仍只按普通采集合同查询，添加任务不匹配。
- 前端添加任务详情提供这些具体 Observation 状态选项，并显示上节定义的输入异常与经营异常分离计数。只 `placeholder` 可筛选但不算技术异常，`base_failed` 不因经营状态命中。首页、详情和 `trigger_kind=all` 的 `current / none` 判定及计数必须与 API 一致。

添加模式没有经营补采，因此不产生 `recovered` 指标状态；不得为兼容筛选而合成恢复事实。商品基础成功与经营异常须分别表达、分别统计。

## 4. B：剪贴板和提交去重

1. 剪贴板读取后拆分非空行。有效链接判定与 Backend `parse_1688_url` 一致（HTTPS、主机 `detail.1688.com`、`/offer/{digits}.html` 路径及现有端口规则）；query/fragment 不参与 Offer 身份。Offer ID 是唯一去重键。输入框中已有的文本原样保留；剪贴板内首次出现且输入框没有的有效 Offer 按原顺序追加，后续同 Offer 行过滤。再次点击粘贴会因已存在而过滤，不再增加重复项。
2. 若剪贴板全是已存在/剪贴板内部重复的有效链接，且没有新的无效输入，则输入框完全不变，并提示“链接已存在，无需重复添加”。若有新有效链接，只追加每个新 Offer 首次出现项，并提示新增数和过滤重复数（例如“已添加 8 条，过滤重复 3 条”）。剪贴板包含重复有效链接和无效行时，过滤重复有效链接、按顺序追加无效行以供原有校验；不能因无效行而保留重复有效链接。剪贴板空白或读取失败沿用现有提示。
3. 手动编辑文本后，提交前在输入副本上运行相同 Offer ID 去重：仅保留每个有效 Offer 首次出现行，顺序不变；无效/不支持行逐行保留，仍走现有错误处理，不归类为重复。此预处理不得在已冻结的 pending envelope 重放时再次运行。
4. `source_line` 是提交前用户可见文本的真实物理行号（从 1 起，包含空行位置）；`position` 是去重后提交列表中的连续顺序，两者独立。过滤空行或重复项不得导致保留行的 `source_line` 被重新编号。最终每条提交的 text、position、source_line 一一对应。
5. 去重后的最终列表是新任务的唯一计数口径：提交按钮数量、进度、输入总数和 `CollectionAddInput` 总数一致。沿用 V1.3 的 100 条非空输入上限，按提交列表计数并校验，不静默截断；无效行仍计入列表并由后端判错。
6. 首次准备提交时只执行一次上述去重，然后生成 `submission_id` 并将精确的有序 inputs（text、source_line）和 group_id 写入 pending envelope。提交结果未知、刷新查询或幂等重放都必须使用 envelope 的原始冻结内容，不得重新读取/去重当前文本或改变 fingerprint。用户明确修改后新提交仍按 V1.3 规则先解决旧提交身份，再生成新 envelope/id；并发受理、查询与幂等协议不变。

### 后端与历史兼容

数据库商品唯一约束及后端按 Offer ID 的最终重复检查继续作为并发/旧客户端的安全边界。API 仍识别并处理 `duplicate_input`，不删除结果码、历史行、计数或查询能力；新 UI 正常提交不应产生该结果。新的添加任务 UI 不再把“提交内重复”作为常规业务结果类别；旧批次中的 `duplicate_input` 仍以兼容的历史结果呈现，统计事实不变。商品已存在（库中已有商品）与同次提交重复（API 收到两个输入）仍是不同结果。

## 5. Schema、范围与继承

不新增表、列、枚举、索引或迁移。现有 Observation 足以关联 `competitor_id + collection_run_id + platform + offer_id + metric_key` 并保存状态、原值、来源、时间和原因；Run、Batch Item、添加输入及 `uq_competitors_platform_offer_id` 足以表达事务和唯一性。实施若发现当前 ORM/数据库合同无法承载上述事实，应先回报具体缺口并更新 Spec，不得擅自迁移。

明确不做：普通手动/定时采集策略调整、Scheduler/采集互斥变更、经营指标重试、V1.3 添加批次重做、视觉系统重构、额外 API/服务/任务队列、历史数据回填、正式数据库迁移、真实 1688 采集。

## 6. 最小验收矩阵

以下均为后续实现验收设计，不是本轮已执行测试。只使用注入 Collector/导航计数、Backend API、隔离 SQLite、React 单测和受控 fail-closed Playwright；不连接真实 1688 或正式数据库。

| 场景 | 必须观察到的结果 | 优先边界 |
| --- | --- | --- |
| 八项真实值 | 单次 Collector/导航；商品、SKU、快照、一个成功 Run、八条原始 Observation 和输入/Item 关联均存在；状态、source、Offer ID、observed_at 正确。 | API + 隔离 SQLite + Collector spy |
| 添加模式状态映射 | 六个新增候选分别返回：①8 observed→`success`；②2 observed+1 placeholder→`partial`；③8 placeholder→`no_values`；④3 placeholder 且其余无证据→`no_values`；⑤1 source_unavailable+2 placeholder、无 observed→`failed`；⑥0 Observation→`not_attempted`。六者各自只保存实际返回 Observation；③④不计技术异常，⑤技术字段数/Item `technical_exception_count`=1。普通手动/定时的部分 placeholder 映射仍按 V1.2，不随本版改变。 | 添加 API + 隔离 SQLite |
| 来源和身份校验 | 正确官方来源及目标 Offer 可保存；任一 Observation Offer/source 错误或不能安全关联时拒绝，零错配商品/Observation。 | API + Collector 注入 |
| 经营异常映射及筛选 | 前述⑥个候选全为输入 `added`、Run `status=success`、`input_summary.anomaly_inputs=0`；仅候选⑤有技术 Observation，因此 `technical_exception_products=1`、`anomaly_products=1`。`current` 返回⑤，`none` 返回其余五个，`base_failed` 返回0，`placeholder` 命中②③④⑤但不增加技术异常计数。具体四类状态在 add_links 详情及 `trigger_kind=all` 查询命中真实关联 Observation；`recovered` 不匹配添加任务。 | API 列表/详情 + React/Playwright |
| 候选保存事务失败 | 商品、SKU、Snapshot、Run、Observation、linked 状态无半成品；只发生一次页面访问；按 V1.3 收口真实失败/导航事实。 | 隔离 SQLite commit fault + spy |
| 幂等重放 | 同一 submission 重放不新增 Batch/Run/Observation、不重新访问页面；异 fingerprint 冲突规则不变。 | API + Collector spy |
| 收口后崩溃恢复 | 新增成功并保存指标后收口，再模拟进程重启恢复、重复收口及再次查询：Run 状态、所有 Observation、Item 经营状态与四类状态计数/`technical_exception_count` 完全不变，页面访问次数不增加；允许删除派生 Item 缓存后从保存记录幂等重建。旧 `not_attempted` Run/空 Observation 查询前后不变。 | 隔离 SQLite + add_links recovery/finalize + API |
| 剪贴板混合输入 | (a)剪贴板全为已有/内部重复有效 Offer：textarea 内容逐字不变、提示全部重复；(b)有效重复+新 Offer：只追加新 Offer 首次项；(c)有效重复+无效行：重复被过滤、无效行保留并可被后端判错；query 不同同 Offer 按重复处理；再次粘贴不再追加。 | `App.test.tsx` + 受控 Playwright |
| 手动输入提交 | 手动文本中 query 不同的有效同 Offer 只提交首次项；无效行保留；例如保留物理第1、第4行时提交 `source_line=[1,4]`、position=`[0,1]`；所有有效 Offer 已在文本/粘贴列表出现时不额外提交。 | React 单测 + 添加 API |
| pending envelope 冻结 | 首次提交前去重并冻结 inputs；模拟受理未知、刷新和重复 POST 时，有序 text/source_line/group_id 与同一 `submission_id`、fingerprint 结构和值一致地重用，即使当前 textarea 后续内容变化也不重新去重。 | React 单测 + `collection-unification.spec.ts` |
| 数量上限 | 100 条去重后输入可提交；超过 100 不截断且按既有 422 合同拒绝；按钮、进度、批次 total 与真实提交列表一致。 | React 单测 + API |
| 已存在与提交内重复 | 新 UI 对相同 Offer 只发送一项；后端仍分别识别库内已存在和旧客户端提交内重复，后者保持 `duplicate_input` 统计/API 兼容。 | API + React |
| 历史及普通采集回归 | 历史 duplicate_input、历史 add_links not_attempted Run/Observation、既有历史筛选事实不变；普通手动/定时补采与观察序列化合同不变。 | 隔离 SQLite fixture + API |

## 7. Review 与交付门槛

本文件和必要索引状态保持 Draft / 待 ChatGPT Review。ChatGPT 从远端读取本次提交的 Spec 做独立 Spec Review；通过后才可 Freeze。Review 未通过时只按 Review 修订 Spec 并单独提交。未经 Review 不实施业务代码，不迁移数据库，不访问真实 1688。
