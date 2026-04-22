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
      { id: 'dashboard',    label: '运营总览',   labelEn: 'Overview',          path: '/overview' },
      { id: 'monitoring',   label: '监控中心',  labelEn: 'Monitoring',        path: '/monitoring' },
      { id: 'topology',     label: '网络拓扑',  labelEn: 'Topology',          path: '/topology' },
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
      { id: 'devices',  label: '网络设备',     labelEn: 'Network Devices',      path: '/inventory/devices' },
      { id: 'servers',  label: '服务器',       labelEn: 'Servers',              path: '/inventory/servers' },
      { id: 'ipam',     label: 'IP/VLAN管理',  labelEn: 'IP/VLAN Mgmt',        path: '/ipam' },
      { id: 'ip-locator', label: 'IP 工具箱',  labelEn: 'IP Toolbox',            path: '/ip-locator' },
      { id: 'tags',     label: '标签管理',     labelEn: 'Tags',                 path: '/tags' },
      { id: 'racks',    label: '机柜管理',     labelEn: 'Rack Layout',          path: '/racks' },
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
      { id: 'auto-exec',  label: '自动化任务',  labelEn: 'Automation',        path: '/automation/execute', activeMatch: '/automation/execute,/automation/playbooks,/automation/scenarios,/automation/history' },
      { id: 'inspection', label: '巡检概览',    labelEn: 'Inspection Overview', path: '/automation/inspection' },
      { id: 'inspection-records', label: '巡检记录', labelEn: 'Inspection Records', path: '/automation/inspection-records' },
      { id: 'exec-schedule', label: '执行计划',  labelEn: 'Execution Schedules', path: '/automation/schedule' },
      { id: 'exec-history', label: '执行历史',   labelEn: 'Execution History', path: '/automation/schedule-history' },
      { id: 'scheduled-jobs', label: '定时作业',  labelEn: 'Scheduled Jobs',    path: '/automation/scheduled-jobs' },
      { id: 'inspection-metrics', label: '巡检指标', labelEn: 'Inspection Metrics', path: '/automation/metrics' },
    ],
  },
  {
    id: 'tickets',
    label: '工单管理',
    labelEn: 'TICKETS',
    icon: 'ClipboardList',
    children: [
      { id: 'new-order',           label: '新建工单',  labelEn: 'New Order',         path: '/change-orders/new' },
      { id: 'my-todo',             label: '个人待办',  labelEn: 'My Todo',           path: '/change-orders/my-todo' },
      { id: 'group-todo',          label: '组内待办',  labelEn: 'Group Todo',        path: '/change-orders/group-todo' },
      { id: 'my-participated',     label: '我参与的',  labelEn: 'My Participated',   path: '/change-orders/participated' },
      { id: 'my-focus',            label: '我的关注',  labelEn: 'My Focus',          path: '/change-orders/focus' },
      { id: 'change-orders',       label: '全部工单',  labelEn: 'All Orders',        path: '/change-orders/all' },
      { id: 'my-drafts',           label: '草稿箱',    labelEn: 'Drafts',            path: '/change-orders/drafts' },
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
      { id: 'credentials',     label: '凭据管理',  labelEn: 'Credentials', icon: 'Shield',   path: '/credentials', requiredRole: 'Administrator' },
    ],
  },
];
