import React from 'react';
import { Download, RotateCcw, ShieldCheck } from 'lucide-react';
import * as XLSX from 'xlsx';
import type { ComplianceFinding, ComplianceOverview } from '../types';
import { sectionToolbarClass, primaryActionBtnClass, severityBadgeClass, complianceStatusBadgeClass } from '../components/shared';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { ActionButton } from '../components/ui/ActionIconButton';
import { fetchAllPaginatedItems } from '../utils/pagination';

interface ComplianceTabProps {
  complianceOverview: ComplianceOverview | null;
  complianceFindings: ComplianceFinding[];
  complianceFindingTotal: number;
  complianceSeverityFilter: string;
  setComplianceSeverityFilter: (v: string) => void;
  complianceStatusFilter: string;
  setComplianceStatusFilter: (v: string) => void;
  complianceCategoryFilter: string;
  setComplianceCategoryFilter: (v: string) => void;
  compliancePage: number;
  setCompliancePage: (v: number) => void;
  compliancePageSize: number;
  setCompliancePageSize: (v: number) => void;
  complianceLoading: boolean;
  complianceRunLoading: boolean;
  runComplianceAudit: () => void;
  openComplianceFindingDetail: (finding: ComplianceFinding) => void;
  updateComplianceFinding: (id: string, patch: { status?: string; owner?: string; note?: string }) => void;
  language: string;
  t: (key: string) => string;
}

const ComplianceTab: React.FC<ComplianceTabProps> = ({
  complianceOverview, complianceFindings, complianceFindingTotal,
  complianceSeverityFilter, setComplianceSeverityFilter,
  complianceStatusFilter, setComplianceStatusFilter,
  complianceCategoryFilter, setComplianceCategoryFilter,
  compliancePage, setCompliancePage, compliancePageSize, setCompliancePageSize,
  complianceLoading, complianceRunLoading,
  runComplianceAudit, openComplianceFindingDetail, updateComplianceFinding,
  language, t,
}) => {
  const handleExportCompliance = async () => {
    const params = new URLSearchParams({
      severity: complianceSeverityFilter,
      status: complianceStatusFilter,
      category: complianceCategoryFilter,
    });

    try {
      const allFindings = await fetchAllPaginatedItems<ComplianceFinding>('/api/compliance/findings', params);
      if (allFindings.length === 0) return;
      const exportData = allFindings.map(f => ({
        Title: f.title,
        'Rule ID': f.rule_id,
        Hostname: f.hostname || '',
        IP: f.ip_address || '',
        Severity: f.severity,
        Category: f.category,
        Status: f.status,
        Description: f.description,
        Remediation: f.remediation || '',
        Owner: f.owner || '',
        'First Seen': f.first_seen ? new Date(f.first_seen).toLocaleString() : '',
        'Last Seen': f.last_seen ? new Date(f.last_seen).toLocaleString() : '',
        'Resolved At': f.resolved_at ? new Date(f.resolved_at).toLocaleString() : '',
      }));
      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Compliance');
      const ts = new Date().toISOString().replace(/[-:]/g, '').replace('T', '_').slice(0, 15);
      XLSX.writeFile(wb, `compliance_findings_${ts}.xlsx`);
    } catch (error) {
      console.error('Failed to export compliance findings:', error);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={ShieldCheck}
        title={t('complianceStandards')}
        subtitle={t('auditGolden')}
        actions={
          <>
            {(complianceOverview as any)?.recent_runs?.[0]?.started_at && (
              <span className="text-xs text-black/40">
                {language === 'zh' ? '最近审计' : 'Last audit'}: {new Date((complianceOverview as any).recent_runs[0].started_at).toLocaleString()}
              </span>
            )}
            <ActionButton
              icon={Download}
              variant="accent"
              onClick={handleExportCompliance}
              title={language === 'zh' ? '导出合规报告' : 'Export Compliance'}
            >
              {language === 'zh' ? '导出' : 'Export'}
            </ActionButton>
            <button
              onClick={runComplianceAudit}
              disabled={complianceRunLoading}
              className={`${primaryActionBtnClass} disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {complianceRunLoading ? <RotateCcw size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
              {language === 'zh' ? '执行审计' : 'Run Audit'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-8">

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-2xl border border-black/5 shadow-sm lg:col-span-1">
          <h3 className="text-sm font-semibold mb-4">{t('complianceScore')}</h3>
          <div className="flex items-center justify-center h-32">
            <div className="relative w-28 h-28">
              <svg className="w-full h-full -rotate-90" viewBox="0 0 36 36">
                <path className="text-black/5" strokeDasharray="100, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="currentColor" strokeWidth="3" />
                <path
                  className={((complianceOverview as any)?.score ?? 0) >= 85 ? 'text-emerald-500' : ((complianceOverview as any)?.score ?? 0) >= 65 ? 'text-amber-500' : 'text-red-500'}
                  strokeDasharray={`${Math.max(0, Math.min(100, (complianceOverview as any)?.score ?? 0))}, 100`}
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="3"
                />
              </svg>
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <div className="text-2xl font-bold">{(complianceOverview as any)?.score ?? 0}%</div>
                <div className="text-[10px] uppercase tracking-widest text-black/35">Score</div>
              </div>
            </div>
          </div>
        </div>
        {[
          { label: language === 'zh' ? '设备总数' : 'Devices Audited', value: (complianceOverview as any)?.total_devices ?? 0, tone: 'text-slate-800' },
          { label: language === 'zh' ? '开放问题' : 'Open Findings', value: complianceOverview?.open_findings ?? 0, tone: 'text-red-600' },
          { label: language === 'zh' ? '高危与严重' : 'High + Critical', value: ((complianceOverview as any)?.severity_counts?.critical ?? 0) + ((complianceOverview as any)?.severity_counts?.high ?? 0), tone: 'text-orange-600' },
        ].map((item) => (
          <div key={item.label} className="bg-white p-6 rounded-2xl border border-black/5 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">{item.label}</p>
            <p className={`mt-4 text-3xl font-semibold ${item.tone}`}>{item.value}</p>
          </div>
        ))}
      </div>

      <div className={sectionToolbarClass}>
        <select value={complianceSeverityFilter} onChange={(e) => setComplianceSeverityFilter(e.target.value)} className="bg-white border border-black/10 rounded-lg px-3 py-2 text-xs outline-none">
          <option value="all">{language === 'zh' ? '全部级别' : 'All Severity'}</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select value={complianceStatusFilter} onChange={(e) => setComplianceStatusFilter(e.target.value)} className="bg-white border border-black/10 rounded-lg px-3 py-2 text-xs outline-none">
          <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
          <option value="open">Open</option>
          <option value="in_progress">In Progress</option>
          <option value="accepted_risk">Accepted Risk</option>
          <option value="resolved">Resolved</option>
        </select>
        <select value={complianceCategoryFilter} onChange={(e) => setComplianceCategoryFilter(e.target.value)} className="bg-white border border-black/10 rounded-lg px-3 py-2 text-xs outline-none">
          <option value="all">{language === 'zh' ? '全部分类' : 'All Categories'}</option>
          <option value="management-plane">Management Plane</option>
          <option value="aaa">AAA</option>
          <option value="logging">Logging</option>
          <option value="snmp">SNMP</option>
          <option value="switching">Switching</option>
          <option value="backup">Backup</option>
        </select>
      </div>

      <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 bg-black/[0.02] flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold">{language === 'zh' ? '审计发现' : 'Compliance Findings'}</h3>
            <p className="text-xs text-black/40 mt-1">{language === 'zh' ? '按规则和设备归档当前未关闭问题。' : 'Current findings grouped by rule and device.'}</p>
          </div>
          <div className="text-xs text-black/40">{complianceFindingTotal} {language === 'zh' ? '条记录' : 'records'}</div>
        </div>

        <div className="overflow-x-auto">
          <table className="nx-data-table text-left">
            <thead>
              <tr className="bg-black/[0.01] border-b border-black/5">
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '规则 / 设备' : 'Rule / Device'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '级别' : 'Severity'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '分类' : 'Category'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '状态' : 'Status'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '最近出现' : 'Last Seen'}</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{language === 'zh' ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody>
              {complianceFindings.map((finding) => (
                <tr key={finding.id} className="border-b border-black/5 hover:bg-black/[0.01] transition-colors">
                  <td className="px-6 py-4 align-top">
                    <div className="text-sm font-semibold text-[#0b2a3c]">{finding.title}</div>
                    <div className="mt-1 text-xs text-black/45">{finding.rule_id} · {finding.hostname || finding.device_id}</div>
                    <div className="mt-1 text-[11px] text-black/35">{finding.ip_address || 'N/A'} · {(finding as any).site || 'Unknown site'}</div>
                  </td>
                  <td className="px-6 py-4 align-top">
                    <span className={`inline-flex px-2.5 py-1 rounded-full text-[10px] font-bold uppercase ${severityBadgeClass(finding.severity)}`}>{finding.severity}</span>
                  </td>
                  <td className="px-6 py-4 align-top text-xs text-black/60">{finding.category}</td>
                  <td className="px-6 py-4 align-top">
                    <span className={`inline-flex px-2.5 py-1 rounded-full text-[10px] font-bold uppercase ${complianceStatusBadgeClass(finding.status)}`}>{finding.status.replace('_', ' ')}</span>
                  </td>
                  <td className="px-6 py-4 align-top text-xs font-mono text-black/50">{new Date((finding as any).last_seen_at).toLocaleString()}</td>
                  <td className="px-6 py-4 align-top">
                    <div className="flex items-center gap-3">
                      <button onClick={() => openComplianceFindingDetail(finding)} className="text-[10px] font-bold uppercase text-blue-600 hover:underline">
                        {language === 'zh' ? '详情' : 'Details'}
                      </button>
                      {finding.status !== 'resolved' && (
                        <button onClick={() => updateComplianceFinding(finding.id, { status: 'in_progress' })} className="text-[10px] font-bold uppercase text-amber-600 hover:underline">
                          {language === 'zh' ? '跟进' : 'Triage'}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!complianceLoading && complianceFindings.length === 0 && (
                <tr><td colSpan={6} className="px-6 py-10 text-center text-sm text-black/40">{language === 'zh' ? '当前筛选条件下没有审计问题。' : 'No findings match the current filters.'}</td></tr>
              )}
              {complianceLoading && complianceFindings.length === 0 && (
                <tr><td colSpan={6} className="px-6 py-10 text-center text-sm text-black/40">{language === 'zh' ? '正在加载审计结果...' : 'Loading compliance findings...'}</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <Pagination
          currentPage={compliancePage}
          totalItems={complianceFindingTotal}
          itemsPerPage={compliancePageSize}
          onItemsPerPageChange={setCompliancePageSize}
          onPageChange={setCompliancePage}
          language={language}
        />
      </div>
      </div>
    </div>
  );
};

export default ComplianceTab;
