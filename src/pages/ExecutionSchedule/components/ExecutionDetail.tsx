import { DataTable } from '../../../components/DataTable';
import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  X, Activity, RotateCcw, AlertTriangle, Search, FileText,
  FileJson, ChevronRight, Loader2, Table2, Copy, Check, Download,
} from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer } from 'recharts';
import OutputActions from '../../../components/OutputActions';
import { ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';
import { TableExportMenu } from '../../../components/ui/TableExportMenu';
import Pagination from '../../../components/Pagination';
import type { UnifiedExecutionLog, InspDetailTab, PlaybookExecutionApproval, ConfigBackupRunDetail, BackupDetailStatus } from '../types';
import type { Device } from '../../../types';
import { splitOutputByCommand, downloadInspJSON } from '../helpers';
import { buildExecutionSnapshotExportData, getExecutionSnapshotCells } from '../executionSnapshotExport';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';

const stripLinuxHealthRating = (output: string) => output
  .split(/\r?\n/)
  .filter((line) => !/^\s*(?:综合健康评级|overall health rating)\s*[:：]/i.test(line))
  .join('\n');

type InspectionHealthKind = 'healthy' | 'warning' | 'critical' | 'not_collected' | 'unknown';

const normalizeInspectionHealth = (value: unknown): InspectionHealthKind => {
  const status = String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (['healthy', 'success', 'ok', 'normal', 'passed', 'pass'].includes(status)) return 'healthy';
  if (['warning', 'warn', 'degraded'].includes(status)) return 'warning';
  if (['critical', 'error', 'failed', 'failure', 'unhealthy', 'down', 'offline'].includes(status)) return 'critical';
  if (['not_collected', 'unavailable', 'unchecked'].includes(status)) return 'not_collected';
  return 'unknown';
};

const parseInspectionJson = <T,>(value: unknown, fallback: T): T => {
  if (typeof value !== 'string') return (value as T) ?? fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

const getInspectionIssueLabel = (status: InspectionHealthKind, zh: boolean): string => {
  if (status === 'healthy') return zh ? '运行正常' : 'Healthy';
  if (status === 'warning') return zh ? '需要关注' : 'Warning';
  if (status === 'critical') return zh ? '需要处理' : 'Critical';
  if (status === 'not_collected') return zh ? '未采集' : 'Not collected';
  return zh ? '状态未知' : 'Unknown';
};

const normalizeConnectivity = (value: unknown): InspectionHealthKind => {
  if (value === null || value === undefined || String(value).trim() === '') return 'not_collected';
  if (value === true || value === 1 || String(value).trim() === '1') return 'healthy';
  if (value === false || value === 0 || String(value).trim() === '0') return 'critical';
  return normalizeInspectionHealth(value);
};

const getConnectivityLabel = (status: InspectionHealthKind, zh: boolean): string => {
  if (status === 'healthy') return 'OK';
  if (status === 'critical') return 'FAIL';
  if (status === 'warning') return 'WARN';
  if (status === 'not_collected') return zh ? '未采集' : 'NOT COLLECTED';
  return zh ? '未知' : 'UNKNOWN';
};

const getConnectivityTone = (status: InspectionHealthKind): string => {
  if (status === 'healthy') return 'text-emerald-400';
  if (status === 'warning') return 'text-amber-400';
  if (status === 'critical') return 'text-red-400';
  return 'text-slate-400';
};

const getMetricValueStatus = (
  key: string,
  value: unknown,
  evaluatedStatus: unknown,
  expectedValue?: unknown,
  category?: unknown,
): InspectionHealthKind => {
  const componentState = /_(fan|psu)$/i.test(key);
  const rawValue = value && typeof value === 'object' ? (value as any).value : value;
  const normalizedValue = String(rawValue ?? '').trim().toLowerCase();
  const explicitStatus = normalizeInspectionHealth(evaluatedStatus);
  const hasExplicitUnknownStatus = evaluatedStatus !== null && evaluatedStatus !== undefined
    && String(evaluatedStatus).trim() !== '' && explicitStatus === 'unknown';
  const isMissingValue = rawValue === null || rawValue === undefined
    || ['', 'unknown', 'unavailable', 'not_collected', 'not collected', 'n/a', 'na', 'null', 'none', '--'].includes(normalizedValue);
  if (componentState && normalizedValue === '3') return 'not_collected';
  if (explicitStatus === 'not_collected') return 'not_collected';
  if (isMissingValue) return hasExplicitUnknownStatus || normalizedValue === 'unknown' ? 'unknown' : 'not_collected';

  if (explicitStatus !== 'unknown') return explicitStatus;

  if (componentState && ['0', '1', '2'].includes(normalizedValue)) {
    if (normalizedValue === '2') return 'critical';
    if (normalizedValue === '1') return 'warning';
    const expected = String(expectedValue ?? '').trim().toLowerCase();
    return expected && !['ok', 'normal', '0'].includes(expected) ? 'warning' : 'healthy';
  }

  if (componentState && ['ok', 'normal', 'up', 'true', 'running', 'operational', 'ready', 'active'].includes(normalizedValue)) return 'healthy';
  if (['warning', 'warn', 'degraded'].includes(normalizedValue)) return 'warning';
  if (['critical', 'error', 'failed', 'fail', 'failure', 'unhealthy', 'down', 'offline', 'alarm', 'false', '0'].includes(normalizedValue)) {
    return componentState ? 'critical' : 'warning';
  }
  const expected = String(expectedValue ?? '').trim().toLowerCase();
  const isComplianceText = String(category ?? '').toLowerCase() === 'compliance';
  const matchesExpected = expected && (
    normalizedValue === expected
    || (isComplianceText && normalizedValue.includes(expected) && !/^(?:un|not|no|non)/.test(normalizedValue))
  );
  if (matchesExpected) return 'healthy';
  if (['healthy', 'success', 'ok', 'normal', 'up', 'true', '1', 'running', 'operational', 'ready', 'active'].includes(normalizedValue)) {
    return expected ? 'warning' : 'healthy';
  }
  if (expected) return 'warning';
  return 'warning';
};

const getMetricValueStatusLabel = (status: InspectionHealthKind, zh: boolean): string => {
  if (status === 'healthy') return zh ? '正常' : 'Normal';
  if (status === 'warning') return zh ? '告警' : 'Alert';
  if (status === 'critical') return zh ? '故障' : 'Failure';
  if (status === 'not_collected') return zh ? '未采集' : 'Not collected';
  return zh ? '状态未知' : 'Unknown';
};

interface InspectionSummaryIssue {
  severity: 'critical' | 'warning';
  reason: string;
  suggestion: string;
  key: string;
}

const buildInspectionSummary = (
  res: any,
  analysis: any[],
  findings: any[],
  correlatedRisks: any[],
  metrics: Record<string, any>,
  zh: boolean,
) => {
  const candidates: InspectionSummaryIssue[] = [];
  const issueCounts = new Map<string, 'critical' | 'warning'>();
  const normalizeAlias = (value: unknown) => String(value ?? '').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]/g, '');
  const aliasesMatch = (left: string[], right: string[]) => left.some((leftAlias) => {
    const normalizedLeft = normalizeAlias(leftAlias);
    return normalizedLeft.length >= 2 && right.some((rightAlias) => normalizeAlias(rightAlias) === normalizedLeft);
  });
  const messageMatchesAliases = (message: string, aliases: string[]) => {
    const normalizedMessage = normalizeAlias(message);
    return aliases.some((alias) => {
      const normalizedAlias = normalizeAlias(alias);
      return normalizedAlias.length >= 2 && normalizedMessage.includes(normalizedAlias);
    });
  };
  const metricConfigSources = [res?.metric_config, res?.metric_configs, res?.inspection_items];
  const findMetricConfig = (key: string) => metricConfigSources.map((source: any) => {
    if (Array.isArray(source)) return source.find((item: any) => String(item?.check_key || item?.key || item?.id || '') === key);
    if (source && typeof source === 'object') return source[key];
    return undefined;
  }).find(Boolean);
  const getMetricConfigAliases = (config: any) => [
    config?.check_key, config?.key, config?.id, config?.name, config?.name_zh,
  ].filter(Boolean).map(String);
  const getConnectivityFindingKey = (finding: any): string | null => {
    if (String(finding?.type || '').trim().toLowerCase() !== 'connectivity_error') return null;
    const details = [finding?.message, finding?.label, finding?.key, finding?.check_key, finding?.raw_error]
      .filter(Boolean).map(String).join(' ').toLowerCase();
    if (/icmp|ping/.test(details)) return 'connectivity:icmp';
    if (/ssh/.test(details)) return 'connectivity:ssh';
    return null;
  };
  const analysisEntries = analysis.map((item, index) => ({
    item,
    metricKey: String(item?.key || item?.check_key || item?.metric || item?.conclusion || `metric-${index}`),
    aliases: [item?.key, item?.check_key, item?.metric, item?.name, item?.name_zh]
      .filter(Boolean).map(String),
    severity: normalizeInspectionHealth(item?.status),
  }));
  const pushIssue = (issue: InspectionSummaryIssue) => {
    const previous = issueCounts.get(issue.key);
    if (!previous || (previous === 'warning' && issue.severity === 'critical')) issueCounts.set(issue.key, issue.severity);
    candidates.push(issue);
  };

  const analysisIssues = analysisEntries.flatMap((entry) => {
    const { item, metricKey, aliases, severity } = entry;
    if (severity !== 'critical' && severity !== 'warning') return [];
    return [{
      severity,
      reason: String(item?.conclusion || item?.metric || ''),
      suggestion: String(item?.suggestion || ''),
      key: `metric:${metricKey}`,
      aliases,
    }];
  });
  analysisIssues.forEach(({ aliases: _aliases, ...issue }) => pushIssue(issue));

  const metricStatusIssues = Object.entries(metrics || {}).flatMap(([statusField, rawStatus]) => {
    if (!/_status$/i.test(statusField)) return [];
    const severity = normalizeInspectionHealth(rawStatus);
    if (severity !== 'critical' && severity !== 'warning') return [];

    const metricKey = statusField.replace(/_evaluation_status$/i, '').replace(/_status$/i, '');
    const config = findMetricConfig(metricKey);
    const configAliases = getMetricConfigAliases(config);
    const metricAliases = [metricKey, metricKey.replace(/_/g, ' '), ...configAliases];
    const matchedAnalysis = analysisEntries.find((entry) => aliasesMatch(entry.aliases, metricAliases));
    const canonicalMetricKey = matchedAnalysis?.metricKey || metricKey;
    const metricName = String(config?.name_zh || config?.name || matchedAnalysis?.item?.metric || metricKey.replace(/_/g, ' '));
    return [{
      severity,
      reason: `${metricName}：${getInspectionIssueLabel(severity, zh)}`,
      suggestion: '',
      key: `metric:${canonicalMetricKey}`,
      aliases: [...metricAliases, ...(matchedAnalysis?.aliases || [])],
    }];
  });
  metricStatusIssues.forEach(({ aliases: _aliases, ...issue }) => pushIssue(issue));

  findings.forEach((finding, index) => {
    const severity = normalizeInspectionHealth(finding?.severity);
    if (severity !== 'critical' && severity !== 'warning') return;
    const message = String(finding?.message || finding?.label || '');
    const findingAliases = [finding?.key, finding?.metric_key, finding?.check_key, finding?.metric, finding?.name, finding?.name_zh]
      .filter(Boolean).map(String);
    const matchedAnalysis = analysisEntries.find((entry) => (
      aliasesMatch(entry.aliases, findingAliases) || messageMatchesAliases(message, entry.aliases)
    ));
    const matchedMetricStatus = metricStatusIssues.find((item) => (
      aliasesMatch(item.aliases, findingAliases) || messageMatchesAliases(message, item.aliases)
    ));
    const connectivityKey = getConnectivityFindingKey(finding);
    const key = connectivityKey || (matchedAnalysis
      ? `metric:${matchedAnalysis.metricKey}`
      : matchedMetricStatus?.key || `finding:${finding?.type || 'issue'}:${message || index}`);
    pushIssue({ severity, reason: message, suggestion: String(finding?.suggestion || ''), key });
  });

  correlatedRisks.forEach((risk, index) => {
    const severity = normalizeInspectionHealth(risk?.severity);
    if (severity !== 'critical' && severity !== 'warning') return;
    const name = String(risk?.rule_name || risk?.description || `risk-${index}`);
    pushIssue({
      severity,
      reason: String(risk?.description || risk?.rule_name || ''),
      suggestion: String(risk?.suggestion || ''),
      key: `risk:${name}`,
    });
  });

  if (normalizeConnectivity(res?.ping_ok) === 'critical') {
    pushIssue({ severity: 'critical', reason: 'ICMP 连接失败', suggestion: '检查设备供电、网络路径和管理地址。', key: 'connectivity:icmp' });
  }
  if (normalizeConnectivity(res?.ssh_ok) === 'critical') {
    pushIssue({ severity: 'warning', reason: 'SSH 采集未成功', suggestion: '检查 SSH 服务、账号凭据和访问策略。', key: 'connectivity:ssh' });
  }

  const notCollectedKeys = new Set<string>();
  Object.entries(metrics || {}).forEach(([key, value]) => {
    if (/_status$/i.test(key)) {
      const status = normalizeInspectionHealth(value);
      if (status === 'not_collected' || status === 'unknown') notCollectedKeys.add(key.replace(/_status$/i, ''));
      return;
    }
    if (value && typeof value === 'object' && /未采集|not[ _-]?collected|unavailable/i.test(String((value as any).error || ''))) {
      notCollectedKeys.add(key);
    }
  });
  analysis.forEach((item, index) => {
    const status = normalizeInspectionHealth(item?.status);
    if (status === 'not_collected' || status === 'unknown') {
      notCollectedKeys.add(String(item?.key || item?.metric || `unknown-${index}`));
    }
  });

  const prioritizedIssues = [...candidates].sort((left, right) => {
    const severityOrder = (right.severity === 'critical' ? 2 : 1) - (left.severity === 'critical' ? 2 : 1);
    return severityOrder || Number(Boolean(right.suggestion)) - Number(Boolean(left.suggestion));
  });
  const primaryIssue = prioritizedIssues[0];
  const healthKinds: InspectionHealthKind[] = [normalizeInspectionHealth(res?.health_status), ...issueCounts.values()];
  const health = healthKinds.reduce<InspectionHealthKind>((current, next) => {
    const rank: Record<InspectionHealthKind, number> = { unknown: 0, not_collected: 0, healthy: 0, warning: 1, critical: 2 };
    if (current === 'unknown' && next !== 'unknown') return next;
    return rank[next] > rank[current] ? next : current;
  }, normalizeInspectionHealth(res?.health_status));

  const isCoreMetricKey = (key: string) => (
    !/_last$|_change_pct$/i.test(key)
    && /cpu|mem|memory|temp|fan|psu|uptime/i.test(key)
  );
  const coreMetricKeys = new Set<string>();
  const analyzedMetricKeys = new Set<string>();
  analysis.forEach((item) => {
    const key = String(item?.key || item?.check_key || '');
    if (key && isCoreMetricKey(key)) {
      analyzedMetricKeys.add(key);
      coreMetricKeys.add(key);
    }
  });
  Object.keys(metrics || {}).forEach((key) => {
    if (isCoreMetricKey(key) && (!/_status$/i.test(key) || analyzedMetricKeys.has(key) || /^(fan|psu)_status$/i.test(key))) {
      coreMetricKeys.add(key);
    }
  });

  const coreMetrics = [...coreMetricKeys].flatMap((key) => {
    const analysisItem = analysis.find((item) => String(item?.key || item?.check_key || '') === key);
    const metricConfig = findMetricConfig(key) || {};
    const rawEntry = metrics[key];
    const value = rawEntry === undefined ? analysisItem?.value : rawEntry && typeof rawEntry === 'object' ? (rawEntry as any).value : rawEntry;
    const unit = String(
      analysisItem?.unit
      || metricConfig?.unit
      || (rawEntry && typeof rawEntry === 'object' ? (rawEntry as any).unit : '')
      || metrics[`${key}_unit`]
      || res?.metric_units?.[key]
      || '',
    ).trim();
    const parseType = String(analysisItem?.parse_type || metricConfig?.parse_type || '').toLowerCase();
    const isStatusMetric = parseType === 'status' || unit.toLowerCase() === 'status' || /_(status|state|fan|psu)$/i.test(key);
    const label = String(analysisItem?.metric || analysisItem?.name_zh || metricConfig?.name_zh || metricConfig?.name || key.replace(/_/g, ' '));

    if (isStatusMetric) {
      const evaluatedStatus = metrics[`${key}_status`] ?? metrics[`${key}_evaluation_status`] ?? analysisItem?.status;
      const expectedValue = analysisItem?.expected_value || metricConfig?.expected_value || metrics[`${key}_expected_value`];
      const status = getMetricValueStatus(key, value, evaluatedStatus, expectedValue, analysisItem?.category || metricConfig?.category);
      return [{ key, label, value: getMetricValueStatusLabel(status, zh), status }];
    }

    if (value === null || value === undefined || typeof value === 'object') return [];
    const evaluatedStatus = metrics[`${key}_status`] ?? metrics[`${key}_evaluation_status`] ?? analysisItem?.status;
    const status = normalizeInspectionHealth(evaluatedStatus);
    const renderedValue = String(value);
    if (!unit) return [{ key, label, value: renderedValue, status }];
    if (unit === '%' || /^°[CF]$/i.test(unit)) return [{ key, label, value: `${renderedValue}${unit}`, status }];
    const displayUnit = unit.toLowerCase() === 'count' ? (zh ? '个' : 'count') : unit;
    return [{ key, label, value: `${renderedValue} ${displayUnit}`, status }];
  }).sort((left, right) => {
    const priority: Record<InspectionHealthKind, number> = {
      critical: 0,
      warning: 1,
      unknown: 2,
      not_collected: 2,
      healthy: 3,
    };
    return priority[left.status] - priority[right.status];
  }).slice(0, 4).map(({ status: _status, ...metric }) => metric);

  const countBySeverity = [...issueCounts.values()].reduce((counts, severity) => {
    counts[severity] += 1;
    return counts;
  }, { critical: 0, warning: 0 });

  return {
    health,
    issueCount: issueCounts.size,
    criticalCount: countBySeverity.critical,
    warningCount: countBySeverity.warning,
    notCollectedCount: notCollectedKeys.size,
    primaryIssue,
    coreMetrics,
  };
};

const parseInspectionResult = (res: any, zh: boolean) => {
  const parsedAnalysis = parseInspectionJson<unknown>(res.analysis_json, []);
  const parsedFindings = parseInspectionJson<unknown>(res.findings_json, []);
  const analysis = Array.isArray(parsedAnalysis) ? parsedAnalysis : [];
  const findings = Array.isArray(parsedFindings) ? parsedFindings : [];
  const parsedMetrics = parseInspectionJson<unknown>(res.metrics_json, {});
  const metricsObj = parsedMetrics && typeof parsedMetrics === 'object' && !Array.isArray(parsedMetrics)
    ? parsedMetrics as Record<string, any>
    : {};
  const parsedCorrelatedRisks = parseInspectionJson<unknown>(res.correlated_risks_json, []);
  const correlatedRisks = Array.isArray(parsedCorrelatedRisks) ? parsedCorrelatedRisks : [];
  const summary = buildInspectionSummary(res, analysis, findings, correlatedRisks, metricsObj, zh);

  return { analysis, findings, metricsObj, correlatedRisks, summary };
};

interface ExecutionDetailProps {
  zh: boolean;
  open: boolean;
  selectedLog: UnifiedExecutionLog | null;
  logDetailLoading: boolean;
  onClose: () => void;
  // Inspection
  inspectionDetail: any;
  selectedInspDeviceId: string | null;
  setSelectedInspDeviceId: (id: string | null) => void;
  collapsedCmds: Record<string, boolean>;
  toggleCmdCollapse: (cmd: string) => void;
  expandAllCmds: (cmds: string[]) => void;
  collapseAllCmds: (cmds: string[]) => void;
  inspParseResults: Record<string, { loading: boolean; data: any; error: string }>;
  inspCopiedKey: string | null;
  inspDetailTab: InspDetailTab;
  setInspDetailTab: (tab: InspDetailTab) => void;
  inspParseViewMode: Record<string, 'raw' | 'parsed'>;
  setInspParseViewMode: React.Dispatch<React.SetStateAction<Record<string, 'raw' | 'parsed'>>>;
  trendData: { deviceId: string; metric: string; series: any[]; firstInspection?: boolean } | null;
  trendLoading: boolean;
  setTrendData: (d: any) => void;
  onParseCmd: (blockKey: string, platform: string, command: string, rawOutput: string) => void;
  onCopyText: (text: string, key: string) => void;
  onFetchTrend: (deviceId: string, metric: string) => void;
  setCollapsedCmds: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  setInspParseResults: React.Dispatch<React.SetStateAction<Record<string, { loading: boolean; data: any; error: string }>>>;
  // Playbook
  pbDetail: any;
  pbDevices: any[];
  pbApprovals: PlaybookExecutionApproval[];
  pbApprovalsLoading: boolean;
  pbApprovalActionId: string;
  pbApprovalError: string;
  onPlaybookApproval: (approval: PlaybookExecutionApproval, decision: 'approve' | 'reject') => void;
  selectedPbDevice: any;
  pbDeviceDetail: any;
  onSelectPbDevice: (deviceId: string) => void;
  backupRunDetail: ConfigBackupRunDetail | null;
  backupRunError: string;
  backupDevicePage: number;
  backupDeviceStatusFilter: BackupDetailStatus;
  onBackupDevicePageChange: (page: number) => void;
  onBackupDeviceStatusFilterChange: (status: BackupDetailStatus) => void;
  onRetryBackupRunDetails: () => void;
  devices: Device[];
}

interface ParsedInspectionOutputTableProps {
  data: { fields: string[]; records: Array<Record<string, unknown>> };
  filename: string;
  zh: boolean;
  onDownloadJson: () => void;
}

const ParsedInspectionOutputTable: React.FC<ParsedInspectionOutputTableProps> = ({ data, filename, zh, onDownloadJson }) => {
  const tableRef = React.useRef<HTMLTableElement>(null);

  return (
    <div className="space-y-2">
      <div className="flex justify-end gap-1">
        <TableExportMenu tableRef={tableRef} filename={filename} language={zh ? 'zh' : 'en'} disabled={data.records.length === 0} />
        <ActionIconButton icon={FileJson} label={zh ? '下载解析结果 (JSON)' : 'Download parsed as JSON'} variant="accent" onClick={onDownloadJson} disabled={data.records.length === 0} />
      </div>
      <div className="overflow-x-auto custom-scrollbar-dark pb-2">
        <table ref={tableRef} className="nx-terminal-table w-full text-left border-collapse border border-white/10">
          <thead>
            <tr className="bg-white/5 border-b border-white/10">
              {data.fields.map((field) => (
                <th key={field} scope="col" className="px-3 py-2 text-[10px] font-bold text-cyan-400/80 uppercase tracking-wider border-r border-white/10 last:border-r-0">{field}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.records.map((record, index) => (
              <tr key={index} className="hover:bg-white/[0.03]">
                {data.fields.map((field) => (
                  <td key={field} className="px-3 py-2 text-[10px] text-white/60 whitespace-nowrap border-r border-white/5 last:border-r-0">{String(record[field] ?? '—')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const ExecutionDetail: React.FC<ExecutionDetailProps> = ({
  zh, open, selectedLog, logDetailLoading, onClose,
  inspectionDetail, selectedInspDeviceId, setSelectedInspDeviceId,
  collapsedCmds, toggleCmdCollapse, expandAllCmds, collapseAllCmds,
  inspParseResults, inspCopiedKey, inspDetailTab, setInspDetailTab,
  inspParseViewMode, setInspParseViewMode,
  trendData, trendLoading, setTrendData,
  onParseCmd, onCopyText, onFetchTrend,
  setCollapsedCmds, setInspParseResults,
  pbDetail, pbDevices, pbApprovals, pbApprovalsLoading, pbApprovalActionId, pbApprovalError, onPlaybookApproval,
  selectedPbDevice, pbDeviceDetail, onSelectPbDevice,
  backupRunDetail, backupRunError, backupDevicePage, backupDeviceStatusFilter,
  onBackupDevicePageChange, onBackupDeviceStatusFilterChange, onRetryBackupRunDetails, devices,
}) => {
  useEscapeClose(open, onClose);
  if (!selectedLog) return null;

  const selectedOutputDevice = devices.find((device) => device.id === String(selectedPbDevice || ''));
  const outputDeviceType = `${selectedOutputDevice?.asset_type || ''} ${selectedOutputDevice?.platform || ''}`.toLowerCase();
  const isLinuxOutput = selectedLog.source === 'playbook' && (
    /linux|ubuntu|debian|centos|redhat|rhel|rocky|alma|suse|server/.test(outputDeviceType)
    || selectedLog.name.toLowerCase().includes('linux')
  );
  let authorizationFailureReason = '';
  if (selectedLog.source === 'playbook' && selectedLog.status === 'denied') {
    try {
      const phases = typeof pbDetail?.phases_json === 'string'
        ? JSON.parse(pbDetail.phases_json)
        : pbDetail?.phases_json;
      authorizationFailureReason = String(phases?.authorization?.reason || '');
    } catch {
      authorizationFailureReason = '';
    }
  }
  const approvalSnapshotMismatch = authorizationFailureReason.trim().toLowerCase() === 'scheduled job content changed after approval';
  const authorizationFailureReasonText = approvalSnapshotMismatch
    ? (zh
      ? '执行时发现作业内容摘要与审批记录不一致，任务已拦截。请检查作业配置，并重新申请审批后再运行。'
      : 'The execution snapshot does not match its approved record, so this run was blocked. Review the job and request approval again before rerunning it.')
    : authorizationFailureReason || (zh ? '执行时未通过作业授权校验。' : 'The scheduled job did not pass its authorization check.');
  const isDeniedRunNotice = selectedLog.status === 'denied'
    && selectedLog.source !== 'inspection'
    && selectedLog.source !== 'config_backup';

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 lg:p-8">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={`relative bg-white rounded-[2rem] shadow-2xl w-full ${isDeniedRunNotice ? 'max-w-xl h-auto max-h-[calc(100vh-2rem)]' : 'max-w-6xl h-[90vh]'} overflow-hidden flex flex-col z-10 border border-black/10`}
          >
            {/* Header */}
            <div className="px-6 py-4 border-b border-black/5 flex items-center justify-between bg-black/[0.015] flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
                  <Activity size={18} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-blue-900">
                    {selectedLog.name}
                  </h3>
                  <p className="text-[10px] text-black/30 font-mono mt-0.5">{zh ? '编号：' : 'ID: '}{selectedLog.id}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={onClose} className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all">
                  <X size={20} />
                </button>
              </div>
            </div>

            {selectedLog.source === 'playbook' && selectedLog.status === 'awaiting_approval' && (
              <div className="shrink-0 border-b border-violet-100 bg-violet-50/60 px-6 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-violet-900">{zh ? '执行审批门' : 'Execution approval gates'}</div>
                  {pbApprovalsLoading && <Loader2 size={14} className="animate-spin text-violet-500" />}
                </div>
                {pbApprovalError && <div className="mt-2 rounded-lg bg-rose-50 px-2.5 py-2 text-[10px] text-rose-700">{pbApprovalError}</div>}
                <div className="mt-2 space-y-2">
                  {pbApprovals.map((approval) => (
                    <div key={approval.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-violet-100 bg-white px-3 py-2 text-[10px]">
                      <div className="min-w-0">
                        <div className="font-semibold text-slate-800">{approval.title || approval.id}</div>
                        <div className="mt-0.5 text-slate-500">{approval.message || (zh ? '审批通过前不会启动设备任务。' : 'Device tasks remain paused until approval.')}</div>
                      </div>
                      {approval.status === 'PENDING' ? (
                        <div className="flex shrink-0 gap-1.5">
                          <button type="button" onClick={() => onPlaybookApproval(approval, 'approve')} disabled={pbApprovalActionId === approval.id} className="rounded-lg bg-emerald-600 px-2.5 py-1.5 font-semibold text-white disabled:opacity-50">{pbApprovalActionId === approval.id ? '...' : (zh ? '批准' : 'Approve')}</button>
                          <button type="button" onClick={() => onPlaybookApproval(approval, 'reject')} disabled={pbApprovalActionId === approval.id} className="rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 font-semibold text-rose-700 disabled:opacity-50">{zh ? '拒绝' : 'Reject'}</button>
                        </div>
                      ) : <span className={`rounded-full px-2 py-1 font-semibold ${approval.status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{approval.status}</span>}
                    </div>
                  ))}
                  {!pbApprovalsLoading && pbApprovals.length === 0 && <div className="text-[10px] text-violet-700/70">{zh ? '未找到审批记录。' : 'No approval records found.'}</div>}
                </div>
              </div>
            )}

            {/* Content */}
            <div className={`${isDeniedRunNotice ? 'flex-none' : 'flex-1'} overflow-hidden relative`}>
              {logDetailLoading ? (
                <div className="h-full flex flex-col items-center justify-center text-black/20 gap-3">
                  <RotateCcw size={32} className="animate-spin opacity-20" />
                  <span className="text-xs font-bold">{zh ? '加载详情中...' : 'Loading details...'}</span>
                </div>
              ) : selectedLog.source === 'inspection' ? (
                <InspectionView
                  zh={zh}
                  inspectionDetail={inspectionDetail}
                  selectedInspDeviceId={selectedInspDeviceId}
                  setSelectedInspDeviceId={setSelectedInspDeviceId}
                  collapsedCmds={collapsedCmds}
                  toggleCmdCollapse={toggleCmdCollapse}
                  expandAllCmds={expandAllCmds}
                  collapseAllCmds={collapseAllCmds}
                  inspParseResults={inspParseResults}
                  inspCopiedKey={inspCopiedKey}
                  inspDetailTab={inspDetailTab}
                  setInspDetailTab={setInspDetailTab}
                  inspParseViewMode={inspParseViewMode}
                  setInspParseViewMode={setInspParseViewMode}
                  trendData={trendData}
                  trendLoading={trendLoading}
                  setTrendData={setTrendData}
                  onParseCmd={onParseCmd}
                  onCopyText={onCopyText}
                  onFetchTrend={onFetchTrend}
                  setCollapsedCmds={setCollapsedCmds}
                  setInspParseResults={setInspParseResults}
                />
              ) : selectedLog.source === 'config_backup' ? (
                <ConfigBackupRunView
                  zh={zh}
                  selectedLog={selectedLog}
                  detail={backupRunDetail}
                  error={backupRunError}
                  loading={logDetailLoading}
                  page={backupDevicePage}
                  statusFilter={backupDeviceStatusFilter}
                  onPageChange={onBackupDevicePageChange}
                  onStatusFilterChange={onBackupDeviceStatusFilterChange}
                  onRetry={onRetryBackupRunDetails}
                />
              ) : selectedLog.status === 'denied' ? (
                <div className={`flex items-center justify-center bg-slate-50 px-6 ${isDeniedRunNotice ? 'py-5 sm:py-6' : 'h-full'}`}>
                  {approvalSnapshotMismatch ? (
                    <section className="w-full rounded-2xl border border-amber-200 bg-white p-5 shadow-sm sm:p-6" role="status" aria-labelledby="approval-mismatch-title">
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-50 text-amber-700">
                          <AlertTriangle size={19} aria-hidden="true" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 id="approval-mismatch-title" className="text-base font-semibold text-slate-900">
                            {zh ? '权限校验未通过，作业未执行' : 'Authorization check failed; job not run'}
                          </h3>
                        </div>
                      </div>
                    </section>
                  ) : (
                    <div className="max-w-2xl rounded-2xl border border-rose-200 bg-white p-6 shadow-sm" role="status">
                      <div className="flex items-center gap-2 text-sm font-bold text-rose-700">
                        <AlertTriangle size={18} />
                        {zh ? '作业未执行：权限校验拒绝' : 'Job not run: authorization denied'}
                      </div>
                      <p className="mt-3 break-words text-xs leading-6 text-slate-600">
                        {authorizationFailureReasonText}
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <PlaybookView
                  zh={zh}
                  isLinuxOutput={isLinuxOutput}
                  pbDevices={pbDevices}
                  selectedPbDevice={selectedPbDevice}
                  pbDeviceDetail={pbDeviceDetail}
                  onSelectPbDevice={onSelectPbDevice}
                  devices={devices}
                  collapsedCmds={collapsedCmds}
                  toggleCmdCollapse={toggleCmdCollapse}
                  setCollapsedCmds={setCollapsedCmds}
                />
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

/* ═══════════════════════════════════════════════════════ */
/*  Inspection Detail Sub-View                             */
/* ═══════════════════════════════════════════════════════ */

interface InspectionViewProps {
  zh: boolean;
  inspectionDetail: any;
  selectedInspDeviceId: string | null;
  setSelectedInspDeviceId: (id: string | null) => void;
  collapsedCmds: Record<string, boolean>;
  toggleCmdCollapse: (cmd: string) => void;
  expandAllCmds: (cmds: string[]) => void;
  collapseAllCmds: (cmds: string[]) => void;
  inspParseResults: Record<string, { loading: boolean; data: any; error: string }>;
  inspCopiedKey: string | null;
  inspDetailTab: InspDetailTab;
  setInspDetailTab: (tab: InspDetailTab) => void;
  inspParseViewMode: Record<string, 'raw' | 'parsed'>;
  setInspParseViewMode: React.Dispatch<React.SetStateAction<Record<string, 'raw' | 'parsed'>>>;
  trendData: any;
  trendLoading: boolean;
  setTrendData: (d: any) => void;
  onParseCmd: (blockKey: string, platform: string, command: string, rawOutput: string) => void;
  onCopyText: (text: string, key: string) => void;
  onFetchTrend: (deviceId: string, metric: string) => void;
  setCollapsedCmds: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  setInspParseResults: React.Dispatch<React.SetStateAction<Record<string, { loading: boolean; data: any; error: string }>>>;
}

export const InspectionView: React.FC<InspectionViewProps> = ({
  zh, inspectionDetail, selectedInspDeviceId, setSelectedInspDeviceId,
  collapsedCmds, toggleCmdCollapse, expandAllCmds, collapseAllCmds,
  inspParseResults, inspCopiedKey, inspDetailTab, setInspDetailTab,
  inspParseViewMode, setInspParseViewMode,
  trendData, trendLoading, setTrendData,
  onParseCmd, onCopyText, onFetchTrend,
  setCollapsedCmds, setInspParseResults,
}) => {
  const summaryByDevice = React.useMemo(() => {
    const summaries = new Map<string, ReturnType<typeof buildInspectionSummary>>();
    (inspectionDetail?.results || []).forEach((result: any) => {
      summaries.set(String(result.device_id), parseInspectionResult(result, zh).summary);
    });
    return summaries;
  }, [inspectionDetail?.results, zh]);

  return (
    <div className="flex flex-col md:flex-row h-full">
      {/* Device List (Left) */}
      <div className="w-full md:w-4/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
        <div className="p-4 border-b border-black/5 bg-white flex items-center justify-between">
          <span className="text-xs font-bold text-black/50">{zh ? '设备巡检结果' : 'Inspection Results'}</span>
          <span className="text-[10px] font-bold text-black/20 uppercase tracking-widest tabular-nums">
            {inspectionDetail?.results?.length || 0} {zh ? '台设备' : 'Devices'}
          </span>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1 custom-scrollbar">
          {(inspectionDetail?.results || []).map((res: any) => {
            const isSelected = selectedInspDeviceId === res.device_id;
            const healthKind = summaryByDevice.get(String(res.device_id))?.health
              ?? normalizeInspectionHealth(res.health_status);
            const healthTone = healthKind === 'healthy'
              ? (isSelected ? 'bg-emerald-400/20 text-emerald-300' : 'bg-emerald-50 text-emerald-600')
              : healthKind === 'warning'
                ? (isSelected ? 'bg-amber-400/20 text-amber-300' : 'bg-amber-50 text-amber-600')
                : healthKind === 'critical'
                  ? (isSelected ? 'bg-red-400/20 text-red-300' : 'bg-red-50 text-red-600')
                  : (isSelected ? 'bg-white/10 text-white/60' : 'bg-slate-100 text-slate-500');
            return (
              <div
                key={res.id}
                onClick={() => {
                  setSelectedInspDeviceId(res.device_id);
                  setCollapsedCmds({});
                  setInspParseResults({});
                }}
                className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                  isSelected 
                    ? 'bg-blue-700 text-white border-transparent shadow-md'
                    : 'bg-white border-black/5 hover:border-black/10 hover:shadow-sm'
                }`}
              >
                <div className="min-w-0">
                  <p className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-blue-900'}`}>{res.hostname}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <p className={`text-[9px] font-mono ${isSelected ? 'text-white/60' : 'text-black/30'}`}>{res.ip_address}</p>
                  </div>
                </div>
                <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${healthTone}`}>
                  {getInspectionIssueLabel(healthKind, zh)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail Content (Right) */}
      <div className="flex-1 flex flex-col bg-[#1E1E1E] overflow-hidden">
        {selectedInspDeviceId ? (() => {
          const res = inspectionDetail.results.find((r: any) => r.device_id === selectedInspDeviceId);
          if (!res) return null;
          
          const resultData = parseInspectionResult(res, zh);
          const parsedRawOutputs = parseInspectionJson<unknown>(res.raw_outputs_json, {});
          const rawOutputs = parsedRawOutputs && typeof parsedRawOutputs === 'object' && !Array.isArray(parsedRawOutputs)
            ? parsedRawOutputs as Record<string, string>
            : {};
          const { analysis, findings, metricsObj, correlatedRisks } = resultData;
          const inspectionSummary = summaryByDevice.get(String(res.device_id)) || resultData.summary;
          const pingStatus = normalizeConnectivity(res.ping_ok);
          const sshStatus = normalizeConnectivity(res.ssh_ok);

          const complianceItems = analysis.filter((a: any) => (a.category === 'compliance') || (a.key && String(a.key).includes('compliance')));
          const summaryTone = inspectionSummary.health === 'critical'
            ? 'border-red-400/25 bg-red-500/10 text-red-200'
            : inspectionSummary.health === 'warning'
              ? 'border-amber-400/25 bg-amber-500/10 text-amber-100'
              : inspectionSummary.health === 'healthy'
                ? 'border-emerald-400/25 bg-emerald-500/10 text-emerald-100'
                : 'border-slate-400/20 bg-slate-500/10 text-slate-200';

          return (
            <>
              {/* Device header bar */}
              <div className="p-4 border-b border-white/10 bg-black/20 flex items-center justify-between">
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-white/80 font-bold block">{res.hostname} ({res.ip_address})</span>
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 ${getConnectivityTone(pingStatus)}`}>Ping: {getConnectivityLabel(pingStatus, zh)}</span>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded bg-white/5 ${getConnectivityTone(sshStatus)}`}>SSH: {getConnectivityLabel(sshStatus, zh)}</span>
                    {res.ssh_error && <span className="text-[10px] text-red-400/70 truncate max-w-[200px]" title={res.ssh_error}>{res.ssh_error}</span>}
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-auto custom-scrollbar-dark p-6 space-y-5 select-text">
                <section aria-label={zh ? '巡检结果摘要' : 'Inspection summary'} className={`rounded-2xl border p-4 sm:p-5 ${summaryTone}`}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest opacity-60">{zh ? '巡检结论' : 'Inspection result'}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <h4 className="text-base font-bold">{getInspectionIssueLabel(inspectionSummary.health, zh)}</h4>
                        {res.health_score != null && <span className="text-xs opacity-70">{zh ? `评分 ${res.health_score}` : `Score ${res.health_score}`}</span>}
                      </div>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-black/10 px-3 py-2 text-right">
                      <p className="text-[10px] opacity-60">{zh ? '异常项' : 'Issues'}</p>
                      <p className="mt-0.5 text-lg font-bold tabular-nums">{inspectionSummary.issueCount}</p>
                      <p className="text-[10px] opacity-60">
                        {zh
                          ? `严重 ${inspectionSummary.criticalCount} · 警告 ${inspectionSummary.warningCount}`
                          : `Critical ${inspectionSummary.criticalCount} · Warnings ${inspectionSummary.warningCount}`}
                      </p>
                    </div>
                  </div>

                  {inspectionSummary.primaryIssue ? (
                    <div className="mt-4 rounded-xl border border-white/10 bg-black/10 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-widest opacity-60">{zh ? '优先处理' : 'Priority'}</p>
                      <p className="mt-1 text-sm font-semibold">{inspectionSummary.primaryIssue.reason || (zh ? '发现需要关注的异常' : 'An issue needs attention')}</p>
                      {inspectionSummary.primaryIssue.suggestion && <p className="mt-1 text-xs leading-relaxed opacity-75">{zh ? '建议：' : 'Next: '}{inspectionSummary.primaryIssue.suggestion}</p>}
                    </div>
                  ) : (
                    <p className="mt-3 text-xs opacity-70">
                      {inspectionSummary.health === 'healthy'
                        ? (zh ? '未发现需要处理的异常。' : 'No issues need attention.')
                        : (zh ? '当前没有足够信息生成异常结论。' : 'There is not enough information for an issue summary.')}
                    </p>
                  )}

                  {inspectionSummary.notCollectedCount > 0 && (
                    <p className="mt-3 text-[11px] opacity-70">
                      {zh
                        ? `${inspectionSummary.notCollectedCount} 项指标未采集或状态未知，不计为严重故障。`
                        : `${inspectionSummary.notCollectedCount} metrics were not collected or have unknown status; they are not counted as critical.`}
                    </p>
                  )}

                  {inspectionSummary.coreMetrics.length > 0 && (
                    <div className="mt-4 border-t border-white/10 pt-3">
                      <p className="text-[10px] font-bold uppercase tracking-widest opacity-60">{zh ? '核心指标' : 'Key metrics'}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {inspectionSummary.coreMetrics.map(metric => (
                          <div key={metric.key} className="min-w-[110px] rounded-lg border border-white/10 bg-black/10 px-3 py-2">
                            <p className="text-[10px] opacity-60">{metric.label}</p>
                            <p className="mt-0.5 text-xs font-mono font-semibold">{metric.value}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </section>

                <details className="group rounded-2xl border border-white/10 bg-black/10">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs font-bold text-white/70 marker:hidden">
                    <span>{zh ? '技术详情' : 'Technical details'}</span>
                    <span className="text-[10px] font-normal text-white/35">{zh ? '完整分析、快照、合规项与原始命令' : 'Full analysis, snapshots, compliance and raw commands'}</span>
                    <ChevronRight size={14} className="shrink-0 text-white/40 transition-transform group-open:rotate-90" />
                  </summary>
                  <div className="p-4 pt-1 space-y-6">
                    {/* Tab bar */}
                    <div className="flex items-center gap-1 border-b border-white/10 px-2">
                  {([
                    { key: 'analysis', label: zh ? '指标分析' : 'Analysis' },
                    { key: 'snapshot', label: zh ? '指标快照' : 'Snapshot' },
                    { key: 'compliance', label: zh ? '合规检查' : 'Compliance' },
                    { key: 'raw', label: zh ? '原始输出' : 'Raw Output' },
                  ] as { key: InspDetailTab; label: string }[]).map(t => (
                    <button
                      key={t.key}
                      onClick={() => { setInspDetailTab(t.key); setTrendData(null); }}
                      className={`px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-colors ${
                        inspDetailTab === t.key ? 'text-cyan-400 border-b-2 border-cyan-400' : 'text-white/40 hover:text-white/70'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                    </div>

                {/* TAB: Analysis */}
                {inspDetailTab === 'analysis' && (
                  <AnalysisTab zh={zh} analysis={analysis} correlatedRisks={correlatedRisks} trendData={trendData} trendLoading={trendLoading} setTrendData={setTrendData} onFetchTrend={onFetchTrend} deviceId={res.device_id} />
                )}

                {/* TAB: Snapshot */}
                {inspDetailTab === 'snapshot' && (
                  <SnapshotTab zh={zh} metricsObj={metricsObj} />
                )}

                {/* TAB: Compliance */}
                {inspDetailTab === 'compliance' && (
                  <ComplianceTab zh={zh} complianceItems={complianceItems} />
                )}

                {/* TAB: Raw Output */}
                {inspDetailTab === 'raw' && (
                  <RawOutputTab
                    zh={zh} res={res} rawOutputs={rawOutputs} analysis={analysis} findings={findings}
                    collapsedCmds={collapsedCmds} toggleCmdCollapse={toggleCmdCollapse}
                    expandAllCmds={expandAllCmds} collapseAllCmds={collapseAllCmds}
                    inspParseResults={inspParseResults} inspCopiedKey={inspCopiedKey}
                    inspParseViewMode={inspParseViewMode} setInspParseViewMode={setInspParseViewMode}
                    onParseCmd={onParseCmd} onCopyText={onCopyText}
                  />
                )}
                  </div>
                </details>
              </div>
            </>
          );
        })() : (
          <div className="flex-1 flex flex-col items-center justify-center text-white/20 gap-3">
            <Search size={48} strokeWidth={1} className="opacity-10" />
            <span className="text-sm">{zh ? '请选择左侧设备查看详情' : 'Select a device to see details'}</span>
          </div>
        )}
      </div>
    </div>
  );
};

/* ═══════════════════════════════════════════════════════ */
/*  Analysis Tab                                           */
/* ═══════════════════════════════════════════════════════ */

const AnalysisTab: React.FC<{
  zh: boolean; analysis: any[]; correlatedRisks: any[];
  trendData: any; trendLoading: boolean; setTrendData: (d: any) => void;
  onFetchTrend: (deviceId: string, metric: string) => void; deviceId: string;
}> = ({ zh, analysis, correlatedRisks, trendData, trendLoading, setTrendData, onFetchTrend, deviceId }) => (
  <div className="space-y-4">
    {correlatedRisks.length > 0 && (
      <div className="space-y-2">
        <h4 className="text-[11px] font-bold text-red-400 uppercase tracking-widest flex items-center gap-2">
          <AlertTriangle size={12} /> {zh ? '关联风险预警' : 'Correlated Risk Alerts'}
        </h4>
        {correlatedRisks.map((risk, i) => (
          <div key={i} className={`p-3 rounded-lg border ${risk.severity === 'critical' ? 'bg-red-500/10 border-red-500/30' : 'bg-amber-500/10 border-amber-500/30'}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1">
                <div className="text-xs font-bold text-white/90 mb-1">⚠️ {risk.rule_name}</div>
                <div className="text-[11px] text-white/60 leading-relaxed">{risk.description}</div>
                {risk.suggestion && <div className="text-[11px] text-cyan-400/70 mt-1.5">💡 {risk.suggestion}</div>}
              </div>
              <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded shrink-0 ${risk.severity === 'critical' ? 'bg-red-500/30 text-red-300' : 'bg-amber-500/30 text-amber-300'}`}>{risk.severity?.toUpperCase()}</span>
            </div>
          </div>
        ))}
      </div>
    )}

    {trendData && (
      <div className="rounded-lg border border-cyan-500/20 bg-black/30 p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-bold text-cyan-400">{zh ? '趋势：' : 'Trend: '}{trendData.metric}</span>
          <button onClick={() => setTrendData(null)} className="text-[10px] text-white/30 hover:text-white/60">✕</button>
        </div>
        {trendLoading ? (
          <div className="text-center py-6 text-white/30 text-xs">{zh ? '加载中...' : 'Loading...'}</div>
        ) : trendData.series.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trendData.series}>
              <CartesianGrid stroke="#334155" strokeDasharray="3 3" />
              <XAxis dataKey="ts" stroke="#64748b" fontSize={10} tickFormatter={(v) => String(v).slice(5, 16)} />
              <YAxis stroke="#64748b" fontSize={10} />
              <RTooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', fontSize: 11 }} />
              <Line type="monotone" dataKey="value" stroke="#2563eb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="text-center py-6 text-white/30 text-xs italic">
            {zh ? '暂无历史数据，首次巡检后将自动记录' : 'No history yet — data appears after future runs'}
          </div>
        )}
      </div>
    )}

    {analysis.length > 0 ? (
      <DataTable unstyled exportConfig={{ filename: 'execution-analysis-results' }} className="nx-data-table nx-data-table--compact text-[11px]">
        <thead>
          <tr className="text-white/50 border-b border-white/10">
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '指标' : 'Metric'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '当前值' : 'Value'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '诊断结论' : 'Conclusion'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '建议' : 'Suggestion'}</th>
            <TableActionHeader className="text-right py-2 px-2 font-bold uppercase tracking-wider">{zh ? '操作' : 'Actions'}</TableActionHeader>
          </tr>
        </thead>
        <tbody>
          {analysis.map((a, i) => {
            const status = normalizeInspectionHealth(a.status);
            const rowBg = status === 'critical' ? 'bg-red-500/10' : status === 'warning' ? 'bg-amber-500/10' : '';
            const isNumeric = typeof a.value === 'number';
            return (
              <tr key={i} className={`${rowBg} border-b border-white/5`}>
                <td className="py-2 px-2 text-white/90 font-bold">{a.metric}</td>
                <td className="py-2 px-2 text-white/70 font-mono">{String(a.value ?? '—')}</td>
                <td className="py-2 px-2">
                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${
                    status === 'critical' ? 'bg-red-500/30 text-red-300' : status === 'warning' ? 'bg-amber-500/30 text-amber-300' : status === 'healthy' ? 'bg-emerald-500/30 text-emerald-300' : 'bg-slate-500/30 text-slate-300'
                  }`}>{getInspectionIssueLabel(status, zh)}</span>
                </td>
                <td className="py-2 px-2 text-white/50">{a.conclusion}</td>
                <td className="py-2 px-2 text-white/50">{a.suggestion}</td>
                <TableActionCell className="py-2 px-2 text-right whitespace-nowrap">
                  {isNumeric && a.key && (
                    <ActionIconGroup label={zh ? '指标操作' : 'Metric actions'}>
                      <ActionIconButton
                        icon={Activity}
                        label={zh ? '查看趋势' : 'View trend'}
                        variant="accent"
                        onClick={() => onFetchTrend(deviceId, a.key)}
                      />
                    </ActionIconGroup>
                  )}
                </TableActionCell>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    ) : (
      <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无分析结果' : 'No analysis available'}</div>
    )}
  </div>
);

/* ═══════════════════════════════════════════════════════ */
/*  Snapshot Tab                                           */
/* ═══════════════════════════════════════════════════════ */

const SnapshotTab: React.FC<{ zh: boolean; metricsObj: Record<string, any> }> = ({ zh, metricsObj }) => (
  <div className="space-y-2">
    {Object.keys(metricsObj).length === 0 ? (
      <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无指标数据' : 'No metrics'}</div>
    ) : (
      <DataTable unstyled exportConfig={{ filename: 'execution-collected-metrics', exportData: buildExecutionSnapshotExportData(metricsObj, zh ? 'zh' : 'en') }} className="nx-data-table nx-data-table--compact text-[11px]">
        <thead>
          <tr className="text-white/50 border-b border-white/10">
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '指标键' : 'Metric Key'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '值' : 'Value'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '错误' : 'Error'}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(metricsObj).map(([key, val]) => {
            const { value, error, isError } = getExecutionSnapshotCells(key, val);
            return (
              <tr key={key} className="border-b border-white/5">
                <td className={`py-2 px-2 font-mono ${isError ? 'text-red-400' : 'text-white/80'}`}>{key}</td>
                <td className="py-2 px-2 text-white/70 font-mono">{value || '—'}</td>
                <td className="py-2 px-2 text-red-400 text-[10px]">{error ? `⚠ ${error}` : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    )}
  </div>
);

/* ═══════════════════════════════════════════════════════ */
/*  Compliance Tab                                         */
/* ═══════════════════════════════════════════════════════ */

const ComplianceTab: React.FC<{ zh: boolean; complianceItems: any[] }> = ({ zh, complianceItems }) => (
  <div className="space-y-2">
    {complianceItems.length === 0 ? (
      <div className="text-white/30 text-center py-6 text-xs italic">{zh ? '暂无合规检查项' : 'No compliance checks defined'}</div>
    ) : (
      <DataTable unstyled exportConfig={{ filename: 'execution-compliance-results' }} className="nx-data-table nx-data-table--compact text-[11px]">
        <thead>
          <tr className="text-white/50 border-b border-white/10">
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '合规项' : 'Item'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '当前值' : 'Value'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
            <th className="text-left py-2 px-2 font-bold uppercase tracking-wider">{zh ? '说明' : 'Description'}</th>
          </tr>
        </thead>
        <tbody>
          {complianceItems.map((c, i) => {
            const status = normalizeInspectionHealth(c.status);
            return (
              <tr key={i} className="border-b border-white/5">
                <td className="py-2 px-2 text-white/90 font-bold">{c.metric}</td>
                <td className="py-2 px-2 text-white/70 font-mono">{String(c.value ?? '—')}</td>
                <td className="py-2 px-2">
                  {status === 'healthy' ? (
                    <span className="inline-flex items-center gap-1 text-emerald-400 text-[10px] font-bold">✓ {zh ? '通过' : 'Pass'}</span>
                  ) : status === 'critical' ? (
                    <span className="inline-flex items-center gap-1 text-red-400 text-[10px] font-bold">✗ {zh ? '失败' : 'Fail'}</span>
                  ) : status === 'warning' ? (
                    <span className="inline-flex items-center gap-1 text-amber-400 text-[10px] font-bold">! {zh ? '警告' : 'Warning'}</span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-slate-400 text-[10px] font-bold">— {getInspectionIssueLabel(status, zh)}</span>
                  )}
                </td>
                <td className="py-2 px-2 text-white/50">{c.conclusion}</td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    )}
  </div>
);

/* ═══════════════════════════════════════════════════════ */
/*  Raw Output Tab                                         */
/* ═══════════════════════════════════════════════════════ */

const RawOutputTab: React.FC<{
  zh: boolean; res: any; rawOutputs: Record<string, string>; analysis: any[]; findings: any[];
  collapsedCmds: Record<string, boolean>; toggleCmdCollapse: (cmd: string) => void;
  expandAllCmds: (cmds: string[]) => void; collapseAllCmds: (cmds: string[]) => void;
  inspParseResults: Record<string, { loading: boolean; data: any; error: string }>;
  inspCopiedKey: string | null;
  inspParseViewMode: Record<string, 'raw' | 'parsed'>;
  setInspParseViewMode: React.Dispatch<React.SetStateAction<Record<string, 'raw' | 'parsed'>>>;
  onParseCmd: (blockKey: string, platform: string, command: string, rawOutput: string) => void;
  onCopyText: (text: string, key: string) => void;
}> = ({ zh, res, rawOutputs, analysis, findings, collapsedCmds, toggleCmdCollapse, expandAllCmds, collapseAllCmds, inspParseResults, inspCopiedKey, inspParseViewMode, setInspParseViewMode, onParseCmd, onCopyText }) => (
  <>
    {/* Findings */}
    {findings.length > 0 && (
      <div className="space-y-3">
        <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
          <AlertTriangle size={12} className="text-amber-500" /> {zh ? '异常发现' : 'Diagnostic Findings'}
        </h4>
        <div className="space-y-2">
          {findings.map((f, i) => (
            <div key={i} className={`p-3 rounded-lg border flex items-start gap-3 ${f.severity === 'critical' ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-amber-500/10 border-amber-500/20 text-amber-400'}`}>
              <div className="mt-1 w-1.5 h-1.5 rounded-full bg-current" />
              <span className="text-xs font-medium leading-relaxed">{f.message}</span>
            </div>
          ))}
        </div>
      </div>
    )}

    {/* Analysis summary */}
    {analysis.length > 0 && (
      <div className="space-y-3">
        <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
          <Activity size={12} className="text-cyan-500" /> {zh ? '智能分析' : 'Smart Analysis'}
        </h4>
        <div className="grid grid-cols-1 gap-3">
          {analysis.map((a, i) => {
            const status = normalizeInspectionHealth(a.status);
            const statusTone = status === 'healthy'
              ? 'text-emerald-400 bg-emerald-400/10'
              : status === 'warning'
                ? 'text-amber-400 bg-amber-400/10'
                : status === 'critical'
                  ? 'text-red-400 bg-red-400/10'
                  : 'text-slate-300 bg-slate-400/10';
            return (
              <div key={i} className="p-3 rounded-lg bg-white/5 border border-white/10 hover:bg-white/[0.08] transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold text-white/80">{a.metric}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${statusTone}`}>{getInspectionIssueLabel(status, zh)}</span>
                </div>
                <div className="text-xs text-white/50 leading-relaxed">{a.conclusion}</div>
                {a.value !== undefined && (
                  <div className="mt-2 text-[10px] font-mono text-white/30 italic">Value: {String(a.value)}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    )}

    {/* Raw Output Blocks */}
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-[11px] font-bold text-white/40 uppercase tracking-widest flex items-center gap-2">
          <FileText size={12} className="text-indigo-400" /> {zh ? '命令执行记录' : 'Command Execution Blocks'}
        </h4>
        {Object.keys(rawOutputs).length > 1 && (
          <div className="flex items-center gap-3">
            <button onClick={() => expandAllCmds(Object.keys(rawOutputs))} className="text-[10px] font-bold text-cyan-400/50 hover:text-cyan-400 transition-colors">{zh ? '全部展开' : 'Expand All'}</button>
            <div className="w-px h-2 bg-white/10" />
            <button onClick={() => collapseAllCmds(Object.keys(rawOutputs))} className="text-[10px] font-bold text-white/20 hover:text-white/40 transition-colors">{zh ? '全部折叠' : 'Collapse All'}</button>
          </div>
        )}
      </div>
      <div className="space-y-3">
        {Object.keys(rawOutputs).length > 0 ? (
          Object.entries(rawOutputs).map(([cmd, output], i) => {
            const outputStr = String(output);
            const isError = outputStr.startsWith('__ERROR__') || outputStr.includes('% Invalid input') || outputStr.includes('error');
            const isCollapsed = collapsedCmds[cmd] ?? (!isError && Object.keys(rawOutputs).length > 3);
            const blockKey = `${res.device_id}::${cmd}`;
            const parseState = inspParseResults[blockKey];
            const isCopied = inspCopiedKey === blockKey;

            return (
              <div key={i} className={`rounded-lg overflow-hidden border transition-all ${isError ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-black/20'}`}>
                <div onClick={() => toggleCmdCollapse(cmd)} className="px-4 py-2 bg-white/5 flex items-center justify-between cursor-pointer hover:bg-white/[0.08]">
                  <div className="flex items-center gap-2 min-w-0">
                    <ChevronRight size={14} className={`text-white/20 transition-transform shrink-0 ${isCollapsed ? '' : 'rotate-90'}`} />
                    <span className={`text-[11px] font-mono font-bold truncate ${isError ? 'text-red-400' : 'text-cyan-400/80'}`}>&gt; {cmd}</span>
                  </div>
                  {!isCollapsed && (
                    <div className="flex items-center gap-1 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-white/5 border border-white/10 mr-1">
                        <button onClick={() => setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }))} className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${(!inspParseViewMode[blockKey] || inspParseViewMode[blockKey] === 'raw') ? 'bg-white/10 text-white' : 'text-white/30 hover:text-white/60'}`}>Raw</button>
                        <button onClick={() => { if (!parseState || (!parseState.data && !parseState.loading)) { onParseCmd(blockKey, res.platform || 'cisco_ios', cmd, outputStr); } else { setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' })); } }} className={`flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-bold transition-all ${(inspParseViewMode[blockKey] === 'parsed') ? 'bg-white/10 text-cyan-400' : 'text-white/30 hover:text-white/60'}`}>
                          {parseState?.loading ? <Loader2 size={9} className="animate-spin" /> : 'Parsed'}
                        </button>
                      </div>
                      <ActionIconButton icon={isCopied ? Check : Copy} label={zh ? '复制' : 'Copy'} variant={isCopied ? 'success' : 'accent'} onClick={() => onCopyText(outputStr, blockKey)} />
                      <ActionIconButton icon={Download} label={zh ? '下载原始文本 (.txt)' : 'Download raw .txt'} variant="accent" onClick={() => { const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40); const blob = new Blob([outputStr], { type: 'text/plain' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `${res.hostname}_${safeCmd}.txt`; a.click(); URL.revokeObjectURL(url); }} />
                      <button onClick={() => { if (!parseState || (!parseState.data && !parseState.loading)) { onParseCmd(blockKey, res.platform || 'cisco_ios', cmd, outputStr); } }} disabled={parseState?.loading} className={`flex items-center gap-1 px-2 py-1 rounded border text-[9px] font-mono transition-all ${parseState?.data ? 'bg-cyan-900/40 border-cyan-500/40 text-cyan-300' : parseState?.error ? 'bg-amber-900/20 border-amber-500/30 text-amber-400/60' : 'bg-white/5 border-white/10 text-white/30 hover:text-cyan-400 hover:border-cyan-500/40'}`} title={parseState?.error || (zh ? '用 TextFSM 解析' : 'Parse with TextFSM')}>
                        {parseState?.loading ? <Loader2 size={11} className="animate-spin" /> : <Table2 size={11} />}
                        <span>{parseState?.data ? (zh ? '已解析' : 'Parsed') : (zh ? '解析' : 'Parse')}</span>
                      </button>
                    </div>
                  )}
                  {isCollapsed && (
                    <span className="text-[10px] text-white/20 font-mono italic truncate max-w-[300px]">
                      {outputStr.substring(0, 60).replace(/\n/g, ' ')}...
                    </span>
                  )}
                </div>
                {!isCollapsed && (
                  <div className={`p-4 font-mono text-[11px] ${inspParseViewMode[blockKey] === 'parsed' ? '' : 'whitespace-pre-wrap'} leading-relaxed ${isError ? 'text-red-300/80' : 'text-white/60'}`}>
                    {inspParseViewMode[blockKey] === 'parsed' ? (
                      <>
                        {parseState?.loading ? (
                          <div className="flex items-center gap-2 py-4 text-cyan-400/50"><Loader2 size={16} className="animate-spin" /><span>{zh ? '正在解析中...' : 'Parsing...'}</span></div>
                        ) : parseState?.error ? (
                          <div className="py-4 text-amber-500/80 italic">⚠ {parseState.error}</div>
                        ) : parseState?.data?.records ? (
                          parseState.data.records.length > 0 ? (
                            <ParsedInspectionOutputTable
                              data={parseState.data}
                              filename={`${res.hostname}_${cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40)}_parsed`}
                              zh={zh}
                              onDownloadJson={() => {
                                const safeCmd = cmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                downloadInspJSON(parseState.data.records, `${res.hostname}_${safeCmd}_parsed`);
                              }}
                            />
                          ) : (
                            <div className="py-4 text-white/20 italic">{zh ? '未解析或解析无结果' : 'Not parsed or no results'}</div>
                          )
                        ) : (
                          <div className="py-4 text-white/20 italic">{zh ? '未解析或解析无结果' : 'Not parsed or no results'}</div>
                        )}
                      </>
                    ) : (
                      outputStr
                    )}
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <div className="text-white/20 text-center py-10 italic text-[11px]">
            {res.ssh_ok ? (zh ? '无命令回显' : 'No output returned') : (zh ? '连接未建立' : 'Connection failed')}
          </div>
        )}
      </div>
    </div>
  </>
);

/* ═══════════════════════════════════════════════════════ */
/*  Configuration Backup Batch Detail                     */
/* ═══════════════════════════════════════════════════════ */

const ConfigBackupRunView: React.FC<{
  zh: boolean;
  selectedLog: UnifiedExecutionLog;
  detail: ConfigBackupRunDetail | null;
  error: string;
  loading: boolean;
  page: number;
  statusFilter: BackupDetailStatus;
  onPageChange: (page: number) => void;
  onStatusFilterChange: (status: BackupDetailStatus) => void;
  onRetry: () => void;
}> = ({ zh, selectedLog, detail, error, loading, page, statusFilter, onPageChange, onStatusFilterChange, onRetry }) => {
  const counts = [
    { label: zh ? '設備總數' : 'Total', value: selectedLog.total_devices, tone: 'text-slate-700' },
    { label: zh ? '成功' : 'Success', value: selectedLog.success_count, tone: 'text-emerald-600' },
    { label: zh ? '失败' : 'Failed', value: selectedLog.failed_count, tone: 'text-rose-600' },
    { label: zh ? '部分完成' : 'Partial', value: selectedLog.partial_count || 0, tone: 'text-amber-600' },
    { label: zh ? '跳过' : 'Skipped', value: selectedLog.skipped_count || 0, tone: 'text-slate-500' },
  ];
  const filters: Array<{ key: BackupDetailStatus; label: string }> = [
    { key: 'all', label: zh ? '全部' : 'All' },
    { key: 'success', label: zh ? '成功' : 'Success' },
    { key: 'failed', label: zh ? '失败' : 'Failed' },
    { key: 'unknown', label: zh ? '未知' : 'Unknown' },
    { key: 'skipped', label: zh ? '跳过' : 'Skipped' },
  ];
  const statusLabel = (status: string) => {
    const normalized = status.toLowerCase();
    if (['success', 'completed'].includes(normalized)) return zh ? '成功' : 'Success';
    if (['failed', 'error', 'unreachable'].includes(normalized)) return zh ? '失败' : 'Failed';
    if (normalized === 'skipped') return zh ? '跳过' : 'Skipped';
    if (['unknown', 'pending'].includes(normalized)) return zh ? '未知' : 'Unknown';
    return status || (zh ? '未知' : 'Unknown');
  };
  const statusTone = (status: string) => {
    const normalized = status.toLowerCase();
    if (['success', 'completed'].includes(normalized)) return 'bg-emerald-50 text-emerald-700';
    if (['failed', 'error', 'unreachable'].includes(normalized)) return 'bg-rose-50 text-rose-700';
    if (normalized === 'skipped') return 'bg-slate-100 text-slate-600';
    return 'bg-amber-50 text-amber-700';
  };
  const needsReason = (status: string) => ['failed', 'error', 'unreachable', 'unknown', 'skipped'].includes(status.toLowerCase());

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50/50">
      <div className="shrink-0 border-b border-black/5 bg-white px-5 py-4">
        <div className="flex flex-wrap gap-2">
          {counts.map((count) => (
            <div key={count.label} className="min-w-[90px] rounded-xl border border-black/5 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-medium text-black/40">{count.label}</div>
              <div className={`mt-0.5 text-sm font-bold tabular-nums ${count.tone}`}>{count.value}</div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[10px] text-black/35">
            {zh ? '只读批次结果；设备配置内容不会显示在此处。' : 'Read-only batch outcomes. Device configuration content is not shown here.'}
          </span>
          <div className="flex flex-wrap items-center gap-1 rounded-xl bg-black/[0.04] p-1">
            {filters.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => onStatusFilterChange(filter.key)}
                disabled={loading}
                className={`rounded-lg px-2.5 py-1.5 text-[10px] font-semibold transition-colors disabled:opacity-50 ${statusFilter === filter.key ? 'bg-white text-cyan-800 shadow-sm' : 'text-black/45 hover:text-black/70'}`}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {error ? (
          <div role="alert" className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-2xl border border-rose-100 bg-rose-50 px-5 py-8 text-center text-rose-700">
            <AlertTriangle size={20} />
            <p className="text-xs font-semibold">{error}</p>
            <button type="button" onClick={onRetry} className="mt-1 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-[10px] font-semibold text-rose-700 hover:bg-rose-100">{zh ? '重试' : 'Retry'}</button>
          </div>
        ) : loading ? (
          <div className="flex min-h-40 items-center justify-center gap-2 text-xs text-black/35"><RotateCcw size={16} className="animate-spin" />{zh ? '正在加载设备结果…' : 'Loading device results…'}</div>
        ) : !detail?.devices.length ? (
          <div className="flex min-h-40 items-center justify-center rounded-2xl border border-dashed border-black/10 text-xs text-black/35">
            {detail?.total === 0 && statusFilter === 'all' ? (zh ? '该批次没有设备结果' : 'This batch has no device results') : (zh ? '此筛选条件下没有设备结果' : 'No device results match this filter')}
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-black/5 bg-white">
            <table className="w-full min-w-[820px] border-collapse text-left">
              <thead>
                <tr className="border-b border-black/5 bg-slate-50 text-[10px] font-bold uppercase tracking-wide text-black/40">
                  <th className="px-3 py-3">{zh ? '设备' : 'Device'}</th>
                  <th className="px-3 py-3">IP</th>
                  <th className="px-3 py-3">{zh ? '状态' : 'Status'}</th>
                  <th className="px-3 py-3">{zh ? '原因' : 'Reason'}</th>
                  <th className="px-3 py-3">{zh ? '详细说明' : 'Details'}</th>
                  <th className="px-3 py-3 text-right">{zh ? '耗时' : 'Duration'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.04]">
                {detail.devices.map((device, index) => (
                  <tr key={device.device_id || device.ip_address || `${device.hostname || 'device'}-${index}`} className="align-top hover:bg-slate-50/60">
                    <td className="max-w-[220px] px-3 py-3 text-xs font-semibold text-blue-900">{device.hostname || device.device_id || '--'}</td>
                    <td className="whitespace-nowrap px-3 py-3 font-mono text-[11px] text-black/55">{device.ip_address || '--'}</td>
                    <td className="whitespace-nowrap px-3 py-3"><span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-bold ${statusTone(device.status)}`}>{statusLabel(device.status)}</span></td>
                    <td className="max-w-[240px] break-words px-3 py-3 text-[11px] text-black/65">{needsReason(device.status) ? (device.reason || '--') : '—'}</td>
                    <td className="max-w-[360px] break-words px-3 py-3 text-[11px] leading-relaxed text-black/50">{['failed', 'error', 'unreachable'].includes(device.status.toLowerCase()) ? (device.detail || '--') : '—'}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-right font-mono text-[10px] text-black/40">{device.duration_ms == null ? '--' : `${device.duration_ms} ms`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {!!detail && detail.total > detail.page_size && (
        <div className="shrink-0 border-t border-black/5 bg-white px-4 py-2">
          <Pagination currentPage={page} totalItems={detail.total} itemsPerPage={detail.page_size} onPageChange={onPageChange} language={zh ? 'zh' : 'en'} />
        </div>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════ */
/*  Playbook Detail Sub-View                               */
/* ═══════════════════════════════════════════════════════ */

const PlaybookView: React.FC<{
  zh: boolean; isLinuxOutput: boolean; pbDevices: any[]; selectedPbDevice: any; pbDeviceDetail: any;
  onSelectPbDevice: (deviceId: string) => void; devices: Device[];
  collapsedCmds: Record<string, boolean>; toggleCmdCollapse: (cmd: string) => void;
  setCollapsedCmds: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
}> = ({ zh, isLinuxOutput, pbDevices, selectedPbDevice, pbDeviceDetail, onSelectPbDevice, devices, collapsedCmds, toggleCmdCollapse, setCollapsedCmds }) => (
  <div className="flex flex-col md:flex-row h-full">
    {/* Device List (Left) */}
    <div className="w-full md:w-4/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
      <div className="p-4 border-b border-black/5 bg-white">
        <span className="text-xs font-bold text-black/50">{zh ? '执行设备情况' : 'Device Execution'}</span>
      </div>
      <div className="flex-1 overflow-auto p-2 space-y-1">
        {pbDevices.map((dev) => {
          const stMap: Record<string, { cls: string; label: string }> = {
            success: { cls: 'bg-emerald-500', label: zh ? '正常' : 'Pass' },
            completed: { cls: 'bg-emerald-500', label: zh ? '正常' : 'Pass' },
            failed: { cls: 'bg-red-500', label: zh ? '异常' : 'Fail' },
            error: { cls: 'bg-red-500', label: zh ? '异常' : 'Fail' },
            partial: { cls: 'bg-amber-500', label: zh ? '部分异常' : 'Partial' },
            partial_failure: { cls: 'bg-amber-500', label: zh ? '部分异常' : 'Partial' },
            running: { cls: 'bg-cyan-500 animate-pulse', label: zh ? '运行中' : 'Live' },
          };
          const dst = stMap[dev.status || ''] || { cls: 'bg-slate-400', label: dev.status || (zh ? '未知' : 'Unknown') };
          const isSelected = selectedPbDevice === dev.device_id;

          return (
            <div
              key={dev.device_id}
              onClick={() => onSelectPbDevice(dev.device_id)}
              className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition-all ${
                isSelected ? 'bg-blue-700 text-white border-transparent shadow-md' : 'bg-white border-black/5 hover:border-black/10 hover:shadow-sm'
              }`}
            >
              <div className="min-w-0">
                <p className={`text-xs font-bold truncate ${isSelected ? 'text-white' : 'text-blue-900'}`}>{dev.hostname}</p>
                <p className={`text-[10px] font-mono mt-0.5 ${isSelected ? 'text-white/60' : 'text-black/30'}`}>{dev.ip_address}</p>
              </div>
              <span className={`text-[9px] font-bold text-white px-2 py-0.5 rounded-md ${dst.cls}`}>{dst.label}</span>
            </div>
          );
        })}
      </div>
    </div>

    {/* Command Output (Right) */}
    <div className={`flex-1 flex flex-col overflow-hidden ${isLinuxOutput ? 'bg-white' : 'bg-[#1E1E1E]'}`}>
      <div className={`p-4 border-b flex items-center justify-between ${isLinuxOutput ? 'border-black/10 bg-slate-50' : 'border-white/10 bg-black/20'}`}>
        <div>
          <span className={`text-xs font-bold block ${isLinuxOutput ? 'text-black' : 'text-white/80'}`}>
            {selectedPbDevice 
              ? (pbDevices.find((d: any) => d.device_id === selectedPbDevice)?.hostname || '') 
              : (zh ? '请选择设备查看命令输出' : 'Select a device to view command outputs')}
          </span>
          {selectedPbDevice && (() => {
            const dev = devices.find(d => d.id === selectedPbDevice);
            if (!dev) return null;
            return (
              <div className="flex items-center gap-3 mt-1.5">
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-tighter ${isLinuxOutput ? 'text-black/55 bg-black/5' : 'text-white/40 bg-white/5'}`}>PLAT: {dev.platform || '-'}</span>
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-tighter ${isLinuxOutput ? 'text-black/55 bg-black/5' : 'text-white/40 bg-white/5'}`}>ROLE: {dev.role || '-'}</span>
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-tighter ${isLinuxOutput ? 'text-black/55 bg-black/5' : 'text-white/40 bg-white/5'}`}>SITE: {dev.site || '-'}</span>
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded uppercase tracking-tighter ${isLinuxOutput ? 'text-black/55 bg-black/5' : 'text-white/40 bg-white/5'}`}>MOD: {dev.model || '-'}</span>
              </div>
            );
          })()}
        </div>
        {selectedPbDevice && pbDeviceDetail?.phases && (
          <div className="flex items-center gap-3">
            <button 
              onClick={() => {
                const next = { ...collapsedCmds };
                Object.entries(pbDeviceDetail.phases).forEach(([ph, pdata]: any) => {
                  const cmds = (pdata || {}).commands || [];
                  const outStr = typeof (pdata || {}).output === 'string' ? pdata.output : JSON.stringify((pdata || {}).output || '');
                  const blocks = splitOutputByCommand(outStr, cmds);
                  blocks.forEach((_, bi) => next[`pb_${selectedPbDevice}_${ph}_${bi}`] = false);
                });
                setCollapsedCmds(next);
              }}
              className={`text-[10px] font-bold transition-colors cursor-pointer ${isLinuxOutput ? 'text-black/55 hover:text-black' : 'text-cyan-400/60 hover:text-cyan-400'}`}
            >
              {zh ? '全部展开' : 'Expand All'}
            </button>
            <div className={`w-px h-2.5 ${isLinuxOutput ? 'bg-black/10' : 'bg-white/10'}`} />
            <button 
              onClick={() => {
                const next = { ...collapsedCmds };
                Object.entries(pbDeviceDetail.phases).forEach(([ph, pdata]: any) => {
                  const cmds = (pdata || {}).commands || [];
                  const outStr = typeof (pdata || {}).output === 'string' ? pdata.output : JSON.stringify((pdata || {}).output || '');
                  const blocks = splitOutputByCommand(outStr, cmds);
                  blocks.forEach((_, bi) => next[`pb_${selectedPbDevice}_${ph}_${bi}`] = true);
                });
                setCollapsedCmds(next);
              }}
              className={`text-[10px] font-bold transition-colors cursor-pointer ${isLinuxOutput ? 'text-black/45 hover:text-black' : 'text-white/30 hover:text-white/60'}`}
            >
              {zh ? '全部折叠' : 'Collapse All'}
            </button>
          </div>
        )}
      </div>
      <div className={`flex-1 p-6 font-mono text-xs overflow-auto whitespace-pre-wrap select-text relative ${isLinuxOutput ? 'bg-white text-black' : 'bg-[#1E1E1E] text-[#d4d4d4]'}`}>
        {pbDeviceDetail?.phases ? (
          Object.entries(pbDeviceDetail.phases).map(([phase, pdata]: any) => {
            const pd = pdata || {};
            const cmds = pd.commands || [];
            const outputStr = typeof pd.output === 'string' ? pd.output : JSON.stringify(pd.output || '');
            const blocks = splitOutputByCommand(outputStr, cmds);
            const dev = devices.find(d => d.id === selectedPbDevice);

            return (
              <div key={phase} className="mb-6 group/phase">
                <div className="flex items-center gap-2 mb-3">
                  <div className={`h-px flex-1 ${isLinuxOutput ? 'bg-black/10' : 'bg-white/5'}`} />
                  <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${isLinuxOutput ? 'text-black/50' : 'text-[#a170e8]'}`}># PHASE: {phase.toUpperCase()}</span>
                  <div className={`h-px flex-1 ${isLinuxOutput ? 'bg-black/10' : 'bg-white/5'}`} />
                </div>
                
                <div className="space-y-3">
                  {blocks.map((blk, bi) => {
                    const rawOutput = blk.output || '';
                    const bOutput = isLinuxOutput ? stripLinuxHealthRating(rawOutput) : rawOutput;
                    const bIsError = !isLinuxOutput && (bOutput.includes('__ERROR__') || bOutput.includes('% Invalid input') || bOutput.includes('error'));
                    const bKey = `pb_${selectedPbDevice}_${phase}_${bi}`;
                    const isCollapsed = collapsedCmds[bKey] ?? false;
                    
                    return (
                      <div key={bi} className={`rounded-lg overflow-hidden border transition-all ${isLinuxOutput ? 'border-black/10 bg-white' : bIsError ? 'border-red-500/30 bg-red-500/5' : 'border-white/5 bg-black/20'}`}>
                        <div 
                          onClick={() => toggleCmdCollapse(bKey)}
                          className={`px-4 py-2 flex items-center justify-between cursor-pointer select-none ${isLinuxOutput ? 'bg-slate-50 hover:bg-slate-100' : 'bg-white/5 hover:bg-white/[0.08]'}`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <ChevronRight size={14} className={`shrink-0 transition-transform duration-200 ${isLinuxOutput ? 'text-black/35' : 'text-white/20'} ${isCollapsed ? '' : 'rotate-90'}`} />
                            <span className={`text-[11px] font-mono font-bold truncate ${isLinuxOutput ? 'text-black/75' : bIsError ? 'text-red-400' : 'text-cyan-400/80'}`}>&gt; {blk.command || 'system'}</span>
                          </div>
                          <div className="flex items-center gap-2 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                            {isCollapsed && (
                              <span className={`text-[10px] font-mono italic truncate max-w-[250px] hidden sm:inline ${isLinuxOutput ? 'text-black/45' : 'text-white/30'}`}>
                                {bOutput.substring(0, 60).replace(/\n/g, ' ')}...
                              </span>
                            )}
                            <OutputActions
                              text={bOutput}
                              filename={`${dev?.hostname || 'device'}_${phase}_cmd${bi}`}
                              theme={isLinuxOutput ? 'light' : 'dark'}
                              zh={zh}
                              iconOnly={true}
                            />
                          </div>
                        </div>
                        {!isCollapsed && (
                          <div className={`p-4 font-mono text-xs whitespace-pre-wrap leading-relaxed ${isLinuxOutput ? 'text-black' : bIsError ? 'text-red-300/80' : 'text-[#d4d4d4]'}`}>
                            {bOutput || (pd.status === 'success' ? (zh ? '命令执行成功，但无回显' : 'Success, no output') : '—')}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
        ) : (
          <div className={`text-center py-24 select-none ${isLinuxOutput ? 'text-black/35' : 'text-white/20'}`}>{zh ? '无命令输出' : 'No command output'}</div>
        )}
      </div>
    </div>
  </div>
);

export default ExecutionDetail;
