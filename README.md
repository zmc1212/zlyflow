# ZLY AI Studio｜创作工作台

工作台使用 React + TypeScript 前端和 FastAPI 后端，在同一界面提供 GRS 图片生成与本机 ComfyUI 视频生成。工作台提供员工账号、角色权限、任务隔离、多轮创作和浏览器本地资源交付；监听本机与局域网 IPv4 地址的 `7865` 端口，ComfyUI 默认 `http://127.0.0.1:8188`，超级管理员可在「管理设置 → AI 供应商」修改连接地址，不会把 ComfyUI 暴露到局域网或公网。账号、任务和导演工程存储在 `docs/存储配置.md` 中的远程 MySQL；媒体默认使用管理设置中的七牛云。unittest 仍使用临时 SQLite。环境变量前缀与包名继续保留 `zly-ai-video-studio` 兼容标识。

## 启动

1. 启动固定目录 `D:\zlyun\ZLY AI Video Studio\整合包及模型\comfyui-integrate-v1.3\comfyui-integrate\Comfyui` 下的 ComfyUI，默认地址为 `http://127.0.0.1:8188`。若端口或映射地址不同，以超级管理员在「管理设置 → AI 供应商」填写实际地址，或设置环境变量 `ZLY_AI_VIDEO_STUDIO_COMFY_URL`（首次启动写入数据库）。
2. 双击 `启动本地视频工作台.bat`。脚本会分别启动 FastAPI（`7865`）和 Vite 开发服务器（`5173`），并始终自动打开 `http://127.0.0.1:5173`。若 FastAPI 已在运行，重复双击仍打开 5173（必要时补启 Vite），不会打开 7865 上的 `frontend/dist` 静态页。Vite 会显示在独立终端窗口，前端代码变更会自动热更新；后端由 `backend/dev_reloader.py` 监督，修改 `backend/app` 下的 Python 文件或服务异常退出后会自动重启，不再使用 Windows 上会把整个进程组一起关掉的 uvicorn `--reload`。首次使用前执行一次 `pnpm --dir frontend install`。要停止本机工作台时，双击 `关闭本地视频工作台.bat`：脚本会结束 `5173`（Vite）和 `7865`（FastAPI / 监督器）上的工作台进程及对应控制台窗口，不会关闭 ComfyUI（`8188`）。若端口被其他无关程序占用，脚本会提示而不强制结束。
3. 首次打开时在工作站本机 `http://127.0.0.1:5173/setup` 创建超级管理员，再由管理后台分配员工账号。之后登录地址为 `/login`，登录成功默认进入 `/generate/video`。图/视频任务为 `/generate/image/:jobId` 与 `/generate/video/:jobId`，导演工程为 `/director/:projectId`（可选 `?stage=` 与桌面 `?view=plan|timeline`）或 `/director/batch/:projectId`，导台2 项目列表为 `/director2`、项目内模块（内容库、资产库、剧集工坊、全部任务）为 `/director2/:projectId`，资产库为 `/assets`。管理设置可通过 `/admin/accounts`、`/admin/providers`、`/admin/llm`、`/admin/storage` 直达；员工打开 `/admin` 会被送回创作台。刷新或浏览器进退会停留在对应 URL。未登录打开这些链接会先登录，成功后再回到原路径。
4. 使用本机 `127.0.0.1` 或 HTTPS 浏览器交付时，员工首次登录并修改初始密码后需选择本机资源目录；最新版 Chrome/Edge 仅在这些安全上下文允许目录授权。通过局域网 IP 访问时不再阻塞目录选择，启用七牛云后直接使用结果中的七牛云短期签名地址播放或下载。
5. 若 7865 已被其他程序占用，请先确认或关闭该程序，再启动工作台。

zlyadmin
qlxing.1

### 启用 GRS 生图

1. 本地双击启动时，脚本会在首次运行自动创建 `data/credential.key` 并在后续启动中复用；该文件只用于加密数据库中的 GRS API Key，不得与数据库分开丢失。也可用环境变量 `ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY` 显式覆盖。
2. Docker/服务器部署应生成 Fernet 主密钥并写入 `.env`：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`。主密钥缺少或错误时应用仍可启动，视频与历史不受影响，图片提交会锁定。
3. 以超级管理员进入“管理设置 → AI 供应商”，填写 GRS Base URL 与 API Key。国内默认 `https://grsai.dakka.com.cn`，连不上时可改为国际节点 `https://grsaiapi.com`。连接测试会直接验证当前输入值，无需先保存；验证成功后仍需点击“保存配置”供图片任务使用。
4. 生图模型由管理后台「GRS 图片供应商」目录配置；默认启用 GPT Image 2 / GPT Image 2 VIP，也可打开 Nano Banana 等 GRS 文档模型。支持 0–10 张有序参考图、每轮 1–4 张结果；真实测试会产生上游消耗，应先获得费用批准。参考图含真人时，上游可能判定内容违规；若实际已出图，工作台会显示为已完成或部分完成并保留结果，同时展示审核失败原因。

本机开发入口为 `http://127.0.0.1:5173`，Vite 会将 `/api` 转发到 `7865`；`7865` 仍可作为 FastAPI 的生产静态资源和局域网访问地址。设置 `ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE` 与 `ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE` 后，Vite 与 FastAPI 会同时使用 HTTPS。即使已有账号认证，也不得把 `7865` 直接暴露到公网。

## Docker 服务器部署

`ZLY AI Video Studio` 将前端和 FastAPI 构建为同一个 Docker 镜像；镜像不包含 ComfyUI、模型或自定义节点。服务器通过同一个 HTTPS origin 对外提供工作台：`https://comfyui.zlyun168.com/` 是前端，`https://comfyui.zlyun168.com/api/*` 是工作台 FastAPI。ComfyUI 不再通过域名或 `/api` 暴露，而是仅由容器在服务器内部访问 `http://127.0.0.1:18188`。

部署前请确认：

- 服务器为 Linux，并已安装 Docker Engine、Docker Compose Plugin 和 Nginx。Compose 使用 `network_mode: host`，使工作台可访问同机回环地址的 ComfyUI。
- ComfyUI 已通过 FRP 映射到服务器 `127.0.0.1:18188`；不要为工作台另建 ComfyUI 容器，也不要将 ComfyUI 的 `/prompt`、`/history`、`/view`、`/upload/image` 或 `/ws` 反向代理到公网。
- `browser-stream` 不需要服务器访问或挂载远端 ComfyUI 的 `output` 目录。当前工作台仅提供 MiniMax H3 系列模式，所有 ComfyUI API graph 均由后端动态生成，不需要工作流 JSON 目录或挂载。

```bash
# 在服务器上的项目目录执行
cp .env.example .env
# 编辑 .env：确认 ZLY_AI_VIDEO_STUDIO_COMFY_URL 为服务器通过 FRP 可访问的 ComfyUI 地址
docker compose build
docker compose up -d
docker compose ps
curl http://127.0.0.1:18189/api/health
```

镜像构建会先升级 pip，再按 `backend/requirements.txt` 安装二进制轮子；默认使用清华 PyPI 镜像和 npmmirror。若要改回官方源，在 `.env` 中设置 `PIP_INDEX_URL=https://pypi.org/simple` 与 `NPM_CONFIG_REGISTRY=https://registry.npmjs.org` 后重新执行 `docker compose build`。

### Nginx HTTPS 反向代理

将 `docker/nginx/zly-ai-video-studio.conf.example` 上传到服务器项目目录。该配置只将工作台根路径和 `/api/` 代理到 `127.0.0.1:18189`，不会公开 ComfyUI。`/api/` 显式关闭 Nginx 请求/响应缓冲，因此 `browser-stream` 视频传输不会写入 Nginx 临时文件。

先将以下三项替换为实际值：`server_name`、`ssl_certificate`、`ssl_certificate_key`。若域名不是 `comfyui.zlyun168.com`，必须同步替换 HTTP 与 HTTPS 两个 `server_name`。然后执行：

```bash
sudo install -D -m 0644 docker/nginx/zly-ai-video-studio.conf.example \
  /etc/nginx/conf.d/zly-ai-video-studio.conf

sudo nginx -t
sudo systemctl reload nginx
curl -I https://comfyui.zlyun168.com/api/health
```

防火墙仅对公网放行 `80/tcp`、`443/tcp`；不要放行 `18189/tcp` 和 FRP 映射的 `18188/tcp`。首次超级管理员初始化接口 `/api/auth/setup` 只接受服务器本机回环请求，按下一节的 `docker compose exec` 命令初始化。

通过 SSH 登录服务器后，先进入容器并通过容器回环接口完成首位管理员初始化：

```bash
docker compose exec zly-ai-video-studio sh
python -c 'import getpass, json, urllib.request
payload = json.dumps({"username": input("username: "), "display_name": input("display name: "), "password": getpass.getpass("password: ")}).encode()
request = urllib.request.Request("http://127.0.0.1:18189/api/auth/setup", data=payload, headers={"Content-Type": "application/json"}, method="POST")
print(urllib.request.urlopen(request, timeout=15).read().decode())'
exit
```

`python -c` 会保留终端的标准输入，因而可以安全地交互输入账号、姓名和密码。不要使用 `python - <<'PY'`：该形式会占用标准输入传递脚本，随后 `input()` 会得到 `EOFError`。

`ZLY_AI_VIDEO_STUDIO_SECURE_COOKIES=true` 已由 Compose 固定启用，因此必须先完成受信任 HTTPS 反向代理再让员工访问。

更新镜像时执行 `docker compose build --pull && docker compose up -d`。SQLite 与上传素材保存在 Docker 命名卷 `zly-ai-video-studio-data`；完成的视频不写入该数据卷，工作台在用户保存时从 ComfyUI `/view` 实时转发到员工电脑。ComfyUI `output` 保留在其运行的电脑上，由该电脑按保留策略清理。停止并删除工作台容器不会删除数据库和上传素材；需要完整回滚时执行 `docker compose down`，恢复旧镜像并 `docker compose up -d`，不要执行 `docker compose down -v`。

### ComfyUI 宿主机浏览器直连交付

当员工在运行 ComfyUI 的同一台电脑使用浏览器时，工作台会先请求该电脑的 `http://127.0.0.1:8188/view`，直接流式写入员工已授权的资源目录，不经服务器或 FRP 传输视频字节。其他电脑、未运行 ComfyUI 的电脑、文件已被清理或本机读取失败时，会自动回退到既有的服务器 `browser-stream` 交付。

远端 ComfyUI 宿主机必须在启动时为实际工作台 HTTPS Origin 开启精确 CORS，例如：

```cmd
Start-ComfyUI.cmd --enable-cors-header https://comfyui.zlyun168.com
```

将该域名替换为企业实际工作台 Origin（协议、域名和端口必须完全一致），然后重启固定的 ComfyUI 实例。不要使用 `--enable-cors-header` 的无参数形式或 `*`；ComfyUI 仍只监听 `127.0.0.1:8188`，不得公开 `/view`。

若使用本机构建后导出的镜像归档，将 `deploy-server-image.sh` 放入服务器项目目录，并将 `zly-ai-video-studio_latest.tar` 放入项目内的 `packages` 目录后执行 `bash deploy-server-image.sh`。例如项目目录为 `/datas/zly-ai-video-studio` 时，默认归档路径为 `/datas/zly-ai-video-studio/packages/zly-ai-video-studio_latest.tar`。脚本也兼容项目目录内同名 tar，或通过 `bash deploy-server-image.sh /absolute/path/to/zly-ai-video-studio_latest.tar` 指定归档路径；它不会执行 `docker compose down` 或删除数据卷。

## 功能

- GRS 图片生成：管理后台维护可启用的模型目录（GPT Image 2 / VIP、Nano Banana 系列及自定义 ID）；每个启用模型作为独立工作流出现在创作页。支持参考图、比例、1K/2K/4K、VIP 自定义尺寸、单轮 1–4 个并发生成项、部分成功和失败项重试。
- 图片与视频任务统一为“任务 → 轮次 → 生成项”；同任务不混合媒介，图片结果可创建有关联的新视频任务并预填首帧。
- MiniMax H3 提示词技能体系与大模型智能优化：结合 MiniMax-H3 官方开源技能规范（三维运镜语法、多模态时序结构、环境音效与背景配乐），融合 OpenAI 兼容大模型（魔搭按魔粒计费；硅基流动 7B / 本机 Ollama 可零云端消耗），提供电影级通用、极简电商广告、3D动画短片、立体纸艺定格、品牌宣传、音乐短片、双人游戏片头、纸拼贴与手绘发光实景等 9 大细分风格技能的一键智能优化。
- MiniMax H3 Web AI 导演台（Director Studio）：进入导演台先选导演创作或短视频批量。导演创作用 9 Agent 生成可编辑 Recipe。工程页顶栏常驻「AI 生成 / 手动编辑」创作模式切换（`?mode=manual`，工程级记忆、刷新保持；AI 写作进行中禁用）：手动编辑模式下剧本阶段与普通阶段同布局（显示左侧阶段导航与任务头，可随时跳转其他环节），直接以「手动编辑剧本」表单编辑（隐藏 Prompt Bar / 澄清卡 / 继续生成），画风「生成创作方案」、「根据剧本生成分镜」等 AI 写作入口隐藏，角色/场景/道具可「新增」空白卡片手动填写，分镜可「新建空白镜头」或导入 Markdown，配乐阶段可编辑「配乐方案 / 环境声方案」文本；定妆、渲染、配音、合成等执行类操作保持可用，手动内容即时计入阶段就绪度，切回 AI 生成时引导链自动跳过已完成环节。方案视图左栏是四组任务（故事与风格 / 视觉素材 / 镜头设计 / 声音与交付），右侧只显示当前任务；当前任务写在 `/director/:projectId?stage=`，刷新和后退保持位置。桌面顶栏可切「方案 | 剪辑」（`?view=plan|timeline`，默认方案）；手机只保留方案视图（镜头横条 + 抽屉）。任务徽标由前端从 payload 派生（剧本、画风、分镜、定妆图、Takes、ttsUrl、muxStatus），不看 `agentStatus`。顶栏「生成创作方案」只写剧本/画风/分镜/人物场景/声音方案，不会生成视频或配音音频；剧本创作阶段为全屏 Agent 对话界面（无左侧导航与页签，顶栏只留返回/工程名/主题/串播/更多）：点击发送后先进入创意澄清——AI 根据创意流式提出 2-3 个剧情走向问题和 1 道镜头数量题（Approval Card 逐题作答，可选推荐项、自己写或跳过；镜头数量题固定提供约 8/16/30/50 个镜头四档并支持自填任意数量），答完自动按所选方向与确认的镜头数量生成剧本（剧本 Beat 数量随之受控，单独重跑剧本也沿用本次确认的方向与数量）；随后进入逐步确认链——画风、角色、场景、分镜手法、配音、配乐每个环节生成前，AI 结合已有剧本再流式提出 2-3 个确认题（同样可选推荐项、自己写或跳过，画风选项对齐画风目录），确认后只生成该环节并继续下一环节，已产出环节自动跳过，中途失败或取消即停链，刷新/中断后可在成稿区用「继续生成：XX」恢复，全部环节完成后出完成卡；失败完成卡提供「重试<环节名>」按钮——分镜重试为续跑（保留已产出镜头，只补跑对白补全、按秒时长与衔接校验，不重头拆镜；无镜头时回落完整重拆），任务栏失败行的重试 pill 行为一致；对话顶部为垂直生成任务面板（每步一行状态图标+实时消息+总进度条+耗时，完成后折叠可回看），分镜按镜头行实时打印（完成镜头收成一行镜号+标题，当前镜头展开流式全文；打磨阶段切换为阶段进度面板——镜头芯片随「正在第 N 镜」逐镜推进高亮，当前镜头被润色的画面描述与对白实时流式打印，已收字数动态计数），画风以卡片展示并可弹层更换，完成后由记录流 footer 提供完成卡与「继续生成」引导；点「进入视觉素材」等引导切换到保留左侧导航的编辑工作台，侧栏点「剧本」随时回对话。生成中剧本任务区为直播工作区（桌面端为左右两栏：左侧 248px 任务栏只负责进度全景——每环节一行状态 + 顶部进度条与耗时，行可点开抽屉；右侧整块为时间线）：已完成环节压缩为单行记录（状态图标 + 环节名 + 结果摘要，点击弹出抽屉查看该环节完整产出，失败行可直接重试；行尾悬停出现「重新生成」按钮，弹窗可选「仅重做本环节」或「重做本环节并清空后续环节」（会列出受影响环节，级联清空后自动从下一环节继续逐步引导重做；生成失败或取消不会清空后续），并可选「直接重新生成」或「调整要求后重新生成」（重新回答该环节确认题后再生成；脚本/研究/媒体仅直接重生成）），任务栏已完成行提供同样的重新生成入口，重新生成分镜时提示已有镜头媒体关联可能失效（原任务媒体不会被删除），当前正在生成的环节是唯一的全宽直播卡片（无流式产出的环节显示骨架占位），流式内容始终自动贴底跟随（向上滚动即暂停跟随并浮现「回到底部」，新环节开始自动跳回最新处），创意气泡与创作方向 chips 按对话顺序排在时间线开头，刷新页面可恢复观看；手机上任务面板保持折叠摘要置于时间线上方；完成后停留展示完成卡与成稿文档（各环节产出仍可从记录行或任务栏抽屉回看），用「编辑剧本」显式切回表单微调或「进入视觉素材」继续，未生成时显示居中欢迎区（含示例创意点击填入）；创意输入采用对话式 Prompt Bar 固定在内容区底部（Enter 发送，生成中变为状态条并承担取消，画风等其他阶段保留原入口），发送后创意以气泡显示在对话顶部；全部定妆、全部出片、生成全部配音、导出成片仍在各任务区，提交前弹出数量与预计消耗。短视频批量页主题输入同样移至底部 Prompt Bar，原表单卡只保留生成参数。9 Agent（含研究/媒体）只在折叠的「AI 运行详情」里。点击「镜头设计」会按当前剧本一次性生成全部镜头（没有完整故事时先写脚本再拆镜），不再回退成单条「主镜头」；生成中主区显示镜头占位卡和人话阶段（读剧本/整理镜头），进度按本次实际步骤计数，不把大模型原文或思考过程打到画布上。自动分镜按 MiniMax H3 官方 `h3-prompt-writing` skill 写镜头正文、运镜和对白；提交时编译为 T2VA 三段式或 Ref2VA 六段式提示词。定妆走 GRS，分镜视频走本机所选工作流。员工级资产库保存人物/场景/道具（图 + 提示词），可在不同工程插入；不建系列分集。镜头设计页（阶段内以「设计 / 制作」切换：设计=编辑镜头序列与提示词，制作=生成设置与逐镜出片）为左镜头列表 + 右 Inspector（手机为横向条 + 抽屉）。桌面「剪辑」视图是同一份 Recipe 的素材栏 + 预览/串播 + 镜头轨 + Inspector，可改标题、描述、对白、时长、角色、场景和机位；默认预览档，可切终稿。画风默认 6 张推荐。保存约 800ms 防抖并显示状态。分镜页可改工作流（LightX2V / 八步双加速 / 官方 MiniMax H3 等）、画面比例、分辨率（0.4 / 1.0 / 2.0 MP）和生成速度；文生、首尾帧、多参考仍按镜头素材自动匹配。16GB 显卡建议 0.4 MP。参考图在提交时自动装箱最多 9 张。短视频批量按主题裂变多条脚本，并按所选工作流并行文生。手机上 Recipe/批量有返回工程库的头栏和底部主按钮（随当前任务切换）；镜头与批量条目显示中文状态，失败可就地重试。工程保存在 SQLite（员工隔离）。旧时间轴工程打开时转为 Recipe。Analyze 仅在大模型支持视觉时根据参考图提取外貌。成片可串播、导出剪映草稿，也可在「成片」任务里用本机 ffmpeg 合成 MP4 并下载 FCPXML/EDL。配音走 OpenAI 兼容 TTS（可复用大模型凭据，不使用 Edge TTS）；本机需安装 ffmpeg/ffprobe 才能导出工作台内成片。
- MiniMax H3：官方文生 / 首尾帧 / 多参考（采样前预留 3 GB 显存并启用 H3 显存高效 Sage），以及自定义「全能参考（多速率）」和「双时钟加速」。另接入 LightX2V 文生 / 首尾帧 / 多参考（默认 1.0 MP、4 步 euler），以及「八步双加速」文生 / 首尾帧 / 多参考（默认 0.4 MP、8 步，FL2V Turbo LoRA + KJ Sage + H3 Sage）。创作页工作流下拉按 LightX2V、八步双加速、官方 MiniMax H3、自定义分组。可选择生成速度：快速 4 步、均衡 8 步、高质量 20 步，或自定义 1–40 步（八步双加速默认即为 8 步档）。创建栏可切换模型体积：完整（32 GB，可挂加速 LoRA）或精简（20 GB，关闭加速 LoRA，适合 32 GB 内存）。尺寸、时长、采样、音频、模型、显存与编码参数由后端 schema 动态显示并在任务详情完整回显。


- 串行任务队列、任务状态、SQLite 任务记录与本地作品库。排队中或生成中的任务可在工作台点「停止生成」：视频会中断固定 ComfyUI 上的对应 prompt 并标记为「已停止」，不会自动重新提交；图片只停止本地等待。本地视频队列空闲后，工作台会通知 ComfyUI 卸载模型并释放显存/内存；若还有下一条视频在排队则保持加载。
- ComfyUI 或 FRP 短暂重启时，运行任务会在连续 30 秒无法通信后标记为“已中断”并释放队列。工作台会继续侦听固定 ComfyUI；若原任务仍在队列或历史中则接回，若进程已重启导致任务丢失则按原参数自动重新提交（最多 3 次）。用户主动停止的任务不会自动重提。显存中未完成的推理无法续跑。仍可在任务详情手动点“重新提交”。
- 超级管理员、管理员、员工三级角色；员工仅可读取自己的任务、参考图和资源。管理员可在生成页与资产页切换用户查看对应任务，切到他人时为只读查看，新建任务仍归属当前管理员。
- 浏览器授权本地目录、生成完成后自动流式保存和交付回执。
- `ZLYUN AI` Windows 桌面客户端：为企业员工提供受控的本地目录交付、可靠本地预览和安装包更新基础；Web 工作台继续保留。

新作品写入员工授权目录的 `ZLY AI Studio/<YYYY-MM>`；既有 IndexedDB 记录和 `ZLY AI Video Studio` 目录继续只读兼容。GRS 图片成功 URL 会在后端校验 HTTPS、重定向、公网地址、MIME、文件签名和 50 MB 上限后暂存，浏览器/桌面端确认交付后立即清理。


## 2026-08-31 导台2 与内容库

- 用户可见行为：左侧导航增加「导台2」（`/director2`）。内容库采用居中导入卡片：可上传 TXT/Markdown/Word 或粘贴正文，开始导入后会切章并调用已配置大模型分析，页面底部展示摘要、角色、场景、道具和剧集规划。资产库、剧集工坊、风格中心、制作助手为占位页。
- 受影响文件：导台2 前后端、`sql/002_xiaji_ingest.sql` 与三份主文档。
- 兼容性：不改既有导演台、工作流和 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复代码并重建前端；可选删除 MySQL 中的 `xiaji_*` 表。

## 2026-09-01 导台2 粘贴导入登录校验

- 用户可见行为：粘贴正文后点开始导入不再因缺少 `user` 查询参数而 422。
- 受影响文件：`backend/app/xiaji_api.py`。
- 兼容性：请求 JSON 不变。
- 验证命令：`python -m unittest backend.tests.test_xiaji`。
- 回滚方式：恢复 `xiaji_api.py`。

## 2026-09-01 导台2 资产库

- 用户可见行为：导台2「资产库」可从内容库同步角色、场景、道具和解说声线；可编辑定义、生成/上传参考图，并为角色与解说生成声线定义、合成试听或上传参考音频。
- 受影响文件：`sql/004_xiaji_assets.sql`、导台2 资产前后端。
- 兼容性：不改导演台、工作流和 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复代码；可选删除 MySQL 中的 `xiaji_assets` / `xiaji_asset_media`。

## 2026-09-01 资产库 GRS 生图

- 用户可见行为：导台2 资产库点「生成参考图」会立刻提交任务并结束转圈；图片在后台用已启用 GRS 生成，完成后资产状态变为就绪。
- 受影响文件：资产库前后端与三份主文档。
- 兼容性：不改 ComfyUI 与导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-01 场景正面/背面/360 分视角生图

- 用户可见行为：导台2 资产库场景页的「重生源图」「重生背面」「生成 360」分别按不同提示词入队，不再复制同一张正面图。
- 受影响文件：场景提示词、资产生图 API、场景编辑页与三份主文档。
- 兼容性：不改 ComfyUI 与导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-01 道具主视图/转面/特写分视角生图

- 用户可见行为：导台2 资产库道具页的「重生主图」「重生转面」「生成特写」分别按不同提示词入队，不再复制同一张主视图。
- 受影响文件：道具提示词、资产生图 API、道具编辑页与三份主文档。
- 兼容性：不改 ComfyUI 与导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-01 导台2 剧集工坊

- 用户可见行为：导台2「剧集工坊」可从内容库规划生成剧集；单集可生成/预览脚本 Beat，并按镜头入队草图。合成页仍为占位。
- 受影响文件：剧集工坊前后端、`sql/006_xiaji_episodes.sql` 与三份主文档。
- 兼容性：不改导演台、工作流和 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复代码；可选删除 `xiaji_episodes` / `xiaji_episode_links` / `xiaji_beats`。

## 2026-09-01 导台2 镜头工作台

- 用户可见行为：剧集「镜头」页改为左右分栏。左侧点选 Beat，右侧可改台词/画面、勾选出场身份与道具、选择场景正面或背面作为背景参考，再生成或上传草图。视频生成仍为后续版本。
- 受影响文件：镜头工作台前后端与三份主文档。
- 兼容性：不改导演台、工作流和 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-02 导台2 草图/渲染图/视频

- 用户可见行为：镜头页「生成草图」产出白纸色块分镜草稿；「精绘渲染」按草图上色写实，完成后可「重新生成」；「生成视频」默认 LightX2V 多参考，头部可选模型、时长、MP、分辨率、部署。未完成上一步时会提示先生成草图或渲染图。
- 受影响文件：导台2 剧集工坊前后端、`sql/007_xiaji_beat_media.sql` 与三份主文档。
- 兼容性：不改 ComfyUI 节点；不接入 DramaClaw 的 NanoBanana/Seedance。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-02 导台2 渲染重生成与视频参数

- 用户可见行为：渲染图生成后可重新精绘。视频条展示 LightX2V 多参考等模型，以及时长、MP、分辨率、部署（均衡 8 步），提交时写入该工作流的 `options`。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI 节点；不改 LightX2V 全局默认 MP。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-02 导台2 头像与造型并发生图

- 用户可见行为：资产库同一角色可同时生成肖像和造型图；完成后两张图各自回填，不再互相覆盖。场景分视角、道具分视角同样按槽位回填。
- 受影响文件：导台2 资产库前后端与三份主文档。
- 兼容性：不改 ComfyUI、表结构和导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 生成本 Beat 视频提示词

- 用户可见行为：镜头视频区可「生成本 Beat 提示词」。页面显示中文，并列出 `<Picture n>` 各图职责。点「生成视频」把对应英文稿传给本机 LightX2V。全部任务可看到这次大模型调用。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI。重启后端会补 `video_prompt_zh` 列。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiBeatPromptTests`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 失败视频可重提交

- 用户可见行为：视频任务失败后镜头不再一直「生成中」，显示失败原因，可点「重新生成视频」。生成本 Beat 提示词改为独立接口，避免 Method Not Allowed。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI。需重启后端。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiEpisodeTests.test_failed_video_job_clears_generating_status backend.tests.test_xiaji.XiajiEpisodeTests.test_video_prompt_accepts_post_not_get`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 提示词使用所选时长

- 用户可见行为：镜头选 10 秒再「生成本 Beat 提示词」，全部任务里的时长入参是 10，不再固定 5 秒。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI。需重启后端。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiEpisodeTests.test_video_prompt_uses_selected_duration`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 提示词写清每张参考图

- 用户可见行为：生成本 Beat 提示词会写明 `<Picture n>` 是哪张精绘、谁的头像、哪套造型、哪个场景，并按本镜动作写较完整的运镜解说。生成视频仍用这篇英文稿。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI。需重启后端，再点一次「重新生成本 Beat 提示词」。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiBeatPromptTests.test_video_motion_messages_name_each_picture_material`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 镜头页显示最新提示词

- 用户可见行为：全部任务里已经成功的「生成本 Beat 提示词」会写回镜头中文/英文稿。刷新镜头 1 应看到齐静春、陈平安等专名，而不是「锁定英雄脸部」。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI。需重启后端并刷新页面。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiEpisodeTests.test_hydrate_applies_latest_video_prompt_job`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 精绘失败不再卡住

- 用户可见行为：精绘或视频任务失败后，镜头页显示「失败」和错误原因，不再一直「精绘中」。可直接重新生成。
- 受影响文件：导台2 剧集工坊前后端与三份主文档。
- 兼容性：不改 ComfyUI。重启后端会给 `xiaji_beats` 补状态列。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiEpisodeTests.test_failed_render_job_clears_generating_status`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 精绘按头像再造型附图

- 用户可见行为：镜头「精绘渲染」为每个出场角色先传入头像、再传入造型图，不再把造型图当成脸。已有角色若头像字段曾被造型任务覆盖，打开资产或重新精绘时会改回真正头像。
- 受影响文件：导台2 剧集工坊与资产回填、三份主文档。
- 兼容性：不改 ComfyUI。重新精绘即可按正确参考图入队。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_hydrate_rewrites_portrait_when_image_job_id_is_look backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_render_character_refs_are_face_then_costume`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 大模型任务进入全部任务

- 用户可见行为：内容导入、生成脚本、用大模型生成声线定义都会在项目「全部任务」留下记录。点开可看到系统提示词、用户提示词、完整 messages、模型参数和模型输出。
- 受影响文件：`sql/008_xiaji_llm_jobs.sql`、导台2 任务前后端与三份主文档。
- 兼容性：不改 ComfyUI 与导演台。已有 MySQL 需补建 `xiaji_llm_jobs`（启动时也会 `CREATE TABLE IF NOT EXISTS`）。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiLlmJobTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码；可选删除 `xiaji_llm_jobs`。

## 2026-09-03 导台2 整集自动生成任务

- 用户可见行为：镜头页「生成本集草图」改为「添加自动生成任务」。提交时锁定当前视频工作流与时长等参数，从第 1 镜起依次生成草图、精绘、提示词和视频；上一镜成片后才开始下一镜。进度显示在按钮旁，全部任务里有一条整集编排记录。
- 受影响文件：导台2 剧集工坊前后端、`sql/010_xiaji_episode_runs.sql` 与三份主文档。
- 兼容性：不改 ComfyUI。旧「批量草图」API 仍可用。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiEpisodeTests.test_auto_run_conflict_and_sketch_gate backend.tests.test_xiaji.XiajiEpisodeTests.test_auto_run_locks_video_params_and_skips_ready_sketch`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码；可选删除 `xiaji_episode_runs`。

## 2026-09-03 导台2 全部任务

- 用户可见行为：项目 Tab「制作助手」后增加「全部任务」。生成中页面底部出现「生成任务」条，点开可看每个任务是否完成、槽位、提示词和回调图。
- 受影响文件：导台2 资产库/任务列表前后端与三份主文档。
- 兼容性：不改 ComfyUI 与导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码。

## 2026-09-03 场景背面/360 传入正面参考图

- 用户可见行为：导台2 生成场景背面时会把已有正面源图作为 REFERENCE 1 传给生图接口；生成 360 时按顺序传入正面和已有背面。没有正面图时，背面生成会提示先上传或生成正面源图。
- 受影响文件：`xiaji_asset_api.py`、`xiaji_asset_prompts.py`、测试与三份主文档。
- 兼容性：不改 ComfyUI、表结构和导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests`。
- 回滚方式：恢复上述代码。

## 2026-09-03 场景背面失败后可重新生成

- 用户可见行为：背面/360 生成失败后按钮不再一直转圈，会显示失败原因，可再次点击生成。本次会把正面图作为参考图传入。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 任务详情显示传入图和全部参数

- 用户可见行为：全部任务里点开一条记录，可看到传入的参考图、提示词、options 和其他全部入参。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_list_project_jobs_returns_slot_records`。
- 回滚方式：恢复上述代码。

## 2026-09-04 导台2 重新导入会清空项目内容

- 用户可见行为：项目里已有文稿、资产或剧集时，再点「开始导入」会先提示将清空现有内容。确认后旧内容库、资产库和剧集会删掉，再用这次导入重新分析。取消则保持原样。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiProjectIsolationTests`。
- 回滚方式：恢复上述代码。

## 2026-09-04 导台2 生成脚本改为逐行标注

- 用户可见行为：「生成脚本」按原文一行一个 Beat，不再改写成 8–40 条。场次头直接成场景镜头；对白行保留原台词。某一行模型超时不会让整集失败。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiLiteralScriptTests backend.tests.test_xiaji.XiajiLlmJobTests`。
- 回滚方式：恢复上述代码。

## 2026-09-04 导台2 画风下拉预览与头像风格图

- 用户可见行为：生成角色头像会把当前画风预览图作为参考图传入，并按该图对齐颜色。

## 2026-09-04 导台2 家页画风入口

- 用户可见行为：导台2 家页「画风」进入 `/director2/art-styles`，显示 34 条目录，不会瞬间回到项目列表。

## 2026-09-07 导台2 剧集成片合成

- 用户可见行为：剧集工坊「合成」可在至少一段镜头视频就绪后拼接本集成片（720p/1080p、可选字幕），场次卡不挡住按钮，未出片镜头会跳过。可预览下载 MP4，并导出 SRT 与素材包。精品剧不强制单独配音；解说剧对入片镜头缺配音时禁用合成。
- 受影响文件：导台2 剧集合成前后端、`sql/012_xiaji_episode_compose.sql` 与三份主文档。
- 兼容性：不改 ComfyUI 与导演台。
- 验证命令：`python -m unittest backend.tests.test_xiaji`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-07 导台2 合成成片写入全部任务

- 用户可见行为：点「合成成片」后，项目「全部任务」会出现一条「合成成片」记录，合成中可看进度，完成后可预览成片。
- 受影响文件：导台2 任务列表与合成入队。
- 兼容性：不改 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiComposeTests`、`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-07 隐藏导台2 空模块 Tab

- 用户可见行为：项目内不再显示「风格中心」「制作助手」占位 Tab；家页模块说明改为内容库、资产库、剧集工坊、全部任务。家页「画风」入口仍可用。
- 受影响文件：`XiajiStudioModule.tsx`、`XiajiHome.tsx` 与三份主文档。
- 兼容性：不改路由与 API。
- 验证命令：`pnpm --dir frontend exec tsc -b --pretty false`。
- 回滚方式：恢复上述代码。

## 2026-09-07 场景参考图强制空镜无人

- 用户可见行为：资产库生成场景正面/背面/360 时按空镜出图，即使场景描述里写了人物动作也不会把人画进画面。重新生成场景图即可。
- 受影响文件：导台2 场景提示词与内容分析。
- 兼容性：不改 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiAssetStoreTests.test_sync_creates_character_scene_prop_and_narrator`。
- 回滚方式：恢复上述代码。

## 2026-09-07 镜头视频提示词加厚为分镜说明书

- 用户可见行为：镜头页「生成本 Beat 提示词」会写出更长的分镜说明书（CUT/运镜/微表演/环境反应）。已有镜头需重新点生成。
- 受影响文件：导台2 镜头视频提示词。
- 兼容性：不改 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiBeatPromptTests.test_bridge_prompt_requires_timing`。
- 回滚方式：恢复上述代码。

## 2026-09-07 镜头视频提示词把本镜动作放到最前

- 用户可见行为：镜头页提示词开头会写「必须演出」+ 本镜动作；生成视频用的英文稿同样以 MUST PLAY THIS ACTION 开头。已有镜头需重新生成提示词再生成视频。
- 受影响文件：导台2 镜头视频提示词。
- 兼容性：不改 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiBeatPromptTests.test_video_motion_leads_with_beat_action`。
- 回滚方式：恢复上述代码。

## 2026-09-07 大模型失败任务展示返回原文

- 用户可见行为：全部任务里失败的大模型调用会显示模型返回原文。历史失败任务没有原文，需重新跑。
- 受影响文件：导台2 全部任务。
- 兼容性：不改 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiLlmJobTests.test_failed_ingest_job_keeps_model_raw`。
- 回滚方式：恢复上述代码。

## 2026-09-04 导台2 用画风目录替换视觉风格

- 用户可见行为：导台2 家页「新建项目」左侧可进画风页，点选后作为新项目默认。项目内容库用导演台画风替换原「视觉风格」六选项。资产库生成默认跟内容库，生成前可改；改完点重新生成不会弹回旧值。
- 验证命令：`python -m unittest backend.tests.test_xiaji`。
- 回滚方式：恢复上述代码。

## 2026-09-04 导台2 资产视觉风格跟随内容库

- 用户可见行为：内容库选「动漫」后，资产库角色下拉会带上该风格（原先为空的角色）。新建角色同样继承项目画风。已单独改过画风的角色不会被覆盖。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiAssetStoreTests.test_sync_fills_empty_visual_style_without_overwriting backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_generate_image_uses_project_visual_style_when_asset_empty backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_create_asset_inherits_project_visual_style`。
- 回滚方式：恢复上述代码。

## 2026-09-04 导台2 造型图对齐 sourceXd 身份锁定

- 用户可见行为：生成造型图会把已有肖像作为身份锚点传入，按 16:9 四面板出图。没有肖像或没填外观描述时不能生成，需先生成/上传头像并填写服装关键词。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_look_generate_keeps_portrait_job_and_media_slots backend.tests.test_xiaji.XiajiGenerateImageRouteTests.test_look_generate_requires_portrait`。
- 回滚方式：恢复上述代码。

## 2026-09-03 导台2 道具主视图/转面/特写对齐 sourceXd

- 用户可见行为：道具「转面图」改为 1x3 三视图（正面/侧面/背面）；主视图、转面、特写均按 16:9 入队。已有主视图时，转面和特写会把主视图作为参考图传入。
- 验证命令：`python -m unittest backend.tests.test_xiaji`。
- 回滚方式：恢复上述代码。

## 2026-09-03 道具附图与场景360须先有主图

- 用户可见行为：没有主视图时不能点「重生转面」「生成特写」；没有正面源图时不能点背面/360。请先生成或上传主图。
- 验证命令：`python -m unittest backend.tests.test_xiaji.XiajiGenerateImageRouteTests`。
- 回滚方式：恢复上述代码。

## 2026-09-02 管理员查看全部任务不再全表拉取

- 用户可见行为：管理端任务栏「全部用户」对应的 `GET /api/jobs?user_id=all` 在远程 MySQL 上应回到秒级，而不再长时间转圈。列表条数和字段不变。
- 受影响文件：任务存储层、MySQL 索引与三份主文档。
- 兼容性：不改任务创建接口和工作流。
- 验证命令：`python -m unittest backend.tests.test_core.StoreTests.test_jobs_are_filtered_by_owner_and_delivery_is_recorded`。
- 回滚方式：恢复上述代码并重启工作台。

## 2026-09-03 导演台镜头进度条恢复实时刷新

- 用户可见行为：在导演台出片或定妆时，进度条与「生成中 xx%」会随任务进度继续更新，不再停在提交后的固定百分比。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/director/DirectorRecipeStudio.tsx` 与三份主文档。
- 兼容性：不改 API、数据库或 ComfyUI；资产页与导台2 仍不轮询任务列表。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述前端文件并重新构建。

## 2026-09-03 共享数据库视频任务本地素材保护

- 原因：本机工作台与服务器共用远程 MySQL 时，各后端都会恢复排队中的 H3 任务；另一台主机可能先接管任务，却无法读取创建端 `data/uploads` 中的参考图，导致提交 ComfyUI 前报 `No such file or directory`。
- 当前基线：视频 worker 在恢复或执行任务前检查绝对参考图路径；本机读不到时不改变任务状态、不提交 ComfyUI，保留给素材所在工作站接管。相对路径旧任务保持兼容。
- 受影响文件：`backend/app/worker.py`、`backend/tests/test_core.py` 与三份主文档。
- 兼容性：不改 API、数据库 schema、工作流、ComfyUI 节点、模型路径或端口；只收紧共享数据库下的视频任务接管条件。
- 验证命令：`python -m unittest backend.tests.test_core.WorkerTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复 worker 的本地参考图检查及对应测试和文档；无需迁移数据库或媒体。

## 2026-08-30 导演台方案/剪辑视图切换

- 原因：方案任务导航和剪辑时间轴要共用同一份 Recipe，不能做成第二套引擎；剪辑台是桌面场景。
- 用户可见行为：导演工程地址为 `/director/:projectId?view=plan|timeline`，默认方案。桌面顶栏增加「方案 | 剪辑」分段开关，刷新和后退保持视图。左栏「镜头生成」在桌面进入剪辑视图。手机锁定方案视图，忽略或清掉 `view=timeline`。
- 受影响文件：`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`director-recipe-view.contract.ts`、`index.css` 与三份主文档。
- 兼容性：不改 API、`agentStatus` 或旧 Recipe。无 `?view=` 时仍是方案视图；`?stage=` 行为不变。
- 验证命令：`pnpm --dir frontend build`。浏览器登录后导演工程桌面 1440 切换方案/剪辑并刷新恢复；手机 390×844 只显示方案视图。
- 回滚方式：恢复上述前端文件并重新构建。

## 2026-08-30 导演台剪辑视图时间轴

- 原因：方案写完后要在桌面按时间轴选镜、装箱和串播，但不能另做一套 payload。
- 用户可见行为：桌面切到「剪辑」后出现素材栏、预览/串播、镜头轨和右侧分镜检查器，读写同一份导演工程。点已定妆角色/场景加入当前镜；串播会扫过已生成镜头；右键可复制/删除镜头；时长仍限制在 2–15 秒。手机继续只显示方案视图。
- 受影响文件：`DirectorTimelineView.tsx`、`TimelineTrackMain.tsx`、`DirectorRecipeStudio.tsx`、`types.ts`、`index.css` 与三份主文档。
- 兼容性：不改 API 或旧 Recipe。无 `?view=` 仍是方案视图。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器登录后导演工程桌面 1440 检查剪辑轨与 Inspector；手机 390×844 无剪辑台。
- 回滚方式：恢复上述前端文件并重新构建。

## 2026-08-30 剪辑轨适配 RecipeShot

- 原因：镜头轨原先吃旧 `DirectorShot`，剪辑视图还要先转一层才能铺开。
- 用户可见行为：时间轴直接按本镜 `durationSec` 铺开，角色/场景名、首尾帧和中文状态来自 Recipe 镜头；刻度带镜头边界，吸附 playhead。手机仍无剪辑台。
- 受影响文件：`types.ts`、`TimelineTrackMain.tsx`、`TimelineRuler.tsx`、`DirectorTimelineView.tsx`、`director-timeline.contract.ts`、`index.css` 与三份主文档。
- 兼容性：不改 API 或旧 Recipe。`recipeShotsToPlayer` 仍只给串播弹层用。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述前端文件并重新构建。

## 2026-08-30 导演台双模式二期验证

- 原因：方案任务导航与桌面剪辑时间轴已落地，需要按 AGENTS.md 把二期基线写入三份主文档，并完成测试构建与桌面/移动回归。
- 用户可见行为：导演工程仍是 `/director/:projectId`。方案视图四组任务导航 + readiness 徽标，当前任务写在 `?stage=`。桌面可切「方案 | 剪辑」（`?view=plan|timeline`）；剪辑视图是同一份 Recipe 的素材栏、预览/串播、镜头轨和 Inspector。手机只保留方案视图。旧 `agentStatus` 工程可直接打开。
- 受影响文件：`types.ts`、`DirectorRecipeStudio.tsx`、`DirectorStageNav.tsx`、`DirectorTimelineView.tsx`、`TimelineTrackMain.tsx`、`TimelineRuler.tsx`、契约文件、`index.css` 与三份主文档。
- 兼容性：不改 API、`agentStatus` 结构或旧 Recipe。无 `?view=` 仍是方案视图。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器登录后导演工程桌面 1440：四组导航、`?stage=`/`?view=` 刷新恢复、剪辑轨道与 Inspector；手机 390×844 只保留方案视图。
- 回滚方式：恢复上述前端与文档并重新构建。

## 2026-08-30 导演台生成创作方案与重资源确认

- 原因：顶栏「运行导演流水线」被理解成会出视频；voice/music/media Agent「已完成」也不等于用户拿到音频或成片。
- 用户可见行为：顶栏改为「生成创作方案」，并写明只产出剧本/画风/分镜/人物场景/声音方案。全部定妆、全部出片、生成全部配音、导出成片仍在各任务区，按钮带数量，提交前确认预计消耗。单镜/单角色生成不弹确认。手机底栏主按钮随当前任务切换。Agent 完成文案改为「方案已写好，媒体待生成」。
- 受影响文件：`director_recipe.py`、`DirectorRecipeStudio.tsx`、`DirectorExportPanel.tsx`、`action-copy.ts`、`action-copy.contract.ts`、测试与三份主文档。
- 兼容性：不改 API、`agentStatus` 结构或旧 Recipe。已落盘的旧完成文案保持原样，重新跑 Agent 后才会换成新文案。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器登录后导演工程桌面 1440 与手机 390×844：四组导航、`?stage=` 刷新/后退、生成创作方案提示、重资源确认数量。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-30 导演台方案视图四组任务导航

- 原因：左栏 9 个 Agent 与右栏 5 个 Tab 同层级且状态语义矛盾（voice/music/media 显示已完成但没有音频/成片）。
- 用户可见行为：导演创作工程改为四组任务导航（方案、镜头制作、声音、交付），每项显示未开始/草稿/部分完成/已就绪。右侧只显示当前任务。地址为 `/director/:projectId?stage=`，刷新和浏览器后退保持位置。9 Agent 原始状态移入「AI 运行详情」。旧工程无需迁移。
- 受影响文件：`frontend/src/director/types.ts`、`DirectorRecipeStudio.tsx`、`DirectorStageNav.tsx`、`DirectorExportPanel.tsx`、`recipe-readiness.contract.ts`、`index.css` 与三份主文档。
- 验证命令：`pnpm --dir frontend build`。浏览器登录后打开导演工程，检查四组导航、`?stage=` 刷新恢复、桌面 1440 与手机 390×844。
- 回滚方式：恢复上述前端文件并重新构建。

## 2026-08-28 分镜读剧本不再因 180 秒整段超时失败

- 原因：点击「分镜」后卡在「正在读剧本」，约 3 分钟后报「请求大模型服务超时（等待 180 秒仍无响应）」。一次生成全部镜头 JSON 经常超过 180 秒，非流式请求会把还在写的响应直接掐掉。
- 用户可见行为：分镜/导演 Agent 改为流式读取大模型。只要模型持续输出，完整分镜可以超过 3 分钟；进度会从「正在读剧本」变成「正在写分镜（已收到 N 字）」，并显示已等待时间。超时文案不再带 urllib3 原文。超时不会自动再打一遍同样的长请求。连接失败仍会重试一次。
- 受影响文件：`llm_client.py`、`director_agents.py`、`llm_provider.py`、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_llm.ChatCompletionTimeoutAndStreamTests backend.tests.test_director.DirectorAgentPipelineTests.test_chat_text_does_not_retry_timeout`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 生成这一镜在润色提示词期间立即显示提交中

- 原因：点「生成这一镜」后要先等大模型润色提示词，接口几分钟才返回；按钮没有转圈，页面像没反应。
- 用户可见行为：点击后立刻出现「正在润色提示词并提交这一镜…」，镜头状态变为提交中。润色完成才会真正排队出片。分镜还在写时会提示先等写完。
- 受影响文件：`director_jobs.py`、`main.py`、导演台 Recipe 工作面、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorDualEngineApiTests.test_recipes_run_and_render_shots_enqueue_t2v`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 视频工作流可切换精简 UNET

- 原因：32 GB 内存机在快速/均衡档会加载约 32 GB 全量 INT8 UNET，Windows 报 1455 页面文件不足。原先只能靠「高质量」或自定义超过 8 步才能走 pruned。
- 用户可见行为：所有 MiniMax H3 视频工作流的创建栏增加「模型体积」：完整（32 GB）或精简（20 GB）。精简保持所选步数，但关闭加速 LoRA 并加载约 20 GB pruned UNET。导演台分镜与短视频批量同步该选项。默认仍为完整，旧任务不变。
- 受影响文件：`workflow_registry.py`、H3/T8 graph 构建、导演编译与入队、导演台界面、测试与三份主文档。
- 兼容性：不改节点 ID、端口。未传 `weight_profile` 时仍为完整权重。Turbo LoRA 不能挂在 pruned 上。
- 验证命令：`python -m unittest backend.tests.test_core.WorkflowTests.test_weight_profile_pruned_keeps_steps_and_skips_turbo_lora backend.tests.test_director.DirectorCompilerTests.test_canvas_quality_maps_to_registry`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 分镜生成展示阶段与镜头占位，不展示思考原文

- 原因：分镜等待态只有空 Empty，进度在子集运行时仍按 9 步计算，看起来像卡在「脚本 7/9」；把模型思考流到主画布也不符合短剧生产台。
- 用户可见行为：生成分镜时主区长出镜头占位卡，侧栏显示「正在运行：分镜 · 正在读剧本（0 / 2）」这类人话阶段。只跑 script+storyboard 时分母是本次步骤数。「AI 运行详情」可看最近一次「已写出 N 个镜头」。不展示大模型 token、JSON 或思考过程，思考模式保持关闭。
- 受影响文件：`director_recipe.py`、`director_agents.py`、`llm_provider.py`、`main.py`、导演台 Recipe 工作面、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。旧 Recipe 无 `pipelineRun` / `message` 时按原 9 步进度处理。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorRecipeModelTests.test_normalize_keeps_agent_stage_and_pipeline_run backend.tests.test_director.DirectorAgentPipelineTests.test_pipeline_subset_tracks_active_run_and_stage_messages`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 导演台点击分镜按剧本一次生成全部镜头

- 原因：分镜页只展示占位「主镜头」，大模型 JSON 失败时也会回退成一条创意原文，用户点击「分镜」看不到按剧本拆出的镜头列表。
- 用户可见行为：点击「分镜」Tab 或「根据剧本生成分镜」会按当前故事一次生成全部镜头（没有完整剧本时先写脚本再拆镜）。分镜覆盖整份故事，通常 8–24 镜；不再静默变成单条「主镜头」。脚本步骤失败时仍会继续拆镜，避免空列表提示「分镜还没有镜头」。上游余额不足或欠费时会提示「大模型上游余额不足」，并可查看供应商返回的错误日志。
- 受影响文件：分镜 Agent、`POST /api/director/recipes/run` 的可选 `agents`、导演台 Recipe 分镜页、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。完整 9 Agent 流水线仍可用。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAgentPipelineTests backend.tests.test_director.DirectorDualEngineApiTests.test_recipes_run_accepts_script_and_storyboard_subset`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 导演台真实声音层与工作台内成片

- 原因：前两版成片交付仍是串播 + 剪映；配音/配乐 Agent 只写文案；仓库内没有 ffmpeg。第三版提供可播放 TTS/BGM/字幕、本机 ffmpeg 合成 MP4、FCPXML/EDL，并保留剪映。
- 用户可见行为：Recipe 增加「出片」页。可上传配乐、设置字幕样式、为角色选音色并试听、按对白生成配音。顶栏与手机底栏主按钮为「导出成片」。失败镜头不进入成片。串播预览可叠字幕；成片可选烧字幕。仍可串播和导出剪映草稿。超级管理员在「管理设置 → LLM」配置独立 TTS（默认可复用大模型凭据）。不使用 Edge TTS，不改 ComfyUI 端口。
- 依赖：本机 PATH 或常见安装路径中的 `ffmpeg` 与 `ffprobe`。未安装时「导出成片」会提示不可用。Docker 镜像默认不内置 ffmpeg。
- 受影响文件：TTS 供应商、导演导出、Recipe/Agent、管理后台 LLM 页、导演台前端、测试与三份主文档。
- 兼容性：旧 Recipe 无音频字段时视为未配音；剪映导出不变。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。浏览器登录后走导演台「导出成片」。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台；新表可保留。成片文件可删 `data/staging/director-mux/`。

## 2026-08-27 导演分镜直接使用官方 h3-prompt-writing 原文

- 原因：中文摘要喂给大模型，不如官方 skill 原文带示例。
- 用户可见行为：分镜卡片仍显示中文；提交 H3 的英文镜头按官方 T2VA/Ref2VA 规范编写。生成页「优化提示词」同样走官方 skill。
- 受影响文件：官方 skill 原文目录、分镜 Agent、生成页优化、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAgentPipelineTests.test_storyboard_agent_follows_h3_official_skill`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 Recipe 分镜 Inspector、预览默认与画风渐进披露

- 原因：分镜只能看卡片，不能改导演参数；出片默认终稿成本高；34 张画风一次铺开。
- 用户可见行为：分镜为左列表 + 右检视器（手机抽屉）。可改标题、描述、对白、时长、角色、场景和机位。默认预览，可切终稿。标题旁显示保存状态。画风先给 6 张推荐。Agent 列表默认折叠。成片仍走串播和剪映。
- 受影响文件：导演台 Recipe 工作面、分镜规范化、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director`（49 项通过，含 camera 规范化、`render_pass=preview`、转换保留已有 camera）、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后 1440×900 与 390×844：返回工程库、运行导演流水线、生成这一镜、标题旁保存状态、画风 6 卡、工程卡可聚焦打开。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 Recipe 首尾帧承接、静帧分镜与 Take A/B

- 原因：Recipe 分镜改不了首尾帧，也无法先出静帧再出视频，Take 和多选重试也接不回。
- 用户可见行为：Inspector 可上传首尾帧、勾选用上一镜尾帧、生成静帧并设为首帧。分镜档位为静帧 / 预览 / 终稿。可切换、批准 Take，桌面可 A/B 对比。镜头列表可多选生成、只重试失败项或取消。成片仍走串播和剪映。
- 受影响文件：导演台 Recipe 工作面、分镜规范化与编译、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director`（56 项通过，含首尾帧规范化、上一镜尾帧/静帧承接编译为 I2V、静帧任务回写）、`pnpm --dir frontend build`。浏览器 `http://127.0.0.1:5173` 登录后 1440×900 与 390×844：分镜可切静帧/预览/终稿、勾选上一镜承接、Take 切换与批准、多选生成/取消。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 员工级人物/场景/道具资产库

- 原因：人物和场景定妆只存在单个工程里，换一个 Recipe 就要重做；不做系列分集树。
- 用户可见行为：`/assets` 的「主体」可新建/编辑/删除人物、场景、道具（图 + 提示词）。导演工程定妆区可「从库插入」和「存入资产库」。跨工程复用靠资产库，工程结构仍是 `scenes[].shots[]`。
- 受影响文件：资产库后端与导演台前端、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演分镜对用户显示中文、提交仍用英文

- 原因：按官方 H3 skill 生成后，分镜卡把英文镜头正文直接展示给用户。
- 用户可见行为：分镜、人物、场景和批量条目卡片显示中文说明。提交 H3 / GRS 仍用英文 `promptText` 或官方编译提示词。已有工程需再跑一次分镜流水线才会换成中文展示稿。
- 受影响文件：分镜 Agent、Recipe 规范化、导演台卡片、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。旧工程没有 `promptText` 时仍用 `description` 编译。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAgentPipelineTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演分镜按 MiniMax H3 官方 skill 生成

- 原因：自动分镜没用官方 H3 skill，提交提示词是中文机位标签，成片对不齐模型习惯。
- 用户可见行为：运行导演流水线后，分镜卡片显示中文说明；提交给 MiniMax H3 的提示词仍按官方 skill 编译为英文三段式或 Ref2VA 六段式。
- 受影响文件：`llm_minimax_skills.py`、`director_agents.py`、`director_compiler.py`、导演台编译器、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。旧中文分镜仍可出片。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorCompilerTests backend.tests.test_director.DirectorAgentPipelineTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 启动脚本始终打开 5173

- 原因：FastAPI 已在 7865 运行时，重复双击会打开生产静态页，开发改动看不到。
- 用户可见行为：启动脚本始终打开 `http://127.0.0.1:5173`。后端已运行时补启或复用 Vite，不再打开 7865。
- 受影响文件：`启动本地视频工作台.bat`、三份主文档。
- 兼容性：不改 API、端口号或 ComfyUI。`7865` 仍提供 API 与生产静态页。
- 验证命令：双击 `启动本地视频工作台.bat`，确认浏览器打开 5173。
- 回滚方式：恢复启动脚本与本节文档。

## 2026-08-27 导演台 Recipe/批量移动端出口与中文状态

- 原因：手机上看 Recipe/批量时桌面顶栏被藏掉，没有返回工程库和主操作；批量条目直接显示英文状态；首页工程卡不能用键盘打开。
- 用户可见行为：手机上 Recipe/批量顶部可返回工程库，右侧菜单提供创作工作台（Recipe 另有串播/剪映）。底部主按钮随当前步骤变化。镜头和批量条目显示中文状态；失败时能看到错误并「重试这一项」。导演台首页工程卡可用 Tab 聚焦后按 Enter/Space 打开。
- 受影响文件：导演台前端、`status-labels.ts`、`index.css`、批量重提交接口、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。桌面布局不变。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorDualEngineApiTests.test_batch_render_retries_only_requested_item`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 创作台与导演台 URL

- 原因：登录和管理设置已有真实地址后，生成页、导演工程和选中任务仍只在内存里，刷新会丢当前页。
- 用户可见行为：左侧「生成 / 导演台 / 资产」会改地址。打开任务后 URL 为 `/generate/image|video/<任务ID>`；导演列表 `/director`，Recipe `/director/<工程ID>`，短视频批量 `/director/batch/<工程ID>`；资产 `/assets`。刷新或浏览器进退停在同一页。未登录打开这些链接会先登录再回来。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/paths.ts`、`frontend/src/router.tsx`、`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/index.css`、`backend/app/main.py`、`backend/tests/test_ai_studio.py`、三份主文档。
- 兼容性：不改 API、端口、ComfyUI 或任务协议。旧入口 `/` 仍转到 `/generate/video`。
- 验证命令：`python -m unittest backend.tests.test_ai_studio.FrontendSpaFallbackTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-27 前端 BrowserRouter 鉴权路由

- 原因：工作台是单页应用，但登录、改密和管理 Tab 原先只在 React state 里，刷新会丢页面，也无法收藏或直达管理设置。
- 用户可见行为：`/login`、`/setup`、`/password` 为独立地址。已登录默认进入 `/generate/video`；管理设置 Tab 写入 `/admin/:tab`。未登录打开任意创作或管理链接会先登录，成功后回到原路径。员工访问 `/admin/*` 会被送回 `/generate/video`。登出硬跳 `/login`。
- 受影响文件：`frontend/package.json`、`frontend/src/main.tsx`、`frontend/src/Root.tsx`、`frontend/src/router.tsx`、`frontend/src/paths.ts`、`frontend/src/auth/AuthScreens.tsx`、`frontend/src/admin/AdminSettings.tsx`、三份主文档。
- 兼容性：不改 API、端口、ComfyUI 或任务协议。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述前端与文档文件并重新构建前端。

## 2026-08-27 关闭本机前后端端口脚本

- 原因：本机开发同时占用 Vite `5173` 和 FastAPI `7865`，关掉启动控制台后监督器子进程仍可能占着端口，再次启动会提示端口占用。
- 用户可见行为：双击 `关闭本地视频工作台.bat` 结束工作台前端和后端进程树及对应控制台窗口。不关闭 ComfyUI `8188`。若端口被无关程序占用，只提示不强制结束。
- 受影响文件：`关闭本地视频工作台.bat`、`README.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 兼容性：不改端口、API、数据库或 ComfyUI。
- 验证命令：双击关闭脚本后执行 `netstat -ano | findstr ":5173 :7865"`，确认无 LISTENING；`8188` 仍可访问。
- 回滚方式：删除该批处理并恢复本节文档。

## 2026-08-27 ComfyUI 连接地址可配置

- 原因：ComfyUI 地址原先只能靠启动环境变量，本机改端口或服务器 FRP 映射后必须改 `.env` 并重启，管理后台也看不到当前连接目标。
- 用户可见行为：超级管理员在「管理设置 → AI 供应商」可填写并测试 ComfyUI 地址，保存后立即对后续视频任务生效。默认仍为 `http://127.0.0.1:8188`；Docker 首次启动继续用 `ZLY_AI_VIDEO_STUDIO_COMFY_URL` 写入数据库。宿主机浏览器直连交付仍固定访问本机 `127.0.0.1:8188/view`。
- 受影响文件：`backend/app/comfy_provider.py`、`backend/app/comfy_service.py`、`backend/app/storage.py`、`backend/app/main.py`、`backend/app/models.py`、`frontend/src/admin/ComfyProviderSettings.tsx`、`frontend/src/Root.tsx`、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、工作台 `7865`、任务协议。已有数据库自动增加 `comfy_provider_settings` 表，首次用当前环境变量或默认 8188 播种。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_comfy_provider.py"`、`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；新表可保留。

## 2026-08-27 导演台双引擎（Recipe + 短视频批量）

- 原因：导演台不再以时间轴和 9 槽参考图为主操作面，需要对标对话导演出片，同时继续使用现有 GRS 与 MiniMax H3。
- 用户可见行为：导演台首页为导演创作 / 短视频批量。一句话可跑 9 步流水线，编辑故事和画风，在人物/场景卡生成定妆图，在分镜卡片墙提交视频。批量模式输入主题、条数、比例和时长后并行排队文生视频。旧时间轴工程打开时转为 Recipe。
- 受影响文件：`backend/app/director_agents.py`、`director_jobs.py`、`main.py`、导演台前端模块、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演台画风预览同源代理

- 原因：画风卡片无法直接加载 OpenDirector CDN，界面全部显示「无预览」。
- 用户可见行为：Recipe / 批量画风选择显示 34 张预览图。图片由工作台登录接口提供，不要求浏览器访问外网 CDN。加载失败时才显示「无预览」。
- 受影响文件：`backend/app/director_catalog/`、`backend/app/main.py`、导演台前端、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演流水线进度条实时刷新

- 原因：研究步跳过后进度停在 11%，后续 Agent 等大模型时界面不更新。
- 用户可见行为：运行导演流水线时进度条会按步前进，并显示当前正在跑的步骤（例如「正在运行：脚本」），不再在 11% 假死。
- 受影响文件：`backend/app/director_agents.py`、`backend/app/main.py`、`frontend/src/director/DirectorRecipeStudio.tsx`、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演定妆与场景卡实时进度

- 原因：人物和场景定妆提交后卡片上看不到该条任务进度。
- 用户可见行为：每张人物卡、场景卡显示独立进度条（排队 / 生成中百分比）。GRS 生图进度按约两分钟往前走，完成后出图。
- 受影响文件：导演台 Recipe 卡片、`director-submit.ts`、`backend/app/worker.py`、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_core.WorkerTests.test_grs_image_progress_moves_within_two_minutes`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演分镜卡实时进度

- 原因：分镜出片后卡片上看不到该条 H3 任务进度，「全部出片」时排队镜头也没有进度条。
- 用户可见行为：每张分镜卡显示独立进度条（排队等待出片 / 出片中百分比），跟任务列表同一条 `jobs.progress`。
- 受影响文件：导演台 Recipe 分镜卡、`director-submit.ts` 与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 GRS 定妆结果允许 *.aitohumanize.com

- 原因：GRS 把结果放到 `file8.aitohumanize.com` 等子域，下载仍只放行 file1，已生成的场景图会被拒绝。
- 用户可见行为：`*.aitohumanize.com` 的定妆结果可以下载。上游「generate image failed」显示为「上游生图失败，请重新生成」。
- 受影响文件：`backend/app/grs_client.py`、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_ai_studio.GrsClientTests.test_download_allows_grs_benchmark_cdn_only`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 导演定妆转存七牛并保存对象地址

- 原因：定妆图会上传七牛，但工程里只记下工作台下载路径，没有保存七牛图片地址。
- 用户可见行为：启用七牛云后，人物/场景定妆完成会把七牛图片地址写入工程。卡片仍用工作台登录下载预览。未启用七牛时与原来一样。
- 受影响文件：七牛存储、导演任务、Recipe 工程、导演台前端、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或 `POST /api/jobs`。已有定妆任务打开工程时会补写云端地址。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorAssetCloudTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 导演台画风目录与 Recipe payload

- 原因：导演工程只有时间轴 JSON，无法保存剧本/画风/人物/场景方案；画风名称也不能让模型随意发明。
- 用户可见行为：登录后可读取 34 条画风目录。导演工程 payload 支持 Recipe（剧本、画风、人物、场景、分镜）与旧时间轴并存；旧工程可一键转为 Recipe。画风只能从目录选择。当前导演台界面仍可打开旧时间轴工程。
- 受影响文件：`backend/app/director_catalog/`、`backend/app/director_recipe.py`、`backend/app/storage.py`、`backend/app/main.py`、`frontend/src/director/types.ts`、`frontend/src/director/director-api.ts`、测试与三份主文档。
- 兼容性：不改 ComfyUI 节点/端口或 `POST /api/jobs`。旧时间轴不自动转换。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-26 导演台项目库与 SQLite 工程文档

- 原因：导演台缺少可见的工程列表，剧本原文关闭弹窗即丢失，空工程还塞了 3 条演示分镜。
- 用户可见行为：进入导演台先看到项目库，可新建空白工程、从剧本创建、打开/复制/删除。空库可用示例创建。打开工程后可返回项目库；刷新后工程和原文仍在。空白工程只有一条空分镜。
- 受影响文件：`backend/app/storage.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/tests/test_director.py`、`frontend/src/director/*` 和三份主文档。
- 兼容性：不改 ComfyUI 节点/端口或生成任务协议。首次打开会把本机 localStorage 工程迁入 SQLite。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-26 导演台剧本文档与拆分确认

- 原因：拆分结果仍会覆盖当前时间轴，原文关闭弹窗后不易回看；移动端旧「切换工程」入口曾绑到改标题。
- 用户可见行为：项目库「从剧本创建」会新建工程并写入原文。已打开工程再拆时需确认「替换当前分镜」或「另存为新工程」，有已生成 Take 时默认另存。工作区内可打开剧本文档抽屉回看和手改，空文案也可保存。移动端返回项目库，标题不再作为切换入口。
- 受影响文件：`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/director/components/ScriptDocumentDrawer.tsx`、`frontend/src/director/components/ScriptSplitModal.tsx`、`frontend/src/director/types.ts`、`backend/tests/test_director.py` 和三份主文档。
- 兼容性：不改 ComfyUI 节点/端口或 `POST /api/jobs`。拆分仍走 `POST /api/llm/split-script`。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-26 生成页管理员切换用户查看任务

- 原因：资产页已能按用户筛选任务，生成页任务栏没有入口，管理员无法在创作区查看指定员工的生成任务。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/media/ImageStudioModule.tsx`、`frontend/src/index.css`、`backend/tests/test_ai_studio.py`、`backend/app/api_documentation.py` 和三份主文档。
- 兼容性：不改数据库、节点、端口或任务归属。`GET /api/jobs?user_id=` 仅管理员有效；员工传入会被忽略。查看他人时隐藏创作表单与继续生成操作，新建仍归属当前管理员。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-25 ComfyUI 重启后自动重提中断视频

- 原因：本机 ComfyUI 卡死或关机后，内存队列会丢失；工作台原先把进行中任务停在“已中断”，必须手动重新提交。
- 受影响文件：`backend/app/worker.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx` 和三份主文档。
- 兼容性：不改数据库、节点、端口。ComfyUI 恢复且原任务已不在队列/历史时，按原参数自动重提最多 3 次；仍可手动点“重新提交”。显存半成品无法续跑。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-13 生图/生视频统一创作工作台

- 原因：在现有视频工作台中接入 Smart-Floor-Planner 已验证的 GRS 图片协议，并统一多轮任务和本地交付体验。
- 受影响文件：`backend/app/models.py`、`workflow_registry.py`、`storage.py`、`grs_client.py`、`grs_provider.py`、`worker.py`、`main.py`，`frontend/src/App.tsx`、`Root.tsx`、图片/视频懒加载模块、供应商设置、本地资源存储、桌面交付目录、测试和部署配置。
- 兼容性：保留数据库文件名、环境变量前缀、包名、旧任务 ID、旧顶层 JobResponse 字段和旧输出 API；启动时在数据库旁创建一次 `*.pre-ai-studio-migration.bak`，旧视频原地生成首轮/首生成项，旧 Flux 图片历史仅只读。固定 `7865`/`8188`、ComfyUI 工作流节点和模型路径不变。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --filter zly-ai-video-studio-webui build`、`docker compose --env-file .env.example config`；界面在桌面端与 `390×844` 检查媒介切换、图片参数、轮次和管理页。
- 回滚方式：停止服务，恢复上一版本代码与镜像，并用数据库旁的 `zly-ai-video-studio.db.pre-ai-studio-migration.bak` 恢复数据库；不要删除员工本地目录、上传素材或 ComfyUI 输出。若仅关闭生图，可在供应商设置停用 GRS，无需数据库回滚。

生成媒体由 ComfyUI 写入其自身的 `output` 后，工作台只记录受控文件引用；浏览器或桌面客户端保存时，经工作台鉴权交付。浏览器若位于 ComfyUI 宿主机，会优先从本机 `/view` 直连读取，否则由工作台流式转发 ComfyUI `/view` 并直接写入员工电脑。完成视频不再写入服务器 `data/staging`，旧版本 `results` 文件仅作为迁移兼容。账号、会话、审计和任务元数据仍位于 `data/zly-ai-video-studio.db`，上传素材位于 `data/uploads/<user_id>`。前端源码位于 `frontend`，后端源码位于 `backend/app`。

## ZLYUN AI 桌面客户端

桌面客户端位于 `desktop`，采用 Tauri。它加载受信任的 HTTPS 工作台页面，因此仍使用同源 Cookie、CSRF 和既有 `/api`；只将“选择员工本机目录、写入交付文件、显示本地媒体”交给原生 Rust 命令处理。网页先用现有会话签发 5 分钟、绑定任务输出的下载凭证，Rust 再分块下载到本地，因此不会读取浏览器 Cookie 或把大型视频经 WebView IPC 复制到内存。目录按工作台账号分别保存在员工电脑的应用数据目录，服务端不会收到本地绝对路径。

部署前必须将下列两个配置中的占位地址 `https://zly-ai-video-studio.company.local:7865/` 同时替换为企业实际 HTTPS 域名，并确保域名证书由员工电脑信任的 CA 签发：

- `desktop/src-tauri/src/lib.rs` 的 `WORKBENCH_URL`。
- `desktop/src-tauri/capabilities/desktop-workbench.json` 的 `remote.urls`。

两处必须保持同一 HTTPS origin。不要设置通配域名、HTTP 地址或公网地址，否则桌面端无法获得本地写盘能力。工作台服务本身仍在固定 `7865` 端口运行，ComfyUI 仍只使用 `127.0.0.1:8188`。

```powershell
pnpm install
pnpm --dir desktop run build
```

安装包输出于 `desktop/src-tauri/target/release/bundle/nsis`。构建 Windows 安装包需要 Rust、Microsoft C++ Build Tools 和 WebView2 Runtime；员工端无需安装 Node.js、Rust 或 ComfyUI。

## 开发与验证

```powershell
pnpm install
pnpm --filter zly-ai-video-studio-webui build
pnpm --dir desktop run build

# 以开发方式运行 API（生产界面仍由 FastAPI 托管）
# 本机开发请用监督器，保存 backend/app 后会重启；不要在 Windows 上使用 uvicorn --reload
# 整合包 Python 使用 ._pth 隔离路径，必须直接运行脚本，不能 python -m backend.dev_reloader
<ComfyUI Python> backend/dev_reloader.py --host 0.0.0.0 --port 7865
<ComfyUI Python> -m uvicorn backend.app.main:app --host 0.0.0.0 --port 7865
<ComfyUI Python> backend/tests/test_core.py
```

可选环境变量：`ZLY_AI_VIDEO_STUDIO_DATA_DIR` 指定 SQLite、上传和旧版兼容暂存目录；`ZLY_AI_VIDEO_STUDIO_RESOURCE_PROVIDER` 选择已注册的资源 provider（当前为 `browser-stream`）；`ZLY_AI_VIDEO_STUDIO_SSL_CERTFILE` 与 `ZLY_AI_VIDEO_STUDIO_SSL_KEYFILE` 同时设置时启用 HTTPS 和安全 Cookie。未知 provider 会在启动时直接报错，不会静默回退到服务器长期存储。

## API 文档

启动工作台后，可在本机打开以下地址：

- `http://127.0.0.1:7865/api/docs`：可交互的 Swagger UI。
- `http://127.0.0.1:7865/api/redoc`：只读 ReDoc。
- `http://127.0.0.1:7865/api/openapi.json`：OpenAPI 3.1 定义，可导入 Apifox。

接口调用约定、任务状态和请求示例见 `docs/API.md`。本项目以 FastAPI 生成的 OpenAPI 为唯一接口定义来源；Apifox 仅作为可选的调试、测试与协作工具，不单独维护接口副本。

工作流参数可通过 `GET /api/modes/{mode_id}` 获取。例如 `GET /api/modes/minimax-h3-r2v` 会返回该模式对应的 multipart 字段、参考图数量与 H3 `options` 参数 schema，外部调用方无需读取前端源码。

## 架构记录

AI 或开发者进行跨模块、接口、工作流、数据库、模型路径或端口调整前，必须先阅读根目录 `AGENTS.md` 和 `docs/ARCHITECTURE.md`。重大架构变更需要同步更新架构快照和 `功能说明与扩展指南.md`。

## 2026-08-17 管理设置白色系高对比度视觉重构与本地凭据回退

- 原因：管理设置此前沿用暗黑背景与低对比度文字，导致 Ant Design 警告框和输入控件在暗色底上严重看不清；本地直接启动时未加载 `credential.key` 会出现“凭证主密钥不可用”提示。
- 受影响文件：`backend/app/config.py`、`frontend/src/Root.tsx`、`frontend/src/admin/LlmProviderSettings.tsx`、`frontend/src/admin/GrsProviderSettings.tsx`、`frontend/src/admin/QiniuStorageSettings.tsx`、`AGENTS.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：不改变接口路由与数据库结构，纯视觉与配置加载优化。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复对应前端与配置文件后重新构建。

## 2026-08-17 LLM 大模型服务与提示词智能优化

- 原因：工作台创作者需要将简短粗糙的视频/图像想法快速扩写为具有电影级运镜、动态细节与艺术质感的高质量提示词；原生支持 ModelScope（魔搭社区）每日免费额度模型及通用 OpenAI 兼容协议。
- 受影响文件：`backend/app/llm_client.py`、`backend/app/llm_provider.py`、`backend/app/models.py`、`backend/app/storage.py`、`backend/app/main.py`、`backend/tests/test_llm.py`、`frontend/src/admin/LlmProviderSettings.tsx`、`frontend/src/Root.tsx`、`frontend/src/App.tsx`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：新增独立的 Provider 表和 API 接口，完全向下兼容已有的任务数据、ComfyUI 实例与 GRS 服务；未启用 LLM 时工作台提示词输入保持原有手动编辑行为。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码与文档文件，重新执行前端 build 即可；数据库表无破坏性改动。


## 2026-08-11 首次目录配置强制引导


- 原因：未配置本地目录时，用户可以进入工作台并创建任务，导致生成资源无法按既定交付流程保存到员工电脑。
- 受影响文件：`frontend/src/App.tsx`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：目录句柄仍按账号仅保存在浏览器 IndexedDB；API、SQLite、任务队列、ComfyUI 节点和固定 `7865`/`8188` 端口均不变。已授权目录的用户直接进入工作台。
- 验证命令：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在 `http://127.0.0.1:7865` 的桌面和 390px 视口检查首次改密后的目录授权、拒绝授权和已授权回访。
- 回滚方式：恢复上述文件并重新构建前端；不涉及数据库迁移或媒体清理。

## 2026-08-06 API 文档基线

- 原因：将现有 FastAPI 后端接口提供为可交互、可导入且随代码更新的统一文档，避免手工接口说明过期。
- 受影响文件：`backend/app/main.py`、`backend/app/models.py`、`backend/tests/test_core.py`、`docs/API.md`、`docs/ARCHITECTURE.md` 和本文档。
- 兼容性：原有业务接口、端口和响应字段保持不变；新增文档端点为 `/api/docs`、`/api/redoc` 和 `/api/openapi.json`。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/openapi.json`。
- 回滚方式：恢复上述受影响文件；新增文档端点无需迁移数据库或清理生成媒体。

## 2026-08-06 局域网访问

- 原因：允许同一可信局域网内的设备访问工作台，便于多设备使用本机生成能力。
- 受影响文件：`启动本地视频工作台.bat`、`backend/app/main.py`、`backend/tests/test_core.py`、`docs/API.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：本机 `http://127.0.0.1:7865` 继续可用；新增 `http://<本机IPv4>:7865` 访问方式。ComfyUI 继续固定且仅由本机工作台访问 `127.0.0.1:8188`。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-WebRequest http://<本机IPv4>:7865/api/health`。
- 回滚方式：将启动脚本和 `backend/app/main.py` 的 Uvicorn `host` 恢复为 `127.0.0.1`，并删除专用防火墙规则（如已创建）。

## 2026-08-11 启动脚本清理旧版 Gradio 进程

- 原因：`启动本地视频工作台.bat` 在 7865 端口已被占用时会直接打开现有服务，可能误进入仍在运行的旧版 Gradio 界面。
- 受影响文件：`启动本地视频工作台.bat`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：启动脚本现在仅会自动结束命令行中包含 `local_video_studio.py` 的旧版 Gradio 进程，随后启动 React + FastAPI 工作台；`local_video_studio.py` 仅保留工作流辅助函数且不能再单独启动 Gradio；其他占用 7865 的程序不会被结束，并会提示用户自行关闭。
- 验证命令：`& "<ComfyUI Python>" backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，然后双击 `启动本地视频工作台.bat` 并访问 `http://127.0.0.1:7865`。
- 回滚方式：恢复启动脚本的端口占用分支，以及本节和对应架构、功能说明记录；不涉及数据库、模型或 ComfyUI 变更。

## 2026-08-06 工作流参数接口

- 原因：`/api/modes` 原先只给出能力标记，外部调用方无法仅凭接口得知每种工作流的提交字段及 H3 参数范围。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/tests/test_core.py`、`docs/API.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：现有 `/api/modes` 字段和 `POST /api/jobs` 协议不变；每个模式新增 `parameters`，并新增 `GET /api/modes/{mode_id}` 详情接口。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/modes/minimax-h3-r2v`。
- 回滚方式：恢复上述文件；无数据库迁移、模型或工作流文件改动。
## 2026-08-05 任务进度同步

- 原因：生成任务此前只返回阶段文字，工作台无法显示 ComfyUI 的实时执行进度。
- 受影响文件：`backend/app/comfy_service.py`、`backend/app/storage.py`、`backend/app/worker.py`、`backend/app/models.py`、`frontend/src/App.tsx`。
- 兼容性：SQLite 启动时自动补充 `progress` 列；仍使用固定 `http://127.0.0.1:8188`，旧任务默认进度为 0。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复上述文件及本节文档，SQLite 新增列可保留，不影响旧字段读取。

## 2026-08-07 H3 自定义比例与任务回显

- 原因：外部 API 调用需要提交任意合法画面比例，并在工作台查看参考图和实际 H3 参数。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`docs/API.md`、`docs/ARCHITECTURE.md` 和本文档。
- 兼容性：H3 `options.aspect_ratio` 从固定枚举扩展为任意有限正数的 `宽:高` 字符串；既有比例仍可用。任务响应新增 `references` 预览 URL，不暴露本地文件路径。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/modes/minimax-h3-r2v`。
- 回滚方式：恢复上述文件；SQLite、模型、ComfyUI 节点和已有任务记录无需迁移或清理。

## 2026-08-11 企业账号与浏览器本地资源交付

- 原因：工作台从可信局域网匿名工具升级为员工账号使用场景，并避免生成资源长期占用生成工作站磁盘。
- 受影响文件：`backend/app/auth.py`、`backend/app/resource_storage.py`、`backend/app/config.py`、`backend/app/storage.py`、`backend/app/models.py`、`backend/app/main.py`、`backend/app/comfy_service.py`、`frontend/src/api.ts`、`frontend/src/local-resource-store.ts`、`frontend/src/Root.tsx`、`frontend/src/App.tsx`、`frontend/src/main.tsx`、`启动本地视频工作台.bat`、测试与文档。
- 兼容性：固定工作台端口 `7865`、ComfyUI `127.0.0.1:8188`、工作流节点和任务队列保持不变；旧任务在首次初始化时归首位超级管理员，旧 `results` 输出可按相同交付流程迁移。交付回执只删除固定 ComfyUI `output` 根目录内与任务记录精确匹配的文件，拒绝路径越界。File System Access API 需要 Chrome/Edge 与 HTTPS 或 `127.0.0.1`，不支持时降级为普通下载。资源 provider 当前为 `browser-local`，接口保留七牛云 provider 扩展点。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在桌面及 390px 视口验证初始化、登录、账号管理和目录状态。
- 回滚方式：恢复上述代码与文档并改回旧前端构建；SQLite 新增表和 `jobs.owner_user_id` 可保留。尚未确认交付的 `data/staging` 文件可迁回 `results`，已经由浏览器确认并清理的资源只存在员工授权目录，回滚不会自动上传或恢复这些本地文件。

## 2026-08-07 任务请求参数完整回显

- 原因：外部 API 与工作台提交的任务需要在详情中核对所有实际传入参数，而非只显示个别 H3 选项。
- 受影响文件：`backend/app/storage.py`、`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`docs/API.md`、`docs/ARCHITECTURE.md` 和本文件。
- 兼容性：任务响应新增 `request_parameters`；SQLite 启动时自动增加提交选项记录列，既有任务仍可读取并按现有有效参数回显。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`Invoke-RestMethod http://127.0.0.1:7865/api/jobs/<job_id>`。
- 回滚方式：恢复上述受影响文件；新增 SQLite 列可保留，不会影响旧版本读取既有任务。

## 2026-08-07 AI 工作台控件与参考图预览

- 原因：对齐 `Smart-Floor-Planner` 的 AI 工作台下拉交互和素材确认体验，提升多工作流选择及参考图核对效率。
- 受影响文件：`frontend/src/App.tsx`、`README.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 兼容性：不改变 `/api`、任务参数、SQLite、ComfyUI 或工作流协议；原生选择框替换为可访问的前端菜单，参考图缩略图可点击放大。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在 `http://127.0.0.1:7865` 检查桌面与 390px 移动端。
- 回滚方式：恢复上述受影响文件；无需数据库迁移或清理任务媒体。

## 2026-08-07 ComfyUI 任务重启恢复

- 原因：工作台重启不应将仍在固定 ComfyUI 队列中执行或等待的任务误标记为中断。
- 受影响文件：`backend/app/storage.py`、`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 兼容性：任务记录新增 ComfyUI `prompt_id`、`client_id` 和阶段信息，SQLite 启动时自动补列；既有 API 和 `http://127.0.0.1:8188` 固定实例保持不变。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`；重启工作台后检查 `/api/jobs` 中正在运行的任务仍可继续进度同步和完成下载。
- 回滚方式：恢复上述文件；新增 SQLite 列可保留，不影响旧版本读取任务。

## 2026-08-11 MiniMax H3 T8 工作流接入

- 原因：将固定 ComfyUI 的 `user/default/workflows/MiniMax H3` 下“MiniMax H3全能参考工作流”和“双时钟采样8步效果更好工作流”接入 ZLY AI Video Studio，并让工作台可提交、保存和回显源工作流的可调参数。
- 受影响文件：`backend/app/models.py`、`backend/app/workflow_registry.py`、`backend/app/minimax_h3_t8_workflow.py`、`backend/app/main.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx`、`docs/API.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 兼容性：保留原有 H3 三个模式及其节点映射；新增 `minimax-h3-t8-all-reference` 和 `minimax-h3-t8-dual-clock`。仍只连接 `http://127.0.0.1:8188`，不复制模型、不修改源工作流文件，不迁移 SQLite。输出前缀、保存开关和 graph 连线由后端固定，以保证任务结果可下载。
- 验证命令：`<ComfyUI Python> backend/tests/test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并以 `http://127.0.0.1:8188/object_info` 校验 T8 graph 节点输入；在 `http://127.0.0.1:7865` 检查桌面与 390px 参数控件。
- 回滚方式：删除两个新模式与 `minimax_h3_t8_workflow.py`，恢复注册表、服务分发、前端动态参数控件、测试和本节文档；既有任务、媒体、账号和数据库结构无需处理。

## 2026-08-12 画质预设与随机种子产品化

- 用户可见行为：画质改为 `1K`、`2K`、`4K` 三档，后端负责映射到实际 MP；随机种子不再出现在创建表单，每次任务由后端自动生成，并在任务详情的运行参数中保留。
- 兼容性：现有 API、SQLite、ComfyUI graph、节点 ID 和固定端口不变；历史 MP 值按最近画质档位回显。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复注册表、API、前端、测试和文档文件；无需迁移数据库或媒体。

## 2026-08-11 工作流参数分层

- 原因：ComfyUI 工作流包含大量节点、采样、模型、显存和编码参数，直接展示会增加普通创作用户的理解成本。
- 受影响文件：`AGENTS.md`、`backend/app/workflow_registry.py`、`backend/app/models.py`、`backend/app/main.py`、`frontend/src/App.tsx`、`backend/tests/test_core.py`、`docs/API.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 用户可见行为：创建页默认只显示画面比例和时长；画质与随机种子进入“更多设置”；任务类型、采样器、模型、VAE、LoRA、显存及编码参数由系统托管。任务详情先显示创作参数，完整有效参数可在“运行参数”中展开核对。
- 兼容性：`POST /api/jobs` 的 `options` 字段和所有已有参数继续有效；`GET /api/modes` schema 新增/扩展 `ui_group=primary|advanced|internal` 语义，`request_parameters[]` 新增 `visibility`。无数据库迁移，不修改 ComfyUI graph 或节点 ID。
- 验证命令：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在 `http://127.0.0.1:7865` 检查桌面与 390px 创建页、更多设置和运行参数折叠区。
- 回滚方式：恢复上述注册表、API、前端、测试和文档文件；SQLite、已有任务、模型和 ComfyUI 工作流无需处理。

## 2026-08-11 密码可见性与重置解锁

- 原因：降低员工输入初始密码和管理员重置密码时的录入错误，并避免密码已重置后仍被旧的登录失败冷却阻挡。
- 受影响文件：`frontend/src/Root.tsx`、`backend/app/main.py`、`backend/tests/test_core.py`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md` 和本文档。
- 用户可见行为：所有密码输入框均可通过眼睛图标切换显示或隐藏；管理员成功重置某个账号密码后，该账号在所有来源地址上的 15 分钟登录失败限制立即解除。
- 兼容性：账号、会话、SQLite 结构、接口请求和响应格式均不变；未重置账号的登录限流行为保持不变。
- 验证命令：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在桌面与 390px 视口验证密码切换按钮。
- 回滚方式：恢复上述前端、后端、测试和文档文件；不需要迁移数据库或处理现有账号。

## 2026-08-11 ZLYUN AI Tauri 桌面客户端

- 原因：局域网 HTTP 页面不满足浏览器 File System Access API 的安全上下文要求；企业交付还需要可控的本地目录、文件写入和后续桌面能力扩展点。
- 受影响文件：`desktop/`、`frontend/src/local-resource-store.ts`、`pnpm-workspace.yaml`、`frontend/package.json`、`.gitignore`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：浏览器端继续使用现有 IndexedDB + File System Access API；桌面端通过同源 HTTPS 页面继续使用现有账号、Cookie、CSRF、任务 API、SQLite、固定 `7865` 端口和 ComfyUI `127.0.0.1:8188`，不变更工作流节点或任务队列。
- 验证命令：`pnpm --filter zly-ai-video-studio-webui build`、`pnpm --dir desktop run build`，并在受信任 HTTPS 域名下检查首次选目录、自动交付、历史本地媒体预览与回执后的服务器暂存清理。
- 回滚方式：停止分发桌面安装包并恢复 `frontend/src/local-resource-store.ts` 的浏览器实现；不涉及数据库迁移、模型或 ComfyUI 修改。

## 2026-08-11 MiniMax H3 参数组件化

- 原因：标准 H3 三种视频工作流的画面比例和时长曾使用原生文本/数字输入，无法与工作台选择控件保持一致。
- 受影响文件：`backend/app/workflow_registry.py`、`frontend/src/App.tsx`、`frontend/src/main.tsx`、`frontend/src/index.css`、`frontend/package.json` 与测试、架构文档。
- 用户可见行为：画面比例显示为注册表下发的预设选择菜单；时长、画质和其他可见数值参数显示为加减步进器；布尔参数显示为开关。
- 兼容性：`POST /api/jobs` 的 `options` 格式及 H3 自定义合法比例 API 校验保持不变；`GET /api/modes` 的参数 schema 仅新增 `ui_control` 和 `ui_options` 展示元数据，无需数据库迁移。
- 验证：`<ComfyUI Python> -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在 `http://127.0.0.1:7865` 的桌面及 390px 视口检查选择和步进交互。
- 回滚：恢复上述注册表、Ant Design 前端接入和测试文件并重新构建前端；现有任务、SQLite 数据、ComfyUI 节点和模型不受影响。

## 2026-08-11 运行环境变量品牌迁移

Docker、服务器和本地启动统一使用 `ZLY_AI_VIDEO_STUDIO_*` 环境变量。现有部署请将 `.env`、系统服务和 CI/CD 中同用途的旧变量改为新变量名后再更新镜像；端口、API、SQLite 数据和 ComfyUI 地址不变。


## 2026-08-11 品牌与运行数据迁移

产品自有的数据库、Cookie、任务标识、输出前缀、浏览器本地存储、桌面端交付目录和包名均迁移为 `ZLY AI Video Studio`。应用启动时会自动将旧数据库及其 WAL/SHM 文件迁移为 `zly-ai-video-studio.db`；所有用户需重新登录，浏览器本地资源记录会自动导入到新 IndexedDB。

## 2026-08-11 browser-stream 成片交付

已完成的 H3 视频不再下载到工作台服务器的 `data/staging`。后端只保存 ComfyUI 输出引用，员工浏览器或桌面客户端使用受保护的工作台下载 URL 时，后端才从 `ZLY_AI_VIDEO_STUDIO_COMFY_URL/view` 流式读取并直接写入员工选定的本机目录。服务器可以通过 FRP 的 `127.0.0.1:18188` 访问远端 ComfyUI，`compose.yaml` 因此不再要求 `COMFY_OUTPUT_DIR` 挂载。

- 原因：远端 ComfyUI 部署时避免已完成视频占用工作台服务器磁盘，同时不向员工公开 ComfyUI API。
- 受影响文件：`backend/app/resource_storage.py`、`backend/app/comfy_service.py`、`backend/app/main.py`、`backend/app/config.py`、`compose.yaml`、`.env.example`、`Dockerfile`、测试与三份主文档。
- 兼容性：工作台 API 路径、SQLite schema、H3 graph、账号权限与本地目录交付流程不变。旧 `browser-local` provider 保留；旧暂存文件继续按原路径读取。远端 ComfyUI `output` 不会由该模式自动删除，应在 ComfyUI 电脑上配置保留期或容量清理。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`、`docker compose --env-file .env.example config`、`docker compose build`。
- 回滚方式：将 `ZLY_AI_VIDEO_STUDIO_RESOURCE_PROVIDER` 改回 `browser-local`，恢复含 `COMFY_OUTPUT_DIR` 挂载的上一版 Compose 和镜像后重启；不要删除命名卷或上传素材。

## 2026-08-12 Docker 配置模块启动修复

- 原因：Docker 容器中的工作台根目录为 `/app`，原本以固定祖先索引推导本地 ComfyUI 默认目录会在导入 FastAPI 应用时触发 `IndexError`，使 Uvicorn 在监听 `127.0.0.1:18189` 前退出并不断重启。
- 受影响文件：`backend/app/config.py`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：默认本地 ComfyUI 目录改为工作台目录父级下的既有整合包；Docker 仍只经 `ZLY_AI_VIDEO_STUDIO_COMFY_URL=http://127.0.0.1:18188` 访问唯一 ComfyUI。端口、API、数据库、任务队列和工作流节点均不变。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`docker compose build`、`docker compose up -d`、`curl http://127.0.0.1:18189/api/health`。
- 回滚方式：恢复上述配置、测试和文档文件后重新构建并启动上一镜像；不要执行 `docker compose down -v`，以保留命名卷中的 SQLite 与上传素材。

## 2026-08-12 tar 镜像一键部署脚本

- 原因：离线 tar 更新需要重复执行镜像加载、容器重建、状态检查和健康检查，手工执行容易遗漏 `--no-build` 或错误清理数据卷。
- 受影响文件：`deploy-server-image.sh`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 兼容性：脚本仅更新 `zly-ai-video-studio` 容器镜像；端口、API、ComfyUI 地址、任务队列和命名数据卷均不变。
- 验证命令：在 Linux 服务器项目目录执行 `bash deploy-server-image.sh`，确认脚本输出健康接口响应。
- 回滚方式：将上一版 tar 作为参数再次执行该脚本；不要执行 `docker compose down -v`。

## 2026-08-12 参数栏视觉化设置

- 原因：创作参数需要更快地完成比例、画质与时长设置，避免在多个下拉菜单和步进器间来回切换。
- 受影响文件：`backend/app/workflow_registry.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 用户可见行为：比例入口以画幅小图标展示；点开后可在同一弹层切换比例和分辨率。时长入口提供带刻度的滑杆，也可直接输入数值。
- 兼容性：`POST /api/jobs` 的 options 值、工作流节点、端口、SQLite 与既有任务保持不变；`GET /api/modes` 仅将 `visual-settings`、`duration-slider` 和 `ui_companion` 作为可忽略的展示元数据下发。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`。
- 回滚方式：恢复本次注册表、前端、测试和三份文档；无需迁移或清理任务、媒体或数据库。

## 2026-08-13 图片参数弹窗选择

- 原因：图片工作台的画面比例和分辨率此前使用普通下拉框，与视频工作台的高频参数交互不一致。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md` 和 `功能说明与扩展指南.md`。
- 用户可见行为：GPT Image 2 和 GPT Image 2 VIP 的比例入口改为画幅图标按钮；点击后在同一弹层选择画面比例和分辨率。VIP 仍可在“更多设置”中填写自定义尺寸。
- 兼容性：`POST /api/jobs` 的 options 值、GRS 请求映射、SQLite、端口和既有任务不变；`GET /api/modes` 仅新增可忽略的 `visual-settings`、`ui_companion` 与 `ui_options` 展示元数据。
- 验证命令：`python -m unittest discover -s backend/tests -p test_core.py`、`pnpm --filter zly-ai-video-studio-webui build`，并在桌面和 `390×844` 视口检查弹窗选择。
- 回滚方式：恢复上述注册表、测试和文档；无需迁移或清理任务、媒体或数据库。

## 2026-08-14 七牛云媒体存储

- 原因：为图片和视频结果提供可持久化的云端媒体存储，避免成片仅依赖浏览器交付或 ComfyUI 临时输出。
- 使用方式：超级管理员在“管理设置 → 媒体存储”填写七牛云 AK、SK、Bucket、区域、HTTPS 访问域名和对象前缀，测试成功后打开“启用七牛云”并保存。
- 本地启动：`启动本地视频工作台.bat` 会检测并使用内置 Python 安装 `qiniu==7.16.0`；Docker 构建自动从 `backend/requirements.txt` 安装。
- 行为：启用后，新生成的 GRS 图片和 ComfyUI 视频会先上传至七牛云；下载接口返回短期私有签名链接，员工本地交付确认只清理 ComfyUI 临时输出，不删除云端媒体。
- 兼容性：未启用时继续使用 `ZLY_AI_VIDEO_STUDIO_RESOURCE_PROVIDER` 的既有交付方式；已有本地任务与文件不迁移。
- 验证：`python -m unittest discover -s backend/tests -v`、`pnpm --dir frontend build`。
- 回滚：在“媒体存储”关闭七牛云后保存配置，并恢复本次后端、前端、依赖与文档变更；已上传对象需在七牛云控制台按保留策略处理。

## 2026-08-14 GRS 上游余额创作页展示

- 原因：员工需要在 AI 生图前直接看到管理员最近查询到的 GRS 上游余额。
- 使用方式：在“图片生成”模式的创作区顶部查看“余额”。生成期间每 5 秒刷新，空闲时每 15 秒刷新；后端以 10 秒短缓存合并上游查询，每张图片成功后也会触发一次异步刷新。超级管理员仍可在“管理设置 → AI 供应商”手动查询。
- 兼容性：任务、SQLite、GRS 生成协议、ComfyUI 节点、模型路径和固定端口不变；旧客户端不调用新增的余额快照接口。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`，并在桌面和 `390×844` 视口进入“图片生成”检查余额状态。
- 回滚：恢复本次后端、前端和文档文件并重启工作台；无需清理 SQLite 中已有的余额快照。

### 即梦式任务会话管理（2026-08-14）

任务栏现在以单行标题配合 32px 封面展示任务，悬浮后可置顶、重命名或删除已结束任务；任务按置顶优先排列。创作区的“图片生成/视频生成”改为与即梦一致的下拉切换。既有任务会自动补齐置顶字段，工作台仍使用 `http://127.0.0.1:7865`。

### 即梦式右侧创作工作台（2026-08-14）

右侧创作区已整理为白色圆角创作卡：参考图槽位、提示词输入和底部参数工具栏分层展示，工具栏控件统一为 36px，并继续支持图片/视频下拉切换、动态工作流参数和本地视频生成。

### 即梦式控件细节修复（2026-08-14）

修复创作区下拉框双层边框、图片模型名称截断和比例设置弹窗对比度问题；工作流菜单可完整显示模型名称，比例选中态改为清晰的蓝色边框与浅蓝背景。

### 即梦式媒体与参数细节修复（2026-08-14）

媒体下拉增加图片/视频图标；视频模型菜单加宽并取消横向滚动；时长按钮保持单行；比例弹层的 1K/2K/4K 文字在默认、hover 和选中状态均保持可读。
### 白色主题文字可读性修复（2026-08-14）

视频模型选择器现以 248px 桌面宽度完整显示默认模型名称；时长弹层的刻度与数值输入在白色背景下使用清晰文本色。此调整仅影响前端显示，不改变任务接口、固定工作台地址 `http://127.0.0.1:7865` 或 ComfyUI `http://127.0.0.1:8188`。
### 创作工具栏窄宽度修复（2026-08-14）

创作工具栏控件不再因 flex 收缩而导致模型选择器消失或文字被截断；窗口空间不足时会自动换行，图片和视频生成流程保持不变。
### 媒体类型下拉宽度修复（2026-08-14）

图片生成/视频生成下拉菜单与触发器保持同宽，窄窗口下不再产生压缩错觉；视频模型名称保持完整显示。

### 图片联合参数选择器（2026-08-15）

图片生成的“画面比例、分辨率、生成数量”由工作流注册表通过 `ui_companions` 声明为同一组，在一个参数弹层内选择；工具栏只保留一个摘要触发器。上传参考图入口在浅色主题中使用蓝色图标和浅蓝底，避免白色图标或文字落在白色背景上。该变更不修改 `POST /api/jobs` 的 options、任务数据、端口或 ComfyUI 配置；验证命令为 `pnpm --dir frontend build` 和 `<ComfyUI Python> -m unittest backend.tests.test_ai_studio`，回滚时恢复注册表、前端控件和样式文件即可。

### 即梦式生成与资产任务栏（2026-08-17）

工作台左侧现在只保留“生成”和“资产”两个菜单。生成页的任务栏按“新对话、当前创作、最近”分组，并支持收起；资产页汇总历史生成的图片和视频，点击视频资产可回到对应任务。该调整仅影响前端导航与展示，不改变任务接口、SQLite、ComfyUI 或固定工作台地址。

### 即梦式资产媒体库（2026-08-17）

资产页现使用即梦式生成历史布局：可按图片、视频、音频或文档筛选，按日期分组浏览 16:9 媒体缩略图，视频带时长角标；“主体”和“画布”保留独立入口。资产视图隐藏会话任务栏，但保留左侧全局“生成/资产”导航。

## 2026-08-21 MiniMax H3 本地输出尺寸预设

- 原因：原先本地 H3 的 `1K/2K/4K` 文案与实际画布像素面积不一致，例如“2K”实际仅为 `0.3 MP`，造成下载尺寸预期错误。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/tests/test_core.py`、`README.md`、`docs/ARCHITECTURE.md`、`功能说明与扩展指南.md`。
- 用户可见行为：分辨率弹层直接显示实际输出尺寸，画面比例切换后尺寸会即时重算。标准 H3 依照 MiniMax `ResolutionSelector` 提供最高 `2.0 MP` 的档位，16:9 实际对齐为 `1920×1088`；T8 仍按其节点硬限制最高 `.98 MP`。MP 仅作为次要说明。
- 兼容性：历史明确传入的 `1K/2K/4K` 请求仍按原有 `0.2/0.3/0.5 MP` 执行；已保存任务的实际 MP 参数不改变。`GET /api/modes` 按每个工作流的注册表下发可用尺寸档位，标准 H3 与 T8 的上限互不混用。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`；在桌面与 `390×844` 视口切换三种 H3 工作流，确认尺寸随比例更新且不超过工作流上限。
- 回滚方式：恢复上述注册表、测试和三份文档；无需数据库迁移、清理任务或媒体。

## 2026-08-24 七牛云上传可靠性修复

启用七牛云时，超过 8 MiB 的图片/视频使用 v2 分片上传（内置 `qiniu==7.16.0` 兼容 `put_stream(..., version="v2")`）；遇到 `RemoteDisconnected`、连接重置、超时或 408/429/5xx 等可恢复错误，后端会对同一对象键最多重试 3 次后再报告失败。该修复避免 ComfyUI 已生成成功却因一次瞬时云端断连而显示“生成失败”，不改变七牛云签名链接、本地交付或未启用七牛云时的行为。

- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚：恢复本次 `qiniu_storage.py`、测试和文档变更并重启工作台；无需删除已上传对象。

## 2026-08-25 MiniMax H3 Web AI 导演台（Director Studio）系统

- 原因：为用户提供对标开源社区成熟 Web 导演台（`NickPittas/DirectorsConsole`、`seesee75-Director`、`oh-my-minimaxh3-director` 与 `AIMixer`）的一站式影视级分镜编排、运镜调度、角色一致性绑定、镜头连续性接龙与成片串播系统。
- 用户可见行为：
  - 左侧全局导航新增 **【🎬 导演台】** 入口；
  - 顶部提供导演分镜项目管理、画面比例选择、全局角色资产栏（`<Picture 1>`~`<Picture 9>`）、AI 剧本一键拆解分镜、成片连播预览与批量生成；
  - 故事板以卡片流呈现各分镜头，可调整景别、运镜、视角与影调，支持首尾帧上传、接龙续拍、单镜头重拍与顺序微调；
  - 提供 Master Sequence Player 成片连续串播播放器，支持全部分镜视频无缝连播与一键批量保存到员工本地授权目录。
- 兼容性：完全向下兼容原有任务、数据库结构、ComfyUI 实例、节点 ID 或工作流协议；导演工程在前端持久化管理并与后端任务引擎无缝同步。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码和文档后重新构建前端；无需数据库迁移。

## 2026-08-25 云端视频下载不再返回 HTTP 307

启用七牛云后，下载接口改为由工作台同源代理云端字节流（HTTP 200），不再 307 跳转到七牛云签名地址。任务 JSON 中的 `download_url` 仍是稳定的 `/api/jobs/.../download`，浏览器播放与 Toonflow 等不跟随重定向的下载客户端都能直接拿到文件。

- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚：恢复本次 `backend/app/main.py`、测试和文档变更并重启工作台；无需删除已上传对象。

## 2026-08-25 GRS 生图模型可配置目录

- 原因：创作页原先写死 GPT Image 2 / VIP 两个工作流，无法使用 GRS 文档中的 Nano Banana 等模型。
- 用户可见行为：超级管理员在「AI 供应商 → GRS」维护生图模型目录（启用、显示名、默认、添加自定义 ID、同步内置目录）。启用的模型各自出现在创作页「选择工作流」；默认仍只打开 GPT Image 2 与 VIP。
- 兼容性：历史任务 `grs-gpt-image-2` / `grs-gpt-image-2-vip` 继续可回显和重试；提交仍走 `POST /v1/api/generate`；SQLite 新增 `grs_image_models` 表。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚：恢复本次代码与文档并重启工作台；已写入的目录表可保留，旧版本会忽略该表。

## 2026-08-25 GRS 生图接回已出图结果与审核说明

- 原因：参考图含真人时上游更容易返回 `violation` 或 HTTP 400；少数任务实际已出图并写入员工目录，但工作台仍标失败且不展示结果。
- 用户可见行为：已落盘的图片仍可在任务详情中查看和保存。整轮只要有成功输出就不会被标成失败（改为部分完成）。审核失败会显示「内容未通过审核（可能含真人等受限内容）」及上游原文。
- 兼容性：不改 SQLite schema、ComfyUI 端口/节点或创建任务接口。下载接口允许带输出的失败/部分完成任务。
- 验证：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚：恢复本次代码与文档并重启工作台。

## 2026-08-25 导演台按现有 H3 工作流正确提交

- 原因：导演台生成路径此前未走编译结果，参考图编号与上传顺序不一致，批量任务没有镜头连续性。
- 用户可见行为：
  - 底部检视器显示即将提交的提示词；≤15s 可整段提交，超过则须逐镜接龙。
  - 批量渲染会等上一镜成功、抽取尾帧作为下一镜首帧后再提交。
  - 主体 Analyze 仅在大模型支持视觉时根据参考图提取外貌，否则按钮禁用并说明原因。
  - 成片可直接导出剪映草稿。刷新后仍保留 `data:` 参考图预览；`File` 对象不会写入 localStorage。
- 兼容性：不改 ComfyUI 实例、节点 ID、任务协议或数据库；仍使用 MiniMax H3 T2V/I2V/R2V。
- 验证命令：`python -m unittest discover -s backend/tests -p "test*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述代码和文档后重新构建前端；无需数据库迁移。

## 2026-08-25 Ollama 本地连接测试等待模型加载

- 原因：本机 Ollama 已启动时，管理后台「测试连接」仍可能因 15 秒超时失败。7B 模型第一次装入显存经常超过这个时间。
- 用户可见行为：本地 Ollama / LM Studio 测试最多等待 90 秒；模型名填错时会列出 `ollama list` 里已有的名称。Ollama 不需要云端 Token。
- 兼容性：云端大模型测试仍为 15 秒；不改数据库、端口或 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复对应文件并重启工作台。

## 2026-08-25 魔搭 LLM 按魔粒计费说明

- 原因：管理后台把魔搭标成「免费额度」，但魔搭 API-Inference 已改为扣除账户魔粒；DeepSeek-V4 默认开思考会额外消耗。
- 用户可见行为：预设改为「按魔粒计费」并给出警告。不想扣魔粒请改用硅基流动免费 7B 或本机 Ollama。工作台对 DeepSeek-V4 请求显式关闭思考，降低单次消耗，但不能阻止扣费。
- 兼容性：不改数据库、端口或 ComfyUI；已保存的魔搭 Token 与模型名不变。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复对应文件并重启工作台。

## 2026-08-25 LLM 后台拉取官方免费模型

- 原因：管理后台模型名只靠几个推荐标签，无法从硅基流动官方目录选择当前免费模型。
- 用户可见行为：超级管理员可「拉取官方列表」，硅基流动会拉取全部可调用模型，再对照模型广场里价格为 0 / Free 的条目，结果以下拉框选择。
- 兼容性：不改数据库、端口或 ComfyUI；已保存的模型名仍可手动输入。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复对应文件并重启工作台。

## 2026-08-25 硅基流动免费模型对照模型广场价格

- 原因：官方 `/v1/models` 没有 Free 字段，按文字筛选会提示目录里没有免费模型。
- 用户可见行为：拉取官方列表时会对照硅基流动模型广场的价格 0 / Free 标记，例如 `Qwen/Qwen2.5-7B-Instruct`。
- 兼容性：不改数据库、端口或 ComfyUI。
- 验证命令：`python -m unittest backend.tests.test_llm`、`pnpm --dir frontend build`。
- 回滚方式：恢复对应文件并重启工作台。

## 2026-08-25 导演台融合版界面冻结与实现

- 原因：将导演台从分散的故事板、时间轴和检视器入口统一为可连续工作的导演工作台，并补齐移动端入口与单手操作布局。
- 用户可见行为：桌面端提供镜头序列、中央预览/故事板切换、右侧镜头检视器和底部时间轴；移动端提供工作区导航、横向镜头条、连续性摘要和底部固定“生成本镜”操作。AI 拆分剧本、续接定格、成片预览和剪映导出继续复用既有能力。
- 受影响文件：`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/director/components/ScriptSplitModal.tsx`、`output/superdesign/director-ui-audit.md`。
- 兼容性：不改 SQLite、API、ComfyUI `127.0.0.1:8188`、工作流节点 ID、`<Picture n>` 编译协议或任务队列；现有导演工程仍由浏览器 localStorage 保存。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`；已用 1440×900 与 390×844 视口完成浏览器回归。
- 回滚方式：恢复上述前端文件并重新构建；无需数据库迁移或清理媒体。

## 2026-08-26 工作台手动停止生成

- 原因：ComfyUI 里删除执行中任务会被工作台当成丢失并自动重提；用户需要在工作台主动停止，且停止后不再自动重跑。
- 用户可见行为：排队中、生成中或已中断的任务可点「停止生成」。视频任务向固定 ComfyUI `127.0.0.1:8188` 中断正在运行的对应 `prompt_id` 或从队列删除排队项，状态变为「已停止」，不会自动重新提交。图片任务停止本地等待，云端可能仍计费。之后可手动「重新提交」或删除记录。
- 受影响文件：`backend/app/models.py`、`backend/app/storage.py`、`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/app/main.py`、`backend/app/api_documentation.py`、`backend/tests/test_core.py`、`backend/tests/test_ai_studio.py`、`frontend/src/App.tsx`、`frontend/src/index.css`、`frontend/src/director/*` 和三份主文档。
- 兼容性：SQLite 为 `generation_items` 增加 `cancel_requested` 列，旧库启动时自动添加；不改 ComfyUI 节点、端口或创建任务接口。`interrupted` 仍表示可自动恢复的中断。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台；新增列可保留，不影响旧逻辑。

## 2026-08-26 视频时长下限改为 2 秒

- 原因：部分工作流界面已能选择 5 秒以下，但后端和导演台仍把短于 5 秒的值改回 5 秒，2 秒不会进入生成 graph。
- 用户可见行为：文生 / 首尾帧 / 多参考以及两个 T8 工作流的时长均可选 2–15 秒。2 秒会生成约 56 帧（约 2.3 秒，对齐模型时间网格）。导演台单镜时长同样可设为 2 秒。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/director_compiler.py`、`frontend/src/director/*`、测试和三份主文档。
- 兼容性：不改 ComfyUI 节点、端口或任务接口；默认时长仍为 5 秒。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 导演台生成状态左右对齐

- 原因：镜头列表按任务 `queued` 显示「排队中」，中央预览却把排队中的镜头一律写成「生成中」；创建任务接口返回入队时的旧快照，导演台又只靠任务列表轮询，ComfyUI 已经开始跑时左侧仍停在排队。
- 用户可见行为：左侧镜头、中央预览百分比条和时间轴使用同一套文案。worker 已领取或 ComfyUI 已在生成时，两侧都显示「生成中」；真正还在工作台队列里才显示「排队中」。
- 受影响文件：`backend/app/main.py`、`backend/tests/test_director.py`、`frontend/src/director/DirectorStudioModule.tsx`、`frontend/src/director/director-submit.ts`、`frontend/src/director/components/TimelineTrackMain.tsx`、`frontend/src/director/prompt-compiler.contract.ts` 和三份主文档。
- 兼容性：不改 ComfyUI 节点、端口、SQLite 或 `POST /api/jobs` 字段；创建任务仍返回 `202`，响应体改为入队后的当前快照。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 视频生成速度预设与自定义步数

- 原因：日常视频固定 20 步太慢；需要在创建页选择 4 步 / 8 步 / 20 步，并允许自定义步数。
- 用户可见行为：文生、首尾帧、多参考、全能参考、双时钟均可选「生成速度」：快速（4 步）、均衡（8 步，默认）、高质量（20 步）、自定义。选自定义后出现步数输入（1–40）。4–8 步启用加速 LoRA；超过 8 步关闭加速。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_workflow.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx` 和三份主文档。
- 兼容性：不改节点、端口或数据库。新任务默认均衡 8 步。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 全能参考有图时切换 Ref2VA 权重

- 原因：全能参考上传参考图后仍用 FL2VA 生成，画面几乎不跟参考图；源工作流里的 `@图片n` 还会被旧替换规则改坏。
- 用户可见行为：全能参考 / 双时钟在有参考图时改走 Ref2VA 权重。提示词里的 `@图片n`、`@图n` 会转成 `<Picture n>`；只上传图、没写标签时，后端会自动补上引用。
- 受影响文件：`backend/app/minimax_h3_t8_workflow.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改节点、端口或数据库。无图任务仍走文生 FL2VA。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 双时钟单图改为 I2VA 首帧

- 原因：双时钟加速上传 1 张图后按 Ref2VA autogrow 提交，T8 条件节点报 `name 'task_type' is not defined`；该路径也不能把 Turbo LoRA 用在 pruned Ref2VA 上。
- 用户可见行为：双时钟无图仍为文生；单图按首帧 I2VA 生成，继续使用 FL2VA 与加速 LoRA。全能参考有图仍走 Ref2VA。
- 受影响文件：`backend/app/minimax_h3_t8_workflow.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改节点、端口或数据库。显式指定 `task_type=Ref2VA` 时仍按参考图连接。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 pruned Ref2VA 不再加载加速 LoRA

- 原因：全能参考上传参考图后走 pruned Ref2VA，仍加载 Turbo LoRA，ComfyUI 初始化时报 AdaLN 维度不匹配。
- 用户可见行为：全能参考有参考图、以及标准多参考视频，不再挂加速 LoRA；快速 / 均衡仍按所选步数生成。无图全能参考、文生、首尾帧、双时钟继续使用加速 LoRA。若有图任务画面偏糊，可改选高质量（20 步）。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_t8_workflow.py`、`backend/app/minimax_h3_workflow.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改节点、端口或数据库。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 多参考加速改用全量 Ref2VA

- 原因：全量 Ref2VA INT8 已就位；有图任务此前强制 pruned，加速 LoRA 无法加载。
- 用户可见行为：多参考视频、全能参考有图、导演台绑角色参考时，快速/均衡会挂加速 LoRA。高质量仍用 pruned、20 步。不是 0.4 二采升 2.0。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_workflow.py`、`backend/app/minimax_h3_t8_workflow.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改节点、端口或数据库。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-26 导演台预览/成片两档渲染

- 原因：导演台需要先低成本打样再出成片，且旧 1K/2K/4K 没有提交真实 MP。
- 用户可见行为：预览渲染默认 0.4 MP + 4 步 + 加速 LoRA。成片渲染默认 1.0 MP + 8 步 + LoRA。导演台设置条可分别改预览/成片的 MP（0.4 / 0.7 / 1.0 / 2.0）和步数（4 / 8 / 20）。批量接龙走成片。Take 会标记预览或成片。
- 受影响文件：`frontend/src/director/*`、`frontend/src/index.css`、`backend/app/director_compiler.py`、`backend/tests/test_director.py` 和三份主文档。
- 兼容性：不改节点、端口或数据库。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-26 导演台预览/成片步数与 MP 可调

- 原因：预览 4 步在标准 H3 上容易彩斑；成片步数此前不可改。
- 用户可见行为：打开导演工程后，标题栏下方设置条可分别改预览渲染和成片渲染的 MP、步数。默认仍是预览 0.4 MP / 4 步、成片 1.0 MP / 8 步。
- 受影响文件：`frontend/src/director/*`、`frontend/src/index.css`、`backend/app/director_compiler.py`、`backend/tests/test_director.py` 和三份主文档。
- 兼容性：不改节点、端口或数据库。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 未选自定义时不回显自定义步数

- 原因：选「快速 / 均衡 / 高质量」后，任务详情仍显示默认「自定义步数 8」，容易和实际采样步数混淆。
- 用户可见行为：只有生成速度为「自定义」时才显示自定义步数；已有任务刷新详情即可。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/main.py`、`backend/tests/test_core.py`、`frontend/src/App.tsx` 和三份主文档。
- 兼容性：不改节点、端口或数据库。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 本机 Windows 后端热更新与可关闭控制台

- 原因：改 Python 后 uvicorn StatReload 把整个控制台一起关掉，服务挂掉且无法热更新；点 CMD 关闭时卡在应用关闭流程，窗口关不掉。
- 用户可见行为：双击启动脚本后，保存 `backend/app` 会自动重启 FastAPI；服务异常退出也会自动拉起。关闭该 CMD 或 Ctrl+C 会立刻结束工作台。若旧进程占着 7865 但已无响应，再次启动会先清掉再拉起。前端仍由 Vite 热更新。
- 受影响文件：`backend/dev_reloader.py`、`backend/app/worker.py`、`backend/tests/test_dev_reloader.py`、`backend/requirements.txt`、`启动本地视频工作台.bat` 和三份主文档。
- 兼容性：不改节点、端口或数据库。Docker 仍直接运行 uvicorn。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_dev_reloader.py"`、`python -m unittest discover -s backend/tests -p "test*.py"`。
- 回滚方式：恢复上述文件并改回 `uvicorn --reload`。

## 2026-08-27 LightX2V 工作流接入与创作页分组

- 原因：本机 LightX2V 加速 LoRA 需要独立工作流，工作流下拉需要按家族分组。
- 用户可见行为：视频工作流下拉分为 LightX2V、官方 MiniMax H3、自定义。LightX2V 文生 / 首尾帧 / 多参考默认 1.0 MP、4 步 euler。官方三个 H3 与 T8 行为不变。改 `extra_model_paths.yaml` 后需重启 ComfyUI。
- 受影响文件：`backend/app/workflow_registry.py`、`backend/app/minimax_h3_lightx2v_workflow.py`、`backend/app/models.py`、`backend/app/comfy_service.py`、`frontend/src/App.tsx`、`frontend/src/index.css` 和三份主文档。
- 兼容性：不改已有节点 ID、端口或数据库。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台与 ComfyUI。

## 2026-08-27 LightX2V JSON 写入 ComfyUI 工作流库

- 原因：ComfyUI 侧边栏「工作流」只列出 `user/default/workflows` 里的前端 JSON。
- 用户可见行为：刷新后出现 LightX2V 分组，含「文生视频」「首尾帧视频」「多参考加速」。工作台下拉里的 LightX2V 仍然独立存在。
- 兼容性：不改官方 MiniMax H3 JSON。LoRA 需重启 ComfyUI 后才能选到。
- 回滚方式：删除 `Comfyui/user/default/workflows/LightX2V`。

## 2026-08-27 LightX2V ComfyUI JSON 对齐本机模型名

- 原因：ComfyUI 侧栏三份 LightX2V 工作流报模型找不到。
- 用户可见行为：加载器改为本机已有的无前缀 INT8 UNET、nvfp4 CLIP、VAE 和 LightX2V LoRA；多参考改用 Ref2V LoRA。已打开的画布需重新从侧栏打开。
- 兼容性：不改官方 MiniMax H3 JSON、工作台 API 或端口。
- 回滚方式：从 `G:\ComfyUI-Models\lightx2v\工作流` 重新复制源 JSON。

## 2026-08-27 LightX2V 去掉本机没有的 RAMCleanup

- 原因：文生视频打开时报缺失节点包 `Comfyui-Memory_Cleanup`。
- 用户可见行为：侧栏三份 LightX2V 不再依赖该包，也不再带未安装的 RTX 超分节点。从侧栏重新打开即可。
- 兼容性：不改官方 MiniMax H3 JSON、工作台 API 或端口。
- 回滚方式：从 `G:\ComfyUI-Models\lightx2v\工作流` 重新复制源 JSON。

## 2026-08-27 安装缺失节点并恢复 LightX2V 原版 JSON

- 原因：补齐文生视频报缺的 `Comfyui-Memory_Cleanup`，以及多参考图里的 RTX 超分节点。
- 用户可见行为：侧栏三份 LightX2V 恢复源图结构（含内存清理与 RTX 超分节点）。模型控件使用本机无前缀 INT8 UNET、nvfp4 CLIP、VAE 和 LightX2V LoRA。重启 ComfyUI 后不再报缺失节点包。
- 兼容性：不改官方 MiniMax H3 JSON、工作台 API 或端口。
- 回滚方式：删除 `custom_nodes` 下这两个目录并卸载 `nvidia-vfx`。

## 2026-08-27 LightX2V 模型路径改回本机无前缀文件

- 原因：整份恢复源 JSON 后又出现 `MiniMax-H3\` 前缀等本机没有的模型名。
- 用户可见行为：加载器改回本机文件；已打开的画布需从侧栏重新打开。
- 兼容性：不改官方 MiniMax H3 JSON、工作台 API 或端口。
- 回滚方式：仅模型控件可再拷源 JSON，但会重新找不到模型。

## 2026-08-27 视频任务空闲后释放 ComfyUI 显存

- 原因：工作台所有动态视频工作流结束后都不卸载模型，ComfyUI 会把权重留在显存和内存里。
- 用户可见行为：没有排队或生成中的本地视频任务时，工作台会让固定 ComfyUI 卸载模型并清缓存（启动时若队列为空也会清一次）。连续排队的多条视频之间不卸载。下一次生成需要重新装模。
- 受影响文件：`backend/app/comfy_service.py`、`backend/app/worker.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改节点 ID、端口或数据库。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 八步双加速工作流分组

- 原因：参考 ComfyUI 前端工作流「minimax_h3八部双加速」的加速链（8 步 FL2V Turbo LoRA + `PathchSageAttentionKJ` + H3 Mem Eff Sage）比官方 H3 和 LightX2V 的接法更完整，需要独立分组供创作页选用。
- 用户可见行为：视频工作流下拉新增「八步双加速」分组，含文生 / 首尾帧 / 多参考。默认 0.4 MP、8 步、`res_multistep`。高质量为 20 步并关闭 LoRA。不改官方 H3、LightX2V、T8 与导演台。
- 受影响文件：`backend/app/models.py`、`backend/app/workflow_registry.py`、`backend/app/minimax_h3_dual_accel_workflow.py`、`backend/app/comfy_service.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改已有节点 ID、端口或数据库；新 mode 为增量 ID。LoRA 仍走既有 `extra_model_paths.yaml` 的 `loras: lightx2v`。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 官方 H3 预留显存并启用 Sage

- 原因：官方 MiniMax H3 首尾帧在 16GB 显卡上于 `SamplerCustomAdvanced` 报 CUDA OOM（已占用 12.51 GiB，再申请 2.56 GiB）。官方图原先没有 T8/LightX2V 的显存预留和 H3 Sage。
- 用户可见行为：官方文生 / 首尾帧 / 多参考在采样前预留 3 GB 并清理缓存，再打上 H3 显存高效 Sage。既有节点 1–15 ID 不变。分辨率仍由用户选择；16GB 上建议不要叠太高分辨率和过长时长。
- 受影响文件：`backend/app/minimax_h3_workflow.py`、`backend/app/workflow_registry.py`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改端口、SQLite 或 `POST /api/jobs` 字段；内部增加 `use_sage_attention`（默认开）。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_core.py"`。
- 回滚方式：恢复上述文件并重启工作台。

## 2026-08-27 导演台分镜页可改分辨率

- 原因：导演台 Recipe 成片默认 1.0 MP，分镜页没有分辨率入口，16GB 显卡出片时只能看到 OOM，改不了画质。
- 用户可见行为：分镜预览标题旁可改画面比例、分辨率（0.4 MP 为 16GB 推荐、1.0 MP 成片、2.0 MP 高清）和生成速度。出片前会先保存这些设置。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/types.ts`、`frontend/src/director/prompt-compiler.contract.ts`、`frontend/src/index.css` 和三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-27 导演台失败信息不撑破卡片

- 原因：ComfyUI OOM 会把整段 traceback、路径和张量字典写进任务 `error`，分镜卡片原样展示后横向撑破网格。
- 用户可见行为：卡片只显示一两句摘要（显存不足会提示改 0.4 MP），完整日志放到「查看详情」。
- 受影响文件：`frontend/src/director/director-submit.ts`、`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/prompt-compiler.contract.ts`、`frontend/src/index.css` 和三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端。

## 2026-08-27 分镜出片先等切换工作流

- 原因：ComfyUI 加载模型时的节点进度被分镜卡当成「出片中 xx%」，采样尚未开始。
- 用户可见行为：出片先显示「正在切换工作流」，UNET/CLIP/VAE 加载完成并进入采样后才显示「MiniMax H3 正在生成视频」和真实百分比。
- 受影响文件：`backend/app/comfy_service.py`、`frontend/src/director/director-submit.ts`、`frontend/src/director/prompt-compiler.contract.ts`、`backend/tests/test_core.py` 和三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs`。
- 验证命令：`python -m unittest backend.tests.test_core.WorkerTests.test_comfy_loader_progress_waits_for_workflow_switch`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-27 分镜生成可选择工作流

- 原因：分镜出片原先锁死官方 MiniMax H3，无法像生成页那样改用 LightX2V、八步双加速或 T8。
- 用户可见行为：分镜预览栏和短视频批量增加「工作流」下拉，选项来自 `/api/modes` 分组。文生 / 首尾帧 / 多参考仍按镜头素材自动匹配。旧工程默认官方 MiniMax H3。
- 受影响文件：`workflow_registry.py`、`director_compiler.py`、`director_jobs.py`、`director_recipe.py`、导演台前端、测试与三份主文档。
- 兼容性：不改节点、端口或 `POST /api/jobs` 外部字段。未写 `videoWorkflowFamily` 的旧工程仍走官方 H3。
- 验证命令：`python -m unittest backend.tests.test_core.WorkflowTests.test_resolve_director_workflow_uses_family_then_route backend.tests.test_director.DirectorCompilerTests.test_workflow_family_routes_lightx2v_and_dual_accel backend.tests.test_director.DirectorDualEngineApiTests.test_batches_enqueue_selected_workflow_family`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端、重启工作台。

## 2026-08-28 导演台定妆绑定与单镜时间线修复

- 原因：分镜 Agent 可能把剧本中的中文人物/地点翻成英文，后续定妆仍保存中文名，导致出片误把无关场景图装进 R2V、漏掉人物定妆；单镜 `promptText` 还可能残留整片的 `[Shot 3] At 00:11.000` 等累计时间码。
- 用户可见行为：出片会先按规范化名称匹配，旧工程在人物/地点数量一一对应时按稳定顺序恢复中英文别名；显式指定但无法匹配的资产不再用任意场景图兜底。每个单独提交的镜头会移除开头的旧镜号和累计时间码，再由编译器生成自己的 `[Shot 1]`。新分镜被要求保留剧本原名且时间从 `00:00` 开始。
- 受影响文件：`backend/app/director_compiler.py`、`backend/app/llm_minimax_skills.py`、`backend/tests/test_director.py` 和三份主文档。
- 兼容性：不改 API、SQLite、工作流 ID、ComfyUI 节点 ID 或媒体文件；历史 Recipe 无需迁移，重新生成镜头即可使用修复后的编译结果。
- 验证命令：`python -m unittest backend.tests.test_director.DirectorCompilerTests backend.tests.test_director.DirectorAgentPipelineTests`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述三个代码/测试文件并重启工作台；已有工程和历史成片不需要回滚。

## 2026-08-28 导演台按官方 H3 模式进行最终提示词润色

- 原因：导演分镜先生成独立镜头正文，提交时才知道实际装箱的参考图顺序；旧编译器只能机械拼装提示词，无法按照 MiniMax H3 官方 `h3-prompt-writing` 的 T2VA / I2VA / FL2VA / L2VA / Ref2VA 分支，对最终镜头做有语义的润色。
- 用户可见行为：提交分镜前，已配置的大模型会按实际参考关系重写最终 H3 提示词：无图为 T2VA，首帧为 I2VA，首尾帧为 FL2VA，仅尾帧为 L2VA，多参考主体为 Ref2VA。Ref2VA 由大模型自然地把 `<Subject N>` 写入镜头正文，工作台只校验官方字段、顺序和既有标签，不替换角色名称。大模型未启用时保留既有编译提示词并可正常出片。
- 受影响文件：`backend/app/llm_minimax_skills.py`、`backend/app/llm_provider.py`、`backend/app/director_compiler.py`、`backend/app/director_jobs.py`、`backend/app/main.py`、`backend/app/director_agents.py`、`backend/app/director_recipe.py`、导演台类型/预览编译器、测试与三份主文档。
- 兼容性：不改工作流 ID、ComfyUI 节点、端口、SQLite schema 或 `POST /api/jobs`。历史 Recipe 无需迁移；无大模型配置时保持原提交路径。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件后重新构建前端并重启工作台；已有任务与媒体不受影响。

## 2026-08-30 导演生成一致性与持久化操作两阶段修复

- 原因：生成进度曾用旧 Recipe 整体回写，可能覆盖生成期间的文案、时长、参考素材和 Take 选择；流式 LLM 的包装超时可能被降级为成功；旧 Take/旧任务状态可能遮蔽新提交；剪辑串播过滤缺片后会重新累计时间，造成片段、刻度和播放头错位。同步 LLM 请求也无法跨后端重启恢复明确状态。
- 第一阶段用户可见行为：H3、静帧和 TTS 只原子合并服务端执行字段并追加 Take，自动保存前会先落盘，轮询不再覆盖本地创作字段。LLM 读超时统一返回现有规范的 502。新任务失败但存在旧可用 Take 时保留旧片预览/合成并显示本次错误；无旧片才进入 `failed`。时间轴保留缺片镜头的真实空档，播放自动跳到下一条可播镜头的原始起点；缩放下限由最短镜头动态计算，删除镜头同步清理选中集合。
- 第二阶段用户可见行为：工程响应增加 `revision` / `content_revision`，创作保存携带 `expected_content_revision`；跨窗口冲突返回 409，前端 Modal 只允许加载云端或明确覆盖。方案流水线和分镜提交准备改为持久化操作：`POST /api/director/recipes/{project_id}/operations` 返回 202，随后通过 `GET /api/director/operations/{operation_id}` 轮询，并可 `POST .../cancel`。重启后未完成操作标为 `interrupted`，不会自动重试或重复计费。
- 字段与模块边界：创作字段和执行字段由 `director_project_service.py` 白名单合并；Take 追加保存，`approvedTakeId` 是持久化创作选择，预览 Take 只留在组件局部状态。前端拆出工程/冲突控制器、长操作控制器、Recipe 模型、readiness、时间轴和执行状态模块，`types.ts` 暂时 re-export 兼容旧导入。
- 受影响文件：`backend/app/llm_client.py`、`director_agents.py`、`director_jobs.py`、`director_project_service.py`、`director_takes.py`、`director_operations.py`、`storage.py`、`models.py`、`main.py`、`api_documentation.py`，`frontend/src/director/DirectorRecipeStudio.tsx`、`director-api.ts`、`director-project-controller.ts`、`director-operation-controller.ts`、`recipe-model.ts`、`recipe-readiness.ts`、`recipe-timeline.ts`、`recipe-execution.ts`、时间轴/Inspector 组件、Vitest 配置与对应测试，以及三份主文档。
- 兼容性：第一阶段不改数据库或工作流协议，唯一有意行为变化是错误的超时 200 改为 502。第二阶段启动前自动备份 SQLite 为 `<数据库文件>.pre-director-concurrency-v2.bak`；新增列、表和响应字段均为增量，旧客户端可暂不传内容版本。`/api/director/recipes/run` 与 `/render-shots` 保留一个版本并标记 deprecated。未修改工作流注册表、ComfyUI graph、节点 ID、模型路径或端口。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。桌面 1440×900 与手机 390×844 检查生成期间编辑、超时提示、缺片跳播、时间轴几何、删除选择清理与冲突 Modal。
- 回滚方式：第一阶段可恢复对应应用文件并重新构建前端。回滚第二阶段前先停止工作台并另存当前数据库；可恢复迁移前的 `.pre-director-concurrency-v2.bak`（会放弃迁移后的工程修改和操作记录），或仅恢复代码并保留新增列/表。历史媒体和 ComfyUI 工作流不需要回滚。

## 2026-08-30 导演台时间轴移植 OpenCut classic 交互内核

- 原因：原时间轴只有刻度点击和窄幅右侧拉伸，播放头不可拖动；拉伸时每次指针移动都会改整份 Recipe 并触发自动保存，播放又依赖低频 `timeupdate`，操作存在明显卡顿和跳动。
- 当前基线：以 MIT 许可的 OpenCut classic `cf5e79e919144200294fb9fed22a222592a0aeea` 为固定上游，源码映射见 `frontend/src/director/opencut-timeline/UPSTREAM.md`。移植 `PlayheadController`、`ResizeController`、`ElementInteractionController`、`ZoomController`、`useCommittedRef` 与边缘自动滚动，保留其显式 Session、全局手势捕获、5px 拖动阈值、preview/commit 分离和订阅式局部刷新。
- 用户可见行为：播放头和刻度均可按帧拖动；镜头块可换序；拉时长只在松手后保存一次；镜头边界/播放头吸附可关闭，按住 Shift 临时绕过；Ctrl/Command+滚轮以播放头为锚点缩放；拖到轨道边缘自动滚动；空白区可拖播放头，Shift 拖框选，空格或中键拖动画布。播放期间用 `requestVideoFrameCallback` 直接更新 playhead transform。
- 受影响文件：`frontend/src/director/opencut-timeline/*`、`director-timeline-engine.ts`、`types.ts`、`DirectorRecipeStudio.tsx`、三个时间轴组件、`director-timeline.test.ts`、`index.css` 和三份主文档。
- 兼容性：只替换前端交互内核；不改 API、SQLite、Recipe 字段、工作流注册表、ComfyUI graph、节点 ID、模型路径或 7865/8188 端口。OpenCut 的任意多轨/WASM 模型收敛为本项目 24fps 的连续 `RecipeShot` 主轨，H3 提交时长仍限制为 2–15 秒整数。
- 验证命令：`pnpm --dir frontend test`、`pnpm --dir frontend build`、`python -m unittest backend.tests.test_director`。浏览器桌面 1440×900 检查全部时间轴手势；手机 390×844 确认仍锁定方案视图。
- 回滚方式：恢复上述前端文件和三份文档后重新构建前端；无需迁移或回滚数据库、Recipe、媒体与 ComfyUI 资产。

## 2026-08-30 导演台播放器复刻 OpenCut 五键运输控制

- 原因：剪辑视图的中间播放器仍使用浏览器原生控制条，缺少 OpenCut 的首尾跳转和逐帧检查，视觉与交互没有跟上已移植的时间轴。
- 用户可见行为：播放器下方改为 OpenCut 同款五键运输控制：跳到开头、后退一帧、播放/暂停、前进一帧、跳到结尾；左侧显示 `HH:MM:SS:FF` 时间码，右侧 SAFE 可显示/隐藏 action-safe 与 title-safe 参考框。Home/End、左右方向键、Space 同步可用，Shift+左右键步进 10 帧。
- 源码基线：五键结构与整数帧语义固定参考 MIT 许可的 `S07K/OpenCut` commit `e9c6cc06b549d7fa857bb8f43f02c47a39368e33`，映射见 `frontend/src/director/opencut-timeline/UPSTREAM.md`。
- 受影响文件：`frontend/src/director/components/DirectorTimelineView.tsx`、`PlayerTransport.tsx`、`opencut-timeline/transport.ts`、`director-timeline.test.ts`、`index.css` 和三份主文档。
- 兼容性：只增加前端播放器控制，不改 API、SQLite、Recipe schema、工作流、ComfyUI graph、节点 ID、媒体与端口；旧工程直接使用。
- 验证命令：`pnpm --dir frontend test`、`pnpm --dir frontend build`、`python -m unittest backend.tests.test_director`；桌面 1440×900 检查五键、逐帧时间码、播放续播/结尾回放与 SAFE，手机 390×844 确认仍锁定方案视图。
- 回滚方式：恢复上述前端文件与文档并重新构建；数据库、Recipe、媒体和 ComfyUI 无需回滚。

## 2026-08-30 全站浅色 / 暗色双主题

- 原因：原工作台以浅色为主，导演台和部分旧组件仍含固定色值，无法给长时间创作用户提供一致的暗色使用环境。
- 用户可见行为：首次访问仍为浅色；桌面顶栏可快捷切换，移动端可从账户菜单切换，导演台自有顶栏同步提供入口。选择保存在当前浏览器，刷新及登录前后继续生效。登录、创作工作台、素材库、导演台、管理员设置和 Ant Design 弹层均跟随主题。
- 受影响文件：`frontend/index.html`、`frontend/src/theme.ts`、`ThemeProvider.tsx`、`components/ThemeToggle.tsx`、`main.tsx`、`App.tsx`、`auth/AuthScreens.tsx`、`admin/AdminSettings.tsx`、导演台页面、`index.css`、`theme.test.ts`、前端产品/设计规范和三份主文档。
- 兼容性：仅新增前端显示状态和浏览器 `localStorage` 键 `zly-ai-video-studio.theme`；无 API、SQLite、任务、Recipe、工作流注册表、ComfyUI graph、节点 ID、模型路径或端口变化。旧浏览器记录缺失或非法时回退浅色。
- 验证命令：`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。浏览器以 1440×900 和 390×844 检查两种主题、刷新记忆、账户菜单、导演台、管理后台与传送弹层。
- 回滚方式：恢复上述前端主题相关文件和文档并重新构建前端；可选清除 `zly-ai-video-studio.theme`，无需迁移或回滚数据库、Recipe、媒体与 ComfyUI 资产。

## 2026-09-03 导演台可选提示词润色

- 原因：角色、场景和道具已完成定妆后，手动出片不一定需要再次调用云端大模型润色 H3 提示词。
- 用户可见行为：导演台“输出设置”新增“提示词润色”开关。开启时保持原有润色流程；关闭时直接提交当前镜头提示词，不调用大模型。偏好按项目保存在浏览器本地，默认开启；静帧模式下开关禁用。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/director-api.ts`、`backend/app/models.py`、`backend/app/director_operations.py`、`backend/app/main.py`、`backend/tests/test_director.py`。
- 兼容性：新增请求字段 `polish_prompt`，默认 `true`，旧客户端和旧工程无需迁移；关闭仅跳过 H3 提示词润色，视频工作流、素材引用和任务队列不变。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述文件并重新构建前端；无需回滚数据库、Recipe、媒体或 ComfyUI 资产。
## 2026-08-31 导演台角色定妆与资产库

导演台的角色定妆已升级为两阶段生产流程：先生成并批准身份肖像，再以肖像为唯一身份参考生成面部特写、正面全身、四分之三和背面四联定妆板。地点生成空场景母版，道具生成四视图转面图；每次候选都保留提示词和工作流快照，只有批准版本才会进入分镜参考图和员工资产库。

分镜现在按稳定的角色/造型、地点和道具 ID 绑定参考资产，提交前会检查 MiniMax H3 最多 9 张参考图的限制并给出可操作提示。旧工程的 `imageUrl` / `imageJobId` 会自动兼容，不需要迁移。后端专项验证：`python -m pytest backend/tests -q`；前端验证：`pnpm --dir frontend build`。

## 2026-09-01 分镜衔接润色

导演台会在拆镜和时长/对白润色后，对整个镜头序列补写入镜状态、出镜状态和中文转场说明。入镜与出镜状态会编译进每个独立的 MiniMax H3 提示词；若要锁住实际画面，还可在镜头检查器启用“用上一镜尾帧作为本镜首帧”。旧工程无这些字段时照旧生成。

## 2026-09-01 Seedance 剧本全流程润色

剧本扩写按 scene ledger 写出每场开场/节拍/收束；分镜首次拆镜就会草拟文案衔接，再经时长与衔接两轮润色。方法来自本地 Seedance 2.5 skill，已适配 MiniMax H3 独立镜头协议，不会改成 Seedance API 格式。

## 2026-09-03 导台2 相邻镜头尾帧衔接

从第二条可出片 Beat 起，必须先生成上一镜视频。镜头页默认截取上一镜最后一帧作为本镜起点（可拖动上一镜进度条后手动截取）。生成提示词和视频时，0–1.5 秒从该截图过渡到本镜精绘，之后按本镜动作继续。没有上一镜成片时不能生成本镜视频。

## 2026-09-03 导台2 整集自动生成

镜头页可添加整集自动生成任务：提交时锁定视频参数，从 Beat 1 起依次完成草图、精绘、提示词和视频。上一镜成片后才进入下一镜。关闭页面不会打断后端编排。

## 2026-09-08 分镜连续性修复

导演台连续性润色现在以五镜头窗口加一个重叠上下文镜头处理镜头序列，镜头 5→6 会在同一请求中校验动作、人物位置、道具、天气、光线和声音承接。连续性 pass 只更新边界状态与声音/提示词字段，错误编号或缺镜头会重试并保留原镜头；结构化 `continuityQa` 会在工程中记录风险，旧 Recipe 没有该字段也能继续打开。对白字段会自动去除 `<d>`、`[Chinese]` 和角色情绪前缀，并同步 H3 提示词中的对白标签。

本阶段仅修改后端连续性处理、对白规范化、回归测试和文档，不改变 API 请求格式、数据库表、ComfyUI 工作流、节点 ID、模型路径或端口。

## 2026-09-08 分镜连续性阶段 2：因果动作修复

- 原因：阶段 1 能发现“上一镜出镜状态与下一镜开场动作不一致”，但只留下风险时，镜头 5→6 仍可能从“递牌/贴符”直接跳到“斩藤落石”。
- 当前行为：连续性 QA 标出的相邻风险会进入一次有界的因果修复请求。修复器只允许改 `promptText`、`continuityIn`、`continuityOut`、`transitionNote`、`soundscape` 和 `soundscapeEn`，强制下一镜先呈现上一镜的触发状态，再开始防御、转身、追逐等后续动作；对白、时长、镜头编号、角色/场景/道具绑定和 camera 不可被覆盖。修复后会重新运行 QA。
- 安全边界：大模型只能返回已请求的边界；重复、越界或缺失边界会被拒绝。若一个镜头确实包含无法在同一片段表达的两个独立可播放动作，可返回 `needs_resplit`，系统记录到 `continuityQa.repair.resplitRequired`，不擅自重编号或伪造过渡。
- 兼容性：只增加可选的 `continuityQa.repair` 结果字段，不改 API 请求格式、数据库表、工作流 graph、ComfyUI 节点、模型路径或端口；旧 Recipe 和无大模型配置仍可打开/生成。
- 受影响文件：`backend/app/director_agents.py`、`backend/app/director_recipe.py`、`backend/app/llm_minimax_skills.py`、`backend/tests/test_director.py` 与三份主文档。
- 验证命令：`python -m unittest backend.tests.test_director`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。
- 回滚方式：恢复上述后端、测试和文档文件；无需迁移数据库或回滚媒体、ComfyUI 资产。

导演台剧本拆解支持 literal（默认，忠实保留原对白与事件）和 creative（允许 AI 扩写）两种模式；旧客户端不传字段时仍按 literal 运行。

导演台连续性风险支持局部 LLM 修复：镜头检查器调用 `/api/llm/repair-continuity`，只修复指定相邻镜头的连续性字段并自动重新 QA。

## 2026-09-08 视频分辨率选择

H3 视频生成以后端 `quality` 档位计算实际宽高，避免旧草稿的内部 MP 缓存覆盖用户选择。新建或重新提交任务时，界面显示的 1280×736 等尺寸会与 ComfyUI graph 保持一致。


## 2026-09-08 流式媒体请求卡死修复

- 原因：请求日志中间件回放请求体后无限返回空 `http.request`，流式响应监听断连时可能进入无让出的忙循环，阻塞同进程健康检查和其他请求。
- 当前基线：请求体仅回放一次，后续 `receive()` 委托原始 ASGI transport，保留真实等待与断连；上传期间断连不再派发残缺请求。
- 受影响文件：`backend/app/request_log.py`、`backend/tests/test_request_log.py` 和三份主文档。
- 兼容性：无 API、数据库、端口、工作流或媒体格式变更。需重建并更新服务器镜像，仅重启旧镜像不会修复。
- 验证命令：`python -m unittest backend.tests.test_request_log -v`、`python -m unittest discover -s backend/tests -p "test_*.py"`、`pnpm --dir frontend build`。部署后打开媒体预览并同时执行 `curl --max-time 5 http://127.0.0.1:18189/api/health`。
- 回滚方式：恢复上述代码并重建旧镜像；无需回滚数据库和数据卷，但旧版会恢复该忙循环风险。
## 2026-09-08 手动分镜结构化对白

为解决双人对白合并到单个语音标签的问题，RecipeShot 新增可选 dialogueLines（speaker/text），经 director_recipe.py 保存、director_compiler.py 和前端 types.ts/prompt-compiler.ts 编译为逐句独立标签；manual-import.ts 与 RecipeShotInspector.tsx 支持导入和编辑角色台词。角色编号在单镜内按首次出现顺序复用，角色名放在语音标签外。旧 dialogue 字符串保持兼容；旧数据丢失的角色信息需重新导入或编辑，不能自动恢复。

验证：pnpm --dir frontend build；python -m unittest backend.tests.test_structured_dialogue backend.tests.test_director -q。当前系统 Python 缺少 pymysql，导演测试有一项启动失败。回滚：恢复上述前后端文件并重新构建；无需数据库迁移。


## 2026-09-08 导演台八步双加速提交修复

导演台预览、终稿及批量生成按所选工作流注册表校正速度：旧工程或默认预览中的 fast 在八步双加速下回退到注册表默认 balanced，避免“生成速度不是有效选项”；支持的速度保持原值。涉及 backend/app/director_compiler.py、backend/app/director_jobs.py 与 backend/tests/test_director_workflow_speed.py。不改变 API、数据库或 ComfyUI graph 协议，旧工程无需迁移。

验证命令：python -m pytest backend/tests -q；pnpm --dir frontend build。回滚：撤销上述文件中本节对应的速度校正和测试改动，保留其他已有修改。

## 2026-09-08 导演台导入与润色预览纠正

修复 Markdown 时间码导入为默认 5 秒、声音遗漏和结构化对白重复；前后端编译保留画面描述。检查器区分当前编译预览与最近一次实际提交快照，明确词数按空白统计。开启润色而 LLM 不可用时返回错误，禁止静默跳过。受影响文件：manual-import.ts、prompt-compiler.ts、types.ts、RecipeShotInspector.tsx、director_compiler.py、director_operations.py、main.py。兼容性：不改数据库与工作流节点；旧工程不自动改写。验证：pnpm --dir frontend build；python -m unittest backend.tests.test_structured_dialogue backend.tests.test_director -q。回滚：仅撤销本次相关变更并重建前端，保留其他未提交改动；无需数据迁移。
## 2026-09-08 导演台五阶段流程重构

导演台按“故事与风格 → 分镜设计 → 视觉素材 → 镜头制作 → 声音与交付”组织导航；切换阶段、剪辑视图和打开页面只导航，不自动生成或导出。镜头制作参数按 `/api/modes` 注册表声明，手机端进入生成设置抽屉；成片页先列出缺失镜头并提供定位。验证：`pnpm --dir frontend build`、隔离 SQLite 后端回归、Playwright 三尺寸双主题流程检查。回滚：恢复本次导演台前端、流程纯函数和注册表兼容字段；不改数据库或 ComfyUI 协议。

## 2026-09-11 导演台剧本流式生成展示

- 用户可见行为：在导演台填写创意简报并点击「生成创作方案」后，剧本任务区不再显示输入框，而是像 AI 聊天工具一样逐步写出作品——顶部为「AI 导演正在创作」状态与耗时，下方任务行显示 9 个 Agent 实时进度，正文以打字机效果流式写出片名、一句话梗概和完整故事，当前写入位置带光标与「正在写：…」提示。生成完成后停留在剧本页展示成稿文档，不再自动跳转分镜；可用「编辑剧本」显式切换回表单微调，或点「进入分镜设计」继续。取消/失败时保留已写出的内容并变暗展示；未填写创意时显示引导空态。刷新页面回到生成中的工程可恢复流式观看。
- 受影响文件：`backend/app/{director_stream,director_operations,director_agents,llm_provider,main}.py`、`backend/tests/test_director_stream.py`、`frontend/src/director/{director-operation-stream.ts,DirectorRecipeStudio.tsx,action-copy.ts,guided-flow.css}`、`frontend/src/director/components/{DirectorScriptStreamPanel,DirectorScriptDocument}.tsx` 和三份主文档。
- 兼容性：新增 SSE 端点 `GET /api/director/operations/{id}/events`；不改既有 operation 创建/轮询/取消 API、数据库、工作流或端口，轮询保留为兜底，旧客户端不受影响。
- 验证命令：`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py -q`；`pnpm --dir frontend build`。
- 回滚方式：还原本次提交即恢复输入框 + 轮询行为；无数据库迁移。

## 2026-09-11 导演台聊天记录式生成与创意澄清

- 用户可见行为：点「生成创作方案」先进入创意澄清——AI 根据创意流式提出 2-3 个剧情走向问题，Approval Card 逐题作答（推荐选项 / 自己写 / 跳过单题 / 跳过全部），答完自动按所选方向开始生成。生成中为聊天记录式视图：剧本、画风、角色、场景、分镜、配音、配乐每步产出依次追加为段落块，角色/场景卡逐张浮现并流式打出描述，镜头行按镜号依次出现；运行中的块展开、完成的块折叠为一行摘要（点击回看），自动跟随滚动、上滚暂停。已确认方向以 chips 显示。未答完问题刷新页面可恢复。
- 受影响文件：`backend/app/{director_stream,director_agents,llm_minimax_skills,models,llm_provider,director_operations,main}.py`、`backend/tests/test_director_stream.py`、`frontend/src/director/{director-operation-stream.ts,DirectorRecipeStudio.tsx,director-api.ts,action-copy.ts,guided-flow.css}`、`frontend/src/director/components/DirectorScriptStreamPanel.tsx` 和三份主文档。
- 兼容性：新增 operation kind `plan_clarify` 与 plan_pipeline 可选 `clarifications` 字段；SSE 事件协议 `script_delta` 升级为通用 `agent_delta`/`agent_item`（前后端同版本）；不改数据库、ComfyUI 协议或既有轮询 API。
- 验证命令：`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py -q`；`pnpm --dir frontend build`。
- 回滚方式：还原本次提交即回到「仅剧本流式展示」现状；无数据库迁移。

## 2026-09-11 导演台 Prompt Bar 对话式创作室布局

- 用户可见行为：创意输入移到剧本任务区底部（对话式输入条，Enter 发送 / Shift+Enter 换行），发送后创意以气泡出现在对话顶部；生成中输入条变为状态条（进度 + 取消），澄清等待时提示先回答上方问题；空状态为居中欢迎区 + 3 个示例创意（点击填入）。剧本阶段顶栏与底栏不再重复生成/取消按钮（画风等其他阶段保留原入口）；左侧栏不再显示创意简报卡。批量短视频页主题输入同样移到底部 Prompt Bar，表单卡只保留生成参数。
- 受影响文件：`frontend/src/director/{DirectorRecipeStudio.tsx,DirectorBatchStudio.tsx,action-copy.ts,guided-flow.css}`、`frontend/src/director/components/{DirectorPromptBar.tsx,DirectorScriptStreamPanel.tsx}` 和三份主文档。
- 兼容性：纯前端布局调整；创意内容的自动保存与生成 API 不变。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：还原本次提交即恢复侧栏简报卡 + 顶栏按钮布局。

## 2026-09-11 导演台 Agent 对话界面重构（双模式）

- 用户可见行为：剧本创作阶段为全屏对话界面——生成任务面板改为垂直 Task Rows（状态图标、实时消息、总进度条、百分比、耗时，终态折叠为一行可展开）；分镜镜头逐字流式打印（活跃镜头带光标，标题未出时显示骨架）；画风以卡片展示并可弹层更换（原「剧本/画风」Tabs 移除）；完成后显示完成卡与「进入分镜设计 / 重新生成」操作卡。左侧导航、阶段头与顶栏任务活动/取消按钮在对话阶段隐藏（取消由输入条承担，「任务活动」移入更多菜单）；其他阶段保留编辑工作台与左侧导航，侧栏点「剧本」回对话。
- 受影响文件：`frontend/src/director/DirectorRecipeStudio.tsx`、`frontend/src/director/components/{DirectorTaskRows,DirectorCompletionCard,DirectorScriptStreamPanel}.tsx`、`frontend/src/director/{action-copy.ts,guided-flow.css}` 和三份主文档。
- 兼容性：纯前端布局重构；不改 API、`?stage=` 协议与后端。
- 验证命令：`pnpm --dir frontend build`；`python -m pytest backend/tests/test_director_stream.py backend/tests/test_director.py -q`。
- 回滚方式：还原本次提交即恢复 Tabs+侧栏+水平任务行布局。

## 2026-09-12 对话组件按官方源码逐像素复刻

创意澄清卡、Prompt Bar、用户气泡、流式光标、等待加载器按官方 ai-native-react-components 源码逐像素复刻：澄清卡为行式单选（选中自动翻页、圆点分页器、墨色发送箭头、可跳过单题或全部）；输入条聚焦加深描边、发送键墨色方形箭头；气泡右对齐无底色；等待态为像素网格加载器。规则已写入 AGENTS.md（导演台 AI 对话界面视觉标准），后续该区域样式改动必须对照官方源码并浏览器实测。

验证：`pnpm --dir frontend build`。回滚：还原本次提交。

## 2026-09-12 复刻台（参考片拉片 + VACE 深度转绘）

- 用户可见行为：导演台首页新增「参考片复刻」创建卡（`/director/replication/:projectId`）。上传参考片（mp4/mov/webm，≤2GB，仅用于分镜学习与参考复刻）后可一键拉片：智能分镜（按镜头切换点，灵敏度可调）或固定分段；自动提取全片深度视频并逐镜切段；用配置的视觉大模型逐镜反推英文 H3 提示词、运镜说明与主体清单（人物/场景/道具及出镜镜头），视觉模型不可用时提示词可手动填写。拉片结果以逐镜卡片展示（原片段、深度视频、关键帧、可编辑提示词），支持修改后批量转绘或单镜转绘：本地 Wan2.1 VACE 1.3B 以深度视频锁定原片运镜与构图，用提示词与原片首帧/参考图重塑画面内容；深度控制强度、采样步数、目标风格可调。转绘任务与创作台共用同一 ComfyUI 串行队列，原片与复刻成片并排对比，失败镜头可就地重试。
- 依赖与准备：整合包 ComfyUI 模型目录需具备 `wan2.1_vace_1.3B.safetensors`（可对 `vace-native-checkpoint/diffusion_pytorch_model.safetensors` 做硬链接）、`text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`（约 6.7GB）、`vae/wan_2.1_vae.safetensors`、`models/geometry_estimation/depth_anything_3_mono_large.safetensors`（约 1.3GB）；反推提示词需在管理后台配置带视觉（VL/Vision）的大模型。单镜转绘按 16fps、4n+1 帧网格，上限 81 帧（约 5 秒）。
- 受影响文件：`backend/app/{video_analysis,video_depth_workflow,wan_vace_depth_workflow,director_replication}.py`（新增）与 `workflow_registry/comfy_service/director_operations/main/models/llm_*` 扩展；`frontend/src/director/{DirectorReplicationStudio.tsx,replication-model.ts}`（新增）与路由/导航/样式扩展。详见 `docs/ARCHITECTURE.md` 同日条目。
- 验证：`python -m pytest backend/tests -q`（440 通过）；`npm --prefix frontend run build` 通过；ComfyUI 实跑深度提取与复刻出片成功。

## 2026-09-12 任务队列原子认领与后端健壮性修复批次

- 用户可见行为：多机共享数据库部署时，同一图片/视频任务只会被一台机器执行一次（此前 GRS 图片可能重复提交重复扣费）；整集自动生成的「取消」不再被进度回写吞掉；管理员查看员工工程的导演台首尾帧、配音、配乐、FCPXML/EDL 导出恢复正常（此前 404）；批量短视频「重新裂变」对非批量工程返回 422 提示（此前静默清空工程）；对不接受负面提示词/图片尺寸的工作流，这两个字段被忽略且任务可正常打开；对白含反斜杠、SRT/ASS 整分进位、静帧重复点击、参考图上传失败残留、ComfyUI 非 JSON 响应、GRS 超时文案、七牛中文文件名 URL、登录限流内存、修改密码污染最后登录时间等健壮性问题一并修复。重试失败项传入不存在的轮次 ID 现在返回 404（此前静默重试最后一轮）；并发双击「再生成一轮」返回 409 友好提示（此前 500）；整集自动生成过程中镜头被删除时给出明确错误（此前内部异常）。
- 受影响文件：`backend/app/{main,storage,worker,auth,comfy_service,dialogue_timing,xiaji_auto_pipeline,xiaji_compose,director_jobs,director_export,xiaji_episode_api,xiaji_episode_run_store,qiniu_storage,llm_provider,api_documentation}.py`、`backend/tests/{test_core,test_director,test_dialogue_timing,test_dev_reloader,test_xiaji,test_ai_studio}.py` 和三份主文档。
- 兼容性：无数据库迁移；API 结构不变；行为变化仅限上述用户可见项；create_job/create_job_round/retry-failed-items 的数据库读写改为线程池执行，事件循环不再被远程数据库抖动阻塞。
- 验证命令：`python -m pytest backend/tests -q`（407 passed）；`pnpm --dir frontend build`。
- 回滚方式：还原本次提交即恢复原行为。

## 2026-09-13 导演台剧本封面

导演台剧本阶段新增可选剧本封面图：在空态或成稿工具栏上传后，工程库卡片和创作回放会显示该用户图片，也可随时替换或移除。没有上传封面时不显示任何自动生成的人物或场景背景。澄清问题卡逐行保留所有预置选项，并额外保留“输入你的想法”自定义输入项。旧工程无需迁移；接口和验证方式详见 `功能说明与扩展指南.md` 与 `docs/ARCHITECTURE.md`。


## 2026-09-13 镜头正文支持“中文编辑、英文提交”

导演台镜头检查器（文案 Tab）的「中文镜头正文」编辑框即这一镜的中文内容（AI 分镜生成后直接有值，原「描述（中文卡片）」编辑框已并入）：直接用中文写这一镜的画面与动作，点「翻译为英文正文」由大模型按 MiniMax H3 官方 skill 生成提交用的英文镜头正文（对白/画面文字保留原语言、人名不翻译）。英文正文仍可手动微调，手动改过后翻译会先确认再覆盖；同步状态以徽标显示（待同步 / 已手动调整 / 已同步）。提交、编译与润色链路不变，仍只提交英文 `promptText`；没有中文正文时在英文框直接手写的老用法完全不变。同时修复了「当前分镜编译预览」会多显示一行实际不会提交的中文描述的问题——预览即润色前的真实提交内容。翻译功能依赖管理设置中已配置的大模型；接口与验证方式详见 `docs/API.md`、`功能说明与扩展指南.md` 与 `docs/ARCHITECTURE.md`。

## 2026-09-13 视觉素材新增「道具定妆」子阶段

导演台视觉素材组的道具从“角色定妆内的一个 Tab”提升为独立子阶段：左侧阶段导航现在显示「角色定妆 / 场景定妆 / 道具定妆」三个子项，与内容区的「角色 / 场景 / 道具」Tab 一一对应；道具定妆有独立就绪进度（按已采纳转面图计算），可用 `?stage=props` 直达，任务头提供道具阶段说明与「采用道具 / 生成待处理道具 / 下一步：镜头制作」按钮链。既有工程与旧链接不受影响；后端生成流水线不变。详见 `功能说明与扩展指南.md` 与 `docs/导演台流程与界面结构.md`。

## 2026-09-13 「分镜设计」并入「镜头设计」

- 用户可见行为：左侧导航不再有独立的「分镜设计」阶段；保留单一「镜头设计」阶段放在视觉素材之后，导航收敛为四组（故事与风格 / 视觉素材 / 镜头设计 / 声音与交付），与后端 Agent 流水线顺序一致。镜头设计阶段内以「设计 / 制作」Segmented 切换：设计=编辑镜头序列与提示词、按剧本重新生成分镜、导入分镜；制作=生成设置、生成选中、重试失败镜头、重新生成全部镜头（原「镜头制作」全部能力）。流程改线性：剧本/画风 → 视觉素材 → 镜头设计 → 声音与交付；镜头检查器设计模式底部按钮为「切换到制作」。旧链接 `?stage=storyboard` / `board` 自动落到镜头设计阶段；既有工程数据与后端 9 Agent 流水线不变。
- 受影响文件：`frontend/src/director/recipe-readiness.ts`、`recipe-flow.ts`、`DirectorRecipeStudio.tsx`、`action-copy.ts`、`components/DirectorTaskHeader.tsx`、`DirectorStageNav.tsx`、`RecipeShotInspector.tsx`、`DirectorExportPanel.tsx`、`DirectorCompletionCard.tsx`、`recipe-readiness.test.ts`、`docs/导演台流程与界面结构.md`、`docs/ARCHITECTURE.md`、`docs/API.md`、`功能说明与扩展指南.md`。
- 兼容性：纯前端导航与交互层变更；不改后端、数据库与 ComfyUI 协议，工程数据零迁移。
- 验证命令：`pnpm --dir frontend build`、`python -m unittest backend.tests.test_director`；桌面/移动端浏览器检查导航分组计数、设计/制作切换与旧链接兼容。
- 回滚方式：还原本次前端提交即可。

## 2026-09-13 存储目录弹窗抗瞬时错误（七牛云场景）

- 用户可见行为：启用七牛云后，「设置作品存储目录」授权弹窗不会因 `/api/storage` 瞬时失败（后端重启、网络抖动）而误弹；能力结果会缓存在浏览器本地作为兜底。未启用七牛云的本地流式交付部署行为不变。
- 受影响文件：`frontend/src/App.tsx`。
- 验证命令：`pnpm --dir frontend build`。
- 回滚方式：还原 `App.tsx` 本次改动即可。

## 2026-09-14 修复：手动模式切不回「AI 生成」

导演台「AI 生成 / 手动编辑」模式开关此前在有未回答的剧本澄清问题时会被整体禁用，而澄清卡只在剧本对话室显示，其他环节既看不到卡片也没有提示——用户拿到澄清问题后没回答就离开，之后在任意环节都无法切换创作模式。现在仅在实际生成（流水线）进行中禁用开关；未回答的澄清问题卡继续保留，切回「AI 生成」后在剧本阶段仍可作答或跳过。切换成功时会弹出「已切换到手动编辑 / 已切换到 AI 生成」提示——画风等阶段两种模式界面几乎一致，此前切换后没有任何可见变化，容易被误认为没切成功。详见 `功能说明与扩展指南.md` 与 `docs/ARCHITECTURE.md`。

## 2026-09-14 导演台2（AI Media Studio）整体替代夏姬模块

旧夏姬（xiaji）前后端模块整体下线，由「导演台2 / AI Media Studio」替代：后端为 `backend/app/media_studio/`（项目 / 内容库 / 资产库 / 剧集工坊 / 任务中心与 LLM、GRS、Comfy、七牛存储设置；`sql/013_media_studio_init.sql` 建 5 张 `ai_*` 新表，与旧 `xiaji_*` 表并存），前端为 `frontend/src/director2/`（路由 `/director2/projects/:projectId/:menu`、剧集工坊 `/director2/projects/:projectId/workshop/:episodeId`、设置页 `/director2/settings`）。旧 xiaji API 与 `/director2/art-styles`、`/director2/:projectId` 旧链接不再可用。详见 `docs/ARCHITECTURE.md` 与 `功能说明与扩展指南.md` 同日条目。
