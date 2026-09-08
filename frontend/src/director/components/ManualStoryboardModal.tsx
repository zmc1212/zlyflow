import { Input, Modal, Radio, Typography } from "antd"
import { useState } from "react"
import { parseManualStoryboard } from "../manual-import"
import type { RecipeScene } from "../types"

export default function ManualStoryboardModal({ open, onCancel, onImport }: { open: boolean; onCancel: () => void; onImport: (scenes: RecipeScene[], mode: "replace" | "append") => void }) {
  const [text, setText] = useState("")
  const [mode, setMode] = useState<"replace" | "append">("replace")
  const parsed = parseManualStoryboard(text)
  return <Modal open={open} title="手动导入分镜" okText="导入分镜" cancelText="取消" onCancel={onCancel} onOk={() => onImport(parsed.scenes, mode)} okButtonProps={{ disabled: !parsed.scenes.length }} width={760}>
    <Typography.Paragraph type="secondary">按 Markdown 粘贴场景和镜头，导入后可继续在镜头检查器中编辑。</Typography.Paragraph>
    <Input.TextArea rows={14} value={text} onChange={(e) => setText(e.target.value)} placeholder={'# 场景 1｜夜晚卧室\n\n## 镜头 1｜00:00–00:06\n- 景别：近景\n- 画面：女主坐在床上。\n- 对白：男主：你今天话好多。\n- 场景：卧室'} />
    <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)} style={{ marginTop: 12 }}><Radio value="replace">替换当前镜头</Radio><Radio value="append">追加到现有镜头</Radio></Radio.Group>
    {text.trim() ? <Typography.Paragraph type={parsed.scenes.length ? "secondary" : "danger"} style={{ marginTop: 12 }}>识别到 {parsed.scenes.reduce((n, s) => n + s.shots.length, 0)} 个镜头{parsed.warnings.length ? `；${parsed.warnings.join("；")}` : ""}</Typography.Paragraph> : null}
  </Modal>
}
