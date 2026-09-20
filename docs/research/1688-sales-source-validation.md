# 1688 销量数据源验证

## 1. 验证日期

2026-09-20。

## 2. 样本数量

- SQLite 中 `Competitor.is_active = true` 的样本：5 个。
- 成功捕获 `mtop.1688.pc.plugin.od.data.query`：3 个。
- 未捕获：2 个，均记录为 `request not triggered`。
- 未新增或修改 `Competitor`，未修改数据库。
- 3 个成功样本的接口响应数均为 1。

样本使用数据库中的 active URL。为避免在文档中扩散商品标识，样本以 Competitor ID 和 offer ID 尾部表示：

| Competitor | offer ID 尾部 | 捕获 |
|---|---:|---|
| 1 | 6789 | 否，request not triggered |
| 2 | 4321 | 否，request not triggered |
| 3 | 9158 | 是 |
| 4 | 8799 | 是 |
| 5 | 9503 | 是 |

## 3. 数据来源与方法

验证脚本为根目录 `poc_sales_validation.py`，独立读取本地 SQLite 中最多 5 个 active Competitor，使用本机 Chrome 和项目根目录 `.browser-profile`，通过 Playwright 监听真实浏览器响应，不构造签名、Token、Cookie 或请求头。

脚本允许现有浏览器扩展运行，并在每个商品页加载后等待插件请求。响应只在内存中解析，输出规范化观察结果；没有保存完整 response、Cookie、Token、headers 或登录信息。

## 4. 字段观察

### 4.1 last30DaysSales

在成功捕获的 3/3 个样本中存在，原始类型均为 `string`。本轮观察到的值为：`20+`、`<10`、`20+`。

本轮没有观察到逗号格式、`1万+`、`null` 或负数，但样本不足以证明这些情况不会出现。`20+`、`<10` 都不是精确整数，不能安全转换为 `int` 或 `Decimal`；不能把 `20+` 转成 20，也不能把 `<10` 转成 10。

结论：字段可以捕获，但当前只能保留为不确定的外部字符串事实，不能作为正式精确销量整数接入。

### 4.2 totalSales

在成功捕获的 3/3 个样本中存在，原始类型均为 `string`。本轮观察到 `60+`、`<10`、`1300+`。

它与 `last30DaysSales` 的时间范围明显可能不同，但本轮不足以证明其确切业务定义，也不能仅凭字段名定义为累计成交件数。

### 4.3 totalOrder

在成功捕获的 3/3 个样本中存在，原始类型均为 `string`。本轮观察到 `60+`、`<10`、`1200+`。

在 Competitor 5 上，`totalSales=1300+` 与 `totalOrder=1200+` 不同；在 Competitor 3 上二者同为 `60+`。这证明两个字段并非稳定相等，但仍不足以确认它们分别是件数和订单数。语义仍未验证。

### 4.4 saleQuantityList

成功捕获的 3/3 个样本均为 list，元素结构均为：

```text
{ "date": "YYYYMMDD", "saleQuantity": <numeric value> }
```

观察结果：

| Competitor | 记录数 | 日期范围 | 日期顺序 | 缺日 | 重复日期 | 近 30 条记录数量和 |
|---|---:|---|---|---:|---:|---:|
| 3 | 36 | 2026-06-27 ~ 2026-09-17 | mixed | 47 | 0 | 46 |
| 4 | 4 | 2026-09-11 ~ 2026-09-18 | descending | 4 | 0 | 8 |
| 5 | 22 | 2026-07-11 ~ 2026-09-19 | mixed | 49 | 0 | 34 |

每个记录都有日期，日期格式本轮稳定为 `YYYYMMDD`；未观察到未来日期、重复日期或 0 数量。数量键本轮稳定为 `saleQuantity`，可安全转为非负整数。

但记录并非每日一条：记录数不同，日期范围内存在大量缺日，且顺序也不一致。因此不能把它提前定义为“最近 30 天每日销量”。更保守的描述是：插件返回了一组带日期的销售数量记录，其记录粒度和业务口径仍未确认。

### 4.5 saleRangeList

成功捕获的 3/3 个样本均为 list，元素键稳定为 `date`、`minPrice`、`maxPrice`，日期格式为 `YYYYMMDD`；记录数为 91、9、86。

它表现为按日期的价格区间/档位相关数据，但本轮没有足够证据确认每项的正式业务含义，不纳入正式销量建模建议。

### 4.6 tradePriceList

成功捕获的 3/3 个样本均为 list，日期格式为 `YYYYMMDD`，记录数为 36、5、21。元素键稳定为：

```text
date
minPrice
maxPrice
minPriceQuantity
maxPriceQuantity
tradeCount
```

它是带交易数量/价格区间信息的外部历史结构，但本轮没有验证它与项目 `ProductSnapshot` 的价格快照在时间点、口径和刷新规则上完全一致。因此不建议用它替代项目自己的长期价格历史。

## 5. 跨商品一致性与正式接入判定

存在率按全部 5 个 active 样本计算；结构和类型按成功捕获的 3 个样本观察。

| 字段 | 样本存在率 | 数据类型 | 跨商品结构一致性 | 当前语义可信度 | 判定 |
|---|---:|---|---|---|---|
| last30DaysSales | 3/5 | string | 基本一致 | 低；模糊值且不能精确规范化 | PARTIAL |
| totalSales | 3/5 | string | 基本一致 | 低；累计范围和件数语义未验证 | PARTIAL |
| totalOrder | 3/5 | string | 基本一致 | 低；与 totalSales 有时不同但定义未验证 | PARTIAL |
| saleQuantityList | 3/5 | list | 元素键一致，时间粒度不一致 | 中低；数量可解析，历史口径未确认 | NOT_READY |
| saleRangeList | 3/5 | list | 元素键一致 | 低；价格区间语义未确认 | PARTIAL |
| tradePriceList | 3/5 | list | 元素键一致 | 中低；与内部价格快照语义未对齐 | PARTIAL |

本轮没有字段达到 `READY`。`3/5` 的整体捕获率还受到两个数据库 active URL 未触发插件请求的影响；这两个样本不能被当作销量为 0。

## 6. last30DaysSales 与历史数量和

对三个成功样本，`saleQuantityList` 均能识别 `saleQuantity`，并计算了按日期排序后的最近 30 条自然记录数量和：46、8、34。

由于对应的 `last30DaysSales` 原始值分别为 `20+`、`<10`、`20+`，均不是精确整数，本轮三者都只能标记为：

```text
cannot compare
```

本轮没有证据支持 `equal` 或 `different`。不能把模糊展示值与历史记录和强行比较。

## 7. 正式 Collector 可行性

最小可行采集 seam 已被 POC 证明：

```text
page.goto(product_url)
→ page.on("response") 捕获 plugin response
→ 只解析目标字段
→ 与 HTML ProductData 合并
```

但它不是现有“只依赖 page.goto → HTML → parser”的同步扩展：目标请求依赖官方采购助手扩展和当前浏览器登录/触发条件，需要启用扩展并在页面加载后等待。两个 active URL 没有产生请求，说明不能假设每个商品都必然有插件 response。

因此正式接入至少需要：

- 将插件响应视为可选补充来源；
- 请求未触发、登录失效、验证页和扩展缺失必须区别记录；
- 缺失销量保存为 `NULL` / 未采集，不得保存为 0；
- 不把插件历史列表直接复制进正式数据库。

本轮没有修改正式 Collector，也没有实现上述接入。

## 8. 推荐的最小正式数据模型候选

本轮不迁移数据库。

如果后续先完成模糊值策略和字段语义确认，最小候选是：

```text
ProductSnapshot.last_30_days_sales: Integer | NULL
```

只保存每天成功采集并能确认是精确非负整数的当前事实；缺失、模糊或插件未触发时保存 `NULL` / 未采集。长期趋势继续以项目每日 `ProductSnapshot` 为 Single Source of Truth。

本轮不建议新增 `total_sales`、`total_order` 或 `sales_history`：前两个语义尚未验证，后者会复制外部稀疏历史并引入未确认的时间口径。`saleRangeList` 和 `tradePriceList` 也不作为正式销量模型字段。

## 9. 是否进入 Schema Feature

不建议立即进入 Schema Feature。

下一步至少需要先解决：

1. `20+`、`<10` 等模糊值是否只做原始展示，还是业务允许转成区间/下界；
2. `totalSales` 与 `totalOrder` 的明确业务语义；
3. `saleQuantityList` 的记录粒度和计算口径；
4. 未触发插件请求的 active 商品如何稳定识别和处理；
5. 多次采集的值和结构稳定性。

## 10. Non-goals

- 不修改正式业务模型、数据库、Alembic、Collector、Parser、Collection Service、ChangeEvent 或 UI。
- 不新增销量 API、销量趋势、Dashboard 或 Detail 展示。
- 不把外部历史列表写入数据库。
- 不自动登录、不绕过验证码/风控、不删除 Cookie。
- 不保存 Cookie、Token、headers、完整 response 或登录信息。
- 不把接口未捕获解释为销量为 0。
- 不提交 Git commit。
