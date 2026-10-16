import type { AlertRuleSettings } from '../types';
import type { TableExportData } from '../components/ui/TableExportMenu';
import {
  alertRuleScopeSummary,
  formatTs,
  metricTypeLabel,
  normalizeAlertRuleNotificationChannels,
  scopeTypeLabel,
  severityLabel,
} from './alertManagementShared';

const isHostMetric = (metricType: string) => metricType.startsWith('host_');
const isServerMetric = (metricType: string) => metricType.startsWith('srv_');

export const getAlertRulesExportHeaders = (language: string) => language === 'zh'
  ? ['规则名称', '监控类型', '采集来源', '模板分组', '范围类型', '范围值', '阈值', '持续时间', '级别', '通知方式', '通知组', '状态', '执行器', '更新时间']
  : ['Rule', 'Metric', 'Collector', 'Template section', 'Scope type', 'Scope value', 'Threshold', 'Duration', 'Severity', 'Notification channels', 'Notification groups', 'Status', 'Executor', 'Updated'];

export function buildAlertRulesExportData(
  rules: AlertRuleSettings[],
  language: string,
  channelLabel: (channel: string) => string,
): TableExportData {
  const zh = language === 'zh';
  return {
    headers: getAlertRulesExportHeaders(language),
    rows: rules.map((rule) => {
      const collectionLabel = rule.collection
        ? (zh ? rule.collection.collection_label : (rule.collection.collection_label_en || rule.collection.collection_label))
        : (zh ? '未定义' : 'Undefined');
      const hostMetric = isHostMetric(rule.metric_type);
      return [
        rule.name || '',
        metricTypeLabel(rule.metric_type, language),
        collectionLabel,
        rule.collection?.template_section || '—',
        scopeTypeLabel(rule.scope_type, language),
        alertRuleScopeSummary(rule.scope_type, rule.scope_value || '', rule.scope_match_mode || 'exact', language),
        rule.threshold != null ? `> ${rule.threshold}%` : (zh ? '状态型' : 'State'),
        rule.for_duration_seconds > 0
          ? (rule.for_duration_seconds >= 60 ? `${Math.floor(rule.for_duration_seconds / 60)}m` : `${rule.for_duration_seconds}s`)
          : '—',
        severityLabel(rule.severity, language),
        hostMetric
          ? (zh ? '仅用于健康状态' : 'Health status only')
          : normalizeAlertRuleNotificationChannels(rule.notification_channels).map(channelLabel).join(', '),
        hostMetric ? '' : (rule.notification_group_names || []).join(', '),
        rule.enabled ? (zh ? '启用' : 'Enabled') : (zh ? '停用' : 'Disabled'),
        rule.rule_supported === false || isServerMetric(rule.metric_type)
          ? (zh ? '未接入' : 'Unavailable')
          : (zh ? '已接入' : 'Available'),
        formatTs(rule.updated_at || rule.created_at),
      ];
    }),
  };
}
