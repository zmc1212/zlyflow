import {
  Button,
  ColorPicker,
  Empty,
  Input,
  InputNumber,
  Select,
  Slider,
  Switch,
  Tabs
} from "antd"
import { Film, Music2, RotateCcw, SlidersHorizontal, Type, X } from "lucide-react"
import { EFFECTS, type EditClip, type EditDocument } from "./model"

export default function Inspector({
  doc,
  clip,
  thumbnails,
  onPatch,
  onClose
}: {
  doc: EditDocument
  clip?: EditClip
  thumbnails: Record<string, string>
  onPatch: (patch: Partial<EditClip>) => void
  onClose: () => void
}) {
  const asset = doc.assets.find((a) => a.id === clip?.asset_id)
  const range = (
    key: "scale" | "rotation" | "opacity" | "volume",
    label: string,
    min: number,
    max: number,
    multiplier = 1
  ) =>
    clip && (
      <div className="se-property">
        <label htmlFor={`se-${key}`}>{label}</label>
        <div className="se-property-range">
          <Slider
            id={`se-${key}`}
            min={min}
            max={max}
            step={1}
            value={Math.round(clip[key] * multiplier)}
            onChange={(value) => onPatch({ [key]: value / multiplier })}
          />
          <InputNumber
            aria-label={label}
            suffix={key === "rotation" ? "°" : "%"}
            min={min}
            max={max}
            step={1}
            value={Math.round(clip[key] * multiplier)}
            onChange={(value) => {
              if (value !== null) onPatch({ [key]: value / multiplier })
            }}
          />
        </div>
      </div>
    )
  const timing = clip && (
    <>
      <div className="se-property-pair">
        <div className="se-property">
          <label>开始 / 秒</label>
          <InputNumber
            aria-label="片段开始时间"
            min={0}
            max={1800}
            step={1 / doc.settings.fps}
            precision={3}
            value={clip.start}
            onChange={(value) => value !== null && onPatch({ start: value })}
          />
        </div>
        <div className="se-property">
          <label>时长 / 秒</label>
          <InputNumber
            aria-label="片段时长"
            min={1 / doc.settings.fps}
            max={1800}
            step={1 / doc.settings.fps}
            precision={3}
            value={clip.duration}
            onChange={(value) => value !== null && onPatch({ duration: value })}
          />
        </div>
      </div>
      {clip.track !== "text" && (
        <div className="se-property">
          <label>素材入点 / 秒</label>
          <InputNumber
            aria-label="素材入点"
            min={0}
            step={1 / doc.settings.fps}
            precision={3}
            value={clip.in_point}
            onChange={(value) => value !== null && onPatch({ in_point: value })}
          />
        </div>
      )}
    </>
  )
  const fades = clip && (
      <div className="se-property-pair">
        <div className="se-property">
          <label>淡入 / 秒</label>
          <InputNumber
            aria-label="淡入时长"
            min={0}
            max={Math.min(10, clip.duration - clip.fade_out)}
            step={0.1}
            value={clip.fade_in}
            onChange={(value) => value !== null && onPatch({ fade_in: value })}
          />
        </div>
        <div className="se-property">
          <label>淡出 / 秒</label>
          <InputNumber
            aria-label="淡出时长"
            min={0}
            max={Math.min(10, clip.duration - clip.fade_in)}
            step={0.1}
            value={clip.fade_out}
            onChange={(value) => value !== null && onPatch({ fade_out: value })}
          />
        </div>
      </div>
  )
  const visual = clip && (
    <>
      {range("scale", "缩放", 25, 300, 100)}
      <div className="se-property se-position-property">
        <label>位置</label>
        <div className="se-position-inputs">
          <InputNumber
            aria-label="水平位置"
            prefix="X"
            min={-100}
            max={100}
            value={clip.x}
            onChange={(value) => value !== null && onPatch({ x: value })}
          />
          <InputNumber
            aria-label="垂直位置"
            prefix="Y"
            min={-100}
            max={100}
            value={clip.y}
            onChange={(value) => value !== null && onPatch({ y: value })}
          />
        </div>
      </div>
      {range("rotation", "旋转", -180, 180)}
      {range("opacity", "不透明度", 0, 100, 100)}
      <div className="se-property se-effect-property">
        <label>画面特效</label>
        <Select
          aria-label="画面特效"
          value={clip.effect}
          options={EFFECTS.map((e) => ({ value: e.id, label: e.name }))}
          onChange={(effect) => onPatch({ effect })}
        />
      </div>
      <Button
        className="se-reset-control"
        icon={<RotateCcw size={13} />}
        onClick={() =>
          onPatch({
            scale: 1,
            rotation: 0,
            x: 0,
            y: 0,
            opacity: 1,
            effect: "none"
          })
        }
      >
        重置画面
      </Button>
    </>
  )
  const text = clip && (
    <>
      <div className="se-property">
        <label htmlFor="se-text">文字内容</label>
        <Input.TextArea
          id="se-text"
          value={clip.text}
          maxLength={1000}
          autoSize={{ minRows: 3, maxRows: 6 }}
          onChange={(event) => onPatch({ text: event.target.value })}
        />
        <p className="se-help">按画面宽度自动换行，也可按 Enter 手动换行。</p>
      </div>
      <div className="se-property-pair">
        <div className="se-property">
          <label>字号</label>
          <InputNumber
            aria-label="文字字号"
            value={clip.font_size}
            min={16}
            max={200}
            onChange={(value) =>
              value !== null && onPatch({ font_size: value })
            }
          />
        </div>
        <div className="se-property">
          <label>颜色</label>
          <ColorPicker
            aria-label="文字颜色"
            value={clip.color}
            showText
            disabledAlpha
            onChange={(color) => onPatch({ color: color.toHexString() })}
          />
        </div>
      </div>
      <div className="se-property-pair">
        <div className="se-property">
          <label>水平位置 / %</label>
          <InputNumber
            aria-label="文字水平位置"
            min={-100}
            max={100}
            value={clip.x}
            onChange={(value) => value !== null && onPatch({ x: value })}
          />
        </div>
        <div className="se-property">
          <label>垂直位置 / %</label>
          <InputNumber
            aria-label="文字垂直位置"
            min={-100}
            max={100}
            value={clip.y}
            onChange={(value) => value !== null && onPatch({ y: value })}
          />
        </div>
      </div>
      {range("opacity", "不透明度 / %", 0, 100, 100)}
      {timing}
      {fades}
    </>
  )
  const sound = clip && (
    <>
      {range("volume", "音量 / %", 0, 100, 100)}
      <div className="se-property se-property-switch">
        <label htmlFor="se-muted">静音</label>
        <Switch
          id="se-muted"
          checked={clip.muted}
          onChange={(muted) => onPatch({ muted })}
        />
      </div>
      {fades}
    </>
  )
  const speed = clip && (
    <>
      <div className="se-property">
        <label>播放速度</label>
        <Select
          aria-label="播放速度"
          value={clip.speed}
          options={[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 4].map((value) => ({
            value,
            label: `${value}×${value === 1 ? " 正常" : ""}`
          }))}
          onChange={(speed) => onPatch({ speed })}
        />
      </div>
      <p className="se-help">
        变速保持原素材区间，片段时长随速度变化。变长时请为后续片段留出空间。
      </p>
      {timing}
    </>
  )
  return (
    <aside id="se-inspector" className="se-inspector" aria-label="片段属性">
      <div className="se-panel-heading">
        <strong>
          <SlidersHorizontal size={14} />
          片段属性
        </strong>
        <Button type="text" size="small" aria-label="收起片段属性" icon={<X size={15} />} onClick={onClose} />
      </div>
      {!clip ? (
        <div className="se-inspector-empty">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="选择时间线片段，调整画面、声音与时长"
          />
        </div>
      ) : (
        <>
          <div className="se-inspector-name" title={asset?.name || clip.text}>
            <div className="se-inspector-thumbnail">
              {asset && (asset.thumbnail || thumbnails[asset.id] || asset.kind === "image")
                ? <img src={asset.thumbnail || thumbnails[asset.id] || asset.url} alt="" />
                : clip.track === "text" ? <Type size={22} /> : clip.track === "audio" ? <Music2 size={22} /> : <Film size={22} />}
            </div>
            <div className="se-inspector-summary">
              <strong>{asset?.name || "文字片段"}</strong>
              <span>
              {clip.track === "text"
                ? "文字"
                : asset?.kind === "image"
                  ? "图片"
                  : clip.track === "audio"
                    ? "音频"
                    : "视频"}
                {` · ${clip.duration.toFixed(2)} 秒`}
              </span>
            </div>
          </div>
          <Tabs
            key={clip.track}
            size="small"
            defaultActiveKey={
              clip.track === "text"
                ? "text"
                : clip.track === "audio"
                  ? "audio"
                  : "visual"
            }
            items={
              clip.track === "text"
                ? [{ key: "text", label: "文字", children: text }]
                : [
                    ...(clip.track === "video"
                      ? [{ key: "visual", label: "画面", children: visual }]
                      : []),
                    {
                      key: "audio",
                      label: "声音",
                      children: sound
                    },
                    { key: "speed", label: "变速", children: speed }
                  ]
            }
          />
        </>
      )}
    </aside>
  )
}
