# Blender → MiniMax H3 运镜对照试验

此目录是独立试验入口，不改变导演台、正式 H3 图或数据库记录。场景通过 [mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) 2.0.3 在 Blender 5.2.2 LTS 中建立；后续渲染使用同一 `.blend` 文件。所有媒体、graph、日志和报告输出到被 Git 忽略的 `test-results/blender-h3/`。

## 运行

1. 启动本机 Blender 5.2.2，启用 `blender_mcp` 插件并在其侧栏启动 MCP Server（`localhost:9876`）。本机试验可用 `blender.exe --python scripts/blender_h3_pilot/start_mcp.py` 启动。
2. `uv run --with mcp-for-blender==2.0.3 python scripts/blender_h3_pilot/mcp_scene.py`：通过 MCP 写入灰模、相机关键帧并保存 `.blend` 与首帧。
3. `python scripts/blender_h3_pilot/render_preview.py`：用 Blender 5.2.2 渲染 124 帧，FFmpeg 编成 24 fps、608×352 的无声预演视频。
4. `python scripts/blender_h3_pilot/pilot.py`：从 `comfy_provider_settings.base_url` 读取当前地址，检查远端节点及输入，不提交生成。
5. `python scripts/blender_h3_pilot/pilot.py --generate`：A 组首帧参考、B 组首帧加预演视频参考，使用相同 H3 R2V 模型、参数和种子；完成后本地保存成片与耗时。
6. `python scripts/blender_h3_pilot/compare.py`：提取三条视频在 0.5、2.5、4.5 秒的画面，生成横向对照图。

若远端缺少 `MiniMaxH3ReferenceToVideo`、`LoadVideo` 或 `GetVideoComponents`，预检直接失败。脚本不会切换地址、安装远端节点或改动正式任务。失败后再次执行 `--generate` 会跳过已有的成功组。

## 判读

对照首帧、中间遮挡帧和尾帧，记录相机推进方向、柱子遮挡时机、人物画面位置，以及准备和生成耗时。单次 A/B 只回答这条中性镜头是否更可控；需要更多镜头才能判断普遍效率。报告保存在 `test-results/blender-h3/REPORT.md`。

## 写实人物与场景复测

`real_trial.py` 使用项目资产库中有图的角色与场景。两组都上传同一张人物图和场景图，按 `<Picture 1>`、`<Picture 2>` 排序；只有 B 组上传灰模预演视频，并通过 `<Video 1>` 指定它只提供运镜、构图及遮挡时机。灰模首帧不作外观参考。若原场景图有多余人物，可先将处理后场景图放在 `test-results/`，通过 `--scene-image` 指定，脚本仍保存原图以便复核。此处的“写实”指画面风格，资产来源和处理步骤应在报告中说明。

```powershell
python -m scripts.blender_h3_pilot.real_trial --project-id <项目ID> --character <角色名> --scene <场景名> --scene-image test-results/blender-h3-real/scene-clean.png
python -m scripts.blender_h3_pilot.real_trial --project-id <项目ID> --character <角色名> --scene <场景名> --scene-image test-results/blender-h3-real/scene-clean.png --generate
python scripts/blender_h3_pilot/compare.py --output-dir test-results/blender-h3-real
```

不指定 `--scene-image` 时直接使用资产库场景图。复测结果放在 `test-results/blender-h3-real/`，不会覆盖中性灰模对照。判读时同时记录写实身份/场景遵循、灰模风格是否泄漏、镜头推进与前景遮挡、两组耗时；单镜不能证明总体节省制作时间。

2026-09-23 的一条走廊镜头复测中，B 在约 3 秒实现完整前景遮挡，4.5 秒重新显露并推进至更近的人物；A 缺少中段遮挡。B 保留写实外观。实际记录与局限见本机 `test-results/blender-h3-real/REPORT.md`。本次素材是写实风格生成图，不是实拍照片。

## 双人打斗：拳法组合、侧踢与近景运镜

`fight_scene.py` 用 Blender 生成两名分色白膜人物的一镜到底动作：左侧刺拳、右直拳；右侧格挡、低身闪躲、直拳反击，再接侧踢；左侧交叉护臂接触并退步，双方收势。相机轻微横移、绕拍和推进。写实参考图 `fight-reference.png` 由内置 imagegen 根据用户提供的上下构图截图另行生成，只取双人位置与室外跑道创意，不含网页或原视频内容；它只供 H3 锁定人物服装与场景。灰模视频只供动作与摄影参考。

```powershell
$out = (Resolve-Path test-results/blender-h3-fight).Path
& 'C:\Users\Administrator\AppData\Local\Programs\Blender 5.2.2\Blender Foundation\Blender 5.2\blender.exe' -b --python scripts/blender_h3_pilot/fight_scene.py -- $out
& 'C:\Users\Administrator\AppData\Local\Programs\Blender 5.2.2\Blender Foundation\Blender 5.2\blender.exe' -b "$out\fight-previs.blend" -a
ffmpeg -framerate 24 -i "$out\frames\frame-%04d.png" -c:v libx264 -pix_fmt yuv420p -crf 18 "$out\blender-fight-preview.mp4"
python -m scripts.blender_h3_pilot.fight_trial
```

试验产物、H3 graph、生成参数与审片记录在 `test-results/blender-h3-fight/`。`fight_trial.py` 读取 `comfy_row()` 的当前地址；不切换供应商或修改正式工作流。重复执行会跳过已成功的成片。

针对分件白膜可能让视频模型学到肢体缝隙的问题，同一个 `fight_scene.py` 可加 `--continuous`：以每人一张 Skin Modifier 连续人体网格、绝对形态键重演相同关键姿态；原分件物体只保留在 `.blend` 中，不参加渲染。第二版保存至 `test-results/blender-h3-fight-human/`，写实图、H3 提示词、种子和参数相同，仅预演视频改为连续人体网格。这是程序生成的无面部细节人体代理，不等同于带骨骼与肌肉系统的真人动捕角色。

```powershell
$out = (Resolve-Path test-results/blender-h3-fight-human).Path
& 'C:\Users\Administrator\AppData\Local\Programs\Blender 5.2.2\Blender Foundation\Blender 5.2\blender.exe' -b --python scripts/blender_h3_pilot/fight_scene.py -- $out --continuous
& 'C:\Users\Administrator\AppData\Local\Programs\Blender 5.2.2\Blender Foundation\Blender 5.2\blender.exe' -b "$out\fight-previs.blend" -a
ffmpeg -framerate 24 -i "$out\frames\frame-%04d.png" -c:v libx264 -pix_fmt yuv420p -crf 18 "$out\blender-fight-preview.mp4"
python -m scripts.blender_h3_pilot.fight_trial --output-dir $out
```

## UE Manny / Quinn 骨骼白膜打斗与三机位

第三版直接使用本机 UE 5.7 的 `SKM_Manny_Simple`、`SKM_Quinn_Simple`、共用的 `SK_Mannequin` 骨骼及 `MM_Attack_01/02/03` 动画。为避免改动原 UE 项目，已在忽略版本控制的 `test-results/blender-h3-fight-ue/UEFightTrial/` 中按资源原有 `/Game/Characters/Mannequins` 路径建立隔离副本，再导出 FBX。导出清单见 `export-manifest.json`。本轮用 Blender 编排与渲染 UE 角色，成片生成仍通过当前远端 H3 R2V，不涉及 UE 项目场景或工作台正式流程。

`ue_fight_scene.py` 让双方分别使用 UE 原生攻击动作，并在 Quinn 的腿部骨骼上补足收膝、侧踢、接触与收腿。镜头在第 1、33、75 帧切换成斜侧跟拍、越肩近景、低机位冲击镜头；各机位内部有平移或推进。与前两版的程序拼接人形、连续网格代理不同，这版是 88 骨骼驱动的 UE 人形网格。FBX 和素材文件保存在被忽略的测试目录，不提交至代码库。

```powershell
$out = (Resolve-Path test-results/blender-h3-fight-ue).Path
$blender = 'C:\Users\Administrator\AppData\Local\Programs\Blender 5.2.2\Blender Foundation\Blender 5.2\blender.exe'
& $blender -b --python scripts/blender_h3_pilot/ue_fight_scene.py -- $out
& $blender -b "$out\ue-mannequin-fight.blend" -a
ffmpeg -framerate 24 -i "$out\frames\frame-%04d.png" -c:v libx264 -pix_fmt yuv420p -crf 18 "$out\blender-fight-preview.mp4"
python -m scripts.blender_h3_pilot.fight_trial --output-dir $out
```

按《花甲正少年》角色设定替换人物时，从该项目当前资产库抓取吴耐和沙丽丽的“日常造型”设定图，连同无人跑道图按 `<Picture 1>` 吴耐、`<Picture 2>` 沙丽丽、`<Picture 3>` 跑道的顺序输入 H3。三机位 UE 骨骼预演保持一致，单独保存在 `test-results/blender-h3-fight-ue-huajia/`，不覆盖前一版对照。`track-clean.png` 是从此前跑道参考图清除原有人物得到的无人场景图，复现时需保留该文件。

```powershell
python -m scripts.blender_h3_pilot.fetch_huajia_looks
Copy-Item test-results/blender-h3-fight-ue/blender-fight-preview.mp4 test-results/blender-h3-fight-ue-huajia/blender-fight-preview.mp4
python -m scripts.blender_h3_pilot.fight_trial --output-dir test-results/blender-h3-fight-ue-huajia
```

如果 UE 单人攻击片段在成片中出现对打脱节，可使用手工配对的连续白膜编排进行同素材对照。`--film-cuts` 只修改相机机位，不重置左右人物动作；参考图沿用同一批吴耐、沙丽丽和无人跑道图片。实际验收与局限见 `test-results/blender-h3-fight-human-huajia/REPORT.md`。

```powershell
$out = 'test-results/blender-h3-fight-human-huajia'
$blender = 'C:\Users\Administrator\AppData\Local\Programs\Blender 5.2.2\Blender Foundation\Blender 5.2\blender.exe'
& $blender -b --python scripts/blender_h3_pilot/fight_scene.py -- $out --continuous --film-cuts
& $blender -b "$out\fight-previs.blend" -a
ffmpeg -framerate 24 -i "$out\frames\frame-%04d.png" -c:v libx264 -pix_fmt yuv420p -crf 18 "$out\blender-fight-preview.mp4"
python -m scripts.blender_h3_pilot.fight_trial --output-dir $out
```

如配对白膜版的 H3 成片仍把侧踢拍成踢空，可用 `test-results/blender-h3-fight-contact-huajia/` 作构图对照：角色设定图两张不变，把第三张无人跑道图替换为吴耐与沙丽丽脚掌压住护臂的同框参考 `contact-reference.png`，白膜视频不变。该图是接触瞬间参考，提示词明确要求不要当作开场帧；实际结果记录在同目录 `REPORT.md`。

```powershell
python -m scripts.blender_h3_pilot.fight_trial --output-dir test-results/blender-h3-fight-contact-huajia
```
