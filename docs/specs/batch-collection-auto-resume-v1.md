# 批量采集验证自动冷却与断点续采 V1 Spec

状态：待实现；本轮只定义 Spec，不修改业务代码。

本 Spec 引用并局部 supersede [`batch-collection.md`](batch-collection.md)。除“局部变更”明确列出的条款外，单 Runner、HTTP polling、headed Chrome、`.browser-profile`、`COLLECTION_LOCK`、串行采集、普通失败继续、内存 Runtime 和 Backend 重启不恢复等规则全部继续有效。

## Problem Statement

批量采集遇到 1688 `verification_required` 后，当前批次会停在人工验证窗口，验证窗口关闭前持续占用资源；关闭后也只能由用户重新发起批次，无法安全地在同一批次中冷却后重试触发验证的竞品。这样既增加人工操作，也容易让用户误以为当前商品已经完成或被永久跳过。

## Solution

验证触发后，Runner 立即停止新的 1688 请求，自动关闭当前 Browser/Context，并在同一内存 batch、同一 `.browser-profile` 和同一 `COLLECTION_LOCK` 下进入 `cooling_down`。默认冷却 10 分钟；冷却结束后首先重新采集刚才触发验证的 competitor，该访问同时承担恢复探测，不创建额外探测请求。

恢复最多进行 2 次。任一恢复成功后，当前 competitor 只产生一个最终逻辑成功结果，Runner 按原顺序继续 remaining IDs。恢复再次触发验证时，重复“关闭 Browser → 冷却 → 重试当前 competitor”。超过最大恢复次数后，停止自动循环，回到现有人工 `verification_required` 语义。

## User Stories

1. 作为批量采集用户，我希望验证触发后系统立即停止新的 1688 请求，以免继续扩大风控影响。
2. 作为批量采集用户，我希望触发验证的 competitor 保留在当前未完成项中，以便恢复时从正确断点继续。
3. 作为批量采集用户，我希望验证 Browser 自动关闭并进入明确的冷却状态，以便不必手动清理窗口。
4. 作为批量采集用户，我希望看到冷却剩余时间、自动恢复次数、完成数和剩余数，以便知道批次何时继续。
5. 作为批量采集用户，我希望冷却结束后系统先重试原 competitor，而不是跳过它或创建独立探测请求。
6. 作为批量采集用户，我希望恢复成功后后续 competitor 继续按原顺序处理，且不会创建第二个 batch 或重复统计已完成商品。
7. 作为批量采集用户，我希望连续触发验证时自动恢复次数准确累计，超过 2 次后回到人工验证处理。
8. 作为系统维护者，我希望冷却可被 stop event 中断，Backend shutdown 能关闭资源并释放锁，不留下不可停止的 Runner。
9. 作为批量采集用户，我希望冷却期间不能启动第二个 batch、daily collection、单条采集或需要该锁的删除操作。

## Implementation Decisions

### 局部 supersede 范围

本 Spec 仅 supersede `batch-collection.md` 中以下旧规则：

- verification 后必须一直保留 Browser 等用户关闭；
- verification 后不自动续跑；
- verification 后不自动重试；
- verification 当前项立即作为 batch terminal item 计入 `completed`。

新规则下，验证当前项不是最终逻辑结果，不增加 `completed`；当前项和其后未启动项都保留在 `remaining`，原始顺序不变。验证 attempt 可以继续写入真实 `CollectionRun`，但同一 competitor 在 batch 的 `completed` 和最终 `items` 中只按最终逻辑结果统计一次。

### Runner 与状态机

保留现有单进程、单 Runner、内存 Runtime 和 `GET /api/competitors/collect-batch/status` polling。状态至少包括：

```text
idle → running → completed
             ├→ cooling_down → running
             └→ verification_required (人工兜底)
```

验证路径固定为：

1. 当前 competitor 抛出既有 `1688_verification_required` 语义后，立即禁止下一个 1688 请求。
2. 当前 competitor 不计入 `completed`；`current_competitor_id` 仍指向它，`remaining` 包含它及所有未启动 ID。
3. 关闭当前验证 Browser/Context，设置 `browser_open=false`、`runner_active=true`，保持 `COLLECTION_LOCK`，状态进入 `cooling_down`。
4. 冷却结束后使用同一个 persistent `.browser-profile` 重新启动 headed Browser/Context，首先采集该 `current_competitor_id`。
5. 成功或普通失败时，当前 competitor 得到最终逻辑结果并只统计一次；成功后继续剩余队列，普通失败按原规则继续。
6. 再次验证时重复关闭和冷却流程；验证再次发生后，`auto_resume_attempt` 加 1。
7. `auto_resume_attempt` 表示已经进入过的自动恢复冷却次数，`auto_resume_max=2`。当第 2 次自动恢复重试仍触发验证时，不再进入新的自动循环，进入现有人工 `verification_required` 兜底。

人工兜底时召回 Chrome 并 `bring_to_front()`，保持现有人工处理、手动关闭 Browser、Runner 仍活跃和锁在 Browser 关闭后释放的语义。本轮不判断人工验证是否完成，也不因页面变化自动恢复。

### 冷却与资源边界

- 默认冷却时长为 10 分钟，集中定义为单一 Runtime/Runner 配置值；不得在等待逻辑、状态序列化或前端散落 magic number。V1 不提供用户修改冷却时长的配置入口。
- 冷却使用现有 `stop_event` 可中断的等待方式；不得使用不可中断的裸 `sleep`。
- 冷却期间 `browser_open=false`、`runner_active=true`，且 `COLLECTION_LOCK` 从验证触发持续持有到 batch 完成、人工 Browser 关闭或 shutdown 清理结束。
- 冷却期间所有需要该锁的 batch、daily collection、单条采集和删除操作均按现有 `collection_in_progress` 语义拒绝；不提供“立即绕过冷却继续”按钮。
- cooldown 结束重启的是同一 persistent profile，不复制 Profile，不使用 stealth/proxy，不操作滑块或绕过验证码。
- Backend shutdown 必须设置 stop event，使冷却立即退出；随后关闭 Browser/Context（如仍存在）、清理 Runtime、释放 `COLLECTION_LOCK`。Backend 重启后不恢复内存 batch，V1 不新增持久化任务表。

### Runtime/status contract

现有 status contract 保持原字段和计数语义，并新增以下字段：

```json
{
  "status": "running | cooling_down | verification_required | completed",
  "auto_resume_attempt": 1,
  "auto_resume_max": 2,
  "cooldown_remaining_seconds": 517,
  "browser_open": false,
  "runner_active": true,
  "current_competitor_id": 18,
  "total": 10,
  "completed": 3,
  "remaining": 7
}
```

现有 `idle` 状态继续有效。`cooldown_remaining_seconds` 在 `cooling_down` 时返回非负整数倒计时，在其他状态返回 0；倒计时只反映真实 Runner 状态，不由前端自行推算。`auto_resume_attempt` 和 `auto_resume_max` 在整个逻辑 batch 内保持可读；成功完成后仍保留最终 batch 状态，开启新的 POST 时才重置。

始终满足 `completed + remaining = total`。`completed` 只统计成功或普通失败等最终逻辑结果，不统计验证 attempt；`CollectionRun` 的 attempt 记录不改变该约束。恢复成功后不改变 `total`，不重复计算已成功 competitor，不创建新的 POST batch。

### Frontend behavior

前端继续通过现有 status polling 消费 Runtime，不新增 batch API。`cooling_down` 必须明确显示：

> 1688 验证已触发，浏览器已自动关闭。将在约 X 分钟后自动继续采集（自动恢复 1/2）。

同时显示完成数和剩余数，并随 polling 更新倒计时。冷却期间批量采集、单条采集、daily 相关入口和需要该锁的删除入口保持禁用或现有 busy 语义；不渲染“立即绕过冷却继续”按钮。人工 `verification_required` 仍显示原人工处理提示。

## Testing Decisions

测试外部行为和 API/UI contract，优先复用现有 batch endpoint、Runner fake Browser/collector、`COLLECTION_LOCK` 和 frontend render/polling seams，不为本 Spec 新增测试框架、队列或持久化 fixture。

Backend 至少覆盖：

- 第一次 verification 立即关闭 Browser/Context 并进入 `cooling_down`，不调用后续 competitor；
- `cooling_down` 时 `completed` 不增加，`remaining` 包含当前触发验证的 competitor；
- 冷却结束后优先重新采集同一 competitor；
- 恢复成功后继续后续队列，`total`、`completed`、`remaining` 和最终 item 不重复；
- 连续 verification 的 `auto_resume_attempt` 计数和 `auto_resume_max=2`；
- 第 2 次自动恢复重试仍验证后进入原人工 `verification_required`，召回 Chrome，不再自动续采；
- `cooling_down` 全程持有 `COLLECTION_LOCK`，第二个 batch、daily、单条采集和删除均被拒绝；
- shutdown 能中断 cooldown、关闭资源并释放锁；
- 既有普通失败继续、正常 completed、CollectionRun/Snapshot 保存和单条采集行为无回归；
- 同一逻辑 batch 内不产生第二个 POST batch；Backend 重启不恢复内存 batch。

Frontend 至少覆盖：

- `cooling_down` 文案、完成数/剩余数和倒计时来自 status contract；
- polling 更新 `cooldown_remaining_seconds`，不自行推算错误状态；
- cooling 期间无绕过按钮且采集/删除入口保持 busy/disabled；
- running、completed、人工 `verification_required` 和普通 batch 行为无回归。

## Out of Scope

- 自动滑块、验证码或风控绕过；
- stealth、proxy、复制 Profile、Cookie/Token/HTML 输出；
- 用户自定义冷却时长、手动跳过冷却或并行恢复探测；
- 新增 Redis、Celery、消息队列、依赖、migration、持久化任务表、批次历史或跨 Backend 重启恢复；
- 新增 API、独立探测请求、第二个 Runner、WebSocket/SSE 或改造未涉及的采集流程；
- 修改普通失败、正常 completed、单条采集、daily scheduler、锁和 Profile 的既有规则。

## Further Notes

实现时必须先检查同一批次的 `completed + remaining = total`、锁释放和 Browser 清理，再处理展示细节。恢复探测就是当前 competitor 的重采集，不得另发一次“检查验证是否解除”的请求。除本 Spec 明确局部 supersede 的四条旧规则外，以 `batch-collection.md` 为准。
