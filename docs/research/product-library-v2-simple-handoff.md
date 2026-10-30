# Issue #11：第三轮 Review 修订交接

用户指定 Spec 基线 `b3b2df0f9ad8668cca508b04b9bae1cb6982a97f`；执行时分支已前进至 `a0e0a7d52bbfdc17dc5e92b8036e6949adc37097`，其中两次前端提交与四份设计文件无关，保留不覆盖。审查输入来自本轮用户消息，[Issue #11](https://github.com/shuzeyong312-rgb/personal-workbench/issues/11) 当时无评论。[V2 Spec](../specs/product-library-v2.md)、[身份合同](../specs/product-library-identity-v2.md)、[原型](../prototypes/product-library-v2-simple-import.html)为待第四轮独立 Review 的目标合同。

本轮规定：旧 manufacturer_name 原值不变、列改可空、新产品写 NULL；供应商只通过来源维护。各来源条件独立，客户报价必须选择来源或确认最终条件并绑定快照；未知或未确认不得计算/导出。普通删除为软删除，归档身份继续占用，导入明确恢复或跳过，保留报价/证据/回执。控价独立 `control_price`，历史 `price_note` 仅为供应商备注，严格隔离成本。

同时限定旧六列仅拒绝四张 V2 专属工作表，保存真实六列证据、版本和行号；手动报价带手动来源、初始 pending；废止旧默认价及批发价镜像；人工客户售价不得绕过采购成本和条件核验。补充字段长度、超限行为及 1000 物理行上限。原型展示同价来源条件选择及确认，演示不保存或计算真实报价。

原始 PDF/厂家 Excel 的 AI 自动整理属于后续任务；本期并未实现 Issue #11 所有原始资料处理能力。本轮不实现业务、不运行迁移、不连接正式库、不合并 PR #7。已应用 20/21 的环境须盘点并通过隔离副本演练；原件缺失时不能补造历史指纹和被覆盖版本。等待 ChatGPT 第四轮独立 Review，未通过不进入实现。
