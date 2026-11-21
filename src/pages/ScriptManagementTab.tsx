import { DataTable } from '../components/DataTable';
import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useLocation } from 'react-router-dom';
import {
  Plus, X, Trash2, Pencil, Search, User, FileCode, Terminal, Layout, Maximize2, XCircle, Wand2, ChevronDown, ChevronUp, CheckCircle2, MessageSquare, AlertCircle, SearchCode, Copy, Filter, RotateCcw
} from 'lucide-react';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import { ListToolbar } from '../components/ui/TableListControls';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { fetchAllPaginatedItems } from '../utils/pagination';
import {
  TEXTFSM_VENDOR_OPTIONS,
  getEditorSelection,
  getPlatformFamilyOption,
  getVendorOption,
  TEXTFSM_VERSION_LABELS,
} from './textfsmPlatformCatalog';

import { TableActionCell, TableActionHeader } from '../components/ui/TableActionColumn';
interface Script {
  id: string;
  name: string;
  content: string;
  description: string;
  platform: string;
  category: string;
  script_type: string;
  author: string;
  version: string;
  status: string;
  submitter_name?: string;
  approver_username?: string;
  rejected_reason?: string;
  updated_at?: string;
  risk_level?: 'low' | 'medium' | 'high';
  risk_findings?: string[];
}

const HIGH_RISK_RULES: Array<{ re: RegExp; zh: string; en: string }> = [
  { re: /\brm\s+-[a-z]*r[a-z]*f\b|\brm\s+-[a-z]*f[a-z]*r\b/i, zh: '强制递归删除文件 (rm -rf)', en: 'Recursive force delete (rm -rf)' },
  { re: /\bmkfs(?:\.[a-z0-9]+)?\b/i, zh: '格式化磁盘分区 (mkfs)', en: 'Filesystem format (mkfs)' },
  { re: /\bdd\s+if=.*\bof=\/dev\//i, zh: '直接覆写块设备 (dd of=/dev/)', en: 'Direct block device write (dd)' },
  { re: /\b(?:reboot|shutdown|poweroff|halt|init\s+[06])\b/i, zh: '主机重启或关机指令', en: 'Host reboot / shutdown command' },
  { re: /\breset\s+saved-configuration\b|\bwrite\s+erase\b|\berase\s+startup-config\b/i, zh: '清空网络设备启动配置', en: 'Erase network device startup config' },
  { re: /\b(?:reload|format\s+flash:|delete\s+\/unreserved)\b/i, zh: '网络设备重启或不可恢复删除', en: 'Network device reload / unreserved delete' },
  { re: /\biptables\s+-F\b|\bufw\s+disable\b/i, zh: '清空或关闭主机防火墙', en: 'Flush or disable host firewall' },
];

const MEDIUM_RISK_RULES: Array<{ re: RegExp; zh: string; en: string }> = [
  { re: /\bdisplay\s+ip\s+routing-table\s+verbose\b/i, zh: '拉取全量详细路由表（大网易超时）', en: 'Full verbose routing table dump' },
  { re: /\bsystemctl\s+(?:stop|restart|disable)\b|\bservice\s+\S+\s+(?:stop|restart)\b/i, zh: '停止或重启系统服务', en: 'Stop or restart system service' },
  { re: /\bkill\s+-9\b|\bpkill\s+-9\b/i, zh: '强制终止进程 (kill -9)', en: 'Force kill process (kill -9)' },
  { re: /^\s*(?:system-view|configure\s+terminal)\b/im, zh: '进入网络设备配置视图', en: 'Enter device configuration mode' },
];

function analyzeScriptRisk(content: string | undefined, zh: boolean): { level: 'low' | 'medium' | 'high'; findings: string[] } {
  const effective = String(content || '')
    .split('\n')
    .filter((line) => !line.trimStart().startsWith('#'))
    .join('\n');
  const high = HIGH_RISK_RULES.filter((r) => r.re.test(effective)).map((r) => (zh ? r.zh : r.en));
  const med = MEDIUM_RISK_RULES.filter((r) => r.re.test(effective)).map((r) => (zh ? r.zh : r.en));
  if (high.length > 0) return { level: 'high', findings: [...high, ...med] };
  if (med.length > 0) return { level: 'medium', findings: med };
  return { level: 'low', findings: [] };
}

interface UserInfo {
  id?: string;
  username: string;
  role?: string;
}

const ScriptManagementTab: React.FC<{ language: string; showToast: (msg: string, type: 'success' | 'error' | 'info') => void; view?: 'scripts' | 'nsot' }> = ({ language, showToast, view = 'scripts' }) => {
  const location = useLocation();
  const scriptDomain: 'all' | 'network' | 'server' = location.pathname.endsWith('/network')
    ? 'network'
    : location.pathname.endsWith('/server')
      ? 'server'
      : 'all';
  const [scripts, setScripts] = useState<Script[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [currentUser, setCurrentUser] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState(() => new URLSearchParams(location.search).get('q') || '');
  const [platformFilter, setPlatformFilter] = useState('All');
  const [nsotVendorFilter, setNsotVendorFilter] = useState('All');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'inspection' | 'change' | 'system'>('all');
  const [typeFilter, setTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [nsotCreateRequest, setNsotCreateRequest] = useState(0);
  const [nsotRefreshRequest, setNsotRefreshRequest] = useState(0);
  
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editForm, setEditForm] = useState<Partial<Script>>({});
  
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [showRejectPrompt, setShowRejectPrompt] = useState(false);
  useEscapeClose(isModalOpen, () => { setIsModalOpen(false); setValidationResult(null); setShowOutputChecker(false); });
  useEscapeClose(showConfirmModal, () => setShowConfirmModal(false));
  useEscapeClose(showRejectPrompt, () => setShowRejectPrompt(false));
  const [rejectReason, setRejectReason] = useState('');
  
  const [auditorSearch, setAuditorSearch] = useState('');
  const [showAuditorDropdown, setShowAuditorDropdown] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    syntax_errors: string[];
    syntax_warnings: string[];
    output_validation?: { passed: boolean; checks: Array<{ rule: string; passed: boolean; detail: string }> } | null;
  } | null>(null);
  const [showOutputChecker, setShowOutputChecker] = useState(false);
  const [outputFormat, setOutputFormat] = useState<'any' | 'json' | 'key_value' | 'numeric'>('key_value');
  const [mustContain, setMustContain] = useState('');
  const [mustNotContain, setMustNotContain] = useState('Traceback, SyntaxError, % Invalid input');
  const [outputRegex, setOutputRegex] = useState('');
  const [sampleOutput, setSampleOutput] = useState('');

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalScripts, setTotalScripts] = useState(0);
  const [loadError, setLoadError] = useState<'auth' | 'permission' | 'request' | ''>('');
  const requestSequenceRef = useRef(0);
  const activeRequestRef = useRef<AbortController | null>(null);
  const reduceMotion = useReducedMotion();

  const zh = language === 'zh';
  const BRAND_COLOR = "#2563eb";

  useEffect(() => {
    setSearchQuery(new URLSearchParams(location.search).get('q') || '');
    setPlatformFilter('All');
    setCurrentPage(1);
  }, [location.search, scriptDomain]);

  // Status Localization Map
  const STATUS_MAP: Record<string, { zh: string, en: string, color: string, bg: string, border: string }> = {
    draft: { zh: '草稿', en: 'Draft', color: 'text-slate-500', bg: 'bg-slate-50 dark:bg-slate-800/50', border: 'border-slate-200 dark:border-slate-700' },
    pending_audit: { zh: '待审核', en: 'Pending', color: 'text-amber-500', bg: 'bg-amber-50 dark:bg-amber-500/10', border: 'border-amber-200 dark:border-amber-500/20' },
    released: { zh: '已发布', en: 'Released', color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-500/10', border: 'border-emerald-200 dark:border-emerald-500/20' },
    rejected: { zh: '已驳回', en: 'Rejected', color: 'text-rose-500', bg: 'bg-rose-50 dark:bg-rose-500/10', border: 'border-rose-200 dark:border-rose-500/20' }
  };

  const getStatusLabel = (status: string) => {
    const meta = STATUS_MAP[status] || STATUS_MAP.draft;
    return zh ? meta.zh : meta.en;
  };

  const getHeaders = useCallback(() => {
    const token = localStorage.getItem('netops_token') || '';
    return {
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    };
  }, []);

  const handleFormat = () => {
    if (!editForm.content) return;
    const formatted = editForm.content.split('\n').map(l => l.trimEnd()).join('\n');
    setEditForm({ ...editForm, content: formatted });
    showToast(zh ? '格式已整理' : 'Formatted', 'info');
  };

  const handleValidateScript = async (includeOutput = false) => {
    setValidating(true);
    try {
      const body: Record<string, unknown> = {
        content: editForm.content || '',
        script_type: editForm.script_type || 'shell',
      };
      if (includeOutput) {
        body.sample_output = sampleOutput;
        body.output_contract = {
          format: outputFormat,
          must_contain: mustContain.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
          must_not_contain: mustNotContain.split(/[,\n]/).map((s) => s.trim()).filter(Boolean),
          regex: outputRegex.trim(),
        };
      }
      const res = await fetch('/api/scripts/validate', {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const data = await res.json();
        setValidationResult(data);
        showToast(
          data.valid
            ? (zh ? '语法与输出校验通过' : 'Validation passed')
            : (zh ? '校验未通过，请查看下方详情' : 'Validation failed'),
          data.valid ? 'success' : 'error',
        );
      } else {
        showToast(zh ? '校验接口调用失败' : 'Validation request failed', 'error');
      }
    } catch {
      showToast(zh ? '校验请求异常' : 'Validation error', 'error');
    } finally {
      setValidating(false);
    }
  };

  const fetchScripts = useCallback(async () => {
    activeRequestRef.current?.abort();
    const controller = new AbortController();
    activeRequestRef.current = controller;
    const requestSequence = ++requestSequenceRef.current;
    setLoading(true);
    setLoadError('');
    setScripts([]);
    setTotalScripts(0);
    try {
      const params = new URLSearchParams({
        q: searchQuery.trim(),
        platform: platformFilter === 'All' ? '' : platformFilter,
        category: categoryFilter === 'all' ? '' : categoryFilter,
        script_type: typeFilter === 'All' ? '' : typeFilter,
        status: statusFilter === 'All' ? '' : statusFilter,
        page: String(currentPage),
        page_size: String(pageSize),
      });
      if (scriptDomain !== 'all') {
        params.set('domain', scriptDomain);
      }
      const res = await fetch(`/api/scripts?${params.toString()}`, { headers: getHeaders(), signal: controller.signal });
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
      if (res.ok) {
        const payload = await res.json();
        if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
        if (Array.isArray(payload)) {
          setScripts(payload);
          setTotalScripts(payload.length);
        } else {
          const data = payload?.data || payload || {};
          setScripts(Array.isArray(data.items) ? data.items : []);
          setTotalScripts(Number(data.total || 0));
        }
      } else {
        setScripts([]);
        setTotalScripts(0);
        setLoadError(res.status === 401 ? 'auth' : res.status === 403 ? 'permission' : 'request');
      }
    } catch {
      if (controller.signal.aborted || requestSequence !== requestSequenceRef.current) return;
      setScripts([]);
      setTotalScripts(0);
      setLoadError('request');
    } finally {
      if (requestSequence === requestSequenceRef.current) {
        setLoading(false);
        if (activeRequestRef.current === controller) activeRequestRef.current = null;
      }
    }
  }, [getHeaders, searchQuery, platformFilter, categoryFilter, typeFilter, statusFilter, currentPage, pageSize, scriptDomain]);

  const fetchUsers = async () => {
    try {
      const res = await fetch('/api/scripts/approvers', { headers: getHeaders() });
      if (res.ok) {
        const payload = await res.json();
        setUsers(Array.isArray(payload.items) ? payload.items : []);
      }
      const meRes = await fetch('/api/session', { headers: getHeaders() });
      if (meRes.ok) {
        const data = await meRes.json();
        setCurrentUser(data.user?.username || 'admin');
      }
    } catch (err) {}
  };

  useEffect(() => {
    if (view === 'scripts') {
      void fetchScripts();
    } else {
      activeRequestRef.current?.abort();
      requestSequenceRef.current += 1;
      setScripts([]);
      setTotalScripts(0);
      setLoadError('');
      setLoading(false);
    }
    return () => {
      requestSequenceRef.current += 1;
      activeRequestRef.current?.abort();
      activeRequestRef.current = null;
    };
  }, [fetchScripts, view]);

  useEffect(() => {
    fetchUsers();
  }, [getHeaders]);

  const handleAction = async (targetStatus: string, reason?: string) => {
    const isEdit = modalMode === 'edit';
    const url = isEdit ? `/api/scripts/${encodeURIComponent(editForm.id!)}` : '/api/scripts';
    
    const payload = {
      ...editForm,
      status: targetStatus,
      rejected_reason: reason || '',
      updated_at: new Date().toISOString()
    };

    try {
      const res = await fetch(url, {
        method: isEdit ? 'PUT' : 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast(zh ? '操作成功' : 'Success', 'success');
        setIsModalOpen(false); setValidationResult(null); setShowOutputChecker(false);
        setShowConfirmModal(false);
        setShowRejectPrompt(false);
        fetchScripts();
      } else {
        const errBody = await res.json().catch(() => ({}));
        showToast(errBody?.detail || (zh ? '操作失败，请检查表单或权限' : 'Operation failed'), 'error');
      }
    } catch (err) {
      showToast(zh ? '同步失败' : 'Failed', 'error');
    }
  };

  const availableReviewers = useMemo(() => 
    users.filter(u => u.username !== currentUser && u.username.toLowerCase().includes(auditorSearch.toLowerCase())), 
  [users, currentUser, auditorSearch]);

  // The TextFSM catalog is the canonical platform vocabulary used by both
  // network scripts and NSOT collection operations. Linux remains available
  // for host-side shell scripts.
  const PLATFORM_OPTIONS: Array<{ value: string; zh: string; en: string }> = [
    { value: 'All', zh: '全部平台', en: 'All platforms' },
    { value: 'Linux', zh: 'Linux', en: 'Linux' },
    ...TEXTFSM_VENDOR_OPTIONS.map((vendor) => ({ value: vendor.value, zh: vendor.label, en: vendor.labelEn })),
  ];

  const SCRIPT_TYPE_OPTIONS: Array<{ value: string; zh: string; en: string }> = [
    { value: 'shell', zh: 'Shell', en: 'Shell' },
    { value: 'python', zh: 'Python', en: 'Python' },
    { value: 'cli', zh: 'CLI 网络命令行', en: 'CLI (Network)' },
  ];

  // Search/filtering and pagination are server-side. The browser keeps only
  // the current page instead of loading the entire script catalog.
  const filteredScripts = scripts;
  const paginatedScripts = scripts;

  const getPlatformLabel = (platform: string): string => {
    if (!platform) return '—';
    if (platform.toLowerCase() === 'linux') return 'Linux';
    const selection = getEditorSelection(platform);
    const vendor = getVendorOption(selection.vendor);
    const family = getPlatformFamilyOption(selection.platformFamily);
    const version = TEXTFSM_VERSION_LABELS[selection.version];
    const vendorLabel = zh ? vendor?.label : vendor?.labelEn;
    const familyLabel = zh ? family?.label : family?.labelEn;
    const versionLabel = selection.version !== 'common' && version ? ` ${zh ? version.label : version.labelEn}` : '';
    return `${vendorLabel || selection.vendor} ${familyLabel || selection.platformFamily}${versionLabel}`;
  };

  const exportScripts = useCallback(async () => {
    const params = new URLSearchParams({
      q: searchQuery.trim(),
      platform: platformFilter === 'All' ? '' : platformFilter,
      category: categoryFilter === 'all' ? '' : categoryFilter,
      script_type: typeFilter === 'All' ? '' : typeFilter,
      status: statusFilter === 'All' ? '' : statusFilter,
    });
    if (scriptDomain !== 'all') params.set('domain', scriptDomain);
    const allScripts = await fetchAllPaginatedItems<Script>('/api/scripts', params);
    return {
      headers: [
        zh ? '脚本名称' : 'Name',
        zh ? '适用平台' : 'OS/Platform',
        zh ? '分类' : 'Category',
        zh ? '类型' : 'Type',
        zh ? '状态' : 'Status',
        zh ? '提交人' : 'Author',
        zh ? '描述' : 'Description',
      ],
      rows: allScripts.map((script) => [
        script.name,
        getPlatformLabel(script.platform),
        script.category === 'change'
          ? (zh ? '配置下发' : 'Change')
          : script.category === 'standard'
            ? (zh ? '性能指标' : 'Metric')
            : (zh ? '周期巡检' : 'Inspection'),
        script.script_type,
        getStatusLabel(script.status),
        script.submitter_name || script.author || 'system',
        script.description || '—',
      ]),
    };
  }, [searchQuery, platformFilter, categoryFilter, typeFilter, statusFilter, zh]);

  const resetFilters = () => {
    setSearchQuery('');
    setPlatformFilter('All');
    setCategoryFilter('all');
    setTypeFilter('All');
    setStatusFilter('All');
    setCurrentPage(1);
  };

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, platformFilter, categoryFilter, typeFilter, statusFilter]);

  const isSystemScript = editForm.submitter_name === 'system' || editForm.author === 'system';
  const isReviewMode = editForm.status === 'pending_audit' && editForm.approver_username === currentUser;
  const isReadOnly = isReviewMode || editForm.status === 'released' || (editForm.status === 'pending_audit' && editForm.submitter_name === currentUser) || isSystemScript;
  const editorRisk = useMemo(() => analyzeScriptRisk(editForm.content, zh), [editForm.content, zh]);

  const inputClass = `w-full bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-2.5 text-[13px] outline-none transition-all ${isReadOnly ? 'text-slate-400 cursor-not-allowed opacity-70' : 'text-slate-700 dark:text-slate-100 focus:ring-2 focus:ring-[#2563eb]/20'}`;
  const labelClass = "text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-1.5 flex items-center gap-1.5";

  return (
    <div className="flex flex-col h-full bg-transparent overflow-hidden">
      <PageHero
        icon={Terminal}
        title={
          scriptDomain === 'network'
            ? (zh ? '网络设备脚本' : 'Network Device Scripts')
            : scriptDomain === 'server'
              ? (zh ? '服务器脚本' : 'Server Scripts')
              : (zh ? '操作管理' : 'Ops')
        }
        subtitle={
          scriptDomain === 'network'
            ? (zh ? '交换机 / 防火墙 / 无线 AC / 路由器巡检与运维脚本' : 'Switch, firewall, wireless AC & router scripts')
            : scriptDomain === 'server'
              ? (zh ? 'Linux / Windows 服务器性能指标、一键深度巡检与系统脚本' : 'Linux & Windows server metrics, inspection & ops scripts')
              : (zh ? '自动化脚本与系统操作' : 'Automation scripts and system operations')
        }
        accent={BRAND_COLOR}
        compact={view === 'nsot'}
      />

      <div className={`flex-1 overflow-y-auto px-6 no-scrollbar ${view === 'nsot' ? 'py-3 space-y-3' : 'py-5 space-y-6'}`}>
        <ListToolbar
          className="py-1"
          leadingAction={view === 'scripts' ? (
            <ActionButton
              icon={Plus}
              variant="primary"
              size="md"
              onClick={() => { setModalMode('create'); setEditForm({ platform: scriptDomain === 'network' ? 'h3c_comware' : 'Linux', script_type: scriptDomain === 'network' ? 'cli' : 'shell', category: 'inspection', version: 'v1.0.0', status: 'draft' }); setIsModalOpen(true); }}
            >
              {zh ? '新建' : 'New'}
            </ActionButton>
          ) : view === 'nsot' ? (
            <ActionButton
              icon={Plus}
              variant="primary"
              size="md"
              onClick={() => setNsotCreateRequest((current) => current + 1)}
            >
              {zh ? '新建' : 'New'}
            </ActionButton>
          ) : undefined}
        >
          <div className="relative min-w-[220px] max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500" size={14} />
            <input
              type="search"
              aria-label={zh ? '搜索操作名称、命令或描述' : 'Search operation name, command, or description'}
              placeholder={zh ? '搜索操作名称、命令或描述...' : 'Search operation name, command, or description...'}
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
              className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-xs text-slate-700 outline-none focus:border-blue-500 dark:border-white/10 dark:bg-slate-900 dark:text-white"
            />
          </div>
          {(view === 'scripts' || view === 'nsot') && (
            <button
              type="button"
              onClick={() => setShowAdvancedFilters((current) => !current)}
              className={`flex shrink-0 items-center gap-2 rounded-xl border px-4 py-2.5 text-xs font-bold transition-all ${showAdvancedFilters ? 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300' : 'border-slate-200 text-slate-500 hover:border-blue-200 hover:text-blue-700 dark:border-white/10 dark:text-slate-400 dark:hover:border-blue-500/30 dark:hover:text-blue-300'}`}
            >
              <Filter size={15} />
              {zh ? '高级搜索' : 'Advanced search'}
              {showAdvancedFilters ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
          {view === 'nsot' && (
            <ActionIconButton
              icon={RotateCcw}
              label={zh ? '刷新目录' : 'Refresh catalog'}
              variant="accent"
              onClick={() => setNsotRefreshRequest((current) => current + 1)}
            />
          )}
        </ListToolbar>

        {view === 'scripts' && showAdvancedFilters && (
          <div className="flex flex-col gap-4 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 dark:border-white/10 dark:bg-slate-900/20">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              <label className="flex flex-col gap-1.5 text-[11px] font-bold text-slate-500 dark:text-slate-400">
                <span>{zh ? '平台' : 'Platform'}</span>
                <select value={platformFilter} onChange={(e) => { setPlatformFilter(e.target.value); setCurrentPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none focus:border-[#2563eb] dark:border-white/10 dark:bg-slate-900 dark:text-slate-200">
                  {PLATFORM_OPTIONS.map((option) => <option key={option.value} value={option.value}>{zh ? option.zh : option.en}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-[11px] font-bold text-slate-500 dark:text-slate-400">
                <span>{zh ? '分类' : 'Category'}</span>
                <select value={categoryFilter} onChange={(e) => { setCategoryFilter(e.target.value as typeof categoryFilter); setCurrentPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none focus:border-[#2563eb] dark:border-white/10 dark:bg-slate-900 dark:text-slate-200">
                  <option value="all">{zh ? '全部分类' : 'All categories'}</option>
                  <option value="inspection">{zh ? '巡检采集' : 'Inspection / collect'}</option>
                  <option value="change">{zh ? '配置下发' : 'Change / push'}</option>
                  <option value="system">{zh ? '系统内置' : 'System built-in'}</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-[11px] font-bold text-slate-500 dark:text-slate-400">
                <span>{zh ? '类型' : 'Type'}</span>
                <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setCurrentPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none focus:border-[#2563eb] dark:border-white/10 dark:bg-slate-900 dark:text-slate-200">
                  <option value="All">{zh ? '全部类型' : 'All types'}</option>
                  <option value="shell">Shell</option>
                  <option value="python">Python</option>
                  <option value="cli">CLI</option>
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-[11px] font-bold text-slate-500 dark:text-slate-400">
                <span>{zh ? '状态' : 'Status'}</span>
                <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none focus:border-[#2563eb] dark:border-white/10 dark:bg-slate-900 dark:text-slate-200">
                  <option value="All">{zh ? '全部状态' : 'All statuses'}</option>
                  <option value="draft">{zh ? '草稿' : 'Draft'}</option>
                  <option value="pending_audit">{zh ? '待审核' : 'Pending audit'}</option>
                  <option value="released">{zh ? '已发布' : 'Released'}</option>
                  <option value="rejected">{zh ? '已驳回' : 'Rejected'}</option>
                </select>
              </label>
            </div>
            <div className="flex items-center justify-between gap-3 border-t border-slate-200/70 pt-3 text-xs dark:border-white/10">
              <span className="text-slate-400">{zh ? '平台名称与版本沿用 TextFSM 平台目录；脚本审核状态仅对脚本来源生效。' : 'Platform names and versions follow the TextFSM catalog; script review status applies only to script sources.'}</span>
              <button type="button" onClick={resetFilters} className="inline-flex shrink-0 items-center gap-1.5 font-semibold text-slate-500 hover:text-[#2563eb]"><RotateCcw size={13} />{zh ? '重置筛选' : 'Reset'}</button>
            </div>
          </div>
        )}

        {view === 'nsot' && showAdvancedFilters && (
          <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 dark:border-white/10 dark:bg-slate-900/20 sm:flex-row sm:items-end sm:justify-between">
            <label className="flex w-full flex-col gap-1.5 text-[11px] font-bold text-slate-500 dark:text-slate-400 sm:max-w-xs">
              <span>{zh ? '厂商' : 'Vendor'}</span>
              <select value={nsotVendorFilter} onChange={(e) => setNsotVendorFilter(e.target.value)} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none focus:border-[#2563eb] dark:border-white/10 dark:bg-slate-900 dark:text-slate-200">
                <option value="All">{zh ? '全部厂商' : 'All vendors'}</option>
                {TEXTFSM_VENDOR_OPTIONS.map((vendor) => <option key={vendor.value} value={vendor.value}>{zh ? vendor.label : vendor.labelEn}</option>)}
              </select>
            </label>
            <div className="flex items-center justify-between gap-3 border-t border-slate-200/70 pt-3 text-xs dark:border-white/10 sm:flex-1 sm:justify-end sm:border-t-0 sm:pt-0">
              <span className="text-slate-400">{zh ? '厂商筛选会同步限定可选 TextFSM 平台 / 版本。' : 'The vendor filter also limits available TextFSM platforms and versions.'}</span>
              <button type="button" onClick={() => setNsotVendorFilter('All')} className="inline-flex shrink-0 items-center gap-1.5 font-semibold text-slate-500 hover:text-[#2563eb]"><RotateCcw size={13} />{zh ? '重置' : 'Reset'}</button>
            </div>
          </div>
        )}

        {view === 'scripts' && <div className="rounded-[24px] border border-slate-100 dark:border-white/5 overflow-hidden bg-white dark:bg-slate-900/20 shadow-lg">
          <div className="overflow-x-auto no-scrollbar">
            <DataTable unstyled exportConfig={{ filename: 'scripts', language: zh ? 'zh' : 'en', disabled: loading || scripts.length === 0, exportData: exportScripts }} className="nx-data-table text-left text-sm">
              <thead>
                <tr className="bg-slate-50/50 dark:bg-slate-800/30 border-b border-slate-100 dark:border-white/5">
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '脚本名称' : 'Name'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '适用平台' : 'OS/Platform'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '分类' : 'Category'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '类型' : 'Type'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '状态' : 'Status'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '提交人' : 'Author'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">{zh ? '描述' : 'Description'}</th>
                  <TableActionHeader className="px-6 py-4 text-[11px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider w-28 text-right">{zh ? '操作' : 'Actions'}</TableActionHeader>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {loading ? (
                  <tr>
                    <td colSpan={8} role="status" className="px-6 py-12 text-center text-[12px] text-slate-400 italic">
                      {zh ? '正在加载脚本…' : 'Loading scripts…'}
                    </td>
                  </tr>
                ) : loadError ? (
                  <tr>
                    <td colSpan={8}>
                      <div role="alert" className="flex flex-col items-center gap-3 px-6 py-10 text-center text-[12px] text-rose-700 dark:text-rose-300">
                        <span>{loadError === 'auth'
                          ? (zh ? '登录状态已失效，请重新登录。' : 'Your session has expired. Please sign in again.')
                          : loadError === 'permission'
                            ? (zh ? '你没有查看操作脚本的权限。' : 'You do not have permission to view operation scripts.')
                            : (zh ? '脚本列表加载失败，请重试。' : 'Failed to load scripts. Please retry.')}</span>
                        <button type="button" onClick={() => void fetchScripts()} className="rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 dark:border-rose-500/30 dark:bg-slate-900 dark:text-rose-300">
                          {zh ? '重试' : 'Retry'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ) : paginatedScripts.length > 0 ? (
                    paginatedScripts.map((script) => {
                      const isSystem = script.submitter_name === 'system' || script.author === 'system';
                      return (
                        <motion.tr
                          key={script.id}
                          initial={reduceMotion ? false : { opacity: 0 }}
                          animate={{ opacity: 1 }}
                          transition={{ duration: reduceMotion ? 0 : 0.14 }}
                          className="hover:bg-slate-50/40 dark:hover:bg-slate-800/20 transition-colors group"
                        >
                          <td className="px-6 py-3.5">
                            <div data-export-primary className="flex items-center gap-2 font-bold text-slate-700 dark:text-slate-200 text-[13px]">
                              <span>{script.name}</span>
                              {script.risk_level === 'high' && (
                                <span title={(script.risk_findings || []).join('；')} className="shrink-0 rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-bold text-rose-600 dark:text-rose-400">
                                  {zh ? '高危' : 'High Risk'}
                                </span>
                              )}
                              {script.risk_level === 'medium' && (
                                <span title={(script.risk_findings || []).join('；')} className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-600 dark:text-amber-400">
                                  {zh ? '中危' : 'Med Risk'}
                                </span>
                              )}
                            </div>
                            <div data-export-ignore className="text-[10px] text-slate-400 dark:text-slate-500 font-mono mt-0.5">{script.id}</div>
                          </td>
                          <td className="px-6 py-3.5 text-[12px] font-semibold text-slate-600 dark:text-slate-300">
                            {getPlatformLabel(script.platform)}
                          </td>
                          <td className="px-6 py-3.5">
                            <span className={`px-2 py-0.5 rounded text-[11px] font-medium ${script.category === 'change' ? 'bg-amber-500/10 text-amber-500' : 'bg-cyan-500/10 text-[#2563eb]'}`}>
                              {script.category === 'change' ? (zh ? '配置下发' : 'Change') : (script.category === 'standard' ? (zh ? '性能指标' : 'Metric') : (zh ? '周期巡检' : 'Inspection'))}
                            </span>
                          </td>
                          <td className="px-6 py-3.5">
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-[10px] font-bold uppercase bg-slate-100 dark:bg-slate-800/80 text-slate-500 dark:text-slate-400 border border-slate-200/50 dark:border-slate-700/50">
                              {script.script_type}
                            </span>
                          </td>
                          <td className="px-6 py-3.5">
                            <span className={`inline-flex px-2.5 py-0.5 rounded-full text-[9px] font-bold uppercase border ${STATUS_MAP[script.status]?.bg || STATUS_MAP.draft.bg} ${STATUS_MAP[script.status]?.color || STATUS_MAP.draft.color} ${STATUS_MAP[script.status]?.border || STATUS_MAP.draft.border}`}>
                              {getStatusLabel(script.status)}
                            </span>
                          </td>
                          <td className="px-6 py-3.5 text-[12px] text-slate-500 dark:text-slate-400 font-medium">
                            {script.submitter_name || script.author || 'system'}
                          </td>
                          <td className="px-6 py-3.5 text-[12px] text-slate-400 dark:text-slate-500 max-w-xs truncate" title={script.description}>
                            {script.description || '—'}
                          </td>
                          <td className="px-6 py-3.5 text-right whitespace-nowrap">
                            <ActionIconGroup label={zh ? '脚本操作' : 'Script actions'}>
                              <ActionIconButton
                                icon={Copy}
                                label={zh ? '克隆/复制为自定义脚本' : 'Clone/Copy as custom script'}
                                variant="accent"
                                onClick={() => {
                                  setModalMode('create');
                                  setEditForm({
                                    ...script,
                                    id: `${script.id}_copy`,
                                    name: zh ? `${script.name} - 副本` : `${script.name} (Copy)`,
                                    status: 'draft',
                                    submitter_name: currentUser,
                                    approver_username: '',
                                    rejected_reason: '',
                                  });
                                  setIsModalOpen(true);
                                }}
                              />
                              <ActionIconButton icon={Pencil} label={zh ? '编辑脚本' : 'Edit script'} variant="accent" onClick={() => { setModalMode('edit'); setEditForm(script); setIsModalOpen(true); }} />
                              <ActionIconButton
                                icon={Trash2}
                                label={isSystem ? (zh ? '系统脚本不可删除' : 'System script cannot be deleted') : (zh ? '删除脚本' : 'Delete script')}
                                variant="danger"
                                disabled={isSystem}
                                onClick={() => { if(window.confirm(zh?'删除？':'Delete?')) fetch(`/api/scripts/${script.id}`, {method:'DELETE', headers:getHeaders()}).then(fetchScripts) }}
                              />
                            </ActionIconGroup>
                          </td>
                        </motion.tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={8} className="px-6 py-12 text-center text-[12px] text-slate-400 italic">
                        {zh ? '暂无匹配的脚本数据' : 'No scripts found matching the filters'}
                      </td>
                    </tr>
                  )}
              </tbody>
            </DataTable>
          </div>
        </div>}

      </div>


      {view === 'scripts' && (
        <div className="px-10 py-5 bg-transparent border-t border-slate-200/10">
          <Pagination currentPage={currentPage} totalItems={totalScripts} itemsPerPage={pageSize} onPageChange={setCurrentPage} onItemsPerPageChange={(size) => { setPageSize(size); setCurrentPage(1); }} language={language} />
        </div>
      )}

      {/* Main Modal */}
      <AnimatePresence>
        {isModalOpen && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-6">
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => { setIsModalOpen(false); setValidationResult(null); setShowOutputChecker(false); }} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
            <motion.div
              layout
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1, width: '1020px', height: '760px' }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="relative bg-white dark:bg-slate-900 shadow-2xl flex flex-col overflow-hidden border border-white/10 rounded-[32px]"
            >
              <div className="px-10 py-5 border-b border-slate-100 dark:border-white/5 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-4">
                  <div className="flex gap-1.5 mr-2">
                    <div className="w-3 h-3 rounded-full bg-red-500/80" />
                    <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                    <div className="w-3 h-3 rounded-full bg-green-500/80" />
                  </div>
                  <h3 className="text-[15px] font-bold text-slate-800 dark:text-white flex items-center gap-3">
                    {isReviewMode ? (zh ? '脚本审核' : 'Review Script') : (modalMode === 'create' ? (zh ? '新建脚本' : 'New Script') : (zh ? '脚本详情' : 'Script Detail'))}
                    {modalMode === 'edit' && (
                       <span className={`px-2 py-0.5 rounded-md text-[9px] font-bold border ${STATUS_MAP[editForm.status!]?.bg} ${STATUS_MAP[editForm.status!]?.color} ${STATUS_MAP[editForm.status!]?.border}`}>
                          {getStatusLabel(editForm.status!)}
                       </span>
                    )}
                  </h3>
                </div>
                <button onClick={() => { setIsModalOpen(false); setValidationResult(null); setShowOutputChecker(false); }} className="p-2 text-slate-400 hover:text-slate-800 transition-all"><X size={20} /></button>
              </div>

              <div className="flex-1 flex overflow-hidden">
                <div className="w-[280px] p-8 border-r border-slate-100 dark:border-white/5 space-y-8 overflow-y-auto no-scrollbar">
                   <section className="space-y-5">
                      <div>
                         <label className={labelClass}>{zh ? '脚本名称' : 'NAME'}</label>
                         <input readOnly={isReadOnly} className={inputClass} value={editForm.name ?? ''} onChange={e => setEditForm({...editForm, name: e.target.value})} />
                      </div>
                      <div>
                         <label className={labelClass}>{zh ? '唯一标识' : 'ID'}</label>
                         <input disabled={modalMode === 'edit' || isReadOnly} className={inputClass} value={editForm.id ?? ''} onChange={e => setEditForm({...editForm, id: e.target.value.replace(/[^a-zA-Z0-9_\-]/g, '')})} />
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                         <div>
                            <label className={labelClass}>{zh ? '类型' : 'TYPE'}</label>
                            <select disabled={isReadOnly} className={inputClass} value={editForm.script_type ?? 'shell'} onChange={e => setEditForm({...editForm, script_type: e.target.value})}>
                              {SCRIPT_TYPE_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                              ))}
                              {/* 兜底：如果当前值不在已知列表中，仍然渲染原值，避免被静默改写 */}
                              {editForm.script_type && !SCRIPT_TYPE_OPTIONS.some(o => o.value === editForm.script_type) && (
                                <option value={editForm.script_type}>{editForm.script_type}</option>
                              )}
                            </select>
                         </div>
                         <div>
                            <label className={labelClass}>{zh ? '平台' : 'OS'}</label>
                            <select disabled={isReadOnly} className={inputClass} value={editForm.platform ?? 'Linux'} onChange={e => setEditForm({...editForm, platform: e.target.value})}>
                              {PLATFORM_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{zh ? opt.zh : opt.en}</option>
                              ))}
                              {editForm.platform && !PLATFORM_OPTIONS.some(o => o.value === editForm.platform) && (
                                <option value={editForm.platform}>{editForm.platform}</option>
                              )}
                            </select>
                         </div>
                      </div>
                      <div>
                         <label className={labelClass}>{zh ? '脚本分类' : 'CATEGORY'}</label>
                         <select disabled={isReadOnly} className={inputClass} value={editForm.category ?? 'inspection'} onChange={e => setEditForm({...editForm, category: e.target.value})}>
                            <option value="inspection">{zh ? '周期巡检/数据采集' : 'Inspection / Collection'}</option>
                            <option value="change">{zh ? '自动化变更/配置下发' : 'Automation Change'}</option>
                         </select>
                      </div>
                      <div>
                         <label className={labelClass}>{zh ? '描述信息' : 'DESC'}</label>
                         <textarea readOnly={isReadOnly} className={inputClass + " h-32 resize-none"} value={editForm.description ?? ''} onChange={e => setEditForm({...editForm, description: e.target.value})} />
                      </div>
                   </section>
                   
                   {editForm.rejected_reason && (
                     <section className="p-5 bg-rose-500/5 border border-rose-500/10 rounded-2xl">
                        <label className={labelClass + " text-rose-500"}><MessageSquare size={11} /> {zh ? '驳回原因' : 'REASON'}</label>
                        <p className="text-[12px] text-rose-600 dark:text-rose-400 leading-relaxed font-medium mt-2">{editForm.rejected_reason}</p>
                     </section>
                   )}
                </div>

                <div className="flex-1 flex flex-col bg-slate-50/30 dark:bg-black/10">
                   <div className="h-10 bg-slate-100/50 dark:bg-black/20 border-b border-slate-200/50 dark:border-white/5 flex items-center justify-between px-6 shrink-0">
                      <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                         <Terminal size={14} className="text-[#2563eb]" />
                         {zh ? '编辑器' : 'EDITOR'} / {editForm.script_type}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={validating}
                          onClick={() => void handleValidateScript(false)}
                          className="px-3 py-1 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded-lg text-[10px] font-bold border border-emerald-500/20 flex items-center gap-1.5 hover:bg-emerald-500/20 transition-all disabled:opacity-50"
                        >
                          <CheckCircle2 size={12} /> {validating ? (zh ? '校验中...' : 'CHECKING...') : (zh ? '语法预检' : 'SYNTAX CHECK')}
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowOutputChecker((cur) => !cur)}
                          className={`px-3 py-1 rounded-lg text-[10px] font-bold border flex items-center gap-1.5 transition-all ${showOutputChecker ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/20 hover:bg-indigo-500/20'}`}
                        >
                          <SearchCode size={12} /> {zh ? '输出校验' : 'OUTPUT CHECK'}
                        </button>
                        {!isReadOnly && (
                          <button type="button" onClick={handleFormat} className="px-3 py-1 bg-[#2563eb]/10 text-[#2563eb] rounded-lg text-[10px] font-bold border border-[#2563eb]/20 flex items-center gap-1.5 hover:bg-[#2563eb]/20 transition-all">
                            <Wand2 size={12} /> {zh ? '格式化' : 'FORMAT'}
                          </button>
                        )}
                      </div>
                   </div>
                   {editorRisk.level !== 'low' && (
                     <div className={`mx-6 mt-3 flex items-start gap-2.5 rounded-xl border px-4 py-2.5 text-[12px] ${editorRisk.level === 'high' ? 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'}`}>
                       <AlertCircle size={15} className="mt-0.5 shrink-0" />
                       <div>
                         <span className="font-bold">
                           {editorRisk.level === 'high'
                             ? (zh ? '高危命令静态检测告警：' : 'High-risk command detected: ')
                             : (zh ? '中危操作风险提示：' : 'Medium-risk command notice: ')}
                         </span>
                         <span>{editorRisk.findings.join('；')}</span>
                       </div>
                     </div>
                   )}
                   {validationResult && (
                     <div className={`mx-6 mt-2.5 rounded-xl border px-4 py-2.5 text-[11px] ${validationResult.valid ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300'}`}>
                       <div className="font-bold flex items-center gap-1.5">
                         {validationResult.valid ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                         <span>{validationResult.valid ? (zh ? '语法与输出契约校验通过' : 'Syntax & output validation passed') : (zh ? '发现以下校验问题：' : 'Validation issues found:')}</span>
                       </div>
                       {validationResult.syntax_errors.map((err, i) => (
                         <div key={`se-${i}`} className="mt-1">• {err}</div>
                       ))}
                       {validationResult.syntax_warnings.map((warn, i) => (
                         <div key={`sw-${i}`} className="mt-1 text-amber-600 dark:text-amber-400">! {warn}</div>
                       ))}
                       {validationResult.output_validation?.checks?.map((chk, i) => (
                         <div key={`oc-${i}`} className={`mt-1 ${chk.passed ? 'text-emerald-700 dark:text-emerald-300' : 'text-rose-600 dark:text-rose-400'}`}>
                           {chk.passed ? '✓' : '✗'} {chk.rule}：{chk.detail}
                         </div>
                       ))}
                     </div>
                   )}
                   {showOutputChecker && (
                     <div className="mx-6 mt-2.5 rounded-xl border border-indigo-200/70 dark:border-indigo-500/20 bg-white dark:bg-slate-900/70 p-3.5 space-y-2.5 text-[11px]">
                       <div className="grid grid-cols-2 gap-2">
                         <label className="flex flex-col gap-1">
                           <span className="font-bold text-slate-500">{zh ? '期望输出格式' : 'Expected Format'}</span>
                           <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value as typeof outputFormat)} className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 text-xs">
                             <option value="any">{zh ? '任意文本' : 'Any text'}</option>
                             <option value="key_value">{zh ? 'KEY=VALUE / KEY:VALUE 键值' : 'Key-Value pairs'}</option>
                             <option value="json">{zh ? 'JSON 结构化对象' : 'Valid JSON'}</option>
                             <option value="numeric">{zh ? '纯数值指标' : 'Numeric metric'}</option>
                           </select>
                         </label>
                         <label className="flex flex-col gap-1">
                           <span className="font-bold text-slate-500">{zh ? '正则断言（可选）' : 'Regex (optional)'}</span>
                           <input value={outputRegex} onChange={(e) => setOutputRegex(e.target.value)} placeholder="OVERALL_STATUS=PASS" className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 text-xs font-mono" />
                         </label>
                         <label className="flex flex-col gap-1">
                           <span className="font-bold text-slate-500">{zh ? '必须包含关键字（逗号分隔）' : 'Must contain'}</span>
                           <input value={mustContain} onChange={(e) => setMustContain(e.target.value)} placeholder="OVERALL_STATUS, CPU_UTIL" className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 text-xs" />
                         </label>
                         <label className="flex flex-col gap-1">
                           <span className="font-bold text-slate-500">{zh ? '禁止包含异常词（逗号分隔）' : 'Must not contain'}</span>
                           <input value={mustNotContain} onChange={(e) => setMustNotContain(e.target.value)} className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 text-xs" />
                         </label>
                       </div>
                       <textarea value={sampleOutput} onChange={(e) => setSampleOutput(e.target.value)} placeholder={zh ? '粘贴一段样本输出（stdout）后点击“执行输出校验”...' : 'Paste sample stdout here...'} className="w-full h-16 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 px-2.5 py-1.5 font-mono text-[11px] resize-none" />
                       <div className="flex justify-end">
                         <button type="button" disabled={validating} onClick={() => void handleValidateScript(true)} className="rounded-lg bg-indigo-600 px-3.5 py-1.5 text-[11px] font-bold text-white hover:bg-indigo-700 disabled:opacity-50">
                           {zh ? '执行输出校验' : 'Run Output Check'}
                         </button>
                       </div>
                     </div>
                   )}
                   <textarea readOnly={isReadOnly} spellCheck={false} className={`flex-1 bg-transparent font-mono text-[13px] p-8 focus:outline-none resize-none leading-6 no-scrollbar ${isReadOnly ? 'text-slate-500 opacity-60' : 'text-slate-700 dark:text-slate-300'}`} value={editForm.content ?? ''} onChange={e => setEditForm({...editForm, content: e.target.value})} />
                   
                   <div className="h-20 bg-white dark:bg-black/10 border-t border-slate-100 dark:border-white/5 px-10 flex items-center justify-end gap-3 shrink-0">
                      {isReviewMode ? (
                        <>
                          <button onClick={() => setShowRejectPrompt(true)} className="px-10 py-2.5 bg-red-500/10 text-red-500 rounded-xl text-[12px] font-bold border border-red-500/20 hover:bg-red-500 hover:text-white transition-all uppercase tracking-widest">{zh ? '驳回审核' : 'REJECT'}</button>
                          <button onClick={() => handleAction('released')} className="px-14 py-2.5 bg-green-600 text-white rounded-xl text-[12px] font-bold shadow-lg shadow-green-600/20 active:scale-[0.98] transition-all uppercase tracking-widest">{zh ? '通过并发布' : 'APPROVE'}</button>
                        </>
                      ) : isReadOnly ? (
                        <>
                          <button
                            type="button"
                            onClick={() => {
                              setModalMode('create');
                              const rootId = (editForm as any).parent_script_id || editForm.id || 'script';
                              const baseVer = String((editForm as any).version || 'v1.0.0').trim();
                              const verMatch = baseVer.match(/^v?(\d+)\.(\d+)\.(\d+)$/i);
                              const nextVersion = verMatch
                                ? `v${verMatch[1]}.${verMatch[2]}.${Number(verMatch[3]) + 1}`
                                : 'v1.0.1';
                              setEditForm({
                                ...editForm,
                                id: `${rootId}_${nextVersion.replace(/\./g, '_')}`,
                                name: editForm.name || (zh ? '脚本' : 'Script'),
                                version: nextVersion,
                                parent_script_id: rootId,
                                status: 'draft',
                                submitter_name: currentUser,
                                author: currentUser,
                                approver_username: '',
                                rejected_reason: '',
                              } as any);
                              showToast(zh ? '已克隆为可编辑草稿，请修改标识与内容后提交审核' : 'Cloned as editable draft', 'info');
                            }}
                            className="inline-flex items-center gap-1.5 px-6 py-2.5 bg-[#2563eb]/10 text-[#2563eb] rounded-xl text-[12px] font-bold border border-[#2563eb]/20 hover:bg-[#2563eb]/20 transition-all"
                          >
                            <Copy size={14} />
                            {zh ? '克隆为新版本' : 'CLONE AS NEW VERSION'}
                          </button>
                          <button onClick={() => { setIsModalOpen(false); setValidationResult(null); setShowOutputChecker(false); }} className="px-10 py-2.5 bg-slate-100 text-slate-500 rounded-xl text-[12px] font-bold transition-all uppercase tracking-widest">{zh ? '关闭窗口' : 'CLOSE'}</button>
                        </>
                      ) : (
                        <>
                          <button onClick={() => handleAction('draft')} className="px-10 py-2.5 bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400 rounded-xl text-[12px] font-bold transition-all uppercase tracking-widest">{zh ? '保存草稿' : 'DRAFT'}</button>
                          <button onClick={() => setShowConfirmModal(true)} className="px-14 py-2.5 bg-[#2563eb] text-white rounded-xl text-[12px] font-bold shadow-xl shadow-[#2563eb]/20 active:scale-[0.98] transition-all uppercase tracking-widest">{zh ? '提交审核' : 'SUBMIT'}</button>
                        </>
                      )}
                   </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Searchable Confirm Audit Modal */}
      <AnimatePresence>
        {showConfirmModal && (
          <div className="fixed inset-0 z-[120] flex items-center justify-center overflow-y-auto p-4 sm:p-6">
             <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowConfirmModal(false)} className="absolute inset-0 bg-black/60 backdrop-blur-md" />
             <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="relative my-auto w-full max-w-sm max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-700 dark:bg-slate-900">
                <h3 className="mb-5 text-base font-semibold text-slate-800 dark:text-white">{zh ? '指派审核人' : 'Assign Reviewer'}</h3>

                <div className="mb-5">
                   <label htmlFor="script-reviewer-search" className={labelClass}>{zh ? '审核人搜索' : 'SEARCH AUDITOR'}</label>
                   <div className="relative">
                      <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
                      <input 
                        id="script-reviewer-search"
                        type="search"
                        placeholder={zh ? "输入用户名搜索..." : "Search user..."}
                        value={auditorSearch}
                        onFocus={() => setShowAuditorDropdown(true)}
                        onChange={(e) => setAuditorSearch(e.target.value)}
                        aria-autocomplete="list"
                        aria-expanded={showAuditorDropdown}
                        aria-controls="script-reviewer-results"
                         className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2.5 pl-10 pr-4 text-[13px] text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                      />
                   </div>

                   <AnimatePresence>
                      {showAuditorDropdown && (
                        <motion.div 
                          id="script-reviewer-results"
                          role="listbox"
                          aria-label={zh ? '审核人搜索结果' : 'Reviewer search results'}
                          initial={{ opacity: 0, y: -4 }}
                          animate={{ opacity: 1, y: 0 }} 
                          exit={{ opacity: 0, y: -4 }}
                          className="mt-2 max-h-40 overflow-y-auto rounded-lg border border-slate-200 bg-white no-scrollbar dark:border-slate-700 dark:bg-slate-800"
                        >
                           {availableReviewers.length > 0 ? (
                             availableReviewers.map(u => (
                               <button
                                 key={u.username} 
                                 type="button"
                                 role="option"
                                 aria-selected={editForm.approver_username === u.username}
                                 onClick={() => { setEditForm({...editForm, approver_username: u.username}); setAuditorSearch(u.username); setShowAuditorDropdown(false); }}
                                 className={`flex min-h-10 w-full items-center justify-between px-3 py-2.5 text-left text-[13px] transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 dark:hover:bg-slate-700/60 ${editForm.approver_username === u.username ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300' : 'text-slate-600 dark:text-slate-300'}`}
                               >
                                  {u.username}
                                  {editForm.approver_username === u.username && <CheckCircle2 size={14} />}
                               </button>
                             ))
                           ) : (
                             <div className="px-3 py-4 text-center text-xs text-slate-400">{zh ? '未找到相关用户' : 'No users found'}</div>
                           )}
                        </motion.div>
                      )}
                   </AnimatePresence>
                </div>

                <div className="flex flex-col gap-2">
                  <button 
                    disabled={!editForm.approver_username} 
                    onClick={() => handleAction('pending_audit')} 
                    className="w-full rounded-lg bg-blue-600 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {zh ? '发送审核申请' : 'SUBMIT FOR REVIEW'}
                  </button>
                  <button onClick={() => setShowConfirmModal(false)} className="w-full rounded-lg py-2 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-300 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200">{zh ? '取消' : 'CANCEL'}</button>
                </div>
             </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Reject Reason Prompt */}
      <AnimatePresence>
        {showRejectPrompt && (
          <div className="fixed inset-0 z-[120] flex items-center justify-center p-6">
             <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowRejectPrompt(false)} className="absolute inset-0 bg-black/60 backdrop-blur-md" />
             <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} className="relative w-full max-w-sm bg-white dark:bg-slate-900 rounded-[32px] p-10 shadow-2xl border border-white/10">
                <XCircle size={32} className="text-red-500 mb-6" />
                <h3 className="text-lg font-bold text-slate-800 dark:text-white mb-2">{zh ? '驳回审核' : 'Reject Submission'}</h3>
                <p className="text-[12px] text-slate-400 mb-6">{zh ? '请说明驳回原因，提交人将收到反馈。' : 'Provide a reason for rejection.'}</p>
                <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)} className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3 text-[13px] h-32 resize-none mb-8 outline-none" placeholder={zh ? "请输入驳回原因..." : "Reason..."} />
                <button disabled={!rejectReason.trim()} onClick={() => handleAction('rejected', rejectReason)} className="w-full py-4 bg-red-500 text-white rounded-2xl text-[13px] font-bold shadow-xl shadow-red-500/20 disabled:opacity-30">
                  {zh ? '执行驳回' : 'REJECT'}
                </button>
             </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ScriptManagementTab;
