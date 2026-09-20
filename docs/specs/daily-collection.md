# 每日自动采集

- Backend 运行期间自动执行，每小时进行一次 due-check。
- Backend 启动后约 30 秒进行首次检查。
- 仅处理 `Competitor.is_active = true` 的竞品，并按顺序采集。
- 最近一条 `CollectionRun.started_at` 距当前 UTC 时间不足 24 小时则跳过；不存在记录或已达到 24 小时则 due。
- 最近一次 `failed` 尝试同样计入 24 小时窗口，不会每小时重复尝试。
- 自动采集复用现有 `collect_competitor()` 和全局 `COLLECTION_LOCK`。
- 采集 busy 时中断当前 cycle，下一次 hourly check 再尝试。
- 单个 `CollectionError` 只记录本次失败并继续后续竞品。
- Backend shutdown 时协作式停止：唤醒 scheduler，允许当前竞品完成，不再启动下一个竞品。
- 不新增 scheduler 依赖。
