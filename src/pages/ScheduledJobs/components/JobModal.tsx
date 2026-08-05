import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, X, Zap, ChevronDown, Info, Search, FileCode, CheckCircle2,
  Trash2, RotateCcw, User, ShieldAlert, Shield, AlertTriangle, Database, Activity
} from 'lucide-react';
import TagConditionPicker, { hasTagFilterConditions, type TagFilterConfig } from '../../../components/TagConditionPicker';
import { ScheduledJob, EligibleApprover, FormState, ValidatedDevice } from '../types';
import {
  CRON_PRESETS, CRON_FIELD_LABELS_ZH, CRON_FIELD_LABELS_EN,
  CRON_FIELD_HINTS_ZH, CRON_FIELD_HINTS_EN, ACTION_TYPES,
  MAJOR_CATEGORIES, SCOPE_OPTIONS
} from '../constants';
import { describeCron } from '../helpers';

interface JobModalProps {
  isOpen: boolean;
  onClose: () => void;
  isEditMode: boolean;
  enablingJobId: string | null;
  editingJob: ScheduledJob | null;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  tagFilter: TagFilterConfig;
  setTagFilter: React.Dispatch<React.SetStateAction<TagFilterConfig>>;
  ipInput: string;
  setIpInput: (val: string) => void;
  ipValidating: boolean;
  ipError: string;
  setIpError: (val: string) => void;
  ipDevices: ValidatedDevice[];
  removeIpDevice: (ip: string) => void;
  validateAndAddIps: (raw: string) => void;
  presetOpen: boolean;
  setPresetOpen: (val: boolean) => void;
  scriptSearch: string;
  setScriptSearch: (val: string) => void;
  showScriptDropdown: boolean;
  setShowScriptDropdown: (val: boolean) => void;
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string }>;
  fetchScripts: () => void;
  approverUsername: string;
  setApproverUsername: (val: string) => void;
  approvers: EligibleApprover[];
  approvalStatus: 'idle' | 'sending' | 'sent' | 'verified';
  approvalCountdown: number;
  approvalCode: string;
  setApprovalCode: (val: string) => void;
  approvalError: string;
  setApprovalError: (val: string) => void;
  requestApproval: () => void;
  verifyApproval: () => void;
  submitForm: () => void;
  language: string;
}

export const JobModal: React.FC<JobModalProps> = ({
  isOpen,
  onClose,
  isEditMode,
  enablingJobId,
  editingJob,
  form,
  setForm,
  tagFilter,
  setTagFilter,
  ipInput,
  setIpInput,
  ipValidating,
  ipError,
  setIpError,
  ipDevices,
  removeIpDevice,
  validateAndAddIps,
  presetOpen,
  setPresetOpen,
  scriptSearch,
  setScriptSearch,
  showScriptDropdown,
  setShowScriptDropdown,
  availableScripts,
  fetchScripts,
  approverUsername,
  setApproverUsername,
  approvers,
  approvalStatus,
  approvalCountdown,
  approvalCode,
  setApprovalCode,
  approvalError,
  setApprovalError,
  requestApproval,
  verifyApproval,
  submitForm,
  language,
}) => {
  const zh = language === 'zh';

  const [inspSource, setInspSource] = React.useState<'default' | 'script' | 'custom'>('default');

  React.useEffect(() => {
    if (isOpen && form.action_type === 'inspection') {
      if (form.script_id) {
        setInspSource('script');
        const current = (availableScripts || []).find(s => s.id === form.script_id);
        if (current) setScriptSearch(current.name);
      } else if (form.commands) {
        setInspSource('custom');
      } else {
        setInspSource('default');
      }
    }
  }, [isOpen, form.action_type, form.script_id, form.commands, availableScripts, setScriptSearch]);

  if (!isOpen) return null;

  // 与 index.tsx 中 validateForm 保持一致的就绪判断,用于禁用确认按钮(轻量版,不弹 toast)
  const isFormReady = (() => {
    if (!form.name.trim()) return false;
    if (!form.action_type) return false;
    const cronParts = form.cron_expr.trim().split(/\s+/);
    if (cronParts.length !== 5 || cronParts.some(p => !p)) return false;
    if (!form.device_scope) return false;
    if (form.device_scope === 'ip' && ipDevices.length === 0) return false;
    if (form.device_scope === 'tag') {
      if (!hasTagFilterConditions(tagFilter)) return false;
    }
    if ((form.device_scope === 'site' || form.device_scope === 'role') && !form.device_filter.trim()) return false;
    if (form.action_type === 'script_run' && !form.script_id) return false;
    if (form.action_type === 'inspection' && inspSource === 'script' && !form.script_id) return false;
    if (form.action_type === 'inspection' && inspSource === 'custom' && !form.commands.trim()) return false;
    return true;
  })();

  const cronParts = form.cron_expr.split(/\s+/);
  const cronFields = [
    cronParts[0] ?? '0',
    cronParts[1] ?? '*',
    cronParts[2] ?? '*',
    cronParts[3] ?? '*',
    cronParts[4] ?? '*'
  ];

  const updateCronField = (index: number, value: string) => {
    const p = [...cronFields];
    p[index] = value || '*';
    setForm(f => ({ ...f, cron_expr: p.join(' ') }));
  };

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key="add-form"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        className="rounded-2xl border border-cyan-200/60 bg-white p-6 space-y-6 shadow-xl relative overflow-hidden"
      >
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-cyan-400 to-blue-500" />
        <div className="flex items-center justify-between border-b border-black/5 pb-4">
          <h3 className="text-lg font-bold text-[#164e63] flex items-center gap-2">
            <CalendarClock className="text-cyan-500" size={20} />
            {enablingJobId === editingJob?.id
              ? (zh ? '安全启用授权验证' : 'Enable Scheduled Job (Auth Required)')
              : isEditMode
                ? (zh ? '编辑定时作业' : 'Edit Scheduled Job')
                : (zh ? '配置新的定时作业' : 'Configure New Scheduled Job')}
          </h3>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Left column */}
            <div className="space-y-4">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                  {zh ? '作业名称' : 'Name'} <span className="text-red-500 normal-case">*</span>
                </label>
                <input
                  type="text"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                  placeholder={zh ? '每日配置备份' : 'Daily config backup'}
                />
              </div>

              <div>
                <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                  {zh ? '作业类型' : 'Job Type'} <span className="text-red-500 normal-case">*</span>
                </label>
                <div className="p-1 bg-slate-100 rounded-xl border border-black/[0.06] flex gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'backup', major_type: 'collection', script_id: '' }));
                    }}
                    className={`flex-1 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'backup'
                        ? 'bg-white shadow-sm text-cyan-700 border border-cyan-100/30'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Database className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '核心配置备份' : 'Config Backup'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'inspection', major_type: 'collection' }));
                    }}
                    className={`flex-1 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'inspection'
                        ? 'bg-white shadow-sm text-cyan-700 border border-cyan-100/30'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Activity className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '智能巡检' : 'Smart Inspection'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'script_run', major_type: 'collection' }));
                      fetchScripts();
                    }}
                    className={`flex-1 py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'script_run'
                        ? 'bg-white shadow-sm text-cyan-700 border border-cyan-100/30'
                        : 'text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <FileCode className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '脚本巡检' : 'Script Inspection'}
                  </button>
                </div>
              </div>

              {form.action_type === 'inspection' && (
                <div className="space-y-3">
                  <div>
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '智能巡检配置来源' : 'Inspection Source'}</label>
                    <div className="p-1 bg-slate-100 rounded-xl border border-black/[0.06] flex gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('default');
                          setForm(f => ({ ...f, script_id: '', commands: '' }));
                        }}
                        className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${
                          inspSource === 'default'
                            ? 'bg-white shadow-sm text-cyan-700 border border-cyan-100/30'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '全量默认指标' : 'Built-in Defaults'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('script');
                          setForm(f => ({ ...f, commands: '' }));
                        }}
                        className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${
                          inspSource === 'script'
                            ? 'bg-white shadow-sm text-cyan-700 border border-cyan-100/30'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '关联巡检脚本' : 'Bound Script'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('custom');
                          setForm(f => ({ ...f, script_id: '' }));
                        }}
                        className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${
                          inspSource === 'custom'
                            ? 'bg-white shadow-sm text-cyan-700 border border-cyan-100/30'
                            : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '手动指标列表' : 'Metric List'}
                      </button>
                    </div>
                  </div>

                  {inspSource === 'default' && (
                    <div className="text-[11px] text-slate-500 bg-slate-50 p-3 rounded-xl border border-slate-100 leading-relaxed">
                      {zh ? '系统将自动启用全量内置的 CPU、内存、环境温度、电源风扇及接口状态等指标，自动进行多厂商设备的综合巡检打分。' : 'System will automatically execute all default CPU, memory, environment, PSU/Fan, and interface metrics for multi-vendor devices.'}
                    </div>
                  )}

                  {inspSource === 'script' && (
                    <div className="relative">
                      <label className="text-[10px] font-bold uppercase tracking-widest text-[#00a9ce] block mb-1.5">
                        {zh ? '关联巡检脚本' : 'ASSOCIATED INSPECTION SCRIPT'} <span className="text-red-500 normal-case">*</span>
                      </label>
                      <div className="relative">
                        <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                        <input
                          type="text"
                          placeholder={zh ? "输入名称搜索巡检脚本..." : "Type to search inspection scripts..."}
                          value={scriptSearch}
                          onFocus={() => {
                            setShowScriptDropdown(true);
                            if (!scriptSearch) {
                              const current = (availableScripts || []).find(s => s.id === form.script_id);
                              if (current) setScriptSearch(current.name);
                            }
                          }}
                          onChange={(e) => { setScriptSearch(e.target.value); setShowScriptDropdown(true); }}
                          className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-cyan-500/20 bg-cyan-500/5 text-sm focus:ring-2 focus:ring-cyan-500/20 outline-none transition-all placeholder:text-black/20"
                        />
                      </div>

                      <AnimatePresence>
                        {showScriptDropdown && (
                          <motion.div
                            initial={{ opacity: 0, y: -5 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -5 }}
                            className="absolute z-[60] left-0 right-0 mt-2 bg-white/95 backdrop-blur-md border border-slate-200 rounded-2xl shadow-xl max-h-48 overflow-y-auto custom-scrollbar"
                          >
                            {(() => {
                              const filtered = (availableScripts || []).filter(s => {
                                const searchVal = scriptSearch.toLowerCase();
                                return s.name.toLowerCase().includes(searchVal) && s.category === 'inspection';
                              });

                              if (filtered.length === 0) {
                                return <div className="p-8 text-center text-slate-400 text-[11px] italic">{zh ? '未找到匹配的巡检脚本' : 'No matching inspection scripts found'}</div>;
                              }

                              return filtered.map(s => {
                                const isSelected = form.script_id === s.id;
                                return (
                                  <div
                                    key={s.id}
                                    onClick={() => {
                                      setForm(f => ({ ...f, script_id: s.id }));
                                      setScriptSearch(s.name);
                                      setShowScriptDropdown(false);
                                    }}
                                    className={`px-5 py-3 text-[12px] cursor-pointer hover:bg-slate-50 transition-all flex items-center justify-between border-b border-slate-100 last:border-0 ${isSelected ? 'bg-cyan-50 text-cyan-700 font-bold' : 'text-slate-600'}`}
                                  >
                                    <span className="flex items-center gap-2">
                                      <FileCode size={12} className="text-emerald-500" />
                                      {s.name}
                                    </span>
                                    <span className="text-[9px] text-slate-400 font-mono">{s.platform}</span>
                                  </div>
                                );
                              });
                            })()}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}

                  {inspSource === 'custom' && (
                    <div className="space-y-1.5">
                      <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block">
                        {zh ? '巡检指标列表 (每行一个)' : 'Inspection Metric Keys (one per line)'} <span className="text-red-500 normal-case">*</span>
                      </label>
                      <textarea
                        value={form.commands}
                        onChange={e => setForm(f => ({ ...f, commands: e.target.value }))}
                        rows={3}
                        className="w-full px-3 py-2 rounded-xl border border-black/[0.08] text-xs font-mono bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all resize-none"
                        placeholder={zh ? '输入指标名称，每行一个\nnet_cisco_cpu\nnet_cisco_mem' : 'Enter metric names, one per line\nnet_cisco_cpu\nnet_cisco_mem'}
                      />
                    </div>
                  )}
                </div>
              )}

              {form.action_type === 'script_run' && (
                <div className="space-y-3">
                  <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="relative">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-[#00a9ce] block mb-1.5">
                      {zh ? '关联已发布脚本' : 'ASSOCIATED SCRIPT'} <span className="text-red-500 normal-case">*</span>
                    </label>
                    <div className="relative">
                      <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                      <input
                        type="text"
                        placeholder={zh ? "输入名称搜索所有脚本..." : "Type to search all scripts..."}
                        value={scriptSearch}
                        onFocus={() => {
                          setShowScriptDropdown(true);
                          if (!scriptSearch) {
                            const current = (availableScripts || []).find(s => s.id === form.script_id);
                            if (current) setScriptSearch(current.name);
                          }
                        }}
                        onChange={(e) => { setScriptSearch(e.target.value); setShowScriptDropdown(true); }}
                        className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-cyan-500/20 bg-cyan-500/5 text-sm focus:ring-2 focus:ring-cyan-500/20 outline-none transition-all placeholder:text-black/20"
                      />
                    </div>

                    <AnimatePresence>
                      {showScriptDropdown && (
                        <motion.div
                          initial={{ opacity: 0, y: -5 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -5 }}
                          className="absolute z-[60] left-0 right-0 mt-2 bg-white/95 backdrop-blur-md border border-slate-200 rounded-2xl shadow-xl max-h-48 overflow-y-auto custom-scrollbar"
                        >
                          {(() => {
                            const filtered = (availableScripts || []).filter(s => {
                              const searchVal = scriptSearch.toLowerCase();
                              return s.name.toLowerCase().includes(searchVal) && s.category !== 'inspection';
                            });

                            if (filtered.length === 0) {
                              return <div className="p-8 text-center text-slate-400 text-[11px] italic">{zh ? '未找到匹配的脚本' : 'No matching scripts found'}</div>;
                            }

                            return filtered.map(s => {
                              const isSelected = form.script_id === s.id;
                              const isTestScript = s.name.toLowerCase().includes('test');
                              const displayName = isTestScript 
                                ? `${zh ? '【测试示例】' : '[Test Example] '}${s.name.replace('test-script-', '')}`
                                : s.name;

                              return (
                                <div
                                  key={s.id}
                                  onClick={() => {
                                    setForm(f => ({ ...f, script_id: s.id }));
                                    setScriptSearch(s.name);
                                    setShowScriptDropdown(false);
                                  }}
                                  className={`px-5 py-3 text-[12px] cursor-pointer hover:bg-slate-50 transition-all flex items-center justify-between border-b border-slate-100 last:border-0 ${isSelected ? 'bg-cyan-50 text-cyan-700 font-bold' : 'text-slate-600'}`}
                                >
                                  <div className="flex flex-col gap-0.5">
                                    <span className="flex items-center gap-2">
                                      <FileCode size={12} className={isTestScript ? 'text-amber-500' : 'text-cyan-500'} />
                                      {displayName}
                                    </span>
                                    <div className="flex items-center gap-2 mt-1">
                                      <span className={`text-[8px] px-1.5 py-0.5 rounded uppercase tracking-wider ${s.category === 'inspection' ? 'bg-emerald-500/10 text-emerald-500' : s.category === 'change' ? 'bg-amber-500/10 text-amber-500' : 'bg-slate-500/10 text-slate-500'}`}>
                                        {s.category === 'inspection' ? (zh ? '巡检/采集' : 'INSPECTION') :
                                         s.category === 'change' ? (zh ? '自动化变更' : 'CHANGE') : (zh ? '未分类' : 'UNCATEGORIZED')}
                                      </span>
                                      {isTestScript && (
                                        <span className="text-[8px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 font-bold tracking-wider">
                                          {zh ? '测试脚本' : 'TEST'}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                  {isSelected && <CheckCircle2 size={14} className="text-cyan-600" />}
                                </div>
                              );
                            });
                          })()}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>

                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block">{zh ? '执行命令 (可选)' : 'Commands (Optional)'}</label>
                    <textarea
                      value={form.commands}
                      onChange={e => setForm(f => ({ ...f, commands: e.target.value }))}
                      rows={3}
                      className="w-full px-3 py-2 rounded-xl border border-black/[0.08] text-xs font-mono bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all resize-none"
                      placeholder={zh ? '输入设备命令，每行一个' : 'Enter commands, one per line'}
                    />
                  </div>
                </div>
              )}

              <div>
                <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                  {zh ? '设备范围' : 'Device Scope'} <span className="text-red-500 normal-case">*</span>
                </label>
                <select
                  value={form.device_scope}
                  onChange={e => {
                    setForm(f => ({ ...f, device_scope: e.target.value, device_filter: '' }));
                    setIpInput('');
                  }}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                >
                  {SCOPE_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{zh ? o.labelZh : o.labelEn}</option>
                  ))}
                </select>
              </div>

              {/* IP input — inline, right below Device Scope */}
              {form.device_scope === 'ip' && (
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                    {zh ? 'IP 地址' : 'IP Addresses'} <span className="text-red-500 normal-case">*</span>
                  </label>
                  <div className="relative">
                    <input
                      type="text"
                      value={ipInput}
                      onChange={e => { setIpInput(e.target.value); setIpError(''); }}
                      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); validateAndAddIps(ipInput); } }}
                      disabled={ipValidating}
                      className="w-full pl-3.5 pr-12 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all font-mono"
                      placeholder={zh ? '输入 IP/关键词 后回车查询，弹窗勾选添加' : 'Enter IP/query and press Enter to select'}
                    />
                    <button
                      type="button"
                      onClick={() => validateAndAddIps(ipInput)}
                      disabled={!ipInput.trim() || ipValidating}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-cyan-600 hover:bg-cyan-50 transition-all disabled:opacity-30"
                    >
                      {ipValidating ? <RotateCcw size={14} className="animate-spin" /> : <Search size={14} />}
                    </button>
                  </div>

                  {ipError && (
                    <p className={`text-[10px] mt-1 ${ipError.includes('已添加') || ipError.includes('added') ? 'text-amber-500' : 'text-red-500'}`}>{ipError}</p>
                  )}

                  {ipDevices.length > 0 && (
                    <div className="mt-2 space-y-1 max-h-40 overflow-y-auto pr-1">
                      {ipDevices.map(dev => (
                        <div
                          key={dev.ip}
                          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border group hover:border-cyan-200/60 transition-all ${
                            dev.hostname ? 'border-black/[0.06] bg-[#f8fafc]' : 'border-amber-200/60 bg-amber-50/30'
                          }`}
                        >
                          <span className="text-xs font-mono font-bold text-[#164e63] shrink-0">{dev.ip}</span>
                          {dev.hostname ? (
                            <>
                              <span className="text-black/15 text-[10px]">·</span>
                              <span className="text-[11px] text-black/40 truncate">{dev.hostname}</span>
                            </>
                          ) : (
                            <span className="text-[10px] text-amber-500 italic">{zh ? '手动IP' : 'manual'}</span>
                          )}
                          {dev.tags.length > 0 && (
                            <div className="flex items-center gap-1 flex-1 min-w-0 overflow-hidden">
                              {dev.tags.slice(0, 3).map(tag => (
                                <span
                                  key={tag.id}
                                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] font-medium bg-white border border-black/[0.06] shrink-0"
                                >
                                  <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: tag.color }} />
                                  <span className="truncate">{zh ? (tag.label_zh || tag.label) : tag.label}</span>
                                </span>
                              ))}
                              {dev.tags.length > 3 && (
                                <span className="text-[9px] text-black/30 shrink-0">+{dev.tags.length - 3}</span>
                              )}
                            </div>
                          )}
                          <button
                            type="button"
                            onClick={() => removeIpDevice(dev.ip)}
                            className="p-1 rounded-lg text-black/25 hover:text-red-500 hover:bg-red-50 transition-all shrink-0 ml-auto"
                            title={zh ? '移除' : 'Remove'}
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  <p className="text-[10px] text-black/25 mt-1.5">
                    {ipDevices.length > 0
                      ? (zh ? `已添加 ${ipDevices.length} 个设备` : `${ipDevices.length} device(s) added`)
                      : (zh ? '输入 IP 后回车,系统自动验证并显示设备标签' : 'Enter IP and press Enter to validate')}
                  </p>
                </div>
              )}

              {/* Tag picker — inline, right below Device Scope */}
              {form.device_scope === 'tag' && (
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                    {zh ? '标签条件' : 'Tag Conditions'} <span className="text-red-500 normal-case">*</span>
                  </label>
                  <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
                </div>
              )}

              {/* Site / Role filter */}
              {(form.device_scope === 'site' || form.device_scope === 'role') && (
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                    {zh ? '过滤条件' : 'Filter'} <span className="text-red-500 normal-case">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.device_filter}
                    onChange={e => setForm(f => ({ ...f, device_filter: e.target.value }))}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                    placeholder={zh ? (form.device_scope === 'site' ? '站点名称' : '角色名称') : (form.device_scope === 'site' ? 'Site name' : 'Role name')}
                  />
                </div>
              )}
            </div>

            {/* Right column */}
            <div className="space-y-4">
              {/* Cron */}
              <div className="space-y-3">
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setPresetOpen(!presetOpen)}
                    className="inline-flex h-10 w-full items-center justify-between gap-2 rounded-xl border border-black/8 bg-[#f8fafc] px-3.5 text-sm text-[#164e63] transition-all hover:border-cyan-400/30 hover:bg-white"
                  >
                    <div className="flex items-center gap-2">
                      <Zap size={13} className="text-cyan-500" />
                      <span>{zh ? '快速预设' : 'Quick Presets'}</span>
                    </div>
                    <ChevronDown size={14} className={`text-black/30 transition-transform ${presetOpen ? 'rotate-180' : ''}`} />
                  </button>
                  <AnimatePresence>
                    {presetOpen && (
                      <motion.div
                        initial={{ opacity: 0, y: -4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        className="absolute z-20 mt-1.5 w-full rounded-xl border border-black/8 bg-white shadow-lg overflow-hidden max-h-56 overflow-y-auto"
                      >
                        {CRON_PRESETS.map(p => (
                          <button
                            type="button"
                            key={p.cron}
                            onClick={() => {
                              setForm(f => ({ ...f, cron_expr: p.cron }));
                              setPresetOpen(false);
                            }}
                            className={`flex w-full items-center justify-between px-3.5 py-2.5 text-sm transition-colors hover:bg-[#ecfeff] ${form.cron_expr === p.cron ? 'bg-[#ecfeff] text-[#0891b2] font-medium' : 'text-black/60'}`}
                          >
                            <span>{zh ? p.label : p.labelEn}</span>
                            <code className="text-[10px] font-mono text-black/30">{p.cron}</code>
                          </button>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Info size={11} className="text-black/25" />
                    <p className="text-[10px] text-black/30">{zh ? '标准 5 段 Cron：分 时 日 月 周' : '5-field Cron: min hour day month weekday'}</p>
                  </div>
                  <div className="grid grid-cols-5 gap-1.5">
                    {cronFields.map((val, i) => (
                      <div key={i}>
                        <label className="block text-[9px] font-bold uppercase tracking-wider text-black/30 mb-0.5">
                          {zh ? CRON_FIELD_LABELS_ZH[i] : CRON_FIELD_LABELS_EN[i]}
                        </label>
                        <input
                          value={val}
                          onChange={e => updateCronField(i, e.target.value)}
                          placeholder="*"
                          className="w-full rounded-lg border border-black/8 bg-[#f8fafc] px-2 py-1.5 text-center font-mono text-sm text-[#164e63] outline-none placeholder:text-black/20 focus:border-cyan-400/40 focus:bg-white focus:ring-2 focus:ring-cyan-500/10 transition-all"
                        />
                        <p className="mt-0.5 text-[8px] text-black/20 text-center truncate">
                          {zh ? CRON_FIELD_HINTS_ZH[i] : CRON_FIELD_HINTS_EN[i]}
                        </p>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-3 rounded-lg bg-cyan-500/[0.04] px-3 py-2">
                    <code className="flex-1 font-mono text-sm text-[#164e63] font-semibold">{form.cron_expr}</code>
                    <span className="text-[11px] text-black/40">{describeCron(form.cron_expr, zh)}</span>
                  </div>
                </div>
              </div>

              {/* Removed command textarea here as it is moved above Device Scope inside script_run / inspection specific conditional panels */}

              {/* Execution User / Role Level */}
              <div className="space-y-2 pt-1">
                <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                  {zh ? '执行凭证与特权借用等级' : 'Execution Credentials & Privilege Level'}
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setForm(f => ({ ...f, use_admin_creds: false }))}
                    className={`flex items-start gap-2.5 p-3 rounded-xl border text-left transition-all ${
                      !form.use_admin_creds
                        ? 'border-cyan-500 bg-cyan-50/50 text-[#164e63] shadow-sm font-semibold'
                        : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                    }`}
                  >
                    <div className={`w-3.5 h-3.5 rounded-full flex items-center justify-center border mt-0.5 shrink-0 ${!form.use_admin_creds ? 'border-cyan-600 bg-cyan-600 text-white' : 'border-slate-300'}`}>
                      {!form.use_admin_creds && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-bold flex items-center gap-1.5">
                        <User className="w-3.5 h-3.5 text-cyan-600 shrink-0" />
                        <span className="truncate">{zh ? '普通运维操作员' : 'Normal Operator'}</span>
                      </div>
                      <div className="text-[10px] text-black/40 font-normal mt-0.5 leading-snug">{zh ? '日常例行巡检与常规低危命令，使用标准受限凭据连接' : 'Routine inspection & standard commands using normal creds'}</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setForm(f => ({ ...f, use_admin_creds: true }))}
                    className={`flex items-start gap-2.5 p-3 rounded-xl border text-left transition-all ${
                      form.use_admin_creds
                        ? 'border-amber-500 bg-amber-50/50 text-amber-900 shadow-sm font-semibold'
                        : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50'
                    }`}
                  >
                    <div className={`w-3.5 h-3.5 rounded-full flex items-center justify-center border mt-0.5 shrink-0 ${form.use_admin_creds ? 'border-amber-600 bg-amber-600 text-white' : 'border-slate-300'}`}>
                      {form.use_admin_creds && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-bold flex items-center gap-1.5 text-amber-800">
                        <ShieldAlert className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                        <span className="truncate">{zh ? '特权借用 (Enable/Admin)' : 'Privileged Borrowing'}</span>
                      </div>
                      <div className="text-[10px] text-amber-700/70 font-normal mt-0.5 leading-snug">{zh ? '高危或管理作业自动申请使用硬件保险箱中的提权密码' : 'Auto borrow enable/admin credentials from hardware vault'}</div>
                    </div>
                  </button>
                </div>
              </div>

              {/* Approval (create & edit) */}
              <div className="rounded-xl border border-black/8 overflow-hidden shadow-sm">
                <div className={`px-4 py-2.5 flex items-center gap-2.5 ${
                  approvalStatus === 'verified'
                    ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white'
                    : 'bg-gradient-to-r from-[#0d9488] to-[#0f766e] text-white'
                }`}>
                  <Shield className="w-3.5 h-3.5 text-white/90" />
                  <span className="text-[12px] font-semibold text-white/95">
                    {approvalStatus === 'verified'
                      ? (zh ? '审批已通过' : 'Approval Granted')
                      : (zh ? '审批验证' : 'Approval Required')}
                  </span>
                  {approvalStatus === 'verified' && (
                    <span className="ml-auto text-[11px] text-white/70 font-medium flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      {zh ? '可以创建' : 'Ready'}
                    </span>
                  )}
                </div>

                {approvalStatus !== 'verified' && (
                  <div className="px-4 py-3.5 bg-[#f7fbfc] space-y-3">
                    <div className="space-y-3">
                      <div>
                        <label className="text-[11px] font-semibold text-black/50 mb-1 block">{zh ? '变更原因' : 'Reason'}</label>
                        <input
                          value={form.config_reason}
                          onChange={e => setForm(f => ({ ...f, config_reason: e.target.value }))}
                          placeholder={zh ? '创建定时备份作业' : 'Create scheduled backup job'}
                          className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 placeholder:text-black/25 transition-all"
                          maxLength={200}
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-black/50 mb-1 block">{zh ? '审批人' : 'Approver'}</label>
                        <div className="flex items-center gap-2">
                          <select
                            value={approverUsername}
                            onChange={e => setApproverUsername(e.target.value)}
                            className="flex-1 rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 transition-all"
                            disabled={approvalStatus === 'sent' || approvalStatus === 'sending'}
                          >
                            <option value="">{zh ? '选择审批人...' : 'Select approver...'}</option>
                            {approvers.map(u => (
                              <option key={u.id} value={u.username}>
                                {u.username} ({u.role})
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            onClick={requestApproval}
                            disabled={!approverUsername || !form.config_reason.trim() || approvalStatus === 'sending' || (approvalStatus === 'sent' && approvalCountdown > 0)}
                            className={`px-3 py-2 rounded-xl text-[11px] font-semibold transition-all whitespace-nowrap flex items-center gap-1.5 ${
                              approverUsername && form.config_reason.trim() && !(approvalStatus === 'sent' && approvalCountdown > 0)
                                ? 'bg-[#005b75] text-white hover:bg-[#00465a] shadow-sm'
                                : 'bg-black/8 text-black/30 cursor-not-allowed'
                            }`}
                          >
                            {approvalStatus === 'sending' ? (
                              <RotateCcw className="w-3 h-3 animate-spin" />
                            ) : approvalStatus === 'sent' && approvalCountdown > 0 ? (
                              `${Math.floor(approvalCountdown / 60)}:${String(approvalCountdown % 60).padStart(2, '0')}`
                            ) : (
                              zh ? '发送验证码' : 'Send Code'
                            )}
                          </button>
                        </div>
                      </div>
                    </div>

                    {approvalStatus === 'sent' && (
                      <div className="space-y-2">
                        <label className="text-[11px] text-black/40 block">
                          {zh ? '输入审批人收到的 6 位验证码' : 'Enter the 6-digit code sent to approver'}
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            value={approvalCode}
                            onChange={e => { setApprovalCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setApprovalError(''); }}
                            placeholder="000000"
                            maxLength={6}
                            className="w-36 tracking-[0.3em] text-center rounded-xl border border-black/10 bg-white px-3 py-2 text-sm font-mono outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 transition-all"
                          />
                          <button
                            type="button"
                            onClick={verifyApproval}
                            disabled={approvalCode.length !== 6}
                            className={`px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                              approvalCode.length === 6
                                ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                                : 'bg-black/8 text-black/30 cursor-not-allowed'
                            }`}
                          >
                            {zh ? '验证' : 'Verify'}
                          </button>
                        </div>
                      </div>
                    )}

                    {approvalError && (
                      <div className="flex items-center gap-1.5 text-red-600 text-[11px]">
                        <AlertTriangle className="w-3 h-3" />
                        {approvalError}
                      </div>
                    )}

                    <p className="text-[10px] text-black/25">
                      {zh ? '验证码将通过飞书发送给审批人，有效期 5 分钟。' : 'A verification code will be sent to the approver via Feishu. Valid for 5 minutes.'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="lg:col-span-2 pt-4 border-t border-black/5 flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-6 py-2.5 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 hover:bg-slate-50 transition-all"
            >
              {zh ? '取消' : 'Cancel'}
            </button>
            <button
              type="button"
              onClick={submitForm}
              disabled={!isFormReady || (!isEditMode && approvalStatus !== 'verified')}
              className="px-8 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-bold shadow-md hover:from-cyan-400 hover:to-blue-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isEditMode ? (zh ? '保存修改' : 'Save Changes') : (zh ? '确认创建' : 'Confirm Create')}
            </button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
};
