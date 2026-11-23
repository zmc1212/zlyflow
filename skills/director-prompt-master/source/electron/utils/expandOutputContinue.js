'use strict';

const { getScenarioByPeId } = require('../config/minimaxScenarios/catalog');

const EXPAND_CONTINUE_MAX = 3;

const INCOMPLETE_EXPAND_WARNING =
  '输出可能未写完，请检查各组字段是否齐全（摘要 / 保留分析 / 详细描述 / 整体声景 / 非叙事配乐）。';

const GROUP_FIELDS = [
  { id: 'summary', zh: '摘要', en: 'summary' },
  { id: 'retention', zh: '保留分析', en: 'retention_analysis' },
  { id: 'detailed', zh: '详细描述', en: 'detailed_description' },
  { id: 'soundscape', zh: '整体声景', en: 'overall_soundscape' },
  { id: 'music', zh: '非叙事配乐', en: 'non_diegetic_music' },
];

const SUBJECT_FIELD = { id: 'subject', zh: '主体定义', en: 'subject_definitions' };

const FULL_REFERENCE_FIELDS = [SUBJECT_FIELD, ...GROUP_FIELDS];

function escapeRe (s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function labelRegex (field) {
  const names = [field.zh, field.en].filter(Boolean).map(escapeRe).join('|');
  return new RegExp(
    `(^|\\n)\\s*(?:#{1,3}\\s*)?(?:\\*\\*)?(?:${names})(?:\\*\\*)?\\s*[:：]`,
    'i'
  );
}

function hasLabel (text, field) {
  return labelRegex(field).test('\n' + String(text || ''));
}

function labelBodyLen (text, field) {
  const src = '\n' + String(text || '');
  const re = labelRegex(field);
  const m = re.exec(src);
  if (!m) return 0;
  const start = m.index + m[0].length;
  const rest = src.slice(start);
  const next = rest.search(/\n\s*(?:#{1,3}\s*)?(?:\*\*)?(?:[^\n]{1,40})(?:\*\*)?\s*[:：]/);
  const body = (next >= 0 ? rest.slice(0, next) : rest).trim();
  return body.length;
}

function isLengthFinish (reason) {
  const r = String(reason || '').toLowerCase().trim();
  return r === 'length' || r === 'max_tokens' || r === 'max_token' || r === 'limit';
}

function normalizeFinishReason (choiceOrReason) {
  if (choiceOrReason == null) return '';
  if (typeof choiceOrReason === 'string') return choiceOrReason;
  const c = choiceOrReason;
  return String(
    c.finish_reason ||
      c.finishReason ||
      c.stop_reason ||
      c.stopReason ||
      ''
  );
}

function resolveExpandOutputContract (info) {
  const peId = String((info && (info.peId || info.ruleId)) || '').trim();
  const scenario = peId ? getScenarioByPeId(peId) : null;
  const lang = String((info && info.outputLang) || 'zh').toLowerCase() === 'en' ? 'en' : 'zh';
  const form = (info && info.minimaxForm) || {};
  if (!scenario) {
    return { kind: 'none', lang };
  }
  if (scenario.outputMode === 'director_segments') {
    const n = Math.max(2, parseInt(String(form.segment_count || '4'), 10) || 4);
    return {
      kind: 'director_segments',
      lang,
      expectedGroups: n,
    };
  }
  if (scenario.outputMode === 'full_reference') {
    return { kind: 'full_reference', lang };
  }
  return { kind: 'loose', lang };
}

function splitDirectorGroups (text) {
  const src = String(text || '');
  const re = /={3,}\s*(?:提示词组|prompt\s*group)\s*(\d+)\s*={3,}/gi;
  const hits = [];
  let m;
  while ((m = re.exec(src))) {
    hits.push({ index: m.index, n: parseInt(m[1], 10) || hits.length + 1, end: m.index + m[0].length });
  }
  if (!hits.length) return [];
  return hits.map((h, i) => {
    const from = h.end;
    const to = i + 1 < hits.length ? hits[i + 1].index : src.length;
    return { n: h.n, body: src.slice(from, to) };
  });
}

function inspectExpandOutput (text, contract) {
  const src = String(text || '').trim();
  const kind = (contract && contract.kind) || 'none';
  if (!src) {
    return { complete: false, kind, groupsFound: 0, expectedGroups: 0, missing: ['empty'] };
  }
  if (kind === 'none' || kind === 'loose') {
    return { complete: true, kind, groupsFound: 0, expectedGroups: 0, missing: [] };
  }

  if (kind === 'full_reference') {
    const missing = FULL_REFERENCE_FIELDS.filter((f) => !hasLabel(src, f)).map((f) => f.id);
    const lastBody = labelBodyLen(src, GROUP_FIELDS[GROUP_FIELDS.length - 1]);
    if (lastBody < 2 && !missing.includes('music')) {
      missing.push('music_body');
    }
    return {
      complete: missing.length === 0,
      kind,
      groupsFound: missing.length === 0 ? 1 : 0,
      expectedGroups: 1,
      missing,
    };
  }

  const expectedGroups = (contract && contract.expectedGroups) || 0;
  const groups = splitDirectorGroups(src);
  const missing = [];
  if (!hasLabel(src, SUBJECT_FIELD)) {
    missing.push('subject');
  }
  if (groups.length < expectedGroups) {
    missing.push(`groups:${groups.length}/${expectedGroups}`);
  }
  for (const g of groups) {
    const lack = GROUP_FIELDS.filter((f) => !hasLabel(g.body, f)).map((f) => `${g.n}:${f.id}`);
    missing.push(...lack);
    if (lack.length === 0) {
      const lastBody = labelBodyLen(g.body, GROUP_FIELDS[GROUP_FIELDS.length - 1]);
      if (lastBody < 2) {
        missing.push(`${g.n}:music_body`);
      }
    }
  }
  return {
    complete: missing.length === 0 && groups.length >= expectedGroups,
    kind,
    groupsFound: groups.length,
    expectedGroups,
    missing,
  };
}

function shouldContinueExpand (finishReason, inspect) {
  if (inspect && inspect.complete === false) return true;
  return isLengthFinish(finishReason);
}

function mergeContinuedText (prev, next) {
  const a = String(prev || '').replace(/\s+$/, '');
  let b = String(next || '').replace(/^\s+/, '');
  if (!b) return a;
  if (!a) return b;
  b = b.replace(/^(?:好的[，,。.]|继续(?:输出|书写|写作)?[：:]|如下[：:])\s*/u, '');
  if (b.startsWith(a)) return b;
  const minOverlap = 12;
  const max = Math.min(a.length, 480);
  for (let n = max; n >= minOverlap; n -= 1) {
    const tail = a.slice(-n);
    const idx = b.indexOf(tail);
    if (idx === 0) {
      return a + b.slice(n);
    }
    if (idx > 0 && idx < 120) {
      return a + b.slice(idx + n);
    }
  }
  return a + (a.endsWith('\n') ? '' : '\n') + b;
}

function buildContinueUserMessage (partial, contract, inspect) {
  const lang = (contract && contract.lang) === 'en' ? 'en' : 'zh';
  const groupsFound = (inspect && inspect.groupsFound) || 0;
  const expected = (contract && contract.expectedGroups) || 0;
  if (lang === 'en') {
    let extra = 'Continue ONLY from the breakpoint. Do not repeat written text. No chat.';
    if (contract && contract.kind === 'director_segments') {
      extra += ` Need exactly ${expected} prompt groups. Each group must contain in order: summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music. Already have ${groupsFound} group(s).`;
    } else if (contract && contract.kind === 'full_reference') {
      extra +=
        ' Finish the six sections: subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music.';
    }
    return extra + '\n\nAlready written (do not rewrite):\n-----\n' + String(partial || '') + '\n-----\nContinue immediately after the last character.';
  }
  let extra = '请从断点继续写，不要重复已写内容，不要寒暄。';
  if (contract && contract.kind === 'director_segments') {
    extra += `需要恰好 ${expected} 组「提示词组」。每组按顺序包含：摘要 / 保留分析 / 详细描述 / 整体声景 / 非叙事配乐。目前已有 ${groupsFound} 组。`;
  } else if (contract && contract.kind === 'full_reference') {
    extra +=
      '请补全六段：主体定义 / 摘要 / 保留分析 / 详细描述 / 整体声景 / 非叙事配乐。';
  }
  return extra + '\n\n已写出（不要重写）：\n-----\n' + String(partial || '') + '\n-----\n请紧接着最后一个字符继续。';
}

/**
 * @param {{
 *   initialMessages: Array<{role:string, content:any}>,
 *   generate: (messages:any[]) => Promise<{ text:string, finishReason?:string, cancelled?:boolean, error?:string }>,
 *   contract: object,
 *   maxContinues?: number,
 *   shouldAbort?: () => boolean,
 *   onContinue?: (n:number, max:number, inspect:object) => void,
 *   strip?: (text:string) => string,
 * }} opts
 */
async function continueExpandUntilComplete (opts) {
  const maxContinues = opts.maxContinues != null ? opts.maxContinues : EXPAND_CONTINUE_MAX;
  const contract = opts.contract || { kind: 'none' };
  const strip = typeof opts.strip === 'function' ? opts.strip : (t) => String(t || '').trim();
  const initial = Array.isArray(opts.initialMessages) ? opts.initialMessages.slice() : [];

  let assembled = '';
  let lastReason = '';
  let continues = 0;
  let messages = initial;
  let inspect = inspectExpandOutput('', contract);

  while (true) {
    if (opts.shouldAbort && opts.shouldAbort()) {
      return {
        cancelled: true,
        text: assembled,
        inspect,
        finishReason: lastReason,
        continued: continues,
        incomplete: true,
      };
    }
    const result = await opts.generate(messages);
    if (result && result.cancelled) {
      return {
        cancelled: true,
        text: assembled,
        inspect,
        finishReason: lastReason,
        continued: continues,
        incomplete: true,
      };
    }
    if (result && result.error && !String(result.text || '').trim()) {
      if (assembled) {
        inspect = inspectExpandOutput(assembled, contract);
        return {
          text: assembled,
          inspect,
          finishReason: lastReason,
          continued: continues,
          incomplete: shouldContinueExpand(lastReason, inspect),
          warning: INCOMPLETE_EXPAND_WARNING,
          generateError: result.error,
        };
      }
      return { error: result.error, text: '', inspect, continued: 0, incomplete: true };
    }
    const chunk = strip(result && result.text);
    lastReason = (result && result.finishReason) || '';
    assembled = assembled ? mergeContinuedText(assembled, chunk) : chunk;
    inspect = inspectExpandOutput(assembled, contract);
    const more = shouldContinueExpand(lastReason, inspect);
    if (!more || continues >= maxContinues) {
      const incomplete = more;
      return {
        text: assembled,
        inspect,
        finishReason: lastReason,
        continued: continues,
        incomplete,
        warning: incomplete ? INCOMPLETE_EXPAND_WARNING : '',
      };
    }
    continues += 1;
    if (opts.onContinue) {
      opts.onContinue(continues, maxContinues, inspect);
    }
    messages = initial.concat([
      { role: 'assistant', content: assembled },
      { role: 'user', content: buildContinueUserMessage(assembled, contract, inspect) },
    ]);
  }
}

module.exports = {
  EXPAND_CONTINUE_MAX,
  INCOMPLETE_EXPAND_WARNING,
  GROUP_FIELDS,
  SUBJECT_FIELD,
  isLengthFinish,
  normalizeFinishReason,
  resolveExpandOutputContract,
  inspectExpandOutput,
  shouldContinueExpand,
  mergeContinuedText,
  buildContinueUserMessage,
  continueExpandUntilComplete,
  hasLabel,
};
