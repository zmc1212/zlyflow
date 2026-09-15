// 新增身份/造型弹窗（参考 source2 CreateIdentityModal）——逐行复刻自 AssetsLibraryPane.vue 的 identityModal 弹窗。
// 原版 identityForm 在 openAddIdentityModal 时按当前角色重置，这里通过 destroyOnHidden 的每次挂载初始化等价实现。
import { useState } from "react"
import { Form, Input, Modal } from "antd"
import type { Director2Asset } from "../../api"

export type IdentityFormState = {
  name: string
  description: string
  visual_prompt: string
}

interface IdentityModalProps {
  open: boolean
  asset: Director2Asset | null
  saving: boolean
  onCancel: () => void
  onConfirm: (form: IdentityFormState) => void
}

export default function IdentityModal({ open, asset, saving, onCancel, onConfirm }: IdentityModalProps) {
  const [identityForm, setIdentityForm] = useState<IdentityFormState>(() => {
    const currentCount = asset?.extra?.identities?.length || 0
    return {
      name: `造型 ${currentCount + 1}`,
      description: "",
      visual_prompt: `${asset?.name || ""} 全身立绘，宋代概念美术设计，电影级质感，8k`,
    }
  })

  return (
    <Modal
      open={open}
      title="为角色新增身份 / 造型 (Identity & Costume)"
      confirmLoading={saving}
      okText="确认添加造型"
      cancelText="取消"
      width={540}
      destroyOnHidden
      onOk={() => onConfirm(identityForm)}
      onCancel={onCancel}
      className="d2-assets-library"
    >
      <Form layout="vertical">
        <Form.Item label="身份/造型名称" required>
          <Input
            value={identityForm.name}
            onChange={(event) => setIdentityForm({ ...identityForm, name: event.target.value })}
            placeholder="例如：伴读常服 / 武行夜行衣 / 金榜题名锦袍"
          />
        </Form.Item>

        <Form.Item label="服装与外观设定 (Appearance)">
          <Input.TextArea
            value={identityForm.description}
            onChange={(event) => setIdentityForm({ ...identityForm, description: event.target.value })}
            placeholder="详细描述该时期的衣着、配饰、颜色、发型与神态特征..."
            rows={3}
          />
        </Form.Item>

        <Form.Item label="AI 造型生图提示词 (Visual Prompt)">
          <Input.TextArea
            value={identityForm.visual_prompt}
            onChange={(event) => setIdentityForm({ ...identityForm, visual_prompt: event.target.value })}
            placeholder="AI 生图提示词，例如：沈砚全身立绘，穿浅青色伴读装，腰佩香囊，宋代书生质感，8k..."
            rows={3}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
