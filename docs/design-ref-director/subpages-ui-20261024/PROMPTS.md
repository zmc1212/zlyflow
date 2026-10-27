# 内置 ImageGen 提示词记录

使用宿主内置 `image_gen.imagegen`，未使用 CLI 或另配生图服务。生成图用于探索与跨页面视觉关系；逐页冻结稿另在 1600×1000 / DPR 1 的浏览器中制作。以下按实际请求的结构归档提示词与参考用途。

## 主页面总览

输出：[concept-core.png](concept-core.png)。输入为旧页面的九屏截图联系表，作为产品结构参考。

```text
Use case: ui-mockup. Design a precise high fidelity desktop UI atlas for the existing Chinese ZLY AI 视频工作台 导演台. Four equal screens in a 2×2 atlas: 内容库空态, 资产库 populated, 剧集工坊 overview, 全部任务.

Preserve the 76px global rail. Project navigation 200px, topbar 72px. Canvas #f8f9fa, white surfaces, ink #171a1f, secondary #4b5563, muted #6b7280, accent #435ce8. Chinese sans-serif. Work area margin28, title26/36, description13/22, 40px buttons, 8px control radius, 12px panel radius, 1px borders. No gradient, glass, invented poster or thumbnail.

Retain project identity, editing, recipe selection, AI/manual mode and theme. Navigation: 内容库 / 资产库 / 剧集工坊 / 智能剪辑 / 全部任务.

Content: document guide and import at upper right, centered 64px document icon and clear empty state, immediate import and sample import, file types.
Assets: one category control with真实数量, batch operation row, 248px name list and flexible character definition, original reference and form fields. Sample names 陈远 / 林夏, scene 林间木屋, prop 旧信封.
Workshop: uniform title and create/refresh; compact real statistics, three episode cards 清晨的来信 / 未寄出的回答 / 重返森林; summary, metadata, 进入工坊, edit and delete.
Jobs: task type tabs, search and status filter, genuine count, wide table for task/status/progress/result/time/actions. Illustrative rows are design samples.

Professional operate UI, preserving product truth and real component constraints.
```

## 镜头与专用工作室总览

输出：[concept-specialists.png](concept-specialists.png)。参考为同一旧页面联系表与已经生成的主页面总览，后者仅承担视觉延展。

```text
Use case: ui-mockup. Create the companion desktop atlas, 2×2 equal screens: 分集镜头工作区, 短视频批量, 参考片复刻, Hypit复刻. Keep the same theme palette, typography, borders and radii. No perspective, browser chrome, gradient or invented media.

Shots: 72px project bar, 200px project navigation; 第1集·清晨的来信 and real draft state; generation settings, video generation, refresh and script actions. Line icon tabs 镜头 / 剧本 / 配音 / 合成. Compact toolbar and two-column storyboard / inspector; 文案 / 草图 / 素材组, dialogue, speaker, camera, scene, time, duration and action. Independent scrolling.

Batch: 320px parameter panel plus flexible white result canvas. Two-column count and aspect, full-width duration/workflow/model/style; 暂无生成结果 with clear next step. Preserve the existing bottom Prompt Bar, only adapt the outer layout.

Replication: 320px reference and settings sidebar plus flexible results; upload supports mp4/mov/webm up to2GB, smart/fixed segmentation, sensitivity, target style, control strength, numeric input and disabled start when no source. Results have count and batch action, centered film icon and instructions.

Hypit: same workspace proportions. Place the existing workflow explanation across the workspace instead of occupying the narrow sidebar; reference upload, change brief, language, quality and existing actions. Empty result clearly explains the next step. No new product capability or fake progress.

All text and controls remain editable in implementation. Keep actual product labels and existing workflows.
```

Hypit 在 2026-10-25 当前仓库中已下线，其生成图仅作本次设计过程归档。设计图实际像素尺寸由图片文件与文件索引记录；工作台精确还原以逐页冻结稿为准。
