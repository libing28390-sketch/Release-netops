import React, { useState, useCallback, useEffect, useMemo } from 'react';
import Pagination from './Pagination';
import PageHero from './PageHero';
import { motion } from 'motion/react';
import {
  RefreshCw, Shield, Loader2, Search, ShieldCheck, ShieldAlert, ShieldX,
  Key, KeyRound, Server, User, Eye, EyeOff, Copy, Check, X,
} from 'lucide-react';

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

interface PasswordRotationPanelProps {
  language: string;
  currentUser?: { role?: string };
}

const API_BASE = import.meta.env.VITE_API_BASE || '';

/* ── platform display helper ── */
const platformLabel = (p: string): string => {
  const map: Record<string, string> = {
    cisco_ios: 'Cisco IOS', cisco_nxos: 'Cisco NX-OS', cisco_xe: 'Cisco IOS-XE',
    huawei_vrp: 'Huawei VRP', h3c_comware: 'H3C Comware',
    arista_eos: 'Arista EOS', juniper_junos: 'Juniper JunOS',
    linux: 'Linux', ubuntu: 'Ubuntu', centos: 'CentOS', debian: 'Debian',
    esxi: 'VMware ESXi',
  };
  return map[p] || p || '-';
};

const platformColor = (p: string): string => {
  if (p?.startsWith('cisco')) return 'bg-blue-50 text-blue-600 border-blue-200';
  if (p?.startsWith('huawei')) return 'bg-red-50 text-red-600 border-red-200';
  if (p?.startsWith('h3c')) return 'bg-orange-50 text-orange-600 border-orange-200';
  if (p?.startsWith('arista')) return 'bg-cyan-50 text-cyan-600 border-cyan-200';
  if (p?.startsWith('juniper')) return 'bg-green-50 text-green-600 border-green-200';
  if (['linux', 'ubuntu', 'centos', 'debian'].includes(p)) return 'bg-slate-100 text-slate-700 border-slate-300';
  return 'bg-slate-50 text-slate-600 border-slate-200';
};

const isServer = (p: string): boolean => {
  const platform = (p || '').toLowerCase();
  return platform.includes('linux') || platform.includes('ubuntu') || platform.includes('centos') || platform.includes('server') || platform.includes('debian');
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
    const groups = new Map<string, { key: string; credentialId: string; credentialName: string; username: string; isCredential: boolean; accounts: any[]; devices: any[] }>();
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

  /* ══════════ Stat card data ══════════ */
  const statCards = [
    {
      key: 'total', value: stats.total,
      label: zh ? '凭据总数' : 'Total', sub: zh ? '已纳管' : 'MANAGED',
      Icon: KeyRound, filter: 'all' as StatusFilter,
      gradient: 'from-slate-700 to-slate-800', iconBg: 'bg-white/[0.06]',
      iconCls: 'text-slate-300', valCls: 'text-white', labelCls: 'text-white/50', subCls: 'bg-white/10 text-white/60',
    },
    {
      key: 'healthy', value: stats.healthy,
      label: zh ? '状态正常' : 'Healthy', sub: zh ? '安全' : 'SECURE',
      Icon: ShieldCheck, filter: 'healthy' as StatusFilter,
      gradient: 'from-emerald-600 to-emerald-700', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/70',
    },
    {
      key: 'expiring', value: stats.expiring,
      label: zh ? '即将过期' : 'Expiring', sub: '≤14D',
      Icon: ShieldAlert, filter: 'expiring' as StatusFilter,
      gradient: 'from-amber-600 to-amber-700', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/70',
      pulse: stats.expiring > 0,
    },
    {
      key: 'expired', value: stats.expired,
      label: zh ? '已过期' : 'Expired', sub: zh ? '紧急' : 'URGENT',
      Icon: ShieldX, filter: 'expired' as StatusFilter,
      gradient: 'from-red-600 to-red-700', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/80',
      pulse: stats.expired > 0,
    },
    {
      key: 'unconfigured', value: stats.unconfigured,
      label: zh ? '未配置周期' : 'Unconfigured', sub: zh ? '待完善' : 'SETUP',
      Icon: Shield, filter: 'unconfigured' as StatusFilter,
      gradient: 'from-slate-500 to-slate-600', iconBg: 'bg-white/[0.08]',
      iconCls: 'text-white/70', valCls: 'text-white', labelCls: 'text-white/60', subCls: 'bg-white/15 text-white/70',
    },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Key}
        title={zh ? '凭据轮换' : 'Credential Rotation'}
        subtitle={zh ? '管理并轮换设备的特权凭据，确保密码周期合规' : 'Manage and rotate privileged credentials across all devices'}
        actions={isAdministrator ? (
          <div className="flex items-center gap-2">
            <select
              value={bulkRole}
              onChange={event => setBulkRole(event.target.value as typeof bulkRole)}
              className="h-10 rounded-xl border border-black/10 bg-white px-3 text-xs font-semibold text-slate-600 outline-none"
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
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-cyan-500 px-4 text-xs font-bold text-white shadow-md hover:bg-cyan-600 disabled:cursor-wait disabled:opacity-50"
            >
              <RefreshCw size={14} className={bulkProgress?.status === 'running' ? 'animate-spin' : ''} />
              {zh ? '批量轮换' : 'Bulk Rotate'}
            </button>
          </div>
        ) : undefined}
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-4">
      <div className="flex items-start gap-2 rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs leading-5 text-cyan-800">
        <ShieldAlert size={14} className="mt-0.5 shrink-0" />
        <span>{zh ? '此页面展示口令轮换状态。绑定设备按凭据分组，未绑定设备单独展示；管理员可查看或更新凭据中心的权威密码，绑定凭据的更新会创建同步任务。' : 'This page shows rotation status. Bound devices are grouped by credential while unbound devices remain individual; administrators can view or update the authoritative credential-center secret, and bound updates run as synchronization jobs.'}</span>
      </div>
      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs leading-5 text-rose-700" role="alert">
          <ShieldAlert size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-700" role="status">
          <Check size={14} className="mt-0.5 shrink-0" />
          <span>{notice}</span>
        </div>
      )}
      {bulkProgress && ['starting', 'running'].includes(bulkProgress.status) && (
        <div className="rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs text-cyan-800">
          {zh ? '批量轮换进度' : 'Bulk rotation progress'}：
          {bulkProgress.done || 0}/{bulkProgress.total || 0}
          {' · '}{zh ? '成功' : 'Succeeded'} {bulkProgress.rotated || 0}
          {' · '}{zh ? '失败' : 'Failed'} {bulkProgress.failed || 0}
        </div>
      )}
      {/* ═══ Stat Cards ═══ */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {statCards.map(c => {
          const isActive = statusFilter === c.filter;
          return (
            <motion.button
              key={c.key}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => setStatusFilter(isActive && c.filter !== 'all' ? 'all' : c.filter)}
              className={`group relative rounded-xl overflow-hidden shadow-sm transition-all
                bg-gradient-to-br ${c.gradient}
                ${isActive ? 'ring-2 ring-white/20 shadow-lg' : 'hover:shadow-md'}`}
            >
              <div className="px-4 py-3.5 flex items-center justify-between relative z-10">
                <div className="text-left">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={`text-[8px] font-bold uppercase tracking-[0.15em] px-1.5 py-0.5 rounded ${c.subCls}`}>{c.sub}</span>
                    <span className={`text-[10px] font-medium ${c.labelCls}`}>{c.label}</span>
                  </div>
                  <p className={`text-3xl font-black tabular-nums leading-none ${c.valCls}`}>{c.value}</p>
                </div>
                <div className={`h-10 w-10 rounded-xl ${c.iconBg} flex items-center justify-center backdrop-blur-sm`}>
                  <c.Icon size={20} className={`${c.iconCls} ${c.pulse ? 'animate-pulse' : ''}`} />
                </div>
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* ═══ Pro Toolbar ═══ */}
      <div className="flex items-center justify-between gap-3 mb-3 bg-white p-2 rounded-xl border border-black/[0.04] shadow-sm">
        <div className="flex items-center gap-2">
          <div className="h-7 px-2 rounded-lg bg-cyan-500 text-white flex items-center gap-1.5 shadow-sm shadow-cyan-500/20">
            <Shield size={12} />
            <span className="text-[10px] font-black uppercase tracking-tighter">{zh ? '凭据中心' : 'VAULT'}</span>
          </div>
          <div className="h-4 w-[1px] bg-black/5 mx-1" />
          <div className="flex flex-wrap items-center gap-2">
             <div className="relative">
                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/20" />
                <input
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={zh ? '快速搜索设备或账号...' : 'Quick search...'}
                  className="w-48 pl-8 pr-3 py-1.5 rounded-lg bg-black/[0.02] border-none text-[11px] text-black/70 placeholder:text-black/20 focus:ring-1 focus:ring-cyan-500/20"
                />
              </div>
              <select
                value={targetFilter}
                onChange={event => setTargetFilter(event.target.value as TargetFilter)}
                className="h-7 rounded-lg border border-black/[0.06] bg-white px-2 text-[10px] font-semibold text-slate-600 outline-none"
              >
                <option value="all">{zh ? '全部目标' : 'All targets'}</option>
                <option value="credential">{zh ? '共享凭据' : 'Shared credentials'}</option>
                <option value="unbound">{zh ? '未绑定设备' : 'Unbound devices'}</option>
              </select>
              <select
                value={roleFilter}
                onChange={event => setRoleFilter(event.target.value as RoleFilter)}
                className="h-7 rounded-lg border border-black/[0.06] bg-white px-2 text-[10px] font-semibold text-slate-600 outline-none"
              >
                <option value="all">{zh ? '全部账号类型' : 'All account types'}</option>
                <option value="normal">{zh ? '普通账号' : 'Normal'}</option>
                <option value="admin">{zh ? '特权账号' : 'Privileged'}</option>
                <option value="enable">{zh ? 'Enable 凭据' : 'Enable'}</option>
              </select>
              {(search || statusFilter !== 'all' || targetFilter !== 'all' || roleFilter !== 'all') && (
                <button
                  type="button"
                  onClick={() => {
                    setSearch('');
                    setStatusFilter('all');
                    setTargetFilter('all');
                    setRoleFilter('all');
                  }}
                  className="h-7 rounded-lg px-2 text-[10px] font-bold text-cyan-700 hover:bg-cyan-50"
                >
                  {zh ? '清空筛选' : 'Clear'}
                </button>
              )}
          </div>
        </div>

        <button
          onClick={fetchStatus}
          disabled={loading}
          className="h-7 px-2.5 rounded-lg bg-black/[0.02] border border-black/[0.04] text-black/40 hover:bg-black/[0.05] hover:text-cyan-600 transition-all"
          title={zh ? '刷新状态' : 'Refresh status'}
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* ═══ High-Density Pro Table ═══ */}
      <div className="bg-white rounded-xl border border-black/[0.06] shadow-md overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse table-fixed">
            <thead>
              <tr className="bg-slate-50 border-b border-black/[0.05]">
                <th className="w-[260px] px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-r border-black/[0.03]">{zh ? '凭据分组 / 未绑定设备' : 'CREDENTIAL / UNBOUND DEVICE'}</th>
                <th className="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-r border-black/[0.03]">{zh ? '普通账号 (Normal)' : 'NORMAL IDENTITY'}</th>
                <th className="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest border-r border-black/[0.03]">{zh ? '特权账号 (Admin)' : 'PRIVILEGED IDENTITY'}</th>
                <th className="px-4 py-2.5 text-[10px] font-black text-slate-400 uppercase tracking-widest">{zh ? '提权凭据 (Enable)' : 'ENABLE SECRET'}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-black/[0.03]">
              {loading && !accountList.length ? (
                <tr><td colSpan={4} className="py-20 text-center"><Loader2 className="inline animate-spin text-cyan-500" size={24} /></td></tr>
              ) : accountList.length === 0 ? (
                <tr><td colSpan={4} className="py-20 text-center text-[11px] text-black/20 font-medium">{zh ? '未检索到凭据数据' : 'No data records found'}</td></tr>
              ) : (
                (() => {
                  const paginatedGroups = rotationGroups.slice((page - 1) * pageSize, page * pageSize);

                  return paginatedGroups.map((group) => {
                    const accounts = group.accounts;
                    const first = accounts[0];
                    
                    // Map accounts to specific columns
                    const roles = {
                      normal: accounts.find(a => a.roleKey === 'normal'),
                      admin: accounts.find(a => a.roleKey === 'admin'),
                      enable: accounts.find(a => a.roleKey === 'enable')
                    };

                    const isDevServer = accounts.every(account => isServer(account.platform || ''));

                    return (
                      <tr key={group.key} className="group hover:bg-slate-50/50 transition-colors">
                        {/* Device Info */}
                        <td className="px-4 py-2 border-r border-black/[0.02]">
                          <div className="flex items-center gap-2.5">
                            <div className="h-8 w-8 rounded-lg bg-white border border-black/5 shadow-sm flex items-center justify-center text-slate-300 group-hover:text-cyan-500 transition-colors">
                              {group.isCredential ? <KeyRound size={14} /> : <Server size={14} />}
                            </div>
                            <div className="min-w-0">
                              {group.isCredential ? (
                                <>
                                  <div className="text-[12px] font-bold text-slate-700 truncate leading-tight tracking-tight">{group.credentialName || (zh ? '已绑定凭据' : 'Bound credential')}</div>
                                  <div className="mt-0.5 flex items-center gap-1.5">
                                    <span className="text-[10px] font-mono text-cyan-600">{group.username || '—'}</span>
                                    <span className="rounded bg-cyan-50 px-1 py-0.5 text-[8px] font-bold text-cyan-600">{zh ? `${group.devices.length} 台设备` : `${group.devices.length} devices`}</span>
                                  </div>
                                </>
                              ) : (
                                <>
                                  <div className="text-[12px] font-bold text-slate-700 truncate leading-tight tracking-tight">{first.hostname}</div>
                                  <div className="flex items-center gap-1.5 mt-0.5">
                                    <span className="text-[10px] font-mono text-slate-400">{first.ip_address}</span>
                                    <span className={`px-1 rounded text-[8px] font-black uppercase ${platformColor(first.platform)}`}>
                                      {platformLabel(first.platform)}
                                    </span>
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                          {group.isCredential ? (
                            <div className="mt-2 flex flex-wrap gap-1 pl-10">
                              {group.devices.slice(0, 3).map(device => (
                                <span key={device.id} className="max-w-[112px] truncate rounded bg-slate-50 px-1.5 py-0.5 text-[8px] text-slate-500" title={`${device.hostname} ${device.ip_address}`}>
                                  {device.hostname} · {device.ip_address}
                                </span>
                              ))}
                              {group.devices.length > 3 && <span className="rounded bg-slate-50 px-1.5 py-0.5 text-[8px] text-slate-400">+{group.devices.length - 3}</span>}
                            </div>
                          ) : null}
                        </td>

                        {/* Account Columns */}
                        {['normal', 'admin', 'enable'].map((role) => {
                          const roleAccounts = accounts.filter(account => account.roleKey === role);
                          const acc = roleAccounts[0] || roles[role as keyof typeof roles];
                          
                          // Optimization: Hide Enable column for servers
                          if (role === 'enable' && isDevServer) {
                            return (
                              <td key={role} className="px-4 py-2 border-r border-black/[0.02] bg-black/[0.01]">
                                <div className="flex items-center justify-center gap-1.5 opacity-20 grayscale">
                                  <Shield size={10} />
                                  <span className="text-[9px] font-black tracking-widest">{zh ? '不适用' : 'N/A'}</span>
                                </div>
                              </td>
                            );
                          }

                          if (!acc) return <td key={role} className="px-4 py-2 border-r border-black/[0.02] text-center"><span className="text-[10px] text-black/5 font-black">N/A</span></td>;

                          const credentialId = credentialIdFor(acc);
                          const secretType: 'password' | 'enable_password' = role === 'enable' ? 'enable_password' : 'password';
                          const secretKey = `${credentialId}:${secretType}`;
                          const isRevealed = Boolean(credentialId && revealedSecret?.id === credentialId && revealedSecret.type === secretType);

                          return (
                            <td key={role} className={`px-4 py-2 border-r border-black/[0.02] ${roleAccounts.some(account => account.currentExpired) ? 'bg-red-50/20' : ''}`}>
                              <div className="flex items-center justify-between gap-2">
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-1.5">
                                    <span className="text-[11px] font-mono font-bold text-slate-600 truncate">{acc.currentUsername || '—'}</span>
                                    {group.isCredential && roleAccounts.length > 1 && <span className="rounded bg-slate-100 px-1 py-0.5 text-[8px] font-bold text-slate-400">{zh ? `${roleAccounts.length} 台` : `${roleAccounts.length} devices`}</span>}
                                    {acc.currentExpiresAt && (
                                      <span className={`text-[9px] font-black ${acc.currentExpired ? 'text-red-500' : 'text-emerald-500/60'}`}>
                                        {acc.currentExpired ? 'EXP' : `${acc.currentDays}d`}
                                      </span>
                                    )}
                                  </div>
                                  <div className="flex items-center justify-between text-[8px] font-bold uppercase tracking-tighter mt-0.5">
                                    <span className="text-slate-300">
                                      {acc.currentLastRotated 
                                        ? `ROT: ${new Date(acc.currentLastRotated).toLocaleDateString()}` 
                                        : (zh ? '未曾轮换' : 'NOT ROTATED')}
                                    </span>
                                    <span className={acc.currentExpired ? 'text-red-400' : 'text-slate-300'}>
                                      {acc.currentExpiresAt 
                                        ? `EXP: ${new Date(acc.currentExpiresAt).toLocaleDateString()}` 
                                        : (zh ? '到期时间待定' : 'EXP: PENDING')}
                                    </span>
                                  </div>
                                  {isAdministrator && credentialId && (
                                    <div className="mt-1 flex items-center gap-1">
                                      <span className="text-[9px] font-medium text-slate-300">{zh ? '凭据中心密码' : 'Vault secret'}</span>
                                      <button
                                        type="button"
                                        onClick={() => { void revealCredentialSecret(acc, secretType); }}
                                        className={`inline-flex h-5 w-5 items-center justify-center rounded border ${isRevealed ? 'border-cyan-500 bg-cyan-500 text-white' : 'border-slate-200 bg-white text-slate-400 hover:border-cyan-300 hover:text-cyan-600'}`}
                                        title={isRevealed ? (zh ? '隐藏密码' : 'Hide password') : (zh ? '查看凭据密码' : 'View credential password')}
                                      >
                                        {secretLoading === secretKey ? <RefreshCw size={10} className="animate-spin" /> : isRevealed ? <EyeOff size={10} /> : <Eye size={10} />}
                                      </button>
                                      {isRevealed && (
                                        <>
                                          <button
                                            type="button"
                                            onClick={() => { void copyRevealedSecret(); }}
                                            className="inline-flex h-5 w-5 items-center justify-center rounded border border-slate-200 bg-white text-slate-400 hover:border-cyan-300 hover:text-cyan-600"
                                            title={zh ? '复制并记录审计' : 'Copy and audit'}
                                          >
                                            {secretCopied ? <Check size={10} /> : <Copy size={10} />}
                                          </button>
                                          <span className="max-w-28 truncate rounded bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] text-cyan-300" title={revealedSecret.secret}>{revealedSecret.secret}</span>
                                        </>
                                      )}
                                      <button
                                        type="button"
                                        onClick={() => openCredentialEditor(group.isCredential
                                          ? { ...acc, hostname: `${group.credentialName || '凭据'}（${group.devices.length}台设备）` }
                                          : acc, secretType)}
                                        className="rounded border border-cyan-200 bg-cyan-50 px-1.5 py-0.5 text-[9px] font-semibold text-cyan-700 hover:bg-cyan-100"
                                        title={zh ? '轮换权威密码并同步关联设备' : 'Rotate the authoritative password and synchronize bound devices'}
                                      >
                                        {zh ? '轮换并同步' : 'Rotate & Sync'}
                                      </button>
                                    </div>
                                  )}
                                  {!credentialId && (
                                    <div className="mt-1 flex items-center gap-1">
                                      <span className="text-[9px] font-medium text-slate-300">{zh ? '设备本地密码' : 'Device-local password'}</span>
                                      {isAdministrator && (
                                        <>
                                          {(() => {
                                            const localRole = acc.roleKey as 'normal' | 'admin' | 'enable';
                                            const localKey = `${acc.id}:${localRole}`;
                                            const isLocalRevealed = localRevealedSecret?.deviceId === acc.id && localRevealedSecret.role === localRole;
                                            return (
                                              <>
                                                <button
                                                  type="button"
                                                  onClick={() => { void revealDeviceLocalSecret(acc); }}
                                                  className={`inline-flex h-5 w-5 items-center justify-center rounded border ${isLocalRevealed ? 'border-amber-500 bg-amber-500 text-white' : 'border-slate-200 bg-white text-slate-400 hover:border-amber-300 hover:text-amber-600'}`}
                                                  title={isLocalRevealed ? (zh ? '隐藏设备本地密码' : 'Hide device-local password') : (zh ? '查看设备本地密码' : 'View device-local password')}
                                                >
                                                  {localSecretLoading === localKey ? <RefreshCw size={10} className="animate-spin" /> : isLocalRevealed ? <EyeOff size={10} /> : <Eye size={10} />}
                                                </button>
                                                {isLocalRevealed && (
                                                  <>
                                                    <button
                                                      type="button"
                                                      onClick={() => { void copyDeviceLocalSecret(); }}
                                                      className="inline-flex h-5 w-5 items-center justify-center rounded border border-slate-200 bg-white text-slate-400 hover:border-amber-300 hover:text-amber-600"
                                                      title={zh ? '复制并记录审计' : 'Copy and audit'}
                                                    >
                                                      {localSecretCopied ? <Check size={10} /> : <Copy size={10} />}
                                                    </button>
                                                    <span className="max-w-28 truncate rounded bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] text-amber-300" title={localRevealedSecret.secret}>{localRevealedSecret.secret}</span>
                                                  </>
                                                )}
                                              </>
                                            );
                                          })()}
                                          <button
                                            type="button"
                                            onClick={() => setPendingRotation(acc)}
                                            className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[9px] font-semibold text-amber-700 hover:bg-amber-100"
                                            title={zh ? '在设备上生成新密码、验证后写回权威存储' : 'Generate a new password on the device, verify it, then update authoritative storage'}
                                          >
                                            {zh ? '立即轮换' : 'Rotate Now'}
                                          </button>
                                        </>
                                      )}
                                    </div>
                                  )}
                                </div>

                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  });
                })()
              )}
            </tbody>
          </table>
        </div>

        {/* Footer Info & Pagination */}
        <div className="px-4 py-2.5 bg-slate-50 border-t border-black/[0.05] flex items-center justify-between">
          <div className="flex items-center gap-4">
             <div className="flex items-center gap-1.5 text-[9px] font-bold text-slate-400 uppercase">
                <span className="w-2 h-2 rounded-full bg-emerald-500" /> {zh ? '监控正常' : 'Healthy'}
             </div>
             <div className="flex items-center gap-1.5 text-[9px] font-bold text-slate-400 uppercase">
                <span className="w-2 h-2 rounded-full bg-red-500" /> {zh ? '凭据过期' : 'Expired'}
             </div>
          </div>
          
          <Pagination
            currentPage={page}
            totalItems={rotationGroups.length}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(v) => { setPage(1); setPageSize(v); }}
            onPageChange={setPage}
            language={language}
          />
        </div>
      </div>
      </div>
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
                <input
                  type="password"
                  value={credentialForm.oldSecret}
                  onChange={event => setCredentialForm(previous => ({ ...previous, oldSecret: event.target.value }))}
                  autoComplete="current-password"
                  className="w-full rounded-xl border border-black/10 px-3 py-2.5 text-sm text-[#164e63] outline-none focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/10"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-black/55">{editingCredential.type === 'enable_password' ? (zh ? '新 Enable 密码' : 'New Enable password') : (zh ? '新密码' : 'New password')}</label>
                <input
                  type="password"
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
