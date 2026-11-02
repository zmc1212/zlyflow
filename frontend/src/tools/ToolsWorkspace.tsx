import { Navigate, useLocation } from "react-router-dom"
import { PATHS } from "../paths"
import type { PromptReverseMediaType, PromptReverseResult } from "../prompt-reverse"
import MotionTransferTool from "./MotionTransferTool"
import PromptReverseTool from "./PromptReverseTool"
import ToolsHome from "./ToolsHome"
import { toolFromPath } from "./tool-registry"

export default function ToolsWorkspace({
  csrfToken, onSendToComposer,
}: {
  csrfToken: string
  onSendToComposer: (target: PromptReverseMediaType, result: PromptReverseResult) => void
}) {
  const { pathname } = useLocation()
  if (pathname === PATHS.tools) return <ToolsHome />
  if (pathname === PATHS.toolMotionTransfer) return <MotionTransferTool csrfToken={csrfToken} />
  if (toolFromPath(pathname)?.id === "prompt-reverse") {
    return <PromptReverseTool csrfToken={csrfToken} onSendToComposer={onSendToComposer} />
  }
  return <Navigate to={PATHS.tools} replace />
}
