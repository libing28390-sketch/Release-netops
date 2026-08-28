import { Database, Activity, Zap, RefreshCw } from 'lucide-react';
import { FormState } from './types';

export const CRON_PRESETS = [
  { label: '每天 02:00', labelEn: 'Daily at 02:00', cron: '0 2 * * *' },
  { label: '每天 06:00', labelEn: 'Daily at 06:00', cron: '0 6 * * *' },
  { label: '每天 22:00', labelEn: 'Daily at 22:00', cron: '0 22 * * *' },
  { label: '每12小时', labelEn: 'Every 12 hours', cron: '0 */12 * * *' },
  { label: '每6小时', labelEn: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: '每小时', labelEn: 'Every hour', cron: '0 * * * *' },
  { label: '工作日 08:00', labelEn: 'Weekdays at 08:00', cron: '0 8 * * 1-5' },
  { label: '每周一 03:00', labelEn: 'Mon at 03:00', cron: '0 3 * * 1' },
  { label: '每月1日 02:00', labelEn: '1st of month at 02:00', cron: '0 2 1 * *' },
];

export const CRON_FIELD_LABELS_ZH = ['分钟', '小时', '日', '月', '星期'];
export const CRON_FIELD_LABELS_EN = ['Minute', 'Hour', 'Day', 'Month', 'Weekday'];
export const CRON_FIELD_HINTS_ZH = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6, 1-5'];
export const CRON_FIELD_HINTS_EN = ['0-59, */5, 0,30', '0-23, */2, 0-6', '1-31, */2', '1-12, */3', '0-6 (Sun=0), 1-5'];

export const ACTION_TYPES = [
  { value: 'backup', labelZh: '核心配置备份', labelEn: 'Config Backup', icon: Database, category: 'collection' },
  { value: 'nsot', labelZh: 'NSOT 事实库采集', labelEn: 'NSOT Facts Collection', icon: RefreshCw, category: 'collection' },
  { value: 'inspection', labelZh: '智能巡检', labelEn: 'Smart Inspection', icon: Activity, category: 'collection' },
  { value: 'script_run', labelZh: '自动化脚本', labelEn: 'Automated Script', icon: Zap, category: 'change' },
];

export const MAJOR_CATEGORIES = [
  { value: 'collection', labelZh: '采集与巡检', labelEn: 'Collection & Inspection', icon: Database },
  { value: 'change', labelZh: '自动化变更', labelEn: 'Automation Change', icon: Zap },
];

export const SCOPE_OPTIONS = [
  { value: 'all', labelZh: '全部在线设备', labelEn: 'All online devices' },
  { value: 'composite', labelZh: '资产复合筛选 (站点/角色/类型)', labelEn: 'Asset Matrix (Site / Role / Category)' },
  { value: 'tag', labelZh: '业务逻辑标签 (Tag Conditions)', labelEn: 'Business Tags (Tag Conditions)' },
  { value: 'ip', labelZh: '指定 IP / 设备清单', labelEn: 'Specific IPs / Device List' },
  { value: 'site', labelZh: '按单个站点 (Site)', labelEn: 'By Single Site' },
  { value: 'role', labelZh: '按单个角色 (Role)', labelEn: 'By Single Role' },
];

export const INITIAL_FORM: FormState = {
  name: '',
  action_type: 'backup',
  cron_expr: '0 2 * * *',
  device_scope: 'all',
  device_filter: '',
  commands: '',
  script_id: '',
  is_config: false,
  config_reason: '',
  use_admin_creds: false,
  major_type: 'collection',
};
