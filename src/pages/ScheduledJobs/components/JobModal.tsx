import React, { useState, useMemo } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  CalendarClock, X, Zap, ChevronDown, Search, FileCode, CheckCircle2,
  Trash2, RotateCcw, Database, Activity, RefreshCw,
  Target, Globe, Server, Check, Terminal, Radio, ChevronRight,
  Layers, Sliders, ShieldCheck, CheckCheck
} from 'lucide-react';
import TagConditionPicker, { hasTagFilterConditions, serializeTagFilter, type TagFilterConfig } from '../../../components/TagConditionPicker';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import { FormActionBar, FormSection } from '../../../components/ui/FormLayout';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import CountdownText from './CountdownText';
import { ScheduledJob, EligibleApprover, FormState, ValidatedDevice, type ApprovalVerificationMethod, type AuthorizationGrantForm, type CollectionPlanFilters } from '../types';
import {
  CRON_PRESETS, CRON_FIELD_LABELS_ZH, CRON_FIELD_LABELS_EN,
  CRON_FIELD_HINTS_ZH, CRON_FIELD_HINTS_EN,
  MAJOR_CATEGORIES, SCOPE_OPTIONS
} from '../constants';
import { describeCron, describeScope } from '../helpers';

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
  availableScripts: Array<{ id: string; name: string; status: string; category: string; platform?: string; script_type?: string; version?: string; parent_script_id?: string }>;
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
  approvalSeq?: string;
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

const toLocalDateTimeInput = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return localDate.toISOString().slice(0, 16);
};

const toUtcIso = (value: string): string => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
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
  approvalSeq,
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
  const grant = form.authorization_grant;
  const updateGrant = <K extends keyof AuthorizationGrantForm,>(key: K, value: AuthorizationGrantForm[K]) => {
    setForm(current => ({ ...current, authorization_grant: { ...current.authorization_grant, [key]: value } }));
  };
  const grantScopeFilter = form.device_scope === 'ip'
    ? ipDevices.map(device => device.ip).join(',')
    : form.device_scope === 'tag'
      ? serializeTagFilter(tagFilter)
      : form.device_filter;
  const grantScopeDescription = describeScope(form.device_scope, grantScopeFilter, zh);
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

  const boundScriptBaseId = editingJob?.script_id || form.script_id || '';
  const currentBoundScript = useMemo(
    () => (availableScripts || []).find(s => s.id === form.script_id) || (availableScripts || []).find(s => s.id === boundScriptBaseId) || null,
    [availableScripts, form.script_id, boundScriptBaseId],
  );
  const sameScriptVersions = useMemo(() => {
    if (!boundScriptBaseId) return [];
    const anchor = (availableScripts || []).find(s => s.id === boundScriptBaseId) || currentBoundScript;
    if (!anchor) return [];
    const rootId = (anchor.parent_script_id || anchor.id).trim();
    const stripVerId = (id: string) => id.replace(/[_-]v\d+(?:[._]\d+)*$/i, '').trim();
    const stripVerName = (name: string) => name.replace(/\s*(?:\(新版本\)|\(New Version\)|v\d+(?:\.\d+)*)\s*$/i, '').trim();
    const baseId = stripVerId(anchor.id);
    const baseName = stripVerName(anchor.name);
    const matches = (availableScripts || []).filter(s => {
      if (s.id === anchor.id) return true;
      const sRoot = (s.parent_script_id || s.id).trim();
      if (sRoot === rootId || s.parent_script_id === anchor.id || anchor.parent_script_id === s.id) return true;
      if (baseId && stripVerId(s.id) === baseId) return true;
      if (baseName && stripVerName(s.name) === baseName) return true;
      return false;
    });
    return matches.sort((a, b) => String(b.version || 'v1.0.0').localeCompare(String(a.version || 'v1.0.0'), undefined, { numeric: true }));
  }, [availableScripts, boundScriptBaseId, currentBoundScript]);

  React.useEffect(() => {
    if (isOpen) setFlowStep(0);
  }, [isOpen]);

  React.useEffect(() => {
    if (!isOpen) {
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
  }, [isOpen, form.cron_expr, fetchCronPreview, cronPreviewRetry, zh]);

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
  const flowStepLabels = zh ? ['作业与设备', '时间与审批'] : ['Task & devices', 'Schedule & approval'];
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

        <div className="flex shrink-0 items-center justify-between border-b border-slate-200/80 bg-white px-5 py-3.5 sm:px-6">
          <div className="flex items-center gap-3.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 text-white shadow-sm shadow-blue-500/20">
              <CalendarClock size={19} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 id="scheduled-job-form-title" className="text-sm font-bold tracking-tight text-slate-900 sm:text-base">
                  {isEditMode ? (zh ? '编辑定时作业' : 'Edit Scheduled Job') : (zh ? '创建定时作业' : 'Create Scheduled Job')}
                </h2>
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${isEditMode ? 'bg-blue-50 text-blue-700 border border-blue-200/70' : 'bg-emerald-50 text-emerald-700 border border-emerald-200/70'}`}>
                  {isEditMode ? (zh ? '修改配置' : 'Editing') : (zh ? '新建任务' : 'New')}
                </span>
              </div>
              <p className="mt-0.5 hidden text-[11px] text-slate-400 sm:block">
                {zh ? '统一配置作业信息、目标设备、执行周期与安全审批' : 'Configure task details, target fleet, schedule, and security approval'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={zh ? '关闭作业配置' : 'Close job setup'}
            disabled={approvalStatus === 'sending' || approvalStatus === 'verifying'}
            className="rounded-xl p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40"
          >
            <X size={18} />
          </button>
        </div>

        {/* The form body scrolls inside the compact dialog while the header and actions stay visible. */}
        <form className="flex min-h-0 flex-1 flex-col overflow-hidden" onSubmit={e => {
          e.preventDefault();
          if (isFormReady && approvalStatus === 'verified') submitForm();
        }}>
          <div className="grid min-h-0 flex-1 grid-cols-1 content-start gap-4 overflow-y-auto overscroll-contain bg-slate-50/80 p-4 sm:p-5 lg:grid-cols-12">
            
            {/* ═══════════════════════════════════════════════════════════════════
                Task setup and targets share a row on desktop.
               ═══════════════════════════════════════════════════════════════════ */}
            <div className="grid min-w-0 items-stretch gap-4 md:grid-cols-2 lg:col-span-12">
              <div className="min-w-0 space-y-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.04)]">
              
              {/* Block 1: 基本属性 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-cyan-50 text-cyan-600">
                    <Sliders size={13} />
                  </span>
                  <h3 className="text-[13px] font-bold text-slate-800">{zh ? '基本信息' : 'Basic Info'}</h3>
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
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-xs font-medium text-slate-800 bg-slate-50/40 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/15 focus:border-blue-500 transition-all placeholder:text-slate-300"
                    placeholder={zh ? '例如：每日凌晨核心交换机巡检' : 'e.g. Daily Core Switch Health Inspection'}
                  />
                </div>
              </div>

              {/* Block 2: 执行动作与驱动协议 */}
              <div className="space-y-3 border-t border-slate-100 pt-4">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                    <FileCode size={13} />
                  </span>
                  <h3 className="text-[13px] font-bold text-slate-800">{zh ? '执行动作与绑定脚本' : 'Action & Bound Script'}</h3>
                </div>

                {/* Action Types (only shown when creating a new job) */}
                {!isEditMode && (
                <div className="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1 sm:grid-cols-3 xl:grid-cols-6 [&>button]:whitespace-nowrap [&>button]:text-[11px] [&>button>svg]:shrink-0">
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
                      setForm(f => ({ ...f, action_type: 'bgp_neighbors', major_type: 'collection', commands: '', script_id: '', is_config: false, config_reason: '', use_admin_creds: false }));
                      setApproverUsername('');
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${form.action_type === 'bgp_neighbors' ? 'bg-white shadow-2xs text-cyan-700' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    <RefreshCw className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? 'BGP 邻居' : 'BGP Neighbors'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setForm(f => ({ ...f, action_type: 'ospf_neighbors', major_type: 'collection', commands: '', script_id: '', is_config: false, config_reason: '', use_admin_creds: false }));
                      setApproverUsername('');
                    }}
                    className={`py-2 rounded-lg text-xs font-bold transition-all flex items-center justify-center gap-1.5 ${form.action_type === 'ospf_neighbors' ? 'bg-white shadow-2xs text-cyan-700' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    <RefreshCw className="w-3.5 h-3.5 text-cyan-600" />
                    {zh ? 'OSPF 邻居' : 'OSPF Neighbors'}
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
                )}
                {(form.action_type === 'bgp_neighbors' || form.action_type === 'ospf_neighbors') && (
                  <div className="rounded-xl border border-cyan-200 bg-cyan-50/60 px-3 py-2.5 text-[11px] leading-relaxed text-slate-600">
                    {form.action_type === 'bgp_neighbors'
                      ? (zh ? '只采集 BGP 邻居状态（SNMP 优先，CLI 回退），不拉取完整 BGP 路由表。最短周期 5 分钟；目标数受审批上限约束。' : 'Collects BGP neighbor state only (SNMP first, CLI fallback), not the full BGP RIB. Minimum interval: 5 minutes; target count is bounded by approval.')
                      : (zh ? '只采集 OSPF 邻居状态（SNMP 优先，CLI 回退）。最短周期 5 分钟；目标数受审批上限约束。' : 'Collects OSPF neighbor state only (SNMP first, CLI fallback). Minimum interval: 5 minutes; target count is bounded by approval.')}
                  </div>
                )}
                {(form.action_type === 'command' || form.action_type === 'script_run') && (
                <div className="flex items-start gap-2 text-[11px] leading-relaxed text-amber-700">
                  <ShieldCheck size={14} className="mt-0.5 shrink-0 text-amber-600" />
                  <span>
                    {zh
                      ? '命令和脚本需经其他审批人验证；修改内容后需重新审批。'
                      : 'Commands and scripts require approval. Changes require re-approval.'}
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
                  isEditMode && form.script_id ? (
                    <div className="rounded-xl border border-blue-100/90 bg-gradient-to-br from-slate-50/90 via-white to-blue-50/40 p-3.5 space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex items-center gap-1.5 text-[10px] font-semibold text-slate-400">
                            <span>{zh ? '已绑定脚本' : 'Bound Script'}</span>
                            {currentBoundScript?.platform && (
                              <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                                {currentBoundScript.platform}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <FileCode size={15} className="shrink-0 text-blue-600" />
                            <span className="text-xs font-bold text-slate-800 break-words leading-snug">
                              {currentBoundScript?.name || form.script_id}
                            </span>
                          </div>
                        </div>
                        <span className="shrink-0 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 font-mono text-[11px] font-bold text-blue-700">
                          {currentBoundScript?.version || 'v1.0.0'}
                        </span>
                      </div>

                      <div className="flex flex-col gap-1.5 border-t border-slate-100 pt-2.5 sm:flex-row sm:items-center sm:justify-between">
                        <span className="text-[11px] text-slate-500">
                          {sameScriptVersions.length > 1
                            ? (zh ? '切换脚本版本（仅限同一脚本）' : 'Switch script version (same script only)')
                            : (zh ? '仅支持切换同一脚本的不同版本，不支持更换为其他脚本' : 'Only versions of the same script can be switched')}
                        </span>
                        {sameScriptVersions.length > 1 ? (
                          <select
                            aria-label={zh ? '选择脚本版本' : 'Select script version'}
                            value={form.script_id}
                            onChange={e => setForm(f => ({ ...f, script_id: e.target.value }))}
                            className="shrink-0 rounded-lg border border-blue-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-blue-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15"
                          >
                            {sameScriptVersions.map(v => (
                              <option key={v.id} value={v.id}>
                                {(v.version || 'v1.0.0')} · {v.id}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                            {zh ? '当前仅 1 个已发布版本' : 'Single released version'}
                          </span>
                        )}
                      </div>
                    </div>
                  ) : (
                  <div className="p-3.5 rounded-xl bg-slate-50/80 border border-slate-200/80 space-y-3">
                    <>
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
                            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-bold whitespace-nowrap transition-all flex items-center justify-center gap-1.5 ${
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
                            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-bold whitespace-nowrap transition-all flex items-center justify-center gap-1.5 ${
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
                              className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-bold whitespace-nowrap transition-all flex items-center justify-center gap-1.5 ${
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
                              className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-bold whitespace-nowrap transition-all flex items-center justify-center gap-1.5 ${
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
                    </>
                  </div>
                  )
                )}
              </div>

              </div>

              {/* Block 3: 目标资产范围设定 */}
              <div className="min-w-0 flex flex-col rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.04)]">
                <div className="mb-3.5 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                      <Target size={13} />
                    </span>
                    <h3 className="text-[13px] font-bold text-slate-800">{zh ? '目标资产范围' : 'Target Fleet Scope'}</h3>
                  </div>
                  {deviceLoadStatus === 'loaded' && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 tabular-nums">
                      <span className={`h-1.5 w-1.5 rounded-full ${onlineCount > 0 ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                      {zh ? `${matchedDevices.length} 台匹配 · ${onlineCount} 在线` : `${matchedDevices.length} matched · ${onlineCount} online`}
                    </span>
                  )}
                </div>

                <div className="space-y-3 flex-1">

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
                </div>
              </div>
            </div>

            {/* Schedule & Approval sit right below on the same unified page */}
            <div className="lg:col-span-12 grid grid-cols-1 items-stretch gap-4 xl:grid-cols-12">
              {/* Cron schedule */}
              <div className="order-1 flex flex-col rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.04)] xl:col-span-6">
                <div className="mb-3.5 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
                      <CalendarClock size={13} />
                    </span>
                    <h3 className="text-[13px] font-bold text-slate-800">{zh ? '执行计划' : 'Schedule'}</h3>
                  </div>
                  <span className="inline-flex items-center rounded-full border border-cyan-200/80 bg-cyan-50/80 px-2.5 py-0.5 text-[11px] font-semibold text-cyan-700">
                    {describeCron(form.cron_expr, zh)}
                  </span>
                </div>

                <div className="space-y-3.5 flex-1">
                {/* 1-Click Quick Cron Preset Pills (clean 4x2 grid) */}
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1 text-[11px] font-semibold text-slate-400">
                    <Zap size={11} className="text-amber-500" />
                    <span>{zh ? '常用快捷周期' : 'Quick Presets'}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                    {[
                      { cron: '*/5 * * * *', label: '每 5 分钟', labelEn: 'Every 5m' },
                      { cron: '*/15 * * * *', label: '每 15 分钟', labelEn: 'Every 15m' },
                      ...CRON_PRESETS,
                    ]
                      .filter((item, idx, arr) => arr.findIndex(x => x.cron === item.cron) === idx)
                      .slice(0, 8)
                      .map(p => {
                        const active = form.cron_expr.trim() === p.cron;
                        return (
                          <button
                            type="button"
                            key={p.cron}
                            onClick={() => setForm(f => ({ ...f, cron_expr: p.cron }))}
                            title={p.cron}
                            className={`rounded-xl border px-2 py-1.5 text-[11px] font-semibold whitespace-nowrap text-center transition-all ${
                              active
                                ? 'border-blue-600 bg-blue-600 text-white shadow-sm shadow-blue-600/20'
                                : 'border-slate-200/90 bg-slate-50/70 text-slate-600 hover:border-blue-300 hover:bg-blue-50/60 hover:text-blue-700'
                            }`}
                          >
                            {zh ? p.label : p.labelEn}
                          </button>
                        );
                      })}
                  </div>
                </div>

                {/* 5-Field Editor */}
                <div className="grid grid-cols-5 gap-2">
                  {cronFields.map((val, idx) => (
                    <div key={idx} className="space-y-1">
                      <input
                        type="text"
                        value={val}
                        onChange={e => updateCronField(idx, e.target.value)}
                        className="w-full text-center py-2 rounded-xl border border-slate-200 text-xs font-mono font-bold bg-slate-50/50 hover:bg-white focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/15 focus:border-blue-500 transition-all text-slate-800"
                        placeholder="*"
                      />
                      <span className="text-[10px] font-medium text-slate-400 block text-center">
                        {zh ? CRON_FIELD_LABELS_ZH[idx] : CRON_FIELD_LABELS_EN[idx]}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="rounded-xl border border-slate-200/80 bg-slate-50/60 p-3" aria-live="polite" aria-busy={cronPreviewStatus === 'loading'}>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-slate-700">{zh ? '接下来 10 次执行时间' : 'Next 10 runs'}</span>
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
                    <ol className={`grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 text-[11px] text-slate-600 transition-opacity ${cronPreviewStatus === 'loading' ? 'opacity-50' : 'opacity-100'}`}>
                      {cronOccurrences.map((occurrence, index) => (
                        <li key={`${occurrence}-${index}`} className="flex items-center gap-2 rounded-lg bg-white/80 px-2 py-1 border border-slate-100">
                          <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-500 tabular-nums">{index + 1}</span>
                          <time dateTime={occurrence} className="font-mono text-[11px] tabular-nums text-slate-700">{new Date(occurrence).toLocaleString(zh ? 'zh-CN' : 'en-US', { hour12: false })}</time>
                        </li>
                      ))}
                    </ol>
                  ) : cronPreviewStatus === 'idle' || cronPreviewStatus === 'loading' ? (
                    <p className="text-[11px] text-slate-400">{cronPreviewStatus === 'loading' ? (zh ? '计算中…' : 'Calculating…') : (zh ? '等待预览…' : 'Waiting for preview…')}</p>
                  ) : null}
                </div>
                </div>
              </div>

              <div className="order-2 flex flex-col rounded-2xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_3px_rgba(15,23,42,0.04)] xl:col-span-6">
                <div className="mb-3.5 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
                      <ShieldCheck size={13} />
                    </span>
                    <h3 className="text-[13px] font-bold text-slate-800">{zh ? '审批验证' : 'Approval'}</h3>
                  </div>
                  {approvalStatus === 'verified' ? (
                    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-bold text-emerald-700">
                      <Check size={12} />
                      {zh ? '已授权通过' : 'Verified'}
                    </span>
                  ) : approvalStatus === 'verifying' ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-blue-700">
                      <RotateCcw size={12} className="animate-spin" />
                      {zh ? '正在验证' : 'Verifying'}
                    </span>
                  ) : (
                    <span className="text-[10px] font-medium text-slate-400">
                      {zh ? '需安全审批人确认' : 'Requires approver verification'}
                    </span>
                  )}
                </div>

                <div className="space-y-3 flex-1">
                  <div className="space-y-2.5 rounded-xl border border-slate-200/80 bg-slate-50/70 p-3.5">
                    <div className="flex items-center justify-between gap-2">
                      <h4 className="text-[11px] font-bold text-slate-700">{zh ? '本次授权清单' : 'Authorization grant'}</h4>
                      <span className="text-[10px] text-slate-400">{zh ? '运行时由服务端强制校验' : 'Server-enforced at runtime'}</span>
                    </div>
                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-12">
                      <label className="block text-[11px] font-semibold text-slate-600 sm:col-span-6">
                        {zh ? '授权有效至' : 'Valid until'} <span className="text-rose-500">*</span>
                        <input
                          aria-label={zh ? '授权有效至' : 'Authorization valid until'}
                          type="datetime-local"
                          required
                          min={toLocalDateTimeInput(new Date().toISOString())}
                          value={toLocalDateTimeInput(grant.valid_until)}
                          onChange={event => updateGrant('valid_until', toUtcIso(event.target.value))}
                          className="mt-1 min-h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-normal text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15"
                        />
                      </label>
                      <label className="block text-[11px] font-semibold text-slate-600 sm:col-span-6">
                        {zh ? '关联变更单 ID（选填）' : 'Change order ID (optional)'}
                        <input
                          aria-label={zh ? '关联变更单 ID（选填）' : 'Change order ID (optional)'}
                          maxLength={120}
                          value={grant.change_order_id}
                          onChange={event => updateGrant('change_order_id', event.target.value)}
                          placeholder={zh ? '需要时填写 CO ID' : 'Enter a CO ID when applicable'}
                          className="mt-1 min-h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-normal text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15"
                        />
                      </label>
                    </div>
                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-12">
                      <label className="block text-[11px] font-semibold text-slate-600 sm:col-span-4">
                        {zh ? '关联工单类型' : 'Ticket type'} <span className="text-rose-500">*</span>
                        <select
                          aria-label={zh ? '关联工单类型' : 'Ticket type'}
                          value={grant.ticket_source_type}
                          onChange={event => updateGrant('ticket_source_type', event.target.value as AuthorizationGrantForm['ticket_source_type'])}
                          className="mt-1 min-h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-normal text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15"
                        >
                          <option value="incident">{zh ? '故障工单' : 'Incident ticket'}</option>
                          <option value="service_request">{zh ? '服务申请' : 'Service request'}</option>
                        </select>
                      </label>
                      <label className="block text-[11px] font-semibold text-slate-600 sm:col-span-8">
                        {zh ? '工单编号 / ID' : 'Ticket number / ID'} <span className="text-rose-500">*</span>
                        <input
                          aria-label={zh ? '工单编号 / ID' : 'Ticket number / ID'}
                          required
                          maxLength={120}
                          value={grant.ticket_id}
                          onChange={event => updateGrant('ticket_id', event.target.value)}
                          placeholder={zh ? '输入工单编号或 ID' : 'Paste ticket number or ID'}
                          className="mt-1 min-h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 font-mono text-xs font-normal text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15"
                        />
                      </label>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    <div className="space-y-1">
                      <label className="text-[11px] font-semibold text-slate-600">{zh ? '安全审批人' : 'Approver'}</label>
                      <select
                        value={approverUsername}
                        onChange={e => setApproverUsername(e.target.value)}
                        disabled={approvalStatus === 'sending' || approvalStatus === 'verifying' || approvalStatus === 'verified'}
                        className="w-full min-h-9 px-3 py-2 rounded-xl border border-slate-200 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/15 focus:border-blue-500 text-slate-700 font-medium transition-all disabled:opacity-60"
                      >
                        <option value="">{zh ? '请选择安全审批人...' : 'Select approver...'}</option>
                        {approvers.map(a => (
                          <option key={a.id} value={a.username}>{a.username}</option>
                        ))}
                      </select>
                    </div>

                    {approverUsername && availableApprovalMethods.length > 0 && (
                      <div className="space-y-1">
                        <label className="text-[11px] font-semibold text-slate-600">{zh ? '验证方式' : 'Verification method'}</label>
                        <select
                          value={approvalMethod}
                          onChange={e => setApprovalMethod(e.target.value as ApprovalVerificationMethod)}
                          disabled={approvalStatus !== 'idle'}
                          className="w-full min-h-9 px-3 py-2 rounded-xl border border-slate-200 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/15 focus:border-blue-500 text-slate-700 font-medium transition-all disabled:opacity-60"
                        >
                          {availableApprovalMethods.map(method => (
                            <option key={method} value={method}>{verificationMethodLabel(method)}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>

                  <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-slate-200/80 bg-slate-50/50 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 transition-colors">
                    <input type="checkbox" checked={Boolean(form.enabled)} onChange={event => setForm(current => ({ ...current, enabled: event.target.checked }))} className="h-3.5 w-3.5 rounded accent-blue-600" />
                    <span className="font-medium">{zh ? '审批通过后立即启用作业' : 'Enable the job after approval'}</span>
                  </label>

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

                  {approverUsername && (approvalStatus === 'sent' || approvalStatus === 'verifying') && (
                    <div className="flex items-center gap-2">
                      {approvalSeq && (
                        <span className="shrink-0 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs font-bold font-mono text-indigo-700" title={zh ? '请核对邮件中的对应序号，防止多人并发混淆' : 'Match this sequence number in the approval email'}>
                          #{approvalSeq}
                        </span>
                      )}
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
                        className="min-w-0 flex-1 px-3.5 py-2 rounded-xl border border-slate-200 text-xs font-mono bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/15 focus:border-blue-500 disabled:bg-slate-50"
                      />
                      {approvalStatus === 'verifying' && <span className="shrink-0 text-[11px] text-blue-700">{zh ? '正在验证…' : 'Verifying…'}</span>}
                    </div>
                  )}
                  {approverUsername && (approvalStatus === 'idle' || approvalStatus === 'sending' || (approvalStatus === 'sent' && approvalCountdown === 0)) && (
                    <button
                      type="button"
                      onClick={requestApproval}
                      disabled={approvalStatus === 'sending'}
                      className="w-full rounded-xl bg-slate-900 px-4 py-2.5 text-xs font-bold text-white shadow-xs transition-all hover:bg-slate-800 active:scale-[0.99] disabled:opacity-40"
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
                        <p className="text-[11px] text-slate-400">{zh ? `可在 ${secondsRemaining} 秒后重新发送` : `Resend available in ${secondsRemaining}s`}</p>
                      )}
                    </CountdownText>
                  )}

                  {approvalError && (
                    <p className="text-[11px] text-rose-600 leading-tight">{approvalError}</p>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════════════
              FOOTER: 全局就绪状态栏与提交按钮
             ═══════════════════════════════════════════════════════════════════ */}
          <FormActionBar className="shrink-0 !flex-col !items-center !justify-between !gap-2 !border-slate-200 !bg-white !px-3 !py-3 sm:!flex-row sm:!px-4">
            <div className="text-xs text-slate-500" aria-live="polite">
              {deviceLoadStatus === 'error'
                ? (zh ? '设备清单加载失败，请重试。' : 'Inventory failed to load. Retry.')
                : deviceLoadStatus !== 'loaded'
                  ? (zh ? '设备清单加载中…' : 'Loading device inventory…')
                  : (zh
                      ? `当前范围匹配 ${matchedDevices.length} 台设备（${onlineCount} 台在线）${approvalStatus === 'verified' ? '' : ' · 完成审批验证后即可保存'}`
                      : `${matchedDevices.length} devices matched (${onlineCount} online)${approvalStatus === 'verified' ? '' : ' · Verify approval to save'}`)}
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
              <button
                type="submit"
                disabled={!isFormReady || approvalStatus !== 'verified'}
                className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 via-sky-600 to-blue-600 px-4 py-2 text-xs font-bold text-white shadow-md shadow-cyan-500/20 transition-all hover:from-cyan-400 hover:to-blue-500 active:scale-98 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <CheckCircle2 size={16} />
                {isEditMode ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建并启用' : 'Create & enable')}
              </button>
            </div>
          </FormActionBar>
        </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
