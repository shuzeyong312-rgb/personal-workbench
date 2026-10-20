# Product Library V1.1 实现与验收记录

日期：2026-10-18。冻结基准：`5743adbb2a6a47bde3504e713c11fe2374f7b83f`。
业务依据：`docs/specs/product-library-v1.1.md`，继承 V1；两份 Frozen Spec 均未修改。

## 实现范围及文件

| 能力 | 实现文件 | 验证 |
| --- | --- | --- |
| 严格大于/小于、含端点区间、报价状态与既有组合筛选；先计数后分页、稳定排序 | `backend/app/product_library.py`、`backend/app/product_library_service.py` | API + 193 款数据跨页查询；NULL/0、错误边界；浏览器查询和翻页 |
| 紧凑列表、命中字段/参数摘要、右侧完整资料预览、三类复制 | `frontend/src/ProductLibrary.tsx`、`ProductLibrary.css` | Vitest 白名单与摘要；浏览器复制确认/取消、成功/失败；保留原文 |
| 当前页全选、跨页保留、筛选变化清空、版本化批量永久删除 | 同上及产品库 Router/Service | API 部分 missing/stale、重复/非法请求、提交失败全回滚；浏览器 21 项跨页选择及二次确认 |
| 问题优先、普通行默认折叠、整批计数及固定操作栏 | `frontend/src/ProductLibrary.tsx`、`ProductLibrary.css` | 193 new + 8 invalid；问题顺序、错误不可选、跨页整批确认；继承全部 V1 导入回归 |
| 三范围报价、规则、人工覆盖、未报价、Decimal、固定集合及版本检查 | `backend/app/product_library_quotations.py`、`frontend/src/ProductQuotation.tsx`、产品库 Router | 半分边界、整数 ceiling、计算顺序、上限、范围、篡改/stale；浏览器规则与人工价格、恢复自动计算、下载 |
| 客户字段白名单、敏感词逐项核查、全部文本确认、Excel 字面文本 | 同上 | 重新打开 xlsx、解包 XML、所有单元格/工作表/批注/属性/文件名、隐藏内容及公式检查；成本/厂家/内部比例等唯一哨兵不得泄露 |
| 复用现有分页 | `frontend/src/PaginationBar.tsx`、`App.tsx` | 原组件原样移动，App 保留导出；既有分页/导航 9 项 E2E 回归 |

测试文件：`backend/tests/test_product_library_v11.py`、`frontend/src/ProductLibrary.test.ts`、`frontend/e2e/product-library.spec.ts`。
没有新增依赖、业务表、数据库迁移、后台任务或报价持久化。

## 自动验证

- 最终全量 Backend pytest：682 passed（包含 V1.1 的 42 项），138.23 秒；78 条既有依赖/接口弃用警告。
- 最终全量 Frontend Vitest：221 passed，3 个测试文件。
- V1.1 定向 Backend pytest：42 passed。
- TypeScript + Vite build：通过（`npm --prefix frontend run build` 包含 `tsc --noEmit`）。
- 产品库 Playwright：11 passed。
- 既有竞品分页/选择与侧栏导航 Playwright：9 passed。
- 独立 Final Gate 额外隔离 pytest：5 passed。
- `git diff --check`：通过；Frozen Spec 与 Alembic 文件无差异。

复现测试命令（PowerShell）：

```powershell
Set-Location C:\data\personal-workbench\backend
..\.venv\Scripts\python.exe -m pytest tests -q
Set-Location C:\data\personal-workbench
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run qa:e2e -- product-library.spec.ts competitor-list-pagination.spec.ts sidebar-navigation.spec.ts
```

后端测试必须从 `backend` 目录运行：旧经营指标迁移测试通过相对路径读取 `alembic.ini`。首次在仓库根目录执行时为 677 passed / 1 failed，原因是该配置路径；从正确目录重跑为 678 passed。最终修复后再执行全量，见最终结果。

## 独立审查与修复

首次使用两个隔离上下文、只读子代理分别进行 Standards / Spec Code Review；覆盖基准至完整工作区 diff 及新增文件。

| 轴 | 首次结果 | 根因与修复 | 独立 Final Gate |
| --- | --- | --- | --- |
| Standards | 1 × P2 | 存量客户文本可含 Excel 非法控制字符。预览增加逐字段错误，导出在生成文件前返回 `422 customer_text_invalid`，携带 ID/字段；四字段回归确认源资料不变 | CLOSED |
| Spec | 1 × P2 | filtered/all 的 stale 恢复可能重新查询并混入新产品。现在已有预览只刷新原快照受影响项；仅显式改变范围/未报价选项才重新解析；人工价格保留、客户核查须重做 | CLOSED |

另一个全新隔离上下文、只读 Reviewer 完成 Final Gate：PASS，未关闭 P0/P1/P2 = **0/0/0**，未发现修复直接引入的新阻塞。其独立执行四字段及快照回归 5 passed；未重复全量测试或浏览器操作，前端另有 2 条 filtered/all 浏览器回归佐证。

## 数据隔离与人工验收启动

自动测试使用临时 SQLite、受控 API Mock 和临时工作簿；未连接正式数据库、未执行正式迁移、未启动自动采集，未运行 `dev.ps1`。报价不写回产品库，删除回滚测试只涉及隔离样本。

人工验收仍待用户和 ChatGPT 完成，不能由 Mock 或 Review 代替。建议核对：组合筛选/预览密度、复制内容、跨页删除确认、真实整理 Excel 的资料保真与冲突操作、三范围报价及下载后的客户文本/金额。

以下方法仅创建临时受控样本，不使用正式库。启动片段已通过隔离自检：创建 23 款样本、API 返回总数 23、默认报价集合 18；自检替换服务器入口，没有真正启动服务。先关闭占用 8200/5201 的旧开发服务；后端若端口冲突应停止，不能继续使用原服务做此验收。

终端 A 在仓库根目录执行以下完整 PowerShell 命令，保持运行：

```powershell
Set-Location C:\data\personal-workbench\backend
@'
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvicorn
from app.database import Base, get_db
from app.main import app
from app.product_library_service import create_product_service

os.environ["PERSONAL_WORKBENCH_DISABLE_SCHEDULER"] = "1"
with TemporaryDirectory(prefix="product-library-v11-acceptance-") as folder:
    engine = create_engine("sqlite:///" + (Path(folder) / "acceptance.sqlite").as_posix(), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def isolated_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    app.state.collection_session_factory = factory
    try:
        for index in range(23):
            with factory() as db:
                create_product_service({"manufacturer_name": "受控验收样本（非真实商品）", "model": f"QA{index:03}", "name": f"验收样本{index:02}", "parameters": "3.7V\n1000mAh（受控样本）", "selling_points": "成本字样提醒测试" if index == 3 else "受控样本卖点", "wholesale_price": None if index % 5 == 0 else str(index), "price_note": "内部备注不应进入客户文件"}, db)
        print("隔离验收：23款受控样本；自动采集关闭；Ctrl+C 后临时库删除。")
        uvicorn.run(app, host="127.0.0.1", port=8200)
    finally:
        engine.dispose()
'@ | ..\.venv\Scripts\python.exe -
```

终端 B：

```powershell
Set-Location C:\data\personal-workbench\frontend
npm exec vite -- --host 127.0.0.1 --port 5201 --strictPort
```

访问 `http://127.0.0.1:5201` → 产品库，确认厂家显示“受控验收样本（非真实商品）”。操作只写临时库；关闭后数据不保留。真实厂家资料可导入该临时验收环境核对，但请自行保存需要留存的导出文件。

## Git 与限制

交付时 7 个已跟踪文件修改、5 个新增文件（含本文），均未暂存，未 Commit / Push；HEAD 保持冻结提交。工作区仅包含本轮产品库实现、测试和验收文档。
截图和测试报告位于忽略的 `frontend/test-results` / `frontend/playwright-report`，不作为业务提交文件。
没有验证真实厂家资料、Excel 桌面应用视觉或正式环境运行；自动工作簿验证使用 openpyxl/XML。依赖现有弃用警告未在本轮升级依赖。
