import { describe, expect, it } from "vitest"
import { EDITING_TOOL_GROUPS, canAdoptEditingResult, matchesAssistantScope, newestPendingEditingAction } from "./editing-tools"
import { emptySelections, type AssistantSession } from "./api"

const session: AssistantSession = { id: "s", status: "ready", version: 1, created_at: "now", updated_at: "now", title: "剪辑", project_id: "p", selections: emptySelections(), resource_snapshot: {}, active_run_id: null, pending_question: null, context: { kind: "smart_edit", sequence_id: "ep1" } }
describe("editing assistant isolation and result adoption", () => {
  it("restores only the current project and sequence, keeping general chat separate", () => {
    expect(matchesAssistantScope(session, "p", { kind: "smart_edit", sequence_id: "ep1" })).toBe(true)
    expect(matchesAssistantScope(session, "p", { kind: "smart_edit", sequence_id: "ep2" })).toBe(false)
    expect(matchesAssistantScope(session, "other", session.context)).toBe(false)
    expect(matchesAssistantScope(session, "p")).toBe(false)
    expect(matchesAssistantScope({ ...session, context: null }, "other")).toBe(false)
    expect(matchesAssistantScope({ ...session, context: null }, "p")).toBe(true)
    expect(matchesAssistantScope({ ...session, context: null }, null)).toBe(true)
  })
  it("rejects duplicate and stale remote results so manual edits cannot be overwritten", () => {
    expect(canAdoptEditingResult(3, 3, 4)).toBe(true)
    expect(canAdoptEditingResult(4, 3, 4)).toBe(false)
    expect(canAdoptEditingResult(5, 3, 4)).toBe(false)
    expect(canAdoptEditingResult(3, 3, 5)).toBe(false)
  })
  it("does not reopen older authorizations after the newest action completes or is dismissed", () => {
    const older = { id: "old", status: "pending" }, latest = { id: "latest", status: "pending" }
    expect(newestPendingEditingAction([older, latest], new Set())).toEqual(latest)
    expect(newestPendingEditingAction([older, latest], new Set([latest.id]))).toBeUndefined()
    expect(newestPendingEditingAction([older, { ...latest, status: "succeeded" }], new Set())).toBeUndefined()
  })
  it("offers nine preview-first operations and explicit hook strategies", () => {
    const tools = EDITING_TOOL_GROUPS.flatMap(group => group.tools)
    expect(tools.map(tool => tool.id)).toEqual(["video_arrange", "remove_waste", "dialogue_cut", "quick_cut", "highlight_cut", "hook_cut", "subtitle_arrange", "audio_subtitle", "subtitle_translate"])
    expect(EDITING_TOOL_GROUPS.map(group => group.label)).toEqual(["素材归位", "智能成片", "字幕"])
    expect(tools.find(tool => tool.id === "hook_cut")?.strategies?.map(item => item.id)).toEqual(["conflict_3s", "climax_only", "quote_open", "ending_hook", "trailer"])
  })
})
