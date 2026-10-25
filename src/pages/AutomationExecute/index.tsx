import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Play, AlertTriangle } from 'lucide-react';
import type { Device } from '../../types';
import type { AutomationExecuteTabProps, StepId, DeviceExecutionState, DeviceExecutionPhase, AutomationScenario, ScenarioVariable } from './types';
import PageHero from '../../components/PageHero';
import { Zap } from 'lucide-react';
import { DeviceSelectionStep } from './components/DeviceSelectionStep';
import { ScenarioSelectionStep } from './components/ScenarioSelectionStep';
import { ParameterConfigStep } from './components/ParameterConfigStep';
import { ExecutionResultsStep } from './components/ExecutionResultsStep';
import { QuickQueryOverlay } from './components/QuickQueryOverlay';
import { QuickQueryResultOverlay } from './components/QuickQueryResultOverlay';
import { TextFSMDebugger } from './components/TextFSMDebugger';
import { getDeviceCategory, getVendor, classifyVarGroup, isAutomationPlatformSupported, normalizeAutomationPlatform } from './helpers';
import { DEVICE_PAGE_SIZE, VAR_GROUP_ORDER } from './constants';
import { ApiError, apiRequest } from '../../api/http';
import { fetchAllPaginatedItems } from '../../utils/pagination';
import { useFocusTrap } from '../../hooks/useFocusTrap';

interface DeviceSelectionSiteFacet {
  site: string;
  count: number;
  online_count?: number;
}

interface DeviceSelectionSiteRoleFacet {
  site: string;
  role: string;
  count: number;
  online_count?: number;
}

interface DeviceSelectionFacets {
  sites?: DeviceSelectionSiteFacet[];
  site_roles?: DeviceSelectionSiteRoleFacet[];
  vendors?: string[];
}

interface DeviceSelectionPageResponse {
  items: Device[];
  total: number;
  page: number;
  page_size: number;
  status_counts?: Record<string, number>;
  facets?: DeviceSelectionFacets;
}

export const AutomationExecuteTab: React.FC<AutomationExecuteTabProps> = (props) => {
  const {
    t,
    language,
    devices,
    rememberedBatchDevices,
    selectedDevice,
    batchMode,
    batchDeviceIds,
    automationSearch,
    scenarioSearch,
    changeTicket: propChangeTicket,
    setChangeTicket: propSetChangeTicket,
    savedQueries,
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
    onRememberDevice,
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
    handleClearSelection,
  } = props;

  const isZh = language === 'zh';

  /* -- Local state -- */
  const [currentStep, setCurrentStep] = useState<StepId>(1);
  const [vendorFilter, setVendorFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [deviceTypeFilter, setDeviceTypeFilter] = useState<'all' | 'network' | 'server'>('all');
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [deviceViewMode, setDeviceViewMode] = useState<'grid' | 'list'>('list');
  const [devicePage, setDevicePage] = useState(1);
  const [devicePageSize, setDevicePageSize] = useState(DEVICE_PAGE_SIZE);
  const [devicePageItems, setDevicePageItems] = useState<Device[]>([]);
  const [deviceTotal, setDeviceTotal] = useState(0);
  const [deviceStatusCounts, setDeviceStatusCounts] = useState<Record<string, number>>({});
  const [deviceFacets, setDeviceFacets] = useState<DeviceSelectionFacets>({});
  const [devicePageLoading, setDevicePageLoading] = useState(false);
  const [devicePageError, setDevicePageError] = useState('');
  const [debouncedDeviceSearch, setDebouncedDeviceSearch] = useState(automationSearch);
  const [deviceRequestVersion, setDeviceRequestVersion] = useState(0);
  const devicePageAbortRef = useRef<AbortController | null>(null);

  const [localChangeTicket, localSetChangeTicket] = useState('');
  const changeTicket = propChangeTicket !== undefined ? propChangeTicket : localChangeTicket;
  const setChangeTicket = propSetChangeTicket || localSetChangeTicket;

  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<'validate' | 'apply'>('validate');
  const confirmDialogRef = useRef<HTMLDivElement>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const [expandedTreeNodes, setExpandedTreeNodes] = useState<Set<string>>(new Set());
  const [treeFilterSite, setTreeFilterSite] = useState<string | null>(null);
  const [treeFilterRole, setTreeFilterRole] = useState<string | null>(null);
  const [showSelectedDrawer, setShowSelectedDrawer] = useState(false);
  const [quickQuerySearch, setQuickQuerySearch] = useState('');

  const [debuggerOpen, setDebuggerOpen] = useState(false);
  const [debuggerPlatform, setDebuggerPlatform] = useState('cisco_ios');
  const [debuggerCommand, setDebuggerCommand] = useState('');
  const [debuggerSampleOutput, setDebuggerSampleOutput] = useState('');

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
    return () => {
      if (ticketValidateTimer.current) clearTimeout(ticketValidateTimer.current);
    };
  }, [changeTicket]);

  /* -- Derived -- */
  const targetCount = batchMode ? batchDeviceIds.length : selectedDevice ? 1 : 0;
  const riskNeedsConfirm = quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed;
  const hasMissingRequired = quickMissingRequiredFields.length > 0;
  const previewLineCount = (['pre_check', 'execute', 'post_check', 'rollback'] as const).reduce(
    (acc, phase) => acc + (quickPlaybookPreview?.[phase]?.length || 0),
    0
  );

  const canExecute =
    quickPlaybookScenario &&
    hasQuickTargets &&
    !isQuickPlaybookRunning &&
    !quickHasMixedPlatforms &&
    !quickPlatformMismatch &&
    !hasMissingRequired &&
    !(quickPlaybookScenario?.risk === 'high' && !quickRiskConfirmed) &&
    !(changeTicket.trim().length >= 4 && ticketValidation.found === true && !ticketValidation.valid) &&
    !(changeTicket.trim().length >= 4 && ticketValidation.found === false);

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

  const buildDeviceRequestParams = useCallback((page: number, searchTerm = debouncedDeviceSearch) => {
    const params = new URLSearchParams({
      mode: 'light',
      asset_type: 'all',
      include_facets: 'true',
      page: String(page),
      page_size: String(devicePageSize),
    });
    if (searchTerm.trim()) params.set('search', searchTerm.trim());
    if (statusFilter !== 'all') params.set('status', statusFilter === 'offline' ? 'not_online' : statusFilter);
    if (vendorFilter !== 'all') params.set('vendor', vendorFilter);
    if (treeFilterSite) params.set('site', treeFilterSite);
    if (treeFilterRole) {
      params.set('role', treeFilterRole);
      params.set('role_exact', 'true');
    }
    if (deviceTypeFilter !== 'all') params.set('device_category', deviceTypeFilter);
    return params;
  }, [debouncedDeviceSearch, statusFilter, vendorFilter, treeFilterSite, treeFilterRole, deviceTypeFilter, devicePageSize]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedDeviceSearch(automationSearch.trim());
      setDevicePage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [automationSearch]);

  useEffect(() => {
    if (currentStep !== 1) {
      devicePageAbortRef.current?.abort();
      setDevicePageLoading(false);
      return;
    }

    const controller = new AbortController();
    devicePageAbortRef.current?.abort();
    devicePageAbortRef.current = controller;
    setDevicePageLoading(true);
    setDevicePageError('');
    setDevicePageItems([]);
    setDeviceTotal(0);
    setDeviceStatusCounts({});
    setDeviceFacets({});

    apiRequest<DeviceSelectionPageResponse>(`/api/devices?${buildDeviceRequestParams(devicePage).toString()}`, {
      signal: controller.signal,
    }).then((response) => {
      if (controller.signal.aborted) return;
      setDevicePageItems(Array.isArray(response.items) ? response.items : []);
      const total = Number.isFinite(response.total) ? Math.max(0, response.total) : 0;
      setDeviceTotal(total);
      setDeviceStatusCounts(response.status_counts || {});
      setDeviceFacets(response.facets || {});
      const lastPage = Math.max(1, Math.ceil(total / devicePageSize));
      if (devicePage > lastPage) setDevicePage(lastPage);
    }).catch((error: unknown) => {
      if (controller.signal.aborted || (error instanceof Error && error.name === 'AbortError')) return;
      setDevicePageError(error instanceof ApiError && error.status === 403
        ? (isZh ? '你没有查看设备列表的权限。' : 'You do not have permission to view the device list.')
        : (error instanceof Error ? error.message : String(error)));
    }).finally(() => {
      if (!controller.signal.aborted) setDevicePageLoading(false);
    });

    return () => {
      controller.abort();
      if (devicePageAbortRef.current === controller) devicePageAbortRef.current = null;
    };
  }, [currentStep, devicePage, devicePageSize, buildDeviceRequestParams, deviceRequestVersion, isZh]);

  const deviceTree = useMemo(() => {
    const rolesBySite = new Map<string, Array<{ role: string; count: number; onlineCount: number }>>();
    (deviceFacets.site_roles || []).forEach((facet) => {
      if (!facet.site || !facet.role) return;
      const roles = rolesBySite.get(facet.site) || [];
      roles.push({
        role: isZh && facet.role === 'Unassigned' ? '未分配' : facet.role,
        count: Number(facet.count || 0),
        onlineCount: Number(facet.online_count || 0),
      });
      rolesBySite.set(facet.site, roles);
    });
    return (deviceFacets.sites || []).map((facet) => ({
      site: isZh && facet.site === 'Unassigned' ? '未分组' : facet.site,
      count: Number(facet.count || 0),
      onlineCount: Number(facet.online_count || 0),
      roles: rolesBySite.get(facet.site) || [],
    }));
  }, [deviceFacets, isZh]);

  const vendors = useMemo(() => [...new Set(deviceFacets.vendors || [])].sort(), [deviceFacets.vendors]);
  const knownDevices = useMemo(() => {
    const byId = new Map<string, Device>();
    [...devices, ...rememberedBatchDevices, ...devicePageItems].forEach((device) => byId.set(device.id, device));
    return Array.from(byId.values());
  }, [devices, rememberedBatchDevices, devicePageItems]);
  const knownDevicesById = useMemo(
    () => new Map<string, Device>(knownDevices.map((device) => [device.id, device] as const)),
    [knownDevices],
  );
  const selectedBatchDevices = useMemo(
    () => batchDeviceIds.map((deviceId) => knownDevicesById.get(deviceId)).filter((device): device is Device => Boolean(device)),
    [batchDeviceIds, knownDevicesById],
  );
  const exportAllMatchingDevices = useCallback(async () => {
    const params = buildDeviceRequestParams(1);
    params.delete('page');
    params.delete('page_size');
    params.delete('include_facets');
    const allDevices = await fetchAllPaginatedItems<Device>('/api/devices', params, 1000);
    return {
      headers: [
        isZh ? '状态' : 'Status',
        isZh ? '主机名' : 'Hostname',
        'IP',
        isZh ? '厂商' : 'Vendor',
        isZh ? '类型' : 'Type',
        isZh ? '角色' : 'Role',
        isZh ? '站点' : 'Site',
      ],
      rows: allDevices.map((device) => [
        device.status === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline'),
        device.hostname,
        device.ip_address,
        getVendor(device),
        getDeviceCategory(device) === 'server' ? (isZh ? '服务器' : 'Server') : (isZh ? '网络设备' : 'Network'),
        device.role || '—',
        device.site || '—',
      ]),
    };
  }, [buildDeviceRequestParams, isZh]);

  const resetDevicePage = () => setDevicePage(1);
  const handleDeviceSearchChange = (value: string) => {
    onAutomationSearchChange(value);
  };
  const handleStatusFilterChange = (value: string) => { setStatusFilter(value); resetDevicePage(); };
  const handleVendorFilterChange = (value: string) => { setVendorFilter(value); resetDevicePage(); };
  const handleDeviceTypeFilterChange = (value: 'all' | 'network' | 'server') => { setDeviceTypeFilter(value); resetDevicePage(); };
  const handleTreeSiteChange = (value: string | null) => { setTreeFilterSite(value); resetDevicePage(); };
  const handleTreeRoleChange = (value: string | null) => { setTreeFilterRole(value); resetDevicePage(); };

  /* Filtered scenarios */
  const displayScenarios = useMemo(() => {
    const selectedDevices = batchMode ? selectedBatchDevices : selectedDevice ? [selectedDevice] : [];
    const selectedPlatforms = new Set(selectedDevices.map((d) => normalizeAutomationPlatform(d.platform)));
    const selectedCategories = new Set(selectedDevices.map((d) => getDeviceCategory(d)));

    return filteredScenarios.filter((s) => {
      if (categoryFilter !== 'all' && (s.category || 'Custom') !== categoryFilter) return false;
      if (riskFilter !== 'all' && s.risk !== riskFilter) return false;

      if (selectedDevices.length > 0) {
        if (s.supported_platforms && s.supported_platforms.length > 0) {
          const hasMatch = Array.from(selectedPlatforms).some((selectedPlatform) =>
            isAutomationPlatformSupported(selectedPlatform, s.supported_platforms)
          );
          if (!hasMatch) return false;
        }

        const isNetScenario = s.category === 'L2' || s.category === 'L3' || /vlan|bgp|ospf|route|switch/i.test(s.name + (s.description || ''));
        if (isNetScenario && selectedCategories.has('server') && !selectedCategories.has('network')) return false;
      }

      return true;
    });
  }, [filteredScenarios, categoryFilter, riskFilter, batchMode, selectedBatchDevices, selectedDevice]);

  const scenarioCategories = useMemo(() => {
    const cats = new Set(filteredScenarios.map((s) => s.category || 'Custom'));
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
  }, [
    hasQuickTargets,
    quickHasMixedPlatforms,
    quickPlatformMismatch,
    hasMissingRequired,
    riskNeedsConfirm,
    isZh,
    quickMissingRequiredFields,
    needsChangeTicket,
    changeTicket,
    ticketValidation,
  ]);

  /* Quick Query helpers */
  const targetDevices = batchMode ? selectedBatchDevices : selectedDevice ? [selectedDevice] : [];
  const singleDevice = targetDevices[0] || null;
  const hasTargets = targetDevices.length > 0;
  const platform = normalizeAutomationPlatform(singleDevice?.platform);
  const isCisco = platform === 'cisco_ios' || platform === 'cisco_xe' || platform === 'cisco';
  const isNxos = platform === 'cisco_nxos';
  const isHuawei = platform === 'huawei_vrp' || platform === 'huawei_vrpv8' || platform === 'huawei_yunshan';
  const isH3c = platform === 'h3c_comware' || platform.startsWith('h3c_comware_v');
  const isJuniper = platform === 'juniper_junos';
  const isArista = platform === 'arista_eos';
  const isRuijie = platform === 'ruijie_rgos';
  const isZte = platform === 'zte_zxros';
  const isDptech = platform === 'dptech_ios' || platform === 'dptech_conplat';
  const isMaipu = platform === 'maipu' || platform === 'maipu_mypower';
  const deviceRole = (singleDevice?.role || '').toLowerCase();

  const filteredQuickQueryRecords = useMemo(() => {
    if (!quickQueryTable.records) return [];
    if (!quickQuerySearch.trim()) return quickQueryTable.records;
    const q = quickQuerySearch.trim().toLocaleLowerCase();
    const searchableValue = (value: unknown): string => {
      if (value === null || value === undefined) return '';
      if (typeof value === 'object') {
        try {
          return JSON.stringify(value);
        } catch {
          return String(value);
        }
      }
      return String(value);
    };
    return quickQueryTable.records.filter((rec) => {
      return Object.values(rec).some((val) => searchableValue(val).toLocaleLowerCase().includes(q));
    });
  }, [quickQueryTable.records, quickQuerySearch]);

  const queryPresets = useMemo(() => {
    const selectedDevices = batchMode ? selectedBatchDevices : selectedDevice ? [selectedDevice] : [];
    const deviceCategory = selectedDevices.length > 0 ? getDeviceCategory(selectedDevices[0]) : 'all';

    const all: Array<{
      icon: string;
      label: string;
      labelEn: string;
      cmds: string;
      group: string;
      scope: 'network' | 'server' | 'all';
      operationalCategory?: string;
      excludeRoles?: string[];
    }> = [
        {
          icon: '📡',
          label: '接口状态',
          labelEn: 'Interfaces',
          group: 'net',
          scope: 'network',
          operationalCategory: 'interfaces',
          cmds: isHuawei || isH3c
            ? 'display interface brief'
            : isJuniper
              ? 'show interfaces terse'
              : isRuijie || isDptech
                ? 'show interface status'
                : isMaipu
                  ? 'show interface switchport brief'
                  : isZte
                    ? 'show interface brief'
                    : 'show ip interface brief',
        },
        {
          icon: '📋',
          label: 'ARP表',
          labelEn: 'ARP Table',
          group: 'net',
          scope: 'network',
          operationalCategory: 'arp',
          cmds: isHuawei
            ? 'display arp all'
            : isH3c
              ? 'display arp all'
              : isNxos
                ? 'show ip arp'
                : isJuniper
                  ? 'show arp no-resolve'
                  : isDptech
                    ? 'show arp all'
                    : 'show arp',
        },
        {
          icon: '🏷️',
          label: 'MAC表',
          labelEn: 'MAC Table',
          group: 'net',
          scope: 'network',
          operationalCategory: 'mac_table',
          excludeRoles: ['router'],
          cmds: isHuawei || isH3c
            ? 'display mac-address'
            : isJuniper
              ? 'show ethernet-switching table'
              : isMaipu
                ? 'show mac-address all'
                : isZte
                  ? 'show mac table'
                  : 'show mac address-table',
        },
        {
          icon: '📊',
          label: 'VLAN',
          labelEn: 'VLAN',
          group: 'net',
          scope: 'network',
          operationalCategory: 'vlan',
          excludeRoles: ['router'],
          cmds: isHuawei
            ? 'display vlan'
            : isH3c
              ? 'display vlan brief'
              : isJuniper
                ? 'show vlans'
                : isZte || isDptech || isMaipu || isRuijie
                  ? 'show vlan'
                  : 'show vlan brief',
        },
        {
          icon: '📌',
          label: 'LLDP邻居',
          labelEn: 'LLDP',
          group: 'net',
          scope: 'network',
          operationalCategory: 'neighbors',
          cmds: isHuawei
            ? 'display lldp neighbor brief'
            : isH3c
              ? 'display lldp neighbor-information list'
              : isJuniper
                ? 'show lldp neighbors'
                : isZte
                  ? 'show lldp neighbor'
                  : isDptech || isMaipu || isRuijie
                    ? 'show lldp neighbors'
                    : isCisco || isNxos
                      ? 'show lldp neighbors detail'
                      : 'show lldp neighbors detail',
        },
        {
          icon: '💎',
          label: '光模块状态',
          labelEn: 'Transceiver',
          group: 'net',
          scope: 'network',
          operationalCategory: 'transceiver',
          // Transceiver collection is SNMP-only. Keep the command empty so
          // unsupported vendors cannot fall through to parsed-command CLI.
          cmds: '',
        },

        {
          icon: '🗺️',
          label: '路由表',
          labelEn: 'Routes',
          group: 'route',
          scope: 'network',
          operationalCategory: 'routing_table',
          cmds: isHuawei
            ? 'display ip routing-table verbose'
            : isH3c
              ? 'display ip routing-table'
              : isJuniper
                ? 'show route'
                : isZte
                  ? 'show ip forwarding route'
                  : 'show ip route',
        },
        {
          icon: '🔗',
          label: 'BGP邻居',
          labelEn: 'BGP Peers',
          group: 'route',
          scope: 'network',
          operationalCategory: 'bgp',
          excludeRoles: ['access'],
          cmds: isHuawei
            ? 'display bgp peer'
            : isH3c
              ? 'display bgp peer ipv4 unicast'
              : isNxos
                ? 'show ip bgp summary'
                : isZte || isRuijie
                  ? 'show ip bgp neighbors'
                  : 'show ip bgp summary',
        },
        {
          icon: '🔍',
          label: 'OSPF邻居',
          labelEn: 'OSPF Nbrs',
          group: 'route',
          scope: 'network',
          operationalCategory: 'ospf',
          excludeRoles: ['access'],
          cmds: isHuawei || isH3c
            ? 'display ospf peer'
            : isNxos
              ? 'show ip ospf neighbors'
              : 'show ip ospf neighbor',
        },
        {
          icon: '⏱️',
          label: 'NTP同步',
          labelEn: 'NTP Status',
          group: 'route',
          scope: 'network',
          operationalCategory: isHuawei || isH3c || isCisco || isNxos || isZte || isDptech || isMaipu || isRuijie ? 'ntp' : undefined,
          cmds: isHuawei || isH3c
            ? 'display ntp-service status'
            : isNxos
              ? 'show ntp peer-status'
              : 'show ntp status',
        },

        {
          icon: '🔄',
          label: 'BFD会话',
          labelEn: 'BFD Sessions',
          group: 'route',
          scope: 'network',
          operationalCategory: isHuawei || isH3c || isCisco || isNxos || isRuijie || isDptech ? 'bfd' : undefined,
          excludeRoles: ['access'],
          cmds: isHuawei
            ? 'display bfd session all'
            : isH3c
              ? 'display bfd session'
              : isDptech
                ? 'show bfd session'
                : isCisco
                  ? 'show bfd neighbors details'
                  : 'show bfd neighbors',
        },

        { icon: '📈', label: '负载统计', labelEn: 'Load Avg', group: 'sys', scope: 'server', cmds: 'uptime && top -bn1 | head -n 5' },
        { icon: '💽', label: '磁盘空间', labelEn: 'Disk Usage', group: 'sys', scope: 'server', cmds: 'df -h' },
        { icon: '🧠', label: '内存占用', labelEn: 'Memory', group: 'sys', scope: 'server', cmds: 'free -m' },
        { icon: '⚡', label: '高负载进程', labelEn: 'Processes', group: 'sys', scope: 'server', cmds: 'ps aux --sort=-%cpu | head -n 11' },
        { icon: '🌐', label: '网络连接', labelEn: 'Netstat', group: 'sys', scope: 'server', cmds: 'ss -tulpn' },
        { icon: '🪵', label: '系统日志', labelEn: 'Syslog', group: 'sys', scope: 'server', cmds: 'tail -n 50 /var/log/syslog' },
        { icon: '🆔', label: 'IP地址', labelEn: 'IP Addr', group: 'sys', scope: 'server', cmds: 'ip a' },
        { icon: '🛤️', label: '路由表', labelEn: 'IP Route', group: 'sys', scope: 'server', cmds: 'ip route' },
        {
          icon: '🔌',
          label: '系统服务',
          labelEn: 'Services',
          group: 'sys',
          scope: 'server',
          cmds: 'systemctl list-units --type=service --state=running | head -n 20',
        },
        { icon: '🛡️', label: 'DNS配置', labelEn: 'DNS', group: 'sys', scope: 'server', cmds: 'cat /etc/resolv.conf' },
        { icon: '👤', label: '最近登录', labelEn: 'Last Login', group: 'sys', scope: 'server', cmds: 'last -n 10' },
        { icon: '🧱', label: '环境变量', labelEn: 'Env Vars', group: 'sys', scope: 'server', cmds: 'env | sort | head -n 30' },

        {
          icon: '🏥',
          label: '设备信息',
          labelEn: 'Version',
          group: 'sys',
          scope: 'all',
          operationalCategory: deviceCategory === 'server' ? undefined : 'version',
          cmds: isHuawei || isH3c
            ? 'display version'
            : 'show version',
        },
        {
          icon: '🔋',
          label: '电源风扇',
          labelEn: 'Environment',
          group: 'sys',
          scope: 'all',
          operationalCategory: isHuawei || isH3c || isCisco || isNxos || isZte || isDptech || isMaipu || isRuijie || isJuniper ? 'environment' : undefined,
          cmds: isHuawei
            ? 'display temperature all'
            : isH3c
              ? 'display environment'
              : isJuniper
                ? 'show chassis environment'
                : isRuijie
                  ? 'show temperature'
                  : isZte
                    ? 'show temperature detail'
                    : isDptech || isMaipu
                      ? 'show environment'
                      : isCisco
                        ? 'show environment temperature'
                        : 'show environment',
        },
        {
          icon: '📝',
          label: '日志概览',
          labelEn: 'Logs',
          group: 'sys',
          scope: 'all',
          operationalCategory: deviceCategory === 'server' ? undefined : 'logs',
          cmds: isHuawei
            ? 'display logbuffer last 30'
            : isH3c
              ? 'display logbuffer'
              : isJuniper
                ? 'show log messages | last 30'
                : isNxos
                  ? 'show logging last 30'
                  : isZte
                    ? 'show logging buffer almlog'
                    : isDptech
                      ? 'show logging operlog recent'
                      : isCisco || isRuijie
                        ? 'show logging'
                        : 'show logging | tail 30',
        },
        {
          icon: '🧩',
          label: '接口配置',
          labelEn: 'Intf Config',
          group: 'sys',
          scope: 'network',
          operationalCategory: 'interface_description',
          cmds: isHuawei || isH3c
            ? isH3c
              ? 'display interface brief description'
              : 'display interface description'
            : isJuniper
              ? 'show interfaces descriptions'
              : isNxos
                ? 'show interface description'
                : isRuijie
                  ? 'show ip interface brief'
                  : isZte || isDptech || isMaipu
                    ? 'show ip interface brief'
                    : isCisco
                      ? 'show interfaces description'
                      : 'show interfaces description\nshow interfaces status',
        },
        {
          icon: '🕒',
          label: '系统运行时间',
          labelEn: 'Uptime',
          group: 'sys',
          scope: 'all',
          operationalCategory: deviceCategory === 'server' ? undefined : 'uptime',
          cmds: isHuawei
            ? 'display version | include uptime'
            : isH3c
              ? 'display version'
              : isJuniper
                ? 'show system uptime'
                : isCisco || isNxos
                  ? 'show version'
                  : 'show version | include uptime',
        },
      ];

    if (isHuawei || isH3c) {
      all.push(
        {
          icon: '🌀',
          label: '风扇状态',
          labelEn: 'Fan Status',
          group: 'sys',
          scope: 'all',
          operationalCategory: 'fan',
          cmds: 'display fan',
        },
        {
          icon: '🔋',
          label: '电源状态',
          labelEn: 'Power Status',
          group: 'sys',
          scope: 'all',
          operationalCategory: 'power',
          cmds: 'display power',
        },
        {
          icon: '🧱',
          label: isHuawei ? 'Stack状态' : 'IRF状态',
          labelEn: isHuawei ? 'Stack Status' : 'IRF Status',
          group: 'sys',
          scope: 'all',
          operationalCategory: 'stack',
          cmds: isHuawei ? 'display stack' : 'display irf',
        },
        {
          icon: '🔗',
          label: 'Eth-Trunk/链路聚合',
          labelEn: 'Link Aggregation',
          group: 'net',
          scope: 'network',
          operationalCategory: 'eth_trunk',
          cmds: isHuawei ? 'display eth-trunk' : 'display link-aggregation verbose',
        },
      );
    }

    if (Array.isArray(savedQueries)) {
      savedQueries.forEach((s) => {
        all.push({
          icon: s.icon || '⭐',
          label: s.label,
          labelEn: s.labelEn || s.label,
          cmds: s.cmds,
          group: 'user',
          scope: 'all',
        });
      });
    }

    return all.filter((p) => {
      if (p.excludeRoles && p.excludeRoles.includes(deviceRole)) return false;
      if (deviceCategory !== 'all' && p.scope !== 'all' && p.scope !== deviceCategory) return false;
      return true;
    });
  }, [isCisco, isHuawei, isH3c, isNxos, isJuniper, isRuijie, deviceRole, savedQueries, batchMode, selectedBatchDevices, selectedDevice]);

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

  const openConfirmationModal = (open: boolean) => {
    setConfirmModalOpen(open);
  };
  useFocusTrap(confirmDialogRef, confirmModalOpen, '[data-confirm-cancel]');

  const handleTreeFilter = (site: string | null, role: string | null) => {
    if (treeFilterSite === site && treeFilterRole === role) {
      setTreeFilterSite(null);
      setTreeFilterRole(null);
    } else {
      setTreeFilterSite(site);
      setTreeFilterRole(role);
    }
    resetDevicePage();
  };

  const varGroupLabel = (group: string) => {
    if (group === 'address') return isZh ? '🌐 地址与邻居' : '🌐 Address & Neighbors';
    if (group === 'interface') return isZh ? '📡 接口与二层' : '📡 Interfaces & L2';
    if (group === 'routing') return isZh ? '🗺️ 路由与策略' : '🗺️ Routing & Policy';
    return isZh ? '⚙️ 通用参数' : '⚙️ General';
  };

  /* ESC key handling */
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (confirmModalOpen) {
          setConfirmModalOpen(false);
          return;
        }
        if (quickQueryRunning || quickQueryOutput) {
          onResetQuickQuery();
          return;
        }
        if (showSelectedDrawer) {
          setShowSelectedDrawer(false);
          return;
        }
        if (hasTargets) {
          handleClearSelection();
          return;
        }
        if (currentStep > 1) {
          if (currentStep === 2) setCurrentStep(1);
          else if (currentStep === 3) setCurrentStep(2);
        }
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [confirmModalOpen, quickQueryRunning, quickQueryOutput, hasTargets, showSelectedDrawer, currentStep, onResetQuickQuery, handleClearSelection]);

  return (
    <div className="h-full min-h-0 flex flex-col relative">
      <PageHero
        icon={Zap}
        title={isZh ? '自动化快捷操作' : 'Quick Operations'}
        subtitle={isZh ? '选择设备进行快捷查询或执行自定义命令' : 'Select devices for quick query or custom commands'}
      />

      <div className="flex-1 min-h-0 flex flex-col px-6 py-5 overflow-hidden">
        <div className="flex-1 min-h-0 overflow-hidden">
          <AnimatePresence mode="wait">
            {currentStep === 1 && (
              <DeviceSelectionStep
                isZh={isZh}
                language={language}
                automationSearch={automationSearch}
                onAutomationSearchChange={handleDeviceSearchChange}
                deviceTree={deviceTree}
                treeFilterSite={treeFilterSite}
                treeFilterRole={treeFilterRole}
                handleTreeFilter={handleTreeFilter}
                setTreeFilterSite={handleTreeSiteChange}
                setTreeFilterRole={handleTreeRoleChange}
                deviceTypeFilter={deviceTypeFilter}
                setDeviceTypeFilter={handleDeviceTypeFilterChange}
                statusFilter={statusFilter}
                setStatusFilter={handleStatusFilterChange}
                deviceItems={devicePageItems}
                totalDevices={deviceTotal}
                onlineDeviceCount={Number(deviceStatusCounts.online || 0)}
                devicePageLoading={devicePageLoading}
                devicePageError={devicePageError}
                onRetryDevicePage={() => setDeviceRequestVersion((version) => version + 1)}
                exportAllMatchingDevices={exportAllMatchingDevices}
                vendors={vendors}
                vendorFilter={vendorFilter}
                setVendorFilter={handleVendorFilterChange}
                devicePageSize={devicePageSize}
                setDevicePageSize={setDevicePageSize}
                deviceViewMode={deviceViewMode}
                setDeviceViewMode={setDeviceViewMode}
                batchMode={batchMode}
                onToggleBatchMode={onToggleBatchMode}
                batchDeviceIds={batchDeviceIds}
                onToggleBatchDevice={onToggleBatchDevice}
                onRememberDevice={onRememberDevice}
                selectedDevice={selectedDevice}
                devicePage={devicePage}
                setDevicePage={setDevicePage}
                targetCount={targetCount}
                showSelectedDrawer={showSelectedDrawer}
                setShowSelectedDrawer={setShowSelectedDrawer}
                handleClearSelection={handleClearSelection}
                devices={knownDevices}
              />
            )}

            {currentStep === 2 && (
              <ScenarioSelectionStep
                isZh={isZh}
                scenarioCategories={scenarioCategories}
                categoryFilter={categoryFilter}
                setCategoryFilter={setCategoryFilter}
                scenarioSearch={scenarioSearch}
                onScenarioSearchChange={onScenarioSearchChange}
                riskFilter={riskFilter}
                setRiskFilter={setRiskFilter}
                targetCount={targetCount}
                batchMode={batchMode}
                selectedDevice={selectedDevice}
                displayScenarios={displayScenarios}
                onOpenScenario={onOpenScenario}
                setCurrentStep={setCurrentStep}
                filteredScenarios={filteredScenarios}
              />
            )}

            {currentStep === 3 && quickPlaybookScenario && (
              <ParameterConfigStep
                isZh={isZh}
                quickPlaybookScenario={quickPlaybookScenario}
                groupedVariables={groupedVariables}
                VAR_GROUP_ORDER={VAR_GROUP_ORDER}
                varGroupLabel={varGroupLabel}
                quickPlaybookVars={quickPlaybookVars}
                onQuickPlaybookVarChange={onQuickPlaybookVarChange}
                quickPlaybookPlatform={quickPlaybookPlatform}
                quickPlaybookConcurrency={quickPlaybookConcurrency}
                onQuickPlaybookConcurrencyChange={onQuickPlaybookConcurrencyChange}
                changeTicket={changeTicket}
                setChangeTicket={setChangeTicket}
                ticketValidation={ticketValidation}
                blockingIssues={blockingIssues}
                quickRiskConfirmed={quickRiskConfirmed}
                onQuickRiskConfirmedChange={onQuickRiskConfirmedChange}
                previewLineCount={previewLineCount}
                quickPlaybookPreview={quickPlaybookPreview}
                onOpenCommandPreview={onOpenCommandPreview}
                canExecute={canExecute}
                setConfirmAction={setConfirmAction}
                setConfirmModalOpen={openConfirmationModal}
                onRunValidation={onRunValidation}
                setCurrentStep={setCurrentStep}
                targetCount={targetCount}
                getPlatformLabel={getPlatformLabel}
              />
            )}

            {currentStep === 4 && (
              <ExecutionResultsStep
                isZh={isZh}
                wsCompleteMsg={wsCompleteMsg}
                deviceStatusMap={deviceStatusMap}
                targetCount={targetCount}
                isQuickPlaybookRunning={isQuickPlaybookRunning}
                quickExecutionResult={quickExecutionResult}
                quickPlaybookScenario={quickPlaybookScenario}
                logEndRef={logEndRef}
                onNavigate={onNavigate}
                handleNewTask={handleNewTask}
              />
            )}
          </AnimatePresence>
        </div>

        {/* Quick Query Area */}
        <QuickQueryOverlay
          isZh={isZh}
          targetDevices={targetDevices}
          handleClearSelection={handleClearSelection}
          queryPresets={queryPresets}
          quickQueryRunning={quickQueryRunning}
          onRunQuickQuery={onRunQuickQuery}
          hasTargets={hasTargets}
        />

        {/* Quick Query Result Terminal Overlay */}
        <QuickQueryResultOverlay
          isZh={isZh}
          quickQueryRunning={quickQueryRunning}
          quickQueryOutput={quickQueryOutput}
          quickQueryMaximized={quickQueryMaximized}
          quickQueryLabel={quickQueryLabel}
          targetDevices={targetDevices}
          onQuickQueryMaximizedChange={onQuickQueryMaximizedChange}
          onResetQuickQuery={onResetQuickQuery}
          quickQueryCommands={quickQueryCommands}
          copyTextWithFallback={copyTextWithFallback}
          showToast={showToast}
          quickQueryStructured={quickQueryStructured}
          quickQueryView={quickQueryView}
          quickQueryTable={quickQueryTable}
          quickQuerySearch={quickQuerySearch}
          setQuickQuerySearch={setQuickQuerySearch}
          filteredQuickQueryRecords={filteredQuickQueryRecords}
          onQuickQueryViewChange={onQuickQueryViewChange}
          onOpenDebugger={(platform, command, output) => {
            setDebuggerPlatform(platform);
            setDebuggerCommand(command);
            setDebuggerSampleOutput(output);
            setDebuggerOpen(true);
          }}
        />

        {/* Execution Confirmation Modal */}
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
                ref={confirmDialogRef}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="fixed left-1/2 top-1/2 z-[80] -translate-x-1/2 -translate-y-1/2 w-[440px] bg-white rounded-2xl shadow-2xl border border-gray-200 overflow-hidden"
                role="dialog"
                aria-modal="true"
                aria-labelledby="automation-confirm-title"
                aria-describedby="automation-confirm-description"
                tabIndex={-1}
              >
                <div
                  className={`px-6 py-4 ${confirmAction === 'apply'
                      ? quickPlaybookScenario?.risk === 'high'
                        ? 'bg-gradient-to-r from-red-50 to-rose-50'
                        : 'bg-gradient-to-r from-cyan-50 to-teal-50'
                      : 'bg-gradient-to-r from-cyan-50 to-cyan-100/50'
                    }`}
                >
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
                      <p id="automation-confirm-title" className="text-base font-bold text-gray-800">
                        {confirmAction === 'validate'
                          ? isZh
                            ? '确认运行校验'
                            : 'Confirm Validation'
                          : isZh
                            ? '确认应用变更'
                            : 'Confirm Apply'}
                      </p>
                      <p id="automation-confirm-description" className="text-xs text-gray-500">
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
                    <span>
                      {quickPlaybookScenario?.icon} {isZh ? quickPlaybookScenario?.name_zh : quickPlaybookScenario?.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-600">
                    <span className="font-bold text-gray-400 w-16">{isZh ? '目标' : 'Target'}</span>
                    <span>
                      {targetCount} {isZh ? '台设备' : 'device(s)'}
                    </span>
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
                    type="button"
                    data-confirm-cancel
                    onClick={() => setConfirmModalOpen(false)}
                    className="px-4 py-2 rounded-xl text-xs font-bold text-gray-500 border border-gray-200 hover:bg-gray-50 transition-all"
                  >
                    {isZh ? '取消' : 'Cancel'}
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmExecute}
                    className={`px-5 py-2 rounded-xl text-xs font-bold text-white transition-all ${confirmAction === 'apply' && quickPlaybookScenario?.risk === 'high'
                        ? 'bg-red-500 hover:bg-red-600 shadow-lg shadow-red-500/25'
                        : 'bg-gradient-to-r from-cyan-500 to-teal-500 shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40'
                      }`}
                  >
                    {confirmAction === 'validate'
                      ? isZh
                        ? '确认校验'
                        : 'Confirm Validate'
                      : isZh
                        ? '确认执行'
                        : 'Confirm Apply'}
                  </button>
                </div>
              </motion.div>
            </>
          )}
        </AnimatePresence>

        <TextFSMDebugger
          isOpen={debuggerOpen}
          onClose={() => setDebuggerOpen(false)}
          platform={debuggerPlatform}
          command={debuggerCommand}
          sampleOutput={debuggerSampleOutput}
          onSaveSuccess={() => {
            // Re-run the quick query with the same parameters
            onRunQuickQuery(quickQueryLabel, quickQueryCommands.join('\n'));
          }}
        />
      </div>
    </div>
  );
};

export default AutomationExecuteTab;
