import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Ban, ChevronDown, GitBranch, Pencil, Plus, RefreshCw, Search, X } from 'lucide-react';
import PageHero from '../../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { apiRequest, ApiError } from '../../api/http';
import {
  createRoutingContextMapping,
  listRoutingContextCandidates,
  listRoutingContextMappings,
  updateRoutingContextMapping,
  type RoutingContextCandidate,
  type RoutingContextMapping,
  type RoutingContextSource,
  type RoutingContextStatus,
  type RoutingContextType,
} from '../../api/ipam';

interface DeviceOption {
  id: string;
  name?: string;
  device_name?: string;
  hostname?: string;
  ip?: string;
  management_ip?: string;
  ip_address?: string;
}

interface AddressSpaceOption {
  id: string;
  name: string;
  kind: RoutingContextType;
  vrf_id: string | null;
  vrf_name: string | null;
}

interface DeviceRoutingContextTabProps {
  language: string;
  t: (key: string) => string;
}

type MappingFormMode = 'create' | 'edit' | null;

interface MappingForm {
  context_source: RoutingContextSource;
  context_type: RoutingContextType;
  local_context_key: string;
  local_context_name: string;
  address_space_id: string;
  status: RoutingContextStatus;
}

const EMPTY_FORM: MappingForm = {
  context_source: 'cli',
  context_type: 'vrf',
  local_context_key: '',
  local_context_name: '',
  address_space_id: '',
  status: 'active',
};

const unwrapItems = <T,>(payload: unknown): T[] => {
  if (Array.isArray(payload)) return payload as T[];
  if (!payload || typeof payload !== 'object') return [];
  const record = payload as { data?: unknown; items?: unknown };
  if (Array.isArray(record.items)) return record.items as T[];
  if (Array.isArray(record.data)) return record.data as T[];
  if (record.data && typeof record.data === 'object') return unwrapItems<T>(record.data);
  return [];
};

const deviceLabel = (device: DeviceOption): string => {
  const name = device.name || device.device_name || device.hostname || device.id;
  const address = device.management_ip || device.ip || device.ip_address;
  return address && address !== name ? `${name} · ${address}` : name;
};

const deviceSearchText = (device: DeviceOption): string => [
  deviceLabel(device),
  device.id,
  device.name,
  device.device_name,
  device.hostname,
  device.management_ip,
  device.ip,
  device.ip_address,
].filter(Boolean).join(' ').toLocaleLowerCase();

const addressSpaceLabel = (space: AddressSpaceOption, zh: boolean): string => (
  space.kind === 'vrf'
    ? `${space.name || space.id} · ${space.vrf_name || space.vrf_id || 'VRF'}`
    : `${space.name || space.id} · ${zh ? '全局' : 'Global'}`
);

const isKnownLocalContextKey = (value: string): boolean => {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return false;
  return !/^unknown(?:[_\s-].*)?$/.test(normalized)
    && !new Set(['none', 'null', 'n/a', 'not available']).has(normalized);
};

const formatSourceDomain = (source: string, zh: boolean): string => {
  const key = source.trim().toLowerCase();
  if (key === 'interface_inventory') return zh ? '接口采集' : 'Interface inventory';
  if (key === 'arp') return zh ? 'ARP 发现' : 'ARP discovery';
  if (key === 'nd') return zh ? 'ND 发现' : 'ND discovery';
  return source;
};

const formatMappingContextTitle = (mapping: RoutingContextMapping, zh: boolean): string => {
  const name = String(mapping.local_context_name || '').trim();
  const key = String(mapping.local_context_key || '').trim();
  if (mapping.context_type === 'global' && (!name || name === '--' || name.toLowerCase() === 'global')) {
    return zh ? '默认全局路由表 (Global)' : 'Default Routing Table (Global)';
  }
  return name || key || (zh ? '未命名路由表' : 'Unnamed context');
};

const formatMappingContextSub = (mapping: RoutingContextMapping, zh: boolean): string | null => {
  const key = String(mapping.local_context_key || '').trim();
  if (!key || key === '--') return null;
  if (mapping.context_type === 'global' && key.toLowerCase() === 'global') {
    return zh ? '全局默认实例' : 'Global instance';
  }
  return key;
};

const displayError = (
  error: unknown,
  zh: boolean,
  fallback: string,
  permissionMessage: string,
): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已过期，请重新登录后重试。' : 'Your session has expired. Sign in and retry.';
    if (error.status === 403) return permissionMessage;
    if (error.status === 409) {
      const conflict = zh
        ? '版本冲突：该映射已被其他人修改，请刷新后重新编辑。'
        : 'Revision conflict: this mapping changed elsewhere. Refresh and edit the latest version.';
      return error.message ? `${conflict} ${error.message}` : conflict;
    }
    return error.message || fallback;
  }
  return error instanceof Error && error.message ? error.message : fallback;
};

const formatTimestamp = (value: string | null, zh: boolean): string => {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const DeviceRoutingContextTab: React.FC<DeviceRoutingContextTabProps> = ({ language }) => {
  const zh = language === 'zh';
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [addressSpaces, setAddressSpaces] = useState<AddressSpaceOption[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [deviceSearchQuery, setDeviceSearchQuery] = useState('');
  const [devicePickerOpen, setDevicePickerOpen] = useState(false);
  const [activeDeviceOption, setActiveDeviceOption] = useState(-1);
  const [lookupsLoading, setLookupsLoading] = useState(true);
  const [lookupsError, setLookupsError] = useState('');
  const [mappings, setMappings] = useState<RoutingContextMapping[]>([]);
  const [candidates, setCandidates] = useState<RoutingContextCandidate[]>([]);
  const [candidateSpaceSelection, setCandidateSpaceSelection] = useState<Record<string, string>>({});
  const [confirmingCandidateKey, setConfirmingCandidateKey] = useState('');
  const [bulkMapping, setBulkMapping] = useState(false);
  const [bulkMappedDone, setBulkMappedDone] = useState(false);
  const [bulkMappingNotice, setBulkMappingNotice] = useState('');
  const [mappingsLoading, setMappingsLoading] = useState(false);
  const [mappingsError, setMappingsError] = useState('');
  const [mutationError, setMutationError] = useState('');
  const [writeDenied, setWriteDenied] = useState(false);
  const [formMode, setFormMode] = useState<MappingFormMode>(null);
  const [editingMapping, setEditingMapping] = useState<RoutingContextMapping | null>(null);
  const [form, setForm] = useState<MappingForm>(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState<RoutingContextMapping | null>(null);
  const mappingRequestId = useRef(0);

  const selectedDevice = useMemo(
    () => devices.find((device) => device.id === selectedDeviceId) || null,
    [devices, selectedDeviceId],
  );
  const filteredDevices = useMemo(() => {
    const query = deviceSearchQuery.trim().toLocaleLowerCase();
    return query ? devices.filter((device) => deviceSearchText(device).includes(query)) : devices;
  }, [devices, deviceSearchQuery]);

  const compatibleAddressSpaces = useMemo(
    () => addressSpaces.filter((space) => space.kind === form.context_type),
    [addressSpaces, form.context_type],
  );

  const selectDevice = (device: DeviceOption) => {
    setWriteDenied(false);
    setSelectedDeviceId(device.id);
    setDeviceSearchQuery('');
    setDevicePickerOpen(false);
    setActiveDeviceOption(-1);
  };

  const handleDeviceSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setDevicePickerOpen(true);
      setActiveDeviceOption((current) => filteredDevices.length === 0
        ? -1
        : current < 0 ? 0 : Math.min(current + 1, filteredDevices.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setDevicePickerOpen(true);
      setActiveDeviceOption((current) => filteredDevices.length === 0
        ? -1
        : current <= 0 ? filteredDevices.length - 1 : current - 1);
    } else if (event.key === 'Enter' && devicePickerOpen) {
      event.preventDefault();
      const device = filteredDevices[activeDeviceOption]
        || (filteredDevices.length === 1 ? filteredDevices[0] : null);
      if (device) selectDevice(device);
    } else if (event.key === 'Escape' && devicePickerOpen) {
      event.preventDefault();
      setDevicePickerOpen(false);
      setActiveDeviceOption(-1);
    }
  };

  const loadLookups = useCallback(async () => {
    setLookupsLoading(true);
    setLookupsError('');
    setMutationError('');
    setWriteDenied(false);
    try {
      const [devicePayload, addressSpacePayload] = await Promise.all([
        apiRequest<unknown>('/api/devices?mode=light'),
        apiRequest<unknown>('/api/ipam/address-spaces'),
      ]);
      const nextDevices = unwrapItems<DeviceOption>(devicePayload).filter((device) => Boolean(device.id));
      const nextAddressSpaces = unwrapItems<AddressSpaceOption>(addressSpacePayload)
        .filter((space) => Boolean(space.id) && (space.kind === 'vrf' || space.kind === 'global'));
      setDevices(nextDevices);
      setAddressSpaces(nextAddressSpaces);
      const urlDeviceId = new URLSearchParams(window.location.search).get('device_id')?.trim() || '';
      if (urlDeviceId && nextDevices.some((device) => device.id === urlDeviceId)) {
        setSelectedDeviceId((current) => current || urlDeviceId);
      }
    } catch (error) {
      setDevices([]);
      setAddressSpaces([]);
      setLookupsError(displayError(
        error,
        zh,
        zh ? '加载设备和地址空间失败，请检查网络后重试。' : 'Failed to load devices and address spaces. Check the connection and retry.',
        zh ? '当前账号没有读取设备或地址空间的权限。' : 'You do not have permission to view devices or address spaces.',
      ));
    } finally {
      setLookupsLoading(false);
    }
  }, [zh]);

  const loadMappings = useCallback(async (deviceId: string) => {
    const requestId = ++mappingRequestId.current;
    if (!deviceId) {
      setMappings([]);
      setCandidates([]);
      setMappingsError('');
      setMappingsLoading(false);
      return;
    }
    setMappingsLoading(true);
    setMappingsError('');
    try {
      const [payload, candidatePayload] = await Promise.all([
        listRoutingContextMappings(deviceId),
        listRoutingContextCandidates(deviceId).catch(() => ({ items: [] as RoutingContextCandidate[] })),
      ]);
      if (requestId !== mappingRequestId.current) return;
      if (!Array.isArray(payload.items)) throw new Error('Invalid routing-context mapping response.');
      setMappings(payload.items);
      setCandidates(Array.isArray(candidatePayload?.items) ? candidatePayload.items : []);
    } catch (error) {
      if (requestId !== mappingRequestId.current) return;
      setMappings([]);
      setCandidates([]);
      if (error instanceof ApiError && error.status === 403) setWriteDenied(true);
      setMappingsError(displayError(
        error,
        zh,
        zh ? '加载设备上下文映射失败，请重试。' : 'Failed to load device context mappings. Please retry.',
        zh ? '当前账号没有查看设备上下文映射的权限。' : 'You do not have permission to view device context mappings.',
      ));
    } finally {
      if (requestId === mappingRequestId.current) setMappingsLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    void loadLookups();
  }, [loadLookups]);

  useEffect(() => {
    void loadMappings(selectedDeviceId);
    return () => { mappingRequestId.current += 1; };
  }, [loadMappings, selectedDeviceId]);

  const openCreateForm = () => {
    setEditingMapping(null);
    setForm({ ...EMPTY_FORM });
    setFormError('');
    setMutationError('');
    setFormMode('create');
  };

  const openEditForm = (mapping: RoutingContextMapping) => {
    setEditingMapping(mapping);
    setForm({
      context_source: mapping.context_source,
      context_type: mapping.context_type,
      local_context_key: mapping.local_context_key,
      local_context_name: mapping.local_context_name || '',
      address_space_id: mapping.address_space_id,
      status: mapping.status,
    });
    setFormError('');
    setMutationError('');
    setFormMode('edit');
  };

  const closeForm = () => {
    if (saving) return;
    setFormMode(null);
    setEditingMapping(null);
    setFormError('');
  };

  const showMutationError = (error: unknown, fallback: string) => {
    if (error instanceof ApiError && error.status === 403) setWriteDenied(true);
    return displayError(
      error,
      zh,
      fallback,
      zh ? '当前账号没有修改设备上下文映射的权限。' : 'You do not have permission to change device context mappings.',
    );
  };

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError('');
    const contextKey = form.local_context_key.trim();
    if (formMode === 'create' && !isKnownLocalContextKey(contextKey)) {
      setFormError(zh
        ? '请输入已明确识别的本地上下文标识；空值和 unknown 不可登记。'
        : 'Enter a known local context key. Empty and unknown contexts cannot be mapped.');
      return;
    }
    if (!selectedDeviceId) {
      setFormError(zh ? '请先选择设备。' : 'Select a device first.');
      return;
    }
    if (!form.address_space_id || !compatibleAddressSpaces.some((space) => space.id === form.address_space_id)) {
      setFormError(zh ? '请选择与上下文类型一致的地址空间。' : 'Select an address space matching the context type.');
      return;
    }
    if (formMode === 'edit' && !editingMapping) return;

    setSaving(true);
    try {
      if (formMode === 'create') {
        await createRoutingContextMapping({
          device_id: selectedDeviceId,
          context_source: form.context_source,
          context_type: form.context_type,
          local_context_key: contextKey,
          local_context_name: form.local_context_name.trim(),
          address_space_id: form.address_space_id,
        });
      } else if (editingMapping) {
        await updateRoutingContextMapping(editingMapping.id, {
          expected_revision: editingMapping.revision,
          address_space_id: form.address_space_id,
          local_context_name: form.local_context_name.trim(),
          status: form.status,
        });
      }
      setFormMode(null);
      setEditingMapping(null);
      setMutationError('');
      await loadMappings(selectedDeviceId);
    } catch (error) {
      const fallback = formMode === 'create'
        ? (zh ? '创建映射失败，请重试。' : 'Failed to create the mapping. Please retry.')
        : (zh ? '更新映射失败，请重试。' : 'Failed to update the mapping. Please retry.');
      setFormError(showMutationError(error, fallback));
      if (error instanceof ApiError && error.status === 409) void loadMappings(selectedDeviceId);
    } finally {
      setSaving(false);
    }
  };

  const candidateRowKey = (candidate: RoutingContextCandidate) => (
    `${candidate.context_source}:${candidate.context_type}:${candidate.local_context_key}`
  );

  const handleConfirmCandidate = async (candidate: RoutingContextCandidate) => {
    if (!selectedDeviceId || !candidate.can_confirm || candidate.context_type === 'unknown') return;
    const key = candidateRowKey(candidate);
    const selectedSpaceId = candidateSpaceSelection[key] || '';
    if (!selectedSpaceId) {
      setMutationError(zh ? '请先为该候选选择目标地址空间。' : 'Select a target address space for this candidate first.');
      return;
    }
    setMutationError('');
    setConfirmingCandidateKey(key);
    try {
      await createRoutingContextMapping({
        device_id: selectedDeviceId,
        context_source: candidate.context_source,
        context_type: candidate.context_type,
        local_context_key: candidate.local_context_key,
        local_context_name: candidate.local_context_name || candidate.local_context_key,
        address_space_id: selectedSpaceId,
      });
      await loadMappings(selectedDeviceId);
    } catch (error) {
      setMutationError(showMutationError(
        error,
        zh ? '确认上下文归属失败，请重试。' : 'Failed to confirm context ownership. Please retry.',
      ));
    } finally {
      setConfirmingCandidateKey('');
    }
  };

  const handleDisable = async () => {
    if (!confirmDisable || saving) return;
    const mapping = confirmDisable;
    setMutationError('');
    setSaving(true);
    try {
      await updateRoutingContextMapping(mapping.id, {
        expected_revision: mapping.revision,
        address_space_id: mapping.address_space_id,
        local_context_name: mapping.local_context_name || '',
        status: 'disabled',
      });
      setConfirmDisable(null);
      await loadMappings(selectedDeviceId);
    } catch (error) {
      setMutationError(showMutationError(
        error,
        zh ? '停用映射失败，请重试。' : 'Failed to disable the mapping. Please retry.',
      ));
      if (error instanceof ApiError && error.status === 409) {
        setConfirmDisable(null);
        void loadMappings(selectedDeviceId);
      } else if (error instanceof ApiError && error.status === 403) {
        setConfirmDisable(null);
      }
    } finally {
      setSaving(false);
    }
  };

  const renderError = (message: string, onRetry: () => void) => (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      <span>{message}</span>
      <ActionButton icon={RefreshCw} size="sm" onClick={onRetry}>{zh ? '重试' : 'Retry'}</ActionButton>
    </div>
  );

  const activeGlobalSpace = useMemo(
    () => addressSpaces.find((space) => space.status === 'active' && space.kind === 'global') || null,
    [addressSpaces],
  );

  const handleBulkMapAllGlobal = async () => {
    if (!activeGlobalSpace || devices.length === 0 || bulkMapping) return;
    setBulkMapping(true);
    setBulkMappingNotice('');
    setMutationError('');
    let created = 0;
    let skipped = 0;
    let failed = 0;
    for (const dev of devices) {
      for (const source of ['cli', 'snmp'] as const) {
        try {
          await createRoutingContextMapping({
            device_id: dev.id,
            context_source: source,
            context_type: 'global',
            local_context_key: 'global',
            local_context_name: 'Global',
            address_space_id: activeGlobalSpace.id,
          });
          created += 1;
        } catch (err: any) {
          const status = Number(err?.status || err?.statusCode || 0);
          const msg = String(err?.message || err?.detail || '').toLowerCase();
          if (status === 409 || msg.includes('409') || msg.includes('exist') || msg.includes('conflict') || msg.includes('已存在') || msg.includes('重复') || msg.includes('duplicate')) {
            skipped += 1;
          } else {
            failed += 1;
          }
        }
      }
    }
    const targetDeviceId = selectedDeviceId || devices[0]?.id || '';
    if (!selectedDeviceId && targetDeviceId) {
      setSelectedDeviceId(targetDeviceId);
    }
    if (targetDeviceId) {
      await loadMappings(targetDeviceId);
    }
    if (failed === 0) {
      setBulkMappedDone(true);
    }
    setBulkMappingNotice(
      zh
        ? `一键映射完成：新增 ${created} 条、已有跳过 ${skipped} 条${failed ? `、失败 ${failed} 条` : ''}（覆盖 CLI 与 SNMP 全局路由表）。`
        : `Bulk map complete: ${created} created, ${skipped} skipped${failed ? `, ${failed} failed` : ''} (CLI & SNMP Global).`,
    );
    setBulkMapping(false);
  };

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden px-4 py-4 sm:px-6 sm:py-5 space-y-4">
      <PageHero
        icon={GitBranch}
        title={zh ? '设备上下文映射' : 'Device Context Mappings'}
        subtitle={zh
          ? '将设备的 Global / VRF 路由表关联到 IPAM 地址空间，便于网段与网关自动匹配。'
          : 'Map device Global / VRF routing contexts to IPAM address spaces for automatic gateway matching.'}
        className="overflow-visible"
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {activeGlobalSpace && devices.length > 0 && (
              <ActionButton
                icon={GitBranch}
                variant={bulkMappedDone ? 'default' : 'accent'}
                onClick={() => void handleBulkMapAllGlobal()}
                disabled={bulkMapping || bulkMappedDone || lookupsLoading || writeDenied}
              >
                {bulkMapping
                  ? (zh ? '批量映射中…' : 'Mapping…')
                  : bulkMappedDone
                    ? (zh ? '已全部映射 Global' : 'All Global Mapped')
                    : (zh ? `一键映射全部设备 Global (${devices.length})` : `Map all devices Global (${devices.length})`)}
              </ActionButton>
            )}
            <ActionButton icon={RefreshCw} onClick={() => void loadMappings(selectedDeviceId)} disabled={!selectedDeviceId || mappingsLoading}>
              {zh ? '刷新' : 'Refresh'}
            </ActionButton>
            <ActionButton icon={Plus} variant="primary" onClick={openCreateForm} disabled={!selectedDeviceId || lookupsLoading || lookupsError !== '' || mappingsLoading || mappingsError !== '' || writeDenied}>
              {zh ? '新增映射' : 'Add mapping'}
            </ActionButton>
          </div>
        )}
        extras={(
          <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="routing-context-device" className="text-xs font-semibold text-slate-600">
              {zh ? '设备' : 'Device'}
            </label>
            <div
              className="relative w-full min-w-[min(100%,20rem)] sm:w-80"
              onBlur={(event) => {
                const nextTarget = event.relatedTarget;
                if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
                  setDevicePickerOpen(false);
                  setActiveDeviceOption(-1);
                }
              }}
            >
              <Search size={15} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                id="routing-context-device"
                role="combobox"
                aria-label={zh ? '选择设备' : 'Select device'}
                aria-autocomplete="list"
                aria-expanded={devicePickerOpen && !lookupsLoading && !lookupsError}
                aria-controls={devicePickerOpen ? 'routing-context-device-options' : undefined}
                aria-activedescendant={devicePickerOpen && activeDeviceOption >= 0 ? `routing-context-device-option-${activeDeviceOption}` : undefined}
                aria-busy={lookupsLoading}
                autoComplete="off"
                value={devicePickerOpen ? deviceSearchQuery : selectedDevice ? deviceLabel(selectedDevice) : deviceSearchQuery}
                placeholder={lookupsLoading
                  ? (zh ? '加载设备中…' : 'Loading devices…')
                  : lookupsError
                    ? (zh ? '设备列表不可用' : 'Device list unavailable')
                    : (zh ? '按设备名称或 IP 搜索' : 'Search by device name or IP')}
                onFocus={(event) => {
                  setDevicePickerOpen(Boolean(deviceSearchQuery.trim()));
                  setActiveDeviceOption(-1);
                  if (selectedDeviceId) {
                    setDeviceSearchQuery('');
                    event.currentTarget.select();
                  }
                }}
                onChange={(event) => {
                  const nextQuery = event.target.value;
                  setDeviceSearchQuery(nextQuery);
                  setSelectedDeviceId('');
                  setWriteDenied(false);
                  setDevicePickerOpen(Boolean(nextQuery.trim()));
                  setActiveDeviceOption(-1);
                }}
                onKeyDown={handleDeviceSearchKeyDown}
                disabled={lookupsLoading || Boolean(lookupsError)}
                className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-9 text-sm text-slate-700 outline-none focus:border-blue-400 disabled:cursor-not-allowed disabled:bg-slate-50"
              />
              <ChevronDown size={15} aria-hidden="true" className={`pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-transform ${devicePickerOpen ? 'rotate-180' : ''}`} />
              {devicePickerOpen && !lookupsLoading && !lookupsError && (
                <div
                  id="routing-context-device-options"
                  role="listbox"
                  aria-label={zh ? '设备搜索结果' : 'Device search results'}
                  className="absolute left-0 top-full z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
                >
                  {filteredDevices.length ? filteredDevices.map((device, index) => (
                    <div
                      key={device.id}
                      id={`routing-context-device-option-${index}`}
                      role="option"
                      aria-selected={device.id === selectedDeviceId}
                      className={`cursor-pointer px-3 py-2 text-sm ${index === activeDeviceOption ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'}`}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveDeviceOption(index)}
                      onClick={() => selectDevice(device)}
                    >
                      {deviceLabel(device)}
                    </div>
                  )) : (
                    <div role="status" className="px-3 py-2 text-sm text-slate-500">
                      {zh ? '没有匹配的设备' : 'No matching devices'}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      />

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-4 py-4 sm:px-6 sm:py-5">
        {lookupsError && renderError(lookupsError, () => void loadLookups())}
        {!lookupsError && mappingsError && renderError(mappingsError, () => void loadMappings(selectedDeviceId))}
        {mutationError && (
          <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{mutationError}</div>
        )}

        {selectedDeviceId && !mappingsLoading && !mappingsError && candidates.length > 0 && (
          <section
            className="overflow-hidden rounded-2xl border border-slate-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900/95 shadow-2xs"
            aria-label={zh ? '已采集路由上下文候选' : 'Discovered routing context candidates'}
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 dark:border-zinc-800 bg-slate-50/70 dark:bg-zinc-800/40 px-5 py-3">
              <div>
                <h2 className="text-sm font-bold text-slate-800 dark:text-zinc-100">
                  {zh ? '自动发现的路由表 / VRF（待确认优先）' : 'Discovered Routing Tables / VRFs'}
                </h2>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  {zh
                    ? '来自最近一次 CLI 接口采集与 SNMP ARP 发现；待确认项选择目标地址空间即可一键归属。'
                    : 'From latest CLI interface & SNMP ARP snapshots. Pick a target address space to confirm pending items.'}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="rounded-full bg-amber-50 dark:bg-amber-950/40 border border-amber-200/70 dark:border-amber-900/60 px-2.5 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300">
                  {zh ? `待确认 ${candidates.filter((c) => c.mapping_status === 'pending').length}` : `${candidates.filter((c) => c.mapping_status === 'pending').length} pending`}
                </span>
                <span className="rounded-full bg-slate-100 dark:bg-zinc-800 px-2.5 py-0.5 text-[11px] font-semibold text-slate-600 dark:text-zinc-300">
                  {zh ? `共 ${candidates.length} 项` : `${candidates.length} total`}
                </span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="nx-data-table min-w-[860px] text-left">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-zinc-800 bg-slate-50/50 dark:bg-zinc-800/30 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                    <th className="px-5 py-2.5">{zh ? '设备路由表 / VRF' : 'Routing Table / VRF'}</th>
                    <th className="px-4 py-2.5">{zh ? '采集方式' : 'Collection Source'}</th>
                    <th className="px-4 py-2.5">{zh ? '发现条目 / 最近采集' : 'Samples / Last Seen'}</th>
                    <th className="px-4 py-2.5">{zh ? '归属状态' : 'Ownership Status'}</th>
                    <th className="px-4 py-2.5 text-right">{zh ? '归属操作' : 'Action'}</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => {
                    const key = candidateRowKey(candidate);
                    const matchingSpaces = candidate.context_type === 'unknown'
                      ? []
                      : addressSpaces.filter((space) => space.kind === candidate.context_type);
                    const selectedSpace = candidateSpaceSelection[key] || '';
                    const isConfirming = confirmingCandidateKey === key;
                    return (
                      <tr key={key} className="border-b border-slate-100 dark:border-zinc-800/80 last:border-0 hover:bg-slate-50/60 dark:hover:bg-zinc-800/40 transition-colors">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2">
                            <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-bold ${
                              candidate.context_type === 'vrf'
                                ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300'
                                : candidate.context_type === 'global'
                                  ? 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-300'
                                  : 'bg-slate-100 text-slate-500 dark:bg-zinc-800 dark:text-zinc-400'
                            }`}>
                              {candidate.context_type === 'vrf' ? 'VRF' : candidate.context_type === 'global' ? 'Global' : (zh ? '未知' : 'Unknown')}
                            </span>
                            <span className="text-sm font-semibold text-slate-800 dark:text-zinc-100">
                              {candidate.context_type === 'global'
                                ? (zh ? '默认全局路由表 (Global)' : 'Default Routing Table (Global)')
                                : candidate.context_type === 'vrf'
                                  ? candidate.local_context_name || candidate.local_context_key
                                  : (zh ? '未识别 VRF 上下文' : 'Unidentified VRF Context')}
                            </span>
                          </div>
                          {candidate.local_context_key && candidate.local_context_key !== '--' && candidate.context_type === 'vrf' && (
                            <code className="mt-0.5 block text-[11px] text-slate-400 dark:text-zinc-500">
                              {candidate.local_context_key}
                            </code>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600 dark:text-zinc-300">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="rounded-md bg-slate-100 dark:bg-zinc-800 px-1.5 py-0.5 text-[10px] font-bold uppercase text-slate-700 dark:text-zinc-200">
                              {candidate.context_source}
                            </span>
                            <span className="text-slate-500 dark:text-zinc-400">
                              {candidate.sources.map((src) => formatSourceDomain(src, zh)).join(' · ')}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-600 dark:text-zinc-300">
                          <div className="font-semibold tabular-nums">{candidate.observation_count} {zh ? '条' : ''}</div>
                          <div className="text-[11px] text-slate-400 dark:text-zinc-500">{formatTimestamp(candidate.last_observed_at, zh)}</div>
                        </td>
                        <td className="px-4 py-3">
                          {candidate.mapping_status === 'mapped' ? (
                            <span className="inline-flex rounded-full border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-0.5 text-[10px] font-bold text-emerald-700 dark:text-emerald-300">
                              {zh ? `已归属 · ${candidate.address_space_name || candidate.address_space_id}` : `Mapped · ${candidate.address_space_name || candidate.address_space_id}`}
                            </span>
                          ) : candidate.mapping_status === 'unknown_context' ? (
                            <span className="inline-flex rounded-full border border-slate-200 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 px-2.5 py-0.5 text-[10px] font-bold text-slate-600 dark:text-zinc-400">
                              {zh ? '缺少可靠上下文（待确认）' : 'Unreliable context (pending)'}
                            </span>
                          ) : (
                            <span className="inline-flex rounded-full border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/40 px-2.5 py-0.5 text-[10px] font-bold text-amber-800 dark:text-amber-300">
                              {zh ? '待确认归属' : 'Pending confirmation'}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {candidate.mapping_status === 'pending' && candidate.can_confirm ? (
                            <div className="inline-flex items-center justify-end gap-2">
                              <select
                                aria-label={`${zh ? '目标地址空间' : 'Target address space'} ${candidate.local_context_key}`}
                                value={selectedSpace}
                                onChange={(event) => setCandidateSpaceSelection((prev) => ({ ...prev, [key]: event.target.value }))}
                                disabled={isConfirming || writeDenied}
                                className="h-8 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 text-xs text-slate-700 dark:text-zinc-200 outline-none focus:border-cyan-500"
                              >
                                <option value="">{zh ? '选择目标地址空间…' : 'Select address space…'}</option>
                                {matchingSpaces.map((space) => (
                                  <option key={space.id} value={space.id}>{addressSpaceLabel(space, zh)}</option>
                                ))}
                              </select>
                              <button
                                type="button"
                                disabled={!selectedSpace || isConfirming || writeDenied}
                                onClick={() => void handleConfirmCandidate(candidate)}
                                className="h-8 rounded-lg bg-cyan-600 px-3 text-xs font-semibold text-white hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                              >
                                {isConfirming ? (zh ? '确认中…' : 'Confirming…') : (zh ? '确认归属' : 'Confirm')}
                              </button>
                            </div>
                          ) : candidate.mapping_status === 'unknown_context' ? (
                            <span className="text-[11px] text-slate-400 dark:text-zinc-500">
                              {zh ? 'SNMP 未携带 VRF，可忽略或手动映射' : 'No VRF in SNMP; ignore or map manually'}
                            </span>
                          ) : (
                            <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
                              {zh ? '已生效' : 'Active'}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {bulkMappingNotice && (
        <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-800">
          {bulkMappingNotice}
        </div>
      )}
      <section className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-slate-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900/95 shadow-2xs" aria-label={zh ? '设备上下文映射列表' : 'Device context mappings'}>
          <div className="h-full overflow-auto">
            {lookupsLoading || mappingsLoading ? (
              <div role="status" className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-slate-500 dark:text-zinc-400">
                <RefreshCw size={16} className="animate-spin" />
                {zh ? '加载中…' : 'Loading…'}
              </div>
            ) : lookupsError ? (
              <div className="flex min-h-[240px] items-center justify-center px-6 text-center text-sm text-slate-500 dark:text-zinc-400">
                {zh ? '无权限或暂时无法加载设备和地址空间。' : 'Devices and address spaces are unavailable or permission was denied.'}
              </div>
            ) : !selectedDeviceId ? (
              <div className="flex min-h-[240px] items-center justify-center px-6 text-center text-sm text-slate-500 dark:text-zinc-400">
                {devices.length === 0
                  ? (zh ? '没有可选择的设备。' : 'No devices are available to select.')
                  : (zh ? '请选择设备以查看其本地路由上下文映射。' : 'Select a device to view its local routing-context mappings.')}
              </div>
            ) : mappingsError ? (
              <div className="flex min-h-[240px] items-center justify-center px-6 text-center text-sm text-slate-500 dark:text-zinc-400">
                {zh ? '映射列表不可用，请查看上方提示并重试。' : 'Mappings are unavailable. Review the message above and retry.'}
              </div>
            ) : mappings.length === 0 ? (
              <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 px-6 text-center">
                <GitBranch size={26} className="text-slate-300 dark:text-zinc-600" />
                <p className="text-sm font-semibold text-slate-600 dark:text-zinc-300">{zh ? '该设备还没有上下文映射' : 'No context mappings for this device'}</p>
                <p className="max-w-xl text-xs text-slate-400 dark:text-zinc-500">
                  {zh ? '只有人工明确登记的 VRF 或 Global 上下文会出现在这里。' : 'Only explicitly registered VRF or Global contexts appear here.'}
                </p>
              </div>
            ) : (
              <table className="nx-data-table min-w-[820px] text-left">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-zinc-800 bg-slate-50/70 dark:bg-zinc-800/40 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                    <th className="px-5 py-3">{zh ? '设备路由表 / 映射关系' : 'Device Routing Table → Address Space'}</th>
                    <th className="px-4 py-3">{zh ? '采集协议' : 'Protocol'}</th>
                    <th className="px-4 py-3">{zh ? '状态' : 'Status'}</th>
                    <th className="px-4 py-3">{zh ? '最近核验' : 'Last Verified'}</th>
                    <th className="px-4 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.map((mapping) => {
                    const subKey = formatMappingContextSub(mapping, zh);
                    return (
                      <tr key={mapping.id} className="border-b border-slate-100 dark:border-zinc-800/80 last:border-0 hover:bg-slate-50/60 dark:hover:bg-zinc-800/40 transition-colors">
                        <td className="px-5 py-3.5">
                          <div className="flex flex-wrap items-center gap-2.5">
                            <div>
                              <div className="flex items-center gap-1.5">
                                <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-bold ${
                                  mapping.context_type === 'vrf'
                                    ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300'
                                    : 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-300'
                                }`}>
                                  {mapping.context_type === 'vrf' ? 'VRF' : (zh ? '全局' : 'Global')}
                                </span>
                                <span className="text-sm font-semibold text-slate-800 dark:text-zinc-100">
                                  {formatMappingContextTitle(mapping, zh)}
                                </span>
                              </div>
                              {subKey && (
                                <code className="mt-0.5 block max-w-[240px] truncate text-[11px] text-slate-400 dark:text-zinc-500">
                                  {subKey}
                                </code>
                              )}
                            </div>
                            <ArrowRight size={14} className="shrink-0 text-slate-300 dark:text-zinc-600" />
                            <div className="rounded-xl border border-slate-200/80 dark:border-zinc-700 bg-slate-50/80 dark:bg-zinc-800/60 px-3 py-1.5">
                              <div className="text-xs font-bold text-slate-800 dark:text-zinc-100">
                                {mapping.address_space_name || mapping.address_space_id}
                              </div>
                              <div className="text-[10px] text-slate-400 dark:text-zinc-500">
                                {mapping.address_space_kind === 'vrf' ? (mapping.vrf_id || 'VRF') : (zh ? 'IPAM 全局地址空间' : 'IPAM Global Space')}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3.5 text-xs text-slate-600 dark:text-zinc-300">
                          <span className="rounded-md bg-slate-100 dark:bg-zinc-800 px-2 py-0.5 text-[11px] font-bold uppercase text-slate-700 dark:text-zinc-200">
                            {mapping.context_source}
                          </span>
                        </td>
                        <td className="px-4 py-3.5">
                          <div className="inline-flex items-center gap-1.5">
                            <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-[10px] font-bold ${mapping.status === 'active'
                              ? 'border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300'
                              : 'border-slate-200 dark:border-zinc-700 bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400'}`}>
                              {mapping.status === 'active' ? (zh ? '启用' : 'Active') : (zh ? '已停用' : 'Disabled')}
                            </span>
                            <span className="sr-only">{mapping.revision}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3.5 whitespace-nowrap text-xs text-slate-500 dark:text-zinc-400">{formatTimestamp(mapping.last_verified_at, zh)}</td>
                        <td className="px-4 py-3.5 text-right">
                          {!writeDenied && (
                            <ActionIconGroup label={zh ? '上下文映射操作' : 'Context mapping actions'}>
                              <ActionIconButton icon={Pencil} label={zh ? '编辑' : 'Edit'} onClick={() => openEditForm(mapping)} />
                              {mapping.status === 'active' && (
                                <ActionIconButton
                                  icon={Ban}
                                  label={zh ? '停用' : 'Disable'}
                                  variant="danger"
                                  onClick={() => setConfirmDisable(mapping)}
                                />
                              )}
                            </ActionIconGroup>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>

      {formMode && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/45 p-4" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeForm();
        }}>
          <form
            role="dialog"
            aria-modal="true"
            aria-labelledby="routing-context-form-title"
            onSubmit={(event) => void handleSave(event)}
            className="max-h-[min(90vh,760px)] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl sm:p-6"
          >
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 id="routing-context-form-title" className="text-lg font-bold text-slate-800">
                  {formMode === 'create' ? (zh ? '新增设备上下文映射' : 'Add Device Context Mapping') : (zh ? '编辑设备上下文映射' : 'Edit Device Context Mapping')}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {formMode === 'create'
                    ? (zh ? '仅登记已明确识别的本地上下文；空值和 unknown 不可登记。' : 'Register only a known local context. Empty and unknown values are not allowed.')
                    : (zh ? `当前 revision：${editingMapping?.revision ?? '-'}` : `Current revision: ${editingMapping?.revision ?? '-'}`)}
                </p>
              </div>
              <button type="button" onClick={closeForm} aria-label={zh ? '关闭' : 'Close'} disabled={saving} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50">
                <X size={18} />
              </button>
            </div>

            {formMode === 'create' ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                  {zh ? '上下文来源' : 'Context source'}
                  <select aria-label={zh ? '上下文来源' : 'Context source'} value={form.context_source} onChange={(event) => setForm((current) => ({ ...current, context_source: event.target.value as RoutingContextSource }))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700">
                    <option value="cli">CLI</option>
                    <option value="snmp">SNMP</option>
                  </select>
                </label>
                <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                  {zh ? '上下文类型' : 'Context type'}
                  <select aria-label={zh ? '上下文类型' : 'Context type'} value={form.context_type} onChange={(event) => setForm((current) => ({ ...current, context_type: event.target.value as RoutingContextType, address_space_id: '' }))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700">
                    <option value="vrf">VRF</option>
                    <option value="global">{zh ? '全局 (Global)' : 'Global'}</option>
                  </select>
                </label>
                <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                  {zh ? '本地上下文标识 *' : 'Local context key *'}
                  <input aria-label={zh ? '本地上下文标识' : 'Local context key'} value={form.local_context_key} onChange={(event) => setForm((current) => ({ ...current, local_context_key: event.target.value }))} placeholder={zh ? '例如：VRF-CORP、global' : 'e.g. VRF-CORP, global'} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-normal text-slate-700 outline-none focus:border-blue-400" />
                </label>
                <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                  {zh ? '本地上下文名称' : 'Local context name'}
                  <input aria-label={zh ? '本地上下文名称' : 'Local context name'} value={form.local_context_name} onChange={(event) => setForm((current) => ({ ...current, local_context_name: event.target.value }))} placeholder={zh ? '可留空' : 'Optional'} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-normal text-slate-700 outline-none focus:border-blue-400" />
                </label>
              </div>
            ) : (
              <div className="mb-4 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                <div className="font-semibold">{editingMapping?.local_context_name || (zh ? '未命名上下文' : 'Unnamed context')}</div>
                <code className="mt-1 block text-xs text-slate-500">{editingMapping?.local_context_key}</code>
                <div className="mt-2 text-xs text-slate-500">{editingMapping?.context_source.toUpperCase()} / {editingMapping?.context_type === 'vrf' ? 'VRF' : 'Global'}</div>
              </div>
            )}

            <div className={`mt-4 grid gap-4 ${formMode === 'edit' ? 'sm:grid-cols-2' : ''}`}>
              <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                {zh ? '目标地址空间' : 'Target address space'}
                <select aria-label={zh ? '目标地址空间' : 'Target address space'} value={form.address_space_id} onChange={(event) => setForm((current) => ({ ...current, address_space_id: event.target.value }))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700">
                  <option value="">{zh ? '选择兼容的地址空间' : 'Select a compatible address space'}</option>
                  {compatibleAddressSpaces.map((space) => <option key={space.id} value={space.id}>{addressSpaceLabel(space, zh)}</option>)}
                </select>
                {compatibleAddressSpaces.length === 0 && <span className="text-[11px] font-normal text-amber-700">{zh ? '没有可匹配的地址空间，请先创建相同类型的空间。' : 'No compatible address spaces. Create one with the matching type first.'}</span>}
              </label>
              {formMode === 'edit' && (
                <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                  {zh ? '本地上下文名称' : 'Local context name'}
                  <input aria-label={zh ? '本地上下文名称' : 'Local context name'} value={form.local_context_name} onChange={(event) => setForm((current) => ({ ...current, local_context_name: event.target.value }))} placeholder={zh ? '可留空' : 'Optional'} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-normal text-slate-700 outline-none focus:border-blue-400" />
                </label>
              )}
              {formMode === 'edit' && (
                <label className="grid gap-1.5 text-xs font-semibold text-slate-600">
                  {zh ? '映射状态' : 'Mapping status'}
                  <select aria-label={zh ? '映射状态' : 'Mapping status'} value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as RoutingContextStatus }))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal text-slate-700">
                    <option value="active">{zh ? '启用' : 'Active'}</option>
                    <option value="disabled">{zh ? '停用' : 'Disabled'}</option>
                  </select>
                </label>
              )}
            </div>

            {formError && <div role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 text-xs text-rose-800">{formError}</div>}

            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <ActionButton type="button" onClick={closeForm} disabled={saving}>{zh ? '取消' : 'Cancel'}</ActionButton>
              <ActionButton type="submit" variant="primary" disabled={saving || writeDenied}>
                {saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存映射' : 'Save mapping')}
              </ActionButton>
            </div>
          </form>
        </div>
      )}

      {confirmDisable && (
        <div className="fixed inset-0 z-[125] flex items-center justify-center bg-slate-950/45 p-4">
          <div role="alertdialog" aria-modal="true" aria-labelledby="disable-routing-context-title" className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
            <h2 id="disable-routing-context-title" className="text-base font-bold text-slate-800">{zh ? '确认停用映射？' : 'Disable this mapping?'}</h2>
            <p className="mt-2 text-sm text-slate-600">
              {zh ? '停用只改变映射状态，不会删除记录。' : 'Disabling changes the mapping status and keeps the record.'}
            </p>
            {mutationError && <div role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">{mutationError}</div>}
            <div className="mt-5 flex justify-end gap-2">
              <ActionButton onClick={() => setConfirmDisable(null)} disabled={saving}>{zh ? '取消' : 'Cancel'}</ActionButton>
              <ActionButton icon={Ban} variant="danger" onClick={() => void handleDisable()} disabled={saving}>{saving ? (zh ? '停用中…' : 'Disabling…') : (zh ? '确认停用' : 'Confirm disable')}</ActionButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DeviceRoutingContextTab;
