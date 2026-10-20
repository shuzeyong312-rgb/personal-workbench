# V1.4 页面视觉验收

本轮改版页面：竞品分组、采集记录。截图由 Chromium 使用隔离 API Fixture 生成，不代表真实采集数据。

## 前后对比

| 页面 | 改版前 | 改版后 | 受控视口 |
| --- | --- | --- | --- |
| 竞品分组 | `before/competitor-groups.png` | `after/competitor-groups.png` | 1600 × 1000 |
| 采集记录 | `before/collection-records.png` | `after/collection-records.png` | 1680 × 1000 |
| 采集记录详情 | — | `after/collection-record-detail.png` | 1680 × 1200 |

分组前后截图使用相同的 8 组 Fixture；采集记录前后使用相同的单批次 Fixture。详情图仅展示本轮状态语义色验收。窄屏补充图分别为 `after/competitor-groups-390.png` 和 `after/collection-records-390.png`（390 × 844）。

## 验收覆盖

- 分组页：Chromium 桌面 1440 / 1600，窄屏 390；检查无横向溢出、卡片 Grid、完整最近变化时间、组分析与查看竞品入口、更多菜单、未分组区、筛选和分页。
- 采集记录：Chromium 桌面 1680、窄屏 390；检查无横向溢出、错误重试、加载与空状态、分页及详情展开；摘要中页面访问和补采访问维持中性，部分状态保留提醒色。
- 页面加载、错误和恢复空态由受控接口 Fixture 覆盖；不访问正式业务数据库或 1688。

## 验收命令

- `npm exec vitest run src/App.test.tsx`：210/210 通过。曾有一次非稳定超时，单独重跑全量通过。
- `npm run build`：TypeScript 与 Vite 构建通过。
- `npm exec playwright test e2e/group-directory.spec.ts e2e/collection-tasks.spec.ts e2e/workbench-ui-refresh-v1.4.spec.ts --project=chromium`：25/25 通过；窄屏时间修复后，分组专项重跑 7/7 通过。
- `git diff --check`：通过；仅有工作区 CRLF 提示。

## Final Gate

独立只读复核已检查 390px 分组卡片的最近变化时间显示；修复后时间完整可见，未发现剩余问题。Final Gate 通过。复核未重复运行测试、构建或视觉检测；以上验收结果沿用实现阶段记录。

## 设计系统复用与影响

- 复用 `docs/ui-system.md` 和 V1.3 已有中性色、白色表面、石墨文字、克制品牌蓝及语义状态色；未新增依赖或第二套 Token。
- 分组与采集记录样式限定在对应页面容器内；共享 UI System 文档同步了字号、间距、状态、窄屏和动效约束。
- Product Library、后端、API 和数据库不属于本轮改动范围。后续迁移其他页面时，按页面逐一核对旧局部样式与当前 Token，避免将分组/采集记录的布局直接套用到其他页面。
