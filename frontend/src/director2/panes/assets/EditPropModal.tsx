// 编辑道具弹窗（严格对齐 source2 PropDialog）——逐行复刻自 AssetsLibraryPane.vue 的 editPropModal 弹窗。
// 原版 draftProp 在 openEditPropModal 时重置，这里通过 destroyOnHidden 的每次挂载初始化等价实现。
import { useState } from "react"
import { Col, Form, Input, Modal, Row, Select } from "antd"
import type { Director2Asset } from "../../api"
import { PROP_TYPE_OPTIONS } from "./shared"

export type PropDraft = {
  name: string
  prop_type: string
  owner: string
  visual_prompt: string
  turnaround_prompt: string
  detail_prompt: string
  description: string
}

interface EditPropModalProps {
  open: boolean
  asset: Director2Asset | null
  saving: boolean
  onCancel: () => void
  onConfirm: (draft: PropDraft) => void
}

export default function EditPropModal({ open, asset, saving, onCancel, onConfirm }: EditPropModalProps) {
  const [draftProp, setDraftProp] = useState<PropDraft>(() => ({
    name: asset?.name || "",
    prop_type: asset?.extra?.prop_type || "object",
    owner: asset?.extra?.owner || asset?.role || "",
    visual_prompt: asset?.extra?.visual_prompt || asset?.visual_prompt || "",
    turnaround_prompt: asset?.extra?.turnaround_prompt || "",
    detail_prompt: asset?.extra?.detail_prompt || "",
    description: asset?.description || "",
  }))

  return (
    <Modal
      open={open}
      title={`编辑道具「${draftProp.name || ""}」`}
      confirmLoading={saving}
      okText="确认保存"
      cancelText="取消"
      width={640}
      destroyOnHidden
      onOk={() => onConfirm(draftProp)}
      onCancel={onCancel}
      className="d2-assets-library"
    >
      <Form layout="vertical">
        <Row gutter={14}>
          <Col span={10}>
            <Form.Item label="道具名称" required>
              <Input value={draftProp.name} onChange={(event) => setDraftProp({ ...draftProp, name: event.target.value })} placeholder="例如：旧木书箱" />
            </Form.Item>
          </Col>
          <Col span={7}>
            <Form.Item label="道具类型 (Prop Type)">
              <Select value={draftProp.prop_type} options={PROP_TYPE_OPTIONS} onChange={(value) => setDraftProp({ ...draftProp, prop_type: value })} />
            </Form.Item>
          </Col>
          <Col span={7}>
            <Form.Item label="所属角色 (Owner)">
              <Input value={draftProp.owner} onChange={(event) => setDraftProp({ ...draftProp, owner: event.target.value })} placeholder="例如：沈砚 专属信物" />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item label="概念参考图提示词 (Visual Prompt)">
          <Input.TextArea
            value={draftProp.visual_prompt}
            onChange={(event) => setDraftProp({ ...draftProp, visual_prompt: event.target.value })}
            placeholder="描述道具整体形态、材质、做旧与电影级工作室布光..."
            rows={2}
          />
        </Form.Item>

        <Row gutter={12}>
          <Col span={12}>
            <Form.Item label="转面三视图提示词 (Turnaround)">
              <Input.TextArea
                value={draftProp.turnaround_prompt}
                onChange={(event) => setDraftProp({ ...draftProp, turnaround_prompt: event.target.value })}
                placeholder="描述道具正视图、侧视图、背视图多方位设计..."
                rows={2}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="细节特写提示词 (Detail Close-up)">
              <Input.TextArea
                value={draftProp.detail_prompt}
                onChange={(event) => setDraftProp({ ...draftProp, detail_prompt: event.target.value })}
                placeholder="描述微距材质、刻字铭文、开刃磨损与质感..."
                rows={2}
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item label="背景故事与叙述性描述 (Description)">
          <Input.TextArea
            value={draftProp.description}
            onChange={(event) => setDraftProp({ ...draftProp, description: event.target.value })}
            placeholder="记录该道具在剧本故事中的起源、象征意义或重要剧情推动作用..."
            rows={3}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
