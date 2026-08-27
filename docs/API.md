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
- 轮询间隔建议为 1-2 秒；任务终态为 `succeeded`、`partial`、`failed`、`interrupted` 或 `cancelled`。
- 通用错误格式为 `{"detail": "错误说明"}`。参数校验错误状态码为 `422`，资源不存在为 `404`，单个文件超过限制为 `413`。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 检查工作台和当前配置的 ComfyUI 实例可用性。 |
| `GET` | `/api/auth/status` | 获取首次初始化或当前登录状态。 |
| `POST` | `/api/auth/setup` | 从工作站本机创建首位超级管理员。 |
| `POST` | `/api/auth/login` | 登录并设置 HttpOnly 会话 Cookie。 |
| `POST` | `/api/auth/logout` | 注销当前会话。 |
| `POST` | `/api/auth/password` | 修改当前密码；初始密码用户必须先调用。 |
| `GET/POST` | `/api/admin/users` | 管理员读取或创建员工账号。 |
| `PATCH` | `/api/admin/users/{user_id}` | 调整角色或启停账号。 |
| `POST` | `/api/admin/users/{user_id}/reset-password` | 重置初始密码并撤销该用户会话。 |
| `GET/PUT` | `/api/admin/providers/comfy` | 超级管理员读取或保存 ComfyUI 连接地址。 |
| `POST` | `/api/admin/providers/comfy/test` | 超级管理员测试当前输入的 ComfyUI 地址，不必先保存。 |
| `GET` | `/api/modes` | 获取工作流能力注册表、图片尺寸和提示词预设。 |
| `GET` | `/api/modes/{mode_id}` | 获取一个工作流在 `POST /api/jobs` 中的完整参数契约。 |
| `POST` | `/api/jobs` | 提交一个生成任务。 |
| `GET` | `/api/jobs` | 按创建时间倒序读取任务列表。 |
| `GET` | `/api/jobs/{job_id}` | 查询单个任务的进度、状态和输出。 |
| `POST` | `/api/jobs/{job_id}/cancel` | 停止排队中、生成中或已中断的任务。 |
| `GET` | `/api/library` | 列出当前用户已成功生成的资源元数据。 |
| `POST` | `/api/admin/providers/llm/models` | 超级管理员向上游拉取模型目录；硅基流动对照模型广场价格 0 / Free 筛选免费模型。 |
| `POST` | `/api/llm/optimize-prompt` | 按工作流/技能优化提示词，不创建生成任务。 |
| `POST` | `/api/llm/analyze-subject` | 上传主体参考图，由视觉模型提取外貌描述。 |
| `POST` | `/api/llm/split-script` | 将剧本拆成结构化分镜头脚本。 |
| `GET` | `/api/director/art-styles` | 读取 9 类 34 条画风目录。`imageUrl` 为同源预览地址。 |
| `GET` | `/api/director/art-styles/{style_id}/preview` | 读取画风 JPEG 预览（登录后，服务端缓存 OpenDirector CDN）。 |
| `GET` | `/api/director/projects` | 列出当前用户的导演工程摘要。 |
| `POST` | `/api/director/projects` | 创建导演工程，可带 `source_script` 与 Recipe/时间轴 payload。 |
| `POST` | `/api/director/projects/migrate` | 将浏览器 localStorage 工程迁入 SQLite；相同 ID 跳过。 |
| `GET` | `/api/director/projects/{project_id}` | 读取工程全文，含剧本原文与 payload。 |
| `PUT` | `/api/director/projects/{project_id}` | 更新标题、原文或 payload；`source_script` 可写空字符串清空。 |
| `DELETE` | `/api/director/projects/{project_id}` | 删除当前用户的导演工程。 |
| `POST` | `/api/director/projects/{project_id}/copy` | 复制工程到当前用户项目库。 |
| `POST` | `/api/director/projects/{project_id}/convert-to-recipe` | 将旧时间轴工程转为 Recipe。 |
| `POST` | `/api/director/recipes/run` | 启动 9 Agent 导演流水线，写入 Recipe。 |
| `POST` | `/api/director/recipes/{project_id}/step` | 重跑单个 Agent。 |
| `POST` | `/api/director/recipes/{project_id}/generate-assets` | 为角色/场景提交 GRS 定妆图。 |
| `POST` | `/api/director/recipes/{project_id}/render-shots` | 按镜提交所选工作流族的视频任务（T2V/I2V/R2V 仍自动匹配）。 |
| `POST` | `/api/director/batches` | 主题裂变多条脚本并并行排队所选工作流族的文生。 |
| `POST` | `/api/director/batches/{project_id}/render` | 对已有批量工程按 `item_ids` 重新排队 H3 文生。 |
| `GET` | `/api/jobs/{job_id}/outputs/{output_index}/download` | 下载当前用户待交付的暂存资源。 |
| `POST` | `/api/jobs/{job_id}/outputs/{output_index}/delivered` | 确认浏览器已落盘并删除服务器暂存。 |
| `GET` | `/api/media/{filename}` | 兼容读取当前用户的旧版结果文件。 |

## 系统与工作流

### `GET /api/health`

用于启动检查。`webui` 为 `ok` 表示 API 进程可用；`comfy.reachable` 表示当前配置的 ComfyUI `/system_stats` 是否可连接。默认地址为 `http://127.0.0.1:8188`，超级管理员可在管理后台覆盖。

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
| `minimax-h3-lightx2v-t2v` | 0 张 | LightX2V 文生；默认 1.0 MP、4 步 euler。 |
| `minimax-h3-lightx2v-i2v` | 1-2 张 | LightX2V 首帧必填，尾帧可选。 |
| `minimax-h3-lightx2v-r2v` | 1-9 张 | LightX2V 多参考；使用 Ref2V 4 步 LoRA，提示词 `<Picture n>`。 |
| `minimax-h3-dual-accel-t2v` | 0 张 | 八步双加速文生；默认 0.4 MP、8 步 `res_multistep`，FL2V 8 步 LoRA + KJ Sage + H3 Sage。 |
| `minimax-h3-dual-accel-i2v` | 1-2 张 | 八步双加速首尾帧；首帧必填，尾帧可选。 |
| `minimax-h3-dual-accel-r2v` | 1-9 张 | 八步双加速多参考；提示词 `<Picture n>`。 |
| `minimax-h3-t2v` | 0 张 | MiniMax H3 文生视频。 |
| `minimax-h3-i2v` | 1-2 张 | MiniMax H3 首帧必填，尾帧可选。 |
| `minimax-h3-r2v` | 1-9 张 | MiniMax H3 多参考视频；提示词以 `<Picture n>` 对应上传顺序。 |
| `minimax-h3-t8-all-reference` | 0-9 张 | H3 全能参考多速率工作流；`auto` 按图片数量选择 `T2VA`+FL2VA / `Ref2VA`+Ref2VA。快速/均衡挂 Turbo LoRA（全量 INT8）；高质量用 pruned 且不挂 LoRA。提示词使用 `<Picture n>`，也接受 `@图片n`。 |
| `minimax-h3-t8-dual-clock` | 0-1 张 | H3 双时钟采样工作流；无图文生，单图为首帧 I2VA，默认 8 步。 |

每个 mode 还包含 `catalog_group`、`catalog_group_label`、`catalog_group_order`。视频工作流分组为 `lightx2v`（LightX2V）、`dual_accel`（八步双加速）、`official_h3`（官方 MiniMax H3）、`custom`（自定义 T8）。前端按下拉分组展示，不硬编码组名。

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
          "duration": {"minimum": 2, "maximum": 15, "default": 5}
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
- `duration`：2 到 15 秒。实际输出帧数按 24fps、17n+5 网格向上对齐，因此 2 秒约为 56 帧（约 2.3 秒）。

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
| `minimax-h3-lightx2v-t2v` | `mode`、`prompt` | `options` | 不可上传参考图。 |
| `minimax-h3-lightx2v-i2v` | `mode`、`prompt`、`references` | `options` | 1-2 张；第一张首帧必填，第二张为可选尾帧。 |
| `minimax-h3-lightx2v-r2v` | `mode`、`prompt`、`references` | `options` | 1-9 张；`<Picture 1>` 对应第一张，依此类推。 |
| `minimax-h3-dual-accel-t2v` | `mode`、`prompt` | `options` | 不可上传参考图。 |
| `minimax-h3-dual-accel-i2v` | `mode`、`prompt`、`references` | `options` | 1-2 张；第一张首帧必填，第二张为可选尾帧。 |
| `minimax-h3-dual-accel-r2v` | `mode`、`prompt`、`references` | `options` | 1-9 张；`<Picture 1>` 对应第一张，依此类推。 |
| `minimax-h3-t8-all-reference` | `mode`、`prompt` | `options`、`references` | 0-9 张；`task_type=Ref2VA` 时至少 1 张。 |
| `minimax-h3-t8-dual-clock` | `mode`、`prompt` | `options`、`references` | 0-1 张；无图为 `T2VA`，单图为 `I2VA` 首帧。`task_type=Ref2VA` 时至少 1 张。 |

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

成功响应为 `202`。返回体是入队后的当前任务快照：worker 尚未领取时 `status` 为 `queued`；若 ComfyUI worker 已经开始准备或提交，则可能直接为 `running`。

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
  "options": {"aspect_ratio": "16:9", "quality": "0.2", "megapixels": 0.2, "duration": 5, "speed": "balanced", "reference_image_size": "match"},
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

列表接口支持可选查询参数 `limit`，范围会被限制为 1-200，默认 100。管理员和超级管理员还可传 `user_id`：指定账号 ID 只返回该用户任务，`all` 返回全部用户任务；员工传入该参数会被忽略，始终只看到自己的任务。单任务接口返回与创建任务相同的对象。`request_parameters` 由工作流注册表生成，回显任务实际使用的标准化有效值；`visibility` 与 option 的 `ui_group` 一致，用于区分创作参数和内部运行参数。带 `ui_visible_when` 的字段仅在条件成立时出现，例如未选自定义速度时不回显 `custom_steps`。参考图通过 `references` 预览 URL 回显。出于隐私和路径安全，响应中不包含上传素材的本地路径。

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

任务失败时，`status` 为 `failed`，`error` 含后端或 ComfyUI 的错误摘要。用户停止生成时，`status` 为 `cancelled`，不会自动重新提交。

### `POST /api/jobs/{job_id}/cancel`

任务所有者或管理员可停止排队中、生成中或已中断的任务。视频任务会向当前配置的 ComfyUI 发送 `/interrupt`（仅当该 `prompt_id` 正在运行）或从 `/queue` 删除排队项，并将任务标为 `cancelled`，禁止自动重提。图片任务只停止工作台等待，云端 GRS 可能仍会继续。已完成或已失败任务返回 `409`。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"} `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/cancel
```

### `POST /api/jobs/{job_id}/retry`

当任务因 ComfyUI 或 FRP 连接中断而变为 `interrupted`，或已安全记录为 `failed` / `cancelled` 时，任务所有者或管理员可调用本接口立即重试。工作台仍会在 ComfyUI 恢复后自动接回或重新提交中断的 H3 视频任务，但用户停止的 `cancelled` 任务不会自动重提。接口只接受已清除 `prompt_id` 的终态任务，将其恢复为 `queued` 并重新加入单 worker 队列；仍在 ComfyUI 中执行的任务会返回 `409`，不会重复提交。

```powershell
Invoke-RestMethod -Method Post `
  -Headers @{"X-CSRF-Token" = "<login response csrf_token>"} `
  http://127.0.0.1:7865/api/jobs/WvhSEuCWne1d/retry
```

## 导演台工程

导演工程与生成任务隔离，员工只能读写自己的记录。`POST /api/llm/split-script` 只即时返回分镜 JSON，不入库；前端把原文 `source_script` 与 shots 一并 `POST`/`PUT` 到 `/api/director/projects`。列表接口只返回 `has_source_script` 与 `kind`，不回传全文。手改空文案后 `PUT source_script` 仍会落盘。

`GET /api/director/art-styles` 返回 9 类 34 条画风（`id`、`name_zh`、`name_en`、`category`、`description`、`promptPrefix`、`imageUrl`、`keywords`）。`promptPrefix` 与 OpenDirector 公开种子一致。`imageUrl` 一律为同源 `/api/director/art-styles/{id}/preview`，浏览器不直连 `files.seme.cc`。`GET /api/director/art-styles/{style_id}/preview` 需要登录，优先返回本地缓存 JPEG；缺失时由服务端从 OpenDirector CDN（`style_01.jpg`–`style_34.jpg`）拉取并写入 `backend/app/director_catalog/previews/`。未知 id 返回 404。Recipe payload 的 `artStyle` 必须使用目录中的 id；保存时服务端用目录覆盖名称、`promptPrefix` 与预览地址，禁止自造风格。

`payload.kind`：缺省或旧数据为时间轴；`director_recipe` 含 `script`（title/summary/fullStory）、`artStyle`、`characters`、`locations`、`scenes[].shots`、`agentStatus`；`batch_run` 为批量主题裂变。`POST /api/director/projects/{project_id}/convert-to-recipe` 把时间轴 shots 映射为 scenes，不自动改写未请求转换的旧工程。

导演主路径不再走 `POST /api/llm/split-script`（该接口仍保留给兼容/测试，拆分时同样读取 MiniMax H3 官方 `h3-prompt-writing` 原文）。`POST /api/director/recipes/run` 顺序调用研究/脚本/画风/分镜/角色/场景/配音/配乐/媒体 9 个 Agent，复用现有 LLM Provider；分镜 Agent 读取官方 skill 与 `base-en.txt`，同时生成中文 `description`（界面展示）和英文 `promptText`（官方镜头正文）。媒体编译把 T2V/I2V 写成 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music`，把 R2V 写成 Ref2VA 六段式。画风只能选自目录。每个 Agent 开始时把 `payload.agentStatus` 写成 `running` 并落盘，因此运行中 `GET /api/director/projects/{id}` 可看到当前步；整次 POST 仍等全部 Agent 结束后才返回。`generate-assets` 为角色和场景提交 GRS 生图任务；运行中 `GET /api/jobs` 的 `progress` 按约 2 分钟预期映射到 12–90%，完成时 100%。启用七牛云时，定妆输出会转存对象存储，任务带稳定 `cloud_url`（不含过期签名），并写入 Recipe 的 `imageUrl`；`download_url` 仍为同源 `/api/jobs/.../download`。`render-shots` 把本镜用到的定妆图编成最多 9 张 `<Picture n>` 参考图，再按 Recipe 的 `videoWorkflowFamily` 提交该族 T2V/I2V/R2V（缺省 `official_h3`，有图走该族 R2V，无图走该族 T2V）；云端定妆会先拉到暂存再作为参考。`POST /api/director/batches` 把主题裂变成多条脚本并并行排队所选工作流族的文生（`video_workflow_family`，缺省官方 H3），不强制角色参考。`POST /api/director/batches/{project_id}/render` 对已有批量条目重新排队；`item_ids` 为空时提交全部条目。

导演台提交 `POST /api/jobs` 时：预览/成片各自读取工程 payload 的 `previewQuality`/`previewSpeed` 与 `finalQuality`/`finalSpeed`。默认预览 `quality=0.4`、`speed=fast`；默认成片 `quality=1.0`、`speed=balanced`。可选 MP 为 0.4 / 0.7 / 1.0 / 2.0，速度为 fast（4 步）/ balanced（8 步）/ quality（20 步）。旧工程无新字段时，成片 MP 仍跟 `canvasTier`。批量接龙与整段提交使用成片档。

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

任务的每个 `outputs[]` 包含 `delivery_status`。只要输出尚未本地交付（`pending` 或 `cloud`），就会返回短路径 `download_url`，包括部分完成或失败但已落盘的图片；启用七牛云时另有稳定 `cloud_url`（对象域名+键，不含过期签名）。浏览器将响应体写入员工授权目录后调用：

```text
POST /api/jobs/{job_id}/outputs/{output_index}/delivered
X-CSRF-Token: <login response csrf_token>
```

回执成功后 `delivery_status` 变为 `local`，`download_url` 变为 `null`，`data/staging` 暂存和固定 ComfyUI `output` 中记录的原始输出会同时删除。ComfyUI 清理目标必须是 `type=output` 且解析路径位于固定 `Comfyui/output` 根目录，否则回执失败并保留 ZLY AI Video Studio 暂存供重试。该操作表示调用方已经可靠落盘，不可在下载开始前提前调用。未来七牛云 provider 继续使用相同任务输出状态，云端对象定位由 provider 负责，不把七牛 SDK 参数暴露到任务接口。
