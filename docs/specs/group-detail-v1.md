# Group Detail V1 / 组级竞争分析详情

## Problem Statement

竞品组已经可以绑定一个真实的我方商品，并将其他组内商品作为直接竞品；现有 Groups Summary 与 Competitor Detail 仍不足以一次回答我方当前事实位置、与直接竞品的差异、今日组内变化及近期动作分布。逐个请求商品详情再由前端拼组级结论会重复请求并复制 Backend 领域规则。

## Solution

Group Detail 是“一个我方真实商品 + 该组直接竞品”的日常竞争分析页。页面目标是让用户在约 10 秒内识别我方当前基准、主要可比较差异和近期竞争动作。详细事实证据交给现有 Competitor Detail，避免组页重复承担单商品详情的全部展示职责。用户也可以进入 Competitor List 继续管理。

它不是大型 BI 大屏、第二个 Dashboard、商品管理页、AI 决策页或自动调价页。

## User Stories

1. 作为用户，我希望在一个组页面查看我方商品和所有直接竞品的真实当前事实，以便不用逐个拼接详情。
2. 作为用户，我希望看到明确低价、较低起批量、更多 SKU 和更高完整库存的可比较竞品数量，以便识别事实差距而不依赖评分。
3. 作为用户，我希望查看组内今天真实发生的事件并区分我方与竞品，以便快速了解当天变化。
4. 作为用户，我希望查看近 7 天或 30 天各直接竞品的事件数量和领域分布，以便识别近期动作较多的商品。
5. 作为用户，我希望未绑定组、无竞品、无快照、字段缺失、下架和停止监控时仍看到准确状态，不被虚构值误导。
6. 作为用户，我希望从组分析进入单商品证据页、竞品列表或返回 Groups，以便继续检查或管理。

## Implementation Decisions

### 1. API 与顶层 contract

提供一个组级只读 endpoint：

```text
GET /api/competitor-groups/{group_id}/detail?days=7|30
```

- `days` 默认 7，只允许 7 或 30；其他值沿用 FastAPI Query validation 返回 422。
- Group 不存在返回 404，错误码 `competitor_group_not_found`。
- Group 存在但未绑定 own 时仍返回 200；`own_product` 为 `null`。
- 不拆分 overview、comparison、today、actions 等多个请求。页面通过同一组级视图一次加载，避免对每个商品调用 Competitor Detail。
- 建议 response 顶层：

```json
{
  "range_days": 7,
  "group": { "id": 1, "name": "A19", "created_at": "..." },
  "own_product": null,
  "summary": {},
  "competitors": [],
  "today": {},
  "action_window": {}
}
```

实现可按 Pydantic contract 调整字段命名，但不得改变下列业务语义。`group` 只含 `id`、`name`、`created_at`，不重复 Groups Summary 卡片数据。

### 2. Product Facts 与最新快照

我方与直接竞品共用一种商品事实结构：

```text
id, role, platform, offer_id, url, title, shop_name, main_image_url,
status, is_active, last_collected_at, latest_snapshot, latest_change
```

`role` 为 `own` 或 `competitor`。已绑定时 `own_product` 使用该结构；未绑定时为 `null`。不得按组名、shop_name 猜 own，也不得自动选择任一 competitor。

`latest_snapshot` 为 `null` 或包含：

```text
id, captured_at, price_min, price_max, min_order_quantity,
sku_count, total_stock
```

- 最新有效 ProductSnapshot 按 `captured_at DESC, id DESC` 选择；每个商品独立取最新，不要求采集时间一致。
- 价格以字符串或 null 返回；MOQ 为 int 或 null。
- 有 Snapshot 时 SKU count 是该 Snapshot 实际 SkuSnapshot 数量，可为 0。无 Snapshot 时整个 latest_snapshot 为 null，不虚构 0 SKU。
- total_stock 仅在 Snapshot 至少有一个 SKU、每个 SKU 的 stock 均非 NULL 且为非负事实时返回其总和。任一 stock 为 NULL 时为 null；0 是有效值。
- 总库存语义复用现有 Detail 的完整 SKU 库存事实规则。不得把 NULL 当 0、从 ChangeEvent 推当前库存，或从库存变化推销量。
- `status = offline` 时仍返回最后有效历史快照，同时明确标记“已下架”并显示 `captured_at`，不伪装成实时值。
- `is_active = false` 表示已停止监控，与商品在线状态分开显示；历史快照仍可见。
- `latest_change` 为最近真实 ChangeEvent，按 `detected_at DESC, id DESC`；没有事件为 null。需要 SKU 名称时复用现有 Detail 的事实性名称恢复规则，不由 Group Detail 重新解释事件方向。

### 3. 成员范围、比较规则与摘要

`competitors` 仅包含 `group_id = 当前 group AND group_role = competitor` 的当前直接竞品；不包括 own、其他组成员或历史移出成员。每个竞品行由 Backend 返回 `comparison`，Frontend 不重新计算：

| 指标 | 枚举 | 规则 |
|---|---|---|
| price | `lower / higher / overlap / unknown` | 任一侧缺边界或快照缺失为 unknown；竞品 `price_max < own.price_min` 为 lower；竞品 `price_min > own.price_max` 为 higher；两侧完整且相交（含边界相等）为 overlap。单值视为 min=max。 |
| min_order_quantity | `lower / higher / equal / unknown` | 两侧值均存在才比较；竞品小于/大于/等于 own 分别为 lower/higher/equal。 |
| sku_count | `more / fewer / equal / unknown` | 两边均有有效 latest Snapshot 才比较；无 Snapshot 为 unknown，不按 0 处理。 |
| total_stock | `higher / lower / equal / unknown` | 仅比较双方完整可计算的 total_stock；任一为 null 则 unknown。只表达库存事实。 |

未绑定 own 时，竞品事实照常返回；所有依赖 own baseline 的比较均为 `unknown`，事实差距计数为 `0 / 0`。不得生成比较结论。

`summary` 至少包含：

```text
direct_competitor_count
monitored_competitor_count
changed_competitors_today
price_lower_than_own: { matched_count, comparable_count }
moq_lower_than_own: { matched_count, comparable_count }
sku_more_than_own: { matched_count, comparable_count }
stock_higher_than_own: { matched_count, comparable_count }
```

直接竞品数不含 own；monitored 数只计 `group_role = competitor AND is_active = true`。差距的 comparable_count 表示该指标两边均有可比较事实的直接竞品数，matched_count 是其中符合方向的数量。未绑定 own 时两者均为 0。UI 对 comparable_count=0 显示“暂无可比数据”，不得让 `0 / 0` 表示为“没有竞品更低”。

### 4. 今日事件

`today` 至少包含：

```text
own_event_count
competitor_event_count
changed_competitor_count
events
```

- 日期区间复用 `backend/app/dashboard.py` 的 Asia/Shanghai business-day helper，使用 UTC 半开区间；不得另建时区规则。
- 事件范围按商品当前 `group_id`、`group_role` 聚合。`changed_competitor_count` 是当前直接竞品中今天至少有一条事件的 distinct 商品数，不计 own。
- 每条 `events` 保留一条真实 ChangeEvent，至少包括 `competitor_id`、`role`、`title`、`offer_id`、`change_type`、`entity_key`、`sku_name`、`old_value`、`new_value`、`delta_value`、`delta_rate`、`detected_at`。
- 按 `detected_at DESC, id DESC` 排序。SKU 名称恢复复用现有 Detail 事实逻辑。
- 多个事件可以在 UI 视觉分组，但 API 不得合并或伪造事件。

### 5. 7 / 30 天动作窗口

`action_window` 包含 `days`、`own_event_count`、`competitor_event_count` 和 `competitors`。时间区间沿用 Asia/Shanghai 日期边界，含今天及此前 `days - 1` 个业务日期；业务日期不排除周末。切换 7 / 30 天必须重新请求 endpoint，不在前端从 30 天结果切片。

每个有事件的直接竞品动作项包含：

```text
competitor_id, title, offer_id, event_count, latest_change_at,
domain_counts: { price, stock, sku, min_order_quantity, lifecycle, title, main_image }
```

计数均为真实 ChangeEvent 条数；own 单独计数，不进入直接竞品列表。动作列表按 `event_count DESC`、`latest_change_at DESC`、`competitor_id ASC` 排序。无事件商品可不出现在动作列表，但仍在 comparison table 中。

Event Domain 映射由 Backend 统一完成：

| Domain | 事件类型 |
|---|---|
| price | `price_increase`、`price_decrease`，商品级与 SKU 级均适用 |
| stock | `stock_increase`、`stock_decrease`、`sku_sold_out`、`sku_restocked`、legacy `stock_changed` |
| sku | `sku_added`、`sku_removed` |
| min_order_quantity | `min_order_quantity_increase`、`min_order_quantity_decrease` |
| lifecycle | `product_offline`、`product_online` |
| title | `title_changed` |
| main_image | `main_image_changed` |

不得增加 risk、important、sales 等推断领域。事件数最多只称“动作最多”或“近期变化较多”，不代表风险、危险程度或竞争力。

今日和动作窗口都按商品**当前**的 `group_id`、`group_role` 聚合历史事件；不新增 membership history 或 historical role snapshot。商品当前归属 A 组，其查询期历史事件可以计入 A 组；系统不得宣称事件发生时商品已属于该组。停止监控不删除历史事件。

### 6. 查询与模块边界

Group Detail 是独立的只读聚合能力，可由独立 group-detail query/router 模块或等价的最小模块边界实现。不得重写 Groups CRUD、复制已有事实规则、增加微服务或 repository framework。

必须批量查询组成员、批量选择最新 Snapshot、批量读取相关 SkuSnapshot 和 ChangeEvent；不得按商品循环查询 latest snapshot、SKU、latest change 或时间窗事件，避免明显 N+1。固定数量的批量查询可接受，不要求一条超级 SQL。

这是从 `CompetitorGroup`、`Competitor`、`ProductSnapshot`、`SkuSnapshot`、`ChangeEvent` 读取的聚合 Feature，不新增数据库模型、schema、migration 或聚合存储表。若实现发现必须增加 schema，停止并重新评估本 Spec。

### 7. 页面信息架构与展示

页面自然纵向滚动，不做第二个 Dashboard。主结构收敛为三段：

1. PageHeader；
2. 我方基准 + 关键差距；
3. 我方 vs 竞品；
4. 竞争动态。

Competitor Detail 证据入口保留在比较行和动态项中，不作为独立大区块。

Header 使用面包屑“个人工作台 / 竞品监控 / 竞品分组 / {group.name}”，标题“{group.name} 竞争分析”，说明围绕我方商品查看当前竞争位置和近期客观变化。必要入口为“查看竞品”和“返回竞品分组”；不放删除、批量采集、绑定管理或自动建议。

我方区域仍展示真实主图、title / Offer fallback、shop_name、1688 链接、status、监控状态、价格、MOQ、SKU 数、完整库存和更新时间。价格、MOQ、SKU、库存使用紧凑事实行或等价布局，不分别制作大 Stat Card；时间信息降低视觉权重，不要求 Snapshot time 与 last_collected_at 都作为独立大字段。它是事实展示，不显示评分或推荐售价。

顶部 Fact Gap 只展示 Backend summary 中的 `price_lower_than_own`（明确低价竞品）、`moq_lower_than_own`（更低起批量竞品）、`sku_more_than_own`（SKU 更多竞品）。`stock_higher_than_own` 仍是 Backend contract 的 summary metric，但不作为顶部 KPI：库存高于我方是客观比较事实，不应在视觉上暗示为一级竞争优势；库存仍留在 comparison table。每项使用 `matched_count / comparable_count` 并注明可比较竞品；`comparable_count = 0` 显示“暂无可比数据”，不显示“0 / 0”。

比较表列为：商品、当前价格、起批量、SKU、库存、当前差异、最近变化、详情。角色和最近采集不独立成列；我方固定第一行，以克制的“我方”小标识和可选浅色行背景突出，普通竞品行不要求重复显示“竞品” Badge。最近采集可作为商品信息下的次级文字（如“14:48 更新”）。竞品行提供“查看详情”。

Frontend 直接消费 Backend comparison，不自行计算。当前差异只突出有意义的真实方向：price 的 lower / higher 显示“低价” / “高价”，overlap 不突出；MOQ 的 lower / higher 显示“起批更低” / “起批更高”；SKU 的 more / fewer 显示“SKU 更多” / “SKU 更少”；库存的 higher / lower 显示“库存更高” / “库存更低”，其视觉权重低于价格、MOQ 和 SKU，且不解释为竞争优势或销量。equal / overlap 不突出，unknown 不生成方向结论。若没有值得突出的可比较方向差异，显示“基本持平”；部分字段 unknown 时仍显示其他真实差异，例如“低价 · SKU 更多”，不得被单个 unknown 覆盖。没有可展示差异且有缺失时可显示“部分数据未知”。

最近变化只显示紧凑的真实事实（例如“库存 994 → 987”“标题已变更”“商品降价 ¥40 → ¥38”）；没有事件时不显示“暂无变化”。完整事件证据由 Competitor Detail 提供。

“竞争动态”合并 today 与 action_window，提供“今日 / 近 7 天 / 近 30 天”Tab，默认“近 7 天”。今日消费 `response.today`，可紧凑显示变化竞品、竞品事件和我方事件计数；三者均为 0 时直接显示“今日暂无变化”，有事件时按 Backend 顺序显示真实事件并区分“我方”与“竞品”。近 7 / 30 天消费 `action_window`；切换 7 与 30 天分别重新请求 `?days=7` 和 `?days=30`，不得从 30 天结果前端切片得到 7 天。range-loading 保留已有页面内容。

动作列表不按“7 个领域列 × N 个竞品”铺开，使用紧凑排行 / 列表，每项展示商品、event_count、非零 domain counts、latest_change_at 和详情入口。Backend `domain_counts` 完整保留；Frontend 只展示 count > 0 的领域。主页面只展示 Backend 已排序 `action_window.competitors` 的前 5 条；Backend 仍返回完整列表。动作数只表示真实 ChangeEvent 数量，允许称“近期动作”“动作最多”或“变化较多”，不得表述为风险、威胁或竞争力判断。

遵守 `docs/ui-system.md` 的浅色、蓝紫雾感、轻毛玻璃、中等圆角和桌面优先规范；不创建新 design system，不做深色 BI、高饱和数据墙、雷达图或评分仪表。

### 8. Navigation 与状态

当前 App 使用内部 Page state 且没有 React Router。新增 `group-detail` 页面语义，并保存 `selectedGroupId` 或等价状态；不引入 React Router 或全局状态框架。

Groups 正式组卡片增加统一入口文案“组分析”，保留现有“查看竞品”和“更多”。“查看竞品”继续进入现有按组筛选的 Competitor List；“组分析”进入对应 Group Detail。竞品行的“查看详情”进入既有 Competitor Detail。Header 提供返回 Groups 和查看竞品入口。

页面状态必须覆盖 loading、error、normal、unbound、empty competitors、partial data。首次请求失败显示页面 ErrorState 和重试；切换时间范围可局部 loading，保留当前事实内容，成功后替换动作窗口；避免整页闪空。

- 组存在但 `own_product = null`：显示“尚未绑定我方商品”，说明“绑定我方商品后，可查看价格、起批量、SKU 和库存的横向比较。”不显示事实差距结论；comparison 为 unknown / 未建立基准。真实竞品当前事实和今日事件仍可显示。提供返回 Groups，不在此页做绑定 Dialog。
- 有 own、无直接竞品：200 正常呈现真实空状态“当前组还没有直接竞品”，提供“查看竞品列表”；不显示伪造价格或比较。
- 缺少事实按语义显示“未采集”“未知”或“暂无变化”，不补 0。offline 显示“已下架”并保留标注时间的历史快照；停止监控明确显示监控状态。
- Group Detail 重载遇到 404，显示“竞品组不存在”并提供返回 Groups。

### 9. Testing Decisions

测试用户可观察行为和业务 contract，不绑定具体 SQL 字符串。沿用现有 Backend TestClient + 临时 SQLite、Detail/Groups/Dashboard 测试 seam，以及 Frontend API mock、纯函数和静态渲染/交互测试方式。

Backend 至少覆盖：

- group 404；bound、unbound、无 competitor、own only、partial data；
- 最新 Snapshot 按 `captured_at DESC, id DESC`；SKU 数量；完整库存、未知库存和有效 0；
- 价格 lower/higher/overlap/single-value/missing boundary unknown；MOQ lower/higher/equal/unknown；SKU more/fewer/equal/no snapshot unknown；库存 higher/lower/equal/incomplete unknown；
- summary matched/comparable 及 own 不计入竞品；
- Asia/Shanghai 今日边界、own 事件分离、直接竞品 distinct 计数、多事件保留、当前成员关系范围；
- days=7/30、非法 days 422、全部 domain mapping、排序、legacy `stock_changed` 属于 stock、当前组成员范围；
- 查询不会按商品形成明显 N+1，不以 SQL 字符串断言实现细节。

Frontend 至少覆盖：Groups“组分析”入口；Group Detail loading、404/error/retry、unbound、own 概览、无竞品、partial data；顶部仅显示三个主要 Fact Gap 且 stock metric 不作为顶部 KPI；比较表没有独立 role / last-collected 列、own first、差异紧凑文本、“基本持平”和“部分数据未知”；comparable_count=0；Today own/competitor 区分及 0 事件显示“今日暂无变化”；竞争动态默认近 7 天；只展示非零 domain counts 和 action Top 5；7/30 请求切换会重新请求；Competitor Detail 导航、返回 Groups、查看竞品列表和 range-loading 保留已有内容。不测试 CSS 像素。

## Out of Scope

- 修改数据库 schema、migration、新聚合表、GroupAnalytics、GroupSnapshot、GroupComparison、ActionSummary 或 Score。
- Dashboard 组级重构或入口排序算法；Dashboard 仅在 Group Detail 稳定后再评估，本 Feature 不修改 Dashboard。
- AI 分析/建议、竞争力或风险评分、推荐价格、自动调价、销量推断、自动匹配、提醒/通知和报表导出。
- Group 内编辑、删除、批量采集；Group Detail 内绑定或更换 own。
- 多平台、多用户、membership history、event importance score、新采集字段。
- React Router 或新全局状态框架。
- 通过 N 次 Competitor Detail 请求由前端拼装组分析。

## Further Notes

本 Spec 是 Group Detail V1 后续 Implementation 的直接 source of truth。当前已实现 `Competitor.group_role`、own bind/replace/unbind、Groups Summary、Snapshot/SKU Snapshot、CollectionRun、ChangeEvent V2 与 legacy `stock_changed` 兼容、单商品 Competitor Detail，以及 Groups/List/Dashboard 页面。Group-level Detail API 与 Group Detail Page 当前均未实现；Frontend Page 类型目前只有 dashboard、competitors、detail、groups。

产品问题：无待确认项。成功标准是以单个组级只读 API 提供以上事实和聚合，页面仅消费该 contract，并保持现有数据真实性与导航边界。
