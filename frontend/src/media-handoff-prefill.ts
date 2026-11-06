import { message } from "antd"
import { useEffect, useRef, useState } from "react"
import { apiErrorMessage } from "./api"
import { fetchHandoffFile, readMediaHandoff } from "./media-handoff"

/**
 * 工具页接收「把这张结果当本次输入」的交接素材。
 * 读回 File 后交给页面既有的上传入口，因此类型校验、预览与进画布等行为和手动上传完全一致。
 * onFile 返回 Promise 时（例如去背景页收到素材直接建任务）会等它结束才收起「正在恢复」。
 */
export function useMediaHandoffPrefill(
  params: URLSearchParams,
  onFile: (file: File) => void | Promise<void>,
): boolean {
  const handoff = readMediaHandoff(params)
  const handoffKey = handoff
    ? `${handoff.jobId}:${handoff.generationItemId}:${handoff.outputIndex}:${handoff.kind}`
    : ""
  const accept = useRef(onFile)
  useEffect(() => { accept.current = onFile }, [onFile])

  const [restoring, setRestoring] = useState(false)
  useEffect(() => {
    if (!handoff) return
    let active = true
    setRestoring(true)
    void fetchHandoffFile(handoff)
      .then(async (file) => { if (active) await accept.current(file) })
      .catch((error) => { if (active) message.error(apiErrorMessage(error, "读取素材失败，请重新上传")) })
      .finally(() => { if (active) setRestoring(false) })
    return () => { active = false }
  }, [handoffKey])

  return restoring
}
