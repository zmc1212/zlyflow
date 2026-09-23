import { useCallback, useEffect, useRef, useState } from "react"
import { getEpisodeProduction, type Director2EpisodeDetail } from "./api"
import type { ProductionMode, ProductionState } from "./production"

export function useEpisodeProduction(projectId: string, episode: Director2EpisodeDetail | null, mode: ProductionMode) {
  const [state, setState] = useState<ProductionState | null>(null)
  const [error, setError] = useState("")
  const sequence = useRef(0)
  const refresh = useCallback(async () => {
    const request = ++sequence.current
    if (!episode) { setState(null); return }
    try {
      const next = await getEpisodeProduction(projectId, episode.id, mode)
      if (request === sequence.current) { setState(next); setError("") }
    } catch (err) {
      if (request === sequence.current) { setError(err instanceof Error ? err.message : "制作数据读取失败"); setState(null) }
    }
  }, [projectId, episode?.id, mode])
  useEffect(() => { setState(null); return () => { sequence.current++ } }, [refresh])
  useEffect(() => { if (episode) void refresh() }, [episode, refresh])
  return { state, error, refresh }
}
