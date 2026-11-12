import { useQuery } from "@tanstack/react-query"
import { Empty, Modal, Spin, message } from "antd"
import { useEffect, useMemo, useState } from "react"
import { requestJson as api } from "../api"

type AssetOutput = {
  kind: "image" | "video"
  label: string
  delivery_status?: string
  download_url?: string | null
  cloud_url?: string | null
  path?: string | null
}

export type AssetJob = {
  id: string
  media_type: "image" | "video"
  status: string
  title?: string | null
  created_at?: string
  outputs: AssetOutput[]
  rounds?: {
    generation_items?: {
      id: string
      outputs: AssetOutput[]
    }[]
  }[]
}

export type AssetPickerItem = {
  id: string
  jobId: string
  url: string
  label: string
}

const MAX_PICKER_IMAGES = 48

export function collectImageOutputs(jobs: AssetJob[]): AssetPickerItem[] {
  const items: AssetPickerItem[] = []
  const seen = new Set<string>()
  for (const job of jobs) {
    const fromRounds = (job.rounds ?? []).flatMap((round) =>
      (round.generation_items ?? []).flatMap((item) => (item.outputs ?? []).map((output, index) => ({ output, index, itemId: item.id || "item" }))))
    // 任务顶层的 outputs 是最新一轮生成物的镜像；有轮次产物时只读轮次，避免同一张图出现两条下载路径。
    const direct = fromRounds.length ? [] : (job.outputs ?? []).map((output, index) => ({ output, index, itemId: "job" }))
    for (const entry of [...direct, ...fromRounds]) {
      const { output } = entry
      if (output.kind !== "image") continue
      const url = output.download_url ?? output.cloud_url
      if (!url) continue
      // 下载路径按来源不同而不同，按底层文件身份（path / cloud_url）去重更稳。
      const identity = output.path || output.cloud_url || url
      if (seen.has(identity)) continue
      seen.add(identity)
      items.push({
        id: `${job.id}:${entry.itemId}:${entry.index}`,
        jobId: job.id,
        url,
        label: job.title || output.label || "未命名图片",
      })
      if (items.length >= MAX_PICKER_IMAGES) return items
    }
  }
  return items
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "读取图片失败"
}

export default function AssetPickerModal({
  open, onClose, onPick,
}: {
  open: boolean
  onClose: () => void
  onPick: (file: File) => void
}) {
  const [fetchingId, setFetchingId] = useState<string | null>(null)
  const jobsQuery = useQuery({
    queryKey: ["tools-asset-jobs"],
    queryFn: () => api<AssetJob[]>("/api/jobs"),
    enabled: open,
    staleTime: 15_000,
  })
  const images = useMemo(() => collectImageOutputs(jobsQuery.data ?? []), [jobsQuery.data])

  useEffect(() => {
    if (!open) setFetchingId(null)
  }, [open])

  const pick = async (item: AssetPickerItem) => {
    if (fetchingId) return
    setFetchingId(item.id)
    try {
      const response = await fetch(item.url)
      if (!response.ok) throw new Error(`读取失败（HTTP ${response.status}）`)
      const blob = await response.blob()
      const type = blob.type && blob.type.startsWith("image/") ? blob.type : "image/png"
      const extension = type === "image/jpeg" ? "jpg" : type.split("/")[1] || "png"
      onPick(new File([blob], `asset-${item.jobId.slice(0, 8)}.${extension}`, { type }))
      onClose()
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setFetchingId(null)
    }
  }

  return (
    <Modal
      open={open}
      title="从资产选取"
      width={760}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
    >
      {jobsQuery.isLoading ? (
        <div className="grid min-h-[220px] w-full place-items-center"><Spin tip="正在读取资产" /></div>
      ) : images.length === 0 ? (
        <div className="grid min-h-[220px] w-full place-items-center">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有可选取的图片资产，先生成一张或从本地上传" />
        </div>
      ) : (
        <div className="grid max-h-[56vh] grid-cols-2 gap-3 overflow-y-auto pb-1 sm:grid-cols-4">
          {images.map((item) => (
            <button
              key={item.id}
              type="button"
              disabled={fetchingId !== null}
              onClick={() => void pick(item)}
              className="group relative aspect-square overflow-hidden rounded-lg border border-[var(--studio-border)] bg-[var(--studio-surface-raised)] transition hover:border-[var(--studio-primary)] disabled:opacity-60"
              title={item.label}
            >
              <img src={item.url} alt={item.label} loading="lazy" className="h-full w-full object-cover" />
              <span className="absolute inset-x-0 bottom-0 truncate bg-[var(--studio-scrim)] px-2 py-1 text-[11px] text-white opacity-0 transition group-hover:opacity-100">{item.label}</span>
              {fetchingId === item.id ? <span className="absolute inset-0 grid place-items-center bg-[var(--studio-scrim)]"><Spin /></span> : null}
            </button>
          ))}
        </div>
      )}
    </Modal>
  )
}
