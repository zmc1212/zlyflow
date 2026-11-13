from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    MINIMAX_H3_DIRECTOR_ACCEL_T2V = "minimax-h3-director-accel-t2v"
    MINIMAX_H3_DIRECTOR_ACCEL_I2V = "minimax-h3-director-accel-i2v"
    MINIMAX_H3_DIRECTOR_ACCEL_R2V = "minimax-h3-director-accel-r2v"
    MINIMAX_H3_ACTION_T2V = "minimax-h3-action-t2v"
    MINIMAX_H3_ACTION_I2V = "minimax-h3-action-i2v"
    MINIMAX_H3_ACTION_R2V = "minimax-h3-action-r2v"
    MINIMAX_H3_T8_ALL_REFERENCE = "minimax-h3-t8-all-reference"
    MINIMAX_H3_T8_DUAL_CLOCK = "minimax-h3-t8-dual-clock"
    NVIDIA_RTX_VSR = "nvidia-rtx-vsr"
    SEEDVR2_UPSCALE = "seedvr2-upscale"
    RELAYVSR_UPSCALE = "relayvsr-upscale"
    KEEP_FACE_RESTORE = "keep-face-restore"
    WAN_VACE_DEPTH_V2V = "wan21-vace-depth-v2v"
    MINIMAX_H3_MOTION_TRANSFER = "minimax-h3-motion-transfer"
    MINIMAX_H3_MOTION_REF_VIDEO = "minimax-h3-motion-ref-video"
    SCAIL2_REPLACEMENT = "scail2-replacement"
    MINIMAX_H3_FACE_SWAP = "minimax-h3-face-swap"
    MINIMAX_H3_INPAINT = "minimax-h3-inpaint"
    MINIMAX_H3_DEPTH = "minimax-h3-depth"
    MINIMAX_H3_VIDEO_EDIT = "minimax-h3-video-edit"
    STEM_SPLIT = "stem-split"
    MINIMAX_H3_AVATAR = "minimax-h3-avatar"
    MINIMAX_H3_LIP_SYNC = "minimax-h3-lip-sync"
    MINIMAX_H3_KEYFRAME = "minimax-h3-keyframe"
    MINIMAX_H3_IMAGE_T2I = "minimax-h3-image-t2i"
    MINIMAX_H3_IMAGE_EDIT = "minimax-h3-image-edit"
    GRS_GPT_IMAGE_2 = "grs-gpt-image-2"
    GRS_GPT_IMAGE_2_VIP = "grs-gpt-image-2-vip"
    IMAGE_BACKGROUND_REMOVE = "image-background-remove"
    IMAGE_LAYER_SPLIT = "image-layer-split"
    IMAGE_INPAINT = "image-inpaint"
    IMAGE_ERASER = "image-eraser"
    IMAGE_OUTPAINT = "image-outpaint"
    # 云端视频模型（executor="cloud_video"，直连厂商官方 API）
    CLOUD_KLING_T2V = "cloud-kling-t2v"
    CLOUD_KLING_I2V = "cloud-kling-i2v"
    CLOUD_SEEDANCE_T2V = "cloud-seedance-t2v"
    CLOUD_SEEDANCE_I2V = "cloud-seedance-i2v"
    CLOUD_HAILUO_T2V = "cloud-hailuo-t2v"
    CLOUD_HAILUO_I2V = "cloud-hailuo-i2v"
    # 超算互联网（SCNet）模型服务：MiniMax-H3 / Seedance / HappyHorse
    CLOUD_SCNET_H3_T2V = "cloud-scnet-h3-t2v"
    CLOUD_SCNET_H3_I2V = "cloud-scnet-h3-i2v"
    CLOUD_SCNET_SEEDANCE_T2V = "cloud-scnet-seedance-t2v"
    CLOUD_SCNET_SEEDANCE_I2V = "cloud-scnet-seedance-i2v"
    CLOUD_SCNET_HAPPYHORSE_T2V = "cloud-scnet-happyhorse-t2v"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REFINE = "awaiting_refine"
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
    cloud_url: str | None = Field(default=None, description="对象存储上的稳定资源地址，不含过期签名。")
    delivered_at: str | None = None


REFERENCE_KINDS: tuple[str, ...] = ("image", "video", "audio", "media")


class JobReference(BaseModel):
    index: int = Field(ge=1, description="Reference material upload order within the job.")
    url: str = Field(description="Authenticated reference material preview URL.")
    kind: Literal["image", "video", "audio", "media"] = Field(
        default="image",
        description=(
            "参考素材类型。media 表示「音频或视频」通用槽位（如人声/伴奏分离），"
            "具体是音频还是视频由客户端按素材本身判定。"
        ),
    )
    label: str | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> Any:
        """注册表新增槽位类型时，单条记录不能把整个任务列表打成 500：未知 kind 归一到 media。"""
        return value if value in REFERENCE_KINDS else "media"


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
    display_prompt: str | None = Field(
        default=None, description="中文展示提示词，界面默认显示；为空时回退到 prompt。",
    )
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


class UpscaleJobRequest(BaseModel):
    engine: Literal["rtx", "seedvr2", "relayvsr"] = "rtx"


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str
    role: UserRole
    is_active: bool
    must_change_password: bool
    email: str | None = None
    created_at: str
    # 登录失败锁定状态由内存计数实时计算，仅账号列表返回真实值。
    login_blocked: bool = False
    login_blocked_seconds: int = 0
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
    email: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255, description="登录账号名，或账号绑定的找回邮箱。")
    password: str = Field(min_length=1, max_length=128)


class CreateUserRequest(SetupAdminRequest):
    role: UserRole = UserRole.EMPLOYEE


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: UserRole | None = None
    is_active: bool | None = None
    email: str | None = Field(default=None, max_length=255)


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    current_password: str | None = Field(default=None, max_length=128)


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class UnlockLoginResponse(BaseModel):
    ok: bool
    cleared: int
    username: str
    login_blocked_seconds: int = 0


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class PasswordEmailChallengeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class PasswordEmailChallengeResponse(BaseModel):
    sent: bool = Field(description="是否已受理发送请求（不区分邮箱是否存在，避免账号枚举）。")
    masked_email: str | None = Field(default=None, description="脱敏后的收件邮箱，用于界面提示。")
    expires_in_minutes: int = Field(description="验证码有效分钟数。")


class PasswordEmailResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=4, max_length=12)
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
    reference_slots: list[str] = Field(default_factory=list)
    result_compare: str = "none"
    accepts_negative_prompt: bool
    accepts_image_size: bool
    accepts_audio_reference: bool = False
    accepts_video_reference: bool = False
    default_prompt: str | None = None
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
    is_default: bool = False
    supports_timeline: bool = False
    supports_multi_segment: bool = False
    # GRS 生图模型的平台标价积分（每张）；非 GRS 工作流为 null。
    credit_cost: int | None = None
    # 云端视频计费提示；目前用于超算互联网每日免费额度说明。
    billing_notice: str | None = None


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


class ProviderSecretRevealRequest(BaseModel):
    provider: Literal["llm", "vlm", "tts", "grs", "qiniu"]
    field: Literal["api_key", "access_key", "secret_key"] = "api_key"


class ProviderSecretRevealResponse(BaseModel):
    provider: str
    field: str
    value: str | None = None


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
    credit_cost: int | None = None


class GrsImageModelUpdateItem(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    sort_order: int = Field(default=100, ge=0, le=10000)
    is_default: bool = False


class GrsImageModelsUpdateRequest(BaseModel):
    models: list[GrsImageModelUpdateItem] = Field(min_length=1)


GrsProfileLiteral = Literal[
    "gpt_image_2", "gpt_image_2_vip", "gpt_image_2_5", "gpt_image_2_5_vip",
    "nano_banana", "nano_banana_2",
]


class GrsImageModelCreateRequest(BaseModel):
    provider_model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    profile: GrsProfileLiteral
    resolutions: list[str] | None = None
    enabled: bool = True


class GrsPlatformModelItem(BaseModel):
    provider_model: str
    workflow_id: str
    display_name: str
    profile: str
    resolutions: list[str] | None = None
    profile_source: Literal["builtin", "guess"]
    in_catalog: bool
    enabled: bool
    is_default: bool
    description: str = Field(default="", description="能力档说明，导入时写入目录。")
    credit_cost: int | None = Field(default=None, description="平台标价积分（每张）；价格接口失败为 null。")


class GrsPlatformModelsResponse(BaseModel):
    models: list[GrsPlatformModelItem] = Field(description="平台在售生图模型（对话模型已过滤）。")
    off_platform: list[dict[str, Any]] = Field(
        default_factory=list, description="本地目录里有、但本次平台列表未返回的模型。"
    )
    total: int = Field(description="平台 /v1/models 返回的模型总数（含对话模型）。")
    fetched_at: str
    message: str | None = None


class GrsPlatformModelImportItem(BaseModel):
    provider_model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str | None = Field(default=None, max_length=80)
    profile: GrsProfileLiteral | None = None
    resolutions: list[str] | None = None
    enabled: bool = True
    description: str | None = Field(default=None, max_length=200)
    credit_cost: int | None = Field(default=None, ge=1, le=100000)


class GrsPlatformModelImportRequest(BaseModel):
    models: list[GrsPlatformModelImportItem] = Field(min_length=1, max_length=60)


class GrsPlatformModelImportResponse(BaseModel):
    created: list[str]
    skipped: list[str]
    models: list[GrsImageModelResponse]
    profiles: list[dict[str, str]]


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
    job_title: str | None = Field(default=None, description="来源任务标题，列表与检索展示用。")


class LibraryQueryCounts(BaseModel):
    image: int = 0
    video: int = 0


class LibraryQueryResponse(BaseModel):
    items: list[LibraryItemResponse]
    total: int = Field(description="当前检索条件下的可用素材总数。")
    limit: int
    offset: int
    has_more: bool
    counts: LibraryQueryCounts = Field(description="按类型统计的可用素材数，不受 kind 筛选影响。")


class LlmProviderUpdateRequest(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="https://api-inference.modelscope.cn/v1", max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str = Field(default="Qwen/Qwen2.5-72B-Instruct", max_length=128)
    assistant_models: list[str] | None = Field(default=None, max_length=32, description="导演助手允许选择的模型 ID；空列表使用默认模型")


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


class ModelProviderPreset(BaseModel):
    key: str
    label: str
    base_url: str
    api_key_url: str
    pricing_url: str
    pricing_verified_at: str
    chat_models: list[LlmCatalogModel]
    vision_models: list[LlmCatalogModel]


class ModelProviderPresetsResponse(BaseModel):
    presets: list[ModelProviderPreset]


class LlmEndpointCredentialSummary(BaseModel):
    base_url: str
    model: str
    api_key_masked: str | None = None
    updated_at: str | None = None


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
    assistant_models: list[str] = Field(default_factory=list, description="导演助手可选模型 ID")
    saved_provider_credentials: list[LlmEndpointCredentialSummary] = Field(
        default_factory=list,
        description="已保存 Key 的供应商端点档案（掩码显示），切换服务地址时自动带出对应凭据",
    )
    use_llm_credentials: bool = False
    llm_base_url: str | None = None


class VisionRouteStatus(BaseModel):
    available: bool = False
    model: str | None = None
    attach_images: bool = False
    source: str | None = None


class LlmStatusResponse(BaseModel):
    available: bool
    message: str | None = None
    supports_vision: bool = False
    model: str | None = None
    authoring_vision: VisionRouteStatus = Field(default_factory=VisionRouteStatus)
    analysis_vision: VisionRouteStatus = Field(default_factory=VisionRouteStatus)


class VlmProviderUpdateRequest(BaseModel):
    enabled: bool = False
    use_llm_credentials: bool = False
    base_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str = Field(default="glm-4.6v-flash", max_length=255)


class VlmProviderTestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=255)
    use_llm_credentials: bool | None = None


class VlmModelCatalogRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    free_only: bool = False
    use_llm_credentials: bool | None = None


class VlmStatusResponse(BaseModel):
    available: bool
    message: str | None = None
    model: str | None = None


class PromptOptimizeRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000, description="待优化的原始创意或提示词")
    media_type: Literal["video", "image"] = Field(default="video", description="生成目标媒体类型")
    workflow_name: str | None = Field(default=None, max_length=128, description="当前选择的工作流名称")
    skill_id: str | None = Field(default=None, max_length=64, description="指定 MiniMax 技能风格 ID")
    skill_pack_id: str | None = Field(default=None, max_length=128, description="导演台技能包 ID；空表示默认 H3 官方六段式大模型装箱")
    reference_count: int | None = Field(default=0, ge=0, le=10, description="当前参考图数量")
    workflow_id: str | None = Field(default=None, max_length=64, description="当前工作流 ID")
    duration_seconds: float | None = Field(
        default=None,
        ge=1,
        le=60,
        description="当前选择的视频时长（秒）；用于首尾帧对齐声明和镜头时间码。",
    )
    image_urls: list[str] | None = Field(
        default=None,
        max_length=8,
        description="可选参考图 URL 或 data URL；最多 8 张，与 H3 一致。名称可看图时带图优化，否则只把张数写进文字。",
    )


class PromptOptimizeResponse(BaseModel):
    original_prompt: str
    optimized_prompt: str
    optimized_prompt_zh: str | None = Field(
        default=None, description="视频 H3 提示词的中文对照，仅用于界面展示；为空时前端回退到英文或原文。",
    )
    skill_id: str | None = None
    skill_pack_id: str | None = None


class AnalyzeSubjectResponse(BaseModel):
    description: str
    kind: str | None = None
    name: str | None = None


class PromptReverseResponse(BaseModel):
    chinese_prompt: str = Field(description="反推出的中文生成提示词")
    english_prompt: str = Field(description="反推出的英文生成提示词；为空时与中文一致")
    media_type: Literal["video", "image"] = Field(description="反推目标媒体类型")


class SkillItem(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    category: str


class SkillsListResponse(BaseModel):
    skills: list[SkillItem]


class SkillPackItem(BaseModel):
    id: str
    name: str
    summary: str = ""
    author: str = ""
    cover: str = ""
    surfaces: list[str] = Field(default_factory=list)
    visual_lock: str = ""
    workshop_shot: list[str] = Field(default_factory=list)
    packing_overrides: dict[str, bool] = Field(default_factory=dict)
    confirm_format: dict[str, Any] = Field(default_factory=dict)


class SkillPackListResponse(BaseModel):
    packs: list[SkillPackItem]


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
    script_mode: Literal["literal", "creative"] = Field(default="literal", description="剧本拆解模式")


class ScriptSplitResponse(BaseModel):
    project_title: str = Field(description="提取或生成的项目标题")
    summary: str = Field(description="剧本核心梗概")
    shots: list[DirectorShotItem] = Field(description="拆解后的分镜头列表")

class DirectorContinuityRepairRequest(BaseModel):
    recipe: dict[str, Any]
    from_shot: int = Field(ge=1)
    to_shot: int = Field(ge=1)


DirectorGenerationStatus = Literal["pending", "partial", "complete"]
DirectorPayloadKind = Literal[
    "timeline", "director_recipe", "batch_run", "shot_replication"
]


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
    imageUrl: str | None = None
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
        description="工程 payload。kind=director_recipe 为 Recipe（script 含可选 coverUrl、artStyle/characters/locations/scenes）；kind=batch_run 为批量；缺省 kind 为旧时间轴。不含 data URL。",
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
    deleted_take_ids: list[str] | None = Field(default=None, description="需要显式删除的 Take ID 列表")
    expected_content_revision: int | None = Field(
        default=None,
        ge=1,
        description="客户端最后读取的创作内容版本；不匹配时返回 409。旧客户端可不传。",
    )
    force: bool = Field(default=False, description="确认内容冲突后显式覆盖创作字段；执行状态仍由服务端保留。")


class DirectorProjectListItem(BaseModel):
    id: str
    title: str
    summary: str
    has_source_script: bool
    cover_url: str | None = Field(default=None, description="剧本封面图读取地址（可选）")
    kind: DirectorPayloadKind = "timeline"
    shot_count: int
    generated_count: int
    generation_status: DirectorGenerationStatus
    revision: int = Field(default=1, ge=1, description="工程任意内容或执行状态的单调递增版本。")
    content_revision: int = Field(default=1, ge=1, description="仅创作内容变更时递增的版本。")
    style_vibe: str | None = None
    requested_shot_count: int | None = None
    created_at: str
    updated_at: str


class DirectorProjectResponse(DirectorProjectListItem):
    source_script: str
    payload: dict[str, Any] = Field(default_factory=dict)
    active_operation: dict[str, Any] | None = Field(
        default=None,
        description="该工程当前排队或运行中的导演操作；没有则为 null。",
    )


class DirectorClarificationItem(BaseModel):
    """One user-confirmed creative answer injected into the matching agent."""

    id: str | None = Field(
        default=None,
        max_length=64,
        description="问题 id；beat_count 表示全剧镜头数量确认题，episode_count 表示集数，shots_per_episode 表示每集默认镜头数",
    )
    agent: str | None = Field(
        default=None,
        max_length=32,
        description="答案所属环节（STAGE_CLARIFY_AGENT_IDS 之一）；为空表示剧本创作方向（开场澄清）。",
    )
    question: str = Field(description="AI 提出的创作方向问题")
    answer: str = Field(description="用户选定或自定义的答案")


class DirectorOperationCreateRequest(BaseModel):
    kind: Literal[
        "plan_pipeline",
        "plan_clarify",
        "shot_render_prepare",
        "analyze_reference_video",
        "replicate_shots",
    ]
    goal: str | None = Field(default=None, max_length=8000)
    agents: list[str] | None = Field(default=None)
    agent: str | None = Field(
        default=None,
        max_length=32,
        description="plan_clarify 专用：为指定环节生成确认问题；为空表示剧本创作方向澄清。",
    )
    guided: bool | None = Field(
        default=None,
        description="前端逐步确认流程标记：本次操作由引导链发起，完成后自动衔接下一环节。",
    )
    art_style_id: str | None = Field(default=None, max_length=32)
    skip_research: bool | None = None
    reset_following: bool = Field(
        default=False,
        description="plan_pipeline 专用：重新生成单个环节成功后，按流水线顺序清空其后环节的产物并重置为待生成；失败或取消不动下游。",
    )
    resume: bool = Field(
        default=False,
        description="plan_pipeline 专用：保留分镜环节已产出的镜头继续处理（跳过重新拆镜，直接补跑对白补全、时长分配与衔接校验）；无镜头时回落为完整重拆，其他环节忽略。",
    )
    shot_ids: list[str] = Field(default_factory=list)
    render_pass: Literal["preview", "final"] = "final"
    polish_prompt: bool = Field(
        default=True,
        description="提交视频前是否调用大模型润色 H3 提示词；关闭后直接使用当前镜头提示词。",
    )
    clarifications: list[DirectorClarificationItem] | None = Field(
        default=None,
        description="plan_pipeline 专用：创作确认问答（plan_clarify 产出），按 agent 注入对应环节 Agent。",
    )
    analysis_mode: Literal["smart", "fixed"] | None = Field(
        default=None,
        description="analyze_reference_video 专用：smart 按镜头切换点切分，fixed 按固定秒数切段。",
    )
    segment_seconds: float | None = Field(
        default=None,
        ge=3,
        le=30,
        description="analyze_reference_video 专用：fixed 模式的分段秒数。",
    )
    scene_threshold: float | None = Field(
        default=None,
        ge=0.05,
        le=0.95,
        description="analyze_reference_video 专用：smart 模式的镜头切换判定阈值。",
    )

class DirectorOperationResponse(BaseModel):
    id: str
    project_id: str
    kind: Literal[
        "plan_pipeline",
        "plan_clarify",
        "shot_render_prepare",
        "analyze_reference_video",
        "replicate_shots",
    ]
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]
    progress: int = Field(ge=0, le=100)
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    cancel_requested: bool = False
    created_at: str
    updated_at: str


class DirectorRenderBatchRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)


class DirectorBatchCreateRequest(BaseModel):
    theme: str = Field(min_length=1, max_length=2000)
    count: int = Field(default=3, ge=1, le=8)
    aspect_ratio: str = Field(default="9:16", max_length=16)
    duration_sec: int = Field(default=8, ge=2, le=15)
    video_workflow_family: str | None = Field(default=None, max_length=80)
    art_style_id: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=120)
    project_id: str | None = Field(default=None, max_length=80)


DirectorLibraryKind = Literal["character", "scene", "prop"]


class DirectorLibraryAssetCreateRequest(BaseModel):
    kind: DirectorLibraryKind = Field(description="人物、场景或道具")
    name: str = Field(min_length=1, max_length=80, description="资产名称")
    description: str = Field(default="", max_length=2000, description="中文说明")
    promptText: str = Field(default="", max_length=4000, description="定妆/参考提示词")
    gender: str = Field(default="", max_length=32)
    imageUrl: str | None = Field(default=None, max_length=2000)
    imageJobId: str | None = Field(default=None, max_length=80)


class DirectorLibraryAssetUpdateRequest(BaseModel):
    kind: DirectorLibraryKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    promptText: str | None = Field(default=None, max_length=4000)
    gender: str | None = Field(default=None, max_length=32)
    imageUrl: str | None = Field(default=None, max_length=2000)
    imageJobId: str | None = Field(default=None, max_length=80)


class DirectorLibraryAssetResponse(BaseModel):
    id: str
    kind: DirectorLibraryKind
    name: str
    description: str = ""
    promptText: str = ""
    gender: str = ""
    imageUrl: str | None = None
    imageJobId: str | None = None
    sourceProjectId: str | None = None
    created_at: str
    updated_at: str


class TtsVoiceItem(BaseModel):
    id: str
    label: str
    gender: str = ""


class TtsProviderUpdateRequest(BaseModel):
    enabled: bool = False
    use_llm_credentials: bool = True
    base_url: str = Field(default="", max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str = Field(default="tts-1", max_length=128)
    voice: str = Field(default="alloy", max_length=64)


class TtsProviderTestRequest(BaseModel):
    enabled: bool | None = None
    use_llm_credentials: bool | None = None
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)
    voice: str | None = Field(default=None, max_length=64)


class TtsProviderResponse(BaseModel):
    enabled: bool
    use_llm_credentials: bool = True
    base_url: str = ""
    model: str
    voice: str
    api_key_masked: str | None = None
    has_api_key: bool
    credential_ready: bool
    available: bool
    unavailable_reason: str | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None
    voices: list[TtsVoiceItem] = Field(default_factory=list)
    provider: str = "custom"
    supports_clone: bool = False


class MusicAdapterUse(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    scales: dict[str, float] | None = None


class MusicProviderUpdateRequest(BaseModel):
    base_url: str = Field(default="", max_length=500)
    access_key: str | None = Field(default=None, max_length=512, description="留空表示保持现有密钥不变")


class MusicProviderTestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    access_key: str | None = Field(default=None, max_length=512, description="留空则使用已保存密钥")


class MusicProviderResponse(BaseModel):
    base_url: str = ""
    has_access_key: bool = False
    credential_ready: bool = False
    configured: bool = False
    # 「测试连接」结果字段：必须随 /api/admin/providers/music/test 回传，
    # 否则前端拿不到 available 会把成功误判为「连接失败：未知原因」。
    available: bool = False
    unavailable_reason: str | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class CloudVideoProviderUpdateRequest(BaseModel):
    enabled: bool | None = Field(default=None, description="None 表示不修改启用状态")
    base_url: str = Field(default="", max_length=500, description="留空表示恢复厂商官方默认地址")
    api_key: str | None = Field(default=None, max_length=512, description="留空表示保持现有密钥不变")
    api_secret: str | None = Field(
        default=None, max_length=512, description="双密钥厂商（可灵 SK / 方舟 SK）使用；留空表示保持现有密钥不变",
    )


class CloudVideoProviderTestRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=512, description="留空则使用已保存密钥")
    api_secret: str | None = Field(default=None, max_length=512, description="留空则使用已保存密钥")


class CloudVideoProviderResponse(BaseModel):
    provider_key: str
    label: str = ""
    requires_secret: bool = False
    api_key_label: str = "API Key"
    api_secret_label: str = "Secret Key"
    base_url_hint: str = ""
    default_base_url: str = ""
    enabled: bool = False
    base_url: str = ""
    effective_base_url: str = ""
    has_api_key: bool = False
    api_key_masked: str = ""
    has_api_secret: bool = False
    credential_ready: bool = False
    # 「测试连接」结果字段：必须随 test 响应回传，否则前端会把成功误判为失败（见 MusicProviderResponse 注释）。
    available: bool = False
    unavailable_reason: str | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class MailProviderUpdateRequest(BaseModel):
    enabled: bool = True
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    security: str = Field(default="starttls", pattern="^(ssl|starttls|none)$")
    username: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=512, description="留空表示保持现有密码不变")
    from_address: str = Field(min_length=3, max_length=255)
    from_name: str = Field(default="ZLY AI Studio", max_length=120)


class MailProviderTestRequest(BaseModel):
    enabled: bool | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: str | None = Field(default=None, pattern="^(ssl|starttls|none)$")
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=512, description="留空则使用已保存密码")
    from_address: str | None = Field(default=None, max_length=255)
    from_name: str | None = Field(default=None, max_length=120)


class MailProviderResponse(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 465
    security: str = "ssl"
    username: str = ""
    from_address: str = ""
    from_name: str = "ZLY AI Studio"
    has_password: bool = False
    credential_ready: bool = False
    configured: bool = False
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class MusicVibeRequest(BaseModel):
    description: str = Field(min_length=1, max_length=1000, description="一句话描述想要的歌")
    duration_seconds: int = Field(default=210, ge=10, le=600)
    instrumental: bool = False


class MusicJobCreateRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    style: str = Field(min_length=1, max_length=2000)
    lyrics: str = Field(default="", max_length=8000)
    duration_seconds: int = Field(default=210, ge=10, le=600)
    output_format: str = Field(default="flac", pattern="^(flac|mp3|wav)$")
    steps: int | None = Field(default=None, ge=1, le=200)
    seed: int | None = None
    lm_seed: int | None = None
    cot: str = Field(default="full", pattern="^(full|melody|off)$")
    adapters: list[MusicAdapterUse] | None = None


class MusicJobResponse(BaseModel):
    id: str
    owner_user_id: str
    title: str = ""
    style: str = ""
    lyrics: str = ""
    status: str
    progress: int = 0
    params: dict = Field(default_factory=dict)
    result_url: str | None = None
    result_format: str | None = None
    cover_url: str | None = None
    duration_seconds: int | None = None
    remote_job_id: str | None = None
    remote_song_id: str | None = None
    error_message: str | None = None
    chat_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class MusicChatCreateRequest(BaseModel):
    anchor_job_id: str | None = None


class MusicChatUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120, description="对话名称")


class MusicChatMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000, description="对音乐助手说的话")
    duration_seconds: int | None = Field(default=None, ge=10, le=600, description="composer 选定的目标时长")
    instrumental: bool | None = Field(default=None, description="composer 选定的人声/纯音乐")


class MusicChatGenerateRequest(BaseModel):
    message_id: str = Field(min_length=1, description="要生成的提案消息 id")


class MusicChatResponse(BaseModel):
    id: str
    owner_user_id: str
    title: str = "新对话"
    anchor_job_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MusicChatMessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    proposal: dict | None = None
    job_id: str | None = None
    created_at: str | None = None


class MusicChatDetailResponse(MusicChatResponse):
    messages: list[MusicChatMessageResponse] = Field(default_factory=list)
    anchor_job: MusicJobResponse | None = None


class MusicLyricLine(BaseModel):
    text: str
    start_seconds: float | None = None
    end_seconds: float | None = None


class MusicLyricsResponse(BaseModel):
    status: Literal["idle", "aligning", "ready", "unavailable", "failed"] = "idle"
    lines: list[MusicLyricLine] = Field(default_factory=list)
    source: Literal["yue2", "local"] | None = None
    message: str | None = None


class CanvasProjectCreateRequest(BaseModel):
    title: str = Field(default="未命名画布", max_length=120, description="画布标题")


class CanvasLinkedProjectRequest(BaseModel):
    director_project_id: str = Field(min_length=1, max_length=64, description="绑定的导演项目 ID")
    title: str = Field(default="", max_length=120, description="首次创建时使用的画布标题")


class CanvasProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120, description="画布标题")
    tags: list[str] | None = Field(default=None, max_length=8, description="标签，去重后最多 8 个")
    is_favorite: bool | None = Field(default=None, description="是否收藏")


class CanvasDraftSaveRequest(BaseModel):
    base_version: int = Field(ge=1, description="客户端最后读取到的草稿版本")
    content: str = Field(min_length=2, max_length=8 * 1024 * 1024, description="JSON.stringify({nodes, edges, canvasSettings})")
    checksum: str | None = Field(default=None, max_length=64, description="内容的 MD5，可选；提供时后端校验")


class CanvasPreviewItem(BaseModel):
    type: str
    x: float
    y: float
    width: float
    height: float
    url: str | None = None
    cover: str | None = None


class CanvasPreview(BaseModel):
    x: float
    y: float
    width: float
    height: float
    nodeCount: int = 0
    items: list[CanvasPreviewItem] = Field(default_factory=list)
    links: list[tuple[int, int]] = Field(default_factory=list)


class CanvasProjectListItem(BaseModel):
    id: str
    title: str
    linked_director_project_id: str | None = None
    created_at: str
    updated_at: str
    tags: list[str] = Field(default_factory=list)
    is_favorite: bool = False
    deleted_at: str | None = None
    draft_version: int | None = None
    node_count: int | None = None
    draft_updated_at: str | None = None
    preview: CanvasPreview | None = None


class CanvasProjectResponse(CanvasProjectListItem):
    version: int = Field(ge=0)
    checksum: str
    content: str
    node_count: int = 0


class CanvasDraftSaveResponse(BaseModel):
    id: str
    version: int = Field(ge=1)
    checksum: str
    node_count: int = 0
    updated_at: str


class CanvasDraftVersionItem(BaseModel):
    id: str
    version: int
    checksum: str
    node_count: int
    created_by: str
    created_at: str
