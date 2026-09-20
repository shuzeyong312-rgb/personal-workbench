# 竞品详情 V1

## 详情 API

`GET /api/competitors/{competitor_id}/detail?days=7`

- `days` 只支持 `7` 和 `30`，默认 `7`；其他值拒绝请求。
- 竞品不存在返回 `404`：`{"code":"competitor_not_found","message":"竞品不存在"}`。
- 详情响应只返回当前 UI 需要的竞品、快照、SKU、价格趋势、变化记录和采集记录字段；只返回 `group_id`，不返回 `group_name`、原始 HTML、外部 JSON、销量或库存聚合。

## 当前快照与 SKU

- `latest_snapshot` 是该竞品全历史中按 `captured_at DESC, id DESC` 选出的最新成功事实，不受 `days` 范围限制。
- 没有快照时，`latest_snapshot` 为 `null`，`latest_skus` 为空数组。
- `latest_skus` 只来自 `latest_snapshot`，按 `SkuSnapshot.id ASC` 稳定排序。
- `stock` 和 SKU `price` 的 `null` 保持 `null`；前端展示为 `—`，不转换为 `0`。

## 价格趋势

- 趋势只使用 `ProductSnapshot.price_min` 和 `price_max`。
- Backend 使用 UTC 的最近 `7×24` 或 `30×24` 小时过滤，包含窗口边界。
- 返回顺序为 `captured_at ASC, id ASC`，同一时间的多条真实快照全部保留。
- `price_min` / `price_max` 为 `null` 时 API 保留 `null`；前端图表只绘制有实际价格的点，全部无价格时显示暂无可用价格数据。

## 历史记录

- `recent_changes` 返回最近 20 条，按 `detected_at DESC, id DESC`。
- `recent_collection_runs` 返回最近 20 条，按 `started_at DESC, id DESC`。
- 采集失败只展示安全的 `error_message`；不展示 traceback 或原始异常。

## 非活跃竞品

`is_active=false` 的竞品仍允许查看详情，以便追溯历史事实；详情显示“已停止监控”，本版本不提供恢复操作。
