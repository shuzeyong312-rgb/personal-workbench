# 手动添加 1688 竞品 Spec

## 1. Goal

允许唯一用户手动粘贴 1688 商品链接，系统提取 offerId，校验未重复后创建一个 Competitor。

本功能只完成竞品登记，不触发采集、不生成快照、不做分析。

## 2. User Flow

1. 用户打开“添加竞品”界面。
2. 粘贴一个 1688 商品链接。
3. 点击“添加”。
4. 系统解析链接并提取 offerId。
5. 系统校验链接有效性及 offerId 是否已存在。
6. 校验通过后创建 Competitor。
7. 页面显示添加成功及竞品基本信息。
8. 如果重复或无效，页面显示对应错误，不创建数据。

## 3. Inputs

必填：

- url：用户粘贴的 1688 商品链接。

第一版 UI 只提供：

- 1688 商品链接输入框；
- 添加按钮。

API 保留以下可选字段：

- group_id：本 Feature 只允许 omitted 或 null，默认使用 null。当前 UI 不提供竞品组选择器。
- 非 null group_id 不属于本 Feature 支持范围，留待后续竞品组 Feature 处理。

不输入：

- 商品标题；
- 店铺名称；
- 价格；
- SKU；
- 快照；
- 采集配置。

## 4. Business Rules

1. platform 固定为 1688。
2. 仅支持以下链接格式：

   https://detail.1688.com/offer/{offerId}.html

3. 链接允许携带 Query 参数，例如 ?offerId=...&spm=...。
4. 暂不支持短链接、移动端链接或其他域名。
5. offerId 只接受纯数字，数据库按字符串保存。
6. 系统必须从链接中提取 offerId。
7. 保存 URL 时统一标准化为：

   https://detail.1688.com/offer/{offerId}.html

   Query 和 Fragment 必须移除。
8. 同一个 platform + offer_id 只能存在一个 Competitor。
9. 重复添加不能创建新记录。
10. 添加成功后创建 Competitor。
11. 新建竞品默认处于监控状态，即 is_active = true。
12. 初始尚未采集商品资料，因此标题、店铺、主图等字段为空。
13. status 正式允许的值为：unknown、active、offline。
14. 新添加但尚未采集的商品，status = unknown。
15. 本 Feature 的 group_id 只允许为 NULL；竞品组关联留待后续 Feature。
16. 添加操作不触发 Playwright，不访问 1688 商品详情页。
17. 添加操作不创建 ProductSnapshot、CollectionRun 或 ChangeEvent。
18. 不通过前端判断唯一性，数据库唯一约束必须作为最终兜底。

## 5. Validation

### URL 校验

- 输入不能为空。
- 必须是合法 URL。
- Scheme 必须为 https。
- Host 必须为 detail.1688.com。
- 不允许 userinfo。
- 端口必须省略或为 HTTPS 默认端口 443。
- Path 必须匹配 /offer/{offerId}.html。
- offerId 必须为纯数字。
- 允许存在 Query 和 Fragment，但标准化保存时必须移除。
- 不支持短链接、移动端链接或其他域名。
- 无法提取 offerId 时拒绝创建。

### 重复校验

- 根据 platform + offer_id 查询现有 Competitor。
- 已存在时返回重复错误。
- 并发或重复请求导致数据库唯一约束冲突时，也转换为明确的重复错误。

### 数据校验

- group_id 为空时允许创建。
- 本 Feature 不接受非 null group_id；不创建 CompetitorGroup model/table，也不实现竞品组查询。
- 不接受用户提交的标题、价格等未经采集的数据作为初始事实。

## 6. Data Changes

只新增或使用 Competitor 数据。

初始字段：

    platform          = "1688"
    offer_id          = 从链接提取的纯数字字符串
    url               = https://detail.1688.com/offer/{offerId}.html
    group_id          = null（非 null 值留待后续竞品组 Feature）
    title             = null
    shop_name         = null
    main_image_url    = null
    status            = "unknown"
    is_active         = true
    created_at        = 当前时间
    updated_at        = 当前时间
    last_collected_at = null

数据库约束：

    UNIQUE(platform, offer_id)

group_id 正式定义为 nullable。当前尚无正式 CompetitorGroup 表，因此直接按可空字段创建，不需要先做修改 migration。

## 7. API Contract

### 创建竞品

    POST /api/competitors
    Content-Type: application/json

请求：

    {
      "url": "https://detail.1688.com/offer/123456789.html?spm=abc",
      "group_id": null
    }

成功响应：

    201 Created

    {
      "id": 1,
      "platform": "1688",
      "offer_id": "123456789",
      "url": "https://detail.1688.com/offer/123456789.html",
      "group_id": null,
      "status": "unknown",
      "is_active": true,
      "created_at": "2026-09-19T10:00:00Z"
    }

错误：

- 400 Bad Request：URL 为空、格式错误、域名不支持或无法提取 offerId。
- 409 Conflict：该 offerId 已添加。
- 500 Internal Server Error：未预期的服务端错误。

具体错误响应至少应包含稳定的错误类型和用户可读信息，例如：

    {
      "code": "competitor_already_exists",
      "message": "该 1688 商品已经添加"
    }

## 8. UI States

1. 初始空表单：
   - 显示 1688 商品链接输入框；
   - 不显示竞品组选择器；
   - 添加按钮可用。
2. 输入中：
   - 展示用户当前输入；
   - 不提前触发采集。
3. 提交中：
   - 禁用提交按钮；
   - 显示正在校验或添加。
4. 添加成功：
   - 显示已添加；
   - 显示提取出的 offerId；
   - 显示标准化后的 URL；
   - 清空表单或允许继续添加。
5. 链接无效：
   - 明确提示仅支持指定格式的 1688 商品链接；
   - 保留用户输入，允许修改后重试。
6. offerId 重复：
   - 明确提示该商品已经添加；
   - 不创建新记录。
7. 服务端异常：
   - 显示通用失败提示；
   - 不伪造成功状态。

## 9. Acceptance Criteria

1. 输入符合指定格式的 1688 商品链接后，可以提取正确的 offerId。
2. 带 Query 或 Fragment 的有效链接可以成功处理。
3. 首次提交有效链接后，创建一条 Competitor。
4. 创建记录的 platform 为 1688。
5. offer_id 以纯数字字符串保存。
6. 保存的 URL 始终为 https://detail.1688.com/offer/{offerId}.html，不包含 Query 或 Fragment。
7. group_id 为 null 时可以成功创建。
8. 同一 offerId 再次提交时返回重复错误。
9. 重复提交不会新增第二条 Competitor。
10. 空链接不能提交成功。
11. 非 https、非 detail.1688.com、不匹配指定路径或无法提取 offerId 的链接不能提交成功。
12. 不会因为添加竞品而触发 Playwright。
13. 不会创建快照、采集记录或变化记录。
14. 初始未采集字段保持为空，status 为 unknown，不填充猜测值。
15. 前端具备 Loading、Success、Validation Error、Duplicate、Server Error 状态。
16. 前端不提供竞品组选择器，API 的 group_id 只允许 omitted 或 null。
17. 数据库唯一约束能够阻止重复 platform + offer_id。

## 10. Non-goals

本次不做：

- Playwright 自动采集；
- 商品标题、店铺、价格、SKU 提取；
- 竞品组创建或管理；
- UI 竞品组选择器；
- Dashboard；
- 历史快照；
- 变化分析；
- 每日调度；
- 商品详情页访问；
- 多用户；
- 权限系统；
- 1688 以外的平台；
- 短链接、移动端链接及其他域名链接；
- 批量导入；
- 竞品编辑、删除、停用；
- 自动标准化商品信息以外的扩展能力。

## 11. Confirmed

- 用户只有一个人。
- 用户手动粘贴 1688 商品链接。
- 仅支持 https://detail.1688.com/offer/{offerId}.html。
- 允许链接携带 Query 参数。
- 暂不支持短链接、移动端链接、其他域名。
- offerId 只接受纯数字，数据库按字符串保存。
- 保存 URL 统一去除 Query 和 Fragment。
- 系统需要提取 offerId。
- 相同 1688 offerId 不能重复添加。
- 添加成功后保存为 Competitor。
- 本 Feature 的 group_id 只允许 omitted 或 NULL；非 NULL group_id 留待后续竞品组 Feature。
- 第一版 UI 不提供竞品组选择器。
- 新添加但尚未采集的商品 status = unknown。
- status 正式允许 unknown、active、offline。
- 不触发 Playwright 自动采集。
- 不做 Dashboard。
- 不做历史快照。
- 不做变化分析。
- 项目使用 React、FastAPI、SQLAlchemy、Alembic、SQLite。
- 业务规则应由后端 Service 负责。
- Schema 变更必须通过 Alembic migration。

## 12. Assumptions

- 初始竞品默认 is_active = true。
- 尚未采集的标题、店铺、主图等字段为空。
- 当前阶段不要求验证商品链接实际可访问，只要求验证格式并提取 offerId。
- 本垂直切片的 UI 固定提交 null，CompetitorGroup 由后续 Feature 实现。

## 13. Unknowns

本 V1 Spec 的原有 5 个 Unknown 已全部冻结为正式规则，不保留待实现判断项：

- 链接格式已冻结；
- offerId 格式已冻结；
- URL 标准化规则已冻结；
- group_id nullable 已冻结；
- status 枚举及初始值已冻结。
