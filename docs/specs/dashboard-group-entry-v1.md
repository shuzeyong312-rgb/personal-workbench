# Dashboard Group Entry V1

## Problem Statement

Dashboard 已经回答“今天有哪些竞品发生了什么”，Group Detail 已经回答“这个我方商品组现在处在什么竞争状态”，但 Dashboard 缺少从变化行或总览直接进入对应组分析的自然路径。用户需要先离开 Dashboard，再从竞品组页面寻找目标组。

## Solution

在不重做现有 Dashboard 的前提下，为“我方商品组 → Group Detail”建立第一版自然入口：Dashboard 今日变化表中的已分组商品可进入其 Group Detail；页面下方并列展示紧凑的“我方商品组”列表，提供常用组分析入口。

这不是 Dashboard 组级重构、第二个 Group Detail、风险排名、AI 推荐或竞争力评分。Dashboard 仍以“今日发生变化的竞品”为最重要模块。

## User Stories

1. 作为用户，我希望从 Dashboard 今日变化表点击竞品组名称进入对应组分析，以便从竞品动作直接查看整组竞争环境。
2. 作为用户，我希望未分组商品继续显示“未分组”且不可点击，以便系统不虚构一个分析组。
3. 作为用户，我希望今日变化表的“查看详情”仍进入单个竞品详情，以便检查该商品的具体事实证据。
4. 作为用户，我希望从 Dashboard 下方看到已绑定我方商品的组，以便快速进入常用 Group Detail。
5. 作为用户，我希望组列表优先展示最近发生竞品变化的组，以便更快到达近期有动作的组；该顺序来自现有 Backend Summary。
6. 作为用户，我希望列表最多展示四个组，避免 Dashboard 下方区域挤压现有内容。
7. 作为用户，我希望能从面板进入完整竞品组页面，以便查找未展示的其他组。
8. 作为用户，我希望未绑定组不出现在“我方商品组”列表中，以便该模块名称与组的真实绑定状态一致。
9. 作为用户，在没有任何已绑定组时，我希望看到明确的空状态和竞品分组入口，以便先完成我方商品绑定。
10. 作为用户，我希望每组显示组名、我方商品标题或 Offer fallback、今日变化竞品数、直接竞品数及最近变化时间，以便快速识别入口而不在 Dashboard 重复做组分析。
11. 作为用户，我希望看到“今日暂无竞品变化”和“暂无变化记录”等事实性状态，而不是安全、正常或风险判断。
12. 作为用户，我希望 Group Summary 加载失败时 Dashboard 的 KPI、今日变化、采集状态和趋势仍可用，以便局部问题不遮蔽整页信息。
13. 作为用户，我希望可以单独重试失败的组面板，或前往竞品分组，以便恢复该区域而不重载失败无关的 Dashboard 主体。
14. 作为用户，我希望添加竞品与立即采集仍容易找到，以便保留 Dashboard 常用操作。
15. 作为用户，我希望绑定、更换或解除我方商品、创建或删除组、改变组成员及完成新一轮采集后看到最新组摘要，以便入口状态反映真实数据。
16. 作为用户，我希望 Dashboard 的四个 KPI、今日聚合、7 天趋势、采集状态和业务日口径保持现状，以便此次入口增强不改变既有监控结果。

## Implementation Decisions

### 页面结构与操作

- PageHeader 保留“监控中 X 个竞品”，并将“添加竞品”“立即采集”从 QuickActions 移至 Header；沿用现有 UI System 的克制操作层级及现有操作可用性条件，不增加其他操作。
- 删除整块 QuickActions 卡片；“竞品列表”已有 Sidebar 固定入口。
- lower-right 原 QuickActions 区域改为紧凑“我方商品组”面板，与左侧“近 7 天竞品变化趋势”并列。最多四行，不做四张大型组卡，也不做 Group Detail mini page；维持 Compact Dashboard 高度。
- 今日变化表标题、竞品行粒度和“查看详情”均保留。Dashboard 最终结构为：Header；四个现有 KPI；左侧今日变化竞品、右侧采集状态概览；左侧 7 天趋势、右侧我方商品组。

### 数据与排序

- 首次 Dashboard 加载和重新加载读取 `GET /api/dashboard/today` 与 `GET /api/competitor-groups/summary`。Summary 是 Dashboard 的组数据唯一来源；不为同一目的同时重复请求 `GET /api/competitor-groups`。
- 面板只消费 Summary 的 `groups`，不消费 `unassigned`。Dashboard 主列表仅包含 `own_product != null` 的正式组。
- 按 Backend Summary 返回顺序展示过滤后的已绑定组，最多四个；Frontend 不二次排序或计算风险、分数、权重。现有 Summary 按 `last_change_at DESC`、无变化组置后，并以创建时间及稳定 ID 排序兜底；其 `last_change_at` 和今日变化数仅聚合直接竞品，不含 own。
- 若已绑定组多于四个，显示“查看全部竞品组”并进入 Groups Page；未绑定组不占用面板行数。
- 组行只显示 `group.name`、`own_product.title`（为空时使用 `Offer {offer_id}`）、`changed_competitors_today`、`competitor_count`、`last_change_at`。可在不增加行高的前提下显示 `active_count`，否则省略。不得显示价格区间、MOQ、SKU、库存、fact gap、事件领域或评分。
- `changed_competitors_today > 0` 显示“今日 {N} 个竞品变化”；为 0 显示“今日暂无竞品变化”。有 `last_change_at` 时使用已有事实性时间格式显示最近时间；为 null 显示“暂无变化记录”。不得从当前时间推算经过时长或给出判断性状态。
- 无已绑定组时显示紧凑空状态“还没有绑定我方商品”，说明“先在竞品分组中绑定我方商品，再从 Dashboard 快速进入组分析。”，操作为“前往竞品分组”。Dashboard 不提供绑定 Dialog。

### 导航与加载状态

- 组行“组分析”和今日变化表内非空 `group_id` 的真实组名都调用现有 `openGroupDetail(group.id)` 导航。今日变化表的组名来自 Summary 中按 ID 匹配的正式组；`group_id = null` 继续显示不可点击的“未分组”。Summary 失败且无法取得组名时显示“组名暂不可用”，不伪造名称或跳转目标。
- 保留“查看详情”并继续进入 Competitor Detail。组名链接和单商品详情是两个不同入口，互不替代。
- Dashboard 主数据和 Group Summary 在同一页面加载周期请求，但拥有隔离的状态：Dashboard 主请求失败时使用现有 Dashboard Error；仅 Summary 请求失败时 Dashboard 主体保持可用，组面板显示局部失败状态，并提供单独重试与“前往竞品分组”。Summary 重试不得把已显示的 Dashboard 主体切换为整体加载或错误状态。
- Group Summary 的加载/错误状态局限于其面板；Dashboard 主请求成功时，Dashboard 主体正常渲染。不得因组面板失败而把 KPI、今日变化、趋势或采集概览显示为整体 Error。

### 刷新边界

- 沿用现有 `loadDashboard()` 页面加载/重载 seam，将 Summary 纳入该加载；不增加事件总线或全局状态框架。
- Dashboard 初次进入、用户重试、组或成员变化后的现有 Dashboard 刷新，以及批量采集由 running 转 completed 后的现有 `loadDashboard()`，都应同步刷新 Summary。绑定、更换、解除 own，创建/删除组，成员变化和采集完成的操作流程完成后，应通过现有刷新路径使 Dashboard 下次可见时反映新状态。
- Summary 局部重试只重取 Summary；不额外刷新 Dashboard 主数据。批量采集完成时不再单独触发第二次组 Summary 请求。

### API 与兼容边界

- Backend 原则上零修改，继续使用 `GET /api/dashboard/today`、`GET /api/competitor-groups/summary` 和既有 `GET /api/competitor-groups/{group_id}/detail`。
- 不修改 Dashboard response、Dashboard 今日聚合、`primary_change`、`change_count`、`change_types`、`stock_total_change`、`trend_7d`、`collection_summary` 或 Asia/Shanghai business day。
- 不新增 `/api/dashboard/groups`、`/api/dashboard/group-attention`、`GroupDashboardSummary`、`DashboardGroupScore` 或其他 Backend endpoint、数据库字段、migration。
- 前端仅增加支撑 Summary、局部状态及回调所需的最小页面 contract；不重构整个 App state，不引入 React Router。
- 延续现有 Dashboard Compact 样式、可访问性基础和 UI System；不扩大到 Sidebar 或其他页面。

## Testing Decisions

- 好的测试验证用户可见行为及加载隔离，不锁定 CSS 像素或内部实现细节。
- 在现有 Frontend 页面测试 seam 覆盖 Header 保留监控数量并提供添加竞品/立即采集；QuickActions 卡片移除；组过滤、Summary 顺序、最多四项、own 标题 fallback、变化数两种文案、空最近变化、空状态、查看全部竞品组和组分析导航。
- 覆盖今日变化表：非空 `group_id` 显示对应可点击组名并进入 Group Detail；空 `group_id` 显示“未分组”且不导航；“查看详情”仍进入 Competitor Detail。
- 覆盖 Summary 失败时 Dashboard 主体保持可见、组面板显示局部失败及独立重试；Dashboard 主请求失败仍使用原页面错误状态。
- 复用现有 Frontend `App.test.tsx` 渲染与交互测试先例；不增加 Backend 测试，因为预期不改变 Backend contract 或行为。现有 Dashboard、Groups Summary 与 Group Detail 测试继续保障其 API contract。

## Out of Scope

- Dashboard Backend contract 修改、新 API、新数据库字段或 migration。
- Group Attention、事件领域分布 API、风险/竞争力/权重评分、AI、自动建议或排序算法。
- Dashboard 展示价格区间、MOQ、SKU、库存横向比较或 fact gap；复制 Group Detail。
- 今日变化竞品级聚合、KPI 口径、7 天趋势、采集状态或 Asia/Shanghai 业务日规则调整。
- 全面组中心化 Dashboard 重构、删除竞品行、Sidebar 改版、React Router、新状态框架或绑定 Dialog。
- 除明确的两个 Spec 文件外的任何项目文件修改。

## Further Notes

本 Feature 是 Group Intelligence 长期方向的过渡阶段：当前保留“竞品事件总览 + 我方商品组入口”。真实使用稳定后，可另行评估是否将 Dashboard 主模块升级为组级关注入口；本 Spec 不预先决定该重构。
