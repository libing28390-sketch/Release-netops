import React, { useEffect, useState, useCallback, useMemo } from 'react';
import { CalendarClock, Plus, X, RotateCcw } from 'lucide-react';
import PageHero from '../../components/PageHero';
import { useSystem } from '../../hooks/useSystem';
import type { ExecutionScheduleTabProps, ScheduledJob, FormState, ValidatedDevice, EligibleApprover, UnifiedExecutionLog, InspSubTab, InspDetailTab, PlaybookExecutionApproval } from './types';
import { INITIAL_FORM } from './constants';
import { serializeTagFilter, EMPTY_TAG_FILTER } from '../../components/TagConditionPicker';
import { fmtDateTime } from './helpers';

// Components
import ScheduleEditor from './components/ScheduleEditor';
import ScheduleList from './components/ScheduleList';
import ScheduleDetail from './components/ScheduleDetail';
import HistoryList from './components/HistoryList';
import ExecutionDetail from './components/ExecutionDetail';
import CandidateModal from './components/CandidateModal';

const ExecutionScheduleCoordinator: React.FC<ExecutionScheduleTabProps> = ({
  language,
  showToast,
  initialTab,
  devices,
  onRerun,
}) => {
  const { systemInfo } = useSystem();
  const zh = language === 'zh';

  /* ═══ STATE ═══ */
  const [inspSchedules, setInspSchedules] = useState<ScheduledJob[]>([]);
  const [inspSchedulesLoading, setInspSchedulesLoading] = useState(false);
  const [inspSchedulePage, setInspSchedulePage] = useState(1);
  const [inspSchedulePageSize, setInspSchedulePageSize] = useState(20);
  const [inspScheduleTotal, setInspScheduleTotal] = useState(0);
  const [showAddInspSchedule, setShowAddInspSchedule] = useState(false);
  const [form, setForm] = useState<FormState>({ ...INITIAL_FORM });

  // IP validation state
  const [ipDevices, setIpDevices] = useState<ValidatedDevice[]>([]);
  const [ipInput, setIpInput] = useState('');
  const [ipValidating, setIpValidating] = useState(false);
  const [ipError, setIpError] = useState('');
  const [tagFilter, setTagFilter] = useState<any>({ ...EMPTY_TAG_FILTER });

  // Candidate IP / Device Selection modal
  const [candidateModalOpen, setCandidateModalOpen] = useState(false);
  const [candidateList, setCandidateList] = useState<Array<{ ip: string; hostname: string; tags: any[]; selected: boolean }>>([]);
  const [candidateSearching, setCandidateSearching] = useState(false);

  // Script selection
  const [availableScripts, setAvailableScripts] = useState<{ id: string; name: string; status: string; category: string }[]>([]);
  const [scriptSearch, setScriptSearch] = useState('');
  const [showScriptDropdown, setShowScriptDropdown] = useState(false);

  const [inspectionItems, setInspectionItems] = useState<any[]>([]);
  const [inspectionItemsLoading, setInspectionItemsLoading] = useState(false);

  const [selectedSchedule, setSelectedSchedule] = useState<ScheduledJob | null>(null);
  const [showScheduleDetail, setShowScheduleDetail] = useState(false);

  const [inspRuns, setInspRuns] = useState<any[]>([]);
  const [inspRunsLoading, setInspRunsLoading] = useState(false);
  const [inspRunPage, setInspRunPage] = useState(1);
  const [inspRunPageSize, setInspRunPageSize] = useState(20);
  const [inspRunTotal, setInspRunTotal] = useState(0);
  const [inspSubTab, setInspSubTab] = useState<InspSubTab>(initialTab || 'schedules');

  // Future projections filter states
  const [timeRange, setTimeRange] = useState<'1h' | '4h' | '12h' | '1d' | '3d' | 'custom'>('1d');
  const [nameFilterInput, setNameFilterInput] = useState('');
  const [searchName, setSearchName] = useState('');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [allFutureSchedules, setAllFutureSchedules] = useState<ScheduledJob[]>([]);

  const paginatedSchedules = useMemo(() => {
    const start = (inspSchedulePage - 1) * inspSchedulePageSize;
    return allFutureSchedules.slice(start, start + inspSchedulePageSize);
  }, [allFutureSchedules, inspSchedulePage, inspSchedulePageSize]);

  // Unified execution history states
  const [unifiedLogs, setUnifiedLogs] = useState<UnifiedExecutionLog[]>([]);
  const [executionTypeFilter, setExecutionTypeFilter] = useState<'all' | 'manual' | 'plan' | 'job'>('all');

  const [selectedLog, setSelectedLog] = useState<UnifiedExecutionLog | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [logDetailLoading, setLogDetailLoading] = useState(false);
  const [selectedInspDeviceId, setSelectedInspDeviceId] = useState<string | null>(null);
  const [collapsedCmds, setCollapsedCmds] = useState<Record<string, boolean>>({});
  
  // TextFSM parse state for inspection command blocks
  const [inspParseResults, setInspParseResults] = useState<Record<string, { loading: boolean; data: any; error: string }>>({});
  const [inspCopiedKey, setInspCopiedKey] = useState<string | null>(null);
  const [inspDetailTab, setInspDetailTab] = useState<InspDetailTab>('analysis');
  const [inspParseViewMode, setInspParseViewMode] = useState<Record<string, 'raw' | 'parsed'>>({});
  
  // Trend chart state for analysis tab
  const [trendData, setTrendData] = useState<{ deviceId: string; metric: string; series: any[]; firstInspection?: boolean } | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  
  const [inspectionDetail, setInspectionDetail] = useState<any>(null);
  const [pbDetail, setPbDetail] = useState<any>(null);
  const [pbDevices, setPbDevices] = useState<any[]>([]);
  const [selectedPbDevice, setSelectedPbDevice] = useState<any>(null);
  const [pbDeviceDetail, setPbDeviceDetail] = useState<any>(null);
  const [pbApprovals, setPbApprovals] = useState<PlaybookExecutionApproval[]>([]);
  const [pbApprovalsLoading, setPbApprovalsLoading] = useState(false);
  const [pbApprovalActionId, setPbApprovalActionId] = useState('');
  const [pbApprovalError, setPbApprovalError] = useState('');

  // Approval states
  const [approvers, setApprovers] = useState<EligibleApprover[]>([]);
  const [approverUsername, setApproverUsername] = useState('');
  const [approvalToken, setApprovalToken] = useState('');
  const [approvalCode, setApprovalCode] = useState('');
  const [approvalStatus, setApprovalStatus] = useState<'idle' | 'sending' | 'sent' | 'verified'>('idle');
  const [approvalError, setApprovalError] = useState('');

  const authHeaders = useMemo(() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
  }, []);

  /* ═══ FETCHERS ═══ */
  const fetchInspectionItems = useCallback(async () => {
    setInspectionItemsLoading(true);
    try {
      const r = await fetch('/api/inspections/items/all', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        setInspectionItems(j.items || []);
        if (form.check_items.length === 0 && j.items?.length > 0) {
          setForm(f => ({ ...f, check_items: j.items.map((i: any) => i.name) }));
        }
      }
    } catch { /* ignore */ }
    finally { setInspectionItemsLoading(false); }
  }, [authHeaders, form.check_items.length]);

  const fetchInspSchedules = useCallback(async () => {
    setInspSchedulesLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('time_range', timeRange);
      if (searchName.trim()) {
        params.append('query', searchName.trim());
      }
      if (timeRange === 'custom') {
        if (customStart) {
          params.append('start_time', new Date(customStart).toISOString());
        }
        if (customEnd) {
          params.append('end_time', new Date(customEnd).toISOString());
        }
      }
      const r = await fetch(`/api/scheduled-jobs/future?${params.toString()}`, { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const items = j.data || [];
        setAllFutureSchedules(items);
        setInspScheduleTotal(items.length);
      }
    } catch { /* ignore */ }
    finally { setInspSchedulesLoading(false); }
  }, [authHeaders, timeRange, searchName, customStart, customEnd]);

  const fetchScripts = useCallback(async () => {
    if (!authHeaders) return;
    try {
      const r = await fetch('/api/scripts', { headers: authHeaders });
      if (r.ok) {
        const data = await r.json();
        const arr = Array.isArray(data) ? data : (data.items || data.data || []);
        setAvailableScripts(arr.map((s: any) => ({
          id: s.id, name: s.name, status: s.status, category: s.category || 'automation'
        })));
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  const validateAndAddIps = async (raw: string) => {
    const queries = raw.split(/[,;\s]+/).map(s => s.trim()).filter(Boolean);
    if (queries.length === 0) return;
    setIpError('');
    setIpValidating(true);
    setCandidateSearching(true);

    const candidatesMap: Record<string, { ip: string; hostname: string; tags: any[]; selected: boolean }> = {};

    try {
      for (const query of queries) {
        let found = false;
        // 1) Search devices table
        const r = await fetch(`/api/devices?search=${encodeURIComponent(query)}&mode=light&page_size=50`, { headers: authHeaders });
        if (r.ok) {
          const j = await r.json();
          const items = Array.isArray(j) ? j : (j.items || j.data?.items || j.data || []);
          if (items.length > 0) {
            found = true;
            for (const dev of items) {
              const ip = dev.ip_address;
              if (ip && !ipDevices.some(existing => existing.ip === ip)) {
                candidatesMap[ip] = {
                  ip,
                  hostname: dev.hostname || '',
                  tags: (dev.tags || []).map((t: any) => ({
                    id: t.id, label: t.label, label_zh: t.label_zh, color: t.color || '#94a3b8',
                  })),
                  selected: true,
                };
              }
            }
          }
        }

        // 2) Fallback: search physical_assets table
        if (!found) {
          try {
            const ar = await fetch(`/api/assets?q=${encodeURIComponent(query)}&page_size=50`, { headers: authHeaders });
            if (ar.ok) {
              const aj = await ar.json();
              const assets = Array.isArray(aj) ? aj : (aj.items || aj.data?.items || aj.data || []);
              if (assets.length > 0) {
                found = true;
                for (const a of assets) {
                  const ip = a.management_ip || a.business_ip || query;
                  if (ip && !ipDevices.some(existing => existing.ip === ip)) {
                    candidatesMap[ip] = candidatesMap[ip] || { ip, hostname: a.hostname || '', tags: [], selected: true };
                  }
                }
              }
            }
          } catch { /* ignore */ }
        }

        // 3) If neither found
        if (!found && !ipDevices.some(existing => existing.ip === query)) {
          candidatesMap[query] = candidatesMap[query] || { ip: query, hostname: '', tags: [], selected: true };
        }
      }

      const candidateArray = Object.values(candidatesMap);
      if (candidateArray.length > 0) {
        setCandidateList(candidateArray);
        setCandidateModalOpen(true);
      } else {
        setIpError(zh ? '输入的 IP 或查询目标已全部添加或无匹配结果' : 'All queried IPs are already added or no results');
      }
    } catch {
      setIpError(zh ? '查询设备失败' : 'Device lookup failed');
    } finally {
      setIpValidating(false);
      setCandidateSearching(false);
    }
  };

  const confirmAddCandidates = () => {
    const selectedCandidates = candidateList.filter(c => c.selected);
    if (selectedCandidates.length === 0) return;
    setIpDevices(prev => {
      const next = [...prev];
      for (const c of selectedCandidates) {
        if (!next.some(existing => existing.ip === c.ip)) {
          next.push({ ip: c.ip, hostname: c.hostname, tags: c.tags });
        }
      }
      return next;
    });
    setIpInput('');
    setCandidateModalOpen(false);
    setCandidateList([]);
  };

  const toggleCandidateSelected = (idx: number) => {
    setCandidateList(prev => prev.map((c, i) => i === idx ? { ...c, selected: !c.selected } : c));
  };

  const toggleAllCandidates = () => {
    const allSel = candidateList.length > 0 && candidateList.every(c => c.selected);
    setCandidateList(prev => prev.map(c => ({ ...c, selected: !allSel })));
  };

  const removeIpDevice = (ip: string) => {
    setIpDevices(prev => prev.filter(d => d.ip !== ip));
  };

  const resolveFilter = (): string => {
    if (form.device_scope === 'tag') return serializeTagFilter(tagFilter);
    if (form.device_scope === 'ip') return ipDevices.map(d => d.ip).join(',');
    return form.device_filter;
  };

  const fetchInspRuns = useCallback(async () => {
    setInspRunsLoading(true);
    try {
      const inspResp = await fetch(`/api/inspections?limit=500`, { headers: authHeaders });
      let inspections: any[] = [];
      if (inspResp.ok) {
        const j = await inspResp.json();
        const d = j.data;
        inspections = Array.isArray(d) ? d : (d?.items || []);
      }

      const pbResp = await fetch(`/api/playbooks?page=1&page_size=500`, { headers: authHeaders });
      let playbooks: any[] = [];
      if (pbResp.ok) {
        const j = await pbResp.json();
        playbooks = Array.isArray(j) ? j : (j?.items || []);
      } else {
        if (pbResp.status === 403) {
          showToast(zh ? '获取执行历史被拒绝 (403)' : 'Access denied to execution history (403)', 'error');
        }
      }

      const normalizedInsp: UnifiedExecutionLog[] = inspections.map(run => ({
        id: run.id,
        source: 'inspection',
        started_at: run.started_at,
        trigger_type: run.trigger_type === 'manual' ? 'manual' : 'plan',
        status: run.status,
        total_devices: run.total_devices || 0,
        success_count: run.success_count || 0,
        failed_count: run.failed_count || 0,
        avg_health_score: run.avg_health_score,
        created_by: run.created_by || 'system',
        name: run.schedule_name || run.name || (zh ? '网络巡检' : 'Network Inspection')
      }));

      const normalizedPlaybooks: UnifiedExecutionLog[] = playbooks.map(pb => {
        const isScheduled = pb.author === 'scheduler' || pb.author === 'system'
                            || (pb.scenario_id && String(pb.scenario_id).startsWith('scheduled:'));
        return {
          id: pb.id,
          source: 'playbook',
          started_at: pb.created_at,
          trigger_type: isScheduled ? 'job' : 'manual',
          status: pb.status,
          total_devices: pb.total_devices || 0,
          success_count: pb.success_count || 0,
          failed_count: pb.failed_count || 0,
          partial_count: pb.partial_count || 0,
          created_by: pb.author || 'admin',
          name: pb.scenario_name || pb.task_name || (zh ? '快捷命令执行' : 'Quick Playbook')
        };
      });

      const combined = [...normalizedInsp, ...normalizedPlaybooks].sort((a, b) => {
        const timeA = a.started_at ? new Date(a.started_at).getTime() : 0;
        const timeB = b.started_at ? new Date(b.started_at).getTime() : 0;
        return (isNaN(timeB) ? 0 : timeB) - (isNaN(timeA) ? 0 : timeA);
      });

      setUnifiedLogs(combined);
    } catch (e) {
      console.error(e);
    } finally {
      setInspRunsLoading(false);
    }
  }, [authHeaders, zh, showToast]);

  const filteredLogs = useMemo(() => {
    return unifiedLogs.filter(log => {
      if (executionTypeFilter === 'all') return true;
      return log.trigger_type === executionTypeFilter;
    });
  }, [unifiedLogs, executionTypeFilter]);

  // Reset log page when filter changes
  useEffect(() => {
    setInspRunPage(1);
  }, [executionTypeFilter, unifiedLogs.length]);

  // ESC to close the execution detail modal and the schedule detail modal
  useEffect(() => {
    if (!isDetailModalOpen && !showScheduleDetail) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (isDetailModalOpen) setIsDetailModalOpen(false);
        if (showScheduleDetail) setShowScheduleDetail(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isDetailModalOpen, showScheduleDetail]);

  const paginatedLogs = useMemo(() => {
    const start = (inspRunPage - 1) * inspRunPageSize;
    return filteredLogs.slice(start, start + inspRunPageSize);
  }, [filteredLogs, inspRunPage, inspRunPageSize]);

  const handleSelectLog = async (log: UnifiedExecutionLog) => {
    setSelectedLog(log);
    setIsDetailModalOpen(true);
    setLogDetailLoading(true);
    setInspectionDetail(null);
    setPbDetail(null);
    setPbDevices([]);
    setSelectedPbDevice(null);
    setPbDeviceDetail(null);
    setPbApprovals([]);
    setPbApprovalError('');

    try {
      if (log.source === 'inspection') {
        const resp = await fetch(`/api/inspections/${log.id}`, { headers: authHeaders });
        if (resp.ok) {
          const j = await resp.json();
          setInspectionDetail(j.data);
          if (j.data?.results?.length > 0) {
            setSelectedInspDeviceId(j.data.results[0].device_id);
          }
        }
      } else {
        const pbResp = await fetch(`/api/playbooks/${log.id}`, { headers: authHeaders });
        if (pbResp.ok) {
          const j = await pbResp.json();
          setPbDetail(j);
        }
        if (log.status === 'awaiting_approval') {
          setPbApprovalsLoading(true);
          try {
            const approvalResp = await fetch(`/api/playbooks/${log.id}/approvals`, { headers: authHeaders });
            if (approvalResp.ok) {
              const approvalPayload = await approvalResp.json();
              setPbApprovals(approvalPayload.data || []);
            } else {
              setPbApprovalError(zh ? '审批记录加载失败' : 'Failed to load approval gates');
            }
          } catch {
            setPbApprovalError(zh ? '审批记录加载失败' : 'Failed to load approval gates');
          } finally {
            setPbApprovalsLoading(false);
          }
        }
        const devResp = await fetch(`/api/playbooks/${log.id}/devices?page=1&page_size=100`, { headers: authHeaders });
        if (devResp.ok) {
          const j = await devResp.json();
          const devs = Array.isArray(j) ? j : (j.items || []);
          setPbDevices(devs);
          if (devs.length > 0) {
            setSelectedPbDevice(devs[0].device_id);
            const detailResp = await fetch(`/api/playbooks/${log.id}/devices/${devs[0].device_id}`, { headers: authHeaders });
            if (detailResp.ok) {
              const dj = await detailResp.json();
              setPbDeviceDetail(dj);
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLogDetailLoading(false);
    }
  };

  const handlePlaybookApproval = async (approval: PlaybookExecutionApproval, decision: 'approve' | 'reject') => {
    if (!selectedLog || selectedLog.source !== 'playbook' || approval.status !== 'PENDING') return;
    const reason = decision === 'reject' ? window.prompt(zh ? '请输入拒绝原因' : 'Reason for rejection') : '';
    if (decision === 'reject' && reason === null) return;
    setPbApprovalActionId(approval.id);
    setPbApprovalError('');
    try {
      const response = await fetch(`/api/playbooks/${encodeURIComponent(selectedLog.id)}/approvals/${encodeURIComponent(approval.id)}/${decision}`, {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ reason: reason || '' }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || (zh ? '审批操作失败' : 'Approval decision failed'));
      setPbApprovals((current) => current.map((item) => item.id === approval.id ? (payload.data?.approval || { ...item, status: decision === 'approve' ? 'APPROVED' : 'REJECTED' }) : item));
      const nextStatus = payload.data?.execution_status;
      if (nextStatus) setSelectedLog((current) => current ? { ...current, status: nextStatus } : current);
      await fetchInspRuns();
      showToast(zh ? (decision === 'approve' ? '审批已通过，执行已恢复' : '审批已拒绝') : (decision === 'approve' ? 'Approval granted; execution resumed' : 'Approval rejected'), decision === 'approve' ? 'success' : 'info');
    } catch (cause) {
      setPbApprovalError(cause instanceof Error ? cause.message : (zh ? '审批操作失败' : 'Approval decision failed'));
    } finally {
      setPbApprovalActionId('');
      setPbApprovalsLoading(false);
    }
  };

  const toggleCmdCollapse = (cmd: string) => {
    setCollapsedCmds(prev => ({ ...prev, [cmd]: !prev[cmd] }));
  };

  const expandAllCmds = (cmds: string[]) => {
    const next: Record<string, boolean> = {};
    cmds.forEach(c => next[c] = false);
    setCollapsedCmds(next);
  };

  const collapseAllCmds = (cmds: string[]) => {
    const next: Record<string, boolean> = {};
    cmds.forEach(c => next[c] = true);
    setCollapsedCmds(next);
  };

  /** Parse a single inspection command output via TextFSM */
  const handleParseInspCmd = useCallback(async (
    blockKey: string,
    platform: string,
    command: string,
    rawOutput: string,
  ) => {
    setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: true, data: null, error: '' } }));
    setInspParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' }));
    try {
      const res = await fetch('/api/inspections/parse-output', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, command, output: rawOutput }),
      });
      const json = await res.json();
      if (json.success && json.data?.count > 0) {
        setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: json.data, error: '' } }));
      } else if (json.has_template === false) {
        setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: zh ? `未找到 ${platform} / ${command} 的解析模板` : `No template for ${platform} / ${command}` } }));
      } else {
        setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: json.message || (zh ? '解析无结果' : 'No parse results') } }));
      }
    } catch {
      setInspParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: zh ? '解析请求失败' : 'Parse request failed' } }));
    }
  }, [authHeaders, zh]);

  /** R5.6: Fetch metric trend for a device */
  const fetchTrend = useCallback(async (deviceId: string, metric: string) => {
    setTrendLoading(true);
    try {
      const resp = await fetch(`/api/inspections/device/${deviceId}/trend?metric=${encodeURIComponent(metric)}&days=30`, { headers: authHeaders });
      if (resp.ok) {
        const j = await resp.json();
        setTrendData({
          deviceId,
          metric,
          series: j.series || [],
          firstInspection: j.first_inspection,
        });
      } else {
        setTrendData({ deviceId, metric, series: [] });
      }
    } catch {
      setTrendData({ deviceId, metric, series: [] });
    } finally {
      setTrendLoading(false);
    }
  }, [authHeaders]);

  const handleSelectPbDevice = async (device_id: string) => {
    setSelectedPbDevice(device_id);
    setPbDeviceDetail(null);
    try {
      const resp = await fetch(`/api/playbooks/${selectedLog?.id}/devices/${device_id}`, { headers: authHeaders });
      if (resp.ok) {
        const j = await resp.json();
        setPbDeviceDetail(j);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (initialTab) setInspSubTab(initialTab);
    setInspRunPage(1);
    setInspSchedulePage(1);
  }, [initialTab]);

  useEffect(() => {
    if (inspSubTab === 'schedules') {
      fetchInspSchedules();
    } else if (inspSubTab === 'history') {
      fetchInspRuns();
    }
  }, [inspSubTab, fetchInspSchedules, fetchInspRuns]);

  useEffect(() => {
    fetchInspectionItems();
  }, [fetchInspectionItems]);

  useEffect(() => {
    setInspSchedulePage(1);
  }, [timeRange, searchName, customStart, customEnd]);

  useEffect(() => {
    const totalPages = Math.ceil(allFutureSchedules.length / inspSchedulePageSize);
    if (inspSchedulePage > totalPages && totalPages > 0) {
      setInspSchedulePage(1);
    }
  }, [allFutureSchedules.length, inspSchedulePageSize, inspSchedulePage]);

  const fetchApprovers = useCallback(async () => {
    try {
      const r = await fetch('/api/users', { headers: authHeaders });
      if (r.ok) {
        const j = await r.json();
        const users = Array.isArray(j) ? j : (j.data || []);
        setApprovers(users.filter((u: EligibleApprover) => u.role === 'Administrator' || u.role === 'Operator'));
      }
    } catch { /* ignore */ }
  }, [authHeaders]);

  useEffect(() => {
    if (showAddInspSchedule) fetchApprovers();
  }, [showAddInspSchedule, fetchApprovers]);

  /* ═══ APPROVAL ═══ */
  const resetApproval = () => {
    setApprovalStatus('idle');
    setApproverUsername('');
    setApprovalToken('');
    setApprovalCode('');
    setApprovalError('');
  };

  const requestApproval = async () => {
    if (!approverUsername) return;
    setApprovalStatus('sending');
    setApprovalError('');
    try {
      const r = await fetch('/api/config-approval/request', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({
          approver_username: approverUsername,
          config_reason: form.config_reason || `${zh ? '创建执行计划' : 'Create execution schedule'}: ${form.name}`,
          device_hostname: resolveFilter() || (zh ? '全部设备' : 'All devices'),
          command_preview: form.commands || '',
          approval_type: 'execution_plan',
          extra_fields: {
            action_type: form.action_type,
            schedule_desc: form.scheduled_at ? fmtDateTime(form.scheduled_at, zh) : (zh ? '未设定' : 'Not set'),
          },
        }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalToken(j.approval_token);
        setApprovalStatus('sent');
        showToast(zh ? '验证码已发送至审批人' : 'Code sent to approver', 'success');
      } else {
        setApprovalStatus('idle');
        setApprovalError(j.detail || j.message || 'Failed');
      }
    } catch {
      setApprovalStatus('idle');
      setApprovalError(zh ? '发送验证码失败' : 'Failed to send code');
    }
  };

  const verifyApproval = async () => {
    if (!approvalToken || !approvalCode) return;
    try {
      const r = await fetch('/api/config-approval/verify', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ approval_token: approvalToken, code: approvalCode }),
      });
      const j = await r.json();
      if (r.ok && j.success) {
        setApprovalStatus('verified');
        showToast(zh ? '审批验证通过' : 'Approval verified', 'success');
      } else {
        setApprovalError(j.detail || j.message || 'Invalid code');
      }
    } catch {
      setApprovalError(zh ? '验证失败' : 'Verification failed');
    }
  };

  /* ═══ ACTIONS ═══ */
  const addInspSchedule = async () => {
    if (!form.name.trim() || !form.scheduled_at) {
      showToast(zh ? '请填写计划名称和执行时间' : 'Name and execution time are required', 'error');
      return;
    }
    if (form.action_type === 'script_run' && !form.script_id) {
      showToast(zh ? '请选择一个要执行的脚本' : 'Please select a script to execute', 'error');
      return;
    }
    if (approvalStatus !== 'verified') {
      showToast(zh ? '请先发送验证码并完成审批验证' : 'Please complete approval verification first', 'error');
      return;
    }
    try {
      const payload = {
        name: form.name,
        action_type: form.action_type,
        job_type: 'once',
        scheduled_at: form.scheduled_at,
        cron_expr: '',
        device_scope: form.device_scope,
        device_filter: resolveFilter(),
        script_id: form.script_id,
        commands: form.commands,
        config_reason: form.config_reason,
        use_admin_creds: form.use_admin_creds ? 1 : 0,
        approval_token: approvalToken,
        approval_code: approvalCode,
        description: form.description,
        check_items: form.check_items,
      };

      const r = await fetch('/api/scheduled-jobs', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify(payload),
      });
      if (r.ok) {
        setShowAddInspSchedule(false);
        setForm({ ...INITIAL_FORM });
        setIpDevices([]);
        setTagFilter({ ...EMPTY_TAG_FILTER });
        resetApproval();
        setInspSchedulePage(1);
        fetchInspSchedules();
        showToast(zh ? '执行计划已创建' : 'Execution schedule created', 'success');
      } else {
        const j = await r.json();
        showToast(j.detail || j.message || 'Failed', 'error');
      }
    } catch {
      showToast(zh ? '创建失败' : 'Create failed', 'error');
    }
  };

  const deleteInspSchedule = async (id: string) => {
    try {
      await fetch(`/api/scheduled-jobs/${id}`, { method: 'DELETE', headers: authHeaders });
      fetchInspSchedules();
      showToast(zh ? '计划已删除' : 'Schedule deleted', 'success');
    } catch { /* ignore */ }
  };

  const toggleInspScheduleEnabled = async (sch: ScheduledJob) => {
    try {
      await fetch(`/api/scheduled-jobs/${sch.id}/toggle`, {
        method: 'PUT', headers: authHeaders,
        body: JSON.stringify({ enabled: !sch.enabled }),
      });
      fetchInspSchedules();
    } catch { /* ignore */ }
  };

  const handleExportReport = async (logId: string, format: string, source: string = 'inspection') => {
    try {
      const sourceParam = source === 'playbook' ? '&source=playbook' : '';
      const resp = await fetch(`/api/inspections/${logId}/export?format=${format}${sourceParam}`, { headers: authHeaders });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
        const prefix = source === 'playbook' ? 'Playbook' : 'Inspection';
        const ext = format === 'xlsx' ? 'xlsx' : format === 'html' ? 'html' : format === 'pdf' ? 'pdf' : 'json';
        a.download = `${systemInfo?.system_name || 'Nexora'}_${prefix}_Report_${logId}_${today}.${ext}`;
        a.click();
        URL.revokeObjectURL(url);
      } else {
        showToast(zh ? `${format.toUpperCase()} 导出失败 (${resp.status})` : `${format.toUpperCase()} export failed (${resp.status})`, 'error');
      }
    } catch (err) {
      console.error(`Export ${format} failed:`, err);
      showToast(zh ? `${format.toUpperCase()} 导出异常` : `${format.toUpperCase()} export error`, 'error');
    }
  };

  const copyInspText = (text: string, key: string) => {
    navigator.clipboard.writeText(text).catch(() => {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    });
    setInspCopiedKey(key);
    setTimeout(() => setInspCopiedKey(null), 2000);
  };

  /* ═══ RENDER ═══ */
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={CalendarClock}
        title={inspSubTab === 'history'
          ? (zh ? '执行历史' : 'Execution History')
          : (zh ? '执行计划' : 'Execution Schedules')}
        subtitle={inspSubTab === 'history'
          ? (zh ? '查看和追溯自动化执行历史' : 'View and trace automation execution history')
          : (zh ? '创建指定时间范围内执行的一次性巡检计划' : 'Create one-time inspection plans within a specified time window')}
        actions={
          <>
            {inspSubTab === 'schedules' && (
              <button
                onClick={() => setShowAddInspSchedule(!showAddInspSchedule)}
                className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-bold shadow-sm transition-all active:scale-[0.97] ${
                  showAddInspSchedule
                    ? 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    : 'bg-gradient-to-r from-cyan-500 to-cyan-600 text-white hover:from-cyan-400 hover:to-cyan-500'
                }`}
              >
                {showAddInspSchedule ? <X size={16} /> : <Plus size={16} />}
                {showAddInspSchedule ? (zh ? '取消新建' : 'Cancel') : (zh ? '新建计划' : 'Add Schedule')}
              </button>
            )}
            {inspSubTab === 'history' && (
              <button
                onClick={fetchInspRuns}
                disabled={inspRunsLoading}
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl border border-cyan-100 bg-cyan-50/50 text-[#0e7490] text-sm font-bold shadow-sm hover:bg-cyan-50 transition-all active:scale-[0.97]"
              >
                <RotateCcw size={16} className={inspRunsLoading ? 'animate-spin' : ''} />
                {zh ? '刷新记录' : 'Refresh'}
              </button>
            )}
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
        {/* Schedules sub-tab */}
        {inspSubTab === 'schedules' && (
          <div className="space-y-4">
            {showAddInspSchedule ? (
              <ScheduleEditor
                zh={zh}
                language={language}
                form={form}
                setForm={setForm}
                ipInput={ipInput}
                setIpInput={setIpInput}
                ipDevices={ipDevices}
                ipValidating={ipValidating}
                ipError={ipError}
                setIpError={setIpError}
                onValidateIps={validateAndAddIps}
                onRemoveIpDevice={removeIpDevice}
                tagFilter={tagFilter}
                setTagFilter={setTagFilter}
                availableScripts={availableScripts}
                scriptSearch={scriptSearch}
                setScriptSearch={setScriptSearch}
                showScriptDropdown={showScriptDropdown}
                setShowScriptDropdown={setShowScriptDropdown}
                onFetchScripts={fetchScripts}
                inspectionItems={inspectionItems}
                inspectionItemsLoading={inspectionItemsLoading}
                approvers={approvers}
                approverUsername={approverUsername}
                setApproverUsername={setApproverUsername}
                approvalStatus={approvalStatus}
                approvalError={approvalError}
                approvalCode={approvalCode}
                setApprovalCode={setApprovalCode}
                setApprovalError={setApprovalError}
                onRequestApproval={requestApproval}
                onVerifyApproval={verifyApproval}
                onResetApproval={resetApproval}
                onSubmit={addInspSchedule}
                onCancel={() => setShowAddInspSchedule(false)}
              />
            ) : (
              <>
                {/* Future Run projections filter bar */}
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-4 rounded-2xl border border-black/5 bg-white shadow-sm">
                  <div className="flex flex-wrap items-center gap-3">
                    {/* Name search */}
                    <div className="relative">
                      <input
                        type="text"
                        placeholder={zh ? '搜索计划名称...' : 'Search by name...'}
                        value={nameFilterInput}
                        onChange={(e) => setNameFilterInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            setSearchName(nameFilterInput);
                          }
                        }}
                        className="px-3 py-1.5 w-44 text-xs rounded-xl border border-slate-200 focus:outline-none focus:border-cyan-500 transition-all font-medium placeholder-slate-400 text-[#1e293b]"
                      />
                    </div>

                    {/* Time range buttons */}
                    <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
                      {(['1h', '4h', '12h', '1d', '3d', 'custom'] as const).map((r) => (
                        <button
                          key={r}
                          type="button"
                          onClick={() => {
                            setTimeRange(r);
                            if (r !== 'custom') {
                              setCustomStart('');
                              setCustomEnd('');
                            }
                          }}
                          className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                            timeRange === r
                              ? 'bg-white text-cyan-600 shadow-sm'
                              : 'text-slate-500 hover:text-slate-700'
                          }`}
                        >
                          {r === '1h' ? (zh ? '1小时' : '1 Hour') :
                           r === '4h' ? (zh ? '4小时' : '4 Hours') :
                           r === '12h' ? (zh ? '12小时' : '12 Hours') :
                           r === '1d' ? (zh ? '1天' : '1 Day') :
                           r === '3d' ? (zh ? '3天' : '3 Days') :
                           (zh ? '自定义' : 'Custom')}
                        </button>
                      ))}
                    </div>

                    {/* Custom time picker */}
                    {timeRange === 'custom' && (
                      <div className="flex items-center gap-2 animate-fadeIn">
                        <input
                          type="datetime-local"
                          value={customStart}
                          onChange={(e) => setCustomStart(e.target.value)}
                          className="px-2 py-1 text-xs rounded-xl border border-slate-200 focus:outline-none focus:border-cyan-500 font-mono text-[#1e293b]"
                        />
                        <span className="text-slate-400 text-xs">—</span>
                        <input
                          type="datetime-local"
                          value={customEnd}
                          onChange={(e) => setCustomEnd(e.target.value)}
                          className="px-2 py-1 text-xs rounded-xl border border-slate-200 focus:outline-none focus:border-cyan-500 font-mono text-[#1e293b]"
                        />
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setSearchName(nameFilterInput)}
                      className="px-4 py-1.5 rounded-xl text-xs font-bold text-white bg-cyan-600 hover:bg-cyan-500 transition-all active:scale-[0.97]"
                    >
                      {zh ? '查询' : 'Query'}
                    </button>
                    <button
                      onClick={() => {
                        setNameFilterInput('');
                        setSearchName('');
                        setTimeRange('1d');
                        setCustomStart('');
                        setCustomEnd('');
                      }}
                      className="px-3 py-1.5 rounded-xl text-xs font-bold border border-slate-200 text-slate-500 hover:bg-slate-50 transition-all active:scale-[0.97]"
                    >
                      {zh ? '重置' : 'Reset'}
                    </button>
                  </div>
                </div>

                <ScheduleList
                  zh={zh}
                  language={language}
                  schedules={paginatedSchedules}
                  loading={inspSchedulesLoading}
                  total={inspScheduleTotal}
                  page={inspSchedulePage}
                  pageSize={inspSchedulePageSize}
                  onPageChange={setInspSchedulePage}
                  onPageSizeChange={(size) => {
                    setInspSchedulePageSize(size);
                    setInspSchedulePage(1);
                  }}
                  onSelect={async (sch) => {
                    try {
                      const idToFetch = sch.job_id || sch.id;
                      const r = await fetch(`/api/scheduled-jobs/${idToFetch}`, { headers: authHeaders });
                      if (r.ok) {
                        const json = await r.json();
                        if (json.success) {
                          setSelectedSchedule(json.data);
                          setShowScheduleDetail(true);
                        }
                      }
                    } catch (e) {
                      console.error(e);
                    }
                  }}
                  onToggleEnabled={toggleInspScheduleEnabled}
                  onDelete={deleteInspSchedule}
                  availableScripts={availableScripts}
                />
              </>
            )}
          </div>
        )}

        {/* History sub-tab */}
        {inspSubTab === 'history' && (
          <HistoryList
            zh={zh}
            language={language}
            loading={inspRunsLoading}
            logs={filteredLogs}
            paginatedLogs={paginatedLogs}
            page={inspRunPage}
            pageSize={inspRunPageSize}
            onPageChange={setInspRunPage}
            onPageSizeChange={setInspRunPageSize}
            executionTypeFilter={executionTypeFilter}
            onFilterChange={setExecutionTypeFilter}
            onSelectLog={handleSelectLog}
            onExport={handleExportReport}
          />
        )}
      </div>

      {/* Modal/Slide-over details */}
      <ScheduleDetail
        zh={zh}
        open={showScheduleDetail}
        schedule={selectedSchedule}
        onClose={() => { setSelectedSchedule(null); setShowScheduleDetail(false); }}
        onToggleEnabled={(sch) => {
          toggleInspScheduleEnabled(sch);
          setSelectedSchedule(prev => prev ? { ...prev, enabled: prev.enabled ? 0 : 1 } : null);
        }}
        onDelete={(id) => {
          deleteInspSchedule(id);
          setShowScheduleDetail(false);
        }}
        onScheduleUpdate={setSelectedSchedule}
      />

      <ExecutionDetail
        zh={zh}
        open={isDetailModalOpen}
        selectedLog={selectedLog}
        logDetailLoading={logDetailLoading}
        onClose={() => setIsDetailModalOpen(false)}
        onExport={handleExportReport}
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
        onParseCmd={handleParseInspCmd}
        onCopyText={copyInspText}
        onFetchTrend={fetchTrend}
        setCollapsedCmds={setCollapsedCmds}
        setInspParseResults={setInspParseResults}
        pbDetail={pbDetail}
        pbDevices={pbDevices}
        pbApprovals={pbApprovals}
        pbApprovalsLoading={pbApprovalsLoading}
        pbApprovalActionId={pbApprovalActionId}
        pbApprovalError={pbApprovalError}
        onPlaybookApproval={handlePlaybookApproval}
        selectedPbDevice={selectedPbDevice}
        pbDeviceDetail={pbDeviceDetail}
        onSelectPbDevice={handleSelectPbDevice}
        devices={devices}
      />

      <CandidateModal
        zh={zh}
        open={candidateModalOpen}
        candidates={candidateList}
        onClose={() => {
          setCandidateModalOpen(false);
          setCandidateList([]);
        }}
        onToggle={toggleCandidateSelected}
        onToggleAll={toggleAllCandidates}
        onConfirm={confirmAddCandidates}
      />
    </div>
  );
};

export default ExecutionScheduleCoordinator;
