import React, { useState, useMemo, useEffect, useRef } from 'react';
import { 
  Search, Terminal, Monitor, Lock, Info, 
  Copy, ShieldCheck, RefreshCw, ChevronLeft, ChevronRight, Send, ChevronDown, UserCheck,
  Database, Server, Cpu, Key, FolderTree, Globe, X, Eye, EyeOff, MapPin, Activity, Wifi, Star
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import TerminalWindow from '../components/access/TerminalWindow';
import { DataTable } from '../components/DataTable';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';
import DeviceMfaModal from './AccessCenterTab/components/DeviceMfaModal';
import { createPamWebSession, enabledWebProfiles, ensurePamWebAgent, launchPamWebSession, type WebAccessLevel } from '../api/pamWeb';
import type { WebAccessProfile } from './AssetManagement/types';
import { WebAccessRequestModal } from './AssetManagement/components/WebAccessRequestModal';
import { formatTerminalAgentError, getLocalTerminalConfig, TERMINAL_APP_LABELS } from '../utils/localTerminal';

interface Device {
  id: string;
  asset_id?: string;
  hostname: string;
  ip_address: string;
  status: 'online' | 'offline' | 'pending';
  platform?: string;
  connection_method?: 'ssh' | 'netconf' | 'web' | 'none' | string;
  management_port?: number;
  normal_username?: string;
  admin_username?: string;
  site?: string;
  site_name?: string;
  site_id?: string;
  device_category?: string;
  role?: string;
  vendor?: string;
  /** True when the linked asset has at least one enabled HTTP(S) entry. */
  web_access_enabled?: boolean;
  web_http_enabled?: boolean;
  web_https_enabled?: boolean;
}

type WebScheme = 'http' | 'https';
type AccessCategory = 'ALL' | 'SSH' | 'RDP' | 'WEB';
type AllAccessMethod = 'ssh-terminal' | 'ssh-web' | 'rdp' | 'http' | 'https';

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
  favoriteDeviceIds?: string[];
  onToggleFavorite?: (device: Device) => void;
}

export default function AccessCenterTab({
  devices,
  language,
  showToast,
  favoriteDeviceIds = [],
  onToggleFavorite,
}: AccessCenterTabProps) {
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
  const [activeCategory, setActiveCategory] = useState<AccessCategory>('ALL');
  const [allAccessMethods, setAllAccessMethods] = useState<Record<string, AllAccessMethod>>({});
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

  // Web PAM uses the asset's configured HTTP(S) entries. Credentials are
  // entered by the user inside the workstation system browser.
  const [webAccessTarget, setWebAccessTarget] = useState<Device | null>(null);
  const [webAccessProfiles, setWebAccessProfiles] = useState<WebAccessProfile[]>([]);
  const [webAccessProfileId, setWebAccessProfileId] = useState('');
  const [webAccessLevel, setWebAccessLevel] = useState<WebAccessLevel>('normal');
  const [webAccessReason, setWebAccessReason] = useState('');
  const [webAccessRequesting, setWebAccessRequesting] = useState(false);

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

  const getTerminalProtocol = (dev: Device): 'SSH' | 'RDP' | null => {
    if (dev.connection_method === 'web' || dev.connection_method === 'none') return null;
    const platform = (dev.platform || '').toLowerCase();
    if (platform.includes('windows')) return 'RDP';
    return 'SSH'; 
  };

  // HTTP(S) management-page access is independent from the SSH terminal
  // transport.  A device can be SSH-capable without having an HTTP(S)
  // profile, and it must still expose the Web SSH terminal action.
  const hasHttpWebAccess = (dev: Device) => Boolean(
    dev.web_access_enabled || dev.web_http_enabled || dev.web_https_enabled,
  );

  const getSupportedProtocols = (dev: Device) => {
    const terminalProtocol = getTerminalProtocol(dev);
    const protocols: Array<'SSH' | 'RDP' | 'HTTP' | 'HTTPS'> = terminalProtocol ? [terminalProtocol] : [];
    if (dev.web_http_enabled) protocols.push('HTTP');
    if (dev.web_https_enabled) protocols.push('HTTPS');
    return protocols;
  };

  const getAllAccessMethods = (dev: Device): AllAccessMethod[] => {
    const methods: AllAccessMethod[] = [];
    const terminalProtocol = getTerminalProtocol(dev);
    if (terminalProtocol === 'SSH') {
      // A device with only SSH configured should not suggest a second login
      // surface that has not been configured for the asset. Keep Web SSH for
      // the combined SSH + HTTP(S) case, where the operator has an explicit
      // browser-access entry to choose from as well.
      methods.push('ssh-terminal');
      if (hasHttpWebAccess(dev)) methods.push('ssh-web');
    } else if (terminalProtocol === 'RDP') {
      methods.push('rdp');
    }
    if (dev.web_http_enabled) methods.push('http');
    if (dev.web_https_enabled) methods.push('https');
    return methods;
  };

  const getAllAccessMethodLabel = (method: AllAccessMethod) => {
    if (isZh) {
      return {
        'ssh-terminal': 'SSH 终端',
        'ssh-web': 'Web SSH',
        rdp: 'RDP',
        http: 'HTTP',
        https: 'HTTPS',
      }[method];
    }
    return {
      'ssh-terminal': 'SSH terminal',
      'ssh-web': 'Web SSH',
      rdp: 'RDP',
      http: 'HTTP',
      https: 'HTTPS',
    }[method];
  };

  const baseFilteredDevices = useMemo(() => {
    const list = Array.isArray(devices) ? devices : [];
    const query = (searchQuery || '').toLowerCase();
    
    return list.filter(d => {
      const terminalProtocol = getTerminalProtocol(d);
      const matchesCategory = activeCategory === 'ALL'
        || (activeCategory === 'WEB' ? hasHttpWebAccess(d) : terminalProtocol === activeCategory);
      const name = (d?.hostname || '').toLowerCase();
      const ip = (d?.ip_address || '').toLowerCase();
      const matchesSearch = name.includes(query) || ip.includes(query);
      return matchesCategory && matchesSearch;
    });
  }, [devices, searchQuery, activeCategory]);

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

  const nodeStats = {
    total: filteredDevices.length,
    online: filteredDevices.filter((device) => device.status === 'online').length,
    terminal: filteredDevices.filter((device) => Boolean(getTerminalProtocol(device))).length,
    web: filteredDevices.filter((device) => hasHttpWebAccess(device)).length,
  };

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
    const iconTone = node.kind === 'root'
      ? 'bg-cyan-50 text-cyan-600'
      : node.kind === 'site'
        ? 'bg-violet-50 text-violet-600'
        : node.kind === 'type'
          ? 'bg-amber-50 text-amber-600'
          : 'bg-emerald-50 text-emerald-600';
    return (
      <div key={node.id}>
        <div className="group relative flex items-center gap-1.5" style={{ paddingLeft: `${depth * 14}px` }}>
          <button
            type="button"
            onClick={() => toggleTreeNode(node)}
            className={`flex h-8 w-6 shrink-0 items-center justify-center rounded-lg transition-colors ${node.children.length ? 'text-slate-400 hover:bg-cyan-50 hover:text-cyan-700' : 'pointer-events-none text-transparent'}`}
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {node.children.length ? (expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <span className="w-3" />}
          </button>
          <button
            type="button"
            onClick={() => { setSelectedTreeKey(node.id); setCurrentPage(1); }}
            aria-current={selected ? 'page' : undefined}
            className={`flex min-w-0 flex-1 items-center gap-2 rounded-xl border px-2.5 py-2 text-left text-xs transition-all ${selected ? 'border-cyan-200 bg-gradient-to-r from-cyan-50 to-white font-semibold text-cyan-800 shadow-sm' : 'border-transparent text-slate-600 hover:border-slate-100 hover:bg-slate-50'}`}
          >
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${selected ? 'bg-cyan-100 text-cyan-700' : iconTone}`}>
              <Icon size={14} />
            </span>
            <span className="min-w-0 flex-1 truncate font-medium">{node.label}</span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold tabular-nums ${selected ? 'bg-white text-cyan-700 ring-1 ring-cyan-100' : 'bg-slate-100 text-slate-500'}`}>{node.count}</span>
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

  const openWebAccess = async (dev: Device, level: WebAccessLevel = 'normal', preferredScheme?: WebScheme) => {
    const assetId = String(dev.asset_id || '').trim();
    if (!assetId) {
      showToast(isZh ? '\u8be5\u8bbe\u5907\u5c1a\u672a\u5173\u8054\u7269\u7406\u8d44\u4ea7' : 'This device is not linked to a physical asset', 'info');
      return;
    }
    try {
      const token = localStorage.getItem('netops_token') || '';
      const response = await fetch(`/api/assets/${encodeURIComponent(assetId)}/web-profiles`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        cache: 'no-store',
      });
      const payload = await response.json().catch(() => ({}));
      const profiles = enabledWebProfiles(Array.isArray(payload?.items) ? payload.items : []);
      const matchingProfiles = preferredScheme
        ? profiles.filter(profile => profile.scheme.toLowerCase() === preferredScheme)
        : profiles;
      if (!response.ok || matchingProfiles.length === 0) {
        const protocolLabel = preferredScheme ? preferredScheme.toUpperCase() : 'HTTP/HTTPS';
        showToast(isZh ? `请先在资产中配置 ${protocolLabel} Web 入口` : `Configure a ${protocolLabel} Web entry for this asset first`, 'info');
        return;
      }
      setWebAccessTarget(dev);
      setWebAccessProfiles(matchingProfiles);
      setWebAccessProfileId(String(matchingProfiles[0].id || ''));
      setWebAccessLevel(level);
      setWebAccessReason('');
    } catch {
      showToast(isZh ? '\u65e0\u6cd5\u52a0\u8f7d Web \u5165\u53e3' : 'Unable to load Web entries', 'error');
    }
  };

  const requestWebAccess = async () => {
    const target = webAccessTarget;
    const assetId = String(target?.asset_id || '').trim();
    if (!target || !assetId || !webAccessProfileId) return;
    setWebAccessRequesting(true);
    try {
      await ensurePamWebAgent();
      const session = await createPamWebSession({
        assetId,
        profileId: webAccessProfileId,
        accessLevel: webAccessLevel,
        reason: webAccessReason,
      });
      await launchPamWebSession(session.session_token);
      showToast(isZh ? 'Web PAM \u4f1a\u8bdd\u5df2\u4ea4\u7531\u672c\u5730 Agent \u6253\u5f00' : 'Web PAM session opened by the local Agent', 'success');
      setWebAccessTarget(null);
      setWebAccessProfiles([]);
      setWebAccessProfileId('');
      setWebAccessReason('');
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error || '');
      showToast(
        message === 'WEB_AGENT_UPGRADE_REQUIRED'
          ? (isZh ? '\u5f53\u524d Agent \u6682\u4e0d\u652f\u6301 Web \u4f1a\u8bdd' : 'The current Agent does not support Web sessions yet')
          : (isZh ? `Web PAM \u4f1a\u8bdd\u542f\u52a8\u5931\u8d25\uff1a${message}` : `Unable to start Web PAM session: ${message}`),
        'error',
      );
    } finally {
      setWebAccessRequesting(false);
    }
  };

  const closeWebAccess = () => {
    if (webAccessRequesting) return;
    setWebAccessTarget(null);
    setWebAccessProfiles([]);
    setWebAccessProfileId('');
    setWebAccessReason('');
  };

  const closeMFAModal = () => {
    setShowMFAModal(false);
    setMfaTarget(null);
    resetMFAState();
  };

  const handleAccessRequest = async (dev: Device, appType: 'xshell' | 'web', identity: 'normal' | 'privileged', webScheme?: WebScheme) => {
    if (appType === 'xshell') {
      // Read the normalized configuration for the workstation running this browser.
      const { path: terminalPath, app: terminalType } = getLocalTerminalConfig();

      if (terminalType !== 'standard' && !terminalPath) {
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

    // Web access is a user-operated browser session. Normal/privileged are
    // audit labels only for now; the device page itself owns authentication.
    openWebAccess(dev, identity === 'privileged' ? 'admin' : 'normal', webScheme);
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

      const appName = TERMINAL_APP_LABELS[terminalType] || 'Terminal';

      showToast(
        isZh ? `正在拉起 ${appName}` : `Launching ${appName}`,
        'success'
      );

    } catch (err) {
      console.error('Local Terminal Agent launch failed', err);
      showToast(formatTerminalAgentError(err, isZh), 'error');
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
      const { path: terminalPath, app: terminalType } = getLocalTerminalConfig();
      if (terminalType !== 'standard' && !terminalPath) {
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

  const tableHeader = (label: string, align: 'left' | 'center' | 'right' = 'left') => (
    <th
      className="px-8 py-5 text-[10px] font-black uppercase tracking-[0.15em] text-slate-400"
      style={{ textAlign: align }}
    >
      {label}
    </th>
  );

  const renderAssetCell = (dev: Device) => (
    <td className="px-8 py-5">
      <div className="flex items-center gap-4">
        <div className={`relative flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border transition-all ${dev.status === 'online' ? 'border-cyan-100 bg-gradient-to-br from-cyan-50 to-sky-50 text-cyan-600 group-hover:shadow-md group-hover:shadow-cyan-100' : 'border-slate-200 bg-slate-50 text-slate-400'}`}>
          <Server className="h-5 w-5" />
          <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white ${dev.status === 'online' ? 'bg-emerald-500' : 'bg-slate-300'}`} />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className="truncate text-sm font-bold text-slate-800">{dev.hostname}</div>
            <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold ${dev.status === 'online' ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>
              {dev.status === 'online' ? (isZh ? '在线' : 'Online') : (isZh ? '离线' : 'Offline')}
            </span>
            <button
              type="button"
              aria-label={favoriteDeviceIds.includes(dev.id)
                ? (isZh ? `取消收藏 ${dev.hostname}` : `Remove ${dev.hostname} from favorites`)
                : (isZh ? `收藏 ${dev.hostname}` : `Add ${dev.hostname} to favorites`)}
              title={favoriteDeviceIds.includes(dev.id)
                ? (isZh ? '取消收藏' : 'Remove from favorites')
                : (isZh ? '加入收藏' : 'Add to favorites')}
              onClick={(event) => {
                event.stopPropagation();
                onToggleFavorite?.(dev);
              }}
              className={`rounded-md p-1 transition-colors ${favoriteDeviceIds.includes(dev.id) ? 'text-amber-500 hover:bg-amber-50' : 'text-slate-300 hover:bg-amber-50 hover:text-amber-500'}`}
            >
              <Star size={13} fill={favoriteDeviceIds.includes(dev.id) ? 'currentColor' : 'none'} />
            </button>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] font-semibold text-slate-400">
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 uppercase tracking-tight">{dev.platform || 'General Linux'}</span>
            {dev.vendor && <span className="truncate">{dev.vendor}</span>}
          </div>
        </div>
      </div>
    </td>
  );

  const renderAddressCell = (dev: Device) => (
    <td className="px-8 py-5">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="rounded-lg bg-slate-50 px-2 py-1 font-mono text-xs font-bold text-slate-600">{dev.ip_address}</span>
          <span className="font-mono text-[10px] font-semibold text-slate-400">:{dev.management_port || 22}</span>
        </div>
        <div className="flex items-center gap-1 text-[10px] font-medium text-slate-400">
          <MapPin className="h-3 w-3 text-violet-400" />
          <span className="max-w-[150px] truncate">{dev.site_name || dev.site || (isZh ? '未分配站点' : 'Unassigned site')}</span>
        </div>
      </div>
    </td>
  );

  const renderCapabilityBadges = (dev: Device) => (
    <div className="flex flex-wrap items-center justify-center gap-1.5">
      {getSupportedProtocols(dev).length > 0
        ? getSupportedProtocols(dev).map((protocol) => (
            <span
              key={protocol}
              className={`rounded-lg px-2.5 py-1 text-[10px] font-black uppercase tracking-wider ${protocol === 'SSH' ? 'bg-emerald-50 text-emerald-700' : protocol === 'RDP' ? 'bg-violet-50 text-violet-700' : 'bg-cyan-50 text-cyan-700'}`}
            >
              {protocol}
            </span>
          ))
        : <span className="text-[10px] font-semibold text-slate-300">—</span>}
    </div>
  );

  const renderWebEntryBadges = (dev: Device) => (
    <div className="flex flex-wrap items-center justify-center gap-1.5">
      {dev.web_http_enabled && <span className="rounded-lg bg-orange-50 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-orange-700">HTTP</span>}
      {dev.web_https_enabled && <span className="rounded-lg bg-cyan-50 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-cyan-700">HTTPS</span>}
      {!hasHttpWebAccess(dev) && <span className="text-[10px] font-semibold text-slate-300">—</span>}
    </div>
  );

  const renderTerminalActions = (dev: Device, protocol: 'SSH' | 'RDP') => (
    <div className="flex flex-nowrap items-center justify-center gap-2.5 whitespace-nowrap">
      <button
        onClick={() => handleAccessRequest(dev, 'xshell', 'normal')}
        className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[10px] font-black text-slate-600 transition-all hover:border-emerald-500 hover:bg-emerald-50 hover:text-emerald-600"
        title={protocol === 'RDP' ? (isZh ? '使用当前本地终端配置发起 RDP 访问' : 'Launch RDP access with the configured local client') : undefined}
      >
        {protocol === 'RDP' ? <Monitor className="h-3.5 w-3.5" /> : <Terminal className="h-3.5 w-3.5" />}
        {dev.normal_username || (isZh ? '普通' : 'user')}
      </button>
      <button
        onClick={() => handleAccessRequest(dev, 'xshell', 'privileged')}
        className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[10px] font-black text-slate-600 transition-all hover:border-orange-500 hover:bg-orange-50 hover:text-orange-600"
        title={protocol === 'RDP' ? (isZh ? '使用当前本地终端配置发起 RDP 特权访问' : 'Launch privileged RDP access with the configured local client') : undefined}
      >
        <Lock className="h-3.5 w-3.5" />
        {dev.admin_username || (isZh ? '特权' : 'admin')}
      </button>
    </div>
  );

  // HTTP/HTTPS management-page login. This is used by the WEB category and
  // by the corresponding method selected in ALL.
  const renderHttpWebActions = (dev: Device, scheme?: WebScheme) => {
    const enabled = scheme === 'http' ? dev.web_http_enabled : scheme === 'https' ? dev.web_https_enabled : hasHttpWebAccess(dev);
    if (!enabled) {
      return <span className="text-[10px] font-semibold text-slate-300">—</span>;
    }
    return (
      <div className="flex flex-nowrap items-center justify-center gap-2.5 whitespace-nowrap">
        <button
          onClick={() => handleAccessRequest(dev, 'web', 'normal', scheme)}
          className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[10px] font-black text-slate-600 transition-all hover:border-[#00bceb] hover:bg-cyan-50 hover:text-[#00bceb]"
        >
          <Globe className="h-3.5 w-3.5" />
          {dev.normal_username || (isZh ? '普通' : 'user')}
        </button>
        <button
          onClick={() => handleAccessRequest(dev, 'web', 'privileged', scheme)}
          className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[10px] font-black text-slate-600 transition-all hover:border-orange-500 hover:bg-orange-50 hover:text-orange-600"
        >
          <Lock className="h-3.5 w-3.5" />
          {dev.admin_username || (isZh ? '特权' : 'admin')}
        </button>
      </div>
    );
  };

  // Web SSH terminal login. The browser is only the terminal surface; the
  // backend session still connects to the device over SSH. This must not be
  // gated by HTTP(S) Web profiles.
  const renderSshWebActions = (dev: Device) => (
    <div className="flex flex-nowrap items-center justify-center gap-2.5 whitespace-nowrap">
      <button
        onClick={() => { void requestSession(dev, 'normal'); }}
        className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[10px] font-black text-slate-600 transition-all hover:border-[#00bceb] hover:bg-cyan-50 hover:text-[#00bceb]"
        title={isZh ? '在网页终端中通过 SSH 登录' : 'Open a browser terminal over SSH'}
      >
        <Globe className="h-3.5 w-3.5" />
        {dev.normal_username || (isZh ? '普通' : 'user')}
      </button>
      <button
        onClick={() => { void requestSession(dev, 'admin'); }}
        className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-[10px] font-black text-slate-600 transition-all hover:border-orange-500 hover:bg-orange-50 hover:text-orange-600"
        title={isZh ? '在网页终端中通过 SSH 发起特权登录' : 'Open a privileged browser terminal over SSH'}
      >
        <Lock className="h-3.5 w-3.5" />
        {dev.admin_username || (isZh ? '特权' : 'admin')}
      </button>
    </div>
  );

  // ALL is an aggregate view, so the selected access method is kept per row.
  // This prevents an HTTP/HTTPS-capable SSH asset from losing either its Web
  // SSH or management-page entry just because the user is viewing ALL. When
  // there is only one supported method, render its label directly instead of
  // making the operator open a one-item dropdown.
  const renderAllAccessActions = (dev: Device) => {
    const methods = getAllAccessMethods(dev);
    const selectedMethod = methods.includes(allAccessMethods[dev.id])
      ? allAccessMethods[dev.id]
      : methods[0];

    if (!selectedMethod) return null;

    const renderSelectedActions = () => {
      switch (selectedMethod) {
        case 'ssh-terminal':
          return renderTerminalActions(dev, 'SSH');
        case 'ssh-web':
          return renderSshWebActions(dev);
        case 'rdp':
          return renderTerminalActions(dev, 'RDP');
        case 'http':
          return renderHttpWebActions(dev, 'http');
        case 'https':
          return renderHttpWebActions(dev, 'https');
        default:
          return null;
      }
    };

    // Keep a dedicated, non-growing slot for the access-method indicator.
    // A native select has browser-owned internal sizing, so fixing only its
    // width is not enough to keep the neighbouring actions aligned with the
    // single-method rows. The outer slot gives both variants the same flex
    // basis while the static variant remains visibly non-interactive.
    const methodSlotStyle: React.CSSProperties = {
      flex: '0 0 92px',
      width: '92px',
      minWidth: '92px',
      maxWidth: '92px',
    };
    const methodControl = (
      <div className="box-border h-[30px] shrink-0" style={methodSlotStyle}>
        {methods.length > 1 ? (
          <select
            aria-label={isZh ? `${dev.hostname} 登录方式` : `${dev.hostname} access method`}
            value={selectedMethod}
            onChange={(event) => {
              const nextMethod = event.target.value as AllAccessMethod;
              setAllAccessMethods((current) => ({ ...current, [dev.id]: nextMethod }));
            }}
            className="box-border h-full w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-bold text-slate-600 outline-none transition-colors focus:border-[#00bceb] focus:ring-2 focus:ring-[#00bceb]/10"
          >
            {methods.map((method) => (
              <option key={method} value={method}>{getAllAccessMethodLabel(method)}</option>
            ))}
          </select>
        ) : (
          <span
            aria-label={isZh ? `${dev.hostname} 登录方式：${getAllAccessMethodLabel(selectedMethod)}` : `${dev.hostname} access method: ${getAllAccessMethodLabel(selectedMethod)}`}
            className="box-border inline-flex h-full w-full items-center justify-start gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-bold text-slate-600"
          >
            {selectedMethod === 'rdp' ? <Monitor className="h-3.5 w-3.5 shrink-0" /> : selectedMethod === 'http' || selectedMethod === 'https' || selectedMethod === 'ssh-web' ? <Globe className="h-3.5 w-3.5 shrink-0" /> : <Terminal className="h-3.5 w-3.5 shrink-0" />}
            <span className="truncate">{getAllAccessMethodLabel(selectedMethod)}</span>
          </span>
        )}
      </div>
    );

    return (
      <div
        className="flex min-w-[420px] flex-nowrap items-center justify-center gap-2 whitespace-nowrap"
        style={{ flex: '0 0 420px', width: '420px' }}
      >
        {methodControl}
        {renderSelectedActions()}
      </div>
    );
  };

  const renderAccessTable = () => {
    const emptyRow = (colSpan: number) => (
      <tr>
        <td colSpan={colSpan} className="py-16 text-center text-sm text-slate-400">
          {isZh ? '当前分类暂无可访问设备' : 'No accessible devices in this category'}
        </td>
      </tr>
    );
    const rows = (renderRow: (dev: Device) => React.ReactNode, colSpan: number) => (
      currentData.length ? currentData.map(renderRow) : emptyRow(colSpan)
    );

    if (activeCategory === 'WEB') {
      return (
        <DataTable className="text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-cyan-50/40">
              {tableHeader(isZh ? '资产信息' : 'Asset')}
              {tableHeader(isZh ? '连接地址' : 'Address')}
              {tableHeader(isZh ? 'Web 入口' : 'Web entries', 'center')}
              {tableHeader(isZh ? 'HTTP 登录' : 'HTTP login', 'center')}
              {tableHeader(isZh ? 'HTTPS 登录' : 'HTTPS login', 'center')}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows((dev) => (
              <tr key={dev.id} className="group transition-colors hover:bg-cyan-50/30">
                {renderAssetCell(dev)}
                {renderAddressCell(dev)}
                <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderWebEntryBadges(dev)}</td>
                <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderHttpWebActions(dev, 'http')}</td>
                <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderHttpWebActions(dev, 'https')}</td>
              </tr>
            ), 5)}
          </tbody>
        </DataTable>
      );
    }

    if (activeCategory === 'RDP') {
      return (
        <DataTable className="text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-violet-50/40">
              {tableHeader(isZh ? '资产信息' : 'Asset')}
              {tableHeader(isZh ? '连接地址' : 'Address')}
              {tableHeader(isZh ? '协议' : 'Protocol')}
              {tableHeader(isZh ? 'RDP 登录' : 'RDP login', 'center')}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows((dev) => (
              <tr key={dev.id} className="group transition-colors hover:bg-violet-50/30">
                {renderAssetCell(dev)}
                {renderAddressCell(dev)}
                <td className="px-8 py-5"><span className="rounded-lg bg-violet-50 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-violet-700">RDP</span></td>
                <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderTerminalActions(dev, 'RDP')}</td>
              </tr>
            ), 4)}
          </tbody>
        </DataTable>
      );
    }

    if (activeCategory === 'SSH') {
      return (
        <DataTable className="text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-emerald-50/40">
              {tableHeader(isZh ? '资产信息' : 'Asset')}
              {tableHeader(isZh ? '连接地址' : 'Address')}
              {tableHeader(isZh ? '协议' : 'Protocol')}
              {tableHeader(isZh ? '终端登录（本地）' : 'Terminal login', 'center')}
              {tableHeader(isZh ? 'Web 终端登录' : 'Web terminal login', 'center')}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows((dev) => (
              <tr key={dev.id} className="group transition-colors hover:bg-emerald-50/30">
                {renderAssetCell(dev)}
                {renderAddressCell(dev)}
                <td className="px-8 py-5"><span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-emerald-700">SSH</span></td>
                <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderTerminalActions(dev, 'SSH')}</td>
                <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderSshWebActions(dev)}</td>
              </tr>
            ), 5)}
          </tbody>
        </DataTable>
      );
    }

    return (
      <DataTable className="text-left">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/70">
            {tableHeader(isZh ? '资产信息' : 'Asset')}
            {tableHeader(isZh ? '连接地址' : 'Address')}
            {tableHeader(isZh ? '接入能力' : 'Capabilities', 'center')}
            {tableHeader(isZh ? '登录方式' : 'Access method', 'center')}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows((dev) => (
            <tr key={dev.id} className="group transition-colors hover:bg-slate-50">
              {renderAssetCell(dev)}
              {renderAddressCell(dev)}
              <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>{renderCapabilityBadges(dev)}</td>
              <td className="px-8 py-5 text-center" style={{ textAlign: 'center' }}>
                {renderAllAccessActions(dev)}
              </td>
            </tr>
          ), 4)}
        </tbody>
      </DataTable>
    );
  };

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
            {(['ALL', 'SSH', 'RDP', 'WEB'] as AccessCategory[]).map((category) => (
              <button
                key={category}
                onClick={() => { setActiveCategory(category); setCurrentPage(1); }}
                className={`px-5 py-2 rounded-xl text-[10px] font-black tracking-widest transition-all uppercase ${
                  activeCategory === category
                  ? 'bg-[#00bceb] text-white shadow-lg shadow-[#00bceb]/20'
                  : 'bg-white text-slate-400 border border-slate-200 hover:border-[#00bceb] hover:text-[#00bceb]'
                }`}
              >
                {category}
              </button>
            ))}
          </div>
        }
      />

      {/* Table Section */}
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
          {[
            { label: isZh ? '当前节点' : 'Current nodes', value: nodeStats.total, note: selectedTreeLabel, icon: Database, tone: 'cyan' },
            { label: isZh ? '在线节点' : 'Online nodes', value: nodeStats.online, note: isZh ? '可直接发起访问' : 'Ready to access', icon: Activity, tone: 'emerald' },
            { label: isZh ? '终端接入' : 'Terminal access', value: nodeStats.terminal, note: 'SSH / RDP', icon: Terminal, tone: 'violet' },
            { label: isZh ? 'Web 入口' : 'Web entries', value: nodeStats.web, note: 'HTTP / HTTPS', icon: Wifi, tone: 'amber' },
          ].map((item) => {
            const StatIcon = item.icon;
            const tone = item.tone === 'emerald'
              ? 'border-emerald-100 bg-emerald-50 text-emerald-600'
              : item.tone === 'violet'
                ? 'border-violet-100 bg-violet-50 text-violet-600'
                : item.tone === 'amber'
                  ? 'border-amber-100 bg-amber-50 text-amber-600'
                  : 'border-cyan-100 bg-cyan-50 text-cyan-600';
            return (
              <div key={item.label} className="flex min-w-0 items-center gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-3 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md">
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${tone}`}>
                  <StatIcon size={18} />
                </span>
                <div className="min-w-0">
                  <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">{item.label}</div>
                  <div className="mt-0.5 flex items-baseline gap-2">
                    <span className="text-xl font-black tabular-nums text-slate-800">{item.value}</span>
                    <span className="truncate text-[10px] font-medium text-slate-400">{item.note}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <div className={`grid min-h-[calc(100vh-250px)] grid-cols-1 gap-4 ${accessTreeCollapsed ? 'xl:grid-cols-[56px_minmax(0,1fr)]' : 'xl:grid-cols-[290px_minmax(0,1fr)]'}`}>
          <aside className={`relative rounded-2xl border border-slate-200 bg-white shadow-sm ${accessTreeCollapsed ? 'p-2' : 'p-3'}`}>
            <div className={`mb-3 border-b border-slate-100 px-2 pb-3 ${accessTreeCollapsed ? 'hidden' : ''}`}>
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-50 to-violet-50 text-cyan-600">
                  <FolderTree size={16} />
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-bold text-slate-800">{isZh ? '节点分类' : 'Node groups'}</div>
                  <div className="mt-0.5 truncate text-[11px] text-slate-400">{isZh ? '按站点、类型和角色定位' : 'Find by site, type, or role'}</div>
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-xl bg-slate-50 px-2.5 py-2 text-[10px] font-semibold text-slate-500">
                <span>{isZh ? '已筛选节点' : 'Filtered nodes'}</span>
                <span className="font-mono font-bold text-cyan-700">{baseFilteredDevices.length}</span>
              </div>
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
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-gradient-to-r from-white to-cyan-50/30 px-5 py-3.5 text-xs text-slate-500">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-50 text-cyan-600"><Database size={14} /></span>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-400">{isZh ? '节点清单' : 'Node inventory'}</div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span>{isZh ? '当前分类' : 'Current branch'}:</span>
                  <span className="font-semibold text-cyan-700">{selectedTreeLabel}</span>
                </div>
              </div>
              <span className="ml-auto tabular-nums">{totalCount} {isZh ? '台设备' : 'devices'}</span>
            </div>
            <div className="min-h-0 overflow-auto">
              {renderAccessTable()}
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

      <WebAccessRequestModal
        isOpen={Boolean(webAccessTarget)}
        asset={webAccessTarget ? { hostname: webAccessTarget.hostname, management_ip: webAccessTarget.ip_address } : null}
        profiles={webAccessProfiles}
        accessLevel={webAccessLevel}
        profileId={webAccessProfileId}
        reason={webAccessReason}
        requesting={webAccessRequesting}
        language={language}
        onAccessLevelChange={setWebAccessLevel}
        onProfileChange={setWebAccessProfileId}
        onReasonChange={setWebAccessReason}
        onClose={closeWebAccess}
        onSubmit={() => void requestWebAccess()}
      />

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
