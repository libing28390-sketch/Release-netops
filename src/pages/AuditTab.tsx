import { DataTable } from '../components/DataTable';
import React from 'react';
import { ClipboardList, Eye, RotateCcw } from 'lucide-react';
import type { AuditEvent } from '../types';
import { severityBadgeClass, auditStatusBadgeClass } from '../components/shared';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton } from '../components/ui/ActionIconButton';
import { SelectField } from '../components/ui/FormField';
import type { TableExportData } from '../components/ui/TableExportMenu';
import { fetchAllPaginatedItems } from '../utils/pagination';
import { buildAuditExportData, getAuditExportHeaders } from './auditTableExport';

import { TableActionCell, TableActionHeader } from '../components/ui/TableActionColumn';

interface AuditTabProps {
  auditRows: AuditEvent[];
  auditTotal: number;
  auditPage: number;
  setAuditPage: (v: number) => void;
  auditPageSize: number;
  setAuditPageSize: (v: number) => void;
  auditLoading: boolean;
  auditCategoryFilter: string;
  setAuditCategoryFilter: (v: string) => void;
  auditSeverityFilter: string;
  setAuditSeverityFilter: (v: string) => void;
  auditStatusFilter: string;
  setAuditStatusFilter: (v: string) => void;
  auditTimeFilter: string;
  setAuditTimeFilter: (v: string) => void;
  openAuditEventDetail: (event: AuditEvent) => void;
  language: string;
  t: (key: string) => string;
}

const AuditTab: React.FC<AuditTabProps> = ({
  auditRows, auditTotal, auditPage, setAuditPage,
  auditPageSize, setAuditPageSize, auditLoading,
  auditCategoryFilter, setAuditCategoryFilter,
  auditSeverityFilter, setAuditSeverityFilter,
  auditStatusFilter, setAuditStatusFilter,
  auditTimeFilter, setAuditTimeFilter,
  openAuditEventDetail, language, t,
}) => {
  const zh = language === 'zh';
  const exportHeaders = getAuditExportHeaders(language);
  const hasActiveFilters = [auditCategoryFilter, auditSeverityFilter, auditStatusFilter, auditTimeFilter].some(value => value !== 'all');
  const resetFilters = () => {
    setAuditCategoryFilter('all');
    setAuditSeverityFilter('all');
    setAuditStatusFilter('all');
    setAuditTimeFilter('all');
    setAuditPage(1);
  };

  const categoryMap: Record<string, string> = {
    auth: '身份认证', identity: '身份认证', inventory: '资产管理',
    execution: '命令执行', automation: '自动化', config: '配置管理',
    playbook: '剧本', template: '模板', compliance: '合规审计',
    system: '系统', credential: '凭据管理',
  };
  const statusMap: Record<string, string> = {
    success: '成功', warning: '警告', failed: '失败', completed: '已完成', error: '错误', pending: '待处理',
  };
  const severityMap: Record<string, string> = {
    critical: '严重', high: '高', medium: '中', low: '低',
  };
  const fmtCategory = (v: string) => zh ? (categoryMap[v?.toLowerCase()] || v) : v;
  const fmtStatus = (v: string) => zh ? (statusMap[v?.toLowerCase()] || v) : v;
  const fmtSeverity = (v: string) => zh ? (severityMap[v?.toLowerCase()] || v) : v;

  /* ── summary / event_type translation ── */
  const eventTypeMap: Record<string, string> = {
    LOGIN_SUCCESS: '登录成功', LOGIN_FAILED: '登录失败', LOGOUT: '退出登录',
    USER_CREATE: '创建用户', USER_UPDATE: '更新用户', USER_DELETE: '删除用户',
    DEVICE_CREATE: '新增设备', DEVICE_UPDATE: '更新设备', DEVICE_DELETE: '删除设备',
    DIRECT_EXECUTION: '直接执行命令', COMMAND_EXECUTION: '命令执行',
    BACKUP_CREATE: '创建备份', BACKUP_RESTORE: '恢复备份',
    CONFIG_CHANGE: '配置变更', CONFIG_DIFF: '配置比对',
    PLAYBOOK_RUN: '执行剧本', PLAYBOOK_CREATE: '创建剧本',
    TEMPLATE_CREATE: '创建模板', TEMPLATE_UPDATE: '更新模板',
    COMPLIANCE_RUN: '合规检查', COMPLIANCE_REMEDIATE: '合规修复',
    PASSWORD_ROTATE: '密码轮换', CREDENTIAL_UPDATE: '凭据更新',
    // PAM events
    'PAM.SESSION.CREATED':       'PAM 会话创建',
    'PAM.SESSION.CONNECTED':     'PAM 会话连接',
    'PAM.SESSION.CLOSED':        'PAM 会话关闭',
    'PAM.SESSION.KILLED':        'PAM 会话强制终止',
    'PAM.SESSION.LOCAL_LAUNCH':  'PAM 本地终端拉起',
  };
  const fmtEventType = (v: string) => zh ? (eventTypeMap[v?.toUpperCase()] || v) : v;
  const summaryPatterns: Array<[RegExp, (...m: string[]) => string]> = [
    [/^User (\S+) logged in$/i, (_, u) => `用户 ${u} 登录`],
    [/^User (\S+) logged out$/i, (_, u) => `用户 ${u} 退出`],
    [/^Updated user (\S+)$/i, (_, u) => `更新用户 ${u}`],
    [/^Created user (\S+)$/i, (_, u) => `创建用户 ${u}`],
    [/^Deleted user (\S+)$/i, (_, u) => `删除用户 ${u}`],
    [/^Executed Direct Command on (\S+)$/i, (_, d) => `在 ${d} 上执行命令`],
    [/^Executed command on (\S+)$/i, (_, d) => `在 ${d} 上执行命令`],
    [/^Backed up (\S+)$/i, (_, d) => `备份 ${d}`],
    [/^Restored config on (\S+)$/i, (_, d) => `恢复 ${d} 配置`],
    [/^Rotated password for (\S+)$/i, (_, d) => `轮换 ${d} 密码`],
    [/^Created device (\S+)$/i, (_, d) => `新增设备 ${d}`],
    [/^Updated device (\S+)$/i, (_, d) => `更新设备 ${d}`],
    [/^Deleted device (\S+)$/i, (_, d) => `删除设备 ${d}`],
    [/^Ran compliance audit$/i, () => '执行合规审计'],
    [/^Ran playbook (.+) on (.+)$/i, (_, p, d) => `在 ${d} 执行剧本 ${p}`],
    // PAM patterns
    [/^PAM session created for (.+) \((\w+)\)$/i, (_, h, l) => `PAM 会话创建: ${h}（${l === 'admin' ? '特权' : '普通'}）`],
    [/^PAM terminal connected: (\S+)@(\S+)/i, (_, u, h) => `PAM 终端连接: ${u}@${h}`],
    [/^PAM terminal closed: session (\S+)/i, (_, s) => `PAM 会话关闭: ${s}`],
    [/^PAM session (\S+) force-terminated/i, (_, s) => `PAM 会话强制终止: ${s}`],
    [/^Local terminal launched: (\S+)@(\S+) via (\S+)/i, (_, u, h, app) => `本地终端拉起: ${u}@${h}（${app}）`],
  ];
  const fmtSummary = (v: string) => {
    if (!zh) return v;
    for (const [re, fn] of summaryPatterns) {
      const m = v.match(re);
      if (m) return fn(...m);
    }
    return v;
  };

  const exportAllAuditEvents = async (): Promise<TableExportData> => {
    const params = new URLSearchParams({
      category: auditCategoryFilter,
      severity: auditSeverityFilter,
      status: auditStatusFilter,
      time_range: auditTimeFilter,
    });
    const events = await fetchAllPaginatedItems<AuditEvent>('/api/audit/events', params, 100);
    return buildAuditExportData(events, language, {
      timestamp: (value) => new Date(value).toLocaleString(),
      summary: fmtSummary,
      eventType: fmtEventType,
      category: fmtCategory,
      status: fmtStatus,
      severity: fmtSeverity,
      unknownTarget: zh ? '未知' : 'Unknown',
    });
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={ClipboardList}
        title={t('auditLogsTitle')}
        subtitle={t('fullHistory')}
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-6">
      <div className="overflow-hidden rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-sm">
        <div className="border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-[var(--ui-fg)]">{zh ? '筛选审计记录' : 'Filter audit events'}</h2>
              <p className="mt-0.5 text-xs text-[var(--ui-fg-muted)]">{zh ? '组合条件查看相关操作；更改后会返回第一页。' : 'Combine criteria to narrow the audit trail; changes return to page one.'}</p>
            </div>
            <ActionButton icon={RotateCcw} onClick={resetFilters} disabled={!hasActiveFilters}>
              {zh ? '重置筛选' : 'Reset filters'}
            </ActionButton>
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SelectField
              label={zh ? '分类' : 'Category'}
              value={auditCategoryFilter}
              onChange={setAuditCategoryFilter}
              language={zh ? 'zh' : 'en'}
              className="min-w-0"
              options={[
                { value: 'all', label: zh ? '全部分类' : 'All categories' },
                { value: 'auth', label: zh ? '身份认证' : 'Authentication' },
                { value: 'inventory', label: zh ? '资产管理' : 'Inventory' },
                { value: 'execution', label: zh ? '命令执行' : 'Execution' },
                { value: 'config', label: zh ? '配置管理' : 'Configuration' },
                { value: 'playbook', label: zh ? '剧本' : 'Playbook' },
                { value: 'template', label: zh ? '模板' : 'Template' },
                { value: 'compliance', label: zh ? '合规审计' : 'Compliance' },
              ]}
            />
            <SelectField
              label={zh ? '级别' : 'Severity'}
              value={auditSeverityFilter}
              onChange={setAuditSeverityFilter}
              language={zh ? 'zh' : 'en'}
              className="min-w-0"
              options={[
                { value: 'all', label: zh ? '全部级别' : 'All severities' },
                { value: 'critical', label: zh ? '严重' : 'Critical' },
                { value: 'high', label: zh ? '高' : 'High' },
                { value: 'medium', label: zh ? '中' : 'Medium' },
                { value: 'low', label: zh ? '低' : 'Low' },
              ]}
            />
            <SelectField
              label={zh ? '状态' : 'Status'}
              value={auditStatusFilter}
              onChange={setAuditStatusFilter}
              language={zh ? 'zh' : 'en'}
              className="min-w-0"
              options={[
                { value: 'all', label: zh ? '全部状态' : 'All statuses' },
                { value: 'success', label: zh ? '成功' : 'Success' },
                { value: 'warning', label: zh ? '警告' : 'Warning' },
                { value: 'failed', label: zh ? '失败' : 'Failed' },
                { value: 'completed', label: zh ? '已完成' : 'Completed' },
              ]}
            />
            <SelectField
              label={zh ? '时间范围' : 'Time range'}
              value={auditTimeFilter}
              onChange={setAuditTimeFilter}
              language={zh ? 'zh' : 'en'}
              className="min-w-0"
              options={[
                { value: 'all', label: zh ? '全部时间' : 'All time' },
                { value: '24h', label: zh ? '最近 24 小时' : 'Last 24 hours' },
                { value: '7d', label: zh ? '最近 7 天' : 'Last 7 days' },
                { value: '30d', label: zh ? '最近 30 天' : 'Last 30 days' },
              ]}
            />
          </div>
        </div>
        <div className="overflow-x-auto">
        <DataTable unstyled exportConfig={{ filename: 'audit-events', language: zh ? 'zh' : 'en', disabled: auditLoading || auditRows.length === 0, exportData: exportAllAuditEvents }} className="nx-data-table text-left">
          <thead>
            <tr className="border-b border-[var(--ui-border)] bg-[var(--ui-surface-muted)]">
              {exportHeaders.map((header) => <th key={header} className="px-6 py-4 text-[var(--ui-text-caption)] font-semibold uppercase tracking-wide text-[var(--ui-fg-muted)]">{header}</th>)}
              <TableActionHeader className="px-6 py-4 text-[var(--ui-text-caption)] font-semibold uppercase tracking-wide text-[var(--ui-fg-muted)]">{language === 'zh' ? '操作' : 'Action'}</TableActionHeader>
            </tr>
          </thead>
          <tbody>
            {auditRows.map((event) => (
              <tr key={event.id} className="border-b border-[var(--ui-border)] transition-colors hover:bg-[var(--ui-surface-muted)]">
                <td className="px-6 py-4 text-xs font-mono text-[var(--ui-fg-muted)]">{new Date(event.created_at).toLocaleString()}</td>
                <td className="px-6 py-4 align-top">
                  <div data-export-primary className="text-sm font-medium text-[var(--ui-fg)]">{fmtSummary(event.summary)}</div>
                </td>
                <td className="px-6 py-4 text-xs font-mono text-[var(--ui-fg-muted)]">{fmtEventType(event.event_type)}</td>
                <td className="px-6 py-4 text-xs text-[var(--ui-fg-muted)]">{fmtCategory(event.category)}</td>
                <td className="px-6 py-4 text-xs">{event.target_name || (zh ? '未知' : 'Unknown')}</td>
                <td className="px-6 py-4 text-xs text-[var(--ui-fg-muted)]">{event.actor_username || 'system'}</td>
                <td className="px-6 py-4"><span data-export-primary className={`inline-flex w-fit px-2 py-1 rounded text-[10px] font-bold uppercase ${auditStatusBadgeClass(event.status)}`}>{fmtStatus(event.status)}</span></td>
                <td className="px-6 py-4"><span className={`inline-flex w-fit px-2 py-1 rounded text-[10px] font-bold uppercase ${severityBadgeClass(event.severity)}`}>{fmtSeverity(event.severity)}</span></td>
                <TableActionCell className="px-6 py-4">
                  <ActionIconButton
                    icon={Eye}
                    label={zh ? '查看详情' : 'View details'}
                    variant="accent"
                    onClick={() => openAuditEventDetail(event)}
                  />
                </TableActionCell>
              </tr>
            ))}
            {!auditLoading && auditRows.length === 0 && (
              <tr>
                <td colSpan={exportHeaders.length + 1} className="px-6 py-8 text-center text-sm text-[var(--ui-fg-muted)]">{zh ? '当前筛选条件下没有审计日志。' : 'No audit logs found for current filters.'}</td>
              </tr>
            )}
            {auditLoading && auditRows.length === 0 && (
              <tr>
                <td colSpan={exportHeaders.length + 1} className="px-6 py-8 text-center text-sm text-[var(--ui-fg-muted)]">{zh ? '正在加载审计日志...' : 'Loading audit logs...'}</td>
              </tr>
            )}
          </tbody>
        </DataTable>
        </div>
        <Pagination
          currentPage={auditPage}
          totalItems={auditTotal}
          itemsPerPage={auditPageSize}
          onItemsPerPageChange={setAuditPageSize}
          onPageChange={setAuditPage}
          language={language}
        />
      </div>
      </div>
    </div>
  );
};

export default AuditTab;
