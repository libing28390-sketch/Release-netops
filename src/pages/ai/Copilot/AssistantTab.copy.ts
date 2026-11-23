/**
 * Page-local copy for new Copilot notices.  The rest of the Copilot page is
 * still written inline in Chinese; shared strings stay in src/i18n/aiAdmin.ts.
 */
export const copilotCopy = {
  noMatchCloudReference: '本地知识库没有匹配的文档。以下是模型给出的通用参考，未经本地知识库或官方文档验证，执行前请核对厂商文档。',
  noMatchWebReference: '本地知识库没有匹配的文档。以下内容依据公开网页整理，网页内容未经验证。',
  noMatchLocal: '本地知识库没有匹配的文档，未生成配置或命令。可以补充厂商、型号或版本后再问。',
  noMatchAria: '知识库未命中提示',
  retrievalRan: '已执行',
  notReported: '未上报',
  notCalled: '未调用',
};

export type CopilotCopy = typeof copilotCopy;
