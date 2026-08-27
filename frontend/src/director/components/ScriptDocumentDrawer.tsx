import { Button, Drawer, Input, Space, Tag } from "antd"
import { FileText, Wand2 } from "lucide-react"

interface ScriptDocumentDrawerProps {
  open: boolean
  projectTitle: string
  sourceScript: string
  styleVibe?: string
  requestedShotCount?: number
  saving?: boolean
  onChangeScript: (value: string) => void
  onSave: () => void
  onSplit: () => void
  onClose: () => void
}

export default function ScriptDocumentDrawer({
  open,
  projectTitle,
  sourceScript,
  styleVibe,
  requestedShotCount,
  saving = false,
  onChangeScript,
  onSave,
  onSplit,
  onClose,
}: ScriptDocumentDrawerProps) {
  const hasScript = Boolean(sourceScript.trim())

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={460}
      className="director-script-drawer"
      title={
        <div className="director-script-drawer-title">
          <FileText size={18} />
          <span>剧本文档</span>
          <Tag color={hasScript ? "blue" : "default"}>{hasScript ? "有原文" : "无原文"}</Tag>
        </div>
      }
      extra={
        <Space>
          <Button icon={<Wand2 size={14} />} onClick={onSplit}>AI 再拆</Button>
          <Button type="primary" loading={saving} onClick={onSave}>保存原文</Button>
        </Space>
      }
    >
      <div className="director-script-body">
        <p className="director-script-hint">
          这是工程 <strong>{projectTitle}</strong> 的剧本文档，关闭拆分弹窗后仍可回看和手改。空文案也可以直接写在这里保存。
        </p>
        <div className="director-script-meta">
          {styleVibe ? <span>风格：{styleVibe}</span> : <span>尚未记录风格</span>}
          {typeof requestedShotCount === "number" ? <span>期望 {requestedShotCount} 镜</span> : null}
        </div>
        <Input.TextArea
          value={sourceScript}
          onChange={(event) => onChangeScript(event.target.value)}
          rows={16}
          placeholder="在此粘贴或编写剧本文案。保存后会随工程一起落盘，刷新后仍在。"
        />
      </div>
    </Drawer>
  )
}
