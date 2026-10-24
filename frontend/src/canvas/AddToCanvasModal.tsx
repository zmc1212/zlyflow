import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Empty, Modal, Select, Spin, message } from "antd"
import { Frame, Plus } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { canvasProjectPath } from "../paths"
import { createCanvasProject, listCanvasProjects } from "./canvas-api"
import { canvasAssetInsertSearch, filterCanvasProjects } from "./canvas-manage"
import { formatCanvasTime } from "./canvas-model"

export type CanvasInsertAsset = {
  jobId: string
  generationItemId?: string | null
  outputIndex: number
  label?: string | null
}

type AddToCanvasModalProps = {
  open: boolean
  csrfToken: string
  asset: CanvasInsertAsset | null
  onClose: () => void
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "操作失败"
}

function defaultCanvasTitle(asset: CanvasInsertAsset | null): string {
  const label = asset?.label?.trim()
  return (label ? `${label} 画布` : "素材画布").slice(0, 120)
}

export default function AddToCanvasModal({ open, csrfToken, asset, onClose }: AddToCanvasModalProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string>()
  const [creating, setCreating] = useState(false)
  const projectsQuery = useQuery({
    queryKey: ["canvas-projects"],
    queryFn: () => listCanvasProjects(),
    enabled: open,
    staleTime: 15_000,
  })
  const projects = useMemo(
    () => filterCanvasProjects(projectsQuery.data ?? [], "", "updated_desc"),
    [projectsQuery.data],
  )
  const options = useMemo(
    () => projects.map((project) => ({ value: project.id, label: project.title })),
    [projects],
  )
  const selectedProject = projects.find((project) => project.id === selectedId)

  useEffect(() => {
    if (!open) return
    setSelectedId(undefined)
  }, [open, asset?.jobId, asset?.generationItemId, asset?.outputIndex])

  const openCanvas = (projectId: string) => {
    if (!asset) return
    const query = canvasAssetInsertSearch(asset)
    onClose()
    navigate(`${canvasProjectPath(projectId)}?${query}`)
  }

  const createAndOpen = async () => {
    if (!asset) return
    setCreating(true)
    try {
      const created = await createCanvasProject(csrfToken, defaultCanvasTitle(asset))
      await queryClient.invalidateQueries({ queryKey: ["canvas-projects"] })
      message.success("已新建画布")
      openCanvas(created.id)
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setCreating(false)
    }
  }

  return (
    <Modal
      open={open}
      title="加入画布"
      width={520}
      destroyOnHidden
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>取消</Button>,
        <Button key="create" icon={<Plus size={15} />} loading={creating} onClick={() => { void createAndOpen() }}>
          新建画布并加入
        </Button>,
        <Button key="insert" type="primary" disabled={!selectedId} onClick={() => selectedId && openCanvas(selectedId)}>
          加入画布
        </Button>,
      ]}
    >
      <p className="mb-3 text-sm text-[var(--studio-text-secondary)]">
        将{asset?.label ? `「${asset.label}」` : "这份素材"}加入已有画布，或新建一张画布。
      </p>
      {projectsQuery.isLoading ? (
        <div className="flex min-h-24 items-center justify-center gap-2 text-sm text-[var(--studio-text-muted)]">
          <Spin size="small" />正在加载画布…
        </div>
      ) : projectsQuery.isError ? (
        <Empty description={errorText(projectsQuery.error)} />
      ) : !projects.length ? (
        <Empty description="还没有画布，可直接新建一张" />
      ) : (
        <>
          <Select
            className="w-full"
            showSearch
            optionFilterProp="label"
            placeholder="选择目标画布"
            value={selectedId}
            onChange={(value) => setSelectedId(value)}
            options={options}
          />
          <p className="mt-2 flex items-center gap-1.5 text-xs text-[var(--studio-text-subtle)]">
            <Frame size={13} />
            {selectedProject
              ? `最近保存 ${formatCanvasTime(selectedProject.draft_updated_at ?? selectedProject.updated_at)}`
              : "加入后会在画布中央插入素材节点"}
          </p>
        </>
      )}
    </Modal>
  )
}
