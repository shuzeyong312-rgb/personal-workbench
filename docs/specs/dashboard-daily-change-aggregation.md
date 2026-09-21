# Dashboard 今日变化竞品级聚合

## Problem Statement

Dashboard 的“今日发生变化的竞品”当前在 Backend 中虽已按 `competitor_id` 组织 `items`，但每个 `ChangeEvent` 仍作为 Frontend 表格的一行展示。一个竞品在同一 Asia/Shanghai 业务日内发生多个事件时，会出现多行相同商品；多个 SKU 的库存事件尤其容易被误读为重复商品。

当前页面还把“今日共 X 条变化”作为事件数显示，而表格视觉上又像竞品列表，造成列表粒度与统计口径不一致。ChangeEvent 本身是事实级事件，没有业务错误；需要调整的是 Dashboard 的展示聚合层。

现状数据事实：

- `ChangeEvent` 支持 `price_increase`、`price_decrease`、`sku_added`、`sku_removed`、`stock_changed`、`title_changed`。
- 商品级事件的 `entity_key` 为 `NULL`；SKU 级事件的 `entity_key` 保存 `sku_id`。
- `ChangeEvent.snapshot_id` 指向产生该事件的当前 `ProductSnapshot`；该快照下的 `SkuSnapshot` 保存同一 SKU 的 `sku_name`。
- `Competitor.group_id` 是当前竞品组关系；不保存事件发生时的历史分组快照。
- 详情页已经提供完整的 `recent_changes`，因此 Dashboard 不需要成为事件明细页。

## Solution

Dashboard 今日变化区域正式定义为：

> 一行一个当前仍在监控的 `Competitor`，回答“今天哪些竞品发生了什么变化”。

同一竞品当天的全部 ChangeEvent 由 Backend 在展示查询中聚合为一个 Dashboard item。ChangeEvent 仍按原语义逐条保存，详情页继续展示完整事件明细。

Dashboard 同时明确两个计数：

- `competitor_count`：今日发生至少一个 ChangeEvent 的 distinct active competitor 数量。现有顶层字段继续命名为 `stats.changed_competitors`。
- `event_count`：今日符合范围的 ChangeEvent 总条数，重复竞品、重复 SKU、同一 SKU 多次变化均逐条计数。现有顶层字段继续命名为 `stats.change_events`。

区域统计文案使用两种口径，例如：`5 个竞品发生 9 条变化`。不得把 9 条事件改成 5 条变化。

## User Stories

1. 作为运营人员，我希望今日变化区域一行只显示一个竞品，以便快速知道哪些竞品发生了变化。
2. 作为运营人员，我希望同一竞品当天多个事件被聚合，而不是看到重复商品行。
3. 作为运营人员，我希望看到一个竞品当天发生了多少条真实事件，以便区分竞品数和事件数。
4. 作为运营人员，我希望看到一个竞品涉及的变化类型，以便快速识别变价、库存、SKU 或标题变化。
5. 作为运营人员，我希望单个库存事件能显示 SKU 名称和库存前后值，以便知道具体哪个 SKU 变化。
6. 作为运营人员，我希望多个 SKU 的库存事件只占一行并显示受影响 SKU 数量，以便避免展开过多细节。
7. 作为运营人员，我希望同一 SKU 一天多次库存变化仍按多条事件统计，但受影响 SKU 数量只计一个 SKU。
8. 作为运营人员，我希望多个变化类型同时发生时不隐藏低优先级类型。
9. 作为运营人员，我希望价格变化在同日多次发生时展示最近一次真实价格变化。
10. 作为运营人员，我希望价格区间或无可靠数值时不看到伪造的百分比。
11. 作为运营人员，我希望百分比只表达选定主要变化本身，不把多个 SKU 的库存百分比平均或合并。
12. 作为运营人员，我希望变化时间表示该竞品当天最近一次变化时间。
13. 作为运营人员，我希望看到竞品当前所属竞品组，而不是某个历史事件发生时的分组。
14. 作为运营人员，我希望点击“查看详情”进入现有竞品详情页查看完整事件明细。
15. 作为运营人员，我希望当天没有事件时仍看到现有“今日暂无竞品变化”空状态。
16. 作为运营人员，我希望顶部 KPI 继续表示 distinct competitor 口径，不因列表聚合而改变。
17. 作为运营人员，我希望 7 天趋势继续表示每天真实监控事件数量，以便观察采集变化量。
18. 作为维护者，我希望 Frontend 不再从原始事件列表猜测竞品归属或完成核心聚合。
19. 作为维护者，我希望 ChangeEvent 事实数据不因 Dashboard 展示需求被合并、删除或改写。
20. 作为维护者，我希望查询不对每个竞品逐个查询事件或 SKU，避免明显 N+1。

## Implementation Decisions

### 1. 聚合边界与查询范围

- 继续使用 `GET /api/dashboard/today`，不新增 `/api/dashboard/changes`。
- 继续按 Asia/Shanghai 业务日使用左闭右开区间 `[start_utc, end_utc)`。
- 只纳入 `Competitor.is_active = true` 且 `ChangeEvent.detected_at` 位于今日业务日的事件。
- Collection failure 不是 ChangeEvent，不进入今日变化 items；失败采集继续由现有 KPI、`collection_summary` 和 `trend_7d` 表达。
- Backend 在一个聚合 seam 内完成事件读取、竞品关联、类型/计数/主要事件/最新时间计算。允许一次事件查询加一次批量 SKU 名称查询，但禁止按竞品或事件逐个查询。
- Dashboard 不缓存，不新增后台任务，不引入 Redis。

### 2. API contract

保留响应顶层结构：

```text
{
  date,
  stats,
  items,
  collection_summary,
  trend_7d
}
```

`stats` 的既有字段和语义保持不变：

- `monitored_competitors`：当前 `is_active = true` 的竞品数；
- `changed_competitors`：今日发生事件的 distinct active competitor 数，即本区域的 `competitor_count`；
- `change_events`：今日事件总数，即本区域的 `event_count`；
- `price_changed_competitors`：至少一个价格事件的 distinct active competitor 数；
- `stock_changed_competitors`：至少一个 `stock_changed` 事件的 distinct active competitor 数；
- `sku_changed_competitors`：至少一个 `sku_added` 或 `sku_removed` 事件的 distinct active competitor 数；
- `failed_collections`：今日业务日内失败 `CollectionRun` 次数。

本 Feature 替换 `items` 的当前事件展开 contract。每个 item 返回：

```text
{
  competitor_id,
  title,
  shop_name,
  main_image_url,
  group_id,
  last_collected_at,

  change_count,
  change_types,
  latest_change_at,
  primary_change,

  stock_changed_sku_count,
  sku_added_count,
  sku_removed_count
}
```

字段规则：

- `change_count`：该竞品今日全部 ChangeEvent 条数；
- `change_types`：该竞品今日出现的 distinct 原始 `change_type` 值，不重复；不返回事件数组。按“价格、库存、SKU、标题”的稳定优先级排列，同一优先级按最近事件优先；
- `latest_change_at`：该竞品今日所有事件的 `max(detected_at)`；同时间不影响时间值，事件排序 tie-break 使用事件 `id DESC`；
- `primary_change`：主要摘要使用的一个事件投影，或无事件时为 `null`。包含 `id`、`change_type`、`entity_key`、`sku_name`、`old_value`、`new_value`、`detected_at`；`sku_name` 对商品级事件为 `null`；
- `stock_changed_sku_count`：有库存事件时按非空 `entity_key` 的 distinct SKU ID 计数；无库存事件时为 `0`；如果历史数据中存在库存事件但缺少可靠 `entity_key`，返回 `null`，不得伪造数量；
- `sku_added_count`：今日 `sku_added` 事件条数；
- `sku_removed_count`：今日 `sku_removed` 事件条数；
- `title`、`shop_name`、`main_image_url`、`last_collected_at` 继续读取当前 `Competitor`；
- `group_id` 继续读取当前 `Competitor.group_id`，不建立历史分组字段；竞品组名称继续由已有竞品组数据映射，Dashboard API 不为本 Feature 新增 `group_name`。

`items` 不再返回 `changes: [...]` 给 Dashboard。完整事件仍由现有竞品详情 API 的 `recent_changes` 提供；Frontend 不得从事件数组重新 group、reduce 或自行决定主要事件。

这是同一 endpoint 内的明确 item contract 替换，不新增版本路由或第二套 Dashboard API。由于当前仓库由现有 Frontend 与 Backend 一起演进，按新 contract 同步更新类型、渲染和测试即可。

### 3. SKU 名称的可靠性约束

- `entity_key` 对库存事件的正式含义是 `sku_id`，不是人类可读 SKU 名称，Frontend 不得直接把它当作 SKU 名展示名称。
- Backend 通过 `ChangeEvent.snapshot_id` 对应的 `ProductSnapshot`，批量匹配该快照下 `SkuSnapshot.sku_id = entity_key`，恢复 `sku_name`。
- 若匹配到名称，单 SKU 摘要使用 `sku_name`；若匹配不到，保留 `sku_name = null`，UI 只能显示事实性回退（例如 `SKU ID：{entity_key}`），不得臆造规格名称。
- `sku_added` / `sku_removed` 的名称继续使用事件已有的 `new_value` / `old_value`；这不改变 ChangeEvent 事实层。
- 本 Feature 不新增 SKU 表字段、不改变 `entity_key` 语义、不为 Dashboard 保存额外 SKU 快照。

### 4. 同一竞品的聚合规则

- 先按 `competitor_id` 聚合今日事件，因此任意数量事件只产生一个 item。
- `change_count` 计所有事件，不按类型、SKU 或时间去重。
- `change_types` 去重但不丢失类型。`price_increase` 与 `price_decrease` 可以同时存在；`sku_added` 与 `sku_removed` 也可以同时存在。
- UI badge 将同一大类只显示一次：两种价格事件显示一个“变价” badge，`stock_changed` 显示一个“库存变化” badge，任一 SKU 增删事件显示一个“SKU变化” badge，`title_changed` 显示一个“标题变化” badge。这个映射只负责显示，不承担事件聚合。
- 同一个竞品既有价格、库存、SKU、标题事件时，所有相应 badge 都必须显示；主要摘要只选择一个事件，不能隐藏其它事实。

### 5. `primary_change` 规则

事件优先级固定为：

1. `price_increase` / `price_decrease`；
2. `stock_changed`；
3. `sku_added` / `sku_removed`；
4. `title_changed`。

在同一优先级内选择 `detected_at DESC, id DESC` 的最近事件。因而价格事件即使早于库存事件，只要当天存在价格事件，价格仍是主要摘要；时间列仍显示竞品的最新事件时间。

`primary_change` 的选择在 Backend 完成。Frontend 只格式化它，不从多个事件推断“最重要的一条”。

### 6. 库存变化

#### 单个库存事件

当竞品当天只有一个 `stock_changed` 事件，且它是 `primary_change` 时：

- `stock_changed_sku_count` 为 `1`；
- 有可靠 `sku_name` 时，变化摘要显示“`{sku_name} {old_value} → {new_value}`”；
- 无名称但有 `entity_key` 时，显示“`SKU ID：{entity_key} {old_value} → {new_value}`”；
- old/new 是真实库存字符串；`0` 必须保留为 0，`null` 或缺失不改写成 0。

#### 多个库存事件

当竞品当天有两个或更多 `stock_changed` 事件时，不论这些事件属于同一 SKU 还是不同 SKU：

- 仍只有一个 Dashboard row；
- `change_count` 保留全部事件数；
- `stock_changed_sku_count` 统计受影响的 distinct SKU 数；
- 变化摘要显示“库存变化 · `{X}` 个 SKU 发生变化”；`X` 为可靠数量时使用该数，无法可靠识别时显示未知态；
- 不在 Dashboard 展开全部 SKU，不把多个库存值合并成一个 old/new；
- 完整的每次库存变化进入现有竞品详情页“最近变化”。

因此，同一 SKU 的 `100 → 90`、`90 → 80` 是 2 条事件、1 个受影响 SKU；两个 SKU 各发生一次则是 2 条事件、2 个受影响 SKU。

### 7. 价格变化

- 有价格事件时，价格优先成为 `primary_change`。
- 同一竞品当天有多个价格事件时，选择最近一次事件，展示该事件的 `old_value → new_value`，不合并成当天第一笔到最后一笔，也不由 Frontend 自行选择。
- 单值价格且 old/new 均为可靠数字、old 不为 0 时，变化幅度按现有价格百分比规则计算；价格下降显示 `↓x.x%`，价格上涨显示 `↑x.x%`。
- 价格范围（例如 `40.00~50.00`）不计算统一百分比，显示 `—`；缺失、非数值或 old 为 0 同样显示 `—`。
- 不新增价格计算算法，不把价格区间强行平均为单值。

### 8. SKU 新增 / 移除

- `sku_added_count` 和 `sku_removed_count` 分别统计对应事件条数。
- 只有新增时摘要为“新增 `{X}` 个 SKU”，只有移除时为“移除 `{X}` 个 SKU”，同时存在时为“新增 `{X}` 个 SKU，移除 `{Y}` 个 SKU”。
- 这两类事件只归入“SKU变化” badge，不归入“库存变化”。
- SKU 名称明细不在 Dashboard 一次展开；详情页保留完整事件。

### 9. 标题变化

- `title_changed` 只归入“标题变化” badge。
- 当没有价格、库存或 SKU 事件时，标题变化可以成为主要摘要，显示“标题变化”。
- 标题变化不抢过价格、库存或 SKU 的主要摘要；旧标题、新标题事实仍保留在 ChangeEvent 和详情页。

### 10. 变化幅度

- 幅度只针对 `primary_change` 表达，不对所有事件求平均。
- 价格事件按单值价格规则计算。
- 只有竞品当天恰有一个库存事件时，才可对该单个库存事件按 old/new 计算百分比；多个库存事件（即使都属于同一 SKU）不显示库存百分比。
- 多 SKU 库存变化不计算总库存百分比、平均百分比或其它聚合百分比，显示 `—`。
- SKU、标题及无法可靠计算的情况显示 `—`。

### 11. 排序与时间

- Backend 返回 `items` 按 `latest_change_at DESC` 排序。
- `latest_change_at` 相同时按 `competitor_id DESC` 稳定排序。
- Frontend 不再次按事件时间排序、不截取前 N 条、不改变 Backend 顺序；V1 不新增分页。
- 当前实现的事件行上限不保留为聚合后的竞品上限；今日返回并展示全部符合范围的竞品 item，避免统计文案与列表内容再次不一致。

### 12. Dashboard 表格

保留现有 Dashboard 结构和视觉体系，只替换今日变化表格的业务字段。最终列为：

| 列 | 内容 |
| --- | --- |
| 商品信息 | 主图、当前商品标题、店铺名称 |
| 变化类型 | 一个或多个已有 `change-type-badge` 视觉体系的 badge |
| 变化摘要 | Backend 选出的 `primary_change` 或 SKU/事件计数摘要 |
| 变化幅度 | 可靠时显示 `↑x.x%` / `↓x.x%`，否则 `—` |
| 变化时间 | `latest_change_at`，即该竞品当天最近一次事件时间 |
| 竞品组 | 当前 `group_id` 对应的已有竞品组名称，空值显示“未分组” |
| 操作 | 现有“查看详情”，进入现有竞品详情页 |

顶部统计文案为“`{competitor_count} 个竞品发生 {event_count} 条变化”。

当天无事件继续显示现有 Empty State“今日暂无竞品变化”；loading、error/retry、采集概览、趋势和快捷入口不因本 Feature 改变。

### 13. KPI 与 7 天趋势兼容性

- 四个 Dashboard KPI 不改变：今日变价竞品、今日库存变化竞品、今日 SKU 变化竞品仍是 distinct active competitor 口径，异常采集仍是失败 `CollectionRun` 次数。
- `stats.changed_competitors` 继续是 distinct active competitor 数；它不改名为事件数。
- `stats.change_events` 继续是事件总数。
- `trend_7d` 保持现有连续 7 个 Asia/Shanghai 业务日和事件级计数：`price_changes`、`stock_changes`、`sku_changes` 是 ChangeEvent 条数，`failed_collections` 是失败采集次数。
- 列表与趋势采用不同口径是有意设计：列表回答“哪些竞品发生了什么”，趋势回答“每天发生多少监控事件”。

### 14. Timezone

- “今日”继续使用 `Asia/Shanghai` 业务日。
- 时区数据库不可用时继续回退固定 UTC+8。
- 边界使用 `[local day start, next local day start)` 转换后的 UTC 半开区间；恰好落在开始边界的事件属于当天，恰好落在结束边界的事件属于下一天。
- API 的 `date`、`latest_change_at` 和趋势日期继续沿用现有响应时间格式，不在 Frontend 重新推断业务日。

### 15. 文档同步

实现完成后，需同步以下长期文档：

- `docs/product.md`：说明 Dashboard 今日变化为竞品级聚合，事件数与竞品数同时呈现；
- `docs/architecture.md`：说明 Dashboard 聚合 seam 在 Backend，Frontend 只展示；
- `docs/data-model.md`：明确 ChangeEvent 仍是逐条事实、无数据库合并，SKU ID/名称边界保持不变；
- `docs/ui-system.md`：说明 Dashboard 今日变化的竞品级行粒度、badge、摘要和现有详情入口。

本轮只创建本 Spec，不同步修改上述长期文档。

## Testing Decisions

测试只验证外部 contract 和用户可见行为，不测试某个内部循环或具体 SQL 写法。优先复用现有 Backend TestClient + 临时 SQLite 模式、现有 Asia/Shanghai 边界测试，以及 Frontend 的 Vitest `renderToStaticMarkup` 和纯 formatter 测试方式。

### Backend tests

至少覆盖：

1. 一个 active competitor 一个 event：返回一个 item、`change_count = 1`、一个 type、正确 primary 和 latest time。
2. 一个 competitor 两个 `stock_changed`：仍一个 item，event count 为 2，不重复商品。
3. 两个 competitor 各有 event：返回两个 item，分别聚合。
4. 同 competitor 多种 change type：所有类型保留，`change_types` 去重，badge 所需事实不丢失。
5. 同一 SKU 多个库存事件：事件数逐条计数，`stock_changed_sku_count = 1`，primary 为该优先级内最近库存事件。
6. 不同 SKU 多个库存事件：事件数逐条计数，受影响 SKU 数为 distinct SKU 数。
7. 多个价格事件：primary 选择最近一次价格事件，不合并第一笔和最后一笔。
8. `latest_change_at`：返回所有事件 `detected_at` 的最大值，而不是 primary 事件时间或第一笔时间。
9. `change_count`：价格、库存、SKU、标题事件全部计入总事件数。
10. `change_types` 去重：同一类型多事件只返回一个原始类型值，同时价格增减、SKU 增删的不同方向不互相覆盖。
11. 排序：按 `latest_change_at DESC`，同时间按 `competitor_id DESC`，结果稳定。
12. Asia/Shanghai today boundary：开始边界包含、结束边界不包含，昨日事件不进入当天聚合。
13. 无 event：`items = []`、现有空状态所需统计为 0，其他 Dashboard 数据仍正常返回。
14. KPI semantics：同一竞品多个同类事件只在 KPI distinct competitor 计一次，跨竞品正确计数，inactive competitor 不计入。
15. `trend_7d semantics`：趋势继续按每天 ChangeEvent 条数和失败 CollectionRun 次数计数，不改成 competitor count。
16. SKU 名称恢复：库存事件通过 `snapshot_id + entity_key` 得到 `SkuSnapshot.sku_name`；名称缺失时返回 `null`，不把 SKU ID写成名称。
17. stock count unknown：库存事件缺少可靠 `entity_key` 时不伪造受影响 SKU 数。
18. current group：item 使用当前 `Competitor.group_id`，不从事件或历史快照生成分组快照。

### Frontend tests

使用竞品级聚合 item fixture，不在测试中提供原始 ChangeEvent 数组让 Frontend 聚合。至少覆盖：

1. 同一 competitor 只渲染一个 row。
2. 多个 stock event 的聚合 item 只渲染一个 row。
3. 单 SKU 变化摘要显示可靠 SKU 名称和 old/new。
4. 多 SKU 变化显示“X 个 SKU 发生变化”，不展开全部 SKU。
5. 多种 change type 显示多个 badge，同一大类只显示一次。
6. 有价格变化时使用价格 primary summary，即使其它类型时间更晚。
7. range price 不显示伪造百分比。
8. 顶部同时显示 competitor count 和 event count 文案。
9. 显示 `latest_change_at` 而不是 primary change 的时间。
10. 显示当前竞品组，未知 group 继续安全显示现有 fallback。
11. “查看详情”继续以 `competitor_id` 进入现有详情页。
12. 空 item 列表继续渲染“今日暂无竞品变化”空状态。

## Out of Scope

- 不修改 ChangeEvent schema、字段含义或事实写入逻辑；
- 不合并、删除或回写数据库中的 ChangeEvent；
- 不新增数据库表、字段、索引或 migration；
- 不新增 Event Detail Page、Dashboard Change Detail Page 或 Dashboard 行展开；
- 不做多级折叠、复杂 Tooltip、变化历史导出或分页；
- 不修改现有竞品详情页的完整事件明细 contract；
- 不修改 Collection pipeline、采集失败语义或竞品生命周期语义；
- 不把异常采集混入今日变化表格；
- 不改变 KPI 的 distinct competitor 口径；
- 不改变 7 天趋势的事件级口径；
- 不新增 WebSocket、SSE、实时推送、Redis、缓存、后台任务或图表；
- 不做 Dashboard 整体重设计，不新增颜色体系或独立 Badge 体系；
- 不新增依赖；
- 本轮不实现 Backend、Frontend、数据库或文档同步以外的代码改动，不提交、不推送。

## Further Notes

### 影响范围

实现阶段只需要触及现有 Dashboard Backend contract/聚合、Dashboard Frontend 类型与展示、对应 Backend/Frontend 测试，以及实现完成后的四份长期文档同步。详情、采集、数据库 schema 和依赖保持不变。

### 成功标准

- 任意一个竞品在今日发生任意数量 ChangeEvent 时，Dashboard 最多渲染一个 row；
- event count 与 competitor count 均可从真实数据验证；
- 主要摘要、类型 badge、SKU 数量和时间均由 Backend contract 明确定义；
- Frontend 不再从事件数组完成核心聚合；
- 详情页仍能看到完整事实事件；
- KPI、趋势、时区边界、空状态和当前分组语义不回归；
- 不需要 schema、migration 或新 dependency。

### 待确认决策

当前没有阻塞实现的产品决策：本 Spec 已冻结“竞品一行、事件单独计数、Backend 聚合、详情保留明细”的方向。实现前仅需用现有真实/测试数据确认历史数据库中是否存在 `stock_changed` 缺少 `entity_key` 或无法匹配 `SkuSnapshot` 的记录；若存在，按本 Spec 的 `null` / 事实性回退规则处理，不扩大到 schema 修复。
