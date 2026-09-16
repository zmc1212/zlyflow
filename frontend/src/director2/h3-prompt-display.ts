const SECTION_KEYS = [
  "subject_definitions",
  "summary",
  "retention_analysis",
  "detailed_description",
  "overall_soundscape",
  "non_diegetic_music",
  "主体定义",
  "摘要",
  "保留分析",
  "详细描述",
  "整体声景",
  "非叙事配乐",
  "画面广告文案",
].join("|")

const SECTION_RE = new RegExp(
  `(?:^|\\n)(?:##\\s*|###\\s*)?(${SECTION_KEYS}):`,
  "gm",
)

export function escapeHtml(text: string): string {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

export function renderH3PromptHtml(text: string): string {
  if (!text) return ""
  return escapeHtml(text)
    .replace(SECTION_RE, '<br><span class="h3-section-key">$1:</span>')
    .replace(/&lt;Picture (\d+)&gt;/g, '<span class="h3-ref-chip-inline"><span class="h3-chip-dot"></span>图片$1</span>')
    .replace(/&lt;Subject (\d+)&gt;/g, '<span class="h3-subject-tag">&lt;Subject $1&gt;</span>')
    .replace(/\[Shot (\d+)\]/g, '<span class="h3-shot-tag">[Shot $1]</span>')
    .replace(/\n/g, "<br>")
    .replace(/^(?:<br>)+/, "")
}
