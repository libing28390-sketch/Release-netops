import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Info, X, CalendarClock, Target, FileText, ExternalLink, Lock, ShieldCheck, Clock3, CircleAlert, CheckCircle2, ChevronLeft, ChevronRight, LoaderCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Pagination from '../../../components/Pagination';
import { NsotCollectionPreview, ScheduledJob, ScheduledJobRun, ScheduledJobRunsResponse } from '../types';
import { describeCron, describeScope } from '../helpers';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

interface JobDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  detailJob: ScheduledJob | null;
  openScriptManagement: (scriptId: string) => void;
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string }>;
  openEditModal: (job: ScheduledJob) => void;
  fetchNsotCollectionPreview: (jobId: string, signal: AbortSignal) => Promise<NsotCollectionPreview>;
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
  fetchNsotCollectionPreview,
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
  const [nsotPreview, setNsotPreview] = useState<NsotCollectionPreview | null>(null);
  const [nsotPreviewLoading, setNsotPreviewLoading] = useState(false);
  const [nsotPreviewError, setNsotPreviewError] = useState('');
  const [nsotPreviewRetry, setNsotPreviewRetry] = useState(0);

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

  useEffect(() => {
    if (!isOpen || detailJob?.action_type !== 'nsot') {
      setNsotPreview(null);
      setNsotPreviewError('');
      setNsotPreviewLoading(false);
      return;
    }

    const controller = new AbortController();
    setNsotPreview(null);
    setNsotPreviewError('');
    setNsotPreviewLoading(true);
    void fetchNsotCollectionPreview(detailJob.id, controller.signal)
      .then((preview) => {
        if (!controller.signal.aborted) setNsotPreview(preview);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setNsotPreviewError(error instanceof Error ? error.message : (zh ? '采集预览加载失败。' : 'Could not load the collection preview.'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setNsotPreviewLoading(false);
      });

    return () => controller.abort();
  }, [detailJob?.action_type, detailJob?.id, fetchNsotCollectionPreview, isOpen, nsotPreviewRetry, zh]);

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

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      >
        <div className="fixed inset-0 bg-black/40" onClick={onClose} />
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          className="relative w-full max-w-2xl max-h-[85vh] bg-white rounded-3xl shadow-2xl flex flex-col overflow-hidden border border-black/5"
        >
          {/* Header */}
          <div className="px-6 py-5 border-b border-black/[0.03] flex items-center justify-between bg-gradient-to-r from-slate-50/50 to-white">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-cyan-500/10 flex items-center justify-center">
                <Info className="w-5 h-5 text-cyan-600" />
              </div>
              <div>
                <h3 className="text-base font-bold text-[#164e63]">{detailJob.name}</h3>
                <div className="flex items-center gap-2 text-[10px] text-black/40 mt-0.5">
                  <span className="bg-slate-100 px-1.5 py-0.5 rounded font-mono">{detailJob.id}</span>
                  <span>·</span>
                  <span>{zh ? '定时作业详情' : 'Scheduled Job Detail'}</span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all"
            >
              <X size={20} />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
            {/* 1. Schedule & Scope Grid */}
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 rounded-2xl bg-slate-50/50 border border-black/[0.02]">
                <div className="flex items-center gap-2 text-[11px] font-bold text-black/40 mb-2 uppercase tracking-wider">
                  <CalendarClock size={12} />
                  {zh ? '执行周期' : 'Schedule'}
                </div>
                <p className="text-sm font-semibold text-[#0e7490]">
                  {describeCron(detailJob.cron_expr, zh)}
                </p>
                <p className="text-[10px] font-mono text-black/30 mt-1">{detailJob.cron_expr}</p>
              </div>
              <div className="p-4 rounded-2xl bg-slate-50/50 border border-black/[0.02]">
                <div className="flex items-center gap-2 text-[11px] font-bold text-black/40 mb-2 uppercase tracking-wider">
                  <Target size={12} />
                  {zh ? '执行范围' : 'Target Scope'}
                </div>
                <p className="text-sm font-semibold text-slate-700">
                  {detailJob.device_scope === 'all' ? (zh ? '全部在线设备' : 'All Online Devices') :
                   detailJob.device_scope === 'ip' ? (zh ? '按 IP 指定' : 'By IP Address') :
                   detailJob.device_scope === 'tag' ? (zh ? '按标签筛选' : 'By Tags') : (zh ? '自定义范围' : 'Custom')}
                </p>
                <p className="text-[10px] text-black/40 mt-1 truncate">
                  {detailJob.device_filter || (zh ? '无额外过滤条件' : 'No filter')}
                </p>
              </div>
            </div>

            {/* 2. Device List (IP List) */}
            {(detailJob.device_scope === 'ip' || detailJob.device_scope === 'all') && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-[11px] font-bold text-black/50 uppercase tracking-wider">{zh ? '执行 IP 列表' : 'Target IPs'}</h4>
                  <span className="text-[10px] text-black/30">
                    {detailJob.device_scope === 'all' ? (zh ? '动态获取' : 'Dynamic') : `${(detailJob.device_filter || '').split(',').length} 个目标`}
                  </span>
                </div>
                <div className="p-3 rounded-2xl border border-black/[0.04] bg-slate-50/30">
                  <div className="flex flex-wrap gap-1.5">
                    {detailJob.device_scope === 'all' ? (
                      <div className="text-[11px] text-black/40 italic px-2 py-1">{zh ? '作业运行时将自动扫描所有在线设备' : 'Automatically targets all online devices at runtime'}</div>
                    ) : (
                      (detailJob.device_filter || '').split(',').map((ip, idx) => (
                        <span key={idx} className="inline-flex items-center px-2 py-0.5 rounded-md bg-white border border-black/[0.06] text-[11px] font-mono text-slate-600 shadow-sm">
                          {ip.trim()}
                        </span>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* 3. Execution summary */}
            <div>
              <h4 className="text-[11px] font-bold text-black/50 uppercase tracking-wider mb-2">{zh ? '执行方式' : 'Execution Method'}</h4>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <FileText size={15} className="shrink-0 text-cyan-700" />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-800">
                        {detailJob.action_type === 'backup' ? (zh ? '配置备份' : 'Configuration backup') :
                         detailJob.action_type === 'nsot' ? (zh ? 'NSOT 网络事实库采集' : 'NSOT facts collection') :
                         detailJob.action_type === 'inspection' ? (zh ? '智能巡检' : 'Smart inspection') :
                         detailJob.action_type === 'command' ? (zh ? '命令执行' : 'Command execution') :
                         (zh ? '自动化脚本' : 'Automation script')}
                      </p>
                      <div className="mt-0.5 truncate text-[11px] text-slate-500">
                        {detailJob.script_id ? (
                          <span className="inline-flex max-w-full items-center gap-1">
                            <span>{zh ? '绑定脚本：' : 'Bound script: '}</span>
                            <button
                              type="button"
                              onClick={() => openScriptManagement(detailJob.script_id!)}
                              aria-label={zh ? `打开脚本：${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}` : `Open script: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}`}
                              title={zh ? '点击跳转到脚本管理' : 'Open in script management'}
                              className="inline-flex max-w-full items-center gap-1 truncate font-semibold text-blue-700 hover:text-blue-600 hover:underline"
                            >
                              <span className="truncate">{availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}</span>
                              <ExternalLink size={11} className="shrink-0" />
                            </button>
                          </span>
                        ) : detailJob.action_type === 'command'
                            ? (zh ? '命令已配置，按审批后的内容执行。' : 'Commands are configured and run from the approved content.')
                            : detailJob.action_type === 'inspection'
                              ? (zh ? '使用平台内置巡检项。' : 'Uses built-in inspection checks.')
                              : detailJob.action_type === 'backup'
                                ? (zh ? '采集设备配置并进行版本比对。' : 'Collects device configuration and tracks versions.')
                                : detailJob.action_type === 'nsot'
                                  ? (zh ? '按目标范围采集网络事实。' : 'Collects network facts for the selected scope.')
                                : (zh ? '未关联脚本。' : 'No script is linked.')}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {detailJob.action_type === 'nsot' && (
              <section className="rounded-2xl border border-cyan-200/80 bg-cyan-50/40 p-4 space-y-4" aria-label={zh ? 'NSOT 采集预览' : 'NSOT collection preview'}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-bold text-slate-800">{zh ? '采集指标与命令预览' : 'Collection facts & command preview'}</h4>
                    <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
                      {zh
                        ? '按当前在线目标、设备模板和平台生成的只读预览；不会连接设备。运行时发现 VRF/协议、平台能力及命令回退可能改变实际命令。'
                        : 'Read-only preview from current online targets, device templates, and platforms. It does not connect to devices. Runtime VRF/protocol discovery, platform capabilities, and fallbacks can change the actual commands.'}
                    </p>
                  </div>
                  {nsotPreview && (
                    <span className="shrink-0 rounded-full bg-white/80 px-2.5 py-1 text-[10px] font-semibold text-cyan-800">
                      {zh ? `当前在线目标 ${nsotPreview.target_count} 台` : `${nsotPreview.target_count} current online targets`}
                    </span>
                  )}
                </div>

                {nsotPreviewLoading && (
                  <div role="status" className="rounded-xl border border-cyan-100 bg-white/70 px-3 py-4 text-xs text-slate-500">
                    {zh ? '正在生成采集预览…' : 'Generating collection preview…'}
                  </div>
                )}
                {!nsotPreviewLoading && nsotPreviewError && (
                  <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-3 text-xs text-rose-800">
                    <span>{nsotPreviewError}</span>
                    <button type="button" onClick={() => setNsotPreviewRetry((attempt) => attempt + 1)} className="rounded-lg border border-rose-300 px-2.5 py-1.5 font-semibold hover:bg-rose-100">
                      {zh ? '重试' : 'Retry'}
                    </button>
                  </div>
                )}
                {!nsotPreviewLoading && !nsotPreviewError && nsotPreview?.target_count === 0 && (
                  <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
                    {zh ? '当前作业范围内没有在线目标设备，因此本次不会下发采集命令。' : 'No online devices currently match this job scope, so no collection commands would be sent.'}
                  </div>
                )}
                {!nsotPreviewLoading && !nsotPreviewError && nsotPreview && nsotPreview.target_count > 0 && nsotPreview.groups.length === 0 && (
                  <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
                    {zh ? '目标设备当前没有可展示的采集项。请检查设备策略和查看权限。' : 'No collection items are available for the current targets. Check device policies and your access scope.'}
                  </div>
                )}

                {!nsotPreviewLoading && nsotPreview?.groups.map((group, groupIndex) => {
                  const deviceSoftwareVersion = group.software_version;
                  const registryReleaseNumber = group.registry_release_number || group.release_number;
                  return (
                  <details key={`${group.platform}:${group.template_id}:${group.role || ''}:${groupIndex}`} open={groupIndex === 0} className="rounded-xl border border-slate-200 bg-white/90">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-3 py-3 text-xs">
                      <span className="font-bold text-slate-800">
                        {group.platform_label || group.platform || (zh ? '未知平台' : 'Unknown platform')}
                        {group.profile_label && <span className="ml-1.5 font-medium text-slate-600">· {group.profile_label}</span>}
                        {deviceSoftwareVersion && <span className="ml-1.5 font-normal text-slate-500">({zh ? '设备软件版本' : 'device software version'} {deviceSoftwareVersion})</span>}
                        {registryReleaseNumber && <span className="ml-1.5 font-normal text-slate-500">({zh ? 'Registry release_number' : 'Registry release_number'} {registryReleaseNumber})</span>}
                        <span className="mx-1.5 text-slate-300">·</span>
                        {group.template_name || group.template_id}
                        {group.role && <span className="ml-1.5 font-normal text-slate-500">({group.role})</span>}
                      </span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 font-semibold text-slate-600">
                        {zh ? `${group.device_count} 台` : `${group.device_count} devices`}
                      </span>
                    </summary>
                    <div className="space-y-3 border-t border-slate-100 p-3">
                      <div>
                        <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">{zh ? '采集事实 / 指标' : 'Facts / metrics'}</p>
                        <div className="flex flex-wrap gap-1.5">
                          {group.collectors.map((collector) => (
                            <span key={collector.key} className="inline-flex items-center gap-1 rounded-full bg-cyan-50 px-2 py-1 text-[10px] text-cyan-900">
                              <span className="font-semibold">{collector.label}</span>
                              <span className="text-cyan-700/70">{collector.transport}</span>
                              {collector.conditional && <span className="rounded bg-amber-100 px-1 text-amber-800">{zh ? '条件' : 'Conditional'}</span>}
                              {collector.status && <span className={`rounded px-1 ${getCollectorStatusClass(collector.status)}`}>{getCollectorStatusLabel(collector.status, zh)}</span>}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div>
                        <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">{zh ? '对应只读命令' : 'Related read-only commands'}</p>
                        <div className="space-y-2">
                          {group.collectors.map((collector) => (
                            <div key={collector.key} className="grid gap-1 sm:grid-cols-[minmax(8rem,0.7fr)_minmax(0,1.5fr)] sm:gap-3">
                              <div className="text-[10px] font-semibold text-slate-600">
                                {collector.label}
                                {collector.conditional && <span className="ml-1 font-normal text-amber-700">{zh ? '（按条件）' : '(conditional)'}</span>}
                                {collector.status && <span className={`ml-1 inline-block rounded px-1 py-0.5 text-[9px] ${getCollectorStatusClass(collector.status)}`}>{getCollectorStatusLabel(collector.status, zh)}</span>}
                              </div>
                              <div className="space-y-1">
                                {collector.commands.length > 0 ? collector.commands.map((command, commandIndex) => (
                                  <div key={`${command.action_code}:${commandIndex}`}>
                                    <p className="mb-0.5 text-[9px] text-slate-500"><span className="font-semibold">action_code: </span><code className="break-all">{command.action_code || '—'}</code></p>
                                    {command.command ? (
                                      <code className="block overflow-x-auto rounded-md bg-slate-900 px-2 py-1.5 font-mono text-[10px] text-cyan-100">{command.command}</code>
                                    ) : (
                                      <p className="rounded-md bg-slate-100 px-2 py-1.5 text-[10px] font-semibold text-amber-700">
                                        {zh ? '此版本未解析到可下发命令' : 'No command resolved for this software release'}
                                      </p>
                                    )}
                                    {(command.command_source || command.textfsm_template) && (
                                      <p className="mt-0.5 text-[9px] text-slate-400">
                                        {command.command_source && <span>{zh ? `命令来源：${command.command_source}` : `Command source: ${command.command_source}`}</span>}
                                        {command.textfsm_template && <span className="ml-2">TextFSM: {command.textfsm_template}{command.textfsm_source ? ` · ${command.textfsm_source}` : ''}</span>}
                                      </p>
                                    )}
                                    {(command.condition || collector.conditional) && (
                                      <p className="mt-0.5 text-[9px] leading-relaxed text-amber-700">
                                        {command.condition || (zh ? '设备命令是否运行由运行时能力或发现结果决定。' : 'Execution depends on runtime capabilities or discovery results.')}
                                      </p>
                                    )}
                                    {command.status === 'unsupported' && collector.status !== 'unsupported' && collector.status !== 'parser_missing' && !command.condition && (
                                      <p className="mt-0.5 text-[9px] text-rose-700">
                                        {zh ? '当前软件版本无对应 action 或 TextFSM 命令模板。' : 'No matching action or TextFSM command template exists for this software release.'}
                                      </p>
                                    )}
                                  </div>
                                )) : (
                                  <p className="text-[10px] text-slate-400">
                                    {getNoCommandMessage(collector.status, collector.transport, zh)}
                                  </p>
                                )}
                                {collector.commands.length > 0 && collector.status && ['unsupported', 'parser_missing', 'partial', 'projection'].includes(collector.status.toLowerCase()) && (
                                  <p className={`mt-1 text-[9px] leading-relaxed ${collector.status === 'unsupported' ? 'text-rose-700' : 'text-amber-700'}`}>
                                    {getCollectorStatusDetail(collector.status, zh)}
                                  </p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>

                      {group.notes.length > 0 && (
                        <ul className="list-disc space-y-1 pl-4 text-[9px] leading-relaxed text-slate-500">
                          {group.notes.map((note, noteIndex) => <li key={`${noteIndex}:${note}`}>{note}</li>)}
                        </ul>
                      )}
                    </div>
                  </details>
                  );
                })}

                {nsotPreview && (
                  <p className="text-right text-[9px] text-slate-400">
                    {zh ? '预览生成时间：' : 'Preview generated: '}{new Date(nsotPreview.generated_at).toLocaleString(zh ? 'zh-CN' : 'en-US')}
                  </p>
                )}
              </section>
            )}

            <section className="rounded-2xl border border-cyan-100 bg-cyan-50/35 p-4" aria-label={zh ? '作业授权' : 'Job authorization'}>
              <div className="mb-3 flex items-start gap-2">
                <ShieldCheck size={15} className="mt-0.5 shrink-0 text-cyan-700" />
                <div>
                  <h4 className="text-xs font-bold text-slate-800">{zh ? '授权状态' : 'Authorization'}</h4>
                  <p className="mt-0.5 text-[10px] text-slate-500">{zh ? '每次运行均受此授权版本、有效期和额度约束。' : 'Each run is bound to this authorization version, expiry, and limits.'}</p>
                </div>
              </div>
              {jobDetailLoading && !authorizationGrant && <p role="status" className="text-xs text-slate-500">{zh ? '正在加载授权信息…' : 'Loading authorization…'}</p>}
              {jobDetailError && <div role="alert" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-800"><span>{jobDetailForbidden ? (zh ? '当前账号无权查看作业授权详情。' : 'You do not have permission to view job authorization details.') : jobDetailError}</span><button type="button" onClick={() => setJobDetailRetry(value => value + 1)} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button></div>}
              {!jobDetailLoading && !jobDetailError && !authorizationGrant && <p role="status" className="rounded-lg bg-white/80 px-3 py-2 text-xs text-slate-500">{zh ? '服务端未返回该作业的授权信息。' : 'No authorization details were returned for this job.'}</p>}
              {authorizationGrant && (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${grantStatusClass(authorizationGrant.status)}`}>{grantStatusText(authorizationGrant.status, zh)}</span>
                    <span className="text-[10px] font-semibold text-slate-500">{zh ? '授权版本' : 'Grant version'} {authorizationGrant.version ?? '—'} · {zh ? '内容版本' : 'Content'} {String(authorizationGrant.template_version || '—').slice(0, 12)}</span>
                  </div>
                  <dl className="grid gap-2 text-[11px] sm:grid-cols-2">
                    <div className="rounded-lg bg-white/85 px-3 py-2"><dt className="text-[10px] text-slate-500">{zh ? '有效期至' : 'Valid until'}</dt><dd className="mt-0.5 font-semibold text-slate-700">{formatRunTime(authorizationGrant.valid_until, zh)}</dd></div>
                    <div className="rounded-lg bg-white/85 px-3 py-2"><dt className="text-[10px] text-slate-500">{zh ? '执行次数' : 'Runs used'}</dt><dd className="mt-0.5 font-semibold text-slate-700">{authorizationGrant.used_runs ?? 0} / {authorizationGrant.max_runs} · {zh ? `剩余 ${authorizationGrant.remaining_runs ?? '—'} 次` : `${authorizationGrant.remaining_runs ?? '—'} remaining`}</dd></div>
                    <div className="rounded-lg bg-white/85 px-3 py-2"><dt className="text-[10px] text-slate-500">{zh ? '批准范围 / 目标上限' : 'Approved scope / target limit'}</dt><dd className="mt-0.5 break-words font-semibold text-slate-700">{describeScope(displayedJob.device_scope, displayedJob.device_filter, zh)} · {zh ? `最多 ${authorizationGrant.max_targets} 台` : `up to ${authorizationGrant.max_targets} targets`}</dd></div>
                    <div className="rounded-lg bg-white/85 px-3 py-2"><dt className="text-[10px] text-slate-500">{zh ? '授权摘要哈希' : 'Manifest hash'}</dt><dd className="mt-0.5 break-all font-mono text-[9px] text-slate-600">{authorizationGrant.manifest_hash || '—'}</dd></div>
                    <div className="rounded-lg bg-white/85 px-3 py-2"><dt className="text-[10px] text-slate-500">{zh ? '关联工单' : 'Linked ticket'}</dt><dd className="mt-0.5">{authorizationGrant.ticket_id ? <button type="button" onClick={() => openTicket(authorizationGrant.ticket_source_type, authorizationGrant.ticket_id)} className="inline-flex items-center gap-1 break-all text-left font-semibold text-cyan-800 hover:underline">{authorizationGrant.ticket_number || authorizationGrant.ticket_id}{authorizationGrant.ticket_title ? ` · ${authorizationGrant.ticket_title}` : ''}<ExternalLink size={10} className="shrink-0" /></button> : '—'}</dd></div>
                    <div className="rounded-lg bg-white/85 px-3 py-2"><dt className="text-[10px] text-slate-500">{zh ? '关联变更单' : 'Linked change order'}</dt><dd className="mt-0.5">{authorizationGrant.change_order_id ? <button type="button" onClick={() => openChangeOrder(authorizationGrant.change_order_id)} className="inline-flex items-center gap-1 break-all text-left font-semibold text-cyan-800 hover:underline">{authorizationGrant.change_order_number || authorizationGrant.change_order_id}<ExternalLink size={10} className="shrink-0" /></button> : (zh ? '未关联' : 'Not linked')}</dd></div>
                  </dl>
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-slate-200 bg-white p-4" aria-label={zh ? '周期作业运行记录' : 'Scheduled job runs'}>
              <div className="mb-3 flex items-start justify-between gap-3">
                <div className="flex items-start gap-2">
                  <Clock3 size={15} className="mt-0.5 shrink-0 text-cyan-700" />
                  <div><h4 className="text-xs font-bold text-slate-800">{zh ? '运行记录' : 'Run history'}</h4><p className="mt-0.5 text-[10px] text-slate-500">{zh ? `共 ${runsTotal} 次；未知结果需人工核实，不会在此重试。` : `${runsTotal} runs. Unknown outcomes require manual review; this view does not retry jobs.`}</p></div>
                </div>
              </div>
              {runsLoading && <p role="status" className="flex items-center gap-2 py-4 text-xs text-slate-500"><LoaderCircle size={14} className="animate-spin" />{zh ? '正在加载运行记录…' : 'Loading run history…'}</p>}
              {!runsLoading && runsError && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-800"><span>{runsForbidden ? (zh ? '当前账号无权查看运行记录。' : 'You do not have permission to view run history.') : runsError}</span><button type="button" onClick={() => setRunsRetry(value => value + 1)} className="font-semibold underline">{zh ? '重试' : 'Retry'}</button></div>}
              {!runsLoading && !runsError && runs.length === 0 && <p role="status" className="rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500">{zh ? '该作业暂无运行记录。' : 'No runs have been recorded for this job.'}</p>}
              {!runsLoading && !runsError && runs.length > 0 && <ol className="space-y-2">
                {runs.map(run => {
                  const canResolve = run.allowed_actions?.includes('resolve') === true;
                  const unknown = canResolve || run.status === 'unknown';
                  return <li key={run.run_id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0"><p className="break-all font-mono text-[10px] font-semibold text-slate-700">{run.run_id}</p><p className={`mt-1 inline-flex items-center gap-1 text-[10px] font-bold ${unknown ? 'text-amber-800' : run.status === 'succeeded' ? 'text-emerald-700' : ['failed', 'partial_failure'].includes(run.status) ? 'text-rose-700' : 'text-slate-600'}`}>{unknown ? <CircleAlert size={11} /> : run.status === 'succeeded' ? <CheckCircle2 size={11} /> : null}{runStatusText(run, zh)}</p></div>
                      {run.authorization_version != null && <span className="rounded bg-white px-2 py-1 text-[9px] text-slate-500">{zh ? '授权版本' : 'Grant'} {run.authorization_version}</span>}
                    </div>
                    <dl className="mt-2 grid gap-x-4 gap-y-1 text-[10px] sm:grid-cols-2">
                      <div><dt className="inline text-slate-500">{zh ? '计划：' : 'Scheduled: '}</dt><dd className="inline text-slate-700">{formatRunTime(run.scheduled_for, zh)}</dd></div>
                      <div><dt className="inline text-slate-500">{zh ? '开始 / 结束：' : 'Started / finished: '}</dt><dd className="inline text-slate-700">{formatRunTime(run.started_at, zh)} / {formatRunTime(run.finished_at, zh)}</dd></div>
                      <div><dt className="inline text-slate-500">{zh ? '目标 / 成功 / 失败：' : 'Targets / success / failure: '}</dt><dd className="inline text-slate-700">{run.target_count ?? '—'} / {run.success_count ?? '—'} / {run.failure_count ?? '—'}</dd></div>
                      <div className="flex flex-wrap gap-x-2"><dt className="text-slate-500">{zh ? '关联：' : 'Linked: '}</dt><dd className="flex flex-wrap gap-x-2">{run.ticket_id ? <button type="button" onClick={() => openTicket(run.ticket_source_type, run.ticket_id)} className="font-semibold text-cyan-800 hover:underline">{run.ticket_number || run.ticket_id}</button> : null}{run.change_order_id ? <button type="button" onClick={() => openChangeOrder(run.change_order_id)} className="font-semibold text-cyan-800 hover:underline">{run.change_order_number || run.change_order_id}</button> : null}{!run.ticket_id && !run.change_order_id ? <span className="text-slate-700">—</span> : null}</dd></div>
                    </dl>
                    {run.summary && <p className="mt-2 whitespace-pre-wrap break-words text-[10px] text-slate-700">{run.summary}</p>}
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
            </section>

            {/* 4. Meta Info */}
            <div className="pt-4 border-t border-black/[0.03] grid grid-cols-2 gap-y-4 text-[10px]">
              <div>
                <p className="text-black/30 mb-1">{zh ? '状态' : 'Status'}</p>
                <span className={`px-2 py-0.5 rounded-full font-bold ${detailJob.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500'}`}>
                  {detailJob.enabled ? (zh ? '已启用' : 'Active') : (zh ? '已停用' : 'Disabled')}
                </span>
              </div>
              <div>
                <p className="text-black/30 mb-1">{zh ? '配置原因' : 'Reason'}</p>
                <p className="text-slate-600 font-medium italic truncate">{detailJob.config_reason || '\u2014'}</p>
              </div>
              <div>
                <p className="text-black/30 mb-1">{zh ? '审批人' : 'Approver'}</p>
                <p className="text-slate-600 font-bold">{detailJob.approved_by || (zh ? '系统自核' : 'Auto')}</p>
              </div>
              <div>
                <p className="text-black/30 mb-1">{zh ? '创建者' : 'Creator'}</p>
                <p className="text-slate-600 font-bold">{detailJob.created_by} · {new Date(detailJob.created_at).toLocaleDateString()}</p>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 bg-slate-50/80 border-t border-black/[0.03] flex items-center justify-end gap-3">
            <button
              onClick={onClose}
              className="px-6 py-2 rounded-xl border border-black/10 text-xs font-bold text-black/50 hover:bg-black/5 transition-all"
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
                className="px-6 py-2 rounded-xl bg-[#164e63] text-white text-xs font-bold shadow-lg shadow-cyan-900/10 hover:bg-[#0891b2] transition-all"
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
