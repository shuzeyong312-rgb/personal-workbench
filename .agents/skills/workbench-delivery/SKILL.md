---
name: workbench-delivery
description: 在 personal-workbench 实现已授权任务，按风险测试、自审、自动 Commit/Push 并提供独立 Review 交接。
---

# workbench-delivery

先读根 AGENTS.md 和 docs/engineering/workflow.md。任务有 Issue 时从 GitHub 读取最新需求、关联原型/Spec 与独立审查评论；不等用户重复粘贴长提示词。核对 Git HEAD/分支/工作区/upstream 与 fetch 后差异，记录无关改动；读相关源码、调用方、配置、fixture、测试和适用 Spec。说明分级、最小修改范围和成功条件，非简单任务给简短计划。

正式合同需要独立 Spec Review 时，先核对 GitHub 上的固定 SHA 审查结论；阻断项未解决不开始相关高风险实现，有条件通过则按裁决补齐 Spec 后推进，不自动要求开启新会话。复用既有架构。Bug 先复现与根因定位；TDD 和 diagnosing-bugs 按需使用，UI 按 frontend/AGENTS.md 选 Skill。新增非平凡逻辑保留有效测试；按正式验证矩阵选择命令，不强迫每次全量测试。禁止依赖生产数据库、真实登录或客户发送。

运行必要检查，自审并修复阻断项。精确暂存本任务文件/hunks、检查 staged Diff 和敏感信息；通过后自动 Conventional Commit + Push，无需再次询问。遵循工作流的远端冲突/失败停止条件；不 force push 或覆盖并行修改。

核验远端提交，交付 base/head SHA、GitHub 链接、文件范围、实际测试、遗留风险和独立 Review 状态，并关联已有 Issue/审查记录。ChatGPT Push 后独立 Code Review 不可由自审冒充；主动读取 GitHub 上的审查结论，按审查发现做范围内修复、再验证并自动再次提交同步，最后等待对应新 head 的审查/验收；无须用户重复转述评论。
