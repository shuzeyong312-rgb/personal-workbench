# Group-first Dashboard V1

状态：正式产品 Spec；定义 Dashboard 的组级关注入口，不实现业务代码。Group Attention 的业务等级、保护规则、Reason 语义和排序以 `group-attention-priority-v1.md` 为准。

## Problem Statement

当前 Dashboard 以“今日发生变化的竞品”为主语，展示竞品级事件行；用户仍需逐行阅读并自行判断哪些我方商品组值得先看。已实现的 Group Detail 能解释组内事实，但现有 Dashboard Group Entry 只是辅助入口，没有组级 Attention 排序和原因摘要。

## Product Goal

Dashboard 以“今天哪些我方商品组最值得先看”为主语。先展示 Backend 已聚合、排序的今日变化组及有限原因摘要，再由用户进入 Group Detail 分析，必要时进入 Competitor Detail 查看具体竞品和变化证据。

Dashboard 不计算 Attention，也不代替组分析或单品证据页。

## Page Responsibility

- **Dashboard**：今天先看哪些商品组？
- **Group Detail**：这个组为什么值得看、我方和竞品差在哪？
- **Competitor Detail**：具体竞品和变化证据是什么？

## Information Architecture

页面按以下优先级组织；不冻结像素、栅格或具体卡片尺寸：

1. Header：页面身份及“添加竞品”“立即采集”操作。
2. Group-first KPI：监控商品组、今日有变化商品组、今日涉及变化竞品、异常采集。
3. 页面核心“今日需要关注的商品组”：仅显示 Backend Attention 返回的今日有变化组，保持返回顺序。
4. 辅助信息：采集运行状态与 7 天趋势。二者不抢占主列表视觉优先级。
5. 次级弱入口：无变化组数量或“查看全部商品组”；不能把无变化组伪装为关注项。

原“今日发生变化的竞品”大表不再是 Dashboard 核心区域。单竞品事件明细由 Group Detail / Competitor Detail 承接。

## KPI Semantics

| KPI | 语义 |
|---|---|
| 监控商品组 | 至少绑定一个 own product 且至少有一个 `is_active = true` 直接竞品的不同组数；按当前成员关系统计。由 Backend 返回，Frontend 不从竞品行推算。 |
| 今日有变化商品组 | 今日有有效直接竞品变化且进入 Group Attention 结果的不同组数；由 Backend 返回。 |
| 今日涉及变化竞品 | 今日 Attention 纳入计算的不同直接竞品数；由 Backend 按 `competitor_id` 去重并返回，不从事件数或页面行数推算。仅计当前属于可进入 Group-first 关注模型商品组的直接竞品；未分组商品不计。组归属范围、当前 `group_role` 与 Asia/Shanghai 今日边界沿用 Group Attention 规则。 |
| 异常采集 | 沿用现有 Dashboard 当日失败采集统计口径；不得与 Attention 失败混为一谈。 |

若当前契约不能返回前三项，Backend read contract 必须补足上述聚合字段；Frontend 不得组合 `/api/competitor-groups/summary`、`/api/dashboard/today` 或组成员数据自行拼数。采集失败 KPI 继续消费现有 Dashboard 数据。

## Attention Group List

主体标题为“今日需要关注的商品组”。列表只消费 Backend Group Attention read model：

- 按 `group-attention-priority-v1.md` 的 Attention Level 和稳定排序键展示，不在 Frontend 再排序；
- 每项展示组名、own product 简要身份、Attention Level（“重点关注 / 建议查看 / 一般变化”）、今日变化竞品数、最多 3 条 Backend Reason、最近变化时间，以及“进入组分析”；
- 不展示内部 `attention_score`；不将 ChangeEvent 条数作为变化竞品数；
- own identity 使用真实 own product 数据；缺失值显示“未绑定我方商品”或契约定义的不可用状态，不按名称猜测；
- 今日无变化的 Group 不出现在关注列表。可以弱化展示无变化组数量或“查看全部商品组”，不提供虚构的 Attention Level / Reason。

## Empty / Loading / Error States

- **加载中**：关注列表区域独立显示加载状态；采集运行状态及 7 天趋势按各自现有请求状态展示。
- **全部无变化**：明确显示“今日暂无需要关注的竞争变化”。不得回填昨日事件或将静态组作为关注项。采集状态和 7 天趋势仍可正常展示。
- **Attention 请求失败**：只将关注列表/KPI 依赖 Attention 的部分降级并提供重试；不遮蔽已成功加载的采集状态、7 天趋势及其他独立 Dashboard 内容。
- **Attention 空数据与请求失败**必须区分；失败不能伪装为零变化。
- **辅助区域失败**：按现有区域局部状态处理，不阻断 Attention 主体。
- 若现有 Dashboard 主数据请求失败，继续保留其独立错误语义；不得由 Attention 状态覆盖或清除。

## Navigation

- 点击组卡片或“进入组分析”复用现有 Group Detail 导航回调和 `openGroupDetail(groupId)` 路径。
- 不新建 Router、平行详情页或前端自行拼接组详情。
- Dashboard 不提供竞品级事件明细入口作为主列表替代。

## Refresh Semantics

- Dashboard 初次进入、既有页面重载/重试，以及现有业务流程触发的 Dashboard 刷新，应同时读取最新 Attention。
- “立即采集”的批量采集状态到达完成后，刷新 Dashboard Attention；采集正在进行时不得把旧内容标成新结果。
- Attention 局部重试只重新请求 Attention 依赖，不要求重置其他已可用区域。
- 保留当前 HTTP 请求与 React state 模式；不引入 Router、状态管理框架、WebSocket、Redis 或新前端架构。

## Backend / Frontend Responsibility

**Backend** 负责复用现有 Group Attention 规则，按 Asia/Shanghai 今日范围读取真实事实、聚合 Level / Reason / 变化竞品数 / 最近变化时间、生成稳定顺序，并提供 Dashboard KPI 所需的权威聚合口径。Attention 是只读派生 read model，不改变 ChangeEvent、Snapshot 或 Group Detail contract。

**Frontend** 负责按返回顺序展示、呈现三档 Level 和最多 3 条 Reason、显示 loading/empty/error、发起重试、刷新及复用 Group Detail 导航。Frontend 不计算、补全或缓存 Attention、Reason、数量口径或排序。

采集状态与趋势继续消费现有 Backend 数据；Attention 请求与它们隔离，失败时各自可用。

## Read Contract Expectations

当前 Dashboard 相关真实 contract：

- `GET /api/dashboard/today` 返回今日竞品级 `items`、当前事件型 `stats`、采集汇总 `collection_summary` 和 `trend_7d`；包含采集异常数、变化竞品数和事件数，但不含 Group Attention。
- `GET /api/competitor-groups/summary` 返回 `groups` 与 `unassigned`；组按 `last_change_at` 最近优先排序，含直接竞品的摘要统计和 own product 绑定身份，但没有 Attention Level、Reasons 或 Priority 排序。
- Frontend 目前请求上述两个 endpoint；Dashboard 仍渲染竞品级大表、事件型 KPI 和旧组摘要面板。
- 当前后端没有 Group Attention Dashboard read endpoint/contract。`group-attention-priority-v1.md` 已要求专门的 Backend Group Attention read model，但未锁定 endpoint 名称。

因此本 Spec 不伪称现有接口已能满足 Group-first Dashboard，也不锁定 endpoint 名称。实现时需提供最小的 Backend 读取契约，可与现有 Dashboard 请求并行，至少权威返回：

- 今日有变化且已排序的 Group 项目；每项含 `group_id` / `group_name`、own product 简要身份、Attention Level、distinct changed competitor count、最多 3 条结构化 Reason（含展示文本）及 `latest_change_at`；
- KPI 所需的监控商品组数、今日有变化商品组数、今日涉及变化竞品数，字段语义清楚；今日变化组和竞品统计范围与 Attention 规则一致；
- 如有必要的业务日期/数据状态字段，以区分成功空结果与失败。

契约不得向 UI 暴露 `attention_score`；不要求新增表、持久化分数或改造历史事实。采集异常数及 7 天趋势继续来自现有 `/api/dashboard/today`。现有 Group Summary 可用于其既定 Groups 页面职责；不得将其旧排序当作 Attention 排序。

## User Stories

1. 作为运营者，我希望先看到今日最值得检查的我方商品组，以便快速安排查看顺序。
2. 作为运营者，我希望列表顺序和关注等级由 Backend Attention 决定，以免页面用事件数量自行推断重要性。
3. 作为运营者，我希望看到每组最多三条简明原因及变化竞品数，以便在进入详情前理解关注依据。
4. 作为运营者，我希望今日无变化组不混入关注列表，以免误把静态状态当作竞争变化。
5. 作为运营者，我希望点击组后进入既有 Group Detail，以便继续查看差异和证据。
6. 作为运营者，我希望 Attention 读取失败时采集状态和趋势仍可用，以便局部故障不影响整页。
7. 作为运营者，我希望批量采集完成后看到刷新后的关注结果，以便依据最新事实行动。

## Implementation Decisions

- 本 Spec supersede `dashboard-group-entry-v1.md` 中“Dashboard 仍以竞品变化表为核心”及其旧 KPI/区域优先级决策；它不回写旧 Spec 的历史记录。
- 可复用旧 Spec 与现有实现中的 Header “添加竞品”“立即采集”、现有 `openGroupDetail(groupId)` 导航、Summary 局部状态处理经验、独立采集状态与 7 天趋势，以及当前批量采集完成后的 Dashboard 刷新 seam。
- 旧“我方商品组”摘要卡不再作为新的 Attention 列表 contract；组名/own identity 与导航呈现可复用，但数据、排序、理由和数值必须改由 Attention read model 提供。旧 Group Summary 的最近变化排序不能复用为 Attention 优先级。
- 移除竞品级大表作为 Dashboard 核心展示；竞品级变化细节归 Group Detail / Competitor Detail。
- 现有 `GET /api/dashboard/today` 与 `GET /api/competitor-groups/summary` 保持各自已有职责；是否通过新的/扩展的读取入口提供 Attention，由正式实现按最小 Backend contract 落地，不预先锁定 URL。
- 不新增前端架构、数据缓存或与本目标无关的后端持久化能力。

## Testing Decisions

测试以真实用户可观察行为和 Backend read contract 为准，不绑定组件私有结构或 SQL。沿用 Backend TestClient + 临时 SQLite 和 Frontend API mock / 渲染 / 交互测试 seam。

至少覆盖：

- 多个 Group 按 Backend Attention 顺序展示，Frontend 不二次排序；
- “重点关注 / 建议查看 / 一般变化”三层级准确呈现；
- Reason 最多 3 条；
- 无变化 Group 不进入主列表；
- 全部无变化时显示指定空状态且不出现昨日事件；
- Attention API 失败但采集状态、趋势及其他成功区域仍可用，失败与空结果可区分；
- 点击 Group 进入现有 Group Detail；
- “立即采集”完成后刷新 Attention；
- 页面不显示 `attention_score`；
- 不恢复竞品级大表作为核心区域；
- 变化竞品 KPI 和列表数量来自 Backend distinct competitor contract，而非事件行数。

## Out of Scope

- Dashboard Attention 算法、Score 校准或 Reason 生成规则的重新定义；以 `group-attention-priority-v1.md` 为准。
- Group Detail 或 Competitor Detail 内容重构。
- 价格/MOQ/SKU/库存完整横向矩阵、完整 ChangeEvent 时间线、单竞品详情、AI 建议、风险分、竞争力评分、attention_score 展示。
- 新 Router、状态管理框架、WebSocket、Redis、推送通知、数据库 Attention 历史表或评分持久化。
- 新增与 Attention 展示无关的 KPI、Dashboard 个性化排序或可配置规则。

## Acceptance Criteria

- Dashboard 的首要问题变为“今天哪些我方商品组最值得先看”。
- 主列表只展示今日有变化的 Attention Group，顺序完全保持 Backend 返回顺序。
- 组项显示规定的身份、Level、变化竞品数、最多三条 Reason、最近变化时间及 Group Detail 入口，不显示 Score。
- Group-first KPI 语义由 Backend 权威提供；Frontend 不从旧接口拼口径。
- 无变化、加载、Attention 失败状态按本 Spec 区分，Attention 失败不使独立采集状态/趋势不可用。
- 批量采集完成后刷新 Attention；导航复用现有 Group Detail。
- 7 天趋势和采集状态是辅助信息；竞品级大表不再是核心区域。
- 不引入 Spec 明确禁止的新前端架构或评分展示；测试决策中的行为全部覆盖。
