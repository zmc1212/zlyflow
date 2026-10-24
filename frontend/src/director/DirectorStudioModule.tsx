import { Navigate, useMatch, useNavigate } from "react-router-dom"
import { PATHS, ROUTE_PATTERNS } from "../paths"
import DirectorBatchStudio from "./DirectorBatchStudio"
import DirectorReplicationStudio from "./DirectorReplicationStudio"
import "./guided-flow.css"
import "../director2/director-surfaces.css"

interface DirectorStudioModuleProps {
  csrfToken: string
  allJobs: any[]
  onExitDirector?: () => void
}

export default function DirectorStudioModule({
  csrfToken,
  allJobs,
  onExitDirector,
}: DirectorStudioModuleProps) {
  const navigate = useNavigate()
  const batchMatch = useMatch(ROUTE_PATTERNS.directorBatch)
  const replicationMatch = useMatch(ROUTE_PATTERNS.directorReplication)
  const activeProjectId = batchMatch?.params.projectId ?? replicationMatch?.params.projectId

  function goHome() {
    navigate(PATHS.director)
  }

  if (!activeProjectId) {
    return <Navigate to={PATHS.director} replace />
  }

  return (
    <div className="director-shell director-specialist !h-0 !min-h-0 flex-1 overflow-hidden">
      {batchMatch ? (
        <DirectorBatchStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          allJobs={allJobs}
          onBack={goHome}
          onExitDirector={onExitDirector}
        />
      ) : (
        <DirectorReplicationStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          allJobs={allJobs}
          onBack={goHome}
          onExitDirector={onExitDirector}
        />
      )}
    </div>
  )
}
