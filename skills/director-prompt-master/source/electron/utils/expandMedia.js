'use strict';

const path = require('path');

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']);
const VIDEO_EXTS = new Set(['.mp4', '.mov', '.avi', '.mkv', '.webm']);
const AUDIO_EXTS = new Set(['.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg']);

const LEGACY_GATE_START = '<<<SKILL_GATE>>>';
const LEGACY_GATE_END = '<<<END_SKILL_GATE>>>';

/** H3 / Minimax 常见段落字段：强制「标签:」后换行，便于 textarea 阅读 */
const H3_FIELD_LABELS = [
  'integrated_multimodal_description',
  'overall_soundscape',
  'non_diegetic_music',
  'subject_definitions',
  'summary',
  'retention_analysis',
  'detailed_description',
];

const DELIVERABLE_FIELD_RE =
  /product_facts|narrative_spine|director_motion|english_copy|anchor_brief|beat_storyboard|video_prompt|master_prompt|h3_prompt|storyboard|prompt_package|integrated_multimodal|overall_soundscape|subject_definitions|制作简报|分镜|锚定|视频提示|叙事脊柱/i;

function classifyMediaPath(filePath) {
  const ext = path.extname(String(filePath || '')).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (VIDEO_EXTS.has(ext)) return 'video';
  if (AUDIO_EXTS.has(ext)) return 'audio';
  return 'file';
}

/**
 * 与前端 @ 提及、formatMediaListForPrompt 一致的编号规则。
 */
function enumerateTaggedMedia(mediaPaths) {
  const list = Array.isArray(mediaPaths) ? mediaPaths : [];
  const counts = { image: 0, video: 0, audio: 0, file: 0 };
  const items = [];
  for (const raw of list) {
    const p = String(raw || '').trim();
    if (!p) continue;
    const kind = classifyMediaPath(p);
    counts[kind] += 1;
    const n = counts[kind];
    let tag = `<File ${n}>`;
    if (kind === 'image') tag = `<Picture ${n}>`;
    else if (kind === 'video') tag = `<Video ${n}>`;
    else if (kind === 'audio') tag = `<Audio ${n}>`;
    items.push({
      path: p,
      kind,
      n,
      tag,
      base: path.basename(p),
    });
  }
  return items;
}

function normalizeOption(raw) {
  if (raw == null) return null;
  if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') {
    const s = String(raw).trim();
    return s ? { label: s, value: s } : null;
  }
  if (typeof raw === 'object') {
    const label = String(
      raw.label ?? raw.text ?? raw.name ?? raw.title ?? raw.value ?? raw.id ?? ''
    ).trim();
    const value = String(
      raw.value ?? raw.id ?? raw.label ?? raw.text ?? raw.name ?? ''
    ).trim();
    if (!label && !value) return null;
    return { label: label || value, value: value || label };
  }
  return null;
}

function fieldBody(rawField) {
  const f = rawField && typeof rawField === 'object' ? rawField : {};
  const fromValue = f.value != null ? String(f.value).trim() : '';
  if (fromValue) return fromValue;
  const fromDefault = f.default != null ? String(f.default).trim() : '';
  if (fromDefault && typeof f.default !== 'object') return fromDefault;
  if (f.default != null && typeof f.default === 'object') {
    const opt = normalizeOption(f.default);
    return opt ? opt.value : '';
  }
  return '';
}

function looksLikeFinalPackageGate(data) {
  const title = String((data && data.title) || '');
  const summary = String((data && data.summary) || '');
  if (
    /final\s*prompt\s*package|完整提示词包|最终提示词|prompt\s*package|complete\s*blueprint/i.test(
      `${title} ${summary}`
    )
  ) {
    return true;
  }
  const fields = Array.isArray(data && data.fields) ? data.fields : [];
  if (fields.length < 3) return false;
  let deliverableHits = 0;
  let longFilled = 0;
  for (const f of fields) {
    const key = `${f && f.id ? f.id : ''} ${f && f.label ? f.label : ''}`;
    if (DELIVERABLE_FIELD_RE.test(key)) deliverableHits += 1;
    if (fieldBody(f).length >= 80) longFilled += 1;
  }
  if (deliverableHits >= 2) return true;
  if (longFilled >= 3 && fields.length >= 4) return true;
  return false;
}

function formatFinalPackageFromGateData(data) {
  const lines = [];
  const title = String((data && data.title) || 'Prompt Package').trim();
  if (title) lines.push(`## ${title}`);
  const summary = String((data && data.summary) || '').trim();
  if (summary) lines.push('', summary);
  const fields = Array.isArray(data && data.fields) ? data.fields : [];
  for (const f of fields) {
    const label = String((f && (f.label || f.id)) || '').trim();
    const body = fieldBody(f);
    if (!label && !body) continue;
    lines.push('', `### ${label || 'Section'}`);
    if (body) {
      lines.push(body);
    } else if (f && f.type === 'select' && Array.isArray(f.options) && f.options.length) {
      const opt = normalizeOption(f.options[0]);
      if (opt) lines.push(opt.value);
    }
  }
  return lines.join('\n').trim();
}

function extractLegacyGateJson(text) {
  const s = String(text || '');
  const start = s.indexOf(LEGACY_GATE_START);
  const end = s.indexOf(LEGACY_GATE_END);
  if (start < 0 || end < 0 || end <= start) return null;
  const raw = s.slice(start + LEGACY_GATE_START.length, end).trim();
  try {
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object') return null;
    if (!Array.isArray(data.fields) || !data.fields.length) return null;
    return { data, start, end };
  } catch {
    return null;
  }
}

/**
 * 去掉遗留 <<<SKILL_GATE>>> 标记；若误包最终包则拆成正文。
 */
function unwrapLegacyGateOutput(text) {
  const raw = String(text || '');
  const extracted = extractLegacyGateJson(raw);
  if (extracted) {
    const { data, start, end } = extracted;
    if (looksLikeFinalPackageGate(data)) {
      return formatFinalPackageFromGateData(data);
    }
    const before = raw.slice(0, start).trim();
    const after = raw.slice(end + LEGACY_GATE_END.length).trim();
    const combined = [before, after].filter(Boolean).join('\n\n').trim();
    if (combined) return combined;
    const summary = String(data.summary || '').trim();
    if (summary) return summary;
  }
  const stripped = raw
    .replace(
      new RegExp(
        `${LEGACY_GATE_START.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]*?${LEGACY_GATE_END.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`,
        'g'
      ),
      ''
    )
    .trim();
  return stripped || raw.trim();
}

function looksLikeExpandPreambleBlock(head) {
  const t = String(head || '').trim();
  if (!t) return false;
  if (/^#{1,6}\s/.test(t)) return false;
  if (/^\*\*[^*]+\*\*/.test(t)) return false;
  if (
    /^(?:integrated_multimodal_description|overall_soundscape|subject_definitions|summary|detailed_description)\s*:/i.test(
      t
    )
  ) {
    return false;
  }
  return /^(根据已确认|问询历史|前置决策|现在进入|最终交付|以下是|为\s*\*?MiniMax|所有前置)/i.test(t);
}

function stripExpandFinalPreamble(text) {
  let s = String(text || '').trim();
  if (!s) return s;

  const hrSplit = s.split(/\n-{3,}\n/);
  if (hrSplit.length >= 2 && looksLikeExpandPreambleBlock(hrSplit[0])) {
    s = hrSplit.slice(1).join('\n---\n').trim();
  }

  const lines = s.split('\n');
  let start = 0;
  while (start < lines.length) {
    const line = lines[start].trim();
    if (!line) {
      start += 1;
      continue;
    }
    if (
      /^#{1,6}\s/.test(line) ||
      /^\*\*[^*]+\*\*/.test(line) ||
      /^[A-Za-z_][\w]*\s*:/.test(line)
    ) {
      break;
    }
    const isMeta = /^(根据已确认|问询历史|前置决策|现在进入|最终交付|以下是|为\s*\*?MiniMax|所有前置)/i.test(
      line
    );
    if (!isMeta) break;
    start += 1;
  }
  if (start > 0 && start < lines.length) {
    s = lines.slice(start).join('\n').trim();
  }

  return s;
}

function normalizeMediaExpandOutput(text) {
  let s = unwrapLegacyGateOutput(text);
  s = stripExpandFinalPreamble(s);
  if (!s) return s;
  const labelAlt = H3_FIELD_LABELS.map((x) => x.replace(/_/g, '[_]?')).join('|');
  const re = new RegExp(`^((?:${labelAlt}))\\s*:\\s*(?=\\S)`, 'gim');
  s = s.replace(re, '$1:\n');
  s = s.replace(/\n{3,}/g, '\n\n');
  return s.trim();
}

module.exports = {
  IMAGE_EXTS,
  VIDEO_EXTS,
  AUDIO_EXTS,
  H3_FIELD_LABELS,
  LEGACY_GATE_START,
  LEGACY_GATE_END,
  classifyMediaPath,
  enumerateTaggedMedia,
  unwrapLegacyGateOutput,
  stripExpandFinalPreamble,
  normalizeMediaExpandOutput,
  looksLikeFinalPackageGate,
  formatFinalPackageFromGateData,
};
