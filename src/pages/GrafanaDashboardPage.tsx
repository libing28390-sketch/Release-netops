import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  BarChart2,
  Clock,
  ExternalLink,
  Eye,
  Layers,
  Maximize2,
  Minimize2,
  Monitor,
  RefreshCw,
  Server,
  ShieldCheck,
  Tv,
  Wifi,
  Globe,
  HardDrive,
  FileSpreadsheet,
} from 'lucide-react';
import PageHero from '../components/PageHero';
import ExportTableModal from '../components/ExportTableModal';

interface GrafanaDashboardPageProps {
  language: 'zh' | 'en';
}

type GrafanaStatus = 'checking' | 'ready' | 'unavailable';
type ViewMode = 'kiosk' | 'tv' | 'full';

export const GRAFANA_DASHBOARDS = [
  {
    uid: 'nexora-network-overview',
    titleZh: '01 网络总览',
    titleEn: '01 Network Overview',
    descZh: '全网全局 KPI、有线/无线流量与负荷概况',
    descEn: 'Global KPIs, wired/wireless traffic and load overview',
    icon: BarChart2,
  },
  {
    uid: 'nexora-network-device',
    titleZh: '02 设备详情',
    titleEn: '02 Device Detail',
    descZh: '单机多核 CPU、内存池、板卡温度与风扇电源',
    descEn: 'Multi-core CPU, memory pools, board temps and hardware health',
    icon: Server,
  },
  {
    uid: 'nexora-network-wireless',
    titleZh: '03 无线专网',
    titleEn: '03 Wireless AP & Clients',
    descZh: '全网 AC/AP 控制器、AP 在线/离线、无线客户端分布与高密排行',
    descEn: 'AC/AP controllers, AP online/offline status, wireless clients and density ranking',
    icon: Wifi,
  },
  {
    uid: 'nexora-network-interface',
    titleZh: '04 接口流量',
    titleEn: '04 Interface Traffic',
    descZh: '端口带宽利用率、速率走势、丢包与 CRC 错包诊断',
    descEn: 'Bandwidth utilization %, rates, discards and CRC diagnostics',
    icon: Activity,
  },
  {
    uid: 'nexora-monitoring-health',
    titleZh: '05 采集健康',
    titleEn: '05 Scrape Health',
    descZh: 'vmagent 探针在线率、SNMP Scrape 耗时分布与慢采集排行',
    descEn: 'vmagent probe up status, scrape durations and slowest targets ranking',
    icon: Layers,
  },
  {
    uid: 'nexora-network-outbound',
    titleZh: '06 互联网出口',
    titleEn: '06 Internet Outbound & WAN',
    descZh: '边界网关出入向实时带宽、利用率走势与出口链路丢包诊断',
    descEn: 'Gateway in/out bandwidth, utilization trends and WAN discards diagnostics',
    icon: Globe,
  },
  {
    uid: 'nexora-linux-metrics',
    titleZh: '07 Linux 服务器',
    titleEn: '07 Linux Server',
    descZh: 'Linux CPU、负载、物理内存/Swap、磁盘空间与 IOPS、网络流量与 TCP 连接',
    descEn: 'Linux CPU, Load, Memory/Swap, disk space & IOPS, network traffic & TCP sockets',
    icon: HardDrive,
  },
  {
    uid: 'nexora-windows-metrics',
    titleZh: '08 Windows 主机',
    titleEn: '08 Windows Host',
    descZh: 'Windows CPU、物理内存、逻辑磁盘读写延迟、网络适配器与远程桌面会话',
    descEn: 'Windows CPU, physical memory, logical disk latency, NIC throughput & RDP sessions',
    icon: Monitor,
  },
];

const TIME_RANGES = [
  { value: '15m', labelZh: '最近 15 分钟', labelEn: 'Last 15m' },
  { value: '1h', labelZh: '最近 1 小时', labelEn: 'Last 1h' },
  { value: '6h', labelZh: '最近 6 小时', labelEn: 'Last 6h' },
  { value: '24h', labelZh: '最近 24 小时', labelEn: 'Last 24h' },
  { value: '7d', labelZh: '最近 7 天', labelEn: 'Last 7d' },
];

const REFRESH_RATES = [
  { value: 'off', labelZh: '关闭自动刷新', labelEn: 'Off' },
  { value: '10s', labelZh: '10 秒', labelEn: '10s' },
  { value: '30s', labelZh: '30 秒', labelEn: '30s' },
  { value: '1m', labelZh: '1 分钟', labelEn: '1m' },
  { value: '5m', labelZh: '5 分钟', labelEn: '5m' },
];

function resolveSystemTheme(): 'light' | 'dark' {
  const dataTheme = document.documentElement.getAttribute('data-theme');
  if (dataTheme === 'dark' || dataTheme === 'light') return dataTheme;
  const saved = localStorage.getItem('netops_theme_mode');
  if (saved === 'dark' || saved === 'light') return saved;
  if (document.documentElement.classList.contains('dark')) return 'dark';
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

const GrafanaDashboardPage: React.FC<GrafanaDashboardPageProps> = ({ language }) => {
  const zh = language === 'zh';
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);

  const [selectedDashboard, setSelectedDashboard] = useState(GRAFANA_DASHBOARDS[0].uid);
  const [frameKey, setFrameKey] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState<GrafanaStatus>('checking');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => resolveSystemTheme());
  const [viewMode, setViewMode] = useState<ViewMode>('kiosk');
  const [timeRange, setTimeRange] = useState('6h');
  const [refreshRate, setRefreshRate] = useState('30s');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isExportModalOpen, setIsExportModalOpen] = useState(false);

  // Sync theme with Nexora's top-level data-theme attribute
  useEffect(() => {
    const observer = new MutationObserver(() => {
      const current = resolveSystemTheme();
      setTheme(prev => (prev !== current ? current : prev));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme', 'class'],
    });
    return () => observer.disconnect();
  }, []);

  // Fullscreen change listener
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const toggleFullscreen = async () => {
    if (!containerRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await containerRef.current.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch {
      // Ignore fullscreen API denial
    }
  };

  const checkGrafana = useCallback(async () => {
    setStatus('checking');
    setLoaded(false);
    try {
      const token = localStorage.getItem('netops_token');
      if (!token) throw new Error('Nexora session is missing');
      const bridgeResponse = await fetch('/api/grafana/session', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!bridgeResponse.ok) throw new Error('Grafana session bridge failed');

      const response = await fetch('/grafana/api/health?_=' + Date.now(), {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const contentType = response.headers.get('content-type') || '';
      const payload = (await response.json().catch(() => null)) as {
        database?: string;
        version?: string;
      } | null;
      if (
        !response.ok ||
        !contentType.toLowerCase().includes('json') ||
        !payload ||
        (payload.database !== 'ok' && !payload.version)
      ) {
        throw new Error('Grafana health check failed');
      }
      setStatus('ready');
      setFrameKey(value => value + 1);
    } catch {
      setStatus('unavailable');
    }
  }, []);

  useEffect(() => {
    void checkGrafana();
  }, [checkGrafana]);

  // Construct iframe URL dynamically
  const dashboardUrl = useMemo(() => {
    const params = new URLSearchParams();
    params.set('orgId', '1');
    if (refreshRate !== 'off') {
      params.set('refresh', refreshRate);
    }
    if (timeRange) {
      params.set('from', `now-${timeRange}`);
      params.set('to', 'now');
    }
    params.set('theme', theme);

    let url = `/grafana/d/${selectedDashboard}/${selectedDashboard}?${params.toString()}`;
    if (viewMode === 'kiosk') {
      // Pure kiosk: completely removes sidebar and top navbar
      url += '&kiosk';
    } else if (viewMode === 'tv') {
      // TV kiosk: keeps top controls while suppressing left sidebar
      url += '&kiosk=tv';
    }
    return url;
  }, [selectedDashboard, theme, viewMode, timeRange, refreshRate]);

  const statusText =
    status === 'checking'
      ? zh
        ? '正在检查 Grafana 服务…'
        : 'Checking Grafana…'
      : status === 'ready'
        ? zh
          ? 'Grafana 已连接'
          : 'Grafana connected'
        : zh
          ? 'Grafana 尚未部署或当前不可用'
          : 'Grafana is not deployed or unavailable';

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50 dark:bg-zinc-950">
      <PageHero
        icon={BarChart2}
        title={zh ? '监控大盘' : 'Monitoring dashboards'}
        subtitle={
          zh
            ? 'Grafana 全局趋势、设备详情、无线专网与采集健康视图（纯净内嵌模式）'
            : 'Grafana global trends, device details, wireless AP/clients and telemetry health'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {selectedDashboard.includes('outbound') && (
              <button
                type="button"
                onClick={() => navigate('/monitor/outbound')}
                className="inline-flex items-center gap-1.5 rounded-xl border border-blue-200 dark:border-blue-900/60 bg-blue-50 dark:bg-blue-950/40 px-3 py-2 text-xs font-semibold text-blue-700 dark:text-blue-300 shadow-sm hover:bg-blue-100 dark:hover:bg-blue-900/50 cursor-pointer transition-colors"
                title={zh ? '配置与管理出口探针、目标与期望公网 IP' : 'Manage outbound probes and target overrides'}
              >
                <Globe size={14} className="text-blue-600 dark:text-blue-400" />
                <span>{zh ? '探针配置管理' : 'Probes Config'}</span>
              </button>
            )}
            {(selectedDashboard.includes('linux') || selectedDashboard.includes('windows') || selectedDashboard.includes('server')) && (
              <button
                type="button"
                onClick={() => navigate('/monitor/servers')}
                className="inline-flex items-center gap-1.5 rounded-xl border border-purple-200 dark:border-purple-900/60 bg-purple-50 dark:bg-purple-950/40 px-3 py-2 text-xs font-semibold text-purple-700 dark:text-purple-300 shadow-sm hover:bg-purple-100 dark:hover:bg-purple-900/50 cursor-pointer transition-colors"
                title={zh ? '查看服务器本地进程清单、磁盘明细与网络连接' : 'View server processes and disk status'}
              >
                <HardDrive size={14} className="text-purple-600 dark:text-purple-400" />
                <span>{zh ? '进程与系统明细' : 'Processes Detail'}</span>
              </button>
            )}
            {selectedDashboard.includes('health') && (
              <button
                type="button"
                onClick={() => navigate('/monitor/collection-health')}
                className="inline-flex items-center gap-1.5 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-xs font-semibold text-amber-700 dark:text-amber-300 shadow-sm hover:bg-amber-100 dark:hover:bg-amber-900/50 cursor-pointer transition-colors"
                title={zh ? '查看采集计划健康诊断与超时测试' : 'Collection diagnostics and tests'}
              >
                <Activity size={14} className="text-amber-600 dark:text-amber-400" />
                <span>{zh ? '采集调度与诊断' : 'Collection Diagnostics'}</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => setIsExportModalOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-600/30 bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-xs font-bold text-emerald-700 dark:text-emerald-300 shadow-sm hover:bg-emerald-100 dark:hover:bg-emerald-900/50 cursor-pointer transition-colors"
              title={zh ? '导出包含多工作表的专业 Excel / CSV 报表' : 'Export multi-sheet Excel / CSV reports'}
            >
              <FileSpreadsheet size={14} className="text-emerald-600 dark:text-emerald-400" />
              <span>{zh ? '导出监控报表 (Excel/CSV)' : 'Export Reports'}</span>
            </button>
            <button
              type="button"
              onClick={() => void checkGrafana()}
              disabled={status === 'checking'}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-semibold text-slate-700 dark:text-zinc-200 shadow-sm hover:border-cyan-300 disabled:cursor-wait disabled:opacity-60 cursor-pointer"
            >
              <RefreshCw size={14} className={status === 'checking' ? 'animate-spin' : ''} />
              {zh ? '检查并刷新' : 'Check & refresh'}
            </button>
            {status === 'ready' && (
              <a
                href={`/grafana/d/${selectedDashboard}/${selectedDashboard}?orgId=1`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-bold text-white shadow-sm hover:bg-cyan-700 cursor-pointer"
              >
                <ExternalLink size={14} />
                {zh ? '在新窗口打开' : 'Open in New Tab'}
              </a>
            )}
          </div>
        }
      />

      <div className="flex min-h-0 flex-1 flex-col p-2 md:p-3">
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {/* Dashboard Switcher Tabs */}
          {status === 'ready' && (
            <div className="flex flex-wrap items-center gap-1 rounded-xl border border-slate-200/80 dark:border-zinc-800/80 bg-white/95 dark:bg-zinc-900/95 p-1 shadow-2xs backdrop-blur">
              {GRAFANA_DASHBOARDS.map(db => {
                const Icon = db.icon;
                const isSelected = selectedDashboard === db.uid;
                return (
                  <button
                    key={db.uid}
                    type="button"
                    onClick={() => {
                      if (selectedDashboard !== db.uid) {
                        setSelectedDashboard(db.uid);
                        setLoaded(false);
                      }
                    }}
                    className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-semibold transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-cyan-50 dark:bg-cyan-950/50 text-cyan-700 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800/60 shadow-2xs'
                        : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 hover:bg-slate-100/70 dark:hover:bg-zinc-800/60 border border-transparent'
                    }`}
                    title={zh ? db.descZh : db.descEn}
                  >
                    <Icon size={14} className={isSelected ? 'text-cyan-600 dark:text-cyan-400' : 'text-slate-400 dark:text-zinc-500'} />
                    <span>{zh ? db.titleZh : db.titleEn}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Top Control & Status Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200/80 dark:border-zinc-800/80 bg-white/95 dark:bg-zinc-900/95 px-3 py-2 shadow-2xs backdrop-blur">
            <div className="flex flex-wrap items-center gap-2">
              <div
                className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium ${
                  status === 'ready'
                    ? 'border border-emerald-200/60 bg-emerald-50 dark:border-emerald-950/60 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300'
                    : 'border border-amber-200/60 bg-amber-50 dark:border-amber-950/60 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300'
                }`}
              >
                <ShieldCheck
                  size={14}
                  className={status === 'ready' ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}
                />
                <span>{statusText}</span>
              </div>

              {status === 'ready' && (
                <>
                  <div className="h-4 w-px bg-slate-200 dark:bg-zinc-800" />

                  {/* View Mode Switcher */}
                  <div className="flex items-center rounded-lg border border-slate-200 dark:border-zinc-800 bg-slate-100/80 dark:bg-zinc-800/60 p-0.5 text-[11px]">
                    <button
                      type="button"
                      onClick={() => setViewMode('kiosk')}
                      className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-semibold transition-all ${
                        viewMode === 'kiosk'
                          ? 'bg-white dark:bg-zinc-700 text-cyan-700 dark:text-cyan-300 shadow-2xs'
                          : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100'
                      }`}
                      title={zh ? '彻底隐藏 Grafana 侧边栏与顶栏，纯净融入' : 'Pure kiosk without sidebars or top header'}
                    >
                      <Eye size={12} />
                      {zh ? '纯净大盘' : 'Clean Kiosk'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewMode('tv')}
                      className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-semibold transition-all ${
                        viewMode === 'tv'
                          ? 'bg-white dark:bg-zinc-700 text-cyan-700 dark:text-cyan-300 shadow-2xs'
                          : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100'
                      }`}
                      title={zh ? '保留 Grafana 顶部时间与状态栏' : 'TV mode with topbar'}
                    >
                      <Tv size={12} />
                      {zh ? '电视模式' : 'TV Mode'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setViewMode('full')}
                      className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 font-semibold transition-all ${
                        viewMode === 'full'
                          ? 'bg-white dark:bg-zinc-700 text-cyan-700 dark:text-cyan-300 shadow-2xs'
                          : 'text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100'
                      }`}
                      title={zh ? '显示完整 Grafana 菜单与编辑控制' : 'Full Grafana controls'}
                    >
                      <Monitor size={12} />
                      {zh ? '完整管理' : 'Full Admin'}
                    </button>
                  </div>
                </>
              )}
            </div>

            {status === 'ready' && (
              <div className="flex flex-wrap items-center gap-1.5">
                {/* Time Range Selector */}
                <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-zinc-400">
                  <Clock size={13} />
                  <select
                    value={timeRange}
                    onChange={e => setTimeRange(e.target.value)}
                    className="rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1 text-[11px] font-semibold text-slate-700 dark:text-zinc-200 outline-none hover:border-cyan-300 cursor-pointer"
                  >
                    {TIME_RANGES.map(item => (
                      <option key={item.value} value={item.value}>
                        {zh ? item.labelZh : item.labelEn}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Refresh Rate Selector */}
                <select
                  value={refreshRate}
                  onChange={e => setRefreshRate(e.target.value)}
                  className="rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2 py-1 text-[11px] font-semibold text-slate-700 dark:text-zinc-200 outline-none hover:border-cyan-300 cursor-pointer"
                >
                  {REFRESH_RATES.map(item => (
                    <option key={item.value} value={item.value}>
                      {zh ? `刷新: ${item.labelZh}` : `Refresh: ${item.labelEn}`}
                    </option>
                  ))}
                </select>

                {/* Fullscreen Button */}
                <button
                  type="button"
                  onClick={() => void toggleFullscreen()}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-slate-700 dark:text-zinc-200 shadow-2xs hover:border-cyan-300 cursor-pointer"
                  title={zh ? '沉浸式全屏展示' : 'Toggle Fullscreen'}
                >
                  {isFullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                  <span>{isFullscreen ? (zh ? '退出全屏' : 'Exit') : zh ? '全屏大盘' : 'Fullscreen'}</span>
                </button>
              </div>
            )}
          </div>

          {/* Embedded Grafana iframe Container */}
          {status === 'ready' && (
            <div
              ref={containerRef}
              className="relative flex flex-1 min-h-[560px] md:min-h-[calc(100vh-260px)] overflow-hidden rounded-xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm"
            >
              <iframe
                key={`${frameKey}-${theme}-${viewMode}`}
                title={zh ? 'Grafana 监控大盘' : 'Grafana monitoring dashboard'}
                src={dashboardUrl}
                onLoad={() => setLoaded(true)}
                className="h-full w-full flex-1 border-0"
                allow="fullscreen"
              />
              {!loaded && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-white/85 dark:bg-zinc-900/85 text-sm text-slate-500 dark:text-zinc-400 backdrop-blur-xs">
                  <RefreshCw size={16} className="mr-2 animate-spin text-cyan-600" />
                  {zh ? '正在加载 Grafana 纯净大盘…' : 'Loading Grafana dashboard…'}
                </div>
              )}
            </div>
          )}

          {status !== 'ready' && (
            <section className="flex min-h-[420px] flex-1 items-center justify-center rounded-2xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm">
              <div className="max-w-xl text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 dark:bg-zinc-800 text-slate-500 dark:text-zinc-400">
                  <BarChart2 size={27} />
                </div>
                <h2 className="mt-4 text-lg font-bold text-slate-900 dark:text-zinc-100">
                  {status === 'checking'
                    ? zh
                      ? '正在连接 Grafana'
                      : 'Connecting to Grafana'
                    : zh
                      ? 'Grafana 大盘暂不可用'
                      : 'Grafana dashboard unavailable'}
                </h2>
                <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-zinc-400">
                  {status === 'checking'
                    ? zh
                      ? '正在确认反向代理返回的是 Grafana 服务，而不是 Nexora 的 SPA 页面。'
                      : 'Verifying that the proxy returns Grafana rather than the Nexora SPA fallback.'
                    : zh
                      ? '当前页面不会嵌套错误的 Nexora 页面。部署并启动 Grafana 后点击“检查并刷新”即可加载大盘。'
                      : 'The page will not embed the Nexora SPA fallback. Deploy Grafana, then click “Check & refresh”.'}
                </p>
                {status === 'unavailable' && (
                  <div className="mt-4 rounded-xl border border-slate-200 dark:border-zinc-800 bg-slate-50 dark:bg-zinc-800/50 p-3 text-left text-xs leading-5 text-slate-600 dark:text-zinc-300">
                    <p className="font-semibold text-slate-800 dark:text-zinc-100">
                      {zh ? '部署提示' : 'Deployment note'}
                    </p>
                    <p className="mt-1">
                      {zh
                        ? 'Docker Compose 需要同时运行 grafana、victoriametrics 和 nginx；Grafana 数据源会自动指向 VictoriaMetrics。'
                        : 'Docker Compose should run grafana, victoriametrics, and nginx together; the datasource points to VictoriaMetrics automatically.'}
                    </p>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => void checkGrafana()}
                  disabled={status === 'checking'}
                  className="mt-5 inline-flex items-center gap-2 rounded-xl bg-cyan-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-cyan-700 disabled:opacity-60"
                >
                  <RefreshCw size={14} className={status === 'checking' ? 'animate-spin' : ''} />
                  {zh ? '重新检查' : 'Check again'}
                </button>
              </div>
            </section>
          )}
        </div>
      </div>

      <ExportTableModal
        isOpen={isExportModalOpen}
        onClose={() => setIsExportModalOpen(false)}
        language={language}
        currentDashboardUid={selectedDashboard}
      />
    </div>
  );
};

export default GrafanaDashboardPage;
