import { AudioLines, Captions, Film, Flame, MessageSquareText, Scissors, Sparkles, type LucideIcon } from "lucide-react"
import type { EditingOperation, EditSnapshot, HookStrategy } from "../smart-edit/api"
import type { AssistantSession } from "./api"

export type { EditingOperation, HookStrategy } from "../smart-edit/api"
export type EditingContext = { kind: "smart_edit"; sequence_id: string }
export type EditorBridge = {
  projectId: string
  sequenceId: string
  sequenceName: string
  draftKey: string
  prepare: () => Promise<number>
  release: () => void
  apply: (snapshot: EditSnapshot, baseRevision: number) => void
}
export type EditingStrategy = { id: HookStrategy; label: string; description: string }
export type EditingTool = { id: EditingOperation; label: string; Icon: LucideIcon; strategies?: EditingStrategy[] }
export const HOOK_STRATEGIES: EditingStrategy[] = [
  { id: "conflict_3s", label: "3秒进冲突", description: "从冲突起刀，丢掉开场铺垫" },
  { id: "climax_only", label: "只留高潮", description: "只留理解分最高的场次" },
  { id: "quote_open", label: "金句开场", description: "先出对白金句，再接高光" },
  { id: "ending_hook", label: "结尾悬念", description: "只留后半段高光，掐掉结局" },
  { id: "trailer", label: "预告片", description: "爆点冷开，金句对切，不给答案" }
]
export const EDITING_TOOL_GROUPS: { id: string; label: string; tools: EditingTool[] }[] = [
  { id: "organize", label: "素材归位", tools: [{ id: "video_arrange", label: "智能铺轨", Icon: Film }] },
  {
    id: "assemble",
    label: "智能成片",
    tools: [
      { id: "dialogue_cut", label: "对白精剪", Icon: MessageSquareText },
      { id: "quick_cut", label: "成片速剪", Icon: Scissors },
      { id: "highlight_cut", label: "高光合集", Icon: Sparkles },
      { id: "hook_cut", label: "引流剪辑", Icon: Flame, strategies: HOOK_STRATEGIES }
    ]
  },
  {
    id: "caption",
    label: "字幕",
    tools: [
      { id: "subtitle_arrange", label: "自动字幕", Icon: Captions },
      { id: "audio_subtitle", label: "音轨字幕", Icon: AudioLines }
    ]
  }
]
export function matchesAssistantScope(session: AssistantSession, projectId: string | null, context?: EditingContext | null) {
  return context
    ? session.project_id === projectId && session.context?.kind === "smart_edit" && session.context.sequence_id === context.sequence_id
    : !session.context
}
export function canAdoptEditingResult(currentRevision: number, baseRevision: number, resultRevision: number) {
  return currentRevision === baseRevision && resultRevision === baseRevision + 1
}
export function newestPendingEditingAction<T extends { id: string; status: string }>(actions: T[], opened: Set<string>) {
  const latest = actions.at(-1)
  return latest?.status === "pending" && !opened.has(latest.id) ? latest : undefined
}
