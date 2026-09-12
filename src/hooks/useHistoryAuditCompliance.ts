import { useState, useEffect, useCallback } from 'react';

import { AuditEvent, ComplianceFinding } from '../types';

interface UseHistoryAuditComplianceProps {
  isAuthenticated: boolean;
  activeTab: string;
  language: string;
  currentUser: { id?: string; username?: string; role?: string };
  showToast: (msg: string, type: string) => void;
}

export const useHistoryAuditCompliance = ({
  isAuthenticated, activeTab, language, currentUser, showToast,
}: UseHistoryAuditComplianceProps) => {
  // History state
  const [historyRows, setHistoryRows] = useState<any[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyPageSize, setHistoryPageSize] = useState(10);
  const [historyStatusFilter, setHistoryStatusFilter] = useState('all');
  const [historyTimeFilter, setHistoryTimeFilter] = useState('all');
  const [historyLoading, setHistoryLoading] = useState(false);

  // Audit state
  const [auditRows, setAuditRows] = useState<any[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(10);
  const [auditCategoryFilter, setAuditCategoryFilter] = useState('all');
  const [auditSeverityFilter, setAuditSeverityFilter] = useState('all');
  const [auditStatusFilter, setAuditStatusFilter] = useState('all');
  const [auditTimeFilter, setAuditTimeFilter] = useState('all');
  const [auditLoading, setAuditLoading] = useState(false);
  const [selectedAuditEvent, setSelectedAuditEvent] = useState<AuditEvent | null>(null);

  // Compliance state
  const [complianceOverview, setComplianceOverview] = useState<any | null>(null);
  const [complianceFindings, setComplianceFindings] = useState<ComplianceFinding[]>([]);
  const [complianceFindingTotal, setComplianceFindingTotal] = useState(0);
  const [compliancePage, setCompliancePage] = useState(1);
  const [compliancePageSize, setCompliancePageSize] = useState(10);
  const [complianceSeverityFilter, setComplianceSeverityFilter] = useState('all');
  const [complianceStatusFilter, setComplianceStatusFilter] = useState('all');
  const [complianceCategoryFilter, setComplianceCategoryFilter] = useState('all');
  const [complianceLoading, setComplianceLoading] = useState(false);
  const [complianceRunLoading, setComplianceRunLoading] = useState(false);
  const [complianceRefreshTick, setComplianceRefreshTick] = useState(0);
  const [selectedFinding, setSelectedFinding] = useState<ComplianceFinding | null>(null);

  // History effects
  useEffect(() => { setHistoryPage(1); }, [historyStatusFilter, historyTimeFilter, historyPageSize]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(historyTotal / historyPageSize));
    if (historyPage > totalPages) setHistoryPage(totalPages);
  }, [historyTotal, historyPage, historyPageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'history') return;
    let cancelled = false;
    const fetchHistoryPage = async () => {
      setHistoryLoading(true);
      try {
        const params = new URLSearchParams({ status: historyStatusFilter, time_range: historyTimeFilter, page: String(historyPage), page_size: String(historyPageSize) });
        const resp = await fetch(`/api/jobs?${params.toString()}`);
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json();
        if (cancelled) return;
        if (Array.isArray(data)) { setHistoryRows(data); setHistoryTotal(data.length); }
        else { setHistoryRows(Array.isArray(data.items) ? data.items : []); setHistoryTotal(typeof data.total === 'number' ? data.total : 0); }
      } catch { if (cancelled) return; setHistoryRows([]); setHistoryTotal(0); }
      finally { if (!cancelled) setHistoryLoading(false); }
    };
    fetchHistoryPage();
    return () => { cancelled = true; };
  }, [isAuthenticated, activeTab, historyStatusFilter, historyTimeFilter, historyPage, historyPageSize]);

  // Audit effects
  useEffect(() => { setAuditPage(1); }, [auditCategoryFilter, auditSeverityFilter, auditStatusFilter, auditTimeFilter, auditPageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'audit') return;
    let cancelled = false;
    const loadAuditEvents = async () => {
      setAuditLoading(true);
      try {
        const params = new URLSearchParams({ category: auditCategoryFilter, severity: auditSeverityFilter, status: auditStatusFilter, time_range: auditTimeFilter, page: String(auditPage), page_size: String(auditPageSize) });
        const resp = await fetch(`/api/audit/events?${params.toString()}`);
        if (!resp.ok) throw new Error('Failed');
        const data = await resp.json();
        if (cancelled) return;
        setAuditRows(Array.isArray(data.items) ? data.items : []);
        setAuditTotal(typeof data.total === 'number' ? data.total : 0);
      } catch { if (cancelled) return; setAuditRows([]); setAuditTotal(0); }
      finally { if (!cancelled) setAuditLoading(false); }
    };
    loadAuditEvents();
    return () => { cancelled = true; };
  }, [isAuthenticated, activeTab, auditCategoryFilter, auditSeverityFilter, auditStatusFilter, auditTimeFilter, auditPage, auditPageSize]);

  // Compliance effects
  useEffect(() => { setCompliancePage(1); }, [complianceSeverityFilter, complianceStatusFilter, complianceCategoryFilter, compliancePageSize]);

  useEffect(() => {
    if (!isAuthenticated || activeTab !== 'compliance') return;
    let cancelled = false;
    const loadCompliance = async () => {
      setComplianceLoading(true);
      try {
        const params = new URLSearchParams({ severity: complianceSeverityFilter, status: complianceStatusFilter, category: complianceCategoryFilter, page: String(compliancePage), page_size: String(compliancePageSize) });
        const [overviewResp, findingsResp] = await Promise.all([fetch('/api/compliance/overview'), fetch(`/api/compliance/findings?${params.toString()}`)]);
        if (!overviewResp.ok || !findingsResp.ok) throw new Error('Failed');
        const overviewData = await overviewResp.json();
        const findingsData = await findingsResp.json();
        if (cancelled) return;
        setComplianceOverview(overviewData);
        setComplianceFindings(Array.isArray(findingsData.items) ? findingsData.items : []);
        setComplianceFindingTotal(typeof findingsData.total === 'number' ? findingsData.total : 0);
      } catch { if (cancelled) return; setComplianceOverview(null); setComplianceFindings([]); setComplianceFindingTotal(0); }
      finally { if (!cancelled) setComplianceLoading(false); }
    };
    loadCompliance();
    return () => { cancelled = true; };
  }, [isAuthenticated, activeTab, complianceSeverityFilter, complianceStatusFilter, complianceCategoryFilter, compliancePage, compliancePageSize, complianceRefreshTick]);

  // Compliance actions
  const runComplianceAudit = useCallback(async () => {
    setComplianceRunLoading(true);
    try {
      const resp = await fetch('/api/compliance/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ author: currentUser.username || 'admin', actor_id: currentUser.id, actor_role: currentUser.role || 'Administrator' }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) { showToast(`Compliance audit failed: ${data.detail || resp.statusText}`, 'error'); return; }
      showToast(language === 'zh' ? `审计完成，合规得分 ${data.score}%` : `Audit completed. Score ${data.score}%`, 'success');
      setComplianceRefreshTick((v) => v + 1);
    } catch { showToast(language === 'zh' ? '审计执行失败' : 'Compliance audit request failed', 'error'); }
    finally { setComplianceRunLoading(false); }
  }, [currentUser, language, showToast]);

  const updateComplianceFinding = useCallback(async (findingId: string, patch: { status?: string; owner?: string; note?: string }) => {
    try {
      const resp = await fetch(`/api/compliance/findings/${findingId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) { showToast(`Update failed: ${data.detail || resp.statusText}`, 'error'); return; }
      setSelectedFinding(data);
      setComplianceRefreshTick((v) => v + 1);
      showToast(language === 'zh' ? '审计问题已更新' : 'Finding updated', 'success');
    } catch { showToast(language === 'zh' ? '更新失败' : 'Update failed', 'error'); }
  }, [language, showToast]);

  const openAuditEventDetail = useCallback(async (event: AuditEvent) => {
    try {
      const resp = await fetch(`/api/audit/events/${event.id}`);
      const data = await resp.json().catch(() => event);
      if (!resp.ok) throw new Error('Failed');
      setSelectedAuditEvent(data);
    } catch {
      setSelectedAuditEvent(event);
      showToast(language === 'zh' ? '无法加载完整审计详情，已显示当前记录。' : 'Unable to load full audit details, showing current row.', 'info');
    }
  }, [language, showToast]);

  const openComplianceFindingDetail = useCallback(async (finding: ComplianceFinding) => {
    try {
      const resp = await fetch(`/api/compliance/findings/${finding.id}`);
      const data = await resp.json().catch(() => finding);
      if (!resp.ok) throw new Error('Failed');
      setSelectedFinding(data);
    } catch {
      setSelectedFinding(finding);
      showToast(language === 'zh' ? '无法加载完整问题详情，已显示当前记录。' : 'Unable to load full finding details, showing current row.', 'info');
    }
  }, [language, showToast]);

  return {
    // History
    historyRows, historyTotal, historyPage, setHistoryPage, historyPageSize, setHistoryPageSize,
    historyStatusFilter, setHistoryStatusFilter, historyTimeFilter, setHistoryTimeFilter, historyLoading,
    // Audit
    auditRows, auditTotal, auditPage, setAuditPage, auditPageSize, setAuditPageSize,
    auditCategoryFilter, setAuditCategoryFilter, auditSeverityFilter, setAuditSeverityFilter,
    auditStatusFilter, setAuditStatusFilter, auditTimeFilter, setAuditTimeFilter, auditLoading,
    selectedAuditEvent, setSelectedAuditEvent,
    // Compliance
    complianceOverview, complianceFindings, complianceFindingTotal,
    compliancePage, setCompliancePage, compliancePageSize, setCompliancePageSize,
    complianceSeverityFilter, setComplianceSeverityFilter, complianceStatusFilter, setComplianceStatusFilter,
    complianceCategoryFilter, setComplianceCategoryFilter, complianceLoading, complianceRunLoading,
    selectedFinding, setSelectedFinding,
    // Actions
    runComplianceAudit, updateComplianceFinding, openAuditEventDetail, openComplianceFindingDetail,
  };
};
