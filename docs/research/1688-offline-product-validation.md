# 1688 商品下架识别 POC

## 结论摘要

本轮使用现有 headed Chrome、项目 `.browser-profile` 和登录态采集方式，未修改数据库、`Competitor.status`、`ChangeEvent` 或正式采集逻辑。

上一轮 3 条 offline 样本的结论已在本文后续历史记录中保留。本轮扩展验证了数据库中的 9 条用户确认 offline 样本，并用 5 条 active 候选 URL 做了两轮对照尝试。

本轮 9 条 offline 样本全部在 `goto(wait_until="domcontentloaded")` 和 `reload(wait_until="domcontentloaded")` 返回后立即命中同一组页面信号。5 条 active 候选中只有 1 条在两轮均正常采集，其余访问期间触发或停留在 1688 验证/空白异常页面，因此本轮没有得到 5 条“当前正常可采集”的有效 active 对照。

当前最有价值的候选强信号仍是：

```text
可见元素：h3.mod-detail-offline-title
精确文案：商品已下架
```

离线 selector 在本轮证据中没有 false positive，但正式 Spec 仍不能在本轮冻结：active 对照未满足 5 条当前正常采集的要求，而且真实 verification 页面暴露出当前 wait strategy 下 existing verification 判断的时序漏检。

## 1. 验证范围与方法

- 时间：2026-09-22。
- 浏览器：Playwright persistent context，Chrome channel，`headless=False`。
- Profile：项目根目录 `.browser-profile`。
- 访问方式：复用现有 headed collector 的 persistent context、`domcontentloaded` 导航、页面 title/URL/HTTP response 检查、verification 检查和 `parse_1688_html`。
- 每个样本访问 2 轮；两轮均为同一 headed context 内顺序访问。
- 未保存完整 HTML、Cookie、Token、请求头或浏览器会话。

样本选择：

- offline：数据库中 2026-09-22 07:18 新增、当前仍为 `unknown` 且没有快照的 3 条记录：competitor `12/13/14`。
- active：数据库中已有多次成功采集记录的 3 条记录：competitor `1/2/3`。

## 2. offline 样本结果

三条 offline 样本在两轮中均得到：HTTP 200、最终 URL 与请求 URL 相同、无导航异常、现有 verification 判断为 false、现有登录判断为 false、页面访问检查为 allowed。

| competitor | offerId | 最终 URL | document.title | 核心页面信号 | 结构化商品数据 | 现有 parser |
|---:|---|---|---|---|---|---|
| 12 | `1081809347336` | `https://detail.1688.com/offer/1081809347336.html` | 暖手宝定制厂家企业礼品LOGO定制磁吸充电暖手宝节日礼赠OEM批发-阿里巴巴 | 可见 `h3.mod-detail-offline-title`，文案“商品已下架”；另有“查看该店铺其他上架商品”“查看其他商品” | `offerId=0`、`subject=0`、`companyName=0`、`skuInfoMap=0`；仍出现 `skuId=4`、`canBookCount=4`、`discountPrice=4` | `CollectionParseError: missing or invalid offer_id` |
| 13 | `1081379064852` | `https://detail.1688.com/offer/1081379064852.html` | 手持小风扇大风力便捷随身usb可充电静音电风扇迷你新款家用户外-阿里巴巴 | 同上 | `offerId=0`、`subject=0`、`companyName=0`、`skuInfoMap=0`；仍出现 `skuId=2`、`canBookCount=2`、`discountPrice=2` | `CollectionParseError: missing or invalid offer_id` |
| 14 | `1063735865360` | `https://detail.1688.com/offer/1063735865360.html` | 锐塔克自拍杆2026新款双机位落地三脚架相机通用旅游便携拍照支架-阿里巴巴 | 同上 | `offerId=0`、`subject=0`、`companyName=0`、`skuInfoMap=0`；仍出现 `skuId=6`、`canBookCount=6`、`discountPrice=6` | `CollectionParseError: missing or invalid offer_id` |

页面正文的三条结果均为：

```text
商品已下架
查看该店铺其他上架商品
查看其他商品
```

注意：expected offerId 仍能在 offline HTML 中找到，但只出现在 URL、canonical、meta 或其他页面上下文中；它没有作为正式结构化 `"offerId"` 字段出现。因此“页面包含 expected offerId”不是下架强信号。

## 3. active 对照结果

三条 active 样本在两轮中均得到：HTTP 200、最终 URL 与请求 URL 相同、无导航异常、现有 verification 判断为 false、现有登录判断为 false、页面访问检查为 allowed，并成功通过现有 parser。

| competitor | offerId | 最终 URL | document.title | 商品字段 | 结构化字段 | parser 结果 |
|---:|---|---|---|---|---|---|
| 1 | `1079906223307` | `https://detail.1688.com/offer/1079906223307.html` | 新款磁吸分离式暖手宝双面速热数显温度便携暖手宝冬季取暖器批发 - 阿里巴巴 | 标题、店铺、价格 `38.00-38.00`、4 SKU，stock `[476,0,474,498]` | `offerId=17`、`subject=2`、`companyName=4`、`skuInfoMap=1`、`skuId=28`、`canBookCount=20` | 成功，expected offerId 匹配 |
| 2 | `1080864798243` | `https://detail.1688.com/offer/1080864798243.html` | 冬季暖手宝二合一女生暖宝宝随身便携磁吸充电新款源头工厂批发 - 阿里巴巴 | 标题、店铺、价格 `38.00-38.00`、5 SKU，stock `[1000,1000,999,1000,1000]` | `offerId=14`、`subject=2`、`companyName=4`、`skuInfoMap=1`、`skuId=35`、`canBookCount=25` | 成功，expected offerId 匹配 |
| 3 | `1083985416394` | `https://detail.1688.com/offer/1083985416394.html` | 2026新款磁吸数显暖手宝6000毫安二合一分离式迷你便携式礼品批发 - 阿里巴巴 | 标题、店铺、价格 `34.00-38.00`、3 SKU，stock `[1000,1000,993]` | `offerId=14`、`subject=2`、`companyName=4`、`skuInfoMap=1`、`skuId=21`、`canBookCount=15` | 成功，expected offerId 匹配 |

三条 active 页面均没有可见 `.mod-detail-offline-title`，正文也没有“商品已下架”。

## 4. 页面差异

| 观察项 | offline | active | 判断价值 |
|---|---|---|---|
| HTTP | 200 | 200 | 不能判断 |
| 最终 URL | 未改变 | 未改变 | 不能判断 |
| existing verification | false | false | 可排除当前已知 verification 页，但不是 offline 信号 |
| expected offerId 普通字符串 | 存在 | 存在 | 不能判断 |
| 结构化 `"offerId"` | 缺失 | 存在 | 只能作为辅助差异，不能单独判 offline |
| `h3.mod-detail-offline-title` 可见 | 3/3 | 0/3 | 当前样本中最强信号 |
| 精确文案“商品已下架” | 3/3 | 0/3 | 当前样本中最强信号 |
| `skuInfoMap` | 缺失 | 存在 | 辅助差异，不能单独判 offline |
| `skuId/canBookCount/discountPrice` | 仍存在 | 存在 | 不能判断；offline 页也会残留这些字段 |
| 标题 | document.title 保留商品标题 | 保留商品标题 | 不能判断 |
| 价格、SKU 正常解析 | 失败 | 成功 | 只能说明无法解析，不能直接等于 offline |

## 5. 重复验证

| 样本组 | 样本数 | 轮数 | `mod-detail-offline-title` + “商品已下架” | active 商品 parser 成功 | verification |
|---|---:|---:|---:|---:|---:|
| offline | 3 | 2 | 6/6 | 不适用 | 0/6 |
| active | 3 | 2 | 0/6 | 6/6 | 0/6 |

重复访问中，3 条 offline 的最终 URL、HTTP 200、正文核心文案、可见 DOM class 和 parser 的 `missing or invalid offer_id` 结果均稳定。

## 6. verification 与 offline 的区别

现有 verification 判断来自 URL marker、精确 title 和 `#nc_1_wrapper` 等已知结构。本轮 6 条页面都没有触发现有 verification 判断。

当前观察到的 offline 页面具有以下特征：

- 仍在 `detail.1688.com`；
- HTTP 200；
- 页面访问检查通过；
- 不属于登录页或 verification 页；
- 页面显示明确的商品下架文案和专用 DOM class；
- 商品结构化入口被移除，现有 parser 找不到 `offerId`。

因此：verification_required 应优先于商品页内容判断；验证页、登录页、网络异常、超时和页面解析异常都不能改判为 offline。

## 7. 可用于正式判断的信号

### 当前可作为候选强信号

在完成 verification/login/域名/导航异常排除后，同时满足以下条件，可作为 `confirmed offline` 候选：

1. 页面上存在可见 `h3.mod-detail-offline-title`；
2. 该元素的规范化文本精确为“商品已下架”；
3. 页面正文存在“查看该店铺其他上架商品”或同等下架页引导文案；
4. 当前 URL 仍为目标 1688 商品页，且没有 verification/login 信号。

其中第 1、2 项是本轮最强证据；第 3 项是同页的辅助确认，不应单独使用。

### 可以用于 active 的组合信号

只有在页面未触发 verification/login/访问异常，并且：

- 现有 parser 成功；
- 解析出的 offerId 等于 expected offerId；
- 标题、店铺、价格或 SKU 等正常商品字段至少有当前 parser 所需的核心字段；

才可将本次页面采集结果视为 `active` 候选。正常商品字段不是“只要存在就一定 active”的绝对证明，但比缺失字段更有价值。

## 8. 绝对不能单独用于判断的信号

- expected offerId 不存在；
- expected offerId 以普通字符串出现在 HTML 中；
- HTTP 200、HTTP 异常或状态码本身；
- 最终 URL 是否改变；
- 页面字段缺失；
- `offerId`、`subject`、`companyName`、`skuInfoMap` 等结构化字段缺失；
- 标题、价格、SKU、stock 或主图缺失；
- `skuId`、`canBookCount`、`discountPrice` 存在或缺失；offline 页本轮仍保留其中一部分；
- 现有 parser 报错或 offerId mismatch；
- 超时、网络异常、页面加载异常、浏览器异常；
- 登录失效；
- verification / 风控页；
- 页面解析失败。

这些信号都应进入 `unknown` 或 `verification_required`，不能为了得到结论而强行归为 offline。

## 9. 推荐判定规则

推荐正式 Spec 采用优先级，而不是互斥的单字段猜测：

```text
1. 已知 verification URL/title/DOM 命中
   -> verification_required

2. 登录页、非 1688 最终域名、导航异常、超时、网络/浏览器异常
   -> unknown

3. 可见 .mod-detail-offline-title 的规范化文本为“商品已下架”，
   且同页存在下架引导文案
   -> confirmed offline

4. 页面通过访问检查，parser 成功，actual offerId == expected offerId，
   且商品核心字段可用
   -> active

5. 其余情况
   -> unknown
```

这只是本轮研究得出的候选规则，尚未接入任何正式代码或状态更新。

## 10. 是否足以进入正式 Spec

结论：

- 足以进入正式 Spec 的“候选信号和优先级规则”阶段；
- 不足以直接进入正式实现、修改 `Competitor.status` 或生成 `product_offline/product_online`；
- 当前证据只覆盖一种 offline 页面模板，不能证明所有下架、删除、失效、店铺关闭或其他商品不可售页面都使用同一文案和 DOM。

## 11. 还需要的样本与验证

正式实现前建议补充：

1. 至少 5 条、最好 10 条以上 offline 样本，覆盖不同店铺、类目、商品模板和下架时间；
2. 至少 5 条以上 active 样本，覆盖不同店铺和页面模板，继续确认 false positive 为 0；
3. 其他可能的下架页类型：商品删除、链接失效、店铺关闭、区域不可售、库存售罄但商品仍在售；分别记录是否应归 offline 或 unknown；
4. 在不同日期重复访问，确认 class 和文案不是短期模板；
5. 至少收集一组真实 verification 页，确认 verification 判断优先级不会被 offline 规则误判；
6. 在正式 Spec 中明确 selector/文案变更时的回退行为：无法确认就返回 `unknown`，不猜测。

## 12. 本轮边界核对

- 未修改 `Competitor.status`。
- 未新增 `ChangeEvent`。
- 未修改正式 collector、parser、API、Frontend、migration 或 Dashboard。
- 未执行 Git commit。
- 未执行 push。

## 14. 本轮 Verification 时序 POC（2026-09-22）

### 14.1 测量对象与方法

- 页面：稳定进入验证的 `https://detail.1688.com/offer/1080864798243.html`。
- headed Chrome、项目 `.browser-profile`、`headless=False`。
- 5 次独立导航；每次 `page.goto(..., wait_until="domcontentloaded")` 返回后，在 0/100/200/300/500/800/1000ms 目标点读取状态。
- 记录 `#nc_1_wrapper` 是否存在、是否可见、existing verification 判断、已知 URL/title 信号和 offline selector。
- 本测量不点击、不拖动、不自动处理 CAPTCHA。

### 14.2 统计结果

| 导航完成后的目标时间 | `#nc_1_wrapper` 存在 | `#nc_1_wrapper` 可见 | existing verification 命中 | offline selector 可见 |
|---:|---:|---:|---:|---:|
| 0ms | 0/5 | 0/5 | 0/5 | 0/5 |
| 100ms | 4/5 | 3/5 | 3/5 | 0/5 |
| 200ms | 4/5 | 4/5 | 4/5 | 0/5 |
| 300ms | 5/5 | 5/5 | 5/5 | 0/5 |
| 500ms | 5/5 | 5/5 | 5/5 | 0/5 |
| 800ms | 5/5 | 5/5 | 5/5 | 0/5 |
| 1000ms | 5/5 | 5/5 | 5/5 | 0/5 |

验证页的其他可见信号稳定为：`document.title = 验证码拦截`，正文包含“亲，请拖动下方滑块完成验证”和“通过验证以确保正常访问”。URL 没有命中现有 `captcha/verify/punish/secdev/slide` marker；因此不能只依赖 URL marker 或现有 exact title 集合。

### 14.3 推荐 recheck 策略

推荐的最小有限策略：

```text
首次检查
  -> 命中 verification：verification_required
  -> 未命中：等待约 300ms
  -> 只再检查一次
  -> 命中：verification_required
  -> 仍未命中：继续后续页面分类；若商品证据也不足则 unknown
```

理由：

- 0ms 立即检查稳定漏判；
- 100ms 和 200ms 仍不是 5/5 稳定；
- 300ms 已达到 5/5 存在、可见和 existing verification 命中；
- 500ms 以上没有本轮收益；
- 不需要长时间固定 sleep，也不需要无限轮询。

这只是研究结论，尚未修改 collector 或正式业务逻辑。

### 14.4 当前 active 对照阻塞

本轮尝试恢复 5 条 active 有效对照时，项目 Profile 仍进入验证页。已尝试的 `competitor 1–5` 中：

- competitor 1：两轮正常解析；
- competitor 2–5：出现验证页或空白异常页，不能计入 active；
- offline selector 和“商品已下架”文本均未在这些验证/异常页面命中。

随后对历史成功记录 `competitor 6–11` 做了各 1 次低频尝试，仍受到验证或空白异常影响，没有形成额外有效 active 样本。按安全边界，本轮未自动拖动 CAPTCHA；需要一次用户确认后的真实人工验证，才能继续使用同一正常登录态重新取得至少 5 条 active × 2 轮。

### 14.5 最新分类优先级建议

在 verification recheck 结论确认后，推荐优先级为：

```text
1. verification_required
2. confirmed offline
3. normal active
4. unknown
```

verification 必须先于 offline：验证页即使 HTTP 200、缺少 expected offerId 或 parser 失败，也不能进入 offline；只有在 verification/login/导航异常排除后，才检查可见 offline selector 和精确文案。

### 14.6 本轮冻结状态

本轮 verification 时序已得到稳定的 300ms 单次 recheck 候选，但 active 有效对照尚未完成，正式 Spec 暂不冻结。冻结前仍缺：

- 至少 5 条当前正常 active 商品；
- 每条 2 轮，共 10/10 有效解析；
- active 与 verification 均保持 offline selector/text 误命中为 0；
- 人工验证后确认登录态恢复，不把 verification/空白页计为 active。

## 15. 人工验证失败记录

用户在 headed Chrome 中进行了一次真实人工滑块操作，页面显示：

```text
亲，请拖动下方滑块完成验证
验证失败，请点击框体重试（error:e3xMEn）
```

该结果只证明本次 verification challenge 没有完成，不证明商品下架、商品在售或登录态恢复。它必须保持为 `verification_required`/未完成验证证据，不能计入 active，也不能计入 offline。

本次没有自动重试、没有自动拖动、没有继续访问更多商品；临时 headed 会话已停止。有效 active 仍不足 5 条，正式 Spec 不能冻结。

## 16. Verification 单次 reload 恢复 POC（2026-09-22）

### 16.1 测试边界

- 商品：`competitor 1`，offerId `1079906223307`；历史上有成功采集记录，本轮未把验证页当作当前 active 成功证据。
- 浏览器：现有 headed Chrome、项目 `.browser-profile`。
- 每次尝试：商品页 `goto(wait_until="domcontentloaded")`，立即检查一次，未命中后等待约 300ms 再检查一次。
- 只有确认进入 verification 后才执行一次 `page.reload()`；reload 后再次立即检查和 300ms 检查。
- 每次最多一次 reload；没有连续 reload、自动拖动滑块或验证码绕过。

### 16.2 结果统计

共 5 次独立尝试：

| 指标 | 次数 |
|---|---:|
| 总尝试 | 5 |
| 按现有 detector 在 300ms 确认进入 verification | 3 |
| 初始页已有验证文案，但现有 detector 在 300ms 漏判 | 2 |
| 实际执行 reload | 3 |
| reload 后恢复 normal active | 0 |
| reload 后仍为 verification 形态 | 3 |
| reload 后最终为 blank/error/unknown | 0 |
| offline selector 误命中 | 0 |

3 次 reload 的共同表现：reload 立即读取时页面可能短暂为空；再检查后仍出现 `document.title = 验证码拦截`、正文“亲，请拖动下方滑块完成验证”，但 `#nc_1_wrapper` 有时存在而不可见，因此 existing verification detector 重新命中为 0/3。按页面事实，3/3 仍是 verification 形态；按当前 narrow detector，属于 detector 漏判而不是 active 或 offline。

另外 2 次未执行 reload 的尝试，在 300ms 时已经出现同样的 title/正文和 `#nc_1_wrapper`，但 wrapper 尚不可见；这说明“立即 + 300ms”对当前失败/未完成验证形态仍可能漏判。它们不计入 reload 结果，也不计入 active。

### 16.3 结论

1. 单次 reload 恢复 active：`0/3`。
2. 单次 reload 后仍为 verification 形态：`3/3`。
3. 单次 reload 没有证明任何恢复收益；不值得加入正式采集器的自动刷新恢复策略。
4. 正式采集遇到 verification 时，应优先进入 `verification_required` 并等待人工处理；人工验证未成功前不应通过 reload 反复尝试。
5. verification 判断应优先于 offline；即使页面 HTTP 200、parser 失败、expected offerId 不存在或 reload 短暂空白，也不能判为 offline。

### 16.4 当前 active 对照状态

当前 active 对照仍被 verification 阻塞：本轮没有产生有效的 normal active 结果，不能满足 5 条商品 × 2 轮的 active 验收条件。此前的 9 条 offline `18/18` 证据仍保留；本轮也没有发现 offline selector/text 误命中。

因此，当前 POC 仍不足以冻结正式 Spec，原因是有效 active 对照和稳定 verification 分类尚未同时完成。推荐最终分类顺序保持：

```text
verification_required
-> confirmed offline
-> normal active
-> unknown

## 17. Verification detector 漏判原因 POC（2026-09-22）

### 17.1 复现范围

- 页面：历史上正常在售、当前容易触发验证的 offerId `1079906223307`。
- headed Chrome、项目 `.browser-profile`，未执行 reload、未拖动滑块。
- 5 次独立导航；每次在 0/300/500/800/1000ms 只读检查。
- iframe URL 只保留 origin + path，去掉 query；没有保存 Cookie、Token、headers 或完整 HTML。

### 17.2 漏判根因

这两类表现不是两个稳定的 verification 页面，而是同一 `baxia-punish` 页面生命周期的两个阶段：

1. loading 阶段：`document.title` 可能已是“验证码拦截”，可见正文已经包含“请拖动下方滑块完成验证”和“通过验证以确保正常访问”，但 `#nc_1_wrapper` 尚不存在或尚不可见。
2. interactive 阶段：`#nc_1_wrapper` 出现并可见，内部出现“请按住滑块，拖动到最右边”，existing detector 才稳定命中。

现有 detector 漏判的具体原因：

- final URL 没有 `captcha/verify/punish/secdev/slide` marker；
- 标题是“验证码拦截”，不等于当前 exact title 集合中的“验证码”；
- detector 只依赖 `#nc_1_wrapper` 的存在和可见性；
- loading 阶段 `#nc_1_wrapper` 的出现晚于外层 verification 容器和明确文案。

### 17.3 DOM / URL / title / timing 证据

稳定观察到的外层结构：

```text
<PUNISH-COMPONENT>
<div id="baxia-punish" class="baxia-punish captcha pc">
  <div class="captcha-tips">亲，请拖动下方滑块完成验证 ...</div>
</div>
```

后续滑块结构：

```text
#nocaptcha.nc-container
#nc_1_nocaptcha.nc_1_nocaptcha
#nc_1_wrapper.nc_wrapper
#nc_1__scale_text.scale_text.slidetounlock
```

观察结论：

- 0ms：页面可能仍为 `interactive` 或空 loading，不能只看 `#nc_1_wrapper`；
- 300ms：`#baxia-punish`、`.captcha-tips` 和明确验证文案在 5/5 重复中稳定出现；`#nc_1_wrapper` 仍可能处于不可见/未完成初始化状态；
- 500ms、800ms、1000ms：`#baxia-punish`、`.captcha-tips`、标题和验证文案继续稳定出现，`#nc_1_wrapper` 通常进入可见交互阶段；
- URL marker：5 次重复的各时间点均未提供可依赖的 URL marker；
- iframe：未发现稳定的验证 iframe；偶发的 `html2canvas-container` 是临时辅助结构，不作为 verification signal；
- offline selector：所有 verification 观察点均为 0。

因此没有发现第二种独立 verification 页面形态；发现的是同一页面的外层 challenge loading 与滑块交互两个阶段。

### 17.4 推荐 verification detector

推荐的研究规则为：

```text
verification_required =
    known verification URL marker
    OR visible #nc_1_wrapper
    OR (
        visible #baxia-punish
        AND visible #baxia-punish .captcha-tips
        AND normalized visible text contains
            “请拖动下方滑块完成验证”
            OR “通过验证以确保正常访问”
    )
```

信号含义与可见性要求：

- known URL marker：只接受已有明确 challenge marker；作为高优先级信号，不由商品字段推断；
- `#nc_1_wrapper`：要求存在且可见，表示滑块交互层已准备好；
- `#baxia-punish` + `.captcha-tips` + 精确验证文案：两个元素都要求可见，用于覆盖 loading 阶段；这是本轮补充的主要强信号；
- 标题“验证码拦截”：只作为辅助证据，不单独判定；标题 exact 集合应把它作为已知变体记录；
- 空白、HTTP 200、parser failure、expected offerId 缺失和商品字段缺失都不是 verification signal。

推荐 timing：保持“立即检查 + 约 300ms 单次 recheck”，不提高到 500ms 作为必需等待，也不做轮询。300ms 时外层容器和文案已在本轮 5/5 出现；如果两次检查都没有强信号，则进入 unknown，而不是继续等待或猜测。

### 17.5 回归结果与剩余阻塞

verification 回归：

- 5 次独立 verification 页面观察；
- 新的外层容器 + 文案候选信号在 300ms：5/5；
- `#nc_1_wrapper` 在 300ms：不稳定，不能继续作为唯一 signal；
- offline selector 误命中：0/5 × 5 个时间点；
- URL marker 命中：0，说明 URL marker 不能覆盖该变体。

offline 负向回归：

- 本轮抽取 offline `competitor 12/15/18` 各 1 条；
- 由于当前 Profile 仍处于风控状态，3 条访问均返回同一 verification 页面，而不是 offline 页面；
- 因此本轮有效 offline 负向样本为 0，不能用这 3 次证明新 `#baxia-punish` signal 对 offline 的 false positive 为 0；
- 既有 offline `18/18` 结果仍证明原 offline selector/text 稳定，但当时尚未采集 `#baxia-punish` 这一新 signal 的专门负向字段。

结论：verification 漏判根因已经明确，推荐 signal 已找到且 300ms 可覆盖本轮 5/5；但 offline 负向回归和 active 对照仍受 Profile 风控阻塞。正式 Spec 仍不能冻结，下一次应在人工验证成功、Profile 恢复后只补做 3 条 offline 新 signal 回归和必要的 active 检查，不再扩大采样。
```

## 13. 扩展 POC：9 条 offline 与 active 对照

### 13.1 执行方式

- 日期：2026-09-22。
- offline：数据库中的 `competitor 12–20`，共 9 条；用户确认它们来自 3 家店铺、每家 3 条。当前数据库中的 `shop_name` 尚未填写，因此本文不猜测具体店铺与样本的映射。
- active 候选：`competitor 1–5`，这些记录此前均有成功采集历史。
- 第一轮：`page.goto(..., wait_until="domcontentloaded")`。
- 第二轮：同一页面执行 `page.reload(wait_until="domcontentloaded")`。
- selector、可见性和标准化文本均在导航方法返回后立即读取，没有额外等待；这与当前 collector 的等待策略一致。
- 补充尝试了 active 历史成功记录 `competitor 6–11` 各 1 轮；它们同样未形成当前正常 active 对照，结果只用于确认风控范围，不计入 active 主统计。

### 13.2 offline 明细

| competitor | offerId | document.title | goto 首屏 | reload 首屏 | 页面形态 |
|---:|---|---|---|---|---|
| 12 | `1081809347336` | 暖手宝定制厂家企业礼品LOGO定制磁吸充电暖手宝节日礼赠OEM批发-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 13 | `1081379064852` | 手持小风扇大风力便捷随身usb可充电静音电风扇迷你新款家用户外-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 14 | `1063735865360` | 锐塔克自拍杆2026新款双机位落地三脚架相机通用旅游便携拍照支架-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 15 | `1085831044696` | 2026新款跨境爆款x6火焰暖手宝炭火1w毫安大容量氛围灯暖宝宝-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 16 | `1025536911911` | 新款山眠系列usb充电加湿器家用大雾量空气净化器迷你加湿器批发-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 17 | `1013905629441` | 新款迷你高速小风扇便携手持口袋风扇充电大风力小型高速小风炮-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 18 | `1086353912269` | 小南瓜迷你养生杯 一人食多功能电煮杯便携烧水杯办公室电炖热奶-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 19 | `1061899322819` | 小南瓜电煮锅宿舍学生家用多功能蒸煮一体电炒火锅泡面【R1】-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |
| 20 | `1062909581414` | 新款桌面高速摇头风扇usb带摇控100档涡力旋钮调节循环小风扇-阿里巴巴 | 命中 | 命中 | 同一 offline 形态 |

18 次访问全部观察到：

```text
h3.mod-detail-offline-title（可见）
标准化文本：商品已下架
正文：商品已下架 / 查看该店铺其他上架商品 / 查看其他商品
```

18 次均为 HTTP 200、最终 URL 未改变、现有页面未判为登录页；现有 parser 均报 `missing or invalid offer_id`。这些 HTTP、URL 和 parser 结果仅作页面记录，未被单独用于 offline 判断。

### 13.3 统计

offline：

- 9 条 × 2 轮 = 18 次；
- selector 可见命中：18/18；
- 标准化文本“商品已下架”命中：18/18；
- selector/text 不一致：0/18；
- 观察到的第二种 offline 页面：0；
- verification 判断命中：0/18；
- reload 后仍命中：9/9。

active 主对照候选：

- 5 条 × 2 轮 = 10 次尝试；
- 当前正常 active 采集：2/10，仅 competitor 1 的 goto/reload 两次；
- selector 误命中：0/10；
- 文本误命中：0/10；
- 明确出现验证页正文“亲，请拖动下方滑块完成验证”：6/10；
- 其余为空白/未形成正常商品页：2/10；
- 5 条有效当前 active 对照：未满足。

补充访问 competitor 6–11 各 1 轮：没有命中 offline selector；其中多条出现同一验证页，另有空白异常页，未计为 active 样本。

### 13.4 verification 页面与误命中

本轮实际观察到的验证页：

```text
document.title：验证码拦截
正文：亲，请拖动下方滑块完成验证 / 通过验证以确保正常访问
DOM：#nc_1_wrapper 可见
offline selector：不存在
```

在单页时序采样中：

- DOMContentLoaded 立即读取时，`#nc_1_wrapper` 已存在且可见，但 existing verification 判断可能仍为 false；
- 约 250ms 后，existing verification 判断稳定为 true；
- 0ms、250ms、750ms、1500ms、3000ms 采样中，offline selector 始终为 0。

因此：

- verification 页面本轮没有误命中 offline selector，离线候选的 selector false positive 为 0；
- 但 current wait strategy 下，verification 判断本身存在时序漏检；title“验证码拦截”也不是当前 exact verification title 集合中的直接值；
- existing verification 未命中、parser 失败或页面字段缺失，都不能转为 active，更不能转为 offline；
- 正式规则应先完成稳定的 verification/login/导航状态确认，未确认时返回 `verification_required` 或 `unknown`，不能继续用商品页字段猜测。

### 13.5 false positive / false negative

- offline selector false positive：0/10 active 主对照尝试，0/10 已观察 verification/异常尝试；
- offline selector false negative：0/18 offline 访问；本轮没有发现不符合该 selector 的用户确认 offline 商品；
- active 误判为 offline：0；
- verification 被 existing detector 漏判：有，至少在 DOMContentLoaded 立即检查的多次访问中出现；这不是 offline false positive，但会造成 verification 与 unknown 的边界不稳定；
- active 证据缺口：8/10 active 主对照尝试没有形成正常商品页，因此不能把它们算作 active 的有效 negative samples。

### 13.6 本轮冻结结论

本轮不能冻结正式 Spec，理由不是 offline selector 失效，而是验收条件没有全部满足：

1. 9 条 offline 已全部稳定命中，且没有发现第二种 offline 页面；
2. offline selector 在 active/verification 页面上没有误命中；
3. 但没有得到至少 5 条当前正常可采集的 active 对照；
4. 真实 verification 页暴露了当前 collection wait strategy 下的识别时序问题。

候选规则已经足够强，可以作为正式 Spec 的研究输入；正式冻结前需要用户手动完成一次验证并降低访问频率，重新取得至少 5 条当前 active、每条 2 轮的有效对照，并明确 verification 页面在首屏时序中的分类行为。
