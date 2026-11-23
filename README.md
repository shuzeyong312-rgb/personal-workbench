# Personal Workbench

面向个人的 Windows 本地 Web 工作台，用于 1688 竞品监控与采集。数据保存在本机 SQLite。

## 当前能力与边界

- **竞争情报**：我方商品 / 竞品管理、分组与基准商品绑定、监控生命周期、商品快照、SKU / 库存 / 主图变化及采集历史。
- **组内分析**：关注组排序、今日重要动态、历史动作、价格 / MOQ / SKU / 库存比较与组内竞争位置排名；经营指标按证据与可用性展示，上架时间、月成交、年成交、评论和履约等字段不保证每个商品都有值。库存变化不能推算销量。
- **采集任务**：串行批次、间隔与休息、验证冷却和有限续采；自动采集支持滚动 24 小时、每日 1–8 个时间点及有每日次数上限的固定间隔，可配置补采 / 跳过。调度依赖后端持续运行，休眠期间不执行。


## 技术栈与目录

React 19、TypeScript、Vite 6、CSS / SVG；FastAPI / Uvicorn 模块化单体；SQLite / SQLAlchemy / Alembic；Python Playwright + 本机 Google Chrome 采集。自动验证使用 pytest、Vitest、Typecheck 和 Build；必要时人工检查浏览器交互与视觉。调度在 FastAPI lifespan 内运行，复用 Batch Runner。

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

脚本执行策略受限时可用 `powershell.exe -ExecutionPolicy Bypass -File .\dev.ps1`。脚本不安装依赖，启动前会在 backend 执行 `alembic upgrade head`。空库可自动初始化，含退役业务的现有工作库需要走下方显式切换流程。工程验证请使用隔离环境。

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

- `backend/data/personal_workbench.db`、备份和 SQLite sidecar（如存在）位于数据目录。运行中的 SQLite 不应只复制主文件；使用 SQLite 在线备份，或安全停写后完整备份并验证可恢复性。
- `.browser-profile/` 包含登录状态，`.env*` 可能含凭证，禁止提交或随意重置；`.venv/` 是 Python 运行依赖。
- `logs/`、`.artifacts/`、`docs/qa/` 和 `.tmp/` 可能保存排障证据或验证副本，先确认用途再清理；不要把隐藏于 VS Code 当成可删除。

## 旧工作库切换

现有 `20261029_21` 或 `20261030_22` 工作库须显式升级至 `20261123_23`。普通启动会拒绝旧库，删除范围及停写验收见 [退役 Spec](docs/specs/personal-workbench-scope-v1.md)。

1. 停止工作台及其他写入方。确认数据库路径为 `backend/data/personal_workbench.db`，使用 SQLite 在线备份接口制作临时恢复点，并恢复到另一个文件验证版本和完整性。
2. 保持停写，从仓库根目录进入后端，显式执行升级。

   ```powershell
   Push-Location backend
   ..\.venv\Scripts\python.exe -m alembic -x retire_legacy_modules=1 upgrade head
   Pop-Location
   ```

3. 用只读连接核验 revision、退役对象、保留数据和约束，并检查 `PRAGMA integrity_check` 与 `PRAGMA foreign_key_check`。需要启动应用的检查在隔离副本上完成。
4. 所有检查通过后放行工作台启动，随后清理本次临时恢复点和演练副本。放行写入前可用临时恢复点恢复旧工作库。放行写入后如需回退，先停写并保全当前库和新增监控数据。

更多入口：[产品](docs/product.md) · [架构](docs/architecture.md) · [数据模型](docs/data-model.md) · [业务 Spec 索引](docs/specs/README.md) · [UI 规范](docs/ui-system.md) · [编码规则](docs/coding-rules.md)。
