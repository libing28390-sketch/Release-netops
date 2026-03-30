/**
 * Navigation configuration for AppSidebar.
 * Defines section groups, items, routes, and badge bindings.
 *
 * Paths map to the actual React Router routes used by the app.
 * Use `activeMatch` for items that should highlight across
 * multiple sub-routes (e.g. /config/backup, /config/diff).
 */
import type { NavGroup } from './types';

export const navConfig: NavGroup[] = [
  {
    id: 'realtime',
    label: '实时监控',
    labelEn: 'REAL-TIME',
    icon: 'Activity',
    badge: 'monitoring',
    children: [
      { id: 'dashboard',    label: '仪表盘',   labelEn: 'Dashboard',         path: '/dashboard' },
      { id: 'monitoring',   label: '监控中心',  labelEn: 'Monitoring',        path: '/monitoring' },
      { id: 'topology',     label: '网络拓扑',  labelEn: 'Topology',          path: '/topology' },
      { id: 'health',       label: '健康检测',  labelEn: 'Health Detection',  path: '/health' },
    ],
  },
  {
    id: 'alerts',
    label: '告警处置',
    labelEn: 'ALERTS',
    icon: 'Bell',
    children: [
      { id: 'alert-desk',   label: '告警中心',  labelEn: 'Alert Center',   path: '/alerts' },
      { id: 'alert-history', label: '历史告警', labelEn: 'Alert History',  path: '/alert-history' },
      { id: 'alert-rules',  label: '告警规则',  labelEn: 'Alert Rules',    path: '/alert-rules' },
      { id: 'maintenance',  label: '维护期',    labelEn: 'Maintenance',    path: '/maintenance' },
    ],
  },
  {
    id: 'assets-config',
    label: '资产与配置',
    labelEn: 'ASSETS & CONFIG',
    icon: 'Server',
    children: [
      { id: 'assets',   label: '资产管理',     labelEn: 'Assets',               path: '/assets' },
      { id: 'devices',  label: '设备列表',     labelEn: 'Device List',          path: '/inventory/devices' },
      { id: 'ipam',     label: 'IP/VLAN管理',  labelEn: 'IP/VLAN Mgmt',        path: '/ipam' },
    ],
  },
  {
    id: 'config-mgmt',
    label: '配置管理',
    labelEn: 'CONFIG',
    icon: 'FileText',
    children: [
      { id: 'config-backup',  label: '备份中心',   labelEn: 'Backup Center',    path: '/config/backup' },
      { id: 'config-diff',    label: '配置对比',   labelEn: 'Config Diff',      path: '/config/diff' },
      { id: 'config-search',  label: '配置搜索',   labelEn: 'Config Search',    path: '/config/search' },
    ],
  },
  {
    id: 'automation',
    label: '自动化',
    labelEn: 'AUTOMATION',
    icon: 'Zap',
    children: [
      { id: 'auto-exec',  label: '自动化任务',  labelEn: 'Automation',        path: '/automation/execute', activeMatch: '/automation/' },
      { id: 'scheduled',  label: '定时任务',    labelEn: 'Scheduled Tasks',   path: '/config/schedule' },
    ],
  },
  {
    id: 'tickets',
    label: '工单管理',
    labelEn: 'TICKETS',
    icon: 'ClipboardList',
    children: [
      { id: 'change-orders',  label: '变更工单',  labelEn: 'Change Orders',  path: '/change-orders' },
    ],
  },
  {
    id: 'capacity',
    label: '容量与报表',
    labelEn: 'CAPACITY',
    icon: 'BarChart2',
    children: [
      { id: 'capacity',  label: '容量分析',  labelEn: 'Capacity',  path: '/capacity' },
      { id: 'reports',   label: '报表中心',  labelEn: 'Reports',   path: '/reports' },
    ],
  },
  {
    id: 'management',
    label: '平台管理',
    labelEn: 'MANAGEMENT',
    section: true,
    children: [
      { id: 'history',        label: '审计日志',  labelEn: 'Audit Logs',  icon: 'Clock',    path: '/history' },
      { id: 'configuration',  label: '平台设置',  labelEn: 'Settings',    icon: 'Settings', path: '/configuration' },
      { id: 'users',          label: '用户管理',  labelEn: 'Users',       icon: 'User',     path: '/users' },
    ],
  },
];
