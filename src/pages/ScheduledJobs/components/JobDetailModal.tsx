import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Info, X, CalendarClock, Target, FileText, FileCode } from 'lucide-react';
import { ScheduledJob } from '../types';
import { describeCron } from '../helpers';

interface JobDetailModalProps {
  isOpen: boolean;
  onClose: () => void;
  detailJob: ScheduledJob | null;
  viewingScript: any;
  fetchAndShowScriptDetail: (scriptId: string) => Promise<void>;
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string }>;
  openEditModal: (job: ScheduledJob) => void;
  language: string;
}

export const JobDetailModal: React.FC<JobDetailModalProps> = ({
  isOpen,
  onClose,
  detailJob,
  viewingScript,
  fetchAndShowScriptDetail,
  availableScripts,
  openEditModal,
  language,
}) => {
  const zh = language === 'zh';

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
                    {(detailJob.action_type === 'backup' || detailJob.action_type === 'inspection') ? (zh ? '采集' : 'COLLECTION') : 
                     (detailJob.action_type === 'script_run' && availableScripts.find(s => s.id === detailJob.script_id)?.category === 'inspection') ? (zh ? '采集' : 'COLLECTION') :
                     (zh ? '变更' : 'CHANGE')}
                  </div>
                </div>
                <div className="p-4 overflow-x-auto">
                  <pre className="font-mono text-[11px] leading-relaxed text-cyan-50/90 whitespace-pre-wrap">
                    {detailJob.action_type === 'backup'
                      ? (zh ? '# 该作业为内置配置备份任务\n# 将自动采集设备 running-config 并进行版本比对' : '# This is a built-in config backup job.\n# It will collect running-config and track drifts.')
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
