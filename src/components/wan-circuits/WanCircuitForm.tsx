import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Save, X } from 'lucide-react';
import { ActionButton } from '../ui/ActionIconButton';
import { SelectField, TextField } from '../ui/FormField';
import { primaryActionBtnClass, secondaryActionBtnClass } from '../shared';
import type { WanCircuitEndpoint, WanCircuitFormPayload, WanCircuitItem, WanCircuitOptions } from '../../types/wan-circuits';

interface Props {
  item: WanCircuitItem | null;
  options: WanCircuitOptions;
  language: 'zh' | 'en';
  saving?: boolean;
  onRefreshDeviceInterfaces: (deviceId: string, action: 'create' | 'update') => Promise<void>;
  onSubmit: (payload: WanCircuitFormPayload) => void;
  onClose: () => void;
}

interface FormState {
  link_name: string;
  site_id: string;
  device_id: string;
  interface_id: string;
  provider: string;
  circuit_number: string;
  // Round-trip the legacy API value without exposing its ambiguous meaning in the form.
  public_ip: string;
  link_type: string;
  link_role: string;
  asymmetricBandwidth: boolean;
  direction_mode: 'normal' | 'reversed';
  contracted_download_mbps: string;
  contracted_upload_mbps: string;
  collection_interval_sec: string;
  customCollectionInterval: boolean;
  timezone: string;
  customTimezone: boolean;
  enabled: boolean;
  notes: string;
  aMeasurementScope: 'dedicated' | 'shared_interface';
  zEndpoint: WanCircuitEndpoint;
}

const defaultZEndpoint = (item: WanCircuitItem | null): WanCircuitEndpoint => {
  const endpoint = item?.endpoints?.find((candidate) => candidate.side === 'Z');
  return endpoint
    ? {
        ...endpoint,
        side: 'Z',
        endpoint_type: endpoint.endpoint_type || 'unmanaged',
        site_id: endpoint.site_id || '',
        counter_orientation: endpoint.counter_orientation || 'normal',
        measurement_scope: endpoint.measurement_scope || 'shared_interface',
      }
    : {
        side: 'Z',
        endpoint_type: 'unmanaged',
        site_id: item?.site_id || '',
        endpoint_name: '',
        counter_orientation: 'normal',
        measurement_scope: 'shared_interface',
      };
};

const initialState = (item: WanCircuitItem | null, language: 'zh' | 'en'): FormState => ({
  link_name: item?.link_name || '',
  site_id: item?.site_id || '',
  device_id: item?.device_id || '',
  interface_id: item?.interface_id || '',
  provider: item?.provider || '',
  circuit_number: item?.circuit_number || '',
  public_ip: item?.public_ip || '',
  link_type: item?.link_type || (language === 'zh' ? '互联网出口' : 'Internet'),
  link_role: item?.link_role || 'standalone',
  asymmetricBandwidth: Boolean(item?.contracted_download_bps && item?.contracted_upload_bps && item.contracted_download_bps !== item.contracted_upload_bps),
  direction_mode: item?.direction_mode === 'reversed' ? 'reversed' : 'normal',
  contracted_download_mbps: item?.contracted_download_bps ? String(item.contracted_download_bps / 1_000_000) : '',
  contracted_upload_mbps: item?.contracted_upload_bps ? String(item.contracted_upload_bps / 1_000_000) : '',
  collection_interval_sec: item?.collection_interval_sec ? String(item.collection_interval_sec) : '60',
  customCollectionInterval: Boolean(item?.collection_interval_sec && item.collection_interval_sec !== 60),
  timezone: item?.timezone || 'Asia/Shanghai',
  customTimezone: false,
  enabled: item?.enabled !== false && item?.enabled !== 0,
  notes: item?.notes || '',
  aMeasurementScope: item?.endpoints?.find((endpoint) => endpoint.side === 'A')?.measurement_scope || 'shared_interface',
  zEndpoint: defaultZEndpoint(item),
});

const hasValidIfIndex = (ifIndex: number | null | undefined): ifIndex is number => typeof ifIndex === 'number' && Number.isInteger(ifIndex) && ifIndex > 0;

export const WanCircuitForm: React.FC<Props> = ({ item, options, language, saving, onRefreshDeviceInterfaces, onSubmit, onClose }) => {
  const zh = language === 'zh';
  const [form, setForm] = useState<FormState>(() => initialState(item, language));
  const [validationError, setValidationError] = useState('');
  const [interfaceRefreshing, setInterfaceRefreshing] = useState({ A: false, Z: false });
  const [interfaceRefreshErrors, setInterfaceRefreshErrors] = useState<{ A: string; Z: string }>({ A: '', Z: '' });
  const refreshSequence = useRef({ A: 0, Z: 0 });

  useEffect(() => {
    setForm(initialState(item, language));
    setValidationError('');
    setInterfaceRefreshing({ A: false, Z: false });
    setInterfaceRefreshErrors({ A: '', Z: '' });
    refreshSequence.current = { A: 0, Z: 0 };
  }, [item, language]);

  const visibleDevices = useMemo(
    () => (form.site_id ? options.devices.filter((device) => device.site_id === form.site_id) : options.devices),
    [form.site_id, options.devices],
  );
  const visibleInterfaces = useMemo(
    () => (form.device_id ? options.interfaces.filter((entry) => entry.device_id === form.device_id && hasValidIfIndex(entry.if_index)) : []),
    [form.device_id, options.interfaces],
  );
  const zDevices = useMemo(
    () => (form.zEndpoint.site_id ? options.devices.filter((device) => device.site_id === form.zEndpoint.site_id) : options.devices),
    [form.zEndpoint.site_id, options.devices],
  );
  const zInterfaces = useMemo(
    () => (form.zEndpoint.device_id ? options.interfaces.filter((entry) => entry.device_id === form.zEndpoint.device_id && hasValidIfIndex(entry.if_index)) : []),
    [form.zEndpoint.device_id, options.interfaces],
  );
  const aDevice = visibleDevices.find((device) => device.id === form.device_id);
  const aInterface = visibleInterfaces.find((entry) => entry.id === form.interface_id);
  const zInterface = zInterfaces.find((entry) => entry.id === form.zEndpoint.interface_id);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };
  const updateBandwidth = (direction: 'download' | 'upload', value: string) => {
    setForm((current) => {
      if (direction === 'download') {
        return {
          ...current,
          contracted_download_mbps: value,
          ...(current.asymmetricBandwidth ? {} : { contracted_upload_mbps: value }),
        };
      }
      return { ...current, contracted_upload_mbps: value };
    });
  };
  const setAsymmetricBandwidth = (checked: boolean) => {
    setForm((current) => ({
      ...current,
      asymmetricBandwidth: checked,
      ...(checked ? {} : { contracted_upload_mbps: current.contracted_download_mbps }),
    }));
  };
  const updateZ = (patch: Partial<WanCircuitEndpoint>) => {
    setForm((current) => ({ ...current, zEndpoint: { ...current.zEndpoint, ...patch, side: 'Z' } }));
  };
  const refreshDeviceInterfaces = async (side: 'A' | 'Z', deviceId: string) => {
    const sequence = ++refreshSequence.current[side];
    if (!deviceId) {
      setInterfaceRefreshing((current) => ({ ...current, [side]: false }));
      setInterfaceRefreshErrors((current) => ({ ...current, [side]: '' }));
      return;
    }
    setInterfaceRefreshing((current) => ({ ...current, [side]: true }));
    setInterfaceRefreshErrors((current) => ({ ...current, [side]: '' }));
    try {
      await onRefreshDeviceInterfaces(deviceId, item ? 'update' : 'create');
    } catch (error) {
      if (refreshSequence.current[side] === sequence) {
        setInterfaceRefreshErrors((current) => ({
          ...current,
          [side]: error instanceof Error ? error.message : (zh ? '读取端口失败，请重试。' : 'Failed to read ports. Please retry.'),
        }));
      }
    } finally {
      if (refreshSequence.current[side] === sequence) {
        setInterfaceRefreshing((current) => ({ ...current, [side]: false }));
      }
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const down = Number(form.contracted_download_mbps);
    const up = Number(form.asymmetricBandwidth ? form.contracted_upload_mbps : form.contracted_download_mbps);
    if (!form.link_name.trim() || !form.site_id || !form.device_id || !form.interface_id || !Number.isFinite(down) || down <= 0 || down > 10_000_000 || !Number.isFinite(up) || up <= 0 || up > 10_000_000) {
      setValidationError(zh ? '请填写线路名称、本端站点/设备/端口及有效带宽（大于 0，最多 10,000,000 Mbps）。' : 'Circuit name, local site/device/port and valid capacity (over 0 and at most 10,000,000 Mbps) are required.');
      return;
    }
    const collectionInterval = Number(form.collection_interval_sec);
    if (form.customCollectionInterval && (!Number.isInteger(collectionInterval) || collectionInterval < 30 || collectionInterval > 3600)) {
      setValidationError(zh ? '自定义采集间隔必须是 30 至 3,600 秒之间的整数。' : 'The custom collection interval must be a whole number between 30 and 3,600 seconds.');
      return;
    }
    if (!aDevice || !aInterface || !hasValidIfIndex(aInterface.if_index)) {
      setValidationError(zh ? 'A 端端口信息已失效。请重新选择设备，系统会自动读取端口后再保存。' : 'The A-side port information is stale. Select the device again to refresh its ports before saving.');
      return;
    }
    if (form.zEndpoint.endpoint_type === 'managed' && (!form.zEndpoint.site_id || !form.zEndpoint.device_id || !form.zEndpoint.interface_id)) {
      setValidationError(zh ? '请选择 Z 端（线路对端）的站点、设备和接口。' : 'Select a site, device and interface for the managed Z endpoint.');
      return;
    }
    if (form.zEndpoint.endpoint_type === 'managed' && (!zInterface || !hasValidIfIndex(zInterface.if_index) || !zDevices.some((device) => device.id === form.zEndpoint.device_id))) {
      setValidationError(zh ? 'Z 端端口信息已失效，或所选设备与站点不匹配。请重新选择站点和设备。' : 'The Z-side port is stale, or its device does not belong to the selected site. Select the site and device again.');
      return;
    }
    if (form.zEndpoint.endpoint_type === 'unmanaged' && !form.zEndpoint.endpoint_name?.trim()) {
      setValidationError(zh ? '请填写线路对端名称。' : 'Enter a name for the remote circuit endpoint.');
      return;
    }

    const aEndpoint: WanCircuitEndpoint = {
      side: 'A',
      endpoint_type: 'managed',
      site_id: form.site_id,
      device_id: form.device_id,
      interface_id: form.interface_id,
      endpoint_name: aInterface.interface_name,
      if_index: aInterface.if_index,
      counter_orientation: form.direction_mode,
      measurement_scope: form.aMeasurementScope,
    };
    const zEndpoint: WanCircuitEndpoint = {
      ...form.zEndpoint,
      side: 'Z',
      site_id: form.zEndpoint.site_id || '',
      endpoint_name: form.zEndpoint.endpoint_type === 'managed'
        ? (zInterface?.interface_name || String(form.zEndpoint.endpoint_name || '').trim())
        : String(form.zEndpoint.endpoint_name || '').trim(),
      ...(form.zEndpoint.endpoint_type === 'unmanaged' ? { device_id: null, interface_id: null, if_index: null } : {}),
    };
    if (form.zEndpoint.endpoint_type === 'managed') zEndpoint.if_index = zInterface?.if_index ?? null;

    onSubmit({
      id: item?.id,
      link_name: form.link_name.trim(),
      site_id: form.site_id,
      device_id: form.device_id,
      interface_id: form.interface_id,
      provider: form.provider.trim(),
      circuit_number: form.circuit_number.trim(),
      public_ip: form.public_ip.trim(),
      link_type: form.link_type.trim() || 'Internet',
      link_role: form.link_role,
      direction_mode: form.direction_mode,
      contracted_download_mbps: down,
      contracted_upload_mbps: up,
      collection_interval_sec: form.customCollectionInterval ? Math.max(30, Number(form.collection_interval_sec || 60)) : 60,
      timezone: form.timezone || 'Asia/Shanghai',
      enabled: form.enabled,
      notes: form.notes.trim(),
      endpoints: [aEndpoint, zEndpoint],
      expected_version: item?.configuration_version,
    });
  };

  const noAInterfaces = Boolean(form.device_id) && visibleInterfaces.length === 0;
  const aInterfaceHelp: React.ReactNode = interfaceRefreshing.A
    ? (zh ? '正在从所选设备读取端口，请稍候…' : 'Reading ports from the selected device…')
    : interfaceRefreshErrors.A
      ? <>{zh ? `自动读取失败：${interfaceRefreshErrors.A} ` : `Automatic refresh failed: ${interfaceRefreshErrors.A} `}<button type="button" className="font-semibold underline underline-offset-2" onClick={() => void refreshDeviceInterfaces('A', form.device_id)}>{zh ? '重试' : 'Retry'}</button></>
      : !form.device_id
        ? (zh ? '选择设备后，系统会自动读取该设备的端口。' : 'The device ports are loaded automatically after you choose a device.')
        : noAInterfaces
          ? (zh ? '没有可用端口。请确认设备已配置 SNMP 只读凭据和 IF-MIB 只读权限。' : 'No ports are available. Confirm SNMP read-only credentials and IF-MIB read access are configured.')
          : (zh ? '请选择实际连接运营商线路的端口；不要选择管理口或内网口。' : 'Choose the port connected to the carrier circuit; do not select a management or LAN port.');
  const zInterfaceHelp: React.ReactNode = interfaceRefreshing.Z
    ? (zh ? '正在从对端设备读取端口，请稍候…' : 'Reading ports from the remote device…')
    : interfaceRefreshErrors.Z
      ? <>{zh ? `自动读取失败：${interfaceRefreshErrors.Z} ` : `Automatic refresh failed: ${interfaceRefreshErrors.Z} `}<button type="button" className="font-semibold underline underline-offset-2" onClick={() => void refreshDeviceInterfaces('Z', form.zEndpoint.device_id || '')}>{zh ? '重试' : 'Retry'}</button></>
      : !form.zEndpoint.device_id
        ? (zh ? '选择对端设备后，系统会自动读取该设备的端口。' : 'The remote device ports are loaded automatically after you choose a device.')
        : zInterfaces.length === 0
          ? (zh ? '没有可用端口。请确认设备已配置 SNMP 只读凭据和 IF-MIB 只读权限。' : 'No ports are available. Confirm SNMP read-only credentials and IF-MIB read access are configured.')
          : (zh ? '选择实际连接本条专线的端口。' : 'Choose the port connected to this circuit.');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-labelledby="wan-circuit-form-title">
      <form onSubmit={submit} className="max-h-[90vh] w-full max-w-5xl overflow-y-auto rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--ui-accent)]">{item ? (zh ? '编辑线路' : 'Edit circuit') : (zh ? '注册线路' : 'Register circuit')}</p>
            <h2 id="wan-circuit-form-title" className="mt-1 text-base font-bold text-[var(--heading-text)]">{item?.link_name || (zh ? '新专线' : 'New circuit')}</h2>
          </div>
          <ActionButton icon={X} size="sm" onClick={onClose}>{zh ? '关闭' : 'Close'}</ActionButton>
        </div>

        <section className="mt-4 rounded-xl border border-[var(--ui-border)] p-4">
          <div className="mb-3">
            <h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? '线路信息' : 'Circuit information'}</h3>
            <p className="mt-1 text-[11px] text-[var(--muted-text)]">{zh ? '先描述线路本身；设备和端口在下一步选择。' : 'Describe the circuit first, then choose its devices and ports.'}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <TextField label={zh ? '线路名称 *' : 'Circuit name *'} value={form.link_name} onChange={(value) => update('link_name', value)} placeholder={zh ? '例如：武汉至上海电信专线' : 'e.g. Wuhan–Shanghai Telecom'} />
            <TextField label={zh ? '运营商' : 'Provider'} value={form.provider} onChange={(value) => update('provider', value)} suggestions={zh ? ['中国电信', '中国联通', '中国移动', '中国广电', '中国教育和科研计算机网', '阿里云', '腾讯云', '华为云', '其他'] : ['China Telecom', 'China Unicom', 'China Mobile', 'China Broadnet', 'CERNET', 'Alibaba Cloud', 'Tencent Cloud', 'Huawei Cloud', 'Other']} placeholder={zh ? '常见运营商可选，也可直接输入' : 'Choose a common provider or enter a custom value'} />
            <TextField label={zh ? '运营商电路编号' : 'Carrier circuit number'} value={form.circuit_number} onChange={(value) => update('circuit_number', value)} helperText={zh ? '填写合同、账单或运营商工单上的线路编号。' : 'Use the circuit ID from the contract or carrier ticket.'} />
            <TextField label={zh ? '线路用途' : 'Circuit purpose'} value={form.link_type} onChange={(value) => update('link_type', value)} suggestions={zh ? ['互联网出口', 'MPLS 专线', 'SD-WAN', 'IDC 互联', '云专线', '分支互联', '其他'] : ['Internet', 'MPLS', 'SD-WAN', 'IDC interconnect', 'Cloud circuit', 'Branch interconnect', 'Other']} placeholder={zh ? '例如：互联网出口、MPLS、云专线' : 'e.g. Internet, MPLS, cloud circuit'} />
            <SelectField
              label={zh ? '冗余角色' : 'Redundancy role'}
              value={form.link_role}
              onChange={(value) => update('link_role', value)}
              options={[
                { value: 'standalone', label: zh ? '单线路' : 'Standalone' },
                { value: 'primary', label: zh ? '主线路' : 'Primary' },
                { value: 'backup', label: zh ? '备用线路' : 'Backup' },
                { value: 'load_balanced', label: zh ? '负载分担' : 'Load balanced' },
              ]}
              language={language}
              helperText={zh ? '单条线路选“单线路”；只有与其他线路组成冗余组时才选主线路、备用线路或负载分担。' : 'Choose Standalone for an independent circuit. Other roles apply only within a redundancy group.'}
            />
            <div className="sm:col-span-2 lg:col-span-3 rounded-lg bg-[var(--ui-surface-muted)] p-3">
              <TextField
                label={form.asymmetricBandwidth ? (zh ? '对端 → 本端（Z→A，下行 Mbps）' : 'Remote → local (Z→A, download Mbps)') : (zh ? '双向对称带宽（Mbps）' : 'Symmetric bandwidth (Mbps)')}
                type="number"
                min={0}
                max={10_000_000}
                step="any"
                value={form.contracted_download_mbps}
                onChange={(value) => updateBandwidth('download', value)}
                placeholder={zh ? '例如：100' : 'e.g. 100'}
                helperText={form.asymmetricBandwidth ? (zh ? '合同规定的数据从线路对端进入本端的带宽。' : 'Contracted capacity from the remote endpoint into the local endpoint.') : (zh ? '上下行相同的线路只需填写一次；系统会将相同带宽用于两个方向。' : 'For equal capacity in both directions, enter the value once.')}
              />
              <label className="mt-3 flex items-center gap-2 text-xs font-semibold text-[var(--heading-text)]">
                <input type="checkbox" checked={form.asymmetricBandwidth} onChange={(event) => setAsymmetricBandwidth(event.target.checked)} />
                {zh ? '上下行合同带宽不同（非对称）' : 'Different capacity in each direction (asymmetric)'}
              </label>
              {form.asymmetricBandwidth && (
                <TextField
                  className="mt-3"
                  label={zh ? '本端 → 对端（A→Z，上行 Mbps）' : 'Local → remote (A→Z, upload Mbps)'}
                  type="number"
                  min={0}
                  max={10_000_000}
                  step="any"
                  value={form.contracted_upload_mbps}
                  onChange={(value) => updateBandwidth('upload', value)}
                  placeholder={zh ? '例如：50' : 'e.g. 50'}
                  helperText={zh ? '合同规定的数据从本端发往线路对端的带宽。' : 'Contracted capacity from the local endpoint to the remote endpoint.'}
                />
              )}
            </div>
          </div>
        </section>

        <section className="mt-4 rounded-xl border border-[var(--ui-border)] p-4">
          <div className="mb-3">
            <h3 className="text-sm font-bold text-[var(--heading-text)]">{zh ? '线路两端' : 'Circuit endpoints'}</h3>
            <p className="mt-1 text-[11px] leading-5 text-[var(--muted-text)]">
              {zh ? 'A、Z 只是线路两端的代号，不代表上行或下行。本端用于采集线路流量；如果对端也是本系统纳管设备，可选择它并自动读取端口。' : 'A and Z are endpoint labels, not traffic directions. The local end anchors collection; choose a managed remote device to read its port too.'}
            </p>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3">
              <div className="mb-3">
                <h4 className="text-xs font-bold text-[var(--heading-text)]">{zh ? '本端（A 端）' : 'Local endpoint (A)'}</h4>
                <p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? '选择本系统用于监控这条专线的站点、设备和端口。' : 'Select the site, device and port used to monitor this circuit.'}</p>
              </div>
              <div className="space-y-3">
                <SelectField
                  label={zh ? '本端站点 *' : 'Local site *'}
                  value={form.site_id}
                  onChange={(value) => {
                    const selectedSite = options.sites.find((site) => site.id === value);
                    update('site_id', value);
                    update('device_id', '');
                    update('interface_id', '');
                    update('timezone', selectedSite?.timezone || 'Asia/Shanghai');
                    update('customTimezone', false);
                    void refreshDeviceInterfaces('A', '');
                  }}
                  options={options.sites.map((site) => ({ value: site.id, label: site.site_name }))}
                  language={language}
                />
                <SelectField
                  label={zh ? '本端设备 *' : 'Local device *'}
                  value={form.device_id}
                  onChange={(value) => {
                    update('device_id', value);
                    update('interface_id', '');
                    void refreshDeviceInterfaces('A', value);
                  }}
                  options={visibleDevices.map((device) => ({ value: device.id, label: device.hostname || device.ip_address || (zh ? '未命名设备' : 'Unnamed device') }))}
                  language={language}
                />
                <SelectField
                  label={zh ? '本端连接专线的端口 *' : 'Local circuit port *'}
                  value={form.interface_id}
                  onChange={(value) => update('interface_id', value)}
                  options={visibleInterfaces.map((entry) => ({ value: entry.id, label: entry.interface_name }))}
                  language={language}
                  disabled={interfaceRefreshing.A}
                  helperText={aInterfaceHelp}
                  helperTone={interfaceRefreshErrors.A || noAInterfaces ? 'warning' : 'neutral'}
                  helperRole={interfaceRefreshErrors.A ? 'alert' : noAInterfaces ? 'status' : undefined}
                />
              </div>
              <p className="mt-3 rounded-md bg-[var(--ui-surface)] px-2.5 py-2 text-[10px] text-[var(--muted-text)]">
                {options.sites.find((site) => site.id === form.site_id)?.site_name || (zh ? '未选择站点' : 'No site selected')}
                {' · '}{aDevice?.hostname || aDevice?.ip_address || (zh ? '未选择设备' : 'No device selected')}
                {' · '}{aInterface?.interface_name || (zh ? '尚未选择端口' : 'No port selected')}
              </p>
            </div>

            <div className="rounded-lg border border-[var(--ui-border)] p-3">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <h4 className="text-xs font-bold text-[var(--heading-text)]">{zh ? '线路对端（Z 端）' : 'Remote endpoint (Z)'}</h4>
                  <p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? '与本端结构一致；差别只在于对端是否由本系统纳管。' : 'The same endpoint structure; the only difference is whether Nexora manages the remote device.'}</p>
                </div>
                <div className="w-48 shrink-0">
                  <SelectField
                    label={zh ? '对端类型' : 'Remote endpoint type'}
                    value={form.zEndpoint.endpoint_type}
                    onChange={(value) => {
                      updateZ({ endpoint_type: value as 'managed' | 'unmanaged', device_id: null, interface_id: null, if_index: null });
                      void refreshDeviceInterfaces('Z', '');
                    }}
                    options={[
                      { value: 'managed', label: zh ? '本系统已纳管设备' : 'Managed device' },
                      { value: 'unmanaged', label: zh ? '外部/未纳管对端' : 'External or unmanaged' },
                    ]}
                    language={language}
                  />
                </div>
              </div>
              {form.zEndpoint.endpoint_type === 'managed' ? (
                <div className="space-y-3">
                  <SelectField
                    label={zh ? '对端站点 *' : 'Remote site *'}
                    value={form.zEndpoint.site_id}
                    onChange={(value) => {
                      updateZ({ site_id: value, device_id: null, interface_id: null, if_index: null });
                      void refreshDeviceInterfaces('Z', '');
                    }}
                    options={options.sites.map((site) => ({ value: site.id, label: site.site_name }))}
                    language={language}
                  />
                  <SelectField
                    label={zh ? '对端设备 *' : 'Remote device *'}
                    value={form.zEndpoint.device_id || ''}
                    onChange={(value) => {
                      updateZ({ device_id: value, interface_id: null, if_index: null });
                      void refreshDeviceInterfaces('Z', value);
                    }}
                    options={zDevices.map((device) => ({ value: device.id, label: device.hostname || device.ip_address || (zh ? '未命名设备' : 'Unnamed device') }))}
                    language={language}
                  />
                  <SelectField
                    label={zh ? '对端连接专线的端口 *' : 'Remote circuit port *'}
                    value={form.zEndpoint.interface_id || ''}
                    onChange={(value) => updateZ({ interface_id: value, if_index: zInterfaces.find((entry) => entry.id === value)?.if_index ?? null })}
                    options={zInterfaces.map((entry) => ({ value: entry.id, label: entry.interface_name }))}
                    language={language}
                    disabled={interfaceRefreshing.Z}
                    helperText={zInterfaceHelp}
                    helperTone={interfaceRefreshErrors.Z || (Boolean(form.zEndpoint.device_id) && zInterfaces.length === 0) ? 'warning' : 'neutral'}
                    helperRole={interfaceRefreshErrors.Z ? 'alert' : Boolean(form.zEndpoint.device_id) && zInterfaces.length === 0 ? 'status' : undefined}
                  />
                </div>
              ) : (
                <div className="space-y-3">
                  <SelectField
                    label={zh ? '对端站点（可选）' : 'Remote site (optional)'}
                    value={form.zEndpoint.site_id}
                    onChange={(value) => updateZ({ site_id: value })}
                    options={options.sites.map((site) => ({ value: site.id, label: site.site_name }))}
                    language={language}
                    helperText={zh ? '知道对端所在站点时选择；例如分支机构或运营商机房。' : 'Choose the site if known.'}
                  />
                  <TextField
                    label={zh ? '对端名称 *' : 'Remote endpoint name *'}
                    value={form.zEndpoint.endpoint_name || ''}
                    onChange={(value) => updateZ({ endpoint_name: value })}
                    placeholder={zh ? '例如：上海分公司路由器 / 运营商交接点' : 'e.g. Shanghai branch router / carrier handoff'}
                    helperText={zh ? '仅保存对端标识，不会从该对端采集流量。' : 'Identifies the remote end; traffic is not collected from it.'}
                  />
                </div>
              )}
            </div>
          </div>
        </section>

        <details className="mt-4 rounded-xl border border-[var(--ui-border)] p-4">
          <summary className="cursor-pointer text-sm font-bold text-[var(--heading-text)]">{zh ? '监控设置（可选）' : 'Monitoring settings (optional)'}</summary>
          <p className="mt-2 text-[11px] leading-5 text-[var(--muted-text)]">
            {zh ? '默认以本端设备端口采集流量；共享端口只能显示端口合计流量，不能拆分出专线流量。方向或承载范围通常保持默认，只有确认配置不同时再修改。' : 'Traffic is collected from the local device port. A shared port reports aggregate traffic only. Change direction or measurement scope only when you have verified the setup.'}
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="flex items-start gap-2 rounded-lg bg-[var(--ui-surface-muted)] p-3 text-xs font-semibold text-[var(--heading-text)]">
              <input className="mt-0.5" type="checkbox" checked={form.enabled} onChange={(event) => update('enabled', event.target.checked)} />
              <span>{zh ? '启用专线监控' : 'Enable circuit monitoring'}<span className="mt-1 block text-[10px] font-normal leading-4 text-[var(--muted-text)]">{zh ? '关闭后保留线路资料，但暂停该线路的流量采集和状态计算。' : 'When disabled, circuit details remain but traffic collection and health evaluation stop.'}</span></span>
            </label>
            <div className="rounded-lg bg-[var(--ui-surface-muted)] p-3">
              <label className="flex items-center gap-2 text-xs font-semibold text-[var(--heading-text)]">
                <input type="checkbox" checked={form.customCollectionInterval} onChange={(event) => update('customCollectionInterval', event.target.checked)} />
                {zh ? '自定义采集间隔' : 'Customize collection interval'}
              </label>
              {!form.customCollectionInterval && <p className="mt-1 text-[10px] text-[var(--muted-text)]">{zh ? '当前采用默认值：60 秒。' : 'Using the default interval: 60 seconds.'}</p>}
              {form.customCollectionInterval && <TextField className="mt-3" label={zh ? '采集间隔（秒，30 至 3,600 秒）' : 'Collection interval (30 to 3,600 seconds)'} type="number" min={30} max={3600} step={1} value={form.collection_interval_sec} onChange={(value) => update('collection_interval_sec', value)} />}
            </div>
            <div className="rounded-lg border border-[var(--ui-border)] p-3 text-[10px] leading-4 text-[var(--muted-text)] sm:col-span-2">
              <p>{zh ? `当前线路时区：${form.timezone || 'Asia/Shanghai'}。新线路默认继承本端站点时区。` : `Circuit timezone: ${form.timezone || 'Asia/Shanghai'}. New circuits inherit the local site's timezone by default.`}</p>
              <label className="mt-2 flex items-center gap-2 text-xs font-semibold text-[var(--heading-text)]">
                <input
                  type="checkbox"
                  checked={form.customTimezone}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    const localSite = options.sites.find((site) => site.id === form.site_id);
                    setForm((current) => ({
                      ...current,
                      customTimezone: checked,
                      ...(checked ? {} : { timezone: localSite?.timezone || 'Asia/Shanghai' }),
                    }));
                  }}
                />
                {zh ? '为这条线路单独设置时区' : 'Set a timezone override for this circuit'}
              </label>
              {form.customTimezone && (
                <TextField
                  className="mt-2"
                  label={zh ? '线路时区' : 'Circuit timezone'}
                  value={form.timezone}
                  onChange={(value) => update('timezone', value)}
                  placeholder="Asia/Shanghai"
                  helperText={zh ? '填写时区名称，例如 Asia/Shanghai、Asia/Tokyo。' : 'Use a timezone name such as Asia/Shanghai or Asia/Tokyo.'}
                />
              )}
            </div>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <CounterDirectionField side="A" value={form.direction_mode} onChange={(value) => update('direction_mode', value)} language={language} />
            <MeasurementScopeField side="A" value={form.aMeasurementScope} onChange={(value) => update('aMeasurementScope', value)} language={language} />
            {form.zEndpoint.endpoint_type === 'managed' && (
              <>
                <CounterDirectionField side="Z" value={form.zEndpoint.counter_orientation} onChange={(value) => updateZ({ counter_orientation: value })} language={language} />
                <MeasurementScopeField side="Z" value={form.zEndpoint.measurement_scope} onChange={(value) => updateZ({ measurement_scope: value })} language={language} />
              </>
            )}
          </div>
        </details>

        <details className="mt-3 rounded-xl border border-[var(--ui-border)] p-4">
          <summary className="cursor-pointer text-sm font-bold text-[var(--heading-text)]">{zh ? '其他信息（可选）' : 'Additional information (optional)'}</summary>
          <div className="mt-3 space-y-3">
            <TextField label={zh ? '备注' : 'Notes'} value={form.notes} onChange={(value) => update('notes', value)} multiline rows={2} />
          </div>
        </details>
        {validationError && <div className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700" role="alert">{validationError}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <ActionButton className={secondaryActionBtnClass} onClick={onClose}>{zh ? '取消' : 'Cancel'}</ActionButton>
          <ActionButton icon={Save} className={primaryActionBtnClass} type="submit" disabled={saving}>{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存线路' : 'Save circuit')}</ActionButton>
        </div>
      </form>
    </div>
  );
};

const CounterDirectionField: React.FC<{
  side: 'A' | 'Z';
  value: 'normal' | 'reversed';
  onChange: (value: 'normal' | 'reversed') => void;
  language: 'zh' | 'en';
}> = ({ side, value, onChange, language }) => {
  const zh = language === 'zh';
  const endpointName = side === 'A' ? (zh ? '本端（A 端）' : 'Local endpoint (A)') : (zh ? '对端（Z 端）' : 'Remote endpoint (Z)');
  return (
    <SelectField
      label={zh ? `${endpointName}端口计数方向` : `${endpointName} port counter direction`}
      value={value}
      onChange={(nextValue) => onChange(nextValue as 'normal' | 'reversed')}
      options={[
        { value: 'normal', label: zh ? '按设备上报方向统计（默认）' : 'Use the direction reported by the device (default)' },
        { value: 'reversed', label: zh ? '设备上报方向相反时反转统计' : 'Reverse counters when the device reports the opposite direction' },
      ]}
      language={language}
      helperText={zh ? '这是采集校正项，一般保持默认；只有监控结果的两个方向确实颠倒时才反转。' : 'This is a collection correction. Keep the default unless observed traffic directions are reversed.'}
    />
  );
};

const MeasurementScopeField: React.FC<{
  side: 'A' | 'Z';
  value: 'dedicated' | 'shared_interface';
  onChange: (value: 'dedicated' | 'shared_interface') => void;
  language: 'zh' | 'en';
}> = ({ side, value, onChange, language }) => {
  const zh = language === 'zh';
  const endpointName = side === 'A' ? (zh ? '本端（A 端）' : 'Local endpoint (A)') : (zh ? '对端（Z 端）' : 'Remote endpoint (Z)');
  return (
    <SelectField
      label={zh ? `${endpointName}接口是否只承载本专线？` : `Does the ${endpointName.toLowerCase()} interface carry only this circuit?`}
      value={value}
      onChange={(nextValue) => onChange(nextValue as 'dedicated' | 'shared_interface')}
      options={[
        { value: 'dedicated', label: zh ? '是，只承载本专线（可计算线路利用率）' : 'Yes, this circuit only (utilisation available)' },
        { value: 'shared_interface', label: zh ? '否，还承载其他业务（只显示端口总流量）' : 'No, other traffic shares it (port total only)' },
      ]}
      language={language}
      helperText={value === 'shared_interface'
        ? (zh ? '设备只能提供整个端口的合计流量，无法拆分出本专线流量；本专线利用率和容量告警将停用。' : 'The device reports total port traffic and cannot isolate this circuit; circuit utilisation and capacity alerts are disabled.')
        : (zh ? '仅当这个端口没有承载其他线路或业务时，才能准确计算本专线利用率。' : 'Utilisation is accurate only when this port carries no other circuits or services.')}
    />
  );
};
