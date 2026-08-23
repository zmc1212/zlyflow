from __future__ import annotations

from dataclasses import dataclass
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

    return f"""你是一位精通 MiniMax H3（海螺视频/H3大模型）的专业提示词架构专家与导演。
你熟练掌握 MiniMax H3 官方的 Prompt 技能体系规范（h3-prompt-writing 及各风格技能），你的任务是将用户的初始创意扩写为工业级、高质量、格式严格符合 MiniMax H3 标准的提示词。

当前应用的风格技能：【{selected_skill.name}】（{selected_skill.description}）
技能专项指导原则：
{selected_skill.guidance}

{mode_alignment_instruction}

【MiniMax H3 提示词核心结构规范】
最终输出文本必须包含以下三段式结构（英文段落标识）：

integrated_multimodal_description: [Shot 1] 画面风格描述（如 Live-action, cinematic / 3D Stylized animation），主体外观与初始构图。运镜动作（采用“运动类型 + 幅度 + 速度”的标准表达，如 The camera pushes in with small amplitude at slow speed...）。主体动作过程、环境光影。如有人物说话，使用标号 (S1) 并用 <d>[语言] 台词内容</d> 格式包裹。如有第二镜头，使用 [Shot 2] At 00:03.500, the camera cuts to...

overall_soundscape: 用 1-3 句连贯文字总结全片的环境音、物理交互声（如脚步、风雨、摩擦声、按键声等），不重复台词。

non_diegetic_music: 用 1-2 句文字描述观众能听到的背景配乐（乐器配器、节奏速度、渐强渐弱），避免空洞情绪词，无配乐时写 N/A。

【三维运镜语法标准库】
- 运动类型：Zoom In / Zoom Out (变焦), Push In / Pull Out (推/拉), Pan Left / Pan Right (摇镜头), Truck Left / Truck Right (平移), Tilt Up / Tilt Down (俯仰), Pedestal Up / Pedestal Down (升降), Arc Shot (弧形环绕), Tracking Shot (跟随跟踪), Static Shot (固定镜头), POV (第一人称主观), Roll Clockwise / Counterclockwise (旋转)。
- 幅度：with small amplitude / with large amplitude。
- 速度：at slow speed / at fast speed。

【严格输出约束】
1. 语言：除人物台词 `<d>` 内的内容可保留中文或指定语言外，描述主体、运镜、soundscape 和 music 请输出标准英语（或中英高质量结合，优先 MiniMax 最擅长的英语结构体）。
2. 直接输出最终提示词纯文本，严禁包含任何前言、问候、解释分析或 markdown ``` 代码块包裹。"""
