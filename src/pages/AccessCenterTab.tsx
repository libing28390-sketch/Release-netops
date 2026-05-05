import React, { useState, useMemo } from 'react';
import { 
  Search, Terminal, Monitor, Lock, Info, 
  Copy, ShieldCheck, RefreshCw, ChevronLeft, ChevronRight,
  Database, Server, Cpu, Key
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface Device {
  id: string;
  name: string;
  ip_address: string;
  status: 'online' | 'offline';
  platform?: string;
  normal_username?: string;
  normal_password?: string;
  admin_username?: string;
  admin_password?: string;
  tags?: string[];
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
  const [mfaCode, setMfaCode] = useState('');
  const [fixedPassword, setFixedPassword] = useState('');
  const [mfaTarget, setMfaTarget] = useState<{device: Device, appType: string} | null>(null);
  const [isSending, setIsSending] = useState(false);

  // Helper to determine protocol
  const getProtocol = (dev: Device) => {
    const platform = (dev.platform || '').toLowerCase();
    if (platform.includes('windows')) return 'RDP';
    if (platform.includes('linux') || platform.includes('ubuntu') || platform.includes('centos')) return 'SSH';
    if (platform.includes('cisco') || platform.includes('huawei') || platform.includes('h3c')) return 'SSH';
    return 'SSH'; 
  };

  const filteredDevices = useMemo(() => {
    const list = Array.isArray(devices) ? devices : [];
    const query = (searchQuery || '').toLowerCase();
    
    return list.filter(d => {
      const proto = getProtocol(d);
      const matchesProtocol = activeProtocol === 'ALL' || proto === activeProtocol;
      const name = (d?.name || '').toLowerCase();
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

  const requestMFACode = async (dev: Device, appType: string, silent = false) => {
    setIsSending(true);
    try {
      const res = await fetch('/api/system/request-mfa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: 'current_user', username: 'Admin' })
      });
      const result = await res.json();
      if (result.success) {
        showToast(result.message, 'success');
        if (!silent) {
          setMfaTarget({ device: dev, appType });
          setShowMFAModal(true);
        }
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
    if (!mfaCode || mfaCode.length !== 6) {
      showToast(isZh ? '请输入6位动态验证码' : 'Enter 6-digit code', 'warning');
      return;
    }
    if (!fixedPassword) {
      showToast(isZh ? '请输入固定密码' : 'Enter fixed password', 'warning');
      return;
    }
    if (mfaTarget) {
      launchTerminal(mfaTarget.device, mfaTarget.appType, 'privileged', mfaCode, fixedPassword);
    }
  };

  const launchTerminal = async (dev: Device, appType: string, identity: 'normal' | 'privileged', code?: string, fixedPw?: string) => {
    const user = identity === 'normal' ? (dev.normal_username || 'user') : (dev.admin_username || 'admin');
    const password = identity === 'normal' ? dev.normal_password : dev.admin_password;
    
    const path = localStorage.getItem('local_terminal_path');
    if (!path) {
      showToast(isZh ? '请先配置终端路径' : 'Configure path in Profile', 'warning');
      return;
    }

    try {
      const res = await fetch('/api/system/launch-terminal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          path, app_type: appType, host: dev.ip_address, user, password,
          is_privileged: identity === 'privileged',
          mfa_code: code,
          fixed_password: fixedPw,
          user_id: 'current_user'
        })
      });
      const result = await res.json();
      if (result.success) {
        if (identity === 'privileged') {
          setShowMFAModal(false);
          setMfaCode('');
          setFixedPassword('');
        }
      } else {
        showToast(result.error, 'error');
      }
    } catch (err) {
      showToast('Launch failed', 'error');
    }
  };

  return (
    <div className="flex flex-col h-full bg-white animate-in fade-in duration-500 overflow-hidden">
      {/* Header */}
      <div className="bg-slate-50/50 border-b border-slate-100 p-6 space-y-6 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-blue-600 text-white rounded-xl shadow-lg shadow-blue-600/20">
              <Database className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-xl font-black text-slate-800 tracking-tight">接入中心</h2>
              <div className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-0.5 flex items-center gap-2">
                <span className="flex h-2 w-2 rounded-full bg-emerald-500"></span>
                {totalCount} Total Devices
              </div>
            </div>
          </div>

          <div className="relative w-80 group">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300 group-focus-within:text-blue-500 transition-colors" />
            <input
              type="text"
              placeholder="搜索资产..."
              className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl shadow-sm outline-none transition-all text-sm font-medium"
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          {['ALL', 'SSH', 'RDP', 'TELNET', 'VNC'].map((proto) => (
            <button
              key={proto}
              onClick={() => { setActiveProtocol(proto); setCurrentPage(1); }}
              className={`px-5 py-2 rounded-xl text-xs font-black tracking-widest transition-all ${
                activeProtocol === proto 
                ? 'bg-blue-600 text-white shadow-lg' 
                : 'bg-white text-slate-400 border border-slate-200 hover:text-blue-500'
              }`}
            >
              {proto}
            </button>
          ))}
        </div>
      </div>

      {/* List Body */}
      <div className="flex-1 overflow-y-auto p-6 min-h-0 custom-scrollbar">
        <div className="bg-white border border-slate-100 rounded-[2rem] overflow-hidden shadow-sm">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/50 border-b border-slate-100">
                <th className="px-6 py-4 text-[10px] font-black text-slate-400 uppercase tracking-widest">资产信息</th>
                <th className="px-6 py-4 text-[10px] font-black text-slate-400 uppercase tracking-widest">网络地址</th>
                <th className="px-6 py-4 text-[10px] font-black text-slate-400 uppercase tracking-widest">登录类型</th>
                <th className="px-6 py-4 text-[10px] font-black text-slate-400 uppercase tracking-widest">状态</th>
                <th className="px-6 py-4 text-[10px] font-black text-slate-400 uppercase tracking-widest text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {currentData.map((dev) => (
                <tr key={dev.id} className="hover:bg-blue-50/30 transition-colors group">
                  <td className="px-6 py-5">
                    <div className="flex items-center gap-3">
                      <Server className="w-4 h-4 text-slate-400" />
                      <div>
                        <div className="text-sm font-bold text-slate-800">{dev.name}</div>
                        <div className="text-[10px] text-slate-400 font-medium">{dev.platform}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-5 font-mono text-sm text-slate-500">{dev.ip_address}</td>
                  <td className="px-6 py-5">
                    <span className="px-2 py-1 bg-slate-100 text-slate-500 text-[10px] font-black rounded uppercase">
                      {getProtocol(dev)}
                    </span>
                  </td>
                  <td className="px-6 py-5">
                    <div className={`flex items-center gap-1.5 text-[10px] font-black uppercase ${
                      dev.status === 'online' ? 'text-emerald-500' : 'text-slate-300'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${dev.status === 'online' ? 'bg-emerald-500 animate-pulse' : 'bg-slate-200'}`} />
                      {dev.status}
                    </div>
                  </td>
                  <td className="px-6 py-5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button 
                        onClick={() => launchTerminal(dev, 'xshell', 'normal')}
                        className="p-2 bg-slate-50 hover:bg-emerald-500 text-slate-400 hover:text-white rounded-xl transition-all"
                      >
                        <Terminal className="w-4 h-4" />
                      </button>
                      <button 
                        onClick={() => requestMFACode(dev, 'xshell')}
                        className="px-3 py-1.5 bg-slate-50 hover:bg-orange-500 text-orange-500 hover:text-white text-[10px] font-black rounded-lg transition-all flex items-center gap-1.5"
                      >
                        <ShieldCheck className="w-3.5 h-3.5" />
                        PRIVILEGED
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="px-6 py-4 border-t border-slate-100 flex items-center justify-between">
        <span className="text-xs text-slate-400 font-bold uppercase tracking-widest">
          {totalCount} Total Entries
        </span>
        <div className="flex items-center gap-2">
          <button 
            disabled={currentPage === 1}
            onClick={() => setCurrentPage(prev => prev - 1)}
            className="p-1.5 rounded-lg border border-slate-200 text-slate-400 disabled:opacity-20"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs font-black text-slate-600 px-2">{currentPage} / {totalPages || 1}</span>
          <button 
            disabled={currentPage === totalPages || totalPages === 0}
            onClick={() => setCurrentPage(prev => prev + 1)}
            className="p-1.5 rounded-lg border border-slate-200 text-slate-400 disabled:opacity-20"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* MFA Modal with Two-Factor Inputs */}
      <AnimatePresence>
        {showMFAModal && (
          <div className="fixed inset-0 z-[1000] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
            <motion.div 
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="w-full max-w-[360px] bg-white rounded-[2.5rem] shadow-2xl overflow-hidden p-8"
            >
              <div className="text-center mb-8">
                <div className="w-14 h-14 bg-orange-50 text-orange-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
                  <ShieldCheck className="w-8 h-8" />
                </div>
                <h3 className="text-xl font-black text-slate-800 tracking-tight">特权访问授权</h3>
                <p className="text-slate-400 text-[10px] uppercase font-bold tracking-widest mt-1">Multi-Factor Authentication</p>
              </div>

              <div className="space-y-6">
                <div>
                  <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2 block ml-1">固定密码 (6位)</label>
                  <div className="relative">
                    <Key className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300" />
                    <input 
                      type="password"
                      maxLength={6}
                      value={fixedPassword}
                      onChange={(e) => setFixedPassword(e.target.value)}
                      className="w-full pl-10 pr-4 py-3 bg-slate-50 border border-slate-100 rounded-xl font-bold tracking-widest outline-none focus:border-orange-400 transition-all"
                      placeholder="••••••"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2 block ml-1">飞书动态验证码</label>
                  <input 
                    type="text"
                    maxLength={6}
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value)}
                    className="w-full py-4 bg-slate-50 border border-slate-100 rounded-xl text-center text-2xl font-black tracking-[0.4em] outline-none focus:border-orange-400 transition-all"
                    placeholder="000000"
                  />
                </div>

                <div className="pt-2">
                  <button 
                    onClick={handleMFAVerify}
                    className="w-full py-4 bg-orange-500 text-white font-black rounded-xl hover:bg-orange-600 shadow-lg shadow-orange-500/30 transition-all text-sm uppercase tracking-widest"
                  >
                    验证并登录
                  </button>
                  <button 
                    onClick={() => setShowMFAModal(false)}
                    className="w-full py-3 mt-2 text-slate-400 font-bold hover:text-slate-600 transition-colors text-xs"
                  >
                    取消
                  </button>
                </div>

                <div className="flex justify-center border-t border-slate-50 pt-4">
                  <button 
                    onClick={() => requestMFACode(mfaTarget!.device, mfaTarget!.appType, true)}
                    disabled={isSending}
                    className="flex items-center gap-2 text-[10px] font-black text-blue-500 hover:text-blue-600 disabled:text-slate-300 uppercase tracking-widest"
                  >
                    <RefreshCw className={`w-3 h-3 ${isSending ? 'animate-spin' : ''}`} />
                    {isSending ? 'Sending...' : 'Resend Feishu Code'}
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
