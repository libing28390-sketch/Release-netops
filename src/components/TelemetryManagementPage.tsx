import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  Clock3,
  Database,
  Gauge,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Server,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react';
import { ApiError } from '../api/http';
import {
  deleteTelemetrySubscription,
  getTelemetryCollectorCapacity,
  getTelemetryCollectors,
  getTelemetryProfiles,
  getTelemetrySubscriptionStatus,
  getTelemetrySubscriptions,
  runTelemetrySubscriptionAction,
  simulateTelemetrySubscription,
} from '../api/telemetry';
import type {
  TelemetryActionAccepted,
  TelemetryCapacityVector,
  TelemetryCollectorCapacity,
  TelemetryCollectorOption,
  TelemetryProtocolProfile,
  TelemetrySimulationResult,
  TelemetrySubscription,
  TelemetrySubscriptionAction,
  TelemetrySubscriptionStatus,
} from '../types/telemetry';
import type { Device } from '../types';
import Pagination from './Pagination';
import TelemetryControlSetupPanel from './TelemetryControlSetupPanel';

interface TelemetryManagementPageProps {
  /** Pass false when the current user's role is known to be read-only. */
  canManage?: boolean;
  devices?: Device[];
}

type Notice = { kind: 'success' | 'error'; message: string };
type LoadIssue = { source: string; message: string; forbidden: boolean };

const PAGE_SIZE = 20;

const PUBLISH_LABELS: Record<string, string> = {
  DRAFT: '草稿',
  QUEUED: '排队中',
  PUBLISHING: '发布中',
  APPLIED: '已应用',
  FAILED: '发布失败',
};
const CONNECTION_LABELS: Record<string, string> = {
  DISABLED: '已停用',
  AWAITING_DEVICE: '等待设备推流',
  CONNECTING: '连接中',
  CONNECTED: '已连接',
  ERROR: '连接异常',
};
const DATA_LABELS: Record<string, string> = {
  NO_DATA: '暂无数据',
  FRESH: '数据新鲜',
  PARTIAL: '数据不完整',
  STALE: '数据过期',
  INVALID: '数据无效',
};

const SUPPORT_LABELS: Record<string, string> = {
  DOCUMENTED: '官方已核验',
  SAMPLE_VERIFIED: '样本已验证',
  DEVICE_VERIFIED: '真机已验证',
  UNKNOWN: '待确认',
  UNSUPPORTED: '不支持',
};

function errorStatus(reason: unknown): number | undefined {
  return reason instanceof ApiError ? reason.status : undefined;
}

function errorMessage(reason: unknown, fallback: string): string {
  const status = errorStatus(reason);
  if (status === 401) return '登录状态已失效，请重新登录。';
  if (status === 403) return '当前账号没有查看或管理 Telemetry 数据的权限。';
  if (status === 404) return '目标资源不存在或已被删除，请刷新后重试。';
  if (reason instanceof ApiError && reason.code) {
    const known: Record<string, string> = {
      TELEMETRY_PROFILE_UNSUPPORTED: '所选协议档不支持此设备。',
      TELEMETRY_VERSION_UNVERIFIED: '设备软件版本尚未验证。',
      TELEMETRY_PATH_UNVERIFIED: '部分采集路径尚未验证。',
      TELEMETRY_INTERVAL_TOO_SHORT: '采样周期短于设备支持的最小周期。',
      TELEMETRY_CAPACITY_EXCEEDED: '采集器容量不足，操作未提交。',
      TELEMETRY_TLS_INVALID: '证书或 TLS 配置无效。',
      TELEMETRY_DEVICE_NOT_READY: '设备尚未准备好接收 Telemetry。',
      TELEMETRY_CONFIG_CONFLICT: '配置已被其他操作更新，请刷新后重试。',
    };
    if (known[reason.code]) return known[reason.code];
  }
  return reason instanceof Error && reason.message ? reason.message : fallback;
}

function displayDate(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

function displayVendor(value?: string): string {
  if (!value) return '—';
  const normalized = value.toLowerCase();
  if (normalized.includes('huawei')) return '华为';
  if (normalized === 'h3c' || normalized.includes('h3c')) return '华三';
  return value;
}

function statusTone(status?: string, type: 'publish' | 'connection' | 'data' | 'support' = 'data'): string {
  const value = (status || '').toUpperCase();
  if (['APPLIED', 'CONNECTED', 'FRESH', 'SUPPORTED', 'VERIFIED', 'SAMPLE_VERIFIED', 'DEVICE_VERIFIED', 'ENABLED', 'DOCUMENTED'].includes(value)) {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  }
  if (['FAILED', 'ERROR', 'INVALID', 'STALE', 'UNSUPPORTED'].includes(value)) {
    return 'border-rose-200 bg-rose-50 text-rose-700';
  }
  if (['UNKNOWN', 'PARTIAL', 'QUEUED', 'PUBLISHING', 'CONNECTING', 'AWAITING_DEVICE', 'UNVERIFIED', 'NO_DATA'].includes(value)) {
    return 'border-amber-200 bg-amber-50 text-amber-800';
  }
  if (type === 'connection' && value === 'DISABLED') return 'border-slate-200 bg-slate-100 text-slate-600';
  return 'border-[var(--card-border)] bg-[var(--card-bg)] text-[var(--muted-text)]';
}

function StatusPill({
  value,
  type,
  fallback = '未知',
  label,
}: {
  value?: string;
  type?: 'publish' | 'connection' | 'data' | 'support';
  fallback?: string;
  label?: string;
}) {
  const normalized = (value || '').toUpperCase();
  const labels =
    type === 'publish'
      ? PUBLISH_LABELS
      : type === 'connection'
        ? CONNECTION_LABELS
        : type === 'support'
          ? SUPPORT_LABELS
          : DATA_LABELS;
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-bold ${statusTone(normalized, type)}`}>
      {label || labels[normalized] || value || fallback}
    </span>
  );
}

function profileDisplayName(profile: TelemetryProtocolProfile): string {
  const key = profile.profile_key;
  if (key === 'h3c_grpc_dialout_json_v2') return '华三数据中心核心交换机协议 (二层 JSON)';
  if (key === 'h3c_grpc_dialout_json_v2_s6850_r6717') return '华三数据中心 ToR/Spine 协议 (二层 JSON)';
  if (key === 'h3c_grpc_dialout_json_v2_campus_s5135s') return '华三园区接入与汇聚交换机协议 (二层 JSON)';
  if (key === 'h3c_grpc_dialout_json_v2_sec_wlan') return '华三安全防火墙 / 无线 AC / 路由器协议';
  if (key === 'h3c_grpc_dialout_json_v3') return '华三园区与核心交换机协议 (三层 JSON v3)';
  if (key === 'h3c_grpc_dialout_json_v3_s6850_r6717') return '华三数据中心交换机协议 (三层 JSON v3)';
  if (key === 'huawei_grpc_dialout_json') return '华为园区交换机 / 路由器 / 防火墙协议';
  if (key === 'huawei_ce6800_v200r005c10_grpc_json') return '华为 CloudEngine 数据中心全系列协议';
  return profile.profile_key;
}

function profileSeriesBadges(profile: TelemetryProtocolProfile): { visible: string[]; extraCount: number } {
  const raw = String(profile.model_scope || '')
    .split(/[,/;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  // Keep concise series tokens (avoid showing both S5135S and S5135S-24P4S-EI in the summary pill bar)
  const concise = Array.from(
    new Set(
      raw.map((token) =>
        token
          .replace(/^CloudEngine\s+/i, '')
          .replace(/^NetEngine\s+/i, '')
          .replace(/\[[^\]]+\]/g, '')
          .split('-')[0]
          .trim(),
      ),
    ),
  ).filter(Boolean);
  return {
    visible: concise.slice(0, 4),
    extraCount: Math.max(0, concise.length - 4),
  };
}

function profileFriendlyVersion(profile: TelemetryProtocolProfile): string {
  const key = profile.profile_key;
  if (key.startsWith('h3c_')) {
    if (key.includes('s6850_r6717')) return 'Comware V7 (7.1.x / R67xx~R68xx)';
    return 'Comware V7 (7.1.x / R63xx~R69xx)';
  }
  if (key.includes('ce6800')) return 'VRP8 (V200R005+ / V300R022+)';
  return 'VRP (V200R019+ / V600R022+ / V800)';
}

function MetricValue({ label, value, icon: Icon }: { label: string; value: string; icon: LucideIcon }) {
  return (
    <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-3">
      <div className="flex items-center justify-between gap-2 text-[10px] font-bold text-[var(--muted-text)]">
        <span>{label}</span>
        <Icon size={14} />
      </div>
      <p className="mt-2 text-lg font-extrabold text-[var(--app-text)]">{value}</p>
    </div>
  );
}

function CapacityTable({ capacity }: { capacity: TelemetryCollectorCapacity }) {
  const formatBytes = (value: number) => {
    if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(value % 1024 ** 3 ? 1 : 0)} GiB`;
    if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(value % 1024 ** 2 ? 1 : 0)} MiB`;
    if (value >= 1024) return `${(value / 1024).toFixed(1)} KiB`;
    return `${value} B`;
  };
  const dimensions: Array<{ key: keyof TelemetryCapacityVector; label: string; format?: (value: number) => string }> = [
    { key: 'devices', label: '设备数' },
    { key: 'series', label: '序列数' },
    { key: 'samples_per_second', label: '样本/秒', format: (value) => value.toLocaleString('zh-CN') },
    { key: 'message_bytes', label: '消息大小', format: formatBytes },
    { key: 'queue_bytes', label: '持久队列', format: formatBytes },
  ];
  const cell = (value: number | null | undefined, format?: (value: number) => string) =>
    value == null ? '—' : format ? format(value) : value.toLocaleString('zh-CN');
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--card-border)]">
      <table className="w-full min-w-[500px] text-left text-[11px]">
        <thead className="bg-black/[0.025] text-[10px] font-bold text-[var(--muted-text)] dark:bg-white/[0.035]">
          <tr>
            <th className="px-3 py-2">容量维度</th>
            <th className="px-3 py-2">上限</th>
            <th className="px-3 py-2">已预留</th>
            <th className="px-3 py-2">实测</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--card-border)]">
          {dimensions.map(({ key, label, format }) => (
            <tr key={key}>
              <th scope="row" className="px-3 py-2 font-semibold text-[var(--app-text)]">
                {label}
              </th>
              <td className="px-3 py-2 text-[var(--muted-text)]">{cell(capacity.limit?.[key], format)}</td>
              <td className="px-3 py-2 text-[var(--muted-text)]">{cell(capacity.reserved?.[key], format)}</td>
              <td className="px-3 py-2 font-semibold text-[var(--app-text)]">{cell(capacity.observed?.[key], format)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-[var(--card-border)] px-3 py-2 text-[10px] text-[var(--muted-text)]">
        容量统计时间：{displayDate(capacity.measured_at)}
      </p>
    </div>
  );
}

function StatusDetails({ status }: { status: TelemetrySubscriptionStatus }) {
  return (
    <div className="grid gap-3 p-3 sm:grid-cols-2 xl:grid-cols-4">
      <div>
        <p className="text-[10px] font-bold text-[var(--muted-text)]">版本</p>
        <p className="mt-1 text-[11px] text-[var(--app-text)]">
          期望 {status.desired_version ?? '—'} · 已发布 {status.published_version ?? '—'} · 已应用 {status.applied_version ?? '—'}
        </p>
      </div>
      <div>
        <p className="text-[10px] font-bold text-[var(--muted-text)]">最近接收</p>
        <p className="mt-1 text-[11px] text-[var(--app-text)]">{displayDate(status.last_received_at)}</p>
      </div>
      <div>
        <p className="text-[10px] font-bold text-[var(--muted-text)]">最近有效样本</p>
        <p className="mt-1 text-[11px] text-[var(--app-text)]">{displayDate(status.last_valid_at)}</p>
      </div>
      {status.clock_skew_ms != null && (
        <div>
          <p className="text-[10px] font-bold text-[var(--muted-text)]">设备时钟偏差</p>
          <p className="mt-1 text-[11px] text-[var(--app-text)]">{status.clock_skew_ms.toLocaleString('zh-CN')} 毫秒</p>
        </div>
      )}
      <div>
        <p className="text-[10px] font-bold text-[var(--muted-text)]">活动序列 / 速率</p>
        <p className="mt-1 text-[11px] text-[var(--app-text)]">
          {status.active_series ?? '—'} / {status.samples_per_second ?? '—'} 样本/秒
        </p>
      </div>
      {status.error && (
        <div className="sm:col-span-2 xl:col-span-3">
          <p className="text-[10px] font-bold text-rose-700">{status.error.code}</p>
          <p className="mt-1 text-[11px] text-rose-700">{status.error.message}</p>
        </div>
      )}
    </div>
  );
}

type TelemetrySubPage = 'onboarding' | 'subscriptions' | 'protocols' | 'capacity';

const SUPPORTED_MODEL_FAMILIES: Array<{
  vendor: 'h3c' | 'huawei';
  vendorLabel: string;
  category: string;
  protocolLabel: string;
  series: string;
  models: string[];
}> = [
  {
    vendor: 'h3c',
    vendorLabel: '华三 H3C',
    category: '园区接入与汇聚交换机',
    protocolLabel: 'Comware V7 · 二层 / 三层 JSON',
    series: 'S5135S-EI/HI / S5130S-EI/HI / S5170-EI / S5000-EI / S5560X-EI/HI / S5570S-EI / S5590-EI / S6520X-SI/EI/HI',
    models: [
      'S5135S-24P4S-EI',
      'S5135S-48T4S-EI-Q',
      'S5135S-28P-EI',
      'S5135S-52P-EI',
      'S5130S-28P-EI',
      'S5130S-52P-EI',
      'S5130S-28S-HI',
      'S5130S-52S-HI',
      'S5170-28S-EI',
      'S5170-54S-EI',
      'S5024PV5-EI',
      'S5048PV5-EI',
      'S5560X-30C-EI',
      'S5560X-54C-EI',
      'S5560X-34S-HI',
      'S5560X-54S-HI',
      'S5570S-28S-EI',
      'S5570S-36F-EI',
      'S5570S-54S-EI',
      'S5590-28T4XC-EI',
      'S5590-48T4XC-EI',
      'S6520X-26C-SI',
      'S6520X-54XC-UPWR-SI',
      'S6520X-30QC-EI',
      'S6520X-54QC-EI',
      'S6520X-30HF-HI',
      'S6520X-54HF-HI',
    ],
  },
  {
    vendor: 'h3c',
    vendorLabel: '华三 H3C',
    category: '园区框式核心交换机',
    protocolLabel: 'Comware V7 · 二层 / 三层 JSON',
    series: 'S7500E / S7500X-G / S10500 / S10500X-G',
    models: ['S7503E', 'S7506E', 'S7510E', 'S7506X-G', 'S7510X-G', 'S10508X', 'S10506X-G', 'S10512X-G'],
  },
  {
    vendor: 'h3c',
    vendorLabel: '华三 H3C',
    category: '数据中心交换机 (Leaf / Spine / Core)',
    protocolLabel: 'Comware V7 · 二层 / 三层 JSON',
    series: 'S6800 / S6805 / S6812 / S6813 / S6820 / S6825 / S6850 / S6860 / S6861 / S6890 / S9820 / S9825 / S9850 / S9855 / S12500G-AF/X-AF/R',
    models: [
      'S6800-54QF',
      'S6800-54HT',
      'S6805-54HF',
      'S6812',
      'S6813',
      'S6820-56HF',
      'S6825-54HT',
      'S6825-54HF',
      'S6850',
      'S6850-56HF',
      'S6850-2C',
      'S6860-54HF',
      'S6861-54QF',
      'S6890-54HF',
      'S9820-8C',
      'S9820-64H',
      'S9825-64D',
      'S9850-32H',
      'S9850-4C',
      'S9855',
      'S9855-48CD8D',
      'S9855-32D',
      'S12508G-AF',
      'S12516G-AF',
      'S12508X-AF',
      'S12516X-AF',
      'S12508R',
    ],
  },
  {
    vendor: 'h3c',
    vendorLabel: '华三 H3C',
    category: '安全防火墙 / 无线 AC / 路由器',
    protocolLabel: 'Comware V7 · 二层 JSON',
    series: 'SecPath F1000 / F5000 / M9000 / WX3500H / WX5500E / WX5540H / MSR3600 / MSR5600 / SR6600 / CR16000 / CR19000',
    models: [
      'F1060',
      'F1070',
      'F1080',
      'F1090',
      'F5020',
      'F5040',
      'F5080',
      'M9000',
      'WX3520H',
      'WX3540H',
      'WX5500E',
      'WX5540H',
      'WX5540H-HCL',
      'MSR3620',
      'MSR5660',
      'SR6604',
      'SR6608',
      'CR16000',
      'CR19000',
    ],
  },
  {
    vendor: 'huawei',
    vendorLabel: '华为 Huawei',
    category: '园区接入与汇聚交换机 (CloudEngine S)',
    protocolLabel: 'VRP · gRPC Dial-out JSON',
    series: 'CloudEngine S3700 / S5700 / S5720 / S5730 / S5731-H/S / S5732-H / S5735-L/S/V2 / S5736-S / S5755-H / S6720-EI / S6730-H/S/V2 / S6750-H/S',
    models: [
      'CloudEngine S5731-H24P4XC',
      'CloudEngine S5731-H48T4XC-B',
      'CloudEngine S5731-S24P4X',
      'CloudEngine S5731-S48T4X',
      'CloudEngine S5732-H24S6Q',
      'CloudEngine S5732-H48S6Q',
      'CloudEngine S5732-H48UM2CC',
      'CloudEngine S5735-L24P4S-A',
      'CloudEngine S5735-L48P4X-A',
      'CloudEngine S5735-L48T4XE-A-V2',
      'CloudEngine S5735-S24P4X',
      'CloudEngine S5735-S24P4XE-V2',
      'CloudEngine S5735-S48T4XE-V2',
      'CloudEngine S5736-S24U4XC',
      'CloudEngine S5736-S48S4XC',
      'CloudEngine S5755-H24U4Y2CZ',
      'CloudEngine S5755-H48U4Y2CZ',
      'CloudEngine S6720-30C-EI-24S-AC',
      'CloudEngine S6720-54C-EI-48S-AC',
      'CloudEngine S6730-S24X6Q',
      'CloudEngine S6730-S48X6Q',
      'CloudEngine S6730-H24X6C',
      'CloudEngine S6730-H48X6C',
      'CloudEngine S6730-H48X6C-V2',
      'CloudEngine S6750-H36C',
      'CloudEngine S6750-S48X8C',
    ],
  },
  {
    vendor: 'huawei',
    vendorLabel: '华为 Huawei',
    category: '园区框式核心交换机',
    protocolLabel: 'VRP · gRPC Dial-out JSON',
    series: 'CloudEngine S7700 / S8700 / S9700 / S12700 / S12700E / S16700',
    models: [
      'CloudEngine S7706',
      'CloudEngine S7712',
      'CloudEngine S8700-4',
      'CloudEngine S8700-6',
      'CloudEngine S8700-10',
      'CloudEngine S12700E-4',
      'CloudEngine S12700E-8',
      'CloudEngine S12700E-12',
      'CloudEngine S16700-4',
      'CloudEngine S16700-8',
    ],
  },
  {
    vendor: 'huawei',
    vendorLabel: '华为 Huawei',
    category: '数据中心交换机 (CloudEngine CE)',
    protocolLabel: 'VRP8 · gRPC Dial-out JSON',
    series: 'CloudEngine CE5800 / CE6800 / CE8800 / CE9800 / CE12800 / CE16800 / XH16800',
    models: [
      'CE5855-48T4S2Q-EI',
      'CE5881-48T6CQ',
      'CE6820-48S6CQ',
      'CE6850-48S6Q-HI',
      'CE6855-48S6Q-HI',
      'CE6857-48S6CQ-EI',
      'CE6860-SAN',
      'CE6863-48S6CQ',
      'CE6863E-48S6CQ',
      'CE6865-48S8CQ-EI',
      'CE6866-48S8CQ-P',
      'CE6870-48S6CQ-EI',
      'CE6881-48S6CQ',
      'CE6881E-48S6CQ',
      'CE6885-48YS8CQ',
      'CE8850-64CQ-EI',
      'CE8850-HAM',
      'CE8851-32CQ8DQ-K',
      'CE8855-32CQ4BQ',
      'CE8861-4C-EI',
      'CE8868-4C-EI',
      'CE9860-4C-EI',
      'CE9865-4C-EI',
      'CE9866-128DQ',
      'CE12804',
      'CE12808',
      'CE12812',
      'CE12816',
      'CE16804',
      'CE16808',
      'CE16816',
      'XH16800-8',
      'XH16800-16',
    ],
  },
  {
    vendor: 'huawei',
    vendorLabel: '华为 Huawei',
    category: '安全防火墙 / 无线 AC / 路由器',
    protocolLabel: 'VRP / VRP8 · gRPC Dial-out JSON',
    series: 'HiSecEngine USG6000E / AirEngine 9700 / AC6508 / AC6805 / NetEngine AR600/6100/6200/6300 / NE40E / NetEngine 8000',
    models: [
      'HiSecEngine USG6500E',
      'HiSecEngine USG6630E',
      'HiSecEngine USG6700E',
      'AirEngine 9700-M1',
      'AC6508',
      'AC6805',
      'NetEngine AR6280',
      'NE40E-X8A',
      'NetEngine 8000 M8',
    ],
  },
];

const TelemetryManagementPage: React.FC<TelemetryManagementPageProps> = ({ canManage = true, devices = [] }) => {
  const location = useLocation();
  const navigate = useNavigate();

  const activeSubPage: TelemetrySubPage = useMemo(() => {
    const seg = location.pathname.split('/').filter(Boolean)[2] || 'onboarding';
    if (seg === 'subscriptions' || seg === 'protocols' || seg === 'capacity') return seg;
    return 'onboarding';
  }, [location.pathname]);

  const switchSubPage = useCallback(
    (target: TelemetrySubPage) => {
      navigate(`/monitor/telemetry-management/${target}`);
    },
    [navigate],
  );

  const [profiles, setProfiles] = useState<TelemetryProtocolProfile[]>([]);
  const [collectors, setCollectors] = useState<TelemetryCollectorOption[]>([]);
  const [subscriptions, setSubscriptions] = useState<TelemetrySubscription[]>([]);
  const [totalSubscriptions, setTotalSubscriptions] = useState(0);
  const [page, setPage] = useState(1);
  const [loadedPage, setLoadedPage] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadIssues, setLoadIssues] = useState<LoadIssue[]>([]);
  const [mutationDenied, setMutationDenied] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyActions, setBusyActions] = useState<Record<string, string>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedStatus, setExpandedStatus] = useState<TelemetrySubscriptionStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusIssue, setStatusIssue] = useState<string | null>(null);
  const [selectedCollectorId, setSelectedCollectorId] = useState('');
  const [capacity, setCapacity] = useState<TelemetryCollectorCapacity | null>(null);
  const [capacityLoading, setCapacityLoading] = useState(false);
  const [capacityIssue, setCapacityIssue] = useState<LoadIssue | null>(null);
  const [latestSimulation, setLatestSimulation] = useState<TelemetrySimulationResult | null>(null);

  const [subSearch, setSubSearch] = useState('');
  const [subStateFilter, setSubStateFilter] = useState<'all' | 'connected' | 'awaiting' | 'disabled'>('all');
  const [protocolViewTab, setProtocolViewTab] = useState<'profiles' | 'models'>('profiles');
  const [modelVendorFilter, setModelVendorFilter] = useState<'all' | 'h3c' | 'huawei'>('all');
  const [modelCategoryFilter, setModelCategoryFilter] = useState<string>('all');
  const [modelSearch, setModelSearch] = useState('');
  const [modelPage, setModelPage] = useState(1);
  const [modelPageSize, setModelPageSize] = useState(20);
  const [expandedProfileId, setExpandedProfileId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    setLoadIssues([]);
    void Promise.allSettled([
      getTelemetryProfiles(controller.signal),
      getTelemetrySubscriptions({ page, page_size: PAGE_SIZE }, controller.signal),
      getTelemetryCollectors(controller.signal),
    ])
      .then(([profilesResult, subscriptionsResult, collectorsResult]) => {
        if (controller.signal.aborted) return;
        const issues: LoadIssue[] = [];
        if (profilesResult.status === 'fulfilled') setProfiles(profilesResult.value.items || []);
        else
          issues.push({
            source: '协议档',
            message: errorMessage(profilesResult.reason, '协议档加载失败。'),
            forbidden: errorStatus(profilesResult.reason) === 403,
          });
        if (subscriptionsResult.status === 'fulfilled') {
          setSubscriptions(subscriptionsResult.value.items || []);
          setTotalSubscriptions(subscriptionsResult.value.total || 0);
          setLoadedPage(page);
        } else {
          issues.push({
            source: '订阅列表',
            message: errorMessage(subscriptionsResult.reason, '订阅列表加载失败。'),
            forbidden: errorStatus(subscriptionsResult.reason) === 403,
          });
        }
        if (collectorsResult.status === 'fulfilled')
          setCollectors(
            (collectorsResult.value.items || []).filter(
              (item) => item.collector_type === 'LOCAL' && item.enabled !== false && item.enabled !== 0,
            ),
          );
        else
          issues.push({
            source: '采集器列表',
            message: errorMessage(collectorsResult.reason, '采集器列表加载失败。'),
            forbidden: errorStatus(collectorsResult.reason) === 403,
          });
        setLoadIssues(issues);
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, [page, reloadKey]);

  const currentPageSubscriptions = loadedPage === page ? subscriptions : [];

  const collectorOptions = useMemo(
    () =>
      collectors.map((collector) => ({
        id: collector.id,
        label: collector.name || collector.id,
      })),
    [collectors],
  );

  useEffect(() => {
    if (collectorOptions.some((item) => item.id === selectedCollectorId)) return;
    setSelectedCollectorId(collectorOptions[0]?.id || '');
  }, [collectorOptions, selectedCollectorId]);

  useEffect(() => {
    if (!selectedCollectorId) {
      setCapacity(null);
      setCapacityIssue(null);
      setCapacityLoading(false);
      return;
    }
    const controller = new AbortController();
    setCapacityLoading(true);
    setCapacityIssue(null);
    void getTelemetryCollectorCapacity(selectedCollectorId, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setCapacity(payload);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setCapacity(null);
        setCapacityIssue({
          source: '容量摘要',
          message: errorMessage(reason, '采集器容量摘要加载失败。'),
          forbidden: errorStatus(reason) === 403,
        });
      })
      .finally(() => {
        if (!controller.signal.aborted) setCapacityLoading(false);
      });
    return () => controller.abort();
  }, [selectedCollectorId, reloadKey]);

  useEffect(() => {
    if (!expandedId) {
      setExpandedStatus(null);
      setStatusIssue(null);
      return;
    }
    const controller = new AbortController();
    setExpandedStatus(null);
    setStatusIssue(null);
    setStatusLoading(true);
    void getTelemetrySubscriptionStatus(expandedId, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setExpandedStatus(payload);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setStatusIssue(errorMessage(reason, '订阅状态加载失败。'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setStatusLoading(false);
      });
    return () => controller.abort();
  }, [expandedId, reloadKey]);

  const refresh = useCallback(() => {
    setNotice(null);
    setReloadKey((current) => current + 1);
  }, []);

  const submitAction = useCallback(async (subscription: TelemetrySubscription, action: TelemetrySubscriptionAction) => {
    setBusyActions((current) => ({ ...current, [subscription.id]: action }));
    setNotice(null);
    try {
      const accepted: TelemetryActionAccepted = await runTelemetrySubscriptionAction(subscription.id, action);
      const actionLabel = action === 'enable' ? '启用' : action === 'disable' ? '停用' : '重试';
      setNotice({
        kind: 'success',
        message: `${actionLabel}请求已提交（版本 ${accepted.desired_version}）。`,
      });
      setReloadKey((current) => current + 1);
    } catch (reason) {
      if (errorStatus(reason) === 403) setMutationDenied(true);
      setNotice({ kind: 'error', message: errorMessage(reason, '操作提交失败。') });
    } finally {
      setBusyActions((current) => {
        const next = { ...current };
        delete next[subscription.id];
        return next;
      });
    }
  }, []);

  const handleSimulate = useCallback(async (subscription: TelemetrySubscription) => {
    setBusyActions((current) => ({ ...current, [subscription.id]: 'simulate' }));
    setNotice(null);
    try {
      const sim = await simulateTelemetrySubscription(subscription.id);
      setLatestSimulation(sim);
      setNotice({
        kind: 'success',
        message: `模拟推流成功！「${sim.hostname}」通过 ${sim.wire_format} 解码生成 ${sim.active_series} 条 Prometheus 指标序列，状态已更新为「已连接 · 数据新鲜」。`,
      });
      setReloadKey((current) => current + 1);
    } catch (reason) {
      setNotice({ kind: 'error', message: errorMessage(reason, '模拟推流执行失败。') });
    } finally {
      setBusyActions((current) => {
        const next = { ...current };
        delete next[subscription.id];
        return next;
      });
    }
  }, []);

  const handleDelete = useCallback(async (subscription: TelemetrySubscription) => {
    setBusyActions((current) => ({ ...current, [subscription.id]: 'delete' }));
    setNotice(null);
    try {
      await deleteTelemetrySubscription(subscription.id);
      setNotice({ kind: 'success', message: `订阅「${subscription.name}」已移除。` });
      if (latestSimulation?.subscription_id === subscription.id) setLatestSimulation(null);
      setReloadKey((current) => current + 1);
    } catch (reason) {
      setNotice({ kind: 'error', message: errorMessage(reason, '删除订阅失败。') });
    } finally {
      setBusyActions((current) => {
        const next = { ...current };
        delete next[subscription.id];
        return next;
      });
    }
  }, [latestSimulation?.subscription_id]);

  const managedDisabled = !canManage || mutationDenied || loadIssues.some((issue) => issue.forbidden);
  const currentPageCount = Math.ceil(totalSubscriptions / PAGE_SIZE);
  const activeCount = currentPageSubscriptions.filter((item) => item.desired_enabled).length;
  const failedCount = currentPageSubscriptions.filter(
    (item) =>
      item.runtime?.publish_state === 'FAILED' ||
      item.runtime?.connection_state === 'ERROR' ||
      item.runtime?.data_state === 'INVALID',
  ).length;

  const filteredSubscriptions = useMemo(() => {
    const q = subSearch.trim().toLowerCase();
    return currentPageSubscriptions.filter((sub) => {
      if (subStateFilter === 'connected' && sub.runtime?.connection_state !== 'CONNECTED') return false;
      if (subStateFilter === 'awaiting' && sub.runtime?.connection_state !== 'AWAITING_DEVICE') return false;
      if (subStateFilter === 'disabled' && sub.desired_enabled) return false;
      if (!q) return true;
      const hay = [
        sub.device_name,
        sub.asset_tag,
        sub.device_id,
        sub.name,
        sub.profile_name,
        sub.template_name,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [currentPageSubscriptions, subSearch, subStateFilter]);

  const allModelRows = useMemo(() => {
    const rows: Array<{
      vendor: 'h3c' | 'huawei';
      vendorLabel: string;
      sku: string;
      seriesName: string;
      category: string;
      protocolLabel: string;
      defaultProfileKey: string;
      osVersion: string;
    }> = [];
    for (const fam of SUPPORTED_MODEL_FAMILIES) {
      for (const sku of fam.models) {
        const cleanToken = sku.replace(/^CloudEngine\s+/i, '').replace(/^HiSecEngine\s+/i, '').replace(/^NetEngine\s+/i, '').replace(/^AirEngine\s+/i, '');
        const seriesPrefix = cleanToken.split('-')[0] || cleanToken;
        let defaultProfileKey = 'h3c_grpc_dialout_json_v2';
        let osVersion = 'Comware V7 (7.1.070+ / R63xx~R69xx)';
        if (fam.vendor === 'h3c') {
          if (fam.category.includes('园区')) {
            defaultProfileKey = 'h3c_grpc_dialout_json_v2_campus_s5135s';
          } else if (fam.category.includes('安全')) {
            defaultProfileKey = 'h3c_grpc_dialout_json_v2_sec_wlan';
          } else if (/^S(?:682|685|686|689|982|985)/.test(cleanToken)) {
            defaultProfileKey = 'h3c_grpc_dialout_json_v2_s6850_r6717';
          } else {
            defaultProfileKey = 'h3c_grpc_dialout_json_v2';
          }
        } else {
          if (fam.category.includes('数据中心')) {
            defaultProfileKey = 'huawei_ce6800_v200r005c10_grpc_json';
            osVersion = 'VRP8 (V200R005C10+ / V300R023+)';
          } else {
            defaultProfileKey = 'huawei_grpc_dialout_json';
            osVersion = 'VRP (V200R019+ / V600R022+ / V800R021+)';
          }
        }
        rows.push({
          vendor: fam.vendor,
          vendorLabel: fam.vendorLabel,
          sku,
          seriesName: `${seriesPrefix} 系列`,
          category: fam.category,
          protocolLabel: fam.protocolLabel,
          defaultProfileKey,
          osVersion,
        });
      }
    }
    return rows;
  }, []);

  const filteredModelRows = useMemo(() => {
    const q = modelSearch.trim().toLowerCase();
    return allModelRows.filter((row) => {
      if (modelVendorFilter !== 'all' && row.vendor !== modelVendorFilter) return false;
      if (modelCategoryFilter !== 'all' && row.category !== modelCategoryFilter) return false;
      if (!q) return true;
      return (
        row.sku.toLowerCase().includes(q) ||
        row.seriesName.toLowerCase().includes(q) ||
        row.category.toLowerCase().includes(q) ||
        row.defaultProfileKey.toLowerCase().includes(q) ||
        row.vendorLabel.toLowerCase().includes(q)
      );
    });
  }, [allModelRows, modelVendorFilter, modelCategoryFilter, modelSearch]);

  const totalModelPages = Math.max(1, Math.ceil(filteredModelRows.length / modelPageSize));
  const safeModelPage = Math.min(modelPage, totalModelPages);
  const pagedModelRows = useMemo(
    () =>
      filteredModelRows.slice(
        (safeModelPage - 1) * modelPageSize,
        safeModelPage * modelPageSize,
      ),
    [filteredModelRows, safeModelPage, modelPageSize],
  );

  const filteredProfiles = useMemo(() => {
    const q = modelSearch.trim().toLowerCase();
    return profiles.filter((p) => {
      const vKey = String(p.vendor || '').toLowerCase();
      if (modelVendorFilter !== 'all' && !vKey.includes(modelVendorFilter)) return false;
      if (!q) return true;
      return (
        profileDisplayName(p).toLowerCase().includes(q) ||
        String(p.profile_key || '').toLowerCase().includes(q) ||
        String(p.model_scope || '').toLowerCase().includes(q) ||
        String(p.version_scope || '').toLowerCase().includes(q) ||
        (p.paths || []).some((pathItem) => pathItem.path.toLowerCase().includes(q))
      );
    });
  }, [profiles, modelVendorFilter, modelSearch]);

  return (
    <section className="space-y-4">
      {canManage === false && (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
          <ShieldCheck size={15} className="mt-0.5 shrink-0" />
          当前账号仅有查看权限，配置与仿真操作已禁用。
        </div>
      )}
      {loadIssues.map((issue) => (
        <div
          key={`${issue.source}:${issue.message}`}
          role="alert"
          className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-xs ${
            issue.forbidden ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-amber-200 bg-amber-50 text-amber-800'
          }`}
        >
          {issue.forbidden ? <ShieldAlert size={15} className="mt-0.5 shrink-0" /> : <AlertTriangle size={15} className="mt-0.5 shrink-0" />}
          <span>
            <b>{issue.source}：</b>
            {issue.message}
          </span>
        </div>
      ))}
      {notice && (
        <div
          role={notice.kind === 'error' ? 'alert' : 'status'}
          className={`rounded-xl border px-3 py-2.5 text-xs ${
            notice.kind === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
          }`}
        >
          {notice.message}
        </div>
      )}

      {/* Live Official Wire-Protocol Simulation Result Drawer (shown on Onboarding & Subscriptions) */}
      {latestSimulation && (activeSubPage === 'onboarding' || activeSubPage === 'subscriptions') && (
        <section className="rounded-2xl border border-emerald-300/80 bg-emerald-50/40 p-4 shadow-sm dark:border-emerald-500/30 dark:bg-emerald-950/20 md:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-300">
                <Sparkles size={13} />
                官方 Protobuf 报文仿真验证通过
              </p>
              <h3 className="mt-1 text-sm font-extrabold text-[var(--app-text)]">
                {latestSimulation.hostname}（{displayVendor(latestSimulation.vendor)}）· {latestSimulation.wire_format}
              </h3>
              <p className="mt-0.5 text-xs text-[var(--muted-text)]">
                已按厂商官方 Protobuf 帧结构完成二进制编码 → wire.py 解包 → normalizer.py 指标归一化 → 接收器状态回写。
              </p>
            </div>
            <div className="flex items-center gap-2">
              {activeSubPage === 'onboarding' && (
                <button
                  type="button"
                  onClick={() => switchSubPage('subscriptions')}
                  className="rounded-lg bg-emerald-700 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-emerald-800"
                >
                  去订阅列表查看状态 →
                </button>
              )}
              <button
                type="button"
                onClick={() => setLatestSimulation(null)}
                className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2.5 py-1 text-[11px] font-semibold text-[var(--muted-text)] hover:text-[var(--app-text)]"
              >
                关闭报告
              </button>
            </div>
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {latestSimulation.decoded_frames.map((frame, idx) => (
              <div key={`${frame.sensor_path}:${idx}`} className="rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] p-2.5 text-xs">
                <code className="block truncate font-mono text-[11px] font-bold text-cyan-800 dark:text-cyan-300">{frame.sensor_path}</code>
                <p className="mt-1 text-[10px] text-[var(--muted-text)]">
                  Protobuf 帧大小：{frame.wire_bytes} Bytes · 产出指标：{frame.sample_count} 条
                </p>
              </div>
            ))}
          </div>

          <div className="mt-3">
            <p className="mb-1.5 text-[11px] font-bold text-[var(--app-text)]">
              归一化产出的 Prometheus 指标样本（共 {latestSimulation.normalized_samples.length} 条）：
            </p>
            <pre className="max-h-48 overflow-auto rounded-xl bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-emerald-300">
              {latestSimulation.normalized_samples.join('\n')}
            </pre>
          </div>
        </section>
      )}

      {/* SUB-PAGE 1: Quick Onboarding & Official CLI Wizard */}
      {activeSubPage === 'onboarding' && (
        <TelemetryControlSetupPanel
          devices={devices}
          profiles={profiles}
          canManage={canManage && !mutationDenied}
          onChanged={refresh}
          onSimulated={(res) => setLatestSimulation(res)}
          onNavigateSubPage={switchSubPage}
        />
      )}

      {/* SUB-PAGE 2: Subscription Management & No-Hardware Wire Simulation */}
      {activeSubPage === 'subscriptions' && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricValue
              label="已配置订阅总数"
              value={`${currentPageSubscriptions.length} / ${loadedPage === page ? totalSubscriptions : '—'}`}
              icon={Activity}
            />
            <MetricValue label="已启用订阅" value={activeCount.toLocaleString('zh-CN')} icon={Play} />
            <MetricValue label="异常 / 告警订阅" value={failedCount.toLocaleString('zh-CN')} icon={AlertTriangle} />
          </div>

          <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-extrabold text-[var(--app-text)]">
                  <Activity size={16} className="text-violet-600" />
                  订阅列表与无真机推流测试
                </h2>
                <p className="mt-1 text-[11px] text-[var(--muted-text)]">
                  可随时启停订阅，或点击「模拟推流」验证华为/华三官方 Protobuf + JSON 报文解析与状态流转。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-full bg-black/[0.04] px-2.5 py-1 text-[10px] font-bold text-[var(--muted-text)] dark:bg-white/[0.06]">
                  <Clock3 size={12} />
                  支持无真机官方报文仿真
                </span>
                <button
                  type="button"
                  onClick={() => switchSubPage('onboarding')}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-700 px-3 py-1.5 text-xs font-bold text-white shadow-2xs transition hover:bg-cyan-800"
                >
                  <Plus size={14} />
                  新增设备订阅
                </button>
              </div>
            </div>

            {/* Subscription Filter & Search Bar */}
            <div className="mt-3.5 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--card-border)] pt-3">
              <div className="relative min-w-[220px] flex-1 max-w-md">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" />
                <input
                  type="text"
                  value={subSearch}
                  onChange={(e) => setSubSearch(e.target.value)}
                  placeholder="搜索订阅设备、订阅名称或协议档..."
                  className="h-9 w-full rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] pl-8 pr-8 text-xs text-[var(--app-text)] outline-none transition focus:border-cyan-600"
                />
                {subSearch && (
                  <button
                    type="button"
                    onClick={() => setSubSearch('')}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-text)] hover:text-[var(--app-text)]"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-1">
                {(
                  [
                    { key: 'all', label: `全部 (${currentPageSubscriptions.length})` },
                    {
                      key: 'connected',
                      label: `已连接推流 (${currentPageSubscriptions.filter((s) => s.runtime?.connection_state === 'CONNECTED').length})`,
                    },
                    {
                      key: 'awaiting',
                      label: `等待设备推流 (${currentPageSubscriptions.filter((s) => s.runtime?.connection_state === 'AWAITING_DEVICE').length})`,
                    },
                    {
                      key: 'disabled',
                      label: `已停用 (${currentPageSubscriptions.filter((s) => !s.desired_enabled).length})`,
                    },
                  ] as const
                ).map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => setSubStateFilter(f.key)}
                    className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold transition ${
                      subStateFilter === f.key
                        ? 'bg-cyan-700 text-white'
                        : 'border border-[var(--card-border)] bg-black/[0.02] text-[var(--muted-text)] hover:text-[var(--app-text)] dark:bg-white/[0.04]'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>

            {isLoading && currentPageSubscriptions.length === 0 ? (
              <div className="mt-4 flex items-center justify-center gap-2 rounded-xl border border-dashed border-[var(--card-border)] py-12 text-xs text-[var(--muted-text)]">
                <Loader2 size={15} className="animate-spin" />
                正在加载订阅…
              </div>
            ) : filteredSubscriptions.length ? (
              <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--card-border)]">
                <table className="w-full min-w-[980px] text-left text-[11px]">
                  <thead className="bg-black/[0.025] text-[10px] font-bold text-[var(--muted-text)] dark:bg-white/[0.035]">
                    <tr>
                      <th className="px-3 py-2.5">设备</th>
                      <th className="px-3 py-2.5">订阅 / 协议档</th>
                      <th className="px-3 py-2.5">期望</th>
                      <th className="px-3 py-2.5">发布</th>
                      <th className="px-3 py-2.5">连接</th>
                      <th className="px-3 py-2.5">数据</th>
                      <th className="px-3 py-2.5">最近有效样本</th>
                      <th className="px-3 py-2.5">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--card-border)]">
                    {filteredSubscriptions.map((subscription) => {
                      const busy = busyActions[subscription.id];
                      const runtime = subscription.runtime;
                      const label = subscription.device_name || subscription.asset_tag || subscription.device_id;
                      return (
                        <Fragment key={subscription.id}>
                          <tr className="align-top">
                            <td className="px-3 py-3">
                              <p className="font-bold text-[var(--app-text)]">{label}</p>
                              <p className="mt-0.5 font-mono text-[10px] text-[var(--muted-text)]">{subscription.asset_tag || subscription.device_id}</p>
                            </td>
                            <td className="px-3 py-3">
                              <p className="font-semibold text-[var(--app-text)]">{subscription.name}</p>
                              <p className="mt-0.5 text-[10px] text-[var(--muted-text)]">
                                {subscription.profile_name || '未关联协议档'}
                                {subscription.template_name ? ` · ${subscription.template_name} v${subscription.template_version ?? '—'}` : ''}
                              </p>
                              <p className="mt-0.5 text-[10px] text-[var(--muted-text)]">
                                {subscription.interval_seconds ? `${subscription.interval_seconds} 秒周期` : '周期未知'}
                                {subscription.collector_name ? ` · ${subscription.collector_name}` : ''}
                              </p>
                            </td>
                            <td className="px-3 py-3">
                              <StatusPill
                                value={subscription.desired_enabled ? 'ENABLED' : 'DISABLED'}
                                type={subscription.desired_enabled ? 'support' : 'connection'}
                                label={subscription.desired_enabled ? '已启用' : '已停用'}
                              />
                            </td>
                            <td className="px-3 py-3">
                              <StatusPill value={runtime?.publish_state} type="publish" />
                            </td>
                            <td className="px-3 py-3">
                              <StatusPill value={runtime?.connection_state} type="connection" />
                            </td>
                            <td className="px-3 py-3">
                              <StatusPill value={runtime?.data_state} type="data" />
                            </td>
                            <td className="px-3 py-3 text-[10px] text-[var(--muted-text)]">{displayDate(runtime?.last_valid_at)}</td>
                            <td className="px-3 py-3">
                              <div className="flex flex-wrap gap-1.5">
                                <button
                                  type="button"
                                  disabled={managedDisabled || Boolean(busy)}
                                  onClick={() => void handleSimulate(subscription)}
                                  className="inline-flex items-center gap-1 rounded-md bg-cyan-700 px-2.5 py-1.5 text-[10px] font-bold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-50"
                                  title="使用厂商官方 Protobuf + JSON 样本模拟设备推流"
                                >
                                  {busy === 'simulate' ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                                  模拟推流
                                </button>
                                <button
                                  type="button"
                                  disabled={managedDisabled || Boolean(busy)}
                                  onClick={() => void submitAction(subscription, subscription.desired_enabled ? 'disable' : 'enable')}
                                  className={`inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[10px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-50 ${
                                    subscription.desired_enabled ? 'bg-slate-600 hover:bg-slate-700' : 'bg-emerald-600 hover:bg-emerald-700'
                                  }`}
                                >
                                  {busy === 'enable' || busy === 'disable' ? (
                                    <Loader2 size={12} className="animate-spin" />
                                  ) : subscription.desired_enabled ? (
                                    <Pause size={12} />
                                  ) : (
                                    <Play size={12} />
                                  )}
                                  {subscription.desired_enabled ? '停用' : '启用'}
                                </button>
                                <button
                                  type="button"
                                  disabled={managedDisabled || Boolean(busy)}
                                  onClick={() => void submitAction(subscription, 'retry')}
                                  className="inline-flex items-center gap-1 rounded-md border border-[var(--card-border)] px-2 py-1.5 text-[10px] font-bold text-[var(--app-text)] hover:bg-black/[0.04] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/[0.06]"
                                >
                                  {busy === 'retry' ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                                  重试
                                </button>
                                <button
                                  type="button"
                                  aria-expanded={expandedId === subscription.id}
                                  onClick={() => setExpandedId((current) => (current === subscription.id ? null : subscription.id))}
                                  className="rounded-md px-2 py-1.5 text-[10px] font-bold text-cyan-700 hover:bg-cyan-50"
                                >
                                  {expandedId === subscription.id ? '收起' : '详情'}
                                </button>
                                <button
                                  type="button"
                                  disabled={managedDisabled || Boolean(busy)}
                                  onClick={() => void handleDelete(subscription)}
                                  className="inline-flex items-center gap-1 rounded-md border border-rose-200 px-2 py-1.5 text-[10px] font-bold text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                                  title="删除此订阅"
                                >
                                  {busy === 'delete' ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                                </button>
                              </div>
                            </td>
                          </tr>
                          {expandedId === subscription.id && (
                            <tr>
                              <td colSpan={8} className="bg-black/[0.02] dark:bg-white/[0.025]">
                                {statusLoading ? (
                                  <p className="flex items-center gap-2 p-3 text-[11px] text-[var(--muted-text)]">
                                    <Loader2 size={13} className="animate-spin" />
                                    正在加载状态详情…
                                  </p>
                                ) : statusIssue ? (
                                  <p role="alert" className="p-3 text-[11px] text-rose-700">
                                    {statusIssue}
                                  </p>
                                ) : expandedStatus ? (
                                  <StatusDetails status={expandedStatus} />
                                ) : (
                                  <p className="p-3 text-[11px] text-[var(--muted-text)]">暂无状态详情。</p>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
                <Pagination
                  currentPage={page}
                  totalItems={totalSubscriptions}
                  itemsPerPage={PAGE_SIZE}
                  onPageChange={setPage}
                  language="zh"
                  itemLabel="条订阅"
                  alwaysVisible
                />
              </div>
            ) : (
              <div className="mt-4 rounded-xl border border-dashed border-[var(--card-border)] px-4 py-10 text-center">
                {isLoading ? (
                  <Loader2 size={16} className="mx-auto animate-spin text-[var(--muted-text)]" />
                ) : loadIssues.some((issue) => issue.source === '订阅列表') ? (
                  <XCircle size={18} className="mx-auto text-rose-500" />
                ) : (
                  <CircleDashed size={18} className="mx-auto text-[var(--muted-text)]" />
                )}
                <p className="mt-2 text-xs font-semibold text-[var(--app-text)]">
                  {loadIssues.some((issue) => issue.source === '订阅列表') ? '订阅列表暂不可用' : '暂无匹配的 Telemetry 订阅'}
                </p>
                <p className="mt-1 text-[10px] text-[var(--muted-text)]">
                  点击右上角「新增设备订阅」进入向导页，一键创建并模拟推流验证。
                </p>
              </div>
            )}
          </section>
        </div>
      )}

      {/* SUB-PAGE 3: Built-in Vendor Protocol Profiles & Supported Huawei/H3C Model Catalog (Clean Single-Table List View) */}
      {activeSubPage === 'protocols' && (
        <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
          {/* Single Compact Toolbar: Segmented View Toggle + Search + Vendor Filter */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--card-border)] pb-3.5">
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex rounded-xl border border-[var(--card-border)] bg-black/[0.025] p-1 dark:bg-white/[0.04]">
                <button
                  type="button"
                  onClick={() => setProtocolViewTab('profiles')}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                    protocolViewTab === 'profiles'
                      ? 'bg-[var(--card-bg)] text-[var(--app-text)] shadow-2xs'
                      : 'text-[var(--muted-text)] hover:text-[var(--app-text)]'
                  }`}
                >
                  <ShieldCheck size={14} className="text-cyan-700" />
                  内置协议档列表
                  <span className="rounded-full bg-cyan-500/10 px-1.5 py-0.2 text-[10px] font-extrabold text-cyan-700">
                    {filteredProfiles.length}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => setProtocolViewTab('models')}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition ${
                    protocolViewTab === 'models'
                      ? 'bg-[var(--card-bg)] text-[var(--app-text)] shadow-2xs'
                      : 'text-[var(--muted-text)] hover:text-[var(--app-text)]'
                  }`}
                >
                  <Server size={14} className="text-indigo-600" />
                  支持设备型号名录
                  <span className="rounded-full bg-indigo-500/10 px-1.5 py-0.2 text-[10px] font-extrabold text-indigo-700">
                    {filteredModelRows.length}
                  </span>
                </button>
              </div>

              {protocolViewTab === 'models' && (
                <div className="flex flex-wrap items-center gap-1">
                  {[
                    { key: 'all', label: '全部分类' },
                    { key: '园区接入与汇聚交换机', label: '园区接入/汇聚' },
                    { key: '园区框式核心交换机', label: '园区框式核心' },
                    { key: '数据中心交换机 (Leaf / Spine / Core)', label: '数据中心' },
                    { key: '安全防火墙 / 无线 AC / 路由器', label: '防火墙/无线/路由' },
                  ].map((cat) => {
                    const active =
                      cat.key === 'all'
                        ? modelCategoryFilter === 'all'
                        : modelCategoryFilter.includes(cat.key.slice(0, 4));
                    return (
                      <button
                        key={cat.key}
                        type="button"
                        onClick={() => {
                          setModelCategoryFilter(cat.key === 'all' ? 'all' : cat.key);
                          setModelPage(1);
                        }}
                        className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold transition ${
                          active
                            ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900'
                            : 'text-[var(--muted-text)] hover:bg-black/[0.04] hover:text-[var(--app-text)]'
                        }`}
                      >
                        {cat.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative w-64">
                <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-text)]" />
                <input
                  type="text"
                  value={modelSearch}
                  onChange={(e) => {
                    setModelSearch(e.target.value);
                    setModelPage(1);
                  }}
                  placeholder={
                    protocolViewTab === 'profiles'
                      ? '搜索协议名称或 Sensor Path...'
                      : '搜索型号 (如 S5135S-24P4S-EI / CE6885)...'
                  }
                  className="h-9 w-full rounded-xl border border-[var(--card-border)] bg-[var(--card-bg)] pl-8 pr-8 text-xs text-[var(--app-text)] outline-none transition focus:border-cyan-600"
                />
                {modelSearch && (
                  <button
                    type="button"
                    onClick={() => {
                      setModelSearch('');
                      setModelPage(1);
                    }}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-text)] hover:text-[var(--app-text)]"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              <div className="inline-flex rounded-xl border border-[var(--card-border)] bg-black/[0.02] p-0.5 dark:bg-white/[0.04]">
                {(
                  [
                    { key: 'all', label: '全部' },
                    { key: 'h3c', label: '华三 H3C' },
                    { key: 'huawei', label: '华为 Huawei' },
                  ] as const
                ).map((v) => (
                  <button
                    key={v.key}
                    type="button"
                    onClick={() => {
                      setModelVendorFilter(v.key);
                      setModelPage(1);
                    }}
                    className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold transition ${
                      modelVendorFilter === v.key
                        ? 'bg-cyan-700 text-white'
                        : 'text-[var(--muted-text)] hover:text-[var(--app-text)]'
                    }`}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* VIEW 1: Built-in Protocol Profiles Table (Clean Single-Line Rows) */}
          {protocolViewTab === 'profiles' && (
            <div className="mt-3.5 overflow-x-auto rounded-xl border border-[var(--card-border)]">
              <table className="w-full min-w-[960px] text-left text-xs">
                <thead className="bg-black/[0.02] text-[11px] font-bold text-[var(--muted-text)] dark:bg-white/[0.03]">
                  <tr>
                    <th className="whitespace-nowrap px-3.5 py-2.5">协议档名称</th>
                    <th className="whitespace-nowrap px-3 py-2.5">厂商</th>
                    <th className="whitespace-nowrap px-3 py-2.5">封装协议</th>
                    <th className="whitespace-nowrap px-3 py-2.5">适用机型系列</th>
                    <th className="whitespace-nowrap px-3 py-2.5">软件版本</th>
                    <th className="whitespace-nowrap px-3 py-2.5">默认采集路径 (Sensor Paths)</th>
                    <th className="whitespace-nowrap px-3 py-2.5">状态</th>
                    <th className="whitespace-nowrap px-3.5 py-2.5 text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--card-border)]">
                  {filteredProfiles.map((profile) => {
                    const isHuawei = String(profile.vendor || '').toLowerCase().includes('huawei');
                    const isV3 = String(profile.adapter_key || profile.profile_key).includes('v3');
                    const uniquePaths = Array.from(new Set((profile.paths || []).map((item) => item.path)));
                    const seriesBadges = profileSeriesBadges(profile);
                    const isExpanded = expandedProfileId === profile.id;
                    return (
                      <Fragment key={profile.id}>
                        <tr className="align-middle transition hover:bg-black/[0.015] dark:hover:bg-white/[0.02]">
                          <td className="px-3.5 py-3">
                            <p className="whitespace-nowrap font-bold text-[var(--app-text)]">{profileDisplayName(profile)}</p>
                            <code className="mt-0.5 block whitespace-nowrap font-mono text-[10px] text-[var(--muted-text)]">
                              {profile.profile_key}
                            </code>
                          </td>
                          <td className="whitespace-nowrap px-3 py-3">
                            <span
                              className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold ${
                                isHuawei
                                  ? 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
                                  : 'bg-cyan-500/10 text-cyan-800 dark:text-cyan-300'
                              }`}
                            >
                              {isHuawei ? '华为 Huawei' : '华三 H3C'}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-3 py-3">
                            <span className="inline-flex whitespace-nowrap rounded-md border border-[var(--card-border)] bg-black/[0.02] px-2 py-0.5 font-mono text-[11px] font-semibold text-[var(--app-text)] dark:bg-white/[0.04]">
                              {isHuawei ? 'gRPC JSON (serviceArgs)' : isV3 ? '三层 JSON (v3)' : '二层 JSON (v2)'}
                            </span>
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex flex-wrap items-center gap-1">
                              {seriesBadges.visible.map((s) => (
                                <span
                                  key={s}
                                  className="inline-flex whitespace-nowrap rounded border border-[var(--card-border)] bg-black/[0.015] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[var(--app-text)] dark:bg-white/[0.03]"
                                >
                                  {s}
                                </span>
                              ))}
                              {seriesBadges.extraCount > 0 && (
                                <button
                                  type="button"
                                  onClick={() => setProtocolViewTab('models')}
                                  className="inline-flex whitespace-nowrap rounded bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-bold text-cyan-700 hover:bg-cyan-500/20 dark:text-cyan-300"
                                  title={profile.model_scope}
                                >
                                  +{seriesBadges.extraCount} 系列
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-3 font-mono text-[11px] text-[var(--muted-text)]">
                            {profileFriendlyVersion(profile)}
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex flex-wrap items-center gap-1">
                              {uniquePaths.slice(0, 2).map((p) => (
                                <code
                                  key={p}
                                  className="whitespace-nowrap rounded bg-black/[0.04] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[var(--app-text)] dark:bg-white/[0.06]"
                                >
                                  {p}
                                </code>
                              ))}
                              {uniquePaths.length > 2 && (
                                <span className="whitespace-nowrap rounded bg-black/[0.04] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--muted-text)]">
                                  +{uniquePaths.length - 2} 路径
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-3 py-3">
                            <StatusPill value={profile.support_status} type="support" />
                          </td>
                          <td className="whitespace-nowrap px-3.5 py-3 text-right">
                            <div className="inline-flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => setExpandedProfileId((cur) => (cur === profile.id ? null : profile.id))}
                                className="whitespace-nowrap rounded-lg border border-[var(--card-border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--app-text)] transition hover:bg-black/[0.04]"
                              >
                                {isExpanded ? '收起' : `指标明细 (${(profile.paths || []).length})`}
                              </button>
                              <button
                                type="button"
                                onClick={() => switchSubPage('onboarding')}
                                className="whitespace-nowrap rounded-lg bg-cyan-700 px-2.5 py-1 text-[11px] font-bold text-white transition hover:bg-cyan-800"
                              >
                                去开通
                              </button>
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr>
                            <td colSpan={8} className="bg-black/[0.015] px-4 py-3 dark:bg-white/[0.02]">
                              <div className="space-y-2">
                                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                                  <span className="text-[var(--muted-text)]">
                                    完整支持机型范围：<code className="font-mono text-[var(--app-text)]">{profile.model_scope}</code>
                                  </span>
                                  {profile.official_sources?.[0] && (
                                    <a
                                      href={profile.official_sources[0]}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="font-semibold text-cyan-700 hover:underline"
                                    >
                                      查看厂商官方 Telemetry 配置手册 ↗
                                    </a>
                                  )}
                                </div>
                                <div className="overflow-x-auto rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)]">
                                  <table className="w-full text-left text-[11px]">
                                    <thead className="bg-black/[0.02] text-[10px] font-bold text-[var(--muted-text)]">
                                      <tr>
                                        <th className="px-3 py-1.5">官方传感器路径 (Sensor Path)</th>
                                        <th className="px-3 py-1.5">标准化 Prometheus 指标名</th>
                                        <th className="px-3 py-1.5">状态</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-[var(--card-border)]">
                                      {(profile.paths || []).map((item, idx) => (
                                        <tr key={`${item.path}:${item.metric_key}:${idx}`}>
                                          <td className="px-3 py-1.5 font-mono font-bold text-[var(--app-text)]">{item.path}</td>
                                          <td className="px-3 py-1.5 font-mono text-cyan-800 dark:text-cyan-300">
                                            nexora_telemetry_{item.metric_key}
                                          </td>
                                          <td className="px-3 py-1.5">
                                            <StatusPill value={item.validation_status} type="support" />
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* VIEW 2: Supported Huawei & H3C Device Models Table List */}
          {protocolViewTab === 'models' && (
            <div className="mt-3.5 overflow-x-auto rounded-xl border border-[var(--card-border)]">
              <table className="w-full min-w-[920px] text-left text-xs">
                <thead className="bg-black/[0.02] text-[11px] font-bold text-[var(--muted-text)] dark:bg-white/[0.03]">
                  <tr>
                    <th className="w-12 whitespace-nowrap px-3 py-2.5 text-center">#</th>
                    <th className="whitespace-nowrap px-3 py-2.5">设备具体型号 (SKU)</th>
                    <th className="whitespace-nowrap px-3 py-2.5">厂商</th>
                    <th className="whitespace-nowrap px-3 py-2.5">所属系列</th>
                    <th className="whitespace-nowrap px-3 py-2.5">设备分类</th>
                    <th className="whitespace-nowrap px-3 py-2.5">软件版本要求</th>
                    <th className="whitespace-nowrap px-3 py-2.5">默认匹配协议档</th>
                    <th className="whitespace-nowrap px-3 py-2.5">状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--card-border)]">
                  {pagedModelRows.map((row, idx) => {
                    const rowNum = (safeModelPage - 1) * modelPageSize + idx + 1;
                    return (
                      <tr key={`${row.vendor}:${row.sku}`} className="hover:bg-black/[0.015] dark:hover:bg-white/[0.02]">
                        <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-[11px] text-[var(--muted-text)]">
                          {rowNum}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 font-mono font-extrabold text-[var(--app-text)]">
                          {row.sku}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5">
                          <span
                            className={`inline-flex items-center whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold ${
                              row.vendor === 'huawei'
                                ? 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300'
                                : 'bg-cyan-500/10 text-cyan-800 dark:text-cyan-300'
                            }`}
                          >
                            {row.vendorLabel}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 font-semibold text-[var(--app-text)]">{row.seriesName}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-[var(--muted-text)]">{row.category}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[11px] text-[var(--muted-text)]">{row.osVersion}</td>
                        <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[11px] text-cyan-800 dark:text-cyan-300">
                          {row.defaultProfileKey}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5">
                          <StatusPill value="DOCUMENTED" type="support" label="已内置支持" />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <Pagination
                currentPage={safeModelPage}
                totalItems={filteredModelRows.length}
                itemsPerPage={modelPageSize}
                onItemsPerPageChange={(size) => {
                  setModelPageSize(size);
                  setModelPage(1);
                }}
                onPageChange={setModelPage}
                language="zh"
                itemLabel="款官方核验型号"
                alwaysVisible
              />
            </div>
          )}
        </section>
      )}

      {/* SUB-PAGE 4: Collector Endpoint & Capacity (Table List View) */}
      {activeSubPage === 'capacity' && (
        <div className="space-y-4">
          <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
            <h2 className="flex items-center gap-2 text-sm font-extrabold text-[var(--app-text)]">
              <Server size={16} className="text-cyan-700" />
              gRPC Dial-out 接收器端点与协议解包服务列表
            </h2>
            <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--card-border)]">
              <table className="w-full min-w-[760px] text-left text-[11px]">
                <thead className="bg-black/[0.025] text-[10px] font-bold text-[var(--muted-text)] dark:bg-white/[0.035]">
                  <tr>
                    <th className="px-3 py-2.5">服务模块</th>
                    <th className="px-3 py-2.5">gRPC 服务标识 / 监听端点</th>
                    <th className="px-3 py-2.5">Protobuf 消息帧格式</th>
                    <th className="px-3 py-2.5">安全与认证模式</th>
                    <th className="px-3 py-2.5">运行状态</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--card-border)]">
                  <tr>
                    <td className="px-3 py-2.5 font-bold text-[var(--app-text)]">本地 Telemetry gRPC 接收器</td>
                    <td className="px-3 py-2.5 font-mono font-bold text-cyan-700 dark:text-cyan-300">
                      {collectors[0]?.target_address || '192.168.56.1'}:{collectors[0]?.grpc_port || 10051}
                    </td>
                    <td className="px-3 py-2.5 text-[var(--muted-text)]">HTTP/2 + Protobuf 双向流</td>
                    <td className="px-3 py-2.5 text-[var(--muted-text)]">无 TLS 直连 (no-tls + IP 白名单) / mTLS 双向证书</td>
                    <td className="px-3 py-2.5">
                      <StatusPill value="CONNECTED" type="connection" label="监听就绪" />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-3 py-2.5 font-bold text-[var(--app-text)]">华三 Comware V7 二层 JSON 解包器</td>
                    <td className="px-3 py-2.5 font-mono text-[var(--app-text)]">/grpc_dialout.GRPCDialout/Dialout</td>
                    <td className="px-3 py-2.5 font-mono text-[var(--muted-text)]">DialoutMsg (deviceMsg + sensorPath + jsonData)</td>
                    <td className="px-3 py-2.5 text-[var(--muted-text)]">源 IP 白名单匹配</td>
                    <td className="px-3 py-2.5">
                      <StatusPill value="DOCUMENTED" type="support" label="已启用" />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-3 py-2.5 font-bold text-[var(--app-text)]">华三 Comware V7 三层 JSON 解包器</td>
                    <td className="px-3 py-2.5 font-mono text-[var(--app-text)]">/grpc_dialout_v3.gRPCDialoutV3/DialoutV3</td>
                    <td className="px-3 py-2.5 font-mono text-[var(--muted-text)]">DialoutV3Args / TelemetryPacked (field 16/19/24)</td>
                    <td className="px-3 py-2.5 text-[var(--muted-text)]">源 IP 白名单匹配</td>
                    <td className="px-3 py-2.5">
                      <StatusPill value="DOCUMENTED" type="support" label="已启用" />
                    </td>
                  </tr>
                  <tr>
                    <td className="px-3 py-2.5 font-bold text-[var(--app-text)]">华为 VRP / VRP8 CloudEngine 解包器</td>
                    <td className="px-3 py-2.5 font-mono text-[var(--app-text)]">/huawei_dialout.gRPCDataservice/dataPublish</td>
                    <td className="px-3 py-2.5 font-mono text-[var(--muted-text)]">serviceArgs (ReqId + packed_data_json / data_json)</td>
                    <td className="px-3 py-2.5 text-[var(--muted-text)]">源 IP 白名单匹配 / TLS</td>
                    <td className="px-3 py-2.5">
                      <StatusPill value="DOCUMENTED" type="support" label="已启用" />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 text-sm font-extrabold text-[var(--app-text)]">
                  <Gauge size={16} className="text-amber-600" />
                  采集器容量摘要
                </h2>
                <p className="mt-1 text-[11px] text-[var(--muted-text)]">对比准入上限、已预留和实际观测值。</p>
              </div>
              <label className="flex items-center gap-2 text-[10px] font-semibold text-[var(--muted-text)]">
                采集器
                <select
                  value={selectedCollectorId}
                  onChange={(event) => setSelectedCollectorId(event.target.value)}
                  disabled={!collectorOptions.length}
                  className="max-w-[240px] rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-1.5 text-[11px] text-[var(--app-text)] disabled:opacity-50"
                >
                  {collectorOptions.map((collector) => (
                    <option key={collector.id} value={collector.id}>
                      {collector.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {capacityLoading ? (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-dashed border-[var(--card-border)] px-3 py-7 text-xs text-[var(--muted-text)]">
                <Loader2 size={14} className="animate-spin" />
                正在加载容量摘要…
              </div>
            ) : capacityIssue ? (
              <div
                role="alert"
                className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-3 text-xs ${
                  capacityIssue.forbidden ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-amber-200 bg-amber-50 text-amber-800'
                }`}
              >
                {capacityIssue.forbidden ? <ShieldAlert size={14} className="mt-0.5 shrink-0" /> : <AlertTriangle size={14} className="mt-0.5 shrink-0" />}
                {capacityIssue.message}
              </div>
            ) : capacity ? (
              <CapacityTable capacity={capacity} />
            ) : (
              <div className="mt-3 rounded-xl border border-dashed border-[var(--card-border)] px-4 py-8 text-center">
                {collectorOptions.length ? <Database size={18} className="mx-auto text-[var(--muted-text)]" /> : <Server size={18} className="mx-auto text-[var(--muted-text)]" />}
                <p className="mt-2 text-xs font-semibold text-[var(--app-text)]">
                  {collectorOptions.length ? '暂无容量摘要' : '当前订阅页没有关联采集器'}
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
};

export default TelemetryManagementPage;
