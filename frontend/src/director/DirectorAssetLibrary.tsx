import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Card, Empty, Input, Modal, Select, Space, Tabs, Tag, Typography, message } from "antd"
import { Library, Maximize2, Pencil, Plus, Search, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"
import {
  createDirectorLibraryAsset,
  deleteDirectorLibraryAsset,
  listDirectorLibraryAssets,
  updateDirectorLibraryAsset,
  uploadDirectorLibraryAssetImage,
} from "./director-api"
import { DIRECTOR_LIBRARY_KIND_LABELS, DirectorLibraryAsset, userFacingCopy } from "./types"
import MediaPreviewModal from "../components/MediaPreviewModal"

type LibraryKind = DirectorLibraryAsset["kind"]
type KindFilter = "all" | LibraryKind

const KIND_OPTIONS: Array<{ value: LibraryKind; label: string }> = [
  { value: "character", label: "人物" },
  { value: "scene", label: "场景" },
  { value: "prop", label: "道具" },
]

function notifyFailure(error: unknown, fallback: string) {
  message.error(error instanceof Error && error.message ? error.message : fallback)
}

export default function DirectorAssetLibrary({
  csrfToken,
  mode = "manage",
  onInsert,
}: {
  csrfToken: string
  mode?: "manage" | "picker"
  onInsert?: (assetIds: string[]) => Promise<void> | void
}) {
  const queryClient = useQueryClient()
  const [kindFilter, setKindFilter] = useState<KindFilter>("all")
  const [search, setSearch] = useState("")
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<DirectorLibraryAsset | null>(null)
  const [formKind, setFormKind] = useState<LibraryKind>("character")
  const [formName, setFormName] = useState("")
  const [formPrompt, setFormPrompt] = useState("")
  const [formFile, setFormFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [inserting, setInserting] = useState(false)
  const [previewingAsset, setPreviewingAsset] = useState<DirectorLibraryAsset | null>(null)

  const assetsQuery = useQuery({
    queryKey: ["director-library-assets"],
    queryFn: () => listDirectorLibraryAssets(),
  })
  const assets = assetsQuery.data || []

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return assets.filter((item) => {
      if (kindFilter !== "all" && item.kind !== kindFilter) return false
      if (!needle) return true
      const haystack = `${item.name} ${item.description} ${item.promptText}`.toLowerCase()
      return haystack.includes(needle)
    })
  }, [assets, kindFilter, search])

  function openCreate() {
    setEditing(null)
    setFormKind(kindFilter === "all" ? "character" : kindFilter)
    setFormName("")
    setFormPrompt("")
    setFormFile(null)
    setEditorOpen(true)
  }

  function openEdit(asset: DirectorLibraryAsset) {
    setEditing(asset)
    setFormKind(asset.kind)
    setFormName(asset.name)
    setFormPrompt(userFacingCopy(asset.description, asset.promptText, asset.name))
    setFormFile(null)
    setEditorOpen(true)
  }

  async function handleSave() {
    const name = formName.trim()
    if (!name) {
      message.warning("请填写名称")
      return
    }
    setSaving(true)
    try {
      const saved = editing
        ? await updateDirectorLibraryAsset(editing.id, {
            kind: formKind,
            name,
            description: formPrompt,
            promptText: formPrompt,
          }, csrfToken)
        : await createDirectorLibraryAsset({
            kind: formKind,
            name,
            description: formPrompt,
            promptText: formPrompt,
          }, csrfToken)
      if (formFile) {
        await uploadDirectorLibraryAssetImage(saved.id, formFile, csrfToken)
      }
      await queryClient.invalidateQueries({ queryKey: ["director-library-assets"] })
      setEditorOpen(false)
      message.success(editing ? "已更新资产" : "已加入资产库")
    } catch (error) {
      notifyFailure(error, "保存资产失败")
    } finally {
      setSaving(false)
    }
  }

  function handleDelete(asset: DirectorLibraryAsset) {
    Modal.confirm({
      title: `删除「${asset.name}」？`,
      content: "只删除资产库条目，已插入到工程里的人物/场景不会跟着删。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        await deleteDirectorLibraryAsset(asset.id, csrfToken)
        setSelectedIds((current) => current.filter((id) => id !== asset.id))
        await queryClient.invalidateQueries({ queryKey: ["director-library-assets"] })
        message.success("已删除")
      },
    })
  }

  function toggleSelect(assetId: string) {
    setSelectedIds((current) => (
      current.includes(assetId) ? current.filter((id) => id !== assetId) : [...current, assetId]
    ))
  }

  async function handleInsert() {
    if (!onInsert || !selectedIds.length) return
    setInserting(true)
    try {
      await onInsert(selectedIds)
      setSelectedIds([])
    } catch (error) {
      notifyFailure(error, "插入失败")
    } finally {
      setInserting(false)
    }
  }

  return (
    <section className="director-library-panel" aria-label="人物场景道具资产库">
      <div className="director-library-toolbar">
        <Tabs
          className="director-library-tabs"
          activeKey={kindFilter}
          onChange={(key) => setKindFilter(key as KindFilter)}
          items={[
            { key: "all", label: "全部" },
            { key: "character", label: "人物" },
            { key: "scene", label: "场景" },
            { key: "prop", label: "道具" },
          ]}
        />
        <div className="director-library-actions">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            allowClear
            prefix={<Search size={15} />}
            placeholder="搜索名称或提示词"
            aria-label="搜索资产库"
          />
          <Button type="primary" icon={<Plus size={14} />} onClick={openCreate}>新建</Button>
        </div>
      </div>
      <p className="director-library-hint">
        员工级资产库，可在不同导演工程里插入人物、场景和道具。继续用工程 + 分镜，不建系列分集。
      </p>
      {assetsQuery.isLoading ? (
        <div className="py-10 text-center text-sm text-[#6b7280]">正在加载资产库...</div>
      ) : visible.length ? (
        <div className="director-asset-grid director-library-grid">
          {visible.map((asset) => {
            const selected = selectedIds.includes(asset.id)
            return (
              <Card
                key={asset.id}
                size="small"
                className={`director-asset-card director-library-card ${selected ? "is-selected" : ""}`}
                cover={asset.imageUrl ? (
                  <button type="button" className="director-asset-preview-trigger" onClick={(event) => {
                    event.stopPropagation()
                    setPreviewingAsset(asset)
                  }} aria-label={`放大查看${asset.name}`}>
                    <img src={asset.imageUrl} alt={asset.name} className="director-asset-cover" />
                    <span><Maximize2 size={18} /> 放大查看</span>
                  </button>
                ) : (
                  <div className="director-asset-placeholder">暂无参考图</div>
                )}
                onClick={mode === "picker" ? () => toggleSelect(asset.id) : undefined}
              >
                <div className="director-library-card-meta">
                  <Typography.Text strong>{asset.name}</Typography.Text>
                  <Tag>{DIRECTOR_LIBRARY_KIND_LABELS[asset.kind]}</Tag>
                </div>
                <Typography.Paragraph ellipsis={{ rows: 2 }} className="director-library-prompt">
                  {userFacingCopy(asset.description, asset.promptText) || "未填写提示词"}
                </Typography.Paragraph>
                <Space wrap>
                  {mode === "picker" ? (
                    <Button size="small" type={selected ? "primary" : "default"} onClick={(event) => {
                      event.stopPropagation()
                      toggleSelect(asset.id)
                    }}>
                      {selected ? "已选" : "选择"}
                    </Button>
                  ) : null}
                  <Button size="small" onClick={(event) => {
                    event.stopPropagation()
                    openEdit(asset)
                  }}>
                    编辑
                  </Button>
                  <Button size="small" danger icon={<Trash2 size={12} />} onClick={(event) => {
                    event.stopPropagation()
                    handleDelete(asset)
                  }}>
                    删除
                  </Button>
                </Space>
              </Card>
            )
          })}
        </div>
      ) : (
        <Empty
          image={<Library size={28} />}
          description={assets.length ? "没有符合筛选的资产" : "还没有人物、场景或道具。可新建，或在导演工程定妆后点「存入资产库」。"}
        >
          <Button type="primary" onClick={openCreate}>新建资产</Button>
        </Empty>
      )}
      {mode === "picker" ? (
        <div className="director-library-picker-bar">
          <span>已选 {selectedIds.length} 项</span>
          <Button type="primary" disabled={!selectedIds.length} loading={inserting} onClick={() => void handleInsert()}>
            插入到本工程
          </Button>
        </div>
      ) : null}
      <Modal
        title={editing ? "编辑资产" : "新建资产"}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <div className="director-library-form">
          <label>
            类型
            <Select
              aria-label="资产类型"
              value={formKind}
              options={KIND_OPTIONS}
              onChange={(value: LibraryKind) => setFormKind(value)}
            />
          </label>
          <label>
            名称
            <Input value={formName} onChange={(event) => setFormName(event.target.value)} maxLength={80} />
          </label>
          <label>
            说明 / 提示词
            <Input.TextArea
              value={formPrompt}
              onChange={(event) => setFormPrompt(event.target.value)}
              autoSize={{ minRows: 3, maxRows: 6 }}
            />
          </label>
          <label>
            参考图
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setFormFile(event.target.files?.[0] || null)}
            />
          </label>
        </div>
      </Modal>
      {previewingAsset?.imageUrl ? <MediaPreviewModal
        open
        kind="image"
        src={previewingAsset.imageUrl}
        title={previewingAsset.name}
        description={userFacingCopy(previewingAsset.description, previewingAsset.promptText)}
        onClose={() => setPreviewingAsset(null)}
        actions={[
          ...(mode === "picker" ? [{ key: "select", label: selectedIds.includes(previewingAsset.id) ? "取消选择" : "选择此资产", type: selectedIds.includes(previewingAsset.id) ? "default" as const : "primary" as const, onClick: () => toggleSelect(previewingAsset.id) }] : []),
          { key: "edit", label: "编辑资产", icon: <Pencil size={15} />, onClick: () => { openEdit(previewingAsset); setPreviewingAsset(null) } },
          { key: "delete", label: "删除资产", icon: <Trash2 size={15} />, danger: true, onClick: () => { handleDelete(previewingAsset); setPreviewingAsset(null) } },
        ]}
      /> : null}
    </section>
  )
}
