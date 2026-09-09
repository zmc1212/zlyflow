import { Alert, Button, Empty, Modal, Progress, Select, Space, Switch, Typography, message } from "antd"
import { Download, FileText, Film } from "lucide-react"
import { useMemo, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
  composeXiajiEpisode,
  downloadXiajiEpisodeSrt,
  downloadXiajiEpisodeVideo,
  downloadXiajiEpisodeZip,
  xiajiBeatCanMakeVideo,
  type XiajiBeat,
  type XiajiEpisode,
} from "./xiaji-api"
import { xiajiProjectJobsQueryKey } from "./XiajiJobsModule"

const RESOLUTIONS = [
  { value: "1280x720", label: "720p" },
  { value: "1920x1080", label: "1080p" },
]

function isComposeShot(beat: XiajiBeat) {
  return xiajiBeatCanMakeVideo(beat) && beat.kind !== "scene_heading"
}

function beatHasVideo(beat: XiajiBeat) {
  return Boolean(String(beat.video_url || "").trim())
}

function formatDuration(totalSeconds: number) {
  if (!totalSeconds || totalSeconds <= 0) return "—"
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60)
  return `${minutes}:${String(seconds).padStart(2, "0")}`
}

function stageLabel(stage: string) {
  return stage === "audio" ? "配音" : "视频"
}

export default function XiajiComposePane({
  csrfToken,
  episode,
  onJumpToBeat,
}: {
  csrfToken: string
  episode: XiajiEpisode
  onJumpToBeat: (beatId: string) => void
}) {
  const queryClient = useQueryClient()
  const [resolution, setResolution] = useState(episode.compose_resolution || "1280x720")
  const [addSubtitles, setAddSubtitles] = useState(episode.compose_add_subtitles !== false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const shots = useMemo(() => (episode.beats || []).filter(isComposeShot), [episode.beats])
  const concatBeats = useMemo(() => (episode.beats || []).filter(beatHasVideo), [episode.beats])
  const estimated = concatBeats.reduce((sum, item) => sum + (Number(item.video_duration) || 5), 0)
  const blockers = (episode.compose_blockers || []).filter((item) => {
    const beat = (episode.beats || []).find((row) => row.id === item.beat_id || row.sequence === item.sequence)
    return !beat || isComposeShot(beat)
  })
  const composing = episode.compose_status === "composing"
  const resultUrl = episode.compose_url
  const filename = episode.compose_filename || `ep${String(episode.number).padStart(3, "0")}_final.mp4`
  const audioBlocked = blockers.some((item) => item.stages.includes("audio"))
  const canCompose = concatBeats.length > 0 && !audioBlocked && !composing
  const composeMutation = useMutation({
    mutationFn: () => composeXiajiEpisode(csrfToken, episode.id, { resolution, add_subtitles: addSubtitles }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episode.id] })
      void queryClient.invalidateQueries({ queryKey: xiajiProjectJobsQueryKey(episode.project_id) })
      if (result.reused) message.info("正在合成成片，请稍候")
      else message.success("已开始合成成片，可在全部任务中查看进度")
    },
    onError: (error: Error) => message.error(error.message),
  })

  const download = async (kind: "video" | "srt" | "zip") => {
    try {
      if (kind === "video") await downloadXiajiEpisodeVideo(episode.id, filename)
      else if (kind === "srt") await downloadXiajiEpisodeSrt(episode.id, `ep${String(episode.number).padStart(3, "0")}.srt`)
      else await downloadXiajiEpisodeZip(csrfToken, episode.id, `ep${String(episode.number).padStart(3, "0")}.zip`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "导出失败")
    }
  }

  if (!shots.length && !concatBeats.length) {
    return <Empty className="xiaji-placeholder" description="请先在「镜头」生成可出片的视频，再合成成片。" />
  }

  return (
    <div className="xiaji-compose">
      <header className="xiaji-compose-head">
        <div>
          <h3>{episode.title || `第${episode.number}集`}</h3>
          <p>
            <code>{filename}</code>
            {estimated ? ` · 约 ${formatDuration(estimated)}` : ""}
            {resultUrl ? ` · ${RESOLUTIONS.find((item) => item.value === (episode.compose_resolution || resolution))?.label || "720p"}` : ""}
          </p>
        </div>
        <Space wrap>
          <Button icon={<FileText size={14} />} onClick={() => void download("srt")}>导出 SRT</Button>
          <Button icon={<Download size={14} />} onClick={() => void download("zip")}>导出素材包</Button>
          {resultUrl ? (
            <>
              <Button type="primary" icon={<Download size={14} />} onClick={() => void download("video")}>下载成片</Button>
              <Button icon={<Film size={14} />} disabled={!canCompose} onClick={() => setConfirmOpen(true)}>重新合成</Button>
            </>
          ) : (
            <Button type="primary" icon={<Film size={14} />} disabled={!canCompose} loading={composing} onClick={() => setConfirmOpen(true)}>
              合成成片
            </Button>
          )}
        </Space>
      </header>
      {episode.compose_error ? <Alert type="error" showIcon message={episode.compose_error} /> : null}

      {resultUrl && !composing ? (
        <div className="xiaji-compose-preview">
          <video src={resultUrl} controls playsInline />
        </div>
      ) : composing ? (
        <div className="xiaji-compose-progress">
          <Typography.Title level={5}>正在合成本集成片</Typography.Title>
          <Progress percent={episode.compose_progress || 0} status="active" />
          <Typography.Text type="secondary">按镜头顺序拼接视频，完成后可预览和下载。</Typography.Text>
        </div>
      ) : (
        <>
          <div className="xiaji-compose-config">
            <div>
              <Typography.Title level={5}>
                {blockers.length
                  ? `将拼接 ${concatBeats.length} 段已有视频，另有 ${blockers.length} 个镜头尚未出片`
                  : "镜头已齐，可以合成本集成片"}
              </Typography.Title>
              <Typography.Text type="secondary">
                {blockers.length
                  ? "场次卡不需要单独成片。未出片镜头会跳过；点卡片可回到镜头页补生成。"
                  : "选择输出分辨率，并决定是否烧录对白字幕。"}
              </Typography.Text>
            </div>
            <Space size="large" wrap>
              <label className="xiaji-compose-field">
                <span>分辨率</span>
                <Select
                  value={resolution}
                  onChange={setResolution}
                  options={RESOLUTIONS}
                  style={{ width: 120 }}
                />
              </label>
              <label className="xiaji-compose-field">
                <span>字幕</span>
                <Switch checked={addSubtitles} onChange={setAddSubtitles} checkedChildren="开" unCheckedChildren="关" />
              </label>
            </Space>
          </div>
          {blockers.length ? (
            <ul className="xiaji-compose-blockers">
              {blockers.map((item) => (
                <li key={item.beat_id || item.sequence}>
                  <button type="button" onClick={() => onJumpToBeat(item.beat_id)}>
                    <em>镜头</em>
                    <strong>{item.sequence}</strong>
                    <span>缺{item.stages.map(stageLabel).join("、")}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}

      <Modal
        title={`合成「${episode.title || `第${episode.number}集`}」`}
        open={confirmOpen}
        onCancel={() => setConfirmOpen(false)}
        onOk={() => {
          setConfirmOpen(false)
          composeMutation.mutate()
        }}
        okText="开始合成"
        confirmLoading={composeMutation.isPending}
      >
        <div className="xiaji-compose-summary">
          <div><span>镜头</span><strong>{concatBeats.length}</strong></div>
          <div><span>时长</span><strong>{formatDuration(estimated)}</strong></div>
          <div><span>分辨率</span><strong>{RESOLUTIONS.find((item) => item.value === resolution)?.label}</strong></div>
          <div><span>字幕</span><strong>{addSubtitles ? "烧录对白" : "不烧录"}</strong></div>
        </div>
      </Modal>
    </div>
  )
}
