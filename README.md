# Personal Workbench

个人 Windows 本地 Web 工作台。当前核心是 **1688 商品竞争情报**：围绕我方商品组采集可靠事实，用 Group Attention 帮助判断今天先看哪些组，再进入组内分析和单品证据。首页和自动上架已有占位页，不代表这些业务已实现。

## 当前已实现

- 大屏统一“添加监控商品”：先验证真实店铺和商品资料，再原子保存商品、baseline 快照及成功采集记录；按已配置我方店铺识别 self / competitor。
- 我方商品与竞品列表分流管理，支持搜索、筛选、前端分页、停止/恢复监控；竞品支持批量分组和永久删除，我方商品只支持单条绑定/解除分组及单条永久删除。
- 竞品分组 CRUD、Summary、每组最多一个我方基准商品；删除组保留商品和历史。
- Group-first Dashboard：Backend 返回关注组顺序、等级和事实原因；采集概览与近 7 天趋势作为辅助信息。
- Group Detail V1：比较价格区间、MOQ、SKU 数量及完整库存，区分我方与直接竞品的今日事件和近 7 / 30 天动作；单品详情提供快照、图库、趋势、SKU、变化与采集证据。
- 统一 Batch Runner：串行采集、商品间隔、主动休息、验证冷却和有限自动续采；采集任务页展示内存批次及持久化单商品历史。
- 系统设置：我方店铺及九项采集配置；自动采集可关闭，支持 rolling_24h / fixed_daily 和 catch_up / skip。

库存变化不等于销量。正式模型没有销量、企业主体或新经营指标；销量 POC 证据不能当作生产能力。系统设置视觉改版是局部试点，全局视觉基线仍有效。

## 技术栈

| 层 | 当前实现 |
| --- | --- |
| Frontend | React 19、TypeScript、Vite 6、原生 CSS / SVG |
| Backend | FastAPI、Uvicorn，模块化单体 |
| Database / ORM / Migration | SQLite、SQLAlchemy、Alembic |
| Collector | Python Playwright、本机 Google Chrome、持久化登录 Profile |
| 验证 | pytest、Vitest、Playwright E2E |

自动调度在 FastAPI lifespan 内运行，执行复用唯一 Batch Runner；没有 Redis、Celery、消息队列或云端调度。

## Windows 本地启动

前置条件：安装 Python（支持当前依赖）、Node.js / npm 和 Google Chrome。在仓库根目录用 PowerShell 安装依赖；`dev.ps1` 不会代为安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm --prefix frontend ci
.\dev.ps1
```

若本机策略阻止脚本执行，可用 `powershell.exe -ExecutionPolicy Bypass -File .\dev.ps1` 启动。

以 [dev.ps1](dev.ps1) 和 [Vite 配置](frontend/vite.config.ts) 为准：

- 固定检查根目录 `.venv\Scripts\python.exe`、`frontend/node_modules` 和 `vite.cmd`。
- 启动前在 backend 目录执行 `alembic upgrade head`；失败则不启动服务。它会升级本地工作数据库，已有数据启动前应确认备份。
- Backend：`http://127.0.0.1:8200`，Uvicorn `--reload`；Frontend：每次启动由 Windows 分配可绑定端口，地址显示在启动输出及 `logs/frontend.log`，Vite 自动打开浏览器，代理 `/api` 到 8200。避免固定端口落入 Windows 动态变化的 TCP 保留范围；再次运行脚本仍可停止服务。
- 两个服务以隐藏 PowerShell 进程启动，日志写入 `logs/backend.log`、`logs/frontend.log`。不会杀掉占用端口的无关进程；Backend 固定端口启动失败时需查看日志处理。
- 两个项目服务都在运行时，再执行脚本会强制停止两者；只有一个存在时，会清理项目残留再执行 migration 并重新启动。脚本是启动/停止切换器，不是独立 stop 命令；强制停止不等于协作式 shutdown。
- SQLite 文件为 `backend/data/personal_workbench.db`；正式采集使用根目录 `.browser-profile` 保存登录态。首次使用应确认 Chrome / 1688 登录可用，并在系统设置核对我方店铺。
- Backend 运行时才检查自动任务，启动即进行首次检查，之后约每 60 秒检查一次（执行耗时会影响间隔）；关机或休眠时不采集。fixed_daily 使用 Backend 所在电脑本地时区，页面“今日”统计使用 Asia/Shanghai。

## 文档与开发流程

先读 [协作方式](docs/roadmap/vibe%20coding协作方式.md)，再读 [产品](docs/product.md)、[架构](docs/architecture.md)、[数据模型](docs/data-model.md)、[UI 规范](docs/ui-system.md)、[开发规则](docs/coding-rules.md) 和 [Spec 状态索引](docs/specs/README.md)。局部业务规则按索引查找后续正式 Spec，历史合同不直接改写为今天的规则。

```text
需求判断 → 必要 POC → Spec → 自检 / 纯 Spec 提交推送
→ ChatGPT Spec Review / Freeze → 最小实现 / 自动验证
→ 按风险人工验收 → 独立 Standards + Spec Review / Final Gate
→ 获授权后聚焦 Commit / Push / 远端核验
```

常用验证（按任务范围选择）：E2E 首次使用需在 `frontend` 目录执行 `npx playwright install chromium`。QA 专用 Vite 端口为 5201，由配置自行启动，不启动 Backend；受控 mock 必须与真实 Backend 隔离。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run qa:e2e
git diff --check
```

## 后续重构计划（尚未实现）

以 [重构计划书](docs/roadmap/competition-intelligence-restructuring-plan.md) 为准：Track A 优先交付现有事实的组内竞争位置；Track B 可并行开展经营指标增量 POC，只阻塞新指标产品化，不阻塞 Track A。组内排名、可比 SKU 确认、企业主体建模、新经营指标、Group Detail V2 和管理导航融合都需要后续正式 Spec 与授权。

AI 建议、自动定价、自动选品、自动上架、多用户、多平台和通知不属于当前已实现业务。
