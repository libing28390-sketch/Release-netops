import React, { useState, useMemo, useEffect, useRef } from 'react';
import { 
  Search, Terminal, Monitor, Lock, Info, 
  Copy, ShieldCheck, RefreshCw, ChevronLeft, ChevronRight, Send, ChevronDown, UserCheck,
  Database, Server, Cpu, Key, FolderTree, Globe, X, Eye, EyeOff
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import TerminalWindow from '../components/access/TerminalWindow';
import { DataTable } from '../components/DataTable';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import DeviceMfaModal from './AccessCenterTab/components/DeviceMfaModal';

interface Device {
  id: string;
  asset_id?: string;
  hostname: string;
  ip_address: string;
  status: 'online' | 'offline' | 'pending';
  platform?: string;
  management_port?: number;
  normal_username?: string;
  admin_username?: string;
  site?: string;
  site_name?: string;
  site_id?: string;
  device_category?: string;
  role?: string;
  vendor?: string;
}

type AccessTreeKind = 'root' | 'site' | 'type' | 'role';
interface AccessTreeNode {
  id: string;
  label: string;
  kind: AccessTreeKind;
  count: number;
  children: AccessTreeNode[];
  deviceIds: string[];
}

function accessSiteOf(device: Device, isZh: boolean): { key: string; label: string } {
  const label = device.site_name || device.site || (isZh ? '未分配站点' : 'Unassigned site');
  return { key: device.site_id || label, label };
}

function accessTypeOf(device: Device, isZh: boolean): { key: string; label: string } {
  const raw = `${device.device_category || ''} ${device.role || ''} ${device.platform || ''}`.toLowerCase();
  if (/(server|linux|windows|unix)/.test(raw)) return { key: 'server', label: isZh ? '服务器' : 'Servers' };
  if (/(firewall|fw|router|switch|network|f5|load.?balanc|wireless|ap)/.test(raw)) return { key: 'network', label: isZh ? '网络设备' : 'Network devices' };
  return { key: 'other', label: isZh ? '其他资产' : 'Other assets' };
}

function accessRoleOf(device: Device, isZh: boolean): { key: string; label: string } {
  const raw = `${device.role || ''} ${device.device_category || ''} ${device.platform || ''}`.toLowerCase();
  if (/(firewall|fw|防火墙)/.test(raw)) return { key: 'firewall', label: isZh ? '防火墙' : 'Firewalls' };
  if (/(router|路由)/.test(raw)) return { key: 'router', label: isZh ? '路由器' : 'Routers' };
  if (/(load.?balanc|f5|负载)/.test(raw)) return { key: 'load_balancer', label: isZh ? '负载均衡' : 'Load balancers' };
  if (/(switch|交换)/.test(raw)) return { key: 'switch', label: isZh ? '交换机' : 'Switches' };
  if (/(server|linux|windows|unix)/.test(raw)) return { key: 'server', label: isZh ? '服务器' : 'Servers' };
  return { key: 'other', label: isZh ? '其他角色' : 'Other roles' };
}

function buildAccessTree(devices: Device[], isZh: boolean): AccessTreeNode {
  const root: AccessTreeNode = {
    id: 'root',
    label: isZh ? '全部资产' : 'All assets',
    kind: 'root',
    count: devices.length,
    children: [],
    deviceIds: devices.map((device) => device.id),
  };
  const findOrCreate = (parent: AccessTreeNode, id: string, label: string, kind: AccessTreeKind) => {
    let node = parent.children.find((item) => item.id === id);
    if (!node) {
      node = { id, label, kind, count: 0, children: [], deviceIds: [] };
      parent.children.push(node);
    }
    return node;
  };
  devices.forEach((device) => {
    const site = accessSiteOf(device, isZh);
    const type = accessTypeOf(device, isZh);
    const role = accessRoleOf(device, isZh);
    const siteNode = findOrCreate(root, `site:${site.key}`, site.label, 'site');
    const typeNode = findOrCreate(siteNode, `${siteNode.id}:type:${type.key}`, type.label, 'type');
    const roleNode = findOrCreate(typeNode, `${typeNode.id}:role:${role.key}`, role.label, 'role');
    [siteNode, typeNode, roleNode].forEach((node) => {
      node.count += 1;
      node.deviceIds.push(device.id);
    });
  });
  return root;
}

interface AccessCenterTabProps {
  devices: Device[];
  language: string;
  showToast: (msg: string, type: 'success' | 'error' | 'info') => void;
}

export default function AccessCenterTab({ devices, language, showToast }: AccessCenterTabProps) {
  const isZh = language === 'zh';
  const [searchQuery, setSearchQuery] = useState('');

  // Read ?q= URL param on mount to pre-fill search (deep-link from NPA hop popover)
  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      const q = params.get('q');
      if (q) setSearchQuery(q);
    } catch { /* ignore */ }
  }, []);
  const [activeProtocol, setActiveProtocol] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedTreeKey, setSelectedTreeKey] = useState('root');
  const [expandedTreeKeys, setExpandedTreeKeys] = useState<Set<string>>(new Set(['root']));
  const [accessTreeCollapsed, setAccessTreeCollapsed] = useState(false);
  
  // --- MFA Logic ---
  const [showMFAModal, setShowMFAModal] = useState(false);
  const [fixedPassword, setFixedPassword] = useState('');
  const [showFixedPassword, setShowFixedPassword] = useState(false);
  const [dynamicCode, setDynamicCode] = useState('');
  // Kept only for backward-compatible request payloads; the active flow uses
  // the authenticator TOTP code directly and never requests a webhook code.
  const [mfaNonce, setMfaNonce] = useState('');
  const [mfaTarget, setMfaTarget] = useState<{device: Device, appType: 'xshell' | 'web', identity: 'normal' | 'privileged'} | null>(null);
  // Legacy webhook-request state is retained for old sessions only; the
  // rendered authorization dialog no longer exposes it.
  const [isSending, setIsSending] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [approvers] = useState<Array<{ id: string; username: string }>>([]);
  const [selectedApproverId, setSelectedApproverId] = useState('');

  // Real current username from session
  const [currentUsername, setCurrentUsername] = useState<string>('');
  const autoLoginDeviceRef = useRef<string | null>(null);
  const [autoLoginInProgress, setAutoLoginInProgress] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('auto') === 'normal';
    } catch {
      return false;
    }
  });
  const autoLoginModeRef = useRef(autoLoginInProgress);

  // Resolve the real requester from the authenticated session.  Device
  // authorization must never trust a username supplied by the browser.
  useEffect(() => {
    const fetchCurrentUser = async () => {
      try {
        const token = localStorage.getItem('netops_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const sessionRes = await fetch('/api/session', { headers });
        if (sessionRes.ok) {
          const sessionData = await sessionRes.json();
          setCurrentUsername(sessionData.user?.username || '');
        }
      } catch (err) {
        console.error('Failed to fetch current user', err);
      }
    };
    fetchCurrentUser();
  }, []);

  const getProtocol = (dev: Device) => {
    const platform = (dev.platform || '').toLowerCase();
    if (platform.includes('windows')) return 'RDP';
    return 'SSH'; 
  };

  const baseFilteredDevices = useMemo(() => {
    const list = Array.isArray(devices) ? devices : [];
    const query = (searchQuery || '').toLowerCase();
    
    return list.filter(d => {
      const proto = getProtocol(d);
      const matchesProtocol = activeProtocol === 'ALL' || proto === activeProtocol;
      const name = (d?.hostname || '').toLowerCase();
      const ip = (d?.ip_address || '').toLowerCase();
      const matchesSearch = name.includes(query) || ip.includes(query);
      return matchesProtocol && matchesSearch;
    });
  }, [devices, searchQuery, activeProtocol]);

  const accessTree = useMemo(
    () => buildAccessTree(baseFilteredDevices, isZh),
    [baseFilteredDevices, isZh],
  );
  const accessTreeIndex = useMemo(() => {
    const index = new Map<string, AccessTreeNode>();
    const visit = (node: AccessTreeNode) => {
      index.set(node.id, node);
      node.children.forEach(visit);
    };
    visit(accessTree);
    return index;
  }, [accessTree]);
  const filteredDevices = useMemo(() => {
    const node = accessTreeIndex.get(selectedTreeKey);
    if (!node || selectedTreeKey === 'root') return baseFilteredDevices;
    const ids = new Set(node.deviceIds);
    return baseFilteredDevices.filter((device) => ids.has(device.id));
  }, [accessTreeIndex, baseFilteredDevices, selectedTreeKey]);
  const selectedTreeLabel = accessTreeIndex.get(selectedTreeKey)?.label || accessTree.label;
  const totalCount = filteredDevices.length;
  const totalPages = Math.ceil(totalCount / pageSize);
  const currentData = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredDevices.slice(start, start + pageSize);
  }, [filteredDevices, currentPage, pageSize]);

  useEffect(() => {
    if (selectedTreeKey !== 'root' && !accessTreeIndex.has(selectedTreeKey)) {
      setSelectedTreeKey('root');
      setCurrentPage(1);
    }
  }, [accessTreeIndex, selectedTreeKey]);

  const toggleTreeNode = (node: AccessTreeNode) => {
    if (!node.children.length) return;
    setExpandedTreeKeys((current) => {
      const next = new Set(current);
      if (next.has(node.id)) next.delete(node.id);
      else next.add(node.id);
      return next;
    });
  };

  const renderTreeNode = (node: AccessTreeNode, depth = 0): React.ReactNode => {
    const expanded = expandedTreeKeys.has(node.id);
    const selected = selectedTreeKey === node.id;
    const Icon = node.kind === 'root' ? Database : node.kind === 'site' ? Server : node.kind === 'type' ? Cpu : Key;
    return (
      <div key={node.id}>
        <div className="flex items-center gap-1" style={{ paddingLeft: `${depth * 16}px` }}>
          <button
            type="button"
            onClick={() => toggleTreeNode(node)}
            className="flex h-7 w-6 shrink-0 items-center justify-center rounded-md text-slate-400 hover:bg-cyan-50 hover:text-cyan-700"
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {node.children.length ? (expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <span className="w-3" />}
          </button>
          <button
            type="button"
            onClick={() => { setSelectedTreeKey(node.id); setCurrentPage(1); }}
            className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition-colors ${selected ? 'bg-cyan-50 font-semibold text-cyan-800' : 'text-slate-600 hover:bg-slate-50'}`}
          >
            <Icon size={14} className={selected ? 'text-cyan-600' : 'text-slate-400'} />
            <span className="min-w-0 flex-1 truncate">{node.label}</span>
            <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-500">{node.count}</span>
          </button>
        </div>
        {expanded && node.children.length > 0 && (
          <div>{node.children.map((child) => renderTreeNode(child, depth + 1))}</div>
        )}
      </div>
    );
  };

  // Reset all MFA-related state to a clean slate.
  const resetMFAState = () => {
    setFixedPassword('');
    setShowFixedPassword(false);
    setDynamicCode('');
  };

  const openMFAModal = (target: { device: Device; appType: 'xshell' | 'web'; identity: 'normal' | 'privileged' }) => {
    resetMFAState();
    setMfaTarget(target);
    setShowMFAModal(true);
  };

  const closeMFAModal = () => {
    setShowMFAModal(false);
    setMfaTarget(null);
    resetMFAState();
  };

  const handleAccessRequest = async (dev: Device, appType: 'xshell' | 'web', identity: 'normal' | 'privileged') => {
    if (appType === 'xshell') {
      // 1. Get saved path from Profile Settings (localStorage keys: local_terminal_path, terminal_app)
      let terminalPath = localStorage.getItem('local_terminal_path');
      let terminalType = localStorage.getItem('terminal_app') || 'xshell';

      if (!terminalPath || terminalPath === '') {
        showToast(isZh ? '请先在个人信息中配置终端路径' : 'Please configure terminal path in Profile first', 'info');
        return;
      }

      // Privileged local terminal MUST pass MFA before the backend will release credentials
      if (identity === 'privileged') {
        openMFAModal({ device: dev, appType: 'xshell', identity });
        return;
      }

      // Normal identity: launch directly
      launchLocalTerminal(dev, terminalPath, terminalType, 'normal');
      return;
    }

    if (identity === 'normal') {
      requestSession(dev, 'normal');
      return;
    }

    // Privileged web: require MFA
    openMFAModal({ device: dev, appType: 'web', identity });
  };

  const launchLocalTerminal = async (
    dev: Device,
    terminalPath: string,
    terminalType: string,
    level: 'normal' | 'admin',
    mfaCode?: string,
    fixedPw?: string,
    mfaNonce?: string,
  ) => {
    const host = dev.ip_address;
    const user = level === 'admin' ? (dev.admin_username || 'admin') : (dev.normal_username || 'user');
    let port = Number(dev.management_port || 22) || 22;
    let sessionToken = '';
    const authToken = localStorage.getItem('netops_token');
    const authHeaders = authToken
      ? { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` }
      : { 'Content-Type': 'application/json' };

    // MFA verification for privileged access — still goes through backend
    if (level === 'admin') {
      if (!mfaCode || !fixedPw) {
        openMFAModal({ device: dev, appType: 'xshell', identity: 'privileged' });
        return;
      }
      try {
        const res = await fetch('/api/system/launch-terminal', {
          method: 'POST',
            headers: authHeaders,
          body: JSON.stringify({
            app_type: terminalType,
            path: terminalPath,
            host, user,
            requester_username: currentUsername || 'unknown',
            access_level: 'admin',
            mfa_code: mfaCode,
            fixed_pin: fixedPw,
            mfa_nonce: mfaNonce,
          })
        });
        const result = await res.json();
        if (result.requires_mfa) { openMFAModal({ device: dev, appType: 'xshell', identity: 'privileged' }); return; }
        if (!result.success && result.error && !result.error.includes('path not found') && !result.error.includes('Executable')) {
          showToast(result.error, 'error'); return;
        }
        if (result.success && result.session_token) {
          sessionToken = result.session_token;
        }
        if (result.success && result.port) {
          port = Number(result.port) || port;
        }
        if (result.success && !result.client_side) {
          showToast(isZh ? '\u6b63\u5728\u542f\u52a8\u672c\u5730\u7ec8\u7aef' : 'Launching local terminal', 'success');
          return;
        }
        // A remote/container backend cannot execute the Windows client. In
        // that case it returns a short-lived token and we use the protocol
        // fallback below.
      } catch {
        showToast(isZh ? 'MFA 验证请求失败' : 'MFA verification failed', 'error');
        return;
      }
    } else {
      // Normal level: Fetch password from backend first (which also writes the audit log)
      try {
        const res = await fetch('/api/system/launch-terminal', {
          method: 'POST',
            headers: authHeaders,
          body: JSON.stringify({
            app_type: terminalType,
            path: terminalPath,
            host, user,
            requester_username: currentUsername || 'unknown',
            access_level: level,
          })
        });
        const result = await res.json();
        if (result.success && result.session_token) {
          sessionToken = result.session_token;
        }
        if (result.success && result.port) {
          port = Number(result.port) || port;
        }
        if (result.success && !result.client_side) {
          showToast(isZh ? '\u6b63\u5728\u542f\u52a8\u672c\u5730\u7ec8\u7aef' : 'Launching local terminal', 'success');
          return;
        }
        if (!result.success) {
          showToast(result.error || (isZh ? '无法创建本地终端会话' : 'Unable to create local terminal session'), 'error');
          return;
        }
      } catch (err) {
        console.error('Failed to fetch password for normal user launch', err);
        showToast(isZh ? '无法获取本地终端会话，请重试' : 'Unable to create the local terminal session. Please retry.', 'error');
        return;
      }
    }

    // Remote Docker/Ubuntu deployments cannot execute a Windows terminal
    // process. Delegate the one-time session token to the local loopback
    // Terminal Agent instead of using a browser custom protocol. This avoids
    // browser confirmation dialogs and transient blank tabs.
    try {
      if (!sessionToken) {
        showToast(isZh ? '\u672c\u5730\u7ec8\u7aef\u4f1a\u8bdd\u65e0\u6548\uff0c\u8bf7\u91cd\u8bd5' : 'The local terminal session is invalid. Please retry.', 'error');
        return;
      }

      const agentBase = (localStorage.getItem('terminal_agent_url') || 'http://127.0.0.1:17890').replace(/\/$/, '');
      const agentRes = await fetch(`${agentBase}/v1/terminal/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          backend_url: window.location.origin,
          session_token: sessionToken,
          client: terminalType,
          path: terminalPath || '',
        }),
      });
      const agentResult = await agentRes.json().catch(() => ({}));
      if (!agentRes.ok || !agentResult.success) {
        throw new Error(agentResult.error || `HTTP ${agentRes.status}`);
      }

      const appName = terminalType === 'standard' ? 'SSH' : terminalType === 'xshell' ? 'Xshell' : terminalType === 'putty' ? 'PuTTY' : terminalType === 'securecrt' ? 'SecureCRT' : terminalType === 'mobaxterm' ? 'MobaXterm' : 'Terminal';

      showToast(
        isZh ? `正在拉起 ${appName}` : `Launching ${appName}`,
        'success'
      );

    } catch (err) {
      console.error('Local Terminal Agent launch failed', err);
      showToast(
        isZh
          ? '\u65e0\u6cd5\u8fde\u63a5\u672c\u5730\u7ec8\u7aef\u4ee3\u7406\uff0c\u8bf7\u5148\u542f\u52a8 Terminal Agent\uff08\u4ec5\u76d1\u542c 127.0.0.1:17890\uff09'
          : 'Cannot connect to the local Terminal Agent. Start it on this workstation (127.0.0.1:17890) and retry.',
        'error',
      );
    }
  };

  const sendMFACode = async () => {
    if (!selectedApproverId) {
      showToast(isZh ? '请先选择审批人' : 'Select approver first', 'info');
      return;
    }
    if (isSending || countdown > 0) return;
    setIsSending(true);
    try {
      const res = await fetch('/api/pam/mfa/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          user_id: 'current_user', 
          username: currentUsername || 'Admin',
          approver_id: selectedApproverId 
        })
      });
      const result = await res.json();
      if (result.success) {
        showToast(result.message, 'success');
        if (result.index) setMfaNonce(result.index);
        setCountdown(60);
      } else {
        showToast(result.error, 'error');
      }
    } catch (err) {
      showToast('MFA Request Failed', 'error');
    } finally {
      setIsSending(false);
    }
  };

  const handleMFAVerify = () => {
    if (fixedPassword.length < 6 || dynamicCode.length < 6) {
      showToast(isZh ? '请输入完整的验证码' : 'Enter complete code', 'info');
      return;
    }

    if (!mfaTarget) return;

    // Snapshot codes + target before closing, so state reset doesn't clear them.
    const target = mfaTarget;
    const code = dynamicCode;
    const pin = fixedPassword;

    if (target.appType === 'xshell') {
      const terminalPath = localStorage.getItem('local_terminal_path') || '';
      const terminalType = localStorage.getItem('terminal_app') || 'xshell';
      if (!terminalPath) {
        showToast(isZh ? '请先在个人信息中配置终端路径' : 'Please configure terminal path in Profile first', 'info');
        return;
      }
      closeMFAModal();
      launchLocalTerminal(target.device, terminalPath, terminalType, 'admin', code, pin);
      return;
    }

    // Privileged web login via PAM Session Gateway
    closeMFAModal();
    requestSession(target.device, 'admin', code, pin);
  };

  const requestSession = async (dev: Device, accessLevel: 'normal' | 'admin', mfaCode?: string, fixedPw?: string, mfaNonce?: string) => {
    const assetId = dev.asset_id || dev.id; // Fallback to id if asset_id is not mapped in UI properly yet
    
    try {
      const res = await fetch('/api/pam/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('netops_token') ? { Authorization: `Bearer ${localStorage.getItem('netops_token')}` } : {}),
        },
        body: JSON.stringify({
          asset_id: assetId,
          access_level: accessLevel,
          connect_method: 'web',
          mfa_code: mfaCode,
          fixed_pin: fixedPw,
          mfa_nonce: mfaNonce,
          requester_username: currentUsername || 'Admin',
        })
      });
      const result = await res.json();
      
      if (!res.ok) {
        showToast(result.detail || result.error || 'Failed to request session', 'error');
        if (autoLoginModeRef.current) {
          autoLoginModeRef.current = false;
          setAutoLoginInProgress(false);
        }
        return;
      }
      
      if (result.requires_mfa) {
        // Only trigger MFA if the backend says we need it (should only happen for admin without provided codes)
        setMfaTarget({ device: dev, appType: 'web', identity: 'privileged' });
        setFixedPassword('');
        setDynamicCode('');
        setShowMFAModal(true);
        return;
      }

      if (result.session_token) {
        const terminalUrl = `/terminal?session=${result.session_token}&hostname=${encodeURIComponent(dev.hostname || 'Terminal')}`;
        if (autoLoginModeRef.current) {
          // The new tab is intentionally still on the loading gate. Replace
          // that tab directly so the workspace UI never flashes first.
          window.location.assign(terminalUrl);
          return;
        }
        const terminalWindow = window.open(terminalUrl, '_blank');
        // A deep-link auto login may be considered a popup by the browser;
        // fall back to the same tab so the user is never left without a
        // terminal after the normal session has been created.
        if (!terminalWindow) window.location.assign(terminalUrl);
      } else if (autoLoginModeRef.current) {
        autoLoginModeRef.current = false;
        setAutoLoginInProgress(false);
      }
    } catch (err) {
      showToast('Session request failed', 'error');
      if (autoLoginModeRef.current) {
        autoLoginModeRef.current = false;
        setAutoLoginInProgress(false);
      }
    }
  };

  // Topology hover actions arrive here as a deep link. Execute only once per
  // device so a state refresh cannot create duplicate PAM sessions.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('auto') !== 'normal') return;
    const deviceId = params.get('device_id');
    if (!deviceId || autoLoginDeviceRef.current === deviceId) return;
    const target = devices.find((device) => device.id === deviceId);
    if (!target) {
      if (devices.length > 0) {
        autoLoginModeRef.current = false;
        setAutoLoginInProgress(false);
      }
      return;
    }

    autoLoginDeviceRef.current = deviceId;
    autoLoginModeRef.current = true;
    setAutoLoginInProgress(true);
    void requestSession(target, 'normal');
    params.delete('auto');
    params.delete('device_id');
    const nextUrl = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`;
    window.history.replaceState(window.history.state, '', nextUrl);
  }, [devices]);

  if (autoLoginInProgress) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center bg-slate-950 text-white">
        <div className="text-center">
          <div className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400" />
          <p className="mt-4 text-sm font-semibold">正在建立普通账号会话...</p>
          <p className="mt-1 text-xs text-white/45">登录成功后将自动进入终端</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full animate-in fade-in duration-500 overflow-hidden text-slate-700 font-sans" style={{ background: '#f8fafc' }}>
      <PageHero
        icon={Database}
        title={isZh ? '操作工作台' : 'Operation Workspace'}
        subtitle={isZh ? '资产统一入口 · 安全受控访问' : 'Unified asset gateway · Controlled secure access'}
        actions={
          <div className="relative group">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300 group-focus-within:text-[#00bceb] transition-colors" />
            <input
              type="text"
              placeholder="搜索资产名称或 IP 地址..."
              className="w-80 pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-sm font-medium"
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
            />
          </div>
        }
        extras={
          <div className="flex items-center gap-2">
            {['ALL', 'SSH', 'RDP'].map((proto) => (
              <button
                key={proto}
                onClick={() => { setActiveProtocol(proto); setCurrentPage(1); }}
                className={`px-5 py-2 rounded-xl text-[10px] font-black tracking-widest transition-all uppercase ${
                  activeProtocol === proto
                  ? 'bg-[#00bceb] text-white shadow-lg shadow-[#00bceb]/20'
                  : 'bg-white text-slate-400 border border-slate-200 hover:border-[#00bceb] hover:text-[#00bceb]'
                }`}
              >
                {proto}
              </button>
            ))}
          </div>
        }
      />

      {/* Table Section */}
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div className={`grid min-h-[calc(100vh-250px)] grid-cols-1 gap-4 ${accessTreeCollapsed ? 'xl:grid-cols-[56px_minmax(0,1fr)]' : 'xl:grid-cols-[290px_minmax(0,1fr)]'}`}>
          <aside className={`relative rounded-2xl border border-slate-200 bg-white shadow-sm ${accessTreeCollapsed ? 'p-2' : 'p-3'}`}>
            <div className={`mb-3 border-b border-slate-100 px-2 pb-3 ${accessTreeCollapsed ? 'hidden' : ''}`}>
              <div className="text-sm font-bold text-slate-800">{isZh ? '资产分类树' : 'Asset tree'}</div>
              <div className="mt-0.5 text-[11px] text-slate-400">{isZh ? '站点 → 类型 → 角色' : 'Site → type → role'}</div>
            </div>
            <button
              type="button"
              onClick={() => setAccessTreeCollapsed((current) => !current)}
              className={`rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-cyan-50 hover:text-cyan-700 ${accessTreeCollapsed ? 'mx-auto block' : 'absolute right-3 top-3'}`}
              title={accessTreeCollapsed ? (isZh ? '展开资产分类树' : 'Expand asset tree') : (isZh ? '折叠资产分类树' : 'Collapse asset tree')}
              aria-label={accessTreeCollapsed ? (isZh ? '展开资产分类树' : 'Expand asset tree') : (isZh ? '折叠资产分类树' : 'Collapse asset tree')}
            >
              {accessTreeCollapsed ? <FolderTree size={15} /> : <ChevronRight size={15} className="rotate-180" />}
            </button>
            <div className={`max-h-[calc(100vh-320px)] overflow-y-auto ${accessTreeCollapsed ? 'hidden' : ''}`}>
              {renderTreeNode(accessTree)}
            </div>
          </aside>
          <div className="min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3 text-xs text-slate-500">
              <Database size={14} className="text-cyan-600" />
              <span>{isZh ? '当前分类' : 'Current branch'}:</span>
              <span className="rounded-full bg-cyan-50 px-2.5 py-1 font-semibold text-cyan-700">{selectedTreeLabel}</span>
              <span className="ml-auto tabular-nums">{totalCount} {isZh ? '台设备' : 'devices'}</span>
            </div>
            <div className="min-h-0 overflow-auto">
              <DataTable className="text-left">
            <thead>
              <tr className="bg-slate-50/50 border-b border-slate-200">
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em]">资产信息</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em]">连接地址</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em]">协议</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em] text-right">终端登录（本地）</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em] text-right">Web 登录</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {currentData.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-16 text-center text-sm text-slate-400">
                    {isZh ? '当前分类暂无可访问设备' : 'No accessible devices in this branch'}
                  </td>
                </tr>
              ) : currentData.map((dev) => (
                <tr key={dev.id} className="hover:bg-cyan-50/30 transition-colors group">
                  <td className="px-8 py-5">
                    <div className="flex items-center gap-4">
                      <div className="p-2.5 bg-slate-50 rounded-xl group-hover:bg-cyan-100 transition-colors">
                        <Server className="w-4 h-4 text-slate-400 group-hover:text-[#00bceb]" />
                      </div>
                      <div>
                        <div className="text-sm font-bold text-slate-800">{dev.hostname}</div>
                        <div className="text-[10px] text-slate-400 font-bold uppercase tracking-tighter mt-0.5">{dev.platform || 'General Linux'}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-8 py-5">
                    <span className="font-mono text-xs font-bold text-slate-500 bg-slate-50 px-2 py-1 rounded-md">{dev.ip_address}</span>
                  </td>
                  <td className="px-8 py-5">
                    <span className="px-2.5 py-1 bg-slate-100 text-slate-500 text-[10px] font-black rounded-lg uppercase tracking-wider">
                      {getProtocol(dev)}
                    </span>
                  </td>
                  <td className="px-8 py-5 text-right">
                    <div className="flex items-center justify-end gap-2.5">
                      <button 
                        onClick={() => handleAccessRequest(dev, 'xshell', 'normal')}
                        className="flex items-center gap-2 px-3.5 py-2 bg-white border border-slate-200 hover:border-emerald-500 hover:text-emerald-600 hover:bg-emerald-50 text-slate-600 text-[10px] font-black rounded-xl transition-all"
                      >
                        <Terminal className="w-3.5 h-3.5" />
                        {dev.normal_username || 'user'}
                      </button>
                      <button 
                        onClick={() => handleAccessRequest(dev, 'xshell', 'privileged')}
                        className="flex items-center gap-2 px-3.5 py-2 bg-white border border-slate-200 hover:border-orange-500 hover:text-orange-600 hover:bg-orange-50 text-slate-600 text-[10px] font-black rounded-xl transition-all"
                      >
                        <Lock className="w-3.5 h-3.5" />
                        {dev.admin_username || 'root'}
                      </button>
                    </div>
                  </td>
                  <td className="px-8 py-5 text-right">
                    <div className="flex items-center justify-end gap-2.5">
                      <button 
                        onClick={() => handleAccessRequest(dev, 'web', 'normal')}
                        className="flex items-center gap-2 px-3.5 py-2 bg-white border border-slate-200 hover:border-[#00bceb] hover:text-[#00bceb] hover:bg-cyan-50 text-slate-600 text-[10px] font-black rounded-xl transition-all"
                      >
                        <Globe className="w-3.5 h-3.5" />
                        {dev.normal_username || 'user'}
                      </button>
                      <button 
                        onClick={() => handleAccessRequest(dev, 'web', 'privileged')}
                        className="flex items-center gap-2 px-3.5 py-2 bg-white border border-slate-200 hover:border-orange-500 hover:text-orange-600 hover:bg-orange-50 text-slate-600 text-[10px] font-black rounded-xl transition-all"
                      >
                        <Lock className="w-3.5 h-3.5" />
                        {dev.admin_username || 'root'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
              </DataTable>
            </div>
        </div>
      </div>
      </div>

      {/* Pagination Bar */}
      <Pagination
        currentPage={currentPage}
        totalItems={totalCount}
        itemsPerPage={pageSize}
        onItemsPerPageChange={(size) => { setPageSize(size); setCurrentPage(1); }}
        onPageChange={setCurrentPage}
        language={language}
      />

      {showMFAModal && mfaTarget && (
        <DeviceMfaModal
          isZh={isZh}
          currentUsername={currentUsername}
          target={mfaTarget}
          fixedPin={fixedPassword}
          dynamicCode={dynamicCode}
          showFixedPin={showFixedPassword}
          onFixedPinChange={setFixedPassword}
          onDynamicCodeChange={setDynamicCode}
          onToggleFixedPin={() => setShowFixedPassword((value) => !value)}
          onClose={closeMFAModal}
          onVerify={handleMFAVerify}
        />
      )}

      {/* Legacy webhook approval dialog kept unreachable for old state recovery. */}
      <AnimatePresence>
        {false && showMFAModal && (
          <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-[500px] bg-white rounded-[2.5rem] shadow-2xl overflow-hidden border border-slate-100 flex flex-col"
            >
              {/* Modal Header */}
              <div className="bg-slate-50/50 border-b border-slate-100 px-8 py-6 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 bg-cyan-100 text-[#00bceb] rounded-2xl flex items-center justify-center shadow-sm">
                    <ShieldCheck className="w-7 h-7" />
                  </div>
                  <div>
                    <h3 className="font-bold text-slate-800 text-lg tracking-tight">资产特权访问授权</h3>
                    <div className="flex items-center gap-1.5 mt-0.5">
                       <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse"></span>
                       <p className="text-[9px] text-slate-400 font-black uppercase tracking-widest">Dual-Control Audit Required</p>
                    </div>
                  </div>
                </div>
                <button onClick={closeMFAModal} className="p-2.5 hover:bg-white rounded-xl transition-all text-slate-300 hover:text-slate-500 hover:shadow-sm">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="p-10 space-y-8 overflow-y-auto max-h-[80vh] custom-scrollbar">
                {/* Step 1: Approver */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest ml-1">Step 01. 选择授权审批人</label>
                  </div>
                  <div className="relative group">
                    <div className="absolute left-4 top-1/2 -translate-y-1/2 w-8 h-8 bg-white rounded-lg border border-slate-100 flex items-center justify-center text-slate-300 group-focus-within:text-[#00bceb] group-focus-within:border-cyan-100 transition-all shadow-sm">
                       <UserCheck className="w-4 h-4" />
                    </div>
                    <select 
                      value={selectedApproverId}
                      onChange={(e) => setSelectedApproverId(e.target.value)}
                      className="w-full pl-14 pr-10 py-4 bg-slate-50/50 border border-slate-100 rounded-2xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-sm font-bold text-slate-700 appearance-none cursor-pointer"
                    >
                      <option value="" disabled>请选择具备授权权限的管理员...</option>
                      {approvers.map(u => (
                        <option key={u.id} value={u.id}>{u.username} (Administrator)</option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
                  </div>
                </div>

                {/* Step 2: Fixed Password */}
                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest ml-1">Step 02. 个人身份固定码 (6位 PIN)</label>
                  <div className="relative group">
                    <div className="absolute left-4 top-1/2 -translate-y-1/2 w-8 h-8 bg-white rounded-lg border border-slate-100 flex items-center justify-center text-slate-300 group-focus-within:text-[#00bceb] group-focus-within:border-cyan-100 transition-all shadow-sm">
                       <Key className="w-4 h-4" />
                    </div>
                    <input 
                      type={showFixedPassword ? 'text' : 'password'}
                      maxLength={6}
                      value={fixedPassword}
                      onChange={(e) => setFixedPassword(e.target.value.replace(/\D/g, ''))}
                      className="w-full pl-14 pr-12 py-4 bg-slate-50/50 border border-slate-100 rounded-2xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-2xl font-black tracking-[0.5em] text-slate-800 placeholder:text-slate-200"
                      placeholder="••••••"
                    />
                    <button
                      type="button"
                      onClick={() => setShowFixedPassword(!showFixedPassword)}
                      className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-300 hover:text-slate-500 focus:outline-none"
                    >
                      {showFixedPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>

                {/* Step 3: Dynamic Code */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between px-1">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Step 03. 动态授权验证码</label>
                    {mfaNonce && (
                      <span className="px-2 py-0.5 bg-cyan-100 text-[#00bceb] text-[10px] font-black rounded-md animate-bounce">
                        索引编号: #{mfaNonce}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-3">
                    <div className="relative flex-1 group">
                      <div className="absolute left-4 top-1/2 -translate-y-1/2 w-8 h-8 bg-white rounded-lg border border-slate-100 flex items-center justify-center text-slate-300 group-focus-within:text-[#00bceb] group-focus-within:border-cyan-100 transition-all shadow-sm">
                         <RefreshCw className={`w-4 h-4 ${isSending ? 'animate-spin' : ''}`} />
                      </div>
                      <input 
                        type="text"
                        maxLength={6}
                        value={dynamicCode}
                        onChange={(e) => setDynamicCode(e.target.value.replace(/\D/g, ''))}
                        className="w-full pl-14 pr-4 py-4 bg-slate-50/50 border border-slate-100 rounded-2xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-2xl font-black tracking-[0.5em] text-slate-800 placeholder:text-slate-200"
                        placeholder="000000"
                      />
                    </div>
                    <button 
                      onClick={sendMFACode}
                      disabled={isSending || countdown > 0 || !selectedApproverId}
                      className="min-w-[100px] bg-white border border-slate-200 text-[#00bceb] rounded-2xl font-black text-[10px] uppercase tracking-widest hover:border-[#00bceb] hover:bg-cyan-50 disabled:bg-slate-50 disabled:text-slate-300 disabled:border-slate-100 transition-all flex flex-col items-center justify-center gap-1 shadow-sm"
                    >
                      {countdown > 0 ? (
                        <>
                          <span className="text-sm">{countdown}s</span>
                          <span className="text-[8px] opacity-50">后重发</span>
                        </>
                      ) : (
                        <>
                          <Send className="w-4 h-4" />
                          <span>获取验证码</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Footer Actions */}
                <div className="pt-4 space-y-4">
                  <button 
                    onClick={handleMFAVerify}
                    className="w-full py-5 bg-gradient-to-r from-[#00bceb] to-cyan-600 text-white font-black rounded-[1.5rem] hover:shadow-xl hover:shadow-[#00bceb]/30 active:scale-[0.98] transition-all flex items-center justify-center gap-3 text-sm uppercase tracking-widest group"
                  >
                    <ShieldCheck className="w-5 h-5 group-hover:scale-110 transition-transform" />
                    验证并授权访问
                  </button>
                  <div className="bg-slate-50 p-4 rounded-2xl border border-slate-100">
                    <p className="text-[10px] text-center text-slate-400 leading-relaxed font-bold">
                      验证码将发送至选中审批人的飞书，请向其获取。<br/>
                      <span className="text-[#00bceb]">本次操作将记录于特权访问审计日志中。</span>
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
