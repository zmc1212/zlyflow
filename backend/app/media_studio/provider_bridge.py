"""Provider 配置桥接层。

dev0914 原版把 ComfyUI/GRS/LLM/七牛配置存放在自己的 ai_*_provider_settings 表并用
独立 Fernet 主密钥加密。复刻到工作台后不再移植这套存储（决策：设置页复用现有
/api/admin/providers/* 体系），本模块把各 service 需要的配置行统一适配为原版 row
形状，数据源改为工作台现有 *_provider_settings 表（同库 ai-media）与统一凭证密钥。
"""
from __future__ import annotations

from typing import Any

from ..config import settings as workbench_settings
from ..grs_provider import CredentialManager
from .db import query_one

GRS_DEFAULT_URL = "https://grsai.dakka.com.cn"
COMFY_DEFAULT_URL = "http://127.0.0.1:8188"


def credential_manager() -> CredentialManager:
    """用工作台统一凭证主密钥解密现有 *_provider_settings 表中的 API Key。"""
    return CredentialManager(workbench_settings.credential_key)


def comfy_row() -> dict[str, Any]:
    """ComfyUI 连接配置（工作台 comfy_provider_settings；未配置时回落环境默认地址）。"""
    row = query_one("SELECT * FROM comfy_provider_settings WHERE id = 1") or {}
    if not row.get("base_url"):
        row["base_url"] = str(workbench_settings.comfy_url or COMFY_DEFAULT_URL)
    return row


def grs_row() -> dict[str, Any]:
    """GRS 生图供应商配置（工作台 grs_provider_settings）。

    dev0914 的 max_storyboard_concurrency 列不移植，固定并发 5。
    """
    row = query_one("SELECT * FROM grs_provider_settings WHERE id = 1") or {}
    row.setdefault("base_url", GRS_DEFAULT_URL)
    row.setdefault("max_storyboard_concurrency", 5)
    row.setdefault("models", "gpt-image-2")
    row.setdefault("vip_models", "gpt-image-2-vip")
    row.setdefault("gpt_image_2_enabled", 1)
    row.setdefault("gpt_image_2_vip_enabled", 1)
    return row


def llm_row() -> dict[str, Any]:
    """LLM 配置（工作台 llm_provider_settings）。"""
    return query_one("SELECT * FROM llm_provider_settings WHERE id = 1") or {}


def qiniu_row() -> dict[str, Any]:
    """七牛云配置（工作台 qiniu_provider_settings）。"""
    return query_one("SELECT * FROM qiniu_provider_settings WHERE id = 1") or {}
