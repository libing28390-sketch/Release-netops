import { Database, Activity, Zap } from 'lucide-react';
import type { FormState } from './types';

export const ACTION_TYPES = [
  { value: 'backup', labelZh: '核心配置备份', labelEn: 'Config Backup', icon: Database, category: 'collection' },
  { value: 'inspection', labelZh: '智能巡检', labelEn: 'Smart Inspection', icon: Activity, category: 'collection' },
  { value: 'script_run', labelZh: '自动化脚本', labelEn: 'Automated Script', icon: Zap, category: 'change' },
];

export const MAJOR_CATEGORIES = [
  { value: 'collection', labelZh: '采集与巡检', labelEn: 'Collection & Inspection', icon: Database },
  { value: 'change', labelZh: '自动化变更', labelEn: 'Automation Change', icon: Zap },
];

export const SCOPE_OPTIONS = [
  { value: 'all', labelZh: '全部在线设备', labelEn: 'All online devices' },
  { value: 'ip', labelZh: '按 IP 地址', labelEn: 'By IP address' },
  { value: 'tag', labelZh: '按标签', labelEn: 'By tag' },
  { value: 'site', labelZh: '按站点', labelEn: 'By site' },
  { value: 'role', labelZh: '按角色', labelEn: 'By role' },
];

export const INITIAL_FORM: FormState = {
  name: '',
  action_type: 'backup',
  scheduled_at: '',
  device_scope: 'all',
  device_filter: '',
  commands: '',
  script_id: '',
  is_config: false,
  config_reason: '',
  use_admin_creds: false,
  major_type: 'collection',
  check_items: [],
  description: '',
};
