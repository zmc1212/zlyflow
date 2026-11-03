import { beforeEach, describe, expect, it, vi } from "vitest"
import { getProject } from "./api"
import { projectVideoPreferences, projectVideoResolution } from "./project-video-resolution"

vi.mock("./api", () => ({ getProject: vi.fn() }))

describe("project video preferences", () => {
  beforeEach(() => vi.resetAllMocks())

  it("carries the home portrait ratio even without a resolution choice", async () => {
    vi.mocked(getProject).mockResolvedValue({ extra: { workshop_aspect_ratio: "9:16" } } as unknown as Awaited<ReturnType<typeof getProject>>)
    expect(await projectVideoPreferences("p")).toEqual({ resolution: null, aspectRatio: "9:16" })
  })

  it("reads nested project settings and preserves the resolution API", async () => {
    vi.mocked(getProject).mockResolvedValue({ settings: { extra: { workshop_aspect_ratio: "16:9", video_resolution: "2k" } } } as unknown as Awaited<ReturnType<typeof getProject>>)
    expect(await projectVideoPreferences("p")).toEqual({ resolution: { value: "2k", label: "2K" }, aspectRatio: "16:9" })
    expect(await projectVideoResolution("p")).toEqual({ value: "2k", label: "2K" })
  })

  it("keeps local defaults usable when metadata cannot be loaded", async () => {
    vi.mocked(getProject).mockRejectedValue(new Error("offline"))
    expect(await projectVideoPreferences("p")).toBeNull()
  })
})
