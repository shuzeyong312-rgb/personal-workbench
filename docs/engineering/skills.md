# 项目 Skills 审计与替代验证

核对日期：2026-10-26。只治理仓库级 Skills，不卸载用户全局或插件 Skills。

| 入口 | 触发/依赖 | 决策 |
|---|---|---|
| workbench-spec | 需求判断、合同、按需 POC；依赖根准则、workflow、相关源码/Spec | 替代 to-spec；移除缺失的 issue tracker、强制外部发布和冗长故事清单 |
| workbench-delivery | 已授权实现、验证、自审、Git 同步；依赖 workflow 和实际工具 | 替代 implement；不强制全量测试或串联所有 Skills |
| workbench-review | 固定 SHA 的只读审查；依赖实际需求、Diff/相连源码 | 替代 code-review；保留需求/标准两个维度，不依赖 tracker，不强制双代理 |
| tdd | 用户要求 test-first，或适合回归循环的非平凡逻辑 | 保留 tests.md/mocking.md；去掉重复确认测试边界和缺失 codebase-design 依赖 |
| diagnosing-bugs | 难复现 Bug、错误或性能回归 | 保留复现/反馈/根因循环及 HITL 模板；不用真实生产请求满足普通验证 |
| frontend-design | 普通 UI 设计/实现主入口 | 保留；项目 UI System 优先 |
| ui-ux-pro-max | 新方向、布局与组件方案检索 | 保留数据/脚本依赖；搜索结果是参考，不覆盖 UI 合同 |
| impeccable | 已有页面打磨与视觉审查 | 保留 reference/scripts/agents；编辑 hooks 按 frontend/AGENTS.md 默认关闭 |
| emil-design-eng | 复杂交互与 motion 细节 | 保留，静态 CSS 小修不加载 |
| animate / find-animation-opportunities / review-animations | 分别实现、发现、审查动画 | 保留专门触发，不与一般 UI 入口并行全加载 |
| react-best-practices | React 渲染、数据流、性能 | 保留 rules 与 AGENTS；CSS-only 不加载 |

替代验证先于删除：新三个 Skills 已覆盖需求/验收、源码核对、分级、实现、验证、自审、默认同步、固定 SHA Review 的旧能力；保留有效业务约束，去掉不适用的 tracker 和流程强制项。删除旧三个 Skill 目录及 lock 中对应来源，避免重新安装旧流程；历史 Spec 对旧 Skill 路径的提及保留为历史记录，当前入口按此映射解释。

本轮场景检查：

- S：改一段文案 → 核对组件与相关检查，无正式 Spec/POC/双代理；自审通过自动同步，独立 Review 标待审。
- M：API 明确增加展示字段 → 核对共享类型/调用方/fixture，相关 pytest/Vitest/TS，按路径 E2E；不自动加数据库表。
- L：身份或调度规则变化 → 正式合同与关键决策 Review，必要隔离 POC/数据恢复验证；默认 Push 授权不扩大为生产写入授权。
- 脏工作区/远端前进/测试阻断 → 保留无关修改、精确 stage，禁止 force push；阻断不得假报完成。
- 纯 Review/纯 Spec → 前者只读，后者不自动实现；均不发 issue tracker 消息。

三个新 Skills 的 frontmatter 使用 skill-creator quick_validate 检查；上述路由和依赖通过源码/文档核对演练，不代表真实业务、真实网站或独立 ChatGPT Review 已通过。
