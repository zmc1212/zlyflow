# 补充生图记录

使用宿主内置 `image_gen.imagegen`，以本仓库上一轮 `actual-batch-light.png`、`actual-replication-dark.png` 为实际图像参考。输出为 [01-concept-board.png](01-concept-board.png)，原始 2112×744，无透明背景。下面归档提示词要点；完整字段与尺寸约束以 [DESIGN.md](DESIGN.md) 为实现规格。

```text
Use case: ui-mockup. One board with two equal desktop screens side by side:
left 短视频批量 in light theme; right 参考片复刻 in dark theme.
Preserve the existing ZLY AI Studio navigation, 72px header, 76px rail,
320px settings panels, neutral surface layers, indigo accent, Chinese sans serif,
26px title, 13px explanation, 8px control and 12px panel radii.

Batch: 创作设置. First row 视频数量=3 and 画面比例=9:16 竖屏.
Then full-width 单条时长（秒）=8, 视频工作流=官方 MiniMax H3,
画风（可选）/选择画风. Remove 模型体积. Preserve the result empty state
and existing bottom Prompt Bar without changing its internal visual language.

Replication: preserve reference upload, file types and 2GB text.
拉片设置: 分镜方式 with equal 智能分镜 / 固定分段, 目标风格（可选）,
quiet collapsed 更多设置 containing the existing 切镜灵敏度 control,
full-width disabled 开始拉片, 上传参考片后即可开始拉片。.
Remove 深度控制强度 and 采样步数 entirely from the user form.
Footer: 参考片复刻 · 拉片后可逐镜编辑，再生成新画面。.

Light: #f8f9fa canvas, white surfaces, #171a1f text.
Dark: #0f1115 canvas, #171a20 surface, #1e2229 raised, #f3f5f7 text.
Readable accurate Chinese, high contrast, no invented capability or decorative imagery.
```

总览生成后已检查，随后使用真实 Ant Design 控件与根主题制作四张精确逐页冻结稿，最后才修改业务源码。总览未拉伸为 1600px 页面的像素基线，业务界面未嵌入整张设计图。
