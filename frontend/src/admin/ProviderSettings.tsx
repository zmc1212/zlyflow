import { Segmented } from "antd"
import { Clapperboard, Cloud, MonitorPlay, Music } from "lucide-react"
import { useSearchParams } from "react-router-dom"
import CloudVideoProviderSettings from "./CloudVideoProviderSettings"
import ComfyProviderSettings from "./ComfyProviderSettings"
import GrsProviderSettings from "./GrsProviderSettings"
import MusicProviderSettings from "./MusicProviderSettings"

type ProviderSectionKey = "comfy" | "cloud-video" | "grs" | "music"

const PROVIDER_SECTIONS: Array<{
  key: ProviderSectionKey
  label: string
  icon: typeof MonitorPlay
}> = [
  { key: "comfy", label: "ComfyUI 视频后端", icon: MonitorPlay },
  { key: "cloud-video", label: "云端视频", icon: Clapperboard },
  { key: "grs", label: "GRS 图片", icon: Cloud },
  { key: "music", label: "音乐生成", icon: Music },
]

function providerSection(value: string | null): ProviderSectionKey {
  return PROVIDER_SECTIONS.some((item) => item.key === value) ? (value as ProviderSectionKey) : "comfy"
}

/**
 * 「AI 供应商」页的分类切换。
 * 各分类面板全部保持挂载、仅隐藏非当前项，切换时不会丢失表单里尚未保存的编辑。
 * 当前分类写入 ?section=...，刷新和分享链接后仍停留在同一供应商。
 */
export default function ProviderSettings({ csrfToken }: { csrfToken: string }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const section = providerSection(searchParams.get("section"))

  const changeSection = (next: string) => {
    const params = new URLSearchParams(searchParams)
    if (next === "comfy") params.delete("section")
    else params.set("section", next)
    setSearchParams(params, { replace: true })
    if (window.scrollY > 0) window.scrollTo({ top: 0 })
  }

  return (
    <div>
      <div className="studio-admin-panel max-w-[1180px] px-5 pt-5 lg:px-8">
        <div className="sticky top-3 z-20 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-black/[0.06] bg-white px-4 py-3 shadow-sm">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#111827]">供应商配置</p>
            <p className="mt-0.5 text-xs text-[#6b7280]">按类别切换查看，页面只展示当前供应商，避免长距离滚动。</p>
          </div>
          <Segmented
            size="large"
            aria-label="切换供应商配置"
            value={section}
            onChange={(value) => changeSection(String(value))}
            options={PROVIDER_SECTIONS.map(({ key, label, icon: Icon }) => ({
              value: key,
              label: (
                <span className="inline-flex items-center gap-1.5">
                  <Icon size={14} />
                  {label}
                </span>
              ),
            }))}
          />
        </div>
      </div>

      <div hidden={section !== "comfy"}>
        <ComfyProviderSettings csrfToken={csrfToken} />
      </div>
      <div hidden={section !== "cloud-video"}>
        <CloudVideoProviderSettings csrfToken={csrfToken} />
      </div>
      <div hidden={section !== "grs"}>
        <GrsProviderSettings csrfToken={csrfToken} />
      </div>
      <div hidden={section !== "music"}>
        <MusicProviderSettings csrfToken={csrfToken} />
      </div>
    </div>
  )
}
