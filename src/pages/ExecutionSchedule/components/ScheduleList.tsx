import React from 'react';
import { motion } from 'motion/react';
import {
  CalendarClock, Trash2, Activity, Target, FileCode,
  RotateCcw, ShieldAlert, User, Database,
} from 'lucide-react';
import Pagination from '../../../components/Pagination';
import type { ScheduledJob } from '../types';
import { ACTION_TYPES } from '../constants';
import { fmtDateTime, getScheduleStatus, describeScope } from '../helpers';

interface ScheduleListProps {
  zh: boolean;
  language: string;
  schedules: ScheduledJob[];
  loading: boolean;
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (p: number) => void;
  onPageSizeChange: (s: number) => void;
  onSelect: (sch: ScheduledJob) => void;
  onToggleEnabled: (sch: ScheduledJob) => void;
  onDelete: (id: string) => void;
  availableScripts: { id: string; name: string }[];
}

const ScheduleList: React.FC<ScheduleListProps> = ({
  zh, language, schedules, loading, total, page, pageSize,
  onPageChange, onPageSizeChange, onSelect, onToggleEnabled, onDelete,
  availableScripts,
}) => {
  return (
    <div className="rounded-2xl border border-black/5 bg-white shadow-sm overflow-hidden min-h-[500px] flex flex-col">
      {/* Table Header / Toolbar */}
      <div className="px-6 py-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-cyan-50 flex items-center justify-center">
            <CalendarClock size={16} className="text-cyan-600" />
          </div>
          <h3 className="text-sm font-bold text-[#164e63]">{zh ? '当前计划列表' : 'Active Schedules'}</h3>
        </div>
        <div className="text-[11px] font-bold text-black/25 uppercase tracking-widest tabular-nums">
          {total} {zh ? '个项目' : 'Items'}
        </div>
      </div>

      {/* List Body */}
      <div className="flex-1 overflow-y-auto max-h-[calc(100vh-420px)] custom-scrollbar">
        {loading ? (
          <div className="h-full flex flex-col items-center justify-center py-24 text-black/20 gap-3">
            <RotateCcw size={32} className="animate-spin opacity-20" />
            <span className="text-sm font-medium">{zh ? '正在加载数据...' : 'Loading schedules...'}</span>
          </div>
        ) : schedules.length > 0 ? (
          <div className="space-y-2.5 p-4">
            {schedules.map(sch => {
              const atInfo = ACTION_TYPES.find(a => a.value === sch.action_type);
              const AtIcon = atInfo?.icon || Database;
              const isEnabled = !!sch.enabled;
              const scopeDesc = describeScope(sch.device_scope, sch.device_filter, zh);
              const isInsp = sch.action_type === 'inspection';
              const isBackup = sch.action_type === 'backup';
              const isScript = sch.action_type === 'script_run';
              const st = getScheduleStatus(sch, zh);
              
              return (
                <motion.div
                  key={`${sch.job_id || sch.id}-${sch.run_at || sch.scheduled_at}`}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  onClick={() => onSelect(sch)}
                  className={`rounded-2xl border transition-all hover:shadow-md cursor-pointer group overflow-hidden ${
                    isEnabled ? 'bg-white border-slate-200/90 shadow-sm' : 'bg-slate-50 border-slate-200/50 opacity-60'
                  }`}
                >
                  <div className="flex items-center gap-4 px-5 py-4">
                    {/* Category Icon */}
                    <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 border ${
                      isEnabled
                        ? isInsp ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                          : isBackup ? 'bg-indigo-50 text-indigo-600 border-indigo-100'
                          : isScript ? 'bg-amber-50 text-amber-600 border-amber-100'
                          : 'bg-cyan-50 text-cyan-600 border-cyan-100'
                        : 'bg-slate-100 text-slate-400 border-slate-200'
                    }`}>
                      <AtIcon size={20} />
                    </div>

                    {/* Main info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2.5">
                        <p className="text-sm font-bold text-[#0f172a] truncate group-hover:text-cyan-700 transition-colors">
                          {sch.name}
                        </p>
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                          st.icon === 'ready' || st.icon === 'pending' ? 'bg-cyan-100/80 text-cyan-700 border border-cyan-200' :
                          st.icon === 'done' ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' :
                          'bg-slate-100 text-slate-500 border border-slate-200'
                        }`}>
                          {st.label}
                        </span>
                        {sch.last_run_status && (
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                            sch.last_run_status === 'success'
                              ? 'bg-emerald-50 text-emerald-600 border border-emerald-100'
                              : 'bg-rose-50 text-rose-600 border border-rose-100'
                          }`}>
                            <div className={`w-1.5 h-1.5 rounded-full ${sch.last_run_status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                            {sch.last_run_status === 'success' ? (zh ? '执行成功' : 'Success') : (zh ? '执行失败' : 'Failed')}
                          </span>
                        )}
                        {sch.use_admin_creds ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-50 text-amber-700 border border-amber-200 shadow-sm">
                            <ShieldAlert size={12} className="text-amber-600" />
                            {zh ? '特权执行 (Admin)' : 'Privileged'}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-100 text-slate-600 border border-slate-200 shadow-sm">
                            <User size={12} className="text-slate-500" />
                            {zh ? '普通执行 (User)' : 'Normal'}
                          </span>
                        )}
                      </div>

                      <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500 flex-wrap">
                        <span className="flex items-center gap-1 font-mono font-semibold text-slate-700 bg-slate-100 px-2 py-0.5 rounded">
                          <CalendarClock size={12} className="text-cyan-600" />
                          {fmtDateTime(sch.run_at || sch.scheduled_at, zh)}
                        </span>
                        <span className="text-slate-300">·</span>
                        <span className={`font-semibold ${isInsp ? 'text-emerald-700' : isBackup ? 'select-none text-indigo-700' : isScript ? 'text-amber-700' : 'text-slate-700'}`}>
                          {zh ? (atInfo?.labelZh || sch.action_type) : (atInfo?.labelEn || sch.action_type)}
                        </span>
                        <span className="text-slate-300">·</span>
                        <span className="flex items-center gap-1 text-slate-600 font-medium">
                          <Target size={12} className="text-slate-400" />
                          {scopeDesc}
                        </span>

                        {sch.action_type === 'script_run' && sch.script_id && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span className="flex items-center gap-1 text-[#00a9ce] font-bold bg-cyan-50 px-2 py-0.5 rounded border border-cyan-100">
                              <FileCode size={12} />
                              {(availableScripts || []).find(s => s.id === sch.script_id)?.name || sch.script_id}
                            </span>
                          </>
                        )}
                        {sch.last_run_at && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span>{zh ? '最近运行' : 'Last run'}: <span className="font-mono">{new Date(sch.last_run_at).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span></span>
                          </>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => onToggleEnabled(sch)}
                        className={`p-2 rounded-xl transition-all ${isEnabled ? 'text-slate-400 hover:bg-amber-50 hover:text-amber-600' : 'text-slate-400 hover:bg-emerald-50 hover:text-emerald-600'}`}
                        title={isEnabled ? (zh ? '停用' : 'Disable') : (zh ? '启用' : 'Enable')}
                      >
                        <Activity size={16} />
                      </button>
                      <button
                        onClick={() => onDelete(sch.job_id || sch.id)}
                        className="p-2 rounded-xl text-slate-400 hover:bg-rose-50 hover:text-rose-600 transition-all"
                        title={zh ? '删除' : 'Delete'}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>

                  {/* Bottom meta */}
                  <div className="px-5 py-2.5 bg-slate-50/80 border-t border-slate-100 flex items-center gap-4 text-[11px] text-slate-500">
                    {sch.description && (
                      <>
                        <span className="text-slate-600 italic truncate max-w-[200px]">{sch.description}</span>
                        <span className="text-slate-300">|</span>
                      </>
                    )}
                    <span>{zh ? '审批授权人' : 'Approver'}: <span className="font-bold text-slate-700">{sch.approved_by || '\u2014'}</span></span>
                    <span className="text-slate-300">|</span>
                    <span>{zh ? '创建者' : 'Creator'}: <span className="font-medium text-slate-700">{sch.created_by}</span> · <span className="font-mono">{new Date(sch.created_at).toLocaleDateString(zh ? 'zh-CN' : 'en-US')}</span></span>
                  </div>
                </motion.div>
              );
            })}
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center py-32 text-black/20 gap-3">
            <CalendarClock size={48} strokeWidth={1} className="opacity-10" />
            <div className="text-center">
              <p className="text-sm font-bold text-black/30">{zh ? '暂无任何执行计划' : 'No schedules found'}</p>
              <p className="text-[11px] mt-1">{zh ? '点击右上角「新建计划」开始自动化巡检' : 'Click "Add Schedule" to start automation'}</p>
            </div>
          </div>
        )}
      </div>

      {/* Pagination Section */}
      {total > 0 && (
        <div className="mt-auto">
          <Pagination
            currentPage={page}
            totalItems={total}
            itemsPerPage={pageSize}
            onPageChange={onPageChange}
            onItemsPerPageChange={onPageSizeChange}
            language={language}
          />
        </div>
      )}
    </div>
  );
};

export default ScheduleList;
