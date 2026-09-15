// 新建资产弹窗（含内嵌「AI 生成角色内容」弹窗）——
// 逐行复刻自 AssetsLibraryPane.vue 的「新建资产弹窗」与「characterAiModalVisible」弹窗。
// 原版 createForm / characterAiRequirement 状态在此弹窗打开时重置，这里通过 destroyOnHidden 的每次挂载初始化等价实现。
import { useState } from "react"
import { Button, Form, Input, message, Modal, Radio } from "antd"
import { Sparkles } from "lucide-react"
import { createAsset, generateCharacterContent, director2ErrorDetail } from "../../api"
import { kindLabel } from "./shared"

export type CreateFormState = {
  kind: string
  name: string
  role: string
  description: string
  visual_prompt: string
  image_url: string
}

interface CreateAssetModalProps {
  open: boolean
  kindInitial: string
  submitting: boolean
  csrfToken: string
  projectId: string
  onClose: () => void
  onSubmit: (form: CreateFormState) => void
}

export default function CreateAssetModal({
  open,
  kindInitial,
  submitting,
  csrfToken,
  projectId,
  onClose,
  onSubmit,
}: CreateAssetModalProps) {
  const [createForm, setCreateForm] = useState<CreateFormState>(() => ({
    kind: kindInitial,
    name: "",
    role: "",
    description: "",
    visual_prompt: "",
    image_url: "",
  }))
  const [characterAiModalVisible, setCharacterAiModalVisible] = useState(false)
  const [characterAiRequirement, setCharacterAiRequirement] = useState("")
  const [generatingCharacterContent, setGeneratingCharacterContent] = useState(false)

  function openCharacterAiModal() {
    setCharacterAiRequirement("")
    setCharacterAiModalVisible(true)
  }

  async function handleGenerateCharacterContent() {
    const requirement = characterAiRequirement.trim()
    if (!requirement) {
      message.warning("请输入角色简洁需求")
      return
    }
    setGeneratingCharacterContent(true)
    try {
      const generated = await generateCharacterContent(csrfToken, projectId, {
        requirement,
        name: createForm.name,
        role: createForm.role,
      })
      setCreateForm((prev) => ({
        ...prev,
        description: generated.description || "",
        visual_prompt: generated.visual_prompt || "",
      }))
      setCharacterAiModalVisible(false)
      message.success("角色内容已生成并回填")
    } catch (err) {
      message.error(director2ErrorDetail(err, "AI 生成角色内容失败"))
    } finally {
      setGeneratingCharacterContent(false)
    }
  }

  return (
    <Modal
      open={open}
      title={`新增项目${kindLabel(createForm.kind)}`}
      width={540}
      destroyOnHidden
      onCancel={onClose}
      className="d2-assets-library"
      footer={(
        <div className="create-asset-modal-footer">
          {createForm.kind === "character" ? (
            <Button disabled={submitting} onClick={openCharacterAiModal}>
              <Sparkles size={15} />
              AI 生成内容
            </Button>
          ) : null}
          <Button disabled={submitting} onClick={onClose}>取消</Button>
          <Button type="primary" loading={submitting} onClick={() => onSubmit(createForm)}>确认保存</Button>
        </div>
      )}
    >
      <Form layout="vertical">
        <Form.Item label="资产类型" required>
          <Radio.Group value={createForm.kind} onChange={(event) => setCreateForm({ ...createForm, kind: event.target.value })}>
            <Radio.Button value="character">角色</Radio.Button>
            <Radio.Button value="scene">场景</Radio.Button>
            <Radio.Button value="prop">道具</Radio.Button>
          </Radio.Group>
        </Form.Item>

        <Form.Item label="资产名称" required>
          <Input
            value={createForm.name}
            onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })}
            placeholder={`例如：${createForm.kind === "character" ? "沈砚" : createForm.kind === "scene" ? "陆府后花园" : "旧木书箱"}`}
          />
        </Form.Item>

        <Form.Item label={createForm.kind === "character" ? "角色定位" : createForm.kind === "scene" ? "地点/势力" : "归属角色 (Owner)"}>
          <Input
            value={createForm.role}
            onChange={(event) => setCreateForm({ ...createForm, role: event.target.value })}
            placeholder={createForm.kind === "character" ? "例如：男主角" : createForm.kind === "scene" ? "例如：陆府、书塾" : "例如：沈砚专属信物"}
          />
        </Form.Item>

        <Form.Item label={createForm.kind === "character" ? "容貌与服装描述" : createForm.kind === "scene" ? "场景环境与格局描述" : "材质纹理与做旧描述"}>
          <Input.TextArea
            value={createForm.description}
            onChange={(event) => setCreateForm({ ...createForm, description: event.target.value })}
            placeholder={createForm.kind === "character" ? "详细描述外貌身材、服饰细节..." : createForm.kind === "scene" ? "详细描述空间、门窗、陈设光影..." : "详细描述木质、玉石、成色磨损..."}
            rows={3}
          />
        </Form.Item>

        <Form.Item label="AI 生图提示词 (Visual Prompt)">
          <Input.TextArea
            value={createForm.visual_prompt}
            onChange={(event) => setCreateForm({ ...createForm, visual_prompt: event.target.value })}
            placeholder={`输入该${kindLabel(createForm.kind)}的 AI 生图提示词...`}
            rows={3}
          />
        </Form.Item>
      </Form>

      {/* AI 生成角色内容弹窗（原版与新建弹窗为兄弟节点，视觉层级等价：后打开者置顶） */}
      <Modal
        open={characterAiModalVisible}
        title="AI 生成角色内容"
        okText="生成并回填"
        cancelText="取消"
        confirmLoading={generatingCharacterContent}
        width={500}
        destroyOnHidden
        onOk={handleGenerateCharacterContent}
        onCancel={() => setCharacterAiModalVisible(false)}
        className="d2-assets-library"
      >
        <Form layout="vertical">
          <Form.Item label="简洁需求" required>
            <Input.TextArea
              value={characterAiRequirement}
              onChange={(event) => setCharacterAiRequirement(event.target.value)}
              placeholder="例如：26岁现代男硕士，短发，沉稳清瘦，穿白衬衫和深色长裤"
              rows={5}
              maxLength={1000}
              showCount
            />
          </Form.Item>
        </Form>
      </Modal>
    </Modal>
  )
}
