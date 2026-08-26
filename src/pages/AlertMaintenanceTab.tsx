import React, { useEffect, useMemo, useState, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Check, Copy, Eye, Plus, RefreshCw, Search, Trash2, Wrench, X } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import DateTimePicker from '../components/DateTimePicker';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import type {
  AlertMaintenanceCondition,
  AlertMaintenanceConditionField,
  AlertMaintenanceConditionLogic,
  AlertMaintenanceConditionOperator,
  AlertMaintenanceListResponse,
  AlertMaintenanceWindow,
  Device,
  User,
} from '../types';
import Pagination from '../components/Pagination';
import { authHeaders } from '../api/http';
import {
  alertAccentButtonClass,
  alertDangerButtonClass,
  alertInputClass,
  alertPanelClass,
  alertPrimaryButtonClass,
  alertSecondaryButtonClass,
  alertTableActionAccentButtonClass,
  alertTableActionBarClass,
  alertTableActionButtonClass,
  alertTableActionDangerButtonClass,
  ALERT_SEVERITY_OPTIONS,
  AlertPageCommonProps,
  buildEmptyMaintenanceCondition,
  buildDefaultMaintenanceConditions,
  buildDefaultMaintenanceForm,
  formatTs,
  maintenanceBadgeClass,
  maintenanceStatusLabel,
  MaintenanceFormState,
  severityLabel,
  useAlertOverlayDismiss,
} from './alertManagementShared';

type RuntimeFilter = 'all' | AlertMaintenanceWindow['runtime_status'];

type SelectionMode = MaintenanceFormState['selection_mode'];

const CONDITION_LOGIC_OPTIONS: Array<{ value: AlertMaintenanceConditionLogic; zh: string; en: string }> = [
  { value: 'all', zh: '满足全部', en: 'Match All' },
  { value: 'any', zh: '满足任意', en: 'Match Any' },
  { value: 'none', zh: '都不满足', en: 'Match None' },
];

const CONDITION_OPERATOR_OPTIONS: Array<{ value: AlertMaintenanceConditionOperator; zh: string; en: string }> = [
  { value: 'contains', zh: '包含', en: 'Contains' },
  { value: 'equals', zh: '等于', en: 'Equals' },
  { value: 'not_contains', zh: '不包含', en: 'Does Not Contain' },
  { value: 'not_equals', zh: '不等于', en: 'Not Equal' },
  { value: 'regex', zh: '正则表达式', en: 'Regex' },
];

const fieldLabel = (field: AlertMaintenanceConditionField, language: string) => {
  switch (field) {
    case 'alert_description':
      return language === 'zh' ? '告警描述' : 'Alert Description';
    case 'alert_ip':
      return language === 'zh' ? '告警IP' : 'Alert IP';
    case 'alert_level':
      return language === 'zh' ? '告警等级' : 'Alert Level';
    default:
      return field;
  }
};

const fieldPlaceholder = (field: AlertMaintenanceConditionField, language: string) => {
  switch (field) {
    case 'alert_description':
      return language === 'zh' ? '例如 Interface Down / CPU High' : 'Example: Interface Down / CPU High';
    case 'alert_ip':
      return language === 'zh' ? '例如 10.0.0.5' : 'Example: 10.0.0.5';
    case 'alert_level':
      return language === 'zh' ? '例如 critical / major / warning' : 'Example: critical / major / warning';
    default:
      return '';
  }
};

const normalizeConditionsForForm = (source?: AlertMaintenanceCondition[] | null) => {
  const items = (source || [])
    .filter((item): item is AlertMaintenanceCondition => Boolean(item?.field && item?.operator))
    .map((item) => ({
      field: item.field,
      operator: item.operator,
      value: item.value || '',
    }));
  return items.length ? items : [buildEmptyMaintenanceCondition()];
};

const conditionSummary = (condition: AlertMaintenanceCondition, language: string) => {
  const operator = CONDITION_OPERATOR_OPTIONS.find((item) => item.value === condition.operator);
  const operatorLabel = operator ? (language === 'zh' ? operator.zh : operator.en) : condition.operator;
  return `${fieldLabel(condition.field, language)} ${operatorLabel} ${condition.value || '--'}`;
};

const conditionLogicLabel = (logic: AlertMaintenanceConditionLogic | undefined, language: string) => {
  const option = CONDITION_LOGIC_OPTIONS.find((item) => item.value === logic);
  return option ? (language === 'zh' ? option.zh : option.en) : (language === 'zh' ? '满足全部' : 'Match All');
};

const AlertMaintenanceTab: React.FC<AlertPageCommonProps> = ({ language, currentUsername, showToast }) => {
  const location = useLocation();
  const [devices, setDevices] = useState<Device[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [windows, setWindows] = useState<AlertMaintenanceWindow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<RuntimeFilter>('all');
  const [showMaintenanceModal, setShowMaintenanceModal] = useState(false);
  const [showAssetPicker, setShowAssetPicker] = useState(false);
  const [assetSearchQuery, setAssetSearchQuery] = useState('');
  const [assetSearchResults, setAssetSearchResults] = useState<Device[]>([]);
  const [assetSearchLoading, setAssetSearchLoading] = useState(false);
  const [assetPickerSelection, setAssetPickerSelection] = useState<string[]>([]);
  const [maintenanceSubmitting, setMaintenanceSubmitting] = useState(false);
  const [maintenanceForm, setMaintenanceForm] = useState<MaintenanceFormState>(buildDefaultMaintenanceForm(null));
  const [maintenanceCancelingId, setMaintenanceCancelingId] = useState<string | null>(null);
  const [selectedWindowId, setSelectedWindowId] = useState<string | null>(null);

  const queriedIps = useRef<Set<string>>(new Set());

  const selectedWindow = useMemo(
    () => windows.find((item) => item.id === selectedWindowId) || null,
    [selectedWindowId, windows],
  );

  const assetByIp = useMemo(
    () => new Map(devices.filter((device) => Boolean(device.ip_address)).map((device) => [device.ip_address, device])),
    [devices],
  );

  const selectedAssets = useMemo(
    () => maintenanceForm.target_ips.map((ip) => assetByIp.get(ip)).filter(Boolean) as Device[],
    [assetByIp, maintenanceForm.target_ips],
  );

  const pickerSelectedAssets = useMemo(
    () => assetPickerSelection.map((ip) => assetByIp.get(ip)).filter(Boolean) as Device[],
    [assetByIp, assetPickerSelection],
  );

  const mergeDeviceCache = (items: Device[]) => {
    if (!items.length) return;
    setDevices((prev) => {
      const merged = new Map(prev.map((device) => [device.ip_address || device.id, device]));
      items.forEach((device) => {
        merged.set(device.ip_address || device.id, device);
      });
      return Array.from(merged.values());
    });
  };

  const updateMaintenanceField = <K extends keyof MaintenanceFormState>(key: K, value: MaintenanceFormState[K]) => {
    setMaintenanceForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateSelectionMode = (mode: SelectionMode) => {
    setMaintenanceForm((prev) => ({
      ...prev,
      selection_mode: mode,
      target_ip: mode === 'resources' ? (prev.target_ips[0] || prev.target_ip) : prev.target_ip,
    }));
  };

  const updateCondition = (index: number, patch: Partial<AlertMaintenanceCondition>) => {
    setMaintenanceForm((prev) => ({
      ...prev,
      match_conditions: prev.match_conditions.map((condition, conditionIndex) => (
        conditionIndex === index ? { ...condition, ...patch } : condition
      )),
    }));
  };

  const addConditionRow = () => {
    setMaintenanceForm((prev) => ({
      ...prev,
      match_conditions: [...prev.match_conditions, buildEmptyMaintenanceCondition()],
    }));
  };

  const removeConditionRow = (index: number) => {
    setMaintenanceForm((prev) => {
      const nextConditions = prev.match_conditions.filter((_, conditionIndex) => conditionIndex !== index);
      return {
        ...prev,
        match_conditions: nextConditions.length ? nextConditions : [buildEmptyMaintenanceCondition()],
      };
    });
  };

  const applySelectedAssets = (targetIps: string[]) => {
    const unique = Array.from(new Set(targetIps.map((ip) => ip.trim()).filter(Boolean)));
    setMaintenanceForm((prev) => ({
      ...prev,
      target_ips: unique,
      target_ip: unique[0] || '',
    }));
  };

  const ensureDeviceLoaded = async (targetIp?: string | null) => {
    const target = targetIp?.trim();
    if (!target || assetByIp.has(target) || queriedIps.current.has(target)) return;
    queriedIps.current.add(target);
    try {
      const params = new URLSearchParams({
        mode: 'light',
        page: '1',
        page_size: '20',
        sort_key: 'hostname',
        sort_direction: 'asc',
        search: target,
      });
      const resp = await fetch(`/api/devices?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed to load device');
      const data = await resp.json();
      const items = Array.isArray(data) ? data : (Array.isArray(data.items) ? data.items : []);
      mergeDeviceCache(items);
    } catch (error) {
      console.error(error);
    }
  };

  const ensureDevicesLoaded = async (targetIps: string[]) => {
    const missing = targetIps.filter((ip) => ip && !assetByIp.has(ip));
    if (!missing.length) return;
    await Promise.all(missing.map((ip) => ensureDeviceLoaded(ip)));
  };

  const loadUsers = async () => {
    try {
      const resp = await fetch('/api/users', { headers: authHeaders() });
      if (!resp.ok) throw new Error('Failed to load users');
      setUsers(await resp.json());
    } catch (error) {
      console.error(error);
    }
  };

  const searchDevices = async (keyword: string) => {
    try {
      const params = new URLSearchParams({
        mode: 'light',
        page: '1',
        page_size: '50',
        sort_key: 'hostname',
        sort_direction: 'asc',
        search: keyword,
      });
      const resp = await fetch(`/api/devices?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed to load devices');
      const data = await resp.json();
      const items = Array.isArray(data) ? data : (Array.isArray(data.items) ? data.items : []);
      setAssetSearchResults(items);
      mergeDeviceCache(items);
    } catch (error) {
      console.error(error);
      setAssetSearchResults([]);
      showToast(language === 'zh' ? '搜索资产失败' : 'Failed to search devices', 'error');
    }
  };

  const loadMaintenanceWindows = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        status: statusFilter,
        search: searchQuery,
      });
      const resp = await fetch(`/api/alerts/maintenance-windows?${params.toString()}`);
      if (!resp.ok) throw new Error('Failed to load maintenance windows');
      const data: AlertMaintenanceListResponse = await resp.json();
      const items = data.items || [];
      setWindows(items);
      setTotal(data.total && data.total > 0 ? data.total : items.length);
      if (selectedWindowId && !items.some((item) => item.id === selectedWindowId)) {
        setSelectedWindowId(null);
      }
    } catch (error) {
      console.error(error);
      showToast(language === 'zh' ? '加载维护窗失败' : 'Failed to load maintenance windows', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadUsers();
  }, []);

  useEffect(() => {
    void loadMaintenanceWindows();
  }, [page, pageSize, searchQuery, statusFilter]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('open') !== '1') return;

    const next = buildDefaultMaintenanceForm(null);
    next.name = params.get('name') || next.name;

    const targetIp = params.get('target_ip') || '';
    const titlePattern = params.get('title_pattern') || '';
    const messagePattern = params.get('message_pattern') || '';

    if (targetIp && !titlePattern && !messagePattern) {
      next.selection_mode = 'resources';
      next.target_ips = [targetIp];
      next.target_ip = targetIp;
    } else {
      next.selection_mode = 'conditions';
      next.condition_logic = 'all';
      next.match_conditions = normalizeConditionsForForm([
        titlePattern ? { field: 'alert_description', operator: 'contains', value: titlePattern } : null,
        messagePattern ? { field: 'alert_description', operator: 'contains', value: messagePattern } : null,
        targetIp ? { field: 'alert_ip', operator: 'equals', value: targetIp } : null,
      ].filter(Boolean) as AlertMaintenanceCondition[]);
    }

    setMaintenanceForm(next);
    setShowMaintenanceModal(true);
  }, [location.search]);

  useEffect(() => {
    if (!showAssetPicker) {
      setAssetSearchLoading(false);
      return;
    }

    const keyword = assetSearchQuery.trim();
    if (!keyword) {
      setAssetSearchResults([]);
      setAssetSearchLoading(false);
      return;
    }

    let active = true;
    setAssetSearchLoading(true);
    const timer = window.setTimeout(() => {
      void searchDevices(keyword).finally(() => {
        if (active) setAssetSearchLoading(false);
      });
    }, 250);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [assetSearchQuery, showAssetPicker]);

  useEffect(() => {
    void ensureDevicesLoaded(maintenanceForm.target_ips);
  }, [maintenanceForm.target_ips]);

  useEffect(() => {
    const windowIps = windows.flatMap((item) => item.target_ips || (item.target_ip ? [item.target_ip] : []));
    void ensureDevicesLoaded(windowIps);
  }, [windows]);

  const closeMaintenanceModal = () => setShowMaintenanceModal(false);
  const closeAssetPicker = () => {
    setShowAssetPicker(false);
    setAssetSearchQuery('');
    setAssetSearchResults([]);
  };
  const closeSelectedWindow = () => setSelectedWindowId(null);

  useAlertOverlayDismiss(showMaintenanceModal, closeMaintenanceModal);
  useAlertOverlayDismiss(showAssetPicker, closeAssetPicker);
  useAlertOverlayDismiss(Boolean(selectedWindow), closeSelectedWindow);

  const handleCreateMaintenance = async () => {
    const activeConditions = maintenanceForm.match_conditions.filter((item) => item.value.trim());
    if (maintenanceForm.selection_mode === 'resources' && !maintenanceForm.target_ips.length) {
      showToast(language === 'zh' ? '请至少选择一个资源对象' : 'Select at least one resource object', 'error');
      return;
    }
    if (maintenanceForm.selection_mode === 'conditions' && !activeConditions.length) {
      showToast(language === 'zh' ? '请至少填写一个条件定义' : 'Add at least one condition', 'error');
      return;
    }

    setMaintenanceSubmitting(true);
    try {
      const toIso = (value: string) => {
        const dt = new Date(value);
        if (Number.isNaN(dt.getTime())) return value;
        return dt.toISOString();
      };
      const payload = {
        ...maintenanceForm,
        target_ip: maintenanceForm.target_ips[0] || '',
        starts_at: toIso(maintenanceForm.starts_at),
        ends_at: toIso(maintenanceForm.ends_at),
        created_by: currentUsername,
      };
      const resp = await fetch('/api/alerts/maintenance-windows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to create maintenance window');
      showToast(language === 'zh' ? '维护窗已创建' : 'Maintenance window created', 'success');
      closeMaintenanceModal();
      setPage(1);
      await loadMaintenanceWindows();
      setSelectedWindowId(data.id || null);
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '创建维护窗失败' : 'Failed to create maintenance window'), 'error');
    } finally {
      setMaintenanceSubmitting(false);
    }
  };

  const handleCancelWindow = async (windowId: string) => {
    setMaintenanceCancelingId(windowId);
    try {
      const resp = await fetch(`/api/alerts/maintenance-windows/${windowId}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_username: currentUsername }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to cancel maintenance window');
      showToast(language === 'zh' ? '维护窗已取消' : 'Maintenance window cancelled', 'success');
      await loadMaintenanceWindows();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '取消维护窗失败' : 'Failed to cancel maintenance window'), 'error');
    } finally {
      setMaintenanceCancelingId(null);
    }
  };

  const handleDeleteWindow = async (windowId: string) => {
    setMaintenanceCancelingId(windowId);
    try {
      const resp = await fetch(`/api/alerts/maintenance-windows/${windowId}?actor_username=${encodeURIComponent(currentUsername)}`, {
        method: 'DELETE',
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Failed to delete maintenance window');
      showToast(language === 'zh' ? '维护窗已删除' : 'Maintenance window deleted', 'success');
      setSelectedWindowId((prev) => (prev === windowId ? null : prev));
      await loadMaintenanceWindows();
    } catch (error: any) {
      showToast(error?.message || (language === 'zh' ? '删除维护窗失败' : 'Failed to delete maintenance window'), 'error');
    } finally {
      setMaintenanceCancelingId(null);
    }
  };

  const handleCopyWindow = (window: AlertMaintenanceWindow) => {
    const next = buildDefaultMaintenanceForm(null);
    next.name = language === 'zh' ? `${window.name} 副本` : `${window.name} Copy`;
    next.selection_mode = window.selection_mode || 'resources';
    next.condition_logic = window.condition_logic || 'all';
    next.target_ips = window.target_ips || (window.target_ip ? [window.target_ip] : []);
    next.target_ip = next.target_ips[0] || window.target_ip || '';
    next.match_conditions = normalizeConditionsForForm(window.match_conditions);
    next.reason = window.reason || '';
    next.notify_user_ids = window.notify_user_ids || [];

    setMaintenanceForm(next);
    setSelectedWindowId(null);
    setShowMaintenanceModal(true);
    showToast(language === 'zh' ? '已打开复制维护期窗口' : 'Opened duplicated maintenance window', 'success');
  };

  const openCreate = () => {
    setMaintenanceForm(buildDefaultMaintenanceForm(null));
    setAssetPickerSelection([]);
    setAssetSearchQuery('');
    setAssetSearchResults([]);
    setShowMaintenanceModal(true);
  };

  const openAssetPicker = () => {
    setAssetPickerSelection(maintenanceForm.target_ips);
    setAssetSearchQuery('');
    setAssetSearchResults([]);
    setShowAssetPicker(true);
  };

  const toggleAssetSelection = (targetIp: string) => {
    setAssetPickerSelection((prev) => (
      prev.includes(targetIp) ? prev.filter((item) => item !== targetIp) : [...prev, targetIp]
    ));
  };

  const confirmAssetSelection = () => {
    applySelectedAssets(assetPickerSelection);
    closeAssetPicker();
    showToast(language === 'zh' ? '资源对象已更新' : 'Resource objects updated', 'success');
  };

  const removeSelectedAsset = (targetIp: string) => {
    applySelectedAssets(maintenanceForm.target_ips.filter((item) => item !== targetIp));
  };

  const renderWindowScope = (window: AlertMaintenanceWindow) => {
    if ((window.selection_mode || 'resources') === 'resources') {
      const targets = window.target_ips || (window.target_ip ? [window.target_ip] : []);
      const firstTarget = targets[0] || '--';
      const firstAsset = assetByIp.get(firstTarget);
      return (
        <div>
          <div className="font-mono">{firstTarget}</div>
          <div className="mt-1 text-xs text-black/40">
            {firstAsset?.hostname || (targets.length > 1 ? `+${targets.length - 1}` : '--')}
          </div>
        </div>
      );
    }

    const activeConditions = (window.match_conditions || []).filter((item) => item.value.trim());
    return (
      <div className="space-y-1">
        <div className="text-xs font-semibold text-[#164e63]">{conditionLogicLabel(window.condition_logic, language)}</div>
        <div className="text-xs text-black/45">{activeConditions[0] ? conditionSummary(activeConditions[0], language) : '--'}</div>
        {activeConditions.length > 1 ? <div className="text-[11px] text-black/35">+{activeConditions.length - 1}</div> : null}
      </div>
    );
  };

  return (
    <>
    <div className="flex-1 flex flex-col overflow-hidden min-h-0">
      <PageHero
        icon={Wrench}
        eyebrow={language === 'zh' ? '告警中心 / 维护期' : 'Alert Center / Maintenance'}
        title={language === 'zh' ? '当前维护期' : 'Current Maintenance Windows'}
        subtitle={language === 'zh' ? '通过灵活的规则组合设定告警静默窗口，避免计划内变更引发告警风暴。' : 'Define suppression windows via flexible rule logic to prevent alert storms during planned maintenance.'}
        actions={
          <>
            <button onClick={() => void loadMaintenanceWindows()} className={alertSecondaryButtonClass}>
              <RefreshCw size={14} />
              {language === 'zh' ? '刷新' : 'Refresh'}
            </button>
            <button onClick={openCreate} className={alertPrimaryButtonClass}>
              <Plus size={14} />
              {language === 'zh' ? '新建维护期' : 'New Window'}
            </button>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 min-h-0">
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        <div className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center">
          <label className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/40" />
            <input
              value={searchQuery}
              onChange={(e) => {
                setPage(1);
                setSearchQuery(e.target.value);
              }}
              placeholder={language === 'zh' ? '搜索名称、资源IP、条件、原因、创建人' : 'Search name, resource IP, conditions, reason, creator'}
              className={`${alertInputClass} rounded-xl py-3 pl-9 pr-3`}
            />
          </label>
          <select
            title={language === 'zh' ? '按状态筛选维护窗' : 'Filter maintenance windows by status'}
            value={statusFilter}
            onChange={(e) => {
              setPage(1);
              setStatusFilter(e.target.value as RuntimeFilter);
            }}
            className="rounded-xl border border-black/10 bg-white px-3 py-3 text-sm text-[#164e63] outline-none"
          >
            <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
            <option value="active">{language === 'zh' ? '生效中' : 'Active'}</option>
            <option value="scheduled">{language === 'zh' ? '待生效' : 'Scheduled'}</option>
            <option value="expired">{language === 'zh' ? '已过期' : 'Expired'}</option>
            <option value="cancelled">{language === 'zh' ? '已取消' : 'Cancelled'}</option>
          </select>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar border-b border-black/5">
          <table className="nx-data-table text-left">
            <thead className="sticky top-0 z-10">
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="px-5 py-3">{language === 'zh' ? '维护名称' : 'Name'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '作用范围' : 'Scope'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '开始时间' : 'Start Time'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '结束时间' : 'End Time'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '状态' : 'Status'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '创建人' : 'Created By'}</th>
                <th className="px-5 py-3">{language === 'zh' ? '操作' : 'Action'}</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '正在加载维护窗...' : 'Loading maintenance windows...'}
                  </td>
                </tr>
              ) : windows.length > 0 ? (
                windows.map((window) => (
                  <tr key={window.id} className="border-b border-black/5 hover:bg-black/[0.02]">
                    <td className="px-5 py-4 align-top">
                      <button title={language === 'zh' ? `查看维护窗 ${window.name}` : `View maintenance window ${window.name}`} onClick={() => setSelectedWindowId(window.id)} className="text-left">
                        <p className="text-sm font-semibold text-[#164e63]">{window.name}</p>
                        <p className="mt-1 line-clamp-1 text-xs text-black/45">{window.reason || (language === 'zh' ? '未填写原因' : 'No reason')}</p>
                      </button>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{renderWindowScope(window)}</td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{formatTs(window.starts_at)}</td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{formatTs(window.ends_at)}</td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-bold uppercase ${maintenanceBadgeClass(window.runtime_status)}`}>
                        {maintenanceStatusLabel(window.runtime_status, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top text-sm text-black/60">{window.created_by}</td>
                    <td className="px-5 py-4 align-top">
                      <ActionIconGroup className={alertTableActionBarClass} label={language === 'zh' ? '维护窗操作' : 'Maintenance window actions'}>
                        <ActionIconButton
                          icon={Eye}
                          label={language === 'zh' ? `查看维护窗 ${window.name}` : `View maintenance window ${window.name}`}
                          size="sm"
                          onClick={() => setSelectedWindowId(window.id)}
                        />
                        <ActionIconButton
                          icon={Copy}
                          label={language === 'zh' ? `复制维护窗 ${window.name}` : `Copy maintenance window ${window.name}`}
                          size="sm"
                          variant="accent"
                          onClick={() => void handleCopyWindow(window)}
                        />
                        <ActionIconButton
                          icon={Trash2}
                          label={language === 'zh' ? `删除维护窗 ${window.name}` : `Delete maintenance window ${window.name}`}
                          size="sm"
                          variant="danger"
                          onClick={() => void handleDeleteWindow(window.id)}
                          disabled={maintenanceCancelingId === window.id}
                        />
                      </ActionIconGroup>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '当前没有维护窗。' : 'No maintenance windows found.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-4">
          <Pagination
            currentPage={page}
            totalItems={total}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(value) => {
              setPage(1);
              setPageSize(value);
            }}
            onPageChange={setPage}
            language={language}
          />
        </div>

      </div>
      </div>
    </div>

      <AnimatePresence>
        {showMaintenanceModal ? (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeMaintenanceModal();
              }
            }}
          >
            <motion.div
              className="relative max-h-[90vh] w-full max-w-4xl overflow-auto rounded-[24px] bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-[0_32px_80px_rgba(11,35,64,0.22)]"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{language === 'zh' ? '新建维护期' : 'New Maintenance Window'}</p>
                  <h3 className="mt-2 text-xl font-semibold text-[#164e63]">{language === 'zh' ? '按条件定义或资源对象创建维护期' : 'Create a maintenance window by conditions or resource objects'}</h3>
                </div>
                <button title={language === 'zh' ? '关闭弹层' : 'Close modal'} onClick={closeMaintenanceModal} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-5 px-6 py-6">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <label className="text-sm text-black/65">
                    <span>{language === 'zh' ? '维护名称' : 'Window Name'}</span>
                    <input value={maintenanceForm.name} onChange={(e) => updateMaintenanceField('name', e.target.value)} className={`${alertInputClass} mt-2 rounded-xl px-3 py-2`} />
                  </label>
                  <div className="text-sm text-black/65">
                    <span>{language === 'zh' ? '覆盖方式' : 'Targeting Mode'}</span>
                    <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <button
                        type="button"
                        onClick={() => updateSelectionMode('conditions')}
                        className={`rounded-2xl border px-4 py-3 text-left transition ${maintenanceForm.selection_mode === 'conditions' ? 'border-[#06b6d4] bg-[#ecfeff] text-[#164e63]' : 'border-black/10 bg-white text-black/55 hover:bg-black/[0.02]'}`}
                      >
                        <p className="text-sm font-semibold">{language === 'zh' ? '条件定义' : 'Condition Rules'}</p>
                        <p className="mt-1 text-xs text-black/45">{language === 'zh' ? '按多行条件定义匹配范围' : 'Build the scope with multiple condition rows'}</p>
                      </button>
                      <button
                        type="button"
                        onClick={() => updateSelectionMode('resources')}
                        className={`rounded-2xl border px-4 py-3 text-left transition ${maintenanceForm.selection_mode === 'resources' ? 'border-[#06b6d4] bg-[#ecfeff] text-[#164e63]' : 'border-black/10 bg-white text-black/55 hover:bg-black/[0.02]'}`}
                      >
                        <p className="text-sm font-semibold">{language === 'zh' ? '资源对象' : 'Resource Objects'}</p>
                        <p className="mt-1 text-xs text-black/45">{language === 'zh' ? '按资源勾选多个设备' : 'Select multiple devices by checkbox'}</p>
                      </button>
                    </div>
                  </div>
                </div>

                {maintenanceForm.selection_mode === 'conditions' ? (
                  <div className="rounded-[24px] border border-black/8 bg-[#fbfcfe] p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-[#164e63]">{language === 'zh' ? '条件定义' : 'Condition Rules'}</p>
                        <p className="mt-1 text-xs text-black/45">{language === 'zh' ? '每一行代表一个条件；组合逻辑会作用于整组条件。' : 'Each row is a single condition. The condition logic applies to the full set.'}</p>
                      </div>
                      <div className="flex min-w-[320px] flex-wrap items-end justify-end gap-3">
                        <label className="min-w-[180px] text-sm text-black/60">
                          <span>{language === 'zh' ? '组合逻辑' : 'Condition Logic'}</span>
                          <select
                            value={maintenanceForm.condition_logic}
                            onChange={(e) => updateMaintenanceField('condition_logic', e.target.value as AlertMaintenanceConditionLogic)}
                            className="mt-2 w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-[#164e63] outline-none"
                          >
                            {CONDITION_LOGIC_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>{language === 'zh' ? option.zh : option.en}</option>
                            ))}
                          </select>
                        </label>
                        <button type="button" onClick={addConditionRow} className={alertSecondaryButtonClass}>
                          <Plus size={14} />
                          {language === 'zh' ? '添加条件' : 'Add Condition'}
                        </button>
                      </div>
                    </div>
                    <div className="overflow-hidden rounded-2xl border border-black/8 bg-white">
                      <div className="hidden grid-cols-[160px_180px_minmax(0,1fr)_44px] gap-3 border-b border-black/6 bg-[#f7f9fc] px-4 py-3 text-[11px] font-bold uppercase tracking-[0.14em] text-black/35 lg:grid">
                        <span>{language === 'zh' ? '字段' : 'Field'}</span>
                        <span>{language === 'zh' ? '运算符' : 'Operator'}</span>
                        <span>{language === 'zh' ? '匹配值' : 'Value'}</span>
                        <span className="text-center">#</span>
                      </div>
                      {maintenanceForm.match_conditions.map((condition, index) => (
                        <div key={`${condition.field}-${index}`} className="grid grid-cols-1 gap-3 border-t border-black/6 px-4 py-4 first:border-t-0 lg:grid-cols-[160px_180px_minmax(0,1fr)_44px] lg:items-center">
                          <label className="text-sm text-black/60 lg:text-[#164e63]">
                            <span className="mb-2 block lg:hidden">{language === 'zh' ? '字段' : 'Field'}</span>
                            <select
                              value={condition.field}
                              onChange={(e) => updateCondition(index, { field: e.target.value as AlertMaintenanceConditionField })}
                              className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-[#164e63] outline-none"
                            >
                              <option value="alert_description">{fieldLabel('alert_description', language)}</option>
                              <option value="alert_ip">{fieldLabel('alert_ip', language)}</option>
                              <option value="alert_level">{fieldLabel('alert_level', language)}</option>
                            </select>
                          </label>
                          <label className="text-sm text-black/60 lg:text-[#164e63]">
                            <span className="mb-2 block lg:hidden">{language === 'zh' ? '运算符' : 'Operator'}</span>
                            <select
                              value={condition.operator}
                              onChange={(e) => updateCondition(index, { operator: e.target.value as AlertMaintenanceConditionOperator })}
                              className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-[#164e63] outline-none"
                            >
                              {CONDITION_OPERATOR_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>{language === 'zh' ? option.zh : option.en}</option>
                              ))}
                            </select>
                          </label>
                          <label className="text-sm text-black/60 lg:text-[#164e63]">
                            <span className="mb-2 block lg:hidden">{language === 'zh' ? '匹配值' : 'Value'}</span>
                            {condition.field === 'alert_level' ? (
                              <select
                                value={condition.value}
                                onChange={(e) => updateCondition(index, { value: e.target.value })}
                                className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-[#164e63] outline-none"
                              >
                                <option value="">{language === 'zh' ? '选择告警等级' : 'Select Severity'}</option>
                                {ALERT_SEVERITY_OPTIONS.map((severity) => (
                                  <option key={severity} value={severity}>{severityLabel(severity, language)}</option>
                                ))}
                              </select>
                            ) : (
                              <input
                                value={condition.value}
                                onChange={(e) => updateCondition(index, { value: e.target.value })}
                                placeholder={fieldPlaceholder(condition.field, language)}
                                className={`${alertInputClass} rounded-xl px-3 py-2`}
                              />
                            )}
                          </label>
                          <div className="flex items-end lg:justify-center">
                            <ActionIconButton
                              type="button"
                              icon={Trash2}
                              label={language === 'zh' ? '删除当前条件' : 'Remove condition'}
                              variant="danger"
                              onClick={() => removeConditionRow(index)}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-black/8 bg-[#fbfcfe] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-[#164e63]">{language === 'zh' ? '资源对象' : 'Resource Objects'}</p>
                        <p className="mt-1 text-xs text-black/45">{language === 'zh' ? '点击“关联资源”后可按名称、SN、管理IP搜索，并勾选多个设备。' : 'Use “Link Resources” to search by name, serial number, or management IP, then check multiple devices.'}</p>
                      </div>
                      <button type="button" onClick={openAssetPicker} className={alertSecondaryButtonClass}>
                        <Search size={14} />
                        {language === 'zh' ? '关联资源' : 'Link Resources'}
                      </button>
                    </div>
                    <div className="mt-4 rounded-2xl border border-dashed border-black/10 bg-white p-4">
                      {selectedAssets.length ? (
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          {selectedAssets.map((device) => (
                            <div key={device.id} className="rounded-2xl border border-[#d8e1eb] bg-[#fbfcfe] px-4 py-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-semibold text-[#164e63]">{device.hostname || (language === 'zh' ? '未命名资产' : 'Unnamed Asset')}</p>
                                  <p className="mt-1 font-mono text-xs text-black/45">{device.ip_address}</p>
                                </div>
                                <button type="button" onClick={() => removeSelectedAsset(device.ip_address)} className="rounded-xl border border-black/10 px-2.5 py-1 text-xs font-semibold text-black/45 hover:bg-black/[0.03]">
                                  {language === 'zh' ? '移除' : 'Remove'}
                                </button>
                              </div>
                              <div className="mt-2 flex flex-wrap gap-3 text-xs text-black/45">
                                <span>{`SN ${device.sn || '--'}`}</span>
                                <span>{language === 'zh' ? `站点 ${device.site || '未分组'}` : `Site ${device.site || 'Unassigned'}`}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="text-sm text-black/40">
                          {language === 'zh' ? '尚未选择资源对象。' : 'No resource objects selected yet.'}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div>
                    <span className="text-sm text-black/65">{language === 'zh' ? '开始时间' : 'Start Time'}</span>
                    <DateTimePicker value={maintenanceForm.starts_at} onChange={(v) => updateMaintenanceField('starts_at', v)} language={language} className="mt-2" />
                  </div>
                  <div>
                    <span className="text-sm text-black/65">{language === 'zh' ? '结束时间' : 'End Time'}</span>
                    <DateTimePicker value={maintenanceForm.ends_at} onChange={(v) => updateMaintenanceField('ends_at', v)} language={language} className="mt-2" />
                  </div>
                </div>

                <label className="block text-sm text-black/65">
                  <span>{language === 'zh' ? '维护原因' : 'Reason'}</span>
                  <textarea value={maintenanceForm.reason} onChange={(e) => updateMaintenanceField('reason', e.target.value)} rows={4} className={`${alertInputClass} mt-2 min-h-[112px] resize-y`} />
                </label>

                <div>
                  <p className="text-sm text-black/65">{language === 'zh' ? '通知联系人' : 'Notify Contacts'}</p>
                  <div className="mt-2 grid max-h-[220px] grid-cols-1 gap-2 overflow-auto rounded-2xl border border-black/10 p-3 md:grid-cols-2">
                    {users.map((user) => {
                      const checked = maintenanceForm.notify_user_ids.includes(String(user.id));
                      return (
                        <label key={String(user.id)} className="flex items-center gap-3 rounded-xl border border-black/6 px-3 py-2 text-sm text-black/65 hover:bg-black/[0.02]">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => updateMaintenanceField(
                              'notify_user_ids',
                              e.target.checked
                                ? [...maintenanceForm.notify_user_ids, String(user.id)]
                                : maintenanceForm.notify_user_ids.filter((id) => id !== String(user.id)),
                            )}
                          />
                          <span>{user.username}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>

              <div className="flex justify-end gap-2 border-t border-black/5 px-6 py-4">
                <button onClick={closeMaintenanceModal} className={alertSecondaryButtonClass}>
                  {language === 'zh' ? '取消' : 'Cancel'}
                </button>
                <button disabled={maintenanceSubmitting} onClick={() => void handleCreateMaintenance()} className={alertPrimaryButtonClass}>
                  {maintenanceSubmitting ? (language === 'zh' ? '创建中...' : 'Creating...') : (language === 'zh' ? '创建维护期' : 'Create Window')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {showAssetPicker ? (
          <motion.div
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/45 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeAssetPicker();
              }
            }}
          >
            <motion.div
              className="relative max-h-[88vh] w-full max-w-3xl overflow-hidden rounded-[24px] bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-[0_32px_80px_rgba(11,35,64,0.22)]"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{language === 'zh' ? '关联资源' : 'Link Resources'}</p>
                  <h3 className="mt-2 text-xl font-semibold text-[#164e63]">{language === 'zh' ? '搜索设备并勾选多个资源对象' : 'Search devices and check multiple resource objects'}</h3>
                </div>
                <button title={language === 'zh' ? '关闭弹层' : 'Close modal'} onClick={closeAssetPicker} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-4 px-6 py-6">
                <label className="relative block">
                  <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/40" />
                  <input
                    autoFocus
                    value={assetSearchQuery}
                    onChange={(e) => setAssetSearchQuery(e.target.value)}
                    placeholder={language === 'zh' ? '输入设备名称、SN 或管理IP' : 'Search by device name, serial number, or management IP'}
                    className={`${alertInputClass} rounded-xl py-3 pl-9 pr-3`}
                  />
                </label>

                <div className="rounded-2xl border border-black/8 bg-[#fbfcfe] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-[#164e63]">{language === 'zh' ? `已选资源 ${assetPickerSelection.length} 个` : `${assetPickerSelection.length} resources selected`}</p>
                    {pickerSelectedAssets.length ? (
                      <div className="flex flex-wrap gap-2">
                        {pickerSelectedAssets.map((device) => (
                          <span key={device.id} className="inline-flex items-center rounded-full bg-white px-3 py-1 text-xs font-semibold text-[#36506c] shadow-sm">
                            {device.hostname || device.ip_address}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="rounded-2xl border border-black/8 bg-[#fbfcfe]">
                  {!assetSearchQuery.trim() ? (
                    <div className="px-5 py-10 text-center text-sm text-black/40">
                      {language === 'zh' ? '输入关键字后开始搜索设备。' : 'Enter a keyword to search devices.'}
                    </div>
                  ) : assetSearchLoading ? (
                    <div className="px-5 py-10 text-center text-sm text-black/40">
                      {language === 'zh' ? '正在搜索资产...' : 'Searching devices...'}
                    </div>
                  ) : assetSearchResults.length > 0 ? (
                    <div className="max-h-[420px] overflow-auto p-2">
                      {assetSearchResults.map((device) => {
                        const checked = assetPickerSelection.includes(device.ip_address);
                        return (
                          <label key={device.id} className={`flex cursor-pointer items-start gap-4 rounded-2xl px-4 py-3 transition ${checked ? 'bg-white' : 'hover:bg-white'}`}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleAssetSelection(device.ip_address)}
                              className="mt-1"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-semibold text-[#164e63]">{device.hostname || (language === 'zh' ? '未命名资产' : 'Unnamed Asset')}</p>
                                  <p className="mt-1 font-mono text-xs text-black/45">{device.ip_address}</p>
                                </div>
                                {checked ? <Check size={16} className="text-[#2b6b8f]" /> : null}
                              </div>
                              <div className="mt-2 flex flex-wrap gap-3 text-xs text-black/40">
                                <span>{`SN ${device.sn || '--'}`}</span>
                                <span>{language === 'zh' ? `站点 ${device.site || '未分组'}` : `Site ${device.site || 'Unassigned'}`}</span>
                                <span>{language === 'zh' ? `平台 ${device.platform || '--'}` : `Platform ${device.platform || '--'}`}</span>
                              </div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="px-5 py-10 text-center text-sm text-black/40">
                      {language === 'zh' ? '没有搜索到匹配设备。' : 'No matching devices found.'}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-2 border-t border-black/5 px-6 py-4">
                <button onClick={closeAssetPicker} className={alertSecondaryButtonClass}>
                  {language === 'zh' ? '取消' : 'Cancel'}
                </button>
                <button onClick={confirmAssetSelection} className={alertPrimaryButtonClass}>
                  {language === 'zh' ? '确认关联' : 'Confirm Selection'}
                </button>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence>
        {selectedWindow ? (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeSelectedWindow();
              }
            }}
          >
            <motion.div
              className="relative max-h-[90vh] w-full max-w-3xl overflow-auto rounded-[24px] bg-white/94 dark:bg-[#1e293b]/94 backdrop-blur-xl border border-white/20 dark:border-white/5 shadow-[0_32px_80px_rgba(11,35,64,0.22)]"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <div className="flex items-start justify-between gap-4 border-b border-black/5 px-6 py-5">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{language === 'zh' ? '维护期详情' : 'Maintenance Detail'}</p>
                  <h3 className="mt-2 text-xl font-semibold text-[#164e63]">{selectedWindow.name}</h3>
                  <div className="mt-3">
                    <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-bold uppercase ${maintenanceBadgeClass(selectedWindow.runtime_status)}`}>
                      {maintenanceStatusLabel(selectedWindow.runtime_status, language)}
                    </span>
                  </div>
                </div>
                <button title={language === 'zh' ? '关闭详情' : 'Close detail'} onClick={closeSelectedWindow} className="rounded-xl border border-black/10 p-2 text-black/55 hover:bg-black/[0.03]">
                  <X size={16} />
                </button>
              </div>

              <div className="space-y-5 px-6 py-6">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <div className="rounded-2xl bg-[#f7f8fb] p-4 text-sm text-black/65">
                    <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{language === 'zh' ? '时间信息' : 'Schedule'}</p>
                    <div className="mt-3 space-y-2">
                      <p><span className="text-black/35">{language === 'zh' ? '覆盖方式' : 'Mode'}:</span> {selectedWindow.selection_mode === 'conditions' ? (language === 'zh' ? '条件定义' : 'Condition Rules') : (language === 'zh' ? '资源对象' : 'Resource Objects')}</p>
                      {selectedWindow.selection_mode === 'conditions' ? <p><span className="text-black/35">{language === 'zh' ? '组合逻辑' : 'Condition Logic'}:</span> {conditionLogicLabel(selectedWindow.condition_logic, language)}</p> : null}
                      <p><span className="text-black/35">{language === 'zh' ? '开始' : 'Start'}:</span> {formatTs(selectedWindow.starts_at)}</p>
                      <p><span className="text-black/35">{language === 'zh' ? '结束' : 'End'}:</span> {formatTs(selectedWindow.ends_at)}</p>
                      <p><span className="text-black/35">{language === 'zh' ? '创建人' : 'Created By'}:</span> {selectedWindow.created_by}</p>
                    </div>
                  </div>

                  <div className="rounded-2xl bg-[#f7f8fb] p-4 text-sm text-black/65">
                    <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{language === 'zh' ? '命中范围' : 'Scope Detail'}</p>
                    {selectedWindow.selection_mode === 'conditions' ? (
                      <div className="mt-3 space-y-2">
                        {(selectedWindow.match_conditions || []).filter((item) => item.value.trim()).map((condition) => (
                          <p key={condition.field}>{conditionSummary(condition, language)}</p>
                        ))}
                        <p><span className="text-black/35">{language === 'zh' ? '最近命中' : 'Recent Matches'}:</span> {selectedWindow.last_match_count || 0}</p>
                      </div>
                    ) : (
                      <div className="mt-3 space-y-2">
                        {(selectedWindow.target_ips || (selectedWindow.target_ip ? [selectedWindow.target_ip] : [])).map((ip) => (
                          <p key={ip}><span className="font-mono">{ip}</span>{assetByIp.get(ip)?.hostname ? ` / ${assetByIp.get(ip)?.hostname}` : ''}</p>
                        ))}
                        <p><span className="text-black/35">{language === 'zh' ? '资源数量' : 'Resource Count'}:</span> {(selectedWindow.target_ips || (selectedWindow.target_ip ? [selectedWindow.target_ip] : [])).length}</p>
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-black/35">{language === 'zh' ? '维护原因' : 'Reason'}</p>
                  <div className="mt-2 rounded-2xl border border-black/8 bg-white p-4 text-sm leading-6 text-black/70">
                    {selectedWindow.reason || (language === 'zh' ? '未填写维护原因。' : 'No maintenance reason provided.')}
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-end gap-2 border-t border-black/5 px-6 py-4">
                <ActionButton icon={Copy} variant="accent" size="md" onClick={() => void handleCopyWindow(selectedWindow)}>
                  {language === 'zh' ? '复制信息' : 'Copy'}
                </ActionButton>
                {selectedWindow.runtime_status !== 'expired' && selectedWindow.runtime_status !== 'cancelled' ? (
                  <button onClick={() => void handleCancelWindow(selectedWindow.id)} disabled={maintenanceCancelingId === selectedWindow.id} className={alertSecondaryButtonClass}>
                    {language === 'zh' ? '取消维护期' : 'Cancel'}
                  </button>
                ) : null}
                <ActionButton icon={Trash2} variant="danger" size="md" onClick={() => void handleDeleteWindow(selectedWindow.id)} disabled={maintenanceCancelingId === selectedWindow.id}>
                  {language === 'zh' ? '删除' : 'Delete'}
                </ActionButton>
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
};

export default AlertMaintenanceTab;
