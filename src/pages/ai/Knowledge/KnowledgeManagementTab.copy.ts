/**
 * Page-local copy for the redesigned Knowledge page.
 * Shared strings stay in src/i18n/aiAdmin.ts; only new labels live here.
 */
export const knowledgePageCopy = {
  zh: {
    documentsAria: '知识文档列表',
    noChunksBody: '文档已入库，但还没有可检索的切片。可以在文档列表的操作列中对它执行“重新切片”。',
  },
  en: {
    documentsAria: 'Knowledge document list',
    noChunksBody: 'The document is stored but has no retrievable chunks yet. Run “Rechunk” on it from the document list.',
  },
};

export type KnowledgePageCopy = typeof knowledgePageCopy.zh;
