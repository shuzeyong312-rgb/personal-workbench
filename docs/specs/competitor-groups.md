# 竞品分组 / 商品型号分组 Feature Spec

## Problem Statement

当前项目已经具备 `CompetitorGroup`、`Competitor.group_id`、新建竞品组 API、添加竞品时选择竞品组，以及竞品列表按竞品组筛选。但“竞品组”目前主要表现为普通文件夹，无法直接回答某个我方商品型号的竞品数量、监控状态、价格范围和近期变化。

本 Feature 将现有竞品组正式定义为“我店铺的一件目标商品型号”，并增加一个以商品型号为中心的竞品竞争总览页面。V1 只维护商品型号，不维护我方商品名称、链接、图片、售价或 SKU。

## Solution

继续复用现有 `CompetitorGroup` 与 `Competitor.group_id`：

- `CompetitorGroup.name` 就是我方商品型号，例如 `A19`、`X6`、`N09A`；页面原样显示，不添加“组”或“型号”后缀。
- 一个 `Competitor` 最多属于一个型号组；关系保持多对一，不改为多对多。
- `Competitor.group_id = null` 表示未分组。未分组是虚拟分类，不创建数据库行。
- 新增竞品分组总览页，使用现有 Personal Workbench 视觉体系和紧凑的型号卡片 Grid。
- 组卡片直接进入现有竞品列表页，并自动应用型号筛选；不新增组详情页。
- 继续使用现有创建接口；新增重命名和删除型号接口。
- 保留现有轻量组列表 API，另提供聚合 summary API，避免把统计字段耦合到 AddDialog 和 ListPage 的简单组选项 contract。

## User Stories

1. 作为个人工作台用户，我希望把一个竞品组理解为我方的一件目标商品型号，以便围绕型号比较直接竞品。
2. 作为用户，我希望看到所有已维护的商品型号，以便知道当前监控覆盖了哪些我方商品。
3. 作为用户，我希望每个型号卡片显示该组全部竞品数量，以便了解竞争样本规模。
4. 作为用户，我希望每个型号卡片显示其中正在监控的竞品数量，以便判断当前有效监控范围。
5. 作为用户，我希望看到某型号竞品最新有效价格的整体区间，以便快速比较市场价格。
6. 作为用户，我希望价格缺失时看到“暂无价格”，而不是被误导为零元或其他推测值。
7. 作为用户，我希望看到某型号今天发生变化的不同竞品数量，以便判断今天是否值得关注该型号。
8. 作为用户，我希望看到某型号最近一次变化时间，以便快速定位近期活跃型号。
9. 作为用户，我希望按最近变化时间查看型号，以便最近有变化的型号优先出现。
10. 作为用户，我希望没有变化记录的型号仍然显示，但排在有变化记录的型号之后。
11. 作为用户，我希望没有任何正式型号但存在未分组竞品时，仍能看到未分组卡片，而不是看到系统完全为空。
12. 作为用户，我希望查看未分组竞品，以便处理尚未归入商品型号的竞品。
13. 作为用户，我希望在没有型号且没有未分组竞品时看到明确空状态，并能直接创建商品型号。
14. 作为用户，我希望从页面顶部创建商品型号，以便先建立型号，再在添加竞品时选择它。
15. 作为用户，我希望创建时输入会被 trim、不能为空、最长 64 个字符且名称唯一，以便型号数据保持稳定。
16. 作为用户，我希望创建失败时看到“商品型号”语义的错误，而不是旧的“竞品组名称”文案。
17. 作为用户，我希望在 AddDialog 中看到“商品型号”“新建商品型号”和“输入商品型号，例如 A19”，以便 UI 语义与正式业务定义一致。
18. 作为用户，我希望点击某个型号卡片的“查看竞品”后直接进入现有竞品列表，并自动筛选该型号。
19. 作为用户，我希望点击未分组卡片后进入现有竞品列表，并自动筛选 `group_id = null`。
20. 作为用户，我希望切换到竞品列表时保留现有搜索、状态和采集状态筛选能力，不引入新的列表页面。
21. 作为用户，我希望通过“更多”重命名型号，以便修正型号名称而不影响竞品监控历史。
22. 作为用户，我希望重命名时仍受 trim、非空、64 字符和唯一性规则保护。
23. 作为用户，我希望删除型号时不会删除该型号下的竞品，以便历史监控资料不会丢失。
24. 作为用户，我希望删除型号前看到竞品数量和转入未分组的后果，以便危险操作可理解、可确认。
25. 作为用户，我希望删除空型号也能成功，以便清理不再使用的型号。
26. 作为用户，我希望删除型号后竞品进入未分组，并保留快照、SKU 快照、变化事件、采集记录和监控状态。
27. 作为用户，我希望删除型号后 Dashboard 的历史变化仍然存在，只是之后按当前关系显示为未分组。
28. 作为用户，我希望组管理操作不阻塞正在按竞品执行的采集任务，因为采集事实关联的是竞品而不是型号组。
29. 作为用户，我希望页面在 loading、error、empty 和正常状态下都给出清晰反馈。
30. 作为用户，我希望页面不展示示例数量、价格或时间，所有指标都来自真实数据库事实。
31. 作为用户，我希望只看到 V1 必需的“查看竞品”和“更多”操作，不被立即采集、批量删除、导出等未实现能力干扰。

## Implementation Decisions

### 1. 正式业务语义

- `CompetitorGroup` 的 V1 语义是“目标商品型号”。`CompetitorGroup.name = "A19"` 表示该组内的竞品都是我方 A19 商品的直接竞品。
- `name` 同时承担当前唯一的我方型号标识；V1 不增加 `OwnProduct`、`TargetProduct`、`ProductGroup` 或其他我方商品实体。
- 一个 `Competitor` 只能通过一个 nullable `group_id` 归属于一个型号组；不新增关联表，不做多对多。
- 型号显示值直接使用 `name`。不自动添加“商品”“型号”“组”等文字。

### 2. 数据模型与历史保留

- 继续使用现有 `CompetitorGroup.id/name/created_at`。
- 继续使用现有 `Competitor.group_id` nullable foreign key。
- 不新增表、字段、索引、migration 或第三方依赖。
- 不修改 `ProductSnapshot`、`SkuSnapshot`、`ChangeEvent`、`CollectionRun` 的结构或历史记录。
- 重命名只修改 `CompetitorGroup.name`。
- 删除型号只解除竞品归属，不删除任何 `Competitor` 或其历史监控事实。
- 删除后 Dashboard 通过当前 `Competitor.group_id = null` 将竞品显示为“未分组”；历史 `ChangeEvent` 本身不改写。

### 3. 名称校验与大小写

- 创建和重命名都执行 trim；trim 后不能为空；长度上限为 64；数据库唯一约束继续作为最终兜底。
- 不新增大小写 normalization，不把 `A19` 自动改写为 `a19` 或反之。
- 当前 SQLite 字符串唯一约束未声明 `NOCASE`，因此按当前数据库实际规则使用精确字符串唯一性；在当前规则下，`A19` 与 `a19` 可视为不同名称。实现不得额外改变这一行为。
- 任何 duplicate 都返回稳定业务错误，不把数据库完整性异常直接暴露给前端。

### 4. 未分组语义与 contract

- 未分组唯一由 `Competitor.group_id IS NULL` 表示。
- 不创建名为“未分组”的 `CompetitorGroup` 行，不分配虚拟 ID。
- Group Page 的未分组卡片显示竞品数量、监控中、价格区间、今日变化和最近变化，与正式型号卡片使用同一指标定义。
- Summary API 使用显式的 `unassigned` 对象，而不是返回 `id = null` 的伪型号，避免前端把虚拟分类误当成真实数据库实体。

### 5. Group Page 信息架构

页面使用现有 `PageHeader`、Breadcrumb、白色/近白卡片、浅蓝紫雾感背景、轻阴影和中等圆角。

结构固定为：

```text
PageHeader
  标题：竞品分组
  说明：按我方商品型号管理对应竞品。
  主要操作：新建商品型号
↓
商品型号卡片 Grid（桌面端 2～3 列）
```

每张卡片包含：

- 型号名称；
- 竞品数量；
- 监控中数量；
- 竞品价格区间；
- 今日变化竞品数；
- 最近变化时间；
- `查看竞品`；
- `更多`，仅包含重命名型号、删除型号。

卡片是管理与总览的混合视图，不使用传统“名称 / 数量 / 创建时间 / 操作” CRUD 表格，不做 Masonry，不做大面积彩色卡，不把五项指标做成五个大型 StatCard。

### 6. Group Summary API

保留现有：

```text
GET /api/competitor-groups
```

其 contract 继续只返回简单组字段：`id`、`name`、`created_at`。AddDialog 和 ListPage 的组选项继续使用该 contract，默认顺序保持当前 `created_at ASC, id ASC`。

新增：

```text
GET /api/competitor-groups/summary
```

推荐响应 contract：

```json
{
  "groups": [
    {
      "id": 1,
      "name": "A19",
      "created_at": "2026-09-20T10:00:00Z",
      "competitor_count": 6,
      "active_count": 6,
      "price_min": "34.00",
      "price_max": "40.00",
      "changed_competitors_today": 2,
      "last_change_at": "2026-09-21T02:35:00Z"
    }
  ],
  "unassigned": {
    "competitor_count": 0,
    "active_count": 0,
    "price_min": null,
    "price_max": null,
    "changed_competitors_today": 0,
    "last_change_at": null
  }
}
```

`groups` 中每个对象包含型号本身和聚合指标；`unassigned` 是固定存在的 summary 对象，即使全部为 0 也不创建数据库行。这样既不改变原有简单组选项 contract，也不为了 REST 理论把每项指标拆成多个接口。

Summary API 的默认排序为：

1. `last_change_at DESC`；
2. 没有变化记录的型号排在所有有变化记录的型号之后；
3. 同一 `last_change_at` 下按 `created_at ASC`；
4. 再按 `id ASC` 保证稳定顺序。

未分组卡片不参与正式型号排序，固定显示在正式型号卡片之后；如果产品需要“最近变化”统一排序，后续另行决定，不在 V1 增加复杂排序参数。

### 7. 指标计算

#### 竞品数量

统计当前 `Competitor.group_id = group.id` 的全部竞品，包含 `is_active = true` 和 `is_active = false`。未分组统计 `group_id IS NULL` 的全部竞品。

#### 监控中

统计当前组内 `Competitor.is_active = true` 的竞品数量。未分组按同样规则统计。

#### 竞品价格区间

- 每个竞品只取其最新一条 `ProductSnapshot`，排序依据为 `captured_at DESC, id DESC`。
- 只使用这条最新快照中的非 null `price_min` 和非 null `price_max`；不混算该竞品的历史快照。
- 在组内所有竞品的有效价格值中取整体最小值和整体最大值。
- `price_min` 或 `price_max` 为 null 时，忽略该值；一侧有值时使用该值作为唯一有效价格。
- 最终没有任何有效价格时，API 返回 `price_min = null`、`price_max = null`，前端显示“暂无价格”，不得显示 `¥0`。
- 只有一个有效价格时，API 的上下界使用相同值，前端显示单个金额，例如 `¥39.00`；有不同上下界时显示 `¥34.00 ~ ¥40.00`。
- 金额使用当前 API 的字符串金额表示和两位小数格式，避免浮点展示误差。
- 不因为 `product_status` 是 offline 就虚构价格，也不从旧快照回填当前快照缺失的价格。

#### 今日变化

- 复用当前 Dashboard 的 Asia/Shanghai 业务日边界；若系统时区数据不可用，继续回退到固定 UTC+8。
- 在当前业务日区间内，按 `ChangeEvent.detected_at` 筛选。
- 统计当前属于该组的 `distinct ChangeEvent.competitor_id` 数量，而不是事件条数。
- V1 Group Summary 不按 `is_active` 过滤；停止监控但仍属于该组的竞品，其当天已有变化事件仍计入该组。
- 未分组按当前 `group_id IS NULL` 的竞品执行同样统计。

#### 最近变化

- 取当前组内竞品关联的 `MAX(ChangeEvent.detected_at)`。
- 没有变化记录时返回 `null`，前端显示“暂无变化”。
- 只修改型号名称不产生 ChangeEvent。

### 8. 查询与性能

- Summary 必须通过聚合查询完成，使用窗口子查询或等价方式先得到每个竞品的最新快照，再按组聚合。
- 今日 distinct 计数和最近变化使用 SQL 聚合，不允许按组逐个查询竞品、快照和事件形成明显 N+1。
- 组规模目前较小，不引入缓存、Redis、物化视图或后台汇总任务。
- 允许为正式型号集合和未分组集合使用固定数量的查询，但不允许查询次数随组数或竞品数线性增长。

### 9. 创建商品型号

页面顶部按钮打开现有 Dialog 风格的创建 Dialog：

- 标题：新建商品型号；
- 字段标签：商品型号；
- placeholder：例如：A19、X6、N09A；
- 提交继续调用 `POST /api/competitor-groups`；
- 请求字段仍为技术字段 `name`，不重命名数据库字段；
- 成功后关闭 Dialog、刷新 summary 和简单 groups 数据，并显示成功反馈；
- 创建操作不自动创建或移动竞品。

创建错误文案使用“商品型号”：

- 空白或超过 64：请输入有效的商品型号；
- duplicate：该商品型号已存在；
- 服务错误：商品型号创建失败，请稍后重试。

### 10. AddDialog 文案同步

只同步用户可见文案和反馈，不改技术字段：

| 当前文案 | V1 正式文案 |
| --- | --- |
| 竞品组 | 商品型号 |
| 新建分组 | 新建商品型号 |
| 输入分组名称 | 输入商品型号，例如 A19 |
| 分组已创建并已选中 | 商品型号已创建并已选中 |
| 请输入有效的分组名称 | 请输入有效的商品型号 |
| 该分组已存在 | 该商品型号已存在 |

底层请求继续使用 `group_id`，`CompetitorGroup`、`group` 等内部技术名称不做无意义重构。

### 11. 重命名型号

新增：

```text
PATCH /api/competitor-groups/{id}
Content-Type: application/json

{
  "name": "A19 Pro"
}
```

响应返回更新后的简单组对象：`id`、`name`、`created_at`。

规则：

- 目标组不存在：404，错误码 `competitor_group_not_found`；
- trim 后为空或超过 64：400，错误码 `invalid_competitor_group_name`；
- 与其他组重复：409，错误码 `competitor_group_already_exists`；
- 成功只更新组名和必要的 ORM 状态，不修改任何竞品、快照、变化事件或采集记录；
- 成功后 Group Page 刷新 summary 和简单 groups 数据；
- 竞品列表在下次渲染时通过同一组 ID 使用新名称。

### 12. 删除型号

新增：

```text
DELETE /api/competitor-groups/{id}
```

成功返回 204 No Content。目标组不存在返回 404，错误码 `competitor_group_not_found`；其他未预期失败返回稳定的 `competitor_group_delete_failed`，不泄露数据库异常细节。

删除必须在一个数据库事务中明确执行：

1. 将目标组下所有 `Competitor.group_id` 更新为 `NULL`；
2. 删除目标 `CompetitorGroup`；
3. 一次性 commit；
4. 任意失败都 rollback。

不得依赖 SQLite 恰好允许的 foreign key 行为，也不得先提交解除关系再单独删除组。空组同样允许删除。

前端使用现有 Dialog 风格，不使用 `window.confirm()`。确认文案包含型号名称和竞品数量：

```text
删除商品型号“A19”？
该型号下有 3 个竞品。
删除后：3 个竞品将移至“未分组”，竞品及历史监控数据不会删除。
```

空组时省略或改为“该型号下暂无竞品”，仍显示取消和删除型号按钮。提交中禁止重复提交，失败保留 Dialog 和错误信息。

### 13. 采集任务与锁

当前采集流程按 `competitor_id` 查询竞品，读取 URL、监控状态和采集相关字段，不读取 `group_id`。ChangeEvent、ProductSnapshot、SkuSnapshot 和 CollectionRun 也通过 `competitor_id` 关联。

因此：

- 创建、重命名、删除型号原则上不接入 `COLLECTION_LOCK`；
- 删除组不会改变竞品的采集目标或历史记录；
- 组 CRUD 仍必须使用正常数据库事务；
- Summary 在事务提交前后最多看到一致的旧状态或新状态，不需要额外锁；
- 如果未来采集流程开始依赖 `group_id`，应在另一个 Feature 中重新评估竞态和锁边界，不在本 V1 预留。

### 14. Group Page 到 ListPage 的自动筛选

不引入 React Router、query router、URL 大改或 localStorage。沿用当前 App 层集中保存页面状态的方式：

- 扩展现有 Page union，增加 `groups` 页面值；
- App 层增加一次性导航意图 `initialGroupFilter`，值为具体 group ID、`"unassigned"` 或空值；
- Group Page 的“查看竞品”调用 App 导航回调，写入意图并切换到 `competitors`；
- ListPage 接收 `initialGroupFilter`，在进入/消费该导航意图时把现有本地 `filters.groupId` 设置为该值；
- 具体型号使用 group ID，未分组使用现有的 `"unassigned"`，不创建虚拟 ID；
- 普通 Sidebar 进入竞品列表时清空导航意图，保持现有默认筛选行为；
- ListPage 继续复用现有本地筛选，不增加服务端筛选 API。

进入结果必须是现有竞品列表页面，筛选下拉显示当前型号名或“未分组”，只展示对应竞品。

### 15. Navigation

启用现有 Sidebar 中的“竞品分组”入口，不改 Sidebar 整体层级：

```text
竞品监控大屏
竞品列表
竞品分组
采集记录（仍 disabled）
```

`groups` 页面进入时高亮“竞品分组”。Group Page 的 Breadcrumb 使用“个人工作台 / 竞品监控 / 竞品分组”。

### 16. 空状态、异常与真实数据

- Loading：显示页面加载状态，不显示假卡片数据。
- Error：显示明确错误和重试入口；不把请求失败当成空数据。
- 无正式组且无未分组竞品：显示“还没有商品型号”，说明创建型号后可将对应竞品归入同组，并提供“新建商品型号”。
- 无正式组但有未分组竞品：显示未分组卡片，不显示系统完全为空。
- 有正式组但无竞品：显示真实的 0 指标；价格为“暂无价格”，最近变化为“暂无变化”。
- 所有数量、价格和时间必须来自 summary API 或现有运行时数据，不写死示例数据，不用前端推断或缓存补齐缺失事实。

### 17. 长期文档最小同步计划

本轮不修改长期文档。正式实现完成后只做必要同步：

- `docs/data-model.md`：补充 CompetitorGroup 的“目标商品型号”语义、未分组的 nullable 表示、删除组的解除关系事务和历史数据保留规则。
- `docs/product.md`：将竞品组管理描述更新为商品型号竞争总览，并记录创建、重命名、删除后的业务行为。
- `docs/ui-system.md`：确认“竞品分组”导航已启用，并补充 Group Page 复用总览型页面骨架、紧凑卡片 Grid 和未分组空状态的最小规则。

不在上述文档中新增独立的我方商品实体，也不把页面示例数据写成业务事实。

## Testing Decisions

本轮不新增或修改测试。正式实现时，测试应只验证外部行为和真实数据语义，不绑定某个 SQL 拼接或组件内部实现。

### Backend 行为

- 创建型号：trim、空白、长度上限、duplicate、稳定错误码和响应字段。
- Summary：正式组和未分组都能返回真实数量；active 计数只计算 `is_active = true`；没有组时仍返回 `unassigned`。
- Summary 价格：只取每个竞品最新快照；忽略 null；单值、无值和上下界均正确；不混算历史快照。
- Summary 今日变化：Asia/Shanghai / UTC+8 fallback、distinct competitor 数量、跨多个事件去重、已停止监控竞品的计数语义。
- Summary 最近变化：取当前关系下的最大 `detected_at`，无记录返回 null。
- 重命名：成功、404、校验失败、duplicate，并确认历史关联不变。
- 删除：空组和有竞品组均成功；组内竞品变为 null；竞品及所有历史事实保留；事务失败 rollback；删除不存在组返回稳定 404。
- 采集隔离：组重命名/删除不改变按 `competitor_id` 运行的采集行为，也不需要取得 `COLLECTION_LOCK`。

### Frontend 行为

- Group Page loading、error、两类 empty state、正常卡片和重试。
- 卡片只渲染 summary 返回的数据；价格和变化缺失时显示约定空值文案。
- 创建、重命名和删除 Dialog 的提交中、成功、失败和重复提交保护。
- 删除确认文案包含真实型号名和真实竞品数量。
- 点击正式型号和未分组卡片都进入现有 ListPage，并分别传递 group ID 或 `unassigned` 初始筛选。
- 进入 Group Page 后 Sidebar 正确高亮；采集记录仍保持 disabled。
- AddDialog 文案同步后仍使用 `group_id` 提交，且简单 groups contract 未被 summary 字段耦合。

### 现有测试先例

后续实现应沿用当前后端 API 的 TestClient + 临时 SQLite 数据库模式、数据库约束测试、Dashboard 已有的业务日边界测试，以及当前前端对纯筛选函数和静态渲染行为的测试方式。除非外部行为变化确实要求，否则不为一次性内部 helper 建立单独测试套件。

## Out of Scope

V1 明确不做：

- 我方商品表、商品名称字段、商品链接、商品图片、售价或 SKU；
- 京东商品同步、1688 自营商品同步；
- 多对多竞品关系；
- Group Detail Page；
- Group 内独立竞品表；
- 多层分组、父子分组、标签系统；
- 拖拽排序、合并组、复制组；
- 导出、批量删除竞品、分组级批量采集；
- 分组级自动采集策略、停止全部监控、立即采集；
- 新数据库表、新字段、新 migration、新第三方依赖；
- 缓存、Redis、物化视图、后台 summary 任务；
- URL routing 大重构、React Router、localStorage 导航传值；
- 用户自定义排序、复杂拖拽布局、Masonry；
- 修改历史 ChangeEvent、Snapshot、SkuSnapshot 或 CollectionRun；
- 本轮任何 Backend、Frontend、数据库、API、CSS、测试、commit 或 push。

## Further Notes

- 推荐采用新增 `GET /api/competitor-groups/summary`，而不是扩展现有 `GET /api/competitor-groups`。理由是现有简单组 contract 已被 AddDialog 和 List filters 直接复用；summary 是 Group Page 的独立聚合读取场景，分离后耦合更低，仍只保留一个聚合接口。
- 推荐默认排序采用“最近变化 DESC，无变化置后，创建时间/id 稳定兜底”。Group Page 的核心任务是竞争变化总览，最近变化比自然名称排序更有业务价值；不增加拖拽排序来解决位置稳定问题。
- 本 Spec 已冻结未分组 contract、价格和今日变化口径、重命名/删除 API、事务语义、导航意图和大小写规则，没有阻塞性产品决策需要额外确认。
- 实现前仍需按仓库现状确认 API schema 和前端类型变更范围；这属于实现核对，不是新的产品决策。
