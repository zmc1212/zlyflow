from __future__ import annotations

import json
from typing import Any

import requests

from ...config import settings as workbench_settings
from ...llm_client import LlmError
from ...storage import JobStore
from ...tts_provider import TtsProviderService
from ..db import execute_sql, now_str, query_one, transaction_cursor
from .dubbing_lines import (
    apply_line_patch,
    expand_episode_lines,
    estimate_duration_sec,
    line_voice_asset,
    lines_by_beat,
    normalize_line,
)
from .qiniu_service import QiniuService
from ...voice_bank import parse_voice_bank_audio_url, read_voice_prompt
from .voice_profile import has_ref_audio, voice_of


def tts_provider_service() -> TtsProviderService:
    return TtsProviderService(JobStore(workbench_settings.runtime_database()), workbench_settings.credential_key)


def fetch_audio_bytes(url: str, timeout: float = 30.0) -> bytes:
    preset_id = parse_voice_bank_audio_url(url)
    if preset_id:
        return read_voice_prompt(preset_id)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    content = response.content or b""
    if not content:
        raise ValueError("参考音下载为空")
    return content


def prompt_audio_bytes(voice: dict[str, Any]) -> bytes:
    preset_id = str(voice.get("preset_id") or "").strip() or parse_voice_bank_audio_url(str(voice.get("ref_audio_url") or ""))
    if preset_id:
        return read_voice_prompt(preset_id)
    url = str(voice.get("ref_audio_url") or "").strip()
    if not url:
        return b""
    return fetch_audio_bytes(url)


class DubbingService:
    @classmethod
    def _episode_row(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT * FROM ai_project_episodes WHERE id = %s AND project_id = %s",
            (episode_id, project_id),
        )
        if not row:
            raise ValueError("分集不存在")
        return row

    @classmethod
    def _parse_data(cls, row: dict[str, Any]) -> dict[str, Any]:
        try:
            data = json.loads(row.get("data_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            data = {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def _assets(cls, project_id: str) -> list[dict[str, Any]]:
        from .project_detail_service import ProjectDetailService

        return ProjectDetailService.list_assets(project_id)

    @classmethod
    def get_track(cls, project_id: str, episode_id: str, *, persist: bool = False) -> dict[str, Any]:
        row = cls._episode_row(project_id, episode_id)
        data = cls._parse_data(row)
        beats = [item for item in (data.get("beats") or []) if isinstance(item, dict)]
        assets = cls._assets(project_id)
        lines = expand_episode_lines(beats, assets)
        if persist:
            cls._write_lines(project_id, episode_id, lines, data=data)
        characters = cls._character_cards(assets)
        ready = sum(1 for item in lines if item.get("status") == "ready" and item.get("audio_url"))
        unbound = [item for item in characters if not item.get("bound")]
        pack_id = ""
        try:
            from ...skill_packs import resolve_skill_pack_id

            pack_id = resolve_skill_pack_id(project_id=project_id)
        except Exception:
            pack_id = ""
        from .dubbing_mix import compose_gate_payload

        return {
            "episode_id": episode_id,
            "project_id": project_id,
            "lines": lines,
            "characters": characters,
            "total": len(lines),
            "ready": ready,
            "unbound_count": len(unbound),
            **compose_gate_payload(lines, pack_id),
        }

    @classmethod
    def sync(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        return cls.get_track(project_id, episode_id, persist=True)

    @classmethod
    def patch_line(
        cls,
        project_id: str,
        episode_id: str,
        line_id: str,
        patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        track = cls.sync(project_id, episode_id)
        target = next((item for item in track["lines"] if item.get("id") == line_id), None)
        if not target:
            raise ValueError("台词不存在")
        updated = apply_line_patch(target, patch)
        lines = [updated if item.get("id") == line_id else item for item in track["lines"]]
        cls._write_lines(project_id, episode_id, lines)
        track["lines"] = lines
        track["ready"] = sum(1 for item in lines if item.get("status") == "ready" and item.get("audio_url"))
        track["line"] = updated
        return track

    @classmethod
    def _character_cards(cls, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for asset in assets:
            if asset.get("kind") != "character":
                continue
            extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
            voice = voice_of(extra)
            cards.append({
                "id": asset.get("id"),
                "name": asset.get("name"),
                "role": extra.get("role_position") or asset.get("role") or "",
                "voice_id": asset.get("voice_id") or "",
                "bound": has_ref_audio(extra),
                "voice": voice,
            })
        return cards

    @classmethod
    def _write_lines(
        cls,
        project_id: str,
        episode_id: str,
        lines: list[dict[str, Any]],
        *,
        data: dict[str, Any] | None = None,
    ) -> None:
        grouped = lines_by_beat(lines)
        ts = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s FOR UPDATE",
                (episode_id, project_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("分集不存在")
            payload = data if data is not None else cls._parse_data(row)
            beats = payload.get("beats") or []
            for beat in beats:
                if not isinstance(beat, dict):
                    continue
                beat["dubbing_lines"] = grouped.get(str(beat.get("id") or ""), [])
            cursor.execute(
                "UPDATE ai_project_episodes SET data_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
                (json.dumps(payload, ensure_ascii=False), ts, episode_id, project_id),
            )

    @classmethod
    def mark_lines(
        cls,
        project_id: str,
        episode_id: str,
        line_ids: list[str],
        *,
        status: str,
        job_id: str = "",
        error: str = "",
    ) -> list[dict[str, Any]]:
        track = cls.sync(project_id, episode_id)
        wanted = {item for item in line_ids if item}
        lines: list[dict[str, Any]] = []
        for line in track["lines"]:
            if line.get("id") in wanted:
                line = apply_line_patch(line, {"status": status, "job_id": job_id, "error": error})
            lines.append(line)
        cls._write_lines(project_id, episode_id, lines)
        return lines

    @classmethod
    def write_line_audio(
        cls,
        project_id: str,
        episode_id: str,
        line_id: str,
        *,
        audio_url: str,
        duration_sec: float,
        job_id: str = "",
    ) -> dict[str, Any]:
        return cls.patch_line(
            project_id,
            episode_id,
            line_id,
            {
                "status": "ready",
                "audio_url": audio_url,
                "duration_sec": duration_sec,
                "job_id": job_id,
                "error": "",
            },
        )["line"]

    @classmethod
    def synthesize_line(
        cls,
        line: dict[str, Any],
        assets: list[dict[str, Any]],
        *,
        tts: TtsProviderService | None = None,
    ) -> tuple[bytes, str]:
        provider = tts or tts_provider_service()
        asset = line_voice_asset(line, assets)
        extra = (asset or {}).get("extra") if isinstance((asset or {}).get("extra"), dict) else {}
        voice = voice_of(extra)
        spk_audio = prompt_audio_bytes(voice)
        filename = "ref.wav" if spk_audio else "prompt.wav"
        gender = ""
        if extra:
            gender = str(extra.get("gender") or "")
        audio = provider.synthesize(
            str(line.get("text") or ""),
            voice=(asset or {}).get("voice_id"),
            spk_audio=spk_audio or None,
            spk_filename=filename,
            emotion=str(line.get("emotion") or voice.get("default_emotion") or "calm"),
            emo_alpha=line.get("emo_alpha", voice.get("emo_alpha")),
            duration_factor=line.get("duration_factor", voice.get("duration_factor")),
        )
        suffix = ".wav" if audio.startswith(b"RIFF") else ".mp3"
        return audio, suffix

    @classmethod
    def store_line_audio(cls, project_id: str, episode_id: str, line_id: str, content: bytes, suffix: str) -> str:
        _key, url = QiniuService.store_bytes(
            f"dubbing/{project_id}/{episode_id}",
            f"{line_id}{suffix}",
            content,
        )
        return url
