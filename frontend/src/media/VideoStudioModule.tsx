import { HardDrive, LoaderCircle } from "lucide-react"

type Output = {
  kind: "image" | "video"; path: string; label: string
  delivery_status?: "pending" | "local" | "cloud" | "expired"
  download_url?: string | null
}

export type VideoResult = {
  generationItemId: string
  outputIndex: number
  output: Output
  src?: string
}

export default function VideoStudioModule({
  results, roundCount, pendingSave, onSave,
}: {
  results: VideoResult[]
  roundCount: number
  pendingSave?: string
  onSave: (result: VideoResult) => void
}) {
  return <section className="relative z-10 mx-auto mt-8 max-w-[1080px]" aria-label="视频生成结果">
    <div className="mb-3"><h2 className="text-sm font-medium text-[#dedee5]">视频结果</h2><p className="mt-1 text-xs text-[#85858f]">共 {roundCount} 轮</p></div>
    <div className="grid gap-4 sm:grid-cols-2">
      {results.map((result) => <article key={`${result.generationItemId}:${result.outputIndex}`} className="overflow-hidden rounded-xl border border-white/[0.1] bg-[#202127]">
        <div className="aspect-video bg-[#17181e]">{result.src ? <video className="h-full w-full object-contain" controls preload="metadata" src={result.src} /> : <div className="grid h-full place-items-center text-[#777781]"><HardDrive size={20} /></div>}</div>
        <div className="flex min-h-11 items-center justify-between gap-3 px-3 py-2">
          <div className="min-w-0"><p className="truncate text-xs text-[#c7c7ce]">{result.output.label}</p><p className={`mt-0.5 text-[10px] ${result.output.delivery_status === "local" ? "text-emerald-300" : "text-amber-200"}`}>{result.output.delivery_status === "local" ? "已保存到员工电脑" : "等待保存到本机"}</p></div>
          {result.output.delivery_status !== "local" && result.output.download_url ? <button type="button" disabled={pendingSave === result.output.path} onClick={() => onSave(result)} className="flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-[#7047f6] px-2.5 text-xs text-white disabled:opacity-45">{pendingSave === result.output.path ? <LoaderCircle className="animate-spin" size={13} /> : <HardDrive size={13} />}保存</button> : null}
        </div>
      </article>)}
    </div>
  </section>
}
