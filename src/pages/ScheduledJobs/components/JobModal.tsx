import React, { useState, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, X, Zap, ChevronDown, Search, FileCode, CheckCircle2,
  Trash2, RotateCcw, Shield, AlertTriangle, Database, Activity, RefreshCw,
  Target, Globe, Server, Check, Terminal, Radio, ChevronRight, Clock,
  Sparkles, Layers, Sliders, ShieldCheck, CheckCheck
} from 'lucide-react';
import TagConditionPicker, { hasTagFilterConditions, type TagFilterConfig } from '../../../components/TagConditionPicker';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
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
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string; script_type?: string }>;
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
  devices?: any[];
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
  devices = [],
}) => {
  const zh = language === 'zh';

  // Sub-states for Inspection
  const [inspSource, setInspSource] = useState<'default' | 'network' | 'server' | 'script'>('default');

  // Sub-states for Script Run
  const [scriptAssetCategory, setScriptAssetCategory] = useState<'network' | 'server'>('network');
  const [scriptProtocolChannel, setScriptProtocolChannel] = useState<'cli' | 'snmp' | 'shell'>('cli');
  
  // Right panel device search
  const [deviceSearchQuery, setDeviceSearchQuery] = useState('');

  React.useEffect(() => {
    if (isOpen && form.action_type === 'inspection') {
      if (form.script_id) {
        setInspSource('script');
        const current = (availableScripts || []).find(s => s.id === form.script_id);
        if (current) setScriptSearch(current.name);
      } else if (form.commands && form.commands.includes('disk')) {
        setInspSource('server');
      } else if (form.commands && form.commands.includes('fan')) {
        setInspSource('network');
      } else {
        setInspSource('default');
      }
    }
  }, [isOpen, form.action_type, form.script_id, form.commands, availableScripts, setScriptSearch]);

  // Extract unique filter options with counts from CMDB devices
  const siteCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    (devices || []).forEach(d => {
      const s = d.site || '';
      if (s) counts[s] = (counts[s] || 0) + 1;
    });
    return counts;
  }, [devices]);

  const roleCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    (devices || []).forEach(d => {
      const r = d.role || '';
      if (r) counts[r] = (counts[r] || 0) + 1;
    });
    return counts;
  }, [devices]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    (devices || []).forEach(d => {
      const c = d.category || (d.role?.toLowerCase().includes('server') ? 'Server' : 'Network');
      counts[c] = (counts[c] || 0) + 1;
    });
    return counts;
  }, [devices]);

  // Parse composite filter
  const compositeFilter = useMemo(() => {
    if (form.device_scope !== 'composite') return { site: '', role: '', category: '' };
    try {
      return JSON.parse(form.device_filter || '{}');
    } catch {
      return { site: '', role: '', category: '' };
    }
  }, [form.device_scope, form.device_filter]);

  const updateCompositeFilter = (key: string, val: string) => {
    const updated = { ...compositeFilter, [key]: val };
    Object.keys(updated).forEach(k => { if (!updated[k as keyof typeof updated]) delete updated[k as keyof typeof updated]; });
    setForm(f => ({ ...f, device_filter: JSON.stringify(updated) }));
  };

  // Real-time matched devices calculation
  const matchedDevices = useMemo(() => {
    const all = devices || [];
    if (form.device_scope === 'all') {
      return all;
    }
    if (form.device_scope === 'composite') {
      return all.filter(d => {
        if (compositeFilter.site && d.site !== compositeFilter.site) return false;
        if (compositeFilter.role && d.role !== compositeFilter.role) return false;
        if (compositeFilter.category && (d.category || (d.role?.toLowerCase().includes('server') ? 'Server' : 'Network')) !== compositeFilter.category) return false;
        return true;
      });
    }
    if (form.device_scope === 'site') {
      return all.filter(d => d.site === form.device_filter);
    }
    if (form.device_scope === 'role') {
      return all.filter(d => d.role === form.device_filter);
    }
    if (form.device_scope === 'ip') {
      const ips = new Set(ipDevices.map(d => d.ip));
      return all.filter(d => ips.has(d.ip_address));
    }
    return all;
  }, [devices, form.device_scope, form.device_filter, compositeFilter, ipDevices]);

  // Filter matched devices by search query
  const displayedMatchedDevices = useMemo(() => {
    if (!deviceSearchQuery.trim()) return matchedDevices;
    const q = deviceSearchQuery.toLowerCase();
    return matchedDevices.filter(d =>
      (d.hostname || '').toLowerCase().includes(q) ||
      (d.ip_address || '').includes(q) ||
      (d.platform || '').toLowerCase().includes(q) ||
      (d.site || '').toLowerCase().includes(q)
    );
  }, [matchedDevices, deviceSearchQuery]);

  // Platform breakdown for matched devices
  const platformBreakdown = useMemo(() => {
    const counts: Record<string, number> = {};
    matchedDevices.forEach(d => {
      const p = d.platform || 'generic';
      counts[p] = (counts[p] || 0) + 1;
    });
    return counts;
  }, [matchedDevices]);

  const onlineCount = useMemo(() => {
    return matchedDevices.filter(d => d.status === 'online' || d.is_active === 1 || d.ping_status === 'up').length;
  }, [matchedDevices]);

  // Filter scripts based on Asset Category & Protocol Channel
  const filteredScripts = useMemo(() => {
    return (availableScripts || []).filter(s => {
      const searchVal = scriptSearch.toLowerCase();
      const matchSearch = !searchVal || s.name.toLowerCase().includes(searchVal) || (s.platform || '').toLowerCase().includes(searchVal);
      if (!matchSearch) return false;

      const p = (s.platform || '').toLowerCase();
      const isShell = s.script_type === 'shell' || p.includes('linux') || p.includes('server') || p.includes('bash') || p.includes('python');
      const isSnmp = (s as any).protocol === 'snmp' || s.name.toLowerCase().includes('snmp') || p.includes('snmp');

      if (scriptAssetCategory === 'server') {
        return isShell;
      } else {
        if (scriptProtocolChannel === 'snmp') {
          return isSnmp;
        } else {
          return !isShell && !isSnmp;
        }
      }
    });
  }, [availableScripts, scriptSearch, scriptAssetCategory, scriptProtocolChannel]);

  // Selected Script & Compatibility Guard
  const selectedScript = useMemo(() => {
    if (form.action_type !== 'script_run' || !form.script_id) return null;
    return (availableScripts || []).find(s => s.id === form.script_id);
  }, [form.action_type, form.script_id, availableScripts]);

  const scriptIncompatibleCount = useMemo(() => {
    if (!selectedScript || !selectedScript.platform || selectedScript.platform === 'any' || selectedScript.platform === 'all') return 0;
    const reqPlatform = selectedScript.platform.toLowerCase();
    return matchedDevices.filter(d => {
      const p = (d.platform || '').toLowerCase();
      return p && !p.includes(reqPlatform) && !reqPlatform.includes(p);
    }).length;
  }, [selectedScript, matchedDevices]);

  if (!isOpen) return null;

  // Form ready calculation
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
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -15 }}
        className="w-full bg-white rounded-3xl border border-slate-200 shadow-xl overflow-hidden"
      >
        {/* Top Gradient Banner */}
        <div className="h-1 bg-gradient-to-r from-cyan-500 via-sky-500 to-blue-600" />
        
        {/* Clean Top Header */}
        <div className="px-8 py-5 flex items-center justify-between border-b border-slate-100 bg-white">
          <div className="flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-2xl bg-cyan-50 border border-cyan-100 flex items-center justify-center text-cyan-600 shadow-sm">
              <CalendarClock size={22} />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900 tracking-tight">
                {isEditMode ? (zh ? '编辑周期性定时作业' : 'Edit Scheduled Job') : (zh ? '创建周期性定时作业' : 'Create Scheduled Job')}
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {zh ? '配置执行动作、调度周期与目标设备，实现全网巡检、备份与自动化执行' : 'Configure strategy, schedule, and target fleet for network automation'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Full-Width Dual-Column Balanced Workspace */}
        <form onSubmit={e => { e.preventDefault(); submitForm(); }}>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 p-6 lg:p-8 bg-slate-50/30">
            
            {/* ═══════════════════════════════════════════════════════════════════
                LEFT COLUMN (56% / 7 cols): 执行策略配置与目标资产范围
               ═══════════════════════════════════════════════════════════════════ */}
            <div className="lg:col-span-7 space-y-6">
              
              {/* Block 1: 基本属性 */}
              <div className="p-6 rounded-2xl bg-white border border-slate-200/90 shadow-2xs space-y-4">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-cyan-500" />
                  <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '基本信息' : 'Basic Info'}</h3>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-600 block">
                    {zh ? '作业名称' : 'Job Name'} <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full px-4 py-2.5 rounded-xl border border-slate-200 text-xs font-medium text-slate-800 bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 transition-all placeholder:text-slate-300"
                    placeholder={zh ? '例如：每日凌晨核心交换机巡检' : 'e.g. Daily Core Switch Health Inspection'}
                  />
                </div>
              </div>

              {/* Block 2: 执行动作与驱动协议 */}
              <div className="p-6 rounded-2xl bg-white border border-slate-200/90 shadow-2xs space-y-4">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-blue-500" />
                  <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '执行动作与驱动策略' : 'Action & Driver Strategy'}</h3>
                </div>

                {/* 4 Action Types */}
                <div className="p-1 bg-slate-100 rounded-xl grid grid-cols-2 sm:grid-cols-4 gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'inspection', major_type: 'collection' }));
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'inspection'
                        ? 'bg-white shadow-2xs text-cyan-700 font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <Activity className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '智能巡检' : 'Inspection'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'backup', major_type: 'collection', script_id: '' }));
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'backup'
                        ? 'bg-white shadow-2xs text-cyan-700 font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <Database className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '配置备份' : 'Backup'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({
                        ...f,
                        action_type: 'nsot',
                        major_type: 'collection',
                        commands: '',
                        script_id: '',
                        is_config: false,
                        use_admin_creds: false,
                      }));
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'nsot'
                        ? 'bg-white shadow-2xs text-cyan-700 font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <RefreshCw className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? 'NSOT 事实库' : 'NSOT Facts'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'script_run', major_type: 'change' }));
                      fetchScripts();
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                      form.action_type === 'script_run'
                        ? 'bg-white shadow-2xs text-cyan-700 font-bold'
                        : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <FileCode className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '脚本执行' : 'Script Run'}
                  </button>
                </div>

                {/* Sub-Action: Inspection */}
                {form.action_type === 'inspection' && (
                  <div className="space-y-3 pt-1">
                    <div className="p-1 bg-slate-50 rounded-xl grid grid-cols-2 sm:grid-cols-4 gap-1 border border-slate-200/70">
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('default');
                          setForm(f => ({ ...f, script_id: '', commands: '' }));
                        }}
                        className={`py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all text-center ${
                          inspSource === 'default' ? 'bg-white text-cyan-700 shadow-2xs' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '✨ 智能自适应' : 'Smart Adaptive'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('network');
                          setForm(f => ({ ...f, script_id: '', commands: 'cpu,memory,temperature,fan,psu,interface_errors,interface_flapping,reachability' }));
                        }}
                        className={`py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all text-center ${
                          inspSource === 'network' ? 'bg-white text-cyan-700 shadow-2xs' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '🔀 网络设备套件' : 'Network Suite'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('server');
                          setForm(f => ({ ...f, script_id: '', commands: 'cpu,memory,disk,loadavg,system_services,reachability' }));
                        }}
                        className={`py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all text-center ${
                          inspSource === 'server' ? 'bg-white text-cyan-700 shadow-2xs' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '🖥️ 主机性能套件' : 'Server Suite'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('script');
                          setForm(f => ({ ...f, commands: '' }));
                        }}
                        className={`py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all text-center ${
                          inspSource === 'script' ? 'bg-white text-cyan-700 shadow-2xs' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '📜 关联巡检脚本' : 'Bound Script'}
                      </button>
                    </div>

                    {inspSource === 'default' && (
                      <p className="text-[11px] text-slate-500 bg-slate-50 p-2.5 rounded-xl border border-slate-100 leading-relaxed">
                        {zh ? '自动根据目标设备厂商（Cisco / Huawei / H3C / Linux 等）匹配内置硬件状态与性能指标并综合打分。' : 'Smart Adaptive: Automatically runs standard metrics matching target device platform.'}
                      </p>
                    )}
                    {inspSource === 'network' && (
                      <p className="text-[11px] text-cyan-800 bg-cyan-50/40 p-2.5 rounded-xl border border-cyan-100 leading-relaxed">
                        {zh ? '网络设备专用巡检：覆盖 CPU、内存、环境温度、风扇电源冗余、接口错包/Flapping 与连通性。' : 'Network Suite: Covers CPU, memory, temperature, PSU/Fan, port errors/flapping, and reachability.'}
                      </p>
                    )}
                    {inspSource === 'server' && (
                      <p className="text-[11px] text-emerald-800 bg-emerald-50/40 p-2.5 rounded-xl border border-emerald-100 leading-relaxed">
                        {zh ? '服务器主机专用巡检：覆盖 CPU Load 负载、内存使用率、磁盘分区空间 (df -h)、关键系统服务与连通性。' : 'Server Suite: Covers CPU load, memory usage, disk storage, system services, and reachability.'}
                      </p>
                    )}
                    {inspSource === 'script' && (
                      <div className="relative">
                        <div className="relative">
                          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                          <input
                            type="text"
                            placeholder={zh ? "搜索巡检脚本..." : "Search inspection scripts..."}
                            value={scriptSearch}
                            onFocus={() => {
                              setShowScriptDropdown(true);
                              if (!scriptSearch) {
                                const current = (availableScripts || []).find(s => s.id === form.script_id);
                                if (current) setScriptSearch(current.name);
                              }
                            }}
                            onChange={(e) => { setScriptSearch(e.target.value); setShowScriptDropdown(true); }}
                            className="w-full pl-10 pr-4 py-2 rounded-xl border border-slate-200 bg-white text-xs focus:ring-2 focus:ring-cyan-500/20 outline-none transition-all"
                          />
                        </div>

                        <AnimatePresence>
                          {showScriptDropdown && (
                            <motion.div
                              initial={{ opacity: 0, y: -4 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0, y: -4 }}
                              className="absolute z-30 left-0 right-0 mt-1.5 bg-white border border-slate-200 rounded-xl shadow-xl max-h-48 overflow-y-auto"
                            >
                              {(() => {
                                const filtered = (availableScripts || []).filter(s => {
                                  const searchVal = scriptSearch.toLowerCase();
                                  return s.name.toLowerCase().includes(searchVal) && s.category === 'inspection';
                                });

                                if (filtered.length === 0) {
                                  return <div className="p-4 text-center text-slate-400 text-xs italic">{zh ? '未找到匹配的巡检脚本' : 'No matching scripts'}</div>;
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
                                      className={`px-4 py-2.5 text-xs cursor-pointer hover:bg-slate-50 transition-all flex items-center justify-between border-b border-slate-100 last:border-0 ${isSelected ? 'bg-cyan-50 text-cyan-700 font-bold' : 'text-slate-600'}`}
                                    >
                                      <span className="flex items-center gap-2">
                                        <FileCode size={13} className="text-emerald-500" />
                                        {s.name}
                                      </span>
                                      <span className="text-[10px] text-slate-400 font-mono">{s.platform}</span>
                                    </div>
                                  );
                                });
                              })()}
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                    )}
                  </div>
                )}

                {/* Sub-Action: Backup & NSOT Notices */}
                {form.action_type === 'backup' && (
                  <div className="p-3 rounded-xl bg-cyan-50/50 border border-cyan-100 text-xs text-cyan-800 flex items-center gap-2">
                    <Database size={15} className="text-cyan-600 shrink-0" />
                    <span>{zh ? '配置备份：自动通过 SSH 获取目标设备当前运行配置并归档版本库。' : 'Runs configuration backup via SSH and archives to version repository.'}</span>
                  </div>
                )}
                {form.action_type === 'nsot' && (
                  <div className="p-3 rounded-xl bg-cyan-50/50 border border-cyan-100 text-xs text-cyan-800 flex items-center gap-2">
                    <RefreshCw size={15} className="text-cyan-600 shrink-0" />
                    <span>{zh ? 'NSOT 事实库：按厂商驱动提取 ARP 表、终端 MAC 位置、路由表、OSPF/BGP 邻居与接口事实数据。' : 'Extracts network reality facts (ARP, routes, neighbors, ports) for targeted devices.'}</span>
                  </div>
                )}

                {/* Sub-Action: Script Run */}
                {form.action_type === 'script_run' && (
                  <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80 space-y-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase text-slate-400">{zh ? '目标资产类型' : 'Asset Category'}</label>
                        <div className="flex items-center gap-1 p-1 bg-white border border-slate-200/80 rounded-xl">
                          <button
                            type="button"
                            onClick={() => {
                              setScriptAssetCategory('network');
                              setScriptProtocolChannel('cli');
                              setForm(f => ({ ...f, script_id: '' }));
                            }}
                            className={`flex-1 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                              scriptAssetCategory === 'network' ? 'bg-cyan-50 text-cyan-700 shadow-2xs' : 'text-slate-500'
                            }`}
                          >
                            <Globe size={13} className="text-cyan-600" />
                            <span>{zh ? '网络设备' : 'Network'}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setScriptAssetCategory('server');
                              setScriptProtocolChannel('shell');
                              setForm(f => ({ ...f, script_id: '' }));
                            }}
                            className={`flex-1 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                              scriptAssetCategory === 'server' ? 'bg-emerald-50 text-emerald-700 shadow-2xs' : 'text-slate-500'
                            }`}
                          >
                            <Server size={13} className="text-emerald-600" />
                            <span>{zh ? '服务器主机' : 'Server'}</span>
                          </button>
                        </div>
                      </div>

                      <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase text-slate-400">{zh ? '协议驱动通道' : 'Protocol Channel'}</label>
                        {scriptAssetCategory === 'network' ? (
                          <div className="flex items-center gap-1 p-1 bg-white border border-slate-200/80 rounded-xl">
                            <button
                              type="button"
                              onClick={() => {
                                setScriptProtocolChannel('cli');
                                setForm(f => ({ ...f, script_id: '' }));
                              }}
                              className={`flex-1 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                                scriptProtocolChannel === 'cli' ? 'bg-cyan-50 text-cyan-700 shadow-2xs' : 'text-slate-500'
                              }`}
                            >
                              <Terminal size={12} className="text-cyan-600" />
                              <span>{zh ? 'SSH / CLI 命令行' : 'SSH / CLI'}</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setScriptProtocolChannel('snmp');
                                setForm(f => ({ ...f, script_id: '' }));
                              }}
                              className={`flex-1 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${
                                scriptProtocolChannel === 'snmp' ? 'bg-indigo-50 text-indigo-700 shadow-2xs' : 'text-slate-500'
                              }`}
                            >
                              <Radio size={12} className="text-indigo-600" />
                              <span>{zh ? 'SNMP 遥测 OID' : 'SNMP OID'}</span>
                            </button>
                          </div>
                        ) : (
                          <div className="p-2 rounded-xl bg-white border border-slate-200/80 text-xs font-semibold text-emerald-800 flex items-center gap-2">
                            <Terminal size={13} className="text-emerald-600" />
                            <span>{zh ? 'Linux Shell (Paramiko SSH Exec / Bash)' : 'Linux Shell'}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="relative pt-1">
                      <div className="relative">
                        <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                        <input
                          type="text"
                          placeholder={zh ? `搜索适用的 ${scriptAssetCategory === 'network' ? '网络' : '服务器'} 脚本...` : 'Search scripts...'}
                          value={scriptSearch}
                          onFocus={() => {
                            setShowScriptDropdown(true);
                            if (!scriptSearch) {
                              const current = (availableScripts || []).find(s => s.id === form.script_id);
                              if (current) setScriptSearch(current.name);
                            }
                          }}
                          onChange={(e) => { setScriptSearch(e.target.value); setShowScriptDropdown(true); }}
                          className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 bg-white text-xs focus:ring-2 focus:ring-cyan-500/20 outline-none transition-all placeholder:text-slate-300"
                        />
                      </div>

                      <AnimatePresence>
                        {showScriptDropdown && (
                          <motion.div
                            initial={{ opacity: 0, y: -4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -4 }}
                            className="absolute z-30 left-0 right-0 mt-1.5 bg-white border border-slate-200 rounded-xl shadow-xl max-h-48 overflow-y-auto"
                          >
                            {filteredScripts.length === 0 ? (
                              <div className="p-4 text-center text-slate-400 text-xs italic">
                                {zh ? '当前分类与协议下暂无匹配的已发布脚本' : 'No matching scripts'}
                              </div>
                            ) : (
                              filteredScripts.map(s => {
                                const isSelected = form.script_id === s.id;
                                return (
                                  <div
                                    key={s.id}
                                    onClick={() => {
                                      setForm(f => ({ ...f, script_id: s.id }));
                                      setScriptSearch(s.name);
                                      setShowScriptDropdown(false);
                                    }}
                                    className={`px-4 py-2.5 text-xs cursor-pointer hover:bg-slate-50 transition-all flex items-center justify-between border-b border-slate-100 last:border-0 ${isSelected ? 'bg-cyan-50 text-cyan-700 font-bold' : 'text-slate-600'}`}
                                  >
                                    <div className="flex items-center gap-2">
                                      <FileCode size={13} className={scriptAssetCategory === 'server' ? 'text-emerald-500' : 'text-cyan-500'} />
                                      <span>{s.name}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5 font-mono text-[10px]">
                                      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{s.platform || 'all'}</span>
                                      {isSelected && <CheckCircle2 size={13} className="text-cyan-600" />}
                                    </div>
                                  </div>
                                );
                              })
                            )}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>
                )}
              </div>

              {/* Block 3: 目标资产范围设定 */}
              <div className="p-6 rounded-2xl bg-white border border-slate-200/90 shadow-2xs space-y-4">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-indigo-500" />
                  <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '目标资产范围' : 'Target Fleet Scope'}</h3>
                </div>

                <div className="space-y-3">
                  <div>
                    <label className="text-xs font-semibold text-slate-600 block mb-1">
                      {zh ? '范围过滤模式' : 'Scope Filter Mode'} <span className="text-rose-500">*</span>
                    </label>
                    <select
                      value={form.device_scope}
                      onChange={e => {
                        setForm(f => ({ ...f, device_scope: e.target.value, device_filter: '' }));
                        setIpInput('');
                      }}
                      className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-xs font-bold text-slate-800 bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 transition-all"
                    >
                      {SCOPE_OPTIONS.map(o => (
                        <option key={o.value} value={o.value}>{zh ? o.labelZh : o.labelEn}</option>
                      ))}
                    </select>
                  </div>

                  {/* Sub-view: Site Select */}
                  {form.device_scope === 'site' && (
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-600 block">{zh ? '选择 CMDB 站点' : 'Select Site'}</label>
                      <select
                        value={form.device_filter}
                        onChange={e => setForm(f => ({ ...f, device_filter: e.target.value }))}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 text-slate-800 font-medium transition-all"
                      >
                        <option value="">{zh ? '请选择 CMDB 站点...' : 'Select site...'}</option>
                        {Object.entries(siteCounts).map(([site, count]) => (
                          <option key={site} value={site}>
                            {site} ({count} {zh ? '台设备' : 'devices'})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Sub-view: Role Select */}
                  {form.device_scope === 'role' && (
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-slate-600 block">{zh ? '选择 CMDB 设备角色' : 'Select Role'}</label>
                      <select
                        value={form.device_filter}
                        onChange={e => setForm(f => ({ ...f, device_filter: e.target.value }))}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 text-slate-800 font-medium transition-all"
                      >
                        <option value="">{zh ? '请选择设备角色...' : 'Select role...'}</option>
                        {Object.entries(roleCounts).map(([role, count]) => (
                          <option key={role} value={role}>
                            {role} ({count} {zh ? '台设备' : 'devices'})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Sub-view: Composite Multi-Criteria */}
                  {form.device_scope === 'composite' && (
                    <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 space-y-2.5">
                      <p className="text-xs text-slate-600 font-medium">{zh ? '资产多维度复合筛选：' : 'Composite matrix filter:'}</p>
                      <div className="grid grid-cols-3 gap-2">
                        <select
                          value={compositeFilter.site || ''}
                          onChange={e => updateCompositeFilter('site', e.target.value)}
                          className="px-2.5 py-2 rounded-xl border border-slate-200 text-xs bg-white focus:ring-2 focus:ring-cyan-500/20 text-slate-700"
                        >
                          <option value="">{zh ? '全部站点' : 'All Sites'}</option>
                          {Object.entries(siteCounts).map(([s, count]) => <option key={s} value={s}>{s} ({count})</option>)}
                        </select>
                        <select
                          value={compositeFilter.role || ''}
                          onChange={e => updateCompositeFilter('role', e.target.value)}
                          className="px-2.5 py-2 rounded-xl border border-slate-200 text-xs bg-white focus:ring-2 focus:ring-cyan-500/20 text-slate-700"
                        >
                          <option value="">{zh ? '全部角色' : 'All Roles'}</option>
                          {Object.entries(roleCounts).map(([r, count]) => <option key={r} value={r}>{r} ({count})</option>)}
                        </select>
                        <select
                          value={compositeFilter.category || ''}
                          onChange={e => updateCompositeFilter('category', e.target.value)}
                          className="px-2.5 py-2 rounded-xl border border-slate-200 text-xs bg-white focus:ring-2 focus:ring-cyan-500/20 text-slate-700"
                        >
                          <option value="">{zh ? '全部类型' : 'All Types'}</option>
                          {Object.entries(categoryCounts).map(([c, count]) => <option key={c} value={c}>{c} ({count})</option>)}
                        </select>
                      </div>
                    </div>
                  )}

                  {/* Sub-view: Compact IP Input */}
                  {form.device_scope === 'ip' && (
                    <div className="space-y-2">
                      <div className="relative">
                        <input
                          type="text"
                          value={ipInput}
                          onChange={e => { setIpInput(e.target.value); setIpError(''); }}
                          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); validateAndAddIps(ipInput); } }}
                          disabled={ipValidating}
                          className="w-full pl-3.5 pr-12 py-2.5 rounded-xl border border-slate-200 text-xs bg-white font-mono focus:ring-2 focus:ring-cyan-500/20"
                          placeholder={zh ? '输入 IP 后回车查询添加' : 'Enter IP and press Enter'}
                        />
                        <button
                          type="button"
                          onClick={() => validateAndAddIps(ipInput)}
                          disabled={!ipInput.trim() || ipValidating}
                          className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-cyan-600 hover:bg-cyan-50"
                        >
                          {ipValidating ? <RotateCcw size={13} className="animate-spin" /> : <Search size={13} />}
                        </button>
                      </div>

                      {ipError && (
                        <p className={`text-[10px] ${ipError.includes('已添加') ? 'text-amber-500' : 'text-rose-500'}`}>{ipError}</p>
                      )}

                      {ipDevices.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 max-h-28 overflow-y-auto p-2 rounded-xl bg-slate-50 border border-slate-200">
                          {ipDevices.map(dev => (
                            <span
                              key={dev.ip}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white border border-slate-200 text-xs font-mono text-slate-700 shadow-2xs"
                            >
                              <span className="font-bold">{dev.ip}</span>
                              {dev.hostname && <span className="text-slate-400">({dev.hostname})</span>}
                              <button
                                type="button"
                                onClick={() => removeIpDevice(dev.ip)}
                                className="text-slate-400 hover:text-rose-500 ml-0.5"
                              >
                                <X size={12} />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Sub-view: Tag Picker */}
                  {form.device_scope === 'tag' && (
                    <div className="p-3.5 rounded-2xl bg-white border border-slate-200">
                      <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* ═══════════════════════════════════════════════════════════════════
                RIGHT COLUMN (44% / 5 cols): 实时资产大盘 & 调度控制
               ═══════════════════════════════════════════════════════════════════ */}
            <div className="lg:col-span-5 space-y-5">
              
              {/* Card 1: 🎯 实时匹配目标资产大盘 */}
              <div className="p-6 rounded-2xl bg-white border border-slate-200/90 shadow-2xs space-y-3.5">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2">
                    <Target size={16} className="text-cyan-600" />
                    <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '实时匹配目标资产' : 'Matching Fleet'}</h3>
                  </div>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-cyan-100 text-cyan-800 font-mono">
                    {matchedDevices.length} {zh ? '台设备' : 'devs'}
                  </span>
                </div>

                {/* Status Bar */}
                <div className="flex items-center justify-between text-xs bg-slate-50 px-3 py-2 rounded-xl border border-slate-100">
                  <span className="flex items-center gap-1.5 text-emerald-600 font-bold">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    {onlineCount} {zh ? '台在线 (就绪)' : 'online'}
                  </span>
                  {matchedDevices.length - onlineCount > 0 && (
                    <span className="flex items-center gap-1.5 text-slate-400 font-medium">
                      <span className="w-2 h-2 rounded-full bg-slate-300" />
                      {matchedDevices.length - onlineCount} {zh ? '台离线' : 'offline'}
                    </span>
                  )}
                </div>

                {/* Platform Breakdown Badges */}
                {Object.keys(platformBreakdown).length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {Object.entries(platformBreakdown).map(([platform, count]) => (
                      <span key={platform} className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg bg-slate-100 text-[10px] text-slate-700 font-mono">
                        <span className="font-bold text-slate-900">{platform}</span>: {count}
                      </span>
                    ))}
                  </div>
                )}

                {/* Incompatible Warning */}
                {scriptIncompatibleCount > 0 && (
                  <div className="flex items-start gap-2 p-2.5 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800">
                    <AlertTriangle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                    <span>
                      {zh 
                        ? `提示：当前脚本限定平台为 [${selectedScript?.platform}]，其中 ${scriptIncompatibleCount} 台不兼容设备将被跳过。` 
                        : `Warning: ${scriptIncompatibleCount} devices incompatible with [${selectedScript?.platform}].`}
                    </span>
                  </div>
                )}

                {/* Quick Search inside preview */}
                <div className="relative">
                  <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    value={deviceSearchQuery}
                    onChange={e => setDeviceSearchQuery(e.target.value)}
                    placeholder={zh ? "在命中结果中快速搜索..." : "Filter matched devices..."}
                    className="w-full pl-8 pr-3 py-1.5 rounded-xl border border-slate-200 text-xs bg-slate-50/50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
                  />
                </div>

                {/* Device Stream Box */}
                <div className="rounded-xl border border-slate-100 bg-slate-50/40 p-2 space-y-1 max-h-52 overflow-y-auto custom-scrollbar">
                  {displayedMatchedDevices.length === 0 ? (
                    <div className="py-8 text-center text-xs text-slate-400 italic">
                      {zh ? '暂无匹配设备，请调整左侧范围过滤条件' : 'No devices match current filter'}
                    </div>
                  ) : (
                    displayedMatchedDevices.map(dev => (
                      <div key={dev.id || dev.ip_address} className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-white border border-slate-100 text-xs shadow-2xs">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={`w-2 h-2 rounded-full shrink-0 ${dev.status === 'online' || dev.is_active === 1 || dev.ping_status === 'up' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                          <span className="font-bold text-slate-800 truncate">{dev.hostname || dev.ip_address}</span>
                          <span className="text-slate-400 font-mono text-[11px]">({dev.ip_address})</span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0 text-[11px] text-slate-500 font-mono">
                          {dev.site && <span className="px-1.5 py-0.2 rounded bg-slate-100 text-slate-600">{dev.site}</span>}
                          <span className="text-cyan-700 font-semibold">{dev.platform || 'generic'}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Card 2: ⏰ Cron 调度周期与执行时间 */}
              <div className="p-6 rounded-2xl bg-white border border-slate-200/90 shadow-2xs space-y-3.5">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2">
                    <Clock size={16} className="text-cyan-600" />
                    <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? 'Cron 调度周期' : 'Cron Schedule'}</h3>
                  </div>

                  {/* Preset Dropdown Trigger */}
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setPresetOpen(!presetOpen)}
                      className="inline-flex items-center gap-1 text-xs font-bold text-cyan-600 hover:text-cyan-700 transition-colors"
                    >
                      <Zap size={12} className="text-amber-500" />
                      <span>{zh ? '常用预设' : 'Presets'}</span>
                      <ChevronDown size={12} />
                    </button>

                    <AnimatePresence>
                      {presetOpen && (
                        <motion.div
                          initial={{ opacity: 0, y: -4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -4 }}
                          className="absolute right-0 z-30 mt-1.5 w-60 rounded-xl border border-slate-200 bg-white shadow-xl overflow-hidden max-h-56 overflow-y-auto"
                        >
                          {CRON_PRESETS.map(p => (
                            <button
                              type="button"
                              key={p.cron}
                              onClick={() => {
                                setForm(f => ({ ...f, cron_expr: p.cron }));
                                setPresetOpen(false);
                              }}
                              className={`flex w-full items-center justify-between px-3.5 py-2 text-xs transition-colors hover:bg-cyan-50 ${form.cron_expr === p.cron ? 'bg-cyan-50 text-cyan-700 font-bold' : 'text-slate-600'}`}
                            >
                              <span>{zh ? p.label : p.labelEn}</span>
                              <code className="text-[10px] font-mono text-slate-400">{p.cron}</code>
                            </button>
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </div>

                {/* 5-Field Editor */}
                <div className="grid grid-cols-5 gap-1.5">
                  {cronFields.map((val, idx) => (
                    <div key={idx}>
                      <input
                        type="text"
                        value={val}
                        onChange={e => updateCronField(idx, e.target.value)}
                        className="w-full text-center py-2 rounded-xl border border-slate-200 text-xs font-mono font-bold bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 transition-all text-slate-800"
                        placeholder="*"
                      />
                      <span className="text-[9px] text-slate-400 block text-center mt-0.5">
                        {zh ? CRON_FIELD_LABELS_ZH[idx] : CRON_FIELD_LABELS_EN[idx]}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="text-xs text-cyan-700 font-medium text-center bg-cyan-50/70 py-1 rounded-xl border border-cyan-100">
                  {describeCron(form.cron_expr, zh)}
                </div>
              </div>

              {/* Card 3: 🛡️ 安全审批授权 */}
              <div className="p-6 rounded-2xl bg-white border border-slate-200/90 shadow-2xs space-y-3.5">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2">
                    <Shield size={16} className="text-cyan-600" />
                    <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '安全审批授权' : 'Approval Gate'}</h3>
                  </div>
                  {approvalStatus === 'verified' && (
                    <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-100">
                      <Check size={12} />
                      {zh ? '已授权通过' : 'Verified'}
                    </span>
                  )}
                </div>

                <div className="space-y-2">
                  <select
                    value={approverUsername}
                    onChange={e => setApproverUsername(e.target.value)}
                    disabled={approvalStatus === 'verified'}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-xs bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 text-slate-700 font-medium transition-all"
                  >
                    <option value="">{zh ? '请选择安全审批人...' : 'Select approver...'}</option>
                    {approvers.map(a => (
                      <option key={a.id} value={a.username}>{a.username} ({a.role})</option>
                    ))}
                  </select>

                  {approverUsername && approvalStatus !== 'verified' && (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={approvalCode}
                        onChange={e => setApprovalCode(e.target.value)}
                        placeholder={zh ? '输入 6 位验证码' : 'Enter 6-digit code'}
                        className="flex-1 px-3 py-2 rounded-xl border border-slate-200 text-xs font-mono bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
                      />
                      <button
                        type="button"
                        onClick={approvalStatus === 'sent' ? verifyApproval : requestApproval}
                        disabled={approvalStatus === 'sending' || (approvalStatus === 'sent' && !approvalCode.trim())}
                        className="px-4 py-2 rounded-xl text-xs font-bold bg-slate-800 text-white hover:bg-slate-900 transition-all disabled:opacity-40 shrink-0"
                      >
                        {approvalStatus === 'sent'
                          ? (zh ? '确认' : 'Verify')
                          : approvalCountdown > 0
                          ? `${approvalCountdown}s`
                          : (zh ? '获取验证码' : 'Get Code')}
                      </button>
                    </div>
                  )}

                  {approvalError && (
                    <p className="text-[10px] text-rose-500 leading-tight">{approvalError}</p>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════════════
              FOOTER: 全局就绪状态栏与提交按钮
             ═══════════════════════════════════════════════════════════════════ */}
          <div className="px-8 py-4 bg-white border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Sparkles size={14} className="text-cyan-600" />
              <span>
                {zh 
                  ? `当前配置：面向 ${matchedDevices.length} 台设备 (${onlineCount} 在线)，按周期 [${describeCron(form.cron_expr, zh)}] 调度执行` 
                  : `Target: ${matchedDevices.length} devices, Schedule: ${describeCron(form.cron_expr, zh)}`}
              </span>
            </div>

            <div className="flex items-center gap-3 w-full sm:w-auto justify-end">
              <button
                type="button"
                onClick={onClose}
                className="px-5 py-2.5 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition-all"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              <button
                type="submit"
                disabled={!isFormReady}
                className="flex items-center gap-2 px-8 py-2.5 rounded-xl text-xs font-bold bg-gradient-to-r from-cyan-500 via-sky-600 to-blue-600 text-white hover:from-cyan-400 hover:to-blue-500 transition-all shadow-md shadow-cyan-500/20 disabled:opacity-40 disabled:cursor-not-allowed active:scale-98"
              >
                <CheckCircle2 size={16} />
                {isEditMode ? (zh ? '保存配置修改' : 'Save Changes') : (zh ? '创建并启用定时作业' : 'Create & Enable Job')}
              </button>
            </div>
          </div>
        </form>
      </motion.div>
    </AnimatePresence>
  );
};
