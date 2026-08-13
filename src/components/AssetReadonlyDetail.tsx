/**
 * Read-only asset detail (badges + field grid) shared by Asset Management drawer
 * and Rack Management device drawer — keep labels and layout in sync.
 */
import React from 'react';
import { Server, Router, Shield } from 'lucide-react';

const LIFECYCLE_STATUSES = [
  { value: 'staging', label: { zh: '待投产', en: 'Staging' } },
  { value: 'production', label: { zh: '已投产', en: 'Production' } },
  { value: 'maintenance', label: { zh: '维护中', en: 'Maintenance' } },
  { value: 'decommissioned', label: { zh: '已退役', en: 'Decommissioned' } },
] as const;

const STATUSES = [
  { value: 'active', label: { zh: '在用', en: 'In Use' }, dot: 'bg-emerald-500', badge: 'bg-emerald-50 text-emerald-700' },
  { value: 'inactive', label: { zh: '闲置', en: 'Idle' }, dot: 'bg-sky-400', badge: 'bg-sky-50 text-sky-600' },
  { value: 'in_storage', label: { zh: '库存中', en: 'In Storage' }, dot: 'bg-blue-400', badge: 'bg-blue-50 text-blue-600' },
  { value: 'maintenance', label: { zh: '维护中', en: 'Maintenance' }, dot: 'bg-amber-500', badge: 'bg-amber-50 text-amber-700' },
  { value: 'decommissioned', label: { zh: '已退役', en: 'Retired' }, dot: 'bg-slate-400', badge: 'bg-slate-100 text-slate-500' },
] as const;

export interface AssetRecord {
  id: string;
  asset_type: string;
  asset_tag: string;
  serial_number: string;
  vendor: string;
  model: string;
  hostname: string;
  site_id: string;
  site_name?: string;
  site_code?: string;
  rack: string;
  rack_unit: string;
  u_height?: number;
  planned_start_u?: number | null;
  management_ip: string;
  connection_method?: string;
  management_port?: number;
  web_profiles?: Array<{ scheme: 'http' | 'https'; port: number | string; enabled: boolean }>;
  business_ip: string;
  device_role: string;
  vlan: string;
  uplink_switch: string;
  uplink_port: string;
  status: string;
  lifecycle_status: string;
  purchase_date: string;
  warranty_expiry: string;
  department: string;
  notes: string;
  created_at: string;
  updated_at: string;
  device_category?: string;
  power_watts?: number | string;
}

export const CATEGORY_MAP: Record<string, { zh: string; en: string }> = {
  // Network
  switch: { zh: '交换机', en: 'Switch' },
  router: { zh: '路由器', en: 'Router' },
  firewall: { zh: '防火墙', en: 'Firewall' },
  load_balancer: { zh: '负载均衡', en: 'Load Balancer' },
  wireless_ap: { zh: '无线 AP', en: 'Wireless AP' },
  // Server
  rack_server: { zh: '机架式服务器', en: 'Rack Server' },
  blade_server: { zh: '刀片服务器', en: 'Blade Server' },
  tower_server: { zh: '塔式服务器', en: 'Tower Server' },
  high_density: { zh: '高密度服务器', en: 'High-Density Server' },
  gpu_server: { zh: 'GPU 服务器', en: 'GPU Server' },
  storage_server: { zh: '存储服务器', en: 'Storage Server' },
  virtual_host: { zh: '虚拟/物理宿主机', en: 'Virtual Host' },
  // Shared
  other: { zh: '其他', en: 'Other' },
};

function statusMeta(v: string) {
  return STATUSES.find(s => s.value === v) || STATUSES[3];
}

function ago(iso: string) {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo`;
}

function ReadonlyField({ label, value, mono, warn }: { label: string; value: string; mono?: boolean; warn?: boolean }) {
  return (
    <div>
      <label className="block text-[10px] text-black/30 mb-0.5">{label}</label>
      <div className={`w-full border border-black/8 rounded-lg px-2.5 py-1.5 text-xs bg-black/[0.01] min-h-[30px] flex items-center ${warn ? 'text-amber-600 font-bold' : 'text-black/65'} ${mono ? 'font-mono' : ''}`}>
        {value}
      </div>
    </div>
  );
}

/** Badges + grid only (no header) — use inside themed drawers. */
export function AssetReadonlyDetailInner({ asset: a, zh }: { asset: AssetRecord; zh: boolean }) {
  const sm = statusMeta(a.status);
  const TypeIcon = a.asset_type === 'server' ? Server : Router;
  const typeLabel = a.asset_type === 'server' ? (zh ? '服务器' : 'Server') : (zh ? '网络设备' : 'Network');
  const typeCls = a.asset_type === 'server' ? 'bg-violet-50 text-violet-600 border-violet-200' : 'bg-cyan-50 text-cyan-600 border-cyan-200';
  const managementMethods = [
    ...(!['web', 'none'].includes(String(a.connection_method || 'ssh').toLowerCase())
      ? [`${String(a.connection_method || 'ssh').toUpperCase()}:${a.management_port ?? 22}`]
      : []),
    ...(a.web_profiles || []).filter(profile => profile.enabled).map(profile => `${profile.scheme.toUpperCase()}:${profile.port}`),
  ];

  return (
    <>
      <div className="flex gap-2 mb-4 flex-wrap">
        <span className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border ${typeCls}`}>
          <TypeIcon size={13} />{typeLabel}
        </span>
        <span className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border ${sm.badge}`}>
          <span className={`h-2 w-2 rounded-full ${sm.dot}`} />{sm.label[zh ? 'zh' : 'en']}
        </span>
        <span className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border ${
          a.lifecycle_status === 'production' ? 'bg-emerald-50 text-emerald-600 border-emerald-200' :
          a.lifecycle_status === 'decommissioned' ? 'bg-slate-50 text-slate-400 border-slate-200' :
          a.lifecycle_status === 'maintenance' ? 'bg-amber-50 text-amber-600 border-amber-200' :
          'bg-blue-50 text-blue-500 border-blue-200'
        }`}>
          {a.lifecycle_status === 'production' && <Shield size={12} />}
          {LIFECYCLE_STATUSES.find(l => l.value === a.lifecycle_status)?.label[zh ? 'zh' : 'en'] || (zh ? '待投产' : 'Staging')}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
        <ReadonlyField label={zh ? '厂商' : 'Vendor'} value={a.vendor || '—'} />
        <ReadonlyField label={zh ? '型号' : 'Model'} value={a.model || '—'} />
        <ReadonlyField label={zh ? '资产编号' : 'Asset Tag'} value={a.asset_tag || '—'} />
        <ReadonlyField label={zh ? '序列号' : 'Serial No.'} value={a.serial_number || '—'} />
        <ReadonlyField label={zh ? '设备分类' : 'Category'} value={CATEGORY_MAP[a.device_category || '']?.[zh ? 'zh' : 'en'] || (a.device_category || '—')} />
        <ReadonlyField label={zh ? '额定功率' : 'Power (W)'} value={a.power_watts != null && String(a.power_watts) !== '0' && String(a.power_watts) !== '' ? `${a.power_watts} W` : '—'} />
        <ReadonlyField label={zh ? '管理IP' : 'Mgmt IP'} value={a.management_ip || '—'} mono />
        <ReadonlyField label={zh ? '管理方式' : 'Management methods'} value={managementMethods.join('、') || (zh ? '无登录通道' : 'No login channel')} mono />
        {a.asset_type === 'server' && (
          <ReadonlyField label={zh ? '业务IP' : 'Biz IP'} value={a.business_ip || '—'} mono />
        )}
        {a.asset_type === 'server' && (
          <ReadonlyField label="VLAN" value={a.vlan || '—'} />
        )}
        {a.asset_type === 'server' && (
          <ReadonlyField label={zh ? '上联交换机' : 'Uplink Switch'} value={a.uplink_switch || '—'} />
        )}
        {a.asset_type === 'server' && (
          <ReadonlyField label={zh ? '上联端口' : 'Uplink Port'} value={a.uplink_port || '—'} mono />
        )}
        <ReadonlyField label={zh ? '站点' : 'Site'} value={a.site_name || a.site_code || a.site_id || '—'} />
        <ReadonlyField label={zh ? '机柜' : 'Rack'} value={a.rack || '—'} />
        <ReadonlyField label={zh ? '设备高度(U)' : 'Height (U)'} value={a.u_height != null ? String(a.u_height) : '—'} />
        <ReadonlyField label={zh ? '计划起始U' : 'Planned start U'} value={a.planned_start_u != null ? String(a.planned_start_u) : '—'} />
        <ReadonlyField label={zh ? '机位备注' : 'Loc. note'} value={a.rack_unit || '—'} />
        <ReadonlyField label={zh ? '角色' : 'Role'} value={a.device_role || '—'} />
        <ReadonlyField label={zh ? '部门/业务' : 'Dept'} value={a.department || '—'} />
        <ReadonlyField label={zh ? '购买日期' : 'Purchased'} value={a.purchase_date || '—'} />
        <ReadonlyField label={zh ? '保修到期' : 'Warranty'} value={a.warranty_expiry || '—'} warn={!!(a.warranty_expiry && new Date(a.warranty_expiry) <= new Date(Date.now() + 90 * 86400000))} />
        <ReadonlyField label={zh ? '最后更新' : 'Updated'} value={ago(a.updated_at)} />
        {a.notes && (
          <div className="col-span-2">
            <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '备注' : 'Notes'}</label>
            <div className="w-full border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/55 bg-black/[0.01] leading-relaxed">{a.notes}</div>
          </div>
        )}
      </div>
    </>
  );
}

export function normalizeAssetApiRow(row: Record<string, unknown>): AssetRecord {
  const s = (k: string, d = '') => (row[k] != null && row[k] !== undefined ? String(row[k]) : d);
  const n = (k: string): number | undefined => {
    const v = row[k];
    if (v == null || v === '') return undefined;
    const x = typeof v === 'number' ? v : parseInt(String(v), 10);
    return Number.isNaN(x) ? undefined : x;
  };
  const ni = (k: string): number | null | undefined => {
    const v = row[k];
    if (v == null || v === '') return null;
    const x = typeof v === 'number' ? v : parseInt(String(v), 10);
    return Number.isNaN(x) ? null : x;
  };
  return {
    id: s('id'),
    asset_type: s('asset_type', 'network_device'),
    asset_tag: s('asset_tag'),
    serial_number: s('serial_number'),
    vendor: s('vendor'),
    model: s('model'),
    hostname: s('hostname'),
    site_id: s('site_id'),
    site_name: s('site_name'),
    site_code: s('site_code'),
    rack: s('rack'),
    rack_unit: s('rack_unit'),
    u_height: n('u_height'),
    planned_start_u: ni('planned_start_u') as number | null | undefined,
    management_ip: s('management_ip'),
    connection_method: s('connection_method', 'ssh'),
    management_port: n('management_port'),
    web_profiles: Array.isArray(row['web_profiles']) ? row['web_profiles'] as AssetRecord['web_profiles'] : [],
    business_ip: s('business_ip'),
    device_role: s('device_role'),
    vlan: s('vlan'),
    uplink_switch: s('uplink_switch'),
    uplink_port: s('uplink_port'),
    status: s('status', 'active'),
    lifecycle_status: s('lifecycle_status', 'staging'),
    purchase_date: s('purchase_date'),
    warranty_expiry: s('warranty_expiry'),
    department: s('department'),
    notes: s('notes'),
    created_at: s('created_at'),
    updated_at: s('updated_at'),
    device_category: s('device_category'),
    power_watts: row['power_watts'] != null ? String(row['power_watts']) : '',
  };
}
