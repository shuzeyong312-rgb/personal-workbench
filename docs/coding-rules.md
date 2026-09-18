# Coding Rules

## 1. 核心原则

这个项目长期依赖 AI / Codex 协助开发。

目标不是让 AI 一次写很多代码，而是：

> 每次只做一个明确任务，最小修改，容易测试，容易审查，容易回滚。

---

## 2. 每个任务开始前

开始修改代码前必须：

1. 明确当前任务目标；
2. 阅读与任务相关的 docs；
3. 先确认影响范围；
4. 列出准备修改的文件；
5. 如果需求不清楚，先停下来确认，不允许自行脑补。

不要因为“顺手”扩大任务范围。

---

## 3. Change Surface

每个任务只允许修改完成当前目标真正需要的代码。

禁止：

- 顺手重构无关模块；
- 顺手改目录结构；
- 顺手重命名大量文件；
- 顺手升级依赖；
- 顺手更换技术方案；
- 顺手重新设计 UI；
- 为未来假设需求提前加抽象。

如果一个简单需求需要修改很多无关文件，应先暂停并重新检查方案。

---

## 4. Feature 与 Refactor 分开

Feature：

> 增加或修改用户可见行为。

Refactor：

> 行为保持不变，只改善内部结构。

不要在同一个任务里同时做大范围 Feature 和 Refactor。

如果确实需要先重构才能实现功能，拆成独立任务并分别提交。

---

## 5. 后端规则

- FastAPI Router 只处理 HTTP 输入输出；
- 业务规则放在 Service；
- 数据访问不要散落在 Router；
- 1688 原始数据解析集中在采集适配层；
- 不允许其他业务模块直接依赖 1688 外部字段名；
- 单个竞品采集失败不能中断整个采集任务；
- 不为了“分层完整”强行增加无必要的 Repository / Manager / Factory。

优先简单、直接、可测试的实现。

---

## 6. 前端规则

React 组件负责：

- 页面展示；
- 用户交互；
- 调用后端 API；
- 页面状态。

React 组件中不要放：

- 1688 采集逻辑；
- 数据库存取；
- 核心业务判断；
- 复杂趋势计算。

新页面优先复用现有组件和 Reference Page。

不要每次重新创造：

- Button；
- Input；
- Table；
- Dialog；
- Card；
- Toast；
- 页面布局体系。

---

## 7. 数据库规则

所有 Schema 修改必须通过 Alembic migration。

禁止：

- 只手动改 SQLite；
- 删除历史数据来“解决”迁移问题；
- 修改字段含义但不更新文档；
- 在多个表重复维护同一业务事实。

数据库修改前必须先考虑：

- 当前结构；
- 目标结构；
- 已有数据影响；
- 向后兼容；
- migration；
- 必要时的 rollback。

---

## 8. 测试规则

不追求虚高覆盖率。

优先测试：

1. 核心业务规则；
2. 数据变化识别；
3. 采集解析逻辑；
4. API Contract；
5. 曾经出现过的 Bug。

Bug 修复尽量增加 Regression Test。

测试重点保护行为，而不是测试内部实现细节。

---

## 9. Bug 修复流程

禁止看到报错后直接猜着改。

标准流程：

```text
复现 Bug
→ 找 Root Cause
→ 写 Regression Test
→ 确认测试失败
→ 最小修复
→ 确认测试通过
→ 跑相关测试
→ 检查 Git Diff
```

不要借修 Bug 的机会进行无关重构。

---

## 10. 外部数据规则

1688 属于外部系统，结构随时可能变化。

外部字段：

```text
skuInfoMap
canBookCount
skuPriceScale
saleQuantityList
tradePriceList
mtop.1688...
```

只能在采集适配层出现。

进入内部系统后转换成项目自己的字段，例如：

```text
canBookCount → stock
```

业务层只依赖内部模型。

---

## 11. 依赖规则

新增依赖前必须回答：

1. 标准库能不能解决？
2. 当前已有依赖能不能解决？
3. 新依赖是否真的降低复杂度？

如果只是为了几行简单逻辑，不新增依赖。

V1 不引入：

- Redis；
- Celery；
- 消息队列；
- 微服务框架；
- 复杂 Agent 框架；
- 不必要的状态管理库。

---

## 12. 安全规则

绝不提交：

- Cookie；
- Token；
- 密码；
- 登录凭证；
- .browser-profile；
- .venv；
- 本地数据库中的敏感测试数据。

登录状态只保存在本地忽略目录。

代码、日志、测试输出不得主动打印敏感凭证。

---

## 13. Definition of Done

一个任务只有全部满足以下条件才算完成：

- [ ] 满足已确认的需求 / Spec；
- [ ] 没有无关修改；
- [ ] 没有不必要的新依赖；
- [ ] 相关测试通过；
- [ ] 类型检查通过；
- [ ] Build 通过；
- [ ] 数据库变更有 migration；
- [ ] Loading / Empty / Error 等必要状态已考虑；
- [ ] 没有提交敏感信息；
- [ ] Git Diff 已检查；
- [ ] Code Review 没有严重问题。

“能运行”不等于“完成”。

---

## 14. Git 规则

Commit 保持小而单一。

推荐：

```text
feat: add competitor group creation
fix: handle missing sku stock
test: add stock change regression test
docs: update data model
refactor: isolate 1688 parser
```

避免：

```text
update
fix stuff
big changes
```

一个 Commit 最好只表达一个明确目的。

---

## 15. 文档同步

当稳定事实发生变化时，更新对应文档：

- 产品范围变化 → product.md
- 架构变化 → architecture.md
- 数据模型变化 → data-model.md
- UI 体系变化 → ui-system.md
- 开发规则变化 → coding-rules.md

不要把临时 TODO、短期想法和未确认方案写成长久规则。

---

## 16. AI / Codex 工作方式

AI 默认必须：

- 先理解，再修改；
- 先最小方案，再实现；
- 优先复用现有代码；
- 不因为“更优雅”而扩大修改；
- 不自行改变技术栈；
- 不自行增加产品功能；
- 不自行决定 Unknown 项。

如果遇到不确定信息：

> 停止猜测，明确指出 Unknown。

---

## 17. 最终判断标准

遇到多个实现方案时，优先选择：

```text
效果足够
+
代码简单
+
依赖少
+
修改范围小
+
容易测试
+
容易维护
```

而不是选择“最先进”或“最复杂”的方案。
