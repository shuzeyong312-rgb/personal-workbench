# Frontend Automated QA V1 Spec

## 1. 目标与范围

为当前 React 前端建立最小、稳定的本地浏览器自动化 QA 闭环，减少完成前端 Feature 后重复手工点击验证的负担。V1 的试点功能是“竞品列表分页 V1”。

本 Spec 只定义后续实现的工程合同，不在本轮安装依赖、创建 Playwright 文件、修改脚本或业务代码。

## 2. 当前基线与职责边界

当前 `frontend` 使用 React、TypeScript、Vite 和 Vitest；没有 `@playwright/test` 依赖、Playwright Test 配置、E2E 目录或 E2E 命令。

仓库后端已有 Python Playwright，职责是通过本机 Chrome 和 `.browser-profile` 访问真实 1688 进行采集。它与本 Spec 的 Playwright Test 完全不同：

- Backend Python Playwright：真实 1688 Collector，可能依赖登录状态和本地数据；
- Frontend Playwright Test：浏览器端 UI QA，只访问 Vite 页面并 stub `/api/...`。

Frontend E2E 不得复用或调用 Collector 的 Playwright、`.browser-profile`、真实 1688 登录态或验证码流程。

## 3. QA 分层

项目后续采用三层验证：

```text
Vitest / pytest
→ 逻辑、纯函数、API Contract、业务规则

Playwright E2E
→ 真实页面、点击、输入、翻页、勾选、筛选等用户行为

人工体验验收
→ 视觉是否舒服、交互是否自然、业务是否真正好用
```

Playwright 不替代 Vitest 或 pytest，也不将现有低层测试机械重写成 E2E。能在低层稳定验证的规则继续留在低层；E2E 只保护关键用户路径。

## 4. 技术选择与运行边界

- 使用 `@playwright/test`，作为 `frontend` 的开发依赖。
- V1 只运行 Chromium；不引入 Firefox、WebKit、Selenium、Cypress 或第二套 E2E 框架。
- 浏览器安装是首次环境准备，单独执行 Playwright 的 Chromium 安装命令；`npm run qa:e2e` 不得每次自动下载浏览器。
- Playwright 配置负责启动独立 Vite 测试服务器，例如 `npm exec vite -- --host 127.0.0.1 --port 5201 --strictPort`，并以 `http://127.0.0.1:5201` 为 base URL。
- `5201` 是 QA 专用端口，与 `dev.ps1` 的常规开发端口 `5200` 分离。QA 不依赖用户先运行 `dev.ps1`，也不修改 `dev.ps1`。
- 后续在 `frontend/package.json` 提供唯一清晰入口：`npm run qa:e2e`。该命令启动 Vite、执行测试并正常退出；它不启动 Backend。

本项目当前 Vite 的 `/api` proxy 仅服务普通开发。E2E 测试必须在页面导航和 API 发起前建立 `/api/**` 的 fail-closed 防线，再以 `page.route(...)` 为当前场景明确声明的 API 返回 fixture。未声明的 API 请求必须由测试层主动阻止并使 QA 失败；不得穿透 proxy 到 `8100`。Backend 是否正在运行不得影响 E2E 测试结果。

## 5. 可控数据与网络 Mock

每个 E2E 场景只使用固定、可预测、与当前 API Contract 形状一致的 fixture。不得连接或写入真实 SQLite，不得使用真实工作数据，不得发起真实 1688 采集，也不得依赖本地 Backend `8100`。

初始目录保持最小：

```text
frontend/
├─ playwright.config.ts
└─ e2e/
   ├─ fixtures/
   │  └─ competitors.ts
   └─ competitor-list-pagination.spec.ts
```

`competitors.ts` 可提供少量 factory，以紧凑构造 10、11、23 条竞品和 active/inactive 变体；不要复制大段 JSON。fixture 的字段必须匹配页面实际读取的 `GET /api/competitors`、`GET /api/competitor-groups`，以及页面启动期间实际需要的 Dashboard 或 batch-status 响应。

每个 spec 在 `page.goto` 前先建立全局 `/api/**` 默认拒绝，再使用 `page.route(...)` 为该场景显式允许的请求返回这些响应。具体场景需要 POST 或 PATCH 时，仅为该场景 stub 对应请求和后续刷新所需的 GET。不得新增 MSW、独立 Mock Server 或额外服务。

`/api/**` 是测试受控资源，固定遵循以下外部行为：

```text
所有 /api/**
        ↓
默认禁止
        ↓
当前测试明确 Mock？
├─ 是 → 返回固定 fixture
└─ 否 → 立即 QA Fail，且请求不继续网络访问
```

未 Mock 的 `/api/**` 是 QA 配置错误，不得以“Backend 未启动，网络请求自然失败”作为隔离手段。即使 `127.0.0.1:8100` 正在运行，Backend 也不得收到该请求。后续实现可采用简单可靠的 catch-all route、allowlist/mock registry，或记录 unexpected API 后在测试结束断言失败；本 Spec 不冻结内部实现。

## 6. 分页 E2E V1 场景

首批只覆盖分页最值得重复点击的用户路径，不重复 `competitor-list-pagination-v1.md` 的全部 18 项低层验收。

### A. 分页基本行为

使用 23 条固定竞品，验证：

1. 打开页面并进入“竞品列表”；
2. 显示完整筛选结果总数 23；
3. 第 1 页只显示前 10 条，并显示 `第 1 / 3 页` 或等价可识别信息；
4. 点击“下一页”后，第 2 页展示正确的第 11 至 20 条数据；
5. 首页“上一页”不可用，末页“下一页”不可用，且不会进入无效页。

断言以用户可见行内容、总数、页码和按钮状态为准，不重复测试内部切片函数。

### B. 跨页选择

使用同时含 active 和 inactive 行的固定 fixture，验证：

```text
第 1 页选择若干 active 竞品
↓
进入第 2 页并继续选择若干 active 竞品
↓
“采集选中（X）”显示跨页累计数量
↓
返回第 1 页，原选择仍存在
```

同时验证 inactive 行不可选择，且单纯翻页不会清理其他页的 selection。

### C. 当前页全选与取消全选

验证：

```text
第 1 页全选 active 竞品
↓
第 2 页选择部分 active 竞品
↓
返回第 1 页并取消全选
↓
第 2 页已有选择仍保留
```

表头全选的作用域是当前页 active 行；此场景保护跨页选择最容易回归的边界。

### D. 代表性筛选变化

先跨页选择若干竞品，再改变一个代表性筛选条件（优先使用搜索词；如当前控件语义更稳定，可使用商品状态或竞品组）。验证：

- 回到第 1 页；
- 被新条件隐藏的 selected IDs 已清理；
- “采集选中（X）”同步更新；
- 页面总数基于完整筛选结果而非当前页。

不为每一种筛选控件逐个建立同质 E2E；具体 filter 规则继续由 Vitest 覆盖。

### E. 新增成功后回第一页：V1.1

新增对话框涉及 URL 输入、可能的竞品组交互、POST 成功结果和多次列表刷新。为了保持 V1 最小且稳定，本场景冻结为 V1.1，不纳入本轮首批 E2E。

V1.1 在不改变生产行为的前提下 mock `POST /api/competitors` 和后续 `GET /api/competitors`，验证用户第 2 页新增成功后回到第 1 页并能看到新竞品。不得为该场景新增测试专用 API、业务分支或 Mock 服务。

## 7. 失败证据与 Git 忽略

Playwright 配置至少启用：

- 失败时 screenshot；
- 失败时保留 trace。

默认不录制视频，也不建立 screenshot snapshot 视觉回归基线。失败产物是运行时文件，不进入 Git。实现时仅根据 Playwright 配置实际使用的目录更新 `.gitignore`；预期是 `test-results/` 和 `playwright-report/`，不预先加入无实际产物的忽略项。

V1 不做视觉回归，因为本地 Windows 的字体和运行环境会造成高噪音 visual diff；当前优先减少行为验证的重复点击。未来仅在稳定核心页面出现明确需求时再单独评估。

## 8. 本地流程与非目标

对于已有对应 E2E 场景的前端功能，实现完成后按影响范围运行：

```text
targeted unit tests
↓
typecheck
↓
full frontend tests
↓
build
↓
relevant Playwright QA
```

自动 QA 通过后，人工验收缩减为体验型检查，而非重新机械点击所有逻辑。Playwright 不替代高风险数据写入、真实 1688 页面、Collector、验证码场景或用户对 UI/UX 的判断。

V1 不做真实 Backend E2E、SQLite 测试数据库、1688 自动采集 QA、headed 1688 浏览器测试、多浏览器矩阵、Mobile、性能测试、Lighthouse、全量 accessibility 审计、视觉回归、GitHub Actions、CI pipeline、Docker、MSW、独立 Mock Server、全站 E2E，或将现有 Vitest 测试重写为浏览器测试。

## 9. 实现验收标准

后续实现必须满足：

1. `npm run qa:e2e` 能自行启动测试用前端服务器、运行 Chromium E2E 并退出；
2. 测试不需要 Backend，且不访问真实数据库、1688、`.browser-profile` 或验证码；
3. 所有页面 API 使用固定 `page.route(...)` mock fixture，并先建立 `/api/**` 默认 fail-closed 防线；
4. 人为触发当前测试未声明的 `/api/**` 请求时，E2E 必须失败，且请求不得到达真实 Backend；即使 `127.0.0.1:8100` 正在运行也成立；
5. Backend 是否启动不得影响 E2E 测试隔离或结果；
6. 首批分页关键路径 A 至 D 可以自动验证；
7. 只运行 Chromium；
8. 失败时产生 screenshot 和 trace；
9. 实际运行产物被 Git 忽略；
10. E2E 不重复低层已有测试，也不改变生产业务行为；
11. 测试失败时命令返回非 0 exit code，Codex 可明确识别失败；
12. 不新增真实 Backend、SQLite、1688 或 CI 依赖链。
