# Data Model

## 1. 文档范围

本文描述 1688 监控商品（我方商品与直接竞品）共用的数据模型，并明确区分：

- **当前已实现**：当前 ORM、数据库表、迁移和采集流程已经支持的事实；
- **后续规划**：仅在 roadmap / research 中讨论，当前没有对应正式模型的部分。核对基线为 `backend/app/models.py`、Alembic 至 `20261004_12` 和现有 API；数据库迁移版本表 `alembic_version` 不计入业务 ORM 实体。

当前 ORM 已实现 7 个实体（7 张业务表）：

~~~text
CompetitorGroup
 └── Competitor
      ├── ProductSnapshot
      │      └── SkuSnapshot
      ├── CollectionRun
      └── ChangeEvent
SystemSetting（独立 key/value，无外键）
~~~

---

## 2. 当前已实现：CompetitorGroup

表示我方一个目标商品型号对应的竞品集合。

当前字段：

~~~text
id
name
created_at
~~~

说明：

- name 为非空、唯一字符串，保存创建时 trim 后的名称；
- name 长度限制为 64 个字符；
- CompetitorGroup 与 Competitor 为 1 → N 关系。
- name 直接作为商品型号显示，不维护独立的我方商品实体；
- 一个正式组可有 0 个或 1 个我方基准商品；旧组是否绑定取决于现有角色与后续 ownership 迁移的店铺识别结果；没有可靠 self 基准时保留未绑定。商品身份保存在 `Competitor.ownership`，组内兼容角色保存在 `Competitor.group_role`，不新增 `own_competitor_id`、OwnProduct 外键或 GroupMember 表；
- 删除型号时，在同一事务内将全部成员设为 `group_id = NULL`、`group_role = competitor`，再删除 CompetitorGroup；保留 Competitor、ProductSnapshot、SkuSnapshot、CollectionRun、ChangeEvent、status 和 is_active；
- 重命名型号只修改 name，不修改 Competitor、Snapshot、ChangeEvent 或 CollectionRun。

---

## 3. 当前已实现：Competitor

表示一个被监控的 1688 商品，包括我方商品与直接竞品。

当前字段：

~~~text
id
group_id
ownership
group_role
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
- group_id 可为 NULL，或引用 competitor_groups.id；NULL 表示未分组；
- `ownership` 只允许 `self` / `competitor`，默认及 server default 为 `competitor`；它独立于 group、status、is_active。未分组 self 仍是我方商品，不能通过 group_role 推断身份。
- `group_role` 只允许 `competitor` / `own`，默认 `competitor`。当前合法组合：

  | ownership | group_id | group_role |
  | --- | --- | --- |
  | competitor | NULL 或正式组 | competitor |
  | self | NULL | competitor（兼容角色，不改变 self 身份） |
  | self | 正式组 | own |

- ORM / migration 同时保留角色、ownership 和组合 CHECK；组合约束 `ck_competitors_ownership_role` 禁止 competitor/own、self 入组却为 competitor，以及未分组 own。SQLite partial unique index `uq_competitors_group_own`（谓词 `group_role = 'own'`）保证每组最多一个 own；status CHECK 为 unknown / active / offline。
- 直接竞品单条或批量转组保持 competitor 身份/角色；self 单条入组成为 own，解除后成为 self/未分组/competitor role，目标组已有 own 返回冲突，不覆盖。竞品批量分组/删除拒绝 self，包含未分组 self。
- ownership 从当前真实店铺与 `own_shop_name` 的空白标准化后精确比较得到；添加前置采集、配置保存重识别、后续成功采集共用身份规则，不使用标题、链接、组名或模糊匹配。
- migration `20261004_12` 使用当前非 NULL shop_name 优先识别；仅 NULL shop_name 的旧 own 可保留 legacy self。组冲突优先真实店铺匹配，按 created_at / id 选择稳定 winner，其余 self 移至未分组并保留历史。配置重识别沿用稳定选择；后续采集保持既有真实 own，只能替代 NULL 店铺的 legacy fallback，不能抢占真实 own。
- 身份/分组变化只影响当前读模型，不回写历史或生成 ownership ChangeEvent。当前 Snapshot、事件和采集记录没有历史 ownership / membership 字段。
- title、shop_name、main_image_url 保存最近一次成功采集得到的当前信息；
- main_image_url 当前优先来自 `gallery.fields.offerImgList[0]`，缺失或无效时仅使用已验证的结构化 fallback；字段仍允许为 NULL，并用于相邻快照的主图变化比较；
- Competitor 只保存当前 `main_image_url`，不保存完整商品图库；
- last_collected_at 表示最近成功完成的采集/状态检查，包括明确 offline 成功；它不等于最新 Snapshot 时间；
- is_active 表示是否继续监控。

status 当前允许：

~~~text
unknown
active
offline
~~~

正式采集在从 `active` 检测到明确下架证据时将商品状态记为 `offline`；恢复上架时回到 `active`，初始或尚未形成商品事实的竞品仍可为 `unknown`。下架和恢复上架分别通过生命周期 ChangeEvent 表达。

---

## 4. 当前已实现：ProductSnapshot

表示某个监控商品某次正常成功采集时的商品级事实快照。

当前字段：

~~~text
id
competitor_id
captured_at
title
shop_name
main_image_url
image_urls
price_min
price_max
min_order_quantity
product_status
collection_source
~~~

说明：

- 正常商品成功采集新增快照，不覆盖历史；明确 offline 成功只更新状态和 Run，不创建空快照；恢复上架创建新快照作为下一轮 baseline；
- `image_urls` 是本次历史快照的 nullable JSON ordered list，来自 `gallery.fields.offerImgList` 的有效 URL，按 normalization 后的原始顺序 exact 去重；Fallback 主图只在必要时作为首项加入；旧 Snapshot 为 NULL；
- 手动、自动 Batch 与添加前置采集的正常成功事实均可生成快照；
- Backend 运行时约每分钟检查自动策略并复用 Batch Runner；rolling_24h 按最近 CollectionRun.started_at 判断 24 小时，fixed_daily 按电脑本地计划时间转 UTC 判断当天是否尝试。failed 同样计入窗口；不承诺每天恰好一条 Snapshot；
- price_min / price_max 使用 Numeric(18, 2)，用于保存商品级价格区间；
- min_order_quantity 保存本次采集的 Offer 级最小起批数量，可为 NULL，非 NULL 时必须大于等于 1；
- 缺失价格保存为 NULL，不转换为 0；
- product_status 当前允许 unknown、active、offline；
- collection_source 当前数据库允许：
  - html
  - network
  - mixed
- 当前正式 Collector 主要通过 HTML / 内嵌 JSON 解析，实际主要保存 html；Network/XHR 是后续能力。

快照只保存当次真实采集到的事实，不保存“涨价”“销量上涨”等判断结果；变化判断由 ChangeEvent 表达。

---

## 5. 当前已实现：SkuSnapshot

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
- price 可以为 NULL；同一 `sku_id` 的相邻有效快照两侧价格均非 NULL 且不同，会生成 SKU 级价格 ChangeEvent；
- `price` 保存 SKU 当前页面展示价格，来源为已验证的 `skuInfoMap[item].discountPrice`；缺失或非法值保存为 NULL，不使用 `price` fallback，也不使用商品级价格或价格区间填充；
- 缺失库存或价格保存为 NULL，不保存为 0；
- ProductSnapshot.min_order_quantity 保存商品级起批量；旧 ProductSnapshot 保持 NULL，不历史回填；
- ProductSnapshot 删除时，所属 SkuSnapshot 使用现有 delete-orphan / ON DELETE CASCADE 语义。

1688 原始字段只在采集适配层处理，例如：

~~~text
canBookCount → stock
discountPrice → SKU 当前页面展示价格 → price
priceAmount → Offer / ProductSnapshot.min_order_quantity
skuPriceScale → 商品级价格 / 商品级价格区间
~~~

业务层只依赖上述内部字段。

---

## 6. 当前已实现：CollectionRun

表示一次监控商品采集执行记录；包括 self 与 competitor，不是批次或持久化任务。

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
- 当前并发互斥由进程内 COLLECTION_LOCK 与共享 BatchRuntime reservation/runner 状态协调；数据库 running 行不是互斥锁；
- 已有商品采集的 running 记录先独立提交，外部采集阶段不持有业务保存事务；统一添加是例外：前置验证成功后才原子创建商品、baseline 快照/SKU 和成功 Run，添加失败不留下商品或 Run；
- 正常成功时，快照、SKU、ChangeEvent、Competitor 当前值（含可靠身份维护）和 Run.success 原子提交；明确 offline 成功允许无 Snapshot，仍更新 last_collected_at 和 Run.success；
- 保存失败时，本次业务数据回滚，随后将该 CollectionRun 记录为 failed；
- error_type 和 error_message 保存安全、简洁的错误信息，不保存 traceback。
- BatchRuntime 为进程内状态，包含 running / resting / cooling_down / verification_required / completed / idle 等，不增加 CollectionRun.status 枚举；重试当前商品可产生新的单商品 Run，没有 batch_id / source 字段。
- `GET /api/collection-runs` 按 started_at DESC / id DESC 分页；返回的商品标题、店铺和 ownership 来自当前 Competitor，不是尝试时的历史身份。重启后可以看 Run 历史，但不能据此恢复或推造批次。

---

## 7. 当前已实现：ChangeEvent

表示监控商品的客观变化：普通 diff 比较相邻有效快照，生命周期事件来自可靠状态转换；覆盖我方与竞品，聚合读取再按当前身份区分。

当前字段：

~~~text
id
competitor_id
snapshot_id
collection_run_id
change_type
entity_key
old_value
new_value
delta_value
delta_rate
detected_at
~~~

字段语义：

- competitor_id：发生变化的当前竞品；
- snapshot_id：新 V2 事件对应本次新建的 ProductSnapshot，不是 previous snapshot；`product_offline` 必须为 NULL，其他新 V2 事件必须关联本次 ProductSnapshot。数据库 CHECK 对兼容的历史 `stock_changed` 也要求非 NULL；
- collection_run_id：nullable，以兼容历史事件；所有新 V2 事件均关联发现它的当前 CollectionRun。历史 NULL 不按时间猜测或回填；
- entity_key：商品级变化为 NULL，SKU 级变化保存 sku_id；
- old_value / new_value：简短、稳定、可读的字符串；
- delta_value / delta_rate：nullable 的 `Numeric(18, 6)`，分别表示数值差和百分比变化率；不是 API 字符串类型；
- detected_at：系统检测到变化的时间。同一个 CollectionRun 产生的事件共享检测时间；它不表示平台上真实发生变化的时间。

old_value / new_value 不保存完整 Snapshot JSON、1688 原始数据、HTML、Cookie、Token 或请求头。

Dashboard 不改变 ChangeEvent 的事实级语义。旧 `/api/dashboard/today` 兼容读模型在查询展示层按 active 直接竞品聚合；当前 Dashboard 核心使用独立 Group Attention，而非该竞品级表；`change_count` 仍统计真实事件条数，`ChangeEvent` 不因展示聚合而合并或删除。SKU 级事件的 `entity_key` 仍是 `sku_id`，名称可从关联快照的 `SkuSnapshot` 可靠恢复时用于展示，不能恢复时保留事实性 SKU ID 回退。

Dashboard item 的 `stock_total_change` 是商品级展示投影；primary event 为 `stock_increase`、`stock_decrease`、`sku_sold_out`、`sku_restocked` 或历史 `stock_changed` 时计算，结构为 `{old_total, new_total}`。current 使用 primary event 的 `snapshot_id`；previous 使用同一 competitor 中按 `(captured_at ASC, id ASC)` 紧邻的上一条 `ProductSnapshot`。总库存分别由对应快照下完整 SKU stock 求和；无 SKU 或任一 SKU stock 为 NULL 时该 total 为 NULL，0 是有效库存。不得将多条 SKU stock event 的 old/new 相加来计算商品总库存。该投影不修改 ChangeEvent。

详情 API 的 `latest_skus[].sku_name` 和 `recent_changes[].sku_name` 是展示层字段：Backend 返回前使用 Python 标准库 `html.unescape` 并 trim，不回写数据库。所有 SKU 级事件统一通过 `entity_key = sku_id`，优先按事件 `snapshot_id + entity_key` 精确匹配 `SkuSnapshot`，再按同一竞品历史 `SkuSnapshot.sku_id` 回退；适用于 SKU price、库存方向、售罄 / 恢复有货、新增 / 删除及历史 `stock_changed`。仍找不到时返回 `null`，前端回退为事实性 `SKU {entity_key}`。

### 7.1 当前已实现的 change_type

当前数据库 CHECK 允许以下 14 种 V2 标准事件：

~~~text
price_increase
price_decrease
stock_increase
stock_decrease
sku_added
sku_removed
sku_sold_out
sku_restocked
min_order_quantity_increase
min_order_quantity_decrease
product_offline
product_online
title_changed
main_image_changed
~~~

数据库同时允许历史 legacy 类型 `stock_changed`，因此 CHECK 共允许 15 个字符串。它只用于兼容读取，不再由新采集生成；不改写或推断历史事件方向。

商品级事件的 `entity_key = NULL`：商品级 price increase/decrease、MOQ increase/decrease、product offline/online、title changed、main image changed。SKU 级事件的 `entity_key = sku_id`：SKU price increase/decrease、stock increase/decrease、sku added/removed/sold out/restocked。

检测规则摘要：

- 商品级价格只有相邻快照两侧价格区间都可比较，且 min/max 同方向变化时才生成 price event；区间无法表达唯一数值差时 delta 字段为 NULL。若两侧均为单值价格，则可计算 delta。
- 同一 `sku_id` 两侧 `SkuSnapshot.price` 均非 NULL 且不同，生成同类型的 `price_increase` / `price_decrease`，以 `entity_key` 表示 SKU 层级。SKU 新增或删除不额外生成 price event。
- 同一 SKU 两侧 stock 均已知时，`old > 0` 且 `new > 0` 的数值变化生成 `stock_increase` / `stock_decrease`；`>0 → 0` 生成 `sku_sold_out`；`0 → >0` 生成 `sku_restocked`。SKU 新增 / 删除只生成 `sku_added` / `sku_removed`。NULL 不按 0 推断。商品总库存仍由 Snapshot 的完整 SKU stock 求和派生，不生成商品级库存 ChangeEvent。
- 起批量两侧均为合法正整数且发生变化时，生成商品级 `min_order_quantity_increase` / `min_order_quantity_decrease`；首次采集、NULL 或无法验证的值不生成事件。
- `main_image_changed` 仅比较相邻快照中已标准化并持久化的 `main_image_url`：两侧均非空且不相等时生成；首次采集、任一侧为 NULL、相同 URL 或仅 `image_urls` 变化均不生成。
- `delta_value` / `delta_rate` 可用于商品单值价格、SKU 价格、SKU 库存变化（包括售罄 / 恢复有货）及 MOQ。例：`100 → 0` 的 delta 为 `-100`、rate 为 `-100%`；`0 → 100` 的 delta 为 `100`、rate 为 NULL，避免除以零。非数值事件的 delta 字段为 NULL。

生命周期规则：

- 第一次成功采集只建立 baseline，不生成普通 ChangeEvent；`unknown → active` 不生成 `product_online`。
- 只有明确下架证据才从 `active` 生成 `product_offline`；不创建空 Snapshot，事件 `snapshot_id = NULL`、`collection_run_id` 有值，历史保留。
- `offline → active` 创建新 Snapshot，只生成 `product_online`，不做普通价格、SKU、库存、MOQ、标题或主图 diff；该 Snapshot 成为后续比较 baseline。

### 7.2 当前检测基线

- previous 是同一 competitor_id 最近一条 ProductSnapshot，排序为 captured_at DESC, id DESC；
- current 是本次采集并标准化后的 ProductData；
- 第一次成功采集没有 previous，只建立 baseline，不产生 ChangeEvent；
- 连续相同采集仍新增 ProductSnapshot、SkuSnapshot 和成功 CollectionRun，但产生 0 条 ChangeEvent；
- ChangeEvent、快照、SKU、Competitor 当前值和成功 CollectionRun 属于同一个业务成功事务；
- 任一步保存失败时，本次业务数据 rollback，CollectionRun 最终为 failed。

### 7.3 latest_change

当前 GET /api/competitors 和 POST collect 的 competitor payload 提供 latest_change。它表示该竞品历史上最近一条真实 ChangeEvent，排序为：

~~~text
detected_at DESC
id DESC
~~~

没有事件时为 null。latest_change 不等于“本次采集变化”：本次采集没有新变化时，仍可能返回历史上的 latest_change。

该字段是单条真实摘要，不代表完整 ChangeEvent 历史，也不扩展为变化历史、分页或趋势接口。

---

## 8. 当前关系与 SystemSetting

~~~text
CompetitorGroup 1 → N Competitor（group_id 可空）
Competitor 1 → N ProductSnapshot 1 → N SkuSnapshot
Competitor 1 → N CollectionRun
Competitor 1 → N ChangeEvent
ChangeEvent.snapshot_id → ProductSnapshot（可空，类型 CHECK）
ChangeEvent.collection_run_id → CollectionRun（可空，历史兼容）
SystemSetting（独立，无外键）
~~~

这是数据库外键关系；ORM 仅显式声明 ProductSnapshot ↔ SkuSnapshot relationship，不代表其他边不存在。每组最多一个 self/own；不存在 OwnProduct、GroupMember、企业主体或经营观察表。

SystemSetting 使用 `key: String(64)` 主键与 `value: nullable String(255)`，当前保存：

- `own_shop_name`：我方店铺配置；迁移仅在缺失时初始化当前业务值，不覆盖已有配置。GET / PUT `/api/settings/own-shop-name`；保存配置与当前商品身份重识别同事务。
- `competitor_monitoring_*`：五项 Batch 节奏/风控（商品间隔、连续采集数量、主动休息、验证冷却、自动续采上限）及四项自动策略（enabled、strategy、time、missed_policy）。GET / PUT `/api/settings/competitor-monitoring` 一次返回/保存九项；值以 canonical 字符串落库，类型/范围由 API 校验，无对应数据库枚举 CHECK。
- 缺失或非法采集设置读取时按字段默认值 fallback，不写回；PUT 完整九项验证、原子提交。BatchConfig 只投影五项节奏/风控，不包含 scheduler 四项。

Group Summary、Group Detail、Group Attention 都是派生读取，没有额外表或持久化分数；按当前 ownership / group / role 聚合，不能宣称历史事件发生时的归属。竞品数量过滤 ownership=competitor，通用采集统计可覆盖所有监控商品。

---

## 9. 趋势数据原则

当前可直接追溯的数据来源：

~~~text
价格趋势
→ ProductSnapshot.price_min / price_max

库存趋势
→ ProductSnapshot 对应的 SkuSnapshot.stock
~~~

竞品详情的 `daily_trend` 返回连续 7 天或 30 天的 Asia/Shanghai 业务日。每天只选择该业务日最后一条成功 `ProductSnapshot`，排序为 `captured_at DESC, id DESC`；缺少采集的日期保留空点，不复制上一日值。价格和库存来自同一每日最终快照，库存按该快照全部 SKU 的 `stock` 求和；无 SKU 或任一库存为 NULL 时总库存为 NULL，0 是有效库存。

详情 API 还动态提供最近一条价格 `ChangeEvent`（只考虑 `price_increase` / `price_decrease`，按 `detected_at DESC, id DESC`），不新增趋势聚合表或数据库字段。当前不支持正式销量趋势，因为 ProductSnapshot 没有销量字段；前端仅展示销量能力占位。

---

## 10. 尚未实现的模型

正式 ORM / API 没有销量快照、销量事件、企业主体、成交/口碑/标签观察或新经营指标。详情销量只是占位；不存在 `sales_increase` 事件。研究来源验证不代表已经入库。

后续 Track A 先用现有事实定义组内竞争位置；Track B 经营指标增量 POC 可并行，不阻塞 A，仅作为新指标产品化 Gate。未来表、字段和事件必须由独立正式 Spec 决定，本文不预设模型。见 [重构计划书](roadmap/competition-intelligence-restructuring-plan.md) 与 [Spec 索引](specs/README.md)。

---

## 11. 数据保留与时间原则

- 当前历史 Snapshot、SkuSnapshot 和 ChangeEvent 用于保持事实可追溯；
- 竞品停止监控时优先使用 is_active = false，不要因为停止监控删除历史事实；
- 永久删除竞品时按 ChangeEvent、CollectionRun、SkuSnapshot、ProductSnapshot、Competitor 顺序删除；CompetitorGroup 保留。删除使用现有 COLLECTION_LOCK 和单事务，失败 rollback；
- 所有时间字段保存明确的时间值，展示时再转换成本地时间；
- 不使用字符串保存时间。

---

## 12. 数据来源原则

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

## 13. 当前 V1 不做的通用能力

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

## 14. Single Source of Truth

~~~text
Competitor.ownership
= 当前商品身份（self 或 competitor）

Competitor.group_id
= 当前组归属

Competitor.group_role
= 当前组内角色（competitor 或 own）

Competitor
= 当前监控对象

ProductSnapshot / SkuSnapshot
= 历史采集事实

ChangeEvent
= 快照差异与可靠生命周期状态转换检测出的客观变化

CollectionRun
= 持久化单商品采集执行记录

SystemSetting
= 当前已保存配置

BatchRuntime
= 进程内当前批次状态（不是 ORM 表）
~~~

不要在多个表中重复维护同一份业务事实，也不要把后续规划描述成当前已经存在的字段、实体或变化类型。
