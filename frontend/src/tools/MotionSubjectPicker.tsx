import { Alert, Button, Modal, Radio, Spin } from "antd"
import { useEffect, useState } from "react"
import { hasSubjects, subjectPointAt, type MotionReferenceAsset, type SubjectPoint } from "../generation/motion-transfer"

export default function MotionSubjectPicker({ asset, video, points, subjectCount = 1, purpose = "person", onChange, onClose }: {
  asset: MotionReferenceAsset | null
  video: boolean
  points: SubjectPoint[]
  subjectCount?: number
  purpose?: "person" | "face"
  onChange: (points: SubjectPoint[]) => void
  onClose: () => void
}) {
  const [frame, setFrame] = useState("")
  const [error, setError] = useState("")
  const [exclude, setExclude] = useState(false)
  const [subject, setSubject] = useState(0)
  useEffect(() => {
    setFrame(""); setError(""); setExclude(false); setSubject(0)
    if (!asset) return
    if (!video) { setFrame(asset.preview); return }
    let active = true
    const element = document.createElement("video")
    element.muted = true
    element.preload = "auto"
    element.onloadeddata = () => {
      if (!active) return
      try {
        const canvas = document.createElement("canvas")
        canvas.width = element.videoWidth; canvas.height = element.videoHeight
        const context = canvas.getContext("2d")
        if (!context) throw new Error("无法读取视频首帧")
        context.drawImage(element, 0, 0)
        setFrame(canvas.toDataURL("image/png"))
      } catch { setError("无法读取视频首帧，请换用标准 MP4 文件。") }
    }
    element.onerror = () => { if (active) setError("浏览器无法解码此视频，请换用标准 MP4 文件。") }
    element.src = asset.preview
    return () => { active = false; element.onloadeddata = null; element.onerror = null; element.removeAttribute("src"); element.load() }
  }, [asset?.id, asset?.preview, video])
  const face = purpose === "face"
  const title = face ? "选择要修复的人脸" : video ? "选择视频中要替换的人物" : "选择形象图中的角色"
  return <Modal open={Boolean(asset)} title={title} width={840} centered onCancel={onClose} destroyOnHidden
    footer={<Button type="primary" disabled={!hasSubjects(points, subjectCount)} onClick={onClose}>完成选择</Button>}>
    <p className="studio-motion-selection-help">{face ? "点击视频首帧中要修复的人脸中心。每次选择一个人脸，点击其他位置可重新选择。" : <>{subjectCount > 1 ? "按相同编号配对：人物 1 对应人物 1，人物 2 对应人物 2。" : "选中同一人物。"}在头发、脸部、躯干等可见部位补点，尤其是深色头发和衣服；可用排除标记指出路人。</>}</p>
    {subjectCount > 1 ? <Radio.Group aria-label="当前标记人物" value={subject} onChange={(event) => setSubject(event.target.value)}
      options={[{ label: "人物 1", value: 0 }, { label: "人物 2", value: 1 }]} optionType="button" /> : null}
    <div className="studio-motion-selection-toolbar">
      {!face ? <Radio.Group value={exclude} onChange={(event) => setExclude(event.target.value)} options={[
        { label: "选中人物", value: false }, { label: "排除人物", value: true },
      ]} optionType="button" /> : null}
      <Button onClick={() => onChange(points.filter((point) => (point.subject ?? 0) !== subject))} disabled={!points.some((point) => (point.subject ?? 0) === subject)}>清除标记</Button>
      <span>{face ? (points.length ? "已选择 1 个人脸" : "尚未选择人脸") : `人物 ${subject + 1}：${points.filter((point) => (point.subject ?? 0) === subject).length} / 20 个标记`}</span>
    </div>
    {error ? <Alert type="error" title={error} showIcon /> : !frame ? <Spin /> : <div className={`studio-motion-selection-canvas${subjectCount > 1 ? " is-two" : ""}`}>
      <div className="studio-motion-selection-image">
        <img src={frame} alt={title} draggable={false} onClick={(event) => {
          if (!face && points.filter((point) => (point.subject ?? 0) === subject).length >= 20) return
          const point = subjectPointAt(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect(), face ? false : exclude)
          if (point) onChange(face ? [{ ...point, subject: 0 }] : [...points, { ...point, subject }])
        }} />
        {points.map((point, index) => <span key={index} className={`studio-motion-selection-dot${point.subject === 1 ? " is-second" : ""}${point.exclude ? " is-excluded" : ""}`}
          style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }} aria-label={`人物 ${(point.subject ?? 0) + 1}${point.exclude ? "排除" : "选中"}标记 ${index + 1}`}>{(point.subject ?? 0) + 1}</span>)}
      </div>
    </div>}
  </Modal>
}
