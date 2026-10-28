# Issue #3 工作浏览器隔离研究（2026-10-28）

基线 `64c0ef3f72223432e6a84df89d9b17f1407aa6e1`。使用 Windows、本机 Chrome、项目已安装的 Python Playwright，在系统临时目录创建全新 Profile；不使用正式 Profile、数据库、1688 或 `dev.ps1`。每次启动使用 collector 的 `channel=chrome`、`headless=False` 与相同 `ignore_default_args`。临时脚本在系统临时目录，不加入产品代码。

## 观察

1. 主进程持有 persistent context（初始 1 个页面）时，另一 Python 进程尝试同一 Profile：返回 `TargetClosedError`，主 context 仍有 1 个页面；关闭主 context 后重新启动同一临时 Profile 成功。这次实验未观察到第二 context 成功，但不证明所有 Chrome 版本或普通 Chrome 的行为。
2. 逐个关闭初始 context 的全部页面后，访问 `context.pages` 没有抛错；因此不能用该调用是否成功证明浏览器仍在运行或已经完全退出。显式关闭 context 后可以再次启动。未验证 close 事件泵和多窗口语义。
3. 另一个实验在子 Python 进程创建 context 并报告 ready 后强制终止该 Python 进程；随即用同一临时 Profile 重启成功（第一次尝试）。这不证明所有崩溃、reload 或孤儿 Chrome 都能退出，也不证明扩展或账号状态持久化。

## 源码核对与不足

`COLLECTION_LOCK` 是进程内 `RLock`；`acquire_collection_slot` 同时检查 `BATCH_RUNTIME` reservation。自动计划在持锁后预留并创建持久批次，再交由 worker；跨进程锁若只在 worker 启动时取得，会留出竞争窗口。当前 lifespan 禁用 scheduler 时提前返回，没有正常分支的 shutdown。`dev.ps1` 使用动态前端端口和 uvicorn reload；Vite 将 `/api` 代理至 8200。

本轮未测试普通 Chrome 占用、两 Backend 跨进程竞争、锁持有者死亡、uvicorn reload、Chrome 崩溃、关闭事件泵、多窗口、账号/扩展状态保持或本地 API 防护。未实施功能，也无法证明插件实际缺失的根因。Spec 给出候选裁决及明确的后续验证，但这些缺口仍须独立复审，不应将有限 POC 视为全部阻断项已解决。
