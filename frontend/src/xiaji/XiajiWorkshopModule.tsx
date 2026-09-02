import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Empty, Space, Spin, Tabs, Tag, Typography, message } from "antd"
import { Clapperboard, Film, RefreshCw, Sparkles, Users } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import {
  createXiajiEpisodesFromAnalysis,
  generateXiajiEpisodeScript,
  getXiajiEpisode,
  listXiajiEpisodes,
  type XiajiBeat,
  type XiajiEpisode,
  type XiajiEpisodeLink,
  type XiajiEpisodeStatus,
} from "./xiaji-api"
import XiajiShotsWorkbench from "./XiajiShotsWorkbench"

const EPISODE_STATUS: Record<XiajiEpisodeStatus, { color: string; text: string }> = {
  draft: { color: "default", text: "草稿" },
  scripting: { color: "processing", text: "生成脚本中" },
  script_ready: { color: "blue", text: "脚本已就绪" },
  sketching: { color: "processing", text: "出图中" },
  sketched: { color: "green", text: "草图完成" },
}

function statusTag(status: XiajiEpisodeStatus) {
  const item = EPISODE_STATUS[status] ?? EPISODE_STATUS.draft
  return <Tag color={item.color}>{item.text}</Tag>
}

function AssetChips({ links, kind }: { links: XiajiEpisodeLink[]; kind: XiajiEpisodeLink["kind"] }) {
  const items = links.filter((item) => item.kind === kind)
  if (!items.length) return <Typography.Text type="secondary">未规划</Typography.Text>
  return (
    <ul className="xiaji-workshop-assets">
      {items.map((item) => (
        <li key={item.id}>
          {item.image_url ? <img src={item.image_url} alt="" /> : <span className="xiaji-workshop-asset-fallback">{(item.name || "?").slice(0, 1)}</span>}
          <div>
            <strong>{item.name}</strong>
            <em>{item.first_seen_line ? `第 ${item.first_seen_line} 行` : "未在原文定位"}</em>
          </div>
        </li>
      ))}
    </ul>
  )
}

function BeatCard({ beat }: { beat: XiajiBeat }) {
  if (beat.kind === "scene_heading") {
    return (
      <article className="xiaji-beat xiaji-beat-heading">
        <span>场景镜头</span>
        <strong>{beat.heading}</strong>
      </article>
    )
  }
  if (beat.kind === "dialogue") {
    return (
      <article className="xiaji-beat xiaji-beat-dialogue">
        <div>
          <span>对白台词</span>
          <p><strong>{beat.speaker}</strong>：{beat.dialogue}</p>
        </div>
        {beat.action ? (
          <div>
            <span>画面描述</span>
            <p>{beat.action}</p>
          </div>
        ) : null}
      </article>
    )
  }
  return (
    <article className="xiaji-beat">
      <span>画面描述</span>
      <p>{beat.action}</p>
    </article>
  )
}

function ScriptPane({ episode }: { episode: XiajiEpisode }) {
  const characters = episode.links.filter((item) => item.kind === "character")
  return (
    <div className="xiaji-script-grid">
      <div className="xiaji-script-col">
        <section>
          <header>
            <Users size={14} />
            <h3>资产规划</h3>
            <em>{characters.length} 个身份</em>
          </header>
          <AssetChips links={episode.links} kind="character" />
        </section>
        <section>
          <header>
            <h3>原文剧本</h3>
            <em>编号后的内容将生成脚本，当前共 {episode.original_lines.length} 行</em>
          </header>
          <ol className="xiaji-original-lines">
            {episode.original_lines.map((line, index) => (
              <li key={`${index}-${line.slice(0, 12)}`}>
                <span>{index + 1}.</span>
                <p>{line}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
      <div className="xiaji-script-col">
        <section>
          <header>
            <h3>脚本预览</h3>
            <em>{episode.beats.length} 个 Beat</em>
          </header>
          {episode.beats.length === 0 ? (
            <Empty description="点「生成脚本」把原文改写成可拍摄的 Beat" />
          ) : (
            <div className="xiaji-beat-list">
              {episode.beats.map((beat) => <BeatCard key={beat.id} beat={beat} />)}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function EpisodeWorkspace({
  csrfToken,
  episodeId,
  onBack,
}: {
  csrfToken: string
  episodeId: string
  onBack: () => void
}) {
  const queryClient = useQueryClient()
  const episodeQuery = useQuery({
    queryKey: ["xiaji-episode", episodeId],
    queryFn: () => getXiajiEpisode(episodeId),
    refetchInterval: (query) => {
      const data = query.state.data
      if (data?.status === "scripting") return 2000
      const beats = data?.beats || []
      return beats.some((item) => item.status === "queued" || item.status === "generating") ? 4000 : false
    },
  })
  const scriptMutation = useMutation({
    mutationFn: () => generateXiajiEpisodeScript(csrfToken, episodeId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episode", episodeId] })
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episodes", result.episode.project_id] })
      if (result.reused) message.info("脚本正在生成，请稍候")
      else message.success("已开始生成脚本")
    },
    onError: (error: Error) => message.error(error.message),
  })
  const episode = episodeQuery.data
  const previousStatus = useRef(episode?.status)
  useEffect(() => {
    const current = episode?.status
    if (previousStatus.current === "scripting" && current === "script_ready") {
      message.success(`已生成 ${episode?.beats.length || 0} 个 Beat`)
    }
    previousStatus.current = current
  }, [episode?.beats.length, episode?.status])
  if (episodeQuery.isLoading || !episode) {
    return (
      <div className="xiaji-workshop-loading">
        <Spin />
        <span>正在打开剧集</span>
      </div>
    )
  }
  return (
    <div className="xiaji-episode">
      <header className="xiaji-episode-head">
        <div>
          <Button onClick={onBack}>返回概览</Button>
          <h2>第{episode.number}集 {episode.title}</h2>
          {statusTag(episode.status)}
        </div>
        <p>
          {episode.line_count} 行原文 · {episode.beats.length} 个 Beat · {episode.character_count} 个身份 ·
          {episode.scene_count} 个场景 · {episode.prop_count} 个道具
        </p>
        {episode.error ? <Alert type="error" showIcon message={episode.error} /> : null}
        <Space>
          <Button
            type="primary"
            icon={<Sparkles size={14} />}
            loading={scriptMutation.isPending || episode.status === "scripting"}
            onClick={() => scriptMutation.mutate()}
          >
            {episode.status === "scripting" ? "正在生成脚本" : "生成脚本"}
          </Button>
        </Space>
      </header>
      <Tabs
        items={[
          { key: "script", label: "剧本", children: <ScriptPane episode={episode} /> },
          {
            key: "shots",
            label: "镜头",
            children: <XiajiShotsWorkbench csrfToken={csrfToken} episode={episode} onRefresh={() => episodeQuery.refetch()} />,
          },
          {
            key: "compose",
            label: "合成",
            children: <Empty className="xiaji-placeholder" description="配音、字幕和时间线合成将在后续版本接入。" />,
          },
        ]}
      />
    </div>
  )
}

export default function XiajiWorkshopModule({ csrfToken, projectId }: { csrfToken: string; projectId: string }) {
  const queryClient = useQueryClient()
  const [episodeId, setEpisodeId] = useState<string | null>(null)
  const listQuery = useQuery({
    queryKey: ["xiaji-episodes", projectId],
    queryFn: () => listXiajiEpisodes(projectId),
    refetchInterval: (query) => {
      const items = query.state.data ?? []
      return items.some((item) => item.status === "scripting") ? 2000 : false
    },
  })
  const createMutation = useMutation({
    mutationFn: () => createXiajiEpisodesFromAnalysis(csrfToken, projectId),
    onSuccess: (items) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-episodes", projectId] })
      message.success(`已生成 ${items.length} 集`)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const episodes = listQuery.data ?? []
  const stats = {
    total: episodes.length,
    ready: episodes.filter((item) => item.status !== "draft").length,
    characters: new Set(episodes.flatMap((item) => item.links.filter((link) => link.kind === "character").map((link) => link.asset_id))).size,
    scenes: new Set(episodes.flatMap((item) => item.links.filter((link) => link.kind === "scene").map((link) => link.asset_id))).size,
    props: new Set(episodes.flatMap((item) => item.links.filter((link) => link.kind === "prop").map((link) => link.asset_id))).size,
    beats: episodes.reduce((sum, item) => sum + item.beat_count, 0),
  }

  if (episodeId) {
    return <EpisodeWorkspace csrfToken={csrfToken} episodeId={episodeId} onBack={() => setEpisodeId(null)} />
  }

  return (
    <div className="xiaji-workshop">
      <header className="xiaji-workshop-hero">
        <span className="xiaji-ingest-hero-icon" aria-hidden="true">
          <Clapperboard size={18} />
        </span>
        <div>
          <h1>剧集工坊</h1>
          <p>把内容库规划落成剧集，生成脚本 Beat，再按镜头出草图。</p>
        </div>
        <Space>
          <Button icon={<RefreshCw size={14} />} onClick={() => listQuery.refetch()}>刷新</Button>
          <Button type="primary" icon={<Film size={14} />} loading={createMutation.isPending} onClick={() => createMutation.mutate()}>
            从规划生成剧集
          </Button>
        </Space>
      </header>
      <div className="xiaji-workshop-stats">
        <span>总集数 {stats.total}</span>
        <span>已有脚本 {stats.ready}</span>
        <span>身份 {stats.characters}</span>
        <span>场景 {stats.scenes}</span>
        <span>道具 {stats.props}</span>
        <span>Beat {stats.beats}</span>
      </div>
      {listQuery.isLoading ? (
        <div className="xiaji-workshop-loading"><Spin /><span>正在加载剧集</span></div>
      ) : episodes.length === 0 ? (
        <Empty
          description="还没有剧集。先在内容库完成导入分析，再点「从规划生成剧集」。角色、场景、道具建议先转入资产库。"
        />
      ) : (
        <div className="xiaji-episode-grid">
          {episodes.map((item) => (
            <button key={item.id} type="button" className="xiaji-episode-card" onClick={() => setEpisodeId(item.id)}>
              <div>
                <strong>第{item.number}集 {item.title}</strong>
                {statusTag(item.status)}
              </div>
              <p>{item.content_summary || "暂无摘要"}</p>
              <em>{item.beat_count} 个分镜 · {item.character_count} 个身份 · {item.scene_count} 个场景</em>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
