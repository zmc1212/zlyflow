import { persistableDirectorProjects } from "./director-storage"
import { jobProgressFromJob, mergeDirectorStatus, shotStatusFromJob } from "./director-submit"
import {
  buildReferencePlan,
  compileClipPrompt,
  compileShotPrompt,
  h3AlignedFrames,
  resolveShotSubmission,
  snapH3DurationSec,
} from "./prompt-compiler"
import { createEmptyShot, createInitialSubjectSlots, defaultCameraDirection, TimelineProject } from "./types"

function sampleProject(overrides?: Partial<TimelineProject>): TimelineProject {
  const slots = createInitialSubjectSlots()
  slots[0] = { ...slots[0], previewUrl: "data:image/png;base64,sub1", description: "黑发风衣" }
  slots[1] = { ...slots[1], previewUrl: "data:image/png;base64,sub2" }
  const shot = {
    ...createEmptyShot(1, 0, 5),
    firstFrameUrl: "data:image/png;base64,first",
    prompt: "主角 @ref1 走过雨夜街道",
    camera: { ...defaultCameraDirection(), scale: "MS" as const, movement: "zoom_in" as const },
  }
  return {
    id: "contract-proj",
    title: "契约工程",
    aspectRatio: "16:9",
    canvasTier: "native",
    previewQuality: "0.4",
    previewSpeed: "fast",
    finalQuality: "1.0",
    finalSpeed: "balanced",
    width: 1344,
    height: 768,
    fps: 24,
    refsMode: "refs_on",
    globalSoundscape: "雨声",
    globalMusic: "",
    subjectSlots: slots,
    shots: [shot],
    manualPromptOverrideEnabled: false,
    manualPromptOverrideText: "",
    createdAt: "2026-08-25T00:00:00.000Z",
    updatedAt: "2026-08-25T00:00:00.000Z",
    ...overrides,
  }
}

/** Compile-time + runtime contract checks used by `pnpm --dir frontend build`. */
export function assertPromptCompilerContract(): void {
  if (snapH3DurationSec(1) !== 2) throw new Error("duration snap 1 → 2")
  if (snapH3DurationSec(2) !== 2) throw new Error("duration snap 2 → 2")
  if (snapH3DurationSec(3) !== 3) throw new Error("duration snap 3 → 3")
  if (snapH3DurationSec(16) !== 15) throw new Error("duration snap 16 → 15")
  if (h3AlignedFrames(2) !== 56) throw new Error("2s should align to 56 frames")
  if (h3AlignedFrames(5) !== 124) throw new Error("5s should align to 124 frames")
  if (h3AlignedFrames(15) !== 362) throw new Error("15s should align to 362 frames")

  const project = sampleProject()
  const plan = buildReferencePlan(project, project.shots[0])
  if (plan.workflowId !== "minimax-h3-r2v") throw new Error("first frame + subjects must route R2V")
  if (plan.items.map((item) => item.role).join(",") !== "first_frame,subject,subject") {
    throw new Error("Picture order must be first frame then subjects")
  }
  if (plan.items.map((item) => item.pictureIndex).join(",") !== "1,2,3") {
    throw new Error("Picture indexes must be sequential")
  }
  const prompt = compileShotPrompt(project, project.shots[0], plan)
  const shotBody = prompt.split("\n\n").at(-1) || prompt
  if (!shotBody.includes("<Picture 2>") || shotBody.includes("@ref1")) {
    throw new Error("shot prompt body must expand @ref1 to Picture tags")
  }

  const t2v = sampleProject({
    refsMode: "refs_off",
    subjectSlots: createInitialSubjectSlots(),
    shots: [{ ...createEmptyShot(1, 0, 5), prompt: "空镜雨夜" }],
  })
  if (buildReferencePlan(t2v, t2v.shots[0]).workflowId !== "minimax-h3-t2v") {
    throw new Error("no refs should route T2V")
  }

  const i2v = sampleProject({
    refsMode: "refs_off",
    subjectSlots: createInitialSubjectSlots(),
    shots: [{
      ...createEmptyShot(1, 0, 5),
      firstFrameUrl: "data:image/png;base64,first",
      endFrameUrl: "data:image/png;base64,last",
      prompt: "首尾帧",
    }],
  })
  const i2vPlan = buildReferencePlan(i2v, i2v.shots[0])
  if (i2vPlan.workflowId !== "minimax-h3-i2v") throw new Error("first+last without subjects must route I2V")
  if (i2vPlan.items.map((item) => item.role).join(",") !== "first_frame,last_frame") {
    throw new Error("I2V plan must be first then last frame")
  }

  const clipOk = compileClipPrompt(sampleProject({
    shots: [
      { ...project.shots[0], durationSec: 5 },
      { ...createEmptyShot(2, 5, 5), prompt: "第二镜 @ref1" },
      { ...createEmptyShot(3, 10, 5), prompt: "第三镜" },
    ],
  }))
  if (!clipOk.allowed || clipOk.durationSec !== 15) throw new Error("15s clip must be allowed")
  if (!clipOk.prompt.includes("[Shot 3]")) throw new Error("clip prompt must list all shots")

  const clipRejected = compileClipPrompt(sampleProject({
    shots: [
      createEmptyShot(1, 0, 5),
      createEmptyShot(2, 5, 5),
      createEmptyShot(3, 10, 5),
      createEmptyShot(4, 15, 5),
    ],
  }))
  if (clipRejected.allowed) throw new Error("20s timeline must reject clip submit")

  const override = sampleProject({
    manualPromptOverrideEnabled: true,
    manualPromptOverrideText: "ONLY THIS SHOT PROMPT",
  })
  if (resolveShotSubmission(override, override.shots[0]).prompt !== "ONLY THIS SHOT PROMPT") {
    throw new Error("manual override must replace the submitted shot prompt")
  }
  const preview = resolveShotSubmission(project, project.shots[0], "preview")
  if (preview.quality !== "0.4" || preview.speed !== "fast" || preview.renderPass !== "preview") {
    throw new Error("preview pass must be 0.4 MP / 4-step turbo")
  }
  const hero = resolveShotSubmission(project, project.shots[0], "final")
  if (hero.quality !== "1.0" || hero.speed !== "balanced" || hero.renderPass !== "final") {
    throw new Error("final pass must be canvas 1.0 MP / 8-step turbo")
  }
  const hq = resolveShotSubmission(sampleProject({ finalQuality: "2.0" }), project.shots[0], "final")
  if (hq.quality !== "2.0") throw new Error("finalQuality 2.0 must submit 2.0 MP")
  const fromCanvas = sampleProject({ canvasTier: "past_native" })
  delete (fromCanvas as { finalQuality?: string }).finalQuality
  if (resolveShotSubmission(fromCanvas, fromCanvas.shots[0], "final").quality !== "2.0") {
    throw new Error("missing finalQuality must follow canvasTier")
  }
  const customPreview = resolveShotSubmission(sampleProject({ previewQuality: "1.0", previewSpeed: "balanced" }), project.shots[0], "preview")
  if (customPreview.quality !== "1.0" || customPreview.speed !== "balanced") {
    throw new Error("preview pass must honor project previewQuality/previewSpeed")
  }
  const customFinal = resolveShotSubmission(sampleProject({ finalQuality: "0.4", finalSpeed: "quality" }), project.shots[0], "final")
  if (customFinal.quality !== "0.4" || customFinal.speed !== "quality") {
    throw new Error("final pass must honor project finalQuality/finalSpeed")
  }

  const persisted = persistableDirectorProjects([{
    ...project,
    subjectSlots: [{ ...project.subjectSlots[0], file: new File(["x"], "ref.png", { type: "image/png" }), previewUrl: "blob:http://local/1" }],
    shots: [{ ...project.shots[0], firstFrameFile: new File(["y"], "first.png", { type: "image/png" }), firstFrameUrl: "data:image/png;base64,keep" }],
  }])
  if (persisted[0].subjectSlots[0].file) throw new Error("persisted slots must drop File")
  if (persisted[0].subjectSlots[0].previewUrl) throw new Error("blob preview URLs must not be stored")
  if (persisted[0].shots[0].firstFrameFile) throw new Error("persisted shots must drop File")
  if (persisted[0].shots[0].firstFrameUrl !== "data:image/png;base64,keep") throw new Error("data URLs must persist")

  if (shotStatusFromJob({ status: "queued", stage: "等待排队", progress: 0 }) !== "queued") {
    throw new Error("queued jobs with waiting stage stay queued")
  }
  if (shotStatusFromJob({ status: "queued", stage: "MiniMax H3 正在生成视频", progress: 0 }) !== "running") {
    throw new Error("queued snapshot with generating stage must surface as running")
  }
  if (shotStatusFromJob({ status: "running", stage: "正在准备任务", progress: 0 }) !== "running") {
    throw new Error("running jobs stay running even at 0%")
  }
  if (mergeDirectorStatus("running", "queued") !== "running") {
    throw new Error("stale queued list must not downgrade a running shot")
  }
  if (jobProgressFromJob({ status: "succeeded", progress: 0 }) !== 100) {
    throw new Error("succeeded jobs must report 100%")
  }
}

assertPromptCompilerContract()
