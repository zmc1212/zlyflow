# 来源与工作台适配

- Hub 路径：`C:\Users\Administrator\.hub-global\skills\half-narrated-live-action-short-drama\`
- 版本：`1.0.1`（Hub `meta.yaml`）
- 官方文件：`SKILL.md`、`meta.yaml`、`references/h3-video-prompt-template.md`、`references/seedaudio-final-track-prompt-template.md`
- 同级未接入：`half-narrated-2d-short-drama`、`half-narrated-3d-short-drama`

本目录是工作台配方，不是 Design Agent。官方 Markdown 原文保留在 `SKILL.md`（文首仅加适配说明）。工作台映射：

| 官方 Design | 工作台 |
| --- | --- |
| Design Image 2、默认 2K | GRS 生图（角色卡 / 场景卡 / 16:9 三联母图默认 2K） |
| 每镜一张 16:9 三联关键帧母图（内含三格 9:16） | 仍生成整张母图给人看、给写稿看运镜；`extract_triptych_panels` 裁切左/中/右格为 9:16 起幅、中格、结果 |
| 成片把三联母图当视觉锚点 | 本地 MiniMax H3 R2V **不**把整张 16:9 三联当 `<Picture n>`；只送角色卡、场景卡和三张 9:16 裁切（起幅/中格/结果）作同一镜时间路标 |
| 角色卡锁身份 | 导台2 角色卡是 16:9 设定板；H3 subject 行只锁脸/发/衣服，禁止抄分格；有造型图时三联不再额外塞头像 |
| 出片前确认 2K 或 768P，整集统一 | `confirm_format.resolution: user-confirmed`；单镜时长按官方 H3 **5–15** 秒 |
| Seed Audio 独立旁白轨、字幕（步骤 10–11） | 第一期配方可声明，不接线 |
| Design 画布工具 | 不搬进工作台 |
| 技能市场封面 `cover` mp4 | Hub `meta.yaml` 的 `cdn.hailuoai.com` 地址；工作台选择页热链播放，不把视频拷进仓库 |

`<Picture n>` 对应 R2V 上传顺序。官方模板里的 `@ImageN` 已改成工作台标签。
