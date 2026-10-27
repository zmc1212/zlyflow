import type { AssistantDetail } from "./api"

/**
 * A terminal SSE event is authoritative for the run. If the follow-up detail
 * request is temporarily unavailable, release the stale local run so the
 * composer does not remain locked forever; the next refresh can hydrate the
 * full message and run history again.
 */
export function releaseTerminalAssistantRun(detail: AssistantDetail, runId: string): AssistantDetail {
  if (detail.run?.id !== runId) return detail
  return {
    ...detail,
    session: { ...detail.session, active_run_id: null },
    run: null,
  }
}
