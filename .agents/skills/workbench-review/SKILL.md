---
name: workbench-review
description: 只读审查 personal-workbench 固定基线与目标 Diff，核对需求、业务规则、回归与测试；支持 Push 后 ChatGPT 独立 Review。
---

# workbench-review

读根 AGENTS.md 和 docs/engineering/workflow.md。固定 base/head 完整 SHA；工作区自审另列 staged/unstaged，不误用三点 Diff 丢掉未提交内容。明确审查来源和独立性：执行者自审不能叫 ChatGPT 独立 Review。

读取真实 Diff 以及相连源码、调用方、相关测试和需求/适用 Spec，不只读交付报告；无正式 Spec 的 S/M 以当前任务验收条件为准，不要求 issue tracker。Push 后独立 ChatGPT 审查读取 GitHub 对应 SHA；访问失败或证据不足应列限制，不给虚假 PASS。

逐项检查需求符合性、业务规则、失败路径/回归、代码质量与必要性、测试证据、范围和敏感信息。发现给文件/行、触发条件、影响、优先级，区分阻断与建议；遵循项目最小实现，不为风格喜好要求无关抽象。未发现问题也列实际审查范围与未验证项。

只报告，不编辑、提交、推送或发送外部消息；无需强制双子代理。修复由 delivery 执行并重新交付新 head，审查结论绑定 SHA。
