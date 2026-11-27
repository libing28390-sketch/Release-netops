/**
 * Page-local copy for the redesigned Prompt Center layout.
 *
 * Keys that already exist in `src/i18n/aiAdmin.ts` stay there; this file only
 * holds the new table/summary labels introduced by the redesign so the shared
 * dictionary is not edited concurrently.
 */
export const promptCenterCopy = {
  zh: {
    listAria: 'Prompt 模板列表',
    summaryAria: 'Prompt 概览',
    filterAria: '筛选 Prompt',
    loading: '正在加载 Prompt 模板…',
    colName: '名称 / 编码',
    colScene: '场景',
    colScope: '适用范围',
    colVariables: '变量',
    colVersion: '版本',
    colStatus: '状态',
    colParams: '参数',
    colUpdated: '更新时间',
    colActions: '操作',
    outputContract: '输出契约',
    rulesLabel: '模板维护约定',
  },
  en: {
    listAria: 'Prompt templates',
    summaryAria: 'Prompt summary',
    filterAria: 'Filter prompts',
    loading: 'Loading prompt templates…',
    colName: 'Name / code',
    colScene: 'Scene',
    colScope: 'Scope',
    colVariables: 'Variables',
    colVersion: 'Version',
    colStatus: 'Status',
    colParams: 'Parameters',
    colUpdated: 'Updated',
    colActions: 'Actions',
    outputContract: 'Output contract',
    rulesLabel: 'Template maintenance rules',
  },
} as const;

export type PromptCenterCopy = Record<keyof (typeof promptCenterCopy)['zh'], string>;

export function promptCenterText(language: string): PromptCenterCopy {
  return language === 'en' ? promptCenterCopy.en : promptCenterCopy.zh;
}
