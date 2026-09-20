# 删除竞品

## Goal

允许用户从竞品列表明确删除不再需要的竞品，尤其用于清理误添加和人工验收期间的测试数据。

“删除竞品”和“停止监控”是两个不同语义：

- 删除竞品：永久删除该竞品及其关联历史数据；
- 停止监控：未来使用 `is_active=false` 保留历史事实，本 Feature 不实现。

## User Flow

1. 用户在竞品列表点击“删除”。
2. 系统显示二次确认 Dialog。
3. Dialog 明确提示：历史快照、变化记录和采集记录也会永久删除且无法恢复。
4. 用户确认后调用 `DELETE /api/competitors/{competitor_id}`。
5. 成功后关闭 Dialog，刷新竞品列表和 Dashboard，并显示成功提示。
6. 用户取消时不做任何修改。

## API

```http
DELETE /api/competitors/{competitor_id}
```

成功：

```http
204 No Content
```

不存在：

```json
{"code":"competitor_not_found","message":"竞品不存在"}
```

存在采集任务占用全局采集锁时返回 `409 collection_in_progress`，避免删除与采集并发写入。

## Data deletion

删除顺序必须满足现有外键关系：

1. ChangeEvent
2. SkuSnapshot
3. ProductSnapshot
4. CollectionRun
5. Competitor

不删除 CompetitorGroup。

## UI

- 删除入口位于竞品列表每行“操作”区域；
- 使用项目现有 Dialog 视觉体系，不使用浏览器原生 confirm；
- 删除按钮使用低饱和危险色；
- 正在采集或正在删除时禁止重复操作；
- 删除失败时保留 Dialog 并展示可读错误。

## Acceptance Criteria

- 可以删除尚未采集的竞品；
- 可以删除已有快照、SKU、变化和采集记录的竞品；
- 删除后关联历史数据不残留；
- 不存在的竞品返回 404；
- 采集进行中不能执行删除；
- 前端删除前必须二次确认；
- 删除成功后列表与 Dashboard 刷新；
- 不新增数据库表、迁移或第三方依赖。
