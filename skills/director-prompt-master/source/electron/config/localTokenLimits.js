'use strict';

/** 本地模型 token 相关默认值（与设置项未配置时一致） */
const DEFAULT_LOCAL_TOKEN_LIMITS = {
  expandMax: 8192,
  reverseMax: 1024,
  mediaExpandMin: 4096,
  ctxSize: 8192,
};

const SETTING_KEYS = {
  expandMax: 'pm_local_expand_max_tokens',
  reverseMax: 'pm_local_reverse_max_tokens',
  mediaExpandMin: 'pm_local_media_expand_min_tokens',
  ctxSize: 'pm_local_ctx_size',
};

const BOUNDS = {
  expandMax: { min: 128, max: 16384 },
  reverseMax: { min: 128, max: 8192 },
  mediaExpandMin: { min: 512, max: 16384 },
  ctxSize: { min: 0, max: 131072 },
};

function parseLimitSetting(raw, fallback, min, max) {
  if (raw == null || String(raw).trim() === '') {
    return fallback;
  }
  const n = parseInt(String(raw).trim(), 10);
  if (Number.isNaN(n)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, n));
}

/**
 * @param {Partial<typeof DEFAULT_LOCAL_TOKEN_LIMITS>} raw
 * @returns {typeof DEFAULT_LOCAL_TOKEN_LIMITS}
 */
function normalizeLocalTokenLimits(raw) {
  const src = raw || {};
  return {
    expandMax: parseLimitSetting(
      src.expandMax,
      DEFAULT_LOCAL_TOKEN_LIMITS.expandMax,
      BOUNDS.expandMax.min,
      BOUNDS.expandMax.max
    ),
    reverseMax: parseLimitSetting(
      src.reverseMax,
      DEFAULT_LOCAL_TOKEN_LIMITS.reverseMax,
      BOUNDS.reverseMax.min,
      BOUNDS.reverseMax.max
    ),
    mediaExpandMin: parseLimitSetting(
      src.mediaExpandMin,
      DEFAULT_LOCAL_TOKEN_LIMITS.mediaExpandMin,
      BOUNDS.mediaExpandMin.min,
      BOUNDS.mediaExpandMin.max
    ),
    ctxSize: parseLimitSetting(
      src.ctxSize,
      DEFAULT_LOCAL_TOKEN_LIMITS.ctxSize,
      BOUNDS.ctxSize.min,
      BOUNDS.ctxSize.max
    ),
  };
}

/**
 * @param {(key: string) => string} getSetting
 */
function readLocalTokenLimits(getSetting) {
  const get = typeof getSetting === 'function' ? getSetting : () => '';
  return normalizeLocalTokenLimits({
    expandMax: get(SETTING_KEYS.expandMax),
    reverseMax: get(SETTING_KEYS.reverseMax),
    mediaExpandMin: get(SETTING_KEYS.mediaExpandMin),
    ctxSize: get(SETTING_KEYS.ctxSize),
  });
}

function readLocalTokenLimitsFromSettingsService() {
  const Services = require('ee-core/services');
  const settings = Services.get('settings');
  return readLocalTokenLimits((key) => {
    const row = settings.getData(key);
    return row && row.value != null ? String(row.value) : '';
  });
}

module.exports = {
  DEFAULT_LOCAL_TOKEN_LIMITS,
  SETTING_KEYS,
  BOUNDS,
  parseLimitSetting,
  normalizeLocalTokenLimits,
  readLocalTokenLimits,
  readLocalTokenLimitsFromSettingsService,
};
