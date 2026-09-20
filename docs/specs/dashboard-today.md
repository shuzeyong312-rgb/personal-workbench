# Dashboard 今日变化

- “今日”按 Asia/Shanghai（UTC+08）本地业务日计算，查询区间为本地今日 00:00 到明日 00:00 转换后的 UTC 半开区间。
- 只展示当前 `Competitor.is_active = true` 的竞品。
- 一个竞品对应一个 item，今天的全部 ChangeEvent 聚合到该 item 的 `changes`。
- `monitored_competitors` 是 active Competitor 数量；`changed_competitors` 是今日有变化的 distinct active Competitor 数量；`change_events` 是今日 ChangeEvent 数量。
- Dashboard item 按该竞品最新变化的 `detected_at DESC, id DESC` 排序；item 内 changes 使用相同排序。
