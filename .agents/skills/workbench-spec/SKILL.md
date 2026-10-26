---
name: workbench-spec
description: 为 personal-workbench 判断需求、核对源码并按风险产出 Spec 或隔离 POC；普通小修可只写验收条件。
---

# workbench-spec

先读根 AGENTS.md 与 docs/engineering/workflow.md，再读相关业务 Spec 和源码，核对 HEAD、调用方、测试及当前合同。指出错误前提、可复用能力和最小方案。

给出 S/M/L、目标/非目标、可观察验收条件及必要测试。S 不建正式 Spec；M 规则不清或跨状态时写短 Spec；L 写正式 Spec、兼容/恢复与风险，关键不确定性先隔离 POC。正式 Spec 放 docs/specs，证据放 docs/research；更新必要索引，保留历史合同。未获独立 Spec Review 不自称冻结。

不依赖 issue tracker，不发布外部工单，不机械扩充 user stories。低风险歧义说明假设继续，重大业务/数据歧义先确认。纯 Spec 任务不自动进入实现；需同步时按正式工作流的默认 Commit/Push 规则交付。
