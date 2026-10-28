# 首页入口素材

日期：2026-10-28。完整首页设计图仅作布局参考，未作为页面背景，也未从整张设计稿裁出 UI 作为可运行页面。

| 文件 | 来源 | 尺寸 | 用途 |
| --- | --- | --- | --- |
| frontend/public/generation-home/director-coast.png | 内置 ImageGen 参照批准稿重新生成的独立摄影画面 | 2172×724 | 导演台入口；文字和箭头由代码呈现 |
| frontend/public/generation-home/image-camellia.png | 内置 ImageGen 参照批准稿重新生成的独立摄影画面 | 2172×724 | 图片生成入口；文字由代码呈现 |
| frontend/public/generation-home/canvas-workspace.png | 原样复用 docs/design-ref-canvas/06-editor-fidelity-light.png | 见源文件 | 画布入口的真实界面预览；使用 CSS 容器裁切，不修改原图 |

背景摄影不承担用户真实作品的含义。「最近创作」只从登录用户实际可见的任务数据中提取，静态入口图片不混入该列表。截图验收使用浏览器内的模拟任务并单独记录。

## 实际生图提示词

### director

Generate ONE standalone cinematic photograph asset for the wide '导演台' shortcut in the attached approved UI. Use the UI only to identify the photograph: an adult woman seen from behind, long dark hair and a flowing deep red coat, standing on a rocky sea coast, grey waves, distant dramatic pale cliffs, overcast luminous sky. Recreate the coastal photo with photographic realism. Panoramic 3:1 composition, high resolution approx 1536x512. Woman in the RIGHT half, leave the LEFT half mostly pale sky and softer muted sea so live UI text will be readable there. Elegant restrained film color, red coat is the focal accent. Return ONLY the photograph, no letters, text, icons, borders, buttons, gradients from the UI, or watermark.

### image

Generate ONE standalone photographic banner asset for the small '图片生成' shortcut in the attached approved UI. The reference identifies the image: white camellia flowers with dark green leaves on a clean pale grey-white tabletop, subtle hard sidelight and refined botanical still-life photography. Panoramic 3:1 composition, approx 1536x512, flowers clustered in the RIGHT half, LEFT half is calm clean pale grey-white negative space for code-rendered labels. Photorealistic white petals, realistic shadows, elegant neutral color and simple art direction. Return only the photograph. No text, logo, UI, border, watermark, or fake transparency.

两次调用均实际传入 generation-home-v3-light.png 作为画面位置与风格参考，transparent_background=false。原始生成文件留在宿主生成目录，选定成品已复制到项目 public/generation-home，未使用其他图像 API 或付费工作台生图接口。
