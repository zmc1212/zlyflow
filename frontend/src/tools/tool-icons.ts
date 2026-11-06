import { ArrowLeftRight, AudioLines, AudioWaveform, Brush, Expand, ImageOff, Images, Layers, Layers2, MicVocal, MonitorUp, Replace, ScanFace, ScanSearch, SquareDashed, Swords, Users, WandSparkles } from "lucide-react"
import type { ComponentType } from "react"
import type { StudioTool } from "./tool-registry"

export const TOOL_ICONS: Record<StudioTool["icon"], ComponentType<{ size?: number | string }>> = {
  "prompt-reverse": ScanSearch,
  "motion-transfer": ArrowLeftRight,
  "character-replace": Users,
  "action-shot": Swords,
  "digital-human": MicVocal,
  "lip-sync": AudioLines,
  "partial-retake": Brush,
  "keyframe-narrative": Images,
  "depth-capture": Layers,
  "video-upscale": MonitorUp,
  "face-restore": ScanFace,
  "face-swap": Replace,
  "stem-split": AudioWaveform,
  "image-bg-remove": ImageOff,
  "image-layer-split": Layers2,
  "photo-edit": WandSparkles,
  "image-inpaint": SquareDashed,
  "image-eraser": Brush,
  "image-outpaint": Expand,
  generic: WandSparkles,
}
