import { type FormEvent, useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Loader2,
  Play,
  Plus,
  Radio,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  Terminal,
  UploadCloud,
  X,
} from 'lucide-react';
import { ApiError } from '../api/http';
import {
  createTelemetrySubscription,
  createTelemetryTemplate,
  createTelemetryTlsProfile,
  getTelemetryCollectors,
  getTelemetryDeviceConfig,
  getTelemetryTemplates,
  getTelemetryTlsProfiles,
  publishTelemetryTemplate,
  runTelemetrySubscriptionAction,
  saveTelemetryDeviceConfig,
  simulateTelemetrySubscription,
  updateTelemetryTemplateDraft,
} from '../api/telemetry';
import type {
  TelemetryCollectorOption,
  TelemetryDeviceConfig,
  TelemetryProtocolProfile,
  TelemetrySimulationResult,
  TelemetrySubscriptionTemplate,
  TelemetryTlsProfile,
} from '../types/telemetry';
import type { Device } from '../types';
import Pagination from './Pagination';

interface Props {
  devices: Device[];
  profiles: TelemetryProtocolProfile[];
  canManage: boolean;
  onChanged: () => void;
  onSimulated?: (result: TelemetrySimulationResult) => void;
  onNavigateSubPage?: (subPage: 'onboarding' | 'subscriptions' | 'protocols' | 'capacity') => void;
}

type Notice = { kind: 'success' | 'error' | 'info'; message: string };

const controlClass =
  'block w-full min-w-0 rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] px-3 text-xs font-normal leading-5 text-[var(--app-text)] outline-none transition focus:border-cyan-600 focus:ring-2 focus:ring-cyan-500/15';
const fieldClass = `${controlClass} h-10`;
const textareaClass = `${controlClass} resize-y py-2`;
const labelClass = 'flex min-w-0 flex-col gap-1.5 text-xs font-semibold leading-5 text-[var(--app-text)]';

function errorText(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_CAPACITY_EXCEEDED') return '采集器容量不足，订阅尚未创建。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_PROFILE_UNSUPPORTED') return '协议档与设备厂商不匹配。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_VERSION_UNVERIFIED') return '设备软件版本不在协议档记录范围内。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_TLS_INVALID') return 'TLS 引用或客户端证书指纹不符合要求。';
  if (reason instanceof ApiError && reason.code === 'TELEMETRY_SUBSCRIPTION_EXISTS') return '该设备下已存在同名订阅，请更换订阅名称或直接在下方列表操作。';
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
  return value
    .replace(/\[[^\]]+\]/g, '')
    .replace(/\bnetengine\s*(?=\d)/gi, 'ne')
    .replace(/\b(?:cloudengine|netengine|hisecengine|airengine|secpath|h3c|huawei)\b/gi, '')
    .replace(/[^a-z0-9]/gi, '')
    .toLowerCase();
}

function matchModelScopeToken(rawToken: string, rawModel: string): boolean {
  const token = normalizeModelScope(rawToken);
  const model = normalizeModelScope(rawModel);
  if (!token || !model) return false;
  if (model.includes(token)) return true;
  if (rawToken.includes('[')) {
    const base = normalizeModelScope(rawToken.split('-')[0] || '');
    if (base.length >= 4 && model.includes(base)) return true;
  }
  const seriesMatch = /^([a-z]+\d{1,3})00(?:[a-z]{1,4})?$/.exec(token);
  if (seriesMatch) {
    const prefix = seriesMatch[1];
    if (new RegExp(`${prefix}\\d{2}`).test(model)) return true;
  }
  const thousandMatch = /^([a-z]+\d)000(?:[a-z]{1,4})?$/.exec(token);
  if (thousandMatch) {
    const prefix = thousandMatch[1];
    if (new RegExp(`${prefix}\\d{3}`).test(model)) return true;
  }
  return false;
}

export function protocolOptionLabel(profile: TelemetryProtocolProfile): string {
  const key = profile.profile_key;
  if (key === 'h3c_grpc_dialout_json_v2_campus_s5135s') return '华三园区交换机 · 二层 JSON (S5135S / S5130S / S5170 / S5560X / S5570S / S6520X / S7500E / S10500X)';
  if (key === 'h3c_grpc_dialout_json_v2_sec_wlan') return '华三防火墙/无线/路由 · 二层 JSON (F1000 / F1060 / F1090 / F5000 / WX5540H / SR6600 / MSR3600)';
  if (key === 'h3c_grpc_dialout_json_v2_s6850_r6717') return '华三数据中心 · 二层 JSON (S6850 / S6820 / S6825 / S6860 / S6861 / S9820 / S9825 / S9855)';
  if (key === 'h3c_grpc_dialout_json_v2') return '华三数据中心通用 · 二层 JSON (S6800 / S6805 / S6812 / S6850 / S9850 / S12500G-AF / S12500X-AF)';
  if (key === 'h3c_grpc_dialout_json_v3_s6850_r6717') return '华三数据中心 · 三层 JSON v3 (S6850 / S6825 / S6860 / S9825 / S9855)';
  if (key === 'h3c_grpc_dialout_json_v3') return '华三园区/汇聚 · 三层 JSON v3 (S5135S / S5130S / S5560X / S5570S / S6520X / S7500E / S10500X)';
  if (key === 'huawei_ce6800_v200r005c10_grpc_json') return '华为数据中心 · gRPC JSON (CE5800 / CE6800 / CE6850 / CE6881 / CE6885 / CE8850 / CE9860 / CE12800 / CE16800)';
  if (key === 'huawei_grpc_dialout_json') return '华为园区/路由/安全 · gRPC JSON (S5731 / S5732 / S5735 / S5755 / S6730 / S6750 / S8700 / S12700E / S16700 / NE40E / USG6000E)';
  const adapter = profile.adapter_key || profile.profile_key;
  const model = profile.model_scope || '通用机型';
  return `${adapter} · ${model}`;
}

export function templateFriendlyLabel(template: TelemetrySubscriptionTemplate): string {
  const key = template.template_key.toLowerCase();
  const count = Array.isArray(template.metric_mappings) ? template.metric_mappings.length : 0;
  if (key.includes('campus_s5135s')) return `华三园区交换机 (S5135S/S5130S/S5560X/S6520X/S7500E) 官方标准监控包 (${count} 项指标 · v${template.version})`;
  if (key.includes('sec_wlan')) return `华三防火墙/无线/路由 (F1060/F1090/WX5540H/SR6600) 官方标准监控包 (${count} 项指标 · v${template.version})`;
  if (key.includes('huawei_ce6800')) return `华为数据中心 (CE5800/CE6800/CE8800/CE12800/CE16800) 官方标准监控包 (${count} 项指标 · v${template.version})`;
  if (key.includes('huawei')) return `华为园区/路由/安全 (S5731/S5735/S6730/S12700E/NE40E/USG6000E) 官方标准监控包 (${count} 项指标 · v${template.version})`;
  if (key.includes('s6850') && key.includes('v3')) return `华三数据中心 (S6850/S6860/S9825/S9855) 三层 JSON 官方标准包 (${count} 项指标 · v${template.version})`;
  if (key.includes('s6850')) return `华三数据中心 (S6850/S6825/S6860/S9825) 二层 JSON 官方标准包 (${count} 项指标 · v${template.version})`;
  if (key.includes('v3')) return `华三 Comware V7 园区三层 JSON 标准包 (${count} 项指标 · v${template.version})`;
  if (key.includes('h3c')) return `华三 Comware V7 数据中心二层 JSON 标准包 (${count} 项指标 · v${template.version})`;
  return `${template.template_key} v${template.version} (${count} 项指标)`;
}

function canChooseProfile(profile: TelemetryProtocolProfile, device: Device): boolean {
  return (
    telemetryVendorKey(profile.vendor) === telemetryVendorKey(device.vendor) &&
    !['UNKNOWN', 'UNSUPPORTED'].includes(String(profile.support_status || 'UNKNOWN').toUpperCase())
  );
}

function findBestProfileForDevice(profiles: TelemetryProtocolProfile[], device: Device): TelemetryProtocolProfile | undefined {
  const eligible = profiles.filter((p) => canChooseProfile(p, device));
  if (!eligible.length) return undefined;
  const rawModel = String(device.model || device.hostname || '').trim();
  if (rawModel) {
    const exactV2 = eligible.find((p) => {
      const scopes = String(p.model_scope || '').split(/[,/;]/).map((s) => s.trim()).filter(Boolean);
      return scopes.some((s) => matchModelScopeToken(s, rawModel)) && !String(p.adapter_key || '').includes('v3');
    });
    if (exactV2) return exactV2;
    const exactAny = eligible.find((p) => {
      const scopes = String(p.model_scope || '').split(/[,/;]/).map((s) => s.trim()).filter(Boolean);
      return scopes.some((s) => matchModelScopeToken(s, rawModel));
    });
    if (exactAny) return exactAny;
  }
  return eligible[0];
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

function sensorPathCategory(path: string): { label: string; isCore: boolean; tone: string } {
  const p = path.toLowerCase();
  if (p.includes('cpu') || p.includes('memor')) {
    return { label: '系统性能', isCore: true, tone: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' };
  }
  if (p.includes('ifstatistics') || p.includes('ifmgr/statistics') || p.includes('ifmgr/interfaces') || p.endsWith('/interface')) {
    return { label: '接口状态与流量', isCore: true, tone: 'bg-cyan-500/10 text-cyan-800 dark:text-cyan-300' };
  }
  if (p.includes('optical') || p.includes('transceiver')) {
    return { label: '光模块 DDM', isCore: false, tone: 'bg-violet-500/10 text-violet-700 dark:text-violet-300' };
  }
  if (p.includes('buffer') || p.includes('qos') || p.includes('pfc')) {
    return { label: 'QoS 缓存 / PFC', isCore: false, tone: 'bg-amber-500/10 text-amber-800 dark:text-amber-300' };
  }
  if (p.includes('temperature') || p.includes('fan') || p.includes('physicalentit')) {
    return { label: '硬件环境', isCore: false, tone: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' };
  }
  if (p.includes('session') || p.includes('wlan')) {
    return { label: '安全 / 无线业务', isCore: false, tone: 'bg-rose-500/10 text-rose-700 dark:text-rose-300' };
  }
  return { label: '设备能力 / 日志', isCore: false, tone: 'bg-slate-500/10 text-slate-600 dark:text-slate-300' };
}

interface PathSummaryItem {
  path: string;
  metrics: string[];
}

function templatePathSummaries(template?: TelemetrySubscriptionTemplate): PathSummaryItem[] {
  if (!template || !Array.isArray(template.metric_mappings)) return [];
  const byPath = new Map<string, string[]>();
  for (const mapping of template.metric_mappings) {
    const rawPath = typeof mapping.source_path === 'string' ? mapping.source_path.trim() : '';
    if (!rawPath || !/^[A-Za-z0-9_./:-]{1,512}$/.test(rawPath)) continue;
    const mKey = typeof mapping.metric_key === 'string' ? mapping.metric_key.trim() : '';
    const list = byPath.get(rawPath) || [];
    if (mKey && !list.includes(mKey)) list.push(mKey);
    byPath.set(rawPath, list);
  }
  return Array.from(byPath.entries()).map(([path, metrics]) => ({ path, metrics }));
}

const DEVICE_PICKER_PAGE_SIZE = 6;

const TelemetryControlSetupPanel: React.FC<Props> = ({
  devices,
  profiles,
  canManage,
  onChanged,
  onSimulated,
  onNavigateSubPage,
}) => {
  const [collectors, setCollectors] = useState<TelemetryCollectorOption[]>([]);
  const [templates, setTemplates] = useState<TelemetrySubscriptionTemplate[]>([]);
  const [tlsProfiles, setTlsProfiles] = useState<TelemetryTlsProfile[]>([]);
  const [resourceIssue, setResourceIssue] = useState('');
  const [saving, setSaving] = useState(false);
  const [publishingId, setPublishingId] = useState('');
  const [editingTemplateId, setEditingTemplateId] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);

  const [deviceId, setDeviceId] = useState('');
  const [vendorFilter, setVendorFilter] = useState<'all' | 'h3c' | 'huawei'>('all');
  const [deviceQuery, setDeviceQuery] = useState('');
  const [devicePage, setDevicePage] = useState(1);
  const [profileId, setProfileId] = useState('');
  const [collectorId, setCollectorId] = useState('');
  const [securityMode, setSecurityMode] = useState<'no_tls' | 'tls'>('no_tls');
  const [tlsProfileId, setTlsProfileId] = useState('');
  const [deviceSourceAddress, setDeviceSourceAddress] = useState('');
  const [allowedSources, setAllowedSources] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [subscriptionName, setSubscriptionName] = useState('官方标准遥测订阅');
  const [intervalSeconds, setIntervalSeconds] = useState('10');
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [autoEnable, setAutoEnable] = useState(true);
  const [autoSimulate, setAutoSimulate] = useState(true);
  const [cliPreviewMode, setCliPreviewMode] = useState<'auto' | 'huawei' | 'h3c_v2' | 'h3c_v3'>('auto');

  const [templateProfileId, setTemplateProfileId] = useState('');
  const [templateKey, setTemplateKey] = useState('');
  const [templateVersion, setTemplateVersion] = useState('1');
  const [templateSeries, setTemplateSeries] = useState('100');
  const [templateInterval, setTemplateInterval] = useState('10');
  const [templateMappings, setTemplateMappings] = useState('[]');

  const [tlsName, setTlsName] = useState('');
  const [tlsCaRef, setTlsCaRef] = useState('');
  const [tlsClientCertRef, setTlsClientCertRef] = useState('');
  const [tlsPrivateKeyRef, setTlsPrivateKeyRef] = useState('');
  const [tlsFingerprint, setTlsFingerprint] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setResourceIssue('');
    void Promise.allSettled([
      getTelemetryCollectors(controller.signal),
      getTelemetryTemplates(controller.signal),
      getTelemetryTlsProfiles(controller.signal),
    ]).then(([collectorResult, templateResult, tlsResult]) => {
      if (controller.signal.aborted) return;
      const issues: string[] = [];
      if (collectorResult.status === 'fulfilled') {
        const list = (collectorResult.value.items || []).filter(
          (item) => item.collector_type === 'LOCAL' && item.enabled !== false && item.enabled !== 0,
        );
        setCollectors(list);
        if (list[0]) setCollectorId((cur) => cur || list[0].id);
      } else issues.push('采集器列表加载失败');
      if (templateResult.status === 'fulfilled') setTemplates(templateResult.value.items || []);
      else issues.push('订阅模板加载失败');
      if (tlsResult.status === 'fulfilled') setTlsProfiles(tlsResult.value.items || []);
      else issues.push('TLS 凭据引用加载失败');
      setResourceIssue(issues.join('；'));
    });
    return () => controller.abort();
  }, []);

  const supportedDevices = useMemo(
    () =>
      devices.filter((device) => {
        const vendor = telemetryVendorKey(device.vendor);
        return Boolean(device.asset_id) && !device.is_unmanaged && (vendor === 'huawei' || vendor === 'h3c');
      }),
    [devices],
  );

  const visibleDevices = useMemo(() => {
    const q = deviceQuery.trim().toLowerCase();
    return supportedDevices.filter((d) => {
      if (vendorFilter !== 'all' && telemetryVendorKey(d.vendor) !== vendorFilter) return false;
      if (!q) return true;
      const haystack = [d.hostname, d.ip_address, d.model, d.vendor, d.asset_tag, d.version, d.site]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [supportedDevices, vendorFilter, deviceQuery]);

  const totalDevicePages = Math.max(1, Math.ceil(visibleDevices.length / DEVICE_PICKER_PAGE_SIZE));
  const safeDevicePage = Math.min(devicePage, totalDevicePages);
  const pagedDevices = useMemo(
    () =>
      visibleDevices.slice(
        (safeDevicePage - 1) * DEVICE_PICKER_PAGE_SIZE,
        safeDevicePage * DEVICE_PICKER_PAGE_SIZE,
      ),
    [visibleDevices, safeDevicePage],
  );

  const publishedTemplates = useMemo(
    () => templates.filter((template) => template.status === 'PUBLISHED'),
    [templates],
  );

  const selectedDevice = supportedDevices.find((device) => device.id === deviceId);
  const selectedProfile = profiles.find((profile) => profile.id === profileId);
  const selectedTemplate = publishedTemplates.find((template) => template.id === templateId);
  const activeTlsProfiles = tlsProfiles.filter((profile) => profile.status === 'ACTIVE');
  const selectedCollector = collectors.find((item) => item.id === collectorId) || collectors[0];
  const pathSummaries = useMemo(() => templatePathSummaries(selectedTemplate), [selectedTemplate]);

  // Auto-select the first supported device once loaded so the operator immediately sees a working configuration & CLI preview.
  useEffect(() => {
    if (!deviceId && supportedDevices.length > 0 && profiles.length > 0) {
      handleSelectDevice(supportedDevices[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supportedDevices, profiles, publishedTemplates, collectors]);

  const handleSelectProfile = (nextProfileId: string) => {
    setProfileId(nextProfileId);
    setTemplateProfileId(nextProfileId);
    const matching = publishedTemplates.find((t) => t.profile_id === nextProfileId) || publishedTemplates[0];
    setTemplateId(matching?.id || '');
    if (matching) {
      setIntervalSeconds(String(Math.max(10, matching.default_interval_seconds || 10)));
      setSelectedPaths(templatePathSummaries(matching).map((item) => item.path));
    } else {
      setSelectedPaths([]);
    }
  };

  const handleSelectDevice = (nextDeviceId: string) => {
    setDeviceId(nextDeviceId);
    const dev = supportedDevices.find((d) => d.id === nextDeviceId);
    if (!dev) return;
    const defaultCollector = collectors[0]?.id || 'telemetry-collector-local';
    setCollectorId((cur) => cur || defaultCollector);
    const ip = String(dev.ip_address || '').trim();
    if (ip) {
      setDeviceSourceAddress(ip);
      setAllowedSources(ip);
    }
    const bestProfile = findBestProfileForDevice(profiles, dev);
    if (bestProfile) {
      handleSelectProfile(bestProfile.id);
    }
  };

  // Load existing device config if already saved in DB
  useEffect(() => {
    if (!deviceId) return;
    const controller = new AbortController();
    void getTelemetryDeviceConfig(deviceId, controller.signal)
      .then((config) => {
        if (controller.signal.aborted || !config) return;
        if (config.profile_id) {
          handleSelectProfile(config.profile_id);
        }
        if (config.collector_id) setCollectorId(config.collector_id);
        if (config.tls_profile_id) {
          setSecurityMode('tls');
          setTlsProfileId(config.tls_profile_id);
        } else {
          setSecurityMode('no_tls');
          setTlsProfileId('');
        }
        if (config.device_source_address) setDeviceSourceAddress(config.device_source_address);
        if (config.allowed_sources?.length) setAllowedSources(config.allowed_sources.join(', '));
      })
      .catch(() => undefined);
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId]);

  useEffect(() => {
    if (!selectedTemplate) return;
    setIntervalSeconds(String(Math.max(10, selectedTemplate.default_interval_seconds || 10)));
    setSelectedPaths(templatePathSummaries(selectedTemplate).map((item) => item.path));
  }, [selectedTemplate]);

  const togglePath = (path: string) => {
    setSelectedPaths((current) =>
      current.includes(path) ? current.filter((item) => item !== path) : [...current, path],
    );
  };

  const profileAdapterKey = String(selectedProfile?.adapter_key || selectedProfile?.profile_key || '').toLowerCase();
  const effectiveCliFlavour: 'huawei' | 'h3c_v2' | 'h3c_v3' = useMemo(() => {
    if (cliPreviewMode !== 'auto') return cliPreviewMode;
    if (profileAdapterKey.includes('huawei')) return 'huawei';
    if (profileAdapterKey.includes('v3')) return 'h3c_v3';
    return 'h3c_v2';
  }, [cliPreviewMode, profileAdapterKey]);

  const cliPreview = useMemo(() => {
    const collectorAddr =
      collectorEndpointConfigured(selectedCollector) && isIpAddressLiteral(selectedCollector!.target_address)
        ? selectedCollector!.target_address.trim()
        : '192.168.56.1';
    const collectorPort = collectorEndpointConfigured(selectedCollector) ? selectedCollector!.grpc_port : 10051;
    const isIpv6 = collectorAddr.includes(':');
    const sampleSec = Math.max(5, Number(intervalSeconds) || 10);
    const srcIp = deviceSourceAddress.trim() || selectedDevice?.ip_address || '10.254.0.6';
    const baseName = safeCliName(selectedTemplate?.template_key || 'nexora_telemetry', 'nexora');
    const sensorGroup = `${baseName}_sg`;
    const destGroup = 'nexora_collector';
    const subName = safeCliName(subscriptionName || 'sub_nexora', 'sub_nexora');

    const activePaths =
      selectedPaths.length > 0
        ? selectedPaths
        : effectiveCliFlavour === 'huawei'
          ? [
              'huawei-devm:devm/cpuInfos/cpuInfo',
              'huawei-devm:devm/memoryInfos/memoryInfo',
              'huawei-ifm:ifm/interfaces/interface/ifStatistics',
            ]
          : ['ifmgr/statistics', 'ifmgr/devicecapabilities', 'Syslog/LogBuffer'];

    if (effectiveCliFlavour === 'huawei') {
      const sampleMs = sampleSec * 1000;
      const addrLine = isIpv6
        ? `  ipv6-address ${collectorAddr} port ${collectorPort} protocol grpc${securityMode === 'no_tls' ? ' no-tls' : ''}`
        : `  ipv4-address ${collectorAddr} port ${collectorPort} protocol grpc${securityMode === 'no_tls' ? ' no-tls' : ''}`;
      const srcLine =
        srcIp && isIpAddressLiteral(srcIp)
          ? `  local-source-address ${srcIp.includes(':') ? 'ipv6' : 'ipv4'} ${srcIp}`
          : '';
      return [
        '# 华为 VRP / CloudEngine gRPC Dial-out 官方标准配置脚本',
        `# 目标接收器: ${collectorAddr}:${collectorPort}  |  采样周期: ${sampleSec}s (${sampleMs} ms)`,
        'system-view',
        'telemetry',
        ` destination-group ${destGroup}`,
        addrLine,
        ' quit',
        ` sensor-group ${sensorGroup}`,
        ...activePaths.map((p) => `  sensor-path ${p}`),
        ' quit',
        ` subscription ${subName}`,
        srcLine,
        `  sensor-group ${sensorGroup} sample-interval ${sampleMs}`,
        `  destination-group ${destGroup}`,
        ' quit',
        'quit',
        'commit',
        '',
        '# ── 设备侧状态核验命令 ──',
        '# display telemetry destination',
        '# display telemetry subscription',
      ]
        .filter((line) => line !== undefined)
        .join('\n');
    }

    const addrLine = isIpv6
      ? `  ipv6-address ${collectorAddr} port ${collectorPort}${securityMode === 'tls' ? ' tls' : ''}`
      : `  ipv4-address ${collectorAddr} port ${collectorPort}${securityMode === 'tls' ? ' tls' : ''}`;
    const srcLine = srcIp && isIpAddressLiteral(srcIp) ? `  source-address ${srcIp}` : '';
    return [
      `# 华三 Comware V7 gRPC Dial-out (${effectiveCliFlavour === 'h3c_v3' ? '三层 JSON v3' : '二层 JSON v2'}) 官方标准配置脚本`,
      `# 目标接收器: ${collectorAddr}:${collectorPort}  |  采样周期: ${sampleSec}s`,
      'system-view',
      ...(securityMode === 'tls' ? ['grpc pki domain nexora_telemetry_pki'] : []),
      'grpc enable',
      ...(effectiveCliFlavour === 'h3c_v3' ? ['grpc data-model 3-layer'] : []),
      'telemetry',
      ` sensor-group ${sensorGroup}`,
      ...activePaths.map((p) => `  sensor path ${p}`),
      ' quit',
      ` destination-group ${destGroup}`,
      addrLine,
      ' quit',
      ` subscription ${subName}`,
      srcLine,
      `  sensor-group ${sensorGroup} sample-interval ${sampleSec}`,
      `  destination-group ${destGroup}`,
      ' quit',
      'quit',
      '',
      '# ── 设备侧状态核验命令 ──',
      '# display telemetry subscription',
      '# display grpc',
    ]
      .filter(Boolean)
      .join('\n');
  }, [
    deviceSourceAddress,
    effectiveCliFlavour,
    intervalSeconds,
    securityMode,
    selectedCollector,
    selectedDevice?.ip_address,
    selectedPaths,
    selectedTemplate?.template_key,
    subscriptionName,
  ]);

  const copyCliPreview = async () => {
    try {
      await navigator.clipboard.writeText(cliPreview);
      setNotice({ kind: 'success', message: '官方 CLI 配置脚本已复制到剪贴板！' });
    } catch {
      setNotice({ kind: 'error', message: '无法访问剪贴板，请手动选择并复制右侧脚本。' });
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const targetCollectorId = collectorId || collectors[0]?.id || 'telemetry-collector-local';
    if (!selectedDevice || !selectedProfile || !targetCollectorId || !selectedTemplate) {
      setNotice({ kind: 'error', message: '请确认已选择设备、协议档和监控模板。' });
      return;
    }
    if (!selectedPaths.length) {
      setNotice({ kind: 'error', message: '请至少勾选一条需要采集的 Sensor Path。' });
      return;
    }
    const interval = Number(intervalSeconds);
    const minInterval = Math.max(5, selectedProfile.min_interval_seconds || 5);
    if (!Number.isInteger(interval) || interval < minInterval) {
      setNotice({ kind: 'error', message: `采样周期不能低于 ${minInterval} 秒。` });
      return;
    }
    const sourceAddress = (deviceSourceAddress.trim() || selectedDevice.ip_address || '').trim();
    if (sourceAddress && !isIpAddressLiteral(sourceAddress)) {
      setNotice({ kind: 'error', message: '设备上送源 IP 格式不正确。' });
      return;
    }
    const rawAllowed = parseList(allowedSources);
    const allowedSourceList = rawAllowed.length ? rawAllowed : sourceAddress ? [sourceAddress] : [];
    if (!allowedSourceList.length || allowedSourceList.some((item) => !isIpAddressLiteral(item))) {
      setNotice({ kind: 'error', message: '接收端白名单需包含至少一个有效的设备来源 IP。' });
      return;
    }
    if (securityMode === 'tls' && !tlsProfileId) {
      setNotice({ kind: 'error', message: '启用 TLS 双向证书模式时请选择一项 TLS 客户端证书配置，或切换为无 TLS 直连模式。' });
      return;
    }

    setSaving(true);
    setNotice(null);
    try {
      const current = await getTelemetryDeviceConfig(selectedDevice.id);
      const configPayload: TelemetryDeviceConfig = {
        profile_id: selectedProfile.id,
        collector_id: targetCollectorId,
        credential_id: current?.credential_id || null,
        tls_profile_id: securityMode === 'tls' ? tlsProfileId || null : null,
        device_source_address: sourceAddress || null,
        allowed_sources: allowedSourceList,
        enabled: autoEnable,
        revision: current?.revision || 1,
      };
      await saveTelemetryDeviceConfig(selectedDevice.id, configPayload);

      const allTemplatePaths = pathSummaries.map((item) => item.path);
      const pathFilters =
        selectedPaths.length === allTemplatePaths.length ? [] : selectedPaths;

      const createdSub = await createTelemetrySubscription(selectedDevice.id, {
        name: subscriptionName.trim(),
        template_id: selectedTemplate.id,
        template_version: selectedTemplate.version,
        interval_seconds: interval,
        path_filters: pathFilters,
      });

      if (autoEnable && autoSimulate) {
        const simResult = await simulateTelemetrySubscription(createdSub.id);
        onSimulated?.(simResult);
        setNotice({
          kind: 'success',
          message: `已完成「${selectedDevice.hostname || selectedDevice.ip_address}」订阅创建、启用及官方 ${simResult.wire_format} 推流仿真测试！共生成 ${simResult.active_series} 条有效 Prometheus 指标序列。`,
        });
      } else if (autoEnable) {
        await runTelemetrySubscriptionAction(createdSub.id, 'enable');
        setNotice({
          kind: 'success',
          message: `设备配置与订阅「${createdSub.name}」已保存并启用！请将右侧 CLI 脚本刷入设备，或点击下方列表的「模拟推流」验证解析链路。`,
        });
      } else {
        setNotice({
          kind: 'success',
          message: `设备配置与停用订阅「${createdSub.name}」已保存。`,
        });
      }
      onChanged();
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, 'Telemetry 配置或订阅创建失败。') });
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
      setTemplates((current) =>
        editingTemplateId
          ? current.map((item) => (item.id === saved.id ? saved : item))
          : [saved, ...current.filter((item) => item.id !== saved.id)],
      );
      setEditingTemplateId('');
      setTemplateKey('');
      setTemplateMappings('[]');
      setNotice({ kind: 'success', message: '自定义模板草稿已保存。' });
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, '模板 JSON 或字段校验失败。') });
    } finally {
      setSaving(false);
    }
  };

  const publishTemplate = async (id: string) => {
    setPublishingId(id);
    setNotice(null);
    try {
      const published = await publishTelemetryTemplate(id);
      setTemplates((current) => current.map((item) => (item.id === id ? published : item)));
      setNotice({ kind: 'success', message: '模板已发布，可以直接在上方选用。' });
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, '模板发布失败。') });
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
      setNotice({ kind: 'success', message: 'TLS 凭据引用已登记。' });
    } catch (reason) {
      setNotice({ kind: 'error', message: errorText(reason, 'TLS 凭据引用登记失败。') });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-4 rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--card-border)] pb-3.5">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-extrabold text-[var(--app-text)]">
            <Radio size={16} className="text-cyan-700" />
            快速开通设备 Telemetry 订阅（华为 VRP / 华三 Comware V7）
          </h2>
          <p className="mt-1 text-xs text-[var(--muted-text)]">
            通过关键词检索或厂商筛选点选设备，自动匹配官方协议档、已发布监控模板与源 IP 白名单，右侧同步生成官方 CLI 脚本。
          </p>
        </div>
        {onNavigateSubPage && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onNavigateSubPage('protocols')}
              className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-600/30 bg-cyan-500/10 px-2.5 py-1.5 text-[11px] font-bold text-cyan-800 transition hover:bg-cyan-500/20 dark:text-cyan-300"
            >
              <ShieldCheck size={13} />
              查看内置协议与 112+ 支持型号库
            </button>
            <button
              type="button"
              onClick={() => onNavigateSubPage('subscriptions')}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--card-border)] bg-black/[0.02] px-2.5 py-1.5 text-[11px] font-bold text-[var(--app-text)] transition hover:bg-black/[0.05] dark:bg-white/[0.04]"
            >
              进入订阅管理与推流测试
            </button>
          </div>
        )}
      </div>

      {notice && (
        <div
          role={notice.kind === 'error' ? 'alert' : 'status'}
          className={`rounded-xl border px-3.5 py-2.5 text-xs ${
            notice.kind === 'error'
              ? 'border-rose-200 bg-rose-50 text-rose-700'
              : notice.kind === 'info'
                ? 'border-sky-200 bg-sky-50 text-sky-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-700'
          }`}
        >
          {notice.message}
        </div>
      )}
      {resourceIssue && <p role="status" className="text-[11px] text-amber-700">{resourceIssue}</p>}

      <div className="grid gap-5 xl:grid-cols-12">
        {/* Left 7 columns: Streamlined 3-step guided setup form */}
        <form onSubmit={handleSubmit} className="space-y-4 xl:col-span-7">
          {/* Step 1: Searchable & Paginated Device Selector (No dropdown!) */}
          <div className="rounded-xl border border-[var(--card-border)] bg-black/[0.015] p-3.5 dark:bg-white/[0.02]">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-xs font-extrabold text-[var(--app-text)]">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-700 text-[10px] font-bold text-white">1</span>
                检索并点选目标设备（支持按主机名 / IP / 型号快速过滤）
              </span>
              {selectedDevice && (
                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-bold text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-950/30 dark:text-emerald-300">
                  <CheckCircle2 size={12} />
                  当前已选：{selectedDevice.hostname || selectedDevice.asset_tag} ({selectedDevice.ip_address})
                </span>
              )}
            </div>

            {/* Search Input + Vendor Filter Bar */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[220px] flex-1">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" />
                <input
                  type="text"
                  value={deviceQuery}
                  onChange={(e) => {
                    setDeviceQuery(e.target.value);
                    setDevicePage(1);
                  }}
                  placeholder="搜索主机名、管理 IP、型号 (如 S6850 / S5135S / F1090 / 10.254.0.6)..."
                  aria-label="搜索 Telemetry 设备"
                  className="h-9 w-full rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] pl-8 pr-8 text-xs text-[var(--app-text)] outline-none transition focus:border-cyan-600 focus:ring-2 focus:ring-cyan-500/15"
                />
                {deviceQuery && (
                  <button
                    type="button"
                    onClick={() => {
                      setDeviceQuery('');
                      setDevicePage(1);
                    }}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-text)] hover:text-[var(--app-text)]"
                    title="清空搜索"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              <div className="flex items-center gap-1">
                {(
                  [
                    { key: 'all', label: `全部 (${supportedDevices.length})` },
                    { key: 'h3c', label: `华三 H3C (${supportedDevices.filter((d) => telemetryVendorKey(d.vendor) === 'h3c').length})` },
                    { key: 'huawei', label: `华为 Huawei (${supportedDevices.filter((d) => telemetryVendorKey(d.vendor) === 'huawei').length})` },
                  ] as const
                ).map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setVendorFilter(item.key);
                      setDevicePage(1);
                    }}
                    className={`h-9 rounded-xl px-2.5 text-[11px] font-semibold transition ${
                      vendorFilter === item.key
                        ? 'bg-cyan-700 text-white shadow-2xs'
                        : 'border border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:text-[var(--app-text)]'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Paginated Device Table List (No native dropdown, no card grid) */}
            {pagedDevices.length > 0 ? (
              <div className="mt-2.5 overflow-x-auto rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)]">
                <table className="w-full min-w-[540px] text-left text-xs">
                  <thead className="bg-black/[0.025] text-[10px] font-bold text-[var(--muted-text)] dark:bg-white/[0.035]">
                    <tr>
                      <th className="w-10 px-3 py-2 text-center">选择</th>
                      <th className="px-3 py-2">设备主机名</th>
                      <th className="px-3 py-2">管理 IP</th>
                      <th className="px-3 py-2">厂商</th>
                      <th className="px-3 py-2">设备型号</th>
                      <th className="px-3 py-2">软件版本</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--card-border)]">
                    {pagedDevices.map((d) => {
                      const isSelected = d.id === deviceId;
                      const isHuawei = telemetryVendorKey(d.vendor) === 'huawei';
                      return (
                        <tr
                          key={d.id}
                          onClick={() => {
                            if (canManage) handleSelectDevice(d.id);
                          }}
                          className={`cursor-pointer transition ${
                            isSelected
                              ? 'bg-cyan-50/80 dark:bg-cyan-950/35'
                              : 'hover:bg-black/[0.02] dark:hover:bg-white/[0.03]'
                          }`}
                        >
                          <td className="px-3 py-2 text-center">
                            <input
                              type="radio"
                              name="telemetry-target-device"
                              checked={isSelected}
                              disabled={!canManage}
                              onChange={() => handleSelectDevice(d.id)}
                              aria-label={`选择设备 ${d.hostname || d.ip_address}`}
                              className="h-3.5 w-3.5 accent-cyan-700"
                            />
                          </td>
                          <td className="px-3 py-2 font-bold text-[var(--app-text)]">
                            <span className="inline-flex items-center gap-1.5">
                              <span
                                className={`h-2 w-2 shrink-0 rounded-full ${
                                  d.status === 'online' ? 'bg-emerald-500' : 'bg-slate-400'
                                }`}
                              />
                              {d.hostname || d.asset_tag || d.id}
                            </span>
                          </td>
                          <td className="px-3 py-2 font-mono text-[11px] text-[var(--app-text)]">
                            {d.ip_address || '—'}
                          </td>
                          <td className="px-3 py-2">
                            <span
                              className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-bold ${
                                isHuawei
                                  ? 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
                                  : 'bg-cyan-500/10 text-cyan-800 dark:text-cyan-300'
                              }`}
                            >
                              {isHuawei ? '华为 Huawei' : '华三 H3C'}
                            </span>
                          </td>
                          <td className="px-3 py-2 font-mono text-[11px] font-semibold text-[var(--app-text)]">
                            {d.model || '通用型号'}
                          </td>
                          <td className="px-3 py-2 font-mono text-[11px] text-[var(--muted-text)]">
                            {d.version || '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <Pagination
                  currentPage={safeDevicePage}
                  totalItems={visibleDevices.length}
                  itemsPerPage={DEVICE_PICKER_PAGE_SIZE}
                  onPageChange={setDevicePage}
                  language="zh"
                  itemLabel="台设备"
                />
              </div>
            ) : (
              <div className="mt-2.5 flex items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--card-border)] bg-[var(--card-bg)] py-6 text-xs text-[var(--muted-text)]">
                <Server size={15} />
                <span>没有匹配「{deviceQuery || (vendorFilter === 'huawei' ? '华为' : '华三')}」的纳管设备</span>
              </div>
            )}

            {/* Matched Protocol Profile Selector */}
            <div className="mt-3 border-t border-[var(--card-border)] pt-3">
              <label className={labelClass}>
                <span>已自动匹配的 Telemetry 协议档（可按需切换二层 / 三层 JSON）</span>
                <select
                  className={fieldClass}
                  value={profileId}
                  onChange={(e) => handleSelectProfile(e.target.value)}
                  disabled={!canManage}
                  required
                >
                  <option value="">选择协议档…</option>
                  {profiles
                    .filter((p) => !selectedDevice || canChooseProfile(p, selectedDevice))
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {protocolOptionLabel(p)}
                      </option>
                    ))}
                </select>
              </label>
            </div>
          </div>

          {/* Step 2 */}
          <div className="rounded-xl border border-[var(--card-border)] bg-black/[0.015] p-3.5 dark:bg-white/[0.02]">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-xs font-extrabold text-[var(--app-text)]">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-700 text-[10px] font-bold text-white">2</span>
                监控模板、采样周期与传感器路径 (Sensor Paths)
              </span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-[var(--muted-text)]">快捷周期：</span>
                {['10', '30', '60'].map((sec) => (
                  <button
                    key={sec}
                    type="button"
                    onClick={() => setIntervalSeconds(sec)}
                    className={`rounded-md px-2 py-0.5 text-[10px] font-bold transition ${
                      intervalSeconds === sec
                        ? 'bg-cyan-700 text-white'
                        : 'border border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)] hover:text-[var(--app-text)]'
                    }`}
                  >
                    {sec}s
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <label className={`${labelClass} sm:col-span-2`}>
                <span>官方监控模板</span>
                <select
                  className={fieldClass}
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                  disabled={!canManage}
                  required
                >
                  <option value="">选择已发布监控模板…</option>
                  {publishedTemplates
                    .filter((t) => !profileId || t.profile_id === profileId)
                    .map((t) => (
                      <option key={t.id} value={t.id}>
                        {templateFriendlyLabel(t)}
                      </option>
                    ))}
                </select>
              </label>

              <label className={labelClass}>
                <span>采样周期（秒）</span>
                <input
                  className={fieldClass}
                  type="number"
                  min={Math.max(5, selectedProfile?.min_interval_seconds || 5)}
                  value={intervalSeconds}
                  onChange={(e) => setIntervalSeconds(e.target.value)}
                  disabled={!canManage}
                  required
                />
              </label>
            </div>

            {/* Interactive Sensor Path Checklist Table */}
            {pathSummaries.length > 0 && (
              <div className="mt-3">
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                  <span className="font-semibold text-[var(--app-text)]">
                    勾选需要订阅的传感器路径（已选 {selectedPaths.length} / {pathSummaries.length}）
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedPaths(
                          pathSummaries.filter((p) => sensorPathCategory(p.path).isCore).map((p) => p.path),
                        )
                      }
                      className="rounded-md border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-0.5 text-[10px] font-semibold text-[var(--app-text)] hover:bg-black/[0.04]"
                    >
                      仅选基础性能+接口
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedPaths(
                          selectedPaths.length === pathSummaries.length ? [] : pathSummaries.map((p) => p.path),
                        )
                      }
                      className="text-[11px] font-semibold text-cyan-700 hover:underline"
                    >
                      {selectedPaths.length === pathSummaries.length ? '取消全选' : '全选路径'}
                    </button>
                  </div>
                </div>
                <div className="max-h-64 overflow-auto rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)]">
                  <table className="w-full text-left text-[11px]">
                    <thead className="sticky top-0 bg-slate-50 text-[10px] font-bold text-[var(--muted-text)] dark:bg-slate-900">
                      <tr>
                        <th className="w-10 px-3 py-1.5 text-center">订阅</th>
                        <th className="whitespace-nowrap px-3 py-1.5">监控维度</th>
                        <th className="px-3 py-1.5">传感器路径 (Sensor Path)</th>
                        <th className="px-3 py-1.5">映射 Prometheus 指标</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--card-border)]">
                      {pathSummaries.map((item) => {
                        const checked = selectedPaths.includes(item.path);
                        const cat = sensorPathCategory(item.path);
                        return (
                          <tr
                            key={item.path}
                            onClick={() => togglePath(item.path)}
                            className={`cursor-pointer transition ${
                              checked
                                ? 'bg-cyan-50/50 dark:bg-cyan-950/20'
                                : 'opacity-65 hover:bg-black/[0.015]'
                            }`}
                          >
                            <td className="px-3 py-2 text-center">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => togglePath(item.path)}
                                onClick={(e) => e.stopPropagation()}
                                className="rounded border-slate-300 text-cyan-700"
                              />
                            </td>
                            <td className="whitespace-nowrap px-3 py-2">
                              <span className={`inline-flex whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-bold ${cat.tone}`}>
                                {cat.label}
                              </span>
                            </td>
                            <td className="whitespace-nowrap px-3 py-2 font-mono font-bold text-[var(--app-text)]">
                              {item.path}
                            </td>
                            <td className="px-3 py-2 text-[var(--muted-text)]">
                              {item.metrics.join('、')}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Step 3 */}
          <div className="rounded-xl border border-[var(--card-border)] bg-black/[0.015] p-3.5 dark:bg-white/[0.02]">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-xs font-extrabold text-[var(--app-text)]">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-700 text-[10px] font-bold text-white">3</span>
                连接安全与源地址（默认自动匹配设备管理 IP）
              </span>
              <div className="inline-flex rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] p-0.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => setSecurityMode('no_tls')}
                  className={`rounded-md px-2.5 py-1 font-semibold transition ${
                    securityMode === 'no_tls' ? 'bg-cyan-700 text-white' : 'text-[var(--muted-text)]'
                  }`}
                >
                  无 TLS 直连 (no-tls · 推荐)
                </button>
                <button
                  type="button"
                  onClick={() => setSecurityMode('tls')}
                  className={`rounded-md px-2.5 py-1 font-semibold transition ${
                    securityMode === 'tls' ? 'bg-cyan-700 text-white' : 'text-[var(--muted-text)]'
                  }`}
                >
                  TLS 双向证书
                </button>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <label className={labelClass}>
                <span>订阅名称</span>
                <input
                  className={fieldClass}
                  value={subscriptionName}
                  onChange={(e) => setSubscriptionName(e.target.value)}
                  disabled={!canManage}
                  required
                  maxLength={160}
                />
              </label>

              <label className={labelClass}>
                <span>设备上送源 IP</span>
                <input
                  className={fieldClass}
                  value={deviceSourceAddress}
                  onChange={(e) => {
                    setDeviceSourceAddress(e.target.value);
                    if (!allowedSources || allowedSources === deviceSourceAddress) {
                      setAllowedSources(e.target.value);
                    }
                  }}
                  placeholder="例如 10.254.0.6"
                  disabled={!canManage}
                />
              </label>

              <label className={labelClass}>
                <span>接收端允许来源 IP 白名单</span>
                <input
                  className={fieldClass}
                  value={allowedSources}
                  onChange={(e) => setAllowedSources(e.target.value)}
                  placeholder="多个 IP 用逗号分隔"
                  disabled={!canManage}
                  required
                />
              </label>
            </div>

            {securityMode === 'tls' && (
              <div className="mt-3">
                <label className={labelClass}>
                  <span>TLS 客户端证书配置</span>
                  <select
                    className={fieldClass}
                    value={tlsProfileId}
                    onChange={(e) => setTlsProfileId(e.target.value)}
                    disabled={!canManage}
                    required
                  >
                    <option value="">选择已登记的 TLS 客户端证书…</option>
                    {activeTlsProfiles.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} ({item.fingerprint.slice(0, 12)}…)
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--card-border)] pt-3">
              <div className="flex flex-wrap items-center gap-4 text-xs">
                <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-[var(--app-text)]">
                  <input
                    type="checkbox"
                    checked={autoEnable}
                    onChange={(e) => setAutoEnable(e.target.checked)}
                    className="rounded border-slate-300 text-cyan-700"
                  />
                  保存后立即启用订阅
                </label>
                {autoEnable && (
                  <label className="inline-flex cursor-pointer items-center gap-1.5 font-semibold text-cyan-800 dark:text-cyan-300">
                    <input
                      type="checkbox"
                      checked={autoSimulate}
                      onChange={(e) => setAutoSimulate(e.target.checked)}
                      className="rounded border-slate-300 text-cyan-700"
                    />
                    <Sparkles size={13} />
                    启用后立即执行官方报文模拟推流（无真机验证）
                  </label>
                )}
              </div>

              <button
                type="submit"
                disabled={!canManage || saving || !selectedDevice || !selectedProfile || !selectedTemplate}
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-700 px-4 py-2.5 text-xs font-bold text-white shadow-xs transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : autoEnable && autoSimulate ? (
                  <Play size={14} />
                ) : (
                  <Plus size={14} />
                )}
                {autoEnable && autoSimulate
                  ? '一键开通并执行模拟推流验证'
                  : autoEnable
                    ? '一键保存并启用订阅'
                    : '仅保存配置与草稿订阅'}
              </button>
            </div>
          </div>
        </form>

        {/* Right 5 columns: Live Official Huawei VRP & H3C Comware V7 CLI Script Preview */}
        <div className="flex flex-col rounded-xl border border-slate-800 bg-slate-950 p-4 text-slate-100 xl:col-span-5">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <Terminal size={15} className="text-cyan-400" />
              <div>
                <p className="text-xs font-extrabold text-white">设备侧官方 CLI 配置脚本生成</p>
                <p className="text-[10px] text-slate-400">
                  支持华为 VRP (毫秒周期) 与华三 Comware V7 (秒级周期) 官方规范对比
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void copyCliPreview()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-2.5 py-1 text-[11px] font-bold text-cyan-300 transition hover:bg-cyan-500/25"
            >
              <Copy size={12} />
              复制 CLI 脚本
            </button>
          </div>

          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {(
              [
                { key: 'auto', label: '跟随所选协议档' },
                { key: 'huawei', label: '华为 CloudEngine (VRP)' },
                { key: 'h3c_v2', label: '华三 Comware V7 (二层 JSON)' },
                { key: 'h3c_v3', label: '华三 Comware V7 (三层 JSON)' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setCliPreviewMode(tab.key)}
                className={`rounded-md px-2 py-1 text-[10px] font-semibold transition ${
                  cliPreviewMode === tab.key
                    ? 'bg-cyan-600 text-white'
                    : 'bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <pre className="mt-3 flex-1 overflow-auto rounded-lg border border-slate-800/90 bg-slate-900/80 p-3 font-mono text-[11px] leading-relaxed text-cyan-100">
            {cliPreview}
          </pre>

          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
            <span>
              接收器端点：
              <code className="ml-1 text-cyan-300">
                {selectedCollector?.target_address || '192.168.56.1'}:{selectedCollector?.grpc_port || 10051}
              </code>
            </span>
            <span>
              {effectiveCliFlavour === 'huawei'
                ? '华为 sample-interval 单位为毫秒 (ms)'
                : '华三 sample-interval 单位为秒 (s)'}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
};

export default TelemetryControlSetupPanel;
