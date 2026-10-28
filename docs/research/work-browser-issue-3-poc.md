# Issue #3 工作浏览器隔离研究（2026-10-28）

基线 `64c0ef3f72223432e6a84df89d9b17f1407aa6e1`。使用 Windows、本机 Chrome、项目已安装的 Python Playwright，在系统临时目录创建全新 Profile；不使用正式 Profile、数据库、1688 或 `dev.ps1`。每次启动使用 collector 的 `channel=chrome`、`headless=False` 与相同 `ignore_default_args`。临时脚本在系统临时目录，不加入产品代码。

## 观察

1. 主进程持有 persistent context（初始 1 个页面）时，另一 Python 进程尝试同一 Profile：返回 `TargetClosedError`，主 context 仍有 1 个页面；关闭主 context 后重新启动同一临时 Profile 成功。这次实验未观察到第二 context 成功，但不证明所有 Chrome 版本或普通 Chrome 的行为。
2. 逐个关闭初始 context 的全部页面后，访问 `context.pages` 没有抛错；因此不能用该调用是否成功证明浏览器仍在运行或已经完全退出。显式关闭 context 后可以再次启动。未验证 close 事件泵和多窗口语义。
3. 另一个实验在子 Python 进程创建 context 并报告 ready 后强制终止该 Python 进程；随即用同一临时 Profile 重启成功（第一次尝试）。这不证明所有崩溃、reload 或孤儿 Chrome 都能退出，也不证明扩展或账号状态持久化。

## 源码核对与不足

`COLLECTION_LOCK` 是进程内 `RLock`；`acquire_collection_slot` 同时检查 `BATCH_RUNTIME` reservation。自动计划在持锁后预留并创建持久批次，再交由 worker；跨进程锁若只在 worker 启动时取得，会留出竞争窗口。当前 lifespan 禁用 scheduler 时提前返回，没有正常分支的 shutdown。`dev.ps1` 使用动态前端端口和 uvicorn reload；Vite 将 `/api` 代理至 8200。

本轮未测试普通 Chrome 占用、两 Backend 跨进程竞争、锁持有者死亡、uvicorn reload、Chrome 崩溃、关闭事件泵、多窗口、账号/扩展状态保持或本地 API 防护。未实施功能，也无法证明插件实际缺失的根因。Spec 给出候选裁决及明确的后续验证，但这些缺口仍须独立复审，不应将有限 POC 视为全部阻断项已解决。

## 追加 POC（独立 Review #2 后）

- `C:\data\personal-workbench\.venv\Scripts\python.exe experiments/poc/issue3_external_chrome.py`：临时 Profile 由普通 Chrome 打开后，Playwright 启动返回 `TargetClosedError`，普通 Chrome 进程仍存活。脚本只结束自己创建的测试 Chrome 进程树。该单次实验不覆盖所有 Chrome 版本和竞态。
- `C:\data\personal-workbench\.venv\Scripts\python.exe experiments/poc/issue3_process_lock.py`：同一临时锁文件第二进程返回 busy；不同文件可获锁；强制结束测试持锁进程后同一文件可获锁。这是 Windows `msvcrt.locking` 文件字节锁的独立机制验证，不是 Backend lifespan、规范路径映射或 reload 集成验证。
- `C:\data\personal-workbench\.venv\Scripts\python.exe experiments/poc/issue3_context_close.py`：临时 Profile 注册 context close 回调，先后关闭两个 Playwright 页面并驱动 Playwright 调用，观察到 close 事件、剩余页面 0；尚未覆盖真实用户关窗或异常事件顺序。

优先方向调整为 Review 建议的 Backend 生命周期独占锁：启动在数据库恢复、scheduler 和 API 服务之前获取；同规范 Profile 的第二 Backend 不能启动；进程内仍使用原有锁和 reservation。该策略避免跨线程传递操作级 OS 锁，但必须先以真实隔离 lifespan/reload 验证正常退出、超时、多个路径、锁故障和竞态，不能把上述文件锁 POC 当作集成结果。两条 shutdown 路径、真实 Vite 代理和 Origin 防护仍未实证。以上仅为验证进展，P0 门槛未全部满足，不连接正式 Profile。

一次隔离 uvicorn `--reload` 测试未能得到预期的释放、重获事件序列：测试进程在等待阶段收到 `KeyboardInterrupt`，临时目录清理同时遇到 Windows 文件占用。该结果不能判定 Backend 锁方案本身失败，也不能证明其安全；不安全的临时测试脚本已移除。随后按测试目录和命令行检查，未发现遗留的测试 uvicorn 进程。需要重新设计隔离进程控制与清理，再复现 reload 的锁交接。按本轮要求暂停功能实施并提交复审。
