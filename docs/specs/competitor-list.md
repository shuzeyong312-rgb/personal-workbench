# 竞品列表 Feature Spec

## 1. Goal

正式建立 Personal Workbench 的“竞品列表”页面，作为 `ui-system.md` 中 List Reference Page 的首次真实落地。

用户可以：

- 查看已添加的全部竞品；
- 查看当前已保存的竞品基础信息；
- 通过列表页添加新的 1688 竞品；
- 添加成功后立即在列表中看到新竞品。

当前阶段不触发采集、不生成快照；搜索与筛选仅在前端本地完成，不实现服务端搜索、排序或复杂分页。

## 2. User Flow

### 查看竞品列表

1. 用户进入 Personal Workbench。
2. 通过左侧导航进入“竞品监控 → 竞品列表”。
3. 页面加载竞品数据。
4. 用户查看列表统计和竞品表格。
5. 对尚未采集的数据展示“未采集”。

### 添加竞品

1. 用户点击 PageHeader 右侧“添加竞品”。
2. 页面打开 Dialog。
3. 用户粘贴 1688 商品链接。
4. 用户提交表单。
5. 前端调用 `POST /api/competitors`。
6. 添加成功后：
   - 关闭 Dialog；
   - 清空表单；
   - 刷新竞品列表；
   - 新竞品出现在列表中；
   - 显示成功反馈。
7. 如果链接无效、竞品重复或服务异常：
   - Dialog 保持打开；
   - 保留用户输入；
   - 显示对应错误；
   - 不刷新为错误数据。

## 3. Page Structure

页面使用 List Reference Page 结构：

```text
左侧分级导航
↓
Breadcrumb
↓
PageHeader + 添加竞品
↓
搜索 / 筛选视觉骨架
↓
列表统计
↓
竞品列表 Table
↓
Pagination 视觉骨架
```

### 左侧导航

品牌区：

- 个人工作台
- 工作提效工具集

导航项：

- 首页
- 竞品监控
  - 竞品监控大屏
  - 竞品列表
  - 竞品分组
  - 采集记录
- 自动上架
- 系统设置

当前状态：

- “竞品监控”展开；
- “竞品列表”高亮；
- 其他尚未实现的页面显示为未启用入口，不进入未实现的业务页面。

### Breadcrumb

```text
个人工作台 / 竞品监控 / 竞品列表
```

### PageHeader

标题：

```text
竞品列表
```

说明：

```text
查看当前已添加的 1688 竞品，并管理监控对象。
```

主要操作：

```text
添加竞品
```

### 搜索 / 筛选区域

启用以下控件：

- 商品名称 / offerId / 店铺搜索输入框；
- 商品状态筛选：全部状态、在售、已下架、状态未知；
- 采集状态筛选：全部状态、已采集、未采集；
- 竞品组筛选：全部竞品组、未分组和当前已加载的竞品组；
- 重置按钮。

搜索同时匹配 `title`、`offer_id`、`shop_name`，trim 首尾空格，支持部分匹配，title / shop_name 大小写不敏感，null 安全处理；不搜索 URL、竞品组或其他字段。

商品状态直接匹配 `status`：在售为 `active`、已下架为 `offline`、状态未知为 `unknown`。采集状态只使用 `last_collected_at`：已采集为非 null，未采集为 null。

搜索词、商品状态、采集状态和竞品组使用 AND。所有控件变化后立即基于本地数据更新结果；“重置”清空四个条件并恢复全部竞品。

竞品组“全部竞品组”不限制 `group_id`，“未分组”匹配 `group_id = null`，指定竞品组匹配对应的 `group_id`。筛选在前端基于一次加载的 `competitors` 本地派生，不发送搜索或筛选请求，不实现服务端搜索、复杂搜索或 debounce。

### 列表统计

至少显示：

- 当前竞品总数；
- 当前已采集数量；
- 当前未采集数量。

统计数据必须来自实际列表数据，不写死示例数字。

### Table

建议列：

1. 商品信息
2. 店铺名称
3. 当前价格
4. SKU 数量
5. 最近变化
6. 最近采集时间
7. 商品状态

商品信息列包含：

- 主图缩略图；无主图时显示占位状态；
- 商品标题；未采集时显示“未采集”；
- offerId；
- 1688 商品链接。

操作列提供详情、立即采集和生命周期“更多”菜单；停止、恢复和永久删除规则见 `competitor-lifecycle.md`。

### Pagination

保留分页区域的视觉位置。

本阶段：

- 不实现分页请求；
- 默认展示全部竞品；
- 当列表数量不足时显示禁用状态或“暂无分页”；
- 不引入分页参数、分页组件逻辑或复杂分页 API。

## 4. Data Requirements

### API 返回字段

`GET /api/competitors` 只返回当前真实存在的数据字段：

- `id`
- `platform`
- `offer_id`
- `url`
- `title`
- `shop_name`
- `main_image_url`
- `status`
- `is_active`
- `created_at`
- `last_collected_at`

### 前端列表展示字段

列表仍保留以下列：

- 当前价格；
- SKU 数量；
- 最近变化。

由于当前 API 不提供这些字段，前端固定展示：

```text
未采集
```

不新增 `price`、`sku_count`、`latest_change` API 字段，也不通过前端推断数据。

### 字段展示规则

| 字段 | 类型 | 展示规则 |
|---|---|---|
| `id` | number | 内部记录标识，不必作为主要展示字段 |
| `platform` | string | 当前固定为 `1688` |
| `offer_id` | string | 展示商品 offerId |
| `url` | string | 作为 1688 商品链接 |
| `title` | string \| null | null 时显示“未采集” |
| `shop_name` | string \| null | null 时显示“未采集” |
| `main_image_url` | string \| null | null 时显示图片占位 |
| `status` | string | 展示为状态 Badge |
| `is_active` | boolean | 当前用于确认是否处于监控状态 |
| `created_at` | datetime | 作为列表排序依据，不提供用户排序操作 |
| `last_collected_at` | datetime \| null | null 时显示“未采集” |

### 状态语义

- `unknown`：尚未确认商品状态，通常对应未采集；
- `active`：商品当前状态为正常；
- `offline`：商品当前状态为下架或失效；
- `last_collected_at = null`：显示“未采集”。

列表统计和表格数量基于当前筛选结果；系统有竞品但筛选结果为空时显示“没有找到符合条件的竞品”和“请调整搜索词或筛选条件”，不显示“还没有添加竞品”。

每次 `filteredCompetitors` 变化时，selectedIds 只保留当前结果中仍可见且 `is_active=true` 的竞品；被隐藏或 inactive 的竞品自动移出。表头全选只选择当前筛选结果中的 active 竞品。采集全部监控中继续基于全部 `competitors` 中的 active 竞品计数，不受筛选结果影响。

不得将未采集商品展示为 `active`，也不得把缺失值显示为 0。

## 5. API Contract

### 获取竞品列表

```http
GET /api/competitors
```

本阶段不支持：

- `page`
- `page_size`
- `sort`
- `search`
- `status`
- `group_id`

正式排序规则固定为：

```text
created_at DESC, id DESC
```

成功响应：

```http
200 OK
Content-Type: application/json
```

```json
[
  {
    "id": 1,
    "platform": "1688",
    "offer_id": "123456789",
    "url": "https://detail.1688.com/offer/123456789.html",
    "title": null,
    "shop_name": null,
    "main_image_url": null,
    "status": "unknown",
    "is_active": true,
    "created_at": "2026-09-19T10:00:00Z",
    "last_collected_at": null
  }
]
```

规则：

- 返回所有已创建的竞品；
- 按 `created_at DESC, id DESC` 返回；
- 不返回 `price`；
- 不返回 `sku_count`；
- 不返回 `latest_change`；
- 前端对应列固定展示“未采集”；
- 空列表返回 `[]`；
- 不触发 Playwright；
- 不访问 1688 商品详情页；
- 不生成 ProductSnapshot、CollectionRun 或 ChangeEvent。

### 添加竞品

继续使用现有接口：

```http
POST /api/competitors
Content-Type: application/json
```

请求：

```json
{
  "url": "https://detail.1688.com/offer/123456789.html",
  "group_id": null
}
```

成功：

```http
201 Created
```

添加成功后前端必须重新请求 `GET /api/competitors`，不依赖本地拼接数据作为唯一列表来源。

错误：

- `400 invalid_competitor_url`
- `400 group_not_supported`
- `409 competitor_already_exists`
- 其他服务端错误

错误响应继续使用现有稳定结构：

```json
{
  "code": "competitor_already_exists",
  "message": "该 1688 商品已经添加"
}
```

## 6. UI States

### 列表状态

#### Loading

- 显示表格骨架或加载状态；
- 禁止误显示为空列表；
- 添加按钮可以暂时禁用，避免数据状态混乱。

#### Empty

- 显示明确空状态；
- 文案说明当前尚未添加竞品；
- 提供“添加竞品”操作；
- 不显示示例商品、示例价格或示例日期。

#### Error

- 显示列表加载失败；
- 提供“重试”操作；
- 不显示过期或伪造数据。

#### Normal

- 显示真实竞品列表；
- 空字段显示“未采集”或对应占位状态；
- 状态使用统一 Badge；
- 统计数据与实际列表一致。

### 添加 Dialog 状态

#### Initial

- 显示 1688 商品链接输入框；
- 不显示竞品组选择器；
- 提交按钮可用。

#### Submitting

- 禁止重复提交；
- 显示“正在校验并保存…”；
- 保留当前输入。

#### Success

- 关闭 Dialog；
- 清空表单；
- 刷新列表；
- 显示成功 Toast；
- 新记录立即可见。

#### Invalid

- 保留输入；
- 提示仅支持指定格式的 1688 商品链接；
- 允许修改后重试。

#### Duplicate

- 保留输入；
- 提示该商品已经添加；
- 不关闭 Dialog；
- 不新增记录。

#### Server Error

- 保留输入；
- 显示通用失败提示；
- 允许重试；
- 不伪造成功状态。

## 7. Add Competitor Integration

现有“添加 1688 竞品”临时页面不再作为独立正式入口。

本次改为：

- 竞品列表页提供唯一正式的“添加竞品”入口；
- 采用 Dialog 承载现有添加表单；
- 复用现有 `POST /api/competitors`；
- 不重新设计添加规则；
- 不增加竞品组选择器；
- 不增加采集或详情访问；
- 添加成功后重新获取列表数据。

Dialog 只负责输入与提交，不负责：

- 解析商品详情；
- 调用 Playwright；
- 生成快照；
- 计算变化；
- 创建竞品组。

## 8. Navigation Behavior

当前可用页面：

```text
竞品监控 / 竞品列表
```

当前高亮：

```text
竞品列表
```

其他导航入口：

- 可以显示；
- 不实现对应业务页面；
- 不显示虚假的统计或列表数据；
- 不触发未实现 API；
- 点击行为应明确为未开放、禁用，或由统一占位处理；
- 不因导航入口存在而扩大本 Feature 范围。

建议当前正式页面路径使用：

```text
/competitors
```

如果项目已有路由约定，应优先复用既有约定。

## 9. Acceptance Criteria

### 页面与导航

1. 用户可以从 Personal Workbench 进入“竞品监控 → 竞品列表”。
2. 页面包含左侧分级导航。
3. 品牌区显示“个人工作台 / 工作提效工具集”或等价文案。
4. 当前“竞品列表”入口明显高亮。
5. 页面包含 Breadcrumb。
6. 页面包含 PageHeader。
7. 页面整体遵循浅色、蓝紫雾感、轻毛玻璃、柔和阴影和统一圆角体系。
8. 页面结构符合 List Reference Page。

### 列表

9. 页面调用 `GET /api/competitors`。
10. 返回的全部竞品都可以展示。
11. 空列表显示正式 Empty State。
12. 加载中显示 Loading State。
13. 请求失败显示 Error State 和重试入口。
14. `title`、`shop_name`、`last_collected_at` 缺失时显示“未采集”或等价空值状态；当前价格、SKU 数量、最近变化列始终显示“未采集”，且不依赖虚假的 API 字段。
15. `GET /api/competitors` 的返回顺序固定为 `created_at DESC, id DESC`。
16. `main_image_url` 缺失时显示占位图，不显示破损图片。
17. `status` 使用统一 Badge。
18. 统计数量来自真实 API 数据。
19. 不写死商品名称、价格、日期、数量或示例图片。
20. 不触发 Playwright。
21. 不生成快照、采集记录或变化记录。

### 添加

22. PageHeader 提供“添加竞品”主要操作。
23. 点击后打开 Dialog。
24. Dialog 复用现有添加接口和校验规则。
25. 提交中禁止重复提交。
26. 添加成功后关闭或重置 Dialog。
27. 添加成功后刷新列表。
28. 添加成功后用户可以立即看到新竞品。
29. 无效链接显示明确错误。
30. 重复商品显示明确错误。
31. 服务异常不显示成功状态。
32. 添加失败时保留用户输入。
33. 不提供竞品组选择器。
34. 添加操作不访问 1688 商品详情页。

### 范围

35. 不实现 Dashboard。
36. 不实现竞品详情。
37. 不实现竞品分组。
38. 不实现采集记录。
39. 立即采集只对监控中的竞品可用。
40. 本页面不实现编辑或批量操作；生命周期操作按 `competitor-lifecycle.md` 执行。
41. 不实现复杂搜索、服务端搜索、排序或分页；搜索和筛选仅限本地列表结果。

## 10. Non-goals

本次不做：

- Playwright 采集；
- 新的采集架构；
- 商品详情页；
- Dashboard；
- 竞品分组；
- 采集记录；
- 历史快照；
- 变化检测；
- 趋势图；
- 编辑竞品；
- 批量操作；
- 复杂分页；
- 服务端搜索；
- 高级筛选（日期、OR 等）；
- 自动上架；
- 系统设置；
- 多平台支持；
- 新增数据库实体；
- 新增采集字段；
- 新的视觉体系；
- 新的第三方依赖。

## 11. Confirmed

- 当前 Feature 名称为“竞品列表”。
- 项目使用 React、TypeScript、Vite、FastAPI、SQLAlchemy、SQLite。
- 当前已存在 `POST /api/competitors`。
- 当前已支持手动添加 1688 竞品。
- 当前已存在 Competitor 数据表。
- 本次新增 `GET /api/competitors`。
- `GET /api/competitors` 只返回当前真实存在的字段。
- `GET /api/competitors` 正式按 `created_at DESC, id DESC` 排序。
- 列表不实现复杂分页、用户排序或服务端搜索；提供基于一次加载数据的本地搜索和筛选，其中排序规则固定为 API 的 `created_at DESC, id DESC`。
- 列表不触发 Playwright。
- 列表不生成快照。
- 当前主要真实字段为 `id`、`offer_id`、`url`、`platform`、`status`、`is_active`、`created_at`。
- `title`、`shop_name`、`main_image_url`、`last_collected_at` 允许为空。
- 当前价格、SKU 数量、最近变化只由前端展示“未采集”，不建立对应 API 字段。
- 页面必须使用 List Reference Page。
- 页面必须包含左侧分级导航。
- 页面必须包含品牌区、首页、竞品监控层级、自动上架和系统设置入口。
- 当前页面必须包含 Breadcrumb、PageHeader、搜索/筛选视觉骨架、列表统计、Table 和 Pagination 视觉骨架。
- 只有真实可用的功能可以交互。
- 添加竞品必须整合到竞品列表页。
- 添加成功后必须关闭或重置添加界面并刷新列表。
- 不实现 Dashboard、竞品分组、采集记录、自动上架和系统设置业务页面。
- 不把 Reference Page 的示例数据写入正式业务逻辑。

## 12. Assumptions

- 列表 API 返回数组，不引入分页响应包装。
- `GET /api/competitors` 只返回当前真实存在的数据字段。
- 当前价格、SKU 数量、最近变化只作为前端展示列存在，不建立对应 API 字段。
- 当前竞品列表默认一次加载全部竞品。
- 列表排序固定为 `created_at DESC, id DESC`。
- 当前不增加数据库字段，也不增加虚假的 API 投影字段。
- 未实现的导航入口使用禁用或占位行为，不创建虚假页面。
- 当前不新增前端状态管理库、表格库、分页库或 UI 依赖。

## 13. Unknowns

以下内容不阻塞本次 Feature，但不得在本次实现中自行固化为未来业务规则：

- 未来高级搜索和筛选规则；
- 未来分页的默认页大小；
- 未来竞品详情页的路由和操作；
- 未来价格、SKU 数量和最近变化的真实数据来源；
- 未来是否支持竞品分组筛选；
- 未来是否允许编辑或停用竞品；
- 未来导航入口的正式占位页内容。

这些问题留待对应 Feature Spec 冻结后处理。
