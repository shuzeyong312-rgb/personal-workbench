# 单个竞品立即采集 Spec

## 1. Goal

为已有竞品列表增加单个竞品手动立即采集能力：用户点击“立即采集”后，系统复用本地 1688 登录态，完成一次真实采集，安全保存当前商品数据、ProductSnapshot、SkuSnapshot 和 CollectionRun，并刷新列表。

本 Feature 不实现定时采集、批量采集、变化检测或 Dashboard。

## 2. User Flow

1. 用户进入“竞品监控 / 竞品列表”。
2. 用户点击某个竞品的“立即采集”。
3. 当前行显示“采集中...”。
4. 任意竞品采集中时，所有其他“立即采集”按钮 disabled；列表仍可浏览。
5. 前端只在没有采集任务时发起请求，不主动发起已知会失败的第二采集请求。
6. 后端使用该竞品保存的 canonical 1688 URL 进行采集。
7. 成功后返回结果，前端重新请求 GET /api/competitors 并显示成功 Toast。
8. 失败后显示可读错误、保留上一次有效数据，并允许重试。
9. 当前 MVP 不判断商品是否下架，正常商品可以保存 product_status = unknown；下架判定保留为后续能力。

第一版全局一次只允许一个真实采集任务。后端进程内全局采集锁是真正并发控制，409 collection_in_progress 是并发安全兜底。

## 3. Collection Flow

1. 校验 competitor_id 并查询 Competitor。
2. 不存在时返回 competitor_not_found。
3. 获取进程内全局采集锁；锁不可用时返回 collection_in_progress。
4. 创建 CollectionRun，状态为 running。
5. 使用项目根目录解析出的 .browser-profile 启动 Playwright persistent context。
6. 打开 canonical 1688 URL，检查登录页、验证页和访问异常。
7. 当前 MVP 仅从 HTML / embedded JSON 提取数据；未来需要时再扩展 Network/XHR → DOM fallback。
8. 通过 collection adapter 转换为内部标准字段。
9. 校验 offer_id 与目标 Competitor 一致。
10. 校验标题、店铺名称和商品状态等最小核心数据。
11. 采集完成后关闭页面和 context。
12. 开启短数据库事务，一次性保存 ProductSnapshot、全部 SkuSnapshot、Competitor 当前字段和 CollectionRun 成功状态。
13. 提交事务，返回结果并释放全局采集锁。
14. 任意异常都必须关闭浏览器资源，并记录失败 CollectionRun。

CollectionRun.running 只表示执行状态，不承担锁职责；真正并发控制由进程内全局采集锁负责。

## 4. Collection Sources

当前实现的采集来源：

- HTML / embedded JSON

未来需要时的扩展顺序：

1. Network Response / XHR JSON；
2. DOM fallback。

Network/XHR 和 DOM fallback 不属于当前 Feature，不在本轮实现或 Acceptance Criteria 内。Playwright 当前只负责本地 Chrome、持久化登录目录、页面访问和 HTML 获取，不以模拟人工点击为主要采集方式。

已验证 POC 能力包括：offerId、商品标题、店铺名称、商品价格、skuInfoMap、SKU 属性、skuId、canBookCount、discountPrice、priceAmount 和 skuPriceScale。当前真实样本已正式确认 discountPrice 与 priceAmount 的以下字段映射。

mtop.1688.pc.plugin.od.data.query 的历史销量、累计销量、销量历史和历史价格数据本 Feature 不接入。

外部字段只允许存在于 collection adapter / parser 边界：

- skuInfoMap → 内部 SKU 集合；
- canBookCount → stock；
- discountPrice → SKU 当前页面展示价格 price；
- priceAmount → Offer / ProductSnapshot.min_order_quantity；
- skuPriceScale → 商品级价格 / 商品级价格区间，不写入 SKU price；
- mtop... → 本 Feature 不使用。

## 5. Normalized Data Contract

### 商品

    offer_id: string
    title: string
    shop_name: string
    main_image_url: string | null
    price_min: Decimal | null
    price_max: Decimal | null
    product_status: unknown | active | offline
    collection_source: html | network | mixed
    captured_at: datetime
    min_order_quantity: integer | null
    skus: list[SkuData]

### SKU

    sku_id: string
    sku_name: string
    stock: integer | null
    price: Decimal | null

规则：

- 统一商品价格同时作为 price_min 和 price_max。
- 可靠价格区间保存真实最小值和最大值。
- 缺失价格保存 null，不能保存为 0。
- `discountPrice` 只有能解析为单一、非负 Decimal 时保存为 SKU price，否则保存 null；不使用 `price` fallback，不从商品级价格或价格区间猜测。
- `priceAmount` 虽然从 SKU item 读取，但按当前真实样本验证表达整个 Offer 的起批数量；只有至少一个 SKU 且所有 SKU 都能解析为相同的大于等于 1 的正整数时，才保存为 ProductData/ProductSnapshot.min_order_quantity，否则保存 null。bool、小数、对象/list、缺失值或冲突值均为未知。
- 上述 `discountPrice` 与 `priceAmount` 映射已通过当前真实样本验证；前者表示当前 SKU 页面展示价格，不宣称是所有促销体系下的最终成交价。
- active 只表示页面明确显示商品正常可售。
- 当前 MVP 不实现 offline 判定，正常商品可以返回 unknown；未来只有明确页面证据时才允许保存 offline。
- 解析失败、登录失效、超时和结构变化不能标记为 offline。

## 6. Data Model Changes

本 Feature 正式引入 ProductSnapshot、SkuSnapshot 和 CollectionRun。

### ProductSnapshot

保存一次成功采集得到的商品级事实：

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

本次 migration 明确不创建：

    sales_30d
    total_sales
    total_orders

未来历史销量 Feature 通过独立 migration 增加，不创建未来占位 nullable 字段。

### SkuSnapshot

保存某个 ProductSnapshot 对应的 SKU 事实：

    id
    product_snapshot_id
    sku_id
    sku_name
    stock
    price

### CollectionRun

保存每次手动采集执行事实：

    id
    competitor_id
    started_at
    finished_at
    status
    error_type
    error_message

状态为 running、success、failed。running 只表示执行状态，不作为并发锁。

### Competitor

Competitor 只保存当前基础信息：

    title
    shop_name
    main_image_url
    status
    last_collected_at

价格、SKU 数量等可变化事实保存到 Snapshot，不堆入 Competitor 当前表。

本 Feature 不引入 ChangeEvent，不比较新旧 Snapshot，不生成涨价、降价、SKU 或库存变化结论。

所有 Schema 变更必须通过 Alembic migration。

## 7. API Contract

### 立即采集

    POST /api/competitors/{competitor_id}/collect

请求体为空。

成功响应为 200 OK，包含 competitor、snapshot 和 collection_run 的真实结果。snapshot 至少包含：

    id
    captured_at
    price_min
    price_max
    product_status
    collection_source
    sku_count

错误响应保持稳定结构：

    {
      "code": "collection_parse_failed",
      "message": "无法解析该商品页面，请稍后重试"
    }

错误类型：

| HTTP 状态 | code |
|---|---|
| 404 | competitor_not_found |
| 409 | collection_in_progress |
| 401 | 1688_login_required |
| 403 | 1688_verification_required |
| 422 | collection_parse_failed / offer_id_mismatch |
| 422 | collection_partial_data |
| 502 | 1688_page_unavailable |
| 504 | collection_timeout |
| 500 | collection_failed / collection_save_failed |

当前 MVP 不识别下架，因此不会主动产生 offline 结果；未来增加下架识别后，明确下架应视为成功采集，不返回失败错误。

### 竞品列表

继续使用：

    GET /api/competitors

本 Feature 只新增真实存在的数据投影：

    latest_snapshot:
      price_min
      price_max
      sku_count

latest_snapshot 可以为 null。

不新增：

- latest_change
- latest_collection_run

“最近变化”继续由前端显示“暂无变化记录”，不建立虚假 API 字段。

## 8. Persistence / Transaction Rules

外部网络采集阶段不持有数据库事务。采集和标准化完成后，使用一个短事务完成：

1. 创建 ProductSnapshot；
2. 创建全部 SkuSnapshot；
3. 更新 Competitor 的当前基础信息和 last_collected_at；
4. 将 CollectionRun 更新为 success；
5. 提交事务。

任一步骤失败时整体回滚，避免 Competitor、Snapshot 和 SKU 只保存一部分。

采集失败时单独使用短事务将 CollectionRun 更新为 failed，保存稳定错误类型和脱敏摘要，不修改上一次成功快照或 Competitor 当前数据。

## 9. Playwright Lifecycle

每次立即采集：

1. 获取进程内全局采集锁；
2. 使用项目根目录稳定解析的 .browser-profile 启动 persistent context；
3. 使用本机 Chrome channel；
4. 创建页面并访问商品 URL；
5. 获取结构化数据；
6. 关闭页面和 persistent context；
7. 释放全局采集锁。

成功、解析失败、超时和异常路径都必须关闭 context，避免浏览器进程泄漏。

.browser-profile 不得依赖 FastAPI 启动时的当前工作目录。

如果 Playwright 尚未写入 Backend 正式依赖文件，本 Feature 允许将已经选定的 Playwright 固化为正式依赖。

本 Feature 不新增与本 Feature 无关的第三方依赖，不引入 Celery、Redis、RabbitMQ、Selenium Grid、Docker Browser、云浏览器或后台任务队列。

## 10. Frontend Behavior

严格复用已有竞品列表页面和 UI 系统。

每行增加“立即采集”入口。点击后：

1. 设置全局 collectingCompetitorId；
2. 当前行显示“采集中...”；
3. 所有“立即采集”按钮 disabled；
4. 列表仍可浏览；
5. 调用立即采集 API；
6. 成功后重新请求 GET /api/competitors；
7. 清除采集状态并显示成功 Toast；
8. 失败后清除采集状态，显示错误并允许重试。

前端不得主动发起第二个已知会因全局采集规则失败的请求。后端全局锁和 409 collection_in_progress 仍保留兜底。

列表当前价格和 SKU 数量使用 latest_snapshot 中的真实值；latest_snapshot = null 或字段缺失时显示“未采集”。最近变化固定显示“暂无变化记录”。

## 11. UI States

列表级状态继续使用 Loading、Empty、Error、Normal。

采集级状态：

- Idle：显示“立即采集”；
- Collecting：当前行显示“采集中...”，所有采集按钮 disabled；
- Success：刷新列表并显示成功 Toast；
- Failure：显示错误 Toast，允许重试。

缺失值展示规则：

- 缺失标题、店铺、价格、SKU 数量或采集时间：显示“未采集”；
- 缺失主图：显示已有占位状态；
- 无变化记录：显示“暂无变化记录”；
- 不将缺失值显示为 0、正常或虚构日期。

## 12. Error Model

| code | 含义 | 是否更新 Competitor |
|---|---|---|
| competitor_not_found | 竞品不存在 | 否 |
| collection_in_progress | 已有采集正在进行 | 否 |
| 1688_login_required | 登录态失效或进入登录页 | 否 |
| 1688_verification_required | 遇到验证或风控页面 | 否 |
| 1688_page_unavailable | 商品页无法访问 | 否 |
| collection_parse_failed | 页面结构无法解析 | 否 |
| offer_id_mismatch | 页面商品与目标竞品不一致 | 否 |
| collection_timeout | 采集超时 | 否 |
| collection_partial_data | 必要字段缺失 | 否 |
| collection_failed | 未分类采集执行异常 | 否 |
| collection_save_failed | 数据库事务保存失败 | 否 |

错误信息必须可读、稳定且脱敏，不暴露 Cookie、Token、HTML、请求头或完整异常堆栈。

未分类采集执行异常固定返回 HTTP 500、code = collection_failed、message = `采集失败，请稍后重试`，并将同一脱敏摘要写入 CollectionRun.error_message。数据库事务保存失败固定使用 code = collection_save_failed，两者不能混用。

当前 MVP 不识别商品下架，正常商品仍可保存：

    CollectionRun.status = success
    ProductSnapshot.product_status = unknown
    Competitor.status = unknown

未来增加下架识别后，只有明确页面证据才允许保存 offline；解析失败、登录失败和超时不能保存 offline。

## 13. Security Rules

.browser-profile、Cookie、Token、登录状态、完整 HTML、请求头和其他敏感请求参数只保留在本地采集边界。

以上内容不得进入：

- 数据库；
- 普通日志；
- 前端响应；
- Snapshot；
- CollectionRun.error_message；
- Git。

项目应继续通过 .gitignore 排除 .browser-profile 和调试输出文件。

## 14. Testing Strategy

测试以外部行为为主，优先覆盖 parser、collection service、API、事务和前端状态。

### Parser / Adapter

Parser fixture 只能使用最小、脱敏的 HTML / embedded JSON 数据。禁止提交完整真实 1688 HTML、Cookie、Token、请求头、登录数据或浏览器 Profile。

验证 offerId、标题、店铺、主图、商品价格、SKU 名称、canBookCount → stock、缺失价格为 null、不可靠 SKU 价格为 null、必要字段缺失错误和不依赖插件历史字段。主图只读取 `gallery.fields.offerImgList[0]`，fallback 仅限 `gallery.fields.mainImage[0]` 和 `dataJson.images[0].fullPathImageURI`；不扫描 HTML 图片、不使用 DOM fallback。

### Collection Service

使用可替换 collector adapter 验证目标 URL、offerId 一致性、登录页和验证页处理、当前 unknown 处理、超时、失败数据保留、全局锁，以及 CollectionRun.running 不承担锁职责。

### Persistence

验证 ProductSnapshot、SkuSnapshot、CollectionRun 和 Competitor 成功写入；SKU 或 Competitor 保存失败时整体回滚；失败不覆盖旧快照；重复采集新增快照。

### API

验证不存在竞品、成功响应、稳定错误、latest_snapshot 三个字段、latest_snapshot = null、不返回 latest_change / latest_collection_run、失败保留旧数据和敏感信息不外泄。

### Frontend

验证任意竞品采集中时所有采集按钮 disabled、列表仍可浏览、前端不发起第二请求、成功刷新列表、失败可重试、缺失值不显示为零、最近变化不显示虚假结论。

## 15. Acceptance Criteria

1. 竞品列表每行都有“立即采集”。
2. 第一版全局同时最多一个真实采集任务。
3. 采集中当前行显示“采集中...”。
4. 任意竞品采集中时所有采集按钮 disabled。
5. 列表仍可浏览。
6. 后端进程内全局采集锁负责并发控制。
7. CollectionRun.running 只表示执行状态。
8. 后端保留 409 collection_in_progress 兜底。
9. 使用项目根目录解析的 .browser-profile。
10. Playwright context 在所有路径关闭。
11. 当前采集来源为 HTML / embedded JSON；Network/XHR → DOM fallback 为未来扩展，不属于本 Feature。
12. offerId 不一致时失败。
13. 登录失效、验证页面、解析失败和超时有稳定错误类型。
14. 解析失败不能标记 offline。
15. 当前不实现 offline 判定，正常商品可以保存 unknown；未来只有明确下架证据才允许保存 offline。
16. 采集失败不覆盖上一次成功数据。
17. ProductSnapshot、SkuSnapshot、CollectionRun 通过 migration 正式引入。
18. 不引入 ChangeEvent。
19. SKU 独立价格不可靠时为 null。
20. 缺失价格不保存为 0。
21. ProductSnapshot migration 不创建 sales_30d、total_sales、total_orders。
22. Competitor 只保存当前基础信息。
23. GET /api/competitors 只新增 latest_snapshot.price_min、price_max、sku_count。
24. latest_snapshot 可以为 null。
25. 不返回 latest_change 或 latest_collection_run。
26. Plugin 历史销量 / 历史价格不接入。
27. ProductSnapshot、全部 SkuSnapshot、Competitor 更新和 CollectionRun 成功状态在同一事务提交。
28. Cookie、Token、HTML、请求头和登录数据不进入数据库、日志、前端或 Git。
29. Parser fixture 仅使用最小脱敏数据。
30. 不新增与本 Feature 无关的第三方依赖。

## 16. Non-goals

- 定时采集；
- 批量采集；
- 不同竞品并发采集；
- Dashboard；
- ChangeEvent；
- 涨价 / 降价、销量、SKU、库存、标题或主图变化判断；
- 趋势图和 7/30 天趋势；
- Plugin 历史销量 / 历史价格接入；
- 通知、自动上架、AI 分析；
- 多平台、多用户、云端部署；
- 后台任务队列和复杂重试系统；
- 采集记录页面和竞品详情页；
- 竞品编辑、删除、停用；
- 保存原始 HTML、Cookie、Token、浏览器会话或登录数据；
- 通过商品级价格猜测 SKU 价格；
- 新增与本 Feature 无关的第三方依赖。

## 17. Confirmed

- 本 Feature 是单个竞品手动立即采集。
- 全局一次只允许一个真实采集任务。
- 任意竞品采集中时，所有“立即采集”按钮 disabled，列表仍可浏览。
- 后端进程内全局锁是真正并发控制。
- CollectionRun.running 只表示执行状态，不承担锁职责。
- ProductSnapshot、SkuSnapshot、CollectionRun 正式引入。
- ChangeEvent 不引入。
- Competitor 只保存 title、shop_name、main_image_url、status、last_collected_at 等当前基础信息。
- GET /api/competitors 只新增 latest_snapshot.price_min、price_max、sku_count。
- 不新增 latest_change 或 latest_collection_run。
- Plugin 历史销量 / 历史价格本 Feature 不接入。
- ProductSnapshot migration 不创建 sales_30d、total_sales、total_orders。
- SKU 独立价格不可靠时保存 null，缺失价格不能保存为 0。
- 当前不实现 offline 判定，正常商品可以保存 unknown；解析失败、网络失败、登录/验证失败不能标记 offline。
- 当前采集来源是 HTML / embedded JSON；Network/XHR → DOM fallback 是未来扩展能力。
- .browser-profile 基于项目根目录解析。
- Cookie、Token、HTML、请求头和登录数据不得进入数据库、日志、前端或 Git。
- Parser fixture 只能使用最小脱敏数据。
- 当前项目使用 React、TypeScript、Vite、FastAPI、SQLAlchemy 和 SQLite。
- 当前已存在 Competitor 模型、POST /api/competitors 和 GET /api/competitors。
- 当前 POC 使用 Playwright、本地 Chrome 和 .browser-profile，并已验证商品与 SKU 相关字段。

## 18. Assumptions

- 当前运行环境为 Windows 本地单用户工具。
- 进程内全局采集锁满足第一版并发控制。
- 采集请求为同步 HTTP 请求，不引入后台任务。
- 标题、店铺名称和 offerId 是成功保存所需的最小核心字段。
- 主图或商品价格缺失时可以保存 null，不伪造数据。
- 主图正式接入链路为 `gallery.fields.offerImgList[0]` → `ProductData.main_image_url` → `ProductSnapshot` / `Competitor`；主图缺失不使商品采集失败。
- SKU 没有可靠独立价格时仍可保存 SKU，但 price = null。
- 当前不实现商品下架判定，未来实现时必须基于明确页面证据。
- 失败 CollectionRun 只保存脱敏错误摘要。
- 前端成功后始终重新获取列表。
- Playwright 可以写入 Backend 正式依赖文件。
- 测试只依赖最小脱敏 fixture，不依赖真实登录会话。

## 20. 商品图库扩展

`ProductData.image_urls` 是可选的有序商品图库，只读取明确结构化的 `gallery.fields.offerImgList`。每个 URL 使用窄 normalization，非法项跳过，按 normalized 完整 URL exact 去重并保留顺序；`main_image_url` 仍严格按 index 0 及既有 fallback 判定，不能因 index 0 无效而提升 index 1。

成功事务将 `image_urls` 保存到 `ProductSnapshot.image_urls`（nullable JSON）；旧 Snapshot 保持 NULL，`Competitor` 不增加图库字段，列表 API 不返回图库。详情 API 的 `latest_snapshot.image_urls` 返回最新 Snapshot 图库，前端在详情页显示不超过大图宽度的缩略图条，点击只改变本地预览；旧 NULL 仅回退到当前 Competitor 首图，空数组显示占位。该扩展不包含 `main_image_changed`、ChangeEvent 或其他变化检测。

## 19. Unknowns

- 1688 页面长期稳定的下架判定结构。
- 主图字段在不同商品模板中的统一提取规则。
- 不同 SKU 价格字段是否始终具有稳定语义。
- 商品详情页是否始终能获得完整 skuInfoMap。
- 页面访问失败、验证码和风控页面的全部变体。
- Playwright persistent context 在目标 Chrome 环境中的最长稳定运行时间。
- 未来是否允许不同竞品并发采集。
- 未来是否接入 Plugin 历史销量和历史价格数据。
- 未来是否需要独立采集记录页面或更细粒度商品状态。
