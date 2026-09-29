import { DataTable } from './DataTable';
import React, { useState, useCallback, useEffect, useMemo } from 'react';
import Pagination from './Pagination';
import PageHero from './PageHero';
import { motion } from 'motion/react';
import {
  RefreshCw, Shield, Loader2, Search, ShieldCheck, ShieldAlert, ShieldX,
  Key, KeyRound, User, Eye, EyeOff, Copy, Check, X, LockKeyhole, SlidersHorizontal, ChevronDown,
} from 'lucide-react';
import { ActionIconButton } from './ui/ActionIconButton';
import { PasswordInputField } from './ui/PasswordInputField';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { buildPasswordRotationExportData, buildRotationExportRow, type RotationExportGroup } from './PasswordRotationPanel.export';

interface RotationDevice {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  auth_model: string;
  username?: string;
  credential_id?: string;
  admin_credential_id?: string;
  
  // Normal
  normal_username: string;
  normal_password_last_rotated: string;
  normal_password_expires_at: string;
  normal_password_days_remaining: number | null;
  normal_password_expired: boolean;
  
  // Admin
  admin_username: string;
  admin_password_last_rotated: string;
  admin_password_expires_at: string;
  admin_password_days_remaining: number | null;
  admin_password_expired: boolean;
  
  // Enable
  enable_password_last_rotated: string;
  enable_password_expires_at: string;
  enable_password_days_remaining: number | null;
  enable_password_expired: boolean;
}

interface RotationDeviceSummary {
  id: string;
  hostname: string;
  ip_address: string;
  platform: string;
}

interface RotationCredentialGroup {
  key: string;
  credentialId: string;
  credentialName: string;
  username: string;
  isCredential: boolean;
  accounts: any[];
  devices: RotationDeviceSummary[];
}

interface RotationDevicePage {
  items: RotationDeviceSummary[];
  total: number;
  page: number;
  page_size: number;
}

interface PasswordRotationPanelProps {
  language: string;
  currentUser?: { role?: string };
}

const API_BASE = import.meta.env.VITE_API_BASE || '';

const isServer = (p: string): boolean => {
  const platform = (p || '').toLowerCase();
  return platform.includes('linux') || platform.includes('ubuntu') || platform.includes('centos') || platform.includes('server') || platform.includes('debian');
};

const rotationStatus = (account: { currentExpired?: boolean; currentDays?: number | null; currentLastRotated?: string | null }, zh: boolean) => {
  const days = typeof account.currentDays === 'number' ? account.currentDays : null;
  if (account.currentExpired || (days !== null && days < 0)) {
    return { label: zh ? '已过期' : 'Expired', className: 'border-rose-200 bg-rose-50 text-rose-700' };
  }
  if (days !== null && days <= 14) {
    return { label: zh ? `剩余 ${days} 天` : `${days}d left`, className: 'border-amber-200 bg-amber-50 text-amber-700' };
  }
  if (days !== null) {
    return { label: zh ? '状态正常' : 'Healthy', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' };
  }
  return {
    label: account.currentLastRotated ? (zh ? '未配置周期' : 'Cycle not set') : (zh ? '未曾轮换' : 'Never rotated'),
    className: 'border-slate-200 bg-slate-100 text-slate-600',
  };
};

const roleRotationStatus = (accounts: Array<{ currentExpired?: boolean; currentDays?: number | null; currentLastRotated?: string | null }>, zh: boolean) => {
  const remainingDays = accounts.reduce<number | null>((nearest, account) => {
    if (typeof account.currentDays !== 'number') return nearest;
    return nearest === null ? account.currentDays : Math.min(nearest, account.currentDays);
  }, null);
  return rotationStatus({
    currentExpired: accounts.some(account => account.currentExpired || (typeof account.currentDays === 'number' && account.currentDays < 0)),
    currentDays: remainingDays,
    currentLastRotated: accounts.some(account => Boolean(account.currentLastRotated)) ? accounts[0]?.currentLastRotated : null,
  }, zh);
};

type StatusFilter = 'all' | 'healthy' | 'expiring' | 'expired' | 'unconfigured';
type TargetFilter = 'all' | 'credential' | 'unbound';
type RoleFilter = 'all' | 'normal' | 'admin' | 'enable';

export default function PasswordRotationPanel({ language, currentUser }: PasswordRotationPanelProps) {
  const zh = language === 'zh';
  const isAdministrator = String(currentUser?.role || '').trim().toLowerCase() === 'administrator';
  const [devices, setDevices] = useState<RotationDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [targetFilter, setTargetFilter] = useState<TargetFilter>('all');
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deviceDrawerGroup, setDeviceDrawerGroup] = useState<RotationCredentialGroup | null>(null);
  const [deviceSearchDraft, setDeviceSearchDraft] = useState('');
  const [deviceSearch, setDeviceSearch] = useState('');
  const [devicePlatform, setDevicePlatform] = useState('');
  const [devicePage, setDevicePage] = useState(1);
  const [devicePageSize, setDevicePageSize] = useState(20);
  const [devicePageData, setDevicePageData] = useState<RotationDevicePage | null>(null);
  const [deviceListLoading, setDeviceListLoading] = useState(false);
  const [deviceListError, setDeviceListError] = useState('');
  const [deviceRequestVersion, setDeviceRequestVersion] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [revealedSecret, setRevealedSecret] = useState<{ id: string; type: 'password' | 'enable_password'; secret: string } | null>(null);
  const [secretLoading, setSecretLoading] = useState<string | null>(null);
  const [secretCopied, setSecretCopied] = useState(false);
  const [localRevealedSecret, setLocalRevealedSecret] = useState<{ deviceId: string; role: 'normal' | 'admin' | 'enable'; secret: string } | null>(null);
  const [localSecretLoading, setLocalSecretLoading] = useState<string | null>(null);
  const [localSecretCopied, setLocalSecretCopied] = useState(false);
  const [editingCredential, setEditingCredential] = useState<{ id: string; type: 'password' | 'enable_password'; label: string; username: string; deviceName: string } | null>(null);
  const [credentialForm, setCredentialForm] = useState({ oldSecret: '', newSecret: '' });
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialError, setCredentialError] = useState('');
  const [notice, setNotice] = useState('');
  const [pendingRotation, setPendingRotation] = useState<any | null>(null);
  const [rotatingPassword, setRotatingPassword] = useState(false);
  const [bulkRole, setBulkRole] = useState<'normal' | 'admin' | 'enable'>('admin');
  const [showBulkConfirm, setShowBulkConfirm] = useState(false);
  useEscapeClose(showBulkConfirm, () => setShowBulkConfirm(false));
  useEscapeClose(Boolean(pendingRotation) && !rotatingPassword, () => setPendingRotation(null));
  useEscapeClose(Boolean(editingCredential) && !credentialSaving, () => setEditingCredential(null));
  useEscapeClose(Boolean(deviceDrawerGroup), () => setDeviceDrawerGroup(null));
  const [bulkProgress, setBulkProgress] = useState<any | null>(null);

  const credentialRoleFor = (account: any): string => {
    if (account.roleKey === 'admin' || account.roleKey === 'enable') {
      return String(account.admin_credential_account_role || 'unbound').trim().toLowerCase();
    }
    return String(account.credential_account_role || 'unbound').trim().toLowerCase();
  };

  const isSharedCredentialAccount = (account: any): boolean => {
    const id = account.roleKey === 'admin' || account.roleKey === 'enable'
      ? account.admin_credential_id
      : account.credential_id;
    return Boolean(id && credentialRoleFor(account) !== 'unbound');
  };

  const credentialIdFor = (account: any): string => {
    if (!isSharedCredentialAccount(account)) return '';
    if (account.roleKey === 'admin' || account.roleKey === 'enable') {
      return String(account.admin_credential_id || '');
    }
    return String(account.credential_id || '');
  };

  const credentialNameFor = (account: any): string => {
    if (account.roleKey === 'admin' || account.roleKey === 'enable') {
      return String(account.admin_credential_name || '');
    }
    return String(account.credential_name || '');
  };

  const revealCredentialSecret = async (account: any, type: 'password' | 'enable_password') => {
    if (!isAdministrator) return;
    const id = credentialIdFor(account);
    if (!id) return;
    if (revealedSecret?.id === id && revealedSecret.type === type) {
      setRevealedSecret(null);
      setSecretCopied(false);
      return;
    }
    const key = `${id}:${type}`;
    setSecretLoading(key);
    setSecretCopied(false);
    setCredentialError('');
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(`${API_BASE}/api/credentials/${encodeURIComponent(id)}/secret?type=${encodeURIComponent(type)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) throw new Error(payload.detail || payload.message || (zh ? '凭据密码读取失败' : 'Unable to read credential secret'));
      setRevealedSecret({ id, type, secret: String(payload.data?.secret || '') });
    } catch (error: any) {
      setCredentialError(error.message || String(error));
    } finally {
      setSecretLoading(null);
    }
  };

  const copyRevealedSecret = async () => {
    if (!revealedSecret?.secret) return;
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(`${API_BASE}/api/credentials/${encodeURIComponent(revealedSecret.id)}/secret/copy?type=${encodeURIComponent(revealedSecret.type)}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) throw new Error(payload.detail || payload.message || (zh ? '复制审计失败' : 'Copy audit failed'));
      await navigator.clipboard.writeText(revealedSecret.secret);
      setSecretCopied(true);
      window.setTimeout(() => setSecretCopied(false), 2000);
    } catch (error: any) {
      setCredentialError(error.message || String(error));
    }
  };

  const revealDeviceLocalSecret = async (account: any) => {
    if (!isAdministrator || !account?.id) return;
    const role = account.roleKey as 'normal' | 'admin' | 'enable';
    const key = `${account.id}:${role}`;
    if (localRevealedSecret?.deviceId === account.id && localRevealedSecret.role === role) {
      setLocalRevealedSecret(null);
      setLocalSecretCopied(false);
      return;
    }
    setLocalSecretLoading(key);
    setLocalSecretCopied(false);
    setCredentialError('');
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(`${API_BASE}/api/devices/${encodeURIComponent(account.id)}/reveal-password?role=${encodeURIComponent(role)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) throw new Error(payload.detail || payload.message || (zh ? '设备本地密码读取失败' : 'Unable to read device-local password'));
      setLocalRevealedSecret({ deviceId: account.id, role, secret: String(payload.data?.password || '') });
    } catch (error: any) {
      setCredentialError(error.message || String(error));
    } finally {
      setLocalSecretLoading(null);
    }
  };

  const copyDeviceLocalSecret = async () => {
    if (!localRevealedSecret?.secret) return;
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(`${API_BASE}/api/devices/${encodeURIComponent(localRevealedSecret.deviceId)}/reveal-password/copy?role=${encodeURIComponent(localRevealedSecret.role)}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) throw new Error(payload.detail || payload.message || (zh ? '复制审计失败' : 'Copy audit failed'));
      await navigator.clipboard.writeText(localRevealedSecret.secret);
      setLocalSecretCopied(true);
      window.setTimeout(() => setLocalSecretCopied(false), 2000);
    } catch (error: any) {
      setCredentialError(error.message || String(error));
    }
  };

  const openDeviceDrawer = (group: RotationCredentialGroup) => {
    setDeviceDrawerGroup(group);
    setDeviceSearchDraft('');
    setDeviceSearch('');
    setDevicePlatform('');
    setDevicePage(1);
    setDevicePageSize(20);
    setDevicePageData(null);
    setDeviceListError('');
  };

  const openCredentialEditor = (account: any, type: 'password' | 'enable_password') => {
    if (!isAdministrator) return;
    const id = credentialIdFor(account);
    if (!id) return;
    setCredentialError('');
    setNotice('');
    setCredentialForm({ oldSecret: '', newSecret: '' });
    setEditingCredential({
      id,
      type,
      label: type === 'enable_password' ? (zh ? 'Enable 密码' : 'Enable password') : (account.roleKey === 'admin' ? (zh ? '特权账号密码' : 'Privileged password') : (zh ? '普通账号密码' : 'Normal account password')),
      username: String(account.currentUsername || '-'),
      deviceName: String(account.hostname || account.ip_address || account.id || ''),
    });
  };

  const submitCredentialUpdate = async () => {
    if (!editingCredential || credentialSaving) return;
    if (!credentialForm.oldSecret || !credentialForm.newSecret) {
      setCredentialError(zh ? '请输入旧密码和新密码。' : 'Enter both the current and new passwords.');
      return;
    }
    setCredentialSaving(true);
    setCredentialError('');
    try {
      const token = localStorage.getItem('netops_token') || '';
      const body = editingCredential.type === 'enable_password'
        ? { old_enable_password: credentialForm.oldSecret, enable_password: credentialForm.newSecret }
        : { old_password: credentialForm.oldSecret, password: credentialForm.newSecret };
      const response = await fetch(`${API_BASE}/api/credentials/${encodeURIComponent(editingCredential.id)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) throw new Error(payload.detail || payload.message || (zh ? '凭据密码更新失败' : 'Credential password update failed'));
      setEditingCredential(null);
      setCredentialForm({ oldSecret: '', newSecret: '' });
      setNotice(payload.job_id
        ? (zh ? `凭据密码更新任务已提交，将同步 ${payload.device_count || 0} 台关联设备。` : `Credential password update queued for ${payload.device_count || 0} bound devices.`)
        : (zh ? '凭据中心密码已更新。' : 'Credential center password updated.'));
      await fetchStatus();
    } catch (error: any) {
      const raw = String(error.message || error);
      setCredentialError(raw.includes('old_password is incorrect')
        ? (zh ? '当前密码不正确，请确认输入的是凭据中心中保存的旧密码。' : 'The current password is incorrect.')
        : raw.includes('old_enable_password is incorrect')
          ? (zh ? '当前 Enable 密码不正确，请确认输入的是凭据中心中保存的旧 Enable 密码。' : 'The current Enable password is incorrect.')
          : raw);
    } finally {
      setCredentialSaving(false);
    }
  };

  const rotateDevicePassword = async () => {
    if (!pendingRotation || rotatingPassword) return;
    setRotatingPassword(true);
    setCredentialError('');
    setNotice('');
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(
        `${API_BASE}/api/devices/${encodeURIComponent(pendingRotation.id)}/rotate-password?role=${encodeURIComponent(pendingRotation.roleKey)}`,
        { method: 'POST', headers: { Authorization: `Bearer ${token}` } },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) {
        throw new Error(payload.message || payload.detail || (zh ? '设备密码轮换失败' : 'Device password rotation failed'));
      }
      setNotice(zh
        ? `${pendingRotation.hostname || pendingRotation.ip_address} 的${pendingRotation.roleLabel}已完成轮换并验证。`
        : `${pendingRotation.roleLabel} password rotated and verified for ${pendingRotation.hostname || pendingRotation.ip_address}.`);
      setPendingRotation(null);
      await fetchStatus();
    } catch (rotationError: any) {
      setCredentialError(rotationError.message || String(rotationError));
    } finally {
      setRotatingPassword(false);
    }
  };

  const startBulkRotation = async () => {
    if (bulkProgress?.status === 'running' || bulkProgress?.status === 'starting') return;
    setShowBulkConfirm(false);
    setCredentialError('');
    setNotice('');
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(
        `${API_BASE}/api/devices/rotation/rotate-all?role=${encodeURIComponent(bulkRole)}`,
        { method: 'POST', headers: { Authorization: `Bearer ${token}` } },
      );
      const payload = await response.json().catch(() => ({}));
      const runId = String(payload.data?.run_id || '');
      if (!response.ok || !payload.success || !runId) {
        throw new Error(payload.message || payload.detail || (zh ? '批量轮换启动失败' : 'Failed to start bulk rotation'));
      }
      setBulkProgress({ status: 'starting', run_id: runId, total: 0, done: 0, rotated: 0, failed: 0 });

      for (let attempt = 0; attempt < 200; attempt += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 1500));
        const progressResponse = await fetch(
          `${API_BASE}/api/devices/rotation/rotate-all/${encodeURIComponent(runId)}/progress`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        const progressPayload = await progressResponse.json().catch(() => ({}));
        if (!progressResponse.ok || !progressPayload.success) continue;
        const progress = progressPayload.data || {};
        setBulkProgress(progress);
        if (progress.status === 'completed') {
          setNotice(zh
            ? `批量轮换完成：成功 ${progress.rotated || 0}，失败 ${progress.failed || 0}。`
            : `Bulk rotation completed: ${progress.rotated || 0} succeeded, ${progress.failed || 0} failed.`);
          await fetchStatus();
          return;
        }
      }
      throw new Error(zh ? '批量轮换仍在后台执行，请稍后刷新状态。' : 'Bulk rotation is still running; refresh status later.');
    } catch (bulkError: any) {
      setCredentialError(bulkError.message || String(bulkError));
    }
  };

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem('netops_token') || '';
      const resp = await fetch(`${API_BASE}/api/devices/rotation/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (data.success) {
        setDevices(data.data || []);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);
  useEffect(() => { setPage(1); }, [roleFilter, search, statusFilter, targetFilter]);

  const activeDeviceCredentialId = deviceDrawerGroup?.isCredential ? deviceDrawerGroup.credentialId : '';
  useEffect(() => {
    if (!activeDeviceCredentialId) {
      setDevicePageData(null);
      setDeviceListLoading(false);
      return;
    }

    const controller = new AbortController();
    const params = new URLSearchParams({
      page: String(devicePage),
      page_size: String(devicePageSize),
    });
    if (deviceSearch) params.set('keyword', deviceSearch);
    if (devicePlatform) params.set('platform', devicePlatform);

    const token = localStorage.getItem('netops_token') || '';
    setDeviceListLoading(true);
    setDeviceListError('');
    setDevicePageData(null);
    fetch(`${API_BASE}/api/devices/rotation/credentials/${encodeURIComponent(activeDeviceCredentialId)}/devices?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async response => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success || !Array.isArray(payload.data?.items)) {
          throw new Error(payload.detail || payload.message || (zh ? '关联设备加载失败' : 'Failed to load linked devices'));
        }
        return payload.data as RotationDevicePage;
      })
      .then(data => setDevicePageData(data))
      .catch((requestError: unknown) => {
        if (controller.signal.aborted) return;
        setDeviceListError(requestError instanceof Error ? requestError.message : String(requestError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDeviceListLoading(false);
      });

    return () => controller.abort();
  }, [activeDeviceCredentialId, devicePage, devicePageSize, devicePlatform, deviceRequestVersion, deviceSearch, zh]);

  /* ── computed stats ── */
  const stats = useMemo(() => {
    let total = 0;
    let expired = 0;
    let healthy = 0;
    let expiring = 0;
    let unconfigured = 0;

    devices.forEach(d => {
      ['normal', 'admin', 'enable'].forEach(role => {
        const days = (d as any)[`${role}_password_days_remaining`];
        const isExp = (d as any)[`${role}_password_expired`];
        
        if (days !== null || role === 'admin') {
          total++;
          const lastRotated = (d as any)[`${role}_password_last_rotated`];
          if (days === null && !lastRotated) unconfigured++;
          else if (isExp) expired++;
          else if (days !== null && days <= 14) expiring++;
          else healthy++;
        }
      });
    });
    
    return { total, healthy, expiring, expired, unconfigured };
  }, [devices]);

  /* ── Flat account list computation & filtering ── */
  const accountList = useMemo(() => {
    const allAccounts: any[] = [];
    
    // 1. Flatten all devices into accounts
    devices.forEach(dev => {
      const roles = [
        { key: 'normal', label: zh ? '普通账号' : 'Normal', icon: User, color: 'blue' },
        { key: 'admin', label: zh ? '特权账号' : 'Privileged', icon: ShieldCheck, color: 'orange' },
        { key: 'enable', label: zh ? '提权密码' : 'Enable', icon: KeyRound, color: 'emerald' },
      ];

      roles.forEach(role => {
        const username = (dev as any)[`${role.key}_username`];
        const days = (dev as any)[`${role.key}_password_days_remaining`];
        const expired = (dev as any)[`${role.key}_password_expired`];
        const last = (dev as any)[`${role.key}_password_last_rotated`];
        const expiresAt = (dev as any)[`${role.key}_password_expires_at`];
        
        const platform = (dev.platform || '').toLowerCase();
        const isServer = platform.includes('linux') || platform.includes('ubuntu') || platform.includes('centos') || platform.includes('server') || platform.includes('debian');
        
        // Show if:
        // 1. It's an admin account (always show)
        // 2. It's a server AND we are looking at the 'normal' role (always show for servers)
        // 3. Or it has a username configured
        // 4. Or it has rotation history
        if (role.key === 'admin' || (isServer && role.key === 'normal') || username || days !== null) {
          allAccounts.push({
            ...dev,
            roleKey: role.key,
            roleLabel: role.label,
            roleIcon: role.icon,
            roleColor: role.color,
            // Fallback: If role-specific username is empty, use the main dev.username
            currentUsername: username || dev.username || (role.key === 'admin' ? 'admin' : ''),
            currentDays: days,
            currentExpired: expired,
            currentLastRotated: last,
            currentExpiresAt: expiresAt,
          });
        }
      });
    });

    // 2. Apply Filters
    let list = allAccounts;

    // Search filter
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(acc => 
        (acc.hostname || '').toLowerCase().includes(q) ||
        (acc.ip_address || '').toLowerCase().includes(q) ||
        (acc.currentUsername || '').toLowerCase().includes(q)
      );
    }

    // Status filter
    if (statusFilter !== 'all') {
      list = list.filter(acc => {
        if (statusFilter === 'expired') return acc.currentExpired;
        if (statusFilter === 'expiring') return acc.currentDays !== null && acc.currentDays <= 14 && acc.currentDays >= 0;
        if (statusFilter === 'healthy') return !acc.currentExpired && acc.currentDays !== null && acc.currentDays > 14;
        if (statusFilter === 'unconfigured') return acc.currentDays === null && !acc.currentLastRotated;
        return true;
      });
    }

    if (roleFilter !== 'all') {
      list = list.filter(acc => acc.roleKey === roleFilter);
    }

    if (targetFilter !== 'all') {
      list = list.filter(acc => targetFilter === 'credential'
        ? isSharedCredentialAccount(acc)
        : !isSharedCredentialAccount(acc));
    }

    return list;
  }, [devices, roleFilter, search, statusFilter, targetFilter, zh]);

  const paginatedAccounts = useMemo(() => {
    const start = (page - 1) * pageSize;
    return accountList.slice(start, start + pageSize);
  }, [accountList, page, pageSize]);

  // A shared credential is one operational object even when it is bound to
  // many devices.  Keep unbound devices as individual rows so the page never
  // hides the device/IP that still needs local credential management.
  const rotationGroups = useMemo(() => {
    const groups = new Map<string, RotationCredentialGroup>();
    accountList.forEach(account => {
      const credentialId = credentialIdFor(account);
      const key = credentialId ? `credential:${credentialId}` : `device:${account.id}`;
      let group = groups.get(key);
      if (!group) {
        group = {
          key,
          credentialId,
          credentialName: credentialNameFor(account),
          username: String(account.currentUsername || ''),
          isCredential: Boolean(credentialId),
          accounts: [],
          devices: [],
        };
        groups.set(key, group);
      }
      group.accounts.push(account);
      if (!group.credentialName) group.credentialName = credentialNameFor(account);
      if (!group.username) group.username = String(account.currentUsername || '');
      if (!group.devices.some(device => device.id === account.id)) {
        group.devices.push({ id: account.id, hostname: account.hostname, ip_address: account.ip_address, platform: account.platform });
      }
    });
    return Array.from(groups.values());
  }, [accountList]);

  const devicePlatformOptions = useMemo(() => Array.from(new Set(
    (deviceDrawerGroup?.devices || []).map(device => String(device.platform || '').trim()).filter(Boolean),
  )).sort((left, right) => left.localeCompare(right)), [deviceDrawerGroup]);

  const localDeviceMatches = useMemo(() => {
    if (!deviceDrawerGroup || deviceDrawerGroup.isCredential) return [];
    const keyword = deviceSearch.trim().toLowerCase();
    const platform = devicePlatform.toLowerCase();
    return deviceDrawerGroup.devices.filter(device => {
      const matchesKeyword = !keyword
        || (device.hostname || '').toLowerCase().includes(keyword)
        || (device.ip_address || '').toLowerCase().includes(keyword);
      return matchesKeyword && (!platform || String(device.platform || '').toLowerCase() === platform);
    });
  }, [deviceDrawerGroup, devicePlatform, deviceSearch]);

  const drawerDeviceRows = deviceDrawerGroup?.isCredential
    ? devicePageData?.items || []
    : localDeviceMatches.slice((devicePage - 1) * devicePageSize, devicePage * devicePageSize);
  const drawerDeviceTotal = deviceDrawerGroup?.isCredential
    ? devicePageData?.total || 0
    : localDeviceMatches.length;

  const rotationExportData = useMemo(() => buildPasswordRotationExportData(rotationGroups, zh), [rotationGroups, zh]);

  /* ══════════ Stat card data ══════════ */
  const statCards = [
    {
      key: 'total', value: stats.total,
      label: zh ? '凭据总数' : 'Total', sub: zh ? '已纳管' : 'MANAGED',
      Icon: KeyRound, filter: 'all' as StatusFilter, tone: 'neutral',
    },
    {
      key: 'healthy', value: stats.healthy,
      label: zh ? '状态正常' : 'Healthy', sub: zh ? '安全' : 'SECURE',
      Icon: ShieldCheck, filter: 'healthy' as StatusFilter, tone: 'healthy',
    },
    {
      key: 'expiring', value: stats.expiring,
      label: zh ? '即将过期' : 'Expiring', sub: '≤14D',
      Icon: ShieldAlert, filter: 'expiring' as StatusFilter, tone: 'expiring',
    },
    {
      key: 'expired', value: stats.expired,
      label: zh ? '已过期' : 'Expired', sub: zh ? '紧急' : 'URGENT',
      Icon: ShieldX, filter: 'expired' as StatusFilter, tone: 'expired',
    },
    {
      key: 'unconfigured', value: stats.unconfigured,
      label: zh ? '未配置周期' : 'Unconfigured', sub: zh ? '待完善' : 'SETUP',
      Icon: Shield, filter: 'unconfigured' as StatusFilter, tone: 'neutral',
    },
  ];

  const hasActiveFilters = Boolean(search || statusFilter !== 'all' || targetFilter !== 'all' || roleFilter !== 'all');
  const visibleGroupCount = rotationGroups.length;
  const accountRoleColumns = [
    { key: 'normal' as const, label: zh ? '普通账号' : 'Normal' },
    { key: 'admin' as const, label: zh ? '特权账号' : 'Privileged' },
    { key: 'enable' as const, label: zh ? '提权账号' : 'Enable' },
  ];
  const visibleRoleColumns = roleFilter === 'all'
    ? accountRoleColumns
    : accountRoleColumns.filter(role => role.key === roleFilter);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-slate-50/60">
      <PageHero
        icon={Key}
        eyebrow={zh ? '安全运营 · 凭据中心' : 'SECURITY OPERATIONS · CREDENTIAL VAULT'}
        title={zh ? '凭据轮换' : 'Credential Rotation'}
        subtitle={zh ? '管理并轮换设备的特权凭据，确保密码周期合规' : 'Manage and rotate privileged credentials across all devices'}
        accent="var(--ui-accent)"
        actions={isAdministrator ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-[10px] font-bold text-emerald-700 sm:inline-flex">
              <ShieldCheck size={12} />
              {zh ? '管理员操作已启用' : 'Administrator actions enabled'}
            </span>
            <select
              value={bulkRole}
              onChange={event => setBulkRole(event.target.value as typeof bulkRole)}
              className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 shadow-sm outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/10"
              aria-label={zh ? '批量轮换账号类型' : 'Bulk rotation account type'}
            >
              <option value="normal">{zh ? '普通账号' : 'Normal'}</option>
              <option value="admin">{zh ? '特权账号' : 'Privileged'}</option>
              <option value="enable">Enable</option>
            </select>
            <button
              type="button"
              onClick={() => setShowBulkConfirm(true)}
              disabled={bulkProgress?.status === 'running' || bulkProgress?.status === 'starting'}
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-cyan-600 px-4 text-xs font-bold text-white shadow-sm shadow-cyan-600/20 transition hover:bg-cyan-700 disabled:cursor-wait disabled:opacity-50"
            >
              <RefreshCw size={14} className={bulkProgress?.status === 'running' ? 'animate-spin' : ''} />
              {zh ? '批量轮换' : 'Bulk Rotate'}
            </button>
          </div>
        ) : undefined}
      />

      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-4 sm:px-6 sm:py-5 lg:px-8">
      <div className="flex items-center gap-2.5 rounded-xl border border-cyan-100 bg-cyan-50/60 px-3.5 py-2.5 text-xs leading-5 text-slate-600" role="note">
        <ShieldAlert size={15} className="shrink-0 text-cyan-700" />
        <p className="min-w-0"><span className="font-semibold text-slate-700">{zh ? '密码周期与同步状态：' : 'Rotation and sync: '}</span>{zh ? '绑定设备按凭据分组；更新共享凭据会创建同步任务。' : 'Bound devices are grouped by credential; updating one creates a synchronization job.'}</p>
      </div>
      {error && (
        <div className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700 shadow-sm" role="alert">
          <ShieldAlert size={15} className="mt-0.5 shrink-0" />
          <div><p className="font-bold">{zh ? '状态加载失败' : 'Unable to load rotation status'}</p><p className="mt-0.5 text-rose-700/80">{error}</p></div>
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs leading-5 text-emerald-700 shadow-sm" role="status">
          <Check size={15} className="mt-0.5 shrink-0" />
          <span className="font-medium">{notice}</span>
        </div>
      )}
      {bulkProgress && ['starting', 'running'].includes(bulkProgress.status) && (
        <div className="rounded-2xl border border-cyan-200 bg-cyan-50 px-4 py-3 text-xs text-cyan-800 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 font-semibold">
            <span>{zh ? '批量轮换进度' : 'Bulk rotation progress'}</span>
            <span className="tabular-nums">{bulkProgress.done || 0}/{bulkProgress.total || 0} · {zh ? '成功' : 'Succeeded'} {bulkProgress.rotated || 0} · {zh ? '失败' : 'Failed'} {bulkProgress.failed || 0}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-cyan-100"><div className="h-full rounded-full bg-cyan-500 transition-all" style={{ width: `${Math.min(100, bulkProgress.total ? ((bulkProgress.done || 0) / bulkProgress.total) * 100 : 0)}%` }} /></div>
        </div>
      )}
      {/* ═══ Stat Cards ═══ */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-5">
        {statCards.map(c => {
          const isActive = statusFilter === c.filter;
          const hasAlert = c.value > 0 && (c.tone === 'expiring' || c.tone === 'expired');
          const cardTone = c.tone === 'expired' && hasAlert
            ? 'border-rose-200 bg-rose-50/60'
            : c.tone === 'expiring' && hasAlert
              ? 'border-amber-200 bg-amber-50/60'
              : 'border-slate-200 bg-white';
          const iconTone = c.tone === 'expired' && hasAlert
            ? 'bg-rose-100 text-rose-700'
            : c.tone === 'expiring' && hasAlert
              ? 'bg-amber-100 text-amber-700'
              : c.tone === 'healthy' && c.value > 0
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-slate-100 text-slate-500';
          const valueTone = c.tone === 'expired' && hasAlert
            ? 'text-rose-700'
            : c.tone === 'expiring' && hasAlert
              ? 'text-amber-700'
              : c.tone === 'healthy' && c.value > 0
                ? 'text-emerald-700'
                : 'text-slate-800';
          return (
            <motion.button
              key={c.key}
              whileHover={{ y: -1 }}
              whileTap={{ scale: 0.995 }}
              onClick={() => setStatusFilter(isActive && c.filter !== 'all' ? 'all' : c.filter)}
              aria-pressed={isActive}
              aria-label={`${c.label}: ${c.value} · ${c.sub}`}
              className={`flex min-h-[76px] items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-left shadow-sm transition hover:shadow-md ${cardTone} ${isActive ? 'ring-2 ring-cyan-500/25 border-cyan-300' : ''}`}
            >
              <div className="min-w-0">
                <p className="truncate text-xs font-medium text-slate-500">{c.label}</p>
                <p className={`mt-1 text-2xl font-bold tabular-nums leading-none ${valueTone}`}>{c.value}</p>
              </div>
              <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${iconTone}`} title={c.sub}>
                <c.Icon size={17} />
              </span>
            </motion.button>
          );
        })}
      </div>

      {/* ═══ Pro Toolbar ═══ */}
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200/80 bg-white p-3 shadow-sm lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
             <div className="relative min-w-[200px] flex-1 sm:flex-none">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={zh ? '快速搜索设备或账号...' : 'Quick search...'}
                  className="h-9 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-cyan-400 focus:bg-white focus:ring-2 focus:ring-cyan-400/10 sm:w-56"
                />
              </div>
              <select
                value={targetFilter}
                onChange={event => setTargetFilter(event.target.value as TargetFilter)}
                className="h-9 rounded-xl border border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-600 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/10"
              >
                <option value="all">{zh ? '全部目标' : 'All targets'}</option>
                <option value="credential">{zh ? '共享凭据' : 'Shared credentials'}</option>
                <option value="unbound">{zh ? '未绑定设备' : 'Unbound devices'}</option>
              </select>
              <select
                value={roleFilter}
                onChange={event => setRoleFilter(event.target.value as RoleFilter)}
                className="h-9 rounded-xl border border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-600 outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/10"
              >
                <option value="all">{zh ? '全部账号类型' : 'All account types'}</option>
                <option value="normal">{zh ? '普通账号' : 'Normal'}</option>
                <option value="admin">{zh ? '特权账号' : 'Privileged'}</option>
                <option value="enable">{zh ? 'Enable 凭据' : 'Enable'}</option>
              </select>
              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={() => {
                    setSearch('');
                    setStatusFilter('all');
                    setTargetFilter('all');
                    setRoleFilter('all');
                  }}
                  className="inline-flex h-9 items-center gap-1 rounded-xl px-2.5 text-xs font-bold text-cyan-700 transition hover:bg-cyan-50"
                >
                  <X size={13} />
                  {zh ? '清空筛选' : 'Clear'}
                </button>
              )}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 lg:justify-end">
          <span className="text-xs font-medium text-slate-500">{zh ? `显示 ${visibleGroupCount} 个凭据组` : `${visibleGroupCount} credential groups`}</span>
          <button
          onClick={fetchStatus}
          disabled={loading}
          className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 text-xs font-semibold text-slate-500 transition hover:border-cyan-200 hover:bg-cyan-50 hover:text-cyan-700 disabled:cursor-wait disabled:opacity-60"
          title={zh ? '刷新状态' : 'Refresh status'}
          aria-label={zh ? '刷新状态' : 'Refresh status'}
        >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">{zh ? '刷新' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* ═══ Credential groups ═══ */}
      <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
        <div className="flex flex-col gap-2 border-b border-slate-100 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600"><SlidersHorizontal size={15} /></span>
            <div>
              <h2 className="text-sm font-bold text-slate-800">{zh ? '凭据分组' : 'Credential groups'}</h2>
              <p className="text-xs text-slate-500">{zh ? '按需展开查看完整轮换状态和关联设备' : 'Expand a group for rotation details and linked devices'}</p>
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span className="whitespace-nowrap">{zh ? `${visibleGroupCount} 个凭据组` : `${visibleGroupCount} groups`}</span>
            <span className="hidden h-4 w-px bg-slate-200 sm:block" />
            <span className="hidden whitespace-nowrap sm:inline">{zh ? '展开行可查看全部字段' : 'Expand a row to view all fields'}</span>
          </div>
        </div>
          <DataTable unstyled exportConfig={{ filename: 'password-rotation-credentials', language: zh ? 'zh' : 'en', disabled: loading || rotationGroups.length === 0, exportData: rotationExportData }} className={`nx-data-table nx-data-table--compact w-full table-fixed ${visibleRoleColumns.length === 3 ? 'min-w-[1120px]' : 'min-w-[820px]'}`}>
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/90">
                <th data-export="public" className="w-[190px] whitespace-nowrap px-4 py-3 text-left text-xs font-semibold text-slate-500">{zh ? '凭据组' : 'Credential'}</th>
                <th data-export="public" className="w-[220px] whitespace-nowrap px-4 py-3 text-left text-xs font-semibold text-slate-500">{zh ? '关联设备' : 'Devices'}</th>
                <th data-export="public" className="w-[140px] whitespace-nowrap px-4 py-3 text-left text-xs font-semibold text-slate-500">{zh ? '平台' : 'Platform'}</th>
                {visibleRoleColumns.map(role => <th key={role.key} data-export="public" className="min-w-[190px] whitespace-nowrap px-3 py-3 text-left text-xs font-semibold text-slate-500">{role.label}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loading && !accountList.length ? (
                <tr><td colSpan={visibleRoleColumns.length + 3} className="py-20 text-center"><div className="flex flex-col items-center gap-3 text-slate-400"><Loader2 className="animate-spin text-cyan-500" size={25} /><span className="text-sm font-medium">{zh ? '正在加载凭据状态…' : 'Loading credential status…'}</span></div></td></tr>
              ) : accountList.length === 0 ? (
                <tr><td colSpan={visibleRoleColumns.length + 3} className="py-20 text-center"><div className="mx-auto flex max-w-sm flex-col items-center gap-2 text-slate-400"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-100 text-slate-400"><LockKeyhole size={20} /></span><p className="text-sm font-bold text-slate-600">{zh ? (hasActiveFilters ? '没有符合条件的凭据' : '暂无凭据数据') : (hasActiveFilters ? 'No credentials match these filters' : 'No credential data yet')}</p><p className="text-xs leading-5">{zh ? (hasActiveFilters ? '尝试清空筛选条件，或使用设备名称、IP 和账号搜索。' : '加载设备后，这里会显示凭据周期与同步状态。') : (hasActiveFilters ? 'Clear a filter or search by device, IP, or account.' : 'Credential rotation status will appear after devices are loaded.')}</p></div></td></tr>
              ) : (
                (() => {
                  const paginatedGroups = rotationGroups.slice((page - 1) * pageSize, page * pageSize);

                  return paginatedGroups.map(group => {
                    const accounts = group.accounts;
                    const isDevServer = group.devices.length > 0 && group.devices.every(device => isServer(device.platform || ''));
                    const exportRow = buildRotationExportRow(group as RotationExportGroup, zh);
                    const isExpanded = expandedId === group.key;
                    const groupName = group.isCredential
                      ? exportRow[0]
                      : group.devices[0]?.hostname || (zh ? '未绑定设备' : 'Unbound device');

                    return (
                      <React.Fragment key={group.key}>
                        <tr className="transition-colors odd:bg-white even:bg-slate-50/30 hover:bg-cyan-50/30">
                          <td className="px-4 py-3 align-top">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-slate-800" title={groupName}>{groupName}</p>
                              <span className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${group.isCredential ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-100 text-slate-600'}`}>
                                {group.isCredential ? (zh ? '共享凭据' : 'Shared credential') : (zh ? '设备本地' : 'Device local')}
                              </span>
                              <button
                                type="button"
                                aria-expanded={isExpanded}
                                onClick={() => setExpandedId(isExpanded ? null : group.key)}
                                className="mt-2 inline-flex items-center gap-1 rounded-md text-xs font-semibold text-cyan-700 hover:text-cyan-800 focus:outline-none focus:ring-2 focus:ring-cyan-500/30"
                              >
                                <ChevronDown size={14} className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
                                {isExpanded ? (zh ? '收起详情' : 'Hide details') : (zh ? '查看详情' : 'View details')}
                              </button>
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <p className="text-sm font-semibold tabular-nums text-slate-700">{group.devices.length} {zh ? '台设备' : 'devices'}</p>
                            <p className="mt-1 max-w-[220px] truncate text-xs text-slate-500" title={group.devices.slice(0, 2).map(device => device.hostname || device.ip_address || '—').join('、')}>
                              {group.devices.slice(0, 2).map(device => device.hostname || device.ip_address || '—').join('、') || '—'}
                              {group.devices.length > 2 && <span className="ml-1 font-semibold text-cyan-700">+{group.devices.length - 2}</span>}
                            </p>
                            <button type="button" onClick={() => openDeviceDrawer(group)} className="mt-1 text-xs font-semibold text-cyan-700 hover:text-cyan-800">
                              {zh ? '查看设备列表' : 'View device list'}
                            </button>
                          </td>
                          <td className="px-4 py-3 align-top text-sm text-slate-600">
                            <span className="block max-w-[140px] truncate" title={exportRow[4]}>{exportRow[4]}</span>
                          </td>
                          {visibleRoleColumns.map(role => {
                            const roleAccounts = accounts.filter(account => account.roleKey === role.key);
                            const acc = roleAccounts[0];
                            if (!acc) {
                              return (
                                <td key={role.key} className="px-3 py-3 align-top">
                                  <div className="flex min-h-[88px] items-center rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-3">
                                    <span className="text-sm text-slate-400">{role.key === 'enable' && isDevServer ? (zh ? '不适用' : 'Not applicable') : (zh ? '未配置' : 'Not configured')}</span>
                                  </div>
                                </td>
                              );
                            }

                            const credentialId = credentialIdFor(acc);
                            const secretType: 'password' | 'enable_password' = role.key === 'enable' ? 'enable_password' : 'password';
                            const secretKey = `${credentialId}:${secretType}`;
                            const isRevealed = Boolean(credentialId && revealedSecret?.id === credentialId && revealedSecret?.type === secretType);
                            const localRole = acc.roleKey as 'normal' | 'admin' | 'enable';
                            const localKey = `${acc.id}:${localRole}`;
                            const isLocalRevealed = localRevealedSecret?.deviceId === acc.id && localRevealedSecret.role === localRole;
                            const status = roleRotationStatus(roleAccounts, zh);

                            return (
                              <td key={role.key} className="px-3 py-3 align-top">
                                <div className="min-h-[88px] rounded-xl border border-slate-200 bg-white px-3 py-2.5">
                                  <div className="flex min-w-0 items-start justify-between gap-2">
                                    <span className="min-w-0 truncate pt-0.5 font-mono text-sm font-semibold text-slate-700" title={acc.currentUsername || ''}>{acc.currentUsername || '—'}</span>
                                    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${status.className}`}>{status.label}</span>
                                  </div>
                                  {roleAccounts.length > 1 && <p className="mt-1 text-xs text-slate-400">{roleAccounts.length} {zh ? '台设备使用' : 'linked devices'}</p>}
                                  {isAdministrator && (
                                    <div className="mt-2 flex flex-nowrap items-center gap-1.5 whitespace-nowrap">
                                      <button
                                        type="button"
                                        onClick={() => credentialId ? void revealCredentialSecret(acc, secretType) : void revealDeviceLocalSecret(acc)}
                                        disabled={Boolean(credentialId ? secretLoading === secretKey : localSecretLoading === localKey)}
                                        className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${isRevealed || isLocalRevealed ? 'border-cyan-200 bg-cyan-50 text-cyan-700' : 'border-slate-200 bg-white text-slate-500 hover:border-cyan-200 hover:text-cyan-700'}`}
                                        title={isRevealed || isLocalRevealed ? (zh ? '隐藏密码' : 'Hide password') : (zh ? '查看凭据密码' : 'View password')}
                                        aria-label={isRevealed || isLocalRevealed ? (zh ? '隐藏密码' : 'Hide password') : (zh ? '查看凭据密码' : 'View password')}
                                      >
                                        {secretLoading === secretKey || localSecretLoading === localKey
                                          ? <RefreshCw size={13} className="animate-spin" />
                                          : isRevealed || isLocalRevealed ? <EyeOff size={14} /> : <Eye size={14} />}
                                      </button>
                                      {isRevealed && <ActionIconButton icon={secretCopied ? Check : Copy} label={zh ? '复制并记录审计' : 'Copy and audit'} size="xs" variant={secretCopied ? 'success' : 'accent'} onClick={() => { void copyRevealedSecret(); }} />}
                                      {isLocalRevealed && <ActionIconButton icon={localSecretCopied ? Check : Copy} label={zh ? '复制并记录审计' : 'Copy and audit'} size="xs" variant={localSecretCopied ? 'success' : 'accent'} onClick={() => { void copyDeviceLocalSecret(); }} />}
                                      {credentialId ? (
                                        <button
                                          type="button"
                                          onClick={() => openCredentialEditor(group.isCredential
                                            ? { ...acc, hostname: `${group.credentialName || '凭据'}（${group.devices.length}台设备）` }
                                            : acc, secretType)}
                                          className="inline-flex h-7 items-center rounded-lg border border-cyan-200 bg-cyan-50 px-2 text-xs font-semibold text-cyan-700 hover:bg-cyan-100"
                                          title={zh ? '轮换权威密码并同步关联设备' : 'Rotate the authoritative password and synchronize bound devices'}
                                        >{zh ? '轮换同步' : 'Rotate'}</button>
                                      ) : (
                                        <button
                                          type="button"
                                          onClick={() => setPendingRotation(acc)}
                                          className="inline-flex h-7 items-center rounded-lg border border-amber-200 bg-amber-50 px-2 text-xs font-semibold text-amber-700 hover:bg-amber-100"
                                          title={zh ? '在设备上生成新密码、验证后写回权威存储' : 'Generate a new password on the device, verify it, then update authoritative storage'}
                                        >{zh ? '立即轮换' : 'Rotate now'}</button>
                                      )}
                                    </div>
                                  )}
                                  {isRevealed && revealedSecret?.secret && (
                                    <div className="mt-2 truncate rounded-lg bg-slate-900 px-2 py-1.5 font-mono text-xs text-cyan-200" title={revealedSecret.secret}>{revealedSecret.secret}</div>
                                  )}
                                  {isLocalRevealed && localRevealedSecret?.secret && (
                                    <div className="mt-2 truncate rounded-lg bg-slate-900 px-2 py-1.5 font-mono text-xs text-amber-200" title={localRevealedSecret.secret}>{localRevealedSecret.secret}</div>
                                  )}
                                </div>
                              </td>
                            );
                          })}
                        </tr>
                        {isExpanded && (
                          <tr className="bg-slate-50/80">
                            <td colSpan={visibleRoleColumns.length + 3} className="px-4 py-4">
                              <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
                                <section>
                                  <h3 className="text-sm font-semibold text-slate-700">{zh ? '账号轮换详情' : 'Account rotation details'}</h3>
                                  <div className="mt-2 grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
                                    {visibleRoleColumns.map(role => {
                                      const roleAccounts = accounts.filter(account => account.roleKey === role.key);
                                      const roleIndex = accountRoleColumns.findIndex(column => column.key === role.key);
                                      const roleExportIndex = 5 + roleIndex * 5;
                                      const acc = roleAccounts[0];
                                      const status = roleAccounts.length > 0 ? roleRotationStatus(roleAccounts, zh) : null;
                                      const detailFields = [
                                        { label: zh ? '用户名' : 'Username', value: acc?.currentUsername || '—' },
                                        { label: zh ? '设备数' : 'Devices', value: exportRow[roleExportIndex + 1] },
                                        { label: zh ? '状态' : 'Status', value: status?.label || (role.key === 'enable' && isDevServer ? (zh ? '不适用' : 'Not applicable') : (zh ? '未配置' : 'Not configured')) },
                                        { label: zh ? '最近轮换' : 'Last rotated', value: exportRow[roleExportIndex + 3] },
                                        { label: zh ? '到期时间' : 'Expires', value: exportRow[roleExportIndex + 4] },
                                      ];
                                      return (
                                        <article key={role.key} className="rounded-xl border border-slate-200 bg-white p-3">
                                          <div className="flex items-center justify-between gap-2">
                                            <h4 className="text-xs font-semibold text-slate-700">{role.label}</h4>
                                            {status && <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${status.className}`}>{status.label}</span>}
                                          </div>
                                          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                                            {detailFields.map(field => (
                                              <div key={field.label} className="min-w-0">
                                                <dt className="text-[11px] text-slate-400">{field.label}</dt>
                                                <dd className="mt-0.5 truncate text-xs font-medium text-slate-700" title={field.value}>{field.value}</dd>
                                              </div>
                                            ))}
                                          </dl>
                                        </article>
                                      );
                                    })}
                                  </div>
                                </section>
                                <section>
                                  <h3 className="text-sm font-semibold text-slate-700">{zh ? '关联设备' : 'Linked devices'}</h3>
                                  <div className="mt-2 rounded-xl border border-slate-200 bg-white p-3">
                                    <p className="text-sm font-semibold tabular-nums text-slate-700">{group.devices.length} {zh ? '台设备绑定到此凭据' : 'devices bound to this credential'}</p>
                                    <p className="mt-1 truncate text-xs text-slate-500" title={group.devices.slice(0, 2).map(device => device.hostname || device.ip_address || '—').join('、')}>
                                      {group.devices.slice(0, 2).map(device => device.hostname || device.ip_address || '—').join('、') || '—'}
                                      {group.devices.length > 2 && <span className="ml-1 font-semibold text-cyan-700">+{group.devices.length - 2}</span>}
                                    </p>
                                    <button type="button" onClick={() => openDeviceDrawer(group)} className="mt-3 inline-flex h-8 items-center rounded-lg border border-cyan-200 bg-cyan-50 px-3 text-xs font-semibold text-cyan-700 hover:bg-cyan-100">
                                      {zh ? `搜索或查看全部 ${group.devices.length} 台` : `Search or view all ${group.devices.length}`}
                                    </button>
                                  </div>
                                </section>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  });
                })()
              )}
            </tbody>
          </DataTable>
        {/* Footer Info & Pagination */}
        <div className="flex flex-col gap-2 border-t border-slate-200 bg-slate-50/80 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-3">
             <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                <span className="h-2 w-2 rounded-full bg-emerald-500" /> {zh ? '状态正常' : 'Healthy'}
             </div>
             <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                <span className="h-2 w-2 rounded-full bg-red-500" /> {zh ? '凭据过期' : 'Expired'}
             </div>
             {isAdministrator ? <span className="hidden items-center gap-1.5 text-[10px] font-medium text-slate-400 sm:inline-flex"><ShieldCheck size={12} /> {zh ? '可执行轮换操作' : 'Rotation actions available'}</span> : <span className="inline-flex items-center gap-1.5 text-[10px] font-medium text-slate-400"><LockKeyhole size={12} /> {zh ? '只读视图' : 'Read-only view'}</span>}
          </div>
          
          <Pagination
            currentPage={page}
            totalItems={rotationGroups.length}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
            onPageChange={setPage}
            language={language}
            itemLabel={zh ? '个凭据组' : 'groups'}
            pageUnitLabel={zh ? '组/页' : 'groups/page'}
          />
        </div>
      </div>
      </div>
      {deviceDrawerGroup && (
        <div className="fixed inset-0 z-[115] bg-slate-950/35">
          <button
            type="button"
            aria-label={zh ? '关闭关联设备列表' : 'Close linked devices'}
            onClick={() => setDeviceDrawerGroup(null)}
            className="absolute inset-0 cursor-default"
          />
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="rotation-device-drawer-title"
            className="absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl"
          >
            <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 sm:px-6">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-cyan-700">{zh ? '凭据关联设备' : 'Credential devices'}</p>
                <h2 id="rotation-device-drawer-title" className="mt-1 truncate text-base font-bold text-slate-900">
                  {deviceDrawerGroup.credentialName || deviceDrawerGroup.devices[0]?.hostname || (zh ? '设备列表' : 'Device list')}
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {zh ? `共绑定 ${deviceDrawerGroup.devices.length} 台设备` : `${deviceDrawerGroup.devices.length} bound devices`}
                </p>
              </div>
              <button type="button" onClick={() => setDeviceDrawerGroup(null)} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label={zh ? '关闭' : 'Close'}>
                <X size={18} />
              </button>
            </header>

            <form
              onSubmit={event => {
                event.preventDefault();
                setDevicePage(1);
                setDeviceSearch(deviceSearchDraft.trim());
              }}
              className="grid gap-2 border-b border-slate-200 bg-slate-50/70 p-4 sm:grid-cols-[minmax(0,1fr)_180px_auto] sm:items-center"
            >
              <label className="relative block">
                <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  value={deviceSearchDraft}
                  onChange={event => setDeviceSearchDraft(event.target.value)}
                  placeholder={zh ? '搜索设备名称或管理 IP' : 'Search device name or management IP'}
                  className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-cyan-300 focus:ring-2 focus:ring-cyan-100"
                />
              </label>
              <select
                value={devicePlatform}
                onChange={event => { setDevicePage(1); setDevicePlatform(event.target.value); }}
                aria-label={zh ? '按平台筛选' : 'Filter by platform'}
                className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-cyan-300 focus:ring-2 focus:ring-cyan-100"
              >
                <option value="">{zh ? '全部平台' : 'All platforms'}</option>
                {devicePlatformOptions.map(platform => <option key={platform} value={platform}>{platform}</option>)}
              </select>
              <div className="flex items-center gap-2">
                <button type="submit" className="h-10 rounded-xl bg-cyan-600 px-4 text-sm font-semibold text-white hover:bg-cyan-700">
                  {zh ? '搜索' : 'Search'}
                </button>
                <button
                  type="button"
                  onClick={() => { setDeviceSearchDraft(''); setDeviceSearch(''); setDevicePlatform(''); setDevicePage(1); }}
                  className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-600 hover:bg-slate-100"
                >
                  {zh ? '重置' : 'Reset'}
                </button>
              </div>
            </form>

            <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
              {deviceListLoading ? (
                <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-sm text-slate-500">
                  <Loader2 className="animate-spin text-cyan-600" size={24} />
                  {zh ? '正在查询关联设备…' : 'Loading linked devices…'}
                </div>
              ) : deviceListError ? (
                <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
                  <p role="alert" className="max-w-md text-sm text-rose-600">{deviceListError}</p>
                  <button type="button" onClick={() => setDeviceRequestVersion(version => version + 1)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                    {zh ? '重试' : 'Retry'}
                  </button>
                </div>
              ) : drawerDeviceRows.length === 0 ? (
                <div className="flex min-h-48 flex-col items-center justify-center gap-2 text-center">
                  <Search size={22} className="text-slate-300" />
                  <p className="text-sm font-semibold text-slate-600">{zh ? (deviceSearch || devicePlatform ? '没有匹配的设备' : '暂无关联设备') : (deviceSearch || devicePlatform ? 'No devices match these filters' : 'No linked devices')}</p>
                  {(deviceSearch || devicePlatform) && <p className="text-xs text-slate-400">{zh ? '请调整搜索词或平台筛选。' : 'Adjust the search or platform filter.'}</p>}
                </div>
              ) : (
                <div className="overflow-hidden rounded-xl border border-slate-200">
                  <table className="w-full table-fixed text-left">
                    <thead className="bg-slate-50 text-xs font-semibold text-slate-500">
                      <tr>
                        <th className="px-3 py-3 sm:px-4">{zh ? '设备名称' : 'Device'}</th>
                        <th className="w-[38%] px-3 py-3 sm:px-4">{zh ? '管理 IP' : 'Management IP'}</th>
                        <th className="w-[24%] px-3 py-3 sm:px-4">{zh ? '平台' : 'Platform'}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white">
                      {drawerDeviceRows.map(device => (
                        <tr key={device.id} className="hover:bg-cyan-50/40">
                          <td className="px-3 py-3 sm:px-4"><span className="block truncate text-sm font-medium text-slate-700" title={device.hostname}>{device.hostname || '—'}</span></td>
                          <td className="px-3 py-3 font-mono text-xs text-slate-500 sm:px-4"><span className="block truncate" title={device.ip_address}>{device.ip_address || '—'}</span></td>
                          <td className="px-3 py-3 text-xs text-slate-500 sm:px-4"><span className="block truncate" title={device.platform}>{device.platform || '—'}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="border-t border-slate-200 bg-white px-3 py-2 sm:px-4">
              <Pagination
                currentPage={devicePage}
                totalItems={drawerDeviceTotal}
                itemsPerPage={devicePageSize}
                onItemsPerPageChange={size => { setDevicePage(1); setDevicePageSize(size); }}
                onPageChange={setDevicePage}
                language={language}
                alwaysVisible
                itemLabel={zh ? '台设备' : 'devices'}
                pageUnitLabel={zh ? '台/页' : 'devices/page'}
              />
            </div>
          </section>
        </div>
      )}
      {showBulkConfirm && (
        <div className="fixed inset-0 z-[130] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => setShowBulkConfirm(false)} />
          <div className="relative w-full max-w-md rounded-3xl border border-amber-200 bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-slate-800">{zh ? '确认批量轮换' : 'Confirm Bulk Rotation'}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              {zh
                ? `将对全部符合条件设备的${bulkRole === 'admin' ? '特权账号' : bulkRole === 'normal' ? '普通账号' : ' Enable 凭据'}执行真实改密、连接验证和权威值更新。失败设备会保留原凭据并记录原因。`
                : `This performs real password changes, verification, and authoritative updates for the selected account type on every eligible device. Failed targets retain their previous secret.`}
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button onClick={() => setShowBulkConfirm(false)} className="h-10 rounded-xl border border-black/10 px-4 text-sm font-semibold text-slate-600">{zh ? '取消' : 'Cancel'}</button>
              <button onClick={() => { void startBulkRotation(); }} className="h-10 rounded-xl bg-amber-500 px-5 text-sm font-bold text-white hover:bg-amber-600">{zh ? '确认执行' : 'Confirm'}</button>
            </div>
          </div>
        </div>
      )}
      {pendingRotation && (
        <div className="fixed inset-0 z-[130] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => !rotatingPassword && setPendingRotation(null)} />
          <div className="relative w-full max-w-md rounded-3xl border border-amber-200 bg-white p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-slate-800">{zh ? '确认设备密码轮换' : 'Confirm Device Rotation'}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              {zh
                ? `目标：${pendingRotation.hostname || pendingRotation.ip_address} · ${pendingRotation.roleLabel}。系统会先在设备上修改密码，验证成功后再更新权威存储；验证失败将尝试回滚。`
                : `Target: ${pendingRotation.hostname || pendingRotation.ip_address} · ${pendingRotation.roleLabel}. The authoritative secret is updated only after the device change is verified; failures trigger rollback.`}
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button disabled={rotatingPassword} onClick={() => setPendingRotation(null)} className="h-10 rounded-xl border border-black/10 px-4 text-sm font-semibold text-slate-600 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button>
              <button disabled={rotatingPassword} onClick={() => { void rotateDevicePassword(); }} className="inline-flex h-10 items-center gap-2 rounded-xl bg-amber-500 px-5 text-sm font-bold text-white hover:bg-amber-600 disabled:cursor-wait disabled:opacity-50">
                {rotatingPassword && <RefreshCw size={14} className="animate-spin" />}
                {zh ? '执行轮换' : 'Rotate'}
              </button>
            </div>
          </div>
        </div>
      )}
      {editingCredential && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/45 backdrop-blur-sm" onClick={() => { if (!credentialSaving) setEditingCredential(null); }} />
          <div className="relative w-full max-w-md rounded-3xl border border-black/10 bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4 border-b border-black/5 pb-4">
              <div>
                <h3 className="text-lg font-semibold text-[#164e63]">{zh ? '轮换并同步凭据密码' : 'Rotate and synchronize credential password'}</h3>
                <p className="mt-1 text-xs text-black/45">{editingCredential.deviceName} · {editingCredential.label} · {editingCredential.username}</p>
              </div>
              <button type="button" disabled={credentialSaving} onClick={() => setEditingCredential(null)} className="rounded-xl border border-black/10 p-1.5 text-black/45 hover:bg-black/[0.03] disabled:opacity-40">
                <X size={16} />
              </button>
            </div>
            <div className="mt-5 space-y-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-black/55">{editingCredential.type === 'enable_password' ? (zh ? '旧 Enable 密码' : 'Current Enable password') : (zh ? '旧密码' : 'Current password')}</label>
                <PasswordInputField
                  showPasswordLabel={zh ? '显示旧密码' : 'Show current password'}
                  hidePasswordLabel={zh ? '隐藏旧密码' : 'Hide current password'}
                  value={credentialForm.oldSecret}
                  onChange={event => setCredentialForm(previous => ({ ...previous, oldSecret: event.target.value }))}
                  autoComplete="current-password"
                  className="w-full rounded-xl border border-black/10 px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/10"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-black/55">{editingCredential.type === 'enable_password' ? (zh ? '新 Enable 密码' : 'New Enable password') : (zh ? '新密码' : 'New password')}</label>
                <PasswordInputField
                  showPasswordLabel={zh ? '显示新密码' : 'Show new password'}
                  hidePasswordLabel={zh ? '隐藏新密码' : 'Hide new password'}
                  value={credentialForm.newSecret}
                  onChange={event => setCredentialForm(previous => ({ ...previous, newSecret: event.target.value }))}
                  autoComplete="new-password"
                  className="w-full rounded-xl border border-black/10 px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/10"
                />
              </div>
              {credentialError && (
                <div className="flex items-start gap-1.5 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-600" role="alert">
                  <ShieldAlert size={14} className="mt-0.5 shrink-0" />
                  <span>{credentialError}</span>
                </div>
              )}
              <p className="text-[11px] leading-5 text-black/45">
                {zh ? '修改绑定凭据后，系统会按凭据关联范围创建同步任务；所有目标设备验证成功后才更新权威值。' : 'For a bound credential, the system creates a synchronization job and updates the authoritative value only after all target devices verify successfully.'}
              </p>
            </div>
            <div className="mt-6 flex justify-end gap-2 border-t border-black/5 pt-4">
              <button type="button" disabled={credentialSaving} onClick={() => setEditingCredential(null)} className="h-10 rounded-xl border border-black/10 px-4 text-sm font-semibold text-black/60 hover:bg-black/[0.02] disabled:opacity-40">{zh ? '取消' : 'Cancel'}</button>
              <button type="button" disabled={credentialSaving} onClick={() => { void submitCredentialUpdate(); }} className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-cyan-500 px-5 text-sm font-semibold text-white shadow-md hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-50">
                {credentialSaving ? <RefreshCw size={14} className="animate-spin" /> : <Check size={14} />}
                {zh ? '提交更新' : 'Submit update'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
