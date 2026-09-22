# Architecture

## 1. 架构目标

当前 V1 只服务一个人、本地运行、每天采集一次 1688 竞品数据。

优先级：

1. 简单；
2. 稳定；
3. 低维护；
4. 容易让 AI 理解和修改；
5. 出问题容易定位和回滚。

因此 V1 采用模块化单体，不使用微服务、消息队列或复杂任务系统。

## 2. 技术栈

### Frontend

- React
- TypeScript
- Vite
- Vitest

### Backend

- Python
- FastAPI
- SQLAlchemy
- Alembic
- pytest

### Database

- SQLite

### Collection

- Playwright
- 本机 Chrome
- 独立浏览器 Profile 保存 1688 登录状态

## 3. 总体结构

```text
React Web
   ↓ HTTP API
FastAPI
   ↓
Application / Domain Services
   ↓
SQLAlchemy
   ↓
SQLite

FastAPI
   ↓
Collector Module
   ↓
Playwright + 1688
```

## 4. 模块边界

V1 建议拆成以下业务模块：

```text
competitors
groups
collection
snapshots
changes
dashboard
```

职责：

- competitors：竞品商品本身；
- groups：竞品分组；
- collection：采集 1688 数据；
- snapshots：保存每天采集到的事实数据；
- changes：比较前后快照并生成变化记录；
- dashboard：首页查询和聚合；今日变化在 Backend 按 active Competitor 聚合 ChangeEvent，Frontend 只展示聚合后的 item；
- shared：少量真正跨模块共享的基础能力。

不要提前创建大量抽象层。

## 5. 后端分层

后端保持简单：

```text
API Router
   ↓
Service
   ↓
Repository / Database
```

规则：

- Router 只处理 HTTP 输入输出，不写业务逻辑；
- Service 负责业务规则；
- 数据访问集中在数据库层；
- Playwright 采集逻辑独立于 API 和数据库模型；
- 变化判断逻辑不能写在 React 组件中。

如果一个功能不需要某一层，不要为了“架构完整”强行新增文件。

## 6. 前端边界

React 负责：

- 页面展示；
- 用户输入；
- 调用后端 API；
- Loading / Empty / Error / Normal 状态；
- 简单的界面交互。

React 不负责：

- 1688 页面采集；
- 业务规则判断；
- 数据持久化；
- 历史趋势计算的核心逻辑；
- 直接访问 SQLite。

## 7. 采集架构

采集入口统一通过 Collector Module。

优先级：

1. HTML / 内嵌 JSON；
2. Network Response / XHR；
3. DOM 文本兜底。

Playwright 主要负责：

- 维持 1688 登录环境；
- 打开商品页；
- 获取 HTML；
- 捕获必要的网络响应。

不要把“模拟人工点击页面”作为主要采集方式。

官方采购助手接口属于补充数据源，不能成为系统唯一历史数据来源。

## 8. 数据原则

长期趋势以本系统每天保存的快照为准。

外部数据进入系统后，需要转换成内部统一模型。

当前真实样本已验证的映射为：`skuInfoMap[item].discountPrice → SkuData.price → SkuSnapshot.price`，表示 SKU 当前页面展示价格；`skuInfoMap[item].priceAmount` 虽然来自 SKU item，但表达整个 Offer 的起批条件，聚合后写入 `ProductData.min_order_quantity → ProductSnapshot.min_order_quantity`。只有所有 SKU 都存在相同合法值时才保存，否则为 NULL。`skuPriceScale` 只用于商品级价格或商品级价格区间，不写入 SKU price。`discountPrice` 不被描述为所有促销体系下的最终成交价。

禁止业务代码到处直接依赖：

```text
skuInfoMap
canBookCount
discountPrice
priceAmount
saleQuantityList
tradePriceList
mtop.1688...
```

这些属于外部数据结构，只允许集中在采集适配层处理。

内部统一使用项目自己的字段。

竞品详情趋势继续复用现有 `GET /api/competitors/{id}/detail?days=7|30`。Backend 使用 dashboard 的 Asia/Shanghai business-day helper，将日期范围转换为 UTC 半开区间，按 `captured_at DESC, id DESC` 选择每日最终 `ProductSnapshot`，再一次性批量读取所选快照的 `SkuSnapshot`，避免按日期逐个查询 SKU 的 N+1。`daily_trend` 同时承载每日价格和库存事实；销量不进入该 contract，仅保留前端占位。

详情 API 的 `recent_changes[].sku_name` 是展示投影，不是数据库字段。Backend 对最多 20 条近期变化批量收集 `snapshot_id` / `entity_key`，一次查询精确快照映射，再一次查询同一竞品历史 SKU 映射；名称通过 `html.unescape` 和 trim 后返回，找不到则为 `null`。Frontend 只负责显示名称、SKU ID 回退和既有变化文案。

Frontend 的 AppShell 使用固定 viewport 高度：Sidebar 自身允许滚动，`.main-content` 承担右侧主纵向滚动；Detail 历史卡和 Dashboard 今日变化表格使用 scoped 内部滚动、sticky 表头与 `overscroll-behavior-y: contain`，不增加 wheel handler 或新的状态层。

`.main-content` 是 column flex 容器时，普通直接子级卡片必须保留自然高度，否则 `.table-card` 的 `overflow: hidden` 会配合默认 flex shrink 裁掉竞品列表。列表不增加固定高度或纵向裁切；只有 Dashboard 今日变化和 Detail 三个历史卡使用明确的内部纵向滚动。

Dashboard 的 `stock_total_change` 使用固定批量查询：收集 primary stock event 的 current snapshot，批量读取相关竞品快照并按 `(captured_at, id)` 在内存确定 previous，再批量读取 current/previous 的 `SkuSnapshot` 计算 totals，避免按竞品或快照 N+1 查询。KPI、priority 和 trend_7d 不变。

## 9. 数据库原则

V1 使用 SQLite。

原因：

- 单用户；
- 本地运行；
- 数据量可控；
- 几乎零维护；
- 适合当前开发阶段。

所有 Schema 修改必须通过 Alembic migration。

禁止手工修改数据库后不留下 migration。

当未来出现明确的多用户、云部署、高并发需求时，再评估迁移 PostgreSQL。

## 10. 调度原则

当前实现使用 FastAPI lifespan 启动一个 asyncio 后台 task。Backend 启动约 30 秒后进行首次 due-check，之后每小时检查一次。

due-check 只处理 active Competitor，使用最近一条 CollectionRun.started_at 统一按 UTC 判断 24 小时窗口，并按顺序调用现有 collect_competitor()。每个竞品使用独立 Session；同步采集批次放入线程，不阻塞 API event loop。

自动采集依赖 Backend 正在运行，电脑关机时不会执行。单个采集失败继续后续竞品；如果全局 COLLECTION_LOCK 忙，则中断当前 cycle，下一次检查再尝试。Backend shutdown 时唤醒 scheduler，允许当前竞品完成后正常退出，不再启动下一个竞品。

当前不引入：

- Celery；
- Redis；
- RabbitMQ；
- Kafka；
- 分布式任务系统。

优先使用简单的本地调度方式。

只有当前方案无法满足真实需求时，才升级任务架构。

## 11. 错误隔离

单个竞品采集失败时：

- 记录失败状态；
- 保存错误信息；
- 不影响其他竞品继续采集。

禁止因为一个商品失败导致整个每日采集任务终止。

## 12. 明确禁止

V1 不引入：

- 微服务；
- Redis；
- Celery；
- Docker 作为开发前提；
- 消息队列；
- DDD 全家桶；
- Repository / Factory / Manager 等无实际必要的抽象；
- 多 Agent 编排；
- 为未来假设需求提前设计复杂架构。

## 13. 修改原则

每个开发任务：

- 只修改完成任务真正需要的文件；
- 不顺手重构；
- 不无理由升级依赖；
- Feature 与 Refactor 分开；
- 数据库变更必须 migration；
- 完成后必须检查 Git Diff；
- 优先复用现有模块，而不是创建新体系。

## 14. 架构升级条件

只有出现真实问题时才升级架构。

例如：

- SQLite 明确成为瓶颈；
- 本地调度无法可靠运行；
- 多用户成为真实需求；
- 数据规模明显增长；
- 单体模块边界已经无法维护。

在这些问题出现之前，保持当前简单架构。
