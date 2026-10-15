# 采集来源统一与记录筛选简化 V1.3

状态：**Draft / 待 ChatGPT Review**。日期：2026-10-15。不得据此进入 Implement 或自行 Freeze。

集中修订依据：ChatGPT 对 `178a58cc08b969f925b872b7d20e760658ef096e` 的 Final Spec Review（P0=0、P1=3、P2=1）；本次处理业务拒绝统计、添加 Runtime、并发受理和 unknown 查询兼容，等待再次独立 Review。

调查基线：`c967005ba39bae926fa27f93ab40fdb890f73557`。V1.2 已交付及正式数据库 revision `20261012_14` 由本轮任务给定；仓库 ORM / 迁移链与其一致，本轮未连接正式数据库核验。下文“现状”是静态代码证据，“合同”是待 Review 的 V1.3 设计，不宣称已经实现。

## 1. Problem Statement 与范围

一次用户操作目前不一定对应可查任务：手动批量和定时有 Batch，添加成功和单商品立即采集却产生无批次 Run；添加失败甚至没有商品或 Run。用户必须理解内部记录类型才能找历史，多链接的部分失败也无法作为一次提交追溯。

V1.3 将手动采集、定时采集、添加链接统一显示为真实 CollectionBatch；首页只查任务，不猜测历史归属。必要增量是任务归档、添加提交的可靠持久化与四项筛选，不重做采集体系。继承 V1.2 的真实访问证据、经营字段、删除、互斥和 Scheduler 合同；本文件明确覆盖的首页/新增入口规则优先于 V1.2 UI 增量，其他规则保持。

本轮仅修改本 Spec 和必要索引，不写业务代码/测试/迁移，不运行应用、Scheduler、1688、Chrome Profile，不修改正式数据库或设置，不发布 Issue Tracker。本轮按 to-spec 的需求整理、仓库调查、测试边界结构工作，用户已明确排除发布步骤；测试边界直接供 ChatGPT Review，不另设访谈门槛。采用 ponytail 的最小完整变更原则。

## 2. 仓库调查与实际入口

### 2.1 调用链证据

| 入口 / 当前调用链 | Batch / Item | Run / Observation | 互斥 / 页面访问 / unbatched |
| --- | --- | --- | --- |
| 大屏立即采集：App 的批量提交 → POST `/api/competitors/collect-batch`（all_active）→ reserve → create_collection_batch → start_batch_task → run_batch_collection → collect_competitor | 非空计划创建 Batch 和不同商品 Item；空计划现状直接返回成功，无持久 Batch | 每轮真实 Run；实际经营读取写 Observation | acquire_collection_slot + COLLECTION_LOCK + Runtime reservation；首轮、验证恢复、合法经营补采可多次访问；正常路径不产生 unbatched |
| 竞品列表选中采集：同一批量提交函数 selected 模式 | 同上；非法/不存在/停用 ID 在受理前拒绝 | 同上 | 同上；当前 UI 入口受我方商品管理合同收敛，保留 selected API/共享提交路径，不为本版恢复已移除按钮 |
| 单商品立即采集：POST `/api/competitors/{id}/collect` → collect_competitor | 无 | 导航前创建 Run；实际读取写 Observation；基础失败保留真实 Run | 共享互斥；一次调用不进入批量补采循环；Run 无 Item 归属。当前 App 无独立调用该 POST 的 handler，API 本身确实存在，兼容它而不新增 UI |
| Scheduler：main lifecycle → prepare_auto_batch → _due_ids → reserve / occurrence key → create_collection_batch → 同一 start_batch_task / Runner | 有 | 同批量 | 同一互斥；按原验证恢复/经营补采可多次访问；不应产生 unbatched |
| 添加单/多链接：App parseCompetitorUrls → addCompetitorsSequentially → 每链接 POST `/api/competitors` → collect_product → collect_1688_product → 最终身份/归组校验及保存 | 无 | 仅成功保存后创建独立 success Run，started_at / finished_at 都取保存时 now；未保存 Observation | 每条各自 acquire_collection_slot；一次提交无总 reservation，条目间可能被其他任务占用；同一有效链接一次导航，但用户超时重交可能再访；成功 Run 全部 unbatched |
| 我方商品自动识别与添加：同一 POST，identify_ownership 读取真实店铺与最终事务中的我方店铺设置 | 无额外入口 | 同上；ProductSnapshot / SkuSnapshot 与商品同事务 | 店铺未知拒绝；self 绑定组时检查已有 own；不是另一次采集 |
| 添加失败/重复/中断：URL、设置、组和已存在预检；采集后再次校验；最终保存事务 | 无 | 预检、页面、店铺或保存失败通常无 Run/Observation；进程中断不能从现存数据还原访问次数 | 预检可零访问；店铺/组冲突可能发生在一次访问后；客户端循环捕获失败后继续，刷新可能令后续链接从未提交 |

重要现状：parseCompetitorUrls 已在客户端去重，因此当前 API 不可能知道原始重复输入；V1.3 必须在提交时保留非空行顺序和重复行，不能只改后端归档。空行不计链接输入，行号可保留供定位。

### 2.2 已核对模块与测试边界

证据定位以函数为准：`backend/app/competitors.py` 的 collect_batch、create_competitor、collect_competitor_now、_delete_competitor_history；`collection/service.py` 的 acquire_collection_slot、collect_product、collect_competitor、create_collection_batch、run_batch_collection、recover_interrupted_batches；`collection/collector_1688.py` 已有导航 claim/confirmed callbacks；`collection/daily.py`、`main.py`；`models.py`、`collection_batches.py`、`collection_runs.py`、`collection/batch_records.py`；`frontend/src/App.tsx` 的添加和 CollectionTasksPage。

现有 Run.competitor_id 非空；Item.competitor_id 已可 NULL，但 get_batch 把所有 NULL 解释为“商品已删除”，不能直接拿 NULL 代表未创建商品。Batch trigger CHECK 只有 manual_selected/manual_all_active/scheduled。现有汇总按 Item 统计，不能把五条输入直接当五件商品。collect_product 不传导航 callbacks，添加成功的旧 Run 也无导航证据，因此不能追补旧访问数或耗时。

已阅读相关测试：test_own_product_management（添加失败无历史、最终事务重读身份/组、并发锁）、test_collection_api（同步响应、快照、失败回滚）、test_batch_collection（导航、补采、恢复）、test_collection_records_ui（查询/匿名摘要）、test_collection_batches_migration（隔离 SQLite round-trip）、test_scheduler / test_daily_collection、CollectionTasks.test.tsx、collection-tasks.spec.ts。它们是实现时增量修改的 seam，不是本轮已运行的验证结果。

## 3. Solution 与 User Stories

唯一推荐：继续以 CollectionBatch 为任务事实来源；添加输入作为 Batch 的附属事实，单商品同步调用作为共享采集服务的一商品执行，不新增独立 Runner、队列服务或任务状态机。

1. 作为用户，我希望三种触发方式各在首页出现一条真实任务，以便按一次操作追溯。
2. 作为用户，我希望单链接和多链接提交采用同一流程，以便不用判断记录类型。
3. 作为用户，我希望五个输入的每个结果都可定位，以便区分新增、已存在和无效链接。
4. 作为用户，我希望页面访问数只来自导航证据，以便零访问拒绝不会被算成采集。
5. 作为用户，我希望超时/刷新后能找到同一任务，以便不会重交并重复访问。
6. 作为用户，我希望已经添加成功的商品保留，以便后续失败不会撤销前面的成功。
7. 作为用户，我希望我方身份、组冲突和验证仍按原规则处理，以便任务归档不会改变业务安全边界。
8. 作为用户，我希望单商品入口仍返回原有结果，以便现有客户端继续工作。
9. 作为用户，我希望四个筛选自动查询并拒绝过期响应，以便看到所选条件对应的数据。
10. 作为用户，我希望旧 Run 仍可在商品历史/API 查询，以便首页简化不丢失事实。
11. 作为用户，我希望删除商品后保留匿名结果，以便历史统计稳定且身份不泄漏。
12. 作为维护者，我希望崩溃后只收口不重放，以便不能证明的访问保持 unknown。

## 4. 三类触发与执行边界

| UI 触发方式 | 内部 trigger_kind | 执行合同 |
| --- | --- | --- |
| 手动采集 | manual_selected / manual_all_active / 新增 manual_single | 批量继续现有 Runner；单商品使用下述同步共享执行路径 |
| 定时采集 | scheduled | due、occurrence、catch_up/skip、配置快照不变 |
| 添加链接 | 新增 add_links | 服务端接收一次完整输入，由现有串行 Runner 的添加模式逐条执行原添加采集/保存操作，不把新增商品 ID 再送回首轮采集 |

空手动 all_active 没有实际商品工作，仍不创建假任务，UI 明确“暂无可采集商品”；受理前的 404/409/请求体错误不是采集任务。添加有所不同：非空有效请求体中的无效 URL 也是本次业务输入，全部无效仍必须生成任务及结果。Scheduler 无 due 集合不创建任务。

添加模式复用现有 worker、单一 Runtime reservation、互斥、Context/Profile、串行节奏、安全检查点、暂停/结束与浏览器清理。仅增加在同一循环选择“已有商品采集”或“添加并保存”执行操作；候选不得使用虚构 competitor_id，Runtime 在添加时以输入位置表示当前项，current_competitor_id 可为 NULL，并新增 current_input_position / work_kind；旧基础商品 succeeded/failed 字段不偷换成输入数。Dashboard 添加模式显示独立的输入进度，持久详情仍是历史查询，不增加第二轮询。调用已有 status 请求路径；弹窗关闭不会终止任务。

### 4.1 添加 Runtime 与响应兼容合同（P1-2）

扩展既有 BatchRuntime 的预约协议为两种明确工作类型：原 reserve(competitor_ids, config) 默认 work_kind=collect_products，行为不变；添加预约使用同一 Runtime 的 add_links 分支，接收 submission_id、不可变有序输入位置及 config，绝不调用 reserve([]) 假装预约成功，也不把输入位置/Offer ID 填入 competitor_ids。两种分支在同一 Runtime 锁内检查并设置 runner_active、递增同一 reservation token、初始化同一 stop_event/resume_event；acquire_collection_slot/COLLECTION_LOCK 及 token 校验仍是唯一采集互斥。输入位置只是工作索引，不是商品 ID；持久化后绑定同一 Batch/输入行 ID，候选数由受理事务确定。

BatchStatusResponse 保留所有现有必填字段及枚举；仅增加 work_kind（缺省 collect_products）、current_input_position（可 NULL）、input_progress（非添加为 NULL，添加为下表对象），旧请求 fixture 可省略这些新增字段。现有 phase 在添加为 NULL，不扩张旧 phase 枚举。添加时 current_competitor_id/title 为 NULL，旧 items 商品数组为空；旧 total/completed/remaining/succeeded/failed/verification_required、经营字段商品计数均为 0，表示“商品采集进度不适用”，不能填输入数、候选拒绝或添加失败。它们在 collect_products 模式保持 V1.2 含义与等式。添加访问数/真实 Run 数仍使用既有 page_visits/unknown/attempts_started，含义不变。

| input_progress 字段 | 精确定义 |
| --- | --- |
| total | 原始非空输入数 N，预约即已知；1～100，整个任务不变 |
| candidate_total | 预检完成前 NULL，事务提交后为固定 planned_products，可为 0 |
| added / business_rejected / technical_failed / verification_required / interrupted / not_executed | 与第 6 节同名互斥输入计数，不是商品计数；仅由已提交输入事实更新 |
| processed | added + business_rejected + technical_failed + verification_required + interrupted；已处理并有结论（含中断未知）的输入数，不含未执行 |
| pending | result_code 尚为 NULL 的输入数，包括正在处理的一个输入 |
| remaining | total - processed = pending + not_executed；终态可能大于 0，必须显示为“未执行”，不能伪称仍在排队 |

预约初始 input_progress.total=N、pending=remaining=N，其余为 0；预检提交后一次绑定持久拒绝/候选计数，再由既有 worker 串行执行候选。输入结果提交后才更新 Runtime；事务失败不提前加成功，缓存可从输入行重建。current_input_position 使用与详情一致的零起 position，UI 显示第 position+1 条/原 source_line；预检、休息、暂停、终态无当前输入时为 NULL。候选 Item 的 completed/remaining 由第 6 节另算，不与 input_progress.processed 混用。预检全部拒绝时仍有一次真实添加预约和完整 N 条结果，立即完成收口、释放 reservation，不启动浏览器。

添加分支的循环终止、has_failures/结果派生和零工作判断必须读取 input_progress/真实输入结果，不得沿用 total==0 的商品空批次快捷成功，或因旧 failed==0 把添加失败报为 success。旧商品 record(BatchItemResult) 不用于添加拒绝/技术失败；添加结果走同一 Runtime 内的输入事实更新，最终调用既有 finish/资源释放机制，终态 counts 保留到下一次预约。

沿用同一 pause/resume/end API、事件与安全点：暂停请求使状态 pausing，当前短事务/页面处理安全结束后 paused；未开始的候选不访问。继续只消费尚未执行输入，不重访已终态输入；暂停时保留工作索引和剩余等待，继续恢复原等待。结束在安全点收口剩余候选为 not_executed，status=stopped、batch_outcome_code=user_ended；已提交成功/拒绝/失败不改写。验证终止为 verification_required；基础设施异常终止保留已提交结果并标未执行，持久 outcome= infrastructure_error；进程中断按第 8 节。普通批量的暂停/休息/验证恢复不变。

Dashboard 必须按 work_kind 分支：添加显示“添加链接：已处理 X/N”、新增/拒绝/技术失败/验证/中断/未执行数量及真实访问，不能显示商品字段的 0/0；running/pausing/paused/resting/stopping 显示既有运行状态，完成显示按第 6 节派生的“全部新增/部分新增成功/未新增/添加失败”，中止同时显示真实原因与已完成结果。基础设施异常不伪造 Runtime 旧 outcome，使用已有 batch_outcome_code/错误说明。恢复启动后 Runtime 可 idle，历史以终态 Batch 为准；不重建运行任务。Frontend 必须先支持此判别再切换添加入口；旧客户端仍可调用原商品批量/Scheduler/单商品 API，不能用新增模式的商品零计数作为添加结果。只使用原 Dashboard status 请求路径，不增加 Runner、控制器或第二个持久化状态机。

添加每候选最多一次导航；不启用经营补采，也不引入添加失败自动重访。遇平台验证/登录限制按现有检测、可见人工处理和清理规则停止本次添加任务，当前项记录验证或登录失败，其余未执行；不消费验证自动恢复访问，不新开绕过窗口。原批量采集的冷却、恢复次数及 V1.2 熔断机制完全保留。这是避免添加批次化扩大访问的推荐取舍。

## 5. 添加链接任务身份、API 与幂等

### 5.1 新提交与刷新

新增 POST `/api/competitors/add-batch`，body 为 `submission_id`（客户端 UUID）、有序 `inputs`（非空原始行，含原始行号）、`group_id`（可 NULL）。单/多链接都使用它。请求体结构错误、空数组、容量/长度非法返回现有风格 4xx，不创建任务；新受理者确认无既存任务后再检查我方店铺配置/组，失败返回原 4xx，不创建任务；重放不得因设置/组已变化被当作新请求拒绝。逐 URL 合法性在受理后分类。每次提交上限 100 条非空输入、每行最多 2048 字符，超过返回 422 且不截断，已由产品确认。

客户端在点击前冻结有序输入/组并生成 submission_id，先存本地 pending envelope，再发送。重复点击共享同一 in-flight envelope；刷新读取该 envelope 查询任务，网络超时不生成新 UUID、不判定服务器失败。用户修改输入或明确“重新提交失败链接”生成新 UUID、新任务。确认旧任务存在后可清除本地原文，仅保留 task_id；本地恢复信息不含浏览器凭证。持久化本地 envelope 失败则不发请求并提示无法保障恢复。

服务端以 submission_id 作为 add_links 的 task_id（全表现有唯一约束），并保存规范 JSON 请求的 SHA-256 request_fingerprint（有序原始非空输入、行号、group_id；不按商品集合合并）。GET `/api/competitors/add-batch/{submission_id}` 用于查找任务或正在受理的提交；其状态码见下节，不能把查不到已提交 Batch 等同于无人正在受理。

### 5.1.1 确定性并发受理协议（P1-3）

本协议沿用现有单 Backend 进程、唯一进程内 Runtime/采集锁的部署边界，不宣称支持多个独立采集进程。在既有 Runtime 内增加仅覆盖“受理未决窗口”的 admission 标记：submission_id、fingerprint、owner token、pending/unknown；由短临界区原子查找/占有，不另建持久表、后台框架或第二套任务状态机。标记不是 Batch、不是已受理任务，不进入记录首页；持久事实仍只有 Batch/输入/Item。互斥锁不得跨 DB IO/浏览器操作持有；本版选择立即回应 pending，不做服务端等待。实现顺序固定如下：

1. 校验请求体并生成 fingerprint；在 Runtime 短临界区检查同 ID admission。若存在且 fingerprint 不同，立即 409 idempotency_conflict；同 fingerprint 且 pending 则在锁外查一次 DB，已有任务按持久事实重放，尚无任务返回下表 pending，不再尝试采集锁，也不按其他任务忙拒绝；标记为 unknown 时 POST/GET 必须先走步骤 5 的核对/收口，不能只返回 created Batch 而永远遗留预约。数据库查询失败返回 unknown，不能回退成未受理。同 ID 无标记时原子登记唯一 owner，随后才读数据库；因此 A 尚未提交 Batch 时 B 仍能识别 A。不同 ID 只登记自己的临时标记，不能接管 A。
2. owner 用新的 DB session 查 task_id。已存在且 fingerprint 相同则直接重放；不同/碰撞到非添加任务为 409 idempotency_conflict；均不预约、不派发。只有权威查无记录、无未决写事务时才检查业务前提并尝试 acquire_collection_slot 和第 4.1 节添加预约。被另一任务占用则 409 collection_in_progress、清理本 owner 标记，不创建 Batch。整个预约 token 唯一，旧 token 不得操作新任务。
3. 唯一 owner 在一个短事务插入 Batch、全部输入/候选 Item；Batch.settings_snapshot 保存原有节奏配置及 add_group_id，最终保存仍重查组/店铺。task_id 唯一约束是持久化兜底：若冲突，先 rollback，再读胜者校验 fingerprint，绝不派发败者，仅按 token 释放败者自身预约，不得清除胜者 Runtime。正常路径由同 ID admission 避免走到第二次插入；唯一约束不代替受理协议。
4. commit 已确认后才绑定 Runtime 和派发；只有创建并确认本次事务的 owner 可用该 token 在同一临界区领取一次 dispatch 权（包括零候选的即时终结权）。把任务交给既有 start/worker 机制一次；重放、GET、唯一键败者绝不派发。派发异常按既有 fail_created_batch 收口 infrastructure_error，不能靠下一次重放再次派发。Batch 已可见且正常派发/零候选终结或失败收口已确定后移除 pending 标记；健康 pending 与 DB 行短暂同时存在时请求优先返回 DB 任务，unknown 则按步骤 5 核对。进程崩溃后不能重建派发权，启动恢复先收口旧 Batch，后接受新请求/Scheduler。
5. commit 抛错且是否成功未知时 owner 不派发、不再次 insert，不提前释放其 reservation；标记 unknown。先终止/关闭旧事务连接，确认原事务已结束，再用新 session 核对：有 Batch 则保留事实，未派发者收口 infrastructure_error（进程重启则 interrupted），只返回该任务；明确 rollback 且无 Batch 才释放预约/移除标记，允许下一次原 ID 重试重新受理。不能结束旧事务或数据库不可读时保持 unknown/互斥占用，返回 503，不假报 404/忙或成功；待后续同 ID 查询/重试触发同一核对，不启动后台重试框架。原 owner 活着时重放只读，不转移 owner；owner 已退出时在同一 Runtime 临界区只允许一个请求取得核对权，核对者只可收口/释放，不能派发旧任务。已确认派发过的任务仅查结果，不能因后续 HTTP/DB 故障重发 worker。

| 情形 | POST / GET 回应与客户端行为 |
| --- | --- |
| 同 ID 同 payload，A 尚在预约/提交，B 先到达 | POST B 返回 202 admission_pending；GET 同 ID 无 DB 行但有 pending 标记亦同。body: submission_id、admission_state=pending、accepted=false、task_id=NULL，Retry-After=1；这仅确认正在受理，不表示已有真实任务。B 不创建/派发，可按 Retry-After 使用原 ID 查状态或重发原 payload |
| 同 ID 不同 payload | POST 409 idempotency_conflict，无论命中 pending 标记还是持久 Batch；不等待、不改原任务 |
| Batch 已提交，仍活动 | 202，accepted=true、task_id、admission_state=accepted、任务摘要；包括 HTTP 响应丢失后的同 ID 重试 |
| Batch 已终态 | 新批量 POST 重放/GET 返回 200，accepted=true 与原 task_id/结果；不重放采集 |
| 不同 ID、Runtime/采集锁忙 | 权威查无该 ID 后 POST 返回 409 collection_in_progress；不建任务，可稍后用原 ID 重试 |
| DB 短暂不可用、commit 结果未证实、无法核对原事务 | 503 admission_unknown，accepted=NULL、submission_id、task_id 仅在已知时提供、Retry-After=1；不声称未受理，不生成新 ID。客户端保留 envelope，用原 ID 查询/重试；服务器先核对，再决定返回既存任务或重新受理 |
| DB 权威查无 Batch、无同 ID 标记、无未决事务（包括启动恢复完成后） | GET 404 admission_not_found；允许原 ID/原 payload POST。404 不授权生成新 ID |

所有 admission_pending/unknown 都不是任务终态，不显示添加失败，也不清除本地原始 envelope。客户端收到这些状态只恢复受理结果，不启动另一条实时进度 polling；已 accepted 后仍沿既有 Dashboard status 路径。进程在 commit 前崩溃：未提交事务回滚，重启后可原 ID重试；commit 后崩溃：启动恢复将真实任务标 interrupted，原 ID 返回同一终态。数据库未恢复前两种情况均保持未知，禁止推断重建。这里只保证每个已提交任务最多一次派发；明确回滚且无任务时可重新受理，同一次未决提交绝不能自动换 ID。

已知任务重放完成、明确未受理的前提校验失败/忙/事务 rollback 后，owner 只清理自己的 admission 标记及其取得的预约；历史幂等以 DB 为准，不无限缓存已完成 ID。只有实际取得 reservation 且事务仍未决时才持续占用采集互斥；纯查询读失败不会凭空预约或撤销仍正常工作的 owner。无持久写入但 owner 异常退出也必须先证明旧事务结束，再允许同 ID 重新受理。

owner 必须有 finally 收口：异常退出时，若既未证明未受理，也未证明正常派发/终结，就把仍属本 owner 的 pending 标记改为 unknown 并保留核对所需 token/事务结束信息；不能留下永久 pending，也不能直接删标记释放后重做。commit 已确认但派发前的线程异常按未派发基础设施失败收口，收口 DB 失败则进入 unknown。关闭 HTTP 连接本身不作为派发或事务是否成功的证据。

### 5.2 旧 POST 兼容

保留 POST `/api/competitors` 的同步 201 商品响应及原错误码；内部作为单输入添加任务调用同一添加执行操作，受理后先持久任务再访问，成功时写同一任务内的 Run。允许 `Idempotency-Key` UUID header；提供时与 task_id 一致、同 payload 可重放原响应，响应 header 返回 task ID；未提供时每个请求是新的任务，不能保证客户端网络重试合并，明确列为旧客户端兼容例外。新 UI 不再逐条调用此 API。删除后重放不重建商品，返回任务仍存在且商品已删除的 410，不重复访问。错误重放使用保存的稳定错误码/HTTP 映射，不保存任意页面内容。

携带 key 的旧同步 POST 也先执行第 5.1.1 节协议；URL/group_id 规范成单输入 envelope（position=0、source_line=1）后计算相同 fingerprint，不按 endpoint 另造命名空间。首个 owner 仍同步执行并返回 201/原错误；并发重放在 pending 或既存活动任务期间返回 202（accepted=false/true 分别按表），不额外等待另一个同步采集，不作为 409 collection_in_progress；完成后再次用相同 key/payload 返回 201 商品响应或保存的稳定错误映射。503 admission_unknown、不同 payload 409、不同 key 忙 409 也按同表。202/503 是选择 Idempotency-Key 的客户端必须处理的并发/不确定受理扩展，不改变未带 key 的原同步响应合同；同步 owner 的 HTTP 断开不转移执行所有权。旧接口成功重放与新批量接口的终态 200 不混用；异常终止而无商品时按稳定失败/中断映射返回并带 task ID，不再次执行。

## 6. 输入、计划项与成功/失败事实

### 6.1 唯一推荐的数据结构

新增 `CollectionAddInput`（建议表名 collection_add_inputs）是必要的输入事实表，不是第二套任务。原因：任意无效字符串、提交内重复及已存在输入不等于计划商品，且失败时无 competitor_id；将它们全塞入 Item 会破坏 V1.2 planned_products 不变量。比修改 Run.competitor_id 为 NULL 的影响面更小。

每条非空输入一行：id、batch_id FK、position、source_line、input_text（受限原文）、normalized_url / offer_id（可 NULL）、duplicate_of_input_id（同批较前输入，可 NULL）、batch_item_id（候选唯一关联，可 NULL）、related_competitor_id（已存在/成功关联，可 NULL）、result_code（NULL 表待处理，否则见结果表）、error_code / sanitized_reason、started_at / finished_at、navigation_claimed_at / navigation_confirmed_at / navigation_terminal_reason、identity_removed（默认 false）。不用另一套 lifecycle/status/outcome；运行与终态由 Batch 决定，输入是否处理由结果和事实时间决定。

合法性按现有 parse_1688_url，合法后按 platform+offer_id 去重，第一条保留；本次重复优先于 already_exists，关联第一条输入但不复制其成功结果。受理事务内识别已存在商品。候选 = 合法、提交内唯一、受理时未存在的链接；每候选创建一个 CollectionBatchItem，competitor_id 初始 NULL。planned_products 固定为候选数，之后不随成功数变化，即使候选在最终事务再次发现已存在也保留计划项。零候选任务真实完成预检，不启动浏览器。

Item 新增 identity_state = pending / linked / removed：旧非 NULL 回填 linked，旧 NULL 回填 removed，候选未创建为 pending，成功后 linked。查询不再以 competitor_id NULL 推断删除。候选输入与 Item 一一对应；非候选不建 Item。删除后身份状态 removed，不改变计划或输入数。

### 6.2 结果与计数

| result_code | 分类 / 是否可能导航 | Item 与 Run |
| --- | --- | --- |
| added | 成功新增 / 有 | Item linked；原页面结果落库的真实 success Run，关联 Item，attempt=1 / first_pass |
| invalid_url | 业务拒绝 / 无 | 无 Item、无 Run |
| duplicate_input | 业务拒绝 / 无 | 无 Item、无 Run，指向首条输入 |
| already_exists | 业务拒绝 / 通常无，最终复核竞态可有 | 预检无 Item；候选竞态已有 Item；不伪造新 Run |
| identity_rejected | 店铺未知、self 组冲突等业务拒绝 / 可有 | 候选 Item 保留原因，无虚构商品/Run |
| technical_failed | 页面读取、导航超时/网络、保存等技术失败 / 可有或无 | 候选 Item 保留错误；没有商品时无 Run |
| verification_required | 平台验证/登录阻断 / 可有 | 候选 Item；无商品不建 Run；停后续导航 |
| not_executed | 受理后未执行 / 无；有 claim 不确定时不能用它 | 未执行候选保留 Item，无 Run |
| interrupted | 已开始但进程中断无法得知结果 / 可 unknown | 保留事实，不宣称失败未访问或新增成功 |

不增加 Run 失败行来代表无商品的失败，也不先创建占位商品。identity_rejected 的店铺缺失不是平台经营指标异常；正常 `-` placeholder 不属于以上失败。

添加详情以“提交链接 / 候选商品 / 新增商品 / 拒绝输入 / 技术失败 / 待处理或未执行 / 页面访问”命名，默认每页 10 条输入，保留原输入位置，并可展开对应 Item 的真实 Run。列表数量列添加任务显示“提交 N 条（候选 C 个）”，不能标“计划 N 商品”。采集任务保持原商品汇总。

终态互斥输入计数：`submitted_inputs = added + business_rejected + technical_failed + verification_required + not_executed + interrupted`；活动时右侧加 pending_inputs。business_rejected 包含 invalid_url、duplicate_input、already_exists、identity_rejected。`planned_products = 候选 Item 数`；added ≤ planned_products ≤ submitted_inputs。`visited_inputs` 是有 confirmed 的不同输入数；page_visits 是确认导航次数，unknown 通过既有 page_visits_unknown 单列，不等于输入/成功/Run 数。attempts_started 仍仅为真实 Run 数，添加失败可能 page_visits > attempts_started，不沿用“访问必有 Run”推断。

添加候选 Item.final_result 扩展一个 **business_rejected** 终态（P1-1），映射完整如下。CollectionAddInput.result_code 仍为添加输入结果权威，Item 为同事务维护的候选计划/Run 关联，不独立驱动任务；非候选业务拒绝无 Item，但必须计入输入拒绝总数。

| 候选输入结果 | Item.final_result / execution_status / base_result | 统计含义 |
| --- | --- | --- |
| added | first_pass_success / completed / success | 新增成功；有实际 Run |
| already_exists（最终复核）或 identity_rejected | business_rejected / completed / not_attempted | 业务拒绝，已处理；即使已导航也不是基础采集技术失败，无伪 Run。not_attempted 表示未形成可提交的商品基础结果，不表示零访问 |
| technical_failed | final_failed / failed / failed | 真实技术失败；与业务拒绝分离 |
| verification_required | verification_required / completed / not_attempted | 验证/登录阻断独立计数，不塞入 failed |
| interrupted | final_failed / failed / not_attempted | 结果未知；按输入码独立计 interrupted，不当已证实技术失败，current 仍需处理 |
| not_executed | not_executed / not_executed / not_attempted | 未执行；无 Run/导航 |

已处理候选包含 business_rejected，因此候选 `completed = first_pass_success + business_rejected + final_failed + verification_required`，`remaining = planned_products - completed`，终态 remaining=候选 not_executed。各结果互斥；活动时 remaining 还含 queued/running。候选 business_rejected 是输入 business_rejected 的子集，二者不相加；没有 Item 的 invalid/duplicate/预检已存在不能增加候选 completed。普通 V1.2 批次不产生 business_rejected，原 final_failed、成功集合、经营技术失败、completed/remaining 和 Runtime 商品统计原义不变；不扩展 SUCCESS_RESULTS 吞入拒绝。

所有添加汇总（首页列表、完整详情 summary、Runtime.input_progress、恢复后摘要、匿名删除后摘要）必须用同一输入分类映射：added=成功新增；business_rejected=四种业务拒绝之和；technical_failed=仅 result_code 同名；verification_required、not_executed、interrupted 分列。`anomaly_inputs = technical_failed + verification_required + interrupted`；task_has_current_anomaly 还包括真实任务级 infrastructure_error/interrupted，不能用 outcome_code=collect_failed/partial_failure 或所有 Item.final_failed 推导添加技术失败。添加响应中的 counts 商品结果键保留候选原义并增加 business_rejected；succeeded（候选成功）=added，final_failed=候选该终态数（含 interrupted），base_failed_products=实际技术失败候选数，technical_exception_products 保留经营字段异常语义为 0；新增添加专用 input_summary 承载输入计数，anomaly_inputs/technical_failed 的业务标签不可误用原 anomaly_products。按 task_kind 分支聚合，不修改普通批次聚合；添加详情旧 anomaly_products 仅作候选技术失败/验证/中断数，与 input_summary.anomaly_inputs 一致，不能加 business_rejected。所有数字基于全任务，详情筛选/分页不改变摘要。

自然结束的添加任务 outcome：全部输入 added 为 success（UI“全部新增”）；至少一条 added 且其余有拒绝/技术失败为 partial_failure（UI“部分新增成功”，并列拒绝/技术失败数量）；零 added 且全部输入为业务拒绝时 collect_failed（UI **“未新增”**、技术异常 0）；零 added 且有真实 technical_failed 时 collect_failed（UI“添加失败”，另示拒绝/失败数）。复用旧 outcome 枚举仅作为任务终结汇总，不由枚举猜异常或成功新增数。不把“已存在”当成功新增。实际中止按 V1.2 优先级 interrupted > infrastructure_error > verification_required > user_ended > 自然结果；用户结束但全部已完成不覆盖既定自然结果。partial_success 原有经营语义不复用为添加部分成功。

### 6.3 成功保存与导航单一事实来源

添加执行沿用 collect_product 的店铺识别/Offer 校验及 ProductSnapshot/SkuSnapshot 保存，最终事务重读我方店铺设置、组存在性、唯一商品、组 own 约束，不能提前缓存代替。成功添加 Run.started_at 使用该输入真实开始执行的时间，finished_at 使用该次保存完成前的真实终结时刻，不再把保存时同一个 now 写成两端。每候选独立短事务：商品、SKU/商品快照、成功 Run、Item linked、输入 added 一起提交；一个失败仅回滚该候选，前面成功不回滚。不把浏览器访问放入长 DB 事务。

添加先持久输入开始事实，再通过现有 Collector 的 claim/confirmed callbacks 记录输入导航；claim 未成功提交不得导航。添加的导航权威事实保存在输入行，因为失败时没有 Run；成功 Run 的 navigation_* 留 NULL，API 明示 navigation_evidence_source=add_input，并从关联输入返回访问事实；不得把 NULL 显示为零访问。Item 的 page_visits 等只作同事务维护/可重建缓存，查询汇总不同时累加输入与 Run。添加失败无 Run 也展示“输入处理历史”，不用伪造 attempt 行。添加模式不生成 operating_metrics_retry / verification_resume。

collect_product 目前可能返回经营字段，但原添加保存路径没有 Observation。本版推荐维持添加基础能力：不为归档启用经营读取/补采；没有实际持久读取证据时 Run.operating_metrics_status=not_attempted，Observation 空，UI“未采集经营指标”，不是完整、8/8、placeholder 或技术失败。若沿现有 Collector 已实际读取但本版不保存这些经营数据，也不能冒充有历史 Observation。后续正式采集才能产生相应真实经营历史。

保存失败后用新的短事务记录 technical_failed / collection_save_failed 与已确认访问；若数据库仍不可写，任务保持未收口，响应报告结果未知，不能再访。网络断开分两类：客户端断开不取消已受理服务端任务；Collector 网络故障按已有稳定错误分类记录，原因不够细时不猜测，不自动重试。

## 7. 单商品立即采集归批与兼容

推荐保留同步 POST `/{id}/collect`，不把旧接口改成 202。预检商品存在/active 和 acquire_collection_slot 成功后，在访问前创建 manual_single Batch + 一 Item，started_at 取开始实际执行的时刻；collect_competitor 使用同一 reservation、batch_item_id、attempt=1 / first_pass。提取/复用现有 Item 终结与 Batch 汇总收口操作，不另起浏览器 Runner，不让同步 handler 再调用会重新采集的异步 Runner。单商品无循环、无第二队列，仍只有一次调用现有 Collector。

返回原 status / body / outcome / snapshot / collection_run，允许在 collection_run 增加可选 task_id、item ID、attempt 信息；既有字段和错误 HTTP 映射保持。成功/基础失败/验证时均在返回前收口真实 Batch；失败 Run 和 Observation 按原事务规则保存。终态汇总根据真实基础/经营结果派生，可能与旧响应基础 outcome 不同，不能偷换旧字段含义。保存 Run 前崩溃留真实 Batch/Item，恢复规则见下文，不补空 Batch。

单商品使用现有 collect_competitor 的验证检测和锁，验证时原响应返回错误/需要验证，不自动冷却重访；operating_metrics_retry_max 在此执行路径强制有效值 0（保留用户设置原值），也不扩大现有单商品访问预算。所有旧调用方继续同步等待；客户端断开不触发另一次调用；后端执行继续或启动恢复收口。旧单商品 API 不新增跨请求幂等保证：两次明确请求是两次手动任务，UI 必须禁重复按钮且不在网络错误时自动重放。

## 8. 崩溃恢复、时间与删除

Batch 仍只有 created/running/terminal 与既有 outcome_code。任务 started_at 是服务端开始本次输入预检/执行（添加）或实际采集执行（其他）的真实时间；不以第一条成功 Run 时间替代。添加受理事务会做业务分类，因此设置 started_at 为开始该分类的时刻；若尚未启动分类就失败则不创建任务。finished_at 是所有输入/候选终结或安全中止完成的时刻。耗时包括服务端等待/休息/人工验证等待，不含客户端编辑；未结束显示进行中，缺失/逆序为 —，不造零秒。created 的采集 Batch 未执行时 started_at 可 NULL，页面标“未启动”，默认日期过滤按真实 started_at，因此可能需清空日期查未启动任务；添加已开始预检的任务不会被此规则漏掉。

启动时扩展现有 recover_interrupted_batches，在 Scheduler 启动前处理包括 add_links/manual_single 的所有活动 Batch，且 Scheduler 被禁用时仍恢复：

- 已终态输入（包括全部业务拒绝）、成功商品/Run/快照原样保留；按第 6.2 节输入码幂等补齐关联 Item/汇总，business_rejected 保持 completed/not_attempted，不能被通用恢复函数重分类为 final_failed 或因为无 Run 而改成 not_executed。已提交 Run 但 Item 缓存未更新时从事实幂等补齐，不能重访问。普通 Batch 恢复逻辑不变。
- 未开始候选标 not_executed；已开始且无最终提交标 interrupted；Batch=interrupted，不自动续跑旧任务。
- 添加输入无 claim=0 访问；claim 无 confirmed=1 unknown；有 confirmed=1 confirmed。进程崩溃时 unknown 不能自动升级为 confirmed/0。无商品和 Run 仍可正确恢复。
- 创建任务成功但 worker/浏览器尚未启动：保留同 task_id，中断收口，全部未执行候选访问为 0；同 ID 重放返回旧任务，不启动它。用户明确重新提交未执行/失败链接才建新任务。
- 不对已明确提交成功的商品按未知失败回滚。对于未提交商品，即使浏览器读取成功但落库未证实，也不显示 added。

受理阶段无持久 Batch 的 pending/unknown 不由 recover_interrupted_batches 伪造任务；进程活着时按第 5.1.1 节确认事务，进程重启则先完成 DB rollback/已有 Batch 恢复，再开放请求。恢复后的 input_summary 从输入结果重建，技术失败与业务拒绝仍分离；无自动重派发。

删除扩展既有事务性 _delete_competitor_history：先冻结匿名计数，再清除所有相关输入的 input_text、normalized_url、offer_id、related_competitor_id、可识别原因/时间外的页面内容及关联 fingerprint 中的可识别材料（只保留不可逆 hash），Item identity_state=removed，然后沿既有 Observation/Run/SKU/Snapshot/事件/商品顺序删除并断开 FK。原始未带商品 ID 的失败及重复行也必须按规范 offer_id 匹配同一商品一起清除；不能只按成功 FK 清理。无效原文不包含可可靠识别商品时保留受限输入文本供定位，显示无关联商品，不误称删除。

成功关联后不能冗余保存标题/店铺/图片供历史泄漏；安全错误说明仅稳定码和脱敏文字，不包含 HTML、cookie、任意 query 参数。删除后只保留输入位置、结果类别、时间、访问事实、匿名统计及“身份已移除”，不显示链接/hash。未创建商品的 pending/failed 与 removed 必须区分。删除受唯一互斥保护，任何失败全部 rollback，删除前后统计不变。幂等 fingerprint 仅验证同请求，不用于重新显示已删除原文。

## 9. 首页筛选组合合同与查询 API

取消 record_type、legacy/single 页面及仅服务它的 search/selected-single 状态、控件、帮助文案、组件和专用 UI 用例。首页固定四个控件：开始日期、结束日期、触发方式、异常情况；只调用 GET `/api/collection-batches`。不新增关键词或 outcome 控件。手动内部枚举统一显示“手动采集”，scheduled“定时采集”，add_links“添加链接”；删除历史未知选项。

异常下拉保持 all/current/none/recovered/placeholder/source_unavailable/loading/read_failed/base_failed，增加 rejected（业务拒绝）、verification_required（需验证）。其中“无当前异常”明确指已终态且无未解决技术失败/验证的任务，允许业务拒绝但列表必须另示拒绝数量；不把运行中/未执行/中断且结论未知归为健康成功。current 包含未解决基础/经营技术失败、添加技术失败、验证和无法确认结果的 interrupted，以及添加任务真实的任务级 infrastructure_error；recovered 必须有本任务真实历史技术失败及后续成功恢复证据，不用旧 latest_valid。

| 触发方式 | 可选异常 | 真正不适用的类别 |
| --- | --- | --- |
| 全部 | 全部类别 | 无；某类别只匹配有能力产生该事实的任务 |
| 手动采集 | 除 rejected 外全部 | rejected：现有商品采集不存在添加输入业务拒绝 |
| 定时采集 | 除 rejected 外全部 | rejected 同上 |
| 添加链接 | all/current/none/base_failed/rejected/verification_required | recovered、placeholder、source_unavailable、loading、read_failed：本版添加不补采、不保存经营 Observation，不能成立 |

base_failed 在添加仅匹配 technical_failed 的真实基础技术失败，不匹配 invalid_url/duplicate_input/already_exists/identity_rejected 或 interrupted；verification_required 独立定位验证/登录，详情显示准确原因。经营具体类别基于本任务任意真实 Observation 或匿名保留计数，recovered 基于最终恢复，不能过滤掉历史 attempt。添加 current 使用第 6.2 节 task_has_current_anomaly，none 要求任务终态、pending/not_executed/interrupted 为 0 且无当前技术/验证/任务级异常，允许纯业务拒绝；rejected 匹配任意输入的四种业务拒绝，不要求有 Item。rejected 与 none 可在同一任务上分别命中，rejected 不属于 current；列表与详情不得沿用 business_rejected→final_failed 的旧假设。

组合能力是代码/合同常量，不按当前数据库计数 disable。切触发方式导致现有异常不适用时，在同一次受控状态更新中重置 anomaly=all，并给出简短原因，page=1；不可先发无效组合请求。新的真正不适用组合返回 422 incompatible_filter（包含 allowed_anomalies），禁止静默返回空表。全部+rejected 和全部+经营异常有效；当前零数据仅显示真实空状态。**兼容例外（P2-1）**：GET `/api/collection-batches?trigger_kind=unknown` 继续接受，按原“无匹配真实批次”返回 200、items=[]、total=0、正常分页元数据；与合法日期/异常参数组合仍为空，不纳入新 UI 能力矩阵/不适用 422 判定，不把任何已知 Batch 改成 unknown。非法参数格式仍按原参数校验处理。旧 Run 查询 API 的 unknown 参数同样保留；只删除 UI 选项，不改变已有调用方查询行为。

手动映射增加 manual_single，已有精确 trigger query 保留兼容。服务端先过滤后排序分页，排序仍 started_at DESC、batch id DESC；同一空 started_at 组内按 batch id 倒序，不制造时间。添加列表/详情返回 task_kind、input_summary、候选数、真实访问数及来源；添加详情 items 为输入行，使用 task_kind 区分响应解释，分页单位 inputs；普通任务维持商品 items 与原字段。响应不得让客户端把输入当商品。全任务摘要独立于详情过滤/分页；添加详情 search 匹配未去身份化的输入文本/规范 Offer 和当前关联商品标题/店铺；复用 final_result=all/success/exception/pending/not_executed 并增加 business_rejected：success 仅 added，exception 为 technical_failed/verification_required/interrupted，business_rejected 为四类业务拒绝（含无 Item 输入），pending 为 result_code NULL，not_executed 同名；新增 input_result 支持第 6 节精确 result_code（all 为默认），两者取交集。输入业务拒绝可由 input_result、final_result=business_rejected 或 anomaly=rejected 定位。添加详情 anomaly 支持 all/current/none/rejected/verification_required，current=technical_failed/verification_required/interrupted，none=added 或四类业务拒绝（not_executed/pending/interrupted 不进入）；任务级基础设施错误在完整摘要显示，不能伪造错误输入。anomalies_first 按技术失败/验证/中断优先、再 position，不改变原始位置。其余精细商品 final_result 和非 all 的 attempt_kind/reason 返回 422，不默默空列表；普通详情保留原合同，input_result 非 all 对它不适用，final_result=business_rejected 查询普通批次为空且不改变其原有结果分类。

日期继承最近 30 天默认起日、结束不限，浏览器本地日转 UTC；清除恢复默认，可清空日期访问全历史；允许单侧，逆序/非法日期本地报错不发请求。日期和合法下拉变化自动服务端查询、回第一页；保留 AbortController + loadedQuery/request URL 绑定和迟到响应拒绝。总数缩减回有效页后重新查询；错误可重试，不显示旧 payload 冒充新结果，不新建轮询。首页 20 条，详情 10 条输入或商品。

## 10. 历史保留与未来 unbatched 例外

不迁移/归并旧 Run 归属，不回填 Batch，不删除 Run、Observation、Snapshot、时间和错误。旧数据允许不出现在新的任务首页；既有 V1.2 Batch 继续出现，内部触发不改写。

可靠查询入口继续存在：GET `/api/collection-runs`（unbatched/legacy_only、商品标识搜索等兼容参数）、GET `/api/collection-runs/{run_id}`，商品详情 API `/api/competitors/{id}/detail` 的 recent_collection_runs；Dashboard 汇总/趋势仍直接使用原 Run。商品详情“最近历史”有界，不宣称它能替代全部历史 API。Observation 的 latest_attempt/latest_valid 查询继续沿原经营指标合同，不由首页限制。UI 不另建历史入口，也不删除供其他页面使用的数据类型/共享组件。

生产写入点静态搜索确认只在 create_competitor 和 collect_competitor；Runner 的两类调用及 Scheduler 均复用后者。V1.3 要求它们在生产执行时必须带真实 Batch/Item：兼容单添加 API 也归批，共享服务的缺省单商品入口须建立同步一商品上下文；若未给足批次上下文且不是明确单商品入口则拒绝在导航前执行，不能漏出未归属 Run。测试 fixture/历史导入可有 NULL，但不是新生产采集入口；低层 Collector 本来不写 Run，不算例外。未来新入口必须接入同一合同。

因此不保留“新生产 unbatched Run”业务例外；只保留升级前既存 NULL 和隔离测试/显式历史导入。旧客户端无幂等 key 可产生多个真实 Batch，是任务重复保护的兼容限制，不能据此制造 unbatched。实现验收需重新全仓搜索 Run 构造/共享服务调用，脚本若发现新的生产写入点必须纳入合同或停止报告，不能默认可信。

## 11. Migration、约束与事务合同

需要新增一个 Alembic revision，down_revision=`20261012_14`，建议编号 `20261015_15`（实施前确认无新 head 冲突）；不改历史迁移、不 stamp。本轮只设计。

| 对象 | 必要变更 / CHECK 与兼容 |
| --- | --- |
| CollectionBatch | trigger CHECK 增 manual_single/add_links；增加 nullable request_fingerprint CHAR(64)，旧行 NULL；add_links 要求非 NULL。task_id 和 scheduler_occurrence_key 唯一性保留；生命周期和 outcome 枚举不扩张 |
| CollectionBatchItem | 增 identity_state，回填规则见第 6 节；CHECK pending/linked/removed，linked 当且仅当 competitor_id 非 NULL，pending/removed 必须 NULL。final_result CHECK 在原枚举上增加 business_rejected，execution_status/base_result 枚举不变；新增 CHECK：business_rejected 必须 execution_status=completed 且 base_result 非 NULL、等于 not_attempted，不能因 SQL NULL 语义漏过约束。原 position/competitor 唯一、其他结果及非负 CHECK 保留 |
| CollectionAddInput | batch FK、可空 Item/competitor/duplicate FK；UNIQUE(batch_id,position)，UNIQUE(batch_item_id)；position/source_line 非负（source_line 从 1 起），result_code 受第 6 节有限枚举约束；finished_at 非空需 result_code 非空；confirmed 要有 claim；identity_removed=true 时所有身份文本/FK 为 NULL；输入文本长度上限 2048；日期允许尚未完成 NULL，不能填伪时间 |
| Run / Observation / Snapshot | 不改 Run.competitor_id 非空，不改历史 NULL batch 关系，不改 Observation CHECK/事实；成功添加 Run 关联已有 Item，原 attempt 唯一约束适用 |

跨表合同由创建/最终提交事务与集成测试保证：输入只能属 add_links；duplicate 指同批较前输入；Item 同批且一候选一项；business_rejected 只能用于 add_links 候选，必须有对应业务拒绝输入；普通 Batch 不产生此终态；成功 Run.competitor_id=Item 的真实商品；计划数等于候选 Item 数。不得仅用 ORM 声称 SQLite CHECK 能验证跨表不变量。

添加导航权威在输入行，普通采集在 Run；Item/Batch 展示汇总可由各自事实重建，既有删除匿名缓存作为删除后事实保留。新增输入行无任务状态；所有派生结果只由 Batch 收口，不增加独立 add job 状态机。数据库写失败时不能发送页面导航。提交输入/计划、每次导航 claim/confirm、每商品保存、最终收口是分离短事务；未知提交先查原 task，不重新访问。启动恢复为幂等 DB 操作。

升级用 SQLite batch_alter_table 处理 CHECK，保证现有 Run→Item→Batch、Observation→Run、SKU→Snapshot 外键及索引不丢失；执行 integrity_check / foreign_key_check、旧行数量和关键值对比。不能因为本地 schema 不符就 stamp，发现 drift 停止。正式库升级只在未来另获授权并备份后做。

downgrade：只有不存在 V1.3 add_links/manual_single 任务、输入事实、business_rejected 终态及 pending 身份等旧模型不可表达数据时才允许降至 _14；存在时应在 DDL 前明确拒绝，不删除事实、不改写 trigger 伪装旧数据、不静默脱关联。无 V1.3 数据时删除增量结构/列、还原 CHECK，旧 Batch/Run 保持。生产回退优先恢复经核验备份，不能把有损降级当兼容。空库升级/回滚与含 V1.2 数据升级/回滚、含 V1.3 数据拒绝回滚均为验收项。

## 12. Testing Decisions 与验收矩阵

只测外部行为、数据不变量和导航证据；复用现有 FastAPI TestClient、SQLite tmp_path、注入 Collector/Context、Runner 线程/事件、现有 fail-closed installApiMock。禁止为测试新建采集框架，不接真实库/1688/Profile，不启动真实 Scheduler。以下是后续实施必须落地的验收，不是本轮测试通过报告。

| 场景 | 可观察结果 / 断言 | 优先 seam |
| --- | --- | --- |
| 三触发与空计划 | manual 各内部枚举/scheduled/add_links 各一任务；无 due/空 all_active 无假任务 | collection API、daily、records |
| 单链接添加 | 一输入、一候选、一商品/快照/SKU/Run、一确认访问；经营 not_attempted/无 Observation | own_product_management + injected Collector |
| 五链接全成功 | 一 Batch、五输入/候选/Run，顺序执行，每链接一次导航，不再采集新商品 | batch_collection + API |
| 三成功/一已存在/一无效 | 一任务五结果、三候选/成功/访问，部分成功；两个拒绝零访问 | 添加 API + records |
| 同提交重复/不同 URL 同 Offer | 保留原始输入与行号，duplicate 指首条；无额外访问/Run | App.test + API |
| 全无效/全已存在 | 有真实添加任务、零候选/访问、无浏览器；全部拒绝不标技术故障 | API + records |
| 一个新增/一个最终复核已存在 | 两候选 completed=2、remaining=0；added=1、business_rejected=1、technical_failed=0、anomaly_inputs=0；拒绝 Item=business_rejected/completed/not_attempted；部分新增成功，首页 none/rejected 均命中、current 不命中 | 添加 API fault seam + records |
| 五输入全部已存在 | total=processed=5、remaining=0、candidate_total=0；added=0、business_rejected=5、technical_failed/anomaly_inputs=0，UI“未新增”；无浏览器/Run，不能因 collect_failed 枚举标技术异常 | API + Runtime + Dashboard |
| 一个新增/一个页面技术失败 | added=1、technical_failed=1、business_rejected=0、anomaly_inputs=1；失败 Item=final_failed/failed/failed；current/base_failed 命中，none 不命中；摘要与详情一致 | 添加 API + records |
| 无效 URL/重复输入零访问 | 每条输入仍有独立拒绝结果，无导航 claim/confirmed、无 Item/Run；不影响候选失败数 | API + Collector callback spy |
| 业务拒绝恢复/删除后查询 | 最终已存在或身份拒绝保持 business_rejected；重复恢复不改终态，删除匿名后输入/候选计数与 current/none/rejected 筛选不变；普通批次既有 final_failed/成功统计不变 | startup/deletion + records |
| self/competitor/组冲突 | 最终事务识别身份；店铺未知/组被删/已有 own 拒绝，快照无半写入 | own_product_management 既有并发 seam |
| 无商品 ID 失败 | 输入 error + 导航证据存在，nullable Item pending 身份，无伪 Run；不显示已删除 | API + detail |
| 添加保存失败/后条失败 | 前面成功保留；失败候选原子回滚，错误收口且无额外访问 | commit fault injection |
| 同 ID 并发/超时/刷新/重复点击 | 同 payload 一任务一次派发；异 payload 409；刷新查原 ID；失败重提新任务且成功项不重交 | API concurrency + own-product-entry E2E |
| A 未获预约/未提交时同 ID B | 用事件阻塞 A 在 admission 登记后、预约前以及 commit 前；B 同 payload 返回 202 pending/accepted=false、task_id=NULL，不能返回 busy；异 payload 即 409 conflict；A 最终只建一 Batch/只派发一次 | 原 Runtime/线程事件 + TestClient |
| 不同 ID 忙/提交成功响应丢失 | 不同 ID 返回 409 busy 且无任务；相同 ID 重试已提交任务返回 202 accepted 或终态 200，唯一约束胜者外无人派发 | API/dispatch spy |
| commit 结果未知/数据库短暂不可用 | 返回 503 unknown、不释放未决预约、不产生第二次写/导航；结束原事务后查到任务则收口不重派，确知 rollback+无 Batch 才允许原 ID 新受理；断库 GET 不得伪装 404 | commit/read fault injection + startup |
| 进程崩溃受理两窗口 | commit 前 rollback 后原 ID可安全受理；commit 后启动先 interrupted、原 ID 返回旧任务；两种都禁止自动新 ID、禁止恢复派发 | migration-safe SQLite fixture + startup |
| 旧同步 Idempotency-Key 并发 | A 同步执行；B 同 payload 在提交前/执行中 202，完成重放 201/原错误；异 payload 409、不同 key 忙409、未知503；Collector/dispatch 仅一次，未带 key 原响应不变 | own_product_management API concurrency |
| 客户端断网/关弹窗 | 不以网络错误回滚或取消任务，记录可重新查询 | controlled requests / E2E |
| 验证/登录/用户结束 | 添加当前真实验证结果，后续未执行；不重访、不启用补采；普通批量原恢复规则不变 | Collector/Runner seam |
| 添加 20 条运行进度 | 20 个输入预约不依赖商品 ID，初始 input_progress=0/20、候选未知后固定；例如预检拒绝2、候选18、先新增3/技术失败1后，processed=6、pending=remaining=14；商品字段仍0且 Dashboard 显示6/20，不显示0/0 | Runtime + API response + Dashboard E2E |
| 零候选 Runtime | N>0 全拒绝仍真实预约/绑定/收口；input_progress=N/N，候选0且无浏览器；完成后 runner_active=false、token释放 | Runtime/Context spy |
| 部分失败与暂停继续 | 页面技术失败只加 input_progress.technical_failed，不加商品 failed；暂停安全点前后当前输入位置正确、计数来自已提交事实；暂停保留剩余等待，继续无重复访问/计数 | 既有 Runner event seam |
| 20 条中处理后结束 | 已拒绝2/新增3/技术失败1后结束：processed=6、not_executed=remaining=14、pending=0；status stopped/user_ended，保留成功，Dashboard 显示6/20与未执行14；候选completed=4/remaining=14 | Runtime + persisted API + E2E |
| 创建后派发失败/浏览器前崩溃 | infrastructure_error 或启动 interrupted，零访问；同 ID 不重启 | scheduler/startup recovery seam |
| claim/confirm 各崩溃窗口 | 0/unknown/confirmed 互斥且幂等，成功事务未知不重访 | batch_collection fault injection |
| 单商品同步归批 | 原响应/错误兼容，导航前 Batch/Item、真实 Run/Observation；设置 retry=2 也不多访 | test_collection_api + operating_metrics |
| 访问/计划/耗时 | 输入、候选、成功、Run、visited_inputs 各异；任务时间覆盖真实执行；缺时间 — | records API + CollectionTasks |
| 删除与失败输入 | 同 Offer 成功/重复/无 ID 失败一并匿名化；计数不变；无悬空 FK/身份泄漏；事务失败全回滚 | deletion API + records |
| 历史保留 | 升级前后 Run/Observation/Snapshot/错误/时间一致，NULL 不回填；历史 list/detail、商品 recent、Dashboard 趋势、latest_valid 可用 | migration + collection_runs/detail/dashboard/operating_metrics |
| 筛选所有组合 | 参数化触发×异常表；不适用 422，合法零数据不禁用；手动精细枚举聚合；current/none/recovered/拒绝口径准确 | records API |
| unknown 旧查询兼容 | trigger_kind=unknown 与 all/current/none/rejected 及日期/分页组合均200空结果，参数元数据正确；UI无该选项；新 manual+rejected/add_links+placeholder 仍422 incompatible_filter | records API + CollectionTasks |
| 自动筛选交互 | 四控件、无 record_type/未知入口；单侧/逆序日期、第一页重置、清除、缩页、过期响应、错误重试 | CollectionTasks + collection-tasks.spec |
| 添加详情与旧详情 | 输入分页/商品分页单位准确；摘要不变；历史 attempt 完整；pending≠removed，经营未采集不造字段 | records API + E2E |
| 迁移完整性 | _14→新 head→可回滚条件；business_rejected CHECK 只允许completed/not_attempted，普通批次跨表规则由事务测试验证；新数据拒绝降级在 DDL 前；外键/索引/CHECK/唯一竞争和数据计数 | migration tmp SQLite |
| 真实副本兼容 | 经另行授权取得一致性副本，在隔离位置升级/校验/回滚条件；绝不对正式库测试 | migration harness，实施/发布阶段 Gate |

删除仅旧页面专用 UI 测试，保留 collection_runs API 历史测试和共享展示、日期、防过期请求回归；修改已有 E2E 场景以保护新合同，不通过整批删除失败测试完成迁移。实施阶段 targeted tests 后检查相关 Backend/Frontend、类型/Lint/构建及受控 Chromium；真实平台人工 QA 须未来另行授权，不由 Mock 测试证明。

## 13. 可行性、已确认规则与 Review 边界

架构可行：现有互斥/共享 Collector/Run 与持久 Batch 已覆盖主体；真正缺口是“商品创建前的输入和导航证据”，因此一个附属输入表合理且必要。添加采用同一 Runner 的执行操作分支，单商品保留同步共享服务，比把所有旧 API 改异步的兼容成本低。备选“仅让前端逐链接带 batch_id”无法保证刷新后剩余输入受理与任务一致性，不推荐；备选“放宽 Run 商品外键并以 Run 代表输入”混淆尝试/拒绝且影响历史查询，不采用。

产品已确认：添加遇验证停止、不自动重访；原批量验证恢复不变；单商品保持同步；旧无 key 客户端跨请求去重有限；添加不做经营补采、不虚构 Observation；100 条/2048 字符上限；删除后去身份化；有 V1.3 数据拒绝有损 downgrade；全业务拒绝显示“未新增”。这些规则不再作为待决风险。

本次四项 Finding 已给出唯一完整合同，无留给 Implement 自行决定的未决产品合同：P1-1 使用输入权威分类及 business_rejected 候选终态；P1-2 使用唯一 Runtime 的显式添加预约/input_progress；P1-3 使用短期 admission 标记+既有互斥+持久唯一键，未决提交不重派；P2-1 保留 unknown 的旧 API 空查询。仍待 ChatGPT Final Spec Review 确认此次修订，不等于已 Freeze。

工程边界：admission 标记只在现有单进程采集部署内有效，不能扩成多进程保障；若原事务无法核对，采集互斥可能保持占用直至 DB 恢复/进程重启后核验，这是避免重复访问的明确限制。正式 schema/真实副本、并发/崩溃与 UI 合同尚未实施验证，须后续按验收矩阵落地；这些是工程验证门槛，不重开已确认的产品决策。

## 14. Spec 自检与交付门槛

- 已沿七类入口核对 API、Batch/Item/Run/Observation、互斥、重访与 unbatched；未把客户端去重后的条数当原始输入。
- 已区分既有事实与新增合同；没有按相近时间猜归属，没有让已成功商品再进入 Runner 重采。
- 已定义幂等/短事务/未知提交、导航计数/中断恢复、失败无 ID、删除匿名化、筛选能力及旧同步接口兼容。
- 本次集中核对 result_code→Item final_result/base_result→Batch outcome→Runtime→列表/详情/异常筛选→恢复→迁移 CHECK→验收；业务拒绝不计技术失败，pending 受理不伪装持久任务，unknown 旧 API 仍兼容。
- 新迁移只设计，旧 _14 不修改；无业务代码、测试、正式数据、设置或 Profile 改动。
- 自检是作者检查，不替代 ChatGPT 独立 Spec Review；状态保持 Draft / 待 Review。
- 仅提交本文及必要 README 索引；Push 后核对远端 SHA。完成后停止，等 ChatGPT 从 GitHub 独立 Review，未 Freeze 不 Implement。
