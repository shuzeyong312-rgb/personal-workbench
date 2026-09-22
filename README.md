# Personal Workbench

个人 Web 工作台，用软件解决工作中反复出现的问题。

当前 V1 只做：

> 1688 竞品监控

V1 稳定之前，不扩展自动上架、选品、AI 分析等其他模块。

## 当前目标

建立一个可长期使用的竞品监控闭环：

```text
手动添加 1688 商品
→ 加入竞品组
→ 每天采集一次
→ 保存历史快照
→ 对比变化
→ 首页展示今日变化
→ 查看 7 / 30 天趋势
```

## 技术栈

```text
Frontend  React + TypeScript + Vite
Backend   FastAPI
Database  SQLite
ORM       SQLAlchemy
Migration Alembic
Collector Playwright + 本机 Chrome
Test      pytest + Vitest
```

V1 采用模块化单体。

不使用微服务、Redis、Celery、消息队列等复杂架构。

## 项目文档

开发前优先阅读：

- `docs/product.md`：产品目标与 V1 范围
- `docs/architecture.md`：技术架构与模块边界
- `docs/data-model.md`：核心数据模型
- `docs/ui-system.md`：UI 基线与页面一致性规则
- `docs/coding-rules.md`：开发规则与 Definition of Done

原则：

> Docs 是项目长期知识源，代码实现必须与 Docs 保持一致。

## 当前核心能力

竞品监控已进入稳定完善阶段，当前已形成可持续使用的闭环：

- 手动添加 1688 竞品，并按商品型号分组；
- 批量选择采集或采集全部监控中的竞品；
- 自动按每日采集规则保存商品、SKU 和主图快照；
- 识别价格、SKU、库存、标题、主图及商品上下架变化；
- Dashboard 展示今日变化、采集状态和近 7 天趋势；
- 竞品详情查看近 7 / 30 天趋势、SKU、变化和采集记录；
- 支持停止 / 恢复监控、下架后继续监控，以及竞品分组管理。

## 开发方式

本项目长期使用 AI / Codex 辅助开发。

默认流程：

```text
需求
→ Spec
→ 最小实现
→ Tests
→ Git Diff
→ Code Review
→ Commit
```

开发原则：

- 一个任务只解决一个问题；
- 最小修改；
- Feature 与 Refactor 分开；
- 不为未来假设需求提前设计；
- Bug 尽量留下 Regression Test；
- 每次修改都必须可审查、可回滚。

## 当前阶段

当前竞品监控已进入稳定完善阶段，后续以真实采集数据、变化识别和界面细节的持续校验为主。

## V1 Non-goals

当前明确不做：

- AI 分析
- 自动选品
- 自动上架
- 多用户
- 权限系统
- 消息推送
- 云端部署
- 多平台监控
- 复杂爬虫架构
- 多 Agent 编排

新想法可以记录，但不允许扩大 V1。
