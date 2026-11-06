export type StudioToolStatus = "available" | "coming_soon" | "planned"
/** 分类对齐即梦 AI 工具页：全部 / 精选 / 视频 / 图片 / 镜头与动态。 */
export type StudioToolCategory = "featured" | "video" | "image" | "camera"

/** 功能示例：左右对比的「原片 vs 效果」素材（视频或拼图），首次打开工具时自动播放。 */
export type StudioToolDemo = {
  kind: "video" | "image"
  /** frontend/public 下的静态对比素材绝对路径。 */
  src: string
  /** 弹框内一句说明：输入什么、看到什么。 */
  caption: string
}

export type StudioTool = {
  id: string
  title: string
  /** 工具中心卡片与工具页头部的完整介绍。 */
  description: string
  /** 首页多功能墙与工具中心卡片上的一句短语。 */
  tagline: string
  /** available 工具指向真实页面；占位工具也登记唯一路径，但不可路由。 */
  path: string
  /** 前端图标键；由调用方映射到具体图标组件，占位工具用 generic。 */
  icon: "prompt-reverse" | "motion-transfer" | "character-replace" | "action-shot" | "digital-human" | "lip-sync" | "partial-retake" | "keyframe-narrative" | "depth-capture" | "video-upscale" | "face-restore" | "face-swap" | "stem-split" | "image-bg-remove" | "image-layer-split" | "photo-edit" | "image-inpaint" | "image-eraser" | "image-outpaint" | "generic"
  status: StudioToolStatus
  /** 工具中心分组，同时决定分类 chips 过滤。 */
  category: StudioToolCategory
  /** 照片封面，public 下的绝对路径；首页多功能墙与工具中心共用。 */
  cover: string
  /** 功能示例对比素材；缺省则首次打开不弹示例框。 */
  demo?: StudioToolDemo
  /** 首页多功能墙前两位的深青高亮卡。 */
  highlight?: boolean
}

/** 状态角标文案；工具中心与首页多功能墙共用。 */
export const TOOL_STATUS_LABEL: Record<StudioToolStatus, string> = {
  available: "可用",
  coming_soon: "即将上线",
  planned: "规划中",
}

export const TOOL_CATEGORY_LABEL: Record<StudioToolCategory, string> = {
  featured: "精选",
  video: "视频",
  image: "图片",
  camera: "镜头与动态",
}

export const TOOL_CATEGORY_ORDER: StudioToolCategory[] = ["featured", "video", "image", "camera"]

/**
 * 工作台「AI 工具」注册表：工具中心、生成页多功能墙都从这里渲染。
 * 新工具在这里登记一个条目并把 status 改为 available 即可上线；
 * 封面放在 frontend/public/tool-covers/ 下以 id 命名。
 */
export const STUDIO_TOOLS: StudioTool[] = [
  {
    id: "prompt-reverse",
    title: "提示词反推",
    description: "上传图片，解析画面内容与镜头语言，生成可编辑的中英文提示词，为下一次创作提供参考。",
    tagline: "解析画面，反推可编辑提示词",
    path: "/tools/prompt-reverse",
    icon: "prompt-reverse",
    status: "available",
    category: "featured",
    cover: "/tool-covers/prompt-reverse.jpg",
    highlight: true,
  },
  {
    id: "motion-transfer",
    title: "动作迁移",
    description: "三种迁移方式任选：点选人物替换并保留场景与音乐、骨架驱动单人复刻、多人角色图直移动作视频的动作运镜与原声。",
    tagline: "可选人物替换 / 骨架 / 多人直迁",
    path: "/tools/motion-transfer",
    icon: "motion-transfer",
    status: "available",
    category: "camera",
    cover: "/tool-covers/motion-transfer.jpg",
    demo: { kind: "video", src: "/tool-demos/motion-transfer.mp4", caption: "左侧为上传的动作原片，右侧为替换人物后的迁移效果：场景、运镜与音乐保持不变。" },
    highlight: true,
  },
  {
    id: "character-replace",
    title: "视频换人",
    description: "上传一段原片视频和 1-6 张角色形象图，按顺序把视频里的表演者换成你的角色；动作、表情、运镜、场景与原声一并保留，一句话即可重演同一段戏。",
    tagline: "换掉主角，重演同一段表演",
    path: "/tools/character-replace",
    icon: "character-replace",
    status: "available",
    category: "camera",
    cover: "/tool-covers/character-replace.jpg",
    demo: { kind: "video", src: "/tool-demos/character-replace.mp4", caption: "左侧为老电影原片（元华下楼名场面），右侧为换成女主后的效果：楼梯场景、运镜与动作节奏完全保留。" },
  },
  {
    id: "action-shot",
    title: "打斗镜头",
    description: "上传 1-9 张角色与场景参考图，用一句话描述动作节拍，生成连贯的拳脚、兵器或法术打斗，带原生音效；单条最长 10 秒。",
    tagline: "一句话生成连贯打斗动作",
    path: "/tools/action-shot",
    icon: "action-shot",
    status: "available",
    category: "camera",
    cover: "/tool-covers/action-shot.jpg",
  },
  {
    id: "digital-human",
    title: "数字人",
    description: "上传一张人物形象图和一段口播音频，生成口型与语音精确同步的说话视频，一句话就能让照片开口。",
    tagline: "照片 + 配音，让人物开口说话",
    path: "/tools/digital-human",
    icon: "digital-human",
    status: "available",
    category: "video",
    cover: "/tool-covers/digital-human.jpg",
    demo: { kind: "video", src: "/tool-demos/digital-human.mp4", caption: "左侧为上传的单张人物形象图，右侧为配音驱动后的数字人成片：身份、服装与背景保持不变，口型与语音精确同步。" },
  },
  {
    id: "video-upscale",
    title: "视频超分",
    description: "低清视频一键放大 2 倍：RTX 秒级增强，或 SeedVR2 生成式补回细节。",
    tagline: "低清视频一键增强画质",
    path: "/tools/video-upscale",
    icon: "video-upscale",
    status: "available",
    category: "featured",
    cover: "/tool-covers/video-upscale.jpg",
    demo: { kind: "video", src: "/tool-demos/video-upscale.mp4", caption: "左侧为低清原片，右侧为 2x 高清增强后的画面，细节由模型补回。" },
  },
  {
    id: "face-restore",
    title: "人脸高清修复",
    description: "选择视频中的人脸，用 KEEP 修复模糊五官，保留其他人物、身体、背景与原声。",
    tagline: "选中人脸，修复模糊五官",
    path: "/tools/face-restore",
    icon: "face-restore",
    status: "available",
    category: "video",
    cover: "/tool-covers/face-restore.jpg",
  },
  {
    id: "face-swap",
    title: "角色替换",
    description: "上传一张角色形象图和一段原片视频，把原片里主要人物的脸换成该角色身份，逐帧贴合动作、表情与口型，保留原片背景、运镜和声音。",
    tagline: "换头修脸，保留原片一切",
    path: "/tools/face-swap",
    icon: "face-swap",
    // 2026-11-04 实测遮脸/多人帧残影明显，暂从入口下线；后端 runner 保留待优化。
    // 下线期间不挂 demo：示例角标只在 available 时渲染，恢复上线时再补回。
    status: "coming_soon",
    category: "video",
    cover: "/tool-covers/face-swap.jpg",
  },
  {
    id: "stem-split",
    title: "人声/伴奏分离",
    description: "上传音频或视频，一键分离出干净的人声与伴奏两条音轨，用于清唱提取、伴奏制作与语音增强。",
    tagline: "人声伴奏，一键分开",
    path: "/tools/stem-split",
    icon: "stem-split",
    status: "available",
    category: "video",
    cover: "/tool-covers/stem-split.jpg",
  },
  {
    id: "lip-sync",
    title: "口型同步",
    description: "上传已有视频与目标音频，让人物口型精准匹配新配音，画面身份与场景保持不变。",
    tagline: "让口型精准匹配配音",
    path: "/tools/lip-sync",
    icon: "lip-sync",
    status: "available",
    category: "video",
    cover: "/tool-covers/lip-sync.jpg",
    demo: { kind: "video", src: "/tool-demos/lip-sync.mp4", caption: "左侧为原视频口型，右侧为按新配音重新驱动的口型：人物身份与场景保持不变，仅嘴部动作匹配新音频。" },
  },
  {
    id: "partial-retake",
    title: "视频局部重拍",
    description: "上传原片和遮罩图，把遮罩区域修复为与原片一致的内容（去瑕疵、补遮挡、画面清理），其余画面逐帧保持原样，音轨不变。",
    tagline: "框选区域，精准修复",
    path: "/tools/partial-retake",
    icon: "partial-retake",
    status: "available",
    category: "featured",
    cover: "/tool-covers/partial-retake.jpg",
    demo: { kind: "video", src: "/tool-demos/partial-retake.mp4", caption: "左侧为带水印的原片，右侧为框选遮罩后的修复效果：仅遮罩区域被无缝重建，其余画面逐帧保持原样。" },
  },
  {
    id: "keyframe-narrative",
    title: "关键帧叙事",
    description: "上传 2-4 张按叙事顺序排列的关键帧，画面依次贯穿每个故事节拍，过渡由模型生成，音画一体。",
    tagline: "关键帧锚定故事节拍",
    path: "/tools/keyframe-narrative",
    icon: "keyframe-narrative",
    status: "available",
    category: "video",
    cover: "/tool-covers/keyframe-narrative.jpg",
  },
  {
    id: "depth-capture",
    title: "深度捕捉",
    description: "上传原片视频，自动提取时序深度图锁定运镜与空间结构，用提示词把画面重塑成新的内容与风格，同时回看深度预览。",
    tagline: "锁定运镜结构，重塑画面内容",
    path: "/tools/depth-capture",
    icon: "depth-capture",
    status: "available",
    category: "camera",
    cover: "/tool-covers/depth-capture.jpg",
    demo: { kind: "video", src: "/tool-demos/depth-capture.mp4", caption: "左侧为原片，右侧为锁定运镜与空间结构后、按提示词重塑的画面。" },
  },
  {
    id: "image-bg-remove",
    title: "图片去背景",
    description: "上传一张图片，自动移除背景并保留主体，输出透明背景 PNG，用于贴纸、合成与再创作。",
    tagline: "去掉背景，保留主体",
    path: "/tools/image-bg-remove",
    icon: "image-bg-remove",
    status: "available",
    category: "image",
    cover: "/tool-covers/image-bg-remove.jpg",
    demo: { kind: "image", src: "/tool-demos/image-bg-remove.jpg", caption: "上传原图后自动移除背景、保留主体，右图棋盘格区域即透明部分。" },
  },
  {
    id: "image-layer-split",
    title: "图层分离",
    description: "智能识别、框选或按描述拆分主体与背景，得到前景、背景两个透明图层，可分别编辑或再创作。",
    tagline: "智能 / 框选 / 按描述拆分图层",
    path: "/tools/image-layer-split",
    icon: "image-layer-split",
    status: "available",
    category: "image",
    cover: "/tool-covers/image-layer-split.jpg",
    demo: { kind: "image", src: "/tool-demos/image-layer-split.jpg", caption: "智能拆分出的前景图层（右图棋盘格区域即被挖空的透明部分），可与背景分别编辑。" },
  },
  {
    id: "photo-edit",
    title: "图片编辑",
    description: "上传原图并用一句话描述修改要求，模型保持其余画面不变；可追加参考图控制风格与素材。",
    tagline: "一句话，精准改图",
    path: "/tools/photo-edit",
    icon: "photo-edit",
    status: "available",
    category: "image",
    cover: "/tool-covers/photo-edit.jpg",
    demo: { kind: "image", src: "/tool-demos/photo-edit.jpg", caption: "上传原图并用一句话描述修改，模型按要求改图，其余画面保持不变。" },
  },
  {
    id: "image-inpaint",
    title: "图片局部重绘",
    description: "框选或涂抹画面区域，一句话把选区变成新内容，选区外的像素与原图完全一致。",
    tagline: "框选区域，重新绘制",
    path: "/tools/image-inpaint",
    icon: "image-inpaint",
    status: "available",
    category: "image",
    cover: "/tool-covers/image-inpaint.jpg",
    demo: { kind: "image", src: "/tool-demos/image-inpaint.jpg", caption: "框选或涂抹区域后一句话重绘，选区外的像素与原图完全一致。" },
  },
  {
    id: "image-eraser",
    title: "消除笔",
    description: "涂抹要移除的内容，模型用周围环境自然填补，选区外的像素与原图完全一致。",
    tagline: "精准涂抹，自然消除",
    path: "/tools/image-eraser",
    icon: "image-eraser",
    status: "available",
    category: "image",
    cover: "/tool-covers/image-eraser.jpg",
    demo: { kind: "image", src: "/tool-demos/image-eraser.jpg", caption: "涂抹要移除的内容，模型用周围环境自然填补，其余画面保持不变。" },
  },
  {
    id: "image-outpaint",
    title: "图片扩图",
    description: "选择目标画幅，画面向四周自然延伸补全，原区域像素与原图完全一致。",
    tagline: "自由拓展画面范围",
    path: "/tools/image-outpaint",
    icon: "image-outpaint",
    status: "available",
    category: "image",
    cover: "/tool-covers/image-outpaint.jpg",
    demo: { kind: "image", src: "/tool-demos/image-outpaint.jpg", caption: "选择目标画幅后画面向四周自然延伸补全，原区域像素与原图完全一致。" },
  },
  {
    id: "video-extend",
    title: "视频延长",
    description: "从现有画面自然衔接生成后续镜头。",
    tagline: "自然衔接后续镜头",
    path: "/tools/video-extend",
    icon: "generic",
    status: "planned",
    category: "video",
    cover: "/tool-covers/video-extend.jpg",
  },
  {
    id: "smart-edit",
    title: "智能编辑",
    description: "标记画面元素后用一句话精准修改局部。",
    tagline: "标记画面，精准修改",
    path: "/tools/smart-edit",
    icon: "generic",
    status: "planned",
    category: "featured",
    cover: "/tool-covers/smart-edit.jpg",
  },
  {
    id: "frame-video",
    title: "首尾帧视频",
    description: "上传首尾两帧，生成完整过渡镜头。",
    tagline: "首尾帧生成完整镜头",
    path: "/tools/frame-video",
    icon: "generic",
    status: "planned",
    category: "video",
    cover: "/tool-covers/frame-video.jpg",
  },
  {
    id: "smart-cover",
    title: "智能封面",
    description: "为成片自动生成竖版封面图，一步产出可发布素材。",
    tagline: "为成片自动生成竖版封面图",
    path: "/tools/smart-cover",
    icon: "generic",
    status: "planned",
    category: "image",
    cover: "/tool-covers/smart-cover.jpg",
  },
  {
    id: "image-angles",
    title: "图片多角度",
    description: "同一角色任意变换拍摄角度与景别。",
    tagline: "任意变换拍摄角度",
    path: "/tools/image-angles",
    icon: "generic",
    status: "planned",
    category: "camera",
    cover: "/tool-covers/image-angles.jpg",
  },
]

export function availableTools(): StudioTool[] {
  return STUDIO_TOOLS.filter((tool) => tool.status === "available")
}

/** 生成页首页多功能墙的工具顺序：注册表顺序，前两位高亮。 */
export function wallTools(): StudioTool[] {
  return STUDIO_TOOLS
}

export function toolsByCategory(category: StudioToolCategory): StudioTool[] {
  return STUDIO_TOOLS.filter((tool) => tool.category === category)
}

export function toolFromPath(pathname: string): StudioTool | null {
  return availableTools().find((tool) => tool.path === pathname) ?? null
}
