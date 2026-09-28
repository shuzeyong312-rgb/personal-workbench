# 竞品列表批量操作 V1 Feature Spec

状态：正式产品 / 工程 Spec；本轮只冻结规则，不实现代码。

## 1. 背景与目标

当前 Dashboard Header 同时提供“添加竞品”“立即采集”，与竞品列表中的操作重复；竞品只能在详情页逐个修改分组。本 Feature 收敛信息架构：

```text
Dashboard
→ 看今天哪些商品组值得关注、查看采集状态和趋势、进入组分析

Competitor List
→ 添加、选择、批量管理、采集
```

本 Spec 只新增竞品列表的通用批量选择、批量采集入口调整和批量设置竞品组能力。

本 Spec 局部 supersede：

- `docs/specs/competitor-list-pagination-v1.md` 中仅允许 `is_active = true` 商品参与 selection 的条款；
- 旧 Dashboard Spec 中要求 Header 保留“添加竞品 / 立即采集”的局部条款。

不改写历史 Spec。分页仍保持固定 10 条、`filter → paginate → render`、跨页 selection、筛选重置页码和普通刷新页码收敛规则。

## 2. Dashboard 入口收敛

移除 Dashboard Header 的：

- 添加竞品；
- 立即采集。

Dashboard 保持现有 KPI、Attention、7 天趋势、采集状态、Group Detail 导航和 Backend contract。不得借机重构 Dashboard、Header、Sidebar 或采集状态区域。

竞品列表统一承接：

- 添加；
- 批量采集；
- 批量设置分组。

实现时只做最小 UI、props 和 handler 清理；若 `DashboardHeaderActions` 完全无引用，可删除。

## 3. 竞品列表批量操作入口

顶部操作区从：

```text
[ 采集选中（0） ▼ ] [ 添加竞品 ]
```

调整为：

```text
[ 批量操作（0） ▼ ] [ 添加竞品 ]
```

`批量操作（X）` 的 X 是当前筛选条件下、跨分页累计的全部 selected IDs 数量：

```text
X = selectedIds ∩ 当前 filteredCompetitors
```

不按当前页、active 状态或可批量分组资格计数。

菜单保持一个紧凑入口，至少包含：

```text
批量操作（X）
────────────
采集选中（Y）
设置分组（Z）
────────────
采集全部监控中（N）
```

分隔标题和具体视觉样式由现有 UI 风格决定，不冻结像素。

## 4. Generic Selection Contract

selection 是通用批量选择，不再是“采集选择”。

### 4.1 行级选择

当前列表中的所有商品均可选择，包括：

- `is_active = true` 或 `false`；
- `group_role = competitor` 或 `own`。

监控状态和角色不决定 checkbox 是否可用。`batchBusy` 等现有重复提交保护仍可禁用操作控件。

### 4.2 跨页与筛选

- 同一筛选条件下跨页累计选择；翻页不清 selection；返回上一页时保留 checkbox 状态。
- 搜索、商品状态、采集状态、竞品组、Reset，以及从外部 Group 导航带入筛选条件时，将 selection 与新的完整 `filteredCompetitors` 求交集：

  ```text
  selectedIds = selectedIds ∩ new filteredCompetitors
  ```

- 隐藏到当前筛选之外、或已不存在于最新列表数据的 ID 清除；不得因为 `is_active = false` 或 `group_role = own` 清除选择。
- 普通 refresh 不因数据重新加载而统一回到第 1 页；当前页合法则保持，不合法才 clamp。筛选变化回到第 1 页。

### 4.3 Header select-all

Header checkbox 只作用当前页的全部商品，不再只作用 active 商品：

- 选中：把当前页全部 ID 加入现有 selection；
- 取消：仅移除当前页全部 ID，其他页 selection 保留；
- checked / indeterminate 基于当前页全部商品；
- 当前页无商品时不可操作。

## 5. 批量采集语义

`采集选中（Y）` 的 Y 为：

```text
Y = selectedIds
    ∩ 当前 filteredCompetitors
    ∩ is_active = true
```

实际提交给现有 `POST /api/competitors/collect-batch` 的 `competitor_ids` 必须与上述 Y 完全一致，去重且不包含 inactive 商品。`group_role` 不影响采集资格，own 和 competitor 均可采集。

当 `X > Y` 时，菜单或相邻提示明确说明：

> 已停止监控的商品不参与采集

当 `Y = 0` 时，“采集选中”禁用；不得发送空的 selected batch request。

`采集全部监控中（N）` 继续表示完整 `competitors` 中所有 `is_active = true` 商品，不受当前 filter、pagination 或 selection 影响。其现有 API 和运行状态语义不变。

采集成功后的现有 selection 清空规则继续适用于采集操作；采集失败按现有错误语义处理。

## 6. 批量设置分组资格与安全规则

`设置分组（Z）` 的 Z 为：

```text
Z = selectedIds
    ∩ 当前 filteredCompetitors
    ∩ group_role = competitor
```

允许：active / inactive、已分组 / 未分组的直接竞品。`is_active` 不限制分组资格。

`group_role = own` 的商品可以被选择，也可以参与采集，但不得参与批量分组：

- 不进入 batch group request；
- 不改变 `group_id`；
- 不改变 `group_role`；
- 不自动降级为 competitor。

如果 selection 含 own，Dialog 明确展示跳过数量，例如：

> 已选择 6 个商品，本次修改 5 个直接竞品；1 个我方商品不会参与本次批量分组。

没有 own 时不显示“0 个跳过”。当 `Z = 0` 时，“设置分组”禁用，不打开最终没有可处理对象的 Dialog。

本批量功能不得循环调用既有 `PATCH /api/competitors/{id}/group`；该单商品 API 的 own 自动降级行为仍保留，但不适用于本批量 contract。

## 7. 批量设置分组 Dialog

点击“设置分组（Z）”打开小型 Dialog，至少包含：

```text
批量设置竞品组

已选择 6 个商品
本次修改 5 个直接竞品
1 个我方商品不会参与本次批量分组

目标竞品组
[ 请选择竞品组 ▼ ]

[取消] [确认设置]
```

目标下拉包含：

- 初始占位项“请选择竞品组”，表示尚未选择目标，不对应任何 API `group_id`；
- 未分组，对应 `group_id = null`；
- 所有正式竞品组。

“尚未选择目标”与“未分组”与正式竞品组是三个不同语义。Dialog 初始目标为尚未选择，确认按钮 disabled，不能提交 request。只有用户显式选择“未分组”时才发送 `group_id: null`；选择正式组时发送对应 group ID。实现可使用 sentinel、`undefined` 或等价最小状态表达，但不得让 API 的 null 同时表示尚未选择。

取消不修改数据。Dialog 关闭后重新打开，目标重新回到“请选择竞品组”，不继承上一次提交或取消时的目标。

提交中禁用重复提交。请求失败时 Dialog 保持打开，已选择的目标、selection 和错误信息保留，用户可以直接重试。

## 8. Backend Batch API Contract

新增最小 API：

```text
PATCH /api/competitors/group-batch
Content-Type: application/json
```

Request：

```json
{
  "competitor_ids": [1, 2, 3],
  "group_id": 5
}
```

移至未分组：

```json
{
  "competitor_ids": [1, 2, 3],
  "group_id": null
}
```

### 8.1 Validation 与错误

`competitor_ids` 必填、非空、至少一个、每项为严格正整数；不接受 bool；重复 ID 去重。空数组、类型错误、非正整数按现有 API 校验风格返回稳定 422，不执行写入。

`group_id` 可为 null；非 null 时目标 `CompetitorGroup` 必须存在，否则返回稳定 404 `competitor_group_not_found`，不执行写入。

Backend 一次读取全部目标商品：

- 任意 ID 不存在时返回 404 `competitor_not_found`，响应包含 `competitor_ids` 缺失 ID；
- 缺失 ID 时不得更新其他商品；
- 请求中任意目标 `group_role = own` 时整体返回 409 `own_product_not_batch_assignable`，响应包含对应 own `competitor_ids`；
- own 错误时不得部分处理 competitor，不得降级、解除或修改 own。

错误 payload 至少保持稳定的 `code`、`message`，并在适用时返回 `competitor_ids`；不得泄露数据库异常或内部 traceback。

### 8.2 Transaction 与写入边界

批量分组必须在一个 DB transaction 内完成：全部成功或全部失败。例如 9 个 competitor 加 1 个 own 时，0 个被修改。

执行顺序固定为：

```text
完整验证整个 request
→ 确认 request 整体合法
→ 区分 same-target no-op 与真正需要修改的 rows
→ 只更新真正变化的 competitor
→ Commit
```

成功时只修改目标商品的：

```text
Competitor.group_id
Competitor.updated_at
```

目标商品的 `group_role` 必须继续为 `competitor`。如果 `competitor.group_id == request.group_id`，该商品是幂等 same-target no-op：不执行 UPDATE、不修改 `updated_at`、不计入 `updated_count`，也不进入 response 的 `competitor_ids`。所有目标都是 no-op 时仍返回成功。

不得修改 `is_active`、`status`、URL、title、shop、Snapshot、SkuSnapshot、CollectionRun、ChangeEvent 或其他历史事实。不需要 migration、新表或重复关系存储。

### 8.3 Response

返回轻量明确响应，不返回完整 Competitor list：

```json
{
  "updated_count": 3,
  "competitor_ids": [1, 2, 3],
  "group_id": 5
}
```

`group_id` 可为 null。`updated_count` 只统计真正改变 `group_id` 的商品；`competitor_ids` 只包含真正更新的 IDs，保持去重后的请求顺序或等价稳定顺序。全部 no-op 时返回 200，例如：

```json
{
  "updated_count": 0,
  "competitor_ids": [],
  "group_id": 5
}
```

完整 validation 必须先于 no-op 判断：missing competitor、目标 group 不存在、非法 ID 或 own 均按整体错误处理，不能因其他商品是 no-op 而跳过校验。

## 9. Frontend 成功与失败

成功后：

1. 关闭 Dialog；
2. 清空 selection；
3. 依据 Backend `updated_count` 显示 Toast：`updated_count > 0` 时显示实际更新数量，例如“已将 2 个竞品设置到「A19」”或“已将 2 个竞品移至未分组”；`updated_count = 0` 时显示“所选竞品已在目标分组，无需修改”，不显示“已修改 0 个竞品”；
4. 复用现有 read seam 刷新竞品列表、Groups / Group Summary 和 Dashboard / Group Attention：优先使用 `loadCompetitors`、`loadGroups`、`loadDashboard` 及现有 Attention refresh，不新增全局状态管理。

Frontend 不把 batch response 当作新的完整 read model；成功后重新读取权威数据。

失败时：

- Dialog 保持打开；
- selection 保留；
- 目标 group 选择保留；
- 显示可理解的错误；
- 不假装部分成功；
- 不自动刷新成未知状态；
- 防止重复提交。

详情页现有“所属竞品组 [修改]”继续保留：单个商品修改在 Detail，批量修改在 Competitor List。

## 10. Implementation Decisions

- 复用现有 Competitor List、App state、`loadCompetitors` / `loadGroups` / `loadDashboard` 和既有 Attention refresh seam；不新增 Router、全局状态管理、migration、表或依赖。
- 复用既有单商品 group assignment 的数据模型和 `group_id` 单一事实来源，但批量写入使用独立原子 API，不循环调用单商品 API。
- Frontend 只负责 generic selection、资格计数、Dialog 三态、请求反馈和刷新；Backend 负责完整 validation、own 安全防线、same-target no-op、事务和真实更新数量。
- `group_id = null` 只在用户显式选择“未分组”后进入 API；尚未选择目标永远不能提交。

## 11. Pagination / E2E 兼容

继续复用现有 Playwright E2E、fixture 和 fail-closed API mock 体系，不新建第二套 QA、Mock Server 或依赖。

现有分页 E2E 中“inactive 行不可选择”必须更新为新 contract，不得为通过旧测试保留 active-only 行为。至少更新/覆盖：

- 分页边界、跨页 selection、header select-all 只影响当前页；
- inactive 行现在允许选择；
- filter change 后 selection 与新的 filtered result 求交集；
- `批量操作（X）` 的 X 为全部 selection；
- “采集选中（Y）”只提交 selected active IDs；
- own 可选择和采集，但不进入 group-batch request；
- 选择多个商品 → 打开批量操作 → 设置分组 → Dialog 显示处理数量且初始无目标 → 选择 A19 或未分组后确认按钮才可用 → 提交；
- 验证真实浏览器发出的 PATCH body、成功后 selection 清空、列表显示刷新后的分组。

E2E fixture 可增加少量 inactive / own / 分组变体；仅为新增 PATCH 及后续 GET 明确声明 mock。不得连接真实 Backend、SQLite、1688 或真实工作数据。

## 12. Testing Decisions

测试只验证外部行为、API contract、持久化事实和用户可见状态，不测试 SQL 拼接、React state 实现或组件内部细节。优先复用现有 Backend API tests、Frontend tests、分页 E2E、fixture 和 fail-closed API mock seam；不新增测试框架、Mock Server 或第二套 QA。

### 12.1 Backend API tests

至少覆盖：

1. 多个 competitor 成功移动到正式组；
2. 批量移动到 null；
3. inactive competitor 可以修改分组；
4. group 不存在；
5. competitor ID 不存在；
6. `competitor_ids` 空、bool、非正整数、非法类型和重复值；
7. request 含 own 返回整体 409；
8. own 错误时其他 competitor 也未修改；
9. `group_role` 保持 competitor；
10. monitoring、status、history 未修改；
11. 任意失败均整体 rollback。

12. mixed request 中部分商品已在目标组、部分需要移动时，只更新变化项，`updated_count`、response IDs 正确，same-target 商品的 `updated_at` 不变化。
13. all already-in-target 返回 200、`updated_count = 0`、空 response IDs，且不修改 `updated_at`。
14. request 含 own 时，即使其他商品或 own 已在目标组，仍整体 409 且所有商品未修改。

测试外部 API 行为和持久化事实，不测试 SQL 拼接或内部实现细节。

### 12.2 Frontend unit/component tests

至少覆盖：

- generic selection 包含 inactive 和 own；
- `批量操作（X）`、`采集选中（Y）`、`设置分组（Z）` 三种口径；
- collection request IDs 与 Y 完全一致；
- header select-all 使用当前页全部商品；
- Dialog own skip 信息；
- Dialog 初始显示“请选择竞品组”，未选择时确认 disabled；
- 显式选择“未分组”时 request 使用 `group_id: null`；
- Dialog 关闭重开后不保留旧目标；
- 成功清空并刷新、失败保留 Dialog / selection / target group；
- `updated_count = 0` 使用“无需修改”成功文案；
- Dashboard 不再出现“添加竞品”“立即采集”；
- Detail 单商品修改入口继续存在。

无需为 same-target no-op 增加独立 E2E；Backend / Frontend tests 足够。Playwright 只保护初始无目标、显式选择后提交、请求 body、成功清空 selection 和列表刷新这条关键路径。

## 13. 非目标

本轮不做：批量停止或恢复监控、批量删除、批量设置 own、批量改状态、拖拽分组、多组归属、标签系统、Group Detail 重构、Dashboard 重构、新 Router、状态管理库、migration、新表、新第三方依赖或其他 V1.1 批量能力。

“批量操作”只是稳定入口，本轮只实现采集选中、设置分组和采集全部监控中三个既定动作。

## 14. 验收标准

1. Dashboard 不显示“添加竞品”“立即采集”。
2. Competitor List 显示“批量操作（X）”。
3. 所有列表商品均可勾选；inactive competitor 可选择和批量设置分组。
4. 跨页 selection 保持；筛选变化按 filtered result 求交集。
5. Header select-all 只影响当前页全部商品。
6. `采集选中（Y）` 只处理 selected active，`采集全部监控中` 语义不变。
7. own 可选择和采集，但不参与批量分组且不发生静默降级。
8. Batch API 支持正式组和 null，并原子执行。
9. Group assignment 不修改监控、状态或历史事实。
10. 成功后 selection 清空、数据刷新并 Toast；失败时 Dialog 和 selection 保留。
11. Detail 单商品修改继续可用。
12. 分页核心行为、Playwright、Frontend tests 和 Backend API tests 覆盖新 contract。
