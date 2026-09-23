# Group Attention Priority V1

状态：正式产品 Spec；仅定义 Group-level Attention 规则，不包含 Dashboard 页面设计或实现。

## Problem Statement

当前系统保存 Snapshot 和 ChangeEvent，也能按组查看事实，但用户仍需自己比较不同商品组今天发生的变化，判断先看哪里。原始事件条数会受 SKU 数量和采集频率影响，直接计数会放大库存噪音、重复价格事件和同一商品的多个内容事件。系统需要在现有事实之上给出稳定、可解释的商品组查看优先级。

## Product Goal

产品长期定位为“1688 商品竞争情报工作台”。以我方商品组为中心，持续采集直接竞品的真实事实，识别并压缩竞争变化，帮助用户回答：今天哪些组值得先看、发生了什么、为什么值得看，然后进入 Group Detail 分析，并进入 Competitor Detail 查看证据。

本 Spec 只定义 Group Attention Priority V1。它是 `Snapshot → ChangeEvent` 之上的组级读取与聚合层，不替代事实来源。

页面职责：

- Dashboard：今天我应该先看哪些我方商品组？
- Group Detail：这个商品组为什么值得看？我方和直接竞品现在是什么状态？
- Competitor Detail：这个具体竞品发生了什么？证据是什么？

## Definitions

- **ChangeEvent**：现有变化事实记录。正式类型和字段以 `detect-competitor-changes.md` 与当前模型为准；本 Spec 只读取，不改写或补造事件。
- **Domain（变化领域）**：将一个竞品当天的相关事件归并后的业务主题：Price、Stock & Supply、SKU Structure、MOQ、Lifecycle、Content。
- **Competitor Attention**：一个当前组内直接竞品在今日各领域聚合后的内部贡献、强事件事实与摘要事实。
- **Group Attention**：当前组内直接竞品的 Competitor Attention 经递减聚合、覆盖修正、强事件下限和保护规则后得到的结果。
- **Attention Score**：Backend 内部排序与分档辅助值。它不是风险分或竞争力分，不向用户展示，不要求归一化，可大于 100。
- **Attention Level**：用户看到的查看优先级，仅有“重点关注”“建议查看”“一般变化”。
- **Strong Event**：满足明确业务条件、可直接抬高 Group Attention 最低 Level 的聚合事实。它不是新的 ChangeEvent 类型。
- **Reason**：由聚合事实形成、可结构化复用的用户可见说明，不是单条原始事件的逐行列表。
- **Changed Competitor**：当前组内 `group_role = competitor` 且今日至少有一条纳入计算的 ChangeEvent 的不同 Competitor。按不同 competitor_id 计数，不按事件条数计数。`own` 商品不计入竞品数，也不为本 V1 触发竞品关注。
- **Today / 今日**：`Asia/Shanghai` 当前自然日，从本地 00:00 至计算时刻；存储/查询使用该自然日对应的 UTC 半开区间 `[start, now)`。

分组范围采用当前 Competitor 的 `group_id` 与 `group_role` 关系，不重建事件发生时的历史组成员关系。只纳入 `group_id` 非空且当前角色为直接竞品的成员；未分组商品不产生 Group Attention。`is_active` 与商品 `status` 语义保持不变，不作为删除事件或伪造事件的理由。当天已有事件即使监控随后停止，仍属于当天事实。

## Event Priority Matrix

以下等级是单条事件的基础重要等级，已冻结。商品级与 SKU 级事件使用同一 ChangeEvent 类型，通过 `entity_key IS NULL` 与 `entity_key = sku_id` 区分；不新增 SKU 价格事件类型。

| 等级 | ChangeEvent 类型 / 语义 |
|---|---|
| S | `price_decrease`：商品级降价（`entity_key = NULL`）；SKU 价格下降（`entity_key = sku_id`） |
| A | `product_offline` 商品下架；`sku_removed` SKU 移除；`sku_sold_out` SKU 售罄；`sku_restocked` SKU 恢复有货 |
| B | `price_increase` 商品或 SKU 涨价；`product_online` 商品恢复上架；`sku_added` SKU 新增；`stock_increase` / `stock_decrease` 普通库存增加 / 下降 |
| C | `min_order_quantity_decrease` MOQ 降低；`min_order_quantity_increase` MOQ 提高 |
| D | `title_changed` 标题变化；`main_image_changed` 主图变化 |

历史 legacy `stock_changed` 只按 B 级普通库存变化兼容处理。不得从其旧、新值推断方向，不得升级语义或贡献。未知类型不参与分级，且不得据此生成 Reason。

基础内部权重冻结为 S=40、A=25、B=12、C=5、D=2。权重只供 Backend 计算，不代表业务风险、竞争力或 0–100 分。

## Attention Pipeline

1. 用 Asia/Shanghai 当日边界读取当前组直接竞品的 ChangeEvent；排除我方商品事件。
2. 按竞品、自然日和 Domain 分桶；保留底层所有事件，不写入新的历史事实。
3. 在 Domain 内按实体和状态转换做去重、覆盖/幅度修正及事件语义覆盖。
4. 计算各竞品领域贡献；领域贡献按 100% / 40% / 20% / 0% 递减聚合。
5. 对组内 Competitor Attention 按 100% / 50% / 25% / 0% 递减聚合，再加入封顶的竞品覆盖、同类高等级集中变化和领域多样性修正。
6. 独立识别 Strong Event；按分数阈值与 Strong Event 得出候选 Level，再应用保护规则。
7. 从聚合事实生成结构化 Reason，最多返回 3 条；产生今日覆盖数和最近变化时间。
8. 按稳定排序规则返回有今日变化的 Group Attention 结果。

原始 ChangeEvent 与 Snapshot 均完整保留。Attention 只做逻辑聚合，不能删除、改写、回填或伪造事件与快照。

## Competitor-level Aggregation

基本单位是“竞品 + 当前自然日 + 变化领域”。同一竞品在同一领域的事件不按事件数线性累加。领域以最高重要等级的有效事件作为主要贡献；同领域不同方向或反转必须保留可解释的事实语义，不能仅因同日存在多条记录就增加完整权重。

领域贡献 = 该领域主事件基础权重 + 允许的幅度/范围修正。领域排序后：最高贡献计 100%，第二计 40%，第三计 20%，第四及以后不增加基础贡献。领域修正先应用，再做上述递减聚合。

同一竞品同一领域覆盖修正仅可使用可追溯到 ChangeEvent 或关联 Snapshot 的事实；各类封顶见对应规则。采集更频繁、原始事件更多不能天然提高 Attention。

## Domain Deduplication Rules

| Domain | 纳入的事件 |
|---|---|
| Price / 价格 | `price_increase`、`price_decrease`，商品级与 SKU 级 |
| Stock & Supply / 库存供应 | `stock_increase`、`stock_decrease`、`sku_sold_out`、`sku_restocked`、legacy `stock_changed` |
| SKU Structure / SKU 结构 | `sku_added`、`sku_removed` |
| MOQ / 起批量 | `min_order_quantity_increase`、`min_order_quantity_decrease` |
| Lifecycle / 商品生命周期 | `product_offline`、`product_online` |
| Content / 商品内容 | `title_changed`、`main_image_changed` |

商品级和 SKU 级价格调整归并至同一个价格领域；标题与主图归并为一个内容领域；同一竞品多个 SKU 新增/移除分别合并为一次 SKU 扩充/收缩事实。多个领域可共同贡献，但边际递减且仅前三个领域贡献基础值。

## Price Rules

- 降价始终是 S 级；小幅降价不得降为 B/C。涨价始终是 B 级。
- 同竞品同日商品级降价与一个或多个 SKU 同方向降价是一个价格领域动作，不是多个完整 S。相同方向的商品级与 SKU 价格 Reason 也必须去重。
- 价格领域主事件采用其中最高等级（降价优先于涨价，等级仍由事件类型决定）；同一方向的 SKU 覆盖只作有限修正。商品级 + SKU 级不得按原始事件数重复获得完整权重。
- SKU 覆盖分母取事件关联的、代表本次变动后状态的 ProductSnapshot 中可识别的不同 `sku_id` 数；每个不同 SKU 最多计一次。关联 Snapshot 或 SKU 列表不可靠/缺失时不计算覆盖比例，只使用可确认的事件事实。SKU 移除覆盖分母取该事件当前 Snapshot 之前最近一条有效 Snapshot 中的 SKU 数；被移除 SKU 数取当天不同 `entity_key` 数。
- 同竞品价格领域范围修正起点：涉及多个 SKU +2；覆盖当时可靠 SKU 总数至少 30% 再 +2；至少 60% 再 +2；总计最多 +6。单商品或单 SKU +0。覆盖使用未四舍五入的真实比例；总数为 0 或未知时不计算比例。
- 幅度优先读取正式事件已有 `delta_rate`。它是相对变化率的百分数，不是 0–1 小数。可靠幅度分档的当前起点：降价 `<1%` 为微小、`1% 至 <5%` 为普通、`>=5%` 为明显；降价幅度仅修正内部强度和 Strong Event 判断，不改变 S 等级。幅度边界与内部加分是 V1 calibration parameter。涨价不触发降价 Strong Event。
- 价格幅度修正起点（V1 calibration parameter）：微小 +0、普通 +4、明显 +8；SKU 覆盖修正另计且最多 +6，因此单个 S 价格领域起点最高为 54。此建议使可靠的大幅降价在同等级中更靠前；需用真实 A19/Y35 与多 Group 场景校准，若实现前尚未确认则先确认，不由实现者自行调整。
- 当前商品级价格区间若 ChangeEvent 没有可靠 `delta_rate`（例如区间端点非同一数值、变化幅度无法对应单一价格），不从 `old_value/new_value` 猜一个代表价或比例；不做幅度修正，也不触发幅度型 Strong Event。SKU 的 `delta_rate` 可按同一 SKU 两个有效页面展示价格计算，不能解释为所有促销体系下的最终成交价。
- 同一价格实体当天先降后涨、先涨后降，按该实体的 `entity_key`（商品级为 NULL，SKU 级为 sku_id）检测方向反转。反转时 Dashboard Reason 使用“今日多次调整价格”事实语义，不断言最后方向以外的当前竞争含义，也不只显示“竞品降价”。若多个实体方向不同但不存在同一实体反转，Reason 可按实际方向分开汇总。

## Stock Noise Reduction Rules

- 普通 `stock_increase` / `stock_decrease` / legacy `stock_changed` 为 B。普通库存领域基础贡献 12。
- 同一 SKU 当日多次普通库存变化只计该 SKU 一次“发生库存变化”；不按 `100→90→85→83` 等采集次数重复计权。若同一 SKU 当日方向反转，Reason 使用“库存多次变化”或中性“库存变化”，不推断最终业务原因。
- 普通库存范围修正起点：多个不同 SKU 同时变化 +1；变化 SKU 覆盖率至少 30% 再 +1；至少 60% 再 +1；普通库存领域总贡献最高 15。
- 普通库存覆盖率分母优先取相关事件所对应的当前 ProductSnapshot SKU 集合；只有能确认事件属于当日同一个商品状态快照时才合并计数。legacy 事件没有可靠方向或关联快照时只作为保守 B 级库存变化事实，不推断方向；不可计算比例时只用可确认的不同 SKU 数。
- `sku_sold_out` 覆盖同一 SKU 同一状态转换上的普通 `stock_decrease` 语义；`sku_restocked` 覆盖同一 SKU 同一状态转换上的普通 `stock_increase` 语义。不得把同一次 `>0→0` 同时算为 A 售罄和 B 库存下降，也不得把 `0→>0` 同时算为 A 恢复有货和 B 库存增加。现有 ChangeEvent V2 正常只生成状态事件；覆盖规则用于聚合兼容。
- 售罄 / 恢复有货本身按 A 贡献，不套用普通库存最多 15 的领域上限；多个 SKU 售罄的额外强事件阈值见 Calibration Parameters。
- 库存下降不等于销量增加，库存增加不等于补货；库存变化不等于热度或成交量。系统只能描述“页面展示库存发生变化 / SKU 售罄 / SKU 恢复有货”。不得生成“爆单、热销、销量上涨/下滑、补货、清库存”等结论，除非未来有独立可靠事实来源。

## SKU Structure Rules

- `sku_added` 为 B，`sku_removed` 为 A。
- 同竞品同日多个 SKU 新增合并成一次“SKU 扩充”；多个移除合并成一次“SKU 收缩”，不按 SKU 数乘完整权重。
- 可以按不同 SKU 数和可靠 SKU 覆盖比例作有限修正；修正需封顶，不允许 SKU 数量线性刷高贡献。V1 校准时以主事件基础权重为下限，修正不得超过该领域基础权重的 25%。移除比例分母取事件前最近有效 Snapshot 的 SKU 数；新增比例分母取变动前 Snapshot SKU 数。分母缺失、为零或 Snapshot 不完整时不算比例。
- SKU 收缩比例达到 30% 的 Strong Event 起点见 Calibration Parameters；该阈值不是事件等级变化。

## Lifecycle / State Reversal Rules

- 生命周期两种方向事件均保留。今日同时出现 `product_offline` 与其后的 `product_online` 时，Attention 仍认为今天发生重要 lifecycle 变化；Dashboard 不得继续显示“竞品下架”，可表达为“1 家竞品今日发生上下架状态变化”。
- 生命周期当前状态以该竞品当天最后一条生命周期事件（`detected_at`，相同时间以稳定事件 ID）确定；如果当天存在反向事件，不将先前状态描述成当前状态。没有反转时允许表达当天发生的方向事实。
- 同一 `sku_id` 当天 `sku_sold_out` 后 `sku_restocked`，保留两条事件和其 Strong Event 事实；当前 Dashboard Reason 改为“今日发生 SKU 供应状态变化”，不能继续说当前售罄。没有反转时可表达售罄/恢复有货事实。
- 价格反转依 Price Rules 处理。V1 只按当日现有事件及实体识别，不加持久化状态、事件合并表或猜测平台当前策略。
- Group Detail 继续通过既有 ChangeEvent 时间线呈现保留的历史事实；Attention 不改变 Group Detail V1 contract。

## Multi-Competitor Aggregation

- 不同竞品各自形成 Competitor Attention 后再聚合，不直接对所有事件或竞品分数求和。
- 竞品贡献按从高到低依次为 100%、50%、25%、0%；第四家及以后不再直接增加完整 competitor contribution。相同贡献以稳定 competitor_id 兜底，不影响最终总值。
- 变化竞品覆盖修正起点：1 家 +0，2 家 +3，3 家 +6，4 家 +8，5 家及以上 +10（封顶 +10）。这是绝对数量的递减修正。
- 组内直接竞品总数可用于弱覆盖率修正，但优先级严格为：事件重要度 > 变化竞品绝对数量 > 覆盖率。覆盖率不能单独触发 Strong Event 或跨越一个 Level；例如 1/1 不得因 100% 覆盖而超过高等级事件。V1 覆盖率不增加额外数值，除非真实数据校准后另行修订本 Spec。
- 同类高等级集中变化：同日有 2 家不同竞品发生同一种 S/A 级动作，加 +4；3 家及以上加 +8，封顶 +8。价格涨与降不视为同一种动作；商品下架、SKU 售罄、SKU 恢复有货、SKU 移除等按相同事件类型/相同方向分别聚合。D/C 不参与。
- Group 多领域弱修正：1 个实际变化领域 +0，2 个 +2，3 个及以上 +4，封顶 +4。领域数按今日有有效事实的不同 Domain 计，不按事件数计；不能压过 S/A 事件等级，也不单独触发 Strong Event。
- 同类高等级集中变化以“不同竞品数”计；同一竞品在同一动作类型的多个 SKU 事件仍只贡献一家。

## Strong Event Rules

Strong Event 只确定 Group Attention 的最低关注 Level，不抹去事件等级，也不代替 Score。相同 Group 当日若命中多个条件，采用最高下限。

### 最低“重点关注”

1. 商品级可靠明显降价：`entity_key = NULL` 的 `price_decrease`，可靠 `delta_rate` 降幅绝对值至少 5%。
2. 同一竞品多个 SKU 当日可靠明显降价：每个不同 SKU 均为 `price_decrease` 且降幅至少 5%；所需 SKU 数量是校准参数，不默认实现者决定。
3. 3 家及以上不同直接竞品同日发生任一商品级或 SKU 级价格下降。单家降幅无需达到 5%。
4. 2 家及以上不同直接竞品同日发生 `product_offline`。

### 最低“建议查看”

1. 单家直接竞品 `product_offline`。
2. 2 家不同直接竞品同日发生价格下降。
3. 一家竞品明显 SKU 结构收缩：不同 SKU 移除数 / 变动前可靠 SKU 数至少 30%。阈值是校准参数。
4. 同一竞品多个 SKU 当日售罄；数量/占比阈值是校准参数。
5. 多家直接竞品同日发生 SKU 售罄，至少为“建议查看”。V1 不单凭此条件设置“重点关注”；更高 Level 可由已确认的 Score 分档触发。

### 明确不单独触发 Strong Event

普通库存增加/下降/legacy `stock_changed`、SKU 恢复有货、SKU 新增、商品恢复上架、MOQ、标题、主图。多个此类事件仍受 Score 与保护规则约束。

如果强事件要求的字段、关联 Snapshot 或分母不可可靠取得，则不触发依赖该事实的 Strong Event；不得猜测或用缺失值补齐。

## Attention Score

Score 是内部排序值，按 Domain 和 Competitor 递减贡献、有限覆盖/集中/多领域修正及价格幅度修正形成。价格幅度与覆盖修正先应用于单一竞品领域贡献，再参与领域/竞品递减。不进行 0–100 归一化；值可超过 100。事件基础权重、修正项及封顶值均在本 Spec 明示，后续如需调参必须用真实业务场景校准并更新 Spec。

事件等级 != 最终 Group Attention Score；Attention Score != 用户看到的关注等级。Score 不以原始事件条数累加，也不代表风险、威胁、竞争力、商品好坏或运营建议。用户不可见 Score 数字、加分项、公式、所谓百分制或评分解释。

最近变化时间不进入 Score。时间不提供线性衰减或新近度加分；只在同 Level、相近 Score 时用于排序辅助。

## Attention Level

候选 Level 分档（V1 calibration starting point）：

| Group Attention Score | 最低 Level |
|---|---|
| `>= 60` | 重点关注 |
| `>= 30` 且 `< 60` | 建议查看 |
| `< 30` | 一般变化 |

最终 Level 是 Score 分档与 Strong Event 最低 Level 中较高者，再执行 Protection Rules 的上限。若 Strong Event 已设置最低 Level，它不能被低 Score 降回；若保护规则限制最高 Level，则保护规则优先。

- **重点关注**：今天存在明确的重要竞争变化，或多个竞品出现较广泛的高价值变化，建议优先进入 Group Detail。
- **建议查看**：今天存在值得了解的竞争变化，但整体优先级低于重点关注。
- **一般变化**：今天检测到变化，但主要是普通、局部或低优先级调整。

三个名称只表达查看优先级，不表达风险、威胁、竞争力、商品好坏或运营建议。

## Protection Rules

**A：C/D-only 上限。** 若组内所有纳入事件仅为 C/D，则最高为“一般变化”，无论竞品数、事件数或重复采集次数多少。C/D 多领域修正不能绕过此上限。

**B：普通库存-only 上限。** 若组内事件仅为普通 `stock_increase`、`stock_decrease`、legacy `stock_changed`，且没有价格事件、SKU 结构事件、生命周期事件、`sku_sold_out` 或 `sku_restocked`，最高为“建议查看”。大量普通库存变化不能触发“重点关注”。

保护规则限制最终 Level，不删除对应事件，也不改变 Reason 的事实内容。

## Time Semantics

1. 今日采用 `Asia/Shanghai` 当前自然日，当日 00:00 至当前时间；用半开区间查询。
2. 跨自然日后重新计算；昨日 Score 不延续到今日。
3. 昨日 ChangeEvent 历史继续保留并可由 Group Detail、趋势和历史查看。
4. `detected_at` 是系统检测时间，不声称是平台真实发生时间。
5. 最近变化时间只作为用户可见新鲜度信息，以及同 Level、相近 Score 时的排序辅助。
6. 不做小时级或其他复杂时间衰减；普通库存新近变化不能压过重大降价。
7. 同一时间的状态事件以稳定 event ID 作次序兜底。

## Reason Summary

每个有今日变化的 Group 输出：

1. 一行变化覆盖，例如“3 家竞品今日发生变化”。
2. 最多 3 个核心 Reason；少于 3 个时不填空项。
3. 最近变化时间。

Reason 必须来自聚合事实。跨竞品同类型同方向的事实合并，例如“3 家竞品降价”；同竞品多个 SKU 同类变化合并，例如“1 家竞品多个 SKU 降价”；商品级与 SKU 级同方向价格调整避免重复摘要。标题和主图可合并成“商品内容调整”。涨价/降价、MOQ 提高/降低方向必须保留。售罄覆盖普通库存下降 Reason，恢复有货覆盖普通库存增加 Reason。状态反转后使用中性、当前状态安全的“今日发生上下架状态变化”“今日发生 SKU 供应状态变化”；价格反转使用“今日多次调整价格”。

Reason 候选顺序与业务优先级一致：明显降价；商品下架；SKU 售罄；SKU 移除；价格上涨；SKU 恢复有货；SKU 新增；普通库存变化；MOQ；标题；主图。排序优先考虑 Strong Event、事件等级、不同竞品覆盖、变化范围，最后以最近变化时间；复用已计算的事实，不另建第二套评分。低优先级 Reason 不能挤掉仍存在的更高优先级事实。仅标题/主图/MOQ 等 C/D 事实不能因数量多进入高关注结论。

用户可见 Reason 只陈述事实，例如“2 家竞品降价”“1 家竞品减少 SKU”“3 家竞品出现库存变化”。禁止“竞争加剧”“正在抢市场/清库存”“销量暴增/下滑”“建议跟价/补货/修改 SKU”等推断与行动建议。

### Structured Reason Contract

Backend 返回有限、可版本化的结构化事实与展示文本，而不是只返回不可处理的自然语言字符串。每个 Reason 至少包含：

- 稳定 `reason_type`：对应方向明确的聚合事实，如 `price_decrease`、`price_increase`、`sku_sold_out`、`stock_changed`、`sku_removed`、`product_content_changed`、`lifecycle_changed`、`price_adjusted_multiple_times`、`sku_supply_changed`；
- `display_text`：依据已聚合事实生成的简短中文展示文本；
- `competitor_count`：该事实涉及的不同直接竞品数；
- 可选 `sku_count`：该事实涉及的不同 SKU 数，只有可确认时返回；
- 可选 `direction`：仅在类型具有确定方向且没有反转歧义时返回；
- `event_level`：对应主要事件等级 S/A/B/C/D；混合事实使用最高等级；
- `current_state_safe`：表示该语义是否已按当日反转处理，避免把历史中间态当作当前态。

不可靠或不适用的可选值省略或返回 null，不填造默认数。`display_text` 与结构化事实同时返回：前者保证界面一致、后者供 Dashboard / Group Detail / 通知或未来 AI Summary 复用并可独立验证。V1 不定义通知或 AI 功能。

## Ordering

今日有变化的 Group 按以下键依次排序：

1. `attention_level`：重点关注 > 建议查看 > 一般变化；
2. `attention_score`：同 Level 内降序，仅供 Backend 内部排序；
3. `strongest_event_level`：S > A > B > C > D；
4. `changed_competitor_count`：多者优先；
5. `latest_change_at`：较新者优先；
6. `group_id`：稳定兜底。

相同输入每次刷新顺序一致。排序若需内部 Score，可由 Backend 完成后只返回已排序列表；用户不需要看到分数。

此排序是 Dashboard Attention 职责，与现有 Group Summary 的管理/基础 Summary 排序不同。不得无意修改 `/api/competitor-groups/summary` 既有排序 contract。

## Backend / Frontend Responsibility

- Attention 规则必须由 Backend 聚合层统一执行；不得在 React 或多个页面分别实现。
- Frontend 不得批量读取 ChangeEvent 后 groupBy，不得计算 Score/Level、识别 Strong Event、做领域去噪或排序。
- Frontend 只消费 Backend 的已排序 Group、`attention_level`、变化竞品数、结构化 Reasons / Facts、最近变化时间及稳定展示所需字段。
- Group Detail 与 Competitor Detail 继续展示现有详细事实和证据；Attention 摘要不改写其含义。

## Read Contract Expectations

后续 Group-first Dashboard 应消费专门的 Backend Group Attention read model，职责是按既定规则读取、聚合并返回 Group Attention；不在本 Spec 锁定 endpoint 名称。契约至少应能表达组身份、attention level、已排序结果、变化竞品数、最多 3 个结构化事实摘要、最近变化时间，以及无变化/无可用数据状态。内部 Score 可以只用于 Backend 排序，无需传给用户端。

此 read model 不等于扩展或重定义现有 Group Summary contract。它应复用现有 ChangeEvent、Snapshot、Competitor、CompetitorGroup、`group_role` 与 Asia/Shanghai 日期能力；不要求新增持久化表、列或快照类型。数据库若无本需求所需改动则不做迁移。

今日无 ChangeEvent：不生成 Attention Level 或虚假 Reason，不进入“今日需要关注的变化 Group”列表；读契约应明确返回无变化/none 状态或空列表。它可与未来展示“今日暂无明显变化”的全部组列表分离，不得伪装成有变化。

## User Stories

1. 作为运营者，我希望先看到今天最值得查看的我方商品组，以便减少逐个检查竞品的时间。
2. 作为运营者，我希望每个关注层级都能对应不超过三条聚合事实，以便快速理解原因并进入 Group Detail。
3. 作为运营者，我希望一个竞品的多条 SKU 事件被降噪，以便采集密度不扭曲优先级。
4. 作为运营者，我希望多家竞品同步降价或下架时获得更高关注，以便及时发现广泛变化。
5. 作为运营者，我希望库存被描述为页面展示事实，以免把库存变化误读成销量或补货。
6. 作为运营者，我希望当天状态反转后摘要不再描述已失效的中间状态，同时保留完整历史证据。
7. 作为运营者，我希望 C/D-only 与普通库存-only 组受保护上限约束，以免低价值噪音占据重点位置。
8. 作为运营者，我希望 Level 和 Score 分离，以便看到的是明确查看优先级而不是虚假精确的分数。
9. 作为运营者，我希望跨日后只计算新的一天，以免昨日变化污染今日列表。
10. 作为运营者，我希望同样输入刷新后排序一致，以便列表稳定、可复核。

## Implementation Decisions

- 仅在 Backend 聚合/read 层实现组级 Attention；本轮 Spec 阶段不写代码。
- 使用当前组关系、当前 `group_role` 和 ChangeEvent 关联的现有 Snapshot；不推测事件发生时的历史组关系。
- 价格幅度仅采用可靠 `delta_rate`；价格覆盖、SKU 结构和库存覆盖仅采用可追溯的关联 Snapshot / SKU ID。
- Attention 输出为只读派生结果，不保存为新的业务历史事实；原 ChangeEvent 和 Snapshot 保持原样。
- 结构化 Reason 与 `display_text` 同时输出，减少多页面复制文本判断，同时保留可供其他消费者复用的事实 contract。
- 不添加新的 ChangeEvent 类型、业务表、migration、后台任务、依赖、服务或评分框架。
- 本 Spec 不修改 `Competitor.status`、`is_active`、Group Detail V1、Competitor Detail 或 Group Summary 的既有语义与 contract。

## Testing Decisions

测试最高使用外部业务 seam：给定真实 ChangeEvent、关联 Snapshot / SkuSnapshot 与当前 Group 成员关系，读取 Group Attention 结果，断言最终 Level、排序、变化竞品数和 Reasons。优先验证最终用户可观察行为，不测试内部 helper 的拆分方式。日期测试固定时钟并覆盖 Asia/Shanghai 自然日半开边界。

至少覆盖以下场景：

| Case | Given | Expected |
|---|---|---|
| 1 | A19 一家竞品商品级降价 8%，具备可靠 `delta_rate` | 命中 Strong Event；Level 至少“重点关注” |
| 2 | Y35 五家竞品各自只有少量普通库存变化 | 库存-only 最高“建议查看”；不能因事件量压过 Case 1 |
| 3 | 三家不同竞品同日各降价 2% | 命中多竞品价格 Strong Event；“重点关注” |
| 4 | 一家竞品 SKU 移除比例至少 30%，分母 Snapshot 可靠 | 至少“建议查看”；比例不可靠时不触发此 Strong Event |
| 5 | 四家竞品全部只改主图 | D-only 保护生效，最高“一般变化” |
| 6 | 同竞品商品降价、多个 SKU 同降、多条普通库存下降、一个 SKU 售罄、标题和主图均变化 | 价格不重复计完整 S；售罄覆盖同 SKU 普通下降；Content 合并；Reason 至多 3 条 |
| 7 | 同一 SKU 09:00 售罄、14:00 恢复有货 | 两条历史事件保留；Dashboard 不称当前售罄，输出供应状态变化语义 |
| 8 | 10:00 下架、15:00 恢复上架 | 历史保留；摘要表达今日上下架状态变化，不称当前下架 |
| 9 | 同一价格实体 09:00 49→39、15:00 39→49 | 不只显示竞品降价；输出今日多次调整价格的中性事实 |
| 10 | 同一 SKU 库存 100→99→98→97 | 当天只计一次该 SKU 普通库存变化，不产生三份完整 B |
| 11 | Group A 一家竞品明显商品降价；Group B 五家轻微库存变化 | A 的 Level / 排序不被库存-only 数量轻易压过 |
| 12 | 大量竞品只有 MOQ / 标题 / 主图变化 | C/D-only 最高“一般变化” |
| 13 | 今日无 ChangeEvent | 无 Level、无虚假 Reason，不进入今日变化 Group 列表；读结果为空/none 明确 |
| 14 | 昨日有重大降价、今日无事件 | 昨日事件不参加今日 Attention，历史仍可查看 |
| 15 | Level、Score、strongest level、变化竞品数、最近时间均相同 | 最终以稳定 group_id 兜底，重复读取顺序一致 |

还需断言：legacy `stock_changed` 不猜方向且最多按普通 B；未知/缺失 delta_rate 不触发幅度判断；事件时间恰在本地日界时只归属一个业务日；我方 `group_role=own` 事件不计入竞品数与竞品 Reason；未分组/不属于当前组的竞品不混入结果；原始历史行未被删除或改写。

## Calibration Parameters

原则与基础等级已冻结；下列数字是 V1 起点/校准项，不应由实现者自行更改。实现前仍未由真实数据确认的项目须先确认，不能默默拍板。

### 已冻结规则

- 基础事件等级及内部权重：S/A/B/C/D = 40/25/12/5/2。
- Domain 递减贡献：100% / 40% / 20% / 之后 0%；竞品贡献递减：100% / 50% / 25% / 之后 0%。
- 普通库存领域基础 B=12、上限 15；库存 SKU 范围修正为 +1/+1/+1 的结构与封顶。
- 价格多 SKU 范围修正 +2、SKU 覆盖档位分别 +2/+2、合计封顶 +6。
- Group 变化竞品绝对覆盖修正 0/3/6/8/10；同类 S/A 集中修正 +4/+8 封顶；多领域修正 0/+2/+4 封顶。
- 降价事件始终为 S；幅度分档和分档修正的建议起点列于下方校准表，不改变事件等级。
- 多家竞品集中降价、生命周期 Strong Event 的竞品数规则；库存与 C/D 保护规则；三档 Level 文案及排序键。

### V1 calibration parameters（当前建议起点）

| 参数 | 起点 | 校准原因与验收要求 |
|---|---|---|
| 多 SKU 明显降价的“多个” | 同一竞品至少 2 个不同 SKU，且各自可靠降幅 >=5% | 判断单 SKU 与广泛 SKU 调价差异；用真实 A19、Y35 和多组数据人工验收，未确认前实现前必须确认 |
| 价格幅度分档与内部修正 | `<1%` +0；`1%–<5%` +4；`>=5%` +8 | 体现可靠降价幅度对同级排序的影响；确认 `delta_rate` 百分数语义后，用真实 A19、Y35 与多 Group 日结果校准 |
| 多 SKU 售罄阈值 | 同一竞品同日至少 2 个不同 SKU 售罄；SKU 覆盖可作辅助，不独立推高为重点关注 | 避免单规格噪音，同时识别多规格供应变化；用真实多 SKU 商品校准 |
| SKU 收缩明显阈值 | 不同移除 SKU / 变动前 SKU 总数 >=30% | 依赖快照完整性和实际 SKU 数分布；用真实 Group 校准 |
| SKU/库存/价格覆盖阈值 | 覆盖档位 30% / 60%；多 SKU 至少 2 个 | 边界对小 SKU 数商品敏感；核验分母、有效 SKU 数与真实 A19/Y35 变化 |
| Score 分档 | `>=60` 重点关注、`>=30` 建议查看 | 只是起始切点，不是数学真理；用真实 A19、Y35 及多个 Group 的完整日结果校准 |
| SKU 结构范围修正封顶 | 单领域附加修正不超过该领域基础权重的 25% | 限制 SKU 数线性增权；人工验收后定值，不能超越 S/A 事实优先级 |

每次校准必须看整组排序、Strong Event 命中和 Reason，而不只看单个公式输出。校准不能改变事件事实、把 Score 暴露给用户或绕过保护规则。

## Out of Scope

- AI / LLM 判断或评分、黑盒评分、自动学习权重、机器学习。
- 用户个性化评分、Redis、Elasticsearch、微服务、WebSocket。
- 销量或市场热度推断、风险评分、竞争力评分。
- 自动定价、自动运营、自动补货建议。
- 自动匹配竞品、通知系统、新供应商数据采集或 Supplier Intelligence。
- Dashboard UI 重构或页面视觉设计；当前 Group Detail 重构。
- 修改 ChangeEvent / Snapshot 历史、Competitor.status / is_active 语义、Group Detail V1 或现有 Group Summary contract。
- 新的事件类型、数据库表/字段、迁移或持久化评分历史。

## Acceptance Criteria

- 对所有正式 ChangeEvent 类型完成等级与 Domain 映射，legacy `stock_changed` 只保守兼容。
- 同竞品去重、状态覆盖、价格幅度、SKU 覆盖、库存降噪和反转规则均可由本 Spec 的例子判定。
- Group 聚合使用递减贡献、覆盖封顶、S/A 同类集中加成和 C/D / 库存-only 保护。
- Strong Event 只能抬高最低 Level；分数分档、保护上限和最终 Level 的先后关系明确。
- Reason 有稳定结构化事实与文本、当前状态安全语义、明确优先级且不超过 3 条。
- 今日边界、跨日、排序兜底、无变化结果和 Frontend/Backend 职责均明确。
- 上述 Testing Decisions 的 15 个主要场景及补充断言进入后续实现验收。
- 不改变 ChangeEvent、Snapshot、Group Detail、Competitor Detail、Group Summary 的既有事实与管理职责。

## Further Notes

本 Spec 不要求一次性证明权重数学最优。V1 目标是按真实事实给出稳定、可解释、少噪音的查看顺序；真实 A19 / Y35 与多 Group 场景的人工验收是校准依据。长期事实链路为：

`Snapshot → ChangeEvent → Group Attention → Group-first Dashboard → Group Detail → Competitor Detail`
