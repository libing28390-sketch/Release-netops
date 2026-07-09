import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Terminal, Shield, Lock, Wifi, Network, Building2, AlertCircle, AlertTriangle, Eye, EyeOff, X } from 'lucide-react';
import DateTimePicker from '../../../components/DateTimePicker';
import { Asset } from '../types';
import { VENDOR_PLATFORMS, SERVER_PLATFORMS, ALL_PLATFORMS, STATUSES, LIFECYCLE_STATUSES } from '../constants';

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
  doSave: () => void;
  language: string;
  setFeedbackMsg: (msg: any) => void;
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
}) => {
  const zh = language === 'zh';

  const [racks, setRacks] = React.useState<any[]>([]);

  React.useEffect(() => {
    if (isOpen) {
      const token = localStorage.getItem('netops_token');
      fetch('/api/racks', {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      })
      .then(res => res.json())
      .then(data => {
        if (data && data.success && Array.isArray(data.data)) {
          setRacks(data.data);
        }
      })
      .catch(err => console.error('Failed to load racks:', err));
    }
  }, [isOpen]);

  const uniqueDatacenters = React.useMemo(() => {
    const set = new Set<string>();
    racks.forEach(r => {
      if (r.datacenter) {
        set.add(r.datacenter);
      }
    });
    return Array.from(set).sort();
  }, [racks]);

  const filteredRacks = React.useMemo(() => {
    if (!form.datacenter) {
      return Array.from(new Set(racks.map(r => r.name))).filter(Boolean).sort();
    }
    return racks
      .filter(r => r.datacenter === form.datacenter)
      .map(r => r.name)
      .filter(Boolean)
      .sort();
  }, [racks, form.datacenter]);

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
                    onChange={e => setForm(f => ({ ...f, vendor: e.target.value }))}
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
                    onChange={e => setForm(f => ({ ...f, vendor: e.target.value }))}
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
                  title="Lifecycle"
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                >
                  {LIFECYCLE_STATUSES.map(s => (
                    <option key={s.value} value={s.value}>
                      {s.label[zh ? 'zh' : 'en']}
                    </option>
                  ))}
                </select>
              </div>
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
                      onChange={e => setForm(f => ({ ...f, platform: e.target.value }))}
                      className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                      title="Platform"
                    >
                      {form.asset_type === 'server' ? (
                        SERVER_PLATFORMS.map(p => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))
                      ) : (
                        (VENDOR_PLATFORMS[form.vendor] || ALL_PLATFORMS).map(p => (
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

                {/* Dual-account credential inputs */}
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
                          {zh ? '（可选，不填则与特权账户密码相同）' : '(optional — defaults to admin password if blank)'}
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

                <div className="flex items-center gap-1.5 mt-2 mb-1">
                  <Wifi size={12} className="text-[#00bceb]/60" />
                  <span className="text-[10px] font-bold text-black/30 uppercase tracking-wider">SNMP</span>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
                  <Field label={zh ? '团体字' : 'Community'} value={form.snmp_community} onChange={v => setForm(f => ({ ...f, snmp_community: v }))} placeholder="public" />
                  <Field label={zh ? '端口' : 'Port'} value={form.snmp_port} onChange={v => setForm(f => ({ ...f, snmp_port: v }))} placeholder="161" />
                </div>
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
                <Field
                  label={zh ? '数据中心' : 'DC'}
                  value={form.datacenter}
                  onChange={v => setForm(f => ({ ...f, datacenter: v }))}
                  placeholder="BJ-DC1"
                  list="dc-options"
                />
                <datalist id="dc-options">
                  {uniqueDatacenters.map(dc => (
                    <option key={dc} value={dc} />
                  ))}
                </datalist>
              </div>
              <div>
                <Field
                  label={zh ? '机柜' : 'Rack'}
                  value={form.rack}
                  onChange={v => {
                    setForm(f => {
                      const matched = racks.find(r => r.name === v);
                      const newDc = !f.datacenter && matched?.datacenter ? matched.datacenter : f.datacenter;
                      return { ...f, rack: v, datacenter: newDc };
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
            {modalError && (
              <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700">
                <AlertCircle size={13} className="shrink-0 text-red-500" />
                <span className="text-xs font-medium flex-1">{modalError}</span>
                <button onClick={() => setModalError(null)} title="Dismiss" className="p-0.5 text-red-400 hover:text-red-600 shrink-0"><X size={12} /></button>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]">{zh ? '取消' : 'Cancel'}</button>
              <button
                onClick={handleSave}
                disabled={saving || (!form.hostname.trim() && !form.asset_tag.trim())}
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
                    ? '设备即将标记为已投产，系统将自动修改默认口令并完成凭据上收，确保安全合规。'
                    : 'Device will be marked as in production. Default passwords will be auto-rotated and credentials secured.'}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowProductionConfirm(false)}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-black/[0.01] border border-black/5 text-black/40 text-xs hover:bg-black/[0.02]"
                  >
                    {zh ? '取消' : 'Cancel'}
                  </button>
                  <button
                    onClick={() => { setShowProductionConfirm(false); doSave(); }}
                    disabled={saving}
                    className="flex-1 px-3 py-1.5 rounded-lg bg-[#00bceb] text-white text-xs font-bold hover:bg-[#00a5d0] disabled:opacity-50"
                  >
                    {saving ? (zh ? '处理中...' : 'Processing...') : (zh ? '确认投产' : 'Confirm')}
                  </button>
                </div>
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
