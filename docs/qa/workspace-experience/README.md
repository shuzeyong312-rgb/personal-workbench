# 工作台整体体验升级验收

日期：2026-10-20。范围：[Spec](../../specs/workbench-experience-v1.md)。本轮改动按用户授权提交并推送。

## 设计决策与实际 Skill 使用

采用“任务入口工作台”，而非第二个监控大屏。首页突出竞品研判与产品资料两个真实工作职责，四条监控任务直接到达既有页面；系统设置说明身份识别前提，规划工具明确尚未开放。保留默认进入竞品监控大屏的既有行为。

| Skill | 实际职责与执行情况 |
| --- | --- |
| frontend-design | 主导方向；比较数据汇总、等权工具卡片、任务入口三种方案，选择最后一种；以文字、空间和不同职责区域形成层级 |
| UI UX Pro Max | CLI 搜索 `workspace navigation enterprise task launcher --domain ux -n 3` 成功；采用键盘导航、可见焦点、面包屑与导航不遮挡内容规范 |
| Impeccable | context CLI 成功，发现无 DESIGN.md，但实际代码已有 V1.3；按既有视觉世界扩展，读取 new-work/operate/craft-floor；detect 返回 `[]`；独立视觉 Review 与文档摘要落地 |
| Emil Design Engineering | 仅负责导航与操作反馈：高频切页无入场动画，140ms颜色/边线反馈，折叠箭头和 reduced-motion；不引入动画库 |
| React best practices | 首页纯组件、复用 navigate，无数据请求和派生状态 Effect；仅新增窄屏展开状态与焦点 ref |
| Ponytail full | 实施限定 Sidebar/AppShell/HomePage、独立样式与验证；无新依赖/后端能力/通用抽象 |

用户明确授权自主设计和 Review 后实施，因此未采用 Skill 的布局访谈、方案选择页或外部发布流程；保留项目既有 UI System 为最终权威。未启用设计 edit hooks。

## 实际改动

- `frontend/src/App.tsx`：首页内容、侧栏分层、窄屏菜单、跳至主内容与可操作面包屑；保留页面标识、业务导航回调与竞品展开上下文。
- `frontend/src/Workspace.css`：232px侧栏，760px非模态展开导航，首页职责区域与任务行；限定首页/Shell，不重写业务按钮、表格或数据组件。
- 自动检查：更新首页断言和侧栏测试；新增首页入口、390/320px、键盘/ESC/reduced-motion与720px组分析导航检查。两处旧详情e2e改为点击当前商品标题；`git show HEAD:frontend/src/App.tsx` 已证实竞品列表原本即使用标题入口。
- `docs/ui-system.md`、`DESIGN.md`、`.impeccable/design.json`：记录实际视觉与交互合同，未宣称其他业务页内部已迁移。

## 浏览器证据

以下为真实 Chromium 运行当前 React 工作台的截图。API 使用隔离 Fixture，**不是正式业务数据或真实采集结果**。首页本身不使用模拟统计或请求数据。

| 证据 | 文件 |
| --- | --- |
| 改版前首页，1440×1000 | [before-home.png](before-home.png) |
| 改版后首页，1440×1000 | [after-home.png](after-home.png) |
| 桌面导航 | [sidebar.png](sidebar.png) |
| 键盘操作截图 | [keyboard-focus.png](keyboard-focus.png) |
| 390px首页 | [narrow-home.png](narrow-home.png) |
| 390px展开导航 | [narrow-navigation.png](narrow-navigation.png) |
| 720px组分析展开导航 | [group-navigation-720.png](group-navigation-720.png) |

回归截图同目录 `regression-*.png`：监控大屏、我方商品、竞品列表、竞品分组、采集记录、产品库与设置。正常有数据的列表、详情、组分析及产品库流程由既有e2e与test-results截图覆盖。

两轮视觉检查修复：旧移动CSS隐藏 nav、末项分隔线误作用于采集记录、reduced-motion优先级、681–760px组分析菜单继承 pointer-events:none、800px组分析与列表左边缘2px偏差。最终复查确认首页与窄屏导航无横向溢出，组分析维持原滚轮穿透和主区域滚动。

## 测试与 Gate

- 独立 Spec Review：PASS，无必须修改项。
- 独立 Code/UI Review：`ship`；发现的窄屏点击P2已修复并补回归，复审无未解决P1/P2。
- TypeScript + Vite build：PASS。
- Impeccable机械检查：`[]`，仅执行一次。
- 定向 Chromium：36 passed，1 skipped（选择性真实A19检查）。
- 最终全量 Chromium：`npm run qa:e2e -- --workers=3` → **102 passed，1 skipped**，2.2分钟；跳过项是需显式提供数据的真实A19检查。
- 全量 Chromium结束后 Vitest复测：`npm test` → **221 passed**，30.37秒；初轮同样为221通过。
- 键盘截图增补：`npm run qa:e2e -- workspace-experience.spec.ts --grep 'workspace visual evidence'` → **1 passed**，真实Tab/Shift+Tab与 `:focus-visible` 断言通过。
- 独立 Final Gate：**PASS，P0 / P1 / P2 = 0 / 0 / 0**；独立核验范围、导航调用链、首页与窄屏截图、720px点击和800px对齐修复及最终测试结果。

首轮全量回归暴露旧“详情”按钮测试定位与首页新增重复名称；保留测试行为断言，仅修正入口定位。并行Vitest与全量Chromium时，已有浏览器集成测试出现5秒超时（220通过、1超时）；全量Chromium结束后复测221全部通过，未放宽超时或为此修改业务代码。

## 限制与后续

未调用正式API、访问业务数据库或执行外部1688采集；未运行后端测试（后端无改动），未增加Lint工具。视觉验收覆盖首页/Shell与既有业务页面回归，不代表其内部完成新一轮独立设计。默认页仍为大屏，用户后续可按实际习惯另行决定是否调整；本轮不扩大导航持久化、最近使用、搜索等功能。
