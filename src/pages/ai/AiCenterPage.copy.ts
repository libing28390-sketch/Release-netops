/**
 * Page-local copy for the AI Center shell (review item L6-e: per-page access).
 */
const zh = {
  forbiddenTitle: '没有访问这个页面的权限',
  forbiddenBody: (page: string, permission: string) => `“${page}”需要 ${permission} 权限。请联系管理员开通，或先使用你有权限的 AI 功能。`,
  forbiddenGoTo: (page: string) => `前往${page}`,
  noAccessTitle: '没有可用的 AI 中心页面',
  noAccessBody: '当前账号没有任何 AI 中心页面的权限，请联系管理员开通。',
  pages: {
    providers: 'Provider 供应商',
    models: '模型与路由',
    health: '健康与 SLA',
    prompts: 'Prompt 提示词',
    copilot: 'Copilot 对话',
    agents: 'Agent 注册表',
    knowledge: '知识库管理',
    'retrieval-test': '检索测试',
    catalog: '产品目录',
    governance: '变更治理',
    usage: 'Token 统计审计',
    security: 'AI 安全网关',
  } as Record<string, string>,
};

type AiCenterCopyShape = typeof zh;

const en: AiCenterCopyShape = {
  forbiddenTitle: 'You do not have access to this page',
  forbiddenBody: (page: string, permission: string) => `"${page}" requires the ${permission} permission. Ask an administrator for access, or use an AI feature you can access.`,
  forbiddenGoTo: (page: string) => `Go to ${page}`,
  noAccessTitle: 'No AI Center pages available',
  noAccessBody: 'Your account has no access to any AI Center page. Ask an administrator for access.',
  pages: {
    providers: 'Providers',
    models: 'Models & Routing',
    health: 'Health & SLA',
    prompts: 'Prompts',
    copilot: 'Copilot',
    agents: 'Agents',
    knowledge: 'Knowledge',
    'retrieval-test': 'Retrieval Test',
    catalog: 'Product Catalog',
    governance: 'Governance',
    usage: 'Token Usage',
    security: 'AI Security',
  },
};

export type AiCenterCopy = AiCenterCopyShape;

export const getAiCenterCopy = (language?: string): AiCenterCopy => (language === 'en' ? en : zh);
