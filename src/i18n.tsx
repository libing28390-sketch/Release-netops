import React, { createContext, useContext, useState, ReactNode } from 'react';

export type Language = 'en' | 'zh';

interface Translations {
  [key: string]: {
    [key in Language]: string;
  };
}

export const translations: Translations = {
  // Sidebar & Navigation
  dashboard: { en: 'Dashboard', zh: '仪表盘' },
  inventory: { en: 'Inventory', zh: '资产管理' },
  automation: { en: 'Automation', zh: '自动化中心' },
  configuration: { en: 'Platform Settings', zh: '平台设置' },
  compliance: { en: 'Compliance', zh: '合规审计' },
  auditLogs: { en: 'Audit Logs', zh: '审计日志' },
  settings: { en: 'Settings', zh: '设置' },
  logout: { en: 'Logout', zh: '退出登录' },

  // Dashboard
  networkOverview: { en: 'Network Overview', zh: '网络概览' },
  realTimeMetrics: { en: 'Real-time health and compliance metrics.', zh: '实时健康与合规指标。' },
  totalAssets: { en: 'Total Assets', zh: '资产总数' },
  onlineNodes: { en: 'Online Nodes', zh: '在线节点' },
  complianceRate: { en: 'Compliance', zh: '合规率' },
  failedTasks: { en: 'Failed Tasks (24h)', zh: '失败任务 (24h)' },
  recentActivity: { en: 'Recent Activity', zh: '最近活动' },
  platformDistribution: { en: 'Platform Distribution', zh: '平台分布' },
  complianceTrend: { en: 'Compliance Trend', zh: '合规趋势' },
  upcomingTasks: { en: 'Upcoming Tasks', zh: '即将进行的任务' },

  // Dashboard — extra labels
  dashboardSubtitle: { en: 'Real-time health and compliance metrics across your infrastructure', zh: '基础设施实时健康与合规指标' },
  complianceTrendSub: { en: 'Network-wide compliance stability over time', zh: '全网合规稳定性趋势' },
  recentActivitySub: { en: 'Latest automation and configuration tasks', zh: '最近的自动化与配置任务' },
  viewAuditLog: { en: 'View Full Audit Log', zh: '查看完整审计日志' },
  viewFullJobHistory: { en: 'View Full Execution History', zh: '查看完整作业历史' },
  noActivity: { en: 'No recent activity found.', zh: '暂无最近活动。' },
  noUpcomingTasks: { en: 'No upcoming tasks scheduled.', zh: '暂无计划中的任务。' },
  systemHealthy: { en: 'System Healthy', zh: '系统健康' },
  systemDegraded: { en: 'Degraded', zh: '性能下降' },
  systemCritical: { en: 'Critical', zh: '严重异常' },
  days7: { en: '7 Days', zh: '7 天' },
  days30: { en: '30 Days', zh: '30 天' },
  todaySnapshot: { en: "Today's Network Operations Snapshot", zh: '今日网络运营概览' },
  todaySnapshotDesc: { en: 'Recommended flow: review health and alerts first, then proceed to automation and audit tracking.', zh: '建议流程：先查看健康状态与告警，再进入自动化执行与审计追踪。' },
  openAutomation: { en: 'Open Automation', zh: '进入自动化执行' },
  viewExecHistory: { en: 'View Execution History', zh: '查看执行历史' },
  lastRefreshed: { en: 'Last refreshed', zh: '上次刷新' },
  secondsAgo: { en: 's ago', zh: '秒前' },
  rememberMe: { en: 'Remember me', zh: '记住我' },

  // Login — extra labels
  loginSubtitle: { en: 'Sign in to your operations console', zh: '登录到您的运维控制台' },
  systemOnline: { en: 'System Online', zh: '系统在线' },
  systemWarning: { en: 'Warning', zh: '告警' },
  networkPulse: { en: 'Network Pulse', zh: '网络脉搏' },
  networkPulseSub: { en: 'Live health snapshot', zh: '实时健康速览' },
  devicesOnlineShort: { en: 'Devices Online', zh: '在线设备' },
  loginStatDevices: { en: 'Devices', zh: '设备' },
  loginStatStatus: { en: 'Status', zh: '状态' },
  loginStatOnline: { en: 'Online', zh: '在线' },
  forgotPassword: { en: 'Forgot password?', zh: '忘记密码？' },
  forgotPasswordHint: { en: 'Please contact your system administrator to reset your password.', zh: '请联系系统管理员重置密码。' },
  // Forgot password modal
  fpTitle: { en: 'Reset Password', zh: '重置密码' },
  fpSubtitle: { en: 'A verification code will be sent to your notification channels', zh: '验证码将发送到您的通知渠道（飞书/钉钉/企业微信）' },
  fpStepUser: { en: 'Account', zh: '账户' },
  fpStepVerify: { en: 'Verify', zh: '验证' },
  fpStepReset: { en: 'Reset', zh: '重置' },
  fpUsernameRequired: { en: 'Please enter your username.', zh: '请输入用户名。' },
  fpUsernamePlaceholder: { en: 'Enter your username', zh: '请输入用户名' },
  fpSendHint: { en: 'A 6-digit code will be sent to the notification channels configured for your account.', zh: '6位验证码将发送至您账户已配置的通知渠道。' },
  fpSendCode: { en: 'Send Code', zh: '发送验证码' },
  fpSending: { en: 'Sending...', zh: '发送中...' },
  fpSendFailed: { en: 'Failed to send verification code. Please try again.', zh: '验证码发送失败，请重试。' },
  fpNetworkError: { en: 'Network error. Please check your connection.', zh: '网络错误，请检查网络连接。' },
  fpCodeLabel: { en: 'Verification Code', zh: '验证码' },
  fpCodeInvalid: { en: 'Please enter a valid 6-digit code.', zh: '请输入6位数字验证码。' },
  fpSentTo: { en: 'Sent to', zh: '已发送至' },
  fpResend: { en: 'Resend', zh: '重新发送' },
  fpNext: { en: 'Next', zh: '下一步' },
  fpBack: { en: 'Back', zh: '返回' },
  fpNewPassword: { en: 'New Password', zh: '新密码' },
  fpNewPasswordPlaceholder: { en: 'Enter new password', zh: '请输入新密码' },
  fpConfirmPassword: { en: 'Confirm Password', zh: '确认密码' },
  fpConfirmPlaceholder: { en: 'Confirm new password', zh: '请再次输入新密码' },
  fpPasswordHint: { en: '≥10 chars, must include uppercase, lowercase, digit, and special character.', zh: '≥10位，需包含大写字母、小写字母、数字和特殊字符。' },
  fpPasswordTooShort: { en: 'Password must be at least 10 characters.', zh: '密码长度不能少于10位。' },
  fpPasswordMismatch: { en: 'Passwords do not match.', zh: '两次输入的密码不一致。' },
  fpResetPassword: { en: 'Reset Password', zh: '重置密码' },
  fpResetting: { en: 'Resetting...', zh: '重置中...' },
  fpResetFailed: { en: 'Reset failed. Please check your code and try again.', zh: '重置失败，请检查验证码后重试。' },
  fpDoneTitle: { en: 'Password Reset Successful', zh: '密码重置成功' },
  fpDoneMessage: { en: 'Your password has been updated. Please log in with your new password.', zh: '密码已更新，请使用新密码登录。' },
  fpBackToLogin: { en: 'Back to Login', zh: '返回登录' },
  activeAlertsShort: { en: 'Active Alerts', zh: '当前告警' },
  runningTasksShort: { en: 'Running Tasks', zh: '运行任务' },
  lastSyncShort: { en: 'Last Sync', zh: '最后同步' },
  noSyncData: { en: 'Waiting for sync', zh: '等待同步数据' },
  copyright: { en: 'Copyright (c)', zh: 'Copyright (c)' },
  allRightsReserved: { en: 'Nexora. All rights reserved.', zh: 'Nexora. 保留所有权利。' },

  // Inventory
  deviceList: { en: 'Network Devices', zh: '网络设备' },
  deviceInventory: { en: 'Network Devices', zh: '网络设备' },
  manageMonitor: { en: 'Manage and monitor your network infrastructure.', zh: '管理和监控您的网络基础设施。' },
  import: { en: 'Import', zh: '导入' },
  export: { en: 'Export', zh: '导出' },
  addDevice: { en: 'Add Device', zh: '添加设备' },
  deviceInfo: { en: 'Device Info', zh: '设备信息' },
  hardwareSn: { en: 'Hardware / SN', zh: '硬件 / 序列号' },
  software: { en: 'Software', zh: '软件版本' },
  siteRole: { en: 'Site / Role', zh: '站点 / 角色' },
  status: { en: 'Status', zh: '状态' },
  actions: { en: 'Actions', zh: '操作' },
  config: { en: 'Config', zh: '配置' },
  details: { en: 'Details', zh: '详情' },

  // Automation
  automationCenter: { en: 'Automation Center', zh: '自动化中心' },
  deployChanges: { en: 'Deploy changes and run orchestration tasks.', zh: '部署变更并运行编排任务。' },
  selectTarget: { en: 'Select Target Device', zh: '选择目标设备' },
  taskLibrary: { en: 'Task Library', zh: '任务库' },
  quickActions: { en: 'Quick Actions', zh: '快速操作' },
  officialTemplates: { en: 'Official Templates', zh: '官方脚本模板' },
  scriptPreview: { en: 'Script Preview', zh: '脚本预览' },
  executionHistory: { en: 'Execution History', zh: '执行历史' },
  execute: { en: 'Execute', zh: '执行' },
  deviceStatus: { en: 'Device Status', zh: '设备状态' },
  lifecycleStatus: { en: 'Lifecycle Status', zh: '投产状态' },
  staging: { en: 'Staging', zh: '待投产' },
  production: { en: 'Production', zh: '已投产' },
  maintenance: { en: 'Maintenance', zh: '维护中' },
  decommissioned: { en: 'Decommissioned', zh: '已退役' },
  allLifecycle: { en: 'All Lifecycle', zh: '全部投产状态' },
  selectDeviceToViewDetails: { en: 'Select a device to view details and scripts', zh: '选择设备以查看详情和脚本' },
  searchPlaceholder: { en: 'Search hostname, IP...', zh: '搜索主机名、IP...' },
  official: { en: 'Official', zh: '官方' },
  custom: { en: 'Custom', zh: '自定义' },
  allPlatforms: { en: 'All Platforms', zh: '所有平台' },
  control: { en: 'Control', zh: '控制' },
  testConnection: { en: 'Test Connection', zh: '测试连接' },
  connecting: { en: 'Connecting...', zh: '正在连接...' },
  connectionSuccess: { en: 'Connection Successful', zh: '连接成功' },
  connectionFailed: { en: 'Connection Failed', zh: '连接失败' },
  updateVlan: { en: 'Update VLAN Config', zh: '更新 VLAN 配置' },
  complianceAudit: { en: 'Compliance Audit', zh: '合规性审计' },
  softwareUpgrade: { en: 'Software Upgrade', zh: '软件升级' },
  customScript: { en: 'Custom Script', zh: '自定义脚本' },
  recentExecutions: { en: 'Recent Executions', zh: '最近执行' },
  rollback: { en: 'Rollback', zh: '回滚' },
  schedule: { en: 'Schedule', zh: '定时' },
  scheduleTask: { en: 'Schedule Task', zh: '定时任务' },
  scheduleType: { en: 'Schedule Type', zh: '定时类型' },
  once: { en: 'Once', zh: '单次' },
  recurring: { en: 'Recurring', zh: '周期性' },
  interval: { en: 'Interval', zh: '间隔' },
  daily: { en: 'Daily', zh: '每天' },
  weekly: { en: 'Weekly', zh: '每周' },
  monthly: { en: 'Monthly', zh: '每月' },
  scheduledTime: { en: 'Scheduled Time', zh: '定时时间' },
  timezone: { en: 'Timezone', zh: '时区' },
  active: { en: 'Active', zh: '激活' },
  paused: { en: 'Paused', zh: '暂停' },
  completed: { en: 'Completed', zh: '已完成' },
  scheduledTasks: { en: 'Scheduled Tasks', zh: '定时任务列表' },
  noScheduledTasks: { en: 'No scheduled tasks.', zh: '没有定时任务。' },

  // Configuration
  configManagement: { en: 'Configuration Management', zh: '配置管理' },
  manageTemplates: { en: 'Manage templates, variables, and configuration archives.', zh: '管理模板、变量和配置归档。' },
  usageGuide: { en: 'How to use Configuration Management?', zh: '如何使用配置管理？' },
  guideStep1: { en: 'Create or import a configuration template using Jinja2 syntax.', zh: '使用 Jinja2 语法创建或导入配置模板。' },
  guideStep2: { en: 'Define global or device-specific variables in the variables section.', zh: '在变量部分定义全局或设备特定的变量。' },
  guideStep3: { en: 'Go to Automation Center to apply templates to target devices.', zh: '前往自动化中心将模板应用到目标设备。' },
  importVars: { en: 'Import Variables', zh: '导入变量' },
  addVar: { en: 'Add Variable', zh: '添加变量' },
  howToRef: { en: 'How to reference', zh: '如何引用' },
  varRefGuide: { en: 'Use double curly braces {{ var_name }} to insert variable values into your template.', zh: '使用双大括号 {{ 变量名 }} 将变量值插入到模板中。' },
  copied: { en: 'Copied to clipboard', zh: '已复制到剪贴板' },
  newTemplate: { en: 'New Template', zh: '新建模板' },
  importSuccess: { en: 'Successfully imported {{count}} devices.', zh: '成功导入 {{count}} 台设备。' },
  importSuccessVars: { en: 'Successfully imported {{count}} variables.', zh: '成功导入 {{count}} 个变量。' },
  authenticating: { en: 'Authenticating...', zh: '正在认证...' },
  loginSuccess: { en: 'Login successful.', zh: '登录成功。' },
  invalidCredentials: { en: 'Invalid username or password.', zh: '用户名或密码错误。' },
  accountLocked: { en: 'Account temporarily locked. Please try again later.', zh: '账户已临时锁定，请稍后再试。' },
  fillAllFields: { en: 'Please fill in all fields.', zh: '请填写所有字段。' },
  importSkipped: { en: ' Skipped {{count}} duplicates.', zh: ' 跳过 {{count}} 个重复项。' },
  importNoNew: { en: 'No new devices imported. All {{count}} entries were duplicates.', zh: '未导入新设备。所有 {{count}} 个条目均为重复项。' },
  importError: { en: 'Failed to parse file. Please ensure it is a valid Excel or CSV file.', zh: '文件解析失败。请确保它是有效的 Excel 或 CSV 文件。' },
  deviceDetails: { en: 'Device Details', zh: '设备详情' },
  basicInfo: { en: 'Basic Information', zh: '基本信息' },
  hardwareInfo: { en: 'Hardware Information', zh: '硬件信息' },
  locationRole: { en: 'Location & Role', zh: '位置与角色' },
  connectivity: { en: 'Connectivity', zh: '连接性' },
  serialNumber: { en: 'Serial Number', zh: '序列号' },
  uptime: { en: 'Uptime', zh: '运行时间' },
  method: { en: 'Method', zh: '方式' },
  close: { en: 'Close', zh: '关闭' },
  templates: { en: 'Config Templates', zh: '配置模板' },
  configModules: { en: 'Configuration Modules', zh: '配置中心模块' },
  globalVars: { en: 'Global Variables', zh: '全局变量' },
  editor: { en: 'Template Editor', zh: '模板编辑器' },
  editorMode: { en: 'Editor Mode', zh: '编辑器模式' },
  saveChanges: { en: 'Save Changes', zh: '保存更改' },
  saveSuccess: { en: 'Template saved successfully.', zh: '模板保存成功。' },
  changesDiscarded: { en: 'Changes discarded.', zh: '更改已放弃。' },
  discard: { en: 'Discard', zh: '放弃' },
  currentConfig: { en: 'Current Configuration', zh: '当前配置' },
  configHistory: { en: 'Configuration History', zh: '配置历史' },
  exportConfig: { en: 'Export Config', zh: '导出配置' },
  importConfig: { en: 'Import Config', zh: '导入配置' },
  noConfigHistory: { en: 'No configuration history available.', zh: '没有可用的配置历史。' },
  viewConfig: { en: 'View Config', zh: '查看配置' },
  rollbackTo: { en: 'Rollback to this version', zh: '回退到此版本' },
  configContent: { en: 'Configuration Content', zh: '配置内容' },
  version: { en: 'Version', zh: '版本' },
  author: { en: 'Author', zh: '作者' },
  description: { en: 'Description', zh: '描述' },

  // Config Center
  retentionPeriod: { en: 'Retention', zh: '保留期限' },
  retentionDays: { en: 'days', zh: '天' },
  storageUsed: { en: 'Storage', zh: '已用存储' },
  vendorGroup: { en: 'Vendor', zh: '厂商' },
  configCenter: { en: 'Config Center', zh: '配置中心' },
  configCenterDesc: { en: 'Backup · View · Diff · Search · Rollback', zh: '备份 · 查看 · 对比 · 搜索 · 回滚' },
  takeSnapshot: { en: 'Take Snapshot', zh: '抓取快照' },
  backupAllOnline: { en: 'Backup All Online', zh: '备份所有在线设备' },
  backupHistory: { en: 'Backup History', zh: '备份历史' },
  configViewTab: { en: 'Config View', zh: '配置查看' },
  diffCompare: { en: 'Diff Compare', zh: '差异对比' },
  configSearchTab: { en: 'Config Search', zh: '配置搜索' },
  selectDevice: { en: 'Select Device', zh: '选择设备' },
  allSnapshots: { en: 'All Snapshots', zh: '所有快照' },
  snapshotHistory: { en: 'Snapshot History', zh: '快照历史' },
  snapshotsCount: { en: 'snapshots', zh: '个快照' },
  noSnapshots: { en: 'No snapshots yet', zh: '暂无快照' },
  noSnapshotHint: { en: 'Select a device and click "Take Snapshot" to begin', zh: '选择设备并点击「抓取快照」开始' },
  triggerType: { en: 'Trigger', zh: '触发方式' },
  fileSize: { en: 'Size', zh: '大小' },
  changedBadge: { en: 'changed', zh: '已变更' },
  copy: { en: 'Copy', zh: '复制' },
  configCopied: { en: 'Config copied', zh: '配置已复制' },
  linesCount: { en: 'lines', zh: '行' },
  fetchLiveConfig: { en: 'Fetch Live Config', zh: '抓取实时配置' },
  configViewHint: { en: 'Select a snapshot from Backup History or click "Fetch Live Config"', zh: '从备份历史中选择快照，或点击「抓取实时配置」' },
  backToList: { en: '← Back to list', zh: '← 返回列表' },
  diffCompareTitle: { en: 'Diff Compare — Select two snapshots to compare', zh: '差异对比 — 选择两个快照进行比较' },
  beforeLabel: { en: 'Before (A)', zh: '之前 (A)' },
  afterLabel: { en: 'After (B)', zh: '之后 (B)' },
  chooseSnapshot: { en: '— choose snapshot —', zh: '— 选择快照 —' },
  linesAdded: { en: 'added', zh: '新增' },
  linesRemoved: { en: 'removed', zh: '删除' },
  noDiff: { en: 'No differences found', zh: '未发现差异' },
  diffHint: { en: 'Select two snapshots above to see the diff', zh: '在上方选择两个快照以查看差异' },
  searchAllConfigs: { en: 'Search Across All Configs', zh: '全局配置搜索' },
  searchHint: { en: 'Enter a keyword to search across all backed-up configs', zh: '输入关键词以搜索所有已备份配置' },
  searchHintSub: { en: 'Covers the latest snapshot per device', zh: '覆盖每台设备的最新快照' },
  noMatchesFound: { en: 'No matches found for', zh: '未找到匹配：' },
  moreLines: { en: 'more lines', zh: '更多行' },
  globalConfigSearchDesc: { en: 'Search IP, keyword, or config fragment across ALL device backup configs', zh: '在所有设备备份配置中搜索IP地址、关键词或配置片段' },
  globalSearchHint: { en: 'Global Config Search — Find anything across all devices', zh: '全局配置搜索 — 在所有设备中查找任意内容' },
  globalSearchHintDesc: { en: 'Enter an IP address (e.g. 192.168.1.1), VLAN, interface name, or any config keyword. Hit Enter or click Search to scan all backed-up device configs.', zh: '输入IP地址（如 192.168.1.1）、VLAN、接口名或任意配置关键词，按回车或点击搜索按钮扫描所有设备的备份配置。' },
  searching: { en: 'Searching', zh: '搜索中' },
  devicesMatched: { en: 'devices matched', zh: '个设备匹配' },
  totalMatches: { en: 'total matches', zh: '个匹配行' },
  delete: { en: 'Delete', zh: '删除' },
  snapshotSaved: { en: 'Snapshot saved for', zh: '快照已保存：' },
  snapshotDeleted: { en: 'Snapshot deleted', zh: '快照已删除' },

  // Config Center — Scheduled Backup
  scheduledBackup: { en: 'Scheduled Backup', zh: '定时备份' },
  enableSchedule: { en: 'Enable Daily Backup', zh: '启用每日定时备份' },
  enableScheduleHint: { en: 'Automatically back up all online devices at the scheduled time every day', zh: '每天在指定时间自动备份所有在线设备的配置' },
  scheduleHour: { en: 'Hour', zh: '小时' },
  scheduleMinute: { en: 'Minute', zh: '分钟' },
  nextBackupAt: { en: 'Next backup at', zh: '下次备份时间' },
  saveSchedule: { en: 'Save Schedule', zh: '保存计划' },
  scheduleUpdated: { en: 'Schedule updated', zh: '备份计划已更新' },
  runBackupNow: { en: 'Run Backup Now', zh: '立即执行备份' },
  backupStarted: { en: 'Backup started for online devices', zh: '开始备份在线设备' },
  backupComplete: { en: 'Backup complete', zh: '备份完成' },
  devicesOnline: { en: 'online', zh: '台在线' },
  backupStats: { en: 'Backup Statistics', zh: '备份统计' },
  backupStoragePath: { en: 'Storage Path', zh: '存储路径' },
  backupPathHint: { en: 'Config files are saved to the filesystem and persist across restarts. Organized by year/month/vendor/hostname.', zh: '配置文件保存至文件系统，重启后不丢失，按年/月/厂商/设备分类存放。' },
  retentionHint: { en: 'Snapshots older than this period will be pruned automatically', zh: '超过保留期的快照将自动清理' },

  // Automation — Playbooks & Scenarios
  directExecution: { en: 'Task Runner', zh: '任务执行' },
  scenarioLibrary: { en: 'Scenario Library', zh: '场景库' },
  scenarioLibraryDesc: { en: 'Built-in playbook templates for common network operations', zh: '常见网络运维场景的内置 Playbook 模板' },
  executionHistoryDesc: { en: 'View automation execution logs and history', zh: '查看自动化任务执行历史日志' },
  playbookDesc: { en: 'Select a scenario, configure variables, and execute across multiple devices', zh: '选择场景、配置参数，在多台设备上批量执行' },
  chooseScenario: { en: 'Choose Scenario', zh: '选择场景' },
  targetDevices: { en: 'Target Devices', zh: '目标设备' },
  devicesSelected: { en: 'devices selected', zh: '台设备已选' },
  concurrency: { en: 'Concurrency', zh: '并行数' },
  previewCommands: { en: 'Preview', zh: '预览命令' },
  commandPreview: { en: 'Command Preview', zh: '命令预览' },
  dryRunExecute: { en: 'Dry-Run Execute', zh: '模拟执行' },
  executeNow: { en: 'Execute Now', zh: '立即执行' },
  selectScenarioHint: { en: 'Select a scenario from the left panel to get started', zh: '从左侧面板选择一个场景开始' },
  previewHint: { en: 'Click "Preview" to see rendered commands', zh: '点击「预览命令」查看渲染后的命令' },
  useScenario: { en: 'Use This', zh: '使用此场景' },
  liveExecution: { en: 'Live Execution', zh: '实时执行' },
  running: { en: 'RUNNING', zh: '执行中' },
  executions: { en: 'executions', zh: '次执行' },
  noExecutions: { en: 'No executions yet', zh: '暂无执行记录' },
  selectExecutionHint: { en: 'Select an execution from the left to view details', zh: '从左侧选择一条执行记录查看详情' },
  noData: { en: 'No data', zh: '无数据' },
  selectPlatform: { en: 'Select Platform', zh: '选择平台' },
  platformsSupported: { en: 'platforms supported', zh: '个平台支持' },

  // Compliance

  complianceStandards: { en: 'Compliance & Standards', zh: '合规与标准' },
  auditGolden: { en: 'Audit your network against Golden Config templates.', zh: '根据黄金配置模板审计您的网络。' },
  complianceScore: { en: 'Compliance Score', zh: '合规评分' },
  nonCompliant: { en: 'Non-Compliant Devices', zh: '违规设备' },
  remediate: { en: 'Remediate', zh: '修复' },
  autoRemediation: { en: 'Auto-Remediation', zh: '自动修复' },
  remediationDesc: { en: 'The following actions will be taken to bring this device back into compliance with the Golden Config.', zh: '将采取以下操作使该设备恢复符合黄金配置。' },
  proposedActions: { en: 'Proposed Actions', zh: '建议操作' },
  startRemediation: { en: 'Start Remediation', zh: '开始修复' },

  // Audit Logs
  auditLogsTitle: { en: 'Audit Logs', zh: '审计日志' },
  fullHistory: { en: 'Full history of all system and user actions.', zh: '系统和用户操作的完整历史记录。' },
  timestamp: { en: 'Timestamp', zh: '时间戳' },
  action: { en: 'Action', zh: '操作' },
  target: { en: 'Target', zh: '目标' },
  userManagement: { en: 'User Management', zh: '用户管理' },
  manageAccess: { en: 'Manage system access and roles', zh: '管理系统访问权限和角色' },
  addUser: { en: 'Add User', zh: '添加用户' },
  lastLogin: { en: 'Last Login', zh: '最后登录' },
  userCreated: { en: 'User created successfully.', zh: '用户创建成功。' },
  addNewUser: { en: 'Add New User', zh: '添加新用户' },
  create: { en: 'Create', zh: '创建' },
  edit: { en: 'Edit', zh: '编辑' },
  user: { en: 'User', zh: '用户' },

  // Auth
  welcomeBack: { en: 'Welcome back', zh: '欢迎回来' },
  createAccount: { en: 'Create account', zh: '创建账户' },
  enterCredentials: { en: 'Enter your credentials to access the console', zh: '输入您的凭据以访问控制台' },
  startManaging: { en: 'Start managing your network infrastructure', zh: '开始管理您的网络基础设施' },
  username: { en: 'Username', zh: '用户名' },
  password: { en: 'Password', zh: '密码' },
  login: { en: 'Login', zh: '登录' },
  register: { en: 'Register', zh: '注册' },
  noAccount: { en: "Don't have an account?", zh: '还没有账户？' },
  haveAccount: { en: 'Already have an account?', zh: '已经有账户了？' },

  // Modals
  importInventory: { en: 'Import Inventory', zh: '导入资产' },
  importDesc: { en: 'Upload a JSON or CSV file to bulk import network devices. Use our standard template for best results.', zh: '上传 JSON 或 CSV 文件以批量导入网络设备。使用我们的标准模板以获得最佳效果。' },
  clickToUpload: { en: 'Click to upload or drag and drop', zh: '点击上传或拖拽文件' },
  downloadTemplate: { en: 'Download Template', zh: '下载模板' },
  getStandardCsv: { en: 'Get the standard CSV format for imports.', zh: '获取导入的标准 CSV 格式。' },
  cancel: { en: 'Cancel', zh: '取消' },
  startImport: { en: 'Start Import', zh: '开始导入' },
  configChangeReview: { en: 'Configuration Change Review', zh: '配置变更审核' },
  reviewDiff: { en: 'Review the differences before committing to', zh: '在提交到以下设备前查看差异：' },
  proposedChange: { en: 'Proposed Change', zh: '建议变更' },
  commitDeploy: { en: 'Commit & Deploy', zh: '提交并部署' },
  selectDeviceToStart: { en: 'Select a device to start automation', zh: '选择设备以开始自动化' },
};

interface I18nContextProps {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nContextProps | undefined>(undefined);

const STORAGE_KEY = 'netops_preferred_language';

export const I18nProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [language, setLangState] = useState<Language>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'zh' || saved === 'en') {
      return saved;
    }
    const navLang = navigator.language || navigator.languages?.[0];
    return navLang?.toLowerCase().startsWith('zh') ? 'zh' : 'en';
  });

  const setLanguage = (lang: Language) => {
    setLangState(lang);
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {
      console.warn('Failed to save language to localStorage:', e);
    }
  };

  const t = (key: string) => {
    return translations[key]?.[language] || key;
  };

  return (
    <I18nContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </I18nContext.Provider>
  );
};

export const useI18n = () => {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return context;
};
