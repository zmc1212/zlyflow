from __future__ import annotations

import re
from typing import Any


class StandardScriptParser:
    """
    短剧/AI视频标准分镜剧本高精度解析器
    支持精准抽取：
    1. 项目/剧本标题与视频定位（题材、世界观、单集时长、主线等）
    2. 主要人物设定（姓名、角色定位、外貌身材服饰、固定道具、一致性Prompt）
    3. 统一视觉风格（基调、负向禁止词）
    4. 各集剧情与详细分镜头（镜头序号、场景、人物、道具、时长、动作、运镜、台词、音效、提示词）
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
        scene_library = cls._extract_scene_library(text)
        episodes = cls._extract_episodes(text)
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
                if ("第" in t and "集" in t) or ("固定场景" in t) or ("人物一致性" in t) or ("制作建议" in t) or ("主要人物" in t):
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
            name = header
            role = "主要角色"
            for sep in ["——", "--", "-", "—"]:
                if sep in header:
                    parts = header.split(sep, 1)
                    name = parts[0].strip()
                    role = parts[1].strip()
                    break

            content = "\n".join(lines[1:]).strip()

            # 提取固定道具
            fixed_props = []
            prop_match = re.search(r"固定道具[：:]([^\n]+)", content)
            if prop_match:
                p_text = prop_match.group(1).strip().rstrip("。；; ")
                raw_props = re.split(r"[、,，\s]+", p_text)
                fixed_props = [p.strip() for p in raw_props if p.strip()]

            # 性别与年龄
            gender = "男"
            if any(w in content or w in role for w in ["女", "母", "小姐", "婉", "妹", "娘", "妇"]):
                gender = "女"

            age = ""
            age_match = re.search(r"(\d+岁)", content)
            if age_match:
                age = age_match.group(1)

            prompt = character_prompts.get(name, "")
            if not prompt:
                prompt = content.replace(f"固定道具：{prop_match.group(1) if prop_match else ''}", "").strip()

            characters.append({
                "name": name,
                "role": role,
                "gender": gender,
                "age": age,
                "description": content,
                "fixed_props": fixed_props,
                "visual_prompt": prompt,
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
                "body": match.group(0).strip(),
            })

        if episodes:
            return episodes
        return cls._fallback_single_episode(text)

    @classmethod
    def _fallback_single_episode(cls, text: str) -> list[dict[str, Any]]:
        """AI 流水线或单集故事常只有「### 镜头」而没有「# 第N集」；整篇视为第 1 集。"""
        shots = cls._extract_shots_from_episode(text)
        if not shots:
            return []
        title = cls._extract_title(text.split("\n"))
        return [{
            "episode_num": 1,
            "title": title or "第 1 集",
            "summary": "",
            "shots_count": len(shots),
            "shots": shots,
            "body": text.strip(),
        }]

    @classmethod
    def _extract_shots_from_episode(cls, episode_block: str) -> list[dict[str, Any]]:
        shots: list[dict[str, Any]] = []
        episode_block = re.split(r"\n#{1,3}\s*[四五]、", episode_block, maxsplit=1)[0]

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

    _SHOT_FIELD_START = re.compile(
        r"^(人物|角色|场景|道具|时长|duration|动作|画面|镜头|运镜|景别|台词|对白|提示词|生图提示词|画面提示词|音效|声音|字幕|旁白)[：:]",
        re.I,
    )
    _TEXT_SHOT_FIELDS = ("action", "camera", "dialogue", "visual_prompt", "audio", "subtitle")

    @classmethod
    def _shot_content_segments(cls, content: str) -> list[str]:
        segments: list[str] = []
        for line in content.split("\n"):
            line_s = line.strip().lstrip("-* ").strip()
            if not line_s:
                continue
            # 只在「人物：…；场景：…」这种多字段同行时按分号切开，避免把动作/提示词里的分号截断。
            if "；" in line_s or ";" in line_s:
                parts = [p.strip() for p in re.split(r"[；;]", line_s) if p.strip()]
                labeled = sum(1 for part in parts if cls._SHOT_FIELD_START.match(part))
                if labeled >= 2:
                    segments.extend(parts)
                    continue
            segments.append(line_s)
        return segments

    @classmethod
    def _append_shot_text(cls, shot: dict[str, Any], key: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        current = str(shot.get(key) or "").strip()
        shot[key] = f"{current} {text}".strip() if current else text

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
            "duration_sec": None,
            "raw_content": content,
        }

        last_text_field = ""
        for seg in cls._shot_content_segments(content):
            if re.match(r"^(人物|角色)[：:]", seg):
                val = re.sub(r"^(人物|角色)[：:]\s*", "", seg)
                raw_chars = re.split(r"[、,，]+", val.rstrip("；;。"))
                shot["characters"] = [c.strip() for c in raw_chars if c.strip()]
                last_text_field = ""
            elif re.match(r"^场景[：:]", seg):
                shot["scene"] = re.sub(r"^场景[：:]\s*", "", seg).rstrip("；;。").strip()
                last_text_field = ""
            elif re.match(r"^道具[：:]", seg):
                val = re.sub(r"^道具[：:]\s*", "", seg)
                raw_props = re.split(r"[、,，]+", val.rstrip("；;。"))
                shot["props"] = [p.strip() for p in raw_props if p.strip()]
                last_text_field = ""
            elif re.match(r"^(时长|duration)[：:]", seg, re.I):
                raw = re.sub(r"^(时长|duration)[：:]\s*", "", seg, flags=re.I).strip()
                match = re.search(r"(\d+(?:\.\d+)?)", raw)
                if match:
                    shot["duration_sec"] = int(round(float(match.group(1))))
                last_text_field = ""
            elif re.match(r"^(动作|画面)[：:]", seg):
                shot["action"] = re.sub(r"^(动作|画面)[：:]\s*", "", seg).strip()
                last_text_field = "action"
            elif re.match(r"^(镜头|运镜|景别)[：:]", seg):
                shot["camera"] = re.sub(r"^(镜头|运镜|景别)[：:]\s*", "", seg).strip()
                last_text_field = "camera"
            elif re.match(r"^(台词|对白)[：:]", seg):
                shot["dialogue"] = re.sub(r"^(台词|对白)[：:]\s*", "", seg).strip()
                last_text_field = "dialogue"
            elif re.match(r"^(提示词|生图提示词|画面提示词)[：:]", seg):
                shot["visual_prompt"] = re.sub(r"^(提示词|生图提示词|画面提示词)[：:]\s*", "", seg).strip()
                last_text_field = "visual_prompt"
            elif re.match(r"^(音效|声音)[：:]", seg):
                shot["audio"] = re.sub(r"^(音效|声音)[：:]\s*", "", seg).strip()
                last_text_field = "audio"
            elif re.match(r"^(字幕|旁白)[：:]", seg):
                shot["subtitle"] = re.sub(r"^(字幕|旁白)[：:]\s*", "", seg).strip()
                last_text_field = "subtitle"
            elif last_text_field in cls._TEXT_SHOT_FIELDS:
                cls._append_shot_text(shot, last_text_field, seg)
            elif not shot["action"] and not any(kw in seg for kw in ["人物", "场景", "道具", "镜头", "台词", "提示词"]):
                shot["action"] = seg
                last_text_field = "action"

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
            for ep in episodes:
                for shot in ep.get("shots", []):
                    shot_chars = " ".join(shot.get("characters", [])) + " " + shot.get("action", "") + " " + shot.get("raw_content", "")
                    if c_name in shot_chars:
                        count += 1
            c["shots_count"] = count
