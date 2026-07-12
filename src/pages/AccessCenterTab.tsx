import React, { useState, useMemo, useEffect } from 'react';
import { 
  Search, Terminal, Monitor, Lock, Info, 
  Copy, ShieldCheck, RefreshCw, ChevronLeft, ChevronRight,
  Database, Server, Cpu, Key, Globe, X, Send, ChevronDown, UserCheck, Eye, EyeOff
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import TerminalWindow from '../components/access/TerminalWindow';
import Pagination from '../components/Pagination';
import PageHero from '../components/PageHero';

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
}

interface User {
  id: string;
  username: string;
  role: string;
  avatar_url?: string;
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
  const [pageSize, setPageSize] = useState(10);
  
  // --- MFA Logic ---
  const [showMFAModal, setShowMFAModal] = useState(false);
  const [fixedPassword, setFixedPassword] = useState('');
  const [showFixedPassword, setShowFixedPassword] = useState(false);
  const [dynamicCode, setDynamicCode] = useState('');
  const [mfaNonce, setMfaNonce] = useState('');
  const [mfaTarget, setMfaTarget] = useState<{device: Device, appType: 'xshell' | 'web', identity: 'normal' | 'privileged'} | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [approvers, setApprovers] = useState<User[]>([]);
  const [selectedApproverId, setSelectedApproverId] = useState('');

  // Real current username from session
  const [currentUsername, setCurrentUsername] = useState<string>('');

  // Countdown timer for MFA code
  useEffect(() => {
    let timer: any;
    if (countdown > 0) {
      timer = setInterval(() => setCountdown(c => c - 1), 1000);
    }
    return () => clearInterval(timer);
  }, [countdown]);

  // Fetch approvers (Admins only, exclude self)
  useEffect(() => {
    const fetchApprovers = async () => {
      try {
        const token = localStorage.getItem('netops_token');
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        
        // 1. Get real current user from session
        const sessionRes = await fetch('/api/session', { headers });
        let loggedInUser = '';
        if (sessionRes.ok) {
          const sessionData = await sessionRes.json();
          loggedInUser = sessionData.user?.username || '';
          setCurrentUsername(loggedInUser);
        }

        // 2. Fetch all users
        const res = await fetch('/api/users', { headers });
        const data = await res.json();
        
        if (Array.isArray(data)) {
          // Strict: only Administrator role, never the current user
          const admins = data.filter((u: any) => u.role === 'Administrator' && u.username !== loggedInUser);
          setApprovers(admins);
          if (admins.length > 0) setSelectedApproverId(admins[0].id);
        }
      } catch (err) {
        console.error('Failed to fetch approvers', err);
      }
    };
    fetchApprovers();
  }, []);

  const getProtocol = (dev: Device) => {
    const platform = (dev.platform || '').toLowerCase();
    if (platform.includes('windows')) return 'RDP';
    return 'SSH'; 
  };

  const filteredDevices = useMemo(() => {
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

  const totalCount = filteredDevices.length;
  const totalPages = Math.ceil(totalCount / pageSize);
  const currentData = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredDevices.slice(start, start + pageSize);
  }, [filteredDevices, currentPage, pageSize]);

  // Reset all MFA-related state to a clean slate (but keep approver selection).
  const resetMFAState = () => {
    setFixedPassword('');
    setShowFixedPassword(false);
    setDynamicCode('');
    setMfaNonce('');
    setCountdown(0);
    setIsSending(false);
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

    // MFA verification for privileged access — still goes through backend
    if (level === 'admin') {
      if (!mfaCode || !fixedPw) {
        openMFAModal({ device: dev, appType: 'xshell', identity: 'privileged' });
        return;
      }
      try {
        const res = await fetch('/api/system/launch-terminal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            app_type: terminalType,
            path: '__mfa_verify_only__',   // 仅做 MFA 校验，不实际启动
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
        // MFA passed — fall through to local launch below
      } catch {
        showToast(isZh ? 'MFA 验证请求失败' : 'MFA verification failed', 'error');
        return;
      }
    } else {
      // Normal level: Fetch password from backend first (which also writes the audit log)
      try {
        const res = await fetch('/api/system/launch-terminal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            app_type: terminalType,
            path: '__client_side_launch__',
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
      } catch (err) {
        console.error('Failed to fetch password for normal user launch', err);
      }
    }

    // ── 纯前端本地启动：通过 URI scheme 调起 Windows 客户端 ──
    // 后端在 Linux 容器里无法执行 Windows 程序，必须由浏览器直接触发。
    // 如果用户在个人设置里选择了特定的本地终端工具（Xshell, PuTTY 等），则通过 nexora:// 协议调起，
    // 否则直接使用系统默认的 ssh:// 协议。
    try {
      let uri = '';
      if (terminalType !== 'standard') {
        const isSsl = window.location.protocol === 'https:' ? '1' : '0';
        uri = `nexora://${window.location.host}?token=${sessionToken}&client=${terminalType}&path=${encodeURIComponent(terminalPath || '')}&ssl=${isSsl}`;
      } else {
        uri = `ssh://${encodeURIComponent(user)}@${host}:${port}`;
      }

      // 用户主动点击触发的 <a> 元素 click，浏览器会识别为用户行为，不会拦截
      // （iframe.src 触发外部协议在 Chrome/Edge 中会被静默拦截）
      const linker = document.createElement('a');
      linker.href = uri;
      linker.style.display = 'none';
      // target=_self 避免新开空白页；rel 防止任何 referrer 泄漏
      linker.rel = 'noopener noreferrer';
      document.body.appendChild(linker);
      linker.click();
      setTimeout(() => {
        try { document.body.removeChild(linker); } catch {}
      }, 1000);

      const appName = terminalType === 'standard' ? 'SSH' : terminalType === 'xshell' ? 'Xshell' : terminalType === 'putty' ? 'PuTTY' : terminalType === 'securecrt' ? 'SecureCRT' : terminalType === 'mobaxterm' ? 'MobaXterm' : 'Terminal';

      showToast(
        isZh ? `正在拉起 ${appName}` : `Launching ${appName}`,
        'success'
      );

    } catch (err) {
      showToast(isZh ? '调起本地客户端失败，请检查浏览器是否允许打开外部程序' : 'Failed to launch local client — check browser permissions', 'error');
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
    const nonce = mfaNonce;

    if (target.appType === 'xshell') {
      const terminalPath = localStorage.getItem('local_terminal_path') || '';
      const terminalType = localStorage.getItem('terminal_app') || 'xshell';
      if (!terminalPath) {
        showToast(isZh ? '请先在个人信息中配置终端路径' : 'Please configure terminal path in Profile first', 'info');
        return;
      }
      closeMFAModal();
      launchLocalTerminal(target.device, terminalPath, terminalType, 'admin', code, pin, nonce);
      return;
    }

    // Privileged web login via PAM Session Gateway
    closeMFAModal();
    requestSession(target.device, 'admin', code, pin, nonce);
  };

  const requestSession = async (dev: Device, accessLevel: 'normal' | 'admin', mfaCode?: string, fixedPw?: string, mfaNonce?: string) => {
    const assetId = dev.asset_id || dev.id; // Fallback to id if asset_id is not mapped in UI properly yet
    
    try {
      const res = await fetch('/api/pam/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
        window.open(`/terminal?session=${result.session_token}&hostname=${encodeURIComponent(dev.hostname || 'Terminal')}`, '_blank');
      }
    } catch (err) {
      showToast('Session request failed', 'error');
    }
  };

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
        <div className="bg-white border border-slate-200 rounded-[2rem] overflow-hidden shadow-sm">
          <table className="w-full text-left border-collapse">
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
              {currentData.map((dev) => (
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
          </table>
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

      {/* MFA Modal with Approver Selection */}
      <AnimatePresence>
        {showMFAModal && (
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
