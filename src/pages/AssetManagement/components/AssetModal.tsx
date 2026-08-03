import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Terminal, Shield, Lock, Wifi, Network, Building2, AlertCircle, AlertTriangle, Eye, EyeOff, X } from 'lucide-react';
import DateTimePicker from '../../../components/DateTimePicker';
import { Asset } from '../types';
import type { TagDefinition } from '../../../types';
import { VENDOR_PLATFORMS, SERVER_PLATFORMS, ALL_PLATFORMS, getPlatformsForVendor, STATUSES, LIFECYCLE_STATUSES } from '../constants';
import { AssetTagPicker } from './AssetTagPicker';
import { isReservedSystemSite } from '../../../utils/siteIdentity';

const TOPOLOGY_ROLE_OPTIONS = [
  { value: 'core', label: { zh: '核心层', en: 'Core' } },
  { value: 'distribution', label: { zh: '汇聚层', en: 'Distribution' } },
  { value: 'access', label: { zh: '接入层', en: 'Access' } },
  { value: 'edge', label: { zh: '边缘层', en: 'Edge' } },
  { value: 'switch', label: { zh: '通用交换机', en: 'Switch' } },
  { value: 'router', label: { zh: '路由器', en: 'Router' } },
  { value: 'firewall', label: { zh: '防火墙', en: 'Firewall' } },
  { value: 'other', label: { zh: '其他', en: 'Other' } },
] as const;

interface AssetModalProps {
  isOpen: boolean;
  onClose: () => void;
  isEditMode: boolean;
  editingAsset: Asset | null;
  form: any;
  setForm: React.Dispatch<React.SetStateAction<any>>;
  saving: boolean;
  modalError: string | null;
  setModalError: (val: string | null) => void;
  showEnableSecret: boolean;
  setShowEnableSecret: React.Dispatch<React.SetStateAction<boolean>>;
  showProductionConfirm: boolean;
  setShowProductionConfirm: (val: boolean) => void;
  handleSave: () => void;
  doSave: (overrides?: Record<string, unknown>) => void;
  language: string;
  setFeedbackMsg: (msg: any) => void;
  allTags: TagDefinition[];
}

export const AssetModal: React.FC<AssetModalProps> = ({
  isOpen,
  onClose,
  isEditMode,
  editingAsset,
  form,
  setForm,
  saving,
  modalError,
  setModalError,
  showEnableSecret,
  setShowEnableSecret,
  showProductionConfirm,
  setShowProductionConfirm,
  handleSave,
  doSave,
  language,
  setFeedbackMsg,
  allTags,
}) => {
  const zh = language === 'zh';

  const [racks, setRacks] = React.useState<any[]>([]);
  const [sites, setSites] = React.useState<any[]>([]);
  const [uValidationError, setUValidationError] = React.useState<string | null>(null);
  const [legacyExemptReason, setLegacyExemptReason] = React.useState('');
  const [credentials, setCredentials] = React.useState<any[]>([]);
  const [credMode, setCredMode] = React.useState<'manual' | 'existing'>('manual');

  React.useEffect(() => {
    if (isOpen) {
      setCredMode(form.credential_id ? 'existing' : 'manual');
    }
  }, [isOpen, form.credential_id]);

  React.useEffect(() => {
    if (isOpen) {
      const token = localStorage.getItem('netops_token');
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      Promise.all([
        fetch('/api/racks', { headers }).then(res => res.json()),
        fetch('/api/cmdb/sites', { headers }).then(res => res.json()),
        fetch('/api/credentials', { headers }).then(res => res.json()),
      ])
      .then(([rackData, siteData, credData]) => {
        if (rackData && rackData.success && Array.isArray(rackData.data)) {
          setRacks(rackData.data);
        }
        if (siteData && siteData.success && Array.isArray(siteData.data)) {
          setSites(siteData.data);
        }
        if (credData && credData.success && Array.isArray(credData.data)) {
          setCredentials(credData.data);
        }
      })
      .catch(err => console.error('Failed to load asset location data:', err));
    }
  }, [isOpen]);

  const filteredRacks = React.useMemo(() => {
    if (!form.site_id) {
      return Array.from(new Set(racks.map(r => r.name))).filter(Boolean).sort();
    }
    return racks
      .filter(r => r.site_id === form.site_id)
      .map(r => r.name)
      .filter(Boolean)
      .sort();
  }, [racks, form.site_id]);

  const businessSites = React.useMemo(
    () => sites.filter(site => !isReservedSystemSite(site)),
    [sites],
  );

  const normalCredentials = React.useMemo(
    () => credentials.filter(c => c.id === form.credential_id || (!String(c.credential_type || '').toLowerCase().startsWith('snmp') && ['normal', 'shared', 'mixed', 'login'].includes(String(c.account_role || '').toLowerCase()))),
    [credentials, form.credential_id],
  );
  const adminCredentials = React.useMemo(
    () => credentials.filter(c => c.id === form.admin_credential_id || (!String(c.credential_type || '').toLowerCase().startsWith('snmp') && ['admin', 'shared', 'mixed', 'login'].includes(String(c.account_role || '').toLowerCase()))),
    [credentials, form.admin_credential_id],
  );
  const snmpCredentials = React.useMemo(
    () => credentials.filter(c => c.id === form.snmp_credential_id || String(c.credential_type || '').toLowerCase() === 'snmpv2'),
    [credentials, form.snmp_credential_id],
  );
  const selectedSnmpCredential = snmpCredentials.find(c => c.id === form.snmp_credential_id);
  const snmpCommunityConfigured = Boolean(form.snmp_community_set || selectedSnmpCredential?.has_snmp_community);

  const withTechnologyTag = (next: any, vendor: string, platform: string) => {
    let targetPlatform = platform;
    if ((vendor === 'DPtech' || vendor === 'DPTech' || vendor === '迪普') && !['dptech_conplat', 'dptech_conplat_fw'].includes(platform)) {
      const isFw = String(next.device_role || '').toLowerCase().includes('firewall') || String(next.device_role || '').includes('防火墙');
      targetPlatform = isFw ? 'dptech_conplat_fw' : 'dptech_conplat';
    }
    const vendorCode = vendor ? `vendor.${vendor.toLowerCase().replace(/\s+/g, '').replace('paloalto', 'paloalto')}` : '';
    const effectivePlatform = next.asset_type === 'network_device' ? targetPlatform : next.platform;
    const platformCode = effectivePlatform ? `platform.${effectivePlatform}` : '';
    const vendorTag = allTags.find(tag => tag.code === vendorCode && tag.exclusive_group === 'technology.vendor');
    const platformTag = allTags.find(tag => tag.code === platformCode && tag.exclusive_group === 'technology.platform');
    const ids = Array.isArray(next.tag_ids) ? next.tag_ids : [];
    const withoutTechnology = ids.filter((id: string) => {
      const tag = allTags.find(item => item.id === id);
      return !tag?.exclusive_group?.startsWith('technology.');
    });
    return { ...next, platform: targetPlatform, tag_ids: [...withoutTechnology, ...(vendorTag ? [vendorTag.id] : []), ...(platformTag ? [platformTag.id] : [])] };
  };

  // Real-time U-position validation
  React.useEffect(() => {
    const rack = form.rack;
    const startU = parseInt(String(form.planned_start_u), 10);
    const height = parseInt(String(form.u_height), 10);

    if (!rack || Number.isNaN(startU) || startU < 1 || Number.isNaN(height) || height < 1) {
      setUValidationError(null);
      return;
    }

    const validate = async () => {
      try {
        const token = localStorage.getItem('netops_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const url = `/api/racks/validate-u?rack=${encodeURIComponent(rack)}&start_u=${startU}&u_height=${height}&exclude_asset_id=${editingAsset?.id || ''}`;
        const res = await fetch(url, { headers });
        if (res.ok) {
          const data = await res.json();
          if (!data.success) {
            setUValidationError(data.reason);
          } else {
            setUValidationError(null);
          }
        }
      } catch (err) {
        console.error("U validation failed", err);
      }
    };

    const timer = setTimeout(validate, 300);
    return () => clearTimeout(timer);
  }, [form.rack, form.planned_start_u, form.u_height, editingAsset]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      >
        <motion.div
          className="bg-white rounded-2xl w-[600px] max-w-[95vw] h-[85vh] shadow-2xl flex flex-col relative overflow-hidden border border-black/5"
          onClick={e => e.stopPropagation()}
          initial={{ scale: 0.98, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.98, opacity: 0 }}
        >
          {/* Header */}
          <div className="shrink-0 px-5 py-4 border-b border-black/5 flex items-center justify-between">
            <h3 className="text-sm font-bold text-black/85">
              {isEditMode ? (zh ? '编辑资产' : 'Edit Asset') : (zh ? '新增资产' : 'Add Asset')}
            </h3>
            <button onClick={onClose} className="p-1 rounded-md hover:bg-black/5 text-black/25">
              <X size={16} />
            </button>
          </div>

          {/* Scrollable body */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <div className="rounded-lg border border-cyan-100 bg-cyan-50/60 px-3 py-2 text-[10px] text-cyan-800">
              {zh ? '必填规则：主机名、资产编号至少填写一项。存量设备直接投产时，还必须填写普通账号、普通密码和免上收投产原因（至少 5 个字符）。' : 'Required: provide either Hostname or Asset Tag. Legacy devices created as production also require a normal username, normal password, and an exemption reason (minimum 5 characters).'}
            </div>
            {/* ─── 基本属性 ─── */}
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '资产类型' : 'Asset Type'}</label>
                <select
                  value={form.asset_type}
                  onChange={e => setForm(f => ({ ...f, asset_type: e.target.value }))}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                  title="Asset Type"
                >
                  <option value="server">{zh ? '服务器' : 'Server'}</option>
                  <option value="network_device">{zh ? '网络设备' : 'Network Device'}</option>
                </select>
              </div>
              <Field label={zh ? '主机名' : 'Hostname'} value={form.hostname} onChange={v => setForm(f => ({ ...f, hostname: v }))} placeholder="e.g. web-srv-01" />
              <Field label={zh ? '资产编号' : 'Asset Tag'} value={form.asset_tag} onChange={v => setForm(f => ({ ...f, asset_tag: v }))} placeholder="e.g. SRV-BJ-001" />
              <Field label={zh ? '序列号 (S/N)' : 'Serial Number'} value={form.serial_number} onChange={v => setForm(f => ({ ...f, serial_number: v }))} />
              
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '厂商' : 'Vendor'}</label>
                {form.asset_type === 'server' ? (
                  <select
                    value={form.vendor}
                    onChange={e => {
                      const vendor = e.target.value;
                      const platformOptions = VENDOR_PLATFORMS[vendor] || [];
                      setForm(f => withTechnologyTag({
                        ...f,
                        vendor,
                        model: f.vendor === vendor ? f.model : '',
                        platform: platformOptions.some(option => option.value === f.platform)
                          ? f.platform
                          : (platformOptions[0]?.value || ''),
                      }, vendor, f.platform));
                    }}
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                    title="Vendor"
                  >
                    <option value="">{zh ? '选择服务器厂商...' : 'Select vendor...'}</option>
                    <option value="Dell">Dell</option>
                    <option value="HP">HP</option>
                    <option value="Lenovo">Lenovo</option>
                    <option value="Huawei">Huawei</option>
                    <option value="Inspur">Inspur</option>
                    <option value="Generic Server">{zh ? '通用白牌/虚拟化' : 'Generic VM/Baremetal'}</option>
                  </select>
                ) : (
                  <select
                    value={form.vendor}
                    onChange={e => setForm(f => withTechnologyTag({ ...f, vendor: e.target.value }, e.target.value, f.platform))}
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                    title="Vendor"
                  >
                    <option value="">{zh ? '选择设备厂商...' : 'Select vendor...'}</option>
                    <option value="Cisco">Cisco</option>
                    <option value="Huawei">Huawei</option>
                    <option value="H3C">H3C</option>
                    <option value="Arista">Arista</option>
                    <option value="Juniper">Juniper</option>
                    <option value="Ruijie">Ruijie</option>
                    <option value="Maipu">Maipu</option>
                    <option value="DCN">DCN</option>
                    <option value="DPtech">DPtech</option>
                    <option value="FiberHome">FiberHome</option>
                    <option value="Fortinet">Fortinet</option>
                    <option value="Palo Alto">Palo Alto</option>
                    <option value="ZTE">ZTE</option>
                  </select>
                )}
              </div>
              <Field label={zh ? '型号' : 'Model'} value={form.model} onChange={v => setForm(f => ({ ...f, model: v }))} placeholder="e.g. PowerEdge R750" />
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '状态' : 'Status'}</label>
                <select
                  value={form.status}
                  onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
                  title="Status"
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                >
                  {STATUSES.map(s => (
                    <option key={s.value} value={s.value}>
                      {s.label[zh ? 'zh' : 'en']}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '投产状态' : 'Lifecycle'}</label>
                <select
                  value={form.lifecycle_status}
                  onChange={e => setForm(f => ({ ...f, lifecycle_status: e.target.value }))}
                  disabled={!isEditMode && form.asset_origin !== 'legacy'}
                  title="Lifecycle"
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                >
                  {LIFECYCLE_STATUSES.map(s => (
                    <option key={s.value} value={s.value}>
                      {s.label[zh ? 'zh' : 'en']}
                    </option>
                  ))}
                </select>
                {!isEditMode && form.asset_origin !== 'legacy' && <p className="mt-1 text-[9px] text-black/30">{zh ? '新设备统一以待投产状态入库' : 'New devices are always created in staging'}</p>}
              </div>
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '录入来源' : 'Asset Origin'}</label>
                <select
                  value={form.asset_origin || 'new'}
                  onChange={e => setForm(f => ({
                    ...f,
                    asset_origin: e.target.value,
                    lifecycle_status: e.target.value === 'legacy' ? f.lifecycle_status : 'staging',
                    takeover_exempt_reason: e.target.value === 'legacy' ? f.takeover_exempt_reason : '',
                  }))}
                  disabled={isEditMode}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 disabled:bg-black/[0.02] focus:outline-none focus:border-[#00bceb]/25"
                >
                  <option value="new">{zh ? '新设备录入' : 'New Device'}</option>
                  <option value="legacy">{zh ? '存量设备补录' : 'Legacy Device'}</option>
                </select>
                <p className="mt-1 text-[9px] text-black/30">
                  {zh ? '记录首次录入方式，投产后不会改变' : 'Records how the asset was first entered and does not change after production'}
                </p>
              </div>
              {!isEditMode && form.asset_origin === 'legacy' && form.lifecycle_status === 'production' && (
                <div className="col-span-2">
                  <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '免上收投产原因' : 'Takeover Exemption Reason'}</label>
                  <textarea
                    value={form.takeover_exempt_reason || ''}
                    onChange={e => setForm(f => ({ ...f, takeover_exempt_reason: e.target.value }))}
                    rows={2}
                    placeholder={zh ? '说明该存量设备暂不修改口令的原因，至少 5 个字符' : 'Explain why this legacy device will not rotate passwords yet'}
                    className="w-full resize-none rounded-lg border border-amber-200 bg-amber-50/40 px-2.5 py-2 text-xs text-black/65 outline-none focus:border-amber-400"
                  />
                </div>
              )}
              <Field label={zh ? '管理IP' : 'Mgmt IP'} value={form.management_ip} onChange={v => setForm(f => ({ ...f, management_ip: v }))} placeholder="e.g. 10.0.1.10" />
              <Field label={zh ? '端口 (SSH/Mgmt)' : 'Mgmt Port'} value={form.management_port} onChange={v => setForm(f => ({ ...f, management_port: v }))} placeholder="22" />
              
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '设备子类' : 'Device Sub-category'}</label>
                <select
                  value={form.device_category}
                  onChange={e => setForm(f => ({ ...f, device_category: e.target.value }))}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                  title="Device Sub-category"
                >
                  <option value="">{zh ? '选择子分类...' : 'Select category...'}</option>
                  {form.asset_type === 'server' ? (
                    <>
                      <option value="rack_server">{zh ? '机架式服务器' : 'Rack Server'}</option>
                      <option value="blade_server">{zh ? '刀片服务器' : 'Blade Server'}</option>
                      <option value="tower_server">{zh ? '塔式服务器' : 'Tower Server'}</option>
                      <option value="high_density">{zh ? '高密度服务器' : 'High-Density Server'}</option>
                      <option value="gpu_server">{zh ? 'GPU 服务器' : 'GPU Server'}</option>
                      <option value="storage_server">{zh ? '存储服务器' : 'Storage Server'}</option>
                      <option value="virtual_host">{zh ? '虚拟/物理宿主机' : 'Virtual Host'}</option>
                      <option value="other">{zh ? '其他' : 'Other'}</option>
                    </>
                  ) : (
                    <>
                      <option value="switch">{zh ? '交换机' : 'Switch'}</option>
                      <option value="router">{zh ? '路由器' : 'Router'}</option>
                      <option value="firewall">{zh ? '防火墙' : 'Firewall'}</option>
                      <option value="load_balancer">{zh ? '负载均衡' : 'Load Balancer'}</option>
                      <option value="wireless_ap">{zh ? '无线 AP' : 'Wireless AP'}</option>
                      <option value="other">{zh ? '其他' : 'Other'}</option>
                    </>
                  )}
                </select>
              </div>
              <Field label={zh ? '额定功率 (W)' : 'Power (W)'} value={form.power_watts} onChange={v => setForm(f => ({ ...f, power_watts: v }))} placeholder="e.g. 350" />
            </div>

            {/* ─── 连接配置 & PAM ─── */}
            {form.asset_type === 'network_device' && <div className="rounded-xl border border-cyan-100 bg-cyan-50/40 px-3 py-2.5">
              <label className="block text-[10px] font-semibold text-cyan-900/70">{zh ? '拓扑角色' : 'Topology Role'}</label>
              <select
                value={form.device_role || ''}
                onChange={e => setForm(f => ({ ...f, device_role: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-cyan-200 bg-white px-2.5 py-1.5 text-xs text-black/65 outline-none focus:border-cyan-400"
                title="Topology Role"
              >
                <option value="">{zh ? '请选择拓扑角色...' : 'Select topology role...'}</option>
                {TOPOLOGY_ROLE_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>{option.label[zh ? 'zh' : 'en']}</option>
                ))}
              </select>
              <p className="mt-1 text-[9px] text-cyan-900/50">{zh ? '用于拓扑图分层，不等同于接口的 access/trunk 模式。' : 'Controls topology layers; different from interface access/trunk mode.'}</p>
            </div>}

            {(form.asset_type === 'network_device' || form.asset_type === 'server') && (
              <div className="col-span-2 space-y-4">
                <div className="flex items-center gap-1.5 mt-4 mb-1">
                  <Terminal size={12} className="text-[#00bceb]/60" />
                  <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">{zh ? '连接与凭据' : 'Connection & Credentials'}</span>
                </div>
                
                <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                  <div>
                    <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '平台' : 'Platform'}</label>
                    <select
                      value={form.platform}
                      onChange={e => setForm(f => withTechnologyTag({ ...f, platform: e.target.value }, f.vendor, e.target.value))}
                      className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                      title="Platform"
                    >
                      {form.asset_type === 'server' ? (
                        SERVER_PLATFORMS.map(p => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))
                      ) : (
                        getPlatformsForVendor(form.vendor).map(p => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))
                      )}
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '连接方式' : 'Method'}</label>
                    <select
                      value={form.connection_method}
                      onChange={e => setForm(f => ({ ...f, connection_method: e.target.value }))}
                      className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                      title="Connection"
                    >
                      <option value="ssh">SSH</option>
                      <option value="netconf">NETCONF</option>
                    </select>
                  </div>
                </div>

                <AssetTagPicker tags={allTags} selectedIds={form.tag_ids || []} onChange={ids => setForm(f => ({ ...f, tag_ids: ids }))} onSave={handleSave} language={language} assetType={form.asset_type} />

                {/* PAM Toggle */}
                <div className="flex items-center justify-between p-2.5 rounded-xl bg-cyan-50 border border-cyan-200/60 mt-1">
                  <div className="flex items-center gap-2">
                    <Shield size={14} className="text-cyan-500" />
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-[10px] font-bold text-slate-700">{zh ? '多角色认证 (PAM)' : 'Multi-Role Auth (PAM)'}</p>
                        <span className="text-[8px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 font-bold border border-cyan-200">
                          {zh ? '强制启用' : 'Required'}
                        </span>
                        {editingAsset && (
                          <button
                            type="button"
                            onClick={async () => {
                              setModalError(null);
                              setFeedbackMsg({ type: 'info', text: zh ? '正在验证连通性...' : 'Verifying connectivity...' });
                              try {
                                const r = await fetch(`/api/assets/${editingAsset.id}/verify`);
                                const d = await r.json();
                                if (d.success || d.ssh) {
                                  setFeedbackMsg({ type: 'success', text: zh ? '✅ 验证通过！' : '✅ Verification success!' });
                                } else {
                                  const err = d.ssh_error || d.error || (zh ? '连接失败' : 'Connection failed');
                                  setModalError(`${zh ? '验证失败' : 'Verify failed'}: ${err}`);
                                  setFeedbackMsg({ type: 'error', text: zh ? '❌ 验证失败' : '❌ Verification failed' });
                                }
                              } catch (e) {
                                setModalError(String(e));
                              }
                            }}
                            className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 hover:bg-cyan-200 transition-colors"
                          >
                            {zh ? '测试连通性' : 'Test Connectivity'}
                          </button>
                        )}
                      </div>
                      <p className="text-[8px] text-slate-400">{zh ? '必须同时录入普通账户和管理员账户凭据，不允许单用户模式' : 'Both normal and admin credentials are required — single-user mode is not allowed'}</p>
                    </div>
                  </div>
                  <div className="p-1.5 rounded-full bg-cyan-100 text-cyan-600" title={zh ? 'PAM 双账户模式已强制启用' : 'PAM dual-account mode is enforced'}>
                    <Lock size={12} />
                  </div>
                </div>

                {/* Mode Selector */}
                <div className="flex gap-2 mb-2 p-1 bg-slate-100 rounded-lg text-[9px] font-bold">
                  <button
                    type="button"
                    onClick={() => {
                      setCredMode('manual');
                      setForm(f => ({ ...f, credential_id: '', admin_credential_id: '' }));
                    }}
                    className={`flex-1 py-1 rounded text-center transition-colors ${credMode === 'manual' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}
                  >
                    {zh ? '手动录入新凭据' : 'Manual Entry'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setCredMode('existing');
                    }}
                    className={`flex-1 py-1 rounded text-center transition-colors ${credMode === 'existing' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}
                  >
                    {zh ? '绑定已有凭据 (推荐)' : 'Select Existing'}
                  </button>
                </div>

                {credMode === 'existing' ? (
                  <div className="p-3 rounded-xl border border-black/5 bg-slate-50/30 space-y-2.5">
                    {form.auth_model === 'dual' ? (
                      <>
                        <div>
                          <label className="block text-[10px] font-bold text-black/50 mb-1">
                            {zh ? '选择普通账号凭据' : 'Select Normal Credential'}
                          </label>
                          <select
                            value={form.credential_id || ''}
                            onChange={e => {
                              const selectedId = e.target.value;
                              setForm(f => ({ ...f, credential_id: selectedId }));
                              const selected = credentials.find(c => c.id === selectedId);
                              if (selected) {
                                setForm(f => ({
                                  ...f,
                                  credential_id: selectedId,
                                  normal_username: selected.username || '',
                                }));
                              }
                            }}
                            className="w-full text-[10px] px-2.5 py-1.5 rounded-lg border border-black/8 bg-white focus:outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20"
                          >
                            <option value="">{zh ? '-- 请选择普通凭据 --' : '-- Select Normal Credential --'}</option>
                            {normalCredentials.map(c => (
                              <option key={c.id} value={c.id}>
                                {c.credential_name} ({c.username || 'no user'} - {c.credential_type})
                              </option>
                            ))}
                          </select>
                        </div>

                        <div>
                          <label className="block text-[10px] font-bold text-black/50 mb-1">
                            {zh ? '选择特权账号凭据' : 'Select Admin Credential'}
                          </label>
                          <select
                            value={form.admin_credential_id || ''}
                            onChange={e => {
                              const selectedId = e.target.value;
                              setForm(f => ({ ...f, admin_credential_id: selectedId }));
                              const selected = credentials.find(c => c.id === selectedId);
                              if (selected) {
                                setForm(f => ({
                                  ...f,
                                  admin_credential_id: selectedId,
                                  admin_username: selected.username || '',
                                }));
                              }
                            }}
                            className="w-full text-[10px] px-2.5 py-1.5 rounded-lg border border-black/8 bg-white focus:outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20"
                          >
                            <option value="">{zh ? '-- 请选择特权凭据 --' : '-- Select Admin Credential --'}</option>
                            {adminCredentials.map(c => (
                              <option key={c.id} value={c.id}>
                                {c.credential_name} ({c.username || 'no user'} - {c.credential_type})
                              </option>
                            ))}
                          </select>
                        </div>
                      </>
                    ) : (
                      <div>
                        <label className="block text-[10px] font-bold text-black/50 mb-1">
                          {zh ? '选择已有凭据' : 'Select Credential'}
                        </label>
                        <select
                          value={form.credential_id || ''}
                          onChange={e => {
                            const selectedId = e.target.value;
                            setForm(f => ({ ...f, credential_id: selectedId }));
                            const selected = credentials.find(c => c.id === selectedId);
                            if (selected) {
                              setForm(f => ({
                                ...f,
                                credential_id: selectedId,
                                normal_username: selected.username || '',
                                admin_username: selected.username || '',
                              }));
                            }
                          }}
                          className="w-full text-[10px] px-2.5 py-1.5 rounded-lg border border-black/8 bg-white focus:outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20"
                        >
                          <option value="">{zh ? '-- 请选择凭据 --' : '-- Select a Credential --'}</option>
                          {normalCredentials.map(c => (
                            <option key={c.id} value={c.id}>
                              {c.credential_name} ({c.username || 'no user'} - {c.credential_type})
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    {(form.credential_id || form.admin_credential_id) && (
                      <p className="text-[8px] text-emerald-600">
                        {zh ? '✓ 已成功选择并关联现有凭据' : '✓ Successfully linked to existing credential'}
                      </p>
                    )}
                  </div>
                ) : (
                  /* Dual-account credential inputs */
                  <div className="grid grid-cols-2 gap-3 p-3 rounded-xl border border-black/5 bg-slate-50/30">
                    <div className="space-y-2">
                      <p className="text-[9px] font-black uppercase tracking-widest text-blue-500">{zh ? '普通账户' : 'Normal Account'}</p>
                      <Field label={zh ? '用户名' : 'Username'} value={form.normal_username} onChange={v => setForm(f => ({ ...f, normal_username: v }))} placeholder="user" />
                      <PasswordField label={zh ? '密码' : 'Password'} value={form.normal_password} onChange={v => setForm(f => ({ ...f, normal_password: v }))} placeholder={editingAsset ? (zh ? '留空不变' : 'Leave empty to keep') : ''} />
                    </div>
                    <div className="space-y-2">
                      <p className="text-[9px] font-black uppercase tracking-widest text-orange-500">{zh ? '特权账户' : 'Admin Account'}</p>
                      <Field label={zh ? '用户名' : 'Username'} value={form.admin_username} onChange={v => setForm(f => ({ ...f, admin_username: v }))} placeholder={form.asset_type === 'network_device' ? 'admin' : 'root'} />
                      <PasswordField label={zh ? '密码' : 'Password'} value={form.admin_password} onChange={v => setForm(f => ({ ...f, admin_password: v }))} placeholder={editingAsset ? (zh ? '留空不变' : 'Leave empty to keep') : ''} />
                    </div>
                  </div>
                )}

                {/* Enable Secret */}
                {form.asset_type === 'network_device' && form.platform.startsWith('cisco') && (
                  <div className="rounded-xl border border-amber-100 bg-amber-50/40 overflow-hidden">
                    <button
                      type="button"
                      onClick={() => {
                        setShowEnableSecret(prev => {
                          const next = !prev;
                          if (!next) setForm(f => ({ ...f, enable_password: '' }));
                          return next;
                        });
                      }}
                      className="w-full flex items-center justify-between px-3 py-2 hover:bg-amber-50 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <Lock size={11} className="text-amber-500" />
                        <span className="text-[9px] font-black uppercase tracking-widest text-amber-600">
                          Enable Secret
                        </span>
                        <span className="text-[8px] text-amber-400/80">
                          {zh ? '（可选，无特权密码时请关闭或留空）' : '(optional — leave blank when the device has no enable secret)'}
                        </span>
                      </div>
                      <div className={`relative inline-flex h-3.5 w-7 items-center rounded-full transition-colors ${showEnableSecret ? 'bg-amber-400' : 'bg-slate-200'}`}>
                        <span className={`inline-block h-2.5 w-2.5 transform rounded-full bg-white transition-transform shadow-sm ${showEnableSecret ? 'translate-x-3.5' : 'translate-x-0.5'}`} />
                      </div>
                    </button>
                    {showEnableSecret && (
                      <div className="px-3 pb-2.5">
                        <PasswordField
                          label={zh ? '密码' : 'Password'}
                          value={form.enable_password}
                          onChange={v => setForm(f => ({ ...f, enable_password: v }))}
                          placeholder={editingAsset ? (zh ? '留空不变' : 'Leave empty to keep') : (zh ? '输入 enable secret' : 'Enter enable secret')}
                        />
                      </div>
                    )}
                  </div>
                )}

                {form.asset_type === 'network_device' && (
                  <>
                    <div className="flex items-center gap-1.5 mt-2 mb-1">
                      <Wifi size={12} className="text-[#00bceb]/60" />
                      <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">SNMP</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                      <div>
                        <Field label={zh ? '团体字' : 'Community'} value={form.snmp_community} onChange={v => setForm(f => ({ ...f, snmp_community: v }))} placeholder={snmpCommunityConfigured ? (zh ? '已安全存储，留空保持不变' : 'Configured; leave empty to keep') : (zh ? '可选' : 'Optional')} />
                        {snmpCommunityConfigured && <p className="mt-1 text-[8px] text-emerald-600">✓ {zh ? '已配置（不会回显明文）' : 'Configured (value is not revealed)'}</p>}
                      </div>
                      <Field label={zh ? '端口' : 'Port'} value={form.snmp_port} onChange={v => setForm(f => ({ ...f, snmp_port: v }))} placeholder="161" />
                      <div className="col-span-2">
                        <label className="block text-[10px] text-black/30 mb-0.5">{zh ? 'SNMP 凭据' : 'SNMP Credential'}</label>
                        <select
                          value={form.snmp_credential_id || ''}
                          onChange={e => setForm(f => ({ ...f, snmp_credential_id: e.target.value }))}
                          className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                        >
                          <option value="">{zh ? '使用资产本地 Community' : 'Use asset-local Community'}</option>
                          {snmpCredentials.map(c => (
                            <option key={c.id} value={c.id}>{c.credential_name} (SNMPv2c)</option>
                          ))}
                        </select>
                        <p className="mt-1 text-[8px] text-black/30">{zh ? '选择后使用凭据中心的 Community，不会替换 SSH 登录凭据。' : 'Uses the credential-center Community without replacing the SSH login credential.'}</p>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ─── 服务器: 网络接入 ─── */}
            {form.asset_type === 'server' && (
              <>
                <div className="flex items-center gap-1.5 mt-4 mb-2">
                  <Network size={12} className="text-violet-400" />
                  <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">{zh ? '网络接入' : 'Network'}</span>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                  <Field label={zh ? '业务IP' : 'Biz IP'} value={form.business_ip} onChange={v => setForm(f => ({ ...f, business_ip: v }))} placeholder="192.168.1.10" />
                  <Field label="VLAN" value={form.vlan} onChange={v => setForm(f => ({ ...f, vlan: v }))} placeholder="VLAN 100" />
                  <Field label={zh ? '上联交换机' : 'Uplink Switch'} value={form.uplink_switch} onChange={v => setForm(f => ({ ...f, uplink_switch: v }))} placeholder="core-sw-01" />
                  <Field label={zh ? '上联端口' : 'Uplink Port'} value={form.uplink_port} onChange={v => setForm(f => ({ ...f, uplink_port: v }))} placeholder="Gi0/1" />
                </div>
              </>
            )}

            {/* ─── 位置 & 资产 ─── */}
            <div className="flex items-center gap-1.5 mt-4 mb-2">
              <Building2 size={12} className="text-black/20" />
              <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">{zh ? '位置 & 资产' : 'Location & Asset'}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <div>
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '站点' : 'Site'}</label>
                <select
                  value={form.site_id || ''}
                  onChange={e => {
                    const siteId = e.target.value;
                    setForm(f => ({ ...f, site_id: siteId, rack: f.site_id === siteId ? f.rack : '' }));
                  }}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                  title={zh ? '站点' : 'Site'}
                >
                  <option value="">{zh ? '未分配站点' : 'Unassigned site'}</option>
                  {businessSites.map(site => (
                    <option key={site.id} value={site.id}>
                      {site.site_name} ({site.site_code})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Field
                  label={zh ? '机柜' : 'Rack'}
                  value={form.rack}
                  onChange={v => {
                    setForm(f => {
                      const matched = racks.find(r => r.name === v);
                      const newSiteId = !f.site_id && matched?.site_id ? matched.site_id : f.site_id;
                      return { ...f, rack: v, site_id: newSiteId };
                    });
                  }}
                  placeholder="A-01"
                  list="rack-options"
                />
                <datalist id="rack-options">
                  {filteredRacks.map(rk => (
                    <option key={rk} value={rk} />
                  ))}
                </datalist>
              </div>
              <Field type="number" label={zh ? '设备高度(U)' : 'Height (U)'} value={form.u_height} onChange={v => setForm(f => ({ ...f, u_height: v }))} placeholder="1" />
              <Field type="number" label={zh ? '计划起始U(选填)' : 'Planned start U'} value={form.planned_start_u} onChange={v => setForm(f => ({ ...f, planned_start_u: v }))} placeholder="" />
              <Field label={zh ? '机位备注(选填)' : 'Location note'} value={form.rack_unit} onChange={v => setForm(f => ({ ...f, rack_unit: v }))} placeholder={zh ? '文本备注' : 'Optional note'} />
              <Field label={zh ? '部门/业务' : 'Service'} value={form.department} onChange={v => setForm(f => ({ ...f, department: v }))} />
              <DateTimePicker label={zh ? '购买日期' : 'Purchased'} value={form.purchase_date} onChange={v => setForm(f => ({ ...f, purchase_date: v }))} language={language} mode="date" />
              <DateTimePicker label={zh ? '保修到期' : 'Warranty'} value={form.warranty_expiry} onChange={v => setForm(f => ({ ...f, warranty_expiry: v }))} language={language} mode="date" />
              <div className="col-span-2">
                <label className="block text-[10px] text-black/30 mb-0.5">{zh ? '备注' : 'Notes'}</label>
                <textarea
                  value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                  rows={2}
                  placeholder={zh ? '可选备注...' : 'Optional notes...'}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25 resize-none"
                />
              </div>
            </div>
          </div>

          {/* Sticky footer */}
          <div className="shrink-0 border-t border-black/5 bg-white rounded-b-2xl px-5 py-3">
            {(modalError || uValidationError) && (
              <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700">
                <AlertCircle size={13} className="shrink-0 text-red-500" />
                <span className="text-xs font-medium flex-1">{modalError || uValidationError}</span>
                <button onClick={() => { setModalError(null); setUValidationError(null); }} title="Dismiss" className="p-0.5 text-red-400 hover:text-red-600 shrink-0"><X size={12} /></button>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]">{zh ? '取消' : 'Cancel'}</button>
              <button
                onClick={handleSave}
                disabled={saving || (!form.hostname.trim() && !form.asset_tag.trim()) || !!uValidationError || (!isEditMode && form.asset_origin === 'legacy' && form.lifecycle_status === 'production' && String(form.takeover_exempt_reason || '').trim().length < 5)}
                className="px-4 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50 shadow-sm shadow-[#00bceb]/20"
              >
                {saving ? (zh ? '保存中...' : 'Saving...') : (zh ? '保存' : 'Save')}
              </button>
            </div>
          </div>

          {/* Production confirmation overlay */}
          {showProductionConfirm && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-black/40"
            >
              <div className="mx-6 max-w-sm rounded-xl bg-white p-5 shadow-xl">
                <div className="flex items-center gap-2 mb-2">
                  <div className="h-7 w-7 rounded-full bg-amber-50 flex items-center justify-center">
                    <AlertTriangle size={14} className="text-amber-500" />
                  </div>
                  <h4 className="text-sm font-bold text-black/80">{zh ? '投产确认' : 'Production Confirmation'}</h4>
                </div>
                <p className="text-xs leading-relaxed text-black/50 mb-4">
                  {zh
                    ? '系统将先执行口令上收与回连验证，全部成功后才会把设备标记为已投产。上收期间设备保持待投产状态。'
                    : 'Credentials will be rotated and verified first. The device will be marked as production only after takeover succeeds.'}
                </p>
                <textarea
                  value={legacyExemptReason}
                  onChange={event => setLegacyExemptReason(event.target.value)}
                  rows={2}
                  placeholder={zh ? '选择免上收投产时，请填写存量设备豁免原因（至少 5 个字符）' : 'Reason required for legacy exemption (minimum 5 characters)'}
                  className="mb-3 w-full resize-none rounded-lg border border-black/10 px-3 py-2 text-xs text-black/70 outline-none focus:border-amber-400"
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowProductionConfirm(false)}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]"
                  >
                    {zh ? '取消' : 'Cancel'}
                  </button>
                  <button
                    onClick={() => { setShowProductionConfirm(false); doSave({ production_mode: 'takeover' }); }}
                    disabled={saving}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50"
                  >
                    {saving ? (zh ? '处理中...' : 'Processing...') : (zh ? '确认投产' : 'Confirm')}
                  </button>
                </div>
                <button
                  onClick={() => {
                    setShowProductionConfirm(false);
                    doSave({ production_mode: 'legacy_exempt', takeover_exempt_reason: legacyExemptReason.trim() });
                  }}
                  disabled={saving || editingAsset?.asset_origin !== 'legacy' || legacyExemptReason.trim().length < 5}
                  className="mt-2 w-full rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-700 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {zh ? '存量设备免上收投产' : 'Legacy production without takeover'}
                </button>
                {editingAsset?.asset_origin !== 'legacy' && (
                  <p className="mt-1 text-center text-[9px] text-black/35">{zh ? '仅录入时标记为“存量设备”的资产可使用免上收投产' : 'Only assets marked as legacy during creation can use this option'}</p>
                )}
              </div>
            </motion.div>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

/* --- Form field --- */
function Field({ label, value, onChange, placeholder, type = 'text', list }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; list?: string;
}) {
  return (
    <div>
      <label className="block text-[10px] text-black/30 mb-0.5">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        list={list}
        className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25"
      />
    </div>
  );
}

/* --- Password field --- */
function PasswordField({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = React.useState(false);
  return (
    <div>
      <label className="block text-[10px] text-black/30 mb-0.5">{label}</label>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 pr-7 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25"
        />
        <button
          type="button"
          onClick={() => setShow(!show)}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-black/15 hover:text-black/30"
        >
          {show ? <EyeOff size={12} /> : <Eye size={12} />}
        </button>
      </div>
    </div>
  );
}
