import React from 'react';
import { Download, ClipboardList } from 'lucide-react';
import * as XLSX from 'xlsx';
import type { AuditEvent } from '../types';
import { severityBadgeClass, auditStatusBadgeClass } from '../components/shared';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { ActionButton } from '../components/ui/ActionIconButton';
import { fetchAllPaginatedItems } from '../utils/pagination';

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

  const handleExportAudit = async () => {
    const params = new URLSearchParams({
      category: auditCategoryFilter,
      severity: auditSeverityFilter,
      status: auditStatusFilter,
      time_range: auditTimeFilter,
    });

    try {
      const allRows = await fetchAllPaginatedItems<AuditEvent>('/api/audit/events', params);
      if (allRows.length === 0) return;
      const exportData = allRows.map(e => ({
        [zh ? '时间' : 'Timestamp']: new Date(e.created_at).toLocaleString(),
        [zh ? '操作' : 'Action']: fmtSummary(e.summary),
        [zh ? '事件类型' : 'Event Type']: fmtEventType(e.event_type),
        [zh ? '分类' : 'Category']: fmtCategory(e.category),
        [zh ? '级别' : 'Severity']: fmtSeverity(e.severity),
        [zh ? '目标' : 'Target']: e.target_name || e.target_id || e.device_id || '',
        [zh ? '用户' : 'User']: e.actor_username || 'system',
        [zh ? '状态' : 'Status']: fmtStatus(e.status),
        [zh ? '来源IP' : 'Source IP']: e.source_ip || '',
      }));
      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Audit Logs');
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      XLSX.writeFile(wb, `audit_logs_${ts}.xlsx`);
    } catch (error) {
      console.error('Failed to export audit logs:', error);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={ClipboardList}
        title={t('auditLogsTitle')}
        subtitle={t('fullHistory')}
        actions={
          <ActionButton icon={Download} variant="accent" size="md" onClick={handleExportAudit} title={language === 'zh' ? '导出审计日志' : 'Export Audit Logs'}>
            {language === 'zh' ? '导出' : 'Export'}
          </ActionButton>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-6">
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="p-4 bg-black/[0.02] border-b border-black/5 flex gap-4 flex-wrap">
          <select
            value={auditCategoryFilter}
            onChange={(e) => setAuditCategoryFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{zh ? '全部分类' : 'All Categories'}</option>
            <option value="auth">{zh ? '身份认证' : 'Auth'}</option>
            <option value="inventory">{zh ? '资产管理' : 'Inventory'}</option>
            <option value="execution">{zh ? '命令执行' : 'Execution'}</option>
            <option value="config">{zh ? '配置管理' : 'Config'}</option>
            <option value="playbook">{zh ? '剧本' : 'Playbook'}</option>
            <option value="template">{zh ? '模板' : 'Template'}</option>
            <option value="compliance">{zh ? '合规审计' : 'Compliance'}</option>
          </select>
          <select
            value={auditSeverityFilter}
            onChange={(e) => setAuditSeverityFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{zh ? '全部级别' : 'All Severity'}</option>
            <option value="critical">{zh ? '严重' : 'Critical'}</option>
            <option value="high">{zh ? '高' : 'High'}</option>
            <option value="medium">{zh ? '中' : 'Medium'}</option>
            <option value="low">{zh ? '低' : 'Low'}</option>
          </select>
          <select
            value={auditStatusFilter}
            onChange={(e) => setAuditStatusFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{zh ? '全部状态' : 'All Status'}</option>
            <option value="success">{zh ? '成功' : 'Success'}</option>
            <option value="warning">{zh ? '警告' : 'Warning'}</option>
            <option value="failed">{zh ? '失败' : 'Failed'}</option>
            <option value="completed">{zh ? '已完成' : 'Completed'}</option>
          </select>
          <select
            value={auditTimeFilter}
            onChange={(e) => setAuditTimeFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{language === 'zh' ? '全部时间' : 'All Time'}</option>
            <option value="24h">{language === 'zh' ? '最近 24 小时' : 'Last 24 Hours'}</option>
            <option value="7d">{language === 'zh' ? '最近 7 天' : 'Last 7 Days'}</option>
            <option value="30d">{language === 'zh' ? '最近 30 天' : 'Last 30 Days'}</option>
          </select>
        </div>
        <div className="overflow-x-auto">
        <table className="nx-data-table text-left">
          <thead>
            <tr className="bg-black/[0.01] border-b border-black/5">
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('timestamp')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('action')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '分类' : 'Category'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('target')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('user')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('status')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '操作' : 'Action'}</th>
            </tr>
          </thead>
          <tbody>
            {auditRows.map((event) => (
              <tr key={event.id} className="border-b border-black/5 hover:bg-black/[0.01] transition-colors">
                <td className="px-6 py-4 text-xs font-mono text-black/50">{new Date(event.created_at).toLocaleString()}</td>
                <td className="px-6 py-4 align-top">
                  <div className="text-sm font-medium text-[#0b2a3c]">{fmtSummary(event.summary)}</div>
                  <div className="mt-1 text-[11px] text-black/35 font-mono">{fmtEventType(event.event_type)}</div>
                </td>
                <td className="px-6 py-4 text-xs text-black/55">{fmtCategory(event.category)}</td>
                <td className="px-6 py-4 text-xs">{event.target_name || event.target_id || event.device_id || (zh ? '未知' : 'Unknown')}</td>
                <td className="px-6 py-4 text-xs text-black/40">{event.actor_username || 'system'}</td>
                <td className="px-6 py-4">
                  <div className="flex flex-col gap-2">
                    <span className={`inline-flex w-fit px-2 py-1 rounded text-[10px] font-bold uppercase ${auditStatusBadgeClass(event.status)}`}>
                      {fmtStatus(event.status)}
                    </span>
                    <span className={`inline-flex w-fit px-2 py-1 rounded text-[10px] font-bold uppercase ${severityBadgeClass(event.severity)}`}>
                      {fmtSeverity(event.severity)}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <button
                    onClick={() => openAuditEventDetail(event)}
                    className="text-[10px] font-bold uppercase text-blue-600 hover:underline"
                  >
                    {zh ? '详情' : 'Details'}
                  </button>
                </td>
              </tr>
            ))}
            {!auditLoading && auditRows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-black/40">{zh ? '当前筛选条件下没有审计日志。' : 'No audit logs found for current filters.'}</td>
              </tr>
            )}
            {auditLoading && auditRows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-black/40">{zh ? '正在加载审计日志...' : 'Loading audit logs...'}</td>
              </tr>
            )}
          </tbody>
        </table>
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
