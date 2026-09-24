# 远端 Blender 动作预演执行器

在当前 ComfyUI 所在的**远端 Windows 电脑**上运行本目录的 `worker.py`。它主动访问工作台 API；MakeHuman FBX、Blender、Blender 插件、接触 IK 和全部渲染也都在这台远端电脑。代码中的 `BLENDER_HOST=127.0.0.1` 是**远端电脑自己的回环地址**，Blender MCP 只监听该电脑的 `127.0.0.1:9876`。工作台电脑不运行 Blender，不连接远端 MCP 端口。不要将 MCP 端口暴露到局域网。

## 准备

### 使用当前远端 ComfyUI 整合包的 Python（远端 PowerShell）

当前远端整合包实际位于 `D:\ZlyFlow-ComfyUI-Portable-20260827-152136`。其中的 `python310\python.exe` 为嵌入式 Python 3.10.11，可运行执行器；它没有 `venv`，且默认没有 `mcp`。**不要把执行器依赖直接安装进整合包的 `Lib/site-packages`**。执行器已上传到远端 `D:\zlyun\Toonflow\action-previs-worker`，在远端 PowerShell 执行：

```powershell
$bundle = 'D:\ZlyFlow-ComfyUI-Portable-20260827-152136'
$py = Join-Path $bundle 'python310\python.exe'
$uv = Join-Path $bundle 'python310\Scripts\uv.exe'
$worker = 'D:\zlyun\Toonflow\action-previs-worker'
Test-Path -LiteralPath $py
& $uv pip install --python $py --target (Join-Path $worker 'vendor') -r (Join-Path $worker 'requirements.txt')
Set-Location -LiteralPath $worker
$env:ZLY_ACTION_UVX_PATH = Join-Path $bundle 'python310\Scripts\uvx.exe'
$env:ZLY_ACTION_FFMPEG_PATH = 'C:\Users\Administrator\AppData\Local\JianyingPro\Apps\11.3.0.14362\ffmpeg.exe'
$env:ZLY_ACTION_MAKEHUMAN_FBX = 'D:\zlyun\Toonflow\action-previs-assets\makehuman-cc0-test.fbx'
& $py .\worker.py --preflight
& $py .\worker.py --smoke
```

上述测试 FBX 已在当前远端电脑生成，包含 MPFB 的蒙皮人形和 `game_engine` 骨骼；若迁移执行器，须重新生成或把 FBX 放在新电脑并修改变量。`Test-Path` 应输出 `True`。先在这台远端电脑启动 Blender、启用 mcp-for-blender 插件，并在侧栏点击 **Connect to MCP server**（端口 9876）；`--preflight` 的 `ready` 应为 `true`。`--smoke` 会渲染约 3 秒的双人、三机位样片，输出在 `$worker\test-results\action-previs\smoke\`。检查 `report.json`、`contact_sheet.jpg`、`preview.mp4` 与可编辑 `.blend`。`ZLY_ACTION_UVX_PATH` 与 `ZLY_ACTION_FFMPEG_PATH` 可使用现有安装的绝对路径，无需修改系统 PATH；剪映更新后若 `ffmpeg.exe` 路径变化，需更新该变量。

### 重新生成 CC0 测试人形

当前远端 Blender 5.2 已安装 [MPFB 2.0.17](https://static.makehumancommunity.org/mpfb/downloads.html)。[MakeHuman 对内置素材及输出的许可说明](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md)允许使用该测试导出物。若换机，在远端下载官方 MPFB 扩展包并执行：

```powershell
$blender = 'D:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$assets = 'D:\zlyun\Toonflow\action-previs-assets'
New-Item -ItemType Directory -Force -Path $assets | Out-Null
Invoke-WebRequest 'https://files.makehumancommunity.org/plugins/mpfb2-latest.zip' -OutFile (Join-Path $assets 'mpfb2-latest.zip')
& $blender --command extension install-file -r user_default -e (Join-Path $assets 'mpfb2-latest.zip')
& $blender --background --python (Join-Path $worker 'generate_mpfb_test_human.py') -- (Join-Path $assets 'makehuman-cc0-test.fbx')
```

远端当前实机 `--preflight` 返回 `ready: true`；`--smoke` 产出了 72 帧、双人三机位的四项产物，诊断 `passed: true`。这只证明任务执行和几何检查通路可用。联系表里动作仍较生硬，进入正式镜头前需要针对表演、打击节奏与镜头手工审片。

通过烟测后才设置工作台与远端执行器共用的令牌、远端可访问的 `ZLY_ACTION_STUDIO_URL`，再在远端运行 `& $py .\worker.py` 常驻领取任务。预检与烟测不需要令牌，也不会提交真实项目任务。

1. 安装 Blender 5.2、`ffmpeg` 和 `uv`。执行器支持现有整合包 Python 3.10.11（依赖装在执行器 `vendor`），也可用独立 Python 3.11。安装并启用 [mcp-for-blender 2.0.3](https://github.com/ahujasid/mcp-for-blender) 的 Blender 插件，点击插件中的 **Connect to MCP server**。执行器通过 `uvx --from mcp-for-blender==2.0.3 mcp-for-blender` 启动 MCP 客户端。
2. 从 [MakeHuman Community](https://static.makehumancommunity.org/makehuman/faq/can_i_sell_models_created_with_makehuman.html) 导出带骨骼和蒙皮的 CC0 人形 FBX，放在远端电脑既有素材目录。不要把模型放进工作台仓库。当前配方能识别 MakeHuman 常见骨骼名；若骨骼不匹配，预演会明确报出缺失骨骼。
3. 在工作台后端与远端执行器设置相同的 `ZLY_ACTION_PREVIS_WORKER_TOKEN`（至少 32 字节随机值）。远端另外设置 `ZLY_ACTION_STUDIO_URL` 为可访问的工作台地址、`ZLY_ACTION_MAKEHUMAN_FBX` 为该电脑上的 FBX 绝对路径。工作台后端需要已经配置 LLM、视觉模型（上传素材时）、七牛云存储和 `ffmpeg`/`ffprobe`。
4. 在远端电脑执行 `python scripts/action_previs_worker/worker.py --preflight`；再执行 `python scripts/action_previs_worker/worker.py --smoke`，实际渲染双骨骼人物、三个机位与 72 帧视频。结果在仓库忽略的 `test-results/action-previs/smoke/` 下。检查 `report.json`、MP4、联系表及 `.blend`；允许质量报告指出接触需要手调，但文件必须齐全、人物须为蒙皮骨骼人形。
5. 通过上述预检后，运行 `python scripts/action_previs_worker/worker.py` 常驻领取任务。`--once` 只领取一次，便于部署检查。使用 Windows 任务计划程序或现有服务管理器守护该进程，不需要另起 ComfyUI。

若只复制 `action-previs-worker.zip` 到远端独立目录，按上方 PowerShell 示例用整合包 Python 安装到 `vendor` 并执行；产物默认写入当前工作目录的 `test-results/action-previs/`。启动领取任务前，再设置工作台 URL 与双方一致的令牌。不要把令牌写入命令行历史、截图或回传日志。

## 限制与返修

- 白膜为动作和运镜预演，不是 H3 输入或成片。动作由受控姿态片段驱动；接触点超过 0.55 米、人物头部出画、单一机位等会记录为需返修。复杂打斗仍需在返回的 `.blend` 中调整动作、IK 和接触。
- 服务端任务租约为 120 秒，执行器每 30 秒续租；取消会立即阻止回传，但已在 Blender 中开始的渲染可能完成当前渲染调用后才停止。执行器失联后任务可由下一次领取恢复；旧租约不能覆盖新结果。
- 该执行器只接收通过后端校验的 JSON 方案，发送给 Blender 的 Python 来自仓库内的静态 `scene_recipe.py`，模型输出不会作为 Python 运行。
