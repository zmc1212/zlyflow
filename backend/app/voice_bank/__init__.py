from __future__ import annotations

import json
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalog.json")
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
HF_EXAMPLES_BASE = "https://huggingface.co/spaces/IndexTeam/IndexTTS-2-Demo/resolve/main/examples"
WAV_MAGIC = b"RIFF"
_PROMPT_LOCK = Lock()
_GROUP_ORDER = ("男声", "女声", "旁白", "外语")


class VoiceBankError(ValueError):
    """Raised when the built-in clone-voice catalog is invalid."""


def _require_text(value: Any, field: str, *, loc: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise VoiceBankError(f"{loc} 缺少 {field}")
    return text


@lru_cache(maxsize=1)
def load_voice_bank() -> dict[str, Any]:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise VoiceBankError("声线目录 JSON 根节点必须是对象")
    voices = raw.get("voices")
    if not isinstance(voices, list) or not voices:
        raise VoiceBankError("声线目录必须包含 voices 数组")
    seen: set[str] = set()
    files: set[str] = set()
    for index, item in enumerate(voices):
        loc = f"voices[{index}]"
        if not isinstance(item, dict):
            raise VoiceBankError(f"{loc} 必须是对象")
        voice_id = _require_text(item.get("id"), "id", loc=loc)
        filename = _require_text(item.get("file"), "file", loc=loc)
        _require_text(item.get("label"), "label", loc=loc)
        if voice_id in seen:
            raise VoiceBankError(f"声线 id 重复：{voice_id}")
        if filename in files:
            raise VoiceBankError(f"参考音文件重复：{filename}")
        seen.add(voice_id)
        files.add(filename)
        if Path(filename).suffix.lower() != ".wav":
            raise VoiceBankError(f"{loc} 只接受 wav 参考音")
    return raw


def list_voice_presets() -> list[dict[str, Any]]:
    catalog = load_voice_bank()
    return [
        _public_voice(item, catalog)
        for item in catalog["voices"]
        if isinstance(item, dict)
    ]


def get_voice_preset(preset_id: str) -> dict[str, Any] | None:
    needle = (preset_id or "").strip()
    if not needle:
        return None
    for item in list_voice_presets():
        if item["id"] == needle:
            return item
    return None


def public_audio_url(preset_id: str) -> str:
    return f"/api/voice-bank/{preset_id}/audio"


def prompt_file_path(filename: str) -> Path:
    name = Path(str(filename or "")).name
    if name != filename or ".." in name:
        raise VoiceBankError("非法参考音文件名")
    return PROMPT_DIR / name


def source_audio_url(filename: str) -> str:
    return f"{HF_EXAMPLES_BASE}/{Path(filename).name}"


def ensure_voice_prompt(preset_id: str) -> Path:
    found = get_voice_preset(preset_id)
    if found is None:
        raise KeyError(preset_id)
    dest = prompt_file_path(str(found["file"]))
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    with _PROMPT_LOCK:
        if dest.is_file() and dest.stat().st_size > 1000:
            return dest
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            source_audio_url(str(found["file"])),
            headers={"User-Agent": "ZLY-AI-Video-Studio/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
        except (OSError, urllib.error.URLError) as error:
            raise VoiceBankError(f"无法下载内置参考音：{error}") from error
        if not data.startswith(WAV_MAGIC) or len(data) < 1000:
            raise VoiceBankError("内置参考音不是有效 wav")
        tmp = dest.with_suffix(".wav.part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return dest


def read_voice_prompt(preset_id: str) -> bytes:
    path = ensure_voice_prompt(preset_id)
    data = path.read_bytes()
    if not data.startswith(WAV_MAGIC):
        raise VoiceBankError("内置参考音损坏")
    return data


def parse_voice_bank_audio_url(url: str) -> str:
    text = str(url or "").strip()
    prefix = "/api/voice-bank/"
    suffix = "/audio"
    if not text.startswith(prefix) or not text.endswith(suffix):
        return ""
    preset_id = text[len(prefix) : -len(suffix)].strip("/")
    if "/" in preset_id or not preset_id:
        return ""
    return preset_id


def _public_voice(item: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    preset_id = str(item["id"]).strip()
    group = str(item.get("group") or "其他").strip() or "其他"
    return {
        "id": preset_id,
        "file": str(item["file"]).strip(),
        "label": str(item["label"]).strip(),
        "gender": str(item.get("gender") or "unspecified").strip() or "unspecified",
        "role": str(item.get("role") or "配角").strip() or "配角",
        "group": group,
        "group_order": _GROUP_ORDER.index(group) if group in _GROUP_ORDER else 99,
        "default_emotion": str(item.get("default_emotion") or "calm").strip() or "calm",
        "description": str(item.get("description") or "").strip(),
        "audio_url": public_audio_url(preset_id),
        "source_url": source_audio_url(str(item["file"]).strip()),
        "license": str(catalog.get("license") or "").strip(),
        "source_name": str(catalog.get("source_name") or "").strip(),
    }
