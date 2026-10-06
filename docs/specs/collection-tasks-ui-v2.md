# 采集任务 UI V2 Feature Spec

状态：待实现；本轮只定义 Frontend 信息架构与视觉表达，不修改业务代码。

## Problem Statement

当前“采集任务”页面将当前批次的全部已完成商品逐条铺开。一次批量采集有 40 至 50 个商品时，页面会被成功项拉长，当前状态和异常难以快速识别。

同时，当前批次的商品级结果与“采集记录”承担了相近的信息展示职责，但两者的数据事实不同：前者是当前或最近一次内存中的 BatchRuntime，后者是可查询的历史 CollectionRun。视觉上未区分这两个层级会让用户误以为它们是重复数据。

最后，运行、成功、失败、计划休息、风控冷却和人工验证大量使用相近的浅蓝灰或浅绿色，不能支持快速状态判断。

## Solution

将“采集任务”页调整为三个职责明确的层级，沿用现有工作台 AppShell 和数据加载 seam：

1. **当前批量采集**：页面第一视觉层级，只提供当前批次的状态、汇总、进度、当前商品和状态提示。
2. **本批次明细**：使用现有 BatchRuntime `items`，默认折叠；用户主动展开后才查看商品级结果。
3. **采集记录**：继续是历史 CollectionRun 的搜索、筛选、表格和分页入口。

不改变 Backend、API、数据库、BatchRuntime、采集行为、现有 polling 归属或 Dashboard 的发起入口。

## User Stories

1. 作为采集用户，我希望首先看到当前批量的明确状态和核心进度，以便不必浏览几十条商品结果也能判断批次是否正常。
2. 作为采集用户，我希望看到已完成、成功、失败和剩余数量，以便快速判断本批次结果。
3. 作为采集用户，我希望在运行时知道当前正在处理哪个商品，以便确认任务没有停在未知位置。
4. 作为采集用户，我希望能区分计划内休息与风控冷却，以便知道是否需要等待或处理风险。
5. 作为采集用户，我希望人工验证需求足够醒目，以便及时采取人工动作。
6. 作为采集用户，我希望默认不看到完整的成功商品列表，以便页面保持紧凑。
7. 作为采集用户，我希望按需展开本批次商品级结果，以便定位具体成功、失败或验证项。
8. 作为采集用户，我希望展开的批次明细保持后端返回顺序，同时通过视觉强调识别失败和验证问题，以便兼顾结果顺序与异常处理。
9. 作为采集用户，我希望仍能搜索、筛选和翻阅历史采集记录，以便查询过去的单商品采集尝试。
10. 作为采集用户，我希望我方商品和直接竞品保持中性身份标识，以便不把身份误读为运行状态。
11. 作为采集用户，我希望状态色一致且节制，以便快速识别而不是面对彩色标签集合。

## Implementation Decisions

### 1. 数据事实、职责与边界

- 当前批量采集和本批次明细只消费既有 `GET /api/competitors/collect-batch/status` 返回的 BatchRuntime；继续复用唯一的 `loadBatchStatus()` 和既有 polling，不创建第二个 polling loop、请求源或本地状态机。
- `completed` 仍是后端 status 的权威事实；Frontend 不得用本地计时把它改写为 `idle`。
- 本批次明细中的商品资料继续由既有未过滤商品响应构造的 `productById` 提供。映射缺失时展示真实 `competitor_id` 与资料缺失状态，不猜测商品资料。
- 采集记录继续只消费既有 `GET /api/collection-runs`。它表示一次单商品 CollectionRun，不得被展示成 batch，也不得按时间推断它属于某个 batch。
- 本批次明细 = 当前或最近一次仍由 BatchRuntime 保留的商品级运行结果；采集记录 = 历史 CollectionRun 查询。二者不互相补造数据。
- 不新增 Backend endpoint、字段、迁移、数据库表、批次持久化、API contract、采集操作或新的复杂组件体系。

### 2. 页面结构与视觉层级

- 页面顺序固定为：当前批量采集 → 本批次明细 → 采集记录。
- 当前批量采集是首要视觉区；采集记录是第二层级；本批次明细是当前批次的按需展开内容，不与历史记录竞争页面首屏。
- 沿用当前工作台的卡片、间距、字体、按钮和 AppShell 语言；仅在现有页面局部调整结构与状态表达。
- 不使用图表、AI 总结、内部固定高度的大滚动框、新的复杂卡片系统、大面积高饱和背景或彩虹式标签集合。
- 大面积背景仅可使用极浅状态 tint。强语义色只用于 Badge、关键数字、进度条和异常提示；普通说明与元数据使用现有蓝灰色。

### 3. 当前批量采集

该区只回答：当前批次是什么状态、已完成多少、成功多少、失败多少、剩余多少、当前处理哪个商品，以及是否处于 `resting`、`cooling_down` 或 `verification_required`。

- 保留四个核心数字：已完成、成功、失败、剩余；主进度条、当前商品和状态提示。
- `running` 与 `resting` 必须展示主进度条，进度仅由现有 `completed / total` 计算。
- 不在此区默认渲染几十条已完成 item，也不以逐条成功项代替批次总结。
- 当前商品仅在 status 提供 `current_competitor_id` 时展示；保持现有可得的标题、Offer ID、店铺与身份信息及缺失 fallback。
- 局部 batch status 的 loading、error、retry 和已取得状态的保留行为沿用现有 contract；不得让历史区的状态遮蔽当前批量采集区，反之亦然。

#### 状态呈现

| 状态 | 用户可见标题与提示 | 必需内容 |
| --- | --- | --- |
| `idle` | 当前无批量采集任务 | 紧凑空态；不得据此推断没有历史记录。 |
| `running` | 采集中 | 四个核心数字、进度条、当前商品、运行提示。 |
| `resting` | 计划内主动休息 | 四个核心数字、进度条、现有 `resting_remaining_seconds`；明确这是计划内主动休息。 |
| `cooling_down` | 风控冷却中 | 四个核心数字、现有 `cooldown_remaining_seconds` 与自动恢复信息；明确这是风控或验证触发后的冷却，不等同于 resting。 |
| `verification_required` | 需要人工验证 | 四个核心数字、当前商品（若有）和清晰人工动作提示；不得提供绕过、跳过或自动验证操作。 |
| `completed` | 本批次已完成 | 批次总结、四个核心数字及现有结果信息；不得默认展开完整 item list。 |

`cooling_down` 不要求进度条；其重点是冷却原因、剩余时间和自动恢复。倒计时始终以 Backend 每次 status 响应为准，Frontend 不自行递减或推测。

### 4. 本批次明细

- 本区使用当前 BatchRuntime `items`，默认折叠。
- 折叠态必须显示：本批次总商品数、成功数、失败数、verification 数（存在时明确显示）以及“查看本批次明细”控制。
- 没有 item 结果时不伪造明细；控件可显示无商品级结果的真实空态。
- 展开后才显示商品级结果，并保留既有成功结果、失败原因、验证信息和 outcome 的事实表达。
- 全成功批次：展示可查看的成功数据，但成功行维持低视觉权重，不得成为页面主体。
- 展开后必须保持 BatchRuntime `items` 的 Backend 原顺序，不得为了异常优先重排。存在 `failed` 或 `verification_required` item 时，仅通过状态色、Badge、提示和高于成功项的视觉权重强化异常；成功项不删除、不隐藏。
- 折叠/展开只改变本批次 items 的可见性，不请求新接口、不改变 batch 运行状态、不影响历史筛选或分页。

### 5. 采集记录

- 继续承担历史查询职责，保留搜索、状态筛选、身份筛选、历史表格和分页。
- 继续使用后端查询、过滤、排序和分页 contract；不下载完整历史后在浏览器重新分页或筛选。
- 历史 `CollectionRun.status = running` 只能表达历史记录“未完成”，不能表示当前批量仍在运行。
- 采集记录的独立 loading、error、empty、retry、最新请求保护和分页行为不得因新增本批次明细回归。
- 身份标签仅表达“我方商品”或“直接竞品”，不得承担 success、failed、running 或异常的强状态色语义。

### 6. 统一状态颜色体系

| 语义 | 强调颜色 | 使用范围 |
| --- | --- | --- |
| `running` | 品牌蓝 | 状态 Badge、进度条、关键数字。 |
| `resting` | 紫或靛蓝 | 状态 Badge、进度条、关键数字。 |
| `cooling_down` | 琥珀 | 状态 Badge、冷却提示、关键数字。 |
| `verification_required` | 橙 | 状态 Badge、人工动作提示、异常数字。 |
| `completed` / `success` | 绿 | 状态 Badge、完成汇总、成功强调。 |
| `failed` | 红 | 状态 Badge、失败提示、失败数字。 |
| `idle` | 灰蓝 | 空态与非运行状态提示。 |

- ownership 使用中性标签；普通元数据使用蓝灰色。
- 不把每个字段、每行或整块背景着色。浅 tint 仅作局部容器辅助，不降低文字与状态的可读性。
- 同一状态在当前批量采集、本批次明细与采集记录中使用同一语义色；历史记录中的运行状态保持低干扰，避免被误认为实时状态。

## Testing Decisions

测试验证用户可见的 DOM、可访问性角色、请求参数和交互结果，不断言私有 React state、内部 helper 或 CSS 实现细节。

优先复用现有 seam：`App.test.tsx` 的应用级渲染 seam、现有 Collection Tasks 页面渲染/交互 seam，以及现有 fail-closed API mock 的 Playwright 页面 QA。无须创建新的测试框架、fixtures 架构或 Backend 测试。

### 页面渲染与交互

至少覆盖：

1. `running` 显示状态、四个数字、progress 和当前商品。
2. `resting` 独立显示计划休息语义、剩余时间和 progress。
3. `cooling_down` 显示风控冷却语义及既有冷却信息，且不混同 resting。
4. `verification_required` 显示明显人工动作提示。
5. `completed` 显示批次总结，且默认不展开完整 items。
6. `idle` 只显示当前无批量采集任务，不影响历史记录。
7. 有批次 items 时，默认不直接渲染完整 item list；“查看本批次明细”可展开并再次收起。
8. 全成功批次展开后可查看成功数据，但没有几十个成功项主导首屏。
9. 展开后 item 顺序保持 Backend 原顺序；存在 failed 或 verification item 时，通过状态色、Badge、提示和视觉权重明确可见，且不重排 items。
10. 历史搜索、状态筛选、身份筛选和分页继续发出既有正确请求并保持现有页面行为。
11. ownership 标签不使用强状态色；普通元数据不被升级成状态强调。
12. status 与历史请求任一失败时，另一块仍独立可用；恢复后沿用既有刷新行为。

### API 与契约回归

- Frontend 测试和 Playwright mock 只使用既有 batch status 和 collection-runs contract；不得为了 UI V2 添加或依赖新字段。
- 保持当前 backend contract：BatchRuntime 是当前批次唯一事实，CollectionRun 是历史单商品事实。
- 本 Spec 不要求新增或修改 Backend 测试；实现时如现有前端 fixture 缺少 `resting` 或其他既有 status，可在现有前端 mock seam 中补足最小 fixture。

### Playwright

保留并扩展一个核心采集任务页面流程：进入采集任务页、验证当前批量采集层级和默认折叠、展开/收起本批次明细、确认历史状态筛选与分页仍可用。API mock 必须继续默认拒绝未声明的 `/api/**` 请求，不连接真实 Backend 或数据库。

## Out of Scope

- 修改 Backend、API、数据库、BatchRuntime、CollectionRun、采集 runner、cooling、resting、自动恢复或验证行为。
- 新增批次 ID、历史 batch 聚合、batch 持久化、WebSocket、SSE 或第二个 polling loop。
- 新增采集发起、重跑、跳过、绕过验证、加速冷却或人工验证自动化操作。
- 重做 AppShell、全局设计系统、Dashboard 或其他页面。
- 图表、AI 总结、固定高度 item 滚动容器和新的复杂卡片系统。

## Further Notes

自检结论：所需状态、计数、当前商品 ID、items、resting/cooldown 剩余时间与验证数量均已由当前 batch status contract 提供；历史查询继续由既有 CollectionRun contract 提供。本 Spec 未要求后端不存在的数据，也未让 batch item 与历史 CollectionRun 互相替代。

实现前以当前 API 响应为准：若 status 响应没有可展示的当前商品或 item，页面显示真实缺失状态，而不以历史记录补造内容。
