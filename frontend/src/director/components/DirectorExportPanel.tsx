import { useQuery } from "@tanstack/react-query"
import { Alert, Button, ColorPicker, InputNumber, Select, Slider, Space, Switch, Tag, Typography, Upload } from "antd"
import { Clapperboard, Download, Film, Play } from "lucide-react"
import { getDirectorExportCapabilities } from "../director-api"
import { directorStatusColor, directorStatusLabel } from "../status-labels"
import {
  RecipeCharacter,
  RecipeProject,
  TTS_VOICE_OPTIONS,
  flattenRecipeShots,
  recipeAudio,
  recipeExportState,
  recipeSubtitles,
  shotIsMuxable,
} from "../types"

export default function DirectorExportPanel({
  recipe,
  ttsBusy,
  muxBusy,
  previewingCharacterId,
  onChangeRecipe,
  onGenerateAllTts,
  onPreviewCharacter,
  onChangeCharacterVoice,
  onUploadBgm,
  onMux,
  onDownload,
  onPlaySequence,
  onJianying,
}: {
  recipe: RecipeProject
  ttsBusy: boolean
  muxBusy: boolean
  previewingCharacterId?: string | null
  onChangeRecipe: (patch: Partial<RecipeProject>) => void
  onGenerateAllTts: () => void
  onPreviewCharacter: (character: RecipeCharacter) => void
  onChangeCharacterVoice: (characterId: string, voiceId: string) => void
  onUploadBgm: (file: File) => void
  onMux: () => void
  onDownload: (kind: "mux" | "fcpxml" | "edl") => void
  onPlaySequence: () => void
  onJianying: () => void
}) {
  const capabilities = useQuery({
    queryKey: ["director-export-capabilities"],
    queryFn: getDirectorExportCapabilities,
  })
  const audio = recipeAudio(recipe)
  const subtitles = recipeSubtitles(recipe)
  const exportState = recipeExportState(recipe)
  const shots = flattenRecipeShots(recipe)
  const muxableCount = shots.filter(shotIsMuxable).length
  const dialogueCount = shots.filter((shot) => shot.dialogue.trim()).length
  const ttsReadyCount = shots.filter((shot) => shot.ttsStatus === "succeeded" && shot.ttsUrl).length
  const ffmpegReady = Boolean(capabilities.data?.ffmpeg)
  const ttsReady = Boolean(capabilities.data?.tts_available)
  const voices = (capabilities.data?.voices?.length ? capabilities.data.voices : TTS_VOICE_OPTIONS).map((item) => ({
    value: item.id,
    label: item.label,
  }))
  const muxUrl = exportState.muxUrl

  return (
    <div className="director-export-section">
      <Alert
        type={ffmpegReady ? "success" : "warning"}
        showIcon
        message={ffmpegReady ? "本机已找到 ffmpeg，可以导出成片 MP4" : "未找到 ffmpeg / ffprobe"}
        description={
          ffmpegReady
            ? `路径：${capabilities.data?.ffmpeg_path || "PATH"}。失败、中断或停止的镜头不会进入成片；优先使用已批准的 Take。剪映草稿仍然可用。`
            : "请把 ffmpeg 和 ffprobe 加入系统 PATH，或安装到常见目录后刷新本页。未安装时导出成片会返回不可用。ComfyUI 端口不变。"
        }
      />
      <Alert
        type={ttsReady ? "success" : "warning"}
        showIcon
        message={ttsReady ? "语音合成可用（OpenAI 兼容 /audio/speech）" : "语音合成尚未就绪"}
        description={
          ttsReady
            ? "音色由管理设置中的独立 TTS 配置提供，可复用大模型凭据。不使用 Edge TTS。"
            : capabilities.data?.tts_reason || "请联系超级管理员在「管理设置 → LLM」启用独立 TTS。"
        }
      />

      <section className="director-export-card">
        <div className="director-section-head">
          <Typography.Title level={5}>配乐</Typography.Title>
          <Upload
            accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac"
            showUploadList={false}
            beforeUpload={(file) => {
              onUploadBgm(file)
              return false
            }}
          >
            <Button size="small">上传配乐</Button>
          </Upload>
        </div>
        {audio.bgmUrl ? (
          <audio className="director-export-audio" src={audio.bgmUrl} controls preload="metadata" />
        ) : (
          <p className="director-output-hint">可选。成片会按音量与淡入淡出混入配乐。</p>
        )}
        <div className="director-export-grid">
          <label className="director-inspector-field">
            <span>配乐音量 {Math.round(audio.bgmVolume * 100)}%</span>
            <Slider
              min={0}
              max={1}
              step={0.01}
              value={audio.bgmVolume}
              onChange={(value) => onChangeRecipe({ audio: { ...audio, bgmVolume: value } })}
            />
          </label>
          <label className="director-inspector-field">
            <span>淡入（秒）</span>
            <InputNumber
              min={0}
              max={8}
              step={0.5}
              className="w-full"
              value={audio.bgmFadeInSec}
              onChange={(value) => onChangeRecipe({ audio: { ...audio, bgmFadeInSec: Number(value ?? 0) } })}
            />
          </label>
          <label className="director-inspector-field">
            <span>淡出（秒）</span>
            <InputNumber
              min={0}
              max={8}
              step={0.5}
              className="w-full"
              value={audio.bgmFadeOutSec}
              onChange={(value) => onChangeRecipe({ audio: { ...audio, bgmFadeOutSec: Number(value ?? 0) } })}
            />
          </label>
        </div>
      </section>

      <section className="director-export-card">
        <div className="director-section-head">
          <Typography.Title level={5}>字幕</Typography.Title>
          <Switch
            checked={subtitles.enabled}
            onChange={(checked) => onChangeRecipe({ subtitles: { ...subtitles, enabled: checked } })}
            checkedChildren="叠层开"
            unCheckedChildren="叠层关"
          />
        </div>
        <p className="director-output-hint">串播预览按此样式叠对白。勾选烧字幕后，成片 MP4 会把字幕写进画面。</p>
        <div className="director-export-grid">
          <label className="director-inspector-field">
            <span>位置</span>
            <Select
              className="w-full"
              value={subtitles.position}
              options={[
                { value: "top", label: "顶部" },
                { value: "center", label: "居中" },
                { value: "bottom", label: "底部" },
              ]}
              onChange={(value: "top" | "center" | "bottom") => onChangeRecipe({
                subtitles: { ...subtitles, position: value },
              })}
            />
          </label>
          <label className="director-inspector-field">
            <span>字号</span>
            <InputNumber
              min={16}
              max={72}
              className="w-full"
              value={subtitles.fontSize}
              onChange={(value) => onChangeRecipe({ subtitles: { ...subtitles, fontSize: Number(value ?? 28) } })}
            />
          </label>
          <label className="director-inspector-field">
            <span>描边</span>
            <InputNumber
              min={0}
              max={8}
              className="w-full"
              value={subtitles.strokeWidth}
              onChange={(value) => onChangeRecipe({ subtitles: { ...subtitles, strokeWidth: Number(value ?? 2) } })}
            />
          </label>
          <label className="director-inspector-field">
            <span>文字颜色</span>
            <ColorPicker
              format="hex"
              value={subtitles.textColor}
              onChange={(color) => onChangeRecipe({ subtitles: { ...subtitles, textColor: color.toHexString() } })}
            />
          </label>
          <label className="director-inspector-field">
            <span>描边颜色</span>
            <ColorPicker
              format="hex"
              value={subtitles.strokeColor}
              onChange={(color) => onChangeRecipe({ subtitles: { ...subtitles, strokeColor: color.toHexString() } })}
            />
          </label>
        </div>
      </section>

      <section className="director-export-card">
        <div className="director-section-head">
          <Typography.Title level={5}>角色音色</Typography.Title>
          <Button size="small" loading={ttsBusy} disabled={!ttsReady || !dialogueCount} onClick={onGenerateAllTts}>
            全部配音
          </Button>
        </div>
        <p className="director-output-hint">
          有对白的镜头 {dialogueCount} 条，已生成配音 {ttsReadyCount} 条。男声默认 Onyx，女声默认 Nova。
        </p>
        <div className="director-export-voices">
          {recipe.characters.map((character) => (
            <div key={character.id} className="director-export-voice-row">
              <strong>{character.name}</strong>
              <Select
                className="director-export-voice-select"
                value={character.voiceId || undefined}
                placeholder="音色"
                options={voices}
                onChange={(value: string) => onChangeCharacterVoice(character.id, value)}
              />
              <Button
                size="small"
                loading={previewingCharacterId === character.id}
                disabled={!ttsReady}
                onClick={() => onPreviewCharacter(character)}
              >
                试听
              </Button>
              {character.voicePreviewUrl ? (
                <audio className="director-export-audio" src={character.voicePreviewUrl} controls preload="metadata" />
              ) : null}
            </div>
          ))}
          {!recipe.characters.length ? <p className="director-output-hint">运行流水线后会出现角色音色。</p> : null}
        </div>
      </section>

      <section className="director-export-card">
        <div className="director-section-head">
          <Typography.Title level={5}>工作台内成片</Typography.Title>
          <Tag color={directorStatusColor(exportState.muxStatus)}>
            {exportState.muxStatus === "idle" ? "未导出" : directorStatusLabel(exportState.muxStatus)}
          </Tag>
        </div>
        <p className="director-output-hint">
          可进入成片的镜头 {muxableCount} / {shots.length}
          {exportState.muxDurationSec ? ` · 上次成片 ${exportState.muxDurationSec}s` : ""}
        </p>
        {exportState.muxError ? <Alert type="error" showIcon message={exportState.muxError} /> : null}
        {muxUrl ? <video className="director-export-film" src={muxUrl} controls playsInline /> : null}
        <Space wrap>
          <Switch
            checked={Boolean(exportState.burnSubtitles)}
            onChange={(checked) => onChangeRecipe({ export: { ...exportState, burnSubtitles: checked } })}
            checkedChildren="烧字幕"
            unCheckedChildren="不烧字幕"
          />
          <Button
            type="primary"
            icon={<Film size={14} />}
            loading={muxBusy}
            disabled={!ffmpegReady || !muxableCount}
            onClick={onMux}
          >
            导出成片
          </Button>
          <Button icon={<Download size={14} />} disabled={!muxUrl} onClick={() => onDownload("mux")}>下载 MP4</Button>
          <Button disabled={!muxableCount} onClick={() => onDownload("fcpxml")}>FCPXML</Button>
          <Button disabled={!muxableCount} onClick={() => onDownload("edl")}>EDL</Button>
          <Button icon={<Play size={14} />} disabled={!muxableCount} onClick={onPlaySequence}>串播</Button>
          <Button icon={<Clapperboard size={14} />} disabled={!muxableCount} onClick={onJianying}>剪映草稿</Button>
        </Space>
      </section>
    </div>
  )
}
