import React, { useState, useMemo, useEffect } from 'react';
import { 
  Search, Terminal, Monitor, Lock, Info, 
  Copy, ShieldCheck, RefreshCw, ChevronLeft, ChevronRight,
  Database, Server, Cpu, Key, Globe, X, Send, ChevronDown, UserCheck
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import TerminalWindow from '../components/access/TerminalWindow';
import Pagination from '../components/Pagination';

interface Device {
  id: string;
  asset_id?: string;
  hostname: string;
  ip_address: string;
  status: 'online' | 'offline';
  platform?: string;
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
  const [activeProtocol, setActiveProtocol] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  
  // --- MFA Logic ---
  const [showMFAModal, setShowMFAModal] = useState(false);
  const [fixedPassword, setFixedPassword] = useState('');
  const [dynamicCode, setDynamicCode] = useState('');
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

  const handleAccessRequest = async (dev: Device, appType: 'xshell' | 'web', identity: 'normal' | 'privileged') => {
    if (appType === 'xshell') {
      // 1. Get saved path from Profile Settings (localStorage keys: local_terminal_path, terminal_app)
      let terminalPath = localStorage.getItem('local_terminal_path');
      let terminalType = localStorage.getItem('terminal_app') || 'xshell';

      if (!terminalPath || terminalPath === '') {
        showToast(isZh ? '请先在个人信息中配置终端路径' : 'Please configure terminal path in Profile first', 'info');
        return;
      }

      // 2. Resolve identity and trigger launch
      try {
        const res = await fetch('/api/system/launch-terminal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            app_type: terminalType,
            path: terminalPath,
            host: dev.ip_address,
            user: identity === 'privileged' ? (dev.admin_username || 'root') : (dev.normal_username || 'user'),
          })
        });
        const result = await res.json();
        if (result.success) {
          showToast(isZh ? '正在拉起本地客户端...' : 'Launching native client...', 'success');
        } else {
          showToast(result.error || 'Launch failed', 'error');
        }
      } catch (err) {
        showToast('Native launch request failed', 'error');
      }
      return;
    }

    if (identity === 'normal') {
      requestSession(dev, 'normal');
      return;
    }

    // Privileged: require MFA
    setMfaTarget({ device: dev, appType: 'web', identity });
    setFixedPassword('');
    setDynamicCode('');
    setShowMFAModal(true);
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
    
    if (mfaTarget) {
      // Privileged web login via PAM Session Gateway
      requestSession(mfaTarget.device, 'admin', dynamicCode, fixedPassword);
      setShowMFAModal(false);
    }
  };

  const requestSession = async (dev: Device, accessLevel: 'normal' | 'admin', mfaCode?: string, fixedPw?: string) => {
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
    <div className="flex flex-col h-full bg-[#f8fafc] animate-in fade-in duration-500 overflow-hidden text-slate-700 font-sans">
      {/* Header Section */}
      <div className="bg-white border-b border-slate-200 p-6 shadow-sm shrink-0">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-[#00bceb] text-white rounded-xl flex items-center justify-center shadow-lg shadow-[#00bceb]/20">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">
                {isZh ? '操作工作台' : 'Operation Workspace'}
              </h1>
              <p className="text-sm text-slate-500">
                {isZh ? '受控访问、动态授权及安全合规' : 'Controlled access, dynamic authorization, and security compliance'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
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
          </div>
        </div>

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
      </div>

      {/* Table Section */}
      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        <div className="bg-white border border-slate-200 rounded-[2rem] overflow-hidden shadow-sm">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/50 border-b border-slate-200">
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em]">资产信息</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em]">网络地址</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em]">协议类型</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-400 uppercase tracking-[0.15em] text-right">终端登录 (本地)</th>
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
          <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-slate-900/70 backdrop-blur-md">
            <motion.div 
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              className="w-full max-w-[460px] bg-white rounded-[3rem] shadow-2xl overflow-hidden border border-slate-100"
            >
              <div className="bg-slate-50 border-b border-slate-100 px-8 py-6 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-orange-100 text-orange-600 rounded-2xl flex items-center justify-center shadow-inner">
                    <ShieldCheck className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="font-bold text-slate-800 tracking-tight">资产特权访问授权</h3>
                    <p className="text-[9px] text-slate-400 font-black uppercase tracking-widest mt-0.5">Dual-Control Audit required</p>
                  </div>
                </div>
                <button onClick={() => setShowMFAModal(false)} className="p-2 hover:bg-white rounded-xl transition-colors text-slate-300 hover:text-slate-500">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="p-10 space-y-8">
                {/* 1. Approver Selection */}
                <div className="space-y-3">
                  <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest ml-1">第一步：选择授权审批人</label>
                  <div className="relative group">
                    <UserCheck className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300 group-focus-within:text-[#00bceb]" />
                    <select 
                      value={selectedApproverId}
                      onChange={(e) => setSelectedApproverId(e.target.value)}
                      className="w-full pl-11 pr-10 py-4 bg-slate-50 border border-slate-100 rounded-2xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-sm font-bold text-slate-700 appearance-none cursor-pointer"
                    >
                      <option value="" disabled>请选择具备授权权限的管理员...</option>
                      {approvers.map(u => (
                        <option key={u.id} value={u.id}>{u.username} (Administrator)</option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
                  </div>
                </div>

                {/* Step 2 & 3: Fixed Password & Dynamic Code (Same Row) */}
                <div className="flex gap-4">
                  <div className="flex-1 space-y-3">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest ml-1">第二步：个人固定码</label>
                    <div className="relative group">
                      <Key className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300 group-focus-within:text-[#00bceb]" />
                      <input 
                        type="password"
                        maxLength={6}
                        value={fixedPassword}
                        onChange={(e) => setFixedPassword(e.target.value.replace(/\D/g, ''))}
                        className="w-full pl-11 pr-4 py-4 bg-slate-50 border border-slate-100 rounded-2xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-xl font-black tracking-[0.4em] text-slate-800 placeholder:text-slate-200"
                        placeholder="••••••"
                      />
                    </div>
                  </div>

                  <div className="flex-1 space-y-3">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest ml-1">第三步：动态授权码</label>
                    <div className="flex gap-2">
                      <input 
                        type="text"
                        maxLength={6}
                        value={dynamicCode}
                        onChange={(e) => setDynamicCode(e.target.value.replace(/\D/g, ''))}
                        className="w-full px-4 py-4 bg-slate-50 border border-slate-100 rounded-2xl outline-none focus:border-[#00bceb] focus:bg-white focus:ring-4 focus:ring-[#00bceb]/5 transition-all text-xl font-black tracking-[0.4em] text-center text-slate-800 placeholder:text-slate-200"
                        placeholder="000000"
                      />
                      <button 
                        onClick={sendMFACode}
                        disabled={isSending || countdown > 0 || !selectedApproverId}
                        className="px-4 bg-[#00bceb] text-white rounded-2xl font-black text-[10px] uppercase tracking-widest hover:bg-[#00a5d0] disabled:bg-slate-100 disabled:text-slate-300 transition-all flex items-center gap-1 whitespace-nowrap shadow-xl shadow-[#00bceb]/10"
                        title={isZh ? '发送至审批人' : 'Send to approver'}
                      >
                        {countdown > 0 ? `${countdown}s` : <Send className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="pt-6 space-y-4">
                  <button 
                    onClick={handleMFAVerify}
                    className="w-full py-5 bg-slate-900 text-white font-black rounded-[1.5rem] hover:bg-black shadow-2xl shadow-slate-900/20 transition-all flex items-center justify-center gap-3 text-sm uppercase tracking-widest"
                  >
                    解锁并验证身份
                  </button>
                  <p className="text-[9px] text-center text-slate-400 leading-relaxed font-bold">
                    * 验证码将发送至选中审批人的飞书，请向其获取。<br/>
                    本次操作将记录于特权访问审计日志中。
                  </p>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
