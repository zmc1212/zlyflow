from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# --- ComfyUI ---
class ComfyConfigResponse(BaseModel):
    base_url: str
    env_default: str = "http://127.0.0.1:8188"
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class ComfyUpdateRequest(BaseModel):
    base_url: str


class ComfyTestRequest(BaseModel):
    base_url: str | None = None


# --- GRS ---
class GrsConfigResponse(BaseModel):
    enabled: bool
    base_url: str
    api_key_masked: str | None = None
    has_api_key: bool
    credential_ready: bool
    gpt_image_2_enabled: bool = True
    gpt_image_2_vip_enabled: bool = True
    models: str = "gpt-image-2"
    vip_models: str = "gpt-image-2-vip"
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None
    last_balance: float | None = None
    last_balance_at: str | None = None
    available: bool = False
    unavailable_reason: str | None = None
    max_storyboard_concurrency: int = Field(default=5, ge=1, le=20)


class GrsUpdateRequest(BaseModel):
    enabled: bool
    base_url: str = "https://grsai.dakka.com.cn"
    api_key: str | None = None
    max_storyboard_concurrency: int = Field(default=5, ge=1, le=20)


class GrsTestRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None


class GrsBalanceResponse(BaseModel):
    credits: float | None = None
    queried_at: str | None = None
    error: str | None = None


class CatalogModel(BaseModel):
    workflow_id: str
    provider_model: str
    display_name: str
    description: str | None = ""
    profile: str
    resolutions: list[str] | None = None
    enabled: bool = True
    sort_order: int = 100
    is_default: bool = False
    builtin: bool = False


class CatalogPayload(BaseModel):
    models: list[CatalogModel]
    profiles: list[dict[str, str]]


class CatalogModelCreateRequest(BaseModel):
    provider_model: str
    display_name: str
    description: str | None = ""
    profile: str = "nano_banana"
    resolutions: list[str] | None = None
    is_default: bool = False


class CatalogModelsBatchUpdateRequest(BaseModel):
    models: list[dict[str, Any]]


# --- LLM ---
class LlmConfigResponse(BaseModel):
    enabled: bool
    base_url: str
    model: str
    api_key_masked: str | None = None
    has_api_key: bool
    credential_ready: bool
    available: bool = False
    unavailable_reason: str | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_test_at: str | None = None


class LlmUpdateRequest(BaseModel):
    enabled: bool
    base_url: str
    model: str
    api_key: str | None = None


class LlmTestRequest(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class LlmCatalogModelItem(BaseModel):
    id: str
    label: str
    free: bool | None = None
    owned_by: str | None = None


class LlmCatalogResponse(BaseModel):
    models: list[LlmCatalogModelItem]
    provider: str
    free_only: bool = False
    message: str | None = None


# --- Qiniu Storage ---
class QiniuConfigResponse(BaseModel):
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


class QiniuUpdateRequest(BaseModel):
    enabled: bool
    access_key: str | None = None
    secret_key: str | None = None
    bucket: str
    region: str
    domain: str
    object_prefix: str = "zly-ai-video-studio/"


class QiniuTestRequest(BaseModel):
    access_key: str | None = None
    secret_key: str | None = None
    bucket: str | None = None
    region: str | None = None
    domain: str | None = None
    object_prefix: str | None = None


# --- Projects ---
class ProjectItem(BaseModel):
    id: str
    name: str
    description: str | None = None
    cover_url: str | None = None
    status: str = "active"
    settings: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = ""
    cover_url: str | None = None
    settings: dict[str, Any] | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    cover_url: str | None = None
    status: str | None = None
    settings: dict[str, Any] | None = None
