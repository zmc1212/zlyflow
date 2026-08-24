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


class JobRoundResponse(BaseModel):
    id: str
    sequence: int = Field(ge=1)
    mode: JobMode
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


class JobSourceResponse(BaseModel):
    job_id: str
    generation_item_id: str | None = None
    output_index: int | None = None


class JobResponse(BaseModel):
    id: str
    mode: JobMode
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
    id: JobMode
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


class ComfyHealthResponse(BaseModel):
    reachable: bool = Field(description="ComfyUI 的 /system_stats 是否在超时时间内可访问。")
    url: str = Field(description="当前使用的固定 ComfyUI 地址。")
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


class GrsProviderUpdateRequest(BaseModel):
    enabled: bool = False
    base_url: str = Field(default="https://grsai.dakka.com.cn", min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=4096)
    gpt_image_2_enabled: bool = True
    gpt_image_2_vip_enabled: bool = True


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


class LlmStatusResponse(BaseModel):
    available: bool
    message: str | None = None


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


class SkillItem(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    category: str


class SkillsListResponse(BaseModel):
    skills: list[SkillItem]
