# 竞品详情页概览与趋势升级 Feature Spec

状态：正式 Feature Spec，供后续实现使用。

本轮只新增本 Spec，不实现 Backend、Frontend、数据库、migration、测试、依赖或 Git 操作。

## Problem Statement

当前竞品详情页已经能展示商品信息、当前价格、状态、SKU、最近变化、采集记录、价格趋势和生命周期操作，但信息层级仍以“单张价格图 + 底部明细”为主：

- 当前状态、历史趋势和事实明细没有形成清晰的阅读顺序；
- 价格趋势返回每次 `ProductSnapshot`，同一 Asia/Shanghai 业务日可能出现多个点；
- 库存只能在 SKU 表中逐行查看，缺少当前总库存和库存历史趋势；
- 最近价格变化没有进入顶部状态摘要；
- 销量数据源已被验证为 PARTIAL / NOT_READY，不能用 POC 字段伪装成正式销量趋势。

本 Feature 要把详情页固定为：

```text
当前状态 → 历史趋势 → 事实明细
```

并且所有展示都必须来自当前正式模型或明确的占位状态。

## Solution

将详情页改为三个连续区域：

1. 商品概览：商品主图、核心信息、当前状态摘要；
2. 趋势数据：共享时间范围的价格趋势、库存趋势、销量占位；
3. 明细：SKU 信息、最近变化、最近采集记录。

详情页继续使用现有浅色高级 SaaS、蓝紫雾感背景、白色卡片、中等圆角、轻阴影和克制的信息密度。继续使用手写 SVG，不引入图表库。

### User Stories

1. 作为竞品监控使用者，我希望打开详情页就能先看到商品当前状态，以便快速判断是否需要处理。
2. 作为竞品监控使用者，我希望看到真实商品主图，以便确认当前详情页对应的商品。
3. 作为竞品监控使用者，我希望主图缺失时看到明确 Placeholder，而不是重复图片或空白区域。
4. 作为竞品监控使用者，我希望在紧凑 Key-Value 布局中看到商品标题、店铺名称、商品链接、offerId 和竞品组。
5. 作为竞品监控使用者，我希望未分组商品明确显示“未分组”。
6. 作为竞品监控使用者，我希望商品链接可以打开原始 1688 页面。
7. 作为竞品监控使用者，我希望看到当前价格，并且单值和区间价格使用稳定的金额格式。
8. 作为竞品监控使用者，我希望看到最近一次真实发生的价格变化，而不是把“最近一次采集”误认为变价。
9. 作为竞品监控使用者，我希望价格区间事件不会被错误压缩成一个虚假的百分比。
10. 作为竞品监控使用者，我希望看到商品状态、SKU 数量、当前库存、最近采集时间和监控状态。
11. 作为竞品监控使用者，我希望库存为真实的 SKU 库存总和，并且 `0` 能被正确展示为真实库存。
12. 作为竞品监控使用者，我希望库存数据不完整时看到 `—`，而不是被错误地当成 0。
13. 作为竞品监控使用者，我希望价格趋势和库存趋势使用同一时间范围，避免分别切换造成误读。
14. 作为竞品监控使用者，我希望 7 天和 30 天趋势的横轴包含连续的 Asia/Shanghai 业务日。
15. 作为竞品监控使用者，我希望缺少采集的日期仍保留为空点，以便区分“没有数据”和“库存为 0”。
16. 作为竞品监控使用者，我希望价格趋势同时表达最低价和最高价，并保留 `min == max` 时两条线重合的事实。
17. 作为竞品监控使用者，我希望库存趋势中的未知值形成缺口，而不是落到 0 轴。
18. 作为竞品监控使用者，我希望通过 Tooltip 查看具体日期、价格和库存数值。
19. 作为竞品监控使用者，我希望看到销量趋势卡片，但能明确知道正式销量能力尚未开放。
20. 作为竞品监控使用者，我希望销量占位不出现随机值、全 0 折线或 POC 数据。
21. 作为竞品监控使用者，我希望继续在详情页停止监控、恢复监控和删除竞品。
22. 作为竞品监控使用者，我希望返回竞品列表的入口不受详情布局调整影响。
23. 作为竞品监控使用者，我希望 SKU 信息、最近变化和最近采集记录仍然保留在页面底部。
24. 作为竞品监控使用者，我希望删除操作在详情页常驻显示为弱化危险视觉，并在确认 Dialog 中使用明确的实心 danger 操作。
25. 作为窄屏使用者，我希望概览和趋势卡片可以自然折叠为单列，而不是出现横向溢出。
26. 作为维护者，我希望价格和库存来自同一个每日最终快照，避免两个趋势接口出现日期聚合不一致。
27. 作为维护者，我希望缺失数据保持 `NULL` 或空点语义，不通过前端推断、缓存或默认值补齐。
28. 作为维护者，我希望 7 天和 30 天查询使用集合查询完成，不为每个日期单独查询 SKU。

## Product Semantics

### 1. 当前模型事实

- `Competitor.main_image_url` 是详情页唯一正式主图来源。V1 只展示这一张真实主图；不复制图片、不伪造缩略图、不新增图片接口。
- `Competitor.title`、`Competitor.shop_name`、`Competitor.url`、`Competitor.offer_id` 和 `Competitor.group_id` 是概览核心信息来源。
- `Competitor.status` 是商品状态；`Competitor.is_active` 是监控状态，二者不可混用。
- `ProductSnapshot` 保存一次成功采集的商品级事实；价格事实来自 `price_min` / `price_max`。
- `SkuSnapshot` 保存某次商品快照下的 SKU 事实；库存事实来自 `stock`，`NULL` 表示未知，`0` 表示真实库存为零。
- `ChangeEvent` 保存已发生的真实变化；价格变价只使用 `price_increase` 和 `price_decrease`。
- 当前 Parser 将 1688 `canBookCount` 映射为 `SkuData.stock`，再保存为 `SkuSnapshot.stock`；Parser 没有把缺失库存转成 0。
- 当前 Parser 可以产生 0 个 SKU，现有模型也允许空的 `SkuSnapshot` 集合。没有证据证明 0 个 SKU 等价于库存为 0，因此无 SKU 的总库存必须是未知。
- 销量相关字段虽然在独立 POC 中被观察到，但没有字段达到正式 READY，不属于本 Feature 的正式事实来源。

### 2. 商品概览最终结构

桌面端采用三列：

```text
左：商品图片区
中：商品核心信息
右：运营摘要指标
```

左列：

- 有 `main_image_url` 时展示真实主图；
- `main_image_url = null` 时展示 Placeholder“暂无主图”；
- 图片加载失败继续使用 Placeholder；
- 不从同一 URL 复制出图片列表。

中列：

- 商品标题；
- 商品状态 Badge；
- 店铺名称；
- 商品链接，允许新窗口外链打开；
- offerId；
- 所属竞品组 Badge / Pill；`group_id = null` 时显示“未分组”；
- 本 Feature 不增加竞品组编辑入口；
- 本 Feature 暂不增加复制链接或复制 offerId 操作，避免为了一个低频操作增加新交互；如后续真实流程需要，再作为独立小 Feature 增加。

右列正式展示：

1. 当前价格；
2. 最近一次价格变化；
3. 商品状态；
4. SKU 数量；
5. 当前库存；
6. 最近采集时间；
7. 监控状态。

右列不得增加假销量、店铺等级、老店年限、发货速度、实力商家、支持定制等未经正式模型支持的指标。

### 3. 当前价格

继续使用现有 `formatPriceDisplay` 语义：

- `min == max`：`¥38.80`；
- `min != max`：`¥34.00 ~ ¥38.00`；
- 两者都缺失：`—`；
- 只有一侧有值时展示该真实值，不补造另一侧边界。

当前价格只取最新 `ProductSnapshot` 的 `price_min` / `price_max`，不从旧快照回填。

### 4. 当前库存

当前库存定义为：

```text
最新 ProductSnapshot
→ 该快照的全部 SkuSnapshot
→ stock 总和
```

具体规则：

- 最新快照不存在：`total_stock = null`；
- 最新快照存在但没有任何 SKU：`total_stock = null`；
- 至少有一个 SKU，且所有 SKU 的 `stock` 都不是 `null`：`total_stock = SUM(stock)`；
- 任意 SKU 的 `stock = null`：`total_stock = null`；
- `stock = 0` 是有效事实，必须参与求和；
- 不忽略 `null` 后再求和；不把 `null` 当作 0。

顶部摘要的最终文案为 `—`。`—` 表示当前总库存未知或数据不完整，不表示库存为 0，也不表示系统错误。SKU 明细仍按行保留 `0` 和 `—`。

### 5. 最近一次价格变化

最近变价不是“较上一次采集”，而是历史上最近一次真实的价格变化事件。

查询范围和排序：

- `ChangeEvent.competitor_id = 当前竞品`；
- `change_type IN ('price_increase', 'price_decrease')`；
- `detected_at DESC, id DESC`；
- 取第一条；
- 无符合事件时为 `null`。

页面同时展示：

- 当前价格：来自最新 `ProductSnapshot`；
- 最近变价：来自 `ChangeEvent.old_value → new_value`；
- 变价方向和百分比：仅在满足百分比规则时展示。

价格趋势和最近变价保持不同语义：

```text
价格趋势：ProductSnapshot 历史事实，例如 40 → 38 → 38
最近变价：ChangeEvent 最近真实事件，例如 40 → 38，↓5.0%
```

### 6. 百分比计算规则

只有以下条件全部满足时才计算百分比：

- `old_value` 和 `new_value` 都是单一价格数值；
- 两个值都能按当前金额格式解析为有限非负数；
- 两个值都不包含价格区间分隔符；
- `old_value != 0`。

计算公式：

```text
(new - old) / old × 100%
```

展示保留 1 位小数，方向按事件实际变化展示：

- `40 → 38`：`↓ 5.0%`；
- `38 → 40`：`↑ 5.3%`。

对于 `40~50 → 38~48`、任一端缺失、无法解析或旧值为 0：

- 仍展示真实的区间或原始变价：`¥40.00 ~ ¥50.00 → ¥38.00 ~ ¥48.00`；
- 百分比显示 `—`；
- 不使用 min、max、中位数或平均值压缩出统一百分比。

## API Contract

### 1. Endpoint

继续使用：

```text
GET /api/competitors/{competitor_id}/detail?days=7|30
```

`days` 只允许 `7` 或 `30`，默认 `7`。原有稳定的 `competitor_not_found` 404 语义保持不变。

### 2. Response shape

保留现有 `range_days`、`competitor`、`latest_skus`、`recent_changes` 和 `recent_collection_runs`。`latest_snapshot` 增加派生字段 `total_stock`，不新增数据库字段。

详情响应新增并统一使用：

```text
latest_price_change: DetailChangeResponse | null
daily_trend: DailyTrendPoint[]
```

`latest_price_change` 必须只包含 `price_increase` 或 `price_decrease`。没有价格事件时为 `null`。

`DailyTrendPoint` 的正式字段为：

```text
{
  date: "YYYY-MM-DD",
  snapshot_id: number | null,
  captured_at: datetime | null,
  price_min: string | null,
  price_max: string | null,
  total_stock: number | null
}
```

字段语义：

- `date` 是 Asia/Shanghai 业务日；
- `snapshot_id` 和 `captured_at` 指向该日选中的最终快照；该日无快照时均为 `null`；
- `price_min` / `price_max` 直接来自该日最终快照；两者都缺失时保留该日期并返回两个 `null`；
- `total_stock` 按当前库存完整性规则计算；未知时为 `null`；
- 不加入销量字段，避免把未 Ready 的销量事实混进正式趋势 contract。

本 Feature 用 `daily_trend` 替代现有重复的 `price_trend` 结构，不同时保留 `price_trend` 和 `stock_trend`，也不增加 `snapshot_trend` 别名。价格和库存本来来自同一个每日最终快照，统一结构可以避免重复日期聚合，并让前端只消费一个趋势数组。

### 3. API null contract

- 没有最新快照：`latest_snapshot = null`（因此其 `total_stock` 语义为未知）、`latest_price_change` 仍可独立返回历史事件；
- 最新快照价格缺失：价格字段为 `null`，前端显示 `—`；
- 最新快照没有 SKU：`sku_count = 0`，`total_stock = null`；
- 某个 SKU 库存未知：总库存为 `null`；
- 趋势日期没有采集：保留日期，`snapshot_id`、`captured_at`、价格和库存全部为 `null`；
- 趋势日期有快照但价格缺失：保留日期，价格为 `null`，库存仍独立表达；
- 趋势日期有快照但库存未知：`total_stock = null`，不输出 0。

## Implementation Decisions

### 1. Daily trend selection

7 天和 30 天均返回连续的 Asia/Shanghai 业务日，包含当前业务日：

```text
days = 7  → 当前业务日往前 6 天至当前业务日
days = 30 → 当前业务日往前 29 天至当前业务日
```

这里的“业务日”沿用项目现有语义，是 Asia/Shanghai 的连续本地日历日，包含周末，不是排除周末的工作日。

每日选择规则：

1. 将每个本地业务日转换为 UTC 半开区间 `[start_utc, end_utc)`；
2. 只考虑该竞品在该区间内的 `ProductSnapshot`；
3. 按 `captured_at DESC, id DESC` 选最后一条；
4. 该快照作为当天的价格和库存共同来源；
5. 没有快照时仍返回该日期的空点。

必须复用现有 `business_day_bounds` / `business_date_utc_bounds` 的 Asia/Shanghai 语义及缺少时区数据库时的固定 UTC+8 fallback。禁止直接对 UTC `captured_at` 使用 `DATE(captured_at)`。

### 2. Query and performance

趋势查询应使用集合式查询、窗口选择或等价的单次批量聚合：

- 一次确定日期范围内每个业务日的最终 `ProductSnapshot`；
- 通过 JOIN / grouped aggregation 一并计算对应 SKU 库存；
- 不允许按日期逐个查询快照，再为每个快照单独查询 SKU，形成 N+1；
- 不新增 cache、Redis、物化趋势表、历史表或后台汇总任务。

项目当前规模很小，简单、可读、可测试优先于更复杂的预计算方案。

### 3. Price trend

- 图表展示最低价和最高价两条线；
- `price_min == price_max` 时两条线使用同一真实坐标并自然重合；
- `null` 不转成 0；
- 缺失日期保留空点；
- 单日只有一侧价格时只绘制有值的一条线；
- 当整个时间范围没有任何有效价格时，卡片保留正常高度并显示非错误 Empty State，例如“该时间范围暂无可用价格数据”。

### 4. Stock trend

- 每个点使用每日最终快照的 SKU 集合计算 `total_stock`；
- 所有 SKU 有效且至少一个 SKU 时求和；
- 任意 `null` 或无 SKU 时为 `null`；
- 0 是有效点；
- SVG 对 `null` 不绘制点、不连接跨缺口的连续线，也不把未知库存画到 0 轴；
- 无有效库存点时显示正常 Empty State，而不是 Error State。

### 5. Sales placeholder

销量趋势卡片正式存在，但只展示能力占位：

```text
销量数据待接入
当前数据源尚未达到正式采集标准
```

销量卡片与价格、库存卡片保持相同卡片高度、边框、圆角、阴影和标题结构；使用中性的辅助视觉，表达“能力尚未开放”，不表达系统错误。

禁止使用 `last30DaysSales`、`totalSales`、`totalOrder`、`saleQuantityList` 或 `tradePriceList` 作为正式销量趋势数据；禁止随机数据、全 0 数据、POC 数据和虚假折线；销量占位不显示 Tooltip。

### 6. SVG chart and tooltip

继续使用原生 SVG。允许抽象一个小型 `DetailTrendChart`，只覆盖价格和库存两种模式；不建设通用 Chart Framework。

价格 Tooltip：

```text
09/20
最低价 ¥38.80
最高价 ¥38.80
```

当最低价等于最高价时可简化为：

```text
09/20
价格 ¥38.80
```

库存 Tooltip：

```text
09/20
库存 9,998
```

空点不显示 Tooltip，不能把空点弹成 0。Tooltip 只展示对应真实点的数据，不能从相邻日期推断或填充。

### 7. Overview and lifecycle UI

- 概览区继续复用现有 Detail Reference Page 和基础 Card / Badge / Button 体系；
- 详情页顶部保留“返回竞品列表”；
- active 竞品保留“停止监控”；inactive 竞品保留“恢复监控”；
- 始终保留“删除竞品”；
- 删除按钮常驻使用 `danger-outline` 或浅红危险按钮；
- 删除确认 Dialog 的“确认删除”继续使用实心 danger；
- 本 Feature 不重新设计 lifecycle API、确认流程或异步请求竞态保护；
- 底部继续保留 SKU 信息、最近变化和最近采集记录，趋势区不重复展示最近变化列表。

### 8. Responsive layout

桌面端：

- 概览三列：图片 / 核心信息 / 摘要；
- 趋势三列：价格 / 库存 / 销量；
- 趋势卡片使用 CSS Grid，不使用 Masonry。

中等宽度：

- 概览允许图片与核心信息并排，摘要换到下一行；
- 趋势根据可用宽度变为两列或一列；
- 明细区域沿用当前响应式折行规则。

窄屏：

- 概览单列；
- 趋势单列；
- 操作按钮允许自然换行；
- 不进行移动端大规模重新设计，不引入新的布局体系。

## Testing Decisions

测试只保护外部行为、数据 contract、空值语义和用户可见结构，不锁定 SQL 写法、React 内部层级或具体 CSS 实现。

### Backend test seams

以详情 API contract 和现有业务日 helper 为最高测试 seam，至少覆盖：

1. 每个 Asia/Shanghai 业务日选取最后一条 ProductSnapshot；
2. 同一天多个快照按 `captured_at DESC, id DESC` 只返回一个；
3. UTC 00:00～08:00 边界被正确归入对应上海本地日期；
4. `days=7` 返回当前业务日及之前连续 6 天；
5. `days=30` 返回当前业务日及之前连续 29 天；
6. 缺采集日期保留空点，不返回上一日值；
7. 价格全部缺失时保留日期，`price_min` / `price_max` 为 `null`；
8. 价格区间保持原始 min/max，不被压缩为单值；
9. 所有 SKU 库存有效时返回总和；
10. SKU 库存包含 0 时仍正确求和；
11. 任意 SKU `stock = null` 时 `total_stock = null`；
12. 无 SKU 时 `total_stock = null`，不能当成 0；
13. 返回最近的 `price_increase`；
14. 返回最近的 `price_decrease`；
15. 没有价格事件时 `latest_price_change = null`；
16. 多个非价格 ChangeEvent 不会干扰最近变价选择；
17. 最新快照的价格和库存与趋势中同一业务日的最后真实点一致；
18. 最新快照落在选定范围之外时，顶部当前值可以与趋势范围内最后点不同，但 contract 仍保持可解释；
19. 价格事件 old/new 为单值和区间值时均原样保留；
20. 不生成销量字段或销量数据。

### Frontend test seams

优先复用现有纯 formatter、趋势点构造函数和 `renderToStaticMarkup` seam，至少覆盖：

1. 新的图片 / 核心信息 / 摘要三列概览布局；
2. 当前库存有效求和展示；
3. 当前库存未知展示 `—`；
4. 最近变价上涨展示方向、旧值、新值和可计算百分比；
5. 最近变价下降展示方向、旧值、新值和可计算百分比；
6. 无最近变价展示明确空状态；
7. 区间价格事件不错误计算百分比；
8. 商品组 Badge 和“未分组”；
9. 商品链接为外链；
10. 价格趋势卡；
11. 库存趋势卡；
12. 销量占位卡的两行正式文案；
13. 统一的近 7 天 / 近 30 天 selector 同时服务价格和库存趋势；
14. 缺失日期被保留为空点；
15. 价格 Tooltip 的单值和区间内容；
16. 库存 Tooltip 的格式化数量；
17. 空点不显示 0 Tooltip；
18. 停止监控、恢复监控和删除竞品操作仍存在；
19. SKU 信息、最近变化和最近采集记录仍存在；
20. 删除常驻按钮使用弱化 danger 视觉，确认 Dialog 使用实心 danger；
21. 缺少 `main_image_url` 时只显示 Placeholder，不生成重复图片列表。

## Out of Scope

本 Feature 不做：

- 正式销量采集；
- sales migration、sales history、`saleQuantityList` / `totalSales` / `totalOrder` 接入；
- 当前商品销量展示；
- 多图、缩略图列表或新图片接口；
- 店铺等级、老店年限、发货时效、实力商家、支持定制等字段；
- 竞品组编辑；
- 新 Chart Library（ECharts、Recharts、Chart.js、D3）；
- 新数据库表、数据库字段、migration；
- cache、Redis、物化趋势表或后台趋势任务；
- 新销量接口、单独 `stock_trend` 接口或重复兼容趋势结构；
- App.tsx 大重构；
- lifecycle 逻辑、删除确认流程或已有请求竞态机制的重新设计；
- 与本 Feature 无关的重构、格式化、视觉体系升级；
- 本轮任何 Backend、Frontend、CSS、测试、提交或推送。

## Further Notes

### 正式实现后需要同步的长期文档

实现并验证完成后，再按实际落地内容同步：

- `docs/product.md`：详情页当前状态、7/30 天趋势和销量占位的产品能力边界；
- `docs/data-model.md`：`latest_price_change`、`latest_snapshot.total_stock`、连续业务日 `daily_trend` 的派生事实语义，并明确没有新增数据库实体或字段；
- `docs/architecture.md`：详情查询复用 Asia/Shanghai business-day helper、统一每日快照 contract 和避免 SKU N+1 的查询边界；
- `docs/ui-system.md`：详情页三段式信息架构、三列趋势卡、空点 / 占位 / Tooltip 和删除按钮视觉规则。

本轮不修改上述长期文档。

### 仍需确认的产品决策

没有阻塞实现的产品决策。当前默认冻结的可选决策是：本 Feature 不加入商品链接或 offerId 复制入口；如果真实使用流程明确需要复制操作，再单独确认并拆分为独立 Feature。
