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
      { id: 'dashboard',         label: '运营总览',   labelEn: 'Overview',          path: '/monitor/overview',    icon: 'LayoutDashboard' },
      { id: 'monitoring',        label: '监控中心',  labelEn: 'Monitoring',        path: '/monitor/telemetry',   icon: 'Activity' },
      { id: 'outbound-monitoring', label: '互联网出口', labelEn: 'Internet Outbound', path: '/monitor/outbound', icon: 'Globe' },
      { id: 'server-monitoring', label: '服务器监控', labelEn: 'Server Monitoring', path: '/monitor/servers',     icon: 'Server' },
      { id: 'network-monitoring', label: '网络监控', labelEn: 'Network Monitoring', path: '/monitor/networks',    icon: 'Router' },
      { id: 'topology',          label: '网络拓扑',  labelEn: 'Topology',          path: '/monitor/topology',    icon: 'Network' },
    ],
  },
  {
    id: 'terminal-access',
    label: '终端接入',
    labelEn: 'TERMINAL ACCESS',
    icon: 'Terminal',
    children: [
      { id: 'access-center', label: '操作工作台', labelEn: 'Operation Workspace', path: '/access/workspace',     icon: 'Terminal' },
      { id: 'pam-audit',     label: '受控审计',   labelEn: 'PAM Audit',           path: '/access/pam-audit',  icon: 'ShieldCheck', requiredRole: 'Administrator' },
    ],
  },
  {
    id: 'alerts',
    label: '告警处置',
    labelEn: 'ALERTS',
    icon: 'Bell',
    children: [
      { id: 'alert-desk',    label: '告警中心', labelEn: 'Alert Center',  path: '/alerts/desk',         icon: 'Bell' },
      { id: 'alert-history', label: '历史告警', labelEn: 'Alert History', path: '/alerts/history',  icon: 'History' },
      { id: 'alert-rules',   label: '告警规则', labelEn: 'Alert Rules',   path: '/alerts/rules',    icon: 'SlidersHorizontal', requiredRole: 'Operator' },
      { id: 'maintenance',   label: '维护期',   labelEn: 'Maintenance',   path: '/alerts/maintenance',    icon: 'Wrench', requiredRole: 'Operator' },
    ],
  },
  {
    id: 'assets-config',
    label: '资产与配置',
    labelEn: 'ASSETS & CONFIG',
    icon: 'Server',
    children: [
      { id: 'assets',     label: '资产管理',    labelEn: 'Assets',          path: '/assets/dashboard',   icon: 'Package' },
      { id: 'devices',    label: '网络设备',    labelEn: 'Network Devices', path: '/assets/network-devices', icon: 'Router' },
      { id: 'servers',    label: '服务器',      labelEn: 'Servers',         path: '/assets/servers',     icon: 'Server' },
      { id: 'path-diagnose', label: 'NPA 智能路径诊断', labelEn: 'NPA Path Diagnostics', path: '/assets/diagnose', icon: 'ShieldAlert' },
      { id: 'nsot',          label: '网络事实库',      labelEn: 'Network Facts (NSOT)', path: '/assets/nsot',     icon: 'Database' },
      { id: 'tags',       label: '标签管理',    labelEn: 'Tags',            path: '/assets/tags',        icon: 'Tag' },
    ],
  },
  {
    id: 'cmdb-group',
    label: 'CMDB基础数据',
    labelEn: 'CMDB Core',
    icon: 'Database',
    children: [
      { id: 'cmdb-credentials', label: '凭据中心', labelEn: 'Credentials', path: '/cmdb/credentials', icon: 'Key', requiredRole: 'Operator' },
      { id: 'cmdb-racks',       label: '机柜管理', labelEn: 'Rack Layout',   path: '/cmdb/racks',       icon: 'Columns3', requiredRole: 'Operator' },
      { id: 'cmdb-assets',      label: '资产目录', labelEn: 'Asset Catalog', path: '/cmdb/assets',      icon: 'Package', requiredRole: 'Viewer' },
      { id: 'cmdb-resources',   label: '资源检索', labelEn: 'Resource Search', path: '/cmdb/resources',  icon: 'Search', requiredRole: 'Viewer' },
      { id: 'cmdb-devices',     label: '设备骨架', labelEn: 'Devices',       path: '/cmdb/devices',     icon: 'Server', requiredRole: 'Operator' },
      { id: 'cmdb-interfaces',  label: '接口骨架', labelEn: 'Interfaces',    path: '/cmdb/interfaces',  icon: 'Network', requiredRole: 'Operator' },
      { id: 'cmdb-sites',       label: '站点管理', labelEn: 'Sites',       path: '/cmdb/sites',       icon: 'Building2', requiredRole: 'Operator' },
      { id: 'cmdb-vrfs',        label: 'VRF管理',  labelEn: 'VRFs',        path: '/cmdb/vrfs',        icon: 'Network', requiredRole: 'Operator' },
      { id: 'cmdb-vlans',       label: 'VLAN管理', labelEn: 'VLANs',       path: '/cmdb/vlans',       icon: 'Layers', requiredRole: 'Operator' },
      { id: 'cmdb-vlan-business', label: 'VLAN业务', labelEn: 'VLAN Business', path: '/cmdb/vlan-business', icon: 'Users', requiredRole: 'Operator' },
      { id: 'cmdb-tenants',     label: '租户管理', labelEn: 'Tenants',     path: '/cmdb/tenants',     icon: 'Users', requiredRole: 'Operator' },
    ],
  },
  {
    id: 'ipam-group',
    label: 'IPAM',
    labelEn: 'IPAM',
    icon: 'Globe',
    children: [
      { id: 'ipam-locate',   label: 'IP定位',       labelEn: 'IP Locator',      path: '/ipam/locate',        icon: 'MapPin' },
      { id: 'ipam-prefixes', label: 'Prefix管理',  labelEn: 'Prefixes',       path: '/ipam/prefixes',     icon: 'Network' },
      { id: 'ipam-ips',      label: 'IP地址',     labelEn: 'IP Addresses',   path: '/ipam/ips',          icon: 'MapPin' },
      { id: 'ipam-pools',    label: '地址池',     labelEn: 'IP Pools',       path: '/ipam/pools',        icon: 'Package' },
      { id: 'ipam-vips',     label: 'VIP管理',    labelEn: 'VIP Mgmt',       path: '/ipam/vips',         icon: 'ShieldCheck' },
      { id: 'ipam-dhcp',     label: 'DHCP租约',   labelEn: 'DHCP Leases',    path: '/ipam/dhcp',         icon: 'Clock' },
      { id: 'ipam-util',     label: '利用率分析',  labelEn: 'Utilization',    path: '/ipam/utilization',  icon: 'TrendingUp' },
      { id: 'ipam-reconciliation', label: 'IP对账中心', labelEn: 'IP Reconciliation', path: '/ipam/reconciliation', icon: 'ClipboardCheck' },
    ]
  },
  {
    id: 'config-mgmt',
    label: '配置管理',
    labelEn: 'CONFIG',
    icon: 'FileText',
    children: [
      { id: 'config-backup',   label: '备份中心', labelEn: 'Backup Center',   path: '/config/backup',    icon: 'Archive' },
      { id: 'config-schedule', label: '备份计划', labelEn: 'Backup Schedule', path: '/config/schedule',  icon: 'CalendarClock', requiredRole: 'Operator' },
      { id: 'config-diff',     label: '配置对比', labelEn: 'Config Diff',     path: '/config/diff',      icon: 'GitCompare' },
      { id: 'config-search',   label: '配置搜索', labelEn: 'Config Search',   path: '/config/search',    icon: 'Search' },
      { id: 'configuration',   label: '配置模板', labelEn: 'Templates',       path: '/config/templates', icon: 'FileCode2', requiredRole: 'Operator' },
    ],
  },
  {
    id: 'automation',
    label: '自动化',
    labelEn: 'AUTOMATION',
    icon: 'Zap',
    children: [
      { id: 'auto-exec',           label: '自动化任务', labelEn: 'Automation',           path: '/automation/tasks', activeMatch: '/automation/tasks,/automation/playbooks,/automation/scenarios', icon: 'Zap' },
      { id: 'inspection',          label: '巡检概览',   labelEn: 'Inspection Overview',  path: '/automation/inspections',          icon: 'ClipboardCheck' },
      { id: 'inspection-records',  label: '巡检记录',   labelEn: 'Inspection Records',   path: '/automation/records',              icon: 'FileSearch' },
      { id: 'exec-schedule',       label: '执行计划',   labelEn: 'Execution Schedules',  path: '/automation/schedules',            icon: 'CalendarClock', requiredRole: 'Operator' },
      { id: 'exec-history',        label: '执行历史',   labelEn: 'Execution History',    path: '/automation/history',             icon: 'History' },
      { id: 'scheduled-jobs',      label: '定时作业',   labelEn: 'Scheduled Jobs',       path: '/automation/scheduled-jobs',      icon: 'Timer', requiredRole: 'Operator' },
      { id: 'inspection-metrics',  label: '巡检指标',   labelEn: 'Inspection Metrics',   path: '/automation/metrics',             icon: 'BarChart2' },
      { id: 'textfsm-templates',   label: '解析模板',   labelEn: 'Parse Templates',      path: '/automation/textfsm',             icon: 'FileCode2', requiredRole: 'Operator' },
      { id: 'scripts',             label: '操作管理',   labelEn: 'Operations',           path: '/automation/scripts',             icon: 'Code2', requiredRole: 'Operator' },
    ],
  },
  {
    id: 'tickets',
    label: '工单管理',
    labelEn: 'TICKETS',
    icon: 'ClipboardList',
    children: [
      { id: 'new-order',       label: '新建工单', labelEn: 'New Order',       path: '/change-orders/new',         icon: 'PlusCircle' },
      { id: 'my-todo',         label: '个人待办', labelEn: 'My Todo',         path: '/change-orders/my-todo',     icon: 'Inbox' },
      { id: 'group-todo',      label: '组内待办', labelEn: 'Group Todo',      path: '/change-orders/group-todo',  icon: 'Users' },
      { id: 'my-participated', label: '我参与的', labelEn: 'My Participated', path: '/change-orders/participated', icon: 'UserCheck' },
      { id: 'my-focus',        label: '我的关注', labelEn: 'My Focus',        path: '/change-orders/focus',       icon: 'Star' },
      { id: 'change-orders',   label: '全部工单', labelEn: 'All Orders',      path: '/change-orders/all',         icon: 'ClipboardList' },
      { id: 'my-drafts',       label: '草稿箱',   labelEn: 'Drafts',          path: '/change-orders/drafts',      icon: 'FileEdit' },
    ],
  },
  {
    id: 'capacity',
    label: '容量与报表',
    labelEn: 'CAPACITY',
    icon: 'BarChart2',
    children: [
      { id: 'capacity', label: '容量分析', labelEn: 'Capacity', path: '/capacity/analysis', icon: 'TrendingUp' },
      { id: 'reports',  label: '报表中心', labelEn: 'Reports',  path: '/capacity/reports',  icon: 'BarChart3' },
    ],
  },
  {
    id: 'ai-center-group',
    label: 'AI 中心',
    labelEn: 'AI CENTER',
    icon: 'Bot',
    children: [
      { id: 'ai-providers',  label: 'Provider 供应商', labelEn: 'Providers',    path: '/ai/providers', activeMatch: '/ai/center,/ai/providers', icon: 'Server', requiredRole: 'Administrator' },
      { id: 'ai-models',     label: 'Model & 路由',   labelEn: 'Models',       path: '/ai/models',     icon: 'Cpu', requiredRole: 'Administrator' },
      { id: 'ai-prompts',    label: 'Prompt 提示词',   labelEn: 'Prompts',      path: '/ai/prompts',    icon: 'FileCode2', requiredRole: 'Administrator' },
      { id: 'ai-copilot',    label: 'AI Copilot 对话', labelEn: 'AI Copilot',   path: '/ai/copilot',    icon: 'MessageSquare' },
      { id: 'ai-agents',     label: 'Agent 注册表',    labelEn: 'Agents',       path: '/ai/agents',     icon: 'Layers3', requiredRole: 'Administrator' },
      { id: 'ai-knowledge',  label: '知识库管理',      labelEn: 'Knowledge',    path: '/ai/knowledge',  icon: 'BookOpen', requiredRole: 'Administrator' },
      { id: 'ai-retrieval-test', label: '检索测试', labelEn: 'Retrieval Test', path: '/ai/retrieval-test', icon: 'Search', requiredRole: 'Administrator' },
      { id: 'ai-catalog',    label: '产品目录',        labelEn: 'Product Catalog', path: '/ai/catalog', icon: 'Layers', requiredRole: 'Administrator' },
      { id: 'ai-governance', label: 'AI 变更治理',    labelEn: 'Governance',   path: '/ai/governance', icon: 'ShieldCheck', requiredRole: 'Administrator' },
      { id: 'ai-usage',      label: 'Token 统计审计',  labelEn: 'Token Usage',  path: '/ai/usage',      icon: 'Activity', requiredRole: 'Administrator' },
      { id: 'ai-security',   label: 'AI 安全网关',     labelEn: 'AI Security',  path: '/ai/security',   icon: 'ShieldCheck', requiredRole: 'Administrator' },
    ],
  },

  {
    id: 'management',
    label: '平台管理',
    labelEn: 'MANAGEMENT',
    section: true,
    children: [
      { id: 'audit',        label: '审计日志', labelEn: 'Audit Logs',        icon: 'Clock',  path: '/management/audit',       requiredRole: 'Administrator' },
      { id: 'users',        label: '用户管理', labelEn: 'Users',             icon: 'User',   path: '/management/users',       requiredRole: 'Administrator' },
      { id: 'credentials',  label: '凭据轮换', labelEn: 'Password Rotation', icon: 'Key',    path: '/management/credentials', requiredRole: 'Administrator' },
      { id: 'snmp-metric-templates', label: 'SNMP 指标模板', labelEn: 'SNMP Metric Templates', icon: 'Cpu', path: '/management/snmp-metric-templates', requiredRole: 'Viewer' },
    ],
  },
];
