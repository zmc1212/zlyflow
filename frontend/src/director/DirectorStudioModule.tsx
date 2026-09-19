import { Navigate, useMatch, useNavigate } from "react-router-dom"
import { PATHS, ROUTE_PATTERNS } from "../paths"
import DirectorBatchStudio from "./DirectorBatchStudio"
import DirectorHypitStudio from "./DirectorHypitStudio"
import DirectorReplicationStudio from "./DirectorReplicationStudio"
import "./guided-flow.css"

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
  const hypitMatch = useMatch(ROUTE_PATTERNS.directorHypit)
  const activeProjectId = batchMatch?.params.projectId ?? replicationMatch?.params.projectId ?? hypitMatch?.params.projectId

  function goHome() {
    navigate(PATHS.director)
  }

  if (!activeProjectId) {
    return <Navigate to={PATHS.director} replace />
  }

  return (
    <div className="director-shell !h-0 !min-h-0 flex-1 overflow-hidden">
      {batchMatch ? (
        <DirectorBatchStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          allJobs={allJobs}
          onBack={goHome}
          onExitDirector={onExitDirector}
        />
      ) : replicationMatch ? (
        <DirectorReplicationStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          allJobs={allJobs}
          onBack={goHome}
          onExitDirector={onExitDirector}
        />
      ) : (
        <DirectorHypitStudio
          projectId={activeProjectId}
          csrfToken={csrfToken}
          onBack={goHome}
          onExitDirector={onExitDirector}
        />
      )}
    </div>
  )
}
