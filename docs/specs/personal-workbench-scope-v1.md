# 个人工作台第一阶段：收敛到竞品监控与采集

- 状态：草稿，待独立 Spec Review
- 风险：L，涉及现有 SQLite 的不可逆数据删除与共享入口调整
- 源码基线：`codex/product-library-v2-simple-implementation` 的 `9a63160a3b8041d538b85efe543ccca632364e3d`

## 目标与范围

公司自研网站已经覆盖产品库、客户报价和客户触达。个人工作台第一阶段保留 1688 竞品监控和采集，移除这三项重复业务及其在本地工作库中的数据。新增个人工具与公司网站集成留待后续决定。

| 保留 | 退出 |
| --- | --- |
| 监控大屏、我方商品、竞品列表和详情、竞品分组和组内比较 | 产品库、厂家资料维护、导入、归档和恢复 |
| 添加监控链接、手动与定时采集、采集任务和记录、现有任务通知 | 采购来源、价格版本和证据、客户报价计算与 Excel 导出 |
| 店铺识别、采集策略及其依赖的工作浏览器、全局搜索中的保留入口 | 客户触达任务和活动、模拟与桌面执行、启动时的任务恢复 |
| “个人工作台”名称和现有技术架构 | 首阶段导航中的 AI 助手、全网比价、自动询价、自动上架占位入口 |

“我方商品”和组内的“展示报价”是监控对象及 1688 快照字段，继续使用原有的数据和业务规则。独立工具箱分支暂缓整合，本机已有的 `toolbox_items` 数据保留。

## 页面、API 与运行逻辑

1. 将现有竞品监控大屏设为打开应用后的默认落点和工作台根导航目标，复用原组件和交互。清理旧首页的产品库卡片和未启用入口。保留我方商品、竞品、分组、采集记录及设置的现有导航。
2. 从侧边栏、设置规划、快捷键搜索和页面状态中移除退出模块。`WorkspaceTools.tsx` 取消对 `/api/product-library/products` 的查询及商品结果，保留现有页面和设置搜索、采集任务通知与跳转。
3. 删除退出模块的前端组件、专用样式及活跃后端业务代码。`main.py` 移除 `/api/product-library` 和 `/api/customer-reach` 路由、产品库专用校验错误分支，以及客户触达启动恢复调用。原端点不再出现在 OpenAPI 中，访问已退役 API 返回 404。
4. 按调用关系更新测试和文档。调整 `test_work_browser.py` 等保留模块测试对客户触达启动逻辑的替身。核对 `openpyxl`、`Pillow` 等依赖，确认没有保留路径或历史迁移使用后再移除。旧 Spec、已发布迁移及其必要辅助代码作为历史保留，`20261030_22` 当前会导入 `library_history_archive.py`。

## 数据删除与迁移

2026-11-23 以只读方式检查了仓库默认工作库 `backend/data/personal_workbench.db`。实际 revision 为 `20261029_21`，`quick_check` 为 `ok`，外键检查无异常。按 `20261030_22` 的条件读取，未发现重复商品身份或旧批发价回填冲突。当前分支迁移头为 `20261030_22`，亦需支持已升级到该版本的库。实施时重新核对目标库与 revision。

### 删除清单

使用固定表名清单。下列以逗号分隔的名称是完整表名。

| 来源 | 删除对象 |
| --- | --- |
| 产品库原表与导入回执 | `library_product_prices`、`library_product_variants`、`library_product_sources`、`library_imports`、`library_products_legacy`、`library_products` |
| 简化版商品来源与报价链 | `library_simple_quote_evidence`、`library_simple_eligibility_audit`、`library_simple_source_events`、`library_simple_product_events`、`library_simple_quote_versions`、`library_simple_quote_keys`、`library_simple_sources` |
| `22` 迁移生成的历史副本 | `library_products_history_snapshot`、`library_product_variants_history_snapshot`、`library_product_sources_history_snapshot`、`library_product_prices_history_snapshot`、`library_imports_history_snapshot`、`library_history_manifest` |
| 客户触达 | `customer_reach_campaigns`、`customer_reach_tasks` |

表所属索引、触发器随表清除。核查共享设置、浏览器存储和仓库数据目录是否另有退出模块专属持久数据，仅按已确认的键或文件路径处理。用户自行存放的资料、已下载的报价文件、已有备份、浏览器 Profile 和公司网站数据超出本期删除边界。此处的删除指工作库中的业务对象和记录，不承诺对存储介质做取证级擦除。

保留 `competitor_groups`、`competitors`、`product_snapshots`、`sku_snapshots`、`collection_runs`、`collection_batches`、`collection_batch_items`、`collection_add_inputs`、`operating_metric_observations`、`change_events`、`system_settings` 和 `toolbox_items`。当前工作库已核对外键，保留表没有引用退出模块表。实施时需再以实际 schema 检查跨范围引用，包括外键和附着于保留表的对象。

### 升级与恢复

- 在 `20261030_22` 后追加一条向前迁移，沿用 Alembic 的 SQLite 写事务。一次升级将 `21` 经 `22` 推进至退役 revision，`22` 直接推进。`22` 在 `21` 路径中生成的快照也在同一事务内删除。保持旧迁移可重放，禁止通过修改 revision 标记跳过校验。
- 启用外键检查，依赖表先于被引用表删除，例如证据与审计先于报价版本，报价版本先于报价键，价格先于旧商品及来源。发现未知结构、保留对象引用退出表、历史升级失败或完整性异常，整体升级回滚，保留原 revision。不得通过清洗即将退役的数据绕过现有校验。
- 落地前先用临时库和工作库副本演练。在切换窗口停止应用和所有写入方，使用 SQLite 在线备份接口生成临时恢复点并验证能打开及恢复。此恢复点仅用于失败恢复，切换验证通过后清理本次创建的恢复点和演练副本。出现异常时，在恢复写入之前用匹配旧代码的恢复点还原。退役迁移不提供会伪装恢复成功的空表 downgrade。
- `dev.ps1` 当前启动前自动执行 `alembic upgrade head`。实施须避免常规启动对已存在工作库静默触发退役迁移，在明确的切换步骤完成升级与验证后再按正常方式启动。

## 验收

| 场景 | 通过条件 |
| --- | --- |
| 典型旧库与已升级库 | 分别以含数据的 `21`、`22` 运行升级，覆盖产品、导入回执、报价证据、历史副本、触达任务与活动。升级后目标对象全部消失。单独验证空库可从头建成。 |
| 保留数据与完整性 | 比对升级前后保留表的内容、键和约束，保留组绑定、历史快照、采集记录、设置和工具箱数据。`integrity_check` 通过且 `foreign_key_check` 为空。 |
| 失败与恢复 | 注入中途 DDL 失败，验证原表、数据和 revision 留存。旧价格冲突或未知跨范围依赖等异常应拒绝迁移。使用恢复点另行验证旧版本可读。 |
| 页面与 API | 桌面和窄屏打开即进入监控大屏，侧栏、设置和搜索只暴露保留入口。搜索不请求退役 API。OpenAPI 无退役路由，已知旧端点返回 404，应用启动不恢复触达任务。 |
| 监控和采集回归 | 在 fixture 与 mock 中验证添加链接、分组与组内比较、手动和定时调度、任务恢复与记录、通知跳转、工作浏览器设置。保留历史有效数据及未知状态的现有处理。 |

实施验证包括后端全量 pytest、前端 Vitest、Typecheck、Build 和涉及启动脚本时的 PowerShell 检查。人工浏览器验收使用隔离环境。产品范围、迁移和故障恢复通过独立 Spec Review 后进入实施。

参考 [现有工作台合同](workbench-experience-v1.md)、[采集触发合同](collection-trigger-unification-v1.3.md)、[自动采集策略](daily-auto-collection-strategy-v2.md)、[产品库简化版合同](product-library-v2.md)及[工作浏览器合同](work-browser-issue-3.md)。本草稿通过审查并实施后，替代这些历史合同中涉及本期退役入口和业务的条款。
