from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from ..db import execute_sql, now_str, query_all, query_one, transaction_cursor
from .asset_image_prompts import (
    character_look_prompt,
    character_portrait_prompt,
    look_costume_text,
    prop_view_prompt,
    scene_view_prompt,
)
from .asset_prompt_inference import (
    apply_inferred_prompts,
    reference_urls_to_data_uris,
    source_urls_for_inference,
)
from .asset_source_references import (
    MAX_SOURCE_REFERENCE_BYTES,
    apply_source_references_to_generation,
    append_source_reference,
    normalize_source_references,
    remove_source_reference,
    sniff_image_suffix,
    source_reference_urls,
)
from .episode_image_prompts import (
    asset_to_prompt_dict,
    beat_reference_urls,
    beat_render_prompt,
    beat_sketch_prompt,
)
from .grs_client import GrsClient, GrsError
from .llm_service import LlmService
from ..provider_bridge import credential_manager, grs_row
from .qiniu_service import QiniuService
from .script_parser import StandardScriptParser


def resolve_shot_scene(
    scene_name: str,
    scene_map: dict[str, str],
    inherited_name: str = "",
    inherited_id: str | None = None,
) -> tuple[str, str | None]:
    """Resolve an explicit scene, or inherit the last explicit scene for continuation shots."""
    scene_name = str(scene_name or "").strip()
    if not scene_name:
        return inherited_name, inherited_id
    for asset_name, asset_id in scene_map.items():
        if asset_name in scene_name or scene_name in asset_name:
            return scene_name, asset_id
    return scene_name, None


def asset_name_id_map(rows: list[dict[str, Any]], kind: str) -> dict[str, str]:
    """Map asset names to IDs, preferring rows that already have an image."""
    mapping: dict[str, str] = {}
    ranked: list[tuple[str, bool, str]] = []
    for row in rows:
        if row.get("kind") != kind or not row.get("id"):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if not extra and row.get("extra_json"):
            try:
                extra = json.loads(row["extra_json"]) if isinstance(row["extra_json"], str) else (row["extra_json"] or {})
            except Exception:
                extra = {}
        has_image = bool(str(
            row.get("image_url")
            or extra.get("master_url")
            or extra.get("avatar_url")
            or extra.get("reference_url")
            or ""
        ).strip())
        ranked.append((name, has_image, str(row["id"])))
    ranked.sort(key=lambda item: item[1])
    for name, _has_image, asset_id in ranked:
        mapping[name] = asset_id
    return mapping


def match_named_asset_ids(names: list[Any], name_map: dict[str, str]) -> list[str]:
    matched: list[str] = []
    for raw in names or []:
        name = str(raw or "").strip()
        if not name:
            continue
        for key, asset_id in name_map.items():
            if key in name or name in key:
                if asset_id not in matched:
                    matched.append(asset_id)
    return matched


class ProjectDetailService:
    # --- 1. 内容库 Documents ---
    @classmethod
    def _analysis_for_document_row(cls, row: dict[str, Any], *, persist: bool = False) -> dict[str, Any] | None:
        analysis = None
        raw_json = row.get("analysis_json")
        if raw_json:
            try:
                analysis = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            except Exception:
                analysis = None
        raw_text = str(row.get("raw_text") or "")
        stale = not analysis or not (analysis.get("episodes") or [])
        if stale and raw_text.strip():
            parsed = StandardScriptParser.parse(raw_text)
            if parsed.get("episodes"):
                analysis = parsed
                if persist and row.get("id"):
                    execute_sql(
                        "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s",
                        (json.dumps(parsed, ensure_ascii=False), row["id"]),
                    )
            elif analysis is None:
                analysis = parsed
        return cls._merge_pipeline_recipe_assets(row, analysis, persist=persist)

    @classmethod
    def _latest_pipeline_recipe(cls, project_id: str | None) -> dict[str, Any] | None:
        if not project_id:
            return None
        job = query_one(
            "SELECT payload_json FROM ai_project_jobs WHERE project_id = %s AND job_type = 'ai_pipeline' ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        )
        if not job:
            return None
        try:
            payload = json.loads(job.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        recipe = payload.get("recipe")
        return recipe if isinstance(recipe, dict) else None

    @classmethod
    def _merge_pipeline_recipe_assets(cls, row: dict[str, Any], analysis: dict[str, Any] | None, *, persist: bool = False) -> dict[str, Any] | None:
        if str(row.get("input_mode") or "") != "ai_pipeline":
            return analysis
        recipe = cls._latest_pipeline_recipe(row.get("project_id"))
        if not recipe:
            return analysis
        from .ai_generation_service import AiGenerationService

        merged = AiGenerationService.merge_recipe_assets_into_analysis(analysis or {}, recipe)
        before = json.dumps(analysis or {}, ensure_ascii=False, sort_keys=True)
        after = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        if persist and row.get("id") and after != before:
            execute_sql(
                "UPDATE ai_project_documents SET analysis_json = %s WHERE id = %s",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
        if persist and row.get("project_id") and (merged.get("characters") or merged.get("scenes") or merged.get("props")):
            AiGenerationService.persist_recipe_assets(str(row.get("project_id") or ""), recipe)
        return merged

    @classmethod
    def list_documents(cls, project_id: str) -> list[dict[str, Any]]:
        rows = query_all(
            "SELECT * FROM ai_project_documents WHERE project_id = %s ORDER BY updated_at DESC",
            (project_id,),
        )
        items = []
        for r in rows:
            analysis = cls._analysis_for_document_row(r, persist=True)
            items.append({
                "id": r["id"],
                "project_id": r["project_id"],
                "filename": r["filename"],
                "file_size": r["file_size"],
                "input_mode": r["input_mode"],
                "status": r["status"],
                "spine_template": r["spine_template"],
                "visual_style": r["visual_style"],
                "raw_text": r["raw_text"],
                "analysis": analysis,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })
        return items

    @classmethod
    def create_document(
        cls,
        project_id: str,
        filename: str,
        raw_text: str,
        spine_template: str = "drama",
        visual_style: str = "chinese_period_drama",
        input_mode: str = "paste",
    ) -> dict[str, Any]:
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        timestamp = now_str()
        file_size = len(raw_text.encode("utf-8"))

        # 使用高精度标准剧本与分镜解析器解析
        analysis = StandardScriptParser.parse(raw_text)

        # 若未提供文件名或为默认名称，自动优先采用解析出的剧目主标题
        if (not filename or filename.startswith("未命名") or filename == "新建剧本文档") and analysis.get("title"):
            filename = analysis["title"]

        execute_sql(
            """
            INSERT INTO ai_project_documents
            (id, project_id, filename, file_size, input_mode, status, spine_template, visual_style, raw_text, analysis_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s, %s)
            """,
            (
                doc_id,
                project_id,
                filename,
                file_size,
                input_mode,
                spine_template,
                visual_style,
                raw_text,
                json.dumps(analysis, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )

        return {
            "id": doc_id,
            "project_id": project_id,
            "filename": filename,
            "file_size": file_size,
            "input_mode": input_mode,
            "status": "ready",
            "spine_template": spine_template,
            "visual_style": visual_style,
            "raw_text": raw_text,
            "analysis": analysis,
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    @classmethod
    def delete_document(cls, project_id: str, doc_id: str) -> bool:
        aff = execute_sql("DELETE FROM ai_project_documents WHERE id = %s AND project_id = %s", (doc_id, project_id))
        return aff > 0

    @classmethod
    def transfer_assets_from_document(cls, project_id: str, doc_id: str) -> dict[str, Any]:
        row = query_one("SELECT id, analysis_json, raw_text FROM ai_project_documents WHERE id = %s AND project_id = %s", (doc_id, project_id))
        if not row:
            raise ValueError("文档不存在或尚未完成分析")
        analysis = cls._analysis_for_document_row(row, persist=True) or {}
        ts = now_str()
        chars = analysis.get("characters") or []
        scenes = analysis.get("scenes") or []
        props = analysis.get("props") or []

        # 查询已有资产以做平滑更新或去重
        existing_rows = query_all("SELECT id, kind, name FROM ai_project_assets WHERE project_id = %s", (project_id,))
        existing_map = {(r["kind"], r["name"]): r["id"] for r in existing_rows}

        c_count = 0
        s_count = 0
        p_count = 0

        # 1. 角色转入（保存角色名、定位、外观与一致性 Prompt）
        for c in chars:
            c_name = c.get("name", "").strip()
            if not c_name:
                continue
            role = c.get("role") or "主要角色"
            desc = c.get("description") or f"{c.get('gender', '')} 角色设定"
            prompt = c.get("visual_prompt") or ""
            key = ("character", c_name)
            if key in existing_map:
                execute_sql(
                    "UPDATE ai_project_assets SET role = %s, description = %s, visual_prompt = %s, updated_at = %s WHERE id = %s",
                    (role, desc, prompt, ts, existing_map[key]),
                )
            else:
                aid = f"ast-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_assets (id, project_id, kind, name, role, description, visual_prompt, created_at, updated_at)
                    VALUES (%s, %s, 'character', %s, %s, %s, %s, %s, %s)
                    """,
                    (aid, project_id, c_name, role, desc, prompt, ts, ts),
                )
            c_count += 1

        # 2. 场景转入（保存场景名、氛围与描述）
        for s in scenes:
            s_name = s.get("name", "").strip()
            if not s_name:
                continue
            role = s.get("type") or "固定场景"
            desc = s.get("description") or f"规划场景: {s_name}"
            key = ("scene", s_name)
            if key in existing_map:
                execute_sql(
                    "UPDATE ai_project_assets SET role = %s, description = %s, updated_at = %s WHERE id = %s",
                    (role, desc, ts, existing_map[key]),
                )
            else:
                aid = f"ast-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_assets (id, project_id, kind, name, role, description, created_at, updated_at)
                    VALUES (%s, %s, 'scene', %s, %s, %s, %s, %s)
                    """,
                    (aid, project_id, s_name, role, desc, ts, ts),
                )
            s_count += 1

        # 3. 道具转入（保存道具名、重要性与关联角色）
        for p in props:
            p_name = p.get("name", "").strip()
            if not p_name:
                continue
            role = p.get("kind") or "核心道具"
            rel_char = p.get("related_character") or "场景公用"
            desc = f"类型: {role}，关联角色/场景: {rel_char}"
            key = ("prop", p_name)
            if key in existing_map:
                execute_sql(
                    "UPDATE ai_project_assets SET role = %s, description = %s, updated_at = %s WHERE id = %s",
                    (role, desc, ts, existing_map[key]),
                )
            else:
                aid = f"ast-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_assets (id, project_id, kind, name, role, description, created_at, updated_at)
                    VALUES (%s, %s, 'prop', %s, %s, %s, %s, %s)
                    """,
                    (aid, project_id, p_name, role, desc, ts, ts),
                )
            p_count += 1

        return {
            "transferred": {
                "characters": c_count,
                "scenes": s_count,
                "props": p_count,
            },
            "total": c_count + s_count + p_count,
        }

    @classmethod
    def transfer_episodes_from_document(cls, project_id: str, doc_id: str) -> dict[str, Any]:
        """将解析出的分集与镜头批量同步到剧集工坊"""
        row = query_one("SELECT id, analysis_json, raw_text FROM ai_project_documents WHERE id = %s AND project_id = %s", (doc_id, project_id))
        if not row:
            raise ValueError("文档不存在或尚未完成分析")
        analysis = cls._analysis_for_document_row(row, persist=True) or {}
        episodes = analysis.get("episodes") or []
        if not episodes:
            raise ValueError("该剧本中未识别到分集或分镜头信息")

        ts = now_str()
        existing_rows = query_all("SELECT id, episode_num FROM ai_project_episodes WHERE project_id = %s", (project_id,))
        existing_map = {r["episode_num"]: r["id"] for r in existing_rows}

        total_episodes = len(episodes)
        total_shots = 0

        for ep in episodes:
            ep_num = ep.get("episode_num", 1)
            title = ep.get("title") or f"第 {ep_num} 集"
            shots = ep.get("shots") or []
            shots_count = len(shots)
            total_shots += shots_count

            # 格式化编排脚本正文供剧集工坊展示
            script_lines = [f"第 {ep_num} 集：{title}"]
            if ep.get("summary"):
                script_lines.append(f"【剧情概要】{ep['summary']}\n")
            inherited_scene_name = ""
            inherited_scene_id = None
            for s in shots:
                s_header = f"### 镜头 {s.get('shot_num', 1)}｜{s.get('title', '')}"
                script_lines.append(s_header)
                if s.get("characters"):
                    script_lines.append(f"- 人物：{', '.join(s['characters'])}")
                if s.get("scene"):
                    script_lines.append(f"- 场景：{s['scene']}")
                if s.get("props"):
                    script_lines.append(f"- 道具：{', '.join(s['props'])}")
                if s.get("camera"):
                    script_lines.append(f"- 运镜：{s['camera']}")
                if s.get("action"):
                    script_lines.append(f"- 动作：{s['action']}")
                if s.get("dialogue"):
                    script_lines.append(f"- 台词：{s['dialogue']}")
                if s.get("audio"):
                    script_lines.append(f"- 音效：{s['audio']}")
                if s.get("visual_prompt"):
                    script_lines.append(f"- 提示词：{s['visual_prompt']}")
                script_lines.append("")

            script_text = "\n".join(script_lines).strip()

            if ep_num in existing_map:
                execute_sql(
                    """
                    UPDATE ai_project_episodes
                    SET title = %s, script_text = %s, shots_count = %s, status = 'script_ready', updated_at = %s
                    WHERE id = %s
                    """,
                    (title, script_text, shots_count, ts, existing_map[ep_num]),
                )
            else:
                eid = f"ep-{uuid.uuid4().hex[:12]}"
                execute_sql(
                    """
                    INSERT INTO ai_project_episodes
                    (id, project_id, episode_num, title, status, script_text, shots_count, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'script_ready', %s, %s, %s, %s)
                    """,
                    (eid, project_id, ep_num, title, script_text, shots_count, ts, ts),
                )

        return {
            "transferred_episodes": total_episodes,
            "transferred_shots": total_shots,
        }

    # --- 2. 资产库 Assets ---
    @classmethod
    def _hydrate_asset(cls, row: dict[str, Any]) -> dict[str, Any]:
        """填充资产的 extra 数据结构（角色多造型、场景主反打机位、道具特写归属）"""
        extra: dict[str, Any] = {}
        if row.get("extra_json"):
            try:
                extra = json.loads(row["extra_json"])
            except Exception:
                extra = {}
        
        kind = row.get("kind")
        # 1. 角色类型
        if kind == "character":
            if not extra.get("avatar_url"):
                extra["avatar_url"] = row.get("image_url") or ""
            if not extra.get("avatar_prompt"):
                extra["avatar_prompt"] = f"{row['name']}，面部肖像，五官特写，眼神清亮坚毅，写实电影级光影，8k"
            
            identities = extra.get("identities")
            if not identities or not isinstance(identities, list):
                base_desc = row.get("description") or "日常基础造型"
                base_prompt = row.get("visual_prompt") or f"{row['name']} 半身立绘，{base_desc}，电影级质感，8k"
                identities = [
                    {
                        "id": f"ident-{row['id'][-6:] if len(row['id']) >= 6 else 'default'}",
                        "name": f"{row['name']} (日常/初始造型)",
                        "description": base_desc,
                        "visual_prompt": base_prompt,
                        "image_url": row.get("image_url") or "",
                    }
                ]
                extra["identities"] = identities

        # 2. 场景类型 (参考 source2: Master主视角 + Reverse背面反打视角 + Pano 360全景图)
        elif kind == "scene":
            if not extra.get("master_url"):
                extra["master_url"] = row.get("image_url") or ""
            if not extra.get("reverse_url"):
                extra["reverse_url"] = ""
            if not extra.get("pano_url"):
                extra["pano_url"] = ""
            if not extra.get("scene_type"):
                is_interior = any(w in (row.get("name") or "") for w in ["堂", "房", "斋", "室内", "舍", "阁", "楼", "院内", "私塾"])
                extra["scene_type"] = "interior" if is_interior else "exterior"
            if not extra.get("environment_prompt"):
                extra["environment_prompt"] = row.get("visual_prompt") or f"{row['name']}，电影级空镜空间全景，宋式古典建筑美学，自然光影，8k"
            if not extra.get("reverse_prompt"):
                extra["reverse_prompt"] = f"{row['name']}，对立反打机位视角，180度反向景深透视，影视级空间镜头，8k"
            if not extra.get("pano_prompt"):
                extra["pano_prompt"] = f"{row['name']}，360度球形等距柱状全景图，无缝环视无死角，宋式古风环境空间漫游，8k"

        # 3. 道具类型 (严格参考 source2: 参考图 + 转面图三视图 + 细节特写 + 归属人物 + 道具类别)
        elif kind == "prop":
            if not extra.get("reference_url"):
                extra["reference_url"] = row.get("image_url") or ""
            if not extra.get("turnaround_url"):
                extra["turnaround_url"] = ""
            if not extra.get("detail_url"):
                extra["detail_url"] = ""
            if not extra.get("owner"):
                extra["owner"] = row.get("role") or ""
            if not extra.get("prop_type"):
                name_str = row.get("name") or ""
                if any(w in name_str for w in ["剑", "刀", "枪", "弓", "匕首", "兵器", "扇"]):
                    extra["prop_type"] = "weapon"       # 武器
                elif any(w in name_str for w in ["佩", "戒", "镯", "簪", "冠", "饰"]):
                    extra["prop_type"] = "accessory"    # 饰品
                elif any(w in name_str for w in ["印", "鼎", "镜", "符", "法器", "圣物"]):
                    extra["prop_type"] = "artifact"     # 神器/法器
                elif any(w in name_str for w in ["书", "信", "折", "图", "册", "文书", "密信"]):
                    extra["prop_type"] = "document"     # 文书
                elif any(w in name_str for w in ["桌", "椅", "案", "床", "屏风", "箱", "榻"]):
                    extra["prop_type"] = "furniture"    # 家具
                else:
                    extra["prop_type"] = "object"       # 其他物件
            if not extra.get("visual_prompt"):
                extra["visual_prompt"] = row.get("visual_prompt") or f"{row['name']}，影视道具概念设计参考图，高清质感，8k"
            if not extra.get("turnaround_prompt"):
                extra["turnaround_prompt"] = f"{row['name']}，道具三视图转面图设计，正视、侧视、俯视/背视三面图，干净纯色背景，工业造型设计图纸，8k"
            if not extra.get("detail_prompt"):
                extra["detail_prompt"] = f"{row['name']}，静物微距细节特写摄影，局部材质纹理、开刃做旧与磨损雕花，微距镜头光影，8k"

        extra["source_references"] = normalize_source_references(extra)
        row["extra"] = extra
        return row

    @classmethod
    def list_assets(cls, project_id: str, kind: Optional[str] = None) -> list[dict[str, Any]]:
        if kind:
            rows = query_all(
                "SELECT * FROM ai_project_assets WHERE project_id = %s AND kind = %s ORDER BY updated_at DESC",
                (project_id, kind),
            )
        else:
            rows = query_all(
                "SELECT * FROM ai_project_assets WHERE project_id = %s ORDER BY updated_at DESC",
                (project_id,),
            )
        return [cls._hydrate_asset(r) for r in rows]

    @classmethod
    def create_asset(cls, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        aid = f"ast-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        name = payload.get("name", "").strip()
        if not name:
            raise ValueError("资产名称不能为空")

        kind = payload.get("kind", "character")
        extra = payload.get("extra") or {}
        if not extra and payload.get("extra_json"):
            try:
                extra = json.loads(payload["extra_json"])
            except Exception:
                extra = {}

        if kind == "character" and not extra.get("identities"):
            base_desc = payload.get("description") or "日常基础造型"
            extra["avatar_url"] = payload.get("image_url") or ""
            extra["avatar_prompt"] = f"{name}，面部肖像，五官特写，超写实电影质感，8k"
            extra["identities"] = [
                {
                    "id": f"ident-{aid[-6:]}",
                    "name": f"{name} (日常造型)",
                    "description": base_desc,
                    "visual_prompt": payload.get("visual_prompt") or f"{name} 全身立绘，{base_desc}",
                    "image_url": payload.get("image_url") or "",
                }
            ]
        elif kind == "scene":
            extra["master_url"] = payload.get("image_url") or ""
            extra["environment_prompt"] = payload.get("visual_prompt") or f"{name}，电影级实景空间，8k"
        elif kind == "prop":
            extra["reference_url"] = payload.get("image_url") or ""
            extra["owner"] = payload.get("role") or ""

        extra_json = json.dumps(extra, ensure_ascii=False) if extra else None

        execute_sql(
            """
            INSERT INTO ai_project_assets
            (id, project_id, kind, name, role, description, visual_prompt, image_url, voice_id, extra_json, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                aid,
                project_id,
                kind,
                name,
                payload.get("role", ""),
                payload.get("description", ""),
                payload.get("visual_prompt", ""),
                payload.get("image_url", ""),
                payload.get("voice_id", ""),
                extra_json,
                ts,
                ts,
            ),
        )
        row = query_one("SELECT * FROM ai_project_assets WHERE id = %s", (aid,))
        return cls._hydrate_asset(row) if row else {}

    @classmethod
    def update_asset(cls, project_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now_str()
        current = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not current:
            raise ValueError("资产不存在")

        extra_val = current.get("extra_json")
        if "extra" in payload:
            extra_val = json.dumps(payload["extra"], ensure_ascii=False)
        elif "extra_json" in payload:
            extra_val = payload["extra_json"]

        img_url = payload.get("image_url", current.get("image_url", ""))
        # 角色联动 avatar_url，场景联动 master_url，道具联动 reference_url
        if "extra" in payload and isinstance(payload["extra"], dict):
            if payload["extra"].get("avatar_url"):
                img_url = payload["extra"]["avatar_url"]
            elif payload["extra"].get("master_url"):
                img_url = payload["extra"]["master_url"]
            elif payload["extra"].get("reference_url"):
                img_url = payload["extra"]["reference_url"]

        execute_sql(
            """
            UPDATE ai_project_assets
            SET name = %s, role = %s, description = %s, visual_prompt = %s, image_url = %s, voice_id = %s, extra_json = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (
                payload.get("name", current.get("name")),
                payload.get("role", current.get("role")),
                payload.get("description", current.get("description")),
                payload.get("visual_prompt", current.get("visual_prompt")),
                img_url,
                payload.get("voice_id", current.get("voice_id")),
                extra_val,
                ts,
                asset_id,
                project_id,
            ),
        )
        row = query_one("SELECT * FROM ai_project_assets WHERE id = %s", (asset_id,))
        return cls._hydrate_asset(row) if row else {}

    @classmethod
    def delete_asset(cls, project_id: str, asset_id: str) -> bool:
        aff = execute_sql("DELETE FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        return aff > 0

    @classmethod
    def generate_asset_image(cls, project_id: str, asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw_row = query_one("SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s", (asset_id, project_id))
        if not raw_row:
            raise ValueError("资产不存在")

        row = cls._hydrate_asset(raw_row)
        target_type = payload.get("target_type") or "asset"  # 'avatar' | 'identity' | 'scene_master' | 'scene_reverse' | 'scene_pano' | 'prop_reference' | 'asset'
        identity_id = payload.get("identity_id")
        prompt = (payload.get("prompt") or "").strip()
        # 解析请求的模型参数，默认为 gpt-image-2
        requested_model = (payload.get("model") or "").strip() or "gpt-image-2"
        # 查找匹配的模型（按 provider_model, display_name 或 workflow_id）
        model_row = query_one(
            """
            SELECT provider_model, display_name FROM grs_image_models
            WHERE (provider_model = %s OR display_name = %s OR workflow_id = %s) AND enabled = 1
            ORDER BY is_default DESC LIMIT 1
            """,
            (requested_model, requested_model, requested_model),
        )
        if not model_row:
            model_row = query_one(
                "SELECT provider_model, display_name FROM grs_image_models WHERE is_default = 1 AND enabled = 1 LIMIT 1"
            )
        grs_model = (model_row["provider_model"] if model_row else None) or "gpt-image-2"
        model_display = (model_row["display_name"] if model_row else None) or grs_model
        extra = row.get("extra") or {}
        extra["source_references"] = normalize_source_references(extra)
        follow_source_photos = bool(source_reference_urls(extra))
        for key in ("ethnicity", "visual_style", "art_style_id", "body_type", "gender", "face_prompt"):
            value = payload.get(key)
            if value not in (None, ""):
                extra[key] = value
        char_ethnicity = str(payload.get("ethnicity") or extra.get("ethnicity") or "Chinese").strip() or "Chinese"

        reference_images: list[str] = []
        reference_urls: list[str] = []
        visual_style = str(payload.get("visual_style") or extra.get("visual_style") or "").strip()
        art_style_id = str(payload.get("art_style_id") or extra.get("art_style_id") or "").strip()

        if target_type == "avatar":
            aspect_ratio = payload.get("aspect_ratio") or "1:1"
            clean_prompt = character_portrait_prompt(
                row,
                extra,
                style=art_style_id,
                visual_style=visual_style,
                ethnicity=char_ethnicity,
                face_prompt="" if follow_source_photos else prompt,
                follow_source_photos=follow_source_photos,
            )
            job_title = f"生成角色头像: {row['name']} ({grs_model})"
        elif target_type == "identity":
            # 对齐 source1 character_look_prompt：16:9 四宫格造型图 + 头像作为身份锚点
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            ident_item = next((it for it in extra.get("identities", []) if it.get("id") == identity_id), None)
            if ident_item is None:
                raise ValueError("找不到该造型")
            ident_name = ident_item.get("name") or "角色造型"
            costume = look_costume_text(ident_item) or (prompt or "").strip()
            if not costume and not follow_source_photos:
                raise ValueError("请先填写外观描述，造型图需要服装关键词")
            ident_item = {**ident_item, "appearance_details": costume, "description": costume}
            avatar_url = (extra.get("avatar_url") or row.get("image_url") or "").strip()
            if not avatar_url and not follow_source_photos:
                raise ValueError("请先生成或上传肖像，或上传原片参考图作为身份锚点")
            if avatar_url and not follow_source_photos:
                reference_urls = [avatar_url]
            clean_prompt = character_look_prompt(
                row,
                ident_item,
                extra,
                style=art_style_id,
                visual_style=visual_style,
                ethnicity=char_ethnicity,
                follow_source_photos=follow_source_photos,
            )
            prompt = costume
            job_title = f"生成造型形象: {row['name']} - {ident_name} ({grs_model})"
        elif target_type == "scene_master":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            if follow_source_photos:
                clean_prompt = (
                    "master wide shot cinematic scene matching the source photos exactly, "
                    "establishing shot, architectural environment, 8k resolution. "
                    "Do not add furniture, signage, or objects that are not in the photos."
                )
            else:
                if not prompt:
                    prompt = extra.get("environment_prompt") or row.get("visual_prompt") or row.get("name")
                clean_prompt = f"{prompt}, master wide shot cinematic scene, establishing shot, architectural environment, 8k resolution"
            job_title = f"生成场景主视角: {row['name']} ({grs_model})"
        elif target_type == "scene_reverse":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            master_url = (extra.get("master_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传正面源图，背面图需要把它作为 REFERENCE 1 传入")
            reference_urls = [master_url]
            clean_prompt = scene_view_prompt(
                row,
                "reverse",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
            )
            job_title = f"生成场景反打视角: {row['name']} ({grs_model})"
        elif target_type == "scene_pano":
            aspect_ratio = payload.get("aspect_ratio") or "2:1"
            master_url = (extra.get("master_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传正面源图，360全景需要把它作为 REFERENCE 1 传入")
            reverse_url = (extra.get("reverse_url") or "").strip()
            reference_urls = [master_url]
            if reverse_url:
                reference_urls.append(reverse_url)
            clean_prompt = scene_view_prompt(
                row,
                "panorama",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
                has_reverse_reference=bool(reverse_url),
            )
            job_title = f"生成场景360全景图: {row['name']} ({grs_model})"
        elif target_type == "prop_reference":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            clean_prompt = prop_view_prompt(
                row, "master", extra, style=art_style_id, visual_style=visual_style
            )
            job_title = f"生成道具参考图: {row['name']} ({grs_model})"
        elif target_type == "prop_turnaround":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            master_url = (extra.get("reference_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传主视图，转面三视图需要把它作为 REFERENCE 1 传入")
            reference_urls = [master_url]
            clean_prompt = prop_view_prompt(
                row,
                "turnaround",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
            )
            job_title = f"生成道具转面三视图: {row['name']} ({grs_model})"
        elif target_type == "prop_detail":
            aspect_ratio = payload.get("aspect_ratio") or "16:9"
            master_url = (extra.get("reference_url") or row.get("image_url") or "").strip()
            if not master_url:
                raise ValueError("请先生成或上传主视图，细节特写需要把它作为 REFERENCE 1 传入")
            reference_urls = [master_url]
            clean_prompt = prop_view_prompt(
                row,
                "detail",
                extra,
                style=art_style_id,
                visual_style=visual_style,
                has_master_reference=True,
            )
            job_title = f"生成道具细节特写: {row['name']} ({grs_model})"
        else:
            aspect_ratio = payload.get("aspect_ratio") or ("1:1" if row.get("kind") == "character" else "16:9")
            if not prompt:
                prompt = row.get("visual_prompt") or row.get("description") or row.get("name")
            clean_prompt = f"{prompt}, cinematic lighting, ultra-detailed, 8k resolution, photorealistic"
            job_title = f"生成资产形象: {row['name']} ({grs_model})"

        extra["source_references"] = normalize_source_references(extra)
        reference_urls, clean_prompt = apply_source_references_to_generation(
            kind=str(row.get("kind") or ""),
            extra=extra,
            payload=payload,
            target_type=target_type,
            reference_urls=reference_urls,
            clean_prompt=clean_prompt,
        )

        dim_map = {
            "1:1": (1024, 1024),
            "3:4": (896, 1152),
            "9:16": (768, 1344),
            "16:9": (1344, 768),
            "2:1": (2048, 1024),
            "4:3": (1152, 896),
        }
        w, h = dim_map.get(aspect_ratio, (1024, 1024))

        # -------- 严格调用 GRS 极速生图供应商 (对齐 source1) --------
        grs_row_data = grs_row()
        grs_base_url = grs_row_data.get("base_url") or "https://grsai.dakka.com.cn"
        encrypted_key = grs_row_data.get("api_key_encrypted")

        cred = credential_manager()
        api_key = cred.decrypt(encrypted_key) if encrypted_key else None
        if not api_key:
            raise ValueError("GRS 供应商 API Key 未配置，请前往「系统设置 - GRS 供应商」配置有效 API Key。")

        ts = now_str()
        jid = f"job-{uuid.uuid4().hex[:12]}"
        job_payload = {
            "model": grs_model,
            "api_endpoint": f"{grs_base_url}/v1/api/generate",
            "image_size": "1K",
            "target_type": target_type,
            "prompt": prompt,
            "clean_prompt": clean_prompt,
            "aspect_ratio": aspect_ratio,
            "width": w,
            "height": h,
            "asset_id": asset_id,
            "asset_name": row.get("name", ""),
            "identity_id": identity_id,
            "identity_anchor": target_type == "identity",
            "visual_style": visual_style,
            "art_style_id": art_style_id,
            "ethnicity": char_ethnicity,
            "body_type": extra.get("body_type") or "",
            "gender": extra.get("gender") or "",
            "reply_type": "async",
            "source_reference_count": len(source_reference_urls(extra)),
            "reference_urls": reference_urls,
            "request_body": {
                "model": grs_model,
                "prompt": clean_prompt,
                "images": reference_urls,
                "aspectRatio": aspect_ratio,
                "imageSize": "1K",
                "replyType": "async",
            },
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'image_generation', %s, 'running', 10, NULL, %s, %s, %s)
            """,
            (jid, project_id, job_title, json.dumps(job_payload, ensure_ascii=False), ts, ts),
        )

        client = GrsClient(base_url=grs_base_url, api_key=api_key)
        try:
            if reference_urls:
                reference_images = []
                for ref_url in reference_urls:
                    ref_name, ref_bytes = client.download_image(ref_url)
                    reference_images.append(GrsClient.data_uri_from_bytes(ref_bytes, ref_name))
            grs_url = client.generate_sync(
                model=grs_model,
                prompt=clean_prompt,
                aspect_ratio=aspect_ratio,
                images=reference_images,
                image_size="1K",
            )
            filename, content = client.download_image(grs_url)
            object_key, image_url = QiniuService.store_bytes("image", filename, content)
        except (GrsError, RuntimeError, Exception) as e:
            fail_ts = now_str()
            err_text = str(e)
            if isinstance(e, GrsError):
                err_text = f"GRS 生图失败: {e}"
            execute_sql(
                """
                UPDATE ai_project_jobs
                SET status = 'failed', progress = 0, error_message = %s, updated_at = %s
                WHERE id = %s
                """,
                (err_text[:4000], fail_ts, jid),
            )
            if isinstance(e, GrsError):
                raise ValueError(err_text) from e
            if isinstance(e, RuntimeError):
                raise ValueError(err_text) from e
            raise
        # -------- GRS 调用结束 --------

        ts = now_str()

        # 根据 target_type 更新对应字段
        if target_type == "avatar":
            extra["avatar_url"] = image_url
            extra["avatar_object_key"] = object_key
            if prompt:
                extra["avatar_prompt"] = prompt
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, extra_json, ts, asset_id, project_id),
            )
        elif target_type == "identity":
            identities = extra.get("identities", [])
            found = False
            for it in identities:
                if it.get("id") == identity_id:
                    it["image_url"] = image_url
                    it["object_key"] = object_key
                    found = True
                    break
            if not found and identity_id:
                identities.append({
                    "id": identity_id,
                    "name": "新造型",
                    "description": "",
                    "visual_prompt": prompt,
                    "image_url": image_url,
                    "object_key": object_key,
                })
            extra["identities"] = identities
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "scene_master":
            extra["master_url"] = image_url
            if prompt:
                extra["environment_prompt"] = prompt
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, extra_json, ts, asset_id, project_id),
            )
        elif target_type == "scene_reverse":
            extra["reverse_url"] = image_url
            extra["reverse_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "scene_pano":
            extra["pano_url"] = image_url
            extra["pano_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "prop_reference":
            extra["reference_url"] = image_url
            extra["reference_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, extra_json, ts, asset_id, project_id),
            )
        elif target_type == "prop_turnaround":
            extra["turnaround_url"] = image_url
            extra["turnaround_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        elif target_type == "prop_detail":
            extra["detail_url"] = image_url
            extra["detail_object_key"] = object_key
            extra_json = json.dumps(extra, ensure_ascii=False)
            execute_sql(
                """
                UPDATE ai_project_assets
                SET extra_json = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (extra_json, ts, asset_id, project_id),
            )
        else:
            execute_sql(
                """
                UPDATE ai_project_assets
                SET image_url = %s, visual_prompt = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (image_url, prompt, ts, asset_id, project_id),
            )


        job_payload["api_url"] = image_url
        job_payload["grs_url"] = grs_url
        job_payload["object_key"] = object_key
        execute_sql(
            """
            UPDATE ai_project_jobs
            SET status = 'completed', progress = 100, result_url = %s, payload_json = %s,
                error_message = NULL, completed_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (image_url, json.dumps(job_payload, ensure_ascii=False), ts, ts, jid),
        )


        updated_row = query_one("SELECT * FROM ai_project_assets WHERE id = %s", (asset_id,))
        hydrated = cls._hydrate_asset(updated_row) if updated_row else {}
        return {
            "status": "success",
            "image_url": image_url,
            "job_id": jid,
            "target_type": target_type,
            "identity_id": identity_id,
            "source_reference_count": len(source_reference_urls(extra)),
            "asset": hydrated,
        }

    @classmethod
    def _persist_asset_extra(cls, project_id: str, asset_id: str, extra: dict[str, Any]) -> dict[str, Any]:
        extra_json = json.dumps(extra, ensure_ascii=False)
        ts = now_str()
        execute_sql(
            """
            UPDATE ai_project_assets
            SET extra_json = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (extra_json, ts, asset_id, project_id),
        )
        updated_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not updated_row:
            raise ValueError("资产不存在")
        return cls._hydrate_asset(updated_row)

    @classmethod
    def add_asset_source_reference(
        cls,
        project_id: str,
        asset_id: str,
        *,
        filename: str,
        content: bytes,
        content_type: str = "",
    ) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        if not content:
            raise ValueError("文件为空")
        if len(content) > MAX_SOURCE_REFERENCE_BYTES:
            raise ValueError("参考图不能超过 10 MB")
        suffix = sniff_image_suffix(content, filename, content_type)
        safe_name = (filename or f"source{suffix}").strip() or f"source{suffix}"
        _object_key, image_url = QiniuService.store_bytes("asset-ref", safe_name, content)
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        extra["source_references"] = append_source_reference(
            extra,
            url=image_url,
            filename=filename or safe_name,
        )
        extra.pop("source_reference_urls", None)
        return cls._persist_asset_extra(project_id, asset_id, extra)

    @classmethod
    def delete_asset_source_reference(cls, project_id: str, asset_id: str, ref_id: str) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        extra = cls._hydrate_asset(raw_row).get("extra") or {}
        before = normalize_source_references(extra)
        extra["source_references"] = remove_source_reference(extra, ref_id)
        if len(extra["source_references"]) == len(before):
            raise ValueError("参考图不存在")
        return cls._persist_asset_extra(project_id, asset_id, extra)

    @classmethod
    def infer_asset_prompts(cls, project_id: str, asset_id: str) -> dict[str, Any]:
        raw_row = query_one(
            "SELECT * FROM ai_project_assets WHERE id = %s AND project_id = %s",
            (asset_id, project_id),
        )
        if not raw_row:
            raise ValueError("资产不存在")
        row = cls._hydrate_asset(raw_row)
        extra = dict(row.get("extra") or {})
        urls = source_urls_for_inference(extra)
        images = reference_urls_to_data_uris(urls)
        inferred = LlmService.infer_asset_prompts_from_images(
            kind=str(row.get("kind") or "character"),
            name=str(row.get("name") or ""),
            role=str(row.get("role") or extra.get("role_position") or ""),
            images=images,
        )
        extra, description, visual_prompt = apply_inferred_prompts(
            kind=str(row.get("kind") or "character"),
            extra=extra,
            inferred=inferred,
            name=str(row.get("name") or ""),
            current_description=str(row.get("description") or extra.get("description") or ""),
            current_visual_prompt=str(row.get("visual_prompt") or extra.get("visual_prompt") or extra.get("environment_prompt") or ""),
        )
        return cls.update_asset(
            project_id,
            asset_id,
            {
                "name": row.get("name") or "",
                "role": row.get("role") or "",
                "description": description,
                "visual_prompt": visual_prompt,
                "image_url": row.get("image_url") or "",
                "voice_id": row.get("voice_id") or "",
                "extra": extra,
            },
        )

    # --- 3. 剧集工坊 Episodes ---
    @classmethod
    def list_episodes(cls, project_id: str) -> list[dict[str, Any]]:
        return query_all(
            "SELECT * FROM ai_project_episodes WHERE project_id = %s ORDER BY episode_num ASC",
            (project_id,),
        )

    @classmethod
    def create_episode(cls, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        eid = f"ep-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        num = payload.get("episode_num", 1)
        title = payload.get("title") or f"第 {num} 集"
        execute_sql(
            """
            INSERT INTO ai_project_episodes (id, project_id, episode_num, title, status, script_text, shots_count, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                eid,
                project_id,
                num,
                title,
                payload.get("status", "draft"),
                payload.get("script_text", ""),
                payload.get("shots_count", 0),
                ts,
                ts,
            ),
        )
        return query_one("SELECT * FROM ai_project_episodes WHERE id = %s", (eid,))

    @classmethod
    def update_episode(cls, project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ts = now_str()
        execute_sql(
            """
            UPDATE ai_project_episodes
            SET title = %s, status = %s, script_text = %s, shots_count = %s, updated_at = %s
            WHERE id = %s AND project_id = %s
            """,
            (
                payload.get("title", ""),
                payload.get("status", "draft"),
                payload.get("script_text", ""),
                payload.get("shots_count", 0),
                ts,
                episode_id,
                project_id,
            ),
        )
        return query_one("SELECT * FROM ai_project_episodes WHERE id = %s", (episode_id,))

    @classmethod
    def delete_episode(cls, project_id: str, episode_id: str) -> bool:
        aff = execute_sql("DELETE FROM ai_project_episodes WHERE id = %s AND project_id = %s", (episode_id, project_id))
        return aff > 0

    @staticmethod
    def _resolved_beat_duration(beat: dict[str, Any]) -> int:
        from ...dialogue_timing import resolve_shot_duration_sec
        return resolve_shot_duration_sec(beat)

    @classmethod
    def _apply_resolved_beat_duration(cls, beat: dict[str, Any]) -> bool:
        if not isinstance(beat, dict):
            return False
        resolved = cls._resolved_beat_duration(beat)
        raw = str(beat.get("video_duration") or "").strip()
        try:
            stored = int(float(raw)) if raw else 0
        except (TypeError, ValueError):
            stored = 0
        if stored >= resolved and stored >= 2:
            return False
        beat["video_duration"] = str(resolved)
        return True

    @classmethod
    def get_episode_detail(cls, project_id: str, episode_id: str) -> dict[str, Any]:
        """获取分集详细数据（含结构化分镜 beats、关联资产 links 等，对齐 source1 XiajiEpisode）"""
        ep_row = query_one("SELECT * FROM ai_project_episodes WHERE id = %s AND project_id = %s", (episode_id, project_id))
        if not ep_row:
            raise ValueError("分集不存在")

        ep = dict(ep_row)
        data = {}
        if ep.get("data_json"):
            try:
                data = json.loads(ep["data_json"])
            except Exception:
                data = {}

        beats = data.get("beats") or []

        # 获取项目资产供反查关联
        assets_rows = query_all("SELECT id, kind, name, image_url, extra_json FROM ai_project_assets WHERE project_id = %s", (project_id,))
        char_map = asset_name_id_map(assets_rows, "character")
        scene_map = asset_name_id_map(assets_rows, "scene")
        prop_map = asset_name_id_map(assets_rows, "prop")

        # 如果 beats 为空，从关联剧本文档解析出的分析结果抽取或生成初始分镜
        if not beats:
            doc_row = query_one(
                "SELECT analysis_json FROM ai_project_documents WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            )
            doc_analysis = json.loads(doc_row["analysis_json"]) if (doc_row and doc_row.get("analysis_json")) else {}
            episodes_list = doc_analysis.get("episodes") or []
            target_ep = next((e for e in episodes_list if e.get("episode_num") == ep["episode_num"]), None)

            shots = (target_ep.get("shots") if target_ep else []) or []
            # 如果依然没有，从 script_text 简单解析行
            if not shots and ep.get("script_text"):
                lines = [l.strip() for l in ep["script_text"].split("\n") if l.strip()]
                for idx, line in enumerate(lines):
                    shots.append({
                        "shot_num": idx + 1,
                        "title": f"分镜 {idx + 1}",
                        "action": line,
                        "visual_prompt": f"{ep['title']}，分镜{idx + 1}，{line}，电影级画面，8k",
                    })

            inherited_scene_name = ""
            inherited_scene_id = None
            for s in shots:
                s_num = s.get("shot_num", len(beats) + 1)
                s_title = s.get("title") or f"镜头 {s_num}"
                s_scene = s.get("scene") or ""
                s_camera = s.get("camera") or "中景"
                s_action = s.get("action") or ""
                s_dialogue = s.get("dialogue") or ""
                s_prompt = s.get("visual_prompt") or ""
                s_audio = s.get("audio") or ""
                s_chars = s.get("characters") or []
                s_props = s.get("props") or []

                matched_char_ids = match_named_asset_ids(s_chars, char_map)

                explicit_scene = bool(str(s_scene or "").strip())
                s_scene, matched_scene_id = resolve_shot_scene(
                    s_scene, scene_map, inherited_scene_name, inherited_scene_id
                )
                if explicit_scene:
                    inherited_scene_name = s_scene
                    inherited_scene_id = matched_scene_id

                matched_prop_ids = match_named_asset_ids(s_props, prop_map)

                speaker = s_chars[0] if s_chars else ""
                heading = f"{s_title} · {s_scene} · {s_camera}" if s_scene else s_title
                video_duration = str(cls._resolved_beat_duration({
                    "dialogue": s_dialogue,
                    "action": s_action,
                    "visual_prompt": s_prompt,
                    "duration_sec": s.get("duration_sec"),
                    "video_duration": s.get("video_duration"),
                    "durationSec": s.get("durationSec") or s.get("duration"),
                }))

                beats.append({
                    "id": f"beat-{episode_id}-{s_num}",
                    "sequence": s_num,
                    "kind": "dialogue" if s_dialogue else "action",
                    "heading": heading,
                    "speaker": speaker,
                    "dialogue": s_dialogue,
                    "action": s_action,
                    "camera": s_camera,
                    "audio": s_audio,
                    "characters": s_chars,
                    "character_ids": matched_char_ids,
                    "scene": s_scene,
                    "scene_id": matched_scene_id,
                    "props": s_props,
                    "prop_ids": matched_prop_ids,
                    "visual_prompt": s_prompt,
                    "sketch_prompt": s_prompt,
                    "sketch_url": None,
                    "render_url": None,
                    "video_url": None,
                    "video_prompt_zh": " ".join(
                        part for part in (s_action, f"运镜：{s_camera}" if s_camera else "", f"声音：{s_audio}" if s_audio else "") if part
                    ) or s_dialogue or s_prompt,
                    "video_duration": video_duration,
                    "status": "draft",
                })

            data["beats"] = beats
            execute_sql(
                "UPDATE ai_project_episodes SET data_json = %s, shots_count = %s WHERE id = %s",
                (json.dumps(data, ensure_ascii=False), len(beats), episode_id),
            )

        duration_changed = False
        for beat in beats:
            if cls._apply_resolved_beat_duration(beat):
                duration_changed = True
        if duration_changed:
            data["beats"] = beats
            execute_sql(
                "UPDATE ai_project_episodes SET data_json = %s, shots_count = %s WHERE id = %s",
                (json.dumps(data, ensure_ascii=False), len(beats), episode_id),
            )

        links = []
        for a in assets_rows:
            links.append({
                "id": f"link-{a['id']}",
                "asset_id": a["id"],
                "kind": a["kind"],
                "name": a["name"],
                "image_url": a.get("image_url") or "",
            })

        original_lines = [l for l in (ep.get("script_text") or "").split("\n") if l.strip()]

        return {
            "id": ep["id"],
            "project_id": ep["project_id"],
            "number": ep["episode_num"],
            "title": ep["title"],
            "status": ep["status"],
            "script_text": ep.get("script_text") or "",
            "content_summary": data.get("summary") or (ep.get("script_text")[:120] if ep.get("script_text") else ""),
            "shots_count": len(beats),
            "beat_count": len(beats),
            "character_count": len([l for l in links if l["kind"] == "character"]),
            "scene_count": len([l for l in links if l["kind"] == "scene"]),
            "prop_count": len([l for l in links if l["kind"] == "prop"]),
            "line_count": len(original_lines),
            "original_lines": original_lines,
            "beats": beats,
            "links": links,
            "data": data,
            "episode_video_url": data.get("episode_video_url") or "",
            "episode_video_source": data.get("episode_video_source") or "",
            "episode_video_job_id": data.get("episode_video_job_id") or "",
        }

    @classmethod
    def update_episode_beat(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新单个分镜的数据（文案、提示词、绑定资产、草图与视频等）"""
        detail = cls.get_episode_detail(project_id, episode_id)
        beats = detail.get("beats") or []
        allowed_fields = [
            "heading", "speaker", "dialogue", "action", "camera", "scene", "scene_id", "time_of_day",
            "characters", "character_ids", "character_look_id", "character_look_ids", "props", "prop_ids", "visual_prompt", "sketch_prompt",
            "sketch_url", "sketch_job_id", "render_url", "render_prompt",
            "render_job_id", "render_status", "video_url", "video_prompt_zh", "video_duration", "status",
            "h3_prompt", "dialogue_turns", "visible_text",
        ]
        updates = {key: payload[key] for key in allowed_fields if key in payload}
        target = cls._update_episode_beat_atomic(
            project_id,
            episode_id,
            beat_id,
            updates,
            initial_beats=beats,
        )
        return {"status": "ok", "beat": target}

    @classmethod
    def _update_episode_beat_atomic(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        updates: dict[str, Any],
        *,
        initial_beats: list[dict[str, Any]] | None = None,
        completed_job: dict[str, Any] | None = None,
        expected_job_id: str | None = None,
        expected_job_field: str | None = None,
    ) -> dict[str, Any]:
        """Lock the episode briefly and merge only one beat into the latest JSON."""
        ts = now_str()
        with transaction_cursor() as cursor:
            cursor.execute(
                "SELECT data_json FROM ai_project_episodes WHERE id = %s AND project_id = %s FOR UPDATE",
                (episode_id, project_id),
            )
            episode_row = cursor.fetchone()
            if not episode_row:
                raise ValueError("分集不存在")

            try:
                data = json.loads(episode_row.get("data_json") or "{}")
            except (TypeError, json.JSONDecodeError) as err:
                raise ValueError("分集数据格式无效，无法安全回填生成结果") from err

            beats = data.get("beats") or initial_beats or []
            target = next((beat for beat in beats if beat.get("id") == beat_id), None)
            if not target:
                raise ValueError("分镜不存在")
            if expected_job_id and expected_job_field and target.get(expected_job_field) != expected_job_id:
                raise ValueError("任务结果已过期，较新的生成任务已替代该任务")
            target.update(updates)
            data["beats"] = beats

            cursor.execute(
                "UPDATE ai_project_episodes SET data_json = %s, updated_at = %s WHERE id = %s AND project_id = %s",
                (json.dumps(data, ensure_ascii=False), ts, episode_id, project_id),
            )
            if completed_job:
                cursor.execute(
                    """
                    UPDATE ai_project_jobs
                    SET status = 'completed', progress = 100, result_url = %s, payload_json = %s,
                        error_message = NULL, completed_at = %s, updated_at = %s
                    WHERE id = %s AND project_id = %s
                    """,
                    (
                        completed_job["result_url"],
                        json.dumps(completed_job["payload"], ensure_ascii=False),
                        ts,
                        ts,
                        completed_job["id"],
                        project_id,
                    ),
                )
            return dict(target)

    @classmethod
    def _project_visual_settings(cls, project_id: str, payload: dict[str, Any]) -> dict[str, str]:
        visual_style = str(payload.get("visual_style") or "").strip()
        ethnicity = str(payload.get("ethnicity") or "").strip()
        art_style_id = str(payload.get("art_style_id") or "").strip()
        if not visual_style:
            doc = query_one(
                "SELECT visual_style FROM ai_project_documents WHERE project_id = %s ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            )
            visual_style = str((doc or {}).get("visual_style") or "").strip()
        return {
            "visual_style": visual_style or "chinese_period_drama",
            "ethnicity": ethnicity or "Chinese",
            "art_style_id": art_style_id,
        }

    @classmethod
    def _resolve_grs_model(cls, requested_model: str) -> tuple[str, str]:
        requested = (requested_model or "").strip() or "gpt-image-2"
        model_row = query_one(
            """
            SELECT provider_model, display_name FROM grs_image_models
            WHERE (provider_model = %s OR display_name = %s OR workflow_id = %s) AND enabled = 1
            ORDER BY is_default DESC LIMIT 1
            """,
            (requested, requested, requested),
        )
        if not model_row:
            model_row = query_one(
                "SELECT provider_model, display_name FROM grs_image_models WHERE is_default = 1 AND enabled = 1 LIMIT 1"
            )
        grs_model = (model_row["provider_model"] if model_row else None) or "gpt-image-2"
        model_display = (model_row["display_name"] if model_row else None) or grs_model
        return grs_model, model_display

    @classmethod
    def generate_beat_sketch(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .storyboard_image_service import StoryboardImageService
        return StoryboardImageService.enqueue(project_id, episode_id, beat_id, payload or {}, stage="sketch")

    @classmethod
    def generate_beat_render(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .storyboard_image_service import StoryboardImageService
        return StoryboardImageService.enqueue(project_id, episode_id, beat_id, payload or {}, stage="render")

    @classmethod
    def generate_beat_images_batch(cls, project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from .storyboard_image_service import StoryboardImageService
        return StoryboardImageService.enqueue_batch(project_id, episode_id, payload or {})

    @classmethod
    def generate_beat_h3_prompt(cls, project_id: str, episode_id: str, beat_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        from .h3_prompt_job_service import H3PromptJobService
        return H3PromptJobService.enqueue(project_id, episode_id, beat_id, payload or {})

    @classmethod
    def _generate_beat_still(
        cls,
        project_id: str,
        episode_id: str,
        beat_id: str,
        payload: dict[str, Any],
        *,
        stage: str,
    ) -> dict[str, Any]:
        """对齐 source1 草图 / 渲染图：2:3 + 1K，beat_*_prompt，参考图顺序与任务 payload 全量落库。"""
        detail = cls.get_episode_detail(project_id, episode_id)
        beats = detail.get("beats") or []
        target = next((b for b in beats if b.get("id") == beat_id), None)
        if not target:
            raise ValueError("分镜不存在")
        if target.get("kind") == "scene_heading" and not (target.get("action") or target.get("heading")):
            raise ValueError("这一条没有可生成的画面")
        if stage == "render" and not str(target.get("sketch_url") or "").strip():
            raise ValueError("请先生成草图")

        scene_view = str(payload.get("scene_view") or "front").strip() or "front"
        if scene_view not in {"front", "reverse"}:
            scene_view = "front"
        style = cls._project_visual_settings(project_id, payload)
        raw_assets = cls.list_assets(project_id)
        prompt_assets = [asset_to_prompt_dict(row) for row in raw_assets]
        if stage == "render" and target.get("character_ids"):
            assets_by_id = {str(asset.get("id") or ""): asset for asset in raw_assets}
            selected_ids = target.get("character_look_ids") if isinstance(target.get("character_look_ids"), dict) else {}
            legacy_look_id = str(target.get("character_look_id") or "").strip()
            invalid_characters: list[str] = []
            for character_id in [str(item) for item in (target.get("character_ids") or [])]:
                character = assets_by_id.get(character_id) or {}
                extra = character.get("extra") if isinstance(character.get("extra"), dict) else {}
                identities = extra.get("identities") or []
                selected_look_id = str(selected_ids.get(character_id) or "").strip()
                if not selected_look_id and legacy_look_id:
                    if any(str((look or {}).get("id") or "") == legacy_look_id for look in identities):
                        selected_look_id = legacy_look_id
                selected_look = next(
                    (
                        look for look in identities
                        if isinstance(look, dict) and str(look.get("id") or "") == selected_look_id
                    ),
                    None,
                )
                selected_look_url = str((selected_look or {}).get("image_url") or "").strip()
                if not selected_look_url.startswith(("http://", "https://")):
                    invalid_characters.append(str(character.get("name") or character_id))
            if invalid_characters:
                raise ValueError("请为当前分镜的出场角色选择有效服饰造型：" + "、".join(invalid_characters))
        if stage == "sketch":
            clean_prompt = beat_sketch_prompt(
                target,
                assets=prompt_assets,
                visual_style=style["visual_style"],
                ethnicity=style["ethnicity"],
                art_style_id=style["art_style_id"],
            )
            job_label = "镜头草图"
            target_type = "beat_sketch"
        else:
            clean_prompt = beat_render_prompt(
                target,
                assets=prompt_assets,
                visual_style=style["visual_style"],
                ethnicity=style["ethnicity"],
                art_style_id=style["art_style_id"],
            )
            job_label = "镜头渲染"
            target_type = "beat_render"

        reference_urls = beat_reference_urls(
            target, raw_assets, stage=stage, scene_view=scene_view
        )
        if stage == "render" and not reference_urls:
            raise ValueError("无法读取草图文件，请重新生成草图")

        aspect_ratio = "2:3"
        image_size = "1K"
        grs_model, _model_display = cls._resolve_grs_model(str(payload.get("model") or ""))
        dim_map = {
            "1:1": (1024, 1024),
            "2:3": (768, 1152),
            "3:4": (896, 1152),
            "9:16": (768, 1344),
            "16:9": (1344, 768),
            "2:1": (2048, 1024),
            "4:3": (1152, 896),
        }
        w, h = dim_map.get(aspect_ratio, (768, 1152))

        grs_row_data = grs_row()
        grs_base_url = grs_row_data.get("base_url") or "https://grsai.dakka.com.cn"
        encrypted_key = grs_row_data.get("api_key_encrypted")
        cred = credential_manager()
        api_key = cred.decrypt(encrypted_key) if encrypted_key else None
        if not api_key:
            raise ValueError("GRS 供应商 API Key 未配置，请前往「系统设置 - GRS 供应商」配置有效 API Key。")

        ts = now_str()
        jid = f"job-{uuid.uuid4().hex[:12]}"
        job_title = f"生成{job_label}: 第 {detail['number']} 集 - Beat {target.get('sequence')} ({grs_model})"
        job_payload = {
            "model": grs_model,
            "api_endpoint": f"{grs_base_url}/v1/api/generate",
            "image_size": image_size,
            "target_type": target_type,
            "episode_id": episode_id,
            "beat_id": beat_id,
            "beat_sequence": target.get("sequence"),
            "scene_view": scene_view,
            "prompt": clean_prompt,
            "clean_prompt": clean_prompt,
            "aspect_ratio": aspect_ratio,
            "width": w,
            "height": h,
            "visual_style": style["visual_style"],
            "art_style_id": style["art_style_id"],
            "ethnicity": style["ethnicity"],
            "reply_type": "async",
            "character_ids": target.get("character_ids") or [],
            "character_look_id": target.get("character_look_id"),
            "character_look_ids": target.get("character_look_ids") or {},
            "scene_id": target.get("scene_id"),
            "prop_ids": target.get("prop_ids") or [],
            "reference_urls": reference_urls,
            "request_body": {
                "model": grs_model,
                "prompt": clean_prompt,
                "images": reference_urls,
                "aspectRatio": aspect_ratio,
                "imageSize": image_size,
                "replyType": "async",
            },
        }
        execute_sql(
            """
            INSERT INTO ai_project_jobs
            (id, project_id, job_type, title, status, progress, result_url, payload_json, created_at, updated_at)
            VALUES (%s, %s, 'image_generation', %s, 'running', 10, NULL, %s, %s, %s)
            """,
            (jid, project_id, job_title, json.dumps(job_payload, ensure_ascii=False), ts, ts),
        )

        client = GrsClient(base_url=grs_base_url, api_key=api_key)
        try:
            reference_images: list[str] = []
            for ref_url in reference_urls:
                ref_name, ref_bytes = client.download_image(ref_url)
                reference_images.append(GrsClient.data_uri_from_bytes(ref_bytes, ref_name))
            grs_url = client.generate_sync(
                model=grs_model,
                prompt=clean_prompt,
                aspect_ratio=aspect_ratio,
                images=reference_images,
                image_size=image_size,
            )
            filename, content = client.download_image(grs_url)
            object_key, image_url = QiniuService.store_bytes("image", filename, content)
        except Exception as e:
            fail_ts = now_str()
            err_text = str(e)
            if isinstance(e, GrsError):
                err_text = f"GRS 生图失败: {e}"
            execute_sql(
                """
                UPDATE ai_project_jobs
                SET status = 'failed', progress = 0, error_message = %s, updated_at = %s
                WHERE id = %s
                """,
                (err_text[:4000], fail_ts, jid),
            )
            raise ValueError(err_text) from e

        job_payload["api_url"] = image_url
        job_payload["grs_url"] = grs_url
        job_payload["object_key"] = object_key
        if stage == "sketch":
            beat_updates = {
                "sketch_url": image_url,
                "sketch_prompt": clean_prompt,
                "sketch_job_id": jid,
                "status": "sketched",
            }
        else:
            beat_updates = {
                "render_url": image_url,
                "render_prompt": clean_prompt,
                "render_job_id": jid,
                "render_status": "succeeded",
            }
        try:
            target = cls._update_episode_beat_atomic(
                project_id,
                episode_id,
                beat_id,
                beat_updates,
                initial_beats=beats,
                completed_job={"id": jid, "result_url": image_url, "payload": job_payload},
            )
        except Exception as err:
            fail_ts = now_str()
            err_text = f"图片已生成，但分镜回填失败: {err}"
            execute_sql(
                """
                UPDATE ai_project_jobs
                SET status = 'failed', progress = 0, error_message = %s, updated_at = %s
                WHERE id = %s AND project_id = %s
                """,
                (err_text[:4000], fail_ts, jid, project_id),
            )
            raise ValueError(err_text) from err
        return {
            "status": "success",
            "image_url": image_url,
            "job_id": jid,
            "beat_id": beat_id,
            "beat": target,
        }


    # --- 4. 全部任务 Jobs ---
    @classmethod
    def list_jobs(cls, project_id: str) -> list[dict[str, Any]]:
        rows = query_all(
            "SELECT * FROM ai_project_jobs WHERE project_id = %s ORDER BY updated_at DESC",
            (project_id,),
        )
        result = []
        for row in rows:
            r = dict(row)
            if r.get("payload_json"):
                try:
                    r["payload"] = json.loads(r["payload_json"])
                except Exception:
                    r["payload"] = {}
            else:
                r["payload"] = {}
            payload = r["payload"]
            refs = [
                u for u in (payload.get("reference_urls") or payload.get("images") or [])
                if isinstance(u, str) and u.startswith(("http://", "https://"))
            ]
            if not refs and payload.get("target_type") == "identity" and payload.get("asset_id"):
                asset = query_one(
                    "SELECT image_url, extra_json FROM ai_project_assets WHERE id = %s",
                    (payload.get("asset_id"),),
                )
                extra = {}
                if asset and asset.get("extra_json"):
                    try:
                        extra = json.loads(asset["extra_json"]) or {}
                    except Exception:
                        extra = {}
                inferred = str((extra.get("avatar_url") if extra else "") or (asset or {}).get("image_url") or "").strip()
                if inferred:
                    refs = [inferred]
                    payload["reference_urls_inferred"] = True
            if not refs and payload.get("target_type") in {"scene_reverse", "scene_pano"} and payload.get("asset_id"):
                asset = query_one(
                    "SELECT image_url, extra_json FROM ai_project_assets WHERE id = %s",
                    (payload.get("asset_id"),),
                )
                extra = {}
                if asset and asset.get("extra_json"):
                    try:
                        extra = json.loads(asset["extra_json"]) or {}
                    except Exception:
                        extra = {}
                master = str((extra.get("master_url") if extra else "") or (asset or {}).get("image_url") or "").strip()
                reverse = str((extra.get("reverse_url") if extra else "") or "").strip()
                if master:
                    refs = [master]
                    if payload.get("target_type") == "scene_pano" and reverse:
                        refs.append(reverse)
                    payload["reference_urls_inferred"] = True
            if not refs and payload.get("target_type") in {"prop_turnaround", "prop_detail"} and payload.get("asset_id"):
                asset = query_one(
                    "SELECT image_url, extra_json FROM ai_project_assets WHERE id = %s",
                    (payload.get("asset_id"),),
                )
                extra = {}
                if asset and asset.get("extra_json"):
                    try:
                        extra = json.loads(asset["extra_json"]) or {}
                    except Exception:
                        extra = {}
                master = str((extra.get("reference_url") if extra else "") or (asset or {}).get("image_url") or "").strip()
                if master:
                    refs = [master]
                    payload["reference_urls_inferred"] = True
            payload["reference_urls"] = refs
            if isinstance(payload.get("request_body"), dict) and not payload["request_body"].get("images"):
                payload["request_body"]["images"] = refs
            result.append(r)
        return result

    @classmethod
    def create_job(cls, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        jid = f"job-{uuid.uuid4().hex[:12]}"
        ts = now_str()
        execute_sql(
            """
            INSERT INTO ai_project_jobs (id, project_id, job_type, title, status, progress, result_url, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                jid,
                project_id,
                payload.get("job_type", "image_generation"),
                payload.get("title", "生成任务"),
                payload.get("status", "running"),
                payload.get("progress", 0),
                payload.get("result_url", ""),
                ts,
                ts,
            ),
        )
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (jid,))

    @classmethod
    def retry_job(cls, project_id: str, job_id: str) -> dict[str, Any]:
        row = query_one(
            "SELECT job_type, payload_json FROM ai_project_jobs WHERE id = %s AND project_id = %s",
            (job_id, project_id),
        )
        if row and row.get("job_type") == "video_generation":
            from .episode_video_service import EpisodeVideoService
            return EpisodeVideoService.retry_job(project_id, job_id)
        if row and row.get("job_type") == "h3_prompt":
            from .h3_prompt_job_service import H3PromptJobService
            return H3PromptJobService.retry(project_id, job_id)
        payload = json.loads((row or {}).get("payload_json") or "{}")
        if payload.get("target_type") in {"beat_sketch", "beat_render"}:
            from .storyboard_image_service import StoryboardImageService
            return StoryboardImageService.retry(project_id, job_id)
        ts = now_str()
        execute_sql(
            "UPDATE ai_project_jobs SET status = 'running', progress = 10, error_message = NULL, updated_at = %s WHERE id = %s AND project_id = %s",
            (ts, job_id, project_id),
        )
        return query_one("SELECT * FROM ai_project_jobs WHERE id = %s", (job_id,))
