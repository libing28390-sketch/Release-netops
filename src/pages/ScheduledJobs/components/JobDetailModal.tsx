import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Info, X, CalendarClock, Target, FileText, FileCode } from 'lucide-react';
import { NsotCollectionPreview, ScheduledJob } from '../types';
import { describeCron } from '../helpers';
import { useEscapeClose } from '../../../hooks/useEscapeClose';

interface JobDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  detailJob: ScheduledJob | null;
  viewingScript: any;
  fetchAndShowScriptDetail: (scriptId: string) => Promise<void>;
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string }>;
  openEditModal: (job: ScheduledJob) => void;
  fetchNsotCollectionPreview: (jobId: string, signal: AbortSignal) => Promise<NsotCollectionPreview>;
  language: string;
}

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
  viewingScript,
  fetchAndShowScriptDetail,
  availableScripts,
  openEditModal,
  fetchNsotCollectionPreview,
  language,
}) => {
  useEscapeClose(isOpen, onClose);
  const zh = language === 'zh';
  const [nsotPreview, setNsotPreview] = useState<NsotCollectionPreview | null>(null);
  const [nsotPreviewLoading, setNsotPreviewLoading] = useState(false);
  const [nsotPreviewError, setNsotPreviewError] = useState('');
  const [nsotPreviewRetry, setNsotPreviewRetry] = useState(0);

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

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      >
        <div className="fixed inset-0 bg-black/40 backdrop-blur-md" onClick={onClose} />
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

            {/* 3. Execution Content (Script/Commands) */}
            <div>
              <h4 className="text-[11px] font-bold text-black/50 uppercase tracking-wider mb-2">{zh ? '执行脚本/内容' : 'Execution Content'}</h4>
              <div className="rounded-2xl border border-black/[0.06] overflow-hidden bg-[#1e293b]">
                <div className="px-4 py-2 bg-white/5 border-b border-white/[0.05] flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileText size={12} className="text-cyan-400" />
                    <span className="text-[11px] font-bold text-white/70">
                      {detailJob.action_type === 'backup' ? (zh ? '采集与巡检：核心配置备份' : 'Collection & Inspection: Config Backup') :
                       detailJob.action_type === 'nsot' ? (zh ? '网络事实库：完整 NSOT 采集' : 'Network Facts: Full NSOT Collection') :
                       detailJob.action_type === 'inspection' && !detailJob.script_id ? (zh ? '智能巡检（全部内置指标）' : 'Smart Inspection (All Built-in)') :
                       (availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id || (zh ? '操作内容' : 'Operation Content'))}
                    </span>
                    {detailJob.script_id && (
                      <button 
                        onClick={() => fetchAndShowScriptDetail(detailJob.script_id!)}
                        className="text-[9px] bg-cyan-500/10 text-cyan-400 px-1.5 py-0.5 rounded border border-cyan-500/20 hover:bg-cyan-500/20 transition-all ml-1"
                      >
                        {zh ? '查看脚本详情' : 'View Script'}
                      </button>
                    )}
                  </div>
                  <div className="text-[9px] font-bold text-cyan-400/60 uppercase tracking-widest">
                    {(detailJob.action_type === 'backup' || detailJob.action_type === 'nsot' || detailJob.action_type === 'inspection') ? (zh ? '采集' : 'COLLECTION') :
                     (detailJob.action_type === 'script_run' && availableScripts.find(s => s.id === detailJob.script_id)?.category === 'inspection') ? (zh ? '采集' : 'COLLECTION') :
                     (zh ? '变更' : 'CHANGE')}
                  </div>
                </div>
                <div className="p-4 overflow-x-auto">
                  <pre className="font-mono text-[11px] leading-relaxed text-cyan-50/90 whitespace-pre-wrap">
                    {detailJob.action_type === 'backup'
                      ? (zh ? '# 该作业为内置配置备份任务\n# 将自动采集设备 running-config 并进行版本比对' : '# This is a built-in config backup job.\n# It will collect running-config and track drifts.')
                      : detailJob.action_type === 'nsot'
                        ? (zh ? '# 该作业为 NSOT 网络事实库采集\n# 按当前设备范围筛选在线目标，并遵循各设备的 NSOT 采集模板\n# 不执行用户命令或配置变更' : '# NSOT facts collection job.\n# Runs for online devices in the saved scope and follows each device collection template.\n# No user commands or configuration changes are executed.')
                      : detailJob.action_type === 'inspection'
                        ? (detailJob.script_id && viewingScript?.id === detailJob.script_id && viewingScript?.content
                           ? viewingScript.content
                           : detailJob.script_id
                             ? (zh ? `# 该作业为智能巡检（绑定脚本: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}）\n# 点击上方"查看脚本详情"查看完整内容` : `# Smart Inspection job bound to script: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}\n# Click "View Script" above to see full content`)
                             : (zh ? '# 该作业为内置综合巡检\n# 将采集 interfaces / neighbors / arp / mac_table / routing_table / bgp / ospf' : '# Built-in comprehensive inspection job.\n# Collects interfaces / neighbors / arp / mac_table / routing_table / bgp / ospf'))
                        : detailJob.script_id && viewingScript?.id === detailJob.script_id && viewingScript?.content
                          ? viewingScript.content
                          : detailJob.commands
                            ? detailJob.commands
                            : detailJob.script_id
                              ? (zh ? `# 此作业绑定脚本: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}\n# 点击上方"查看脚本详情"查看完整内容` : `# Bound script: ${availableScripts.find(s => s.id === detailJob.script_id)?.name || detailJob.script_id}\n# Click "View Script" above to see full content`)
                              : (zh ? '-- 未设置具体执行内容 --' : '-- No commands defined --')}
                  </pre>
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
            <button
              onClick={() => {
                onClose();
                openEditModal(detailJob);
              }}
              className="px-6 py-2 rounded-xl bg-[#164e63] text-white text-xs font-bold shadow-lg shadow-cyan-900/10 hover:bg-[#0891b2] transition-all"
            >
              {zh ? '编辑该作业' : 'Edit Job'}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
