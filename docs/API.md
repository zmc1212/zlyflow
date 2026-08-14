# ZLY AI Video Studio API 文档

更新日期：2026-08-11

## 使用方式

工作台监听本机与局域网 IPv4 地址的 `7865` 端口。启动 `启动本地视频工作台.bat` 后，以下三个地址由 FastAPI 自动从当前后端代码生成；其中 `127.0.0.1` 可替换为本机 IPv4 地址。

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:7865/api/docs` | Swagger UI，可在浏览器中填写参数、上传文件并直接发起请求。 |
| `http://127.0.0.1:7865/api/redoc` | ReDoc，只读浏览版。 |
| `http://127.0.0.1:7865/api/openapi.json` | OpenAPI 3.1 JSON，是接口定义的唯一来源，可供代码生成和第三方工具导入。 |

本项目采用 **FastAPI OpenAPI + Swagger UI/ReDoc** 作为主文档工具：它已随 FastAPI 提供，不增加部署服务，也能从 Pydantic 模型、参数校验和路由自动同步。若团队需要接口用例、自动化测试、Mock 或多人协作，可把 `/api/openapi.json` 下载为文件后导入 Apifox；不要在 Apifox 中单独维护另一份接口定义。

## 通用约定

- 所有业务接口以 `/api` 开头，响应为 JSON，媒体下载接口除外。
- 除 `/api/health`、`/api/auth/status`、`/api/auth/setup` 和 `/api/auth/login` 外，业务接口都需要 `zly_ai_video_studio_session` HttpOnly Cookie。所有写操作还需要登录响应中的 `csrf_token`，通过 `X-CSRF-Token` 请求头提交。
- 本机访问可使用 `http://127.0.0.1:7865`；局域网员工端的目录写入必须通过受信任 HTTPS。不得将 `7865` 直接暴露到公网。
- 创建任务使用 `multipart/form-data`，不是 JSON；`references` 可重复提交多个图片文件，上传顺序有业务含义。
- 单张参考图最大 50 MB，且 `Content-Type` 必须为 `image/*`。
- 创建任务成功返回 `202 Accepted`，表示已入队，并不代表图片或视频已经生成完成。
- 轮询间隔建议为 1-2 秒；任务终态为 `succeeded`、`failed` 或 `interrupted`。
- 通用错误格式为 `{"detail": "错误说明"}`。参数校验错误状态码为 `422`，资源不存在为 `404`，单个文件超过限制为 `413`。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 检查工作台和固定 ComfyUI 实例可用性。 |
| `GET` | `/api/auth/status` | 获取首次初始化或当前登录状态。 |
| `POST` | `/api/auth/setup` | 从工作站本机创建首位超级管理员。 |
| `POST` | `/api/auth/login` | 登录并设置 HttpOnly 会话 Cookie。 |
| `POST` | `/api/auth/logout` | 注销当前会话。 |
| `POST` | `/api/auth/password` | 修改当前密码；初始密码用户必须先调用。 |
| `GET/POST` | `/api/admin/users` | 管理员读取或创建员工账号。 |
| `PATCH` | `/api/admin/users/{user_id}` | 调整角色或启停账号。 |
| `POST` | `/api/admin/users/{user_id}/reset-password` | 重置初始密码并撤销该用户会话。 |
| `GET` | `/api/modes` | 获取工作流能力注册表、图片尺寸和提示词预设。 |
| `GET` | `/api/modes/{mode_id}` | 获取一个工作流在 `POST /api/jobs` 中的完整参数契约。 |
| `POST` | `/api/jobs` | 提交一个生成任务。 |
| `GET` | `/api/jobs` | 按创建时间倒序读取任务列表。 |
| `GET` | `/api/jobs/{job_id}` | 查询单个任务的进度、状态和输出。 |
| `GET` | `/api/library` | 列出当前用户已成功生成的资源元数据。 |
| `GET` | `/api/jobs/{job_id}/outputs/{output_index}/download` | 下载当前用户待交付的暂存资源。 |
| `POST` | `/api/jobs/{job_id}/outputs/{output_index}/delivered` | 确认浏览器已落盘并删除服务器暂存。 |
| `GET` | `/api/media/{filename}` | 兼容读取当前用户的旧版结果文件。 |

## 系统与工作流

### `GET /api/health`

用于启动检查。`webui` 为 `ok` 表示 API 进程可用；`comfy.reachable` 表示 `http://127.0.0.1:8188/system_stats` 是否可连接。

```json
{
  "webui": "ok",
  "comfy": {
    "reachable": true,
    "url": "http://127.0.0.1:8188",
    "error": null
  }
}
```

### `GET /api/modes`

前端或外部客户端应以此接口返回值为准，不硬编码模式、参考图数量或 H3 选项。每个 `modes[]` 项均包含 `parameters` 数组；数组的 `name` 是 `POST /api/jobs` 的表单字段名，`values` 为枚举值，`min_items`/`max_items` 描述参考图数量，`schema` 描述 `options` JSON 字符串解析后的对象。

| `id` | 参考图 | 说明 |
| --- | --- | --- |
| `image` | 0-1 | Flux2-Klein 文生图；支持 `negative_prompt` 和 `image_size`。 |
| `ltx-video` | 固定 3 张 | 场景、主体、风格三图生成首帧后制作 LTX 视频。 |
| `vace-video` | 固定 3 张 | 场景、主体、风格三图直接制作 Wan VACE 视频。 |
| `minimax-h3-t2v` | 0 张 | MiniMax H3 文生视频。 |
| `minimax-h3-i2v` | 1-2 张 | MiniMax H3 首帧必填，尾帧可选。 |
| `minimax-h3-r2v` | 1-9 张 | MiniMax H3 多参考视频；提示词以 `<Picture n>` 对应上传顺序。 |
| `minimax-h3-t8-all-reference` | 0-9 张 | H3 全能参考多速率工作流；`auto` 按图片数量选择 `T2VA`/`Ref2VA`。 |
| `minimax-h3-t8-dual-clock` | 0-1 张 | H3 双时钟采样工作流，默认 8 步。 |

### `GET /api/modes/{mode_id}`

返回指定模式的参数详情，适合外部客户端在选择工作流后动态创建表单。`mode_id` 可使用上表的任一 `id`，例如：

```text
GET /api/modes/minimax-h3-r2v
```

返回示例中的 `parameters` 可直接映射到提交接口：

```json
{
  "id": "minimax-h3-r2v",
  "request_content_type": "multipart/form-data",
  "parameters": [
    {"name": "mode", "type": "string", "required": true, "values": ["minimax-h3-r2v"]},
    {"name": "prompt", "type": "string", "required": true},
    {"name": "references", "type": "array", "required": true, "min_items": 1, "max_items": 9, "content_type": "image/*"},
    {
      "name": "options",
      "type": "string",
      "required": false,
      "default": "{}",
      "schema": {
        "type": "object",
        "properties": {
          "aspect_ratio": {"type": "string", "pattern": "^(?:\\d+(?:\\.\\d*)?|\\.\\d+)\\s*:\\s*(?:\\d+(?:\\.\\d*)?|\\.\\d+)$", "default": "16:9"},
          "megapixels": {"enum": [0.2, 0.3, 0.4, 0.5], "default": 0.2},
          "duration": {"minimum": 5, "maximum": 15, "default": 5}
        }
      }
    }
  ]
}
```

## 任务

### `POST /api/jobs`

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `mode` | string | 是 | 工作流 ID，必须是 `/api/modes` 的一个 `id`。 |
| `prompt` | string | 是 | 创作提示词。 |
| `negative_prompt` | string | 否 | 仅 `image` 模式生效，默认空字符串。 |
| `image_size` | string | `image` 时是 | `横版 1280 x 720`、`方图 1024 x 1024` 或 `竖版 720 x 1280`。 |
| `options` | string | 否 | JSON 字符串；仅 H3 模式使用，其他模式传 `{}`。 |
| `references` | file[] | 视模式而定 | 图片文件数组，字段名必须重复为 `references`。 |

H3 的 `options` 形如：

```json
{"aspect_ratio":"16:9","megapixels":0.2,"duration":5}
```

- `aspect_ratio`：任意有限正数的 `宽:高` 字符串，例如 `16:9`、`2:3`、`3:2` 或 `21:9`；必须放在 `options` JSON 字符串中，不是独立的 multipart 字段。
- `megapixels`：`0.2`、`0.3`、`0.4`、`0.5`。
- `duration`：5 到 15 秒。

两个 T8 模式也通过 `options` 提交参数，但字段更多。调用方必须以对应的 `GET /api/modes/{mode_id}` schema 为准；schema 包含 `type`、`enum`、`minimum`、`maximum`、`step`、`default`、`ui_group` 和可选 `unit`。`ui_group` 的语义为：`primary` 是创建页必要参数，`advanced` 进入“更多设置”，`internal` 由系统托管且不进入创建表单。未识别或缺失的层级应按 `internal` 处理。参数分为：

- 通用：`task_type`、`aspect_ratio`、`megapixels`、`multiple`、`duration`、`seed`。
- 音频与参考策略：`audio_mode`、`audio_denoise_strength`、`add_source_as_reference`、`prompt_primary_audio_ordinal`、`strict_prompt_tags`、`ref_image_size`、`reference_video_policy`。
- 采样：多速率模式的 `video_steps`/`audio_steps`，双时钟模式的 `steps`，以及两者共有的 `shift_video`/`shift_audio`。
- 模型与运行：模型、CLIP、VAE、LoRA、LoRA 强度、SageAttention；多速率模式另含预留显存参数。
- 输出：帧率、循环、H.264 像素格式、CRF、元数据、音频裁剪和 ping-pong。`filename_prefix` 与 `save_output` 由服务端固定。

### 按工作流提交参数

| `mode` | 必填字段 | 可选字段 | `references` 规则 |
| --- | --- | --- | --- |
| `image` | `mode`、`prompt`、`image_size` | `negative_prompt` | 0-1 张图片。 |
| `ltx-video` | `mode`、`prompt`、`references` | 无 | 固定 3 张，上传顺序为场景、主体、风格。 |
| `vace-video` | `mode`、`prompt`、`references` | 无 | 固定 3 张，上传顺序为场景、主体、风格。 |
| `minimax-h3-t2v` | `mode`、`prompt` | `options` | 不可上传参考图。 |
| `minimax-h3-i2v` | `mode`、`prompt`、`references` | `options` | 1-2 张；第一张首帧必填，第二张为可选尾帧。 |
| `minimax-h3-r2v` | `mode`、`prompt`、`references` | `options` | 1-9 张；`<Picture 1>` 对应第一张，依此类推。 |
| `minimax-h3-t8-all-reference` | `mode`、`prompt` | `options`、`references` | 0-9 张；`task_type=Ref2VA` 时至少 1 张。 |
| `minimax-h3-t8-dual-clock` | `mode`、`prompt` | `options`、`references` | 0-1 张；`task_type=Ref2VA` 时至少 1 张。 |

非 H3 工作流无需提交 `options`。原有 H3 模式未传时使用 `16:9`、`0.2 MP`、`5 秒`；T8 模式使用各自源工作流默认值。`GET /api/modes/{mode_id}` 是参数取值和约束的唯一来源。

使用 `curl.exe` 创建 H3 多参考任务的示例：

```powershell
curl.exe -X POST http://127.0.0.1:7865/api/jobs `
  -F "mode=minimax-h3-r2v" `
  -F "prompt=<Picture 1> 中的角色走进 <Picture 2> 的场景，镜头缓慢推进。" `
  -F "options={\"aspect_ratio\":\"16:9\",\"megapixels\":0.2,\"duration\":5}" `
  -F "references=@D:\素材\角色.png" `
  -F "references=@D:\素材\场景.png"
```

成功响应为 `202`：

```json
{
  "id": "WvhSEuCWne1d",
  "mode": "minimax-h3-r2v",
  "status": "queued",
  "stage": "等待排队",
  "progress": 0,
  "prompt": "<Picture 1> 中的角色走进 <Picture 2> 的场景，镜头缓慢推进。",
  "negative_prompt": "",
  "image_size": null,
  "options": {"aspect_ratio": "16:9", "megapixels": 0.2, "duration": 5, "reference_image_size": "match"},
  "reference_count": 2,
  "references": [
    {"index": 1, "url": "/api/jobs/WvhSEuCWne1d/references/1"},
    {"index": 2, "url": "/api/jobs/WvhSEuCWne1d/references/2"}
  ],
  "request_parameters": [
    {"name": "mode", "label": "工作流", "value": "minimax-h3-r2v", "visibility": "primary"},
    {"name": "prompt", "label": "创作提示词", "value": "<Picture 1> 中的角色走进 <Picture 2> 的场景，镜头缓慢推进。", "visibility": "primary"},
    {"name": "references", "label": "参考图", "value": 2, "visibility": "primary"},
    {"name": "options.aspect_ratio", "label": "画面比例", "value": "16:9", "visibility": "primary"},
    {"name": "options.megapixels", "label": "画质", "value": 0.2, "unit": "MP", "visibility": "advanced"},
    {"name": "options.duration", "label": "时长", "value": 5, "unit": "秒", "visibility": "primary"}
  ],
  "outputs": [],
  "error": null,
  "created_at": "2026-08-06T00:00:00+00:00",
  "updated_at": "2026-08-06T00:00:00+00:00"
}
```

### `GET /api/jobs` 和 `GET /api/jobs/{job_id}`

列表接口支持可选查询参数 `limit`，范围会被限制为 1-200，默认 100。单任务接口返回与创建任务相同的对象。`request_parameters` 由工作流注册表生成，回显任务实际使用的标准化有效值；`visibility` 与 option 的 `ui_group` 一致，用于区分创作参数和内部运行参数。参考图通过 `references` 预览 URL 回显。出于隐私和路径安全，响应中不包含上传素材的本地路径。

```powershell
Invoke-RestMethod http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d
```

任务成功时，`outputs` 包含媒体元数据：

```json
{
  "status": "succeeded",
  "stage": "生成完成",
  "progress": 100,
  "outputs": [
    {"kind": "video", "path": "minimax_h3_20260806_120000_a1b2c3d4.mp4", "label": "MiniMax H3 视频"}
  ],
  "error": null
}
```

任务失败时，`status` 为 `failed`，`error` 含后端或 ComfyUI 的错误摘要。

### `POST /api/jobs/{job_id}/retry`

当任务因 ComfyUI 或 FRP 连接中断而变为 `interrupted`，或已安全记录为 `failed` 时，确认 ComfyUI 已恢复后，可由任务所有者或管理员重新提交。接口只接受已清除 `prompt_id` 的终态任务，将其恢复为 `queued` 并重新加入单 worker 队列；仍在 ComfyUI 中执行的任务会返回 `409`，不会重复提交。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"} `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/retry
```

## 作品库与媒体

### `GET /api/library`

返回完成任务的输出，并补充 `results` 中尚未写入任务记录的历史文件。每项包含 `kind`、`path`、`label`、`job_id` 与 `created_at`；历史文件的 `job_id` 为 `null`。

### `GET /api/media/{filename}`

`filename` 必须是任务 `outputs[].path` 或作品库记录的 `path`。接口仅会读取 `results` 目录下的同名文件，路径片段会被剥离，不能借此读取任意文件。

```text
http://127.0.0.1:7865/api/media/minimax_h3_20260806_120000_a1b2c3d4.mp4
```

## Apifox 导入

1. 在浏览器打开 `http://127.0.0.1:7865/api/openapi.json` 并保存为 `zly-ai-video-studio-openapi.json`。
2. 在 Apifox 新建 HTTP 项目，选择“导入 OpenAPI/Swagger”，选择该 JSON 文件。
3. 后端路由或模型变更后，重新下载并用“智能合并”导入，或让 Apifox 指向受控的 OpenAPI 文件副本。

工作台仅面向本机和可信局域网，不要使用需要 Apifox 云端服务器访问本机 URL 的自动 URL 导入方式，也不要为导入而将 API 公开到互联网。

## 账号与资源交付约定

首次访问先读取 `GET /api/auth/status`。当 `setup_required=true` 时，只能从工作站本机提交：

```json
POST /api/auth/setup
{"username":"admin","display_name":"管理员","password":"至少十位的初始密码"}
```

登录和初始化响应包含 `user` 与 `csrf_token`，并通过 `Set-Cookie` 写入会话。非浏览器客户端必须同时维护 Cookie，并在 `POST/PATCH` 请求中发送 `X-CSRF-Token`。员工接口的任务列表、单任务、参考图、作品库和输出下载都会校验 `jobs.owner_user_id`；普通员工访问其他人的资源时按不存在处理。

成功任务的每个 `outputs[]` 包含 `delivery_status`。当状态为 `pending` 时还会返回短路径 `download_url`；浏览器将响应体写入员工授权目录后调用：

```text
POST /api/jobs/{job_id}/outputs/{output_index}/delivered
X-CSRF-Token: <login response csrf_token>
```

回执成功后 `delivery_status` 变为 `local`，`download_url` 变为 `null`，`data/staging` 暂存和固定 ComfyUI `output` 中记录的原始输出会同时删除。ComfyUI 清理目标必须是 `type=output` 且解析路径位于固定 `Comfyui/output` 根目录，否则回执失败并保留 ZLY AI Video Studio 暂存供重试。该操作表示调用方已经可靠落盘，不可在下载开始前提前调用。未来七牛云 provider 继续使用相同任务输出状态，云端对象定位由 provider 负责，不把七牛 SDK 参数暴露到任务接口。
