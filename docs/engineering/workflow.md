# Personal Workbench V2 开发工作流

本文件是开发流程唯一正式入口。根 AGENTS.md 提供执行摘要，coding-rules.md 管代码约束，ui-system.md 管视觉交互，业务 Spec 管行为合同；roadmap/research 是背景与证据。当前用户明确范围优先。后续已确认的业务条款只覆盖对应旧条款；发现源码与合同冲突应核实，不能用现状自行改写合同。历史文档中的单轮提交禁令、全流程门槛和旧 Skill 路径不再作为当前流程要求。

## 流程与角色

需求判断 → 源码核对 → 任务分级 → 按需 Spec / POC → Codex 实现 → 自动测试 → 自审与修复 → Commit / Push → ChatGPT 独立 Review → 必要修复与再次 Push → 最终验收。

只有稳定事实变化才更新长期核心文档；局部业务规则放 Spec，POC 放 Research，普通 Bug 不强制更新历史 Spec。

用户决定目标、关键业务取舍与最终验收；Codex 可自主完成需求判断、源码核对、实现、隔离验证、自审和同步；ChatGPT 对推送后的固定 Commit 独立核对需求、源码和 Diff。无需先由 ChatGPT 编写实施提示词才能开展已授权任务。

## 风险分级

| 级别 | 判定与例子 | 最小交付证据 |
|---|---|---|
| S 简单 | 文案、局部 CSS、文档、小范围无契约变化的修复 | 简短目标、源码核对、相关检查、Diff 自审；无需正式 Spec/POC/全量测试 |
| M 标准 | 模块内功能、明确规则的 API/UI 调整、工程工作流与 CI | 简短计划、可观察验收条件、影响文件/调用方/测试；按需短 Spec，受影响测试与工程检查 |
| L 复杂或高风险 | 身份/金额/数据模型、迁移、共享契约、调度并发、真实外部写入、大范围重构 | 正式 Spec、兼容与恢复方案、边界和失败测试、受影响全量回归；不确定前提先隔离 POC |

按最高实质风险定级，文件数量不是风险指标；发现共享影响应升级。S 不因跳过正式 Spec 而跳过需求核对或自审。新增正式业务合同在独立 Spec Review 通过前标草稿，不自行宣称 Freeze；L 在影响业务/数据的关键决策确定并完成必要 Spec Review 后实现。已有冻结合同下的小修不重复冻结。

Spec 写问题、目标/非目标、当前源码基线、输入输出/业务规则、边界与失败、兼容/数据影响、验收场景和测试。普通任务可在对话中表达。POC 只验证不确定前提，隔离正式服务与数据；Mock UI 不证明真实采集或桌面行为。

## 实现与验证

先读真实实现、共享调用方、fixture、配置和现有测试，再选最小方案。新非平凡逻辑有一个有效自动测试或自检；Bug 尽可能先保留失败回归测试。无关失败先在干净基线复现，不修改业务来掩盖 CI。

| 影响面 | 必要验证（按影响范围选择） |
|---|---|
| 纯文档/Skill | 引用、触发/依赖、授权冲突、场景演练、Skill validator、git diff --check |
| 后端规则/API | pytest 相关文件；共享规则/L 运行 backend/tests 全量 |
| React/TS | 相关 Vitest + typecheck；构建配置、依赖、交付或共享组件运行 build |
| UI 操作路径 | 对应 Playwright + 可用时真实浏览器检查；局部纯样式无需全量 E2E |
| CI/测试基础设施 | 实际运行所配置命令；推送后核查 Actions，远端未跑完明确 pending |
| 迁移/身份/金额/调度 | 隔离 SQLite 升级、约束、失败/恢复与并发边界，结合相关前后端回归 |

从仓库根运行：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run qa:e2e
git diff --check
```

pytest 从 backend 工作目录运行等价命令 `python -m pytest tests`。测试复用内存/临时 SQLite 和依赖替换；scheduler 禁用变量是 `PERSONAL_WORKBENCH_DISABLE_SCHEDULER=1`，它不替代 DB 隔离。不得运行 dev.ps1、正式 migration、真实登录采集或客户发送来满足普通验证。Playwright 配置只启动 5201 Vite，API 由受控 mock 或 tests.library_browser_server 的临时数据库服务提供，不启动 8200 正式后端。部分 E2E 使用 Windows .venv/Scripts/python.exe，因此前端 CI 使用 Windows Runner 并安装 Python 测试依赖；Chromium 必须在包含浏览器测试的 Vitest 前安装。新增测试也必须保持隔离。

## Git 同步与阻断

1. 开始记录 `git rev-parse HEAD`、`git branch --show-current`、`git status --short`、`git remote -v`；fetch 后核对 upstream 与 ahead/behind。无 upstream 时先核对任务允许的远端分支；detached HEAD 或目标不明不能猜测推送。新建分支默认 codex/ 前缀，无需为每个小任务强建分支。
2. 保留原有未提交改动；精确 stage 本任务文件/hunks，检查 staged Diff、敏感信息、验证证据与范围。Conventional Commit 描述一个目的。
3. 相关检查通过、自审修复且无阻断后自动 Commit + Push；现有 main 且任务未限制分支时允许同步 origin/main。不得 force push、reset 覆盖并行工作、擅自 stash 或提交无关文件。
4. 提交前再次 fetch。远端新提交先核对影响；可安全整合时继续，有未知冲突则保留成果并报告，不盲目重试。Push 后 `git ls-remote <remote> refs/heads/<branch>` 核对 SHA（若远端已前进，fetch 并确认提交可达）。输出 GitHub Commit/Compare 和 Actions 链接。
5. 阻断性测试失败、无法排除敏感信息或远端冲突时，不提交有问题的交付，不宣称完成；可单独同步已验证、可独立交付的安全部分，明确剩余阻碍。

默认授权仅覆盖本项目当前任务的工程提交同步，不覆盖部署、生产迁移/数据破坏、真实客户发送或新增外部消息。用户当轮明确禁令优先。

## 审查与验收

Codex 提交前自审：需求符合性、业务合同、失败/回归、质量、测试证据、变更范围和敏感信息。Push 后交给 ChatGPT 的材料：base/head 完整 SHA、GitHub Diff/Commit、适用需求/Spec、测试命令结果、未覆盖边界与已知问题。

ChatGPT 必须从 GitHub 读取相同 SHA 的 Diff、相连源码与测试，独立判断；不能只复述 Codex 报告。发现给出文件/行、触发条件、影响和优先级。P0/P1 及影响本次验收的 P2 是阻断项；其他建议不扩大任务。Codex 在原范围修复、验证并自动再次 Commit/Push，独立审查必须覆盖新的 head。未有独立 ChatGPT 证据时标“待审”，无访问能力标“无法执行”，不得用自审或 CI 替代。

最终验收条件：范围满足、必要验证通过、阻断问题解决、远端可核验、独立 Review 通过；涉及产品行为时还需用户场景验收。报告实际状态，区分“已实现并同步”“待 Review/CI”“已最终验收”。

## Skills 入口

见 [Skills 审计与替代验证](skills.md)。不强制 issue tracker、全量加载前端 Skills 或每次双代理；独立 ChatGPT Review 的位置固定在 Push 后。
