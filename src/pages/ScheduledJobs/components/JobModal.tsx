import React, { useState, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, X, Zap, ChevronDown, Search, FileCode, CheckCircle2,
  Trash2, RotateCcw, Database, Activity, RefreshCw,
  Target, Globe, Server, Check, Terminal, Radio, ChevronRight,
  Sparkles, Layers, Sliders, ShieldCheck, CheckCheck
} from 'lucide-react';
import TagConditionPicker, { hasTagFilterConditions, type TagFilterConfig } from '../../../components/TagConditionPicker';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import { FormActionBar, FormSection } from '../../../components/ui/FormLayout';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import CountdownText from './CountdownText';
import { ScheduledJob, EligibleApprover, FormState, ValidatedDevice, type ApprovalVerificationMethod, type CollectionPlanFilters } from '../types';
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
  approverLoadStatus: 'idle' | 'loading' | 'loaded' | 'error';
  refreshApprovers: () => void;
  approvalMethod: ApprovalVerificationMethod;
  setApprovalMethod: (val: ApprovalVerificationMethod) => void;
  approvalStatus: 'idle' | 'sending' | 'sent' | 'verifying' | 'verified';
  approvalCountdown: number;
  approvalDeadline: number;
  onApprovalCountdownExpire: () => void;
  approvalCode: string;
  setApprovalCode: (val: string) => void;
  approvalError: string;
  setApprovalError: (val: string) => void;
  requestApproval: () => void;
  verifyApproval: (code?: string) => void;
  fetchCronPreview: (cronExpr: string, signal: AbortSignal) => Promise<string[]>;
  submitForm: () => void;
  language: string;
  devices?: any[];
  deviceLoadStatus: 'idle' | 'loading' | 'loaded' | 'error';
  refreshDevices: () => void;
}

const getDeviceCategory = (device: { category?: string | null; device_category?: string | null; role?: string | null }): string =>
  device.category || device.device_category || (device.role?.toLowerCase().includes('server') ? 'Server' : 'Network');

const normalizeScriptPlatformFamily = (value?: string | null): string => {
  const platform = String(value || '').toLowerCase().trim().replace(/[\s.-]+/g, '_');
  const linuxPlatforms = ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'rhel', 'rocky', 'alma', 'almalinux', 'oracle_linux', 'oraclelinux', 'fedora', 'suse', 'opensuse'];
  if (linuxPlatforms.some(alias => platform === alias || platform.startsWith(`${alias}_`) || platform.startsWith(`${alias}v`))) return 'linux';
  if (platform === 'win' || platform.includes('windows') || platform.includes('winrm')) return 'windows';
  return platform;
};

const areScriptPlatformsCompatible = (devicePlatform: string, requiredPlatform: string): boolean => {
  const deviceKey = String(devicePlatform || '').toLowerCase().trim();
  const requiredKey = String(requiredPlatform || '').toLowerCase().trim();
  return normalizeScriptPlatformFamily(deviceKey) === normalizeScriptPlatformFamily(requiredKey)
    || deviceKey.includes(requiredKey)
    || requiredKey.includes(deviceKey);
};

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
  approverLoadStatus,
  refreshApprovers,
  approvalMethod,
  setApprovalMethod,
  approvalStatus,
  approvalCountdown,
  approvalDeadline,
  onApprovalCountdownExpire,
  approvalCode,
  setApprovalCode,
  approvalError,
  setApprovalError,
  requestApproval,
  verifyApproval,
  fetchCronPreview,
  submitForm,
  language,
  devices = [],
  deviceLoadStatus,
  refreshDevices,
}) => {
  const zh = language === 'zh';
  useEscapeClose(isOpen && approvalStatus !== 'sending' && approvalStatus !== 'verifying', onClose);
  const selectedApprover = approvers.find(item => item.username === approverUsername);
  const availableApprovalMethods = selectedApprover?.verification_methods || [];

  const verificationMethodLabel = (method: ApprovalVerificationMethod) => {
    if (method === 'mfa') return zh ? 'MFA 动态码' : 'MFA code';
    if (method === 'email') return zh ? '邮箱验证码' : 'Email code';
    return zh ? '飞书验证码' : 'Feishu code';
  };

  // Sub-states for Inspection
  const [inspSource, setInspSource] = useState<'default' | 'network' | 'server' | 'script'>('default');

  // Sub-states for Script Run
  const [scriptAssetCategory, setScriptAssetCategory] = useState<'network' | 'server'>('network');
  const [scriptProtocolChannel, setScriptProtocolChannel] = useState<'cli' | 'snmp' | 'shell'>('cli');
  
  const [flowStep, setFlowStep] = useState(0);
  const [cronOccurrences, setCronOccurrences] = useState<string[]>([]);
  const [cronPreviewStatus, setCronPreviewStatus] = useState<'idle' | 'loading' | 'loaded' | 'invalid' | 'error'>('idle');
  const [cronPreviewError, setCronPreviewError] = useState('');
  const [cronPreviewRetry, setCronPreviewRetry] = useState(0);

  React.useEffect(() => {
    if (isOpen) setFlowStep(0);
  }, [isOpen]);

  React.useEffect(() => {
    if (!isOpen || flowStep !== 1) {
      setCronPreviewStatus('idle');
      return;
    }

    const expression = form.cron_expr.trim();
    if (expression.split(/\s+/).length !== 5) {
      setCronPreviewStatus('invalid');
      setCronPreviewError(zh ? 'Cron 表达式需要包含 5 个字段。' : 'A cron expression must contain 5 fields.');
      return;
    }

    const controller = new AbortController();
    setCronPreviewError('');
    setCronPreviewStatus('loading');
    const timeout = window.setTimeout(() => {
      void fetchCronPreview(expression, controller.signal)
        .then(occurrences => {
          if (controller.signal.aborted) return;
          setCronOccurrences(occurrences.slice(0, 10));
          setCronPreviewStatus('loaded');
        })
        .catch(error => {
          if (controller.signal.aborted) return;
          const status = (error as { status?: number })?.status;
          setCronPreviewStatus(status === 400 || status === 422 ? 'invalid' : 'error');
          setCronPreviewError(error instanceof Error ? error.message : (zh ? '无法预览执行时间。' : 'Unable to preview execution times.'));
        });
    }, 250);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [isOpen, flowStep, form.cron_expr, fetchCronPreview, cronPreviewRetry, zh]);

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
      const c = getDeviceCategory(d);
      counts[c] = (counts[c] || 0) + 1;
    });
    return counts;
  }, [devices]);

  const platformCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    (devices || []).forEach(d => {
      const platform = d.platform || '';
      if (platform) counts[platform] = (counts[platform] || 0) + 1;
    });
    return counts;
  }, [devices]);

  // Parse composite filter
  const compositeFilter = useMemo(() => {
    if (form.device_scope !== 'composite') return {} as CollectionPlanFilters;
    try {
      const parsed: unknown = JSON.parse(form.device_filter || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {} as CollectionPlanFilters;
      const values = parsed as Record<string, unknown>;
      return {
        site: typeof values.site === 'string' ? values.site : '',
        role: typeof values.role === 'string' ? values.role : '',
        category: typeof values.category === 'string' ? values.category : '',
        platform: typeof values.platform === 'string' ? values.platform : '',
      };
    } catch {
      return {} as CollectionPlanFilters;
    }
  }, [form.device_scope, form.device_filter]);

  const hasCompositeFilter = Object.values(compositeFilter).some(value => String(value || '').trim());

  const updateCompositeFilter = (key: keyof CollectionPlanFilters, val: string) => {
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
        if (compositeFilter.category && getDeviceCategory(d) !== compositeFilter.category) return false;
        if (compositeFilter.platform && (d.platform || '') !== compositeFilter.platform) return false;
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
      const ips = new Set(ipDevices.map(d => String(d.ip || '').trim()));
      return all.filter(d => ips.has(String(d.ip_address || '').trim()));
    }
    return all;
  }, [devices, form.device_scope, form.device_filter, compositeFilter, ipDevices]);

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
      const platform = String(d.platform || '').toLowerCase().trim();
      return platform && !areScriptPlatformsCompatible(platform, reqPlatform);
    }).length;
  }, [selectedScript, matchedDevices]);

  if (!isOpen) return null;

  const isTaskReady = (() => {
    if (!form.name.trim() || !form.action_type) return false;
    if (form.action_type === 'command' && !form.commands.trim()) return false;
    if (form.action_type === 'script_run' && !form.script_id.trim()) return false;
    if (form.is_config && !form.config_reason.trim()) return false;
    if (form.action_type === 'inspection' && (inspSource === 'script' || form.script_id.trim())) return false;
    return true;
  })();

  const isScopeReady = (() => {
    if (!form.device_scope) return false;
    if (form.device_scope === 'ip' && ipDevices.length === 0) return false;
    if (form.device_scope === 'composite' && !hasCompositeFilter) return false;
    if (form.device_scope === 'tag') {
      if (!hasTagFilterConditions(tagFilter)) return false;
    }
    if ((form.device_scope === 'site' || form.device_scope === 'role') && !form.device_filter.trim()) return false;
    return true;
  })();

  const cronParts = form.cron_expr.trim().split(/\s+/);
  const isScheduleReady = cronParts.length === 5 && cronParts.every(Boolean);
  const isTaskAndTargetReady = isTaskReady && isScopeReady;
  const isFormReady = isTaskAndTargetReady && isScheduleReady;
  const flowStepLabels = zh ? ['任务与目标', '调度与审批'] : ['Task & targets', 'Schedule & approval'];
  const actionLabel = ACTION_TYPES.find(action => action.value === form.action_type);
  const scopeLabel = SCOPE_OPTIONS.find(scope => scope.value === form.device_scope);
  const canAdvance = flowStep === 0 && isTaskAndTargetReady;

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
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/45 p-2 sm:p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="scheduled-job-form-title"
      >
        <motion.div
          initial={{ opacity: 0, y: 10, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.985 }}
          className="flex max-h-[min(860px,calc(100dvh-1rem))] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl sm:max-h-[min(860px,calc(100dvh-2rem))] sm:rounded-3xl"
        >
        <div className="h-1 shrink-0 bg-gradient-to-r from-cyan-500 via-sky-500 to-blue-600" />

        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 bg-white px-4 py-3 sm:px-5">
          <div className="flex items-center gap-3.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-100 bg-cyan-50 text-cyan-600 shadow-sm">
              <CalendarClock size={19} />
            </div>
            <div>
              <h2 id="scheduled-job-form-title" className="text-sm font-bold tracking-tight text-slate-900 sm:text-base">
                {isEditMode ? (zh ? '编辑周期性定时作业' : 'Edit Scheduled Job') : (zh ? '创建周期性定时作业' : 'Create Scheduled Job')}
              </h2>
              <p className="mt-0.5 hidden text-[11px] text-slate-400 sm:block">
                {zh ? '配置执行动作、调度周期与目标设备，实现全网巡检、备份与自动化执行' : 'Configure strategy, schedule, and target fleet for network automation'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={zh ? '关闭作业配置' : 'Close job setup'}
            disabled={approvalStatus === 'sending' || approvalStatus === 'verifying'}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40"
          >
            <X size={18} />
          </button>
        </div>

        {/* The form body scrolls inside the compact dialog while the header and actions stay visible. */}
        <form className="flex min-h-0 flex-1 flex-col overflow-hidden" onSubmit={e => {
          e.preventDefault();
          if (flowStep === 0) {
            if (canAdvance) setFlowStep(step => step + 1);
            return;
          }
          if (isFormReady && approvalStatus === 'verified') submitForm();
        }}>
          <div className="shrink-0 bg-white px-3 pt-3 sm:px-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" aria-label={zh ? '作业创建步骤' : 'Job setup steps'}>
              {flowStepLabels.map((label, index) => {
                const isCurrent = flowStep === index;
                const isComplete = flowStep > index;
                return (
                  <button
                    key={label}
                    type="button"
                    onClick={() => { if (index < flowStep) setFlowStep(index); }}
                    disabled={index >= flowStep}
                    className={`flex items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition-colors ${
                      isCurrent ? 'border-cyan-200 bg-cyan-50 text-cyan-800' :
                      isComplete ? 'border-emerald-100 bg-emerald-50/60 text-emerald-700 hover:bg-emerald-50' :
                      'border-slate-100 bg-slate-50 text-slate-400'
                    }`}
                    aria-current={isCurrent ? 'step' : undefined}
                  >
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                      isCurrent ? 'bg-cyan-600 text-white' : isComplete ? 'bg-emerald-500 text-white' : 'bg-slate-200 text-slate-500'
                    }`}>
                      {isComplete ? <Check size={13} /> : index + 1}
                    </span>
                    <span className="text-xs font-semibold">{label}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-1 content-start gap-3 overflow-y-auto overscroll-contain bg-slate-50/40 p-3 sm:gap-4 sm:p-4 lg:grid-cols-12">
            
            {/* ═══════════════════════════════════════════════════════════════════
                Task setup and targets share a row on desktop.
               ═══════════════════════════════════════════════════════════════════ */}
            {flowStep === 0 ? (
            <div className="grid min-w-0 items-start gap-3 md:grid-cols-2 lg:col-span-12 sm:gap-4">
              <div className="min-w-0 space-y-4 rounded-2xl border border-slate-200/90 bg-white p-4 shadow-2xs">
              
              {/* Block 1: 基本属性 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-cyan-500" />
                  <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '基本信息' : 'Basic Info'}</h3>
                </div>

                <div className="space-y-1.5">
                  <label htmlFor="scheduled-job-name" className="text-xs font-semibold text-slate-600 block">
                    {zh ? '作业名称' : 'Job Name'} <span className="text-rose-500">*</span>
                  </label>
                  <input
                    id="scheduled-job-name"
                    type="text"
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full px-4 py-2.5 rounded-xl border border-slate-200 text-xs font-medium text-slate-800 bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 transition-all placeholder:text-slate-300"
                    placeholder={zh ? '例如：每日凌晨核心交换机巡检' : 'e.g. Daily Core Switch Health Inspection'}
                  />
                </div>
              </div>

              {/* Block 2: 执行动作与驱动协议 */}
              <div className="space-y-3 border-t border-slate-100 pt-3">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-blue-500" />
                  <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">{zh ? '执行动作与驱动策略' : 'Action & Driver Strategy'}</h3>
                </div>

                {/* Action Types */}
                <div className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 sm:grid-cols-3 xl:grid-cols-5 [&>button]:whitespace-nowrap [&>button]:text-[11px] [&>button>svg]:shrink-0">
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'inspection', major_type: 'collection', commands: '', script_id: '', is_config: false, config_reason: '', use_admin_creds: false }));
                      setApproverUsername('');
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
                      setForm(f => ({ ...f, action_type: 'backup', major_type: 'collection', commands: '', script_id: '', is_config: false, config_reason: '', use_admin_creds: false }));
                      setApproverUsername('');
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
                        config_reason: '',
                        use_admin_creds: false,
                      }));
                      setApproverUsername('');
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
                      setForm(f => ({ ...f, action_type: 'command', major_type: 'change', commands: '', script_id: '', is_config: false, config_reason: '', use_admin_creds: false }));
                      setApproverUsername('');
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${form.action_type === 'command' ? 'bg-white shadow-2xs text-cyan-700' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    <Terminal className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '命令执行' : 'Command'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'script_run', major_type: 'change', commands: '', script_id: '', is_config: false, config_reason: '', use_admin_creds: false }));
                      setApproverUsername('');
                      fetchScripts();
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${form.action_type === 'script_run' ? 'bg-white shadow-2xs text-cyan-700' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    <FileCode className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? '脚本执行' : 'Script Run'}
                  </button>
                </div>
                {(form.action_type === 'command' || form.action_type === 'script_run') && (
                <div className="flex items-start gap-2 text-[11px] leading-relaxed text-amber-700">
                  <ShieldCheck size={14} className="mt-0.5 shrink-0 text-amber-600" />
                  <span>
                    {zh
                      ? '按周期重复执行，需由其他审批人验证；内容与脚本发布版本绑定，修改后须重新审批。'
                      : 'Runs on schedule with approval from another user. Content and released script versions are pinned; changes require re-approval.'}
                  </span>
                </div>
                )}

                {/* Sub-Action: Inspection */}
                {form.action_type === 'inspection' && (
                  <div className="space-y-3 pt-1">
                    <div className="p-1 bg-slate-50 rounded-xl grid grid-cols-2 sm:grid-cols-4 gap-1 border border-slate-200/70">
                      <button
                        type="button"
                        onClick={() => {
                          setInspSource('default');
                          setForm(f => ({ ...f, script_id: '', commands: '', is_config: false }));
                          setApproverUsername('');
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
                          setForm(f => ({ ...f, script_id: '', commands: 'cpu,memory,temperature,fan,psu,interface_errors,interface_flapping,reachability', is_config: false }));
                          setApproverUsername('');
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
                          setForm(f => ({ ...f, script_id: '', commands: 'cpu,memory,disk,loadavg,system_services,reachability', is_config: false }));
                          setApproverUsername('');
                        }}
                        className={`py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all text-center ${
                          inspSource === 'server' ? 'bg-white text-cyan-700 shadow-2xs' : 'text-slate-500 hover:text-slate-800'
                        }`}
                      >
                        {zh ? '🖥️ 主机性能套件' : 'Server Suite'}
                      </button>
                      <button
                        type="button"
                        disabled
                        title={zh ? '定时作业暂不支持关联脚本；请选择内置巡检套件' : 'Scheduled jobs do not support attached scripts; choose a built-in inspection suite'}
                        onClick={() => {
                          setInspSource('script');
                          setForm(f => ({ ...f, commands: '' }));
                        }}
                        className="py-1.5 px-2 rounded-lg text-[11px] font-bold transition-all text-center text-slate-400 cursor-not-allowed"
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
                            type="search"
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
                  <div className="flex items-start gap-2 text-[11px] leading-relaxed text-slate-500">
                    <Database size={15} className="text-cyan-600 shrink-0" />
                    <span>{zh ? '通过 SSH 采集运行配置，自动归档至版本库。' : 'Collects running configurations via SSH and archives each version.'}</span>
                  </div>
                )}
                {form.action_type === 'nsot' && (
                  <div className="flex items-start gap-2 text-[11px] leading-relaxed text-slate-500">
                    <RefreshCw size={15} className="text-cyan-600 shrink-0" />
                    <span>{zh ? '按设备模板只读采集所选范围内的在线设备，写入 NSOT 事实库。' : 'Collects online targets using their read-only templates and updates NSOT facts.'}</span>
                  </div>
                )}

                {form.action_type === 'command' && (
                  <div className="space-y-1.5">
                    <label htmlFor="scheduled-job-commands" className="text-[11px] font-semibold text-slate-600">
                      {zh ? '执行命令' : 'Commands'} <span className="text-rose-500">*</span>
                    </label>
                    <textarea
                      id="scheduled-job-commands"
                      rows={4}
                      value={form.commands}
                      onChange={event => setForm(current => ({ ...current, commands: event.target.value }))}
                      placeholder={zh ? '每行一条命令' : 'Enter one command per line'}
                      className="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2.5 font-mono text-xs text-slate-800 outline-none transition focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20"
                    />
                    <p className="text-[10px] leading-relaxed text-slate-500">
                      {zh ? '命令将按上方目标范围和 Cron 周期执行，每次运行都会记录结果。' : 'Commands run against the selected targets on this schedule, with every run recorded.'}
                    </p>
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
                          type="search"
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

                {(form.action_type === 'command' || form.action_type === 'script_run') && (
                  <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3">
                    <label className="flex cursor-pointer items-start gap-2.5 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={form.is_config}
                        onChange={event => setForm(current => ({
                          ...current,
                          is_config: event.target.checked,
                          config_reason: event.target.checked ? current.config_reason : '',
                        }))}
                        className="mt-0.5 h-3.5 w-3.5 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                      />
                      <span>
                        <span className="font-semibold">{zh ? '标记为配置变更' : 'Mark as a configuration change'}</span>
                        <span className="mt-0.5 block text-[10px] leading-relaxed text-slate-500">
                          {zh ? '配置变更需填写原因并纳入本次审批清单。' : 'Configuration changes require a reason and are included in the approval manifest.'}
                        </span>
                      </span>
                    </label>
                    {form.is_config && (
                      <textarea
                        rows={2}
                        value={form.config_reason}
                        onChange={event => setForm(current => ({ ...current, config_reason: event.target.value }))}
                        placeholder={zh ? '填写配置变更原因' : 'Enter the configuration change reason'}
                        className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20"
                      />
                    )}
                  </div>
                )}
              </div>

              </div>

              {/* Block 3: 目标资产范围设定 */}
              <FormSection
                title={zh ? '目标资产范围' : 'Target Fleet Scope'}
                className="min-w-0 !mt-0 !rounded-2xl !border-slate-200/90 !bg-white shadow-2xs"
                contentClassName="!space-y-3 !p-4"
              >

                {deviceLoadStatus === 'loading' || deviceLoadStatus === 'idle' ? (
                  <p className="rounded-xl bg-slate-50 px-3 py-2 text-[11px] text-slate-500">{zh ? '正在加载设备清单，加载完成后可继续。' : 'Loading the device inventory. Continue when it finishes.'}</p>
                ) : deviceLoadStatus === 'error' ? (
                  <div className="flex items-center justify-between gap-3 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-[11px] text-rose-700" role="alert">
                    <span>{zh ? '设备清单加载失败，可能是登录状态或权限问题。' : 'The inventory failed to load. Check your session or permissions.'}</span>
                    <button type="button" onClick={refreshDevices} className="shrink-0 font-semibold underline">{zh ? '重试' : 'Retry'}</button>
                  </div>
                ) : null}

                <div className="space-y-3">
                  <div>
                    <label htmlFor="scheduled-job-scope" className="text-xs font-semibold text-slate-600 block mb-1">
                      {zh ? '范围过滤模式' : 'Scope Filter Mode'} <span className="text-rose-500">*</span>
                    </label>
                    <select
                      id="scheduled-job-scope"
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
                      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
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
                        <select
                          value={compositeFilter.platform || ''}
                          onChange={e => updateCompositeFilter('platform', e.target.value)}
                          className="px-2.5 py-2 rounded-xl border border-slate-200 text-xs bg-white focus:ring-2 focus:ring-cyan-500/20 text-slate-700"
                        >
                          <option value="">{zh ? '全部平台' : 'All Platforms'}</option>
                          {Object.entries(platformCounts).map(([platform, count]) => <option key={platform} value={platform}>{platform} ({count})</option>)}
                        </select>
                      </div>
                      {!hasCompositeFilter && (
                        <p className="text-[11px] text-amber-700">
                          {zh ? '至少选择一个筛选条件；否则可能意外覆盖全部设备。' : 'Choose at least one filter to avoid unintentionally targeting every device.'}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Sub-view: IP lookup and selected targets */}
                  {form.device_scope === 'ip' && (
                    <div className="space-y-3">
                      <div className="space-y-1.5">
                        <label htmlFor="scheduled-job-ip-search" className="block text-xs font-semibold text-slate-600">
                          {zh ? '查找目标设备' : 'Find target devices'}
                        </label>
                      <div className="flex gap-2">
                        <input
                          id="scheduled-job-ip-search"
                          type="text"
                          value={ipInput}
                          onChange={e => { setIpInput(e.target.value); setIpError(''); }}
                          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); validateAndAddIps(ipInput); } }}
                          disabled={ipValidating}
                          aria-describedby="scheduled-job-ip-hint"
                          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 font-mono text-xs text-slate-800 outline-none focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/20 disabled:bg-slate-50"
                          placeholder={zh ? 'IP / 设备名，支持批量输入' : 'IP / hostname, multiple allowed'}
                        />
                        <button
                          type="button"
                          onClick={() => validateAndAddIps(ipInput)}
                          disabled={!ipInput.trim() || ipValidating}
                          className="flex shrink-0 items-center justify-center gap-1.5 rounded-xl bg-cyan-700 px-3 text-xs font-semibold text-white transition-colors hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {ipValidating ? <RotateCcw size={13} className="animate-spin" /> : <Search size={13} />}
                          {ipValidating ? (zh ? '查询中' : 'Searching') : (zh ? '查找' : 'Find')}
                        </button>
                      </div>
                        <p id="scheduled-job-ip-hint" className="text-[11px] leading-relaxed text-slate-400">
                          {zh ? '多个目标用逗号或空格分隔，查询后勾选添加。' : 'Separate targets with commas or spaces, then select matches to add.'}
                        </p>
                      </div>

                      {ipError && (
                        <p role="alert" className={`text-[11px] ${ipError.includes('已添加') ? 'text-amber-600' : 'text-rose-600'}`}>{ipError}</p>
                      )}

                      <div className="overflow-hidden rounded-xl border border-slate-200">
                        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-3 py-2 text-[11px]">
                          <span className="font-semibold text-slate-600">{zh ? '已选目标' : 'Selected targets'}</span>
                          <span className="font-semibold tabular-nums text-cyan-700" aria-live="polite">{zh ? `${ipDevices.length} 台` : `${ipDevices.length} devices`}</span>
                        </div>
                        {ipDevices.length > 0 ? (
                        <div className="max-h-52 divide-y divide-slate-100 overflow-y-auto overscroll-contain">
                          {ipDevices.map(dev => (
                            <div
                              key={dev.ip}
                              className="flex min-w-0 items-center gap-2 px-3 py-2 text-xs"
                            >
                              <span className="min-w-0 flex-1 break-all font-mono font-semibold text-slate-700">{dev.ip}</span>
                              {dev.hostname && <span className="min-w-0 flex-1 truncate text-slate-500" title={dev.hostname}>{dev.hostname}</span>}
                              <button
                                type="button"
                                onClick={() => removeIpDevice(dev.ip)}
                                aria-label={zh ? `移除 ${dev.ip}` : `Remove ${dev.ip}`}
                                className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600"
                              >
                                <X size={12} />
                              </button>
                            </div>
                          ))}
                        </div>
                        ) : (
                          <div className="flex items-center justify-center gap-2 px-3 py-5 text-[11px] text-slate-400">
                            <Target size={15} />
                            {zh ? '查找并添加本次作业的目标设备' : 'Find and add devices for this job'}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Sub-view: Tag Picker */}
                  {form.device_scope === 'tag' && (
                    <div className="p-3.5 rounded-2xl bg-white border border-slate-200">
                      <TagConditionPicker value={tagFilter} onChange={setTagFilter} language={language} />
                    </div>
                  )}
                </div>
              </FormSection>
            </div>
            ) : (
              <div className="lg:col-span-12 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-2xs">
                <div className="mb-2 flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-cyan-500" />
                  <h3 className="text-xs font-bold text-slate-800">{zh ? '任务摘要' : 'Task summary'}</h3>
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3 xl:grid-cols-5">
                  <div className="min-w-0">
                    <dt className="text-[10px] text-slate-400">{zh ? '作业名称' : 'Job name'}</dt>
                    <dd className="truncate font-semibold text-slate-800">{form.name || (zh ? '未填写' : 'Not set')}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-[10px] text-slate-400">{zh ? '执行动作' : 'Action'}</dt>
                    <dd className="truncate font-semibold text-slate-800">{zh ? actionLabel?.labelZh : actionLabel?.labelEn}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-[10px] text-slate-400">{zh ? '目标范围' : 'Target scope'}</dt>
                    <dd className="truncate font-semibold text-slate-800">{zh ? scopeLabel?.labelZh : scopeLabel?.labelEn}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-[10px] text-slate-400">{zh ? '设备 / 在线' : 'Devices / online'}</dt>
                    <dd className="font-bold text-cyan-700">{deviceLoadStatus === 'loaded' ? `${matchedDevices.length} / ${onlineCount}` : deviceLoadStatus === 'error' ? (zh ? '加载失败' : 'Load failed') : (zh ? '加载中' : 'Loading')}</dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-[10px] text-slate-400">{zh ? '运行周期' : 'Schedule'}</dt>
                    <dd className="truncate font-semibold text-slate-800">{describeCron(form.cron_expr, zh)}</dd>
                  </div>
                </dl>
              </div>
            )}

            {/* Keep the schedule primary and group target preview and approval in a compact side rail. */}
            {flowStep === 1 && (
            <div className="lg:col-span-12 grid grid-cols-1 items-start gap-4 xl:grid-cols-2 2xl:grid-cols-12">
              <FormSection
                title={zh ? '目标设备预览' : 'Target preview'}
                description={(
                  <span className="font-semibold text-cyan-700">
                    {deviceLoadStatus === 'loaded'
                      ? `${matchedDevices.length} ${zh ? '台设备' : 'devices'} · ${onlineCount} ${zh ? '在线' : 'online'}`
                      : deviceLoadStatus === 'error' ? (zh ? '加载失败' : 'Load failed') : (zh ? '加载中…' : 'Loading…')}
                  </span>
                )}
                className="order-2 !mt-0 !rounded-2xl !border-slate-200/90 !bg-white shadow-2xs xl:col-start-2 xl:row-start-1 2xl:col-span-3 2xl:col-start-7 2xl:row-start-1"
                contentClassName="!space-y-2.5 !p-4"
              >
                {deviceLoadStatus === 'error' ? (
                  <div className="flex items-center justify-between gap-2 rounded-lg bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
                    <span>{zh ? '设备清单加载失败，无法计算目标数量。' : 'The inventory could not be loaded.'}</span>
                    <button type="button" onClick={refreshDevices} className="shrink-0 font-semibold underline">{zh ? '重试' : 'Retry'}</button>
                  </div>
                ) : (deviceLoadStatus === 'loading' || deviceLoadStatus === 'idle') && matchedDevices.length === 0 ? (
                  <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500">{zh ? '正在加载完整设备清单…' : 'Loading the complete device inventory…'}</p>
                ) : matchedDevices.length === 0 ? (
                  <p className="rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500">{zh ? '当前范围没有匹配设备。' : 'No devices match this scope.'}</p>
                ) : (
                  <div className="space-y-1">
                    {matchedDevices.slice(0, 4).map(dev => (
                      <div key={dev.id || dev.ip_address} className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-[11px]">
                        <span className="min-w-0 truncate font-medium text-slate-700">{dev.hostname || dev.ip_address}</span>
                        <span className="shrink-0 font-mono text-slate-500">{dev.ip_address}</span>
                      </div>
                    ))}
                    {matchedDevices.length > 4 && (
                      <p className="pt-0.5 text-right text-[10px] text-slate-400">{zh ? `另有 ${matchedDevices.length - 4} 台设备` : `and ${matchedDevices.length - 4} more`}</p>
                    )}
                  </div>
                )}
                {scriptIncompatibleCount > 0 && (
                  <p className="text-[11px] text-amber-700">{zh ? `${scriptIncompatibleCount} 台设备与脚本平台不兼容，将被跳过。` : `${scriptIncompatibleCount} devices do not match the script platform and will be skipped.`}</p>
                )}
              </FormSection>

              {/* Cron schedule and approval share the same final setup step. */}
              <FormSection
                title={zh ? 'Cron 调度周期' : 'Cron Schedule'}
                className="order-1 !mt-0 !rounded-2xl !border-slate-200/90 !bg-white shadow-2xs xl:col-start-1 xl:row-start-1 2xl:col-span-6 2xl:col-start-1 2xl:row-start-1"
                contentClassName="!space-y-3.5 !p-4"
              >
                {/* Preset Dropdown Trigger */}
                <div className="relative flex justify-end">
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
                <div className="min-h-[170px] rounded-xl border border-slate-100 bg-slate-50/70 p-3" aria-live="polite" aria-busy={cronPreviewStatus === 'loading'}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold text-slate-700">{zh ? '未来 10 次执行时间' : 'Next 10 runs'}</span>
                    {cronPreviewStatus === 'loading' && <span className="text-[10px] text-slate-400">{zh ? '计算中…' : 'Calculating…'}</span>}
                  </div>
                  {cronPreviewStatus === 'invalid' || cronPreviewStatus === 'error' ? (
                    <div className={`flex items-center justify-between gap-2 text-[11px] ${cronPreviewStatus === 'invalid' ? 'text-amber-700' : 'text-rose-700'}`} role="status">
                      <span>{cronPreviewError}</span>
                      {cronPreviewStatus === 'error' && (
                        <button type="button" onClick={() => setCronPreviewRetry(retry => retry + 1)} className="shrink-0 font-semibold underline">{zh ? '重试' : 'Retry'}</button>
                      )}
                    </div>
                  ) : cronPreviewStatus === 'loaded' && cronOccurrences.length === 0 ? (
                    <p className="text-[11px] text-amber-700">{zh ? '该表达式没有可预览的执行时间。' : 'No upcoming execution time was returned for this expression.'}</p>
                  ) : cronOccurrences.length > 0 ? (
                    <ol className={`grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-600 transition-opacity ${cronPreviewStatus === 'loading' ? 'opacity-50' : 'opacity-100'}`}>
                      {cronOccurrences.map((occurrence, index) => (
                        <li key={`${occurrence}-${index}`} className="flex gap-2">
                          <span className="w-4 shrink-0 text-right text-slate-400">{index + 1}.</span>
                          <time dateTime={occurrence}>{new Date(occurrence).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}</time>
                        </li>
                      ))}
                    </ol>
                  ) : cronPreviewStatus === 'idle' || cronPreviewStatus === 'loading' ? (
                    <p className="text-[11px] text-slate-400">{cronPreviewStatus === 'loading' ? (zh ? '计算中…' : 'Calculating…') : (zh ? '等待预览…' : 'Waiting for preview…')}</p>
                  ) : null}
                </div>
              </FormSection>

              <FormSection
                title={zh ? '安全审批授权' : 'Approval Gate'}
                description={approvalStatus === 'verified' ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-emerald-100 bg-emerald-50 px-2 py-0.5 text-xs font-bold text-emerald-600">
                    <Check size={12} />
                    {zh ? '已授权通过' : 'Verified'}
                  </span>
                ) : approvalStatus === 'verifying' ? (
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-700">
                    <RotateCcw size={12} className="animate-spin" />
                    {zh ? '正在验证' : 'Verifying'}
                  </span>
                ) : undefined}
                className="order-3 !mt-0 !rounded-2xl !border-slate-200/90 !bg-white shadow-2xs xl:col-span-2 xl:col-start-1 xl:row-start-2 2xl:col-span-3 2xl:col-start-10 2xl:row-start-1"
                contentClassName="!p-4"
              >

                <div className="space-y-2">
                  <select
                    value={approverUsername}
                    onChange={e => setApproverUsername(e.target.value)}
                    disabled={approvalStatus === 'sending' || approvalStatus === 'verifying' || approvalStatus === 'verified'}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-xs bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 text-slate-700 font-medium transition-all"
                  >
                    <option value="">{zh ? '请选择安全审批人...' : 'Select approver...'}</option>
                    {approvers.map(a => (
                      <option key={a.id} value={a.username}>{a.username}</option>
                    ))}
                  </select>

                  {approverLoadStatus === 'loading' && (
                    <p className="text-[11px] text-slate-500">{zh ? '正在加载审批人…' : 'Loading approvers…'}</p>
                  )}
                  {approverLoadStatus === 'error' && (
                    <div className="flex items-center justify-between gap-3 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
                      <span>{zh ? '审批人列表加载失败，请检查登录状态或权限后重试。' : 'Approvers could not be loaded. Check your session or permissions and retry.'}</span>
                      <button type="button" onClick={refreshApprovers} className="shrink-0 font-semibold underline">{zh ? '重试' : 'Retry'}</button>
                    </div>
                  )}
                  {approverLoadStatus === 'loaded' && approvers.length === 0 && (
                    <div className="rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800">
                      {zh
                        ? '当前没有可用审批人。审批人账号需启用、具有 PAM 审批权限，并配置 MFA、邮箱或飞书验证方式。'
                        : 'No eligible approver is available. Accounts must be active, have PAM approval permission, and have MFA, email, or Feishu configured.'}
                      <button type="button" onClick={refreshApprovers} className="ml-2 font-semibold underline">{zh ? '刷新' : 'Refresh'}</button>
                    </div>
                  )}

                  {approverUsername && availableApprovalMethods.length > 0 && (
                    <div className="space-y-1">
                      <label className="text-[10px] font-semibold text-slate-500">{zh ? '验证方式' : 'Verification method'}</label>
                      <select
                        value={approvalMethod}
                        onChange={e => setApprovalMethod(e.target.value as ApprovalVerificationMethod)}
                        disabled={approvalStatus !== 'idle'}
                        className="w-full px-3.5 py-2 rounded-xl border border-slate-200 text-xs bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 focus:border-cyan-500 text-slate-700 font-medium transition-all disabled:opacity-60"
                      >
                        {availableApprovalMethods.map(method => (
                          <option key={method} value={method}>{verificationMethodLabel(method)}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  {approverUsername && (approvalStatus === 'sent' || approvalStatus === 'verifying') && (
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        value={approvalCode}
                        disabled={approvalStatus === 'verifying'}
                        onChange={e => {
                          const code = e.target.value.replace(/\D/g, '').slice(0, 6);
                          setApprovalCode(code);
                          setApprovalError('');
                          if (code.length === 6) verifyApproval(code);
                        }}
                        placeholder={zh ? '输入 6 位动态码/验证码' : 'Enter 6-digit code'}
                        className="min-w-0 flex-1 px-3 py-2 rounded-xl border border-slate-200 text-xs font-mono bg-white focus:outline-none focus:ring-2 focus:ring-cyan-500/20 disabled:bg-slate-50"
                      />
                      {approvalStatus === 'verifying' && <span className="shrink-0 text-[11px] text-cyan-700">{zh ? '正在验证…' : 'Verifying…'}</span>}
                    </div>
                  )}
                  {approverUsername && (approvalStatus === 'idle' || approvalStatus === 'sending' || (approvalStatus === 'sent' && approvalCountdown === 0)) && (
                    <button
                      type="button"
                      onClick={requestApproval}
                      disabled={approvalStatus === 'sending'}
                      className="w-full rounded-xl bg-slate-800 px-4 py-2 text-xs font-bold text-white hover:bg-slate-900 disabled:opacity-40"
                    >
                      {approvalStatus === 'sending'
                        ? (zh ? '正在发送…' : 'Sending…')
                        : approvalMethod === 'mfa'
                          ? (zh ? '开始 MFA 验证' : 'Start MFA verification')
                          : (zh ? '发送验证码' : 'Send code')}
                    </button>
                  )}
                  {approvalStatus === 'sent' && approvalCountdown > 0 && (
                    <CountdownText deadline={approvalDeadline} onExpire={onApprovalCountdownExpire}>
                      {secondsRemaining => (
                        <p className="text-[10px] text-slate-400">{zh ? `可在 ${secondsRemaining} 秒后重新发送` : `Resend available in ${secondsRemaining}s`}</p>
                      )}
                    </CountdownText>
                  )}

                  {approvalError && (
                    <p className="text-[10px] text-rose-500 leading-tight">{approvalError}</p>
                  )}
                </div>
              </FormSection>
            </div>
            )}
          </div>

          {/* ═══════════════════════════════════════════════════════════════════
              FOOTER: 全局就绪状态栏与提交按钮
             ═══════════════════════════════════════════════════════════════════ */}
          <FormActionBar className="shrink-0 !flex-col !items-center !justify-between !gap-2 !border-slate-200 !bg-white !px-3 !py-3 sm:!flex-row sm:!px-4">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Sparkles size={14} className="text-cyan-600" />
              <span>
                {flowStep === 0
                  ? deviceLoadStatus === 'error'
                    ? (zh ? '设备清单加载失败，请检查权限后重试。' : 'Inventory loading failed. Check access and retry.')
                    : deviceLoadStatus !== 'loaded'
                      ? (zh ? '设备清单加载中…' : 'Loading device inventory…')
                      : (zh ? '先配置任务和目标设备。' : 'Start by choosing the task and target devices.')
                  : deviceLoadStatus === 'loaded'
                    ? (zh ? `目标 ${matchedDevices.length} 台（${onlineCount} 台在线）` : `${matchedDevices.length} targets (${onlineCount} online)`)
                    : deviceLoadStatus === 'error'
                      ? (zh ? '设备数量暂不可用' : 'Device count unavailable')
                      : (zh ? '设备清单加载中…' : 'Loading device inventory…')}
                {flowStep === 1 && approvalStatus !== 'verified' && (
                  <span className="ml-2 text-amber-700">{zh ? '完成审批验证后即可创建。' : 'Complete approval verification to create the job.'}</span>
                )}
              </span>
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
              <button
                type="button"
                onClick={onClose}
                disabled={approvalStatus === 'sending' || approvalStatus === 'verifying'}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition-all hover:bg-slate-50 disabled:opacity-40"
              >
                {zh ? '取消' : 'Cancel'}
              </button>
              {flowStep > 0 && (
                <button
                  type="button"
                  onClick={() => setFlowStep(step => Math.max(0, step - 1))}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition-all hover:bg-slate-50"
                >
                  {zh ? '上一步' : 'Back'}
                </button>
              )}
              {flowStep === 0 ? (
                <button
                  type="button"
                  onClick={() => setFlowStep(1)}
                  disabled={!canAdvance}
                  className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 via-sky-600 to-blue-600 px-4 py-2 text-xs font-bold text-white shadow-md shadow-cyan-500/20 transition-all disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {zh ? `下一步：${flowStepLabels[flowStep + 1]}` : `Next: ${flowStepLabels[flowStep + 1]}`}
                  <ChevronRight size={14} />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!isFormReady || approvalStatus !== 'verified'}
                  className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 via-sky-600 to-blue-600 px-4 py-2 text-xs font-bold text-white shadow-md shadow-cyan-500/20 transition-all hover:from-cyan-400 hover:to-blue-500 active:scale-98 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <CheckCircle2 size={16} />
                  {isEditMode ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建并启用' : 'Create & enable')}
                </button>
              )}
            </div>
          </FormActionBar>
        </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
