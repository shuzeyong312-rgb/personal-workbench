# 工作目录维护记录

2026-10-26 盘点包含跟踪、未跟踪和忽略文件；初始工作区干净，main 与 origin/main 一致。以下大小为整理前近似值，不跟随 Junction。

| 内容 | 分类与来源 | 处理 |
| --- | --- | --- |
| backend、frontend/src、frontend/e2e、tests、docs | 正式工程源码、测试、合同与参考资料 | 保留结构 |
| .agents、.codex、.github、.impeccable、skills-lock.json、DESIGN.md | 工具、CI 与设计配置；.codex 当前为空 | 保留可访问性 |
| .venv（187 MiB） | Python 运行依赖 | 正式服务正在使用，原路径保留 |
| frontend（800 MiB，含依赖与构建） | 前端源码、npm 依赖和生成物 | 保留依赖与 dist |
| 根 node_modules | 指向 Codex 共享运行库的 Junction | 保留且不递归进入目标，VS Code 隐藏 |
| .browser-profile（896 MiB） | Chrome 登录态、浏览器运行数据 | 原路径保留，不重置 |
| backend/data（约 29 MiB） | SQLite 工作库、升级前备份及客户触达运行数据 | 全部保留，不打开写连接、不迁移 |
| logs（0.14 MiB） | 开发及验收服务日志 | 正式服务仍运行，保留排障证据 |
| .artifacts（119 MiB） | 截图、验收库、客户触达与 schema 排障证据 | 文档和测试仍引用，整体保留 |
| .tmp（144 MiB） | workflow-baseline.zip、验证源码 / 虚拟环境副本、validator 依赖、失败与重试日志 | 混有环境及证据，未证明全部失效，保留并隐藏 |
| 根 test-results（0.23 MiB） | 失败 Playwright 结果及错误上下文 | 保留排障证据，隐藏 |
| frontend/test-results-settings、docs/qa | 设置截图与历史验收记录 | 保留；不改变既有 docs/qa 忽略策略 |
| backend/tests/customer-reach-*.db | test_customer_reach.py 使用 UUID 生成的测试库 | 确认来源，但历史任务证据价值未排除，保留 |
| experiments 原有目录（0.16 MiB） | Gate1 POC、JSONL、截图及本地客户触达实验；current-page 目录为空 | 原样保留，POC 不等于正式能力 |
| 根七个 poc_*.py | 独立浏览器与采集实验，部分相互导入 | 移到 experiments/poc；根路径改为 parents[2]，同目录导入不变 |
| 根 poc_collect_debug.json | poc_collect.py 生成的历史字段诊断 | 暂留原处并继续忽略，避免丢失证据；未来输出在脚本目录 |
| __pycache__、.pytest_cache | Python / pytest 可再生成缓存 | 删除操作被自动审批策略拒绝，未清理；VS Code 隐藏 |
| frontend/test-results、frontend/playwright-report | 上轮 passed 的结果与 HTML 报告 | 同一清理命令被拒绝，未主动删除；测试工具可能重新生成 |

## 维护边界

files.exclude 隐藏运行环境、依赖、缓存、日志和测试输出；search.exclude 另排除 logs 与 backend/data。工程配置目录仍可访问。隐藏不表示可删除。

.gitignore 补充 pytest 缓存、根 .tmp、Python 字节码、移动后的 POC 诊断、SQLite 扩展名及 sidecar。既有源码、正式配置、文档和 CI 保持版本管理，原有 *.db、logs、Profile 与依赖忽略规则不变。

本轮只移动 POC、修正固定路径和文档引用，不执行 POC main、真实采集、发送或正式迁移。根目录调用入口为 `.\.venv\Scripts\python.exe experiments/poc/<脚本名>.py`。POC 验证使用编译、导入和路径断言，不访问工作库。

## 本轮验证

- POC 编译、跨目录导入及根路径断言，采集 parser 与 Gate1 探针：65 passed、4 subtests passed。
- 后端从 backend 执行 pytest：824 passed。首次从根目录执行为 823 passed / 1 failed，原因是既有迁移测试按 cwd 查找 alembic.ini；已修正文档命令，测试与配置未改动。
- Vitest：230 passed；Typecheck、Build 通过（既有超过 500 kB 的 chunk 提示保留）。
- Playwright 导航 smoke：1 passed；本轮未改 UI，未运行全量 E2E。
- tests/dev-port.ps1：三次随机端口 HTTP 200 与进程识别通过，未执行 dev.ps1。
- README / 工程文档链接、POC 引用、设置 JSON、忽略规则和移动前后逐文件差异检查通过；git diff --check 通过。

自审与本地验证不替代 Push 后 ChatGPT 固定 SHA 独立 Review。缓存物理清理因自动审批拒绝仍未完成。
