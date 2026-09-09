import type { RecipeProject, RecipeShot } from "./recipe-model"

const REPAIR_FIELDS = [
  "promptText",
  "continuityIn",
  "continuityOut",
  "transitionNote",
  "soundscape",
  "soundscapeEn",
] as const satisfies ReadonlyArray<keyof RecipeShot>
const FROM_SHOT_REPAIR_FIELDS = [
  "continuityOut",
  "transitionNote",
  "soundscape",
  "soundscapeEn",
] as const satisfies ReadonlyArray<keyof RecipeShot>

export function mergeContinuityRepair(
  current: RecipeProject,
  repaired: RecipeProject,
  fromShot: number,
  toShot: number,
): RecipeProject {
  const repairedByNumber = new Map(
    repaired.scenes.flatMap((scene) => scene.shots).map((shot) => [shot.shotNumber, shot]),
  )
  const targetNumbers = new Set([fromShot, toShot])
  return {
    ...current,
    continuityQa: repaired.continuityQa,
    scenes: current.scenes.map((scene) => ({
      ...scene,
      shots: scene.shots.map((shot) => {
        if (!targetNumbers.has(shot.shotNumber)) return shot
        const source = repairedByNumber.get(shot.shotNumber)
        if (!source) return shot
        const patch: Partial<RecipeShot> = {}
        const fields = shot.shotNumber === fromShot ? FROM_SHOT_REPAIR_FIELDS : REPAIR_FIELDS
        for (const field of fields) {
          if (Object.prototype.hasOwnProperty.call(source, field)) {
            Object.assign(patch, { [field]: source[field] })
          }
        }
        return { ...shot, ...patch }
      }),
    })),
  }
}
