# 1688 主图数据源验证

## 1. 验证日期

2026-09-20。

执行时工作树 HEAD 为 `3614d68`；本次未切换或修改用户工作树中的其他变更。

## 2. 样本与成功率

- SQLite 中 `Competitor.is_active = true`：5 个。
- 页面访问成功但目标商品确认成功：3/5。
- 主图结构化候选成功提取：3/5（已确认目标商品的 3/3）。
- 重复访问：2 个已确认样本，各访问两次。
- 未确认的 2 个页面返回了可访问页面，但内嵌结构没有对应 expected `offerId`；其图片候选属于其他页面内容，不能计为商品主图。
- 未新增 Competitor，未修改数据库；未遇到 login required 或 verification required。

## 3. 结构化来源

已确认商品中观察到的主要字段/路径包括：

- `gallery.fields.offerImgList[0]`
- `gallery.fields.mainImage[0]`
- `Root.fields.dataJson.images[0].fullPathImageURI`
- `size220x220ImageURI`、`size310x310ImageURI`、`searchImageURI`、`summImageURI`

三个已确认商品均稳定选择：

```text
gallery.fields.offerImgList[0]
```

`offerImgList` 后续项是同一商品的其他商品图，不应把列表整体扩展成图片图库。页面还包含推荐位、背景图、视频封面等 URL，不能按页面中发现的第一个 URL 选择主图。

建议未来正式 Parser 的优先级：

1. `gallery.fields.offerImgList[0]`；
2. 同一结构中已观察到的 `mainImage[0]` / `fullPathImageURI` 作为结构化校验或有限 fallback；
3. 结构化数据缺失时才考虑 DOM fallback。

## 4. DOM 交叉验证

- 已确认商品：3/3 匹配页面当前可见商品图。
- 结构化候选是原始 `.jpg` 形式；DOM `currentSrc` 观察到相同资源前缀的 `.jpg_.webp` 形式。
- 因此本轮 DOM 结果为 `different-but-equivalent`，不是字符串完全相等；匹配依据是相同 host、相同资源路径前缀、相同首图顺序。
- DOM 仅作为验证依据，未形成正式 selector。

## 5. URL 形态

已确认的结构化候选全部观察为：

- scheme：`https`；
- hostname：主要为 `cbu01.alicdn.com`；
- path：`/img/ibank/...-0-cib.jpg` 形态；
- query：0 个候选带 query；
- fragment：0 个候选带 fragment；
- protocol-relative：本轮 0 个候选观察到 `//`；
- 后缀/路径变体：观察到 `.jpg`、`.220x220.jpg`、`.310x310.jpg`、`.search.jpg`、`.summ.jpg`，以及 DOM 当前渲染的 `.jpg_.webp`。

本轮没有足够证据把所有后缀都归约为同一 canonical path，也没有证据可以删除 query 或替换 CDN hostname。

## 6. 重复访问稳定性

两个成功重复样本的结果均为：

- raw selected URL：`same`；
- canonical selected URL：`same`；
- 结构化来源：仍为 `gallery.fields.offerImgList[0]`。

这只证明本次两个重复样本稳定，尚不能证明长期跨时间稳定。

## 7. 推荐 canonicalization

未来窄契约：

```text
normalize_main_image_url(raw: str) -> str | None
```

本轮只建议：

1. trim；
2. `//host/path` 转为 `https://host/path`；
3. 只接受 `http` / `https`，且必须有 hostname 和非空 path；
4. 忽略 fragment；
5. 暂时保留 query、hostname 和 path 后缀。

不要凭经验删除 `.jpg_.webp`、尺寸后缀、`.search`、`.summ` 或 query；这些只能在更多真实样本证明等价后再扩展规则。

## 8. `main_image_changed` 语义建议

只有 previous/current 都是有效 canonical URL 且不相同，才建议产生 `main_image_changed`。

以下默认不产生事件：

- `None → URL`
- `URL → None`
- `None → None`

缺失数据不等于真实主图新增或删除，应保持与当前库存 NULL transition 的保守原则一致。本轮未修改 `detect_changes` 或 ChangeEvent。

## 9. READY 判定

结论：**PARTIAL**。

理由：3 个已确认真实商品均有稳定结构化首图，并与 DOM 首图一致；但当前 active 样本中另有 2 个 URL 未确认属于目标商品，且本轮只完成 2 个样本的重复访问。不能据此把当前 active 集合判为全部 READY，也不能把未确认页面的图片候选当作缺失主图。

## 10. 是否进入正式 Feature

本轮不建议进入正式主图 Feature。先保留 `main_image_url = NULL`，不修改正式 Parser、ProductData、Snapshot、Competitor 或 ChangeEvent。

若后续补充更多可确认的真实商品并重复验证仍保持相同结果，正式接入可保持最小范围：结构化 `offerImgList[0]` → 现有 `ProductData.main_image_url` → Snapshot / Competitor；加入 `main_image_changed` 的 ChangeEvent CHECK 仍需独立 migration。

如果未来达到 READY，最小 parser fixture 应覆盖：valid structured main image、protocol-relative URL、invalid scheme、missing main image、multiple image candidates、canonical-equivalent URL。

## 11. Remaining Unknowns

- 当前 2 个未确认 URL 是否为数据库中的占位/失效商品，不能由本次 POC 代替业务修复；
- protocol-relative URL 尚未在真实有效样本中出现；
- query 参数形式及其是否为 CDN transform 尚未观察到；
- `.jpg_.webp` 与其他尺寸/格式后缀的长期等价规则仍需更多样本；
- DOM 首图 selector 未建立，也不应成为正式首选数据源；
- 重复访问只覆盖 2 个商品、同一验证时段，长期 CDN 或页面改版影响未验证；
- 未下载图片、未计算 hash、未发起 HEAD 请求，因此本轮没有内容级同图证明。
