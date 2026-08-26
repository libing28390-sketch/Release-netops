import React, { useMemo, useState, useEffect } from 'react';
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
  Bot,
  Sparkles,
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
  icon: React.ComponentType<any>;
  path: string;
  accent: string;
}

/* ─────────────── App definitions (12 Modules) ─────────────── */

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
  { id: 'ai',         label: 'AI 中心',    labelEn: 'AI Center',    desc: 'Copilot、Agent与排障', descEn: 'Copilot, Agent & RAG', icon: Bot,               path: '/ai/center',          accent: '#6366f1' },
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
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains('dark'));

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

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

  /* ── Quick Action Buttons ── */
  const quickActions = [
    { label: zh ? '添加网络设备' : 'Add Network Device', path: '/assets/network-devices', icon: Plus },
    { label: zh ? '执行自动化巡检' : 'Run Inspection', path: '/automation/inspections', icon: Play },
    { label: zh ? '查看配置差异' : 'View Config Diff', path: '/config/diff', icon: FileCode2 },
    { label: zh ? '新建变更工单' : 'New Change Order', path: '/change-orders/new', icon: ClipboardList },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* ════════ 1. Title + Inline Metrics ════════ */}
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b pb-5"
        style={{ borderColor: 'var(--card-border)' }}
      >
        <div>
          <h1 className="nx-page-title" style={{ color: 'var(--heading-text)' }}>
            {zh ? '你好，欢迎回来' : 'Welcome back'}
          </h1>
          <p className="nx-page-description mt-1" style={{ color: 'var(--muted-text)' }}>
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

      {/* ════════ 2. Stat Blocks — 4 cols ════════ */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.04 }}
        className="grid grid-cols-2 sm:grid-cols-4 gap-3.5"
      >
        {statBlocks.map((block, idx) => {
          const Icon = block.icon;
          return (
            <div
              key={idx}
              className="rounded-xl p-4 flex flex-col justify-between transition-all duration-150"
              style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: '12px', boxShadow: '0 4px 16px rgba(0,0,0,0.04)' }}
            >
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium" style={{ color: 'var(--muted-text)' }}>
                  {block.label}
                </span>
                <div className="w-7 h-7 rounded-md flex items-center justify-center" style={{ background: block.accent + '15', color: block.accent }}>
                  <Icon size={15} strokeWidth={2} />
                </div>
              </div>
              <div className="mt-3">
                <div className="text-2xl font-bold tracking-tight" style={{ color: 'var(--heading-text)' }}>
                  {block.value}
                </div>
                <div className="text-[11px] mt-0.5" style={{ color: 'var(--dim-text)' }}>
                  {block.sub}
                </div>
              </div>
            </div>
          );
        })}
      </motion.div>

      {/* ════════ 3. Module Grid — 4 cols card nav (12 Modules) ════════ */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.08 }}
        className="grid grid-cols-2 sm:grid-cols-4 gap-3"
      >
        {apps.map((app, idx) => {
          const Icon = app.icon;
          return (
            <motion.button
              key={app.id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: 0.06 + 0.025 * idx }}
              onClick={() => navigate(app.path)}
              className="group flex items-center gap-3 rounded-xl px-3.5 py-3 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30 transition-all duration-150 text-left"
              style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: '12px', boxShadow: '0 4px 16px rgba(0,0,0,0.04)' }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = app.accent + '60'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--card-border)'; }}
            >
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 transition-transform duration-150 group-hover:scale-105"
                style={{ background: app.accent + '15', color: app.accent }}
              >
                <Icon size={18} strokeWidth={2} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium truncate" style={{ color: 'var(--heading-text)' }}>
                  {zh ? app.label : app.labelEn}
                </div>
                <div className="text-[11px] truncate mt-0.5" style={{ color: 'var(--dim-text)' }}>
                  {zh ? app.desc : app.descEn}
                </div>
              </div>
            </motion.button>
          );
        })}
      </motion.div>

      {/* ════════ 3. Two-Column Layout — Platform Distribution + Quick Actions ════════ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Left (2 cols): System Platform Overview */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.18 }}
          className="lg:col-span-2 rounded-xl p-5 space-y-4"
          style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: '12px', boxShadow: '0 4px 16px rgba(0,0,0,0.04)' }}
        >
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold tracking-tight" style={{ color: 'var(--heading-text)' }}>
              {zh ? '厂商与平台分布' : 'Platform Distribution'}
            </h3>
            <button
              onClick={() => navigate('/assets/network-devices')}
              className="text-xs flex items-center gap-1 hover:underline cursor-pointer"
              style={{ color: 'var(--accent-color)' }}
            >
              {zh ? '查看全部设备' : 'View all devices'} <ArrowRight size={13} />
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {stats.platforms.map(([platform, count]) => (
              <div
                key={platform}
                className="p-3 rounded-lg flex items-center justify-between text-xs"
                style={{ background: 'var(--subtle-bg)', border: '1px solid var(--subtle-border)' }}
              >
                <span className="font-mono text-gray-700 dark:text-gray-300 truncate">{platform}</span>
                <span className="font-bold text-indigo-600 dark:text-indigo-400 ml-2">{count} 台</span>
              </div>
            ))}
          </div>

          {/* Quick host resources details if available */}
          {hostResources && (
            <div className="pt-3 border-t grid grid-cols-3 gap-3 text-xs" style={{ borderColor: 'var(--card-border)' }}>
              <div>
                <span style={{ color: 'var(--dim-text)' }}>内存使用:</span>{' '}
                <strong style={{ color: 'var(--heading-text)' }}>{stats.memUsedGb} GB / {stats.memTotalGb} GB ({stats.memPercent}%)</strong>
              </div>
              <div>
                <span style={{ color: 'var(--dim-text)' }}>磁盘使用:</span>{' '}
                <strong style={{ color: 'var(--heading-text)' }}>{stats.diskUsedGb} GB / {stats.diskTotalGb} GB ({stats.diskPercent}%)</strong>
              </div>
              <div>
                <span style={{ color: 'var(--dim-text)' }}>在线运行:</span>{' '}
                <strong style={{ color: 'var(--heading-text)' }}>{stats.uptimeHours} 小时</strong>
              </div>
            </div>
          )}
        </motion.div>

        {/* Right (1 col): Quick Actions */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.22 }}
          className="rounded-xl p-5 space-y-4"
          style={{ background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: '12px', boxShadow: '0 4px 16px rgba(0,0,0,0.04)' }}
        >
          <h3 className="text-sm font-semibold tracking-tight" style={{ color: 'var(--heading-text)' }}>
            {zh ? '快捷入口' : 'Quick Actions'}
          </h3>

          <div className="space-y-2">
            {quickActions.map((qa, idx) => {
              const Icon = qa.icon;
              return (
                <button
                  key={idx}
                  onClick={() => navigate(qa.path)}
                  className="w-full flex items-center justify-between p-3 rounded-lg text-xs font-medium transition cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/60"
                  style={{ border: '1px solid var(--subtle-border)' }}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon size={15} className="text-indigo-500" />
                    <span style={{ color: 'var(--heading-text)' }}>{qa.label}</span>
                  </div>
                  <ArrowRight size={13} style={{ color: 'var(--dim-text)' }} />
                </button>
              );
            })}
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default HomePage;
