---
name: workbench-delivery
description: 在 personal-workbench 实现已授权任务，按风险测试、自审、自动 Commit/Push 并提供独立 Review 交接。
---

# workbench-delivery

先读根 AGENTS.md 和 docs/engineering/workflow.md。任务有 Issue 时从 GitHub 读取最新需求、关联原型/Spec 与独立审查评论；不等用户重复粘贴长提示词。核对 Git HEAD/分支/工作区/upstream 与 fetch 后差异，记录无关改动；读相关源码、调用方、配置、fixture、测试和适用 Spec。说明分级、最小修改范围和成功条件，非简单任务给简短计划。

正式合同需要独立 Spec Review 时，先核对 GitHub 上的固定 SHA 审查结论；对已明确的裁决按要求收敛后实施，只有出现新的重大合同冲突或有具体依据的高风险阻断才复审。可恢复的 POC 中断、未覆盖的假设性极端情况不得导致整个已授权功能反复停工；自主排障或保守降级，继续安全可实施部分。没有用户授权不得新建 Git Worktree。复用既有架构。Bug 先复现与根因定位；TDD 和 diagnosing-bugs 按需使用，UI 按 frontend/AGENTS.md 选 Skill。新增非平凡逻辑保留有效测试；按正式验证矩阵选择命令，不强迫每次全量测试。禁止依赖生产数据库、真实登录或客户发送。

前端任务如有已确认原型，将其作为方向与核心约束，而非逐像素复制指令；尊重用户明确确认的关键布局和交互，按 `frontend/AGENTS.md` 选用专业 Skills 主动优化视觉、真实状态、可访问性与响应式。一般设计细节自主决策，确需改变核心确认内容先征得用户同意；交付时简述重要设计优化及理由，不将设计审阅变为额外反复停工。

运行必要检查，自审并修复阻断项。精确暂存本任务文件/hunks、检查 staged Diff 和敏感信息；通过后自动 Conventional Commit + Push，无需再次询问。遵循工作流的远端冲突/失败停止条件；不 force push 或覆盖并行修改。

核验远端提交，交付 base/head SHA、GitHub 链接、文件范围、实际测试、遗留风险和独立 Review 状态，并关联已有 Issue/审查记录。ChatGPT Push 后独立 Code Review 不可由自审冒充；主动读取 GitHub 上的审查结论，按审查发现做范围内修复、再验证并自动再次提交同步，最后等待对应新 head 的审查/验收；无须用户重复转述评论。
