# competitors.status CHECK 漂移专项诊断与修复候选

日期：2026-10-14。ChatGPT 已批准一次性受控修复；独立脚本 Review、最新备份隔离复测和正式修复后 Schema Gate 均 PASS。修复只补齐既定 CHECK，未执行 Alembic 迁移或 stamp，未启动服务或采集。

## 诊断结论：情况 B

正式路径由 `app.database.DATABASE_FILE` 解析为仓库内 `backend/data/personal_workbench.db`。当前revision为20261012_14，但本结论不是由revision推断。

原始 CREATE TABLE SQL 已保存为 `.artifacts/status-constraint/formal-create.sql`。它只声明 `status VARCHAR(32) NOT NULL`，完全没有status CHECK表达式，不存在名称不同、匿名约束或IN值顺序不同导致的误判。其余实际CHECK为group_role、own_requires_group、ownership、ownership_role，均保留；Model预期的其他直接相关约束没有遗漏。旧own_requires_group属于canonical migration遗留约束，不在本专项删除。

canonical Model `backend/app/models.py` 明确要求：

```sql
CONSTRAINT ck_competitors_status CHECK (status IN ('unknown', 'active', 'offline'))
```

现存status均为合法状态；NULL和其他非法值0条。无需修改任何业务值。

## 已证实的根因与历史边界

- 当前根因是物理表DDL缺少状态域约束，不是检查器按名称误判。
- 初始20260919_01 migration及首次引入的Git提交8251d24就含此CHECK；该历史migration从引入后没有修改记录。
- 直接涉及competitors重建的20260920_04、20260923_11、20261004_12以及后续_13/_14，已在新建隔离数据库逐级重放。所有阶段都保留ck_competitors_status。
- 因此当前仓库受控migration正常执行不能复现正式库的遗漏。V1.2 _14不重建competitors，不能把这项历史漂移归因于V1.2。
- 现存库没有DDL执行审计和缺失发生前的表快照；无法可靠区分“正式最初建表就遗漏”与“某次未留证据的历史重建丢失”，也无法命名具体执行脚本、操作者或旧依赖版本。不得把推测当成已确认根因。根因定位的可信边界是：正式Schema来源与当前canonical建表/迁移结果不一致。

迁移逐级CHECK清单、实际和Model约束表达式、状态值分布见 `.artifacts/status-constraint/evidence.json`。

## 唯一推荐：一次性受控、事务性本地修复脚本

候选：`backend/scripts/repair_competitors_status.py`。

理由：目前只确认这一份正式库的一项既有漂移。一次性修复仅补齐既定canonical规则，不改revision、不stamp、不改已经应用过的历史migration，不使其他正常数据库升新版本。脚本默认只读；必须显式--apply及新备份路径才写入。等价的匿名/不同名称/不同IN顺序CHECK已存在时完全不操作，文件字节不变；同名但不同表达式则BLOCKED。

相比新增幂等Alembic修复migration：后者适合确认存在多个部署需持续自动升级的同类缺陷。本项目目前没有这项需求；全体正常库也要推进revision，降级还需要区别约束原先存在还是此次补建。为这一份已定位数据库增加新head和降级语义成本更大。本轮不采用，不修改历史migration。

SQLite流程：检查合法数据/完整性/FK → SQLite Backup API到全新独立文件并验证 →关闭此专用连接的FK检查 →BEGIN IMMEDIATE →重新检查Schema和全表数据未变化 →用原CREATE SQL创建临时表，只追加CHECK →按原列和ID复制 →DROP旧表 →RENAME →原样重建显式索引及触发器 →核对所有表数据指纹、索引/触发器、integrity/FK →COMMIT。任何错误ROLLBACK；恢复连接FK设置并关闭连接。临时表已存在时拒绝执行，不擅自删除。

专用候选并非通用Schema修复器。正式执行前必须确认除了本CHECK外的结构均与本次诊断一致；新增视图/触发器/结构变化须重新隔离验证，不能照搬本次结果。

## 隔离验证

正式SQLite通过mode=ro、SQLite Backup API生成一致性副本，候选只对副本执行。

- Schema diff仅competitors表新增status CHECK；其他表、索引、外键和触发器定义不变。最终候选修复后的列、CHECK、FK、Unique和Index定义与逐级重放的canonical migration完全一致。
- 对所有业务表逐行内容生成指纹，比对前后完全一致，不只比较行数。
- Competitor、CollectionRun、Observation、Snapshot、SKU、Batch和BatchItem均保持原始事实；system_settings和其他表同样不变。
- integrity_check=ok；foreign_key_check为空。
- 非法值invalid、ACTIVE、空字符串均被CHECK拒绝；unknown/active/offline均可通过（验证事务随后回滚，不保留验证修改）。
- Alembic revision仍为20261012_14。
- 实际V1.2 batch router对修复副本查询通过，现存真实批次及全部商品，未启动lifespan/Scheduler/Collector。
- 一致性备份还原到另一个隔离文件后，Schema和所有表数据与修复前完全一致。
- 6项定向测试通过：保留历史/FK/索引/触发器、非法值拒绝、合法值、不同名称/匿名等价CHECK字节级no-op、非法数据BLOCKED、同名不同表达式BLOCKED，以及DROP之后故障注入的完整事务回滚。
- 诊断阶段正式数据库文件SHA256前后相同；批准执行阶段仅表DDL补齐CHECK，所有表数据指纹保持相同。

证据：`.artifacts/status-constraint/evidence.json`、`schema.diff`；诊断重放脚本位于同目录，生成物不提交。

## 正式修复前置条件和执行命令

方案已经 ChatGPT 审查批准。以下命令模板必须在每次停写、备份及结构检查通过后显式执行，不会随应用启动自动运行。

1. 再次只读确认实际数据库路径、revision、DDL、全部状态合法，差异仍只有本CHECK。
2. 安全停止所有Backend/Scheduler/Runner/其他数据库writer，确认无活动采集、无Profile并发占用。不要通过修改持久采集设置来停机。
3. 保留原数据库及所有sidecar；选择全新备份文件路径，禁止覆盖已有备份。
4. 使用已验证解释器和当前候选版本；先dry-run，再执行批准的apply：

```powershell
.\.venv\Scripts\python.exe backend/scripts/repair_competitors_status.py "C:\data\personal-workbench\backend\data\personal_workbench.db"
# 仅在批准及全部停写门槛满足后：
.\.venv\Scripts\python.exe backend/scripts/repair_competitors_status.py "C:\data\personal-workbench\backend\data\personal_workbench.db" --apply --backup "<仓库外全新备份绝对路径>"
```

若目标/Schema/状态/备份路径或锁有冲突，停止，不强行修复，不stamp。

## 失败恢复与解除V1.2阻塞

- COMMIT前错误：脚本ROLLBACK恢复原表、索引、触发器及数据；不删备份。再次只读验证完整性/FK/Schema，调查错误后再决定是否重试。
- 进程崩溃或存储异常：停止所有writer，不覆盖正在使用的SQLite。先用SQLite Backup API将已验证备份还原到新文件，核对Schema/全表数据/完整性/FK；离线替换或切换目标必须单独按恢复门槛操作。
- 成功后：再次比较完整canonical Schema，应不再缺CHECK；核对revision仍_14、全表事实不变、非法值拒绝、完整性/FK通过；再用禁用Scheduler的受控实例完成只读API检查。
- 只有正式Schema Gate解除，且其余V1.2 Gate仍有效，才可按已有条件授权进入Commit/Push。再按用户条件授权提交修复维护内容。

本专项仅新增脚本、定向测试与本文档；此前V1.2代码保留，未修改Frozen Spec、采集配置或Chrome Profile。

## 批准执行结果

- 正式 Backend/Scheduler 已停止；执行前数据库及现存 sidecar 独占只读打开检查通过，无占用。未改变持久采集设置。
- 创建仓库外全新一致性备份，并验证完整性、外键、所有表内容；在最新副本完成修复、非法值拒绝、合法值、幂等、备份恢复及实际只读 API 查询验证。
- 独立脚本 Standards / Spec Review PASS，P0/P1/P2=0/0/0。
- 定向 Backend 123 passed，包含6项专项修复测试、competitors/删除关联、采集记录查询及批次迁移测试。测试连接保护禁止连接正式库。
- 正式脚本执行一次，修复后完整 canonical Schema 一致，revision仍20261012_14；integrity_check=ok，foreign_key_check为空。全表内容、索引、触发器及关联保持一致，现有真实批次详情只读查询通过。
- 复用已通过的 V1.2 Backend 511、Frontend 218、Playwright 19及TypeScript/生产构建证据，不重跑无关全量测试。
- 经营补采与验证恢复仅有隔离测试证据，本轮未在真实网站上执行或宣称通过。备份路径、业务数据和本机执行产物不提交。
