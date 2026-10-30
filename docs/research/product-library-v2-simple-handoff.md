# Issue #11：第二轮 Review 修订交接

[Issue #11](https://github.com/shuzeyong312-rgb/personal-workbench/issues/11)；本轮基线 `b3b2bc7daab625fb00f6f3a78eaedf93eaff53d2`，PR #7 源码核对基线 `81dac9bbb01e1e0c5927791f55e74aeec612e946`。审查要求由用户消息提供；Issue 评论当时为空。修订后的目标见 [V2 Spec](../specs/product-library-v2.md)、[身份合同](../specs/product-library-identity-v2.md) 和 [原型](../prototypes/product-library-v2-simple-import.html)。

- 恢复 V1 六列兼容：原“产品数据”及可选“填写说明”结构映射为统一八列，旧价待确认；新单表八列仍是唯一推荐模板。
- 五项旧业务工作表对应的实际主表、JSON、规格、来源、价格及回执建立只读历史快照/保留旧表，保全 ID、字段、时间和关系；新业务不读写归档参与匹配或计算。新增报价键、追加式版本和版本—来源关联，不能将并发版本当历史。
- 明确 pending / eligible / ineligible 与用户复核转换；旧 V1 价及 PR #7 默认标记不得自动取得资格或自动选价。客户报价必须选择当前合格的供应商及规格。
- 两份实施合同统一型号+名称精确身份，明确历史 manufacturer_name 和来源归属。仓库检索发现 `product-library-v1.md` 及 `product-library-vnext-operations.md` 保留历史厂家身份；V2 第 8 节明确覆盖关系，旧文历史原样保留，后续实现不可将旧条款当作有效身份合同。
- 支持换行、中英文分号及混合分隔，歧义整格待核对；模板型号预设文本，数字型号按行报错重输。原型明确冲突决策仅作用当前产品参数，并恢复旧模板兼容提示。

原始 PDF/厂家 Excel 的 AI 自动整理属于后续任务，本期不实现，也不宣称 Issue #11 原始资料处理能力已经全部实现。原型的模板下载只是演示入口，不生成 Excel；示例均为虚构。本轮没有运行正式数据库或迁移，也未实现业务代码。历史原件缺失时不能重建文件指纹和已被覆盖的历史价格；已应用 20/21 的环境和归档数据需先盘点并在隔离副本验证。

等待 ChatGPT 对本次固定 SHA 第三轮独立 Review，通过后再进入实现；不合并 PR #7、不部署。
