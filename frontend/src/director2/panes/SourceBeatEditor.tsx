import { useState } from "react"
import { Button, Form, Input, Modal, message } from "antd"
import { director2ErrorDetail, updateEpisodeBeat, type Director2Beat } from "../api"

export default function SourceBeatEditor({ csrfToken, projectId, episodeId, beat, onSaved }: {
  csrfToken: string; projectId: string; episodeId: string; beat: Director2Beat; onSaved: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  async function save() {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSaving(true)
    try {
      const dialogueChanged = values.dialogue !== beat.dialogue || values.speaker !== beat.speaker
      await updateEpisodeBeat(csrfToken, projectId, episodeId, beat.id, {
        ...values, ...(dialogueChanged ? { dialogue_turns: [] } : {}),
      })
      await onSaved(); setOpen(false); message.success("来源分镜已保存，相关制作方案需重新确认")
    } catch (err) { message.error(director2ErrorDetail(err, "保存分镜失败")) }
    finally { setSaving(false) }
  }
  return <><Button size="small" onClick={() => { form.setFieldsValue(beat); setOpen(true) }}>编辑来源分镜</Button>
    <Modal title="编辑来源分镜" open={open} onCancel={() => setOpen(false)} onOk={() => void save()} confirmLoading={saving} okText="保存来源" cancelText="取消">
      <Form form={form} layout="vertical">
        <Form.Item name="heading" label="分镜标题" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="action" label="动作与画面"><Input.TextArea autoSize={{ minRows: 3, maxRows: 10 }} /></Form.Item>
        <Form.Item name="speaker" label="说话人"><Input /></Form.Item>
        <Form.Item name="dialogue" label="对白"><Input.TextArea autoSize={{ minRows: 2, maxRows: 8 }} /></Form.Item>
        <Form.Item name="camera" label="运镜"><Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} /></Form.Item>
      </Form>
    </Modal></>
}
