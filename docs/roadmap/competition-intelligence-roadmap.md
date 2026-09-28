# 1688 竞争情报工作台开发规划

> 状态：Product Direction V2
>
> 适用项目：personal-workbench
>
> 当前主线：1688 竞争情报
>
> 本文优先级高于临时聊天中的功能想法。后续新增需求如果与本文冲突，应先修改本文或对应正式 Spec，再实施代码。

---

# 1. 产品重新定位

## 1.1 不再定位为

> 1688 竞品监控系统

这个定义过于底层，容易把产品做成：

- 网页采集器；
- 价格监控器；
- ChangeEvent 列表；
- 数据 Dashboard；
- 高级爬虫后台。

这些能力是基础设施，不是产品最终价值。

---

## 1.2 正式定位

> **1688 商品竞争情报工作台**

核心定义：

> **以我方商品组为中心，持续采集直接竞品的真实事实，识别和压缩竞争变化，帮助运营快速判断今天哪些商品最值得关注、发生了什么，并进一步进入组级分析和单品证据。**

系统不是为了展示更多数据，而是为了降低运营人员每天查看竞品的成本。

---

# 2. 产品核心问题

整个产品必须围绕以下三个问题设计。

## 第一层：Dashboard

回答：

> **我今天应该先看哪些我方商品？**

不是：

> 今天哪些竞品发生了变化？

---

## 第二层：Group Detail

回答：

> **这个商品组为什么值得看？我方和直接竞品现在分别是什么状态？**

---

## 第三层：Competitor Detail

回答：

> **这个具体竞品发生了什么？证据是什么？**

---

# 3. 产品核心对象

业务核心对象不再是单个 Competitor。

正式业务层级：

```text
我方商品 / 型号
        ↓
Competitor Group
        ↓
我方商品 + 多个直接竞品
        ↓
Snapshot
        ↓
ChangeEvent
        ↓
Group Change Summary
        ↓
Attention Priority
        ↓
Dashboard
```

例如：

```text
A19 磁吸暖手宝
├── 我方 A19
├── 竞品 A
├── 竞品 B
├── 竞品 C
└── 竞品 D
```

系统真正需要回答的是：

> A19 今天的竞争环境发生了什么变化？

而不是只回答：

> 竞品 B 库存下降了。

---

# 4. 核心产品链路

长期核心链路固定为：

```text
采集事实
↓
生成 Snapshot
↓
检测 ChangeEvent
↓
组级聚合
↓
变化降噪
↓
关注优先级判断
↓
Dashboard 告诉用户先看什么
↓
Group Detail 分析原因
↓
Competitor Detail 查看证据
```

后续开发必须优先强化这条链路。

不要在主链路稳定之前横向增加大量功能。

---

# 5. 三层页面职责

## 5.1 Dashboard

长期定位：

> **今日工作入口。**

它不负责完整分析。

它只需要告诉用户：

1. 今天有多少商品组发生变化；
2. 哪些商品组需要优先关注；
3. 每个组为什么值得关注；
4. 最近发生变化的时间；
5. 一键进入 Group Detail。

Dashboard 不应该再成为巨大的竞品事件表。

---

## 5.2 Group Detail

长期定位：

> **竞争分析核心页。**

负责：

- 我方商品当前状态；
- 直接竞品当前状态；
- 价格横向比较；
- 起批量比较；
- SKU 数量比较；
- 库存事实比较；
- 今日竞争变化；
- 近 7 / 30 天竞争动作；
- 谁最近动作较多；
- 进入单个竞品查看证据。

Group Detail 可以展示事实差距。

但当前阶段不做：

- 自动定价建议；
- 竞争力评分；
- 风险评分；
- AI 决策；
- 销量推断。

---

## 5.3 Competitor Detail

长期定位：

> **证据页。**

负责：

- 商品信息；
- 当前快照；
- SKU；
- 历史趋势；
- ChangeEvent；
- 采集记录；
- 检测时间；
- 上下架事实；
- 原始变化证据。

不要把 Competitor Detail 的大量明细重新搬到 Dashboard。

---

# 6. Dashboard 正式转向 Group-first

当前 Dashboard Group Entry V1 的人工验收暴露了一个产品问题：

虽然已经增加 Group Detail 入口，但页面主语仍然是：

> 哪些竞品发生变化。

因此用户仍然需要自己判断：

> 哪些变化属于 A19？
>
> A19 和 Y35 今天哪个更值得看？

这不符合新的产品定位。

---

# 7. Group-first Dashboard 的目标

Dashboard 的核心目标冻结为：

> **用户进入竞品监控大屏后，10 秒内知道今天哪些我方商品组最值得优先查看，以及为什么。**

页面核心对象改成：

```text
Competitor Group
```

而不是：

```text
Competitor
```

---

# 8. Dashboard 推荐信息架构

第一版目标结构：

```text
PageHeader
监控状态 + 添加竞品 + 立即采集

↓

核心统计

监控商品组
今日有变化商品组
今日涉及变化竞品
异常采集

↓

今日需要关注的商品组

A19 磁吸暖手宝        重点关注
3 个竞品发生变化
1 家降价 · 1 个 SKU 售罄 · 2 家库存调整
最近变化 14:48
[进入组分析]

Y35 暖手宝            建议查看
1 个竞品发生变化
新增 2 个 SKU
最近变化 13:20
[进入组分析]

↓

其他今日暂无明显变化的商品组

↓

采集状态 / 近期整体趋势
```

具体视觉设计在正式 Spec 中冻结。

不要现在提前锁死像素和组件结构。

---

# 9. Dashboard 不再承担什么

Group-first Dashboard 不应继续承担：

- 展开全部竞品；
- 展开全部 ChangeEvent；
- 大量 SKU 明细；
- 价格横向矩阵；
- MOQ 对比；
- 库存详细比较；
- Group Detail mini version；
- Competitor Detail mini version。

这些内容全部下沉到对应详情页。

---

# 10. 关注优先级系统

需要新增：

> **Attention Priority / 今日关注优先级**

它的作用只有一个：

> 决定 Dashboard 中商品组的展示顺序和关注层级。

---

# 11. 内部评分不向用户展示

系统内部可以存在：

```text
attention_score
```

但用户不能直接看到：

```text
A19：82 分
Y35：47 分
```

原因：

1. 分数本身没有直接业务含义；
2. 用户不知道 82 和 75 有什么区别；
3. 容易产生虚假精确感；
4. 容易让产品变成“评分系统”而不是工作辅助系统。

---

# 12. 用户看到的是关注层级

用户侧只显示：

```text
重点关注
建议查看
一般变化
```

名称以后可以轻微调整，但必须表达：

> 查看优先级

不能表达：

> 风险判断

---

# 13. 禁止使用风险标签

当前阶段禁止：

```text
高风险
低风险
危险
安全
竞争力弱
竞争力强
威胁指数
风险指数
```

目前事实不足以支撑这种业务判断。

正确概念是：

> **关注优先级**

---

# 14. 关注优先级必须解释原因

系统不能只告诉用户：

```text
重点关注
```

必须同时给出事实依据。

例如：

```text
A19 磁吸暖手宝
重点关注

3 个竞品发生变化
1 家降价
1 个 SKU 售罄
2 家库存调整

最近变化 14:48
```

用户应该不需要知道内部评分，也能理解：

> 为什么 A19 排在第一。

---

# 15. Attention Engine 的输入

第一版关注优先级可以基于以下事实。

## 15.1 变化类型

例如：

- 商品价格下降；
- SKU 价格下降；
- 起批量降低；
- 商品下架；
- 恢复上架；
- SKU 新增；
- SKU 删除；
- SKU 售罄；
- SKU 恢复有货；
- 普通库存变化；
- 标题变化；
- 主图变化。

---

## 15.2 变化竞品覆盖

例如：

```text
1 个竞品变化
```

与：

```text
5 个不同竞品同时变化
```

关注程度应不同。

重点关注：

> distinct competitor

而不是简单 ChangeEvent 数量。

---

## 15.3 变化范围

同一个商品：

```text
10 个 SKU 各产生一条小库存事件
```

不能简单理解为：

```text
10 次重大竞争动作
```

必须避免 ChangeEvent 数量膨胀导致排序失真。

---

## 15.4 变化幅度

只有事实可靠时才能使用。

例如：

```text
价格 -15%
```

可以比：

```text
价格 -0.2%
```

具有更高关注价值。

但不能强行给以下事件计算幅度：

- 标题；
- 主图；
- SKU 新增；
- SKU 删除；
- 无法可靠计算的价格区间。

---

## 15.5 变化新近程度

可以适当考虑：

```text
最近变化时间
```

但不能让时间完全压过事件类型。

---

# 16. 强事件规则

Attention Engine 不能只是：

```text
所有事件权重直接相加
```

否则会出现：

```text
10 次小库存波动
```

排名超过：

```text
一次明确商品降价
```

因此必须存在：

> **Strong Event Rule**

某些事件即使只有一次，也可以显著提升关注优先级。

候选强事件包括：

- 明确商品级降价；
- 明显 SKU 降价；
- 起批量显著降低；
- 商品下架；
- 多个直接竞品同时调整价格；
- SKU 售罄等结构性变化。

具体规则必须另写正式 Spec，并通过真实例子确认。

---

# 17. 库存变化必须降噪

库存是最容易制造噪音的数据。

规则：

```text
库存下降 ≠ 销量
库存增加 ≠ 补货一定发生
库存变化 ≠ 市场热度
```

系统只能表达：

```text
页面展示库存发生变化
```

不能表达：

```text
卖得很好
爆单
销量增长
销量下滑
```

---

# 18. 库存事件第一版策略

普通小幅库存变化：

> 低权重。

SKU 售罄：

> 较高权重。

SKU 恢复有货：

> 中等权重。

大量不同 SKU 同时明显变化：

> 可以提高组关注度。

但必须经过去噪和聚合。

---

# 19. Attention Engine 第一版开发原则

第一版不要追求数学完美。

目标是：

> **排序结果符合运营直觉。**

开发流程必须使用真实场景验证。

至少准备以下测试场景。

### Case A

```text
A19
1 家商品级明显降价
```

### Case B

```text
Y35
同一个竞品 10 个 SKU 各下降少量库存
```

预期：

```text
A19 应优先于 Y35
```

---

### Case C

```text
A19
3 个不同竞品同时调整价格
```

### Case D

```text
Y35
1 个竞品修改标题
```

预期：

```text
A19 明显优先
```

---

### Case E

```text
A19
竞品商品下架
```

即使只有一个事件，也应该获得较高关注。

---

### Case F

```text
Y35
1 次主图调整
```

通常不应排在重大价格变化前面。

---

# 20. Attention Engine 第一版不能做什么

禁止加入：

- AI 判断；
- LLM 评分；
- 黑盒评分；
- 自动学习权重；
- 机器学习模型；
- 用户画像；
- 动态个性化；
- 复杂规则引擎；
- Redis；
- Elasticsearch。

第一版必须：

> 可解释、稳定、可测试。

---

# 21. Attention Engine 技术定位

评分发生在：

> Backend 聚合层。

Frontend 不允许自己从 ChangeEvent 推算：

```text
哪个 Group 更重要。
```

Frontend 只消费 Backend 输出：

```text
排序
关注层级
事实原因
```

原因：

- 保持统一业务口径；
- 避免多个页面重复算法；
- 容易测试；
- 容易后续调整规则。

---

# 22. Group Dashboard Read Contract

Group-first Dashboard 需要一个正式的组级读取 Contract。

不要让 Frontend：

```text
拿所有 Competitor ChangeEvent
→ 自己 groupBy
→ 自己评分
→ 自己排序
```

正确流程：

```text
Backend
→ 聚合 Group
→ 计算 Attention Priority
→ 生成事实摘要
→ 返回 Dashboard
```

正式 endpoint、字段和排序规则在专门 Spec 中定义。

当前规划文档不提前锁死 API 名称。

---

# 23. Group Summary 与 Dashboard Attention 区分

现有：

```text
/api/competitor-groups/summary
```

定位是：

> Group 管理和基础 Summary。

未来 Group-first Dashboard 的数据需求更复杂：

```text
今日事件领域
变化竞品数
主要变化
关注层级
排序依据
```

不要为了省一个 endpoint，把所有 Dashboard intelligence 强行塞进通用 Group Summary。

正式 Spec 时重新评估：

```text
扩展现有 Summary
```

还是：

```text
建立 Dashboard 专用 group read contract
```

优先保证职责清楚。

---

# 24. 当前已有资产必须复用

以下能力已经完成，不重新建设：

```text
Competitor
CompetitorGroup
group_role
own product binding

ProductSnapshot
SkuSnapshot

CollectionRun
ChangeEvent V2

Dashboard 基础采集统计
Competitor List
Competitor Detail

Group Summary
Group Detail API
Group Detail UI

Asia/Shanghai 时间规则
批量采集
定时采集
生命周期
```

下一阶段只在已有事实链路上增加：

```text
Group-level Attention Layer
```

---

# 25. 当前 Dashboard Group Entry V1 如何处理

当前有三个未提交前端文件：

```text
frontend/src/App.tsx
frontend/src/App.css
frontend/src/App.test.tsx
```

它们属于：

> Dashboard Group Entry V1 实验实现。

人工验收发现产品定位需要调整。

因此：

**暂不 Code Review。**
**暂不 Commit。**
**暂不 Push。**

下一阶段首先重新冻结 Group-first Dashboard Spec。

之后再决定：

- 哪些代码继续复用；
- 哪些代码删除；
- 哪些代码调整。

不要直接全部 revert，也不要直接 commit。

---

# 26. 当前 Group Entry V1 可以复用的部分

大概率仍然有价值：

- Header 的添加竞品；
- Header 的立即采集；
- Summary 独立错误状态思路；
- Group Detail 导航；
- group_id → Group Detail 的入口能力；
- Backend / Frontend 状态隔离模式。

但是否保留必须由新 Spec 决定。

---

# 27. 下一阶段开发顺序

## Phase 0：冻结当前实验状态

目标：

> 不继续优化旧 Dashboard Group Entry。

动作：

- 保留未提交 working tree；
- 不 Code Review；
- 不 commit；
- 不 push；
- 不继续修 UI。

进入产品重新定义。

---

## Phase 1：Attention Priority Spec

先只讨论业务规则。

输出：

```text
docs/specs/group-attention-priority-v1.md
```

冻结：

- 哪些事件重要；
- 事件基础权重；
- 商品级价格 vs SKU 价格；
- 库存降噪；
- distinct competitor coverage；
- 多领域变化；
- 强事件规则；
- 时间因素；
- score 如何内部归一；
- 重点关注 / 建议查看 / 一般变化的边界；
- 用户可见 reason 如何生成；
- 同组事件如何去重；
- 排序稳定性。

本阶段：

**不写代码。**

必须用真实 A19 / Y35 示例人工确认。

---

## Phase 2：Group-first Dashboard Spec

Attention Spec 冻结后再设计 Dashboard。

输出：

```text
docs/specs/group-first-dashboard-v1.md
```

冻结：

- Dashboard KPI；
- 今日关注 Group 列表；
- Group item 内容；
- 关注等级；
- fact reasons；
- 排序；
- 空状态；
- 无变化 Group；
- loading/error；
- Group Detail navigation；
- 采集状态；
- 7 天趋势是否保留；
- 原 competitor table 如何处理。

本阶段：

**不写代码。**

---

## Phase 3：Backend Group Attention Read Model

实现 Backend。

目标：

```text
Snapshot
+
ChangeEvent
+
Group Membership
↓
Group Attention Result
```

至少返回：

```text
group identity

own product

changed competitor count

event domain summary

primary factual reasons

attention level

internal sorting value

latest change time
```

注意：

内部 sorting score 不需要给用户展示。

API 即使返回 score，也应明确：

> 仅用于系统排序。

更优方案是前端只消费已排序列表和 level。

正式 Spec 决定。

---

## Phase 4：Group-first Dashboard Frontend

只消费 Backend contract。

Frontend 不重新评分。

Dashboard 重点实现：

```text
今天应该先看哪些商品组
```

每个 Group：

```text
组名
关注等级
变化竞品数量
核心变化原因
最近变化
进入组分析
```

---

## Phase 5：人工验收

人工验收重点不是：

> 页面好不好看。

而是：

> 我进入 Dashboard 后，能不能快速决定今天先看什么？

至少使用真实多个 Group 测试。

例如：

```text
A19
Y35
风扇
加湿器
```

验证排序是否符合真实运营直觉。

---

## Phase 6：独立 Code Review

人工验收通过以后：

```text
Standards Review
+
Spec Review
```

必须：

```text
P0 = 0
P1 = 0
P2 = 0
```

P3 可记录后延。

然后：

```text
commit
push
```

---

# 28. 下一阶段暂时不要做的功能

在 Group-first Dashboard 稳定之前，不要开发：

- 自动选品；
- 自动定价；
- AI 运营建议；
- AI 竞争力分析；
- 自动匹配竞品；
- 邮件 / 微信提醒；
- 报表导出；
- 多用户；
- 权限；
- 云部署；
- Redis；
- 微服务；
- 实时 WebSocket；
- 销量推断；
- 大模型 Agent。

这些都会分散主线。

---

# 29. 1688 长期差异化方向

普通电商竞品监控主要关注：

```text
价格
库存
商品变化
```

1688 是 B2B 平台。

长期竞争情报应该进一步覆盖：

```text
商品竞争
+
采购条件竞争
+
供应商竞争
```

---

# 30. 未来供应商 Intelligence 候选字段

以后可以逐步验证：

- 是否源头工厂；
- 是否深度验厂；
- 经营年限；
- 所在地区；
- 店铺评分；
- 回头率；
- 采购回购相关指标；
- 是否支持一件代发；
- 是否支持定制；
- 阶梯价；
- 起批量；
- 跨境属性；
- 交付能力；
- 供应商标签。

但：

**没有稳定数据源之前，不进入正式模型。**

必须先 POC。

---

# 31. 长期路线

产品长期可能演进为：

```text
V1
竞争事实监控

↓

V2
Group-level Attention
告诉用户先看什么

↓

V3
商品竞争分析
价格 / MOQ / SKU / 库存

↓

V4
供应商竞争情报

↓

V5
通知 / 关注订阅

↓

V6
AI Summary
自动解释变化

↓

V7
AI Action Assistant
基于可靠事实辅助运营决策
```

其中：

V6 / V7 必须建立在 V1-V5 的可靠事实之上。

---

# 32. AI 的正确位置

AI 不负责制造事实。

AI 未来只应该：

```text
读取可靠事实
↓
总结
↓
解释
↓
辅助用户判断
```

禁止：

```text
AI 猜销量
AI 猜库存
AI 猜竞争力
AI 猜风险
```

---

# 33. 产品核心原则

整个项目长期遵守以下原则。

## 原则 1：事实优先

没有数据就显示未知。

不要补默认值。

---

## 原则 2：减少噪音

不是展示变化越多越好。

重点是：

> 哪些变化值得用户花时间。

---

## 原则 3：Group-first

用户工作对象是：

> 我方商品。

不是数据库里的 Competitor ID。

---

## 原则 4：可解释

任何：

```text
重点关注
```

都应该能够回答：

> 为什么？

---

## 原则 5：不伪造业务结论

尤其禁止：

```text
库存下降 = 销量上涨
库存增加 = 补货
降价 = 竞争力增强
```

只能展示事实。

---

## 原则 6：逐层深入

```text
Dashboard
→ Group Detail
→ Competitor Detail
```

不要一个页面承担全部信息。

---

## 原则 7：简单优先

优先：

```text
明确规则
模块化单体
现有数据库
现有 API seam
```

不为了“未来可能”提前设计复杂架构。

---

# 34. 每次新需求必须检查的四个问题

以后任何新功能，开始开发前先回答：

### 1.

它帮助用户回答哪个问题？

### 2.

它属于：

```text
Dashboard
Group Detail
Competitor Detail
管理页面
采集基础设施
```

哪一层？

### 3.

它使用的是可靠事实还是推断？

### 4.

它是否强化下面这条主链？

```text
采集
→ 变化
→ 组级聚合
→ 降噪
→ 关注优先级
→ 分析
```

如果不能明确回答：

不要立即开发。

---

# 35. 当前唯一主线

从现在开始，项目唯一主线是：

> **Group-level Attention**

即：

```text
如何把大量 ChangeEvent
↓
转成少量值得关注的商品组
↓
告诉用户为什么值得关注
↓
进入 Group Detail 继续分析
```

在这条主线人工验收稳定之前：

不要开启新的大型 Feature。

---

# 36. 下一步

下一步不是写代码。

下一步正式任务：

> **Group Attention Priority V1 需求设计**

需要先冻结：

1. 事件重要程度；
2. 库存降噪规则；
3. 同一竞品多事件去重；
4. 多竞品覆盖加权；
5. 多领域变化加权；
6. 强事件规则；
7. 时间影响；
8. 关注等级；
9. 排序稳定规则；
10. 用户可见事实原因。

完成并人工确认以后，

再进入：

> Group-first Dashboard V1

---

# 37. 当前成功标准

项目近期成功标准不是功能数量。

而是：

> 打开 Dashboard 后，不需要逐个检查竞品，就能快速知道今天哪些我方商品最值得查看，以及为什么。

只要这个问题还没有解决，

就不应该把主要开发精力转移到其他方向。