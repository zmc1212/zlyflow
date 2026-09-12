from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class H3Skill:
    id: str
    name: str
    description: str
    icon: str
    category: str
    guidance: str


H3_SKILLS: list[H3Skill] = [
    H3Skill(
        id="general",
        name="电影级通用叙事",
        description="标准 MiniMax H3 全模态时序结构，包含镜头运镜、景别推进、环境音效与背景配乐。",
        icon="🎬",
        category="general",
        guidance="""你将通用视频想法扩写为高电影质感、视听协调的 MiniMax H3 标准提示词。
- 画面与运镜：构图优美，合理运用推/拉/摇/移/俯仰/跟随等三维运镜，描述主体的细微动作与光影质感。
- 时序分镜：多镜头时使用 [Shot 1]、[Shot 2] At 00:03.000 等标准切镜语法。
- 音效与配乐：提供真实贴合的环境音效与非剧情背景配乐。""",
    ),
    H3Skill(
        id="minimalist-product-ad",
        name="极简电商产品广告",
        description="提炼产品核心卖点、精致产品光影质感、极简英文文案与节拍卡点运镜。",
        icon="🛍️",
        category="commercial",
        guidance="""遵循 MiniMax H3 极简产品广告短片技能规范（minimalist-product-ad-generator）：
- 视觉风格：极简纯净摄影棚或自然光影场景，突出产品的精工材质、微距质感（如金属磨砂、玻璃通透、流体光泽）。
- 镜头语言：优雅的微距平移（Truck）、慢速推近（Push In）或环绕镜头（Arc Shot），营造高端产品大片氛围。
- 画面文案：画面中如有文字，使用双引号包含极简英文标语（如 "Purity Defined"），严禁乱码。
- 声音设计：清脆的高级物理交互音效（如按键回弹、水滴凝结、盖子合拢声），搭配节奏感强、简约现代的电子/氛围音乐。""",
    ),
    H3Skill(
        id="3d-animation-short",
        name="3D 风格化动画短片",
        description="皮克斯/迪士尼风格化 3D 叙事，强调角色生动表情、肢体表演与戏剧性光影。",
        icon="🧸",
        category="animation",
        guidance="""遵循 MiniMax H3 3D 动画短片技能规范（3d-animation-short-generator）：
- 视觉风格：3D Stylized CG / Pixar-style animation，饱满色彩与体积光，角色具有夸张富有弹性的肢体表演与生动微表情。
- 角色与场景：明确角色的外貌特征与服装，场景具备童话或幻想世界的丰富细节。
- 镜头推进：动态跟随镜头（Tracking Shot）、角色视点（POV）或戏剧性仰俯拍，节奏活泼鲜明。
- 声音设计：富有卡通质感的动作音效（噗嗤、滑行、轻弹）与富有叙事感染力的管弦乐/轻快钢琴配乐。""",
    ),
    H3Skill(
        id="papercraft-stop-motion",
        name="立体纸艺定格解说",
        description="剪纸、立体书、分层纸雕与微缩定格手工肌理，搭配轻快手工音效。",
        icon="✂️",
        category="creative",
        guidance="""遵循 MiniMax H3 立体纸艺定格技能规范（papercraft-stop-motion-explainer）：
- 视觉风格：Handmade papercraft stop-motion, layered diorama, pop-up book texture，显现纸张边缘折痕、厚度感与细微手工定格停顿。
- 动画机制：角色和道具通过剪纸分层抽拉、翻转、升降或折叠展开进行场景转换。
- 镜头设计：微缩摄影机位，浅景深微距视角，带有手工逐帧拍摄的质感。
- 声音设计：沙沙的纸张摩擦、翻页（page turning）、剪刀剪切与木质轻敲等清脆手工物理音效，无多余复杂音。""",
    ),
    H3Skill(
        id="brand-promo-video",
        name="品牌宣传与使用场景",
        description="现代企业与产品品牌调性，快节奏场景切换、产品应用与行动号召。",
        icon="🏢",
        category="commercial",
        guidance="""遵循 MiniMax H3 品牌宣传技能规范（brand-promo-video-generator）：
- 视觉风格：高端商务科技或人文纪实风，现代明亮采光，展现真实使用场景与人物专注神情。
- 节奏与分镜：紧凑的快切（Fast Cuts）与流畅转场，从宏观场景迅速聚焦到核心功能与交互细节。
- 声音设计：清晰有力的环境氛围，搭配具有上升动量（Inspiring crescendo）、现代流行或合成器律动的品牌配乐。""",
    ),
    H3Skill(
        id="music-video-subtitle",
        name="音乐短片与排版字效",
        description="音乐短片与情绪律动，空间立体排版字效与强节奏光影变幻。",
        icon="🎵",
        category="creative",
        guidance="""遵循 MiniMax H3 音乐短片与字效技能规范（music-video-subtitle-generator）：
- 视觉风格：Cinematic music video, stylized neon / moody lighting, dynamic atmosphere。
- 字效设计：将歌词或关键词设计为与场景光影互动的空间排版（3D typography / neon lyric titles in scene）。
- 运镜与节拍：镜头推拉与旋转紧扣音乐重拍（Beat-synced zooms, rhythmic cuts, rotating arc shot）。
- 声音设计：精准描述背景音乐的乐器编配、节奏重音（Drum kick, bass drops）与环境回响。""",
    ),
    H3Skill(
        id="co-op-game-intro",
        name="双人联机游戏片头",
        description="双角色站位与互动、游戏 UI 角色卡片与开场交互动效。",
        icon="🎮",
        category="creative",
        guidance="""遵循 MiniMax H3 双人游戏菜单与片头技能规范（co-op-game-intro-generator）：
- 视觉风格：Co-op game lobby / start menu, stylized 3D or stylized cel-shaded game art, 两个核心角色并排或对峙站立。
- UI 与交互：包含悬浮的游戏玩家卡片（Player 1, Player 2）、状态指示框或发光确认光效。
- 动态表现：角色待机动作（Idle breathing / weapon inspection）随玩家选择做出回应动作。
- 声音设计：未来感或街机风 UI 确认音（Menu beep, lock-in chime），搭配充满战斗或冒险热情的芯片音乐/电子重低音。""",
    ),
    H3Skill(
        id="paper-collage-explainer",
        name="纸拼贴定格解说",
        description="半色调复古纸张撕裂拼贴、报刊插画重组与概念视觉隐喻。",
        icon="📰",
        category="creative",
        guidance="""遵循 MiniMax H3 纸拼贴解说技能规范（paper-collage-explainer-generator）：
- 视觉风格：Halftone paper collage, retro magazine cutouts, textured kraft paper, stop-motion displacement。
- 表现手法：用不同报纸、杂志图层撕裂重叠，组成抽象幽默或深刻的概念视觉隐喻。
- 声音设计：撕纸声（Paper tear）、盖章声（Thud stamp）、打字机敲击声，默认不包含多余 BGM，突出纯正定格物理质感。""",
    ),
    H3Skill(
        id="handdrawn-live-video",
        name="手绘发光实景混合",
        description="手绘发光线条精灵与真实实景空间产生物理碰撞与穿梭追逐。",
        icon="✏️",
        category="creative",
        guidance="""遵循 MiniMax H3 手绘实景混合技能规范（handdrawn-live-video-generator）：
- 视觉风格：Live-action footage overlaid with glowing neon hand-drawn doodle animation / rough sketch strokes。
- 空间互动：发光手绘涂鸦精灵在真实房间/街道中穿梭、跳跃、在物体表面弹跳并投下动态彩色辉光。
- 运镜设计：带有略微延迟的手持跟随镜头（Delayed handheld camera tracking），如同真实摄影师追随发光实体。
- 声音设计：轻微的电火花嗡鸣（Electrical sizzle / magic hum）、真实环境脚步与轻快灵动的音效。""",
    ),
]

H3_SKILLS_BY_ID = {skill.id: skill for skill in H3_SKILLS}

_H3_PROMPT_WRITING_ROOT = Path(__file__).resolve().parent / "h3_prompt_writing"
_SHOT_TIMING_SKILL_ROOT = Path(__file__).resolve().parent / "shot_timing_skill"
_SHOT_CONTINUITY_SKILL_ROOT = Path(__file__).resolve().parent / "shot_continuity_skill"


def load_shot_timing_skill() -> str:
    return (_SHOT_TIMING_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").strip()


def load_shot_timing_guide() -> str:
    return (_SHOT_TIMING_SKILL_ROOT / "references" / "timing-guide.md").read_text(encoding="utf-8").strip()


def load_shot_timing_excerpt() -> str:
    return "\n".join([
        "# Shot timing budget (Seedance-inspired, adapted for MiniMax H3)",
        "Before finalizing each shot:",
        "- Estimate minimum speakable seconds for dialogue (~4 Chinese chars/s normal, ~3/s emotional).",
        "- Budget one primary visible action every 2–3 seconds; do not cram dialogue + walk + turn into 5s.",
        "- Set durationSec to max(speech budget, action budget), clamped 2–15; split the shot if still too tight — never truncate dialogue.",
        "- In promptText, place At 00:XX.XXX beats and start <d> dialogue at the second speech begins.",
    ])


def load_shot_continuity_skill() -> str:
    return (_SHOT_CONTINUITY_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8").strip()


def load_shot_continuity_guide() -> str:
    return (_SHOT_CONTINUITY_SKILL_ROOT / "references" / "continuity-guide.md").read_text(encoding="utf-8").strip()


def load_shot_continuity_excerpt() -> str:
    return "\n".join([
        "# Continuity handoff (Seedance-inspired, adapted for MiniMax H3)",
        "- Treat the ordered storyboard as one continuous edit; every H3 request remains an independently renderable clip that starts at 00:00.",
        "- Draft a miniature scene ledger per beat: visual anchors, opening state, one playable change, closing state.",
        "- continuityIn = English visible state at this clip's 00:00; continuityOut = English final-frame state the next clip can inherit.",
        "- transitionNote = one concise Chinese bridge name (动作匹配切 / 视线匹配切 / 方向匹配切 / 声音桥 / 硬切换场).",
        "- Carry wardrobe, wetness, injury, held props, light, and screen direction forward unless the script changes them.",
        "- Hard-cut intentional time/place/subject jumps; do not fake a seamless physical join.",
        "- Make promptText opening/final beats agree with continuityIn/continuityOut. Never emit film-wide timecodes or [Shot 2+].",
    ])


# Backward-compatible alias used by older tests/imports.
SEEDANCE_CONTINUITY_EXCERPT = load_shot_continuity_excerpt()


def build_shot_timing_polish_prompt() -> str:
    return "\n\n".join([
        "You are the Shot Timing Editor for ZLY AI Video Studio / MiniMax H3.",
        "Input: a complete storyboard JSON (scenes[].shots[]) already split from the script.",
        "Task: polish EVERY shot so dialogue, visible actions, and durationSec fit together.",
        "Return ONLY one JSON object with the SAME schema as the input. Include ALL shots; do not omit unchanged shots.",
        "You may adjust durationSec (2–15), description, promptText, soundscape, soundscapeEn. Do NOT shorten dialogue.",
        "Never truncate dialogue with ellipsis (... or …). If speech does not fit, increase durationSec up to 15s or split into another shot.",
        "Both the dialogue field and the <d> tag in promptText must contain ONLY the pure spoken words — never the character name or emotion label prefix. Extract just the words inside the quotation marks (e.g. script line \"陆沉舟（沉稳）：\\\"好，跟紧我。\\\"\" → dialogue field and <d> tag should both be \"好，跟紧我。\").",
        "Rewrite promptText with [Shot 1] and At 00:XX.XXX beats inside durationSec; put spoken lines in <d>[Language] ...</d>.",
        "When you change timing, add timingNote in Chinese explaining the adjustment (1 short sentence).",
        "Preserve shotNumber order, characterBindings, locationId, propIds, camera, continuity fields, and story meaning.",
        "Do not collapse multiple shots into one. Split only when dialogue cannot fit even at 15s.",
        "Never delete dialogue or mark a shot as silent when dialogue was supplied in the input JSON.",
        "If dialogue exists in a shot, it must appear in both dialogue and promptText <d>; never write Dialogue: none.",
        load_shot_timing_skill(),
        load_shot_timing_guide(),
        STORYBOARD_JSON_CONTRACT,
        STORYBOARD_DIALOGUE_CONTRACT,
    ])


def build_storyboard_continuity_polish_prompt() -> str:
    return "\n\n".join([
        "You are the continuity editor for ZLY AI Video Studio / MiniMax H3.",
        "Input: one ordered continuity window after its timing pass. The user message includes contextShotNumbers and editableShotNumbers metadata.",
        "Context shots are read-only evidence for the incoming handoff. Return ONLY one JSON object with the SAME scenes[].shots[] schema and include every editable shot; context shots may be echoed but will not be written.",
        "Every returned shot MUST include its original global shotNumber. Never renumber shots relative to this window and never omit an editable shot.",
        "You may improve promptText, continuityIn, continuityOut, transitionNote, soundscape, and soundscapeEn ONLY. Preserve story meaning, dialogue, durationSec, shotNumber, shot order, bindings, locations, props, and camera fields.",
        "For every shot after the first, continuityIn must be present. For every shot except the last, continuityOut and transitionNote must be present. The first shot may have continuityIn empty; the final shot may have continuityOut empty. continuityIn and continuityOut MUST be pure English (NO CHINESE, or it triggers TTS bugs).",
        "Make Shot N continuityOut reusable as Shot N+1 continuityIn unless the cut is an explicit hard change of time, place, or subject.",
        "For every same-scene adjacent pair, explicitly carry character positions, screen direction, held props, prop state, weather, light, time, and ongoing sound from the outgoing state into the incoming state. The next prompt's first visible action must be motivated by that incoming state, not jump directly to an unrelated action.",
        "Make promptText independently renderable, but make its opening and final At 00:XX.XXX beats agree with continuityIn and continuityOut. Never use accumulated film timecodes or [Shot 2+].",
        "Do not invent a bridge event just to hide a missing handoff. If the source beat already contains a coordinated reaction, show the causal trigger and the visible response in the next shot's opening state.",
        "When a character cuts, turns, reaches, or moves defensively, state the threat being answered and who or what the action protects. When debris or another object blocks a subject, state the spatial barrier between them and preserve the subjects' screen direction.",
        "Do not invent a new character, costume, prop, dialogue, event, or reference tag. Do not force usePreviousEndFrame; that is a user-controlled visual-anchor setting.",
        "Never shorten dialogue or <d> tags with ellipsis to fit duration; preserve full lines exactly.",
        load_shot_continuity_excerpt(),
        load_shot_continuity_skill(),
        load_shot_continuity_guide(),
        DIRECTOR_STUDIO_ADAPTER,
        STORYBOARD_JSON_CONTRACT,
        STORYBOARD_DIALOGUE_CONTRACT,
        "CONTINUITY WINDOW RESPONSE REMINDER: Return global shotNumber on every returned shot; cover every editableShotNumbers entry exactly once. ContextShotNumbers are read-only and may be omitted or echoed, but their fields are never an instruction to overwrite the stored context shot. Do not change dialogue, durationSec, characterBindings, locationId, propIds, or camera.",
    ])


def build_storyboard_continuity_repair_prompt() -> str:
    """Prompt for the bounded post-QA causal repair pass."""
    return "\n\n".join([
        "You are the causal continuity repair editor for ZLY AI Video Studio / MiniMax H3.",
        "Input: a JSON object with storyContext and a bounded list of adjacent shot pairs flagged by deterministic QA.",
        "Return ONLY {\"repairs\":[...]} and no explanation outside JSON.",
        "Repair the causal handoff at each requested boundary without changing the story's plot or adding a new character, prop, dialogue line, location, or unrelated event.",
        "The incoming shot must visibly or audibly inherit the outgoing shot's last state before starting its next action. If a character attacks, turns, reaches, flees, or blocks, show the threat or trigger being answered in the opening beat and preserve who protects whom and the screen direction.",
        "If the existing target shot contains two independent playable changes that cannot be made coherent in one clip, set status to needs_resplit and leave the patch empty. This pass reports that requirement; it must not invent a fake bridge or change duration.",
        "For a repairable pair, use fromShotPatch only for continuityOut, transitionNote, soundscape, and soundscapeEn; use toShotPatch for promptText, continuityIn, continuityOut, transitionNote, soundscape, and soundscapeEn.",
        "Never return or modify dialogue, durationSec, shotNumber, shot order, characterBindings, locationId, propIds, or camera. Every returned pair must use the original global fromShot/toShot numbers.",
        "promptText must remain one independently renderable [Shot N] clip whose local timeline starts at 00:00.000. Its opening action must agree with toShotPatch.continuityIn. Keep any existing dialogue exactly as supplied and keep its <d> tag synchronized.",
        "continuityIn, continuityOut, and soundscapeEn must be pure English. transitionNote is concise Chinese for the editor and is not pasted into H3.",
        "Output schema:",
        '{"repairs":[{"fromShot":5,"toShot":6,"status":"repaired","fromShotPatch":{"continuityOut":""},"toShotPatch":{"promptText":"","continuityIn":"","continuityOut":"","transitionNote":"","soundscape":"","soundscapeEn":""},"reason":""}]}',
        "When status is needs_resplit, return empty patches and a short reason. Cover every requested pair exactly once; do not return any other pair.",
        load_shot_continuity_excerpt(),
        load_shot_continuity_skill(),
        load_shot_continuity_guide(),
        STORYBOARD_DIALOGUE_CONTRACT,
    ])


def build_clarify_questions_prompt() -> str:
    beat_option_items = "、".join(
        '{"label":"%s","value":"%s"}' % (item["label"], item["value"])
        for item in BEAT_COUNT_OPTIONS
    )
    return "\n\n".join([
        "你是短剧导演，正在为用户的创意做开机前的方向规划。根据用户的一句话创意，提出 2-3 个真正决定剧情走向的问题。",
        "只问会改变剧情走向的创作方向问题，并让各题覆盖不同维度，例如：结局倒向、故事基调、主角动机、冲突升级方式、叙事视角、时空设定。禁止重复维度，禁止问画面风格、配音、台词语言等执行细节（镜头数量除外，见下）。",
        "每个问题给 3-4 个具体、可直接采用的选项，其中一个标记 recommended=true（你认为最适合这个创意的方向）。选项 label 用简体中文短语，value 与 label 相同。",
        "方向问题之后，必须在 questions 最后输出一道固定题：id 固定为 \"beat_count\"，question 固定为「" + BEAT_COUNT_QUESTION_TEXT + "」，why 用一句话结合该创意说明镜头数量如何决定成片时长与节奏，options 固定为：" + beat_option_items + "（value 必须用这些纯数字，不得改动），并根据创意体量给其中一个标 recommended=true；allowCustom 固定为 true，用户可自填其他数量。",
        "问题与选项必须贴合用户创意的具体内容，禁止空泛模板问题（beat_count 的 why 除外）。",
        '必须且仅输出一个合法 JSON 对象：{"questions":[{"id":"q1","question":"","why":"一句话说明这个问题如何影响剧情走向","options":[{"label":"","value":"","recommended":true}],"allowCustom":true},{"id":"beat_count","question":"' + BEAT_COUNT_QUESTION_TEXT + '","why":"","options":[{"label":"约 8 个镜头 · 1 分钟内","value":"8"},{"label":"约 16 个镜头 · 1-2 分钟","value":"16","recommended":true},{"label":"约 30 个镜头 · 3 分钟左右","value":"30"},{"label":"约 50 个镜头 · 完整短剧","value":"50"}],"allowCustom":true}]}',
    ])


BEAT_COUNT_QUESTION_ID = "beat_count"

# 镜头数量题的固定档位：value 必须是纯数字，前端与后端都按这个约定解析。
BEAT_COUNT_OPTIONS: list[dict[str, str]] = [
    {"label": "约 8 个镜头 · 1 分钟内", "value": "8"},
    {"label": "约 16 个镜头 · 1-2 分钟", "value": "16"},
    {"label": "约 30 个镜头 · 3 分钟左右", "value": "30"},
    {"label": "约 50 个镜头 · 完整短剧", "value": "50"},
]
BEAT_COUNT_DEFAULT_RECOMMENDED = "16"
BEAT_COUNT_QUESTION_TEXT = "这部剧拍多少个镜头（Beat）？"


def build_beat_count_question(recommended_value: str = BEAT_COUNT_DEFAULT_RECOMMENDED) -> dict[str, Any]:
    """Deterministic 镜头数量 clarify question; the LLM only picks the recommended tier."""
    recommended = str(recommended_value) if str(recommended_value) in {item["value"] for item in BEAT_COUNT_OPTIONS} else BEAT_COUNT_DEFAULT_RECOMMENDED
    options = []
    for item in BEAT_COUNT_OPTIONS:
        option = {"label": item["label"], "value": item["value"]}
        if option["value"] == recommended:
            option["recommended"] = True
        options.append(option)
    return {
        "id": BEAT_COUNT_QUESTION_ID,
        "question": BEAT_COUNT_QUESTION_TEXT,
        "why": "镜头数量决定成片时长与节奏：每个镜头约 3-8 秒，确认后剧本会按这个数量拆写节拍。",
        "options": options,
        "allowCustom": True,
    }


def normalize_clarify_questions(parsed_questions: Any) -> list[dict[str, Any]]:
    """Normalize raw LLM clarify output: cap direction questions, force the beat_count question last."""
    questions: list[dict[str, Any]] = []
    beat_recommended = BEAT_COUNT_DEFAULT_RECOMMENDED
    if isinstance(parsed_questions, list):
        for item in parsed_questions:
            if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                continue
            if str(item.get("id") or "").strip() == BEAT_COUNT_QUESTION_ID:
                for option in item.get("options") or []:
                    if isinstance(option, dict) and option.get("recommended"):
                        value = str(option.get("value") or "").strip()
                        if value in {entry["value"] for entry in BEAT_COUNT_OPTIONS}:
                            beat_recommended = value
                continue
            options = []
            for option in item.get("options") or []:
                if not isinstance(option, dict):
                    continue
                label = str(option.get("label") or "").strip()
                if not label:
                    continue
                options.append({
                    "label": label,
                    "value": str(option.get("value") or label).strip() or label,
                    "recommended": bool(option.get("recommended")),
                })
            if not options:
                continue
            questions.append({
                "id": str(item.get("id") or f"q{len(questions) + 1}"),
                "question": str(item.get("question")).strip(),
                "why": str(item.get("why") or "").strip(),
                "options": options[:4],
                "allowCustom": item.get("allowCustom") is not False,
            })
    questions = questions[:3]
    questions.append(build_beat_count_question(beat_recommended))
    return questions


def build_script_agent_prompt(target_beats: int | None = None) -> str:
    if target_beats and target_beats > 0:
        scale_line = (
            f"fullStory 中文，总 Beat 数量必须约为 {target_beats} 个（上下浮动不超过 2 个）。"
            "情节按这个数量规划节奏：禁止把多个动作合并进一个 Beat 来减少数量，也禁止超出该数量继续加戏。"
            "必须使用基于 Seedance Scene Ledger（场景账本）的节拍式写法："
        )
    else:
        scale_line = "fullStory 800-1500 字中文。必须使用基于 Seedance Scene Ledger（场景账本）的节拍式写法："
    return "\n\n".join([
        "把一句话扩成可拍的 AI 短剧剧本。输出 {\"title\":\"\",\"summary\":\"\",\"fullStory\":\"\"}。",
        scale_line,
        "1. 【禁止传统段落式动作】：严禁把多个动作打包成一段。必须将情节拆解为独立的『动作节拍 (Beat)』。",
        "2. 【One Playable Change】：每个 Beat 只能发生一个肉眼可见的物理变化（如：角色 A 拔剑，或角色 B 倒下）。",
        "3. 【物理状态继承】：下一个 Beat 必须严格继承上一个 Beat 的人物站位、手持道具、环境光影和残骸。禁止凭空变出未交代的道具，禁止空间逻辑瞬移。",
        "4. 【视觉重于对白】：优先用动作、特写来推进，对白只作为辅助。",
        "请参考以下的格式输出 fullStory：\n【场景名】\n视觉锚点：交代基础站位与环境状态。\nBeat 1：单一动作...\nBeat 2：单一动作...\n对白：...",
        "禁止只写一段摘要。不要发明未给出的品牌、产品参数或真人形象。",
        "Follow the Seedance-inspired scene-ledger method below while writing Chinese scenes:",
        "- Each scene block should make opening visual state, one dramatic beat, and closing visual state obvious.",
        "- Preserve dialogue verbatim once written; later agents must not lose spoken lines.",
        "- Prefer observable action over abstract emotion labels so storyboard continuity can inherit positions, props, light, and direction.",
        load_shot_continuity_excerpt(),
    ])


STORYBOARD_DIALOGUE_CONTRACT = """DIALOGUE ASSIGNMENT (non-negotiable):
- Every speakable line in the source script must appear exactly once in some shot's dialogue field, using the user's original words (no translation).
- Count script lines such as 李元婴：（自言自语）台词 or 同门甲：台词. Each such line needs its own shot OR shares the shot where that action happens simultaneously.
- Self-talk (自言自语), muttering, and voice-over count as dialogue — never treat them as silent action-only shots.
- When a character speaks while walking, reacting, or holding a prop, put BOTH the visible action AND the spoken line in the SAME shot's dialogue; do not split into a silent establishing shot plus a later dialogue shot.
- dialogue is the TTS/subtitle source of truth. BOTH the dialogue field and the <d> tag in promptText must contain ONLY the pure spoken words. If the script line is formatted as "角色名（情绪）：\"台词\"", extract only the quoted text for both fields (e.g. script line "陆沉舟（沉稳）：\"好，跟紧我。\"" → dialogue field is "好，跟紧我。", and <d> tag is <d>[Chinese] 好，跟紧我。</d>).
- Never write Dialogue: none, no dialogue, or leave dialogue empty when the script gives that beat spoken words.
- Pure reaction shots with no script line may stay silent; do not invent dialogue.
- Prefer one spoken line per shot; if two characters exchange lines in one beat, split into two shots unless the script explicitly groups them.
- Never truncate dialogue with ellipsis (... or …) to fit durationSec. Extend duration up to 15s or split the shot; dialogue and <d> must contain the full line.
"""

DIRECTOR_STUDIO_ADAPTER = """Director Studio adapter (keep this even while following the official skill):
- Each shot is submitted as its own MiniMax H3 job, usually T2VA. The compiler later adds I2VA/Ref2VA wrappers when keyframes or character stills exist.
- promptText: English H3 shot prose from the official guide. Write one independent [Shot 1] clip covering style, composition, subjects, environment, action, camera (motion type + amplitude + speed), and dialogue. Do not wrap integrated_multimodal_description / overall_soundscape / non_diegetic_music in JSON; the compiler adds those fields.
- title, description, soundscape: Chinese for the user-facing storyboard card. Never copy promptText into description.
- soundscapeEn: a separate English H3 soundscape sentence covering ambience and physical action sounds; do not repeat dialogue. Keep soundscape as the Chinese card summary.
- dialogue: keep the user's original spoken words verbatim, but ALWAYS strip any leading character name or emotion label (e.g. strip the "陆沉舟（低语）：" prefix). Inside promptText use <d>[Chinese] SPOKEN_WORDS</d>. BOTH the dialogue field and the <d> tag must contain ONLY the actual words spoken. Every script spoken line must land here — including 自言自语 / 旁白 / 画外音.
- If the script gives speech during an action, dialogue and that action belong in one shot; silent establishing shots are only for beats with zero script dialogue.
- Use <d> only for audible dialogue or lyrics. For a computer, phone, sign, or other visible written text, describe it as visible on-screen text in prose and do not wrap it in <d>.
- durationSec: integer 2–15. Budget speech + action using the shot-timing skill; default 5 only when the beat is truly short.
- continuityIn / continuityOut: MUST BE PURE ENGLISH boundary states (NO CHINESE ALLOWED, or else it triggers TTS bugs). They are not plot summaries: state composition, character/prop pose, motion direction, light/time and ongoing sound needed to connect the cut.
- transitionNote: concise Chinese editorial note for the incoming cut; name the bridge or the deliberate hard cut. Keep it user-facing and do not put it in promptText.
- characterNames and locationName must copy the exact proper nouns and original writing system used by the source script. Never translate or transliterate names (for example, keep 李明 instead of Li Ming).
- Every promptText is a standalone clip whose local timeline starts at 00:00. Use [Shot 1] or no shot tag; never emit [Shot 2+], an accumulated film timecode, or phrases such as "At 00:11.000, the camera cuts to".
"""


def load_h3_prompt_writing_skill() -> str:
    return (_H3_PROMPT_WRITING_ROOT / "SKILL.md").read_text(encoding="utf-8").strip()


def load_h3_prompt_writing_guide(*, mode: str = "base") -> str:
    name = "ref-en.txt" if mode == "ref" else "base-en.txt"
    return (_H3_PROMPT_WRITING_ROOT / "references" / name).read_text(encoding="utf-8").strip()


SEEDANCE_DIRECTOR_RULES = """SEEDANCE DIRECTOR RULES (CRITICAL FOR promptText):
- Rule 1: Subject First. NEVER start promptText with camera parameters or vague adjectives like "Cinematic, 4k". Start EXACTLY with WHO is doing WHAT (e.g., "A woman in a wool cardigan sits at the table, reading a letter").
- Rule 2: Strict Information Hierarchy. The promptText MUST flow in this exact order: 
  1. Visual Anchors & Subject Action (who, what, where)
  2. Camera Motion (e.g., "The camera pushes in...")
  3. Lighting & Atmosphere (e.g., "Left side overcast window light...")
- Rule 3: 1 Beat = 1 Shot. Map EVERY SINGLE BEAT from the Chinese script into EXACTLY ONE independent shot. Do not merge multiple consecutive beats into one mega-shot.
- Rule 4: Director's Intent. Before writing, ask yourself what the dramatic intent of this shot is, and use the camera and lighting to serve that specific intent.
"""


STORYBOARD_JSON_CONTRACT = """OUTPUT CONTRACT (non-negotiable):
- Return ONLY one JSON object. Do not return integrated_multimodal_description / overall_soundscape / non_diegetic_music as the top-level format; the compiler adds those later.
- Split the provided script excerpt into shots. DO NOT invent extra shots; follow the STRICT 1:1 MAPPING rule exactly.
- STRICT 1:1 MAPPING: Map EVERY single action beat (Beat 1, Beat 2) from the Chinese script into EXACTLY ONE independent shot. Do not merge multiple beats. Never collapse the story.
- title / description / soundscape: Chinese for the storyboard card. promptText: English H3 shot body for one [Shot 1] clip whose local timeline starts at 00:00.
- Schema: {"_thinking":"分析核心动作与视听风格（强制在此输出你的思考过程，限200字内）","scenes":[{"title":"","locationName":"","shots":[{"title":"","description":"","promptText":"","dialogue":"","characterNames":[],"locationName":"","durationSec":5,"camera":{},"soundscape":"","soundscapeEn":"","timingNote":"","continuityIn":"","continuityOut":"","transitionNote":""}]}]}
- durationSec must fit dialogue + actions (see shot-timing skill). Prefer 4–8 for simple beats; extend to 7–12 when dialogue has ≥10 Chinese characters or multiple actions.
- While splitting, draft continuityIn / continuityOut / transitionNote for adjacent cuts using the continuity skill; a later continuity pass may refine them.
- Before finishing, verify every script dialogue line is assigned to a shot's dialogue field (see DIALOGUE ASSIGNMENT).
"""


def load_h3_storyboard_writing_excerpt() -> str:
    return "\n".join([
        "# Video Prompt Writing Guide excerpt (for promptText only)",
        "Write each promptText as one independent [Shot 1] clip. Do not reply with integrated_multimodal_description as the top-level format.",
        "Camera motion examples:",
        "The camera pushes in with small amplitude at slow speed toward the folded letter in her hands.",
        "The camera pans right with large amplitude at fast speed, revealing the open doorway.",
        "The camera holds a static shot as the runner exits the frame.",
        "Dialogue inside promptText uses <d>[Chinese] ...</d> and keeps the original words.",
    ])


def build_h3_storyboard_agent_prompt() -> str:
    return "\n\n".join([
        SEEDANCE_DIRECTOR_RULES,
        STORYBOARD_JSON_CONTRACT,
        STORYBOARD_DIALOGUE_CONTRACT,
        "Follow the official MiniMax H3 h3-prompt-writing skill below ONLY as the writing standard for each shot's promptText.",
        "Follow the shot-timing skill below when choosing durationSec and writing At 00:XX.XXX beats in promptText.",
        "Follow the continuity skill below when drafting opening/closing handoffs between adjacent shots.",
        DIRECTOR_STUDIO_ADAPTER,
        load_shot_timing_excerpt(),
        load_shot_continuity_excerpt(),
        load_h3_prompt_writing_skill(),
        load_h3_storyboard_writing_excerpt(),
        SEEDANCE_DIRECTOR_RULES,
        STORYBOARD_JSON_CONTRACT,
        STORYBOARD_DIALOGUE_CONTRACT,
    ])


def build_h3_final_prompt_polish_prompt(mode: str) -> str:
    """Final H3 editor prompt selected from the actual image/reference relationship."""
    normalized_mode = str(mode or "T2VA").upper()
    is_ref2va = normalized_mode == "REF2VA"
    mode_instructions = {
        "T2VA": "Use the T2VA three-field format; no image-alignment instruction is allowed.",
        "I2VA": "Use the I2VA first-frame alignment instruction followed by the three core fields.",
        "FL2VA": "Use the FL2VA first-and-last-frame alignment instruction and describe one continuous path between them.",
        "L2VA": "Use the L2VA last-frame alignment instruction and describe how the video converges on it.",
        "REF2VA": "Use the Ref2VA six-section format.",
    }
    shared = [
        f"You are the final MiniMax H3 {normalized_mode} prompt editor. Rewrite the supplied draft into one complete, production-ready H3 prompt.",
        "Return ONLY the final prompt. Do not return JSON, Markdown fences, analysis, or a preface.",
        mode_instructions.get(normalized_mode, mode_instructions["T2VA"]),
        "Keep the requested duration plausible. Do not pad with invented events. Use <d> only for audible dialogue or lyrics; describe visible screen, phone, and sign text in prose in its original language.",
        "Align spoken lines and visible beats to the shot duration using the shot-timing skill (At HH:MM.SSS markers inside the clip length).",
    ]
    if is_ref2va:
        shared.extend([
            "The draft's <Subject N> and <Picture N> labels are the actual uploaded-reference mapping. Keep their numbering and meaning exactly; never invent, renumber, merge, or omit a supplied reference label.",
            "Do the semantic writing yourself: use each relevant <Subject N> naturally at its first visible appearance in detailed_description, with its referenced visual characteristics, placement, and action. Do not mechanically replace character names with labels.",
            "Use <Picture N> only according to the official guide. A picture used only to define a reusable subject belongs inside that subject's definition; do not turn it into an unrelated keyframe anchor.",
            "Follow the official MiniMax H3 Ref2VA guide below exactly.",
        ])
    else:
        shared.append("Follow the official MiniMax H3 base-mode guide below exactly.")
    shared.extend([
        load_shot_timing_excerpt(),
        load_shot_timing_guide(),
        load_h3_prompt_writing_skill(),
        load_h3_prompt_writing_guide(mode="ref" if is_ref2va else "base"),
    ])
    return "\n\n".join(shared)


def build_h3_ref2va_polish_prompt() -> str:
    """Backward-compatible Ref2VA specialization."""
    return build_h3_final_prompt_polish_prompt("REF2VA")


def build_h3_split_script_prompt(*, script_mode: str = "literal") -> str:
    mode_rules = ("Literal mode: preserve every original dialogue word-for-word, keep event order, and do not add dialogue, characters, props, or events. Only divide the supplied material into shots."
                  if script_mode == "literal" else
                  "Creative mode: you may expand connective action and dialogue, but preserve all original dialogue verbatim and mark additions in prompt prose as AI-added.")
    return f"""Follow the official MiniMax H3 h3-prompt-writing skill below.
{DIRECTOR_STUDIO_ADAPTER}
{load_shot_continuity_excerpt()}
Split the user's script into a coherent shot list. Shots may continue the story, but each prompt field must be independently submittable to MiniMax H3 as a single [Shot 1] clip.
{mode_rules}
Keep adjacent cuts inherit opening/closing visual state in the English prompt prose when helpful.
title 用中文。prompt 字段写英文 H3 镜头正文。sfx 字段写中文环境声给用户看。

{load_h3_prompt_writing_skill()}

{load_h3_prompt_writing_guide(mode="base")}

必须且仅输出严格合法的 JSON 对象：
{{
  "project_title": "短片标题",
  "summary": "故事一句话梗概",
  "shots": [
    {{
      "shot_number": 1,
      "title": "中文场景镜头简述",
      "prompt": "English MiniMax H3 shot body",
      "scale": "WS",
      "movement": "zoom_in",
      "angle": "eye_level",
      "speed": "smooth",
      "lighting": "cinematic_soft",
      "sfx": "中文环境音效"
    }}
  ]
}}
严禁输出任何思考过程或解释文字，直接输出 JSON。"""


def build_h3_batch_fission_prompt(*, count: int, duration_sec: int, aspect_ratio: str) -> str:
    return "\n".join([
        "AGENT_ID: batch_fission",
        "Follow the official MiniMax H3 h3-prompt-writing skill. Split the theme into distinct short T2VA scripts.",
        f"Exactly {count} items. title and description are Chinese for the user-facing card.",
        "script must be a complete English T2VA prompt ready to submit: integrated_multimodal_description, overall_soundscape, non_diegetic_music.",
        f"Duration about {duration_sec} seconds, aspect {aspect_ratio}. One dominant action and camera move unless the official guide's multi-shot example is needed.",
        "Preserve original dialogue inside <d>[Chinese] ...</d> or the matching language tag.",
        'Output {"items":[{"title":"","description":"","script":""}]} and nothing else.',
        "",
        load_h3_prompt_writing_skill(),
        "",
        load_h3_prompt_writing_guide(mode="base"),
    ])


def list_h3_skills_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "icon": skill.icon,
            "category": skill.category,
        }
        for skill in H3_SKILLS
    ]


def build_h3_system_prompt(
    skill_id: str | None = None,
    reference_count: int = 0,
    media_type: str = "video",
    workflow_name: str | None = None,
) -> str:
    """Build a specialized system prompt integrating MiniMax H3 skills and multimodal prompt rules."""
    if media_type != "video":
        return """你是一位顶级的 AI 绘画与图像生成提示词专家（精通 Midjourney、Stable Diffusion、FLUX、GPT-Image 等模型）。
你的任务是将用户输入的简短图像创意，优化为具有丰富细节、高审美构图与强烈艺术氛围的高质量提示词。

优化原则：
1. 画面主体：精准刻画主体的形态、材质、服饰、姿态与神情。
2. 构图与视角：明确构图法则（黄金分割、对称构图、主观视角等）与空间景深。
3. 光影与色彩：细化光源方向、光质（柔光、强光、戏剧性高光）与色彩搭配方案。
4. 细节与质感：增强材质纹理细节与环境真实感/艺术质感。
5. 参考图标记：若原提示词中包含 `<Picture 1>`、`<Picture 2>` 等参考图标记，必须在对应主体位置原样保留这些标记，不得删除或更改序号。
6. 输出格式：直接输出优化后的提示词文本，严禁包含任何前言、解释、分析或 markdown 格式块。输出纯文本。"""

    selected_skill = H3_SKILLS_BY_ID.get(skill_id or "general", H3_SKILLS[0])

    mode_alignment_instruction = ""
    if reference_count == 1:
        mode_alignment_instruction = """
【当前任务模式：I2VA (单图首帧生成)】
- 必须在输出第一行放置 MiniMax H3 官方首帧对齐声明：
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
- [Shot 1] 必须基于 <Picture 1> 中确立的主体人物/物品、服饰、构图与环境展开，描述其随后的动作发展与镜头运动。
"""
    elif reference_count >= 2:
        mode_alignment_instruction = f"""
【当前任务模式：Ref2VA (多参考图生成，共 {reference_count} 张参考图)】
- 必须在分镜描述中依次合理引用并标注 <Picture 1> 到 <Picture {reference_count}>，不得遗漏或随意篡改序号。
- 明确指出各个参考图所对应的主体特征、外观服饰、场景环境或关键帧位置。
"""
    else:
        mode_alignment_instruction = """
【当前任务模式：T2VA (纯文本生成视频)】
- 无需首行对齐声明，直接以 integrated_multimodal_description 开头构建完整的视听时间线。
"""

    guides = [load_h3_prompt_writing_skill(), load_h3_prompt_writing_guide(mode="base")]
    if reference_count >= 2:
        guides.append(load_h3_prompt_writing_guide(mode="ref"))
    official = "\n\n".join(guides)

    return f"""Follow the official MiniMax H3 h3-prompt-writing skill. You rewrite the user's idea into a production-ready H3 prompt.

Current style skill: [{selected_skill.name}] ({selected_skill.description})
{selected_skill.guidance}

{mode_alignment_instruction}

{official}

Output only the final prompt text. No preamble, no markdown fences."""
