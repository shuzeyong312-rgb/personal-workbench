# 采集可靠性与采集记录重构 V1.2

状态：Frozen / 已冻结（2026-10-12；ChatGPT 独立 Final Spec Review PASS，P0/P1/P2 = 0/0/0；审核基线 `02e9c6a0f61b76091f993b6b0af25796b5024cc8`）。

## 问题与目标

目前 `BatchRuntime` 只在进程内保存批次进度，`CollectionRun` 只表示一个商品的一次页面采集尝试。历史表格因此无法可靠回答一次批量任务包含哪些商品、哪些商品补采过、每次访问发生了什么；也不能把时间接近的 CollectionRun 安全地归并成批次。经营字段部分成功还把真实页面占位和临时技术异常放在同一个结果中，用户无法据此判断是否值得再次访问商品。

V1.2 让大屏继续承担实时批量采集进度和控制，新增可查询的持久化批次记录及详情；把左侧“采集任务”改为“采集记录”；在同一 Batch Runner 中先完成所有商品的首次访问，再按明确的资格、次数和批次保护规则有限补采经营指标异常。已有真实字段状态、失败原因、`latest_attempt`、`latest_valid`、基础快照及经营 Observation 语义继续作为事实来源。

## 真实 SQLite 诊断

诊断日期：2026-10-12（Asia/Shanghai）。只通过 SQLite `mode=ro` 连接正式文件，并使用 SQLite Backup API 建立一致性临时副本后查询；副本在分析结束后清理。未启动应用、Scheduler、Runner 或浏览器，未访问 1688。只读副本 `integrity_check=ok`，数据库 Alembic revision 为 `20261010_13`，Observation 表存在。

最新 27 条 CollectionRun 的时间窗口为 2026-10-12 09:53:19–09:56:40（Asia/Shanghai），其经营状态数量与用户提供的截图完全相同；但数据库没有持久化 Batch ID，故这里仅称“27 条候选时间窗口”，不认定为同一批次。27 条基础商品采集均为 `success`；经营结果为 3 `success`、22 `partial`、2 `failed`。

每条 Run 的八项字段计数（按 `observed / placeholder / loading / source_unavailable / read_failed`）：

| Offer 字段 | observed | placeholder | loading | source_unavailable | read_failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 上架时间 `listing_time` | 25 | 0 | 0 | 2 | 0 |
| 月成交 `monthly_deal` | 11 | 14 | 0 | 2 | 0 |
| 月分销代发 `monthly_dropship` | 25 | 0 | 0 | 2 | 0 |
| 年成交件数 `annual_units` | 11 | 14 | 0 | 2 | 0 |
| 年成交订单数 `annual_orders` | 11 | 14 | 0 | 2 | 0 |
| 评价数 `review_count` | 3 | 22 | 0 | 2 | 0 |
| 好评率 `positive_rate` | 3 | 22 | 0 | 2 | 0 |
| 揽收率 `pickup_rate` | 11 | 14 | 0 | 2 | 0 |

27 条候选窗口中每条 Run 的五类字段数（按 `CollectionRun.id`，依次为 `observed / placeholder / loading / source_unavailable / read_failed`）：

| Run ID | 字段数 | Run ID | 字段数 | Run ID | 字段数 |
| ---: | --- | ---: | --- | ---: | --- |
| 1156 | 8/0/0/0/0 | 1157 | 8/0/0/0/0 | 1158 | 3/5/0/0/0 |
| 1159 | 2/6/0/0/0 | 1160 | 2/6/0/0/0 | 1161 | 2/6/0/0/0 |
| 1162 | 6/2/0/0/0 | 1163 | 6/2/0/0/0 | 1164 | 2/6/0/0/0 |
| 1165 | 0/0/0/8/0 | 1166 | 2/6/0/0/0 | 1167 | 0/0/0/8/0 |
| 1168 | 2/6/0/0/0 | 1169 | 2/6/0/0/0 | 1170 | 6/2/0/0/0 |
| 1171 | 2/6/0/0/0 | 1172 | 6/2/0/0/0 | 1173 | 2/6/0/0/0 |
| 1174 | 5/3/0/0/0 | 1175 | 8/0/0/0/0 | 1176 | 6/2/0/0/0 |
| 1177 | 6/2/0/0/0 | 1178 | 6/2/0/0/0 | 1179 | 2/6/0/0/0 |
| 1180 | 2/6/0/0/0 | 1181 | 2/6/0/0/0 | 1182 | 2/6/0/0/0 |

在 22 条部分成功中，评价数和好评率各有 22 个 `placeholder`；月成交、年成交件数、年成交订单数、揽收率各有 14 个 `placeholder`。对应原始页面值为 `-`，应解释为页面占位，不能当作 0 或技术故障，不补采。3 条全成功各有 8 个 observed；2 条经营失败的 8 个字段全部 `source_unavailable`，基础商品采集仍成功。

这 16 个 `source_unavailable` 字段属于两次商品访问，落在商品记录 ID 57、59（CollectionRun 1165、1167）；8 项原因均是“官方采购助手标题不存在或不唯一”。这两个商品在前一日各有一次助手读取成功但指标部分占位（各 2 项 observed、6 项 placeholder），所以当次完整来源缺失有恢复证据，适合在同次页面等待后仍未恢复时各限补采一次。27 条候选窗口的两次异常之间有一条商品成功读取，未形成连续失败；窗口内也没有 `loading` 或 `read_failed`。对整个现存 Observation 历史，状态总数为 457 `observed`、295 `placeholder`、72 `source_unavailable`，没有持久化的 `loading` / `read_failed`；72 个来源不可用状态均来自 9 次整组八字段失败，且原因为助手标题不存在或不唯一。

若 27 条窗口仅对这 2 个有来源故障证据的商品补采：默认 0 次新增访问；最多补采 1 次时估算新增 2 次商品页访问；最多补采 2 次时估算新增 4 次。若某个未来批次每个计划商品都符合资格，严格上限为 `计划商品数 × 最大补采次数`；补采不保证成功。该估算只计商品页面导航，不是网络请求总数。

## 用户场景与页面职责

1. 用户在竞品监控大屏发起立即采集，实时查看计划商品进度、页面访问数、首轮与补采进度；在大屏暂停、继续、结束任务，等待计划休息或处理验证冷却/人工验证。
2. 用户进入左侧“采集记录”，首页逐行查看真实批次，按异常类型过滤；选择批次进入详情，先看摘要，再定位需要处理的商品、字段原因和逐轮访问记录。
3. 用户看到部分经营字段是 `-` 时知道这是正常页面占位；看到官方助手来源或读取异常时能看到实际原因、尝试历史和是否已经达到补采上限。
4. 旧 CollectionRun 没有可靠批次身份，继续作为独立的“历史单次记录”展示，不依据时间窗口、商品顺序或相邻 Run 推断历史批次归属。

### 页面信息架构

- **竞品监控大屏**：批量采集唯一实时进度及控制入口，保留立即采集、暂停、继续、结束、计划休息、验证冷却及自动恢复进度。继续使用唯一 `BatchRuntime` 状态轮询；不得在采集记录页增加控制器或第二个 polling loop。
- **左侧导航**：“采集任务”更名为“采集记录”。
- **采集记录首页**：批次列表展示开始时间、触发方式、计划商品数、基础采集结果、经营结果、补采情况、访问数和终态。默认按真实 `started_at DESC, batch_id DESC` 排序，最近批次永远优先；异常筛选、醒目状态及异常数用于定位，不改变时间顺序。保留历史单次记录独立区块。
- **批次详情**：摘要区域区分计划商品数、实际页面访问次数、首次成功、补采成功、最终失败、未执行；商品明细按异常优先呈现，正常商品可折叠。每个商品可查看基础结果、八项经营字段当前最终结果、每项原因以及按时间排序的每次 CollectionRun / Observation。补采成功不得清除或覆盖前次失败记录。
- 筛选至少包括：页面占位、官方来源不可用、字段加载失败、字段读取失败、基础采集失败。可同时覆盖商品级最终状态及其任一历史 attempt，筛选不得把历史失败从详情中删除。
- 文案要分别呈现“经营部分指标可用”和“存在需要处理的技术异常”。页面占位明确提示“页面显示 -，无需补采”；来源异常展示字段级保存的具体原因。商品基础采集失败与经营字段部分可用允许同时出现。
- 沿用当前工作台 AppShell、紧凑密度和克制色彩；异常优先级由排序、摘要和状态 Badge 表达，不以大量正常商品填满首屏。

## 状态分类与计数

### 事实层

- `CollectionBatch` 表示一次持久化任务及固定计划集合。
- `CollectionBatchItem` 表示批次中一个计划商品，不因重复访问增加商品数量。
- 一条 `CollectionRun` 表示一次真实采集尝试，并在导航前创建；它可能尚未发起页面访问。每次首次采集、验证冷却后的恢复访问、经营指标补采均各自创建 CollectionRun，关联同一批次商品，具有单调递增的 `attempt_number` 和明确的 `attempt_kind = first_pass / verification_resume / operating_metrics_retry`。
- `OperatingMetricObservation` 仍是一轮、一个 Offer、一个字段的事实记录。只保存实际读取的八字段状态、值、来源、时间和原因。
- 基础商品结果、经营指标结果独立统计。基础成功且经营字段全部 `placeholder` 应显示“基础采集成功 / 经营无有效值”而不是技术故障。已有六值经营 Run 状态继续为 `not_attempted / success / partial / no_values / failed / blocked`，不增加同义枚举。

### 批次商品状态和汇总

每个批次商品具有固定计划位置、执行状态、最终基础结果、最终经营状态和一个互斥的 `final_result`：`first_pass_success / verification_resume_success / retry_success / final_failed / verification_required / not_executed`。`queued / running / completed / failed / not_executed` 是商品执行状态；其中 `failed` 只表示基础商品采集失败，`verification_required` 表示达到现有验证恢复上限后仍需人工处理且尚无其他最终结果。经营指标技术失败单独计入持久批次的 `final_failed` / `technical_exception_products`，不得改写 BatchRuntime/API 的 `failed`。终态前符合补采资格的商品保持 `running`，每次失败均保留真实 CollectionRun，不提前计入最终结果。

批次摘要必须分开提供：

- `planned_products`：批次固定计划中的不同商品数；
- `attempts_started`：已持久化创建并置为 `running` 的 CollectionRun 数，包括随后因浏览器/导航前故障而未访问页面的 Run；
- `page_visits`：已确认调用浏览器页面导航命令的次数；页面未必成功加载或被平台接收；
- `page_visits_unknown`：进程中断/持久化故障发生在导航调用与确认记录之间、无法证明命令是否已发出的次数；不伪装为已确认访问，访问预算按 `page_visits + page_visits_unknown` 保守计算；
- `verification_resume_visits`：`attempt_kind=verification_resume` 且已确认或 unknown 的导航访问；单独显示，不受 `operating_metrics_retry_max` 计数限制；
- `retry_visits`：只统计 `attempt_kind=operating_metrics_retry` 且已确认或 unknown 的导航访问，`retry_visits ≤ page_visits + page_visits_unknown`；验证恢复访问不计入；同页等待不增加计数；
- `first_pass_success`：在首次计划访问中完成，基础采集成功，且八项 Observation 中没有未解决的 `loading / source_unavailable / read_failed` 的商品数。经营指标可少于八项，真实 placeholder 不使其失败；不可补采的技术异常也不能算成功；
- `verification_resume_success`：需通过验证冷却恢复访问后才成功，且没有由经营指标补采 attempt 的新 Observation 证明技术恢复的商品数；该项不计入 `retry_success`；
- `retry_success`：本批次至少发生一次补采，且补采的本批次新 Observation 证明首轮可重试技术异常已恢复的商品数。它不是要求八项全 `observed`；
- `final_failed`：最终基础采集失败，或经营指标存在未恢复的技术异常，按商品去重计数；
- `not_executed`：批次终止时从未发起页面导航的计划商品数。

首轮技术异常仅在本批次 `operating_metrics_retry` attempt 的新 Observation 不再有相应 `loading / source_unavailable / read_failed`，且字段被真实读取为 `observed` 或真实 `placeholder` 时视为由经营补采恢复。示例：首轮助手整组不可用，补采得到 6 个 `observed`、2 个真实 `placeholder`，即技术异常恢复并计入 `retry_success`；原有 `latest_valid` 值、验证恢复访问的结果、其他批次 Observation 或旧快照不得冒充经营补采证据。保留首轮异常 Observation，不将其改写成成功。补采后仍有技术异常则持久化 `final_failed`；同时基础结果如实记录。经营字段全为真实 placeholder 且无技术失败时为成功（可显示“经营无有效值”），不触发补采。

`first_pass_success`、`verification_resume_success`、`retry_success`、`final_failed`、`verification_required` 对已执行并终结的商品互斥，且之和等于 `completed`；每个计划商品至多计入一个结果。先按终态事实分类：已知基础失败或经营技术异常仍未恢复时计 `final_failed`；否则，因验证机制停止且没有可确认的其他最终结果时计 `verification_required`；其余成功商品中，经营补采 attempt 的新 Observation 恢复了原技术异常时计 `retry_success`，否则成功依赖验证恢复访问时计 `verification_resume_success`，否则计 `first_pass_success`。因此已存在经营技术异常的商品若随后又被验证阻断，商品结果仍为 `final_failed`，验证阻断另由批次停止原因及异常明细呈现；无其他已知失败的验证阻断商品计 `verification_required`。BatchRuntime/API 的 `succeeded / failed / verification_required` 保持既有基础商品采集口径，经营指标异常不得更改它们；持久批次 `final_failed` 是独立的最终商品技术/基础失败数，不提供旧 `failed` 字段别名。`technical_exception_products` 是 `final_failed` 中仍有经营技术异常的唯一商品子集；`base_failed_products` 是其中基础失败的唯一商品子集，两者可能重叠，不相加替代 `final_failed`。例如诊断候选的 27 条基础成功、0 基础失败、2 条经营技术异常在 `operating_metrics_retry_max=0` 且无验证恢复时为 Runtime `succeeded=27, failed=0`，持久化 `first_pass_success=25, final_failed=2, technical_exception_products=2, base_failed_products=0`；如期间发生一次合法验证恢复，Runtime `succeeded/failed` 仍按基础结果计，访问数增加一次且 `verification_resume_visits=1`，不增加 `retry_visits`。Runtime 经营 counts 与 `outcome_code` 仍按原合同报告。持久化/运行状态始终满足 `completed + remaining = planned_products`。`completed` 是已有最终商品结果（含各类失败/验证终态）的商品数；活动批次 `remaining` 含 queued/running，终止后未执行项仍在 `remaining`，并且 `not_executed ≤ remaining`。访问数与商品进度完全分离。

持久批次字段分离为生命周期 `lifecycle_status = created / running / terminal` 和仅终态设置的 `outcome_code`。`outcome_code` 使用持久化合同：`success / partial_success / partial_failure / user_ended / verification_required / collect_failed / infrastructure_error / interrupted`。先按实际终止原因判定：重启恢复=`interrupted`；持久化/浏览器基础设施故障=`infrastructure_error`；验证阻断=`verification_required`；用户结束=`user_ended`。只有自然结束才按结果派生：所有计划商品均成功且无未执行项=`success`；无基础失败、但至少一件商品仍有经营技术异常=`partial_success`（即使没有成功商品）；存在基础失败且至少一件商品成功=`partial_failure`；没有任何成功商品且至少一件基础失败=`collect_failed`。成功商品数为 `first_pass_success + verification_resume_success + retry_success`。出现无法归因的未执行商品时不得伪报 success，归为 `infrastructure_error` 并保留原因。补采恢复的商品按成功处理。终止原因优先级为 `interrupted > infrastructure_error > verification_required > user_ended > result-derived`，但只适用于实际发生的终止原因。`BatchRuntime.status` 继续只表达运行状态（`idle/running/pausing/paused/stopping/stopped/resting/cooling_down/completed/verification_required`）；现有 API `outcome_code`（`success/partial_success/partial_failure/user_ended/collect_failed/verification_required/collection_in_progress`）含义不变。持久批次字段不复用 Runtime status 枚举；适配层不得重定义现有 Runtime/API 语义。持久化的 `infrastructure_error`、`interrupted` 在旧 Runtime outcome 没有对应值时不得伪造映射；旧 API 仅按其已有合同报告运行态/可表达结果。

## 补采规则

### 首轮采集与同页面等待

1. 所有计划商品先按冻结顺序进行一次首次访问。只有首轮结束后，Runner 才消费补采队列；不在首轮中途插队补采。
2. 对同次可信 Offer 页面，Collector 在官方助手目标区域或字段可见后最多额外等待 5 秒，并再次读取；若助手已就绪则立即读取，不固定等待满 5 秒。等待期间不新建 Page / 导航，不增加 CollectionRun、attempt 或访问数。每个安全检查点按现有逻辑检测验证；暂停/结束请求遵循现有安全边界，完成或安全中止当前读取后执行控制，不屏蔽验证信号。
3. 页面显示 `-` 的字段固定记 `placeholder`。真实 placeholder 不作为补采资格；指标不足 8/8 不是重试条件。

### 补采资格

初版只自动补采经营字段，不补采基础商品失败。首轮需有可信 Offer 身份、基础商品解析成功，并且字段原因命中有界 allowlist 才具备资格：数据库当前可见的助手标题缺失/不唯一（前提是有界等待后仍然缺失）、字段仍在加载。资格按一件商品合并判断，一轮补采重读同页可读的经营字段，不按每个字段分别访问。只有失败原因来自真实 Observation `reason` 或稳定错误码时才可资格判定；重复字段标签、普通解析问题等 `read_failed` 先展示/筛选，不自动重试。

以下情况不可自动补采：真实页面占位；身份或 Offer ID 不匹配；登录失效；验证弹窗/风控；访问限制；商品已确认下架；所有基础采集失败；非 allowlist 的 `read_failed`；数据库提交/事务失败；取消、结束或未执行项。数据库保存失败不应触发第二次外部访问。虽然现有 `collection_timeout` 可能是暂时的，但当前稳定错误不区分导航超时、页面内容超时和其他失败上下文；因此基础采集重试留待未来有证据支持的专项规则，不复用本设置扩大范围。

### 有限队列和停机保护

- 所有首轮商品结束后才构造补采队列；符合条件的商品按原计划顺序进入队尾，每个商品保留补采次数和 attempt 历史。一次队列项至多发起一次补采页面访问。
- 初始允许范围为 **0～2 次最大补采**，默认 **0**。每次批次创建时将该值复制为不可变批次配置快照；进行中的任务不受随后设置更改影响。
- 产品默认仍为 0；用户启用后建议默认选择 1，允许显式设置 2。该值只限制 `operating_metrics_retry`：最多 `operating_metrics_retry_max` 次/商品。它不限制也不消费现有 `auto_resume_max`。在 `N` 个计划商品、每商品最多 `r` 次经营补采时，经营补采访问预算为 `N×r`；已确认的首次访问最多 `N` 次。验证冷却恢复由现有 `auto_resume_max` 独立控制，每次合法恢复可能对当前商品再导航一次，因此全批次保守上限是 `N + N×r + auto_resume_max`，而不是按每商品扩大 `1+r` 后再加恢复次数。`page_visits_unknown` 也计入相应类别的访问预算；导航前失败不计访问。补采遵守原 item interval、连续采集数及计划休息节奏，不重置或缩短。
- 连续异常保护：连续 3 个**不同商品**的首轮 attempt 均有八字段整组 `source_unavailable` 时，立即熔断本批次新增补采。此前已排队但未开始的补采全部标记 `cancelled_circuit_breaker`，记录取消数和熔断原因；不得再发起补采访问。该熔断不停止其他商品首轮的正常页面访问、即时读取及有界同页等待，也不影响基础采集；平台验证/限制仍由既有 Runner 机制优先停止。只有后续首轮商品出现可信助手来源恢复（至少一个助手字段为 observed 或真实 placeholder，且无整组 unavailable）才将连续计数清零；同商品补采不能累计或重置连续首轮计数。批次详情展示触发原因、连续计数及被抑制商品数。
- 访问限制、验证、登录失效、Offer 不匹配、批次取消或结束始终优先于 retry queue；不得绕过现有验证冷却或人工处理状态。
- `operating_metrics_retry_max` 与 `auto_resume_max` 完全独立。前者控制经营指标额外页面访问，后者继续只控制验证冷却后的恢复次数。

### 访问量示例

在 27 商品候选窗口中，可补采候选仅 2 个助手整组来源失败商品；页面占位的 22 个商品不符合资格。若配置 0、1、2 次最大经营补采，本样本估算新增经营补采导航分别为 0、最多 2、最多 4 次；在没有验证冷却恢复的情况下，总访问分别最多为 27、29、31。若发生合法验证冷却恢复，其恢复导航另计，不属于 `retry_visits`，最多另增加 `auto_resume_max` 次/批次。因此该样本全批次保守导航预算分别为 `27 + auto_resume_max`、`29 + auto_resume_max`、`31 + auto_resume_max`；unknown 访问同样消耗对应预算。一般预算为首次访问至多 `N`、经营补采至多 `N×r`、验证恢复至多 `auto_resume_max`，总计 `N + N×r + auto_resume_max`。上述为访问预算，不是成功率承诺。

## 批次与采集记录数据模型

### 推荐的最小持久化结构

新增 `collection_batches` 与 `collection_batch_items` 两表：

- `CollectionBatch`：数据库 ID、不可变且唯一的真实 task ID（建议 UUID）、触发方式 (`manual_selected / manual_all_active / scheduled`)、创建/真实开始/结束时间、`lifecycle_status`、`outcome_code`、冻结设置、计划商品数、批次保护/安全错误摘要及定时 occurrence 幂等键。`created` 仅表示批次与计划已提交、Runner 还未确认开始。Scheduler key 包含策略窗口、按现有 due 状态生成的候选商品签名及 occurrence generation；唯一约束在同一数据库事务中阻止同一 occurrence 并发重复创建。
- `CollectionBatchItem`：batch FK、稳定 position、可空 competitor FK、执行状态、互斥 final_result、最终基础/经营状态、批次保护/停止原因及匿名统计快照：`attempts_started / page_visits / page_visits_unknown / verification_resume_visits / retry_visits`、终态结果分类和必要异常计数。每批每商品仅一行；不复制 Offer ID、店铺、标题、URL 或原始页面内容。计数由关联 Run 事务递增，商品删除时保留该匿名快照。
- `CollectionRun`：增加 nullable `collection_batch_item_id`、nullable `attempt_number`、`attempt_kind`、导航已发起时间/标志及终结来源。每次尝试在导航前创建 Run，attempt 从 1 开始递增，kind 为 `first_pass / verification_resume / operating_metrics_retry`；旧 Run 关联字段保持 NULL，不推测归批。attempt_number 对同一 item 的所有 kind 统一递增；验证恢复不会增加经营补采次数。
- `OperatingMetricObservation` 继续 FK 到单次 CollectionRun；字段原因保留在 Observation `reason` 中。失败 attempt 记录不因后续成功而修改或删除。

批次创建和固定商品计划一次事务提交后才调用唯一 Runner；Runner 确认已获锁并开始才将批次从 `created` 转为 `running`。每次真实尝试先提交独立 running CollectionRun，记录 `attempt_number` 与 `attempt_kind`；浏览器已启动后，在调用导航命令前持久化一次性 dispatch claim，随后调用浏览器导航命令并持久化“已确认调用”事件。确认事件计入总 `page_visits`；若进程在 claim 与确认记录间中断，恢复为 `page_visits_unknown`，不假定成功或未发生。导航调用报错但调用已发出仍计一次；浏览器启动失败、验证在导航前暂停、dispatch claim 提交失败不调用导航且不计访问。`retry_visits` 只对经营补采 kind 计数；验证冷却后的恢复访问只计 `verification_resume_visits`。item 匿名统计保留 `attempts_started / page_visits / page_visits_unknown / verification_resume_visits / retry_visits`；批次计数由 item 快照求和，不另存重复总数。单次访问的基础事实、Observation 和 Run 终态沿用现有原子保存事务；Run、item 计数/状态推进及 attempt 终态尽量同事务提交。保存失败不得重访；用安全独立事务记录保存失败/未知结果，幂等启动核对不得重复 Snapshot/Observation/计数。访问预算按已确认和 unknown 访问合计执行，不把导航发起宣称为页面成功加载。

不要单独新增第二个 Runner、队列服务、分布式任务系统或第二个持久化执行状态机。持久化批次是既有唯一 Runner 与历史查询的事实记录；运行中的暂停/继续/结束/冷却控制仍使用现有 `BatchRuntime`、`COLLECTION_LOCK` 和 API。

### 服务重启和批次中途结束

- 重启启动阶段只执行数据库核对，不创建/打开 Chrome，不自动续跑、不自动导航、不重开 Profile。旧进程遗留的 `created`（Runner 尚未确认开始）或 `running` 批次均转 `terminal/interrupted`；旧批次不自动重放。Scheduler 随后按照原有 fixed_daily/rolling_24h 与 catch_up/skip 配置决定是否创建**新** occurrence/batch；新批次不是恢复旧批次，也不修改用户配置。
- 幂等核对规则：批次 `created` 表示计划已提交但 Runner 未确认启动，重启后中断，商品均未执行；Run `running` 且无 dispatch claim 则计一次 `attempts_started`、零访问，以 `interrupted_before_navigation` 收口；有 claim 且无确认事件则计入 `page_visits_unknown` 并以 `interrupted_navigation_unknown` 收口；已确认导航事件保留一次 `page_visits`，以 `interrupted_after_navigation` 收口，不补造成功 Observation/Snapshot；Run 已终态但 item 未更新时，只根据唯一 Run/attempt 关联补齐 item 与匿名计数快照，使用唯一约束/幂等更新防止二次累计。若 Run/item 状态提交原子性无法证明，保留安全错误并终止，不重访。
- 终态已写入但 batch outcome/汇总未完成时，依据持久化 item/Run 事实重建一次；终态批次不得被恢复成活动态。
- 用户“结束”表示当前商品按既有 runner 规则完成其可安全提交的事务后停止，不再启动剩余初次访问或补采；未完成计划数和排队 retry 不应冒充失败访问。
- 暂停发生在页面访问/事务中时沿用既有安全边界：当前 CollectionRun 得到一致终态后关闭/停放浏览器并进入 paused；补采队列和已发生 attempt 保留，继续时不重新运行已经终态的 attempt。冷却与 auto-resume 完全继续沿用 V1 状态机。

## API 合同和兼容

以下是建议新增/扩展合同，实际实现遵循现有 FastAPI Pydantic schema 和统一错误 envelope。

- 保持 `POST /api/competitors/collect-batch`、`GET /api/competitors/collect-batch/status`、`POST .../pause|resume|end` 的路径及现有状态控制语义。新 POST/status 增加 `batch_id`、`task_id`、`lifecycle_status`、终态持久化 `batch_outcome_code`、当前首轮/验证恢复/经营补采阶段、`attempts_started/page_visits/page_visits_unknown/verification_resume_visits/retry_visits`、重试进度和固定商品摘要。Runtime `succeeded / failed / verification_required` 与 `outcome_code` 原样保留；新增持久化统计不得回写或重解释旧字段。既有 `total` 始终是不同计划商品数，`items` 仍每商品一项；`completed + remaining = total`，访问/尝试数不推动商品进度。
- 现有 `GET /api/collection-runs` 默认过滤行为与字段兼容。新增 nullable `collection_batch_item_id`、`attempt_number`、`attempt_kind` 和 batch task ID 展示字段；既有旧客户端忽略新增字段应可用。增加 `batch_id` 查询过滤及异常类型过滤；只有显式 `unbatched=true` 才筛选没有持久批次关联的记录。
- 新增只读 `GET /api/collection-batches`，以分页/筛选返回批次摘要，支持时间、触发方式、终态和异常类别。默认 `started_at DESC, batch_id DESC`；异常筛选仅过滤结果，不改变排序。
- 新增只读 `GET /api/collection-batches/{batch_id}`，返回批次快照和商品列表；attempt 历史含关联 CollectionRun、两路 Run 状态、八项 Observation 状态/原值/安全原因/时间。分页策略按现有数据量最小实现；不得 N+1 查询商品、Run 或 Observation。
- 批次列表摘要包含 `batch_id / task_id / trigger / lifecycle_status / batch_outcome_code / started_at / finished_at / planned_products / completed / remaining / attempts_started / page_visits / page_visits_unknown / verification_resume_visits / retry_visits / first_pass_success / verification_resume_success / retry_success / final_failed / verification_required / technical_exception_products / base_failed_products / not_executed / retry_max / exception_types` 及分页信息。详情每个商品包含 `position / competitor_id / execution_status / final_result / base_status / operating_metrics_status / attempts / deletion_notice`；每个 attempt 包含 Run ID、attempt number/kind、导航事件时间、终态、错误码/安全消息及 fields。fields 只对应真实 Observation；没有 Observation 返回空数组。商品已删除时 competitor_id 为 NULL，详情显示“商品已删除，字段明细已随商品删除”，不得伪造 Observation；匿名计数快照仍返回。
- 触发类型由创建批次的路径明确定义，不按 Run 时间、调用栈、商品顺序或 `CollectionRun` 现有字段推断。
- 请求参数校验错误维持 4xx 和既有 error code 格式；未知批次返回稳定 404。权限、鉴权沿用当前本地工作台 API，不新建用户角色或外部服务。
- Scheduler occurrence key 不将每日或 24h 窗口粗略视为永远只允许一个批次；它必须兼顾窗口与实际 due 商品集合。与现有 `_due_ids` 一致，`rolling_24h` 按每个 active 商品独立判定：无 CollectionRun，或 `now - latest CollectionRun.started_at ≥ 24h` 即 due；签名包含该商品及其最近 Run 身份/到期锚点，因此不同商品在不同时刻到期可分别创建新批次。`fixed_daily` 的窗口是 configured local date + configured time 得出的 boundary；商品无 Run 或 latest Run.started_at 早于该 boundary 即 due。一个日期内新增/重新 active 且无 Run 的商品会改变 due 集合签名，可生成该窗口的新批次；若其最近 Run 已在 boundary 后，则仍按 `_due_ids` 判为非 due。
- 为候选 due 集合生成确定性 occurrence key：`strategy + policy window/boundary + sorted due-set signature + generation`。due-set signature 基于 `_due_ids` 返回的商品及各自最新 Run ID/started_at（无 Run 使用固定空标记），不以时间相近的 Run 推测批次；generation 对同一候选 key 首次为 1，仅在此前同 key 批次已终态、后续一次合法 poll 仍得到相同 due-set signature 时递增。相同 key 由数据库唯一约束串行化；并发调用中成功插入者是唯一创建者，其他调用读取该 batch 并退出，不再启动 Runner。occurrence 记录与 Batch/Item 必须同事务提交；唯一键冲突回滚候选写入后读取胜出记录。若任意 scheduled 批次仍为 `created/running`，新的 Scheduler poll 不得因运行中 Run 改变 due-set 签名而插入另一批次；等待该批次终态后重新按 `_due_ids` 求值，新近到期/新增商品届时可组成下一 occurrence。generation 不得在同一批次仍 `created/running` 时递增，也不得用当前毫秒时间生成新 key。`rolling_24h` 的 policy window 是策略标识，不是固定的日历 24 小时分桶；各商品到期锚点与 due-set signature 决定不同时刻的新 due occurrence。`fixed_daily` 使用 configured local date 与 configured time 算出的 boundary。
- 服务启动先把旧 `created/running` 批次收口为 interrupted，随后 Scheduler 只按原 `_due_ids` 与现有 catch_up/skip 决策创建新 Batch/task ID；这不是恢复旧批次。崩溃后尚未创建 CollectionRun 的 due 商品仍按现有 `_due_ids` 在下一次合法 poll 处理；如果同一候选 due 集合先前批次已 interrupted，则通过终态后的 generation 创建新 occurrence。已在导航前创建 Run 的商品继续遵守当前 `_due_ids`：rolling_24h 等到该 Run 满 24h；fixed_daily 按其时间与当前/下一 boundary 关系重新判断。不得为“未访问”另造 due 判据，也不得把新批次称作旧批次恢复。固定日期 skip/catch_up 的既有生命周期门槛不变；rolling_24h 不新增 missed-policy 分支。不同时间真正进入 due 集合的新商品允许产生新 occurrence；锁失败、同次 Scheduler 并发或重启重复提交同一个候选 key 时不得重复创建。调度关闭、未到固定时间或无 due ID 时不创建批次，不修改用户配置。

## 设置

- 在现有竞品监控设置中新增 `operating_metrics_retry_max`（或最终确定的等义 snake_case 字段）：最大经营指标补采次数，合法范围 0～2，默认 0。设置 0 保证无新增经营指标补采访问；不关闭、扣减或改变 `auto_resume_max` 允许的验证恢复访问。
- 当前 `auto_resume_max` 仍为 0～5 并与新值独立校验、存储、展示、快照。更新现有完整设置 PUT contract 时必须同步更新所有现有调用方和测试 fixture；不接受超界值、bool、字符串或局部非法配置。
- 设置界面说明“首次采集不计入经营补采次数；补采 1 次代表最多增加 1 次经营补采访问；验证冷却恢复访问单独计算”。显示按批次生效，修改不改变运行中批次的冻结配置。
- 默认 0 避免升级后自动增加 1688 访问；只有用户显式改为 1 或 2 才会产生增量。

## 单商品、手动批次与 Scheduler 边界

- **手动批次**：大屏立即采集入口继续使用唯一现有 POST/Batch Runner。选中集合在创建时固定；触发方式记录为 `manual_selected` 或 `manual_all_active`。暂停、继续、结束操作仍从大屏进入。
- **定时采集**：沿用现有 `_due_ids`、`rolling_24h / fixed_daily`、catch-up/skip、互斥和配置快照；相同 due-set occurrence 由唯一键去重并交给同一个 Batch Runner。不同时间形成的新 due 商品集合允许新批次。获取锁失败不创建可执行批次；重启后的新触发遵守现有 missed policy，不恢复旧批次。调度关闭、未到固定时间或无 due ID 时不建批次，不修改用户设置。
- **单商品立即采集**：现有单商品 API/详情操作保持独立，无 `CollectionBatch`；每次真实访问仍保留独立 CollectionRun 及 Observation，不运行补采逻辑，`batch_id` 为空。其 CollectionRun 可进入历史单次记录。
- “历史单次记录”仅展示可靠证实为 unbatched 的记录。升级前 run 一律保留为 unbatched；V1.2 新创建、由现有 Runner 正式启动的批次页访问可由 nullable item FK 直接判别。

## Scheduler、验证与节奏兼容

- `COLLECTION_LOCK` 仍是单商品、手动批次、定时批次之间的互斥边界。Runner 仍串行使用 headed Browser/Context；不并发访问，不增加 browser profile，不绕过平台验证。
- Scheduler 启动时的批次恢复只读写数据库状态；任何 Chrome/Profile 启动必须来自新的、去重后的合法调度 occurrence 或用户操作。occurrence 幂等键不改变现有 fixed_daily/rolling_24h、catch_up/skip 选择结果。
- 每次真实页面访问（首次、验证恢复、经营指标补采）都执行现有验证检测与人工处理。验证触发必须停止开始新的访问/补采，保留当前页及 Runner 现有可见性、关闭 Browser、冷却倒计时、恢复次数和人工处理行为；冷却后的恢复访问单独留 attempt，不消耗经营补采次数。
- 现有 item interval、连续采集次数、计划休息、暂停/继续/结束都要覆盖补采访问。页面读取等待只在当前一次访问内进行，不构成访问间隔或重试次数。
- 设置修改只作用于后续批次；运行批次继续使用它开始时的 interval、rest、cooldown、auto-resume 和 metrics retry 快照。新 metrics retry 设置不能消费、重置或扩大 verification `auto_resume_max`。

## 删除、历史引用与迁移约束

- 仅新增 Alembic 迁移，不执行正式迁移；实现阶段另行按仓库 SQLite/Alembic 安全门槛进行预检和隔离验证。
- 迁移新增批次和商品关系表、必要 FK/check/索引；`CollectionRun` 新增 nullable 批次商品 FK/attempt 序号。不得为旧 CollectionRun 回填批次，也不得从密集的同日 runs 构造旧批次或 `CollectionBatchItem`。
- 保留现有 `latest_attempt`（Observation 最近真实尝试）、`latest_valid`（只从 observed 且非空 raw value 选取）、基础 Snapshot 和 Observation 规则；`placeholder/loading/source_unavailable/read_failed` 均不覆盖最新有效值。
- 沿用现有单事务显式删除路径及 NO ACTION 原则，不改成不受控级联。获准保留去身份化 item 汇总：在既有原子删除事务中先保存/确认该 item 的 attempt、page/retry/verification-resume/unknown visit、最终结果和必要异常分类快照，再将 competitor FK 置空，并按现有顺序删除 ChangeEvent、Observation、CollectionRun、Snapshot 和商品。快照不得包含可反推出商品身份的信息（Offer ID、店铺、标题、URL、原始页面内容）。批次所有计数只依赖 item 匿名快照/关联现存 item，不依赖已删除的 Run 行，因此删除前后计划数、访问/尝试数、执行结果和异常统计一致。字段明细没有了就明确显示已随商品删除，禁止生成合成 Observation。
- 删除及批量删除必须一次事务处理；任一 FK/提交步骤失败整体回滚。存在 `created/running` 批次商品计划时，删除与批次创建/Runner 启动共享事务或互斥检查，返回现有 409 语义，避免已提交计划在取得 Runner 锁前被删除；采集运行中沿用现有互斥/409 保护。item 终结后不得阻止商品永久删除。
- 新增约束/索引包括 `(batch_id, position)` 唯一、`(batch_item_id, attempt_number)` 唯一、非空 Scheduler occurrence key 唯一、导航标记单次写入约束，以及批次 lifecycle/outcome/trigger 合法值和分页排序索引。具体迁移不得暗中重建/修复既有无关 Schema；旧 Run 外键仍 nullable。发现正式库 schema drift 必须遵循独立安全门槛停止。

## 测试方案

测试覆盖用户可见契约与持久化结果，复用现有 `BatchRuntime`、collector/service、`COLLECTION_LOCK`、temp SQLite、FastAPI TestClient、settings contract、`CollectionTasks.test.tsx` 及 fail-closed API mock。不要另造 runner 或测试框架，不访问正式业务库、1688、用户 Browser Profile 或真实 Scheduler。

### Backend / 数据库

1. 批次创建一次性原子写入任务 ID、触发方式、设置快照和不重复商品集合；校验拒绝时无 Batch/Item/CollectionRun；创建成功但 Runner 尚未确认启动即模拟崩溃时，启动核对将其幂等终结为 interrupted 且商品未执行。
2. 单 Runner/锁保护跨手动、scheduled 与单商品；批次每商品仅一行，多个真实页面访问对应多个 CollectionRun，attempt 编号递增，商品计数不增加。
3. 同一页面的 bounded wait 能最终读到助手数据则只有一条 CollectionRun；wait 超时后只有符合资格的 item 入尾队列。
4. 先全部完成首次访问后才开始经营补采；placeholder 不补；达到 0/1/2 补采上限后停止。`retry_max=0` 时发生一次符合现有规则的验证冷却恢复，应保留独立 attempt、计入 `verification_resume_visits` 和总导航数，但 `retry_visits=0`；它不受经营补采开关关闭。验证恢复期间暂停/结束仍遵守现有控制边界。预算按首次访问 `N`、经营补采 `N×r`、验证恢复 `auto_resume_max` 分开核对；rest/interval 对补采访问生效；同页等待最多 5 秒、就绪立即读取且不增加访问计数。
5. 补采后 6 observed + 2 个真实 placeholder 能将首轮来源异常判为已恢复并计一次 retry_success；仅本批次经营补采 attempt 的新 Observation 可作恢复证据；首轮失败历史保留。27 个商品基础结果全部成功、0 个基础失败但 2 个商品最终存在经营技术异常时，Runtime 仍为 `succeeded=27, failed=0`，持久化经营统计为 `final_failed=2, technical_exception_products=2, base_failed_products=0`，并与商品级互斥结果及 completed/remaining/not_executed 不变量一致。
6. 登录失效、验证、访问限制、Offer 不符、已确认下架、数据库事务错误不盲目补采；验证冷却/自动恢复次数独立且行为与既有测试一致。
7. 三个连续不同商品的首轮助手整组 unavailable 后熔断新增补采，取消未执行队列并记录原因/数量；同商品补采不影响连续计数；后续首轮真实来源恢复才重置；其余首轮等待/验证检测行为不变。
8. 分别覆盖导航前浏览器失败、导航调用发起后失败、验证暂停、访问保存失败、进程中断；attempts_started/page_visits/page_visits_unknown/retry_visits 按事件规则计数，同页等待不创建 Run。
9. 重启仅做 DB 核对，活动/未启动批次标 interrupted、不自动续跑；Run running 且无 dispatch claim 为 0 次访问，有 claim 无确认事件计一次 unknown，确认事件保留一次 page visit；Run 已终态而 item 未更新时幂等补齐；不得重复计数或重访。
10. Scheduler 合同依照现有 `_due_ids`：rolling_24h 中两个商品可在不同时间各自到期并形成各自合法 due occurrence；fixed_daily 在 boundary 后新增或恢复 active、且无 Run 的商品可加入该日期 due 集合，但 boundary 后已有 Run 的商品仍按 `_due_ids` 不 due。相同候选集合下 Scheduler 并发启动或进程重启不得重复创建/启动同一 occurrence；任一 scheduled 批次仍活动时，不因其运行使 due-set 签名变化而再插入批次。Batch 创建提交前崩溃可由下次合法 poll 重新尝试创建，创建已提交但 Runner 未启动的批次先标 `interrupted`，其尚未访问且仍被 `_due_ids` 判为 due 的商品只能通过下一次新 occurrence 处理。catch_up/skip 原规则不变，不恢复旧批次。
11. 用户暂停时当前安全事务完成后不丢队列；补采暂停后恢复不重访终态 attempt；结束不访问剩余/排队补采商品。
12. CollectionRun / Observation / BatchItem 联合事务提交失败无半写入；已存在 Run 以稳定错误状态收口；批次统计可重建且不假成功；Run/item 更新错序可幂等修复。
13. 事务性单个/批量删除遵守明确顺序；汇总删除前后相同、item 去身份化、attempt FK 不悬空、字段明细显示随商品删除；采集中走互斥/409；任一步失败完全 rollback。
14. 迁移旧数据后全部旧 run 的 batch 关联仍 NULL，旧 Observation/Snapshot/latest valid 一致；migration downgrade 与现有约束可验证。

### API / 前端 / 浏览器

1. 旧批量 start/status/pause/resume/end 与旧 CollectionRun 客户端合同兼容；settings 新旧字段范围严格校验。
2. 首页批次分页/触发/状态/异常过滤准确；旧无批次数据出现在“历史单次记录”，不显示虚构批次；按 batch detail 返回 attempt 与字段原因，无 N+1。
3. Dashboard 仍是唯一实时控制入口且 counters 分离产品数/访问数；页面 refresh 消费 authoritative status，不生成第二个 polling loop。
4. 采集记录列表按真实批次开始时间倒序；筛选页面占位/来源不可用/loading/read failed/基础失败不改变顺序；detail 可异常优先呈现商品，但保留原计划位置和 attempt 时间，placeholder 显示无需补采。
5. 删除后批次展示去身份化 item 和稳定汇总；无 Offer、店铺或历史页面内容泄漏。
6. Frontend 使用既有组件和 fail-closed `/api/**` Playwright mock 验证首页 → 筛选 → 批次详情 → attempt 展开；不向真实数据库或平台请求。

## 最终用户验收标准

- 立即采集仍能在大屏看到唯一、可信的实时进度，并执行暂停、继续、结束；重启后明确显示中断且不会自动重放。
- 一次实际批次在采集记录中仅出现一条批次；商品数不受补采访问数影响。
- 用户能区分页面占位和技术异常；`-` 不触发重试，异常详情显示每一轮访问的字段状态与原因。
- 补采有默认关闭的独立设置、可见次数限制、队列尾执行、明确访问预算；验证、身份和数据提交安全优先。
- 所有旧 run 都留在单次历史区，没有按时间臆造的批次；Observation、基础快照与 latest-valid 可信性不被破坏。
- 删除商品仍能完成；批次历史保留去身份化汇总，不留下 dangling FK 或意外保留商品敏感资料。
- 自动检查使用隔离数据通过，ChatGPT Spec Review 通过后才冻结；真实采集 QA 属于后续 Implement/人工验收，不由本轮诊断替代。

## 非目标与已知风险

- 本轮不实现代码、迁移、API、真实采集、用户 Browser Profile 或 Scheduler 启动；不修改其他 Frozen Spec。
- 不通过时间、排序、Offer 相邻位置或状态相似归并历史 CollectionRun。
- 不新增第二个 Runner、并发采集、分布式队列、Redis/Celery、WebSocket/SSE、自动验证/验证码绕过、无限重试或“保证 8/8”。
- 不因单个 `-`、缺少 8/8 指标、成功基础采集或确认下架自动补采。
- 本地诊断只反映现存 SQLite 行。来源不可用原因现存数据明确到“助手标题不存在或不唯一”，不能进一步断定是助手未加载、页面 DOM 改版或平台行为；需要真实页面 POC 才能细分，后续 QA 不得只靠数据库日志声称解决。
- 5 秒同页等待、连续 3 商品来源保护阈值、发生导航命令即计访问，以及删除商品时保留去身份化 item 汇总为本版明确规则；如 Review 需调整，应在 Spec Review 阶段修改本文件，不能在 Implement 时静默改规则。
- 基础采集重试不包含在 V1.2 经营指标设置内；若后续要覆盖，需要再定义可验证的瞬态错误码和独立访问预算。

## 与现有实现的接口检查

- 唯一运行路径是 `run_batch_collection`、`BatchRuntime`、`COLLECTION_LOCK`，手动批次 API 继续调用现有 start/pause/resume/end seam。
- Collector 当前在单次导航后立即解析助手顶部区域；字段 Observation 已含 `reason`，适合插入有限同页等待并保留每次读取证据。
- `CollectionRun` 保持“一次采集尝试”语义；`OperatingMetricObservation` 保持“一次访问一个字段”语义；独立 CollectionRun History endpoint 与现有 `_delete_competitor_history` 是读历史及删除路径。
- 定时入口是 `prepare_auto_batch`/现有 scheduler lifecycle，应调用同一个持久化 Batch Runner，而非继续扩建第二条 runner loop。
- 现有竞品监控 Settings PUT 要完整提交所有字段，新增 retry 设置需要同步 Settings 页面/API、BatchConfig 快照、现有设置测试和所有请求 fixture。
- 当前采集任务页面已经消费唯一 status polling 和 `GET /api/collection-runs`；V1.2 需将实时卡片/按钮职责留在 Dashboard，将历史区域改由批次列表/详情 API 驱动，并保留 unbatched legacy 访问。
- 直接相关的既有回归覆盖：`backend/tests/test_batch_collection.py`、`test_collection_api.py`、`test_collection_runs.py`、`test_operating_metrics.py`、`test_operating_metrics_migration.py`、Scheduler/daily tests、`frontend/src/CollectionTasks.test.tsx`、settings tests、已有 fail-closed E2E mock。实现阶段补充新持久化表/API/重试/崩溃恢复用例；无需复制现有 Runtime 全部状态机。

## Spec Review 后的流程

1. 本轮完成只读诊断与本文档自检。
2. Freeze Commit 仅包含本 Spec 与必要的状态索引；不向 Issue Tracker 发布，不加 triage label。
3. ChatGPT 从 GitHub 读取最新提交，独立 Final Spec Review 业务规则、删除策略、迁移风险、接口兼容和边界测试；本 Spec 已于 2026-10-12 通过（P0/P1/P2 = 0/0/0）。
4. Spec 冻结后进入 Implement 阶段，严格遵循冻结合同。
