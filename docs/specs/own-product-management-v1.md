# 我方商品与统一监控入口 V1

## Problem Statement

当前系统把“我方商品”和“竞品”都放在 `Competitor` 列表中，商品身份主要依赖人工设置 `group_role = own`。这使三个本应分开的事实混在一起：商品属于哪一家店铺、商品和哪个商品组比较、商品是否正在监控。结果是列表、Dashboard、Group Summary 和 Group Attention 容易把我方商品算进竞品统计，也让用户必须先把商品加入竞品列表，再人工维护我方角色。

当前 1688 采集边界已经能够得到可靠的 `shop_name`、商品事实和历史快照，但新增商品接口还没有在持久化前完成真实商品识别。解析失败、验证、网络错误和缺少店铺名称时，如果先创建 `Competitor`，就会留下无法解释的半成品记录。

本 Feature 需要在不重建现有采集链路、不把 `Competitor` 全仓重命名的前提下，建立可靠的商品身份事实、监控大屏单一添加入口和我方商品管理页面。

## Solution

V1 引入独立的 `ownership` 商品身份事实：

- `ownership = self`：成功采集到的标准化店铺名称精确等于系统配置的我方店铺名称。
- `ownership = competitor`：成功采集到的标准化店铺名称不等于我方店铺名称，或历史迁移中没有足够证据证明是我方商品。

身份识别只做确定性的空白处理：去除首尾空白，并把连续空白折叠为一个空格；不做大小写、全半角、Unicode 归一化、关键词、简称、相似度或模糊匹配。

`ownership` 回答“是谁家的商品”，`group_id` 回答“和谁比较”。现有 `group_role` 保留为兼容的组内角色，但不再是商品身份来源，也不允许用户直接指定。其合法状态由商品身份和分组关系自动维护。

“添加竞品”调整为监控大屏的主操作“添加监控商品”，并作为竞品监控模块唯一的新增商品入口；我方商品、竞品列表、竞品分组和采集任务不重复提供添加入口。添加时先通过现有 1688 Collector / Parser 边界取得足以确认 `shop_name` 的真实结果，成功后才创建监控商品并自动出现在我方商品或竞品列表；失败时不创建 `Competitor`、Snapshot、ChangeEvent 或无主的 CollectionRun。

新增“竞品监控 → 我方商品”页面。我方商品和竞品列表共享现有列表模式、采集和生命周期能力，但按 `ownership` 分流。竞品统计、竞品排序和 Group Attention 的 Changed Competitor 只使用 `ownership = competitor`；我方商品仍完整参与采集和事实保存，但不被算作竞品。

本 Spec supersede `docs/specs/own-product-role-binding.md` 中关于“由用户在竞品组页面人工绑定我方身份”、由 `group_role` 识别我方商品、旧解除行为和旧新增流程的产品语义；不删除旧 Spec。旧 Spec 中关于一个组最多一个 own、使用现有 `Competitor` 采集与历史事实、事务安全和历史保留的兼容性原则继续有效，但以本 Spec 的 `ownership` 不变量和组操作语义为准。

## User Stories

1. 作为运营者，我希望配置我方店铺名称，以便系统能依据真实 1688 店铺事实识别商品归属。
2. 作为运营者，我希望查看当前我方店铺名称和是否已配置，以便知道新增监控是否具备自动识别条件。
3. 作为运营者，我希望只从竞品监控大屏使用“添加监控商品”入口，由系统自动识别并分流到我方商品或竞品列表，以便新增入口集中且不必先判断商品应该放在哪个列表。
4. 作为运营者，我希望粘贴 1688 链接后系统先确认真实店铺名称，再正式创建监控商品，以便列表中没有身份未知的半成品。
5. 作为运营者，我希望成功识别为我方的商品自动进入我方商品页面，以便不用人工绑定身份。
6. 作为运营者，我希望成功识别为其他店铺的商品自动进入竞品列表，以便新增流程保持简单。
7. 作为运营者，我希望解析失败、验证、网络失败或无法取得店铺名称时看到明确原因，并保留原链接，以便修复后重试。
8. 作为运营者，我希望添加失败不会留下商品、快照或错误的竞品记录，以便监控数据只包含可解释对象。
9. 作为运营者，我希望一次粘贴多个链接时逐条处理，失败链接保留在 Dialog 中，成功链接不需要重复提交。
10. 作为运营者，我希望我方商品页面只显示 `ownership = self`，竞品列表只显示 `ownership = competitor`，以便两个列表的身份边界稳定。
11. 作为运营者，我希望我方商品页面沿用现有搜索、状态筛选、采集状态筛选、分组筛选和分页，以便不学习第二套列表交互。
12. 作为运营者，我希望从我方商品页面选择商品并采集选中商品，以便我方基准商品和竞品一样持续更新事实。
13. 作为运营者，我希望停止、恢复和单条永久删除我方商品，以便按现有监控生命周期管理基准商品。
14. 作为运营者，我希望停止监控只改变监控开关并保留历史，永久删除继续遵守现有锁、事务和历史级联删除规则。
15. 作为运营者，我希望为单个我方商品绑定竞品组，以便建立它和直接竞品的比较关系。
16. 作为运营者，我希望更换单个我方商品的竞品组，以便修正比较范围，而不是批量改变多个基准商品。
17. 作为运营者，我希望解除我方商品的竞品组后它仍然是我方商品，以便分组关系不会改变商品身份。
18. 作为运营者，我希望一个竞品组最多只有一个我方基准商品，以便组内比较基准始终明确。
19. 作为运营者，我希望目标组已有其他我方基准商品时操作被拒绝且原状态不变，以便系统不静默覆盖重要关系。
20. 作为运营者，我希望竞品分组页仍能看到组的我方基准商品和竞品统计，但不再从该页人工把商品“绑定为我方”，以便身份来源保持单一。
21. 作为运营者，我希望竞品分组、Group Detail、Group Attention 和 Dashboard 的竞品数量只统计直接竞品，以便我方变化不会伪装成市场竞品变化。
22. 作为运营者，我希望我方商品仍保存 ProductSnapshot、SkuSnapshot、ChangeEvent、在线/下架、价格、SKU、库存、MOQ、标题和主图事实，以便未来使用我方商品做竞争分析。
23. 作为运营者，我希望修改我方店铺名称后，已有且有可靠店铺名称的商品重新识别，以便页面分类和当前配置最终一致。
24. 作为运营者，我希望当前店铺名称缺失时系统不猜测商品身份，并保留已有可靠身份直到下一次成功识别，以便缺失数据不会造成错误迁移。
25. 作为运营者，我希望后续采集发现店铺名称变化时商品身份自动更新，并在组冲突时明确告知处理结果，以便列表分类不会长期落后于真实商品。
26. 作为运营者，我希望旧数据升级后人工确认过的 own 不会无故消失，历史快照和变化事件也不会被覆盖、清空或伪造。
27. 作为运营者，我希望旧数据中同组多个可能的我方商品得到确定且可解释的冲突处理，以便升级后不留下需要手工修复的非法角色状态。
28. 作为维护者，我希望沿用现有 API、Collector、Snapshot、ChangeEvent、CollectionRun 和前端测试 seam，以便本 Feature 不扩展成 TrackedProduct 全仓重构。
29. 作为运营者，我希望在系统设置中查看和修改我方店铺名称，并在修改已有配置前看到重识别影响提示，以便明确配置变更可能带来的商品分流和竞品组基准变化。
30. 作为运营者，我希望进入竞品监控大屏时直接看到当前我方店铺，并在同一紧凑信息行右侧看到“添加监控商品”主按钮，以便先确认当前分析基准再执行新增。

## Implementation Decisions

### 1. 身份、分组和兼容角色

- 在现有 `Competitor` 增加非空 `ownership`，允许值仅为 `self`、`competitor`。不新增 `OwnProduct`、OwnProductSnapshot、SkuSnapshot、GroupMember 或多对多关系。
- `Competitor`、`competitor_id`、现有 API 路径和底层采集对象名称本轮保持不变；这是兼容性债务，不在本 Feature 中全局重命名。
- `group_id` 仍是当前分组事实；`ownership` 是商品归属事实；`group_role` 只表达当前组内角色。
- `group_role` 不提供给客户端作为可写身份字段。任何新建、绑定、换组、解除、删组和采集后的身份更新，都由 Backend 根据 `ownership` 与 `group_id` 在同一业务事务中维护。

合法状态固定为：

| ownership | group_id | group_role | 含义 |
|---|---|---|---|
| `competitor` | NULL 或非 NULL | `competitor` | 直接竞品，未分组或属于某个竞品组 |
| `self` | NULL | `competitor` | 我方商品，暂未建立比较组；此处的 `competitor` 仅是兼容的组内角色默认值 |
| `self` | 非 NULL | `own` | 该组唯一的我方基准商品 |

因此必须满足：

- `competitor` 不得成为 `group_role = own`；
- `group_role = own` 必须同时满足 `ownership = self` 且 `group_id IS NOT NULL`；
- `ownership = self` 未分组时必须保留 `ownership = self`，并使用 `group_role = competitor`；
- `ownership = self` 进入有组时必须成为该组 own；
- 每个组最多一个 `group_role = own`；
- 不允许通过绕过前端的请求制造需要用户手工修复的长期不一致状态。

数据库使用 `CHECK` 约束、现有 partial unique index（每组最多一个 own）和事务内组变更维护上述状态。`group_role` 的状态约束不能被前端条件判断替代。

### 2. 我方店铺名称设置

只新增与本 Feature 直接相关的最小设置能力，不实现通用设置框架或其他系统设置。

- 持久化一个 `own_shop_name` 设置项。实现可使用最小的 `system_settings` key/value 表；不新增设置领域对象、配置服务或多租户抽象。
- 当前工作区迁移时，若设置项不存在，写入当前业务值 `广州莓有科技有限公司`；不得覆盖用户已经保存的设置。接口仍必须能表达“设置缺失/未配置”，以覆盖新安装、异常恢复或设置项缺失的安全路径。
- `GET /api/settings/own-shop-name` 返回：

  ```json
  { "configured": true, "own_shop_name": "广州莓有科技有限公司" }
  ```

  未配置时返回 `200`、`configured = false`、`own_shop_name = null`。
- `PUT /api/settings/own-shop-name` 请求体为 `{ "own_shop_name": "..." }`。服务端去除首尾空白；空字符串、全空白和超出当前设置字段安全长度的值返回稳定校验错误，不保存部分值。成功返回新的设置状态。
- 不提供客户端设置 `ownership`、`group_role` 或批量重分类参数。保存设置后的重识别是 Backend 的确定性事务行为。
- 未配置时新增监控商品返回 `409 own_shop_name_not_configured`，不访问后续创建持久化边界，也不创建半成品记录。前端 Dialog 保持打开并提示先在系统设置中配置我方店铺名称。
- 未配置时已有商品仍可按现有采集链路采集并保存真实快照；若本次没有可用配置，采集不得猜测或改写 `ownership`。已有 `ownership` 作为最近一次可靠确认的身份事实保留，直到配置存在且再次成功识别。
- 本 Feature 同时启用现有左侧“系统设置”入口并提供最小系统设置页：展示当前 `own_shop_name`，支持编辑和保存，并明确覆盖 loading、save、validation、error 和保存后的刷新状态。页面不实现其他设置项，不建立通用设置框架。
- 当已有配置被修改时，Frontend 在发起 PUT 前必须让用户确认以下提示： “保存后将根据当前商品店铺名称重新识别我方商品与竞品，并可能调整竞品组中的我方基准商品。” 用户取消则不发请求；保存成功后刷新设置、我方商品、竞品列表、竞品组和相关 Dashboard 读数据。

### 3. 店铺名称标准化与身份识别

- 比较前对配置值和成功采集得到的 `shop_name` 使用同一安全标准化：去除首尾 Unicode 空白，并将连续 Unicode 空白折叠为一个普通空格。
- 除空白处理外不做大小写折叠、全半角转换、Unicode 归一化、标点删除、关键词匹配、简称推断、相似度计算或平台身份 ID 推断。
- 只有成功采集并通过现有 `expected_offer_id` 校验、字段语义校验和 `shop_name` 非空校验后，才允许据此更新身份。
- 标准化后精确相等配置值时目标身份为 `self`，否则目标身份为 `competitor`。解析失败、验证、网络失败、Offer ID 不一致、页面不可用、数据不完整和 `shop_name` 缺失都不是 competitor 证据。
- 不新增 `unknown ownership`、`ownership_pending` 或持久化“待识别”状态。未知只存在于请求/错误结果中，不进入监控商品表。

### 4. 统一添加监控商品

- 保留现有 `POST /api/competitors` 路径以减少兼容面，但其产品语义从“直接添加竞品”改为“添加监控商品”。请求继续接受标准化 1688 URL 和可选 `group_id`；客户端不得传 `ownership` 或 `group_role`。
- “添加监控商品”只在竞品监控大屏展示，并作为本模块唯一新增商品入口；我方商品、竞品列表、竞品分组和未来采集任务页不重复展示该按钮。点击后仍复用同一 Add Dialog 和 Backend `POST /api/competitors` 流程，按钮文案固定为“添加监控商品”。
- 添加采用两阶段校验。Preflight 只做尽早失败检查：校验 URL、确认当前 `own_shop_name` 已配置、校验提交的目标 `group_id` 当前存在、校验当前没有重复的 platform + offer_id；这些结果不能作为最终落库的权威状态。Preflight 通过后才尝试取得 `COLLECTION_LOCK` 并执行真实 Collector / Parser。
- 这条添加前置采集属于正式采集，必须复用现有进程内 `COLLECTION_LOCK`。只读的 URL、设置、目标组和重复检查可以在加锁前完成；进入 Collector 前必须以非阻塞方式取得该锁。锁已被单商品采集、批量采集、daily collection 或其他现有正式采集占用时，立即返回稳定的 `409 collection_in_progress`，不继续访问 Collector，也不访问后续持久化创建边界，不创建 Competitor、ProductSnapshot、SkuSnapshot、CollectionRun 或 ChangeEvent。
- 添加流程从 Collector 开始到保存完成期间持有同一把 `COLLECTION_LOCK`，因此现有单商品/批量采集在添加持锁期间也必须按 `collection_in_progress` 拒绝；不新增第二把锁、等待队列或并发模型。所有成功、采集失败、保存失败和异常路径都必须在 `finally` 中释放锁，确保下一次正式采集能够重新获取。
- 外部采集阶段不得先提交 Competitor。失败时不保存 Competitor、ProductSnapshot、SkuSnapshot、ChangeEvent 或 CollectionRun；不得为了记录失败而留下没有监控对象的 CollectionRun。
- Collector 成功后，必须在最终持久化数据库事务中重新读取并验证当前事实：当前 `own_shop_name`、platform + offer_id 是否已经存在、提交的目标 `group_id` 是否仍存在，以及按最终 `own_shop_name` 与本次真实非空 `shop_name` 识别为 self 时目标组是否已有其他 own。最终事务读取到的事实是唯一权威：ownership 不得使用 Collector 前缓存的配置值；配置在采集期间变化时按新配置决定 self / competitor；如果最终设置已缺失，返回稳定的 `409 own_shop_name_not_configured`，不得猜测身份；Offer 已存在返回稳定的 `409 competitor_already_exists`；目标组已不存在返回稳定的 `404 competitor_group_not_found`；self 的目标组已有其他 own 返回稳定的 `409 own_product_already_bound`。任一最终校验失败都必须原子 rollback，不创建 Competitor、ProductSnapshot、SkuSnapshot、CollectionRun 或 ChangeEvent。
- 外部 Collector 执行期间不得持有长生命周期的数据库事务。最终校验通过后，才在一个数据库事务中原子创建 Competitor、baseline ProductSnapshot、其 SkuSnapshot、成功 CollectionRun 和当前商品事实；首次 baseline 不生成普通 ChangeEvent。数据库约束继续作为最后防线；并发数据库写入导致约束冲突时不得提交部分状态，必须 rollback 并映射为相应稳定业务错误或安全的可重试冲突。实现不新增锁、版本字段、队列或复杂并发框架，继续复用现有采集、标准化、快照和变化检测边界。
- 未选择目标组时：`self` 保存为 `ownership = self, group_id = NULL, group_role = competitor`；`competitor` 保存为 `ownership = competitor, group_id = NULL, group_role = competitor`。
- 选择目标组时：`competitor` 加入目标组并保持 `group_role = competitor`；`self` 只有在目标组没有 own 时才能加入并成为 own。目标组已有其他 own 时返回 `409 own_product_already_bound`（或等价稳定错误码），整个添加不创建任何监控记录，不自动覆盖或换组。
- 成功响应必须至少包含 `ownership`、`group_id`、`group_role` 和真实商品信息，使前端可以展示准确分流反馈；不得通过商品 ID、列表来源或组摘要反推身份。
- 失败错误沿用现有稳定错误分类，并新增 `own_shop_name_not_configured` 与 `shop_name_unavailable` 等明确身份前置错误。HTTP 错误、请求异常和真实采集业务错误必须区分；任何一种失败都不能被转换为 competitor 成功。首次添加时，如果 Collector 检测到商品已下架或页面失效且无法可靠提供非空 `shop_name`，统一返回 `422 shop_name_unavailable`，消息必须明确“无法确认店铺名称，未添加监控商品，请重试”；不得因存在 offline 证据而绕过身份识别。该错误不创建 Competitor、Snapshot、SkuSnapshot、CollectionRun 或 ChangeEvent；登录、验证、超时、解析等已有稳定错误仍沿用各自 contract。
- 添加 Dialog 的交互保持：提交中禁用重复提交；任一 URL 识别失败时保持 Dialog 打开、保留失败 URL 和失败原因；混合结果只从输入框移除已成功 URL，失败 URL 继续可重试；不因部分成功静默关闭。
- self 成功提示固定表达“已识别为我方商品「…」，已添加至我方商品”；competitor 成功提示“已添加监控商品「…」”或等价明确文案，不把结果描述为用户主动选择的竞品。

### 5. 列表、导航与页面职责

- `GET /api/competitors` 增加可选 `ownership=self|competitor` 过滤参数，并在返回商品对象中暴露 `ownership`。无参数时保持现有兼容语义，返回全部监控商品（self + competitor）；`ownership=competitor` 只返回竞品；`ownership=self` 只返回我方商品；其他值返回稳定的参数校验错误，不静默退化为全量或 competitor。
- 竞品列表必须显式请求 `GET /api/competitors?ownership=competitor`；我方商品页面必须显式请求 `GET /api/competitors?ownership=self`。页面分类不得依赖无参数全量结果再由前端猜测或过滤身份。
- 搜索、商品状态、采集状态、竞品组筛选和分页沿用现有 Competitor List 的前端模式；本 Feature 不引入服务端搜索、排序、分页框架或全局状态库。
- “我方商品”页面消费同一列表 contract 的 `ownership = self` 结果，至少展示现有竞品列表已有的监控事实：商品标题、店铺、Offer ID、分组、价格、SKU 数量、最近变化、最近采集、商品状态和监控状态；缺失事实继续显示“未采集/未知/—”，不补零。
- 我方商品页面的批量操作仅支持采集选中、停止监控、恢复监控。永久删除只提供单条操作，并沿用现有 `COLLECTION_LOCK`、单事务、历史级联删除和失败回滚规则；停止/恢复不删除历史。
- 我方商品页面提供单条“绑定竞品组 / 更换竞品组 / 解除竞品组”。不能提供多个我方商品批量绑定到同一组的操作。解除后商品为 `ownership = self, group_id = NULL, group_role = competitor`，仍出现在我方商品页面。
- 我方商品的单条分组操作复用现有商品分组 API seam，但对 self 采用 ownership-aware 语义：绑定到空闲组成为 own；目标组已有其他 own 时返回 409 且不变更；解除或移动到未分组保留 self 身份；不自动覆盖目标组 own。
- 竞品列表只展示 `ownership = competitor`。删除“绑定为我方商品”“解除我方商品”等人工身份入口；普通竞品仍可按现有规则单条/批量设置竞品组、采集和生命周期操作。
- 我方商品不得批量绑定竞品组，也不得批量永久删除。Backend 对批量分组和批量删除仍必须按 `ownership = self` 拒绝 self，不能只检查 `group_role = own`，因为未分组 self 的兼容 `group_role` 是 competitor；拒绝不得部分改变身份或历史。
- 如果 Feature A 阶段仍从现有 Dashboard/列表暴露 `all_active` 采集入口，其文案统一为“采集全部监控商品”，范围必须是全部 `is_active = true` 的 self + competitor，展示数量必须与 Backend `all_active` 实际请求范围一致。移动到“采集任务”页面属于独立 Feature B。
- 左侧导航顺序为：竞品监控大屏、我方商品、竞品列表、竞品分组、采集任务。`采集任务` 的页面和 CollectionRun 管理不属于本 Spec；本轮只统一导航命名，不实现采集任务页面。
- 竞品监控大屏标题说明区与 KPI 卡片之间增加一条紧凑的当前上下文行：左侧显示 `我方店铺：{own_shop_name}`，右侧显示主按钮“添加监控商品”。该店铺信息不是 KPI，不新增第五张指标卡，也不在每个商品组重复强调。
- Dashboard 通过现有设置 contract 获取当前 `own_shop_name`。未配置时显示“我方店铺：未配置”及“去系统设置”的明确入口；此时“添加监控商品”不可进入真实添加流程，用户应先完成店铺配置。
- “添加监控商品”仅由 Dashboard 打开现有统一 Add Dialog；我方商品、竞品列表、竞品分组和采集任务页面不显示新增商品按钮。系统设置页只处理 `own_shop_name`，不新增批量添加 API、依赖或页面级复制流程。

### 6. 分组 API 与旧角色绑定兼容

- `PATCH /api/competitors/{competitor_id}/group` 继续作为单商品组变更入口，但必须按 ownership 维护 `group_role`：competitor 始终为 competitor；self 进入组时只能成为 own，移出组时变为兼容的 competitor role。
- 现有 `PUT /api/competitor-groups/{group_id}/own-product` 和 `DELETE /api/competitor-groups/{group_id}/own-product` 不作为新 UI 的身份来源，但为已存在客户端保留兼容路径。PUT 只能操作 `ownership = self` 且属于该组的商品；对 competitor 返回稳定 `ownership_mismatch`，禁止旧客户端重新制造人工 own。DELETE 对 self 解除组关系并保留 self 身份；不得把 self 留在组内作为 competitor。
- 竞品分组页面可以只读展示 `own_product` 摘要和竞品统计；不再提供旧 Spec 中的“绑定我方商品/更换/解除”菜单。新绑定入口只在我方商品页面的单条操作中提供。
- 更换、解除、转组、删组和删除商品不得改写 ProductSnapshot、SkuSnapshot、CollectionRun 或 ChangeEvent。删除组时所有成员 `group_id = NULL`、`group_role = competitor`，但 self 的 `ownership` 必须保留。
- 组 Summary、Group Detail、Group Attention 使用 `ownership = competitor` 作为竞品成员资格的最终过滤条件，并继续使用当前 `group_role` 读取组内 own。对历史不一致行，读 API 不应把它们计为竞品；迁移/服务写入应修复到本 Spec 合法状态。

### 7. 数据迁移与冲突处理

- 新增一条 Alembic migration，不修改历史 migration。迁移增加 `ownership`、设置持久化结构和必要约束/索引，使用仓库现有 SQLite batch/table-rebuild 方式；升级后不得残留临时表，不删除或重建历史 Snapshot/ChangeEvent 内容。
- 设置项先确定当前配置；当前业务值为 `广州莓有科技有限公司`。若设置项已经存在，迁移不得覆盖；若缺失，插入该当前业务值。若实际部署无法得到配置，迁移必须 fail-closed：非 NULL 的 `shop_name` 无法完成当前配置比较时不得据此猜测 self；只有 NULL shop_name 的旧人工 own 才可使用 legacy fallback。
- ownership 回填规则按以下固定顺序执行：

  1. 当前 `shop_name` 非 NULL 时，它是最高优先级的当前身份事实：标准化后等于当前 `own_shop_name` 标记为 `ownership = self`，不等于则标记为 `ownership = competitor`；旧 `group_role` 不得覆盖明确的非匹配店铺名称。
  2. 只有当前 `shop_name = NULL` 时，原有 `group_role = own` 才可作为 legacy 人工确认 fallback，标记为 `ownership = self`；NULL shop_name 的其他记录标记为 `ownership = competitor`。
  3. 不得根据标题、URL、Offer ID、价格、组名或历史 Snapshot 猜测 self。回填后按 `ownership + group_id` 重建合法 `group_role`，不允许 self 留在组内但仍是 competitor role。

- 同一组冲突处理固定如下，不静默覆盖：

  - 先只保留依据当前非 NULL shop_name 精确匹配得到的 self，以及 NULL shop_name 的 legacy own fallback；已知其他店铺的旧 own 已是 competitor，不得成为 winner，也不得抢占真实 self。
  - 组内存在一个有效 legacy own fallback 且没有更高优先级的真实 self 时，该 fallback 可保留为 self/own；组内有多个真实 self 时，按 `(created_at ASC, id ASC)` 选择唯一 winner，不得让 legacy fallback 覆盖真实 self。
  - 组内没有有效 legacy own 或真实 self 时，不生成 own；组内有多个通过 shop_name 精确识别为 self 的商品时，按 `(created_at ASC, id ASC)` 选择唯一 winner 作为 self/own。
  - 其余 self 商品保留 `ownership = self` 和全部历史事实，但移动为 `group_id = NULL, group_role = competitor`，在“我方商品”页面可见，等待用户单条绑定到合适的组。
  - 如果历史数据库中出现多个 NULL shop_name 的原 own，按 `(created_at ASC, id ASC)` 保留一个 fallback，其他 own 同样转为 self/未分组；非 NULL 且已知不匹配配置的旧 own 全部按 competitor 处理。任何分支都不得覆盖或删除商品事实。
  - 迁移输出明确的冲突数量和商品 ID/winner 信息供升级日志核对；不新增持久化冲突状态，也不把冲突伪装成 competitor。

- migration downgrade 只有在不存在 `ownership = self` 时才允许删除本 migration 的 ownership 结构；仍存在 self 时明确拒绝并保持 schema/data 不变，避免静默丢失商品身份。
- 迁移验证必须确认原有商品、组、Snapshot、SkuSnapshot、CollectionRun、ChangeEvent 数量和内容保持，原有 platform/offer 唯一约束、生命周期约束、外键和 own partial unique index 仍有效。

### 8. 配置修改与后续重新识别

- 保存新的 `own_shop_name` 后，在同一数据库事务中对当前 `Competitor.shop_name` 非 NULL 的商品重新识别；非 NULL shop_name 始终优先于 legacy role，不重新解析历史 HTML，也不重写历史 Snapshot.shop_name。
- 当前 `shop_name = NULL` 的商品不因配置修改被猜测或自动反转身份：保留已有 ownership，等待下一次成功采集到 shop_name 后再识别。
- 对有可靠当前 shop_name 的商品，新配置精确匹配则目标为 self，否则目标为 competitor。目标变更只修改当前 ownership、必要的 group/role 关系和 `updated_at`，不制造 ChangeEvent，不删除历史。
- 重新识别后按组逐组维护唯一 own：当前非 NULL shop_name 精确匹配得到的真实 self 优先；只有没有真实 self 候选时，NULL shop_name 的既有 self/own 才可作为 legacy fallback 保留。若原 own 已变为 competitor，则按 `(created_at ASC, id ASC)` 选择真实 self winner；其余 self 冲突商品（包括失去优先级的 NULL fallback）移至未分组并保留 self。
- 配置保存返回成功设置状态，并以真实字段表达重识别结果（至少可由 Backend contract tests 验证重识别和冲突数）；页面不能显示“配置已成功”却继续按旧身份长期展示。
- 配置缺失时不执行全量反转、不把商品批量改成 competitor，也不允许新增商品；这是 fail-closed，而不是一种新的 ownership 状态。

### 9. 成功采集后的身份维护

- 每一次成功采集得到新的非空 `shop_name` 后，都使用当前 `own_shop_name` 重新判定 ownership；不允许只在创建时判定一次。此时 legacy `group_role = own` fallback 不再覆盖真实 shop_name 事实。
- `competitor → self`：当前商品的非 NULL `shop_name` 精确匹配当前配置时，它是高于 NULL legacy fallback 的真实 self。若商品未分组，保留未分组 self；若所在组无 own，当前商品成为该组 own；若所在组的 own 是 `shop_name = NULL` 的 legacy fallback，则当前真实 self 成为该组 own，原 fallback 保留 `ownership = self`，但移至 `group_id = NULL, group_role = competitor`；若所在组已有基于非 NULL `shop_name` 精确匹配得到的真实 self，则保留现有 own，新识别的 self 移至 `group_id = NULL, group_role = competitor`。不能在每次采集时重新选择真实 self winner，避免组关系抖动；legacy fallback 永远不能覆盖后来取得的明确非 NULL `shop_name`。
- `self → competitor`：ownership 改为 competitor；若商品仍在组内，保留 group_id 并成为直接竞品；若未分组则继续未分组 competitor。
- `self → self` 和 `competitor → competitor` 不改变组关系；采集事实照常保存。
- 上述 ownership、当前 `shop_name`、必要的 `group_id/group_role` 调整与本次成功采集事实保存属于同一数据库事务；事务提交前不得向客户端暴露部分状态。身份调整不修改既有 ProductSnapshot、SkuSnapshot、CollectionRun 或 ChangeEvent，也不制造历史身份事件。
- 采集响应、批量采集结果或下一次列表刷新必须能表达身份变化和组冲突提示，例如“已识别为我方商品；因目标组已有我方基准商品，已移至未分组”。成功采集不能因身份冲突被伪装成失败，也不能静默覆盖组 own。
- 身份变化不生成“ownership_changed”类型的 ChangeEvent；ChangeEvent 继续只表达已有 Snapshot 事实之间的客观商品变化。

### 10. 竞品统计与历史事实

- 我方商品继续参与正式采集，继续产生 ProductSnapshot、SkuSnapshot、ChangeEvent、在线/下架状态、价格、SKU、库存、MOQ、标题和主图事实；采集 service 不建立 self 专属分支或第二套 Collector。
- 以下所有“竞品”口径必须过滤 `ownership = competitor`：Dashboard 监控竞品数量、今日变化竞品数、竞品降价/库存变化统计、竞品变化列表、趋势中的竞品变化计数、Group Summary 的竞品数量/监控数/价格区间/今日变化、Group Attention 的 Changed Competitor、以及所有以竞品命名的排序和数量。
- Group Detail 可继续把 own 事件作为单独的我方事实展示，直接竞品比较和 action 列表仍只使用 competitor；不在本 Spec 增加 Own Competitive Position。
- 通用“采集状态概览”可以统计所有监控商品的 CollectionRun，因为它描述采集能力而不是竞品数量；任何面向用户的文案必须区分“监控商品”与“竞品”。
- `ownership`、`group_id` 和 `group_role` 的变更只影响当前读模型，不改写 Snapshot、SkuSnapshot、ChangeEvent 或 CollectionRun 的历史行。

## Testing Decisions

测试只验证外部可观察行为和稳定 contract，不测试内部 helper 拆分、SQL 拼接、组件内部 state 形状或具体 Collector 实现细节。外部 1688 / Playwright 行为全部在现有采集边界替换为 fake/stub，不访问真实网站，不输出 profile、Cookie、HTML 或 Token。

### Backend

优先使用现有 FastAPI TestClient + 临时 SQLite 的 API/service seam；身份判定、添加前置采集、设置保存和统计过滤应通过最终 HTTP 行为验证。只有当 API 无法覆盖迁移输入时，才使用现有 Alembic 临时数据库 migration seam。

至少覆盖：

- 设置 GET 的已配置/未配置 contract；PUT 的 trim、空值拒绝、保存后读取和已有设置不被迁移覆盖；未配置时添加返回稳定错误且没有 Competitor、Snapshot、CollectionRun。
- 系统设置页的初始加载、保存中禁用重复提交、校验失败、读取/保存错误、首次配置直接保存和已有配置修改前的精确确认文案；取消确认不得发 PUT，保存成功后相关列表/分组/Dashboard 重新读取。页面不出现其他设置项。
- 标准化只处理空白：首尾/连续 Unicode 空白可匹配；大小写、全半角、简称、关键词和相似名称不匹配。
- 添加 self：fake Collector 返回目标 Offer 的真实 shop_name，创建 self、baseline Snapshot/SKU/CollectionRun，返回 self，未产生 ChangeEvent，并按目标组空闲/未分组规则设置 group_role。
- 添加 competitor：真实其他店铺进入 competitor；竞品列表可读到，self 列表不可读到。
- 添加前置采集复用现有 `COLLECTION_LOCK`：单商品/批量/daily collection 占锁时添加返回 `409 collection_in_progress`，Collector 不执行且数据库没有新增；添加持锁时其他正式采集同样返回 `collection_in_progress`；Collector 或保存异常后锁可再次获取。成功保存只在数据库事务中原子创建 Competitor、baseline Snapshot/SKU、成功 CollectionRun 和当前事实，不在外部采集期间持有长事务。
- 添加失败：无效 URL、重复 Offer、Offer ID 不一致、登录/验证、超时、解析失败、数据不完整、shop_name 缺失和保存失败均不创建半成品；首次添加检测到 offline/页面失效但无可靠非空 `shop_name` 时稳定返回 `422 shop_name_unavailable`，不创建任何监控商品或历史行；错误码与错误类型不把失败归类为 competitor。已有监控商品后续采集检测为 offline 的生命周期语义不受此首次添加规则影响。
- 添加最终持久化重校验：fake Collector 期间修改 `own_shop_name` 后，最终按新配置分类；删除目标组后添加返回稳定 group-not-found 且不创建任何记录；目标组在 Collector 期间获得其他 own 时 self 添加返回 `409 own_product_already_bound` 且不创建任何记录；最终重复检查发现 Offer 已存在时返回稳定 duplicate contract 并原子失败。上述最终校验失败均不创建 Competitor、Snapshot、SkuSnapshot、CollectionRun 或 ChangeEvent。
- 后续成功采集的 competitor→self、self→competitor、self 未分组、空闲组和配置缺失路径；组冲突必须分别按第 9 节验证：当前 own 为 `shop_name = NULL` 的 legacy fallback 时，新取得的真实 self 替代该 fallback，fallback 保留 self 身份但移至未分组；当前 own 为非 NULL `shop_name` 精确匹配得到的真实 self 时，保持现有 own 稳定，新识别的真实 self 移至未分组。两种组关系调整均与当前事实保存原子提交，历史 Snapshot/ChangeEvent 不变。
- self 单条绑定、换组、解除和删除；目标组已有 own 返回 409 且无部分更新；解除后仍 self/未分组；停止/恢复保持历史；单条永久删除沿用锁、事务和级联规则；我方批量永久删除明确被拒绝。
- ownership 合法状态的数据库约束：competitor 不得 own，self 未分组必须兼容 role，self 入组必须 own，同组最多一个 own；批量分组/批量删除按 ownership 保护未分组 self；我方页面批量菜单只有采集选中、停止监控、恢复监控。
- 列表 contract：无参数 GET 返回 self + competitor；`ownership=competitor` 和 `ownership=self` 各自精确过滤；非法 ownership 返回稳定参数错误；`all_active` 采集范围和展示数量均为全部 active self + competitor，文案为“采集全部监控商品”。
- 迁移输入覆盖：既有 own 且 shop_name 非 NULL 匹配、既有 own 且 shop_name 非 NULL 明确不匹配、shop_name 精确等于 `广州莓有科技有限公司` 但 role 为 competitor、shop_name 为 NULL、其他店铺、同组多个真实 self 候选、同组多个 NULL shop_name 旧 own。断言非 NULL shop_name 优先、已知其他店铺旧 own 不得成为 winner、NULL legacy fallback 规则和 winner/未分组结果确定、历史行未变、约束有效、downgrade 在存在 self 时拒绝且不改数据。
- 修改配置后的已知 shop_name 重识别、NULL shop_name 保留身份、组冲突的稳定 winner 和历史不变。
- Dashboard、Group Summary、Group Detail、Group Attention 对 self 的竞品统计排除；self 事件不进入 Changed Competitor、竞品排序或竞品变化数量；Group Detail 既有 own 事件分离语义不回归。

### Frontend

沿用当前 `App.test.tsx` 的 Vitest 静态渲染、交互和 API mock seam，并复用 Competitor List 的筛选/分页测试方式。至少覆盖：

- Dashboard 在 KPI 前显示紧凑上下文行：已配置时显示 `我方店铺：{own_shop_name}` 与右侧“添加监控商品”主按钮；未配置时显示“我方店铺：未配置”和“去系统设置”，且不能进入真实添加流程。
- 导航包含“我方商品”，顺序和“采集任务”命名正确；只有 Dashboard 展示“添加监控商品”入口，我方商品、竞品列表、竞品分组不显示添加按钮；Dashboard 能打开既有 Add Dialog；系统设置入口启用并进入最小设置页。
- self/competitor 列表分流、竞品列表显式请求 `ownership=competitor`、我方商品显式请求 `ownership=self`、无参数全量 contract 不被误用、身份字段消费、我方页面列表事实、搜索/筛选/分页、选择和空状态；不通过 `group_role` 推导 ownership。
- 添加 Dialog 的成功提示、self 明确分流提示、失败保持打开、失败 URL 保留、混合输入只保留失败项、设置未配置提示、采集/验证/网络错误与普通 HTTP 业务错误分开。
- 我方页面的批量采集选中、批量停止、批量恢复，以及单条永久删除、单条绑定/更换/解除竞品组；成功刷新列表/组/统计，409 冲突保留操作上下文并显示错误；不出现批量绑定或批量永久删除入口。
- 竞品列表不显示 self，不显示旧人工“绑定/解除我方商品”入口；批量操作对 self 的保护反馈稳定。

### Playwright

继续使用 fail-closed 的受控 API mock，与真实 Backend 和 1688 隔离，只增加高价值路径：

1. 从 Dashboard“添加监控商品”入口提交 self → 出现在我方商品 → 单条绑定竞品组。
2. 从 Dashboard“添加监控商品”入口提交 competitor → 出现在竞品列表。

不将每个后端状态重新做成 E2E；迁移、约束、统计排除和错误矩阵由 Backend contract tests 保护。

## Out of Scope

- 采集任务页面、CollectionRun 管理 UI、定时采集和调度器改造。
- AI 分析、Own Competitive Position、Group Situation Summary、推荐、风险/竞争力评分、通知和报表导出。
- 多店铺、多平台身份体系，以及 seller_id、member_id、shop_id 等平台身份模型。
- 模糊店铺名匹配、相似度、关键词、简称或人工猜测。
- 完整商品资料库、ERP、库存管理、订单或商品编辑能力。
- `Competitor`、`competitor_id` 全局重命名，或 TrackedProduct 全仓重构。
- 新建第二套 1688 Collector、第二套 Snapshot/ChangeEvent 体系、批量添加 API、全局状态框架、新依赖或大规模前端重构。
- 将 `ownership` 失败、未知或配置缺失持久化成新的业务状态。
- 通过本 Feature 改写既有 Snapshot、SkuSnapshot、CollectionRun、ChangeEvent 的历史事实、检测语义或事件类型。
- 在竞品分组页面继续提供人工绑定/解除我方身份的产品入口；旧兼容 API 的保留不等于继续支持旧 UI 语义。
- 本轮修改 `docs/data-model.md`、roadmap 或其他长期文档；实现完成并验证稳定后，如有必要再由独立文档变更同步长期数据模型。

## Further Notes

- 当前 `docs/data-model.md` 对 `group_role` 的现状描述仍是实现基线；本 Spec 是后续实现 `ownership`、设置、添加前置识别和统计过滤的 Feature contract，不在本轮直接修改长期数据模型文档。
- 本 Spec 的关键单一事实来源为：`ownership` = 商品归属，`group_id` = 当前比较组，`group_role` = 兼容的组内角色，`ProductSnapshot/SkuSnapshot` = 历史采集事实，`ChangeEvent` = 客观变化，`CollectionRun` = 采集执行状态。
- “我方商品”不是 ERP 或独立商品实体，而是现有监控商品中经过可靠店铺事实识别后的一个 ownership 视图。这样可以继续复用采集、快照、详情和生命周期能力。
- 迁移和重新识别将 self 冲突商品移至未分组是有意的可解释关系修复：它保留身份和历史，不覆盖组内既有基准，也不制造非法 `group_role`；用户之后只能对单个 self 商品显式选择目标组。
- 任何页面分类都必须直接消费 Backend 返回的 `ownership`，不使用 `shop_name`、`group_role`、组摘要 ID 或前端缓存自行推断。
- 成功标准：配置存在时，新增商品只有在真实店铺名称可验证后才落库；self/competitor 分流正确；合法状态始终满足数据库约束；self 完整参与采集但不进入竞品统计；迁移、配置变更和后续采集都不会留下长期身份/组角色不一致；所有失败路径保留用户输入并给出可行动反馈。
- 产品问题：本轮需求已冻结，无仍需产品决策的问题。实现阶段若发现现有 Collector 无法在不持久化 Competitor 的情况下复用，必须在现有采集边界内补充最小的“采集后持久化” seam，不得回退为先创建半成品再尝试识别。
