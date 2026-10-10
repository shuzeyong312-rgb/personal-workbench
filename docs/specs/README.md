# Spec 状态索引

核对日期：2026-10-08。基线：`main` 的 `4822b4a`（本轮纯文档治理前），当前 ORM、API、Frontend、12 条 Alembic revision 和 Git 历史。索引覆盖现有全部 **30 份 Spec**，不改写冻结业务正文，不删除或重命名历史合同。

## 阅读顺序与优先级

1. [协作方式](../roadmap/vibe%20coding协作方式.md)：角色、Spec Review / Freeze、验证与 Git 授权。
2. [产品](../product.md)、[架构](../architecture.md)、[数据模型](../data-model.md)、[UI 规范](../ui-system.md)、[开发规则](../coding-rules.md)：当前稳定事实与全局约束。
3. 本索引 → 对应业务当前合同 → 被引用的旧合同未被替代部分。不要按文件名版本号或旧“待实现”字样判断是否需要重新开发。
4. [重构计划书](../roadmap/competition-intelligence-restructuring-plan.md) 与 [历史 roadmap](../roadmap/competition-intelligence-roadmap.md)：未来顺序、判断与历史背景；research 只提供来源证据，不是生产合同。

规则优先级：本轮明确授权/范围 → 已 Review / Freeze 的适用正式 Spec（后续明确变更条款覆盖旧条款，其余继承）→ 长期文档全局规范 → roadmap / research。新 Spec 的存在或较晚时间不自动证明已经 Freeze / 实施；代码是核实当前行为的证据，不自动授予改写冻结合同的权力。发现未解释的实现冲突应报告并核验，不能用索引自行创造新规则。

当前关键覆盖链：

- 身份/添加/归组：`own-product-role-binding` → `own-product-management-v1`。身份用 ownership，分组用 group_id，兼容角色用 group_role。
- Dashboard：`dashboard-today` / `dashboard-daily-change-aggregation` / `dashboard-group-entry-v1` → `group-first-dashboard-v1`；Header 经批量操作 Spec 调整后，最终由 `own-product-management-v1` 再更新。
- 列表：`competitor-list` → `competitor-list-pagination-v1` → `competitor-list-batch-actions-v1` → `own-product-management-v1`（统一添加/采集入口回到大屏）。
- 采集：`batch-collection` → `batch-collection-auto-resume-v1` → `competitor-monitoring-settings-v1`；`daily-collection` → `daily-auto-collection-strategy-v1`。Runtime 与 CollectionRun 不是同一种历史。
- 设置：我方店铺设置 + 五项 Batch 配置 → 九项完整配置 → `system-settings-visual-refresh-v1`（仅控件/外观，业务不变）。
- 组分析：`group-intelligence` → `group-detail-v1` → 已实施的 `group-competitive-position-v1`，身份叠加 `own-product-management-v1`；Group Detail V2 尚无实施合同。

## 分类含义

| 状态 | 如何使用 |
| --- | --- |
| 当前有效 | 仍是对应能力的主要合同，已有实现证据；需叠加列出的独立扩展，不意味着所有历史背景/Out of Scope 永久有效。 |
| 已被后续规则更新 | 有局部或主要条款被后续正式规则更新；按表内链读取，未替代部分仍有效，不能整份丢弃。 |
| 已实施历史 | 旧能力确有实施记录，但该阶段的主要执行合同已整体退出当前用法；用于历史追溯，当前以列出的后续合同为准。 |
| 待核验 | 证据不足时使用，不推断 Freeze、实施或替代关系。 |

分类统计：当前有效 **8**；已被后续规则更新 **20**；已实施历史 **2**；待核验 **0**。共 30 份（不含本索引）；状态互斥，流程元数据待核验另列下方。

## 逐份状态与证据

以下提交是实现/历史线索，模块为当前可核对入口；不是仅凭 Spec 提交标题确认实现。路径以仓库为根，Backend 文件在 `backend/app/`，Frontend 文件在 `frontend/src/`。本轮只做静态/历史核对，不运行真实采集或迁移。

| Spec | 状态 | 实现 / 历史证据 | 后续合同与保留边界 |
| --- | --- | --- | --- |
| [add-competitor.md](add-competitor.md) | 已实施历史 | 8251d24；competitors.py 的旧登记流程 | 当前添加整体改为前置采集、店铺识别及原子落库，见 [own-product-management-v1.md](own-product-management-v1.md)；URL/唯一性原则继承。 |
| [collect-competitor.md](collect-competitor.md) | 已被后续规则更新 | 0616fac、9378d57、d16f767；collection/service.py、collector_1688.py、parser_1688.py | 无生命周期/无 diff 和列表单条采集入口已更新：[product-lifecycle-monitoring.md](product-lifecycle-monitoring.md)、[detect-competitor-changes.md](detect-competitor-changes.md)、[own-product-management-v1.md](own-product-management-v1.md)；保留采集/图库事实边界。 |
| [competitor-list.md](competitor-list.md) | 已被后续规则更新 | e1e295c、421d837；competitors.py、App.tsx ListPage | 真实快照/变化由 [collect-competitor.md](collect-competitor.md)、[detect-competitor-changes.md](detect-competitor-changes.md) 补足；分页见 [competitor-list-pagination-v1.md](competitor-list-pagination-v1.md)，选择见 [competitor-list-batch-actions-v1.md](competitor-list-batch-actions-v1.md)；身份分流与添加/采集入口最终以 [own-product-management-v1.md](own-product-management-v1.md) 为准。 |
| [competitor-detail.md](competitor-detail.md) | 已被后续规则更新 | 0995bfa、0e0bf5d；competitor_detail.py、App.tsx DetailPage | 逐快照 price_trend 改为每日最终 daily_trend，见 [competitor-detail-overview-trends.md](competitor-detail-overview-trends.md)；图库见 [collect-competitor.md](collect-competitor.md)；事件及身份见 [detect-competitor-changes.md](detect-competitor-changes.md)、[own-product-management-v1.md](own-product-management-v1.md)。 |
| [competitor-lifecycle.md](competitor-lifecycle.md) | 已被后续规则更新 | ac58c76、30e8f7d；competitors.py monitoring / delete API | 单条语义保留；批量限制由 [competitor-list-batch-actions-v1.md](competitor-list-batch-actions-v1.md) 更新；self 的批量删除保护见 [own-product-management-v1.md](own-product-management-v1.md)。不要与商品上下架检测混淆。 |
| [competitor-groups.md](competitor-groups.md) | 已被后续规则更新 | 3753405；competitor_groups.py、App.tsx GroupsPage | own/直接竞品摘要由 [own-product-role-binding.md](own-product-role-binding.md) 扩展，最终身份与归组入口由 [own-product-management-v1.md](own-product-management-v1.md) 更新；组分析见 [group-detail-v1.md](group-detail-v1.md)。CRUD/删除保留历史原则仍有效。 |
| [daily-collection.md](daily-collection.md) | 已实施历史 | 6d170b5；旧 direct-cycle；现 main.py、collection/daily.py | 整段旧启动 30 秒/每小时直接采集策略由 [daily-auto-collection-strategy-v1.md](daily-auto-collection-strategy-v1.md) 替代；不要据此恢复旧调度。 |
| [dashboard-today.md](dashboard-today.md) | 已被后续规则更新 | f1560b9、421d837；dashboard.py | 聚合见 [dashboard-daily-change-aggregation.md](dashboard-daily-change-aggregation.md)；核心页面与 KPI 由 [group-first-dashboard-v1.md](group-first-dashboard-v1.md) 替代，入口最终见 [own-product-management-v1.md](own-product-management-v1.md)。/api/dashboard/today 仍提供采集概览/趋势与兼容数据，接口存在不代表旧大表仍是首页主体。 |
| [batch-collection.md](batch-collection.md) | 已被后续规则更新 | 4272354、bef1f04；collection/service.py、competitors.py | 验证中止/浏览器清理由 [batch-collection-auto-resume-v1.md](batch-collection-auto-resume-v1.md) 局部更新；设置化/休息见 [competitor-monitoring-settings-v1.md](competitor-monitoring-settings-v1.md)；范围及 UI 入口见 [own-product-management-v1.md](own-product-management-v1.md)；自动 Batch 见 [daily-auto-collection-strategy-v1.md](daily-auto-collection-strategy-v1.md)。 |
| [competitor-detail-overview-trends.md](competitor-detail-overview-trends.md) | 当前有效 | 0e0bf5d、4a20491；competitor_detail.py daily_trend、App.tsx DetailPage | 概览与 7/30 天每日价格/完整库存趋势合同仍有效；库存未知不为零，销量仍是占位。 |
| [dashboard-daily-change-aggregation.md](dashboard-daily-change-aggregation.md) | 已被后续规则更新 | 46b430a、7680ba5；dashboard.py | 底层兼容聚合仍有实现；事件扩展见 [detect-competitor-changes.md](detect-competitor-changes.md)、[product-lifecycle-monitoring.md](product-lifecycle-monitoring.md)；页面主表被 [group-first-dashboard-v1.md](group-first-dashboard-v1.md) 替代，self 过滤见 [own-product-management-v1.md](own-product-management-v1.md)。 |
| [main-image-change-detection.md](main-image-change-detection.md) | 已被后续规则更新 | 63d6d1e；changes.py、parser_1688.py | 首图比较规则继续有效；事件 V2 关联/delta 见 [detect-competitor-changes.md](detect-competitor-changes.md)，生命周期 primary 优先见 [product-lifecycle-monitoring.md](product-lifecycle-monitoring.md)；首页展示/Attention 由 [group-first-dashboard-v1.md](group-first-dashboard-v1.md)、[group-attention-priority-v1.md](group-attention-priority-v1.md) 更新。 |
| [product-lifecycle-monitoring.md](product-lifecycle-monitoring.md) | 已被后续规则更新 | a36e372；collection/service.py、collector_1688.py；迁移 08/09 | 上下架状态机、offline 无 Snapshot 与恢复 baseline 仍有效；事件字段见 [detect-competitor-changes.md](detect-competitor-changes.md)；首次添加验证与 UI 入口见 [own-product-management-v1.md](own-product-management-v1.md)，Batch 验证流程见 [batch-collection-auto-resume-v1.md](batch-collection-auto-resume-v1.md)。 |
| [detect-competitor-changes.md](detect-competitor-changes.md) | 当前有效 | 70bc5c2；changes.py、models.py；迁移 20260923_10 | 14 种标准事件 + legacy stock_changed；NULL、baseline、entity_key、Run 关联与 delta 合同。页面消费另叠加后续身份与 Group-first Spec，不能据旧实施背景重新建事件模型。 |
| [group-intelligence.md](group-intelligence.md) | 已被后续规则更新 | 35a958e；9d2ba28、012ae39、9ebad20 的后续实施 | 作为组中心方向保留；具体组合同见 [group-detail-v1.md](group-detail-v1.md)，旧人工身份见 [own-product-management-v1.md](own-product-management-v1.md)；旧“下一步 Group Entry”及竞品级 Dashboard 主语由 [group-first-dashboard-v1.md](group-first-dashboard-v1.md) 更新。 |
| [own-product-role-binding.md](own-product-role-binding.md) | 已被后续规则更新 | 9d2ba28；迁移 20260923_11；现 competitor_groups.py | 人工组内指定身份、解除仍留组及 own 转组降为竞品的语义由 [own-product-management-v1.md](own-product-management-v1.md) 明确替代；当前兼容绑定 API 仅允许 self，UI 不再提供旧人工指定身份入口。 |
| [group-detail-v1.md](group-detail-v1.md) | 已被后续规则更新 | 012ae39；group_detail.py、App.tsx GroupDetailPage | V1 比较/今日/动作窗口仍有效；直接竞品范围以 [own-product-management-v1.md](own-product-management-v1.md) 的 ownership 过滤为准，不能仅凭 group_role 把未分组 self 当竞品；不是未来 V2 排名。 |
| [dashboard-group-entry-v1.md](dashboard-group-entry-v1.md) | 已被后续规则更新 | 128d8d5 为 Spec 提交；最终页面见 9ebad20、App.tsx DashboardPage | 竞品表主语、Summary 面板与旧 KPI 由 [group-first-dashboard-v1.md](group-first-dashboard-v1.md) 明确 supersede；Header 最终见 [own-product-management-v1.md](own-product-management-v1.md)。未确认独立实验曾单独作为正式版本交付，不据此宣称已发布旧 Group Entry。 |
| [group-attention-priority-v1.md](group-attention-priority-v1.md) | 当前有效 | 9ebad20；group_attention.py | 事件矩阵、去噪、Strong Event、等级/原因/稳定排序仍有效；ownership 过滤叠加 [own-product-management-v1.md](own-product-management-v1.md)，不把内部权重解释为经营评分。 |
| [group-first-dashboard-v1.md](group-first-dashboard-v1.md) | 已被后续规则更新 | 9ebad20；group_attention.py、App.tsx DashboardPage | 组级主语、KPI、eligibility 仍有效；Header 曾由 [competitor-list-batch-actions-v1.md](competitor-list-batch-actions-v1.md) 移除，后由 [own-product-management-v1.md](own-product-management-v1.md) 恢复并统一为添加监控商品/all_active；最终以后者为准。 |
| [competitor-list-pagination-v1.md](competitor-list-pagination-v1.md) | 已被后续规则更新 | ac68d9c；App.tsx ListPage | 固定 10 条、筛选再分页及跨页保留仍有效；active-only selection 由 [competitor-list-batch-actions-v1.md](competitor-list-batch-actions-v1.md) 更新为通用选择，列表采集入口由 [own-product-management-v1.md](own-product-management-v1.md) 收敛。 |
| [frontend-automated-qa-v1.md](frontend-automated-qa-v1.md) | 当前有效 | 2b28ebd；frontend/playwright.config.ts、frontend/e2e | 受控 Chromium / 默认拒绝未声明 API 的 QA 基础合同；后续业务测试按最新 Spec，旧“列表添加”场景不证明当前入口仍在那里；旧 5200/8100 示例已过时，常规端口按当前 dev.ps1 / Vite 为 5300/8200，QA 仍为 5201。 |
| [competitor-list-batch-actions-v1.md](competitor-list-batch-actions-v1.md) | 已被后续规则更新 | 30e8f7d；competitors.py batch API、App.tsx ListPage | 通用选择及批量生命周期继续有效；列表添加/采集和以 group_role 判定我方的旧规则由 [own-product-management-v1.md](own-product-management-v1.md) 替代。 |
| [batch-collection-auto-resume-v1.md](batch-collection-auto-resume-v1.md) | 已被后续规则更新 | 6948a52；collection/service.py BatchRuntime / runner | 冷却、有限自动续采及人工兜底继续有效；固定冷却/次数由 [competitor-monitoring-settings-v1.md](competitor-monitoring-settings-v1.md) 改为 Batch 配置快照。 |
| [own-product-management-v1.md](own-product-management-v1.md) | 当前有效 | dcf0462；ownership.py、competitors.py、settings.py、App.tsx；迁移 20261004_12 | 当前身份、统一添加、分流、组关系、竞品统计排除 self 的权威合同；设置页面后叠加采集设置及视觉试点，不按其当时 Out of Scope 否定已实施后续功能。 |
| [collection-tasks-v1.md](collection-tasks-v1.md) | 已被后续规则更新 | efe1e3f；collection_runs.py、App.tsx CollectionTasksPage | Runtime/持久化单商品历史职责保留；resting 与参数见 [competitor-monitoring-settings-v1.md](competitor-monitoring-settings-v1.md)，自动任务经 Runtime 见 [daily-auto-collection-strategy-v1.md](daily-auto-collection-strategy-v1.md)；视觉层级/明细折叠见 [collection-tasks-ui-v2.md](collection-tasks-ui-v2.md)。 |
| [competitor-monitoring-settings-v1.md](competitor-monitoring-settings-v1.md) | 已被后续规则更新 | 7b382ef；settings.py、collection/service.py | 五项节奏/风控规则仍有效；完整保存对象由 [daily-auto-collection-strategy-v1.md](daily-auto-collection-strategy-v1.md) 扩展为九项；卡片/Select 展示由 [system-settings-visual-refresh-v1.md](system-settings-visual-refresh-v1.md) 局部替代。 |
| [daily-auto-collection-strategy-v1.md](daily-auto-collection-strategy-v1.md) | 当前有效 | 7e9dbd7；main.py、collection/daily.py、settings.py | 九项完整设置、两策略、电脑本地时间、missed policy、统一 Batch 编排已实现；策略控件外观按 [system-settings-visual-refresh-v1.md](system-settings-visual-refresh-v1.md)，业务语义不变。 |
| [collection-tasks-ui-v2.md](collection-tasks-ui-v2.md) | 当前有效 | 826c2f5；App.tsx CollectionTasksPage、App.css、CollectionTasks.test.tsx | 已实施 UI V2：当前状态/默认折叠明细/历史分层，items 保持 Backend 原顺序；不是 Group Detail V2。 |
| [system-settings-visual-refresh-v1.md](system-settings-visual-refresh-v1.md) | 当前有效 | a083047 Freeze 记录；b71f822 实施；App.tsx SettingsPage、App.css settings scoped | 仅设置页视觉试点，继承九项设置及独立模块保存语义，不代表全局换肤。 |
| [1688-operating-metrics-integration-v1.md](1688-operating-metrics-integration-v1.md) | 已冻结（2026-10-10；ChatGPT 独立 Final Spec Review 通过，P0/P1/P2/P3 = 0/0/0/0） | 本地 Gate 1 五链接报告与现有 Collector / Batch Runner 证据；尚未实现 | 八项助手顶部指标限定原值；收藏和八标签 Hold。验证弹窗漏检是独立已知问题，不是本 Spec 门槛。待按冻结 Spec 实施。 |

## 仍待核验的流程事实与文档边界

- 早期 Spec 没有统一 Freeze / 人工验收记录格式；代码和 Git 可以确认表中能力已经实施，但不能凭“feat”提交为每份历史 Spec 补签 Review / Freeze。若需要发布审计，须另查对应 Review / 验收档案；本索引不宣称全部正式流程已获重新确认。
- Dashboard Group Entry 的独立实验是否曾单独完成正式交付未确认；可以确认它的旧页面合同已被 Group-first 替代，不要求复原该实验。
- [architecture.md](../architecture.md) 仍含旧 Dashboard 今日变化表和内部滚动的历史描述；其调度章节已更新，但旧表不是当前页面核心。该文件不在本轮修改范围，页面职责按本索引的 Group-first / 我方商品管理合同以及 product / ui-system 当前说明读取，后续可做聚焦同步。
- 未读取真实工作数据库或运行迁移；表结构状态指仓库 ORM / Alembic 能力，不宣称本机数据库已升级 head。正式销量/经营字段来源稳定性仍由 research / POC 核验。

## 后续重构范围

Track A 优先定义现有事实的组内竞争位置；Track B 经营指标增量 POC 可并行，只阻塞新指标产品化。Group Detail V2、公司/企业主体建模、同规格排名、经营指标观察、管理导航融合都不是当前已实现能力，也未因本索引获得开发授权。

## 已 Freeze Spec（2026-10-09）

| Spec | 状态 | 范围与 Gate |
| --- | --- | --- |
| [组内竞争情报与竞争位置 V1](group-competitive-position-v1.md) | 已通过 ChatGPT Final Spec Review / 已 Freeze；本轮已实施，最新 UI 已由用户验收，完整验证结果见最终收尾报告；冻结基准 `7bd49355df7ca19a1de2835c0280d140a76b624f` | 升级现有组详情的目标 UI、真实 Offer 排序/位置和变化证据；R1～R3 已正式确认。原始原型截图已入库，历史明细有界首批/游标加载，排名基于各 Offer 最近有效快照且非实时同步。新经营字段与评分保持未就绪。Freeze 后局部覆盖 Group Detail V1 的我方首行、首屏结构和主要动态呈现，其余事实合同继承。 |

以上 Spec 不计入 2026-10-08 的 30 份历史核验分类统计；当前索引共收录 32 份 Spec。组分析现按已实施的 group-competitive-position-v1 及其继承合同运行；完整验证结果见最终收尾报告。
