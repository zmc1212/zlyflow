import { Modal, Button } from "antd"
import { useEffect, useState } from "react"
import type { StudioTool } from "./tool-registry"

/** 每个工具「首次打开自动弹示例」只发生一次，标记持久化在浏览器本地。 */
const seenKey = (toolId: string) => `studio.tool-demo.seen.${toolId}`

export function hasToolDemoSeen(toolId: string): boolean {
  try {
    return localStorage.getItem(seenKey(toolId)) === "1"
  } catch {
    return false
  }
}

export function markToolDemoSeen(toolId: string): void {
  try {
    localStorage.setItem(seenKey(toolId), "1")
  } catch {
    // 隐私模式下 localStorage 不可写：忽略，示例框仍可正常关闭。
  }
}

export default function ToolDemoModal({
  tool, open, onClose,
}: {
  tool: StudioTool | null
  open: boolean
  onClose: () => void
}) {
  const demo = open ? tool?.demo : undefined
  return (
    <Modal
      open={open && !!demo}
      title={tool ? `${tool.title} · 功能示例` : undefined}
      width={demo?.kind === "video" ? 780 : 1000}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
    >
      {demo ? (
        <div className="studio-tool-demo">
          {demo.kind === "video" ? (
            <video
              className="studio-tool-demo-media"
              src={demo.src}
              autoPlay
              muted
              loop
              playsInline
              controls
            />
          ) : (
            <img className="studio-tool-demo-media" src={demo.src} alt={`${tool?.title}功能示例对比`} />
          )}
          <p className="studio-tool-demo-caption">{demo.caption}</p>
          <div className="studio-tool-demo-actions">
            <Button type="primary" onClick={onClose}>知道了，开始创作</Button>
          </div>
        </div>
      ) : null}
    </Modal>
  )
}

/** 挂在工具页外层：进入有示例的工具页时，若本机从未看过示例则自动弹出。 */
export function ToolDemoGate({ tool }: { tool: StudioTool | null }) {
  const [open, setOpen] = useState(false)
  const toolId = tool?.id ?? null
  useEffect(() => {
    if (!toolId || !tool?.demo || hasToolDemoSeen(toolId)) return
    setOpen(true)
  }, [toolId, tool?.demo])
  if (!tool?.demo) return null
  return (
    <ToolDemoModal
      tool={tool}
      open={open}
      onClose={() => { markToolDemoSeen(tool.id); setOpen(false) }}
    />
  )
}
