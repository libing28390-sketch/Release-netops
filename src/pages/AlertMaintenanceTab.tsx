import { DataTable } from '../components/DataTable';
import React, { useEffect, useMemo, useState, useRef } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Check, Copy, Eye, Plus, RefreshCw, Search, Trash2, Wrench } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import DateTimePicker from '../components/DateTimePicker';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';
import { FormDialogShell, FormSection } from '../components/ui/FormLayout';
import { SelectField, TextField } from '../components/ui/FormField';
import { ListSearchInput, ListToolbar } from '../components/ui/TableListControls';
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
import { ApiError, authHeaders } from '../api/http';
import {
  cancelAlertMaintenanceWindow,
  createAlertMaintenanceWindow,
  deleteAlertMaintenanceWindow,
  listAlertMaintenanceWindows,
} from './alertMaintenanceApi';
import {
  alertPanelClass,
  alertPrimaryButtonClass,
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

import { TableActionCell, TableActionHeader } from '../components/ui/TableActionColumn';
import type { TableExportData } from '../components/ui/TableExportMenu';
import { fetchAllPaginatedItems } from '../utils/pagination';
type RuntimeFilter = 'all' | AlertMaintenanceWindow['runtime_status'];
type MaintenanceLoadIssue = 'auth' | 'permission' | 'request';

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

const maintenanceIssueForError = (error: unknown): MaintenanceLoadIssue => {
  if (error instanceof ApiError && error.status === 401) return 'auth';
  if (error instanceof ApiError && error.status === 403) return 'permission';
  return 'request';
};

const maintenanceErrorMessage = (
  error: unknown,
  language: string,
  action: 'load' | 'create' | 'cancel' | 'delete',
) => {
  if (error instanceof ApiError && error.status === 401) {
    return language === 'zh' ? '登录状态已失效，请重新登录后重试。' : 'Your session expired. Sign in again and retry.';
  }
  if (error instanceof ApiError && error.status === 403) {
    if (action === 'load') {
      return language === 'zh' ? '你没有权限查看维护期。' : 'You do not have permission to view maintenance windows.';
    }
    return language === 'zh' ? '你没有权限执行此维护期操作。' : 'You do not have permission to perform this maintenance action.';
  }
  if (error instanceof Error && error.message) return error.message;
  const messages = {
    zh: { load: '加载维护期失败', create: '创建维护期失败', cancel: '取消维护期失败', delete: '删除维护期失败' },
    en: { load: 'Failed to load maintenance windows', create: 'Failed to create maintenance window', cancel: 'Failed to cancel maintenance window', delete: 'Failed to delete maintenance window' },
  };
  return messages[language === 'zh' ? 'zh' : 'en'][action];
};

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
  const [loadIssue, setLoadIssue] = useState<MaintenanceLoadIssue | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
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
      const resp = await fetch(`/api/devices?${params.toString()}`, { headers: authHeaders() });
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
      const resp = await fetch(`/api/devices?${params.toString()}`, { headers: authHeaders() });
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
      const data: AlertMaintenanceListResponse = await listAlertMaintenanceWindows(params);
      const items = data.items || [];
      setWindows(items);
      setTotal(data.total && data.total > 0 ? data.total : items.length);
      setLoadIssue(null);
      if (selectedWindowId && !items.some((item) => item.id === selectedWindowId)) {
        setSelectedWindowId(null);
      }
    } catch (error) {
      console.error(error);
      setLoadIssue(maintenanceIssueForError(error));
      showToast(maintenanceErrorMessage(error, language, 'load'), 'error');
    } finally {
      setLoading(false);
    }
  };

  const exportAllMaintenanceWindows = async (): Promise<TableExportData> => {
    const params = new URLSearchParams({ status: statusFilter, search: searchQuery });
    const items = await fetchAllPaginatedItems<AlertMaintenanceWindow>('/api/alerts/maintenance-windows', params, 100);

    const scopeValue = (window: AlertMaintenanceWindow) => {
      if ((window.selection_mode || 'resources') === 'resources') {
        const targets = window.target_ips || (window.target_ip ? [window.target_ip] : []);
        const firstTarget = targets[0] || '--';
        const firstAsset = assetByIp.get(firstTarget);
        return [firstTarget, firstAsset?.hostname || (targets.length > 1 ? `+${targets.length - 1}` : '--')]
          .filter(Boolean).join(' — ');
      }
      const activeConditions = (window.match_conditions || []).filter((item) => item.value.trim());
      return [
        conditionLogicLabel(window.condition_logic, language),
        activeConditions[0] ? conditionSummary(activeConditions[0], language) : '--',
        activeConditions.length > 1 ? `+${activeConditions.length - 1}` : '',
      ].filter(Boolean).join(' — ');
    };

    return {
      headers: language === 'zh'
        ? ['维护名称', '原因', '作用范围', '开始时间', '结束时间', '状态', '创建人']
        : ['Name', 'Reason', 'Scope', 'Start Time', 'End Time', 'Status', 'Created By'],
      rows: items.map((window) => [
        window.name || '',
        window.reason || (language === 'zh' ? '未填写原因' : 'No reason'),
        scopeValue(window),
        formatTs(window.starts_at),
        formatTs(window.ends_at),
        maintenanceStatusLabel(window.runtime_status, language),
        window.created_by || '',
      ]),
    };
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
      await createAlertMaintenanceWindow(payload);
      showToast(language === 'zh' ? '维护窗已创建' : 'Maintenance window created', 'success');
      closeMaintenanceModal();
      setPage(1);
      await loadMaintenanceWindows();
    } catch (error) {
      showToast(maintenanceErrorMessage(error, language, 'create'), 'error');
    } finally {
      setMaintenanceSubmitting(false);
    }
  };

  const handleCancelWindow = async (windowId: string) => {
    setMaintenanceCancelingId(windowId);
    try {
      await cancelAlertMaintenanceWindow(windowId, currentUsername);
      showToast(language === 'zh' ? '维护窗已取消' : 'Maintenance window cancelled', 'success');
      await loadMaintenanceWindows();
    } catch (error) {
      showToast(maintenanceErrorMessage(error, language, 'cancel'), 'error');
    } finally {
      setMaintenanceCancelingId(null);
    }
  };

  const handleDeleteWindow = async (windowId: string) => {
    setMaintenanceCancelingId(windowId);
    try {
      await deleteAlertMaintenanceWindow(windowId, currentUsername);
      showToast(language === 'zh' ? '维护窗已删除' : 'Maintenance window deleted', 'success');
      setSelectedWindowId((prev) => (prev === windowId ? null : prev));
      await loadMaintenanceWindows();
    } catch (error) {
      showToast(maintenanceErrorMessage(error, language, 'delete'), 'error');
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
        <div className="nx-data-table-cell--wrap max-w-[240px]">
          <div className="break-words font-mono">{firstTarget}</div>
          <div className="mt-1 text-xs text-black/40">
            {firstAsset?.hostname || (targets.length > 1 ? `+${targets.length - 1}` : '--')}
          </div>
        </div>
      );
    }

    const activeConditions = (window.match_conditions || []).filter((item) => item.value.trim());
    return (
      <div className="nx-data-table-cell--wrap max-w-[240px] space-y-1">
        <div className="text-xs font-semibold text-[#164e63] dark:text-[var(--app-text)]">{conditionLogicLabel(window.condition_logic, language)}</div>
        <div className="line-clamp-2 text-xs text-black/45">{activeConditions[0] ? conditionSummary(activeConditions[0], language) : '--'}</div>
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
            <button onClick={openCreate} className={alertPrimaryButtonClass}>
              <Plus size={14} />
              {language === 'zh' ? '新建维护期' : 'New Window'}
            </button>
          </>
        }
      />

      <div className="flex-1 flex flex-col overflow-hidden px-6 py-5 min-h-0">
      <div className={`${alertPanelClass} flex-1 min-h-0 flex flex-col overflow-hidden`}>
        <ListToolbar className="min-w-0 flex-col items-stretch gap-3 border-b border-black/5 px-4 py-3 sm:px-5 lg:flex-row lg:items-center">
          <div className="grid min-w-0 flex-1 gap-2 lg:grid-cols-[minmax(220px,1fr)_auto]">
            <ListSearchInput
              language={language}
              className="w-full min-w-0"
              aria-label={language === 'zh' ? '搜索维护期名称、资源 IP、描述、执行目标或创建人' : 'Search maintenance window name, resource IP, description, execution target, or creator'}
              value={searchQuery}
              onChange={(e) => {
                setPage(1);
                setSearchQuery(e.target.value);
              }}
              onClear={() => {
                setPage(1);
                setSearchQuery('');
              }}
              placeholder={language === 'zh' ? '搜索名称、资源 IP、描述、执行目标、创建人' : 'Search name, resource IP, description, execution target, creator'}
            />
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <select
                aria-label={language === 'zh' ? '按状态筛选维护期' : 'Filter maintenance windows by status'}
                title={language === 'zh' ? '按状态筛选维护期' : 'Filter maintenance windows by status'}
                value={statusFilter}
                onChange={(e) => {
                  setPage(1);
                  setStatusFilter(e.target.value as RuntimeFilter);
                }}
                className="min-h-9 min-w-0 flex-1 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 text-sm text-[var(--ui-fg)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] sm:flex-none"
              >
                <option value="all">{language === 'zh' ? '全部状态' : 'All Status'}</option>
                <option value="active">{language === 'zh' ? '生效中' : 'Active'}</option>
                <option value="scheduled">{language === 'zh' ? '待生效' : 'Scheduled'}</option>
                <option value="expired">{language === 'zh' ? '已过期' : 'Expired'}</option>
                <option value="cancelled">{language === 'zh' ? '已取消' : 'Cancelled'}</option>
              </select>
              <ActionIconButton
                icon={RefreshCw}
                label={language === 'zh' ? '刷新维护期列表' : 'Refresh maintenance windows'}
                size="md"
                iconClassName={loading ? 'animate-spin' : ''}
                className="shrink-0"
                onClick={() => void loadMaintenanceWindows()}
              />
            </div>
          </div>
        </ListToolbar>

        <div className="alert-management-table-scroll flex-1 min-h-0 overflow-auto custom-scrollbar border-b border-black/5">
          <DataTable exportConfig={{ filename: 'alert-maintenance-windows', language: language === 'zh' ? 'zh' : 'en', disabled: loading || windows.length === 0, exportData: exportAllMaintenanceWindows }} className="alert-management-table text-left">
            <thead className="sticky top-0 z-10">
              <tr className="border-y border-black/5 bg-[#f8fafc] text-[11px] font-bold uppercase tracking-[0.16em] text-black/40">
                <th className="min-w-[160px] px-5 py-3">{language === 'zh' ? '维护期' : 'Window'}</th>
                <th className="min-w-[220px] px-5 py-3">{language === 'zh' ? '描述' : 'Description'}</th>
                <th className="min-w-[240px] px-5 py-3">{language === 'zh' ? '执行目标' : 'Execution Target'}</th>
                <th className="min-w-[170px] whitespace-nowrap px-5 py-3">{language === 'zh' ? '开始时间' : 'Start Time'}</th>
                <th className="min-w-[170px] whitespace-nowrap px-5 py-3">{language === 'zh' ? '结束时间' : 'End Time'}</th>
                <th className="min-w-[120px] px-5 py-3">{language === 'zh' ? '状态' : 'Status'}</th>
                <th className="min-w-[140px] px-5 py-3">{language === 'zh' ? '创建人' : 'Creator'}</th>
                <TableActionHeader className="min-w-[120px] whitespace-nowrap px-5 py-3">{language === 'zh' ? '操作' : 'Actions'}</TableActionHeader>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '正在加载维护窗...' : 'Loading maintenance windows...'}
                  </td>
                </tr>
              ) : loadIssue ? (
                <tr>
                  <td colSpan={8} role="alert" className="px-5 py-12 text-center text-sm text-rose-700">
                    {loadIssue === 'auth'
                      ? (language === 'zh' ? '登录状态已失效，请重新登录后重试。' : 'Your session expired. Sign in again and retry.')
                      : loadIssue === 'permission'
                        ? (language === 'zh' ? '你没有权限查看维护期。' : 'You do not have permission to view maintenance windows.')
                        : (language === 'zh' ? '加载维护期失败，请重试。' : 'Unable to load maintenance windows. Retry.')}
                  </td>
                </tr>
              ) : windows.length > 0 ? (
                windows.map((window) => (
                  <tr key={window.id} className="border-b border-black/5 hover:bg-black/[0.02]">
                    <td className="px-5 py-4 align-top">
                      <button title={language === 'zh' ? `查看维护窗 ${window.name}` : `View maintenance window ${window.name}`} onClick={() => setSelectedWindowId(window.id)} className="group rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)]/35">
                        <p className="max-w-[220px] truncate text-sm font-semibold text-[#164e63] group-hover:text-[var(--ui-accent)] dark:text-[var(--app-text)]">{window.name}</p>
                        <span className="mt-1 block text-[11px] text-[var(--ui-fg-muted)]">{(window.selection_mode || 'resources') === 'conditions' ? (language === 'zh' ? '条件定义' : 'Condition Rules') : (language === 'zh' ? '资源对象' : 'Resource Objects')}</span>
                      </button>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <div title={window.reason || (language === 'zh' ? '未填写描述' : 'No description')} className="nx-data-table-cell--wrap line-clamp-2 max-w-[360px] text-sm leading-5 text-[var(--ui-fg-muted)]">
                        {window.reason || (language === 'zh' ? '未填写描述' : 'No description')}
                      </div>
                    </td>
                    <td className="px-5 py-4 align-top">{renderWindowScope(window)}</td>
                    <td className="whitespace-nowrap px-5 py-4 align-top text-xs tabular-nums text-[var(--ui-fg-muted)]">{formatTs(window.starts_at)}</td>
                    <td className="whitespace-nowrap px-5 py-4 align-top text-xs tabular-nums text-[var(--ui-fg-muted)]">{formatTs(window.ends_at)}</td>
                    <td className="px-5 py-4 align-top">
                      <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${maintenanceBadgeClass(window.runtime_status)}`}>
                        {maintenanceStatusLabel(window.runtime_status, language)}
                      </span>
                    </td>
                    <td className="px-5 py-4 align-top">
                      <span title={window.created_by} className="block max-w-[160px] truncate text-sm text-[var(--ui-fg-muted)]">{window.created_by}</span>
                    </td>
                    <TableActionCell className="px-5 py-4 align-top">
                      <ActionIconGroup label={language === 'zh' ? '维护窗操作' : 'Maintenance window actions'}>
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
                    </TableActionCell>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-black/40">
                    {language === 'zh' ? '当前没有维护窗。' : 'No maintenance windows found.'}
                  </td>
                </tr>
              )}
            </tbody>
          </DataTable>
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
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3 backdrop-blur-sm sm:p-4"
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
              className="w-full max-w-5xl"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <FormDialogShell
                title={language === 'zh' ? '新建维护期' : 'New Maintenance Window'}
                description={language === 'zh' ? '按条件定义或资源对象创建维护期，并设置静默时段与通知联系人。' : 'Create a maintenance window by conditions or selected resources, then set its schedule and contacts.'}
                onClose={closeMaintenanceModal}
                language={language === 'zh' ? 'zh' : 'en'}
                widthClassName="max-w-5xl"
                className="h-[min(90vh,900px)]"
                bodyClassName="space-y-4"
                actions={(
                  <div className="flex w-full flex-wrap justify-end gap-2 px-5 py-3">
                    <ActionButton variant="default" onClick={closeMaintenanceModal}>
                      {language === 'zh' ? '取消' : 'Cancel'}
                    </ActionButton>
                    <ActionButton variant="accent" disabled={maintenanceSubmitting} onClick={() => void handleCreateMaintenance()}>
                      {maintenanceSubmitting ? (language === 'zh' ? '创建中...' : 'Creating...') : (language === 'zh' ? '创建维护期' : 'Create Window')}
                    </ActionButton>
                  </div>
                )}
              >

              <div>
                <FormSection
                  title={language === 'zh' ? '维护期设置' : 'Window Settings'}
                  description={language === 'zh' ? '选择维护范围的定义方式。' : 'Choose how the maintenance scope is defined.'}
                  contentClassName="grid grid-cols-1 gap-4 md:grid-cols-2"
                >
                  <TextField
                    label={language === 'zh' ? '维护名称' : 'Window Name'}
                    value={maintenanceForm.name}
                    onChange={(value) => updateMaintenanceField('name', value)}
                  />
                  <div className="text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
                    <span>{language === 'zh' ? '覆盖方式' : 'Targeting Mode'}</span>
                    <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <button
                        type="button"
                        aria-pressed={maintenanceForm.selection_mode === 'conditions'}
                        onClick={() => updateSelectionMode('conditions')}
                        className={`rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] ${maintenanceForm.selection_mode === 'conditions' ? 'border-[var(--ui-accent)] bg-[var(--ui-accent-subtle)] text-[var(--ui-accent)]' : 'border-[var(--ui-border)] bg-[var(--ui-surface)] text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]'}`}
                      >
                        <span className="block text-sm font-semibold">{language === 'zh' ? '条件定义' : 'Condition Rules'}</span>
                        <span className="mt-1 block text-xs font-normal text-[var(--ui-fg-muted)]">{language === 'zh' ? '按多行条件定义匹配范围' : 'Build the scope with multiple condition rows'}</span>
                      </button>
                      <button
                        type="button"
                        aria-pressed={maintenanceForm.selection_mode === 'resources'}
                        onClick={() => updateSelectionMode('resources')}
                        className={`rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ui-accent)] ${maintenanceForm.selection_mode === 'resources' ? 'border-[var(--ui-accent)] bg-[var(--ui-accent-subtle)] text-[var(--ui-accent)]' : 'border-[var(--ui-border)] bg-[var(--ui-surface)] text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]'}`}
                      >
                        <span className="block text-sm font-semibold">{language === 'zh' ? '资源对象' : 'Resource Objects'}</span>
                        <span className="mt-1 block text-xs font-normal text-[var(--ui-fg-muted)]">{language === 'zh' ? '按资源勾选多个设备' : 'Select multiple devices by checkbox'}</span>
                      </button>
                    </div>
                  </div>
                </FormSection>

                {maintenanceForm.selection_mode === 'conditions' ? (
                  <FormSection
                    title={language === 'zh' ? '条件定义' : 'Condition Rules'}
                    description={language === 'zh' ? '每一行代表一个条件；组合逻辑会作用于整组条件。' : 'Each row is a single condition. The logic applies to the full set.'}
                  >
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                      <div className="flex min-w-0 flex-wrap items-end gap-3 sm:min-w-[320px] sm:justify-end">
                        <SelectField
                          label={language === 'zh' ? '组合逻辑' : 'Condition Logic'}
                          value={maintenanceForm.condition_logic}
                          onChange={(value) => updateMaintenanceField('condition_logic', value as AlertMaintenanceConditionLogic)}
                          options={CONDITION_LOGIC_OPTIONS.map((option) => ({ value: option.value, label: language === 'zh' ? option.zh : option.en }))}
                          language={language === 'zh' ? 'zh' : 'en'}
                          className="min-w-[180px]"
                        />
                        <ActionButton icon={Plus} variant="default" onClick={addConditionRow}>
                          {language === 'zh' ? '添加条件' : 'Add Condition'}
                        </ActionButton>
                      </div>
                    </div>
                    <div className="overflow-hidden rounded-lg border border-[var(--ui-border)]">
                      {maintenanceForm.match_conditions.map((condition, index) => (
                        <div key={`${condition.field}-${index}`} className="grid grid-cols-1 gap-3 border-b border-[var(--ui-border)] p-3 last:border-b-0 lg:grid-cols-[minmax(150px,1fr)_minmax(150px,1fr)_minmax(200px,1.5fr)_auto] lg:items-end">
                          <SelectField
                            label={language === 'zh' ? '字段' : 'Field'}
                            value={condition.field}
                            onChange={(value) => updateCondition(index, { field: value as AlertMaintenanceConditionField })}
                            options={[
                              { value: 'alert_description', label: fieldLabel('alert_description', language) },
                              { value: 'alert_ip', label: fieldLabel('alert_ip', language) },
                              { value: 'alert_level', label: fieldLabel('alert_level', language) },
                            ]}
                            language={language === 'zh' ? 'zh' : 'en'}
                          />
                          <SelectField
                            label={language === 'zh' ? '运算符' : 'Operator'}
                            value={condition.operator}
                            onChange={(value) => updateCondition(index, { operator: value as AlertMaintenanceConditionOperator })}
                            options={CONDITION_OPERATOR_OPTIONS.map((option) => ({ value: option.value, label: language === 'zh' ? option.zh : option.en }))}
                            language={language === 'zh' ? 'zh' : 'en'}
                          />
                          {condition.field === 'alert_level' ? (
                            <SelectField
                              label={language === 'zh' ? '匹配值' : 'Value'}
                              value={condition.value}
                              onChange={(value) => updateCondition(index, { value })}
                              options={ALERT_SEVERITY_OPTIONS.map((severity) => ({ value: severity, label: severityLabel(severity, language) }))}
                              language={language === 'zh' ? 'zh' : 'en'}
                              placeholder={language === 'zh' ? '选择告警等级' : 'Select Severity'}
                            />
                          ) : (
                            <TextField
                              label={language === 'zh' ? '匹配值' : 'Value'}
                              value={condition.value}
                              onChange={(value) => updateCondition(index, { value })}
                              placeholder={fieldPlaceholder(condition.field, language)}
                            />
                          )}
                          <ActionIconButton
                            type="button"
                            icon={Trash2}
                            label={language === 'zh' ? '删除当前条件' : 'Remove condition'}
                            variant="danger"
                            onClick={() => removeConditionRow(index)}
                            className="lg:mb-0.5"
                          />
                        </div>
                      ))}
                    </div>
                  </FormSection>
                ) : (
                  <FormSection
                    title={language === 'zh' ? '资源对象' : 'Resource Objects'}
                    description={language === 'zh' ? '按名称、SN 或管理 IP 搜索并选择多个设备。' : 'Search by name, serial number, or management IP, then select devices.'}
                  >
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                      <span className="text-sm text-[var(--ui-fg-muted)]">{language === 'zh' ? `已关联 ${selectedAssets.length} 个资源对象` : `${selectedAssets.length} resources selected`}</span>
                      <ActionButton icon={Search} variant="default" onClick={openAssetPicker}>
                        {language === 'zh' ? '关联资源' : 'Link Resources'}
                      </ActionButton>
                    </div>
                    {selectedAssets.length ? (
                      <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                        {selectedAssets.map((device) => (
                          <div key={device.id} className="min-w-0 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold text-[var(--ui-fg)]">{device.hostname || (language === 'zh' ? '未命名资产' : 'Unnamed Asset')}</p>
                                <p className="mt-1 break-all font-mono text-xs text-[var(--ui-fg-muted)]">{device.ip_address}</p>
                              </div>
                              <ActionIconButton
                                type="button"
                                icon={Trash2}
                                label={language === 'zh' ? `移除 ${device.hostname || device.ip_address}` : `Remove ${device.hostname || device.ip_address}`}
                                variant="danger"
                                size="sm"
                                onClick={() => removeSelectedAsset(device.ip_address)}
                              />
                            </div>
                            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--ui-fg-muted)]">
                              <span>{`SN ${device.sn || '--'}`}</span>
                              <span>{language === 'zh' ? `站点 ${device.site || '未分组'}` : `Site ${device.site || 'Unassigned'}`}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-[var(--ui-fg-muted)]">{language === 'zh' ? '尚未选择资源对象。' : 'No resource objects selected yet.'}</p>
                    )}
                  </FormSection>
                )}

                <FormSection
                  title={language === 'zh' ? '维护时段' : 'Schedule'}
                  description={language === 'zh' ? '明确维护窗口的起止时间。' : 'Choose when the maintenance window starts and ends.'}
                  contentClassName="grid grid-cols-1 gap-4 md:grid-cols-2"
                >
                  <div className="min-w-0 text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
                    <span>{language === 'zh' ? '开始时间' : 'Start Time'}</span>
                    <DateTimePicker value={maintenanceForm.starts_at} onChange={(value) => updateMaintenanceField('starts_at', value)} language={language} className="mt-1" />
                  </div>
                  <div className="min-w-0 text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
                    <span>{language === 'zh' ? '结束时间' : 'End Time'}</span>
                    <DateTimePicker value={maintenanceForm.ends_at} onChange={(value) => updateMaintenanceField('ends_at', value)} language={language} className="mt-1" />
                  </div>
                </FormSection>

                <FormSection title={language === 'zh' ? '维护原因' : 'Reason'}>
                  <TextField
                    label={language === 'zh' ? '原因说明' : 'Reason details'}
                    value={maintenanceForm.reason}
                    onChange={(value) => updateMaintenanceField('reason', value)}
                    multiline
                    rows={3}
                    controlClassName="min-h-[96px] resize-y"
                  />
                </FormSection>

                <FormSection
                  title={language === 'zh' ? '通知联系人' : 'Notify Contacts'}
                  description={language === 'zh' ? `已选 ${maintenanceForm.notify_user_ids.length} 人` : `${maintenanceForm.notify_user_ids.length} selected`}
                >
                  <div className="grid max-h-[200px] grid-cols-1 gap-2 overflow-auto md:grid-cols-2">
                    {users.map((user) => {
                      const checked = maintenanceForm.notify_user_ids.includes(String(user.id));
                      return (
                        <label key={String(user.id)} className="flex cursor-pointer items-center gap-3 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2 text-sm text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => updateMaintenanceField(
                              'notify_user_ids',
                              e.target.checked
                                ? [...maintenanceForm.notify_user_ids, String(user.id)]
                                : maintenanceForm.notify_user_ids.filter((id) => id !== String(user.id)),
                            )}
                            className="accent-[var(--ui-accent)]"
                          />
                          <span>{user.username}</span>
                        </label>
                      );
                    })}
                  </div>
                </FormSection>
              </div>

              </FormDialogShell>
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
              className="w-full max-w-3xl"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <FormDialogShell
                title={language === 'zh' ? '关联资源' : 'Link Resources'}
                description={language === 'zh' ? '搜索设备并勾选需要静默的资源对象。' : 'Search for devices and select the resource objects to suppress.'}
                onClose={closeAssetPicker}
                language={language === 'zh' ? 'zh' : 'en'}
                widthClassName="max-w-3xl"
                bodyClassName="space-y-4"
                actions={(
                  <div className="flex w-full flex-wrap justify-end gap-2 px-5 py-3">
                    <ActionButton variant="default" onClick={closeAssetPicker}>
                      {language === 'zh' ? '取消' : 'Cancel'}
                    </ActionButton>
                    <ActionButton variant="accent" onClick={confirmAssetSelection}>
                      {language === 'zh' ? '确认关联' : 'Confirm Selection'}
                    </ActionButton>
                  </div>
                )}
              >
                <ListSearchInput
                  language={language}
                  className="w-full"
                  autoFocus
                  aria-label={language === 'zh' ? '搜索设备名称、序列号或管理 IP' : 'Search device name, serial number, or management IP'}
                  value={assetSearchQuery}
                  onChange={(event) => setAssetSearchQuery(event.target.value)}
                  placeholder={language === 'zh' ? '输入设备名称、SN 或管理 IP' : 'Search by device name, serial number, or management IP'}
                />

                <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-[var(--ui-fg)]">{language === 'zh' ? `已选资源 ${assetPickerSelection.length} 个` : `${assetPickerSelection.length} resources selected`}</p>
                    {pickerSelectedAssets.length ? (
                      <div className="flex flex-wrap gap-2">
                        {pickerSelectedAssets.map((device) => (
                          <span key={device.id} className="inline-flex items-center rounded-full border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-1 text-xs font-semibold text-[var(--ui-fg-muted)]">
                            {device.hostname || device.ip_address}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="overflow-hidden rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface)]">
                  {!assetSearchQuery.trim() ? (
                    <div className="px-5 py-10 text-center text-sm text-[var(--ui-fg-muted)]">
                      {language === 'zh' ? '输入关键字后开始搜索设备。' : 'Enter a keyword to search devices.'}
                    </div>
                  ) : assetSearchLoading ? (
                    <div role="status" className="px-5 py-10 text-center text-sm text-[var(--ui-fg-muted)]">
                      {language === 'zh' ? '正在搜索资产...' : 'Searching devices...'}
                    </div>
                  ) : assetSearchResults.length > 0 ? (
                    <div className="max-h-[420px] overflow-auto p-2">
                      {assetSearchResults.map((device) => {
                        const checked = assetPickerSelection.includes(device.ip_address);
                        return (
                          <label key={device.id} className={`flex cursor-pointer items-start gap-3 border-b border-[var(--ui-border)] px-3 py-2.5 last:border-b-0 transition-colors ${checked ? 'bg-[var(--ui-accent-subtle)]' : 'hover:bg-[var(--ui-surface-muted)]'}`}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleAssetSelection(device.ip_address)}
                              className="mt-1 accent-[var(--ui-accent)]"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-semibold text-[var(--ui-fg)]">{device.hostname || (language === 'zh' ? '未命名资产' : 'Unnamed Asset')}</p>
                                  <p className="mt-1 break-all font-mono text-xs text-[var(--ui-fg-muted)]">{device.ip_address}</p>
                                </div>
                                {checked ? <Check size={16} className="text-[var(--ui-accent)]" /> : null}
                              </div>
                              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--ui-fg-muted)]">
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
                    <div className="px-5 py-10 text-center text-sm text-[var(--ui-fg-muted)]">
                      {language === 'zh' ? '没有搜索到匹配设备。' : 'No matching devices found.'}
                    </div>
                  )}
                </div>
              </FormDialogShell>
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
              className="w-full max-w-3xl"
              initial={{ y: 18, opacity: 0, scale: 0.98 }}
              animate={{ y: 0, opacity: 1, scale: 1 }}
              exit={{ y: 18, opacity: 0, scale: 0.98 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
            >
              <FormDialogShell
                title={selectedWindow.name}
                description={(
                  <span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${maintenanceBadgeClass(selectedWindow.runtime_status)}`}>
                    {maintenanceStatusLabel(selectedWindow.runtime_status, language)}
                  </span>
                )}
                onClose={closeSelectedWindow}
                language={language === 'zh' ? 'zh' : 'en'}
                widthClassName="max-w-3xl"
                bodyClassName="space-y-4"
                actions={(
                  <div className="flex w-full flex-wrap items-center justify-end gap-2 px-5 py-3">
                    <ActionButton icon={Copy} variant="accent" size="md" onClick={() => void handleCopyWindow(selectedWindow)}>
                      {language === 'zh' ? '复制信息' : 'Copy'}
                    </ActionButton>
                    {selectedWindow.runtime_status !== 'expired' && selectedWindow.runtime_status !== 'cancelled' ? (
                      <ActionButton variant="default" onClick={() => void handleCancelWindow(selectedWindow.id)} disabled={maintenanceCancelingId === selectedWindow.id}>
                        {language === 'zh' ? '取消维护期' : 'Cancel'}
                      </ActionButton>
                    ) : null}
                    <ActionButton icon={Trash2} variant="danger" size="md" onClick={() => void handleDeleteWindow(selectedWindow.id)} disabled={maintenanceCancelingId === selectedWindow.id}>
                      {language === 'zh' ? '删除' : 'Delete'}
                    </ActionButton>
                  </div>
                )}
              >

              <div>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <FormSection title={language === 'zh' ? '时间信息' : 'Schedule'} className="!mt-0">
                    <div className="space-y-2 text-sm text-[var(--ui-fg)]">
                      <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '覆盖方式' : 'Mode'}:</span> {selectedWindow.selection_mode === 'conditions' ? (language === 'zh' ? '条件定义' : 'Condition Rules') : (language === 'zh' ? '资源对象' : 'Resource Objects')}</p>
                      {selectedWindow.selection_mode === 'conditions' ? <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '组合逻辑' : 'Condition Logic'}:</span> {conditionLogicLabel(selectedWindow.condition_logic, language)}</p> : null}
                      <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '开始' : 'Start'}:</span> {formatTs(selectedWindow.starts_at)}</p>
                      <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '结束' : 'End'}:</span> {formatTs(selectedWindow.ends_at)}</p>
                      <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '创建人' : 'Created By'}:</span> {selectedWindow.created_by}</p>
                    </div>
                  </FormSection>

                  <FormSection title={language === 'zh' ? '命中范围' : 'Scope Detail'} className="!mt-0">
                    {selectedWindow.selection_mode === 'conditions' ? (
                      <div className="space-y-2 text-sm text-[var(--ui-fg)]">
                        {(selectedWindow.match_conditions || []).filter((item) => item.value.trim()).map((condition) => (
                          <p key={condition.field}>{conditionSummary(condition, language)}</p>
                        ))}
                        <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '最近命中' : 'Recent Matches'}:</span> {selectedWindow.last_match_count || 0}</p>
                      </div>
                    ) : (
                      <div className="space-y-2 text-sm text-[var(--ui-fg)]">
                        {(selectedWindow.target_ips || (selectedWindow.target_ip ? [selectedWindow.target_ip] : [])).map((ip) => (
                          <p key={ip}><span className="font-mono">{ip}</span>{assetByIp.get(ip)?.hostname ? ` / ${assetByIp.get(ip)?.hostname}` : ''}</p>
                        ))}
                        <p><span className="text-[var(--ui-fg-muted)]">{language === 'zh' ? '资源数量' : 'Resource Count'}:</span> {(selectedWindow.target_ips || (selectedWindow.target_ip ? [selectedWindow.target_ip] : [])).length}</p>
                      </div>
                    )}
                  </FormSection>
                </div>

                <FormSection title={language === 'zh' ? '维护原因' : 'Reason'}>
                  <div className="text-sm leading-6 text-[var(--ui-fg)]">
                    {selectedWindow.reason || (language === 'zh' ? '未填写维护原因。' : 'No maintenance reason provided.')}
                  </div>
                </FormSection>
              </div>

              </FormDialogShell>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
};

export default AlertMaintenanceTab;
