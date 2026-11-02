export type StudioToolStatus = "available" | "coming_soon" | "planned"
export type StudioToolCategory = "featured" | "video" | "image" | "efficiency"

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
  icon: "prompt-reverse" | "motion-transfer" | "generic"
  status: StudioToolStatus
  /** 工具中心分组，同时决定分类 chips 过滤。 */
  category: StudioToolCategory
  /** 照片封面，public 下的绝对路径；首页多功能墙与工具中心共用。 */
  cover: string
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
  efficiency: "效率",
}

export const TOOL_CATEGORY_ORDER: StudioToolCategory[] = ["featured", "video", "image", "efficiency"]

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
    description: "把参考视频里的人物动作迁移到目标角色，让角色做出同样的表演。",
    tagline: "把参考动作迁移到目标角色",
    path: "/tools/motion-transfer",
    icon: "motion-transfer",
    status: "available",
    category: "featured",
    cover: "/tool-covers/motion-transfer.jpg",
    highlight: true,
  },
  {
    id: "video-upscale",
    title: "视频超分",
    description: "低清视频一键放大增强画质，最高支持 8K 输出。",
    tagline: "低清视频一键增强画质",
    path: "/tools/video-upscale",
    icon: "generic",
    status: "coming_soon",
    category: "video",
    cover: "/tool-covers/video-upscale.jpg",
  },
  {
    id: "lip-sync",
    title: "口型同步",
    description: "让角色口型精准匹配配音，支持中英文台词驱动。",
    tagline: "让口型精准匹配配音",
    path: "/tools/lip-sync",
    icon: "generic",
    status: "planned",
    category: "video",
    cover: "/tool-covers/lip-sync.jpg",
  },
  {
    id: "partial-retake",
    title: "视频局部重拍",
    description: "框选画面片段重新生成，其余部分保持原样。",
    tagline: "重新生成指定片段",
    path: "/tools/partial-retake",
    icon: "generic",
    status: "coming_soon",
    category: "video",
    cover: "/tool-covers/partial-retake.jpg",
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
    category: "video",
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
    category: "image",
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
