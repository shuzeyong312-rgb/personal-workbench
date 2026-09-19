# Data Model

## 1. 目标

V1 的数据模型只服务 1688 竞品监控。

需要支持：

- 手动添加竞品；
- 按竞品组管理；
- 每天保存一次商品快照；
- 保存 SKU 级库存；
- 对比前后变化；
- 展示今日变化；
- 查看 7 天 / 30 天趋势；
- 记录采集失败。

不为未来的多用户、权限、其他平台提前设计字段。

---

## 2. 核心实体

V1 只保留 6 个核心实体：

```text
CompetitorGroup
      ↓
  Competitor
      ↓
ProductSnapshot
      ↓
  SkuSnapshot

CollectionRun

ChangeEvent
```

---

## 3. CompetitorGroup

表示一个竞品分组。

建议字段：

```text
id
name
description
created_at
updated_at
```

规则：

- `name` 必填；
- V1 不做复杂层级分组；
- 不做父子分组。

---

## 4. Competitor

表示一个被监控的 1688 商品。

建议字段：

```text
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
```

说明：

- `platform` V1 固定为 `1688`；
- `offer_id` 是 1688 商品唯一标识；
- `url` 保存标准化后的商品链接；
- `title`、`shop_name`、`main_image_url` 保存最近一次成功采集结果；
- `status` 表示商品当前状态，例如 `active` / `offline` / `unknown`；
- `is_active` 表示用户是否继续监控；
- `last_collected_at` 表示最后一次成功采集时间。

约束：

```text
platform + offer_id 唯一
```

同一个 1688 商品不要重复创建多个监控对象。

---

## 5. ProductSnapshot

表示某个竞品某次采集时的商品级事实快照。

建议字段：

```text
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
```

说明：

- 每次成功采集都新增一条；
- 不覆盖旧快照；
- `price_min` / `price_max` 用于兼容阶梯价或多 SKU 价格；
- `collection_source` 只记录简短来源，例如：
  - `html`
  - `network`
  - `mixed`
- 本 Feature 不接入插件历史数据。

规则：

> Snapshot 只保存当时真实采集到的事实，不保存“涨价”“销量上涨”等判断结果。

这些判断由 ChangeEvent 表达。

---

## 6. SkuSnapshot

表示某次商品快照下的 SKU 数据。

建议字段：

```text
id
product_snapshot_id
sku_id
sku_name
stock
price
```

说明：

- 一个 ProductSnapshot 可以对应多个 SkuSnapshot；
- `sku_id` 保存 1688 的 SKU ID；
- `sku_name` 保存内部标准化后的规格名称，例如 `米白色`；
- `stock` 保存当前可售库存，缺失时可以为空；
- `price` 如果无法取得 SKU 独立价格，可以为空，缺失时不保存为 0。

重要：

不要把 1688 原始字段名直接扩散到业务层。

例如：

```text
canBookCount → stock
skuPriceScale → price / 商品级价格
```

原始结构只在采集适配层处理。

---

## 7. CollectionRun

表示一次采集执行记录。

建议字段：

```text
id
competitor_id
started_at
finished_at
status
error_type
error_message
```

`status` 正式值为：

```text
running
success
failed
```

`running` 只表示采集任务正在执行，不承担数据库锁职责；真正的并发控制由应用层进程内全局采集锁负责。

用途：

- 记录某个竞品今天是否采集成功；
- 单个商品失败时不影响其他商品；
- 方便排查登录失效、页面变化、接口失败等问题。

不要把完整异常堆栈长期塞进数据库。

---

## 8. ChangeEvent

表示两次快照之间检测出的业务变化。

建议字段：

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

`change_type` V1 只支持：

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

说明：

- `entity_key` 用于标识变化对象；
- 商品级变化可以为空；
- SKU 变化时可存 `sku_id`；
- `old_value` / `new_value` 保存简洁、可读的值；
- 今日变化首页直接查询 ChangeEvent。

不要为每一种变化创建单独的数据表。

---

## 9. 关系

```text
CompetitorGroup
    1
    │
    └── N Competitor
             │
             ├── N ProductSnapshot
             │        │
             │        └── N SkuSnapshot
             │
             ├── N CollectionRun
             │
             └── N ChangeEvent
```

---

## 10. 趋势数据原则

7 天 / 30 天趋势直接基于 ProductSnapshot 和 SkuSnapshot 查询。

例如：

```text
价格趋势
→ ProductSnapshot.price_min / price_max

销量趋势
→ 不属于本 Feature，待未来独立 migration 增加

库存趋势
→ SkuSnapshot.stock
```

V1 不建立额外的趋势聚合表。

只有真实数据量证明查询性能不足时，再考虑聚合。

---

## 11. 删除原则

V1 默认：

- 竞品删除优先采用停止监控，而不是物理删除；
- 设置 `is_active = false`；
- 历史 Snapshot 和 ChangeEvent 保留。

这样历史趋势不会因为误删竞品而丢失。

---

## 12. 时间原则

所有时间字段统一保存明确时间值。

业务展示时再转成本地时间。

不要用字符串保存时间。

---

## 13. 数据来源原则

内部数据库只保存标准化后的业务字段。

禁止其他模块直接依赖以下外部字段：

```text
skuInfoMap
canBookCount
skuPriceScale
saleQuantityList
saleRangeList
tradePriceList
mtop.1688...
```

外部结构变化时，只修改采集适配层。

---

## 14. V1 不做

当前数据模型明确不包含：

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

出现真实需求后再增加。

---

## 15. Single Source of Truth

核心原则：

```text
Competitor
= 当前被监控对象

ProductSnapshot / SkuSnapshot
= 历史事实

ChangeEvent
= 快照之间的变化结果

CollectionRun
= 采集执行状态
```

不要在多个表里重复维护同一份业务事实。
