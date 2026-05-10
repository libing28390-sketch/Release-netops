import React, { useState, useMemo, useRef, useEffect } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Cpu,
  Database,
  Download,
  ExternalLink,
  FileText,
  Filter,
  FolderTree,
  History,
  LayoutGrid,
  List,
  Maximize2,
  Minimize2,
  Monitor,
  Play,
  Plus,
  RotateCcw,
  Search,
  Server,
  Shield,
  Terminal,
  Ticket,
  Trash2,
  X,
  XCircle,
  Zap, Settings, ShieldCheck, User, MonitorSpeaker, Check,
} from 'lucide-react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import 'xterm/css/xterm.css';
import { motion, AnimatePresence } from 'motion/react';
import type { Device, TagDefinition } from '../types';
import Pagination from '../components/Pagination';
import TagFilterDropdown from '../components/TagFilterDropdown';
import OutputActions from '../components/OutputActions';

/* ─────────── Types ─────────── */
interface ScenarioVariable {
  key: string;
  label?: string;
  label_zh?: string;
  required?: boolean;
  type?: string;
  placeholder?: string;
  platform_hints?: Record<string, string>;
}

interface AutomationScenario {
  id: string;
  icon?: string;
  risk: 'low' | 'medium' | 'high';
  name: string;
  name_zh?: string;
  description: string;
  description_zh?: string;
  supported_platforms?: string[];
  default_platform?: string;
  variables?: ScenarioVariable[];
  category?: string;
}

interface QuickPlaybookPreview {
  pre_check?: string[];
  execute?: string[];
  post_check?: string[];
  rollback?: string[];
}

interface QuickQueryTable {
  category: any;
  records: Record<string, any>[];
  columns: string[];
}

interface DeviceExecutionPhase {
  success: boolean;
  output?: string;
}

interface DeviceExecutionState {
  hostname: string;
  status: string;
  phases: Record<string, DeviceExecutionPhase>;
  error?: string;
}

interface AutomationExecuteTabProps {
  t: (key: string) => string;
  language: string;
  sectionHeaderRowClass: string;
  devices: Device[];
  selectedDevice: Device | null;
  batchMode: boolean;
  batchDeviceIds: string[];
  automationSearch: string;
  scenarioSearch: string;
  changeTicket?: string;
  setChangeTicket?: (val: string) => void;
  savedQueries: any[];
  filteredScenarios: AutomationScenario[];
  quickPlaybookScenario: AutomationScenario | null;
  quickPlaybookVars: Record<string, string>;
  quickPlaybookPlatform: string;
  quickPlaybookDryRun: boolean;
  quickPlaybookConcurrency: number;
  quickPlaybookPreview: QuickPlaybookPreview | null;
  quickRiskConfirmed: boolean;
  hasQuickTargets: boolean;
  quickMissingRequiredFields: string[];
  quickHasMixedPlatforms: boolean;
  quickPlatformMismatch: boolean;
  isQuickPlaybookRunning: boolean;
  quickExecutionResult: any;
  executionStatus: string;
  wsCompleteMsg: any;
  deviceStatusMap: Record<string, DeviceExecutionState>;
  quickQueryRunning: boolean;
  quickQueryOutput: string;
  quickQueryLabel: string;
  quickQueryStructured: any;
  quickQueryView: 'terminal' | 'table';
  quickQueryMaximized: boolean;
  quickQueryCommands: string[];
  quickQueryTable: QuickQueryTable;
  onNavigate: (path: string) => void;
  onAutomationSearchChange: (value: string) => void;
  onScenarioSearchChange: (value: string) => void;
  onToggleBatchMode: () => void;
  onToggleBatchDevice: (deviceId: string) => void;
  onSelectDevice: (device: Device) => void;
  onOpenCustomCommandModal: () => void;
  onOpenScenario: (scenario: AutomationScenario) => void;
  onClearScenario: () => void;
  onQuickPlaybookVarChange: (key: string, value: string) => void;
  onQuickPlaybookConcurrencyChange: (value: number) => void;
  onQuickRiskConfirmedChange: (value: boolean) => void;
  onRunValidation: (changeTicket?: string) => void;
  onRunApply: (changeTicket?: string) => void;
  onRunQuickQuery: (label: string, commands: string, operationalCategory?: string, authRole?: string) => void;
  onResetQuickQuery: () => void;
  onQuickQueryViewChange: (view: 'terminal' | 'table') => void;
  onQuickQueryMaximizedChange: (value: boolean) => void;
  onOpenCommandPreview: () => void;
  onExportQuickQueryTable: (commands: string[]) => void;
  copyTextWithFallback: (text: string) => Promise<boolean>;
  showToast: (message: string, tone: 'success' | 'error' | 'warning' | 'info') => void;
  onResetExecutionState: () => void;
  getPlatformLabel: (platform: string) => string;
}

/* ─────────── Helpers ─────────── */
const VENDOR_MAP: Record<string, string> = {
  cisco_ios: 'Cisco', cisco_nxos: 'Cisco', cisco_iosxe: 'Cisco',
  huawei_vrp: 'Huawei', h3c_comware: 'H3C',
  arista_eos: 'Arista', juniper_junos: 'Juniper',
};
const getVendor = (p: string) => VENDOR_MAP[p] || 'Other';

const getDeviceCategory = (d: Device): 'network' | 'server' => {
  const p = (d.platform || '').toLowerCase();
  const serverKeywords = ['linux', 'ubuntu', 'centos', 'windows', 'debian', 'redhat', 'esxi', 'docker', 'alma', 'rocky', 'oracle', 'server', 'service'];
  const r = (d.role || '').toLowerCase();
  if (serverKeywords.some(kw => p.includes(kw)) || serverKeywords.some(kw => r.includes(kw))) {
    return 'server';
  }
  return 'network';
};

const CATEGORY_META: Record<string, { label: string; labelEn: string; icon: string; color: string }> = {
  L2: { label: '二层网络', labelEn: 'L2 Network', icon: '🔗', color: 'text-cyan-600' },
  L3: { label: '三层路由', labelEn: 'L3 Routing', icon: '🗺️', color: 'text-violet-600' },
  Security: { label: '安全策略', labelEn: 'Security', icon: '🛡️', color: 'text-rose-600' },
  Operations: { label: '运维工具', labelEn: 'Operations', icon: '🔧', color: 'text-amber-600' },
  Custom: { label: '自定义', labelEn: 'Custom', icon: '⭐', color: 'text-cyan-600' },
};

const RISK_CONFIG = {
  high: { label: '高危', labelEn: 'HIGH', bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', dot: 'bg-red-500', stripe: 'border-l-red-500', glow: 'shadow-red-500/10' },
  medium: { label: '中等', labelEn: 'MED', bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', dot: 'bg-amber-500', stripe: 'border-l-amber-400', glow: 'shadow-amber-500/10' },
  low: { label: '低风', labelEn: 'LOW', bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-500', stripe: 'border-l-emerald-400', glow: 'shadow-emerald-500/10' },
};

const classifyVarGroup = (v: ScenarioVariable) => {
  const text = `${v?.key || ''} ${v?.label || ''}`.toLowerCase();
  if (/ip|prefix|mask|gateway|network|neighbor|next_hop|peer/.test(text)) return 'address';
  if (/interface|port|intf|vlan/.test(text)) return 'interface';
  if (/asn|as\b|route|bgp|ospf|policy|metric|community/.test(text)) return 'routing';
  return 'general';
};

const VAR_GROUP_ORDER = ['address', 'interface', 'routing', 'general'];

/* ─────────── Step Definitions ─────────── */
type StepId = 1 | 2 | 3 | 4;
const STEPS = [
  { id: 1 as StepId, label: '选择设备', labelEn: 'Select Devices', icon: Server },
  { id: 2 as StepId, label: '选择任务', labelEn: 'Select Task', icon: Zap },
  { id: 3 as StepId, label: '参数配置', labelEn: 'Configure', icon: FileText },
  { id: 4 as StepId, label: '执行结果', labelEn: 'Execute', icon: Terminal },
];

/* ═══════════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════════ */
const AutomationExecuteTab: React.FC<AutomationExecuteTabProps> = (props) => {
  const {
    t, language, devices, selectedDevice, batchMode, batchDeviceIds,
    automationSearch, scenarioSearch, changeTicket: propChangeTicket, setChangeTicket: propSetChangeTicket,
    savedQueries,
    filteredScenarios,
    quickPlaybookScenario, quickPlaybookVars, quickPlaybookPlatform,
    quickPlaybookDryRun, quickPlaybookConcurrency, quickPlaybookPreview,
    quickRiskConfirmed, hasQuickTargets, quickMissingRequiredFields,
    quickHasMixedPlatforms, quickPlatformMismatch,
    isQuickPlaybookRunning, quickExecutionResult, wsCompleteMsg, deviceStatusMap,
    quickQueryRunning, quickQueryOutput, quickQueryLabel, quickQueryStructured,
    quickQueryView, quickQueryMaximized, quickQueryCommands, quickQueryTable,
    onNavigate, onAutomationSearchChange, onScenarioSearchChange,
    onToggleBatchMode, onToggleBatchDevice, onSelectDevice,
    onOpenCustomCommandModal, onOpenScenario, onClearScenario,
    onQuickPlaybookVarChange, onQuickPlaybookConcurrencyChange,
    onQuickRiskConfirmedChange, onRunValidation, onRunApply,
    onRunQuickQuery, onResetQuickQuery, onQuickQueryViewChange,
    onQuickQueryMaximizedChange, onOpenCommandPreview, onExportQuickQueryTable,
    copyTextWithFallback, showToast, onResetExecutionState, getPlatformLabel,
  } = props;

  const isZh = language === 'zh';

  /* ── Local state ── */
  const [currentStep, setCurrentStep] = useState<StepId>(1);
  const [vendorFilter, setVendorFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [siteFilter, setSiteFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all'); // This is for scenarios
  const [deviceTypeFilter, setDeviceTypeFilter] = useState<'all' | 'network' | 'server'>('all');
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [showQuickQuery, setShowQuickQuery] = useState(false);
  const [deviceViewMode, setDeviceViewMode] = useState<'grid' | 'list'>('list');
  const [devicePage, setDevicePage] = useState(1);
  // Fallback to local if props not provided (though they should be)
  const [localChangeTicket, localSetChangeTicket] = useState('');
  const changeTicket = propChangeTicket !== undefined ? propChangeTicket : localChangeTicket;
  const setChangeTicket = propSetChangeTicket || localSetChangeTicket;

  const DEVICE_PAGE_SIZE = 20;
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'validate' | 'apply'>('validate');
  const logEndRef = useRef<HTMLDivElement>(null);
  
  /* --- Professional Terminal States --- */
  const [terminals, setTerminals] = useState<Record<string, { term: XTerm; fit: FitAddon }>>({});
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [selectedAuthRole, setSelectedAuthRole] = useState<'normal' | 'admin'>('normal');
  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [approvalData, setApprovalData] = useState({ ticket: '', reason: '', mfa: '' });
  const [isApproved, setIsApproved] = useState(false);
  const [localTerminalPath, setLocalTerminalPath] = useState(() => localStorage.getItem('local_terminal_path') || '');

  /* Helper to initialize xterm on a ref */
  const initTerminal = (container: HTMLDivElement, id: string) => {
    if (terminals[id]) return;
    const term = new XTerm({
      cursorBlink: true,
      fontSize: 12,
      fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, "Courier New", monospace',
      theme: {
        background: '#0d1117',
        foreground: '#e6edf3',
        cursor: '#00bceb',
      },
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();
    fitAddon.fit();
    
    term.onData(data => {
      // In Automation tab, quick query is usually a triggered event, 
      // but for interactivity we can pipe this if a session is kept open.
      // For now, let's just make it feel interactive.
      if (data === '\r') term.write('\r\n');
      else term.write(data);
    });

    setTerminals(prev => ({ ...prev, [id]: { term, fit: fitAddon } }));
  };

  /* Sync quickQueryOutput to the terminal */
  useEffect(() => {
    const qTerm = terminals['quick-query']?.term;
    if (qTerm && quickQueryOutput) {
      // If it's a fresh start, clear first (basic heuristic)
      if (quickQueryRunning && quickQueryOutput.length < 50) {
        qTerm.clear();
      }
      // Replace \n with \r\n for xterm
      const formatted = quickQueryOutput.replace(/\r?\n/g, '\r\n');
      qTerm.reset(); // Full reset for now as we receive full text, 
                     // in real streaming we would use .write() with diffs
      qTerm.write(formatted);
    }
  }, [quickQueryOutput, terminals, quickQueryRunning]);

  /* Handle resize */
  useEffect(() => {
    if (quickQueryMaximized) {
      setTimeout(() => {
        terminals['quick-query']?.fit.fit();
      }, 300);
    }
  }, [quickQueryMaximized, terminals]);
  /* ── New states for tree filter, drawer, change ticket ── */
  const [expandedTreeNodes, setExpandedTreeNodes] = useState<Set<string>>(new Set());
  const [treeFilterSite, setTreeFilterSite] = useState<string | null>(null);
  const [treeFilterRole, setTreeFilterRole] = useState<string | null>(null);
  const [showSelectedDrawer, setShowSelectedDrawer] = useState(false);
  const [quickQuerySearch, setQuickQuerySearch] = useState('');


  const [ticketValidation, setTicketValidation] = useState<{
    loading: boolean;
    found?: boolean;
    valid?: boolean;
    reason?: string;
    message?: string;
    title?: string;
    status?: string;
    scheduled_start?: string;
    scheduled_end?: string;
  }>({ loading: false });
  const ticketValidateTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  /* Debounced ticket validation */
  useEffect(() => {
    if (ticketValidateTimer.current) clearTimeout(ticketValidateTimer.current);
    const trimmed = changeTicket.trim();
    if (!trimmed || trimmed.length < 4) {
      setTicketValidation({ loading: false });
      return;
    }
    setTicketValidation({ loading: true });
    ticketValidateTimer.current = setTimeout(async () => {
      try {
        const token = localStorage.getItem('netops_token') || '';
        const resp = await fetch(`/api/change-orders/validate-ticket/${encodeURIComponent(trimmed)}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (resp.ok) {
          const json = await resp.json();
          if (json.success) setTicketValidation({ loading: false, ...json.data });
          else setTicketValidation({ loading: false });
        } else {
          setTicketValidation({ loading: false });
        }
      } catch {
        setTicketValidation({ loading: false });
      }
    }, 600);
    return () => { if (ticketValidateTimer.current) clearTimeout(ticketValidateTimer.current); };
  }, [changeTicket]);

  /* ── Derived ── */
  const targetCount = batchMode ? batchDeviceIds.length : (selectedDevice ? 1 : 0);
  const riskNeedsConfirm = quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed;
  const hasMissingRequired = quickMissingRequiredFields.length > 0;
  const previewLineCount = (['pre_check', 'execute', 'post_check', 'rollback'] as const)
    .reduce((acc, phase) => acc + (quickPlaybookPreview?.[phase]?.length || 0), 0);

  const canExecute = quickPlaybookScenario && hasQuickTargets && !isQuickPlaybookRunning
    && !quickHasMixedPlatforms && !quickPlatformMismatch && !hasMissingRequired
    && !(quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed)
    && !(changeTicket.trim().length >= 4 && ticketValidation.found === true && !ticketValidation.valid)
    && !(changeTicket.trim().length >= 4 && ticketValidation.found === false);

  /* Auto-advance to execution step when running starts */
  useEffect(() => {
    if (isQuickPlaybookRunning || quickExecutionResult) setCurrentStep(4);
  }, [isQuickPlaybookRunning, quickExecutionResult]);

  /* Auto-advance when scenario selected */
  useEffect(() => {
    if (quickPlaybookScenario && currentStep < 3) setCurrentStep(3);
  }, [quickPlaybookScenario]);

  /* Auto scroll execution log */
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [deviceStatusMap]);

  /* Filtered devices */
  const filteredDevices = useMemo(() => {
    return devices.filter(d => {
      if (automationSearch) {
        const q = automationSearch.toLowerCase();
        if (!String(d.hostname || '').toLowerCase().includes(q) && !String(d.ip_address || '').includes(q)) return false;
      }
      if (statusFilter !== 'all' && d.status !== statusFilter) return false;
      if (vendorFilter !== 'all') {
        const vendor = getVendor(d.platform);
        if (vendor !== vendorFilter) return false;
      }
      if (siteFilter !== 'all' && (d.site || '') !== siteFilter) return false;
      /* Tag filter */
      /* Tree filter */
      if (treeFilterSite) {
        const dSite = d.site || (isZh ? '未分组' : 'Ungrouped');
        if (dSite !== treeFilterSite) return false;
      }
      if (treeFilterRole) {
        const dRole = d.role || (isZh ? '未分配' : 'Unassigned');
        if (dRole !== treeFilterRole) return false;
      }
      if (deviceTypeFilter !== 'all') {
        const type = getDeviceCategory(d);
        if (type !== deviceTypeFilter) return false;
      }
      return true;
    });
  }, [devices, automationSearch, statusFilter, vendorFilter, siteFilter, treeFilterSite, treeFilterRole, isZh, deviceTypeFilter]);

  /* Device tree structure: site → role → count */
  const deviceTree = useMemo(() => {
    const tree: Array<{ site: string; count: number; onlineCount: number; roles: Array<{ role: string; count: number; onlineCount: number }> }> = [];
    const siteMap = new Map<string, Map<string, { total: number; online: number }>>();
    for (const d of devices) {
      const site = d.site || (isZh ? '未分组' : 'Ungrouped');
      const role = d.role || (isZh ? '未分配' : 'Unassigned');
      if (!siteMap.has(site)) siteMap.set(site, new Map());
      const roleMap = siteMap.get(site)!;
      if (!roleMap.has(role)) roleMap.set(role, { total: 0, online: 0 });
      const c = roleMap.get(role)!;
      c.total++;
      if (d.status === 'online') c.online++;
    }
    for (const [site, roleMap] of Array.from(siteMap.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
      const roles: Array<{ role: string; count: number; onlineCount: number }> = [];
      let siteTotal = 0, siteOnline = 0;
      for (const [role, c] of Array.from(roleMap.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
        roles.push({ role, count: c.total, onlineCount: c.online });
        siteTotal += c.total;
        siteOnline += c.online;
      }
      tree.push({ site, count: siteTotal, onlineCount: siteOnline, roles });
    }
    return tree;
  }, [devices, isZh]);

  /* Reset page when filters change */
  useEffect(() => { setDevicePage(1); }, [automationSearch, statusFilter, vendorFilter, siteFilter, treeFilterSite, treeFilterRole]);

  const pagedDevices = useMemo(() => {
    const start = (devicePage - 1) * DEVICE_PAGE_SIZE;
    return filteredDevices.slice(start, start + DEVICE_PAGE_SIZE);
  }, [filteredDevices, devicePage]);

  /* Unique values for filters */
  const vendors = useMemo(() => [...new Set(devices.map(d => getVendor(d.platform)))].sort(), [devices]);
  const sites = useMemo(() => [...new Set(devices.filter(d => d.site).map(d => d.site))].sort(), [devices]);

  /* Filtered scenarios */
  const displayScenarios = useMemo(() => {
    const selectedDevices = batchMode ? devices.filter(d => batchDeviceIds.includes(d.id)) : (selectedDevice ? [selectedDevice] : []);
    const selectedPlatforms = new Set(selectedDevices.map(d => d.platform));
    const selectedCategories = new Set(selectedDevices.map(d => getDeviceCategory(d)));

    return filteredScenarios.filter(s => {
      if (categoryFilter !== 'all' && (s.category || 'Custom') !== categoryFilter) return false;
      if (riskFilter !== 'all' && s.risk !== riskFilter) return false;
      
      // Filter by platform/category if devices are selected
      if (selectedDevices.length > 0) {
        // If scenario defines supported_platforms, check it
        if (s.supported_platforms && s.supported_platforms.length > 0) {
          const hasMatch = s.supported_platforms.some(sp => selectedPlatforms.has(sp));
          if (!hasMatch) return false;
        }
        
        // Logical filtering: don't show network playbooks for servers and vice versa
        const isNetScenario = s.category === 'L2' || s.category === 'L3' || /vlan|bgp|ospf|route|switch/i.test(s.name + (s.description || ''));
        if (isNetScenario && selectedCategories.has('server') && !selectedCategories.has('network')) return false;
      }

      return true;
    });
  }, [filteredScenarios, categoryFilter, riskFilter, batchMode, batchDeviceIds, devices, selectedDevice]);

  const scenarioCategories = useMemo(() => {
    const cats = new Set(filteredScenarios.map(s => s.category || 'Custom'));
    return ['all', ...Array.from(cats)];
  }, [filteredScenarios]);

  /* Variable groups */
  const groupedVariables = useMemo(() => {
    return (quickPlaybookScenario?.variables || []).reduce((acc: Record<string, ScenarioVariable[]>, v) => {
      const group = classifyVarGroup(v);
      if (!acc[group]) acc[group] = [];
      acc[group].push(v);
      return acc;
    }, {});
  }, [quickPlaybookScenario]);

  /* Blocking issues */
  const needsChangeTicket = quickPlaybookScenario?.risk !== 'low';
  const blockingIssues = useMemo(() => {
    const items: Array<{ message: string; severity: 'critical' | 'high' | 'medium' }> = [];
    if (!hasQuickTargets) items.push({ message: isZh ? '请先选择目标设备' : 'Select target device(s)', severity: 'critical' });
    if (quickHasMixedPlatforms) items.push({ message: isZh ? '检测到多平台设备，请按平台分批执行' : 'Mixed platforms detected', severity: 'critical' });
    if (quickPlatformMismatch) items.push({ message: isZh ? '该场景不支持当前设备平台' : 'Scenario unsupported on platform', severity: 'high' });
    if (hasMissingRequired) items.push({ message: isZh ? `缺少必填字段：${quickMissingRequiredFields.join('、')}` : `Missing: ${quickMissingRequiredFields.join(', ')}`, severity: 'high' });
    if (needsChangeTicket && changeTicket.trim() && ticketValidation.found === true && !ticketValidation.valid) {
      items.push({ message: ticketValidation.message || (isZh ? '变更工单不可用' : 'Change ticket invalid'), severity: 'critical' });
    }
    if (needsChangeTicket && changeTicket.trim().length >= 4 && ticketValidation.found === false) {
      items.push({ message: isZh ? '未找到该工单号，请检查输入' : 'Change ticket not found', severity: 'high' });
    }
    if (riskNeedsConfirm) items.push({ message: isZh ? '请确认高风险执行' : 'Confirm high-risk execution', severity: 'medium' });
    return items;
  }, [hasQuickTargets, quickHasMixedPlatforms, quickPlatformMismatch, hasMissingRequired, riskNeedsConfirm, isZh, quickMissingRequiredFields, needsChangeTicket, changeTicket, ticketValidation]);

  /* Quick Query helpers */
  const targetDevices = batchMode
    ? devices.filter(d => batchDeviceIds.includes(d.id))
    : (selectedDevice ? [selectedDevice] : []);
  const singleDevice = targetDevices[0] || null;
  const hasTargets = targetDevices.length > 0;
  const platform = (singleDevice?.platform || '').toLowerCase();
  const isCisco = platform.includes('cisco') || platform.includes('arista') || platform.includes('rgos');
  const isHuawei = platform.includes('huawei') || platform.includes('h3c') || platform.includes('ce_');
  const isJuniper = platform.includes('juniper') || platform.includes('junos');
  const deviceRole = (singleDevice?.role || '').toLowerCase();

  const filteredQuickQueryRecords = useMemo(() => {
    if (!quickQueryTable.records) return [];
    if (!quickQuerySearch.trim()) return quickQueryTable.records;
    const q = quickQuerySearch.toLowerCase().trim();
    return quickQueryTable.records.filter((rec) => {
      return Object.values(rec).some((val) =>
        String(val || '').toLowerCase().includes(q)
      );
    });
  }, [quickQueryTable.records, quickQuerySearch]);

  const queryPresets = useMemo(() => {
    const selectedDevices = batchMode ? devices.filter(d => batchDeviceIds.includes(d.id)) : (selectedDevice ? [selectedDevice] : []);
    const deviceCategory = selectedDevices.length > 0 ? getDeviceCategory(selectedDevices[0]) : 'all';

    const all: Array<{ icon: string; label: string; labelEn: string; cmds: string; group: string; scope: 'network' | 'server' | 'all'; operationalCategory?: string; excludeRoles?: string[] }> = [
      // --- Network Presets ---
      { icon: '📡', label: '接口状态', labelEn: 'Interfaces', group: 'net', scope: 'network', operationalCategory: 'interfaces', cmds: isCisco ? 'show ip interface brief' : isHuawei ? 'display interface brief' : isJuniper ? 'show interfaces terse' : 'show ip interface brief' },
      { icon: '📋', label: 'ARP表', labelEn: 'ARP Table', group: 'net', scope: 'network', operationalCategory: 'arp', cmds: isCisco ? 'show arp' : isHuawei ? 'display arp' : isJuniper ? 'show arp' : 'show arp' },
      { icon: '🏷️', label: 'MAC表', labelEn: 'MAC Table', group: 'net', scope: 'network', operationalCategory: 'mac_table', excludeRoles: ['router'], cmds: isCisco ? 'show mac address-table' : isHuawei ? 'display mac-address' : isJuniper ? 'show ethernet-switching table' : 'show mac address-table' },
      { icon: '📊', label: 'VLAN', labelEn: 'VLAN', group: 'net', scope: 'network', excludeRoles: ['router'], cmds: isCisco ? 'show vlan brief' : isHuawei ? 'display vlan' : isJuniper ? 'show vlans' : 'show vlan brief' },
      { icon: '📌', label: 'LLDP邻居', labelEn: 'LLDP', group: 'net', scope: 'network', operationalCategory: 'neighbors', cmds: isCisco ? 'show lldp neighbors' : isHuawei ? 'display lldp neighbor brief' : isJuniper ? 'show lldp neighbors' : 'show lldp neighbors' },
      { icon: '💎', label: '光模块状态', labelEn: 'Transceiver', group: 'net', scope: 'network', cmds: isCisco ? 'show inventory | include Transceiver\nshow interfaces transceiver' : isHuawei ? 'display transceiver verbose' : isJuniper ? 'show interfaces diagnostics transceiver' : 'show interface transceiver' },
      
      // --- Routing & Advanced ---
      { icon: '🗺️', label: '路由表', labelEn: 'Routes', group: 'route', scope: 'network', operationalCategory: 'routing_table', cmds: isCisco ? 'show ip route' : isHuawei ? 'display ip routing-table' : isJuniper ? 'show route' : 'show ip route' },
      { icon: '🔗', label: 'BGP邻居', labelEn: 'BGP Peers', group: 'route', scope: 'network', operationalCategory: 'bgp', excludeRoles: ['access'], cmds: isCisco ? 'show bgp summary' : isHuawei ? 'display bgp peer' : isJuniper ? 'show bgp summary' : 'show bgp summary' },
      { icon: '🔍', label: 'OSPF邻居', labelEn: 'OSPF Nbrs', group: 'route', scope: 'network', operationalCategory: 'ospf', excludeRoles: ['access'], cmds: isCisco ? 'show ip ospf neighbor' : isHuawei ? 'display ospf peer brief' : isJuniper ? 'show ospf neighbor' : 'show ip ospf neighbor' },
      { icon: '⏱️', label: 'NTP同步', labelEn: 'NTP Status', group: 'route', scope: 'network', cmds: isCisco ? 'show ntp status\nshow ntp associations' : isHuawei ? 'display ntp-service status' : isJuniper ? 'show ntp status' : 'show ntp status' },
      
      // --- Server Presets ---
      { icon: '📈', label: '负载统计', labelEn: 'Load Avg', group: 'sys', scope: 'server', cmds: 'uptime && top -bn1 | head -n 5' },
      { icon: '💽', label: '磁盘空间', labelEn: 'Disk Usage', group: 'sys', scope: 'server', cmds: 'df -h' },
      { icon: '🧠', label: '内存占用', labelEn: 'Memory', group: 'sys', scope: 'server', cmds: 'free -m' },
      { icon: '⚡', label: '高负载进程', labelEn: 'Processes', group: 'sys', scope: 'server', cmds: 'ps aux --sort=-%cpu | head -n 11' },
      { icon: '🌐', label: '网络连接', labelEn: 'Netstat', group: 'sys', scope: 'server', cmds: 'ss -tulpn' },
      { icon: '🪵', label: '系统日志', labelEn: 'Syslog', group: 'sys', scope: 'server', cmds: 'tail -n 50 /var/log/syslog' },
      { icon: '🆔', label: 'IP地址', labelEn: 'IP Addr', group: 'sys', scope: 'server', cmds: 'ip a' },
      { icon: '🛤️', label: '路由表', labelEn: 'IP Route', group: 'sys', scope: 'server', cmds: 'ip route' },
      { icon: '🔌', label: '系统服务', labelEn: 'Services', group: 'sys', scope: 'server', cmds: 'systemctl list-units --type=service --state=running | head -n 20' },
      { icon: '🛡️', label: 'DNS配置', labelEn: 'DNS', group: 'sys', scope: 'server', cmds: 'cat /etc/resolv.conf' },
      { icon: '👤', label: '最近登录', labelEn: 'Last Login', group: 'sys', scope: 'server', cmds: 'last -n 10' },
      { icon: '🧱', label: '环境变量', labelEn: 'Env Vars', group: 'sys', scope: 'server', cmds: 'env | sort | head -n 30' },

      // --- Common Presets ---
      { icon: '🏥', label: '设备信息', labelEn: 'Version', group: 'sys', scope: 'all', cmds: isCisco ? 'show version' : isHuawei ? 'display version' : isJuniper ? 'show version' : 'uname -a || show version' },
      { icon: '🔋', label: '电源风扇', labelEn: 'Environment', group: 'sys', scope: 'all', cmds: isCisco ? 'show environment' : isHuawei ? 'display environment' : isJuniper ? 'show chassis environment' : 'sensors || cat /proc/acpi/thermal_zone/*/temperature' },
      { icon: '📝', label: '日志概览', labelEn: 'Logs', group: 'sys', scope: 'all', cmds: isCisco ? 'show logging | tail 30' : isHuawei ? 'display logbuffer last 30' : isJuniper ? 'show log messages | last 30' : 'dmesg | tail -n 30' },
      // NOTE: 运行配置 (show running-config) removed — requires privileged exec
      // on most platforms. Use the approved Change Center workflow or a PAM
      // session with admin role to collect the full running-config.
      // Interface-level snippets that work at user-exec level:
      { icon: '🧩', label: '接口配置', labelEn: 'Intf Config', group: 'sys', scope: 'network', cmds: isCisco ? 'show interfaces description\nshow interfaces status' : isHuawei ? 'display interface description' : isJuniper ? 'show interfaces descriptions' : 'show interfaces description' },
      { icon: '🕒', label: '系统运行时间', labelEn: 'Uptime', group: 'sys', scope: 'all', cmds: isCisco ? 'show version | include uptime' : isHuawei ? 'display version | include uptime' : isJuniper ? 'show system uptime' : 'uptime' },
    ];

    // Load user saved queries from reactive state
    if (Array.isArray(savedQueries)) {
      savedQueries.forEach(s => {
        all.push({
          icon: s.icon || '⭐',
          label: s.label,
          labelEn: s.labelEn || s.label,
          cmds: s.cmds,
          group: 'user',
          scope: 'all'
        });
      });
    }

    return all.filter(p => {
      // Role filter
      if (p.excludeRoles && p.excludeRoles.includes(deviceRole)) return false;
      // Category (Scope) filter
      if (deviceCategory !== 'all' && p.scope !== 'all' && p.scope !== deviceCategory) return false;
      return true;
    });
  }, [isCisco, isHuawei, isJuniper, deviceRole, savedQueries, batchMode, batchDeviceIds, devices, selectedDevice]);

  /* Step validation */
  const canProceed = (step: StepId): boolean => {
    if (step === 1) return targetCount > 0;
    if (step === 2) return !!quickPlaybookScenario;
    if (step === 3) return !!canExecute;
    return true;
  };

  const handleStepClick = (step: StepId) => {
    if (step <= currentStep) setCurrentStep(step);
    else if (step === 2 && canProceed(1)) setCurrentStep(2);
    else if (step === 3 && quickPlaybookScenario) setCurrentStep(3);
    else if (step === 4 && (isQuickPlaybookRunning || quickExecutionResult)) setCurrentStep(4);
  };

  const handleNewTask = () => {
    onResetExecutionState();
    onClearScenario();
    setCurrentStep(1);
  };

  const handleConfirmExecute = () => {
    setConfirmModalOpen(false);
    if (confirmAction === 'validate') onRunValidation(changeTicket.trim());
    else onRunApply(changeTicket.trim());
  };

  const handleSelectAllOnline = () => {
    if (!batchMode) onToggleBatchMode();
    filteredDevices.filter(d => d.status === 'online').forEach(d => {
      if (!batchDeviceIds.includes(d.id)) onToggleBatchDevice(d.id);
    });
  };

  const handleClearSelection = () => {
    batchDeviceIds.forEach(id => onToggleBatchDevice(id));
  };

  const handleToggleTreeNode = (site: string) => {
    setExpandedTreeNodes(prev => {
      const next = new Set(prev);
      if (next.has(site)) next.delete(site); else next.add(site);
      return next;
    });
  };

  const handleTreeFilter = (site: string | null, role: string | null) => {
    if (treeFilterSite === site && treeFilterRole === role) {
      setTreeFilterSite(null);
      setTreeFilterRole(null);
    } else {
      setTreeFilterSite(site);
      setTreeFilterRole(role);
    }
  };

  const varGroupLabel = (group: string) => {
    if (group === 'address') return isZh ? '🌐 地址与邻居' : '🌐 Address & Neighbors';
    if (group === 'interface') return isZh ? '📡 接口与二层' : '📡 Interfaces & L2';
    if (group === 'routing') return isZh ? '🗺️ 路由与策略' : '🗺️ Routing & Policy';
    return isZh ? '⚙️ 通用参数' : '⚙️ General';
  };

  /* ESC key handling for modals and overlays */
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // 1. Close secondary confirmation modals first
        if (confirmModalOpen) {
          setConfirmModalOpen(false);
          return;
        }
        
        // 2. Close terminal/query overlays
        if (quickQueryRunning || quickQueryOutput) {
          onResetQuickQuery();
          handleClearSelection();
          return;
        }

        // 3. Close the "Confirm target and select operation" modal
        if (hasTargets) {
          handleClearSelection();
          return;
        }

        // 4. Close the selected devices drawer
        if (showSelectedDrawer) {
          setShowSelectedDrawer(false);
          return;
        }

        // 5. Navigate back in steps
        if (currentStep > 1) {
          if (currentStep === 2) setCurrentStep(1);
          else if (currentStep === 3) setCurrentStep(2);
          // We don't auto-exit step 4 to avoid losing execution results
        }
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [confirmModalOpen, quickQueryRunning, quickQueryOutput, hasTargets, showSelectedDrawer, currentStep, onResetQuickQuery, handleClearSelection]);

  /* ═══════════════════════════════════════════════════════════════════
     RENDER
     ═══════════════════════════════════════════════════════════════════ */
  return (
    <div className="h-full min-h-0 flex flex-col relative">
      {/* ── Title bar ── */}
      <div className="flex-shrink-0 flex items-center justify-between px-1 pb-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-gray-900">
            {isZh ? '自动化执行控制台' : 'Automation Console'}
          </h2>
          <p className="text-sm text-gray-400 mt-0.5">
            {isZh ? '选择设备进行快捷查询或执行自定义命令' : 'Select devices for quick query or custom commands'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {}} 
            className="px-3 py-2 text-xs font-bold rounded-xl text-gray-500 hover:bg-gray-50 transition-all flex items-center gap-1.5"
          >
            <History size={13} />
            {isZh ? '执行历史' : 'History'}
          </button>
        </div>
      </div>

      {/* ── Stepper (Hidden for Execute Tab) ── */}
      {/* 
      <div className="flex-shrink-0 mb-3">
        <div className="flex items-center bg-white rounded-xl border border-gray-100 px-5 py-2.5">
          {STEPS.map((step, idx) => {
            const Icon = step.icon;
            const isActive = currentStep === step.id;
            const isDone = currentStep > step.id ||
              (step.id === 1 && targetCount > 0) ||
              (step.id === 2 && !!quickPlaybookScenario) ||
              (step.id === 4 && !!quickExecutionResult && !isQuickPlaybookRunning);
            const isRunning = step.id === 4 && isQuickPlaybookRunning;

            return (
              <React.Fragment key={step.id}>
                {idx > 0 && (
                  <div className="flex-1 mx-2 h-px bg-gray-200 relative">
                    <div
                      className={`absolute inset-y-0 left-0 h-px transition-all duration-500 ${
                        isDone || isActive ? 'bg-cyan-500 w-full' : 'w-0'
                      }`}
                    />
                  </div>
                )}
                <button
                  onClick={() => handleStepClick(step.id)}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all ${
                    isActive
                      ? 'bg-cyan-50 ring-1 ring-cyan-200'
                      : isDone
                        ? 'hover:bg-gray-50'
                        : 'opacity-40 cursor-default'
                  }`}
                >
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold transition-all ${
                    isRunning
                      ? 'bg-cyan-500 text-white'
                      : isDone && !isActive
                        ? 'bg-emerald-500 text-white'
                        : isActive
                          ? 'bg-cyan-500 text-white'
                          : 'bg-gray-100 text-gray-400'
                  }`}>
                    {isRunning ? (
                      <RotateCcw size={11} className="animate-spin" />
                    ) : isDone && !isActive ? (
                      <CheckCircle2 size={12} />
                    ) : (
                      <span>{step.id}</span>
                    )}
                  </div>
                  <span className={`text-xs font-semibold whitespace-nowrap ${isActive ? 'text-gray-800' : isDone ? 'text-gray-500' : 'text-gray-400'}`}>
                    {isZh ? step.label : step.labelEn}
                  </span>
                  {isActive && step.id === 1 && targetCount > 0 && (
                    <span className="text-[10px] text-cyan-600 font-bold">{targetCount}</span>
                  )}
                  {step.id === 4 && isRunning && (
                    <span className="text-[10px] text-cyan-500 font-bold animate-pulse">{isZh ? '执行中' : 'Running'}</span>
                  )}
                </button>
              </React.Fragment>
            );
          })}
        </div>
      </div>
      */}

      {/* ── Step Content ── */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <AnimatePresence mode="wait">
          {/* ════════════ STEP 1: Device Selection ════════════ */}
          {currentStep === 1 && (
            <motion.div
              key="step-1"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              className="h-full flex flex-col gap-2"
            >
              {/* Main area: filter panel + device table */}
              <div className="flex-1 min-h-0 flex gap-3 overflow-hidden">
                {/* ── Left: Quick Filter Panel ── */}
                <div className="w-[200px] flex-shrink-0 bg-white rounded-xl border border-gray-100 overflow-hidden flex flex-col">
                  <div className="px-3 py-2.5 border-b border-gray-100 flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">{isZh ? '快速筛选' : 'Quick Filter'}</span>
                    {(treeFilterSite || treeFilterRole) && (
                      <button
                        onClick={() => { setTreeFilterSite(null); setTreeFilterRole(null); }}
                        className="text-[10px] text-cyan-600 hover:text-cyan-700 font-semibold"
                      >
                        {isZh ? '清除' : 'Clear'}
                      </button>
                    )}
                  </div>
                  <div className="flex-1 min-h-0 overflow-auto p-2.5 space-y-3">
                    {/* IP/Hostname search */}
                    <div>
                      <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '搜索设备' : 'Search'}</label>
                      <div className="relative">
                        <Search className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-300" size={12} />
                        <input
                          type="text"
                          placeholder={isZh ? 'IP / 主机名...' : 'IP / Hostname...'}
                          value={automationSearch}
                          onChange={e => onAutomationSearchChange(e.target.value)}
                          className="w-full pl-7 pr-2.5 py-1.5 bg-gray-50 border border-gray-100 rounded-lg text-[11px] focus:border-cyan-300 focus:bg-white outline-none transition-all"
                        />
                      </div>
                    </div>
                    {/* Site chips */}
                    <div>
                      <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '站点' : 'Site'}</label>
                      <div className="flex flex-wrap gap-1">
                        {deviceTree.map(node => (
                          <button
                            key={node.site}
                            onClick={() => handleTreeFilter(node.site, null)}
                            className={`px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                              treeFilterSite === node.site
                                ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
                                : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                            }`}
                          >
                            {node.site}
                            <span className="ml-1 text-[9px] opacity-60">{node.onlineCount}/{node.count}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Device Type chips */}
                    <div>
                      <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '设备类型' : 'Device Type'}</label>
                      <div className="flex flex-wrap gap-1">
                        {(['all', 'network', 'server'] as const).map(t => (
                          <button
                            key={t}
                            onClick={() => setDeviceTypeFilter(t)}
                            className={`px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                              deviceTypeFilter === t
                                ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
                                : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                            }`}
                          >
                            {t === 'all' ? (isZh ? '全部' : 'All') : t === 'network' ? (isZh ? '网络设备' : 'Network') : (isZh ? '服务器' : 'Server')}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Status chips */}
                    <div>
                      <label className="text-[10px] font-semibold text-gray-400 block mb-1.5">{isZh ? '状态' : 'Status'}</label>
                      <div className="flex flex-wrap gap-1">
                        {(['all', 'online', 'offline'] as const).map(s => (
                          <button
                            key={s}
                            onClick={() => setStatusFilter(s)}
                            className={`px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                              statusFilter === s
                                ? 'bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200'
                                : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                            }`}
                          >
                            {s === 'all' ? (isZh ? '全部' : 'All') : s === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline')}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Summary */}
                    <div className="pt-2 border-t border-gray-100 text-[10px] text-gray-400">
                      {isZh ? '匹配' : 'Found'} <span className="font-semibold text-gray-600">{filteredDevices.length}</span> {isZh ? '台设备' : 'devices'}
                    </div>
                  </div>
                </div>

                {/* ── Right: Filter + Device Table ── */}
                <div className="flex-1 min-w-0 flex flex-col gap-2">
                  {/* Filter bar */}
                  <div className="flex-shrink-0 flex items-center gap-2 bg-white rounded-xl border border-gray-100 px-3 py-2">
                    {vendors.length > 1 && (
                      <select
                        value={vendorFilter}
                        onChange={e => setVendorFilter(e.target.value)}
                        className="px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300"
                      >
                        <option value="all">{isZh ? '全部厂商' : 'All Vendors'}</option>
                        {vendors.map(v => <option key={v} value={v}>{v}</option>)}
                      </select>
                    )}
                    <div className="flex-1" />
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleSelectAllOnline}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-100 hover:bg-emerald-100 transition-all"
                      >
                        <CheckCircle2 size={11} />
                        {isZh ? '全选在线' : 'Select Online'}
                      </button>
                      <div className="w-px h-5 bg-gray-200" />
                      <div className="flex items-center bg-gray-100 rounded-lg p-0.5">
                        <button
                          onClick={() => setDeviceViewMode('grid')}
                          title={isZh ? '卡片视图' : 'Grid view'}
                          className={`p-1.5 rounded-md transition-all ${deviceViewMode === 'grid' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-400 hover:text-gray-500'}`}
                        >
                          <LayoutGrid size={13} />
                        </button>
                        <button
                          onClick={() => setDeviceViewMode('list')}
                          title={isZh ? '列表视图' : 'List view'}
                          className={`p-1.5 rounded-md transition-all ${deviceViewMode === 'list' ? 'bg-white text-gray-700 shadow-sm' : 'text-gray-400 hover:text-gray-500'}`}
                        >
                          <List size={13} />
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Device grid / list */}
                  <div className="flex-1 min-h-0 overflow-auto">
                    {deviceViewMode === 'grid' ? (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2.5">
                      {pagedDevices.map(device => {
                        const isSelected = batchMode
                          ? batchDeviceIds.includes(device.id)
                          : selectedDevice?.id === device.id;
                        const vendor = getVendor(device.platform);
                        const isOffline = device.status !== 'online';
                        return (
                          <motion.button
                            key={device.id}
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            disabled={isOffline}
                            onClick={() => {
                              if (isOffline) return;
                              if (!batchMode) onToggleBatchMode();
                              onToggleBatchDevice(device.id);
                            }}
                            className={`relative p-3 rounded-xl border-2 text-left transition-all group ${
                              isOffline
                                ? 'border-gray-100 bg-gray-50/60 opacity-50 cursor-not-allowed'
                                : isSelected
                                  ? 'border-cyan-400 bg-cyan-50/60 shadow-md shadow-cyan-500/10 ring-1 ring-cyan-200'
                                  : 'border-gray-100 bg-white hover:border-cyan-200 hover:shadow-md hover:-translate-y-0.5'
                            }`}
                          >
                            <div className={`absolute top-2 right-2 w-4 h-4 rounded border-2 flex items-center justify-center transition-all ${
                              isOffline ? 'border-gray-200 bg-gray-100' : isSelected ? 'bg-cyan-500 border-cyan-500' : 'border-gray-200 bg-white'
                            }`}>
                              {isSelected && <CheckCircle2 size={10} className="text-white" />}
                            </div>
                            <div className="flex items-center gap-2 mb-1.5">
                              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                                device.status === 'online' ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-gray-300'
                              }`} />
                              <div className="flex-1 flex items-center justify-between min-w-0">
                                <span className="text-xs font-bold text-gray-800 truncate">{device.hostname}</span>
                                {getDeviceCategory(device) === 'server' ? (
                                  <Terminal size={10} className="text-gray-400 ml-1" />
                                ) : (
                                  <Cpu size={10} className="text-gray-400 ml-1" />
                                )}
                              </div>
                            </div>
                            <p className="text-[11px] font-mono text-gray-400 mb-1.5">{device.ip_address}</p>
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{vendor}</span>
                              {device.role && (
                                <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-400">{device.role}</span>
                              )}
                            </div>
                          </motion.button>
                        );
                      })}
                      {filteredDevices.length === 0 && (
                        <div className="col-span-full py-16 text-center text-gray-300">
                          <Server size={32} strokeWidth={1} className="mx-auto mb-3 opacity-50" />
                          <p className="text-sm">{isZh ? '没有匹配的设备' : 'No matching devices'}</p>
                        </div>
                      )}
                    </div>
                    ) : (
                    /* ── High-density Table View ── */
                    <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
                      <table className="w-full text-left">
                        <thead>
                          <tr className="border-b border-gray-100 bg-gray-50/60">
                            <th className="w-10 px-3 py-2">
                              <input
                                type="checkbox"
                                checked={pagedDevices.filter(d => d.status === 'online').length > 0 && pagedDevices.filter(d => d.status === 'online').every(d => batchDeviceIds.includes(d.id))}
                                onChange={() => {
                                  if (!batchMode) onToggleBatchMode();
                                  const onlineOnPage = pagedDevices.filter(d => d.status === 'online');
                                  const allSelected = onlineOnPage.every(d => batchDeviceIds.includes(d.id));
                                  onlineOnPage.forEach(d => {
                                    if (allSelected) {
                                      if (batchDeviceIds.includes(d.id)) onToggleBatchDevice(d.id);
                                    } else {
                                      if (!batchDeviceIds.includes(d.id)) onToggleBatchDevice(d.id);
                                    }
                                  });
                                }}
                                title="Select all"
                                className="w-3.5 h-3.5 rounded accent-cyan-500"
                              />
                            </th>
                            <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '状态' : 'Status'}</th>
                            <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '主机名' : 'Hostname'}</th>
                            <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">IP</th>
                                                         <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '厂商' : 'Vendor'}</th>
                             <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '类型' : 'Type'}</th>
                            <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '角色' : 'Role'}</th>
                            <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '站点' : 'Site'}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pagedDevices.map(device => {
                            const isSelected = batchDeviceIds.includes(device.id);
                            const vendor = getVendor(device.platform);
                            const isOffline = device.status !== 'online';
                            return (
                              <tr
                                key={device.id}
                                onClick={() => {
                                  if (isOffline) return;
                                  if (!batchMode) onToggleBatchMode();
                                  onToggleBatchDevice(device.id);
                                }}
                                className={`border-b border-gray-50 transition-colors ${
                                  isOffline
                                    ? 'opacity-40 cursor-not-allowed'
                                    : isSelected
                                      ? 'bg-cyan-50/70 hover:bg-cyan-50 cursor-pointer'
                                      : 'hover:bg-gray-50/80 cursor-pointer'
                                }`}
                              >
                                <td className="px-3 py-1.5">
                                  <input
                                    title="Select device"
                                    type="checkbox"
                                    disabled={isOffline}
                                    checked={isSelected}
                                    onChange={e => {
                                      e.stopPropagation();
                                      if (isOffline) return;
                                      if (!batchMode) onToggleBatchMode();
                                      onToggleBatchDevice(device.id);
                                    }}
                                    onClick={e => e.stopPropagation()}
                                    className="w-3.5 h-3.5 rounded accent-cyan-500 disabled:opacity-30"
                                  />
                                </td>
                                <td className="px-3 py-1.5">
                                  <span className={`inline-flex items-center gap-1.5 text-[10px] font-semibold ${
                                    device.status === 'online' ? 'text-emerald-600' : 'text-gray-400'
                                  }`}>
                                    <span className={`w-1.5 h-1.5 rounded-full ${
                                      device.status === 'online' ? 'bg-emerald-500' : 'bg-gray-300'
                                    }`} />
                                    {device.status === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline')}
                                  </span>
                                </td>
                                <td className="px-3 py-1.5 text-xs font-bold text-gray-800">{device.hostname}</td>
                                <td className="px-3 py-1.5 text-[11px] font-mono text-gray-500">{device.ip_address}</td>
                                <td className="px-3 py-1.5">
                                                                     <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{vendor}</span>
                                 </td>
                                 <td className="px-3 py-1.5">
                                   <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
                                     {getDeviceCategory(device) === 'server' ? (
                                       <><Terminal size={10} /> {isZh ? '服务器' : 'Server'}</>
                                     ) : (
                                       <><Cpu size={10} /> {isZh ? '网络设备' : 'Network'}</>
                                     )}
                                   </div>
                                </td>
                                <td className="px-3 py-1.5 text-[11px] text-gray-500">{device.role || '—'}</td>
                                <td className="px-3 py-1.5 text-[11px] text-cyan-500">{device.site || '—'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      {filteredDevices.length === 0 && (
                        <div className="py-16 text-center text-gray-300">
                          <Server size={32} strokeWidth={1} className="mx-auto mb-3 opacity-50" />
                          <p className="text-sm">{isZh ? '没有匹配的设备' : 'No matching devices'}</p>
                        </div>
                      )}
                    </div>
                    )}
                  </div>

                  {/* Pagination */}
                  {filteredDevices.length > DEVICE_PAGE_SIZE && (
                    <div className="flex-shrink-0 px-1">
                      <Pagination
                        currentPage={devicePage}
                        totalItems={filteredDevices.length}
                        onPageChange={setDevicePage}
                        itemsPerPage={DEVICE_PAGE_SIZE}
                        language={language}
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* Bottom action bar — enhanced sticky footer */}
              <div className="flex-shrink-0 flex items-center justify-between rounded-xl border border-gray-100 bg-white px-4 py-2.5 shadow-sm">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">
                    {isZh ? `共 ${filteredDevices.length} 台` : `${filteredDevices.length} devices`}
                    {statusFilter === 'all' && (
                      <span className="ml-1.5 text-emerald-600 font-medium">
                        ({devices.filter(d => d.status === 'online').length} {isZh ? '在线' : 'online'})
                      </span>
                    )}
                  </span>
                  {targetCount > 0 && (
                    <>
                      <button
                        onClick={() => setShowSelectedDrawer(!showSelectedDrawer)}
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-50 text-cyan-700 text-xs font-bold border border-cyan-100 shadow-sm hover:bg-cyan-100 transition-all cursor-pointer"
                      >
                        <CheckCircle2 size={12} />
                        {isZh ? `已选 ${targetCount} 台` : `${targetCount} selected`}
                        <ChevronDown size={10} className={`transition-transform ${showSelectedDrawer ? 'rotate-180' : ''}`} />
                      </button>
                      <button
                        onClick={handleClearSelection}
                        className="text-[11px] text-gray-400 hover:text-red-500 transition-colors font-semibold"
                      >
                        {isZh ? '清空已选' : 'Clear All'}
                      </button>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-gray-400 font-medium italic">
                    {isZh ? '请从顶部或下方选择工具' : 'Select a tool from above'}
                  </span>
                </div>
              </div>

              {/* Quick Query Area — Re-imagined as a focused overlay */}
              <AnimatePresence>
                {hasTargets && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="fixed inset-0 z-[60] flex flex-col bg-slate-900/40 backdrop-blur-md p-6"
                  >
                    <div className="flex-1 flex flex-col max-w-6xl mx-auto w-full bg-white rounded-[2.5rem] shadow-2xl border border-white/20 overflow-hidden">
                      {/* Header: Target Confirmation */}
                      <div className="flex-shrink-0 px-8 py-6 bg-gradient-to-r from-slate-50 to-white border-b border-gray-100 flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          <div className="w-12 h-12 rounded-2xl bg-cyan-500 flex items-center justify-center shadow-lg shadow-cyan-500/20">
                            <Terminal size={24} className="text-white" />
                          </div>
                          <div>
                            <h3 className="text-xl font-black text-slate-800 tracking-tight">
                              {isZh ? '确认目标并选择操作' : 'Confirm Targets & Execute'}
                            </h3>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                              <p className="text-sm text-slate-500 font-medium">
                                {isZh ? `已选中 ${targetDevices.length} 台设备，请确认后点击下方工具执行` : `${targetDevices.length} devices selected. Confirm and click a tool below.`}
                              </p>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <button
                            onClick={handleClearSelection}
                            className="flex items-center gap-2 px-5 py-2.5 rounded-2xl bg-white border border-gray-200 text-slate-500 hover:text-red-500 hover:border-red-100 hover:bg-red-50 transition-all font-bold text-sm shadow-sm"
                          >
                            <X size={16} />
                            {isZh ? '重选设备' : 'Reselect Devices'}
                          </button>
                        </div>
                      </div>

                      {/* Device List Recap (Confirmation Bar) */}
                      <div className="flex-shrink-0 px-8 py-4 bg-slate-50/50 border-b border-gray-100 overflow-hidden">
                        <div className="flex flex-wrap gap-2">
                          {targetDevices.map(dev => (
                            <div key={dev.id} className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white border border-slate-200/60 shadow-sm">
                              <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                              <span className="text-xs font-bold text-slate-700">{dev.hostname}</span>
                              <span className="text-[10px] font-mono text-slate-400">{dev.ip_address}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Tools Grid */}
                      <div className="flex-1 overflow-auto p-8 custom-scrollbar">
                        <div className="space-y-8">
                          {Object.entries(
                            queryPresets.reduce((acc: Record<string, typeof queryPresets>, item) => {
                              if (!acc[item.group]) acc[item.group] = [];
                              acc[item.group].push(item);
                              return acc;
                            }, {})
                          ).map(([groupId, items]) => {
                            const groupMeta = groupId === 'net' ? { label: isZh ? '基础网络查询' : 'Network', icon: '🌐', bg: 'bg-cyan-50', text: 'text-cyan-600', border: 'border-cyan-100' }
                              : groupId === 'route' ? { label: isZh ? '路由协议分析' : 'Routing', icon: '🗺️', bg: 'bg-indigo-50', text: 'text-indigo-600', border: 'border-indigo-100' }
                              : groupId === 'sys' ? { label: isZh ? '系统状态监控' : 'System', icon: '⚙️', bg: 'bg-slate-50', text: 'text-slate-600', border: 'border-slate-100' }
                              : { label: isZh ? '个人常用收藏' : 'Favorites', icon: '⭐', bg: 'bg-amber-50', text: 'text-amber-600', border: 'border-amber-100' };

                            return (
                              <div key={groupId} className="space-y-4">
                                <div className="flex items-center gap-3">
                                  <span className={`text-sm font-black uppercase tracking-[0.2em] ${groupMeta.text}`}>
                                    {groupMeta.icon} {groupMeta.label}
                                  </span>
                                  <div className="h-px flex-1 bg-slate-100" />
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
                                  {items.map((cmd, idx) => (
                                    <button
                                      key={idx}
                                      disabled={quickQueryRunning}
                                      onClick={() => { onRunQuickQuery(isZh ? cmd.label : cmd.labelEn, cmd.cmds, cmd.operationalCategory, 'normal'); }}
                                      className="group relative flex items-center gap-4 p-4 rounded-2xl border border-slate-100 bg-white hover:border-cyan-400 hover:shadow-xl hover:shadow-cyan-500/10 hover:-translate-y-1 transition-all duration-300 disabled:opacity-40"
                                    >
                                      <div className={`w-12 h-12 rounded-xl ${groupMeta.bg} ${groupMeta.border} border flex items-center justify-center text-2xl group-hover:scale-110 transition-transform flex-shrink-0`}>
                                        {cmd.icon}
                                      </div>
                                      <div className="min-w-0 text-left">
                                        <p className="text-[13px] font-black text-slate-700 group-hover:text-cyan-700 transition-colors">{isZh ? cmd.label : cmd.labelEn}</p>
                                        <p className="text-[10px] text-slate-400 font-bold mt-0.5 font-mono uppercase tracking-wider">{cmd.operationalCategory || 'CLI'}</p>
                                      </div>
                                    </button>
                                  ))}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      {/* Footer: Tips */}
                      <div className="flex-shrink-0 px-8 py-4 bg-slate-50 text-[11px] text-slate-400 flex items-center gap-2 border-t border-slate-100">
                        <Zap size={12} className="text-amber-400" />
                        {isZh ? '点击上方图标将立即开始执行快捷查询。' : 'Click any icon to execute a quick query.'}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* ── Selected devices drawer ── */}
              <AnimatePresence>
                {showSelectedDrawer && targetCount > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 10 }}
                    className="absolute bottom-16 left-4 right-4 z-40 bg-white rounded-xl border border-gray-200 shadow-xl max-h-[240px] overflow-hidden"
                  >
                    <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
                      <span className="text-xs font-bold text-gray-600">
                        {isZh ? `已选设备 (${targetCount})` : `Selected Devices (${targetCount})`}
                      </span>
                      <button title="Close" onClick={() => setShowSelectedDrawer(false)} className="p-1 rounded-lg hover:bg-gray-100 text-gray-400">
                        <X size={12} />
                      </button>
                    </div>
                    <div className="overflow-auto max-h-[190px] p-2">
                      <div className="flex flex-wrap gap-1.5">
                        {(batchMode ? batchDeviceIds : (selectedDevice ? [selectedDevice.id] : [])).map(deviceId => {
                          const dev = devices.find(d => d.id === deviceId);
                          if (!dev) return null;
                          return (
                            <span
                              key={deviceId}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-50 border border-gray-100 text-xs group"
                            >
                              <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                              <span className="font-semibold text-gray-700">{dev.hostname}</span>
                              <span className="text-gray-400 font-mono text-[10px]">{dev.ip_address}</span>
                              <button
                                title="Remove"
                                onClick={() => onToggleBatchDevice(deviceId)}
                                className="text-gray-300 hover:text-red-500 transition-colors ml-0.5"
                              >
                                <X size={10} />
                              </button>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Removed old Quick Query slide-up panel */}
            </motion.div>
          )}

          {/* ════════════ STEP 2: Scenario Selection ════════════ */}
          {currentStep === 2 && (
            <motion.div
              key="step-2"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              className="h-full flex flex-col gap-3"
            >
              {/* Category + Filter bar */}
              <div className="flex-shrink-0 flex items-center gap-3 bg-white rounded-2xl border border-gray-100 shadow-sm px-4 py-3">
                <div className="flex items-center gap-1 flex-1 overflow-auto">
                  {scenarioCategories.map(cat => {
                    const meta = cat === 'all'
                      ? { label: '全部', labelEn: 'All', icon: '📋', color: 'text-gray-600' }
                      : (CATEGORY_META[cat] || { label: cat, labelEn: cat, icon: '📦', color: 'text-gray-600' });
                    const count = cat === 'all' ? filteredScenarios.length : filteredScenarios.filter(s => (s.category || 'Custom') === cat).length;
                    const isActive = categoryFilter === cat;
                    return (
                      <button
                        key={cat}
                        onClick={() => setCategoryFilter(cat)}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold whitespace-nowrap transition-all ${
                          isActive
                            ? 'bg-cyan-50 text-cyan-700 border border-cyan-200 shadow-sm'
                            : 'text-gray-500 hover:bg-gray-50'
                        }`}
                      >
                        <span>{meta.icon}</span>
                        <span>{isZh ? meta.label : meta.labelEn}</span>
                        <span className="text-[10px] font-mono opacity-60">{count}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="flex items-center gap-2">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-300" size={12} />
                    <input
                      type="text"
                      value={scenarioSearch}
                      onChange={e => onScenarioSearchChange(e.target.value)}
                      placeholder={isZh ? '搜索场景...' : 'Search...'}
                      className="pl-7 pr-3 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300 w-40"
                    />
                  </div>
                  <select
                    value={riskFilter}
                    onChange={e => setRiskFilter(e.target.value)}
                    className="px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300"
                  >
                    <option value="all">{isZh ? '全部风险' : 'All Risks'}</option>
                    <option value="low">{isZh ? '🟢 低风险' : '🟢 Low'}</option>
                    <option value="medium">{isZh ? '🟡 中等' : '🟡 Medium'}</option>
                    <option value="high">{isZh ? '🔴 高危' : '🔴 High'}</option>
                  </select>
                </div>
              </div>

              {/* Target summary */}
              <div className="flex-shrink-0 flex items-center gap-3 px-2">
                <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">{isZh ? '目标设备' : 'TARGET'}</span>
                <span className="inline-flex items-center gap-1.5 text-xs font-bold text-cyan-700 px-2.5 py-1 rounded-full bg-cyan-50 border border-cyan-100">
                  <Server size={11} />
                  {batchMode
                    ? `${targetCount} ${isZh ? '台设备' : 'devices'}`
                    : (selectedDevice?.hostname || '')}
                </span>
                <button
                  onClick={() => setCurrentStep(1)}
                  className="text-[10px] font-semibold text-gray-400 hover:text-cyan-600 transition-colors"
                >
                  {isZh ? '修改' : 'Change'}
                </button>
              </div>

              {/* Scenario grid */}
              <div className="flex-1 min-h-0 overflow-auto">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                  {displayScenarios.map(scenario => {
                    const risk = RISK_CONFIG[scenario.risk];
                    const cat = CATEGORY_META[scenario.category || 'Custom'] || CATEGORY_META.Custom;
                    return (
                      <motion.button
                        key={scenario.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        onClick={() => {
                          onOpenScenario(scenario);
                          setCurrentStep(3);
                        }}
                        className={`group relative p-4 rounded-xl border-2 border-l-4 text-left transition-all hover:shadow-lg hover:-translate-y-0.5 bg-white border-gray-100 hover:border-cyan-200 ${risk.stripe}`}
                      >
                        <div className="flex items-start justify-between gap-2 mb-2.5">
                          <div className="flex items-center gap-2.5">
                            <span className="text-2xl leading-none">{scenario.icon}</span>
                            <div>
                              <p className="text-sm font-bold text-gray-800 group-hover:text-cyan-700 transition-colors">
                                {isZh ? scenario.name_zh : scenario.name}
                              </p>
                              <p className="text-[11px] text-gray-400 mt-0.5 line-clamp-2">
                                {isZh ? scenario.description_zh : scenario.description}
                              </p>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 flex-wrap mt-3">
                          <span className={`inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded-full border ${risk.bg} ${risk.border} ${risk.text}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${risk.dot}`} />
                            {isZh ? risk.label : risk.labelEn}
                          </span>
                          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full bg-gray-50 border border-gray-100 ${cat.color}`}>
                            {isZh ? cat.label : cat.labelEn}
                          </span>
                          {(scenario.supported_platforms || []).length > 0 && (
                            <span className="text-[9px] text-gray-400 ml-auto">
                              {(scenario.supported_platforms || []).slice(0, 3).map(p => getVendor(p)).filter((v, i, a) => a.indexOf(v) === i).join(' · ')}
                              {(scenario.supported_platforms || []).length > 3 && ' +'}
                            </span>
                          )}
                        </div>
                      </motion.button>
                    );
                  })}
                  {displayScenarios.length === 0 && (
                    <div className="col-span-full py-16 text-center text-gray-300">
                      <Zap size={32} strokeWidth={1} className="mx-auto mb-3 opacity-50" />
                      <p className="text-sm">{isZh ? '没有匹配的场景' : 'No matching scenarios'}</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Bottom bar */}
              <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
                <button
                  onClick={() => setCurrentStep(1)}
                  className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <ChevronLeft size={14} />
                  {isZh ? '返回设备选择' : 'Back to Devices'}
                </button>
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  {['low', 'medium', 'high'].map(risk => {
                    const count = filteredScenarios.filter(s => s.risk === risk).length;
                    const cfg = RISK_CONFIG[risk as keyof typeof RISK_CONFIG];
                    return (
                      <span key={risk} className="flex items-center gap-1.5">
                        <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
                        <span className="font-bold tabular-nums">{count}</span>
                        {isZh ? cfg.label : cfg.labelEn}
                      </span>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          )}

          {/* ════════════ STEP 3: Parameter Configuration ════════════ */}
          {currentStep === 3 && quickPlaybookScenario && (
            <motion.div
              key="step-3"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              className="h-full flex flex-col gap-3"
            >
              {/* Scenario + Target header */}
              <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-2xl leading-none">{quickPlaybookScenario.icon}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-gray-800 truncate">{isZh ? quickPlaybookScenario.name_zh : quickPlaybookScenario.name}</p>
                      <span className={`inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded-full border ${RISK_CONFIG[quickPlaybookScenario.risk].bg} ${RISK_CONFIG[quickPlaybookScenario.risk].border} ${RISK_CONFIG[quickPlaybookScenario.risk].text}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${RISK_CONFIG[quickPlaybookScenario.risk].dot}`} />
                        {isZh ? RISK_CONFIG[quickPlaybookScenario.risk].label : RISK_CONFIG[quickPlaybookScenario.risk].labelEn}
                      </span>
                    </div>
                    <p className="text-[11px] text-gray-400 truncate">{isZh ? quickPlaybookScenario.description_zh : quickPlaybookScenario.description}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="inline-flex items-center gap-1.5 text-xs font-bold text-cyan-700 px-2.5 py-1 rounded-full bg-cyan-50 border border-cyan-100">
                    <Server size={11} />
                    {batchMode ? `${targetCount} ${isZh ? '台' : 'dev'}` : (selectedDevice?.hostname || '')}
                  </span>
                  <span className="text-[10px] text-gray-400 font-mono">{getPlatformLabel(quickPlaybookPlatform)}</span>
                  <button
                    onClick={() => { onClearScenario(); setCurrentStep(2); }}
                    className="text-xs font-semibold text-gray-400 hover:text-red-500 border border-gray-200 rounded-lg px-2.5 py-1 hover:bg-red-50 transition-all"
                  >
                    {isZh ? '更换场景' : 'Change'}
                  </button>
                </div>
              </div>

              {/* Main content: Form + Preview split */}
              <div className="flex-1 min-h-0 flex gap-3 overflow-hidden">
                {/* Left: Form */}
                <div className="flex-1 min-w-0 overflow-auto bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-5">
                  {/* Variables */}
                  {(quickPlaybookScenario.variables || []).length > 0 ? (
                    VAR_GROUP_ORDER
                      .filter(g => (groupedVariables[g] || []).length > 0)
                      .map(group => (
                        <div key={group}>
                          <p className="text-xs font-bold text-gray-500 mb-3">{varGroupLabel(group)}</p>
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            {(groupedVariables[group] || []).map(variable => (
                              <div key={variable.key} className="rounded-xl border border-gray-100 p-3.5 bg-gray-50/40 hover:bg-gray-50 transition-colors">
                                <div className="flex items-center justify-between gap-2 mb-2">
                                  <label className="text-xs font-semibold text-gray-600">
                                    {isZh ? (variable.label_zh || variable.label || variable.key) : (variable.label || variable.key)}
                                  </label>
                                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-bold ${
                                    variable.required ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-gray-400'
                                  }`}>
                                    {variable.required ? (isZh ? '必填' : 'REQ') : (isZh ? '选填' : 'OPT')}
                                  </span>
                                </div>
                                <input
                                  type={variable.type === 'number' ? 'number' : 'text'}
                                  value={quickPlaybookVars[variable.key] || ''}
                                  onChange={e => onQuickPlaybookVarChange(variable.key, e.target.value)}
                                  placeholder={variable.platform_hints?.[quickPlaybookPlatform] || variable.placeholder || variable.key}
                                  className={`w-full px-3 py-2 border rounded-lg text-xs outline-none bg-white transition-colors ${
                                    quickMissingRequiredFields.includes(variable.key)
                                      ? 'border-red-300 focus:border-red-400 bg-red-50/50'
                                      : 'border-gray-200 focus:border-cyan-400'
                                  }`}
                                />
                                {variable.platform_hints?.[quickPlaybookPlatform] && (
                                  <p className="text-[10px] text-gray-400 mt-1 italic">
                                    {isZh ? '示例：' : 'e.g. '}{variable.platform_hints[quickPlaybookPlatform]}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      ))
                  ) : (
                    <div className="flex items-center gap-2.5 rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-4 text-sm text-emerald-700">
                      <CheckCircle2 size={16} />
                      <span>{isZh ? '该场景无需配置参数，可直接执行。' : 'No parameters required. Ready to run.'}</span>
                    </div>
                  )}

                  {/* Options: Concurrency + Dry-run + Change Ticket */}
                  <div className="space-y-3 pt-2 border-t border-gray-100">
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">{isZh ? '并发数' : 'Concurrency'}</span>
                        <select
                          value={quickPlaybookConcurrency}
                          onChange={e => onQuickPlaybookConcurrencyChange(Number(e.target.value))}
                          className="px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs bg-white outline-none"
                        >
                          {[1, 2, 3, 5, 10].map(n => <option key={n} value={n}>×{n}</option>)}
                        </select>
                      </div>
                      {quickPlaybookConcurrency > 1 && (
                        <span className="text-[10px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
                          {isZh ? '⚠ 建议先小批量验证' : '⚠ Validate with small batch first'}
                        </span>
                      )}
                    </div>

                    {/* Change Ticket Number — required for non-read-only (medium/high risk) scenarios */}
                    {quickPlaybookScenario.risk !== 'low' && (
                      <div className="flex flex-col gap-2 rounded-xl border border-amber-100 bg-amber-50/50 p-3.5">
                        <div className="flex items-center gap-2">
                          <Ticket size={14} className="text-amber-600" />
                          <label className="text-xs font-semibold text-amber-800">
                            {isZh ? '变更工单号' : 'Change Ticket Number'}
                            <span className="text-amber-700/70 ml-1">({isZh ? '可选' : 'Optional'})</span>
                          </label>
                        </div>
                        <div className="flex items-center gap-2">
                          <input
                            type="text"
                            value={changeTicket}
                            onChange={e => setChangeTicket(e.target.value)}
                            placeholder={isZh ? '可选：指定工单号；留空时自动匹配' : 'Optional: specify ticket; leave empty to auto-match'}
                            className={`w-full max-w-[360px] px-3 py-2 border rounded-lg text-xs outline-none bg-white transition-colors ${
                              ticketValidation.found === true && ticketValidation.valid ? 'border-emerald-400 focus:border-emerald-500' :
                              ticketValidation.found === true && !ticketValidation.valid ? 'border-red-400 focus:border-red-500' :
                              'border-gray-200 focus:border-cyan-400'
                            }`}
                          />
                          {ticketValidation.loading && (
                            <RotateCcw size={14} className="animate-spin text-black/30 flex-shrink-0" />
                          )}
                          {!ticketValidation.loading && ticketValidation.found === true && ticketValidation.valid && (
                            <CheckCircle2 size={14} className="text-emerald-500 flex-shrink-0" />
                          )}
                          {!ticketValidation.loading && ticketValidation.found === true && !ticketValidation.valid && (
                            <XCircle size={14} className="text-red-500 flex-shrink-0" />
                          )}
                          {!ticketValidation.loading && ticketValidation.found === false && changeTicket.trim().length >= 4 && (
                            <XCircle size={14} className="text-black/25 flex-shrink-0" />
                          )}
                        </div>

                        {/* Ticket validation feedback */}
                        {!ticketValidation.loading && changeTicket.trim().length >= 4 && (
                          <div className={`rounded-lg px-3 py-2 text-[11px] ${
                            ticketValidation.found === true && ticketValidation.valid
                              ? 'bg-emerald-50 border border-emerald-200 text-emerald-700'
                              : ticketValidation.found === true && !ticketValidation.valid
                                ? 'bg-red-50 border border-red-200 text-red-700'
                                : ticketValidation.found === false
                                  ? 'bg-gray-50 border border-gray-200 text-gray-500'
                                  : ''
                          }`}>
                            {ticketValidation.found === true && ticketValidation.valid && (
                              <div className="space-y-0.5">
                                <p className="font-semibold">{ticketValidation.title}</p>
                                <p className="text-[10px] text-emerald-600/70">
                                  {isZh ? '工单已审批，当前在变更窗口内' : 'Order approved, within change window'}
                                  {ticketValidation.scheduled_start && ticketValidation.scheduled_end && (
                                    <span className="ml-1 font-mono">({ticketValidation.scheduled_start.replace('T', ' ').slice(0, 16)} ~ {ticketValidation.scheduled_end.replace('T', ' ').slice(0, 16)})</span>
                                  )}
                                </p>
                              </div>
                            )}
                            {ticketValidation.found === true && !ticketValidation.valid && (
                              <div className="space-y-0.5">
                                <p className="font-semibold flex items-center gap-1">
                                  <AlertTriangle size={11} />
                                  {ticketValidation.reason === 'expired' ? (isZh ? '变更窗口已超时' : 'Change window expired') :
                                   ticketValidation.reason === 'not_started' ? (isZh ? '变更窗口尚未开始' : 'Change window not started') :
                                   ticketValidation.reason === 'invalid_status' ? (isZh ? '工单状态不允许执行' : 'Order status does not allow execution') :
                                   (isZh ? '工单不可用' : 'Order unavailable')}
                                </p>
                                <p className="text-[10px] text-red-600/70">{ticketValidation.message}</p>
                              </div>
                            )}
                            {ticketValidation.found === false && (
                              <p>{isZh ? '未找到该工单号，请检查输入' : 'Order number not found, please check input'}</p>
                            )}
                          </div>
                        )}

                        <p className="text-[10px] text-amber-600">
                          {isZh ? '系统会自动匹配该任务对应的有效变更单并校验时间窗；超时将禁止执行。' : 'System auto-matches a valid change order for this scenario and enforces its time window.'}
                        </p>
                      </div>
                    )}
                  </div>

                  {/* Blocking issues */}
                  {blockingIssues.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-red-500 flex items-center gap-1.5">
                        <AlertTriangle size={12} />
                        {isZh ? '阻塞项' : 'Blocking Issues'}
                      </p>
                      {blockingIssues.map((issue, i) => (
                        <div key={i} className={`flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-xs border ${
                          issue.severity === 'critical' ? 'border-red-200 bg-red-50 text-red-700'
                            : issue.severity === 'high' ? 'border-orange-200 bg-orange-50 text-orange-700'
                              : 'border-amber-200 bg-amber-50 text-amber-700'
                        }`}>
                          <span className="flex-shrink-0 mt-0.5 font-bold">
                            {issue.severity === 'critical' ? '✕' : issue.severity === 'high' ? '!' : '▲'}
                          </span>
                          <span>{issue.message}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* High risk confirmation */}
                  {quickPlaybookScenario.risk === 'high' && (
                    <label className="flex items-start gap-2.5 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={quickRiskConfirmed}
                        onChange={e => onQuickRiskConfirmedChange(e.target.checked)}
                        className="mt-0.5 flex-shrink-0 accent-red-600"
                      />
                      <span className="leading-relaxed">
                        <Shield size={12} className="inline mr-1 -mt-0.5" />
                        {isZh
                          ? '我已了解该场景为高风险操作，确认继续执行。执行后可能影响网络连通性。'
                          : 'I understand this is a high-risk operation and want to proceed. Network connectivity may be affected.'}
                      </span>
                    </label>
                  )}
                </div>

                {/* Right: CLI Preview */}
                <div className="w-[380px] flex-shrink-0 flex flex-col bg-[#0d1117] rounded-2xl border border-white/5 shadow-lg overflow-hidden">
                  <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-white/5">
                    <div className="flex items-center gap-2">
                      <div className="flex gap-[5px]">
                        <span className="w-[9px] h-[9px] rounded-full bg-[#ff5f57]/80" />
                        <span className="w-[9px] h-[9px] rounded-full bg-[#febc2e]/80" />
                        <span className="w-[9px] h-[9px] rounded-full bg-[#28c840]/80" />
                      </div>
                      <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider">{isZh ? 'CLI 预览' : 'CLI Preview'}</span>
                      {previewLineCount > 0 && (
                        <span className="text-[10px] text-white/25 font-mono">{previewLineCount} {isZh ? '行' : 'lines'}</span>
                      )}
                    </div>
                    {quickPlaybookPreview && (
                      <button
                        onClick={onOpenCommandPreview}
                        className="text-[10px] text-white/30 hover:text-white/60 px-2 py-1 rounded-lg hover:bg-white/5 transition-all"
                      >
                        <Maximize2 size={12} />
                      </button>
                    )}
                  </div>
                  <div className="flex-1 min-h-0 overflow-auto p-4">
                    {quickPlaybookPreview ? (
                      <div className="space-y-4">
                        {(['pre_check', 'execute', 'post_check', 'rollback'] as const)
                          .filter(phase => (quickPlaybookPreview[phase] || []).length > 0)
                          .map(phase => (
                            <div key={phase}>
                              <div className="flex items-center gap-2 mb-2">
                                <span className={`w-1 h-3 rounded-full ${
                                  phase === 'execute' ? 'bg-cyan-400' : phase === 'rollback' ? 'bg-red-400' : 'bg-white/20'
                                }`} />
                                <span className="text-[9px] font-bold uppercase tracking-widest text-white/30">{phase.replace('_', ' ')}</span>
                              </div>
                              {(quickPlaybookPreview[phase] || []).map((cmd, idx) => (
                                <div key={idx} className="flex items-start gap-2 mb-1">
                                  <span className="text-cyan-400/40 text-[11px] select-none mt-0.5">❯</span>
                                  <code className="text-[11px] font-mono text-[#e6edf3] leading-relaxed whitespace-pre-wrap">{cmd}</code>
                                </div>
                              ))}
                            </div>
                          ))
                        }
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center h-full gap-3 text-white/20">
                        <Terminal size={24} strokeWidth={1} />
                        <p className="text-xs">{isZh ? '填写参数后自动生成命令预览' : 'CLI preview auto-generates after filling variables'}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Bottom action bar */}
              <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
                <button
                  onClick={() => setCurrentStep(2)}
                  className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 transition-colors"
                >
                  <ChevronLeft size={14} />
                  {isZh ? '返回场景选择' : 'Back to Scenarios'}
                </button>
                <div className="flex items-center gap-3">
                  <p className="text-[10px] text-gray-400">
                    {isZh ? '推荐：先运行校验确认无误，再应用变更' : 'Recommended: validate first, then apply'}
                  </p>
                  <button
                    onClick={() => {
                      if (quickPlaybookScenario.risk === 'high') {
                        setConfirmAction('validate');
                        setConfirmModalOpen(true);
                      } else {
                        onRunValidation(changeTicket.trim());
                      }
                    }}
                    disabled={!canExecute}
                    className={`px-5 py-2.5 rounded-xl text-xs font-bold transition-all border ${
                      canExecute
                        ? 'bg-white text-cyan-700 border-cyan-300 hover:bg-cyan-50 shadow-sm'
                        : 'bg-gray-50 text-gray-300 border-gray-100 cursor-not-allowed'
                    }`}
                  >
                    {isZh ? '🔍 运行校验' : '🔍 Validate'}
                  </button>
                  <button
                    onClick={() => {
                      setConfirmAction('apply');
                      setConfirmModalOpen(true);
                    }}
                    disabled={!canExecute}
                    className={`px-6 py-2.5 rounded-xl text-xs font-bold text-white transition-all flex items-center gap-2 ${
                      canExecute
                        ? 'bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 hover:-translate-y-0.5'
                        : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                    }`}
                  >
                    <Play size={13} />
                    {isZh ? `应用变更 (${targetCount})` : `Apply (${targetCount})`}
                  </button>
                </div>
              </div>
            </motion.div>
          )}

          {/* ════════════ STEP 4: Execution & Results ════════════ */}
          {currentStep === 4 && (
            <motion.div
              key="step-4"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              className="h-full flex flex-col gap-3"
            >
              {/* Execution status header */}
              {(() => {
                const completeMsg = wsCompleteMsg;
                const deviceEntries = Object.entries(deviceStatusMap) as Array<[string, DeviceExecutionState]>;
                const successCount = completeMsg?.summary?.success ?? deviceEntries.filter(([, s]) => s.status === 'success').length;
                const failedCount = completeMsg?.summary?.failed ?? deviceEntries.filter(([, s]) => s.status === 'failed' || s.status === 'partial_failure').length;
                const runningCount = deviceEntries.filter(([, s]) => s.status === 'running').length;
                const totalDevices = Math.max(targetCount, deviceEntries.length);
                const progressPct = totalDevices > 0 ? ((successCount + failedCount) / totalDevices * 100) : 0;

                const isDone = !isQuickPlaybookRunning && (completeMsg || quickExecutionResult);
                const overallStatus = isDone
                  ? (failedCount === 0 ? 'success' : failedCount < totalDevices ? 'partial' : 'failed')
                  : 'running';

                const scenarioTitle = quickExecutionResult
                  ? (isZh ? (quickExecutionResult.scenarioNameZh || quickExecutionResult.scenarioName) : quickExecutionResult.scenarioName)
                  : (quickPlaybookScenario ? (isZh ? (quickPlaybookScenario.name_zh || quickPlaybookScenario.name) : quickPlaybookScenario.name) : '');

                return (
                  <>
                    {/* Status bar */}
                    <div className={`flex-shrink-0 rounded-2xl border shadow-sm overflow-hidden ${
                      overallStatus === 'success' ? 'bg-gradient-to-r from-emerald-50 to-teal-50 border-emerald-200'
                        : overallStatus === 'partial' ? 'bg-gradient-to-r from-amber-50 to-orange-50 border-amber-200'
                          : overallStatus === 'failed' ? 'bg-gradient-to-r from-red-50 to-rose-50 border-red-200'
                            : 'bg-gradient-to-r from-cyan-50 to-cyan-100/50 border-cyan-200'
                    }`}>
                      <div className="px-5 py-3 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          {isQuickPlaybookRunning ? (
                            <div className="w-8 h-8 rounded-lg bg-cyan-500 flex items-center justify-center">
                              <RotateCcw size={16} className="text-white animate-spin" />
                            </div>
                          ) : overallStatus === 'success' ? (
                            <div className="w-8 h-8 rounded-lg bg-emerald-500 flex items-center justify-center">
                              <CheckCircle2 size={16} className="text-white" />
                            </div>
                          ) : overallStatus === 'partial' ? (
                            <div className="w-8 h-8 rounded-lg bg-amber-500 flex items-center justify-center">
                              <AlertTriangle size={16} className="text-white" />
                            </div>
                          ) : (
                            <div className="w-8 h-8 rounded-lg bg-red-500 flex items-center justify-center">
                              <XCircle size={16} className="text-white" />
                            </div>
                          )}
                          <div>
                            <p className="text-sm font-bold text-gray-800">{scenarioTitle}</p>
                            <p className="text-[11px] text-gray-500">
                              {isQuickPlaybookRunning
                                ? (isZh ? `正在执行... ${successCount + failedCount}/${totalDevices}` : `Running... ${successCount + failedCount}/${totalDevices}`)
                                : isDone
                                  ? (isZh ? `执行完成 · ${successCount} 成功 · ${failedCount} 失败` : `Done · ${successCount} success · ${failedCount} failed`)
                                  : (isZh ? '已提交执行请求' : 'Submitted')}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-4">
                          {quickExecutionResult?.dryRun && (
                            <span className="text-xs font-bold px-2.5 py-1 rounded-lg bg-amber-100 text-amber-700 border border-amber-200">DRY-RUN</span>
                          )}
                          {/* Stats pills */}
                          <div className="flex items-center gap-2">
                            <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-700 bg-emerald-100 px-2.5 py-1 rounded-lg">
                              <CheckCircle2 size={12} /> {successCount}
                            </span>
                            {failedCount > 0 && (
                              <span className="flex items-center gap-1.5 text-xs font-bold text-red-700 bg-red-100 px-2.5 py-1 rounded-lg">
                                <XCircle size={12} /> {failedCount}
                              </span>
                            )}
                            {runningCount > 0 && (
                              <span className="flex items-center gap-1.5 text-xs font-bold text-cyan-700 bg-cyan-100 px-2.5 py-1 rounded-lg">
                                <RotateCcw size={12} className="animate-spin" /> {runningCount}
                              </span>
                            )}
                          </div>
                          {/* Success rate ring */}
                          {isDone && totalDevices > 0 && (
                            <div className="flex items-center gap-2">
                              <div className="relative w-10 h-10">
                                <svg className="w-10 h-10 -rotate-90" viewBox="0 0 36 36">
                                  <circle cx="18" cy="18" r="15" fill="none" stroke="#e5e7eb" strokeWidth="3" />
                                  <circle
                                    cx="18" cy="18" r="15" fill="none"
                                    stroke={failedCount === 0 ? '#10b981' : failedCount < totalDevices ? '#f59e0b' : '#ef4444'}
                                    strokeWidth="3" strokeLinecap="round"
                                    strokeDasharray={`${(successCount / totalDevices) * 94.2} 94.2`}
                                  />
                                </svg>
                                <span className="absolute inset-0 flex items-center justify-center text-[9px] font-bold text-gray-600">
                                  {Math.round(successCount / totalDevices * 100)}%
                                </span>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                      {/* Progress bar */}
                      {isQuickPlaybookRunning && (
                        <div className="h-1 bg-cyan-100">
                          <div
                            className="h-full bg-gradient-to-r from-cyan-500 to-teal-400 transition-all duration-500 ease-out"
                            style={{ width: `${Math.max(progressPct, 5)}%` }}
                          />
                        </div>
                      )}
                    </div>

                    {/* Device results + terminal */}
                    <div className="flex-1 min-h-0 flex gap-3 overflow-hidden">
                      {/* Left: Device status cards */}
                      <div className="w-[340px] flex-shrink-0 flex flex-col bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                        <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50/50">
                          <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">
                            {isZh ? '设备执行状态' : 'Device Status'}
                          </span>
                          <span className="text-[10px] font-mono text-gray-300 ml-2">{deviceEntries.length}/{totalDevices}</span>
                        </div>
                        <div className="flex-1 min-h-0 overflow-auto p-3 space-y-2">
                          {deviceEntries.length === 0 && isQuickPlaybookRunning && (
                            <div className="flex flex-col items-center justify-center h-32 gap-3">
                              <RotateCcw size={24} className="text-cyan-400 animate-spin" />
                              <p className="text-xs text-gray-400">{isZh ? '等待设备响应...' : 'Waiting for device response...'}</p>
                            </div>
                          )}
                          {deviceEntries.length === 0 && !isQuickPlaybookRunning && isDone && (
                            <div className="flex flex-col items-center justify-center h-32 gap-3 text-gray-400">
                              <AlertTriangle size={24} className="text-amber-400" />
                              <p className="text-xs font-semibold">{isZh ? '未接收到设备执行事件' : 'No device events received'}</p>
                              <p className="text-[10px] text-gray-300 max-w-[200px] text-center">
                                {isZh ? 'WebSocket 连接可能中断，请查看执行历史获取详细结果。' : 'WebSocket may have disconnected. Check execution history for details.'}
                              </p>
                              <button
                                onClick={() => onNavigate('/automation/queries')}
                                className="text-[11px] text-cyan-600 hover:text-cyan-700 font-semibold mt-1"
                              >
                                {isZh ? '查看执行历史 →' : 'View History →'}
                              </button>
                            </div>
                          )}
                          {deviceEntries.map(([deviceId, deviceState]) => (
                            <div
                              key={deviceId}
                              className={`rounded-xl border-2 p-3 transition-all ${
                                deviceState.status === 'running' ? 'border-cyan-200 bg-cyan-50/40'
                                  : deviceState.status === 'success' ? 'border-emerald-200 bg-emerald-50/40'
                                    : deviceState.status === 'partial_failure' ? 'border-amber-200 bg-amber-50/40'
                                      : 'border-red-200 bg-red-50/40'
                              }`}
                            >
                              <div className="flex items-center gap-2 mb-1.5">
                                {deviceState.status === 'running' ? (
                                  <RotateCcw size={13} className="text-cyan-500 animate-spin flex-shrink-0" />
                                ) : deviceState.status === 'success' ? (
                                  <CheckCircle2 size={13} className="text-emerald-500 flex-shrink-0" />
                                ) : deviceState.status === 'partial_failure' ? (
                                  <AlertTriangle size={13} className="text-amber-500 flex-shrink-0" />
                                ) : (
                                  <XCircle size={13} className="text-red-500 flex-shrink-0" />
                                )}
                                <span className="text-xs font-bold text-gray-700 truncate">{deviceState.hostname}</span>
                              </div>
                              {Object.keys(deviceState.phases).length > 0 && (
                                <div className="flex flex-wrap gap-1 pl-5">
                                  {(Object.entries(deviceState.phases) as Array<[string, DeviceExecutionPhase]>).map(([phase, ps]) => (
                                    <span key={phase} className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                                      ps.success ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
                                    }`}>
                                      {ps.success ? '✓' : '✗'} {phase}
                                    </span>
                                  ))}
                                </div>
                              )}
                              {deviceState.error && (
                                <p className="text-[10px] text-red-600 pl-5 font-mono mt-1 truncate" title={deviceState.error}>{deviceState.error}</p>
                              )}
                            </div>
                          ))}
                          <div ref={logEndRef} />
                        </div>
                      </div>

                      {/* Right: Terminal-style execution log */}
                      <div className="flex-1 min-w-0 flex flex-col bg-[#0d1117] rounded-2xl border border-white/5 shadow-lg overflow-hidden">
                        <div className="flex-shrink-0 flex items-center justify-between px-4 py-2.5 bg-[#161b22] border-b border-white/5">
                          <div className="flex items-center gap-2">
                            <div className="flex gap-[5px]">
                              <span className="w-[9px] h-[9px] rounded-full bg-[#ff5f57]/80" />
                              <span className="w-[9px] h-[9px] rounded-full bg-[#febc2e]/80" />
                              <span className="w-[9px] h-[9px] rounded-full bg-[#28c840]/80" />
                            </div>
                            <Terminal size={12} className="text-white/40" />
                            <span className="text-[10px] font-bold text-white/50 uppercase tracking-wider">
                              {isZh ? '执行日志' : 'Execution Log'}
                            </span>
                            {isQuickPlaybookRunning && (
                              <span className="flex items-center gap-1 text-[10px] text-cyan-400 font-bold">
                                <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                                LIVE
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex-1 min-h-0 overflow-auto p-4 font-mono text-[12px] leading-relaxed">
                          {deviceEntries.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full gap-3 text-white/15">
                              <Terminal size={32} strokeWidth={1} />
                              <p className="font-sans text-sm">
                                {isQuickPlaybookRunning
                                  ? (isZh ? '等待执行输出...' : 'Waiting for output...')
                                  : (isZh ? '未收到执行日志，请查看执行历史' : 'No logs received. Check execution history')}
                              </p>
                            </div>
                          ) : (
                            deviceEntries.map(([deviceId, ds]) => (
                              <div key={deviceId} className="mb-4 last:mb-0">
                                <div className="flex items-center gap-2 mb-1.5">
                                  <span className={`w-2 h-2 rounded-full ${
                                    ds.status === 'running' ? 'bg-cyan-400 animate-pulse'
                                      : ds.status === 'success' ? 'bg-emerald-400'
                                        : 'bg-red-400'
                                  }`} />
                                  <span className="text-cyan-300 font-bold">[{ds.hostname}]</span>
                                  <span className={`text-[10px] uppercase font-bold ${
                                    ds.status === 'running' ? 'text-cyan-400' : ds.status === 'success' ? 'text-emerald-400' : 'text-red-400'
                                  }`}>
                                    {ds.status}
                                  </span>
                                </div>
                                {Object.entries(ds.phases).map(([phase, ps]) => (
                                  <div key={phase} className="pl-4 mb-1">
                                    <span className={`${ps.success ? 'text-emerald-400' : 'text-red-400'}`}>
                                      {ps.success ? '✓' : '✗'} {phase}
                                    </span>
                                    {ps.output && (
                                      <pre className="text-white/40 pl-3 text-[11px] whitespace-pre-wrap mt-0.5 max-h-24 overflow-hidden">
                                        {ps.output.slice(0, 500)}
                                      </pre>
                                    )}
                                  </div>
                                ))}
                                {ds.error && (
                                  <div className="pl-4 text-red-400 text-[11px]">
                                    ⚠ {ds.error}
                                  </div>
                                )}
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Bottom action bar */}
                    {!isQuickPlaybookRunning && (
                      <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
                        <div className="flex items-center gap-3 text-sm text-gray-600">
                          {isDone && (
                            <>
                              <span className="font-bold">{isZh ? '执行完成' : 'Execution Complete'}</span>
                              <span className="text-gray-300">|</span>
                              <span>{isZh ? `成功率：${Math.round(successCount / Math.max(totalDevices, 1) * 100)}%` : `Success: ${Math.round(successCount / Math.max(totalDevices, 1) * 100)}%`}</span>
                              {failedCount > 0 && (
                                <span className="text-red-500 text-xs font-bold">
                                  {failedCount} {isZh ? '台设备失败' : 'device(s) failed'}
                                </span>
                              )}
                            </>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => onNavigate('/automation/queries')}
                            className="px-4 py-2 rounded-xl text-xs font-bold border border-gray-200 hover:bg-gray-50 transition-all flex items-center gap-1.5"
                          >
                            <ExternalLink size={12} />
                            {isZh ? '查看完整历史' : 'Full History'}
                          </button>
                          <button
                            onClick={handleNewTask}
                            className="px-5 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 transition-all flex items-center gap-1.5"
                          >
                            <Plus size={13} />
                            {isZh ? '新建任务' : 'New Task'}
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Execution Confirmation Modal ── */}
      <AnimatePresence>
        {confirmModalOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[70] bg-black/50 backdrop-blur-sm"
              onClick={() => { setConfirmModalOpen(false); }}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="fixed left-1/2 top-1/2 z-[80] -translate-x-1/2 -translate-y-1/2 w-[440px] bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden"
            >
              <div className={`px-6 py-4 ${
                confirmAction === 'apply'
                  ? (quickPlaybookScenario?.risk === 'high' ? 'bg-gradient-to-r from-red-50 to-rose-50' : 'bg-gradient-to-r from-cyan-50 to-teal-50')
                  : 'bg-gradient-to-r from-cyan-50 to-cyan-100/50'
              }`}>
                <div className="flex items-center gap-3">
                  {confirmAction === 'apply' && quickPlaybookScenario?.risk === 'high' ? (
                    <div className="w-10 h-10 rounded-xl bg-red-500 flex items-center justify-center">
                      <AlertTriangle size={20} className="text-white" />
                    </div>
                  ) : (
                    <div className="w-10 h-10 rounded-xl bg-cyan-500 flex items-center justify-center">
                      <Play size={20} className="text-white" />
                    </div>
                  )}
                  <div>
                    <p className="text-base font-bold text-gray-800">
                      {confirmAction === 'validate'
                        ? (isZh ? '确认运行校验' : 'Confirm Validation')
                        : (isZh ? '确认应用变更' : 'Confirm Apply')}
                    </p>
                    <p className="text-xs text-gray-500">
                      {isZh
                        ? `将对 ${targetCount} 台设备执行${confirmAction === 'validate' ? '校验' : '配置变更'}`
                        : `Will ${confirmAction === 'validate' ? 'validate' : 'apply changes to'} ${targetCount} device(s)`}
                    </p>
                  </div>
                </div>
              </div>
              <div className="px-6 py-4 space-y-3">
                <div className="flex items-center gap-3 text-xs text-gray-600">
                  <span className="font-bold text-gray-400 w-16">{isZh ? '场景' : 'Scenario'}</span>
                  <span>{quickPlaybookScenario?.icon} {isZh ? quickPlaybookScenario?.name_zh : quickPlaybookScenario?.name}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-600">
                  <span className="font-bold text-gray-400 w-16">{isZh ? '目标' : 'Target'}</span>
                  <span>{targetCount} {isZh ? '台设备' : 'device(s)'}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-600">
                  <span className="font-bold text-gray-400 w-16">{isZh ? '平台' : 'Platform'}</span>
                  <span>{getPlatformLabel(quickPlaybookPlatform)}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-600">
                  <span className="font-bold text-gray-400 w-16">{isZh ? '并发' : 'Concurrency'}</span>
                  <span>×{quickPlaybookConcurrency}</span>
                </div>
                {changeTicket.trim() && (
                  <div className="flex items-center gap-3 text-xs text-gray-600">
                    <span className="font-bold text-gray-400 w-16">{isZh ? '工单号' : 'Ticket'}</span>
                    <span className="font-mono text-cyan-700">{changeTicket.trim()}</span>
                  </div>
                )}
                {confirmAction === 'validate' && (
                  <div className="flex items-center gap-2 rounded-lg bg-cyan-50 border border-cyan-100 px-3 py-2 text-xs text-cyan-700">
                    <span>ℹ</span>
                    {isZh ? '校验模式：仅检查，不下发实际配置' : 'Validation mode: check only, no actual config push'}
                  </div>
                )}
                {confirmAction === 'apply' && quickPlaybookScenario?.risk === 'high' && (
                  <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-100 px-3 py-2 text-xs text-red-700">
                    <AlertTriangle size={12} />
                    {isZh ? '⚠ 高风险操作！配置将立即生效，可能影响网络连通性。' : '⚠ High-risk! Config will take effect immediately.'}
                  </div>
                )}
              </div>
              <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-2">
                <button
                  onClick={() => setConfirmModalOpen(false)}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-gray-500 border border-gray-200 hover:bg-gray-50 transition-all"
                >
                  {isZh ? '取消' : 'Cancel'}
                </button>
                <button
                  onClick={handleConfirmExecute}
                  className={`px-5 py-2 rounded-xl text-xs font-bold text-white transition-all ${
                    confirmAction === 'apply' && quickPlaybookScenario?.risk === 'high'
                      ? 'bg-red-500 hover:bg-red-600 shadow-lg shadow-red-500/25'
                      : 'bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40'
                  }`}
                >
                  {confirmAction === 'validate'
                    ? (isZh ? '确认校验' : 'Confirm Validate')
                    : (isZh ? '确认执行' : 'Confirm Apply')}
                </button>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* ── Quick Query Result Overlay (preserved from original) ── */}
      {(quickQueryRunning || quickQueryOutput) && (
        <>
          <div className="fixed inset-0 z-[70] bg-[#020817]/72 backdrop-blur-sm" onClick={() => { onResetQuickQuery(); handleClearSelection(); }} />
          <div className={quickQueryMaximized
            ? 'fixed left-1/2 top-1/2 z-[80] flex h-[84vh] w-[min(1280px,90vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)]'
            : 'fixed left-1/2 top-1/2 z-[80] flex h-[min(520px,70vh)] w-[min(720px,85vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)]'}>
            {/* Terminal title bar */}
            <div className="shrink-0 flex items-center justify-between border-b border-white/[0.06] bg-[linear-gradient(90deg,#1c2030_0%,#161b22_100%)] px-4 py-2.5">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex gap-[6px] mr-1 shrink-0">
                  <span className="w-[10px] h-[10px] rounded-full bg-[#ff5f57]/80" />
                  <span className="w-[10px] h-[10px] rounded-full bg-[#febc2e]/80" />
                  <span className="w-[10px] h-[10px] rounded-full bg-[#28c840]/80" />
                </div>
                {quickQueryRunning
                  ? <RotateCcw size={13} className="animate-spin text-[#00bceb] shrink-0" />
                  : <Monitor size={13} className="text-emerald-400 shrink-0" />}
                <span className="text-[12px] font-bold text-white/90 truncate">{quickQueryLabel}</span>
                <div className="flex items-center gap-2 truncate">
                  <Terminal size={12} className="text-cyan-400/70" />
                  <span className="text-[11px] font-bold tracking-widest text-white/80 uppercase truncate">
                    {targetDevices.length === 1 ? targetDevices[0].hostname : (isZh ? `批量执行 (${targetDevices.length})` : `Batch (${targetDevices.length})`)}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <button onClick={() => onQuickQueryMaximizedChange(!quickQueryMaximized)} className="text-white/30 hover:text-white transition-colors">
                  {quickQueryMaximized ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                </button>
                <button onClick={() => { onResetQuickQuery(); handleClearSelection(); }} className="text-white/30 hover:text-white transition-colors">
                  <X size={16} />
                </button>
              </div>
            </div>



            {/* Executed commands bar */}
            {!quickQueryRunning && quickQueryCommands.length > 0 && (
              <div className="shrink-0 border-b border-white/[0.05] bg-[linear-gradient(180deg,rgba(16,23,34,0.92)_0%,rgba(9,14,22,0.82)_100%)] px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center rounded-full border border-cyan-400/18 bg-cyan-400/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-100/90">
                        {isZh ? '实际执行命令' : 'Executed Commands'}
                      </span>
                      <span className="text-[10px] text-white/38">{quickQueryCommands.length} {isZh ? '条' : `cmd${quickQueryCommands.length > 1 ? 's' : ''}`}</span>
                    </div>
                    <div className="mt-2 flex flex-col gap-1.5">
                      {quickQueryCommands.map((cmd, idx) => (
                        <div key={`${cmd}-${idx}`} className="overflow-hidden rounded-xl border border-cyan-400/14 bg-[linear-gradient(180deg,rgba(3,11,21,0.96)_0%,rgba(7,18,32,0.92)_100%)]">
                          <div className="flex items-stretch">
                            <span className="w-1 shrink-0 bg-[linear-gradient(180deg,rgba(34,211,238,0.95)_0%,rgba(6,182,212,0.45)_100%)]" />
                            <div className="min-w-0 flex-1 px-3 py-2">
                              <div className="mb-1 flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-200/55">
                                <span>{isZh ? '命令' : 'Command'}</span>
                                <span className="text-white/18">#{idx + 1}</span>
                              </div>
                              <code className="block overflow-x-auto text-[11px] font-medium leading-relaxed text-[#F7FBFF]">{cmd}</code>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      const ok = await copyTextWithFallback(quickQueryCommands.join('\n'));
                      showToast(ok ? (isZh ? '命令已复制' : 'Copied') : (isZh ? '复制失败' : 'Failed'), ok ? 'success' : 'error');
                    }}
                    className="shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-white/60 hover:bg-white/[0.08] hover:text-white transition-all"
                  >
                    {isZh ? '复制' : 'Copy'}
                  </button>
                </div>
              </div>
            )}

            {/* Terminal content */}
            <div className="flex-1 overflow-auto terminal-scroll">
              {quickQueryRunning ? (
                <div className="flex flex-col items-center justify-center py-16 gap-4">
                  <div className="w-10 h-10 rounded-full border-2 border-[#00bceb]/20 border-t-[#00bceb] animate-spin" />
                  <span className="text-xs text-white/25 font-mono">{isZh ? '正在查询...' : 'Querying...'}</span>
                </div>
              ) : quickQueryStructured && quickQueryView === 'table' ? (
                <div className="p-5 space-y-4">
                  <div className="flex items-center justify-between gap-3 border-b border-white/[0.04] pb-3">
                    <div className="flex items-center gap-4 min-w-0">
                      <div className="min-w-0">
                        <p className="text-[12px] font-bold text-white/90 truncate">{quickQueryLabel}</p>
                        <p className="mt-1 text-[10px] text-white/35">{quickQueryTable.category?.parser || 'ntc-templates'} · {isZh ? '记录数' : 'Records'} {filteredQuickQueryRecords.length} / {Number(quickQueryTable.category?.count || 0)}</p>
                      </div>
                      <div className="relative">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/25" size={11} />
                        <input
                          type="text"
                          value={quickQuerySearch}
                          onChange={(e) => setQuickQuerySearch(e.target.value)}
                          placeholder={isZh ? '过滤结果...' : 'Filter results...'}
                          className="pl-7 pr-3 py-1 bg-white/[0.04] border border-white/[0.08] rounded-lg text-[11px] text-white placeholder-white/25 outline-none focus:border-cyan-500/50 w-44 transition-all"
                        />
                        {quickQuerySearch && (
                          <button
                            onClick={() => setQuickQuerySearch('')}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-white/25 hover:text-white"
                          >
                            <X size={10} />
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {quickQueryTable.category?.parse_errors?.length > 0 && (
                        <span className="rounded-full bg-amber-500/12 px-2 py-1 text-[10px] font-bold uppercase text-amber-300">{isZh ? '部分回退' : 'Partial Fallback'}</span>
                      )}
                      <OutputActions
                        text={quickQueryOutput}
                        csvRows={filteredQuickQueryRecords as Array<Record<string, unknown>>}
                        filename={`${(quickQueryLabel || 'query').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 40) || 'query'}`}
                        theme="dark"
                        zh={isZh}
                      />
                    </div>
                  </div>
                  {quickQueryTable.records.length > 0 ? (
                    <div className={quickQueryMaximized ? 'overflow-auto rounded-xl border border-white/[0.06] bg-black/20 max-h-[calc(84vh-12rem)]' : 'overflow-auto rounded-xl border border-white/[0.06] bg-black/20 min-h-[24rem] max-h-[58vh]'}>
                      <table className="min-w-full text-left text-[12px] text-[#d8e2eb]">
                        <thead className="sticky top-0 bg-[#101722]">
                          <tr className="border-b border-white/[0.06]">
                            {quickQueryTable.columns.map(col => (
                              <th key={col} className="px-3 py-2 text-[10px] font-bold uppercase tracking-[0.14em] text-white/45 whitespace-nowrap">{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {filteredQuickQueryRecords.map((rec, ri) => (
                            <tr key={ri} className="border-b border-white/[0.04] last:border-b-0 hover:bg-white/[0.03]">
                              {quickQueryTable.columns.map(col => {
                                const val = rec?.[col];
                                return (
                                  <td key={`${ri}-${col}`} className="px-3 py-2 align-top text-[11px] text-[#d8e2eb] whitespace-nowrap">
                                    {val == null || val === '' ? <span className="text-white/20">-</span> : String(val)}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="rounded-xl border border-dashed border-white/[0.08] bg-white/[0.02] px-4 py-5 text-sm text-white/45">
                      {isZh ? '当前没有结构化记录，可切回终端查看原始回显。' : 'No structured records available. Switch to Terminal for raw output.'}
                    </div>
                  )}
                  {quickQueryTable.category?.parse_errors?.length > 0 && (
                    <div className="rounded-xl border border-amber-400/20 bg-amber-400/8 px-4 py-3 text-xs text-amber-200">
                      <p className="font-bold uppercase tracking-[0.14em]">{isZh ? '解析提示' : 'Parsing Notes'}</p>
                      <div className="mt-2 space-y-1">
                        {quickQueryTable.category.parse_errors.map((item: any, idx: number) => (
                          <div key={idx}>{item.command}: {item.error}</div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-5 relative group/output">
                  <div className="mb-3 flex items-start justify-between gap-2 border-b border-white/[0.04] pb-3">
                    <div className="flex items-start gap-2 flex-1 min-w-0">
                      <span className="text-emerald-400/60 font-mono font-bold text-[11px] mt-0.5 select-none shrink-0">❯</span>
                      <code className="text-[11px] font-mono text-emerald-400/40 leading-relaxed whitespace-pre-wrap break-all">{quickQueryLabel}</code>
                    </div>
                    {quickQueryOutput && (
                      <OutputActions
                        text={quickQueryOutput}
                        filename={`${(quickQueryLabel || 'query').replace(/[^a-zA-Z0-9_-]+/g, '_').slice(0, 40) || 'query'}`}
                        theme="dark"
                        zh={isZh}
                      />
                    )}
                  </div>
                  <pre className="text-[13px] font-mono text-[#e6edf3] leading-[1.75] whitespace-pre-wrap break-all select-text">{quickQueryOutput}</pre>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default AutomationExecuteTab;
