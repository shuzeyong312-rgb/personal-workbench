# Personal Workbench 开发准则

正式流程见 [docs/engineering/workflow.md](docs/engineering/workflow.md)。先判断需求价值和更简单方案，再核对源码、调用方、测试与适用 Spec；不默认用户提出的技术方案最优。

- 按 S / M / L 风险裁剪流程。非简单任务先给简短计划及验证方式；小而可逆的歧义说明假设后继续，影响架构、数据、兼容性、用户行为或不可逆操作的歧义先确认。
- 只改当前目标必需内容，复用现有模块与依赖，不顺手重构、格式化或新增推测性能力。Bug 先复现、查全调用方，在共享根因处修复。
- 保留 [编码规则](docs/coding-rules.md)、适用业务 Spec、[UI 规范](docs/ui-system.md) 及 frontend/AGENTS.md 的有效约束。历史 Spec 中的单轮 Git 授权不覆盖当前默认授权；业务合同不因流程变更失效。
- 项目 Skills：需求与合同用 `workbench-spec`，实现验证同步用 `workbench-delivery`，独立审查用 `workbench-review`。按需使用 TDD、Bug 诊断与前端 Skills，不强制加载全部 Skills 或调度子代理。
- 跨会话任务默认由 ChatGPT 将确认的目标、验收条件与原型链接存入 GitHub Issue，Codex 从 Issue/源码按需补正式 Spec，ChatGPT 完成必要独立 Spec Review 后由 Codex 继续开发；Issue 非强制，Spec 不重复照抄 Issue。两种 Review 意见优先直接记在关联 GitHub Issue/审查文档，Codex 从 GitHub 读取，不要求用户反复转发长提示词；新开 Codex 会话不是门槛。
- 开始检查 HEAD、分支、工作区、upstream 与远端差异。保留未知并行改动；只暂存本任务文件或明确的 hunks，禁止 `git add .` 混入无关变更。
- 默认授权 Commit + Push：任务范围实现、相关测试、自审完成且阻断问题解决后，使用 Conventional Commit 自动提交并推送当前任务允许的远端分支，无需再次询问；核验远端 SHA。不得 force push、覆盖未知并行修改或破坏生产数据。明确的本轮限制优先。
- 测试使用隔离数据库、fixture 和 mock，不运行 dev.ps1 验证，不依赖真实 1688 登录、桌面客户发送或生产库。未知数据不得伪造；历史有效事实不得因采集异常清空；异常不等于下架或零库存。
- Push 是工程同步，不代表验收或发布。Push 后由 ChatGPT 独立读取固定 SHA 的 GitHub 源码和 Diff 并将结论留在 GitHub；自审、CI、子代理审查均不得冒充该审查。未独立 Review 时明确待审。
- 最终报告范围、实际测试结果、独立审查状态、分支/SHA/GitHub 链接、遗留风险及是否达到验收条件。阻断失败、敏感数据疑虑或远端冲突不能宣称完成；保留安全成果并说明阻碍。
