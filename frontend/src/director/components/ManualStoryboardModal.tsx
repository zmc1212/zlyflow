import { Input, Modal, Radio, Typography, Upload, Button, message, Checkbox } from "antd"
import { FileUp } from "lucide-react"
import { useState, useEffect } from "react"
import { parseManualStoryboard, ManualImportResult } from "../manual-import"

export default function ManualStoryboardModal({ open, title = "手动导入分镜", hint = "按 Markdown 粘贴场景和镜头，导入后可继续在镜头检查器中编辑。", onCancel, onImport }: { open: boolean; title?: string; hint?: string; onCancel: () => void; onImport: (parsed: ManualImportResult, mode: "replace" | "append", autoGenerate: boolean) => void }) {
  const [text, setText] = useState("")
  const [mode, setMode] = useState<"replace" | "append">("replace")
  const [autoGenerate, setAutoGenerate] = useState(true)
  const parsed = parseManualStoryboard(text)

  // Clear text when modal is reopened
  useEffect(() => {
    if (open) {
      setText("")
    }
  }, [open])

  const handleFileUpload = (file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const content = e.target?.result
      if (typeof content === "string") {
        setText(content)
      }
    }
    reader.onerror = () => {
      message.error("读取文件失败")
    }
    reader.readAsText(file)
    return false // Prevent default upload behavior
  }

  return <Modal open={open} title={title} okText="导入" cancelText="取消" onCancel={onCancel} onOk={() => onImport(parsed, mode, autoGenerate)} okButtonProps={{ disabled: !parsed.scenes.length && !parsed.fullStory }} width={760}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
      <Typography.Paragraph type="secondary" style={{ margin: 0, flex: 1, paddingRight: 16 }}>{hint}</Typography.Paragraph>
      <Upload accept=".md,.txt" beforeUpload={handleFileUpload} showUploadList={false}>
        <Button icon={<FileUp size={14} />}>选择本地文件...</Button>
      </Upload>
    </div>
    <Input.TextArea rows={14} value={text} onChange={(e) => setText(e.target.value)} placeholder={'# 《剧本标题》\n\n## 角色设定\n...\n\n# 场景 1｜夜晚卧室\n\n## 镜头 1｜00:00–00:06\n- 景别：近景\n- 画面：女主坐在床上。\n- 对白：男主：你今天话好多。\n- 场景：卧室'} />
    <div style={{ marginTop: 12, display: "flex", gap: 24, alignItems: "center" }}>
      <Radio.Group value={mode} onChange={(e) => setMode(e.target.value)}>
        <Radio value="replace">替换当前内容</Radio>
        <Radio value="append">追加到现有内容</Radio>
      </Radio.Group>
      <Checkbox checked={autoGenerate} onChange={(e) => setAutoGenerate(e.target.checked)}>
        导入后自动启动 AI 提取角色与场景设定
      </Checkbox>
    </div>
    {text.trim() ? (
      <div style={{ marginTop: 12 }}>
        <Typography.Paragraph type={parsed.scenes.length || parsed.fullStory ? "secondary" : "danger"} style={{ marginBottom: 4 }}>
          识别到 {parsed.scenes.reduce((n, s) => n + s.shots.length, 0)} 个镜头，
          {parsed.fullStory ? `已识别全局剧本设定（${parsed.fullStory.length}字）` : '无全局剧本设定'}
        </Typography.Paragraph>
        {parsed.warnings.length > 0 && (
          <div style={{ maxHeight: 120, overflowY: "auto", padding: "8px 12px", background: "var(--studio-surface-raised, rgba(255, 77, 79, 0.05))", border: "1px solid var(--studio-border, rgba(255, 77, 79, 0.2))", borderRadius: 6 }}>
            <ul style={{ margin: 0, paddingLeft: 16, color: "var(--studio-text-danger, #cf1322)", fontSize: 13 }}>
              {parsed.warnings.map((w, i) => <li key={i} style={{ marginBottom: 4 }}>{w}</li>)}
            </ul>
          </div>
        )}
      </div>
    ) : null}
  </Modal>
}
