# Personal Workbench

面向个人的 Windows 本地 Web 工作台，主要用于 1688 竞争情报、厂家产品库与客户报价，并提供开发态客户触达工具。数据保存在本机 SQLite。

## 当前能力与边界

- **竞争情报**：我方商品 / 竞品管理、分组与基准商品绑定、监控生命周期、商品快照、SKU / 库存 / 主图变化及采集历史。
- **组内分析**：关注组排序、今日重要动态、历史动作、价格 / MOQ / SKU / 库存比较与组内竞争位置排名；经营指标按证据与可用性展示，上架时间、月成交、年成交、评论和履约等字段不保证每个商品都有值。库存变化不能推算销量。
- **采集任务**：串行批次、间隔与休息、验证冷却和有限续采；自动采集支持滚动 24 小时、每日 1–8 个时间点及有每日次数上限的固定间隔，可配置补采 / 跳过。调度依赖后端持续运行，休眠期间不执行。
- **产品库与报价**：厂家商品维护、canonical-package-v1 ZIP 导入预览 / 确认、搜索与高级筛选、Identity V2 商品身份、客户报价计算与 Excel 导出。客户导出隔离内部字段，具体合同见 Spec。
- **客户触达（开发态）**：持久化任务、模拟演练、暂停 / 跳过 / 取消与结果记录；可选 Windows 桌面执行器的客户端依赖、确认方式和适用边界见[客户触达说明](docs/customer-reach-v1.md)。默认 simulated，不操作客户端；真实发送需另行明确授权，不能把模拟测试当作实机验收。

首页与自动上架仍有占位入口。AI 建议、自动定价、自动选品、自动上架、多用户、多平台及通知尚未作为正式业务实现。`experiments/` 是实验与历史证据，不是正式服务；[旧重构计划](docs/roadmap/competition-intelligence-restructuring-plan.md)仅供历史背景，已落地的排名与经营指标不再列为待实现。

## 技术栈与目录

React 19、TypeScript、Vite 6、CSS / SVG；FastAPI / Uvicorn 模块化单体；SQLite / SQLAlchemy / Alembic；Python Playwright + 本机 Google Chrome 采集；openpyxl 处理 Excel。自动验证使用 pytest、Vitest、Typecheck 和 Build；必要时人工检查浏览器交互与视觉。调度在 FastAPI lifespan 内运行，复用 Batch Runner。

```text
personal-workbench/
├─ backend/
│  ├─ app/                 # API、业务服务、collection 采集模块
│  ├─ alembic/             # 版本化迁移
│  ├─ data/                # 本地数据库、备份及运行数据（不提交）
│  ├─ scripts/             # 数据修复 / 迁移演练工具，按说明谨慎使用
│  └─ tests/               # 隔离数据库与 fixture 测试
├─ frontend/
│  ├─ src/                 # React 页面、样式与 Vitest
├─ experiments/
│  └─ poc/                 # 原根目录七个独立 Python POC
├─ tests/                  # PowerShell 开发脚本检查
├─ docs/                   # 工程流程、业务 Spec、Research、UI 参考
├─ .agents/skills/         # 项目 Skills
├─ .github/workflows/      # CI
├─ .vscode/settings.json   # 资源管理器 / 搜索排除生成物
├─ .codex/                 # 本地工具配置入口（可为空）
├─ .impeccable/            # 设计工具配置
├─ AGENTS.md / DESIGN.md   # 开发摘要 / 设计说明
├─ skills-lock.json        # Skill 安装锁定信息
└─ dev.ps1                 # Windows 启停脚本
```

本地还会出现 `.venv/`、`.browser-profile/`、`logs/`、`.tmp/`、`.artifacts/`、依赖和测试输出。分类、保留原因与清理边界见[目录维护记录](docs/engineering/workspace-layout.md)。

## Windows 环境与启动

建议使用与 CI 一致的 Python 3.12、Node.js 22 / npm，安装 Google Chrome。在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
.\dev.ps1
```

脚本执行策略受限时可用 `powershell.exe -ExecutionPolicy Bypass -File .\dev.ps1`。脚本不安装依赖，启动前会在 backend 执行 `alembic upgrade head`，**会升级本地工作库，已有数据先备份**；工程验证不要用此脚本。

- 后端固定 `http://127.0.0.1:8200`，启用 reload；前端由 Windows 分配可绑定端口并打开浏览器，实际地址见控制台与 `logs/frontend.log`，`/api` 代理到 8200。
- 两服务都运行时再次执行脚本会强制停止；只有一个存在时清理项目残留并重新启动。日志在 `logs/backend.log` 和 `logs/frontend.log`，脚本不会杀掉占用端口的无关进程。
- 采集 Profile 为根目录 `.browser-profile/`。首次采集前需在本机 Chrome 完成登录并核对系统设置的我方店铺；不要并发使用同一 Profile。手动登录辅助脚本已移至 `experiments/poc/poc_login.py`，不作为测试命令。
- 自动调度启动即检查，之后约每 60 秒检查；每日时间使用后端电脑本地时区，页面今日统计使用 Asia/Shanghai。

## 日常开发、测试与 CI

从仓库根执行；按影响范围选用。测试使用隔离 fixture、临时 SQLite 和 mock；前端 Vitest 不启动浏览器。

```powershell
$env:PERSONAL_WORKBENCH_DISABLE_SCHEDULER = '1'
Push-Location backend
..\.venv\Scripts\python.exe -m pytest tests
Pop-Location
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
powershell.exe -ExecutionPolicy Bypass -File tests/dev-port.ps1
git diff --check
```

禁用 scheduler 不等于隔离数据库；测试必须使用 fixture、临时 SQLite 和 mock。不要用真实采集、客户发送或正式迁移验证工程改动。[CI](.github/workflows/ci.yml) 使用 Windows Runner、Python 3.12 / Node 22，执行后端 pytest、Vitest、Typecheck 与 Build。前端 UI 行为按需人工验收。

## V2 Vibe Coding 工作流

需求判断 → 源码核对 → S/M/L 分级 → 按需 Spec / POC → 实现 → 自动测试 → 自审修复 → Commit / Push → ChatGPT 独立 Review → 修复与最终验收。

| 级别 | 典型范围 | 最小要求 |
| --- | --- | --- |
| S | 文案、文档、局部无契约小修 | 源码核对、相关检查与 Diff 自审 |
| M | 模块内功能、API/UI 调整、工程流程 | 简短计划、验收条件、受影响测试 |
| L | 身份、金额、迁移、调度并发、真实外部写入 | 正式 Spec、兼容 / 恢复方案、边界回归 |

入口 Skills：需求与合同用 `workbench-spec`，实现验证用 `workbench-delivery`，只读审查用 `workbench-review`；Bug、前端、TDD 等按需选择，见[Skills 路由](docs/engineering/skills.md)。

任务内检查通过、阻断解决后，Codex 默认精确暂存任务文件，使用 Conventional Commit 自动提交并推送允许的当前远端分支，核验远端 SHA；不 force push 或覆盖未知改动。Push 仅表示工程同步。ChatGPT 必须独立读取固定 SHA 的 GitHub Diff、关联源码与测试；自审和 CI 不替代独立 Review，未审标待审。完整规则见[正式工作流](docs/engineering/workflow.md)和[根准则](AGENTS.md)。

## 本地数据与备份

- `backend/data/personal_workbench.db`、备份、SQLite sidecar 和客户触达运行数据均保留原路径。运行中的 SQLite 不应只复制主文件；使用 SQLite 在线备份，或安全停写后完整备份并验证可恢复性。
- `.browser-profile/` 包含登录状态，`.env*` 可能含凭证，禁止提交或随意重置；`.venv/` 是 Python 运行依赖。
- `logs/`、`.artifacts/`、`docs/qa/` 和 `.tmp/` 可能保存排障证据或验证副本，先确认用途再清理；不要把隐藏于 VS Code 当成可删除。
- Identity V2 之后的多商品写入不能靠直接 downgrade 恢复，参见[Identity V2 Spec](docs/specs/product-library-identity-v2.md)的备份恢复约束。

更多入口：[产品](docs/product.md) · [架构](docs/architecture.md) · [数据模型](docs/data-model.md) · [业务 Spec 索引](docs/specs/README.md) · [UI 规范](docs/ui-system.md) · [编码规则](docs/coding-rules.md)。
