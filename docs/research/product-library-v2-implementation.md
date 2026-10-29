# Issue #8 实施与 Code Review 交接

日期：2026-10-29。需求入口：[Issue #8](https://github.com/shuzeyong312-rgb/personal-workbench/issues/8)。设计依据：已独立审查通过的 [产品库 V2 Spec，5304fd4](https://github.com/shuzeyong312-rgb/personal-workbench/blob/5304fd4a8cad1533dca5e925887052f904ad8a42/docs/specs/product-library-v2.md)，未重复 Spec Review。

## 范围与检查点

- 基线：`5304fd4a8cad1533dca5e925887052f904ad8a42`，任务分支 `codex/product-library-v2-spec`，开始时工作区干净；未创建或切换 worktree。
- 身份迁移检查点：`f01e8ab112122b1a73ceafe75d0126da6347d201`。全局型号+名称及无型号同名唯一性，拒绝历史冲突，不自动归并。
- 后端检查点：`f8c24dac7aab37a06b32cb250e7b01ddc434768a`。关联模型、参数、V1/V2 导入、事务回执、报价适配及隔离回归。
- 本记录随详情编辑、五表预览及报价交互提交；最终 UI head 由固定 SHA 的交接消息提供。B/C 中间提交不能单独上线。

## 实现入口

- `backend/app/product_library_details.py`：规格/来源/价格校验、版本、引用保护、旧价格命令和单向默认价投影。
- `backend/app/product_library_v2_import.py`：严格五表模板，工作表/行/临时ID定位的不可变计划、关联匹配、依赖、重复/冲突、确认与幂等回执。
- `backend/app/product_library_service.py`：全局身份、V1 六列兼容及来源追加、历史 committed 回执、筛选和主产品 CRUD。
- `backend/app/product_library_quotations.py`：采购价型白名单、规格与来源快照、条件确认、客户七列白名单与全新工作簿。
- `frontend/src/ProductLibraryDetails.tsx` / `ProductLibraryV2Import.tsx` / `ProductQuotation.tsx`：沿用现有对话框/详情分区，补充真实编辑、逐表审核、选规格/选价与条件确认；窄屏报价纵向排列。

## 数据与迁移保护

新增 revision `20261029_20`、`20261029_21`，保留既有 revision。SQLite 连续升级在同一事务内；预检、建表、回填、索引或 revision 更新失败均回滚。旧行 ID、version、原字段和 committed 回执不重写。默认价明细回填保留原人民币金额，不从备注推断价格或条件。

仅使用新建临时 SQLite、fixture 和 mock。全量测试进程将默认库和工作浏览器 Profile 根目录隔离到临时目录，并用 SQLAlchemy `do_connect` 拦截正式数据库路径。迁移测试另断言目标在 tmp_path 内且不同于正式库。未运行 dev.ps1、正式迁移、真实 1688 登录、客户发送或部署。

V2 禁止通过 drop 新表降级；恢复须停写、导出增量并恢复已验证的一致性旧备份。正式库尚未预检或升级，不声称正式历史数据无碰撞。

## 实际验证

- 后端：完整运行隔离 `backend/tests`，**882 项通过**；另对最终产品库、身份、V1.1、客户报价及迁移执行 **191 项通过**的定向回归。
- 迁移：**11 项通过**，含跨公司/无型号冲突、非规范身份、数据库唯一约束、旧行/回执及金额保留、连续升级 DDL/回填/stamp 失败恢复、安全拒绝降级。
- 前端：`npm --prefix frontend test`，**226 项通过**；`typecheck` 和 `build` 通过。构建有大于 500 kB 的非阻断 chunk 提示，未借任务扩大为全站打包重构。
- 人工浏览器：独立临时库 + 端口 8217/6578，验证详情新增规格、V2 上传/逐表预览/附件确认/回执、多价格不自动择价、规格/采购价选择、MOQ/条件确认及 390px 纵向布局。没有新增或执行前端 Playwright E2E；浏览器工具交互不作为真实厂家或生产库证据。
- 自审与 `git diff --check` 完成；工程提交的 Actions 与最终远端 SHA 在交接消息给出。

旧报价算术测试现在明确提交采购条件确认，金额与七列输出行为保持；未知税费/运费或 MOQ 不再绕过新确认合同。旧迁移测试固定在各自 revision，避免移动 head 的 V2 安全降级门禁遮蔽原测试目标。

## 未覆盖与验收状态

- Phase D 图片、证书和原件二进制存储未实施；来源文件名/页码不是文件归档。预览明确警告，需确认未保存附件。
- 仅通用模拟资料覆盖六类形态，没有声称核验六份真实厂家原件。更多真实品类和资料完整性仍属后续用户数据验收。
- 不自动汇率换算、按箱折价、推断 MOQ 或价格类型；控价/其他价不得作为采购基准。
- 当前为“已实现并同步，待 ChatGPT 对最终固定 SHA 独立 Code Review”。自审、测试和 CI 均不替代独立 Review，也不代表用户最终验收或授权正式迁移。
