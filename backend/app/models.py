from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class JobMode(str, Enum):
    # Retain removed values so existing SQLite job history can still be serialized.
    IMAGE = "image"
    LTX_VIDEO = "ltx-video"
    VACE_VIDEO = "vace-video"
    MINIMAX_H3_T2V = "minimax-h3-t2v"
    MINIMAX_H3_I2V = "minimax-h3-i2v"
    MINIMAX_H3_R2V = "minimax-h3-r2v"
    MINIMAX_H3_LIGHTX2V_T2V = "minimax-h3-lightx2v-t2v"
    MINIMAX_H3_LIGHTX2V_I2V = "minimax-h3-lightx2v-i2v"
    MINIMAX_H3_LIGHTX2V_R2V = "minimax-h3-lightx2v-r2v"
    MINIMAX_H3_DUAL_ACCEL_T2V = "minimax-h3-dual-accel-t2v"
    MINIMAX_H3_DUAL_ACCEL_I2V = "minimax-h3-dual-accel-i2v"
    MINIMAX_H3_DUAL_ACCEL_R2V = "minimax-h3-dual-accel-r2v"
    MINIMAX_H3_T8_ALL_REFERENCE = "minimax-h3-t8-all-reference"
    MINIMAX_H3_T8_DUAL_CLOCK = "minimax-h3-t8-dual-clock"
    GRS_GPT_IMAGE_2 = "grs-gpt-image-2"
    GRS_GPT_IMAGE_2_VIP = "grs-gpt-image-2-vip"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    EMPLOYEE = "employee"


class MediaOutput(BaseModel):
    kind: str = Field(description="媒体类型，例如 image 或 video。")
    path: str = Field(description="结果文件名；通过 /api/media/{filename} 下载或预览。")
    label: str = Field(description="面向界面的媒体名称。")
    delivery_status: Literal["pending", "local", "cloud", "expired"] = Field(
        default="pending", description="资源交付状态；local 表示服务器暂存副本已清理。",
    )
    download_url: str | None = Field(default=None, description="当前用户可访问的临时交付 URL。")
    delivered_at: str | None = None


class JobReference(BaseModel):
    index: int = Field(ge=1, description="Reference image upload order within the job.")
    url: str = Field(description="Reference image preview URL.")


class JobRequestParameter(BaseModel):
    name: str = Field(description="Original request field name, including nested options keys.")
    label: str = Field(description="Display label derived from the workflow registry.")
    value: str | int | float | bool = Field(description="Normalized effective value used by this task.")
    unit: str | None = Field(default=None, description="Optional display unit from the workflow registry.")
    visibility: Literal["primary", "advanced", "internal"] = Field(
        default="primary", description="Workbench display tier from the workflow registry."
    )


class GenerationItemResponse(BaseModel):
    id: str
    index: int = Field(ge=1)
    executor: str
    status: JobStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    outputs: list[MediaOutput] = Field(default_factory=list)
    error: str | None = None
    remote_task_id: str | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0, description="从发起到结束的等待毫秒数；进行中为 null。")
    execution_elapsed_ms: int | None = Field(default=None, ge=0, description="ComfyUI 历史记录中的推理耗时毫秒数；没有时为 null。")


class JobRoundResponse(BaseModel):
    id: str
    sequence: int = Field(ge=1)
    mode: str
    media_type: MediaType
    status: JobStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    prompt: str
    negative_prompt: str = ""
    image_size: str | None = None
    options: dict = Field(default_factory=dict)
    reference_count: int
    references: list[JobReference] = Field(default_factory=list)
    request_parameters: list[JobRequestParameter] = Field(default_factory=list)
    generation_items: list[GenerationItemResponse] = Field(default_factory=list)
    error: str | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0, description="从发起到结束的等待毫秒数；进行中为 null。")
    execution_elapsed_ms: int | None = Field(default=None, ge=0, description="ComfyUI 历史记录中的推理耗时毫秒数；没有时为 null。")


class JobSourceResponse(BaseModel):
    job_id: str
    generation_item_id: str | None = None
    output_index: int | None = None


class JobResponse(BaseModel):
    id: str
    mode: str
    status: JobStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    prompt: str
    negative_prompt: str
    image_size: str | None = None
    options: dict = Field(default_factory=dict)
    reference_count: int
    references: list[JobReference] = Field(default_factory=list)
    request_parameters: list[JobRequestParameter] = Field(default_factory=list)
    outputs: list[MediaOutput]
    error: str | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0, description="从发起到结束的等待毫秒数；进行中为 null。")
    execution_elapsed_ms: int | None = Field(default=None, ge=0, description="ComfyUI 历史记录中的推理耗时毫秒数；没有时为 null。")
    media_type: MediaType = MediaType.VIDEO
    title: str | None = None
    pinned: bool = False
    rounds: list[JobRoundResponse] = Field(default_factory=list)
    source: JobSourceResponse | None = None


class JobMetadataUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None


class AuthStatusResponse(BaseModel):
    setup_required: bool
    authenticated: bool
    user: UserResponse | None = None
    csrf_token: str | None = None


class SetupAdminRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class CreateUserRequest(SetupAdminRequest):
    role: UserRole = UserRole.EMPLOYEE


class UpdateUserRequest(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class StorageCapabilityResponse(BaseModel):
    provider: str
    delivery: Literal["browser-directory"]
    temporary_server_staging: bool
    requires_local_directory: bool = Field(description="当前交付方式是否要求浏览器授权员工电脑上的本地目录。")
    qiniu_compatible: bool


class DesktopDeliveryTicketResponse(BaseModel):
    download_url: str = Field(description="仅供 ZLYUN AI 客户端在短时间内下载当前输出的临时地址。")
    expires_in_seconds: int = Field(description="临时下载地址的有效秒数。")


class WorkflowParameterResponse(BaseModel):
    name: str = Field(description="multipart/form-data 字段名。")
    label: str = Field(description="面向调用方的字段名称。")
    type: Literal["string", "number", "integer", "boolean", "array"] = Field(description="字段基础类型。")
    required: bool
    description: str
    default: str | int | float | bool | None = None
    values: list[str | int | float] = Field(default_factory=list, description="可选枚举值；空数组表示不限制为枚举。")
    min_items: int | None = Field(default=None, description="数组字段的最少项目数。")
    max_items: int | None = Field(default=None, description="数组字段的最多项目数。")
    content_type: str | None = Field(default=None, description="文件数组允许的 MIME 类型。")
    json_schema: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="JSON 字符串字段反序列化后的对象约束。",
    )


class ModeResponse(BaseModel):
    id: str
    name: str
    description: str
    reference_mode: str
    min_references: int
    max_references: int
    reference_labels: list[str] = Field(default_factory=list)
    accepts_negative_prompt: bool
    accepts_image_size: bool
    supports_h3_options: bool = False
    request_content_type: str = "multipart/form-data"
    parameters: list[WorkflowParameterResponse] = Field(default_factory=list)
    media_type: MediaType = MediaType.VIDEO
    executor: str = "comfyui"
    available: bool = True
    unavailable_reason: str | None = None
    catalog_group: str = ""
    catalog_group_label: str = ""
    catalog_group_order: int = 100


class ComfyHealthResponse(BaseModel):
    reachable: bool = Field(description="ComfyUI 的 /system_stats 是否在超时时间内可访问。")
    url: str = Field(description="当前生效的 ComfyUI 地址。")
    error: str | None = Field(default=None, description="连接失败时的错误摘要。")


class GrsHealthResponse(BaseModel):
    configured: bool
    enabled: bool
    credential_ready: bool
    available: bool
    last_test_status: str | None = None
    last_test_at: str | None = None
    message: str | None = None


class HealthResponse(BaseModel):
    webui: str = Field(description="工作台后端状态；正常时为 ok。")
    comfy: ComfyHealthResponse
    grs: GrsHealthResponse


class ComfyProviderUpdateRequest(BaseModel):
    base_url: str = Field(default="http://127.0.0.1:8188", min_length=8, max_length=500)


class ComfyProviderTestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)


class ComfyProviderResponse(BaseModel):
    base_url: str
    env_default: str
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class GrsProviderUpdateRequest(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="https://grsai.dakka.com.cn", min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=4096)


class GrsProviderTestRequest(BaseModel):
    base_url: str = Field(default="https://grsai.dakka.com.cn", min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=4096)


class GrsProviderResponse(BaseModel):
    enabled: bool
    base_url: str
    api_key_masked: str | None = None
    has_api_key: bool
    credential_ready: bool
    gpt_image_2_enabled: bool
    gpt_image_2_vip_enabled: bool
    models: str
    vip_models: str
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None
    last_balance: float | None = None
    last_balance_at: str | None = None
    available: bool
    unavailable_reason: str | None = None


class QiniuProviderUpdateRequest(BaseModel):
    enabled: bool = False
    access_key: str | None = Field(default=None, max_length=512)
    secret_key: str | None = Field(default=None, max_length=512)
    bucket: str = Field(default="", max_length=256)
    region: str = Field(default="z0", max_length=32)
    domain: str = Field(default="", max_length=500)
    object_prefix: str = Field(default="zly-ai-video-studio/", max_length=500)


class QiniuProviderResponse(BaseModel):
    enabled: bool
    bucket: str
    region: str
    domain: str
    object_prefix: str
    has_access_key: bool
    has_secret_key: bool
    credential_ready: bool
    available: bool
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class GrsImageModelResponse(BaseModel):
    workflow_id: str
    provider_model: str
    display_name: str
    description: str = ""
    profile: str
    resolutions: list[str] | None = None
    enabled: bool
    sort_order: int
    is_default: bool
    builtin: bool


class GrsImageModelUpdateItem(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    sort_order: int = Field(default=100, ge=0, le=10000)
    is_default: bool = False


class GrsImageModelsUpdateRequest(BaseModel):
    models: list[GrsImageModelUpdateItem] = Field(min_length=1)


class GrsImageModelCreateRequest(BaseModel):
    provider_model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    profile: Literal["gpt_image_2", "gpt_image_2_vip", "nano_banana", "nano_banana_2"]
    resolutions: list[str] | None = None
    enabled: bool = True


class GrsImageModelsResponse(BaseModel):
    models: list[GrsImageModelResponse]
    profiles: list[dict[str, str]]


class GrsBalanceResponse(BaseModel):
    credits: float
    queried_at: str


class GrsBalanceSnapshotResponse(BaseModel):
    credits: float | None = None
    queried_at: str | None = None
    refresh_error: str | None = None


class BrowserDirectOutputResponse(BaseModel):
    view_url: str = Field(description="An authorized local ComfyUI output URL for the current browser.")


class ModesResponse(BaseModel):
    modes: list[ModeResponse]
    image_sizes: list[str] = Field(description="image 模式允许的画布尺寸。")
    presets: dict[str, str] = Field(description="前端可直接使用的提示词预设。")


class LibraryItemResponse(MediaOutput):
    job_id: str | None = Field(description="来源任务 ID；扫描到的历史文件为 null。")
    generation_item_id: str | None = None
    output_index: int | None = None
    created_at: str = Field(description="创建时间；任务记录为 ISO 8601，历史文件为 Unix 时间戳字符串。")


class LlmProviderUpdateRequest(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="https://api-inference.modelscope.cn/v1", max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str = Field(default="Qwen/Qwen2.5-72B-Instruct", max_length=128)


class LlmProviderTestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)


class LlmModelCatalogRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    free_only: bool = True


class LlmCatalogModel(BaseModel):
    id: str
    label: str
    free: bool | None = None
    owned_by: str | None = None


class LlmModelCatalogResponse(BaseModel):
    models: list[LlmCatalogModel]
    provider: str
    free_only: bool
    message: str | None = None


class LlmProviderResponse(BaseModel):
    enabled: bool
    base_url: str
    model: str
    api_key_masked: str | None = None
    has_api_key: bool
    credential_ready: bool
    available: bool
    unavailable_reason: str | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None
    supports_vision: bool = False


class LlmStatusResponse(BaseModel):
    available: bool
    message: str | None = None
    supports_vision: bool = False
    model: str | None = None


class PromptOptimizeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000, description="待优化的原始创意或提示词")
    media_type: Literal["video", "image"] = Field(default="video", description="生成目标媒体类型")
    workflow_name: str | None = Field(default=None, max_length=128, description="当前选择的工作流名称")
    skill_id: str | None = Field(default=None, max_length=64, description="指定 MiniMax 技能风格 ID")
    reference_count: int | None = Field(default=0, ge=0, le=10, description="当前参考图数量")
    workflow_id: str | None = Field(default=None, max_length=64, description="当前工作流 ID")


class PromptOptimizeResponse(BaseModel):
    original_prompt: str
    optimized_prompt: str
    skill_id: str | None = None


class AnalyzeSubjectResponse(BaseModel):
    description: str
    kind: str | None = None
    name: str | None = None


class SkillItem(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    category: str


class SkillsListResponse(BaseModel):
    skills: list[SkillItem]


class DirectorShotItem(BaseModel):
    shot_number: int = Field(description="分镜序号")
    title: str = Field(description="分镜简要标题或场景动作")
    prompt: str = Field(description="结构化画面描述提示词")
    scale: Literal["ELS", "WS", "MS", "CU", "ECU"] = Field(default="MS", description="景别：大远景/全景/中景/特写/大特写")
    movement: Literal["zoom_in", "zoom_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "orbit", "tracking", "static"] = Field(
        default="zoom_in", description="运镜方式",
    )
    angle: Literal["eye_level", "low_angle", "high_angle", "dutch", "pov"] = Field(
        default="eye_level", description="拍摄机位角度",
    )
    speed: Literal["smooth", "dynamic", "slow"] = Field(default="smooth", description="运镜节奏",)
    lighting: Literal["cinematic_soft", "cyberpunk", "golden_hour", "dramatic_low_key", "studio"] = Field(
        default="cinematic_soft", description="影调布光",
    )
    sfx: str = Field(default="", description="环境音效与拟音描述")


class ScriptSplitRequest(BaseModel):
    script: str = Field(min_length=1, max_length=10000, description="剧本大纲或故事文本")
    shot_count: int | None = Field(default=4, ge=2, le=12, description="期望拆分的分镜头数量")
    style_vibe: str | None = Field(default=None, max_length=64, description="整体风格基调，如电影级、赛博朋克等")
    cast_names: list[str] = Field(default_factory=list, description="已知角色名称列表")


class ScriptSplitResponse(BaseModel):
    project_title: str = Field(description="提取或生成的项目标题")
    summary: str = Field(description="剧本核心梗概")
    shots: list[DirectorShotItem] = Field(description="拆解后的分镜头列表")


DirectorGenerationStatus = Literal["pending", "partial", "complete"]
DirectorPayloadKind = Literal["timeline", "director_recipe", "batch_run"]


class DirectorArtStyleCategory(BaseModel):
    id: str
    name_zh: str
    name_en: str


class DirectorArtStyle(BaseModel):
    id: str
    name_zh: str
    name_en: str
    category: str
    category_name_zh: str = ""
    category_name_en: str = ""
    description: str = ""
    promptPrefix: str
    keywords: list[str] = Field(default_factory=list)


class DirectorArtStyleCatalogResponse(BaseModel):
    categories: list[DirectorArtStyleCategory]
    styles: list[DirectorArtStyle]
    count: int


class DirectorProjectCreateRequest(BaseModel):
    id: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9._-]+$", description="可选工程 ID；迁库时保留浏览器原 ID。")
    title: str = Field(min_length=1, max_length=120, description="工程标题")
    summary: str = Field(default="", max_length=2000, description="工程梗概")
    source_script: str = Field(default="", max_length=20000, description="原始剧本文档，可空")
    style_vibe: str | None = Field(default=None, max_length=64, description="拆分时使用的风格基调")
    requested_shot_count: int | None = Field(default=None, ge=1, le=24, description="拆分时请求的镜数")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="工程 payload。kind=director_recipe 为 Recipe（script/artStyle/characters/locations/scenes）；kind=batch_run 为批量；缺省 kind 为旧时间轴。不含 data URL。",
    )
    created_at: str | None = Field(default=None, max_length=64, description="迁库时保留的创建时间")
    updated_at: str | None = Field(default=None, max_length=64, description="迁库时保留的更新时间")


class DirectorProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=2000)
    source_script: str | None = Field(default=None, max_length=20000)
    style_vibe: str | None = Field(default=None, max_length=64)
    requested_shot_count: int | None = Field(default=None, ge=1, le=24)
    payload: dict[str, Any] | None = Field(default=None, description="完整替换工程 payload（时间轴或 Recipe）")


class DirectorProjectListItem(BaseModel):
    id: str
    title: str
    summary: str
    has_source_script: bool
    kind: DirectorPayloadKind = "timeline"
    shot_count: int
    generated_count: int
    generation_status: DirectorGenerationStatus
    style_vibe: str | None = None
    requested_shot_count: int | None = None
    created_at: str
    updated_at: str


class DirectorProjectResponse(DirectorProjectListItem):
    source_script: str
    payload: dict[str, Any] = Field(default_factory=dict)


class DirectorProjectMigrateRequest(BaseModel):
    projects: list[DirectorProjectCreateRequest] = Field(default_factory=list, max_length=200)


class DirectorProjectMigrateResponse(BaseModel):
    imported: int
    skipped: int
    projects: list[DirectorProjectListItem] = Field(default_factory=list)


class DirectorRecipeRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=8000, description="一句话创意或故事")
    project_id: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=120)
    art_style_id: str | None = Field(default=None, max_length=32, description="画风目录 id，例如 as_1001")
    skip_research: bool | None = Field(default=None, description="为 true 时跳过研究 Agent")


class DirectorRecipeStepRequest(BaseModel):
    agent_id: Literal[
        "research", "script", "art_style", "storyboard", "characters",
        "locations", "voice", "music", "media",
    ]
    goal: str | None = Field(default=None, max_length=8000)
    art_style_id: str | None = Field(default=None, max_length=32)
    skip_research: bool | None = None


class DirectorGenerateAssetsRequest(BaseModel):
    character_ids: list[str] = Field(default_factory=list)
    location_ids: list[str] = Field(default_factory=list)
    force: bool = False


class DirectorRenderShotsRequest(BaseModel):
    shot_ids: list[str] = Field(default_factory=list)
    render_pass: Literal["preview", "final"] = "final"


class DirectorBatchCreateRequest(BaseModel):
    theme: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=3, ge=1, le=8)
    aspect_ratio: str = Field(default="9:16", max_length=16)
    duration_sec: int = Field(default=8, ge=2, le=15)
    art_style_id: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=120)
    project_id: str | None = Field(default=None, max_length=80)
