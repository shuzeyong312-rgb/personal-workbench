# 我方商品角色绑定 Feature Spec

## Problem Statement

当前竞品组能够归集多个 `Competitor`，并展示竞品数量、监控状态、价格区间和变化摘要。但 Group Intelligence 的正式业务单元是“一个我方真实 1688 基准商品 + 多个直接竞品”，现有模型只表达组成员关系，无法指出哪一个成员是我方商品。把组名当作商品或根据标题、店铺、链接等信息推测角色都会造成不可靠事实。

## Solution

在现有组成员上显式维护唯一的组内角色：每个组最多有一个我方基准商品，其余成员都是直接竞品。角色只改变组内分析身份，不改变商品实体、采集链路、监控状态或历史记录。用户只在 Groups 页面显式绑定、更换或解除角色。

## User Stories

1. 作为工作台用户，我希望把组内一个真实商品指定为我方基准商品，以便明确 Group Intelligence 的比较基准。
2. 作为用户，我希望一个组最多有一个我方基准商品，以便组的分析角色保持明确。
3. 作为用户，我希望未指定我方商品的旧组继续正常显示为未绑定状态，以便升级后不丢数据也不误认商品。
4. 作为用户，我希望绑定候选仅来自当前组已有成员，以便角色操作不复制添加商品流程。
5. 作为用户，我希望候选商品展示真实标题、店铺、Offer ID、商品状态和监控状态，以便识别正确商品。
6. 作为用户，我希望未采集标题时以 Offer ID 标识候选，而不是看到虚构商品名称。
7. 作为用户，我希望能将我方角色更换到同组另一商品，以便修正基准商品选择。
8. 作为用户，我希望更换时明确知道旧我方商品会保留并成为直接竞品，以便理解操作后果。
9. 作为用户，我希望解除我方绑定后商品仍留在组内并作为直接竞品，以便历史与监控不中断。
10. 作为用户，我希望我方商品与直接竞品继续共享现有采集、快照、SKU 快照、采集记录和变化事件，以便数据链路一致。
11. 作为用户，我希望我方商品的在线状态与监控开关独立于角色，以便角色操作不改变商品生命周期。
12. 作为用户，我希望转组不会静默改变商品的业务角色，以便移动分组与选择比较基准仍是两个明确意图。
13. 作为用户，我希望移出组或删除组时原我方角色自动解除，以便未分组商品不残留非法角色。
14. 作为用户，我希望删除我方商品后组自动显示未绑定，同时其余成员和历史按现有删除规则处理。
15. 作为用户，我希望 Group Summary 的竞品数量、监控数、价格和变化只反映直接竞品，以便不把我方数据混入竞品分析。
16. 作为用户，我希望在组卡片看到我方商品绑定状态和标题，以便从 Groups 页面识别当前基准。
17. 作为用户，我希望竞品列表中的我方商品有克制的“我方”标记，以便识别角色而不让普通商品列表充满冗余标签。
18. 作为用户，我希望商品详情能看到所属组内角色，以便检查商品身份。
19. 作为用户，我希望未分组卡片不提供绑定入口，以便角色仅存在于正式竞品组内。
20. 作为用户，我希望并发或重复请求不能造成组内多个我方商品或部分更换，以便角色状态始终一致。

## Implementation Decisions

### 1. 角色模型与数据库不变量

- 在现有 `Competitor` 增加 `group_role`，允许值为 `competitor`、`own`。默认值为 `competitor`；旧行迁移后全部为 `competitor`。
- `group_role = competitor` 表示当前组中的直接竞品；`group_role = own` 表示该组唯一的我方基准商品。
- 不新增 `OwnProduct`、`OwnProductSnapshot`、`OwnSkuSnapshot`、`GroupMember` 或多对多关联表。采集与历史事实继续关联现有 `Competitor`。
- 数据库必须同时约束：角色值合法；`group_id IS NULL` 时角色只能是 `competitor`；每个非空 `group_id` 最多一行 `group_role = own`。
- SQLite 使用 `CHECK (group_role IN ('competitor', 'own'))`、`CHECK (group_id IS NOT NULL OR group_role = 'competitor')`，以及对 `group_id` 建立、谓词为 `group_role = 'own'` 的 partial unique index。SQLite 支持 partial index，SQLAlchemy 的 SQLite partial-index 条件可表达该索引；它由数据库执行，不依赖前端检查。若仓库当前迁移封装不能直接表达，应使用 Alembic/SQLAlchemy 支持的 SQLite 索引定义，而不是退化为应用层唯一性判断。
- `group_id` 仍是商品至组的唯一归属事实。拒绝 `CompetitorGroup.own_competitor_id`：该方案会同时存储 `Competitor.group_id` 和组到商品的反向引用，可能指向另一组成员，形成双向冗余且需额外同步；`group_role` 与既有 `group_id` 位于同一行，更易由约束和组变更事务维护。
- `group_role` 与 `status`、`is_active` 完全独立。任意角色都允许 `active` / `offline` 状态和监控中 / 已停止状态组合。角色只回答“它是谁”，不表示是否在线、是否监控或采集是否成功。

### 2. 绑定与解除 API

绑定或更换使用组级业务 API，不开放通用 role 字段更新：

```text
PUT /api/competitor-groups/{group_id}/own-product
Content-Type: application/json

{ "competitor_id": 123, "replace_existing": false }
```

- 成功返回 200 JSON：`{ "competitor": <完整 Competitor 响应，含 group_role> }`；角色字段必须为 `own`。实现可复用仓库既有的单商品响应封装，但不得省略新的角色事实。
- 组不存在返回 404 `competitor_group_not_found`；商品不存在返回 404 `competitor_not_found`；商品不属于 path 中的组返回 400 `competitor_not_in_group`。
- 组尚无 own 时将目标设为 `own`。
- 目标已经是当前组 own 时幂等返回成功，不要求 `replace_existing` 为 true。
- 组已有另一个 own 且 `replace_existing = false` 时返回 409 `own_product_already_bound`。
- 组已有另一个 own 且 `replace_existing = true` 时，在同一数据库事务中将旧 own 改为 `competitor`、目标改为 `own`，然后提交。不得部分提交或出现事务完成后的中间状态；唯一索引冲突或其他失败须回滚并映射为稳定错误。
- `replace_existing` 默认为 false；类型不合法的请求体按现有 API 校验风格返回 422。

解除使用：

```text
DELETE /api/competitor-groups/{group_id}/own-product
```

- 若组存在且绑定 own，将其角色改为 `competitor`；不删除商品、任何历史数据或监控状态。
- 组存在但没有 own 时幂等成功，返回 204 No Content。
- 组不存在返回 404 `competitor_group_not_found`。
- 更新在单一事务内完成；失败返回稳定的业务错误，不泄露数据库异常。

### 3. 与既有商品操作的交互

- 新建商品仍默认 `group_role = competitor`。创建 API 不允许客户端指定 `own`。
- 既有 `PATCH /api/competitors/{id}/group` 仍只负责 `group_id`。普通组内 `competitor` 从 A 移到 B 后仍为 `competitor`。own 从 A 移到 B 后成为 B 组的 `competitor`；不会自动绑定为 B 的 own，也不会覆盖 B 已有 own。own 移至未分组时，同一事务同时写入 `group_id = NULL`、`group_role = competitor`。
- 若目标组已绑定 own，转入商品继续作为 competitor，目标组原 own 保持不变。
- 删除组时，在一个事务内先将所有成员写为 `group_id = NULL`、`group_role = competitor`，再删除组并提交。保留所有商品和快照、SKU 快照、变化事件、采集记录及监控状态。
- 删除 `group_role = own` 商品时按现有商品删除规则删除该商品及其关联历史。由于没有组到商品的反向引用，删除后组自然未绑定；无需额外组清理。
- 转组、解除角色、删组、绑定与更换均不得改动历史采集事实。采集服务继续按现有 `Competitor`、`is_active` 路径工作；不为 own 建立第二套采集逻辑。

### 4. Migration 与降级

- 新增下一条 Alembic migration，不修改任何历史 migration。增加字段、合法值与未分组角色约束、partial unique index；所有既有行显式置为 `competitor`，不按标题、店铺、组名、Offer ID、URL 或价格推断我方商品。
- 迁移保留现存 Competitor、Snapshot、SKU Snapshot、CollectionRun、ChangeEvent 数据，以及既有唯一约束、检查约束、外键和索引。按 SQLite/Alembic 现有 batch/table-rebuild 方式处理不能原位增加的约束；执行后不得遗留临时表。
- Downgrade 先检查是否存在 `group_role = 'own'`。若存在，明确拒绝并保留当前 schema 与数据，避免静默丢失真实角色语义。只有所有行均为 `competitor` 时，才允许删除本 migration 添加的 partial index、约束和字段。

### 5. Group Summary contract 与统计

- `GET /api/competitor-groups` 保持原有简单选项 contract（`id`、`name`、`created_at`），不得加入 own 商品字段。
- `GET /api/competitor-groups/summary` 的每个正式 group 增加 `own_product`，绑定时返回以下最小字段，未绑定时为 `null`：

```json
{
  "own_product": {
    "id": 123,
    "offer_id": "123456",
    "title": "A19 磁吸暖手宝",
    "shop_name": "我的店铺",
    "main_image_url": "...",
    "status": "active",
    "is_active": true
  }
}
```

- `own_product` 不含价格、起批量、SKU、库存或趋势数据；它仅服务于 Groups 页面绑定识别与管理。
- `competitor_count` 只计 `group_role = competitor`；`active_count` 只计 `group_role = competitor AND is_active = true`。
- 价格区间仅用直接竞品各自最新快照的有效价格计算，排除 own。
- `changed_competitors_today` 仅统计业务日内有事件的 distinct 直接竞品，不含 own。
- `last_change_at` 继续表达竞品组竞争变化总览，只取直接竞品事件最大时间。own 的变化不更新该字段；未来如需展示我方变化，在另行定义的 Group Detail 中处理。
- 正式组的摘要含 own 绑定状态；固定 `unassigned` 汇总不含 own 概念，未分组统计只涉及 `group_id IS NULL` 的直接竞品。
- 聚合仍使用固定数量的 SQL 查询或等价聚合，不得按组或商品形成 N+1。保持现有空值、金额与业务时区语义。

### 6. Competitor API contract

- `CompetitorResponse`、`CompetitorListResponse`、Competitor Detail 内嵌商品响应、Collect 响应内嵌 competitor 均暴露 `group_role`，取值为 `competitor` 或 `own`。
- 创建商品响应返回 `competitor`；绑定 API 响应返回更新后的 `own`。
- 前端通过正式角色字段识别商品，不得通过比较其 ID 与 Summary 的 `own_product.id` 推导角色。
- 收集、单条采集、批量采集仍按现有 `is_active` 处理 own 与 competitor；角色不改变 API 采集行为或响应的其余语义。

### 7. Frontend 管理与识别

- Groups 页面正式组卡片在既有指标卡片内增加克制的“我方商品”区域：显示真实商品标题；未绑定时显示“尚未绑定”。不重做卡片布局，不将未分组卡片作为分析组扩展。
- 每个正式组卡片的现有“更多”菜单：未绑定时提供“绑定我方商品”；已绑定时提供“更换我方商品”和“解除我方商品”。未分组卡片没有这些操作。
- 绑定 Dialog 只列出 `competitor.group_id = 当前 group.id` 的现有成员，包含任意商品状态和监控状态。每项至少显示 title、shop_name、offer_id、status、monitoring state；title 未采集时使用 offer_id 作为事实性 fallback。空成员时给出明确说明，不在 Dialog 创建商品。
- 首次绑定直接确认并调用 bind API；更换必须明确询问从商品 A 更换到商品 B。文案说明 A 留在该组成为普通竞品，历史监控数据不删除。确认后传 `replace_existing = true`。
- 解除操作需二次确认，说明该商品仍留组并成为普通竞品、继续按现有监控设置运行，历史不删除。失败时 Dialog 保持打开并展示错误；提交中禁用重复提交。
- Competitor List 仅对 `group_role = own` 显示“我方” Badge，不给全部普通商品添加“竞品”标签。Competitor Detail 在现有所属组信息附近显示角色（“我方商品”或“直接竞品”），本 Feature 不在详情页增加绑定入口。
- 成功的绑定、更换、解除、转组或删除操作刷新相应组摘要、商品列表和详情数据，沿用现有加载/错误处理模式；不增加全局状态层。

## Testing Decisions

测试验证数据库约束、事务完成后的外部 API 行为、摘要结果和用户可见状态，不绑定 SQL 拼接细节或组件内部实现。优先使用仓库现有 Alembic migration 测试、API 测试、Group Summary 测试以及 React 静态渲染/交互测试模式。

- Migration：旧 schema 升级、旧行均为 competitor；非法角色及 own + NULL group 被拒绝；同组第二个 own 被拒绝；不同组各有一个 own 合法；所有行为角色均为 competitor 时可安全降级；存在 own 时降级明确拒绝且数据未改；无临时表残留，并保留既有约束和历史数据。
- Bind：首次绑定成功；绑定当前 own 幂等；组/商品不存在；商品属于另一组；未请求替换时冲突及稳定错误码；显式替换后旧 own 为 competitor、新 own 为 own；强制事务失败时回滚后仍只有旧状态；并发写入不能留下两个 own。
- Unbind：解除后商品仍在组内且为 competitor，历史和监控状态保留；未绑定组幂等成功；不存在的组返回稳定 404。
- 组变更与删除：competitor A→B 保持 competitor；own A→未分组、own A→B 均变 competitor；目标组已有 own 时不静默覆盖；删组后全部成员未分组且角色为 competitor，历史保留；删除 own 商品后组摘要为未绑定且无悬空引用。
- Summary：own 不计入竞品数、监控数、价格区间、今日变化竞品数、最近竞品变化时间；绑定对象字段准确；未绑定组为 null；unassigned 无 own 概念。
- Frontend：组卡片绑定/未绑定状态、仅当前组候选、标题 fallback、更换与解除确认文案、API 失败保留 Dialog、重复提交保护、List own Badge、Detail 角色、未分组无绑定入口均符合 contract。

## Out of Scope

- Group Detail、我方与竞品价格比较、Group Intelligence API、7/30 天组分析、Dashboard 组级重构。
- AI、评分、建议、提醒、自动匹配或根据店铺、URL、标题识别我方商品。
- 多个 own、一个商品属于多个组、新建 OwnProduct 实体或多对多组成员关系。
- URL 添加流程重写、新采集逻辑或角色专属 Snapshot/采集链路。
- 在本 Feature 以外修改产品、数据模型、架构、UI 系统或 ChangeEvent V2 Spec 文档。

## Further Notes

- 本 Spec 扩展现有“竞品组 = 我方商品型号 + 多个直接竞品”的组语义：型号组仍由用户命名，但必须再绑定一个真实我方商品，才能具备真实比较基准。旧组不自动绑定，兼容升级状态为尚未绑定。
- 本 Feature 不要求改写历史事件中的组归属；摘要按当前 Competitor.group_id 和当前 group_role 计算，延续现有按当前关系呈现的规则。
- 成功标准：用户能从 Groups 页面显式维护唯一基准；DB 不变量在绕过前端时仍成立；所有组级竞品指标排除 own；转组、删除、采集和历史事实保持上述一致语义。
