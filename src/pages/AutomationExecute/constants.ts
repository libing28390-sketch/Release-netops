import { Server, Zap, FileText, Terminal } from 'lucide-react';
import type { StepId } from './types';

export const VENDOR_MAP: Record<string, string> = {
  cisco_ios: 'Cisco',
  cisco_nxos: 'Cisco',
  cisco_iosxe: 'Cisco',
  huawei_vrp: 'Huawei',
  h3c_comware: 'H3C',
  arista_eos: 'Arista',
  juniper_junos: 'Juniper',
};

export const CATEGORY_META: Record<string, { label: string; labelEn: string; icon: string; color: string }> = {
  L2: { label: '二层网络', labelEn: 'L2 Network', icon: '🔗', color: 'text-cyan-600' },
  L3: { label: '三层路由', labelEn: 'L3 Routing', icon: '🗺️', color: 'text-violet-600' },
  Security: { label: '安全策略', labelEn: 'Security', icon: '🛡️', color: 'text-rose-600' },
  Operations: { label: '运维工具', labelEn: 'Operations', icon: '🔧', color: 'text-amber-600' },
  Custom: { label: '自定义', labelEn: 'Custom', icon: '⭐', color: 'text-cyan-600' },
};

export const RISK_CONFIG = {
  high: { label: '高危', labelEn: 'HIGH', bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', dot: 'bg-red-500', stripe: 'border-l-red-500', glow: 'shadow-red-500/10' },
  medium: { label: '中等', labelEn: 'MED', bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', dot: 'bg-amber-500', stripe: 'border-l-amber-400', glow: 'shadow-amber-500/10' },
  low: { label: '低风', labelEn: 'LOW', bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-500', stripe: 'border-l-emerald-400', glow: 'shadow-emerald-500/10' },
};

export const VAR_GROUP_ORDER = ['address', 'interface', 'routing', 'general'];

export const STEPS = [
  { id: 1 as StepId, label: '选择设备', labelEn: 'Select Devices', icon: Server },
  { id: 2 as StepId, label: '选择任务', labelEn: 'Select Task', icon: Zap },
  { id: 3 as StepId, label: '参数配置', labelEn: 'Configure', icon: FileText },
  { id: 4 as StepId, label: '执行结果', labelEn: 'Execute', icon: Terminal },
];

export const DEVICE_PAGE_SIZE = 10;
