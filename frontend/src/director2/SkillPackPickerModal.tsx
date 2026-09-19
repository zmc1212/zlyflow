import { useEffect, useRef, useState } from "react"
import { Modal, Spin } from "antd"
import { Clapperboard } from "lucide-react"
import type { Director2SkillPack } from "./api"
import {
  packIdFromSelectValue,
  selectValueForPackId,
  skillPackAuthor,
  skillPackCardTitle,
  skillPackCoverUrl,
  skillPackPickerOrder,
} from "./skill-pack"

function PackCover({ cover, official }: { cover: string; official: boolean }) {
  const [failed, setFailed] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    setFailed(false)
  }, [cover])
  useEffect(() => {
    const video = videoRef.current
    if (!video || failed) return
    const play = () => {
      void video.play().catch(() => undefined)
    }
    play()
    video.addEventListener("canplay", play)
    return () => video.removeEventListener("canplay", play)
  }, [cover, failed])
  return (
    <span className="dh-pack-picker-cover">
      {cover && !failed ? (
        <video
          ref={videoRef}
          src={cover}
          muted
          loop
          playsInline
          autoPlay
          preload="auto"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="dh-pack-picker-cover-fallback" aria-hidden>
          <Clapperboard size={28} />
        </span>
      )}
      {official ? <span className="dh-pack-picker-badge">官方精选</span> : null}
    </span>
  )
}

export default function SkillPackPickerModal({
  open,
  packs,
  loading,
  confirming,
  value,
  onChange,
  onOk,
  onCancel,
}: {
  open: boolean
  packs: Director2SkillPack[]
  loading?: boolean
  confirming?: boolean
  value: string
  onChange: (packId: string) => void
  onOk: (packId?: string) => void
  onCancel: () => void
}) {
  return (
    <Modal
      title="选择制作配方"
      open={open}
      onOk={() => onOk()}
      onCancel={onCancel}
      okText="创建工程"
      cancelText="取消"
      confirmLoading={Boolean(confirming)}
      okButtonProps={{ disabled: Boolean(loading) }}
      destroyOnClose
      wrapClassName="dh-pack-picker-modal"
      width={920}
    >
      <p className="dh-pack-picker-hint">后续剧本、定妆和工坊都按这个配方处理。内容库里的骨架模板不是这一项。</p>
      {loading ? (
        <div className="dh-pack-picker-loading"><Spin /><span>正在加载配方</span></div>
      ) : (
        <div className="dh-pack-picker-grid" role="listbox" aria-label="制作配方">
          {skillPackPickerOrder(packs).map((pack) => {
            const selected = selectValueForPackId(value) === selectValueForPackId(pack.id)
            const cover = skillPackCoverUrl(pack)
            const author = skillPackAuthor(pack)
            return (
              <button
                key={selectValueForPackId(pack.id)}
                type="button"
                role="option"
                aria-selected={selected}
                className={`dh-pack-picker-card${selected ? " is-selected" : ""}`}
                onClick={() => onChange(packIdFromSelectValue(selectValueForPackId(pack.id)))}
                onDoubleClick={() => {
                  const packId = packIdFromSelectValue(selectValueForPackId(pack.id))
                  onChange(packId)
                  onOk(packId)
                }}
              >
                <PackCover cover={cover} official={Boolean(cover || author)} />
                <span className="dh-pack-picker-copy">
                  <strong>{skillPackCardTitle(pack)}</strong>
                  {pack.summary ? <small>{pack.summary}</small> : null}
                  {author ? <em>{author}</em> : <em>工作台默认</em>}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </Modal>
  )
}
