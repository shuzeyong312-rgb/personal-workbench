# 1688 后台批次与窗口控制验证

## 1. 验证目的

在不修改正式 collector、service、API、数据库或 frontend 的前提下，验证：

1. headed Chrome 是否可以移到可视区域之外并继续执行页面逻辑；
2. 检测到 1688 验证页后是否可以召回窗口、置前并暂停批次；
3. 人工验证完成后是否可以继续并再次移出窗口；
4. 一个 Browser / Context 下并发使用 2 个 Page 是否可行；
5. 并发 2 是否增加 `verification_required` 或造成字段串线。

本轮新增独立 POC：`poc_background_batch_collection.py`。

## 2. 现有正式架构确认

- 正式 collector 使用 Chrome channel、仓库根目录 `.browser-profile`、`headless=False` 和 persistent context。
- 正式 `collect_competitor(db, competitor_id)` 会在创建 CollectionRun、Playwright 采集、解析、保存 Snapshot/ChangeEvent 到最终释放之间持有 `COLLECTION_LOCK`。
- daily scheduler 也会获取同一 `COLLECTION_LOCK`，因此正式采集路径当前是串行的。
- POC 没有调用 `collect_competitor()`，只读一次 SQLite 样本列表，然后在同一个 headed Context 中直接使用 Page 采集；没有共享 SQLAlchemy Session，也没有写数据库。
- 现有 Parser 是纯局部输入处理，没有发现共享可变状态。

## 3. POC 实现

- Browser：每个场景 1 次 `launch_persistent_context`。
- Context：每个场景 1 个，共享同一个专用 Profile。
- 串行场景：1 个 Page，依次处理 3 个商品。
- 并发场景：2 个 Page、2 个 asyncio worker；不同 worker 使用不同 Page。
- 窗口隐藏：CDP `Browser.getWindowForTarget` + `Browser.setWindowBounds`，使用 `(-32000, -32000)` 和 `windowState=normal`，不最小化、不关闭。
- 窗口召回：先恢复 `windowState=normal`，再设置可见坐标和约 `1200x600~800` 尺寸，最后调用 `page.bring_to_front()`。
- 验证检测：复用正式 detector 的 URL、标题、`#nc_1_wrapper` 语义，并适配 async Page；另保留现有 POC 对无 `offerId` challenge HTML 的诊断。
- 验证暂停：`asyncio.Event` + `asyncio.Lock`。检测到验证后不启动新的竞品；当前已开始的 Page 可结束或等待；验证等待有超时。
- 字段：title、offerId、price、SKU 数量、SKU ID、SKU 名称、stock、已有主图研究逻辑；network 只监听真实 response。

## 4. 窗口行为结果

最终批次和独立冒烟均记录：

- 移出前窗口坐标约为 `(40, 60)`；
- 移出后实际坐标为 `(-32000, -32000)`，`windowState=normal`；
- 召回后实际坐标恢复到可见区域约 `(40, 60)`；
- `bring_to_front` 返回成功；
- 再次移出成功；
- Context 关闭后可重新打开同一 Profile，`profile_reopen_probe=true`。

## 5. 串行与并发结果

样本仍为当前数据库中 3 个 active 且有历史成功采集记录的竞品：

| Competitor | offerId | 价格 | SKU 数量 |
|---:|---|---:|---:|
| 3 | `1042199069158` | `38.00 - 38.00` | 4 |
| 4 | `1081895898799` | `40.00 - 40.00` | 3 |
| 5 | `976443859503` | `45.00 - 50.00` | 9 |

最终复跑结果：

| 场景 | 成功数 | verification_required | 最大并发 Page | window sequence |
|---|---:|---:|---:|---|
| 串行 headed | 3/3 | 0 | 1 | PASS |
| 并发 2 headed | 3/3 | 0 | 2 | PASS |

3 个商品的串行 / 并发结果逐商品比较：

- `actual offerId` 全部匹配 expected offerId；
- title、shop、price、SKU 数量、SKU ID、SKU 名称、stock 核心字段均一致，3/3；
- 主图研究逻辑均为 `captured`；
- 未发现 Page 间数据串线。

## 6. 人工验证召回与恢复

首次正式运行中，串行第一个商品实际触发 `verification_required`：

- 控制台输出：`检测到 1688 人工验证，请在浏览器中完成验证。`；
- Chrome 被召回到可见区域并 `bring_to_front`；
- 新采集任务暂停；
- 本次没有执行自动点击或验证码处理。

该次运行没有完成用户人工验证，在超时后安全停止；因此只证明“检测、召回、暂停、超时退出”，没有证明“用户完成验证后自动恢复、再次移出并继续剩余批次”。修复 async 导航轮询竞态后，后续最终批次没有再次触发验证页，无法用正常页面冒充人工恢复成功。

上一轮真实人工操作还记录到：

- `verification_required` 确实曾在真实采集中触发；
- 浏览器召回后，用户在 Playwright 管理的 headed Chrome 中手动拖动滑块；
- 滑块持续显示验证失败；
- 用户随后直接刷新了页面；
- 当时没有留下“刷新后恢复到商品页并继续剩余批次”的完整证据。

因此，Playwright headed 窗口中的“人工滑块验证 → 自动恢复”不能判定为可用。当前 POC 在刷新后的行为是：继续检查同一个 Page；只有验证标记消失、页面解析成功且 expected `offerId` 匹配时才继续；仍为验证页时不自动刷新、不自动点击、不自动重试滑块。

## 7. network 数据

串行和并发最终批次的销量 network 目标接口均为 `network data missing`。

这只表示本轮没有捕获目标 response，不能解释为销量为 0。POC 没有保存完整 response、Cookie、Token 或 headers。

## 8. COLLECTION_LOCK 影响

正式架构中 `COLLECTION_LOCK` 覆盖整个 `collect_competitor()`，所以如果正式并发路径直接复用该入口，两个采集会被串行化或返回 `collection_in_progress`。

本 POC 绕过正式 service，只验证“同一个 Browser / Context 的页面层并发”。正式 Feature 若要支持并发，未来需要把锁边界从整个竞品采集事务重新划分；本轮没有修改正式锁语义。

## 9. 已知限制

- 样本只有 3 个，不足建议的 5 个。
- 人工验证恢复流程未完成真实人工闭环，因此不能判 PASS；上一轮还实际观察到 Playwright headed Chrome 中滑块验证失败，用户随后刷新页面。
- network 扩展接口本轮仍未捕获；缺失不等于销量为 0。
- POC 没有验证更高并发，也没有引入数据库并发写入。
- 没有 pywin32、Windows API、stealth、User-Agent 修改或验证码自动化。

## 10. 结论

### A. Window Management：PASS

CDP 移出、等待页面执行、召回、置前、再次移出均有实际坐标证据；Browser/Context/Page 生命周期正常，Context 关闭后 Profile 可重新打开。

### B. Manual Verification Resume：CONDITIONAL

验证页检测、自动召回、置前、暂停和超时退出已验证；但本轮没有用户完成验证，因此“恢复、再次移出、继续剩余批次”尚未得到真实闭环证据。

### C. Concurrency = 2：CONDITIONAL（页面层 POC）

同一 Browser / Context 的 2 个 Page 并发处理 3 个样本，成功率 3/3，核心字段 3/3 一致，`verification_required` 为 0，没有发现串线。该结论不代表正式 service 已支持并发，因为正式 `COLLECTION_LOCK` 仍覆盖整个采集入口。

由于样本只有 3 个，且本轮实际运行期间曾出现 `verification_required`，尚不能证明并发 2 不会提高风控概率；因此并发结论仅为页面层技术可行，风控稳定性仍未验证。

正式 Feature 建议：暂不进入。先在用户可见环境中手工完成一次验证闭环并重新记录；如果未来正式支持并发，还必须先单独设计并验证 `COLLECTION_LOCK` 的边界和数据库写入策略。

## 11. 普通 Chrome 对照验证

本轮检查到的实际运行参数：

- Chrome executable：`C:\Program Files\Google\Chrome\Application\chrome.exe`
- user data dir：`C:\data\personal-workbench\.browser-profile`
- profile directory：`Default`
- 商品页：`https://detail.1688.com/offer/1042199069158.html`

Playwright Context 已关闭；当前没有发现使用 `.browser-profile` 的 Chrome 进程，也没有发现 `Singleton*` Profile 锁。当前系统中另有普通用户 Profile 的 Chrome 窗口，但它不是本 POC 的专用 Profile，未将其结果混入本验证。

普通 Chrome 对照结果：

- 使用上述同一个专用 Profile 成功启动并打开商品页；
- 未出现 `verification_required`；
- 因未出现验证页，滑块人工完成、刷新恢复和验证后回到商品页均不适用；
- 登录态保留。

本次结果只能证明普通 Chrome 可以复用当前 Profile 的登录态，不能证明普通 Chrome 能完成此前失败的人工滑块，也不能证明 Playwright 与普通 Chrome 在相同风控状态下行为不同。

因此 Manual Verification Resume 仍为 `CONDITIONAL`，正式方案暂不进入实现。
