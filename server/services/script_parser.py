from __future__ import annotations

import re
from typing import Any

from .cast_resolver import (
    attach_character_prompts,
    looks_from_description,
    normalize_episodes_cast,
    split_header_name,
)


class StandardScriptParser:
    """
    短剧/AI视频标准分镜剧本高精度解析器
    支持精准抽取：
    1. 项目/剧本标题与视频定位（题材、世界观、单集时长、主线等）
    2. 主要人物设定（姓名、角色定位、外貌身材服饰、固定道具、一致性Prompt）
    3. 统一视觉风格（基调、负向禁止词）
    4. 各集剧情与详细分镜头（镜头序号、场景、人物、道具、动作、运镜、台词、音效、提示词）
    5. 固定场景库与环境要素
    6. 关键道具全量汇聚
    7. 制作建议
    """

    @classmethod
    def parse(cls, raw_text: str) -> dict[str, Any]:
        if not raw_text or not raw_text.strip():
            return cls._empty_result()

        text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        title = cls._extract_title(lines)
        positioning = cls._extract_positioning(text)
        visual_style = cls._extract_visual_style(text)
        character_prompts = cls._extract_character_prompts(text)
        characters = cls._extract_characters(text, character_prompts)
        attach_character_prompts(characters, character_prompts)
        scene_library = cls._extract_scene_library(text)
        episodes = cls._extract_episodes(text)
        normalize_episodes_cast(characters, episodes)
        production_advice = cls._extract_production_advice(text)

        # 道具全局汇聚去重与关联统计
        props = cls._aggregate_props(characters, scene_library, episodes)

        # 汇总各镜头场景并补充到场景列表
        scenes = cls._aggregate_scenes(scene_library, episodes)

        # 角色出现频次统计
        cls._enrich_character_stats(characters, episodes)

        total_shots = sum(ep.get("shots_count", 0) for ep in episodes)

        summary = (
            f"共解析出 {len(episodes)} 集剧情、{total_shots} 个分镜头；"
            f"识别到 {len(characters)} 位主要人物、{len(scenes)} 处拍摄场景、{len(props)} 件核心道具。"
        )
        if positioning.get("genre"):
            summary = f"【{positioning.get('genre')}】" + summary

        logs = [
            f"剧本文本解析完毕，全文共计 {len(text)} 字符",
            f"识别剧目名称: {title or '未命名剧目'}",
            f"成功构建 {len(episodes)} 集分镜头结构，总计 {total_shots} 个分镜",
            f"提炼核心人物 {len(characters)} 位，固定场景 {len(scene_library)} 处，关键道具 {len(props)} 件",
        ]

        return {
            "title": title,
            "summary": summary,
            "positioning": positioning,
            "visual_style": visual_style,
            "characters": characters,
            "scenes": scenes,
            "props": props,
            "episodes": episodes,
            "production_advice": production_advice,
            "model": "standard-storyboard-parser-v2",
            "logs": logs,
        }

    @classmethod
    def _empty_result(cls) -> dict[str, Any]:
        return {
            "title": "",
            "summary": "暂无有效剧本内容",
            "positioning": {},
            "visual_style": {},
            "characters": [],
            "scenes": [],
            "props": [],
            "episodes": [],
            "production_advice": "",
            "model": "standard-storyboard-parser-v2",
            "logs": ["剧本文本为空"],
        }

    @classmethod
    def _extract_title(cls, lines: list[str]) -> str:
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("# "):
                t = line_str.lstrip("#").strip()
                if ("第" in t and "集" in t) or ("固定场景" in t) or ("人物一致性" in t) or ("制作建议" in t):
                    continue
                return t
        return "未命名短剧剧本"

    @classmethod
    def _extract_positioning(cls, text: str) -> dict[str, Any]:
        pos: dict[str, Any] = {
            "genre": "",
            "worldview": "",
            "duration_per_episode": "",
            "shots_per_episode": "",
            "main_storyline": "",
            "items": [],
        }
        match = re.search(r"#{1,3}\s*视频定位\s*\n(.*?)(?=\n#{1,2}\s+[^\n#]|\Z)", text, re.DOTALL)
        if not match:
            return pos

        block = match.group(1).strip()
        for line in block.split("\n"):
            line = line.strip().lstrip("-* ").strip()
            if not line:
                continue
            pos["items"].append(line)
            if line.startswith("类型：") or line.startswith("类型:"):
                pos["genre"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line.startswith("世界观：") or line.startswith("世界观:"):
                pos["worldview"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line.startswith("单集：") or line.startswith("单集:"):
                pos["duration_per_episode"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line.startswith("每集：") or line.startswith("每集:"):
                pos["shots_per_episode"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif line.startswith("主线：") or line.startswith("主线:"):
                pos["main_storyline"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        return pos

    @classmethod
    def _extract_visual_style(cls, text: str) -> dict[str, str]:
        style = {"description": "", "prohibited": ""}
        match = re.search(r"#{1,3}\s*(?:二[、.])?\s*统一视觉风格\s*\n(.*?)(?=\n#{1,2}\s+[^\n#]|\Z)", text, re.DOTALL)
        if not match:
            return style

        block = match.group(1).strip()
        desc_lines = []
        for line in block.split("\n"):
            line_str = line.strip()
            if not line_str or line_str.startswith("---"):
                continue
            if line_str.startswith("禁止：") or line_str.startswith("禁止:"):
                style["prohibited"] = line_str.split("：", 1)[-1].split(":", 1)[-1].strip()
            else:
                cleaned = line_str.lstrip("> ").strip()
                if cleaned:
                    desc_lines.append(cleaned)
        style["description"] = " ".join(desc_lines)
        return style

    @classmethod
    def _extract_character_prompts(cls, text: str) -> dict[str, str]:
        """提取 #/## 四、人物一致性提示词"""
        prompts: dict[str, str] = {}
        match = re.search(r"#{1,3}\s*(?:四[、.])?\s*人物一致性提示词\s*\n(.*?)(?=\n#{1,2}\s+[^\n#]|\Z)", text, re.DOTALL)
        if not match:
            return prompts

        block = match.group(1).strip()
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\*?\*?\s*([^：:\n*]+?)\s*\*?\*?\s*[：:]\s*(.*)", line)
            if m:
                c_name = m.group(1).strip()
                p_val = m.group(2).strip().lstrip("* ").strip()
                prompts[c_name] = p_val
        return prompts

    @classmethod
    def _extract_characters(cls, text: str, character_prompts: dict[str, str]) -> list[dict[str, Any]]:
        characters: list[dict[str, Any]] = []
        # 注意：不要在 ### 处提前截断，截断条件必须是 #{1,2} 并且后面不是 #
        match = re.search(r"#{1,3}\s*(?:一[、.])?\s*主要人物固定设定\s*\n(.*?)(?=\n#{1,2}\s+[^\n#]|\Z)", text, re.DOTALL)
        if not match:
            return characters

        block = match.group(1).strip()
        char_blocks = re.split(r"\n(?=###\s*)", block)
        for cb in char_blocks:
            cb_str = cb.strip()
            if not cb_str.startswith("###"):
                continue

            lines = cb_str.split("\n")
            header = lines[0].replace("###", "").strip()
            raw_name = header
            role = ""
            for sep in ["——", "--", "-", "—"]:
                if sep in header:
                    parts = header.split(sep, 1)
                    raw_name = parts[0].strip()
                    role = parts[1].strip()
                    break

            name, aliases = split_header_name(raw_name)
            content = "\n".join(lines[1:]).strip()

            fixed_props = []
            prop_match = re.search(r"固定道具[：:]([^\n]+)", content)
            if prop_match:
                p_text = prop_match.group(1).strip().rstrip("。；; ")
                raw_props = re.split(r"[、,，\s]+", p_text)
                fixed_props = [p.strip() for p in raw_props if p.strip()]

            age = ""
            age_match = re.search(r"(\d+\s*岁)", content)
            if age_match:
                age = re.sub(r"\s+", "", age_match.group(1))

            prompt = character_prompts.get(name, "") or character_prompts.get(raw_name, "")
            if not prompt:
                prompt = content.replace(f"固定道具：{prop_match.group(1) if prop_match else ''}", "").strip()

            characters.append({
                "name": name,
                "aliases": [item for item in aliases if item and item != name],
                "role": role,
                "gender": "",
                "age": age,
                "age_group": "",
                "role_position": "",
                "description": content,
                "fixed_props": fixed_props,
                "visual_prompt": prompt,
                "face_prompt": "",
                "body_type": "",
                "art_style_id": "",
                "visual_style": "",
                "ethnicity": "",
                "looks": looks_from_description(content),
                "shots_count": 0,
            })
        return characters

    @classmethod
    def _extract_scene_library(cls, text: str) -> list[dict[str, Any]]:
        """提取 #/## 三、固定场景库"""
        scenes: list[dict[str, Any]] = []
        match = re.search(r"#{1,3}\s*(?:三[、.])?\s*固定场景库\s*\n(.*?)(?=\n#{1}\s+[^\n#]|\Z)", text, re.DOTALL)
        if not match:
            return scenes

        block = match.group(1).strip()
        parts = re.split(r"\n(?=##\s*)", block)
        for part in parts:
            part_str = part.strip()
            if not part_str.startswith("##"):
                continue
            lines = [l.strip() for l in part_str.split("\n") if l.strip()]
            s_name = lines[0].lstrip("#").strip()
            s_desc = "\n".join(lines[1:]).strip()
            elements = [e.strip() for e in re.split(r"[、,，\s]+", s_desc.rstrip("。；; ")) if e.strip()]

            scenes.append({
                "name": s_name,
                "type": "固定场景",
                "description": s_desc,
                "elements": elements,
                "shots_count": 0,
            })
        return scenes

    @classmethod
    def _extract_episodes(cls, text: str) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []

        ep_matches = list(re.finditer(r"#\s*第\s*([0-9一二三四五六七八九十百]+)\s*集[：:\s]*(.*?)(?=\n#\s*第|\n#\s*[一二三四五六七八九十]|#{1,2}\s*三|\Z)", text, re.DOTALL))

        cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

        for match in ep_matches:
            num_raw = match.group(1).strip()
            if num_raw.isdigit():
                ep_num = int(num_raw)
            else:
                ep_num = cn_map.get(num_raw, len(episodes) + 1)

            title_and_rest = match.group(2).strip()
            ep_lines = title_and_rest.split("\n")
            ep_title = ep_lines[0].strip() if ep_lines else f"第 {ep_num} 集"

            summary = ""
            sum_match = re.search(r"\*?\*?剧情[：:]\*?\*?\s*([^\n]+)", title_and_rest)
            if sum_match:
                summary = sum_match.group(1).strip()

            shots = cls._extract_shots_from_episode(title_and_rest)

            episodes.append({
                "episode_num": ep_num,
                "title": ep_title,
                "summary": summary,
                "shots_count": len(shots),
                "shots": shots,
            })

        return episodes

    @classmethod
    def _extract_shots_from_episode(cls, episode_block: str) -> list[dict[str, Any]]:
        shots: list[dict[str, Any]] = []

        shot_splits = list(re.finditer(r"###\s*镜头\s*([0-9一二三四五六七八九十]+)[｜|/：:\s\-]*([^\n]*)", episode_block))
        if not shot_splits:
            return shots

        cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

        for i, m in enumerate(shot_splits):
            s_num_raw = m.group(1).strip()
            s_num = int(s_num_raw) if s_num_raw.isdigit() else cn_map.get(s_num_raw, i + 1)
            s_title = m.group(2).strip() or f"镜头 {s_num}"

            start_pos = m.end()
            end_pos = shot_splits[i + 1].start() if i + 1 < len(shot_splits) else len(episode_block)
            content_block = episode_block[start_pos:end_pos].strip()

            shot_data = cls._parse_single_shot(s_num, s_title, content_block)
            shots.append(shot_data)

        return shots

    @classmethod
    def _parse_single_shot(cls, shot_num: int, title: str, content: str) -> dict[str, Any]:
        shot: dict[str, Any] = {
            "shot_num": shot_num,
            "title": title,
            "characters": [],
            "scene": "",
            "props": [],
            "action": "",
            "camera": "",
            "dialogue": "",
            "visual_prompt": "",
            "audio": "",
            "subtitle": "",
            "raw_content": content,
        }

        # 先将行按换行与分号拆分成原子片段
        raw_lines = content.split("\n")
        atomic_segments: list[str] = []
        for line in raw_lines:
            line_s = line.strip().lstrip("-* ").strip()
            if not line_s:
                continue
            # 若行内包含分号，如 "人物：沈砚、村民；场景：村口田地；道具：农具、竹筐、木车；村民因灌溉争论。"
            if "；" in line_s or ";" in line_s:
                parts = re.split(r"[；;]", line_s)
                for p in parts:
                    if p.strip():
                        atomic_segments.append(p.strip())
            else:
                atomic_segments.append(line_s)

        for seg in atomic_segments:
            if re.match(r"^(人物|角色)[：:]", seg):
                val = re.sub(r"^(人物|角色)[：:]\s*", "", seg)
                raw_chars = re.split(r"[、,，\s]+", val.rstrip("；;。"))
                shot["characters"] = [c.strip() for c in raw_chars if c.strip()]
            elif re.match(r"^场景[：:]", seg):
                shot["scene"] = re.sub(r"^场景[：:]\s*", "", seg).rstrip("；;。").strip()
            elif re.match(r"^道具[：:]", seg):
                val = re.sub(r"^道具[：:]\s*", "", seg)
                raw_props = re.split(r"[、,，\s]+", val.rstrip("；;。"))
                shot["props"] = [p.strip() for p in raw_props if p.strip()]
            elif re.match(r"^动作[：:]", seg):
                shot["action"] = re.sub(r"^动作[：:]\s*", "", seg).strip()
            elif re.match(r"^(镜头|运镜|景别)[：:]", seg):
                shot["camera"] = re.sub(r"^(镜头|运镜|景别)[：:]\s*", "", seg).strip()
            elif re.match(r"^(台词|对白)[：:]", seg):
                shot["dialogue"] = re.sub(r"^(台词|对白)[：:]\s*", "", seg).strip()
            elif re.match(r"^(提示词|生图提示词|画面提示词)[：:]", seg):
                shot["visual_prompt"] = re.sub(r"^(提示词|生图提示词|画面提示词)[：:]\s*", "", seg).strip()
            elif re.match(r"^(音效|声音)[：:]", seg):
                shot["audio"] = re.sub(r"^(音效|声音)[：:]\s*", "", seg).strip()
            elif re.match(r"^(字幕|旁白)[：:]", seg):
                shot["subtitle"] = re.sub(r"^(字幕|旁白)[：:]\s*", "", seg).strip()
            elif not shot["action"] and not any(kw in seg for kw in ["人物", "场景", "道具", "镜头", "台词", "提示词"]):
                shot["action"] = seg

        # 若台词为空但内容里有引号对话
        if not shot["dialogue"] and content:
            dialogue_match = re.search(r"[“\"「](.*?)[”\"」]", content)
            if dialogue_match:
                shot["dialogue"] = dialogue_match.group(0)

        # 若动作仍为空，用全文非标签行代替
        if not shot["action"] and content:
            shot["action"] = content.replace("\n", " ").strip()

        return shot

    @classmethod
    def _extract_production_advice(cls, text: str) -> str:
        match = re.search(r"#{1,3}\s*(?:五[、.])?\s*视频制作建议\s*\n(.*?)(?=\n#|\Z)", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @classmethod
    def _aggregate_props(
        cls,
        characters: list[dict[str, Any]],
        scene_library: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prop_map: dict[str, dict[str, Any]] = {}

        for c in characters:
            for p in c.get("fixed_props", []):
                p_clean = p.strip()
                if not p_clean:
                    continue
                if p_clean not in prop_map:
                    prop_map[p_clean] = {
                        "name": p_clean,
                        "kind": "人物固定道具",
                        "related_character": c["name"],
                        "related_shots": [],
                        "count": 1,
                    }
                else:
                    prop_map[p_clean]["count"] += 1
                    if not prop_map[p_clean]["related_character"]:
                        prop_map[p_clean]["related_character"] = c["name"]

        for ep in episodes:
            for s in ep.get("shots", []):
                shot_ref = f"第{ep['episode_num']}集 {s['title']}"
                for p in s.get("props", []):
                    p_clean = p.strip()
                    if not p_clean:
                        continue
                    if p_clean not in prop_map:
                        prop_map[p_clean] = {
                            "name": p_clean,
                            "kind": "分镜关键道具",
                            "related_character": ", ".join(s.get("characters", [])) or "分镜道具",
                            "related_shots": [shot_ref],
                            "count": 1,
                        }
                    else:
                        prop_map[p_clean]["count"] += 1
                        if shot_ref not in prop_map[p_clean]["related_shots"]:
                            prop_map[p_clean]["related_shots"].append(shot_ref)

        for sc in scene_library:
            for elem in sc.get("elements", []):
                if any(kw in elem for kw in ["书箱", "砚台", "毛笔", "宣纸", "陶碗", "米缸", "竹简", "讲案", "灯笼", "木床"]):
                    elem_clean = elem.strip()
                    if elem_clean and elem_clean not in prop_map:
                        prop_map[elem_clean] = {
                            "name": elem_clean,
                            "kind": "场景陈设道具",
                            "related_character": sc["name"],
                            "related_shots": [],
                            "count": 1,
                        }

        result = list(prop_map.values())
        result.sort(key=lambda x: (0 if x["kind"] == "人物固定道具" else 1, -x["count"]))
        return result

    @classmethod
    def _aggregate_scenes(
        cls,
        scene_library: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scenes_map: dict[str, dict[str, Any]] = {}

        for s in scene_library:
            scenes_map[s["name"]] = {
                "name": s["name"],
                "type": "固定场景库",
                "description": s["description"],
                "elements": s.get("elements", []),
                "shots_count": 0,
                "related_shots": [],
            }

        for ep in episodes:
            for shot in ep.get("shots", []):
                s_name = shot.get("scene", "").strip()
                if not s_name:
                    continue
                shot_ref = f"第{ep['episode_num']}集 {shot['title']}"

                matched = False
                for fixed_name in scenes_map:
                    if fixed_name in s_name:
                        scenes_map[fixed_name]["shots_count"] += 1
                        scenes_map[fixed_name]["related_shots"].append(shot_ref)
                        matched = True
                        break

                if not matched:
                    if s_name not in scenes_map:
                        scenes_map[s_name] = {
                            "name": s_name,
                            "type": "分镜实拍场景",
                            "description": f"拍摄场地：{s_name}",
                            "elements": [],
                            "shots_count": 1,
                            "related_shots": [shot_ref],
                        }
                    else:
                        scenes_map[s_name]["shots_count"] += 1
                        scenes_map[s_name]["related_shots"].append(shot_ref)

        return list(scenes_map.values())

    @classmethod
    def _enrich_character_stats(
        cls,
        characters: list[dict[str, Any]],
        episodes: list[dict[str, Any]],
    ) -> None:
        for c in characters:
            count = 0
            c_name = c["name"]
            aliases = c.get("aliases") or []
            keys = [c_name, *aliases] if isinstance(aliases, list) else [c_name, str(aliases)]
            for ep in episodes:
                for shot in ep.get("shots", []):
                    shot_chars = " ".join(shot.get("characters", [])) + " " + shot.get("action", "") + " " + shot.get("raw_content", "")
                    if any(key and str(key) in shot_chars for key in keys):
                        count += 1
            c["shots_count"] = count
