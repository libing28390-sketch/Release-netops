import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { CalendarClock, X, Trash2, Activity, CheckCircle2, RotateCcw } from 'lucide-react';
import type { ScheduledJob } from '../types';
import { fmtDateTime } from '../helpers';

interface ScheduleDetailProps {
  zh: boolean;
  open: boolean;
  schedule: ScheduledJob | null;
  onClose: () => void;
  onToggleEnabled: (sch: ScheduledJob) => void;
  onDelete: (id: string) => void;
  onScheduleUpdate: (sch: ScheduledJob) => void;
}

const ScheduleDetail: React.FC<ScheduleDetailProps> = ({
  zh, open, schedule, onClose, onToggleEnabled, onDelete, onScheduleUpdate,
}) => {
  if (!schedule) return null;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 lg:p-8">
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-[#00172D]/60 backdrop-blur-md"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 30 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 30 }}
            className="relative w-full max-w-3xl bg-white rounded-[2.5rem] shadow-2xl shadow-black/40 overflow-hidden flex flex-col max-h-[90vh]"
          >
            {/* Modal Header */}
            <div className="px-8 py-6 border-b border-black/5 flex items-center justify-between bg-[linear-gradient(to_bottom,#fcfdfd_0%,#ffffff_100%)]">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-cyan-50 flex items-center justify-center text-cyan-600 shadow-sm border border-cyan-100">
                  <CalendarClock size={24} />
                </div>
                <div>
                  <h3 className="text-xl font-bold text-[#164e63]">{schedule.name}</h3>
                  <p className="text-xs text-black/30 font-medium tracking-tight mt-0.5">ID: {schedule.id}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-3 rounded-2xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all active:scale-90"
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto px-8 py-8 custom-scrollbar">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                {/* Info Blocks */}
                <div className="space-y-8">
                  <section>
                    <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '基本信息' : 'Basic Info'}</label>
                    <div className="space-y-5">
                      <div>
                        <p className="text-[11px] font-bold text-black/30 mb-1">{zh ? '描述' : 'Description'}</p>
                        <p className="text-sm text-[#164e63] font-medium leading-relaxed">
                          {schedule.description || (zh ? '未填写描述' : 'No description provided')}
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-[11px] font-bold text-black/30 mb-1">{zh ? '创建者' : 'Author'}</p>
                          <p className="text-sm text-[#164e63] font-black">{schedule.created_by || '—'}</p>
                        </div>
                        <div>
                          <p className="text-[11px] font-bold text-black/30 mb-1">{zh ? '创建时间' : 'Created At'}</p>
                          <p className="text-sm text-[#164e63] font-black font-mono">{new Date(schedule.created_at).toLocaleDateString()}</p>
                        </div>
                      </div>
                    </div>
                  </section>

                  <section>
                    <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '执行配置' : 'Execution Config'}</label>
                    <div className="rounded-3xl bg-slate-50 border border-black/5 p-6 space-y-5 shadow-inner">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-black/40">{zh ? '范围类型' : 'Scope Type'}</span>
                        <span className="text-xs font-black text-[#164e63] uppercase tracking-wide bg-white px-3 py-1 rounded-full shadow-sm">{schedule.device_scope}</span>
                      </div>
                      {schedule.device_filter && (
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-black/40">{zh ? '过滤条件' : 'Filter'}</span>
                          <span className="text-xs font-black text-[#164e63] max-w-[150px] truncate">{schedule.device_filter}</span>
                        </div>
                      )}
                      <div className="pt-2 border-t border-black/5">
                        <span className="text-[11px] font-bold text-black/30 block mb-2">{zh ? '执行时间' : 'Execution Time'}</span>
                        <div className="flex items-center gap-3">
                          <div className="flex-1 text-[11px] font-mono text-cyan-600 bg-cyan-50 px-3 py-2 rounded-xl border border-cyan-100 text-center">
                            {fmtDateTime(schedule.scheduled_at, zh)}
                          </div>
                        </div>
                      </div>
                    </div>
                  </section>
                </div>

                {/* Metrics Block */}
                <div className="space-y-8">
                  <section>
                    <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '关联指标项' : 'Linked Metrics'}</label>
                    <div className="flex flex-wrap gap-2">
                      {Array.isArray(schedule.check_items) && schedule.check_items.length > 0 ? (
                        schedule.check_items.map(item => (
                          <div key={item} className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-cyan-500/[0.06] border border-cyan-500/10 transition-all hover:bg-cyan-500/10 cursor-default">
                            <CheckCircle2 size={12} className="text-cyan-500" />
                            <span className="text-xs font-bold text-cyan-800">{item}</span>
                          </div>
                        ))
                      ) : (
                        <span className="text-xs text-black/20 italic">{zh ? '未关联任何指标' : 'No metrics linked'}</span>
                      )}
                    </div>
                  </section>

                  <section>
                    <label className="text-[10px] font-black text-black/20 uppercase tracking-[0.2em] block mb-3">{zh ? '状态与记录' : 'Status & Stats'}</label>
                    <div className="grid grid-cols-1 gap-4">
                      <div className="flex items-center justify-between p-5 rounded-[2rem] bg-gradient-to-br from-white to-slate-50 border border-black/5 shadow-sm group">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 rounded-2xl flex items-center justify-center transition-all group-hover:scale-110 ${schedule.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-50 text-slate-400'}`}>
                            <Activity size={20} />
                          </div>
                          <div>
                            <p className="text-[11px] font-bold text-black/30 uppercase tracking-widest">{zh ? '当前状态' : 'Current Status'}</p>
                            <p className={`text-sm font-black ${schedule.enabled ? 'text-emerald-600' : 'text-slate-400'}`}>
                              {schedule.enabled ? (zh ? '运行中' : 'Active') : (zh ? '已停用' : 'Disabled')}
                            </p>
                          </div>
                        </div>
                        <button
                          onClick={() => { onToggleEnabled(schedule); onScheduleUpdate({ ...schedule, enabled: schedule.enabled ? 0 : 1 } as ScheduledJob); }}
                          className={`px-4 py-1.5 rounded-full text-[10px] font-black uppercase transition-all shadow-sm ${schedule.enabled ? 'bg-white text-emerald-600 hover:bg-emerald-50 border border-emerald-100' : 'bg-emerald-600 text-white hover:bg-emerald-700'}`}
                        >
                          {schedule.enabled ? (zh ? '停用' : 'Disable') : (zh ? '启动' : 'Enable')}
                        </button>
                      </div>

                      <div className="p-5 rounded-[2rem] bg-slate-50 border border-black/5 shadow-inner">
                        <div className="flex items-center gap-3 mb-2">
                          <RotateCcw size={14} className="text-black/20" />
                          <span className="text-[11px] font-bold text-black/30 uppercase tracking-widest">{zh ? '最近一次执行' : 'Last Execution'}</span>
                        </div>
                        <p className="text-sm font-black text-[#164e63] font-mono">
                          {schedule.last_run_at ? fmtDateTime(schedule.last_run_at, zh) : (zh ? '暂无执行记录' : 'Never executed')}
                        </p>
                      </div>
                    </div>
                  </section>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-8 py-6 border-t border-black/5 bg-slate-50/30 flex items-center justify-between">
              <button
                onClick={() => {
                  if (confirm(zh ? '确定删除该执行计划？' : 'Are you sure you want to delete this schedule?')) {
                    onDelete(schedule.id);
                    onClose();
                  }
                }}
                className="flex items-center gap-2 px-6 py-2.5 rounded-2xl text-red-500 hover:bg-red-50 text-xs font-black transition-all"
              >
                <Trash2 size={16} />
                {zh ? '删除计划' : 'Delete Plan'}
              </button>
              <button
                onClick={onClose}
                className="px-8 py-2.5 rounded-2xl bg-[#164e63] text-white text-xs font-black hover:bg-[#155e75] transition-all shadow-lg shadow-cyan-900/20 active:scale-95"
              >
                {zh ? '完成并关闭' : 'Done & Close'}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

export default ScheduleDetail;
