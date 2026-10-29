---
name: workbench-spec
description: 为 personal-workbench 判断需求、核对源码并按风险产出 Spec 或隔离 POC；普通小修可只写验收条件。
---

# workbench-spec

先读根 AGENTS.md 与 docs/engineering/workflow.md；有 GitHub Issue 时先读取任务及最新评论、确认的原型/验收条件，再读相关业务 Spec 和真实源码，核对 HEAD、调用方、测试及当前合同。Issue 是任务索引，不是未经审查的技术事实；对 ChatGPT 所写需求也要独立指出源码冲突、不合理前提与风险。

给出 S/M/L、目标/非目标、可观察验收条件及必要测试。S 不建正式 Spec；M 规则不清或跨状态时写短 Spec；L 写正式 Spec、兼容/恢复与风险，关键不确定性先隔离 POC。正式 Spec 放 docs/specs，证据放 docs/research；更新必要索引，保留历史合同。已有 Issue/原型的确认内容优先稳定引用，Spec 集中补齐技术合同、数据/API、边界和测试，不复制整份 Issue 或机械扩充 user stories。

需要独立 Spec Review 时，推送可审查的 Spec 和引用，提供固定 SHA 并通过 Issue/相关审查记录交接；未获独立 Review 不自称冻结。审查结论已留在 GitHub 时主动读取，按明确的通过/有条件通过/阻断结论处理修正；有条件通过且满足裁决的修改可继续，新的重大业务冲突仍须重新决策，不反复要求用户转发同一份意见。

Issue 是默认跨会话入口但非强制，纯 Spec 任务不自动进入业务实现；需同步时按正式工作流的默认 Commit/Push 规则交付。低风险歧义说明假设继续，重大业务/数据歧义先确认。
