import type { Director2Project, Director2SkillPack } from "./api"

export const HALF_NARRATED_PACK_ID = "half-narrated-live-action-short-drama"
export const UNBOUND_PACK_SELECT_VALUE = "__unbound__"

export function defaultCreateSkillPackId(packs: Director2SkillPack[]): string {
  if (packs.some((item) => item.id === HALF_NARRATED_PACK_ID)) return HALF_NARRATED_PACK_ID
  return String(packs[0]?.id || "")
}

export function skillPackDisplayName(pack: Pick<Director2SkillPack, "id" | "name">): string {
  if (!String(pack.id || "").trim()) return "不绑定配方 · 默认程序装箱"
  return String(pack.name || pack.id).trim() || pack.id
}

export function createProjectSkillPackExtra(packId: string): { skill_pack_id: string } | undefined {
  const id = String(packId || "").trim()
  if (!id) return undefined
  return { skill_pack_id: id }
}

export function projectBoundSkillPackId(
  project: Pick<Director2Project, "extra" | "settings"> | null | undefined,
): string {
  if (!project) return ""
  const extra = project.extra && typeof project.extra === "object" ? project.extra : {}
  const fromExtra = String(extra.skill_pack_id || extra.skillPackId || "").trim()
  if (fromExtra) return fromExtra
  const settings = project.settings && typeof project.settings === "object" ? project.settings : {}
  const nested = settings.extra && typeof settings.extra === "object"
    ? settings.extra as Record<string, unknown>
    : {}
  return String(nested.skill_pack_id || nested.skillPackId || settings.skill_pack_id || "").trim()
}

export function selectValueForPackId(packId: string): string {
  return String(packId || "").trim() || UNBOUND_PACK_SELECT_VALUE
}

export function packIdFromSelectValue(value: string): string {
  return value === UNBOUND_PACK_SELECT_VALUE ? "" : String(value || "").trim()
}

export function skillPackSelectOptions(packs: Director2SkillPack[]): { value: string; label: string }[] {
  return packs.map((pack) => ({
    value: selectValueForPackId(pack.id),
    label: skillPackDisplayName(pack),
  }))
}

export function skillPackCoverUrl(pack: Pick<Director2SkillPack, "cover"> | null | undefined): string {
  const url = String(pack?.cover || "").trim()
  return /^https?:\/\//i.test(url) ? url : ""
}

export function skillPackAuthor(pack: Pick<Director2SkillPack, "author"> | null | undefined): string {
  return String(pack?.author || "").trim()
}

export function skillPackCardTitle(pack: Pick<Director2SkillPack, "id" | "name">): string {
  if (!String(pack.id || "").trim()) return "不绑定配方"
  return skillPackDisplayName(pack)
}

export function skillPackPickerOrder(packs: Director2SkillPack[]): Director2SkillPack[] {
  return [...packs].sort((left, right) => {
    const leftUnbound = !String(left.id || "").trim()
    const rightUnbound = !String(right.id || "").trim()
    if (leftUnbound === rightUnbound) return 0
    return leftUnbound ? 1 : -1
  })
}
