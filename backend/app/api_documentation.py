"""面向调用方的 OpenAPI 文档补充。

运行时接口仍以 FastAPI 路由、Pydantic 模型和工作流注册表为唯一事实来源；
本模块只为自动生成的 OpenAPI schema 补充业务语义、示例和安全说明，避免维护第二份接口文档。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FIELD_DOCUMENTATION: dict[str, tuple[str, str]] = {
    "access_key": ("七牛 Access Key", "七牛云对象存储的 Access Key；仅提交时使用，读取配置时不会返回原文。"),
    "accepts_image_size": ("支持画布尺寸", "该工作流是否接受 image_size 字段。"),
    "accepts_negative_prompt": ("支持负面提示词", "该工作流是否接受 negative_prompt 字段。"),
    "api_key": ("API 密钥", "供应商 API 密钥；仅在保存或测试连接时提交，接口不会回显原始值。"),
    "api_key_masked": ("已脱敏 API 密钥", "已保存 API 密钥的脱敏展示值；不含可用的完整密钥。"),
    "attach_images": ("是否附图", "当前写稿或分析路径是否会把参考图作为 image_url 发给模型；7B 等纯文本模型为 false。"),
    "authoring_vision": ("写稿看图路由", "工坊写稿、生成页优化、导演台最终润色使用的看图路径：LLM 名称可看图时走 LLM，否则走 VLM。"),
    "analysis_vision": ("分析看图路由", "资产反推、主体分析和复刻台拉片使用的看图路径：默认 VLM，VLM 未开且 LLM 可看图时回退 LLM。"),
    "available": ("当前可用", "当前配置及连通性是否允许使用该能力。"),
    "base_url": ("服务地址", "上游服务的 API 根地址，必须包含协议。"),
    "bucket": ("存储桶", "七牛云中用于保存交付文件的 Bucket 名称。"),
    "catalog_group": ("工作流分组 ID", "创作页工作流下拉的分组标识，例如 lightx2v、dual_accel、official_h3、custom。"),
    "catalog_group_label": ("工作流分组名称", "创作页工作流下拉展示的分组标题。"),
    "catalog_group_order": ("工作流分组顺序", "分组在下拉菜单中的排序，数值越小越靠前。"),
    "category": ("技能分类", "提示词技能所属的业务分类。"),
    "comfy": ("ComfyUI 健康状态", "固定 ComfyUI 实例的连接检测结果。"),
    "configured": ("已配置", "是否已填写该供应商所需的基础配置。"),
    "content_type": ("文件 MIME 类型", "数组文件字段允许上传的 MIME 类型；为空表示由接口另行校验。"),
    "created_at": ("创建时间", "记录创建时的 ISO 8601 时间字符串（UTC）。"),
    "credential_ready": ("凭据加密可用", "服务端用于加密保存供应商凭据的主密钥是否可用。"),
    "credits": ("剩余额度", "上游 GRS 账户当前可查询到的余额或点数。"),
    "cloud_url": ("云端资源地址", "对象存储上的稳定 HTTPS 地址，不含过期签名；任务 JSON 的 download_url 仍为同源下载路径。"),
    "csrf_token": ("CSRF 令牌", "登录后返回的防跨站请求伪造令牌；所有会改变服务端状态的 Cookie 会话请求须在 X-CSRF-Token 请求头中携带此值。"),
    "ctx": ("校验上下文", "字段校验失败时由验证器返回的附加上下文。"),
    "current_password": ("当前密码", "当前登录账号的密码；仅用于修改密码时核验，不会保存或回显。"),
    "default": ("默认值", "未传入此工作流参数时由服务端采用的默认值。"),
    "delivered_at": ("交付确认时间", "员工电脑确认收到资源的 ISO 8601 时间；未交付时为 null。"),
    "delivery": ("交付方式", "资源交付机制；browser-directory 表示由浏览器或桌面客户端写入员工已授权目录。"),
    "delivery_status": ("交付状态", "pending 表示待交付，local 表示已写入员工电脑且临时副本已清理，cloud 表示已持久化到云存储，expired 表示临时资源已过期。"),
    "description": ("说明", "面向调用方的业务说明。"),
    "detail": ("错误明细", "请求失败时的结构化校验错误列表。"),
    "display_name": ("显示名称", "在工作台界面展示的员工姓名或昵称。"),
    "domain": ("访问域名", "七牛云 Bucket 绑定的访问域名，须包含协议且可被员工浏览器访问。"),
    "download_url": ("临时下载地址", "当前用户或桌面客户端下载指定输出的临时地址；过期后须重新签发。"),
    "enabled": ("已启用", "是否启用该供应商或存储能力。"),
    "elapsed_ms": ("等待耗时（毫秒）", "从任务发起到进入终态的墙上时钟毫秒数；排队或生成中为 null，由前端按 created_at 实时计时。"),
    "error": ("错误信息", "生成项、轮次或任务失败时的错误摘要；成功时为 null。"),
    "extra": ("项目扩展字段", "导台2项目 settings_json.extra。skill_pack_id 绑定技能包配方；空或省略表示默认程序装箱。"),
    "execution_elapsed_ms": ("ComfyUI 推理耗时（毫秒）", "从 ComfyUI 历史记录 execution_start 到 execution_success 的推理耗时；没有历史时间戳时为 null。"),
    "executor": ("执行器", "实际执行任务的后端，例如 comfyui 或 grs。"),
    "finished_at": ("结束时间", "任务进入完成、失败、中断或停止等终态时的 ISO 8601 时间；进行中为 null。交付或改名不会覆盖此值。"),
    "expires_in_seconds": ("有效期（秒）", "临时下载凭证或地址从签发起的有效秒数。"),
    "free": ("是否免费", "该模型是否为免费项：来自上游 Free 标记、价格为 0，或硅基流动模型广场标价 0。"),
    "free_only": ("仅免费模型", "为 true 时只返回免费模型。硅基流动会再对照模型广场价格为 0 / Free 的条目。"),
    "generation_item_id": ("生成项 ID", "轮次中某个独立生成项的唯一标识。"),
    "generation_items": ("生成项列表", "该轮次拆分出的独立生成项及其状态、输出。"),
    "gpt_image_2_enabled": ("启用 GPT Image 2", "目录中 GPT Image 2 是否启用；完整目录以 /api/admin/providers/grs/models 为准。"),
    "gpt_image_2_vip_enabled": ("启用 GPT Image 2 VIP", "目录中 GPT Image 2 VIP 是否启用；完整目录以 /api/admin/providers/grs/models 为准。"),
    "grs": ("GRS 健康状态", "GRS 图片供应商的配置和可用性检测结果。"),
    "has_access_key": ("已配置 Access Key", "是否已保存七牛 Access Key；不会泄露具体内容。"),
    "has_api_key": ("已配置 API 密钥", "是否已保存供应商 API 密钥；不会泄露具体内容。"),
    "has_secret_key": ("已配置 Secret Key", "是否已保存七牛 Secret Key；不会泄露具体内容。"),
    "icon": ("图标", "前端展示该提示词技能时使用的图标标识。"),
    "id": ("ID", "该资源在工作台中的唯一标识。"),
    "image_urls": ("参考图地址", "提示词优化可选附图，最多 8 张 HTTP(S) 或 data URL；解析器可看图时带图调用，否则只把张数写入文字。"),
    "image_sizes": ("可用图片尺寸", "当前图片模式允许使用的画布尺寸列表。"),
    "index": ("序号", "从 1 开始的业务序号；参考图序号同时决定其在提示词中的对应顺序。"),
    "input": ("收到的值", "未通过校验的原始输入值。"),
    "builtin": ("内置模型", "是否来自工作台内置 GRS 文档目录；同步内置目录时不会覆盖已有项。"),
    "is_default": ("默认模型", "创作页生图工作流下拉的默认项；同一时间只有一个默认模型。"),
    "job_id": ("任务 ID", "生成任务的唯一标识。"),
    "kind": ("媒体类型", "输出媒体类型，例如 image 或 video。"),
    "label": ("显示名称", "面向界面或调用方展示的字段或媒体名称。"),
    "last_balance": ("最近余额", "最近一次成功查询到的 GRS 余额；从未查询过时为 null。"),
    "last_balance_at": ("余额查询时间", "最近一次成功查询余额的 ISO 8601 时间；未查询过时为 null。"),
    "last_login_at": ("最后登录时间", "账号最后一次成功登录的 ISO 8601 时间；从未登录时为 null。"),
    "last_test_at": ("最近测试时间", "最近一次连接测试的 ISO 8601 时间；尚未测试时为 null。"),
    "last_test_message": ("最近测试信息", "最近一次供应商连接测试返回的成功信息或错误摘要。"),
    "last_test_status": ("最近测试状态", "最近一次供应商连接测试的结果状态；尚未测试时为 null。"),
    "loc": ("错误位置", "校验失败字段在请求中的位置路径。"),
    "max_items": ("最多项目数", "数组字段允许的最大项目数量；null 表示未设置上限。"),
    "max_references": ("最多参考图数", "该工作流一次任务最多允许上传的参考图数量。"),
    "media_type": ("媒体类型", "任务或工作流生成的媒体类别：image 为图片，video 为视频。"),
    "message": ("状态说明", "当前服务、能力或操作结果的人类可读说明；无额外说明时为 null。"),
    "min_items": ("最少项目数", "数组字段必须提供的最少项目数量；null 表示未设置下限。"),
    "min_references": ("最少参考图数", "该工作流一次任务至少需要上传的参考图数量。"),
    "mode": ("工作流 ID", "本次生成使用的工作流标识；先通过 GET /api/modes 查询当前可用值和参数约束。"),
    "profile": ("能力档", "生图模型的参数能力档，决定比例、分辨率和是否支持自定义尺寸。"),
    "profiles": ("能力档列表", "管理后台可选择的 GRS 生图能力档及其显示名。"),
    "provider_model": ("上游模型 ID", "提交给 GRS /v1/api/generate 的 model 字段。"),
    "resolutions": ("分辨率列表", "该模型允许的分辨率档；为空时使用能力档默认值。"),
    "sort_order": ("排序", "管理目录和创作页工作流列表中的显示顺序，数值越小越靠前。"),
    "model": ("模型标识", "上游大模型服务使用的模型名称。"),
    "modes": ("工作流列表", "当前账号可见的生成工作流及其能力摘要。"),
    "msg": ("错误消息", "校验失败的人类可读原因。"),
    "must_change_password": ("需修改密码", "true 表示账号使用初始或重置密码，登录后必须修改密码。"),
    "name": ("名称", "资源、技能或工作流参数的机器可读名称。"),
    "negative_prompt": ("负面提示词", "希望图片避免出现的内容；仅支持该能力的图片工作流生效。"),
    "new_password": ("新密码", "要设置的新密码，长度须符合接口约束；不会保存或回显原文。"),
    "object_prefix": ("对象前缀", "七牛云对象键的统一前缀，用于隔离本工作台写入的资源。"),
    "optimized_prompt": ("优化后提示词", "大模型依据目标媒体、工作流和技能改写后的可直接使用提示词。"),
    "options": ("工作流参数 JSON", "JSON 对象字符串。字段、默认值、枚举和约束以 GET /api/modes/{mode_id} 返回的 parameters 中 options.schema 为准；不要传入未声明字段。"),
    "original_prompt": ("原始提示词", "提交给提示词优化接口的原文，便于调用方比对优化结果。"),
    "output_index": ("输出序号", "输出数组的从 0 开始索引。"),
    "outputs": ("输出列表", "该任务或生成项已经产生的媒体输出列表。"),
    "parameters": ("参数定义", "该工作流可提交字段的完整定义，包括必填、默认值、枚举和 JSON schema。"),
    "password": ("密码", "账号密码；仅用于注册、登录或重置，不会在任何响应中返回。"),
    "path": ("媒体文件名", "受控媒体文件名，可用于工作台媒体访问接口；不包含服务器本地绝对路径。"),
    "pinned": ("置顶", "是否在任务列表中将此任务置顶。"),
    "presets": ("提示词预设", "前端可直接使用的提示词预设名称与内容映射。"),
    "progress": ("进度百分比", "生成进度，范围为 0 到 100。"),
    "prompt": ("创作提示词", "描述希望生成内容的正向提示词；去除首尾空白后不能为空。"),
    "provider": ("资源提供方", "当前用于临时资源交付的存储提供方标识。"),
    "qiniu_compatible": ("支持七牛云", "当前资源交付配置是否兼容七牛云持久化存储。"),
    "queried_at": ("查询时间", "余额数据对应的 ISO 8601 查询时间。"),
    "reachable": ("可连接", "在超时时间内能否访问固定 ComfyUI 实例的 /system_stats。"),
    "reference_count": ("参考图数量", "本次任务或轮次实际保存的参考图数量。"),
    "reference_labels": ("参考图角色", "按上传顺序说明各参考图的业务角色，例如首帧、尾帧或角色参考。"),
    "reference_mode": ("参考图规则", "工作流对参考图的使用方式和顺序要求。"),
    "references": ("参考图文件", "multipart/form-data 中可重复提交的图片文件字段。数组顺序具有业务含义；数量和图片角色以所选工作流定义为准。"),
    "refresh_error": ("刷新失败原因", "最近一次后台刷新 GRS 余额失败的错误摘要；成功时为 null。"),
    "region": ("存储区域", "七牛云 Bucket 所在区域代码，例如 z0。"),
    "remote_task_id": ("上游任务 ID", "ComfyUI 或 GRS 等执行器返回的远端任务标识；尚未提交时为 null。"),
    "request_content_type": ("请求 Content-Type", "提交此工作流时必须使用的 HTTP Content-Type。"),
    "request_parameters": ("有效参数快照", "本任务实际生效的参数、显示名称和可见层级，用于复现与排障；未满足 ui_visible_when 的条件字段不回显。"),
    "required": ("是否必填", "该工作流字段是否必须在请求中提供。"),
    "role": ("账号角色", "super_admin 可管理全局配置和管理员；admin 可管理员工；employee 仅访问自己的任务和资源。"),
    "rounds": ("生成轮次", "同一任务下的历史生成轮次，按 sequence 递增。"),
    "schema": ("JSON 参数约束", "当字段以 JSON 字符串提交时，反序列化对象必须满足的 JSON Schema。"),
    "secret_key": ("七牛 Secret Key", "七牛云对象存储的 Secret Key；仅提交时使用，读取配置时不会返回原文。"),
    "sequence": ("轮次序号", "同一任务下从 1 开始递增的生成轮次序号。"),
    "setup_required": ("需要初始化", "是否尚未创建首位超级管理员；仅为 true 时可从工作站本机调用初始化接口。"),
    "skill_id": ("提示词技能 ID", "要应用的 MiniMax H3 提示词技能标识；null 表示使用通用优化。"),
    "skill_pack_id": ("技能包 ID", "导演台项目 extra.skill_pack_id 绑定的制作配方；空字符串表示默认程序装箱。不是生成页 H3 风格芯片。"),
    "skills": ("提示词技能列表", "当前可选的 MiniMax H3 提示词优化技能。"),
    "source": ("来源图片信息", "由图片转视频创建时，记录所引用的来源任务、生成项和输出序号。"),
    "source_generation_item_id": ("来源生成项 ID", "图片转视频时被引用图片所在的生成项 ID，须与 source_job_id 对应。"),
    "source_job_id": ("来源任务 ID", "图片转视频时被引用图片所在的图片任务 ID。"),
    "source_output_index": ("来源输出序号", "图片转视频时被引用图片在来源生成项输出数组中的从 0 开始索引。"),
    "style_id": ("画风 ID", "导演台画风目录中的唯一标识，例如 as_1001。"),
    "stage": ("处理阶段", "任务当前所在的执行阶段，例如 queued、uploading、generating 或 completed。"),
    "status": ("状态", "任务、轮次或生成项的状态：queued 排队中，running 处理中，succeeded 成功，failed 失败，interrupted 已中断，cancelled 用户已停止，partial 部分成功。"),
    "supports_vision": ("是否可看图", "GET /api/llm/status 中表示写稿路径能否附图（authoring_vision.attach_images），不再表示仅 VLM 是否启用。管理页 LLM/VLM 配置里仍表示当前模型名称是否可识别为视觉模型。"),
    "supports_timeline": ("支持 Timeline", "该视频工作流是否走 MiniMaxH3Director Timeline。"),
    "supports_multi_segment": ("支持多段 Timeline", "是否可一次提交多个镜头段；与 supports_timeline 同时为真时剧集工坊为一键整集直出。"),
    "temporary_server_staging": ("使用临时服务端暂存", "资源交付前是否先在服务端临时暂存；交付确认后可能被清理。"),
    "title": ("任务标题", "调用方为便于检索而设置的任务标题；最长 120 个字符，null 表示未设置。"),
    "type": ("字段类型", "工作流参数的基础 JSON 类型。"),
    "unavailable_reason": ("不可用原因", "当前能力不可用时返回的人类可读原因；可用时为 null。"),
    "use_llm_credentials": ("复用大模型凭据", "TTS 与 VLM 可选开关：为 true 时使用 LLM 页的 Base URL 与 API Key，模型名称仍在本页填写。VLM 默认关闭，以免覆盖已有智谱配置。"),
    "unit": ("单位", "参数展示时使用的可选单位，例如 秒。"),
    "updated_at": ("更新时间", "记录最后更新时的 ISO 8601 时间字符串（UTC）。"),
    "url": ("访问地址", "当前用户可访问的受控资源预览地址。"),
    "user": ("当前用户", "当前会话对应的用户资料；未登录时为 null。"),
    "username": ("账号名", "登录账号名；创建超级管理员时只能使用字母、数字、点、下划线和连字符。"),
    "value": ("有效值", "任务实际生效且已规范化的参数值。"),
    "values": ("可选值", "参数允许的枚举值；空数组表示不限制为枚举。"),
    "view_url": ("本机直连地址", "仅在浏览器与 ComfyUI 位于同一电脑且输出可直连时返回的受控 ComfyUI 查看地址。"),
    "visibility": ("参数层级", "primary 为常用创作参数，advanced 为更多设置，internal 为服务端内部参数。"),
    "webui": ("工作台状态", "工作台后端状态；正常时为 ok。"),
    "workflow_id": ("工作流 ID", "当前选择的生成工作流标识。"),
    "workflow_name": ("工作流名称", "当前选择工作流的展示名称，用于帮助大模型理解创作目标。"),
    "source_script": ("原始剧本", "导演工程保存的剧本文档原文；拆分后仍保留，不随弹窗关闭丢失。"),
    "style_vibe": ("风格基调", "拆分剧本时使用的影视风格，例如电影级或赛博朋克。"),
    "requested_shot_count": ("期望镜数", "拆分剧本时请求的分镜数量。"),
    "has_source_script": ("是否有原文", "工程是否已保存非空剧本文档。"),
    "shot_count": ("镜头数量", "时间轴中的分镜数量。"),
    "generated_count": ("已生成镜数", "至少有一条成功 Take 或成片的分镜数量。"),
    "generation_status": ("生成进度", "pending 待生成；partial 部分完成；complete 已完成。"),
    "payload": ("时间轴载荷", "分镜、主体槽、画幅等 JSON；服务端会剥离 data URL，参考图走上传目录。"),
    "imported": ("迁入数量", "本次迁库新写入的工程数量。"),
    "skipped": ("跳过数量", "因 ID 已存在而未重复写入的工程数量。"),
}


PATH_PARAMETER_DOCUMENTATION = {
    "job_id": "任务的唯一标识。只能访问当前登录用户拥有的任务。",
    "round_id": "任务下生成轮次的唯一标识，须属于 path 中的 job_id。",
    "generation_item_id": "轮次中生成项的唯一标识，须属于 path 中的 job_id。",
    "output_index": "输出数组从 0 开始的索引，必须落在对应任务或生成项的 outputs 范围内。",
    "reference_index": "参考图从 1 开始的上传顺序，顺序同时决定提示词中的图片对应关系。",
    "user_id": "员工账号的唯一标识。管理员只能修改其角色权限范围内的账号。",
    "mode_id": "工作流 ID；必须是 GET /api/modes 返回的 id 之一。",
    "style_id": "导演台画风目录中的唯一标识；必须是 GET /api/director/art-styles 返回的 id 之一。",
    "project_id": "导演工程的唯一标识。员工只能访问自己的工程；管理员按任务隔离规则可按 ID 读取。",
    "operation_id": "导演长操作的唯一标识；必须属于当前登录用户。",
    "asset_id": "员工级人物、场景或道具资产的唯一标识；员工只能访问自己的资产。",
    "shot_id": "导演工程内分镜的唯一标识，必须属于 path 中的 project_id。",
    "character_id": "导演工程内角色的唯一标识，必须属于 path 中的 project_id。",
    "slot": "分镜帧槽位；first 表示首帧，end 表示尾帧。",
    "kind": "可选资产类型筛选：character 人物、scene 场景或 prop 道具。",
    "filename": "受控媒体文件名，不接受目录路径。",
    "limit": "返回的最大任务数，服务端会限制到 1 至 200，默认 100。",
    "desktop_ticket": "ZLYUN AI 桌面客户端临时下载凭证。使用该参数时可不携带浏览器 Cookie，凭证过期后须重新签发。",
    "X-CSRF-Token": "登录响应中的 csrf_token。使用 Cookie 会话调用 POST、PUT、PATCH、DELETE 时必须携带。",
}


OPERATION_DETAILS: dict[tuple[str, str], str] = {
    ("get", "/api/auth/status"): "无需登录。用于判断是否需要初始化首位超级管理员，以及当前浏览器是否已有有效会话。",
    ("post", "/api/auth/setup"): "无需既有会话，但仅接受工作站本机回环请求，且仅在 setup_required 为 true 时成功。成功后会设置 HttpOnly 会话 Cookie 并返回 CSRF 令牌。",
    ("post", "/api/auth/login"): "无需既有会话。成功后服务端以 Set-Cookie 写入 HttpOnly 会话 Cookie；后续写操作还须携带响应中的 csrf_token。连续失败会受到登录限流保护。",
    ("post", "/api/auth/logout"): "需要已登录会话和 X-CSRF-Token。撤销当前会话并清除浏览器 Cookie。",
    ("post", "/api/auth/password"): "需要已登录会话和 X-CSRF-Token。校验当前密码后更新密码并换发会话 Cookie。",
    ("get", "/api/admin/users"): "需要管理员或超级管理员权限。返回可管理的账号列表；员工不能调用。",
    ("post", "/api/admin/users"): "需要管理员或超级管理员权限和 X-CSRF-Token。创建账号后，该账号首次登录必须修改密码。",
    ("patch", "/api/admin/users/{user_id}"): "需要管理员或超级管理员权限和 X-CSRF-Token。可按权限调整目标账号角色或启用状态。",
    ("post", "/api/admin/users/{user_id}/reset-password"): "需要管理员或超级管理员权限和 X-CSRF-Token。重置后目标账号必须在下次登录时修改密码。",
    ("get", "/api/storage"): "需要登录。返回当前环境的资源交付能力，供浏览器或桌面客户端选择交付流程。",
    ("get", "/api/health"): "无需登录。检查工作台、固定 ComfyUI 与 GRS 图片能力的可用性；不返回任何密钥。",
    ("get", "/api/modes"): "需要登录。获取当前注册的工作流摘要、提示词预设和图片尺寸能力；创建任务前应先调用。",
    ("get", "/api/modes/{mode_id}"): "需要登录。获取指定工作流在 POST /api/jobs 中可提交的字段、参考图数量和 options JSON Schema；这是动态工作流参数的唯一来源。",
    ("post", "/api/jobs"): "需要登录和 X-CSRF-Token。使用 multipart/form-data 创建任务，仅表示已入队（202）；随后轮询 GET /api/jobs/{job_id} 直至进入终态。references 可重复提交，上传顺序不能改变。options 是 JSON 对象字符串，例如 {\"aspect_ratio\":\"16:9\",\"duration\":5}。",
    ("post", "/api/jobs/{job_id}/rounds"): "需要登录和 X-CSRF-Token。为既有同媒介任务创建新的生成轮次，表单字段与创建任务相同；成功后返回更新后的任务。",
    ("post", "/api/jobs/{job_id}/rounds/{round_id}/retry-failed-items"): "需要登录和 X-CSRF-Token。仅重新入队该轮次中失败的生成项；没有失败项时返回 409。",
    ("get", "/api/jobs"): "需要登录。默认只返回当前用户的最近任务，使用 limit 控制数量。管理员和超级管理员可传 user_id 查看指定账号，或传 user_id=all 查看全部；员工传入该参数会被忽略。",
    ("get", "/api/jobs/{job_id}"): "需要登录。获取当前用户任务、轮次、生成项和输出的最新状态；推荐用于创建任务后的轮询。",
    ("patch", "/api/jobs/{job_id}"): "需要登录和 X-CSRF-Token。仅更新任务标题和置顶状态；未提供的字段保持不变。",
    ("delete", "/api/jobs/{job_id}"): "需要登录和 X-CSRF-Token。仅可删除已结束任务；排队中或运行中的任务返回 409。",
    ("post", "/api/jobs/{job_id}/retry"): "需要登录和 X-CSRF-Token。重新提交符合条件的 MiniMax H3 或 RTX 超分失败、中断或已停止任务；ComfyUI 恢复后中断视频也会自动重提，用户停止的任务不会自动重提。接口成功时返回 202。",
    ("post", "/api/jobs/{job_id}/upscale"): "需要登录和 X-CSRF-Token。对已成功的成片新建独立 nvidia-rtx-vsr 任务（固定 2x / ULTRA）。同一原片已有进行中的超分时返回 409；显存预估过大时返回 422。超分失败不影响原片。接口成功时返回 202。",
    ("post", "/api/jobs/{job_id}/cancel"): "需要登录和 X-CSRF-Token。停止排队中、生成中或已中断的任务。视频任务会向固定 ComfyUI 发送 interrupt 或从队列删除对应 prompt_id，并禁止自动重提。图片任务停止本地等待，云端 GRS 可能仍会继续。成功时返回更新后的任务。",
    ("get", "/api/jobs/{job_id}/references/{reference_index}"): "需要登录。以图片二进制流预览任务的指定参考图；reference_index 从 1 开始。",
    ("get", "/api/jobs/{job_id}/rounds/{round_id}/references/{reference_index}"): "需要登录。以图片二进制流预览指定历史轮次的参考图；reference_index 从 1 开始。",
    ("get", "/api/library"): "需要登录。返回当前用户已成功生成的所有可访问媒体及其交付信息。",
    ("get", "/api/media/{filename}"): "需要登录。下载或内联预览当前用户仍可访问的媒体文件；已交付到本地且被清理的临时资源返回 410。",
    ("get", "/api/jobs/{job_id}/outputs/{output_index}/download"): "需要登录，或携带有效 desktop_ticket。以二进制流下载任务顶层输出；资源交付并清理后返回 410。",
    ("get", "/api/jobs/{job_id}/outputs/{output_index}/browser-direct"): "需要登录。仅当浏览器与 ComfyUI 在同一电脑且资源支持直连时，返回受控的本机 ComfyUI 查看地址。",
    ("post", "/api/jobs/{job_id}/outputs/{output_index}/desktop-ticket"): "需要登录和 X-CSRF-Token。签发只绑定当前用户、任务和输出的短时桌面客户端下载凭证。",
    ("post", "/api/jobs/{job_id}/outputs/{output_index}/delivered"): "需要登录和 X-CSRF-Token。仅在客户端已成功写入员工电脑后调用；确认后会按当前存储策略清理临时副本。",
    ("get", "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/download"): "需要登录，或携带有效 desktop_ticket。以二进制流下载指定生成项输出。",
    ("get", "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/browser-direct"): "需要登录。返回指定生成项输出的同机 ComfyUI 直连地址；不支持时返回 409。",
    ("post", "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/desktop-ticket"): "需要登录和 X-CSRF-Token。为指定生成项输出签发短时且范围受限的桌面下载凭证。",
    ("post", "/api/jobs/{job_id}/generations/{generation_item_id}/outputs/{output_index}/delivered"): "需要登录和 X-CSRF-Token。确认指定生成项输出已写入员工电脑，并按当前存储策略清理临时副本。",
    ("get", "/api/director/art-styles"): "需要登录。返回 9 类 34 条画风目录；promptPrefix 对齐 OpenDirector 种子，imageUrl 为同源 /api/director/art-styles/{id}/preview。画风 id 必须选自该目录。",
    ("get", "/api/director/art-styles/{style_id}/preview"): "需要登录。返回画风 JPEG 预览。优先读本地缓存，缺失时由服务端从 OpenDirector CDN（files.seme.cc/styles/style_NN.jpg）拉取并缓存。未知 id 返回 404。",
    ("get", "/api/director/projects"): "需要登录。只返回当前用户的导演工程摘要，不含剧本文档和时间轴/Recipe payload。kind 为 timeline、director_recipe、batch_run、shot_replication 或 hypit_replication。",
    ("post", "/api/director/projects"): "需要登录和 X-CSRF-Token。创建导演工程，可同时写入 source_script 与 payload。payload.kind=director_recipe 时按 Recipe 校验画风目录；缺省 kind 为旧时间轴。服务端剥离 data URL。",
    ("post", "/api/director/projects/migrate"): "需要登录和 X-CSRF-Token。将浏览器 localStorage 中的导演工程一次性迁入 SQLite；相同 ID 跳过，避免重复。",
    ("get", "/api/director/projects/{project_id}"): "需要登录。读取当前用户的完整工程，包括 source_script 与 payload。无权访问时按 404 处理。",
    ("put", "/api/director/projects/{project_id}"): "需要登录和 X-CSRF-Token。更新标题、原文或 payload；未提交的字段保持不变。Recipe 的 artStyle 必须选自画风目录。",
    ("delete", "/api/director/projects/{project_id}"): "需要登录和 X-CSRF-Token。删除当前用户的导演工程。",
    ("post", "/api/director/projects/{project_id}/copy"): "需要登录和 X-CSRF-Token。复制工程到当前用户的项目库，生成新 ID 与「副本」标题。",
    ("post", "/api/director/projects/{project_id}/convert-to-recipe"): "需要登录和 X-CSRF-Token。将旧时间轴 payload 转为 Recipe（shots 映射为 scenes，主体槽映射为人物/场景）。已是 Recipe 时原样返回。批量任务返回 422。",
    ("post", "/api/director/recipes/run"): "需要登录和 X-CSRF-Token。用现有 LLM Provider 顺序跑 9 Agent，写入 Recipe payload。可选 agents 只跑指定步骤（例如 script+storyboard 按剧本一次生成全部分镜）。导演对话走 SSE 流式读取，连接超时 20 秒、分块空闲 300 秒，整段生成可超过 180 秒。运行中 payload.pipelineRun 记录本次步骤，agentStatus[].message 为人话阶段（读剧本/整理镜头），不回传模型思考原文。上游余额不足或欠费返回 HTTP 502，detail 含上游原文。可选 project_id 更新已有工程，否则新建。art_style_id 必须选自画风目录。",
    ("post", "/api/director/recipes/{project_id}/step"): "需要登录和 X-CSRF-Token。重跑单个 Agent。media 步只编译 H3 提示词，不调用大模型。",
    ("get", "/api/director/library-assets"): "需要登录。列出当前用户的员工级人物/场景/道具资产（图 + prompt）。可按 kind=character|scene|prop 筛选。跨工程复用靠此库，不建系列分集树。",
    ("post", "/api/director/library-assets"): "需要登录和 X-CSRF-Token。新建员工级资产。kind 为 character、scene 或 prop。",
    ("post", "/api/director/library-assets/from-recipe"): "需要登录和 X-CSRF-Token。把当前 Recipe 工程的人物/场景/道具快照写入资产库。character_ids / location_ids 为空时保存全部。",
    ("put", "/api/director/library-assets/{asset_id}"): "需要登录和 X-CSRF-Token。更新当前用户的资产名称、说明、提示词或图片引用。",
    ("delete", "/api/director/library-assets/{asset_id}"): "需要登录和 X-CSRF-Token。删除当前用户的资产及其上传图。",
    ("post", "/api/director/library-assets/{asset_id}/image"): "需要登录和 X-CSRF-Token。multipart 上传资产参考图，写入 data/uploads/{user}/library/{id}。",
    ("get", "/api/director/library-assets/{asset_id}/image"): "需要登录。读取当前用户资产参考图。",
    ("post", "/api/director/recipes/{project_id}/insert-library-assets"): "需要登录和 X-CSRF-Token。把选中的库资产复制进 Recipe：人物/道具进 characters（道具 type=object），场景进 locations。写入 libraryAssetId，不建立系列分集。",
    ("post", "/api/director/recipes/{project_id}/generate-assets"): "需要登录和 X-CSRF-Token。为角色/场景提交 GRS 定妆图任务，结果写入 imageJobId。",
    ("post", "/api/director/recipes/{project_id}/generate-stills"): "需要登录和 X-CSRF-Token。为分镜提交 GRS 静帧，提示词用本镜描述+画风，参考图复用人物/场景定妆。结果写入 stillJobId / stillUrl。",
    ("get", "/api/skill-packs"): "需要登录。列出导演台技能包配方（含空 id 的默认程序装箱，以及 summary、author、cover）。cover 仅为 http(s) 公开地址。首页新建导演工程与项目顶栏用此列表写入 extra.skill_pack_id。Plaza 短剧模板不是生成页 H3 风格芯片。未知 id 在创建/更新项目或优化提示词时返回 400。",
    ("post", "/api/projects"): "需要登录和 X-CSRF-Token。创建导台2项目。首页会先选技能包，extra.skill_pack_id 写入 settings_json.extra；空 id 或不传表示默认程序装箱。",
    ("put", "/api/projects/{project_id}"): "需要登录和 X-CSRF-Token。更新导台2项目。可单独提交 extra 合并进 settings.extra；只改 settings 时保留已有 extra。skill_pack_id 必须是 GET /api/skill-packs 中的 id。",
    ("get", "/api/projects/{project_id}/documents"): "需要登录。列出内容库文档。analysis.episodes 含程序切集结果：episode_num、body（本集 Markdown）、shots（出片镜，含 duration_sec）；规划成功时 shots_source=llm。进行中的镜头规划会带 shot_plan_job_id，文档 status 为 planning。",
    ("post", "/api/projects/{project_id}/documents"): "需要登录和 X-CSRF-Token。导入或粘贴剧本文档。JSON：raw_text，可选 filename / spine_template / visual_style / input_mode（缺省 paste）。程序按「# 第N集」切集（不改集号），每集写入 body 后立刻返回 200；粘贴/文件导入再入队 shot_plan 后台任务，响应带 shot_plan_job_id，文档 status=planning。input_mode=ai_pipeline 不入队。某集规划失败则保留解析器镜头并写入 analysis.logs。",
    ("post", "/api/projects/{project_id}/documents/{doc_id}/shot-plan"): "需要登录和 X-CSRF-Token。为未规划或规划失败的内容库文档入队 shot_plan 任务（与导入同一套）。AI 流水线文档或已全部 shots_source=llm 时返回 400。已有进行中任务则返回原 job_id 并标 duplicate。202 返回 job_id。",
    ("post", "/api/projects/{project_id}/documents/{doc_id}/transfer-episodes"): "需要登录和 X-CSRF-Token。把内容库该文档的分集/出片镜头写入剧集工坊。JSON {mode}：overwrite（缺省）重写已有集的 beats 并删除剧本里没有的旧集；append 只补尚未存在的集号。只拷贝文档里已有的出片镜，不再在同步时调大模型规划。",
    ("put", "/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}"): "需要登录和 X-CSRF-Token。更新当前分镜字段。可写 h3_prompt 与 h3_prompt_source（manual/generated）。手动保存的提示词出片按原文使用。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/h3-prompt"): "需要登录和 X-CSRF-Token。为当前分镜入队一个 h3_prompt 任务，不再按口型/内心/近景规则拆镜。未绑技能包时按 Beat 的动作/运镜/台词编译六段 Ref2VA（会剥掉动作里整段粘贴的台词，内心/旁白不作为开口对白）。绑定半解说包时由 LLM 一次写官方八块中文分秒稿（VLM/可看图 LLM 可用时看角色卡/场景卡/整张三联）和英文六段；配方临时 skip_program_pack=true 时出片英文用 GPT 六段原文（规范化 Picture/Subject 标签、六段 name: 标题，并在 detailed_description 补 [Shot 1]；内心改成官方 says in an off-screen voiceover 且 </d> 后闭嘴），不再程序灌水、中文时间码或轿厢句，也不走第二次装箱；同一人连续多句按问号/句号切开后逐字校验；内心若写成口型同步 says: 会先修补，修补后仍不合格则任务失败；中文分秒仍回写 timestamped_zh_prompt。中文或英文未通过校验则任务 failed，payload 含 author_errors / vision_* 与残稿，不覆盖 Beat，不回退无时间码骨架。R2V 为角色设定板+场景卡+三联起幅/中格/结果三张 9:16 裁切，不送整张 16:9 母图。设定板只锁身份/发型/服装，禁止抄分格、白底、重复小人。工坊若已有拆开的出片镜，payload.merge_as_one=true 则合并回一条再生成。h3_prompt_source=manual 的镜按原文出片。202 返回 job_id。生成过程可通过 GET /api/projects/{project_id}/jobs/{job_id}/events 直播思考与正文。",
    ("get", "/api/projects/{project_id}/jobs"): "需要登录。列出项目任务，含 image_generation / video_generation / h3_prompt / shot_plan / ai_pipeline / tts_generation。shot_plan 的 payload.document_id 用于跳回内容库该文档。",
    ("get", "/api/voice-bank"): "需要登录。返回内置短剧配音声线目录（IndexTTS 官方示例参考音 + 产品侧角色名）。",
    ("get", "/api/voice-bank/{preset_id}/audio"): "需要登录。读取内置声线 wav。未知 id 404。",
    ("post", "/api/projects/{project_id}/assets/{asset_id}/generate"): "需要登录和 X-CSRF-Token。JSON target_type：identity 为角色设定板（16:9、2K、2048x1152），不要求已有头像；无外观描述且无原片时 400。参考图：原片 > 其他已出图设定板（排除当前 look）> 仅当两档都没有时才用旧 avatar_url。avatar 仍可用但不在界面露出。头像/场景/道具分辨率仍为 1K。",
    ("post", "/api/projects/{project_id}/assets/{asset_id}/voice"): "需要登录和 X-CSRF-Token。multipart 上传角色参考音，写入 extra.voice.ref_audio_url。",
    ("post", "/api/projects/{project_id}/assets/{asset_id}/voice/preset"): "需要登录和 X-CSRF-Token。JSON {preset_id} 绑定内置短剧声线，写入 extra.voice.preset_id 与 ref_audio_url。",
    ("delete", "/api/projects/{project_id}/assets/{asset_id}/voice"): "需要登录和 X-CSRF-Token。清除角色参考音。",
    ("post", "/api/projects/{project_id}/assets/{asset_id}/voice/preview"): "需要登录和 X-CSRF-Token。按当前角色声线合成试听，写入 extra.voice.preview_url。",
    ("get", "/api/projects/{project_id}/assets/{asset_id}/voice/extract-sources"): "需要登录。列出该角色有开口对白且已有 H3 原片 video_url 的镜头，供框选提取参考音。只读解析 data_json，不回写 beats。",
    ("post", "/api/projects/{project_id}/assets/{asset_id}/voice/extract"): "需要登录和 X-CSRF-Token。JSON {episode_id, beat_id, start_sec, end_sec}，按用户框选的 1–15 秒从 H3 原片抽 16kHz mono wav，写入 extra.voice.ref_audio_url 并清空 preset_id。同步执行，不入队。缺区间/过短/过长/越界/无音轨/缺 ffmpeg 返回 400。",
    ("get", "/api/projects/{project_id}/episodes/{episode_id}/dubbing"): "需要登录。读取本集台词轨（Beat 开口/内心/旁白展开，合并已保存的 dubbing_lines）。响应含 compose_blocked / compose_block_reason：半解说包旁白未配音时合成禁用。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/dubbing/sync"): "需要登录和 X-CSRF-Token。从分镜同步台词轨并写回 beats[].dubbing_lines。",
    ("patch", "/api/projects/{project_id}/episodes/{episode_id}/dubbing/lines/{line_id}"): "需要登录和 X-CSRF-Token。更新单句配音导演参数。改文本会清空已生成音频。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/dubbing/generate"): "需要登录和 X-CSRF-Token。单句或批量入队 tts_generation。可选 line_id / line_ids；缺省本集全部。202 返回 job_id。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/generate-video"): "需要登录和 X-CSRF-Token。按当前工作流一键生成整集或逐镜视频。JSON 可带注册表 options，含 advanced 布尔 upscale_after。仅 render_scope=shot|selection 会在原片写入后自动 2x 超分；episode 整集直出和 compose 拼接片不自动超分。超分失败保留原片 video_url。202 返回 job_id。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-video"): "需要登录和 X-CSRF-Token。为单个 Beat 入队逐镜视频。可带 options.upscale_after；成片成功后先 POST /free 再跑 RTX 2x。原片写入 beat.video_url，超分写入 beat.upscaled_video_url。202 返回 job_id。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/compose"): "需要登录和 X-CSRF-Token。拼接各镜视频为分集成片。JSON 可选 mix_dubbing（缺省 true）：内心/旁白叠到成片，mix=replace 的开口句静音原声。半解说包旁白未配音时 400。202 返回 job_id。不因 upscale_after 自动超分。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/upscale"): "需要登录和 X-CSRF-Token。对本镜已成功的成片提交独立 2x 超分（RTX Video Super Resolution，固定 2x / ULTRA）。先 POST /free 卸载 H3。原片 video_url 不变，结果写入 beat.upscaled_video_url。同一镜头已有进行中的视频或超分时 409；无成片、相对当前连接 GPU 显存预估过大、或该 ComfyUI 未安装 RTXVideoSuperResolution 时 422。超分失败不影响原片。202 返回 job_id。整集直出和拼接片不会因 options.upscale_after 自动超分。",
    ("post", "/api/projects/{project_id}/jobs/{job_id}/upscale"): "需要登录和 X-CSRF-Token。对导演台2 已成功的 video_generation 成片提交独立 2x 超分。原片 result_url 不变，结果写入 payload.upscaled_video_url；有关联镜头时同时写 beat.upscaled_video_url。超分任务本身、未完成、多镜 selection 返回 422；同一成片进行中超分 409；相对当前连接 GPU 显存预估过大或未安装 RTXVideoSuperResolution 时 422。整集直出/拼接片可手动提交，过长可能被显存门闸拒绝。202 返回 job_id。",
    ("get", "/api/projects/{project_id}/jobs/{job_id}/events"): "需要登录。以 text/event-stream 按 job_type 推送任务事件。h3_prompt：status / reasoning / delta / done / error。shot_plan：status（第几集/共几集）/ reasoning / delta（本集 JSON 正文）/ episode_done（该集 shots 已写入 analysis_json）/ done / error。可带 since 或 Last-Event-ID 断点续传。",
    ("post", "/api/projects/{project_id}/episodes/{episode_id}/beats/{beat_id}/generate-triptych"): "需要登录和 X-CSRF-Token。为当前分镜入队 16:9 三联关键帧母图（内部三格 9:16）。参考图为选中造型设定板 + 场景卡；已有造型图时不再追加 avatar_url。完成后写入 beat.triptych_url，并裁切起幅/中格/结果到 triptych_panels.start|mid|end 供本地 H3 素材组使用；整张三联不作为 Picture n。202 返回 job_id。",
    ("post", "/api/projects/{project_id}/ai/operations"): "需要登录和 X-CSRF-Token。创建导台2 AI 生成操作；首期支持 clarify 创意澄清和 pipeline 剧本、资产文本、分集与 Beat 分镜流水线。",
    ("get", "/api/projects/{project_id}/ai/operations/{operation_id}"): "需要登录。读取当前用户导台2 AI 操作的阶段、进度、结果和错误。",
    ("get", "/api/projects/{project_id}/ai/operations/{operation_id}/events"): "需要登录。以 SSE 推送导台2 AI 操作的阶段进度、流式消息和终态事件。",
    ("post", "/api/projects/{project_id}/ai/operations/{operation_id}/cancel"): "需要登录和 X-CSRF-Token。取消尚未结束的导台2 AI 操作，已完成阶段的数据不会删除。",
    ("post", "/api/projects/{project_id}/ai/operations/{operation_id}/retry"): "需要登录和 X-CSRF-Token。无 body 时重试失败或已取消任务的当前阶段。可选 {stage} 从已完成的更早阶段重跑（failed/cancelled/awaiting_review/succeeded），该阶段之后不再算完成，需再次生成。stage=clarify 在同一条 pipeline 上重开开场问题。",
    ("post", "/api/projects/{project_id}/ai/operations/{operation_id}/advance"): "需要登录和 X-CSRF-Token。采纳当前 awaiting_review 阶段并启动下一阶段；最后一步采纳后任务成功结束。状态不符返回 400。",
    ("post", "/api/projects/{project_id}/ai/operations/{operation_id}/revise"): "需要登录和 X-CSRF-Token。对当前 awaiting_review 阶段提交 feedback，AI 为该阶段生成澄清问题并进入 revising。空反馈或状态不符返回 400。",
    ("post", "/api/projects/{project_id}/ai/operations/{operation_id}/rerun"): "需要登录和 X-CSRF-Token。提交 clarifications 后只重跑当前阶段，完成后回到 awaiting_review。状态不符返回 400。",
    ("post", "/api/director/recipes/{project_id}/frames"): "需要登录和 X-CSRF-Token。multipart 上传分镜首帧或尾帧（shot_id、slot=first|end、file）。写入 firstFrameUrl / endFrameUrl。",
    ("get", "/api/director/recipes/{project_id}/frames/{shot_id}/{slot}"): "需要登录。读取当前用户工程内已上传的分镜首帧或尾帧。",
    ("post", "/api/director/recipes/{project_id}/cover"): "需要登录和 X-CSRF-Token。multipart 上传剧本封面图（file，支持 PNG/JPG/WebP/GIF/BMP），写入 Recipe script.coverUrl，并保存到 data/uploads/{user}/{project}/cover.*。",
    ("get", "/api/director/recipes/{project_id}/cover"): "需要登录。读取当前用户工程的剧本封面图；未上传时返回 404。",
    ("delete", "/api/director/recipes/{project_id}/cover"): "需要登录和 X-CSRF-Token。移除剧本封面图；可传 expected_content_revision 防止覆盖其他窗口的更新。",
    ("post", "/api/director/recipes/{project_id}/render-shots"): "需要登录和 X-CSRF-Token。按镜编译 ≤9 张参考图，并按 payload.videoWorkflowFamily 提交该族 T2V/I2V/R2V。有 LLM 且 polish_prompt=true（默认）时先把镜头标为 queued 再润色 H3 提示词；polish_prompt=false 时直接使用当前提示词，润色完成才入队；GET 工程可见排队。未知 shot_ids 返回 422。有首帧或勾选上一镜尾帧时走 I2V/R2V。无定妆图且无首帧时走该族 T2V。缺省族为官方 MiniMax H3。",
    ("post", "/api/director/recipes/{project_id}/shots/{shot_id}/translate-prompt"): "需要登录和 X-CSRF-Token。把镜头中文正文（body 可选 text，缺省读镜头中文正文：promptTextZh 兼容字段，否则 description，规范化产生的标题占位不算中文正文）按官方 h3-prompt-writing skill 翻译为英文 H3 镜头正文，返回 {promptText} 不落库（由前端随工程保存写回）。LLM 未配置 503，缺中文正文 422，未知 shot 404。",
    ("get", "/api/director/export-capabilities"): "需要登录。返回本机是否找到 ffmpeg/ffprobe、TTS 是否可用，以及音色目录。不暴露密钥。",
    ("post", "/api/director/recipes/{project_id}/tts"): "需要登录和 X-CSRF-Token。按对白调用 OpenAI 兼容 /audio/speech 生成逐镜 TTS；character_id 时写角色试听。不使用 Edge TTS。",
    ("get", "/api/director/recipes/{project_id}/tts/{shot_id}"): "需要登录。读取当前用户工程内已生成的分镜 TTS 音频。",
    ("get", "/api/director/recipes/{project_id}/voices/{character_id}"): "需要登录。读取角色 TTS 试听音频。",
    ("post", "/api/director/recipes/{project_id}/bgm"): "需要登录和 X-CSRF-Token。multipart 上传配乐，写入 data/uploads/{user}/{project}/audio/。",
    ("get", "/api/director/recipes/{project_id}/bgm"): "需要登录。读取当前用户工程配乐。",
    ("post", "/api/director/recipes/{project_id}/mux"): "需要登录和 X-CSRF-Token。用本机 ffmpeg 按批准/成功镜头 concat，混 TTS 与 BGM，可选烧字幕。失败镜头不进入成片。未安装 ffmpeg 返回 503。",
    ("get", "/api/director/recipes/{project_id}/mux"): "需要登录。下载工作台内成片 MP4。",
    ("get", "/api/director/recipes/{project_id}/export.fcpxml"): "需要登录。下载 FCPXML 时间线（镜头入出点、对白、音频轨）。",
    ("get", "/api/director/recipes/{project_id}/export.edl"): "需要登录。下载 CMX 3600 EDL。",
    ("post", "/api/director/batches"): "需要登录和 X-CSRF-Token。主题裂变成多条脚本并并行排队所选工作流族的文生视频，不强制角色参考图。可选 video_workflow_family，缺省 official_h3。",
    ("post", "/api/director/batches/{project_id}/render"): "需要登录和 X-CSRF-Token。对已有批量工程按 item_ids 重新排队该工程所选工作流族的文生；空列表表示全部条目。",
    ("post", "/api/director/hypit/{project_id}/source-video"): "需要登录和 X-CSRF-Token。multipart 上传 Hypit 复刻参考片（mp4/mov/webm ≤2GB），写入 data/hypit/{user}/{project}/samples。与 VACE 复刻台 source-video 分离。",
    ("get", "/api/director/hypit/{project_id}/source"): "需要登录。读取 Hypit 复刻参考片。",
    ("get", "/api/director/hypit/{project_id}/transcript"): "需要登录。读取本机 WhisperX 转写 JSON。",
    ("get", "/api/director/hypit/{project_id}/result"): "需要登录。读取 Hypit CLI 编译成片。",
    ("post", "/api/director/hypit/{project_id}/reveal"): "需要登录和 X-CSRF-Token。在本机打开 data/hypit/{user}/{project}，供 Agent 改 SVML 后重跑。",
    ("post", "/api/director/hypit/{project_id}/operations"): "需要登录和 X-CSRF-Token。kind=hypit_transcribe 本机 WhisperX 拉片；kind=hypit_compile 子进程 hypit check/plan/build。不接受 analyze_reference_video / replicate_shots。H3 画面走 hypit.runtime.json 的 comfy.h3（默认 http://192.168.10.54:8188），不占用本机 8188。仅当该地址是回环时才 occupy_gpu(comfy)。画质读工程 payload.h3Quality（safe/balanced/official），编译时写入项目 runtime overlay 与 ZLY_HYPIT_H3_MEGAPIXELS。CLI 报告保留 Hypit 品牌。",
}


SUMMARY_TRANSLATIONS = {
    "Get Grs Provider": "获取 GRS 图片供应商配置",
    "Update Grs Provider": "更新 GRS 图片供应商配置",
    "Get Grs Balance Snapshot": "获取 GRS 余额快照",
    "Get Qiniu Provider": "获取七牛云存储配置",
    "Update Qiniu Provider": "更新七牛云存储配置",
    "Test Qiniu Provider": "测试七牛云存储连接",
    "Test Grs Provider": "测试 GRS 图片供应商连接",
    "Query Grs Balance": "查询 GRS 账户余额",
    "Preview a task reference image": "预览任务参考图",
    "Get Comfy Provider": "获取 ComfyUI 连接地址",
    "Update Comfy Provider": "更新 ComfyUI 连接地址",
    "Test Comfy Provider": "测试 ComfyUI 连接",
}


def _provider_operation_detail(method: str, path: str) -> str | None:
    if path.startswith("/api/admin/providers/"):
        if method == "get":
            return "需要超级管理员权限。读取供应商配置的公开状态；任何密钥字段均经过脱敏或仅返回是否已配置。"
        if path.endswith("/test"):
            return "需要超级管理员权限和 X-CSRF-Token。使用提交值（如有）测试供应商连接，不必先保存配置；测试结果会写入最近测试状态。"
        if path.endswith("/llm/models"):
            return "需要超级管理员权限和 X-CSRF-Token。向上游拉取完整模型目录；硅基流动按名称或标记中的 Free 文字筛选免费模型。"
        if path.endswith("/vlm/models"):
            return "需要超级管理员权限和 X-CSRF-Token。向上游拉取完整模型目录，再按名称筛选 VL/Vision 视觉模型；不默认只保留免费对话项。"
        if path.endswith("/balance"):
            return "需要超级管理员权限和 X-CSRF-Token。向上游查询当前 GRS 余额，并记录本次查询时间。"
        return "需要超级管理员权限和 X-CSRF-Token。保存供应商配置；敏感密钥会在服务端加密保存，响应不会返回原文。"
    if path == "/api/providers/grs/balance":
        return "需要登录。读取服务端缓存的 GRS 余额快照，并在可用时刷新；不会暴露供应商 API 密钥。"
    if path.startswith("/api/llm/"):
        if path.endswith("/skills"):
            return "需要登录。返回提示词优化可选择的 MiniMax H3 技能。"
        if path.endswith("/status"):
            return "需要登录。查询文本大模型是否已正确配置、当前是否可用；supports_vision 表示写稿路径能否附图（LLM 名称可看图或回退到已启用的 VLM），详见 authoring_vision / analysis_vision。"
        if path.endswith("/analyze-subject"):
            return "需要登录和 X-CSRF-Token。上传主体参考图提取外貌描述；默认走 VLM，VLM 未启用且 LLM 可看图时回退 LLM，否则 503。"
        if path.endswith("/split-script"):
            return "需要登录和 X-CSRF-Token。将剧本或故事拆成结构化分镜头，不会创建生成任务。"
        return "需要登录和 X-CSRF-Token。按目标媒体、工作流、可选 H3 风格技能和可选技能包优化提示词；可附带最多 8 张参考图 URL。写稿解析器可看图时带图优化，否则只写张数。不会创建生成任务。"
    if path.startswith("/api/vlm/"):
        return "需要登录。查询独立视觉模型是否已启用且可用。"
    return None


def _operation_description(method: str, path: str, summary: str) -> str:
    detail = OPERATION_DETAILS.get((method, path)) or _provider_operation_detail(method, path)
    if detail is None:
        detail = "需要已登录用户按其角色权限访问。"
    return f"{detail}\n\n**操作说明：** {summary}。\n\n**通用错误：** 401 表示未登录或会话/下载凭证失效；403 表示权限不足；404 表示当前用户无权访问或资源不存在；422 表示请求字段或业务规则不符合约束。"


def _add_examples(operation: dict[str, Any], method: str, path: str) -> None:
    if (method, path) == ("post", "/api/auth/login"):
        operation.setdefault("requestBody", {}).setdefault("content", {}).setdefault("application/json", {}).setdefault("example", {"username": "zhangsan", "password": "请使用真实密码"})
    elif (method, path) == ("post", "/api/llm/optimize-prompt"):
        operation.setdefault("requestBody", {}).setdefault("content", {}).setdefault("application/json", {}).setdefault("example", {"prompt": "雨夜城市中一辆汽车驶过霓虹灯", "media_type": "video", "workflow_id": "minimax-h3-t2v", "reference_count": 0, "image_urls": []})
    elif (method, path) == ("post", "/api/jobs"):
        content = operation.get("requestBody", {}).get("content", {}).get("multipart/form-data")
        if content is not None:
            content["example"] = {"mode": "minimax-h3-t2v", "prompt": "雨夜城市中一辆汽车驶过霓虹灯，电影感镜头", "options": "{\"aspect_ratio\": \"16:9\", \"duration\": 5}"}


def _document_enums(schema: dict[str, Any]) -> None:
    components = schema.get("components", {}).get("schemas", {})
    enum_descriptions = {
        "JobMode": "工作流 ID。当前实际可用工作流以 GET /api/modes 返回的 modes 为准；保留的历史值仅用于兼容旧任务。",
        "JobStatus": "任务状态：queued 排队中；running 执行中；succeeded 成功；failed 失败；interrupted 因服务中断等原因停止；cancelled 用户停止生成；partial 部分生成项成功。",
        "MediaType": "媒体类型：image 为图片，video 为视频。",
        "UserRole": "账号角色：super_admin 管理全局配置和管理员；admin 管理员工账号；employee 仅管理自己的创作任务和资源。",
    }
    for name, description in enum_descriptions.items():
        if name in components:
            components[name]["description"] = description


def enrich_openapi_documentation(schema: dict[str, Any]) -> dict[str, Any]:
    """在不改变 API 行为的前提下，补全 Swagger 和 ReDoc 使用的 OpenAPI 元数据。"""
    documented = deepcopy(schema)
    info = documented.setdefault("info", {})
    info["description"] = (
        "监听本机与局域网 IPv4 地址的 `7865` 端口的企业内网创作工作台 API。\n\n"
        "## 调用顺序\n"
        "1. 调用 `POST /api/auth/login` 登录；浏览器会自动保存 HttpOnly 会话 Cookie。\n"
        "2. 从登录响应读取 `csrf_token`；所有 `POST`、`PUT`、`PATCH`、`DELETE` 请求在 `X-CSRF-Token` 中携带它。\n"
        "3. 调用 `GET /api/modes` 与 `GET /api/modes/{mode_id}` 获取动态工作流字段和约束。\n"
        "4. 调用 `POST /api/jobs` 创建任务，收到 202 后轮询 `GET /api/jobs/{job_id}`。\n"
        "5. 通过下载/交付接口保存成功输出；确认交付会按存储策略清理临时副本。\n\n"
        "所有时间均为 ISO 8601 UTC 字符串。除健康检查、登录状态、初始化和登录接口外，业务接口都要求有效会话。"
    )
    for path, path_item in documented.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            summary = SUMMARY_TRANSLATIONS.get(operation.get("summary"), operation.get("summary") or "执行接口操作")
            operation["summary"] = summary
            operation["description"] = _operation_description(method, path, summary)
            for parameter in operation.get("parameters", []):
                name = parameter.get("name")
                if name in PATH_PARAMETER_DOCUMENTATION:
                    parameter["description"] = PATH_PARAMETER_DOCUMENTATION[name]
            if path not in {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login"}:
                operation["security"] = [{"APIKeyCookie": []}]
            _add_examples(operation, method, path)
    for component in documented.get("components", {}).get("schemas", {}).values():
        for property_name, property_schema in component.get("properties", {}).items():
            title, description = FIELD_DOCUMENTATION.get(
                property_name,
                (property_name, f"接口字段 `{property_name}` 的业务值；请结合所属响应或请求对象使用。"),
            )
            property_schema["title"] = title
            property_schema["description"] = description
    _document_enums(documented)
    return documented
