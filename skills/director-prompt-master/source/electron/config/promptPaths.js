'use strict';

/**
 * 内置扩写模板：源码在 electron/config/prompts/*.js，开发和安装都走 require。
 * 打安装包时随 electron JS 一起加密进包，无需额外步骤。
 */
const TEMPLATES = {
  'h3-full-reference-rewrite.zh.md': require('./prompts/h3-full-reference-rewrite.zh'),
  'h3-full-reference-rewrite.en.md': require('./prompts/h3-full-reference-rewrite.en'),
  'h3-full-reference-rewrite.md': require('./prompts/h3-full-reference-rewrite'),
};

function readPromptMd(fileName) {
  const name = String(fileName || '').trim();
  const text = TEMPLATES[name];
  if (typeof text !== 'string' || !text.trim()) {
    throw new Error(
      `缺少 MiniMax 提示词模板「${name}」。请重新安装最新版本，或联系技术支持。`
    );
  }
  return text.trim();
}

module.exports = {
  readPromptMd,
};
