# ChangeEvent V2：统一变化事件模型 Spec

状态：正式 Spec，仅定义下一阶段实现边界；本轮不实现。

本 Spec 更新现有“单次采集后的快照变化检测” Spec。后续实现以本文为准；与旧文档中仅支持 `stock_changed`、不支持主图或商品生命周期的描述，以本文为准。

## 1. Problem Statement

系统已经形成：

```text
采集 → ProductSnapshot / SkuSnapshot → ChangeEvent → Dashboard / Detail / List / Groups
```

Snapshot 记录某个时点的商品事实，ChangeEvent 记录本次有效采集与上一份有效事实之间客观发生的变化。

当前 ChangeEvent 的问题是事件粒度和语义不统一：

- 价格已经区分 `price_increase` / `price_decrease`；
- SKU 已经区分 `sku_added` / `sku_removed`；
- 商品生命周期已经区分 `product_offline` / `product_online`；
- 库存仍只有笼统的 `stock_changed`，页面需要再次判断方向；
- SKU 售罄与恢复有货尚未成为独立事件；
- 每条事件没有正式关联发现它的 `CollectionRun`；
- 价格和库存变化没有可直接使用的数值差值字段；
- 不同消费者需要重复理解旧事件类型和 Snapshot 结构。

如果继续让 Dashboard、列表、详情、竞品组各自重新判断变化含义，后续排序、筛选、提醒、报表和横向分析会产生多套不一致的规则。

## 2. Solution

建立一个统一的、只表达客观变化的 ChangeEvent V2：

1. 以同一竞品的上一份有效 ProductSnapshot 为比较基线；
2. 把商品价格、商品总库存、SKU 状态、商品生命周期、标题和主图变化拆成标准事件；
3. 一次采集发现多个事实变化时保存多条独立 ChangeEvent；
4. 第一次成功采集只建立 Snapshot baseline，不生成普通变化事件；
5. 下架只在采集器取得明确正面证据时生成 `product_offline`；
6. 恢复上架首轮只生成 `product_online`，不把下架期间的累计差异伪装成当前时刻发生的普通变化；
7. 新事件关联本次 ProductSnapshot（下架事件除外）和本次 CollectionRun；
8. 用可空的数值差值字段直接表达可计算的价格或库存差异；
9. 保留历史事件，不删除、不补造、不把无法可靠判断方向的历史事件改写成新语义。

ChangeEvent V2 不引入事件总线、聚合表、规则引擎、独立事件表或新的采集字段。

## 3. 当前实现事实

本 Spec 基于当前 main 分支代码、测试、长期文档和 Alembic migrations 核对得出。

### 3.1 当前模型

当前 `ChangeEvent` 字段为：

```text
id
competitor_id
snapshot_id
change_type
entity_key
old_value
new_value
detected_at
```

当前没有 `collection_run_id`、`delta_value` 或 `delta_rate`。

当前数据库允许的 9 种类型为：

```text
price_increase
price_decrease
sku_added
sku_removed
stock_changed
title_changed
main_image_changed
product_offline
product_online
```

`product_offline` 的 `snapshot_id` 为 `NULL`；其他当前事件必须关联 Snapshot。当前没有 ChangeEvent 到 CollectionRun 的外键。

### 3.2 当前采集与保存流程

- CollectionRun 先以 `running` 短事务提交；Playwright/网络采集不持有业务保存事务。
- 正常商品页会被标准化为 `ProductData`，`product_status = unknown` 会在服务层归一为 `active`。
- 正常成功时创建新的 ProductSnapshot 和 SkuSnapshot，并保存 ChangeEvent、更新 Competitor、把 CollectionRun 标记为 `success`，最后在同一业务事务提交。
- 保存异常会回滚本次业务数据，再把原 CollectionRun 标记为 `failed`。
- 明确下架成功时不创建 ProductSnapshot，保留历史 Snapshot，并在同一成功事务中更新状态、Run 和可能的 `product_offline`。
- `active → offline` 只生成一次 `product_offline`；`offline → active` 创建恢复 Snapshot 并只生成 `product_online`。

### 3.3 当前下架证据边界

采集器目前使用明确可见的下架标题选择器和精确文本命中识别下架，并且验证页判断优先于下架判断。

以下情况都不能当作下架：

- 滑块或风控验证；
- 登录页；
- 页面空白；
- 网络错误、HTTP 不可用或超时；
- HTML/内嵌 JSON 解析失败；
- offer ID 缺失或不匹配；
- 商品必要字段缺失；
- 任意未验证的页面形态。

### 3.4 当前 SKU 身份与库存总量

- parser 从结构化 SKU 数据中读取 `skuId`，缺少或无效的 `sku_id` 会导致解析失败。
- 当前不存在 SKU 名称、数组位置或模糊匹配的 fallback。
- `sku_name` 仅用于展示和事件值，不用于判断 SKU 身份。
- 当前没有持久化 `total_stock` 字段。
- 当前总库存计算规则是：至少存在一个 SKU，且本次快照全部 SKU 的 `stock` 都非 `NULL` 时，求所有 SKU `stock` 之和；否则返回 `NULL`。
- `0` 是有效库存，不等同于未知。

## 4. Goals

ChangeEvent V2 的目标：

- 冻结 12 种标准变化事件及其触发条件；
- 让库存方向和 SKU 售罄/恢复无需消费者二次推断；
- 让事件能追溯到发现它的 CollectionRun；
- 让价格和库存事件在可靠时直接携带差值和变化率；
- 保持 Snapshot 是事实记录、ChangeEvent 是相邻事实比较结果；
- 兼容已有历史 ChangeEvent 和现有页面消费者；
- 让实现可以复用当前 parser、collector、service、Snapshot 和测试 seam；
- 保持 SQLite migration 可回滚、可拒绝不安全 downgrade，且不删除历史数据。

## 5. Non-goals

本 Spec 不做：

- 普通 / 重要 / 重大等级；
- 风险评分；
- 自定义阈值；
- 用户提醒、邮件、微信或 App 通知；
- AI 摘要或 AI 运营建议；
- 销量估算或销量变化；
- 把库存下降解释为销量；
- 新 Dashboard、List、Detail 或 Group UI；
- 报表；
- 多平台；
- 新采集字段或新的 SKU 匹配算法；
- 重构现有采集架构；
- 事件聚合表、消息队列、后台事件总线或新服务；
- 历史 Snapshot 回填；
- 历史上不存在的 ChangeEvent 补造；
- 本轮业务代码、模型、migration、测试或前端实现。

## 6. V2 标准事件清单

V2 正式标准事件共 12 种：

| 领域 | `change_type` |
|---|---|
| 价格 | `price_decrease`、`price_increase` |
| 商品总库存 | `stock_decrease`、`stock_increase` |
| SKU | `sku_added`、`sku_removed`、`sku_sold_out`、`sku_restocked` |
| 商品生命周期 | `product_offline`、`product_online` |
| 商品内容 | `title_changed`、`main_image_changed` |

`stock_changed` 不属于 V2 新标准事件，但在兼容期保留为历史 legacy 类型，见第 19 节。

V2 不支持 `sales_increase`、SKU 独立价格变化或其他未列出的类型。

## 7. 事件共同规则

### 7.1 事件表示客观事实

ChangeEvent 只记录“相邻有效事实之间发生了什么”，不记录重要度、风险、原因、建议或用户偏好。

事件不得因为页面展示需要而合并、删除或改写。页面可以把多条事件组合成一句摘要，但底层仍保留每条事件。

### 7.2 相邻有效事实

对同一 `competitor_id`：

- previous 是本次新 Snapshot 创建前，按 `captured_at DESC, id DESC` 排序的最近一条正常 ProductSnapshot；
- current 是本次已完成标准化并即将保存的 ProductData，保存后对应新的 ProductSnapshot；
- 不按自然日、昨天、最近一次 Run 或页面打开时间替代 Snapshot 基线；
- 不与多个历史 Snapshot 同时比较；
- 下架检查没有正常商品事实，不创建空 Snapshot，也不参与普通字段 diff。

### 7.3 统一检测时间

同一次 CollectionRun 产生的所有 ChangeEvent 使用同一个 UTC `detected_at`。它表示系统检测到变化的时间，不表示商品在平台上真实发生变化的时间。

### 7.4 独立事件

一次采集可产生多条事件，示例：

```text
价格 42 → 35
总库存 8240 → 3110
黑色 SKU 127 → 0
新增白色 SKU
```

应保存：

```text
price_decrease
stock_decrease
sku_sold_out
sku_added
```

不创建“大变化”单条事件，不把多个客观变化压缩成一行。

## 8. 各事件的业务含义与触发条件

### 8.1 `price_decrease` / `price_increase`

价格比较继续沿用当前明确方向规则。只有 previous/current 的 `price_min` 和 `price_max` 都非 `NULL` 时才比较：

```text
current.price_min > previous.price_min
且 current.price_max > previous.price_max
→ price_increase

current.price_min < previous.price_min
且 current.price_max < previous.price_max
→ price_decrease
```

其他情况不产生价格事件，包括：

- 任一价格边界缺失；
- 区间一端上涨、一端不变或下降；
- 区间方向不一致；
- 只有一个边界变化；
- 无法确认方向。

`old_value` / `new_value` 沿用当前稳定字符串：统一价使用 `40.00`，区间价使用 `40.00~45.00`，不带人民币符号。

### 8.2 `stock_decrease` / `stock_increase`

它们表达商品总库存方向，不表达某个 SKU 的普通库存变化。

previous 和 current 都只有在以下条件全部满足时，才得到可比较的商品总库存：

1. 快照至少有一个可识别 SKU；
2. 快照中每个已保存 SKU 的 `stock` 都是非 `NULL` 的非负整数；
3. 快照是正常成功采集产生的完整 Snapshot，而不是解析失败或下架状态。

总库存定义为该快照所有 SKU `stock` 的算术和：

```text
total_stock = sum(all identifiable SKU stock values)
```

比较规则：

```text
current_total < previous_total → stock_decrease
current_total > previous_total → stock_increase
current_total = previous_total → 不产生商品总库存事件
```

事件为商品级事件：`entity_key = NULL`。`old_value` / `new_value` 保存总库存整数的字符串值。

以下情况不能产生 `stock_decrease` 或 `stock_increase`：

- previous 或 current 没有 SKU；
- 任一侧存在 `stock = NULL`；
- 商品页解析失败、字段不完整或保存失败；
- 本次没有有效 ProductSnapshot；
- 只能得到部分 SKU，无法证明快照是完整可比较集合。

未知库存保持未知，不能按 `0` 参与求和，不能用 ChangeEvent 的 SKU 事件值相加代替总库存。

SKU 集合增删本身不阻止总库存比较：只要前后两个 Snapshot 各自满足完整库存条件，就按各自全部可识别 SKU 的总和比较，同时另行产生 `sku_added` / `sku_removed`。

### 8.3 `sku_added`

previous 中不存在该 `sku_id`，current 中存在该 `sku_id`。

每个新增 SKU 独立一条事件：

- `entity_key = sku_id`；
- `old_value = NULL`；
- `new_value = current.sku_name`；
- 不产生 `delta_value` / `delta_rate`。

### 8.4 `sku_removed`

previous 中存在该 `sku_id`，current 中不存在该 `sku_id`。

每个删除 SKU 独立一条事件：

- `entity_key = sku_id`；
- `old_value = previous.sku_name`；
- `new_value = NULL`；
- 不产生 `delta_value` / `delta_rate`。

SKU 消失时只产生 `sku_removed`，不因为旧库存为 0 再产生 `sku_sold_out`。

### 8.5 `sku_sold_out`

只有同一个 `sku_id` 同时存在于 previous 和 current，且库存发生以下转换时产生：

```text
previous.stock > 0
且 current.stock = 0
→ sku_sold_out
```

事件字段：

- `entity_key = sku_id`；
- `old_value = previous.stock` 的字符串值；
- `new_value = "0"`；
- 可保存库存差值；
- 不能与同一次 SKU 删除同时产生。

### 8.6 `sku_restocked`

只有同一个 `sku_id` 同时存在于 previous 和 current，且库存发生以下转换时产生：

```text
previous.stock = 0
且 current.stock > 0
→ sku_restocked
```

事件字段：

- `entity_key = sku_id`；
- `old_value = "0"`；
- `new_value = current.stock` 的字符串值；
- 可保存库存差值；
- 不能与同一次 SKU 新增同时产生。

如果任一侧库存为 `NULL`，不产生 `sku_sold_out` 或 `sku_restocked`。例如 `NULL → 0` 和 `0 → NULL` 都只是未知，不能猜测。

对同一 SKU 的 `10 → 20`、`20 → 10` 等普通非零库存变化，V2 不单独创建 SKU 普通库存事件；若商品总库存因此改变，则由 `stock_increase` / `stock_decrease` 表达商品级客观变化。

### 8.7 `product_offline`

只有当前状态为 `active`，且采集器取得明确、正面的“商品已下架”证据时产生：

- `old_value = "active"`；
- `new_value = "offline"`；
- `entity_key = NULL`；
- `snapshot_id = NULL`；
- `collection_run_id` 必须指向检测到下架的成功 CollectionRun。

下架不创建全 NULL Snapshot，不删除历史 Snapshot，不清空 Competitor 的标题、价格、库存、SKU 或主图摘要，也不修改 `is_active`。

### 8.8 `product_online`

只有 previous Competitor 状态为 `offline`，并且后续一次采集重新成功打开正常商品页并完成标准化时产生：

- `old_value = "offline"`；
- `new_value = "active"`；
- `entity_key = NULL`；
- `snapshot_id` 指向恢复本次新建的 ProductSnapshot；
- `collection_run_id` 指向本次恢复采集的成功 CollectionRun。

恢复上架这一轮只记录 `product_online`，不同时产生价格、商品总库存、SKU、标题或主图普通变化事件。原因是下架期间可能发生了多个未知时点的变化，当前系统只能确认“现在恢复了”，不能把差异归因到恢复这一刻。

恢复 Snapshot 作为下一次 `active → active` 普通比较的基线。

### 8.9 `title_changed`

previous 和 current 的标准化标题都为非空字符串，且 trim 后不相等时产生：

- `entity_key = NULL`；
- `old_value = previous.title`；
- `new_value = current.title`；
- 不产生差值字段。

不使用编辑距离、AI、模糊匹配或标题语义判断。

### 8.10 `main_image_changed`

previous 和 current 都存在已经标准化的非空主图 URL，且 URL 不相等时产生：

- `entity_key = NULL`；
- `old_value = previous.main_image_url`；
- `new_value = current.main_image_url`；
- 不产生差值字段。

任一侧主图为 `NULL`、两侧相同或只有 `image_urls` 详情图库变化时，不产生主图事件。主图事件不比较图片内容 hash，也不比较图库中非首图。

## 9. 第一次采集规则

第一次成功采集的主要作用是建立 baseline：

- 创建 ProductSnapshot；
- 创建全部可识别的 SkuSnapshot；
- 创建成功 CollectionRun；
- 更新 Competitor 当前摘要和状态；
- 不创建价格、总库存、SKU、标题或主图普通事件。

如果没有上一份有效 ProductSnapshot，即使 current 与“没有数据”相比看起来像新增，也不生成 `sku_added` 或其他普通事件。

`unknown → active` 只建立 active 基线，不产生 `product_online`。

`unknown → offline` 只建立 offline 状态，不产生 `product_offline`。

## 10. Snapshot 对比规则

### 10.1 active → active

当上一状态为 `active` 且本次正常采集成功：

1. 在创建 current Snapshot 前读取 previous Snapshot；
2. 按 `captured_at DESC, id DESC` 取同一竞品最近一条；
3. 对 previous 与 current 执行 V2 规则；
4. 保存零条或多条 ChangeEvent；
5. current Snapshot 成为后续比较基线。

### 10.2 offline → active

创建恢复 Snapshot，只生成 `product_online`，不调用普通字段差异检测。下一次正常采集再与恢复 Snapshot 比较。

### 10.3 active → offline

不创建 Snapshot，只生成 `product_offline`，保留最后一个正常 Snapshot 和其全部 SKU。

### 10.4 重复有效采集

如果连续两次有效采集的价格、总库存、SKU 集合与库存状态、标题和主图都没有产生 V2 定义的变化：

- 仍创建新的 ProductSnapshot；
- 仍创建新的 SkuSnapshot；
- 仍创建成功 CollectionRun；
- 不创建 ChangeEvent。

## 11. 商品总库存比较规则

总库存只从当前 Snapshot 下所有可识别 SKU 的 `stock` 计算，不从页面摘要、旧事件或 SKU 名称推断。

### 可比较

previous 和 current 都满足：

- 至少一个 SKU；
- 每个 SKU 的库存均为非 `NULL` 非负整数；
- 本次采集是正常成功并已保存的有效商品 Snapshot。

### 不可比较

任一侧满足以下条件时跳过商品总库存事件：

- 没有 SKU；
- 存在任意未知库存；
- 只解析出部分商品数据；
- 解析异常、网络异常、验证异常、保存异常；
- 本次是下架检查，没有 ProductSnapshot；
- 无法证明当前 Snapshot 的 SKU 库存集合是完整可识别结果。

跳过只影响 `stock_decrease` / `stock_increase`，不阻止在证据充分时保存其他独立事件，例如 `title_changed` 或 `sku_added`。

## 12. SKU 身份判断规则

SKU 身份严格使用 parser/collector 产出的稳定 `sku_id`：

- 相同 `sku_id` 视为同一个 SKU；
- 不同 `sku_id` 即使名称相同，也视为不同 SKU；
- `sku_name` 变化不产生新增或删除；
- 不使用名称、数组位置、颜色文本、价格或库存作为 fallback；
- parser 缺少或无法验证 `sku_id` 时，本次采集按解析失败处理，不进入 ChangeEvent 比较。

当前系统没有新的 SKU 匹配算法。重复 `sku_id` 属于当前采集数据的异常边界，V2 不通过名称或位置为其发明额外身份规则。

## 13. SKU 新增、删除、售罄、恢复关系

比较顺序必须先按 `sku_id` 分出：

- 只在 current 的 ID → `sku_added`；
- 只在 previous 的 ID → `sku_removed`；
- 两侧都存在 → 再判断库存状态转换。

因此：

| previous | current | 事件 |
|---|---|---|
| 不存在 | `stock = 0` | 只有 `sku_added` |
| 不存在 | `stock > 0` | 只有 `sku_added` |
| `stock = 0` | 不存在 | 只有 `sku_removed` |
| `stock > 0` | 不存在 | 只有 `sku_removed` |
| `stock > 0` | `stock = 0` | `sku_sold_out` |
| `stock = 0` | `stock > 0` | `sku_restocked` |
| `stock = NULL` 或 current/previous 缺失 | 任意 | 不产生售罄/恢复事件 |

`sku_removed` 与 `sku_sold_out` 永远不能针对同一个 SKU、同一次采集同时产生。

## 14. 商品下架与恢复规则

### 下架

只有采集器给出已验证的正面下架证据才允许 `product_offline`。

下架成功：

- `Competitor.status = offline`；
- `Competitor.is_active` 保持原值；
- `CollectionRun.status = success`；
- `ProductSnapshot` 数量不增加；
- 历史 Snapshot、SKU、价格、标题、主图均保留；
- `last_collected_at` 更新为本次成功状态检查时间。

### 恢复

正常商品页重新打开且数据成功解析时：

- `Competitor.status = active`；
- `Competitor.is_active` 保持原值；
- 创建新的 ProductSnapshot / SkuSnapshot；
- 创建一个 `product_online`；
- 不创建恢复首轮普通字段事件。

### 重复状态

- `active → active` 不产生生命周期事件；
- `offline → offline` 不产生生命周期事件；
- `active → offline → offline` 只产生一个 `product_offline`；
- `offline → active → active` 只产生一个 `product_online`。

## 15. 一次采集产生多事件规则

ChangeEvent 是事件集合，不是商品版本摘要。一次 CollectionRun 可以同时产生：

- 一条价格事件；
- 一条商品总库存事件；
- 多条 SKU 新增、删除、售罄、恢复事件；
- 一条标题事件；
- 一条主图事件。

每个客观变化各占一行，并共享：

- `competitor_id`；
- `collection_run_id`；
- 同一个 `detected_at`；
- 对应本次 Snapshot（下架事件除外）。

页面层可以按竞品聚合这些事件，但不能把聚合结果回写成单条 ChangeEvent。

实现应保持稳定生成顺序，建议按以下领域顺序生成，顺序不是业务优先级：

1. 价格；
2. 商品总库存；
3. SKU 新增；
4. SKU 删除；
5. SKU 售罄；
6. SKU 恢复；
7. 标题；
8. 主图。

同类型多条 SKU 事件按 `sku_id` 排序。消费者不得依赖插入顺序代替自己的展示优先级。

## 16. ChangeEvent V2 建议数据结构

### 16.1 保留字段

继续使用现有字段，不把 `change_type` 重命名为 `event_type`：

| 字段 | V2 规则 |
|---|---|
| `id` | 主键 |
| `competitor_id` | 必填，发生变化的竞品 |
| `snapshot_id` | 普通事件指向本次 Snapshot；`product_offline` 为 `NULL` |
| `change_type` | 12 种 V2 标准类型，兼容期保留 legacy `stock_changed` |
| `entity_key` | 商品级为 `NULL`；SKU 级为 `sku_id` |
| `old_value` | 稳定、简短的旧事实字符串；没有旧值时为 `NULL` |
| `new_value` | 稳定、简短的新事实字符串；没有新值时为 `NULL` |
| `detected_at` | 本次检测时间，保存 UTC 事实 |

不保存完整 Snapshot JSON、HTML、Cookie、Token、请求头或页面原始结构。

### 16.2 新增 `collection_run_id`

V2 新增 `collection_run_id`，形成正式的：

```text
ChangeEvent → CollectionRun
```

关系。

原因：每条变化都来自一次具体采集；尤其 `product_offline` 没有 ProductSnapshot，必须通过 CollectionRun 追溯发现来源。

由于历史事件无法可靠地按时间反推对应 Run，字段在数据库层保持 nullable：

- 历史事件允许 `collection_run_id = NULL`；
- V2 新生成的事件必须填入当前 Run ID；
- 不根据 `detected_at`、`started_at` 或时间相近关系回填旧事件；
- 外键删除行为沿用现有历史数据保留边界，不通过级联删除事件。

### 16.3 新增 `delta_value`

增加可空数值字段 `delta_value`，仅用于有明确数值差异的事件：

```text
delta_value = new numeric value - old numeric value
```

使用范围：

- `price_increase` / `price_decrease`：两侧都是统一价时使用；
- `stock_increase` / `stock_decrease`：使用商品总库存差值；
- `sku_sold_out` / `sku_restocked`：使用该 SKU 库存差值。

价格区间一侧或两侧不是统一价时，`delta_value = NULL`，因为一个区间没有单一、无歧义的价格差值。标题、主图、SKU 新增、SKU 删除和生命周期事件不保存差值。

### 16.4 新增 `delta_rate`

增加可空数值字段 `delta_rate`，单位为百分比数值，不保存 `%` 字符：

```text
delta_rate = (new - old) / old × 100
```

规则：

- 只在 old 是非零且两侧数值可靠时计算；
- old 为 0 时 `delta_rate = NULL`，但 `delta_value` 仍可保存；
- 价格区间事件不计算单一变化率；
- 标题、主图、SKU 新增、SKU 删除和生命周期事件为 `NULL`；
- 差值和变化率的精度、舍入由数据库 Numeric 类型和现有 Decimal 约定统一实现，不把格式化百分号存入字段。

示例：

```text
42 → 35
delta_value = -7
delta_rate = -16.666...  （展示层可格式化为 -16.67%）

8240 → 3110
delta_value = -5130
delta_rate = -62.257...  （展示层可格式化为 -62.26%）

0 → 500
delta_value = 500
delta_rate = NULL
```

## 17. ChangeEvent 与 ProductSnapshot 的关系

普通 ChangeEvent 的 `snapshot_id` 必须指向发现变化时新建的 ProductSnapshot，而不是 previous Snapshot：

```text
ChangeEvent.snapshot_id = current ProductSnapshot.id
```

关系规则：

- `price_*`、`stock_*`、`sku_*`、`title_changed`、`main_image_changed`、`product_online` 必须有关联 Snapshot；
- `product_offline` 必须没有 Snapshot；
- 下架不创建占位 Snapshot；
- 恢复上架的 `product_online` 指向恢复本次新 Snapshot；
- 不删除、不修改 previous Snapshot 来模拟状态转换。

数据库约束继续保证事件类型与 `snapshot_id` 的基本对应关系；同一竞品关系的业务一致性由保存事务保证。

## 18. ChangeEvent 与 CollectionRun 的关系

ChangeEvent V2 的正式关系为：

```text
CollectionRun 1 ─── N ChangeEvent
```

一次 Run 可以没有事件，也可以有多条事件：

- 首次成功采集：成功 Run，0 条 ChangeEvent；
- 连续相同采集：成功 Run，0 条 ChangeEvent；
- 多种变化同时发生：成功 Run，多条 ChangeEvent；
- 明确下架：成功 Run，可能 1 条 `product_offline`，没有 Snapshot；
- 失败 Run：不产生本次采集的 ChangeEvent。

正常成功的 ProductSnapshot、SkuSnapshot、ChangeEvent、Competitor 当前摘要和 `CollectionRun.success` 必须在一个业务保存事务中提交。采集失败或保存失败不得留下半套事件事实。

## 19. 历史 ChangeEvent 兼容策略

### 19.1 推荐方案：保留历史，V2 新写方向事件

推荐采用方案 C：

1. 不删除任何历史 ChangeEvent；
2. 不默认把历史 `stock_changed` 改写成 `stock_increase` 或 `stock_decrease`；
3. V2 新采集只生成 `stock_increase` / `stock_decrease`，不再生成新的 `stock_changed`；
4. 兼容期数据库 CHECK 继续允许 `stock_changed`，让旧数据可读；
5. 消费者同时识别 V2 新事件和历史 legacy `stock_changed`；
6. legacy `stock_changed` 的方向未知时，不在消费者中猜测。

### 19.2 为什么不采用直接全量转换

当前正式生成逻辑确实把 SKU 库存保存为字符串整数，现有本地数据库中的历史 `stock_changed` 样本也都是可解析的整数对。但数据库字段本身是普通字符串，没有约束保证所有历史写入路径都遵守该格式。

因此，直接把所有旧行改名存在两个问题：

- 对非整数、空值或不符合旧约定的历史数据可能产生伪造方向；
- 改写历史 `change_type` 会改变已有消费者看到的历史事实语义。

V2 的目标是统一未来事件，不是重写历史。

### 19.3 可选的未来历史分析

如果未来确实需要历史方向统计，可以另行做只读分析或独立、经过审计的 backfill：

- 只有 old/new 都能严格解析为非负整数且不相等时，才允许分类；
- old < new 才能分类为 increase；
- old > new 才能分类为 decrease；
- 其他情况保持 `stock_changed`，不猜；
- 该 backfill 不属于本 V2 migration，也不作为 V2 上线前提。

## 20. Migration 原则

正式实现预计需要一个 SQLite 安全 migration，具体 revision 名称由实现阶段按仓库约定确定。

迁移至少覆盖：

- `change_type` CHECK 增加四种库存方向/SKU 状态事件，继续允许 legacy `stock_changed`；
- 增加 nullable `collection_run_id` 外键；
- 增加 nullable `delta_value`；
- 增加 nullable `delta_rate`；
- 同步 ORM 模型约束和字段；
- 保留现有字段、索引、外键和所有行。

SQLite 约束重建必须：

- 使用 Alembic batch/recreate 方式；
- 在重建前后保持外键和索引语义；
- 不执行历史事件删除或默认值填充；
- 不按时间猜测历史 `collection_run_id`；
- 不自动转换历史 `stock_changed`；
- 在失败时不留下临时表或部分迁移状态。

### Downgrade

如果数据库中已存在 V2 专用事件，或存在无法由旧 schema 表示的非空 `collection_run_id`、`delta_value`、`delta_rate`，downgrade 必须明确拒绝，而不是静默丢失列或事件语义。

只有在没有 V2 专用数据、所有新增字段仍为 `NULL` 时，才允许恢复旧 CHECK 和旧字段集合。

## 21. Dashboard / Detail / List / Groups 兼容影响

本轮不设计 UI，只冻结后续实现需要同步修改的旧依赖。

### 21.1 Dashboard

当前 Dashboard 直接按 `stock_changed` 聚合、统计、解析 SKU 名称和计算商品总库存投影。V2 实现时需要：

- 把 `stock_increase` / `stock_decrease` 纳入库存变化集合；
- 把 `sku_sold_out` / `sku_restocked` 纳入 SKU 变化集合；
- lifecycle、price、product stock、SKU、main image、title 继续作为不同事件领域；
- 新库存事件优先使用 `old_value` / `new_value` / `delta_*`，不重新从两个 Snapshot 推断方向；
- 对 legacy `stock_changed` 保留旧兼容路径，不将其强行分类；
- 现有商品一行、事件逐条计数和按 active Competitor 过滤原则保持不变；
- 现有 `stock_changed_*` 字段如继续存在，需要明确兼容命名，不把新方向事件误报为旧类型；
- primary 展示优先级保持“生命周期 > 价格 > 商品总库存 > SKU > 主图 > 标题”，同一领域内按检测时间和 ID 决定最近事件。

### 21.2 Competitor Detail

Detail 当前返回通用 `recent_changes`，并对 `stock_changed` 做 SKU 名称回溯。V2 实现时需要：

- 保持通用事件响应，不新建每种事件专用表；
- 商品级 `stock_increase` / `stock_decrease` 不绑定 SKU 名称；
- `sku_sold_out` / `sku_restocked` 通过 `entity_key = sku_id` 回溯名称；
- `sku_added` / `sku_removed` 继续按事件值或 Snapshot 事实展示；
- `product_offline` 继续允许 `snapshot_id = NULL`；
- 详情中的最新价格仍只筛选两种价格事件；
- 旧 `stock_changed` 记录继续可读，不被当作新方向事件。

### 21.3 Competitor List

列表的 `latest_change` 是最近一条真实 ChangeEvent 的通用投影，排序仍为 `detected_at DESC, id DESC`。

后续实现需要：

- 增加 12 种标准类型的展示映射；
- 保留 legacy `stock_changed` 展示映射；
- 不在前端通过 old/new 值重新判断库存方向；
- 不把 `latest_change` 扩展成完整事件历史或筛选接口；
- 保持 `NULL` 就表示没有历史事件，不填充虚假默认值。

### 21.4 Competitor Groups

竞品组当前按时间范围内的 ChangeEvent 统计 distinct competitor 和最近变化时间，不依赖某个具体库存事件名称。

后续实现需要：

- 继续按 ChangeEvent 事实统计，不修改历史事件；
- 新旧事件类型都计入“发生过变化”的统一口径；
- 如果未来增加按变化类型筛选，应使用 V2 领域集合，同时单独定义 legacy `stock_changed` 的处理；
- 本 V2 不新增 Group Detail、横向分析或新的组接口。

## 22. 边界情况

- previous 没有 Snapshot：建立 baseline，不生成普通事件。
- current 解析失败：不创建 Snapshot、SKU 或 ChangeEvent，Run 为 failed。
- current 为验证页、登录页、网络错误或空白页：不生成 `product_offline`。
- previous/current 价格缺失：不生成价格事件。
- 价格区间方向不一致：不生成价格事件。
- 商品总库存任一未知：不生成商品总库存事件。
- 总库存为 0 是有效事实；0 → 正数可产生 `stock_increase`，正数 → 0 可产生 `stock_decrease`。
- SKU `NULL → 0`、`0 → NULL`：不生成售罄/恢复。
- SKU 消失：只生成 `sku_removed`，不生成售罄。
- SKU 新出现：只生成 `sku_added`，不生成恢复有货。
- SKU 名称改变但 ID 相同：不生成新增或删除。
- 主图一侧缺失：不生成主图变化。
- `image_urls` 详情图库变化但首图不变：不生成主图变化。
- active → offline：没有 Snapshot 的 `product_offline`，但必须有 CollectionRun 关系。
- offline → active：只生成 `product_online`，不生成恢复首轮普通事件。
- offline → offline：不创建空 Snapshot，不重复生命周期事件。
- 同一 Run 多条事件：共享 `detected_at` 和 `collection_run_id`，不合并。
- 历史事件缺少 `collection_run_id`：允许作为 legacy 历史事实，不回填猜测值。
- 历史 `stock_changed` 无法严格解析方向：保持 legacy，不猜。
- 事件展示排序不能把数据库插入顺序当作业务重要度。
- 0 除错误率：old 为 0 时 `delta_rate` 必须为 `NULL`。

## 23. Testing Decisions

测试优先验证外部行为、事件内容、持久化关系、数据保留和 API 合同，不测试某个私有函数的实现形式。优先复用当前纯变化检测、collection service、SQLite migration、TestClient、Dashboard、Detail、List 和 Groups 测试 seam。

### 23.1 标准事件规则

至少覆盖：

1. 第一次成功采集产生 0 条普通 ChangeEvent；
2. 连续相同采集产生新 Snapshot、SKU、成功 Run，但 0 条事件；
3. 价格统一价上涨/下降；
4. 价格区间完整同向变化；
5. 价格缺失、单边变化、方向不一致均不产生价格事件；
6. 完整总库存上升/下降；
7. 总库存相等不产生事件；
8. 任一库存缺失、无 SKU、解析失败均跳过商品总库存事件；
9. 0 参与总库存求和，且不被当作未知；
10. SKU 新增、删除按 ID 独立生成；
11. 相同 ID 改名不产生 add/remove；
12. `>0 → 0` 产生 `sku_sold_out`；
13. `0 → >0` 产生 `sku_restocked`；
14. SKU 消失不同时产生售罄；
15. SKU 新增不同时产生恢复有货；
16. `NULL` 库存不产生售罄/恢复；
17. 标题和主图变化符合当前标准化边界；
18. 一次采集可以产生多条独立事件；
19. 每条普通事件指向本次 Snapshot；
20. 所有本次事件共享当前 Run 和 `detected_at`。

### 23.2 生命周期与失败隔离

覆盖：

- `unknown → active`：baseline，无 `product_online`；
- `unknown → offline`：状态基线，无 `product_offline`；
- `active → offline`：成功 Run、无 Snapshot、一个 `product_offline`；
- `offline → offline`：无事件、无空 Snapshot；
- `offline → active`：新 Snapshot、一个 `product_online`、无普通差异事件；
- 恢复后的下一轮 active 采集可以产生普通事件；
- 验证、登录、网络、超时、空白和 parser 失败均不改变商品状态，不产生事件；
- `is_active` 与商品 `status` 独立；
- 下架保留旧 Snapshot、旧 SKU、旧价格、旧标题和旧主图；
- 保存失败时 Snapshot、SKU、事件、Competitor 更新和成功 Run 一起回滚，Run 记录失败。

### 23.3 Schema 与 migration

覆盖：

- 12 种 V2 类型可写入；
- legacy `stock_changed` 仍可读；
- 不支持的类型仍被拒绝；
- `product_offline` 允许 NULL Snapshot，其他事件拒绝 NULL Snapshot；
- 新事件的 `collection_run_id`、差值字段可保存；
- 历史事件的新增字段保持 NULL；
- upgrade 保留所有既有行、索引和外键；
- 有 V2 数据时 downgrade 明确拒绝；
- 无 V2 数据时 clean upgrade/downgrade/upgrade 成功；
- 失败或拒绝 downgrade 后不残留 SQLite 临时表。

### 23.4 消费者合同

覆盖：

- Dashboard 同一竞品仍只显示一行，但事件数逐条统计；
- Dashboard 同时识别新库存方向事件、SKU 售罄/恢复和 legacy `stock_changed`；
- Detail 正确返回商品级库存事件、SKU 级售罄/恢复和 nullable Snapshot；
- List `latest_change` 返回真实新旧事件类型，不进行前端方向推断；
- Groups 的变化竞品数同时兼容新旧事件；
- Asia/Shanghai 业务日边界不改变；
- 无事件时仍返回 `NULL`，不填充默认变化。

## 24. Acceptance Criteria

1. 数据库和业务规则冻结 12 种 V2 标准事件。
2. 新库存事件按商品总库存方向生成，`stock_changed` 不再作为新写入类型。
3. SKU 售罄和恢复只对两侧都存在且库存分别发生 `>0 → 0`、`0 → >0` 的同一 `sku_id` 生成。
4. 第一次有效采集只建立 baseline。
5. 恢复上架首轮只生成 `product_online`。
6. 明确下架以外的失败、验证、空白和解析异常不生成 `product_offline`。
7. 缺失库存不参与总库存比较，不被当作 0。
8. 每条新 V2 事件可追溯到发现它的 CollectionRun；历史事件不强行回填。
9. `delta_value` / `delta_rate` 只用于有可靠数值语义的价格或库存事件。
10. 非数值事件不保存无意义差值。
11. 历史数据不删除、不伪造、不默认重命名。
12. 现有 Dashboard、Detail、List、Groups 的消费边界在实现阶段同步兼容。
13. 实现阶段通过纯规则、采集服务、migration 和消费者回归测试。

## 25. Out of Scope

本 Spec 之外的所有能力继续保持不实现：变化重要度、风险、阈值、提醒、消息、AI、销量、报表、多平台、新页面、新字段、复杂匹配算法和架构重构。

## 26. 需要产品确认的问题

当前没有需要产品确认的问题。

理由：

- 12 种标准事件及库存/SKU/生命周期语义已由本轮需求明确；
- 恢复首轮只记录 `product_online` 已按倾向方案冻结；
- 当前代码和文档足以确定 SKU 身份、总库存完整性和下架证据边界；
- 历史 `stock_changed` 采用保留 legacy、未来新写方向事件的兼容策略，不需要额外产品语义选择。

## 27. Further Notes

- 本 Spec 只定义客观事件，不定义事件展示文案和 UI 排版。
- `detected_at` 仍表示检测时间，不应被页面描述为平台真实发生时间。
- V2 实现前应继续以当前真实数据库字段和采集能力为准，不把文档中的未来字段提前当作已有事实。
- 本文完成后不自动修改长期数据模型文档；待实现、migration、测试和消费者同步完成后，再同步长期文档中的“当前已实现”部分。
- 本轮不发布 issue tracker，不新增 ready-for-agent 标签，不修改代码、模型、migration、测试或前端。
