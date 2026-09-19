# 单次采集后的快照变化检测 / ChangeEvent Feature Spec

## 1. Problem Statement

当前系统已经可以在一次成功的手动采集后保存：

- `ProductSnapshot`；
- `SkuSnapshot`；
- `CollectionRun`；
- 竞品的当前基础信息。

每次成功采集都会新增快照，不覆盖历史事实。但系统还不能回答：

> 这次采集相比该竞品上一次成功采集，具体发生了什么变化？

本 Feature 为一次成功采集建立变化检测结果。变化结果必须来自两份真实的标准化快照事实，不能由前端推断，也不能根据未来规划字段或外部 1688 原始数据伪造。

本轮只写 Spec，不修改业务代码、Migration、Frontend 或 `docs/data-model.md`。

## 2. Feature Goal

对每个成功保存的新快照：

1. 找到同一 `competitor_id` 在新快照创建前的最近一份成功 `ProductSnapshot`；
2. 将旧快照与本次采集得到的标准化 `ProductData` 比较；
3. 为当前明确支持的每个变化生成一条 `ChangeEvent`；
4. 让 `ChangeEvent.snapshot_id` 永远指向本次新快照；
5. 首次成功采集只建立 baseline，不生成事件；
6. 让事件与新快照、SKU 快照、竞品当前信息和成功的 `CollectionRun` 在同一成功事务中提交。

连续两次采集事实相同仍然会保存新快照，但不保存任何 `ChangeEvent`。

## 3. Current Data Boundary

本 Feature 只依赖当前已经存在的内部标准化字段：

| 数据 | 当前能力 | 本 Feature 用途 |
|---|---|---|
| 商品标题 | 可靠 | `title_changed` |
| 店铺名称 | 可靠 | 仅随新快照保存，不检测变化 |
| 商品级价格 | 当前测试商品可靠 | `price_increase` / `price_decrease` |
| SKU ID、SKU 名称 | 可靠 | `sku_added` / `sku_removed`，名称只用于事件值 |
| SKU 库存 | 当前测试商品可靠 | `stock_changed` |
| 主图 URL | 当前始终为 `None` | 不检测 |
| 商品状态 | 基本为 `unknown` | 不检测下架 |
| SKU 独立价格 | 通常为 `None` 且不可靠 | 不检测 |
| 销量 | 不在 Snapshot 中 | 不检测 |

业务规则只依赖 `ProductSnapshot`、`SkuSnapshot` 和标准化 `ProductData`，不依赖 `skuInfoMap`、`canBookCount` 等 1688 外部字段名。

## 4. Solution

### 4.1 ChangeEvent 数据模型

正式创建 `ChangeEvent` 表，至少包含：

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

字段语义：

| 字段 | 规则 |
|---|---|
| `id` | 主键 |
| `competitor_id` | 必填，指向 `Competitor` |
| `snapshot_id` | 必填，指向本次新建的 `ProductSnapshot` |
| `change_type` | 必填，只能使用本 Feature 冻结的支持集合 |
| `entity_key` | 商品级变化为 `NULL`；SKU 级变化保存 `sku_id` |
| `old_value` | 简短、稳定、可读的旧值；没有旧值时为 `NULL` |
| `new_value` | 简短、稳定、可读的新值；没有新值时为 `NULL` |
| `detected_at` | 必填，保存变化被检测到的明确时间值 |

`old_value` 和 `new_value` 不保存完整 Snapshot JSON、1688 原始字段、HTML、Cookie、Token 或请求头。

所有 Schema 修改必须通过 Alembic migration。表结构应至少保证两个外键有效，并为按竞品和时间读取最近事件提供必要索引；不新增事件总线、聚合表或每种变化独立的表。

### 4.2 Previous Snapshot 选择

对一次新采集，比较基线严格定义为：

```text
old = 当前 competitor 在本次新 ProductSnapshot 创建之前的最近一条 ProductSnapshot
排序：captured_at DESC, id DESC
new = 本次采集得到的标准化 ProductData / 即将保存的新 ProductSnapshot
```

实现必须在新快照插入前读取旧快照，或使用等价的明确排除逻辑，不能让本次新快照成为自己的比较基线。

不允许：

- 与第一条历史快照比较；
- 与某个自然日或“昨天”绑定；
- 同时比较多个历史快照；
- 使用 `CollectionRun` 作为变化基线。

变化检测永远表示：

```text
上一次成功事实 vs 这一次成功事实
```

如果 `old` 不存在，本次是 baseline：保存新快照及其 SKU 快照，不生成 `ChangeEvent`。

### 4.3 当前支持的 change_type

本 Feature 当前只支持：

```text
price_increase
price_decrease
sku_added
sku_removed
stock_changed
title_changed
```

不支持的类型不得通过特殊值、空值或推测逻辑写入事件。

#### 4.3.1 商品价格变化

只有旧、新两份数据的 `price_min` 和 `price_max` 均为可靠非空值时，才允许进行价格方向判断。任何缺失价格都不能转换为 `0`，也不产生价格事件。

记：

```text
(old_min, old_max)
(new_min, new_max)
```

规则：

```text
new_min > old_min 且 new_max > old_max
→ price_increase

new_min < old_min 且 new_max < old_max
→ price_decrease
```

其他情况不产生价格事件，包括方向不一致、仅一个边界变化或边界相等：

```text
40~50 → 40~55
40~50 → 42~48
```

统一价自然属于区间两端相同的情况：

```text
40 / 40 → 45 / 45
→ price_increase
```

价格事件的值使用稳定显示字符串，不携带人民币符号作为数据语义：

- 统一价：`40.00`；
- 区间价：`40.00~45.00`。

`old_value` 保存旧价格显示，`new_value` 保存新价格显示，`entity_key = NULL`。

#### 4.3.2 SKU 新增与删除

SKU 身份只由 `sku_id` 决定，禁止使用 `sku_name` 判断身份。

```text
new sku ids - old sku ids → sku_added
old sku ids - new sku ids → sku_removed
```

每个新增或删除的 SKU 独立保存一条事件：

| 类型 | `entity_key` | `old_value` | `new_value` |
|---|---|---|---|
| `sku_added` | 新 SKU 的 `sku_id` | `NULL` | 新 SKU 的 `sku_name` |
| `sku_removed` | 旧 SKU 的 `sku_id` | 旧 SKU 的 `sku_name` | `NULL` |

如果 `sku_id` 相同但 `sku_name` 改变，当前 Feature 不定义 `sku_renamed`，也不得错误地产生 `sku_removed` 和 `sku_added`。

#### 4.3.3 SKU 库存变化

对同一个 `sku_id`，仅在以下条件全部成立时生成 `stock_changed`：

```text
old.stock != NULL
new.stock != NULL
old.stock != new.stock
```

事件字段：

```text
entity_key = sku_id
old_value = 旧库存的字符串表示
new_value = 新库存的字符串表示
```

库存 `0` 是真实数值，以下情况必须检测：

```text
0 → 10
10 → 0
```

以下情况不产生事件：

```text
NULL → 100
100 → NULL
NULL → NULL
```

#### 4.3.4 商品标题变化

只有旧、新标题都是有效的非空标准化字符串，且两者实际不相等时，才生成：

```text
change_type = title_changed
entity_key = NULL
old_value = 旧标题
new_value = 新标题
```

当前标准化沿用采集服务已有的字符串清理边界；不做模糊匹配、AI 判断、编辑距离或大小写/标点推断。

### 4.4 变化检测位置

变化判断属于 Backend 业务规则。实现应放在一个简单、可测试的后端变化检测边界，优先采用一个小的 `changes` 模块，由现有 collection service 在成功保存流程中调用。

变化检测不得放在：

- React；
- 1688 Parser；
- Playwright Collector；
- FastAPI Router。

不创建 `ChangeManager`、`ChangeRepository`、Strategy Factory、Event Bus 或 Rule Engine。

建议检测函数接收“旧快照事实”和“新标准化事实”，返回待保存的事件值；它不负责数据库提交，不负责外部采集，也不负责 HTTP 响应。

### 4.5 Transaction Boundary

Playwright 和外部网络采集阶段不得持有数据库事务。

采集、标准化、旧快照读取完成后，成功保存事务必须同时包含：

1. 新建 `ProductSnapshot`；
2. 新建全部 `SkuSnapshot`；
3. 根据旧快照与新事实生成并保存全部 `ChangeEvent`；
4. 更新 `Competitor` 当前基础信息和 `last_collected_at`；
5. 将 `CollectionRun` 标记为 `success`；
6. 一次性 `commit`。

第一次采集没有旧快照时，第 3 步保存零条事件，但仍属于同一成功事务。

成功保存事务任一步失败时：

1. 回滚 `ProductSnapshot`、`SkuSnapshot`、`ChangeEvent`、`Competitor` 更新和成功状态；
2. 使用短的失败事务将该 `CollectionRun` 标记为 `failed`；
3. `error_type` 固定为 `collection_save_failed`；
4. 不留下孤立的快照、SKU 或事件。

因此不能出现：

- Snapshot 成功但 ChangeEvent 丢失；
- ChangeEvent 存在但 Snapshot 已回滚；
- `CollectionRun = success` 但 ChangeEvent 保存失败。

Collector、登录、验证、超时或解析失败时，不进入变化检测，不新增 Snapshot、SkuSnapshot 或 ChangeEvent；沿用现有失败处理，且不覆盖上一份成功事实。

## 5. API Read Strategy

本 Feature 选择在现有 `GET /api/competitors` 中增加一个极小的真实投影 `latest_change`，不把完整 ChangeEvent 集合塞进竞品列表，也不实现 Frontend UI。

### 5.1 `latest_change` Contract

每个竞品最多返回一条最近真实事件：

```text
latest_change: ChangeEventSummary | NULL
```

`ChangeEventSummary` 只包含已有事件中的真实字段：

```text
id
snapshot_id
change_type
entity_key
old_value
new_value
detected_at
```

读取排序固定为：

```text
detected_at DESC, id DESC
```

没有事件时返回 `null`，不返回虚构的 `change_type`、默认值或“最近变化”文本。该投影满足后续竞品列表展示最近一条变化的需要；Dashboard 或历史变化页面仍应直接基于 `ChangeEvent` 查询，不把 `latest_change` 当作趋势数据或完整历史。

本 Feature 不增加变化筛选、分页、趋势聚合或批量事件接口。

## 6. User Stories

1. 作为竞品监控用户，我希望第一次成功采集只建立 baseline，以免系统把初始数据误报成变化。
2. 作为竞品监控用户，我希望每次后续成功采集都与上一次成功事实比较，以便知道变化确实发生在两次成功采集之间。
3. 作为竞品监控用户，我希望价格只有在涨跌方向明确时才报警，以免价格区间变化被误判。
4. 作为竞品监控用户，我希望 SKU 通过稳定的 `sku_id` 识别，以免规格名称变化造成错误的新增或删除。
5. 作为竞品监控用户，我希望库存从或变为 `0` 时仍被识别，以便看到售罄或恢复库存等真实变化。
6. 作为竞品监控用户，我希望缺失库存或价格只表示采集可用性不足，而不是被解释成业务变化。
7. 作为后续列表和 Dashboard 的使用者，我希望变化记录指向新快照，以便追溯变化对应的成功采集事实。
8. 作为系统维护者，我希望变化记录与快照在同一事务提交，以免出现无法解释的半成功数据。

## 7. Testing Decisions

测试以外部行为为主，优先测试变化检测纯业务边界和 collection service 的事务行为，不测试实现细节或外部 1688 页面。

### 7.1 变化规则测试

至少覆盖：

1. 第一次成功采集 → 0 `ChangeEvent`；
2. 连续相同快照 → 0 `ChangeEvent`；
3. 统一价格上涨 → `price_increase`；
4. 统一价格下降 → `price_decrease`；
5. 价格为 `None` → 不产生价格变化；
6. 价格区间方向不一致 → 不产生 price event；
7. SKU 新增 → `sku_added`；
8. SKU 删除 → `sku_removed`；
9. `sku_id` 相同、仅名称变化 → 不产生 add/remove；
10. 库存 `10 → 20` → `stock_changed`；
11. 库存 `0 → 10` → `stock_changed`；
12. 库存 `None → 10` → 不产生 `stock_changed`；
13. 标题 `A → B` → `title_changed`；
14. 多种变化同时发生 → 多条彼此独立的事件；
15. 所有事件的 `snapshot_id` 都关联新快照。

### 7.2 持久化和失败测试

使用最小内部 `ProductData` 和数据库测试数据验证：

- 旧快照按 `captured_at DESC, id DESC` 选择；
- 新快照尚未创建时才读取上一份成功快照；
- 首次采集没有旧快照时只保存 baseline；
- ChangeEvent 保存失败时 Snapshot、SKU、Competitor 更新全部 rollback，`CollectionRun` 为 `failed` 且 `error_type = collection_save_failed`；
- Collector 失败时不做变化检测、不产生 ChangeEvent，且不覆盖旧成功数据；
- 连续相同事实仍然新增 Snapshot、SkuSnapshot 和成功 CollectionRun，但事件数为零。

### 7.3 API 测试

验证 `GET /api/competitors`：

- 有事件时只返回一条真实 `latest_change`；
- `latest_change` 的字段值来自真实 `ChangeEvent`；
- 多条事件时按 `detected_at DESC, id DESC` 选择；
- 没有事件时返回 `latest_change = null`；
- 不返回完整事件数组、伪造变化字段或未来未支持的事件类型。

## 8. Acceptance Criteria

1. 成功采集有旧快照时，系统按 `captured_at DESC, id DESC` 选择上一份成功 `ProductSnapshot`。
2. 第一次成功采集只建立 baseline，`ChangeEvent` 数量为 0。
3. 连续相同事实保存新快照，但 `ChangeEvent` 数量为 0。
4. 当前支持的 `change_type` 只有 `price_increase`、`price_decrease`、`sku_added`、`sku_removed`、`stock_changed`、`title_changed`。
5. 统一价格明确上涨时生成 `price_increase`。
6. 统一价格明确下降时生成 `price_decrease`。
7. 任一价格边界缺失或区间方向不一致时不生成价格事件。
8. SKU 新增和删除按 `sku_id` 比较，每个 SKU 独立生成事件。
9. 相同 `sku_id` 仅名称变化时不生成新增或删除事件。
10. 两个非空库存不同，包含 `0` 的变化时，生成 `stock_changed`。
11. 任一库存值为 `NULL` 时不生成 `stock_changed`。
12. 两个有效非空标准化标题不相等时生成 `title_changed`。
13. 每条 `ChangeEvent` 的 `snapshot_id` 都指向本次新建的 `ProductSnapshot`。
14. `old_value` / `new_value` 只保存稳定、简短、可读字符串，不保存完整 Snapshot JSON、原始 1688 字段或 HTML。
15. `ProductSnapshot`、全部 `SkuSnapshot`、全部 `ChangeEvent`、Competitor 当前信息和 `CollectionRun.success` 在同一成功事务中提交。
16. ChangeEvent 保存失败时，Snapshot、SKU、Competitor 更新全部 rollback，`CollectionRun` 标记为 `failed`，`error_type = collection_save_failed`。
17. Collector 失败时不做变化检测、不生成 ChangeEvent。
18. `GET /api/competitors` 最多返回一条真实 `latest_change`；无事件时为 `null`，不嵌入完整事件集合。
19. 不实现 Frontend UI，不改变当前前端页面行为。
20. 所有 Schema 修改通过正式 Alembic migration 实现；本次 Spec-only 交付不创建 migration。

## 9. Non-goals

本 Feature 明确不实现：

- `sales_increase`；当前 Snapshot 没有销量字段；
- `product_offline`；当前 Parser 没有可靠下架判定；
- `main_image_changed`；当前 `main_image_url` 没有真实采集值；
- SKU 独立价格变化；当前 SKU 价格不可靠；
- Daily scheduler；
- 7 天 / 30 天趋势；
- Dashboard 页面；
- 通知；
- AI 分析；
- 批量采集；
- 复杂规则引擎、Strategy Factory、Event Bus 或 Manager；
- fuzzy matching、编辑距离或 AI 标题判断；
- Network/XHR 扩展；
- Parser 能力扩展；
- Frontend redesign；
- 修改 `docs/data-model.md`；
- 修改任何业务代码或 Migration（本轮仅写 Spec）。

## 10. Relation to Long-term V1 Model

`docs/data-model.md` 中列出的完整 V1 目标集合包含：

```text
price_increase
price_decrease
sales_increase
sku_added
sku_removed
stock_changed
product_offline
title_changed
main_image_changed
```

本 Feature 只冻结其中的可验证子集：

```text
price_increase
price_decrease
sku_added
sku_removed
stock_changed
title_changed
```

长期目标集合是产品方向，不代表当前采集能力已经存在。`sales_increase`、`product_offline` 和 `main_image_changed` 在未来各自具备可靠数据来源和判断规则后，才能通过独立变更加入支持集合。

本轮不先同步 `docs/data-model.md`。待实际代码、Migration、测试和运行结果稳定后，再更新长期数据模型文档，明确当前已实现子集与未来目标集合的差异。

## 11. Unknowns

以下问题不阻塞本 Feature，但不得在本轮通过猜测固化：

- 未来销量字段的可靠来源、统计口径和历史保存方式；
- 商品下架需要哪些稳定的 1688 页面证据；
- 主图 URL 的可靠提取和图片内容变化判定方式；
- SKU 独立价格何时达到可作为事实保存和比较的可靠程度；
- ChangeEvent 的长期保留、归档或清理策略；
- Dashboard 需要的历史事件聚合、趋势和分页 API；
- 未来是否需要按一次采集返回“变化集合”而不是单条 `latest_change`。

这些 Unknown 不得通过默认值、伪造字段或扩大本 Feature 的支持范围解决。

## 12. Delivery Verification

本次交付只允许新增：

```text
docs/specs/detect-competitor-changes.md
```

交付前必须确认：

- `git status --short` 只显示上述新增 Spec（若工作树另有用户改动，必须保留并单独说明）；
- `git diff --check` 通过；
- 不 commit；
- 不修改业务代码、Migration、Frontend 或其他文档。
