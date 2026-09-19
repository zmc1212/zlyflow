import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Alert, Button, Input, Select, Slider, Space, Tag, Upload, message } from "antd"
import { Mic, RefreshCw, Volume2 } from "lucide-react"
import {
  generateEpisodeDubbing,
  getEpisodeDubbing,
  patchDubbingLine,
  syncEpisodeDubbing,
  uploadAssetVoice,
  applyAssetVoicePreset,
  listVoiceBank,
  director2ErrorDetail,
} from "../api"
import { director2ProjectPath } from "../paths"
import {
  INDEXTTS_EMOTIONS,
  MAX_VOICE_AUDIO_BYTES,
  VOICE_AUDIO_ACCEPT,
  isVoiceAudioFile,
} from "../voice-profile"
import { groupedVoicePresetOptions, type VoicePreset } from "../voice-bank"
import {
  formatLineDuration,
  isActiveDubbingStatus,
  lineEmotionLabel,
  lineKindLabel,
  lineMixLabel,
  lineStatusLabel,
  mixDirectorHint,
  speakerColor,
  type DubbingLine,
  type DubbingTrack,
} from "../dubbing-track"

interface DubbingWorkbenchProps {
  csrfToken: string
  projectId: string
  episodeId: string
}

export default function DubbingWorkbench({ csrfToken, projectId, episodeId }: DubbingWorkbenchProps) {
  const navigate = useNavigate()
  const [track, setTrack] = useState<DubbingTrack | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [uploadingId, setUploadingId] = useState<string | null>(null)
  const [presetVoices, setPresetVoices] = useState<VoicePreset[]>([])
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null)
  const [filterCharacterId, setFilterCharacterId] = useState<string | null>(null)
  const [playingSeq, setPlayingSeq] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const playIndexRef = useRef(0)

  const lines = track?.lines || []
  const visibleLines = useMemo(
    () => (filterCharacterId ? lines.filter((item) => item.character_id === filterCharacterId) : lines),
    [lines, filterCharacterId],
  )
  const selected = useMemo(
    () => visibleLines.find((item) => item.id === selectedLineId) || lines.find((item) => item.id === selectedLineId) || visibleLines[0] || lines[0] || null,
    [lines, visibleLines, selectedLineId],
  )
  const selectedVoice = useMemo(
    () => (track?.characters || []).find((item) => item.id === selected?.character_id) || null,
    [track, selected],
  )
  const busy = lines.some((item) => isActiveDubbingStatus(item.status))

  async function loadTrack() {
    setLoading(true)
    try {
      const next = await getEpisodeDubbing(projectId, episodeId)
      setTrack(next)
      setSelectedLineId((current) => (current && next.lines.some((item) => item.id === current) ? current : next.lines[0]?.id || null))
    } catch (err) {
      message.error(director2ErrorDetail(err, "读取台词轨失败"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadTrack()
    return () => stopPlayback()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, episodeId])

  useEffect(() => {
    void listVoiceBank()
      .then((payload) => setPresetVoices(payload.voices || []))
      .catch(() => setPresetVoices([]))
  }, [])

  useEffect(() => {
    if (!busy) return
    const timer = window.setInterval(() => {
      void getEpisodeDubbing(projectId, episodeId).then(setTrack).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [busy, projectId, episodeId])

  function stopPlayback() {
    setPlayingSeq(false)
    const player = audioRef.current
    if (player) {
      player.pause()
      player.removeAttribute("src")
    }
  }

  function playUrls(urls: string[], start = 0) {
    const player = audioRef.current
    if (!player || !urls.length) return
    playIndexRef.current = start
    const playAt = () => {
      const index = playIndexRef.current
      if (index >= urls.length) {
        setPlayingSeq(false)
        return
      }
      player.src = urls[index]
      void player.play().catch(() => setPlayingSeq(false))
    }
    player.onended = () => {
      playIndexRef.current += 1
      playAt()
    }
    setPlayingSeq(true)
    playAt()
  }

  async function handleSync() {
    setSyncing(true)
    try {
      const next = await syncEpisodeDubbing(csrfToken, projectId, episodeId)
      setTrack(next)
      message.success(`已从分镜同步 ${next.total} 句`)
    } catch (err) {
      message.error(director2ErrorDetail(err, "同步台词轨失败"))
    } finally {
      setSyncing(false)
    }
  }

  async function handleGenerate(lineIds?: string[]) {
    setGenerating(true)
    try {
      const result = await generateEpisodeDubbing(csrfToken, projectId, episodeId, lineIds?.length ? { line_ids: lineIds } : {})
      message.success(result.duplicate ? "已有相同配音任务在排队" : "配音任务已入队，可在「全部任务 → 配音」查看")
      const next = await getEpisodeDubbing(projectId, episodeId)
      setTrack(next)
    } catch (err) {
      message.error(director2ErrorDetail(err, "生成配音失败"))
    } finally {
      setGenerating(false)
    }
  }

  async function handlePatch(lineId: string, patch: Record<string, unknown>) {
    try {
      const next = await patchDubbingLine(csrfToken, projectId, episodeId, lineId, patch)
      setTrack(next)
    } catch (err) {
      message.error(director2ErrorDetail(err, "更新台词失败"))
    }
  }

  async function handleApplyPreset(characterId: string, presetId: string) {
    setUploadingId(characterId)
    try {
      await applyAssetVoicePreset(csrfToken, projectId, characterId, presetId)
      message.success("已绑定内置短剧声线")
      await loadTrack()
    } catch (err) {
      message.error(director2ErrorDetail(err, "绑定内置声线失败"))
    } finally {
      setUploadingId(null)
    }
  }

  async function handleUploadVoice(characterId: string, file: File) {
    setUploadingId(characterId)
    try {
      await uploadAssetVoice(csrfToken, projectId, characterId, file)
      message.success("已绑定参考音")
      await loadTrack()
    } catch (err) {
      message.error(director2ErrorDetail(err, "上传参考音失败"))
    } finally {
      setUploadingId(null)
    }
  }

  function statusColor(status: string) {
    if (status === "ready") return "success"
    if (status === "failed") return "error"
    if (status === "running" || status === "queued") return "processing"
    return "default"
  }

  function playLine(line: DubbingLine) {
    if (!line.audio_url) {
      message.warning("这句还没有音频")
      return
    }
    playUrls([line.audio_url])
  }

  function playReadySequence() {
    const urls = visibleLines.map((item) => item.audio_url).filter(Boolean)
    if (!urls.length) {
      message.warning("还没有已生成的配音")
      return
    }
    playUrls(urls)
  }

  return (
    <div className="xiaji-dubbing-workbench">
      <audio ref={audioRef} hidden />
      <div className="dubbing-toolbar">
        <div className="toolbar-left">
          <Mic size={15} />
          <strong>台词轨</strong>
          <em>{track ? `${track.ready}/${track.total} 已就绪` : loading ? "读取中…" : "—"}</em>
        </div>
        <Space wrap>
          <Button size="small" loading={syncing} icon={<RefreshCw size={13} />} onClick={() => void handleSync()}>
            从分镜同步
          </Button>
          <Button size="small" onClick={playingSeq ? stopPlayback : playReadySequence} icon={<Volume2 size={13} />}>
            {playingSeq ? "停止试听" : "连续试听"}
          </Button>
          <Button type="primary" size="small" loading={generating || busy} onClick={() => void handleGenerate()}>
            批量生成
          </Button>
        </Space>
      </div>

      {track && track.unbound_count ? (
        <Alert
          type="warning"
          showIcon
          className="dubbing-unbound-alert"
          message={`${track.unbound_count} 个角色还没有参考音`}
          description="可在左侧声线卡选用内置短剧声线或上传参考音。开口对白仍可降级系统音色；IndexTTS 克隆需要参考音。"
        />
      ) : null}

      <div className="xiaji-dubbing-grid">
        <aside className="dubbing-col dubbing-chars">
          <header>
            <h3>角色声线</h3>
            <em>{track?.characters.length || 0}</em>
          </header>
          <ul>
            {(track?.characters || []).map((item) => {
              const refUrl = item.voice?.ref_audio_url || item.voice?.preview_url || ""
              return (
                <li
                  key={item.id}
                  className={`${item.bound ? "is-bound" : "is-unbound"}${filterCharacterId === item.id ? " is-selected" : ""}`}
                  onClick={() => setFilterCharacterId((current) => (current === item.id ? null : item.id))}
                >
                  <span className="char-dot" style={{ background: speakerColor(item.name) }} />
                  <div className="char-body">
                    <strong>{item.name}</strong>
                    <em>{item.role || "角色"}</em>
                    <Tag color={item.bound ? "success" : "warning"}>{item.bound ? "已绑定参考音" : "未绑定"}</Tag>
                    {refUrl ? <audio src={refUrl} controls preload="metadata" onClick={(event) => event.stopPropagation()} /> : null}
                    <Space size={4} wrap onClick={(event) => event.stopPropagation()}>
                      <Select
                        placeholder="内置声线"
                        value={item.voice?.preset_id || undefined}
                        options={groupedVoicePresetOptions(presetVoices)}
                        onChange={(value) => { if (value) void handleApplyPreset(item.id, value) }}
                        loading={uploadingId === item.id}
                        showSearch
                        optionFilterProp="label"
                        size="small"
                        style={{ minWidth: 148 }}
                      />
                      <Upload
                        accept={VOICE_AUDIO_ACCEPT}
                        showUploadList={false}
                        beforeUpload={(file) => {
                          if (!isVoiceAudioFile(file)) {
                            message.warning("请上传 wav / mp3 / m4a / flac / ogg")
                            return Upload.LIST_IGNORE
                          }
                          if (file.size > MAX_VOICE_AUDIO_BYTES) {
                            message.warning("参考音不能超过 20 MB")
                            return Upload.LIST_IGNORE
                          }
                          void handleUploadVoice(item.id, file)
                          return false
                        }}
                      >
                        <Button size="small" loading={uploadingId === item.id}>{item.bound ? "更换" : "绑定参考音"}</Button>
                      </Upload>
                    </Space>
                  </div>
                </li>
              )
            })}
            {!track?.characters.length ? (
              <li className="empty-hint">
                本集还没有角色资产。
                <Button type="link" size="small" onClick={() => navigate(director2ProjectPath(projectId, "assets"))}>
                  去资产库
                </Button>
              </li>
            ) : null}
          </ul>
        </aside>

        <section className="dubbing-col dubbing-lines">
          <header>
            <h3>对白</h3>
            <em>{filterCharacterId ? `已筛选 ${visibleLines.length} 句` : "B1…Bn"}</em>
          </header>
          <ol>
            {visibleLines.map((line) => (
              <li
                key={line.id}
                className={line.id === selected?.id ? "is-selected" : ""}
                onClick={() => setSelectedLineId(line.id)}
              >
                <span className="line-seq" style={{ background: speakerColor(line.speaker || "旁白") }}>{line.seq || "B"}</span>
                <div className="line-body">
                  <div className="line-meta">
                    <strong>{line.speaker || "旁白"}</strong>
                    <Tag>{lineKindLabel(line.kind)}</Tag>
                    <Tag color={statusColor(String(line.status))}>{lineStatusLabel(line.status)}</Tag>
                    <Tag>{lineMixLabel(line.mix)}</Tag>
                    <em>{formatLineDuration(line.duration_sec)}</em>
                  </div>
                  <p>{line.text}</p>
                  {line.audio_url ? (
                    <audio className="line-wave" src={line.audio_url} controls preload="metadata" onClick={(event) => event.stopPropagation()} />
                  ) : null}
                  {line.error ? <span className="line-error">{line.error}</span> : null}
                </div>
              </li>
            ))}
            {!visibleLines.length ? <li className="empty-hint">点「从分镜同步」按 Beat 开口/内心/旁白展开台词。</li> : null}
          </ol>
        </section>

        <aside className="dubbing-col dubbing-director">
          <header>
            <h3>配音导演</h3>
            <em>{selected?.seq || "未选"}</em>
          </header>
          {selected ? (
            <div className="director-form">
              <label>台词</label>
              <Input.TextArea
                rows={4}
                value={selected.text}
                onChange={(event) => {
                  const text = event.target.value
                  setTrack((prev) => (prev ? {
                    ...prev,
                    lines: prev.lines.map((item) => (item.id === selected.id ? { ...item, text } : item)),
                  } : prev))
                }}
                onBlur={(event) => void handlePatch(selected.id, { text: event.target.value })}
              />
              <label>情绪 · {lineEmotionLabel(selected.emotion)}</label>
              <Select
                value={selected.emotion}
                options={INDEXTTS_EMOTIONS.map((item) => ({ value: item.id, label: item.label }))}
                onChange={(value) => void handlePatch(selected.id, { emotion: value })}
              />
              <label>情绪强度 {Number(selected.emo_alpha).toFixed(2)}</label>
              <Slider
                min={0}
                max={1}
                step={0.05}
                value={Number(selected.emo_alpha)}
                onChange={(value) => {
                  setTrack((prev) => (prev ? {
                    ...prev,
                    lines: prev.lines.map((item) => (item.id === selected.id ? { ...item, emo_alpha: value } : item)),
                  } : prev))
                }}
                onChangeComplete={(value) => void handlePatch(selected.id, { emo_alpha: value })}
              />
              <label>语速 {Number(selected.duration_factor).toFixed(2)}x</label>
              <Slider
                min={0.5}
                max={2}
                step={0.05}
                value={Number(selected.duration_factor)}
                onChange={(value) => {
                  setTrack((prev) => (prev ? {
                    ...prev,
                    lines: prev.lines.map((item) => (item.id === selected.id ? { ...item, duration_factor: value } : item)),
                  } : prev))
                }}
                onChangeComplete={(value) => void handlePatch(selected.id, { duration_factor: value })}
              />
              <label>混音</label>
              <Select
                value={selected.mix || "overlay"}
                options={[
                  { value: "overlay", label: lineMixLabel("overlay") },
                  { value: "replace", label: lineMixLabel("replace") },
                ]}
                onChange={(value) => void handlePatch(selected.id, { mix: value })}
              />
              <p className="mix-hint">{mixDirectorHint(selected.kind, selected.mix)}</p>
              <label>参考音</label>
              {selectedVoice?.voice?.ref_audio_url ? (
                <audio src={selectedVoice.voice.ref_audio_url} controls preload="metadata" />
              ) : (
                <p className="empty-hint">{selectedVoice ? "该角色尚未绑定参考音。" : "这句没有匹配到角色资产。"}</p>
              )}
              <Space wrap>
                <Button onClick={() => (playingSeq ? stopPlayback() : playLine(selected))}>
                  {playingSeq ? "停止试听" : "试听本句"}
                </Button>
                <Button type="primary" loading={generating || isActiveDubbingStatus(selected.status)} onClick={() => void handleGenerate([selected.id])}>
                  重新生成本句
                </Button>
              </Space>
            </div>
          ) : (
            <p className="empty-hint">选择一句台词后，可改情绪、语速并单独生成。</p>
          )}
        </aside>
      </div>
    </div>
  )
}
