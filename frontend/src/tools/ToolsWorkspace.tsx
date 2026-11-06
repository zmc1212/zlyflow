import { Navigate, useLocation } from "react-router-dom"
import { PATHS } from "../paths"
import { MOTION_REF_VIDEO_WORKFLOW } from "../generation/motion-transfer"
import type { PromptReverseMediaType, PromptReverseResult } from "../prompt-reverse"
import ActionShotTool from "./ActionShotTool"
import DigitalHumanTool from "./DigitalHumanTool"
import DepthCaptureTool from "./DepthCaptureTool"
import FaceSwapTool from "./FaceSwapTool"
import ImageBgRemoveEditor from "./ImageBgRemoveEditor"
import ImageBgRemoveTool from "./ImageBgRemoveTool"
import ImageEraserTool from "./ImageEraserTool"
import ImageInpaintTool from "./ImageInpaintTool"
import ImageLayerSplitTool from "./ImageLayerSplitTool"
import ImageOutpaintTool from "./ImageOutpaintTool"
import KeyframeNarrativeTool from "./KeyframeNarrativeTool"
import LipSyncTool from "./LipSyncTool"
import MotionTransferTool from "./MotionTransferTool"
import PartialRetakeTool from "./PartialRetakeTool"
import PhotoEditTool from "./PhotoEditTool"
import PromptReverseTool from "./PromptReverseTool"
import StemSplitTool from "./StemSplitTool"
import VideoUpscaleTool from "./VideoUpscaleTool"
import FaceRestoreTool from "./FaceRestoreTool"
import ToolsHome from "./ToolsHome"
import { ToolDemoGate } from "./ToolDemoModal"
import { toolFromPath } from "./tool-registry"

export default function ToolsWorkspace({
  csrfToken, onSendToComposer,
}: {
  csrfToken: string
  onSendToComposer: (target: PromptReverseMediaType, result: PromptReverseResult) => void
}) {
  const { pathname } = useLocation()
  if (pathname === PATHS.tools) return <ToolsHome />
  const tool = toolFromPath(pathname)
  return <>
    {renderToolPage(pathname, csrfToken, onSendToComposer)}
    <ToolDemoGate tool={tool} />
  </>
}

function renderToolPage(
  pathname: string,
  csrfToken: string,
  onSendToComposer: (target: PromptReverseMediaType, result: PromptReverseResult) => void,
) {
  if (pathname === PATHS.toolMotionTransfer) return <MotionTransferTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolCharacterReplace) return <MotionTransferTool csrfToken={csrfToken} lockedWorkflow={MOTION_REF_VIDEO_WORKFLOW}
    copy={{
      title: "视频换人",
      description: "上传一段原片视频和 1-6 张角色形象图，按顺序把视频里的表演者换成你的角色；动作、运镜、场景与原声一并保留",
    }} />
  if (pathname === PATHS.toolFaceSwap) return <FaceSwapTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolPartialRetake) return <PartialRetakeTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolKeyframeNarrative) return <KeyframeNarrativeTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolActionShot) return <ActionShotTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolDepthCapture) return <DepthCaptureTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolVideoEdit) return <DepthCaptureTool key="h3-video-edit" csrfToken={csrfToken}
    workflowId="minimax-h3-video-edit" copy={{
      title: "H3 视频编辑（试用）",
      description: "上传已有视频，用文字修改场景，先用短片检查人物与动作的保留效果",
      help: "直接参考原片完整画面进行编辑。描述要保留的人物、动作和镜头，以及需要替换的背景；生成时长取原片开头对应片段。",
      placeholder: "例如：保留原片中的双人身份、发型、衣服、舞步和表情，只把古镇背景换成白天江边步行道，保持自拍视角。",
      note: "原片不超过 50 MB；人物细节和动作可能变化，建议先试 5 秒。开启保留原声时，平台直接沿用原 BGM。",
    }} />
  if (pathname === PATHS.toolVideoUpscale) return <VideoUpscaleTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolFaceRestore) return <FaceRestoreTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolStemSplit) return <StemSplitTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolDigitalHuman) return <DigitalHumanTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolLipSync) return <LipSyncTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolImageBgRemove) return <ImageBgRemoveTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolImageBgRemoveEditor) return <ImageBgRemoveEditor csrfToken={csrfToken} />
  if (pathname === PATHS.toolImageLayerSplit) return <ImageLayerSplitTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolPhotoEdit) return <PhotoEditTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolImageInpaint) return <ImageInpaintTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolImageEraser) return <ImageEraserTool csrfToken={csrfToken} />
  if (pathname === PATHS.toolImageOutpaint) return <ImageOutpaintTool csrfToken={csrfToken} />
  if (toolFromPath(pathname)?.id === "prompt-reverse") {
    return <PromptReverseTool csrfToken={csrfToken} onSendToComposer={onSendToComposer} />
  }
  return <Navigate to={PATHS.tools} replace />
}
