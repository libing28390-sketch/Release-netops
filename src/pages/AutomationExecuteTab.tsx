import React from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  Maximize2,
  Minimize2,
  Monitor,
  Plus,
  RotateCcw,
  Search,
  Server,
  X,
  XCircle,
  Zap,
} from 'lucide-react';
import type { Device } from '../types';

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

const AutomationExecuteTab: React.FC<AutomationExecuteTabProps> = ({
  t,
  language,
  sectionHeaderRowClass,
  devices,
  selectedDevice,
  batchMode,
  batchDeviceIds,
  automationSearch,
  scenarioSearch,
  filteredScenarios,
  quickPlaybookScenario,
  quickPlaybookVars,
  quickPlaybookPlatform,
  quickPlaybookDryRun,
  quickPlaybookConcurrency,
  quickPlaybookPreview,
  quickRiskConfirmed,
  hasQuickTargets,
  quickMissingRequiredFields,
  quickHasMixedPlatforms,
  quickPlatformMismatch,
  isQuickPlaybookRunning,
  quickExecutionResult,
  executionStatus,
  wsCompleteMsg,
  deviceStatusMap,
  quickQueryRunning,
  quickQueryOutput,
  quickQueryLabel,
  quickQueryStructured,
  quickQueryView,
  quickQueryMaximized,
  quickQueryCommands,
  quickQueryTable,
  onNavigate,
  onAutomationSearchChange,
  onScenarioSearchChange,
  onToggleBatchMode,
  onToggleBatchDevice,
  onSelectDevice,
  onOpenCustomCommandModal,
  onOpenScenario,
  onClearScenario,
  onQuickPlaybookVarChange,
  onQuickPlaybookConcurrencyChange,
  onQuickRiskConfirmedChange,
  onRunValidation,
  onRunApply,
  onRunQuickQuery,
  onResetQuickQuery,
  onQuickQueryViewChange,
  onQuickQueryMaximizedChange,
  onOpenCommandPreview,
  onExportQuickQueryTable,
  copyTextWithFallback,
  showToast,
  onResetExecutionState,
  getPlatformLabel,
}) => {
  const isZh = language === 'zh';
  const targetCount = batchMode ? batchDeviceIds.length : (selectedDevice ? 1 : 0);
  const missingTarget = !hasQuickTargets;
  const riskNeedsConfirm = quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed;
  const hasMissingRequired = quickMissingRequiredFields.length > 0;
  const previewLineCount = (['pre_check', 'execute', 'post_check', 'rollback'] as const)
    .reduce((acc, phase) => acc + (quickPlaybookPreview?.[phase]?.length || 0), 0);

  const classifyVarGroup = (variable: ScenarioVariable) => {
    const text = `${variable?.key || ''} ${variable?.label || ''}`.toLowerCase();
    if (/ip|prefix|mask|gateway|network|neighbor|next_hop|peer/.test(text)) return 'address';
    if (/interface|port|intf|vlan/.test(text)) return 'interface';
    if (/asn|as\b|route|bgp|ospf|policy|metric|community/.test(text)) return 'routing';
    return 'general';
  };

  const varGroupOrder = ['address', 'interface', 'routing', 'general'];

  const varGroupLabel = (group: string) => {
    if (group === 'address') return isZh ? '地址与邻居' : 'Address and Neighbors';
    if (group === 'interface') return isZh ? '接口与二层' : 'Interfaces and L2';
    if (group === 'routing') return isZh ? '路由与策略' : 'Routing and Policy';
    return isZh ? '通用参数' : 'General Parameters';
  };

  const groupedVariables = (quickPlaybookScenario?.variables || []).reduce((acc: Record<string, ScenarioVariable[]>, variable) => {
    const group = classifyVarGroup(variable);
    if (!acc[group]) acc[group] = [];
    acc[group].push(variable);
    return acc;
  }, {});

  const blockingIssueItems: Array<{ message: string; severity: 'critical' | 'high' | 'medium'; score: number }> = [];
  if (missingTarget) {
    blockingIssueItems.push({
      message: isZh ? '请先选择目标设备' : 'Select target device(s) first',
      severity: 'critical',
      score: 100,
    });
  }
  if (quickHasMixedPlatforms) {
    blockingIssueItems.push({
      message: isZh ? '检测到多平台设备，请按平台分批执行' : 'Mixed platforms detected, split execution by platform',
      severity: 'critical',
      score: 90,
    });
  }
  if (quickPlatformMismatch) {
    blockingIssueItems.push({
      message: isZh ? '该场景不支持当前设备平台' : 'Scenario does not support current device platform',
      severity: 'high',
      score: 80,
    });
  }
  if (hasMissingRequired) {
    blockingIssueItems.push({
      message: isZh ? `缺少必填字段：${quickMissingRequiredFields.join('、')}` : `Missing required fields: ${quickMissingRequiredFields.join(', ')}`,
      severity: 'high',
      score: 70,
    });
  }
  if (riskNeedsConfirm) {
    blockingIssueItems.push({
      message: isZh ? '请先确认高风险执行' : 'Confirm high-risk execution first',
      severity: 'medium',
      score: 60,
    });
  }

  const blockingIssues = [...blockingIssueItems].sort((a, b) => b.score - a.score);
  const executeDisabledReason = blockingIssues[0]?.message || '';
  const advisoryNotes: string[] = [];
  if (quickPlaybookDryRun) {
    advisoryNotes.push(isZh ? '当前为 Validation 模式，仅校验不下发。' : 'Validation mode is enabled: this run will not push config changes.');
  }
  if (targetCount > 1 && quickPlaybookConcurrency > 1) {
    advisoryNotes.push(isZh ? `当前并发为 ${quickPlaybookConcurrency}，建议先小批量验证。` : `Concurrency is set to ${quickPlaybookConcurrency}; validate with a smaller batch first.`);
  }

  const quickQueryDisabled = !quickPlaybookScenario && !(selectedDevice || (batchMode && batchDeviceIds.length === 1));
  const selectedBatchDevice = batchMode && batchDeviceIds.length === 1
    ? devices.find((device) => device.id === batchDeviceIds[0]) || null
    : null;

  return (
    <div className="h-full min-h-0 flex flex-col gap-4 relative">
      <div className={sectionHeaderRowClass}>
        <div>
          <h2 className="text-2xl font-medium tracking-tight">{t('directExecution')}</h2>
          <p className="text-sm text-black/40">{isZh ? '选择场景，配置参数，批量下发到设备' : 'Select scenario, configure parameters, deploy to devices'}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onNavigate('/automation/history')}
            className="px-3 py-2 text-xs font-semibold border border-black/10 rounded-lg hover:bg-black/5 transition-all"
          >
            {isZh ? '查看实时历史' : 'View Live History'}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        <div className="w-[220px] flex-shrink-0 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="px-3 py-3 border-b border-black/5 bg-black/[0.01] space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-[#06b6d4] text-white text-[9px] font-bold">1</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-black/50">
                  {isZh ? '目标设备' : 'Target'}
                </span>
              </div>
              <button
                onClick={onToggleBatchMode}
                className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[9px] font-bold uppercase tracking-wider transition-all ${batchMode ? 'bg-amber-100 text-amber-700 border border-amber-200' : 'bg-black/5 text-black/40 hover:bg-black/10'}`}
              >
                <Database size={9} /> {isZh ? '批量' : 'Batch'}
              </button>
            </div>
            {targetCount > 0 && (
              <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-emerald-50 border border-emerald-100">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                <span className="text-[10px] font-semibold text-emerald-700">
                  {batchMode
                    ? (isZh ? `已选 ${targetCount} 台` : `${targetCount} selected`)
                    : (selectedDevice?.hostname || '')}
                </span>
              </div>
            )}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/25" size={12} />
              <input
                type="text"
                placeholder={isZh ? '搜索设备...' : 'Search devices...'}
                value={automationSearch}
                onChange={(event) => onAutomationSearchChange(event.target.value)}
                className="w-full pl-7 pr-2 py-1.5 bg-white border border-black/8 rounded-lg text-[11px] focus:border-black/20 outline-none"
              />
            </div>
          </div>

          <div className="flex-1 min-h-0 overflow-auto p-2 space-y-0.5">
            {(() => {
              const filtered = devices.filter((device) => device.hostname.toLowerCase().includes(automationSearch.toLowerCase()) || device.ip_address.includes(automationSearch));
              const onlineDevices = filtered.filter((device) => device.status === 'online');
              const offlineDevices = filtered.filter((device) => device.status !== 'online');
              const renderDevice = (device: Device) => {
                const checked = batchDeviceIds.includes(device.id);
                const isSelected = batchMode ? checked : selectedDevice?.id === device.id;
                return (
                  <button
                    key={device.id}
                    onClick={() => {
                      if (batchMode) {
                        onToggleBatchDevice(device.id);
                        return;
                      }
                      if (selectedDevice?.id !== device.id) {
                        onResetQuickQuery();
                      }
                      onSelectDevice(device);
                    }}
                    className={`w-full px-2.5 py-2 rounded-xl text-left border transition-all ${isSelected
                      ? (batchMode ? 'bg-amber-50 border-amber-200' : 'bg-[#06b6d4] text-white border-[#06b6d4]')
                      : 'border-transparent hover:border-black/8 hover:bg-black/[0.02]'}`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <p className={`text-[11px] font-semibold truncate ${isSelected && !batchMode ? 'text-white' : 'text-black/80'}`}>
                        {device.hostname}
                      </p>
                      <span className={`w-1.5 h-1.5 flex-shrink-0 rounded-full ${device.status === 'online' ? 'bg-emerald-500' : 'bg-red-400'}`} />
                    </div>
                    <p className={`text-[10px] font-mono mt-0.5 ${isSelected && !batchMode ? 'text-white/50' : 'text-black/35'}`}>
                      {device.ip_address}
                    </p>
                  </button>
                );
              };

              return (
                <>
                  {onlineDevices.length > 0 && (
                    <>
                      <div className="flex items-center gap-1.5 px-2 pt-1 pb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                        <span className="text-[9px] font-bold uppercase tracking-widest text-emerald-600/70">{isZh ? '在线' : 'Online'}</span>
                        <span className="text-[9px] font-mono text-black/30">{onlineDevices.length}</span>
                      </div>
                      {onlineDevices.map(renderDevice)}
                    </>
                  )}
                  {offlineDevices.length > 0 && (
                    <>
                      {onlineDevices.length > 0 && <div className="border-t border-black/5 my-1.5" />}
                      <div className="flex items-center gap-1.5 px-2 pt-1 pb-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" />
                        <span className="text-[9px] font-bold uppercase tracking-widest text-red-500/70">{isZh ? '离线' : 'Offline'}</span>
                        <span className="text-[9px] font-mono text-black/30">{offlineDevices.length}</span>
                      </div>
                      {offlineDevices.map(renderDevice)}
                    </>
                  )}
                  {filtered.length === 0 && (
                    <div className="text-center py-6 text-[10px] text-black/25">{isZh ? '无匹配设备' : 'No devices found'}</div>
                  )}
                </>
              );
            })()}
          </div>

          <div className="flex-shrink-0 p-2 border-t border-black/5">
            <button
              type="button"
              onClick={onOpenCustomCommandModal}
              className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-[#00bceb] text-white text-[11px] font-bold hover:bg-[#0096bd] transition-all"
              title={isZh ? '快速新建自定义命令' : 'Quick create custom command'}
            >
              <Plus size={13} />
              <span className="truncate">
                {batchMode
                  ? (batchDeviceIds.length > 0
                    ? (isZh ? `新建命令 (${batchDeviceIds.length}台)` : `New Cmd (${batchDeviceIds.length})`)
                    : (isZh ? '新建命令' : 'New Cmd'))
                  : (selectedDevice?.hostname
                    ? (isZh ? `命令 → ${selectedDevice.hostname}` : `Cmd → ${selectedDevice.hostname}`)
                    : (isZh ? '新建命令' : 'New Cmd'))}
              </span>
            </button>
          </div>
        </div>

        <div className="flex-1 min-w-0 flex flex-col gap-3 overflow-hidden">
          <div className="flex-shrink-0 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
            {quickPlaybookScenario ? (
              <div className="px-4 py-2.5 flex items-center gap-3">
                <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-[#06b6d4] text-white text-[9px] font-bold flex-shrink-0">2</span>
                <span className="text-base leading-none flex-shrink-0">{quickPlaybookScenario.icon}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold truncate">{isZh ? quickPlaybookScenario.name_zh : quickPlaybookScenario.name}</p>
                </div>
                <span className={`flex-shrink-0 inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded-full border ${
                  quickPlaybookScenario.risk === 'high' ? 'text-red-600 bg-red-50 border-red-200'
                  : quickPlaybookScenario.risk === 'medium' ? 'text-amber-600 bg-amber-50 border-amber-200'
                  : 'text-emerald-600 bg-emerald-50 border-emerald-200'
                }`}>
                  <span className={`w-1 h-1 rounded-full ${
                    quickPlaybookScenario.risk === 'high' ? 'bg-red-500' : quickPlaybookScenario.risk === 'medium' ? 'bg-amber-400' : 'bg-emerald-500'
                  }`} />
                  {quickPlaybookScenario.risk === 'high' ? (isZh ? '高危' : 'HIGH') : quickPlaybookScenario.risk === 'medium' ? (isZh ? '中等' : 'MED') : (isZh ? '低风' : 'LOW')}
                </span>
                <button
                  onClick={onClearScenario}
                  className="flex-shrink-0 text-[10px] text-black/40 hover:text-black/70 border border-black/10 rounded-lg px-2 py-1 hover:bg-black/5 transition-all"
                >
                  {isZh ? '重选' : 'Change'}
                </button>
              </div>
            ) : (
              <>
                <div className="px-4 py-3 border-b border-black/5 bg-black/[0.01] flex items-center justify-between gap-3">
                  <div className="flex items-center gap-1.5">
                    <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-[#06b6d4] text-white text-[9px] font-bold">2</span>
                    <span className="text-[10px] font-bold uppercase tracking-widest text-black/50">
                      {isZh ? '选择场景' : 'Scenario'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="relative flex-1 min-w-0">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/25" size={12} />
                      <input
                        type="text"
                        value={scenarioSearch}
                        onChange={(event) => onScenarioSearchChange(event.target.value)}
                        placeholder={isZh ? '搜索场景...' : 'Search...'}
                        className="w-full pl-7 pr-2 py-1.5 border border-black/8 rounded-lg text-[11px] outline-none focus:border-[#00bceb]/40"
                      />
                    </div>
                    <button
                      onClick={() => onNavigate('/automation/scenarios')}
                      className="flex-shrink-0 text-[11px] font-semibold text-[#008bb0] hover:underline"
                    >
                      {isZh ? '场景库 →' : 'Library →'}
                    </button>
                  </div>
                </div>
                <div className="p-3 grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2 max-h-[260px] overflow-auto content-start">
                  {filteredScenarios.slice(0, 16).map((scenario) => {
                    const riskColor = scenario.risk === 'high'
                      ? 'text-red-600 bg-red-50 border-red-200'
                      : scenario.risk === 'medium'
                        ? 'text-amber-600 bg-amber-50 border-amber-200'
                        : 'text-emerald-600 bg-emerald-50 border-emerald-200';
                    const riskDot = scenario.risk === 'high' ? 'bg-red-500' : scenario.risk === 'medium' ? 'bg-amber-400' : 'bg-emerald-500';
                    const riskStripe = scenario.risk === 'high' ? 'border-l-red-400' : scenario.risk === 'medium' ? 'border-l-amber-400' : 'border-l-emerald-400';
                    return (
                      <button
                        key={scenario.id}
                        onClick={() => onOpenScenario(scenario)}
                        className={`group p-2.5 rounded-xl border border-l-[3px] text-left transition-all border-black/8 hover:border-[#00bceb]/30 hover:bg-[#00bceb]/5 ${riskStripe}`}
                      >
                        <div className="flex items-start justify-between gap-1 mb-1.5">
                          <span className="text-base leading-none">{scenario.icon}</span>
                          <span className={`inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${riskColor}`}>
                            <span className={`w-1 h-1 rounded-full ${riskDot}`} />
                            {scenario.risk === 'high' ? (isZh ? '高危' : 'HIGH') : scenario.risk === 'medium' ? (isZh ? '中等' : 'MED') : (isZh ? '低风' : 'LOW')}
                          </span>
                        </div>
                        <p className="text-[11px] font-bold leading-snug line-clamp-1">{isZh ? scenario.name_zh : scenario.name}</p>
                        <p className="text-[10px] text-black/40 mt-0.5 line-clamp-1">{isZh ? scenario.description_zh : scenario.description}</p>
                      </button>
                    );
                  })}
                  {filteredScenarios.length === 0 && (
                    <div className="col-span-4 text-center py-8 text-xs text-black/35">
                      {isZh ? '没有匹配的场景' : 'No matching scenarios'}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          <div className="flex-1 min-h-0 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex flex-col">
            {quickPlaybookScenario ? (
              <>
                <div className="flex-shrink-0 px-4 py-3 border-b border-black/5 bg-black/[0.01] flex items-center gap-3">
                  <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-[#06b6d4] text-white text-[9px] font-bold flex-shrink-0">3</span>
                  <span className="text-base leading-none">{quickPlaybookScenario.icon}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-bold truncate">{isZh ? quickPlaybookScenario.name_zh : quickPlaybookScenario.name}</p>
                    <p className="text-[10px] text-black/40 truncate">{isZh ? quickPlaybookScenario.description_zh : quickPlaybookScenario.description}</p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-[10px] text-black/35 font-mono">{getPlatformLabel(quickPlaybookPlatform)}</span>
                    <select
                      value={quickPlaybookConcurrency}
                      onChange={(event) => onQuickPlaybookConcurrencyChange(Number(event.target.value))}
                      className="px-2 py-1 border border-black/10 rounded-lg text-[11px] bg-white outline-none"
                      title={isZh ? '并发数' : 'Concurrency'}
                    >
                      {[1, 2, 3, 5, 10].map((count) => <option key={count} value={count}>×{count}</option>)}
                    </select>
                  </div>
                </div>

                <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4">
                  {(quickPlaybookScenario.variables || []).length > 0 ? (
                    varGroupOrder
                      .filter((group) => (groupedVariables[group] || []).length > 0)
                      .map((group) => (
                        <div key={group}>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-black/35 mb-2">{varGroupLabel(group)}</p>
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                            {(groupedVariables[group] || []).map((variable) => (
                              <div key={variable.key} className="rounded-xl border border-black/8 p-3 bg-black/[0.01]">
                                <div className="flex items-center justify-between gap-2 mb-1.5">
                                  <label className="text-[11px] font-semibold text-black/75 truncate">{isZh ? (variable.label_zh || variable.label || variable.key) : (variable.label || variable.key)}</label>
                                  <span className={`flex-shrink-0 text-[9px] px-1.5 py-0.5 rounded-full font-bold ${variable.required ? 'bg-red-100 text-red-600' : 'bg-black/8 text-black/40'}`}>
                                    {variable.required ? (isZh ? '必填' : 'REQ') : (isZh ? '选填' : 'OPT')}
                                  </span>
                                </div>
                                <input
                                  type={variable.type === 'number' ? 'number' : 'text'}
                                  value={quickPlaybookVars[variable.key] || ''}
                                  onChange={(event) => onQuickPlaybookVarChange(variable.key, event.target.value)}
                                  placeholder={variable.platform_hints?.[quickPlaybookPlatform] || variable.placeholder || variable.key}
                                  className={`w-full px-2.5 py-1.5 border rounded-lg text-xs outline-none bg-white transition-colors ${quickMissingRequiredFields.includes(variable.key) ? 'border-red-300 focus:border-red-400' : 'border-black/10 focus:border-[#00bceb]/40'}`}
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      ))
                  ) : (
                    <div className="flex items-center gap-2 rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-xs text-emerald-700">
                      <span>✓</span>
                      <span>{isZh ? '该场景无需填写变量，可直接执行。' : 'No variables required. Ready to run.'}</span>
                    </div>
                  )}
                </div>
              </>
            ) : (quickQueryRunning || quickQueryOutput) ? (
              <>
                {quickQueryMaximized && (
                  <div className="fixed inset-0 z-[70] bg-[#020817]/72 backdrop-blur-sm" />
                )}
                <div className={quickQueryMaximized
                  ? 'fixed left-1/2 top-1/2 z-[80] flex h-[84vh] w-[min(1280px,90vw)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl border border-white/10 bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)] shadow-[0_32px_120px_rgba(0,0,0,0.6)]'
                  : 'flex flex-1 flex-col overflow-hidden rounded-b-2xl bg-[linear-gradient(180deg,#0d1117_0%,#151b23_100%)]'}>
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
                      <span className="shrink-0 text-[10px] px-2 py-0.5 rounded-md bg-white/[0.06] text-white/35 font-mono border border-white/[0.04]">{selectedDevice?.hostname || selectedBatchDevice?.hostname || ''}</span>
                      {!quickQueryRunning && quickQueryStructured && (
                        <div className="ml-2 flex items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.04] p-1">
                          <button
                            onClick={() => onQuickQueryViewChange('terminal')}
                            className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase transition-all ${quickQueryView === 'terminal' ? 'bg-white/14 text-white' : 'text-white/45 hover:text-white/75'}`}
                            title={isZh ? '终端回显' : 'Terminal Output'}
                          >
                            {isZh ? '终端' : 'Terminal'}
                          </button>
                          <button
                            onClick={() => onQuickQueryViewChange('table')}
                            className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase transition-all ${quickQueryView === 'table' ? 'bg-white/14 text-white' : 'text-white/45 hover:text-white/75'}`}
                            title={isZh ? '结构化表格' : 'Structured Table'}
                          >
                            {isZh ? '表格' : 'Table'}
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-0.5 shrink-0">
                      {!quickQueryRunning && quickQueryOutput && (
                        <button
                          onClick={() => onQuickQueryMaximizedChange(!quickQueryMaximized)}
                          className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all"
                          title={quickQueryMaximized ? (isZh ? '还原' : 'Restore') : (isZh ? '放大' : 'Maximize')}
                        >
                          {quickQueryMaximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                        </button>
                      )}
                      {!quickQueryRunning && quickQueryStructured && quickQueryTable.records.length > 0 && (
                        <button
                          onClick={() => onExportQuickQueryTable(quickQueryCommands)}
                          className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all"
                          title={isZh ? '导出 Excel' : 'Export Excel'}
                        >
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
                          title={isZh ? '复制' : 'Copy'}
                        >
                          <Copy size={13} />
                        </button>
                      )}
                      <button
                        onClick={onResetQuickQuery}
                        className="text-white/25 hover:text-white/60 p-2 rounded-lg hover:bg-white/[0.06] transition-all"
                        title={isZh ? '关闭' : 'Close'}
                      >
                        <X size={13} />
                      </button>
                    </div>
                  </div>

                  {!quickQueryRunning && quickQueryCommands.length > 0 && (
                    <div className="shrink-0 border-b border-white/[0.05] bg-[linear-gradient(180deg,rgba(16,23,34,0.92)_0%,rgba(9,14,22,0.82)_100%)] px-4 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="inline-flex items-center rounded-full border border-cyan-400/18 bg-cyan-400/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-100/90">
                              {isZh ? '实际执行命令' : 'Executed Commands'}
                            </span>
                            <span className="text-[10px] text-white/38">
                              {isZh ? `${quickQueryCommands.length} 条` : `${quickQueryCommands.length} command${quickQueryCommands.length > 1 ? 's' : ''}`}
                            </span>
                          </div>
                          <div className="mt-2 flex flex-col gap-1.5">
                            {quickQueryCommands.map((command, index) => (
                              <div
                                key={`${command}-${index}`}
                                className="overflow-hidden rounded-xl border border-cyan-400/14 bg-[linear-gradient(180deg,rgba(3,11,21,0.96)_0%,rgba(7,18,32,0.92)_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                              >
                                <div className="flex items-stretch">
                                  <span className="w-1 shrink-0 bg-[linear-gradient(180deg,rgba(34,211,238,0.95)_0%,rgba(6,182,212,0.45)_100%)]" />
                                  <div className="min-w-0 flex-1 px-3 py-2">
                                    <div className="mb-1 flex items-center gap-2 text-[9px] font-bold uppercase tracking-[0.16em] text-cyan-200/55">
                                      <span>{isZh ? '命令' : 'Command'}</span>
                                      <span className="text-white/18">#{index + 1}</span>
                                    </div>
                                    <code className="block overflow-x-auto text-[11px] font-medium leading-relaxed text-[#F7FBFF]">
                                      {command}
                                    </code>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                        <button
                          onClick={async () => {
                            const ok = await copyTextWithFallback(quickQueryCommands.join('\n'));
                            showToast(ok ? (isZh ? '命令已复制' : 'Commands copied') : (isZh ? '复制失败' : 'Copy failed'), ok ? 'success' : 'error');
                          }}
                          className="shrink-0 rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-white/60 transition-all hover:bg-white/[0.08] hover:text-white"
                          title={isZh ? '复制命令' : 'Copy commands'}
                        >
                          {isZh ? '复制命令' : 'Copy'}
                        </button>
                      </div>
                    </div>
                  )}

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
                            <p className="mt-1 text-[10px] text-white/35">
                              {quickQueryTable.category?.parser || 'ntc-templates'} · {isZh ? '记录数' : 'Records'} {Number(quickQueryTable.category?.count || 0)}
                            </p>
                          </div>
                          {quickQueryTable.category?.parse_errors?.length > 0 && (
                            <span className="rounded-full bg-amber-500/12 px-2 py-1 text-[10px] font-bold uppercase text-amber-300">
                              {isZh ? '部分回退' : 'Partial Fallback'}
                            </span>
                          )}
                        </div>

                        {quickQueryTable.records.length > 0 ? (
                          <div className={quickQueryMaximized
                            ? 'overflow-auto rounded-xl border border-white/[0.06] bg-black/20 max-h-[calc(84vh-12rem)]'
                            : 'overflow-auto rounded-xl border border-white/[0.06] bg-black/20 min-h-[24rem] max-h-[58vh]'}>
                            <table className="min-w-full text-left text-[12px] text-[#d8e2eb]">
                              <thead className="sticky top-0 bg-[#101722]">
                                <tr className="border-b border-white/[0.06]">
                                  {quickQueryTable.columns.map((column) => (
                                    <th key={column} className="px-3 py-2 text-[10px] font-bold uppercase tracking-[0.14em] text-white/45 whitespace-nowrap">
                                      {column}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {quickQueryTable.records.map((record, index) => (
                                  <tr key={`quick-row-${index}`} className="border-b border-white/[0.04] last:border-b-0 hover:bg-white/[0.03]">
                                    {quickQueryTable.columns.map((column) => {
                                      const value = record?.[column];
                                      return (
                                        <td key={`${index}-${column}`} className="px-3 py-2 align-top text-[11px] text-[#d8e2eb] whitespace-nowrap">
                                          {value == null || value === '' ? <span className="text-white/20">-</span> : String(value)}
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
                            {isZh ? '当前没有结构化记录，可切回终端查看原始回显。' : 'No structured records are available for this query. Switch back to Terminal for raw output.'}
                          </div>
                        )}

                        {quickQueryTable.category?.parse_errors?.length > 0 && (
                          <div className="rounded-xl border border-amber-400/20 bg-amber-400/8 px-4 py-3 text-xs text-amber-200">
                            <p className="font-bold uppercase tracking-[0.14em]">{isZh ? '解析提示' : 'Parsing Notes'}</p>
                            <div className="mt-2 space-y-1">
                              {quickQueryTable.category.parse_errors.map((item: any, index: number) => (
                                <div key={`parse-error-${index}`}>{item.command}: {item.error}</div>
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
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-center gap-3 p-6">
                <Zap size={20} strokeWidth={1.5} className="text-black/15" />
                <p className="text-sm text-black/35">{isZh ? '从上方选择一个场景' : 'Select a scenario above'}</p>
                <div className="flex items-center gap-3 mt-1">
                  {[
                    { risk: 'low', dot: 'bg-emerald-400', label: isZh ? '低风险' : 'Low' },
                    { risk: 'medium', dot: 'bg-amber-400', label: isZh ? '中等' : 'Med' },
                    { risk: 'high', dot: 'bg-rose-400', label: isZh ? '高危' : 'High' },
                  ].map((riskMeta) => {
                    const count = filteredScenarios.filter((scenario) => scenario.risk === riskMeta.risk).length;
                    return (
                      <span key={riskMeta.risk} className="flex items-center gap-1.5 text-[11px] text-black/40">
                        <span className={`h-2 w-2 rounded-full ${riskMeta.dot}`} />
                        <span className="font-bold tabular-nums text-black/55">{count}</span>
                        {riskMeta.label}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="w-[300px] flex-shrink-0 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-black/5">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-[#06b6d4] text-white text-[9px] font-bold flex-shrink-0">✓</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-black/50">
                  {isZh ? '执行决策' : 'Execution Decision'}
                </span>
              </div>
              <button
                onClick={onOpenCustomCommandModal}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/8 text-[#007d9d] text-[10px] font-bold hover:bg-[#00bceb]/14 transition-all"
                title={isZh ? '在当前设备上下文直接编写命令' : 'Open command composer in current device context'}
              >
                <FileText size={11} />
                {targetCount > 0 ? (isZh ? '对当前目标下命令' : 'Command Target') : (isZh ? '自定义命令' : 'Custom')}
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2">
              {quickPlaybookScenario ? (
                <span className={`inline-flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1 rounded-full border ${
                  quickPlaybookScenario.risk === 'high'
                    ? 'bg-red-50 border-red-200 text-red-700'
                    : quickPlaybookScenario.risk === 'medium'
                      ? 'bg-amber-50 border-amber-200 text-amber-700'
                      : 'bg-emerald-50 border-emerald-200 text-emerald-700'
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    quickPlaybookScenario.risk === 'high' ? 'bg-red-500' : quickPlaybookScenario.risk === 'medium' ? 'bg-amber-400' : 'bg-emerald-500'
                  }`} />
                  {quickPlaybookScenario.risk === 'high'
                    ? (isZh ? '高危场景' : 'HIGH RISK')
                    : quickPlaybookScenario.risk === 'medium'
                      ? (isZh ? '中等风险' : 'MED RISK')
                      : (isZh ? '低风险' : 'LOW RISK')}
                </span>
              ) : (
                <span className="text-[10px] text-black/30">{isZh ? '未选场景' : 'No scenario'}</span>
              )}
            </div>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full ${targetCount > 0 ? 'bg-[#06b6d4] text-white' : 'bg-black/8 text-black/40'}`}>
                {targetCount > 0
                  ? (batchMode ? `${targetCount} ${isZh ? '台' : 'devices'}` : (selectedDevice?.hostname || ''))
                  : (isZh ? '未选设备' : 'No device')}
              </span>
              {quickPlaybookDryRun && (
                <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-bold">
                  DRY-RUN
                </span>
              )}
              {quickPlaybookConcurrency > 1 && (
                <span className="text-[10px] text-black/40">×{quickPlaybookConcurrency} concurrency</span>
              )}
            </div>
          </div>

          {(isQuickPlaybookRunning || quickExecutionResult) ? (
            (() => {
              const completeMsg = wsCompleteMsg;
              const deviceEntries = Object.entries(deviceStatusMap) as Array<[string, DeviceExecutionState]>;
              const scenarioTitle = quickExecutionResult
                ? (isZh ? (quickExecutionResult.scenarioNameZh || quickExecutionResult.scenarioName) : quickExecutionResult.scenarioName)
                : (quickPlaybookScenario ? (isZh ? (quickPlaybookScenario.name_zh || quickPlaybookScenario.name) : quickPlaybookScenario.name) : '');
              return (
                <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                  <div className={`px-4 py-3 border-b flex items-center gap-2 ${completeMsg ? (completeMsg.status === 'success' ? 'bg-emerald-50 border-emerald-100' : completeMsg.status === 'partial_failure' ? 'bg-amber-50 border-amber-100' : 'bg-red-50 border-red-100') : 'bg-blue-50 border-blue-100'}`}>
                    {isQuickPlaybookRunning ? (
                      <RotateCcw size={14} className="text-blue-500 animate-spin shrink-0" />
                    ) : completeMsg?.status === 'success' ? (
                      <CheckCircle2 size={14} className="text-emerald-500 shrink-0" />
                    ) : completeMsg?.status === 'partial_failure' ? (
                      <AlertTriangle size={14} className="text-amber-500 shrink-0" />
                    ) : (
                      <XCircle size={14} className="text-red-500 shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-black/70 truncate">{scenarioTitle}</p>
                      <p className="text-[10px] text-black/40">
                        {isQuickPlaybookRunning
                          ? (isZh ? '正在执行...' : 'Executing...')
                          : completeMsg
                            ? `${isZh ? '完成' : 'Done'} · ${completeMsg.summary?.success ?? 0}✓ ${completeMsg.summary?.failed ?? 0}✗`
                            : (isZh ? '已提交' : 'Submitted')}
                      </p>
                    </div>
                    {quickExecutionResult?.dryRun && (
                      <span className="ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 shrink-0">DRY</span>
                    )}
                  </div>

                  <div className="flex-1 min-h-0 overflow-auto p-3 space-y-2">
                    {deviceEntries.length === 0 && isQuickPlaybookRunning && (
                      <div className="flex flex-col items-center justify-center h-24 gap-2">
                        <RotateCcw size={20} className="text-blue-400 animate-spin" />
                        <p className="text-xs text-black/30">{isZh ? '等待设备响应...' : 'Waiting for device response...'}</p>
                      </div>
                    )}
                    {deviceEntries.map(([deviceId, deviceState]) => (
                      <div key={deviceId} className={`rounded-xl border p-3 space-y-1.5 ${deviceState.status === 'running' ? 'border-blue-100 bg-blue-50/40' : deviceState.status === 'success' ? 'border-emerald-100 bg-emerald-50/40' : deviceState.status === 'partial_failure' ? 'border-amber-100 bg-amber-50/40' : 'border-red-100 bg-red-50/40'}`}>
                        <div className="flex items-center gap-2">
                          {deviceState.status === 'running' ? (
                            <RotateCcw size={11} className="text-blue-500 animate-spin shrink-0" />
                          ) : deviceState.status === 'success' ? (
                            <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
                          ) : deviceState.status === 'partial_failure' ? (
                            <AlertTriangle size={11} className="text-amber-500 shrink-0" />
                          ) : (
                            <XCircle size={11} className="text-red-500 shrink-0" />
                          )}
                          <span className="text-xs font-semibold text-black/70 truncate">{deviceState.hostname}</span>
                        </div>
                        {Object.keys(deviceState.phases).length > 0 && (
                          <div className="flex flex-wrap gap-1 pl-4">
                            {(Object.entries(deviceState.phases) as Array<[string, DeviceExecutionPhase]>).map(([phase, phaseState]) => (
                              <span key={phase} className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${phaseState.success ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                                {phaseState.success ? '✓' : '✗'} {phase}
                              </span>
                            ))}
                          </div>
                        )}
                        {deviceState.error && (
                          <p className="text-[10px] text-red-600 pl-4 font-mono truncate">{deviceState.error}</p>
                        )}
                      </div>
                    ))}
                  </div>

                  {!isQuickPlaybookRunning && (
                    <div className="p-3 pt-2 space-y-1.5 border-t border-black/5">
                      <button
                        onClick={() => onNavigate('/automation/history')}
                        className="w-full px-3 py-2 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#0096bd] transition-all flex items-center justify-center gap-2"
                      >
                        <ExternalLink size={11} />
                        {isZh ? '查看完整历史' : 'View Full History'}
                      </button>
                      <button
                        onClick={onResetExecutionState}
                        className="w-full px-3 py-2 rounded-lg border border-black/10 text-xs font-semibold text-black/50 hover:bg-black/5 transition-all"
                      >
                        {isZh ? '新建任务' : 'New Task'}
                      </button>
                    </div>
                  )}
                </div>
              );
            })()
          ) : !quickPlaybookScenario ? (
            <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
              {(() => {
                const platform = (selectedDevice?.platform || selectedBatchDevice?.platform || '').toLowerCase();
                const isCisco = platform.includes('cisco') || platform.includes('arista') || platform.includes('rgos');
                const isHuawei = platform.includes('huawei') || platform.includes('h3c') || platform.includes('ce_');
                const isJuniper = platform.includes('juniper') || platform.includes('junos');
                const presets: Array<{ icon: string; label: string; labelEn: string; cmds: string; group: string; operationalCategory?: string }> = [
                  { icon: '📡', label: '接口状态', labelEn: 'Interfaces', group: 'net', operationalCategory: 'interfaces', cmds: isCisco ? 'show ip interface brief' : isHuawei ? 'display interface brief' : isJuniper ? 'show interfaces terse' : 'show ip interface brief' },
                  { icon: '📋', label: 'ARP表', labelEn: 'ARP Table', group: 'net', operationalCategory: 'arp', cmds: isCisco ? 'show arp' : isHuawei ? 'display arp' : isJuniper ? 'show arp' : 'show arp' },
                  { icon: '🏷️', label: 'MAC表', labelEn: 'MAC Table', group: 'net', operationalCategory: 'mac_table', cmds: isCisco ? 'show mac address-table' : isHuawei ? 'display mac-address' : isJuniper ? 'show ethernet-switching table' : 'show mac address-table' },
                  { icon: '📊', label: 'VLAN', labelEn: 'VLAN', group: 'net', cmds: isCisco ? 'show vlan brief' : isHuawei ? 'display vlan' : isJuniper ? 'show vlans' : 'show vlan brief' },
                  { icon: '📌', label: 'LLDP邻居', labelEn: 'LLDP', group: 'net', operationalCategory: 'neighbors', cmds: isCisco ? 'show lldp neighbors' : isHuawei ? 'display lldp neighbor brief' : isJuniper ? 'show lldp neighbors' : 'show lldp neighbors' },
                  { icon: '🗺️', label: '路由表', labelEn: 'Routes', group: 'route', operationalCategory: 'routing_table', cmds: isCisco ? 'show ip route' : isHuawei ? 'display ip routing-table' : isJuniper ? 'show route' : 'show ip route' },
                  { icon: '🔗', label: 'BGP邻居', labelEn: 'BGP Peers', group: 'route', operationalCategory: 'bgp', cmds: isCisco ? 'show bgp summary' : isHuawei ? 'display bgp peer' : isJuniper ? 'show bgp summary' : 'show bgp summary' },
                  { icon: '🔍', label: 'OSPF邻居', labelEn: 'OSPF Nbrs', group: 'route', operationalCategory: 'ospf', cmds: isCisco ? 'show ip ospf neighbor' : isHuawei ? 'display ospf peer brief' : isJuniper ? 'show ospf neighbor' : 'show ip ospf neighbor' },
                  { icon: '🏥', label: '设备信息', labelEn: 'Version', group: 'sys', cmds: isCisco ? 'show version' : isHuawei ? 'display version' : isJuniper ? 'show version' : 'show version' },
                  { icon: '📝', label: '日志', labelEn: 'Logs', group: 'sys', cmds: isCisco ? 'show logging | tail 30' : isHuawei ? 'display logbuffer last 30' : isJuniper ? 'show log messages | last 30' : 'show logging | tail 30' },
                  { icon: '⏱️', label: '运行时间', labelEn: 'Uptime', group: 'sys', cmds: isCisco ? 'show uptime' : isHuawei ? 'display clock\ndisplay version | include uptime' : isJuniper ? 'show system uptime' : 'show uptime' },
                  { icon: '💾', label: '运行配置', labelEn: 'Running Config', group: 'sys', cmds: isCisco ? 'show running-config' : isHuawei ? 'display current-configuration' : isJuniper ? 'show configuration' : 'show running-config' },
                ];
                const userSavedCmds: Array<{ icon: string; label: string; labelEn: string; cmds: string; operationalCategory?: string }> = (() => {
                  try { return JSON.parse(localStorage.getItem('quickQuerySaved') || '[]'); } catch { return []; }
                })();
                const allCommands = [...presets, ...userSavedCmds.map((command) => ({ ...command, group: 'custom' }))];
                const hasDevice = !!(selectedDevice || selectedBatchDevice);
                const deviceName = selectedDevice?.hostname || selectedBatchDevice?.hostname || '';
                const categoryGroups = [
                  { key: 'net', label: isZh ? '🌐 网络基础' : '🌐 Network', accentClass: 'query-accent-net' },
                  { key: 'route', label: isZh ? '🔀 路由协议' : '🔀 Routing', accentClass: 'query-accent-route' },
                  { key: 'sys', label: isZh ? '🖥️ 系统运维' : '🖥️ System', accentClass: 'query-accent-sys' },
                  ...(userSavedCmds.length > 0 ? [{ key: 'custom', label: isZh ? '⭐ 自定义' : '⭐ Custom', accentClass: 'query-accent-custom' }] : []),
                ];

                return (
                  <div className="flex-1 overflow-auto p-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <div className="w-1 h-4 rounded-full bg-[#00bceb]" />
                        <span className="text-xs font-bold text-black/70">{isZh ? '快捷查询' : 'Quick Query'}</span>
                      </div>
                      {hasDevice && (
                        <span className="text-[10px] px-2.5 py-1 rounded-lg bg-gradient-to-r from-[#00bceb]/10 to-[#00bceb]/5 text-[#0087a9] font-mono font-bold border border-[#00bceb]/10">
                          {deviceName}
                        </span>
                      )}
                    </div>

                    {!hasDevice ? (
                      <div className="rounded-2xl border-2 border-dashed border-black/8 p-8 text-center">
                        <Server size={28} strokeWidth={1.2} className="mx-auto mb-3 text-black/10" />
                        <p className="text-sm text-black/30 font-medium">{isZh ? '← 先在左侧选择一台设备' : '← Select a device first'}</p>
                      </div>
                    ) : (
                      <>
                        {categoryGroups.map((group) => {
                          const items = allCommands.filter((command) => command.group === group.key);
                          if (items.length === 0) return null;
                          return (
                            <div key={group.key}>
                              <div className="flex items-center gap-2 mb-2">
                                <div className={`h-3 w-0.5 rounded-full ${group.accentClass}`} />
                                <span className={`text-[10px] font-bold tracking-wide ${group.accentClass}`}>{group.label}</span>
                                <div className={`flex-1 h-px ${group.accentClass}-line`} />
                              </div>
                              <div className="grid grid-cols-3 gap-2">
                                {items.map((command, index) => (
                                  <button
                                    key={`${group.key}-${index}`}
                                    disabled={quickQueryRunning}
                                    onClick={() => onRunQuickQuery(isZh ? command.label : command.labelEn, command.cmds, command.operationalCategory)}
                                    title={command.cmds}
                                    className="group relative flex flex-col items-center gap-1.5 px-2 py-3 rounded-xl border border-black/[0.05] bg-white hover:border-[#00bceb]/25 hover:shadow-lg hover:shadow-[#00bceb]/[0.06] hover:-translate-y-0.5 active:translate-y-0 transition-all duration-200 disabled:opacity-40 disabled:hover:translate-y-0"
                                  >
                                    <span className="text-[18px] leading-none group-hover:scale-110 transition-transform duration-200">{command.icon}</span>
                                    <span className="text-[10px] font-semibold text-black/55 group-hover:text-[#0087a9] leading-tight text-center transition-colors">{isZh ? command.label : command.labelEn}</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </>
                    )}

                    <div className="pt-3 border-t border-black/5">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-black/25 mb-2">{isZh ? '场景执行' : 'Scenario Execution'}</p>
                      <div className="space-y-1.5">
                        {[
                          { step: '1', text: isZh ? '在左侧选择目标设备' : 'Select target device on the left', done: targetCount > 0 },
                          { step: '2', text: isZh ? '在中间选择执行场景' : 'Choose a scenario in the center', done: false },
                          { step: '3', text: isZh ? '填写参数后点击执行' : 'Fill variables and execute', done: false },
                        ].map((item) => (
                          <div key={item.step} className={`flex items-center gap-2.5 rounded-lg border px-3 py-2 ${item.done ? 'border-emerald-200 bg-emerald-50' : 'border-[#06b6d4]/10 bg-[#06b6d4]/[0.03]'}`}>
                            <span className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold flex-shrink-0 ${item.done ? 'bg-emerald-500 text-white' : 'bg-[#06b6d4]/15 text-[#06b6d4]/60'}`}>
                              {item.done ? '✓' : item.step}
                            </span>
                            <span className={`text-xs ${item.done ? 'text-emerald-700' : 'text-black/50'}`}>{item.text}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : (
            <>
              <div className="flex-1 min-h-0 overflow-auto p-4 space-y-3">
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-black/40">
                      {isZh ? '阻塞项' : 'Blocking Issues'}
                    </p>
                    {blockingIssues.length > 0 && (
                      <span className="text-[10px] font-bold w-4 h-4 rounded-full bg-red-500 text-white flex items-center justify-center">
                        {blockingIssues.length}
                      </span>
                    )}
                  </div>
                  {blockingIssues.length > 0 ? (
                    <ul className="space-y-1.5">
                      {blockingIssues.map((issue, index) => (
                        <li key={index} className={`flex items-start gap-2 rounded-xl px-3 py-2 border text-xs ${
                          issue.severity === 'critical'
                            ? 'border-red-200 bg-red-50 text-red-700'
                            : issue.severity === 'high'
                              ? 'border-orange-200 bg-orange-50 text-orange-700'
                              : 'border-amber-200 bg-amber-50 text-amber-700'
                        }`}>
                          <span className="flex-shrink-0 mt-0.5 font-black text-[11px]">
                            {issue.severity === 'critical' ? '✕' : issue.severity === 'high' ? '!' : '▲'}
                          </span>
                          <span className="flex-1">{issue.message}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
                      <span className="font-bold">✓</span>
                      <span>{isZh ? '检查通过，可以执行。' : 'All clear. Ready to run.'}</span>
                    </div>
                  )}
                </div>

                {advisoryNotes.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[10px] font-bold uppercase tracking-widest text-black/35">
                      {isZh ? '操作提示' : 'Advisory'}
                    </p>
                    {advisoryNotes.map((note, index) => (
                      <div key={index} className="flex items-start gap-2 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700">
                        <span className="flex-shrink-0 font-bold">ℹ</span>
                        <span>{note}</span>
                      </div>
                    ))}
                  </div>
                )}

                {quickPlaybookScenario?.risk === 'high' && (
                  <label className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={quickRiskConfirmed}
                      onChange={(event) => onQuickRiskConfirmedChange(event.target.checked)}
                      className="mt-0.5 flex-shrink-0"
                    />
                    <span>{isZh ? '我已了解该场景为高风险操作，并确认继续执行。' : 'I understand this is a high-risk operation and want to proceed.'}</span>
                  </label>
                )}

                <div className="rounded-xl border border-black/10 overflow-hidden">
                  <div className="px-3 py-2.5 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <p className="text-[10px] font-bold uppercase tracking-widest text-black/40 flex-shrink-0">
                        {isZh ? '命令预览' : 'Preview'}
                      </p>
                      {previewLineCount > 0 ? (
                        <span className="text-[10px] text-black/40 font-mono truncate">
                          {quickPlaybookPlatform} · {previewLineCount} {isZh ? '行' : 'lines'}
                        </span>
                      ) : (
                        <span className="text-[10px] text-black/25">
                          {quickPlaybookScenario ? (isZh ? '生成中...' : 'Generating...') : (isZh ? '未选场景' : 'No scenario')}
                        </span>
                      )}
                    </div>
                    {quickPlaybookPreview && (
                      <button
                        onClick={onOpenCommandPreview}
                        className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-black/10 text-[10px] font-semibold text-black/55 hover:bg-black/5 transition-all"
                      >
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M1 9L9 1M9 1H4M9 1V6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                        {isZh ? '展开' : 'Expand'}
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex-shrink-0 border-t border-black/5 p-4 bg-white space-y-2">
                <p className="text-[10px] text-black/35 text-center">
                  {isZh ? '推荐：先运行校验确认无误，再应用变更' : 'Recommended: validate first, then apply changes'}
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={onRunValidation}
                    disabled={!quickPlaybookScenario || !hasQuickTargets || isQuickPlaybookRunning || quickHasMixedPlatforms || quickPlatformMismatch || hasMissingRequired || (quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed)}
                    title={executeDisabledReason || (isZh ? '仅校验，不下发配置' : 'Validate only, no config push')}
                    className={`px-3 py-2.5 rounded-xl text-xs font-bold transition-all border ${
                      (!quickPlaybookScenario || !hasQuickTargets || isQuickPlaybookRunning || quickHasMixedPlatforms || quickPlatformMismatch || hasMissingRequired || (quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed))
                        ? 'bg-black/5 text-black/25 border-black/8 cursor-not-allowed'
                        : 'bg-white text-[#0891b2] border-[#06b6d4]/30 hover:bg-[#ecfeff]'
                    }`}
                  >
                    {isQuickPlaybookRunning && quickPlaybookDryRun ? (isZh ? '校验中...' : 'Validating...') : (isZh ? '运行校验' : 'Run Validation')}
                  </button>
                  <button
                    onClick={onRunApply}
                    disabled={!quickPlaybookScenario || !hasQuickTargets || isQuickPlaybookRunning || quickHasMixedPlatforms || quickPlatformMismatch || hasMissingRequired || (quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed)}
                    title={executeDisabledReason || (isZh ? '真实下发配置变更' : 'Push config changes to device')}
                    className={`px-3 py-2.5 rounded-xl text-xs font-bold text-white transition-all ${
                      (!quickPlaybookScenario || !hasQuickTargets || isQuickPlaybookRunning || quickHasMixedPlatforms || quickPlatformMismatch || hasMissingRequired || (quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed))
                        ? 'bg-[#06b6d4]/20 text-black/30 cursor-not-allowed'
                        : 'bg-[#06b6d4] hover:bg-[#0891b2] shadow-lg shadow-[#06b6d4]/20'
                    }`}
                  >
                    {isQuickPlaybookRunning && !quickPlaybookDryRun ? (isZh ? '下发中...' : 'Applying...') : (isZh ? `应用变更 (${targetCount})` : `Apply Changes (${targetCount})`)}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default AutomationExecuteTab;