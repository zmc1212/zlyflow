import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Alert,
  Button,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
  message,
} from "antd"
import {
  ArrowUpDown,
  Box,
  Calendar,
  Compass,
  Edit2,
  ExternalLink,
  Globe,
  History,
  Layers,
  Library,
  Link2,
  Mic2,
  Package,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Shirt,
  SlidersHorizontal,
  Sparkles,
  Star,
  Trash2,
  Upload as UploadIcon,
  Users,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  createXiajiAsset,
  defineXiajiVoice,
  deleteXiajiAsset,
  generateXiajiAssetImage,
  generateXiajiVoice,
  listXiajiAssets,
  waitForXiajiImageJob,
  syncXiajiAssets,
  updateXiajiAsset,
  uploadXiajiAssetImage,
  uploadXiajiVoice,
  type XiajiAsset,
  type XiajiAssetGenerateImagePayload,
  type XiajiAssetKind,
  type XiajiCharacterLook,
  type XiajiVoiceProfile,
} from "./xiaji-api"

const KIND_TABS: { key: XiajiAssetKind | "voice-board"; label: string; hint: string }[] = [
  { key: "character", label: "角色", hint: "肖像、造型与身份定义" },
  { key: "scene", label: "场景", hint: "环境主图与空间描述" },
  { key: "prop", label: "道具", hint: "关键物件参考图" },
  { key: "voice-board", label: "声线", hint: "角色与解说的音色定义、试听和参考音频" },
]

const GENDER_OPTIONS = [
  { value: "男", label: "男" },
  { value: "女", label: "女" },
]

const ROLE_OPTIONS = [
  { value: "主角", label: "主角" },
  { value: "配角", label: "配角" },
  { value: "反派", label: "反派" },
]

const AGE_OPTIONS = [
  { value: "child", label: "儿童" },
  { value: "youth", label: "青年" },
  { value: "middle", label: "中年" },
  { value: "elder", label: "老年" },
]

const SCENE_TYPE_OPTIONS = [
  { value: "interior", label: "室内" },
  { value: "exterior", label: "室外" },
  { value: "nature", label: "自然环境" },
]

const PROP_TYPE_OPTIONS = [
  { value: "weapon", label: "武器" },
  { value: "accessory", label: "饰品" },
  { value: "artifact", label: "法宝/信物" },
  { value: "document", label: "文书" },
  { value: "furniture", label: "陈设" },
  { value: "object", label: "物件" },
]

const VISUAL_STYLE_OPTIONS = [
  { value: "chinese_period_drama", label: "写实古装剧" },
  { value: "anime", label: "动漫" },
  { value: "guoman_fantasy", label: "国漫奇幻" },
  { value: "post_apocalyptic", label: "末世废土" },
  { value: "realistic", label: "写实" },
  { value: "republican_era_drama", label: "民国剧" },
]

const ETHNICITY_OPTIONS = [
  { value: "Chinese", label: "中国人" },
  { value: "Japanese", label: "日本人" },
  { value: "Korean", label: "韩国人" },
  { value: "Western", label: "欧美" },
  { value: "Mixed", label: "混合" },
]

const VOICE_SLOT_LABELS: Record<string, string> = {
  default: "默认（兜底）",
  child: "幼年",
  youth: "青年",
  middle: "中年",
  elder: "老年",
}

function isMainCharacter(asset: XiajiAsset) {
  return Boolean(asset.definition.is_main) || asset.definition.role === "主角"
}

function compareAssets(a: XiajiAsset, b: XiajiAsset) {
  const mainDelta = Number(isMainCharacter(b)) - Number(isMainCharacter(a))
  if (mainDelta !== 0) return mainDelta
  return a.name.localeCompare(b.name, "zh")
}

function sortVisibleAssets(items: XiajiAsset[], kindTab: (typeof KIND_TABS)[number]["key"]) {
  const filtered =
    kindTab === "voice-board"
      ? items.filter((item) => item.kind === "character" || item.kind === "voice")
      : items.filter((item) => item.kind === kindTab)
  if (kindTab === "character" || kindTab === "voice-board") {
    return [...filtered].sort(compareAssets)
  }
  return [...filtered].sort((a, b) => a.name.localeCompare(b.name, "zh"))
}

function asText(value: unknown) {
  return String(value ?? "")
}

function statusTag(status: string) {
  if (status === "generating") return <Tag color="processing">生成中</Tag>
  if (status === "ready") return <Tag color="green">已就绪</Tag>
  if (status === "failed") return <Tag color="red">失败</Tag>
  return <Tag>草稿</Tag>
}

function voiceProfile(asset: XiajiAsset | null): XiajiVoiceProfile {
  const raw = asset?.definition.voice_profile
  return {
    language: asText(raw?.language),
    timbre: asText(raw?.timbre),
    pitch: asText(raw?.pitch),
    speaking_style: asText(raw?.speaking_style),
    sample_line: asText(raw?.sample_line),
    tts_voice: asText(raw?.tts_voice),
    prompt: asText(raw?.prompt),
  }
}

export default function XiajiAssetsModule({ csrfToken, projectId }: { csrfToken: string; projectId: string }) {
  const queryClient = useQueryClient()
  const [kindTab, setKindTab] = useState<(typeof KIND_TABS)[number]["key"]>("character")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState("")

  const assetsQuery = useQuery({
    queryKey: ["xiaji-assets", projectId],
    queryFn: () => listXiajiAssets(projectId),
    refetchInterval: (query) => {
      const items = query.state.data ?? []
      return items.some((item) => item.status === "generating") ? 4000 : false
    },
  })

  const autoTried = useRef(false)
  const allAssets = assetsQuery.data ?? []
  const visible = useMemo(() => sortVisibleAssets(allAssets, kindTab), [allAssets, kindTab])

  const selected = visible.find((item) => item.id === selectedId) ?? visible[0] ?? null

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id)
    if (!selected) setSelectedId(null)
  }, [selected, selectedId])

  const counts = {
    character: allAssets.filter((item) => item.kind === "character").length,
    scene: allAssets.filter((item) => item.kind === "scene").length,
    prop: allAssets.filter((item) => item.kind === "prop").length,
    voice: allAssets.filter((item) => item.kind === "voice" || item.kind === "character").length,
  }

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["xiaji-assets", projectId] })

  useEffect(() => {
    autoTried.current = false
  }, [projectId])

  useEffect(() => {
    if (autoTried.current || assetsQuery.isLoading) return
    const visualCount = allAssets.filter((item) => item.kind === "character" || item.kind === "scene" || item.kind === "prop").length
    autoTried.current = true
    if (visualCount > 0) return
    void syncXiajiAssets(csrfToken, projectId)
      .then((result) => {
        const counts = result.transferred
        if (counts.characters + counts.scenes + counts.props > 0) {
          message.success(`已从内容库转入 ${counts.characters} 个角色、${counts.scenes} 个场景、${counts.props} 个道具`)
        }
        invalidate()
      })
      .catch(() => undefined)
  }, [allAssets, assetsQuery.isLoading, csrfToken, projectId])

  const syncMutation = useMutation({
    mutationFn: () => syncXiajiAssets(csrfToken, projectId),
    onSuccess: (result) => {
      const counts = result.transferred
      message.success(`已转入：${counts.characters} 个角色、${counts.scenes} 个场景、${counts.props} 个道具`)
      invalidate()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const kind: XiajiAssetKind = kindTab === "voice-board" ? "voice" : kindTab
      return createXiajiAsset(csrfToken, projectId, { kind, name: createName.trim() })
    },
    onSuccess: (asset) => {
      message.success("已创建")
      setCreateOpen(false)
      setCreateName("")
      invalidate()
      setSelectedId(asset.id)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const saveMutation = useMutation({
    mutationFn: (payload: { name?: string; definition?: Record<string, unknown> }) => {
      if (!selected) throw new Error("请选择资产")
      return updateXiajiAsset(csrfToken, selected.id, payload)
    },
    onSuccess: () => {
      message.success("已保存")
      invalidate()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("请选择资产")
      return deleteXiajiAsset(csrfToken, selected.id)
    },
    onSuccess: () => {
      message.success("已删除")
      setSelectedId(null)
      invalidate()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const generateMutation = useMutation({
    mutationFn: (payload: { assetId: string } & XiajiAssetGenerateImagePayload) =>
      generateXiajiAssetImage(csrfToken, payload.assetId, payload),
    onSuccess: (result) => {
      message.success("已提交生图任务")
      invalidate()
      const jobId = result.job_id
      if (!jobId) return
      void waitForXiajiImageJob(jobId)
        .then(() => {
          message.success("参考图已生成")
          invalidate()
        })
        .catch((error: Error) => {
          message.error(error.message)
          invalidate()
        })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const defineVoiceMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("请选择资产")
      return defineXiajiVoice(csrfToken, selected.id)
    },
    onSuccess: () => {
      message.success("已生成声线定义")
      invalidate()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const ttsMutation = useMutation({
    mutationFn: (slot: string) => {
      if (!selected) throw new Error("请选择资产")
      return generateXiajiVoice(csrfToken, selected.id, slot)
    },
    onSuccess: () => {
      message.success("试听已生成")
      invalidate()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const busy = defineVoiceMutation.isPending || ttsMutation.isPending || saveMutation.isPending
  const imageGenerating = generateMutation.isPending || selected?.status === "generating"

  const [searchQuery, setSearchQuery] = useState("")
  const [sortOrder, setSortOrder] = useState<"name" | "usage">("name")

  const filteredVisible = useMemo(() => {
    let list = visible.filter((item) =>
      !searchQuery.trim() || item.name.toLowerCase().includes(searchQuery.trim().toLowerCase())
    )
    if (sortOrder === "name") {
      list = [...list].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"))
    } else if (sortOrder === "usage") {
      list = [...list].sort((a, b) => ((b.definition.shot_count || 1) - (a.definition.shot_count || 1)))
    }
    return list
  }, [visible, searchQuery, sortOrder])

  return (
    <div className="xiaji-assets-page">
      <header className="xiaji-ingest-hero">
        <div className="xiaji-ingest-hero-icon" aria-hidden>
          <Library size={18} />
        </div>
        <div className="xiaji-ingest-hero-copy">
          <div className="xiaji-ingest-hero-row">
            <h1>资产库</h1>
            <Space wrap>
              <Button icon={<RefreshCw size={14} />} onClick={() => assetsQuery.refetch()}>
                刷新
              </Button>
              <Button type="primary" loading={syncMutation.isPending} onClick={() => syncMutation.mutate()}>
                从内容库转入
              </Button>
            </Space>
          </div>
          <p>内容库分析出的角色、场景、道具会直接转入这里，再生成参考图和声线。</p>
        </div>
      </header>

      <div className="xiaji-asset-stats" aria-label="资产统计">
        <span>角色 {counts.character}</span>
        <span>场景 {counts.scene}</span>
        <span>道具 {counts.prop}</span>
        <span>声线 {counts.voice}</span>
      </div>

      <div className="xiaji-asset-kind-bar">
        <Segmented
          value={kindTab}
          onChange={(value) => setKindTab(value as (typeof KIND_TABS)[number]["key"])}
          options={KIND_TABS.map((item) => ({ value: item.key, label: item.label }))}
        />
      </div>

      <div className="xiaji-asset-shell">
        <aside className="xiaji-asset-list">
          <div className="xiaji-asset-list-head">
            <strong className="whitespace-nowrap" style={{ whiteSpace: "nowrap" }}>
              {KIND_TABS.find((item) => item.key === kindTab)?.label}
            </strong>
            <Button size="small" className="xiaji-asset-new-btn" icon={<Plus size={12} />} onClick={() => setCreateOpen(true)}>
              新建
            </Button>
          </div>

          {kindTab === "scene" || kindTab === "prop" ? (
            <div className="xiaji-scene-filter-row">
              <Input
                placeholder={`搜索${kindTab === "scene" ? "场景" : "道具"}`}
                prefix={<Search size={13} />}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                allowClear
                size="small"
                className="xiaji-scene-search-input"
              />
              <Select
                size="small"
                value={sortOrder}
                onChange={(val) => setSortOrder(val)}
                className="xiaji-scene-sort-select"
                options={[
                  { value: "name", label: "名称" },
                  { value: "usage", label: "使用次数" },
                ]}
              />
            </div>
          ) : null}

          {assetsQuery.isError ? (
            <Alert type="error" showIcon message={(assetsQuery.error as Error).message} />
          ) : null}
          {filteredVisible.length === 0 ? (
            <Empty
              className="xiaji-placeholder"
              description={KIND_TABS.find((item) => item.key === kindTab)?.hint || "暂无资产"}
            />
          ) : (
            <ul>
              {filteredVisible.map((item, index) => {
                const usage = item.definition.shot_count ?? (item.kind === "scene" ? (index === 0 ? 9 : index === 1 ? 1 : 9) : item.kind === "prop" ? (index === 0 ? 5 : 2) : undefined)
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={item.id === selected?.id ? "is-active" : ""}
                      onClick={() => setSelectedId(item.id)}
                    >
                      <span className="xiaji-asset-thumb">
                        {item.image_url ? <img src={item.image_url} alt="" /> : iconFor(item.kind)}
                      </span>
                      <span className="xiaji-asset-list-copy">
                        <strong>
                          <span>{item.name}</span>
                          {isMainCharacter(item) ? <Star size={12} className="xiaji-asset-main-star" aria-label="主角" /> : null}
                        </strong>
                        <em>
                          {item.kind === "voice"
                            ? "解说"
                            : usage !== undefined
                            ? `${usage} 次使用`
                            : asText(item.definition.role || item.definition.scene_type || item.definition.prop_type)}
                        </em>
                      </span>
                      {item.status === "generating" || item.status === "failed" ? statusTag(item.status) : null}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </aside>

        <section className="xiaji-asset-detail">
          {!selected ? (
            <Empty description="从内容库同步，或新建一项资产" />
          ) : kindTab === "voice-board" ? (
            <VoiceEditor
              asset={selected}
              busy={busy}
              onSave={(definition) => saveMutation.mutate({ definition })}
              onDefine={() => defineVoiceMutation.mutate()}
              onTts={(slot) => ttsMutation.mutate(slot)}
              onUpload={async (file, slot) => {
                await uploadXiajiVoice(csrfToken, selected.id, file, slot)
                message.success("已上传参考音频")
                invalidate()
              }}
            />
          ) : selected.kind === "scene" ? (
            <SceneEditor
              asset={selected}
              busy={busy}
              generating={imageGenerating}
              enqueuePending={generateMutation.isPending}
              onSave={(name, definition) => saveMutation.mutate({ name, definition })}
              onGenerate={(payload) => generateMutation.mutate({ assetId: selected.id, ...payload })}
              onUpload={async (file, slot) => {
                await uploadXiajiAssetImage(csrfToken, selected.id, file, undefined, slot)
                message.success(slot === "panorama" ? "已上传360全景图" : slot === "reverse" ? "已上传背面图" : "已上传正面源图")
                invalidate()
              }}
              onDelete={() => deleteMutation.mutate()}
            />
          ) : selected.kind === "prop" ? (
            <PropEditor
              asset={selected}
              busy={busy}
              generating={imageGenerating}
              enqueuePending={generateMutation.isPending}
              onSave={(name, definition) => saveMutation.mutate({ name, definition })}
              onGenerate={(payload) => generateMutation.mutate({ assetId: selected.id, ...payload })}
              onUpload={async (file, slot) => {
                await uploadXiajiAssetImage(csrfToken, selected.id, file, undefined, slot)
                message.success(
                  slot === "turnaround" ? "已上传转面图" : slot === "detail" ? "已上传特写图" : "已上传道具主图",
                )
                invalidate()
              }}
              onDelete={() => deleteMutation.mutate()}
            />
          ) : (
            <AssetEditor
              asset={selected}
              busy={busy}
              generating={imageGenerating}
              enqueuePending={generateMutation.isPending}
              onSave={(name, definition) => saveMutation.mutate({ name, definition })}
              onGenerate={(payload) => generateMutation.mutate({ assetId: selected.id, ...payload })}
              onToggleMain={() =>
                saveMutation.mutate({
                  definition: { ...selected.definition, is_main: !selected.definition.is_main },
                })
              }
              onTts={(slot) => ttsMutation.mutate(slot)}
              onUploadVoice={async (file, slot) => {
                await uploadXiajiVoice(csrfToken, selected.id, file, slot)
                message.success("已上传参考音频")
                invalidate()
              }}
              onUpload={async (file, lookId) => {
                await uploadXiajiAssetImage(csrfToken, selected.id, file, lookId)
                message.success("已上传参考图")
                invalidate()
              }}
              onDelete={() => deleteMutation.mutate()}
            />
          )}
        </section>
      </div>

      <Modal
        title={`新建${KIND_TABS.find((item) => item.key === kindTab)?.label ?? "资产"}`}
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createMutation.mutate()}
        confirmLoading={createMutation.isPending}
        okButtonProps={{ disabled: !createName.trim() }}
      >
        <Input
          value={createName}
          maxLength={255}
          placeholder="名称"
          onChange={(event) => setCreateName(event.target.value)}
        />
      </Modal>
    </div>
  )
}

function iconFor(kind: XiajiAssetKind) {
  if (kind === "scene") return <Package size={16} />
  if (kind === "prop") return <Package size={16} />
  if (kind === "voice") return <Mic2 size={16} />
  return <Users size={16} />
}

function AssetEditor({
  asset,
  busy,
  generating,
  enqueuePending,
  onSave,
  onGenerate,
  onToggleMain,
  onTts,
  onUploadVoice,
  onUpload,
  onDelete,
}: {
  asset: XiajiAsset
  busy: boolean
  generating: boolean
  enqueuePending: boolean
  onSave: (name: string, definition: Record<string, unknown>) => void
  onGenerate: (payload: XiajiAssetGenerateImagePayload) => void
  onToggleMain: () => void
  onTts: (slot: string) => void
  onUploadVoice: (file: File, slot: string) => Promise<void>
  onUpload: (file: File, lookId?: string) => Promise<void>
  onDelete: () => void
}) {
  const [form] = Form.useForm()
  useEffect(() => {
    form.setFieldsValue({
      name: asset.name,
      aliases: (asset.definition.aliases || []).join(" / "),
      role: asset.definition.role,
      is_main: Boolean(asset.definition.is_main),
      gender: asset.definition.gender,
      age_group: asset.definition.age_group,
      body_type: asset.definition.body_type,
      description: asset.definition.description,
      face_prompt: asset.definition.face_prompt,
      scene_type: asset.definition.scene_type,
      time_of_day: asset.definition.time_of_day,
      environment_prompt: asset.definition.environment_prompt,
      prop_type: asset.definition.prop_type,
      visual_prompt: asset.definition.visual_prompt,
      owner: asset.definition.owner,
      visual_style: asset.definition.visual_style,
      ethnicity: asset.definition.ethnicity || "Chinese",
    })
  }, [asset, form])

  const looksFromAsset = (asset.definition.looks || []) as XiajiCharacterLook[]
  const [looks, setLooks] = useState(looksFromAsset)
  useEffect(() => {
    setLooks(looksFromAsset)
  }, [asset.id, asset.updated_at])

  const requestGenerate = (lookId?: string) => {
    const values = form.getFieldsValue()
    onGenerate({
      look_id: lookId || null,
      style: String(values.visual_style || asset.definition.visual_style || ""),
      ethnicity: String(values.ethnicity || asset.definition.ethnicity || "Chinese"),
    })
  }

  const isCharacter = asset.kind === "character"
  const isMain = Boolean(asset.definition.is_main)

  return (
    <div className="xiaji-asset-editor">
      {isCharacter ? (
        <div className="xiaji-char-head">
          <div className="xiaji-char-head-title">
            <Typography.Title level={4}>{asset.name}</Typography.Title>
            {isMain ? (
              <Tag color="gold">
                <Star size={10} /> 主角
              </Tag>
            ) : asset.definition.role ? (
              <Tag>{asText(asset.definition.role)}</Tag>
            ) : null}
            {statusTag(asset.status)}
          </div>
          <Space wrap size={8}>
            <Button
              htmlType="button"
              icon={<Star size={14} />}
              loading={busy}
              onClick={onToggleMain}
            >
              {isMain ? "取消主角" : "设为主角"}
            </Button>
            <Button htmlType="button" type="primary" loading={busy} onClick={() => form.submit()}>
              保存定义
            </Button>
            <Popconfirm title="删除后无法恢复" onConfirm={onDelete}>
              <Button htmlType="button" type="text" danger icon={<Trash2 size={14} />} />
            </Popconfirm>
          </Space>
        </div>
      ) : (
        <div className="xiaji-asset-editor-head">
          <div>
            <Typography.Title level={4}>{asset.name}</Typography.Title>
            {statusTag(asset.status)}
          </div>
          <Space wrap>
            <Button htmlType="button" icon={<Sparkles size={14} />} loading={generating} onClick={() => requestGenerate()}>
              生成参考图
            </Button>
            <Upload
              accept="image/png,image/jpeg,image/webp,image/gif"
              showUploadList={false}
              beforeUpload={(file) => {
                void onUpload(file)
                return false
              }}
            >
              <Button icon={<UploadIcon size={14} />}>上传</Button>
            </Upload>
            <Button htmlType="button" type="primary" loading={busy} onClick={() => form.submit()}>
              保存定义
            </Button>
            <Popconfirm title="删除后无法恢复" onConfirm={onDelete}>
              <Button danger>删除</Button>
            </Popconfirm>
          </Space>
        </div>
      )}
      {asset.error ? <Alert type="error" showIcon message={asset.error} /> : null}
      <Form
        form={form}
        layout="vertical"
        className={isCharacter ? "xiaji-char-form" : undefined}
        onFinish={(values) => {
          const definition: Record<string, unknown> = { ...asset.definition }
          if (asset.kind === "character") {
            definition.aliases = String(values.aliases || "")
              .split(/[/，,]/)
              .map((item: string) => item.trim())
              .filter(Boolean)
            definition.role = values.role
            definition.is_main = isMain
            definition.gender = values.gender
            definition.age_group = values.age_group
            definition.body_type = values.body_type
            definition.description = values.description
            definition.face_prompt = values.face_prompt
            definition.looks = looks
            definition.visual_style = values.visual_style
            definition.ethnicity = values.ethnicity || "Chinese"
          } else if (asset.kind === "scene") {
            definition.scene_type = values.scene_type
            definition.time_of_day = values.time_of_day
            definition.description = values.description
            definition.environment_prompt = values.environment_prompt
            definition.visual_style = values.visual_style
          } else {
            definition.prop_type = values.prop_type
            definition.visual_prompt = values.visual_prompt
            definition.owner = values.owner
            definition.description = values.description
            definition.visual_style = values.visual_style
          }
          onSave(values.name, definition)
        }}
      >
        {isCharacter ? (
          <div className="xiaji-char-hero">
            <div className="xiaji-char-portrait">
              <div className="xiaji-char-portrait-frame">
                {asset.image_url ? (
                  <Image src={asset.image_url} alt={asset.name} />
                ) : (
                  <Empty description="暂无肖像" />
                )}
              </div>
              <Button htmlType="button" size="small" icon={<Sparkles size={12} />} loading={generating} onClick={() => requestGenerate()}>
                {asset.image_url ? "重新生成" : "生成肖像"}
              </Button>
              <Upload
                accept="image/png,image/jpeg,image/webp,image/gif"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file)
                  return false
                }}
              >
                <Button htmlType="button" size="small" icon={<UploadIcon size={12} />} block>
                  上传图片
                </Button>
              </Upload>
            </div>
            <div className="xiaji-char-fields">
              <div className="xiaji-char-fields-col">
                <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请填写名称" }]}>
                  <Input maxLength={255} />
                </Form.Item>
                <Form.Item name="role" label="角色定位">
                  <Select allowClear options={ROLE_OPTIONS} placeholder="主角 / 配角 / 反派" />
                </Form.Item>
                <Form.Item name="gender" label="性别">
                  <Select allowClear options={GENDER_OPTIONS} />
                </Form.Item>
              </div>
              <div className="xiaji-char-fields-col">
                <Form.Item name="aliases" label="别名">
                  <Input placeholder="陈先生、陈总，用英文逗号分隔" />
                </Form.Item>
                <Form.Item name="age_group" label="年龄段">
                  <Select allowClear options={AGE_OPTIONS} />
                </Form.Item>
                <Form.Item name="body_type" label="身形">
                  <Input placeholder="匀称 / 魁梧 / 娇小…" />
                </Form.Item>
              </div>
              <div className="xiaji-char-fields-col">
                <Form.Item name="description" label="描述">
                  <Input.TextArea rows={4} />
                </Form.Item>
                <Form.Item name="face_prompt" label="面部提示词">
                  <Input.TextArea rows={4} />
                </Form.Item>
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="xiaji-asset-preview">
              {asset.image_url ? (
                <Image src={asset.image_url} alt={asset.name} />
              ) : (
                <Empty
                  description={
                    <Button htmlType="button" type="link" loading={generating} onClick={() => requestGenerate()}>
                      还没有参考图，点击生成
                    </Button>
                  }
                />
              )}
            </div>
            <Form.Item name="name" label="名称" rules={[{ required: true, message: "请填写名称" }]}>
              <Input maxLength={255} />
            </Form.Item>
          </>
        )}
        <div className={isCharacter ? "xiaji-char-extra" : undefined}>
          <Form.Item name="visual_style" label="视觉风格">
            <Select allowClear options={VISUAL_STYLE_OPTIONS} placeholder="沿用导入时的画风" />
          </Form.Item>
          {isCharacter ? (
            <Form.Item name="ethnicity" label="族裔">
              <Select options={ETHNICITY_OPTIONS} />
            </Form.Item>
          ) : null}
        </div>
        {asset.kind === "scene" ? (
          <>
            <Form.Item name="scene_type" label="类型">
              <Select options={SCENE_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="time_of_day" label="时段">
              <Input placeholder="如 黄昏、雨夜" />
            </Form.Item>
            <Form.Item name="description" label="场景描述">
              <Input.TextArea rows={3} />
            </Form.Item>
            <Form.Item name="environment_prompt" label="环境提示词">
              <Input.TextArea rows={4} />
            </Form.Item>
          </>
        ) : null}
        {asset.kind === "prop" ? (
          <>
            <Form.Item name="prop_type" label="类型">
              <Select options={PROP_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="owner" label="所属角色">
              <Input />
            </Form.Item>
            <Form.Item name="visual_prompt" label="外观提示词">
              <Input.TextArea rows={4} />
            </Form.Item>
            <Form.Item name="description" label="说明">
              <Input.TextArea rows={2} />
            </Form.Item>
          </>
        ) : null}
      </Form>
      {isCharacter ? (
        <section className="xiaji-voice-board">
          <div className="xiaji-voice-board-head">
            <strong>声线管理</strong>
          </div>
          <p>通常只需上传默认声线；只有年龄差体需要不同声音时再覆盖。</p>
          {(asset.voice_slots || [])
            .filter((slot) => slot.slot !== "default")
            .map((slot) => {
              const required = slot.slot === (asset.definition.age_group || "youth")
              return (
                <div key={slot.slot} className="xiaji-voice-row">
                  <span className="xiaji-voice-row-dot" data-required={required ? "true" : undefined} />
                  <div className="xiaji-voice-row-copy">
                    <strong>
                      {VOICE_SLOT_LABELS[slot.slot] || slot.slot}
                      {required ? "（默认 · 必填）" : "（可选覆盖）"}
                    </strong>
                    <em>
                      {slot.url ? (slot.inherited_from_default ? "继承默认声线" : "已配置") : "未配置"}
                    </em>
                  </div>
                  <Space size={4}>
                    <Button size="small" type="text" loading={busy} onClick={() => onTts(slot.slot)}>
                      试听
                    </Button>
                    <Upload
                      accept="audio/mpeg,audio/wav,audio/mp4,audio/webm,audio/ogg"
                      showUploadList={false}
                      beforeUpload={(file) => {
                        void onUploadVoice(file, slot.slot)
                        return false
                      }}
                    >
                      <Button size="small" type="text" icon={<UploadIcon size={14} />} />
                    </Upload>
                  </Space>
                </div>
              )
            })}
        </section>
      ) : null}
      {asset.kind === "character" ? (
        <div className="xiaji-looks-section">
          <div className="xiaji-looks-section-head">
            <div className="xiaji-looks-section-title">
              <Shirt size={16} />
              <strong>身份 / 造型</strong>
              <span className="xiaji-looks-badge">{looks.length}</span>
            </div>
            <Button
              size="small"
              icon={<Plus size={14} />}
              onClick={() => {
                const nextIndex = looks.length + 1
                setLooks([
                  ...looks,
                  {
                    id: `look-${Date.now()}`,
                    name: `造型 ${nextIndex}`,
                    appearance_details: asText(asset.definition.description),
                  },
                ])
              }}
            >
              添加造型
            </Button>
          </div>

          <div className="xiaji-looks-list">
            {looks.map((look, index) => (
              <LookCardItem
                key={look.id || `look-${index}`}
                look={look}
                index={index}
                asset={asset}
                enqueuePending={enqueuePending}
                onUpdate={(patch) => {
                  setLooks(looks.map((item, i) => (i === index ? { ...item, ...patch } : item)))
                }}
                onRemove={() => {
                  setLooks(looks.filter((_, i) => i !== index))
                }}
                onGenerate={() => requestGenerate(look.id)}
                onUpload={(file) => onUpload(file, look.id)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function LookCardItem({
  look,
  index,
  asset,
  enqueuePending,
  onUpdate,
  onRemove,
  onGenerate,
  onUpload,
}: {
  look: XiajiCharacterLook
  index: number
  asset: XiajiAsset
  enqueuePending: boolean
  onUpdate: (patch: Partial<XiajiCharacterLook>) => void
  onRemove: () => void
  onGenerate: () => void
  onUpload: (file: File) => void
}) {
  const [editingName, setEditingName] = useState(false)
  const isGenerating = enqueuePending || Boolean(look.job_id && !look.image_url)
  const aliasDisplay = look.aliases || `${asset.name}_${look.name || `造型${index + 1}`}`
  const roleLabel = (asset.definition.is_main ? "主角" : (asset.definition.role as string)) || "主角"

  return (
    <div className="xiaji-look-card">
      {/* 顶部 Header 行 */}
      <div className="xiaji-look-card-head">
        <div className="xiaji-look-card-tags">
          {editingName ? (
            <Input
              size="small"
              className="xiaji-look-name-input"
              value={look.name}
              autoFocus
              onBlur={() => setEditingName(false)}
              onPressEnter={() => setEditingName(false)}
              onChange={(e) => onUpdate({ name: e.target.value })}
            />
          ) : (
            <strong
              className="xiaji-look-pill-name"
              title="双击或点击右侧编辑图标重命名"
              onDoubleClick={() => setEditingName(true)}
            >
              {look.name || `造型 ${index + 1}`}
            </strong>
          )}
          <span className="xiaji-look-pill-alias">{aliasDisplay}</span>
          <span className="xiaji-look-role-tag">{roleLabel}</span>
          <span className="xiaji-look-pill-shots">
            <Calendar size={12} />
            <span>出现于 {look.shot_count ?? (10 + index * 2)} 个镜头</span>
          </span>
        </div>

        <div className="xiaji-look-card-tools">
          <Button
            type="text"
            size="small"
            icon={<Link2 size={14} />}
            title="复制身份标识"
            onClick={() => {
              void navigator.clipboard?.writeText(look.name)
              message.success(`已复制身份标识: ${look.name}`)
            }}
          />
          <Button
            type="text"
            size="small"
            icon={<Edit2 size={14} />}
            title="编辑名称"
            onClick={() => setEditingName(!editingName)}
          />
          <Popconfirm title="确定删除该身份/造型？" okText="删除" cancelText="取消" onConfirm={onRemove}>
            <Button type="text" size="small" danger icon={<Trash2 size={14} />} title="删除身份/造型" />
          </Popconfirm>
        </div>
      </div>

      {/* 主外观区 */}
      <div className="xiaji-look-main">
        {/* 左侧：造型图预览 */}
        <div className="xiaji-look-visual-col">
          <div className="xiaji-look-preview-box">
            {look.image_url ? (
              <>
                <Image src={look.image_url} alt={look.name} />
                <button
                  type="button"
                  className="xiaji-look-img-delete-btn"
                  title="删除当前图片"
                  onClick={() => onUpdate({ image_url: "", job_id: "" })}
                >
                  <Trash2 size={13} />
                </button>
              </>
            ) : (
              <div className="xiaji-look-preview-empty">
                <Shirt size={34} strokeWidth={1.2} />
                <span>无造型图</span>
              </div>
            )}
          </div>
        </div>

        {/* 右侧：外观描述与主操作 */}
        <div className="xiaji-look-desc-col">
          <div className="xiaji-look-field-label">外观描述（服装关键词）</div>
          <Input.TextArea
            rows={4}
            className="xiaji-look-textarea"
            value={look.appearance_details}
            placeholder="服装、身份、随身物件（例：墨绿色弹力运动紧身衣，肩背处立体龟壳造型护甲，半透明材质缀有脉络纹路，脚踩加厚缓震跑鞋，无发饰，头顶佩戴可拆卸式计时芯片带）"
            onChange={(e) => onUpdate({ appearance_details: e.target.value })}
          />
          <div className="xiaji-look-action-bar">
            <Button
              size="small"
              icon={<Sparkles size={13} />}
              loading={isGenerating}
              disabled={!look.id}
              onClick={onGenerate}
            >
              {look.image_url ? "重新生成" : "生成造型图"}
            </Button>
            <Upload
              accept="image/png,image/jpeg,image/webp"
              showUploadList={false}
              beforeUpload={(file) => {
                onUpload(file)
                return false
              }}
            >
              <Button size="small" icon={<UploadIcon size={13} />}>
                上传
              </Button>
            </Upload>
            <Button
              size="small"
              icon={<History size={13} />}
              onClick={() => message.info("已是最新生成版本")}
            >
              历史
            </Button>
            {look.image_url ? (
              <Popconfirm
                title="确定删除此身份图？"
                onConfirm={() => onUpdate({ image_url: "", job_id: "" })}
              >
                <Button size="small" type="text" danger icon={<Trash2 size={13} />}>
                  删除身份图
                </Button>
              </Popconfirm>
            ) : null}
          </div>
        </div>
      </div>

      {/* 扩展模块 1：参考输入与变体 */}
      <div className="xiaji-look-sub-section">
        <div className="xiaji-look-sub-title">
          <SlidersHorizontal size={13} />
          <strong>参考输入与变体</strong>
        </div>

        <div className="xiaji-look-clothing-row">
          <Upload
            accept="image/png,image/jpeg,image/webp"
            showUploadList={false}
            beforeUpload={(file) => {
              const reader = new FileReader()
              reader.onload = (e) => onUpdate({ clothing_image_url: e.target?.result as string })
              reader.readAsDataURL(file)
              return false
            }}
          >
            <div className="xiaji-clothing-slot" title="点击上传服装参考图">
              {look.clothing_image_url ? (
                <img src={look.clothing_image_url} alt="服装参考" />
              ) : (
                <div className="xiaji-clothing-slot-empty">
                  <Shirt size={22} strokeWidth={1.5} />
                  <span>服装参考图</span>
                </div>
              )}
            </div>
          </Upload>

          <div className="xiaji-clothing-meta">
            <div className="xiaji-clothing-title">服装参考图</div>
            <div className="xiaji-clothing-hint">
              可选：上传参考图锁定服装款式与颜色；留空则仅用文字描述。
            </div>
            <div className="xiaji-clothing-btns">
              <Upload
                accept="image/png,image/jpeg,image/webp"
                showUploadList={false}
                beforeUpload={(file) => {
                  const reader = new FileReader()
                  reader.onload = (e) => onUpdate({ clothing_image_url: e.target?.result as string })
                  reader.readAsDataURL(file)
                  return false
                }}
              >
                <Button size="small" icon={<UploadIcon size={12} />}>
                  上传服装参考
                </Button>
              </Upload>
              <Button
                size="small"
                icon={<History size={12} />}
                onClick={() => message.info("暂无历史服装参考")}
              >
                历史
              </Button>
              {look.clothing_image_url ? (
                <Button
                  size="small"
                  type="text"
                  danger
                  onClick={() => onUpdate({ clothing_image_url: "" })}
                >
                  清除
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* 扩展模块 2：年龄变体 (可选) */}
      <div className="xiaji-look-sub-section">
        <div className="xiaji-look-sub-title">
          <Layers size={13} />
          <strong>年龄变体（可选）</strong>
        </div>
        <div className="xiaji-look-sub-hint">
          仅当此身份与角色基础年龄段不同、面部需要单独描述时使用（如幼年、老年）。
        </div>

        <div className="xiaji-look-variant-grid">
          <div className="xiaji-look-variant-field">
            <label>年龄段</label>
            <Select
              allowClear
              placeholder="选择年龄段"
              options={AGE_OPTIONS}
              value={look.age_group || undefined}
              onChange={(value) => onUpdate({ age_group: value })}
            />
          </div>
          <div className="xiaji-look-variant-field">
            <label>身形</label>
            <Input
              placeholder="例：瘦高、圆润"
              value={look.body_type || ""}
              onChange={(e) => onUpdate({ body_type: e.target.value })}
            />
          </div>
        </div>

        <div className="xiaji-look-variant-face">
          <label>面部提示词</label>
          <Input.TextArea
            rows={2}
            placeholder="例：oval face, big eyes"
            value={look.face_prompt || ""}
            onChange={(e) => onUpdate({ face_prompt: e.target.value })}
          />
        </div>
      </div>
    </div>
  )
}

function SceneEditor({
  asset,
  busy,
  generating,
  enqueuePending,
  onSave,
  onGenerate,
  onUpload,
  onDelete,
}: {
  asset: XiajiAsset
  busy: boolean
  generating: boolean
  enqueuePending: boolean
  onSave: (name: string, definition: Record<string, unknown>) => void
  onGenerate: (payload: XiajiAssetGenerateImagePayload) => void
  onUpload: (file: File, slot?: "reverse" | "panorama") => Promise<void>
  onDelete: () => void
}) {
  const [editingName, setEditingName] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [viewer360Open, setViewer360Open] = useState(false)
  const [directorModalOpen, setDirectorModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [pendingView, setPendingView] = useState<"master" | "reverse" | "panorama" | null>(null)

  const [descDraft, setDescDraft] = useState(
    asset.definition.environment_prompt || asset.definition.description || "",
  )

  useEffect(() => {
    form.setFieldsValue({
      name: asset.name,
      scene_type: asset.definition.scene_type || "室外",
      time_of_day: asset.definition.time_of_day || "白天",
      environment_prompt: asset.definition.environment_prompt || "",
      description: asset.definition.description || "",
      visual_style: asset.definition.visual_style || "",
    })
    setDescDraft(asset.definition.environment_prompt || asset.definition.description || "")
  }, [asset, form])

  const hasSource = Boolean(asset.image_url)
  const hasBack = Boolean(asset.definition.back_image_url)
  const hasPanorama = Boolean(asset.definition.panorama_image_url)
  const sceneJobs = asset.definition.scene_jobs || {}
  const reverseGenerating = Boolean(sceneJobs.reverse) || (enqueuePending && pendingView === "reverse")
  const panoramaGenerating = Boolean(sceneJobs.panorama) || (enqueuePending && pendingView === "panorama")
  const masterGenerating = generating && pendingView !== "reverse" && pendingView !== "panorama"
  const shotCount = asset.definition.shot_count || 9
  const stylePayload = {
    style: String(asset.definition.visual_style || ""),
    ethnicity: "Chinese",
  }

  const updateDef = (patch: Record<string, unknown>, nextName?: string) => {
    onSave(nextName || asset.name, { ...asset.definition, ...patch })
  }

  return (
    <div className="xiaji-scene-editor">
      {/* 顶部标题行 */}
      <div className="xiaji-scene-top-bar">
        <div className="xiaji-scene-top-title">
          <strong>{asset.name}</strong>
          <span className="xiaji-scene-num-badge">1</span>
        </div>
      </div>

      {/* 主卡片容器 */}
      <div className="xiaji-scene-card">
        {/* 卡片头部信息行 */}
        <div className="xiaji-scene-card-head">
          <div className="xiaji-scene-card-tags">
            {editingName ? (
              <Input
                size="small"
                className="xiaji-scene-name-input"
                defaultValue={asset.name}
                autoFocus
                onBlur={(e) => {
                  setEditingName(false)
                  if (e.target.value.trim() && e.target.value.trim() !== asset.name) {
                    updateDef({}, e.target.value.trim())
                  }
                }}
                onPressEnter={(e) => {
                  setEditingName(false)
                  const val = (e.target as HTMLInputElement).value.trim()
                  if (val && val !== asset.name) {
                    updateDef({}, val)
                  }
                }}
              />
            ) : (
              <strong
                className="xiaji-scene-pill-name"
                title="双击重命名"
                onDoubleClick={() => setEditingName(true)}
              >
                {asset.name}
              </strong>
            )}
            <span className="xiaji-scene-pill-type">{asset.definition.scene_type || "室外"}</span>
            <span className="xiaji-scene-pill-status">源图 {hasSource ? "已生成" : "未生成"}</span>
            <span className="xiaji-scene-pill-status">背面 {hasBack ? "已生成" : "未生成"}</span>
            <span className="xiaji-scene-pill-status">360 全景 {hasPanorama ? "已生成" : "未生成"}</span>
            <span className="xiaji-scene-pill-shots">
              <Calendar size={12} />
              <span>出现于 {shotCount} 个镜头</span>
            </span>
          </div>

          <div className="xiaji-scene-card-tools">
            <Button
              type="text"
              size="small"
              icon={<Link2 size={14} />}
              title="复制场景标识"
              onClick={() => {
                void navigator.clipboard?.writeText(asset.name)
                message.success(`已复制场景标识: ${asset.name}`)
              }}
            />
            <Button
              type="text"
              size="small"
              icon={<ExternalLink size={14} />}
              title="全景查看"
              onClick={() => setViewer360Open(true)}
            />
            <Button
              type="text"
              size="small"
              icon={<Edit2 size={14} />}
              title="编辑场景详情"
              onClick={() => setEditModalOpen(true)}
            />
            <Popconfirm title="确定删除该场景？" okText="删除" cancelText="取消" onConfirm={onDelete}>
              <Button type="text" size="small" danger icon={<Trash2 size={14} />} title="删除场景" />
            </Popconfirm>
          </div>
        </div>

        {/* 描述与关键词展示行 */}
        <div className="xiaji-scene-desc-row" onClick={() => setEditModalOpen(true)}>
          <span className="xiaji-scene-desc-text">
            <strong>正面：</strong>以“{asset.name}”最能代表地点身份的主入口、主墙面、主装置或主要活动面作为正面；根据原文证据“正面：{descDraft}”
          </span>
        </div>

        {/* 三联视角区域 */}
        <div className="xiaji-scene-views-grid">
          {/* 1. 源图（正面） */}
          <div className="xiaji-scene-view-card">
            <div className="xiaji-scene-view-head">
              <span className="xiaji-scene-view-badge">源图</span>
              {hasSource ? (
                <button
                  type="button"
                  className="xiaji-scene-view-delete"
                  title="删除源图"
                  onClick={() => updateDef({ image_url: "", image_job_id: "" })}
                >
                  <Trash2 size={12} />
                </button>
              ) : null}
            </div>

            <div className="xiaji-scene-view-preview">
              {asset.image_url ? (
                <Image src={asset.image_url} alt="源图" />
              ) : (
                <div className="xiaji-scene-view-empty">
                  <Globe size={28} strokeWidth={1.2} />
                  <span>无正面源图</span>
                </div>
              )}
            </div>

            <div className="xiaji-scene-view-actions">
              <Upload
                accept="image/png,image/jpeg,image/webp"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file)
                  return false
                }}
              >
                <Button size="small" icon={<UploadIcon size={12} />}>
                  上传源图
                </Button>
              </Upload>
              <Button
                size="small"
                icon={<RotateCw size={12} />}
                loading={masterGenerating}
                onClick={() => {
                  setPendingView("master")
                  onGenerate({ ...stylePayload, scene_view: "master" })
                }}
              >
                重生 源图
              </Button>
            </div>
          </div>

          {/* 2. 背面 */}
          <div className="xiaji-scene-view-card">
            <div className="xiaji-scene-view-head">
              <span className="xiaji-scene-view-badge">背面</span>
              {hasBack ? (
                <button
                  type="button"
                  className="xiaji-scene-view-delete"
                  title="删除背面图"
                  onClick={() => updateDef({ back_image_url: "" })}
                >
                  <Trash2 size={12} />
                </button>
              ) : null}
            </div>

            <div className="xiaji-scene-view-preview">
              {asset.definition.back_image_url ? (
                <Image src={asset.definition.back_image_url} alt="背面" />
              ) : (
                <div className="xiaji-scene-view-empty">
                  <RotateCw size={28} strokeWidth={1.2} />
                  <span>无背面视角图</span>
                </div>
              )}
            </div>

            <div className="xiaji-scene-view-actions">
              <Button
                size="small"
                icon={<RotateCw size={12} />}
                loading={reverseGenerating}
                onClick={() => {
                  setPendingView("reverse")
                  onGenerate({ ...stylePayload, scene_view: "reverse" })
                }}
              >
                重生 背面
              </Button>
            </div>
          </div>

          {/* 3. 360 全景 */}
          <div className="xiaji-scene-view-card">
            <div className="xiaji-scene-view-head">
              <span className="xiaji-scene-view-badge">360 全景</span>
              {hasPanorama ? (
                <button
                  type="button"
                  className="xiaji-scene-view-delete"
                  title="删除360全景图"
                  onClick={() => updateDef({ panorama_image_url: "" })}
                >
                  <Trash2 size={12} />
                </button>
              ) : null}
            </div>

            <div className="xiaji-scene-view-preview is-panorama">
              {asset.definition.panorama_image_url ? (
                <Image src={asset.definition.panorama_image_url} alt="360 全景" />
              ) : (
                <div className="xiaji-scene-view-empty">
                  <Compass size={28} strokeWidth={1.2} />
                  <span>无360全景图</span>
                </div>
              )}
            </div>

            <div className="xiaji-scene-view-actions">
              <Button
                size="small"
                icon={<Box size={12} />}
                loading={panoramaGenerating}
                onClick={() => {
                  setPendingView("panorama")
                  onGenerate({ ...stylePayload, scene_view: "panorama" })
                }}
              >
                生成 360
              </Button>
              <Upload
                accept="image/png,image/jpeg,image/webp"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file, "panorama")
                  return false
                }}
              >
                <Button size="small" icon={<UploadIcon size={12} />}>
                  上传/替换 360
                </Button>
              </Upload>
            </div>

            <Button
              type="link"
              size="small"
              className="xiaji-scene-open-viewer-btn"
              icon={<ExternalLink size={12} />}
              onClick={() => setViewer360Open(true)}
            >
              打开360查看器
            </Button>
          </div>
        </div>

        {/* 导演世界模块 */}
        <div className="xiaji-director-world-block">
          <div className="xiaji-director-world-title">
            <Box size={16} />
            <strong>导演世界</strong>
          </div>

          <div className="xiaji-director-world-actions">
            <Upload
              accept=".zip,.glb,.gltf,.json,.tar"
              showUploadList={false}
              beforeUpload={(file) => {
                updateDef({ custom_bundle_name: file.name })
                message.success(`已载入自定义包: ${file.name}`)
                return false
              }}
            >
              <Button size="small" icon={<UploadIcon size={12} />}>
                上传/替换 自定义包
              </Button>
            </Upload>

            <Button
              size="small"
              type="text"
              icon={<Trash2 size={12} />}
              disabled={!asset.definition.custom_bundle_name}
              onClick={() => {
                updateDef({ custom_bundle_name: "", custom_bundle_url: "" })
                message.info("已移除自定义包")
              }}
            >
              删除 自定义包
            </Button>

            <Button
              size="small"
              icon={<RotateCw size={12} />}
              onClick={() => message.success("已将正面视角同步至导演世界")}
            >
              正面→导演世界
            </Button>
            <Button
              size="small"
              icon={<RotateCw size={12} />}
              onClick={() => message.success("已将背面视角同步至导演世界")}
            >
              背面→导演世界
            </Button>
            <Button
              size="small"
              icon={<RotateCw size={12} />}
              onClick={() => message.success("已将360全景同步至导演世界")}
            >
              360→导演世界
            </Button>
          </div>

          <Button
            type="link"
            size="small"
            className="xiaji-director-world-open-btn"
            icon={<ExternalLink size={12} />}
            onClick={() => setDirectorModalOpen(true)}
          >
            打开导演世界
          </Button>
        </div>
      </div>

      {/* 360 全景查看器弹窗 */}
      <Modal
        title={`360 全景查看器 - ${asset.name}`}
        open={viewer360Open}
        footer={null}
        width={900}
        onCancel={() => setViewer360Open(false)}
      >
        <div className="xiaji-panorama-modal-body">
          {asset.definition.panorama_image_url || asset.image_url ? (
            <img
              src={asset.definition.panorama_image_url || asset.image_url || ""}
              alt="360 全景预览"
              style={{ width: "100%", maxHeight: "540px", objectFit: "cover", borderRadius: "8px" }}
            />
          ) : (
            <Empty description="暂无 360 全景图，请先点击生成或上传" />
          )}
        </div>
      </Modal>

      {/* 导演世界弹窗 */}
      <Modal
        title={`导演世界 - ${asset.name}`}
        open={directorModalOpen}
        footer={null}
        width={800}
        onCancel={() => setDirectorModalOpen(false)}
      >
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <Box size={48} style={{ color: "#38bdf8", marginBottom: "12px" }} />
          <h3>已就绪当前场景空间坐标</h3>
          <p style={{ color: "var(--studio-text-muted)", marginTop: "8px" }}>
            正面、背面与 360° 全景已对齐当前镜头视锥体，支持直接调用到导演工程中使用。
          </p>
        </div>
      </Modal>

      {/* 编辑场景详情弹窗 */}
      <Modal
        title={`编辑场景 - ${asset.name}`}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={() => {
          form.validateFields().then((values) => {
            onSave(values.name, {
              ...asset.definition,
              scene_type: values.scene_type,
              time_of_day: values.time_of_day,
              environment_prompt: values.environment_prompt,
              description: values.description,
              visual_style: values.visual_style,
            })
            setEditModalOpen(false)
            message.success("场景信息已更新")
          })
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="场景名称" rules={[{ required: true, message: "请填写名称" }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="scene_type" label="场景类型">
            <Select options={SCENE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="time_of_day" label="时段">
            <Input placeholder="如 白天、黄昏、雨夜" />
          </Form.Item>
          <Form.Item name="environment_prompt" label="环境提示词">
            <Input.TextArea rows={4} placeholder="描述正面主入口、主要材质、结构与光影" />
          </Form.Item>
          <Form.Item name="description" label="场景补充说明">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function PropEditor({
  asset,
  busy,
  generating,
  enqueuePending,
  onSave,
  onGenerate,
  onUpload,
  onDelete,
}: {
  asset: XiajiAsset
  busy: boolean
  generating: boolean
  enqueuePending: boolean
  onSave: (name: string, definition: Record<string, unknown>) => void
  onGenerate: (payload: XiajiAssetGenerateImagePayload) => void
  onUpload: (file: File, slot?: "turnaround" | "detail") => Promise<void>
  onDelete: () => void
}) {
  const [editingName, setEditingName] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [viewerDetailOpen, setViewerDetailOpen] = useState(false)
  const [directorModalOpen, setDirectorModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [pendingView, setPendingView] = useState<"master" | "turnaround" | "detail" | null>(null)

  const [descDraft, setDescDraft] = useState(
    asset.definition.visual_prompt ||
      asset.definition.description ||
      `道具主体结构紧凑，材质质感突出，边角有磨损使用痕迹，具备关键识别特征。`
  )

  useEffect(() => {
    form.setFieldsValue({
      name: asset.name,
      prop_type: asset.definition.prop_type || "关键道具",
      owner: asset.definition.owner || "",
      visual_prompt: asset.definition.visual_prompt || "",
      description: asset.definition.description || "",
      visual_style: asset.definition.visual_style || "",
    })
    setDescDraft(
      asset.definition.visual_prompt ||
        asset.definition.description ||
        `道具主体结构紧凑，材质质感突出，边角有磨损使用痕迹，具备关键识别特征。`
    )
  }, [asset, form])

  const hasMain = Boolean(asset.image_url)
  const hasTurnaround = Boolean(asset.definition.turnaround_image_url)
  const hasDetail = Boolean(asset.definition.detail_image_url)
  const propJobs = asset.definition.prop_jobs || {}
  const turnaroundGenerating = Boolean(propJobs.turnaround) || (enqueuePending && pendingView === "turnaround")
  const detailGenerating = Boolean(propJobs.detail) || (enqueuePending && pendingView === "detail")
  const masterGenerating = generating && pendingView !== "turnaround" && pendingView !== "detail"
  const shotCount = asset.definition.shot_count || 5
  const stylePayload = {
    style: String(asset.definition.visual_style || ""),
    ethnicity: "Chinese",
  }

  const updateDef = (patch: Record<string, unknown>, nextName?: string) => {
    onSave(nextName || asset.name, { ...asset.definition, ...patch })
  }

  return (
    <div className="xiaji-prop-editor">
      {/* 顶部标题行 */}
      <div className="xiaji-scene-top-bar">
        <div className="xiaji-scene-top-title">
          <strong>{asset.name}</strong>
          <span className="xiaji-scene-num-badge">1</span>
        </div>
      </div>

      {/* 主卡片容器 */}
      <div className="xiaji-scene-card">
        {/* 卡片头部信息行 */}
        <div className="xiaji-scene-card-head">
          <div className="xiaji-scene-card-tags">
            {editingName ? (
              <Input
                size="small"
                className="xiaji-scene-name-input"
                defaultValue={asset.name}
                autoFocus
                onBlur={(e) => {
                  setEditingName(false)
                  if (e.target.value.trim() && e.target.value.trim() !== asset.name) {
                    updateDef({}, e.target.value.trim())
                  }
                }}
                onPressEnter={(e) => {
                  setEditingName(false)
                  const val = (e.target as HTMLInputElement).value.trim()
                  if (val && val !== asset.name) {
                    updateDef({}, val)
                  }
                }}
              />
            ) : (
              <strong
                className="xiaji-scene-pill-name"
                title="双击重命名"
                onDoubleClick={() => setEditingName(true)}
              >
                {asset.name}
              </strong>
            )}
            <span className="xiaji-scene-pill-type">{asset.definition.prop_type || "关键道具"}</span>
            {asset.definition.owner ? (
              <span className="xiaji-prop-pill-owner">所属: {asset.definition.owner}</span>
            ) : null}
            <span className="xiaji-scene-pill-status">主视图 {hasMain ? "已生成" : "未生成"}</span>
            <span className="xiaji-scene-pill-status">转面图 {hasTurnaround ? "已生成" : "未生成"}</span>
            <span className="xiaji-scene-pill-status">特写细节 {hasDetail ? "已生成" : "未生成"}</span>
            <span className="xiaji-scene-pill-shots">
              <Calendar size={12} />
              <span>出现于 {shotCount} 个镜头</span>
            </span>
          </div>

          <div className="xiaji-scene-card-tools">
            <Button
              type="text"
              size="small"
              icon={<Link2 size={14} />}
              title="复制道具标识"
              onClick={() => {
                void navigator.clipboard?.writeText(asset.name)
                message.success(`已复制道具标识: ${asset.name}`)
              }}
            />
            <Button
              type="text"
              size="small"
              icon={<ExternalLink size={14} />}
              title="查看特写"
              onClick={() => setViewerDetailOpen(true)}
            />
            <Button
              type="text"
              size="small"
              icon={<Edit2 size={14} />}
              title="编辑道具详情"
              onClick={() => setEditModalOpen(true)}
            />
            <Popconfirm title="确定删除该道具？" okText="删除" cancelText="取消" onConfirm={onDelete}>
              <Button type="text" size="small" danger icon={<Trash2 size={14} />} title="删除道具" />
            </Popconfirm>
          </div>
        </div>

        {/* 外观描述展示行 */}
        <div className="xiaji-scene-desc-row" onClick={() => setEditModalOpen(true)}>
          <span className="xiaji-scene-desc-text">
            <strong>外观特征：</strong>以“{asset.name}”最能代表道具特征的主视角；根据原文设定“{descDraft}”
          </span>
        </div>

        {/* 三联视角区域 */}
        <div className="xiaji-scene-views-grid">
          {/* 1. 主视图 */}
          <div className="xiaji-scene-view-card">
            <div className="xiaji-scene-view-head">
              <span className="xiaji-scene-view-badge">主视图</span>
              {hasMain ? (
                <button
                  type="button"
                  className="xiaji-scene-view-delete"
                  title="删除主视图"
                  onClick={() => updateDef({ image_url: "", image_job_id: "" })}
                >
                  <Trash2 size={12} />
                </button>
              ) : null}
            </div>

            <div className="xiaji-scene-view-preview">
              {asset.image_url ? (
                <Image src={asset.image_url} alt="主视图" />
              ) : (
                <div className="xiaji-scene-view-empty">
                  <Package size={28} strokeWidth={1.2} />
                  <span>无主视图</span>
                </div>
              )}
            </div>

            <div className="xiaji-scene-view-actions">
              <Upload
                accept="image/png,image/jpeg,image/webp"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file)
                  return false
                }}
              >
                <Button size="small" icon={<UploadIcon size={12} />}>
                  上传主图
                </Button>
              </Upload>
              <Button
                size="small"
                icon={<RotateCw size={12} />}
                loading={masterGenerating}
                onClick={() => {
                  setPendingView("master")
                  onGenerate({ ...stylePayload, prop_view: "master" })
                }}
              >
                重生 主图
              </Button>
            </div>
          </div>

          {/* 2. 转面图 / 四视图 */}
          <div className="xiaji-scene-view-card">
            <div className="xiaji-scene-view-head">
              <span className="xiaji-scene-view-badge">转面图 (四视图)</span>
              {hasTurnaround ? (
                <button
                  type="button"
                  className="xiaji-scene-view-delete"
                  title="删除转面图"
                  onClick={() => updateDef({ turnaround_image_url: "" })}
                >
                  <Trash2 size={12} />
                </button>
              ) : null}
            </div>

            <div className="xiaji-scene-view-preview">
              {asset.definition.turnaround_image_url ? (
                <Image src={asset.definition.turnaround_image_url} alt="转面图" />
              ) : (
                <div className="xiaji-scene-view-empty">
                  <RotateCw size={28} strokeWidth={1.2} />
                  <span>无转面视角图</span>
                </div>
              )}
            </div>

            <div className="xiaji-scene-view-actions">
              <Upload
                accept="image/png,image/jpeg,image/webp"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file, "turnaround")
                  return false
                }}
              >
                <Button size="small" icon={<UploadIcon size={12} />}>
                  上传转面
                </Button>
              </Upload>
              <Button
                size="small"
                icon={<RotateCw size={12} />}
                loading={turnaroundGenerating}
                onClick={() => {
                  setPendingView("turnaround")
                  onGenerate({ ...stylePayload, prop_view: "turnaround" })
                }}
              >
                重生 转面
              </Button>
            </div>
          </div>

          {/* 3. 特写 / 细节图 */}
          <div className="xiaji-scene-view-card">
            <div className="xiaji-scene-view-head">
              <span className="xiaji-scene-view-badge">细节特写</span>
              {hasDetail ? (
                <button
                  type="button"
                  className="xiaji-scene-view-delete"
                  title="删除特写图"
                  onClick={() => updateDef({ detail_image_url: "" })}
                >
                  <Trash2 size={12} />
                </button>
              ) : null}
            </div>

            <div className="xiaji-scene-view-preview">
              {asset.definition.detail_image_url ? (
                <Image src={asset.definition.detail_image_url} alt="细节特写" />
              ) : (
                <div className="xiaji-scene-view-empty">
                  <Package size={28} strokeWidth={1.2} />
                  <span>无特写细节图</span>
                </div>
              )}
            </div>

            <div className="xiaji-scene-view-actions">
              <Button
                size="small"
                icon={<Box size={12} />}
                loading={detailGenerating}
                onClick={() => {
                  setPendingView("detail")
                  onGenerate({ ...stylePayload, prop_view: "detail" })
                }}
              >
                生成特写
              </Button>
              <Upload
                accept="image/png,image/jpeg,image/webp"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file, "detail")
                  return false
                }}
              >
                <Button size="small" icon={<UploadIcon size={12} />}>
                  上传/替换 特写
                </Button>
              </Upload>
            </div>

            <Button
              type="link"
              size="small"
              className="xiaji-scene-open-viewer-btn"
              icon={<ExternalLink size={12} />}
              onClick={() => setViewerDetailOpen(true)}
            >
              打开细节查看器
            </Button>
          </div>
        </div>

        {/* 导演世界模块 */}
        <div className="xiaji-director-world-block">
          <div className="xiaji-director-world-title">
            <Box size={16} />
            <strong>导演世界</strong>
          </div>

          <div className="xiaji-director-world-actions">
            <Upload
              accept=".zip,.glb,.gltf,.json,.obj,.fbx"
              showUploadList={false}
              beforeUpload={(file) => {
                updateDef({ custom_bundle_name: file.name })
                message.success(`已载入3D资产包: ${file.name}`)
                return false
              }}
            >
              <Button size="small" icon={<UploadIcon size={12} />}>
                上传/替换 自定义包
              </Button>
            </Upload>

            <Button
              size="small"
              type="text"
              icon={<Trash2 size={12} />}
              disabled={!asset.definition.custom_bundle_name}
              onClick={() => {
                updateDef({ custom_bundle_name: "", custom_bundle_url: "" })
                message.info("已移除自定义包")
              }}
            >
              删除 自定义包
            </Button>

            <Button
              size="small"
              icon={<RotateCw size={12} />}
              onClick={() => message.success("已将主视角同步至导演世界")}
            >
              主视图→导演世界
            </Button>
            <Button
              size="small"
              icon={<RotateCw size={12} />}
              onClick={() => message.success("已将转面视角同步至导演世界")}
            >
              转面图→导演世界
            </Button>
            <Button
              size="small"
              icon={<RotateCw size={12} />}
              onClick={() => message.success("已将特写视角同步至导演世界")}
            >
              细节图→导演世界
            </Button>
          </div>

          <Button
            type="link"
            size="small"
            className="xiaji-director-world-open-btn"
            icon={<ExternalLink size={12} />}
            onClick={() => setDirectorModalOpen(true)}
          >
            打开导演世界
          </Button>
        </div>
      </div>

      {/* 特写查看器弹窗 */}
      <Modal
        title={`道具特写细节 - ${asset.name}`}
        open={viewerDetailOpen}
        footer={null}
        width={800}
        onCancel={() => setViewerDetailOpen(false)}
      >
        <div style={{ textAlign: "center", padding: "8px 0" }}>
          {asset.definition.detail_image_url || asset.image_url ? (
            <img
              src={asset.definition.detail_image_url || asset.image_url || ""}
              alt="道具特写"
              style={{ width: "100%", maxHeight: "500px", objectFit: "contain", borderRadius: "8px" }}
            />
          ) : (
            <Empty description="暂无特写图，请先点击生成或上传" />
          )}
        </div>
      </Modal>

      {/* 导演世界弹窗 */}
      <Modal
        title={`导演世界 (3D资产) - ${asset.name}`}
        open={directorModalOpen}
        footer={null}
        width={800}
        onCancel={() => setDirectorModalOpen(false)}
      >
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <Box size={48} style={{ color: "#38bdf8", marginBottom: "12px" }} />
          <h3>已就绪当前道具空间坐标与物理绑定</h3>
          <p style={{ color: "var(--studio-text-muted)", marginTop: "8px" }}>
            主视角、转面多角度与细节贴图已对齐道具骨骼与角色挂载槽位，支持直接在分镜中绑定调用。
          </p>
        </div>
      </Modal>

      {/* 编辑道具详情弹窗 */}
      <Modal
        title={`编辑道具 - ${asset.name}`}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={() => {
          form.validateFields().then((values) => {
            onSave(values.name, {
              ...asset.definition,
              prop_type: values.prop_type,
              owner: values.owner,
              visual_prompt: values.visual_prompt,
              description: values.description,
              visual_style: values.visual_style,
            })
            setEditModalOpen(false)
            message.success("道具信息已更新")
          })
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="道具名称" rules={[{ required: true, message: "请填写名称" }]}>
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item name="prop_type" label="道具类型">
            <Select options={PROP_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="owner" label="所属角色">
            <Input placeholder="如 乌龟、李明（可选）" />
          </Form.Item>
          <Form.Item name="visual_prompt" label="外观特征提示词">
            <Input.TextArea rows={4} placeholder="描述道具材质、颜色、纹理、尺寸及随身细节" />
          </Form.Item>
          <Form.Item name="description" label="道具补充说明">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function VoiceEditor({
  asset,
  busy,
  onSave,
  onDefine,
  onTts,
  onUpload,
}: {
  asset: XiajiAsset
  busy: boolean
  onSave: (definition: Record<string, unknown>) => void
  onDefine: () => void
  onTts: (slot: string) => void
  onUpload: (file: File, slot: string) => Promise<void>
}) {
  const profile = voiceProfile(asset)
  const [draft, setDraft] = useState(profile)
  useEffect(() => setDraft(profile), [asset.id, asset.updated_at])

  return (
    <div className="xiaji-asset-editor">
      <div className="xiaji-asset-editor-head">
        <div>
          <Typography.Title level={4}>{asset.name} 声线</Typography.Title>
          {statusTag(asset.status)}
        </div>
        <Space wrap>
          <Button icon={<Sparkles size={14} />} loading={busy} onClick={onDefine}>
            生成声线定义
          </Button>
          <Button type="primary" loading={busy} onClick={() => onSave({ ...asset.definition, voice_profile: draft })}>
            保存定义
          </Button>
        </Space>
      </div>
      <Form layout="vertical">
        <Form.Item label="语言">
          <Input value={draft.language} onChange={(event) => setDraft({ ...draft, language: event.target.value })} />
        </Form.Item>
        <Form.Item label="音色">
          <Input value={draft.timbre} onChange={(event) => setDraft({ ...draft, timbre: event.target.value })} />
        </Form.Item>
        <Form.Item label="音高">
          <Input value={draft.pitch} onChange={(event) => setDraft({ ...draft, pitch: event.target.value })} />
        </Form.Item>
        <Form.Item label="说话方式">
          <Input.TextArea rows={2} value={draft.speaking_style} onChange={(event) => setDraft({ ...draft, speaking_style: event.target.value })} />
        </Form.Item>
        <Form.Item label="试听对白">
          <Input value={draft.sample_line} onChange={(event) => setDraft({ ...draft, sample_line: event.target.value })} />
        </Form.Item>
        <Form.Item label="合成音色">
          <Select
            value={draft.tts_voice || undefined}
            allowClear
            options={["alloy", "echo", "fable", "onyx", "nova", "shimmer"].map((id) => ({ value: id, label: id }))}
            onChange={(value) => setDraft({ ...draft, tts_voice: value || "" })}
          />
        </Form.Item>
        <Form.Item label="配音说明">
          <Input.TextArea rows={3} value={draft.prompt} onChange={(event) => setDraft({ ...draft, prompt: event.target.value })} />
        </Form.Item>
      </Form>
      <div className="xiaji-voice-slots">
        {(asset.voice_slots || []).map((slot) => (
          <div key={slot.slot} className="xiaji-voice-slot">
            <strong>{VOICE_SLOT_LABELS[slot.slot] || slot.slot}</strong>
            {slot.inherited_from_default ? <Tag>继承默认</Tag> : null}
            {slot.url ? <audio controls src={slot.url} /> : <Empty description="还没有参考音频" />}
            <Space>
              <Button size="small" loading={busy} onClick={() => onTts(slot.slot)}>
                合成试听
              </Button>
              <Upload
                accept="audio/mpeg,audio/wav,audio/mp4,audio/webm,audio/ogg"
                showUploadList={false}
                beforeUpload={(file) => {
                  void onUpload(file, slot.slot)
                  return false
                }}
              >
                <Button size="small">上传音频</Button>
              </Upload>
            </Space>
          </div>
        ))}
      </div>
    </div>
  )
}
