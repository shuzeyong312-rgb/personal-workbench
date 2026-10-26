# 工作流 V2 本轮验证记录

日期：2026-10-26。分级 M，仅规范、项目 Skills、文档与 CI；无 backend/app、frontend/src、迁移、业务依赖差异。

## 基线与隔离

开始 HEAD 为 2f37620d2b802f3a1b9d1434aded45618596a3ee，main 与 origin/main 一致，App.tsx / Dashboard.css 已有未提交修改。期间并行提交 ba489904370ae0ba89de8db7aee9e1ee4042cbd5 同步到 main，内容仅该两文件，本轮保留且不重复提交。

验证在 git archive 源码快照内运行，无生产数据或 .browser-profile。后端用现有内存/临时 DB fixtures；E2E 使用 mock 或 library_browser_server 临时数据库。未启动 dev.ps1、正式调度、真实采集或客户发送。临时校验环境安装 PyYAML，未新增项目依赖；本机 Python 3.13，CI 配置 Python 3.12，Linux 后端 Runner 行为待远端执行确认。

## 实际结果

| 检查 | 结果 |
|---|---|
| 3 个新 Skills + 调整后的 TDD quick_validate | 全部通过；Windows 使用 PYTHONUTF8=1 |
| 文档相对链接、CI YAML 结构、浏览器安装顺序、scheduler 禁用 | 通过 |
| git diff --check / 范围与敏感信息自审 | 通过；仅工程文件，未暂存本地验证产物 |
| pytest tests -q（初始基线业务快照） | 823 passed，95 warnings |
| npm test（初始基线及 ba48990 各一次） | 均 228 passed / 2 failed |
| npm run typecheck / npm run build | 通过；现有 bundle 大小警告 |
| npm run qa:e2e（首轮） | 156 passed / 1 skipped / 8 failed |
| playwright test --last-failed（补齐快照 .venv，更新 ba48990 后） | 4 passed / 4 failed |

首轮 E2E 三项因快照缺失 .venv 路径失败，补齐后通过；一项排序用例重跑通过，不能据此断言稳定。其余四项在未改业务/测试源码的 ba48990 快照中仍失败：

- group-directory 两项：现有 mock 缺少 `/api/competitor-groups/{id}/events`。
- home-command-center：1280×720 下侧栏 scrollHeight 756 超过 720。
- settings-experience：校验文案期望“范围内的整数”，实际提示已变化。

Vitest 两项仍失败：`polls cooling batches through retry and refreshes authoritative data once on completion`、`refreshes after cooling_down completes directly and ignores historical completed on first load`，涉及冷却倒计时及完成刷新预期。未通过 skip/continue-on-error 隐藏失败，未修改业务来通过 CI。npm ci 同时报告既有依赖 5 项安全告警（1 moderate / 2 high / 2 critical）；本轮未做依赖升级或安全定性。

## 交付状态

工程规范、Skill 替代、文档与 CI 配置可独立审查并同步；已有业务基线失败继续阻断“全绿 / 最终验收”结论，不扩大本轮范围修复业务。CI 保留完整 pytest / Vitest / TS / Build / Playwright；前端 Windows Runner 配置 .venv 与 Chromium，未伪造通过状态。

Codex 已按需求、有效规范、依赖和范围自审；Skills 的场景路由演练见 skills.md。独立 ChatGPT Review **待审**，不能由本记录或自审替代。远端 Actions 运行结果需以提交对应页面为准；本记录不证明 CI 已通过。最终交接提供 base ba489904370ae0ba89de8db7aee9e1ee4042cbd5 与实际 head 的 GitHub Compare 链接。
