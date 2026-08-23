# ZLY AI Studio｜创作工作台

工作台使用 React + TypeScript 前端和 FastAPI 后端，在同一界面提供 GRS 图片生成与本机 ComfyUI 视频生成。工作台提供员工账号、角色权限、任务隔离、多轮创作和浏览器本地资源交付；监听本机与局域网 IPv4 地址的 `7865` 端口，ComfyUI 仍只使用 `http://127.0.0.1:8188`，不会暴露到局域网或公网。数据库文件名、环境变量前缀与包名继续保留 `zly-ai-video-studio` 兼容标识。

## 启动

1. 启动固定目录 `D:\zlyun\ZLY AI Video Studio\整合包及模型\comfyui-integrate-v1.3\comfyui-integrate\Comfyui` 下的 ComfyUI，默认地址为 `http://127.0.0.1:8188`。
2. 双击 `启动本地视频工作台.bat`。脚本会分别启动 FastAPI（`7865`）和 Vite 开发服务器（`5173`），并自动打开 `http://127.0.0.1:5173`；Vite 会显示在独立终端窗口，前端代码变更会自动热更新。首次使用前执行一次 `pnpm --dir frontend install`。
3. 首次打开时在工作站本机 `http://127.0.0.1:5173` 创建超级管理员，再由管理后台分配员工账号。
4. 员工首次登录并修改初始密码后，必须选择本机资源目录才能进入工作台；最新版 Chrome/Edge 仅在 HTTPS 或 `127.0.0.1` 安全上下文允许目录授权。
5. 若 7865 已被其他程序占用，请先确认或关闭该程序，再启动工作台。

### 启用 GRS 生图

1. 本地双击启动时，脚本会在首次运行自动创建 `data/credential.key` 并在后续启动中复用；该文件只用于加密数据库中的 GRS API Key，不得与数据库分开丢失。也可用环境变量 `ZLY_AI_VIDEO_STUDIO_CREDENTIAL_KEY` 显式覆盖。
2. Docker/服务器部署应生成 Fernet 主密钥并写入 `.env`：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`。主密钥缺少或错误时应用仍可启动，视频与历史不受影响，图片提交会锁定。
3. 以超级管理员进入“管理设置 → AI 供应商”，填写 GRS Base URL 与 API Key。连接测试会直接验证当前输入值，无需先保存；验证成功后仍需点击“保存配置”供图片任务使用。
4. 生图支持 GPT Image 2 / GPT Image 2 VIP、0–10 张有序参考图、每轮 1–4 张结果；真实测试会产生上游消耗，应先获得费用批准。

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

- GRS 图片生成：GPT Image 2 与 VIP；支持参考图、比例、1K/2K/4K、VIP 自定义尺寸、单轮 1–4 个并发生成项、部分成功和失败项重试。
- 图片与视频任务统一为“任务 → 轮次 → 生成项”；同任务不混合媒介，图片结果可创建有关联的新视频任务并预填首帧。
- MiniMax H3 提示词技能体系与大模型智能优化：结合 MiniMax-H3 官方开源技能规范（三维运镜语法、多模态时序结构、环境音效与背景配乐），融合 OpenAI 兼容大模型（如 ModelScope 免费模型），提供电影级通用、极简电商广告、3D动画短片、立体纸艺定格、品牌宣传、音乐短片、双人游戏片头、纸拼贴与手绘发光实景等 9 大细分风格技能的一键智能优化。
- MiniMax H3：文生视频、首尾帧视频，以及 1-9 张可排序参考图的视频生成；另接入“全能参考（多速率）”和“双时钟 8 步”工作流。新工作流的尺寸、时长、种子、采样、音频、模型、显存与编码参数由后端 schema 动态显示并在任务详情完整回显。

- 串行任务队列、任务状态、SQLite 任务记录与本地作品库。
- ComfyUI 或 FRP 短暂重启时，运行任务会在连续 30 秒无法通信后标记为“已中断”或安全失败，自动释放队列；恢复连接后可在任务详情点击“重新提交”，无需重启工作台镜像。
- 超级管理员、管理员、员工三级角色；员工仅可读取自己的任务、参考图和资源。
- 浏览器授权本地目录、生成完成后自动流式保存和交付回执。
- `ZLYUN AI` Windows 桌面客户端：为企业员工提供受控的本地目录交付、可靠本地预览和安装包更新基础；Web 工作台继续保留。

新作品写入员工授权目录的 `ZLY AI Studio/<YYYY-MM>`；既有 IndexedDB 记录和 `ZLY AI Video Studio` 目录继续只读兼容。GRS 图片成功 URL 会在后端校验 HTTPS、重定向、公网地址、MIME、文件签名和 50 MB 上限后暂存，浏览器/桌面端确认交付后立即清理。

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
