# 1688 商品下架 / 恢复上架检测 Feature Spec

状态：正式 Spec，当前仅定义，不实现业务代码。

本 Spec 基于 `docs/research/1688-offline-product-validation.md` 的 POC 结果，以及当前 Backend、Frontend、数据库和已有采集/变化检测行为整理。

## Problem Statement

当前系统已经保存 `Competitor.status`，但 1688 商品下架检测尚未正式接入。商品页面下架、滑块验证、登录失效、网络异常和 parser 失败之间必须保持清晰边界，否则会产生以下风险：

- 把一次采集异常错误写成商品下架；
- 把商品下架错误写成正常在售；
- 下架时创建空 Snapshot，污染价格、库存、SKU 和趋势历史；
- 商品下架后自动停止监控，导致无法发现恢复上架；
- 恢复上架时把长时间下架前后的变化一次性误报为多个普通属性变化；
- 使用现有 `ChangeEvent.snapshot_id NOT NULL` 约束时，为下架事件伪造 Snapshot 或错误关联旧 Snapshot。

本 Feature 解决商品生命周期状态和采集异常的边界，并把“商品下架”和“恢复上架”纳入现有 ChangeEvent、Dashboard、Detail 和采集结果体系。

## Solution

### 1. 核心概念

商品状态与监控状态是两个独立维度：

| 字段 | 值 | 含义 |
|---|---|---|
| `Competitor.status` | `unknown` | 尚未通过可靠证据确认当前商品状态 |
| `Competitor.status` | `active` | 已成功解析正常商品页，确认正常在售 |
| `Competitor.status` | `offline` | 命中经过 POC 验证的明确下架页面 |
| `Competitor.is_active` | `true` | 用户仍希望系统继续监控 |
| `Competitor.is_active` | `false` | 用户主动停止监控 |

商品下架不等于停止监控。允许并且必须支持：

```text
status = offline
is_active = true
```

它表示商品已经下架，但系统仍继续访问该商品，以发现恢复上架。系统不得因为检测到下架而自动修改 `is_active`、删除竞品或弹出必须处理的阻塞式确认框。

### 2. 页面分类优先级

一次采集的页面分类按以下顺序执行：

1. `verification_required`
2. 明确 `offline`
3. 成功解析的正常 `active`
4. 其他情况作为采集异常，保留既有商品状态

verification 必须早于 offline。验证页即使 HTTP 200、缺少 expected offerId、商品字段缺失或 parser 失败，也不能判定为下架。

### 3. Verification 判断

沿用现有可靠判断，并保留当前已修复的有限时序策略：

```text
已有 verification URL marker
OR 已知 exact title
OR 可见 #nc_1_wrapper
OR 同时满足：
   可见 #baxia-punish
   可见 #baxia-punish .captcha-tips
   可见提示包含：
     “请拖动下方滑块完成验证”
     或“通过验证以确保正常访问”
```

检测时机固定为：页面导航完成后立即检查一次；未命中时使用约 300ms 的单次 recheck；第二次仍未命中即结束，不轮询、不自动 reload、不自动拖动滑块。

命中 verification 后：

- 当前采集停止；
- 沿用 `verification_required` 错误和批量停止行为；
- 召回/保留 headed Chrome 窗口，等待用户人工处理；
- 不修改 `Competitor.status`；
- 不修改 `Competitor.is_active`；
- 不创建 ProductSnapshot；
- 不生成商品上下架 ChangeEvent。

### 4. Offline 判断

在 verification、登录和导航异常排除后，只使用已通过 POC 验证的明确下架信号：

1. 页面存在并且可见 `h3.mod-detail-offline-title`；
2. 该元素的可见文本标准化后精确等于 `商品已下架`。

标准化只包括去除首尾空白并按现有文本规则折叠无意义空白，不做模糊关键词推断。

本 Feature 不把以下内容作为下架证据：

- expected offerId 缺失；
- 标题、店铺、价格、SKU 或主图缺失；
- parser 失败；
- 页面空白或结构不完整；
- HTTP 200 或其他 HTTP 状态；
- 网络失败、超时或浏览器异常；
- 登录页；
- verification 页；
- 没有看到下架文案。

POC 证据为 3 家店铺、9 条真实下架商品、每条重复 2 次，共 18/18 命中，未发现第二种下架页面形态。该证据只支持当前 selector + 精确文本组合，不支持把其他缺失字段升级为 offline。

### 5. Active 判断

只有同时满足以下条件，才确认 `active`：

- 页面不是 verification 或登录页；
- 页面没有明确 offline selector/text；
- 现有 parser 成功完成正常商品字段解析；
- 解析出的 offerId 与目标 Competitor.offer_id 一致；
- parser 所需核心字段通过现有校验。

“没有发现下架提示”不能单独证明 active。普通商品解析失败时保持原状态并记录采集异常。

### 6. 状态机

| 当前状态 | 本次可靠结果 | 状态处理 | 生命周期事件 |
|---|---|---|---|
| `unknown` | 正常商品页 | `unknown → active` | 无 |
| `unknown` | 明确下架页 | `unknown → offline` | 无 |
| `active` | 正常商品页 | 保持 `active` | 无生命周期事件，普通 diff 按规则执行 |
| `active` | 明确下架页 | `active → offline` | 生成一次 `product_offline` |
| `offline` | 明确下架页 | 保持 `offline` | 不重复生成 |
| `offline` | 正常商品页 | `offline → active` | 生成一次 `product_online` |
| 任意状态 | verification/登录/网络/空白/parser 等异常 | 保持原状态 | 不生成任何上下架事件 |

状态变化以采集开始前持久化的 `Competitor.status` 为旧状态，以本次可靠页面分类为新状态。重复采集不得通过重复访问生成重复生命周期事件。

### 7. 采集异常

采集异常包括：

- `verification_required`；
- 登录失效；
- 网络或页面访问失败；
- 超时；
- 空白或异常页面；
- expected offerId 不匹配；
- parser 失败；
- 数据库保存失败。

异常处理统一遵守：

- `Competitor.status` 保持原值；
- `Competitor.is_active` 保持原值；
- 不创建正常 ProductSnapshot；
- 不创建 `product_offline` 或 `product_online`；
- 失败 CollectionRun 记录稳定错误类型和脱敏消息；
- 保留历史 Snapshot、历史 ChangeEvent 和 Competitor 最后有效摘要。

例如：

```text
active + verification       → 仍为 active
offline + verification      → 仍为 offline
unknown + parser failure    → 仍为 unknown
```

## User Stories

1. 作为商品监控用户，我希望只有明确的 1688 下架页面才能把商品标记为已下架，以免普通采集异常污染状态。
2. 作为商品监控用户，我希望正常商品页成功解析后才标记为在售，以免“未发现下架文案”被误当作在售。
3. 作为商品监控用户，我希望滑块验证页不会被判定为下架，以免商品状态被风控页面错误改变。
4. 作为商品监控用户，我希望商品下架后仍保持监控，以便系统继续发现恢复上架。
5. 作为商品监控用户，我希望主动停止监控与商品下架互不影响，由我决定是否继续监控。
6. 作为商品监控用户，我希望首次确认 `unknown → active` 只建立基线，不产生虚假的恢复上架事件。
7. 作为商品监控用户，我希望首次确认 `unknown → offline` 只建立下架状态，不产生虚假的商品下架事件。
8. 作为商品监控用户，我希望 `active → offline` 只生成一次商品下架事件。
9. 作为商品监控用户，我希望连续多次访问已下架页面不会重复生成商品下架事件。
10. 作为商品监控用户，我希望 `offline → active` 生成一次恢复上架事件。
11. 作为商品监控用户，我希望恢复上架后的首次 Snapshot 成为新的正常基线，不把下架期间的变化误报为价格、库存或 SKU 变化。
12. 作为商品监控用户，我希望恢复上架后的下一次正常采集恢复普通变化检测。
13. 作为商品监控用户，我希望下架检查成功被记录为成功采集，而不是异常采集。
14. 作为商品监控用户，我希望下架时保留最近一次正常商品数据，仍能查看历史价格、库存、SKU、标题和主图。
15. 作为商品监控用户，我希望下架页不会生成字段为空的伪 Snapshot。
16. 作为商品监控用户，我希望最近采集时间反映最近一次成功的下架检查，而不是停留在上一次正常商品 Snapshot 时间。
17. 作为商品监控用户，我希望 Dashboard 今日变化显示商品下架和恢复上架，并且每个竞品仍只占一行。
18. 作为商品监控用户，我希望商品下架在 Dashboard 中优先于价格、库存、SKU、主图和标题变化展示。
19. 作为商品监控用户，我希望 Detail 明确显示商品已下架，同时看到它仍在监控中。
20. 作为商品监控用户，我希望列表中的商品状态和监控状态独立显示，例如“已下架”和“监控中”同时出现。
21. 作为批量采集用户，我希望监控中的 offline 商品仍属于采集范围，以便继续检查恢复上架。
22. 作为批量采集用户，我希望遇到 verification 时沿用现有批次停止和人工处理流程。
23. 作为维护者，我希望 migration 在 SQLite downgrade 遇到新事件或空 snapshot_id 时安全拒绝，而不是留下临时表或丢失数据。

## Implementation Decisions

### 1. 采集结果边界

采集器/采集服务应把一次页面访问转换成有限结果：

```text
verification_required
offline
active
collection_error
```

`offline` 是成功得到的状态结论，不是采集失败。`active` 必须来自正常 parser 成功。`collection_error` 覆盖所有不能可靠判断的情况，并保持原商品状态。

verification 判断必须优先于 offline 判断；offline 判断必须优先于正常 parser 结果保存。不得通过 parser failure、字段缺失或 offerId 缺失推断 offline。

### 2. Competitor

继续使用现有 `Competitor.status` 三值约束，不增加生命周期专用字段：

- `unknown`：没有可靠状态基线；
- `active`：最近一次可靠结果为正常商品页；
- `offline`：最近一次可靠结果为明确下架页。

`is_active` 继续只表达用户监控意愿。下架、恢复上架和采集异常均不得自动修改它。

商品从 active 变为 offline 时，只更新 `status`、成功采集时间和必要的更新时间；不把下架页不存在的正常商品字段写入 Competitor。

### 3. ProductSnapshot

#### 下架

明确 offline 时：

- 不创建 ProductSnapshot；
- 不创建 SkuSnapshot；
- 不删除、修改或回填历史 Snapshot；
- 不清空历史价格、库存、SKU、标题、店铺或主图；
- 不创建字段全为 NULL 的空 Snapshot；
- 最新正常 Snapshot 继续表示“最近一次成功采集到的正常商品数据”。

#### 正常在售

正常 active 结果继续按现有规则创建 ProductSnapshot 和 SkuSnapshot，并更新 Competitor 当前摘要字段。

#### 恢复上架

`offline → active` 时创建本次正常 ProductSnapshot，并将其作为后续普通变化检测的基线。

### 4. CollectionRun

明确下架属于成功完成的状态检查：

- `CollectionRun.status = success`；
- `finished_at` 写入本次检查完成时间；
- `error_type = NULL`；
- `error_message = NULL`；
- 不要求存在 ProductSnapshot。

verification、网络、空白、登录、parser 和保存异常继续使用 `status = failed`，沿用现有稳定错误编码和脱敏错误信息。

不新增复杂任务系统，也不新增 lifecycle run 表。现有批量运行时，明确 offline 计入 succeeded；verification 继续停止后续批次。

内部采集结果和单条采集 API 必须允许成功结果的 `snapshot = null`，并提供可识别的结果状态 `offline`；正常 active 成功结果仍返回当前 Snapshot。该调整是为了表达真实结果，不是创建占位 Snapshot。

### 5. 最近采集时间

`Competitor.last_collected_at` 表示最近一次成功完成的采集/状态检查时间，而不再仅表示最近一次 ProductSnapshot 时间。

- active 成功：写入本次正常商品采集时间；
- offline 成功：写入本次下架状态检查时间；
- verification 或其他失败：不更新；
- `ProductSnapshot.captured_at` 仍只表示该 Snapshot 对应的正常商品数据时间。

Dashboard 的 `last_collection_at` 继续从 CollectionRun 的完成/开始时间聚合，必须把成功 offline run 纳入成功采集统计，但不纳入 failed collections。

### 6. ChangeEvent

沿用现有 ChangeEvent，不新增事件表。新增事件类型：

```text
product_offline
product_online
```

事件语义冻结为：

| 事件 | 前置状态 | 本次状态 | `snapshot_id` | `old_value` | `new_value` |
|---|---|---|---|---|---|
| `product_offline` | `active` | `offline` | `NULL` | `active` | `offline` |
| `product_online` | `offline` | `active` | 本次新 Snapshot | `offline` | `active` |

两个事件的 `competitor_id` 和 `detected_at` 取本次状态确认；`entity_key = NULL`。

事件生成规则：

- `unknown → active`：不生成 `product_online`；
- `unknown → offline`：不生成 `product_offline`；
- `active → active`：不生成生命周期事件；
- `offline → offline`：不生成生命周期事件；
- `active → offline`：只生成一个 `product_offline`；
- `offline → active`：只生成一个 `product_online`。

下架事件不能关联旧 Snapshot；恢复事件必须关联本次创建的新 Snapshot。

### 7. 普通变化检测与恢复基线

`detect_changes()` 当前只比较 ProductSnapshot 与当前正常 ProductData，并且已经忽略 product_status 变化。正式接入后采用以下最小规则：

1. `offline` 页面不调用普通 Snapshot diff，因为没有正常商品数据；
2. `active → offline` 只生成 `product_offline`；
3. `offline → active` 创建新 Snapshot，只生成 `product_online`，不调用普通字段 diff；
4. 下一次 `active → active` 以恢复上架这一轮的 Snapshot 为 previous，恢复价格、库存、SKU、主图和标题的普通检测；
5. `unknown → active` 创建首个正常 Snapshot，继续作为普通基线，不生成普通变化事件；
6. 不修改旧 Snapshot 的状态来伪造生命周期转换。

理由：恢复上架本身已经是一个更高优先级的生命周期事实。跳过恢复首轮普通 diff 可以避免把下架前最后数据与恢复后新数据之间的长期差异误报成同一时刻发生的普通变化，同时只需保留现有相邻 Snapshot 比较模型。

### 8. Dashboard 今日变化

Dashboard `/api/dashboard/today` 继续保持一个竞品一行，并纳入 active 监控对象的 `product_offline`、`product_online` 事件。

primary priority 冻结为：

```text
最新生命周期事件（product_offline 或 product_online）
price_increase / price_decrease
stock_changed
sku_added / sku_removed
main_image_changed
title_changed
```

生命周期事件整体优先于普通变化，但 `product_offline` 与 `product_online` 之间不设固定优先级。同一竞品当天同时存在两种生命周期事件时，按 `detected_at DESC`、再按 `id DESC` 选择最新事件作为 primary；`change_types` 仍保留所有真实事件类型。

Dashboard 展示要求：

- 增加“商品下架” Badge；
- 增加“恢复上架” Badge；
- 同一竞品的多个变化类型 Badge 横向排列，单个 Badge 使用 inline-flex 且禁止文字换行；
- 摘要显示“商品已下架”或“商品恢复上架”；
- 检测时间使用 `detected_at`，不得将其描述为商品真实发生变化的时间；
- 后端继续按统一 UTC 策略保存时间；Frontend 展示统一使用 `Asia/Shanghai`（UTC+8）。无 offset 的后端时间按 UTC 解析，已有 offset 的时间按原 offset 解析，不重复加时区偏移；
- 不新增上下架 KPI 卡；
- 不新增 7 天上下架趋势序列；
- 现有 `change_events` 总数和 changed competitors 统计包含生命周期事件；
- 现有 `failed_collections` 不包含成功识别的 offline；
- `is_active=false` 的竞品继续不出现在 Dashboard 今日变化中；
- Asia/Shanghai 今日边界保持不变。

7 天趋势仍只保留当前价格、库存、SKU 和失败采集序列，不新增上下架趋势字段。

### 9. Detail

Detail 继续使用现有状态字段和最近变化列表：

- `status = offline` 显示“已下架”；
- `status = offline && is_active = true` 显示“该商品已下架，目前仍在监控。”；
- `is_active = false` 仍独立显示“已停止监控”；
- 允许同时出现“已下架”和“监控中”；
- `recent_changes` 支持 `product_offline` 与 `product_online`；
- 生命周期事件显示事件名称和“检测时间”（`detected_at`），不得显示为“变化时间”或商品真实下架/上架时间；
- `latest_snapshot` 在下架期间继续返回下架前最后一个正常 Snapshot；
- 下架期间不生成空 Snapshot，因此价格、SKU 和库存仍代表最后一次正常采集事实；
- 不新增复杂生命周期时间轴；
- `latest_price_change` 仍只表达价格事件。

Detail change response 的 `snapshot_id` 必须改为 nullable，因为 `product_offline` 没有关联 Snapshot；只有生命周期事件需要时才为 NULL，普通事件仍必须有 Snapshot。

### 10. 竞品列表

列表继续分别显示：

- 商品状态：状态未知 / 在售 / 已下架；
- 监控状态：监控中 / 已停止。

商品状态 Badge 使用 inline-flex、水平/垂直居中、足够的最小宽度和 `white-space: nowrap`，保证“已下架”“在售”“状态未知”始终单行显示，不明显扩大整个状态列。

允许显示：

```text
商品状态：已下架
监控状态：监控中
```

列表不因为 offline 自动隐藏、删除或禁用继续监控的竞品。现有 `last_collected_at` 应显示最近成功的下架状态检查时间。

### 11. 单条采集

单条采集沿用当前 headed Chrome、登录态、全局采集锁和资源清理边界：

1. 查询 Competitor；
2. 继续拒绝 `is_active=false` 的手动采集；
3. 创建 running CollectionRun；
4. 使用 verification 优先、offline 次之、active 再次之的页面分类；
5. offline 成功时不创建 Snapshot，但更新 status、last_collected_at 和成功 Run；
6. active 成功时按现有 Snapshot/SKU/ChangeEvent 流程保存；
7. 失败时保留原状态和历史数据，并将 Run 标记 failed。

单条采集成功响应必须能区分：

- `outcome = active` 且 `snapshot` 有值；
- `outcome = offline` 且 `snapshot = null`。

不得返回伪造的空 Snapshot。

### 12. 批量采集

- `is_active=true` 的 active 和 offline 竞品都属于可监控对象；
- 不因为 `status=offline` 自动跳过；
- `is_active=false` 继续沿用现有不采集规则；
- offline 成功计入 succeeded；
- verification 继续停止后续批次、召回浏览器并等待人工处理；
- 普通异常计入 failed；
- 批量状态和 item 结果必须能表达 offline 成功，但不需要创建新的后台任务系统。

## Migration Decisions

### 必需 migration

1. `change_events.change_type` CHECK 增加 `product_offline` 和 `product_online`；
2. `change_events.snapshot_id` 从 NOT NULL 改为 nullable，以支持没有正常 Snapshot 的 `product_offline`。

### 不需要 migration

- 不新增生命周期表；
- 不新增 Competitor.status 值；
- 不新增 Competitor.is_active 字段；
- 不新增 ProductSnapshot 字段；
- 不新增 CollectionRun 状态值；`success` 已能表达明确下架检查成功；
- 不修改或回填历史 Snapshot；
- 不新增 Redis、Celery、消息队列或微服务。

### SQLite 安全要求

由于 SQLite 约束修改需要批量重建表，migration 必须：

- 在 upgrade 中同时修改 CHECK 和 `snapshot_id` nullable 属性；
- 保留现有数据、索引、外键和字段；
- 在 downgrade 前检查是否存在 `product_offline` / `product_online`；
- 在 downgrade 前检查是否存在 `snapshot_id IS NULL` 的事件；
- 只要仍存在任一新事件类型或 NULL snapshot_id，就明确抛出可读错误并拒绝 downgrade；
- 不留下 `_alembic_tmp_*` 临时表；
- downgrade 成功时恢复原 CHECK 和 NOT NULL 约束。

## Testing Decisions

测试优先验证外部行为、真实状态变化、事件数量、历史数据保留和 API/UI 合同，不测试某个私有函数的具体实现方式。优先复用现有 parser、collection service、TestClient、SQLite migration、Dashboard、Detail 和 `renderToStaticMarkup` 测试 seam。

### 页面分类与采集器

- 明确 offline selector + 精确文本命中得到 offline；
- selector 缺失、文本不精确、不可见或只出现部分条件不能得到 offline；
- verification URL/title/DOM 命中优先于 offline；
- baxia 页面立即检查未命中、300ms 后出现时得到 verification；
- 两次检查均未命中时只继续正常流程一次，不发生无限等待；
- 普通商品页不误判 offline；
- verification 页不误判 offline；
- 空白页、登录页和 parser 失败不误判 offline；
- HTTP 200、HTTP 非 200、offerId 缺失和字段缺失不能单独改变商品状态。

### 状态机与采集服务

必须覆盖：

| 场景 | 断言 |
|---|---|
| `unknown → active` | status active，创建正常 Snapshot，无 product_online |
| `unknown → offline` | status offline，无 Snapshot，无 product_offline |
| `active → active` | status 不变，普通 diff 按现有规则执行 |
| `active → offline` | status offline，成功 Run，只有一个 product_offline |
| `offline → offline` | status 不变、无新生命周期事件、无空 Snapshot |
| `offline → active` | status active、创建新 Snapshot、只有一个 product_online |
| 任意状态 + verification | status/is_active 不变，Run failed，无事件 |
| 任意状态 + 网络/空白/parser 失败 | status/is_active 不变，Run failed，无事件 |

额外断言：

- 下架后旧 Snapshot 完整保留；
- 下架不清空 Competitor.title、shop_name、main_image_url；
- 下架成功更新 `last_collected_at`；
- 异常不更新 `last_collected_at`；
- active→offline→offline 只有一个 product_offline；
- offline→active→active 只有一个 product_online；
- unknown→offline 不生成 product_offline；
- unknown→active 不生成 product_online；
- 恢复首轮不产生价格、库存、SKU、主图或标题普通事件；
- 恢复下一轮可以基于恢复 Snapshot 产生普通事件；
- `product_offline.snapshot_id is NULL`；
- `product_online.snapshot_id` 指向恢复本次新 Snapshot。

### CollectionRun、批量和 API

- offline Run 为 `success`，不计入 failed；
- offline 成功不返回 4xx/5xx；
- offline 成功响应的 snapshot 为 null，outcome 为 offline；
- active 成功响应仍包含正常 Snapshot；
- verification 仍返回现有 `1688_verification_required`；
- 批量中的 offline 计入 succeeded；
- offline 竞品只要 `is_active=true` 就不会被批量过滤；
- `is_active=false` 仍不能手动或批量采集；
- 失败保留旧 Snapshot、旧 Competitor 摘要和旧 status。

### ChangeEvent 与 migration

- 新 CHECK 允许两种生命周期事件；
- 非法事件类型仍被拒绝；
- nullable snapshot_id 允许只用于 product_offline；
- 普通事件仍拒绝 NULL snapshot_id；
- upgrade 后所有旧数据、索引和外键仍存在；
- clean database upgrade/downgrade 成功；
- downgrade 有新事件或 NULL snapshot_id 时安全拒绝；
- 拒绝后没有 `_alembic_tmp_*` 残留；
- 数据库重启和重复迁移保持幂等。

### Dashboard、Detail、List 和 Frontend

- 一个竞品当天多个变化仍只显示一行；
- 最新生命周期事件优先于价格、库存、SKU、主图和标题；
- product_offline 与 product_online 按 `detected_at DESC`、`id DESC` 选择 primary，不使用固定相互优先级；
- 两种生命周期 Badge 和摘要文案正确；
- Dashboard 不新增 KPI 和 7 天生命周期趋势；
- failed collections 不包含成功 offline；
- Asia/Shanghai 当日边界仍正确；
- Detail 显示“已下架”和“仍在监控”的组合状态；
- Detail 最近变化显示上下架事件和检测时间；
- 下架期间 latest_snapshot 仍为最后正常 Snapshot；
- List 商品状态和监控状态独立显示；
- inactive 竞品不进入 Dashboard 今日变化；
- 缺失值不伪造为 0、active 或空 Snapshot。

## Out of Scope

本 Feature 不做：

- 自动停止监控；
- 自动删除竞品；
- 自动降低 offline 商品采集频率；
- 通知、邮件、短信或消息提醒；
- 下架原因分析；
- 第二种未经 POC 验证的 offline 页面推断；
- 用 HTTP、parser failure、字段缺失或 offerId 缺失推断下架；
- 新建生命周期专用表；
- Redis、Celery、消息队列、微服务或定时任务架构；
- 上下架专用 KPI；
- 7 天上下架趋势；
- 生命周期时间轴；
- 图片 hash、图库变化或其他无关变化检测；
- 历史 Snapshot 回填或历史上下架事件补造；
- 自动 reload、验证码绕过或自动拖动滑块；
- 本 Feature 之外的平台商品状态检测。

未来如果需要为 offline 商品降低检查频率，应单独设计定时监控策略，不在本 Feature 中隐含实现。

## Expected Implementation Surface

以下是实现阶段预计需要评估的最小文件范围，不代表本轮已修改：

### Backend

- `backend/app/collection/collector_1688.py`：复用已冻结 verification 检测和页面分类边界；
- `backend/app/collection/parser_1688.py` 或采集分类边界：接入已验证 offline selector/text，不把页面缺失当作 offline；
- `backend/app/collection/types.py`：表达 active/offline/异常的采集结果；
- `backend/app/collection/service.py`：状态机、Run 成功/失败、Snapshot 创建条件、生命周期事件和恢复基线；
- `backend/app/models.py`：ChangeEvent 类型约束和 nullable snapshot_id 的模型契约；
- `backend/app/changes.py`：为恢复首轮提供跳过普通 diff 的调用边界，保持现有字段 diff 规则；
- `backend/app/competitors.py`：单条采集成功响应、列表 latest_change 的 nullable snapshot_id；
- `backend/app/competitor_detail.py`：生命周期事件响应和下架提示所需数据；
- `backend/app/dashboard.py`：生命周期事件聚合、priority、summary 和 badge 数据；
- `backend/app/collection/daily.py`：确认 offline 仍属于 active monitoring 范围；
- `backend/alembic/versions/`：ChangeEvent CHECK 和 snapshot_id nullable 的 SQLite 安全 migration。

### Frontend

- `frontend/src/App.tsx`：状态/监控状态文案、生命周期事件展示、单条采集结果处理；
- `frontend/src/App.test.tsx`：Dashboard、Detail、List 和状态组合渲染测试；
- 现有样式文件：仅在现有设计系统内增加必要 Badge/提示样式，不引入新 UI 依赖。

### Tests

- `backend/tests/test_collector_1688.py`；
- `backend/tests/test_parser_1688.py`；
- `backend/tests/test_changes.py`；
- `backend/tests/test_collection_api.py`；
- `backend/tests/test_dashboard.py`；
- `backend/tests/test_competitor_detail.py`；
- `backend/tests/test_competitors.py`；
- 新增或扩展 migration 测试；
- `frontend/src/App.test.tsx`。

## Further Notes

### 1. 当前产品决策是否还需确认

本 Spec 已冻结以下产品决策，无阻塞性确认项：

- offline 不自动停止监控；
- 明确 offline 是成功状态检查；
- offline 不创建 Snapshot；
- `product_offline.snapshot_id = NULL`；
- `product_online` 关联恢复本次 Snapshot；
- unknown 首次建立 active/offline 基线不产生生命周期事件；
- 恢复上架首轮只产生 product_online，不产生普通字段变化；
- 下一轮 active→active 恢复普通变化检测；
- verification 优先于 offline；
- 不新增生命周期表、任务系统或趋势/KPI。

### 2. 实现前必须保持的边界

- 本文是 Spec，不包含业务代码实现；
- 实现时不得把 parser 失败、验证页、登录失效、网络异常或字段缺失改成 offline；
- 实现时不得修改 `is_active` 的用户控制语义；
- 实现时不得用空 Snapshot 解决 nullable foreign key 问题；
- 实现时应先完成 Backend 状态机、事务和 migration，再接入 Dashboard/Detail/List；
- 实现后必须用真实 SQLite upgrade/downgrade 和完整 Backend/Frontend 测试验证。

### 3. POC 限制

当前 POC 的 active 对照曾受 1688 Profile 风控影响，不能把异常页计入 active。offline 强信号已经在 9 条真实商品、18 次访问中稳定命中，但正式实现仍必须保留未知/异常回退边界，并继续把未识别的页面形态归入异常或 unknown，而不是猜测。

### 4. Git 边界

本轮只生成本 Spec 文件，不修改业务代码，不修改数据库，不运行实现，不 commit，不 push，也不发布到外部 issue tracker。
