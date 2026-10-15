# 添加链接首轮经营指标与输入去重 V1.4

状态：**Draft / 待 ChatGPT Review**（2026-10-15）。

基线：`0cff99870a2feb4e6d852e977bc0f2d6aab470ef`。本 Spec 只定义实现合同，不授权实施、Freeze、迁移或真实采集。

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
- 有实际 Observation 时复用 `operating_metrics_status()` 的既有聚合语义；Run 与 Item 记录同一状态。经营字段缺失、占位或读取异常只影响经营状态，不单独把基础商品成功改成失败。
- 指标身份校验必须覆盖八个已知键、同次无重复键、每条 Observation 的 Offer ID 等于目标 Offer，来源为 V1.2 准入的 1688 官方采购助手顶部区域（`1688_official_procurement_assistant_top`），状态及原值组合符合 Observation 约束。身份或来源不匹配、未知/重复键等无法安全关联的结果不得写入，并按添加候选失败处理；不得静默跳过疑似串商品的数据。
- 返回值没有指标列表表示没有读取证据，按 `not_attempted` 保存。Collector 提供了可安全关联的部分真实 Observation 时只保存这些实际项，不补齐不存在的字段；状态仍使用既有聚合函数。不得将缺字段推断为 `source_unavailable`。
- 指标异常不覆盖既有有效 Observation，不改写历史 Run。历史添加批次中的 `not_attempted` 及空 Observation 保持原事实，不回填、不追采。

基础新增结果与指标结果分开：输入仍为 `added`、Batch Item 的基础结果为 `success`、Run 的基础 `status` 为 `success`；经营字段技术异常不把它们改成失败，也不改变添加任务按输入结果派生的 `outcome_code`。Batch Item 的经营状态及异常计数从本次 Observation 更新。添加任务汇总继续保留 `input_summary.anomaly_inputs` 的输入处理口径，并用现有经营异常汇总字段另报有经营技术异常的不同候选商品数；该数按商品去重，不能把 Observation 异常字段数标成商品数。不得用输入拒绝数替代指标异常数，或把同一指标异常计作基础失败。

### 3.3 展示与筛选

新增商品详情和添加批次详情应显示本次 Run 的真实经营状态及实际字段 Observation，包括状态、原始值、来源、观察时间、原因。无 Observation 才显示“未读取经营指标”，不可对所有添加 Run 固定显示“经营指标未采集”。添加任务详情的 `current` / `none` 和 `placeholder / source_unavailable / loading / read_failed` 具体字段筛选须依照实际持久化记录；其中仅 `source_unavailable / loading / read_failed` 构成经营技术异常，placeholder 可筛选但不算技术异常。首页相应选项和计数不得因 `trigger_kind=add_links` 而把经营状态视为不可能；展示经营技术异常候选数时按不同商品计数。添加模式没有指标补采，因此不产生 `recovered` 指标状态；不得为兼容筛选而合成恢复事实。商品基础成功与经营异常须分别表达、分别统计。

## 4. B：剪贴板和提交去重

1. 剪贴板读取后立即拆分非空行。有效链接判定与 Backend `parse_1688_url` 一致（HTTPS、主机 `detail.1688.com`、`/offer/{digits}.html` 路径及现有端口规则）；query/fragment 不参与 Offer 身份。Offer ID 是唯一去重键。保留输入框及本次剪贴板中首次出现的有效链接及顺序，忽略之后相同 Offer ID 的链接。输入框已有该 Offer 时不再追加。
2. 重复点击粘贴不重复增加链接。部分新增时显示简洁结果（例如“已添加 8 条，过滤重复 3 条”）；粘贴中所有有效链接均已存在时不修改输入框，提示“链接已存在，无需重复添加”。剪贴板内无非空内容、读取权限错误沿用现有提示。
3. 手动编辑文本后，提交前运行同一去重规则。有效重复项只保留首次出现项；不同 Offer 的顺序不变。无效/不支持链接不参与 Offer 去重，仍进入现有错误处理，不能被当作重复项吞掉。
4. `source_line` 保留每个最终输入项在提交前文本中的原始 1 起始行号；过滤空行或后续重复项时不得把剩余项错误重编号为其他原始行。提交顺序、行号、文本必须一一对应。
5. 最终去重列表是新任务的唯一计数口径：提交按钮数量、添加进度、输入总数和 `CollectionAddInput` 总数一致。沿用 V1.3 的 100 条非空输入上限：按去重后列表校验；不得静默截断。有效链接已去重，无效行仍计入提交输入并由后端判错。
6. 不改变 `submission_id`、请求 fingerprint、pending envelope、并发受理、未知提交查询和幂等重放语义。提交前只规范此次固定输入列表；重放同一 envelope 时不得重新解析成不同内容或发起第二次导航。

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
| 状态组合 | 8 observed→success；observed/placeholder/技术状态混合按既有规则；8 placeholder→no_values；技术读取失败按既有状态；无读数→not_attempted 且零 Observation。 | API + 隔离 SQLite |
| 来源和身份校验 | 正确官方来源及目标 Offer 可保存；任一 Observation Offer/source 错误或不能安全关联时拒绝，零错配商品/Observation。 | API + Collector 注入 |
| 经营异常但基础成功 | 商品新增及 Snapshot 成功，Run 基础 `success`；Run/Item/批次汇总/UI 准确表示经营异常，首页和详情相应筛选命中。 | API + 记录查询 + React/Playwright |
| 候选保存事务失败 | 商品、SKU、Snapshot、Run、Observation、linked 状态无半成品；只发生一次页面访问；按 V1.3 收口真实失败/导航事实。 | 隔离 SQLite commit fault + spy |
| 幂等重放 | 同一 submission 重放不新增 Batch/Run/Observation、不重新访问页面；异 fingerprint 冲突规则不变。 | API + Collector spy |
| 粘贴内部/跨次重复 | 同一剪贴板重复行、再次粘贴、与输入框已有 Offer 重复、query 不同同 Offer 均只留首次项；顺序和提示准确。 | `App.test.tsx` |
| 手动输入提交 | query 不同的有效重复只提交一项；无效行仍提交并走原错误分类；source_line 对应原文本行；全部有效项已存在时不改输入、不提交重复。 | React 单测 + 添加 API |
| 数量上限 | 100 条去重后输入可提交；超过 100 不截断且按既有 422 合同拒绝；按钮、进度、批次 total 与真实提交列表一致。 | React 单测 + API |
| 已存在与提交内重复 | 新 UI 对相同 Offer 只发送一项；后端仍分别识别库内已存在和旧客户端提交内重复，后者保持 `duplicate_input` 统计/API 兼容。 | API + React |
| 历史及普通采集回归 | 历史 duplicate_input、历史 add_links not_attempted Run/Observation、既有历史筛选事实不变；普通手动/定时补采与观察序列化合同不变。 | 隔离 SQLite fixture + API |

## 7. Review 与交付门槛

本文件和必要索引状态保持 Draft / 待 ChatGPT Review。ChatGPT 从远端读取本次提交的 Spec 做独立 Spec Review；通过后才可 Freeze。Review 未通过时只按 Review 修订 Spec 并单独提交。未经 Review 不实施业务代码，不迁移数据库，不访问真实 1688。
