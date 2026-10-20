---
name: Personal Workbench
description: 商品资料与竞争情报的日常工作台
colors:
  canvas: "#f3f4f6"
  surface: "#ffffff"
  surface-subtle: "#f6f7f8"
  ink: "#20242c"
  muted: "#626b78"
  border: "#dde1e6"
  accent: "#2563eb"
typography:
  headline:
    fontFamily: '"Noto Sans SC", "Microsoft YaHei", sans-serif'
    fontSize: "32px"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-.025em"
  title:
    fontSize: "20px"
    fontWeight: 650
    lineHeight: 1.45
  body:
    fontSize: "13px"
    lineHeight: 1.8
rounded:
  control: "6px"
  workspace: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  regular: "16px"
  lg: "24px"
  xl: "32px"
---

# Design System: Personal Workbench

## Overview

本文件是已实现首页与 Shell 的 Token 摘要；最终视觉权威为 [UI System](docs/ui-system.md)，业务行为以对应 Feature Spec 为准。代码取样：`frontend/src/Workspace.css`、`frontend/src/App.tsx`。不据此宣称业务页面内部完成迁移。

延续中性浅灰、白色表面、石墨文字与克制操作蓝，以任务、文字层级和分隔线组织工作。首页是任务入口，竞品监控与产品库承担不同工作职责。

## Colors

品牌蓝用于主要操作、焦点和当前导航；中性色分别承担画布、内容、浅表面、文字、辅助文字与边线。准确值见 frontmatter，不另建色彩体系。

## Typography

全局沿用本地中文字体栈，不加载字体。首页引导文字 32px/650，窄屏 28px；区域标题 20px/650；正文 13px，说明 12–14px；导航 13px，子导航 12px。各业务页仍按自身 Reference 层级。

## Layout

桌面侧栏 232px，主内容复用现有宽度与内边距。首页工作区为 1.5:1 双列，1100px 以下变为 1.2:1，760px 以下单列。窄屏导航在文档流展开，不覆盖正文；首页和 Shell 样式限定在对应 class 内。

## Elevation & Depth

首页静态表面和操作不使用投影，以细边线、白色与浅表面、留白建立层次；不将此局部规则追溯为所有旧页面已迁移。

## Shapes

小圆角用于控件；首页工作区 12px 圆角只形成一个整体容器，内部以分隔线组织，不重复嵌套卡片。

## Components

首页以一个主要竞品入口、一个产品库入口、四条监控任务导航和系统设置入口组织；不请求数据，不展示 KPI。规划清单明确尚未开放，导航保留四项既有占位路由。

侧栏按首页、工作工具、规划工具、系统设置分层。当前项同时有背景与 `aria-current`；竞品模块保留折叠状态。窄屏触发按钮提供 `aria-expanded`，隐藏导航不可聚焦；Escape 收起并回焦触发按钮，选页后收起。提供跳至主内容链接与可操作面包屑。Shell 按钮焦点为蓝色 2px 轮廓、3px 偏移。

## Do's and Don'ts

- Do 延用 UI System、Reference 和现有组件。
- Do 用明确文字区分可用工具和规划功能。
- Don't 为首页增加模拟 KPI、活动或额外数据请求。
- Don't 将首页任务结构变成所有业务页的强制模板。
- Don't 引入新字体、依赖、渐变或导航入场动画。
