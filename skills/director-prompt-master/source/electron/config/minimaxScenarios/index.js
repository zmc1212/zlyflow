'use strict';

const { ALL_SUBJECT_DOMAIN_IDS } = require('../promptEngineeringTaxonomy');
const { listScenarios, getScenarioById, getScenarioByPeId } = require('./catalog');
const {
  resolveMinimaxScenarioExpand,
  isMinimaxScenarioProfile,
  normalizeForm,
  fieldVisible,
} = require('./assemble');

function buildMinimaxScenarioProfiles() {
  return listScenarios().map((s) => ({
    id: s.peId,
    kind: 'expand',
    builtin: true,
    builtinKey: s.builtinKey,
    name: s.name,
    category: '视频 / MiniMax',
    description: s.description,
    systemPrompt: '',
    userPromptTemplate: '',
    enabled: true,
    sort: s.sort,
    outputFormat: 'minimax',
    tags: ['扩写', '视频', 'MiniMax', 'H3', s.id],
    subjectDomains: ALL_SUBJECT_DOMAIN_IDS,
    mediaExpandLayout: true,
    minimaxScenarioId: s.id,
    formFields: s.formFields || [],
    outputMode: s.outputMode,
  }));
}

function getFormFieldsForPeId(peId) {
  const s = getScenarioByPeId(peId);
  return (s && s.formFields) || [];
}

function defaultFormForPeId(peId) {
  const s = getScenarioByPeId(peId);
  if (!s) return {};
  return normalizeForm(s, {});
}

module.exports = {
  buildMinimaxScenarioProfiles,
  getScenarioById,
  getScenarioByPeId,
  listScenarios,
  resolveMinimaxScenarioExpand,
  isMinimaxScenarioProfile,
  getFormFieldsForPeId,
  defaultFormForPeId,
  fieldVisible,
  normalizeForm,
};
