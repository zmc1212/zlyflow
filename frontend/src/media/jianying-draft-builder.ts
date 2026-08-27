import JSZip from "jszip"
import { createLocalId } from "../lib/utils"

export interface JianyingMediaItem {
  id: string
  title: string
  kind: "video" | "image"
  path: string
  url: string
  durationSeconds?: number
}

export interface JianyingDraftOptions {
  draftName: string
  aspectRatio: "16:9" | "9:16" | "1:1" | "4:3" | "21:9"
  fps?: number
}

const ASPECT_RATIO_RESOLUTIONS: Record<string, { width: number; height: number; ratio: string }> = {
  "16:9": { width: 1920, height: 1080, ratio: "16:9" },
  "9:16": { width: 1080, height: 1920, ratio: "9:16" },
  "1:1": { width: 1080, height: 1080, ratio: "1:1" },
  "4:3": { width: 1440, height: 1080, ratio: "4:3" },
  "21:9": { width: 2560, height: 1080, ratio: "21:9" },
}

/**
 * 构造剪映 draft_meta_info.json
 */
export function buildJianyingDraftMetaInfo(options: JianyingDraftOptions, draftId: string) {
  const nowUs = Date.now() * 1000
  return {
    draft_id: draftId,
    draft_name: options.draftName || "ZLY_Studio_草稿",
    draft_fold_path: "",
    draft_timeline_materials_size_: 0,
    tm_draft_create: nowUs,
    tm_draft_modified: nowUs,
    draft_root_path: "",
    draft_removable_storage_device: "",
  }
}

/**
 * 构造剪映 draft_content.json
 */
export function buildJianyingDraftContent(
  items: JianyingMediaItem[],
  options: JianyingDraftOptions,
  draftId: string,
) {
  const resolution = ASPECT_RATIO_RESOLUTIONS[options.aspectRatio] ?? ASPECT_RATIO_RESOLUTIONS["16:9"]
  const fps = options.fps ?? 30.0

  const videoMaterials: Record<string, unknown>[] = []
  const speedMaterials: Record<string, unknown>[] = []
  const canvasMaterials: Record<string, unknown>[] = []
  const segments: Record<string, unknown>[] = []

  let currentTimelinePositionUs = 0

  items.forEach((item, index) => {
    const materialId = createLocalId()
    const speedId = createLocalId()
    const canvasId = createLocalId()
    const segmentId = createLocalId()

    // 默认时长：视频 5 秒（若有解析则用实际时长），图片默认 3 秒（3_000_000 微秒）
    const durationSeconds = item.durationSeconds && item.durationSeconds > 0
      ? item.durationSeconds
      : item.kind === "image" ? 3.0 : 5.0
    const durationUs = Math.round(durationSeconds * 1_000_000)

    videoMaterials.push({
      category_id: "",
      category_name: "local",
      check_flag: 63487,
      crop: {
        lower_left_x: 0.0,
        lower_left_y: 1.0,
        lower_right_x: 1.0,
        lower_right_y: 1.0,
        upper_left_x: 0.0,
        upper_left_y: 0.0,
        upper_right_x: 1.0,
        upper_right_y: 0.0,
      },
      crop_ratio: "free",
      crop_scale: 1.0,
      duration: durationUs,
      extra_type_option: 0,
      formula_id: "",
      id: materialId,
      intensifies_audio_path: "",
      is_ai_generate_content: true,
      is_unified_beauty_mode: false,
      material_name: item.title || `素材_${index + 1}.${item.kind === "image" ? "png" : "mp4"}`,
      path: item.path || "",
      type: item.kind === "image" ? "photo" : "video",
    })

    speedMaterials.push({
      curve_speed: null,
      id: speedId,
      mode: 0,
      speed: 1.0,
      type: "speed",
    })

    canvasMaterials.push({
      blur: 0.0,
      color: "",
      id: canvasId,
      image: "",
      image_id: "",
      image_name: "",
      source_platform_type: 0,
      team_id: "",
      type: "canvas_color",
    })

    segments.push({
      enable_adjust: true,
      enable_color_curves: true,
      enable_color_wheels: true,
      enable_lut: true,
      enable_smart_color_adjust: false,
      extra_material_refs: [speedId, canvasId],
      id: segmentId,
      material_id: materialId,
      render_index: index,
      source_timerange: {
        duration: durationUs,
        start: 0,
      },
      speed: 1.0,
      target_timerange: {
        duration: durationUs,
        start: currentTimelinePositionUs,
      },
      volume: 1.0,
    })

    currentTimelinePositionUs += durationUs
  })

  const trackId = createLocalId()

  return {
    canvas_config: {
      height: resolution.height,
      ratio: resolution.ratio,
      width: resolution.width,
    },
    duration: currentTimelinePositionUs,
    fps,
    materials: {
      videos: videoMaterials,
      speeds: speedMaterials,
      canvases: canvasMaterials,
      audios: [],
      transitions: [],
      stickers: [],
      texts: [],
      effects: [],
    },
    tracks: [
      {
        attribute: 0,
        flag: 0,
        id: trackId,
        is_default_name: true,
        name: "主视频轨",
        segments,
        type: "video",
      },
    ],
    version: 3000000,
  }
}

/**
 * 打包并下载剪映草稿 ZIP 压缩包
 */
export async function exportJianyingDraftZip(
  items: JianyingMediaItem[],
  options: JianyingDraftOptions,
): Promise<void> {
  const draftId = createLocalId()
  const metaInfo = buildJianyingDraftMetaInfo(options, draftId)
  const content = buildJianyingDraftContent(items, options, draftId)

  const zip = new JSZip()
  const folderName = options.draftName || `Jianying_Draft_${Date.now()}`
  const folder = zip.folder(folderName) ?? zip

  folder.file("draft_meta_info.json", JSON.stringify(metaInfo, null, 2))
  folder.file("draft_content.json", JSON.stringify(content, null, 2))

  // 生成一个使用说明 README.txt
  const readmeText = `剪映电脑版草稿使用说明：
1. 将此文件夹 "${folderName}" 解压或复制到剪映的草稿工程目录中：
   Windows 默认路径：%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\
2. 重新启动或打开剪映电脑版，即可在首页“最近草稿”中看到此工程。
3. 如果素材提示文件丢失，请在剪映中点击“重新定位”选择本地素材，或从工作台下载素材到同一路径。
`
  folder.file("草稿使用说明.txt", readmeText)

  const blob = await zip.generateAsync({ type: "blob" })
  downloadBlob(blob, `${folderName}.zip`)
}

/**
 * 单独下载 draft_content.json 与 draft_meta_info.json
 */
export function downloadJianyingJsonFiles(
  items: JianyingMediaItem[],
  options: JianyingDraftOptions,
): void {
  const draftId = createLocalId()
  const metaInfo = buildJianyingDraftMetaInfo(options, draftId)
  const content = buildJianyingDraftContent(items, options, draftId)

  downloadBlob(
    new Blob([JSON.stringify(metaInfo, null, 2)], { type: "application/json" }),
    "draft_meta_info.json",
  )
  downloadBlob(
    new Blob([JSON.stringify(content, null, 2)], { type: "application/json" }),
    "draft_content.json",
  )
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
