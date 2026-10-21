import React from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Terminal, Shield, Lock, Wifi, Network, Building2, AlertCircle, AlertTriangle, Globe2, Plus, Trash2, X, RefreshCw, ChevronDown } from 'lucide-react';
import DateTimePicker from '../../../components/DateTimePicker';
import { PasswordInputField } from '../../../components/ui/PasswordInputField';
import { FormActionBar, FormSection } from '../../../components/ui/FormLayout';
import { Asset } from '../types';
import type { TagDefinition } from '../../../types';
import {
  VENDOR_PLATFORMS,
  NETWORK_VENDOR_GROUPS,
  ALL_VENDOR_NAMES,
  SERVER_PLATFORMS,
  ALL_PLATFORMS,
  getPlatformsForVendor,
  isCiscoNetworkPlatform,
  STATUSES,
  LIFECYCLE_STATUSES,
  NETWORK_TOPOLOGY_ROLE_OPTIONS,
  TOPOLOGY_FUNCTION_OPTIONS,
  TOPOLOGY_ZONE_OPTIONS,
  isValidIpAddress,
} from '../constants';
import { AssetTagPicker } from './AssetTagPicker';
import { ActionIconButton } from '../../../components/ui/ActionIconButton';
import { isReservedSystemSite } from '../../../utils/siteIdentity';
import { ApiError, apiRequest, authHeaders } from '../../../api/http';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';
import RemoteDesktopProfileEditor from './RemoteDesktopProfileEditor';

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
  handleSave: () => void | Promise<void>;
  doSave: (overrides?: Record<string, unknown>) => void | Promise<void>;
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
  const [lookupsLoading, setLookupsLoading] = React.useState(false);
  const [lookupsLoaded, setLookupsLoaded] = React.useState(false);
  const [lookupRetry, setLookupRetry] = React.useState(0);
  const [lookupError, setLookupError] = React.useState<{ status: number | null; message: string; permissionDenied: boolean } | null>(null);
  const [lookupEmptyResources, setLookupEmptyResources] = React.useState<string[]>([]);
  const [uValidationError, setUValidationError] = React.useState<string | null>(null);
  const [legacyExemptReason, setLegacyExemptReason] = React.useState('');
  const [credentials, setCredentials] = React.useState<any[]>([]);
  const [showMoreAssetDetails, setShowMoreAssetDetails] = React.useState(false);
  const [showWebProfilesDialog, setShowWebProfilesDialog] = React.useState(false);
  const [webProfilesDraft, setWebProfilesDraft] = React.useState<any[]>([]);
  const webProfilesBeforeDialogRef = React.useRef<any[] | null>(null);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const webProfilesDialogRef = React.useRef<HTMLDivElement>(null);
  const saveLockRef = React.useRef(false);
  const [credMode, setCredMode] = React.useState<'manual' | 'existing'>('manual');
  const dialogTitleId = React.useId();
  const webProfilesDialogTitleId = React.useId();
  const webProfiles = Array.isArray(form.web_profiles) ? form.web_profiles : [];
  const webProfilesEnabled = webProfiles.some((profile: any) => profile.enabled !== false);
  const ciscoEnablePasswordAvailable = isCiscoNetworkPlatform(form.asset_type, form.platform);
  const onboardingStatus = isEditMode
    ? String(editingAsset?.onboarding_status || 'pending_credentials').trim().toLowerCase()
    : '';
  const onboardingStatusLabel = onboardingStatus === 'pending_credentials'
    ? (zh ? '待设置凭据' : 'credentials not set')
    : onboardingStatus === 'credentials_set'
      ? (zh ? '待验证连通性' : 'connectivity not verified')
      : onboardingStatus;
  const productionOnboardingBlocked = isEditMode
    && form.lifecycle_status === 'production'
    && (editingAsset?.lifecycle_status || 'staging') !== 'production'
    && !['verified', 'active'].includes(onboardingStatus);
  const createDefaultWebProfile = (assetType: string) => ({
    profile_name: assetType === 'server' ? 'BMC' : 'Web管理',
    scheme: 'https',
    port: '443',
    path: '/',
    enabled: true,
    credential_mode: 'inherit_asset',
  });
  const openWebProfilesDialog = () => {
    const profiles = webProfiles.length ? webProfiles.map((profile: any) => ({ ...profile })) : [createDefaultWebProfile(form.asset_type)];
    webProfilesBeforeDialogRef.current = webProfiles.map((profile: any) => ({ ...profile }));
    setWebProfilesDraft(profiles);
    setShowWebProfilesDialog(true);
  };
  const cancelWebProfilesDialog = () => {
    const previousProfiles = webProfilesBeforeDialogRef.current;
    if (previousProfiles) {
      setForm((current: any) => ({ ...current, web_profiles: previousProfiles.map(profile => ({ ...profile })) }));
    }
    webProfilesBeforeDialogRef.current = null;
    setShowWebProfilesDialog(false);
  };
  const toggleWebProfiles = (enabled: boolean) => {
    const profiles = webProfiles.length ? webProfiles : enabled ? [createDefaultWebProfile(form.asset_type)] : [];
    const nextProfiles = profiles.map((profile: any) => ({ ...profile, enabled }));
    setForm((current: any) => ({ ...current, web_profiles: nextProfiles }));
    if (enabled) {
      webProfilesBeforeDialogRef.current = webProfiles.map((profile: any) => ({ ...profile }));
      setWebProfilesDraft(nextProfiles.map((profile: any) => ({ ...profile })));
      setShowWebProfilesDialog(true);
    }
  };
  const updateWebProfileDraft = (index: number, updates: Record<string, unknown>) => {
    setWebProfilesDraft(current => current.map((profile, itemIndex) => itemIndex === index ? { ...profile, ...updates } : profile));
  };
  useEscapeClose(isOpen && !showWebProfilesDialog, onClose);
  useEscapeClose(isOpen && showWebProfilesDialog, cancelWebProfilesDialog);
  useFocusTrap(dialogRef, isOpen, 'input:not([type="hidden"])');
  useFocusTrap(webProfilesDialogRef, isOpen && showWebProfilesDialog, 'input:not([type="hidden"])');

  React.useEffect(() => {
    if (isOpen) setShowMoreAssetDetails(isEditMode);
  }, [isOpen, isEditMode]);

  React.useEffect(() => {
    if (!isOpen || ciscoEnablePasswordAvailable) return;
    setShowEnableSecret(false);
    setForm(current => current.enable_password ? { ...current, enable_password: '' } : current);
  }, [ciscoEnablePasswordAvailable, isOpen, setForm, setShowEnableSecret]);
  const mgmtIpError = React.useMemo(() => {
    if (isEditMode) return null;
    const ip = String(form.management_ip || '').trim();
    if (!ip) return null;
    return isValidIpAddress(ip) ? null : (zh ? 'IP 格式不正确' : 'Invalid IP format');
  }, [form.management_ip, isEditMode, zh]);

  React.useEffect(() => {
    if (isOpen) setCredMode(form.credential_id ? 'existing' : 'manual');
  }, [isOpen, form.credential_id]);

  React.useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    let active = true;
    setLookupsLoading(true);
    setLookupError(null);

    const readLookup = (
      result: PromiseSettledResult<{ success?: boolean; data?: unknown }>,
      label: string,
    ): { data: any[] | null; failure: { label: string; status: number | null } | null; empty: boolean } => {
      if (result.status === 'rejected') {
        const status = result.reason instanceof ApiError ? result.reason.status : null;
        return { data: null, failure: { label, status }, empty: false };
      }
      if (!result.value.success || !Array.isArray(result.value.data)) {
        return { data: null, failure: { label, status: null }, empty: false };
      }
      return { data: result.value.data, failure: null, empty: result.value.data.length === 0 };
    };

    const loadLookups = async () => {
      const results = await Promise.allSettled([
        apiRequest<{ success?: boolean; data?: unknown }>('/api/racks', { signal: controller.signal }),
        apiRequest<{ success?: boolean; data?: unknown }>('/api/cmdb/sites', { signal: controller.signal }),
        apiRequest<{ success?: boolean; data?: unknown }>('/api/credentials', { signal: controller.signal }),
      ]);
      if (!active) return;

      const rackResult = readLookup(results[0], zh ? '机柜' : 'racks');
      const siteResult = readLookup(results[1], zh ? '站点' : 'sites');
      const credentialResult = readLookup(results[2], zh ? '凭据' : 'credentials');
      if (rackResult.data) setRacks(rackResult.data);
      if (siteResult.data) setSites(siteResult.data);
      if (credentialResult.data) setCredentials(credentialResult.data);

      const failures = [rackResult.failure, siteResult.failure, credentialResult.failure].filter(Boolean) as Array<{ label: string; status: number | null }>;
      const emptyResources = [rackResult, siteResult, credentialResult].filter(result => result.empty).map(result => result.failure?.label || (
        result === rackResult ? (zh ? '机柜' : 'racks') : result === siteResult ? (zh ? '站点' : 'sites') : (zh ? '凭据' : 'credentials')
      ));
      setLookupEmptyResources(emptyResources);
      if (failures.length > 0) {
        const status = failures.some(failure => failure.status === 401) ? 401
          : failures.some(failure => failure.status === 403) ? 403
            : failures.find(failure => failure.status)?.status || null;
        const permissionDenied = status === 401 || status === 403;
        const names = failures.map(failure => failure.label).join(zh ? '、' : ', ');
        const message = status === 401
          ? (zh ? '登录状态已失效，请重新登录后加载表单选项。' : 'Your session has expired. Sign in again to load form options.')
          : status === 403
            ? (zh ? `你没有权限读取以下表单选项：${names}。` : `You do not have permission to load these form options: ${names}.`)
            : (zh ? `表单选项加载失败：${names}。请重试。` : `Unable to load these form options: ${names}. Retry to check again.`);
        setLookupError({ status, message, permissionDenied });
      }
      setLookupsLoaded(true);
      setLookupsLoading(false);
    };

    void loadLookups();
    return () => {
      active = false;
      controller.abort();
    };
  }, [isOpen, lookupRetry, zh]);

  React.useEffect(() => {
    if (!isOpen) setShowWebProfilesDialog(false);
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
    () => credentials.filter(c => c.id === form.snmp_credential_id || ['snmpv2', 'snmpv3'].includes(String(c.credential_type || '').toLowerCase())),
    [credentials, form.snmp_credential_id],
  );
  const selectedSnmpCredential = snmpCredentials.find(c => c.id === form.snmp_credential_id);
  const snmpCommunityConfigured = Boolean(form.snmp_community_set || selectedSnmpCredential?.has_snmp_community);
  const isWindowsMachine = form.asset_type === 'server' && ['windows', 'windows_server'].includes(String(form.platform || '').toLowerCase());
  const showLookupLoading = isOpen && (lookupsLoading || (!lookupsLoaded && !lookupError));
  const runSaveAction = React.useCallback(async (action: () => void | Promise<void>) => {
    if (saving || saveLockRef.current) return;
    saveLockRef.current = true;
    try {
      await action();
    } finally {
      saveLockRef.current = false;
    }
  }, [saving]);
  const handleSaveOnce = React.useCallback(() => { void runSaveAction(handleSave); }, [handleSave, runSaveAction]);
  const doSaveOnce = React.useCallback((overrides?: Record<string, unknown>) => {
    void runSaveAction(() => doSave(overrides));
  }, [doSave, runSaveAction]);

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

  // A vendor with exactly one supported platform should always have that
  // platform selected, including when an older alias is loaded for editing.
  // Vendors with multiple platforms remain user-selectable.
  React.useEffect(() => {
    if (isEditMode) return;
    if (form.asset_type !== 'network_device' || !form.vendor) return;
    const platformOptions = getPlatformsForVendor(form.vendor);
    if (platformOptions.length !== 1) return;
    const defaultPlatform = platformOptions[0].value;
    if (String(form.platform || '') === defaultPlatform) return;
    setForm(current => {
      if (current.asset_type !== 'network_device' || current.vendor !== form.vendor || String(current.platform || '') === defaultPlatform) {
        return current;
      }
      return withTechnologyTag({ ...current, platform: defaultPlatform }, current.vendor, defaultPlatform);
    });
  }, [allTags, form.asset_type, form.platform, form.vendor, isEditMode, setForm]);

  // Real-time U-position validation
  React.useEffect(() => {
    const placementChanged = !isEditMode || !editingAsset
      || String(form.site_id || '') !== String(editingAsset.site_id || '')
      || String(form.rack || '') !== String(editingAsset.rack || '')
      || String(form.planned_start_u ?? '').trim() !== String(editingAsset.planned_start_u ?? '').trim();
    if (!placementChanged) {
      setUValidationError(null);
      return;
    }
    const rack = form.rack;
    const startU = parseInt(String(form.planned_start_u), 10);
    const height = parseInt(String(form.u_height), 10);

    if (!rack || Number.isNaN(startU) || startU < 1 || Number.isNaN(height) || height < 1) {
      setUValidationError(null);
      return;
    }

    const controller = new AbortController();
    const validate = async () => {
      try {
        const url = `/api/racks/validate-u?rack=${encodeURIComponent(rack)}&start_u=${startU}&u_height=${height}&exclude_asset_id=${editingAsset?.id || ''}`;
        const data = await apiRequest<{ success?: boolean; reason?: string }>(url, { signal: controller.signal });
        if (!data.success) setUValidationError(data.reason || (zh ? '机柜位置校验失败' : 'Rack position validation failed'));
        else setUValidationError(null);
      } catch (error) {
        if (controller.signal.aborted) return;
        const status = error instanceof ApiError ? error.status : null;
        const message = status === 401
          ? (zh ? '登录状态已失效，请重新登录后校验机柜位置。' : 'Your session has expired. Sign in again to validate rack placement.')
          : status === 403
            ? (zh ? '你没有权限校验机柜位置。' : 'You do not have permission to validate rack placement.')
            : (zh ? '机柜位置校验失败，请稍后重试。' : 'Unable to validate rack placement. Retry shortly.');
        setUValidationError(message);
      }
    };

    const timer = setTimeout(() => { void validate(); }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [form.site_id, form.rack, form.planned_start_u, form.u_height, editingAsset, isEditMode, language]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-3"
        onClick={onClose}
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-hidden={showWebProfilesDialog ? true : undefined}
          aria-labelledby={dialogTitleId}
          className="nx-form-dialog-surface relative flex h-[85vh] w-[760px] max-w-[95vw] flex-col overflow-hidden rounded-xl border"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="nx-dialog-header flex shrink-0 items-center justify-between border-b px-5 py-4">
            <h3 id={dialogTitleId} className="text-sm font-bold text-black/85">
              {isEditMode ? (zh ? '编辑资产' : 'Edit Asset') : (zh ? '新增资产' : 'Add Asset')}
            </h3>
            <button type="button" onClick={onClose} aria-label={zh ? '关闭' : 'Close'} className="rounded-md p-1 text-black/45 hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500">
              <X size={16} />
            </button>
          </div>

          {/* Scrollable body */}
          <div className="nx-dialog-body flex-1 space-y-4 overflow-y-auto px-5 py-4">
            <div className="nx-dialog-info rounded-lg border px-3 py-2 text-[11px] leading-relaxed">
              {zh ? '主机名和资产编号至少填写一项。新设备默认待投产，可先保存再完成凭据验证。' : 'Provide a hostname or asset tag. New devices start in staging so you can save first and verify credentials afterward.'}
            </div>
            {isEditMode && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] leading-4 text-slate-600">
                {zh ? '设备标识创建后固定；站点、机柜和安装 U 位可在设备迁移时调整。' : 'Device identifiers are fixed after creation; site, rack, and installed U position can change during a move.'}
              </div>
            )}
            {showLookupLoading && (
              <div role="status" className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <RefreshCw size={12} />
                {zh ? '正在加载站点、机柜和凭据选项…' : 'Loading sites, racks, and credential options…'}
              </div>
            )}
            {lookupError && (
              <div role="alert" className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs ${lookupError.permissionDenied ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-rose-200 bg-rose-50 text-rose-800'}`}>
                <span>{lookupError.message}</span>
                <button type="button" onClick={() => setLookupRetry(value => value + 1)} disabled={lookupsLoading} className="rounded-md border border-current/20 px-2 py-1 font-semibold disabled:opacity-50">{lookupsLoading ? (zh ? '重试中…' : 'Retrying…') : (zh ? '重试选项' : 'Retry options')}</button>
              </div>
            )}
            {lookupEmptyResources.length > 0 && (
              <div role="status" className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                {zh ? `没有可用的${lookupEmptyResources.join('、')}选项。` : `No ${lookupEmptyResources.join(', ')} options are available.`}
              </div>
            )}
            {/* ─── 基本属性 ─── */}
            <FormSection
              title={zh ? '资产信息' : 'Asset details'}
              className="nx-dialog-card overflow-hidden rounded-xl !border-[var(--ui-border)] !bg-[var(--ui-surface)]"
              contentClassName="!p-3 sm:!p-4"
            >
            <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
              <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '资产类型' : 'Asset Type'}</label>
                <select
                  value={form.asset_type}
                  disabled={isEditMode}
                  onChange={e => {
                    const assetType = e.target.value;
                    setForm(f => ({
                      ...f,
                      asset_type: assetType,
                      // Do not carry a server vendor/platform into a network
                      // row (or a network platform into a server row).
                      vendor: '',
                      platform: assetType === 'server' ? SERVER_PLATFORMS[0]?.value || 'linux' : '',
                    }));
                  }}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 disabled:bg-black/[0.03] disabled:text-black/35 disabled:cursor-not-allowed focus:outline-none focus:border-[#00bceb]/25"
                  title="Asset Type"
                >
                  <option value="server">{zh ? '服务器' : 'Server'}</option>
                  <option value="network_device">{zh ? '网络设备' : 'Network Device'}</option>
                </select>
              </div>
              <Field
                label={zh ? '主机名' : 'Hostname'}
                value={form.hostname}
                onChange={v => setForm(f => ({ ...f, hostname: v }))}
                disabled={isEditMode}
                helper={zh ? '网络设备批量导入时可能通过 SNMP 同步主机名；也可在此手动填写。' : 'Network device imports may sync the hostname through SNMP; you can also enter it here.'}
                placeholder={zh ? '例如：core-sw-01' : 'e.g. host-01'}
              />
              <Field label={zh ? '资产编号' : 'Asset Tag'} value={form.asset_tag} onChange={v => setForm(f => ({ ...f, asset_tag: v }))} placeholder="e.g. SRV-BJ-001" disabled={isEditMode} />
              {showMoreAssetDetails && <Field label={zh ? '序列号 (S/N)' : 'Serial Number'} value={form.serial_number} onChange={v => setForm(f => ({ ...f, serial_number: v }))} disabled={isEditMode} />}

              <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '厂商' : 'Vendor'}</label>
                {form.asset_type === 'server' ? (
                  <select
                    value={form.vendor}
                    disabled={isEditMode}
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
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 disabled:bg-black/[0.03] disabled:text-black/35 disabled:cursor-not-allowed focus:outline-none focus:border-[#00bceb]/25"
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
                    disabled={isEditMode}
                    onChange={e => {
                      const vendor = e.target.value;
                      const platformOptions = getPlatformsForVendor(vendor);
                      setForm(f => {
                        const nextPlatform = platformOptions.some(option => option.value === f.platform)
                          ? f.platform
                          : (platformOptions[0]?.value || '');
                        return withTechnologyTag({
                          ...f,
                          vendor,
                          model: f.vendor === vendor ? f.model : '',
                          platform: nextPlatform,
                        }, vendor, nextPlatform);
                      });
                    }}
                    className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 disabled:bg-black/[0.03] disabled:text-black/35 disabled:cursor-not-allowed focus:outline-none focus:border-[#00bceb]/25"
                    title="Vendor"
                  >
                    <option value="">{zh ? '选择设备厂商...' : 'Select vendor...'}</option>
                    {NETWORK_VENDOR_GROUPS.map(group => (
                      <optgroup key={group.key} label={zh ? group.labelZh : group.labelEn}>
                        {group.vendors.map(vendor => <option key={vendor} value={vendor}>{vendor}</option>)}
                      </optgroup>
                    ))}
                    {form.vendor && !ALL_VENDOR_NAMES.includes(form.vendor as typeof ALL_VENDOR_NAMES[number]) && (
                      <option value={form.vendor}>{form.vendor} ({zh ? '当前值' : 'Current value'})</option>
                    )}
                  </select>
                )}
              </div>
              <Field label={zh ? '型号' : 'Model'} value={form.model} onChange={v => setForm(f => ({ ...f, model: v }))} placeholder="e.g. PowerEdge R750" disabled={isEditMode} />
              {showMoreAssetDetails && <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '状态' : 'Status'}</label>
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
              </div>}
              {showMoreAssetDetails && <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '投产状态' : 'Lifecycle'}</label>
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
                {productionOnboardingBlocked && (
                  <p className="mt-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-4 text-amber-800">
                    {zh
                      ? `当前口令上手状态：${onboardingStatusLabel}。请先在设备详情完成凭据设置与连通性验证，再投产；此时保存会被系统拒绝。`
                      : `Device onboarding is ${onboardingStatusLabel}. Complete credential setup and connectivity verification in device details before production.`}
                  </p>
                )}
                {!isEditMode && form.asset_origin !== 'legacy' && <p className="mt-1 text-[11px] text-black/30">{zh ? '新设备统一以待投产状态入库' : 'New devices are always created in staging'}</p>}
              </div>}
              {showMoreAssetDetails && <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '录入来源' : 'Asset Origin'}</label>
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
                <p className="mt-1 text-[11px] text-black/30">
                  {zh ? '记录首次录入方式，投产后不会改变' : 'Records how the asset was first entered and does not change after production'}
                </p>
              </div>}
              {showMoreAssetDetails && !isEditMode && form.asset_origin === 'legacy' && form.lifecycle_status === 'production' && (
                <div className="sm:col-span-2">
                  <label className="block text-xs text-black/30 mb-0.5">{zh ? '免上收投产原因' : 'Takeover Exemption Reason'}</label>
                  <textarea
                    value={form.takeover_exempt_reason || ''}
                    onChange={e => setForm(f => ({ ...f, takeover_exempt_reason: e.target.value }))}
                    rows={2}
                    placeholder={zh ? '说明该存量设备暂不修改口令的原因，至少 5 个字符' : 'Explain why this legacy device will not rotate passwords yet'}
                    className="w-full resize-none rounded-lg border border-amber-200 bg-amber-50/40 px-2.5 py-2 text-xs text-black/65 outline-none focus:border-amber-400"
                  />
                </div>
              )}
              <Field label={zh ? '管理IP' : 'Mgmt IP'} value={form.management_ip} onChange={v => setForm(f => ({ ...f, management_ip: v }))} placeholder="e.g. 10.0.1.10" error={mgmtIpError} disabled={isEditMode} />
              <Field label={zh ? '主通道端口' : 'Primary channel port'} value={form.management_port} onChange={v => setForm(f => ({ ...f, management_port: v }))} placeholder={form.connection_method === 'web' || form.connection_method === 'none' ? '-' : '22'} />

              <div className="sm:col-span-2">
                <button
                  type="button"
                  aria-expanded={showMoreAssetDetails}
                  onClick={() => setShowMoreAssetDetails(value => {
                    if (value && form.asset_origin === 'legacy' && form.lifecycle_status === 'production') return value;
                    return !value;
                  })}
                  className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left hover:bg-slate-100"
                >
                  <span className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                    <ChevronDown size={13} className={`transition-transform ${showMoreAssetDetails ? 'rotate-180' : ''}`} />
                    {zh ? (showMoreAssetDetails ? '收起更多信息' : '更多信息（选填）') : (showMoreAssetDetails ? 'Hide additional details' : 'More details (optional)')}
                  </span>
                  <span className="text-right text-[11px] text-slate-400">{zh ? '序列号、状态、分类、网络、位置和保修' : 'Serial, status, category, network, location and warranty'}</span>
                </button>
              </div>

              <div className="sm:col-span-2 flex items-center justify-between gap-3 rounded-xl border border-cyan-100 bg-cyan-50/30 px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2.5">
                  <Globe2 size={15} className="shrink-0 text-cyan-600" />
                  <div className="min-w-0">
                    <p className="text-[11px] font-bold text-slate-700">{zh ? 'Web 管理入口' : 'Web management entry'}</p>
                    <p className="truncate text-[11px] text-slate-400">{webProfilesEnabled
                      ? `${webProfiles.filter((profile: any) => profile.enabled !== false).length} ${zh ? '个入口已启用' : 'enabled'}`
                      : webProfiles.length
                        ? (zh ? `已停用，保留 ${webProfiles.length} 个入口配置` : `${webProfiles.length} saved entry configuration(s), disabled`)
                        : (zh ? '未启用；适用于网络设备 Web 管理及服务器带外管理' : 'Optional for network Web management and server BMC access')}</p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <label className="inline-flex cursor-pointer items-center gap-2 text-xs font-semibold text-slate-600">
                    <input
                      type="checkbox"
                      checked={webProfilesEnabled}
                      onChange={event => toggleWebProfiles(event.target.checked)}
                      className="h-3.5 w-3.5 accent-cyan-600"
                    />
                    {zh ? '启用' : 'Enabled'}
                  </label>
                  {webProfiles.length > 0 && (
                    <button
                      type="button"
                      onClick={openWebProfilesDialog}
                      className="rounded-lg border border-cyan-200 bg-white px-2.5 py-1.5 text-[11px] font-bold text-cyan-700 hover:bg-cyan-50"
                    >
                      {zh ? '配置' : 'Configure'}
                    </button>
                  )}
                </div>
              </div>

              {showMoreAssetDetails && isWindowsMachine && (isEditMode && editingAsset?.id ? (
                <RemoteDesktopProfileEditor
                  assetId={editingAsset.id}
                  credentials={credentials}
                  language={language}
                />
              ) : (
                <div className="sm:col-span-2 rounded-xl border border-violet-100 bg-violet-50/35 px-3.5 py-3 text-xs leading-4 text-slate-500">
                  <span className="font-bold text-violet-700">{zh ? 'RDP / VNC：' : 'RDP / VNC: '}</span>
                  {zh ? '请先保存资产以生成资产 ID，然后重新打开该资产并单独保存远程桌面配置。' : 'Save the asset first to create its ID, then reopen it and save its remote desktop profiles.'}
                </div>
              ))}

              {showMoreAssetDetails && <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '设备子类' : 'Device Sub-category'}</label>
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
              </div>}
              {showMoreAssetDetails && <SelectField
                label={zh ? '功能' : 'Function'}
                value={form.function || ''}
                onChange={v => setForm(f => ({ ...f, function: v }))}
                options={TOPOLOGY_FUNCTION_OPTIONS}
                language={language}
              />}
              {showMoreAssetDetails && <SelectField
                label={zh ? '区域' : 'Zone'}
                value={form.zone || ''}
                onChange={v => setForm(f => ({ ...f, zone: v }))}
                options={TOPOLOGY_ZONE_OPTIONS}
                language={language}
              />}
              {showMoreAssetDetails && <Field label={zh ? '额定功率 (W)' : 'Power (W)'} value={form.power_watts} onChange={v => setForm(f => ({ ...f, power_watts: v }))} placeholder="e.g. 350" />}
            </div>

            {/* ─── 连接配置 & PAM ─── */}
            {showMoreAssetDetails && form.asset_type === 'network_device' && <div className="rounded-xl border border-cyan-100 bg-cyan-50/40 px-3 py-2.5">
              <label className="block text-xs font-semibold text-cyan-900/70">{zh ? '拓扑角色' : 'Topology Role'}</label>
              <select
                value={form.device_role || ''}
                onChange={e => setForm(f => ({ ...f, device_role: e.target.value }))}
                className="mt-1 w-full rounded-lg border border-cyan-200 bg-white px-2.5 py-1.5 text-xs text-black/65 outline-none focus:border-cyan-400"
                title="Topology Role"
              >
                <option value="">{zh ? '请选择拓扑角色...' : 'Select topology role...'}</option>
                {form.device_role && !NETWORK_TOPOLOGY_ROLE_OPTIONS.some(option => option.value === form.device_role) && (
                  <option value={form.device_role}>{form.device_role}</option>
                )}
                {NETWORK_TOPOLOGY_ROLE_OPTIONS.map(option => (
                  <option key={option.value} value={option.value}>{option.label[zh ? 'zh' : 'en']}</option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-cyan-900/50">{zh ? '记录设备身份；拓扑层级由关系证据和布局算法计算，不由角色固定。' : 'Records device identity; topology layers are calculated from evidence, not fixed by role.'}</p>
            </div>}

            {(form.asset_type === 'network_device' || form.asset_type === 'server') && (
              <div className="sm:col-span-2 space-y-4">
                <div className="flex items-center gap-1.5 mt-4 mb-1">
                  <Terminal size={12} className="text-[#00bceb]/60" />
                  <span className="text-xs font-bold text-black/30 uppercase tracking-wider">{zh ? '连接与凭据' : 'Connection & Credentials'}</span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-2.5">
                  <div>
                    <label className="block text-xs text-black/30 mb-0.5">{zh ? '平台' : 'Platform'}</label>
                    <select
                      value={form.platform}
                      onChange={e => setForm(f => {
                        const platform = e.target.value;
                        const windows = platform === 'windows' || platform === 'windows_server';
                        return withTechnologyTag({
                          ...f,
                          platform,
                          connection_method: windows ? 'winrm' : f.connection_method === 'winrm' ? 'ssh' : f.connection_method,
                          management_port: windows ? '5986' : f.connection_method === 'winrm' ? '22' : f.management_port,
                          winrm_enabled: windows ? true : f.winrm_enabled,
                        }, f.vendor, platform);
                      })}
                      className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                      title="Platform"
                    >
                      {form.asset_type === 'network_device' && !form.vendor && !form.platform && (
                        <option value="" disabled>
                          {zh ? '请选择厂商或平台…' : 'Choose a vendor or platform…'}
                        </option>
                      )}
                      {form.asset_type === 'server' ? (
                        SERVER_PLATFORMS.map(p => (
                          <option key={p.value} value={p.value}>{p.label}</option>
                        ))
                      ) : (
                        getPlatformsForVendor(form.vendor).map(p => (
                          <option key={p.value} value={p.value}>{zh ? (p.labelZh || p.label) : (p.labelEn || p.label)}</option>
                        ))
                      )}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-black/30 mb-0.5">{zh ? '连接方式' : 'Method'}</label>
                    <select
                      value={form.connection_method}
                      onChange={e => setForm(f => ({ ...f, connection_method: e.target.value }))}
                      className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                      title="Connection"
                    >
                      <option value="ssh">SSH</option>
                      <option value="netconf">NETCONF</option>
                      {(form.platform === 'windows' || form.platform === 'windows_server') && (
                        <option value="winrm">WinRM HTTPS</option>
                      )}
                      <option value="web">{zh ? '仅 Web（HTTP/HTTPS）' : 'Web only (HTTP/HTTPS)'}</option>
                      <option value="none">{zh ? '无登录通道' : 'No login channel'}</option>
                    </select>
                  </div>
                </div>

                {ciscoEnablePasswordAvailable && (
                  <div className="rounded-xl border border-amber-100 bg-amber-50/40 px-3 py-2">
                    <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-amber-800">
                      <input
                        type="checkbox"
                        checked={showEnableSecret}
                        aria-label={zh ? 'Cisco Enable 密码' : 'Cisco Enable Secret'}
                        onChange={event => {
                          const enabled = event.target.checked;
                          setShowEnableSecret(enabled);
                          if (!enabled) setForm(current => ({ ...current, enable_password: '' }));
                        }}
                        className="h-3.5 w-3.5 accent-amber-500"
                      />
                      {zh ? 'Cisco Enable 密码（可选）' : 'Cisco Enable Secret (optional)'}
                    </label>
                    {showEnableSecret && (
                      <div className="mt-2">
                        <PasswordField
                          label={zh ? 'Enable 密码' : 'Enable Secret'}
                          language={zh ? 'zh' : 'en'}
                          value={form.enable_password}
                          onChange={v => setForm(f => ({ ...f, enable_password: v }))}
                          placeholder={editingAsset ? (zh ? '留空不变' : 'Leave empty to keep') : (zh ? '输入 Enable 密码' : 'Enter enable secret')}
                        />
                      </div>
                    )}
                  </div>
                )}

                {(form.platform === 'windows' || form.platform === 'windows_server') && (
                  <div className="rounded-xl border border-blue-200 bg-blue-50/40 p-3">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-[11px] font-bold text-slate-700">Windows HTTPS</p>
                        <p className="text-[11px] text-slate-500">{zh ? '使用本地 Windows 账号通过 WinRM HTTPS 纳管；无需 AD 域。' : 'Manage with a local Windows account over WinRM HTTPS; no AD domain required.'}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setForm(f => ({ ...f, winrm_enabled: !f.winrm_enabled }))}
                        className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${form.winrm_enabled ? 'bg-blue-600 text-white' : 'bg-white text-slate-500 ring-1 ring-slate-200'}`}
                      >
                        {form.winrm_enabled ? (zh ? '已启用' : 'Enabled') : (zh ? '未启用' : 'Disabled')}
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <Field label="WinRM HTTPS Port" value={String(form.winrm_port || '5986')} onChange={v => setForm(f => ({ ...f, winrm_port: v, management_port: v }))} placeholder="5986" />
                      <div>
                        <label className="mb-0.5 block text-xs text-black/30">{zh ? '认证方式' : 'Authentication'}</label>
                        <select value={form.winrm_auth_mode || 'ntlm'} onChange={e => setForm(f => ({ ...f, winrm_auth_mode: e.target.value }))} className="w-full rounded-lg border border-black/8 bg-white px-2.5 py-1.5 text-xs text-black/65 outline-none">
                          <option value="ntlm">NTLM</option>
                          <option value="basic">Basic over HTTPS</option>
                        </select>
                      </div>
                      <div>
                        <label className="mb-0.5 block text-xs text-black/30">{zh ? 'TLS 校验' : 'TLS validation'}</label>
                        <select value={form.winrm_tls_mode || 'pin_fingerprint'} onChange={e => setForm(f => ({ ...f, winrm_tls_mode: e.target.value }))} className="w-full rounded-lg border border-black/8 bg-white px-2.5 py-1.5 text-xs text-black/65 outline-none">
                          <option value="pin_fingerprint">{zh ? '固定证书指纹' : 'Pin fingerprint'}</option>
                          <option value="verify_ca">{zh ? '系统 CA 校验' : 'Verify system CA'}</option>
                          <option value="insecure_lab">{zh ? '测试环境跳过校验' : 'Skip verification (lab)'}</option>
                        </select>
                      </div>
                      <Field label={zh ? 'SHA-256 证书指纹' : 'SHA-256 fingerprint'} value={form.winrm_cert_fingerprint || ''} onChange={v => setForm(f => ({ ...f, winrm_cert_fingerprint: v }))} placeholder="AA:BB:CC:..." />
                    </div>
                    {form.winrm_tls_mode === 'insecure_lab' && (
                      <p className="mt-2 text-[11px] font-medium text-amber-600">{zh ? '仅用于可信测试网络；正式环境建议保存证书指纹。' : 'Use only on a trusted lab network; pin the certificate in production.'}</p>
                    )}
                  </div>
                )}

                {showMoreAssetDetails && <AssetTagPicker tags={allTags} selectedIds={form.tag_ids || []} onChange={ids => setForm(f => ({ ...f, tag_ids: ids }))} onSave={handleSaveOnce} language={language} assetType={form.asset_type} />}

                {/* PAM Toggle */}
                <div className="nx-dialog-card mt-1 flex items-center justify-between rounded-lg border p-2.5">
                  <div className="flex items-center gap-2">
                    <Shield size={14} className="text-cyan-500" />
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-bold text-slate-700">{zh ? '多角色认证 (PAM)' : 'Multi-Role Auth (PAM)'}</p>
                        <span className="text-[11px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 font-bold border border-cyan-200">
                          {zh ? '强制启用' : 'Required'}
                        </span>
                        {editingAsset && (
                          <button
                            type="button"
                            onClick={async () => {
                              setModalError(null);
                              setFeedbackMsg({ type: 'info', text: zh ? '正在验证连通性...' : 'Verifying connectivity...' });
                              try {
                                const r = await fetch(`/api/assets/${editingAsset.id}/verify`, { headers: authHeaders() });
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
                            className="text-[11px] px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-700 hover:bg-cyan-200 transition-colors"
                          >
                            {zh ? '测试连通性' : 'Test Connectivity'}
                          </button>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-400">{zh ? '必须同时录入普通账户和管理员账户凭据，不允许单用户模式' : 'Both normal and admin credentials are required — single-user mode is not allowed'}</p>
                    </div>
                  </div>
                  <div className="p-1.5 rounded-full bg-cyan-100 text-cyan-600" title={zh ? 'PAM 双账户模式已强制启用' : 'PAM dual-account mode is enforced'}>
                    <Lock size={12} />
                  </div>
                </div>

                {/* Mode Selector */}
                <div role="group" aria-label={zh ? '凭据录入方式' : 'Credential entry mode'} className="flex gap-2 mb-2 rounded-lg border border-slate-200 bg-slate-100 p-1 text-xs font-semibold">
                  <button
                    type="button"
                    aria-pressed={credMode === 'manual'}
                    onClick={() => {
                      setCredMode('manual');
                      setForm(f => ({ ...f, credential_id: '', admin_credential_id: '' }));
                    }}
                    className={`min-h-9 flex-1 rounded-md border px-2 py-1.5 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 ${credMode === 'manual' ? 'border-cyan-200 bg-white text-slate-900 shadow-sm' : 'border-transparent text-slate-600 hover:bg-white/70 hover:text-slate-800'}`}
                  >
                    {zh ? '手动录入新凭据' : 'Manual Entry'}
                  </button>
                  <button
                    type="button"
                    aria-pressed={credMode === 'existing'}
                    onClick={() => {
                      setCredMode('existing');
                    }}
                    className={`min-h-9 flex-1 rounded-md border px-2 py-1.5 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 ${credMode === 'existing' ? 'border-cyan-200 bg-white text-slate-900 shadow-sm' : 'border-transparent text-slate-600 hover:bg-white/70 hover:text-slate-800'}`}
                  >
                    {zh ? '绑定已有凭据 (推荐)' : 'Select Existing'}
                  </button>
                </div>

                {credMode === 'existing' ? (
                  <div className="p-3 rounded-xl border border-black/5 bg-slate-50/30 space-y-2.5">
                    {form.auth_model === 'dual' ? (
                      <>
                        <div>
                          <label className="block text-xs font-bold text-black/50 mb-1">
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
                            className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-black/8 bg-white focus:outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20"
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
                          <label className="block text-xs font-bold text-black/50 mb-1">
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
                            className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-black/8 bg-white focus:outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20"
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
                        <label className="block text-xs font-bold text-black/50 mb-1">
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
                          className="w-full text-xs px-2.5 py-1.5 rounded-lg border border-black/8 bg-white focus:outline-none focus:border-[#00bceb] focus:ring-1 focus:ring-[#00bceb]/20"
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
                      <p className="text-[11px] text-emerald-600">
                        {zh ? '✓ 已成功选择并关联现有凭据' : '✓ Successfully linked to existing credential'}
                      </p>
                    )}
                  </div>
                ) : (
                  /* Dual-account credential inputs */
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3 rounded-xl border border-black/5 bg-slate-50/30">
                    <div className="space-y-2">
                      <p className="text-[11px] font-black uppercase tracking-widest text-blue-500">{zh ? '普通账户' : 'Normal Account'}</p>
                      <Field label={zh ? '用户名' : 'Username'} value={form.normal_username} onChange={v => setForm(f => ({ ...f, normal_username: v }))} placeholder="user" />
                      <PasswordField label={zh ? '密码' : 'Password'} language={zh ? 'zh' : 'en'} value={form.normal_password} onChange={v => setForm(f => ({ ...f, normal_password: v }))} placeholder={editingAsset ? (zh ? '留空不变' : 'Leave empty to keep') : ''} />
                    </div>
                    <div className="space-y-2">
                      <p className="text-[11px] font-black uppercase tracking-widest text-orange-500">{zh ? '特权账户' : 'Admin Account'}</p>
                      <Field label={zh ? '用户名' : 'Username'} value={form.admin_username} onChange={v => setForm(f => ({ ...f, admin_username: v }))} placeholder={form.asset_type === 'network_device' ? 'admin' : 'root'} />
                      <PasswordField label={zh ? '密码' : 'Password'} language={zh ? 'zh' : 'en'} value={form.admin_password} onChange={v => setForm(f => ({ ...f, admin_password: v }))} placeholder={editingAsset ? (zh ? '留空不变' : 'Leave blank to keep') : ''} />
                    </div>
                  </div>
                )}

                {form.asset_type === 'network_device' && (
                  <>
                    <div className="flex items-center gap-1.5 mt-2 mb-1">
                      <Wifi size={12} className="text-[#00bceb]/60" />
                      <span className="text-xs font-bold text-black/30 uppercase tracking-wider">SNMP</span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-2.5">
                      <div>
                        <Field label={zh ? '团体字' : 'Community'} value={form.snmp_community} onChange={v => setForm(f => ({ ...f, snmp_community: v }))} placeholder={snmpCommunityConfigured ? (zh ? '已安全存储，留空保持不变' : 'Configured; leave empty to keep') : (zh ? '可选' : 'Optional')} />
                        {snmpCommunityConfigured && <p className="mt-1 text-[11px] text-emerald-600">✓ {zh ? '已配置（不会回显明文）' : 'Configured (value is not revealed)'}</p>}
                      </div>
                      <Field label={zh ? '端口' : 'Port'} value={form.snmp_port} onChange={v => setForm(f => ({ ...f, snmp_port: v }))} placeholder="161" />
                      <div className="sm:col-span-2">
                        <label className="block text-xs text-black/30 mb-0.5">{zh ? 'SNMP 凭据' : 'SNMP Credential'}</label>
                        <select
                          value={form.snmp_credential_id || ''}
                          onChange={e => setForm(f => ({ ...f, snmp_credential_id: e.target.value }))}
                          className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
                        >
                          <option value="">{zh ? '使用资产本地 Community' : 'Use asset-local Community'}</option>
                          {snmpCredentials.map(c => (
                            <option key={c.id} value={c.id}>
                              {c.credential_name} ({String(c.credential_type || '').toLowerCase() === 'snmpv3'
                                ? `SNMPv3 ${c.snmp_security_level || 'authPriv'}`
                                : 'SNMPv2c'})
                            </option>
                          ))}
                        </select>
                        <p className="mt-1 text-[11px] text-black/30">{zh ? 'Nexora 后台将使用该 Profile 与管理 IP 执行设备识别和硬件采集；不会替换 SSH 登录凭据，密钥也不会回显。' : 'Nexora uses this profile with the management IP for device identification and hardware collection. It does not replace SSH credentials, and secrets are never revealed.'}</p>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {showMoreAssetDetails && <div className="sm:col-span-2 space-y-4 border-t border-black/5 pt-3">
            {/* ─── 服务器: 网络接入 ─── */}
            {form.asset_type === 'server' && (
              <>
                <div className="flex items-center gap-1.5 mt-4 mb-2">
                  <Network size={12} className="text-violet-400" />
                  <span className="text-xs font-bold text-black/30 uppercase tracking-wider">{zh ? '网络接入' : 'Network'}</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-2.5">
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
              <span className="text-xs font-bold text-black/30 uppercase tracking-wider">{zh ? '位置 & 资产' : 'Location & Asset'}</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-2.5">
              <div>
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '站点' : 'Site'}</label>
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
                      {site.site_name}
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
              <Field type="number" label={zh ? '设备高度(U)' : 'Height (U)'} value={form.u_height} onChange={v => setForm(f => ({ ...f, u_height: v }))} placeholder="1" disabled={isEditMode} />
              <Field type="number" label={zh ? '计划起始U(选填)' : 'Planned start U'} value={form.planned_start_u} onChange={v => setForm(f => ({ ...f, planned_start_u: v }))} placeholder="" />
              <Field label={zh ? '机位备注(选填)' : 'Location note'} value={form.rack_unit} onChange={v => setForm(f => ({ ...f, rack_unit: v }))} placeholder={zh ? '文本备注' : 'Optional note'} />
              <Field label={zh ? '部门/业务' : 'Service'} value={form.department} onChange={v => setForm(f => ({ ...f, department: v }))} />
              <DateTimePicker label={zh ? '购买日期' : 'Purchased'} value={form.purchase_date} onChange={v => setForm(f => ({ ...f, purchase_date: v }))} language={language} mode="date" />
              <DateTimePicker label={zh ? '保修到期' : 'Warranty'} value={form.warranty_expiry} onChange={v => setForm(f => ({ ...f, warranty_expiry: v }))} language={language} mode="date" />
              <div className="sm:col-span-2">
                <label className="block text-xs text-black/30 mb-0.5">{zh ? '备注' : 'Notes'}</label>
                <textarea
                  value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                  rows={2}
                  placeholder={zh ? '可选备注...' : 'Optional notes...'}
                  className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 placeholder:text-black/12 focus:outline-none focus:border-[#00bceb]/25 resize-none"
                />
              </div>
            </div>
            </div>}
            </FormSection>
          </div>

          {/* Sticky footer */}
          <FormActionBar className="nx-dialog-footer shrink-0 !flex-col !items-stretch !gap-0 !rounded-b-2xl !px-5 !py-3">
            {(modalError || uValidationError) && (
              <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700">
                <AlertCircle size={13} className="shrink-0 text-red-500" />
                <span className="text-xs font-medium flex-1">{modalError || uValidationError}</span>
                <button onClick={() => { setModalError(null); setUValidationError(null); }} title="Dismiss" className="p-0.5 text-red-400 hover:text-red-600 shrink-0"><X size={12} /></button>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="nx-dialog-action-secondary rounded-lg border px-3 py-1.5 text-xs">{zh ? '取消' : 'Cancel'}</button>
              <button
                onClick={handleSaveOnce}
                disabled={saving || (!isEditMode && !form.hostname.trim() && !form.asset_tag.trim()) || !!uValidationError || (!isEditMode && form.asset_origin === 'legacy' && form.lifecycle_status === 'production' && String(form.takeover_exempt_reason || '').trim().length < 5)}
                className="nx-dialog-action-primary rounded-lg border px-4 py-1.5 text-xs font-semibold disabled:opacity-50"
              >
                {saving ? (zh ? '保存中...' : 'Saving...') : (zh ? '保存' : 'Save')}
              </button>
            </div>
          </FormActionBar>

          {/* Production confirmation overlay */}
          {showProductionConfirm && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="absolute inset-0 z-10 flex items-center justify-center overflow-y-auto rounded-xl bg-slate-950/35 p-3"
            >
              <div className={`nx-dialog-card mx-2 max-h-full w-full overflow-y-auto rounded-lg border p-5 ${productionOnboardingBlocked ? 'max-w-2xl' : 'max-w-lg'}`}>
                {productionOnboardingBlocked ? (
                  <>
                    <div className="mb-2 flex items-center gap-2">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-50">
                        <AlertTriangle size={14} className="text-amber-500" />
                      </div>
                      <h4 className="text-sm font-bold text-black/80">{zh ? '设备尚未完成口令上手' : 'Device onboarding is incomplete'}</h4>
                    </div>
                    <p className="mb-3 text-xs leading-relaxed text-black/60">
                      {zh
                        ? `当前状态：${onboardingStatusLabel}。口令上收和免上收投产都要求先保存凭据并验证连通性。直接投产会被拒绝，表单不会保存。`
                        : `Current status: ${onboardingStatusLabel}. Both production paths require saved credentials and a verified connection. A direct production save will be rejected.`}
                    </p>
                    <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="rounded-lg border border-cyan-100 bg-cyan-50/60 p-3">
                        <p className="text-xs font-bold text-cyan-900">{zh ? '口令上收并投产' : 'Take over credentials and enter production'}</p>
                        <p className="mt-1 text-xs leading-4 text-cyan-900/75">
                          {zh
                            ? '验证现有账号后更换普通和特权账号密码，并把新凭据保存到 Nexora。'
                            : 'Verifies the current accounts, changes normal and privileged passwords, and stores the new credentials in Nexora.'}
                        </p>
                        <button type="button" disabled className="mt-2 w-full cursor-not-allowed rounded-lg bg-cyan-200 px-3 py-2 text-xs font-bold text-cyan-900/70">
                          {zh ? '完成凭据保存和连通性验证后可用' : 'Available after saving credentials and verifying connectivity'}
                        </button>
                      </div>
                      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                        <p className="text-xs font-bold text-amber-900">{zh ? '免上收投产，保留现有口令' : 'Enter production without takeover'}</p>
                        <p className="mt-1 text-xs leading-4 text-amber-900/75">
                          {zh
                            ? '不更改设备密码，但仍要先验证普通账号连通性；投产后记录豁免原因，设备不纳入 Nexora 托管。'
                            : 'Leaves device passwords unchanged, but still requires normal-account connectivity verification; the exemption is recorded and the device is not enrolled for Nexora management.'}
                        </p>
                        <button type="button" disabled className="mt-2 w-full cursor-not-allowed rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-bold text-amber-800/60">
                          {zh ? '免上收投产（验证通过后启用）' : 'Skip takeover (available after verification)'}
                        </button>
                        <p className="mt-1 text-xs leading-4 text-amber-800">
                          {editingAsset?.asset_origin === 'legacy'
                            ? (zh ? '当前设备尚未完成连通性验证，因此暂不可执行。' : 'Connectivity is not verified yet, so this action is unavailable.')
                            : (zh ? '此方式仅适用于录入来源为“存量设备”的资产。' : 'This option is only available for assets entered as legacy devices.')}
                        </p>
                      </div>
                    </div>
                    <div className="mb-4 rounded-lg border border-cyan-100 bg-cyan-50/70 px-3 py-2 text-[11px] leading-5 text-cyan-900">
                      {zh
                        ? '下一步：先保存表单并保持“待投产”，再到设备详情完成连通性验证。验证通过后重新选择投产，即可使用上面符合条件的方式。'
                        : 'Next: save the form while keeping the asset in staging, then verify connectivity from device details. After verification, reopen production to use an eligible option above.'}
                    </div>
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => setShowProductionConfirm(false)}
                        className="rounded-lg border border-black/10 px-3 py-2 text-xs text-black/55 hover:bg-black/[0.02]"
                      >
                        {zh ? '返回编辑' : 'Back to editing'}
                      </button>
                      <button
                        onClick={() => {
                          setShowProductionConfirm(false);
                          doSaveOnce({ lifecycle_status: editingAsset?.lifecycle_status || 'staging' });
                        }}
                        disabled={saving}
                        className="nx-dialog-action-primary rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50"
                      >
                        {saving ? (zh ? '保存中...' : 'Saving...') : (zh ? '保存表单并保持待投产' : 'Save and keep in staging')}
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="mb-2 flex items-center gap-2">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-50">
                        <AlertTriangle size={14} className="text-amber-500" />
                      </div>
                      <h4 className="text-sm font-bold text-black/80">{zh ? '选择投产方式' : 'Choose a production path'}</h4>
                    </div>
                    <p className="mb-3 text-xs leading-relaxed text-black/55">
                      {zh
                        ? '两种方式都要求凭据已保存且连通性验证通过。请选择你确实要执行的设备生命周期操作。'
                        : 'Both options require saved credentials and a verified connection. Choose the lifecycle action you intend to perform.'}
                    </p>
                    <div className="mb-3 rounded-lg border border-cyan-100 bg-cyan-50/60 p-3">
                      <p className="text-xs font-bold text-cyan-900">{zh ? '口令上收并投产' : 'Take over credentials and enter production'}</p>
                      <p className="mt-1 text-xs leading-4 text-cyan-900/75">
                        {zh
                          ? '会验证现有账号，然后更换普通和特权账号的设备密码，并将新凭据安全保存到 Nexora。'
                          : 'Verifies the current accounts, changes the device passwords for normal and privileged accounts, and stores the new credentials in Nexora.'}
                      </p>
                      <button
                        onClick={() => { setShowProductionConfirm(false); doSaveOnce({ production_mode: 'takeover' }); }}
                        disabled={saving}
                        className="nx-dialog-action-primary mt-2 w-full rounded-lg border px-3 py-2 text-xs font-semibold disabled:opacity-50"
                      >
                        {saving ? (zh ? '处理中...' : 'Processing...') : (zh ? '执行口令上收并投产（会更改设备密码）' : 'Take over and produce (changes device passwords)')}
                      </button>
                    </div>
                    <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                      <p className="text-xs font-bold text-amber-900">{zh ? '免上收投产，保留现有口令' : 'Enter production without takeover'}</p>
                      <p className="mt-1 text-xs leading-4 text-amber-900/75">
                        {zh
                          ? '仅适用于录入时标记为存量的设备：不会更改设备密码，但会记录豁免原因，且设备不会纳入 Nexora 托管。'
                          : 'For legacy assets only. Device passwords stay unchanged; the exemption is recorded and the asset is not enrolled for Nexora management.'}
                      </p>
                      {editingAsset?.asset_origin === 'legacy' ? (
                        <>
                          <textarea
                            value={legacyExemptReason}
                            onChange={event => setLegacyExemptReason(event.target.value)}
                            rows={2}
                            aria-label={zh ? '免上收原因' : 'Exemption reason'}
                            placeholder={zh ? '填写免上收原因（至少 5 个字符）' : 'Reason for skipping takeover (minimum 5 characters)'}
                            className="mt-2 w-full resize-none rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs text-black/70 outline-none focus:border-amber-400"
                          />
                          <button
                            onClick={() => {
                              setShowProductionConfirm(false);
                              doSaveOnce({ production_mode: 'legacy_exempt', takeover_exempt_reason: legacyExemptReason.trim() });
                            }}
                            disabled={saving || legacyExemptReason.trim().length < 5}
                            className="mt-2 w-full rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-bold text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            {zh ? '记录免上收并投产（不更改设备密码）' : 'Record exemption and produce (no password change)'}
                          </button>
                        </>
                      ) : (
                        <p className="mt-2 text-xs text-amber-800">{zh ? '仅录入时标记为“存量设备”的资产可使用免上收投产。' : 'Only assets marked as legacy during creation can use this option.'}</p>
                      )}
                    </div>
                    <button
                      onClick={() => setShowProductionConfirm(false)}
                      className="mt-3 w-full rounded-lg border border-black/10 px-3 py-2 text-xs text-black/55 hover:bg-black/[0.02]"
                    >
                      {zh ? '取消，返回资产表单' : 'Cancel and return to the asset form'}
                    </button>
                  </>
                )}
              </div>
            </motion.div>
          )}
        </div>
      </div>
      {showWebProfilesDialog && (
        <motion.div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/35 p-3 sm:p-5"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={event => { event.stopPropagation(); cancelWebProfilesDialog(); }}
        >
          <motion.div
            ref={webProfilesDialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={webProfilesDialogTitleId}
            className="nx-form-dialog-surface flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={event => event.stopPropagation()}
          >
            <div className="nx-dialog-header flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-cyan-50 text-cyan-600"><Globe2 size={16} /></span>
                <div className="min-w-0">
                  <h3 id={webProfilesDialogTitleId} className="text-sm font-bold text-slate-800">{zh ? '配置 Web 管理入口' : 'Configure Web management entries'}</h3>
                  <p className="truncate text-xs text-slate-400">{zh ? '管理 IP 使用资产表单中的管理 IP；在这里设置协议、端口、路径和登录凭据。' : 'The management IP comes from the asset form. Set protocol, port, path and login credentials here.'}</p>
                </div>
              </div>
              <button type="button" onClick={cancelWebProfilesDialog} aria-label={zh ? '关闭' : 'Close'} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X size={16} /></button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs leading-4 text-slate-500">{zh ? '这里只保存入口信息；实际登录请到“操作工作台 → WEB”发起 PAM 会话。' : 'This saves entry details only. Start the PAM session from Operation Workspace → WEB.'}</p>
                <button type="button" onClick={() => setWebProfilesDraft(current => [...current, createDefaultWebProfile(form.asset_type)])} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-cyan-200 bg-white px-2.5 py-1.5 text-xs font-bold text-cyan-700 hover:bg-cyan-50"><Plus size={12} />{zh ? '添加入口' : 'Add entry'}</button>
              </div>
              {webProfilesDraft.length === 0 ? (
                <div className="rounded-xl border border-dashed border-cyan-200 px-4 py-8 text-center text-xs text-slate-400">{zh ? '还没有入口。添加一个 Web 管理入口，或关闭弹窗保持未配置。' : 'No entry configured. Add a Web entry or close this dialog to leave it unconfigured.'}</div>
              ) : webProfilesDraft.map((profile: any, index: number) => (
                <section key={profile.id || `web-profile-${index}`} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3 sm:p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{zh ? `入口 ${index + 1}` : `Entry ${index + 1}`}</span>
                    <ActionIconButton icon={Trash2} label={zh ? '删除入口' : 'Remove entry'} size="xs" variant="danger" onClick={() => setWebProfilesDraft(current => current.filter((_: any, itemIndex: number) => itemIndex !== index))} />
                  </div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-12">
                    <div className="sm:col-span-4"><Field label={zh ? '入口名称' : 'Name'} value={profile.profile_name || ''} onChange={value => updateWebProfileDraft(index, { profile_name: value })} placeholder={form.asset_type === 'server' ? 'iDRAC / iLO' : 'Web管理'} /></div>
                    <div className="sm:col-span-2">
                      <label className="mb-0.5 block text-xs text-black/40">{zh ? '协议' : 'Protocol'}</label>
                      <select value={profile.scheme || 'https'} onChange={event => {
                        const scheme = event.target.value as 'http' | 'https';
                        const oldDefault = scheme === 'https' ? '80' : '443';
                        updateWebProfileDraft(index, { scheme, port: String(profile.port) === oldDefault ? (scheme === 'https' ? '443' : '80') : profile.port });
                      }} className="w-full rounded-lg border border-black/10 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400">
                        <option value="https">HTTPS</option><option value="http">HTTP</option>
                      </select>
                    </div>
                    <div className="sm:col-span-2"><Field label={zh ? '端口' : 'Port'} value={String(profile.port || '')} onChange={value => updateWebProfileDraft(index, { port: value })} placeholder={profile.scheme === 'http' ? '80' : '443'} /></div>
                    <div className="sm:col-span-4"><Field label={zh ? '登录路径' : 'Login path'} value={profile.path || '/'} onChange={value => updateWebProfileDraft(index, { path: value })} placeholder="/ or /login" /></div>
                    <div className="sm:col-span-12 truncate rounded-lg bg-cyan-50 px-2.5 py-2 text-xs text-cyan-800">
                      {zh ? '最终地址：' : 'Final URL: '}{`${profile.scheme || 'https'}://${form.management_ip || (zh ? '管理IP' : '<mgmt-ip>')}:${profile.port || (profile.scheme === 'http' ? '80' : '443')}${String(profile.path || '/').startsWith('/') ? (profile.path || '/') : `/${profile.path || ''}`}`}
                    </div>
                    <div className="sm:col-span-12 rounded-xl border border-slate-200 bg-white p-3">
                      <label className="mb-1 block text-xs font-semibold text-slate-500">{zh ? 'Web 凭据模式' : 'Web credential mode'}</label>
                      <select value={profile.credential_mode || 'inherit_asset'} onChange={event => updateWebProfileDraft(index, { credential_mode: event.target.value })} className="w-full rounded-lg border border-black/10 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400">
                        <option value="inherit_asset">{zh ? '继承资产凭据' : 'Inherit asset credentials'}</option>
                        <option value="independent">{zh ? '独立 Web 凭据' : 'Independent Web credentials'}</option>
                      </select>
                      {(profile.credential_mode || 'inherit_asset') === 'independent' && (
                        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                          <Field label={zh ? '普通用户' : 'Normal user'} value={profile.normal_username || ''} onChange={value => updateWebProfileDraft(index, { normal_username: value })} />
                          <PasswordField label={zh ? '普通密码' : 'Normal password'} language={zh ? 'zh' : 'en'} value={profile.normal_password || ''} onChange={value => updateWebProfileDraft(index, { normal_password: value })} placeholder={profile.normal_password_set ? (zh ? '已配置，留空不变' : 'Configured; leave blank to keep') : ''} />
                          <Field label={zh ? '特权用户' : 'Admin user'} value={profile.admin_username || ''} onChange={value => updateWebProfileDraft(index, { admin_username: value })} />
                          <PasswordField label={zh ? '特权密码' : 'Admin password'} language={zh ? 'zh' : 'en'} value={profile.admin_password || ''} onChange={value => updateWebProfileDraft(index, { admin_password: value })} placeholder={profile.admin_password_set ? (zh ? '已配置，留空不变' : 'Configured; leave blank to keep') : ''} />
                          <div>
                            <label className="mb-1 block text-xs font-semibold text-slate-500">{zh ? '绑定普通凭据' : 'Normal credential'}</label>
                            <select value={profile.credential_id || ''} onChange={event => updateWebProfileDraft(index, { credential_id: event.target.value })} className="w-full rounded-lg border border-black/10 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400">
                              <option value="">{zh ? '不绑定' : 'Not bound'}</option>
                              {credentials.filter(c => !String(c.credential_type || '').toLowerCase().startsWith('snmp')).map(c => <option key={c.id} value={c.id}>{c.credential_name} ({c.username || '-'})</option>)}
                            </select>
                          </div>
                          <div>
                            <label className="mb-1 block text-xs font-semibold text-slate-500">{zh ? '绑定特权凭据' : 'Admin credential'}</label>
                            <select value={profile.admin_credential_id || ''} onChange={event => updateWebProfileDraft(index, { admin_credential_id: event.target.value })} className="w-full rounded-lg border border-black/10 bg-white px-2.5 py-2 text-xs text-slate-700 outline-none focus:border-cyan-400">
                              <option value="">{zh ? '不绑定' : 'Not bound'}</option>
                              {credentials.filter(c => !String(c.credential_type || '').toLowerCase().startsWith('snmp')).map(c => <option key={c.id} value={c.id}>{c.credential_name} ({c.username || '-'})</option>)}
                            </select>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </section>
              ))}
              {webProfilesDraft.some((profile: any) => profile.scheme === 'http') && <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-4 text-amber-800">{zh ? 'HTTP 会明文传输页面内容和用户输入，请仅用于不支持 HTTPS 的旧设备。' : 'HTTP transmits page content and user input in clear text; use it only for legacy devices.'}</p>}
            </div>
            <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-white px-4 py-3 sm:px-5">
              <button type="button" onClick={cancelWebProfilesDialog} className="nx-dialog-action-secondary rounded-lg border px-3 py-2 text-xs font-medium">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" onClick={() => { setForm((current: any) => ({ ...current, web_profiles: webProfilesDraft.map(profile => ({ ...profile })) })); webProfilesBeforeDialogRef.current = null; setShowWebProfilesDialog(false); }} className="nx-dialog-action-primary rounded-lg border px-4 py-2 text-xs font-semibold">{zh ? '完成' : 'Done'}</button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

/* --- Form field --- */
function Field({ label, value, onChange, placeholder, helper, type = 'text', list, error, action, disabled = false }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; helper?: string; type?: string; list?: string; error?: string | null; action?: React.ReactNode; disabled?: boolean;
}) {
  const inputId = React.useId();
  const helperId = helper ? `${inputId}-helper` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [helperId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <label htmlFor={inputId} className="block text-xs font-medium text-[var(--ui-fg-muted)]">{label}</label>
        <div className="flex items-center gap-1.5">
          {action}
          {error && <span id={errorId} className="text-[11px] text-red-600 font-medium">{error}</span>}
        </div>
      </div>
      <input
        id={inputId}
        type={type}
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        list={list}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        className={`w-full bg-white border rounded-lg px-2.5 py-1.5 text-xs text-black/65 placeholder:text-black/12 disabled:bg-black/[0.03] disabled:text-black/35 disabled:cursor-not-allowed focus:outline-none ${
          error ? 'border-red-400 bg-red-50/20 focus:border-red-500' : 'border-black/8 focus:border-[#00bceb]/25'
        }`}
      />
      {helper && <p id={helperId} className="mt-1 text-[11px] leading-4 text-[var(--ui-fg-muted)]">{helper}</p>}
    </div>
  );
}

function SelectField({ label, value, onChange, options, language }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: ReadonlyArray<{ readonly value: string; readonly label: { readonly zh: string; readonly en: string } }>;
  language: string;
}) {
  const labelKey = language === 'zh' ? 'zh' : 'en';
  const hasCurrentValue = !value || options.some(option => option.value === value);
  const inputId = React.useId();
  return (
    <div>
      <label htmlFor={inputId} className="mb-1 block text-xs font-medium text-[var(--ui-fg-muted)]">{label}</label>
      <select
        id={inputId}
        value={value}
        onChange={event => onChange(event.target.value)}
        className="w-full bg-white border border-black/8 rounded-lg px-2.5 py-1.5 text-xs text-black/65 focus:outline-none focus:border-[#00bceb]/25"
      >
        <option value="">{language === 'zh' ? '请选择...' : 'Select...'}</option>
        {!hasCurrentValue && <option value={value}>{value}</option>}
        {options.map(option => (
          <option key={option.value} value={option.value}>{option.label[labelKey]}</option>
        ))}
      </select>
    </div>
  );
}

/* --- Password field --- */
function PasswordField({ label, value, onChange, placeholder, language }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; language: 'zh' | 'en';
}) {
  const inputId = React.useId();
  return (
    <div>
      <label htmlFor={inputId} className="mb-1 block text-xs font-medium text-[var(--ui-fg-muted)]">{label}</label>
      <PasswordInputField
        id={inputId}
        autoComplete="new-password"
        showPasswordLabel={language === 'zh' ? `显示${label}` : `Show ${label}`}
        hidePasswordLabel={language === 'zh' ? `隐藏${label}` : `Hide ${label}`}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="rounded-lg bg-white text-xs text-black/65 placeholder:text-black/12 focus:border-[#00bceb]/25"
      />
    </div>
  );
}
