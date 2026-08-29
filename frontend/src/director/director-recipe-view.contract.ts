import {
  parseDirectorRecipeView,
  resolveDirectorRecipeView,
  DIRECTOR_RECIPE_VIEWS,
} from "./types"

/** Compile-time + runtime contract checks used by `pnpm --dir frontend build`. */
export function assertDirectorRecipeViewContract(): void {
  if (DIRECTOR_RECIPE_VIEWS.join(",") !== "plan,timeline") {
    throw new Error("director recipe views must be plan and timeline")
  }
  if (parseDirectorRecipeView(null) !== "plan" || parseDirectorRecipeView("") !== "plan") {
    throw new Error("missing view query must default to plan")
  }
  if (parseDirectorRecipeView("plan") !== "plan" || parseDirectorRecipeView("PLAN") !== "plan") {
    throw new Error("plan view query must be accepted")
  }
  if (parseDirectorRecipeView("timeline") !== "timeline" || parseDirectorRecipeView("Timeline") !== "timeline") {
    throw new Error("timeline view query must be accepted")
  }
  if (parseDirectorRecipeView("edit") !== "plan" || parseDirectorRecipeView("shots") !== "plan") {
    throw new Error("unknown view query must fall back to plan")
  }
  if (resolveDirectorRecipeView("timeline", { mobile: true }) !== "plan") {
    throw new Error("mobile must lock to plan even when view=timeline")
  }
  if (resolveDirectorRecipeView("timeline", { mobile: false }) !== "timeline") {
    throw new Error("desktop must honor view=timeline")
  }
  if (resolveDirectorRecipeView(null, { mobile: true }) !== "plan") {
    throw new Error("mobile without view query must stay on plan")
  }
  if (resolveDirectorRecipeView("PLAN", { mobile: false }) !== "plan") {
    throw new Error("desktop PLAN must resolve to plan")
  }
}

assertDirectorRecipeViewContract()
