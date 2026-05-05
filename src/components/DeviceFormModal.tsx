import React, { useState, useEffect } from 'react';
import { motion } from 'motion/react';
import { ChevronDown, ChevronRight, Edit2, Eye, EyeOff, Plus, Search, X } from 'lucide-react';
import type { Device, TagDefinition } from '../types';
import { TAG_CATEGORY_LABELS } from '../types';

type DeviceFormMode = 'add' | 'edit';

interface DeviceFormModalProps {
  mode: DeviceFormMode;
  language: string;
  form: Partial<Device>;
  passwordVisible: boolean;
  onFormChange: (nextForm: Partial<Device>) => void;
  onTogglePasswordVisibility: () => void;
  onClose: () => void;
  onSubmit: () => void;
}

const PLATFORM_OPTIONS = [
  { value: 'cisco_ios', label: 'Cisco IOS' },
  { value: 'cisco_nxos', label: 'Cisco NX-OS' },
  { value: 'juniper_junos', label: 'Juniper Junos' },
  { value: 'arista_eos', label: 'Arista EOS' },
  { value: 'fortinet_fortios', label: 'Fortinet FortiOS' },
  { value: 'huawei_vrp', label: 'Huawei VRP' },
  { value: 'h3c_comware', label: 'H3C Comware' },
  { value: 'ruijie_rgos', label: 'Ruijie RGOS' },
];

const ROLE_OPTIONS = [
  'Core',
  'Distribution',
  'Access',
  'Edge',
  'Firewall',
  'Load Balancer',
  'Unknown',
];

const LIFECYCLE_OPTIONS = [
  { value: 'staging', labelZh: '待投产', labelEn: 'Staging' },
  { value: 'production', labelZh: '已投产', labelEn: 'Production' },
  { value: 'maintenance', labelZh: '维护中', labelEn: 'Maintenance' },
  { value: 'decommissioned', labelZh: '已退役', labelEn: 'Decommissioned' },
];

const DeviceFormModal: React.FC<DeviceFormModalProps> = ({
  mode,
  language,
  form,
  passwordVisible,
  onFormChange,
  onTogglePasswordVisibility,
  onClose,
  onSubmit,
}) => {
  const isAdd = mode === 'add';
  const [enablePwdVisible, setEnablePwdVisible] = useState(false);
  const [showAdvancedCred, setShowAdvancedCred] = useState(
    !!(form.enable_password || form.priv_username || (form.credential_source && form.credential_source !== 'local') || form.vault_path || form.auth_model === 'dual')
  );
  const [pamMode, setPamMode] = useState(form.auth_model === 'dual');

  /* ── Tag Selection State ── */
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>(form.tag_ids || []);
  const [tagSearch, setTagSearch] = useState('');
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('netops_token') || '';
    fetch('/api/tags/definitions', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(json => {
        if (json?.success) setAllTags(json.data || []);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (form.tag_ids) setSelectedTagIds(form.tag_ids);
  }, [form.tag_ids]);

  const toggleTag = (tagId: string) => {
    const next = selectedTagIds.includes(tagId)
      ? selectedTagIds.filter(id => id !== tagId)
      : [...selectedTagIds, tagId];
    setSelectedTagIds(next);
    onFormChange({ ...form, tag_ids: next });
  };

  const filteredTags = allTags.filter(tag => {
    if (!tagSearch) return true;
    const q = tagSearch.toLowerCase();
    return tag.label.toLowerCase().includes(q) || tag.label_zh.toLowerCase().includes(q) || tag.value.toLowerCase().includes(q);
  });

  const handleFieldChange = <K extends keyof Device>(key: K, value: Device[K] | string | number | undefined) => {
    onFormChange({ ...form, [key]: value });
  };

  const title = isAdd
    ? (language === 'zh' ? '新增设备' : 'Add New Device')
    : (language === 'zh' ? '编辑设备' : 'Edit Device');

  const submitLabel = isAdd
    ? (language === 'zh' ? '创建设备' : 'Create Device')
    : (language === 'zh' ? '保存修改' : 'Save Changes');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-black/5 bg-black/[0.02] p-6">
          <div className="flex items-center gap-3">
            <div className={`rounded-lg p-2 ${isAdd ? 'bg-emerald-100 text-emerald-600' : 'bg-blue-100 text-blue-600'}`}>
              {isAdd ? <Plus size={20} /> : <Edit2 size={20} />}
            </div>
            <h2 className="text-lg font-semibold text-black">{title}</h2>
          </div>
          <button
            onClick={onClose}
            title={isAdd
              ? (language === 'zh' ? '关闭新增设备窗口' : 'Close add device dialog')
              : (language === 'zh' ? '关闭编辑设备窗口' : 'Close edit device dialog')}
            className="text-black/40 transition-colors hover:text-black"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Hostname</label>
              <input
                type="text"
                value={form.hostname || ''}
                title="Device hostname"
                onChange={(event) => handleFieldChange('hostname', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="e.g. Core-SW-01"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">IP Address</label>
              <input
                type="text"
                value={form.ip_address || ''}
                title="Device IP address"
                onChange={(event) => handleFieldChange('ip_address', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="e.g. 192.168.1.1"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Software / Platform</label>
              <select
                value={form.platform || 'cisco_ios'}
                title="Device platform"
                onChange={(event) => handleFieldChange('platform', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
              >
                {PLATFORM_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Role</label>
              <select
                value={form.role || 'Access'}
                title="Device role"
                onChange={(event) => handleFieldChange('role', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Connection Method</label>
              <select
                value={form.connection_method || 'ssh'}
                title="Connection method"
                onChange={(event) => handleFieldChange('connection_method', event.target.value as Device['connection_method'])}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
              >
                <option value="ssh">SSH</option>
                <option value="netconf">NETCONF</option>
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Site</label>
              <input
                type="text"
                value={form.site || ''}
                title="Device site"
                onChange={(event) => handleFieldChange('site', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="e.g. DataCenter-A"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">
                {language === 'zh' ? '投产状态' : 'Lifecycle Status'}
              </label>
              <select
                value={form.lifecycle_status || 'staging'}
                title={language === 'zh' ? '投产状态' : 'Lifecycle status'}
                onChange={(event) => handleFieldChange('lifecycle_status', event.target.value as Device['lifecycle_status'])}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
              >
                {LIFECYCLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {language === 'zh' ? opt.labelZh : opt.labelEn}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Serial Number</label>
              <input
                type="text"
                value={form.sn || ''}
                title="Serial number"
                onChange={(event) => handleFieldChange('sn', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="e.g. SN12345678"
              />
            </div>

            {/* ── Tag Selection ── */}
            <div className="col-span-1 sm:col-span-2">
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">
                {language === 'zh' ? '标签' : 'Tags'}
              </label>
              {/* Selected tags display */}
              <div className="flex flex-wrap gap-1.5 mb-2 min-h-[28px]">
                {selectedTagIds.map(tagId => {
                  const tag = allTags.find(t => t.id === tagId);
                  if (!tag) return null;
                  return (
                    <span key={tagId} className="inline-flex items-center gap-1 rounded-full border border-black/8 bg-black/[0.03] px-2 py-0.5 text-[11px]">
                      <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: tag.color || '#06b6d4' }} />
                      <span className="font-medium text-black/70">{language === 'zh' ? (tag.label_zh || tag.label) : tag.label}</span>
                      <button
                        type="button"
                        onClick={() => toggleTag(tagId)}
                        className="ml-0.5 text-black/30 hover:text-black/60"
                        title={language === 'zh' ? '移除标签' : 'Remove tag'}
                      >
                        <X size={10} />
                      </button>
                    </span>
                  );
                })}
                {selectedTagIds.length === 0 && (
                  <span className="text-[11px] text-black/30 italic py-0.5">
                    {language === 'zh' ? '点击下方添加标签…' : 'Click below to add tags…'}
                  </span>
                )}
              </div>
              {/* Tag dropdown toggle */}
              <button
                type="button"
                onClick={() => setTagDropdownOpen(!tagDropdownOpen)}
                className="w-full flex items-center justify-between rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2 text-sm text-black/50 hover:border-black/15 transition-colors"
              >
                <span>{language === 'zh' ? `已选 ${selectedTagIds.length} 个标签` : `${selectedTagIds.length} tag(s) selected`}</span>
                <ChevronDown size={14} className={`transition-transform ${tagDropdownOpen ? 'rotate-180' : ''}`} />
              </button>
              {/* Tag dropdown */}
              {tagDropdownOpen && (
                <div className="mt-1 rounded-xl border border-black/8 bg-white shadow-lg shadow-black/5 max-h-52 overflow-hidden flex flex-col">
                  <div className="relative px-2 pt-2 pb-1 border-b border-black/5">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-black/25 pointer-events-none" size={12} />
                    <input
                      type="text"
                      value={tagSearch}
                      onChange={e => setTagSearch(e.target.value)}
                      placeholder={language === 'zh' ? '搜索标签…' : 'Search tags…'}
                      className="w-full pl-7 pr-2 py-1.5 text-xs bg-black/[0.02] rounded-lg border border-black/5 outline-none focus:border-black/15"
                    />
                  </div>
                  <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
                    {Object.keys(TAG_CATEGORY_LABELS).map(cat => {
                      const catTags = filteredTags.filter(t => t.category === cat);
                      if (catTags.length === 0) return null;
                      const catLabel = language === 'zh' ? TAG_CATEGORY_LABELS[cat as keyof typeof TAG_CATEGORY_LABELS].zh : TAG_CATEGORY_LABELS[cat as keyof typeof TAG_CATEGORY_LABELS].en;
                      return (
                        <div key={cat}>
                          <div className="px-2 py-1 text-[9px] font-bold uppercase tracking-widest text-black/25">{catLabel}</div>
                          {catTags.map(tag => {
                            const active = selectedTagIds.includes(tag.id);
                            return (
                              <button
                                key={tag.id}
                                type="button"
                                onClick={() => toggleTag(tag.id)}
                                className={`w-full flex items-center gap-2 px-2 py-1 rounded-lg text-xs transition-all ${
                                  active ? 'bg-cyan-50 text-cyan-800 font-medium' : 'text-black/60 hover:bg-black/[0.03]'
                                }`}
                              >
                                <span className="h-2 w-2 rounded-full flex-shrink-0" style={{ backgroundColor: tag.color || '#06b6d4' }} />
                                <span className="flex-1 text-left truncate">{language === 'zh' ? (tag.label_zh || tag.label) : tag.label}</span>
                                {active && <span className="text-cyan-500 text-[10px]">✓</span>}
                              </button>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Model</label>
              <input
                type="text"
                value={form.model || ''}
                title="Device model"
                onChange={(event) => handleFieldChange('model', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="e.g. C9300-48P"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">{isAdd ? 'Software Version' : 'Version'}</label>
              <input
                type="text"
                value={form.version || ''}
                title="Software version"
                onChange={(event) => handleFieldChange('version', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="e.g. 17.3.3"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">SNMP Community</label>
              <input
                type="text"
                value={form.snmp_community || (isAdd ? 'public' : '')}
                title="SNMP community"
                onChange={(event) => handleFieldChange('snmp_community', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                placeholder="public"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">SNMP Port</label>
              <input
                type="number"
                value={form.snmp_port || 161}
                title="SNMP port"
                onChange={(event) => handleFieldChange('snmp_port', Number.parseInt(event.target.value || '161', 10))}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Username</label>
              <input
                type="text"
                value={form.username || ''}
                title="Login username"
                onChange={(event) => handleFieldChange('username', event.target.value)}
                className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">Password</label>
              <div className="relative">
                <input
                  type={passwordVisible ? 'text' : 'password'}
                  value={form.password || ''}
                  title={language === 'zh' ? 'SSH / Telnet 登录密码' : 'SSH / Telnet login password'}
                  onChange={(event) => handleFieldChange('password', event.target.value)}
                  placeholder={isAdd ? (language === 'zh' ? '输入 SSH 登录密码' : 'Enter SSH login password') : (language === 'zh' ? '留空则保持当前密码不变' : 'Leave blank to keep current password')}
                  className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 pr-10 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                />
                <button
                  type="button"
                  title={passwordVisible ? 'Hide password' : 'Show password'}
                  onClick={onTogglePasswordVisibility}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 transition-colors hover:text-black/60"
                >
                  {passwordVisible ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>
          </div>

          {/* Advanced Credentials Section */}
          <div className="col-span-1 sm:col-span-2 border-t border-black/5 pt-4">
            <button
              type="button"
              onClick={() => setShowAdvancedCred(!showAdvancedCred)}
              className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-black/50 transition-colors hover:text-black/80"
            >
              {showAdvancedCred ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              {language === 'zh' ? '特权凭据 / PAM / Vault' : 'Privileged / PAM / Vault Credentials'}
            </button>
          </div>
          
          {showAdvancedCred && (
            <div className="col-span-1 sm:col-span-2 space-y-6 pt-2">
              {/* PAM Toggle */}
              <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-black/5">
                <div>
                   <p className="text-xs font-bold text-slate-700">{language === 'zh' ? '多角色认证 (PAM)' : 'Multi-Role Auth (PAM)'}</p>
                   <p className="text-[10px] text-slate-400">{language === 'zh' ? '同时管理普通账户和管理员账户凭据' : 'Manage both normal and admin account credentials'}</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    const next = !pamMode;
                    setPamMode(next);
                    handleFieldChange('auth_model', next ? 'dual' : 'single');
                  }}
                  className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${pamMode ? 'bg-cyan-500' : 'bg-slate-200'}`}
                >
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${pamMode ? 'translate-x-5.5' : 'translate-x-1'}`} />
                </button>
              </div>

              {pamMode ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {/* Normal Account */}
                  <div className="p-3 rounded-xl border border-black/5 bg-blue-50/20">
                    <p className="text-[10px] font-black uppercase tracking-widest text-blue-600 mb-3">{language === 'zh' ? '普通账户 (Normal)' : 'Normal Account'}</p>
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[10px] font-medium text-black/40">Username</label>
                        <input
                          type="text"
                          value={form.normal_username || ''}
                          onChange={(e) => handleFieldChange('normal_username', e.target.value)}
                          className="w-full rounded-lg border border-black/5 bg-white px-3 py-1.5 text-xs outline-none focus:border-blue-200"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[10px] font-medium text-black/40">Password</label>
                        <input
                          type={passwordVisible ? 'text' : 'password'}
                          value={form.normal_password || ''}
                          onChange={(e) => handleFieldChange('normal_password', e.target.value)}
                          placeholder={!isAdd ? (language === 'zh' ? '留空保持不变' : 'Leave blank') : ''}
                          className="w-full rounded-lg border border-black/5 bg-white px-3 py-1.5 text-xs outline-none focus:border-blue-200"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Admin Account */}
                  <div className="p-3 rounded-xl border border-black/5 bg-orange-50/20">
                    <p className="text-[10px] font-black uppercase tracking-widest text-orange-600 mb-3">{language === 'zh' ? '特权账户 (Admin)' : 'Admin Account'}</p>
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1 block text-[10px] font-medium text-black/40">Username</label>
                        <input
                          type="text"
                          value={form.admin_username || ''}
                          onChange={(e) => handleFieldChange('admin_username', e.target.value)}
                          className="w-full rounded-lg border border-black/5 bg-white px-3 py-1.5 text-xs outline-none focus:border-orange-200"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[10px] font-medium text-black/40">Password</label>
                        <input
                          type={passwordVisible ? 'text' : 'password'}
                          value={form.admin_password || ''}
                          onChange={(e) => handleFieldChange('admin_password', e.target.value)}
                          placeholder={!isAdd ? (language === 'zh' ? '留空保持不变' : 'Leave blank') : ''}
                          className="w-full rounded-lg border border-black/5 bg-white px-3 py-1.5 text-xs outline-none focus:border-orange-200"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">
                      {language === 'zh' ? '特权用户名' : 'Privileged Username'}
                    </label>
                    <input
                      type="text"
                      value={form.priv_username || ''}
                      title={language === 'zh' ? '特权用户名（用于 enable 模式）' : 'Privileged username (for enable mode)'}
                      onChange={(event) => handleFieldChange('priv_username', event.target.value)}
                      className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                      placeholder={language === 'zh' ? '留空则使用普通用户名' : 'Leave blank to use login username'}
                    />
                  </div>
                  <div>
                    <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">
                      {language === 'zh' ? 'Enable Secret（特权密码）' : 'Enable Secret'}
                    </label>
                    <div className="relative">
                      <input
                        type={enablePwdVisible ? 'text' : 'password'}
                        value={form.enable_password || ''}
                        title={language === 'zh' ? '设备特权提权密码' : 'Device privilege escalation password'}
                        onChange={(event) => handleFieldChange('enable_password', event.target.value)}
                        placeholder={isAdd ? (language === 'zh' ? '输入特权提权密码' : 'Enter enable secret') : (language === 'zh' ? '留空则保持不变' : 'Leave blank to keep unchanged')}
                        className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 pr-10 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                      />
                      <button
                        type="button"
                        title={enablePwdVisible ? 'Hide' : 'Show'}
                        onClick={() => setEnablePwdVisible(!enablePwdVisible)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 transition-colors hover:text-black/60"
                      >
                        {enablePwdVisible ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 border-t border-black/5 pt-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">
                    {language === 'zh' ? '凭据来源' : 'Credential Source'}
                  </label>
                  <select
                    value={form.credential_source || 'local'}
                    title={language === 'zh' ? '凭据存储方式' : 'Credential storage method'}
                    onChange={(event) => handleFieldChange('credential_source', event.target.value as Device['credential_source'])}
                    className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                  >
                    <option value="local">{language === 'zh' ? '本地加密' : 'Local Encrypted'}</option>
                    <option value="vault">{language === 'zh' ? 'HashiCorp Vault' : 'HashiCorp Vault'}</option>
                  </select>
                </div>
                {form.credential_source === 'vault' && (
                  <div>
                    <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-black/60">
                      {language === 'zh' ? 'Vault 路径' : 'Vault Path'}
                    </label>
                    <input
                      type="text"
                      value={form.vault_path || ''}
                      title={language === 'zh' ? 'Vault KV 路径' : 'Vault KV path'}
                      onChange={(event) => handleFieldChange('vault_path', event.target.value)}
                      className="w-full rounded-xl border border-black/5 bg-black/[0.02] px-4 py-2.5 text-sm outline-none transition-colors focus:border-black/20 focus:bg-white"
                      placeholder="netops/devices/core-sw-01"
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className={`border-t border-black/5 ${isAdd ? 'bg-black/[0.01]' : 'bg-black/[0.02]'} p-6 ${isAdd ? 'flex gap-3' : 'flex justify-end gap-3'}`}>
          <button
            onClick={onClose}
            className={isAdd
              ? 'flex-1 rounded-xl border border-black/10 px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest transition-all hover:bg-black/5'
              : 'px-6 py-2 text-sm font-medium text-black/60 hover:text-black'}
          >
            {language === 'zh' ? '取消' : 'Cancel'}
          </button>
          <button
            onClick={onSubmit}
            className={isAdd
              ? 'flex-1 rounded-xl bg-black px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-white shadow-lg shadow-black/20 transition-all hover:bg-black/80'
              : 'rounded-xl bg-black px-8 py-2 text-sm font-medium text-white shadow-lg shadow-black/10 transition-all hover:bg-black/80'}
          >
            {submitLabel}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default DeviceFormModal;