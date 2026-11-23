import { useCallback, useEffect, useRef, useState } from "react"
import { message } from "antd"
import { ApiRequestError } from "../api"
import { readEdit, readExport, saveEdit, uploadMedia, exportMp4, type ExportJob } from "./api"
import {
  blankDocument,
  duplicateClip,
  endOf,
  frame,
  laneClips,
  makeClip,
  moveClip,
  parseDocument,
  patchClip,
  splitClip,
  type EditAsset,
  type EditClip,
  type EditDocument,
  type EditTrack,
} from "./model"
import { editorSessionKey, isEditSessionActive } from "./editing-shared"

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试"

/**
 * 剪辑文档状态机：迷你时间线节点与全屏编辑器共用。
 *
 * 与 SmartEditPane 页面同一条后端契约（revision 乐观锁 + 409 冲突 + 浏览器草稿恢复），
 * 但不带分集切换、助手桥与素材面板 —— 面板由宿主变体自己渲染。
 */
export function useEditDocument(options: {
  csrfToken: string
  scopeProjectId: string
  sequence: string
  /** 有全屏写入者时暂停自动保存（迷你节点传 true）。 */
  deferWhileBusySession?: boolean
}) {
  const { csrfToken, scopeProjectId, sequence, deferWhileBusySession = false } = options
  const [doc, setDoc] = useState<EditDocument>(blankDocument)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [saveState, setSaveState] = useState("已保存")
  const [saveError, setSaveError] = useState("")
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [selected, setSelected] = useState("")
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({})
  const [uploading, setUploading] = useState(false)
  const [job, setJob] = useState<ExportJob | null>(null)
  const [jobError, setJobError] = useState("")
  const docRef = useRef(doc)
  docRef.current = doc
  const revision = useRef(0)
  const dirty = useRef(false)
  const ready = useRef(false)
  const conflict = useRef(false)
  const mounted = useRef(true)
  const saving = useRef<Promise<void> | null>(null)
  const recoveryKey = useRef("")
  const history = useRef({
    past: [] as EditDocument[],
    future: [] as EditDocument[]
  })
  const sessionKey = editorSessionKey(scopeProjectId, sequence)
  const sessionActive = useRef(false)
  sessionActive.current = deferWhileBusySession && isEditSessionActive(sessionKey)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const saveLatest = useCallback(async () => {
    if (saving.current) return saving.current
    if (!ready.current || !dirty.current || conflict.current) return
    if (sessionActive.current) return
    const run = async () => {
      while (dirty.current && !conflict.current) {
        if (sessionActive.current) break
        const snapshot = docRef.current
        if (mounted.current) setSaveState("保存中…")
        try {
          const response = await saveEdit(csrfToken, scopeProjectId, sequence, revision.current, snapshot)
          revision.current = response.revision
          dirty.current = docRef.current !== snapshot
          if (dirty.current) {
            try {
              sessionStorage.setItem(recoveryKey.current, JSON.stringify({ revision: revision.current, document: docRef.current }))
            } catch {
              /* cloud save still works */
            }
          } else sessionStorage.removeItem(recoveryKey.current)
          if (mounted.current) setSaveState(dirty.current ? "待保存" : "已保存")
        } catch (error) {
          if (error instanceof ApiRequestError && error.status === 409) conflict.current = true
          if (mounted.current) {
            setSaveState("保存失败")
            setSaveError(errorText(error))
          }
          throw error
        }
      }
    }
    saving.current = run().finally(() => {
      saving.current = null
    })
    return saving.current
  }, [csrfToken, scopeProjectId, sequence])

  const commit = useCallback(
    (change: EditDocument | ((current: EditDocument) => EditDocument), record = true) => {
      if (!ready.current || conflict.current) return
      try {
        const previous = docRef.current
        const next = typeof change === "function" ? change(previous) : change
        if (next === previous) return
        if (next.clips.length > 200 || next.assets.length > 300 || endOf(next) > 1800)
          throw new Error("单个工程最多 300 个素材、200 个片段、30 分钟")
        if (record) {
          history.current.past = [...history.current.past.slice(-59), previous]
          history.current.future = []
          setPlaying(false)
        }
        docRef.current = next
        dirty.current = true
        setDoc(next)
        setSaveState("待保存")
        try {
          sessionStorage.setItem(recoveryKey.current, JSON.stringify({ revision: revision.current, document: next }))
        } catch {
          /* save failure is shown separately */
        }
      } catch (error) {
        message.warning(errorText(error))
      }
    },
    []
  )

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError("")
    ready.current = false
    try {
      const snapshot = await readEdit(scopeProjectId, sequence)
      if (!mounted.current) return
      let document = snapshot.document
      recoveryKey.current = `zly-edit-recovery:${snapshot.draft_key}`
      try {
        const local = JSON.parse(sessionStorage.getItem(recoveryKey.current) || "null")
        if (local?.document) {
          const parsed = parseDocument(JSON.stringify(local.document))
          if (local.revision === snapshot.revision) {
            document = parsed
            dirty.current = true
            message.info("已恢复尚未保存的浏览器草稿")
          }
        }
      } catch {
        /* ignore invalid local recovery, preserve remote version */
      }
      revision.current = snapshot.revision
      docRef.current = document
      setDoc(document)
      ready.current = true
      conflict.current = false
      setSaveError("")
      history.current = { past: [], future: [] }
      setSaveState(dirty.current ? "待保存" : "已保存")
      setSelected("")
      setTime(0)
    } catch (error) {
      if (mounted.current) setLoadError(errorText(error))
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [scopeProjectId, sequence])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (loading || !dirty.current || conflict.current) return
    const timer = window.setTimeout(() => {
      void saveLatest().catch(() => undefined)
    }, 700)
    return () => window.clearTimeout(timer)
  }, [doc, loading, saveLatest])

  // 卸载时冲刷未保存修改；迷你节点关闭/画布卸载都不丢最后一次编辑。
  useEffect(
    () => () => {
      void saveLatest().catch(() => undefined)
    },
    [saveLatest]
  )

  useEffect(() => {
    if (!playing) return
    const start = performance.now()
    const initial = time
    const end = endOf(docRef.current)
    let animation = 0
    const step = (now: number) => {
      const next = Math.min(end, initial + (now - start) / 1000)
      setTime(next)
      if (next < end) animation = requestAnimationFrame(step)
      else setPlaying(false)
    }
    animation = requestAnimationFrame(step)
    return () => cancelAnimationFrame(animation)
    // Playback clock restarts only on transport actions, not on every displayed frame.
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return
    let cancelled = false
    let timer = 0
    const poll = async () => {
      try {
        const value = await readExport(scopeProjectId, job.id)
        if (cancelled) return
        setJob(value)
        setJobError("")
        if (["queued", "running"].includes(value.status))
          timer = window.setTimeout(poll, 2000)
      } catch (error) {
        if (!cancelled) {
          setJobError(errorText(error))
          timer = window.setTimeout(poll, 6000)
        }
      }
    }
    timer = window.setTimeout(poll, 1000)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [job?.id, job?.status, scopeProjectId])

  const seek = useCallback((next: number) => {
    setPlaying(false)
    setTime(next)
  }, [])

  const play = useCallback(
    (value: boolean) => {
      if (value && time >= endOf(docRef.current) - 0.001) setTime(0)
      setPlaying(value)
    },
    [time]
  )

  const undo = useCallback(
    (redo = false) => {
      const from = redo ? history.current.future : history.current.past
      const to = redo ? history.current.past : history.current.future
      const previous = from.pop()
      if (!previous) return
      to.push(docRef.current)
      commit(previous, false)
      setPlaying(false)
    },
    [commit]
  )

  const patch = useCallback(
    (values: Partial<EditClip>) => {
      commit((current) => patchClip(current, selected, values))
    },
    [commit, selected]
  )

  const split = useCallback(() => {
    const next = splitClip(docRef.current, selected, time)
    if (next === docRef.current) message.info("请先选中片段并把播放头移到片段内部")
    else commit(next)
  }, [commit, selected, time])

  const remove = useCallback(() => {
    commit((current) => ({
      ...current,
      clips: current.clips.filter((c) => c.id !== selected)
    }))
    setSelected("")
  }, [commit, selected])

  const add = useCallback(
    (asset: EditAsset, at?: number, track?: EditTrack) => {
      const current = docRef.current
      const lane = track || (asset.kind === "audio" ? "audio" : undefined)
      const clip = makeClip(
        current,
        asset,
        at ??
          (lane === "audio" || lane === "music"
            ? time
            : Math.max(0, ...laneClips(current, "video").map((c) => c.start + c.duration))),
        lane
      )
      commit({
        ...current,
        assets: current.assets.some((item) => item.id === asset.id)
          ? current.assets
          : [...current.assets, asset],
        clips: [...current.clips, clip]
      })
      setSelected(clip.id)
      seek(clip.start)
    },
    [commit, seek, time]
  )

  const dragClip = useCallback(
    (id: string, kind: "move" | "left" | "right", delta: number, snap: boolean) => {
      commit((current) => {
        const clip = current.clips.find((c) => c.id === id)
        if (!clip) return current
        const offset = frame(Math.abs(delta), current.settings.fps) * Math.sign(delta)
        if (kind === "move") return moveClip(current, id, clip.start + offset, snap)
        if (kind === "right") return patchClip(current, id, { duration: clip.duration + offset })
        const start = Math.max(0, clip.start + offset)
        const change = start - clip.start
        const inPoint = clip.in_point + change * clip.speed
        if (inPoint < 0 || clip.duration - change < 1 / current.settings.fps)
          throw new Error("不能裁切到原始素材范围之外")
        return patchClip(current, id, { start, duration: clip.duration - change, in_point: inPoint })
      })
    },
    [commit]
  )

  const probeAsset = useCallback(
    (id: string, duration: number) => {
      const current = docRef.current
      const asset = current.assets.find((a) => a.id === id)
      if (!asset || !Number.isFinite(duration) || Math.abs(asset.duration - duration) < 0.01 || duration < 1 / current.settings.fps)
        return
      const fps = current.settings.fps
      commit(
        {
          ...current,
          assets: current.assets.map((a) => (a.id === id ? { ...a, duration } : a)),
          clips: current.clips.flatMap((c) => {
            if (c.asset_id !== id) return [c]
            const available = Math.floor(((duration - c.in_point) / c.speed) * fps) / fps
            if (available < 1 / fps) return []
            const length = Math.min(c.duration, available)
            return [
              {
                ...c,
                duration: length,
                fade_in: Math.min(c.fade_in, length / 2),
                fade_out: Math.min(c.fade_out, length / 2)
              }
            ]
          })
        },
        false
      )
    },
    [commit]
  )

  const importFiles = useCallback(
    async (files: File[]) => {
      setUploading(true)
      for (const file of files) {
        if (file.size > 512 * 1024 * 1024) {
          message.error(`${file.name} 超过 512 MB`)
          continue
        }
        try {
          const asset = await uploadMedia(csrfToken, scopeProjectId, sequence, file)
          if (mounted.current) commit((current) => ({ ...current, assets: [...current.assets, asset] }))
        } catch (error) {
          message.error(`${file.name}：${errorText(error)}`)
        }
      }
      if (mounted.current) setUploading(false)
    },
    [commit, csrfToken, scopeProjectId, sequence]
  )

  const copy = useCallback(() => {
    commit((current) => duplicateClip(current, selected))
  }, [commit, selected])

  const startExport = useCallback(
    async (quality: number) => {
      setJobError("")
      await saveLatest()
      const result = await exportMp4(csrfToken, scopeProjectId, docRef.current, quality)
      setJob(result)
      return result
    },
    [csrfToken, saveLatest, scopeProjectId]
  )

  return {
    doc,
    docRef,
    loading,
    loadError,
    saveState,
    saveError,
    conflict: () => conflict.current,
    reload: load,
    saveLatest,
    commit,
    time,
    playing,
    seek,
    play,
    selected,
    select: setSelected,
    canUndo: history.current.past.length > 0,
    canRedo: history.current.future.length > 0,
    undo,
    patch,
    split,
    remove,
    add,
    copy,
    dragClip,
    probeAsset,
    importFiles,
    uploading,
    thumbnails,
    captureThumbnail: (id: string, dataUrl: string) => setThumbnails((current) => ({ ...current, [id]: dataUrl })),
    job,
    jobError,
    startExport
  }
}

export type EditDocumentController = ReturnType<typeof useEditDocument>
