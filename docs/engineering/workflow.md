# Personal Workbench V2 开发工作流

本文件是开发流程唯一正式入口。根 AGENTS.md 提供执行摘要，coding-rules.md 管代码约束，ui-system.md 管视觉交互，业务 Spec 管行为合同；roadmap/research 是背景与证据。当前用户明确范围优先。后续已确认的业务条款只覆盖对应旧条款；发现源码与合同冲突应核实，不能用现状自行改写合同。历史文档中的单轮提交禁令、全流程门槛和旧 Skill 路径不再作为当前流程要求。

## 流程与角色

默认跨会话协作链路（按 S/M/L 风险裁剪）：

用户 + ChatGPT 确认需求与验收，按需确认 UI 原型 → ChatGPT 建立 GitHub Issue 作为任务入口并关联原型 → Codex 从 GitHub 读取任务、核对真实源码并分级，按需编写 Spec / 隔离 POC → **需要时由 ChatGPT 独立 Spec Review，审查意见留在 GitHub** → Codex 按审查结论继续开发、测试、自审和修复 → Commit / Push → **ChatGPT 对固定 SHA 独立 Code Review，审查意见留在 GitHub** → Codex 按需修复、再次 Push、ChatGPT 审新 SHA → 用户最终验收。

GitHub Issue 是跨会话任务管理与交接的**默认入口，不是强制门槛**；没有 Issue 时可使用已确认的需求、仓库 Spec 或本轮明确指令继续。无需先让 ChatGPT 编写长篇实施提示词，也不要求审查通过后新开 Codex 会话。

用户决定目标、关键业务取舍、原型确认与最终验收；ChatGPT 协助明确需求、按需维护 Issue/已确认原型，负责必要的独立 Spec Review 和 Push 后独立 Code Review；Codex 负责审阅需求可行性、核对源码、技术 Spec、实现、隔离验证、自审、修复和同步。Codex 对 ChatGPT 编写的 Issue 也必须提出独立的源码与风险判断，而不是直接照抄。ChatGPT 不代替 Codex 修改业务代码；用户明确授权的文档、Issue 或原型维护不视为业务代码实施。

只有稳定事实变化才更新长期核心文档；局部业务规则放 Spec，POC 放 Research，普通 Bug 不强制更新历史 Spec。

### 已授权任务的交付优先与暂停边界

- **以可验收的实际交付为目标**：用户已授权实施时，Codex 应在核对源码、确定最小方案后尽快进入实际代码修改；除非用户只要求研究、Spec 或 Review，不得多轮只交 POC、Spec 和审查报告而始终不实现功能。
- **预研按需且有边界**：仅对直接影响当前实现正确性、兼容性或生产安全的关键未知前提做必要隔离 POC；已获结论不重复验证。实验中断、可恢复的环境/脚本问题、暂未覆盖的极端场景，不自动构成禁止编码的证据；Codex 应自主排障、采用保守降级或记录已知限制，并继续可安全实施的部分。
- **独立 Review 不循环**：一次审查的具体技术裁决已明确、没有新重大事实或合同冲突时，按裁决实施，不以相同未验证事项反复申请 Spec Review。Review 不代替开发，额外试验要有明确目的、退出条件和与交付直接相关的价值。
- **仅在实质阻断时暂停相关危险操作**：例如有具体依据的 Profile/凭证/生产数据损坏或不可逆外部写入风险、已复现的关键失败、无法安全确定身份/目标或明确的高风险合同冲突。暂停范围限于受影响步骤；保留并交付已验证的安全成果，说明证据与恢复条件。不得掩盖真实失败、跳过必需回归或宣称未验证功能已通过。
- **开发位置不擅自改变**：默认使用用户当前指定的仓库目录及 Git 分支；未经用户明确授权，不创建或切换到新的 Git Worktree。确需隔离并行修改时先说明原因并取得同意；保护已有工作区改动。

## Issue、Spec、原型及审查交接

- **Issue 管任务**：写清目标、已确认范围、非目标、可观察验收条件与当前状态，链接相关 Spec、已确认 UI 原型、提交和审查意见。它是长期交接索引，不是必须复制一整份技术 Spec 的地方；Issue # 等简短入口足以让 Codex 找到任务。
- **Spec 管正式合同**：Codex 在源码核对后按风险补齐数据/API、兼容迁移、错误边界、技术权衡与测试方案。已有 Issue 的确认内容可通过稳定链接引用，避免大段抄写；不能因为技术实现方便而改写已确认的业务行为。L 级正式 Spec 放 `docs/specs/`；S 级无需正式 Spec，M 按需短 Spec。
- **原型管视觉与交互**：由用户确认，作为原型文件在 GitHub 可访问时才宣称已入库；引用具体路径/提交。原型脚本不等于生产代码，原型里的技术默认值不自动升级为用户确认的业务合同。Codex 自行从 GitHub 获取文件，不要求用户在 ChatGPT 和本地项目之间搬运。
- **独立 Spec Review（需要时）**：ChatGPT 在实现前对照 Issue 的已确认需求、原型、正式 Spec 和真实源码审查遗漏、冲突、越界与高风险技术决定。结论注明固定 Spec SHA、阻断项/可接受的技术裁决，优先直接评论到对应 GitHub Issue 或审查文档。只有明确通过或有条件通过且阻断问题已按裁决收敛，才继续相关高风险实现；重大新争议需再审或由用户决策，不机械反复审查原文。
- **独立 Code Review**：Codex 推送后，ChatGPT 按固定 base/head SHA 读取 GitHub Diff、相关代码和测试，在关联的 GitHub Issue/审查记录中留下结论与问题。Codex 读取 GitHub 评论自行修复并推送新 SHA；不能用 Codex 自审或 CI 替代这一独立审查。
- **减少转述**：Issue/Spec/原型/Review 链接是唯一交接线索，同一 Codex 会话可在 Review 后继续；新窗口可选。每次交接只需任务编号或链接及最新审查入口，不复制整份需求或长提示词。GitHub 写入不可用时须明确说明并交付可复制的审查结论，不得假称已同步。

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
Push-Location backend
..\.venv\Scripts\python.exe -m pytest tests
Pop-Location
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run qa:e2e
git diff --check
```

pytest 须从 backend 工作目录运行 `python -m pytest tests`（使用项目虚拟环境）；部分迁移测试按当前目录读取 alembic.ini，不能直接在根目录运行 pytest backend/tests。测试复用内存/临时 SQLite 和依赖替换；scheduler 禁用变量是 `PERSONAL_WORKBENCH_DISABLE_SCHEDULER=1`，它不替代 DB 隔离。不得运行 dev.ps1、正式 migration、真实登录采集或客户发送来满足普通验证。Playwright 配置只启动 5201 Vite，API 由受控 mock 或 tests.library_browser_server 的临时数据库服务提供，不启动 8200 正式后端。部分 E2E 使用 Windows .venv/Scripts/python.exe，因此前端 CI 使用 Windows Runner 并安装 Python 测试依赖；Chromium 必须在包含浏览器测试的 Vitest 前安装。新增测试也必须保持隔离。

## Git 同步与阻断

1. 开始记录 `git rev-parse HEAD`、`git branch --show-current`、`git status --short`、`git remote -v`；fetch 后核对 upstream 与 ahead/behind。无 upstream 时先核对任务允许的远端分支；detached HEAD 或目标不明不能猜测推送。新建分支默认 codex/ 前缀，无需为每个小任务强建分支。
2. 保留原有未提交改动；精确 stage 本任务文件/hunks，检查 staged Diff、敏感信息、验证证据与范围。Conventional Commit 描述一个目的。
3. 相关检查通过、自审修复且无阻断后自动 Commit + Push；现有 main 且任务未限制分支时允许同步 origin/main。不得 force push、reset 覆盖并行工作、擅自 stash 或提交无关文件。
4. 提交前再次 fetch。远端新提交先核对影响；可安全整合时继续，有未知冲突则保留成果并报告，不盲目重试。Push 后 `git ls-remote <remote> refs/heads/<branch>` 核对 SHA（若远端已前进，fetch 并确认提交可达）。输出 GitHub Commit/Compare 和 Actions 链接。
5. 阻断性测试失败、无法排除敏感信息或远端冲突时，不提交有问题的交付，不宣称完成；可单独同步已验证、可独立交付的安全部分，明确剩余阻碍。

默认授权仅覆盖本项目当前任务的工程提交同步，不覆盖部署、生产迁移/数据破坏、真实客户发送或新增外部消息。用户当轮明确禁令优先。

## 审查与验收

Spec Review 与 Code Review 属于不同关口：前者只在新正式合同和 L 级等必要场景于实现前进行，后者按固定提交在 Push 后进行。两者的决策、修复状态及对应 SHA 均优先记录到关联 GitHub Issue/审查文档，以免重复传递。

Codex 提交前自审：需求符合性、业务合同、失败/回归、质量、测试证据、变更范围和敏感信息。Push 后交给 ChatGPT 的材料：base/head 完整 SHA、GitHub Diff/Commit、适用需求/Spec、测试命令结果、未覆盖边界与已知问题。

ChatGPT 必须从 GitHub 读取相同 SHA 的 Diff、相连源码与测试，独立判断；不能只复述 Codex 报告。发现给出文件/行、触发条件、影响和优先级。P0/P1 及影响本次验收的 P2 是阻断项；其他建议不扩大任务。Codex 在原范围修复、验证并自动再次 Commit/Push，独立审查必须覆盖新的 head。未有独立 ChatGPT 证据时标“待审”，无访问能力标“无法执行”，不得用自审或 CI 替代。

最终验收条件：范围满足、必要验证通过、阻断问题解决、远端可核验、独立 Review 通过；涉及产品行为时还需用户场景验收。报告实际状态，区分“已实现并同步”“待 Review/CI”“已最终验收”。

## Skills 入口

见 [Skills 审计与替代验证](skills.md)。Issue 是跨会话交接的默认入口但非门槛；不强制全量加载前端 Skills 或每次双代理。必要的独立 Spec Review 在实现前，独立 ChatGPT Code Review 固定在 Push 后。
