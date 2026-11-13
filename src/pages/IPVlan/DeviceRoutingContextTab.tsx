import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Ban, GitBranch, Pencil, Plus, RefreshCw, X } from 'lucide-react';
import PageHero from '../../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../components/ui/ActionIconButton';
import { apiRequest, ApiError } from '../../api/http';
import {
  createRoutingContextMapping,
  listRoutingContextMappings,
  updateRoutingContextMapping,
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
  const [lookupsLoading, setLookupsLoading] = useState(true);
  const [lookupsError, setLookupsError] = useState('');
  const [mappings, setMappings] = useState<RoutingContextMapping[]>([]);
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

  const compatibleAddressSpaces = useMemo(
    () => addressSpaces.filter((space) => space.kind === form.context_type),
    [addressSpaces, form.context_type],
  );

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
      setMappingsError('');
      setMappingsLoading(false);
      return;
    }
    setMappingsLoading(true);
    setMappingsError('');
    try {
      const payload = await listRoutingContextMappings(deviceId);
      if (requestId !== mappingRequestId.current) return;
      if (!Array.isArray(payload.items)) throw new Error('Invalid routing-context mapping response.');
      setMappings(payload.items);
    } catch (error) {
      if (requestId !== mappingRequestId.current) return;
      setMappings([]);
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

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-hidden">
      <PageHero
        icon={GitBranch}
        title={zh ? '设备上下文映射' : 'Device Context Mappings'}
        subtitle={zh
          ? '显式关联设备本地 VRF / Global 上下文与地址空间。映射由人工维护，不从发现结果自动登记。'
          : 'Explicitly map device-local VRF / Global contexts to address spaces. Mappings are maintained manually.'}
        actions={(
          <div className="flex items-center gap-2">
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
            <select
              id="routing-context-device"
              aria-label={zh ? '选择设备' : 'Select device'}
              value={selectedDeviceId}
              onChange={(event) => {
                setWriteDenied(false);
                setSelectedDeviceId(event.target.value);
              }}
              disabled={lookupsLoading || Boolean(lookupsError)}
              className="min-w-[min(100%,20rem)] rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-blue-400 disabled:cursor-not-allowed disabled:bg-slate-50"
            >
              <option value="">{lookupsLoading ? (zh ? '加载设备中…' : 'Loading devices…') : (zh ? '选择设备' : 'Select a device')}</option>
              {devices.map((device) => <option key={device.id} value={device.id}>{deviceLabel(device)}</option>)}
            </select>
            <span className="text-xs text-slate-400">
              {zh ? '仅显示所选设备的显式映射' : 'Showing explicit mappings for the selected device'}
            </span>
          </div>
        )}
      />

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-4 py-4 sm:px-6 sm:py-5">
        {lookupsError && renderError(lookupsError, () => void loadLookups())}
        {!lookupsError && mappingsError && renderError(mappingsError, () => void loadMappings(selectedDeviceId))}
        {mutationError && (
          <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{mutationError}</div>
        )}

        <section className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm" aria-label={zh ? '设备上下文映射列表' : 'Device context mappings'}>
          <div className="h-full overflow-auto">
            {lookupsLoading || mappingsLoading ? (
              <div role="status" className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-slate-500">
                <RefreshCw size={16} className="animate-spin" />
                {zh ? '加载中…' : 'Loading…'}
              </div>
            ) : lookupsError ? (
              <div className="flex min-h-[240px] items-center justify-center px-6 text-center text-sm text-slate-500">
                {zh ? '无权限或暂时无法加载设备和地址空间。' : 'Devices and address spaces are unavailable or permission was denied.'}
              </div>
            ) : !selectedDeviceId ? (
              <div className="flex min-h-[240px] items-center justify-center px-6 text-center text-sm text-slate-500">
                {devices.length === 0
                  ? (zh ? '没有可选择的设备。' : 'No devices are available to select.')
                  : (zh ? '请选择设备以查看其本地路由上下文映射。' : 'Select a device to view its local routing-context mappings.')}
              </div>
            ) : mappingsError ? (
              <div className="flex min-h-[240px] items-center justify-center px-6 text-center text-sm text-slate-500">
                {zh ? '映射列表不可用，请查看上方提示并重试。' : 'Mappings are unavailable. Review the message above and retry.'}
              </div>
            ) : mappings.length === 0 ? (
              <div className="flex min-h-[240px] flex-col items-center justify-center gap-2 px-6 text-center">
                <GitBranch size={26} className="text-slate-300" />
                <p className="text-sm font-semibold text-slate-600">{zh ? '该设备还没有上下文映射' : 'No context mappings for this device'}</p>
                <p className="max-w-xl text-xs text-slate-400">
                  {zh ? '只有人工明确登记的 VRF 或 Global 上下文会出现在这里。' : 'Only explicitly registered VRF or Global contexts appear here.'}
                </p>
              </div>
            ) : (
              <table className="nx-data-table min-w-[980px] text-left">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50/70 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    <th className="px-5 py-3">{zh ? '本地上下文' : 'Local Context'}</th>
                    <th className="px-4 py-3">{zh ? '来源 / 类型' : 'Source / Type'}</th>
                    <th className="px-4 py-3">{zh ? '归属地址空间' : 'Address Space'}</th>
                    <th className="px-4 py-3">{zh ? '状态' : 'Status'}</th>
                    <th className="px-4 py-3">Revision</th>
                    <th className="px-4 py-3">{zh ? '最近核验' : 'Last Verified'}</th>
                    <th className="px-4 py-3 text-right">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.map((mapping) => (
                    <tr key={mapping.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/60">
                      <td className="px-5 py-3.5">
                        <div className="text-sm font-semibold text-slate-800">{mapping.local_context_name || (zh ? '未命名上下文' : 'Unnamed context')}</div>
                        <code className="mt-1 block max-w-[260px] truncate text-xs text-slate-500">{mapping.local_context_key}</code>
                      </td>
                      <td className="px-4 py-3.5 text-xs text-slate-600">
                        <span className="font-semibold uppercase">{mapping.context_source}</span>
                        <span className="mx-1.5 text-slate-300">/</span>
                        {mapping.context_type === 'vrf' ? 'VRF' : (zh ? '全局' : 'Global')}
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="text-sm font-medium text-slate-700">{mapping.address_space_name || mapping.address_space_id}</div>
                        <div className="mt-1 text-[11px] text-slate-400">{mapping.address_space_kind === 'vrf' ? (mapping.vrf_id || 'VRF') : (zh ? '全局地址空间' : 'Global address space')}</div>
                      </td>
                      <td className="px-4 py-3.5">
                        <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-bold ${mapping.status === 'active'
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-slate-200 bg-slate-100 text-slate-600'}`}>
                          {mapping.status === 'active' ? (zh ? '启用' : 'Active') : (zh ? '已停用' : 'Disabled')}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 font-mono text-xs tabular-nums text-slate-600">{mapping.revision}</td>
                      <td className="px-4 py-3.5 whitespace-nowrap text-xs text-slate-500">{formatTimestamp(mapping.last_verified_at, zh)}</td>
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
                  ))}
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
