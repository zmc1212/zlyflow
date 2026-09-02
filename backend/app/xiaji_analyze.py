from __future__ import annotations

import json
import re
from typing import Any

from .llm_client import LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS, LlmError, OpenAICompatibleClient
from .xiaji_parser import estimated_episode_count

MAX_ANALYZE_CHARS = 24000

CHARACTER_PROMPT = """你是小说角色分析专家。请基于原文提取所有人物角色。

⚠️ 核心规则：
1. **只提取人类角色**（男性、女性角色）
2. **不要提取**：动物、宠物、神兽、怪物、精灵、机器人等非人类实体
3. 别名/称谓（如"陛下"→同一人物）应合并到同一角色
4. **不要提取身份/服装信息** — 身份由后续流程单独规划
5. **年龄变体是同一角色**：同一人物的幼年/少年/青年/中年/老年形态必须合并为一个角色，age_group 取角色在故事中**最主要的时期**对应的年龄段。例如：小说中出现"小谢铮"（幼年回忆）和"谢铮"（成年主线），应合并为一个角色"谢铮"，age_group="youth"，aliases 中包含"小谢铮"

对于每个角色，生成：
1. name: 角色主名称（最正式的称呼）
2. aliases: 该角色在原文中真实出现过的其他称呼/头衔/昵称
3. role: 角色定位（如：主角、闺蜜、前男友、皇后）
4. is_main: 是否为解说主角/第一人称叙述者（整部小说只能有 1 个 is_main=True）
5. gender: 性别（男/女）
6. age_group: 年龄段分类，必须是以下四个值之一: child（儿童）/ youth（青年）/ middle（中年）/ elder（老年）
7. body_type: 体型描述（如：纤细高挑、健壮魁梧、娇小玲珑）
8. description: 外貌和性格特征
9. face_prompt: 纯面部特征描述（不含服装）
   格式：[性别]，[年龄段]，[发型发色]，[眼睛特征]，[肤色]，[脸型/骨骼]
   示例："女性，二十多岁，黑色长发马尾，黑色杏眼，小麦肤色，瓜子脸"

规则：
- face_prompt 必须是纯面部特征，绝对不能包含服装描述
- aliases 只保留原文里真实出现过、且能稳定指向该角色的称呼
- 不要把过于泛化、依赖上下文才成立的称谓塞进 aliases，例如“男人 / 女人 / 老板 / 爸爸 / 女儿 / 店员”
- 如果信息不足，只允许对 role / body_type / description 做保守推测；不要为 aliases 编造原文未出现的称呼"""

EPISODE_PROMPT = """你是一个专业的剧集规划师。将小说内容规划为指定集数。

对于每集，生成：
1. number: 集数
2. title: 吸引人的标题
3. content_summary: 内容摘要（50字以内）
4. main_conflict: 主要冲突
5. cliffhanger: 结尾悬念（让观众想看下一集）
6. key_events: 关键事件列表（字符串数组）

规则：
- 每集要有明确的冲突和悬念
- 情节连贯，前后呼应
- 高潮放在中后期"""

SCENE_PROMPT = """你是场景环境设计专家。根据原文列出可复用的地点场景。

对于每个场景，生成：
1. name: 场景名称（保留原文具体地名，不要过度概括，例如不要把「兰州拉面馆」改成「面馆」）
2. scene_type: interior / exterior / nature
3. description: 场景叙述性描述（中文，50字以内）"""

PROP_PROMPT = """你是小说道具分析专家。只提取推动剧情的重要物品（信物、武器、法宝、文书等），不提取普通日用品。

对于每个道具，生成：
1. name: 道具主名称
2. aliases: 原文中真实出现过的其他称呼、简称
3. prop_type: weapon / accessory / artifact / document / furniture
4. visual_prompt: 固有外观视觉描述（材质、工艺、尺寸、色泽、纹饰，80-120字，不含人物和临时状态）
5. owner: 所属角色名（如有，否则空字符串）

规则：
- aliases 不要发散编造；不要加入过于泛化的类别词
- visual_prompt 基于原文组织，不凭空创造细节"""


def parse_llm_json(raw: str) -> dict[str, Any]:
    clean_text = (raw or "").strip()
    if "```json" in clean_text:
        clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in clean_text:
        clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()
    first = clean_text.find("{")
    last = clean_text.rfind("}")
    if first != -1 and last != -1 and last > first:
        clean_text = clean_text[first : last + 1]
    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError as error:
        raise LlmError("大模型返回的分析结果不是合法 JSON") from error
    if not isinstance(parsed, dict):
        raise LlmError("大模型返回的分析结果格式不正确")
    return parsed


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str_list(value: Any) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in _as_list(value):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def normalize_analysis(parsed: dict[str, Any], *, target_episodes: int) -> dict[str, Any]:
    characters = []
    found_main = False
    for item in _as_list(parsed.get("characters")):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        is_main = bool(item.get("is_main")) and not found_main
        if is_main:
            found_main = True
        characters.append(
            {
                "name": name[:128],
                "aliases": _as_str_list(item.get("aliases"))[:12],
                "role": str(item.get("role") or "").strip()[:64],
                "is_main": is_main,
                "gender": str(item.get("gender") or "").strip()[:16],
                "age_group": str(item.get("age_group") or "").strip()[:16],
                "body_type": str(item.get("body_type") or "").strip()[:64],
                "description": str(item.get("description") or "").strip()[:500],
                "face_prompt": str(item.get("face_prompt") or "").strip()[:500],
            }
        )

    scenes = []
    for item in _as_list(parsed.get("scenes")):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        scenes.append(
            {
                "name": name[:128],
                "scene_type": str(item.get("scene_type") or "interior").strip()[:32],
                "description": str(item.get("description") or "").strip()[:80],
            }
        )

    props = []
    for item in _as_list(parsed.get("props")):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        props.append(
            {
                "name": name[:128],
                "aliases": _as_str_list(item.get("aliases"))[:12],
                "prop_type": str(item.get("prop_type") or "artifact").strip()[:32],
                "visual_prompt": str(item.get("visual_prompt") or "").strip()[:800],
                "owner": str(item.get("owner") or "").strip()[:64],
            }
        )

    episodes = []
    for item in _as_list(parsed.get("episodes")):
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        try:
            number_int = int(number)
        except (TypeError, ValueError):
            number_int = len(episodes) + 1
        episodes.append(
            {
                "number": number_int,
                "title": str(item.get("title") or f"第{number_int}集").strip()[:128],
                "content_summary": str(item.get("content_summary") or "").strip()[:200],
                "main_conflict": str(item.get("main_conflict") or "").strip()[:200],
                "cliffhanger": str(item.get("cliffhanger") or "").strip()[:200],
                "key_events": _as_str_list(item.get("key_events"))[:12],
            }
        )
    episodes.sort(key=lambda item: item["number"])
    if not episodes and target_episodes > 0:
        episodes = [
            {
                "number": 1,
                "title": "第1集",
                "content_summary": str(parsed.get("summary") or "")[:50],
                "main_conflict": "",
                "cliffhanger": "",
                "key_events": [],
            }
        ]

    return {
        "summary": str(parsed.get("summary") or "").strip()[:800],
        "characters": characters[:40],
        "scenes": scenes[:40],
        "props": props[:40],
        "episodes": episodes[:40],
    }


def build_ingest_messages(
    text: str,
    *,
    spine_template: str,
    visual_style: str,
    narration_style: str,
    ethnicity: str,
    target_episodes: int,
) -> list[dict[str, str]]:
    excerpt = text.strip()
    if len(excerpt) > MAX_ANALYZE_CHARS:
        excerpt = excerpt[:MAX_ANALYZE_CHARS] + "\n…（原文已截断）"
    system = (
        "你负责小说/剧本导入后的结构化知识准备。只输出一个 JSON 对象，不要 Markdown。"
        "JSON 字段：summary, characters, scenes, props, episodes。\n\n"
        f"{CHARACTER_PROMPT}\n\n{SCENE_PROMPT}\n\n{PROP_PROMPT}\n\n"
        f"{EPISODE_PROMPT}\n目标集数：{max(1, target_episodes)}。"
    )
    user = (
        f"项目类型：{spine_template or 'drama'}\n"
        f"视觉风格：{visual_style or ''}\n"
        f"解说人称：{narration_style or ''}\n"
        f"人物族裔：{ethnicity or ''}\n\n"
        f"【原文】\n{excerpt}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def analyze_ingest_text(
    client: OpenAICompatibleClient,
    model: str,
    text: str,
    *,
    spine_template: str = "drama",
    visual_style: str = "",
    narration_style: str = "",
    ethnicity: str = "",
) -> dict[str, Any]:
    clean = re.sub(r"\r\n?", "\n", text).strip()
    if not clean:
        raise LlmError("没有可分析的正文")
    target_episodes = estimated_episode_count(len(clean))
    messages = build_ingest_messages(
        clean,
        spine_template=spine_template,
        visual_style=visual_style,
        narration_style=narration_style,
        ethnicity=ethnicity,
        target_episodes=target_episodes,
    )
    raw = client.chat_completion(
        messages,
        model=model,
        temperature=0.3,
        max_tokens=4096,
        timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
    )
    normalized = normalize_analysis(parse_llm_json(raw), target_episodes=target_episodes)
    normalized["model"] = model
    normalized["target_episodes"] = target_episodes
    return normalized


def define_voice_profile(client: OpenAICompatibleClient, model: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .xiaji_asset_prompts import VOICE_DEFINE_PROMPT

    name = str(payload.get("name") or "角色").strip()
    user = (
        f"名称：{name}\n"
        f"定位：{payload.get('role') or ''}\n"
        f"性别：{payload.get('gender') or ''}\n"
        f"年龄段：{payload.get('age_group') or ''}\n"
        f"外貌与性格：{payload.get('description') or ''}\n"
        f"用途：{payload.get('purpose') or '角色对白'}"
    )
    raw = client.chat_completion(
        [
            {"role": "system", "content": VOICE_DEFINE_PROMPT + "\n只输出 JSON。"},
            {"role": "user", "content": user},
        ],
        model=model,
        temperature=0.4,
        max_tokens=800,
        timeout=LLM_DIRECTOR_CHAT_TIMEOUT_SECONDS,
    )
    parsed = parse_llm_json(raw)
    allowed_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    tts_voice = str(parsed.get("tts_voice") or "").strip().lower()
    if tts_voice not in allowed_voices:
        gender = str(payload.get("gender") or "")
        tts_voice = "onyx" if "男" in gender else "nova" if "女" in gender else "alloy"
    return {
        "language": str(parsed.get("language") or "中文普通话").strip()[:32],
        "timbre": str(parsed.get("timbre") or "").strip()[:64],
        "pitch": str(parsed.get("pitch") or "适中").strip()[:16],
        "speaking_style": str(parsed.get("speaking_style") or "").strip()[:120],
        "sample_line": str(parsed.get("sample_line") or f"我是{name}。").strip()[:40],
        "tts_voice": tts_voice,
        "prompt": str(parsed.get("prompt") or "").strip()[:200],
    }
