/** Page-local copy for the redesigned health page (not in aiAdmin.ts). */
export const healthPageCopy = {
  zh: {
    description: '按天汇总各模型的健康探测结果，用于判断可用性和 SLA。',
    info: '每次健康探测通过与生产流量相同的安全网关发出一条固定的公开测试消息。每天的状态取当天探测结果：全部成功为正常，部分失败为降级，全部失败为异常。',
    infoLabel: '健康探测说明',
    summaryLabel: '健康概览',
    services: '个模型',
    availability: '可用率',
    avgLatency: '平均延迟',
    checks: '次探测',
    failures: '次失败',
    emptyDescription: '启用对话或推理模型后，这里会显示它们的探测历史。',
    never: '从未探测',
    backoff: (name: string) => `${name} 当前处于健康探测退避窗口，请稍后再试`,
  },
  en: {
    description: 'Daily health-probe results per model, for availability and SLA tracking.',
    info: 'Each probe sends one fixed public test message through the same security gateway as production traffic. A day is healthy when all probes succeed, degraded when some fail, unhealthy when all fail.',
    infoLabel: 'About health probes',
    summaryLabel: 'Health overview',
    services: 'models',
    availability: 'availability',
    avgLatency: 'avg latency',
    checks: 'probes',
    failures: 'failures',
    emptyDescription: 'Enable a chat or reasoning model to see its probe history here.',
    never: 'Never probed',
    backoff: (name: string) => `${name} is in the health-check backoff window; please retry shortly`,
  },
} as const;

export type HealthPageCopy = (typeof healthPageCopy)['zh'];
