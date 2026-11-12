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


# --- GRS ---
class GrsBalanceResponse(BaseModel):
    credits: float | None = None
    queried_at: str | None = None
    error: str | None = None


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


# --- Projects ---
class ProjectItem(BaseModel):
    id: str
    name: str
    description: str | None = None
    cover_url: str | None = None
    status: str = "active"
    settings: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None
    owner_user_id: str | None = Field(default=None, exclude=True)
    created_at: str
    updated_at: str


class ProjectCreateRequest(BaseModel):
    name: str = Field(max_length=255)
    description: str | None = ""
    cover_url: str | None = None
    settings: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    cover_url: str | None = None
    status: str | None = None
    settings: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None
