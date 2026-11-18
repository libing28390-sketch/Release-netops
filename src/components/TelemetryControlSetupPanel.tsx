import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Loader2, Plus, Radio, ShieldCheck, UploadCloud } from 'lucide-react';
import { ApiError } from '../api/http';
import {
  createTelemetrySubscription,
  createTelemetryTemplate,
  createTelemetryTlsProfile,
  getTelemetryCollectors,
  getTelemetryTemplates,
  getTelemetryTlsProfiles,
  getTelemetryDeviceConfig,
  publishTelemetryTemplate,
  saveTelemetryDeviceConfig,
  updateTelemetryTemplateDraft,
} from '../api/telemetry';
import type {
  TelemetryCollectorOption,
  TelemetryDeviceConfig,
  TelemetryProtocolProfile,
  TelemetrySubscriptionTemplate,
  TelemetryTlsProfile,
} from '../types/telemetry';
import type { Device } from '../types';

interface Props {
  devices: Device[];
  profiles: TelemetryProtocolProfile[];
  canManage: boolean;
  onChanged: () => void;
}

type Notice = { kind: 'success' | 'error' | 'info'; message: string };

const fieldClass = 'w-full rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 py-2.5 text-sm font-normal text-[var(--app-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-600 disabled:opacity-60';
const labelClass = 'grid min-w-0 content-start gap-1.5 text-xs font-semibold text-[var(--app-text)]';

function errorText(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_CAPACITY_EXCEEDED') return '采集器容量不足，订阅尚未创建。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_PROFILE_UNSUPPORTED') return '协议档与设备厂商或型号不匹配。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_VERSION_UNVERIFIED') return '设备软件版本不在协议档记录范围内。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_TLS_INVALID') return 'TLS 引用或客户端证书指纹不符合要求。';
  return reason instanceof Error && reason.message ? reason.message : fallback;
}

function parseList(value: string): string[] {
  return [...new Set(value.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean))];
}

function telemetryVendorKey(value?: string | null): string {
  const vendor = String(value || '').trim().toLowerCase();
  if (vendor.includes('huawei') || vendor.includes('华为')) return 'huawei';
  if (vendor.includes('h3c') || vendor.includes('华三') || vendor.includes('新华三')) return 'h3c';
  return vendor;
}

function normalizeModelScope(value: string): string {
  return value.replace(/\[[^\]]+\]/g, '').replace(/[^a-z0-9]/gi, '').toLowerCase();
}

type ProfileMatch = { state: 'MATCHED' | 'IDENTIFICATION_PENDING' | 'KNOWN_MISMATCH'; reason: string };

function telemetryProfileMatch(profile: TelemetryProtocolProfile, device: Device): ProfileMatch {
  if (String(profile.vendor || '').trim().toLowerCase() !== String(device.vendor || '').trim().toLowerCase()) return { state: 'KNOWN_MISMATCH', reason: '厂商标识不匹配' };
  const pendingReasons: string[] = [];
  const supportStatus = String(profile.support_status || '').toUpperCase();
  if (supportStatus === 'UNSUPPORTED') return { state: 'KNOWN_MISMATCH', reason: '协议档标记为不支持' };
  if (!['DOCUMENTED', 'SAMPLE_VERIFIED', 'DEVICE_VERIFIED'].includes(supportStatus)) pendingReasons.push('协议档支持状态待确认');

  const modelScope = String(profile.model_scope || '').trim();
  if (modelScope) {
    const deviceModel = normalizeModelScope(String(device.model || ''));
    const scopes = modelScope.split(/[,/;]/).map(normalizeModelScope).filter(Boolean);
    if (!deviceModel) pendingReasons.push('设备型号未录入');
    else if (!scopes.some((scope) => deviceModel.includes(scope))) return { state: 'KNOWN_MISMATCH', reason: '型号超出协议档范围' };
  }

  const versionScope = String(profile.version_scope || '').trim();
  if (versionScope) {
    const deviceVersion = String(device.version || '').trim();
    const scopes = versionScope.split(/[,/;]/).map((scope) => scope.trim()).filter(Boolean);
    if (!deviceVersion) pendingReasons.push('设备软件版本未录入');
    const matchesVersion = scopes.some((scope) => {
      const pattern = scope.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/x/gi, '[0-9a-z]');
      return new RegExp(pattern, 'i').test(deviceVersion);
    });
    if (deviceVersion && !matchesVersion) return { state: 'KNOWN_MISMATCH', reason: '软件版本超出协议档范围' };
  }
  return pendingReasons.length
    ? { state: 'IDENTIFICATION_PENDING', reason: pendingReasons.join('；') }
    : { state: 'MATCHED', reason: '' };
}

function isIpAddressLiteral(value: string): boolean {
  const ip = value.trim();
  if (!ip) return false;
  if (!ip.includes(':')) {
    const octets = ip.split('.');
    return octets.length === 4 && octets.every((part) => /^\d{1,3}$/.test(part) && Number(part) >= 0 && Number(part) <= 255);
  }
  try {
    new URL(`http://[${ip}]/`);
    return true;
  } catch {
    return false;
  }
}

function collectorEndpointConfigured(collector?: TelemetryCollectorOption): boolean {
  return Boolean(collector?.endpoint_configured && collector.target_address.trim() && collector.grpc_port != null && collector.grpc_port > 0);
}

function safeCliName(value: string, fallback: string): string {
  return value.trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 28) || fallback;
}

function templatePathList(template?: TelemetrySubscriptionTemplate): string[] {
  if (!template) return [];
  return [...new Set(template.metric_mappings
    .map((mapping) => typeof mapping.source_path === 'string' ? mapping.source_path.trim() : '')
    .filter((path) => /^[A-Za-z0-9_./:-]{1,512}$/.test(path)))];
}

const TelemetryControlSetupPanel: React.FC<Props> = ({ devices, profiles, canManage, onChanged }) => {
  const [collectors, setCollectors] = useState<TelemetryCollectorOption[]>([]);
  const [templates, setTemplates] = useState<TelemetrySubscriptionTemplate[]>([]);
  const [tlsProfiles, setTlsProfiles] = useState<TelemetryTlsProfile[]>([]);
  const [resourceIssue, setResourceIssue] = useState('');
  const [resourcesLoading, setResourcesLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [publishingId, setPublishingId] = useState('');
  const [editingTemplateId, setEditingTemplateId] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [deviceId, setDeviceId] = useState('');
  const [profileId, setProfileId] = useState('');
  const [collectorId, setCollectorId] = useState('');
  const [tlsProfileId, setTlsProfileId] = useState('');
  const [deviceSourceAddress, setDeviceSourceAddress] = useState('');
  const [allowedSources, setAllowedSources] = useState('');
  const [deviceSearch, setDeviceSearch] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [subscriptionName, setSubscriptionName] = useState('基础状态');
  const [intervalSeconds, setIntervalSeconds] = useState('60');
  const [pathFilters, setPathFilters] = useState('');

  const [templateProfileId, setTemplateProfileId] = useState('');
  const [templateKey, setTemplateKey] = useState('');
  const [templateVersion, setTemplateVersion] = useState('1');
  const [templateSeries, setTemplateSeries] = useState('100');
  const [templateInterval, setTemplateInterval] = useState('60');
  const [templateMappings, setTemplateMappings] = useState('[]');

  const templateDetails = useRef<HTMLDetailsElement>(null);
  const tlsDetails = useRef<HTMLDetailsElement>(null);

  const openSettings = (details: HTMLDetailsElement | null) => {
    if (!details) return;
    details.open = true;
    details.querySelector('summary')?.focus();
  };

  const [tlsName, setTlsName] = useState('');
  const [tlsCaRef, setTlsCaRef] = useState('');
  const [tlsClientCertRef, setTlsClientCertRef] = useState('');
  const [tlsPrivateKeyRef, setTlsPrivateKeyRef] = useState('');
  const [tlsFingerprint, setTlsFingerprint] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setResourceIssue('');
    setResourcesLoading(true);
    void Promise.allSettled([
      getTelemetryCollectors(controller.signal),
      getTelemetryTemplates(controller.signal),
      getTelemetryTlsProfiles(controller.signal),
    ]).then(([collectorResult, templateResult, tlsResult]) => {
      if (controller.signal.aborted) return;
      const issues: string[] = [];
      if (collectorResult.status === 'fulfilled') {
        setCollectors((collectorResult.value.items || []).filter((item) => item.collector_type === 'LOCAL' && item.enabled !== false && item.enabled !== 0));
      } else issues.push('采集器列表加载失败');
      if (templateResult.status === 'fulfilled') setTemplates(templateResult.value.items || []);
      else issues.push('订阅模板加载失败');
      if (tlsResult.status === 'fulfilled') setTlsProfiles(tlsResult.value.items || []);
      else issues.push('TLS 凭据引用加载失败');
      setResourceIssue(issues.join('；'));
      setResourcesLoading(false);
    });
    return () => controller.abort();
  }, [reloadKey]);

  const supportedDevices = useMemo(() => devices.filter((device) => {
    const vendor = telemetryVendorKey(device.vendor);
    return Boolean(device.asset_id) && !device.is_unmanaged && (vendor === 'huawei' || vendor === 'h3c');
  }), [devices]);
  const filteredDevices = useMemo(() => {
    const query = deviceSearch.trim().toLowerCase();
    if (query.length < 2) return [];
    return supportedDevices.filter((device) => [device.asset_tag, device.hostname, device.ip_address, device.model]
      .some((value) => String(value || '').toLowerCase().includes(query))).slice(0, 100);
  }, [deviceSearch, supportedDevices]);
  const selectedDevice = supportedDevices.find((device) => device.id === deviceId);
  const selectedProfile = profiles.find((profile) => profile.id === profileId);
  const selectedProfileMatch = selectedDevice && selectedProfile ? telemetryProfileMatch(selectedProfile, selectedDevice) : null;
  const publishedTemplates = templates.filter((template) => template.status === 'PUBLISHED');
  const matchingTemplates = publishedTemplates.filter((template) => !profileId || template.profile_id === profileId);
  const selectedTemplate = matchingTemplates.find((template) => template.id === templateId);
  const activeTlsProfiles = tlsProfiles.filter((profile) => profile.status === 'ACTIVE');
  const selectedCollector = collectors.find((item) => item.id === collectorId);
  const selectedTemplatePaths = useMemo(() => templatePathList(selectedTemplate), [selectedTemplate]);
  const requestedPathFilters = useMemo(() => parseList(pathFilters), [pathFilters]);
  const invalidPathFilters = requestedPathFilters.filter((path) => !selectedTemplatePaths.includes(path));
  const profileAdapterKey = String(selectedProfile?.adapter_key || selectedProfile?.profile_key || '').toLowerCase();
  const h3cProfileVersion = profileAdapterKey === 'h3c_grpc_dialout_json_v2' ? 'v2'
    : profileAdapterKey === 'h3c_grpc_dialout_json_v3' ? 'v3'
      : null;
  const isHuaweiJsonGrpc = profileAdapterKey === 'huawei_grpc_dialout_json';

  const cliPreview = useMemo(() => {
    if (!h3cProfileVersion || !selectedTemplate || !selectedCollector) return '';
    const selectedPaths = templatePathList(selectedTemplate).filter((path) => !requestedPathFilters.length || requestedPathFilters.includes(path));
    if (!selectedPaths.length || invalidPathFilters.length) return '';
    const sensorGroup = safeCliName(`${selectedTemplate.template_key}_sensor`, 'telemetry_sensor');
    const destinationGroup = safeCliName(`${selectedTemplate.template_key}_collector`, 'telemetry_collector');
    const subscription = safeCliName(subscriptionName || selectedTemplate.template_key, 'telemetry_subscription');
    const address = collectorEndpointConfigured(selectedCollector) && isIpAddressLiteral(selectedCollector.target_address)
      ? selectedCollector.target_address.trim()
      : '<COLLECTOR_IP_PLACEHOLDER>';
    const addressCommand = address.includes(':') ? `ipv6-address ${address}` : `ipv4-address ${address}`;
    const sampleInterval = Number(intervalSeconds);
    const minInterval = Math.max(5, selectedProfile?.min_interval_seconds || 0);
    const safeInterval = Number.isInteger(sampleInterval) && sampleInterval >= minInterval ? sampleInterval : '<INTERVAL_SECONDS>';
    const source = deviceSourceAddress.trim();
    const sourceCommand = source && isIpAddressLiteral(source) ? `  source-address ${source}\n` : '';
    const tlsRequired = ['tls_pki', 'device_configured'].includes(String(selectedProfile?.auth_mode || '').toLowerCase());
    const pkiCommand = tlsRequired
      ? '# Replace this placeholder with an existing, verified device PKI domain; do not use the platform TLS profile ID.\ngrpc pki domain <PKI_DOMAIN_NAME_PLACEHOLDER>\n'
      : '# If device-side TLS/SSL is required, replace <DEVICE_PKI_OR_SSL_ID_PLACEHOLDER> with a verified device identity identifier.\n';
    const modelCommand = h3cProfileVersion === 'v3' ? 'grpc data-model 3-layer' : '';
    const pathCommands = selectedPaths.map((path) => ` sensor path ${path}`).join('\n');
    return [
      '# H3C gRPC Dial-out periodic sampling preview. Review for the exact model/release before applying.',
      '# This is a copyable preview only; NetOps has not configured the device.',
      'system-view',
      pkiCommand.trimEnd(),
      'grpc enable',
      modelCommand,
      'telemetry',
      `sensor-group ${sensorGroup}`,
      pathCommands,
      'quit',
      `destination-group ${destinationGroup}`,
      ` ${addressCommand} port ${collectorEndpointConfigured(selectedCollector) ? selectedCollector.grpc_port : '<GRPC_PORT_PLACEHOLDER>'}`,
      'quit',
      `subscription ${subscription}`,
      sourceCommand.trimEnd(),
      ` sensor-group ${sensorGroup} sample-interval ${safeInterval}`,
      ` destination-group ${destinationGroup}`,
      'quit',
    ].filter(Boolean).join('\n');
  }, [deviceSourceAddress, h3cProfileVersion, intervalSeconds, invalidPathFilters.length, requestedPathFilters, selectedCollector, selectedProfile?.auth_mode, selectedProfile?.min_interval_seconds, selectedTemplate, subscriptionName]);

  const endpointConfigured = collectorEndpointConfigured(selectedCollector);
  const canEnableDeviceConfig = selectedProfileMatch?.state === 'MATCHED' && endpointConfigured;
  const allowedSourceList = useMemo(() => parseList(allowedSources), [allowedSources]);

  const copyCliPreview = async () => {
    try {
      await navigator.clipboard.writeText(cliPreview);
      setNotice({ kind: 'success', message: '配置预览已复制；这只是待核对文本，NetOps 未向设备下发命令。' });
    } catch {
      setNotice({ kind: 'error', message: '无法访问剪贴板，请手动选择并复制预览文本。' });
    }
  };

  const selectDevice = (nextDeviceId: string) => {
    const device = supportedDevices.find((item) => item.id === nextDeviceId);
    const nextProfile = device && profiles.find((item) => telemetryProfileMatch(item, device).state !== 'KNOWN_MISMATCH');
    setDeviceId(nextDeviceId);
    setDeviceSearch('');
    setProfileId(nextProfile?.id || '');
    setCollectorId('');
    setTlsProfileId('');
    setDeviceSourceAddress('');
    setAllowedSources('');
    setTemplateId('');
    if (nextProfile) setTemplateProfileId(nextProfile.id);
  };

  const selectProfile = (nextProfileId: string) => {
    setProfileId(nextProfileId);
    setTemplateProfileId(nextProfileId);
    const matching = publishedTemplates.find((template) => template.profile_id === nextProfileId);
    setTemplateId(matching?.id || '');
    setPathFilters('');
    if (matching) setIntervalSeconds(String(matching.default_interval_seconds));
  };

  useEffect(() => {
    if (!deviceId) return;
    const controller = new AbortController();
    void getTelemetryDeviceConfig(deviceId, controller.signal).then((config) => {
      if (controller.signal.aborted || !config) return;
      setProfileId(config.profile_id);
      setCollectorId(config.collector_id);
      setTlsProfileId(config.tls_profile_id || '');
      setDeviceSourceAddress(config.device_source_address || '');
      setAllowedSources((config.allowed_sources || []).join(', '));
      setTemplateProfileId(config.profile_id);
    }).catch(() => undefined);
    return () => controller.abort();
  }, [deviceId, reloadKey]);

  useEffect(() => {
    if (!selectedTemplate) return;
    setIntervalSeconds(String(selectedTemplate.default_interval_seconds));
  }, [selectedTemplate]);

  const createSubscription = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedDevice || !selectedProfile || !collectorId || !selectedTemplate) {
      setNotice({ kind: 'error', message: '请选择设备、协议档、采集器和已发布模板。' });
      return;
    }
    if (selectedProfileMatch?.state === 'KNOWN_MISMATCH') {
      setNotice({ kind: 'error', message: `协议档与设备已知信息不匹配：${selectedProfileMatch.reason}` });
      return;
    }
    if (!selectedTemplatePaths.length) {
      setNotice({ kind: 'error', message: '已发布模板没有可用于订阅的 sensor path。' });
      return;
    }
    if (invalidPathFilters.length) {
      setNotice({ kind: 'error', message: `采集路径只能从所选已发布模板中选择：${invalidPathFilters.join('、')}` });
      return;
    }
    const interval = Number(intervalSeconds);
    if (!Number.isInteger(interval) || interval < Math.max(5, selectedProfile.min_interval_seconds || 0)) {
      setNotice({ kind: 'error', message: `采样周期不能低于 ${Math.max(5, selectedProfile.min_interval_seconds || 0)} 秒。` });
      return;
    }
    const sourceAddress = deviceSourceAddress.trim();
    if (sourceAddress && !isIpAddressLiteral(sourceAddress)) {
      setNotice({ kind: 'error', message: '设备上送源 IP 格式不正确。' });
      return;
    }
    const allowedSourceList = parseList(allowedSources);
    if (!allowedSourceList.length || allowedSourceList.some((item) => !isIpAddressLiteral(item))) {
      setNotice({ kind: 'error', message: '接收端允许来源 IP 白名单必须至少包含一个有效 IP 地址。' });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      const current = await getTelemetryDeviceConfig(selectedDevice.id);
      if (current?.enabled && !canEnableDeviceConfig) {
        setNotice({ kind: 'error', message: '此设备已有启用的 Telemetry 配置。型号/版本待确认或接收器端点未配置时，为避免误停用现有配置，本次未更新；请先核对兼容范围和接收器设置。' });
        return;
      }
      const configPayload: TelemetryDeviceConfig = {
        profile_id: selectedProfile.id,
        collector_id: collectorId,
        credential_id: current?.credential_id || null,
        tls_profile_id: tlsProfileId || null,
        device_source_address: sourceAddress || null,
        allowed_sources: allowedSourceList,
        enabled: canEnableDeviceConfig,
        revision: current?.revision || 1,
      };
      const savedConfig = await saveTelemetryDeviceConfig(selectedDevice.id, configPayload);
      await createTelemetrySubscription(selectedDevice.id, {
        name: subscriptionName.trim(),
        template_id: selectedTemplate.id,
        template_version: selectedTemplate.version,
        interval_seconds: interval,
        path_filters: parseList(pathFilters),
      });
      setNotice({ kind: 'success', message: selectedProfileMatch?.state === 'IDENTIFICATION_PENDING'
        ? `设备配置草稿和停用订阅已登记；设备型号/软件版本识别待确认${endpointConfigured ? '' : '，且接收器端点尚未配置'}，后端会在启用时再次校验。`
        : !endpointConfigured
          ? '设备配置草稿和停用订阅已登记；接收器端点未配置，补齐设备可达地址和端口后再启用。'
          : savedConfig.publish_job
            ? `设备配置更新已发布（任务 ${savedConfig.publish_job.job_id}）；新订阅保持停用，确认设备侧配置完成后再启用。`
            : '设备配置和订阅已登记；订阅保持停用，确认设备侧配置完成后再启用。' });
      setSubscriptionName('基础状态');
      setPathFilters('');
      onChanged();
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, 'Telemetry 设备配置或订阅保存失败。') });
    } finally {
      setSaving(false);
    }
  };

  const saveTemplate = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const mappings = JSON.parse(templateMappings);
      if (!Array.isArray(mappings)) throw new Error('指标映射必须是 JSON 数组。');
      setSaving(true);
      const saved = editingTemplateId
        ? await updateTelemetryTemplateDraft(editingTemplateId, {
          metric_mappings: mappings,
          estimated_series: Number(templateSeries),
          default_interval_seconds: Number(templateInterval),
        })
        : await createTelemetryTemplate({
          profile_id: templateProfileId,
          template_key: templateKey.trim(),
          version: Number(templateVersion),
          metric_mappings: mappings,
          estimated_series: Number(templateSeries),
          default_interval_seconds: Number(templateInterval),
        });
      setTemplates((current) => editingTemplateId
        ? current.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current.filter((item) => item.id !== saved.id)]);
      setEditingTemplateId('');
      setTemplateKey('');
      setTemplateMappings('[]');
      setNotice({ kind: 'success', message: '模板草稿已保存。审核字段映射和路径证据后可发布。' });
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, '模板 JSON 或字段校验失败。') });
    } finally {
      setSaving(false);
    }
  };

  const editTemplateDraft = (template: TelemetrySubscriptionTemplate) => {
    if (template.status !== 'DRAFT') return;
    setEditingTemplateId(template.id);
    setTemplateProfileId(template.profile_id);
    setTemplateKey(template.template_key);
    setTemplateVersion(String(template.version));
    setTemplateSeries(String(template.estimated_series));
    setTemplateInterval(String(template.default_interval_seconds));
    setTemplateMappings(JSON.stringify(template.metric_mappings || [], null, 2));
    setNotice({ kind: 'info', message: '正在编辑模板草稿。标记为 UNKNOWN 的字段映射通过真实样本确认前不能发布。' });
  };

  const cancelTemplateEdit = () => {
    setEditingTemplateId('');
    setTemplateKey('');
    setTemplateVersion('1');
    setTemplateSeries('100');
    setTemplateInterval('60');
    setTemplateMappings('[]');
  };

  const publishTemplate = async (id: string) => {
    setPublishingId(id);
    setNotice(null);
    try {
      const published = await publishTelemetryTemplate(id);
      setTemplates((current) => current.map((item) => item.id === id ? published : item));
      setNotice({ kind: 'success', message: '模板已发布，可以分配给设备订阅。' });
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, '模板发布失败；请补齐路径依据并重新校验。') });
    } finally {
      setPublishingId('');
    }
  };

  const saveTlsProfile = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      const created = await createTelemetryTlsProfile({
        name: tlsName.trim(),
        ca_certificate_ref: tlsCaRef.trim(),
        client_certificate_ref: tlsClientCertRef.trim(),
        encrypted_private_key_ref: tlsPrivateKeyRef.trim(),
        fingerprint: tlsFingerprint.trim(),
      });
      setTlsProfiles((current) => [...current, created]);
      setTlsName('');
      setNotice({ kind: 'success', message: 'TLS 凭据引用已登记。此处只保存引用和客户端证书指纹，不接收证书私钥内容。' });
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, 'TLS 凭据引用登记失败。') });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-3 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-[var(--app-text)]"><Radio size={16} className="text-cyan-700" />配置设备采集</h2>
        <p className="mt-1 text-xs text-[var(--muted-text)]">只登记采集器、TLS 引用和订阅；不会自动向设备下发配置命令。</p>
      </div>
      <details className="rounded-xl border border-[var(--card-border)] px-4 py-3">
        <summary className="cursor-pointer text-xs font-semibold text-[var(--app-text)]">批量导入已有资产</summary>
        <p className="mt-3 text-xs leading-relaxed text-[var(--muted-text)]">下载资产导入模板，在网络设备表填写资产编号和管理 IP，再在 Telemetry 采集工作表为每条订阅填写一行。导入后的订阅默认停用。</p>
        <a href="/assets/dashboard" className="mt-2 inline-block text-xs font-semibold text-cyan-700 hover:underline dark:text-cyan-300">前往资产导入与模板</a>
      </details>
      {notice && <div role={notice.kind === 'error' ? 'alert' : 'status'} className={`rounded-lg border px-3 py-2 text-xs ${notice.kind === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : notice.kind === 'info' ? 'border-sky-200 bg-sky-50 text-sky-800' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{notice.message}</div>}
      {resourceIssue && <p role="status" className="text-xs text-amber-700">{resourceIssue}</p>}

      <form onSubmit={createSubscription} className="space-y-5">
        <fieldset className="min-w-0 rounded-2xl border border-[var(--card-border)] px-4 pb-4 pt-2 md:px-5">
          <legend className="px-2 text-sm font-semibold text-[var(--app-text)]">设备与协议</legend>
          <div className="grid items-start gap-x-6 gap-y-4 md:grid-cols-2">
            <div className={labelClass}>
              <span>设备</span>
              <input type="search" className={fieldClass} value={deviceSearch} onChange={(event) => setDeviceSearch(event.target.value)} placeholder="搜索资产编号、主机名、管理 IP 或型号" disabled={!canManage} aria-label="搜索 Telemetry 设备" />
              {selectedDevice && !deviceSearch.trim() && <div className="rounded-lg border border-cyan-200 bg-cyan-50/60 px-2.5 py-2 text-xs text-cyan-950">
                <span className="font-bold">已选：</span>{[selectedDevice.asset_tag, selectedDevice.hostname, selectedDevice.ip_address, selectedDevice.model].filter(Boolean).join(' · ')}
              </div>}
              {deviceSearch.trim().length < 2
                ? <p className="rounded-lg border border-dashed border-[var(--card-border)] px-2.5 py-2 text-xs text-[var(--muted-text)]">输入至少 2 个字符搜索华为/华三设备；选择结果后可继续搜索更换。</p>
                : <div role="group" aria-label="搜索结果：可配置的华为和华三设备" className="max-h-40 overflow-y-auto rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)]">
                {filteredDevices.length ? filteredDevices.map((device) => {
                  const selected = device.id === deviceId;
                  const title = [device.asset_tag || '无资产编号', device.hostname || '无主机名', device.ip_address, device.model || '型号待补'].filter(Boolean).join(' · ');
                  return <button key={device.id} type="button" aria-pressed={selected} disabled={!canManage} onClick={() => selectDevice(device.id)} className={`block w-full border-b border-[var(--card-border)] px-2.5 py-2 text-left text-xs last:border-b-0 disabled:cursor-not-allowed ${selected ? 'bg-cyan-50 font-bold text-cyan-900' : 'text-[var(--app-text)] hover:bg-black/[0.04] dark:hover:bg-white/[0.06]'}`}>{title}</button>;
                }) : <p className="px-2.5 py-3 text-xs text-[var(--muted-text)]">没有匹配的华为/华三设备。</p>}
              </div>}
              {selectedDevice && <span className="text-xs text-[var(--muted-text)]">设备软件版本：{selectedDevice.version || '未录入'}</span>}
            </div>
            <label className={labelClass}>协议档
              <select className={fieldClass} value={profileId} onChange={(event) => selectProfile(event.target.value)} disabled={!canManage || !selectedDevice} required>
                <option value="">选择协议档</option>
                {profiles.map((profile) => {
                  const match = selectedDevice ? telemetryProfileMatch(profile, selectedDevice) : { state: 'IDENTIFICATION_PENDING' as const, reason: '请先选择设备' };
                  const mismatch = match.state === 'KNOWN_MISMATCH';
                  return <option key={profile.id} value={profile.id} disabled={mismatch}>{profile.profile_key}{mismatch ? ` · 不匹配：${match.reason}` : match.state === 'IDENTIFICATION_PENDING' ? ` · 待确认：${match.reason}` : ''}</option>;
                })}
              </select>
              {selectedDevice && selectedProfile && selectedProfileMatch?.state === 'KNOWN_MISMATCH' && <span role="alert" className="text-xs font-semibold text-rose-700">协议档不匹配：{selectedProfileMatch.reason}</span>}
              {selectedDevice && selectedProfile && selectedProfileMatch?.state === 'IDENTIFICATION_PENDING' && <span role="status" className="text-xs font-semibold text-amber-800">兼容性待确认：{selectedProfileMatch.reason}。可保存停用草稿，启用时由后端再次校验。</span>}
              {selectedDevice && selectedProfile && selectedProfileMatch?.state === 'MATCHED' && <span className="text-xs text-[var(--muted-text)]">协议档范围：{selectedProfile.model_scope || '不限型号'} · {selectedProfile.version_scope || '不限版本'}</span>}
            </label>
          </div>
        </fieldset>
        <fieldset className="min-w-0 rounded-2xl border border-[var(--card-border)] px-4 pb-4 pt-2 md:px-5">
          <legend className="px-2 text-sm font-semibold text-[var(--app-text)]">接收器与连接</legend>
          <div className="grid items-start gap-x-6 gap-y-4 md:grid-cols-2">
            <label className={labelClass}>采集器
              <select className={fieldClass} value={collectorId} onChange={(event) => setCollectorId(event.target.value)} disabled={!canManage} required>
                <option value="">选择已启用 Telemetry 接收器</option>
                {collectors.map((item) => {
                  const endpoint = collectorEndpointConfigured(item)
                    ? `${item.target_address.includes(':') ? `[${item.target_address}]` : item.target_address}:${item.grpc_port}`
                    : '接收端点未配置';
                  return <option key={item.id} value={item.id}>{item.name} ({item.id}) · {endpoint}</option>;
                })}
              </select>
              {selectedCollector ? endpointConfigured
                ? <span className="text-xs text-emerald-700">设备可达接收地址：{selectedCollector.target_address.includes(':') ? `[${selectedCollector.target_address}]` : selectedCollector.target_address}:{selectedCollector.grpc_port}</span>
                : <span role="status" className="text-xs font-semibold text-amber-800">此接收器尚未配置设备可达地址或有效 gRPC 端口；仍可保存停用草稿，启用动作会由后端阻止，补齐端点后再启用。</span>
                : <span className="text-xs text-[var(--muted-text)]">地址和端口来自独立 Telemetry 接收器配置，不使用 SNMP 采集器地址。</span>}
            </label>
            <label className={labelClass}>TLS 客户端身份
              <select className={fieldClass} value={tlsProfileId} onChange={(event) => setTlsProfileId(event.target.value)} disabled={!canManage} required>
                <option value="">选择活动 TLS 配置</option>
                {activeTlsProfiles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label className={labelClass}>设备上送源 IP（可选）
              <input className={fieldClass} value={deviceSourceAddress} onChange={(event) => setDeviceSourceAddress(event.target.value)} placeholder="留空时使用设备到接收器路由的默认源地址" disabled={!canManage} />
              <span className="text-xs text-[var(--muted-text)]">选择设备用于发起 gRPC 连接的本地源地址。</span>
            </label>
            <label className={`${labelClass} md:col-span-2`}>允许来源 IP（接收端白名单，必填）
              <textarea className={fieldClass} rows={2} value={allowedSources} onChange={(event) => setAllowedSources(event.target.value)} placeholder="填写接收端需放行的设备来源 IP，例如 10.20.1.15" disabled={!canManage} required />
              <span className="text-xs text-[var(--muted-text)]">这是接收端实际观察到的来源地址；NAT 场景下可与设备上送源 IP 不同，二者分别配置。</span>
            </label>
          </div>
        </fieldset>
        <fieldset className="min-w-0 rounded-2xl border border-[var(--card-border)] px-4 pb-4 pt-2 md:px-5">
          <legend className="px-2 text-sm font-semibold text-[var(--app-text)]">采集内容</legend>
          <div className="grid items-start gap-x-6 gap-y-4 md:grid-cols-2">
            <label className={labelClass}>已发布订阅模板
              <select className={fieldClass} value={templateId} onChange={(event) => setTemplateId(event.target.value)} disabled={!canManage} required>
                <option value="">选择模板</option>
                {matchingTemplates.map((item) => <option key={item.id} value={item.id}>{item.template_key} v{item.version}</option>)}
              </select>
            </label>
            <label className={labelClass}>订阅名称
              <input className={fieldClass} value={subscriptionName} onChange={(event) => setSubscriptionName(event.target.value)} disabled={!canManage} required maxLength={160} />
            </label>
            <label className={labelClass}>采样周期（秒）
              <input className={fieldClass} type="number" min={Math.max(5, selectedProfile?.min_interval_seconds || 0)} value={intervalSeconds} onChange={(event) => setIntervalSeconds(event.target.value)} disabled={!canManage} required />
            </label>
            <label className={`${labelClass} md:col-span-2`}>传感器路径筛选（只允许已发布模板中的 source_path；可留空表示使用模板全部路径）
              <textarea className={fieldClass} rows={2} value={pathFilters} onChange={(event) => setPathFilters(event.target.value)} placeholder="每行或逗号分隔" disabled={!canManage} />
            </label>
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--card-border)] bg-cyan-500/[0.04] p-4">
          <div role="status" className="space-y-1 text-xs text-[var(--muted-text)]">
            {resourcesLoading ? <p>正在加载采集配置…</p> : resourceIssue ? <p>采集配置加载不完整，请刷新后重试。</p> : (
              <>
                {matchingTemplates.length === 0 && <p>{profileId ? '当前协议档没有已发布模板。' : '暂无已发布模板。'} <button type="button" onClick={() => openSettings(templateDetails.current)} className="font-semibold text-cyan-700 underline dark:text-cyan-300">查看订阅模板</button></p>}
                {activeTlsProfiles.length === 0 && <p>暂无活动 TLS 配置。 <button type="button" onClick={() => openSettings(tlsDetails.current)} className="font-semibold text-cyan-700 underline dark:text-cyan-300">打开 TLS 配置</button></p>}
                {collectors.length === 0 && <p>暂无可用的本地 Telemetry 接收器。</p>}
              </>
            )}
          </div>
          <button type="submit" disabled={!canManage || saving || resourcesLoading || !selectedCollector || !tlsProfileId || !selectedTemplate || !selectedProfileMatch || selectedProfileMatch.state === 'KNOWN_MISMATCH' || invalidPathFilters.length > 0} className="inline-flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2.5 text-xs font-semibold text-white hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-50">
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}登记设备和停用订阅
          </button>
        </div>
      </form>
      {selectedDevice && <p className="text-xs text-[var(--muted-text)]">状态：{canEnableDeviceConfig ? '平台设备配置已启用' : '平台设备配置保持停用'}，订阅保持停用。协议、采集器、周期与模板仅登记在控制面；需在设备上完成配置后，再从订阅列表手动启用。</p>}
      {h3cProfileVersion && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
          <p className="font-bold">华三 {h3cProfileVersion.toUpperCase()} gRPC Dial-out JSON</p>
          {h3cProfileVersion === 'v3'
            ? <p className="mt-1">设备通过 gRPC Dial-out 上送，默认编码为 JSON；如型号/版本支持三层数据模型，需确认并配置 <code className="rounded bg-amber-100 px-1">grpc data-model 3-layer</code>。采样周期仅对周期型 sensor path 生效。</p>
            : <p className="mt-1">设备默认使用 gRPC Dial-out、JSON 编码和二层 Telemetry 数据模型；预览不输出这几个默认项的配置命令。采样周期仅对周期型 sensor path 生效。</p>}
          <p className="mt-1">下方 CLI 仅预览已发布模板中的路径与当前表单字段，不会下发；PKI domain 使用显式占位符，需按设备侧证书策略核对。</p>
        </div>
      )}
      {isHuaweiJsonGrpc && (
        <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2.5 text-xs text-sky-900">
          <p className="font-bold">华为 gRPC Dial-out JSON 协议档</p>
          <p className="mt-1">协议档范围和模板周期表示平台支持边界；此处只登记控制面订阅。设备侧仍需按所选型号/版本人工配置 JSON/gRPC 周期采样，本页不会动态下发；TLS/SSL 身份也需设备侧单独核验。</p>
        </div>
      )}
      {h3cProfileVersion && (
        <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><p className="text-xs font-bold text-[var(--app-text)]">华三周期采样 CLI 预览</p><p className="mt-1 text-xs text-[var(--muted-text)]">接收端允许来源 IP 是服务端白名单，不会写入设备命令。</p></div>
            <button type="button" onClick={() => void copyCliPreview()} disabled={!cliPreview} className="rounded-lg border border-[var(--card-border)] px-3 py-1.5 text-xs font-bold text-[var(--app-text)] disabled:cursor-not-allowed disabled:opacity-50">复制预览</button>
          </div>
          {invalidPathFilters.length > 0 && <p role="alert" className="mt-2 text-xs font-semibold text-rose-700">路径筛选只能使用已发布模板路径：{invalidPathFilters.join('、')}</p>}
          {!endpointConfigured && <p className="mt-2 text-xs text-amber-800">接收端点未配置；预览中使用地址/端口占位符。补齐可达地址后再登记订阅。</p>}
          {!selectedTemplatePaths.length && <p className="mt-2 text-xs text-amber-800">当前模板没有有效的已发布 source_path，暂不生成 CLI。</p>}
          <pre className="mt-3 max-h-80 overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-relaxed text-slate-100">{cliPreview || '选择已有发布模板后生成预览。'}</pre>
          <p className="mt-2 text-xs text-[var(--muted-text)]">复制后仍需按具体设备版本审阅并在经授权的设备变更流程中应用；此预览不表示设备已配置。</p>
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-2">
        <details ref={templateDetails} className="rounded-xl border border-[var(--card-border)] p-3">
          <summary className="cursor-pointer text-xs font-bold text-[var(--app-text)]"><UploadCloud size={13} className="mr-1 inline" />订阅模板草稿</summary>
          <form onSubmit={saveTemplate} className="mt-3 grid gap-2 sm:grid-cols-2">
            <label className={labelClass}>协议档<select className={fieldClass} value={templateProfileId} onChange={(event) => setTemplateProfileId(event.target.value)} disabled={Boolean(editingTemplateId)} required><option value="">选择协议档</option>{profiles.map((item) => <option key={item.id} value={item.id}>{item.profile_key}</option>)}</select></label>
            <label className={labelClass}>模板 Key<input className={fieldClass} value={templateKey} onChange={(event) => setTemplateKey(event.target.value)} disabled={Boolean(editingTemplateId)} required maxLength={160} /></label>
            <label className={labelClass}>版本<input className={fieldClass} type="number" min="1" value={templateVersion} onChange={(event) => setTemplateVersion(event.target.value)} disabled={Boolean(editingTemplateId)} required /></label>
            <label className={labelClass}>估算序列数<input className={fieldClass} type="number" min="1" value={templateSeries} onChange={(event) => setTemplateSeries(event.target.value)} required /></label>
            <label className={labelClass}>默认周期（秒）<input className={fieldClass} type="number" min="5" value={templateInterval} onChange={(event) => setTemplateInterval(event.target.value)} required /></label>
            <label className={`${labelClass} sm:col-span-2`}>指标映射 JSON<textarea className={`${fieldClass} font-mono`} rows={8} value={templateMappings} onChange={(event) => setTemplateMappings(event.target.value)} spellCheck={false} required /></label>
            <p className="sm:col-span-2 text-xs text-[var(--muted-text)]">每条映射需要填写 metric_key、source_path、source_field、value_type、support_status 和 evidence。路径证据来自厂商资料或逐设备验证；未验证路径不能发布。</p>
            <div className="sm:col-span-2 flex flex-wrap gap-2"><button type="submit" disabled={!canManage || saving} className="rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs font-bold disabled:opacity-50">{editingTemplateId ? '保存草稿修改' : '保存草稿'}</button>{editingTemplateId && <button type="button" onClick={cancelTemplateEdit} disabled={saving} className="rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs font-semibold disabled:opacity-50">取消编辑</button>}</div>
          </form>
          <div className="mt-3 space-y-1.5">{templates.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-black/[0.025] px-2.5 py-2 text-xs dark:bg-white/[0.04]"><span className="font-semibold text-[var(--app-text)]">{item.template_key} v{item.version} · {item.status} · {item.estimated_series} 序列<code className="mt-0.5 block break-all font-normal text-[9px] text-[var(--muted-text)]">ID: {item.id}</code></span>{item.status === 'DRAFT' && <div className="flex gap-1.5"><button type="button" disabled={!canManage || saving} onClick={() => editTemplateDraft(item)} className="inline-flex items-center gap-1 rounded border border-[var(--card-border)] px-2 py-1 font-bold disabled:opacity-50">编辑</button><button type="button" disabled={!canManage || publishingId === item.id} onClick={() => void publishTemplate(item.id)} className="inline-flex items-center gap-1 rounded border border-[var(--card-border)] px-2 py-1 font-bold disabled:opacity-50">{publishingId === item.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}发布</button></div>}</div>)}</div>
        </details>

        <details ref={tlsDetails} className="rounded-xl border border-[var(--card-border)] p-3">
          <summary className="cursor-pointer text-xs font-bold text-[var(--app-text)]"><ShieldCheck size={13} className="mr-1 inline" />TLS 凭据引用</summary>
          <form onSubmit={saveTlsProfile} className="mt-3 grid gap-2 sm:grid-cols-2">
            <label className={labelClass}>名称<input className={fieldClass} value={tlsName} onChange={(event) => setTlsName(event.target.value)} required maxLength={160} /></label>
            <label className={labelClass}>客户端证书 SHA-256 指纹<input className={fieldClass} value={tlsFingerprint} onChange={(event) => setTlsFingerprint(event.target.value)} placeholder="64 位十六进制" required /></label>
            <label className={labelClass}>CA 证书密钥库引用<input className={fieldClass} value={tlsCaRef} onChange={(event) => setTlsCaRef(event.target.value)} required /></label>
            <label className={labelClass}>客户端证书密钥库引用<input className={fieldClass} value={tlsClientCertRef} onChange={(event) => setTlsClientCertRef(event.target.value)} required /></label>
            <label className={`${labelClass} sm:col-span-2`}>私钥密钥库引用<input className={fieldClass} value={tlsPrivateKeyRef} onChange={(event) => setTlsPrivateKeyRef(event.target.value)} required /></label>
            <p className="sm:col-span-2 text-xs text-[var(--muted-text)]">仅登记密钥库引用，不填写 PEM、私钥或其他密钥内容。容器证书卷还需由部署方按相同身份配置。</p>
            <div className="sm:col-span-2"><button type="submit" disabled={!canManage || saving} className="rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs font-bold disabled:opacity-50">登记 TLS 引用</button></div>
          </form>
          <div className="mt-3 space-y-1.5">{tlsProfiles.map((item) => <div key={item.id} className="rounded-lg bg-black/[0.025] px-2.5 py-2 text-xs dark:bg-white/[0.04]"><span className="font-semibold text-[var(--app-text)]">{item.name} · {item.status}</span><code className="mt-0.5 block break-all text-[9px] text-[var(--muted-text)]">ID: {item.id} · SHA-256: {item.fingerprint}</code></div>)}</div>
        </details>
      </div>
    </section>
  );
};

export default TelemetryControlSetupPanel;
