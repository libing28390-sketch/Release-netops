import React from 'react';
import { Download } from 'lucide-react';
import * as XLSX from 'xlsx';
import type { AuditEvent } from '../types';
import { sectionHeaderRowClass, severityBadgeClass, auditStatusBadgeClass } from '../components/shared';
import Pagination from '../components/Pagination';

interface HistoryTabProps {
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

const HistoryTab: React.FC<HistoryTabProps> = ({
  auditRows, auditTotal, auditPage, setAuditPage,
  auditPageSize, setAuditPageSize, auditLoading,
  auditCategoryFilter, setAuditCategoryFilter,
  auditSeverityFilter, setAuditSeverityFilter,
  auditStatusFilter, setAuditStatusFilter,
  auditTimeFilter, setAuditTimeFilter,
  openAuditEventDetail, language, t,
}) => {
  const handleExportAudit = () => {
    if (auditRows.length === 0) return;
    const exportData = auditRows.map(e => ({
      Timestamp: new Date(e.created_at).toLocaleString(),
      Action: e.summary,
      'Event Type': e.event_type,
      Category: e.category,
      Severity: e.severity,
      Target: e.target_name || e.target_id || e.device_id || '',
      User: e.actor_username || 'system',
      Status: e.status,
      'Source IP': e.source_ip || '',
    }));
    const ws = XLSX.utils.json_to_sheet(exportData);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Audit Logs');
    const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
    XLSX.writeFile(wb, `audit_logs_${ts}.xlsx`);
  };

  return (
    <div className="space-y-6">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-medium tracking-tight">{t('auditLogsTitle')}</h2>
          <p className="text-sm text-black/40">{t('fullHistory')}</p>
        </div>
        <button onClick={handleExportAudit} className="inline-flex items-center gap-2 rounded-xl border border-black/10 bg-white px-4 py-2 text-sm font-medium text-black/60 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all" title={language === 'zh' ? '导出审计日志' : 'Export Audit Logs'}>
          <Download size={14} />
          {language === 'zh' ? '导出' : 'Export'}
        </button>
      </div>

      <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="p-4 bg-black/[0.02] border-b border-black/5 flex gap-4 flex-wrap">
          <select
            value={auditCategoryFilter}
            onChange={(e) => setAuditCategoryFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{language === 'zh' ? '全部分类' : 'All Categories'}</option>
            <option value="auth">Auth</option>
            <option value="inventory">Inventory</option>
            <option value="execution">Execution</option>
            <option value="config">Config</option>
            <option value="playbook">Playbook</option>
            <option value="template">Template</option>
            <option value="compliance">Compliance</option>
          </select>
          <select
            value={auditSeverityFilter}
            onChange={(e) => setAuditSeverityFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{language === 'zh' ? '全部级别' : 'All Severity'}</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            value={auditStatusFilter}
            onChange={(e) => setAuditStatusFilter(e.target.value)}
            className="bg-white border border-black/10 rounded-lg px-3 py-1.5 text-xs outline-none"
          >
            <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
            <option value="success">Success</option>
            <option value="warning">Warning</option>
            <option value="failed">Failed</option>
            <option value="completed">Completed</option>
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
        <table className="w-full text-left border-collapse">
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
                  <div className="text-sm font-medium text-[#0b2a3c]">{event.summary}</div>
                  <div className="mt-1 text-[11px] text-black/35 font-mono">{event.event_type}</div>
                </td>
                <td className="px-6 py-4 text-xs text-black/55">{event.category}</td>
                <td className="px-6 py-4 text-xs">{event.target_name || event.target_id || event.device_id || 'Unknown'}</td>
                <td className="px-6 py-4 text-xs text-black/40">{event.actor_username || 'system'}</td>
                <td className="px-6 py-4">
                  <div className="flex flex-col gap-2">
                    <span className={`inline-flex w-fit px-2 py-1 rounded text-[10px] font-bold uppercase ${auditStatusBadgeClass(event.status)}`}>
                      {event.status}
                    </span>
                    <span className={`inline-flex w-fit px-2 py-1 rounded text-[10px] font-bold uppercase ${severityBadgeClass(event.severity)}`}>
                      {event.severity}
                    </span>
                  </div>
                </td>
                <td className="px-6 py-4">
                  <button
                    onClick={() => openAuditEventDetail(event)}
                    className="text-[10px] font-bold uppercase text-blue-600 hover:underline"
                  >
                    {language === 'zh' ? '详情' : 'Details'}
                  </button>
                </td>
              </tr>
            ))}
            {!auditLoading && auditRows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-black/40">{language === 'zh' ? '当前筛选条件下没有审计日志。' : 'No audit logs found for current filters.'}</td>
              </tr>
            )}
            {auditLoading && auditRows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-black/40">{language === 'zh' ? '正在加载审计日志...' : 'Loading audit logs...'}</td>
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
  );
};

export default HistoryTab;
