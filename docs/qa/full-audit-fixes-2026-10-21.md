# Full Audit 修复验收 — 2026-10-21

审查基线 `21e3d96..919a064`。六项原缺陷全部关闭，独立 Standards 与 Spec/Integration Final Gate 均 PASS；修复范围剩余确认 P0/P1/P2 = 0/0/0。自动采集静默永久停止在修复前重评为 P1 可靠性缺陷，现已关闭。

## 修复范围

- 身份迁移：索引 DDL 前检查含 NULL 型号的精确重复；拒绝时保留数据、revision 和索引，不自动清理。
- 自动采集：真实 SQLite BUSY/LOCKED 按原间隔重试；准备查询不遗留 reservation，派发失败的持久化清理先于新计划；失败任务仍保证 shutdown。未知非锁故障继续抛出。
- 产品库：无效价格草稿提示实际生效条件，明确当前筛选报价范围，保留原校验与查询规则。
- 竞品组：原生模态处理初始焦点、Tab/背景隔离、Escape、提交期间禁关和焦点恢复。
- 大屏：today 与 attention 独立请求代次保护，旧成功/失败不覆盖新状态，也不使旧调用者误报刷新失败。
- E2E：适配当前首页入口及侧栏精确定位，原业务断言保留；不删测、不新增 skip、不延长超时。

## 冻结代码后的实际回归

| 检查 | 结果 |
|---|---|
| 后端完整 pytest | 728 passed，92 warnings |
| 前端完整 Vitest | 223 passed |
| TypeScript / 生产构建 | tsc --noEmit 与 vite build 通过 |
| Chromium E2E | 154 passed，0 failed，1 原有条件 skipped（共155项） |
| 独立 Final Gate | Standards PASS；Spec/Integration PASS |
| git diff --check | 通过 |

新增后端8项、Chromium5项回归，并增强价格筛选既有断言。原27项E2E失败全部恢复，其所在4个文件定向29项通过。

红绿验证覆盖：真实临时旧版库重复迁移拒绝及回滚；真实 SQLite 锁解除后的下一 tick；reservation/持久化清理/shutdown；旧成功与旧失败乱序；弹窗提交锁和背景焦点；无效草稿实际查询条件。数据库写入验证均为隔离 SQLite，未重跑正式迁移。

前端首次并发验证时为222通过/1个5秒超时；未修改测试或阈值，同源码在其它重负载结束后串行完整重跑223通过。原A19手工响应检查缺少 GROUP_REAL_RESPONSE，保留原条件跳过，不记为通过。

## 本轮正式运行冒烟

- 未发现其他正在运行且修改同工作区的 Codex 任务；无后台 Python 服务、无未完成采集批次。旧前端已停止并重启。
- 直接启动 Uvicorn 与 Vite，未运行会自动迁移的 dev.ps1。后端 8200，前端 14096，均只绑定127.0.0.1。
- 自动采集保持原 enabled=true / fixed_daily / 09:30 / skip，启动未禁用调度；当前已错过当天时间，按原规则不补采。无手动或强制批量采集。
- 前端代理 health、产品库、厂家、竞品、分组、dashboard、采集记录/批次、配置与采集状态共11个只读API均200。
- 真实Chromium连接运行服务，产品库、大屏、竞品列表、竞品分组、采集记录和设置页面可用，pageerror=0，非GET请求=0。
- 启动完成后日志无异常，采集 idle、runner_active=false、browser_open=false。正式数据库只读 integrity=ok、FK违规0、revision=20261020_17；启动前后全部表行摘要与配置完全相同。
- 本轮测试覆盖的38张原QA图已恢复并核对；日志、截图、SQLite、浏览器资料和临时脚本不随提交发布。.gitignore保留原字节，本轮未修改忽略规则。

## 边界

未执行真实1688采集或长期生产负载，未证明下一个真实09:30窗口的外部站点可用性。自动采集恢复与锁争用已通过隔离回归；运行冒烟不主动制造真实采集。P3文档索引维护未扩大处理。
