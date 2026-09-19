# Data Model

## 1. 文档范围

本文只描述 1688 竞品监控的数据模型，并明确区分：

- **当前已实现**：当前 ORM、数据库表、迁移和采集流程已经支持的事实；
- **未来 V1 计划**：产品目标中仍保留、但当前没有对应数据库模型或可靠业务能力的部分。

当前数据库已经实现 5 个实体：

~~~text
Competitor
 ├── ProductSnapshot
 │      └── SkuSnapshot
 ├── CollectionRun
 └── ChangeEvent
        └── snapshot_id → ProductSnapshot
~~~

CompetitorGroup 当前尚未实现，不属于当前数据库实体。

---

## 2. 当前已实现：Competitor

表示一个被监控的 1688 商品。

当前字段：

~~~text
id
group_id
platform
offer_id
url
title
shop_name
main_image_url
status
is_active
created_at
updated_at
last_collected_at
~~~

说明：

- platform 当前固定为 1688；
- platform + offer_id 具有唯一约束；
- url 保存标准化后的商品链接；
- group_id 当前可为 NULL，但没有 competitor_groups 表、ORM、外键或分组 CRUD；
- title、shop_name、main_image_url 保存最近一次成功采集得到的当前信息；
- main_image_url 当前允许为 NULL，尚未成为可靠的图片变化事实来源；
- last_collected_at 只在成功采集后更新；
- is_active 表示是否继续监控。

status 当前允许：

~~~text
unknown
active
offline
~~~

当前 1688 Parser 尚没有可靠的下架判定，因此正式采集通常仍使用 unknown，不能把 offline 描述成已经稳定支持的采集能力。

---

## 3. 当前已实现：ProductSnapshot

表示某个竞品某次成功采集时的商品级事实快照。

当前字段：

~~~text
id
competitor_id
captured_at
title
shop_name
main_image_url
price_min
price_max
product_status
collection_source
~~~

说明：

- 每次成功采集新增一条快照，不覆盖历史快照；
- 当前手动“立即采集”也会生成快照；
- 每日自动调度尚未实现，不能将“每天一次”描述成当前保存规则；
- price_min / price_max 使用 Numeric(18, 2)，用于保存商品级价格区间；
- 缺失价格保存为 NULL，不转换为 0；
- product_status 当前允许 unknown、active、offline；
- collection_source 当前数据库允许：
  - html
  - network
  - mixed
- 当前正式 Collector 主要通过 HTML / 内嵌 JSON 解析，实际主要保存 html；Network/XHR 是后续能力。

快照只保存当次真实采集到的事实，不保存“涨价”“销量上涨”等判断结果；变化判断由 ChangeEvent 表达。

---

## 4. 当前已实现：SkuSnapshot

表示某个 ProductSnapshot 下的 SKU 事实。

当前字段：

~~~text
id
product_snapshot_id
sku_id
sku_name
stock
price
~~~

说明：

- sku_id 是 SKU 身份依据；
- sku_name 保存标准化后的规格名称；
- stock 可以为 NULL，0 是真实库存；
- price 可以为 NULL，当前不可靠的 SKU 独立价格不参与 ChangeEvent 检测；
- 缺失库存或价格保存为 NULL，不保存为 0；
- ProductSnapshot 删除时，所属 SkuSnapshot 使用现有 delete-orphan / ON DELETE CASCADE 语义。

1688 原始字段只在采集适配层处理，例如：

~~~text
canBookCount → stock
skuPriceScale → price / 商品级价格
~~~

业务层只依赖上述内部字段。

---

## 5. 当前已实现：CollectionRun

表示一次竞品采集执行记录。

当前字段：

~~~text
id
competitor_id
started_at
finished_at
status
error_type
error_message
~~~

status 当前允许：

~~~text
running
success
failed
~~~

事务和并发语义：

- running 表示采集执行状态，不是数据库锁；
- 当前并发控制由进程内 COLLECTION_LOCK 负责；
- running 记录先独立提交，Playwright / 网络采集阶段不持有业务保存事务；
- 采集成功后，快照、SKU、ChangeEvent、Competitor 当前值和 CollectionRun.success 在同一个业务事务中提交；
- 保存失败时，本次业务数据回滚，随后将该 CollectionRun 记录为 failed；
- error_type 和 error_message 保存安全、简洁的错误信息，不保存 traceback。

---

## 6. 当前已实现：ChangeEvent

表示本次成功采集相对于同一竞品上一份快照检测出的真实变化。

当前字段：

~~~text
id
competitor_id
snapshot_id
change_type
entity_key
old_value
new_value
detected_at
~~~

字段语义：

- competitor_id：发生变化的当前竞品；
- snapshot_id：变化对应的**本次新建 ProductSnapshot**，不是 previous snapshot；
- entity_key：商品级变化为 NULL，SKU 级变化保存 sku_id；
- old_value / new_value：简短、稳定、可读的字符串；
- detected_at：本次变化检测时间。

old_value / new_value 不保存完整 Snapshot JSON、1688 原始数据、HTML、Cookie、Token 或请求头。

### 6.1 当前已实现的 change_type

当前数据库 CHECK 和业务检测逻辑只支持以下 6 种：

~~~text
price_increase
price_decrease
sku_added
sku_removed
stock_changed
title_changed
~~~

当前检测语义只覆盖价格、标题、SKU 新增、SKU 删除和库存变化。具体比较规则由 docs/specs/detect-competitor-changes.md 负责，本文只保留稳定的数据边界。

### 6.2 当前检测基线

- previous 是同一 competitor_id 最近一条 ProductSnapshot，排序为 captured_at DESC, id DESC；
- current 是本次采集并标准化后的 ProductData；
- 第一次成功采集没有 previous，只建立 baseline，不产生 ChangeEvent；
- 连续相同采集仍新增 ProductSnapshot、SkuSnapshot 和成功 CollectionRun，但产生 0 条 ChangeEvent；
- ChangeEvent、快照、SKU、Competitor 当前值和成功 CollectionRun 属于同一个业务成功事务；
- 任一步保存失败时，本次业务数据 rollback，CollectionRun 最终为 failed。

### 6.3 latest_change

当前 GET /api/competitors 和 POST collect 的 competitor payload 提供 latest_change。它表示该竞品历史上最近一条真实 ChangeEvent，排序为：

~~~text
detected_at DESC
id DESC
~~~

没有事件时为 null。latest_change 不等于“本次采集变化”：本次采集没有新变化时，仍可能返回历史上的 latest_change。

该字段是单条真实摘要，不代表完整 ChangeEvent 历史，也不扩展为变化历史、分页或趋势接口。

---

## 7. 当前关系

~~~text
Competitor
    │
    ├── N ProductSnapshot
    │      │
    │      └── N SkuSnapshot
    │
    ├── N CollectionRun
    │
    └── N ChangeEvent
           │
           └── snapshot_id → ProductSnapshot
~~~

CompetitorGroup 不应画入当前关系图。Competitor.group_id 当前只是可空字段，尚未形成分组实体关系。

---

## 8. 趋势数据原则

当前可直接追溯的数据来源：

~~~text
价格趋势
→ ProductSnapshot.price_min / price_max

库存趋势
→ SkuSnapshot.stock
~~~

当前不支持销量趋势，因为 ProductSnapshot 没有销量字段。7 天 / 30 天趋势查询和展示尚未实现，也没有额外趋势聚合表。

---

## 9. 当前尚未实现：未来 V1 计划

以下内容仍是长期 V1 目标，但当前没有对应的完整实现，不能当作当前数据模型：

- CompetitorGroup：未来增加分组表、ORM、外键和分组 CRUD；
- 每日自动调度；
- sales snapshot / sales change；
- 可靠的商品下架检测；
- 主图变化检测；
- 7 天 / 30 天趋势展示；
- Dashboard 今日变化展示。

### 9.1 未来但尚未实现的 change_type

以下 3 种属于未来 V1 计划，当前不能生成，也不在当前 ChangeEvent CHECK 中：

| change_type | 当前未实现原因 |
|---|---|
| sales_increase | 当前 ProductSnapshot 没有销量字段 |
| product_offline | 当前 Parser 没有可靠下架判定 |
| main_image_changed | 当前 main_image_url 尚未稳定真实采集 |

SKU price change 当前也不支持，且不属于当前 change_type 集合。

这些能力具备可靠数据来源和明确规则后，才能通过独立变更加入当前模型。

---

## 10. 数据保留与时间原则

- 当前历史 Snapshot、SkuSnapshot 和 ChangeEvent 用于保持事实可追溯；
- 竞品停止监控时优先使用 is_active = false，不要因为停止监控删除历史事实；
- 所有时间字段保存明确的时间值，展示时再转换成本地时间；
- 不使用字符串保存时间。

---

## 11. 数据来源原则

内部数据库只保存标准化后的业务字段。以下外部字段不得扩散到业务层：

~~~text
skuInfoMap
canBookCount
skuPriceScale
saleQuantityList
saleRangeList
tradePriceList
mtop.1688...
~~~

外部页面或接口结构变化时，只修改采集适配层，不改变内部数据模型的字段语义。

---

## 12. 当前 V1 不做的通用能力

当前数据模型不包含：

- User；
- Role / Permission；
- Workspace / Tenant；
- Notification；
- AI Analysis；
- Recommendation；
- 多平台抽象层；
- 复杂审计日志；
- 数据仓库；
- 事件总线；
- 分布式任务表。

---

## 13. Single Source of Truth

~~~text
Competitor
= 当前被监控对象

ProductSnapshot / SkuSnapshot
= 历史采集事实

ChangeEvent
= 两次成功采集事实之间的变化结果

CollectionRun
= 采集执行状态
~~~

不要在多个表中重复维护同一份业务事实，也不要把未来 V1 目标描述成当前已经存在的字段、实体或变化类型。
