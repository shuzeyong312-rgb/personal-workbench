# 1688 Headless 采集验证

## 1. 验证目的

验证当前专用 Chrome Profile 在 Playwright `headless=True` 下，是否能够稳定完成正式采集当前已经支持的商品数据获取。

本轮只新增独立 POC `poc_headless_collection.py`，没有修改正式 collector、Parser、API、数据库、Frontend 或 `dev.ps1`。

## 2. 测试环境

- 日期：2026-09-20。
- Windows；项目 `.venv` 中的 Playwright；Chrome channel：`chrome`。
- Profile：项目根目录 `.browser-profile`。
- 页面：数据库中 `Competitor.url` 的原始 1688 商品页 URL。
- HTML 解析：直接复用 `backend/app/collection/parser_1688.py` 的 `parse_1688_html`。
- 页面访问判定：复用正式 collector 的登录、验证、状态码和域名检查；POC 额外把“无 `offerId` 且 HTML 出现 challenge 标记”归类为 `verification_required`，仅用于记录风控页。
- network 监听：复用已有销量 POC 的真实 response 监听目标 `mtop.1688.pc.plugin.od.data.query`；不构造签名、Cookie、Token 或请求头。
- 每种模式只启动一次 `launch_persistent_context`，连续创建页面访问多个商品，批次结束后关闭 Context。

## 3. 样本与轮数

数据库当前有 4 个 active 竞品，但只有以下 3 个同时满足“active 且至少有一次历史成功 headed 采集”；第 1 个只有失败记录，因此没有把它伪造成已验证样本。

| Competitor | expected offerId | 店铺 | headed 历史成功次数 | 价格基线 | SKU 数量基线 |
|---:|---|---|---:|---:|---:|
| 3 | `1042199069158` | 佛山淘趣科技有限公司 | 1 | `38.00 - 38.00` | 4 |
| 4 | `1081895898799` | 深圳市米小蓝科技有限公司 | 7 | `40.00 - 40.00` | 3 |
| 5 | `976443859503` | 佛山淘趣科技有限公司 | 4 | `45.00 - 50.00` | 9 |

主基线来自首次验证批次的现有 parser 结果；3 个样本覆盖 2 个店铺、不同价格区间和不同 SKU 数量。没有足够样本达到用户建议的 5 个，未伪造额外商品。

稳定性批次：headed 3 轮、headless 3 轮，共 9 次/模式。

## 4. 首次批次结果

### 4.1 Headed

- 核心商品采集：9/9。
- `actual offerId`：9/9 与 expected offerId 匹配。
- 标题、店铺、价格区间、SKU 数量、SKU ID、SKU 名称、stock：3 个商品在 3 轮中均成功返回；同一商品的业务字段保持一致。
- 主图研究逻辑：9/9 得到结构化候选；在本次历史验证时正式 `ProductData.main_image_url` 仍为 `NULL`，后续正式接入状态以 `docs/research/1688-main-image-validation.md` 的 implementation decision 为准。
- network 目标接口：0/9 捕获。本次启动参数严格保持正式 collector 的参数，没有额外为扩展删除 Chromium 的 `--disable-extensions` 默认参数；因此不能把本次 network 缺失解释为销量为 0。

### 4.2 Headless

- Browser 启动：成功，`headless=True`，没有 Profile lock。
- 核心商品采集：0/9。
- 初始错误表现：9/9 `parse_failed`，异常为 `missing or invalid offer_id`。
- 安全诊断：9/9 HTTP 200，商品 URL 仍在 `detail.1688.com`，HTML 没有任何 `"offerId"`，但出现 `captcha`、`verify`、`punish`、`secdev` 等 challenge 标记；因此按 POC 的额外诊断规则归类为 `verification_required`。
- network 目标接口：0/9，均为 `network data missing`。
- 没有出现 `login_required`，但这不等于登录态验证成功：headless 没有拿到商品 embedded JSON，无法证明登录后的商品数据访问稳定。

首次批次的 headed / headless 核心字段无法判定一致：headed 有 9 次完整结果，headless 没有 1 次完整结果，业务字段比较为 0/9。

## 5. 重复复核结果

在不处理验证码、不关闭用户 Chrome、不复制 Profile 的前提下，同一 Profile 又顺序复跑一次 headed 3 轮和 headless 3 轮：

| 模式 | 核心成功 | 失败原因 | Browser 启动次数 | Context 是否复用 |
|---|---:|---|---:|---|
| headed | 0/9 | `verification_required` 9/9 | 1 | 是 |
| headless | 0/9 | `verification_required` 9/9 | 1 | 是 |

这说明重复访问后 headed 也进入了 1688 风控页面；POC 没有尝试自动处理或绕过验证。综合两次 headless 批次，headless 核心成功率为 0/18。

## 6. 登录态、验证与资源行为

- 专用 `.browser-profile` 可以被 headed 和 headless persistent context 启动，没有观察到 Profile lock 冲突。
- headless 使用 `headless=True`，POC 没有创建可见浏览器窗口；没有使用 Windows API 或自动最小化。当前用户可见的系统默认 Chrome 与项目 `.browser-profile` 不是同一个 User Data 路径。
- 没有自动登录、验证码识别、滑块处理、stealth、指纹伪装、User-Agent 修改或其他规避逻辑。
- 每个模式只启动 1 次 Browser/Context；一个 Context 连续访问 3 个商品、共 3 轮，每次商品新建并关闭 Page，批次结束再关闭 Context。
- Profile 可启动不代表 headless 成功复用登录态：本轮 headless 实际拿到的是风控页而不是商品数据。

## 7. 已知限制

- active 且已有 headed 成功记录的样本只有 3 个，不足建议的 5 个。
- 1688 风控状态在重复访问期间发生变化：首次 headed 成功，后续 headed/headless 均验证失败。因此不能把首次 headed 9/9 外推为长期稳定。
- 本 POC 没有保存 HTML、完整 response、Cookie、Token、headers 或登录信息；诊断只保存页面状态摘要和字段结果。
- 本轮 network 监听按正式 collector 的启动参数执行，没有额外启用已有销量 POC 所需的扩展启动差异；因此 network 数据缺失只表示本轮未捕获，不表示销量为 0。
- 没有进行像素级页面比较；比较范围是 offerId、标题、店铺、价格、SKU 和可选研究字段。

## 8. 结论

**FAIL：当前不建议进入正式 headless 采集 Feature。**

原因是：headless 在首次稳定批次中为 0/9，全部返回验证/风控页；后续 headed 和 headless 复跑也均为 0/9 验证失败；核心字段没有可用的 headless 结果，network 数据也没有捕获。当前证据不足以证明“正常登录后的专用 Profile，headless 足够稳定用于个人采集”。

下一步只建议在用户手动完成一次正常验证、确认 Profile 恢复可用后，再减少访问频率重新做同样的独立 POC；不要在没有新证据前改正式 collector 或设计验证码绕过方案。
