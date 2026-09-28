export type ProductionMode = "shot" | "director"
export type ProductionUnit = { id: string; title: string; part_id: string; render_mode?: "director" | "shot"; workflow_id?: string; source_beat_ids: string[]; duration: number }
export type ProductionMaterial = {
  id: string; job_id: string; plan_key: string; unit_ids: string[]; url: string; title: string;
  verified: boolean; duration: number | null; created_at?: string; legacy?: boolean; workflow_id?: string;
  ranges: Record<string, { start: number; end: number }>
}
export type ProductionAudio = {
  id: string; line_id: string; material_id: string; unit_ids: string[]; text?: string;
  audio_url: string; duration: number; start: number; end: number;
  mix: "overlay" | "replace"; enabled: boolean; needs_alignment: boolean;
}
export type ProductionExport = { job_id?: string; url: string; created_at?: string; title?: string; fingerprint?: string }
export type ProductionState = {
  schema_version: number; revision: number; active_mode: ProductionMode; plan_key: string; plan_revision?: number;
  plan_stale: boolean; units: ProductionUnit[]; materials: ProductionMaterial[]; adopted: Record<string, string>;
  audio: ProductionAudio[]; exports: ProductionExport[]; legacy_exports: ProductionExport[];
  current_export: ProductionExport | null; ready: boolean; block_reasons: string[]; needs_export: boolean;
  fingerprint: string;
  timeline: Array<{ material_id: string; unit_ids: string[]; url: string; start: number; end: number | null; duration: number | null }>
}

export function materialAdopted(state: ProductionState, material: ProductionMaterial): boolean {
  return material.unit_ids.length > 0 && material.unit_ids.every(id => state.adopted[id] === material.id)
}

export function materialsForUnit(state: ProductionState, unitId: string): ProductionMaterial[] {
  return state.materials.filter(m => m.plan_key === state.plan_key && (!unitId || m.unit_ids.includes(unitId))).slice().reverse()
}

export function productionFilm(state: ProductionState): ProductionExport | undefined {
  return state.current_export || state.exports[state.exports.length - 1] || state.legacy_exports[state.legacy_exports.length - 1]
}
