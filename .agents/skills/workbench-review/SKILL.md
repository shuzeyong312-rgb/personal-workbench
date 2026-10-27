---
name: workbench-review
description: 独立审查 personal-workbench 的 Spec 或固定基线与目标 Diff；按需将审查意见记录到关联 GitHub Issue，不修改业务代码。
---

# workbench-review

读根 AGENTS.md 和 docs/engineering/workflow.md，确认审查类型、独立性及固定 SHA。Codex 自审、子代理或 CI 不能冒充 ChatGPT 独立 Review；工作区自审另列 staged/unstaged，不误用三点 Diff 丢掉未提交内容。

**Spec Review（仅按需、实现前）**：读关联 Issue 的已确认需求、最新评论、原型与指定 SHA 的 Spec，并核对必要真实源码。检查需求偏差、遗漏、额外范围、实现风险、数据迁移和边界/测试是否合理。给出通过、有条件通过或阻断，注明固定 SHA、需修正条款及重大决策是否需要用户确认；不要把已确认的功能清单重复抄成另一份需求。只有真实完成这次独立审查才能称为通过。

**Code Review（Push 后）**：固定 base/head 完整 SHA，读取 GitHub 上真实 Diff 以及相连源码、调用方、相关测试和需求/适用 Spec，不只读 Codex 交付报告。无正式 Spec 的 S/M 以确认的验收条件为准。逐项检查需求符合性、业务规则、失败路径/回归、代码质量与必要性、测试证据、范围和敏感信息。发现给文件/行、触发条件、影响、优先级，区分阻断与建议；遵循项目最小实现。未发现问题也列审查范围和未验证项。访问失败或证据不足不得虚报 PASS。

**GitHub 交接**：独立审查者（ChatGPT）在具备授权工具时将结论直接记录至对应 Issue 评论或审查文档，关联 Spec/Commit SHA、阻断情况和后续动作；Codex 从 GitHub 读取并修复。无法写入时明确标注“未同步 GitHub”，在对话提供可直接转存的结论，不谎称已经提交。审查本身只读代码，不改业务实现、提交或推送；记录 Review 评论不等于修改代码。无需强制双子代理。修复交由 workbench-delivery，Code Review 必须覆盖修复后的新 head。
