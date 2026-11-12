# 正交错觉 · B 版（独立实现，用于对照）

同级目录 `tools/perspective-illusion` 是另一个模型正在开发的 A 版。本目录**从零独立实现**，没有复用 A 版的任何代码，方便并排比较效果。两版依据的都是截图里提到的 `dotslashsimran/simcraft → skills/video/perspective-illusion` 方法：**用长焦把三维街景压成平面插画，镜头一动纵深突然拉开，压平时偷偷把物体从一排换成斜列**。

## 直接看结果

| 文件 | 内容 |
| --- | --- |
| `out/AB_compare.mp4` | **A / B 上下对照视频**（上 B 下 A，各 960×540，10 s 同步播放） |
| `out/AB_stills.png` | 三个时刻的静态对照：平面态 / 展开 / 角落视角 |
| `out/preview.mp4` | B 版预览，960×540 / 30fps / 10.000s / H.264 |
| `out/final.mp4` | B 版终版，1920×1080 |
| `out/contact.png` | B 版 10 个关键帧联系表 |
| `out/compare_t0.png` | 仅平面态的上下对照 |
| `out/stills/` | 各时间点 PNG 原图 |

A 版预览在 `../../tmp/perspective-illusion/preview.mp4`。

## 方法落点（skill 里最值钱的那张相机参数表）

- **镜头**：海报态 `fov 2.2° / 573 m`，广角态 `46–48° / 25 m`。`W = 22 m` 全程不变，`dist = (W/2)/tan(fov/2)`，所以是严格的 dolly zoom：主体尺寸不动，只有纵深打开。
- **移轴**：`makePerspective` 构造非对称视锥，让地平线精确落在 NDC 的 `H` 上。相机**永远水平**，竖线始终竖直，这是"像立面图"的前提。
- **插值**：25 个关键帧走 Fritsch–Carlson 单调三次（PCHIP），`W` / `fov` 在对数空间插值，速度不会在关键帧处跳。
- **换位**：6 个路锥只在 `z` 方向移动、`x` 保持不变，并且只在 `fov ≈ 2.2°` 的平面停留段内完成。平面态完全看不出变化，广角展开时才变成一列。
- **角落视角**：左右各一组，成对出现——先 `4.5–5°` 长焦压平，再 `36–38°` 广角展开并下压移轴，露出街面。
- **无缝循环**：10 s 首尾同帧；雨、行人、车、路锥全部是 `ms` 的周期函数，且每圈走整数个周期。

## 与 A 版在实现上的不同

| | A 版 | B 版 |
| --- | --- | --- |
| 渲染通道 | beauty / 法线 / 深度 / 平面色，四遍 | 颜色 + 法线深度两遍，单遍合成 |
| 墨线来源 | 多缓冲差分 | 法线差 + 深度二阶差 + 色差，按深度淡出远景细线 |
| 明暗 | 双色调 | 双色调 + 世界坐标锚定的排线（只在背光面）+ 按**视线方向**绘制的天空/远景 |
| 平面态密度 | 楼群 + 大片天空 | 满幅窗格 + 横跨街面的招牌门 / 低横幅（长焦叠成横带，展开后分离成四个深度）+ 远景窗墙 |
| 运动模糊 | GPU 内子帧累加 | 同样思路：按 `probe` 点的屏幕位移自适应 k，jitter 子帧在 GPU 内累加 |
| 静态几何 | 程序化 | 程序化 + 按材质合并（整条街只有个位数 draw call） |

## 运行

```bash
cd tools/perspective-illusion-b
npm install                       # three 0.170 + playwright-core；已自带一份可直接跑

node render.mjs --stills 0,1.5,2.6,3.5,4.5,5.8,7.4,8.2,9.9   # 关键帧，先改构图看这个
node render.mjs --preview                                       # 960×540，约 20 s
node render.mjs --final                                         # 1920×1080
node check.mjs out/preview.mp4                                  # 接缝 + 闪烁
node serve.mjs                                                  # 实时页面 http://127.0.0.1:8123/scene.html?w=1280&h=720
```

调试开关：`--raw`（只看颜色通道，不合成）、`--noink`（关墨线）、`--w/--h/--fps/--dur/--sub/--maxsub/--step/--out`。设置 `CHROME_PATH` / `FFMPEG` 可覆盖浏览器和编码器路径。渲染是确定性的：同一个 `t` 永远出同一帧，可以只重渲某几帧。

## 校验结果

`node check.mjs out/preview.mp4`（960×540 / 300 帧）：

```
seam      : 0.70 / 255   OK          # 循环接缝
frame diff: mean 11.05  max 59.81    # 最大运动在二次推近
still     : 151 frames, blinking 5 (worst 2.6%)
verdict   : PASS
```

闪烁来自雨丝与霓虹，属于预期运动；相机静止段没有几何 popping。`out/final.mp4`（1920×1080）同样通过：seam `0.32 / 255`、150 静止帧中 2 帧闪烁、PASS。

## 目录

| 文件 | 作用 |
| --- | --- |
| `src/rig.js` | 相机参数表 `KEYS`、PCHIP 插值、移轴投影、probe 点 |
| `src/city.js` | 程序化雨夜街景：楼体/窗格/店招/路灯/电线/行人/车/雨/换位路锥 |
| `src/textures.js` | 全部 canvas 贴图：沥青标线、地砖、16 格招牌 atlas、海报、光晕 |
| `src/ink.js` | 合成着色器：墨线、双色调、世界空间排线、手绘天空、泛光、分级 |
| `src/main.js` | 两遍几何 + 合成 + GPU 子帧累加；页面钩子 `READY / render / probe / renderMany` |
| `render.mjs` | 逐帧截图 + ffmpeg 编码 |
| `check.mjs` | 循环接缝与闪烁统计 |
| `serve.mjs` | 静态服务 / 实时预览 |

## 可调项

- **运镜**：`src/rig.js` 的 `KEYS`。`H` 是地平线在 NDC 的位置（正值画面下压、负值上抬），`W` 是焦平面宽度，`yaw` 是绕焦点转向，`lay` 是换位进度。改完先跑 `--stills`。
- **画面密度**：`src/city.js` 的 `overpass()` / `lowBanner()` / `building()` / 远景窗墙。
- **配色与墨线**：`src/ink.js` 的 `skyColor()` / `groundFar()`、`edge` 的三个权重、`lit` 阈值、最后的 grade。
- **画幅/质量**：`render.mjs --w --h --fps --sub --maxsub`。

## 已知取舍

- 长焦压平后，画面在焦平面上只有 `W / aspect ≈ 12.4 m` 高，所以海报态是「城市立面的一条横截面」，看不到楼顶和完整街面。这是这个光学效果本身决定的，靠横跨街面的招牌门、低横幅和远景窗墙把这条横截面填满。
- 射出场景的下方像素用按视线方向绘制的 `groundFar()` 兜底（夜雾 + 远处光带），避免出现突兀的纯色空块；它不参与墨线，所以不会闪。
- 排线是"背光面近似"，没有单独渲 shadow map；真正的投射阴影需要用 shadow mask 再替换这一层。
- 场景完全程序化，不依赖任何外部贴图或模型，整个目录可以单独拷走运行。
