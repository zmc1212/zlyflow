// 编辑场景弹窗（严格对齐 source2 SceneDialog）——逐行复刻自 AssetsLibraryPane.vue 的 editSceneModal 弹窗，
// 并包含 360 空间环境合同 (七大维度) 的解析与序列化函数（对齐 source2 scene-environment-prompt.tsx）。
// 原版 draftScene / envSections 在 openEditSceneModal 时重置，这里通过 destroyOnHidden 的每次挂载初始化等价实现。
import { useState } from "react"
import { Col, Form, Input, Modal, Row, Select } from "antd"
import { Compass } from "lucide-react"
import type { Director2Asset } from "../../api"
import { SCENE_TYPE_OPTIONS } from "./shared"

export type SceneDraft = {
  name: string
  scene_type: string
  role: string
  description: string
}

export type EnvSections = {
  front: string
  back: string
  left: string
  right: string
  light: string
  material: string
  forbidden: string
}

interface EditSceneModalProps {
  open: boolean
  asset: Director2Asset | null
  saving: boolean
  onCancel: () => void
  onConfirm: (draft: SceneDraft, envPrompt: string) => void
}

// 360 空间环境合同 (七大维度) 解析与序列化 (严格对齐 source2 scene-environment-prompt.tsx)
function parseEnvironmentPrompt(prompt?: string | null): EnvSections {
  const res: EnvSections = { front: "", back: "", left: "", right: "", light: "", material: "", forbidden: "" }
  if (!prompt) return res
  const text = prompt.replace(/\r\n/g, "\n").trim()
  const map: Record<string, keyof EnvSections> = {
    "正面": "front", "正面描述": "front",
    "背面": "back", "背面描述": "back",
    "左侧": "left", "左侧描述": "left",
    "右侧": "right", "右侧描述": "right",
    "光源": "light", "光源描述": "light",
    "材质/风格": "material", "材质": "material", "风格": "material",
    "禁止元素": "forbidden", "禁止": "forbidden",
  }
  const regex = /(?:^|\n)\s*(正面|背面|左侧|右侧|光源|材质\/风格|材质|禁止元素|禁止)\s*[:：]([\s\S]*?)(?=(?:\n\s*(?:正面|背面|左侧|右侧|光源|材质\/风格|材质|禁止元素|禁止)\s*[:：]|$))/g
  let match: RegExpExecArray | null
  let count = 0
  while ((match = regex.exec(text)) !== null) {
    count++
    const k = map[match[1]]
    if (k) res[k] = match[2].trim()
  }
  if (count === 0) {
    res.front = text
  }
  return res
}

function serializeEnvironmentPrompt(sections: EnvSections): string {
  const lines: string[] = []
  if (sections.front?.trim()) lines.push(`正面：${sections.front.trim()}`)
  if (sections.back?.trim()) lines.push(`背面：${sections.back.trim()}`)
  if (sections.left?.trim()) lines.push(`左侧：${sections.left.trim()}`)
  if (sections.right?.trim()) lines.push(`右侧：${sections.right.trim()}`)
  if (sections.light?.trim()) lines.push(`光源：${sections.light.trim()}`)
  if (sections.material?.trim()) lines.push(`材质/风格：${sections.material.trim()}`)
  if (sections.forbidden?.trim()) lines.push(`禁止元素：${sections.forbidden.trim()}`)
  return lines.join("\n")
}

export default function EditSceneModal({ open, asset, saving, onCancel, onConfirm }: EditSceneModalProps) {
  const [draftScene, setDraftScene] = useState<SceneDraft>(() => ({
    name: asset?.name || "",
    scene_type: asset?.extra?.scene_type || "interior",
    role: asset?.role || "",
    description: asset?.description || "",
  }))
  const [envSections, setEnvSections] = useState<EnvSections>(() =>
    parseEnvironmentPrompt(asset?.extra?.environment_prompt || ""),
  )

  return (
    <Modal
      open={open}
      title={`编辑场景「${draftScene.name || ""}」`}
      confirmLoading={saving}
      okText="确认保存"
      cancelText="取消"
      width={780}
      destroyOnHidden
      onOk={() => onConfirm(draftScene, serializeEnvironmentPrompt(envSections))}
      onCancel={onCancel}
      className="d2-assets-library"
    >
      <Form layout="vertical">
        <Row gutter={14}>
          <Col span={12}>
            <Form.Item label="场景名称" required>
              <Input value={draftScene.name} onChange={(event) => setDraftScene({ ...draftScene, name: event.target.value })} placeholder="例如：沈家正堂" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item label="场景类型 (Scene Type)">
              <Select value={draftScene.scene_type} options={SCENE_TYPE_OPTIONS} onChange={(value) => setDraftScene({ ...draftScene, scene_type: value })} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item label="归属势力 / 地点定位">
              <Input value={draftScene.role} onChange={(event) => setDraftScene({ ...draftScene, role: event.target.value })} placeholder="例如：沈家老宅、陆府" />
            </Form.Item>
          </Col>
        </Row>

        {/* 360 空间合同七大维度结构化编辑 (对齐 source2 SceneEnvironmentPromptFields) */}
        <div className="modal-section-title">
          <Compass size={14} className="text-cyan" />
          <span>360° 空间环境合同 (七大维度提示词)</span>
        </div>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item label="正面描述 (Front)">
              <Input.TextArea value={envSections.front} rows={2} placeholder="正面主视线景观、空间主体与轴线..." onChange={(event) => setEnvSections({ ...envSections, front: event.target.value })} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="背面描述 (Back / Reverse)">
              <Input.TextArea value={envSections.back} rows={2} placeholder="180度反打视角门窗、屏风与对向景深..." onChange={(event) => setEnvSections({ ...envSections, back: event.target.value })} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="左侧描述 (Left)">
              <Input.TextArea value={envSections.left} rows={2} placeholder="左侧陈设、通道门廊、墙体挂画..." onChange={(event) => setEnvSections({ ...envSections, left: event.target.value })} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="右侧描述 (Right)">
              <Input.TextArea value={envSections.right} rows={2} placeholder="右侧采光窗格、案几器皿、绿植..." onChange={(event) => setEnvSections({ ...envSections, right: event.target.value })} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="光源描述 (Light)">
              <Input value={envSections.light} onChange={(event) => setEnvSections({ ...envSections, light: event.target.value })} placeholder="如：午后斜阳、烛台暖光、柔和自然散光" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="材质/风格 (Material/Style)">
              <Input value={envSections.material} onChange={(event) => setEnvSections({ ...envSections, material: event.target.value })} placeholder="如：宋代古典木构、青砖黛瓦、古拙朴素" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="禁止元素 (Forbidden)">
              <Input value={envSections.forbidden} onChange={(event) => setEnvSections({ ...envSections, forbidden: event.target.value })} placeholder="如：现代电器、塑胶水管、英文标识" />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item label="场景陈设与叙述性描述 (Description)">
          <Input.TextArea
            value={draftScene.description}
            onChange={(event) => setDraftScene({ ...draftScene, description: event.target.value })}
            placeholder="描述该场景在剧本中的陈设细节、环境氛围与剧情故事..."
            rows={3}
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
