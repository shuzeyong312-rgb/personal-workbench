# 工作浏览器管理 V1（修订草案，待独立复审）

需求：[Issue #3](https://github.com/shuzeyong312-rgb/personal-workbench/issues/3)；[首次独立 Review](https://github.com/shuzeyong312-rgb/personal-workbench/issues/3#issuecomment-6459524899)；源码基线 `09296d9c4790e3715b739ad0679caa801f5f616c`。风险 L。证据和未覆盖项见 [隔离研究](../research/work-browser-issue-3-poc.md)。本草案未通过复审，不授权功能实施。

## 目标与范围

设置页添加工作浏览器模块，使用采集进程解析的项目根目录 `.browser-profile` 和 `_launch_context` 的 Chrome、headed、扩展参数。用户自行登录、切换账号及检查扩展。不同 checkout 的路径不同：必须从正式 Backend 所在项目启动；本工作树的 Profile 不等于正式 Profile。不得读取、展示、复制、删除或重建 Profile 或凭据，不自动安装扩展，不改变指标、历史、验证和调度合同。

浏览器状态仅说明占用及最近操作错误；扩展显示「未自动检测，需人工验证」。区域缺失不能证明扩展缺失。用户在工作 Chrome 的 `chrome://extensions/` 检查扩展，在真实商品页确认助手区域，关闭整个浏览器，再按原流程受控采集核对八项指标及诊断；安装扩展不能证明恢复。

## 互斥与支持边界

V1 支持 Windows、本项目一个活跃 Backend worker；多 worker 不作为正常运行方式，但须安全拒绝争用。根据独立 Review #2，优先以规范化 Profile 绝对路径为键，在 Backend lifespan 启动时、数据库恢复和 scheduler 前取得 OS 跨进程独占锁，保持至所有采集及浏览器资源确认关闭后退出。第二 Backend 获锁失败时启动失败，不能提供不受保护的采集 API。锁文件仅作锁载体，不凭文件存在判断占用、不删除 Chrome 锁文件；进程异常退出由 OS 释放锁。本进程内继续使用 `COLLECTION_LOCK` 和 `BATCH_RUNTIME` 的既有 reservation 协议，避免在 reservation 到 worker 的交接中转移 OS 锁。该方向仍需实际 lifespan 和 reload 隔离验证；若失败或不能确认安全退出，停止并复审。

锁不覆盖外部 Chrome：成功获取锁也不代表 Profile 可用。仅启动固定 persistent context；启动失败或无法确认 context 所有权时返回未知/占用，释放已取得的资源，不附着其他 Chrome、重试破坏 Profile、删除锁文件或终止未知进程。外部 Chrome 不参与本锁，因此启动行为须在受支持 Chrome 版本以临时 Profile 测试；若无法证明失败关闭，则不能放行。崩溃后 OS 锁释放，但可能遗留 Chrome；再次启动仍须经过 Chrome 自身占用检查，失败保持未知并提示用户自行关闭有关窗口后重试。无自动删除或强制清理。

## 生命周期及并发

管理状态内部为 `idle → opening → managing → closing → idle`，失败进入 `error`；所有权或关闭无法确认进入 `unknown`，不报告空闲。短状态锁原子认领 opening，重复请求返回现有 opening/managing 状态，不重复创建线程。工作线程独自获取和释放 `RLock`、跨进程锁，创建和操作 Playwright/context；HTTP 与 shutdown 线程只发送退出信号，绝不跨线程关闭或释放。锁竞争或已有 reservation 返回占用；反向竞争由所有采集入口统一拒绝。成功打开必须显示窗口；不能误操作 verification 窗口。

工作线程注册 context close/disconnect 信号，循环用 Playwright 的短时等待驱动事件泵并检查退出信号；页面数为零不是 context 已关闭的证明。用户关闭整个浏览器后收到关闭信号并完成清理，才能释放锁和报告 idle。启动部分成功、异常或 shutdown 均由工作线程 finally 关闭其拥有的 context 和 Playwright，确认关闭后反向释放锁。无法确认时保留 unknown，不能报告空闲；关闭异常不吞掉为成功。正常与 scheduler 禁用的 lifespan 均请求退出并有界等待；超时报告失败且维持占用，不跨线程强关。进程退出后按上节处理潜在遗留 Chrome。Backend reload 与崩溃真实行为需隔离集成验证，不能以本草案中有限 POC 替代。

## 本地接口合同

新增状态 GET 和固定用途的打开 POST；请求不接受 URL、路径、命令或启动选项。操作入口只监听 loopback。POST 同时要求：Host 精确为配置的 `127.0.0.1:8200` 或由受控 Vite 代理转发的原始 `127.0.0.1:<frontend-port>`；Origin 精确匹配本次启动由 `dev.ps1` 传给 Backend 的 `http://127.0.0.1:<frontend-port>`；`Content-Type: application/json`、固定专用 header 且 JSON 空对象。缺失、null、多个或非匹配 Origin 一律拒绝，包括无 Origin CLI；不支持无 Origin 写客户端。未配置前端 Origin 时操作禁用。必须验证代理的实际 Host 转发，若不符合则调整并测试明确的代理配置，不能相信客户端自报 forwarded headers。禁止跨域 CORS 授权；专用 header 使跨站浏览器请求需预检，而服务端 Origin/Host 校验也独立 fail closed。状态响应不含敏感路径或运行异常。只对新接口增加这些限制，不改变其他 API。

## 必要验证与恢复

- 隔离临时 Profile 的实际 Chrome 测试：同 Profile 多进程竞争、外部 Chrome 占用、可见窗口、全部窗口关闭、正常关闭后的同 Profile 状态保持、Chrome/Backend 意外退出、reload 和重启；不得访问真实 Profile、1688、正式 DB。验证 OS 锁持有者终止后释放；无法确认 Chrome 占用时失败关闭。
- mock 与临时 DB 覆盖所有采集入口双向竞争、reservation 交接、自动计划和 verification、并发重复点击、部分启动失败、事件泵、两条 lifespan shutdown 和超时；核对冲突不创建错误持久批次、退出后可采集。保留原异常、历史及调度语义。
- API 覆盖动态合法 Origin/Host、代理链、缺失或恶意 Origin、DNS rebinding Host、form/fetch、预检、JSON/header 缺失和无 Origin CLI；前端覆盖模块导航、原草稿、错误和重复操作，运行相关测试、typecheck、build 与隔离 Playwright。共享规则改动运行后端全量回归。
- 恢复仅允许用户关闭其已知浏览器、等待后重试；不得删除 Profile/Chrome 锁、迁移数据、强杀未知进程或声称插件健康。人工真实环境验收单独进行。

## 实施前复审重点

跨进程锁贯穿 reservation 与批次交接的具体实现仍需验证；API 启动配置的变更及部署兼容性需确认。研究中的 POC 不覆盖所有阻断场景，尤其外部普通 Chrome、reload、状态持久化和扩展注入，不能视为放行证据。复审确定可接受的补充验证与实施边界后再实施。
