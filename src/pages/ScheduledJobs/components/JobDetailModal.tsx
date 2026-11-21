import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Info, X, CalendarClock, Target, FileText, ExternalLink, Lock, ShieldCheck, Clock3, CircleAlert, CheckCircle2, ChevronLeft, ChevronRight, LoaderCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Pagination from '../../../components/Pagination';
import { ScheduledJob, ScheduledJobRun, ScheduledJobRunsResponse } from '../types';
import { describeCron, describeScope } from '../helpers';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

interface JobDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  detailJob: ScheduledJob | null;
  openScriptManagement: (scriptId: string) => void;
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string }>;
  openEditModal: (job: ScheduledJob) => void;
  fetchScheduledJobDetail: (jobId: string, signal: AbortSignal) => Promise<ScheduledJob>;
  fetchScheduledJobRuns: (jobId: string, page: number, perPage: number, signal: AbortSignal) => Promise<ScheduledJobRunsResponse>;
  resolveScheduledJobRun: (jobId: string, runId: string, body: { outcome: 'succeeded' | 'partial_failure' | 'failed'; note: string }) => Promise<ScheduledJobRun>;
  language: string;
}

const grantStatusText = (status: string, zh: boolean): string => ({
  active: zh ? '有效' : 'Active',
  expired: zh ? '已过期' : 'Expired',
  exhausted: zh ? '额度已用尽' : 'Exhausted',
  revoked: zh ? '已撤销' : 'Revoked',
  reauthorization_required: zh ? '需要重新授权' : 'Reauthorization required',
}[status] || (status || (zh ? '状态未知' : 'Unknown status')));

const grantStatusClass = (status: string): string => ({
  active: 'bg-emerald-100 text-emerald-800',
  expired: 'bg-rose-100 text-rose-800',
  exhausted: 'bg-amber-100 text-amber-800',
  revoked: 'bg-slate-200 text-slate-700',
  reauthorization_required: 'bg-amber-100 text-amber-800',
}[status] || 'bg-slate-100 text-slate-600');

const runStatusText = (run: ScheduledJobRun, zh: boolean): string => {
  if (run.allowed_actions?.includes('resolve') || run.status === 'unknown') return zh ? '结果未知，需人工核实' : 'Unknown outcome · manual review required';
  return ({
    queued: zh ? '排队中' : 'Queued',
    running: zh ? '执行中' : 'Running',
    succeeded: zh ? '成功' : 'Succeeded',
    partial_failure: zh ? '部分失败' : 'Partial failure',
    failed: zh ? '失败' : 'Failed',
    cancelled: zh ? '已取消' : 'Cancelled',
  }[run.status] || run.status || (zh ? '状态未知' : 'Unknown status'));
};

const formatRunTime = (value: string | null | undefined, zh: boolean): string => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const getCollectorStatusLabel = (status: string, zh: boolean): string => {
  switch (status.toLowerCase()) {
    case 'supported': return zh ? '可用' : 'Supported';
    case 'partial': return zh ? '部分可解析' : 'Partially resolved';
    case 'parser_missing': return zh ? '缺少解析器' : 'Parser missing';
    case 'unsupported': return zh ? '不支持' : 'Unsupported';
    case 'projection': return zh ? '数据库投影' : 'Database projection';
    default: return status;
  }
};

const getCollectorStatusClass = (status: string): string => {
  switch (status.toLowerCase()) {
    case 'unsupported': return 'bg-rose-100 text-rose-800';
    case 'parser_missing':
    case 'partial': return 'bg-amber-100 text-amber-800';
    case 'projection': return 'bg-slate-100 text-slate-600';
    default: return 'bg-emerald-100 text-emerald-800';
  }
};

const getCollectorStatusDetail = (status: string, zh: boolean): string => {
  switch (status.toLowerCase()) {
    case 'unsupported': return zh
      ? '当前 profile/release 没有已发布 Registry action，且未找到同 parser 平台与版本的 TextFSM command 模板。'
      : 'No published Registry action or TextFSM command template matching this parser platform and release was found.';
    case 'parser_missing': return zh
      ? '当前 CLI 平台缺少匹配的解析器；这表示输出无法解析，不代表设备不支持该命令。'
      : 'No parser matches this CLI platform. Output parsing is unavailable; this does not mean the device lacks command support.';
    case 'partial': return zh
      ? '只有部分命令或输出解析可用；请查看各命令来源和条件说明。'
      : 'Only some commands or output parsers are available; review the command sources and conditions.';
    case 'projection': return zh
      ? '该采集项由数据库投影生成，不对应设备 CLI 命令。'
      : 'This fact is produced by a database projection and has no device CLI command.';
    default: return '';
  }
};

const getNoCommandMessage = (status: string | null | undefined, transport: string, zh: boolean): string => {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'unsupported') return getCollectorStatusDetail(normalized, zh);
  if (normalized === 'parser_missing') return getCollectorStatusDetail(normalized, zh);
  if (normalized === 'partial') return zh ? '当前采集项没有可解析命令，或仅部分命令可用。' : 'No command is resolved for this item, or only some commands are available.';
  if (normalized === 'projection') return getCollectorStatusDetail(normalized, zh);
  return zh ? `通过 ${transport} 或数据库派生，无对应 CLI 命令。` : `Uses ${transport} or database projection; no CLI command.`;
};

export const JobDetailModal: React.FC<JobDetailModalProps> = ({
  isOpen,
  onClose,
  detailJob,
  openScriptManagement,
  availableScripts,
  openEditModal,
  fetchScheduledJobDetail,
  fetchScheduledJobRuns,
  resolveScheduledJobRun,
  language,
}) => {
  useEscapeClose(isOpen, onClose);
  const navigate = useNavigate();
  const zh = language === 'zh';
  const [jobDetail, setJobDetail] = useState<ScheduledJob | null>(detailJob);
  const [jobDetailLoading, setJobDetailLoading] = useState(false);
  const [jobDetailError, setJobDetailError] = useState('');
  const [jobDetailForbidden, setJobDetailForbidden] = useState(false);
  const [jobDetailRetry, setJobDetailRetry] = useState(0);
  const [runs, setRuns] = useState<ScheduledJobRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsPage, setRunsPage] = useState(1);
  const [runsPageSize, setRunsPageSize] = useState(10);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState('');
  const [runsForbidden, setRunsForbidden] = useState(false);
  const [runsRetry, setRunsRetry] = useState(0);
  const [resolvingRunId, setResolvingRunId] = useState('');
  const [resolutionOutcome, setResolutionOutcome] = useState<'succeeded' | 'partial_failure' | 'failed'>('succeeded');
  const [resolutionNote, setResolutionNote] = useState('');
  const [resolutionError, setResolutionError] = useState('');
  const [resolutionForbidden, setResolutionForbidden] = useState(false);
  const [resolutionBusy, setResolutionBusy] = useState(false);

  useEffect(() => {
    if (!isOpen || !detailJob) {
      setJobDetail(null);
      setJobDetailError('');
      setJobDetailForbidden(false);
      setJobDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    setJobDetail(detailJob);
    setJobDetailError('');
    setJobDetailForbidden(false);
    setJobDetailLoading(true);
    void fetchScheduledJobDetail(detailJob.id, controller.signal)
      .then((job) => { if (!controller.signal.aborted) setJobDetail(job); })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = (error as { status?: number })?.status;
        setJobDetailForbidden(status === 403);
        setJobDetailError(error instanceof Error ? error.message : (zh ? '作业详情加载失败。' : 'Unable to load job details.'));
      })
      .finally(() => { if (!controller.signal.aborted) setJobDetailLoading(false); });
    return () => controller.abort();
  }, [detailJob?.id, fetchScheduledJobDetail, isOpen, jobDetailRetry, zh]);

  useEffect(() => {
    if (!isOpen || !detailJob) {
      setRuns([]);
      setRunsTotal(0);
      setRunsError('');
      setRunsForbidden(false);
      setRunsLoading(false);
      return;
    }
    const controller = new AbortController();
    setRunsLoading(true);
    setRunsError('');
    setRunsForbidden(false);
    void fetchScheduledJobRuns(detailJob.id, runsPage, runsPageSize, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) return;
        setRuns(response.items);
        setRunsTotal(response.total);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const status = (error as { status?: number })?.status;
        setRunsForbidden(status === 403);
        setRunsError(error instanceof Error ? error.message : (zh ? '运行记录加载失败。' : 'Unable to load run history.'));
      })
      .finally(() => { if (!controller.signal.aborted) setRunsLoading(false); });
    return () => controller.abort();
  }, [detailJob?.id, fetchScheduledJobRuns, isOpen, runsPage, runsPageSize, runsRetry, zh]);

  if (!isOpen || !detailJob) return null;

  const displayedJob = jobDetail || detailJob;
  const authorizationGrant = displayedJob.authorization_grant;
  const openTicket = (sourceType: string | null | undefined, ticketId: string | null | undefined) => {
    if (!ticketId) return;
    const search = sourceType === 'service_request'
      ? `?source_type=service_request&request_id=${encodeURIComponent(ticketId)}`
      : `?ticket_id=${encodeURIComponent(ticketId)}`;
    onClose();
    navigate(`/tickets${search}`);
  };
  const openChangeOrder = (changeOrderId?: string | null) => {
    if (!changeOrderId) return;
    onClose();
    navigate(`/change-orders/all?order_id=${encodeURIComponent(changeOrderId)}`);
  };

  const submitResolution = async (run: ScheduledJobRun) => {
    if (!resolutionNote.trim() || !run.allowed_actions?.includes('resolve') || resolutionBusy) return;
    setResolutionBusy(true);
    setResolutionError('');
    setResolutionForbidden(false);
    try {
      const updatedRun = await resolveScheduledJobRun(displayedJob.id, run.run_id, { outcome: resolutionOutcome, note: resolutionNote.trim() });
      setRuns(current => current.map(item => item.run_id === updatedRun.run_id ? updatedRun : item));
      setResolvingRunId('');
      setResolutionNote('');
      const controller = new AbortController();
      try { setJobDetail(await fetchScheduledJobDetail(displayedJob.id, controller.signal)); } catch { /* the saved run remains visible if the summary refresh fails */ }
    } catch (error) {
      const status = (error as { status?: number })?.status;
      setResolutionForbidden(status === 403);
      setResolutionError(error instanceof Error ? error.message : (zh ? '人工核实未能保存。' : 'Manual outcome could not be saved.'));
      if (status === 403) {
        setRuns(current => current.map(item => item.run_id === run.run_id ? { ...item, allowed_actions: (item.allowed_actions || []).filter(action => action !== 'resolve') } : item));
      }
    } finally {
      setResolutionBusy(false);
    }
  };

  const usedRuns = authorizationGrant?.used_runs ?? 0;
  const maxRuns = Math.max(1, Number(authorizationGrant?.max_runs || 1));
  const quotaPct = Math.min(100, Math.round((usedRuns / maxRuns) * 100));
  const manifestHash = authorizationGrant?.manifest_hash || '';
  const shortHash = manifestHash.length > 20 ? `${manifestHash.slice(0, 10)}…${manifestHash.slice(-8)}` : (manifestHash || '—');

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      >
        <div className="fixed inset-0 bg-slate-950/45 backdrop-blur-[2px]" onClick={onClose} />
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 16 }}
          transition={{ duration: 0.16 }}
          className="relative w-full max-w-3xl max-h-[86vh] bg-white dark:bg-slate-900 rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-slate-200/80 dark:border-white/10"
        >
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-100 dark:border-white/10 flex items-center justify-between bg-gradient-to-r from-slate-50/90 via-white to-blue-50/40 dark:from-slate-900 dark:via-slate-900 dark:to-slate-800/60">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-600 text-white flex items-center justify-center shadow-sm shadow-blue-600/20">
                <CalendarClock className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <h3 className="text-[15px] font-bold text-slate-900 dark:text-white truncate">{detailJob.name}</h3>
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border ${detailJob.enabled ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20' : 'bg-slate-100 text-slate-500 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${detailJob.enabled ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                    {detailJob.enabled ? (zh ? '已启用' : 'Active') : (zh ? '已停用' : 'Disabled')}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-slate-400 mt-1">
                  <span className="bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded font-mono text-[10px] text-slate-500 dark:text-slate-400" title={detailJob.id}>
                    {detailJob.id}
                  </span>
                  <span>·</span>
                  <span>{zh ? '定时作业详情' : 'Scheduled Job Detail'}</span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label={zh ? '关闭弹窗' : 'Close dialog'}
              className="p-2 rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-slate-200 transition-colors"
            >
              <X size={18} />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4 custom-scrollbar bg-slate-50/40 dark:bg-slate-950/20">
            {/* 1. Compact 3-Column Overview Strip */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="rounded-xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-white/10 p-3.5 shadow-xs">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400 mb-1.5">
                  <CalendarClock size={13} className="text-blue-600" />
                  {zh ? '执行周期' : 'Schedule'}
                </div>
                <p className="text-[13px] font-bold text-slate-800 dark:text-slate-100">
                  {describeCron(detailJob.cron_expr, zh)}
                </p>
                <p className="mt-1 inline-block rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-[10px] font-mono text-slate-500">
                  {detailJob.cron_expr}
                </p>
              </div>

              <div className="rounded-xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-white/10 p-3.5 shadow-xs">
                <div className="flex items-center justify-between gap-1.5 text-[11px] font-semibold text-slate-400 mb-1.5">
                  <span className="inline-flex items-center gap-1.5">
                    <Target size={13} className="text-indigo-600" />
                    {zh ? '执行范围' : 'Target Scope'}
                  </span>
                  {detailJob.device_scope === 'ip' && (
                    <span className="text-[10px] font-medium text-slate-400">
                      {(detailJob.device_filter || '').split(',').filter(Boolean).length} {zh ? '台' : 'hosts'}
                    </span>
                  )}
                </div>
                <p className="text-[13px] font-bold text-slate-800 dark:text-slate-100">
                  {detailJob.device_scope === 'all' ? (zh ? '全部在线设备' : 'All Online Devices') :
                   detailJob.device_scope === 'ip' ? (zh ? '按 IP 指定' : 'By IP Address') :
                   detailJob.device_scope === 'tag' ? (zh ? '按标签筛选' : 'By Tags') : (zh ? '自定义范围' : 'Custom')}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {detailJob.device_scope === 'ip' && detailJob.device_filter ? (
                    detailJob.device_filter.split(',').slice(0, 3).map((ip, idx) => (
                      <span key={idx} className="inline-flex items-center px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[10px] font-mono text-slate-600 dark:text-slate-300">
                        {ip.trim()}
                      </span>
                    ))
                  ) : (
                    <span className="text-[11px] text-slate-400 truncate">
                      {detailJob.device_filter || (zh ? '动态扫描在线设备' : 'Dynamic online devices')}
                    </span>
                  )}
                </div>
              </div>

              <div className="rounded-xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-white/10 p-3.5 shadow-xs">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400 mb-1.5">
                  <FileText size={13} className="text-emerald-600" />
                  {zh ? '执行方式' : 'Execution Method'}
                </div>
                <p className="text-[13px] font-bold text-slate-800 dark:text-slate-100">
                  {detailJob.action_type === 'backup' ? (zh ? '配置备份' : 'Configuration backup') :
                   detailJob.action_type === 'arp_sweep' ? (zh ? 'ARP 分批采集' : 'Bounded ARP sweep') :
                   detailJob.action_type === 'bgp_neighbors' ? (zh ? 'BGP 邻居采集' : 'BGP neighbor collection') :
                   detailJob.action_type === 'ospf_neighbors' ? (zh ? 'OSPF 邻居采集' : 'OSPF neighbor collection') :
                   detailJob.action_type === 'nsot' ? (zh ? '全量 NSOT 作业（已下线）' : 'Full NSOT job (retired)') :
                   detailJob.action_type === 'inspection' ? (zh ? '智能巡检' : 'Smart inspection') :
                   detailJob.action_type === 'command' ? (zh ? '命令执行' : 'Command execution') :
                   (zh ? '自动化脚本' : 'Automation script')}
                </p>
                <div className="mt-1 truncate text-[11px] text-slate-500">
                  {detailJob.script_id ? (
                    <button
                      type="button"
                      onClick={() => openScriptManagement(detailJob.script_id!)}
                      aria-label={zh ? `打开脚本：${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}` : `Open script: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}`}
                      title={zh ? '点击跳转到脚本管理' : 'Open in script management'}
                      className="inline-flex max-w-full items-center gap-1 truncate font-semibold text-blue-600 hover:text-blue-700 hover:underline"
                    >
                      <span className="truncate">{availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}</span>
                      <ExternalLink size={11} className="shrink-0" />
                    </button>
                  ) : detailJob.action_type === 'command'
                    ? (zh ? '按审批命令执行' : 'Approved commands')
                    : detailJob.action_type === 'inspection'
                      ? (zh ? '平台内置巡检项' : 'Built-in checks')
                      : (zh ? '系统托管动作' : 'Platform managed')}
                </div>
              </div>
            </div>

            {/* 2. Authorization Card */}
            <section className="rounded-xl border border-slate-200/80 dark:border-white/10 bg-white dark:bg-slate-900 overflow-hidden shadow-xs" aria-label={zh ? '作业授权' : 'Job authorization'}>
              <div className="px-4 py-3 border-b border-slate-100 dark:border-white/10 flex flex-wrap items-center justify-between gap-2 bg-slate-50/60 dark:bg-slate-800/40">
                <div className="flex items-center gap-2">
                  <ShieldCheck size={15} className="shrink-0 text-blue-600" />
                  <h4 className="text-xs font-bold text-slate-800 dark:text-slate-100">{zh ? '有界授权与审批凭证' : 'Bounded Authorization'}</h4>
                  {authorizationGrant && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${grantStatusClass(authorizationGrant.status)}`}>
                      {grantStatusText(authorizationGrant.status, zh)}
                    </span>
                  )}
                </div>
                {authorizationGrant && (
                  <span className="text-[10px] font-mono text-slate-400">
                    v{authorizationGrant.version ?? '—'} · {String(authorizationGrant.template_version || '—').slice(0, 10)}
                  </span>
                )}
              </div>

              <div className="p-4">
                {jobDetailLoading && !authorizationGrant && <p role="status" className="text-xs text-slate-500">{zh ? '正在加载授权信息…' : 'Loading authorization…'}</p>}
                {jobDetailError && <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-800"><span>{jobDetailForbidden ? (zh ? '当前账号无权查看作业授权详情。' : 'You do not have permission to view job authorization details.') : jobDetailError}</span><button type="button" onClick={() => setJobDetailRetry(value => value + 1)} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button></div>}
                {!jobDetailLoading && !jobDetailError && !authorizationGrant && <p role="status" className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">{zh ? '服务端未返回该作业的授权信息。' : 'No authorization details were returned for this job.'}</p>}
                {authorizationGrant && (
                  <div className="space-y-3.5">
                    {/* Quota Progress Bar */}
                    <div className="rounded-lg bg-slate-50 dark:bg-slate-800/50 px-3.5 py-2.5 border border-slate-100 dark:border-white/5">
                      <div className="flex items-center justify-between text-[11px] mb-1.5">
                        <span className="font-medium text-slate-500">{zh ? '授权执行次数' : 'Execution Count'}</span>
                        <span className="font-bold text-slate-700 dark:text-slate-200">
                          {Number(authorizationGrant.max_runs || 0) > 0 ? (
                            <>
                              {usedRuns} / {authorizationGrant.max_runs}
                              <span className="ml-1.5 font-normal text-slate-400">
                                ({zh ? `剩余 ${authorizationGrant.remaining_runs ?? '—'} 次` : `${authorizationGrant.remaining_runs ?? '—'} left`})
                              </span>
                            </>
                          ) : (
                            <>
                              {zh ? `已执行 ${usedRuns} 次` : `${usedRuns} runs`}
                              <span className="ml-1.5 font-normal text-emerald-600">
                                ({zh ? '不限次数' : 'Unlimited'})
                              </span>
                            </>
                          )}
                        </span>
                      </div>
                      {Number(authorizationGrant.max_runs || 0) > 0 && (
                        <div className="h-1.5 w-full rounded-full bg-slate-200/80 dark:bg-slate-700 overflow-hidden">
                          <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all" style={{ width: `${Math.max(quotaPct, usedRuns > 0 ? 6 : 0)}%` }} />
                        </div>
                      )}
                    </div>

                    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2.5 text-[11px]">
                      <div className="flex items-center justify-between gap-2 py-1 border-b border-slate-100 dark:border-white/5">
                        <dt className="text-slate-400 shrink-0">{zh ? '有效期至' : 'Valid until'}</dt>
                        <dd className="font-semibold text-slate-700 dark:text-slate-200 truncate">{formatRunTime(authorizationGrant.valid_until, zh)}</dd>
                      </div>
                      <div className="flex items-center justify-between gap-2 py-1 border-b border-slate-100 dark:border-white/5">
                        <dt className="text-slate-400 shrink-0">{zh ? '批准范围' : 'Approved scope'}</dt>
                        <dd className="font-semibold text-slate-700 dark:text-slate-200 truncate" title={describeScope(displayedJob.device_scope, displayedJob.device_filter, zh)}>
                          {describeScope(displayedJob.device_scope, displayedJob.device_filter, zh)}
                          {Number(authorizationGrant.max_targets || 0) > 0
                            ? ` · ${zh ? `≤${authorizationGrant.max_targets} 台` : `≤${authorizationGrant.max_targets}`}`
                            : ''}
                        </dd>
                      </div>
                      <div className="flex items-center justify-between gap-2 py-1 border-b border-slate-100 dark:border-white/5">
                        <dt className="text-slate-400 shrink-0">{zh ? '关联工单' : 'Linked ticket'}</dt>
                        <dd className="min-w-0 truncate">
                          {authorizationGrant.ticket_id ? (
                            <button
                              type="button"
                              onClick={() => openTicket(authorizationGrant.ticket_source_type, authorizationGrant.ticket_id)}
                              title={`${authorizationGrant.ticket_number || authorizationGrant.ticket_id}${authorizationGrant.ticket_title ? ` · ${authorizationGrant.ticket_title}` : ''}`}
                              className="inline-flex max-w-full items-center gap-1 truncate font-semibold text-blue-600 hover:underline"
                            >
                              <span className="truncate">{authorizationGrant.ticket_number || authorizationGrant.ticket_id}</span>
                              <ExternalLink size={10} className="shrink-0" />
                            </button>
                          ) : <span className="text-slate-400">—</span>}
                        </dd>
                      </div>
                      <div className="flex items-center justify-between gap-2 py-1 border-b border-slate-100 dark:border-white/5">
                        <dt className="text-slate-400 shrink-0">{zh ? '关联变更单' : 'Change order'}</dt>
                        <dd className="min-w-0 truncate">
                          {authorizationGrant.change_order_id ? (
                            <button type="button" onClick={() => openChangeOrder(authorizationGrant.change_order_id)} className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:underline">
                              {authorizationGrant.change_order_number || authorizationGrant.change_order_id}
                              <ExternalLink size={10} className="shrink-0" />
                            </button>
                          ) : <span className="text-slate-400">{zh ? '未关联' : 'Not linked'}</span>}
                        </dd>
                      </div>
                      <div className="sm:col-span-2 flex items-center justify-between gap-2 py-1">
                        <dt className="text-slate-400 shrink-0">{zh ? '授权摘要哈希' : 'Manifest hash'}</dt>
                        <dd className="font-mono text-[10px] text-slate-500 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded" title={manifestHash}>
                          {shortHash}
                        </dd>
                      </div>
                    </dl>
                  </div>
                )}
              </div>
            </section>

            {/* 3. Run History Card */}
            <section className="rounded-xl border border-slate-200/80 dark:border-white/10 bg-white dark:bg-slate-900 overflow-hidden shadow-xs" aria-label={zh ? '周期作业运行记录' : 'Scheduled job runs'}>
              <div className="px-4 py-3 border-b border-slate-100 dark:border-white/10 flex items-center justify-between gap-2 bg-slate-50/60 dark:bg-slate-800/40">
                <div className="flex items-center gap-2">
                  <Clock3 size={15} className="shrink-0 text-slate-500" />
                  <h4 className="text-xs font-bold text-slate-800 dark:text-slate-100">{zh ? '运行记录' : 'Run history'}</h4>
                  <span className="rounded-full bg-slate-200/70 dark:bg-slate-700 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:text-slate-300">
                    {zh ? `共 ${runsTotal} 次` : `${runsTotal} runs`}
                  </span>
                </div>
                <span className="text-[10px] text-slate-400">{zh ? '未知结果需人工核实' : 'Unknown outcomes require review'}</span>
              </div>
              <div className="p-4">
                {runsLoading && <p role="status" className="flex items-center gap-2 py-4 text-xs text-slate-500"><LoaderCircle size={14} className="animate-spin" />{zh ? '正在加载运行记录…' : 'Loading run history…'}</p>}
                {!runsLoading && runsError && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-800"><span>{runsForbidden ? (zh ? '当前账号无权查看运行记录。' : 'You do not have permission to view run history.') : runsError}</span><button type="button" onClick={() => setRunsRetry(value => value + 1)} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button></div>}
                {!runsLoading && !runsError && runs.length === 0 && (
                  <div role="status" className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/20 py-6 text-center">
                    <Clock3 size={20} className="text-slate-300 mb-1.5" />
                    <p className="text-xs font-medium text-slate-500">{zh ? '该作业暂无运行记录。' : 'No runs have been recorded for this job.'}</p>
                    <p className="text-[10px] text-slate-400 mt-0.5">{zh ? '到达计划时间后将自动触发执行并记录结果' : 'Execution records will appear here once triggered'}</p>
                  </div>
                )}
                {!runsLoading && !runsError && runs.length > 0 && <ol className="space-y-2">
                  {runs.map(run => {
                    const canResolve = run.allowed_actions?.includes('resolve') === true;
                    const unknown = canResolve || run.status === 'unknown';
                    return <li key={run.run_id} className="rounded-xl border border-slate-200/80 dark:border-white/10 bg-slate-50/60 dark:bg-slate-800/30 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0"><p className="break-all font-mono text-[10px] font-semibold text-slate-700 dark:text-slate-200">{run.run_id}</p><p className={`mt-1 inline-flex items-center gap-1 text-[10px] font-bold ${unknown ? 'text-amber-800' : run.status === 'succeeded' ? 'text-emerald-700' : ['failed', 'partial_failure'].includes(run.status) ? 'text-rose-700' : 'text-slate-600'}`}>{unknown ? <CircleAlert size={11} /> : run.status === 'succeeded' ? <CheckCircle2 size={11} /> : null}{runStatusText(run, zh)}</p></div>
                        {run.authorization_version != null && <span className="rounded bg-white dark:bg-slate-900 border border-slate-200/70 px-2 py-0.5 text-[9px] text-slate-500">{zh ? '授权版本' : 'Grant'} v{run.authorization_version}</span>}
                      </div>
                      <dl className="mt-2 grid gap-x-4 gap-y-1 text-[10px] sm:grid-cols-2">
                        <div><dt className="inline text-slate-400">{zh ? '计划：' : 'Scheduled: '}</dt><dd className="inline text-slate-700 dark:text-slate-300">{formatRunTime(run.scheduled_for, zh)}</dd></div>
                        <div><dt className="inline text-slate-400">{zh ? '开始 / 结束：' : 'Started / finished: '}</dt><dd className="inline text-slate-700 dark:text-slate-300">{formatRunTime(run.started_at, zh)} / {formatRunTime(run.finished_at, zh)}</dd></div>
                        <div><dt className="inline text-slate-400">{zh ? '目标 / 成功 / 失败：' : 'Targets / success / failure: '}</dt><dd className="inline text-slate-700 dark:text-slate-300">{run.target_count ?? '—'} / {run.success_count ?? '—'} / {run.failure_count ?? '—'}</dd></div>
                        <div className="flex flex-wrap gap-x-2"><dt className="text-slate-400">{zh ? '关联：' : 'Linked: '}</dt><dd className="flex flex-wrap gap-x-2">{run.ticket_id ? <button type="button" onClick={() => openTicket(run.ticket_source_type, run.ticket_id)} className="font-semibold text-blue-600 hover:underline">{run.ticket_number || run.ticket_id}</button> : null}{run.change_order_id ? <button type="button" onClick={() => openChangeOrder(run.change_order_id)} className="font-semibold text-blue-600 hover:underline">{run.change_order_number || run.change_order_id}</button> : null}{!run.ticket_id && !run.change_order_id ? <span className="text-slate-700">—</span> : null}</dd></div>
                      </dl>
                      {run.summary && <p className="mt-2 whitespace-pre-wrap break-words text-[10px] text-slate-700 dark:text-slate-300">{run.summary}</p>}
                      {run.error && <p className="mt-1 whitespace-pre-wrap break-words rounded-md bg-rose-50 px-2 py-1.5 text-[10px] text-rose-800">{run.error}</p>}
                      {unknown && !canResolve && <p role="note" className="mt-2 text-[10px] text-slate-500">{zh ? '当前账号不能提交结果核实。' : 'Your account cannot resolve this run outcome.'}</p>}
                      {canResolve && resolvingRunId !== run.run_id && <button type="button" onClick={() => { setResolvingRunId(run.run_id); setResolutionOutcome('succeeded'); setResolutionNote(''); setResolutionError(''); setResolutionForbidden(false); }} className="mt-2 min-h-8 rounded-lg border border-amber-300 bg-amber-50 px-3 text-[10px] font-bold text-amber-900 hover:bg-amber-100">{zh ? '人工核实结果' : 'Resolve outcome'}</button>}
                      {canResolve && resolvingRunId === run.run_id && <div className="mt-3 space-y-2 border-t border-slate-200 pt-3">
                        <label className="block text-[10px] font-semibold text-slate-600">{zh ? '核实结果' : 'Verified outcome'}<select aria-label={zh ? '核实结果' : 'Verified outcome'} value={resolutionOutcome} onChange={event => setResolutionOutcome(event.target.value as typeof resolutionOutcome)} className="mt-1 min-h-8 w-full rounded-lg border border-slate-200 bg-white px-2 text-[11px] font-normal text-slate-700"><option value="succeeded">{zh ? '成功' : 'Succeeded'}</option><option value="partial_failure">{zh ? '部分失败' : 'Partial failure'}</option><option value="failed">{zh ? '失败' : 'Failed'}</option></select></label>
                        <label className="block text-[10px] font-semibold text-slate-600">{zh ? '核实说明' : 'Review note'}<textarea aria-label={zh ? '核实说明' : 'Review note'} required rows={2} value={resolutionNote} onChange={event => setResolutionNote(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[11px] font-normal text-slate-700" /></label>
                        {resolutionError && <p role="alert" className="text-[10px] text-rose-700">{resolutionForbidden ? (zh ? '当前账号无权核实此运行结果。' : 'You are not permitted to resolve this run.') : resolutionError}</p>}
                        <div className="flex justify-end gap-2"><button type="button" onClick={() => { setResolvingRunId(''); setResolutionError(''); }} disabled={resolutionBusy} className="min-h-8 rounded-lg border border-slate-200 px-3 text-[10px] font-semibold text-slate-600 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button><button type="button" onClick={() => void submitResolution(run)} disabled={!resolutionNote.trim() || resolutionBusy} className="inline-flex min-h-8 items-center gap-1.5 rounded-lg bg-amber-700 px-3 text-[10px] font-bold text-white disabled:opacity-50">{resolutionBusy && <LoaderCircle size={11} className="animate-spin" />}{zh ? '保存核实结果' : 'Save verified outcome'}</button></div>
                      </div>}
                    </li>;
                  })}
                </ol>}
                {!runsLoading && !runsError && runsTotal > 0 && <div className="mt-3 border-t border-slate-100 pt-2"><Pagination currentPage={runsPage} totalItems={runsTotal} itemsPerPage={runsPageSize} onPageChange={setRunsPage} onItemsPerPageChange={size => { setRunsPageSize(size); setRunsPage(1); }} language={language} /></div>}
              </div>
            </section>

            {/* 4. Compact Audit Meta Bar */}
            <div className="rounded-xl border border-slate-200/70 dark:border-white/10 bg-white dark:bg-slate-900 px-4 py-3 grid grid-cols-1 sm:grid-cols-3 gap-3 text-[11px]">
              <div>
                <p className="text-[10px] text-slate-400">{zh ? '审批人' : 'Approver'}</p>
                <p className="mt-0.5 font-semibold text-slate-700 dark:text-slate-200">{detailJob.approved_by || (zh ? '系统自核' : 'Auto')}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-400">{zh ? '创建者' : 'Creator'}</p>
                <p className="mt-0.5 font-semibold text-slate-700 dark:text-slate-200">{detailJob.created_by} · {new Date(detailJob.created_at).toLocaleDateString()}</p>
              </div>
              <div className="min-w-0">
                <p className="text-[10px] text-slate-400">{zh ? '配置原因' : 'Reason'}</p>
                <p className="mt-0.5 font-medium text-slate-600 dark:text-slate-300 truncate" title={detailJob.config_reason || ''}>{detailJob.config_reason || '—'}</p>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-3.5 bg-white dark:bg-slate-900 border-t border-slate-100 dark:border-white/10 flex items-center justify-end gap-2.5">
            <button
              onClick={onClose}
              className="px-5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              {zh ? '关闭' : 'Close'}
            </button>
            {detailJob.authorization_mode === 'system' ? (
              <p className="inline-flex items-center gap-1.5 text-xs text-slate-500" role="note">
                <Lock size={13} />
                {zh ? '系统内置作业由平台托管，此处仅可查看。' : 'This built-in job is platform-managed and read-only here.'}
              </p>
            ) : (
              <button
                onClick={() => {
                  onClose();
                  openEditModal(detailJob);
                }}
                className="px-5 py-2 rounded-xl bg-blue-600 text-white text-xs font-semibold shadow-sm shadow-blue-600/20 hover:bg-blue-700 transition-colors"
              >
                {zh ? '编辑该作业' : 'Edit Job'}
              </button>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
