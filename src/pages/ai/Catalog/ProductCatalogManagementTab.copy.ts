/**
 * Page-local copy for the redesigned Product Catalog page.
 *
 * Shared admin copy lives in src/i18n/aiAdmin.ts (owned by another task);
 * strings that only exist because of the new layout are kept here.
 */
export const catalogPageCopy = {
  zh: {
    summaryLabel: '产品目录概况',
    modelsTotal: '个型号（当前筛选）',
    aliasesTotal: '个别名（当前筛选）',
    conflicts: '个别名冲突待复核',
    noConflicts: '无别名冲突',
    seedMode: '官方种子（只读）',
    customMode: '官方 + 自定义',
    infoLabel: '目录说明',
    emptyModelsTitle: '没有匹配的型号',
    emptyModelsBody: '调整分类浏览或筛选条件后再试；管理员可以新增自定义型号。',
    emptyAliasesTitle: '没有匹配的别名',
    emptyAliasesBody: '调整搜索词或别名类型后再试。',
    hierarchyCount: '项',
  },
  en: {
    summaryLabel: 'Product catalog overview',
    modelsTotal: 'models (current filter)',
    aliasesTotal: 'aliases (current filter)',
    conflicts: 'alias conflicts pending review',
    noConflicts: 'No alias conflicts',
    seedMode: 'Official seed (read-only)',
    customMode: 'Official + custom',
    infoLabel: 'About the catalog',
    emptyModelsTitle: 'No matching models',
    emptyModelsBody: 'Adjust the hierarchy or filters; administrators can add a custom model.',
    emptyAliasesTitle: 'No matching aliases',
    emptyAliasesBody: 'Adjust the search text or alias kind.',
    hierarchyCount: 'items',
  },
} as const;

export type CatalogPageCopy = (typeof catalogPageCopy)['zh'];

export function catalogCopy(language: string | undefined): CatalogPageCopy {
  return language === 'zh' ? catalogPageCopy.zh : (catalogPageCopy.en as unknown as CatalogPageCopy);
}
