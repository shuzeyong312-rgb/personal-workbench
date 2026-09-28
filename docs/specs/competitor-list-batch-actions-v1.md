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

本 Spec 新增竞品列表的通用批量选择、批量采集入口调整、批量设置竞品组，以及批量停止监控、批量恢复监控和批量永久删除能力。

本 Spec 局部 supersede：

- `docs/specs/competitor-list-pagination-v1.md` 中仅允许 `is_active = true` 商品参与 selection 的条款；
- 旧 Dashboard Spec 中要求 Header 保留“添加竞品 / 立即采集”的局部条款。
- `docs/specs/competitor-lifecycle.md` 中“本 Feature 不新增批量操作”的局部历史限制。

不改写历史 Spec。生命周期语义仍完全复用 `docs/specs/competitor-lifecycle.md`：停止不删除历史，恢复不立即采集，永久删除不可恢复且受 `COLLECTION_LOCK` 保护。本 Spec 仅局部 supersede 其批量操作限制。分页仍保持固定 10 条、`filter → paginate → render`、跨页 selection、筛选重置页码和普通刷新页码收敛规则。

## 2. Dashboard 入口收敛

移除 Dashboard Header 的：

- 添加竞品；
- 立即采集。

Dashboard 保持现有 KPI、Attention、7 天趋势、采集状态、Group Detail 导航和 Backend contract。不得借机重构 Dashboard、Header、Sidebar 或采集状态区域。

竞品列表统一承接：

- 添加；
- 批量采集；
- 批量设置分组；
- 批量停止监控；
- 批量恢复监控；
- 批量永久删除竞品。

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
停止监控（A）
恢复监控（B）
────────────
删除竞品（D）
────────────
采集全部监控中（N）
```

分隔线和具体视觉样式由现有 UI 风格决定，不冻结像素。菜单不增加一排顶部按钮，继续复用现有紧凑 Popover。

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
- 生命周期批量操作复用既有 `is_active`、历史保留、恢复不立即采集和永久删除语义；Detail 的单商品 API 与入口继续保留，List 只增加多选入口。
- Monitoring Batch 使用独立原子 API，不循环调用单商品 monitoring API；不获取 `COLLECTION_LOCK`，不引入新的等待、排队或并发模型。
- Batch Delete 使用独立 API，在现有 `COLLECTION_LOCK` 内重新读取并完整验证目标，在一个事务中按既有依赖顺序删除；不循环调用单商品 delete API。
- Frontend 按 generic selection 计算 X / Y / Z / A / B / D，Frontend 排除 own 只作为 UX 防线，Backend 对 batch delete 再次执行 own 安全校验。

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
- 选择 active 商品（可含 own）→ 停止监控 → 普通确认 Dialog → 验证 monitoring-batch PATCH body 只包含 active IDs → 成功后 selection 清空、监控状态刷新；
- 选择普通 competitor 与 own → 删除竞品 → 高风险确认 Dialog 显示 own 跳过数量 → 验证 delete-batch POST body 只包含 competitor IDs → 成功后普通竞品消失且 own 保留。

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
- Detail 单商品停止 / 恢复 / 删除入口继续存在；
- 停止与恢复分别只处理 active / inactive selected 商品；own 可停止和恢复；
- 停止需要普通确认，恢复不需要二次确认；停止、恢复失败时保留 selection；
- 删除 Dialog 显示 own 跳过数量，active / inactive competitor 均可删除，D 为 0 时 disabled；
- 删除成功清空 selection，删除失败保留 Dialog 和 selection；
- monitoring-batch 与 delete-batch 的错误、no-op、数量和 response IDs 按 Backend contract 展示。

无需为 same-target no-op 增加独立 E2E；Backend / Frontend tests 足够。Playwright 只保护初始无目标、显式选择后提交、请求 body、成功清空 selection 和列表刷新这条关键路径。

### 12.3 Monitoring Batch API tests

至少覆盖：

1. 多个 active 成功停止监控；
2. 多个 inactive 成功恢复监控；
3. own 可以停止和恢复；
4. mixed active / inactive 只更新真实变化项；
5. same-state no-op 不修改 `updated_at`；
6. 全部 no-op 返回 200、`updated_count = 0`、空 response IDs；
7. duplicate IDs 去重并保持稳定顺序；
8. bool、非正整数、非法类型和空数组返回 422；
9. `is_active` 严格接受 boolean，拒绝 `0`、`1`、`"true"`、`"false"`；
10. missing ID 返回整体 404，其他商品不更新；
11. 只改变 `is_active` 和 `updated_at`，不改变 status、group、role 或历史事实；
12. 不依赖 `COLLECTION_LOCK`，锁被占用时仍按 monitoring contract 处理。

### 12.4 Batch Delete API tests

至少覆盖：

1. 多个普通 competitor 成功删除；
2. active 与 inactive competitor 均可删除；
3. ChangeEvent、CollectionRun、SkuSnapshot、ProductSnapshot 和 Competitor 均被删除；
4. CompetitorGroup 保留；
5. own 出现在 request 时整体返回 409 `own_product_not_batch_deletable`，其他 competitor 也不删除；
6. missing ID 返回整体 404，其他 competitor 不删除；
7. duplicate、bool、非正整数、非法类型和空数组按 contract 返回 422；
8. `COLLECTION_LOCK` 忙时返回 409 `collection_in_progress`；
9. 删除过程异常 rollback 整个 batch；
10. 删除成功后相同 offerId 可以重新添加；
11. response 的 `deleted_count` 和 IDs 正确。

## 13. 非目标

本轮不做：批量设置 own、批量修改商品业务 `status`、拖拽分组、多组归属、标签系统、Group Detail 重构、Dashboard 重构、新 Router、状态管理库、migration、新表、新第三方依赖、自动排队删除、删除回收站、撤销删除、批量恢复已永久删除商品或其他未明确冻结的批量能力。

“批量操作”是稳定入口，本 Spec 现在实现采集选中、设置分组、停止监控、恢复监控、删除竞品和采集全部监控中六个动作；不改变单商品 Detail 生命周期入口。

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
13. 菜单显示停止监控（A）、恢复监控（B）和删除竞品（D），保持现有紧凑 Popover。
14. X 为当前 filter 下全部 selected；Y / A 为 active selected；B 为 inactive selected；Z / D 为 competitor selected；N 继续为全部 active 商品。
15. 停止只处理 selected active，恢复只处理 selected inactive；own 可以停止和恢复。
16. 停止使用普通确认 Dialog，恢复不要求二次确认；两者均不立即启动采集。
17. Monitoring Batch 原子执行，same-state no-op 不更新 `updated_at`，且不获取 `COLLECTION_LOCK`。
18. 删除支持 active / inactive 普通 competitor；own 不进入请求，Backend 对 own request 返回整体 409。
19. Batch Delete 使用 `COLLECTION_LOCK` 和单事务，按 ChangeEvent、CollectionRun、SkuSnapshot、ProductSnapshot、Competitor 顺序删除，任何 missing / own / lock / transaction failure 均不产生部分删除。
20. 删除成功后 selection 清空、权威数据刷新并按现有分页规则 clamp；失败保留 Dialog 和 selection。
21. Detail 的停止、恢复、删除单商品入口和既有 API 继续存在。

## 15. 生命周期批量操作扩展

本节是对现有 Batch Actions V1 的增量扩展。已经冻结并实现的批量采集、批量分组、generic selection、分页和 Dashboard 规则继续有效；以下规则只增加生命周期批量动作，不重新定义既有动作。

### 15.1 User stories

1. 作为竞品监控用户，我希望一次停止多个仍在监控的商品，以便减少逐个打开详情页的操作。
2. 作为竞品监控用户，我希望一次恢复多个已停止商品，以便重新纳入后续监控范围。
3. 作为竞品监控用户，我希望停止后历史快照、SKU、采集记录和变化事件仍可查看，以便保留事实追溯。
4. 作为竞品监控用户，我希望恢复不会立即启动采集，以便监控状态变化不会意外触发耗时任务。
5. 作为竞品监控用户，我希望一次永久删除多个普通竞品及其历史，以便清理误添加或验收数据。
6. 作为竞品监控用户，我希望删除 Dialog 明确显示不可恢复和历史数据范围，以便在高风险操作前确认后果。
7. 作为竞品监控用户，我希望我方商品可以停止或恢复，但不能被批量删除，以便保护组基准商品。
8. 作为竞品监控用户，我希望 active、inactive、own 商品继续共享 checkbox selection，再由不同动作按资格处理，以便保持统一列表交互。
9. 作为竞品监控用户，我希望批量 lifecycle 操作失败时保留 selection 和 Dialog 状态，以便修正问题后重试。
10. 作为竞品监控用户，我希望 Detail 的单商品停止、恢复、删除入口继续存在，以便需要精确处理单个商品时仍有直接入口。

### 15.2 共通数量和资格

生命周期动作继续使用 generic selection。selection 本身不因 active 状态或 `group_role` 清理，也不为不同动作创建不同 checkbox。

设 `filteredCompetitors` 为当前完整筛选结果，`selectedIds` 为跨分页 selection：

```text
X = selectedIds ∩ filteredCompetitors
Y = selectedIds ∩ filteredCompetitors ∩ is_active=true
Z = selectedIds ∩ filteredCompetitors ∩ group_role=competitor
A = selectedIds ∩ filteredCompetitors ∩ is_active=true
B = selectedIds ∩ filteredCompetitors ∩ is_active=false
D = selectedIds ∩ filteredCompetitors ∩ group_role=competitor
```

其中：

- X 用于批量操作总数；
- Y 用于采集选中，group role 不限制采集；
- Z 用于设置分组；
- A 用于停止监控，own 和 competitor 均允许；
- B 用于恢复监控，own 和 competitor 均允许；
- D 用于永久删除，只允许直接 competitor，active / inactive 均允许；
- N 继续表示完整 `competitors` 中 `is_active=true` 的数量，不受 filter、pagination 或 selection 影响。

Y 与 A 可以相同，这是语义上的自然结果，不增加人为区分规则。

当对应数量为 0 时，动作 disabled：Y、Z、A、B、D 分别独立判断。inactive 不进入采集请求，active 不进入恢复请求，own 不进入分组或删除请求；被排除的商品不是错误，也不触发部分成功提示。

### 15.3 批量操作菜单

最终菜单结构为：

```text
批量操作（X）
────────────
采集选中（Y）
设置分组（Z）
────────────
停止监控（A）
恢复监控（B）
────────────
删除竞品（D）
────────────
采集全部监控中（N）
```

菜单继续是 Competitor List 顶部的单一紧凑 Popover，不新增一排顶部按钮，不改变既有采集和分组菜单的视觉体系。`X` 仍为 filter 下全部 selected，不按当前页、active 或动作资格缩小。

### 15.4 批量停止监控

点击“停止监控（A）”时仅提交当前 filter 下 `is_active=true` 的 selected 商品。selection 中的 inactive 商品不进入 request，也不算错误；own 与 competitor 均可停止。

当 `A = 0` 时按钮 disabled。停止必须打开普通确认 Dialog，不使用高危删除样式：

```text
停止监控 4 个商品？

停止后这些商品将不再参与后续自动采集和手动采集，
已有商品信息、快照、SKU、采集记录和变化历史都会保留。

[取消] [确认停止]
```

取消不发送 request。确认后调用 Monitoring Batch API，request IDs 只包含 A。停止不删除任何历史，不改变商品 `status`、`group_id` 或 `group_role`。

### 15.5 批量恢复监控

点击“恢复监控（B）”时仅提交当前 filter 下 `is_active=false` 的 selected 商品。selection 中的 active 商品不进入 request，也不算错误；own 与 competitor 均可恢复。

当 `B = 0` 时按钮 disabled。恢复是可逆操作，V1 不要求二次确认；点击菜单项后直接提交 Monitoring Batch API，request IDs 只包含 B。

恢复只将 `is_active` 设为 `true`，不立即启动 Playwright，不立即采集。商品在下一次自动采集周期或用户手动采集时重新进入采集范围。

### 15.6 Monitoring Batch API

正式 API：

```http
PATCH /api/competitors/monitoring-batch
Content-Type: application/json
```

停止 request：

```json
{
  "competitor_ids": [1, 2, 3],
  "is_active": false
}
```

恢复 request：

```json
{
  "competitor_ids": [1, 2, 3],
  "is_active": true
}
```

#### Request validation

`competitor_ids` 必填、非空、至少一个；每项必须是严格正整数，bool 必须拒绝；duplicate 去重并保持稳定顺序。非法值整体返回 422，不修改任何商品。

`is_active` 必须是严格 boolean。不得接受 `0`、`1`、`"true"`、`"false"` 或其他隐式 coercion 值；非法值整体返回 422。

任意 ID 不存在时返回整体 404 `competitor_not_found`，错误 body 包含 missing `competitor_ids`。missing 时不得更新其他商品。

#### Atomicity / no-op

完整 request validation 和目标读取完成后，才识别 same-state rows、写入和 commit。若 `competitor.is_active == request.is_active`，该商品是 same-state no-op：

- 不执行 UPDATE；
- 不修改 `updated_at`；
- 不计入 `updated_count`；
- 不进入 response `competitor_ids`。

mixed request 只返回真正状态发生变化的 IDs。例如两个已停止商品和两个监控中商品请求停止时，只更新后两个。全部 no-op 仍返回 200：

```json
{
  "updated_count": 0,
  "competitor_ids": [],
  "is_active": false
}
```

成功 response：

```json
{
  "updated_count": 2,
  "competitor_ids": [3, 4],
  "is_active": false
}
```

`competitor_ids` 只包含真正改变状态的去重 IDs，保持 request 顺序或等价稳定顺序。

#### 写入边界与锁

成功只允许改变：

```text
Competitor.is_active
Competitor.updated_at
```

不得改变 `status`、`group_id`、`group_role`、URL、title、shop、ProductSnapshot、SkuSnapshot、CollectionRun 或 ChangeEvent。own 与 competitor 使用完全相同的 monitoring contract。

Monitoring Batch 不获取 `COLLECTION_LOCK`。即使采集任务正在运行，API 仍按 monitoring contract 更新状态；采集任务实际处理每个 ID 时由既有 per-item active 检查决定后续行为。不新增等待、排队或新的 lock 系统。

### 15.7 批量永久删除资格与保护

“删除竞品（D）”只处理：

```text
D = selectedIds ∩ filteredCompetitors ∩ group_role=competitor
```

active / inactive 的普通 competitor 均可删除。`D = 0` 时按钮 disabled。

own 可以继续被 generic selection 选中，也可以停止或恢复，但：

- 不进入 batch delete request；
- 不删除；
- 不自动解除 own；
- 不自动降级为 competitor；
- 不改变所在组。

如果 selection 中包含 own，删除 Dialog 明确显示：

```text
已选择 8 个商品
本次将永久删除 7 个直接竞品
1 个我方商品不会参与批量删除
```

Frontend request 只发送 D。Frontend 排除 own 是 UX 防线，Backend 必须再次验证。如果直接调用 API 的 request 含 own，整体返回 409：

```json
{
  "code": "own_product_not_batch_deletable",
  "message": "我方商品不能参与批量删除",
  "competitor_ids": [8]
}
```

该错误不得部分删除 competitor，不得删除 own、解除 own 或改变 `group_role`。

### 15.8 Batch Delete API、锁和事务

正式 API：

```http
POST /api/competitors/delete-batch
Content-Type: application/json
```

Request：

```json
{
  "competitor_ids": [1, 2, 3]
}
```

不得循环调用 `DELETE /api/competitors/{id}`。

`competitor_ids` 的输入 validation 与 Monitoring Batch 相同：必填、非空、至少一个、严格正整数、拒绝 bool、duplicate 去重；非法 request 整体返回 422。

Batch Delete 执行顺序固定为：

```text
request 结构 validation
→ 尝试获取 COLLECTION_LOCK
→ 获取失败：409 collection_in_progress
→ 在锁保护内重新读取全部 competitors
→ validate missing IDs
→ validate own IDs
→ 确认 request 整体合法
→ 一个 DB transaction 按依赖顺序删除
→ commit
→ finally release COLLECTION_LOCK
```

在锁保护内重新读取是必须的，不能依赖获取锁前的对象状态。任意 missing 或 own 都使整个 request 失败，不产生部分删除。

对所有 eligible IDs，在同一事务按既有生命周期顺序删除：

1. ChangeEvent；
2. CollectionRun；
3. SkuSnapshot；
4. ProductSnapshot；
5. Competitor。

CompetitorGroup 保留。任何异常 rollback 整个 batch，返回稳定的 500 `competitor_delete_failed`，不得暴露 traceback。批量删除成功后，相同 offerId 仍可以重新添加。

成功 response：

```json
{
  "deleted_count": 3,
  "competitor_ids": [1, 2, 3]
}
```

response IDs 为真正删除的去重 IDs。因为 missing / own 会使整个 request 失败，成功 response 中所有合法目标都应被删除。

### 15.9 Lifecycle Dialog 与刷新行为

停止 Dialog 是普通确认，不使用删除式危险样式；恢复不需要二次确认；删除 Dialog 是明确的不可逆高风险确认，不使用 `window.confirm()`，不要求用户输入 `DELETE`、商品名或其他复杂文本。

删除 Dialog 至少表达：

```text
永久删除竞品

已选择 8 个商品
本次将永久删除 7 个直接竞品
1 个我方商品不会参与批量删除

删除后将同时删除这些竞品的：
- 商品快照
- SKU 快照
- 采集记录
- 变化事件

此操作不可恢复。

[取消] [永久删除 7 个竞品]
```

没有 own 时不显示“0 个我方商品”。

停止 / 恢复 / 删除成功后均：

1. 关闭对应 Dialog（恢复没有 Dialog）；
2. 清空 selection；
3. 按真实 response 数量显示 Toast；
4. 重新读取权威数据。

成功文案：

- 停止 `updated_count > 0`：`已停止监控 4 个商品`；
- 停止全部 no-op：`所选商品均已停止监控，无需修改`；
- 恢复 `updated_count > 0`：`已恢复监控 3 个商品`；
- 恢复全部 no-op：`所选商品均在监控中，无需修改`；
- 删除：`已永久删除 7 个竞品`。

不显示假数量，不把 no-op 显示为“修改 0 个”。刷新至少覆盖 Competitor List、Dashboard、Groups / Group Summary 和 Group Attention，复用现有 read seam。

失败时：

- 停止 Dialog 保持打开；
- 删除 Dialog 保持打开；
- 停止 / 恢复 / 删除 selection 保留；
- 保留可重试的错误；
- 不假装部分成功；
- 不因失败强制刷新成未知状态。

恢复是直接操作，失败使用 Toast 或页面反馈显示错误，selection 不清空。删除成功导致页数减少时继续使用现有 pagination 规则：当前页仍合法则保持，页数缩减才 clamp，不无条件回到第 1 页。

### 15.10 Detail 单商品生命周期与兼容关系

以下 Detail 能力继续保留且不改变：

- 停止监控；
- 恢复监控；
- 永久删除竞品。

既有单商品 API 继续存在：

```text
PATCH /api/competitors/{id}/monitoring
DELETE /api/competitors/{id}
```

单商品操作仍由 Competitor Detail 承担，多商品操作由 Competitor List / 批量操作承担。Batch APIs 不取代单商品 API，不改变 Detail 的确认、错误和历史保留语义。
