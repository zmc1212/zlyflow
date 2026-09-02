import {
  resolveTakeGenerationMeta,
  takeGenerationDiff,
  workflowFamilyLabel,
} from "./take-generation-params"
import type { ShotTake } from "./types"

function sampleTake(overrides: Partial<ShotTake> = {}): ShotTake {
  return {
    id: "job-1",
    takeNumber: 1,
    jobId: "job-1",
    status: "succeeded",
    progress: 100,
    createdAt: "2026-09-01T06:00:00.000Z",
    renderPass: "final",
    workflowId: "minimax-h3-t2v",
    videoWorkflowFamily: "official_h3",
    options: {
      aspect_ratio: "16:9",
      quality: "1.0",
      speed: "quality",
      weight_profile: "full",
      duration: 5,
    },
    ...overrides,
  }
}

const previewTake = sampleTake({
  id: "job-2",
  jobId: "job-2",
  takeNumber: 2,
  renderPass: "preview",
  workflowId: "minimax-h3-lightx2v-t2v",
  videoWorkflowFamily: "lightx2v",
  options: {
    aspect_ratio: "16:9",
    quality: "0.4",
    speed: "fast",
    weight_profile: "full",
    duration: 5,
  },
})

if (workflowFamilyLabel("official_h3") !== "MiniMax H3") {
  throw new Error("workflow family label mismatch")
}

const finalMeta = resolveTakeGenerationMeta(sampleTake())
if (!finalMeta.summary.includes("成片") || !finalMeta.summary.includes("1.0 MP")) {
  throw new Error("final take summary must include pass and quality")
}

const backfilled = resolveTakeGenerationMeta(
  sampleTake({ options: undefined, workflowId: undefined }),
  { mode: "minimax-h3-t2v", options: { quality: "1.0", speed: "quality", weight_profile: "full", duration: 5 } },
)
if (backfilled.options.quality !== "1.0" || backfilled.workflowId !== "minimax-h3-t2v") {
  throw new Error("job fallback must backfill take generation meta")
}

const diff = takeGenerationDiff(finalMeta, resolveTakeGenerationMeta(previewTake))
if (!diff.includes("档位") || !diff.includes("分辨率") || !diff.includes("生成速度")) {
  throw new Error("diff must highlight changed generation fields")
}

console.log("take-generation-params.test.ts passed")
