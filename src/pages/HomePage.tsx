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
  Plus,
  Play,
  Server,
  SlidersHorizontal,
  Users,
  Wifi,
  Zap,
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
  icon: React.ElementType;
  path: string;
  accent: string;
}

/* ─────────────── App definitions ─────────────── */

const apps: AppEntry[] = [
  { id: 'monitor',    label: '实时监控',   labelEn: 'Monitoring',   icon: Activity,          path: '/overview',           accent: '#1677ff' },
  { id: 'alerts',     label: '告警管理',   labelEn: 'Alerts',       icon: Bell,              path: '/alerts',             accent: '#fa8c16' },
  { id: 'assets',     label: '资产与配置', labelEn: 'Assets',       icon: Server,            path: '/assets',             accent: '#1677ff' },
  { id: 'config',     label: '配置管理',   labelEn: 'Config',       icon: FileCode2,         path: '/config/backup',      accent: '#722ed1' },
  { id: 'automation', label: '自动化',     labelEn: 'Automation',   icon: Zap,               path: '/automation/execute', accent: '#0891b2' },
  { id: 'tickets',    label: '工单管理',   labelEn: 'Tickets',      icon: ClipboardList,     path: '/change-orders',      accent: '#1677ff' },
  { id: 'capacity',   label: '容量与报表', labelEn: 'Reports',      icon: BarChart2,         path: '/capacity',           accent: '#13c2c2' },
  { id: 'platform',   label: '平台管理',   labelEn: 'Platform',     icon: SlidersHorizontal, path: '/history',            accent: '#8c8c8c' },
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
    const now = Date.now();
    const todayJobs = jobs.filter(j => new Date(j.created_at).getTime() > now - 86400000);
    const successJobs = todayJobs.filter(j => j.status === 'success').length;
    const successRate = todayJobs.length > 0 ? Math.round((successJobs / todayJobs.length) * 100) : 100;
    const critical = notifications.filter(n => !n.read && (n.severity === 'critical' || n.severity === 'high')).length;
    return {
      total: devices.length, online,
      onlineRate: devices.length > 0 ? Math.round((online / devices.length) * 100) : 0,
      cpuPercent: hostResources?.cpu_percent ?? null,
      memPercent: hostResources?.mem_percent ?? null,
      critical, successRate, userCount,
      todayJobs: todayJobs.length,
    };
  }, [devices, jobs, notifications, hostResources, userCount]);

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
      className="select-none overflow-y-auto"
      style={{ height: 'calc(100vh - 4rem)', background: 'var(--app-bg)' }}
    >
      <div className="max-w-[960px] w-full mx-auto px-5 sm:px-8 py-6">

        {/* ════════ 1. Title ════════ */}
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
          <h1 className="text-lg font-semibold tracking-tight" style={{ color: 'var(--heading-text)' }}>
            Nexora {zh ? '控制台' : 'Console'}
            <span className="ml-2 text-[13px] font-normal" style={{ color: 'var(--muted-text)' }}>
              {zh ? '网络自动化运维平台' : 'Network Automation Platform'}
            </span>
          </h1>
        </motion.div>

        {/* ════════ 2. Icon Grid — 5 cols ════════ */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.04 }}
          className="mt-5 grid grid-cols-4 sm:grid-cols-5 lg:grid-cols-8 gap-x-1 gap-y-2"
        >
          {apps.map((app, idx) => {
            const Icon = app.icon;
            return (
              <motion.button
                key={app.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.2, delay: 0.06 + 0.025 * idx }}
                onClick={() => navigate(app.path)}
                className="group flex flex-col items-center text-center rounded-lg py-3 px-1 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-cyan-500/30 transition-colors duration-150"
                style={{ background: 'transparent' }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--app-hover-bg)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                <div
                  className="flex items-center justify-center w-9 h-9 rounded-lg mb-1.5 transition-transform duration-150 group-hover:scale-105"
                  style={{ background: `${app.accent}14` }}
                >
                  <Icon size={18} strokeWidth={1.5} style={{ color: app.accent }} />
                </div>
                <span className="text-[11px] font-medium leading-tight" style={{ color: 'var(--heading-text)' }}>
                  {zh ? app.label : app.labelEn}
                </span>
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
                className="rounded-lg px-4 py-3.5 flex items-start gap-3"
                style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}
              >
                <div
                  className="flex items-center justify-center w-8 h-8 rounded-lg flex-shrink-0 mt-0.5"
                  style={{ background: `${s.accent}14` }}
                >
                  <Icon size={16} strokeWidth={1.6} style={{ color: s.accent }} />
                </div>
                <div className="min-w-0">
                  <div className="text-[11px] font-medium" style={{ color: 'var(--muted-text)' }}>{s.label}</div>
                  <div className="text-xl font-semibold tabular-nums leading-tight mt-0.5" style={{ color: s.accent }}>
                    {s.value}
                  </div>
                  <div className="text-[11px] mt-0.5" style={{ color: 'var(--dim-text)' }}>{s.sub}</div>
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
          className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4 pb-4"
        >
          {/* ── Left: Recent Activity (2/3) ── */}
          <div
            className="md:col-span-2 rounded-lg px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}
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
            className="rounded-lg px-4 py-3.5"
            style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)' }}
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
                    className="w-full flex items-center gap-3 rounded-md px-3 py-2.5 text-left cursor-pointer transition-colors duration-150"
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
      </div>
    </div>
  );
};

export default HomePage;
