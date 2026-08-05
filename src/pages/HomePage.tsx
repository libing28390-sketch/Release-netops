/**
 * HomePage — Nexora Console Dashboard
 *
 * Layout (top → bottom):
 *   1. Title + inline summary metrics
 *   2. Icon grid (5 cols) — module quick-nav
 *   3. Stat blocks (4 cols) — key numbers with visual weight
 *   4. Two-column: Recent Activity (left) + Quick Actions (right)
 */
import React, { useMemo } from 'react';
import { motion } from 'motion/react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart2,
  Bell,
  CheckCircle2,
  ClipboardList,
  Clock,
  Cpu,
  FileCode2,
  HardDrive,
  MemoryStick,
  Plus,
  Play,
  Server,
  SlidersHorizontal,
  Wifi,
  Zap,
  Globe,
  Database,
} from 'lucide-react';
import type { Device, Job, NotificationItem, HostResourceSnapshot } from '../types';

/* ─────────────── Types ─────────────── */

interface HomePageProps {
  language: string;
  navigate: (path: string) => void;
  userRole?: string;
  devices: Device[];
  jobs: Job[];
  notifications: NotificationItem[];
  hostResources: HostResourceSnapshot | null;
  userCount: number;
}

interface AppEntry {
  id: string;
  label: string;
  labelEn: string;
  desc: string;
  descEn: string;
  icon: React.ElementType;
  path: string;
  accent: string;
}

/* ─────────────── App definitions ─────────────── */

const apps: AppEntry[] = [
  { id: 'access',     label: '操作工作台', labelEn: 'Operation Workspace', desc: '终端接入与登录',     descEn: 'Terminal access',      icon: Activity,          path: '/access/workspace',    accent: '#13c2c2' },
  { id: 'monitor',    label: '实时监控',   labelEn: 'Monitoring',   desc: '设备状态与流量',     descEn: 'Status & traffic',     icon: Activity,          path: '/monitor/overview',   accent: '#1677ff' },
  { id: 'alerts',     label: '告警管理',   labelEn: 'Alerts',       desc: '告警查看与处置',     descEn: 'View & handle alerts', icon: Bell,              path: '/alerts/desk',        accent: '#fa8c16' },
  { id: 'assets',     label: '资产与配置', labelEn: 'Assets',       desc: '设备台账与资产',     descEn: 'Inventory & assets',   icon: Server,            path: '/assets/dashboard',   accent: '#1677ff' },
  { id: 'ipam',       label: 'IPAM地址管理', labelEn: 'IPAM',       desc: '网段前缀与IP分配',    descEn: 'IPAM & prefixes',      icon: Globe,             path: '/ipam/locate',        accent: '#06b6d4' },
  { id: 'cmdb',       label: 'CMDB基础数据', labelEn: 'CMDB Core',  desc: '凭据、站点、VLAN与租户', descEn: 'CMDB Core records',    icon: Database,          path: '/cmdb/credentials',   accent: '#6366f1' },
  { id: 'config',     label: '配置管理',   labelEn: 'Config',       desc: '备份、差异与合规',   descEn: 'Backup & compliance',  icon: FileCode2,         path: '/config/backup',      accent: '#722ed1' },
  { id: 'automation', label: '自动化',     labelEn: 'Automation',   desc: '作业执行与编排',     descEn: 'Jobs & orchestration', icon: Zap,               path: '/automation/tasks',   accent: '#0891b2' },
  { id: 'tickets',    label: '工单管理',   labelEn: 'Tickets',      desc: '变更审批与跟踪',     descEn: 'Change & approval',    icon: ClipboardList,     path: '/change-orders/all',  accent: '#1677ff' },
  { id: 'capacity',   label: '容量与报表', labelEn: 'Reports',      desc: '趋势分析与报表',     descEn: 'Trends & reports',     icon: BarChart2,         path: '/capacity/analysis',  accent: '#13c2c2' },
  { id: 'platform',   label: '平台管理',   labelEn: 'Platform',     desc: '用户、审计与系统',   descEn: 'Users, audit & system', icon: SlidersHorizontal, path: '/management/audit',   accent: '#8c8c8c' },
];

/* ─────────────── Helpers ─────────────── */

function timeAgo(ts: string, zh: boolean): string {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return zh ? '刚刚' : 'just now';
  if (mins < 60) return zh ? `${mins} 分钟前` : `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return zh ? `${hrs} 小时前` : `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return zh ? `${days} 天前` : `${days}d ago`;
}

/* ─────────────── Main Component ─────────────── */

const HomePage: React.FC<HomePageProps> = ({
  language,
  navigate,
  devices,
  jobs,
  notifications,
  hostResources,
  userCount,
}) => {
  const zh = language === 'zh';

  const stats = useMemo(() => {
    const online = devices.filter(d => d.status === 'online').length;
    const offline = devices.filter(d => d.status === 'offline').length;
    const pending = devices.filter(d => d.status === 'pending').length;
    const now = Date.now();
    const todayJobs = jobs.filter(j => new Date(j.created_at).getTime() > now - 86400000);
    const successJobs = todayJobs.filter(j => j.status === 'success').length;
    const failedJobs = todayJobs.filter(j => j.status === 'failed').length;
    const runningJobs = todayJobs.filter(j => j.status === 'running').length;
    const pendingJobs = todayJobs.filter(j => j.status === 'pending').length;
    const successRate = todayJobs.length > 0 ? Math.round((successJobs / todayJobs.length) * 100) : 100;
    const critical = notifications.filter(n => !n.read && (n.severity === 'critical' || n.severity === 'high')).length;

    // Platform distribution
    const platformMap: Record<string, number> = {};
    devices.forEach(d => {
      const key = d.platform || (zh ? '未知' : 'Unknown');
      platformMap[key] = (platformMap[key] || 0) + 1;
    });
    const platforms = Object.entries(platformMap)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);

    return {
      total: devices.length, online, offline, pending,
      onlineRate: devices.length > 0 ? Math.round((online / devices.length) * 100) : 0,
      cpuPercent: hostResources?.cpu_percent ?? null,
      memPercent: hostResources?.memory_percent ?? null,
      diskPercent: hostResources?.disk_percent ?? null,
      memUsedGb: hostResources?.memory_used_gb ?? null,
      memTotalGb: hostResources?.memory_total_gb ?? null,
      diskUsedGb: hostResources?.disk_used_gb ?? null,
      diskTotalGb: hostResources?.disk_total_gb ?? null,
      uptimeHours: hostResources?.uptime_hours ?? null,
      dbStatus: hostResources?.database_status ?? null,
      dbOk: hostResources?.database_ok ?? null,
      hostname: hostResources?.hostname ?? null,
      critical, successRate, userCount,
      todayJobs: todayJobs.length,
      successJobs, failedJobs, runningJobs, pendingJobs,
      platforms,
    };
  }, [devices, jobs, notifications, hostResources, userCount, zh]);

  /* ── Stat blocks data ── */
  const statBlocks = [
    { label: zh ? '在线率' : 'Online Rate',   value: `${stats.onlineRate}%`, sub: `${stats.online} / ${stats.total}`, icon: Wifi,          accent: '#1677ff' },
    { label: zh ? '严重告警' : 'Critical',     value: String(stats.critical), sub: zh ? '未处理' : 'unresolved',       icon: AlertTriangle, accent: stats.critical > 0 ? '#f5222d' : '#52c41a' },
    { label: zh ? '自动化成功率' : 'Success',   value: `${stats.successRate}%`, sub: zh ? `今日 ${stats.todayJobs} 任务` : `${stats.todayJobs} jobs today`, icon: CheckCircle2, accent: '#52c41a' },
    { label: zh ? 'CPU 使用率' : 'CPU Usage',  value: stats.cpuPercent !== null ? `${stats.cpuPercent}%` : '—', sub: zh ? '主机资源' : 'host resource', icon: Cpu, accent: '#722ed1' },
  ];

  /* ── Recent events: merge alerts + jobs, sort by time, take 5 ── */
  const recentEvents = useMemo(() => {
    const alertItems = notifications.slice(0, 10).map(n => ({
      id: n.id,
      type: 'alert' as const,
      title: n.title || (zh ? '告警' : 'Alert'),
      severity: n.severity,
      time: n.time,
      read: n.read,
    }));
    const jobItems = jobs.slice(0, 10).map(j => ({
      id: j.id,
      type: 'job' as const,
      title: `${j.task_name}`,
      severity: j.status === 'failed' ? 'high' : j.status === 'success' ? 'low' : ('medium' as string),
      time: j.created_at,
      read: j.status === 'success',
    }));
    return [...alertItems, ...jobItems]
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
      .slice(0, 5);
  }, [notifications, jobs, zh]);

  /* ── Quick actions ── */
  const quickActions = [
    { label: zh ? '添加设备' : 'Add Device',       icon: Plus, path: '/assets',             accent: '#1677ff' },
    { label: zh ? '执行备份' : 'Run Backup',        icon: Play, path: '/config/backup',      accent: '#722ed1' },
    { label: zh ? '创建工单' : 'New Ticket',        icon: ClipboardList, path: '/change-orders', accent: '#fa8c16' },
    { label: zh ? '设备巡检' : 'Inspection',        icon: Activity, path: '/automation/inspections', accent: '#0891b2' },
  ];

  const severityDot: Record<string, string> = { critical: '#f5222d', high: '#fa541c', medium: '#fa8c16', low: '#52c41a' };

  return (
    <div
      className="select-none h-full"
      style={{ background: 'var(--app-bg)' }}
    >
      <div className="max-w-[960px] xl:max-w-[1200px] 2xl:max-w-[1440px] w-full mx-auto px-5 sm:px-8 py-6">

        {/* ════════ 1. Greeting / status summary ════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex flex-wrap items-end justify-between gap-3"
        >
          <div>
            <h1 className="text-2xl font-semibold tracking-tight" style={{ color: 'var(--heading-text)' }}>
              {zh ? '你好，欢迎回来' : 'Welcome back'}
            </h1>
            <p className="text-[13px] mt-1" style={{ color: 'var(--muted-text)' }}>
              {zh
                ? `今日网络 · ${stats.total} 台设备 · ${stats.online} 台在线 · ${stats.critical} 条严重告警`
                : `Today · ${stats.total} devices · ${stats.online} online · ${stats.critical} critical alerts`}
            </p>
          </div>
          <div className="flex items-center gap-2 text-[11px]" style={{ color: 'var(--dim-text)' }}>
            {stats.hostname && (
              <span className="px-2.5 py-1 rounded-full" style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}>
                {stats.hostname}
              </span>
            )}
            {stats.dbStatus && (
              <span
                className="px-2.5 py-1 rounded-full font-medium"
                style={{
                  background: stats.dbOk ? 'rgba(82,196,26,0.12)' : 'rgba(245,34,45,0.12)',
                  color: stats.dbOk ? '#52c41a' : '#f5222d',
                }}
              >
                DB · {stats.dbStatus}
              </span>
            )}
          </div>
        </motion.div>

        {/* ════════ 2. Module Grid — 4 cols card nav ════════ */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.04 }}
          className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3"
        >
          {apps.map((app, idx) => {
            const Icon = app.icon;
            return (
              <motion.button
                key={app.id}
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.2, delay: 0.06 + 0.025 * idx }}
                onClick={() => navigate(app.path)}
                className="group flex items-center gap-3 rounded-xl px-3.5 py-3 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30 transition-all duration-150 text-left"
                style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: '12px', boxShadow: '0 4px 16px rgba(0,0,0,0.04)' }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = app.accent + '60'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--card-border)'; }}
              >
                <div
                  className="flex items-center justify-center w-10 h-10 rounded-lg flex-shrink-0 transition-transform duration-150 group-hover:scale-105"
                  style={{ background: `${app.accent}14` }}
                >
                  <Icon size={20} strokeWidth={1.6} style={{ color: app.accent }} />
                </div>
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold leading-tight" style={{ color: 'var(--heading-text)' }}>
                    {zh ? app.label : app.labelEn}
                  </div>
                  <div className="text-[11px] mt-0.5 truncate" style={{ color: 'var(--muted-text)' }}>
                    {zh ? app.desc : app.descEn}
                  </div>
                </div>
              </motion.button>
            );
          })}
        </motion.div>

        {/* ════════ 3. Stat Blocks — 4 cols ════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.12 }}
          className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3"
        >
          {statBlocks.map((s, i) => {
            const Icon = s.icon;
            return (
              <div
                key={i}
                className="relative rounded-xl px-4 py-4 overflow-hidden"
                style={{
                  background: 'var(--card-bg)',
                  border: '1px solid var(--card-border)',
                  boxShadow: '0 4px 16px rgba(0, 0, 0, 0.04)',
                }}
              >
                {/* Accent left bar */}
                <span
                  aria-hidden
                  className="absolute left-0 top-3 bottom-3 w-[3px] rounded-r"
                  style={{ background: s.accent }}
                />
                <div className="flex items-start justify-between gap-3 pl-2">
                  <div className="min-w-0">
                    <div className="text-[11px] font-medium uppercase tracking-wider" style={{ color: 'var(--muted-text)' }}>
                      {s.label}
                    </div>
                    <div
                      className="text-[26px] font-bold tabular-nums leading-none mt-1.5"
                      style={{ color: s.accent }}
                    >
                      {s.value}
                    </div>
                    <div className="text-[11px] mt-1.5" style={{ color: 'var(--dim-text)' }}>
                      {s.sub}
                    </div>
                  </div>
                  <div
                    className="flex items-center justify-center w-9 h-9 rounded-lg flex-shrink-0"
                    style={{ background: `${s.accent}1a` }}
                  >
                    <Icon size={18} strokeWidth={1.7} style={{ color: s.accent }} />
                  </div>
                </div>
              </div>
            );
          })}
        </motion.div>

        {/* ════════ 4. Two-column: Recent Activity + Quick Actions ════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.18 }}
          className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4"
        >
          {/* ── Left: Recent Activity (2/3) ── */}
          <div
            className="md:col-span-2 rounded-xl px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 4px 16px rgba(0, 0, 0, 0.04)' }}
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-[13px] font-semibold" style={{ color: 'var(--heading-text)' }}>
                {zh ? '最近动态' : 'Recent Activity'}
              </span>
              <button
                onClick={() => navigate('/alerts')}
                className="text-[11px] flex items-center gap-0.5 cursor-pointer"
                style={{ color: 'var(--muted-text)' }}
              >
                {zh ? '查看全部' : 'View all'} <ArrowRight size={11} />
              </button>
            </div>

            {recentEvents.length === 0 ? (
              <div className="text-[12px] py-6 text-center" style={{ color: 'var(--dim-text)' }}>
                {zh ? '暂无动态' : 'No recent activity'}
              </div>
            ) : (
              <div className="space-y-0">
                {recentEvents.map((ev, i) => (
                  <div
                    key={ev.id + i}
                    className="flex items-center gap-3 py-2 border-b last:border-b-0"
                    style={{ borderColor: 'var(--card-border)' }}
                  >
                    {/* severity dot */}
                    <div
                      className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      style={{ background: severityDot[ev.severity] || '#8c8c8c' }}
                    />
                    {/* icon */}
                    {ev.type === 'alert'
                      ? <Bell size={13} strokeWidth={1.5} style={{ color: 'var(--muted-text)' }} className="flex-shrink-0" />
                      : <Zap  size={13} strokeWidth={1.5} style={{ color: 'var(--muted-text)' }} className="flex-shrink-0" />}
                    {/* text */}
                    <span className="text-[12px] flex-1 truncate" style={{ color: 'var(--body-text)' }}>
                      {ev.title}
                    </span>
                    {/* time */}
                    <span className="text-[11px] flex-shrink-0 flex items-center gap-1" style={{ color: 'var(--dim-text)' }}>
                      <Clock size={10} /> {timeAgo(ev.time, zh)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Right: Quick Actions (1/3) ── */}
          <div
            className="rounded-xl px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 4px 16px rgba(0, 0, 0, 0.04)' }}
          >
            <span className="text-[13px] font-semibold block mb-3" style={{ color: 'var(--heading-text)' }}>
              {zh ? '快捷操作' : 'Quick Actions'}
            </span>
            <div className="space-y-2">
              {quickActions.map((a, i) => {
                const AIcon = a.icon;
                return (
                  <button
                    key={i}
                    onClick={() => navigate(a.path)}
                    className="w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left cursor-pointer transition-colors duration-150"
                    style={{ background: 'transparent' }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--app-hover-bg)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div
                      className="flex items-center justify-center w-7 h-7 rounded-md flex-shrink-0"
                      style={{ background: `${a.accent}14` }}
                    >
                      <AIcon size={14} strokeWidth={1.6} style={{ color: a.accent }} />
                    </div>
                    <span className="text-[12px] font-medium" style={{ color: 'var(--heading-text)' }}>{a.label}</span>
                    <ArrowRight size={12} className="ml-auto flex-shrink-0" style={{ color: 'var(--dim-text)' }} />
                  </button>
                );
              })}
            </div>
          </div>
        </motion.div>

        {/* ════════ 5. Three-column: Device Status │ Host Resources │ Platform Distribution ════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.24 }}
          className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4"
        >
          {/* ── Left: Device Status Overview ── */}
          <div
            className="rounded-xl px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 4px 16px rgba(0, 0, 0, 0.04)' }}
          >
            <span className="text-[13px] font-semibold block mb-3" style={{ color: 'var(--heading-text)' }}>
              {zh ? '设备状态' : 'Device Status'}
            </span>
            {stats.total > 0 ? (
              <>
                {/* Stacked status bar */}
                <div className="flex h-2.5 rounded-full overflow-hidden mb-3" style={{ background: 'var(--app-hover-bg)' }}>
                  {stats.online > 0 && (
                    <div style={{ width: `${(stats.online / stats.total) * 100}%`, background: '#52c41a' }} />
                  )}
                  {stats.pending > 0 && (
                    <div style={{ width: `${(stats.pending / stats.total) * 100}%`, background: '#fa8c16' }} />
                  )}
                  {stats.offline > 0 && (
                    <div style={{ width: `${(stats.offline / stats.total) * 100}%`, background: '#f5222d' }} />
                  )}
                </div>
                {/* Legend */}
                <div className="space-y-1.5">
                  {([
                    { label: zh ? '在线' : 'Online', count: stats.online, color: '#52c41a' },
                    { label: zh ? '离线' : 'Offline', count: stats.offline, color: '#f5222d' },
                    { label: zh ? '待定' : 'Pending', count: stats.pending, color: '#fa8c16' },
                  ] as const).map(s => (
                    <div key={s.label} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ background: s.color }} />
                        <span className="text-[12px]" style={{ color: 'var(--body-text)' }}>{s.label}</span>
                      </div>
                      <span className="text-[12px] font-medium tabular-nums" style={{ color: 'var(--heading-text)' }}>
                        {s.count}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="text-[12px] py-4 text-center" style={{ color: 'var(--dim-text)' }}>
                {zh ? '暂无设备' : 'No devices'}
              </div>
            )}
          </div>

          {/* ── Middle: Host Resources ── */}
          <div
            className="rounded-xl px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 4px 16px rgba(0, 0, 0, 0.04)' }}
          >
            <span className="text-[13px] font-semibold block mb-3" style={{ color: 'var(--heading-text)' }}>
              {zh ? '主机资源' : 'Host Resources'}
            </span>
            <div className="space-y-3">
              {([
                {
                  label: 'CPU',
                  icon: Cpu,
                  percent: stats.cpuPercent,
                  sub: stats.cpuPercent !== null ? `${stats.cpuPercent}%` : '—',
                  color: '#722ed1',
                },
                {
                  label: zh ? '内存' : 'Memory',
                  icon: MemoryStick,
                  percent: stats.memPercent,
                  sub: stats.memUsedGb !== null && stats.memTotalGb !== null
                    ? `${stats.memUsedGb.toFixed(1)} / ${stats.memTotalGb.toFixed(1)} GB`
                    : '—',
                  color: '#1677ff',
                },
                {
                  label: zh ? '磁盘' : 'Disk',
                  icon: HardDrive,
                  percent: stats.diskPercent,
                  sub: stats.diskUsedGb !== null && stats.diskTotalGb !== null
                    ? `${stats.diskUsedGb.toFixed(1)} / ${stats.diskTotalGb.toFixed(1)} GB`
                    : '—',
                  color: '#13c2c2',
                },
              ] as const).map(r => {
                const RIcon = r.icon;
                const pct = r.percent ?? 0;
                return (
                  <div key={r.label}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5">
                        <RIcon size={12} strokeWidth={1.6} style={{ color: r.color }} />
                        <span className="text-[11px] font-medium" style={{ color: 'var(--body-text)' }}>{r.label}</span>
                      </div>
                      <span className="text-[11px] tabular-nums" style={{ color: 'var(--muted-text)' }}>{r.sub}</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: 'var(--app-hover-bg)' }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: r.percent !== null ? `${Math.min(pct, 100)}%` : '0%',
                          background: pct >= 90 ? '#f5222d' : pct >= 70 ? '#fa8c16' : r.color,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Right: Platform Distribution ── */}
          <div
            className="rounded-xl px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 4px 16px rgba(0, 0, 0, 0.04)' }}
          >
            <span className="text-[13px] font-semibold block mb-3" style={{ color: 'var(--heading-text)' }}>
              {zh ? '平台分布' : 'Platform Distribution'}
            </span>
            {stats.platforms.length > 0 ? (
              <div className="space-y-2">
                {stats.platforms.map(([platform, count]) => (
                  <div key={platform}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-[11px]" style={{ color: 'var(--body-text)' }}>{platform}</span>
                      <span className="text-[11px] font-medium tabular-nums" style={{ color: 'var(--heading-text)' }}>
                        {count}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--app-hover-bg)' }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${(count / stats.total) * 100}%`,
                          background: '#0078d4',
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[12px] py-4 text-center" style={{ color: 'var(--dim-text)' }}>
                {zh ? '暂无数据' : 'No data'}
              </div>
            )}
          </div>
        </motion.div>

        {/* bottom spacer */}
        <div className="h-4" />
      </div>
    </div>
  );
};

export default HomePage;
