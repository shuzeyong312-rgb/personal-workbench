# 竞品生命周期 Feature Spec

## 1. 语义

- `Competitor.is_active=true`：监控中，属于每日自动采集范围。
- `Competitor.is_active=false`：已停止监控，竞品本身和全部历史事实仍保留。
- `status` 仍表示商品自身状态（`unknown` / `active` / `offline`），不表示本系统是否监控。

停止监控与永久删除是两个独立操作。停止后可以恢复；永久删除不可恢复。

## 2. 停止与恢复

停止监控将 `is_active` 设为 `false`，不删除 Competitor、ProductSnapshot、SkuSnapshot、ChangeEvent 或 CollectionRun。停止后的竞品仍出现在列表中，可以查看详情和历史趋势，详情显示“已停止监控”。每日自动采集不再处理它，Dashboard 不计入当前监控竞品。

恢复监控将 `is_active` 设为 `true`，不改变历史数据，也不立即触发 Playwright。竞品会在下一次每日采集周期或用户手动采集时重新进入采集范围。

已停止监控的竞品不能手动采集；Backend 和前端都必须防守。

## 3. 永久删除

永久删除用于清理误添加或验收测试数据。删除在现有 `COLLECTION_LOCK` 内执行，并在一个数据库事务中按依赖顺序删除：

1. ChangeEvent；
2. CollectionRun；
3. SkuSnapshot；
4. ProductSnapshot；
5. Competitor。

CompetitorGroup 不删除。任何步骤失败都 rollback，不留下半删除状态。删除期间如果已有采集任务持有 `COLLECTION_LOCK`，返回稳定的 `collection_in_progress` 冲突错误。

删除成功后，原 offerId 可以重新添加。

## 4. API

### 更新监控状态

```http
PATCH /api/competitors/{id}/monitoring
Content-Type: application/json
```

```json
{ "is_active": false }
```

`is_active=true` 表示恢复，`false` 表示停止。竞品不存在返回：

```json
{ "code": "competitor_not_found", "message": "竞品不存在" }
```

### 永久删除

```http
DELETE /api/competitors/{id}
```

成功返回 `204 No Content`。不存在返回 `competitor_not_found`；采集进行中返回 `409 collection_in_progress`；删除失败返回稳定的 `500 competitor_delete_failed`，不返回 traceback。

### 手动采集保护

```http
POST /api/competitors/{id}/collect
```

当竞品 inactive 时返回 `409`：

```json
{ "code": "competitor_inactive", "message": "该竞品已停止监控，无法立即采集" }
```

## 5. UI

列表保留每个竞品一行：

- 监控中：详情 | 立即采集 | 更多；更多包含停止监控、删除竞品；
- 已停止监控：详情 | 立即采集（禁用） | 更多；更多包含恢复监控、删除竞品。

列表明确显示“监控中”或“已停止监控”，不把商品 `status` 与 `is_active` 混用。停止监控使用普通确认 Dialog，说明历史数据会保留。永久删除使用二次确认 Dialog，显示商品标题（无标题时显示 offerId）和不可恢复的历史数据说明，不使用 `window.confirm()`。

成功操作关闭 Dialog、刷新列表和 Dashboard，并显示 Toast。失败时保持 Dialog 打开，显示可读错误，不伪造成功状态。

## 6. Acceptance Criteria

1. 停止监控只改变 `is_active`，所有历史表数据保留。
2. 停止后每日采集、Dashboard 当前监控统计和手动采集均不再处理该竞品。
3. 详情仍可查看并显示“已停止监控”。
4. 恢复只改变 `is_active`，不立即采集。
5. 删除未采集竞品和有完整历史的竞品都成功。
6. 删除后竞品关联的 Snapshot、SKU、ChangeEvent、CollectionRun 全部清除，CompetitorGroup 保留。
7. 删除事务失败会 rollback；采集中的竞品不会与删除发生竞态。
8. 删除后相同 offerId 可以重新添加。
9. 前端提供更多菜单、确认 Dialog、inactive 采集禁用、可读错误和成功刷新反馈。
10. 本 Feature 不新增数据库字段、表、migration、第三方 UI 库或批量操作。
