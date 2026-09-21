# Dashboard 今日变化与监控概览

## 页面定位

Dashboard 用于每天快速判断今日发生了什么，以及当前采集系统是否正常。数据来自 `Competitor`、`ChangeEvent`、`CollectionRun` 和现有 `BatchRuntime`，不保存 Dashboard 专用数据。

## API

`GET /api/dashboard/today` 按 Asia/Shanghai 业务日计算今日区间；系统缺少时区数据库时固定回退到 UTC+8。响应包含 `date`、`items`、`stats`、`collection_summary` 和连续 7 个业务日的 `trend_7d`。

## 核心统计

- `monitored_competitors`：`Competitor.is_active = true` 的数量，仅作为标题区域的监控中数量。
- `price_changed_competitors`：今日发生 `price_increase` 或 `price_decrease` 的 distinct active competitor 数量。
- `stock_changed_competitors`：今日发生 `stock_changed` 的 distinct active competitor 数量。
- `sku_changed_competitors`：今日发生 `sku_added` 或 `sku_removed` 的 distinct active competitor 数量。
- `failed_collections`：今日 `CollectionRun.status = failed` 的次数。
- `changed_competitors` 和 `change_events` 保留用于今日变化区域的摘要。

## 今日变化

只展示当前 `Competitor.is_active = true` 的竞品。`items` 按竞品聚合，但每个 `ChangeEvent` 在前端表格中占一行，按 `detected_at DESC, id DESC` 展示，最多显示最近 8 条；标题显示当天全部事件数量。表格使用真实的商品标题、店铺、主图、竞品组、旧值、新值和时间。价格和库存仅在两端均为可靠数字且旧值不为 0 时计算变化幅度，其他情况显示 `—`。

当天没有事件时显示紧凑 Empty State，采集状态、趋势和快捷入口仍保持可用。

## 采集状态

`collection_summary` 提供最新一次 `finished_at`；如果系统没有任何完成时间，则使用最新 `started_at`。今日成功/失败按今日业务日内的 `CollectionRun.started_at` 统计，平均耗时只计算 `finished_at != null` 的运行。当前批次直接复用前端已有的 `BatchState`，不建立第二套状态。

## 7 天趋势

`trend_7d` 始终返回包含今天在内、旧到新的连续 7 个 Asia/Shanghai 业务日；无数据日期补 0。变化事件按 active competitor 统计，失败采集按 `CollectionRun` 次数统计。

- `price_changes`：`price_increase` + `price_decrease` 事件数；
- `stock_changes`：`stock_changed` 事件数；
- `sku_changes`：`sku_added` + `sku_removed` 事件数；
- `failed_collections`：失败 `CollectionRun` 次数。

前端使用原生 SVG 折线图，四条线分别表达变价、库存变化、SKU 变化和异常采集；不使用价格平均值、百分比、假 sparkline 或第三方图表库。全 0、单点非 0 和多线重合都保留日期、网格和 0 线。

## 快捷入口与刷新

- 添加竞品：调用现有 `openDialog()`；
- 立即采集：调用现有 `handleBatchAction("all_active")`，忙碌或没有 active competitor 时禁用；
- 竞品列表：调用现有 `navigate("competitors")`。

进入 Dashboard、添加竞品成功、停止/恢复/删除竞品以及批量采集完成后，复用 `loadDashboard()` 获取新数据。Dashboard 不自行建立轮询；批量状态继续由 App 现有 1.5 秒 polling 提供。

## 状态与非目标

支持 loading、明确 error/retry、今日无变化 empty state 和真实 BatchRuntime running/verification/completed/idle 状态。当前不做最近变化列表、昨日百分比、KPI sparkline、价格/销量趋势、导出、价格对比、系统设置入口、新表、新字段、migration、缓存、WebSocket、SSE 或新依赖。
