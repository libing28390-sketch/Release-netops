import React, { useState, useMemo, useRef, useEffect } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  Filter,
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
  X,
  XCircle,
  Zap,
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import type { Device } from '../types';
import Pagination from '../components/Pagination';

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
  onRunValidation: () => void;
  onRunApply: () => void;
  onRunQuickQuery: (label: string, commands: string, operationalCategory?: string) => void;
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

const CATEGORY_META: Record<string, { label: string; labelEn: string; icon: string; color: string }> = {
  L2: { label: '二层网络', labelEn: 'L2 Network', icon: '🔗', color: 'text-blue-600' },
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
    automationSearch, scenarioSearch, filteredScenarios,
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
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [showQuickQuery, setShowQuickQuery] = useState(false);
  const [deviceViewMode, setDeviceViewMode] = useState<'grid' | 'list'>('grid');
  const [devicePage, setDevicePage] = useState(1);
  const DEVICE_PAGE_SIZE = 18;
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'validate' | 'apply'>('validate');
  const logEndRef = useRef<HTMLDivElement>(null);

  /* ── Derived ── */
  const targetCount = batchMode ? batchDeviceIds.length : (selectedDevice ? 1 : 0);
  const riskNeedsConfirm = quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed;
  const hasMissingRequired = quickMissingRequiredFields.length > 0;
  const previewLineCount = (['pre_check', 'execute', 'post_check', 'rollback'] as const)
    .reduce((acc, phase) => acc + (quickPlaybookPreview?.[phase]?.length || 0), 0);

  const canExecute = quickPlaybookScenario && hasQuickTargets && !isQuickPlaybookRunning
    && !quickHasMixedPlatforms && !quickPlatformMismatch && !hasMissingRequired
    && !(quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed);

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
        if (!d.hostname.toLowerCase().includes(q) && !d.ip_address.includes(q)) return false;
      }
      if (statusFilter !== 'all' && d.status !== statusFilter) return false;
      if (vendorFilter !== 'all') {
        const vendor = getVendor(d.platform);
        if (vendor !== vendorFilter) return false;
      }
      if (siteFilter !== 'all' && (d.site || '') !== siteFilter) return false;
      return true;
    });
  }, [devices, automationSearch, statusFilter, vendorFilter, siteFilter]);

  /* Auto-switch to list view when many devices */
  useEffect(() => {
    if (filteredDevices.length > 12) setDeviceViewMode('list');
  }, []);

  /* Reset page when filters change */
  useEffect(() => { setDevicePage(1); }, [automationSearch, statusFilter, vendorFilter, siteFilter]);

  const pagedDevices = useMemo(() => {
    const start = (devicePage - 1) * DEVICE_PAGE_SIZE;
    return filteredDevices.slice(start, start + DEVICE_PAGE_SIZE);
  }, [filteredDevices, devicePage]);

  /* Unique values for filters */
  const vendors = useMemo(() => [...new Set(devices.map(d => getVendor(d.platform)))].sort(), [devices]);
  const sites = useMemo(() => [...new Set(devices.filter(d => d.site).map(d => d.site))].sort(), [devices]);

  /* Filtered scenarios */
  const displayScenarios = useMemo(() => {
    return filteredScenarios.filter(s => {
      if (categoryFilter !== 'all' && (s.category || 'Custom') !== categoryFilter) return false;
      if (riskFilter !== 'all' && s.risk !== riskFilter) return false;
      return true;
    });
  }, [filteredScenarios, categoryFilter, riskFilter]);

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
  const blockingIssues = useMemo(() => {
    const items: Array<{ message: string; severity: 'critical' | 'high' | 'medium' }> = [];
    if (!hasQuickTargets) items.push({ message: isZh ? '请先选择目标设备' : 'Select target device(s)', severity: 'critical' });
    if (quickHasMixedPlatforms) items.push({ message: isZh ? '检测到多平台设备，请按平台分批执行' : 'Mixed platforms detected', severity: 'critical' });
    if (quickPlatformMismatch) items.push({ message: isZh ? '该场景不支持当前设备平台' : 'Scenario unsupported on platform', severity: 'high' });
    if (hasMissingRequired) items.push({ message: isZh ? `缺少必填字段：${quickMissingRequiredFields.join('、')}` : `Missing: ${quickMissingRequiredFields.join(', ')}`, severity: 'high' });
    if (riskNeedsConfirm) items.push({ message: isZh ? '请确认高风险执行' : 'Confirm high-risk execution', severity: 'medium' });
    return items;
  }, [hasQuickTargets, quickHasMixedPlatforms, quickPlatformMismatch, hasMissingRequired, riskNeedsConfirm, isZh, quickMissingRequiredFields]);

  /* Quick Query helpers */
  const singleDevice = batchMode && batchDeviceIds.length === 1
    ? devices.find(d => d.id === batchDeviceIds[0]) || null
    : selectedDevice;
  const platform = (singleDevice?.platform || '').toLowerCase();
  const isCisco = platform.includes('cisco') || platform.includes('arista') || platform.includes('rgos');
  const isHuawei = platform.includes('huawei') || platform.includes('h3c') || platform.includes('ce_');
  const isJuniper = platform.includes('juniper') || platform.includes('junos');
  const deviceRole = (singleDevice?.role || '').toLowerCase();

  const queryPresets = useMemo(() => {
    const all: Array<{ icon: string; label: string; labelEn: string; cmds: string; group: string; operationalCategory?: string; excludeRoles?: string[] }> = [
      { icon: '📡', label: '接口状态', labelEn: 'Interfaces', group: 'net', operationalCategory: 'interfaces', cmds: isCisco ? 'show ip interface brief' : isHuawei ? 'display interface brief' : isJuniper ? 'show interfaces terse' : 'show ip interface brief' },
      { icon: '📋', label: 'ARP表', labelEn: 'ARP Table', group: 'net', operationalCategory: 'arp', cmds: isCisco ? 'show arp' : isHuawei ? 'display arp' : isJuniper ? 'show arp' : 'show arp' },
      { icon: '🏷️', label: 'MAC表', labelEn: 'MAC Table', group: 'net', operationalCategory: 'mac_table', excludeRoles: ['router'], cmds: isCisco ? 'show mac address-table' : isHuawei ? 'display mac-address' : isJuniper ? 'show ethernet-switching table' : 'show mac address-table' },
      { icon: '📊', label: 'VLAN', labelEn: 'VLAN', group: 'net', excludeRoles: ['router'], cmds: isCisco ? 'show vlan brief' : isHuawei ? 'display vlan' : isJuniper ? 'show vlans' : 'show vlan brief' },
      { icon: '📌', label: 'LLDP邻居', labelEn: 'LLDP', group: 'net', operationalCategory: 'neighbors', cmds: isCisco ? 'show lldp neighbors' : isHuawei ? 'display lldp neighbor brief' : isJuniper ? 'show lldp neighbors' : 'show lldp neighbors' },
      { icon: '🗺️', label: '路由表', labelEn: 'Routes', group: 'route', operationalCategory: 'routing_table', cmds: isCisco ? 'show ip route' : isHuawei ? 'display ip routing-table' : isJuniper ? 'show route' : 'show ip route' },
      { icon: '🔗', label: 'BGP邻居', labelEn: 'BGP Peers', group: 'route', operationalCategory: 'bgp', excludeRoles: ['access'], cmds: isCisco ? 'show bgp summary' : isHuawei ? 'display bgp peer' : isJuniper ? 'show bgp summary' : 'show bgp summary' },
      { icon: '🔍', label: 'OSPF邻居', labelEn: 'OSPF Nbrs', group: 'route', operationalCategory: 'ospf', excludeRoles: ['access'], cmds: isCisco ? 'show ip ospf neighbor' : isHuawei ? 'display ospf peer brief' : isJuniper ? 'show ospf neighbor' : 'show ip ospf neighbor' },
      { icon: '🏥', label: '设备信息', labelEn: 'Version', group: 'sys', cmds: isCisco ? 'show version' : isHuawei ? 'display version' : isJuniper ? 'show version' : 'show version' },
      { icon: '📝', label: '日志', labelEn: 'Logs', group: 'sys', cmds: isCisco ? 'show logging | tail 30' : isHuawei ? 'display logbuffer last 30' : isJuniper ? 'show log messages | last 30' : 'show logging | tail 30' },
      { icon: '⏱️', label: '运行时间', labelEn: 'Uptime', group: 'sys', cmds: isCisco ? 'show uptime' : isHuawei ? 'display clock\ndisplay version | include uptime' : isJuniper ? 'show system uptime' : 'show uptime' },
      { icon: '💾', label: '运行配置', labelEn: 'Running Config', group: 'sys', cmds: isCisco ? 'show running-config' : isHuawei ? 'display current-configuration' : isJuniper ? 'show configuration' : 'show running-config' },
    ];
    return all.filter(p => !p.excludeRoles || !p.excludeRoles.includes(deviceRole));
  }, [isCisco, isHuawei, isJuniper, deviceRole]);

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
    if (confirmAction === 'validate') onRunValidation();
    else onRunApply();
  };

  const handleSelectAllOnline = () => {
    if (!batchMode) onToggleBatchMode();
    filteredDevices.filter(d => d.status === 'online').forEach(d => {
      if (!batchDeviceIds.includes(d.id)) onToggleBatchDevice(d.id);
    });
  };

  const varGroupLabel = (group: string) => {
    if (group === 'address') return isZh ? '🌐 地址与邻居' : '🌐 Address & Neighbors';
    if (group === 'interface') return isZh ? '📡 接口与二层' : '📡 Interfaces & L2';
    if (group === 'routing') return isZh ? '🗺️ 路由与策略' : '🗺️ Routing & Policy';
    return isZh ? '⚙️ 通用参数' : '⚙️ General';
  };

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
            {isZh ? '选择设备 → 选择任务 → 配置参数 → 批量执行' : 'Select → Configure → Execute → Monitor'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onOpenCustomCommandModal}
            className="px-3 py-2 text-xs font-semibold border border-gray-200 rounded-xl hover:bg-gray-50 transition-all flex items-center gap-1.5"
          >
            <Plus size={12} />
            {isZh ? '自定义命令' : 'Custom Command'}
          </button>
          <button
            onClick={() => onNavigate('/automation/history')}
            className="px-3 py-2 text-xs font-semibold border border-gray-200 rounded-xl hover:bg-gray-50 transition-all"
          >
            {isZh ? '执行历史' : 'History'}
          </button>
        </div>
      </div>

      {/* ── Stepper ── */}
      <div className="flex-shrink-0 mb-4">
        <div className="flex items-center bg-gradient-to-r from-slate-900 via-slate-800 to-slate-900 rounded-2xl px-6 py-3 shadow-lg">
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
                  <div className="flex-1 mx-3 h-[2px] rounded-full overflow-hidden bg-white/10">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        isDone || isActive ? 'bg-gradient-to-r from-cyan-400 to-teal-400 w-full' : 'w-0'
                      }`}
                    />
                  </div>
                )}
                <button
                  onClick={() => handleStepClick(step.id)}
                  className={`flex items-center gap-2.5 px-4 py-2 rounded-xl transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-cyan-500/20 to-teal-500/20 ring-1 ring-cyan-400/30'
                      : isDone
                        ? 'bg-white/5 hover:bg-white/10'
                        : 'opacity-40 cursor-default'
                  }`}
                >
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold transition-all ${
                    isRunning
                      ? 'bg-blue-500 text-white animate-pulse'
                      : isDone && !isActive
                        ? 'bg-emerald-500/90 text-white'
                        : isActive
                          ? 'bg-cyan-500 text-white shadow-lg shadow-cyan-500/30'
                          : 'bg-white/10 text-white/40'
                  }`}>
                    {isRunning ? (
                      <RotateCcw size={13} className="animate-spin" />
                    ) : isDone && !isActive ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <Icon size={14} />
                    )}
                  </div>
                  <div className="text-left">
                    <p className={`text-xs font-bold ${isActive ? 'text-white' : isDone ? 'text-white/70' : 'text-white/35'}`}>
                      {isZh ? step.label : step.labelEn}
                    </p>
                    {isActive && step.id === 1 && targetCount > 0 && (
                      <p className="text-[10px] text-cyan-300/80">{targetCount} {isZh ? '台已选' : 'selected'}</p>
                    )}
                    {isActive && step.id === 2 && quickPlaybookScenario && (
                      <p className="text-[10px] text-cyan-300/80 truncate max-w-[100px]">{isZh ? quickPlaybookScenario.name_zh : quickPlaybookScenario.name}</p>
                    )}
                    {step.id === 4 && isRunning && (
                      <p className="text-[10px] text-blue-300/80">{isZh ? '执行中...' : 'Running...'}</p>
                    )}
                  </div>
                </button>
              </React.Fragment>
            );
          })}
        </div>
      </div>

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
              className="h-full flex flex-col gap-3"
            >
              {/* Filter bar */}
              <div className="flex-shrink-0 flex items-center gap-3 bg-white rounded-2xl border border-gray-100 shadow-sm px-4 py-3">
                <div className="flex items-center gap-1.5">
                  <Filter size={13} className="text-gray-400" />
                  <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">{isZh ? '筛选' : 'Filter'}</span>
                </div>
                <div className="flex items-center gap-2 flex-1">
                  <div className="relative flex-1 max-w-[280px]">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-300" size={13} />
                    <input
                      type="text"
                      placeholder={isZh ? '搜索主机名或IP...' : 'Search hostname or IP...'}
                      value={automationSearch}
                      onChange={e => onAutomationSearchChange(e.target.value)}
                      className="w-full pl-8 pr-3 py-1.5 bg-gray-50 border border-gray-100 rounded-lg text-xs focus:border-cyan-300 focus:bg-white outline-none transition-all"
                    />
                  </div>
                  <select
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value)}
                    className="px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300"
                  >
                    <option value="all">{isZh ? '全部状态' : 'All Status'}</option>
                    <option value="online">{isZh ? '🟢 在线' : '🟢 Online'}</option>
                    <option value="offline">{isZh ? '🔴 离线' : '🔴 Offline'}</option>
                  </select>
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
                  {sites.length > 1 && (
                    <select
                      value={siteFilter}
                      onChange={e => setSiteFilter(e.target.value)}
                      className="px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300"
                    >
                      <option value="all">{isZh ? '全部站点' : 'All Sites'}</option>
                      {sites.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={onToggleBatchMode}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
                      batchMode
                        ? 'bg-amber-100 text-amber-700 border border-amber-200 shadow-sm'
                        : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                    }`}
                  >
                    <Database size={12} />
                    {isZh ? '批量模式' : 'Batch'}
                  </button>
                  {batchMode && (
                    <button
                      onClick={handleSelectAllOnline}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-100 hover:bg-emerald-100 transition-all"
                    >
                      <CheckCircle2 size={11} />
                      {isZh ? '全选在线' : 'Select Online'}
                    </button>
                  )}
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
              <div className="min-h-0 overflow-auto">
                {deviceViewMode === 'grid' ? (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-2.5">
                  {pagedDevices.map(device => {
                    const isSelected = batchMode
                      ? batchDeviceIds.includes(device.id)
                      : selectedDevice?.id === device.id;
                    const vendor = getVendor(device.platform);
                    return (
                      <motion.button
                        key={device.id}
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        onClick={() => {
                          if (batchMode) onToggleBatchDevice(device.id);
                          else {
                            if (selectedDevice?.id !== device.id) onResetQuickQuery();
                            onSelectDevice(device);
                          }
                        }}
                        className={`relative p-3.5 rounded-xl border-2 text-left transition-all group ${
                          isSelected
                            ? 'border-cyan-400 bg-cyan-50/60 shadow-lg shadow-cyan-500/10 ring-1 ring-cyan-200'
                            : device.status === 'online'
                              ? 'border-gray-100 bg-white hover:border-cyan-200 hover:shadow-md hover:-translate-y-0.5'
                              : 'border-gray-100 bg-gray-50/60 opacity-70 hover:opacity-90'
                        }`}
                      >
                        {batchMode && (
                          <div className={`absolute top-2 right-2 w-5 h-5 rounded-md border-2 flex items-center justify-center transition-all ${
                            isSelected ? 'bg-cyan-500 border-cyan-500' : 'border-gray-200 bg-white'
                          }`}>
                            {isSelected && <CheckCircle2 size={12} className="text-white" />}
                          </div>
                        )}
                        <div className="flex items-center gap-2 mb-2">
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                            device.status === 'online' ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-gray-300'
                          }`} />
                          <span className="text-xs font-bold text-gray-800 truncate">{device.hostname}</span>
                        </div>
                        <p className="text-[11px] font-mono text-gray-400 mb-1.5">{device.ip_address}</p>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{vendor}</span>
                          {device.role && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-400">{device.role}</span>
                          )}
                          {device.site && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-400">{device.site}</span>
                          )}
                        </div>
                        {(device.cpu_usage != null || device.memory_usage != null) && (
                          <div className="mt-2 flex items-center gap-3 text-[9px] text-gray-400">
                            {device.cpu_usage != null && <span>CPU {device.cpu_usage}%</span>}
                            {device.memory_usage != null && <span>MEM {device.memory_usage}%</span>}
                          </div>
                        )}
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
                /* ── Compact List View ── */
                <div className="rounded-xl border border-gray-100 bg-white overflow-hidden">
                  <table className="w-full text-left">
                    <thead>
                      <tr className="border-b border-gray-100 bg-gray-50/60">
                        {batchMode && <th className="w-10 px-3 py-2" />}
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '状态' : 'Status'}</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '主机名' : 'Hostname'}</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">IP</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '厂商' : 'Vendor'}</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '角色' : 'Role'}</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">{isZh ? '站点' : 'Site'}</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">CPU</th>
                        <th className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-gray-400">MEM</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedDevices.map(device => {
                        const isSelected = batchMode
                          ? batchDeviceIds.includes(device.id)
                          : selectedDevice?.id === device.id;
                        const vendor = getVendor(device.platform);
                        return (
                          <tr
                            key={device.id}
                            onClick={() => {
                              if (batchMode) onToggleBatchDevice(device.id);
                              else {
                                if (selectedDevice?.id !== device.id) onResetQuickQuery();
                                onSelectDevice(device);
                              }
                            }}
                            className={`border-b border-gray-50 cursor-pointer transition-colors ${
                              isSelected
                                ? 'bg-cyan-50/70 hover:bg-cyan-50'
                                : device.status === 'online'
                                  ? 'hover:bg-gray-50/80'
                                  : 'opacity-60 hover:opacity-80'
                            }`}
                          >
                            {batchMode && (
                              <td className="px-3 py-1.5">
                                <div className={`w-4 h-4 rounded border-2 flex items-center justify-center ${
                                  isSelected ? 'bg-cyan-500 border-cyan-500' : 'border-gray-200 bg-white'
                                }`}>
                                  {isSelected && <CheckCircle2 size={10} className="text-white" />}
                                </div>
                              </td>
                            )}
                            <td className="px-3 py-1.5">
                              <span className={`w-2 h-2 rounded-full inline-block ${
                                device.status === 'online' ? 'bg-emerald-500' : 'bg-gray-300'
                              }`} />
                            </td>
                            <td className="px-3 py-1.5 text-xs font-bold text-gray-800">{device.hostname}</td>
                            <td className="px-3 py-1.5 text-[11px] font-mono text-gray-400">{device.ip_address}</td>
                            <td className="px-3 py-1.5">
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{vendor}</span>
                            </td>
                            <td className="px-3 py-1.5 text-[10px] text-gray-400">{device.role || '—'}</td>
                            <td className="px-3 py-1.5 text-[10px] text-blue-400">{device.site || '—'}</td>
                            <td className="px-3 py-1.5 text-[10px] text-gray-400 tabular-nums">{device.cpu_usage != null ? `${device.cpu_usage}%` : '—'}</td>
                            <td className="px-3 py-1.5 text-[10px] text-gray-400 tabular-nums">{device.memory_usage != null ? `${device.memory_usage}%` : '—'}</td>
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

              {/* Pagination + Count */}
              {filteredDevices.length > DEVICE_PAGE_SIZE && (
                <div className="flex-shrink-0 px-1 mt-2">
                  <Pagination
                    currentPage={devicePage}
                    totalItems={filteredDevices.length}
                    onPageChange={setDevicePage}
                    itemsPerPage={DEVICE_PAGE_SIZE}
                    language={language}
                  />
                </div>
              )}

              {/* Bottom action bar — always sticky at bottom */}
              <div className="mt-auto flex-shrink-0 flex items-center justify-between rounded-2xl border border-gray-100 bg-gradient-to-r from-slate-50 to-gray-50 px-5 py-3.5 shadow-sm">
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
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-cyan-50 text-cyan-700 text-xs font-bold border border-cyan-100 shadow-sm">
                      <CheckCircle2 size={12} />
                      {isZh ? `已选 ${targetCount} 台` : `${targetCount} selected`}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {singleDevice && (
                    <button
                      onClick={() => setShowQuickQuery(!showQuickQuery)}
                      className="px-4 py-2.5 rounded-xl text-xs font-bold border border-gray-200 bg-white hover:bg-gray-50 transition-all flex items-center gap-1.5 shadow-sm"
                    >
                      <Terminal size={13} />
                      {isZh ? '快捷查询' : 'Quick Query'}
                    </button>
                  )}
                  <button
                    onClick={() => targetCount > 0 && setCurrentStep(2)}
                    disabled={targetCount === 0}
                    className={`px-7 py-2.5 rounded-xl text-sm font-bold transition-all flex items-center gap-2 ${
                      targetCount > 0
                        ? 'bg-gradient-to-r from-cyan-500 to-teal-500 text-white shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 hover:-translate-y-0.5'
                        : 'bg-gray-100 text-gray-300 cursor-not-allowed'
                    }`}
                  >
                    {isZh ? '下一步：选择任务' : 'Next: Select Task'}
                    <ChevronRight size={15} />
                  </button>
                </div>
              </div>

              {/* Quick Query slide-up panel */}
              <AnimatePresence>
                {showQuickQuery && singleDevice && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 20 }}
                    className="fixed bottom-4 left-[calc(var(--sidebar-width,240px)+1rem)] right-4 z-50 bg-white rounded-2xl border border-gray-200 shadow-2xl p-4"
                    style={{ maxHeight: '45vh' }}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2.5">
                        <Terminal size={14} className="text-cyan-600" />
                        <span className="text-sm font-bold text-gray-700">{isZh ? '快捷查询' : 'Quick Query'}</span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-50 text-cyan-700 font-mono font-bold border border-cyan-100">
                          {singleDevice.hostname}
                        </span>
                      </div>
                      <button onClick={() => setShowQuickQuery(false)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400"><X size={14} /></button>
                    </div>
                    <div className="grid grid-cols-6 md:grid-cols-8 lg:grid-cols-12 gap-2 overflow-auto" style={{ maxHeight: 'calc(45vh - 60px)' }}>
                      {queryPresets.map((cmd, idx) => (
                        <button
                          key={idx}
                          disabled={quickQueryRunning}
                          onClick={() => { onRunQuickQuery(isZh ? cmd.label : cmd.labelEn, cmd.cmds, cmd.operationalCategory); setShowQuickQuery(false); }}
                          title={cmd.cmds}
                          className="flex flex-col items-center gap-1 px-2 py-2.5 rounded-xl border border-gray-100 bg-white hover:border-cyan-200 hover:shadow-md hover:-translate-y-0.5 transition-all disabled:opacity-40"
                        >
                          <span className="text-lg leading-none">{cmd.icon}</span>
                          <span className="text-[10px] font-semibold text-gray-500 text-center leading-tight">{isZh ? cmd.label : cmd.labelEn}</span>
                        </button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
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

                  {/* Options: Concurrency + Dry-run */}
                  <div className="flex items-center gap-4 pt-2 border-t border-gray-100">
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
                        onRunValidation();
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
                            : 'bg-gradient-to-r from-blue-50 to-cyan-50 border-blue-200'
                    }`}>
                      <div className="px-5 py-3 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          {isQuickPlaybookRunning ? (
                            <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center">
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
                              <span className="flex items-center gap-1.5 text-xs font-bold text-blue-700 bg-blue-100 px-2.5 py-1 rounded-lg">
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
                        <div className="h-1 bg-blue-100">
                          <div
                            className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-500 ease-out"
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
                              <RotateCcw size={24} className="text-blue-400 animate-spin" />
                              <p className="text-xs text-gray-400">{isZh ? '等待设备响应...' : 'Waiting for device response...'}</p>
                            </div>
                          )}
                          {deviceEntries.map(([deviceId, deviceState]) => (
                            <div
                              key={deviceId}
                              className={`rounded-xl border-2 p-3 transition-all ${
                                deviceState.status === 'running' ? 'border-blue-200 bg-blue-50/40'
                                  : deviceState.status === 'success' ? 'border-emerald-200 bg-emerald-50/40'
                                    : deviceState.status === 'partial_failure' ? 'border-amber-200 bg-amber-50/40'
                                      : 'border-red-200 bg-red-50/40'
                              }`}
                            >
                              <div className="flex items-center gap-2 mb-1.5">
                                {deviceState.status === 'running' ? (
                                  <RotateCcw size={13} className="text-blue-500 animate-spin flex-shrink-0" />
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
                              <span className="flex items-center gap-1 text-[10px] text-blue-400 font-bold">
                                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                                LIVE
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex-1 min-h-0 overflow-auto p-4 font-mono text-[12px] leading-relaxed">
                          {deviceEntries.length === 0 ? (
                            <div className="flex flex-col items-center justify-center h-full gap-3 text-white/15">
                              <Terminal size={32} strokeWidth={1} />
                              <p className="font-sans text-sm">{isZh ? '等待执行输出...' : 'Waiting for output...'}</p>
                            </div>
                          ) : (
                            deviceEntries.map(([deviceId, ds]) => (
                              <div key={deviceId} className="mb-4 last:mb-0">
                                <div className="flex items-center gap-2 mb-1.5">
                                  <span className={`w-2 h-2 rounded-full ${
                                    ds.status === 'running' ? 'bg-blue-400 animate-pulse'
                                      : ds.status === 'success' ? 'bg-emerald-400'
                                        : 'bg-red-400'
                                  }`} />
                                  <span className="text-cyan-300 font-bold">[{ds.hostname}]</span>
                                  <span className={`text-[10px] uppercase font-bold ${
                                    ds.status === 'running' ? 'text-blue-400' : ds.status === 'success' ? 'text-emerald-400' : 'text-red-400'
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
                            onClick={() => onNavigate('/automation/history')}
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
              onClick={() => setConfirmModalOpen(false)}
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
                  : 'bg-gradient-to-r from-blue-50 to-cyan-50'
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
                {confirmAction === 'validate' && (
                  <div className="flex items-center gap-2 rounded-lg bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-blue-700">
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
          <div className="fixed inset-0 z-[70] bg-[#020817]/72 backdrop-blur-sm" onClick={onResetQuickQuery} />
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
                <span className="shrink-0 text-[10px] px-2 py-0.5 rounded-md bg-white/[0.06] text-white/35 font-mono border border-white/[0.04]">
                  {singleDevice?.hostname || ''}
                </span>
                {!quickQueryRunning && quickQueryStructured && (
                  <div className="ml-2 flex items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.04] p-1">
                    <button
                      onClick={() => onQuickQueryViewChange('terminal')}
                      className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase transition-all ${quickQueryView === 'terminal' ? 'bg-white/14 text-white' : 'text-white/45 hover:text-white/75'}`}
                    >
                      {isZh ? '终端' : 'Terminal'}
                    </button>
                    <button
                      onClick={() => onQuickQueryViewChange('table')}
                      className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase transition-all ${quickQueryView === 'table' ? 'bg-white/14 text-white' : 'text-white/45 hover:text-white/75'}`}
                    >
                      {isZh ? '表格' : 'Table'}
                    </button>
                  </div>
                )}
              </div>
              <div className="flex items-center gap-0.5 shrink-0">
                {!quickQueryRunning && quickQueryOutput && (
                  <button onClick={() => onQuickQueryMaximizedChange(!quickQueryMaximized)} className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all">
                    {quickQueryMaximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                  </button>
                )}
                {!quickQueryRunning && quickQueryStructured && quickQueryTable.records.length > 0 && (
                  <button onClick={() => onExportQuickQueryTable(quickQueryCommands)} className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all" title={isZh ? '导出 Excel' : 'Export Excel'}>
                    <Download size={13} />
                  </button>
                )}
                {!quickQueryRunning && quickQueryOutput && (
                  <button
                    onClick={async () => {
                      const ok = await copyTextWithFallback(quickQueryOutput);
                      showToast(ok ? (isZh ? '已复制' : 'Copied') : (isZh ? '复制失败' : 'Copy failed'), ok ? 'success' : 'error');
                    }}
                    className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all"
                  >
                    <Copy size={13} />
                  </button>
                )}
                <button onClick={onResetQuickQuery} className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all">
                  <X size={13} />
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
                    <div>
                      <p className="text-[12px] font-bold text-white/90">{quickQueryLabel}</p>
                      <p className="mt-1 text-[10px] text-white/35">{quickQueryTable.category?.parser || 'ntc-templates'} · {isZh ? '记录数' : 'Records'} {Number(quickQueryTable.category?.count || 0)}</p>
                    </div>
                    {quickQueryTable.category?.parse_errors?.length > 0 && (
                      <span className="rounded-full bg-amber-500/12 px-2 py-1 text-[10px] font-bold uppercase text-amber-300">{isZh ? '部分回退' : 'Partial Fallback'}</span>
                    )}
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
                          {quickQueryTable.records.map((rec, ri) => (
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
                <div className="p-5">
                  <div className="mb-3 flex items-start gap-2 border-b border-white/[0.04] pb-3">
                    <span className="text-emerald-400/60 font-mono font-bold text-[11px] mt-0.5 select-none shrink-0">❯</span>
                    <code className="text-[11px] font-mono text-emerald-400/40 leading-relaxed whitespace-pre-wrap">{quickQueryLabel}</code>
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
