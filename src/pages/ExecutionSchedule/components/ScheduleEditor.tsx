import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, X, RotateCcw, Shield, AlertTriangle,
  Search, CheckCircle2, FileCode, ShieldAlert, User,
} from 'lucide-react';
import DateTimePicker from '../../../components/DateTimePicker';
import TagConditionPicker, { type TagFilterConfig } from '../../../components/TagConditionPicker';
import type { FormState, ValidatedDevice, EligibleApprover } from '../types';
import { MAJOR_CATEGORIES, SCOPE_OPTIONS } from '../constants';
import { Trash2 } from 'lucide-react';

interface ScheduleEditorProps {
  zh: boolean;
  language: string;
  form: FormState;
  setForm: React.Dispatch<React.SetStateAction<FormState>>;
  // IP validation
  ipInput: string;
  setIpInput: (v: string) => void;
  ipDevices: ValidatedDevice[];
  ipValidating: boolean;
  ipError: string;
  setIpError: (v: string) => void;
  onValidateIps: (raw: string) => void;
  onRemoveIpDevice: (ip: string) => void;
  // Tag
  tagFilter: TagFilterConfig;
  setTagFilter: (v: TagFilterConfig) => void;
  // Script
  availableScripts: { id: string; name: string; status: string; category: string }[];
  scriptSearch: string;
  setScriptSearch: (v: string) => void;
  showScriptDropdown: boolean;
  setShowScriptDropdown: (v: boolean) => void;
  onFetchScripts: () => void;
  // Inspection items
  inspectionItems: any[];
  inspectionItemsLoading: boolean;
  // Approval
  approvers: EligibleApprover[];
  approverUsername: string;
  setApproverUsername: (v: string) => void;
  approvalStatus: 'idle' | 'sending' | 'sent' | 'verified';
  approvalError: string;
  approvalCode: string;
  setApprovalCode: (v: string) => void;
  setApprovalError: (v: string) => void;
  onRequestApproval: () => void;
  onVerifyApproval: () => void;
  onResetApproval: () => void;
  // Actions
  onSubmit: () => void;
  onCancel: () => void;
}

const ScheduleEditor: React.FC<ScheduleEditorProps> = ({
  zh, language, form, setForm,
  ipInput, setIpInput, ipDevices, ipValidating, ipError, setIpError,
  onValidateIps, onRemoveIpDevice,
  tagFilter, setTagFilter,
  availableScripts, scriptSearch, setScriptSearch, showScriptDropdown, setShowScriptDropdown, onFetchScripts,
  inspectionItems, inspectionItemsLoading,
  approvers, approverUsername, setApproverUsername,
  approvalStatus, approvalError, approvalCode, setApprovalCode, setApprovalError,
  onRequestApproval, onVerifyApproval, onResetApproval,
  onSubmit, onCancel,
}) => {
  return (
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
          {zh ? '配置新的执行计划' : 'Configure New Execution Schedule'}
        </h3>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left Column: Basic Info & Scope */}
        <div className="space-y-5">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '计划名称' : 'Name'}</label>
            <input
              type="text" value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
              placeholder={zh ? '例：核心交换机月度变更' : 'e.g. Core Switch Monthly Check'}
            />
          </div>

          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '作业类型' : 'Action Type'}</label>
            <div className="grid grid-cols-2 gap-2">
              {MAJOR_CATEGORIES.map(mc => (
                <button
                  key={mc.value} type="button"
                  onClick={() => {
                     setForm(f => ({ ...f, major_type: mc.value as any }));
                     if (mc.value === 'change') {
                       setForm(f => ({ ...f, action_type: 'script_run' }));
                     } else if (mc.value === 'collection' && form.action_type !== 'script_run') {
                       setForm(f => ({ ...f, action_type: 'backup' }));
                     }
                     onFetchScripts();
                  }}
                  className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border text-xs font-semibold transition-all ${
                    form.major_type === mc.value
                      ? 'border-cyan-400 bg-cyan-50 text-[#0891b2]'
                      : 'border-black/[0.06] bg-white text-black/50 hover:border-black/15'
                  }`}
                >
                  <mc.icon className="w-3.5 h-3.5" />
                  {zh ? mc.labelZh : mc.labelEn}
                </button>
              ))}
            </div>
          </div>

          {form.major_type === 'collection' && (
            <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="p-1 bg-slate-50 rounded-xl border border-black/5 flex gap-1">
              <button
                type="button"
                onClick={() => setForm(f => ({ ...f, action_type: 'backup', script_id: '' }))}
                className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${form.action_type === 'backup' ? 'bg-white shadow-sm text-cyan-600' : 'text-black/40 hover:text-black/60'}`}
              >
                {zh ? '核心配置采集' : 'Config Backup'}
              </button>
              <button
                type="button"
                onClick={() => setForm(f => ({ ...f, action_type: 'inspection' }))}
                className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${form.action_type === 'inspection' ? 'bg-white shadow-sm text-cyan-600' : 'text-black/40 hover:text-black/60'}`}
              >
                {zh ? '智能巡检' : 'Inspection'}
              </button>
              <button
                type="button"
                onClick={() => setForm(f => ({ ...f, action_type: 'script_run' }))}
                className={`flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-all ${form.action_type === 'script_run' ? 'bg-white shadow-sm text-cyan-600' : 'text-black/40 hover:text-black/60'}`}
              >
                {zh ? '脚本运行' : 'Script'}
              </button>
            </motion.div>
          )}

          {form.action_type === 'script_run' && (
             <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="relative">
                <label className="text-[10px] font-bold uppercase tracking-widest text-[#00a9ce] block mb-1.5">{zh ? '关联已发布脚本' : 'ASSOCIATED SCRIPT'}</label>
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
                        initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }}
                        className="absolute z-[60] left-0 right-0 mt-2 bg-[#0f172a]/95 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl max-h-48 overflow-y-auto custom-scrollbar"
                      >
                         {(() => {
                            const filtered = (availableScripts || []).filter(s => {
                               const searchVal = scriptSearch.toLowerCase();
                               return s.name.toLowerCase().includes(searchVal);
                            });
                            if (filtered.length === 0) return <div className="p-8 text-center text-slate-400 text-[11px] italic">{zh ? '未找到匹配的脚本' : 'No matching scripts found'}</div>;
                            return filtered.map(s => {
                               const isSelected = form.script_id === s.id;
                               const expectedCategory = form.major_type === 'collection' ? 'inspection' : 'change';
                               const isWrongCategory = s.category && s.category !== expectedCategory;
                               return (
                                  <div 
                                    key={s.id} 
                                    onClick={() => { 
                                      setForm(f => ({ ...f, script_id: s.id })); 
                                      setScriptSearch(s.name); 
                                      setShowScriptDropdown(false); 
                                    }}
                                    className={`px-5 py-3 text-[12px] cursor-pointer hover:bg-white/5 transition-all flex items-center justify-between border-b border-white/5 last:border-0 ${isSelected ? 'bg-cyan-500/20 text-[#00a9ce] font-bold' : 'text-slate-300'}`}
                                  >
                                     <div className="flex flex-col gap-0.5">
                                        <span className="flex items-center gap-2">
                                           <FileCode size={12} className={isWrongCategory ? 'text-amber-500' : 'text-cyan-500'} /> 
                                           {s.name}
                                        </span>
                                        <div className="flex items-center gap-2 mt-1">
                                           <span className={`text-[8px] px-1.5 py-0.5 rounded uppercase tracking-wider ${s.category === 'inspection' ? 'bg-emerald-500/10 text-emerald-500' : s.category === 'change' ? 'bg-amber-500/10 text-amber-500' : 'bg-slate-500/10 text-slate-500'}`}>
                                              {s.category === 'inspection' ? (zh ? '巡检/采集' : 'INSPECTION') : 
                                               s.category === 'change' ? (zh ? '自动化变更' : 'CHANGE') : (zh ? '未分类' : 'UNCATEGORIZED')}
                                           </span>
                                           {isWrongCategory && <span className="text-[8px] text-amber-500/60 italic font-normal">{zh ? '(非当前分类)' : '(Not current category)'}</span>}
                                        </div>
                                     </div>
                                     {isSelected && <CheckCircle2 size={14} className="text-cyan-400" />}
                                  </div>
                               );
                            });
                         })()}
                      </motion.div>
                   )}
                </AnimatePresence>
             </motion.div>
          )}

          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '设备范围' : 'Device Scope'}</label>
            <select
              value={form.device_scope}
              onChange={e => { setForm(f => ({ ...f, device_scope: e.target.value, device_filter: '' })); }}
              className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
            >
              {SCOPE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{zh ? o.labelZh : o.labelEn}</option>
              ))}
            </select>
          </div>

          {form.device_scope === 'ip' && (
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
                {zh ? 'IP 地址' : 'IP Addresses'}
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={ipInput}
                  onChange={e => { setIpInput(e.target.value); setIpError(''); }}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); onValidateIps(ipInput); } }}
                  disabled={ipValidating}
                  className="w-full pl-3.5 pr-12 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all font-mono"
                  placeholder={zh ? '输入 IP/关键词 后回车查询，弹窗勾选添加' : 'Enter IP/query and press Enter to select'}
                />
                <button
                  type="button"
                  onClick={() => onValidateIps(ipInput)}
                  disabled={!ipInput.trim() || ipValidating}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-cyan-600 hover:bg-cyan-50 transition-all disabled:opacity-30"
                >
                  {ipValidating ? <RotateCcw size={14} className="animate-spin" /> : <Search size={14} />}
                </button>
              </div>
              {ipError && <p className={`text-[10px] mt-1 ${ipError.includes('已添加') || ipError.includes('added') ? 'text-amber-500' : 'text-red-500'}`}>{ipError}</p>}
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
                      <button
                        type="button"
                        onClick={() => onRemoveIpDevice(dev.ip)}
                        className="p-1 rounded-lg text-black/25 hover:text-red-500 hover:bg-red-50 transition-all shrink-0 ml-auto"
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

          {form.device_scope === 'tag' && (
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '标签条件' : 'Tag Conditions'}</label>
              <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
            </div>
          )}

          {(form.device_scope === 'site' || form.device_scope === 'role') && (
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">{zh ? '过滤条件' : 'Filter'}</label>
              <input
                type="text" value={form.device_filter}
                onChange={e => setForm(f => ({ ...f, device_filter: e.target.value }))}
                className="w-full px-3.5 py-2.5 rounded-xl border border-black/[0.08] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all"
                placeholder={zh ? (form.device_scope === 'site' ? '站点名称' : '角色名称') : (form.device_scope === 'site' ? 'Site name' : 'Role name')}
              />
            </div>
          )}
        </div>

        {/* Right Column: Time, Commands, Security */}
        <div className="space-y-5">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block mb-1.5">
              {zh ? '执行时间' : 'Execution Time'}
            </label>
            <DateTimePicker
              value={form.scheduled_at}
              onChange={v => setForm(f => ({ ...f, scheduled_at: v }))}
              language={language}
              className="w-full"
            />
          </div>

          {form.action_type !== 'backup' && (
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/35 block">
                {form.action_type === 'inspection' ? (zh ? '巡检指标项' : 'Inspection Items') : (zh ? '执行命令 (可选)' : 'Commands (Optional)')}
              </label>
              {form.action_type === 'inspection' ? (
                <div className="rounded-xl border border-black/[0.08] p-3 max-h-48 overflow-y-auto custom-scrollbar bg-[#f8fafc]">
                  {inspectionItemsLoading ? (
                    <div className="py-4 text-center text-black/20 text-[11px] italic">{zh ? '加载中...' : 'Loading...'}</div>
                  ) : inspectionItems.length > 0 ? (
                    <div className="grid grid-cols-2 gap-2">
                      {inspectionItems.map(item => {
                        const isChecked = form.check_items.includes(item.name);
                        return (
                          <label key={item.id} className="flex items-center gap-2 cursor-pointer group">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => {
                                setForm(f => ({
                                  ...f,
                                  check_items: isChecked ? f.check_items.filter(x => x !== item.name) : [...f.check_items, item.name]
                                }));
                              }}
                              className="w-3.5 h-3.5 rounded border-black/20 text-cyan-500 focus:ring-cyan-500/20"
                            />
                            <span className="text-[11px] text-black/60 font-medium group-hover:text-cyan-600 truncate">{item.name}</span>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="py-4 text-center text-black/20 text-[11px] italic">{zh ? '暂无可用指标项' : 'No items available'}</div>
                  )}
                </div>
              ) : (
                <textarea
                  value={form.commands}
                  onChange={e => setForm(f => ({ ...f, commands: e.target.value }))}
                  rows={3}
                  className="w-full px-3 py-2 rounded-xl border border-black/[0.08] text-xs font-mono bg-[#f8fafc] focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-400 transition-all resize-none"
                  placeholder={zh ? '输入设备命令，每行一个' : 'Enter commands, one per line'}
                />
              )}
            </div>
          )}

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
                  <div className="text-[11px] font-bold flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5 text-cyan-600 shrink-0" />
                    <span className="truncate">{zh ? '普通运维操作员' : 'Normal Operator'}</span>
                  </div>
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
                  <div className="text-[11px] font-bold flex items-center gap-1.5 text-amber-800">
                    <ShieldAlert className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                    <span className="truncate">{zh ? '特权借用 (Enable)' : 'Privileged Borrowing'}</span>
                  </div>
                </div>
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-black/8 overflow-hidden">
            <div className={`px-4 py-2.5 flex items-center gap-2.5 ${
              approvalStatus === 'verified'
                ? 'bg-gradient-to-r from-emerald-500 to-emerald-600'
                : 'bg-gradient-to-r from-[#005b75] to-[#00465a]'
            }`}>
              <Shield className="w-3.5 h-3.5 text-white/90" />
              <span className="text-[12px] font-semibold text-white/95">
                {approvalStatus === 'verified' ? (zh ? '审批已通过' : 'Approval Granted') : (zh ? '审批验证' : 'Approval Required')}
              </span>
            </div>

            {approvalStatus !== 'verified' && (
              <div className="px-4 py-3.5 bg-[#f7fbfc] space-y-3">
                <div className="space-y-3">
                  <div>
                    <label className="text-[11px] font-semibold text-black/50 mb-1 block">{zh ? '变更原因' : 'Reason'}</label>
                    <input
                      value={form.config_reason}
                      onChange={e => setForm(f => ({ ...f, config_reason: e.target.value }))}
                      placeholder={zh ? '创建执行计划' : 'Create execution plan'}
                      className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-xs outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20 placeholder:text-black/25 transition-all"
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
                          <option key={u.id} value={u.username}>{u.username} ({u.role})</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={onRequestApproval}
                        disabled={!approverUsername || !form.config_reason.trim() || approvalStatus === 'sending' || approvalStatus === 'sent'}
                        className={`px-3 py-2 rounded-xl text-[11px] font-semibold transition-all flex items-center gap-1.5 ${
                          approverUsername && form.config_reason.trim() && approvalStatus !== 'sent'
                            ? 'bg-[#005b75] text-white hover:bg-[#00465a] shadow-sm'
                            : 'bg-black/8 text-black/30 cursor-not-allowed'
                        }`}
                      >
                        {approvalStatus === 'sending' ? <RotateCcw className="w-3 h-3 animate-spin" /> : (zh ? '发验证码' : 'Send Code')}
                      </button>
                    </div>
                  </div>
                </div>

                {approvalStatus === 'sent' && (
                  <div className="space-y-1.5 pt-2 border-t border-black/5">
                    <label className="text-[11px] text-black/50 block">{zh ? '输入 6 位工单验证码' : 'Enter 6-digit verification code'}</label>
                    <div className="flex items-center gap-2">
                      <input
                        value={approvalCode} onChange={e => { setApprovalCode(e.target.value.replace(/\D/g, '').slice(0, 6)); setApprovalError(''); }}
                        placeholder="000000" maxLength={6}
                        className="w-32 tracking-[0.3em] text-center font-mono rounded-xl border border-black/10 py-2 text-sm outline-none focus:border-emerald-500 transition-all"
                      />
                      <button
                        type="button" onClick={onVerifyApproval} disabled={approvalCode.length !== 6}
                        className={`px-4 py-2 rounded-xl font-bold transition-all ${approvalCode.length === 6 ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-black/8 text-black/30 cursor-not-allowed'}`}
                      >
                        {zh ? '验证' : 'Verify'}
                      </button>
                      <button onClick={onResetApproval} className="p-2 text-black/30 hover:text-black/50 ml-1" title={zh ? '重置审批状态' : 'Reset'}>
                        <RotateCcw size={14} />
                      </button>
                    </div>
                  </div>
                )}

                {approvalError && (
                  <div className="flex items-center gap-1.5 text-rose-600 text-[11px] pt-1">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>{approvalError}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Submit */}
      <div className="border-t border-black/5 pt-5 flex items-center justify-end gap-3">
        <button
          onClick={onCancel}
          className="px-6 py-2.5 rounded-xl border border-black/10 text-sm font-semibold text-black/50 hover:bg-black/5 transition-all"
        >
          {zh ? '取消' : 'Cancel'}
        </button>
        <button
          onClick={onSubmit}
          disabled={!form.name.trim() || !form.scheduled_at || approvalStatus !== 'verified'}
          className="px-8 py-2.5 rounded-xl bg-[#164e63] text-white text-sm font-bold shadow-lg shadow-cyan-900/10 hover:bg-[#0891b2] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {zh ? '发布执行计划' : 'Publish Schedule'}
        </button>
      </div>
    </motion.div>
  );
};

export default ScheduleEditor;
