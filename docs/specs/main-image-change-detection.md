# 1688 竞品主图变化检测 `main_image_changed` Feature Spec

> 本轮仅产出 Spec，不实现业务代码、不创建 migration、不修改现有业务文档、不 commit、不 push。

## Problem Statement

系统已经在每次成功采集时保存 `ProductSnapshot.main_image_url`，并使用相邻快照检测价格、库存、SKU 和标题变化，但尚不能识别竞品是否真正更换了商品主图。

本 Feature 只比较已经由 parser/service 层标准化并最终持久化的 `ProductSnapshot.main_image_url`。主图是 optional collection data，单次采集缺失不能被解释为主图被删除或新增。

## Solution

为现有 `ChangeEvent` 增加 `main_image_changed` 类型。每次成功采集在保存新快照前，沿用现有基线选择规则，比较同一竞品最近一条旧 `ProductSnapshot` 与本次标准化后的当前事实；只有旧、新主图 URL 都是非空合法 normalized URL 且不相同时，才保存一条主图变化事件。

第一次采集只建立 baseline。历史快照不回填历史事件；上线后的下一次成功采集只与相邻上一条快照比较。

## User Stories

1. 作为竞品监控用户，我希望知道竞品是否真正更换了主图，以便及时发现商品展示变化。
2. 作为竞品监控用户，我希望第一次采集只建立 baseline，以免初始主图被误报为变化。
3. 作为竞品监控用户，我希望相同 URL 的重复采集不产生事件，以免列表和详情出现重复提醒。
4. 作为竞品监控用户，我希望 URL A 变为 URL B 时能看到旧 URL、新 URL 和检测时间，以便追溯事实。
5. 作为竞品监控用户，我希望 `None → URL` 不被报告为新增主图，因为旧数据可能只是没有采到主图。
6. 作为竞品监控用户，我希望 `URL → None` 不被报告为删除主图，因为一次采集缺失可能是 optional collection data 的暂时缺失。
7. 作为竞品监控用户，我希望图库副图增删或顺序变化不触发主图变化，以免把 gallery 变化混入本 Feature。
8. 作为竞品监控用户，我希望 Detail 的“最近变化”显示“主图发生变化”和时间，以便快速理解事件。
9. 作为竞品监控用户，我希望 Dashboard 今日变化仍一条竞品一行，并显示“主图变化” badge。
10. 作为竞品监控用户，我希望主图变化不会改变价格、库存、SKU、标题已有语义或优先级关系。
11. 作为维护者，我希望主图事件沿用现有 `ChangeEvent`，以便复用现有事务、详情查询和 Dashboard 聚合。
12. 作为维护者，我希望失败采集、inactive 过滤、Asia/Shanghai 今日边界继续遵循现有规则。

## Implementation Decisions

### 1. 比较基线与冻结规则

- `previous` 是同一 `competitor_id` 最近一条 `ProductSnapshot`，排序继续使用 `captured_at DESC, id DESC`。
- `current` 是本次已经标准化、即将持久化的 `ProductData` / `ProductSnapshot`。
- 读取 `previous` 必须发生在创建当前快照之前，或使用等价的明确排除逻辑。
- 只比较 `main_image_url`；不读取、不比较 `image_urls`。
- 不下载图片，不计算图片 hash/perceptual hash，不比较 CDN 内容，不做 jpg/webp 等价转换。
- parser/service 已负责 URL normalization；检测逻辑直接比较最终持久化值，不再次调用 normalizer 或转换 URL。
- 非空合法 normalized URL 以现有 normalization contract 为准；不合法或空值按不可比较处理，不生成事件。

| previous | current | 结果 |
| --- | --- | --- |
| 不存在 | URL A | 只建立 baseline，不生成事件 |
| URL A | URL A | 不生成事件 |
| URL A | URL B，A/B 均为非空合法 normalized URL 且 A != B | 生成 `main_image_changed` |
| `NULL` | URL A | 不生成事件 |
| URL A | `NULL` | 不生成事件 |
| `NULL` | `NULL` | 不生成事件 |

### 2. ChangeEvent contract

复用现有 `ChangeEvent`，不新造事件模型、不新增 payload 结构、不新增表或字段。

`main_image_changed` 的字段约定：

| 字段 | 值 |
| --- | --- |
| `competitor_id` | 当前竞品 ID |
| `snapshot_id` | 本次新建的当前 `ProductSnapshot.id`，不是 previous snapshot |
| `change_type` | `main_image_changed` |
| `entity_key` | `NULL`，主图是商品级变化 |
| `old_value` | previous `main_image_url`，原样保存最终 normalized URL |
| `new_value` | current `main_image_url`，原样保存最终 normalized URL |
| `detected_at` | 沿用现有事件检测时间 |

URL 不保存为完整 Snapshot JSON、HTML、原始 1688 数据、Cookie、Token 或请求头。

快照、SKU 快照、事件、Competitor 当前值和成功 `CollectionRun` 继续在现有成功事务中提交。事件写入失败时继续回滚本次快照和当前竞品更新，并将采集运行标记为 `collection_save_failed`。

### 3. 重复采集与事件去重

不增加唯一约束、去重表、队列或其他基础设施。现有相邻快照比较已经提供足够的幂等语义：

- A → B：当前保存只生成一条事件；
- 后续 B → B：previous 已是 B，不生成事件；
- A → B → C：生成两条事件，分别表达 A → B、B → C；
- 连续相同采集仍可保存新的 ProductSnapshot，但不新增 `main_image_changed`。

现有进程内采集锁和成功事务继续作为并发/保存边界；本 Feature 不引入跨进程锁或幂等基础设施。

### 4. Schema / migration

需要 migration，但仅用于扩展现有 `change_events.change_type` CHECK constraint，允许 `main_image_changed`；同时同步 ORM 模型约束。不得修改历史 migration 文件，不创建新表、新字段或新索引，不回填历史事件。

由于当前测试和部署使用 SQLite，migration 必须使用项目现有可行的 SQLite constraint 变更方式，并通过 migration/check 验证。旧数据保持不变。

### 5. Detail API / UI

复用现有 Detail API 的 `recent_changes` 和现有 ChangeEvent response 字段，不增加主图专用 API 字段。`main_image_changed` 的 `old_value`、`new_value`、`snapshot_id`、`detected_at` 由现有事件响应直接返回。

Detail「最近变化」中新增最小可用文案：

```text
主图发生变化
```

同时显示现有事件时间。第一版不要求新增图片对比组件、不要求在事件行内加载旧图/新图；旧 URL 和新 URL 作为事件事实保留在 API payload 中即可。现有 `latest_price_change` 仍只表达价格事件，不改成“任意最近变化”。

Detail 对 inactive competitor 继续可查看其历史事件；inactive 只影响现有监控/采集和 Dashboard 过滤，不删除历史事件。

### 6. Dashboard 今日变化

继续使用现有 `GET /api/dashboard/today` 和竞品级聚合：同一个 active competitor 当天无论有多少事件，仍只返回一行；`change_count` 逐条统计真实 ChangeEvent，`change_types` 保留 distinct 原始类型，`latest_change_at` 继续取所有事件的最新时间。

`main_image_changed` 参与：

- `change_types`；
- “主图变化” badge；
- `primary_change` 候选；
- `change_events` 总事件数和 `changed_competitors` 现有口径。

不新增 `main_image_changed_competitors` KPI 字段；现有 price/stock/SKU 类型统计字段保持原有语义，主图变化不被塞入其中。

推荐 primary priority（从高到低）：

1. `price_increase` / `price_decrease`
2. `stock_changed`
3. `sku_added` / `sku_removed`
4. `main_image_changed`
5. `title_changed`

理由：价格和库存直接影响交易，SKU 变化影响可购买规格；主图变化具有明显的商品展示和合规/运营价值，但通常不如交易事实紧急；标题变化保留现有最低优先级。该顺序保留现有 price > stock > SKU > title 的相对关系，只在 SKU 与 title 之间插入主图变化。相同优先级继续按 `detected_at DESC, id DESC` 选择最近事件。

当主图事件成为 primary change 时：

- `primary_change.change_type = "main_image_changed"`；
- `old_value/new_value` 为前后 normalized URL；
- 变化摘要显示“主图发生变化”；
- 变化幅度显示 `—`，不计算百分比。

Dashboard 仍只纳入 `Competitor.is_active = true` 的竞品；不改变现有当前竞品字段、竞品组、排序、空态或详情入口。

### 7. 7 天趋势与 KPI

本 Feature 暂不增加 `trend_7d` 的 `main_image_changes` 字段或图表系列，也不新增“主图变化” KPI 卡。

理由：当前 Dashboard 图表已经是紧凑的价格、库存、SKU、异常采集多系列视图；主图变化的首要消费场景是今日变化列表和 Detail 事件历史。新增趋势系列会同时扩大 API contract、图例、tooltip、前端图表和测试，而当前没有足够产品证据证明需要长期观察主图变化频率。

因此现有 7 天趋势字段和系列保持不变；主图事件仍属于真实 ChangeEvent，可在 Detail 和今日变化列表中查询。若后续需要分析主图变更频率，应另立 Feature 决定是否新增趋势字段及其展示语义。

### 8. 历史、失败与边界

- 不回填历史 `main_image_changed`。
- 旧 snapshot `main_image_url = NULL` 按冻结的 `NULL` 语义处理。
- parser、登录、验证、网络、超时、解析或保存失败不进入变化检测，不生成主图事件。
- Dashboard 今日范围继续使用 `Asia/Shanghai` 业务日转换后的 UTC 半开区间 `[start_utc, end_utc)`：开始边界包含，结束边界不包含。
- Detail 的历史事件查询不按 active 过滤；Dashboard 今日变化、今日统计和 7 天 active 事件趋势继续沿用现有 inactive 过滤规则。

## Testing Decisions

测试外部行为和数据契约，不测试 URL 下载、图片内容或具体内部循环。优先复用现有 `detect_changes` 纯函数、采集 API 测试、Detail TestClient、Dashboard TestClient、SQLite fixture 和 Frontend Vitest `renderToStaticMarkup` / formatter seam。

### 1. 变化检测矩阵

| 场景 | 预期事件 |
| --- | --- |
| first snapshot URL A | 0；只保存 baseline |
| A → A | 0 |
| A → B | 1 条 `main_image_changed` |
| `None` → A | 0 |
| A → `None` | 0 |
| `None` → `None` | 0 |
| A → B → B | 1 条；第二次 B → B 不重复 |
| A → B → C | 2 条；分别为 A → B、B → C |

主图测试值使用非空合法 normalized URL；另覆盖 `image_urls` 发生变化但 `main_image_url` 不变时不生成事件。

### 2. ChangeEvent persistence / collection transaction

- 断言事件类型、`entity_key = NULL`、`old_value`、`new_value`、`detected_at`、`competitor_id` 正确。
- 断言 `snapshot_id` 指向当前新快照，不指向 previous snapshot。
- 断言 baseline 仍保存 Snapshot/SkuSnapshot/成功 CollectionRun，但无事件。
- 断言 A → B → B 的事件总数为 1，A → B → C 为 2。
- 断言事件保存失败会回滚当前快照、SKU、Competitor 更新，且 CollectionRun 为 failed；不留下孤立事件。
- 断言 unsupported `change_type` 仍被 schema 拒绝，`main_image_changed` 被接受。

### 3. Detail API / UI

- Detail API 的 `recent_changes` 返回 `main_image_changed` 及其现有通用字段。
- 多事件按现有 `detected_at DESC, id DESC` 返回，主图事件不破坏价格事件的 `latest_price_change` 语义。
- inactive competitor 仍能查看主图历史变化。
- Frontend formatter 将 `main_image_changed` 渲染为“主图发生变化”，显示事件时间；不要求新增图片对比组件或下载图片。
- 不影响当前图库展示：图库仍来自 `latest_snapshot.image_urls`，主图变化检测不扩展为 gallery diff。

### 4. Dashboard 聚合

- active competitor 的主图事件返回一行，`change_count`、`change_types`、`latest_change_at` 和 `primary_change` 正确。
- 同一竞品同时有 price、stock、SKU、main image、title 事件时，所有 badge 都保留，primary 按推荐顺序选择 price；没有更高优先级时依次验证 stock、SKU、main image、title。
- 主图事件 primary 的摘要是“主图发生变化”，幅度是 `—`。
- 不新增主图 KPI；现有 `changed_competitors`/`change_events` 仍按竞品数/事件数统计，现有 price/stock/SKU KPI 不被改写。
- inactive competitor 即使有今日主图事件，也不进入 Dashboard item、今日事件数、类型统计或 active trend。
- 同一 Asia/Shanghai 业务日边界：`start` 事件包含，`end` 事件排除；7 天趋势字段保持现有 contract，不出现主图新系列。

### 5. Acceptance Criteria

1. 仅 `URL A → URL B` 且两者均为非空合法 normalized URL 时生成 `main_image_changed`。
2. 首次采集和任意一侧为 `NULL` 时不生成主图事件。
3. `image_urls` 的任何变化在 `main_image_url` 不变时不生成主图事件。
4. 事件沿用现有 ChangeEvent 结构，并指向当前新快照。
5. A → B 只产生一次事件，B → B 不重复，A → B → C 产生两次相邻变化事件。
6. Detail 能显示主图变化说明和时间，Dashboard 能显示主图 badge 和正确 primary。
7. inactive 过滤、Asia/Shanghai 今日边界、事务回滚和现有价格/库存/SKU/标题语义保持不变。
8. 没有历史回填、新表、新字段、图片下载、hash、通知、queue、Redis、Celery 或新 KPI 卡。

## Out of Scope

- `image_urls` gallery 增删、排序或副图变化检测；
- 图片 hash、perceptual hash、下载图片、CDN 内容比较；
- 商品下架检测；
- 自动通知；
- 新 KPI 卡；
- 新数据库表；
- 微服务、queue、Redis、Celery 或其他异步基础设施；
- Detail 复杂旧图 → 新图对比组件；
- 历史主图事件回填；
- 7 天趋势主图系列；
- 任何价格、库存、SKU、标题语义重设计。

## Further Notes

### 预计实现涉及的文件

实现阶段预计只需触及以下现有 seam 和对应测试：

- `backend/app/changes.py`：增加主图 URL 比较 draft；
- `backend/app/models.py`：扩展 `ChangeEvent` 类型约束；
- `backend/alembic/versions/<new_revision>_allow_main_image_changed.py`：更新现有 CHECK constraint；
- `backend/tests/test_changes.py`、`backend/tests/test_change_events.py`、`backend/tests/test_collection_api.py`：纯规则、schema 和持久化/事务矩阵；
- `backend/app/competitor_detail.py`、`backend/tests/test_competitor_detail.py`：确认通用事件 response 和 Detail 行为，无需新 API 模型；
- `backend/app/dashboard.py`、`backend/tests/test_dashboard.py`：新增类型聚合、primary priority、badge 所需字段和边界覆盖；
- `frontend/src/App.tsx`、`frontend/src/App.css`、`frontend/src/App.test.tsx`：增加主图文案、badge 样式和渲染测试；
- 实现完成后按项目既有约定同步 `docs/data-model.md`、`docs/architecture.md` 等长期文档；本轮不修改这些文档。

### 需要确认的产品决策

本 Spec 已按用户提供的冻结语义落定，没有阻塞实现的产品决策。唯一保留为未来独立决策的是：是否在后续另立 Feature 将主图变化加入 7 天趋势；本轮推荐不接入。
