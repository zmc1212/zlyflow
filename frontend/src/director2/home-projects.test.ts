import { describe, expect, it } from "vitest"
import type { DirectorProjectListItem } from "../director/director-api"
import type { Director2Project } from "./api"
import {
  DEFAULT_HOME_PROJECT_FILTER,
  filterHomeProjects,
  homeProjectFilterEmptyCopy,
  homeProjectFilterLabel,
  homeProjectKindLabel,
  mergeHomeProjects,
  type HomeProjectItem,
} from "./home-projects"

function studio(partial: Partial<Director2Project> & Pick<Director2Project, "id" | "name" | "updated_at">): Director2Project {
  return {
    description: null,
    cover_url: null,
    status: "active",
    settings: null,
    extra: null,
    created_at: partial.updated_at,
    ...partial,
  }
}

function director(partial: Partial<DirectorProjectListItem> & Pick<DirectorProjectListItem, "id" | "title" | "kind" | "updated_at">): DirectorProjectListItem {
  return {
    summary: "",
    has_source_script: false,
    shot_count: 0,
    generated_count: 0,
    generation_status: "pending",
    revision: 1,
    content_revision: 1,
    created_at: partial.updated_at,
    ...partial,
  }
}

describe("director home project merge", () => {
  it("keeps studio projects and the two leftover director studios, drops recipe/timeline", () => {
    const merged = mergeHomeProjects(
      [studio({ id: "s1", name: "短剧", updated_at: "2026-09-19T12:00:00Z" })],
      [
        director({ id: "b1", title: "批量", kind: "batch_run", updated_at: "2026-09-19T13:00:00Z" }),
        director({ id: "r1", title: "复刻", kind: "shot_replication", updated_at: "2026-09-18T10:00:00Z" }),
        director({ id: "old", title: "九阶段", kind: "director_recipe", updated_at: "2026-09-20T10:00:00Z" }),
        director({ id: "tl", title: "时间轴", kind: "timeline", updated_at: "2026-09-21T10:00:00Z" }),
      ],
    )
    expect(merged.map((item) => item.id)).toEqual(["b1", "s1", "r1"])
    expect(merged.every((item) => String(item.kind) !== "director_recipe" && String(item.kind) !== "timeline")).toBe(true)
  })

  it("labels leftover studios for the recent-project chips", () => {
    expect(homeProjectKindLabel("studio")).toBe("创作项目")
    expect(homeProjectKindLabel("batch_run")).toBe("短视频批量")
    expect(homeProjectKindLabel("shot_replication")).toBe("参考片复刻")
  })

  it("defaults the recent-project filter to director studio projects", () => {
    expect(DEFAULT_HOME_PROJECT_FILTER).toBe("studio")
    expect(homeProjectFilterLabel("studio")).toBe("导演创作")
    expect(homeProjectFilterLabel("all")).toBe("全部")
    const items: HomeProjectItem[] = [
      { id: "s1", source: "studio", kind: "studio", title: "短剧", summary: "", updated_at: "2026-09-19T12:00:00Z" },
      { id: "b1", source: "director", kind: "batch_run", title: "批量", summary: "", updated_at: "2026-09-19T13:00:00Z" },
    ]
    expect(filterHomeProjects(items, "studio").map((item) => item.id)).toEqual(["s1"])
    expect(filterHomeProjects(items, "batch_run").map((item) => item.id)).toEqual(["b1"])
    expect(filterHomeProjects(items, "all").map((item) => item.id)).toEqual(["s1", "b1"])
    expect(homeProjectFilterEmptyCopy("studio").title).toBe("还没有导演创作项目")
  })

  it("searches titles and summaries while respecting the selected project type", () => {
    const items: HomeProjectItem[] = [
      { id: "s1", source: "studio", kind: "studio", title: "雨夜来信", summary: "H3 真人短剧", updated_at: "2026-10-23" },
      { id: "s2", source: "studio", kind: "studio", title: "未命名导演工程", summary: "", updated_at: "2026-10-22" },
      { id: "b1", source: "director", kind: "batch_run", title: "雨夜主题", summary: "H3 批量制作", updated_at: "2026-10-21" },
    ]
    expect(filterHomeProjects(items, "studio", " 雨夜 ").map(item => item.id)).toEqual(["s1"])
    expect(filterHomeProjects(items, "all", "h3").map(item => item.id)).toEqual(["s1", "b1"])
    expect(filterHomeProjects(items, "studio", "   ").map(item => item.id)).toEqual(["s1", "s2"])
    expect(filterHomeProjects(items, "batch_run", "未命名")).toEqual([])
    expect(items.map(item => item.id)).toEqual(["s1", "s2", "b1"])
  })
})
