import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, CheckCircle2, Loader2, Server, X } from 'lucide-react';
import { apiRequest } from '../../api/http';
import type { ModelPresetItem } from './PresetProfilesModal';
import type { CandidateDevice } from './components/LiveWalkInspector';

interface HardwareMetricResult {
  value?: unknown;
  raw_value?: unknown;
  status?: string;
  message?: string;
}

interface HardwareTestResult {
  status?: string;
  message?: string;
  metric_count?: number;
  metrics?: Record<string, HardwareMetricResult>;
}

interface InterfaceTestResult {
  status?: string;
  passed?: boolean;
  message?: string;
  interfaces?: number;
}

interface BindingTestResult {
  hardware?: HardwareTestResult;
  interface?: InterfaceTestResult;
  errors: string[];
}

interface DeviceListResponse {
  items?: Array<Record<string, unknown>>;
  data?: Array<Record<string, unknown>>;
}

interface BuiltinPresetBindingModalProps {
  open: boolean;
  preset: ModelPresetItem | null;
  fallbackDevice?: CandidateDevice;
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onClose: () => void;
  onConfirm: (preset: ModelPresetItem) => Promise<void>;
}

const modelKey = (value: unknown) => String(value || '').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
const vendorKey = (value: unknown) => String(value || '').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fff]+/g, '');
const statusRank = (status?: string) => String(status || '').trim().toLowerCase() === 'online' ? 0 : 1;

const displayValue = (value: unknown) => {
  if (value === undefined || value === null || value === '') return '-';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
};

const BuiltinPresetBindingModal: React.FC<BuiltinPresetBindingModalProps> = ({
  open,
  preset,
  fallbackDevice,
  language,
  showToast,
  onClose,
  onConfirm,
}) => {
  const zh = language === 'zh';
  const [devices, setDevices] = useState<CandidateDevice[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [snmpVersion, setSnmpVersion] = useState<'1' | '2c'>('2c');
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [testing, setTesting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [testResult, setTestResult] = useState<BindingTestResult | null>(null);
  const [loadError, setLoadError] = useState('');

  const selectedDevice = useMemo(
    () => devices.find(device => device.device_id === selectedDeviceId),
    [devices, selectedDeviceId],
  );
  const selectedDeviceIsOnline = String(selectedDevice?.status || '').trim().toLowerCase() === 'online';

  useEffect(() => {
    if (!open || !preset) return;
    let active = true;
    setDevices([]);
    setSelectedDeviceId('');
    setSnmpVersion('2c');
    setTestResult(null);
    setLoadError('');
    setLoadingDevices(true);

    const loadDevices = async () => {
      try {
        const response = await apiRequest<DeviceListResponse | Array<Record<string, unknown>>>(
          `/api/devices?mode=light&search=${encodeURIComponent(preset.model)}&page=1&page_size=1000&asset_type=network_device`,
        );
        const rawItems = Array.isArray(response)
          ? response
          : Array.isArray(response.items)
            ? response.items
            : Array.isArray(response.data)
              ? response.data
              : [];
        const expectedVendor = vendorKey(preset.vendor);
        const expectedModel = modelKey(preset.model);
        const matches: CandidateDevice[] = rawItems
          .filter(item => {
            const itemModel = modelKey(item.model);
            const itemVendor = vendorKey(item.vendor || item.platform);
            return itemModel === expectedModel && (!expectedVendor || !itemVendor || itemVendor === expectedVendor || itemVendor.includes(expectedVendor));
          })
          .map(item => ({
            device_id: String(item.id || ''),
            hostname: String(item.hostname || item.ip_address || item.model || ''),
            ip_address: String(item.ip_address || item.management_ip || ''),
            status: String(item.status || ''),
          }))
          .filter(item => item.device_id);

        if (fallbackDevice?.device_id && !matches.some(item => item.device_id === fallbackDevice.device_id)) {
          matches.push(fallbackDevice);
        }
        matches.sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.hostname.localeCompare(b.hostname));
        if (!active) return;
        setDevices(matches);
        setSelectedDeviceId(matches[0]?.device_id || '');
        if (matches.length === 0) {
          setLoadError(zh ? '未找到与该型号匹配的受管设备' : 'No managed device matched this model');
        }
      } catch (error) {
        if (!active) return;
        if (fallbackDevice?.device_id) {
          setDevices([fallbackDevice]);
          setSelectedDeviceId(fallbackDevice.device_id);
        } else {
          setLoadError(error instanceof Error ? error.message : zh ? '设备列表加载失败' : 'Failed to load devices');
        }
      } finally {
        if (active) setLoadingDevices(false);
      }
    };

    void loadDevices();
    return () => {
      active = false;
    };
  }, [open, preset, fallbackDevice, zh]);

  if (!open || !preset) return null;

  const hardwarePassed = testResult?.hardware?.status === 'ok';
  const interfacePassed = !preset.interface_config?.enabled || testResult?.interface?.passed === true;
  const canTest = Boolean(selectedDeviceId && selectedDeviceIsOnline);
  const canConfirm = Boolean(
    selectedDeviceId &&
    (!selectedDeviceIsOnline || Boolean(testResult && testResult.errors.length === 0 && hardwarePassed && interfacePassed)),
  );

  const testPreset = async () => {
    if (!selectedDeviceId) {
      showToast(zh ? '请先选择一台设备' : 'Select a device first', 'error');
      return;
    }
    if (!selectedDeviceIsOnline) {
      showToast(zh ? '当前设备不在线，无法测试；仍可直接绑定模板' : 'This device is offline, so it cannot be tested; you can still bind the template', 'info');
      return;
    }
    setTesting(true);
    setTestResult(null);
    const result: BindingTestResult = { errors: [] };
    try {
      const requests: Array<Promise<unknown>> = [
        apiRequest<{ success: boolean; data: HardwareTestResult }>(
          '/api/platform-registry/snmp-hardware-test',
          {
            method: 'POST',
            body: JSON.stringify({
              device_id: selectedDeviceId,
              version: snmpVersion,
              include_default_metrics: true,
              metric_definitions: preset.metric_definitions,
            }),
          },
        ),
      ];
      if (preset.interface_config?.enabled) {
        requests.push(
          apiRequest<{ success: boolean; data: InterfaceTestResult }>(
            '/api/platform-registry/snmp-interface-test',
            {
              method: 'POST',
              body: JSON.stringify({
                device_id: selectedDeviceId,
                version: snmpVersion,
                interface_config: preset.interface_config,
              }),
            },
          ),
        );
      }
      const responses = await Promise.allSettled(requests);
      const hardwareResponse = responses[0];
      if (hardwareResponse.status === 'fulfilled') {
        result.hardware = (hardwareResponse.value as { data: HardwareTestResult }).data;
      } else {
        result.errors.push(zh ? '硬件指标测试失败' : 'Hardware metric test failed');
      }
      const interfaceResponse = responses[1];
      if (interfaceResponse) {
        if (interfaceResponse.status === 'fulfilled') {
          result.interface = (interfaceResponse.value as { data: InterfaceTestResult }).data;
        } else {
          result.errors.push(zh ? '接口指标测试失败' : 'Interface metric test failed');
        }
      }
      setTestResult(result);
      showToast(
        result.errors.length === 0 && result.hardware?.status === 'ok'
          ? (zh ? '测试通过，请确认绑定模板' : 'Test passed; confirm the template binding')
          : (zh ? '测试未通过，暂不能绑定' : 'Test did not pass; binding is not available'),
        result.errors.length === 0 && result.hardware?.status === 'ok' ? 'success' : 'error',
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : zh ? '模板测试失败' : 'Template test failed';
      setTestResult({ errors: [message] });
      showToast(message, 'error');
    } finally {
      setTesting(false);
    }
  };

  const confirmBinding = async () => {
    if (!canConfirm) return;
    setConfirming(true);
    try {
      await onConfirm(preset);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[160] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="flex max-h-[88vh] w-full max-w-[720px] flex-col overflow-hidden rounded-2xl border border-[#00bceb]/25 bg-[var(--card-bg)] shadow-2xl dark:border-white/10" onMouseDown={event => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-black/8 px-5 py-4 dark:border-white/8">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-black/85 dark:text-white/90">
              <Server size={17} className="text-[#009ec4]" />
              {zh ? '测试并绑定官方 SNMP 模板' : 'Test and bind official SNMP template'}
            </div>
            <div className="mt-1 text-[11px] text-black/45 dark:text-white/45">
              {zh ? '选择一台匹配设备作为测试样例 → 查看数据 → 确认后绑定该型号。所选设备仅用于测试，测试前不会修改配置。' : 'Select a matched device as the test sample → review the data → confirm to bind this model. The selected device is only for testing; nothing changes before confirmation.'}
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
                <div className="text-xs font-semibold text-[#008aad] dark:text-[#00bceb]">{preset.vendor}</div>
                <div className="mt-0.5 font-mono text-base font-bold text-black/85 dark:text-white/90">{preset.model}</div>
              </div>
              <span className="rounded-full bg-[#00bceb]/15 px-2 py-1 text-[10px] font-semibold text-[#007391] dark:text-[#00c2e8]">
                {zh ? '官方内置模板' : 'Official built-in'}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {Object.keys(preset.metric_definitions || {}).map(key => (
                <span key={key} className="rounded bg-white/60 px-1.5 py-0.5 text-[9px] dark:bg-white/[.08]">{key}</span>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
            <label className="block text-xs font-medium text-black/70 dark:text-white/70">
              {zh ? '选择测试设备' : 'Test device'}
              <select
                aria-label={zh ? '选择测试设备' : 'Test device'}
                value={selectedDeviceId}
                onChange={event => {
                  setSelectedDeviceId(event.target.value);
                  setTestResult(null);
                }}
                disabled={loadingDevices || devices.length === 0}
                className="mt-1 w-full rounded-lg border border-black/8 bg-transparent px-3 py-2 text-xs outline-none focus:border-[#00bceb]/55 disabled:opacity-50 dark:border-white/10"
              >
                <option value="">{loadingDevices ? (zh ? '正在加载匹配设备…' : 'Loading matched devices…') : zh ? '请选择设备' : 'Select a device'}</option>
                {devices.map(device => (
                  <option key={device.device_id} value={device.device_id}>
                    {device.hostname || device.ip_address || device.device_id} · {device.ip_address || '-'} · {device.status || (zh ? '状态未知' : 'unknown')}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-medium text-black/70 dark:text-white/70">
              {zh ? 'SNMP 版本' : 'SNMP version'}
              <select value={snmpVersion} onChange={event => setSnmpVersion(event.target.value as '1' | '2c')} className="mt-1 w-full rounded-lg border border-black/8 bg-transparent px-3 py-2 text-xs outline-none dark:border-white/10">
                <option value="2c">SNMPv2c</option>
                <option value="1">SNMPv1</option>
              </select>
            </label>
          </div>
          {selectedDevice && (
            <div className="mt-1.5 text-[10px] text-emerald-700 dark:text-emerald-400">
              ✓ {selectedDevice.hostname} · {selectedDevice.ip_address || '-'} · {selectedDevice.status || (zh ? '状态未知' : 'status unknown')}
            </div>
          )}
          {selectedDevice && !selectedDeviceIsOnline && (
            <div className="mt-2 flex items-start gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/[.05] px-3 py-2 text-[10px] text-amber-800 dark:text-amber-200">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>{zh ? '当前设备不在线或状态未知，无法实时测试；这不影响模板绑定。' : 'This device is offline or its status is unknown, so live testing is unavailable; binding is still allowed.'}</span>
            </div>
          )}
          {loadError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/[.05] px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>{loadError}。{zh ? '请返回列表新建自定义模板。' : 'Return to the list and create a custom template.'}</span>
            </div>
          )}

          <button type="button" onClick={() => void testPreset()} disabled={testing || loadingDevices || !canTest} className="mt-4 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#00a9ce] py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:cursor-not-allowed disabled:opacity-45">
            {testing ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {testing ? (zh ? '测试中…' : 'Testing…') : canTest ? (zh ? '测试模板' : 'Test template') : (zh ? '设备不在线，无法测试' : 'Device offline; test unavailable')}
          </button>

          {testResult && (
            <div className="mt-4 rounded-xl border border-black/8 bg-black/[.015] p-3 dark:border-white/8 dark:bg-white/[.02]">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-semibold text-black/80 dark:text-white/85">{zh ? '测试结果' : 'Test result'}</div>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${canConfirm ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'bg-red-500/10 text-red-700 dark:text-red-300'}`}>
                  {canConfirm ? (zh ? '通过' : 'Passed') : (zh ? '未通过' : 'Failed')}
                </span>
              </div>
              {testResult.hardware && (
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
                  {Object.entries(testResult.hardware.metrics || {}).map(([key, detail]) => (
                    <div key={key} className="rounded-lg border border-black/6 bg-white/55 px-2.5 py-2 dark:border-white/8 dark:bg-white/[.03]">
                      <div className="flex items-center justify-between gap-2 text-[10px]">
                        <span className="font-medium">{key}</span>
                        <span className={detail.status === 'ok' ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>{detail.status || '-'}</span>
                      </div>
                      <div className="mt-1 font-mono text-sm text-black/75 dark:text-white/80">{displayValue(detail.value)}</div>
                    </div>
                  ))}
                </div>
              )}
              {testResult.interface && (
                <div className="mt-2 rounded-lg border border-violet-500/15 bg-violet-500/[.04] px-2.5 py-2 text-[10px] text-black/65 dark:text-white/70">
                  {zh ? '接口指标' : 'Interface metrics'}：{testResult.interface.passed ? (zh ? '通过' : 'passed') : (testResult.interface.status || (zh ? '失败' : 'failed'))} · {testResult.interface.interfaces || 0} {zh ? '个接口' : 'interfaces'}
                </div>
              )}
              {testResult.errors.map(error => <div key={error} className="mt-2 text-[10px] text-red-700 dark:text-red-300">{error}</div>)}
              {testResult.hardware?.message && <div className="mt-2 text-[10px] text-black/45 dark:text-white/45">{testResult.hardware.message}</div>}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-black/8 px-5 py-3 dark:border-white/8">
          <button type="button" onClick={onClose} disabled={confirming} className="rounded-lg border border-black/8 px-3.5 py-1.5 text-xs font-medium text-black/60 hover:bg-black/5 disabled:opacity-45 dark:border-white/10 dark:text-white/60">{zh ? '取消' : 'Cancel'}</button>
          <button type="button" onClick={() => void confirmBinding()} disabled={!canConfirm || confirming} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-45">
            {confirming ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            {confirming ? (zh ? '绑定中…' : 'Binding…') : !selectedDeviceIsOnline ? (zh ? '确认绑定（未测试）' : 'Confirm binding (untested)') : zh ? '确认绑定模板' : 'Confirm binding'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default BuiltinPresetBindingModal;
