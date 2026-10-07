import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, CheckCircle2, Loader2, Search, Server, X } from 'lucide-react';
import { apiRequest } from '../../api/http';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import type { ModelPresetItem } from './PresetProfilesModal';
import type { CandidateDevice } from './components/LiveWalkInspector';

interface InterfaceTestResult {
  status?: string;
  passed?: boolean;
  message?: string;
  interfaces?: number;
}

interface BindingTestResult {
  interface?: InterfaceTestResult;
  errors: string[];
}

interface DeviceListResponse {
  items?: Array<Record<string, unknown>>;
  data?: Array<Record<string, unknown>> | { items?: Array<Record<string, unknown>> };
}

interface BindingListResponse {
  data?: {
    devices?: Array<{ device_id?: string }>;
  };
}

export interface TemplateBindingModalProps {
  open: boolean;
  template: ModelPresetItem | null;
  fallbackDevice?: CandidateDevice;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onClose: () => void;
  onConfirm: (template: ModelPresetItem, deviceIds: string[], removedDeviceIds: string[]) => Promise<void>;
}

const normalize = (value: unknown) => String(value || '').trim().toLowerCase();
const statusRank = (status?: string) => normalize(status) === 'online' ? 0 : 1;

const scopeList = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.map(item => normalize(item)).filter(Boolean);
  return String(value || '').split(/[;,\n]/).map(item => normalize(item)).filter(Boolean);
};

const globMatch = (actual: string, selector: string) => {
  if (!selector || selector === '*' || selector === 'any' || selector === 'all') return true;
  const escaped = selector.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.');
  return new RegExp(`^${escaped}$`, 'i').test(actual);
};

const templateCompatible = (template: ModelPresetItem | null, device: CandidateDevice) => {
  if (!template) return false;
  const vendor = normalize(device.vendor);
  const templateVendor = normalize(template.vendor);
  if (vendor && templateVendor && !vendor.includes(templateVendor) && !templateVendor.includes(vendor)) return false;
  const platforms = scopeList(template.platforms);
  const platform = normalize(device.platform);
  if (platforms.length && platform && !platforms.some(selector => platform === selector || platform.startsWith(`${selector}_`) || selector.includes(platform) || globMatch(platform, selector))) return false;
  const model = normalize(device.model);
  const modelPattern = normalize(template.model_pattern || template.model);
  if (model && modelPattern && !globMatch(model, modelPattern) && model !== modelPattern && !model.startsWith(`${modelPattern}-`) && !model.startsWith(`${modelPattern} `)) return false;
  const versions = scopeList(template.software_version_scope || template.firmware_scope);
  const version = normalize(device.version);
  const platformForVersion = normalize(device.platform);
  if (versions.length && version && !versions.some(selector => {
    const compactSelector = selector.replace(/[^a-z0-9]/g, '');
    const compactVersion = version.replace(/[^a-z0-9]/g, '');
    const major = selector.match(/(?:v|version|comware|vrp|ios(?:xe)?|nxos|asa)?(\d+)/)?.[1];
    return version.includes(selector)
      || globMatch(version, selector)
      || (compactSelector && compactVersion.includes(compactSelector))
      || Boolean(major && (new RegExp(`(?:^|[^0-9])v?${major}(?:$|[^0-9])`).test(version) || platformForVersion.includes(`v${major}`) || platformForVersion.endsWith(major)));
  })) return false;
  return true;
};

const TemplateBindingModal: React.FC<TemplateBindingModalProps> = ({
  open,
  template,
  fallbackDevice,
  language,
  showToast,
  onClose,
  onConfirm,
}) => {
  useEscapeClose(open && Boolean(template), onClose);
  const zh = language === 'zh';
  const [devices, setDevices] = useState<CandidateDevice[]>([]);
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>([]);
  const [initialDeviceIds, setInitialDeviceIds] = useState<string[]>([]);
  const [testDeviceId, setTestDeviceId] = useState('');
  const [deviceSearch, setDeviceSearch] = useState('');
  const [snmpVersion, setSnmpVersion] = useState<'1' | '2c'>('2c');
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [testing, setTesting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [testResult, setTestResult] = useState<BindingTestResult | null>(null);
  const [loadError, setLoadError] = useState('');

  const selectedTestDevice = useMemo(
    () => devices.find(device => device.device_id === testDeviceId),
    [devices, testDeviceId],
  );
  const testDeviceIsOnline = normalize(selectedTestDevice?.status) === 'online';
  const filteredDevices = useMemo(() => {
    const term = normalize(deviceSearch);
    return devices.filter(device => !term || [device.hostname, device.ip_address, device.device_id]
      .some(value => normalize(value).includes(term)));
  }, [devices, deviceSearch]);

  useEffect(() => {
    if (!open || !template) return;
    let active = true;
    setDevices([]);
    setSelectedDeviceIds([]);
    setInitialDeviceIds([]);
    setTestDeviceId('');
    setDeviceSearch('');
    setSnmpVersion('2c');
    setTestResult(null);
    setLoadError('');
    setLoadingDevices(true);

    const load = async () => {
      try {
        const response = await apiRequest<DeviceListResponse>(
          '/api/devices?mode=light&page=1&page_size=1000&asset_type=network_device',
        );
        const rawData = response.data;
        const rawItems = Array.isArray(response.items)
          ? response.items
          : Array.isArray(rawData)
            ? rawData
            : !Array.isArray(rawData) && Array.isArray(rawData?.items)
              ? rawData.items
              : [];
        const mapped: CandidateDevice[] = rawItems
          .map(item => ({
            device_id: String(item.id || ''),
            hostname: String(item.hostname || item.ip_address || item.model || ''),
            ip_address: String(item.ip_address || item.management_ip || ''),
            status: String(item.status || ''),
            vendor: String(item.vendor || ''),
            platform: String(item.platform || item.platform_code || ''),
            model: String(item.model || ''),
            version: String(item.version || item.software_version || item.os_version || item.firmware_version || ''),
          }))
          .filter(device => device.device_id)
          .sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.hostname.localeCompare(b.hostname));
        if (fallbackDevice?.device_id && !mapped.some(device => device.device_id === fallbackDevice.device_id)) {
          mapped.push(fallbackDevice);
        }

        let nextSelected: string[] = [];
        if (template.profile_id) {
          try {
            const bindingResponse = await apiRequest<BindingListResponse>(
              `/api/platform-registry/snmp-metric-profiles/${template.profile_id}/bindings`,
            );
            nextSelected = (bindingResponse.data?.devices || [])
              .map(device => String(device.device_id || ''))
              .filter(Boolean);
          } catch {
            // A newly created profile simply has no existing bindings.
          }
        } else if (fallbackDevice?.device_id) {
          // A device-context entry point may preselect that one device. New
          // templates opened from the library intentionally start empty.
          nextSelected = [...nextSelected, fallbackDevice.device_id];
        }
        if (!active) return;
        setDevices(mapped);
        setInitialDeviceIds(nextSelected);
        setSelectedDeviceIds(nextSelected);
        const firstSelected = mapped.find(device => nextSelected.includes(device.device_id));
        setTestDeviceId(firstSelected?.device_id || mapped.find(device => statusRank(device.status) === 0)?.device_id || '');
        if (!mapped.length) {
          setLoadError(zh ? '当前没有可选择的受管设备' : 'No managed devices are available');
        }
      } catch (error) {
        if (!active) return;
        if (fallbackDevice?.device_id) {
          setDevices([fallbackDevice]);
          setInitialDeviceIds([fallbackDevice.device_id]);
          setSelectedDeviceIds([fallbackDevice.device_id]);
          setTestDeviceId(fallbackDevice.device_id);
        } else {
          setLoadError(error instanceof Error ? error.message : zh ? '设备列表加载失败' : 'Failed to load devices');
        }
      } finally {
        if (active) setLoadingDevices(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [open, template, fallbackDevice, zh]);

  if (!open || !template) return null;

  const selectedDevice = devices.find(device => device.device_id === testDeviceId);
  const hasInterfaceTemplate = template.interface_config?.enabled === true;
  const toggleDevice = (deviceId: string) => {
    setTestResult(null);
    setSelectedDeviceIds(current => {
      const next = current.includes(deviceId)
        ? current.filter(id => id !== deviceId)
        : [...current, deviceId];
      if (deviceId === testDeviceId && !next.includes(deviceId)) {
        setTestDeviceId(next[0] || '');
      }
      if (!testDeviceId && next.length) setTestDeviceId(next[0]);
      return next;
    });
  };

  const selectAllVisible = () => {
    const visibleIds = filteredDevices.filter(device => templateCompatible(template, device)).map(device => device.device_id);
    setSelectedDeviceIds(current => Array.from(new Set([...current, ...visibleIds])));
    if (!testDeviceId) setTestDeviceId(visibleIds[0] || '');
    setTestResult(null);
  };

  const selectAllDevices = () => {
    const allIds = devices.filter(device => templateCompatible(template, device)).map(device => device.device_id);
    setSelectedDeviceIds(allIds);
    if (!testDeviceId) {
      setTestDeviceId(
        devices.find(device => statusRank(device.status) === 0)?.device_id || allIds[0] || '',
      );
    }
    setTestResult(null);
  };

  const clearVisible = () => {
    const visibleIds = new Set(filteredDevices.map(device => device.device_id));
    const next = selectedDeviceIds.filter(id => !visibleIds.has(id));
    setSelectedDeviceIds(next);
    if (testDeviceId && visibleIds.has(testDeviceId)) setTestDeviceId(next[0] || '');
    setTestResult(null);
  };

  const testTemplate = async () => {
    if (!hasInterfaceTemplate) return;
    if (!testDeviceId) {
      showToast(zh ? '请先选择测试设备' : 'Select a test device first', 'error');
      return;
    }
    if (!testDeviceIsOnline) {
      showToast(zh ? '测试设备不在线，可以直接绑定；在线设备建议先测试' : 'The test device is offline; binding is still allowed', 'info');
      return;
    }
    setTesting(true);
    setTestResult(null);
    const result: BindingTestResult = { errors: [] };
    try {
      const response = await apiRequest<{ success: boolean; data: InterfaceTestResult }>(
        '/api/platform-registry/snmp-interface-test',
        {
          method: 'POST',
          body: JSON.stringify({
            device_id: testDeviceId,
            version: snmpVersion,
            interface_config: template.interface_config,
          }),
        },
      );
      result.interface = response.data;
      setTestResult(result);
      const passed = result.interface.passed === true;
      showToast(
        passed
          ? (zh ? '接口模板验证通过，可确认绑定' : 'Interface template validation passed; the binding can be confirmed')
          : (zh ? '接口模板验证未通过，但仍可由操作员直接确认绑定' : 'Interface template validation did not pass; an operator may still confirm the binding directly'),
        passed ? 'success' : 'info',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : zh ? '接口模板验证失败' : 'Interface template validation failed';
      result.errors.push(message);
      setTestResult(result);
      showToast(message, 'error');
    } finally {
      setTesting(false);
    }
  };

  const confirmBinding = async () => {
    const removed = initialDeviceIds.filter(id => !selectedDeviceIds.includes(id));
    if (!selectedDeviceIds.length && !removed.length) {
      showToast(zh ? '至少选择一台设备' : 'Select at least one device', 'error');
      return;
    }
    setConfirming(true);
    try {
      await onConfirm(template, selectedDeviceIds, removed);
    } finally {
      setConfirming(false);
    }
  };

  const isExistingTemplate = Boolean(template.profile_id);
  const sourceLabel = template.source === 'official' || template.id
    ? (zh ? '官方/已保存模板' : 'Official / saved template')
    : (zh ? '自定义模板' : 'Custom template');

  return (
    <div className="fixed inset-0 z-[160] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="flex max-h-[90vh] w-full max-w-[820px] flex-col overflow-hidden rounded-2xl border border-[#00bceb]/25 bg-[var(--card-bg)] shadow-2xl dark:border-white/10" onMouseDown={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-black/8 px-5 py-4 dark:border-white/8">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-black/85 dark:text-white/90">
              <Server size={17} className="text-[#009ec4]" />
              {isExistingTemplate ? (zh ? '管理模板绑定设备' : 'Manage template device bindings') : (zh ? '选择设备并绑定 SNMP 模板' : 'Select devices and bind SNMP template')}
            </div>
            <div className="mt-1 text-[11px] text-black/45 dark:text-white/45">
              {zh ? '模板不会按型号自动套用；请勾选需要使用该模板的设备。此处仅验证已启用的接口 IF-MIB 模板。' : 'Templates are not applied by model automatically; select the exact devices that should use this template. This dialog only validates an enabled interface IF-MIB template.'}
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8" aria-label={zh ? '关闭' : 'Close'}>
            <X size={17} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="rounded-xl border border-[#00bceb]/20 bg-[#00bceb]/[.04] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-xs font-semibold text-[#008aad] dark:text-[#00bceb]">{template.vendor}</div>
                <div className="mt-0.5 font-mono text-base font-bold text-black/85 dark:text-white/90">{template.model}</div>
              </div>
              <span className="rounded-full bg-[#00bceb]/15 px-2 py-1 text-[10px] font-semibold text-[#007391] dark:text-[#00c2e8]">{sourceLabel}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.keys(template.metric_definitions || {}).map(key => (
                <span key={key} className="rounded bg-white/60 px-1.5 py-0.5 text-[9px] dark:bg-white/[.08]">{key}</span>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-[1.3fr_.7fr]">
            <div>
              <div className="flex items-center justify-between gap-2 text-xs font-medium text-black/70 dark:text-white/70">
                <span>{zh ? `目标设备（已选 ${selectedDeviceIds.length} 台）` : `Target devices (${selectedDeviceIds.length} selected)`}</span>
                <div className="flex items-center gap-1">
                  <button type="button" onClick={selectAllDevices} disabled={loadingDevices || devices.length === 0} className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-[#008aad] hover:bg-[#00bceb]/10 disabled:opacity-40">{zh ? '一键全选' : 'Select all'}</button>
                  <button type="button" onClick={selectAllVisible} disabled={loadingDevices || filteredDevices.length === 0} className="rounded px-1.5 py-0.5 text-[10px] text-[#008aad] hover:bg-[#00bceb]/10 disabled:opacity-40">{zh ? '选择当前结果' : 'Select visible'}</button>
                  <button type="button" onClick={clearVisible} className="rounded px-1.5 py-0.5 text-[10px] text-black/45 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8">{zh ? '清除当前' : 'Clear visible'}</button>
                </div>
              </div>
              <div className="relative mt-1.5">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
                <input value={deviceSearch} onChange={event => setDeviceSearch(event.target.value)} placeholder={zh ? '搜索主机名 / IP' : 'Search hostname / IP'} className="w-full rounded-lg border border-black/8 bg-transparent py-2 pl-8 pr-3 text-xs outline-none focus:border-[#00bceb]/55 dark:border-white/10" />
              </div>
              <div className="mt-2 max-h-[270px] overflow-y-auto rounded-xl border border-black/8 dark:border-white/10">
                {loadingDevices ? (
                  <div className="p-8 text-center text-xs text-black/40 dark:text-white/40"><Loader2 size={17} className="mx-auto mb-2 animate-spin" />{zh ? '加载设备中…' : 'Loading devices…'}</div>
                ) : filteredDevices.length === 0 ? (
                  <div className="p-8 text-center text-xs text-black/40 dark:text-white/40">{zh ? '没有可选设备' : 'No selectable devices'}</div>
                ) : filteredDevices.map(device => {
                  const checked = selectedDeviceIds.includes(device.device_id);
                  const compatible = templateCompatible(template, device);
                  return (
                    <label key={device.device_id} className={`flex items-center gap-2 border-b border-black/5 px-3 py-2.5 last:border-b-0 dark:border-white/6 ${compatible ? 'cursor-pointer' : 'cursor-not-allowed opacity-55'} ${checked ? 'bg-[#00bceb]/[.06]' : compatible ? 'hover:bg-black/[.02] dark:hover:bg-white/[.03]' : ''}`}>
                      <input type="checkbox" checked={checked} disabled={!compatible} onChange={() => toggleDevice(device.device_id)} className="accent-[#00a9ce]" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-black/80 dark:text-white/85">{device.hostname || device.device_id}</span>
                        <span className="block truncate text-[10px] text-black/45 dark:text-white/45">{device.ip_address || '-'} · {device.vendor || '-'} · {device.platform || '-'} · {device.model || '-'} · {device.version || '-'} · {device.status || (zh ? '状态未知' : 'unknown')}</span>
                      </span>
                      {hasInterfaceTemplate && <button type="button" onClick={event => { event.preventDefault(); setTestDeviceId(device.device_id); setTestResult(null); }} className={`shrink-0 rounded px-1.5 py-1 text-[9px] ${testDeviceId === device.device_id ? 'bg-[#00bceb]/15 text-[#007391] dark:text-[#00bceb]' : 'text-black/35 hover:bg-black/5 dark:text-white/35 dark:hover:bg-white/8'}`}>
                        {testDeviceId === device.device_id ? (zh ? '接口测试样例' : 'Interface test sample') : (zh ? '设为测试' : 'Test')}
                      </button>}
                      {!compatible && <span className="shrink-0 text-[9px] font-semibold text-rose-600">{zh ? '范围不匹配' : 'Out of scope'}</span>}
                    </label>
                  );
                })}
              </div>
              {hasInterfaceTemplate ? <label className="mt-2 block text-[10px] font-medium text-black/55 dark:text-white/55">
                {zh ? '测试设备' : 'Test device'}
                <select
                  aria-label={zh ? '选择测试设备' : 'Test device'}
                  value={testDeviceId}
                  onChange={event => { setTestDeviceId(event.target.value); setTestResult(null); }}
                  disabled={loadingDevices || devices.length === 0}
                  className="mt-1 w-full rounded-lg border border-black/8 bg-transparent px-3 py-2 text-xs outline-none focus:border-[#00bceb]/55 disabled:opacity-50 dark:border-white/10"
                >
                  <option value="">{loadingDevices ? (zh ? '正在加载设备…' : 'Loading devices…') : (zh ? '请选择测试设备' : 'Select a test device')}</option>
                  {devices.map(device => (
                    <option key={device.device_id} value={device.device_id}>
                      {device.hostname || device.device_id} · {device.ip_address || '-'} · {device.status || (zh ? '状态未知' : 'unknown')}
                    </option>
                  ))}
                </select>
              </label> : null}
              {loadError && <div className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/[.05] px-3 py-2 text-[10px] text-amber-800 dark:text-amber-200"><AlertTriangle size={13} className="mt-0.5 shrink-0" /><span>{loadError}</span></div>}
            </div>

            <div>
              {hasInterfaceTemplate ? <>
              <label className="block text-xs font-medium text-black/70 dark:text-white/70">
                {zh ? 'SNMP 版本' : 'SNMP version'}
                <select value={snmpVersion} onChange={event => setSnmpVersion(event.target.value as '1' | '2c')} className="mt-1.5 w-full rounded-lg border border-black/8 bg-transparent px-3 py-2 text-xs outline-none dark:border-white/10">
                  <option value="2c">SNMPv2c</option>
                  <option value="1">SNMPv1</option>
                </select>
              </label>
              <div className="mt-3 rounded-lg border border-black/8 bg-black/[.015] p-3 text-[10px] text-black/55 dark:border-white/8 dark:bg-white/[.02] dark:text-white/55">
                <div className="font-semibold text-black/70 dark:text-white/75">{zh ? '测试样例' : 'Test sample'}</div>
                <div className="mt-1">{selectedDevice ? `${selectedDevice.hostname} · ${selectedDevice.ip_address || '-'}` : (zh ? '尚未选择' : 'Not selected')}</div>
                <div className="mt-2 text-black/45 dark:text-white/45">{zh ? '此测试只校验当前样例设备上的接口 IF-MIB 配置，不采集 CPU、内存等硬件数据。' : 'This validates only the interface IF-MIB configuration on the selected sample device; it does not collect CPU, memory, or other hardware readings.'}</div>
                {selectedDevice && !testDeviceIsOnline && <div className="mt-2 flex items-start gap-1 text-amber-700 dark:text-amber-300"><AlertTriangle size={12} className="mt-0.5 shrink-0" /><span>{zh ? '设备不在线，不能实时验证接口模板，但仍可直接绑定。' : 'The device is offline, so the interface template cannot be validated live; binding is still allowed.'}</span></div>}
              </div>
              <button type="button" onClick={() => void testTemplate()} disabled={testing || !testDeviceId || !testDeviceIsOnline} className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-[#00bceb]/30 bg-[#00bceb]/10 py-2.5 text-xs font-semibold text-[#008aad] hover:bg-[#00bceb]/20 disabled:cursor-not-allowed disabled:opacity-45 dark:text-[#00bceb]">
                {testing ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                {testing ? (zh ? '接口验证中…' : 'Validating interface…') : testDeviceIsOnline ? (zh ? '验证接口模板（可选）' : 'Validate interface template') : (zh ? '设备不在线，无法验证' : 'Device offline; validation unavailable')}
              </button>
              </> : <div className="rounded-lg border border-[#00bceb]/20 bg-[#00bceb]/[.04] p-3 text-[10px] text-black/60 dark:text-white/65">
                <div className="font-semibold text-black/75 dark:text-white/80">{zh ? '硬件结果使用 LibreNMS 原生采集' : 'Hardware results use native LibreNMS collection'}</div>
                <div className="mt-1">{zh ? '此模板未启用接口 IF-MIB 验证。CPU、内存等硬件采集结果请在 SNMP 诊断页查看。' : 'This template has no enabled interface IF-MIB validation. View CPU, memory, and other native hardware collection results in SNMP diagnostics.'}</div>
                <a href="/monitor/snmp-walk" className="mt-2 inline-block font-semibold text-[#008aad] underline dark:text-[#00bceb]">{zh ? '打开 SNMP 诊断 →' : 'Open SNMP diagnostics →'}</a>
              </div>}
            </div>
          </div>

          {testResult && (
            <div className="mt-4 rounded-xl border border-black/8 bg-black/[.015] p-3 dark:border-white/8 dark:bg-white/[.02]">
              <div className="flex items-center justify-between gap-2 text-xs font-semibold text-black/80 dark:text-white/85"><span>{zh ? '接口模板验证结果' : 'Interface template validation'}</span><span className={testResult.interface?.passed ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>{testResult.interface?.passed ? (zh ? '通过' : 'Passed') : (zh ? '需关注' : 'Review')}</span></div>
              {testResult.interface && <div className="mt-2 text-[10px] text-black/60 dark:text-white/65">{testResult.interface.message || testResult.interface.status} · {testResult.interface.interfaces || 0} {zh ? '个接口' : 'interfaces'}</div>}
              {testResult.errors.map(error => <div key={error} className="mt-2 text-[10px] text-red-700 dark:text-red-300">{error}</div>)}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-black/8 px-5 py-3 dark:border-white/8">
          <button type="button" onClick={onClose} disabled={confirming} className="rounded-lg border border-black/8 px-3.5 py-1.5 text-xs font-medium text-black/60 hover:bg-black/5 disabled:opacity-45 dark:border-white/10 dark:text-white/60">{zh ? '取消' : 'Cancel'}</button>
          <button type="button" onClick={() => void confirmBinding()} disabled={(!selectedDeviceIds.length && !initialDeviceIds.length) || confirming} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-45">
            {confirming ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            {confirming ? (zh ? '保存中…' : 'Saving…') : !selectedDeviceIds.length ? (zh ? `解绑全部 ${initialDeviceIds.length} 台` : `Unbind all ${initialDeviceIds.length}`) : !testDeviceIsOnline ? (zh ? `确认绑定 ${selectedDeviceIds.length} 台（未测试）` : `Confirm binding (untested)`) : (zh ? `确认绑定 ${selectedDeviceIds.length} 台` : 'Confirm binding')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default TemplateBindingModal;
