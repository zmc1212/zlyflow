import { ArrowLeftRight, ScanSearch, WandSparkles } from "lucide-react"
import type { ComponentType } from "react"
import type { StudioTool } from "./tool-registry"

export const TOOL_ICONS: Record<StudioTool["icon"], ComponentType<{ size?: number | string }>> = {
  "prompt-reverse": ScanSearch,
  "motion-transfer": ArrowLeftRight,
  generic: WandSparkles,
}
